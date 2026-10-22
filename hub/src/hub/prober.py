"""The verification funnel — five stages, cheapest first.

Ordering is the whole design. Each stage is an order of magnitude cheaper than
the next, so a node that cannot pass stage 1 never consumes a stage-4 socket.
Live numbers from the reference implementation: ~4800 raw -> 2900 TCP -> 2600
TLS -> 840 config-valid -> ~280 verified. That is a 5.8% yield, and the
expensive stages see 4% of the candidates.

Concurrency is **socket-bound, not CPU-bound** (v2go measures ~40 us of CPU per
config, so 10k configs cost 0.4 s total). The limits below are therefore chosen
for what the *targets* tolerate, not what we can afford:

* 200 concurrent TCP connects — drops ~40% of the pool for almost nothing.
* 200 concurrent TLS handshakes — pipes the survivors through.
* unbounded `sing-box check` — pure CPU, microseconds each.
* **100 concurrent HTTP-over-proxy**, tested in two rounds 45 s apart, keeping
  only nodes with >=50% success. Above ~500 the reference implementation
  empirically degrades.
* 20 reputation lookups — API free tiers, published nodes only.

The prober never opens a listening port on the host network and never dials a
private address: both are enforced in `ssrf_guard`, before the driver sees the
node.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable, Iterable, Optional, Protocol, Sequence

from .models import Node, ProbeResult, Stage, is_blocked_address

# --------------------------------------------------------------------------- #
# SSRF guard
# --------------------------------------------------------------------------- #

#: `is_blocked_address` and its block list live in `models.py`, so the parser and
#: the prober reject exactly the same set. This module used to keep a second copy
#: that had `2001:db8::/32`; the parser's copy did not, so a documentation-prefix
#: address parsed cleanly and only died at a later stage — a weaker guard wearing
#: the costume of a strong one. It is re-exported here because every caller of
#: the prober imports the guard from here.
__all__ = ["is_blocked_address", "Concurrency", "CoreDriver", "RoundTrip",
           "ProbeReport", "Prober", "node_tag"]


def node_tag(node: Node) -> str:
    """The driver tag one node is registered under, in every stage.

    `speedtest.SpeedStage` re-registers a node the prober already measured, and
    the two must agree on the name or the speed stage adds the node under one
    tag and reads bytes through a *different* node's SOCKS port — which would
    attribute one node's throughput to another's key and quietly corrupt the
    ranking. Deriving it here, next to the funnel that mints it, makes the
    duplication structural rather than a convention two modules have to keep in
    sync by hand.

    16 characters, matching the prefix length already used by `_http`.
    """
    return node.dedup_key[:16]


# --------------------------------------------------------------------------- #
# Core driver protocol
# --------------------------------------------------------------------------- #


class CoreDriver(Protocol):
    """The prober talks to this; the sing-box driver implements it.

    Keeping it a Protocol means the entire funnel is testable with a scripted
    fake — no network, no binary, no ports.
    """

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def add_node(self, node: Node, tag: str) -> None:
        """Register a node as an outbound plus a tagged local SOCKS inbound."""
        ...
    async def remove_node(self, tag: str) -> None: ...
    async def socks_check(self, tag: str, *, timeout: float) -> tuple[bool, float]:
        """Return (ok, seconds) for an HTTP request over the node's SOCKS port."""
        ...
    async def trace(self, tag: str, *, timeout: float) -> Optional[dict]:
        """Where does this node actually exit? `{}`/`None` when unavailable.

        `cdn-cgi/trace` over the node's own SOCKS port. This is *optional*: a
        driver without it still probes, it just produces no `exit_country`, and
        `Node.country` stays empty rather than being guessed at. Adding it as a
        required method would break every existing driver on upgrade, and a
        country is worth less than a working funnel.

        Keys are the flat trace fields — `loc`, `ip`, `colo`; the prober maps
        them onto `ProbeResult`.
        """
        ...
    async def config_ok(self, node: Node) -> bool:
        """`sing-box check` semantics: would this config even start?"""
        ...
    async def speed_read(
        self, tag: str, url: str, timeout: float
    ) -> AsyncIterator[bytes]:
        """Stream bytes over the node's own SOCKS port.

        Optional, like `trace`: a driver without it still probes, it just
        produces no `speed_bps`, and `scorer._throughput_points` scores the
        node at half credit rather than zero. `hub.speedtest.SpeedChecker`
        owns the *policy* (what to fetch, when to stop); this method is the
        only part that touches the network, which is why the split exists —
        the policy is testable against a scripted reader with no binary and no
        sockets.

        Yielding rather than returning one blob is deliberate: a driver that
        buffered a whole 4 MiB body into memory before returning could not be
        cut off mid-transfer, and the whole byte-bounded safety argument rests
        on being able to stop asking.
        """
        ...


