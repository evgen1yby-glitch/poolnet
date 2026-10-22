"""The CLI entry point.

    python -m hub serve           # FastAPI subscription server
    python -m hub run             # one pipeline run
    python -m hub verify-log      # replay the NDJSON event log
    python -m hub rollback        # repoint to the retained previous generation
    python -m hub stats           # pool and publish health
    python -m hub speedtest       # rank the pool by measured throughput
    python -m hub audit-sources   # re-verify every source, report dead ones
    python -m hub check-parser    # parse the malformed-URI fixture, expect refusals
    python -m hub init            # write the config and data skeleton
    python -m hub bot             # Telegram notifier (needs --channel-id)

Every command exits non-zero on a real failure and prints one line of outcome.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
from pathlib import Path

#: The kernel-owned, per-network-namespace interface table. This is the one the
#: isolation gate reads, and it is a module-level name so a test can point it at a
#: fixture — see `_interface_names` for why an inlined literal was not enough.
_PROC_NET_DEV = Path("/proc/net/dev")

#: The stale sysfs directory, kept only so a test can *disagree* with the above
#: and prove the gate is not reading it. Not used by any code path: on this host
#: it lists the host's interfaces from inside any namespace.
_SYS_CLASS_NET = Path("/sys/class/net")


def _root() -> Path:
    """Project root: the directory containing `src/` and `data/`."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "src" / "hub").is_dir():
            return parent
    return Path.cwd()


def _resolve(value: str | None, default: Path) -> Path:
    if not value:
        return default
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (_root() / candidate)


