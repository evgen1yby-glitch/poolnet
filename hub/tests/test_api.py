"""API contract tests. Run against the FastAPI app with a real Store.

These pin the exact response contract that clients depend on, because a header
regression is invisible until a user imports the subscription.
"""

from __future__ import annotations

import json
import os
import re
import sys
import base64
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from hub.api import (  # noqa: E402
    NO_EXPIRY,
    _CLIENT_EXT,
    _CONTENT_TYPE,
    _DEFAULT_EXT,
    _FMT_BY_QUERY,
    _FMT_EXT,
    _client_headers,
    _profile_title,
    create_app,
)  # noqa: E402
from hub.models import Format, Tier  # noqa: E402
from hub.store import Store  # noqa: E402


def test_expire_is_a_real_far_future_timestamp():
    """expire=0 means 1970-01-01 to a client, i.e. 'already expired'."""
    assert NO_EXPIRY > 4102444800  # after 2100-01-01
    headers = _client_headers("test", Tier.CURATED, "sing-box", Format.SINGBOX, "https://x.dev")
    assert f"expire={NO_EXPIRY}" in headers["subscription-userinfo"]
    assert "total=0" in headers["subscription-userinfo"]
    assert "upload=0" in headers["subscription-userinfo"]


def test_empty_base_url_drops_url_headers():
    headers = _client_headers("test", Tier.VERIFIED, "xray", Format.BASE64, "")
    assert "profile-web-page-url" not in headers
    assert "support-url" not in headers
    assert headers["content-disposition"].startswith("attachment;")


def test_profile_title_is_present_and_within_happ_limit():
    """Happ renders `profile-title` and truncates at 25 chars.

    The header is absent today, so a Happ import shows the raw URL as the
    profile name. 25 is Happ's documented ceiling: a longer value is silently
    cut, which reads as a truncated name rather than as a bug in this service.
    """
    headers = _client_headers("test", Tier.VERIFIED, "xray", Format.BASE64, "https://x.dev")
    assert "profile-title" in headers
    assert headers["profile-title"]
    title = headers["profile-title"]
    if title.startswith("base64:"):
        import base64 as _b64

        title = _b64.b64decode(title[len("base64:") :]).decode("utf-8")
    # Happ counts characters, not bytes.
    assert len(title) <= 25, title


def test_profile_title_is_a_whole_name_for_every_core():
    """A length ceiling is not a shape check.

    `?unique=1` serves a rotation variant whose core is `unique-rot10`, and
    `hub verified (unique-rot10)` is 27 characters. Slicing it at 25 produced
    `hub verified (unique-rot1`: inside the limit, and an unbalanced
    parenthesis — a name that reads as corrupted rather than as long. The
    invariant is that the value is a complete, balanced name at every core the
    server can choose.
    """
    cores = [
        "auto",
        "sing-box",
        "mihomo",
        "xray",
        "unique-rot0",
        "unique-rot9",
        "unique-rot10",
        "unique-rot999",
    ]
    for core in cores:
        title = _profile_title(Tier.VERIFIED, core)
        assert len(title) <= 25, (core, title)
        assert title.startswith("hub "), (core, title)
        assert title.count("(") == title.count(")"), (core, title)
        assert not title.endswith("("), (core, title)
        assert not title.endswith("-"), (core, title)


def test_profile_title_keeps_the_core_when_it_fits():
    """Abbreviation is for the rotation counter only, not for every core: the
    client shows this name to tell profiles apart, so `(xray)` and `(mihomo)`
    have to survive."""
    assert _profile_title(Tier.VERIFIED, "xray") == "hub verified (xray)"
    assert _profile_title(Tier.VERIFIED, "unique-rot1") == "hub verified (unique)"


def test_support_url_points_at_a_route_that_exists(client, monkeypatch):
    """A support link that 404s is worse than no link: Happ renders it as a tile.

    The header was built as `{base_url}/help` and no `/help` route exists, so
    every client that displays `support-url` offered a dead link.
    """
    api, _ = client
    monkeypatch.setenv("HUB_TOKEN", "t")
    response = api.get("/sub/t")
    url = response.headers["support-url"]
    assert url.startswith("https://nodes.example")
    path = url[len("https://nodes.example") :] or "/"
    assert api.get(path).status_code == 200, f"{path} is advertised but does not exist"


def test_head_covers_every_subscription_route_not_just_the_default(client, monkeypatch):
    """One rewrite in the ASGI layer, so no route is left answering 405.

    An `@app.head` handler per route was the first attempt and it broke: the
    subscription handlers are closures inside `create_app`, so the sibling
    handler raised `NameError: name '_subscription_country' is not defined` and
    the country route returned **500** to a HEAD. This pins all three forms.
    """
    api, _ = client
    monkeypatch.setenv("HUB_TOKEN", "t")
    for path in ("/sub/t", "/sub/t/verified"):
        head = api.head(path)
        assert head.status_code == 200, f"{path} -> {head.status_code}"
        assert head.content == b"", path
        assert "subscription-userinfo" in head.headers, path

    # The country form has no shard in this fixture, so 404 is the honest
    # answer — the point is that it is no longer 405 *or* 500. 405 was the
    # missing HEAD registration; 500 was the `@app.head` attempt calling a
    # closure it could not see.
    country = api.head("/sub/t/country/fi")
    assert country.status_code == 404, country.status_code


def test_head_keeps_the_content_length_of_the_get(client, monkeypatch):
    """RFC 9110: HEAD reports the headers the GET would, body omitted."""
    api, _ = client
    monkeypatch.setenv("HUB_TOKEN", "t")
    get = api.get("/sub/t")
    head = api.head("/sub/t")
    assert head.headers["content-length"] == get.headers["content-length"]


def test_help_page_is_served_and_self_contained(client):
    """`support-url` is rendered as a tappable tile, so it must resolve."""
    api, _ = client
    response = api.get("/help")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    # No external asset: the page is opened from a client's import screen on
    # networks where this host may be the only thing that answers.
    assert "http://" not in body
    assert "<script" not in body


def test_head_request_gets_headers_not_405(client, monkeypatch):
    """HEAD must mirror GET: probing a subscription with HEAD is routine.

    FastAPI's `@app.get` does not add HEAD, so the app answered 405. A client
    (or an operator's health check) that probes with HEAD concludes the
    subscription is broken while GET works, which is the confusing half of the
    bug.
    """
    api, _ = client
    monkeypatch.setenv("HUB_TOKEN", "t")
    head = api.head("/sub/t")
    assert head.status_code == 200
    assert "subscription-userinfo" in head.headers
    assert head.headers["content-type"].startswith("application/json")
    # A HEAD response carries the headers of the GET and no body.
    assert head.content == b""


def test_content_type_per_format():
    # No hand-copied table here: a drift between the served type and the
    # renderer's body is invisible until a client silently drops the payload.
    assert _EXT_TYPE(Format.SINGBOX) == "application/json; charset=utf-8"
    assert _EXT_TYPE(Format.BASE64) == "text/plain; charset=utf-8"
    assert _EXT_TYPE(Format.CLASH) == "application/x-yaml; charset=utf-8"


