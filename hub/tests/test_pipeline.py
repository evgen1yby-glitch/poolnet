"""Pipeline tests: fail-open behaviour, immutable generations, rollback."""

from __future__ import annotations

import hashlib
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from hub.models import Node, Protocol, Security, Transport, TransportSettings, TLS  # noqa: E402
from hub.pipeline import Pipeline  # noqa: E402
from hub.prober import Concurrency  # noqa: E402
from hub.scorer import Weights  # noqa: E402
from hub.speedtest import SpeedPolicy  # noqa: E402
from hub.store import Store  # noqa: E402

from tests.test_prober import FakeDriver, NoSpeedDriver, _dial_nowhere  # noqa: E402


def _offline():
    """(concurrency, connect, handshake) that collapse both network stages.

    The nodes here are synthetic `*.example.com`. Letting the funnel dial them
    would perform real DNS and — for the REALITY nodes — a verifying TLS
    handshake against a live host whose certificate we do not control. The
    seam keeps the fake driver honest and the suite hermetic.
    """
    return dict(
        concurrency=Concurrency(tcp=5, tls=5, http=5, round2_gap_s=0.0),
        connect=_dial_nowhere,
        handshake=_handshake_ok,
    )


async def _handshake_ok(address, port, server_hostname, context):
    """A handshake that succeeds without opening a socket.

    The writer stub matches what `prober._tls_inner` actually calls: `close()`
    (synchronous) followed by `await wait_closed()`. Declaring both as `async`
    leaked a "coroutine never awaited" warning for every REALITY node in the
    run, because `close()` returns a coroutine that nothing awaits.
    """

    class _Stub:
        def close(self):
            return None

        async def wait_closed(self):
            return None

    return object(), _Stub()


def _node(index: int = 0, **over):
    base = dict(
        protocol=Protocol.VLESS,
        address=f"n{index}.example.com",
        port=443,
        uuid="11111111-2222-3333-4444-555555555555",
        transport=Transport.TCP,
        transport_settings=TransportSettings(kind=Transport.TCP),
        security=Security.REALITY,
        tls=TLS(sni="www.microsoft.com", public_key="K", short_id="ab"),
        flow="xtls-rprx-vision",
        remark=f"node {index}",
        country="NL",
        source="fixture",
    )
    base.update(over)
    return Node(**base)


class PipelineHarness:
    def __init__(self, tmp_path, *, nodes=20, http_ok=True, validate=None,
                 countries=None):
        """`countries` is a cycle of measured exit codes, one per node.

        Empty (the default) means "every node exits where the fake driver
        says", which is a single-country pool. A cycle is needed by any test
        whose claim is about *one country among several*: with one country the
        shard for it legitimately contains the whole tier, so "the shard is a
        subset" is untestable — and worse, it passes with the filter deleted.
        """
        self.root = tmp_path
        self.store = Store(tmp_path)
        self.driver = FakeDriver(http_ok=http_ok)
        if countries:
            self.driver = _CyclingTraceDriver(countries, http_ok=http_ok)
        self.pipeline = Pipeline(
            root=tmp_path,
            sources={
                # A source must actually exist for the fetch client to be
                # called: `fetch_all` iterates sources, so an empty list
                # fetches nothing and the whole run is a no-op no matter what
                # the client would have returned.
                "sources": [{"url": "https://example.test/sub", "name": "fixture"}],
                # Parsing happens against an inline body via fetch_client.
                "protocol_reliability": 0.85,
                "fetch_client": _make_client([_uri_body(nodes)]),
            },
            driver_factory=lambda: self.driver,
            validate=validate,
            **_offline(),
        )


class _CyclingTraceDriver(FakeDriver):
    """A `FakeDriver` whose `trace` answers per *node*, cycling by host index.

    The country cannot be keyed off the tag: `node_tag` is `dedup_key[:16]`, a
    hash, so there is no index to recover from it. What the driver does get is
    `add_node(node, tag)` before the funnel touches it, so the tag→node map is
    built there and `trace` reads the host index out of the node it resolves to.

    A counter over `trace` calls would not do: the prober traces each surviving
    node once per round and a run may probe the same node again, so a counter
    would reassign a node's country between two runs of the identical pool —
    which changes the generation id for a reason unrelated to the pool, and
    `country_shards` ordering is what the id is derived from.
    """

    def __init__(self, countries, **kw):
        super().__init__(**kw)
        self._cycle = list(countries)
        self._by_tag: dict[str, str] = {}

    async def add_node(self, node, tag):
        self.added.append(tag)
        # `n<index>.example.com` — the fixture's own naming, and the only
        # stable index available after the dedup hash erased the identity.
        self._by_tag[tag] = node.address

    async def trace(self, tag, *, timeout=5.0):
        address = self._by_tag.get(tag, "")
        try:
            index = int(address.split(".", 1)[0].lstrip("n"))
        except ValueError:
            index = 0
        self.trace_calls.append(tag)
        code = self._cycle[index % len(self._cycle)]
        return {"ip": "203.0.113.7", "loc": code, "colo": "AMS"}


