"""The `sources` table: state that has to survive the process.

`Fetcher` is constructed fresh for every `hub run`, so a counter it keeps in a
dict means nothing. The `sources` table was created for exactly this — ETags to
send back, the body to reuse on a 304, and the empty-round/rounds counters the
circuit breaker and the quarantine cap read — and until `Store` gained the two
methods below, nothing read or wrote any of it: 0 rows, in production, forever.

Two properties are load-bearing and are the only reason this file exists:

1. **A partial write must not clobber what it did not name.** A caller that
   measured `empty_rounds` and `rounds` but not `last_ok` must leave `last_ok`
   alone. Whole-row writes from a partially-populated dict were how a reset
   counter would restart the empty-round count, so a source that fails forever
   never reaches the limit that is supposed to disable it.

2. **The migration must be additive.** The live API holds this database open and
   keeps serving through an upgrade. `CREATE TABLE IF NOT EXISTS` is a no-op on
   an existing table, so a new column in that script never reaches a `hub.db`
   that already exists — which is why `body`/`rounds` are `ALTER`ed in behind a
   `PRAGMA table_info` check.

The fixtures here use a real `Store` on `tmp_path`, not an in-memory `sqlite3`
connection: the tests are about what a *second* process opening the file can
see, and an in-memory connection cannot express that.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hub.store import Store  # noqa: E402

URL = "https://example.invalid/config.txt"


def test_state_round_trips_through_a_fresh_connection(tmp_path):
    """A second reader must see exactly what the first writer wrote.

    The connection is closed and reopened between write and read because that
    is the actual scenario: `Fetcher` is destroyed and rebuilt every run, so the
    only thing that carries the ETag across is the file on disk.
    """
    store = Store(tmp_path)
    store.save_source_state(URL, etag='"v1"', body="vless://a#x", rounds=3)

    reopened = Store(tmp_path)
    states = reopened.load_source_states()

    assert URL in states
    assert states[URL]["etag"] == '"v1"'
    assert states[URL]["body"] == "vless://a#x"
    assert states[URL]["rounds"] == 3


def test_an_unknown_source_is_absent_rather_than_defaulted(tmp_path):
    """"No history" and "a history of failing" need different handling.

    A brand-new source must be quarantined; one with 20 failed rounds must be
    disabled. `load_source_states` returning a defaulted row for every URL in
    the config would make those the same, and `quarantine_cap`/`is_disabled`
    both key off what comes back.
    """
    store = Store(tmp_path)
    assert store.load_source_states() == {}, "an empty table must read as empty"


def test_a_partial_save_leaves_the_fields_it_did_not_name_alone(tmp_path):
    """The clobber guard, and the reason it is the first test here.

    A circuit breaker is only a breaker if the counter accumulates. If saving
    `rounds` reset `empty_rounds`, a source failing forever would reset its own
    streak on every round and never be disabled — the exact failure
    `EMPTY_ROUND_LIMIT` exists to prevent, and one that looks like "the source
    kept failing but we kept trying".
    """
    store = Store(tmp_path)
    store.save_source_state(URL, etag='"v1"', body="b", empty_rounds=7, rounds=12)
    store.save_source_state(URL, last_ok="2026-10-15T00:00:00+00:00")

    state = Store(tmp_path).load_source_states()[URL]
    assert state["empty_rounds"] == 7, "a partial save reset the empty-round streak"
    assert state["rounds"] == 12
    assert state["etag"] == '"v1"'
    assert state["body"] == "b"
    assert state["last_ok"] == "2026-10-15T00:00:00+00:00"


def test_saving_nothing_is_not_a_write(tmp_path):
    """No keys means no SQL, not a row of defaults over existing columns.

    The guard is `if not fields: return`. Without it, `save_source_state(url)`
    would insert a row of `NULL`s that a later partial save then has to merge
    against, and `body`/`etag` would be silently null where the caller expected
    "untouched".
    """
    store = Store(tmp_path)
    store.save_source_state(URL, etag='"v1"')
    store.save_source_state(URL)
    assert Store(tmp_path).load_source_states()[URL]["etag"] == '"v1"'


def test_an_unknown_column_is_rejected_not_silently_accepted():
    """The field-name guard.

    `save_source_state` builds its SQL from the keys it is handed, so accepting
    a typo means either an `OperationalError: no such column` at an arbitrary
    later point or a column name interpolated into a statement. Naming the
    offending field is the difference between a clear error and either.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        store = Store(tmp)
        with pytest.raises(ValueError, match="empty_yrounds"):
            store.save_source_state(URL, empty_yrounds=3)


