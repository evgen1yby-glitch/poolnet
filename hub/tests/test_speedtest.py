"""Speed-checker tests. Every "node" here is a scripted reader.

The properties worth pinning are the safety ones, not the arithmetic: that a
throughput failure never becomes an error, that the host load ceiling defers
the *whole* round instead of quietly shrinking it, and that no measurement can
run away in bytes or in time.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from hub.speedtest import (  # noqa: E402
    DEFAULT_MAX_LOAD,
    DEFAULT_TOP_N,
    MIN_WINDOW_BYTES,
    SpeedChecker,
    SpeedPolicy,
    SpeedReport,
    SpeedStage,
    apply_speed,
)


def _reader(bps: float, chunk: int = 65_536, fail: bool = False):
    """A reader that yields bytes at `bps` until the checker stops asking.

    Timing is real: the point of the checker is that it decides when to stop,
    so a reader that ignores `deadline` and just keeps going is exactly the
    node the policy has to be able to cut off.
    """

    async def read(tag, url, timeout):
        if fail:
            raise OSError("connection reset by peer")
        started = asyncio.get_running_loop().time()
        sent = 0
        while True:
            await asyncio.sleep(chunk / bps if bps > 0 else 0)
            yield b"x" * chunk
            sent += chunk
            if asyncio.get_running_loop().time() - started > timeout:
                return

    return read


def _checker(read, load=None, **policy) -> SpeedChecker:
    """A checker with the co-tenant guard off by default.

    `load` is a constructor argument, not a policy field: it is *how* the host
    load is read, while `max_load` is *whether* to act on it. Conflating the
    two is a TypeError from `SpeedPolicy`, which is the correct complaint — a
    measurement method is not a threshold.
    """
    kwargs = dict(transfer_concurrency=4, timeout_s=3.0, max_load=None)
    kwargs.update(policy)
    return SpeedChecker(read=read, policy=SpeedPolicy(**kwargs), load=load)


# --------------------------------------------------------------------------- #
# the measurement
# --------------------------------------------------------------------------- #


async def test_a_fast_node_is_measured():
    """A fast node closes its window on volume, not on the timeout.

    The reader yields more than `MIN_WINDOW_BYTES` immediately, so the checker
    must stop asking — a checker that drains the whole requested payload would
    still be *correct* here, but it would spend 4 MiB to learn what 1 MiB
    taught it, which is the cost the volume bound exists to avoid.
    """
    async def read(tag, url, timeout):
        yield b"x" * MIN_WINDOW_BYTES
        return

    checker = _checker(read)
    sample = await checker.measure_tag("n0")
    assert sample.ok, sample.skipped_reason
    assert sample.bps > 1_000_000
    assert sample.bytes_moved >= MIN_WINDOW_BYTES


async def test_a_slow_node_still_reports_a_real_speed():
    """A 200 kB/s node must not be reported as "unmeasured".

    The coarse window is what makes this work: the coarse window is 256 KiB, so
    a 200 kB/s node moves it in ~1.3 s and produces a real number. Cutting the
    window at 1 s instead would have returned "no bytes" and thrown away a
    working node — which is the failure this pins.
    """
    checker = _checker(_reader(bps=200_000))
    sample = await checker.measure_tag("slow")
    assert sample.ok, sample.skipped_reason
    assert 100_000 < sample.bps < 400_000, sample.bps
    # It must not have been promoted to the second window.
    assert sample.attempts == 1


async def test_a_throughput_failure_is_never_an_error():
    """A reset mid-transfer is "unknown", which the scorer scores as half credit."""
    checker = _checker(_reader(bps=1_000_000, fail=True))
    sample = await checker.measure_tag("dead")
    assert sample.ok is False
    assert sample.bps is None
    assert sample.skipped_reason  # the reason survives for the run report


async def test_a_zero_byte_transfer_is_not_a_zero_speed():
    """0 bytes is a broken node, and `0 bps` would rank below every measured one."""
    async def read(tag, url, timeout):
        yield b""
        return

    sample = await _checker(read).measure_tag("empty")
    assert sample.bps is None
    assert "no bytes" in sample.skipped_reason


async def test_the_transfer_semaphore_is_shared_across_nodes():
    """One limiter for the whole process, not one per node.

    Per-node limiters would mean the host ceiling is a function of how many
    nodes happen to be measured at once, which is the opposite of a ceiling.
    """
    checker = _checker(_reader(bps=4_000_000))
    first = await checker.measure_tag("a")
    assert first.ok
    assert checker._limiter is checker._limiter


async def test_concurrent_transfers_are_capped():
    """One limiter for the whole process, not one per node.

    Measured with a `try/finally` that closes the generator explicitly, because
    an abandoned async generator does not run its `finally` until it is
    collected — a counter decremented in `finally` therefore reports
    "generators still referenced", not "transfers in flight", and the first
    version of this test asserted on that and failed against *correct* code.
    """
    inside = 0
    peak = 0

    async def read(tag, url, timeout):
        nonlocal inside, peak
        inside += 1
        peak = max(peak, inside)
        try:
            await asyncio.sleep(0.02)
            yield b"x" * MIN_WINDOW_BYTES
        finally:
            # Only reached when the consumer stops iterating and the generator
            # is closed, which is what `break` in `_one` does.
            inside -= 1

    checker = _checker(read, transfer_concurrency=3)
    await asyncio.gather(*[checker.measure_tag(f"n{i}") for i in range(12)])
    assert peak <= 3, peak
    assert inside == 0, "a reader was left open"


# --------------------------------------------------------------------------- #
# the round
# --------------------------------------------------------------------------- #


async def test_the_load_ceiling_defers_the_whole_round():
    """A capped round must not look like a small pool.

    Deferring every tag with a reason is what distinguishes "we measured
    nothing because the host is busy" from "the pool has 20 fast nodes" — the
    latter is a lie an operator would act on.
    """
    checker = _checker(_reader(bps=4_000_000), load=lambda: 9.5, max_load=2.0)
    report = await checker.measure(["a", "b", "c"])
    assert report.samples == []
    assert set(report.deferred) == {"a", "b", "c"}
    assert all("load" in reason for reason in report.deferred.values())


async def test_a_broken_load_probe_does_not_stop_the_run():
    """Telemetry that throws must not become an outage.

    The previous assertion was `assert report.measured or report.deferred`,
    which passes on *either* side of the `or` — and both are satisfiable by a
    wrong answer. A probe returning `inf` ("infinitely busy") defers every node,
    so `report.measured` is empty but `report.deferred` is not, and the
    assertion is satisfied by the exact failure mode it documents against:
    telemetry that throws becoming an outage, expressed as "defer everything".

    So this asserts the probe's *value*, not just that the round produced
    something. A broken probe means "the host's load is unknown", and unknown
    is treated as idle — the measurement proceeds and a node that is genuinely
    slow is cut by its own timeout, not by a round that never ran.
    """
    def broken():
        raise RuntimeError("no /proc")

    checker = SpeedChecker(read=_reader(bps=4_000_000),
                           policy=SpeedPolicy(max_load=2.0, transfer_concurrency=2),
                           load=broken)
    assert await checker._host_load() == 0.0
    report = await checker.measure(["a"])

    # The node was actually measured, and named as deferred by nothing: the
    # round ran rather than being deferred wholesale.
    assert "a" in report.by_key(), report.by_key()
    assert "a" not in report.deferred, (
        f"deferred with {report.deferred} — that is the outage this test pins against"
    )


async def test_only_the_top_n_are_measured_and_the_rest_are_named():
    checker = _checker(_reader(bps=4_000_000), top_n=3)
    tags = [f"n{i}" for i in range(10)]
    report = await checker.measure(tags)
    assert len(report.samples) == 3
    assert len(report.deferred) == 7
    assert all("top_n" in reason for reason in report.deferred.values())


async def test_ranking_decides_the_order_not_the_input_order():
    """The caller's ranking wins, so the budget goes to the best candidates.

    Order of *first* appearance is the assertion, because a fast node is read
    twice (coarse then fine window) and the second read of "best" lands before
    the first read of "mid" — asserting on the raw sequence would pin the
    two-attempt design instead of the ranking.
    """
    seen: list[str] = []

    async def read(tag, url, timeout):
        if tag not in seen:
            seen.append(tag)
        yield b"x" * MIN_WINDOW_BYTES
        return

    checker = _checker(read, top_n=2)
    await checker.measure(["worst", "mid", "best"], ranked=["best", "mid", "worst"])
    assert seen == ["best", "mid"], seen


async def test_the_report_summarises_measured_and_deferred_separately():
    async def read(tag, url, timeout):
        if tag == "slow":
            raise OSError("reset")
        yield b"x" * MIN_WINDOW_BYTES
        return

    report = await _checker(read, top_n=4).measure(["fast", "slow"])
    assert isinstance(report, SpeedReport)
    summary = report.as_dict()
    assert summary["measured"] == 1
    assert summary["attempted"] == 2
    assert summary["deferred"] == {}


# --------------------------------------------------------------------------- #
# the stage: driver lifecycle and the join back to the pipeline
# --------------------------------------------------------------------------- #


class _StageDriver:
    """Records its own lifecycle, and serves bytes from any `Callback`."""

    def __init__(self, *, fail_read=False):
        self.added: list[str] = []
        self.removed: list[str] = []
        self.reads: list[str] = []
        self.fail_read = fail_read

    async def add_node(self, node, tag):
        self.added.append(tag)

    async def remove_node(self, tag):
        self.removed.append(tag)

    async def speed_read(self, tag, url, timeout):
        self.reads.append(tag)
        if self.fail_read:
            raise OSError("connection reset by peer")
        yield b"x" * MIN_WINDOW_BYTES
        return


def _node(index: int):
    """A real `Node`, so `node_tag` derives the real tag.

    Hand-written tags would not exercise the join at all: the pipeline's
    `ProbeResult.dedup_key` is a 64-char hash and the driver tag is its first
    16 characters, so a test using literal tags would pass even if the two ever
    disagreed — which is the whole failure this stage exists to prevent.
    """
    from hub.models import Node, Protocol, Security, Transport, TransportSettings

    return Node(
        protocol=Protocol.VLESS,
        address=f"n{index}.example.invalid",
        port=443,
        uuid="11111111-2222-3333-4444-555555555555",
        transport=Transport.TCP,
        transport_settings=TransportSettings(kind=Transport.TCP),
        security=Security.NONE,
        remark=f"n{index}",
        country="NL",
    )


def _nodes(count: int) -> list:
    return [_node(i) for i in range(count)]


def _keys(nodes: list) -> list[str]:
    return [n.dedup_key for n in nodes]


async def test_the_stage_registers_and_unregisters_every_node_it_measures():
    """A leaked registration is a leaked SOCKS inbound.

    The prober removes each node in its own `finally`, so by the time the speed
    stage runs the driver holds nothing. If the stage re-adds and forgets to
    remove, the process accumulates one loopback inbound per dead node — the
    leak the `finally` discipline exists to prevent.

    The tag is compared against `node_tag(node)` rather than a literal, which
    is what makes this test able to fail: a stage that mints its own name would
    still add and remove symmetrically, and only the *shared* name with the
    prober catches it.
    """
    from hub.prober import node_tag

    nodes = _nodes(3)
    driver = _StageDriver()
    stage = SpeedStage(driver=driver,
                       policy=SpeedPolicy(top_n=3, transfer_concurrency=2,
                                          timeout_s=3.0, max_load=None))
    report = await stage.measure_nodes(nodes, _keys(nodes))

    expected = sorted(node_tag(n) for n in nodes)
    assert sorted(driver.added) == expected, driver.added
    assert sorted(driver.removed) == expected, "a node stayed registered"
    assert sorted(report.by_key()) == _keys(nodes)


class _TagKeyedDriver:
    """A driver that stores entries by tag, like the real one does.

    This is the difference between a test that can fail and one that cannot.
    `_StageDriver.speed_read` serves bytes from *any* tag, so a stage that
    registered under one name and read through another still measured fine —
    the join was never exercised. `SingBoxDriver` does `self.entries.get(tag)`
    and returns an empty stream for a tag it does not hold, which is the
    behaviour that makes the mismatch a silent zero rather than a loud error.

    Reproducing only that one detail is what turns the class into evidence: a
    stage passing `dedup_key`s where tags belong gets zero bytes here, exactly
    as it would in production, and the assertion below fails.
    """

    def __init__(self) -> None:
        self.entries: set[str] = set()
        self.reads: list[str] = []
        self.bytes_served: dict[str, int] = {}

    async def add_node(self, node, tag) -> None:
        self.entries.add(tag)

    async def remove_node(self, tag) -> None:
        self.entries.discard(tag)

    async def speed_read(self, tag, url, timeout):
        self.reads.append(tag)
        if tag not in self.entries:
            # What the real driver does: an unknown tag is not an error, it is
            # an empty stream. The measurement then reports "no data", which is
            # indistinguishable from a very slow node — which is why this bug
            # survived: it fails softly, not loudly.
            return
        self.bytes_served[tag] = self.bytes_served.get(tag, 0) + MIN_WINDOW_BYTES
        yield b"x" * MIN_WINDOW_BYTES


async def test_the_stage_measures_through_the_tag_the_driver_actually_holds():
    """The speed stage must read through the tag it registered, not the key.

    The bug this pins: `measure_nodes` handed `SpeedChecker` full `dedup_key`s
    while registering nodes under `node_tag` (the 16-char prefix). Every
    `entries.get()` lookup missed, so no bytes moved, every sample came back
    `bps=None`, and `speed.measured` was 0 — masked in the logs by the load
    guard, which was deferring rounds for an unrelated, legitimate reason. Two
    causes, one observable, and only the visible one was being believed.
    """
    from hub.prober import node_tag

    nodes = _nodes(4)
    driver = _TagKeyedDriver()
    stage = SpeedStage(
        driver=driver,
        policy=SpeedPolicy(top_n=4, transfer_concurrency=2, timeout_s=5.0,
                           max_load=None),
    )
    report = await stage.measure_nodes(nodes, _keys(nodes))

    # Every read must be through a tag the driver holds. If this is empty the
    # stage read through names it never registered, which is the bug.
    assert driver.bytes_served, (
        f"the driver served bytes to no tag; reads={driver.reads}, "
        f"entries={sorted(driver.entries)}"
    )
    # Backwards guard: the tags read must be prefixes of the keys reported, so
    # the translation is a real one and not two unrelated namespaces that both
    # happen to be populated.
    reported = {s.dedup_key for s in report.samples}
    for tag in driver.reads:
        assert any(k.startswith(tag) for k in reported), (
            f"the driver read tag {tag!r} but no reported key starts with it"
        )

    # And the results must come back in the caller's key space, or no store row
    # can claim them and the measurement is dropped rather than scored.
    assert sorted(report.by_key()) == sorted(_keys(nodes)), (
        "samples are not keyed by dedup_key; the pipeline would discard them"
    )
    assert report.measured, "no sample reported a throughput"


async def test_a_stage_whose_registration_fails_names_every_node():
    """Registration failure is reported, not silently swallowed.

    `_add` catches its exceptions because a failed registration is not fatal to
    the run. But "not fatal" must not mean "not recorded": if every `add_node`
    raises, no SOCKS inbound is opened, nothing can be measured, and a report
    that says nothing would read as a pool with no fast nodes.
    """

    class _RefusesRegistration(_TagKeyedDriver):
        async def add_node(self, node, tag) -> None:
            raise RuntimeError("cannot bind loopback port")

    nodes = _nodes(3)
    driver = _RefusesRegistration()
    stage = SpeedStage(
        driver=driver,
        policy=SpeedPolicy(top_n=3, transfer_concurrency=2, timeout_s=3.0,
                           max_load=None),
    )
    report = await stage.measure_nodes(nodes, _keys(nodes))

    assert report.samples == [] or not any(s.ok for s in report.samples)
    assert set(report.deferred) == set(_keys(nodes)), sorted(report.deferred)
    reasons = set(report.deferred.values())
    assert any("registration failed" in r for r in reasons), reasons


async def test_the_stage_removes_nodes_even_when_a_transfer_explodes():
    """A crash in the reader must not cost the cleanup, or the next round leaks."""
    nodes = _nodes(2)
    driver = _StageDriver(fail_read=True)
    stage = SpeedStage(driver=driver,
                       policy=SpeedPolicy(top_n=2, transfer_concurrency=2,
                                          timeout_s=3.0, max_load=None))
    await stage.measure_nodes(nodes, _keys(nodes))
    assert sorted(driver.removed) == sorted(driver.added)


async def test_a_driver_that_predates_throughput_is_not_an_error():
    """Absent `speed_read` names every node rather than running a broken round.

    Both halves of the assertion matter: `getattr` finds nothing (or a
    non-callable) and the *report* still says why each node went unmeasured, so
    an old driver's run cannot be mistaken for a pool with no fast nodes.
    """
    class OldDriver:
        async def add_node(self, node, tag):
            return None

        async def remove_node(self, tag):
            return None

        #: No `speed_read` at all: the pre-throughput driver.

    nodes = _nodes(3)
    report = await SpeedStage(driver=OldDriver()).measure_nodes(nodes, _keys(nodes))
    assert report.samples == []
    assert set(report.deferred) == set(_keys(nodes))
    assert all("no speed_read" in reason for reason in report.deferred.values())


async def test_a_non_callable_speed_read_is_treated_as_absent():
    """A present-but-not-callable `speed_read` cannot move bytes either.

    This is the stronger partner of `test_an_absent_speed_read_defers_the_round`:
    `is not None` would pass this value through to the checker, which then fails
    on the first call — after the round has already been announced as running,
    which is the failure mode that looks like a broken pool rather than a broken
    driver. The fixture is deliberately *not* `None`, because `None` is rejected
    by both `is not None` and `not callable()` and so cannot tell the two guards
    apart.
    """
    nodes = _nodes(2)
    report = await SpeedStage(driver=_ShadowDriver()).measure_nodes(nodes, _keys(nodes))
    assert set(report.deferred) == set(_keys(nodes))
    assert all("no speed_read" in reason for reason in report.deferred.values())
    assert report.samples == [], "bytes were read through a non-callable reader"


async def test_a_none_speed_read_is_treated_as_absent():
    """`speed_read = None` is the explicit "I cannot stream" declaration.

    Same deferral as the non-callable case, reached through a different value:
    one driver has no such attribute, one shadows it with `None`, and one puts
    something unusable in it. All three are absent as far as the stage is
    concerned, and all three have to be refused by the same guard rather than
    each discovering its way to a TypeError.
    """
    nodes = _nodes(2)
    report = await SpeedStage(driver=_NoReadDriver()).measure_nodes(nodes, _keys(nodes))
    assert set(report.deferred) == set(_keys(nodes))
    assert all("no speed_read" in reason for reason in report.deferred.values())


async def test_the_stage_survives_a_driver_that_will_not_stream_at_all():
    """`measure_tag` guards a failing *stream*; this guards what happens when
    the driver refuses to hand one over.

    A `speed_read` that raises is caught per-node and recorded as a failed
    sample, which is the right answer for a dead node. A driver that fails
    *outside* any node — before the stream exists — is a different event, and
    the stage has to absorb it rather than let it kill the pipeline: the real
    transfer work is already done, and losing the run's report to a broken
    throughput probe would be the most expensive possible way to fail.
    """
    class BrokenStart:
        async def add_node(self, node, tag):
            raise RuntimeError("sing-box is not running")

        async def remove_node(self, tag):
            return None

        async def speed_read(self, tag, url, timeout):
            yield b"x" * MIN_WINDOW_BYTES
            return

    nodes = _nodes(2)
    report = await SpeedStage(driver=BrokenStart()).measure_nodes(nodes, _keys(nodes))
    # Registration already swallows its own failure, so the round still runs;
    # what must never happen is the runner dying before these tags are named.
    assert report.by_key() or report.deferred
    for sample in list(report.samples):
        assert sample.dedup_key in set(_keys(nodes))


async def test_a_reader_that_raises_is_a_failed_sample_not_a_crash():
    """The per-node guard, kept distinct from the stage guard above.

    Both must hold, and they are different code paths: this one returns a
    sample with `bps=None` and a reason, which is what the scorer prices at
    half credit. Asserting it separately from the stage guard is what stops
    either from being removed as "already covered".
    """
    nodes = _nodes(1)
    report = await SpeedStage(driver=_StageDriver(fail_read=True)).measure_nodes(
        nodes, _keys(nodes)
    )
    assert len(report.samples) == 1
    assert report.samples[0].bps is None
    assert report.samples[0].skipped_reason
    assert report.deferred == {}


async def test_the_stage_measures_only_tags_that_exist():
    """A tag with no node behind it produces a sample nothing can claim."""
    nodes = _nodes(2)
    driver = _StageDriver()
    stage = SpeedStage(driver=driver,
                       policy=SpeedPolicy(top_n=5, transfer_concurrency=2,
                                          timeout_s=3.0, max_load=None))
    ranked = _keys(nodes) + ["ghost" * 8]
    report = await stage.measure_nodes(nodes, ranked)

    assert set(report.by_key()) == set(_keys(nodes))
    assert driver.reads, "no bytes were read for a node that does exist"
    assert sorted(driver.added) == sorted(driver.removed)


# --------------------------------------------------------------------------- #
# the join: writing speed back onto the pipeline's results
# --------------------------------------------------------------------------- #


class _ShadowDriver:
    """A driver whose `speed_read` exists, is not `None`, and is not callable.

    The third property is the whole point. A `speed_read` shadowed with `None`
    satisfies *both* `reader is None` and `not callable(reader)`, so a test built
    on `None` passes whichever guard the code uses — it cannot tell them apart,
    and a mutation swapping one for the other survives. Only a present-but-not-
    callable value (a stub, a `MagicMock` left unconfigured, a leftover scalar)
    separates the two, and that is what the guard has to reject.
    """

    speed_read = "not-a-coroutine-function"

    async def add_node(self, node, tag):
        return None

    async def remove_node(self, tag):
        return None


class _NoReadDriver(_ShadowDriver):
    """The other shape: `speed_read` shadowed to `None` outright.

    Kept separate from `_ShadowDriver` because it is a genuinely different
    driver — one that explicitly declares "I cannot stream", rather than one
    that exposes something unusable. Both must be deferred, for the same
    reason, via the same guard.
    """

    speed_read = None


class _Report:
    """A `SpeedReport` stand-in with an explicit, caller-chosen sample set.

    Deliberately *not* `SpeedReport(...)`: the point of these tests is which
    keys are present, and constructing the real object would hide a missing
    sample behind the real `by_key()`.
    """

    def __init__(self, samples):
        self._samples = samples

    def by_key(self):
        return {s.dedup_key: s for s in self._samples}


def _result(key: str, ok: bool = True):
    from hub.models import ProbeResult, Stage

    return ProbeResult(key, Stage.HTTP, ok=ok)


async def test_measured_speed_is_written_back_onto_the_right_result():
    """Join by `dedup_key`, never by position.

    The report comes back in the order the checker *finished*, which for a
    two-attempt measurement is not the order it was started in. Matching by
    index would silently attribute one node's throughput to whichever node
    happened to finish next to it, and the ranking would be noise.
    """
    fast, slow = (_node(0), _node(1))
    results = [_result(fast.dedup_key), _result(slow.dedup_key)]
    # The sample array is deliberately in the *opposite* order to `results`:
    # the report comes back in finish order, and joining by position would
    # hand `slow`'s bytes to `fast`.
    samples = [type("S", (), {"dedup_key": slow.dedup_key, "bps": 500.0, "ok": True})()]

    applied = apply_speed(results, _Report(samples))
    assert applied == 1
    assert results[0].speed_bps is None, "fast kept an unmeasured value it did not earn"
    assert results[1].speed_bps == 500.0


async def test_a_failed_node_is_not_given_a_speed():
    """Speed is measured on survivors; a dead node must not gain throughput from
    a sample that happens to share its key."""
    dead = _node(2)
    results = [_result(dead.dedup_key, ok=False)]
    samples = [type("S", (), {"dedup_key": dead.dedup_key, "bps": 900.0, "ok": True})()]

    applied = apply_speed(results, _Report(samples))
    assert applied == 0
    assert results[0].speed_bps is None


async def test_an_unmeasured_survivor_stays_unmeasured_not_zero():
    """Half credit requires `None`, and `None` requires that nothing write 0.

    `0.0` would rank below every measured node, so "we never asked" and "it was
    useless" would collapse into the same number — the bug the scorer's
    half-credit rule exists to prevent, reintroduced one line further down.
    """
    survivor = _node(3)
    results = [_result(survivor.dedup_key)]

    assert apply_speed(results, _Report([])) == 0
    assert results[0].speed_bps is None


class _ExplodingChecker:
    """A checker whose *round* raises, as opposed to whose reads fail.

    The distinction is the whole point of this fixture. `measure_tag` converts a
    read failure into a sample with `bps=None` and the caller never learns
    anything went wrong, so a driver whose reads fail cannot reach the guard in
    `SpeedStage.measure_nodes` — `checker.run` simply returns a report. Only a
    failure *outside* the per-node try can get there: a bug in `plan`, in the
    load re-check, or in the checker's own bookkeeping. That is what this stands
    in for, and why the previous test with a failing reader could not cover the
    guard at all.
    """

    def __init__(self, *args, **kwargs):
        pass

    async def plan(self, tags, *, ranked=None):
        return list(tags), {}

    async def run(self, order):
        raise RuntimeError("planner exploded")


async def test_a_crashing_speed_checker_defers_every_node_instead_of_raising(
    monkeypatch,
):
    """The guard: `checker.run` raising must become named deferrals, not a crash.

    The pipe is `SpeedStage.measure_nodes` → `SpeedChecker.run`, and `run` is
    where a round either produces samples or takes the pipeline down with it.
    "Nothing here is allowed to raise" is the class docstring's own claim, and
    deleting the `except Exception` arm leaves that claim false while the suite
    stays green — because every reader failure is already handled one level
    down. So the assertion is written against the *report*, where a crash and a
    clean round are still distinguishable:

      * every tag the round tried must appear in `deferred`,
      * with a reason naming the stage rather than an empty one,
      * and `samples` must be empty, because "measured nothing" and "the stage
        died" are different facts.

    A raising `checker.run` is injected rather than simulated through a driver,
    so the assertion can only pass if the stage caught it.
    """
    import hub.speedtest as speedtest_module

    monkeypatch.setattr(speedtest_module, "SpeedChecker", _ExplodingChecker)

    nodes = _nodes(3)
    driver = _StageDriver()
    stage = SpeedStage(
        driver=driver,
        policy=SpeedPolicy(top_n=3, transfer_concurrency=2, timeout_s=3.0,
                           max_load=None),
    )
    report = await stage.measure_nodes(nodes, _keys(nodes))

    assert report.samples == [], "a crashed stage must not report measurements"
    assert set(report.deferred) == set(_keys(nodes)), (
        f"every attempted node must be named, got {sorted(report.deferred)}"
    )
    for reason in report.deferred.values():
        assert "speed stage failed" in reason, reason
    # The cleanup runs in a `finally`, so the crash must not leak the
    # registrations either — a stage that dies and leaves SOCKS inbounds behind
    # turns one crash into a slow leak.
    assert sorted(driver.removed) == sorted(driver.added)


async def test_a_crashing_speed_checker_names_nodes_that_were_planned_but_not_attempted(
    monkeypatch,
):
    """The deferral map covers the *whole* list, not just what was measured.

    The guard builds its map from `order + planned_deferred`, which is easy to
    get wrong in a way that still passes the previous test's shape: naming only
    the attempted tags would leave a node absent from both `samples` and
    `deferred`, so the run report's counts would sum to less than the pool.
    Seven nodes through a `top_n=3` policy is the fixture that separates the
    two, because four of them are planned deferrals rather than attempts.
    """
    import hub.speedtest as speedtest_module

    monkeypatch.setattr(speedtest_module, "SpeedChecker", _ExplodingChecker)

    nodes = _nodes(7)
    driver = _StageDriver()
    stage = SpeedStage(
        driver=driver,
        policy=SpeedPolicy(top_n=3, transfer_concurrency=2, timeout_s=3.0,
                           max_load=None),
    )
    report = await stage.measure_nodes(nodes, _keys(nodes))

    assert set(report.deferred) == set(_keys(nodes)), sorted(report.deferred)
    assert report.samples == []


# --------------------------------------------------------------------------- #
# the operator's escape hatch
# --------------------------------------------------------------------------- #


def test_the_load_ceiling_is_reachable_on_a_box_that_is_never_idle(monkeypatch):
    """A guard that can never be satisfied is a feature that is off.

    The throughput stage is the answer to the operator's ranking priority, and
    on this box it defers every round: the 0.85/core ceiling against a host
    running an editor, a browser and a VM at 1.5-2.5/core. Nothing is wrong —
    measuring on a saturated box measures the co-tenant — but the consequence is
    `speed.measured: 0` in every run, forever, with no way for an operator to
    say "I know, measure anyway".

    So `HUB_MAX_LOAD` exists, and these are the three states it must have:
    unset means the safe default, a number means that ceiling, and `none` means
    "no ceiling" rather than "no measurement".
    """
    from hub.cli import _speed_policy_from_env

    monkeypatch.delenv("HUB_MAX_LOAD", raising=False)
    monkeypatch.delenv("HUB_TOP_N", raising=False)
    assert _speed_policy_from_env().max_load == DEFAULT_MAX_LOAD

    monkeypatch.setenv("HUB_MAX_LOAD", "6")
    assert _speed_policy_from_env().max_load == 6.0

    monkeypatch.setenv("HUB_MAX_LOAD", "none")
    assert _speed_policy_from_env().max_load is None, (
        "`none` must disable the guard, not mean zero"
    )

    monkeypatch.setenv("HUB_MAX_LOAD", "off")
    assert _speed_policy_from_env().max_load is None

    monkeypatch.setenv("HUB_TOP_N", "12")
    assert _speed_policy_from_env().top_n == 12


def test_a_typo_in_the_override_falls_back_rather_than_killing_the_run(monkeypatch):
    """An optional override must not be able to stop a probe run.

    A misspelled ceiling is an operator problem to surface in the run report,
    not a reason for `hub run` to die before it fetches anything. The deferral
    is already visible in the report either way, so the safe failure is to
    ignore the bad value and continue with defaults.
    """
    from hub.cli import _speed_policy_from_env

    monkeypatch.setenv("HUB_MAX_LOAD", "not-a-number")
    monkeypatch.delenv("HUB_TOP_N", raising=False)
    assert _speed_policy_from_env().max_load == DEFAULT_MAX_LOAD

    monkeypatch.delenv("HUB_MAX_LOAD", raising=False)
    monkeypatch.setenv("HUB_TOP_N", "lots")
    assert _speed_policy_from_env().top_n == DEFAULT_TOP_N


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