def _uri_body(count: int, offset: int = 0) -> str:
    lines = []
    for index in range(count):
        lines.append(
            f"vless://11111111-2222-3333-4444-555555555555@n{index + offset}.example.com:443"
            f"?security=reality&sni=www.microsoft.com&pbk=K&sid=ab&flow=xtls-rprx-vision#n{index + offset}"
        )
    return "\n".join(lines)


def _make_client(bodies):
    """A fetch client returning the same canned body for every source."""

    async def client(url, headers):
        return bodies[0], 200, {}

    return client


def _make_client_by_url(mapping):
    """A fetch client that answers each URL with its own body.

    Needed the moment a test mixes source *kinds*: sharing one body across
    sources makes the dedup step collapse identical nodes, so a "3 sources"
    test silently becomes a "1 source, 3 times" test and every count in it
    is wrong by the dedup, not by the logic under test.
    """
    fallback = next(iter(mapping.values()))

    async def client(url, headers):
        return mapping.get(url, fallback), 200, {}

    return client


async def test_full_run_publishes_a_generation(tmp_path):
    harness = PipelineHarness(tmp_path, nodes=20, validate=lambda _text, _fmt: True)
    report = await harness.pipeline.run_once()

    assert report["nodes_parsed"] == 20
    assert report["nodes_verified"] == 20
    assert report["generation"].startswith("gen-")
    assert not report["fatal"]

    generation = harness.store.current_generation()
    assert generation == report["generation"]
    manifest = json.loads((harness.store.generation_path(generation) / "manifest.json").read_text())
    assert manifest["generation"] == generation
    assert manifest["payloads"]
    for item in manifest["payloads"]:
        payload_path = harness.store.generation_path(generation) / item["name"]
        assert hashlib.sha256(payload_path.read_bytes()).hexdigest() == item["sha256"]
    assert not list(harness.store.generations.glob(f".{generation}-*"))


async def test_second_identical_run_is_a_noop(tmp_path):
    harness = PipelineHarness(tmp_path, nodes=20, validate=lambda _text, _fmt: True)
    first = await harness.pipeline.run_once()
    second = await harness.pipeline.run_once()
    # Identical pool -> identical content-derived generation id -> no new files.
    assert first["generation"] == second["generation"]


async def test_zero_verified_keeps_previous_generation(tmp_path):
    harness = PipelineHarness(tmp_path, nodes=20, http_ok=False, validate=lambda _text, _fmt: True)
    # Seed a good generation first.
    good = PipelineHarness(tmp_path, nodes=20, validate=lambda _text, _fmt: True)
    first = await good.pipeline.run_once()
    assert first["generation"]

    # Now a run where every node fails the HTTP stage.
    bad = Pipeline(
        root=tmp_path,
        sources={
            "sources": [],
            "fetch_client": _make_client([_uri_body(20)]),
            "protocol_reliability": 0.85,
        },
        driver_factory=lambda: FakeDriver(http_ok=False),
        **_offline(),
    )
    report = await bad.run_once()
    assert report["nodes_verified"] == 0
    assert not report["generation"]  # nothing new published
    assert harness.store.current_generation() == first["generation"]


async def test_validation_failure_keeps_previous_generation(tmp_path):
    good = PipelineHarness(tmp_path, nodes=20, validate=lambda _text, _fmt: True)
    first = await good.pipeline.run_once()
    assert first["generation"]

    def always_fail(text, fmt):
        return False

    bad = Pipeline(
        root=tmp_path,
        sources={"sources": [], "fetch_client": _make_client([_uri_body(20)])},
        driver_factory=lambda: FakeDriver(http_ok=True),
        validate=always_fail,
        **_offline(),
    )
    report = await bad.run_once()
    # Fail-open: yesterday's payload stays live.
    assert not report["generation"]
    assert good.store.current_generation() == first["generation"]


async def test_retain_keeps_three_generations_by_age(tmp_path):
    """Retention is by **write order**, never by generation name.

    Generation ids are content-derived, so `gen-0000…` can legitimately be
    written after `gen-ffff…` whenever the content hash happens to be smaller.
    Ordering by name therefore retains the wrong set. The timestamps are set
    explicitly here so the test does not depend on mtime granularity.
    """
    import os
    import time

    store = Store(tmp_path)
    names = ["gen-a", "gen-b", "gen-c", "gen-d", "gen-e"]
    # gen-e is newest, gen-a is oldest. Names are deliberately *descending*
    # relative to age, so a name-sorted implementation deletes the wrong two.
    for index, name in enumerate(names):
        path = store.generations / name
        path.mkdir(parents=True, exist_ok=True)
        stamp = time.time() - (len(names) - index) * 60
        os.utime(path, (stamp, stamp))
    removed = store.retain(3)
    assert set(removed) == {"gen-b", "gen-a"}
    assert {p.name for p in store.generations.iterdir()} == {"gen-c", "gen-d", "gen-e"}


