"""Published-data aggregation for the platform, with no web-framework imports.

Two pools publish their results in different places: the VPN pool in the hub's
SQLite store, the proxy pool in the TypeScript engine's data directory. Before
the merge each project had its own page reader; the merged site needs the same
numbers in three shapes — `/api/v1/stats` (the hub's public contract),
`/api/status.json` (both pools, one request) and the page renderer's payload.

Keeping that logic here, away from FastAPI, is what makes it testable without an
app and reusable by the gateway and the renderer. Nothing in this module opens
an HTTP request, caches a response, or knows about `Request`.

Failure posture: published files are read defensively. A missing directory, a
half-written JSON or a renamed field yields a smaller payload — never an
exception. The site keeps its static fallbacks; the API keeps its documented
shape with empty sections.
"""

from __future__ import annotations

import json
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from .models import Format, Tier
from .store import Store

#: Coordinates of the country dots on the index map, in the SVG's 200×75 grid.
#: Ported verbatim from the hub's legacy `ui/hub.js` (`MAP_POS`), which drew the
#: same map before the merge. Keeping the copy here rather than parsing JS is
#: deliberate: the dashboard bundle is an unrelated surface, and a site build
#: must not depend on it.
MAP_POS: dict[str, tuple[float, float]] = {
    "US": (22.8, 26.1), "CA": (21.9, 12.6), "MX": (21.5, 37.9), "BR": (35.6, 63.6),
    "AR": (32.2, 81.2), "ZA": (56.9, 77), "IN": (71.9, 38.6), "AE": (65.1, 37.8),
    "IL": (59.7, 32.3), "TR": (59.8, 26.7), "GE": (62.1, 24.3), "AM": (62.5, 25.7),
    "AZ": (63.2, 25.6), "KZ": (68.6, 19.9), "UZ": (67.6, 24.6), "GB": (49.6, 16.5),
    "IE": (47.8, 16.1), "IS": (44.8, 7.5), "FR": (50.7, 21), "DE": (52.9, 17.6),
    "NL": (51.5, 16.9), "BE": (51.3, 18.1), "LU": (51.7, 18.7), "CH": (52.3, 20.9),
    "AT": (53.9, 20.3), "CZ": (54.3, 18.7), "PL": (55.4, 17), "SK": (55.5, 19.5),
    "HU": (55.4, 20.6), "SI": (54.1, 21.4), "HR": (54.6, 21.8), "BA": (54.9, 22.8),
    "RS": (55.8, 22.9), "ME": (55.4, 23.9), "MK": (56, 24.7), "AL": (55.6, 25.1),
    "GR": (56.2, 26.6), "BG": (57, 23.9), "RO": (56.9, 21.5), "MD": (57.9, 20.6),
    "UA": (58.7, 19.3), "BY": (57.6, 15.9), "LT": (56.7, 14.7), "LV": (56.9, 13.4),
    "EE": (57.2, 12.1), "FI": (57.2, 9), "SE": (54.6, 10.7), "NO": (52.8, 10),
    "DK": (52.6, 14.1), "IT": (53.5, 23.9), "ES": (49, 25.8), "PT": (47.7, 26.2),
    "MT": (54, 29), "CY": (59.2, 29.6), "JP": (88.3, 28.5), "SG": (78.8, 54.6),
    "HK": (81.7, 39), "KR": (85.5, 28.6), "AU": (87.4, 74.3), "NZ": (98, 86.5),
    "TW": (83.6, 38), "TH": (78.1, 44.4), "VN": (79.5, 43.3), "MY": (78.3, 52.4),
    "PH": (84.1, 46), "ID": (81.6, 57.3), "CR": (26.6, 48.2), "RU": (77.5, 10),
    "CL": (30.2, 82),
}

#: The largest dot on the map, in SVG units. The hub's map used the same value.
_MAP_MAX_R = 2.6


def pool_dir(store: Store) -> Path:
    """Where the proxy engine publishes: `EVILGATE_POOL_DIR`, else a sibling."""
    return Path(
        os.environ.get("EVILGATE_POOL_DIR", "") or store.root.parent / "pool" / "data"
    )