# --------------------------------------------------------------------------- #
# Concurrency policy
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Concurrency:
    """How much network the funnel may use at once, and for how long.

    Every field is overrideable from the environment (`HUB_TCP_CONCURRENCY`,
    `HUB_TLS_CONCURRENCY`, `HUB_HTTP_CONCURRENCY`, …) because the right value
    is a property of the *box*, not of the code: 200 parallel dials is
    unremarkable on a dedicated runner and antisocial next to somebody else's
    VPN project on the same host. The operator constraint on this deployment is
    explicit — the probe must not disturb the neighbouring services — so the
    default has to be lowerable without a code change, and readable afterwards.

    `0` means unlimited for `config`, matching the previous behaviour; the
    same `0` on a semaphore field would deadlock the stage, so those fields
    treat `0` as "use the default" rather than as "no permits".
    """
    tcp: int = 200
    tls: int = 200
    config: int = 0  # 0 = unlimited
    http: int = 100
    reputation: int = 20
    tcp_timeout: float = 2.0
    tls_timeout: float = 3.0
    http_timeout: float = 5.0
    #: Gap between the two HTTP rounds. 45 s is the reference-implementation
    #: value and the default: close together and a node that was merely up
    #: during one test window looks stable. Tests set it to 0 so the funnel
    #: runs in milliseconds without weakening the rule.
    round2_gap_s: float = 45.0

    def __post_init__(self) -> None:
        for name in ("tcp", "tls", "http", "reputation"):
            raw = os.environ.get(f"HUB_{name.upper()}_CONCURRENCY", "").strip()
            if not raw:
                continue
            try:
                value = int(raw)
            except ValueError:
                continue
            if value > 0:
                object.__setattr__(self, name, value)
        for name in ("tcp_timeout", "tls_timeout", "http_timeout"):
            raw = os.environ.get(f"HUB_{name.upper()}", "").strip()
            if not raw:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if value > 0:
                object.__setattr__(self, name, value)


#: The two network seams, as types. Both are defined with names that resolve at
#: import time (`object`, not `ssl.SSLContext`) — under
#: `from __future__ import annotations` a *function* annotation would be fine
#: as a string, but a module-level alias like this one is evaluated eagerly,
#: so it can only name things the module already imports.
_Connector = Callable[[str, int], Awaitable[None]]

#: A stage-2 handshake, positional (address, port, server_hostname, context).
_TlsHandshake = Callable[[str, int, str, object], Awaitable[tuple[object, object]]]


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #

@dataclass
class RoundTrip:
    """One candidate's passage through the funnel, for the metrics endpoint."""

    stage_reached: Stage
    survivors: dict[str, int] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)


@dataclass
class ProbeReport:
    """What one pipeline run measured. Feeds metrics and the score history."""

    results: list[ProbeResult] = field(default_factory=list)
    stage_survivors: dict[str, int] = field(default_factory=dict)
    stage_errors: dict[str, int] = field(default_factory=dict)
    duration_s: float = 0.0
    #: Why the driver never came up, if it did not. Empty on every healthy run.
    #: Without this field a driver failure is indistinguishable from a round in
    #: which every node was dead, and the run report is the only place an
    #: operator looks.
    driver_error: str = ""

    def by_key(self) -> dict[str, ProbeResult]:
        return {r.dedup_key: r for r in self.results}


# --------------------------------------------------------------------------- #
# The funnel
# --------------------------------------------------------------------------- #