def _EXT_TYPE(fmt: Format) -> str:
    return _CONTENT_TYPE[fmt]


def test_client_filename_extension_is_not_the_disk_extension():
    """The two extensions are different on purpose.

    `Content-Disposition` carries the conventional `.json`/`.txt`/`.yaml` that
    clients recognise; the on-disk name is the pipeline's `fmt.value`. Asserting
    they differ pins the distinction — collapsing them back into one map is what
    made the API look for `verified-sing-box.json` while the pipeline wrote
    `verified-sing-box.singbox`.
    """
    assert _CLIENT_EXT[Format.SINGBOX] != _FMT_EXT[Format.SINGBOX]
    assert _CLIENT_EXT[Format.SINGBOX] == "json"


def test_lookup_extension_matches_what_the_pipeline_writes():
    """The reader's map must be the writer's spelling, byte for byte."""
    for fmt, ext in _FMT_EXT.items():
        assert ext == fmt.value
        assert _FMT_BY_QUERY[ext] is fmt


def test_every_format_is_reachable_from_a_query():
    """No format can be unreachable just because it has no query alias.

    Two spellings must both resolve: the on-disk name an operator or a manifest
    link carries (`singbox`), and the client-facing extension `Content-
    Disposition` advertises (`json`). A `?format=` reader that only knew the
    first made `?format=yaml` silently fall back to the sing-box dialect, so a
    request for a Clash payload was answered with sing-box JSON.
    """
    for fmt, ext in _FMT_EXT.items():
        assert _FMT_BY_QUERY[ext] is fmt
        assert _FMT_BY_QUERY[_CLIENT_EXT[fmt]] is fmt
    assert _DEFAULT_EXT is Format.SINGBOX.value


# --------------------------------------------------------------------------- #
# app
# --------------------------------------------------------------------------- #


@pytest.fixture()
def client(tmp_path):
    store = Store(tmp_path)
    generation = store.generation_path("gen-test")
    generation.mkdir(parents=True, exist_ok=True)
    # Names exactly as `pipeline._publish` writes them: `{tier}-{core}.{fmt}`
    # where `fmt` is the lowercase Format *value*. These are asserted, not
    # written by hand: `tests/test_fixtures.py` pins the same rule for every
    # payload a pipeline actually produces, so a drift between writer and reader
    # fails a test instead of 404-ing in production.
    (generation / "verified-sing-box.singbox").write_text('{"ok":true}', encoding="utf-8")
    (generation / "verified-xray.base64").write_text("vless://x", encoding="utf-8")
    (generation / "verified-mihomo.clash").write_text("proxies: []", encoding="utf-8")
    (generation / "curated-sing-box.singbox").write_text('{"ok":true}', encoding="utf-8")
    (generation / "manifest.json").write_text(
        json.dumps({"generation": "gen-test", "sha256": "a" * 64, "payloads": []}),
        encoding="utf-8",
    )
    store.flip_pointer("gen-test", "a" * 64)
    app = create_app(store=store, sources={"base_url": "https://nodes.example"})
    return TestClient(app), store


def test_unknown_token_is_404(client):
    api, _ = client
    response = api.get("/sub/does-not-exist")
    assert response.status_code == 404


def test_operator_token_serves_payload(client, monkeypatch):
    api, _ = client
    monkeypatch.setenv("HUB_TOKEN", "operatortoken")
    response = api.get("/sub/operatortoken")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers["content-type"].startswith("application/json")
    assert "subscription-userinfo" in response.headers
    assert response.headers["profile-update-interval"] == "6"
    assert response.headers["profile-web-page-url"] == "https://nodes.example"
    assert response.headers["content-disposition"].endswith('verified-sing-box.json"')


def test_format_query_selects_the_dialect(client, monkeypatch):
    api, _ = client
    monkeypatch.setenv("HUB_TOKEN", "t")
    clash = api.get("/sub/t", params={"format": "yaml"})
    assert clash.status_code == 200
    assert clash.text == "proxies: []"
    assert clash.headers["content-type"].startswith("application/x-yaml")

    base64 = api.get("/sub/t?format=txt")
    assert base64.status_code == 200
    assert base64.text == "vless://x"

    # An unknown format falls back to the sing-box dialect, not to a 404.
    unknown = api.get("/sub/t?format=toml")
    assert unknown.status_code == 200
    assert unknown.headers["content-type"].startswith("application/json")


def test_missing_payload_for_a_tier_404s_with_the_available_list(client, monkeypatch):
    api, _ = client
    monkeypatch.setenv("HUB_TOKEN", "t")
    response = api.get("/sub/t", params={"format": "yaml"})
    assert response.status_code == 200  # mihomo clash exists for verified
    # Curated has no clash payload for any core in this generation.
    response = api.get("/sub/t/curated", params={"format": "yaml"})
    assert response.status_code == 404
    assert any(name.endswith("curated-sing-box.singbox") for name in response.json()["available"])


def test_curated_tier_selection(client, monkeypatch):
    api, _ = client
    monkeypatch.setenv("HUB_TOKEN", "operatortoken")
    response = api.get("/sub/operatortoken/curated")
    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith('curated-sing-box.json"')


def test_unknown_tier_is_404_not_500(client, monkeypatch):
    """`Tier("garbage")` raises; a URL typo must not take the endpoint down."""
    api, _ = client
    monkeypatch.setenv("HUB_TOKEN", "t")
    assert api.get("/sub/t/platinum").status_code == 404
    assert api.get("/sub/t/CURATED").status_code == 200


def test_healthz_reports_generation(client):
    api, _ = client
    response = api.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["generation"] == "gen-test"


def test_no_generation_is_503(tmp_path):
    store = Store(tmp_path)
    api = TestClient(create_app(store=store))
    response = api.get("/healthz")
    assert response.status_code == 503


def test_stale_threshold_is_longer_than_the_probe_cycle():
    """A healthy box must read `ok` for most of the cycle, not `stale`.

    The first threshold was one hour while `hub-probe.timer` re-checks every
    six, so `/healthz` was red five hours out of six on a box with nothing
    wrong with it. Rather than assert the number (which would just pin one
    arbitrary constant), this reads the cadence out of the timer that actually
    runs the probe and requires the threshold to cover a whole cycle plus
    slack. If someone changes the schedule, this fails instead of the
    endpoint quietly turning permanently red.

    `HUB_STALE_AFTER_HOURS` is honoured, and an unparseable override falls back
    rather than raising: this is a monitoring knob, not a startup requirement.
    """
    from hub.api import _DEFAULT_STALE_AFTER_HOURS

    timer = Path(__file__).resolve().parents[1] / "deploy" / "hub-probe.timer"
    body = timer.read_text(encoding="utf-8")
    match = re.search(r"^OnCalendar=00/(\d+):", body, re.MULTILINE)
    assert match, "hub-probe.timer no longer uses the 00/N:MM cadence this test reads"
    cycle_hours = int(match.group(1))

    assert _DEFAULT_STALE_AFTER_HOURS > cycle_hours, (
        f"the probe runs every {cycle_hours}h but the threshold is "
        f"{_DEFAULT_STALE_AFTER_HOURS}h: a healthy box would report stale"
    )


