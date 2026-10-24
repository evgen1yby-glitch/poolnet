"""The pool page's query API: filtering, pagination, and its validation.

The page used to render ten static rows under controls that did nothing.
`query_proxies` is the part that makes the controls real: one cached index of
the publication, a linear scan per request, and a slice. These tests pin the
order the page promises (30-day uptime, then latency), that filters compose,
and that bad parameters are a 400 rather than a silently empty table.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from hub import poolstatus  # noqa: E402
from hub.api import create_app  # noqa: E402
from hub.store import Store  # noqa: E402


def _publication(tmp_path: Path) -> Path:
    pool = tmp_path / "pub"
    pool.mkdir()
    rows = [
        {"protocol": "http", "host": "10.0.0.1", "port": 80, "latency_ms": 10,
         "anonymity": "elite", "country": "DE", "uptime_30d": 100, "uptime_7d": 100},
        {"protocol": "http", "host": "10.0.0.2", "port": 80, "latency_ms": 5,
         "anonymity": "elite", "country": "DE", "uptime_30d": 100, "uptime_7d": 99},
        {"protocol": "socks5", "host": "10.0.0.3", "port": 1080, "latency_ms": 20,
         "anonymity": "anonymous", "country": "US", "uptime_30d": 90, "uptime_7d": 95},
        {"protocol": "socks4", "host": "10.0.0.4", "port": 1080, "latency_ms": 30,
         "anonymity": "transparent", "country": "CA", "uptime_30d": 80, "uptime_7d": 90},
        {"protocol": "http", "host": "10.0.0.5", "port": 8080, "latency_ms": 40,
         "anonymity": "unknown", "country": "US", "uptime_30d": 70, "uptime_7d": 80},
    ]
    (pool / "proxies.json").write_text(json.dumps({"proxies": rows}), encoding="utf-8")
    return pool


def test_default_order_and_pagination(tmp_path):
    pool = _publication(tmp_path)
    first = poolstatus.query_proxies(pool, page=1, per=2)
    assert first["total"] == 5
    assert first["pages"] == 3
    assert [row["address"] for row in first["rows"]] == ["10.0.0.2:80", "10.0.0.1:80"]
    assert first["pool_total"] == 5
    second = poolstatus.query_proxies(pool, page=2, per=2)
    assert [row["rank"] for row in second["rows"]] == [3, 4]
    last = poolstatus.query_proxies(pool, page=99, per=2)
    assert last["page"] == 3
    assert [row["address"] for row in last["rows"]] == ["10.0.0.5:8080"]


def test_filters_compose(tmp_path):
    pool = _publication(tmp_path)
    de = poolstatus.query_proxies(pool, country="DE")
    assert {row["country"] for row in de["rows"]} == {"DE"}
    elite = poolstatus.query_proxies(pool, grades=("elite",))
    assert elite["total"] == 2
    socks = poolstatus.query_proxies(pool, protocols=("socks5", "socks4"))
    assert {row["protocol"] for row in socks["rows"]} == {"socks5", "socks4"}
    combo = poolstatus.query_proxies(
        pool, protocols=("http",), grades=("elite",), country="DE", query="0.0.1"
    )
    assert combo["total"] == 1
    assert combo["rows"][0]["address"] == "10.0.0.1:80"
    assert combo["rows"][0]["rank"] == 1


def test_country_facets_cover_the_whole_publication(tmp_path):
    facets = poolstatus.query_proxies(_publication(tmp_path))["countries"]
    assert facets == [{"cc": "DE", "n": 2}, {"cc": "US", "n": 2}, {"cc": "CA", "n": 1}]


def test_missing_publication_is_empty_not_an_error(tmp_path):
    result = poolstatus.query_proxies(tmp_path / "absent")
    assert result["available"] is False
    assert result["total"] == 0
    assert result["rows"] == []


def _client(tmp_path: Path, monkeypatch, pool: Path) -> TestClient:
    monkeypatch.setenv("POOLNET_POOL_DIR", str(pool))
    monkeypatch.setenv("HUB_SITE", str(tmp_path / "no-site"))
    return TestClient(create_app(store=Store(tmp_path / "store")))


def test_endpoint_returns_a_page_and_is_not_cached(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, _publication(tmp_path))
    response = client.get("/api/proxies", params={"per": 2, "country": "DE"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["total"] == 2
    assert len(body["rows"]) == 2
    assert body["rows"][0]["country"] == "DE"


@pytest.mark.parametrize(
    ("params", "fragment"),
    [
        ({"proto": "ftp"}, "proto"),
        ({"grade": "legendary"}, "grade"),
        ({"country": "DEU"}, "country"),
    ],
)
def test_endpoint_rejects_unknown_filters(tmp_path, monkeypatch, params, fragment):
    client = _client(tmp_path, monkeypatch, _publication(tmp_path))
    response = client.get("/api/proxies", params=params)
    assert response.status_code == 400
    assert fragment in response.json()["error"]