def build_parser() -> argparse.ArgumentParser:
    """The whole argument table, as an object.

    Split out of `main` so the CLI's surface is inspectable without running a
    subcommand. This is not tidiness: the subcommand list, the `--allow-network`
    default, and which flag maps to which command are all things an operator
    discovers by typing, and "the suite never called `main`" is how a
    subcommand gets documented, added to the docstring, and then left out of
    `choices` — an argparse error at the operator's terminal, invisible here.

    Tests that build this parser directly are the only kind that can assert on
    it, because `main` dispatches as soon as `parse_args` returns.
    """
    parser = argparse.ArgumentParser(prog="hub", description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "serve",
            "run",
            "verify-log",
            "rollback",
            "stats",
            "check-parser",
            "bot",
            "init",
            "speedtest",
            "audit-sources",
        ],
    )
    parser.add_argument("--root", default=os.environ.get("HUB_ROOT", ""))
    parser.add_argument("--sources", default=os.environ.get("HUB_SOURCES", "config/sources.yaml"))
    parser.add_argument("--token", default=os.environ.get("HUB_TOKEN", ""))
    parser.add_argument("--host", default=os.environ.get("HUB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("HUB_PORT", "8090")))
    parser.add_argument(
        "--allow-network",
        action="store_true",
        default=False,
        help=(
            "permit real network probing (requires the sing-box driver binary). "
            "Off by default so `hub run` can never touch the host's live network; "
            "when this is enabled, run the worker inside `ip netns exec hubns` — "
            "a namespace with only `lo` and no route cannot dial anything."
        ),
    )
    parser.add_argument(
        "--channel-id",
        type=int,
        default=int(os.environ.get("HUB_CHANNEL_ID", "0")),
        help="Telegram channel id (negative for channels); required for `bot`",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=40,
        help="rows to print for `speedtest` (default 40)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    root = _resolve(args.root, _root())

    if args.command == "check-parser":
        return _check_parser(root)
    if args.command == "init":
        return _init(root)
    if args.command == "stats":
        return _stats(root)
    if args.command == "serve":
        return _serve(root, args)
    if args.command == "bot":
        return _bot(root, args)
    if args.command == "run":
        return asyncio.run(_run(root, args))
    if args.command == "verify-log":
        return _verify_log(root)
    if args.command == "rollback":
        return _rollback(root)
    if args.command == "speedtest":
        return asyncio.run(_speedtest(root, args))
    if args.command == "audit-sources":
        return _audit_sources(root, args)
    parser.error("unknown command")
    return 2


def _audit_sources(root: Path, args) -> int:
    """Re-verify every source in the config and report which yield nothing.

    A thin wrapper over `scripts/audit_sources.py`, which is where the logic
    lives. It is a subcommand rather than a separate script because it belongs
    in the deploy cadence: a source list rots silently, and a timer is the only
    thing that notices without an operator remembering to ask.

    Read-only by construction — no driver is constructed, no node is dialled,
    and nothing under `data/` is touched, so it is safe to run on the live host.
    """
    import importlib.util
    from pathlib import Path as _Path

    script = _root() / "scripts" / "audit_sources.py"
    if not script.exists():
        print(f"audit: {script} not found", file=sys.stderr)
        return 2
    spec = importlib.util.spec_from_file_location("audit_sources", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    sys.argv = [
        str(script),
        "--config",
        str(_resolve(args.sources, _root() / "config" / "sources.yaml")),
    ]
    return int(module.main())


def _parse_source_texts(sources_path: Path) -> tuple[dict, dict]:
    """Load the two config files that are allowed to be missing.

    The sources file contributes *both* the list and the knobs that sit beside
    it, because `Pipeline` and `create_app` read all of them from one mapping.
    Building `{"sources": [...]}` and nothing else is what made `canary_token`,
    `base_url`, `source_pass_rate` and `protocol_reliability` unreachable: the
    pipeline then read its own defaults and nobody was told the config had been
    half-ignored.
    """
    sources: dict = {}
    scoring: dict = {}
    if sources_path.exists():
        from hub.fetcher import load_sources

        entries, settings = load_sources(sources_path)
        sources = {"sources": [s.__dict__ for s in entries], **settings}
    scoring_path = sources_path.parent / "scoring.yaml"
    if scoring_path.exists():
        from hub.scorer import Weights

        scoring = {"weights": Weights().__dict__}
    return sources, scoring


def _serve(root: Path, args) -> int:
    try:
        import uvicorn
    except ImportError:  # pragma: no cover
        print("uvicorn is not installed; pip install -r requirements.txt", file=sys.stderr)
        return 1
    from hub.api import create_app

    sources, _ = _parse_source_texts(_resolve(args.sources, root / "config" / "sources.yaml"))
    app = create_app(store=None, sources=sources)
    print(f"serving on http://{args.host}:{args.port} (token via HUB_TOKEN)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=False)
    return 0


async def _run(root: Path, args) -> int:
    from hub.pipeline import Pipeline, _default_geo_lookup
    from hub.speedtest import SpeedPolicy

    sources, _ = _parse_source_texts(_resolve(args.sources, root / "config" / "sources.yaml"))
    driver_factory, why = _driver_factory(args)
    if driver_factory is None and getattr(args, "allow_network", False):
        # Named, not silent. An operator who asked for probing and did not get
        # it has to be told, or the run reports `0 verified` and looks like a
        # round where every node happened to be dead.
        print(f"no driver this run: {why}")
    # Geo-IP is enabled only for a networked run, and only when the operator has
    # not turned it off. It exists to name the nodes the probe could not place —
    # the probe's own answer comes from the node and always wins — and it is off
    # for a run that cannot probe anyway, because a country resolver on a run
    # that publishes nothing is an outbound request for no result.
    allow_network = bool(getattr(args, "allow_network", False))
    geo = None
    if allow_network and os.environ.get("HUB_GEO_LOOKUP", "1").lower() not in ("0", "off", "no"):
        geo = _default_geo_lookup

    pipeline = Pipeline(
        root=root,
        sources=sources,
        network=allow_network,
        driver_factory=driver_factory,
        speed_policy=_speed_policy_from_env(),
        geo_lookup=geo,
        # One probe interval. A check older than a full re-check cycle is
        # evidence about the past, not about now.
        recent_hours=int(os.environ.get("HUB_RECENT_HOURS", "8") or 0),
    )
    if driver_factory is None:
        print(
            "driver absent (network disabled) — 0 verified, previous generation kept. "
            "Pass --allow-network to probe nodes, and run it inside"
            " `ip netns exec hubns` (see deploy/hub-probe.service)."
        )
    report = await pipeline.run_once()
    print(
        f"run {report['run_id']}: "
        f"{report['nodes_raw']} raw -> {report['nodes_verified']} verified -> "
        f"{report['published']} published "
        f"({'new generation ' + report['generation'] if report['generation'] else 'kept previous'})"
    )
    return 0 if not report.get("fatal") else 1


def _speed_policy_from_env():
    """A `SpeedPolicy` with the operator's two knobs, from the environment.

    `HUB_MAX_LOAD` and `HUB_TOP_N` exist because the throughput stage is
    otherwise *unreachable* on a shared box. Its load guard is per-core and
    deliberately conservative (0.85), and a box running an operator desktop,
    a browser and a VM sits at 1.5-2.5 per-core forever — so every round
    defers, `speed.measured` is 0, and the ranking the operator asked to be
    speed-prioritised ("в приоритете с наибольшей скоростью VPN") is ranked on
    half-credit throughput without any measurement ever happening.

    That is the guard working correctly, not a failure: measuring throughput on
    a saturated box measures the co-tenant. But a guard that can never be
    satisfied is a feature that is off, so the two knobs that make it
    *reachable* — how busy is too busy, and how many nodes to measure — are
    operator-settable rather than hardcoded.

    Unset or unparseable means the defaults, and unparseable is silent on
    purpose: a typo in an optional override must not kill a probe run that
    would otherwise have worked. The run report still records the deferral
    reason, so a round that measured nothing is visible either way.
    """
    from dataclasses import replace

    from hub.speedtest import SpeedPolicy

    policy = SpeedPolicy()
    raw_load = os.environ.get("HUB_MAX_LOAD", "").strip()
    raw_top = os.environ.get("HUB_TOP_N", "").strip()
    try:
        if raw_load:
            # `None` is a real, meaningful value: it disables the guard outright,
            # which is how an operator says "I know this box is busy, measure
            # anyway". Everything else is parsed as a float.
            policy = replace(
                policy,
                max_load=None if raw_load.lower() in ("none", "off") else float(raw_load),
            )
        if raw_top:
            policy = replace(policy, top_n=int(raw_top))
    except ValueError:
        return SpeedPolicy()
    return policy


def _driver_factory(args) -> tuple[object | None, str]:
    """A `(factory, reason)` pair; a `None` factory comes with its reason.

    Three guards, in the order they must be checked:

    1. **the flag.** `--allow-network` is what makes the pipeline probe at all;
       without it there is no factory and `Pipeline` reports `driver: absent`.
    2. **the gate.** Probing is the only stage that can carry the host's own
       traffic, so it must already be inside a network namespace. The check is
       "which namespace am I in", and it is refused loudly rather than skipped:
       on the live network a probed node is a live leak. Note that this asks
       nothing about whether a namespace *could* be created — see `_is_isolated`.
    3. **the binary.** No `sing-box` and there is nothing to speak SOCKS5 to.

    The reason is returned rather than printed because a factory that is absent
    for the wrong-stated cause sends an operator to fix the wrong thing — and
    "no sing-box binary" is the wrong thing when the real answer is "this box
    cannot isolate". `_run` prints it, which is also why it is a single message
    and not a stream of refusals.

    A *factory* is returned rather than an instance because `Pipeline` owns when
    the driver is created, and creating one per run keeps a crashed child from
    surviving into the next.
    """
    if not getattr(args, "allow_network", False):
        return None, "network probing disabled; pass --allow-network to enable it"
    isolated, why_not = _is_isolated()
    if not isolated:
        return None, why_not
    from hub.singbox import SingBoxUnavailable, find_binary

    if find_binary() is None:
        return None, (
            "sing-box was not found on PATH and SINGBOX_BIN is unset; "
            "install sing-box or set SINGBOX_BIN, then re-run"
        )

    def factory():
        from hub.singbox import SingBoxDriver

        try:
            return SingBoxDriver()
        except SingBoxUnavailable:
            # Caught here rather than raised, because a missing binary is not a
            # crash: the run proceeds and reports 0 verified, which is honest.
            # Raising would abort the whole run over a missing optional dep.
            return None

    return factory, "sing-box driver ready"


def _is_isolated() -> tuple[bool, str]:
    """Am I *actually* inside a network namespace that is not the host's?

    One question, and the wording is the fix. This used to ask "am I isolated,
    or could isolating still be done?" and answered `True` to both — which made
    the return value useless for the one caller that depended on it. A process
    running on the host's live network was told `(True, "probing can be […]
    isolated")`, i.e. *not isolated*, and any unit that trusted the boolean
    would probe through eth0. Verified on this host:

        host netns, as astrobot:  (True, 'probing can be isolated with `unshare -rn`')

    A safety gate whose `True` means "this would be fine if someone had bothered"
    is worse than no gate: it converts the one state that must fail into a pass.

    So the second question is gone. Whether a namespace *could* be created is a
    question for the code that is about to create one, and the caller of *this*
    function is not that code — it is asking for permission to touch the host's
    network, and the only honest answer is the one about the current namespace.

    "Actually isolated" is two tests, in this order, because each catches what
    the other cannot:

    1. **A managed namespace, by inode.** `/run/netns/*` holds one bind mount per
       namespace created with `ip netns add`, and those files are world-readable
       even though `/proc/*/ns/net` is not. So the netns's own inode number can be
       read and compared: if `/proc/self/ns/net` matches `/run/netns/hubns`, the
       process is inside hubns. This is *identification*, not inference — it names
       the namespace rather than guessing from its traffic-shaped properties.
       That matters: `hubns` has a veth and a default route (it can probe), while a
       `unshare -rn` namespace has neither. An interface-list heuristic reports
       those two differently only by accident, and reports any *other* managed
       namespace identically.
    2. **No host interfaces, as a fallback.** A namespace made by `unshare -rn` or
       `PrivateNetwork=yes` has no bind mount in `/run/netns`, so the first test
       cannot see it. Read from `/proc/net/dev`: if the only interface is `lo`,
       there is no external interface and nothing here can reach the host's
       network. That file is per-namespace in the kernel, which is why it is used
       and `/sys/class/net` is not — see `_interface_names`. Deliberately *not*
       read from `/proc/*/ns` inode comparison against `/proc/1`: that path is
       root-owned, an unprivileged reader gets `PermissionError`, and the tempting
       handling of that error (treat it as "same namespace") reports the host as
       isolated — the one false answer that makes a gate actively dangerous.

    The order is not cosmetic. The `lo`-only test is *sound* (an empty namespace
    cannot reach the host), so it may come second; but if a namespace has any
    interface besides `lo` and a route out of it, then only the inode test can
    vouch for it, and it must not have been consulted with a guessed answer. A
    namespace that has a veth and is *not* in `/run/netns` therefore reports "the
    host" here — which is the conservative direction: it refuses.
    """
    # The `lo`-only test first, because it is the one that cannot lie: a namespace
    # with nothing but loopback provably has no path to the host's network.
    interfaces = _interface_names()
    if interfaces and not (interfaces - {"lo"}):
        return True, f"inside a private network namespace (only {sorted(interfaces)})"
    # Anything with an external interface is ambiguous, and ambiguity is exactly
    # where guessing must not happen. Name it by inode or refuse.
    named = _named_netns()
    if named:
        return True, f"inside a managed network namespace ({named})"
    return False, (
        "probing would use the host's live network"
        + (
            f" ({sorted(interfaces)} visible)"
            if interfaces
            # Said as a refusal with no evidence, not as an observation about a
            # namespace: an empty list here means "could not read", which is a
            # different claim from "there is nothing here", and the two must not
            # produce the same sentence. The gate is refusing because it cannot
            # prove isolation, and that is what an operator has to be told.
            else " (no interface table visible — /proc/net/dev unreadable?)"
        )
        + "; re-run inside an isolated namespace with an uplink —"
        " `ip netns exec hubns` (see deploy/hubns-ensure.sh)"
    )


def _isolation_method() -> str | None:
    """How this box can isolate a probe, or `None` if it cannot.

    No production caller: the permission gate is `_is_isolated`, which asks about
    the *current* namespace, and that is the only question the run path needs.
    This is kept for its two helpers and for the tests that monkeypatch it to
    prove the gate ignores it. Do not read its ranking as advice.

    Three shapes, most usable first:

    1. **`sudo -n ip netns`** — an operator-owned named namespace with an uplink
       attached on purpose, which is the shape `deploy/hubns-ensure.sh` builds and
       `deploy/hub-probe.service` uses. This is the only one of the three that can
       both probe and be *named*, and naming is what makes the gate a fact rather
       than a judgement (see `_named_netns`).
    2. **`sudo -n unshare -rn`** — works where unprivileged user namespaces are
       denied by policy (this server). Isolates completely and safely, but has no
       route and no external interface: a probe run in it completes and verifies 0
       nodes forever while reporting success. Safe is not the same as useful.
    3. **`unshare -rn`** — no privileges needed, but same route-less shape as (2).

    Each is *tested*, not assumed: the method is reported as available only if
    the actual command succeeds, because "sudo exists" and "sudo is passwordless
    for this exact command" are different facts and the second is the one that
    matters at 3am.
    """
    import shutil

    if shutil.which("unshare") is None and shutil.which("ip") is None:
        return None
    probes: list[tuple[str, list[str]]] = [
        ("sudo -n ip netns add", ["sudo", "-n", "ip", "netns", "add", "hub-probe-check"]),
        ("sudo -n unshare -rn", ["sudo", "-n", "unshare", "-rn", "true"]),
        ("unshare -rn", ["unshare", "-rn", "true"]),
    ]
    available: list[str] = []
    for name, argv in probes:
        if _probe_runs(argv):
            available.append(name)
    # The third probe *creates* a namespace as its test, so it must be removed
    # again whether it succeeded or not: a probe that leaves `hub-probe-check`
    # behind turns a capability check into a slow resource leak, and a run that
    # later tries `ip netns add hubns` on a name that exists fails for a reason
    # that has nothing to do with this machine.
    import subprocess

    if any(n.startswith("sudo -n ip netns") for n in available) or _netns_exists(
        "hub-probe-check"
    ):
        with contextlib.suppress(Exception):
            subprocess.run(
                ["sudo", "-n", "ip", "netns", "del", "hub-probe-check"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
    return available[0] if available else None


def _netns_exists(name: str) -> bool:
    """Does a named network namespace already exist?"""
    import subprocess

    try:
        proc = subprocess.run(
            ["ip", "netns", "list"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.split()[0] == name for line in proc.stdout.splitlines() if line.strip())


def _probe_runs(argv: list[str]) -> bool:
    """Does this command succeed right now, without hanging?"""
    import subprocess

    try:
        proc = subprocess.run(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _named_netns() -> str | None:
    """The name of the `ip netns` namespace this process is in, if any.

    `/run/netns/<name>` is a bind mount of exactly one network namespace, so its
    inode *is* the namespace's inode: comparing it to `/proc/self/ns/net` names
    the current namespace rather than inferring it. Verified on this host, as
    unprivileged astrobot:

        inside `ip netns exec hubns`:  mine 4026532270, /run/netns/hubns 4026532270 -> "hubns"
        on the host:                   mine 4026531840, /run/netns/hubns 4026532270 -> None

    Why inodes at all, when `/sys/class/net` is right there: the interface list
    cannot distinguish "host" from "a namespace with an uplink". `hubns` has a
    veth, `unshare -rn` has only `lo`, and both are non-host — a check that
    accepts one and rejects the other based on interfaces is guessing at the
    exact property that decides whether probing is safe. The inode is the
    property itself.

    Returns `None` for an *unnamed* namespace, which is not a bug: those are
    handled by the interface-list fallback in `_is_isolated`. Returns `None` when
    the directory is missing or unreadable too, which is the "cannot tell" case,
    and the caller must treat it as "not isolated" rather than as "isolated" — a
    gate that reads "cannot tell" as a pass inverts.
    """
    import os

    mine: int | None = None
    try:
        mine = os.stat("/proc/self/ns/net").st_ino
    except OSError:
        return None
    for base in (Path("/run/netns"), Path("/var/run/netns")):
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if os.stat(entry).st_ino == mine:
                    return entry.name
            except OSError:
                continue
    return None


def _interface_names() -> set[str]:
    """Names of the interfaces *this network namespace* has, from `/proc/net/dev`.

    The obvious source, `/sys/class/net`, is wrong here and the failure is quiet:
    read inside a freshly-created namespace it still lists the host's `eth0`,
    `docker0` and `veth-hub-br`. That is not a kernel oddity but a mount-order
    one — on this host `/sys` is a read-only bind mount made by the container
    runtime *before* the namespace switch, and `unshare` does not remount sysfs
    for the new namespace (a full runtime does; verified here, the remount is
    refused with `mount: /sys: permission denied`). So `/sys/class/net` reports
    what the mount point shows, which is the host, in every namespace.

    `/proc/net/dev` is per-network-namespace by the kernel's own doing — it is one
    of the proc files whose contents follow `nsproxy->net_ns` rather than the
    mount — so it needs no privilege and no remount. Verified on this host:

        host:            lo eth0 docker0 veth-hub-br
        unshare -rn:     lo
        ip netns hubns:  lo veth-hub

    This function's result is *not* used to decide whether we are on the host any
    more (that is `_named_netns`'s job, and it is exact), because an interface
    list cannot separate "the host" from "some other namespace with an uplink".
    What it is still good for is describing the current namespace and catching the
    bind-mount-less shapes, which are exactly the ones `unshare -rn` makes.

    Empty when no such file can be read, which the caller must treat as "cannot
    tell" rather than as "isolated": a gate that reads "cannot tell" as a pass
    inverts.

    The two paths are module-level constants rather than inlined literals, so a
    test can point them at a fixture. That is not a convenience: with the path
    inlined, the only way to test this function is to monkeypatch the whole thing
    (which every gate test does) and then *nothing pins which file it reads*. A
    mutation that restored `/sys/class/net` passed the entire suite, and this is
    the seam that makes such a mutation visible.
    """
    try:
        text = _PROC_NET_DEV.read_text(encoding="ascii")
    except OSError:
        return set()
    names: set[str] = set()
    for line in text.splitlines()[2:]:
        if ":" not in line:
            continue
        name = line.split(":", 1)[0].strip()
        if name:
            names.add(name)
    return names


def _can_create_netns() -> bool:
    """Would `unshare -rn` succeed here? Never probes anything itself.

    `unshare -rn true` is the direct question: it creates a namespace that has
    a loopback interface and nothing else, then immediately exits. Success
    means the capability is present; failure means either no `unshare`, no
    permission, or a kernel without `CONFIG_USER_NS`, and in all three cases
    probing on the live network is exactly what must not happen.
    """
    import shutil
    import subprocess

    if shutil.which("unshare") is None:
        return False
    try:
        proc = subprocess.run(
            ["unshare", "-rn", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


# --------------------------------------------------------------------------- #
# speedtest
# --------------------------------------------------------------------------- #

#: Sources whose *own* published numbers are worth ranking on, even though
#: their payloads cannot become share URIs. VPN Gate measures ping and
#: throughput per server, so it is the one source that answers "which of these
#: is fastest" without us transferring a byte.
_RANKABLE = ("vpngate",)


async def _speedtest(root: Path, args) -> int:
    """Rank the unfetchable sources by their own measured throughput.

    This is the direct answer to "как можно тестировать скорость VPN?" for the
    OpenVPN/SoftEther families: we do **not** transfer anything. VPN Gate
    publishes `Ping` and `Speed` (bytes/second) per server, so ranking is a
    sort over data the source already measured, at the cost of one HTTP GET.

    The share-URI pool is the opposite case — there the number has to be
    *measured*, and `hub.speedtest.SpeedChecker` does that over a node's own
    SOCKS port with a byte ceiling and a host-load guard. The two are kept
    apart on purpose: treating a source's claim as a measurement is how a
    ranking ends up certifying nodes nobody ever connected to.
    """
    from hub.adapters import parse_vpngate_csv
    from hub.fetcher import Source, load_sources

    sources_path = _resolve(args.sources, root / "config" / "sources.yaml")
    entries, _settings = load_sources(sources_path)
    entries = [s for s in entries if s.kind in _RANKABLE]
    if not entries:
        print(f"no rankable source in {sources_path} (expected kind: {', '.join(_RANKABLE)})")
        return 1

    limit = int(getattr(args, "top", 40) or 40)
    rows_all: list[dict] = []
    for source in entries:
        body = await _fetch_body(source)
        if not body:
            print(f"{source.key}: fetch failed", file=sys.stderr)
            continue
        rows = parse_vpngate_csv(body)
        print(f"{source.key}: {len(rows)} servers, {len({r.get('CountryShort','') for r in rows})} countries")
        rows_all.extend(rows)

    if not rows_all:
        print("nothing to rank")
        return 1

    ranked = _rank_by_source_numbers(rows_all)
    print(f"\nTop {min(limit, len(ranked))} of {len(ranked)} by the source's own measured speed:")
    print(f"  {'country':<8}{'ip':<18}{'ping':>7}{'mbps':>10}{'sessions':>10}  host")
    for row in ranked[:limit]:
        # A missing ping prints as "?" rather than crashing the table: a server
        # the source never timed is still worth showing.
        ping = "-" if row["ping"] is None else f"{row['ping']:.0f}"
        print(
            f"  {row['country']:<8}{row['ip']:<18}{ping:>7}"
            f"{row['mbps']:>10.1f}{row['sessions']:>10}  {row['host']}"
        )
    return 0


def _rank_by_source_numbers(rows: list[dict]) -> list[dict]:
    """Sort VPN Gate rows by the throughput the source itself measured.

    `Speed` is bytes/second and can be `0`, `-`, or empty on a row the source
    never got a measurement for; those sort last rather than being read as
    zero-speed servers, because "never measured" and "measured at 0" rank in
    opposite directions for anyone reading the table.
    """
    out = []
    for row in rows:
        raw_speed = (row.get("Speed") or "").strip()
        raw_ping = (row.get("Ping") or "").strip()
        try:
            speed = float(raw_speed)
        except ValueError:
            speed = None
        try:
            ping = float(raw_ping)
        except ValueError:
            ping = None
        out.append(
            {
                "country": (row.get("CountryShort") or "").strip() or "??",
                "ip": (row.get("IP") or "").strip(),
                "host": (row.get("HostName") or "").strip(),
                "sessions": int(row.get("NumVpnSessions") or 0),
                "speed": speed,
                "mbps": (speed or 0.0) / 1_000_000.0,
                "ping": ping,
            }
        )
    # Unmeasured last, then descending speed, then ascending ping as the
    # tie-break so two servers at the same throughput are ordered by the
    # cheaper one to reach.
    out.sort(key=lambda r: (r["speed"] is None, -(r["speed"] or 0.0), r["ping"] if r["ping"] is not None else 1e9))
    return out


async def _fetch_body(source: Source) -> str:
    """One GET of a source body, using the project's own fetcher."""
    from hub.fetcher import Fetcher

    fetcher = Fetcher([source])
    items, _stats = await fetcher.fetch_all()
    return items[0].body if items else ""


class _AiogramTransport:
    """Adapts a real `aiogram.Bot` to the gate's `BotTransport` protocol.

    Only two methods are needed, and the gate is the only consumer, so the
    adapter stays deliberately tiny. It is defined here so `hub bot` works
    without importing aiogram at module load — the import happens lazily.
    """

    def __init__(self, config) -> None:
        from hub.bot import BotConfig  # local import, no cycle

        if not isinstance(config, BotConfig):  # pragma: no cover - type guard
            raise TypeError("expected BotConfig")
        try:
            from aiogram import Bot
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("aiogram is required in real bot mode") from exc
        self.bot = Bot(token=config.token)

    async def get_chat_member(self, chat_id: int, user_id: int) -> str:
        member = await self.bot.get_chat_member(chat_id, user_id)
        return str(getattr(member, "status", ""))

    async def get_me(self):
        me = await self.bot.get_me()
        return {"id": me.id, "is_bot": me.is_bot, "first_name": me.first_name}


def _check_parser(root: Path) -> int:
    from hub.parser import parse_one

    ok = 0
    bad = 0
    for line in (root / "tests" / "fixtures" / "valid_uris.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        node, error = parse_one(line)
        if node is None:
            bad += 1
            print(f"  FAIL {line[:60]}: {error}")
        else:
            ok += 1
    print(f"parser: {ok} ok, {bad} failed")
    return 0 if bad == 0 else 1


def _bot(root: Path, args) -> int:
    """Run the long-poll bot, or the mock transport when no token is set.

    No token means mock mode: same gate, same code, no network. That is the
    state the project ships in until a real @BotFather token is configured.
    """
    from hub.bot import BotConfig, Gate, MockTransport, run_bot

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel_id = args.channel_id
    if not channel_id:
        print("HUB_CHANNEL_ID is required for the bot", file=sys.stderr)
        return 2

    # `HUB_BASE_URL` wins, and the sources file is the fallback. Reading only the
    # variable meant the API — which reads the file — and the bot, which reads
    # the environment, disagreed about the same public address: with it set in
    # `config/sources.yaml` and not exported, the API served absolute links and
    # the bot handed out `/sub/<token>`, a relative path no Telegram user can
    # open. One address, two readers, one of them reading the wrong place.
    base_url = os.environ.get("HUB_BASE_URL", "")
    if not base_url:
        sources, _scoring = _parse_source_texts(root / "config" / "sources.yaml")
        base_url = str(sources.get("base_url", "") or "")
    if token:
        config = BotConfig(token=token, channel_id=channel_id, base_url=base_url)
        gate = Gate(transport=_AiogramTransport(config), channel_id=channel_id)
    else:
        transport = MockTransport()
        config = BotConfig(
            token="", channel_id=channel_id, base_url=base_url, transport=transport
        )
        gate = Gate(transport=transport, channel_id=channel_id)
        print(f"no TELEGRAM_BOT_TOKEN: bot in mock mode, channel {channel_id}")

    run_bot(config, gate)
    return 0


def _init(root: Path) -> int:
    """Create runtime directories and the default config if absent."""
    from hub.store import Store as _Store

    store = _Store(root)
    store.append_event("init", root=str(root))
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    for name in ("sources.yaml", "scoring.yaml"):
        target = config / name
        if not target.exists():
            print(f"missing config/{name} — copy the examples from deploy/ or docs")
    print(f"initialised {store.data}")
    return 0


def _verify_log(root: Path) -> int:
    from hub.store import Store

    store = Store(root)
    if not store.log.exists():
        print("no event log yet")
        return 0
    kinds: dict[str, int] = {}
    runs = 0
    with store.log.open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            kinds[record.get("kind", "?")] = kinds.get(record.get("kind", "?"), 0) + 1
            if record.get("kind") == "run":
                runs += 1
    print(f"event log: {sum(kinds.values())} records, {runs} runs")
    for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {kind:20s} {count}")
    return 0


def _rollback(root: Path) -> int:
    from hub.store import Store

    store = Store(root)
    current = store.current_generation()
    # Same mtime ordering as `Store.retain`: a content-derived generation id
    # does not sort chronologically, so the rollback target must be found by
    # write order, not by name.
    dirs = sorted(
        (p for p in store.generations.iterdir() if p.is_dir()),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    if not dirs:
        print("no generations to roll back to", file=sys.stderr)
        return 1
    target = None
    for path in dirs:
        if path.name != current:
            target = path
            break
    if target is None:
        print("only one generation exists; nothing to roll back to", file=sys.stderr)
        return 1
    manifest_path = target / "manifest.json"
    sha = ""
    if manifest_path.exists():
        sha = json.loads(manifest_path.read_text())["sha256"]
    store.flip_pointer(target.name, sha)
    # Retain with the new pointer live, so the rollback target survives.
    removed = store.retain(3)
    store.append_event(
        "rollback", from_generation=current, to_generation=target.name, removed=removed
    )
    print(f"rolled back {current} -> {target.name}")
    return 0


def _stats(root: Path) -> int:
    from hub.store import Store

    store = Store(root)
    conn = store.connect()
    try:
        rows = conn.execute(
            "SELECT protocol, COUNT(*) AS n, MAX(score) AS best FROM nodes GROUP BY protocol ORDER BY n DESC"
        ).fetchall()
        published = conn.execute(
            # Whole-tier payloads only, and the newest row per generation per
            # tier. `node_count` on a whole-tier row *is* the tier size, so
            # summing across cores/formats would report the same nodes three
            # times, and a country shard is a subset of its tier that would
            # count them again. A shard is the row whose `core` is `cc:XX` (see
            # `Pipeline._publish`), so "not a shard" is the predicate —
            # `core != ''` used to be enough when a shard's core was the empty
            # string, and stopped being enough the moment it carried `cc:`.
            "SELECT generation, tier, core, node_count FROM publishes"
            " WHERE core NOT LIKE 'cc:%' AND rowid IN ("
            "   SELECT MAX(rowid) FROM publishes WHERE core NOT LIKE 'cc:%'"
            "   GROUP BY generation, tier"
            " ) ORDER BY created_at DESC"
        ).fetchall()
        live = store.current_generation()
    finally:
        conn.close()

    print(f"live generation: {live or 'none'}")
    print(f"{'protocol':14s} {'nodes':>7s} {'best':>5s}")
    for row in rows:
        print(f"{row['protocol']:14s} {row['n']:7d} {row['best'] if row['best'] is not None else '-':>5}")
    print("published payloads (whole-tier, newest first):")
    for row in published:
        mark = "*" if row["generation"] == live else " "
        print(
            f" {mark}{row['generation']:16s} {row['tier']:9s} {row['core']:8s}"
            f" {row['node_count'] or 0:6d} nodes"
        )
    if not published:
        print("  (none yet)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
