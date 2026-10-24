"""The operator panel: what it may expose, and what it must refuse.

The panel shows the pool, the sources, the generation history and the issued
tokens — everything an operator needs and nothing a visitor may see. That makes
its access control the load-bearing part, and these tests are mostly about that
rather than about the pages.

Two properties are non-negotiable and each has a test that fails loudly:

* **No secret, no data.** An unauthenticated request gets 403 and an empty body.
  Not a page with the data already inline, not a redirect to a login form with
  the data in a hidden field — nothing.
* **Loopback only.** The panel is reachable from the machine and nowhere else,
  so a misconfigured nginx vhost exposing `/admin` still does not hand out the
  token list. The secret is the second layer, not the first.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from hub.api import create_app  # noqa: E402
from hub.store import Store  # noqa: E402

SECRET = "operator-secret-for-tests"


@pytest.fixture
def admin(tmp_path, monkeypatch):
    """An app with a store and the operator secret set.

    The loopback check is satisfied by patching the predicate, because the test
    transport's peer is the literal string `testclient` — not an address, so not
    provably local, so refused. Patching it here keeps every other test in this
    module about *what the panel returns*, while the tests that are about the
    peer check itself patch it back.
    """
    import hub.api as api_module

    monkeypatch.setenv("HUB_BOT_SECRET", SECRET)
    monkeypatch.setattr(api_module, "_is_loopback_request", lambda request: True)
    store = Store(tmp_path)
    store.connect().close()
    return TestClient(create_app(store=store, sources={})), store


def test_nothing_is_served_without_the_secret(admin):
    """No data and no markup — not a page that merely looks empty.

    `/admin` redirects to the login form rather than answering 403: a browser
    cannot show an operator anything useful about a 403, and the first version
    did exactly that. `/admin/data` still answers 403, because a script that
    gets redirected to an HTML form learns nothing it can act on.

    Asserted on the body as well as the status: a handler that renders the panel
    and *then* checks the secret looks correct to a status-code test and is a
    full disclosure.
    """
    api, _ = admin

    panel = api.get("/admin", follow_redirects=False)
    assert panel.status_code == 303, panel.status_code
    assert panel.headers["location"] == "/admin/login"
    assert "hub-token" not in panel.text.lower()

    for path in ("/admin/data",):
        response = api.get(path)
        assert response.status_code == 403, path
        body = response.text.lower()
        for leak in ("token", "secret", "telegram", "hash"):
            assert leak not in body, f"{path} leaked '{leak}' in a 403 body"


def test_a_wrong_secret_is_refused(admin):
    """A near-miss must not pass. Compared with `compare_digest`, not `==`."""
    api, _ = admin
    for wrong in ("", "operator-secret-for-test", "operator-secret-for-testss", SECRET.upper()):
        response = api.get("/admin/data", headers={"x-hub-secret": wrong})
        assert response.status_code == 403, wrong


def test_no_secret_configured_means_no_access(admin, monkeypatch):
    """An unset secret must close the panel, not open it.

    The failure this prevents is the classic one: `if supplied == secret` with
    both empty is `True`, so a host that never configured a secret serves the
    panel to anyone. The check requires the configured secret to be non-empty
    before it compares anything.
    """
    api, _ = admin
    monkeypatch.delenv("HUB_BOT_SECRET", raising=False)
    assert api.get("/admin/data", headers={"x-hub-secret": ""}).status_code == 403
    assert api.get("/admin/data", headers={"x-hub-secret": SECRET}).status_code == 403


def test_the_secret_never_appears_in_a_response(admin):
    """Not in the body, not in a header, not echoed back on failure."""
    api, _ = admin
    for response in (
        api.get("/admin/data", headers={"x-hub-secret": SECRET}),
        api.get("/admin/data"),
        api.get("/admin"),
    ):
        assert SECRET not in response.text
        assert SECRET not in str(dict(response.headers))


def test_the_data_endpoint_reports_pool_sources_and_generations(admin):
    """The panel's data is aggregate pool state, and it carries no addresses.

    Same rule as `/api/v1/stats`: the moment this returns rows from `nodes`, the
    operator panel becomes the scrape that endpoint exists not to be. Counts,
    names and timestamps only.
    """
    api, store = admin
    response = api.get("/admin/data", headers={"x-hub-secret": SECRET})
    assert response.status_code == 200
    payload = response.json()

    assert set(payload) >= {"pool", "sources", "generations", "tokens", "health"}
    # Pool: counts, not nodes.
    assert isinstance(payload["pool"].get("by_country"), list)
    for row in payload["pool"]["by_country"]:
        assert set(row) == {"name", "n"}, row
    # Generations: one row per publish, no payload paths.
    assert isinstance(payload["generations"], list)
    for row in payload["generations"]:
        assert "generation" in row
        assert "path" not in row and "manifest" not in row
    # Sources: URLs and health, which the operator already has in config.
    assert isinstance(payload["sources"], list)


def test_loopback_only_even_with_the_right_secret(tmp_path, monkeypatch):
    """The secret is the second layer; the socket peer is the first.

    A panel that trusts the secret alone hands the token list to anyone who
    finds it — through a proxy, a misconfigured vhost, or a copied secret. The
    peer check means exposure requires the secret *and* a request that arrived
    over loopback, which is a vhost the operator configured on purpose.

    Asserted *without* the fixture's patch, so the real predicate runs: the test
    transport's peer is `testclient`, which is not an address at all, and the
    refusal below is therefore the honest case — a request the panel cannot
    prove came from the machine is refused even when it carries the right
    secret.
    """
    monkeypatch.setenv("HUB_BOT_SECRET", SECRET)
    store = Store(tmp_path)
    store.connect().close()
    api = TestClient(create_app(store=store, sources={}))

    refused = api.get("/admin/data", headers={"x-hub-secret": SECRET})
    assert refused.status_code == 404, (
        "a peer that is not loopback must be refused even with the correct secret"
    )

    # And a loopback peer is accepted, so the check discriminates rather than
    # refusing everything. The pair is the point.
    import hub.api as api_module

    monkeypatch.setattr(api_module, "_is_loopback_request", lambda request: True)
    assert api.get("/admin/data", headers={"x-hub-secret": SECRET}).status_code == 200


# ---- login form ----------------------------------------------------------


def test_the_panel_offers_a_login_form_without_a_secret(admin):
    """A browser cannot set a header, so the panel cannot require one.

    The first version authenticated with `x-hub-secret` and nothing else, which
    meant the panel was reachable only by `curl` or a browser with a header-
    editing extension. That is not a security property, it is an unusable UI: an
    operator who is told "open /admin" and gets 403 has no way to find out why.

    `/admin/login` is served to anyone who reaches it, and carries no data.
    """
    api, _ = admin
    response = api.get("/admin/login")
    assert response.status_code == 200
    body = response.text
    assert "<form" in body.lower(), "no form on the login page"
    assert 'type="password"' in body, "the secret field must not be a plain text input"


def test_the_login_page_carries_no_pool_data(admin):
    """Served without authentication, so it must contain nothing worth having."""
    api, store = admin
    conn = store.connect()
    conn.execute(
        "INSERT INTO nodes (dedup_key, protocol, address, port, country, source,"
        " first_seen, last_ok, score, rounds) VALUES ('k','vless','203.0.113.77',"
        " 443,'NL','s','2026-10-16T10:00:00+00:00','2026-10-16T10:00:00+00:00',40,1)"
    )
    conn.commit()
    conn.close()
    body = api.get("/admin/login").text
    assert "203.0.113.77" not in body
    assert SECRET not in body


def test_a_correct_secret_sets_a_cookie_and_opens_the_panel(admin):
    """The form posts the secret, gets a cookie, and the cookie opens the panel."""
    api, _ = admin
    response = api.post("/admin/login", data={"secret": SECRET}, follow_redirects=False)
    assert response.status_code in (302, 303), response.status_code
    cookie = response.cookies.get("hub_admin")
    assert cookie, "no session cookie was set"
    # The session value must not be the secret itself: a cookie is readable by
    # anything on the machine and ends up in browser history exports.
    assert SECRET not in cookie

    opened = api.get("/admin/data", cookies={"hub_admin": cookie})
    assert opened.status_code == 200


def test_a_wrong_secret_sets_no_cookie(admin):
    api, _ = admin
    response = api.post("/admin/login", data={"secret": "nope"}, follow_redirects=False)
    assert response.status_code == 403
    assert not response.cookies.get("hub_admin"), "a cookie was issued for a wrong secret"


def test_a_forged_cookie_is_refused(admin):
    """The cookie is signed, so a made-up value cannot pass.

    This is the property that lets the session live in the cookie at all
    instead of a server-side table: the server verifies an HMAC rather than
    looking anything up, and an attacker who can write cookies cannot mint one
    without the key.
    """
    api, _ = admin
    for forged in ("admin", "1", "true", SECRET, "a.b.c", "x" * 64):
        assert api.get("/admin/data", cookies={"hub_admin": forged}).status_code == 403, forged


def test_a_cookie_signed_with_another_key_is_refused(admin, monkeypatch):
    """The signature is checked against the *current* secret, not just any HMAC.

    A token minted before the secret was rotated must stop working — otherwise
    rotation is cosmetic, which is the whole reason an operator rotates.
    """
    api, _ = admin
    login = api.post("/admin/login", data={"secret": SECRET}, follow_redirects=False)
    cookie = login.cookies.get("hub_admin")
    assert api.get("/admin/data", cookies={"hub_admin": cookie}).status_code == 200

    monkeypatch.setenv("HUB_BOT_SECRET", "rotated-to-something-else")
    assert api.get("/admin/data", cookies={"hub_admin": cookie}).status_code == 403


def test_the_header_still_works_for_scripts(tmp_path, monkeypatch):
    """The cookie is for browsers; the header stays for `curl` and cron.

    Dropping it would break every scripted call that already exists, and the
    header path was never the problem — the absence of a browser-friendly one
    was. Asserted against the real loopback predicate, so this also proves the
    header check runs *after* the peer check rather than instead of it.
    """
    import hub.api as api_module

    monkeypatch.setenv("HUB_BOT_SECRET", SECRET)
    store = Store(tmp_path)
    store.connect().close()
    api = TestClient(create_app(store=store, sources={}))

    # Not loopback: hidden like a missing page, even with the right header.
    assert api.get("/admin/data", headers={"x-hub-secret": SECRET}).status_code == 404

    monkeypatch.setattr(api_module, "_is_loopback_request", lambda request: True)
    assert api.get("/admin/data", headers={"x-hub-secret": SECRET}).status_code == 200


def test_logout_clears_the_cookie(admin):
    api, _ = admin
    login = api.post("/admin/login", data={"secret": SECRET}, follow_redirects=False)
    cookie = login.cookies.get("hub_admin")
    out = api.post("/admin/logout", cookies={"hub_admin": cookie}, follow_redirects=False)
    assert out.status_code in (302, 303)
    cleared = out.cookies.get("hub_admin")
    assert cleared in (None, "", '""'), "the cookie was not cleared"


# ---- key issuing in the panel --------------------------------------------


def _login(api):
    """A session cookie, so the key tests do not each repeat the dance."""
    response = api.post("/admin/login", data={"secret": SECRET}, follow_redirects=False)
    return response.cookies.get("hub_admin")


def test_the_panel_can_mint_a_key_without_telegram(admin):
    """Keys are issued from the panel, so Telegram is optional rather than required.

    The bot was the only way to mint a key, which makes it a dependency of the
    product rather than an optional channel: an operator with no bot token — the
    shipped default — could not hand out a subscription at all. The README says
    the bot degrades to "the web page still works"; for keys it did not, because
    there was no other way in.

    The token is returned **once**, at creation. It is stored as a SHA-256 digest,
    so a later request cannot recover it — which is why the response has to carry
    it and why the panel shows a copy prompt rather than a table cell.
    """
    api, store = admin
    cookie = _login(api)
    response = api.post(
        "/admin/keys/issue", data={"label": "тест"}, cookies={"hub_admin": cookie}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["token"], payload
    assert len(payload["token"]) >= 40, "the token must not be guessable"

    # It is stored, by digest, and active.
    conn = store.connect()
    row = conn.execute(
        "SELECT telegram_id, status FROM subscription_tokens WHERE token_hash = ?",
        (__import__("hashlib").sha256(payload["token"].encode()).hexdigest(),),
    ).fetchone()
    conn.close()
    assert row is not None, "the issued key is not in the store"
    assert row[1] == "active"


def test_a_minted_key_actually_works_as_a_subscription(admin):
    """End to end: mint it in the panel, fetch it as a client.

    The failure this catches is a key that is stored but not resolvable — the
    panel says "issued" and the client gets 404. The two code paths share the
    store but not the lookup, so both have to be exercised.

    A generation is written by hand first: without one the endpoint answers 503,
    which is correct and would make this test pass for the wrong reason.
    """
    api, store = admin
    generation = store.generation_path("gen-keys")
    generation.mkdir(parents=True, exist_ok=True)
    (generation / "verified-xray.base64").write_text("dmxlc3M6Ly94", encoding="utf-8")
    (generation / "manifest.json").write_text(
        '{"generation":"gen-keys","sha256":"' + "a" * 64 + '","payloads":[]}',
        encoding="utf-8",
    )
    store.flip_pointer("gen-keys", "a" * 64)

    cookie = _login(api)
    token = api.post(
        "/admin/keys/issue", data={"label": ""}, cookies={"hub_admin": cookie}
    ).json()["token"]
    assert api.get(f"/sub/{token}?format=base64").status_code == 200


def test_the_panel_can_revoke_a_key(admin):
    """Revoking has to work from the panel too, or issuing is one-way."""
    api, _ = admin
    cookie = _login(api)
    token = api.post(
        "/admin/keys/issue", data={"label": ""}, cookies={"hub_admin": cookie}
    ).json()["token"]
    digest = __import__("hashlib").sha256(token.encode()).hexdigest()

    revoked = api.post(
        "/admin/keys/revoke", data={"id": digest[:12]}, cookies={"hub_admin": cookie}
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert api.get(f"/sub/{token}").status_code == 404, "a revoked key still serves"


def test_issuing_needs_a_session(admin):
    """The endpoints that change state are behind the same check as the panel."""
    api, _ = admin
    assert api.post("/admin/keys/issue", data={"label": "x"}).status_code == 403
    assert api.post("/admin/keys/revoke", data={"id": "abc"}).status_code == 403


def test_the_token_list_shows_only_digest_prefixes(admin):
    """The list cannot show a token it does not have, and must not pretend to."""
    api, _ = admin
    cookie = _login(api)
    api.post("/admin/keys/issue", data={"label": "one"}, cookies={"hub_admin": cookie})
    payload = api.get("/admin/data", cookies={"hub_admin": cookie}).json()
    for row in payload["tokens"]:
        assert len(row["id"]) <= 12, row
        assert set(row) >= {"id", "status", "created_at", "label"}
