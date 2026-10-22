"""The Telegram bot. Optional delivery channel, never the backbone.

aiogram 3.x, long-polling by default (buffers updates up to 24 h, so a dead
server recovers — a webhook does not). Every Telegram call is behind a
`BotTransport` protocol so the whole bot, including the gate, runs against a
mock with no network and no token.

Telegram is under de-facto blocking in Russia (verified March 2026), so:
* every link the bot hands out is also on the web landing page and in the README;
* the bot never *holds* a subscription — it hands out the same public URL;
* a dead bot degrades the service to "the web page still works".
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Optional

from .countries import country_name
from .countries import country_names
from .countries import _parse_country_names as _parse_country_names_impl
from .countries import is_ru as _is_ru_impl
from .gate import Gate, TransportError

#: One broadcast per this many seconds, plus Telegram's own ~25 msg/s global cap
#: and ~1/s per chat. Broadcasts are a background job with their own budget.
BROADCAST_INTERVAL = 25.0


class MockTransport:
    """A `BotTransport` with scripted behaviour, used in tests and mock mode.

    It models the things that actually break in production: rate limits,
    transient 5xx, and the admin-status requirement.
    """

    def __init__(
        self,
        *,
        bot_id: int = 42,
        bot_status: str = "administrator",
        members: Optional[dict[tuple[int, int], str]] = None,
        rate_limit_after: Optional[int] = None,
    ) -> None:
        self.bot_id = bot_id
        self.bot_status = bot_status
        self.members = members or {}
        self.calls: list[tuple[str, int, int]] = []
        self.sent: list[tuple[int, str]] = []
        # `None` means "never rate-limit", which is the useful default: the
        # mock exists for the happy path first, and the rate-limit tests set
        # `rate_limit_after=0` explicitly to fail on the very first call.
        # A default of 0 made every default-constructed transport 429 on its
        # first lookup, so `is_member` could never return True and no amount of
        # scripted `members` helped.
        self.rate_limit_after = rate_limit_after
        self._calls_since_limit = 0

    async def get_chat_member(self, chat_id: int, user_id: int) -> str:
        self.calls.append(("getChatMember", chat_id, user_id))
        if self.rate_limit_after is not None:
            self._calls_since_limit += 1
            if self._calls_since_limit > self.rate_limit_after:
                raise TransportError("429 Too Many Requests", retry_after=1.0)
        # An explicit scripted entry always wins — including one for the bot's
        # own id, which is how a test writes "the bot is no longer an admin" and
        # is the only way `is_admin_ok` can be made False here at all.
        #
        # The fallback for the bot's own id is `bot_status`, which is what makes
        # a *default-constructed* mock usable: `is_admin_ok` looks the bot up by
        # its own id, and with the default answer for that lookup being "left"
        # every default mock failed its own admin check — including the one
        # `run_bot` builds for mock mode, which then refused to start with "the
        # bot must be an administrator of the channel". The field was accepted
        # and stored at construction, and nothing read it.
        if user_id == self.bot_id and (chat_id, user_id) not in self.members:
            return self.bot_status
        return self.members.get((chat_id, user_id), "left")

    async def get_me(self) -> dict:
        return {"id": self.bot_id, "is_bot": True, "first_name": "hub"}

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


@dataclass
class BotConfig:
    token: str
    channel_id: int
    base_url: str = ""
    #: When empty the bot runs in mock mode: same code, transport replaced.
    transport: object | None = None


def _deep_links(base_url: str, token: str) -> dict[str, str]:
    """Client deep links for the same subscription URL.

    The URL is the product; these are conveniences. Per verified client
    behaviour: v2rayNG needs the URL percent-encoded with the name in the
    `#NAME` fragment, Shadowrocket's `sub://` payload is base64 of the URL and
    must *not* be percent-encoded, and sing-box wants `import-remote-profile`.
    """
    return _links_for(_sub_url(base_url, token))


def _sub_url(base_url: str, token: str) -> str:
    """The subscription URL, which is the one thing every link is built from."""
    return f"{base_url.rstrip('/')}/sub/{token}" if base_url else f"/sub/{token}"


def _links_for(url: str) -> dict[str, str]:
    """Per-client import links for *one* subscription URL.

    Split out of `_deep_links` because the country links need exactly this
    mapping for a second URL, and a second copy of the client quirks is a
    second place for them to be wrong. Two of them are already subtle
    (v2rayNG percent-encodes, Shadowrocket base64s); the country path uses the
    same rules for the same reason.
    """
    import base64
    import urllib.parse

    encoded = urllib.parse.quote(url, safe="")
    return {
        "copy": url,
        "hiddify": f"hiddify://import/{url}#hub",
        "v2rayng": f"v2rayng://install-sub?url={encoded}#hub",
        "singbox": f"sing-box://import-remote-profile?url={encoded}#hub",
        "clash": f"clash://install-config?url={encoded}#hub",
        "karing": f"karing://install-config?url={url}&name=hub",
        "shadowrocket": f"sub://{base64.b64encode(url.encode()).decode()}#hub",
    }


#: Label per link key, in the order the intro prints them. Kept next to the
#: mapping so adding a client cannot forget the label: a link the message never
#: prints is a link nobody uses.
_LINK_LABELS = (
    ("Copy URL", "copy"),
    ("Hiddify", "hiddify"),
    ("v2rayNG", "v2rayng"),
    ("sing-box", "singbox"),
    ("Clash", "clash"),
    ("Karing", "karing"),
    ("Shadowrocket", "shadowrocket"),
)


def _code_or_none(value: str) -> str:
    """Two ASCII letters from `value`, or "" when it is not exactly that.

    One normalisation, shared by `country_link` and `_country_arg`, because the
    two inputs are the same piece of data arriving by different routes and the
    failure of normalising them separately is that they disagree.

    The rule that matters: **exactly** two letters, never the first two of
    more. Truncating before checking is what turns "/start please" into "PL" —
    a real country chosen from a word the visitor typed for an unrelated
    reason, and `/start NLD` into "NL". Junk around the letters is stripped
    first (`n<l>` -> `NL`) because that is what a mistyped or copy-pasted
    payload looks like, but extra *letters* mean the argument was never a code.
    """
    code = re.sub(r"[^A-Za-z]", "", value or "").upper()
    return code if len(code) == 2 else ""


def country_link(base_url: str, token: str, country: str) -> str:
    """`/sub/{token}/country/{cc}` — one country, as a link.

    The shard is written at publish time for every measured country, so this
    is the same subscription narrowed to one exit. It is what makes the landing
    page's country cards useful: a visitor picks Netherlands and the client
    shows one "Netherlands" destination instead of every country at once.

    Normalised to two letters rather than interpolated. The input reaches this
    function from a URL the page built and a `/start` payload the visitor
    typed, so neither can be assumed clean, and a country code ends up inside
    an outbound tag on the client.

    Raises rather than falling back to the whole pool. A card linking to a
    country whose code could not be read is a bug, and answering it with every
    other country would look like the feature working while silently ignoring
    what the visitor clicked.
    """
    code = _code_or_none(country)
    if not code:
        raise ValueError(f"not a country code: {country!r}")
    return f"{_sub_url(base_url, token)}/country/{code}"


def _country_arg(message) -> str:
    """Read the country a message asked for, or "" when it asked for none.

    `/start` and `/start NL` are both valid, and the second is how a country
    card reaches the bot: the landing page cannot mint a token (it holds no
    secret and publishes no node list), so it deep-links *here* with the
    country in the payload and the bot answers with that country's links.
    """
    text = getattr(message, "text", "") or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return ""
    # `_code_or_none`, not `[:2]`: a start payload of "please" must not become
    # "PL". Truncating first and checking length after accepts any string that
    # merely *starts* with two letters, which turns an unrelated argument into
    # a real country — the visitor asked for nothing and gets a Netherlands
    # subscription.
    return _code_or_none(parts[1]) or ""


def build_bot(config: BotConfig, gate: Gate, *, status_sink=None):
    """Assemble the aiogram app. Import is deferred so tests never need it.

    Returns `None` in mock mode: the caller gets the transport instead and
    drives the handlers directly. This is what "no bot token yet" means in
    practice — the code is complete and exercised, the token is not.
    """
    if config.transport is None:
        return None

    try:
        from aiogram import Dispatcher
        from aiogram.filters import Command, CommandStart
        from aiogram.types import Message
    except ImportError:  # pragma: no cover
        return None

    dispatcher = Dispatcher()

    async def _deny(message: Message, reason: str) -> None:
        text = (
            f"{reason}\n\n"
            f"Подпишитесь на канал и нажмите /start снова."
            if _is_ru()
            else "Subscribe to the channel and send /start again."
        )
        await message.answer(text)

    @dispatcher.message(CommandStart())
    async def on_start(message: Message, **_) -> None:
        user_id = message.from_user.id if message.from_user else 0
        result = await gate.check(user_id, force=True)
        if result.is_unknown:
            # Do not lock a user out on a rate limit: serve and warn.
            await message.answer(_intro(config.base_url, country=_country_arg(message)))
            return
        if not result.is_member:
            await _deny(message, "Access requires channel membership.")
            return
        token = os.environ.get("HUB_TOKEN", "")
        country = _country_arg(message)
        if country:
            # The visitor arrived from a country card, which is the whole point
            # of the card: answer with *that* country's links. Falling back to
            # the whole pool would ignore what they clicked, and a 404 for a
            # country whose shard has not been written yet is the honest answer
            # rather than a silent switch to every other country.
            source = country_link(config.base_url, token or "demo", country)
        else:
            source = None
        links = _deep_links(config.base_url, token or "demo")
        if source is not None:
            links = _links_for(source)
        await message.answer(_intro(config.base_url, links, country=country))

    @dispatcher.message(Command("check"))
    async def on_check(message: Message, **_) -> None:
        user_id = message.from_user.id if message.from_user else 0
        result = await gate.check(user_id, force=True)
        if result.is_member:
            await message.answer("Membership confirmed.")
        else:
            await _deny(message, "Not a member.")

    @dispatcher.channel_chat_member()
    @dispatcher.chat_member()
    async def on_member_update(event, **_) -> None:
        old = _status_of(event.old_chat_member) if getattr(event, "old_chat_member", None) else "none"
        new = _status_of(event.new_chat_member) if getattr(event, "new_chat_member", None) else "none"
        chat = event.chat.id if getattr(event, "chat", None) else 0
        user = event.from_user.id if getattr(event, "from_user", None) else 0
        gate.on_chat_member_update(chat, user, old, new)

    return dispatcher


def _status_of(member) -> str:
    return str(getattr(member, "status", "") or "")


def _is_ru() -> bool:
    return os.environ.get("HUB_LOCALE", "ru").lower().startswith("ru")


#: Re-exported so the names have exactly one reader (`hub.countries`) while the
#: callers that already import them from this module keep working. `_NAMES` is
#: a property of the parser, not of the bot, and a second copy here would be the
#: same disagreement this delegation exists to prevent.
_country_names = country_names
_parse_country_names = _parse_country_names_impl
_is_ru = _is_ru_impl


def _country_name(code: str) -> str:
    """Localised country name for a code. Delegates to `countries.py`.

    The table itself lives in `ui/hub.js` and is parsed by `hub.countries`,
    which the renderer also uses to label nodes. Keeping one reader means the
    subscription and the landing page cannot disagree about what a country is
    called — the bug where the bot says "Germany" while the card the visitor
    just clicked said "Германия" and the link reads as broken.

    It is imported at module scope from `countries`, not re-parsed here,
    because the renderer must be able to label a node without the Telegram
    library installed.
    """
    return country_name(code)


def _intro(base_url: str, links: dict | None = None, *, country: str = "") -> str:
    #: The safety warning is shared by both shapes and comes first in both,
    #: because it is the one thing that must survive any rearrangement of this
    #: message. `tests/test_api.py` pins it on the landing page too.
    warn = (
        "Unverified third-party nodes. Assume hostile: never send credentials,",
        "sessions, or wallet operations through any listed node.",
    )
    lines: list[str] = []
    if country:
        # Ahead of the pitch, not after it. Telegram shows a few preview lines,
        # and a visitor who arrived from a country card that does not see that
        # country before the fold reasonably concludes the link did nothing.
        # `_country_arg` has already reduced it to two ASCII letters, so it is
        # safe to interpolate into a message.
        lines += [f"🎯 {_country_name(country)} ({country})", ""]
    lines += [
        "hub — decentralised FREE VPN platform",
        "",
        "Free of charge, free as in libres, free as in unblocked: a public",
        "index of working proxy configs, verified five times per run.",
        "",
    ]
    lines += list(warn)
    lines += [""]
    if links:
        for label, key in _LINK_LABELS:
            if key in links:
                lines.append(f"{label}: {links[key]}")
    else:
        lines.append(f"Web: {base_url or '/'}")
    return "\n".join(lines)


def run_bot(config: BotConfig, gate: Gate) -> None:
    """Long-poll entry point. Called by the `hub-bot` systemd unit.

    Mock mode (no token) is a first-class mode: the gate is assembled and
    checked, the deep links are computed and printed, and the process idles.
    That is what "no bot token yet" means operationally — the code path is
    exercised end to end, only the network is absent.
    """
    dispatcher = build_bot(config, gate)
    # Mock mode is chosen by the *transport being the mock one*, never by
    # `build_bot` returning None. Both conditions return None from `build_bot`
    # — no token, and token-with-no-aiogram — and conflating them made mock
    # mode raise `RuntimeError("aiogram is not installed")` on a box that has
    # no aiogram and, correctly, no token. That is the state the project ships
    # in, so the one mode that must work without the optional dependency was
    # the mode it guaranteed to fail.
    if dispatcher is None and not isinstance(config.transport, MockTransport):
        raise RuntimeError("aiogram is not installed")

    async def _main() -> None:
        assert gate.transport is not None
        if not await gate.is_admin_ok():
            raise RuntimeError(
                "the bot must be an administrator of the channel to gate membership"
            )
        if dispatcher is None:
            # Mock mode: report readiness and idle instead of polling.
            token = os.environ.get("HUB_TOKEN", "demo")
            links = _deep_links(config.base_url, token)
            print("bot ready in mock mode")
            for label, key in _LINK_LABELS[:2]:
                print(f"  {label}: {links[key]}")
            print(f"  e.g. one country: {country_link(config.base_url, token, 'NL')}")
            while True:
                await asyncio.sleep(3600)
            return
        await dispatcher.start_polling(config.transport.bot)

    asyncio.run(_main())
