"""Public VPN payloads: only files the generation manifest declares."""

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
def client(tmp_path):
    store = Store(tmp_path)
    generation = "gen-vpn-public"
    directory = store.generation_path(generation)
    directory.mkdir(parents=True)
    (directory / "verified-sing-box.base64").write_text("dmxlc3M6Ly8=", encoding="utf-8")
    (directory / "verified-sing-box.singbox").write_text('{"outbounds":[]}', encoding="utf-8")
    (directory / "private.tmp").write_text("not for the public", encoding="utf-8")
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "generation": generation,
                "sha256": "a" * 64,
                "payloads": [
                    {"name": "verified-sing-box.base64", "nodes": 1},
                    {"name": "verified-sing-box.singbox", "nodes": 1},
                ],
            }
        ),
        encoding="utf-8",
    )
    store.flip_pointer(generation, "a" * 64)
    return TestClient(create_app(store=store))


def test_manifest_listed_payload_is_served(client):
    response = client.get("/vpn/verified-sing-box.base64")
    assert response.status_code == 200
    assert response.text == "dmxlc3M6Ly8="
    assert response.headers["content-type"].startswith("text/plain")


def test_unlisted_file_is_not_served(client):
    assert client.get("/vpn/private.tmp").status_code == 404
    assert client.get("/vpn/../hub.db").status_code == 404
