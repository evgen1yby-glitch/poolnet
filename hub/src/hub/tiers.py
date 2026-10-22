"""Score buckets that turn a ranked pool into subscription tiers.

A tier is not a score threshold — it is a *policy object* with a target size, a
protocol preference, and a floor. The distinction matters: a hard threshold
produces an empty payload on a bad week, whereas "top N that clear the floor"
always produces a usable list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from .models import MAX_NODES_PER_PAYLOAD, Format, Node, Score, Tier

#: A node below this score is never published, however short the pool is.
SCORE_FLOOR = 15

#: A node must survive at least this many pipeline rounds before it may enter
#: `curated`. One good run is worth almost nothing.
MIN_ROUNDS_CURATED = 5


@dataclass(frozen=True)
class TierPolicy:
    tier: Tier
    target: int
    min_score: int = SCORE_FLOOR
    require_reality: bool = False
    max_per_source: int = 0  # 0 = unlimited; anti-Sybil
    formats: tuple[Format, ...] = (Format.BASE64, Format.SINGBOX, Format.CLASH)


DEFAULT_POLICIES: tuple[TierPolicy, ...] = (
    TierPolicy(
        tier=Tier.CURATED,
        target=30,
        min_score=55,
        require_reality=True,
        max_per_source=6,
    ),
    TierPolicy(
        tier=Tier.VERIFIED,
        target=150,
        min_score=SCORE_FLOOR,
        require_reality=False,
        # 60, not 15. The cap is anti-Sybil — one source must not own the
        # published pool — and at 15 it was doing something else entirely: on
        # the real pool, 60 of the 75 nodes that passed every check came from a
        # single source, so the cap dropped ~45 live nodes. The countries it
        # dropped were exactly the small ones (BR, CA, LT, EE, GB, ID, IN, TW),
        # because a country with one or two nodes in the pool usually has them
        # from the source that carries the most nodes overall. The published
        # pool went from 18 countries to 15, and its thin countries to almost
        # none — the cap was not defending the pool, it was shrinking it.
        #
        # The number is set above what any single source currently supplies,
        # with headroom, rather than at the point where the countries come back.
        # Measured on the real pool: caps of 15/25/40 all yield the same 15
        # countries, and BR, CA and LT only reappear once the cap reaches the
        # ~60 nodes the largest source holds. Verified at 100 on the same run:
        # 75 published nodes across 18 countries, identical to no cap at all,
        # while the cap is still in force.
        #
        # Sitting exactly at 60 was rejected: the fix would rest on a
        # coincidence, and one more node from that source would delete the same
        # countries again for a reason nobody would connect to this line. 100 is
        # two thirds of `target`, which is where the cap starts doing its actual
        # job — with a full 150-node pool no single source can own more than two
        # thirds of it.
        #
        # What this gives up, stated honestly: a single source now supplies 80%
        # of the published nodes, so that source failing, being poisoned, or
        # being taken over has an outsized effect on the feed. The mitigations
        # that remain are the ones that do not need a cap — the score floor,
        # `source_history` weighting, per-source disable after repeated empty
        # rounds, and the fact that every node is independently probe-verified
        # before publication. Raising this is a deliberate trade of source
        # diversity for country coverage, not a bug fix.
        max_per_source=100,
    ),
)


@dataclass(frozen=True)
class RankedNode:
    """A node with its score, ready for tiering."""

    node: Node
    score: Score
    rounds: int
    rank: int


def rank(
    entries: Iterable[tuple[Node, Score, int]],
) -> list[RankedNode]:
    """Sort by score descending, then by `dedup_key` for determinism.

    The tie-break is *not* latency, even though latency is the larger factor
    inside the score: two nodes with equal totals would otherwise swap places
    between runs depending on measurement jitter, and an unstable order changes
    the generated tags — which breaks client-side caching and makes rollback
    comparisons meaningless. `dedup_key` is stable, so identical pools rank
    identically.
    """
    ordered = sorted(
        entries,
        key=lambda e: (-e[1].total, e[0].dedup_key),
    )
    return [
        RankedNode(node=node, score=score, rounds=rounds, rank=index + 1)
        for index, (node, score, rounds) in enumerate(ordered)
    ]


def select(
    ranked: Sequence[RankedNode],
    policy: TierPolicy,
) -> list[RankedNode]:
    """Apply a tier policy to a ranked pool.

    Returns at most `policy.target` nodes, all clearing `min_score`. Per-source
    cap prevents a single noisy source from owning the tier (Sybil defence).
    """
    picked: list[RankedNode] = []
    per_source: dict[str, int] = {}

    for entry in ranked:
        if len(picked) >= min(policy.target, MAX_NODES_PER_PAYLOAD):
            break
        if entry.score.total < policy.min_score:
            continue
        if policy.require_reality and entry.node.security.value != "reality":
            continue
        if policy.tier is Tier.CURATED and entry.rounds < MIN_ROUNDS_CURATED:
            continue
        source = entry.node.source
        if policy.max_per_source:
            if per_source.get(source, 0) >= policy.max_per_source:
                continue
            per_source[source] = per_source.get(source, 0) + 1
        picked.append(entry)

    return picked


def build_tiers(
    entries: Iterable[tuple[Node, Score, int]],
    policies: Sequence[TierPolicy] = DEFAULT_POLICIES,
) -> dict[Tier, list[RankedNode]]:
    """Rank once, slice per policy. A node may appear in more than one tier."""
    ranked = rank(entries)
    return {policy.tier: select(ranked, policy) for policy in policies}
