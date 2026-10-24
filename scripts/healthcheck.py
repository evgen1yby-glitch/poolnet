#!/usr/bin/env python3
"""Fail when the public service is up but its data has stopped moving."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = os.environ.get("POOLNET_INTERNAL_URL", "http://127.0.0.1:8090").rstrip("/")
MAX_POOL_HOURS = float(os.environ.get("POOLNET_MAX_POOL_HOURS", "2"))
MAX_VPN_HOURS = float(os.environ.get("POOLNET_MAX_VPN_HOURS", "6"))


def get(path: str) -> tuple[int, object]:
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def alert(message: str) -> None:
    print("healthcheck:", message, file=sys.stderr)
    hook = os.environ.get("POOLNET_ALERT_WEBHOOK", "").strip()
    if not hook:
        return
    body = json.dumps({"text": f"PoolNet healthcheck: {message}"}).encode("utf-8")
    request = urllib.request.Request(
        hook, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            pass
    except (OSError, urllib.error.URLError) as exc:
        print(f"healthcheck: alert webhook failed: {exc}", file=sys.stderr)


def main() -> int:
    try:
        status, health = get("/healthz")
        if status != 200 or not isinstance(health, dict) or health.get("status") != "ok":
            alert(f"healthz is {status}: {health!r}")
            return 1
        age_s = health.get("age_s")
        if isinstance(age_s, (int, float)) and age_s > MAX_VPN_HOURS * 3600:
            alert(f"VPN generation is {age_s / 3600:.1f}h old (limit {MAX_VPN_HOURS}h)")
            return 1

        status, snapshot = get("/api/status.json")
        pool = snapshot.get("pool") if isinstance(snapshot, dict) else None
        if status != 200 or not isinstance(pool, dict) or not pool.get("available"):
            alert(f"pool status is unavailable ({status})")
            return 1
        stamp = str(pool.get("generated_iso") or "")
        try:
            generated = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if generated.tzinfo is None:
                generated = generated.replace(tzinfo=timezone.utc)
        except ValueError:
            alert(f"pool generated_iso is missing or invalid: {stamp!r}")
            return 1
        age_h = (datetime.now(timezone.utc) - generated).total_seconds() / 3600
        if age_h > MAX_POOL_HOURS:
            alert(f"proxy pool is {age_h:.1f}h old (limit {MAX_POOL_HOURS}h)")
            return 1
        return 0
    except (OSError, urllib.error.URLError, ValueError) as exc:
        alert(f"request failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