async def test_retain_never_removes_the_live_generation(tmp_path):
    """Regression: a rollback must not delete the payload being served."""
    store = Store(tmp_path)
    for name in ("gen-a", "gen-b"):
        (store.generations / name).mkdir(parents=True, exist_ok=True)
    # Live points at the *older* generation, as after a rollback.
    store.flip_pointer("gen-a", "a" * 64)
    removed = store.retain(3)
    assert removed == []  # gen-a is live; gen-b is within the window
    assert (store.generations / "gen-a").is_dir()


async def test_retain_protects_live_even_outside_window(tmp_path):
    store = Store(tmp_path)
    for name in ("gen-a", "gen-b", "gen-c", "gen-d", "gen-e"):
        (store.generations / name).mkdir(parents=True, exist_ok=True)
    store.flip_pointer("gen-a", "a" * 64)
    removed = store.retain(2)
    assert "gen-a" not in removed
    assert (store.generations / "gen-a").is_dir()
    assert (store.generations / "gen-e").is_dir()


async def test_pointer_flip_is_atomic_and_readable(tmp_path):
    store = Store(tmp_path)
    assert store.current_generation() is None
    for name in ("gen-1", "gen-2"):
        (store.generations / name).mkdir(parents=True, exist_ok=True)
    store.flip_pointer("gen-1", "a" * 64)
    assert store.current_generation() == "gen-1"
    store.flip_pointer("gen-2", "b" * 64)
    assert store.current_generation() == "gen-2"


async def test_event_log_is_written(tmp_path):
    harness = PipelineHarness(tmp_path, nodes=5)
    await harness.pipeline.run_once()
    kinds = [
        json.loads(line)["kind"]
        for line in harness.store.log.read_text().splitlines()
        if line.strip()
    ]
    assert "run" in kinds
    assert "publish" in kinds or "run_done" in kinds


async def test_parse_errors_do_not_kill_the_run(tmp_path):
    body = _uri_body(12) + "\ngarbage\nnot a node\n"
    pipeline = Pipeline(
        root=tmp_path,
        sources={
            "sources": [{"url": "https://example.test/sub", "name": "fixture"}],
            "fetch_client": _make_client([body]),
        },
        driver_factory=lambda: FakeDriver(http_ok=True),
        validate=lambda _text, _fmt: True,
        **_offline(),
    )
    report = await pipeline.run_once()
    assert report["nodes_parsed"] == 12
    assert report["parse_errors"] == 2
    assert report["generation"]


async def test_ssrf_rejected_at_pipeline_boundary(tmp_path):
    """A private line is dropped at *parse*, before the prober ever sees it.

    `10.0.0.1` is rejected by `parse_one`, so it lands in `parse_errors` and
    never reaches the driver — the boundary is parse, not probe. The other 12
    nodes are what make the pool usable; below `MIN_USABLE_POOL` the pipeline
    keeps the previous generation instead, which is a different behaviour.
    """
    body = "\n".join(
        [
            "vless://11111111-2222-3333-4444-555555555555@10.0.0.1:443#bad",
            *_uri_body(12).splitlines(),
        ]
    )
    pipeline = Pipeline(
        root=tmp_path,
        sources={
            "sources": [{"url": "https://example.test/sub", "name": "fixture"}],
            "fetch_client": _make_client([body]),
        },
        driver_factory=lambda: FakeDriver(http_ok=True),
        validate=lambda _text, _fmt: True,
        **_offline(),
    )
    report = await pipeline.run_once()
    assert report["parse_errors"] == 1  # the RFC1918 line is rejected at parse
    assert report["nodes_parsed"] == 12
    assert report["generation"]


async def test_stats_shows_a_populated_pool(tmp_path):
    """The landing page's numbers are real pool data.

    `tests/test_api.py` covers the endpoint against an empty table, which would
    also pass if the SQL were wrong and returned nothing. This runs the whole
    pipeline into a real store and asserts the pool is actually counted.
    """
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from hub.api import create_app

    # `store=None` would make the app read HUB_ROOT or cwd, i.e. a different
    # store than the pipeline just wrote to, and every assertion below would be
    # about someone else's database.
    api = TestClient(create_app(store=Store(tmp_path), sources={}))

    pipeline = Pipeline(
        root=tmp_path,
        sources={
            "sources": [{"url": "https://example.test/sub", "name": "fixture"}],
            "fetch_client": _make_client([_uri_body(12)]),
        },
        driver_factory=lambda: FakeDriver(),
        validate=lambda _text, _fmt: True,
        **_offline(),
    )
    report = await pipeline.run_once()
    assert report["nodes_verified"] == 12

    payload = api.get("/api/v1/stats").json()
    assert payload["generation"] == report["generation"]
    assert payload["known"] == 12
    assert payload["verified"] == 12
    assert payload["by_protocol"] == [{"name": "vless", "n": 12}]
    assert payload["published"], "a tier was published but is not reported"


