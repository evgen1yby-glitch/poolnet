"""Tests for the SSRF guard, the funnel ordering, and the CoreDriver protocol."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


from hub.models import Node, Protocol, Security, Stage, Transport, TransportSettings, TLS  # noqa: E402
from hub.prober import Concurrency, Prober, is_blocked_address  # noqa: E402


async def _dial_nowhere(address: str, port: int) -> None:
    """Stand-in for a real TCP connect: succeeds without touching the network.

    Injected via the `connect` seam so the *cheap* stages stop being the ones
    under test. Using the real `_raw_connect` here would resolve `example.com`
    for every fixture node, which is I/O the tests must not perform.
    """
    return None


def _prober(driver, **kwargs) -> Prober:
    """A `Prober` with no network at either stage: fake driver + no-op dial."""
    concurrency = kwargs.pop(
        "concurrency", Concurrency(tcp=5, tls=5, http=5, round2_gap_s=0.0)
    )
    return Prober(driver=driver, concurrency=concurrency, connect=_dial_nowhere, **kwargs)


def test_ssrf_guard_blocks_private_ranges():
    for address in ("10.1.2.3", "192.168.0.1", "172.16.5.5", "127.0.0.1", "169.254.169.254"):
        assert is_blocked_address(address) is True, address


def test_ssrf_guard_blocks_cgnat_and_ipv6():
    assert is_blocked_address("100.64.0.1") is True
    assert is_blocked_address("::1") is True
    assert is_blocked_address("fe80::1") is True
    assert is_blocked_address("[fd00::1]") is True


def test_ssrf_guard_passes_public():
    assert is_blocked_address("1.1.1.1") is False
    assert is_blocked_address("nl.example.com") is False
    assert is_blocked_address("203.0.113.1") is False  # TEST-NET-3, not ours to reject
    assert is_blocked_address("2606:4700:4700::1111") is False


def test_ssrf_guard_blocks_documentation_prefix():
    """`2001:db8::/32` is documentation-only and never routable.

    It is *not* in the same class as a public address, so a test asserting it
    passes would pin the wrong rule. A node advertising it is unreachable.
    """
    assert is_blocked_address("2001:db8::1") is True


def test_ssrf_guard_blocks_metadata_aliases():
    assert is_blocked_address("metadata.google.internal") is True
    assert is_blocked_address("localhost") is True


# --------------------------------------------------------------------------- #
# fake core driver
# --------------------------------------------------------------------------- #


class FakeDriver:
    """Scripted responses so the funnel runs without network or sing-box."""

    def __init__(self, *, tcp_ok=True, tls_ok=True, config_ok=True, http_ok=True,
                 trace_data={"ip": "203.0.113.7", "loc": "NL", "colo": "AMS"}):
        self.flags = dict(tcp=tcp_ok, tls=tls_ok, config=config_ok, http=http_ok)
        self.started = False
        self.stopped = False
        self.added: list[str] = []
        self.removed: list[str] = []
        self.socks_calls: list[str] = []
        #: What `trace` answers. `trace_data=None` makes the driver declare no
        #: trace capability at all, which is the pre-trace behaviour and has to
        #: stay supported: making the stage mandatory broke older drivers.
        self.trace_data = trace_data
        self.trace_calls = []
        self.speed_reads: list[tuple[str, str, float]] = []

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def add_node(self, node, tag):
        self.added.append(tag)

    async def remove_node(self, tag):
        self.removed.append(tag)

    async def socks_check(self, tag, *, timeout=5.0):
        self.socks_calls.append(tag)
        return self.flags["http"], 0.12

    async def trace(self, tag, *, timeout=5.0):
        self.trace_calls.append(tag)
        if self.trace_data is None:
            raise AttributeError("trace")
        return self.trace_data

    async def config_ok(self, node):
        return self.flags["config"]

    async def speed_read(self, tag, url, timeout):
        """One gap of `MIN_WINDOW_BYTES`, which is a whole measurement.

        Yielding exactly the volume bound means the speed stage's window closes
        on its *volume* check rather than its timeout, so a pipeline test
        exercises the fast path without spending 12 seconds per node on a slow
        reader.

        A driver that reports *no* throughput capability cannot be simulated by
        a method that yields nothing: a callable `speed_read` is the capability.
        `SpeedStage` probes with `getattr`, so absence has to be modelled by
        deleting the attribute — see `NoSpeedDriver` below.
        """
        self.speed_reads.append((tag, url, timeout))
        yield b"x" * (1024 * 1024)
        return


class NoSpeedDriver(FakeDriver):
    """A `FakeDriver` with the throughput capability genuinely absent.

    Not `speed_bps=0`, and not a `speed_read` that yields nothing: both of those
    declare a *working* capability that happens to be useless, and the
    pipeline's guard is `getattr(driver, "speed_read", None)`. Deleting the
    inherited attribute is the only way to express "this driver predates
    throughput", which is the upgrade path that has to keep working.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Instance attribute shadowing the class method. `del type(self)...`
        # would mutate `FakeDriver` for every other test in the process.
        self.speed_read = None


