"""The sing-box `CoreDriver`: one proxy process per live node, one SOCKS port each.

The `CoreDriver` protocol in `hub.prober` is the seam that makes the whole
funnel testable without a network, and until now nothing implemented it — so
`hub run` could fetch and parse but never *verify*, and published nothing. This
is that implementation.

The shape is chosen for the thing that actually matters when you are probing
third-party endpoints you do not trust: **the host is never configured to route
through them.**

Spawning one `sing-box` process per node would mean up to 336 processes holding
336 configs. Instead one process runs **per live node**, and each `add_node`
spawns one carrying that node's outbound plus a SOCKS inbound on an *ephemeral
loopback port*. The driver then speaks HTTP over `127.0.0.1:<port>`:

    ┌────────────── host ──────────────┐
    │  sing-box (one per live node)    │
    │    inbound: socks://127.0.0.1:P  │   <- bound per node, port chosen
    │    outbound: the node's config   │      by the OS, never routable from
    └──────────────────────────────────┘      outside this host

Because the inbound is loopback-only and the outbound is the node's own
setting, nothing about the host's routing changes: a failure inside sing-box
cannot black-hole the machine it runs on. That is the property that makes it
safe to run this next to other services, and it is why this design was chosen
over a TUN device (which would require exactly the route changes that must not
happen).

Every method that touches a network is a method the caller already had to opt
into: `hub run` only builds a driver on demand, and the pipeline reports
`driver: absent` until one is injected. See `hub.prober.Prober._probe`.

The binary is located, not assumed. `sing-box` is a separate dependency; the
driver says so plainly rather than failing at the first `add_node` with a
message about a file that does not exist.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import json
import os
import shutil
import signal
import socket
import ssl
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from .models import Node
from .renderer import _singbox_outbound

#: `sing-box` looked up on PATH, or `SINGBOX_BIN` pointing at it. An env var
#: because the packaged binary is often installed somewhere not on the service's
#: PATH, and "the unit's PATH" is a thing nobody remembers to set.
BIN_CANDIDATES = ("sing-box",)

#: Seconds allowed for `sing-box check` on one config. `sing-box check` is
#: pure validation — it starts no listener and dials nothing — so this only
#: bounds a config that makes the binary hang rather than reject.
DEFAULT_CHECK_TIMEOUT = 10.0

#: Seconds `add_node` waits for the child to accept before giving up and
#: letting `socks_check` do the honest failing. Generous for a cold start
#: (first exec of the binary, page cache cold), bounded so a config sing-box
#: starts and then wedges cannot hold the round open.
DEFAULT_STARTUP_TIMEOUT = 20.0

#: Seconds allowed for `writer.wait_closed()` — the one wait in this driver
#: that is on the *peer's* cooperation rather than the peer's existence.
#: See `_close_writer`, which is the single place it happens now.
DEFAULT_CLOSE_TIMEOUT = 2.0

#: `prctl(2)` option 1. There is no `ctypes` constant for it, and writing the
#: literal with this name is what keeps line 300 of this file readable.
PR_SET_PDEATHSIG = 1


def _death_signal_preexec() -> None:
    """`preexec_fn` that makes this child die when the process that forked it dies.

    `PR_SET_PDEATHSIG` is the kernel's own answer to "reap orphans": it asks
    for a signal to be delivered to *this* process when its **parent** exits,
    which is exactly the condition under which the driver's own bookkeeping
    (`_procs`, `stop()`, the `finally` in `Prober._probe`) can no longer run.
    Everything this driver does on the orderly path is Python, so every one of
    those paths is a path that does not execute when the driver is SIGKILLed,
    OOM-killed, or crashes out from under the event loop.

    Three properties make it the right tool rather than a watchdog:

    * **it survives the parent dying.** A watchdog is *in* the dying process;
    * **it costs nothing per node.** One syscall in the fork, against a timer
      that would otherwise have to wake `limits.http` times a round;
    * **it is exact.** The kernel compares a parent PID, where a watchdog
      compares a name and can kill a *different* driver's child.

    The re-check after the call is not paranoia. Between `fork` and the signal
    request there is a window in which the parent has already exited and this
    child has not yet been reparented to init. `prctl` alone cannot close it:
    the request is armed against a parent that no longer exists, so the child
    would grow up as the very PPID=1 orphan this is here to prevent. Comparing
    the parent PID *before and after* the call catches that window, and the
    comparison is in the child — the only place that can see it.

    Failures are swallowed rather than raised, because a `preexec_fn` that
    raises does not just lose the guard: `subprocess` turns the exception into
    a `SubprocessError` and the child never starts at all, which would take the
    whole round offline for a missing optional syscall. `_spawn` still records
    the child and `stop()` still reaps it on every orderly path.
    """
    try:
        parent = os.getppid()
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL)
        if os.getppid() != parent:
            os.kill(os.getpid(), signal.SIGKILL)
    except Exception:
        return


def _death_signal_hook() -> Callable[[], None]:
    """A `preexec_fn` for this platform, or a no-op where it cannot be armed.

    On Linux this is `_death_signal_preexec` itself. Everywhere else it is a
    function that does nothing, so `_spawn` passes it unconditionally and the
    platform check lives in exactly one place instead of at both call sites —
    which is how a caller on macOS would otherwise silently lose the guard.
    """
    if sys.platform.startswith("linux"):
        return _death_signal_preexec
    return lambda: None


class SingBoxUnavailable(RuntimeError):
    """No `sing-box` binary. Raised at construction, not at first probe."""


class SingBoxStartError(RuntimeError):
    """A `sing-box` child for one node never became usable.

    Distinct from `SingBoxUnavailable`, which says *no binary* and means the
    whole driver is dead. This says *this node* did not start: either the child
    exited (a config sing-box rejects) or it never bound its port within
    `startup_timeout` (a config that starts and wedges).

    It has to be an exception rather than a return value, because the two
    callers of `add_node` — `Prober._http` and `SpeedStage._add` — already have
    per-node exception paths that record the cause, and both were previously
    fed a *successful* return with a dead port behind it. That combination is
    the worst one available: the funnel then reported "node is dead" (true of
    the node, silent about the driver) and the speed stage reported
    "throughput unknown", while a config the driver could not run was recorded
    nowhere at all. Verified on this host with a live run: 12 of 12 `add_node`
    calls returned without raising, and one node was already unreachable.

    Not a subclass of `SingBoxUnavailable`: a node that fails to start must not
    make the caller conclude the binary is missing and stop the driver for
    every other node in the pool.
    """


async def _close_writer(writer: object, *, timeout: float = DEFAULT_CLOSE_TIMEOUT) -> None:
    """Close a stream writer and *bounded*-wait for the transport to finish.

    The unbounded `await writer.wait_closed()` that this replaces cost a
    production round its entire run. Three nodes in it never completed their
    upstream — one never answered a SOCKS CONNECT, one never finished the TLS
    upgrade — so their `asyncio.wait_for` timers fired correctly and the
    cancellation left the transport **paused with an undrained write buffer**.
    `_SelectorSocketTransport.close` (`asyncio/selector_events.py:867`) then
    only removes the reader: with a non-empty buffer it never schedules
    `connection_lost`, so `StreamReaderProtocol._closed` — the future
    `wait_closed()` awaits (`asyncio/streams.py:364`) — is never resolved. The
    `finally` blocks forever, nothing raises, nothing times out, and the round
    simply stops after its last node.

    Why it is a `finally`, and why that made it invisible: every measurement in
    `_http_over_socks` is wrapped in `asyncio.wait_for`, so the *measurement*
    was correctly bounded and the failure was reported as a dead node — which
    it was. The teardown of the same exchange was not bounded at all, so the
    funnel could finish the measurement and still never return. `py-spy` showed
    the event loop idle at `ep_poll` with three pidfds registered and no
    project frames anywhere: no stack named the loop that was not finishing,
    because the frames doing the waiting were the suspended coroutines', and
    only `asyncio.all_tasks()` with a `cr_await` walk put them on screen.

    Bounded rather than removed: a clean close is still worth waiting a moment
    for, because it releases the loopback port promptly and lets the OS reap
    the child's socket table entry. What it must not be is unbounded, and two
    seconds is generous for a loopback transport whose peer we are about to
    stop talking to anyway.
    """
    with contextlib.suppress(Exception):
        writer.close()
    # `wait_closed` in its own bounded wait, not inside the caller's `finally`
    # scope: a `TimeoutError` here is the *expected* outcome for a wedged peer
    # and must be swallowed, not propagated as a node measurement.
    with contextlib.suppress(Exception):
        await asyncio.wait_for(writer.wait_closed(), timeout=timeout)


def find_binary() -> Optional[str]:
    """Where `sing-box` lives, or `None`. Checked once per process."""
    env = os.environ.get("SINGBOX_BIN", "")
    if env and shutil.which(env):
        return shutil.which(env)
    for name in BIN_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


@dataclass
class _Entry:
    """One node's live state: its tag and the port its SOCKS inbound holds."""

    tag: str
    node: Node
    port: int = 0