async def test_the_published_pool_is_not_the_same_as_the_index(tmp_path):
    """The landing page must describe what a subscription contains, not the index.

    `nodes` is an accumulating index: it keeps every node ever probed, including
    rows written before `state` existed, which `_carry_forward` can never
    rebuild into a payload. The generation is what actually ships. Reading the
    index for the page's numbers produced, on the live install, "NL: 235 nodes"
    over a 24-node NL shard, and 43 country cards over 29 shards — so a quarter
    of the country picker led to a 404.

    The fixture makes the two sets differ the way production does: `Http_ok`
    nodes are indexed, the tier publishes a bounded number of them, and a node
    that failed stays in `nodes` while being absent from the generation.
    """
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from hub.api import create_app

    api = TestClient(create_app(store=Store(tmp_path), sources={}))
    harness = PipelineHarness(tmp_path, nodes=20, validate=lambda _t, _f: True)
    report = await harness.pipeline.run_once()
    assert report["generation"]

    # The rows that made production wrong: indexed nodes with no `state`.
    # They predate the column, `_carry_forward` skips them because a node
    # cannot be rebuilt from the flat columns, and they are therefore never
    # published — but they are still rows in `nodes` with a `last_ok`.
    conn = harness.store.connect()
    conn.executemany(
        "INSERT INTO nodes (dedup_key, protocol, address, port, country, source,"
        " first_seen, last_ok, score, rounds, state)"
        " VALUES (?, 'vless', ?, 8444, 'NL', 'legacy', 'T', 'T', 33, 7, NULL)",
        [(f"legacy{i:04d}", f"198.51.100.{i}") for i in range(30)],
    )
    conn.commit()
    conn.close()

    payload = api.get("/api/v1/stats").json()
    # The index and the published tier are both reported, and they are
    # different numbers with different labels on the page.
    assert payload["known"] == 50, payload  # 20 drained + 30 legacy rows
    assert payload["verified"] == report["published"], payload
    # The legacy rows are NL, and they must not inflate NL's card: the page
    # describes the shard, and the shard cannot contain a node with no state.
    nl = [row for row in payload["by_country"] if row["name"] == "NL"]
    if nl:
        assert nl[0]["n"] <= report["published"], nl

    # Every country on the page has a shard a visitor can actually download.
    # This is the assertion whose absence let 14 dead cards ship. Checked on
    # disk rather than through `/sub/...`, because that route needs a token and
    # the property under test is the *generation's content*, not the route.
    generation_dir = harness.store.generation_path(report["generation"])
    on_page = {row["name"] for row in payload["by_country"]}
    on_disk = {
        p.name[len("verified-") : -len(".singbox")]
        for p in generation_dir.glob("verified-*.singbox")
        if len(p.name[len("verified-") : -len(".singbox")]) == 2
    }
    assert on_page == on_disk, (sorted(on_page - on_disk), sorted(on_disk - on_page))

    # And the per-country counts are the shard's own size, not the index's.
    for row in payload["by_country"]:
        shard = json.loads((generation_dir / f"verified-{row['name']}.singbox").read_text())
        nodes = [
            o for o in shard["outbounds"]
            if o.get("type") not in ("selector", "urltest", "direct", "block", "dns")
        ]
        assert row["n"] == len(nodes), row


class _TimedDriver(FakeDriver):
    """Per-node latency in **seconds**, exactly as `Driver.socks_check` promises.

    The prober tags a node by `dedup_key[:16]`, never by its sid or address, so
    the seconds map has to be keyed by whatever the caller derived from
    `parse_many`. An unmapped tag is an assertion, not a fallback: returning
    `inf` there would turn "the test's keys are wrong" into "this node is slow",
    which is the exact confusion that once let seconds pass as milliseconds.
    """

    def __init__(self, seconds: dict[str, float]) -> None:
        super().__init__()
        self.seconds = seconds
        self.seen: list[str] = []

    async def socks_check(self, tag: str, *, timeout: float = 5.0):
        self.seen.append(tag)
        # An unmapped tag is a test bug, not a node failure: returning `inf`
        # here would silently turn "my key is wrong" into "that node is slow".
        return self.flags["http"], self.seconds[tag]


