"""The sing-box `CoreDriver`, tested without sing-box and without a network.

`hub.singbox` is the one module whose whole job is touching a network through a
third-party binary, so the obvious way to test it — run it — is the one way this
project must not. Two constraints from the brief shape every test here:

* **no route changes and no routable listener** on the live host network;
* **the host's traffic must not go through any node.**

Both are satisfied by never dialling anything but `127.0.0.1`. Where a socket is
needed, it is a loopback listener on an ephemeral port that this file starts and
stops itself, and where the module under test *would* open an outbound
connection, the test drives the seam one level down — the SOCKS5 client against
a scripted server — rather than standing up a real proxy.

The parts that are pure logic get real assertions on real outputs:

* **config generation** is asserted by parsing the JSON the driver writes and
  checking the outbound the renderer would produce, and the loopback-only
  inbound that is the safety property;
* **process lifecycle** is asserted against a stand-in `sing-box` — a script
  that listens on the port the config names — which is what proves the driver
  actually starts, and reaps, a child rather than only writing files;
* **the SOCKS5 conversation** is asserted against a server scripted to answer
  RFC 1928, which is what proves the driver speaks the protocol rather than
  merely opening a socket.

A real `sing-box` binary is *used* when one is present, in exactly one test, and
that test only runs `check` — a pure validation mode that opens no listener and
no outbound connection.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import signal
import socket
import ssl
import subprocess
import tempfile
import stat
import sys
import time
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hub import cli, singbox  # noqa: E402
from hub.cli import _driver_factory  # noqa: E402
from hub.singbox import (  # noqa: E402
    SingBoxDriver,
    SingBoxStartError,
    SingBoxUnavailable,
    _Entry,
    _parse_trace,
    _socks_connect,
    _socks_handshake,
    _split_url,
    find_binary,
)

#: A stand-in `sing-box` that binds the config's inbound port and idles. It is
#: a real child process, so `add_node`'s spawn is genuinely exercised, but it
#: never makes an outbound connection: nothing it does reaches the network.
FAKE_CORE = """#!/usr/bin/env python3
import json, socket, sys, time
config = json.load(open(sys.argv[sys.argv.index("-c") + 1]))
port = config["inbounds"][0]["listen_port"]
# `--die` exits before binding anything, standing in for a config sing-box
# rejects: the child is gone before the driver's first poll, which is the
# "already exited" path of `_await_listening`.
if "--die" in sys.argv:
    sys.stderr.write("exiting before listen\\n")
    sys.exit(3)
# `--no-listen` sleeps forever without binding, standing in for a config that
# starts and wedges: the child is alive and no port is ever open. The `--die`
# case short-circuits on `returncode`, so a test that only used it would pass
# against an implementation that had kept half the fix.
if "--no-listen" in sys.argv:
    time.sleep(600.0)
    sys.exit(0)
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", port))
# Backlog 16, not 1. `_await_listening` polls this port with a *TCP connect*
# and never accepts, so a listen(1) socket consumes its only backlog slot and
# then drops SYNs — which makes the next `connect()` hang for seconds instead
# of failing, and a test that opens several ports in one round times out while
# the driver is behaving correctly.
s.listen(16)
sys.stderr.write("listening\\n"); sys.stderr.flush()
# `--linger` is honoured if a caller passes it and ignored otherwise. The
# driver never does: it execs exactly `run -c <path>`, which is the real
# sing-box's contract, so a stand-in that *required* an invented flag would
# exit 1 under the actual invocation and the test would read that as "the
# listener never came up" instead of "this fixture was wrong".
linger = 600.0
if "--linger" in sys.argv:
    linger = float(sys.argv[sys.argv.index("--linger") + 1])