@dataclass
class SingBoxDriver:
    """`CoreDriver` over a single `sing-box` process.

    Parameters
    ----------
    binary:
        Path to `sing-box`. `None` means "find it on PATH", which is the normal
        construction; the explicit form exists for tests and for an operator who
        keeps the binary somewhere unusual.
    workdir:
        Where the regenerated config is written. A fresh temp dir by default,
        because the config holds live material (UUIDs, passwords) and a
        predictable path in `/tmp` is a predictable path for anyone else on the
        box to read.
    check_timeout:
        Seconds allowed for `sing-box check` on one config.
    startup_timeout:
        Seconds `add_node` waits for the child to accept connections before
        returning anyway. The wait is what makes the method's contract "the
        proxy is up" rather than "the process was forked"; the bound is what
        stops a config that starts-and-hangs from stalling the round.
    """

    binary: Optional[str] = None
    workdir: Optional[Path] = None
    check_timeout: float = DEFAULT_CHECK_TIMEOUT
    startup_timeout: float = DEFAULT_STARTUP_TIMEOUT
    #: tag -> live entry. `dict` rather than a list: `remove_node` is called by
    #: the funnel for nodes that died mid-round, and a list would make that a
    #: scan plus a splice for each one.
    entries: dict[str, _Entry] = field(default_factory=dict)
    started: bool = False
    _seq: int = 0
    _used_tags: set[str] = field(default_factory=set)
    #: tag -> the child serving that node, and the port it holds.
    #:
    #: This was one field, `_proc`, holding one resident process: the docstring
    #: above still describes that shape, and it is wrong in a way the unit tests
    #: could not see. Every test added one node, so "replace the process on
    #: `add_node`" looked correct; the funnel adds up to `limits.http` nodes
    #: *concurrently* and checks each one afterwards, so the process the last
    #: `add_node` spawned was the only one alive — and every other node's
    #: `socks_check` dialled a loopback port with nothing listening on it.
    #: That is the defect behind 44 real nodes measuring 0 verified.
    #:
    #: Per-tag is the honest shape: `socks_check(tag)` must reach the process
    #: that carries *that* node, and only a 1:1 tag->process mapping makes
    #: that true no matter the order or concurrency of the calls.
    #:
    #: The cost is one short-lived process per live node, bounded from above by
    #: `Prober`'s `http` concurrency (100 by default, env-tunable) because
    #: `_http` calls `add_node` then checks before the next node is added.
    _procs: dict[str, asyncio.subprocess.Process] = field(default_factory=dict)
    _tmp: Optional[tempfile.TemporaryDirectory] = None

    def __post_init__(self) -> None:
        if self.binary is None:
            self.binary = find_binary()
        if not self.binary:
            raise SingBoxUnavailable(
                "sing-box was not found on PATH and SINGBOX_BIN is unset; "
                "install sing-box or set SINGBOX_BIN, then re-run"
            )

    # -- lifecycle ------------------------------------------------------- #

    async def start(self) -> None:
        """Bring the process up. Idempotent, and cheap on the second call."""
        if self.started:
            return
        if self._tmp is None:
            # A real temp dir, mode 0700: it holds live credentials.
            self._tmp = tempfile.TemporaryDirectory(prefix="hub-singbox-")
            os.chmod(self._tmp.name, 0o700)
        if self.workdir is None:
            self.workdir = Path(self._tmp.name)
        # Created, not assumed. An operator (or a test) naming a path that does
        # not exist yet would otherwise get the first write failing as a
        # FileNotFoundError naming a config file, which looks like a config
        # problem rather than the missing-directory problem it is.
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.started = True

    async def stop(self) -> None:
        """Drop the process and every port it holds.

        Best-effort by design: a node that fails mid-round must not turn into a
        driver that can no longer be stopped, and the round's last node dying is
        an ordinary event, not an error worth propagating.
        """
        self.entries.clear()
        self._used_tags.clear()
        self.started = False
        # Kill every child, not "the" child. With per-tag processes the
        # invariant this restores is "no sing-box of ours is left running",
        # which is the one that matters for a service sharing the box.
        await self._kill_all()
        if self._tmp is not None:
            with contextlib.suppress(Exception):
                self._tmp.cleanup()
            self._tmp = None

    # -- registration ---------------------------------------------------- #

    async def add_node(self, node: Node, tag: str) -> None:
        """Register `node`, bind it a loopback SOCKS port, and start sing-box.

        The port is allocated by the OS, which is what makes it safe to run
        more than one driver on one host: two drivers cannot collide, and no
        fixed port is left listening when the round ends.

        One child per live node, so the node this registers is the node whose
        port answers. An earlier revision kept a single resident process and
        replaced it on every `add_node`; that is fine for one node at a time
        and wrong for a funnel that adds up to `limits.http` nodes concurrently
        and checks them afterwards — the last `add_node` won, and every other
        node's check dialled a port nothing was listening on. See `_procs`.

        The caller must `remove_node` (or `stop`) to release the child; a
        registration that is never removed is a process leak, which is why
        `Prober._http` removes in a `finally`.

        Returns only once the child is listening. Without that wait the method
        has a race the test for it caught: `create_subprocess_exec` resolves
        when the child has *exec'd*, which is before its interpreter has run a
        single statement, and the prober calls `socks_check` immediately after
        (`prober.py`'s `add_node` then `_http_round`) — so every node's first
        probe would race the bind and report a healthy node as dead. Waiting
        for the port here, rather than retrying in `socks_check`, keeps the
        "was this node reachable" question a measurement of the node instead of
        a measurement of the driver's own startup timing.
        """
        if not self.started:
            await self.start()
        port = self._free_port()
        self.entries[tag] = _Entry(tag=tag, node=node, port=port)
        try:
            await self._spawn(tag)
            await self._await_listening(tag, port)
        except Exception:
            # The entry has to go: it holds a port nothing is listening on, and
            # `speed_read`'s only guard is `self.entries.get(tag)`, so a stale
            # one turns "this node failed to start" into a dial that gets
            # `ConnectionRefused` — the same error a *dead* node produces. Two
            # different causes, one observable, and the callers cannot tell them
            # apart.
            #
            # `remove_node` rather than `entries.pop`: it also reaps the child,
            # which the caller-died path has already attempted but the
            # hung-config path has not.
            with contextlib.suppress(Exception):
                await self.remove_node(tag)
            raise

    async def remove_node(self, tag: str) -> None:
        """Drop a node and reap the child that served it.

        Pop before killing, so a concurrent `add_node` for the same tag (the
        funnel does not do this, but a driver must be safe for it) starts a
        fresh child instead of having this removal reap it.
        """
        self.entries.pop(tag, None)
        proc = self._procs.pop(tag, None)
        if proc is None or proc.returncode is not None:
            return
        # Killed, not asked to stop: sing-box has no signal that means "close
        # this inbound and exit cleanly, quickly", and this is a loopback child
        # of ours holding no state worth preserving.
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        # Reaped *here* rather than left for the transport, because a
        # killed-but-unreaped child keeps its listening socket in the kernel's
        # table until the parent exits — which is how a driver that appears to
        # stop cleanly still holds ports.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=5.0)

    # -- the checks the funnel runs -------------------------------------- #

    async def socks_check(self, tag: str, *, timeout: float = 5.0) -> tuple[bool, float]:
        """HTTP over the node's own SOCKS port. `(ok, seconds)`.

        The request goes to a **fixed, inert** target rather than to the node
        itself: the point of the stage is "does a connection through this node
        carry bytes", not "does this node serve anything interesting". A node
        that cannot relay to one host cannot relay at all, and asking it to
        fetch something real would be sending the host's traffic through it.
        """
        entry = self.entries.get(tag)
        if entry is None or not entry.port:
            return False, 0.0
        started = asyncio.get_running_loop().time()
        ok = await self._socks_roundtrip(entry.port, timeout=timeout)
        return ok, (asyncio.get_running_loop().time() - started)

    async def config_ok(self, node: Node) -> bool:
        """`sing-box check` on this node alone: would the config even start?

        Runs the binary as a subprocess against a temporary config, and never
        starts the proxy — `check` is a pure validation mode, so this is where
        a malformed outbound is rejected without a socket ever opening.
        """
        config = self._config_for(node, tag="check", port=self._free_port())
        path = await self._write_temp(config)
        try:
            proc = await asyncio.create_subprocess_exec(
                self.binary,
                "check",
                "--config",
                str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=self.check_timeout)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                return False
            return proc.returncode == 0
        except (OSError, ValueError):
            # A config we could not even serialise is a config that would not
            # start, which is exactly what `False` means here.
            return False
        finally:
            with contextlib.suppress(OSError):
                path.unlink()

    async def trace(self, tag: str, *, timeout: float = 5.0) -> Optional[dict]:
        """`loc`/`ip`/`colo` from `cdn-cgi/trace` over the node's SOCKS port.

        Optional in the protocol, and the comment there explains why: a driver
        without it still probes. It is implemented because it is what makes the
        landing page's country groups true rather than decorative — the exit
        country is a *measurement*, and the label on a share URI is a claim.

        One request, so the driver's own network use is one small GET per node,
        sent through the node being measured.
        """
        entry = self.entries.get(tag)
        if entry is None or not entry.port:
            return None
        return await self._trace_over(entry.port, timeout=timeout)

    async def speed_read(
        self, tag: str, url: str, timeout: float
    ) -> AsyncIterator[bytes]:
        """Stream bytes from `url` over the node's own SOCKS port.

        A generator, not a function returning a blob: the byte-bounded safety
        argument in `hub.speedtest` rests on the consumer being able to stop
        asking mid-transfer, and a driver that buffered 4 MiB before yielding
        once could not be cut off.
        """
        entry = self.entries.get(tag)
        if entry is None or not entry.port:
            return
        reader = writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", entry.port), timeout=timeout
            )
            await asyncio.wait_for(_socks_handshake(reader, writer), timeout=timeout)
            target = _split_url(url)
            if target is None:
                return
            host, port, path = target
            await _socks_connect(reader, writer, host, port)
            # TLS for the same reason as the trace: the speed endpoint is
            # `https://speed.cloudflare.com/__down`, and a plain request to its
            # 443 gets the `400 ... HTTPS port` page instead of bytes. That
            # page is small and fast, so without this a dead node would
            # measure as a *quick* one rather than a failed one.
            if url.lower().startswith("https"):
                context = ssl.create_default_context()
                await asyncio.wait_for(
                    writer.start_tls(context, server_hostname=host),
                    timeout=timeout,
                )
            request = (
                f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                "User-Agent: hub-speedcheck/1\r\nConnection: close\r\n\r\n"
            )
            writer.write(request.encode())
            await writer.drain()
            # Read the response *head* before yielding any bytes. The consumer
            # (`hub.speedtest.SpeedChecker`) counts every byte it receives as
            # throughput, so a raw stream whose first chunk is
            # `HTTP/1.1 400 Bad Request` plus a 250-byte error page would be
            # recorded as a 250-byte transfer that succeeded — a dead-node
            # error message turned into a positive measurement.
            #
            # `_read_head`, not `_read_response`: that one reads to EOF, which
            # costs the whole window rather than a few bytes. It returns the
            # same total, but only after the peer closes, so a live slow node
            # measures `bytes_moved = 0` — see `_read_head`'s docstring for the
            # measured comparison and for the earlier, incorrect account of
            # what this bug was.
            head = await asyncio.wait_for(_read_head(reader), timeout=timeout)
            if head is None or not _is_ok_status(head[0]):
                return
            if head[1]:
                yield head[1]
            while True:
                chunk = await asyncio.wait_for(reader.read(65536), timeout=timeout)
                if not chunk:
                    break
                yield chunk
        finally:
            await _close_writer(writer)

    # -- internals ------------------------------------------------------- #

    @staticmethod
    def _free_port() -> int:
        """An ephemeral loopback port, allocated and immediately released.

        The bind-and-close makes the OS choose a free port; sing-box then binds
        it again a moment later. The window is the standard TOCTOU race every
        ephemeral-port allocator has, and it is on loopback inside one host, so
        the worst case is a failed bind the driver reports as a failed check.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    def _config_for(self, node: Node, *, tag: str, port: int) -> dict:
        """A complete sing-box config: the node outbound + one SOCKS inbound.

        Reuses `renderer._singbox_outbound` rather than building the outbound a
        second time. Seven protocols are serialised there and the quirks are
        already encoded (REALITY's `public_key`/`short_id`, hysteria2's obfs,
        TUIC's congestion control); a second copy in this file would be a
        second place for them to drift, and a node that renders for a client
        but not for the prober is a node nobody can verify.
        """
        outbound = _singbox_outbound(node, self._seq, self._used_tags)
        outbound["tag"] = tag
        return {
            "log": {"level": "error"},
            "outbounds": [outbound],
            "inbounds": [
                {
                    "type": "socks",
                    "tag": "in",
                    "listen": "127.0.0.1",
                    "listen_port": port,
                }
            ],
        }

    async def _write_config(self, tag: str) -> Path:
        assert self.workdir is not None
        entry = self.entries[tag]
        config = self._config_for(entry.node, tag=tag, port=entry.port)
        path = self.workdir / f"{tag}.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    async def _spawn(self, tag: str) -> None:
        """Start `sing-box run -c <tag>.json` for one node.

        Called with no other child's state in scope: each call spawns exactly
        one child and stores it under `tag`. That is what makes `add_node`
        safe to await concurrently — the old `_respawn` killed a shared `_proc`
        first, which is the orphan factory described in `_procs`.

        The config is written before the spawn so a config that cannot be
        serialised fails here, with the file's own error, rather than inside
        sing-box as a parse failure that names no node.
        """
        assert self.workdir is not None
        path = await self._write_config(tag)
        assert self.binary is not None
        try:
            proc = await asyncio.create_subprocess_exec(
                self.binary,
                "run",
                "-c",
                str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                # The child dies with the driver, so a driver that dies without
                # running `stop()` leaves nothing behind. `--allow-network` runs
                # are launched in a namespace and can be killed at any point,
                # and every orderly reap in this file is a path that does not
                # execute when the process is SIGKILLed or OOM-killed.
                preexec_fn=_death_signal_hook(),
            )
        except OSError as exc:
            # The binary was found at construction and is gone now, or is not
            # executable. Either way there is no proxy this round, and the funnel
            # reports every node as unverified rather than crashing the run.
            self._procs.pop(tag, None)
            raise SingBoxUnavailable(
                f"could not start {self.binary!r}: {exc}"
            ) from exc
        self._procs[tag] = proc

    async def _kill_one(self, tag: str) -> None:
        """Stop and reap one node's child, if any."""
        proc = self._procs.pop(tag, None)
        if proc is None or proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=5.0)

    async def _kill_all(self) -> None:
        """Stop and reap every child. The `stop()` invariant.

        Sequentially rather than with `asyncio.gather`: each reap is bounded at
        5 s and a child we just SIGKILLed has already released its file
        descriptors, so in practice this is a handful of microseconds each.
        Gaining microseconds in exchange for a burst of concurrent `wait()`
        calls is a trade not worth making on a box running other work.
        """
        for tag in list(self._procs):
            await self._kill_one(tag)

    async def _await_listening(self, tag: str, port: int) -> None:
        """Wait until `127.0.0.1:port` accepts, or the child has already died.

        Bounded by `startup_timeout`, and short-circuited by the child exiting:
        a node whose config sing-box rejects on startup would otherwise cost
        the full timeout every time, and a whole round of those is a round that
        takes hours instead of minutes.

        The poll is a TCP connect to a loopback address, so it sends nothing
        and learns only "is this port open". It is the same probe
        `socks_check` starts with, done here so the caller's first real check
        measures the node rather than a fork that had not finished starting.

        Looks up this tag's child by name on every iteration rather than
        holding a reference: with one child per tag, a concurrent
        `remove_node` is entitled to reap and pop it while this polls, and a
        held reference would then poll a port whose owner is already gone.
        """
        deadline = asyncio.get_running_loop().time() + self.startup_timeout
        delay = 0.001  # 1 ms to start; doubling below.
        while True:
            proc = self._procs.get(tag)
            if proc is not None and proc.returncode is not None:
                # Already exited. Reap it so the zombie does not outlive the
                # node, and report the node as unstartable rather than letting
                # the port poll time out.
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                self._procs.pop(tag, None)
                # This is a fact, not a guess: the child we spawned for this tag
                # is gone, so nothing will ever listen on this port. Returning
                # here silently — which is what this did — left `add_node`
                # reporting success for a node with a closed port, because the
                # entry was written *before* the spawn. The caller then dialled
                # and got `ConnectionRefused`, which a funnel reads as "node is
                # dead" and a speed stage reads as "throughput unknown", while
                # the true cause (the config did not start) was recorded nowhere.
                # Raising puts the cause where the two callers already handle
                # exceptions, and the port is closed so there is nothing to leak.
                raise SingBoxStartError(
                    f"sing-box exited with code {proc.returncode} for tag {tag}"
                )
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", port), timeout=delay
                )
                await _close_writer(writer, timeout=0.5)
                return
            except (ConnectionRefusedError, OSError):
                pass  # not up yet; keep polling until the deadline
            if asyncio.get_running_loop().time() >= deadline:
                # The other silent path: a config that starts and hangs. Same
                # asymmetry — the child is alive but no proxy is up, and the
                # caller has no way to tell that from a node that is merely
                # slow. Raising names it.
                raise SingBoxStartError(
                    f"sing-box never listened on 127.0.0.1:{port} for tag {tag}"
                    f" within {self.startup_timeout:g}s"
                )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 0.05)  # cap the poll at 20 Hz

    async def _write_temp(self, config: dict) -> Path:
        assert self.workdir is not None
        fd, name = tempfile.mkstemp(dir=str(self.workdir), suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(config, fh)
        return Path(name)

    async def _socks_roundtrip(self, port: int, *, timeout: float) -> bool:
        """One HTTP request over a SOCKS port. `False` on anything going wrong.

        TLS first, and the **status code** is the verdict — not "a line
        starting with `HTTP/`". Those are different questions, and conflating
        them is how 44 nodes got published as healthy: Cloudflare answers a
        plain `HEAD /cdn-cgi/trace` on port 443 with `400 Bad Request`, which
        does start with `HTTP/`, so the old check called an exchange it had
        refused a success. A 400 is a complete, well-formed HTTP response, so
        only the code says whether the node carried the request.

        A `GET`, not a `HEAD` — and this is not a preference. Cloudflare
        answers `HEAD /cdn-cgi/trace` with `404 Not Found` *on its own
        origin*, verifiable without any proxy in the path
        (`curl -I https://cloudflare.com/cdn-cgi/trace`), so a HEAD probe
        reports every node as dead no matter how healthy it is. One production
        round measured 0 of 44 nodes that way.

        The scheme is `https`, because Cloudflare returns `301 Moved
        Permanently` for `http://1.1.1.1/cdn-cgi/trace` — the measurement lives
        behind the redirect, and a plain-HTTP probe reads the redirect page and
        no data. `trace` and `speed_read` needed the same change; all three now
        share `_http_over_socks` rather than each carrying its own copy.
        """
        entry = await self._http_over_socks(port, _PROBE_HOST, _PROBE_PATH,
                                            timeout=timeout, method="GET")
        return entry is not None and _is_ok_status(entry[0])

    async def _trace_over(self, port: int, *, timeout: float) -> Optional[dict]:
        """`cdn-cgi/trace` as a dict, or `None` when it could not be read.

        TLS and a `GET`, for the same reason as `_socks_roundtrip`: the body is
        what carries `loc`, and the body only exists over HTTPS.
        """
        got = await self._http_over_socks(port, _PROBE_HOST, _PROBE_PATH,
                                          timeout=timeout, method="GET")
        if got is None or not _is_ok_status(got[0]):
            return None
        return _parse_trace(got[1])

    async def _http_over_socks(
        self, port: int, host: str, path: str, *, timeout: float, method: str = "GET"
    ) -> Optional[tuple[str, bytes]]:
        """`(status_line, body)` from `https://{host}/{path}` over a SOCKS port.

        One implementation for every HTTP measurement the driver makes, because
        the alternative was three: they agreed on TLS, then drifted on it, and
        the version that drifted was the one reading the body nobody could read.

        `None` on any failure — a transport error, a TLS failure, or a
        connection the node refused. Callers decide what "no answer" means;
        this only reports what the node actually said.
        """
        reader = writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), timeout=timeout
            )
            await asyncio.wait_for(_socks_handshake(reader, writer), timeout=timeout)
            await asyncio.wait_for(
                _socks_connect(reader, writer, host, 443), timeout=timeout
            )
            # A verifying context with the SNI set to the host we asked for.
            # The node is the thing under test, so a certificate it cannot
            # produce is a failure of the node, not something to wave through.
            context = ssl.create_default_context()
            await asyncio.wait_for(
                writer.start_tls(context, server_hostname=host), timeout=timeout
            )
            request = (
                f"{method} /{path} HTTP/1.1\r\nHost: {host}\r\n"
                "User-Agent: hub-prober/1\r\nConnection: close\r\n\r\n"
            )
            writer.write(request.encode())
            await asyncio.wait_for(writer.drain(), timeout=timeout)
            head = await asyncio.wait_for(_read_response(reader), timeout=timeout)
            if head is None:
                return None
            status_line, body = head
            return status_line, body
        except (OSError, ssl.SSLError, asyncio.TimeoutError):
            return None
        finally:
            # Bounded — see `_close_writer`. This one was the production hang.
            if writer is not None:
                await _close_writer(writer, timeout=timeout)