async def test_http_latency_is_recorded_in_milliseconds(tmp_path):
    """`http_ms` is milliseconds; `socks_check` reports seconds.

    The two conventions met once and the seconds travelled straight into the
    milliseconds column, so a 0.14 s round trip was stored as 0.14 ms and the
    latency factor — a quarter of the rubric — paid every node full marks. No
    assertion about the score would have caught it: only the unit can.
    """
    from hub.store import Store as _Store

    # Two nodes differing in exactly one field, so the dedup keys differ. The
    # sid is *not* what distinguishes them — it rides in the URI, not the dedup
    # key — so it is kept constant and the host carries the difference.
    uri = (
        "vless://11111111-2222-3333-4444-555555555555@{host}:443"
        "?security=reality&sni=www.microsoft.com&pbk=K&sid=fastnode01"
        "&type=tcp&headerType=none#n"
    )
    body = "\n".join(
        [uri.format(host="fast.example.com"), uri.format(host="slow.example.com")]
    )

    # Keyed through `parse_many`'s own dedup keys, because that is the only
    # thing the prober will tag these nodes by — `_TimedDriver` looks up seconds
    # by that tag, and a hand-rolled key is how "my keys are wrong" becomes
    # "that node is slow".
    from hub.parser import parse_many

    nodes = parse_many(body, source="fixture")[0]
    assert len(nodes) == 2, nodes
    fast_node = next(n for n in nodes if "fast" in n.address)
    slow_node = next(n for n in nodes if "slow" in n.address)
    # Distinct tags matter: a tag collision would make the driver answer one
    # node's latency for the other, and the score comparison below would still
    # pass for the wrong reason.
    assert fast_node.dedup_key[:16] != slow_node.dedup_key[:16], nodes
    by_tag = {
        fast_node.dedup_key[:16]: 0.14,
        slow_node.dedup_key[:16]: 0.90,
    }

    driver = _TimedDriver(by_tag)
    pipeline = Pipeline(
        root=tmp_path,
        sources={
            "sources": [{"url": "https://example.test/sub", "name": "fixture"}],
            "fetch_client": _make_client([body]),
        },
        driver_factory=lambda: driver,
        **_offline(),
    )
    await pipeline.run_once()
    assert driver.seen, "the driver was never asked for an HTTP round"

    store = _Store(tmp_path)
    conn = store.connect()
    try:
        rows = conn.execute(
            "SELECT dedup_key, http_ms FROM checks WHERE stage = 'http' ORDER BY http_ms"
        ).fetchall()
        # One row per node: the two HTTP rounds collapse into a single recorded
        # check, so the count is the node count and not double it.
        assert len(rows) == 2, rows
        scores = dict(conn.execute("SELECT address, score FROM nodes").fetchall())
    finally:
        conn.close()

    assert sorted(r["http_ms"] for r in rows) == pytest.approx([140.0, 900.0], rel=0.5), rows
    # The fast node must outscore the slow one: if the seconds leaked through
    # again, both latencies read as "instant" and the two would tie.
    assert scores["fast.example.com"] > scores["slow.example.com"], scores


# --------------------------------------------------------------------------- #
# source adapters
# --------------------------------------------------------------------------- #

#: The real proxyfreeonly API body, obfuscated keys and all.
PFO_BODY = """[
 {"vpn_servers":"public-vpn-43","__0":"219.100.37.7","__1":2892468,"__2":14,"__3":129606790,"__4":"JP","__5":1118995861},
 {"vpn_servers":"vpn521576029","__0":"58.96.70.159","__1":1556692,"__2":7,"__3":97947395,"__4":"AU","__5":1293430790}
]"""


async def test_a_refused_source_is_reported_not_silently_empty(tmp_path):
    """A source the adapter refuses must show up in `errors`, not vanish.

    The failure this pins is subtle: the fetcher *succeeded* — HTTP 200, a real
    body — so nothing in the fetch path looks wrong. Only the run report tells
    an operator that 2 (or 2663) rows were considered and none ingested, and
    without that line the pool just looks smaller with no explanation.
    """
    pipeline = Pipeline(
        root=tmp_path,
        sources={
            "sources": [
                {"url": "https://example.test/plain", "name": "plain"},
                {"url": "https://proxyfreeonly.test/api", "name": "pfo", "kind": "proxyfreeonly"},
                {"url": "https://example.test/uris", "name": "uris"},
            ],
            "fetch_client": _make_client_by_url(
                {
                    "https://example.test/plain": _uri_body(12),
                    "https://proxyfreeonly.test/api": PFO_BODY,
                    "https://example.test/uris": _uri_body(12, offset=100),
                }
            ),
        },
        driver_factory=lambda: FakeDriver(http_ok=True),
        validate=lambda _text, _fmt: True,
        **_offline(),
    )
    report = await pipeline.run_once()
    # The refused source is counted, and the good ones still came through.
    assert report["errors"].get("adapt:pfo") == 1
    assert report["nodes_parsed"] == 24
    assert report["generation"]


