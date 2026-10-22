"""The gateway's own behaviour: rendering, the check guard, client addressing.

Routing and file serving are pinned in `test_site.py` / `test_pool_files.py`.
This file covers what the extraction introduced: pages actually rendered from
published data, the on-demand check's rate and concurrency limits, and the
forwarded-address rule both use.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from starlette.requests import Request  # noqa: E402

from hub import gateway  # noqa: E402
from hub.api import create_app  # noqa: E402
from hub.store import Store  # noqa: E402

SITE_DIR = Path(__file__).resolve().parents[2] / "web" / "site"
pytestmark = pytest.mark.skipif(
    not (SITE_DIR / "index.html").is_file(), reason="site not in checkout"
)


def _pool_dir(tmp_path: Path, total: int = 4242) -> Path:
    pool = tmp_path / "pub"
    (pool / "country").mkdir(parents=True)
    (pool / "stats.json").write_text(
        json.dumps(
            {
                "generatedIso": "2026-10-22T16:24:34Z",
                "total": total,
                "byProtocol": {"http": total - 10, "socks4": 5, "socks5": 5},
                "anonymity": {"elite": 1, "anonymous": 1, "transparent": 1, "unknown": 1},
                "medianLatencyMs": 113,
                "p95LatencyMs": 5593,
                "countries": [{"country": "CA", "count": 1}],
            }
        ),
        encoding="utf-8",
    )
    (pool / "benchmark.json").write_text(
        json.dumps({"cycle": {"parsed": 1, "unique": 1, "sampled": 1, "alive": 1}, "sources": []}),
        encoding="utf-8",
    )
    (pool / "http.txt").write_text("1.1.1.1:80\n", encoding="utf-8")
    return pool


def _client(tmp_path: Path, monkeypatch, pool: Path) -> TestClient:
    monkeypatch.setenv("HUB_SITE", str(SITE_DIR))
    monkeypatch.setenv("EVILGATE_POOL_DIR", str(pool))
    return TestClient(create_app(store=Store(tmp_path / "store")))


def test_pages_are_rendered_from_published_data(tmp_path, monkeypatch):
    """The pool page shows the fixture's total, not the baked fallback copy."""
    client = _client(tmp_path, monkeypatch, _pool_dir(tmp_path, total=4242))
    body = client.get("/proxy").text
    assert "4 242" in body
    assert "{{" not in body
    assert "<!--begin:" not in body


def test_rendered_index_carries_the_map_and_protocol_rows(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, _pool_dir(tmp_path))
    body = client.get("/").text
    assert "{{" not in body
    assert "ms-dot" in body or "ms-land" in body


def test_unknown_page_serves_the_site_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, _pool_dir(tmp_path))
    response = client.get("/definitely-not-a-page")
    assert response.status_code == 404
    assert "не найдена" in response.text


def test_check_guard_rate_limits_a_burst():
    guard = gateway.CheckGuard(per_minute=5, burst=3, concurrent=8)
    assert guard.acquire("203.0.113.7")[0] is True
    assert guard.acquire("203.0.113.7")[0] is True
    assert guard.acquire("203.0.113.7")[0] is True
    allowed, reason = guard.acquire("203.0.113.7")
    assert allowed is False
    assert "rate" in reason


def test_check_guard_caps_concurrent_probes():
    guard = gateway.CheckGuard(per_minute=100, burst=10, concurrent=1)
    assert guard.acquire("203.0.113.7")[0] is True
    allowed, reason = guard.acquire("198.51.100.9")
    assert allowed is False
    assert "flight" in reason
    guard.release()
    assert guard.acquire("198.51.100.9")[0] is True


def test_check_endpoint_answers_429_after_the_burst(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, _pool_dir(tmp_path))
    monkeypatch.setattr(
        gateway,
        "check_proxy",
        lambda *a, **kw: {"alive": True, "remote_ip": None, "latency_ms": 1, "error": None},
    )
    statuses = [
        client.get("/api/check", params={"proxy": "8.8.8.8:1080", "proto": "socks5"}).status_code
        for _ in range(4)
    ]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429


def test_client_address_trusts_forwarded_only_from_loopback():
    request = Request(
        {
            "type": "http",
            "client": ("203.0.113.5", 1234),
            "headers": [(b"x-forwarded-for", b"198.51.100.7")],
        }
    )
    assert gateway.client_address(request) == "203.0.113.5"

    forwarded = Request(
        {
            "type": "http",
            "client": ("127.0.0.1", 1234),
            "headers": [(b"x-forwarded-for", b"198.51.100.7")],
        }
    )
    assert gateway.client_address(forwarded) == "198.51.100.7"

    listed = Request(
        {
            "type": "http",
            "client": ("127.0.0.1", 1234),
            "headers": [(b"x-forwarded-for", b"198.51.100.7, 10.0.0.1")],
        }
    )
    assert gateway.client_address(listed) == "127.0.0.1"


def test_hash_ip_never_keeps_the_address():
    assert gateway.hash_ip("203.0.113.7") == gateway.hash_ip("203.0.113.200")
    assert gateway.hash_ip("203.0.113.7") != gateway.hash_ip("203.0.114.7")
