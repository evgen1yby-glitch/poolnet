#!/usr/bin/env python3
"""Rotate through the pool for one request at a time.

Reads data/proxies.json (or a URL), keeps the healthy entries in a local
file, and hands out one working proxy per call. A stand-in for the paid
residential pools — same interface, no bill.

Usage:
    python3 examples/rotate.py https://api.ipify.org
    python3 examples/rotate.py https://api.ipify.org 20   # 20 requests
"""
from __future__ import annotations

import json
import random
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

POOL = Path(__file__).resolve().parent.parent / "data" / "proxies.json"
CACHE = Path.home() / ".cache" / "proxy-pool" / "alive.txt"
TIMEOUT = 12


def load_pool() -> list[dict]:
    if not POOL.exists():
        sys.exit(f"pool file not found: {POOL} — run the pipeline once first")
    data = json.loads(POOL.read_text())
    return data.get("proxies", [])


def test(entry: dict) -> str | None:
    """One full request through the proxy; returns the exit IP or None."""
    scheme = "socks5h" if entry["protocol"] == "socks5" else entry["protocol"]
    proxy = f"{scheme}://{entry['host']}:{entry['port']}"
    handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    opener = urllib.request.build_opener(handler)
    try:
        with opener.open("https://api.ipify.org", timeout=TIMEOUT) as res:
            if res.status == 200:
                return res.read().decode().strip()
    except Exception:
        return None
    return None


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "https://api.ipify.org"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    pool = load_pool()

    # elite first, then anonymous — the pool file is already quality-sorted
    pool.sort(key=lambda p: (p.get("anonymity") != "elite", p.get("latency_ms") or 9e9))
    candidates = pool[: min(len(pool), count * 8)]

    with ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(test, candidates))

    alive = [f"{c['protocol']}://{c['host']}:{c['port']}" for c, ip in zip(candidates, results) if ip]
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text("\n".join(alive))

    print(f"{len(alive)} of {len(candidates)} candidates answered a full request")
    print(f"cached to {CACHE}")

    for line in alive[:count]:
        print(f"  {line}")


if __name__ == "__main__":
    main()
