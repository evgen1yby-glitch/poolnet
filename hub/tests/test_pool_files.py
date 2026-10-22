"""`/pool/*` — the proxy base's published files, served by the hub.

The site's copy points readers at internal paths instead of the demo port,
so the hub hands out exactly the files the pool engine published into the
shared data dir. Pinned here: the allow-list (a request for `all.json` or
`/pool/makefile` is a probe, not a mistake worth answering), the country
shard naming (`country/XX.txt`, two uppercase letters — anything else is a
path), the content types, and the 404 for everything else, including a hub
installed without a proxy base.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from hub.api import create_app  # noqa: E402
from hub.store import Store  # noqa: E402


@pytest.fixture()
def make_client(monkeypatch):
    def _make(pool_dir: Path | None) -> TestClient:
        tmp = Path(f"/tmp/opencode/pooltest-{id(monkeypatch)}")
        if pool_dir is not None:
            monkeypatch.setenv("EVILGATE_POOL_DIR", str(pool_dir))
        else:
            monkeypatch.setenv("EVILGATE_POOL_DIR", str(tmp / "absent"))
        return TestClient(create_app(store=Store(tmp)))

    return _make


def _pool_dir(tmp_path: Path) -> Path:
    pool = tmp_path / "pooldir"
    pool.mkdir()
    (pool / "http.txt").write_text("1.2.3.4:8080\n5.6.7.8:3128\n", encoding="utf-8")
    (pool / "socks4.txt").write_text("1.2.3.4:1080\n", encoding="utf-8")
    (pool / "country").mkdir()
    (pool / "country/CA.txt").write_text("1.2.3.4:8080\n", encoding="utf-8")
    (pool / "proxies.json").write_text('{"ok":true}', encoding="utf-8")
    (pool / "meta.json").write_text('{"runId":"12345678"}', encoding="utf-8")
    (pool / "secret.txt").write_text("should not be served\n", encoding="utf-8")
    return pool


def test_line_lists_and_json_are_served(make_client, tmp_path):
    pool = _pool_dir(tmp_path)
    c = make_client(pool)
    r = c.get("/pool/http.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "1.2.3.4:8080" in r.text
    assert c.get("/pool/socks4.txt").status_code == 200
    r = c.get("/pool/proxies.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"ok": True}
    assert c.get("/pool/meta.json").status_code == 200


def test_country_shard_served(make_client, tmp_path):
    c = make_client(_pool_dir(tmp_path))
    r = c.get("/pool/country/CA.txt")
    assert r.status_code == 200
    assert "1.2.3.4:8080" in r.text


def test_country_shard_name_is_strict(make_client, tmp_path):
    c = make_client(_pool_dir(tmp_path))
    for probe in (
        "/pool/country/ca.txt",
        "/pool/country/CAX.txt",
        "/pool/country/CA.json",
    ):
        assert c.get(probe).status_code == 404, probe


def test_allow_list_is_closed(make_client, tmp_path):
    c = make_client(_pool_dir(tmp_path))
    for probe in (
        "/pool/secret.txt",
        "/pool/roast.json",
        "/pool/sourcecheck-spys-one-en.json",
    ):
        assert c.get(probe).status_code == 404, probe


def test_no_proxy_base_is_all_404(make_client):
    c = make_client(None)
    assert c.get("/pool/http.txt").status_code == 404