#: The host a `socks_check` asks the node to reach. Cloudflare's own anycast,
#: chosen because it is the host the *measurement* needs anyway and because
#: asking a third-party node to fetch any operator-chosen URL would route that
#: operator's traffic through it.
_PROBE_HOST = "cloudflare.com"
_PROBE_PATH = "cdn-cgi/trace"


# --------------------------------------------------------------------------- #
# SOCKS5, written out rather than imported
# --------------------------------------------------------------------------- #


async def _socks_handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """RFC 1928 greeting, no authentication.

    sing-box's SOCKS inbound accepts no-auth by default, and the driver's
    inbound is on loopback, so there is nothing to authenticate against: the
    only client is this process.
    """
    writer.write(b"\x05\x01\x00")
    await writer.drain()
    reply = await reader.readexactly(2)
    if reply[0] != 0x05 or reply[1] != 0x00:
        raise OSError(f"socks handshake refused: {reply!r}")


async def _socks_connect(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, host: str, port: int
) -> None:
    """CONNECT to `host:port` and confirm the reply.

    A domain name is sent (ATYP 0x03) rather than resolved here, so the node's
    own resolver answers — which is part of what is being measured. A node
    whose DNS is broken fails here rather than at the HTTP stage, which is a
    different and more honest failure.
    """
    encoded = host.encode()
    if len(encoded) > 255:
        raise OSError("hostname too long for SOCKS5")
    writer.write(b"\x05\x01\x00\x03" + bytes([len(encoded)]) + encoded + port.to_bytes(2, "big"))
    await writer.drain()
    head = await reader.readexactly(4)
    if head[1] != 0x00:
        raise OSError(f"socks connect failed: code {head[1]}")
    # Skip the bound address, whose length depends on its type. The reply is
    # acknowledged, not used: the client is already connected to the target.
    atyp = head[3]
    if atyp == 0x01:
        await reader.readexactly(4)
    elif atyp == 0x04:
        await reader.readexactly(16)
    elif atyp == 0x03:
        length = (await reader.readexactly(1))[0]
        await reader.readexactly(length)
    await reader.readexactly(2)


