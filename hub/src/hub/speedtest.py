"""Throughput measurement. A separate question from "is this node alive?".

The funnel answers *reachability*. This module answers *how fast*, which is the
question the operator actually ranked on ("в приоритете с наибольшей
скоростью"). They are separated because they have opposite cost profiles: a
reachability test is ~200 bytes and milliseconds, while a throughput test is
megabytes and seconds. Running both on every candidate is how a checker
misdirects its own budget.

Design that comes from the co-tenant constraint (this box also runs another
VPN project, and the operator was explicit that neither may disturb the other):

1. **Speed is measured only on survivors.** Candidates reach `measure()` having
   passed TCP + TLS + an HTTP round, so a transfer is never attempted against
   a node that cannot carry one. `speed_bps` stays `None` for the rest, and
   `scorer._throughput_points` gives unmeasured nodes half credit rather than
   zero — an unmeasured node is not a slow node.
2. **A byte ceiling per node, and a global one.** 4 MiB per node against 2663
   candidates is a bounded, known worst case, not "as much as the node will
   send". The global cap is what makes the whole run safe to run unattended.
3. **Sticky concurrency**, not per-stage. One semaphore for all transfers, so
   the ceiling is a property of the *host* rather than of one stage: raising
   `http` for liveness must not silently raise transfer parallelism.
4. **Adaptive.** The window widens on a fast node and narrows on a slow one, so
   a 56 kbps node costs a fraction of a 100 Mbps one and the measurement is
   still statistically meaningful.

The measurement itself is deliberately unglamorous: pull a fixed-size range
from Cloudflare's `speed.cloudflare.com` over the node's own SOCKS port and
time the transfer. No third-party speedtest binary, no upload, no accounting
with a commercial API.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from .prober import node_tag

# --------------------------------------------------------------------------- #
# policy
# --------------------------------------------------------------------------- #

#: A file big enough to measure a slow node honestly but small enough that a
#: fast one finishes inside the window. `__down?bytes=` is Cloudflare's own
#: throttled endpoint: it is free, unauthenticated, and reachable from a node's
#: exit rather than from ours.
SPEED_URL = "https://speed.cloudflare.com/__down?bytes=%d"

#: Bytes requested on the first attempt. Small on purpose: the first attempt is
#: a *probe*, and a probe that costs 1 MiB from a dead-slow node is wasted.
FIRST_BYTES = 262_144          # 256 KiB
#: Bytes requested once a node has shown it can move the first window.
SECOND_BYTES = 4_194_304       # 4 MiB

#: How long a single transfer may run before it is abandoned and the node is
#: recorded as unmeasured. Slow but working must not cost the budget of a
#: measurement that would have succeeded.
MAX_WINDOW_S = 12.0

#: The window closes early once this much has been transferred: timing a full
#: 4 MiB on a 50 Mbps link spends 0.7 s to learn what 1 MiB learned in 0.2 s.
MIN_WINDOW_BYTES = 1_048_576   # 1 MiB

#: One semaphore for every transfer in the process. This is the number that
#: actually protects the host, and it is intentionally *not* `Concurrency.http`
#: — a liveness tweak must not be able to multiply transfer sockets.
DEFAULT_TRANSFER_CONCURRENCY = 32

#: Refuse to start a measurement round if the host is already this busy. Read
#: from the caller, which knows the host; `None` disables the check. Per-**core**
#: scale, not absolute `/proc/loadavg`: 1.0 means one runnable task per core,
#: so the number means the same thing on a 4-core and a 12-core box. An
#: absolute 4.0 on a 12-core machine with a co-tenant defers every round
#: forever, which is a guard that silently disables the feature it guards.
#: The default is deliberately conservative because this box has a co-tenant.
DEFAULT_MAX_LOAD = 0.85

#: How many nodes to measure per round, most promising first. The pool is
#: ranked by score, and score already encodes liveness and latency, so the top
#: of the list is where the throughput question actually needs answering.
DEFAULT_TOP_N = 150


@dataclass(frozen=True)
class SpeedPolicy:
    """Every knob a throughput round needs, so a run is reproducible."""

    top_n: int = DEFAULT_TOP_N
    transfer_concurrency: int = DEFAULT_TRANSFER_CONCURRENCY
    max_load: Optional[float] = DEFAULT_MAX_LOAD
    timeout_s: float = MAX_WINDOW_S
    first_bytes: int = FIRST_BYTES
    second_bytes: int = SECOND_BYTES
    #: Reported rather than hidden: a round that skipped nodes because of the
    #: load ceiling looks identical to one that found nothing to measure.
    defer_on_load: bool = True


@dataclass
class SpeedSample:
    """One node's measured throughput in one round."""

    dedup_key: str
    bps: Optional[float]
    bytes_moved: int = 0
    seconds: float = 0.0
    skipped_reason: str = ""
    attempts: int = 0

    @property
    def ok(self) -> bool:
        return self.bps is not None

    @property
    def mbps(self) -> float:
        return (self.bps or 0.0) / 1_000_000.0