def test_stale_override_is_optional_and_forgiving(monkeypatch):
    from hub.api import _DEFAULT_STALE_AFTER_HOURS, _stale_after_hours

    monkeypatch.delenv("HUB_STALE_AFTER_HOURS", raising=False)
    assert _stale_after_hours() == _DEFAULT_STALE_AFTER_HOURS

    monkeypatch.setenv("HUB_STALE_AFTER_HOURS", "12")
    assert _stale_after_hours() == 12.0

    for bad in ("", "soon", "0", "-3"):
        monkeypatch.setenv("HUB_STALE_AFTER_HOURS", bad)
        assert _stale_after_hours() == _DEFAULT_STALE_AFTER_HOURS, bad


def test_healthz_uses_the_same_threshold_as_the_panel(client, monkeypatch):
    """Both surfaces read one helper, so they cannot disagree.

    `/healthz` and the admin panel each had their own `3600` literal. Two copies
    of a threshold is two chances to change one and not the other, and the
    disagreement is invisible: the panel would show "всё свежее" over a
    generation the health endpoint calls stale.
    """
    api, store = client
    manifest = store.generation_path("gen-test") / "manifest.json"
    # Two hours old: stale under the old one-hour rule, fresh under the
    # schedule-derived one.
    two_hours_ago = manifest.stat().st_mtime - 2 * 3600
    os.utime(manifest, (two_hours_ago, two_hours_ago))

    assert api.get("/healthz").json()["status"] == "ok"


def test_metrics_endpoint(client):
    api, _ = client
    response = api.get("/metrics")
    assert response.status_code == 200
    assert "hub_generation" in response.text


def test_bot_issue_requires_shared_secret(client, monkeypatch):
    api, _ = client
    monkeypatch.delenv("HUB_BOT_SECRET", raising=False)
    response = api.post(
        "/api/v1/bot/issue",
        json={"telegram_id": 99},
        headers={"x-hub-secret": "wrong"},
    )
    assert response.status_code == 403


def test_bot_issue_mints_token(client, monkeypatch):
    api, _ = client
    monkeypatch.setenv("HUB_BOT_SECRET", "supersecret")
    response = api.post(
        "/api/v1/bot/issue",
        json={"telegram_id": 99},
        headers={"x-hub-secret": "supersecret"},
    )
    assert response.status_code == 200
    token = response.json()["token"]
    assert len(token) >= 40
    assert token != "supersecret"
    assert response.json()["url"].endswith(f"/sub/{token}")

    # The token is durable across app reconstruction and is not stored in plaintext.
    assert client[1].subscription_status(token) == "active"
    conn = client[1].connect()
    try:
        stored = conn.execute("SELECT token_hash FROM subscription_tokens").fetchone()[0]
        assert stored != token
    finally:
        conn.close()
    restarted = TestClient(create_app(store=Store(client[1].root)))
    assert restarted.get(f"/sub/{token}").status_code == 200


def test_legacy_plaintext_subscriptions_are_migrated_to_hashes(tmp_path):
    store = Store(tmp_path)
    conn = store.connect()
    conn.execute(
        "INSERT INTO subscriptions (token, telegram_id, status, created_at)"
        " VALUES (?, ?, 'active', '2026-10-01T00:00:00+00:00')",
        ("legacy-bearer-token", 7),
    )
    conn.commit()
    conn.close()

    migrated = Store(tmp_path)
    assert migrated.subscription_status("legacy-bearer-token") == "active"
    conn = migrated.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] == 0
        stored = conn.execute("SELECT token_hash FROM subscription_tokens").fetchone()[0]
        assert stored != "legacy-bearer-token"
    finally:
        conn.close()

    store = Store(tmp_path)
    generation = store.generation_path("gen-legacy")
    generation.mkdir(parents=True)
    (generation / "verified-sing-box.singbox").write_text('{"outbounds": []}', encoding="utf-8")
    (generation / "manifest.json").write_text(
        json.dumps({"generation": "gen-legacy", "sha256": "c" * 64, "payloads": []}),
        encoding="utf-8",
    )
    store.flip_pointer("gen-legacy", "c" * 64)
    api = TestClient(create_app(store=store))
    assert api.get("/sub/legacy-bearer-token").status_code == 200


def test_minted_subscription_can_be_revoked_without_url_token(client, monkeypatch):
    api, store = client
    monkeypatch.setenv("HUB_BOT_SECRET", "secret")
    issue = api.post("/api/v1/bot/issue", json={"telegram_id": 9}, headers={"x-hub-secret": "secret"})
    token = issue.json()["token"]
    assert api.get(f"/sub/{token}").status_code == 200

    revoked = api.post("/api/v1/sub/revoke", json={"token": token}, headers={"x-hub-secret": "secret"})
    assert revoked.json() == {"status": "revoked"}
    assert api.get(f"/sub/{token}").status_code == 404
    assert api.get(f"/api/v1/sub/{token}/status").json() == {"status": "revoked"}


def test_invalid_bot_issue_payloads_are_client_errors(client, monkeypatch):
    api, _store = client
    monkeypatch.setenv("HUB_BOT_SECRET", "secret")
    headers = {"x-hub-secret": "secret"}
    assert api.post("/api/v1/bot/issue", json=[], headers=headers).status_code == 400
    assert api.post("/api/v1/bot/issue", json={"telegram_id": "invalid"}, headers=headers).status_code == 400
    assert api.post("/api/v1/bot/issue", json={"telegram_id": -1}, headers=headers).status_code == 400


def test_unknown_subscription_tokens_do_not_allocate_token_buckets(client):
    api, _store = client
    app = api.app
    for index in range(50):
        api.get(f"/sub/unknown-{index}")
    assert len(app.state.subscriptions) == 0
    # Internal token buckets are created only for valid tokens.
    assert not app.state.limiter._buckets
    assert len(app.state.ip_limiter._buckets) == 1


def test_minted_tokens_are_random_not_derived(client, monkeypatch):
    api, _ = client
    monkeypatch.setenv("HUB_BOT_SECRET", "s")
    tokens = set()
    for _ in range(20):
        response = api.post(
            "/api/v1/bot/issue",
            json={"telegram_id": 5},
            headers={"x-hub-secret": "s"},
        )
        tokens.add(response.json()["token"])
    assert len(tokens) == 20
    assert all(len(token) >= 40 for token in tokens)


