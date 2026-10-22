"""Build a demo generation in an isolated store, using offline seams.

This is a *manual* verification aid, not part of the suite: it renders real,
fully-shaped sing-box / base64 / clash payloads through the same
`Pipeline._publish` the production run uses, so the API can be exercised
end to end (headers, formats, tiers) without waiting for a verified pool.

Two properties matter here, and both are non-negotiable:

* **the network is never touched.** `connect` and `handshake` collapse to
  no-ops before any socket exists, and no driver is constructed, so nothing
  dials the synthetic `*.example.com` nodes. This is the same injection the
  test suite uses.
* **the real `data/` store is never written.** `HUB_ROOT` points at a scratch
  directory, so the production pointer, event log and database are untouched.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tests.test_prober import FakeDriver, _dial_nowhere  # noqa: E402

from hub.parser import parse_many  # noqa: E402

SCRATCH = Path(tempfile.mkdtemp(prefix="hub-demo-", dir="/tmp"))

#: A realistic mixed-protocol source body: VLESS+REALITY, Shadowsocks and
#: Trojan nodes across distinct hostnames and countries, exactly as
#: `parse_many` expects to receive them. Rendering then goes through the real
#: parser, so the published payloads are the genuine article rather than a
#: hand-written fixture that happens to fit.
_UUID = "11111111-2222-3333-4444-555555555555"
# Two or three nodes per country, not one. A country with a single node gets no
# shard at all (`MIN_COUNTRY_SHARD_NODES = 2`: one node in its own file is a
# redirect with extra steps), so a one-node-per-country fixture would exercise
# the country *labels* and then publish a pool where almost no country has a
# link — the exact shape the operator asked to see working.
_VLESS = [
    ("nl1.example.com", 443, "NL · Amsterdam · REALITY", "www.microsoft.com", "ab"),
    ("nl2.example.com", 443, "NL · Amsterdam · REALITY", "www.microsoft.com", "ac"),
    ("de1.example.com", 443, "DE · Frankfurt · REALITY", "www.microsoft.com", "cd"),
    ("de2.example.com", 443, "DE · Frankfurt · REALITY", "www.microsoft.com", "ce"),
    ("fi1.example.com", 443, "FI · Helsinki · REALITY", "www.microsoft.com", "ef"),
    ("uk1.example.com", 443, "UK · London · REALITY", "www.microsoft.com", "12"),
    ("us1.example.com", 443, "US · New York · REALITY", "www.microsoft.com", "34"),
    ("pl1.example.com", 443, "PL · Warsaw · REALITY", "www.microsoft.com", "56"),
    ("pl2.example.com", 443, "PL · Warsaw · REALITY", "www.microsoft.com", "57"),
    ("se1.example.com", 443, "SE · Stockholm · REALITY", "www.microsoft.com", "78"),
    ("cz1.example.com", 443, "CZ · Prague · REALITY", "www.microsoft.com", "9a"),
]
_TROJAN = [
    ("at1.example.com", 8443, "AT · Vienna · Trojan", "www.apple.com"),
    ("at2.example.com", 8443, "AT · Vienna · Trojan", "www.apple.com"),
    ("lt1.example.com", 8443, "LT · Vilnius · Trojan", "www.apple.com"),
    ("ee1.example.com", 8443, "EE · Tallinn · Trojan", "www.apple.com"),
]
_SS = [
    ("ee1.example.com", 8388, "EE · Tallinn · Shadowsocks"),
    ("md1.example.com", 8388, "MD · Chișinău · Shadowsocks"),
    ("md2.example.com", 8388, "MD · Chișinău · Shadowsocks"),
]


def _vless_uri(host: str, port: int, remark: str, sni: str, sid: str) -> str:
    return (
        f"vless://{_UUID}@{host}:{port}?security=reality&encryption=none"
        "&flow=xtls-rprx-vision"
        f"&sni={sni}&pbk=ZmFrZS1rZXktZm9yLWRlbW8&sid={sid}"
        "&type=tcp&headerType=none"
        f"#{remark.replace(' ', '%20')}"
    )


def _trojan_uri(host: str, port: int, remark: str, sni: str) -> str:
    return (
        f"trojan://cGFzc3dvcmQ@{host}:{port}?security=tls"
        f"&sni={sni}&type=tcp&headerType=none"
        f"#{remark.replace(' ', '%20')}"
    )


def _ss_uri(host: str, port: int, remark: str) -> str:
    # SIP002 form: userinfo is base64(method:password), already URL-safe here.
    userinfo = "Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpwYXNzd29yZA"
    return f"ss://{userinfo}@{host}:{port}#{remark.replace(' ', '%20')}"


def _body() -> str:
    lines = [
        _vless_uri(host, port, remark, sni, sid)
        for host, port, remark, sni, sid in _VLESS
    ]
    lines += [
        _trojan_uri(host, port, remark, sni)
        for host, port, remark, sni in _TROJAN
    ]
    lines += [
        _ss_uri(host, port, remark) for host, port, remark in _SS
    ]
    return "\n".join(lines)


BODY = _body()


class LatencyDriver(FakeDriver):
    """Scripted funnel with per-node latency **and** per-node flakiness.

    The landing page's score section shows three buckets, and a pool where every
    node always answers lands entirely in one of them: `availability` is worth
    twenty points and saturates after a handful of successes, so twelve clean
    runs push the whole pool to 70+ regardless of speed. Some nodes therefore
    fail on a fixed schedule — the same "a node that behaves until publication"
    the rubric exists to catch — which is what spreads the pool across buckets.

    Keying is by the prober's tag (`dedup_key[:16]`), resolved through the real
    dedup function rather than a hand-written hash: a key that no longer
    resolves means the fixture and the parser have drifted apart, and raising is
    the honest response. Silently inventing a latency for an unknown tag would
    turn "my fixture is stale" into "that node is slow".
    """

    #: hostname -> (latency seconds, pass pattern over successive runs).
    _PLAN: ClassVar[dict[str, tuple[float, str]]] = {
        # Always fast, always up: the top of the pool.
        "nl1": (0.09, "111111111111"),
        "nl2": (0.10, "111111111111"),
        "de1": (0.11, "111111111111"),
        "de2": (0.13, "111111111111"),
        "fi1": (0.12, "111111111111"),
        "uk1": (0.14, "111111111111"),
        # Mostly fine with an occasional failure.
        "us1": (0.16, "111101111111"),
        "pl1": (0.19, "111111011111"),
        "pl2": (0.21, "111111111111"),
        "se1": (0.22, "111011111101"),
        "cz1": (0.26, "111111101111"),
        # Flaky, but not dead: still passes often enough to stay published.
        "at1": (0.38, "111111101101"),
        "at2": (0.42, "111111111111"),
        "lt1": (0.52, "111110111111"),
        "ee1": (0.75, "101111111011"),
        "md1": (1.40, "111101111101"),
        "md2": (1.55, "111111111111"),
    }

    def __init__(self) -> None:
        super().__init__()
        #: Resolved once: tag -> plan. Built from the real parser so the keys
        #: cannot drift away from what the prober actually sees.
        self._by_tag = {}
        #: tag -> Node, filled by `add_node`. See `trace` for why the tag alone
        #: is not enough.
        self._node_by_tag = {}
        for node in parse_many(BODY, source="demo")[0]:
            host = node.address.split(".")[0]
            if host in self._PLAN:
                self._by_tag[node.dedup_key[:16]] = (host, *self._PLAN[host])
        self._calls = 0

    async def add_node(self, node, tag):
        """Remember the node each tag belongs to, for `trace` below.

        `node_tag` is `dedup_key[:16]`, a hash, so the country cannot be
        recovered from the tag alone — but the prober always registers the node
        before the funnel touches it, and that is the only place the real `Node`
        is available. Everything the fixture needs about a node comes from here.
        """
        self.added.append(tag)
        self._node_by_tag[tag] = node

    async def trace(self, tag, *, timeout: float = 5.0):
        """Answer `cdn-cgi/trace` with the country the remark claims.

        Without this the driver inherits `FakeDriver.trace`, which returns one
        hard-coded `loc` — so a fixture spanning twelve countries publishes as a
        single "NL" group, and the landing page's country cards are decorative
        in exactly the way `pipeline` warns about. A *measured* country has to
        be per node, which means per tag, which means this override.

        The code is read out of the remark rather than from the hostname:
        `nl1.example.com` is a claim, and parsing it back would be trusting the
        label. Deriving it from the same string the parser already turned into a
        remark keeps the demo honest about what a measurement looks like — one
        value, per node, supplied by the driver that carried its traffic.
        """
        node = self._node_by_tag.get(tag)
        code = ""
        if node is not None:
            head = node.remark.split("·", 1)[0].strip()
            if len(head) == 2 and head.isalpha():
                code = head.upper()
        self.trace_calls.append(tag)
        return {"ip": "203.0.113.9", "loc": code or "NL", "colo": "AMS"}

    async def socks_check(self, tag: str, *, timeout: float = 5.0):
        """Two calls per node per run (the two HTTP rounds), so track both.

        `availability` is a ratio of successful rounds to attempted ones, and
        the prober records one check per node per run, so the per-node counter
        has to advance per node rather than per call: a shared counter would
        couple every node's fate to the order the scheduler happened to pick.
        """
        if tag not in self._by_tag:
            raise KeyError(f"no latency plan for tag {tag!r}")
        _host, latency, pattern = self._by_tag[tag]
        self._calls += 1
        # `socks_calls` is appended per call, which is the run index in disguise
        # only if every node is called exactly once per run — it is, because
        # `Concurrency` serialises a node's two rounds.
        run = self.socks_calls.count(tag)
        ok = pattern[(run - 1) % len(pattern)] == "1"
        self.socks_calls.append(tag)
        return ok and self.flags["http"], latency


async def _handshake_ok(address, port, server_hostname, context):
    """A handshake that succeeds without opening a socket.

    It must return the `(reader, writer)` pair `prober` unpacks, not a bool.
    The writer stub carries `close()` **synchronous** followed by
    `await wait_closed()`, matching what `prober._tls_inner` actually calls:
    making both `async` leaks a "coroutine never awaited" for every REALITY
    node, because `close()` returns a coroutine nobody awaits.
    """

    class _Stub:
        def close(self):
            return None

        async def wait_closed(self):
            return None

    return object(), _Stub()


async def main() -> None:
    from hub.pipeline import Pipeline
    from hub.prober import Concurrency

    async def _client(url, headers):
        """A canned body, so no request ever leaves the host."""
        return BODY, 200, {}

    # A scratch root: the demo store lives entirely under /tmp.
    os.environ["HUB_ROOT"] = str(SCRATCH)
    pipeline = Pipeline(
        root=SCRATCH,
        sources={
            "sources": [{"url": "https://example.test/demo", "name": "demo"}],
            "protocol_reliability": 0.5,
            "source_pass_rate": 1.0,
            "fetch_client": _client,
        },
        driver_factory=LatencyDriver,
        concurrency=Concurrency(tcp=5, tls=5, http=5, round2_gap_s=0.0),
        # `min_pool=2` is a demo knob, not a policy change: the shipped
        # `MIN_USABLE_POOL` is 10, and synthetic nodes must not publish in
        # production. Lowering it here is what makes the API exercisable at all
        # with a scripted pool; nothing else reads this value.
        min_pool=2,
        connect=_dial_nowhere,
        handshake=_handshake_ok,
    )

    # Twelve runs on the same store, so the pool earns a history before it is
    # judged. A node's `availability` factor is twenty points of the rubric and
    # it is worth nothing on a first run: every node starts at zero rounds, so
    # a single run caps the whole pool below the 60+ bucket no matter how fast
    # the nodes are. Re-running is not a shortcut around the scoring — it is
    # the only way for the score to mean what it claims to mean, and the same
    # code path the cron job takes on the server.
    runs = 12
    for i in range(runs):
        await pipeline.run_once()

    conn = pipeline.store.connect()
    try:
        scores = [r[0] for r in conn.execute("SELECT score FROM nodes")]
    finally:
        conn.close()
    buckets = {
        "60+": sum(1 for s in scores if s >= 60),
        "30-59": sum(1 for s in scores if 30 <= s < 60),
        "0-29": sum(1 for s in scores if s < 30),
    }

    report = {"run_id": "demo", "nodes_verified": len(scores), "published": len(scores),
              "generation": pipeline.store.current_generation(), "tier_counts": buckets}
    print("runs:", runs)
    print("nodes:", len(scores), "score buckets:", buckets)
    print("scores:", sorted(scores))
    print("generation:", report["generation"])
    print("scratch root:", SCRATCH)


if __name__ == "__main__":
    asyncio.run(main())