@dataclass
class SpeedReport:
    samples: list[SpeedSample]
    #: Nodes that were never attempted, with a reason. Non-empty means the
    #: round was capped, not that those nodes are slow.
    deferred: dict[str, str]

    @property
    def measured(self) -> list[SpeedSample]:
        """Only real measurements, best first."""
        return sorted((s for s in self.samples if s.ok), key=lambda s: s.bps or 0.0, reverse=True)

    def by_key(self) -> dict[str, SpeedSample]:
        return {s.dedup_key: s for s in self.samples}

    def as_dict(self) -> dict:
        return {
            "measured": len(self.measured),
            "attempted": len(self.samples),
            "deferred": dict(self.deferred),
            "mbps": [round(s.mbps, 2) for s in self.measured[:10]],
        }


# --------------------------------------------------------------------------- #
# the measurement
# --------------------------------------------------------------------------- #

#: A reader the checker pulls bytes through. Signature matches
#: `CoreDriver.speed_read`, and an injected stub is what makes the round
#: testable without a network.
SpeedReader = Callable[[str, str, float], "asyncio.Future"]


async def _aclose(stream) -> None:
    """Close a reader, tolerating one that has nothing to close.

    An injected stub may return a plain awaitable or an object with no
    `aclose`; a cleanup helper that raises would turn a *successful*
    measurement into a failure, which is the wrong way round.
    """
    closer = getattr(stream, "aclose", None)
    if closer is None:
        return
    try:
        await closer()
    except Exception:  # noqa: BLE001 - closing must never fail the measurement
        pass