def test_landing_page_states_the_decentralised_positioning(client):
    """The positioning is a commitment, so it is asserted, not assumed.

    If someone rewrites the landing copy back to "public node index", the
    product quietly stops being what it says it is. The bot intro must carry the
    same words, or the two surfaces tell users different stories.
    """
    from hub.bot import _intro

    api, _ = client
    body = api.get("/").text
    assert "FREE VPN" in body
    assert "decentralised" in body

    intro = _intro("https://nodes.example", {"copy": "https://nodes.example/sub/x"})
    assert "FREE VPN" in intro
    # The safety warning is non-negotiable copy: it must never be dropped while
    # polishing the positioning.
    assert "hostile" in intro


def test_landing_page_is_html_not_plaintext(client):
    """A landing page that answers `text/plain` renders as source in browsers.

    This is the whole difference between "the site is up" and "the site shows
    code", and it is why `/` returns `HTMLResponse` rather than the
    `PlainTextResponse` it started as.
    """
    api, _ = client
    response = api.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in response.text.lower()


def test_landing_page_links_its_assets(client):
    """A page that links CSS it does not ship renders unstyled and looks broken."""
    api, _ = client
    body = api.get("/").text
    assert "/static/hub.css" in body
    assert "/static/hub.js" in body

    for asset in ("/static/hub.css", "/static/hub.js"):
        response = api.get(asset)
        assert response.status_code == 200, asset
        assert len(response.content) > 400, f"{asset} is unexpectedly small"


def test_landing_page_warns_that_nodes_are_hostile(client):
    """The safety warning is part of the promise, not fine print.

    Pinning it here as well as in the bot intro keeps both surfaces honest.
    """
    api, _ = client
    body = api.get("/").text
    assert "враждеб" in body  # the no-JS copy, which is what a crawler sees
    # The English version must carry the same warning, or switching language
    # drops a safety promise. Pinned in both surfaces because the dictionary in
    # hub.js is a separate copy that drifts the moment nobody looks.
    script = api.get("/static/hub.js").text
    assert "hostile" in script
    assert "without guarantees" in script


def test_landing_page_carries_an_english_dictionary(client):
    """A switcher that swaps to nothing is worse than no switcher.

    The markup ships Russian and English overwrites it, so the invariant is
    that *every* `data-i18n` key in the HTML has a matching English entry. A
    key with no translation leaves that element in Russian on an English page
    — which is exactly the "сырой перевод" complaint this is meant to fix, and
    it is invisible until someone switches the language.
    """
    api, _ = client
    body = api.get("/").text
    script = api.get("/static/hub.js").text

    keys = set()
    for line in body.splitlines():
        key = line.strip().split('data-i18n="')
        if len(key) > 1:
            keys.add(key[1].split('"')[0])
    assert keys, "the landing page declares no translatable strings"

    en = script.split("en: {")[1].split("},")[0]
    for key in keys:
        assert f'"{key}":' in en, key

    # The second half: labels the *script* renders itself, which never appear
    # in the HTML at all. Those are the ones a switcher can silently turn into
    # empty strings, because `t()` returns "" for a missing key rather than
    # falling back to anything. Both halves are needed — checking only the
    # HTML keys is a test that passes while the pool panel goes blank.
    used = set(re.findall(r"""\bt\(\s*["']([\w.]+)["']""", script))
    assert used, "no t() calls found; the extraction itself is broken"
    for key in sorted(used):
        assert f'"{key}":' in en, key


def test_every_js_rendered_label_exists_in_both_languages(client):
    """The switcher was found half-translating the page in a real browser.

    Clicking "RU" restored the *markup's* Russian but left every label the
    script renders in English, because `STRINGS.ru` was `null` and `t()` then
    returned "". A page that says "Живая генерация" above the word "Score" is
    the "сырой перевод" this page exists to answer, and no unit test caught it
    — the old ones only asserted the English direction, so "Russian is
    missing" was indistinguishable from "Russian works".

    The invariant is bidirectional: any key `t()` looks up must have an entry in
    *both* dictionaries, and `?lang=` exists so this is checkable without a
    browser that can click.
    """
    api, _ = client
    script = api.get("/static/hub.js").text
    body = api.get("/?lang=ru").text

    used = set(re.findall(r"""\bt\(\s*["']([\w.]+)["']""", script))
    assert used, "no t() calls found; the extraction itself is broken"

    for key in sorted(used):
        for lang in ("ru", "en"):
            table = script.split(f"{lang}: {{")[1].split("},")[0]
            assert f'"{key}":' in table, f"{key} missing from the {lang} dictionary"

    # And the markup's own keys must not be duplicated into the `ru`
    # dictionary: two Russian copies of one string drift apart, and the
    # snapshot that rest them come from the HTML, not from the table.
    html_keys = set(re.findall(r'data-i18n="([\w.]+)"', body))
    ru_table = script.split("ru: {")[1].split("},")[0]
    duplicated = html_keys & set(re.findall(r'"([\w.]+)":', ru_table))
    assert not duplicated, f"these Russian strings live in both places: {duplicated}"

    # The lookup itself, not just the tables. Reading the two dictionaries
    # statically cannot see a `t()` that consults only `STRINGS.en`: the data
    # would be perfectly bilingual while every Russian label rendered English,
    # which is half the bug above. A static test that only inspects the data is
    # exactly how a broken lookup stays green.
    assert "STRINGS[state.lang]" in script
    lookup = script.split("function t(key) {")[1].split("function countryName")[0]
    assert "STRINGS[state.lang]" in lookup, "t() does not read the active language"
    assert "STRINGS.en" in lookup, "t() has no fallback, so a missing key blanks a label"


def test_landing_page_accepts_a_language_query_parameter(client):
    """`?lang=` is what makes the switcher verifiable without a click.

    `--dump-dom` cannot press a button, so before this existed the only way to
    see a language other than the initial one was to open a browser. A page
    whose RU mode still rendered English would have passed every source-level
    assertion — which is exactly how the half-translated page reached
    production. This pins the *mechanism* (the client reads the parameter),
    and `test_every_js_rendered_label_exists_in_both_languages` pins the
    content that makes switching complete.
    """
    api, _ = client
    # The page is one static file for both languages — the server has nothing
    # to translate — so the assertion is that the client actually consults it.
    script = api.get("/static/hub.js").text
    assert "location.search" in script
    assert "initialLang" in script
    # The parameter is only honoured for a language we ship, so a stray
    # `?lang=fr` must not blank the page: `STRINGS` lookup would be undefined
    # and the fallback keeps the markup's Russian.
    assert "STRINGS[match[1].toLowerCase()] !== undefined" in script


def test_landing_page_shows_country_cards_not_a_bare_bar(client):
    """The country list is the feature the audience asks for first.

    It is a card grid rather than another bar row because a flag and a
    localised country name cannot live in a bar; and the container is asserted
    so a redesign that silently drops countries fails here rather than on the
    next user complaint.
    """
    api, _ = client
    script = api.get("/static/hub.js").text
    assert "countries" in script
    assert "function countryCards" in script
    # Only measured countries: a card labelled "not measured" is the one card
    # that must never be rendered.
    assert "unknown" in script and 'r.name !== "unknown"' in script
    # Localised names, because a flag alone does not tell a visitor where a
    # node exits and every other word on the page is RU/EN. `COUNTRY_NAMES` is
    # split on its own anchor rather than a positional `ru: {`, because the
    # script has two `ru:` blocks (STRINGS and COUNTRY_NAMES) and a positional
    # split silently reads whichever one comes first.
    country_block = script.split("COUNTRY_NAMES = {")[1]
    assert "Нидерланды" in country_block.split("en: {")[0]
    assert "Netherlands" in country_block.split("en: {")[1]