async def _read_head(reader: asyncio.StreamReader) -> Optional[tuple[str, bytes]]:
    """`(status_line, body_so_far)` — the response head only, no EOF wait.

    The helper `_speed_read` needs and `_read_response` could not give. The
    difference is one word: this stops at the header terminator, that one reads
    until the peer closes.

    **What this fixes, stated as it was measured.** An earlier version of this
    docstring claimed the old code lost the body entirely — "`moved == 0`,
    nothing left to yield". That was wrong, and it was tested and refuted: with
    a body that arrives complete and then closes, the pre-fix code delivered
    *every byte* (262144 in one chunk, where this helper yields five) and
    measured identically. `_read_response` returns the whole body as
    `body_so_far`, and the old `speed_read` yielded it.

    What it actually cost was the **first byte**, and with it the window. The
    old head read waited for EOF, so a live-but-slow node — the common case —
    handed the consumer nothing until the connection closed. Measured against a
    peer that answered `200 OK` with `Content-Length: 4194304`, trickled 3 MiB
    and then held the socket open:

        pre-fix (`_read_response`):  timeout, bytes_moved = 0, measured = False
        this helper:                 first byte at 0.001 s, 1048576 bytes,
                                     bps = 6553600, window closed on the
                                     1 MiB volume bound rather than the 12 s
                                     clock

    `SpeedChecker` closes its window at `MIN_WINDOW_BYTES` or `timeout_s`, and
    stops asking when the consumer breaks — which only helps if the bytes are
    already flowing. So this is a real defect: a live-but-slow node measured
    `bytes_moved = 0` and was recorded under `speed.fail:no bytes`, the bucket
    named for a dead node.

    **It was not, however, the cause of the live zeros.** That was the tempting
    conclusion and it is wrong: a full live run *with this fix in place*
    (`run-20261015T215128Z`) still reported `speed.measured: 0` and
    `speed.fail:no bytes: 25` — the top-N cap, i.e. every attempted node. The
    same run's HTTP stage verified 170 nodes through the identical SOCKS
    plumbing, so the nodes were fine and the transfer was not. The actual cause
    is in `_split_url`, which dropped the `?bytes=` query and asked the
    endpoint for an unbounded transfer; this helper only governs how the answer
    is read once it arrives.

    Recorded this way on purpose. A docstring that claims a fix which a later
    measurement contradicts is worse than no docstring: it sends the next
    reader past the bug. The two are independent — this one is about *reading*
    the response, `_split_url` is about *asking* — and both had to be fixed for
    `speed.measured` to move off zero.

    The bytes that arrive in the same read as the terminator are returned as
    `body_so_far` rather than dropped, because they are real payload and
    `read(65536)` does not stop at a boundary.
    """
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = await reader.read(65536)
        if not chunk:
            break  # peer closed; whatever headers arrived are what there is
        buffer += chunk
        # The head cannot be large, and an unbounded read here is the same
        # unbounded wait this whole file was rewritten to remove.
        if len(buffer) > 65536:
            return None
    if not buffer:
        return None
    head, _, body = buffer.partition(b"\r\n\r\n")
    line = head.split(b"\r\n", 1)[0]
    if not line:
        return None
    return line.decode("latin-1"), body