def _counts(conn, sql: str) -> list[dict]:
    """`{name, n}` rows in name order, empty cells dropped."""
    rows = conn.execute(sql).fetchall()
    return [
        {"name": (row[0] or "unknown"), "n": row[1]}
        for row in sorted(rows, key=lambda r: (r[0] or ""))
        if row[1]
    ]


def _last_funnel(store: Store) -> dict:
    """Node counts at each verification stage, from the most recent run.

    This is the one number on the landing page that says what the pool *is*
    rather than how big it is: of tens of thousands of lines the sources offer,
    the stages discard all but a couple of hundred. Publishing the funnel is
    the honest counterpart to publishing the count.

    Read from the event log rather than the database because the stages are a
    property of one *run*: `checks` keeps a row per node per stage across all
    history, so counting there would mix runs and report a funnel wider than
    any single pass. A fetch-only pass carries no stages at all, so the most
    recent run with stage counts wins — otherwise the funnel would read as a
    broken pool after a pass that did not probe.
    """
    import json

    last: dict | None = None
    try:
        with store.log.open("r", encoding="utf-8") as handle:
            for line in handle:
                if '"run_done"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("kind") != "run_done":
                    continue
                if (event.get("stage_survivors") or {}).get("survivors.tcp") is not None:
                    last = event
    except OSError:
        last = None
    if not last:
        return {"raw": 0, "parsed": 0, "tcp": 0, "tls": 0, "config": 0, "http": 0}
    stages = last.get("stage_survivors") or {}
    return {
        "raw": last.get("nodes_raw", 0),
        "parsed": last.get("nodes_parsed", 0),
        "tcp": stages.get("survivors.tcp", 0),
        "tls": stages.get("survivors.tls", 0),
        "config": stages.get("survivors.config", 0),
        "http": stages.get("survivors.http", 0),
    }


def vpn_payload(store: Store) -> dict:
    """The published VPN-pool aggregates, shared by both status callers.

    `GET /api/v1/stats` and `GET /api/status.json` answer the same store, so
    the SQL lives here once: `/api/v1/stats` predates the merge and keeps its
    exact shape (clients depend on the key set), while the unified status page
    wraps it in a `vpn` section.

    Every count comes from the published generation, not from the `nodes`
    table. `nodes` accumulates every probe ever recorded — including rows that
    predate the `state` column and can never be published — so it reported 832
    nodes over a generation holding 150. `known` stays the index size on
    purpose: "how big is the pool we check" is a different, useful number, and
    the page labels which is which.
    """
    conn = store.connect()
    try:
        generation = store.current_generation()
        verified = conn.execute(
            "SELECT COALESCE(MAX(node_count), 0) FROM publishes"
            " WHERE generation = ? AND tier = ? AND core NOT LIKE 'cc:%'",
            (generation, Tier.VERIFIED.value),
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        by_protocol = _counts(conn, "SELECT protocol, COUNT(*) FROM nodes GROUP BY protocol")
        rows = conn.execute(
            "SELECT SUBSTR(core, 4) AS cc, MIN(node_count) AS n"
            " FROM publishes"
            " WHERE generation = ? AND tier = ?"
            "   AND core LIKE 'cc:%' AND fmt = ?"
            " GROUP BY cc ORDER BY cc",
            (generation, Tier.VERIFIED.value, Format.SINGBOX.value),
        ).fetchall()
        by_country = [{"name": row[0], "n": row[1]} for row in rows if row[0] and row[1]]
        by_score = {
            "60+": conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE score >= 60"
            ).fetchone()[0],
            "30-59": conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE score >= 30 AND score < 60"
            ).fetchone()[0],
            "0-29": conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE score < 30"
            ).fetchone()[0],
        }
        tier_rows = conn.execute(
            "SELECT tier, MAX(node_count) AS n, MIN(created_at) AS first_at"
            " FROM publishes WHERE generation = ? AND core NOT LIKE 'cc:%'"
            " GROUP BY tier ORDER BY first_at",
            (generation,),
        ).fetchall()
        funnel = _last_funnel(store)
    finally:
        conn.close()
    return {
        "generation": generation,
        "verified": verified,
        "known": total,
        "by_protocol": by_protocol,
        "by_country": by_country,
        "by_score": by_score,
        "published": [{"tier": row[0], "nodes": row[1], "at": row[2]} for row in tier_rows],
        "funnel": funnel,
    }


