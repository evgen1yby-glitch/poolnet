"""The landing page's country cards, executed rather than read.

Every other test in this repo inspects `hub.js` as *text*: it asserts that
`'<a class="country" href="'` appears, that a key is in both dictionaries, that
one fetch precedes another. That is fine for the things text can prove, and it
proved enough to build the feature.

It cannot prove the one thing that matters, which is what the cards actually
render to. Mutation testing demonstrated the gap concretely: replacing
`encodeURIComponent(code)` with `encodeURIComponent("XX")` — every country card
pointing at the same link — left all 44 of those tests green. A source-string
assertion is satisfied by the string; it says nothing about the function.

So this file runs the real bundle. Node executes the shipped `hub.js` inside a
DOM stub small enough to read, against a stats payload written the way the real
endpoint writes it, and the assertions are on the resulting HTML.

Two constraints shaped the design:

* **Offline.** No HTTP. The payload is constructed in Python and handed to the
  stub's `fetch`, so the assertions are about rendering and not about the
  server. `tests/test_api.py` owns the server.
* **The bundle is the one the API serves.** Read from `src/hub/ui/hub.js`, not
  copied into a fixture: a fixture drifts from the asset the moment the asset
  changes, and the drift is invisible because the fixture still passes.

Node is required and the file skips itself without it. That is a deliberate
choice over a pure-Python reimplementation of the renderer: a second
implementation of `countryCards` in Python tests the Python, and the JavaScript
— the thing that actually renders — remains unverified.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

UI = ROOT / "src" / "hub" / "ui"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not installed; the bundle is not executed"
)

#: A payload in exactly the shape `/api/v1/stats` returns. Three countries with
#: different counts, so the sort and the per-card width are both observable, and
#: each name is a country the RU dictionary actually has — a card whose
#: localised name is missing would be pinned against a fallback.
STATS = {
    "generation": "gen-test",
    "verified": 6,
    "known": 6,
    "by_protocol": [{"name": "vless", "n": 4}, {"name": "trojan", "n": 2}],
    "by_country": [
        {"name": "DE", "n": 2},
        {"name": "NL", "n": 3},
        {"name": "FI", "n": 1},
    ],
    "by_score": {"60+": 6, "30-59": 0, "0-29": 0},
    "published": [],
}


def _render(stats: dict, bot_payload, *, search: str = "") -> str:
    """Execute the shipped bundle and return what the pool element contains.

    The stub is minimal on purpose: `document` needs only `getElementById` and
    `querySelectorAll`, because that is all of the DOM the bundle touches. A
    fuller stub would be more code to trust and less to read, and the parts it
    omitted (forms, events) are parts the bundle does not use during render.
    """
    harness = _HARNESS.replace("__STATS_JSON__", json.dumps(stats)).replace(
        "__BOT_JSON__", json.dumps(bot_payload)
    ).replace("__SEARCH__", json.dumps(search))
    # The bundle goes in last, as a separate argument, so a syntax error in it
    # is reported as such rather than as a harness error.
    result = subprocess.run(
        ["node", "--input-type=module", "-e", harness, "--", str(UI / "hub.js")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"the bundle did not execute:\n{result.stderr}\n{result.stdout}"
        )
    return result.stdout


#: The runner. Written as a module so `import` can load the bundle from disk —
#: importing it is what makes this a test of the real file rather than of a
#: copy, and a bundle with a syntax error fails here instead of in a browser.
_HARNESS = r"""
const html = await import("node:fs").then((fs) =>
  fs.promises.readFile(process.argv[process.argv.length - 1], "utf8")
);

const STATS = __STATS_JSON__;
const BOT = __BOT_JSON__;
const SEARCH = __SEARCH__;

const host = { tagName: "SECTION", dataset: { endpoint: "/api/v1/stats", botEndpoint: "/api/v1/bot" }, innerHTML: "" };
const langButtons = [];
const document = {
  documentElement: {
    _a: {},
    setAttribute(n, v) { this._a[n] = v; },
    getAttribute(n) { return this._a[n] || null; },
  },
  getElementById: (id) => (id === "stats" ? host : null),
  querySelectorAll: (sel) => (sel === ".lang button" ? langButtons : []),
};