def _node(**over):
    base = dict(
        protocol=Protocol.VLESS,
        address="nl.example.com",
        port=443,
        uuid="11111111-2222-3333-4444-555555555555",
        transport=Transport.TCP,
        transport_settings=TransportSettings(kind=Transport.TCP),
        security=Security.NONE,  # skip the TLS stage in fake tests
        remark="n",
        country="NL",
        source="fixture",
    )
    base.update(over)
    return Node(**base)


# --------------------------------------------------------------------------- #
# funnel
# --------------------------------------------------------------------------- #


async def test_happy_path_reaches_http_stage():
    driver = FakeDriver()
    prober = _prober(driver)
    nodes = [_node(address=f"{i}.example.com") for i in range(3)]
    report = await prober.run(nodes)
    assert driver.started and driver.stopped
    assert report.stage_survivors.get("http") == 3
    assert all(r.ok for r in report.results)


async def test_driver_removes_every_node_it_added():
    driver = FakeDriver()
    prober = _prober(driver)
    await prober.run([_node(address=f"{i}.example.com") for i in range(4)])
    assert sorted(driver.added) == sorted(driver.removed)
    assert len(driver.added) == 4


async def test_private_address_never_reaches_the_driver():
    driver = FakeDriver()
    prober = _prober(driver)
    nodes = [_node(address="10.0.0.1"), _node(address="nl.example.com")]
    report = await prober.run(nodes)
    assert report.stage_errors.get("ssrf") == 1
    # The private address is dropped before the TCP gate, so it never reaches
    # the driver and is recorded as an SSRF rejection, not a connectivity one.
    assert len(driver.added) == 1
    assert driver.added == [nodes[1].dedup_key[:16]]
    rejected = [r for r in report.results if not r.ok]
    assert len(rejected) == 1
    assert rejected[0].dedup_key == nodes[0].dedup_key
    assert rejected[0].stage_reached is Stage.TCP
    assert rejected[0].error == "ssrf guard"


async def test_failed_tcp_stops_the_node_early():
    class DeadDial:
        def __init__(self):
            self.calls: list[tuple[str, int]] = []

        async def __call__(self, address: str, port: int) -> None:
            self.calls.append((address, port))
            raise OSError("connection refused")

    driver = FakeDriver()
    dial = DeadDial()
    prober = Prober(driver=driver, concurrency=Concurrency(round2_gap_s=0.0), connect=dial)
    report = await prober.run([_node()])
    # A node that cannot connect is never handed to the driver at all.
    assert driver.added == []
    assert report.stage_survivors.get("tcp", 0) == 0
    assert not any(r.ok for r in report.results)


async def test_failed_config_stops_the_node_early():
    driver = FakeDriver(config_ok=False)
    prober = _prober(driver)
    report = await prober.run([_node()])
    assert driver.added == []
    assert report.stage_errors.get("config") == 1


async def test_stage_order_is_cheapest_first():
    """TCP is gated by concurrency 200; HTTP by 100. Both are socket-bound."""

    class CountingDriver(FakeDriver):
        def __init__(self):
            super().__init__()
            self.order: list[str] = []

        async def add_node(self, node, tag):
            self.order.append("add")
            await super().add_node(node, tag)

        async def config_ok(self, node):
            self.order.append("config")
            return True

    driver = CountingDriver()
    prober = _prober(driver)
    await prober.run([_node()])
    # config_ok runs before add_node: the HTTP stage is the most expensive and
    # must be reached last.
    assert driver.order == ["config", "add"]
    assert Concurrency().http == 100
    assert Concurrency().tcp == 200


async def test_two_round_http_check_keeps_flapping_out():
    """A node must pass >=1 of 2 rounds; the crew tests the 45 s gap separately."""
    driver = FakeDriver(http_ok=False)
    prober = _prober(driver)
    report = await prober.run([_node()])
    assert all(not r.ok for r in report.results)
    assert report.stage_errors.get("http") == 1