def _read_json(path: Path) -> dict:
    """Read a published JSON file, or `{}` — half-written files are normal."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _int(value, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _number(value, default: float = 0.0) -> float:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def pool_payload(directory: Path) -> dict:
    """The published proxy-pool aggregates, read from the TS engine's data dir.

    The engine writes `stats.json` (its own aggregates), `meta.json` (the run's
    counts and how it was made) and `benchmark.json` (what each public list is
    worth). Line files are not read here: a reader that needs entries fetches
    them from `/pool/*`, and parsing 30 MB of JSON on every status request
    would serve one number. `available: false` is the honest answer for a hub
    installed without a proxy base.
    """
    stats = _read_json(directory / "stats.json")
    meta = _read_json(directory / "meta.json")
    bench = _read_json(directory / "benchmark.json")
    if not (stats or meta or bench):
        return {"available": False}
    countries = stats.get("countries")
    if not isinstance(countries, list):
        countries = []

    def bench_rows(rows) -> list:
        return [
            {
                "id": row.get("id"),
                "candidates": row.get("candidates"),
                "alive": row.get("alive"),
                "live_rate": row.get("liveRate"),
                "published": row.get("published"),
                "median_ms": row.get("medianLatency"),
                "elite_rate": row.get("eliteRate"),
            }
            for row in (rows if isinstance(rows, list) else [])[:8]
            if isinstance(row, dict)
        ]

    return {
        "available": True,
        "generated_iso": meta.get("generatedIso") or stats.get("generatedIso"),
        "run_id": meta.get("runId"),
        "pipeline": meta.get("pipeline"),
        "total": stats.get("total") or (meta.get("counts") or {}).get("published"),
        "by_protocol": stats.get("byProtocol") or meta.get("byProtocol") or {},
        "grades": stats.get("anonymity") or {},
        "median_ms": stats.get("medianLatencyMs"),
        "p95_ms": stats.get("p95LatencyMs"),
        "mitm": stats.get("mitm"),
        "tls_capable": stats.get("tlsCapable"),
        "countries_count": len(countries),
        "countries_top": [
            {"cc": row.get("country"), "n": row.get("count")}
            for row in countries[:12]
            if isinstance(row, dict) and row.get("country")
        ],
        "cycle": bench.get("cycle"),
        "sources": len(bench.get("sources") or [])
        if isinstance(bench.get("sources"), list)
        else 0,
        "benchmark_top": bench_rows(bench.get("sources")),
    }


def combined(store: Store, directory: Path | None = None) -> dict:
    """Both pools in the shape `/api/status.json` publishes."""
    return {"vpn": vpn_payload(store), "pool": pool_payload(directory or pool_dir(store))}


def _utc_hm(value) -> str:
    """`2026-10-22T16:29:10+00:00` -> `16:29`; unparseable -> unchanged text."""
    if not isinstance(value, str) or not value:
        return ""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[11:16] if len(value) >= 16 else value
    return moment.astimezone(timezone.utc).strftime("%H:%M")


def _line_count(path: Path) -> int:
    """Count lines without decoding 30k addresses: newline bytes are enough."""
    try:
        with path.open("rb") as handle:
            return sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(1 << 20), b""))
    except OSError:
        return 0


#: Parsed `proxies.json` per publication, keyed by path and file version. The
#: file is several megabytes and the pool page asks for it on every filter
#: change; re-parsing per keystroke would make the search feel broken.
_PROXY_CACHE: dict[str, tuple[tuple[int, int], list[dict]]] = {}
_PROXY_LOCK = threading.Lock()

#: The order the page promises: "sorted by 30-day uptime". Ties go to the
#: faster node, then the address, so equal rows never reshuffle between reads.
_PROXY_SORT = lambda row: (  # noqa: E731 - one expression, used once
    -_number(row.get("uptime_30d")),
    row.get("latency_ms") if isinstance(row.get("latency_ms"), int) else 10**9,
    str(row.get("host")),
)


def proxy_index(directory: Path) -> list[dict]:
    """Every published proxy, sorted for display, cached per file version."""
    path = directory / "proxies.json"
    try:
        stat = path.stat()
    except OSError:
        return []
    version = (stat.st_mtime_ns, stat.st_size)
    key = str(path)
    with _PROXY_LOCK:
        cached = _PROXY_CACHE.get(key)
        if cached is not None and cached[0] == version:
            return cached[1]
    published = _read_json(path)
    entries = published.get("proxies")
    clean = (
        [row for row in entries if isinstance(row, dict) and row.get("host")]
        if isinstance(entries, list)
        else []
    )
    clean.sort(key=_PROXY_SORT)
    with _PROXY_LOCK:
        _PROXY_CACHE[key] = (version, clean)
    return clean


def _proxy_view(row: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "address": f"{row.get('host')}:{row.get('port')}",
        "protocol": str(row.get("protocol") or ""),
        "grade": str(row.get("anonymity") or "unknown"),
        "latency_ms": _int(row.get("latency_ms")),
        "uptime_7d": _number(row.get("uptime_7d")),
        "country": str(row.get("country") or ""),
    }


def _proxy_rows(directory: Path, limit: int = 10) -> list[dict]:
    """A deterministic sample for the static render and the console."""
    return [
        _proxy_view(row, index)
        for index, row in enumerate(proxy_index(directory)[:limit], start=1)
    ]


def query_proxies(
    directory: Path,
    *,
    page: int = 1,
    per: int = 50,
    protocols: tuple[str, ...] = (),
    grades: tuple[str, ...] = (),
    country: str = "",
    query: str = "",
) -> dict:
    """One page of the published pool, filtered by the page's controls.

    Filtering happens here rather than in the browser because the full list is
    32k rows / several megabytes: the page needs a page of rows and a total,
    not the whole pool. The index is sorted once per publication and cached, so
    a keystroke costs a linear scan of dicts, not a JSON parse.

    Ranks are positions in the *filtered* result, which is what the number
    column means to a reader paging through.
    """
    index = proxy_index(directory)
    proto_set = {value.lower() for value in protocols if value}
    grade_set = {value.lower() for value in grades if value}
    cc = country.upper().strip()
    needle = query.strip().lower()
    matched = [
        row
        for row in index
        if (not proto_set or str(row.get("protocol") or "").lower() in proto_set)
        and (not grade_set or str(row.get("anonymity") or "").lower() in grade_set)
        and (not cc or str(row.get("country") or "").upper() == cc)
        and (
            not needle
            or needle in str(row.get("host") or "").lower()
            or needle in str(row.get("country") or "").lower()
        )
    ]
    per = max(1, min(int(per or 50), 100))
    pages = max(1, math.ceil(len(matched) / per))
    page = max(1, min(int(page or 1), pages))
    start = (page - 1) * per
    country_counts: dict[str, int] = {}
    for row in index:
        code = str(row.get("country") or "").upper()
        if code:
            country_counts[code] = country_counts.get(code, 0) + 1
    return {
        "available": bool(index),
        "generated_utc": _utc_hm(_read_json(directory / "meta.json").get("generatedIso")),
        "total": len(matched),
        "pool_total": len(index),
        "page": page,
        "per": per,
        "pages": pages,
        "rows": [
            _proxy_view(row, start + offset + 1)
            for offset, row in enumerate(matched[start : start + per])
        ],
        "countries": [
            {"cc": code, "n": count}
            for code, count in sorted(country_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }


def _source_rows(benchmark: dict, limit: int = 8) -> list[dict]:
    """Benchmark rows in published rank order — the page's top-sources table."""
    rows = benchmark.get("sources")
    if not isinstance(rows, list):
        return []
    ranks = benchmark.get("ranks") if isinstance(benchmark.get("ranks"), dict) else {}
    clean = [row for row in rows if isinstance(row, dict)]
    clean.sort(key=lambda row: ranks.get(str(row.get("id")), 10**6))
    out: list[dict] = []
    for row in clean[:limit]:
        out.append(
            {
                "id": str(row.get("id") or ""),
                "candidates": _int(row.get("candidates")),
                "alive": _int(row.get("alive")),
                "live_rate": _number(row.get("liveRate")),
                "published": _int(row.get("published")),
                "median_ms": _int(row.get("medianLatency")),
                "elite_rate": _number(row.get("eliteRate")),
            }
        )
    return out


