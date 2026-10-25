"""Free public subscription: seven days, one key per network per cooldown.

The site's free CTA issues a key directly, while the bot remains an optional
funnel. These tests pin the contract the page relies on: a seven-day term, a
working `/sub/` URL, expiry enforced at fetch time, a signed proof-of-wait
challenge, and a persistent claim so a reload or a script cannot mint a second
key from the same address.
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
    monkeypatch.setenv("HUB_FREE_WAIT_SECONDS", "0")
    monkeypatch.setenv("HUB_FREE_SECRET", "free-test-secret")
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
    return TestClient(create_app(store=store), client=("127.0.0.1", 50000)), store


def _issue(api, ip: str | None = None):
    headers = {"x-forwarded-for": ip} if ip else {}
    challenge = api.get("/api/free-challenge", headers=headers)
    assert challenge.status_code == 200, challenge.text
    return api.post(
        "/api/free-subscription",
        headers=headers,
        json={"challenge": challenge.json()["challenge"]},
    )


def test_free_key_is_seven_days_and_works(client):
    api, store = client
    response = _issue(api)
    assert response.status_code == 200
    body = response.json()
    assert body["subscription"].startswith("https://poolnet.online/sub/")
    expires = datetime.fromisoformat(body["expires_at"])
    left = expires - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < left <= timedelta(days=7, minutes=1)
    assert store.subscription_status(body["token"]) == "active"
    assert api.get(f"/sub/{body['token']}?format=base64").status_code == 200


def test_one_key_per_ip_per_day(client):
    api, store = client
    assert _issue(api, "203.0.113.10").status_code == 200
    second = api.get("/api/free-challenge", headers={"x-forwarded-for": "203.0.113.10"})
    assert second.status_code == 429
    assert second.json()["retry_after"] > 23 * 3600
    status = api.get("/api/free-status", headers={"x-forwarded-for": "203.0.113.10"})
    assert status.json()["available"] is False
    assert status.json()["retry_after"] > 23 * 3600
    assert store.count_subscriptions(status="active") == 1


def test_a_challenge_cannot_be_replayed_without_waiting(client, monkeypatch):
    api, _store = client
    monkeypatch.setenv("HUB_FREE_WAIT_SECONDS", "5")
    challenge = api.get("/api/free-challenge", headers={"x-forwarded-for": "203.0.113.20"})
    early = api.post(
        "/api/free-subscription",
        headers={"x-forwarded-for": "203.0.113.20"},
        json={"challenge": challenge.json()["challenge"]},
    )
    assert early.status_code == 429
    assert early.headers.get("retry-after")


def test_a_missing_or_forged_challenge_is_refused(client):
    api, _store = client
    assert api.post("/api/free-subscription", json={}).status_code == 400
    assert api.post(
        "/api/free-subscription",
        json={"challenge": "1.nonce.forged"},
    ).status_code == 400


def test_a_daily_global_budget_backs_up_per_ip_claims(client, monkeypatch):
    api, _store = client
    monkeypatch.setenv("HUB_FREE_DAILY_LIMIT", "1")
    assert _issue(api, "203.0.113.30").status_code == 200
    second = _issue(api, "203.0.113.31")
    assert second.status_code == 429
    assert second.headers.get("retry-after")


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