async def test_driver_sees_every_node_it_added():
    """Stage 4 adds and removes by the same tag, or the SOCKS inbound leaks."""

    class TaggingDriver(FakeDriver):
        def __init__(self):
            super().__init__()
            self.tags: list[str] = []

        async def add_node(self, node, tag):
            self.tags.append(tag)
            await super().add_node(node, tag)

    driver = TaggingDriver()
    prober = _prober(driver)
    node = _node()
    await prober.run([node])
    # The tag is derived from the dedup key, so it is stable across runs and
    # safe to log (no credentials in it).
    assert driver.tags == [node.dedup_key[:16]]


async def test_semaphore_is_shared_per_stage():
    """One semaphore per stage, keyed by name, so limits survive across nodes."""

    driver = FakeDriver()
    prober = _prober(driver)
    first = prober._sem("http", 5)
    second = prober._sem("http", 5)
    assert first is second
    # An unlimited stage (config) returns None rather than a semaphore.
    assert prober._sem("config", 0) is None


# --------------------------------------------------------------------------- #
# exit country (cdn-cgi/trace)
# --------------------------------------------------------------------------- #


async def test_exit_country_is_measured_not_inferred():
    """The landing page groups by country, so the country must be measured.

    `Node.country` is a *claim* on the share URI; `exit_country` is what the node
    actually reported through Cloudflare's trace endpoint. Filling the measured
    one is what turns the landing page's country sections into facts, and a
    test that only checks the node survives the funnel would pass either way.
    """
    driver = FakeDriver(trace_data={"ip": "203.0.113.9", "loc": "de", "colo": "FRA"})
    prober = _prober(driver)
    node = _node(country="NL")  # the URI claims NL; the exit says DE
    report = await prober.run([node])
    result = report.by_key()[node.dedup_key]
    assert result.ok, result.error
    assert driver.trace_calls, "the trace stage never ran"
    # Normalised to upper-case, because a mixed-case column splits one country
    # into two groups on the landing page.
    assert result.exit_country == "DE"
    assert result.exit_ip == "203.0.113.9"
    assert result.exit_colo == "FRA"


async def test_trace_is_not_called_for_a_dead_node():
    """A country read from a node that cannot carry traffic is a lie.

    The scorer believes `exit_country` when it disagrees with the claim, so a
    fabricated one would silently downgrade a node that simply timed out.
    """
    driver = FakeDriver(http_ok=False, trace_data={"loc": "NL"})
    prober = _prober(driver)
    node = _node()
    report = await prober.run([node])
    assert not report.by_key()[node.dedup_key].ok
    assert driver.trace_calls == [], "traced a node that never answered"


async def test_trace_is_optional_for_older_drivers():
    """A driver written before the trace stage must keep working.

    `getattr` in the prober rather than a protocol cast: a required method here
    would break every already-written driver on upgrade, and a missing country
    is worth far less than a broken funnel.

    Written against a driver that implements only the four mandatory methods,
    because that is the literal shape of "older driver": not a trace that raises,
    an absent attribute. A driver that raised would exercise the `except`
    branch instead and let this test pass for the wrong reason.
    """
    class PreTraceDriver:
        def __init__(self):
            self.added, self.removed = [], []
            self.socks_calls: list[str] = []

        async def start(self): pass
        async def stop(self): pass
        async def add_node(self, node, tag): self.added.append(tag)
        async def remove_node(self, tag): self.removed.append(tag)
        async def socks_check(self, tag, *, timeout=5.0): return True, 0.12
        async def config_ok(self, node): return True

    driver = PreTraceDriver()
    assert not hasattr(driver, "trace")
    prober = _prober(driver)
    node = _node()
    report = await prober.run([node])
    result = report.by_key()[node.dedup_key]
    assert result.ok, result.error
    assert result.exit_country == ""
    assert result.exit_ip == ""
    prober = _prober(driver)
    node = _node()
    report = await prober.run([node])
    result = report.by_key()[node.dedup_key]
    assert result.ok, result.error
    assert result.exit_country == ""
    assert result.exit_ip == ""


