"""Durable state: SQLite for indexed facts, the filesystem for payloads.

Two stores, deliberately:

* **`hub.db`** — `nodes`, `checks`, `sources`, `subscriptions`, `publishes`.
  Queryable, but never on the hot path; the API does not open it at all.
* **`data/gen/<id>/`** — immutable payload directories plus an NDJSON event
  log. A generation is content-addressed, so re-publishing identical content is
  a no-op and rolling back is a pointer change rather than a re-render.

The `gen-current` pointer is the only mutable thing an HTTP reader trusts, and
it is swapped with `os.replace`, so a reader sees the old value or the new one.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional



def _generation_mtime(path: Path) -> tuple[float, str]:
    """Sort key for `retain`: newest first, with the name as a tie-break.

    The tie-break matters because several generations can be written inside the
    same filesystem timestamp resolution, and a non-deterministic retention
    order makes both tests and rollback unpredictable.
    """
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (mtime, path.name)


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #


class Store:
    """Filesystem layout: SQLite for indexed state, NDJSON for the fact log."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.data = self.root / "data"
        self.generations = self.data / "gen"
        self.pointer = self.data / "gen-current"
        self.log = self.data / "events.ndjson"
        for path in (self.data, self.generations):
            path.mkdir(parents=True, exist_ok=True)

    # -- index ------------------------------------------------------------

    def connect(self):
        import sqlite3

        db = self.data / "hub.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate(conn)
        return conn

    @staticmethod
    def _migrate(conn) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                dedup_key   TEXT PRIMARY KEY,
                protocol    TEXT NOT NULL,
                address     TEXT NOT NULL,
                port        INTEGER NOT NULL,
                country     TEXT,
                source      TEXT,
                first_seen  TEXT NOT NULL,
                last_ok     TEXT,
                score       INTEGER,
                rounds      INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS nodes_score ON nodes (score DESC);

            CREATE TABLE IF NOT EXISTS checks (
                dedup_key   TEXT NOT NULL,
                run_at      TEXT NOT NULL,
                ok          INTEGER NOT NULL,
                stage       TEXT,
                http_ms     REAL,
                jitter_ms   REAL,
                error       TEXT
            );
            CREATE INDEX IF NOT EXISTS checks_run ON checks (run_at);

            CREATE TABLE IF NOT EXISTS sources (
                url         TEXT PRIMARY KEY,
                enabled     INTEGER NOT NULL DEFAULT 1,
                last_ok     TEXT,
                last_empty  TEXT,
                empty_rounds INTEGER NOT NULL DEFAULT 0,
                etag        TEXT
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                token       TEXT PRIMARY KEY,
                telegram_id INTEGER,
                status      TEXT NOT NULL DEFAULT 'active',
                created_at  TEXT NOT NULL,
                last_seen   TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS subs_token ON subscriptions (token);

            CREATE TABLE IF NOT EXISTS subscription_tokens (
                token_hash  TEXT PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                status      TEXT NOT NULL DEFAULT 'active',
                created_at  TEXT NOT NULL,
                label       TEXT NOT NULL DEFAULT '',
                expires_at  TEXT,
                username    TEXT NOT NULL DEFAULT '',
                source      TEXT NOT NULL DEFAULT '',
                last_seen   TEXT
            );
            CREATE INDEX IF NOT EXISTS subscription_tokens_status
                ON subscription_tokens (status);

            -- One free key per network per cooldown. Only a keyed hash of the
            -- address is stored: the raw IP never reaches disk.
            CREATE TABLE IF NOT EXISTS free_claims (
                ip_hash    TEXT PRIMARY KEY,
                claimed_at TEXT NOT NULL
            );

            -- Anonymous app installations. The client sends a random install
            -- id; only its keyed digest is stored. No IP, account or device
            -- identifier is kept here.
            CREATE TABLE IF NOT EXISTS app_instances (
                instance_hash TEXT PRIMARY KEY,
                first_seen    TEXT NOT NULL,
                last_seen     TEXT NOT NULL,
                version       TEXT NOT NULL DEFAULT '',
                platform      TEXT NOT NULL DEFAULT '',
                locale        TEXT NOT NULL DEFAULT '',
                connected     INTEGER NOT NULL DEFAULT 0,
                connected_at  TEXT
            );
            CREATE INDEX IF NOT EXISTS app_instances_seen
                ON app_instances (last_seen DESC);

            -- One anonymous access key per app installation. The raw token is
            -- returned once to the app and never stored here.
            CREATE TABLE IF NOT EXISTS app_access (
                instance_hash TEXT PRIMARY KEY,
                token_hash    TEXT NOT NULL,
                issued_at     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_diagnostics (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                version       TEXT NOT NULL DEFAULT '',
                platform      TEXT NOT NULL DEFAULT '',
                locale        TEXT NOT NULL DEFAULT '',
                logs          TEXT NOT NULL,
                meta          TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS app_diagnostics_created
                ON app_diagnostics (created_at DESC);

            -- One row per *payload* (tier x core x format, plus one per
            -- country shard). The generation is part of the key rather than the
            -- whole of it, because a run writes many payloads into one
            -- generation and every one of them is a row of the rollback index:
            -- a PRIMARY KEY of `generation` alone made the whole set collide.
            CREATE TABLE IF NOT EXISTS publishes (
                generation  TEXT NOT NULL,
                sha256      TEXT NOT NULL,
                tier        TEXT NOT NULL,
                core        TEXT NOT NULL,
                fmt         TEXT NOT NULL,
                node_count  INTEGER NOT NULL,
                created_at  TEXT NOT NULL,
                PRIMARY KEY (generation, tier, core, fmt)
            );
            CREATE INDEX IF NOT EXISTS pub_created ON publishes (created_at DESC);
            """
        )
        Store._migrate_publishes_key(conn)
        Store._migrate_subscription_tokens(conn)
        # Additive migrations only. The live API holds this database open and
        # must keep serving through an upgrade, so a new column is ALTERed in
        # rather than recreated by dropping and re-declaring the table: `CREATE
        # TABLE IF NOT EXISTS` is a no-op on an existing table, so a column
        # added to this script would never reach the `hub.db` the worker
        # already created. `PRAGMA table_info` is the checkpoint.
        existing = {row[1] for row in conn.execute("PRAGMA table_info(sources)")}
        additions = {
            # The last body that produced nodes, so a 304 has something to
            # parse. Without it "skip parsing on a 304" means the round yields
            # nothing at all, and `run_once` builds its whole node pool from
            # fetched bodies — an unchanged source would publish an empty
            # generation, which looks exactly like a broken checker.
            "body": "ALTER TABLE sources ADD COLUMN body TEXT",
            # Rounds of history for the quarantine cap: a brand-new source is
            # novel, not proven, and "proven" is what this counter records.
            "rounds": "ALTER TABLE sources ADD COLUMN rounds INTEGER NOT NULL DEFAULT 0",
        }
        for column, ddl in additions.items():
            if column not in existing:
                conn.execute(ddl)

        # `nodes.state` — the node serialised whole, so a verified node can be
        # published in a later round without being re-probed.
        #
        # The other columns are enough to *recognise* a node and not enough to
        # *reconstruct* one: the uuid, the password and the transport settings
        # are what a render needs, and a node rebuilt without them passes every
        # check and then produces dead entries. Storing the node whole is what
        # makes the pool the union of what has been proven working recently
        # rather than the intersection of what one round happened to probe.
        node_columns = {row[1] for row in conn.execute("PRAGMA table_info(nodes)")}
        if "state" not in node_columns:
            conn.execute("ALTER TABLE nodes ADD COLUMN state TEXT")

        # `label` on an issued key: a name the operator gave it ("для мамы",
        # "тест"), so the list is readable months later when the digest prefixes
        # have stopped meaning anything. Empty for keys the bot minted, which
        # have an identity attached instead.
        token_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(subscription_tokens)")
        }
        for column, ddl in {
            "label": "ALTER TABLE subscription_tokens ADD COLUMN label TEXT NOT NULL DEFAULT ''",
            "expires_at": "ALTER TABLE subscription_tokens ADD COLUMN expires_at TEXT",
            "username": "ALTER TABLE subscription_tokens ADD COLUMN username TEXT NOT NULL DEFAULT ''",
            "source": "ALTER TABLE subscription_tokens ADD COLUMN source TEXT NOT NULL DEFAULT ''",
            "last_seen": "ALTER TABLE subscription_tokens ADD COLUMN last_seen TEXT",
        }.items():
            if token_columns and column not in token_columns:
                conn.execute(ddl)
        conn.commit()

    @staticmethod
    def _migrate_subscription_tokens(conn) -> None:
        """Hash legacy bearer tokens before any API path reads the new table."""
        import sqlite3

        conn.execute(
            "CREATE TABLE IF NOT EXISTS subscription_tokens ("
            "token_hash TEXT PRIMARY KEY, telegram_id INTEGER NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, "
            "label TEXT NOT NULL DEFAULT '', expires_at TEXT, "
            "username TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', "
            "last_seen TEXT)"
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(subscriptions)")}
        if "token" not in columns:
            conn.commit()
            return
        if not conn.execute("SELECT 1 FROM subscriptions LIMIT 1").fetchone():
            conn.commit()
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            rows = conn.execute(
                "SELECT token, telegram_id, status, created_at FROM subscriptions"
            ).fetchall()
            for token, telegram_id, status, created_at in rows:
                if not token:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO subscription_tokens "
                    "(token_hash, telegram_id, status, created_at) VALUES (?, ?, ?, ?)",
                    (
                        hashlib.sha256(str(token).encode("utf-8")).hexdigest(),
                        int(telegram_id or 0),
                        str(status or "active"),
                        str(created_at or datetime.now(timezone.utc).isoformat()),
                    ),
                )
            # Remove plaintext bearer material from the legacy table. Keep the
            # table shape for older code but leave it empty after migration.
            conn.execute("DELETE FROM subscriptions")
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise

    @staticmethod
    def _migrate_publishes_key(conn) -> None:
        """Widen the `publishes` key from `(generation)` to all four columns.

        A PRIMARY KEY cannot be altered in place, so this is the one migration
        in the schema that rebuilds a table rather than adding a column. It is
        safe to run on every open, and must be: `hub.db` is opened by the API
        reader, the worker, and the CLI, and none of them can be the one that
        is trusted to migrate first.

        `CREATE TABLE IF NOT EXISTS` builds the *new* shape, so the rebuild is
        guarded on the old shape being what is actually there rather than on a
        version counter nothing else maintains. The test for it is the
        two-column version number: the old table's `generation` column reports
        `pk=1`, the rebuilt one reports `pk` starting at 1 across four columns,
        and both are discovered the same way — `PRAGMA table_info`.

        The existing row, if any, is carried across verbatim. It is the *last*
        payload of an old run and its `core` is mis-parsed, so it cannot be
        repaired by guessing; `tier_counts` is recomputed from the payload rows
        on the next publish, and a stale single row is more honest than a
        fabricated one.
        """
        info = list(conn.execute("PRAGMA table_info(publishes)"))
        if not info:
            return
        pk = sorted((row[5], row[1]) for row in info if row[5])
        if len(pk) != 1 or pk[0][1] != "generation":
            return  # already the composite key, or a fresh table
        conn.executescript(
            """
            ALTER TABLE publishes RENAME TO publishes_old;
            CREATE TABLE publishes (
                generation  TEXT NOT NULL,
                sha256      TEXT NOT NULL,
                tier        TEXT NOT NULL,
                core        TEXT NOT NULL,
                fmt         TEXT NOT NULL,
                node_count  INTEGER NOT NULL,
                created_at  TEXT NOT NULL,
                PRIMARY KEY (generation, tier, core, fmt)
            );
            INSERT INTO publishes (generation, sha256, tier, core, fmt, node_count, created_at)
                SELECT generation, sha256, tier, core, fmt, node_count, created_at
                  FROM publishes_old;
            DROP TABLE publishes_old;
            CREATE INDEX IF NOT EXISTS pub_created ON publishes (created_at DESC);
            """
        )
        conn.commit()

    # -- subscriptions -----------------------------------------------------

    @staticmethod
    def _subscription_key(token: str) -> str:
        """Store only a digest of the bearer token, never the usable secret."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def issue_subscription(
        self,
        token: str,
        telegram_id: int,
        *,
        label: str = "",
        expires_at: str | None = None,
        username: str = "",
        source: str = "panel",
    ) -> bool:
        """Persist a new active token; return False only on a token collision.

        `telegram_id` is 0 for a key minted on the web or in the panel rather
        than by the bot. `expires_at` is an ISO timestamp or None for a token
        with no term; new public keys have no term.
        """
        import sqlite3

        conn = self.connect()
        try:
            try:
                conn.execute(
                    "INSERT INTO subscription_tokens"
                    " (token_hash, telegram_id, status, created_at, label, expires_at, username, source)"
                    " VALUES (?, ?, 'active', ?, ?, ?, ?, ?)",
                    (
                        self._subscription_key(token),
                        telegram_id,
                        datetime.now(timezone.utc).isoformat(),
                        label,
                        expires_at,
                        username,
                        source,
                    ),
                )
            except sqlite3.IntegrityError:
                conn.rollback()
                return False
            conn.commit()
            return True
        finally:
            conn.close()

    def subscription_status(self, token: str) -> str | None:
        """Return active/expired/revoked for a bearer token, without storing it."""
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT status, expires_at FROM subscription_tokens WHERE token_hash = ?",
                (self._subscription_key(token),),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        status, expires_at = str(row[0]), row[1]
        if status == "active" and expires_at:
            try:
                expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
            except ValueError:
                # A malformed term cannot be trusted: fail closed, not "forever".
                return "expired"
            if expiry <= datetime.now(timezone.utc):
                return "expired"
        return status

    def free_claim_remaining(self, ip_hash: str, *, hours: int = 24) -> int:
        """Seconds left before this hashed network may claim another key."""
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT claimed_at FROM free_claims WHERE ip_hash = ?", (ip_hash,)
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return 0
        try:
            claimed = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
            if claimed.tzinfo is None:
                claimed = claimed.replace(tzinfo=timezone.utc)
        except ValueError:
            return 1
        remaining = (claimed + timedelta(hours=hours) - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(remaining))

    def claim_free_slot(self, ip_hash: str, *, hours: int = 24) -> int:
        """Atomically reserve this network's one free key for `hours`.

        Returns 0 when the slot was reserved, otherwise the seconds remaining.
        `BEGIN IMMEDIATE` makes two concurrent requests from one network race
        for the same row: exactly one can win, even on a multi-worker server.
        """
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT claimed_at FROM free_claims WHERE ip_hash = ?", (ip_hash,)
            ).fetchone()
            now = datetime.now(timezone.utc)
            if row:
                try:
                    claimed = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                    if claimed.tzinfo is None:
                        claimed = claimed.replace(tzinfo=timezone.utc)
                except ValueError:
                    claimed = now - timedelta(hours=hours)
                remaining = (claimed + timedelta(hours=hours) - now).total_seconds()
                if remaining > 0:
                    conn.rollback()
                    return max(1, int(remaining))
            conn.execute(
                "INSERT INTO free_claims (ip_hash, claimed_at) VALUES (?, ?)"
                " ON CONFLICT(ip_hash) DO UPDATE SET claimed_at = excluded.claimed_at",
                (ip_hash, now.isoformat()),
            )
            conn.commit()
            return 0
        finally:
            conn.close()

    def release_free_slot(self, ip_hash: str) -> None:
        """Give a reservation back when token minting failed after the claim."""
        conn = self.connect()
        try:
            conn.execute("DELETE FROM free_claims WHERE ip_hash = ?", (ip_hash,))
            conn.commit()
        finally:
            conn.close()

    def subscription_expiry(self, token: str) -> str | None:
        """The stored term for a token, or None for a permanent one."""
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT expires_at FROM subscription_tokens WHERE token_hash = ?",
                (self._subscription_key(token),),
            ).fetchone()
        finally:
            conn.close()
        return str(row[0]) if row and row[0] else None

    def touch_subscription(self, token: str) -> None:
        """Record the last successful fetch, best-effort; never raises."""
        conn = self.connect()
        try:
            conn.execute(
                "UPDATE subscription_tokens SET last_seen = ? WHERE token_hash = ?",
                (datetime.now(timezone.utc).isoformat(), self._subscription_key(token)),
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def extend_subscription(self, prefix: str, days: int) -> int:
        """Add days to the one token whose digest starts with `prefix`.

        A short prefix is ambiguous by construction; returning the match count
        lets the caller refuse with 409 instead of silently changing several
        keys the operator did not name.
        """
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT token_hash, expires_at FROM subscription_tokens"
                " WHERE token_hash LIKE ? AND status = 'active'",
                (prefix + "%",),
            ).fetchall()
            if len(rows) != 1:
                return len(rows)
            now = datetime.now(timezone.utc)
            for digest, expires_at in rows:
                try:
                    base = (
                        datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                        if expires_at
                        else now
                    )
                    if base.tzinfo is None:
                        base = base.replace(tzinfo=timezone.utc)
                except ValueError:
                    base = now
                if base < now:
                    base = now
                conn.execute(
                    "UPDATE subscription_tokens SET expires_at = ? WHERE token_hash = ?",
                    ((base + timedelta(days=days)).isoformat(), digest),
                )
            conn.commit()
            return len(rows)
        finally:
            conn.close()

    def revoke_subscription(self, token: str) -> bool:
        """Revoke a subscription by bearer token; return whether it was active."""
        conn = self.connect()
        try:
            cursor = conn.execute(
                "UPDATE subscription_tokens SET status = 'revoked'"
                " WHERE token_hash = ? AND status = 'active'",
                (self._subscription_key(token),),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    # -- anonymous app presence ------------------------------------------

    def add_app_diagnostics(
        self,
        instance_hash: str,
        *,
        version: str,
        platform: str,
        locale: str,
        logs: str,
        meta: str,
    ) -> int:
        conn = self.connect()
        try:
            cur = conn.execute(
                "INSERT INTO app_diagnostics"
                " (instance_hash, created_at, version, platform, locale, logs, meta)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    instance_hash,
                    datetime.now(timezone.utc).isoformat(),
                    version[:32],
                    platform[:16],
                    locale[:16],
                    logs[:32_000],
                    meta[:8_000],
                ),
            )
            conn.commit()
            return int(cur.lastrowid or 0)
        finally:
            conn.close()

    def app_diagnostics(self, *, limit: int = 30) -> list[dict]:
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT id, instance_hash, created_at, version, platform, locale, logs, meta"
                " FROM app_diagnostics ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "id": row["id"],
                "instance": row["instance_hash"][:12],
                "created_at": row["created_at"],
                "version": row["version"] or "—",
                "platform": row["platform"] or "—",
                "locale": row["locale"] or "—",
                "logs": row["logs"],
                "meta": row["meta"],
            }
            for row in rows
        ]

    def issue_app_access(self, instance_hash: str, token: str, *, rotate: bool = False) -> bool:
        """Issue one hidden access key per anonymous app installation.

        The app stores the subscription URL in SecureStore; this table keeps
        only the token digest and never leaks the bearer token again. Returns
        False when the installation already has a key and `rotate` is false.
        Rotation is an explicit recovery path for a stored key that no longer
        resolves; the previous token is revoked before the new one is issued.
        """
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT token_hash FROM app_access WHERE instance_hash = ?", (instance_hash,)
            ).fetchone()
            if existing:
                if not rotate:
                    conn.rollback()
                    return False
                conn.execute(
                    "UPDATE subscription_tokens SET status = 'revoked' WHERE token_hash = ?",
                    (existing["token_hash"],),
                )
                conn.execute("DELETE FROM app_access WHERE instance_hash = ?", (instance_hash,))
            digest = self._subscription_key(token)
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO subscription_tokens"
                " (token_hash, telegram_id, status, created_at, label, expires_at, username, source)"
                " VALUES (?, ?, 'active', ?, ?, NULL, '', 'app')",
                (digest, 0, now, "app-install"),
            )
            conn.execute(
                "INSERT INTO app_access (instance_hash, token_hash, issued_at) VALUES (?, ?, ?)",
                (instance_hash, digest, now),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    def touch_app_instance(
        self,
        instance_hash: str,
        *,
        version: str = "",
        platform: str = "",
        locale: str = "",
        connected: bool = False,
    ) -> None:
        """Upsert one anonymous installation heartbeat.

        `instance_hash` is derived server-side from a random client install id.
        The raw id, IP, account and device identifiers are never stored.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self.connect()
        try:
            conn.execute(
                "INSERT INTO app_instances"
                " (instance_hash, first_seen, last_seen, version, platform, locale, connected, connected_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(instance_hash) DO UPDATE SET"
                " last_seen=excluded.last_seen,"
                " version=excluded.version,"
                " platform=excluded.platform,"
                " locale=excluded.locale,"
                " connected=excluded.connected,"
                " connected_at=CASE WHEN excluded.connected=1"
                "   THEN excluded.last_seen ELSE app_instances.connected_at END",
                (
                    instance_hash,
                    now,
                    now,
                    version[:32],
                    platform[:16],
                    locale[:16],
                    1 if connected else 0,
                    now if connected else None,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _iso_cutoff(seconds: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()

    def app_instance_stats(self, *, row_limit: int = 200) -> dict:
        """Aggregate unique anonymous app installations for the admin panel."""
        conn = self.connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM app_instances").fetchone()[0]
            active_24h = conn.execute(
                "SELECT COUNT(*) FROM app_instances WHERE last_seen >= ?",
                (self._iso_cutoff(24 * 3600),),
            ).fetchone()[0]
            active_7d = conn.execute(
                "SELECT COUNT(*) FROM app_instances WHERE last_seen >= ?",
                (self._iso_cutoff(7 * 24 * 3600),),
            ).fetchone()[0]
            active_30d = conn.execute(
                "SELECT COUNT(*) FROM app_instances WHERE last_seen >= ?",
                (self._iso_cutoff(30 * 24 * 3600),),
            ).fetchone()[0]
            cutoff = self._iso_cutoff(10 * 60)
            online = conn.execute(
                "SELECT COUNT(*) FROM app_instances WHERE connected=1 AND last_seen >= ?",
                (cutoff,),
            ).fetchone()[0]
            by_version = [
                {"name": row[0] or "unknown", "n": row[1]}
                for row in conn.execute(
                    "SELECT version, COUNT(*) FROM app_instances"
                    " GROUP BY version ORDER BY COUNT(*) DESC"
                ).fetchall()
            ]
            by_platform = [
                {"name": row[0] or "unknown", "n": row[1]}
                for row in conn.execute(
                    "SELECT platform, COUNT(*) FROM app_instances"
                    " GROUP BY platform ORDER BY COUNT(*) DESC"
                ).fetchall()
            ]
            rows = [
                {
                    "id": row["instance_hash"][:12],
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "version": row["version"] or "—",
                    "platform": row["platform"] or "—",
                    "locale": row["locale"] or "—",
                    "connected": bool(row["connected"]),
                    "online": bool(row["connected"] and row["last_seen"] >= cutoff),
                }
                for row in conn.execute(
                    "SELECT instance_hash, first_seen, last_seen, version, platform, locale, connected"
                    " FROM app_instances ORDER BY last_seen DESC LIMIT ?",
                    (int(row_limit),),
                ).fetchall()
            ]
        finally:
            conn.close()
        return {
            "total": total,
            "active_24h": active_24h,
            "active_7d": active_7d,
            "active_30d": active_30d,
            "online": online,
            "by_version": by_version,
            "by_platform": by_platform,
            "rows": rows,
        }

    def count_subscriptions_since(self, since: str, *, source: str | None = None) -> int:
        conn = self.connect()
        try:
            sql = "SELECT COUNT(*) FROM subscription_tokens WHERE created_at >= ?"
            params: list[str] = [since]
            if source:
                sql += " AND source = ?"
                params.append(source)
            return int(conn.execute(sql, params).fetchone()[0])
        finally:
            conn.close()

    def count_subscriptions(self, *, status: str = "active") -> int:
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM subscription_tokens WHERE status = ?"
                " AND (expires_at IS NULL OR datetime(expires_at) > datetime('now'))",
                (status,),
            ).fetchone()
            return int(row[0])
        finally:
            conn.close()

    # -- source state ------------------------------------------------------

    def load_source_states(self) -> dict[str, dict]:
        """The per-source counters that must survive the process.

        `Fetcher` is constructed fresh for every `hub run`, so anything it
        remembers about a source dies with it. An in-memory ETag cache
        therefore never hits: the round after a successful fetch is a new
        process with an empty `_etags`, so `fetch_one` sends no
        `If-None-Match`. The database is the only place a counter can mean
        "consecutive rounds", and the `sources` table was created for exactly
        this and never wired up.

        Returns `{url: {...}}`. A source the database has never seen is *absent*
        rather than defaulted, because "no history" and "a long history of
        failing" call for different behaviour, and collapsing them is how a
        brand-new source gets treated as proven.
        """
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT url, enabled, last_ok, last_empty, empty_rounds, etag,"
                " body, rounds FROM sources"
            )
            return {row["url"]: dict(row) for row in rows}
        finally:
            conn.close()

    def save_source_state(self, url: str, **fields) -> None:
        """Upsert one source's counters.

        Only the keys handed in are written. A caller that measured nothing
        about `last_empty` must not reset it, which is exactly what a
        whole-row write from a partially-populated dict would do — and an
        accidentally reset counter restarts the empty-round count, so a source
        that fails forever never reaches the limit that disables it.
        """
        if not fields:
            return
        allowed = {
            "enabled", "last_ok", "last_empty", "empty_rounds", "etag", "body",
            "rounds",
        }
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(
                f"unknown source-state field(s): {', '.join(unknown)}; "
                f"expected one of {', '.join(sorted(allowed))}"
            )
        conn = self.connect()
        try:
            conn.execute(
                f"INSERT INTO sources (url, {', '.join(fields)})"
                f" VALUES (?, {', '.join('?' * len(fields))})"
                " ON CONFLICT(url) DO UPDATE SET "
                + ", ".join(f"{k} = excluded.{k}" for k in fields),
                (url, *fields.values()),
            )
            conn.commit()
        finally:
            conn.close()

    # -- fact log ---------------------------------------------------------

    def append_event(self, event: str, **fields) -> None:
        """NDJSON, append-only, the source of truth for score recomputation.

        The event name is `event`, not `kind`, on purpose: callers legitimately
        carry a field *called* `kind` (a parse error records
        `kind=error.kind.value`), and a positional parameter with that name
        makes `append_event("parse_error", kind=...)` a TypeError about
        "multiple values for argument 'kind'". The log record itself still
        spells the discriminator `kind`, because that is the schema readers
        and the UI filter on.
        """
        record = {"ts": datetime.now(timezone.utc).isoformat(), "kind": event, **fields}
        with self.log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    # -- generations ------------------------------------------------------

    def current_generation(self) -> Optional[str]:
        """Resolve the immutable generation currently being served.

        The pointer is a small JSON file replaced atomically by `os.replace`,
        so a reader either sees the old value or the new one — never a torn
        path built from half-updated mutable state.
        """
        try:
            raw = self.pointer.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)["generation"]
        except (json.JSONDecodeError, KeyError):
            return None

    def generation_path(self, generation: str) -> Path:
        return self.generations / generation

    def flip_pointer(self, generation: str, sha256: str) -> None:
        tmp = self.pointer.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"generation": generation, "sha256": sha256}, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, self.pointer)

    def retain(self, keep: int, *, protect: str | None = None) -> list[str]:
        """Keep the newest `keep` generations; return what was removed.

        The **live** generation is never removed, even when it falls outside the
        retention window — that happens right after a rollback or when a run
        re-publishes an older generation. Deleting files the API is currently
        serving turns a stale payload into a 404, which is the one failure mode
        the spec prohibits (fail-open). If the live generation must go, flip the
        pointer first.

        `protect` overrides the live-generation lookup (tests pass it in).

        "Newest" is **mtime order, not name order**: a generation id is
        content-derived, so `gen-0000…` can be written after `gen-ffff…`
        whenever the content hash happens to be smaller. Ordering by name would
        retain the wrong set and could delete the most recent payload.
        """
        live = protect if protect is not None else self.current_generation()
        dirs = sorted(
            (p for p in self.generations.iterdir() if p.is_dir()),
            key=_generation_mtime,
            reverse=True,
        )
        kept = dirs[:keep] if keep > 0 else []
        if live:
            live_path = self.generation_path(live)
            if live_path.is_dir() and live_path not in kept:
                kept.append(live_path)
        to_remove = [p for p in dirs if p not in kept]
        removed: list[str] = []
        for path in to_remove:
            shutil.rmtree(path, ignore_errors=True)
            removed.append(path.name)
        return removed