const sandbox = {
  document,
  location: { search: SEARCH },
  navigator: { language: "en" },
  fetch: (url) =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(url === "/api/v1/bot" ? BOT : STATS),
    }),
  console,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

// `new Function` rather than `eval`: the bundle is an IIFE that references
// `document` and `fetch` by free variable, and this binds them to the stub
// without polluting the runner's own scope.
new Function("document", "location", "navigator", "fetch", "console", "window", "globalThis", html)
  .call(sandbox.window, document, sandbox.location, sandbox.navigator, sandbox.fetch, console, sandbox, sandbox);

// Both fetches are chained promises; one turn is not enough for the second to
// have resolved, so the wait is what makes this deterministic rather than fast.
await new Promise((r) => setTimeout(r, 50));
process.stdout.write(host.innerHTML);
"""


# --------------------------------------------------------------------------- #
# what the cards render to
# --------------------------------------------------------------------------- #


def test_with_a_bot_every_country_card_is_a_link_bearing_that_country():
    """The behaviour the source-string test could not reach.

    This is the assertion whose absence let `encodeURIComponent("XX")` pass:
    it reads the rendered href and checks it names the country the card is for.
    A card for DE whose href says `?start=NL` fails here, and no string search
    on the bundle can see the difference.
    """
    html = _render(STATS, {"username": "hub_bot"})
    cards = _cards(html)
    assert cards, html

    for code, href in cards:
        assert href == f"https://t.me/hub_bot?start={code}", (code, href)


def test_without_a_bot_no_card_is_a_link():
    """`bot_username` unset means the cards render as plain divs.

    Pinned on the rendered tag rather than on the source, because the failure
    that matters is a *generated* `<a href="">` — an anchor with an empty href,
    which reloads the page on click and makes every country look like a broken
    link. Text assertions cannot tell an empty attribute from an absent one.
    """
    html = _render(STATS, {"username": ""})
    assert _cards(html) == [("NL", ""), ("DE", ""), ("FI", "")], html
    assert "<a " not in html, "an anchor was rendered with no bot to link to"
    assert "href" not in html


def test_a_failing_bot_endpoint_still_renders_the_pool():
    """The bot is a delivery channel, not the backbone.

    Asserted on the rendered output and not on the source's `.catch`, because
    the observable difference is that the cards are there. A version where the
    pool render were chained behind the bot fetch would produce an empty pool
    element and every assertion above would fail with an unhelpful message.
    """
    html = _render(STATS, None)  # `fetch` still resolves, but as a null body
    assert _cards(html) == [("NL", ""), ("DE", ""), ("FI", "")], html
    # The rest of the pool panel survives, which is the actual promise.
    assert "Protocol" in html, html
    assert "vless" in html, html


def test_cards_are_ordered_by_count_then_name():
    """The country with the deepest rotation is on the left.

    NL has 3 nodes and DE has 2, so NL comes first despite DE sorting first
    alphabetically. A pure-name sort would pass a test that only checked
    presence, and the order is what makes the page useful at a glance.
    """
    html = _render(STATS, {"username": "hub_bot"})
    assert [c for c, _ in _cards(html)] == ["NL", "DE", "FI"], html


def test_each_card_shows_its_own_count_and_a_flag():
    """The count is the country's, not the pool's or the max's.

    `width` is derived from `count / max`, so a card showing the wrong count
    also draws the wrong bar — and a bar that is 100% for every country is
    visible on the page while a missing number is not.
    """
    html = _render(STATS, {"username": "hub_bot"})
    assert 'class="count">3<' in html, html  # NL
    assert 'class="count">2<' in html, html  # DE
    assert 'class="count">1<' in html, html  # FI
    assert html.count('class="flag"') == 3, html
    # The deepest country is the full bar; the shallowest is not.
    assert "width:100%" in html, html
    assert "width:33%" in html, html


def test_every_card_carries_a_localised_country_name():
    """A flag alone does not say where a node exits.

    Pinned in Russian because Russian is the language the markup ships — `lang`
    is `ru` in `index.html`, and the audience this is built for reads it. The
    English rendering is covered by `test_switching_to_english_translates_the_
    cards` and by every other test here, whose stub reports an English browser.

    `bot._country_names` reads the same table through a second parser, so this
    is also what catches the two drifting apart.
    """
    html = _render(STATS, {"username": "hub_bot"}, search="?lang=ru")
    assert "Германия" in html, html  # DE
    assert "Нидерланды" in html, html  # NL
    assert "Финляндия" in html, html  # FI
    # The link must survive the language switch: `applyLang` re-renders from
    # `state.data`, and a re-render that lost `BOT_URL` would draw dead cards
    # the moment the visitor changed language.
    assert 'href="https://t.me/hub_bot?start=DE"' in html, html


def test_the_hint_appears_with_a_bot_and_not_without_one():
    """"Pick a country" printed over dead cards invites a click that goes nowhere.

    Both directions from the rendered output: the hint is conditional on the
    same binding the cards are, so a version that renders one without the other
    is broken in a way that is visible to a visitor and invisible in the source.
    """
    with_bot = _render(STATS, {"username": "hub_bot"})
    assert 'class="hint"' in with_bot, with_bot
    assert "Выбирай страну" in with_bot or "Pick a country" in with_bot, with_bot

    without = _render(STATS, {"username": ""})
    assert 'class="hint"' not in without, without


def test_a_country_that_is_unmeasured_is_not_carded():
    """`unknown` is the one label that must never reach the grid.

    The prober fills `Node.country` from `cdn-cgi/trace`, and a pool that has
    never been probed would otherwise draw a single card reading "not
    measured". Pinned through the rendered output because the filter is applied
    before `countryCards` is even called — a source-string test of the filter
    would not notice it being moved inside the map, which produces the same
    strings and one extra card.
    """
    stats = dict(STATS, by_country=STATS["by_country"] + [{"name": "unknown", "n": 4}])
    html = _render(stats, {"username": "hub_bot"})
    # The codes, not a localised string. `countryName` falls back to the code
    # when the dictionary has no entry, so an UNKNOWN card renders the literal
    # "UNKNOWN" — asserting on "не измерено" was satisfied by the card's
    # *absence of a translation* and would have passed even with the card
    # drawn. The helper used to filter the card out entirely (`[A-Z]{2}`), which
    # is why this test survived the filter being deleted; both halves are fixed
    # together so neither can hide the other again.
    assert [c for c, _ in _cards(html)] == ["NL", "DE", "FI"], html
    assert "UNKNOWN" not in html, html
    assert "unknown" not in html, html
    # And the link must not have been built for it either: a card that links to
    # `?start=UNKNOWN` sends the visitor to a country the bot cannot resolve.
    assert "start=UNKNOWN" not in html, html


def test_an_empty_pool_renders_no_cards_and_no_crash():
    """A generation with nothing in it is a state the page has to survive.

    The live server was serving a demo generation for most of this project's
    life, and the landing page drew it every time. An empty `by_country` must
    produce the "no generation" note rather than a blank panel or a thrown
    error, and it must not produce a hint about clicking countries.
    """
    html = _render(dict(STATS, generation="", by_country=[], verified=0, known=0), {"username": ""})
    assert "<a " not in html, html
    assert 'class="hint"' not in html, html
    assert html.strip(), "the pool panel rendered nothing at all"


def test_switching_to_english_translates_the_cards():
    """The cards are language-aware, and `?lang=en` is how that is verified.

    Pinned because `applyLang` re-renders from `state.data`: a version that
    stored the rendered HTML would leave the cards in Russian after a switch,
    which is the "half-translated page" this project already shipped once.
    """
    html = _render(STATS, {"username": "hub_bot"}, search="?lang=en")
    assert "Germany" in html, html
    assert "Netherlands" in html, html
    assert "Германия" not in html, html
    # And the links survive the language switch rather than being re-rendered
    # without them.
    assert 'href="https://t.me/hub_bot?start=DE"' in html, html


def test_numbers_follow_the_language_the_visitor_chose():
    """A translated page with Russian numbers is still a half-translated page.

    The first version formatted with a hardcoded `toLocaleString("ru-RU")` and
    a `.replace(".", ",")` for the share. On English it rendered `59 013` and
    `0,13%`: a narrow no-break space as the thousands separator and a decimal
    comma. Neither is wrong arithmetic — both are wrong *English*, and the
    comma is the worse of the two because `0,13%` reads as a list of numbers
    rather than one.

    The stub's `navigator.language` is `"en"` and `?lang=ru` is passed
    explicitly, so the two cases genuinely differ: the assertion is that the
    numbers follow the *page's* language, not the browser's, because `?lang=`
    is what overrides it.
    """
    ru = _render(STATS, {"username": "hub_bot"}, search="?lang=ru")
    assert "6" in ru

    # A payload big enough for the separator to be visible in both locales.
    big = dict(STATS, verified=59013, known=59013)
    big["by_country"] = [{"name": "NL", "n": 59013}]
    en = _render(big, {"username": "hub_bot"}, search="?lang=en")
    ru_big = _render(big, {"username": "hub_bot"}, search="?lang=ru")

    assert "59,013" in en, en
    # `ru-RU` separates groups with U+00A0, not U+0020. Written as an escape
    # rather than the character itself on purpose: the two look identical in a
    # diff and in a terminal, so a test that "passes" with the wrong one would
    # be checking a string nobody can see. The intent is the Russian grouping
    # separator specifically, which is what a browser renders.
    assert "59\u00a0013" in ru_big, ru_big
    assert "59,013" not in ru_big, ru_big


def _cards(html: str) -> list[tuple[str, str]]:
    """`[(code, href)]` for each card, in the order the grid renders them.

    Read out of the produced markup rather than from the renderer's inputs, so
    a test that asserts on this is asserting on what a visitor's browser would
    parse. An `<a>` yields its href; a plain `<div>` yields "".

    The whole opening tag is captured and then searched, rather than assuming
    the attribute order: the bundle emits `href` before `data-cc` on the anchor
    and `data-cc` alone on the div, and a pattern built for one order silently
    matches nothing against the other — which is how this helper first
    reported every card as link-less while the cards were anchors.

    `[^"]*` for `data-cc`, deliberately, not `[A-Z]{2}`. The first version was
    `[A-Z]{2}`, and mutation testing showed what it cost: removing the source's
    own `r.name !== "unknown"` filter produced a card reading "UNKNOWN" in the
    markup, and the helper — asked to find it — silently skipped it, because
    7 letters do not match a 2-letter class. `test_a_country_that_is_
    unmeasured_is_not_carded` then passed against a page that had drawn exactly
    the card it forbids. So the helper records what the renderer emitted and
    the assertions decide what is allowed; a helper that pre-judges the answer
    is the second filter my source filter was supposed to be the only one of.
    """
    cards: list[tuple[str, str]] = []
    tags = re.findall(r'<(?:a|div) class="country"([^>]*)>', html)
    for attrs in tags:
        code = re.search(r'data-cc="([^"]*)"', attrs)
        if not code:
            # A card the helper cannot read is a card no assertion here can see,
            # which is the failure mode that hid the UNKNOWN card in the first
            # place. Named rather than skipped: a silent `continue` is how a
            # broken reader and a broken renderer look identical.
            raise AssertionError(
                "a country card was rendered without a readable data-cc; "
                f"the test helper is not seeing the page: {attrs!r}"
            )
        href = re.search(r'href="([^"]*)"', attrs)
        cards.append((code.group(1), href.group(1) if href else ""))
    return cards


import re  # noqa: E402  (kept beside the helper that uses it)