async def test_unknown_country_code_is_dropped_not_kept():
    """Cloudflare answers `loc=XX` for "unknown"; that is not a country.

    Keeping it would put a literal "XX" on the landing page as if it were a
    place, and the country filter would offer it as a destination.
    """
    driver = FakeDriver(trace_data={"ip": "203.0.113.5", "loc": "xx", "colo": "X"})
    prober = _prober(driver)
    node = _node()
    report = await prober.run([node])
    result = report.by_key()[node.dedup_key]
    assert result.ok
    # The IP is still worth keeping — it is the one genuinely measured fact.
    assert result.exit_country == ""
    assert result.exit_ip == "203.0.113.5"


async def test_a_trace_failure_never_fails_the_node():
    """Country is a bonus, not a gate.

    The HTTP rounds already proved the node carries traffic. Losing the trace —
    blocked CDN, timeout, malformed body — must not discard a working node.
    """
    driver = FakeDriver(trace_data={})  # a body with no loc at all
    prober = _prober(driver)
    node = _node()
    report = await prober.run([node])
    result = report.by_key()[node.dedup_key]
    assert result.ok, result.error
    assert result.exit_country == ""


def test_concurrency_limits_come_from_the_environment(monkeypatch):
    """An operator on a shared box can shrink the probe's footprint.

    The deployment constraint is explicit: this host also runs another VPN
    project and the probe must not disturb it. 200 parallel dials is fine on a
    dedicated runner and antisocial here, so the limits have to be settable
    without editing source — and readable back, which is what `Concurrency()`
    now does.
    """
    monkeypatch.setenv("HUB_TCP_CONCURRENCY", "8")
    monkeypatch.setenv("HUB_TLS_CONCURRENCY", "8")
    monkeypatch.setenv("HUB_HTTP_CONCURRENCY", "4")
    monkeypatch.setenv("HUB_TCP_TIMEOUT", "0.5")
    limits = Concurrency()
    assert limits.tcp == 8, limits
    assert limits.tls == 8, limits
    assert limits.http == 4, limits
    assert limits.tcp_timeout == 0.5, limits


def test_a_nonsense_limit_is_ignored_rather_than_fatal(monkeypatch):
    """A typo in the environment must not take the whole run down.

    `HUB_TCP_CONCURRENCY=abc` used to mean nothing; now it means the default.
    Refusing to start would turn a typo into an outage, and silently using 0
    permits would deadlock the stage — both worse than the default.
    """
    monkeypatch.setenv("HUB_TCP_CONCURRENCY", "abc")
    monkeypatch.setenv("HUB_HTTP_CONCURRENCY", "0")
    monkeypatch.setenv("HUB_TLS_TIMEOUT", "not-a-number")
    limits = Concurrency()
    assert limits.tcp == 200, limits
    assert limits.http == 100, limits
    assert limits.tls_timeout == 3.0, limits


def test_no_environment_keeps_the_documented_defaults(monkeypatch):
    """The default is still the default when nothing is set."""
    for name in ("TCP", "TLS", "HTTP", "REPUTATION"):
        monkeypatch.delenv(f"HUB_{name}_CONCURRENCY", raising=False)
    limits = Concurrency()
    assert limits.tcp == 200
    assert limits.http == 100


async def test_the_tcp_stage_runs_nodes_concurrently():
    """Stage 1 must overlap its dials, or a round is dials × timeout.

    The loop here was `for node: await self._tcp(node)` — one node at a time —
    so 337 nodes at the 2 s default took 11 minutes before a single TLS
    handshake. The stage already had a `tcp` semaphore, which made the
    sequential loop look bounded while permitting exactly one call in flight
    at a time. That is the shape to prevent from coming back.

    The observable is overlap of the underlying dials, not the wall clock: a
    dial that sleeps is how time is spent, and only a concurrent loop puts
    more than one of them in flight.
    """
    in_flight = 0
    peak = 0

    class SlowDial:
        async def __call__(self, address, port):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            try:
                await asyncio.sleep(0.02)
            finally:
                in_flight -= 1

    nodes = [_node(address=f"n{i}.example.com") for i in range(20)]
    prober = Prober(
        driver=FakeDriver(),
        concurrency=Concurrency(tcp=8, tls=8, http=8, round2_gap_s=0.0),
        connect=SlowDial(),
    )
    report = await prober.run(nodes)
    assert peak > 1, (
        "TCP dials never overlapped; stage 1 is sequential again and a "
        "large round takes len(nodes) * tcp_timeout"
    )
    assert report.stage_survivors.get("tcp") == len(nodes)