def _map_dots(by_country: list[dict]) -> list[dict]:
    """Country dots for the 200×75 map, radius ∝ sqrt(n).

    `MAP_POS` is stored on the 100×100 grid the hub's dashboard used; the site
    draws the world at 200×75 (360°×135°, the map's natural proportion), so the
    same transform the dashboard applied is required here: x×2, y×0.75. Without
    it every dot sat in the left third of the map and above its latitude, which
    read as a broken projection rather than as data.
    """
    points = [
        (str(row.get("name") or "").upper(), _int(row.get("n")))
        for row in by_country
        if isinstance(row, dict) and row.get("name")
    ]
    points = [(cc, n) for cc, n in points if n > 0 and cc in MAP_POS]
    if not points:
        return []
    peak = max(n for _cc, n in points)
    dots = []
    for cc, n in sorted(points):
        share = math.sqrt(n / peak)
        dots.append(
            {
                "cc": cc,
                "n": n,
                "x": round(MAP_POS[cc][0] * 2, 2),
                "y": round(MAP_POS[cc][1] * 0.75, 2),
                "r": round(max(0.9, _MAP_MAX_R * share), 2),
                "halo": round(5.8 * share, 2) if n == peak else 0,
            }
        )
    return dots


def country_rows(by_country: list[dict], limit: int = 8) -> list[dict]:
    """Top countries for the map strip and the console: flag, count, bar width."""
    points = sorted(
        (
            (str(row.get("name") or "").upper(), _int(row.get("n")))
            for row in by_country
            if isinstance(row, dict) and row.get("name") and _int(row.get("n")) > 0
        ),
        key=lambda pair: (-pair[1], pair[0]),
    )[:limit]
    if not points:
        return []
    peak = points[0][1]
    return [
        {"cc": cc, "n": n, "width": round(100.0 * n / peak, 1)} for cc, n in points
    ]