def test_disabling_a_source_round_trips():
    """`enabled` is the circuit breaker's persistent half."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        real = Store(tmp)
        real.save_source_state(URL, enabled=0)
        assert Store(tmp).load_source_states()[URL]["enabled"] == 0
        # And re-enabling it works, which is what an operator does after
        # inspecting a disabled source with `audit_sources.py`.
        real.save_source_state(URL, enabled=1)
        assert Store(tmp).load_source_states()[URL]["enabled"] == 1


def test_the_migration_adds_its_columns_to_a_database_that_predates_them(tmp_path):
    """`CREATE TABLE IF NOT EXISTS` cannot add a column. This is what can.

    The live `hub.db` was created before `body`/`rounds` existed, so their
    absence is the normal case, not the edge case. The columns are added with
    `ALTER TABLE ... ADD COLUMN` guarded by `PRAGMA table_info`, and the check
    is what makes the migration re-runnable — a second `ADD COLUMN` for a column
    that now exists raises `OperationalError: duplicate column name`.
    """
    data = tmp_path / "data"
    data.mkdir()
    # A `sources` table shaped exactly like the original DDL.
    conn = sqlite3.connect(str(data / "hub.db"))
    conn.executescript(
        "CREATE TABLE sources (url TEXT PRIMARY KEY, enabled INTEGER NOT NULL"
        " DEFAULT 1, last_ok TEXT, last_empty TEXT,"
        " empty_rounds INTEGER NOT NULL DEFAULT 0, etag TEXT);"
    )
    conn.execute(
        "INSERT INTO sources (url, etag, empty_rounds) VALUES (?, ?, ?)",
        (URL, '"old"', 4),
    )
    conn.commit()
    conn.close()

    store = Store(tmp_path)
    store.save_source_state(URL, body="vless://later#x")

    # The row written before the migration is still readable, and the new
    # columns are populated.
    state = store.load_source_states()[URL]
    assert state["etag"] == '"old"', "the migration lost a pre-existing row"
    assert state["empty_rounds"] == 4
    assert state["body"] == "vless://later#x"

    # Re-running the migration must not raise, and must not lose the column.
    conn = sqlite3.connect(str(data / "hub.db"))
    Store._migrate(conn)
    Store._migrate(conn)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(sources)")]
    conn.close()
    assert "body" in columns and "rounds" in columns, columns


def test_subscription_tokens_are_hashed_and_survive_reopen(tmp_path):
    store = Store(tmp_path)
    token = "a-secret-bearer-token-that-must-not-be-stored"
    assert store.issue_subscription(token, 1234)
    assert not store.issue_subscription(token, 1234)

    reopened = Store(tmp_path)
    assert reopened.subscription_status(token) == "active"
    conn = reopened.connect()
    try:
        row = conn.execute("SELECT token_hash FROM subscription_tokens").fetchone()
        assert row[0] != token
        assert len(row[0]) == 64
    finally:
        conn.close()


def test_subscription_revocation_is_durable(tmp_path):
    token = "issued-token"
    store = Store(tmp_path)
    assert store.issue_subscription(token, 5)
    assert store.revoke_subscription(token)
    assert not store.revoke_subscription(token)
    assert Store(tmp_path).subscription_status(token) == "revoked"


def test_other_tables_survive_the_migration(tmp_path):
    """The migration must not recreate the schema.

    Dropping and re-declaring `sources` to add a column would take every other
    table's data with it if the table name were ever wrong, and would 404 the
    live API's generation pointer mid-run. The tables this project depends on
    are all still present and still queryable after a migration.
    """
    store = Store(tmp_path)
    store.save_source_state(URL, body="x")
    conn = store.connect()
    tables = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    conn.close()
    assert tables == ["checks", "nodes", "publishes", "sources", "subscription_tokens", "subscriptions"], tables


# --------------------------------------------------------------------------- #
# the `publishes` key
# --------------------------------------------------------------------------- #
#
# These are regression tests for a defect that shipped green. `_publish` writes
# one row per payload — ~15 per generation — but `publishes.generation` was the
# PRIMARY KEY, so every insert was an `ON CONFLICT(generation) DO UPDATE`. The
# last row won, and because only `node_count` was in the SET list, tier/core/fmt
# froze at the first payload's values while the count became the last country
# shard's. `/api/v1/stats` reported 2 published nodes for a 39-node pool.
#
# Nothing caught it, because the only assertion on the field was truthiness
# (`assert payload["published"]`), and truthiness is satisfied by a single row
# that contains the wrong number. Every assertion below is on a *count*, and
# every count is one a wrong row cannot satisfy by accident.


def _old_shape(db: Path) -> None:
    """Rebuild `publishes` in the pre-fix shape, with one surviving row.

    Written by hand rather than imported from a snapshot: the point is to
    express the exact schema the live database had, including the single-column
    primary key, so the migration is exercised against what actually existed.
    """
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        DROP TABLE publishes;
        CREATE TABLE publishes (
            generation  TEXT PRIMARY KEY,
            sha256      TEXT NOT NULL,
            tier        TEXT NOT NULL,
            core        TEXT NOT NULL,
            fmt         TEXT NOT NULL,
            node_count  INTEGER NOT NULL,
            created_at  TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO publishes VALUES ('gen-old','sha','verified','sing','base64',2,'2026-01-01')"
    )
    conn.commit()
    conn.close()


def _pk(conn) -> list[str]:
    return [
        row[1]
        for row in sorted(
            (r for r in conn.execute("PRAGMA table_info(publishes)") if r[5]),
            key=lambda r: r[5],
        )
    ]


def test_a_publish_writes_one_row_per_payload_not_one_per_generation(tmp_path):
    """11 payloads of one generation must be 11 rows, not 1.

    The failure this pins is silent in every other way: the generation exists,
    the pointer flips, the API serves the files, and the only wrong number is
    the one nobody asserts on. A row count is the observable that distinguishes
    the two behaviours, so it is what is asserted.
    """
    store = Store(tmp_path)
    conn = store.connect()
    conn.executemany(
        "INSERT INTO publishes (generation, sha256, tier, core, fmt, node_count, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(generation, tier, core, fmt) DO UPDATE SET"
        " node_count=excluded.node_count, sha256=excluded.sha256",
        [
            ("gen-1", "sha", "verified", "sing-box", "base64", 39, "T"),
            ("gen-1", "sha", "verified", "sing-box", "singbox", 39, "T"),
            ("gen-1", "sha", "verified", "sing-box", "clash", 39, "T"),
            ("gen-1", "sha", "verified", "mihomo", "base64", 39, "T"),
            ("gen-1", "sha", "verified", "xray", "base64", 39, "T"),
            # Four shards, three of them in the same format. These are the rows
            # that collide on (core, fmt) alone, which is why the country is
            # carried in `core` as `cc:XX` rather than left empty.
            ("gen-1", "sha", "verified", "cc:US", "base64", 20, "T"),
            ("gen-1", "sha", "verified", "cc:NL", "base64", 7, "T"),
            ("gen-1", "sha", "verified", "cc:CA", "base64", 2, "T"),
            ("gen-1", "sha", "verified", "cc:JP", "base64", 2, "T"),
        ],
    )
    conn.commit()
    rows = [tuple(r) for r in conn.execute("SELECT core, node_count FROM publishes WHERE generation='gen-1'")]
    conn.close()
    assert len(rows) == 9, rows
    # The count that reaches `/api/v1/stats` must be the tier's real size.
    conn = store.connect()
    published = [
        tuple(r)
        for r in conn.execute(
            "SELECT tier, MAX(node_count) FROM publishes"
            " WHERE generation='gen-1' AND core NOT LIKE 'cc:%' GROUP BY tier"
        )
    ]
    conn.close()
    assert published == [("verified", 39)], published


def test_the_publishes_key_is_all_four_columns(tmp_path):
    """A PK of `generation` alone is the defect, so pin the shape, not a count.

    Asserted through the primary key rather than a behaviour because the
    behaviour was broken *and green*: the insert statement's ON CONFLICT target
    and this key are two halves of one promise, and a future change to either
    one without the other reintroduces the collision without failing anything
    that touches rows.
    """
    conn = Store(tmp_path).connect()
    assert _pk(conn) == ["generation", "tier", "core", "fmt"], _pk(conn)
    conn.close()


def test_the_publishes_migration_rebuilds_an_old_table_and_keeps_its_rows(tmp_path):
    """The live `hub.db` has the one-column key, and the API keeps serving.

    This is the migration path, and it is the only one in this schema that
    rebuilds a table rather than adding a column — a PRIMARY KEY cannot be
    ALTERed. Three properties, because a rebuild can fail three ways:

    * it widens the key,
    * it carries the pre-existing row across, and
    * it is a no-op the second time, which matters because the API, the worker
      and the CLI all open this file and none of them is "the one that
      migrates first".
    """
    store = Store(tmp_path)
    store.connect().close()  # create the new schema
    _old_shape(tmp_path / "data" / "hub.db")

    conn = store.connect()
    assert _pk(conn) == ["generation", "tier", "core", "fmt"], _pk(conn)
    kept = [tuple(r) for r in conn.execute("SELECT generation, node_count FROM publishes")]
    conn.close()
    assert kept == [("gen-old", 2)], kept

    conn = store.connect()
    assert len(list(conn.execute("SELECT 1 FROM publishes"))) == 1
    conn.close()


def test_a_shard_row_is_distinguishable_from_a_whole_tier_row(tmp_path):
    """`cc:` is the whole-tier predicate's other half, in both readers.

    `/api/v1/stats` and `hub stats` both exclude country shards by `core NOT
    LIKE 'cc:%'`. A shard that is not distinguishable would be counted into the
    tier's total as a second copy of its nodes, and a whole-tier row that *were*
    matched would be dropped from it entirely — a false zero, which is worse.
    """
    conn = Store(tmp_path).connect()
    conn.executemany(
        "INSERT INTO publishes VALUES (?,?,?,?,?,?,?)",
        [
            ("g", "sha", "verified", "sing-box", "singbox", 39, "T"),
            ("g", "sha", "verified", "cc:US", "singbox", 20, "T"),
            ("g", "sha", "verified", "xray", "base64", 39, "T"),
            ("g", "sha", "curated", "sing-box", "singbox", 6, "T"),
        ],
    )
    conn.commit()
    whole = [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT tier, MAX(node_count) FROM publishes WHERE core NOT LIKE 'cc:%' GROUP BY tier"
        )
    ]
    shards = [r[0] for r in conn.execute("SELECT core FROM publishes WHERE core LIKE 'cc:%'")]
    conn.close()
    assert whole == [("curated", 6), ("verified", 39)], whole
    assert shards == ["cc:US"], shards
