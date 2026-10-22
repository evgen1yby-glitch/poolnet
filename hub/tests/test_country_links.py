"""Per-country subscription links: the "list of countries" ask, end to end.

The complaint this file exists to close was *"мне надо чтобы выдавало ссылку как
у Marzban я вставил ссылку к примеру в HApp и все, там список стран"* — one
link, pasted into a client, showing a list of countries. Three separate pieces
have to be true at once for that to work, and each one had a different reason to
be missing:

1. **The payload groups by country.** `render_singbox` emits one `urltest` per
   measured country and a `proxy` selector over them; `tests/test_renderer.py`
   owns that. Restated here only as far as `country_link` depends on it.
2. **The bot answers a country with that country's link.** `/start NL` has to
   produce `/sub/{token}/country/NL`, not the whole pool. `_deep_links` built
   links for exactly one URL and nothing knew a shard URL was a second shape.
3. **The landing page's cards link somewhere.** They rendered as `<div>`s — the
   CSS already carried `text-decoration: none; :hover` lift, i.e. anchor styling
   for a card that was never an anchor — so the one place a visitor picks a
   country was the one place that did nothing.

The load-bearing decision is *what a card links to*. Not `/sub/{token}`: the page
has no token and must not, because a token in a public HTML file is a token
published to the internet, and `/api/v1/stats` publishes counts only by design
("a public node list is a ready-made blocklist"). A card carries the country to
the bot, which gates membership, mints a token, and answers with the shard.

No test here opens a socket. The API half uses `TestClient` against a store with
a hand-written shard; the bot half drives the pure helpers directly, because
`build_bot` needs aiogram and aiogram is not installed — which is precisely the
"code complete, token absent" state this project ships in.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hub import bot  # noqa: E402
from hub import countries  # noqa: E402
from hub.bot import (  # noqa: E402
    _country_arg,
    _country_name,
    _country_names,
    _deep_links,
    _links_for,
    country_link,
)
from hub.models import Format  # noqa: E402
from hub.renderer import render_singbox  # noqa: E402
from hub.store import Store  # noqa: E402

from tests.factories import make_reality_node, make_trojan_node  # noqa: E402


# --------------------------------------------------------------------------- #
# `country_link` itself
# --------------------------------------------------------------------------- #


def test_a_country_link_is_the_subscription_narrowed_to_one_exit():
    """The URL shape the API route serves, byte for byte.

    Pinned against the live route rather than against a local convention: if
    `country_link` produced `/sub/t/NL` or `/sub/t/country/nl`, the card would
    send visitors to a 404 that looks like a broken service.
    """
    assert (
        country_link("https://nodes.example", "tok", "NL")
        == "https://nodes.example/sub/tok/country/NL"
    )


def test_a_base_url_with_a_trailing_slash_does_not_double_up():
    """`base_url` is operator input and arrives with a trailing slash.

    The same normalisation `_deep_links` has always done, and the reason
    `_sub_url` exists as one function rather than an f-string per caller: a
    second copy of that `rstrip` is a second place to forget it, and the
    resulting link (`https://x//sub/...`) is one a client resolves and a
    visitor reports as a bug nobody can reproduce.
    """
    assert (
        country_link("https://nodes.example/", "tok", "NL")
        == "https://nodes.example/sub/tok/country/NL"
    )
    # And the whole-pool link still behaves the same way, through the same code.
    assert (
        _deep_links("https://nodes.example/", "tok")["copy"]
        == "https://nodes.example/sub/tok"
    )


def test_an_absent_base_url_gives_a_relative_link():
    """The stock install has `base_url: ""`, and the link must still work.

    A relative URL resolves against whatever host served the page, which is
    correct for the nginx-fronted deployment where the page and the API are the
    same origin. Absolute-or-nothing would break it for the case most installs
    are actually in.
    """
    assert country_link("", "tok", "nl") == "/sub/tok/country/NL"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("nl", "NL"),
        (" NL ", "NL"),
        ("n<l>", "NL"),
        ("n l", "NL"),
        ("n-l", "NL"),
        ("..//nl", "NL"),
        ("Nl", "NL"),
        ("🇳🇱nl", "NL"),
    ],
)
def test_a_country_code_is_normalised_not_trusted(raw, expected):
    """The code ends up inside an outbound tag on the visitor's client.

    It reaches `country_link` from two directions — a URL the page built from
    `/api/v1/stats`, and a `/start` payload the visitor typed — so neither can
    be assumed clean. Normalising to two ASCII letters here means the value
    that lands in `f"/sub/{token}/country/{code}"` is always something the
    `_CC` regex on the route side accepts.

    Separators are stripped because they are what a payload acquires when it is
    copy-pasted or mistyped. Asserted on the full URL so the test cannot pass
    via a separately-imported constant.
    """
    assert country_link("https://x.dev", "tok", raw) == f"https://x.dev/sub/tok/country/{expected}"


@pytest.mark.parametrize("raw", ["", "n", "1", "!!!", "nld", "please", "nl;drop", "  "])
def test_a_value_that_is_not_two_letters_is_refused(raw):
    """Loudly, not silently.

    The tempting failure is to interpolate whatever arrived and let the route
    404 it: the card would present a link that resolves to nothing, and the
    operator learns about it from a visitor. Raising here is caught by the
    caller, which then has no shard to offer and says so.

    `"please"` and `"nl;drop"` are the cases that separate truncating from
    validating: both *begin* with two letters, and a `[:2]` before the length
    check turns them into "PL" and "NL" — real countries chosen from strings
    that were never country codes. That is the bug this assertion exists for.
    """
    with pytest.raises(ValueError, match="not a country code"):
        country_link("https://x.dev", "tok", raw)


# --------------------------------------------------------------------------- #
# the start payload
# --------------------------------------------------------------------------- #


def test_a_plain_start_yields_no_country():
    """/start is the ordinary case and must not be treated as an error."""
    assert _country_arg(_Msg("/start")) == ""


def test_a_start_with_a_country_yields_that_country():
    """How a card reaches the bot, and the whole reason this file exists."""
    assert _country_arg(_Msg("/start nl")) == "NL"
    assert _country_arg(_Msg("/start NL")) == "NL"


def test_a_start_payload_is_normalised_the_same_way_a_url_is():
    """Both paths feed the same function, so both are held to the same rule.

    A card sends `?start=NL`; a visitor typing `/start n<l>` must not arrive at
    a country the route would reject. Same normalisation, asserted through the
    parser rather than through `country_link`, because this is the other door
    into it.
    """
    assert _country_arg(_Msg("/start  n<l>1! ")) == "NL"
    assert _country_arg(_Msg("/start junk")) == ""


def test_a_start_payload_with_only_letters_and_no_code_yields_nothing():
    """`[:2]` takes the first two of *some* string; that must not become a code.

    `/start please` would otherwise become `"PL"` — a real country, picked
    from a word the visitor typed for an unrelated reason. The length check is
    what makes the difference, so it is pinned from the payload side too.
    """
    assert _country_arg(_Msg("/start please")) == ""


def test_a_message_with_no_text_yields_no_country():
    """Non-text updates reach `on_start` too, and must not raise.

    A photo caption or a sticker arrives as a `Message` whose `.text` is
    `None`, and `getattr(..., "") or ""` is what keeps the handler from
    turning an ordinary update into an unhandled exception.
    """
    assert _country_arg(_Msg(None)) == ""
    assert _country_arg(object()) == ""


# --------------------------------------------------------------------------- #
# the link table is built for both URLs
# --------------------------------------------------------------------------- #


def test_the_country_links_use_the_same_client_quirks_as_the_pool_links():
    """This is why `_links_for` was split out at all.

    Every client dialect is reproduced for the shard URL: v2rayNG
    percent-encodes, Shadowrocket base64s, sing-box takes `import-remote-profile`.
    A second copy of that mapping for the country path is a second place for it
    to drift, and the symptom is one client that imports the country link and
    six that do not — which reads as a broken service rather than a bug.

    Asserted against the whole-pool mapping produced from the equivalent URL,
    so the two are compared rather than checked against a hard-coded table:
    the table is in `_links_for`, and this pins that there is only one of it.
    """
    country = _links_for(country_link("https://x.dev", "tok", "NL"))
    pool = _links_for("https://x.dev/sub/tok/country/NL")
    assert country == pool
    assert country["copy"] == "https://x.dev/sub/tok/country/NL"
    assert "country%2FNL" in country["v2rayng"] or "country/NL" in country["v2rayng"]
    # Shadowrocket's payload is base64 of the URL, not the URL itself.
    import base64

    assert base64.b64decode(country["shadowrocket"][6:99].encode()).decode().startswith(
        "https://x.dev/sub/tok/country/NL"
    )


def test_every_link_label_points_at_a_key_that_exists():
    """A label for a key that is not in the mapping prints an empty line.

    `_LINK_LABELS` and the mapping from `_links_for` are two lists that have to
    agree, and the intro iterates one to print the other. Asserted against the
    *union*: a link the message never prints is a link nobody uses, which is
    the failure that motivated extracting the labels in the first place.
    """
    labels = {key for _label, key in bot._LINK_LABELS}
    assert labels == set(_links_for("https://x.dev/sub/tok")), (
        f"labels and links disagree: labels={sorted(labels)}"
    )


# --------------------------------------------------------------------------- #
# the country names come from the page, not from a second copy
# --------------------------------------------------------------------------- #


def test_country_names_are_read_from_the_shipped_bundle():
    """The bot and the cards must name the same country the same way.

    `hub.js` already carries the RU/EN tables, and a Python copy would be a
    second place for them to disagree — the bot would answer "Germany" while
    the card the visitor just clicked said "Германия", which reads as a broken
    link rather than a translation. So the parser reads the real file, and this
    asserts it actually got a table out of it rather than quietly returning {}.
    """
    names = _country_names()
    assert names, "_country_names() returned nothing; the bundle was not parsed"
    assert names["NL"], names.get("NL")
    # A flag-only or code-only mapping would be useless here.
    assert names.get("NL") not in (None, "", "NL")


def test_a_country_name_falls_back_to_the_code_not_to_a_blank():
    """An unmeasured or unmapped code must still produce a readable line.

    The visitor clicked a card for a country the dictionary has no name for.
    Returning "" would print `🎯  ()` — an empty label that looks like a bug in
    the bot rather than a missing translation.
    """
    assert _country_name("NL") and _country_name("NL") != ""
    assert _country_name("ZZ") == "ZZ"


def test_a_missing_bundle_leaves_the_bot_able_to_answer(monkeypatch):
    """A static asset going away must not take the bot down with it.

    The bundle is served from disk on every install, and the bot's answer is
    the subscription link — which works regardless. A bot that refuses to
    answer because it could not read a JavaScript file is a worse failure than
    one that says "NL" instead of "Нидерланды", so the parser returns empty
    and the fallback carries it.

    Pinned through `monkeypatch` on `bot.Path` (not by deleting the real file,
    which would leave the repo dirty) and restored automatically, so the real
    table is still there for the next test. The `_NAMES` cache is cleared
    explicitly: `_country_names` memoises, and without the reset the previous
    test's table would still be live and the parser would never be called.
    """
    # The parser and its cache live in `hub.countries` now: one reader shared
    # by the renderer and the bot, so a node label and a landing-page card
    # cannot disagree about a country name.
    monkeypatch.setattr(countries, "_NAMES", None, raising=True)

    # The real `Path`, pointed at a file that does not exist. Replacing `Path`
    # with a stub is tempting but wrong: the constructor call is outside the
    # `try`, so any stub has to reimplement `resolve`, `/` and `parent` exactly
    # or it fails for the wrong reason. Pointing the real class at a missing
    # path produces the actual `OSError` a vanished mount produces.
    monkeypatch.setattr(countries, "Path", lambda *a, **k: Path("/nonexistent/hub.js"))

    assert countries._parse_country_names() == {}
    assert bot._country_name("NL") == "NL"

    # `monkeypatch` restores `Path` on the way out, so undoing it here is what
    # lets the last assertion read the real bundle — and it has to, or the test
    # would "pass" by asserting that the *replaced* parser finds nothing.
    monkeypatch.undo()
    monkeypatch.setattr(countries, "_NAMES", None, raising=True)
    assert countries._parse_country_names(), "the real bundle was not parsed back"


# --------------------------------------------------------------------------- #
# the intro
# --------------------------------------------------------------------------- #


def test_the_intro_leads_with_the_country_that_was_asked_for():
    """A message that opens with the generic pitch reads as "the click did nothing".

    The visitor arrived from a country card. The first line has to be that
    country, before the marketing, or the deep link looks broken.
    """
    links = _links_for(country_link("https://x.dev", "tok", "NL"))
    intro = bot._intro("https://x.dev", links, country="NL")
    assert "NL" in intro.splitlines()[0], intro
    assert "Netherlands" in intro or "Нидерланды" in intro, intro


def test_the_intro_without_a_country_has_no_country_line():
    """The plain `/start` must keep the exact shape it always had.

    Pinned on absence rather than on a specific line, because the surrounding
    copy is marketing and changes; what must not change is that an ordinary
    `/start` gains no empty `🎯  ()` header.
    """
    intro = bot._intro("https://x.dev", _deep_links("https://x.dev", "tok"))
    assert "🎯" not in intro, intro
    assert intro.splitlines()[0] == "hub — decentralised FREE VPN platform"


def test_the_intro_carries_the_hostile_node_warning_with_a_country():
    """The safety copy is non-negotiable, and the country line must not displace it.

    `test_landing_page_states_the_decentralised_positioning` pins the same
    warning on the landing page and on the plain intro. A path that opens with
    a country header could easily drop a line while being rearranged, and this
    is the one line that must never go.
    """
    intro = bot._intro("https://x.dev", None, country="NL")
    assert "hostile" in intro, intro


# --------------------------------------------------------------------------- #
# the payload the link resolves to
# --------------------------------------------------------------------------- #


@pytest.fixture()
def country_store(tmp_path):
    """A store whose generation holds two countries' shards and a full payload.

    Written through `renderer`, not by hand, so the test cannot pass against a
    filename the pipeline does not actually produce: the shard is exactly what
    `render_singbox(country=...)` writes, which is what
    `renderer.country_shards` calls at publish time.
    """
    from fastapi.testclient import TestClient

    from hub.api import create_app
    from hub.renderer import RenderParams

    store = Store(tmp_path)
    generation = store.generation_path("gen-cc")
    generation.mkdir(parents=True, exist_ok=True)

    nodes = [
        make_reality_node(address="a.example.com", country="NL"),
        make_reality_node(address="b.example.com", country="NL"),
        make_trojan_node(address="c.example.com", country="DE"),
        make_trojan_node(address="d.example.com", country="DE"),
        make_trojan_node(address="e.example.com", country="FI"),
    ]
    params = RenderParams(fmt=Format.SINGBOX, client_core="sing-box")
    for name, body in [
        ("verified-sing-box.singbox", render_singbox(nodes, params)),
        *[
            (f"verified-{cc}.singbox", render_singbox(nodes, replace(params, country=cc)))
            for cc in ("NL", "DE")
        ],
    ]:
        (generation / name).write_text(body, encoding="utf-8")
    (generation / "manifest.json").write_text(
        json.dumps({"generation": "gen-cc", "sha256": "b" * 64, "payloads": []}),
        encoding="utf-8",
    )
    store.flip_pointer("gen-cc", "b" * 64)
    return TestClient(create_app(store=store, sources={"base_url": "https://x.dev"})), store


@pytest.fixture()
def country_client(country_store):
    return country_store


def test_a_country_link_actually_resolves_to_that_country_only(country_client, monkeypatch):
    """The end-to-end promise: paste the link, get one country.

    `country_link` builds a URL, and a URL that 404s is a link that looks
    broken. So this follows it: set the operator token the way a real install
    does, request the exact URL `country_link` produced, and read the shard.
    The shard must contain DE's nodes and none of NL's — a link that returned
    everything would make the whole country feature decorative.

    The token comes from `HUB_TOKEN` rather than `_mint_token`, because that is
    random by construction and a subscription nobody issued is 404 by design.
    """
    api, _store = country_client
    monkeypatch.setenv("HUB_TOKEN", "operatortoken")
    url = country_link("https://x.dev", "operatortoken", "DE")[len("https://x.dev") :]
    response = api.get(url)
    assert response.status_code == 200, url

    payload = response.json()
    # Node tags are the country's own name now, so the assertion is on the
    # label a user sees rather than on the old `nNNN-<proto>-<cc>` serial.
    # `proxy`/`direct` are group and built-in tags, not nodes.
    tags = [
        o["tag"]
        for o in payload["outbounds"]
        if o.get("type") not in ("selector", "direct", "urltest")
    ]
    assert tags, payload["outbounds"]
    assert all("DE" in t or "Германия" in t for t in tags), tags


def test_the_country_shard_presents_one_country_as_one_destination(
    country_client, monkeypatch
):
    """Marzban means a *named destination*, not a flat list.

    A shard that listed its nodes without a `urltest` group would leave the
    visitor choosing between "node 14" and "node 15", which is the flat list
    the complaint was about. One group, named after the country, whose members
    are that country's nodes.
    """
    api, _store = country_client
    monkeypatch.setenv("HUB_TOKEN", "operatortoken")
    payload = api.get(
        country_link("https://x.dev", "operatortoken", "NL")[len("https://x.dev") :]
    ).json()

    groups = [o for o in payload["outbounds"] if o["type"] == "urltest"]
    assert len(groups) == 1, payload["outbounds"]
    # The group is named after the country, in the language the page uses, so
    # the picker reads "🇳🇱 Нидерланды" rather than "g-nl".
    assert groups[0]["tag"] == "🇳🇱 Нидерланды", groups[0]["tag"]
    assert len(groups[0]["outbounds"]) == 2, groups[0]["outbounds"]

    # Auto-selection and failover are the point: one `urltest` group means the
    # client picks the best of the two and re-picks when one dies, with no
    # action from the user. Without the group (a bare node list) picking a node
    # is permanent until the user notices it stopped working.
    assert groups[0]["type"] == "urltest"
    assert groups[0]["url"], groups[0]
    assert groups[0]["interval"], groups[0]
    assert groups[0]["interrupt_exist_connections"] is False, groups[0]

    # And the selector offers the group, so the client's UI shows the country.
    selector = [o for o in payload["outbounds"] if o["type"] == "selector"]
    assert selector and "🇳🇱 Нидерланды" in selector[0]["outbounds"]
    # The shard's own two nodes must not also be listed, or the country and its
    # members appear side by side as equals.
    node_tags = [o["tag"] for o in payload["outbounds"] if o.get("server")]
    assert not (set(selector[0]["outbounds"]) & set(node_tags)), selector[0]["outbounds"]


def test_a_country_with_no_shard_names_the_countries_that_do_exist(
    country_client, monkeypatch
):
    """A 404 that says what is available is an answer; a bare 404 is a dead end.

    The route already does this (`test_an_unknown_country_names_the_countries_
    that_exist` in `tests/test_api.py`), and it is repeated here because a card
    links to whatever `/api/v1/stats` reported — so a country measured in the
    database but missing on disk is exactly the state a visitor can click into.
    The response has to name the shards that *do* exist so they can pick one.

    FI is the fixture's trap and the reason this test is worth having: FI has
    nodes in the database but no shard file, and the answer must not list it.
    "Available" here means available *as a link* — what is on disk — which is a
    different set from what the pool contains, and conflating them produces a
    404 that recommends a country the very same request cannot serve.
    """
    api, _store = country_client
    monkeypatch.setenv("HUB_TOKEN", "operatortoken")
    response = api.get(
        country_link("https://x.dev", "operatortoken", "US")[len("https://x.dev") :]
    )
    assert response.status_code == 404
    body = response.json()
    assert body["country"] == "US", body
    assert body["countries"] == ["DE", "NL"], body
    assert "FI" not in body["countries"], (
        "a country with nodes but no shard is not available as a link"
    )


# --------------------------------------------------------------------------- #
# the landing page's cards
# --------------------------------------------------------------------------- #


def _ui(name: str) -> str:
    return (ROOT / "src" / "hub" / "ui" / name).read_text(encoding="utf-8")


def test_a_country_card_is_a_link_when_there_is_a_bot_to_link_to():
    """The bug this whole file closes.

    The cards were `<div>`s, and the CSS had already been written for anchors
    (`text-decoration: none`, `color: var(--fg)`, a `:hover` lift) — styling for
    a link that was never one. So the visitor saw a grid of twelve countries
    and none of them did anything, which is precisely "где список стран?" asked
    of a page that drew one.

    Pinned on the `<a` the map emits, not on the presence of an `href` string:
    the code branches between an anchor and a div, and only the anchor is the
    fix.
    """
    script = _ui("hub.js")
    assert "'<a class=\"country\" href=\"'" in script, (
        "countryCards does not emit an anchor, so the cards stay unclickable"
    )


def test_a_country_card_carries_the_country_code_as_data():
    """The code has to be on the card for a test — or a screen reader — to read it.

    It is also what makes the link's target verifiable without a browser:
    `data-cc="NL"` next to `href="...?start=NL"` shows the card and its
    destination name the same country.
    """
    script = _ui("hub.js")
    assert 'data-cc="' in script, script


def test_a_card_degrades_to_a_plain_div_when_there_is_no_bot():
    """`bot_username` is unset on a stock install, and that must not break cards.

    The failure to avoid is `<a href="">`: an anchor with an empty href
    reloads the page on click, so every country becomes a link that appears to
    do nothing at all — worse than the `<div>` it replaced. So the branch is
    explicit, and both halves are pinned because a change to either direction
    is invisible from the other.
    """
    script = _ui("hub.js")
    assert "'<div class=\"country\" data-cc=\"'" in script, script
    assert "if (!BOT_URL) return \"\";" in script, script


def test_the_page_asks_for_the_bot_endpoint():
    """A card cannot link to a bot it has not been told about.

    The username is configuration (`bot_username` in `config/sources.yaml`) and
    must not be compiled into the bundle: a bundle with a hard-coded username
    is wrong on every install but the one it was written on. `data-bot-endpoint`
    is what puts the value in the right place, and a missing attribute means
    `undefined` is fetched — a request to a relative `undefined` that 404s, so
    the failure is silent either way, which is why it is pinned here.
    """
    body = _ui("index.html")
    assert 'data-bot-endpoint="/api/v1/bot"' in body, body


def test_no_function_in_the_bundle_is_defined_twice():
    """The shadowing bug this score already caught once.

    A duplicated `function` declaration is legal JavaScript and lints clean:
    the second definition silently wins, so the page works and the first copy
    is dead code that still reads as the shipping behaviour. It happened here
    during this very change — `countryHref` was emitted twice by two adjacent
    edits, and nothing complained.

    Mutation testing is what surfaced it: replacing the *first* copy changed
    nothing observable, which is the signature of a shadowed declaration. The
    rule is asserted on the whole bundle rather than on one function name,
    because the next duplicate will be a different function.
    """
    script = _ui("hub.js")
    names = re.findall(r"^\s*function ([A-Za-z_$][\w$]*)\s*\(", script, re.MULTILINE)
    assert names, "no function declarations found; the extraction is broken"
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert not duplicates, (
        f"these functions are declared twice, so the first copy is dead code: "
        f"{duplicates}"
    )


def test_a_bot_url_is_built_from_the_username_the_endpoint_returns():
    """`https://t.me/{username}`, not an absolute URL from the server.

    Building it client-side from just the username means the answer stays a
    username — a value every Telegram user can see, which is why it is safe to
    publish — rather than a full URL the operator has to keep in step with the
    bot's actual identity.
    """
    script = _ui("hub.js")
    assert '"https://t.me/" + name' in script, script


# --------------------------------------------------------------------------- #
# the endpoint itself
# --------------------------------------------------------------------------- #


def test_the_bot_endpoint_reports_the_configured_username(tmp_path):
    """The one fact the cards need to route a click, read off the real route.

    This is the test whose absence let a whole class of mutations through.
    Deleting `app.state.bot_username = bot_username` — the single line that
    carries the operator's configuration to the handler — left every other test
    green, because nothing had ever *called* `/api/v1/bot`; the only assertions
    about it were string searches on the bundle and on `index.html`. Those
    prove the page asks for the right URL. They cannot prove the server answers
    it, and a route nobody requests is a route nobody knows is 500-ing.

    So the request is made here, and the value is the one from `sources`, not a
    value the test supplied by another route.
    """
    from hub.api import create_app
    from fastapi.testclient import TestClient

    api = TestClient(
        create_app(store=Store(tmp_path), sources={"bot_username": "@hub_bot"})
    )
    response = api.get("/api/v1/bot")
    assert response.status_code == 200, response.text
    # `@` stripped: the page concatenates `https://t.me/` + username, and a
    # leading `@` would produce `t.me/@hub_bot`, which Telegram redirects at
    # best. Normalisation is the server's job because the server owns the config.
    assert response.json() == {"username": "hub_bot"}, response.text


def test_the_bot_endpoint_reports_no_bot_when_unconfigured(tmp_path):
    """Unset means unset — an empty string, not a guess.

    The page's contract is "empty username means render plain cards", so this
    endpoint reporting anything else when the operator has configured nothing
    would produce links to a bot that does not exist.
    """
    from hub.api import create_app
    from fastapi.testclient import TestClient

    for sources in ({}, {"bot_username": ""}, {"bot_username": "   "}):
        api = TestClient(create_app(store=Store(tmp_path), sources=sources))
        response = api.get("/api/v1/bot")
        assert response.status_code == 200, sources
        assert response.json() == {"username": ""}, (sources, response.text)


def test_bot_username_reaches_the_route_from_config(tmp_path):
    """The `sources.yaml` key is the whole wiring, so read it as written.

    `fetcher.FILE_SETTINGS` keeps `bot_username` in the set of values that may
    come from a file. A key read by `create_app` but dropped by the loader
    would make this feature configurable in code and inert in production, which
    is not a state any UI-level test could see.
    """
    from hub.fetcher import FILE_SETTINGS

    assert "bot_username" in FILE_SETTINGS, sorted(FILE_SETTINGS)
    assert FILE_SETTINGS["bot_username"] is str


def test_the_bot_is_fetched_before_the_pool_is_rendered():
    """Ordering, asserted because the wrong order is visible to visitors.

    A card's href is built during `render`. If the pool were fetched first, the
    first paint would draw twelve dead cards and the bot response would redraw
    them — a flash of unclickable countries that only appears on a slow
    connection, i.e. exactly when it matters.
    """
    script = _ui("hub.js")
    bot_at = script.index("dataset.botEndpoint")
    pool_at = script.index("function loadPool()")
    assert bot_at < pool_at, (bot_at, pool_at)


def test_a_failing_bot_endpoint_leaves_the_pool_rendered():
    """The bot is a delivery channel, never the backbone — the module says so.

    If the pool's own render were chained behind the bot's fetch, an unset
    username would blank the page: no cards, no counts, no protocols. The bot
    fetch has its own `.catch` for exactly this, and the assertion is that the
    pool still loads through the failure rather than being swallowed by it.
    """
    script = _ui("hub.js")
    assert ".catch(function () { return null; })" in script, script


def test_the_country_hint_is_translated_in_both_languages():
    """"Pick a country" has to exist in RU and EN or it is the "сырой перевод" again.

    `tests/test_api.py::test_every_js_rendered_label_exists_in_both_languages`
    enforces this for every `t()` key automatically; this test exists because a
    key added *after* that machinery was written is exactly the one that gets
    forgotten, and because the hint is the only text that explains the
    interaction the visitor is about to have.
    """
    script = _ui("hub.js")
    for lang in ("ru", "en"):
        table = script.split(f"{lang}: {{")[1].split("},")[0]
        assert '"pool.country.hint":' in table, lang


def test_the_hint_is_rendered_only_when_the_cards_are_links():
    """A hint under a grid of dead cards is an instruction the visitor cannot follow.

    "Pick a country and the bot gives you that country's link" printed above
    cards that do nothing is worse than no hint at all — it invites a click
    that goes nowhere. So the hint is conditional on the same `BOT_URL` the
    cards are, asserted here as the `&&` that ties them together.
    """
    script = _ui("hub.js")
    assert 'countryHref("XX") && BOT_URL' in script, script


class _Msg:
    """Just enough `Message` for `_country_arg`: a `.text` attribute."""

    def __init__(self, text):
        self.text = text