def _shards(directory: Path) -> int:
    try:
        return sum(1 for path in (directory / "country").glob("*.txt") if path.is_file())
    except OSError:
        return 0


def _signature(store: Store, directory: Path) -> tuple:
    """Cheap fingerprint of everything the site payload is built from."""
    parts: list[object] = [store.current_generation()]
    for name in (
        "stats.json",
        "meta.json",
        "benchmark.json",
        "proxies.json",
        "http.txt",
        "socks4.txt",
        "socks5.txt",
        "all.txt",
        "country/CA.txt",
    ):
        try:
            stat = (directory / name).stat()
        except OSError:
            parts.append((name, 0, 0))
        else:
            parts.append((name, stat.st_mtime_ns, stat.st_size))
    try:
        parts.append(("country", (directory / "country").stat().st_mtime_ns))
    except OSError:
        parts.append(("country", 0))
    return tuple(parts)


def site_payload(store: Store, directory: Path | None = None) -> tuple[dict, str]:
    """The renderer's data plus a version string, built once per publish cycle.

    The TS engine rewrites its files every fifteen minutes and the VPN pipeline
    on its own schedule; rebuilding this payload per request would re-read a
    5 MB `proxies.json` and count 120k lines for numbers that did not change.
    The version is a fingerprint of the published files and the current
    generation, so the renderer's cache invalidates exactly when data changes.
    """
    directory = directory or pool_dir(store)
    vpn = vpn_payload(store)
    pool = pool_payload(directory)
    benchmark = _read_json(directory / "benchmark.json")
    version = repr(_signature(store, directory))

    protocols = vpn.get("by_protocol") if isinstance(vpn.get("by_protocol"), list) else []
    countries = vpn.get("by_country") if isinstance(vpn.get("by_country"), list) else []
    published = vpn.get("published") if isinstance(vpn.get("published"), list) else []
    updated = (
        _utc_hm(published[0].get("at"))
        if published and isinstance(published[0], dict)
        else ""
    )

    cycle = pool.get("cycle") if isinstance(pool.get("cycle"), dict) else {}
    by_protocol = pool.get("by_protocol") if isinstance(pool.get("by_protocol"), dict) else {}
    grades = pool.get("grades") if isinstance(pool.get("grades"), dict) else {}
    source_list = benchmark.get("sources") if isinstance(benchmark.get("sources"), list) else []
    sources_ok = sum(
        1 for row in source_list if isinstance(row, dict) and _int(row.get("candidates")) > 0
    )
    files = {
        "http": _line_count(directory / "http.txt"),
        "socks4": _line_count(directory / "socks4.txt"),
        "socks5": _line_count(directory / "socks5.txt"),
        "all": _line_count(directory / "all.txt"),
        "ca": _line_count(directory / "country" / "CA.txt"),
    }

    data = {
        "vpn": {
            "generation": vpn.get("generation") or "",
            "verified": _int(vpn.get("verified")),
            "known": _int(vpn.get("known")),
            "countries": len(countries),
            "protocols": [
                {"name": row.get("name"), "n": _int(row.get("n"))}
                for row in protocols
                if isinstance(row, dict)
            ],
            "funnel": {
                key: _int(value) for key, value in (vpn.get("funnel") or {}).items()
            },
            "updated_utc": updated,
        },
        "pool": {
            "available": bool(pool.get("available")),
            "generated_utc": _utc_hm(pool.get("generated_iso")),
            "total": _int(pool.get("total")),
            "by_protocol": {
                "http": _int(by_protocol.get("http")),
                "socks4": _int(by_protocol.get("socks4")),
                "socks5": _int(by_protocol.get("socks5")),
            },
            "grades": {
                "elite": _int(grades.get("elite")),
                "anonymous": _int(grades.get("anonymous")),
                "transparent": _int(grades.get("transparent")),
                "unknown": _int(grades.get("unknown")),
            },
            "median_ms": _int(pool.get("median_ms")),
            "p95_ms": _int(pool.get("p95_ms")),
            "countries": _int(pool.get("countries_count")),
            "cycle": {
                "parsed": _int(cycle.get("parsed")),
                "unique": _int(cycle.get("unique")),
                "sampled": _int(cycle.get("sampled")),
                "alive": _int(cycle.get("alive")),
            },
            "sources_ok": sources_ok,
            "sources_total": _int(pool.get("sources")),
            "shards": _shards(directory),
            "files": files,
        },
        "proxy_rows": _proxy_rows(directory),
        "source_rows": _source_rows(benchmark),
        "map_dots": _map_dots(countries),
        "country_rows": country_rows(countries),
    }
    return data, version


class SiteDataSource:
    """Cache `site_payload` between publish cycles.

    The lock makes a concurrent burst during a publish build the payload once;
    the version check on every request keeps the rendered numbers within one
    file-write of the published state.
    """

    def __init__(self, store: Store, directory: Path | None = None) -> None:
        self.store = store
        #: `None` means "resolve from the environment on every request", which
        #: keeps `EVILGATE_POOL_DIR` an operational knob rather than a startup
        #: constant; tests rely on that too.
        self.directory = directory
        self._lock = threading.Lock()
        self._version = ""
        self._data: dict = {}

    def get(self) -> tuple[dict, str]:
        directory = self.directory or pool_dir(self.store)
        version = repr(_signature(self.store, directory))
        with self._lock:
            if self._data and version == self._version:
                return self._data, self._version
        data, version = site_payload(self.store, directory)
        with self._lock:
            self._data, self._version = data, version
            return self._data, self._version