def test_no_russian_text_is_left_outside_the_translation_keys(client):
    """The English page must contain no Cyrillic at all.

    The other i18n tests start from the list of `data-i18n` keys and ask "is
    each one translated?". That direction cannot catch the failure this page
    actually shipped: three stage labels in the funnel (`<b>Скорость</b>`, …)
    had no key at all, so they were invisible to the switcher and the English
    page read "Скорость — a 256 KiB then 4 MiB window". Checking declared keys
    is blind to undeclared ones, and a reviewer switches the language, sees
    English, and stops looking.

    So the assertion runs the other way: take every run of Cyrillic in the
    markup and demand that it sits inside an element carrying a key. An
    untranslated string is then a missing key, not a happy accident.

    This is a *coverage* check, not a correctness check — it says nothing about
    whether the English is good, only that no Russian can survive the switch.
    """
    api, _ = client
    body = api.get("/").text

    # Deliberate exceptions, each pinned above at its definition site:
    #   aria-label="Язык / Language"  — the language switcher names both
    #       languages in every language by convention, so it is correct in both.
    #   the sr-only positioning line and the hero `<b>HOW IT WORKS` heading —
    #       covered by their own dedicated tests below, which assert the exact
    #       words. Neither is user-visible in the body; the framer's `html`
    #       extraction puts them in the body as plain text with no tag.
    exempt = {
        "hub — decentralised FREE VPN platform",
        "RU", "EN",
        # Client names are proper nouns: "Hiddify", "v2rayNG" and "Mihomo" are
        # how the products spell themselves, in every language.
        "sing-box / Hiddify / Happ",
        "v2rayNG / v2rayN",
        "Clash / Mihomo",
        "Karing / Shadowrocket",
    }

    leaks = []
    # The walk is over `body`, not over a stripped-text copy: `_cyrillic_runs`
    # answers a question about *ancestry* ("does some enclosing element carry a
    # key"), and flattening the document to text first destroys exactly the
    # information the question is asked about. Stripping here would make every
    # key absent and the test would report the entire page as a leak.
    for text, key in _cyrillic_runs(body):
        # Only Cyrillic *inside* the run matters; a page that renders Arabic
        # client names ("v2rayNG" has none, but "Mihomo" would not) is not
        # Russian text left behind.
        if not re.search(r"[А-Яа-яЁё]", text):
            continue
        if text.strip() in exempt:
            continue
        if key is None:
            leaks.append(text.strip()[:60])

    assert not leaks, "these Russian strings have no data-i18n key, so the switcher cannot reach them: " + "; ".join(leaks)