class SpeedChecker:
    """Measures throughput over nodes that already passed the funnel.

    `read` is the only thing that touches the network, and it is injected:
    the checker decides *what* to fetch and *when to stop*, the driver decides
    *how*. That split is what lets the policy be tested with a scripted reader
    that returns bytes at a known rate.
    """

    def __init__(
        self,
        *,
        read: SpeedReader,
        policy: SpeedPolicy | None = None,
        load: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], "asyncio.Future"]] = None,
    ) -> None:
        self.read = read
        self.policy = policy or SpeedPolicy()
        self._load = load
        self._sleep = sleep or asyncio.sleep
        self._sem: Optional[asyncio.Semaphore] = None

    # -- helpers ----------------------------------------------------------

    @property
    def _limiter(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.policy.transfer_concurrency)
        return self._sem

    async def _host_load(self) -> float:
        if self._load is None:
            return 0.0
        try:
            return float(self._load())
        except Exception:  # noqa: BLE001 - a broken load probe must not stop the run
            return 0.0

    async def _one(self, tag: str, *, url_bytes: int) -> SpeedSample:
        """One attempt at one node.

        Returns a sample with `bps=None` on any failure. A throughput failure
        is *never* an error: the node already proved it carries traffic in the
        funnel, so the honest outcome is "throughput unknown", which the scorer
        scores as half credit rather than as zero.
        """
        policy = self.policy
        deadline = time.monotonic() + policy.timeout_s
        moved = 0
        started = time.monotonic()
        # Kept as a *variable* rather than an inline `async for` so the reader
        # can be closed explicitly. Breaking out of an `async for` leaves the
        # generator suspended at its `yield`, holding the underlying socket open
        # until it is collected — and the second attempt of the same node then
        # runs while the first is still connected, which is two sockets for one
        # node and a ceiling that is quietly double what the policy says.
        stream = self.read(tag, SPEED_URL % url_bytes, policy.timeout_s)
        try:
            async for chunk in stream:
                if chunk:
                    moved += len(chunk)
                # Close the window on whichever bound is hit first: a slow node
                # is cut by time, a fast one by volume. Both are checked on
                # every chunk, so neither bound can overshoot by more than one
                # chunk — and a node that never yields is cut by `timeout_s`
                # passed to the reader itself.
                if moved >= MIN_WINDOW_BYTES or time.monotonic() >= deadline:
                    break
        except asyncio.TimeoutError:
            return SpeedSample(tag, None, moved, time.monotonic() - started,
                               "timeout", attempts=1)
        except Exception as exc:  # noqa: BLE001
            return SpeedSample(tag, None, moved, time.monotonic() - started,
                               f"{type(exc).__name__}: {exc}", attempts=1)
        finally:
            await _aclose(stream)

        elapsed = time.monotonic() - started
        if moved == 0:
            # Zero bytes in a successful transfer is a broken node, not a slow
            # one, and a `0 bps` would rank it below every measured node.
            return SpeedSample(tag, None, 0, elapsed, "no bytes", attempts=1)
        return SpeedSample(tag, moved / elapsed if elapsed > 0 else None, moved, elapsed, attempts=1)

    async def measure_tag(self, tag: str) -> SpeedSample:
        """Two attempts, coarse then fine, for one node.

        The first window is small: it decides whether the node can move data at
        all, which is most of the value. Only a node that passes the coarse
        window pays for the fine one, so the expensive measurement is spent on
        candidates that justify it.

        The semaphore is held across *both* attempts. Releasing it between them
        would let the coarse and the fine attempt of one node overlap with
        themselves, so the effective host ceiling would be
        `transfer_concurrency * 2` — a ceiling that doubles exactly when the
        pool is fast enough to reach the second window, which is the situation
        where doubling it hurts most.
        """
        policy = self.policy
        async with self._limiter:
            first = await self._one(tag, url_bytes=policy.first_bytes)
            if not first.ok:
                return first
            # A node that already looks slow at 256 KiB will not look better at
            # 4 MiB; the coarse window is the answer, and doubling the bytes
            # would mostly double the wait.
            if (first.bps or 0.0) < 1_000_000.0:  # below ~1 Mbps
                return first
            second = await self._one(tag, url_bytes=policy.second_bytes)
            if not second.ok:
                return first
            return second

    # -- the round --------------------------------------------------------

    async def plan(
        self, tags: Sequence[str], *, ranked: Optional[Sequence[str]] = None
    ) -> tuple[list[str], dict[str, str]]:
        """Decide what to measure, and name what is being skipped.

        Split out from running the transfers so a caller can find out the
        *size* of a round before committing to it. The speed stage needs that:
        it registers a driver SOCKS inbound per node before measuring, and
        registering 2663 nodes to measure 150 of them would open 2513
        loopback listeners for nothing.

        Returns `(order, deferred)`, where `order` is what pass one measurement
        each and `deferred` says why each skipped node was skipped — never empty
        when a node was skipped, because a silently dropped node and a node the
        source never listed are the same report to whoever reads it.
        """
        policy = self.policy
        deferred: dict[str, str] = {}

        order = [t for t in (ranked or tags) if t in set(tags)]
        if len(order) > policy.top_n:
            # Anything ranked after `top_n` is deferred with a reason, not
            # dropped: the caller can see that the pool was capped and act on it.
            for tag in order[policy.top_n:]:
                deferred[tag] = f"beyond top_n={policy.top_n}"
            order = order[: policy.top_n]
        return order, deferred

    async def measure(
        self, tags: Sequence[str], *, ranked: Optional[Sequence[str]] = None
    ) -> SpeedReport:
        """Measure `tags`, best-ranked first, under the load ceiling.

        `ranked` is a permutation of `tags` in the order worth measuring (score
        descending in production). Passing it separately rather than sorting
        inside keeps the policy free of any dependency on scoring, and lets the
        round be driven by a caller that has already limited the list.
        """
        order, deferred = await self.plan(tags, ranked=ranked)

        if self.policy.max_load is not None and self.policy.defer_on_load:
            load = await self._host_load()
            if load >= self.policy.max_load:
                # The whole round defers rather than running at reduced size.
                # A half-run that publishes "top 20" is indistinguishable from
                # a pool that only has 20 fast nodes.
                return SpeedReport([], dict(deferred, **{
                    tag: f"host load {load:.2f} >= {self.policy.max_load}"
                    for tag in order
                }))

        samples: list[SpeedSample] = []
        for tag in order:
            samples.append(await self.measure_tag(tag))

        return SpeedReport(samples, deferred)

    async def run(self, order: Sequence[str]) -> SpeedReport:
        """Measure an already-planned `order`, re-checking the load ceiling.

        The companion to `plan`. A caller that planned, registered, and then
        passes the plan back here gets the same round `measure` would have
        produced for those tags — including the load check, which is re-run
        because time passed between planning and measuring and the host may
        have become busy in between.
        """
        samples: list[SpeedSample] = []

        if self.policy.max_load is not None and self.policy.defer_on_load:
            load = await self._host_load()
            if load >= self.policy.max_load:
                return SpeedReport([], {
                    tag: f"host load {load:.2f} >= {self.policy.max_load}"
                    for tag in order
                })

        for tag in order:
            samples.append(await self.measure_tag(tag))
        return SpeedReport(samples, {})