async def _read_response(reader: asyncio.StreamReader) -> Optional[tuple[str, bytes]]:
    """`(status_line, body)`, or `None` if no status line arrived.

    Reads to the close of a `Connection: close` response and splits the first
    line off. The split is by the header terminator rather than by a fixed
    offset, because a server may send any number of headers — including a
    `Location:` on a redirect — before the body starts.

    Used where the whole body is the answer (`cdn-cgi/trace`). **Not** usable
    where the body is the measurement: see `_read_head`, whose docstring is the
    incident report for that case.
    """
    raw = await _read_body(reader)
    if not raw:
        return None
    head, _, body = raw.partition(b"\r\n\r\n")
    line = head.split(b"\r\n", 1)[0]
    if not line:
        return None
    return line.decode("latin-1"), body


def _is_ok_status(status_line: str) -> bool:
    """`True` only for a 2xx status line.

    The whole *point* of this function is that a response can be well-formed
    and still be a refusal. `400 Bad Request` and `301 Moved Permanently` both
    begin a valid HTTP response; the old check accepted anything beginning
    with `HTTP/`, so a node that was told "no" was recorded as healthy and the
    country that was supposed to come from the body was empty forever.

    A status line that cannot be parsed at all is a refusal too: guessing
    "success" for an unreadable answer is how an unmeasurable stage reports
    full marks.
    """
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        return False
    return 200 <= int(parts[1]) < 300