def _cyrillic_runs(body):
    """Yield (text, key) for every text node, with its inherited key.

    A real tree rather than a flag, because `hero.warn` is declared on the
    `<p>` while the Cyrillic inside sits on a nested `<strong>` with no key of
    its own. A flat flag calls that markup a leak, and a test that cries wolf on
    its own correct structure gets deleted rather than fixed.

    Inheritance is why this cannot be a regex: "is this string covered" is a
    question about ancestry, and ancestry is the one thing a pattern cannot see.
    """
    from html.parser import HTMLParser

    class Tree(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.root = {"tag": None, "key": None, "children": []}
            self.stack = [self.root]
            self.void = {
                "area", "base", "br", "col", "embed", "hr", "img", "input",
                "link", "meta", "param", "source", "track", "wbr",
            }

        def _push(self, tag, attrs):
            node = {"tag": tag, "key": dict(attrs).get("data-i18n"), "children": []}
            self.stack[-1]["children"].append(node)
            return node

        def handle_starttag(self, tag, attrs):
            node = self._push(tag, attrs)
            # `<br>` gets no `</br>`, so pushing it would leak every later
            # element into its subtree and let the whole page inherit one key.
            if tag not in self.void:
                self.stack.append(node)

        def handle_startendtag(self, tag, attrs):
            self._push(tag, attrs)

        def handle_endtag(self, tag):
            if tag in self.void:
                return
            for i in range(len(self.stack) - 1, 0, -1):
                if self.stack[i]["tag"] == tag:
                    del self.stack[i:]
                    return

        def handle_data(self, data):
            self.stack[-1]["children"].append(("text", data))

    def walk(node, inherited):
        key = node["key"] or inherited
        for child in node["children"]:
            if isinstance(child, tuple):
                yield child[1], key
            else:
                yield from walk(child, key)

    tree = Tree()
    tree.feed(body)
    return walk(tree.root, None)


def test_language_switch_reaches_the_meta_tags(client):
    """`innerHTML` cannot write a `<meta>` description.

    The tab title and the search-engine snippet are the two most visible
    translated strings on the page, and neither one has an element body: both
    live in attributes. A switcher built on `innerHTML` therefore translates
    every word on screen while both stay Russian — and the snapshot that
    "restores" Russian stores the `<meta>`'s empty inner HTML, so returning to
    Russian blanks the description rather than restoring it. Nothing about that
    failure is visible while looking at the page; it only shows up as a
    description that is either Russian or absent.

    The page itself carries no English text to assert, so this checks the
    mechanism: a reader and a writer that agree on where the text lives.
    """
    api, _ = client
    script = api.get("/static/hub.js").text
    body = api.get("/").text

    assert 'data-i18n="doc.title"' in body
    assert 'data-i18n="doc.desc"' in body
    # Both keys must actually be translated: the `test_landing_page_carries_an_
    # english_dictionary` check starts from the markup's keys, so declaring one
    # without translating it is exactly what it catches.
    en = script.split("en: {")[1].split("},")[0]
    assert '"doc.title":' in en, "the tab title stays Russian on an English page"
    assert '"doc.desc":' in en, "the description stays Russian on an English page"
    # The write path must be attribute-aware, and the read path must use the
    # same rule — two functions reading the same tag is the only way the
    # snapshot round-trips.
    assert 'el.tagName === "META"' in script
    assert 'el.setAttribute("content", text)' in script
    for func in ("function readText", "function writeText"):
        assert func in script, func
    read = script.split("function readText")[1].split("function ")[0]
    assert 'el.tagName === "META"' in read, "the snapshot must read the attribute, not the empty innerHTML"
    write = script.split("function writeText")[1].split("function ")[0]
    assert 'el.tagName === "META"' in write, "the writer must reach the attribute too"
    # And the neighbours must be used in both places, so a future edit to one
    # function that forgets the other still fails loudly.
    assert "ORIGINALS[nodes[i].getAttribute" in script
    assert "readText(nodes[i])" in script


def test_stats_publishes_aggregates_only(client):
    """No per-node address may appear: a public node list is a blocklist.

    The stats endpoint exists so the landing page has something true to show;
    the moment it starts returning rows from `nodes`, the service quietly
    becomes scrapeable.
    """
    api, _store = client
    payload = api.get("/api/v1/stats").json()
    assert set(payload) == {
        "generation", "verified", "known", "by_protocol",
        "by_country", "by_score", "published", "funnel",
    }
    assert "address" not in payload

    # The funnel is six integers from the last probing run, and nothing else.
    # It is easy to add "just the failing hostnames" here while wiring the
    # chart, and that would turn this endpoint into the scrape it exists not to
    # be.
    funnel = payload["funnel"]
    assert set(funnel) == {"raw", "parsed", "tcp", "tls", "config", "http"}
    for key, value in funnel.items():
        assert isinstance(value, int), (key, value)
    for key in ("by_protocol", "by_country"):
        for row in payload[key]:
            assert set(row) == {"name", "n"}
    assert set(payload["by_score"]) == {"60+", "30-59", "0-29"}


def test_stats_reads_the_store_it_is_given(client):
    """The numbers must come from the live store, not from a constant.

    This fixture writes payload *files* and flips the pointer by hand, and the
    `nodes` table stays empty because filling it is the pipeline's job — so the
    assertion is that the endpoint reports exactly that emptiness rather than a
    hard-coded non-zero pool. The populated case is covered in
    `tests/test_pipeline.py`.
    """
    api, store = client
    payload = api.get("/api/v1/stats").json()
    assert payload["generation"] == "gen-test"
    assert payload["known"] == 0
    assert payload["verified"] == 0
    assert payload["by_protocol"] == []
    # An empty pool must still be a valid response, never a 500.
    assert api.get("/api/v1/stats").status_code == 200


# --------------------------------------------------------------------------- #
# the per-country endpoint
# --------------------------------------------------------------------------- #


@pytest.fixture()
def country_client(tmp_path):
    """A store with a country shard on disk, named exactly as the pipeline does.

    `verified-NL.singbox` — the dot between the country and the format is what
    keeps it from reading as `verified-<core>.singbox`. Written by hand here
    rather than by a pipeline run, so the test pins the *reader* against the
    naming rule instead of against whatever the writer happened to produce.
    """
    store = Store(tmp_path)
    generation = store.generation_path("gen-test")
    generation.mkdir(parents=True, exist_ok=True)
    (generation / "verified-sing-box.singbox").write_text('{"full":true}', encoding="utf-8")
    # Both dialects `country_shards(core="sing-box")` writes, and no others:
    # the fixture is deliberately the shape the pipeline produces, so a test
    # that asks for Clash on a country link gets the 404 the real store gives.
    (generation / "verified-NL.singbox").write_text('{"nl":true}', encoding="utf-8")
    (generation / "verified-NL.base64").write_text(
        base64.b64encode(b"vless://u@nl1.example.com:443#nl1").decode(), encoding="utf-8"
    )
    (generation / "manifest.json").write_text(
        json.dumps({"generation": "gen-test", "sha256": "a" * 64, "payloads": []}),
        encoding="utf-8",
    )
    store.flip_pointer("gen-test", "a" * 64)
    app = create_app(store=store, sources={"base_url": "https://nodes.example"})
    return TestClient(app), store


def test_a_country_endpoint_serves_only_that_country(country_client, monkeypatch):
    """`country/nl` must return the shard, not the whole tier.

    The failure this pins is the lookup resolving to `verified-sing-box.singbox`
    because the shard name was not recognised: the response would be a 200 with
    the full pool in it, which is the one outcome that looks like success.
    """
    api, _ = country_client
    monkeypatch.setenv("HUB_TOKEN", "operatortoken")
    response = api.get("/sub/operatortoken/country/nl")
    assert response.status_code == 200, response.text
    assert response.json() == {"nl": True}, response.text


def test_the_country_url_is_case_insensitive(country_client, monkeypatch):
    """`nl` and `NL` are the same link, and a client that lower-cases a link the
    user pasted must not get a 404 for it."""
    api, _ = country_client
    monkeypatch.setenv("HUB_TOKEN", "operatortoken")
    lower = api.get("/sub/operatortoken/country/nl")
    upper = api.get("/sub/operatortoken/country/NL")
    assert lower.status_code == upper.status_code == 200
    assert lower.json() == upper.json()


def test_an_unknown_country_names_the_countries_that_exist(country_client, monkeypatch):
    """A country is not a secret: "no DE shard yet" is the useful answer.

    The contrast is deliberate — an unknown *token* is a bare 404 so a scanner
    cannot distinguish "exists" from "does not". A country that is not in the
    pool tells the caller nothing about anyone else's subscription, and a bare
    404 would send them refreshing a link that will never work.
    """
    api, _ = country_client
    monkeypatch.setenv("HUB_TOKEN", "operatortoken")
    response = api.get("/sub/operatortoken/country/de")
    assert response.status_code == 404
    body = response.json()
    assert body["country"] == "DE"
    assert "NL" in body["countries"], body
    assert "sing-box" not in body["countries"], body  # a core is not a country


def test_the_country_segment_validates_before_it_names_a_file(
    country_client, monkeypatch
):
    """The country code reaches a filename, so `..` must never get past `_CC`.

    Asserted against `_CC` directly rather than over HTTP, and that is not a
    shortcut: an HTTP client normalises `/country/..` to `/` *before sending*,
    so the traversal never reaches the server and an HTTP assertion would pass
    because the client defused it, not because the endpoint did. The endpoint's
    own guard is the thing that has to hold, and calling it directly is the only
    way to test it.

    The previous version of this test *re-implemented* the guard —
    `accepted = code.isascii() and bool(_CC.match(code))` — and asserted on its
    own arithmetic, which is green however the endpoint's real guard behaves.
    This version calls `_CC` and asserts on its verdict.
    """
    from hub.api import _CC

    for hostile in ("..", ".", "nl/", "/nl", "n", "nl1", "n l", "n\nl", "nl/.."):
        code = hostile.strip()
        assert not _CC.match(code), f"{hostile!r} was accepted as a country code"

    # A full-width spelling is not a country code and must not leak into the
    # file lookup as a path: it 404s like any other unrecognised code. This is
    # the endpoint being called, not a re-derivation of it — the server really
    # does receive `ｎｌ` unnormalised (verified: `cc.isascii()` is False on
    # arrival), so this is the observable the guard's whole expression produces.
    api, _store = country_client

    # The token is the other condition on this route: without it every answer
    # is a 404, which would make the assertions below unable to distinguish
    # "rejected as a bad country code" from "never authorised at all" — the
    # over-determined observation that lets a guard deletion pass.
    monkeypatch.setenv("HUB_TOKEN", "operatortoken")

    spoofed = api.get("/sub/operatortoken/country/" + quote("ｎｌ"))
    assert spoofed.status_code == 404, spoofed.status_code
    # A real code still resolves, so the guard is not rejecting everything.
    ok = api.get("/sub/operatortoken/country/NL")
    assert ok.status_code == 200, ok.status_code


def test_a_value_matching_the_country_regex_is_always_ascii():
    """Why `isascii()` in the endpoint guard cannot be pinned by input.

    `_CC` is `[A-Za-z]{2}\Z`. Every character in that class is ASCII, so **no
    string exists that matches `_CC` while failing `isascii()`** — the
    `not code.isascii()` term can never be the deciding one. An earlier audit
    called it "unpinned belt"; it is stronger than that: it is *unreachable*
    belt, defence-in-depth against a future `_CC` whose character class widens
    to a non-ASCII script.

    This test records that fact rather than pretending to test it. It is here
    so the next person who deletes `not code.isascii()` learns that nothing
    regressed, instead of hunting for the missing fixture — and so the guard
    itself stays covered by the tests that *can* fail: the direct `_CC` test
    above and the encoded-traversal test below.
    """
    import hub.api as api_module

    discriminating = [
        value
        for value in ("NL", "nl", "NĹ", "ΝL", "ｎｌ", "NK", "ǅL", "ＮＬ")
        if api_module._CC.match(value) and not value.isascii()
    ]
    assert discriminating == [], (
        "a value matching _CC but not ASCII would make the isascii() term "
        f"load-bearing: {discriminating}"
    )


def test_an_encoded_traversal_is_rejected_by_the_endpoint(country_client, monkeypatch):
    """`%2e%2e` reaches the route as a literal `..`, unlike the raw form.

    The complement of the direct test above: an encoded traversal is *not*
    normalised away by the client, so it arrives at the endpoint intact and the
    endpoint's own validation is what rejects it. Both halves are needed — one
    proves the guard, this one proves the guard is actually reached.

    Why this writes a file first: `..` matches no filename, so `_payload_path`
    returns `None` and the endpoint 404s *with the guard deleted*. Asserting 404
    against an ordinary store therefore passes for two unrelated reasons, which
    is the same "two mechanisms, one observation" trap as the speed gate. The
    traversal has to land on something real before the 404 can mean "the guard
    held" rather than "nothing matched".
    """
    api, store = country_client
    monkeypatch.setenv("HUB_TOKEN", "operatortoken")
    # `verified-..singbox` is reachable from `verified-..` by `_payload_path`,
    # which tries `{prefix}-{core}.{ext}`. With the guard gone the raw `..`
    # survives into the prefix and resolves here.
    target = store.generation_path("gen-test") / "verified-..singbox"
    target.write_text('{"escaped":true}', encoding="utf-8")
    try:
        raw = api.get("/sub/operatortoken/country/%2e%2e")
        assert raw.status_code == 404, raw.text
        assert "escaped" not in raw.text, raw.text
        # A single dot is the same class: it is not a country code, and it
        # must not be treated as one just because a file happens to match.
        one = api.get("/sub/operatortoken/country/%2e")
        assert one.status_code == 404, one.text
        assert "escaped" not in one.text, one.text
    finally:
        target.unlink(missing_ok=True)


def test_a_traversal_is_rejected_even_when_the_file_exists(country_client, monkeypatch):
    """The guard has to hold against a filename that *does* resolve.

    Same setup as the test above, stated as its own claim: a store containing a
    file reachable by a hostile country segment must still 404 it. Without this
    pairing, deleting the guard in `subscription_country` is invisible — the
    ordinary case 404s anyway because nothing matched.
    """
    api, store = country_client
    monkeypatch.setenv("HUB_TOKEN", "operatortoken")
    target = store.generation_path("gen-test") / "verified-..singbox"
    target.write_text('{"escaped":true}', encoding="utf-8")
    try:
        response = api.get("/sub/operatortoken/country/%2e%2e")
        assert response.status_code == 404, response.text
        # Empty, not a payload listing: the guard 404s before the store is
        # consulted at all, so there is nothing to report about it.
        assert "escaped" not in response.text, response.text
        assert response.text == "", response.text
    finally:
        target.unlink(missing_ok=True)


def test_the_country_endpoint_still_gates_on_the_token(country_client):
    """The country shard is the same nodes as the tier it came from.

    A shard that skipped the token check would be a public list of every node,
    reached by a URL that looks narrower than the one that is gated.
    """
    api, _ = country_client
    assert api.get("/sub/not-a-token/country/nl").status_code == 404


def test_a_country_shard_only_offers_the_dialects_it_was_written_in(country_client, monkeypatch):
    """A 200 with an unparseable body is worse than a 404.

    `country_shards` writes a shard in the formats the target core can read —
    `.singbox` and `.base64` for the sing-box core, `.clash` only for mihomo.
    So `?format=clash` on a country link must 404: the alternative is answering
    a Clash request with sing-box JSON, which every client reports as a broken
    profile rather than a missing one, and the operator debugs the wrong layer.

    This also pins what the README claims about the country links. The doc says
    `.singbox`/`.base64` only; nothing asserts that from the prose side, so it
    is asserted here.
    """
    api, _ = country_client
    monkeypatch.setenv("HUB_TOKEN", "operatortoken")
    assert api.get("/sub/operatortoken/country/nl").status_code == 200
    assert api.get("/sub/operatortoken/country/nl?format=singbox").status_code == 200
    assert api.get("/sub/operatortoken/country/nl?format=base64").status_code == 200
    # The fixture writes only .singbox and .base64 for NL, exactly as
    # `country_shards(core="sing-box")` does.
    assert api.get("/sub/operatortoken/country/nl?format=clash").status_code == 404
    assert api.get("/sub/operatortoken/country/nl?format=yaml").status_code == 404


def test_unique_query_serves_the_deduplicated_variant(tmp_path):
    """`?unique=1` picks the one-node-per-country payload when it exists.

    Happ cannot group, so the flat list repeats a country once per node. The
    unique variant exists for that client; the default must stay the full list,
    because the JSON and YAML payloads fail over within a country and that is
    strictly better wherever it is understood.
    """
    store = Store(tmp_path)
    gen = store.generation_path("gen-u")
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "verified-xray.base64").write_text("FULL", encoding="utf-8")
    # Rotation variants are one file per round; the API picks one by counter.
    # Two rounds here so the test can prove the counter advances rather than
    # always resolving to the same file.
    (gen / "verified-unique-rot0.base64").write_text("ROT0", encoding="utf-8")
    (gen / "verified-unique-rot1.base64").write_text("ROT1", encoding="utf-8")
    (gen / "manifest.json").write_text(
        json.dumps({"generation": "gen-u", "sha256": "a" * 64, "payloads": []}),
        encoding="utf-8",
    )
    store.flip_pointer("gen-u", "a" * 64)
    api = TestClient(create_app(store=store, sources={}))
    api.app and None
    os.environ["HUB_TOKEN"] = "t"
    try:
        assert api.get("/sub/t?format=base64").text == "FULL"
        # The rotation counter advances per request, so two fetches of the same
        # URL must be able to differ — that is the whole mechanism.
        seen = {
            api.get("/sub/t?format=base64&unique=1").text,
            api.get("/sub/t?format=base64&unique=1").text,
        }
        assert seen <= {"ROT0", "ROT1"}, seen
        assert len(seen) == 2, f"the counter did not advance: {seen}"
        # A bare `?unique` is what a user types when guessing; treating it as
        # "no" would serve the full list while appearing to honour the flag.
        assert api.get("/sub/t?format=base64&unique").text in {"ROT0", "ROT1"}
        # The flag must not leak into the JSON dialect, which has groups.
        assert api.get("/sub/t?unique=1").text != "ROT0"
    finally:
        os.environ.pop("HUB_TOKEN", None)


