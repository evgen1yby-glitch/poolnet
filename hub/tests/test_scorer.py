"""Scorer tests: bounded, monotone, auditable."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hub.models import Score  # noqa: E402
from hub.scorer import RUBRIC_VERSION, History, Weights, score  # noqa: E402
from tests.factories import make_history, make_probe_result, make_reality_node  # noqa: E402


def test_score_is_bounded_and_versioned():
    node = make_reality_node()
    result = score(node, make_history(), make_probe_result(node))
    assert 0 <= result.total <= 100
    assert result.rubric_version == RUBRIC_VERSION
    assert isinstance(result, Score)


def test_score_is_reproducible():
    node = make_reality_node()
    a = score(node, make_history(), make_probe_result(node))
    b = score(node, make_history(), make_probe_result(node))
    assert a == b


def test_lower_latency_scores_higher():
    node = make_reality_node()
    fast = score(node, make_history(), make_probe_result(node, http_ms=50))
    slow = score(node, make_history(), make_probe_result(node, http_ms=800))
    assert fast.total > slow.total
    assert fast.latency > slow.latency


def test_latency_above_one_second_scores_zero():
    node = make_reality_node()
    result = score(node, make_history(), make_probe_result(node, http_ms=5000))
    assert result.latency == 0.0


def test_unmeasured_speed_is_half_credit_not_zero():
    node = make_reality_node()
    fast = score(node, make_history(), make_probe_result(node, speed_bps=100_000_000))
    unknown = score(node, make_history(), make_probe_result(node, speed_bps=None))
    slow = score(node, make_history(), make_probe_result(node, speed_bps=100_000))
    assert fast.throughput > unknown.throughput > slow.throughput


def test_availability_is_history_weighted_single_run_counts_less():
    node = make_reality_node()
    once = score(
        node, History(node_successes=1, node_rounds=1, published_days=0),
        make_probe_result(node),
    )
    many = score(
        node, History(node_successes=9, node_rounds=10, published_days=10),
        make_probe_result(node),
    )
    assert many.availability > once.availability
    # A single good run is worth almost nothing: the freshness-attack defence.
    assert once.availability < 0.5 * 20.0


def test_protocol_history_differs_for_reality_vs_wireguard():
    """The per-protocol table must actually rank protocols, not flatten them.

    The comparison is VLESS+Reality vs Trojan — a protocol the static table
    scores far lower for a RU/CIS vantage. A regression that hard-codes one
    reliability value for every protocol (or reads a per-source measurement
    over the table) collapses both to the same score.
    """
    reality = make_reality_node()
    from tests.factories import make_trojan_node

    trojan = make_trojan_node()
    r = score(reality, make_history(), make_probe_result(reality))
    t = score(trojan, make_history(), make_probe_result(trojan))
    assert r.protocol_history > t.protocol_history


def test_fingerprint_resistance_rewards_reality():
    """Identical endpoints, one with REALITY and one without.

    `security=Security.NONE` is the real "no REALITY" state — a bare `None` is
    not a value `Node` ever holds in production (the field defaults to
    `Security.NONE`), so passing it here tested an impossible node.
    """
    from hub.models import Security

    reality = make_reality_node()
    plain = make_reality_node(
        security=Security.NONE, flow="", tls=make_reality_node().tls
    )
    r = score(reality, make_history(), make_probe_result(reality))
    p = score(plain, make_history(), make_probe_result(plain))
    assert r.fingerprint_resistance > p.fingerprint_resistance


def test_geo_lie_is_penalised():
    node = make_reality_node(country="US")
    honest = score(node, make_history(), make_probe_result(node, exit_country="US"))
    liar = score(node, make_history(), make_probe_result(node, exit_country="RU"))
    assert liar.total < honest.total
    assert liar.geo_integrity == 0.0


def test_an_unmeasured_exit_is_worth_less_than_an_honest_one():
    """"Cannot tell" must score below "checked and matches".

    This factor used to give the *same* full weight to both, which made the
    cheapest route to maximum geo points a node that never answers
    `cdn-cgi/trace` — the gate grants its reward when it cannot read its
    evidence. The distinct-violation test above only pins the liar case, so a
    regression to full-credit-on-missing would have left it green.
    """
    node = make_reality_node(country="US")
    honest = score(node, make_history(), make_probe_result(node, exit_country="US"))
    unknown = score(node, make_history(), make_probe_result(node, exit_country=""))
    assert honest.geo_integrity > unknown.geo_integrity > 0.0


def test_an_unmeasured_exit_is_not_confused_with_a_measured_lie():
    """The other half: "cannot tell" must not cost what a *mismatch* costs.

    A mismatch is a finding about the node — it reported a country and the
    country is wrong. An empty trace is a statement about the round, and
    charging it as a finding would punish a pool for the funnel's own
    `round2_gap` timing. Same three-state shape as `_throughput_points`, and
    for the same reason.
    """
    node = make_reality_node(country="US")
    unknown = score(node, make_history(), make_probe_result(node, exit_country=""))
    liar = score(node, make_history(), make_probe_result(node, exit_country="RU"))
    assert unknown.total > liar.total
    assert unknown.geo_integrity > liar.geo_integrity


def test_a_node_that_claims_no_country_has_nothing_to_disagree_with():
    """`node.country` empty is the one place full marks are still right.

    The comparison is "claimed country vs traced country", so with no claim
    there is nothing to be wrong about. Distinguishing this from
    "the trace failed" is what keeps the half-credit branch honest — without
    it, every unlabelled node would also lose the points, and an unscored
    label would be indistinguishable from a suppressed trace.
    """
    unlabelled = make_reality_node(country="")
    result = score(
        unlabelled, make_history(), make_probe_result(unlabelled, exit_country="")
    )
    assert result.geo_integrity == 5.0


def test_jitter_penalty():
    node = make_reality_node()
    steady = score(node, make_history(), make_probe_result(node, jitter_ms=10))
    jumpy = score(node, make_history(), make_probe_result(node, jitter_ms=290))
    assert steady.jitter > jumpy.jitter


def test_weights_sum_to_100():
    total = Weights().total()
    assert abs(total - 100.0) < 1e-9


def test_bad_history_does_not_crash():
    node = make_reality_node()
    for history in (
        History(),
        History(node_rounds=0, node_successes=5),
        History(node_successes=10, node_rounds=10, source_pass_rate=0.0),
    ):
        result = score(node, history, make_probe_result(node, http_ms=float("inf")))
        assert 0 <= result.total <= 100