time.sleep(linger)
"""


@pytest.fixture()
def workdir(tmp_path):
    return tmp_path


def _fake_binary(
    tmp_path: Path, linger: float = 30.0, extra: str = ""
) -> str:
    """Write the stand-in core and return its path.

    `extra` is appended to *argv* by the driver's invocation, not by the script:
    these lines have to run before `FAKE_CORE` reads `sys.argv`, so they go on
    the first line, not the last. The previous shape appended them after the
    core's `time.sleep(linger)` — text at a point control flow never reaches —
    which made every flag passed this way silently inert, and a test written
    against it would then have been asserting against the *idle* path while
    looking like it was asserting against `--die`.

    An env var would be the tidier seam, but the driver does not set one, so a
    fixture that read it would be testing a different process than production
    runs. Pre-seeding argv keeps the invocation exactly `run -c <path>`.
    """
    path = tmp_path / "fake-sing-box"
    # Both the linger and the failure-mode flags are pre-seeded into `sys.argv`
    # *before* the core's first statement, because the core reads argv at import
    # time and then sleeps. The previous shape appended `--linger 30` after the
    # core's `time.sleep(...)`, which is text control flow never reaches, so the
    # core always ran on its 600 s default — harmless for the tests that only
    # check "is the port open", and silently fatal for any test that needs a
    # child to exit or to stay alive without binding.
    #
    # Inserted on the line *after* the core's `import json, socket, sys, time`,
    # not before it: the prefix uses `sys`, and Python executes statements in
    # file order, so a prefix on line 2 dies with `NameError: name 'sys' is not
    # defined` — exit code 1, which is the wrong failure mode for a fixture that
    # is trying to produce exit code 3. Split the shebang and the imports out,
    # insert, and put the rest back.
    lines = FAKE_CORE.split("\n")
    assert lines[0].startswith("#!"), lines[0]
    assert lines[1].startswith("import "), lines[1]
    prefix = f"sys.argv.append('--linger'); sys.argv.append('{linger}'); "
    if extra:
        for flag in extra.split():
            prefix += f"sys.argv.append({flag!r}); "
    path.write_text(
        "\n".join([lines[0], lines[1], prefix, *lines[2:]]),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)



def _trojan(address: str = "de.example.com"):
    from hub.models import Node, Protocol, Security, Transport, TransportSettings, TLS

    return Node(
        protocol=Protocol.TROJAN,
        address=address,
        port=443,
        password="secret",
        transport=Transport.TCP,
        transport_settings=TransportSettings(kind=Transport.TCP),
        security=Security.TLS,
        tls=TLS(sni=address),
        country="DE",
        source="fixture",
    )


def _reality():
    from hub.models import Node, Protocol, Security, Transport, TransportSettings, TLS

    return Node(
        protocol=Protocol.VLESS,
        address="nl.example.com",
        port=443,
        uuid="11111111-2222-3333-4444-555555555555",
        transport=Transport.TCP,
        transport_settings=TransportSettings(kind=Transport.TCP),
        security=Security.REALITY,
        # A genuine x25519 public key, produced by `sing-box generate
        # reality-keypair`. The stand-in never parsed it, so `TESTPUBKEY`
        # looked fine; the real binary rejects it with `invalid public_key`.
        tls=TLS(sni="www.microsoft.com", fingerprint="chrome",
                 public_key="kScLZUsi7RrRNpGSL023RjG05tzdegft4kMlij4C5X0", short_id="ab"),
        flow="xtls-rprx-vision",
        country="NL",
        source="fixture",
    )


def _ss():
    from hub.models import Node, Protocol, Security, Transport, TransportSettings, TLS

    # A *real* SS-2022 password: base64 of exactly the key length the method
    # demands. `2022-blake3-aes-128-gcm` is 16 bytes, so the fixture carries
    # 24 base64 characters — the earlier 6-character `"secret"` was a string
    # no real 2022 server ever issues, and the stand-in binary accepted it
    # because a stand-in validates nothing. Only the real `sing-box check`
    # caught it (`bad key length, required 16, got 6`), which is precisely the
    # bug this fixture now prevents: a shape that passes the fakes and fails
    # the world.
    password = base64.b64encode(b"0123456789abcdef").decode()
    assert len(base64.b64decode(password)) == 16, password

    return Node(
        protocol=Protocol.SHADOWSOCKS,
        address="se.example.com",
        port=8388,
        method="2022-blake3-aes-128-gcm",
        password=password,
        transport=Transport.TCP,
        transport_settings=TransportSettings(kind=Transport.TCP),
        security=Security.NONE,
        tls=TLS(),
        country="SE",
        source="fixture",
    )


# --------------------------------------------------------------------------- #
# finding the binary
# --------------------------------------------------------------------------- #


def test_no_binary_means_a_named_error_not_a_crash(tmp_path, monkeypatch):
    """Absence has to be diagnosable at construction, not at the first probe.

    The failure this replaces is a `FileNotFoundError` from
    `create_subprocess_exec` inside `add_node`, three hundred nodes into a
    round, with nothing in the message naming `sing-box` or `SINGBOX_BIN`.
    """
    monkeypatch.delenv("SINGBOX_BIN", raising=False)
    monkeypatch.setattr(singbox.shutil, "which", lambda _n: None)
    with pytest.raises(SingBoxUnavailable) as caught:
        SingBoxDriver()
    assert "sing-box" in str(caught.value), str(caught.value)
    assert "SINGBOX_BIN" in str(caught.value), str(caught.value)


def test_singbox_bin_overrides_the_path_lookup(tmp_path, monkeypatch):
    """An operator who keeps the binary elsewhere gets honoured.

    The env var is checked *before* PATH, so a stale `sing-box` earlier on the
    path cannot win.
    """
    binary = _fake_binary(tmp_path)

    # A `which` that answers only for names that are really there. Patching it
    # to return a path for *every* name is the tempting shortcut and it is
    # wrong: it makes the candidate loop find a binary that does not exist, so
    # the assertion below would pass even if the env var were never consulted
    # -- both branches would return the same nonexistent string.
    def which(name):
        if name == binary:
            return binary
        if name in singbox.BIN_CANDIDATES:
            return "/nonexistent/sing-box"  # a stale one, earlier on the path
        return None

    monkeypatch.setattr(singbox.shutil, "which", which)
    monkeypatch.setenv("SINGBOX_BIN", binary)
    assert find_binary() == binary
    assert SingBoxDriver(binary=binary).binary == binary


# --------------------------------------------------------------------------- #
# the safety property: loopback only
# --------------------------------------------------------------------------- #


async def test_the_inbound_is_loopback_only_and_on_an_ephemeral_port(workdir, tmp_path):
    """The property the whole design rests on.

    Asserted from the written config rather than from the source, because the
    observable that matters is what appears in the file sing-box reads:
    `listen: 127.0.0.1` and a port the OS chose. A config listening on `0.0.0.0`
    is a SOCKS proxy published to the host's network, and a fixed port is a
    collision with whatever already holds it.
    """
    driver = SingBoxDriver(binary=_fake_binary(tmp_path), workdir=workdir)
    await driver.start()
    try:
        await driver.add_node(_trojan(), "n000-trojan-xx")
        config = json.loads((workdir / "n000-trojan-xx.json").read_text())

        inbound = config["inbounds"][0]
        assert inbound["listen"] == "127.0.0.1", inbound
        assert inbound["type"] == "socks", inbound
        # `> 1024` because a privileged port is a port that needs root, and a
        # driver that requires root is a driver that does not run under the
        # service's `User=hub`.
        assert inbound["listen_port"] > 1024, inbound
        # The outbound points at the node, so the *host* is never in the path.
        outbound = config["outbounds"][0]
        assert outbound["server"] == "de.example.com", outbound
        assert outbound["tag"] == "n000-trojan-xx", outbound
    finally:
        await driver.stop()


async def test_two_drivers_get_different_ports(workdir, tmp_path):
    """Ephemeral allocation is what makes concurrent rounds safe.

    Two drivers on one host must not be able to bind the same port. The OS
    chooses, so they cannot.
    """
    a = SingBoxDriver(binary=_fake_binary(tmp_path), workdir=workdir / "a")
    b = SingBoxDriver(binary=_fake_binary(tmp_path), workdir=workdir / "b")
    await a.start()
    await b.start()
    try:
        await a.add_node(_trojan(), "t")
        await b.add_node(_trojan(), "t")
        pa = json.loads((workdir / "a" / "t.json").read_text())["inbounds"][0]["listen_port"]
        pb = json.loads((workdir / "b" / "t.json").read_text())["inbounds"][0]["listen_port"]
        assert pa != pb, (pa, pb)
    finally:
        await a.stop()
        await b.stop()


# --------------------------------------------------------------------------- #
# config generation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "node_factory, expected_type",
    [
        (_trojan, "trojan"),
        (_reality, "vless"),
        (_ss, "shadowsocks"),
    ],
)
async def test_every_protocol_renders_through_the_shared_outbound_builder(
    workdir, tmp_path, node_factory, expected_type
):
    """The driver does not serialise outbounds a second time.

    `renderer._singbox_outbound` handles seven protocols with the quirks
    already encoded, and a node that renders for a client but not for the
    prober is a node nobody can verify. This asserts the driver's output *is*
    that builder's output for the same node, so a second copy could not drift
    without this failing.
    """
    from hub.renderer import _singbox_outbound

    driver = SingBoxDriver(binary=_fake_binary(tmp_path), workdir=workdir)
    node = node_factory()
    await driver.start()
    try:
        await driver.add_node(node, "tag")
        written = json.loads((workdir / "tag.json").read_text())["outbounds"][0]
        written["tag"] = "tag"  # the driver owns the tag; the builder mints its own
        assert written["type"] == expected_type, written
        # Same server/port/tls as the renderer would produce for this node.
        expected = _singbox_outbound(node, 0, set())
        for key in ("server", "server_port", "tls", "transport"):
            assert written.get(key) == expected.get(key), (key, written, expected)
    finally:
        await driver.stop()


async def test_reality_keys_reach_the_outbound(workdir, tmp_path):
    """REALITY is the reason VLESS nodes pass at all in this deployment.

    `public_key` and `short_id` live in a nested `tls.reality` block, and a
    driver that flattened them would produce a config sing-box refuses to
    start. Asserted through the written file, so a change in how the nested
    object is shaped fails here rather than as an unexplained probe failure.
    """
    driver = SingBoxDriver(binary=_fake_binary(tmp_path), workdir=workdir)
    await driver.start()
    try:
        await driver.add_node(_reality(), "tag")
        outbound = json.loads((workdir / "tag.json").read_text())["outbounds"][0]
        reality = outbound.get("tls", {}).get("reality", {})
        assert reality.get("enabled") is True, outbound
        assert reality.get("public_key") == "kScLZUsi7RrRNpGSL023RjG05tzdegft4kMlij4C5X0", outbound
        assert reality.get("short_id") == "ab", outbound
    finally:
        await driver.stop()


# --------------------------------------------------------------------------- #
# process lifecycle
# --------------------------------------------------------------------------- #


async def test_add_node_starts_a_child_that_actually_listens(workdir, tmp_path):
    """The gap that a file-only implementation leaves.

    Writing a config is not running a proxy: a driver that only writes files
    answers every `socks_check` with a connection refused, and the funnel then
    reports every node unverified while looking perfectly healthy. The stand-in
    core binds the port the config names, so a successful connect here is
    evidence the spawn happened — and that it produced a listener on exactly
    the advertised port.
    """
    driver = SingBoxDriver(binary=_fake_binary(tmp_path, linger=60), workdir=workdir)
    await driver.start()
    try:
        await driver.add_node(_trojan(), "tag")
        port = json.loads((workdir / "tag.json").read_text())["inbounds"][0]["listen_port"]
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=5.0
        )
        writer.close()
        await writer.wait_closed()
    finally:
        await driver.stop()


async def test_a_child_that_exits_before_listening_is_an_error_not_a_success(workdir, tmp_path):
    """`add_node` must not return success for a port nothing is listening on.

    This was a live bug on this host, not a hypothetical. `_await_listening`'s
    "the child already exited" path returned *silently*, so `add_node` — which
    writes `self.entries[tag]` *before* the spawn — handed back a success whose
    entry pointed at a closed port. A live run added 12 nodes, got 12 silent
    successes, and one of them was already unreachable. The funnel read that as
    "dead node" and the speed stage read it as "throughput unknown", and the
    true cause (the config did not start) was recorded nowhere.

    The assertion is on the *exception*, and on the entry being gone. Both
    halves matter: raising while leaving the stale entry would still hand
    `speed_read` a port that is closed, which is the `ConnectionRefusedError`
    this bug was diagnosed from.

    `SingBoxStartError` and not `SingBoxUnavailable`: one node failing to start
    must not tell the caller the binary is missing and cost the other nodes in
    the pool their round.
    """
    driver = SingBoxDriver(
        binary=_fake_binary(tmp_path, extra="--die"), workdir=workdir
    )
    await driver.start()
    try:
        with pytest.raises(SingBoxStartError) as caught:
            await driver.add_node(_trojan(), "tag")
        # The exit code has to survive into the message: "the config was
        # rejected" and "sing-box segfaulted" are different problems and the
        # operator needs the one that was observed.
        assert "3" in str(caught.value), caught.value
        assert "tag" in str(caught.value), caught.value
        # No half-registered node, and no child left to reap.
        assert "tag" not in driver.entries, dict(driver.entries)
        assert "tag" not in driver._procs, dict(driver._procs)
    finally:
        await driver.stop()


async def test_a_child_that_starts_and_never_listens_is_an_error_too(workdir, tmp_path):
    """The other silent path: alive process, no port. Same rule.

    A config sing-box accepts and then wedges never opens the port, and the
    poll runs to `startup_timeout` before giving up. It also used to return
    silently, for the same reason and with the same consequences.

    This test exists because the one above cannot catch it: `--die` exits
    *before* the first poll iteration, so it short-circuits on `returncode` and
    never reaches the deadline branch. An implementation that fixed only the
    first path — which is the one the live incident produced — passes
    `test_a_child_that_exits_before_listening_is_an_error_not_a_success` and
    still holds the deadline silent. Two causes, one observable; each test
    removes one of the mechanisms able to produce it.
    """
    driver = SingBoxDriver(
        binary=_fake_binary(tmp_path, extra="--no-listen"), workdir=workdir,
        startup_timeout=0.3,
    )
    await driver.start()
    try:
        # `--no-listen <seconds>`: the child sleeps past the driver's deadline
        # while the process stays alive, so only the deadline branch can fire.
        with pytest.raises(SingBoxStartError) as caught:
            await driver.add_node(_trojan(), "tag")
        message = str(caught.value)
        assert "never listened" in message, message
        # The port and the bound are both named, because "never came up" with
        # no port is not something an operator can check.
        assert "127.0.0.1" in message, message
        assert "0.3" in message, message
        assert "tag" not in driver.entries, dict(driver.entries)
    finally:
        await driver.stop()
        # The live child must not outlive the driver.
        assert "tag" not in driver._procs, dict(driver._procs)


async def test_stop_reaps_the_child_and_frees_the_port(workdir, tmp_path):
    """A killed-but-unreaped child holds its port until the parent exits.

    This is the failure that makes a second round fail to bind: the kernel
    keeps the socket in the table until the parent reaps the zombie. Asserted
    by binding the same port after `stop()`, which is the only observation
    that distinguishes reaped from merely killed.
    """
    driver = SingBoxDriver(binary=_fake_binary(tmp_path, linger=60), workdir=workdir)
    await driver.start()
    await driver.add_node(_trojan(), "tag")
    port = json.loads((workdir / "tag.json").read_text())["inbounds"][0]["listen_port"]

    await driver.stop()
    # The zombie is reaped, so the port is bindable again.
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        s.listen(1)


async def test_every_added_node_keeps_its_own_process(workdir, tmp_path):
    """One child per live node — the invariant the funnel actually needs.

    This test was written for the opposite design: one resident process,
    replaced on every `add_node`. It passed, and it was wrong, and the
    production funnel is what proved it — 44 real nodes added concurrently,
    every one of them checking a loopback port that the last `add_node`'s
    child had never bound. 0 verified out of 44.

    The replacement asserts the property that makes a concurrent funnel
    correct: after adding several nodes, *each* node's own port answers, not
    just the most recent one. A design that replaces the process fails this
    with exactly one survivor; a design that leaks orphans fails it with a
    child count that does not return to zero.
    """
    driver = SingBoxDriver(binary=_fake_binary(tmp_path, linger=60), workdir=workdir)
    await driver.start()
    try:
        tags = [f"t{i}" for i in range(4)]
        for tag in tags:
            await driver.add_node(_trojan(address=f"{tag}.example.com"), tag)
            await asyncio.sleep(0.05)

        children = await _children_pids()
        assert len(children) == len(tags), (
            f"expected one child per node, got {len(children)} for {len(tags)} nodes"
        )
        # Each node's *own* port must accept. Not just the last one's.
        for tag in tags:
            port = driver.entries[tag].port
            ok = await _port_accepts(port)
            assert ok, f"{tag}'s port {port} is not listening"

        # Removing one node must reap only that node's child and leave the
        # others serving: this is the difference between per-tag children and
        # "kill everything", which the resident-process design would do.
        await driver.remove_node(tags[0])
        for tag in tags[1:]:
            ok = await _port_accepts(driver.entries[tag].port)
            assert ok, f"removing {tags[0]} also killed {tag}"
    finally:
        await driver.stop()

    await asyncio.sleep(0.2)
    assert not await _children_pids(), "stop() left children running"


async def test_a_binary_that_cannot_start_is_named_not_swallowed(tmp_path):
    """Found at construction, gone at runtime: still a diagnosable failure.

    The message names the binary, so an operator sees which one and can set
    `SINGBOX_BIN`; a bare `OSError` from the spawn would name nothing.
    """
    driver = SingBoxDriver(binary="/nonexistent/sing-box", workdir=tmp_path)
    await driver.start()
    with pytest.raises(SingBoxUnavailable) as caught:
        await driver.add_node(_trojan(), "tag")
    assert "/nonexistent/sing-box" in str(caught.value), str(caught.value)


# --------------------------------------------------------------------------- #
# the child dies with the driver
# --------------------------------------------------------------------------- #


async def test_a_child_whose_driver_dies_without_stop_is_reaped(workdir, tmp_path):
    """The orphan case, which is not the case `stop()` covers.

    Every reap in `singbox.py` is Python inside the driver, so every one of them
    is a path that does not run when the driver is SIGKILLed, OOM-killed, or
    raises out of the event loop. That is how PPID=1 sing-box processes showed
    up on the live box three times: the driver was gone, its children were not,
    and nothing in the code could have noticed.

    The assertion is that the *child* is dead, read from `/proc` — not that the
    driver recorded it. A driver that dies cannot record anything, so a test
    asserted against the driver's own bookkeeping would pass on the broken
    build. The child here is a grandchild of this test process: the test forks
    a driver, which forks the child under its own `_spawn`, so the child's
    parent is a process other than the test — which is what makes the
    driver's death observable rather than hypothetical.
    """
    driver_script = tmp_path / "driver.py"
    driver_script.write_text(
        _driver_script(workdir=workdir, binary=_fake_binary(tmp_path, linger=60)),
        encoding="utf-8",
    )

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(driver_script),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=str(tmp_path),
    )
    try:
        # Wait for the driver to say its child is up, so the kill cannot race
        # the spawn: killing before the child exists would leave an assertion
        # that passes because nothing was ever started.
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=30.0)
        assert b"LISTENING" in line, f"driver never came up: {line!r}"

        # The *driver's* own child, which is the sing-box stand-in. The driver
        # is a grandchild of this test process, so this is a child-of-a-child
        # and its parent is the process about to be SIGKILLed.
        driver_pid = proc.pid
        child_pid = await _only_child_pid_of(driver_pid)
        assert child_pid is not None, (
            "the driver forked nothing under itself, so there is no child to"
            " reap and the assertion below would pass vacuously"
        )

        # The death that leaves no chance to run `stop()`: SIGKILL on the
        # driver. `terminate()` would give asyncio its SIGTERM handler, which
        # is the orderly path this test is specifically not about.
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        # Reparenting, if it happens, settles immediately; give the kernel a
        # bounded moment rather than sleeping an arbitrary quarter-second.
        for _ in range(200):
            if not _pid_alive(child_pid):
                break
            await asyncio.sleep(0.01)
        assert not _pid_alive(child_pid), (
            f"child {child_pid} survived its driver's death "
            f"(ppid={_ppid_of(child_pid)}) — an orphaned sing-box still"
            f" holding a loopback port"
        )
    finally:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()


async def test_the_orphan_assertion_can_fail(workdir, tmp_path):
    """The control that makes the test above mean something.

    A child that dies is not, by itself, evidence that the death signal killed
    it — something else could reap orphans on this box (a supervisor's
    control-group kill, a container runtime, a PID-namespace teardown). The way
    to tell is to run the *same* scenario with the guard removed and see
    whether the child survives. It does here, which is what licenses the main
    test's claim: the death above is attributable to `PR_SET_PDEATHSIG` and
    nothing else.

    So this test does not flip with the mutation — it should pass either way.
    Its job is the opposite direction: if it ever *fails*, the child died with
    the guard disabled, which means some other mechanism reaps orphans and the
    main test is no longer isolating what it claims to isolate.
    """
    from hub import singbox as singbox_module

    driver_script = tmp_path / "orphan.py"
    driver_script.write_text(
        _driver_script(
            workdir=workdir,
            binary=_fake_binary(tmp_path, linger=60),
            disable_guard=True,
        ),
        encoding="utf-8",
    )
    assert singbox_module._death_signal_hook is not None  # imported, not shadowed

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(driver_script),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=str(tmp_path),
    )
    orphan_pid: int | None = None
    try:
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=30.0)
        assert b"LISTENING" in line, f"driver never came up: {line!r}"
        # The guard's own absence is what makes this the control: the child of
        # the same driver, found the same way, found and reaped by the test.
        orphan_pid = await _only_child_pid_of(proc.pid)
        assert orphan_pid is not None, (
            "the driver forked nothing under itself, so this control proves"
            " nothing about the death signal"
        )

        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        for _ in range(50):
            if not _pid_alive(orphan_pid):
                break
            await asyncio.sleep(0.01)
        # The point of the whole file: with the guard off, the kernel does not
        # reap, and nothing else does either.
        assert _pid_alive(orphan_pid), (
            f"the control survived too: with the guard removed the child"
            f" {orphan_pid} is still dead, so the orphan test above is not"
            f" isolating the death signal — something else on this box reaps"
            f" orphans, and it alone could be what the main test measures"
        )
    finally:
        # This test deliberately creates an orphan, so it must also be the one
        # to clean it up. Without this the control leaves a live sing-box
        # behind, and a *later* orphan assertion in the same session finds no
        # child to observe and passes for the wrong reason — which is exactly
        # how a first run of this file looked green against the broken build.
        if orphan_pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(orphan_pid, signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()


def _driver_script(*, workdir: Path, binary: str, disable_guard: bool = False) -> str:
    """Source for a driver that adds one node, announces itself, then idles.

    Written to disk and run as a separate process because the property under
    test is about a *process tree*: the child must die when its parent dies,
    and the parent has to be something other than this test process for that
    to be observable. Patching the guard in-process would test a shorthand.

    `disable_guard` replaces `_death_signal_hook` **in the child's own module**,
    before the spawn, which is the only way to observe the build without the
    fix and prove the assertion can actually fail.
    """
    prefix = "import hub.singbox as s\ns._death_signal_hook = lambda: (lambda: None)\n" if disable_guard else ""
    return (
        "import asyncio, sys\n"
        f"sys.path.insert(0, {str(ROOT / 'src')!r})\n"
        f"{prefix}"
        "from pathlib import Path\n"
        "from hub.singbox import SingBoxDriver\n"
        "from hub.models import Node, Protocol, Security, Transport, TransportSettings, TLS\n"
        "node = Node(protocol=Protocol.TROJAN, address='de.example.com', port=443,"
        " password='s', transport=Transport.TCP,"
        " transport_settings=TransportSettings(kind=Transport.TCP),"
        " security=Security.TLS, tls=TLS(sni='de.example.com'))\n"
        "async def main():\n"
        "    d = SingBoxDriver(binary=%r, workdir=Path(%r))\n" % (binary, str(workdir))
        + "    await d.start()\n"
        "    await d.add_node(node, 'tag')\n"
        "    print('LISTENING', flush=True)\n"
        "    await asyncio.sleep(120)\n"
        "asyncio.run(main())\n"
    )


def _pid_alive(pid: int) -> bool:
    """Is this PID still a process the kernel has not reaped?

    `os.kill(pid, 0)` answers a different question — a zombie answers it too,
    because that path checks permission and not liveness. `/proc/<pid>` exists
    for a zombie as well, so the *state* field is the discriminator: `Z` is a
    process that has already exited and is only waiting to be collected. That
    counts as "gone" here, because a zombie holds no listening socket and no
    memory, which is the property actually being asserted.
    """
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            fields = fh.read().rsplit(")", 1)[1].split()
        return fields[0] != "Z"
    except (OSError, IndexError):
        return False


def _ppid_of(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            fields = fh.read().rsplit(")", 1)[1].split()
        return fields[1]
    except (OSError, IndexError):
        return "?"


async def _only_child_pid_of(pid: int) -> Optional[int]:
    """The single process whose parent is `pid`, or `None` if there is not one.

    Needed because the driver under test is itself a *child* of this test
    process — `_children_pids()` reports the driver, and an assertion that the
    driver is dead after `proc.kill()` is true for reasons that have nothing
    to do with `PR_SET_PDEATHSIG`. This looks one level further down, at the
    sing-box child the driver spawned, which is the one whose reaping is the
    property under test.

    Returns `None` rather than raising when the tree is not what is expected,
    so the callers can assert on the *absence* itself. A test that silently
    picks the wrong PID passes for a reason unrelated to its own claim.
    """
    found: list[int] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="utf-8") as fh:
                fields = fh.read().rsplit(")", 1)[1].split()
            ppid = int(fields[1])
        except (OSError, ValueError, IndexError):
            continue
        if ppid == pid:
            found.append(int(entry))
    return found[0] if len(found) == 1 else None


async def test_the_guard_is_not_armed_on_a_platform_without_it(monkeypatch):
    """`_death_signal_hook` is a no-op where `PR_SET_PDEATHSIG` is not Linux.

    Called out in the platform helper so a caller on macOS silently keeps the
    old behaviour rather than crashing at the first `add_node`. The test pins
    the branch, because the code that would remove it is a `startswith` — and
    on a non-Linux box the guard does not exist, which means this whole file's
    orphan guarantee is a Linux guarantee. That must be visible, not assumed.
    """
    from hub import singbox as singbox_module

    monkeypatch.setattr(singbox_module.sys, "platform", "darwin")
    hook = singbox_module._death_signal_hook()
    hook()  # must not raise, and must not signal anything
    assert callable(hook)
    assert hook is not singbox_module._death_signal_preexec


# --------------------------------------------------------------------------- #
# SOCKS5
# --------------------------------------------------------------------------- #


async def _scripted_server(handler) -> tuple[int, asyncio.base_events.Server]:
    """A loopback SOCKS5 server whose behaviour is the test's to choose.

    Started on `127.0.0.1:0`, so the port is chosen by the OS and the listener
    is unreachable from outside this host. Nothing here dials a target: the
    handler decides what to answer and the client code under test is what is
    being observed.
    """
    async def _serve(reader, writer):
        try:
            await handler(reader, writer)
        finally:
            with contextlib.suppress(Exception):
                writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    server = await asyncio.start_server(_serve, "127.0.0.1", 0)
    return server.sockets[0].getsockname()[1], server


async def _method_aware_peer(certfile: str, method: str = "GET", status: str = "200 OK"):
    """A SOCKS+TLS peer that answers like Cloudflare does to `HEAD`.

    It completes the SOCKS greeting and CONNECT, upgrades to TLS, and then
    reads the client's request one byte at a time until it sees the expected
    request line. Byte-at-a-time rather than `readline()` because
    `_http_over_socks` writes its whole request with a single `writer.write`,
    and a peer waiting on a CRLF that only completes at the end would block
    until the driver's timeout — which is a hang, not a test.

    The byte counts are the ones `_socks_handshake`/`_socks_connect` consume on
    the client side; a peer that answers with more leaves the surplus to be
    read as the start of the TLS handshake, which surfaces as a reset
    connection indistinguishable from a handshake failure.
    """
    expect = f"{method} /{_probe_path()} HTTP/1.1".encode()
    wrong = "HEAD" if method == "GET" else "GET"

    async def _serve(reader, writer):
        with contextlib.suppress(Exception):
            greeting = await reader.readexactly(2)  # VER, NMETHODS
            await reader.readexactly(greeting[1])
            writer.write(b"\x05\x00")
            await writer.drain()
            head = await reader.readexactly(4)
            atyp = head[3]
            if atyp == 0x01:
                await reader.readexactly(4)
            elif atyp == 0x03:
                await reader.readexactly((await reader.readexactly(1))[0])
            else:
                await reader.readexactly(16)
            await reader.readexactly(2)
            writer.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
            await writer.drain()
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile)
            await writer.start_tls(context)
            received = b""
            while expect not in received:
                chunk = await reader.read(1)
                if not chunk:
                    break
                received += chunk
                if len(received) > 4096 or b"\r\n\r\n" in received:
                    break
            if received.startswith(wrong.encode()):
                # The real Cloudflare behaviour that cost a production round:
                # `HEAD /cdn-cgi/trace` -> 404, while `GET` -> 200.
                body = b"not found"
                writer.write(
                    b"HTTP/1.1 404 Not Found\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\nConnection: close\r\n\r\n" + body
                )
            else:
                body = b"200-body"
                writer.write(
                    f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\n"
                    "Connection: close\r\n\r\n".encode() + body
                )
            await writer.drain()
        with contextlib.suppress(Exception):
            writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()

    server = await asyncio.start_server(_serve, "127.0.0.1", 0)
    return server.sockets[0].getsockname()[1], server


def _probe_path() -> str:
    """The driver's own probe path, read from the module rather than copied.

    A test that hardcodes `cdn-cgi/trace` passes silently if the driver's
    `_PROBE_PATH` changes, because the peer would then be answering a request
    the driver never sends.
    """
    return singbox._PROBE_PATH


async def _greet(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """The *server* half of the greeting: read the offer, accept no-auth.

    Deliberately not `_socks_handshake`, which is the *client* half — it writes
    the greeting and reads the reply. A handler that called it would write a
    greeting at a peer that sends none and deadlock, which is indistinguishable
    from a driver that never sends one. Separating the halves is what makes a
    test that skips the handshake fail loudly instead of hanging or
    mis-parsing: without this, the greeting read eats the first three bytes of
    the connect request and the length byte read back is a host octet.
    """
    greeting = await reader.readexactly(3)
    assert greeting[0] == 0x05, greeting
    assert greeting[1] == 0x01, greeting  # exactly one method offered
    assert greeting[2] == 0x00, greeting  # and it is "no authentication"
    writer.write(b"\x05\x00")
    await writer.drain()


async def _connect(reader, writer, host: str, port: int) -> None:
    """The client half of a full round: handshake, then CONNECT.

    `_socks_connect` presumes a greeting has already been sent and answered,
    exactly as the driver's `_socks_roundtrip` sequences them. Driving it
    alone makes the *server's* greeting read consume the first three bytes of
    the connect request, so the length byte it reads back is a host octet —
    a client-side desynchronisation that belongs to the test, not the driver.
    """
    await asyncio.wait_for(_socks_handshake(reader, writer), timeout=2.0)
    await asyncio.wait_for(_socks_connect(reader, writer, host, port), timeout=2.0)


async def test_the_greeting_is_no_auth_and_the_reply_is_checked():
    """RFC 1928 greeting.

    A reply of `method 0xFF` (no acceptable method) must raise rather than be
    treated as success — a driver that ignored the method byte would report
    every node as working, because it would read the *next* bytes as the
    connect reply and mis-parse them as an address.
    """
    async def refuse(reader, writer):
        await reader.readexactly(3)
        writer.write(b"\x05\xff")  # no acceptable authentication method
        await writer.drain()

    port, server = await _scripted_server(refuse)
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            with pytest.raises(OSError):
                await asyncio.wait_for(_socks_handshake(reader, writer), timeout=2.0)
        finally:
            writer.close()


async def test_the_connect_request_sends_the_domain_not_an_ip():
    """ATYP 0x03, with the length prefix, and the port big-endian.

    Resolving here instead would measure the *host's* DNS rather than the
    node's, which is a different (and less useful) fact. The bytes are read off
    the wire, so a driver that pre-resolved would send ATYP 0x01 and fail this.
    """
    seen: list[bytes] = []

    async def capture(reader, writer):
        await _greet(reader, writer)
        # version, cmd, rsv, atyp, then a length byte, then host, then port.
        head = await reader.readexactly(5)
        length = head[4]
        seen.append(head + await reader.readexactly(length + 2))
        # A 12-byte domain and a 2-byte port follow the 5-byte header; the
        # request is exactly that, so an off-by-one here would leave the port
        # unread and the assertion below would compare against nothing.
        writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await writer.drain()

    port, server = await _scripted_server(capture)
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            await _connect(reader, writer, "cloudflare.com", 443)
        finally:
            writer.close()
    assert seen, "no connect request arrived"
    request = seen[0]
    assert request[3] == 0x03, request
    length = request[4]
    assert request[5:5 + length] == b"cloudflare.com", request
    assert request[5 + length:] == (443).to_bytes(2, "big"), request


async def test_a_failed_connect_reply_raises():
    """REP != 0 is a failure, and must not be read as an address.

    The reply's address is length-prefixed by its own type; a driver that
    skipped the REP check would consume those bytes as the next request and
    hang. Asserting the raise is what keeps that honest.
    """
    async def refuse(reader, writer):
        await _greet(reader, writer)
        head = await reader.readexactly(5)
        await reader.readexactly(head[4] + 2)
        writer.write(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")  # connection refused
        await writer.drain()

    port, server = await _scripted_server(refuse)
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            with pytest.raises(OSError):
                await _connect(reader, writer, "h.example", 80)
        finally:
            writer.close()


async def test_the_reply_address_of_each_type_is_consumed():
    """A server may answer with any ATYP, and the reader must land cleanly.

    Three replies, three address lengths. A reader that assumed IPv4 would
    desynchronise on a domain reply and the next stage would read garbage as a
    timestamp — which looks like a slow node rather than a broken parse.
    """
    async def domain_reply(reader, writer):
        await _greet(reader, writer)
        head = await reader.readexactly(5)
        await reader.readexactly(head[4] + 2)
        # 5-byte header + host + 2-byte port: the same length the client sends.
        # REP 0, ATYP 3, len 4, "node", port 1080
        writer.write(b"\x05\x00\x00\x03\x04node\x04\x38")
        await writer.drain()

    port, server = await _scripted_server(domain_reply)
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            # Completes without raising, which is the whole assertion: the
            # reader consumed exactly the reply and stopped.
            await _connect(reader, writer, "h.example", 1080)
        finally:
            writer.close()


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #


def test_cdn_cgi_trace_is_parsed_as_flat_key_values():
    """The response is `key=value` per line, and `ip=` is where it starts.

    Asserted on a real body, including the `fl=` field that varies in length,
    so a parser that split on a fixed column count would fail here rather than
    reporting a wrong country for every node.
    """
    body = (
        "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n"
        "fl=4f2a1b\nh=1.1.1.1\nip=203.0.113.7\nts=1750000000.1\n"
        "visit_scheme=https\nuag=hub-prober/1\ncolo=AMS\nsl=en\ntls=TLSv1.3\n"
        "http=http/3\nloc=NL\n"
    ).encode()
    parsed = _parse_trace(body)
    assert parsed["loc"] == "NL", parsed
    assert parsed["ip"] == "203.0.113.7", parsed
    assert parsed["colo"] == "AMS", parsed


def test_a_body_without_a_trace_is_empty_not_a_crash():
    """A captive portal answering with HTML is an ordinary event.

    Returning `{}` rather than raising is what lets the funnel record "no exit
    country" and move on; the protocol docstring makes it optional for exactly
    this reason.
    """
    assert _parse_trace(b"<html>login required</html>") == {}


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://cloudflare.com/cdn-cgi/trace", ("cloudflare.com", 443, "/cdn-cgi/trace")),
        ("http://1.1.1.1/cdn-cgi/trace", ("1.1.1.1", 80, "/cdn-cgi/trace")),
        ("https://x.example:8443/p", ("x.example", 8443, "/p")),
        ("https://x.example", ("x.example", 443, "/")),
        # The query string is part of the request target, not decoration.
        # `https://speed.cloudflare.com/__down?bytes=262144` took its size
        # *only* from `?bytes=`, and `urlsplit().path` drops it — so the driver
        # asked for an unbounded transfer while believing it had asked for
        # 256 KiB, and the endpoint answered with nothing to measure. Every
        # case above is query-free, which is exactly why none of them caught it.
        (
            "https://speed.cloudflare.com/__down?bytes=262144",
            ("speed.cloudflare.com", 443, "/__down?bytes=262144"),
        ),
        (
            "https://speed.cloudflare.com/__down?bytes=4194304",
            ("speed.cloudflare.com", 443, "/__down?bytes=4194304"),
        ),
        (
            "http://speed.cloudflare.com/__down?bytes=1&x=2",
            ("speed.cloudflare.com", 80, "/__down?bytes=1&x=2"),
        ),
        # A bare `?` with nothing after it is not a query, and must not produce
        # a trailing `?` in the request line.
        ("https://x.example/p?", ("x.example", 443, "/p")),
    ],
)
def test_urls_split_for_the_speed_reader(url, expected):
    assert _split_url(url) == expected, url


# --------------------------------------------------------------------------- #
# the real binary, when there is one
# --------------------------------------------------------------------------- #


async def test_config_ok_reports_what_the_binary_actually_said(workdir, tmp_path):
    """`config_ok` is the verdict-handling, not the verdict.

    The real binary's opinion is a subprocess exit code, and that plumbing is
    what a stand-in can observe: a fake `sing-box` that exits non-zero must
    produce `False`, and one that exits zero must produce `True`. Without
    this, `return True` in place of `returncode == 0` survives the whole
    suite, because the only other caller of `config_ok` is skipped on any box
    that does not have sing-box installed -- which is every box until the
    operator installs it.
    """

    def _stub(name: str, script: str) -> str:
        # A distinct path per stub. Writing both to one filename leaves the
        # second one there, so `accepts.binary == rejects.binary` and the first
        # assertion reads the reject stub's exit code — the test then fails for
        # a reason that has nothing to do with the driver.
        path = tmp_path / name
        path.write_text("#!/usr/bin/env python3\n" + script, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return str(path)

    accepts = _stub("stub-accepts", "import sys; sys.exit(0)")
    rejects = _stub("stub-rejects", "import sys; sys.stderr.write('bad outbound\\n'); sys.exit(1)")

    ok_driver = SingBoxDriver(binary=accepts, workdir=workdir)
    reject_driver = SingBoxDriver(binary=rejects, workdir=workdir)
    for driver in (ok_driver, reject_driver):
        await driver.start()
    try:
        # Two different binaries under two different paths: this only fails if
        # the driver treats a non-zero exit as success, which is the whole
        # point. An assert pair that passes when both binaries are the same
        # file would not prove that.
        assert ok_driver.binary != reject_driver.binary
        assert await ok_driver.config_ok(_trojan()) is True
        assert await reject_driver.config_ok(_trojan()) is False
        # ...and it holds per node, not once per driver.
        assert await ok_driver.config_ok(_reality()) is True
        assert await reject_driver.config_ok(_reality()) is False
    finally:
        for driver in (ok_driver, reject_driver):
            await driver.stop()


async def test_a_hanging_check_is_killed_rather_than_waited_on(workdir, tmp_path):
    """`check_timeout` bounds the subprocess, and the bound is real.

    A `check` that never exits is the failure that turns one malformed node
    into a round that never ends. Asserted with a stub that sleeps and a
    timeout far shorter than the sleep, so a missing `wait_for` would hang the
    suite instead of failing it -- which is why this is a test at all rather
    than a comment promising the behaviour.
    """

    def _stub() -> str:
        path = tmp_path / "slow-check"
        path.write_text(
            "#!/usr/bin/env python3\nimport time\ntime.sleep(60)\n", encoding="utf-8"
        )
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return str(path)

    driver = SingBoxDriver(binary=_stub(), workdir=workdir, check_timeout=0.25)
    await driver.start()
    try:
        started = asyncio.get_running_loop().time()
        ok = await driver.config_ok(_trojan())
        elapsed = asyncio.get_running_loop().time() - started
        assert ok is False, ok
        assert elapsed < 10, f"the hang was waited on: {elapsed:.1f}s"
    finally:
        await driver.stop()


async def test_no_temporary_config_is_left_behind_by_a_check(tmp_path):
    """`_write_temp` cleans up, and the cleanup is observable.

    A work directory that accumulated one temp config per node would grow
    without bound across rounds, and each of those files holds live material
    (UUIDs, passwords) that a round should not leave lying around.

    The count is taken with a driver whose *only* artifacts are the temp
    configs: a workdir separate from `tmp_path`, so the fixtures this test
    itself writes cannot be miscounted as a leak. (They were, the first time.)
    """
    from hub.singbox import SingBoxDriver

    workdir = tmp_path / "work"
    stub = tmp_path / "stub-check"
    stub.write_text("#!/usr/bin/env python3\\nimport sys; sys.exit(0)\\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    driver = SingBoxDriver(binary=str(stub), workdir=workdir)
    await driver.start()
    try:
        await driver.config_ok(_trojan())
        await driver.config_ok(_reality())
        left = sorted(p.name for p in workdir.iterdir())
        assert left == [], left
    finally:
        await driver.stop()


@pytest.mark.skipif(find_binary() is None, reason="sing-box is not installed")
async def test_a_real_binary_validates_the_renderer_output(tmp_path):
    """`sing-box check` on a config this project generated.

    The one test that uses the real binary, and it runs `check` — a pure
    validation mode that reads the file and exits. No listener, no outbound
    connection, nothing on the network.

    It is here because the assertable promise is "a node that renders for a
    client also passes the prober's own config check", and only the real
    binary can confirm that. Without it the driver is trusted on the strength
    of the renderer's own output, which is the same code saying the same thing.
    """
    driver = SingBoxDriver(workdir=tmp_path)
    await driver.start()
    try:
        for node in (_reality(), _trojan(), _ss()):
            ok = await driver.config_ok(node)
            assert ok, f"{node.protocol.value} failed `sing-box check`"
    finally:
        await driver.stop()



# --------------------------------------------------------------------------- #
# the CLI's three gates
# --------------------------------------------------------------------------- #


def test_a_run_without_the_network_flag_has_no_factory_at_all(monkeypatch):
    """The flag is the first gate, and it has to be observable on its own.

    Nothing else may be able to produce this outcome. In practice the other
    two gates return `None` too, so a gate-1 test that only asserted
    `factory is None` would pass with gate 1 deleted — a refusal from the
    namespace gate looks identical to a refusal from the flag. That is why
    the reason is asserted here and why the other two gates are satisfied:
    with a namespace available *and* a binary found, the only thing that can
    still refuse is the flag itself.
    """

    class _Args:
        allow_network = False

    monkeypatch.setattr(cli, "_is_isolated", lambda: (True, "isolated already"))
    monkeypatch.setattr(singbox, "find_binary", lambda: "/usr/bin/sing-box")
    factory, reason = _driver_factory(_Args())
    assert factory is None, "probing was enabled without --allow-network"
    assert "--allow-network" in reason, reason
    assert "namespace" not in reason.lower(), reason
    assert "sing-box" not in reason.lower(), reason


def test_a_box_that_cannot_isolate_gets_named_not_a_second_guess(monkeypatch):
    """No namespace → no probing, whatever else is true.

    The reason must name the namespace, not the binary: this box has neither,
    and a message that says "install sing-box" would send an operator to fix
    the one thing that is not the problem.
    """

    class _Args:
        allow_network = True

    monkeypatch.setattr(cli, "_is_isolated", lambda: (False, "no namespace here"))
    monkeypatch.setattr(singbox, "find_binary", lambda: "/usr/bin/sing-box")
    factory, reason = _driver_factory(_Args())
    assert factory is None, "probing was enabled on a box that cannot isolate"
    assert "namespace" in reason.lower(), reason


def test_no_binary_is_a_named_reason_rather_than_a_silent_none(monkeypatch):
    """The third gate, and its reason has to name the fix.

    A `None` with no reason is indistinguishable from "this run never asked",
    which is how a misconfigured worker reports `0 verified` for months.
    """

    class _Args:
        allow_network = True

    monkeypatch.setattr(cli, "_is_isolated", lambda: (True, "isolated already"))
    monkeypatch.setattr(singbox, "find_binary", lambda: None)
    factory, reason = _driver_factory(_Args())
    assert factory is None, factory
    assert "SINGBOX_BIN" in reason, reason


def test_every_gate_fires_only_on_its_own_condition(monkeypatch):
    """Two guards must not be able to produce the same observable.

    Each gate is tested with the other two *satisfied*, so a message naming
    the namespace cannot come from a missing binary and vice versa. Without
    this, deleting either gate is invisible: the other still refuses, and the
    reason still prints.
    """

    class _Args:
        allow_network = True

    # Gate 2 fires with the binary present and the flag set.
    monkeypatch.setattr(singbox, "find_binary", lambda: "/usr/bin/sing-box")
    monkeypatch.setattr(cli, "_is_isolated", lambda: (False, "no namespace here"))
    _, ns_reason = _driver_factory(_Args())
    assert "namespace" in ns_reason.lower(), ns_reason
    assert "sing-box" not in ns_reason.lower(), ns_reason

    # Gate 3 fires with the namespace available and the flag set.
    monkeypatch.setattr(cli, "_is_isolated", lambda: (True, "isolated already"))
    monkeypatch.setattr(singbox, "find_binary", lambda: None)
    _, bin_reason = _driver_factory(_Args())
    assert "SINGBOX_BIN" in bin_reason, bin_reason
    assert "namespace" not in bin_reason.lower(), bin_reason


def test_the_gate_is_asked_about_namespaces_not_about_the_binary(monkeypatch):
    """`_can_create_netns` runs `unshare -rn true`, so it probes the *capability*.

    Spying on `subprocess.run` is what pins the exact argv: a gate that asked
    `unshare -rn -- cat /etc/hosts` would still "work" while testing the wrong
    thing, and a gate that asked about the presence of `unshare` alone would
    report True on a kernel without `CONFIG_USER_NS`.
    """
    import subprocess

    seen: list[list[str]] = []
    real = subprocess.run

    def spy(argv, *a, **kw):
        seen.append(list(argv))
        return real(["true"], *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    assert cli._can_create_netns() is True
    assert seen, "unshare was never invoked"
    assert seen[0][0].endswith("unshare"), seen[0]
    assert "-rn" in seen[0], seen[0]
    assert "true" in seen[0], seen[0]


def test_the_namespace_gate_refuses_when_the_kernel_says_no(monkeypatch):
    """`unshare` exiting non-zero is a refusal, not a warning.

    EPERM and ENOSYS both land here as a non-zero exit, and both mean the same
    thing for our purposes: this process cannot be isolated, so it must not
    probe.
    """
    import subprocess

    class _Proc:
        returncode = 1

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Proc())
    assert cli._can_create_netns() is False

    class _Raises:
        def __call__(self, *a, **kw):
            raise subprocess.SubprocessError("no unshare")

    monkeypatch.setattr(subprocess, "run", _Raises())
    assert cli._can_create_netns() is False


def test_an_already_isolated_process_is_not_asked_to_isolate_again(monkeypatch):
    """A namespace with no external interface is already safe, and says so.

    `unshare -rn` and `PrivateNetwork=yes` both produce a namespace whose only
    interface is loopback, which provably has no path to the host's network. Such
    a run must be accepted — and `_can_create_netns` is rigged to raise so the
    test proves the capability question is not even asked for it: the answer comes
    from where the process *is*, not from what it could do.

    The rerouting of this test compared with its first version is the point. It
    used to assert `"already" in reason`; the message now names the observable and
    the observables changed when the source of truth moved from `/sys/class/net`
    to `/proc/net/dev` (see `_interface_names`). Asserting on the *shape* of the
    namespace rather than on a word is what keeps this test honest if the wording
    changes again.
    """
    monkeypatch.setattr(cli, "_interface_names", lambda: {"lo"})
    monkeypatch.setattr(
        cli, "_can_create_netns",
        lambda: (_ for _ in ()).throw(AssertionError("asked to isolate an isolated run")),
    )
    monkeypatch.setattr(cli, "_isolation_method", lambda: None)
    ok, reason = cli._is_isolated()
    assert ok is True, reason
    # The interfaces are named, not summarised. A generic "already isolated"
    # passes the assertion above and tells an operator nothing about *why* this
    # run was considered safe — which is the whole point of a message that is
    # going to be read when someone is deciding whether to trust the gate.
    assert "lo" in reason, reason
    # "private" is the word that carries the reason: there is no bind mount and no
    # uplink, so the only thing keeping this off the host's network is the absence
    # of a route. Naming it is what distinguishes this from a *managed* namespace.
    assert "private" in reason.lower(), reason


def test_the_host_namespace_is_not_treated_as_isolated(monkeypatch):
    """The other half: real interfaces and no bind mount means no isolation.

    This is the failure the whole module exists to prevent: a run on the live
    host must never be told it is isolated. The earlier version compared
    `/proc/self/ns/net` against `/proc/1/ns/net`, which is root-owned and
    therefore raises `PermissionError` for an unprivileged service; the natural
    handling of that was to assume "same namespace", which reports the host as
    isolated. Identity is now read from `/run/netns` inodes instead, which cannot
    make that mistake because the bind mounts are world-readable.
    """
    monkeypatch.setattr(cli, "_interface_names", lambda: {"lo", "eth0"})
    monkeypatch.setattr(cli, "_named_netns", lambda: None)
    monkeypatch.setattr(cli, "_isolation_method", lambda: None)
    ok, reason = cli._is_isolated()
    assert ok is False, reason
    assert "eth0" in reason, reason  # the evidence, not just the verdict


def test_the_interface_list_comes_from_the_kernel_s_not_from_a_stale_mount(tmp_path, monkeypatch):
    """`/proc/net/dev`, because `/sys/class/net` lies inside a namespace here.

    This test exists because a mutation proved the suite could not see the
    difference: reverting `_interface_names` to `/sys/class/net` left every test
    green. Every gate test above monkeypatches this function — correctly, because
    they are about the *decision* — with the side effect that nothing pinned the
    file it reads. A gate whose source of evidence silently changes is a gate
    whose accident nobody notices.

    So the two sources are given *different content* and the function's answer
    must follow the kernel one:

        /proc/net/dev      -> "lo"       (the truth: a private namespace)
        /sys/class/net     -> "eth0"     (the stale mount, listing the host)

    Reading the stale one is not hypothetical and not a kernel bug: on this host
    `/sys` is a ro bind mount made by the container runtime *before* the namespace
    switch, and `unshare` never remounts sysfs. Verified:

        on the host:      /proc/net/dev  lo eth0 docker0 veth-hub-br
        unshare -rn:      /proc/net/dev  lo     /sys/class/net  eth0 docker0 veth-hub-br

    The consequence for the gate is a false *negative in the safety direction* —
    a correctly isolated `unshare -rn` run sees `eth0` in `/sys` and is refused,
    which reads as "this box cannot isolate" and sends an operator to fix the
    wrong thing for hours. Note the direction: the stale source fails closed, so
    this is a correctness bug and a debugging trap rather than a leak. The reason
    to pin it is that the *other* interface-source bug — one that failed open —
    would look identical to a passing suite.
    """
    proc = tmp_path / "proc-net-dev"
    proc.write_text(
        "Inter-|   Receive\n"
        " face |bytes\n"
        "    lo: 1234 0 0 0 0 0 0 0\n",
        encoding="ascii",
    )
    sysdir = tmp_path / "sys-class-net"
    (sysdir / "lo").mkdir(parents=True)
    (sysdir / "eth0").mkdir(parents=True)

    monkeypatch.setattr(cli, "_PROC_NET_DEV", proc)
    monkeypatch.setattr(cli, "_SYS_CLASS_NET", sysdir)

    names = cli._interface_names()
    # The kernel's file won, and the stale one would have answered differently.
    assert names == {"lo"}, names
    # The control, stated as a fact about the fixture rather than about the code:
    # the other source still advertises the host, so the two really do disagree
    # and the assertion above is not a tautology.
    assert {p.name for p in sysdir.iterdir()} == {"lo", "eth0"}


def test_an_unreadable_interface_file_is_cannot_tell_and_not_isolated(monkeypatch):
    """"Cannot tell" must read as a refusal, or the gate inverts.

    The failure mode this guards is specific: an operator deletes the proc mount,
    or a hardened container hides `/proc/net/*`, and `_interface_names` returns
    `set()`. The obvious handling — "no interfaces, so nothing to reach the host
    with, so it is safe" — is exactly backwards, because `set()` also means "I
    could not see". An empty namespace and an unreadable one are the same `set()`
    and must not be the same answer.

    Pinned on the interface-source path and not only on `_is_isolated`, because
    the wrong handling lives in the reader, and a test that fixes it at the caller
    would leave any other caller free to reintroduce it.
    """
    monkeypatch.setattr(cli, "_PROC_NET_DEV", Path("/nonexistent/proc/net/dev"))

    assert cli._interface_names() == set()
    ok, reason = cli._is_isolated()
    assert ok is False, reason
    # The reason must say it could not see anything, rather than claiming an
    # empty namespace with "only [] visible" — which would be the lie that makes
    # an unreadable kernel indistinguishable from a genuinely isolated one.
    assert "visible" in reason, reason


def test_a_box_that_can_isolate_is_not_the_same_as_being_isolated(monkeypatch):
    """`hub run` on the host is refused even where a namespace is *creatable*.

    This test replaced two that asserted the opposite, and it is the one that
    matters. The gate used to answer "am I isolated, or could isolation still be
    done?" with `True` for both — so a process running on the live host was told
    `(True, "probing can be isolated with `unshare -rn`")`. Verified on this host
    before the fix: the host netns answered green.

    A gate that green-lights the un-isolated case is worse than no gate, because
    it converts the one state that must fail into the pass that is read as
    permission. The capability question belongs to whoever is about to create the
    namespace; a *permission* gate must be about the current process only.

    The two old tests are kept in their corrected form beside this one: "lo only"
    and "a managed namespace" are the two shapes that *are* isolated. What is gone
    is the third shape, "not isolated but creatable", which was never safe to
    accept.
    """
    monkeypatch.setattr(cli, "_interface_names", lambda: {"lo", "eth0"})
    monkeypatch.setattr(cli, "_named_netns", lambda: None)
    monkeypatch.setattr(cli, "_isolation_method", lambda: "unshare -rn")
    ok, reason = cli._is_isolated()
    assert ok is False, reason
    # The refusal must say what to do, because "you are not isolated" alone sends
    # an operator looking for a bug in the gate rather than for the flag they
    # forgot. It must not, however, claim the box cannot isolate.
    assert "re-run inside" in reason, reason


def test_a_managed_namespace_with_an_uplink_is_accepted_and_named(monkeypatch):
    """The hubns shape: a veth and a default route, and still isolated.

    This is the configuration `hub-probe.service` actually runs in, and it is the
    case an interface-list heuristic cannot get right. `hubns` has an external
    interface (`veth-hub`) *and* a route out of it (`default via 10.99.0.1`), so
    "no host interfaces visible" is false — yet it is the single safest shape on
    the box, because it is a *named* namespace whose loopback is not the host's and
    whose uplink is a MASQUERADE with no path back to eth0.

    Identification, not inference: `/proc/self/ns/net`'s inode matches
    `/run/netns/hubns`'s bind-mount inode, so the answer is a fact about the
    process rather than a judgement about its traffic-shaped properties. Verified
    on this host inside `ip netns exec hubns` (mine 4026532270 == hubns
    4026532270), and on the host where they differ (4026531840).

    The test also pins why the inode test comes *after* the `lo`-only test: an
    empty namespace is refused by no bind mount but is still safe, and that
    answer must not depend on `/run/netns` existing.
    """
    monkeypatch.setattr(cli, "_interface_names", lambda: {"lo", "veth-hub"})
    monkeypatch.setattr(cli, "_named_netns", lambda: "hubns")
    ok, reason = cli._is_isolated()
    assert ok is True, reason
    # It must name *which* namespace. "You are in a namespace" is not the
    # reassurance "you are in hubns" is, and the second is the one an operator
    # can check with `ip netns list`.
    assert "hubns" in reason, reason
    # And it must not be reported as the safe-but-route-less shape: those are
    # different namespaces with different properties, and conflating them would
    # make this test pass against the `lo`-only implementation.
    assert "private network namespace" not in reason, reason


def test_a_namespace_with_an_uplink_that_cannot_be_named_is_refused(monkeypatch):
    """The conservative direction: a veth and no bind mount is the host.

    The counterpart to the test above, and the reason this function refuses
    rather than infers. If a namespace has an external interface and no
    `/run/netns` entry to identify it, the only two possibilities are "the host"
    and "an operator made this by some route this module does not know about".
    The gate cannot tell those apart, and "cannot tell" must fail closed — the
    alternative is a prober dialing nodes through eth0 while a log line claims a
    namespace.

    This is the shape that would catch a `hubns` deleted from `/run/netns` while
    its veth survived: not a realistic accident, but the case where the inode
    test and the interface test disagree, and the disagreement must not resolve
    towards "safe".
    """
    monkeypatch.setattr(cli, "_interface_names", lambda: {"lo", "veth-hub"})
    monkeypatch.setattr(cli, "_named_netns", lambda: None)
    monkeypatch.setattr(cli, "_isolation_method", lambda: "unshare -rn")
    ok, reason = cli._is_isolated()
    assert ok is False, reason


def test_no_isolation_of_any_kind_is_still_a_refusal(monkeypatch):
    """The gate has to be able to say no.

    `_isolation_method` returning `None` is the box where nothing works: no
    unprivileged namespaces, no passwordless sudo, no operator namespace. Then
    the answer is a refusal even though the flag was passed, and that refusal
    is the whole point of the gate.

    Note what this test no longer proves on its own: with the old contract it was
    the *only* refusal test, so it passed while the host was green-lit. A single
    "can say no" test is not evidence that the gate says no *in the right place* —
    that is what `test_a_box_that_can_isolate_is_not_the_same_as_being_isolated`
    and `test_the_host_namespace_is_not_treated_as_isolated` are for.
    """
    monkeypatch.setattr(cli, "_interface_names", lambda: {"lo", "eth0"})
    monkeypatch.setattr(cli, "_named_netns", lambda: None)
    monkeypatch.setattr(cli, "_isolation_method", lambda: None)
    ok, reason = cli._is_isolated()
    assert ok is False, reason
    assert "namespace" in reason.lower(), reason


def test_cannot_tell_is_not_the_same_as_isolated(monkeypatch):
    """No sysfs, no answer — and no probing either.

    An empty interface list is a box that mounted nothing at `/sys/class/net`,
    not a box that is safe. Treating it as isolated would open the hole the gate
    exists to close, so it falls through to the capability question exactly as
    "visible host interfaces" does.
    """
    monkeypatch.setattr(cli, "_interface_names", lambda: set())
    monkeypatch.setattr(cli, "_isolation_method", lambda: None)
    ok, reason = cli._is_isolated()
    assert ok is False, reason


# --------------------------------------------------------------------------- #
# The measurement is TLS, and the verdict is the status code
#
# These exist because of a defect that reached a real generation: every probe
# sent plain HTTP to port 443, where Cloudflare answers `400 Bad Request`, and
# `_socks_roundtrip` called that a success because the line *starts* with
# `HTTP/`. 70 nodes were published as verified with no country at all. The
# suite was green the whole time, which is the part worth remembering.
#
# Each test below kills one half of that defect on its own, so a stale-green
# result is not available: no TLS and the request is refused before a status
# exists; no status check and a 400 counts as healthy.
# --------------------------------------------------------------------------- #

def _self_signed():
    """A throwaway cert/key pair, so the fake peer can complete a real handshake.

    Written into a temp file rather than generated per connection: the cost is
    per-run, not per-request, and the alternative (a client that skips
    verification) would mean the driver under test is the thing being
    reimplemented — a verifying handshake is part of what is being asserted.
    """
    pem_path = Path(tempfile.mkdtemp(prefix="hub-tls-")) / "cert.pem"
    # SAN, not just CN: modern clients ignore CN entirely, so a certificate
    # with only `CN=cloudflare.com` is rejected for `speed.cloudflare.com` as
    # a hostname mismatch. Both names the probes touch are listed, because the
    # alternative is a test that passes for the trace and fails for the speed
    # reader for a reason that has nothing to do with the code under test.
    subject_alt = "subjectAltName=DNS:cloudflare.com,DNS:speed.cloudflare.com"
    with contextlib.suppress(Exception):
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(pem_path), "-out", str(pem_path),
                "-days", "1", "-nodes",
                "-subj", "/CN=cloudflare.com",
                "-addext", subject_alt,
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
            check=True,
        )
    if not pem_path.exists():
        pytest.skip("openssl unavailable, so no TLS server can be stood up")
    return str(pem_path)


@contextlib.contextmanager
def _patched_ssl(certfile: str):
    """Temporarily make `singbox.ssl` trust `certfile`, then put it back.

    A `with` rather than a decorator or a fixture, because the patch has to be
    settled before the driver's call and removed after — leaving it in place
    would make every later test in the process trust a self-signed certificate,
    which is the one thing this file must never teach the driver.
    """
    saved, shim = singbox.ssl, _trust_our_cert(certfile)
    singbox.ssl = shim
    try:
        yield shim
    finally:
        singbox.ssl = saved


def _trust_our_cert(certfile: str):
    """Patch `singbox.ssl` so the driver's own context accepts our self-signed cert.

    A patched module attribute rather than a driver parameter, deliberately: the
    driver's job is to verify, and a knob to turn that off would be a hole in
    production. The test is asserting the *shape* of the request (TLS, status
    code, body), so what the certificate proves is the platform's business.

    The patch is narrow — `create_default_context` returns a real verifying
    context with one extra CA — so the driver still refuses an untrusted peer,
    which is what keeps the replaced version from becoming the default.
    """
    class _SSL:
        SSLError = ssl.SSLError
        SSLContext = ssl.SSLContext

        @staticmethod
        def create_default_context(*args, **kwargs):
            context = ssl.create_default_context(*args, **kwargs)
            context.load_verify_locations(certfile)
            return context

    return _SSL


async def _tls_socks_peer(status_line: bytes, body: bytes, certfile: str):
    """A SOCKS peer that upgrades to TLS and then says exactly `status_line`.

    The upgrade is the point: the driver now calls `start_tls`, so a peer that
    does not upgrade fails at the handshake instead of at the status line, and
    the test cannot pass by accident because the driver stopped speaking TLS.

    Every byte count here is the one `_socks_connect` on the client side
    consumes — the 10-byte CONNECT reply, the 2-byte greeting reply — because a
    peer that answers with more leaves the surplus in the stream to be read as
    the start of the TLS handshake, which the client reports as a reset
    connection that looks exactly like a handshake failure.
    """

    async def _serve(reader, writer):
        try:
            await _greet(reader, writer)
            head = await reader.readexactly(4)
            atyp = head[3]
            if atyp == 0x01:
                await reader.readexactly(4)
            elif atyp == 0x03:
                length = (await reader.readexactly(1))[0]
                await reader.readexactly(length)
            else:
                await reader.readexactly(16)
            await reader.readexactly(2)
            writer.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
            await writer.drain()
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile)
            await writer.start_tls(context)
            payload = status_line + b"\r\nContent-Length: " + str(len(body)).encode() \
                + b"\r\nConnection: close\r\n\r\n" + body
            writer.write(payload)
            await writer.drain()
        finally:
            with contextlib.suppress(Exception):
                writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    server = await asyncio.start_server(_serve, "127.0.0.1", 0)
    return server.sockets[0].getsockname()[1], server


async def test_the_probe_speaks_tls_and_a_2xx_is_the_verdict(workdir, tmp_path):
    """`socks_check` over a working TLS peer is `True`.

    The peer refuses the connection unless the driver completes a handshake, so
    this is also the regression test for the TLS half: if the driver ever goes
    back to plain HTTP, the handshake fails and the check is `False`.
    """
    body, certfile = b"ok", _self_signed()
    port, server = await _tls_socks_peer(b"HTTP/1.1 200 OK", body, certfile)
    async with server:
        with _patched_ssl(certfile):
            ok = await singbox.SingBoxDriver(workdir=workdir)._socks_roundtrip(
                port, timeout=5.0
            )
    assert ok is True, "a 2xx over TLS should pass"


async def test_the_probe_asks_with_get_because_cloudflare_404s_a_head(workdir, tmp_path):
    """`socks_check` must use GET. Cloudflare answers `HEAD` with `404`.

    This is a production defect pinned down: a whole funnel round measured 0 of
    44 nodes verified, while the same nodes verified 38 of 44 once the method
    was corrected. The 404 is Cloudflare's own behaviour and is reachable
    without any proxy in the path (`curl -I https://cloudflare.com/cdn-cgi/trace
    `), which is why no amount of "the node must be healthy" reasoning finds it
    — the probe was asking a question whose answer is always "no".

    The peer here answers `HEAD` with 404 and `GET` with 200, exactly like the
    real endpoint. A driver that sends HEAD therefore fails through the honest
    status code rather than because the peer dislikes the method.
    """
    certfile = _self_signed()
    port, server = await _method_aware_peer(certfile, method="GET")
    async with server:
        with _patched_ssl(certfile):
            ok = await singbox.SingBoxDriver(workdir=workdir)._socks_roundtrip(
                port, timeout=5.0
            )
    assert ok is True, (
        "socks_check sent HEAD; Cloudflare answers HEAD /cdn-cgi/trace with 404, "
        "so every node measures dead"
    )


async def test_a_400_is_not_a_success_even_though_it_looks_like_one(workdir, tmp_path):
    """The defect itself, as a test: Cloudflare's `400` must fail.

    `400 Bad Request` begins a perfectly valid HTTP response, which is exactly
    what fooled the old `line.startswith(b"HTTP/")`. If a future change makes
    the check accept any status again, this is the test that says so.
    """
    body, certfile = b"<html>The plain HTTP request was sent to HTTPS port</html>", _self_signed()
    port, server = await _tls_socks_peer(b"HTTP/1.1 400 Bad Request", body, certfile)
    async with server:
        with _patched_ssl(certfile):
            ok = await singbox.SingBoxDriver(workdir=workdir)._socks_roundtrip(
                port, timeout=5.0
            )
    assert ok is False, "a 400 must not count as a working node"


async def test_a_redirect_is_not_a_success_either(workdir, tmp_path):
    """`301` to https, which is what `http://…/cdn-cgi/trace` now returns.

    Following the redirect was never an option for a `HEAD`, and a redirect is
    not a measurement: the body it hands back is the redirect page.
    """
    certfile = _self_signed()
    port, server = await _tls_socks_peer(b"HTTP/1.1 301 Moved Permanently", b"", certfile)
    async with server:
        with _patched_ssl(certfile):
            ok = await singbox.SingBoxDriver(workdir=workdir)._socks_roundtrip(
                port, timeout=5.0
            )
    assert ok is False


async def test_the_trace_reads_loc_out_of_a_real_tls_body(workdir, tmp_path):
    """`loc`/`colo` come back from a body the driver actually read.

    This is the country half of the defect: 70 nodes were published with an
    empty `country` column because the body was never readable. The peer is
    TLS and the status is 2xx, so anything short of a parsed `loc=US` means the
    trace path is still not reading what the node said.
    """
    body = b"fl=1\nh=cloudflare.com\nip=104.18.0.1\nts=1\nvisit_scheme=https\n" \
           b"uag=\ncolo=IAD\nsliver=none\nhttp=http/1.1\nloc=US\ntls=TLSv1.3\n" \
           b"sni=off\nwarp=off\ngateway=off\rbi=off\nkex=X25519\n"
    certfile = _self_signed()
    port, server = await _tls_socks_peer(b"HTTP/1.1 200 OK", body, certfile)
    async with server:
        with _patched_ssl(certfile):
            got = await singbox.SingBoxDriver(workdir=workdir)._trace_over(
                port, timeout=5.0
            )
    assert got is not None, "the body should have been read"
    assert got["loc"] == "US", got
    assert got["colo"] == "IAD", got


async def test_a_refused_body_yields_no_country_rather_than_a_guess(workdir, tmp_path):
    """A non-2xx body must not be parsed for a country.

    Conflating "the node answered" with "the node answered usefully" is how a
    pool ends up with a `loc` that came from an error page.
    """
    body, certfile = b"<html><title>400 Bad Request</title></html>", _self_signed()
    port, server = await _tls_socks_peer(b"HTTP/1.1 400 Bad Request", body, certfile)
    async with server:
        with _patched_ssl(certfile):
            got = await singbox.SingBoxDriver(workdir=workdir)._trace_over(
                port, timeout=5.0
            )
    assert got is None, got


def test_the_status_check_accepts_only_2xx():
    """Unit-level pin on `_is_ok_status`, so the three cases cannot drift.

    Written directly against the helper rather than through a network peer,
    because a test per status through the socket would each need a server; and
    the interesting cases (`400`, `301`, `500`, unparseable) are all things this
    helper must refuse.
    """
    assert singbox._is_ok_status("HTTP/1.1 200 OK")
    assert singbox._is_ok_status("HTTP/1.1 204 No Content")
    assert not singbox._is_ok_status("HTTP/1.1 301 Moved Permanently")
    assert not singbox._is_ok_status("HTTP/1.1 400 Bad Request")
    assert not singbox._is_ok_status("HTTP/1.1 403 Forbidden")
    assert not singbox._is_ok_status("HTTP/1.1 500 Internal Server Error")
    # Unreadable is not success. This is the same asymmetry the isolation gate
    # in `hub.cli` turned on: "cannot tell" must be the refusal.
    assert not singbox._is_ok_status("garbage")
    assert not singbox._is_ok_status("")
    assert not singbox._is_ok_status("HTTP/1.1")


async def test_the_response_reader_splits_the_status_line_from_the_body():
    """`_read_response` on a canned response.

    The split is by the header terminator, not by a fixed offset, so a server
    that sends extra headers still yields a body rather than a truncated one.
    """
    raw = (b"HTTP/1.1 200 OK\r\nServer: cloudflare\r\nContent-Length: 5\r\n"
           b"Connection: close\r\n\r\nip=1.2.3.4")
    status, body = await singbox._read_response(_FakeReader(raw))
    assert status == "HTTP/1.1 200 OK", status
    assert body == b"ip=1.2.3.4", body
    assert await singbox._read_response(_FakeReader(b"")) is None


class _FakeReader:
    """Just enough `asyncio.StreamReader` for `_read_response`."""

    def __init__(self, blob: bytes):
        self._blob = blob

    async def read(self, _n: int = -1) -> bytes:
        blob, self._blob = self._blob, b""
        return blob


async def test_the_speed_reader_upgrades_and_yields_the_body(workdir, tmp_path):
    """`speed_read` over an https URL reads the body over TLS.

    The third survivor of the original defect: `speed_read` sent plain HTTP to
    `https://speed.cloudflare.com/__down`, whose 443 answers with the small
    `400 ... HTTPS port` page. A page that small arrives in microseconds, so a
    dead node would have measured as a *fast* one — the exact inversion of the
    truth, which is worse than a failure because the ranking trusts it.

    The peer is TLS, so a driver that stops upgrading fails the handshake and
    yields nothing rather than something wrong.
    """
    body = b"\x00" * 4096
    certfile = _self_signed()

    async def _serve(reader, writer):
        await _greet(reader, writer)
        head = await reader.readexactly(4)
        atyp = head[3]
        if atyp == 0x01:
            await reader.readexactly(4)
        elif atyp == 0x03:
            length = (await reader.readexactly(1))[0]
            await reader.readexactly(length)
        await reader.readexactly(2)
        writer.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
        await writer.drain()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile)
        await writer.start_tls(context)
        request = await reader.readuntil(b"\r\n\r\n")
        # The line up to CRLF, so the query is *pinned* rather than substring-
        # matched. `b"GET /__down" in request` passed whether or not the query
        # was there — `/__down` is a prefix of `/__down?bytes=4096` — which is
        # how the size parameter stayed dropped through a passing test. A
        # request line with no `?bytes=` asks Cloudflare for an unbounded
        # transfer, and the answer is nothing to measure.
        request_line = request.split(b"\r\n", 1)[0]
        assert request_line == b"GET /__down?bytes=4096 HTTP/1.1", request_line
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode()
            + b"\r\nConnection: close\r\n\r\n" + body
        )
        await writer.drain()
        # Close, so the response terminates. `_read_head` stops at the header
        # terminator and does not need this, but the `async for` that follows
        # ends on EOF, and a peer that holds the socket open leaves the reader
        # waiting for a close that never comes — a timeout that is not a defect.
        # This test asserts the *byte total* on a body that arrives complete,
        # which is the one case where the pre-fix head read behaved identically
        # (262144 bytes either way; the difference was the first byte's timing,
        # which is what the stalling-peer test below measures).
        writer.close()

    server = await asyncio.start_server(_serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        driver = singbox.SingBoxDriver(workdir=workdir)
        await driver.start()
        driver.entries["t"] = singbox._Entry(tag="t", node=None, port=port)
        with _patched_ssl(certfile):
            got = b""
            async for chunk in driver.speed_read(
                "t", "https://speed.cloudflare.com/__down?bytes=4096", timeout=5.0
            ):
                got += chunk
    assert got == body, (len(got), len(body))


async def test_a_live_but_slow_node_is_measured_not_timed_out(workdir, tmp_path):
    """The head read must not wait for the body to finish before its first byte.

    The scenario the *pre-fix* code failed, measured on this host rather than
    reasoned about. A peer that answers `200 OK` with `Content-Length: 4194304`,
    trickles 3 MiB, then holds the connection open without closing — a live node
    that is simply slow, which is what most real nodes are.

    Driving `speed_read` with the old `_read_response` head read:

        old: timeout after 12 s, moved = 0, measured = False
        new: first chunk at 0.001 s, moved = 1048576, bps = 6553600

    Three claims, in order of how easy they are to get wrong:

    1. **the byte count is the same either way when the body completes.** An
       earlier version of this fix claimed the old code lost the bytes entirely
       (`moved == 0`, "nothing left to yield"). It did not: `_read_response`
       returns the whole body as `body_so_far` and the old `speed_read` yielded
       it, so a body that arrives complete and then closes measured *identically*
       — 262144 bytes, in one chunk instead of five. That claim was tested and
       refuted, and the docstring that made it has been corrected. A test that
       asserted only "bytes arrive" would have passed both before and after.
    2. **what the old code actually cost was the first byte, and therefore the
       whole window.** It read the head to EOF, so the consumer's `async for`
       had nothing to iterate until the connection closed. `SpeedChecker` closes
       its window on `MIN_WINDOW_BYTES` (1 MiB) or `timeout_s` (12 s); here the
       peer never closes, so the old path burned all 12 s and returned
       `bytes_moved=0` — the exact "no bytes" bucket the run report showed for
       25 live nodes, with `speed.measured: 0` behind it.
    3. **so the assertion that discriminates is on elapsed time, not on bytes.**
       A passing old implementation cannot get a first byte before EOF arrives.

    The consumer's own loop is reproduced verbatim (count, then break on the
    1 MiB / 12 s bounds) rather than calling `SpeedChecker`, because the checker
    builds its own https URL and would make both arms hang in `start_tls` — a
    timeout that says nothing about the head read. The URL here is plain http
    for exactly that reason, which is why this test is about the head read and
    not about the TLS upgrade the neighbouring test covers.
    """
    body = 3_145_728  # 3 MiB, then the peer stalls — most of a 4 MiB window

    async def _serve(reader, writer):
        await _greet(reader, writer)
        head = await reader.readexactly(4)
        atyp = head[3]
        if atyp == 0x01:
            await reader.readexactly(4)
        elif atyp == 0x03:
            length = (await reader.readexactly(1))[0]
            await reader.readexactly(length)
        await reader.readexactly(2)
        writer.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")
        promised = 4_194_304
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: " + str(promised).encode()
            + b"\r\nConnection: close\r\n\r\n"
        )
        await writer.drain()
        chunk = b"\x00" * 65536
        sent = 0
        while sent < body:
            writer.write(chunk)
            await writer.drain()
            sent += len(chunk)
            await asyncio.sleep(0.01)
        await asyncio.sleep(30)  # live, stalled, never closes

    server = await asyncio.start_server(_serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        driver = singbox.SingBoxDriver(workdir=workdir)
        await driver.start()
        driver.entries["t"] = singbox._Entry(tag="t", node=None, port=port)
        try:
            moved = 0
            first_chunk_at = None
            started = time.monotonic()
            async for piece in driver.speed_read(
                "t", "http://speed.cloudflare.com/__down?bytes=4194304",
                timeout=12.0,
            ):
                if piece:
                    if first_chunk_at is None:
                        first_chunk_at = time.monotonic() - started
                    moved += len(piece)
                if moved >= 1_048_576 or time.monotonic() - started >= 12.0:
                    break
            elapsed = time.monotonic() - started
        finally:
            await driver.stop()

    # The first byte must not wait on the transfer finishing.
    assert first_chunk_at is not None, "no bytes at all, for a node that sent 3 MiB"
    assert first_chunk_at < 1.0, f"first byte took {first_chunk_at:.2f}s"
    # ...and the window must therefore close on the volume bound, not the clock.
    assert moved >= 1_048_576, f"only {moved} bytes before the window closed"
    assert elapsed < 12.0, f"burned the whole {elapsed:.1f}s clock"


async def test_a_refusal_is_not_a_fast_node(workdir, tmp_path):
    """A non-2xx head yields nothing, even with a body behind it.

    The other half of the same fix, and the reason `_read_head` returns a status
    line at all. A `301` or `400` arrives with a full `Content-Length` and a real
    body, so a reader that checked nothing would record the error page as
    throughput — the dead-node-measured-as-fast inversion `_is_ok_status` exists
    to prevent, now reachable again the moment the head and the body are read by
    the same call.

    The `301` specifically, not `400`: a redirect is the case where the body is
    largest and most plausibly mistaken for payload, and it is the status a CDN
    actually returns when the speed path is wrong.
    """
    body = b"<html><body>Moved Permanently</body></html>" * 64

    async def _serve(reader, writer):
        await _greet(reader, writer)
        head = await reader.readexactly(4)
        atyp = head[3]
        if atyp == 0x01:
            await reader.readexactly(4)
        elif atyp == 0x03:
            length = (await reader.readexactly(1))[0]
            await reader.readexactly(length)
        await reader.readexactly(2)
        writer.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 301 Moved Permanently\r\n"
            b"Content-Length: " + str(len(body)).encode()
            + b"\r\nLocation: https://example.com/\r\n"
            b"Connection: close\r\n\r\n" + body
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(_serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        driver = singbox.SingBoxDriver(workdir=workdir)
        await driver.start()
        driver.entries["t"] = singbox._Entry(tag="t", node=None, port=port)
        try:
            moved = 0
            async for piece in driver.speed_read(
                "t", "http://speed.cloudflare.com/__down?bytes=262144",
                timeout=5.0,
            ):
                moved += len(piece)
        finally:
            await driver.stop()

    assert moved == 0, f"a refusal handed the consumer {moved} bytes to measure"


async def test_concurrent_add_nodes_leave_no_orphan_processes(workdir, tmp_path):
    """No child outlives its node, under the concurrency the prober uses.

    `Prober` runs the HTTP stage with `limits.http` in flight — 100 by default
    — and every one of those calls `add_node`. Two failure modes matter here,
    and this test is aimed at the one that a *wrong* design produced first:

    - a design that shares one process and kills it per `add_node` leaks
      orphans with `PPID=1` still holding ports (269 of them in one real run,
      which stalled the round at 1% CPU);
    - a design that spawns per node and forgets to reap leaks them from the
      driver instead.

    Both are the same observable — children that are alive after `stop()` — so
    it is read out of `/proc`, not from driver bookkeeping: the leak was of
    children asyncio had already forgotten, which is why the driver's own
    `_procs` could not see it.

    The nodes are added and removed the way `Prober._http` does it — add, then
    remove in a `finally` — so reaping is exercised under concurrency rather
    than only at teardown.
    """
    driver = singbox.SingBoxDriver(workdir=workdir, startup_timeout=5.0)
    await driver.start()
    node = _ss()

    async def _spin(i: int) -> None:
        try:
            await driver.add_node(node, f"t{i}")
        except Exception:  # noqa: BLE001
            pass
        await driver.remove_node(f"t{i}")

    try:
        await asyncio.gather(*[_spin(i) for i in range(20)])
    finally:
        await driver.stop()
        await asyncio.sleep(0.2)

    survivors = await _children_pids()
    assert not survivors, f"driver leaked children: {survivors}"


async def _children_pids() -> list[int]:
    """PIDs whose parent is this test process.

    Read from `/proc` rather than from the driver's bookkeeping, because both
    leaks this file has had were of *children asyncio had already forgotten* —
    the resident-process design killed a process it no longer held a reference
    to, leaving it re-parented to PID 1 and still listening.
    """
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="utf-8") as fh:
                fields = fh.read().rsplit(")", 1)[1].split()
            ppid = int(fields[1])
        except (OSError, ValueError, IndexError):
            continue
        if ppid == os.getpid():
            found.append(int(entry))
    return found


async def _port_accepts(port: int) -> bool:
    """Does anything accept on this loopback port? Sends nothing."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=2.0
        )
    except OSError:
        return False
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    return True


