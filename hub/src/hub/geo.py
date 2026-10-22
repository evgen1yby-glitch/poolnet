"""Country lookup for nodes the probe could not place.

The authoritative source is the probe: it asks the node itself (Cloudflare's
`cdn-cgi/trace` over the node's own tunnel) and gets the *exit* country, which
is the only answer that describes where traffic actually comes out. When that
fails, the probe records "unknown" rather than guessing from the hostname —
`3h-unitedstates1.09vpn.com` may exit anywhere, and a wrong flag is worse than
an honest blank.

The cost of that honesty was a client group called "🌐 XX 5": five working
nodes a user cannot choose by country, which is the one thing the grouping
exists for. This module closes that gap with a *different measured* source
rather than a guess: geo-IP resolves the address itself.

Two properties matter and are both tested:

* It is only consulted for addresses the probe could not place, so the
  authoritative answer always wins and this can never overwrite it.
* Every answer is cached in the database — including a negative one — so one
  address costs one lookup ever. The free tier is 45 requests/minute and a
  batch call covers 100 addresses, but the point is to not need the budget at
  all after the first round.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.request
from pathlib import Path
from typing import Callable, Iterable

__all__ = ["GeoCache", "lookup_countries", "default_fetch"]

#: The batch endpoint takes up to 100 addresses in one POST and is the reason
#: this is affordable: the free tier is 45 requests/minute, so 100 per request
#: makes a pool of thousands cost a handful of calls rather than thousands.
_BATCH_URL = "http://ip-api.com/batch?fields=status,countryCode,query"
_BATCH_MAX = 100


class GeoCache:
    """`address -> country code` in the hub's own SQLite file.

    A separate table rather than a column on `nodes`, because the answer is a
    property of the *address*, not of the node: two nodes behind one address
    share it, and a node that leaves the pool does not invalidate it.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS geo_country (
                address    TEXT PRIMARY KEY,
                country    TEXT NOT NULL,
                looked_up  TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def get(self, address: str) -> str | None:
        """The cached code, `""` for a cached negative, or `None` if unknown.

        The three-state return is the point: `None` means "never asked" and is
        what triggers a lookup, while `""` means "asked, no answer" and must
        not be asked again.
        """
        row = self._conn.execute(
            "SELECT country FROM geo_country WHERE address = ?", (address,)
        ).fetchone()
        return None if row is None else str(row[0])

    def put(self, address: str, country: str, *, now: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO geo_country (address, country, looked_up)"
            " VALUES (?, ?, ?)",
            (address, country, now),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def default_fetch(addresses: list[str]) -> dict[str, str]:
    """One batched geo-IP call, or `{}` on any failure.

    Never raises: a geo lookup is an improvement, not a requirement, and a
    round that publishes nothing because a third-party API was down is a worse
    outcome than a round with one unnamed group. The caller keeps the blank.
    """
    payload = json.dumps([{"query": a} for a in addresses[:_BATCH_MAX]]).encode()
    request = urllib.request.Request(
        _BATCH_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            rows = json.loads(response.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - any failure means "no answer"
        return {}
    if not isinstance(rows, list):
        return {}
    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("status") != "success":
            continue
        code = str(row.get("countryCode") or "").strip().upper()
        address = str(row.get("query") or "").strip()
        # Same rule the prober applies to Cloudflare's `loc`: exactly two ASCII
        # letters, and `XX` is a sentinel rather than a country. A full name or
        # a bad code would split one country into two groups silently.
        if address and len(code) == 2 and code.isascii() and code != "XX":
            out[address] = code
    return out


def lookup_countries(
    addresses: Iterable[str],
    *,
    cache: GeoCache,
    fetch: Callable[[list[str]], dict[str, str]] = default_fetch,
    now: str = "",
) -> dict[str, str]:
    """Country codes for `addresses`, consulting the network only when needed.

    Returns only the addresses that got an answer. An address with no answer is
    cached as `""` so the next round does not spend a lookup on it again — a
    dead address stays dead, and re-asking every six hours is how a free tier
    gets exhausted by a handful of nodes.
    """
    wanted: list[str] = []
    seen: set[str] = set()
    for address in addresses:
        if not address or address in seen:
            continue
        seen.add(address)
        if cache.get(address) is None:
            wanted.append(address)

    for start in range(0, len(wanted), _BATCH_MAX):
        chunk = wanted[start : start + _BATCH_MAX]
        answers = fetch(chunk) or {}
        for address in chunk:
            # Validated here, not only in `default_fetch`: the fetch callable is
            # injectable, and a rule that lives in one implementation of an
            # interface is a rule the next implementation does not have. A bad
            # code reaching the cache would put a country like "United States"
            # or "XX" into the pool's grouping, which is the silent kind of
            # wrong.
            raw = str(answers.get(address) or "").strip().upper()
            code = raw if len(raw) == 2 and raw.isascii() and raw != "XX" else ""
            cache.put(address, code, now=now)

    resolved: dict[str, str] = {}
    for address in seen:
        value = cache.get(address)
        if value:
            resolved[address] = value
    return resolved