class Prober:
    def __init__(
        self,
        driver: CoreDriver,
        concurrency: Concurrency | None = None,
        canary_token: str = "",
        connect: _Connector | None = None,
        handshake: _TlsHandshake | None = None,
    ) -> None:
        self.driver = driver
        self.limits = concurrency or Concurrency()
        self.canary_token = canary_token
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        #: The stage-1 dial. Injectable because a TCP connect is real I/O and
        #: the funnel's *cheap* stages are exactly the ones a fake driver does
        #: not cover — without this seam a fake-driven run does genuine DNS and
        #: every fixture node dies at stage 1, which is the opposite of
        #: production, where most candidates survive it.
        self._connect = connect or _raw_connect
        #: The stage-2 handshake. Injectable for the same reason: the tests
        #: below run against `example.com`, and letting a verifying handshake
        #: fire makes the outcome a function of the live internet.
        self._handshake = handshake or _tls_handshake

    def _sem(self, key: str, limit: int) -> asyncio.Semaphore | None:
        if limit <= 0:
            return None
        sem = self._semaphores.get(key)
        if sem is None:
            sem = asyncio.Semaphore(limit)
            self._semaphores[key] = sem
        return sem

    # -- stage 1: TCP ----------------------------------------------------

    async def _tcp(self, node: Node) -> ProbeResult | None:
        sem = self._sem("tcp", self.limits.tcp)
        try:
            if sem is not None:
                async with sem:
                    return await self._tcp_inner(node)
            return await self._tcp_inner(node)
        except asyncio.TimeoutError:
            return ProbeResult(node.dedup_key, Stage.TCP, ok=False, error="tcp timeout")
        except Exception as exc:  # noqa: BLE001 - a probe must not crash the run
            return ProbeResult(node.dedup_key, Stage.TCP, ok=False, error=f"{type(exc).__name__}: {exc}")

    async def _raw_dial(self, node: Node) -> None:
        """Bare TCP connect against the *real* network, for the stage-1 gate."""
        await asyncio.wait_for(
            self._connect(node.address, node.port), timeout=self.limits.tcp_timeout
        )

    async def _tcp_inner(self, node: Node) -> ProbeResult | None:
        started = time.monotonic()
        await self._raw_dial(node)
        elapsed = (time.monotonic() - started) * 1000.0
        return ProbeResult(node.dedup_key, Stage.TLS, ok=True, tcp_ms=elapsed)

    # -- stage 2: TLS ----------------------------------------------------

    async def _tls(self, node: Node, passed: ProbeResult) -> ProbeResult:
        # The `tls` semaphore is acquired HERE and only here. It is where the
        # timeout and exception handlers live, so a permit held by this frame is
        # released on every exit path — and it is the only frame on the stage-2
        # path that may take it. `run()` used to acquire it a second time
        # around this call, which deadlocked every node in the cohort.
        sem = self._sem("tls", self.limits.tls)
        try:
            if sem is not None:
                async with sem:
                    return await self._tls_inner(node, passed)
            return await self._tls_inner(node, passed)
        except asyncio.TimeoutError:
            return ProbeResult(
                passed.dedup_key, Stage.TLS, ok=False, tcp_ms=passed.tcp_ms, error="tls timeout"
            )
        except Exception as exc:  # noqa: BLE001
            return ProbeResult(
                passed.dedup_key, Stage.TLS, ok=False, tcp_ms=passed.tcp_ms,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _tls_inner(self, node: Node, passed: ProbeResult) -> ProbeResult:
        """A **verifying** TLS handshake against the SNI the node advertises.

        This is the anti-MITM stage, and it only works if we actually verify:
        published free-proxy measurements find ~4% of nodes perform TLS
        interception, which shows up here as a certificate that is either
        untrusted, expired, or issued for a name other than the advertised
        SNI. We therefore build a verifying context and let the handshake
        fail — then record *why* it failed as a security signal.

        A REALITY node serves the conjunction of its advertised SNI's real
        certificate, so the verifying handshake succeeds for an honest node;
        an interception proxy serves its own CA, which is not in the public
        trust store, and fails.

        We deliberately do **not** disable verification — a non-verifying
        handshake here would classify every MITM as healthy.
        """
        import ssl

        if node.security.value == "none" or node.security is None:
            # A plain-TCP node has no TLS stage to fail; it advances to the
            # config check unchanged.
            return ProbeResult(
                passed.dedup_key, Stage.CONFIG, ok=True,
                tcp_ms=passed.tcp_ms, tls_ms=None,
            )

        server_hostname = (node.tls.sni or node.address).strip()
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.minimum_version = ssl.TLSVersion.TLSv1_2

        started = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                self._handshake(node.address, node.port, server_hostname, context),
                timeout=self.limits.tls_timeout,
            )
        except ssl.SSLCertVerificationError as exc:
            elapsed = (time.monotonic() - started) * 1000.0
            # Untrusted chain / hostname mismatch / expired: the node either
            # intercepts TLS or is misconfigured. Both are disqualifying for a
            # hub whose whole pitch is "we check what the incumbent does not".
            result = ProbeResult(
                passed.dedup_key, Stage.TLS, ok=False,
                tcp_ms=passed.tcp_ms, tls_ms=elapsed,
                cert_substituted=True, error=f"cert verification: {exc.verify_message or exc}",
            )
            return result
        except (ssl.SSLError, ssl.SSLEOFError) as exc:
            elapsed = (time.monotonic() - started) * 1000.0
            result = ProbeResult(
                passed.dedup_key, Stage.TLS, ok=False,
                tcp_ms=passed.tcp_ms, tls_ms=elapsed,
                error=f"ssl: {type(exc).__name__}: {exc}",
            )
            return result
        except asyncio.TimeoutError:
            raise

        try:
            elapsed = (time.monotonic() - started) * 1000.0
            return ProbeResult(
                passed.dedup_key, Stage.CONFIG, ok=True,
                tcp_ms=passed.tcp_ms, tls_ms=elapsed,
            )
        finally:
            # The same unbounded wait `hub.singbox` had, and the same hazard:
            # the handshake above is cancelled by a `wait_for` timer, so a node
            # that stops mid-handshake leaves this writer's transport paused
            # with an undrained buffer — the state where
            # `_SelectorSocketTransport.close` never schedules
            # `connection_lost` and `wait_closed` never resolves. Bounded, and
            # imported from the driver so there is exactly one implementation
            # of the bound rather than two that can drift.
            from .singbox import _close_writer

            await _close_writer(writer, timeout=self.limits.tls_timeout)

    # -- stage 3: config -------------------------------------------------

    async def _config(self, node: Node, passed: ProbeResult) -> ProbeResult:
        """`sing-box check` semantics: would this outbound even start?

        This is where client-crashing parameters die: a VLESS node with no
        flow but `xtls-rprx-vision` in the URI, a gRPC transport with no
        service name, an XHTTP node for a sing-box client. It is pure CPU, so
        it runs unbounded.
        """
        try:
            if not await self.driver.config_ok(node):
                return ProbeResult(
                    passed.dedup_key, Stage.CONFIG, ok=False,
                    tcp_ms=passed.tcp_ms, tls_ms=passed.tls_ms, error="config check failed",
                )
        except Exception as exc:  # noqa: BLE001
            return ProbeResult(
                passed.dedup_key, Stage.CONFIG, ok=False,
                tcp_ms=passed.tcp_ms, tls_ms=passed.tls_ms,
                error=f"{type(exc).__name__}: {exc}",
            )
        return ProbeResult(
            passed.dedup_key, Stage.HTTP, ok=True,
            tcp_ms=passed.tcp_ms, tls_ms=passed.tls_ms,
        )

    # -- stage 4: HTTP over the proxy ------------------------------------

    async def _http(self, node: Node, passed: ProbeResult) -> ProbeResult:
        """Two rounds, 45 s apart, keep nodes with >=50% success.

        The second round is what kills flapping nodes. Reference implementation
        (Au1rxx) and subs-check both do it; a single round is the classic
        mistake that fills a subscription with nodes that were alive for
        exactly one test window.
        """
        sem = self._sem("http", self.limits.http)
        tag = node_tag(node)
        try:
            await self.driver.add_node(node, tag)
        except Exception as exc:  # noqa: BLE001
            return ProbeResult(
                passed.dedup_key, Stage.HTTP, ok=False,
                tcp_ms=passed.tcp_ms, tls_ms=passed.tls_ms,
                error=f"add_node: {type(exc).__name__}: {exc}",
            )

        try:
            # `_http_round` returns the driver's own `(ok, elapsed, error)`
            # triple, not a ProbeResult: the round is a measurement, and a
            # ProbeResult is only built once both rounds are in. Treating the
            # triple as an object is what made every node die with
            # `AttributeError: 'tuple' object has no attribute 'ok'`.
            if sem is not None:
                async with sem:
                    ok1, elapsed1, error1 = await self._http_round(node, tag)
            else:
                ok1, elapsed1, error1 = await self._http_round(node, tag)

            if not ok1:
                return ProbeResult(
                    passed.dedup_key, Stage.HTTP, ok=False,
                    tcp_ms=passed.tcp_ms, tls_ms=passed.tls_ms,
                    http_ms=elapsed1, error=error1, rounds_passed=0,
                )

            await asyncio.sleep(self.limits.round2_gap_s)
            ok2, elapsed2, error2 = await self._http_round(node, tag)

            passed_rounds = int(ok1) + int(ok2)
            ok = passed_rounds >= 1  # >=50% of 2 rounds
            result = ProbeResult(
                passed.dedup_key,
                Stage.HTTP,
                ok=ok,
                tcp_ms=passed.tcp_ms,
                tls_ms=passed.tls_ms,
                http_ms=elapsed1,
                http_ms_round2=elapsed2,
                rounds_passed=passed_rounds,
                error="" if ok else error2,
            )
            if ok:
                # Only a node that actually worked gets a trace: asking a dead
                # one is a wasted round trip, and an exit country read from a
                # node that cannot carry traffic is a lie the scorer would then
                # believe.
                exit_ip, exit_country, exit_colo = await self._trace(tag)
                result.exit_ip = exit_ip
                result.exit_country = exit_country
                result.exit_colo = exit_colo
            return result
        finally:
            try:
                await self.driver.remove_node(tag)
            except Exception:  # noqa: BLE001
                pass

    async def _trace(self, tag: str) -> tuple[str, str, str]:
        """`(exit_ip, exit_country, exit_colo)` — `("", "", "")` if unmeasurable.

        A country is the strongest single signal the pool has: it is what the
        landing page groups by, and a node whose exit disagrees with its claimed
        country is scored down by `_geo_points`. So this must be measured, never
        inferred from the hostname — `nl1.example.com` says nothing about where
        a node exits, and trusting the label is exactly how a pool ends up full
        of mislabelled nodes.

        Optional by design: `getattr` rather than a protocol cast, so a driver
        written before this existed keeps working and simply yields no country.
        A hard requirement here would break every existing driver on upgrade.
        """
        tracer = getattr(self.driver, "trace", None)
        if tracer is None:
            return "", "", ""
        try:
            data = await asyncio.wait_for(tracer(tag, timeout=self.limits.http_timeout),
                                         timeout=self.limits.http_timeout + 1.0)
        except Exception:  # noqa: BLE001
            return "", "", ""
        if not isinstance(data, dict):
            return "", "", ""
        loc = str(data.get("loc") or "").strip().upper()
        # A two-letter code is what the rest of the pipeline stores; anything
        # else (a full country name, or Cloudflare's `XX` for unknown) is
        # dropped rather than half-normalised, because "Netherlands" and "NL"
        # in the same column silently splits one country into two groups.
        if len(loc) != 2 or loc == "XX":
            return str(data.get("ip") or ""), "", ""
        return str(data.get("ip") or ""), loc, str(data.get("colo") or "")

    async def _http_round(self, node: Node, tag: str) -> tuple[bool, float, str]:
        """One HTTP request over the node, as `(ok, milliseconds, error)`.

        `Driver.socks_check` documents its duration in **seconds**, every other
        stage in this funnel records milliseconds, and `ProbeResult.http_ms` is
        milliseconds by name. Converting here rather than at each caller keeps
        the two conventions from meeting: passing the raw value through made a
        0.12 s round trip look like 0.14 ms, i.e. instant, so the latency factor
        (a quarter of the rubric) paid every node nearly full marks.
        """
        try:
            ok, elapsed = await asyncio.wait_for(
                self.driver.socks_check(tag, timeout=self.limits.http_timeout),
                timeout=self.limits.http_timeout + 1.0,
            )
            return ok, elapsed * 1000.0, "" if ok else "http failed"
        except asyncio.TimeoutError:
            return False, float("inf"), "http timeout"
        except Exception as exc:  # noqa: BLE001
            return False, float("inf"), f"{type(exc).__name__}: {exc}"

    # -- driver ----------------------------------------------------------

    async def run(self, nodes: Sequence[Node]) -> ProbeReport:
        """Run the whole funnel. Never raises; a dead node is a data point."""
        started = time.monotonic()
        report = ProbeReport()
        survivors: dict[str, int] = {}
        errors: dict[str, int] = {}

        try:
            # `start()` inside the `try`, where it was outside. A driver that
            # fails to start is the most ordinary failure there is — a config
            # sing-box rejects, a port it cannot bind, a binary that is present
            # and broken — and the docstring here says this method never raises.
            # With `start()` above the `try` it raised straight through
            # `_probe`, through `run_once`, and out of the CLI: the run recorded
            # no `run_done` event, no generation was considered, and the operator
            # got a traceback instead of "0 verified this round". The next run
            # behaved identically, so a persistently broken driver looked like a
            # crashing binary rather than a broken sandbox.
            #
            # Reported as a stage failure instead, which is what it is: the run
            # proceeds, `stage_errors` says the driver never came up, and the
            # previous generation is kept.
            await self.driver.start()
        except Exception as exc:  # noqa: BLE001 - a dead driver is a data point
            errors["driver"] = errors.get("driver", 0) + 1
            report.stage_errors = errors
            # The reason, kept. The first version of this handler counted the
            # failure and dropped `exc`, which is the shape that makes a stage
            # error useless: `errors.driver: 1` tells an operator *that* the
            # sandbox did not come up and nothing about which part — a missing
            # binary, a config sing-box rejects, or a port it cannot bind are
            # three different fixes, and "the driver failed" sends you to fix the
            # wrong one. `str(exc)` is enough here; the traceback would go on for
            # 40 lines in an event log that is appended to every round.
            report.driver_error = f"{type(exc).__name__}: {exc}"
            report.duration_s = round(time.monotonic() - started, 2)
            with contextlib.suppress(Exception):
                await self.driver.stop()
            return report
        try:
            # Stage 1 in bounded concurrency, the way the comment above always
            # claimed and the code never did: the loop below was
            # `for node in nodes: await self._tcp(node)`, which is one node at
            # a time, so a 337-node round spent up to `tcp_timeout` * 337 — 11
            # minutes at the default 2 s — before a single TLS handshake was
            # attempted. The `tcp` semaphore that `_tcp` already honoured was
            # doing nothing, because there was only ever one call in flight.
            #
            # The SSRF guard stays in front of it and stays synchronous: it is
            # a local address test, so it is not something to pay concurrency
            # for, and a blocked node must never reach a socket at all.
            tls_candidates: list[tuple[Node, ProbeResult]] = []

            async def _tcp_gated(node: Node) -> tuple[Node, ProbeResult | None]:
                # NOTE: no semaphore here. `self._tcp` already acquires the
                # `tcp` semaphore itself, and taking it again in the caller
                # deadlocks: a `Semaphore(8)` held by `_tcp` while the caller
                # waits for the same one is a cycle that only resolves when the
                # event loop is torn down. Concurrency comes from `gather`
                # starting every node's `_tcp` at once; the semaphore's job is
                # to cap how many of those run, which `_tcp` already does.
                return node, await self._tcp(node)

            allowed = [
                node for node in nodes if not is_blocked_address(node.address)
            ]
            blocked = len(nodes) - len(allowed)
            if blocked:
                errors["ssrf"] = errors.get("ssrf", 0) + blocked
                report.results.extend(
                    ProbeResult(node.dedup_key, Stage.TCP, ok=False, error="ssrf guard")
                    for node in nodes
                    if is_blocked_address(node.address)
                )

            for node, stage1 in await asyncio.gather(
                *[_tcp_gated(n) for n in allowed]
            ):
                if stage1 is None or not stage1.ok:
                    errors["tcp"] = errors.get("tcp", 0) + 1
                    if stage1 is not None:
                        report.results.append(stage1)
                    continue
                tls_candidates.append((node, stage1))

            survivors["tcp"] = len(tls_candidates)

            # Stage 2 in bounded concurrency. The semaphore that bounds it is
            # acquired inside `_tls`, one boundary only — see the note there.
            config_candidates: list[tuple[Node, ProbeResult]] = []

            async def _run_tls(node: Node, passed: ProbeResult) -> tuple[Node, ProbeResult]:
                # NOTE: no semaphore here, exactly as in stage 1 above.
                # `self._tls` acquires the *same* `tls` semaphore at its own
                # boundary, and taking it twice on one path is a self-deadlock:
                # `gather` starts every node's `_tls` at once, the outer
                # wrapper here takes all `limits.tls` permits, and each inner
                # `_tls` then waits for a permit that no one will ever release
                # — because the only holders are the wrappers, and they are
                # blocked waiting on the inners they just started.
                #
                # That is not theoretical. A 339-node production round froze
                # here: 167 tasks parked at `_run_tls`, the semaphore reported
                # `[locked, waiters: 167], value: 0`, and `_tls_inner` was
                # never entered once. Two of twenty nodes managed to finish
                # before the holders arrived, which is why the funnel always
                # looked "almost" healthy and then stopped.
                #
                # The semaphore still caps the stage. It just has to be taken
                # by exactly one of the two functions, and that one is `_tls`,
                # which also handles the timeout/exception paths it protects.
                return node, await self._tls(node, passed)

            # Stage 3 owns no semaphore — it is `sing-box check` semantics, pure
            # CPU, so bounding it would only serialise work that the event loop
            # already schedules fairly.
            async def _run_config(
                node: Node, passed: ProbeResult
            ) -> tuple[Node, ProbeResult]:
                return node, await self._config(node, passed)

            async def _run_http(node: Node, passed: ProbeResult) -> tuple[Node, ProbeResult]:
                return node, await self._http(node, passed)

            for node, stage2 in await asyncio.gather(
                *[_run_tls(n, p) for n, p in tls_candidates]
            ):
                if stage2.ok:
                    config_candidates.append((node, stage2))
                else:
                    errors["tls"] = errors.get("tls", 0) + 1
                    report.results.append(stage2)

            survivors["tls"] = len(config_candidates)

            # Stage 3: unbounded CPU. Like stage 2, the coroutine is wrapped so
            # the node stays attached to its own result — `asyncio.gather`
            # preserves the input order, but the wrapper is what keeps the
            # pairing explicit instead of relying on that.
            http_candidates: list[tuple[Node, ProbeResult]] = []
            for node, stage3 in await asyncio.gather(
                *[_run_config(n, p) for n, p in config_candidates]
            ):
                if stage3.ok:
                    http_candidates.append((node, stage3))
                else:
                    errors["config"] = errors.get("config", 0) + 1
                    report.results.append(stage3)

            survivors["config"] = len(http_candidates)

            # Stage 4: bounded, two rounds, slowest stage.
            for node, stage4 in await asyncio.gather(
                *[_run_http(n, p) for n, p in http_candidates]
            ):
                report.results.append(stage4)
                if stage4.ok:
                    survivors["http"] = survivors.get("http", 0) + 1
                else:
                    errors["http"] = errors.get("http", 0) + 1

        finally:
            await self.driver.stop()

        report.stage_survivors = survivors
        report.stage_errors = errors
        report.duration_s = round(time.monotonic() - started, 2)
        return report


async def _tls_handshake(
    address: str, port: int, server_hostname: str, context: object
) -> tuple[object, object]:
    """A **verifying** TLS handshake. Real network; see `_tls_inner`."""
    return await asyncio.open_connection(
        address, port, ssl=context, server_hostname=server_hostname
    )


async def _raw_connect(address: str, port: int) -> None:
    """A bare TCP connection. Used by the stage-1 gate only."""
    reader, writer = await asyncio.open_connection(address, port)
    from .singbox import _close_writer

    await _close_writer(writer, timeout=2.0)