async def test_the_tls_stage_acquires_its_semaphore_exactly_once():
    """Each stage's semaphore must be taken by exactly one frame.

    The stage-1 note in `run()` says concurrency comes from `gather` and the
    semaphore only caps. Stage 2 was written the other way round: `run()` took
    the `tls` semaphore *and then* called `_tls`, which took it again. With
    `gather` starting every node at once the outer wrappers consume all
    `limits.tls` permits and each inner waits for a permit whose only holders
    are the wrappers, blocked on the inners they started. Nothing times out and
    nothing raises — the round just stops, mid-stage, forever.

    That is the shape to pin. It cannot be written as "does it finish", because
    a hang is a terrible failure mode for a suite; instead the test asserts the
    *invariant* the deadlock violated, and checks the accounting that only holds
    when it is intact: a deadlocked cohort leaves `limits.tls` permits held by
    tasks that can no longer finish, so the semaphore would be drained with
    waiters queued behind a holder that never returns.

    A test that only asserted "the funnel reached http" would also pass if the
    semaphore were removed entirely, so it checks the cap too: with `tls=1` the
    handshakes must have been serialised, which is the semaphore doing its job
    exactly once rather than not at all.
    """
    in_flight = 0
    peak = 0

    class SerialisingHandshake:
        """A handshake slow enough that `tls=1` has to actually withhold work."""

        async def __call__(self, address, port, server_hostname, context):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            try:
                await asyncio.sleep(0.05)
                return object(), _ClosableWriter()
            finally:
                in_flight -= 1

    nodes = [
        _node(address=f"n{i}.example.com", security=Security.TLS, tls=TLS(sni="example.com"))
        for i in range(12)
    ]
    prober = Prober(
        driver=FakeDriver(),
        concurrency=Concurrency(tcp=16, tls=1, http=8, round2_gap_s=0.0),
        connect=_dial_nowhere,
        handshake=SerialisingHandshake(),
    )
    report = await asyncio.wait_for(prober.run(nodes), 30)

    # The deadlock is gone: every node crossed stage 2 rather than stalling in it.
    assert report.stage_survivors.get("tls") == len(nodes), (
        report.stage_errors,
        "stage 2 lost nodes; if the run also hung, the tls semaphore is being "
        "acquired twice on one path",
    )
    # And the cap is real, so the fix was not "delete the semaphore": `tls=1`
    # must have serialised the handshakes down to one at a time.
    assert peak == 1, (
        f"{peak} handshakes overlapped with tls=1; the tls semaphore no longer "
        "bounds the stage"
    )
    # The permits are all back where they started. A cohort that left a holder
    # blocked in the inner acquisition shows `value: 0` with N waiters.
    sem = prober._sem("tls", prober.limits.tls)
    assert sem is not None
    assert sem._value == 1 and not (sem._waiters or ()), (
        f"tls semaphore leaked: value={sem._value} waiters={len(sem._waiters or ())}"
    )


async def test_a_failing_tls_does_not_keep_the_semaphore():
    """A leak and a deadlock wear the same coat.

    Both are "permits drain, waiters queue, nothing finishes". The test above
    pins the double-acquisition version; this one pins the version where the
    stage-2 semaphore is held across a path that can raise and never released.
    Killing every node at stage 2 must leave the semaphore whole, and it is
    asserted on the state asyncio reports rather than on the wall clock.

    It does **not** fail against the double-acquisition bug — with a driver that
    never blocks, the outer wrappers finish before the permits matter. Its job
    is the failure path, which it catches by mutation: replacing `async with
    sem` in `_tls` with a bare `acquire()` makes the run hang here.
    """

    class RaisingHandshake:
        async def __call__(self, address, port, server_hostname, context):
            raise OSError("handshake refused")

    nodes = [
        _node(address=f"n{i}.example.com", security=Security.TLS, tls=TLS(sni="example.com"))
        for i in range(10)
    ]
    prober = Prober(
        driver=FakeDriver(tls_ok=False),
        concurrency=Concurrency(tcp=10, tls=3, http=3, round2_gap_s=0.0),
        connect=_dial_nowhere,
        handshake=RaisingHandshake(),
    )
    report = await asyncio.wait_for(prober.run(nodes), 30)
    assert report.stage_survivors.get("tls", 0) == 0
    assert report.stage_errors.get("tls") == len(nodes)
    sem = prober._sem("tls", prober.limits.tls)
    assert sem is not None
    assert sem._value == 3 and not (sem._waiters or ()), (
        f"tls semaphore leaked through the failure path: value={sem._value} "
        f"waiters={len(sem._waiters or ())}"
    )


class _ClosableWriter:
    """The half of a stream the funnel actually touches."""

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass
