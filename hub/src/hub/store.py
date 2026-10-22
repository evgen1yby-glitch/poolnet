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

import asyncio
import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from . import fetcher, parser as uri_parser, tiers as tierlib
from .gate import RateLimiter
from .models import Format, Node, ProbeResult, Score
from .prober import CoreDriver, Prober
from .renderer import RenderParams, render_validated
from .scorer import History, Weights, score as score_node


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
                created_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS subscription_tokens_status
                ON subscription_tokens (status);

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
        if token_columns and "label" not in token_columns:
            conn.execute(
                "ALTER TABLE subscription_tokens ADD COLUMN label TEXT NOT NULL DEFAULT ''"
            )
        conn.commit()

    @staticmethod
    def _migrate_subscription_tokens(conn) -> None:
        """Hash legacy bearer tokens before any API path reads the new table."""
        import sqlite3

        conn.execute(
            "CREATE TABLE IF NOT EXISTS subscription_tokens ("
            "token_hash TEXT PRIMARY KEY, telegram_id INTEGER NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL)"
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
        self, token: str, telegram_id: int, *, label: str = ""
    ) -> bool:
        """Persist a new active token; return False only on a token collision.

        `telegram_id` is 0 for a key minted in the operator panel rather than by
        the bot. That is not a placeholder for a missing value — the column is
        the bot's identity for the holder, and a panel-issued key has none. Zero
        says so, and the panel's list distinguishes the two by it.
        """
        import sqlite3

        conn = self.connect()
        try:
            try:
                conn.execute(
                    "INSERT INTO subscription_tokens"
                    " (token_hash, telegram_id, status, created_at, label)"
                    " VALUES (?, ?, 'active', ?, ?)",
                    (
                        self._subscription_key(token),
                        telegram_id,
                        datetime.now(timezone.utc).isoformat(),
                        label,
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
        """Return active/revoked for a known bearer token, without storing it."""
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT status FROM subscription_tokens WHERE token_hash = ?",
                (self._subscription_key(token),),
            ).fetchone()
            return str(row[0]) if row else None
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

    def count_subscriptions(self, *, status: str = "active") -> int:
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM subscription_tokens WHERE status = ?", (status,)
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
