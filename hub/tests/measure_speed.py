#!/usr/bin/env python3
"""Measure real throughput on freshly-parsed nodes, inside `hubns`.

This answers a question the production pipeline cannot answer on this host. Every
run defers the speed stage: the box sits at ~2.1-2.5 per-core load (the
operator's `opencode` sessions, `chrome`, a `qemu` VM) against a 0.85 ceiling, so
the load guard refuses to produce throughput numbers that would measure the
co-tenant rather than the node. That is the guard working. It also means
`speed.measured` has never been non-zero in a real run, and — because the store
keeps no credential material (see the `nodes` table: protocol/address/port/
country/score, no UUID, no password) — deferred nodes can never be measured in
a later pass. Half-credit throughput is the permanent state on a busy box.

So this parses a handful of nodes fresh, measures them with the ceiling lifted,
and reports whether the measurement path itself works. It writes nothing and
publishes nothing.

Safety: run inside `hubns`, the sandbox `deploy/hub-probe.service` uses, so the
dials and per-node SOCKS listener stay off the host's network. The store is
opened read-only for the same reason.

    sudo ip netns exec hubns setpriv --reuid=astrobot --regid=astrobot \
      --clear-groups env PYTHONPATH=src python3 tests/measure_speed.py --n 3
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import time
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--n", type=int, default=3,
                    help="nodes to measure; keep small — this is a real transfer")
    ap.add_argument("--max-load", type=float, default=50.0,
                    help="lift the load ceiling; the guard has already won on"
                         " this box, so measuring anything means overriding it")
    args = ap.parse_args()

    from hub.fetcher import Fetcher, Source
    from hub.parser import parse_many
    from hub.singbox import SingBoxDriver
    from hub.speedtest import SpeedPolicy, SpeedStage

    url = ("https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/"
           "Splitted-By-Protocol/vless.txt")
    print(f"parsing up to {args.n} nodes from Epodonios/vless")
    fetcher = Fetcher([Source(url=url, name="Epodonios/vless")])
    try:
        # `fetch_all` is the same call the pipeline makes, so this exercises the
        # real fetch path rather than a private shortcut that could differ. It
        # returns `(items, stats)`, and an item can be a 304 whose body is empty
        # — that is a successful round that fetched nothing, and saying so beats
        # reporting "no body" as if it were a failure.
        items, _stats = await fetcher.fetch_all()
    except Exception as exc:  # noqa: BLE001
        print(f"source fetch failed: {type(exc).__name__}: {exc}")
        return 1
    if not items:
        print("source returned nothing")
        return 1

    item = items[0]
    body = item.body or ""
    if not body:
        print(f"no body to parse (not_modified={item.not_modified},"
              f" etag={item.etag[:12] or 'none'})")
        return 1

    parsed, errors = parse_many(body)
    print(f"parsed {len(parsed)} nodes ({len(errors)} refused)")
    if not parsed:
        print("nothing to measure")
        return 1

    load = Path("/proc/loadavg").read_text().split()[0]
    cores = len(__import__("os").sched_getaffinity(0))
    print(f"host load {load} across {cores} cores "
          f"({float(load) / cores:.2f}/core, ceiling overridden to {args.max_load})")

    driver = SingBoxDriver()
    try:
        await driver.start()
    except Exception as exc:  # noqa: BLE001
        print(f"driver failed to start: {type(exc).__name__}: {exc}")
        print("expected outside hubns: the driver needs a writable /tmp and its own"
              " loopback, neither of which the host namespace gives it")
        return 1

    measured = 0
    attempted = 0
    started = time.monotonic()
    try:
        # `SpeedStage` is the same object the pipeline drives: it registers each
        # node on the driver, measures, and unregisters in a `finally`. Driving
        # the checker directly would skip that registration and measure nothing.
        stage = SpeedStage(
            driver=driver,
            policy=SpeedPolicy(
                max_load=args.max_load,
                top_n=args.n,
            ),
        )
        # Only a handful of nodes, and only after they have passed the funnel in
        # a real run — here they have not, so most will fail to dial at all. The
        # question is whether the *transfer* path produces a number, and a node
        # that cannot connect is reported as such rather than counted as a
        # measurement failure.
        candidates = parsed[: max(args.n * 4, 12)]
        report = await stage.measure_nodes(candidates, [n.dedup_key for n in candidates])

        by_key = {n.dedup_key: n for n in candidates}
        for sample in report.samples:
            node = by_key.get(sample.dedup_key)
            tag = f"{node.address}:{node.port}" if node else sample.dedup_key[:12]
            attempted += 1
            if sample.ok:
                measured += 1
                print(f"  {tag}: {sample.mbps:8.3f} Mbps "
                      f"({sample.bytes_moved} B in {sample.seconds:.2f}s)")
            else:
                # The reason matters more than the count here: "no bytes moved"
                # is the signature of the tag bug this script exists to catch,
                # and it is also what a dead node looks like. Naming which one
                # is the difference between the two.
                print(f"  {tag}: measured nothing — {sample.skipped_reason}")
        for key, reason in report.deferred.items():
            node = by_key.get(key)
            tag = f"{node.address}:{node.port}" if node else key[:12]
            print(f"  {tag}: deferred — {reason}")
    finally:
        with contextlib.suppress(Exception):
            await driver.stop()

    print(f"\n{measured} measured, {len(report.deferred)} deferred, "
          f"{time.monotonic() - started:.1f}s")
    if measured == 0:
        print("MEASUREMENT PATH BROKEN: the throughput stage cannot produce a number")
        return 1
    print("measurement path works. On this box `hub run` still defers it, and"
          " correctly so — the numbers above were taken with the ceiling lifted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
