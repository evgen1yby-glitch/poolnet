"""Model construction helpers shared by tests.

Imports go through the same `hub.*` namespace every test module uses, and rely
on `sys.path` already containing `src/`. Importing `src.hub.*` here instead
would only work when the *project root* is also on the path — true when pytest
is launched from the root, false from almost anywhere else.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hub.models import Node, ProbeResult, Protocol, Security, Tier
from hub.models import Stage, Transport, TransportSettings, TLS
from hub.scorer import History
from hub.scorer import Weights
from hub.tiers import TierPolicy


def make_reality_node(**over):
    """VLESS + REALITY: the gold standard for a RU vantage."""
    base = dict(
        protocol=Protocol.VLESS,
        address="nl.example.com",
        port=443,
        uuid="11111111-2222-3333-4444-555555555555",
        transport=Transport.TCP,
        transport_settings=TransportSettings(kind=Transport.TCP),
        security=Security.REALITY,
        tls=TLS(
            sni="www.microsoft.com",
            fingerprint="chrome",
            public_key="TESTPUBKEY",
            short_id="ab",
        ),
        flow="xtls-rprx-vision",
        remark="NL Reality 01",
        country="NL",
        source="fixture",
    )
    base.update(over)
    return Node(**base)


def make_trojan_node(**over):
    base = dict(
        protocol=Protocol.TROJAN,
        address="de.example.com",
        port=443,
        password="secret",
        transport=Transport.TCP,
        transport_settings=TransportSettings(kind=Transport.TCP),
        security=Security.TLS,
        tls=TLS(sni="de.example.com"),
        remark="DE Trojan",
        country="DE",
        source="fixture",
    )
    base.update(over)
    return Node(**base)


def make_probe_result(node, *, ok=True, http_ms=120.0, jitter_ms=20.0, **over):
    base = dict(
        dedup_key=node.dedup_key,
        stage_reached=Stage.HTTP,
        ok=ok,
        tcp_ms=25.0,
        tls_ms=60.0,
        http_ms=http_ms,
        http_ms_round2=http_ms * 1.1,
        jitter_ms=jitter_ms,
        exit_country=node.country,
        rounds_passed=2,
    )
    base.update(over)
    return ProbeResult(**base)


def make_history(**over):
    """A plausible cross-run history.

    `protocol_reliability` is left unset on purpose. It is a *per-source
    measurement*, and pinning it to 0.85 here masked the scorer's static
    per-protocol table — every protocol then scored 0.85 * weight and the
    ranking factor became a constant. Tests that need an explicit measurement
    pass one; the rest should exercise the published default.
    """
    base = dict(
        node_successes=8,
        node_rounds=10,
        source_pass_rate=0.9,
        published_days=10,
    )
    base.update(over)
    return History(**base)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "make_reality_node",
    "make_trojan_node",
    "make_probe_result",
    "make_history",
    "now_iso",
    "Tier",
    "TierPolicy",
    "Weights",
]