def test_core_xray_serves_the_xray_dialect(tmp_path):
    """`?core=xray` must return the balancer config, not the sing-box one.

    Both dialects are `.json`, so the extension cannot distinguish them and a
    client that asked for Xray would otherwise be handed a sing-box config —
    which Happ passes to the Xray core verbatim, so the core would refuse it and
    the user would see a config that cannot start.
    """
    store = Store(tmp_path)
    gen = store.generation_path("gen-x")
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "verified-xray.base64").write_text("B64", encoding="utf-8")
    (gen / "verified-sing-box.singbox").write_text('{"sing": true}', encoding="utf-8")
    (gen / "verified-xray.json").write_text(
        json.dumps({"outbounds": [{"tag": "FI-1"}],
                    "routing": {"balancers": [{"tag": "FI", "selector": ["FI-"]}]},
                    "observatory": {"subjectSelector": ["FI-"]}}),
        encoding="utf-8",
    )
    (gen / "manifest.json").write_text(
        json.dumps({"generation": "gen-x", "sha256": "a" * 64, "payloads": []}),
        encoding="utf-8",
    )
    store.flip_pointer("gen-x", "a" * 64)
    api = TestClient(create_app(store=store, sources={}))
    os.environ["HUB_TOKEN"] = "t"
    try:
        xray = api.get("/sub/t?core=xray")
        assert xray.status_code == 200
        assert "balancers" in xray.json()["routing"], xray.text
        # The default stays the sing-box dialect, which has no balancers.
        default = api.get("/sub/t")
        assert "routing" not in default.json(), default.text
    finally:
        os.environ.pop("HUB_TOKEN", None)