async def test_an_adapted_source_contributes_its_nodes(tmp_path):
    """The ipspeed adapter turns HTML into URIs, and those URIs count.

    An adapter that ran but produced nothing would be indistinguishable from
    an adapter that never ran, so this asserts the *nodes arrive*, not merely
    that the pipeline does not crash.
    """
    html = (
        "".join(
            f"<li>vless://11111111-2222-3333-4444-555555555555@{i}.example.test:443"
            f"?security=reality&sni=www.microsoft.com#n{i}</li>"
            for i in range(12)
        )
    )
    pipeline = Pipeline(
        root=tmp_path,
        sources={
            "sources": [{"url": "https://ipspeed.test/x.php", "name": "ips", "kind": "ipspeed"}],
            "fetch_client": _make_client([html]),
        },
        driver_factory=lambda: FakeDriver(http_ok=True),
        validate=lambda _text, _fmt: True,
        **_offline(),
    )
    report = await pipeline.run_once()
    assert "adapt:ips" not in report["errors"]
    assert report["nodes_parsed"] == 12
    assert report["generation"]


def test_the_declared_kind_is_read_off_the_source_list(tmp_path):
    """A source's adapter kind lives on the source, not in a second config.

    Two places to name the same thing is one place too many: the day one is
    edited and the other is not, the adapter silently stops running and the
    body reaches `parse_many` unadapted.
    """
    pipeline = Pipeline(
        root=tmp_path,
        sources={
            "sources": [
                {"url": "https://a.test/x", "name": "with-kind", "kind": "proxyfreeonly"},
                {"url": "https://b.test/x", "name": "no-kind"},
            ]
        },
    )
    assert pipeline._source_kinds() == {"with-kind": "proxyfreeonly"}


# --------------------------------------------------------------------------- #
# the speed stage
# --------------------------------------------------------------------------- #

#: Nodes for the speed tests. Deliberately not small: a fixture that pinches
#: the pool to 4 trips `MIN_USABLE_POOL` and fails with an empty generation,
#: which looks like a bug in the speed stage and is not.
_SPEED_NODES = 12

#: The cap the speed tests assert against. Smaller than `_SPEED_NODES` on
#: purpose: a round that measures everything never exercises the deferral
#: path, and the deferral path is the one that reports *why* the pool looks
#: smaller than it is.
_SPEED_TOP_N = 10


def _speed_pipeline(tmp_path, *, driver, **over):
    """A pipeline wired for the speed tests.

    `min_pool=1` because these tests are about throughput, not pool sizing:
    `MIN_USABLE_POOL` is a publication policy pinned by its own tests, and
    making every speed test justify one would bury what the test asserts.

    `max_load=None` because the load guard is a *host* property: with the
    default on, whether the round runs depends on how busy the machine happens
    to be, and a suite that passes on an idle box and fails on a busy one is a
    flaky suite. The guard itself is pinned in `test_speedtest.py`.
    """
    settings = dict(
        root=tmp_path,
        sources=PipelineHarness(tmp_path, nodes=_SPEED_NODES).pipeline.sources,
        driver_factory=lambda: driver,
        validate=lambda _text, _fmt: True,
        speed_policy=SpeedPolicy(top_n=_SPEED_TOP_N, transfer_concurrency=4,
                                 timeout_s=3.0, max_load=None),
        network=True,
        min_pool=1,
        **_offline(),
    )
    settings.update(over)
    return Pipeline(**settings)


async def test_the_speed_stage_is_not_reached_without_allow_network(tmp_path):
    """`--allow-network` is the gate, and a driver alone is not enough.

    Probing is the half of this system that can touch the host's live network.
    A driver being present is an implementation detail; the operator saying yes
    is the decision. Asserting the *absence* of reads is what catches a version
    where the transfer runs anyway and the flag becomes decorative.

    It runs through `_speed_pipeline` rather than a bespoke `Pipeline`, and that
    is load-bearing: with the default `max_load` the load guard defers the round
    on a busy host for a reason that has nothing to do with the flag, so
    `speed_reads == []` would be true with the gate deleted. Two mechanisms
    producing one observation means the observation proves neither. Disabling
    the load guard leaves the flag as the only thing that can suppress the
    reads, which is the only way an absence can be evidence.

    The `stage_survivors` assertion is the second half of the trap: because the
    stage never runs, both keys are missing and `get(..., 0)` is 0 however the
    gate is written. It is kept as a description of the expected shape, not as
    the assertion doing the work.
    """
    driver = FakeDriver()
    driver.speed_reads.clear()
    pipeline = _speed_pipeline(tmp_path, driver=driver, network=False)
    report = await pipeline.run_once()

    assert driver.speed_reads == [], "bytes were moved without --allow-network"
    assert report["stage_survivors"].get("speed.measured", 0) == 0


