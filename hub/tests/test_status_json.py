"""`/api/status.json` — the whole platform's status in one request.

The unified status page reads this once; two pools answering in two places
was the drift the merge removes. Pinned here: `vpn` is byte-for-byte what
`/api/v1/stats` returns, `pool` is the TypeScript engine's published
aggregates (never its line files, never a live store read), and a hub
without a proxy base answers `available: false` instead of erroring.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from hub.api import create_app  # noqa: E402
from hub.store import Store  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = Store(tmp_path)
    generation = store.generation_path("gen-test")
    generation.mkdir(parents=True, exist_ok=True)
    (generation / "verified-sing-box.singbox").write_text('{"ok":true}', encoding="utf-8")
    (generation / "manifest.json").write_text(
        json.dumps({"generation": "gen-test", "sha256": "a" * 64, "payloads": []}),
        encoding="utf-8",
    )
    store.flip_pointer("gen-test", "a" * 64)
    conn = store.connect()
    conn.execute(
        "INSERT INTO nodes (dedup_key, protocol, address, port, score, first_seen)"
        " VALUES (?,?,?,?,?,?)",
        ("a", "vless", "1.2.3.4", 443, 50, 0),
    )
    conn.execute(
        "INSERT INTO publishes (generation, tier, core, fmt, node_count, created_at, sha256)"
        " VALUES (?,?,?,?,?,?,?)",
        ("gen-test", "verified", "main", "singbox", 1, 0, "a" * 64),
    )
    conn.commit()
    conn.close()
    app = create_app(store=store)
    return TestClient(app), tmp_path


def _pool_dir(tmp_path: Path) -> Path:
    """A proxy base publication like `pool/src/publish` writes it."""
    pool = tmp_path / "pooldir"
    pool.mkdir(exist_ok=True)
    (pool / "meta.json").write_text(
        json.dumps(
            {
                "generatedAt": 1792661015878,
                "generatedIso": "2026-10-22T12:54:37.081Z",
                "runId": "12345678",
                "pipeline": "fetch->validate(matrix)->merge->publish",
                "counts": {"published": 30},
                "byProtocol": {"http": 20, "socks5": 10},
            }
        ),
        encoding="utf-8",
    )
    (pool / "stats.json").write_text(
        json.dumps(
            {
                "generatedAt": 1792661015878,
                "generatedIso": "2026-10-22T12:54:37.081Z",
                "total": 30,
                "byProtocol": {"http": 20, "socks5": 10},
                "medianLatencyMs": 123,
                "p95LatencyMs": 5570,
                "countries": [
                    {"country": "CA", "count": 12},
                    {"country": "US", "count": 8},
                ],
                "anonymity": {"elite": 25, "transparent": 5},
                "mitm": 1,
                "tlsCapable": 7,
            }
        ),
        encoding="utf-8",
    )
    (pool / "benchmark.json").write_text(
        json.dumps(
            {
                "generatedAt": 1792661015878,
                "cycle": {"parsed": 3_811_493, "unique": 754_973, "sampled": 3_000, "alive": 3_507},
                "sources": [
                    {
                        "id": "src-http",
                        "candidates": 23,
                        "alive": 22,
                        "liveRate": 0.956,
                        "published": 500,
                        "medianLatency": 17,
                        "eliteRate": 0.95,
                        "staleDays": None,
                    }
                ],
                "ranks": {"src-http": 1},
            }
        ),
        encoding="utf-8",
    )
    return pool


def test_vpn_section_is_exactly_the_v1_stats_payload(client):
    """One store read, one shape: the two callers cannot drift apart."""
    api, _ = client
    unified = api.get("/api/status.json").json()
    assert unified["vpn"] == api.get("/api/v1/stats").json()
    assert set(unified["vpn"]) == {
        "generation",
        "verified",
        "known",
        "by_protocol",
        "by_country",
        "by_score",
        "published",
        "funnel",
    }


def test_pool_section_carries_the_published_aggregates(client, monkeypatch):
    api, tmp_path = client
    monkeypatch.setenv("POOLNET_POOL_DIR", str(_pool_dir(tmp_path)))
    pool = api.get("/api/status.json").json()["pool"]
    assert pool["available"] is True
    assert pool["total"] == 30
    assert pool["by_protocol"] == {"http": 20, "socks5": 10}
    assert pool["grades"] == {"elite": 25, "transparent": 5}
    assert pool["median_ms"] == 123
    assert pool["p95_ms"] == 5570
    assert pool["countries_count"] == 2
    assert pool["countries_top"][:1] == [{"cc": "CA", "n": 12}]
    assert pool["cycle"] == {"parsed": 3_811_493, "unique": 754_973, "sampled": 3_000, "alive": 3_507}
    assert pool["sources"] == 1
    assert pool["run_id"] == "12345678"
    assert pool["pipeline"] == "fetch->validate(matrix)->merge->publish"


def test_benchmark_top_is_capped_at_eight(client, monkeypatch):
    """The status page shows the head of the source board, not all of it.

    `sources` still counts every source so the page can say how many were
    benchmarked overall; `benchmark_top` exists for the few rows the reader
    is likely to see.
    """
    api, tmp_path = client
    pool_dir = _pool_dir(tmp_path)
    meta = json.loads((pool_dir / "benchmark.json").read_text(encoding="utf-8"))
    meta["sources"] = [dict(meta["sources"][0], id=f"src-{i}") for i in range(12)]
    (pool_dir / "benchmark.json").write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setenv("POOLNET_POOL_DIR", str(pool_dir))
    pool = api.get("/api/status.json").json()["pool"]
    assert pool["sources"] == 12
    assert len(pool["benchmark_top"]) == 8
    assert pool["benchmark_top"][0]["id"] == "src-0"


def test_without_a_proxy_base_the_pool_section_stays_honest(client, monkeypatch):
    """No engine run on this install yet: an explicit `false`, never an empty lie."""
    api, _ = client
    monkeypatch.setenv("POOLNET_POOL_DIR", "/does/not/exist")
    assert api.get("/api/status.json").json()["pool"] == {"available": False}


def test_a_corrupt_pool_file_is_not_an_endpoint_error(client, monkeypatch):
    """Half-written publication happens; the status must survive it."""
    api, tmp_path = client
    pool = _pool_dir(tmp_path)
    (pool / "stats.json").write_text('{"total": ', encoding="utf-8")
    monkeypatch.setenv("POOLNET_POOL_DIR", str(pool))
    pool_section = api.get("/api/status.json").json()["pool"]
    # The run counts survive through meta.json; the stats-only fields don't lie.
    assert pool_section["available"] is True
    assert pool_section["total"] == 30  # meta.json counts.published
    assert pool_section["median_ms"] is None
