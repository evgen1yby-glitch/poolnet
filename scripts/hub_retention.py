#!/usr/bin/env python3
"""Trim hub history so SQLite and the event log do not grow without bound.

Checks older than 30 days are aggregates nobody reads; the current node state
lives in `nodes`, and `publishes` is tiny. Rotate the event log by keeping the
most recent lines when it exceeds the cap. Safe to run while the service is up
(SQLite serialises the delete; the event file is replaced atomically).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=os.environ.get("HUB_ROOT", "/home/dev/poolnet/hub"))
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--events-lines", type=int, default=20_000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, args.days))).isoformat()
    db = root / "data" / "hub.db"
    if db.exists():
        conn = sqlite3.connect(db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM checks WHERE run_at < ?", (cutoff,)).fetchone()[0]
            print(f"checks older than {cutoff}: {count}")
            if not args.dry_run:
                conn.execute("DELETE FROM checks WHERE run_at < ?", (cutoff,))
                conn.commit()
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()

    events = root / "data" / "events.ndjson"
    if events.exists():
        lines = events.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > args.events_lines:
            keep = lines[-args.events_lines :]
            print(f"events: {len(lines)} -> {len(keep)} lines")
            if not args.dry_run:
                tmp = events.with_name(events.name + ".tmp")
                tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
                tmp.replace(events)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