async def _read_body(reader: asyncio.StreamReader) -> bytes:
    """Everything after a chunked-free `Connection: close` response ends."""
    chunks: list[bytes] = []
    while True:
        chunk = await reader.read(65536)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_trace(body: bytes) -> dict:
    """The flat `key=value` lines `cdn-cgi/trace` answers with.

    `_http`/`_speed` split it, so the parse is on the whole blob rather than on
    the response's first line: the shape is one `key=value` per line with no
    header framing to strip, and the caller wants `loc`, not a status code.
    """
    text = body.decode("utf-8", errors="replace")
    start = text.find("ip=")
    if start < 0:
        return {}
    out: dict[str, str] = {}
    for line in text[start:].splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip():
            out[key.strip()] = value.strip()
    return out


def _split_url(url: str) -> Optional[tuple[str, int, str]]:
    """`(host, port, request_target)` for the request line.

    The **query string must survive**, and this is not a detail. `urlsplit`
    splits `?bytes=262144` into `.query`, never into `.path`, so returning
    `parts.path` alone turned every request for
    `https://speed.cloudflare.com/__down?bytes=262144` into
    `GET /__down HTTP/1.1` — the size parameter silently gone.

    Measured against the real endpoint, because the failure mode is not obvious:

        GET /__down?bytes=262144  ->  200 OK, Content-Length: 262144
        GET /__down               ->  200 OK, Content-Length: 0

    A **zero-length 200**, not a 404 and not an error. So `_is_ok_status` passed,
    the body was empty, the consumer counted `moved == 0`, and the run report
    filed it under `speed.fail:no bytes` — the bucket named for a dead node —
    for all 25 top-N nodes, with `speed.measured: 0` behind it. Every layer was
    behaving correctly on the answer it was given; the request was wrong.

    Why four tests did not catch it: they asserted the *path* (`/cdn-cgi/trace`)
    and the speed test asserted `b"GET /__down" in request` — and `/__down` is a
    substring of `/__down?bytes=4096`, so that assertion passes whether or not
    the query is present. A substring check cannot pin a suffix.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if not parts.hostname:
        return None
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"
    return parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), target
