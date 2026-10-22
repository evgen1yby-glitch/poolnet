"""Deterministic 0-100 scoring. Pure, auditable, versioned.

The rubric is the only published one that exists (AutoMergePublicNodes'
`config/scoring.yaml`), adapted for a RU/CIS audience: `availability` outranks
`source_history`, because with a pool whose end-to-end yield is ~2%, whether a
node was there *last week* predicts next week better than how many sources
carried it does.

Every factor is published per node so a score is auditable rather than
asserted. `rubric_version` is part of `Score`, so a score is always traceable
to the weights that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from .models import Node, ProbeResult, Protocol, Score, Security

#: Bumped when a factor's behaviour changes, because `Score` carries it and a
#: score from before the change must not be compared against one from after as
#: though the same rubric produced them. `.2` is the `geo_integrity` three-state
#: fix: an unmeasurable exit country used to score full marks.
RUBRIC_VERSION = "2026-10-14.2"


@dataclass(frozen=True)
class Weights:
    latency: float = 25.0
    availability: float = 20.0
    jitter: float = 15.0
    source_history: float = 10.0
    protocol_history: float = 10.0
    throughput: float = 10.0
    fingerprint_resistance: float = 5.0
    geo_integrity: float = 5.0

    def total(self) -> float:
        return (
            self.latency
            + self.availability
            + self.jitter
            + self.source_history
            + self.protocol_history
            + self.throughput
            + self.fingerprint_resistance
            + self.geo_integrity
        )


#: Per-protocol historical reliability over the last 30 days, for a RU/CIS
#: vantage. VLESS+Reality is the only construct that still works reliably from
#: RU after the late-2025 TSPU upgrades; WG is ~100% blocked. These numbers feed
#: `protocol_history` and are re-derivable from `checks`.
PROTOCOL_RELIABILITY: Mapping[str, float] = {
    "vless": 0.85,
    "trojan": 0.45,
    "shadowsocks": 0.35,
    "vmess": 0.40,
    "hysteria2": 0.60,
    "tuic": 0.50,
    "wireguard": 0.05,
    "socks": 0.55,
    "http": 0.45,
}

#: Protocols worth extra `fingerprint_resistance` credit, because they actively
#: resist active probing from censors rather than merely surviving it.
FINGERPRINT_BONUS: Mapping[str, float] = {
    "vless": 1.0,  # REALITY + xtls-rprx-vision: gold standard
    "trojan": 0.4,  # real TLS, no anti-probing
    "shadowsocks": 0.1,  # AEAD only
    "vmess": 0.3,  # TLS, deprecated in Xray 26.x
    "hysteria2": 0.7,  # QUIC masquerade + obfs
    "tuic": 0.7,
    "wireguard": 0.0,  # statistically trivially identified
    "socks": 0.0,
    "http": 0.0,
}


@dataclass
class History:
    """Cross-run knowledge about a node, a source, and a protocol.

    Every value is a rate in [0, 1]; the scorer turns them into points.
    """

    node_successes: int = 0
    node_rounds: int = 0
    source_pass_rate: float = 1.0
    #: Measured 30-day reliability of the node's *protocol*. `None` means "not
    #: measured yet" and is the default, which is what makes the sentinel safe:
    #: `0.5` is a legitimate measurement (a protocol that works half the time),
    #: so it must not double as "absent". Using a magic value conflated the two
    #: and made a real 0.5 measurement silently fall back to the static table.
    protocol_reliability: Optional[float] = None
    published_days: int = 0

    def availability(self) -> float:
        if self.node_rounds == 0:
            return 0.0
        return self.node_successes / self.node_rounds


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def score(node: Node, history: History, probe: ProbeResult, weights: Weights | None = None) -> Score:
    """Compute the 0-100 score with the full breakdown attached."""
    w = weights or Weights()

    latency = _latency_points(probe.latency_ms, w.latency)
    availability = _availability_points(history, w.availability)
    jitter = _jitter_points(probe.jitter_ms, w.jitter)
    source = _clamp(history.source_pass_rate) * w.source_history
    protocol = _protocol_points(node, history, w.protocol_history)
    throughput = _throughput_points(probe.speed_bps, w.throughput)
    fingerprint = _fingerprint_points(node, w.fingerprint_resistance)
    geo = _geo_points(probe, node, w.geo_integrity)

    total = (
        latency
        + availability
        + jitter
        + source
        + protocol
        + throughput
        + fingerprint
        + geo
    )

    return Score(
        total=int(round(_clamp(total, 0.0, 100.0))),
        latency=round(latency, 2),
        availability=round(availability, 2),
        jitter=round(jitter, 2),
        source_history=round(source, 2),
        protocol_history=round(protocol, 2),
        throughput=round(throughput, 2),
        fingerprint_resistance=round(fingerprint, 2),
        geo_integrity=round(geo, 2),
        rubric_version=RUBRIC_VERSION,
    )


# ---------------------------------------------------------------------------
# factor implementations
# ---------------------------------------------------------------------------


def _latency_points(latency_ms: float, weight: float) -> float:
    """max(0, weight * (1 - p50/1000ms)).

    A node slower than 1 s scores zero; anything faster is linear below that.
    `inf` means "never measured" and scores zero — a node that reached the HTTP
    stage always has a measurement, so this is the defensive branch.

    `latency_ms <= 0` also scores zero rather than full marks: a TCP connect
    timer cannot legitimately return 0 or negative, so it means a broken
    measurement (a clock jump or a mocked driver), not a perfect node.
    """
    if latency_ms == float("inf") or latency_ms <= 0:
        return 0.0
    return max(0.0, weight * (1.0 - latency_ms / 1000.0))


def _availability_points(history: History, weight: float) -> float:
    """`weight * success_rate`, EWMA-weighted by how long we have known it.

    A node seen once scores at most ~1/3 of this factor, because **one good run
    is worth almost nothing** (the freshness attack: a hostile node that behaves
    perfectly for one window then turns).
    """
    if history.node_rounds == 0:
        return 0.0
    raw = history.availability()
    confidence = _clamp(history.node_rounds / 10.0)
    streak = _clamp(history.published_days / 7.0, 0.0, 1.0)
    return weight * raw * (0.4 + 0.4 * confidence + 0.2 * streak)


def _jitter_points(jitter_ms: Optional[float], weight: float) -> float:
    if jitter_ms is None:
        return 0.0
    return max(0.0, weight * (1.0 - jitter_ms / 300.0))


def _protocol_points(node: Node, history: History, weight: float) -> float:
    """Measured per-protocol reliability, falling back to the static table.

    The static table is the *publication* of what was measured historically for
    a RU/CIS vantage; a fresh per-run measurement always wins over it.
    """
    base = history.protocol_reliability
    if base is None:
        base = PROTOCOL_RELIABILITY.get(node.protocol.value, 0.5)
    return _clamp(base) * weight


def _throughput_points(speed_bps: Optional[float], weight: float) -> float:
    """min(weight, weight * speed / 2 MB/s).

    Unmeasured (top-N only) is **half credit**, not zero: absence of a speed
    measurement must not make a great ranked node look bad.
    """
    if speed_bps is None:
        return weight * 0.5
    return min(weight, weight * (speed_bps / 2_000_000.0))


def _fingerprint_points(node: Node, weight: float) -> float:
    """Active-probing resistance: does the node look like something else?

    Three things are measured, and they used to be conflated:

    * the **protocol's** ceiling (`FINGERPRINT_BONUS`): REALITY borrows a real
      certificate, Hysteria2 masquerades as QUIC;
    * whether this **node actually deploys** one. A VLESS endpoint on plain
      TLS with no flow has none of the protocol's protection;
    * surface details (port 443, a uTLS fingerprint).

    The ceiling is only reachable if the construct is present. Without that
    check every VLESS node scored 1.0 * weight whether or not it deployed
    REALITY, and since that already saturates the weight the factor could
    never separate a REALITY node from a plain one — the exact ranking the
    rubric docstring claims to reward most.
    """
    bonus = FINGERPRINT_BONUS.get(node.protocol.value, 0.0)
    points = bonus * weight
    if node.security is Security.REALITY:
        points += weight * 0.5  # the construct that defeats active probing
    elif node.security is Security.TLS or node.security is Security.NONE:
        # Real TLS without REALITY, or no TLS at all: the node is identifiable
        # by active probing regardless of what its protocol could do.
        points *= 0.5
    if getattr(node, "flow", "") and "xtls" in node.flow.lower():
        points += weight * 0.2  # vision masks the TLS record pattern
    if node.port == 443:
        points *= 1.1  # 443 blends in with ordinary TLS
    if node.tls.fingerprint:
        points *= 1.1  # uTLS fingerprint present
    return min(weight, points)


def _geo_points(probe: ProbeResult, node: Node, weight: float) -> float:
    """Penalise a node whose `cdn-cgi/trace` lies about its own country.

    Advisory, not a hard reject: CDN-fronted exits legitimately report the PoP
    country, and hard-rejecting them throws away good nodes. Penalty instead.

    Three states, and the middle one is the point. This returned full `weight`
    whenever the exit country was *unmeasurable* — which is the same score an
    honestly-matching node gets. That inverts the factor: a node that cannot
    show its exit is rewarded exactly like one that showed a matching one, so
    the cheapest way to max the factor is to make the measurement impossible,
    and a node that never answered the trace ranks above a CDN exit that
    answered with a country that differs from its label.

    Unmeasurable is therefore worth neither the full weight nor zero. Zero
    would make it indistinguishable from a *measured mismatch*, which is a real
    finding about the node; "cannot tell" is a statement about this round. Half
    is the same convention `_throughput_points` uses for an unmeasured node —
    an absent measurement must not outrank a good one, and must not be confused
    with a bad one.
    """
    if not node.country:
        # Nothing claimed, so nothing to disagree with. Full marks are right
        # here and only here: the comparison cannot be had, so nobody is being
        # credited for having suppressed it.
        return weight
    if not probe.exit_country:
        return weight / 2.0
    if probe.exit_country.upper() == node.country.upper():
        return weight
    return 0.0
