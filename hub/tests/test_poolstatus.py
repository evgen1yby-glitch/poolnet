"""The platform's data layer: both pools, the renderer payload, its cache.

`poolstatus` is deliberately framework-free, so most of it is tested without an
app. The HTTP contracts that consume it stay pinned in `test_status_json.py`
and `test_site.py`; here the focus is the shapes the renderer relies on, the
defensive reads, and the cache invalidating exactly when a published file
changes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hub import poolstatus  # noqa: E402
from hub.store import Store  # noqa: E402


def _store(tmp_path: Path) -> Store:
    return Store(tmp_path)


def _publication(tmp_path: Path) -> Path:
    pool = tmp_path / "data"
    (pool / "country").mkdir(parents=True)
    (pool / "stats.json").write_text(
        json.dumps(
            {
                "generatedIso": "2026-10-22T16:24:34.650Z",
                "total": 30,
                "byProtocol": {"http": 20, "socks4": 3, "socks5": 7},
                "anonymity": {"elite": 24, "anonymous": 2, "transparent": 1, "unknown": 3},
                "medianLatencyMs": 113,
                "p95LatencyMs": 5593,
                "countries": [{"country": "CA", "count": 12}, {"country": "US", "count": 8}],
            }
        ),
        encoding="utf-8",
    )
    (pool / "meta.json").write_text(
        json.dumps({"generatedIso": "2026-10-22T16:24:34.650Z", "runId": "123"}),
        encoding="utf-8",
    )
    (pool / "benchmark.json").write_text(
        json.dumps(
            {
                "cycle": {"parsed": 1000, "unique": 900, "sampled": 300, "alive": 40},
                "ranks": {"b": 1, "a": 2},
                "sources": [
                    {"id": "a", "candidates": 5, "alive": 1, "liveRate": 20,
                     "published": 1, "medianLatency": 100, "eliteRate": 100},
                    {"id": "b", "candidates": 0, "alive": 0, "liveRate": 0,
                     "published": 0, "medianLatency": 0, "eliteRate": 0},
                ],
            }
        ),
        encoding="utf-8",
    )
    (pool / "http.txt").write_text("1.1.1.1:80\n2.2.2.2:80\n", encoding="utf-8")
    (pool / "socks4.txt").write_text("3.3.3.3:1080\n", encoding="utf-8")
    (pool / "socks5.txt").write_text("4.4.4.4:1080\n", encoding="utf-8")
    (pool / "all.txt").write_text("1.1.1.1:80\n2.2.2.2:80\n3.3.3.3:1080\n", encoding="utf-8")
    (pool / "country" / "CA.txt").write_text("1.1.1.1:80\n", encoding="utf-8")
    (pool / "proxies.json").write_text(
        json.dumps(
            {
                "count": 3,
                "proxies": [
                    {"protocol": "http", "host": "9.9.9.9", "port": 80,
                     "latency_ms": 300, "anonymity": "elite", "uptime_7d": 90, "uptime_30d": 90,
                     "country": "US"},
                    {"protocol": "http", "host": "8.8.8.8", "port": 80,
                     "latency_ms": 10, "anonymity": "anonymous", "uptime_7d": 50, "uptime_30d": 50,
                     "country": "DE"},
                    {"protocol": "socks5", "host": "7.7.7.7", "port": 1080,
                     "latency_ms": 50, "anonymity": "elite", "uptime_7d": 100, "uptime_30d": 100,
                     "country": "CA"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return pool


def test_pool_payload_keeps_the_documented_shape(tmp_path):
    pool = poolstatus.pool_payload(_publication(tmp_path))
    assert pool["available"] is True
    assert pool["total"] == 30
    assert pool["countries_count"] == 2
    assert pool["sources"] == 2
    assert len(pool["benchmark_top"]) <= 8


def test_missing_publication_is_available_false(tmp_path):
    assert poolstatus.pool_payload(tmp_path / "nope") == {"available": False}


def test_corrupt_json_does_not_raise(tmp_path):
    directory = _publication(tmp_path)
    (directory / "stats.json").write_text('{"total": ', encoding="utf-8")
    payload = poolstatus.pool_payload(directory)
    assert payload["available"] is True  # meta/benchmark still readable
    assert payload["total"] is None


def test_site_payload_maps_both_pools_into_renderer_fields(tmp_path):
    directory = _publication(tmp_path)
    data, version = poolstatus.site_payload(_store(tmp_path / "store"), directory)
    assert version
    assert data["pool"]["total"] == 30
    assert data["pool"]["generated_utc"] == "16:24"
    assert data["pool"]["shards"] == 1
    assert data["pool"]["files"]["http"] == 2
    assert data["pool"]["files"]["ca"] == 1
    assert data["pool"]["sources_ok"] == 1
    assert data["pool"]["sources_total"] == 2
    assert data["proxy_rows"][0]["address"] == "7.7.7.7:1080"  # 30-day uptime
    assert [row["id"] for row in data["source_rows"]] == ["b", "a"]  # rank order
    assert data["vpn"]["countries"] == 0  # empty store: honest zeros
    assert data["map_dots"] == []


def test_map_dots_use_known_coordinates_and_sqrt_radius(tmp_path):
    dots = poolstatus._map_dots(
        [{"name": "CA", "n": 100}, {"name": "US", "n": 25}, {"name": "ZZ", "n": 10}]
    )
    assert [dot["cc"] for dot in dots] == ["CA", "US"]  # unknown coordinate skipped
    top = next(dot for dot in dots if dot["cc"] == "CA")
    half = next(dot for dot in dots if dot["cc"] == "US")
    assert top["r"] == 2.6
    assert half["r"] < top["r"]


def test_source_cache_rebuilds_when_a_published_file_changes(tmp_path):
    directory = _publication(tmp_path)
    source = poolstatus.SiteDataSource(_store(tmp_path / "store"), directory)
    first, first_version = source.get()
    assert source.get() == (first, first_version)  # cache hit

    (directory / "stats.json").write_text(
        json.dumps({"total": 99, "generatedIso": "2026-10-22T17:00:00Z"}),
        encoding="utf-8",
    )
    os.utime(directory / "stats.json", ns=(1, 1))
    second, second_version = source.get()
    assert second["pool"]["total"] == 99
    assert second_version != first_version


def test_cache_follows_the_env_when_no_directory_was_pinned(tmp_path, monkeypatch):
    directory = _publication(tmp_path)
    monkeypatch.setenv("EVILGATE_POOL_DIR", str(directory))
    source = poolstatus.SiteDataSource(_store(tmp_path / "store"))
    data, _version = source.get()
    assert data["pool"]["total"] == 30