async def _silent_after_connect_peer():
    """A SOCKS5 peer that accepts the CONNECT and then goes silent forever.

    This is the node that ended a production round. It is built to reproduce
    the *exact* condition that wedges `_http_over_socks`, and it does so
    without any network but loopback:

    1. it completes the RFC 1928 greeting and the CONNECT reply, so the
       driver starts a TLS handshake whose completion is on the peer — and the
       peer never sends one byte of it;
    2. it stops reading, so the client's `start_tls` bytes sit in the socket
       buffer and the client's write side stalls once those fill.

    The client's `asyncio.wait_for(start_tls, timeout)` then cancels a
    transport that is **paused with an undrained write buffer**. On that state
    `_SelectorSocketTransport.close` (`asyncio/selector_events.py:867`) only
    removes the reader — with a non-empty buffer it never schedules
    `connection_lost`, so the `StreamReaderProtocol._closed` future that
    `wait_closed()` awaits is never resolved and the `finally` never returns.

    The earlier mocks all *answered*, and an answering peer lets `close()` take
    the empty-buffer branch and fire `connection_lost` immediately — which is
    why the first two attempts at reproducing this with a scripted peer agreed
    the theory was wrong. Only a peer that stops talking reproduces it, so
    this peer stops talking.
    """
    async def _serve(reader, writer):
        with contextlib.suppress(Exception):
            greeting = await reader.readexactly(2)
            await reader.readexactly(greeting[1])
            writer.write(b"\x05\x00")
            await writer.drain()
            head = await reader.readexactly(4)
            atyp = head[3]
            if atyp == 0x01:
                await reader.readexactly(4)
            elif atyp == 0x03:
                await reader.readexactly((await reader.readexactly(1))[0])
            else:
                await reader.readexactly(16)
            await reader.readexactly(2)
            # CONNECT granted — the driver now believes it has a tunnel.
            writer.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
            await writer.drain()
            # And then nothing. No TLS, no EOF, no read. Ever.
            await asyncio.sleep(3600)

    server = await asyncio.start_server(_serve, "127.0.0.1", 0)
    return server.sockets[0].getsockname()[1], server


