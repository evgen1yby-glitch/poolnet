"""Per-source line filters and the quarantine cap, at the pipeline level.

Two mechanisms, both of which were once wired up and then read by nobody.

`Source.include` and `Source.exclude` are parsed by `load_sources` and tested
in `tests/test_fetcher.py`. Until `run_once` started consulting them they were
never *read* — a source could declare `exclude: ['badexample']` and still
contribute every one of its lines. That is the shape these tests exist to
catch: an option documented in the config file, validated by the loader, and
then ignored by the only consumer that matters.

The quarantine cap is the other half. `Fetcher.quarantine_cap` reports that a
source with fewer than `QUARANTINE_ROUNDS` rounds of history may only contribute
`QUARANTINE_CAP` nodes, so one brand-new URL listing ten thousand dead nodes
cannot set the pool's character on its first day. The *number* comes from the
fetcher; whether it is applied at all is the pipeline's decision, which is why
the cap is tested here and not in `test_fetcher_requests.py`.

Every test drives a full `run_once` and asserts on `report["nodes_parsed"]` or
`report["errors"]`, because those are what a broken filter actually changes.
Asserting on `_filter_body`'s return value would pass while the pool stayed
unfiltered — the exact escape the mutations below were written to catch.

A note on fixture shape: all three filter tests share one body of 17 uniquely
hostnamed vless nodes, 3 of which carry the segment `badexample`. Unique hosts
matter because `run_once` deduplicates on `dedup_key` (protocol+uuid+host+port),
so a body of identical nodes collapses to one and every count in the test would
be wrong by the dedup rather than by the logic under test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tests.test_pipeline import Pipeline  # noqa: E402
from tests.test_prober import FakeDriver  # noqa: E402
from hub.fetcher import QUARANTINE_CAP, QUARANTINE_ROUNDS  # noqa: E402
from hub.store import Store  # noqa: E402

from tests.test_pipeline import _make_client, _uri_body, _handshake_ok  # noqa: E402
from tests.test_prober import Concurrency  # noqa: E402


def _offline():
    """See `tests/test_pipeline._offline`: collapse both network stages."""
    return dict(
        concurrency=Concurrency(tcp=5, tls=5, http=5, round2_gap_s=0.0),
        connect=_dial_nowhere,
        handshake=_handshake_ok,
    )


async def _dial_nowhere(address, port, **kwargs):
    raise OSError("no network in a filter test")


#: 17 vless nodes, 3 of them carrying the segment `badexample`.
FILTER_BODY = "\n".join(
    f"vless://11111111-2222-3333-4444-555555555555@{host}.example.com:443"
    f"?security=reality&sni=www.microsoft.com&pbk=K&sid=ab&flow=xtls-rprx-vision#{remark}"
    for host, remark in [
        *((f"keep{i}", f"keep{i}") for i in range(14)),
        *((f"bad{i}", f"badexample{i}") for i in range(3)),
    ]
)

_TOTAL = 17
_MARKED = 3
_CLEAN = 14


def _pipeline(root, **source_over):
    """A pipeline over `FILTER_BODY` with one source, always named `fixture`."""
    source = {"url": "https://example.test/sub", "name": "fixture"}
    source.update(source_over)
    return Pipeline(
        root=root,
        sources={
            "sources": [source],
            "protocol_reliability": 0.85,
            "fetch_client": _make_client([FILTER_BODY]),
        },
        driver_factory=lambda: FakeDriver(http_ok=True),
        **_offline(),
    )


async def test_no_filters_means_the_whole_body(tmp_path):
    """The baseline every other test here is measured against.

    Without this, `nodes_parsed == 14` in the include test has nothing to be
    relative to: the same assertion would also hold if the parser only ever
    produced 14 nodes from any body. This is the number that makes the two
    filter tests *discriminating* rather than merely passing.
    """
    report = await _pipeline(tmp_path).run_once()
    assert report["nodes_parsed"] == _TOTAL, report
    assert "quarantined" not in report["errors"], report


async def test_an_include_filter_keeps_only_matching_lines(tmp_path):
    """The whitelist form: "this source is vless, take nothing else".

    A curated source declaring `include: ['^vless']` on a body that also holds
    trojan lines must contribute the vless ones and none of the others. The
    mutation that deletes the include guard leaves all 14 vless plus 3 trojan
    reaching the parser, so the parsed count is 17, not 14 — which is the only
    reason this assertion is worth making.
    """
    body = FILTER_BODY + "\n" + "\n".join(
        f"trojan://password@t{i}.example.com:443?security=tls&sni=www.microsoft.com#t{i}"
        for i in range(3)
    )
    pipeline = Pipeline(
        root=tmp_path,
        sources={
            "sources": [
                {"url": "https://example.test/sub", "name": "fixture",
                 "include": ["^vless"]}
            ],
            "protocol_reliability": 0.85,
            "fetch_client": _make_client([body]),
        },
        driver_factory=lambda: FakeDriver(http_ok=True),
        **_offline(),
    )
    report = await pipeline.run_once()

    # The 3 trojan lines never reach the parser: `_filter_body` drops them
    # *before* parsing, so they are not recorded as parse errors either.
    assert report["nodes_parsed"] == _TOTAL, report
    assert report["parse_errors"] == 0, (
        "lines the operator excluded were not filtered, they were parsed and "
        "rejected — a filter and a parse failure are different things"
    )


async def test_an_exclude_filter_drops_matching_lines(tmp_path):
    """The same guard from the other direction, pinned separately.

    Written as its own test rather than folded into the include one because the
    two are separate `continue` statements in `_filter_body`: a run that deleted
    only one of them would look identical to a test that only checked the other.
    3 marked lines are dropped, 14 clean ones survive.
    """
    report = await _pipeline(tmp_path, exclude=["badexample"]).run_once()
    assert report["nodes_parsed"] == _CLEAN, report


async def test_exclude_narrows_what_include_kept(tmp_path):
    """Both filters at once, and the order between them.

    `include` narrows first, then `exclude` removes from what survived, which is
    the documented combination: "vless nodes, but not the example ones". The
    count is 14 and not 17, which is only true if both ran — an unfiltered run
    parses 17 and an exclude-only run on this body also parses 14, so the
    include is what makes the pair discriminating rather than redundant.
    """
    body = FILTER_BODY + "\n" + "\n".join(
        f"trojan://password@t{i}.example.com:443?security=tls&sni=www.microsoft.com#t{i}"
        for i in range(3)
    )
    pipeline = Pipeline(
        root=tmp_path,
        sources={
            "sources": [
                {"url": "https://example.test/sub", "name": "fixture",
                 "include": ["^vless"], "exclude": ["badexample"]}
            ],
            "protocol_reliability": 0.85,
            "fetch_client": _make_client([body]),
        },
        driver_factory=lambda: FakeDriver(http_ok=True),
        **_offline(),
    )
    report = await pipeline.run_once()
    assert report["nodes_parsed"] == _CLEAN, report
    assert report["parse_errors"] == 0, report


async def test_an_uncompilable_filter_raises_rather_than_being_ignored(tmp_path):
    """A typo'd regex must not silently mean "no filter".

    `include: ['(']` can only be a mistake. The previous handling swallowed it
    into the event log and carried on unfiltered, which reads identically to a
    source that declared no filters at all — the opposite of what was written.
    Raising names the source and the pattern, so the operator fixes the config.

    Deliberately not a "the run survives" test: a run that survives a broken
    filter while publishing every line it was meant to exclude is the bug.
    """
    pipeline = _pipeline(tmp_path, include=["("])
    with pytest.raises(ValueError, match="fixture"):
        await pipeline.run_once()


async def test_a_large_new_source_is_not_throttled_to_a_trickle(tmp_path):
    """A new source contributes everything it offers, up to a generous cap.

    The cap was 50 nodes for 10 rounds, which gated the pool's growth on
    wall-clock time: a ~7000-node source needed 35 days to be fully considered,
    and the pool stayed thin while the sources that could fill it sat throttled.
    Volume was never the danger — every node is probed before publication, so a
    source listing 7000 dead links contributes 7000 failures and nothing else.

    The fixture offers 120 nodes: above the old cap, far below the new one, which
    is the interval where the fix is observable. Nothing is dropped.
    """
    big = _uri_body(120)
    pipeline = Pipeline(
        root=tmp_path,
        sources={
            "sources": [{"url": "https://example.test/fresh", "name": "fresh"}],
            "protocol_reliability": 0.85,
            "fetch_client": _make_client([big]),
        },
        driver_factory=lambda: FakeDriver(http_ok=True),
        **_offline(),
    )
    report = await pipeline.run_once()

    assert report["nodes_parsed"] == 120, report
    assert report["errors"].get("quarantined", 0) == 0, report
    assert QUARANTINE_CAP > 120, "a source this size must not be throttled"


async def test_a_source_beyond_the_cap_is_still_capped(tmp_path):
    """The cap still binds, so it remains a cap and not a decoration.

    Raising it to 2000 is a threshold change, not a removal. A source offering
    more than the cap is parsed up to the cap and the remainder is counted as
    quarantined, which is what keeps the number honest in the run report.
    """
    from hub import fetcher as fetcher_module

    original = fetcher_module.QUARANTINE_CAP
    try:
        # Lower the cap for the fixture rather than build a 2000-node body:
        # the question is whether the mechanism binds, not what the number is.
        fetcher_module.QUARANTINE_CAP = 40
        big = _uri_body(120)
        pipeline = Pipeline(
            root=tmp_path,
            sources={
                "sources": [{"url": "https://example.test/fresh2", "name": "fresh2"}],
                "protocol_reliability": 0.85,
                "fetch_client": _make_client([big]),
            },
            driver_factory=lambda: FakeDriver(http_ok=True),
            **_offline(),
        )
        report = await pipeline.run_once()
    finally:
        fetcher_module.QUARANTINE_CAP = original

    assert report["nodes_parsed"] == 40, report
    assert report["errors"].get("quarantined") == 80, report


async def test_the_cap_lifts_once_a_source_has_history(tmp_path):
    """The cap expires, and the expiry is keyed by **URL**.

    This is the test that pins the bug `quarantine_cap` had: it was called with
    `item.source`, the source *name*, while every other state accessor
    (`state`, `note_yield`, `is_disabled`) is keyed by the URL. The name-keyed
    lookup therefore read a dictionary entry nothing ever wrote and reported
    "0 rounds" for every source on every round — so the cap applied forever, and
    no amount of good behaviour ever lifted it.

    The two halves are asserted together because they are one comparison: a
    name-keyed cap passes the fresh half and fails this one, and a cap of
    `None` fails the fresh one. Neither single-side assertion would notice.
    """
    big = _uri_body(120)

    with_history = tmp_path / "history"
    Store(with_history).save_source_state(
        "https://example.test/established", rounds=QUARANTINE_ROUNDS
    )
    pipeline = Pipeline(
        root=with_history,
        sources={
            "sources": [
                {"url": "https://example.test/established", "name": "established"}
            ],
            "protocol_reliability": 0.85,
            "fetch_client": _make_client([big]),
        },
        driver_factory=lambda: FakeDriver(http_ok=True),
        **_offline(),
    )
    report = await pipeline.run_once()

    assert report["nodes_parsed"] == 120, (
        "a source with enough history is still capped: quarantine_cap is not "
        "reading the state the run persists"
    )
    assert "quarantined" not in report["errors"], report


async def test_one_round_short_of_quarantine_is_still_quarantined(tmp_path):
    """The boundary is exactly `QUARANTINE_ROUNDS`, not "more than nothing".

    A cap keyed on anything looser — `rounds > 0`, say — would let a source with
    one good round contribute without limit, which is the first day the cap is
    most needed. `QUARANTINE_ROUNDS - 1` is the only value that separates
    `>=` from `>`.
    """
    big = _uri_body(120)
    Store(tmp_path).save_source_state(
        "https://example.test/nine", rounds=QUARANTINE_ROUNDS - 1
    )
    pipeline = Pipeline(
        root=tmp_path,
        sources={
            "sources": [{"url": "https://example.test/nine", "name": "nine"}],
            "protocol_reliability": 0.85,
            "fetch_client": _make_client([big]),
        },
        driver_factory=lambda: FakeDriver(http_ok=True),
        **_offline(),
    )
    report = await pipeline.run_once()

    # The fixture offers 120 nodes and the cap is 2000, so the cap must NOT be
    # the binding constraint — every offered node is parsed. That is the point
    # of the change: the cap exists to stop a source dominating, not to gate the
    # pool's growth on wall-clock time.
    assert report["nodes_parsed"] == 120, report
    assert report["nodes_parsed"] > 50, "the old per-round cap is back"


async def test_a_productive_round_records_the_source_state_for_next_time(tmp_path):
    """The counters the whole scheme depends on are written by the run.

    Without this the quarantine cap never lifts and the circuit breaker never
    trips, because both read state nothing produces. Asserted against a fresh
    `load_source_states` on a reopened store, so it is the file on disk being
    read rather than the in-memory objects from this run.
    """
    await _pipeline(tmp_path).run_once()

    states = Store(tmp_path).load_source_states()
    assert "https://example.test/sub" in states, states
    state = states["https://example.test/sub"]
    assert state["rounds"] >= 1, state
    assert state["empty_rounds"] == 0, state
    assert state["last_ok"], "a productive round records when it succeeded"
    assert state["etag"] == "", "no ETag was sent, so none may be persisted"


async def test_a_source_with_no_name_is_keyed_by_its_url(tmp_path):
    """An unnamed source must not behave differently from a named one.

    `Source.key` falls back to the URL when `name` is empty, so an unnamed
    source's filters and kinds are addressed by its URL — the one case where the
    name-keyed and URL-keyed spellings coincide. This is what makes the cap bug
    invisible in a config where every source is named: the fix is only observable
    when the two keys differ, and it differs for every named source.
    """
    big = _uri_body(120)
    Store(tmp_path).save_source_state(
        "https://example.test/anon", rounds=QUARANTINE_ROUNDS
    )
    pipeline = Pipeline(
        root=tmp_path,
        sources={
            "sources": ["https://example.test/anon"],
            "protocol_reliability": 0.85,
            "fetch_client": _make_client([big]),
        },
        driver_factory=lambda: FakeDriver(http_ok=True),
        **_offline(),
    )
    report = await pipeline.run_once()
    assert report["nodes_parsed"] == 120, report


def test_the_verified_cap_admits_a_country_that_one_source_holds():
    """The per-source cap must not delete countries the pool actually has.

    Anti-Sybil is the cap's purpose, but at 15 it was also removing thin
    countries, because a country with one or two nodes in the pool usually has
    them from whichever source carries the most nodes overall. Measured on the
    real pool: caps of 15, 25 and 40 all yield the same 15 countries, and only
    at 60 do BR, CA and LT reappear. The cap now has to be high enough for the
    pool the hub actually has, not for a pool of thousands.
    """
    from hub.models import Node, Protocol, Score, Security, Transport, TransportSettings, TLS
    from hub.tiers import DEFAULT_POLICIES, Tier, build_tiers

    def node(country: str, source: str, n: int) -> Node:
        return Node(
            protocol=Protocol.VLESS,
            address=f"{country}{n}.example.com",
            port=443,
            uuid=f"11111111-2222-3333-4444-{n:012d}",
            transport=Transport.TCP,
            transport_settings=TransportSettings(kind=Transport.TCP),
            security=Security.REALITY,
            tls=TLS(sni="www.example.com", fingerprint="chrome", public_key="K", short_id="ab"),
            country=country,
            source=source,
        )

    entries = []
    # 60 nodes from one big source, and a single BR node that only that same
    # source carries — the shape of the real pool.
    for i in range(90):
        entries.append((node("NL", "big", i), Score(total=40, latency=0, availability=0,
            jitter=0, source_history=0, protocol_history=0, throughput=0,
            fingerprint_resistance=0, geo_integrity=0, rubric_version="t"), 1))
    entries.append((node("BR", "big", 99), Score(total=39, latency=0, availability=0,
        jitter=0, source_history=0, protocol_history=0, throughput=0,
        fingerprint_resistance=0, geo_integrity=0, rubric_version="t"), 1))

    built = build_tiers(entries, DEFAULT_POLICIES)
    verified = built[Tier.VERIFIED]
    countries = {e.node.country for e in verified}
    assert "BR" in countries, f"BR was capped away: {sorted(countries)}"

    # The cap still exists and still binds — this is a threshold change, not a
    # removal, so a source can never own the whole tier.
    policy = next(p for p in DEFAULT_POLICIES if p.tier is Tier.VERIFIED)
    assert policy.max_per_source > 0
    assert policy.max_per_source < 150, "the cap stopped being a cap"


def test_geo_lookup_fills_countries_and_caches_them(tmp_path):
    """A node whose exit country could not be measured gets one from geo-IP.

    Cloudflare's trace returns `XX` for a node it cannot place, and the prober
    deliberately keeps that as "unknown" rather than guessing from the hostname.
    The result was a client group called "🌐 XX 5" — five working nodes the user
    cannot pick by country, which is the one thing the grouping exists for.

    Geo-IP is the honest source: it resolves the *address*, so it is a measured
    fact rather than a guess from a name, and it is only consulted for nodes the
    authoritative check could not answer. Results are cached in the database, so
    one address costs one lookup ever — the free tier is 45 requests/minute.
    """
    from hub.geo import GeoCache, lookup_countries

    calls: list[list[str]] = []

    def fake_fetch(addresses: list[str]) -> dict[str, str]:
        calls.append(list(addresses))
        return {a: "US" for a in addresses}

    cache = GeoCache(tmp_path / "hub.db")
    try:
        first = lookup_countries(["1.2.3.4", "5.6.7.8"], cache=cache, fetch=fake_fetch)
        assert first == {"1.2.3.4": "US", "5.6.7.8": "US"}
        assert len(calls) == 1, calls
        assert sorted(calls[0]) == ["1.2.3.4", "5.6.7.8"]

        # Second call hits the cache: no network at all.
        calls.clear()
        again = lookup_countries(["1.2.3.4"], cache=cache, fetch=fake_fetch)
        assert again == {"1.2.3.4": "US"}
        assert calls == [], "a cached address must not be looked up again"

        # An address with no answer is cached as empty, so a dead lookup is not
        # retried every round.
        empty = lookup_countries(["9.9.9.9"], cache=cache, fetch=lambda a: {})
        assert empty == {}
        calls.clear()
        lookup_countries(["9.9.9.9"], cache=cache, fetch=fake_fetch)
        assert calls == [], "a negative result must be cached too"
    finally:
        cache.close()


def test_geo_lookup_never_returns_a_bogus_code(tmp_path):
    """Only a two-letter code is stored; anything else is treated as no answer.

    The same rule the prober applies to Cloudflare's `loc`: a full country name
    or a sentinel like `XX` would split one country into two groups, which is
    silent and worse than "unknown".
    """
    from hub.geo import GeoCache, lookup_countries

    cache = GeoCache(tmp_path / "hub.db")
    try:
        got = lookup_countries(
            ["1.1.1.1", "2.2.2.2", "3.3.3.3"],
            cache=cache,
            fetch=lambda a: {"1.1.1.1": "United States", "2.2.2.2": "XX", "3.3.3.3": "de"},
        )
        assert got == {"3.3.3.3": "DE"}, got
    finally:
        cache.close()


def test_node_survives_a_round_trip_through_json():
    """A stored node must rebuild byte-identically, credentials included.

    The database keeps only `dedup_key`/`address`/`port`/`country`, which is
    enough to *recognise* a node and not enough to *reconstruct* one: the uuid,
    the password and the transport settings are exactly what a render needs and
    exactly what was missing. Any attempt to carry a node between rounds without
    them produces a placeholder that fails validation immediately — which is how
    a 150-node pool became a 10-node one.

    Every field is asserted, because a partial round trip is the failure that
    looks like success: the node rebuilds, renders, and connects nowhere.
    """
    from hub.models import Node, Protocol, Security, Transport, TransportSettings, TLS
    from hub.store_state import node_from_json, node_to_json

    node = Node(
        protocol=Protocol.VLESS,
        address="a.example.com",
        port=443,
        uuid="11111111-2222-3333-4444-555555555555",
        transport=Transport.WS,
        transport_settings=TransportSettings(kind=Transport.WS, host="h.example.com", path="/p"),
        security=Security.REALITY,
        tls=TLS(sni="s.example.com", fingerprint="chrome", alpn=("h2", "http/1.1"),
                public_key="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8", short_id="ab"),
        flow="xtls-rprx-vision",
        source="src",
        remark="r",
        country="NL",
    )
    back = node_from_json(node_to_json(node))
    assert back == node, (back, node)
    assert back.dedup_key == node.dedup_key


def test_a_password_is_round_tripped_too():
    """The credential-bearing fields are the ones that were missing.

    Asserted separately from the field-by-field case because a serializer that
    forgets a password still round-trips a VLESS node — its identity lives in
    the uuid — and the loss would only surface as nodes that cannot connect.
    """
    from hub.models import Node, Protocol
    from hub.store_state import node_from_json, node_to_json

    for proto, kwargs in (
        (Protocol.TROJAN, {"password": "p@ss:word/with?chars"}),
        (Protocol.SHADOWSOCKS, {"password": "pw", "method": "aes-256-gcm"}),
        (Protocol.HYSTERIA2, {"password": "pw", "obfs": "salamander", "obfs_password": "op"}),
    ):
        node = Node(protocol=proto, address="a.example.com", port=443, **kwargs)
        assert node_from_json(node_to_json(node)) == node, proto


def test_a_node_that_cannot_be_rebuilt_is_skipped_not_faked(tmp_path):
    """Unreadable state must drop the node, never invent one.

    The failure this guards against is the one that already happened: a
    placeholder rebuilt from partial data passes every check up to the render
    and then produces a payload where most entries are dead. Dropping is
    visible; faking is not.
    """
    from hub.store_state import node_from_json

    assert node_from_json("{not json") is None
    assert node_from_json('{"protocol": "nonsense", "address": "a", "port": 1}') is None
    assert node_from_json("") is None
    # A valid node missing its required address is not a node.
    assert node_from_json('{"protocol": "vless", "address": "", "port": 443}') is None


def test_the_pool_is_the_union_of_recently_proven_nodes(tmp_path):
    """A node proven working an hour ago must survive a round that missed it.

    Measured on the live pool: four consecutive rounds verified 68, 239, 72 and
    57 nodes and shared only 316 distinct nodes between them — so publishing
    each round on its own made countries appear and disappear for no reason a
    user could see, and a link that worked at 16:40 was thinner at 17:01.

    The window is a *freshness* bound, not an optimisation: a check from longer
    ago than one probe cycle is evidence about the past, and a node that has
    since died must not be published forever.
    """
    from hub.models import Node, Protocol
    from hub.pipeline import Pipeline
    from hub.store_state import node_to_json

    pipeline = Pipeline(root=tmp_path, **_offline())
    conn = pipeline.store.connect()

    fresh = Node(protocol=Protocol.VLESS, address="a.example.com", port=443,
                 uuid="11111111-2222-3333-4444-555555555555", country="NL")
    old = Node(protocol=Protocol.VLESS, address="b.example.com", port=443,
               uuid="22222222-3333-4444-5555-666666666666", country="DE")
    conn.execute(
        "INSERT INTO nodes (dedup_key, protocol, address, port, country, source,"
        " first_seen, last_ok, score, rounds, state) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (fresh.dedup_key, "vless", fresh.address, 443, "NL", "s",
         "2026-10-16T10:00:00+00:00", "2026-10-16T10:00:00+00:00", 40, 1,
         node_to_json(fresh)),
    )
    conn.execute(
        "INSERT INTO nodes (dedup_key, protocol, address, port, country, source,"
        " first_seen, last_ok, score, rounds, state) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (old.dedup_key, "vless", old.address, 443, "DE", "s",
         "2026-10-15T00:00:00+00:00", "2026-10-15T00:00:00+00:00", 40, 1,
         node_to_json(old)),
    )
    for key, when in ((fresh.dedup_key, "2026-10-16T10:00:00+00:00"),
                      (old.dedup_key, "2026-10-15T00:00:00+00:00")):
        conn.execute(
            "INSERT INTO checks (dedup_key, run_at, ok, stage, http_ms, jitter_ms, error)"
            " VALUES (?,?,1,'http',10.0,1.0,'')", (key, when))
    conn.commit()

    nodes = pipeline.recent_nodes(conn, hours=8, now="2026-10-16T11:00:00+00:00")
    by_address = {n.address: n for n in nodes}
    assert "a.example.com" in by_address, "a node proven an hour ago was dropped"
    assert "b.example.com" not in by_address, "a day-old check must not count"
    # And the rebuilt node carries its credentials, not just its address.
    assert by_address["a.example.com"].uuid == "11111111-2222-3333-4444-555555555555"


async def test_a_run_without_network_does_not_republish_the_pool(tmp_path):
    """Carry-over must not turn the offline worker into a publisher.

    The worker runs every 15 minutes with no `--allow-network`, so it verifies
    nothing. Before the carry-over existed it published nothing and said so
    ("0 verified, previous generation kept"). With the window in place it began
    publishing ~150 nodes every quarter hour, taken straight from the database
    and stamped with a fresh `run_id` — so the generation looked newly verified
    while containing no measurement from that hour at all, and it overwrote the
    generation the real probe had just produced.

    Carrying nodes forward is only meaningful after a round has probed
    something: it fills the gaps in a sample, it does not replace sampling.
    """
    from hub.pipeline import Pipeline
    from hub.models import Node, Protocol
    from hub.store_state import node_to_json

    pipeline = Pipeline(root=tmp_path, recent_hours=8, **_offline())
    conn = pipeline.store.connect()
    node = Node(protocol=Protocol.VLESS, address="a.example.com", port=443,
                uuid="11111111-2222-3333-4444-555555555555", country="NL")
    conn.execute(
        "INSERT INTO nodes (dedup_key, protocol, address, port, country, source,"
        " first_seen, last_ok, score, rounds, state) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (node.dedup_key, "vless", node.address, 443, "NL", "s",
         "2026-10-16T10:00:00+00:00", "2026-10-16T10:00:00+00:00", 40, 1,
         node_to_json(node)),
    )
    conn.execute(
        "INSERT INTO checks (dedup_key, run_at, ok, stage, http_ms, jitter_ms, error)"
        " VALUES (?,?,1,'http',10.0,1.0,'')", (node.dedup_key, "2026-10-16T10:00:00+00:00")
    )
    conn.commit()

    # A round that probed nothing must publish nothing, however much history the
    # database holds.
    report = await pipeline.run_once()
    assert report["published"] == 0, report
    assert report["generation"] == "", report