# --------------------------------------------------------------------------- #
# the stage: the part the pipeline drives
# --------------------------------------------------------------------------- #


class SpeedStage:
    """Binds `SpeedChecker` to the driver lifecycle and the node population.

    `SpeedChecker` is pure policy: it decides what to fetch and when to stop,
    and its only network dependency is an injected `read`. That makes it
    testable, but it leaves three things it cannot know about:

    1. **Registration.** A transfer goes through a *specific node's* SOCKS
       port, so the node has to be registered first. The prober registers and
       removes each node inside its own `finally`, so by the time the speed
       stage runs the driver holds nothing. This class re-adds the survivors,
       measures, and removes them — in the same `finally` discipline, so a crash
       mid-transfer cannot leak a SOCKS inbound per dead node into the process.
    2. **Selection.** *Which* nodes are worth a megabyte each. Ranking by a
       provisional score answers that, and the provisional score is available
       precisely because `scorer._throughput_points` gives unmeasured nodes
       half credit rather than zero — the same design choice that keeps the
       score usable before any transfer is what makes the ranking honest.
    3. **Capability.** A driver without `speed_read` has no way to move bytes,
       and must be detected rather than assumed. Probing `getattr` and returning
       an empty report keeps an older driver working exactly as before.

    Nothing here is allowed to raise. A speed stage that crashes would take the
    whole pipeline run with it, and a missing throughput measurement costs a
    handful of points on one factor — the opposite trade worth making.
    """

    def __init__(
        self,
        *,
        driver,
        policy: SpeedPolicy | None = None,
        load: Optional[Callable[[], float]] = None,
    ) -> None:
        self.driver = driver
        self.policy = policy or SpeedPolicy()
        self._load = load
        #: Why the last `_add` failed, if it did. Empty means it did not. Kept
        #: on the instance rather than raised because a registration failure is
        #: genuinely not fatal — the transfer will simply produce no sample —
        #: and "not fatal" must not mean "not recorded".
        self._last_error = ""

    async def measure_nodes(
        self,
        nodes: Sequence,
        ranked_keys: Sequence[str],
    ) -> SpeedReport:
        """Register `nodes`, measure the ones worth measuring, unregister them.

        `ranked_keys` is `dedup_key` order, best first, from the caller's
        provisional ranking. Passing the order in rather than computing it keeps
        the stage free of any scoring dependency: the pipeline ranks, the stage
        measures, and the seam between them is one list.
        """
        reader = getattr(self.driver, "speed_read", None)
        # Not an error: a driver written before throughput existed is a
        # working driver. Naming every node with a reason is what stops a
        # missing measurement from looking like a round that found nothing.
        #
        # `callable` and not `is not None`: the guard is "can this driver move
        # bytes", and a stub that shadows the method with `None` cannot, any
        # more than a driver that never defined it can. Testing only for `None`
        # would let a non-callable through to `SpeedChecker`, where it fails on
        # the first call — after the round has already been announced as
        # running.
        if not callable(reader):
            return SpeedReport([], {n.dedup_key: "driver has no speed_read" for n in nodes})

        by_key = {n.dedup_key: n for n in nodes}
        # dedup_key -> tag, and the reverse for mapping results back.
        tag_of = {k: node_tag(n) for k, n in by_key.items()}
        key_of = {node_tag(n): k for k, n in by_key.items()}
        # The driver registers and looks nodes up by **tag**, not by
        # `dedup_key`: `node_tag()` is the 16-char prefix, and
        # `SingBoxDriver.speed_read` does `self.entries.get(tag)`. Handing the
        # checker full `dedup_key`s therefore made every lookup miss — the
        # driver returns an empty stream for a tag it does not hold, so no bytes
        # move, every sample comes back `bps=None`, and `speed.measured` is 0
        # *independently of the load guard*.
        #
        # Which is how this hid: the guard was deferring most rounds on this
        # box, so "0 measured" had a visible explanation and nobody looked for
        # a second one. Two mechanisms, one observable.
        #
        # So the stage owns the translation in both directions: `dedup_key` in,
        # `node_tag` to the driver, and the sample's tag mapped back to the
        # `dedup_key` the caller ranks by. The keys the caller sees never change.
        checker = SpeedChecker(
            read=reader, policy=self.policy, load=self._load
        )
        # Only nodes we can actually re-register are worth measuring: a tag
        # with no node behind it would produce a sample no pipeline row can
        # claim, and the scorer would then be handing points to a node that
        # no longer exists.
        usable = [k for k in ranked_keys if k in by_key]

        # The whole `usable` list is handed to the checker even though only
        # `top_n` of it gets measured, because the checker's `top_n` slice is
        # also what produces the `deferred` map naming the rest. Slicing here
        # as well would make the cap invisible: the round would quietly measure
        # the same nodes and report nothing deferred, which is exactly the
        # "capped round looks like a small pool" failure the map exists to
        # prevent — reintroduced one layer up, where no test was looking.
        #
        # Registration follows what the checker will actually attempt, not the
        # whole list: registering a node that is never measured is a loopback
        # SOCKS inbound opened for nothing.
        order, planned_deferred = await checker.plan([tag_of[k] for k in usable])
        for tag in order:
            await self._add(by_key[key_of[tag]])
        try:
            report = await checker.run(order)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - see the class docstring
            # Both maps are in *tag* space here, and the caller's key space is
            # `dedup_key`, so the failure path translates too. Returning the
            # tags would leave a report no row in the store can claim, which is
            # the same silent drop as an unmeasured node.
            return SpeedReport(
                [],
                {key_of[k]: f"speed stage failed: {type(exc).__name__}: {exc}"
                 for k in list(order) + list(planned_deferred) if k in key_of},
            )
        finally:
            for tag in order:
                await self._remove(by_key[key_of[tag]])
        # `run` reports only the tags it tried; `plan` reports the tags it
        # skipped. Both maps are needed for the count to be honest: a node that
        # was never attempted and a node that failed are different facts to an
        # operator reading "measured 1 of 12", and only the sum says which.
        merged = {key_of[k]: v for k, v in planned_deferred.items()}
        merged.update({key_of[k]: v for k, v in report.deferred.items()})
        report.deferred = merged
        if self._last_error:
            # A round where registration failed is not a round with no fast
            # nodes; it is a round that never measured anything. Saying so —
            # and naming every node with the reason — is the difference between
            # an operator seeing "speed stage broken" and one reading a pool
            # ranked on half-credit throughput and believing it.
            for key in usable:
                report.deferred.setdefault(key, f"registration failed: {self._last_error}")
        # Same translation on the way out: the caller stores results by
        # `dedup_key`, and a sample tagged `5ae3ebe3da698af4` would match no row
        # — so the measurement would be silently dropped rather than scored.
        for sample in report.samples:
            sample.dedup_key = key_of.get(sample.dedup_key, sample.dedup_key)
        return report

    async def _add(self, node) -> None:
        try:
            await self.driver.add_node(node, node_tag(node))
        except Exception as exc:  # noqa: BLE001 - registration failure is not fatal
            # Logged rather than dropped. A bare `pass` here is how the stage
            # can end up measuring nothing while reporting nothing: the transfer
            # reads bytes through a port that was never opened, every sample
            # fails, and there is no record of why. The registration and the
            # transfer are two names for one dependency, so a failure in the
            # first has to be visible to whoever reads the second.
            self._last_error = f"add_node: {type(exc).__name__}: {exc}"

    async def _remove(self, node) -> None:
        try:
            await self.driver.remove_node(node_tag(node))
        except Exception:  # noqa: BLE001 - cleanup must never fail the run
            pass


def apply_speed(results, report: SpeedReport) -> int:
    """Write measured throughput back onto the pipeline's `ProbeResult`s.

    Returns how many results gained a real measurement. A node that failed
    keeps `speed_bps=None` — it already proved it carries traffic in the funnel,
    so the honest state is "throughput unknown", which the scorer prices at
    half credit. Nothing is written to zero, because "measured at zero" and
    "never measured" rank in opposite directions for anyone reading the score.

    `dedup_key` is the join, not list position: the report comes back in the
    order the checker finished, and matching by index would attribute one
    node's throughput to whichever node happened to finish next to it.
    """
    by_key = report.by_key()
    applied = 0
    for result in results:
        if not result.ok:
            continue
        sample = by_key.get(result.dedup_key)
        if sample is None or sample.bps is None:
            continue
        result.speed_bps = sample.bps
        applied += 1
    return applied