async def test_a_silent_peer_cannot_hold_the_round_open(tmp_path, monkeypatch):
    """`socks_check` against a wedged node must return, not wedge the round.

    This is the regression test for the hang that stopped a production run
    three nodes from the end: the funnel reported `errors: {http: 126}` for the
    nodes it had measured and then simply stopped, with three children still
    listening and the pool unpublished.

    The assertion is a **bounded completion**, not a counted one. Every other
    test in this file asserts what the driver said to the peer; this one
    asserts that it comes back at all. `asyncio.wait_for` around the call is
    the assertion — if the wait in the `finally` is unbounded, the call never
    returns and the test fails with `TimeoutError` rather than a message.

    The mutation that must kill it: an unbounded
    `await writer.wait_closed()` in `_http_over_socks`' `finally`. Nothing else
    can produce this timeout, because the peer only ever speaks SOCKS and the
    TLS upgrade is the first thing that needs its cooperation.
    """
    port, server = await _silent_after_connect_peer()
    try:
        driver = SingBoxDriver(binary="/nonexistent/sing-box", workdir=tmp_path)
        # Registered through `add_node` the way the funnel does, so the call
        # exercises `_await_listening` -> `socks_check` -> `_http_over_socks`
        # rather than short-circuiting on a missing entry. A bare
        # `socks_check("silent")` returns `(False, 0.0)` immediately because
        # there is no such tag, which would make this test pass against the
        # unbounded bug for the wrong reason.
        driver.started = True
        driver.entries["silent"] = _Entry(tag="silent", node=_trojan(), port=port)
        # A short probe timeout so the test's own budget is small: the point is
        # the *shape* (bounded on every path), and 0.4 s makes the bound on
        # teardown unmistakable against the unbounded version's hang.
        started = asyncio.get_running_loop().time()
        try:
            await asyncio.wait_for(
                driver.socks_check("silent", timeout=0.4), timeout=15.0
            )
        except asyncio.TimeoutError:
            pytest.fail(
                "socks_check never returned for a peer that accepted the CONNECT "
                "and then stopped talking: the wait in the driver's finally is "
                "unbounded, which is the hang that cost a production round its "
                "last three nodes. Bound it with _close_writer."
            )
        elapsed = asyncio.get_running_loop().time() - started
        # And the bound has to be the one documented, not merely small: a
        # teardown that is bounded at *zero* would mean the port is never
        # released, which is the adjacent leak. 0.4 s probe + the 2 s close
        # ceiling is the shape the helper promises.
        assert elapsed >= 0.4, f"returned too fast ({elapsed:.2f}s); did the probe even run?"
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(server.wait_closed(), timeout=2.0)
