"""Free public subscription: seven days, no account, rate-limited by subnet.

The site's free CTA issues a key directly, while the bot remains an optional
funnel. These tests pin the contract the page relies on: a seven-day term, a
working `/sub/` URL, expiry enforced at fetch time, and a burst limit so one
network cannot mint an unlimited supply.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    monkeypatch.setenv("HUB_BASE_URL", "https://poolnet.online")
    store = Store(tmp_path)
    generation = store.generation_path("gen-test")
    generation.mkdir(parents=True, exist_ok=True)
    (generation / "verified-sing-box.singbox").write_text('{"ok":true}', encoding="utf-8")
    (generation / "verified-sing-box.base64").write_text(
        "c29ja3M1Oi8vMS4yLjMuNDoxMDgwCg==", encoding="utf-8"
    )
    (generation / "manifest.json").write_text(
        '{"generation":"gen-test","sha256":"' + "a" * 64 + '","payloads":[]}',
        encoding="utf-8",
    )
    store.flip_pointer("gen-test", "a" * 64)
    return TestClient(create_app(store=store)), store


def test_free_key_is_seven_days_and_works(client):
    api, store = client
    response = api.post("/api/free-subscription")
    assert response.status_code == 200
    body = response.json()
    assert body["subscription"].startswith("https://poolnet.online/sub/")
    expires = datetime.fromisoformat(body["expires_at"])
    left = expires - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < left <= timedelta(days=7, minutes=1)
    assert store.subscription_status(body["token"]) == "active"
    assert api.get(f"/sub/{body['token']}?format=base64").status_code == 200


def test_free_keys_are_rate_limited(client):
    api, _store = client
    codes = [api.post("/api/free-subscription").status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429


def test_expired_key_is_a_404_and_admin_reports_it(client):
    api, store = client
    token = "expired-test-token"
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert store.issue_subscription(token, 0, expires_at=past, source="web")
    assert store.subscription_status(token) == "expired"
    assert api.get(f"/sub/{token}").status_code == 404


def test_extend_moves_the_expiry_and_touch_records_last_seen(client):
    api, store = client
    token = "extend-test-token"
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert store.issue_subscription(token, 0, expires_at=past, source="panel")
    import hashlib
    digest = hashlib.sha256(token.encode()).hexdigest()
    assert store.extend_subscription(digest[:12], 3) == 1
    assert store.subscription_status(token) == "active"
    assert api.get(f"/sub/{token}").status_code == 200
    conn = store.connect()
    try:
        seen = conn.execute(
            "SELECT last_seen FROM subscription_tokens WHERE token_hash LIKE ?",
            (__import__("hashlib").sha256(token.encode()).hexdigest()[:12] + "%",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert seen