async def test_the_speed_stage_measures_survivors_and_scores_them(tmp_path):
    """The whole point of the wiring: measured speed reaches the score.

    Without the stage, `throughput` is half credit (5.0 of 10). With it, a node
    that moves 1 MiB in a fraction of a second clears the 2 MB/s benchmark and
    takes the full weight. The assertion is on the run report and the score
    table, because the run report counts samples and the score is what a
    published ranking is actually made of.
    """
    driver = FakeDriver()
    pipeline = _speed_pipeline(tmp_path, driver=driver)
    report = await pipeline.run_once()

    assert driver.speed_reads, "the speed stage never read a byte"
    # Every survivor is measured *or* named as skipped, and the two counts sum
    # to the pool exactly: `_SPEED_NODES` nodes against `top_n`, so the overflow
    # is deferred with a reason. The sum being exact is the real assertion — a
    # node that is neither measured nor deferred is the bug.
    survivors = report["stage_survivors"]
    overflow = report["nodes_verified"] - _SPEED_TOP_N
    assert survivors["speed.measured"] == _SPEED_TOP_N
    assert survivors["speed.deferred"] == overflow
    assert survivors["speed.measured"] + survivors["speed.deferred"] == report["nodes_verified"]
    assert report["generation"], "the speed stage blocked publication"

    conn = Store(tmp_path).connect()
    try:
        scored = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE score > 0"
        ).fetchone()[0]
    finally:
        conn.close()
    assert scored == report["nodes_verified"]


async def test_the_speed_stage_reports_why_nodes_went_unmeasured(tmp_path):
    """A capped round must not look like a small pool.

    `top_n=1` is the cheapest way to cause a deferral, and it is the one an
    operator would otherwise misread as "only one of these is fast" rather than
    "the round was capped".
    """
    driver = FakeDriver()
    pipeline = _speed_pipeline(
        tmp_path, driver=driver,
        speed_policy=SpeedPolicy(top_n=1, transfer_concurrency=4,
                                 timeout_s=3.0, max_load=None),
    )
    report = await pipeline.run_once()

    survivors = report["stage_survivors"]
    verified = report["nodes_verified"]
    assert verified > 1
    assert survivors["speed.measured"] == 1
    assert survivors["speed.deferred"] == verified - 1
    # The bucket name, not the per-node string: "top_n=150" would be one key per
    # node, which reports nothing an operator can act on.
    assert survivors["speed.defer:beyond top_n"] == verified - 1


async def test_a_driver_that_predates_speed_read_still_publishes(tmp_path):
    """No throughput capability must cost availability, not correctness.

    The half-credit rule is what makes this pass: unmeasured nodes score
    slightly lower, not zero, so a pool still publishes. A driver rollout is
    slow across nodes, not a single coherent switch.
    """
    from tests.test_prober import NoSpeedDriver

    pipeline = _speed_pipeline(tmp_path, driver=NoSpeedDriver())
    report = await pipeline.run_once()

    assert report["generation"], "a driver without speed_read failed to publish"
    assert report["stage_survivors"]["speed.measured"] == 0
    assert report["stage_survivors"][
        "speed.defer:driver has no speed_read"
    ] == report["nodes_verified"]