def test_base_url_can_come_from_the_environment(tmp_path, monkeypatch):
    """`HUB_BASE_URL` must override the config file for the API too.

    The config file carries one deployment's origin, so a checked-in `base_url`
    is always wrong for somebody: it points at the author's host, and every
    install that does not edit the file advertises links to a server it does not
    run. The bot already reads the environment for exactly this reason; the API
    read only the file, so the two surfaces disagreed about the same deployment
    — the bot handing out one origin and the subscription headers naming another.
    """
    from hub.api import _client_headers
    from hub.models import Format, Tier

    # The environment wins when set.
    monkeypatch.setenv("HUB_BASE_URL", "https://hub.example.test")
    store = Store(tmp_path)
    app = create_app(store=store, sources={"base_url": "https://from-file.test"})
    assert app.state.base_url == "https://hub.example.test"

    # And the file is the fallback, so an install that edits only the config
    # keeps working.
    monkeypatch.delenv("HUB_BASE_URL", raising=False)
    app2 = create_app(store=store, sources={"base_url": "https://from-file.test"})
    assert app2.state.base_url == "https://from-file.test"

    # An empty value in either place is "unset", not "the empty origin": the
    # headers that carry a URL are dropped rather than rendered as `""`.
    monkeypatch.setenv("HUB_BASE_URL", "")
    store3 = Store(tmp_path / "3")
    app3 = create_app(store=store3, sources={"base_url": ""})
    assert app3.state.base_url == ""
    headers = _client_headers("ua", Tier.VERIFIED, "sing-box", Format.BASE64, "")
    assert "profile-web-page-url" not in headers


def test_static_assets_must_be_revalidated(client):
    """A deploy must not leave a visitor with a new page and an old bundle.

    `StaticFiles` sends `ETag` and `Last-Modified` and no `Cache-Control`, so a
    client falls back to heuristic freshness — 10% of the file's age. The
    asset names carry no content hash, so that heuristic outlives a release:
    production served the previous `hub.js` alongside the new `index.html`
    after a redeploy, and the page rendered with code from two releases at
    once.

    `no-cache`, not `no-store`: the ETag still turns an unchanged file into a
    304, so this costs one conditional request per load, not one download.
    """
    api, _ = client
    response = api.get("/static/hub.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_the_static_policy_does_not_leak_onto_other_routes(client):
    """The middleware is keyed on the path, so the policy stays where it belongs."""
    api, _ = client
    assert "no-cache" not in api.get("/").headers.get("cache-control", "")


def test_a_static_response_is_revalidated_but_still_cached(client):
    """`no-cache` keeps the ETag useful: a second request may answer 304.

    This is what makes `no-cache` the right policy rather than `no-store`:
    every load costs a conditional request, and an unchanged asset costs no
    body. Pinned because the two policies differ by one word and either would
    pass a test that only checks the header's presence.
    """
    api, _ = client
    first = api.get("/static/hub.css")
    etag = first.headers["etag"]
    second = api.get("/static/hub.css", headers={"if-none-match": etag})
    assert second.status_code == 304, second.status_code


def test_a_subscription_is_never_stored(client, monkeypatch):
    """The URL carries the bearer token, and `?unique=1` changes per request.

    Two independent reasons for `no-store`:

    * a cache keyed on the URL would keep a credential-bearing response;
    * the rotation variant deliberately answers with a different node set on
      each request, so any cache — browser or intermediary — silently pins one
      round and defeats the feature.

    The country route is checked through its **404**, because that is the
    response this rule was first missing on: a handler-level header covers the
    200 and leaves the "no shard for DE yet" answer cacheable. A cached 404
    then outlives the round that publishes the shard, and the client keeps
    reporting a country that now exists as missing.
    """
    api, _ = client
    monkeypatch.setenv("HUB_TOKEN", "t")
    for path, status in (
        ("/sub/t", 200),
        ("/sub/t/verified", 200),
        ("/sub/t/country/fi", 404),
    ):
        response = api.get(path)
        assert response.status_code == status, path
        assert response.headers.get("cache-control") == "no-store", path


def test_an_unknown_token_is_not_stored_either(client):
    """404 for a bad token is a response too, and it must not be kept.

    Not a security claim about the token — the response is empty — but the same
    path rule: a cached 404 for a token issued a minute later would make a
    freshly issued subscription look dead to that client until its cache
    expires.
    """
    api, _ = client
    response = api.get("/sub/not-a-real-token")
    assert response.status_code == 404
    assert response.headers.get("cache-control") == "no-store"