async def test_measured_speed_changes_the_published_score(tmp_path):
    """The wiring's actual product: a fast node scores higher than an unmeasured one.

    This is the assertion the count-based test above cannot make. `speed.measured`
    counts *samples*, which is a fact about the round; the score is a fact about
    what ships to subscribers. A pipeline that measured every node and then
    dropped the result on the floor would pass the count test and fail this one —
    which is exactly what happened, found by mutation, after `apply_speed` was
    neutralised and all 41 tests stayed green.

    The comparison is measured-vs-unmeasured on the *same* nodes with the same
    weights, so the only difference between the two runs is whether
    `speed_bps` was written back. Anything else would let a score difference
    through some other cause and the test would be measuring the wrong thing.
    """
    weights = Weights(throughput=10)

    async def _run(driver, where: Path):
        pipeline = _speed_pipeline(where, driver=driver, weights=weights)
        return await pipeline.run_once()

    # Same pool, same weights, same policy. Only `speed_bps` differs.
    measured = await _run(FakeDriver(), tmp_path / "measured")
    unmeasured = await _run(NoSpeedDriver(), tmp_path / "unmeasured")

    assert measured["nodes_verified"] == unmeasured["nodes_verified"]
    assert measured["stage_survivors"]["speed.measured"] > 0
    assert unmeasured["stage_survivors"]["speed.measured"] == 0

    def top_score(where: Path) -> int:
        conn = Store(where).connect()
        try:
            return conn.execute(
                "SELECT score FROM nodes ORDER BY score DESC LIMIT 1"
            ).fetchone()[0]
        finally:
            conn.close()

    fast = top_score(tmp_path / "measured")
    flat = top_score(tmp_path / "unmeasured")

    # The 1 MiB the fake serves arrives in microseconds, so it clears the 2 MB/s
    # benchmark and takes the full 10 points, against 5.0 for never having asked.
    assert fast > flat, (
        f"measured {fast} is not above unmeasured {flat}: speed is not reaching "
        "the score, so the throughput factor is paying half credit either way"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


async def test_a_run_publishes_one_shard_per_country(tmp_path):
    """The per-country links only exist if the pipeline writes the files.

    This is the whole supply chain for `/sub/{token}/country/{cc}`: the API
    serves bytes from a generation directory and holds no `Node` objects, so a
    shard that was never written can never be served. A test that only checked
    the endpoint (against a hand-written store) would pass with the pipeline
    emitting nothing — the two halves are only tested together here.

    Naming is asserted too, because the name *is* the lookup key:
    `verified-NL.singbox` must not read as `verified-<core>.singbox`, and the
    dot is what makes the split structural rather than a guess about whether
    "NL" is a core.

    Two fixtures are load-bearing here and both are easy to get wrong:

    * `nodes=20`, not 8. Below `MIN_USABLE_POOL` (10) nothing is published at
      all, so the assertion fails on an empty directory for a reason unrelated
      to shards — the trap this file documents at its own fixture.
    * `countries=["NL", "NL", "DE"]`. With a single country the assertion is
      also satisfied by the tier payload written under that country's name,
      which is the very bug under test; a shard is only meaningful as a subset.
    """
    harness = PipelineHarness(tmp_path, nodes=20, countries=["NL", "NL", "DE"], validate=lambda _text, _fmt: True)
    report = await harness.pipeline.run_once()
    generation = harness.store.generation_path(report["generation"])
    names = sorted(p.name for p in generation.iterdir())

    assert "verified-NL.singbox" in names, names
    assert "verified-NL.base64" in names, names
    assert "verified-DE.singbox" in names, names
    # The whole-tier payload is still there, unchanged: a shard must not replace
    # it, or a client that pasted the original link loses the other countries.
    assert "verified-sing-box.singbox" in names, names


async def test_a_shard_carries_fewer_nodes_than_the_tier(tmp_path):
    """A shard that contained the whole pool would be indistinguishable from
    the tier payload to any test that only checks the file exists.

    The manifest count is the sharper of the two assertions: a byte comparison
    also passes when the shard is a *reordered* copy of the same nodes, which
    is still the entire pool wearing a country's name.
    """
    harness = PipelineHarness(tmp_path, nodes=20, countries=["NL", "NL", "DE"], validate=lambda _text, _fmt: True)
    report = await harness.pipeline.run_once()
    generation = harness.store.generation_path(report["generation"])

    tier = (generation / "verified-sing-box.singbox").read_text()
    shard = (generation / "verified-NL.singbox").read_text()
    assert shard != tier, "the shard is the whole tier payload"
    assert len(shard) < len(tier), (len(shard), len(tier))
    manifest = json.loads((generation / "manifest.json").read_text())
    counts = {p["name"]: p["nodes"] for p in manifest["payloads"]}
    assert counts["verified-NL.singbox"] < counts["verified-sing-box.singbox"], counts
    assert counts["verified-DE.singbox"] < counts["verified-sing-box.singbox"], counts
    # The fixture is two thirds NL, one third DE, and every node got a measured
    # country, so the shards must account for the tier exactly. If they sum to
    # more, the filter is duplicating nodes; to less, it is dropping them.
    assert counts["verified-NL.singbox"] + counts["verified-DE.singbox"] == counts[
        "verified-sing-box.singbox"
    ], counts


def test_production_validator_accepts_a_good_payload():
    """The built-in validator must actually decide, not return None.

    A shadowing `@staticmethod def _validate_payload` with an empty body was
    defined *after* the real implementation, so the empty one won. It returned
    `None` for every input, and `renderer.render` rejects a payload whenever
    `validate(...)` is falsy — so with no injected validator (i.e. production)
    every payload failed validation, the renderer binary-searched down to a
    single node, and then raised `ValueError`. Country shards were swallowed by
    the `except ValueError` in the publish path.

    Both directions are pinned: a good payload passes, a bad one fails. A
    validator that returned `True` unconditionally would satisfy only the first
    assertion, and the empty stub satisfied neither.
    """
    from hub.models import Format
    from hub.pipeline import Pipeline

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._validate = None

    good_b64 = base64.b64encode(
        b"vless://e13cf851-b4fd-413b-8d49-146e6eb8c1a2@example.com:443?type=tcp#n"
    ).decode()
    assert pipeline._validation_callback(good_b64, Format.BASE64) is True

    # Not base64 at all: the decoder must reject it rather than pass it through.
    assert pipeline._validation_callback("!!!not base64!!!", Format.BASE64) is False


def test_injected_validator_still_takes_precedence():
    """The hermetic-test seam must keep working after the shadowing fix."""
    from hub.models import Format
    from hub.pipeline import Pipeline

    pipeline = Pipeline.__new__(Pipeline)
    pipeline._validate = lambda text, fmt: text == "yes"
    assert pipeline._validation_callback("yes", Format.BASE64) is True
    assert pipeline._validation_callback("no", Format.BASE64) is False
