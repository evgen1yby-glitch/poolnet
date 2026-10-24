"""FastAPI subscription server. Read-only on the hot path.

The endpoint resolves a token, then serves the immutable file inside the live
generation directly. It never triggers a pipeline run, never touches SQLite on
the hot path, and never builds a path from mutable state — the only thing it
trusts is the already-validated `gen-current` pointer.

Serving the bytes straight from the app (rather than 302-ing to nginx) keeps the
subscription headers authoritative in one place; nginx proxies the already-heavy
body, and `Cache-Control` on `location /data/gen-` covers the file path.

Failure posture is fail-open where it can be:

* unknown or blocked token -> 404, no subscription content, no enumeration hint;
* no generation yet -> 503, because serving nothing is the honest answer;
* rate limit exceeded -> 429 on the API surface but **404** on the enumeration
  surface, so a scanner cannot tell "you exist" from "you do not".
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
import itertools
import json
import os
import re
import secrets
import time
from pathlib import Path

from .gateway import PAGE_SLUGS, client_address, hash_ip, register_gateway
from .gate import RateLimiter
from .models import Format, Tier
from .poolstatus import _counts, _last_funnel, vpn_payload
from .store import Store

#: Where the landing page and its assets live, resolved relative to this file
#: so a move of the project does not break them.
_UI_DIR = Path(__file__).resolve().parent / "ui"

#: How old a generation may be before `/healthz` stops calling it fresh.
#:
#: Derived from the probe schedule, not chosen: `hub-probe.timer` re-checks the
#: pool every six hours (`OnCalendar=00/6:17`), and a generation is only as new
#: as the round that produced it. A one-hour threshold — the first version —
#: made `/healthz` report `stale` for five hours out of every six on a
#: perfectly healthy box. That is not a stricter signal, it is a constant one:
#: a monitor that is red 83% of the time is a monitor whose red carries no
#: information, and an operator who learns to ignore it will also ignore the
#: run that genuinely failed. The threshold is therefore one full cycle plus
#: slack for a slow round, so red means "a scheduled re-check did not happen"
#: rather than "the last re-check was a while ago, as planned".
#:
#: `HUB_STALE_AFTER_HOURS` overrides it for an install that probes on a
#: different cadence; an unparseable value falls back to the default, because a
#: typo in a monitoring knob must not take the endpoint down.
_DEFAULT_STALE_AFTER_HOURS = 7.0


def _stale_after_hours() -> float:
    raw = os.environ.get("HUB_STALE_AFTER_HOURS", "").strip()
    if not raw:
        return _DEFAULT_STALE_AFTER_HOURS
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_STALE_AFTER_HOURS
    return value if value > 0 else _DEFAULT_STALE_AFTER_HOURS

#: Truth over origin: FastAPI is an optional dependency, so the UI mounts only
#: when it is present. `hub.ui` ships as package data — see `pyproject.toml`,
#: which must keep these files in wheel builds, or a `pip install`ed hub serves
#: a 404 landing page that no test here can catch.

#: FastAPI's names, made visible *now* so the annotation strings that use them
#: can be resolved — but imported lazily, so `hub.api` still imports on a box
#: with no FastAPI installed (the property `test_imports.py` pins, and the one
#: that lets the pipeline, parser and renderer run on a bare host).
#
#: Why this is needed rather than a convenience: `from __future__ import
#: annotations` stores every annotation as a *string*. FastAPI resolves those
#: strings through `typing.get_type_hints`, which consults module globals and
#: nothing else. The `from fastapi import ...` inside `create_app` below creates
#: the names in that function's local scope, where the resolver cannot see them,
#: so `request: Request` failed to resolve on every route. FastAPI degrades an
#: unresolvable annotation to "unknown type, treat as a query field", which made
#: `request` a *required* query parameter and every request answered 422 before
#: the handler body ran.
try:  # See the comment below: these names are needed *at import time*.
    from fastapi import FastAPI, Request
    from fastapi.responses import (
        FileResponse,
        HTMLResponse,
        JSONResponse,
        PlainTextResponse,
        RedirectResponse,
        Response,
    )
    from fastapi.staticfiles import StaticFiles
except ImportError:  # pragma: no cover - FastAPI is an optional dependency
    # `hub.api` must still import on a host with no FastAPI, so the pipeline,
    # parser and renderer can run there. Nothing in this module runs unless
    # `create_app` is called, and that raises a clear error of its own.
    FastAPI = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]
    HTMLResponse = None  # type: ignore[assignment]
    FileResponse = None  # type: ignore[assignment]
    JSONResponse = None  # type: ignore[assignment]
    PlainTextResponse = None  # type: ignore[assignment]
    Response = None  # type: ignore[assignment]
    StaticFiles = None  # type: ignore[assignment]

#: A country code on the country endpoint: exactly two ASCII letters, and
#: nothing else in the segment. Validated *before* it reaches a path lookup,
#: because the code arrives from the URL: `..`/`%2F`/an absolute path in that
#: segment is a traversal attempt against the generation directory, not a
#: country. Anchored at both ends, so `nl` is the whole segment rather than a
#: prefix of something longer. Case is not constrained here — the endpoint
#: accepts either, and normalises before it looks anything up.
_CC = re.compile(r"[A-Za-z]{2}\Z")

#: The extension `pipeline._publish` writes: `{tier}-{core}.{Format.value}`.
#: This is the *lookup* extension and it must match the producer exactly, or
#: every request 404s. See `_payload_path`.
_FMT_EXT = {
    Format.BASE64: Format.BASE64.value,
    Format.SINGBOX: Format.SINGBOX.value,
    Format.CLASH: Format.CLASH.value,
}

#: The reverse map, for turning a `?format=` query into a known Format without
#: ever constructing an enum from untrusted input.
_FMT_BY_EXT = {ext: fmt for fmt, ext in _FMT_EXT.items()}
_DEFAULT_EXT = _FMT_EXT[Format.SINGBOX]

#: The extension a *client* should see in `Content-Disposition`. These differ
#: from `_FMT_EXT` on purpose: on-disk names are the pipeline's business, but a
#: client seeing `verified-sing-box.singbox` has no idea what that is, whereas
#: `.json` is the extension every mainstream subscription client expects.
_CLIENT_EXT = {
    Format.BASE64: "txt",
    Format.SINGBOX: "json",
    Format.CLASH: "yaml",
}

#: Content-Type per format, not per extension, so it can never drift from the
#: body the renderer actually produced. A mismatched type makes some clients
#: skip the body entirely, so this is pinned rather than delegated to `mimetypes`.
_CONTENT_TYPE = {
    Format.BASE64: "text/plain; charset=utf-8",
    Format.SINGBOX: "application/json; charset=utf-8",
    Format.CLASH: "application/x-yaml; charset=utf-8",
}

#: What `?format=` accepts. Two spellings per dialect, because the request comes
#: from two different places:
#:
#: * the **on-disk** name (`singbox`, `base64`, `clash`) — what the pipeline
#:   writes, and what an operator or a link copied from a manifest carries;
#: * the **client-facing** name (`json`, `txt`, `yaml`) — the extension a user
#:   or a client actually types, and the one `Content-Disposition` shows.
#:
#: Accepting only the first meant `?format=yaml` was unrecognised and silently
#: fell back to the sing-box dialect, so a request for a Clash payload was
#: answered with sing-box JSON and the `application/x-yaml` content type it
#: asked for. Both spellings resolve to the same Format, and the unknown-value
#: fallback below still covers genuinely bad input.
_FMT_BY_QUERY: dict[str, Format] = {}
for _fmt in _FMT_EXT:
    _FMT_BY_QUERY[_fmt.value] = _fmt  # on-disk spelling, e.g. "singbox"
    _FMT_BY_QUERY[_CLIENT_EXT[_fmt]] = _fmt  # client spelling, e.g. "json"
del _fmt

#: The cores a generation contains payloads for, and the order the API prefers
#: them. `sing-box` leads because sing-box's own client, Hiddify, and Happ all
#: read its JSON dialect; `xray` is the fallback for Xray-only features.
_CORES = ("sing-box", "xray", "mihomo")

#: Header set that the de-facto standard (XTLS/Xray-core discussion #4877) and
#: every mainstream client except v2rayNG actually read. See `_client_headers`.
#: 2200-01-01T00:00:00Z. `subscription-userinfo: expire=` is seconds since the
#: epoch, and `0` means 1970-01-01 to a client — i.e. "already expired", which
#: makes some clients refuse to refresh at all. So "no expiry" has to be written
#: as a real far-future timestamp, not as zero. The previous value,
#: 4102444799, was 2099-12-31T23:59:59Z: one second short of the boundary a
#: reader checking "is this past 2100" wants.
NO_EXPIRY = 7258118400

#: The profile name clients show for the import. Kept to 25 characters or
#: fewer because Happ truncates `profile-title` at 25 — a longer value is cut
#: mid-word, which looks like a broken name rather than a long one. The name
#: states the tier, and the tier names are short by construction.
_TITLE_MAX = 25

#: The page behind `support-url`. Static on purpose: it is opened from a
#: client's import screen, often on a network where the hub is the only host
#: that answers, so it must not depend on a CDN, a font, or JavaScript.
_HELP_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>hub — help</title>
<link rel="stylesheet" href="/static/base.css">
<style>
/* Only layout here. Colour, type and the warning rule come from
   `base.css`, the one file allowed to declare them: this page is reached
   from a client, but it is the same product, and the palette had already
   drifted once when pages carried their own copies. The stylesheet is
   same-origin, so the page still needs nothing from a third party — and if
   it fails to load, the markup below is plain readable HTML. */
.help { max-width: 40rem; margin: 0 auto; padding: 2rem 1.25rem 4rem; }
.help h1 { font-size: 1.5rem; }
.help h2 { font-size: 1.05rem; margin-top: 2.2rem; }
.help p, .help li { max-width: 62ch; }
.help p + p { margin-top: 0.8rem; }
.help code { background: var(--paper-2); padding: 0.08rem 0.34rem; border-radius: var(--r-sm); }
.help .warn strong { color: var(--warn); }
.help .warn { margin: 1.4rem 0; color: var(--ink); }
</style>
</head>
<body>
<main class="help">
<h1>hub — subscription help</h1>

<p>This endpoint serves a subscription list of free, third-party proxy nodes.
The hub only <em>publishes</em> the list; it never carries your traffic and
never sees it.</p>

<div class="warn">
<strong>These nodes are not trusted.</strong> They are collected from public
sources and were reachable when last checked. Assume the operator of any node
can observe and modify what passes through it. Do not sign in to accounts you
care about while using one, and never treat it as a privacy guarantee.
</div>

<h2>Importing</h2>
<p>Add the subscription URL to your client. For a single country, append
<code>/country/XX</code> to the token path, where <code>XX</code> is a
two-letter code such as <code>FI</code> or <code>US</code>. A code with no
nodes answers 404 and lists the codes that exist.</p>

<h2>Choosing a format</h2>
<p>The default is sing-box JSON. Add <code>?format=base64</code> for a
newline-delimited list of share URIs, or <code>?format=yaml</code> for Clash /
mihomo YAML. Base64 is the safest choice for a client that accepts share URIs
directly.</p>

<h2>Freshness</h2>
<p>The list is rebuilt when the nodes are re-checked, not continuously. A node
list can be hours old, and its age is reported by <code>/healthz</code>. A
node that worked yesterday may be gone today.</p>

<h2>Status</h2>
<p>The current generation and health are at <code>/healthz</code>. If a
subscription stops loading, check that first: an empty or stale generation
looks identical to a broken link from the client's side.</p>

</main>
</body>
</html>
"""


class _HeadAsGet:
    """Let HEAD reach the GET handlers, then drop the response body.

    FastAPI's `@app.get` does not register HEAD (unlike Flask), so the app
    answered **405** to a HEAD probe of a subscription URL while GET on that
    same URL returned **200**. The asymmetry is what does the damage: a client
    or an operator's health check that probes with HEAD is told the method is
    not allowed, which reads as "this link is broken" for a link that works.

    Rewriting the method at the ASGI layer, rather than adding `@app.head`
    handlers, is deliberate on two counts:

    * the subscription handlers are local functions inside `create_app`, so a
      sibling handler cannot call them — an `@app.head` route that tried
      raised `NameError: name '_subscription_country' is not defined`;
    * one rewrite covers every route at once, including the country and tier
      forms and anything added later, instead of a handler per route that can
      silently fall out of sync.

    The body is dropped here because Starlette's `Response.__call__` writes
    `body` regardless of the request method: without this, a HEAD would put the
    full ~16 KiB payload on the wire for a request that asked for headers only.
    The `content-length` header is left as the GET would report it, which is
    what RFC 9110 asks for.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "HEAD":
            await self.app(scope, receive, send)
            return

        # A copy: mutating the incoming scope in place would leak the rewritten
        # method into anything else holding a reference to it.
        scope = dict(scope, method="GET")

        async def send_headers_only(message):
            if message["type"] == "http.response.body":
                message = dict(message, body=b"", more_body=False)
            await send(message)

        await self.app(scope, receive, send_headers_only)


class _CachePolicy:
    """Give the two dynamic prefixes an explicit `Cache-Control`.

    Both were previously left to the client, and an HTTP client with no
    `Cache-Control` falls back to *heuristic* freshness — typically 10% of the
    file's age, with no upper bound. That produced two production-visible
    defects from one missing header:

    * `/static/hub.js` was served with `ETag` and `Last-Modified` only, so a
      browser kept the previous bundle after a redeploy while fetching the new
      `index.html`. The page then ran code from two releases at once — the
      "deploy did not happen" bug that a hard refresh hides from whoever is
      debugging it.
    * `/sub/<token>` had no policy at all, which is wrong twice over: the URL
      *is* the bearer token, so a shared cache would store a credential; and
      `?unique=1` answers with a different node set on each request, so any
      caching layer pins one rotation and defeats the feature.

    The two policies differ on purpose:

    * `/static/` gets `no-cache` — store it, but revalidate. The ETag makes an
      unchanged file a 304, so this costs a conditional request, not a
      re-download. `no-store` here would throw away the 304 that makes
      revalidation cheap.
    * `/sub/` gets `no-store` — do not keep it. A 304 on a rotating payload
      would assert "same as last time", which is false.

    **`/sub/` is matched on the prefix, not on the handler's 200 path.** The
    404 for a country with no shard is a response a client may cache too, and a
    cached 404 outlives the round that publishes the shard to a non-404. The
    test that asserts this walks the country route's 404, not only its 200.

    Pure ASGI, like `_HeadAsGet` and for the same reason: a `BaseHTTPMiddleware`
    between the two buffers the body to hand it to `call_next`, which re-sends
    `http.response.body` after completion — the HEAD rewrite then saw the body
    twice and the suite failed. Rewriting on `http.response.start` leaves the
    body path exactly as the app wrote it.
    """

    #: `(prefix, policy)`, longest prefix first is unnecessary: the prefixes do
    #: not overlap, and a route below one of them matches exactly one.
    POLICY = (
        ("/static/", b"no-cache"),
        # Same reasoning as `/static/`: a design is rebuilt often and reviewed
        # immediately, and a cached stylesheet beside fresh markup is the bug
        # that already produced one silent visual regression here. Set here,
        # not in nginx, so the response carries exactly one `Cache-Control`.
        ("/design/", b"no-cache"),
        ("/sub/", b"no-store"),
        ("/admin", b"no-store"),
        ("/admin/", b"no-store"),
        ("/api/v1/sub/", b"no-store"),
        ("/api/v1/bot/", b"no-store"),
    )

    def __init__(self, app, site_index: bool = False, site_slugs: tuple = ()):
        self.app = app
        #: Whether `/` is a site page at all, and which extensionless page
        #: slugs (`/vpn`, `/proxy`, …) the site owns. Fixed once at app
        #: creation: re-checking the directory per request would make the
        #: cache policy change on a file rename, which is the bug the tests
        #: pin.
        #: The site's extensionless page paths (`/vpn`, `/proxy`, …): same
        #: policy as their `.html` twins, computed once with them.
        self.site_index = site_index
        self.site_slugs = {f"/{slug}" for slug in site_slugs}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        policy = next((p for prefix, p in self.POLICY if path.startswith(prefix)), None)
        if policy is None and (
            path.endswith((".html", ".css", ".js", ".png", ".jpg", ".svg", ".ico", ".woff", ".woff2"))
            or (path == "/" and self.site_index)
            or path in self.site_slugs
            or path == "/en"
            or path.startswith("/en/")
        ):
            # The PoolNet site pages: rebuilt often and reviewed immediately,
            # the same bug class `/design/` guards against — a cached
            # stylesheet beside fresh markup. `/static/` and `/design/` above
            # take precedence; a suffix this far down is a site path, and the
            # hub's own landing (no site deployed) keeps its old behaviour —
            # no `Cache-Control` at all — so a hub install alone tests and
            # behaves exactly as before.
            policy = b"no-cache"
        if policy is None:
            await self.app(scope, receive, send)
            return

        async def send_with_policy(message):
            if message["type"] == "http.response.start":
                # Replace, not append: two `Cache-Control` headers are resolved
                # inconsistently between clients and caches.
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"cache-control"
                ]
                headers.append((b"cache-control", policy))
                message = dict(message, headers=headers)
            await send(message)

        await self.app(scope, receive, send_with_policy)


def _profile_title(tier: Tier, core: str) -> str:
    """The `profile-title` value, ASCII so no client has to guess an encoding.

    `profile-title` accepts `base64:<b64>` for non-ASCII, and a plain value
    otherwise. A plain value is used here because every name this produces is
    ASCII, and a plain string is what the widest set of clients reads without a
    decode step.

    The whole value is kept under `_TITLE_MAX` by choosing a SHORT name, not by
    slicing a long one. `?unique=1` resolves to a rotation variant whose core
    name is `unique-rot10`, and `hub verified (unique-rot10)` is 27 characters —
    slicing at 25 produced `hub verified (unique-rot1`, an unbalanced parenthesis
    that reads as a corrupted name. A trailing `…` would have been truncation
    made visible but still a cut name, so the core is abbreviated instead: the
    rotation counter is dropped, because which rotation round answered is not
    something the client shows or the user needs.
    """
    if core.startswith("unique-rot"):
        core = "unique"
    title = f"hub {tier.value} ({core})"
    if len(title) > _TITLE_MAX:
        # No shorter honest name exists for an unexpected core: name the tier
        # alone rather than invent one or emit a cut one.
        title = f"hub {tier.value}"
    return title


def _client_headers(
    user_agent: str, tier: Tier, core: str, fmt: Format, base_url: str,
    expires_at: str | None = None,
) -> dict:
    """Headers a subscription client parses to render the import UI.

    Three details are load-bearing:

    * `subscription-userinfo` must carry **both** `total` and `expire`; Hiddify
      silently discards the whole block (and then `support-url` /
      `profile-web-page-url`) otherwise.
    * `expire` is a **real timestamp**, not a flag. `expire=0` means
      1970-01-01, and clients render that as "expired". A term-limited key uses
      its own `expires_at`; an operator/permanent key keeps the far-future
      `NO_EXPIRY`, which is why `NO_EXPIRY` is not zero.
    * every URL sent here must resolve. `profile-title` and `support-url` are
      rendered as a name and a tappable tile, so a header pointing at a 404 is
      worse than the header being absent: the client advertises a link that
      fails. `/help` is a real route for exactly this reason.
    """
    announce = "Unverified third-party nodes. Assume hostile; never send credentials."
    expire = NO_EXPIRY
    if expires_at:
        try:
            moment = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            expire = int(moment.timestamp())
        except ValueError:
            expire = NO_EXPIRY
    headers = {
        "profile-title": _profile_title(tier, core),
        "profile-update-interval": "6",
        "subscription-userinfo": f"upload=0; download=0; total=0; expire={expire}",
        "profile-web-page-url": base_url or "",
        "support-url": (base_url.rstrip("/") + "/help") if base_url else "",
        "announce": announce,
        "content-disposition": f'attachment; filename="{tier.value}-{core}.{_CLIENT_EXT[fmt]}"',
    }
    return {k: v for k, v in headers.items() if v}


def create_app(store: Store | None, sources: dict | None = None):
    """Build the FastAPI app.

    Kept as a factory so the CLI and tests construct it with a Store (or a
    stub). The names this module needs (`FastAPI`, `Request`, ...) are imported
    at module scope above so the annotation strings resolve, but they are
    optional: on a host with no FastAPI the import above substitutes `None`, and
    this factory says so plainly instead of failing later on a `None` call.
    """
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed; pip install -r requirements.txt")

    sources = sources or {}
    if store is None:
        store = Store(Path(os.environ.get("HUB_ROOT", Path.cwd())))

    # The environment wins over the config file, and both surfaces read it the
    # same way (see `cli._bot`). A checked-in `base_url` is one deployment's
    # origin, so it is wrong for every other install — it advertises links to a
    # server the operator does not run. Reading only the file here made the bot
    # and the subscription headers disagree about the same deployment.
    base_url = (
        os.environ.get("HUB_BASE_URL", "").strip()
        or str(sources.get("base_url", "") or "")
    ).rstrip("/")
    #: Bot username without the leading `@`, or "" when there is no bot. Read
    #: by `/api/v1/bot` so the landing page's country cards can deep-link into
    #: it instead of hard-coding a host that only exists on one install.
    bot_username = str(sources.get("bot_username", "")).lstrip("@").strip()
    #: Legacy app-state mapping retained for embedders; issued subscriptions are
    #: persisted by Store and their bearer tokens are stored only as hashes.
    subscriptions: dict[str, dict] = {}
    limiter = RateLimiter(rate=240 / 3600.0, burst=240, max_buckets=10_000)
    ip_limiter = RateLimiter(rate=600 / 3600.0, burst=600, max_buckets=10_000)
    # Public free keys: three per hour per subnet is enough for a household and
    # not enough to mint a pool of throwaway subscriptions.
    free_limiter = RateLimiter(rate=5 / 3600.0, burst=3, max_buckets=4096)
    # Five login attempts per quarter hour per subnet. The secret is long, but
    # an unauthenticated form on the public vhost should still have a ceiling.
    admin_login_limiter = RateLimiter(rate=5 / 900.0, burst=5, max_buckets=4096)

    #: The interface mockup is a design artifact, not a product surface, and it
    #: lives in the repository rather than in the package. It is served from
    #: disk so that opening it needs no checkout path baked into the code, and
    #: so a `git pull` that rebuilds it needs no restart.
    mockup_path = Path(
        os.environ.get("HUB_MOCKUP", "")
        or store.root / "docs" / "design" / "mockup.html"
    )

    #: The two design directions under evaluation, and their font files. They
    #: live beside the mockup in the repository for the same reason: a design
    #: is reviewed on a phone, and a phone has no checkout. Served from disk so
    #: a rebuild (`build_directions.py`) shows up on the next request.
    design_dir = Path(
        os.environ.get("HUB_DESIGN", "")
        or store.root / "docs" / "design"
    )

    #: The public site of the merged project (`PoolNet`): multipage static
    #: grown from the design mockup, served under `/` when present. It lives
    #: beside the hub checkout (`../web/site`) so `git pull` deploys pages on
    #: the next request without a restart, for the same reason `/design/` is
    #: served from disk. `HUB_SITE` moves it; a hub installed without a site
    #: keeps serving its own landing (`_UI_DIR/index.html`) unchanged, so a
    #: standalone install and the older tests are unaffected.
    site_dir = Path(
        os.environ.get("HUB_SITE", "")
        or store.root.parent / "web" / "site"
    )

    app = FastAPI(title="hub", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.subscriptions = subscriptions
    app.state.base_url = base_url
    app.state.bot_username = bot_username
    app.state.limiter = limiter
    app.state.ip_limiter = ip_limiter
    app.state.mockup_path = mockup_path
    app.state.site_dir = site_dir

    # Registered whether or not the UI directory exists: `/sub/` needs its
    # policy on an install that only serves the feed.
    app.add_middleware(
        _CachePolicy,
        site_index=(site_dir / "index.html").is_file(),
        site_slugs=tuple(
            name for name in PAGE_SLUGS if (site_dir / f"{name}.html").is_file()
        ),
    )

    if _UI_DIR.is_dir():
        # Served from the app, not from nginx, so a bare `python -m hub.cli
        # serve` presents a complete page. The cache policy for this mount is
        # in `_CachePolicy` above, which also explains why `StaticFiles` needs
        # one: it sends validators but no `Cache-Control`.
        app.mount("/static", StaticFiles(directory=str(_UI_DIR)), name="static")

    @app.get("/help")
    async def help_page() -> HTMLResponse:
        """Where `support-url` points, and why it is a real page.

        `support-url` is rendered by Hiddify, mihomo, Shadowrocket and Happ as
        a tappable tile inside the subscription's import screen. Advertising
        `{base_url}/help` without serving `/help` gave every one of those
        clients a link to a 404 — a defect the client-side UI cannot report
        usefully, because the failure happens outside this service's response.

        The content is deliberately static and self-contained: this page must
        render with no network, no JavaScript and no assets, because the
        clients that open it are frequently on a network where the hub is the
        only reachable host.
        """
        return HTMLResponse(_HELP_HTML)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        generation = store.current_generation()
        if generation is None:
            # Serving nothing is honest, but it is also an outage.
            return JSONResponse({"status": "no-generation"}, status_code=503)
        manifest_path = store.generation_path(generation) / "manifest.json"
        if not manifest_path.exists():
            return JSONResponse({"status": "missing-manifest"}, status_code=503)
        age = time.time() - manifest_path.stat().st_mtime
        status = "ok" if age < _stale_after_hours() * 3600 else "stale"
        return JSONResponse({"status": status, "generation": generation, "age_s": round(age)})

    @app.get("/metrics")
    async def metrics() -> PlainTextResponse:
        generation = store.current_generation() or ""
        active_subscriptions = store.count_subscriptions(status="active")
        lines = [
            f"hub_generation {generation}",
            f"hub_payload_valid {1 if generation else 0}",
            f"hub_subscriptions {active_subscriptions}",
        ]
        return PlainTextResponse("\n".join(lines) + "\n")

    @app.get("/sub/{token}")
    async def subscription_default(request: Request, token: str):
        return await _subscription(request, token, Tier.VERIFIED)

    @app.get("/sub/{token}/{tier}")
    async def subscription_tier(request: Request, token: str, tier: str):
        """Tier as a path segment, because clients let users type it.

        An unknown tier is 404, never a 500: the tier name comes straight off
        the URL, and an unvalidated enum construction turns a typo into an
        incident for the whole endpoint.
        """
        try:
            tier_name = Tier(tier.lower())
        except ValueError:
            return Response(status_code=404)
        return await _subscription(request, token, tier_name)

    @app.get("/sub/{token}/country/{cc}")
    async def subscription_country(request: Request, token: str, cc: str):
        """One country's nodes, as a link a client can be given directly.

        This is the "paste the link into Hiddify and get a list of countries"
        ask, narrowed to one country per link: `country/nl` renders as a single
        "Netherlands" destination instead of a flat list where the country is
        only a naming convention in a remark.

        The payload was written at publish time rather than rendered here, and
        that is forced: this endpoint serves bytes from a generation directory
        and holds no `Node` objects, so a shard that is not on disk before the
        request arrives cannot be produced during it. `renderer.country_shards`
        writes it; the API only looks it up.

        An unknown code is a 404 that *names what exists*. A bare 404 is the
        right answer for a token the caller may not have, and the wrong answer
        for a country: this one is not a secret, and "the pool has no DE shard
        yet" is exactly the information the caller needs.
        """
        code = cc.strip()
        # `isascii()` first is not the deciding term and cannot be: `_CC` is
        # `[A-Za-z]{2}\Z`, so every string it matches is ASCII already and no
        # input exists that passes one and fails the other. It is kept as
        # defence-in-depth for the day `_CC` widens to a non-ASCII script, and
        # `tests/test_api.py::test_a_value_matching_the_country_regex_is_always_ascii`
        # records why it cannot be pinned by any fixture.
        if not code.isascii() or not _CC.match(code):
            return Response(status_code=404)
        # Upper-case for the lookup, and the URL takes either: `country/nl` and
        # `country/NL` are the same link, and a client that lower-cases a link
        # the user pasted must not get a 404 for it.
        return await _subscription(
            request, token, Tier.VERIFIED, country=code.upper()
        )

    async def _subscription(
        request: Request, token: str, tier: Tier, *, country: str = ""
    ):
        ip_key = hash_ip(client_address(request))
        # IP limiting happens before token lookup to keep random-token scans
        # bounded. Token buckets are allocated only for a valid subscription.
        if not ip_limiter.allow(ip_key):
            return Response(status_code=404)
        if not _token_exists(token, subscriptions, store):
            return Response(status_code=404)
        store.touch_subscription(token)
        if not limiter.allow(hashlib.sha256(token.encode()).hexdigest()):
            return Response(status_code=429, headers={"Retry-After": "3600"})

        generation = store.current_generation()
        if generation is None:
            return JSONResponse({"error": "no payload published yet"}, status_code=503)

        # What the caller asked for, and what the file on disk is called, are
        # two different names: `?format=yaml` selects the Clash dialect, whose
        # payload the pipeline wrote as `{tier}-{core}.clash`. Resolving one
        # name and using it for both is what made `?format=yaml` return
        # sing-box JSON — the query resolved to nothing, fell through to the
        # default, and then looked for `.singbox`.
        requested = (request.query_params.get("format") or _DEFAULT_EXT).lower()
        fmt = _FMT_BY_QUERY.get(requested)
        if fmt is None:
            # An unknown format falls back to the dialect almost every client
            # reads, rather than 404-ing a request that was otherwise fine.
            fmt = Format.SINGBOX
        ext = _FMT_EXT[fmt]  # the on-disk extension, for the actual lookup

        # A country shard is `{tier}-{CC}.{ext}`, a whole-tier payload is
        # `{tier}-{core}.{ext}`. Same prefix, same lookup, one fewer segment.
        prefix = f"{tier.value}-{country}" if country else tier.value

        # `?unique=1` serves the one-node-per-country variant. It exists for
        # clients that cannot group: Happ's documentation describes a
        # subscription body as a URI list or a JSON array and never mentions
        # proxy groups, so the `urltest` grouping the default payload carries is
        # invisible there and the flat list repeats a country once per node.
        # Only the base64 dialect has a unique variant — the JSON and YAML
        # payloads keep their groups, which is strictly better where they work.
        # `?core=xray` selects the Xray dialect, which is a *different schema*
        # under the same `.json` extension. It is what gives a Happ user
        # automatic failover: Happ passes a JSON body to the Xray core
        # verbatim, so the balancers declared in `{tier}-xray.json` run inside
        # the client and re-point traffic when a node dies.
        #
        # Without this the only JSON the API can serve is the sing-box dialect,
        # which Happ would hand to Xray unchanged and Xray would refuse — the
        # client would show a config that cannot start.
        if (
            fmt is Format.SINGBOX
            and (request.query_params.get("core") or "").strip().lower() == "xray"
            and not country
        ):
            xray = _payload_path(store, generation, f"{tier.value}-xray", "json")
            if xray is not None:
                prefix, ext = f"{tier.value}-xray", "json"

        if _wants_unique(request) and fmt is Format.BASE64 and not country:
            rotated = _rotated_payload(store, generation, tier.value)
            if rotated is not None:
                prefix = rotated

        path = _payload_path(store, generation, prefix, ext)
        if path is None:
            available = sorted(p.name for p in store.generation_path(generation).iterdir())
            if country:
                # Name what *is* there. A 404 for a country is not a secret the
                # way an unknown token is, and "the pool has no DE shard yet" is
                # the answer the caller needs in order to stop retrying.
                #
                # Parsed out of the filenames rather than held in state: the
                # pipeline writes a shard per country and this endpoint reads
                # what it wrote, so the directory *is* the set of countries.
                # `verified-NL.singbox` is the shard for NL.
                head = f"{tier.value}-"
                tail = f".{ext}"
                countries = sorted(
                    name[len(head) : -len(tail)]
                    for name in available
                    if name.startswith(head) and name.endswith(tail)
                    # A whole-tier payload is `verified-sing-box.singbox`; its
                    # middle segment is a core, and every core name is longer
                    # than two letters while a country code is exactly two.
                    and len(name[len(head) : -len(tail)]) == 2
                )
                return JSONResponse(
                    {
                        "error": "no payload for this country",
                        "country": country,
                        "countries": countries,
                        "available": available,
                    },
                    status_code=404,
                )
            return JSONResponse(
                {"error": "payload not found", "available": available}, status_code=404
            )

        # The core is only ever a header value; a shard's name has none, and
        # inventing one would put a lie next to `subscription-userinfo`. The
        # core is whatever follows the tier in the file name, if anything does.
        core = path.stem[len(tier.value) + 1 :] or "auto"
        headers = _client_headers(
            request.headers.get("user-agent", ""), tier, core, fmt, base_url,
            store.subscription_expiry(token),
        )
        return Response(
            content=path.read_bytes(),
            media_type=_CONTENT_TYPE[fmt],
            headers=headers,
        )


    @app.post("/api/free-subscription")
    async def free_subscription(request: Request) -> JSONResponse:
        """A seven-day key for anyone, without Telegram or an account.

        The site's free CTA is the top of the funnel; requiring the bot first
        would make the funnel depend on a channel that may not exist yet. The
        key is public and rate-limited per /24, and the panel can see it as
        source=web next to bot- and panel-issued keys.
        """
        if not free_limiter.allow(hash_ip(client_address(request))):
            return JSONResponse(
                {"error": "too many keys from this network; try again later"},
                status_code=429,
                headers={"Cache-Control": "no-store", "Retry-After": "600"},
            )
        # A per-/24 bucket alone lets a botnet spread across many networks.
        # The daily global budget is deliberately generous; it is a circuit
        # breaker against runaway issuance, not a monetisation limit.
        try:
            daily_limit = max(0, int(os.environ.get("HUB_FREE_DAILY_LIMIT", "2000")))
        except ValueError:
            daily_limit = 2000
        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        if daily_limit and store.count_subscriptions_since(
            day_start.isoformat(), source="web"
        ) >= daily_limit:
            return JSONResponse(
                {"error": "daily free-key budget exhausted; try again tomorrow"},
                status_code=429,
                headers={"Cache-Control": "no-store", "Retry-After": "3600"},
            )
        expires = datetime.now(timezone.utc) + timedelta(days=7)
        for _ in range(3):
            token = _mint_token(0)
            if store.issue_subscription(
                token,
                0,
                label="free-web",
                expires_at=expires.isoformat(),
                source="web",
            ):
                base = base_url.rstrip("/")
                return JSONResponse(
                    {
                        "token": token,
                        "expires_at": expires.isoformat(),
                        "subscription": f"{base}/sub/{token}" if base else f"/sub/{token}",
                    },
                    headers={"Cache-Control": "no-store"},
                )
        return JSONResponse({"error": "could not issue token"}, status_code=503)

    @app.post("/api/v1/bot/issue")
    async def issue_token(request: Request) -> JSONResponse:
        """Called by the bot after a successful membership check.

        Authenticated with a shared secret from the environment; the endpoint
        never assumes the request came from the bot.
        """
        secret = os.environ.get("HUB_BOT_SECRET", "")
        supplied = request.headers.get("x-hub-secret", "")
        if not secret or not hmac.compare_digest(secret, supplied):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"error": "bad json"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "bad json"}, status_code=400)
        try:
            telegram_id = int(payload.get("telegram_id", 0))
        except (TypeError, ValueError):
            telegram_id = 0
        if telegram_id <= 0:
            return JSONResponse({"error": "telegram_id required"}, status_code=400)
        username = str(payload.get("username") or "").strip()[:64]
        source = str(payload.get("source") or "bot").strip()[:40] or "bot"
        expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        token = _mint_token(telegram_id)
        if not store.issue_subscription(
            token, telegram_id, expires_at=expires_at, username=username, source=source
        ):
            # A collision is cryptographically negligible, but retrying is cheap
            # and avoids returning an already-issued bearer credential.
            for _ in range(3):
                token = _mint_token(telegram_id)
                if store.issue_subscription(
                    token, telegram_id, expires_at=expires_at, username=username, source=source
                ):
                    break
            else:
                return JSONResponse({"error": "could not issue token"}, status_code=503)
        url = f"{base_url}/sub/{token}" if base_url else f"/sub/{token}"
        return JSONResponse({"token": token, "url": url})

    @app.post("/api/v1/sub/revoke")
    async def revoke_token(request: Request) -> JSONResponse:
        """Revoke a bearer token without putting it in the request URL."""
        secret = os.environ.get("HUB_BOT_SECRET", "")
        supplied = request.headers.get("x-hub-secret", "")
        if not secret or not hmac.compare_digest(secret, supplied):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"error": "bad json"}, status_code=400)
        token = payload.get("token", "") if isinstance(payload, dict) else ""
        if not isinstance(token, str) or not token:
            return JSONResponse({"error": "token required"}, status_code=400)
        revoked = store.revoke_subscription(token)
        return JSONResponse({"status": "revoked" if revoked else "unknown"})

    @app.get("/api/v1/sub/{token}/status")
    async def token_status(token: str) -> JSONResponse:
        status = _token_status(token, subscriptions, store)
        if status is None:
            return JSONResponse({"status": "unknown"}, status_code=404)
        return JSONResponse({"status": status})

    # ---- operator panel --------------------------------------------------
    #
    # Two layers, and both are load-bearing. The secret is the second: a panel
    # that trusts the secret alone hands the token list to anyone who finds it,
    # through a proxy or a misconfigured vhost or a copied secret. So the
    # *socket peer* is checked first, and exposure requires a request that
    # arrived over loopback — i.e. through an nginx vhost the operator
    # configured on purpose.
    #
    # No login form, no session cookie, no CSRF token. There is one operator,
    # not a user table, and the shared secret already exists in
    # `/etc/hub/hub.env` for the bot. Adding a session layer would add a session
    # file to protect and a CSRF hole to close, for no threat that is not
    # already covered by "loopback plus a secret".

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_page(request: Request):
        """The panel, or the login form.

        A browser that is not logged in is *redirected* to the form rather than
        shown a 403. That is the whole reason the form exists: 403 is correct
        for a script and useless for a person, who has no way to tell "wrong
        secret" from "not allowed at all" and nothing to act on.
        """
        if _admin_session(request) is None:
            return RedirectResponse("/admin/login", status_code=303)
        return HTMLResponse(_admin_html())

    @app.get("/admin/login", response_class=HTMLResponse)
    async def admin_login_page(request: Request):
        """The form. Local/allowlisted peers only; carries no data."""
        if not _admin_peer_allowed(request):
            return PlainTextResponse("not found", status_code=404)
        return HTMLResponse(_admin_login_html())

    @app.post("/admin/login")
    async def admin_login(request: Request):
        """Check the secret and set the session cookie.

        `SameSite=Strict` is the CSRF defence: a cross-site form post cannot
        carry the cookie, so a forged login cannot ride an existing session. A
        token field would be the alternative, and it is defence against a threat
        this page does not have — there is nothing to protect but the act of
        logging in, and that already needs the secret.
        """
        if not _admin_peer_allowed(request):
            return PlainTextResponse("not found", status_code=404)
        if not admin_login_limiter.allow(hash_ip(client_address(request))):
            return HTMLResponse(
                _admin_login_html(error="Слишком много попыток. Повторите через 15 минут."),
                status_code=429,
                headers={"Retry-After": "900"},
            )
        secret = os.environ.get("HUB_BOT_SECRET", "")
        if not secret:
            return JSONResponse({"error": "no secret configured"}, status_code=403)
        form = await request.form()
        supplied = str(form.get("secret") or "")
        if not hmac.compare_digest(secret, supplied):
            return HTMLResponse(
                _admin_login_html(error="Секрет не совпал."), status_code=403
            )
        response = RedirectResponse("/admin", status_code=303)
        # Secure only when the request actually arrived over TLS. The panel is
        # also legitimately reached over plain HTTP through an SSH tunnel; a
        # hard-coded Secure cookie would make that login appear to succeed and
        # then send no cookie at all.
        proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).lower()
        response.set_cookie(
            _ADMIN_COOKIE,
            _admin_cookie_value(secret),
            httponly=True,
            samesite="strict",
            secure=proto == "https",
            path="/admin",
            max_age=60 * 60 * 12,
        )
        return response

    @app.post("/admin/keys/issue")
    async def admin_issue_key(request: Request):
        """Mint a subscription key from the panel. Telegram is not required.

        The bot was the only way in, which made it a dependency rather than an
        optional channel: an operator with no bot token — the shipped default —
        could not hand out a subscription at all. The README already says a dead
        bot degrades to "the web page still works"; for keys it did not, because
        there was no other door.

        The token is returned **once**, here. It is stored as a SHA-256 digest,
        so no later request can recover it — which is why the panel shows a copy
        prompt instead of a table cell, and why there is no "show token" action
        to add later.
        """
        refusal = _admin_refusal(request)
        if refusal is not None:
            return refusal
        form = await request.form()
        label = str(form.get("label") or "").strip()[:120]
        username = str(form.get("username") or "").strip()[:64]
        source = str(form.get("source") or "panel").strip()[:40] or "panel"
        try:
            days = int(str(form.get("days") or "7"))
        except ValueError:
            days = 7
        days = max(1, min(days, 3650))
        expires = datetime.now(timezone.utc) + timedelta(days=days)
        # The store rejects a duplicate digest; a collision is a 1-in-2^256 event
        # and retrying is the honest response rather than reporting it as an
        # error the operator could act on.
        for _ in range(3):
            token = _mint_token(0)
            if store.issue_subscription(
                token,
                0,
                label=label,
                expires_at=expires.isoformat(),
                username=username,
                source=source,
            ):
                return JSONResponse(
                    {"token": token, "label": label, "expires_at": expires.isoformat()}
                )
        return JSONResponse({"error": "could not mint"}, status_code=500)

    @app.post("/admin/keys/extend")
    async def admin_extend_key(request: Request):
        """Add days to an active key by digest prefix."""
        refusal = _admin_refusal(request)
        if refusal is not None:
            return refusal
        form = await request.form()
        prefix = str(form.get("id") or "").strip()
        if len(prefix) != 12 or not all(c in "0123456789abcdef" for c in prefix):
            return JSONResponse({"error": "bad id"}, status_code=400)
        try:
            days = int(str(form.get("days") or "7"))
        except ValueError:
            days = 7
        days = max(1, min(days, 3650))
        count = store.extend_subscription(prefix, days)
        if not count:
            return JSONResponse({"status": "unknown"}, status_code=404)
        if count > 1:
            return JSONResponse({"status": "ambiguous", "count": count}, status_code=409)
        return JSONResponse({"status": "extended", "count": count, "days": days})

    @app.post("/admin/keys/revoke")
    async def admin_revoke_key(request: Request):
        """Revoke by digest prefix — the only identifier the panel has.

        Deliberately not by full digest: the panel shows 12 characters and the
        operator copies what they see, so accepting more than that would be an
        API nobody uses. Twelve hex characters are 48 bits, and a collision
        within one operator's key list is not a scenario worth a longer
        identifier to avoid.
        """
        refusal = _admin_refusal(request)
        if refusal is not None:
            return refusal
        form = await request.form()
        prefix = str(form.get("id") or "").strip()
        if len(prefix) != 12 or not all(c in "0123456789abcdef" for c in prefix):
            return JSONResponse({"error": "bad id"}, status_code=400)
        conn = store.connect()
        try:
            rows = conn.execute(
                "SELECT token_hash FROM subscription_tokens"
                " WHERE token_hash LIKE ? AND status = 'active'",
                (prefix + "%",),
            ).fetchall()
            if not rows:
                return JSONResponse({"status": "unknown"}, status_code=404)
            if len(rows) != 1:
                return JSONResponse({"status": "ambiguous", "count": len(rows)}, status_code=409)
            for (digest,) in rows:
                conn.execute(
                    "UPDATE subscription_tokens SET status = 'revoked'"
                    " WHERE token_hash = ?",
                    (digest,),
                )
            conn.commit()
        finally:
            conn.close()
        return JSONResponse({"status": "revoked", "count": len(rows)})

    @app.post("/admin/logout")
    async def admin_logout():
        """Clear the cookie. POST, so a link cannot log the operator out."""
        response = RedirectResponse("/admin/login", status_code=303)
        response.delete_cookie(_ADMIN_COOKIE, path="/admin")
        return response

    @app.get("/admin/data")
    async def admin_data(request: Request):
        """Everything the panel draws, as one JSON document.

        One request rather than four: the panel is a handful of tables and the
        operator is on a slow link to their own server. Counts and timestamps
        only — the same rule `/api/v1/stats` follows, and for the same reason:
        the moment this returns rows from `nodes`, the panel becomes the scrape
        that endpoint exists not to be.
        """
        refusal = _admin_refusal(request)
        if refusal is not None:
            return refusal
        conn = store.connect()
        try:
            generation = store.current_generation()
            payload = {
                "health": _admin_health(store, generation),
                "pool": {
                    "generation": generation,
                    "verified": conn.execute(
                        "SELECT COALESCE(MAX(node_count), 0) FROM publishes"
                        " WHERE generation = ? AND tier = ? AND core NOT LIKE 'cc:%'",
                        (generation, Tier.VERIFIED.value),
                    ).fetchone()[0],
                    "known": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
                    "by_country": _counts(
                        conn,
                        "SELECT country, COUNT(*) FROM nodes"
                        " WHERE last_ok IS NOT NULL GROUP BY country",
                    ),
                    "by_protocol": _counts(
                        conn, "SELECT protocol, COUNT(*) FROM nodes GROUP BY protocol"
                    ),
                },
                "sources": _admin_sources(conn),
                "generations": _admin_generations(conn),
                "tokens": _admin_tokens(conn),
                "subscriptions": _admin_subscription_stats(conn),
                "funnel": _last_funnel(store),
            }
        finally:
            conn.close()
        return JSONResponse(payload)

    # ---- public status page ----------------------------------------------
    #
    # Deliberately public and deliberately thin: aggregate pool health, and
    # nothing that would let a reader reconstruct the pool. It is the counterpart
    # to `/admin` — the panel shows source URLs because the operator wrote them
    # and a health table without a name is unusable; this page shows counts,
    # because a URL here tells a reader where to fetch the same list directly,
    # which is the one thing an index has.

    @app.get("/mockup", response_class=HTMLResponse)
    async def mockup_page() -> HTMLResponse:
        """The interface mockup, for reviewing the design without a checkout.

        Not a product surface and not linked from anywhere a user reaches: it is
        the specimen sheet, and it shows the operator panel drawn with fixture
        data. Serving it from the repository is what makes it reviewable on a
        phone or by someone who has no shell on this box — the alternative was
        `scp` or an SSH tunnel, and both need a shell.

        `noindex` because a search engine indexing a page that *depicts* an
        admin panel with invented rows would publish a screen that looks like a
        live one. The fixture data is public — a source URL and a country count
        — but a reader has no way to know that from looking at it.

        404 rather than a placeholder when the file is absent: a checkout
        without `docs/` is a legitimate deployment, and an empty specimen sheet
        would read as a broken design rather than a missing file.
        """
        if not mockup_path.is_file():
            return HTMLResponse(
                "<!doctype html><meta charset=utf-8>"
                "<title>hub — макет не собран</title>"
                "<p>Макет не собран. Запустите <code>python3 scripts/build_mockup.py</code>.</p>",
                status_code=404,
            )
        return HTMLResponse(
            mockup_path.read_text(encoding="utf-8"),
            headers={"X-Robots-Tag": "noindex, nofollow"},
        )

    #: What `/design/` will hand out. An allow-list of suffixes, not a
    #: blocklist of names: these are the only kinds of file the design directory
    #: contains, and a request for anything else is a mistake or a probe.
    _DESIGN_TYPES = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".woff2": "font/woff2",
    }

    def _design_file(rel: str) -> Path | None:
        """Resolve a request path inside the design directory, or `None`.

        `Path.resolve()` follows `..` and symlinks *before* the containment
        check, so a link pointing out of the tree is refused rather than
        followed. The suffix check runs on the resolved name, so `x.html/../..`
        cannot smuggle a different type through the allow-list.
        """
        if not design_dir.is_dir():
            return None
        candidate = (design_dir / rel).resolve()
        try:
            candidate.relative_to(design_dir.resolve())
        except ValueError:
            return None
        if candidate.suffix not in _DESIGN_TYPES or not candidate.is_file():
            return None
        return candidate

    def _design_response(path: Path) -> Response:
        return FileResponse(
            str(path),
            media_type=_DESIGN_TYPES[path.suffix],
            headers={
                # Same reasoning as `/mockup`: these pages depict an operator
                # panel drawn with fixture data, so they must not be indexed.
                "X-Robots-Tag": "noindex, nofollow",
            },
        )

    @app.get("/design", include_in_schema=False)
    async def design_index_bare() -> Response:
        return RedirectResponse("/design/", status_code=307)

    @app.get("/design/{path:path}", response_class=HTMLResponse)
    async def design_page(path: str) -> Response:
        """The two design directions, for review on any screen.

        Served from the repository for the reason `/mockup` is: the person who
        has to judge a design is looking at it on a phone, not on this box. The
        root of the tree is the specimen sheet (`directions.html`); the pages
        and fonts it frames are under `pages/` and `assets/fonts/`.

        A 404 for a missing file, never a directory listing: the repository is
        not a gallery, and a listing of it would be one more surface to keep.
        """
        target = design_dir / "directions.html" if path == "" else design_dir / path
        if path == "":
            if not target.is_file():
                return HTMLResponse(
                    "<!doctype html><meta charset=utf-8>"
                    "<title>hub — макеты не собраны</title>"
                    "<p>Макеты не собраны. Запустите "
                    "<code>python3 docs/design/src/build_directions.py</code>.</p>",
                    status_code=404,
                )
            return _design_response(target)

        found = _design_file(path)
        if found is None:
            return PlainTextResponse("нет такого файла", status_code=404)
        return _design_response(found)

    @app.get("/status/data")
    async def status_data() -> JSONResponse:
        """The public status page's payload.

        "Now" means the *published* generation, for the same reason and with
        the same consequence as `/api/v1/stats`: this page read the `nodes`
        index, which keeps every node ever probed — including rows that predate
        the `state` column and can never be published — and reported 832 nodes
        in 43 countries over a generation holding 150 in 29. Two public pages
        quoting two different sizes of the same pool is worse than either being
        slightly stale: a reader who compares them has no way to tell which
        one is the subscription.

        `verified` and `countries` here are therefore the tier's own size and
        the number of country shards, both read from `publishes`.
        """
        conn = store.connect()
        try:
            generation = store.current_generation()
            verified = conn.execute(
                "SELECT COALESCE(MAX(node_count), 0) FROM publishes"
                " WHERE generation = ? AND tier = ? AND core NOT LIKE 'cc:%'",
                (generation, Tier.VERIFIED.value),
            ).fetchone()[0]
            countries = conn.execute(
                "SELECT COUNT(DISTINCT core) FROM publishes"
                " WHERE generation = ? AND tier = ?"
                "   AND core LIKE 'cc:%' AND fmt = ?",
                (generation, Tier.VERIFIED.value, Format.SINGBOX.value),
            ).fetchone()[0]
            payload = {
                "now": {
                    "generation": generation or "",
                    "verified": verified,
                    "countries": countries,
                    "age_s": _generation_age(store, generation),
                },
                "runs": _status_runs(store),
                "sources": _status_sources(conn),
                "generations": _admin_generations(conn, limit=30),
            }
        finally:
            conn.close()
        return JSONResponse(payload)

    @app.get("/api/v1/bot")
    async def bot_info() -> JSONResponse:
        """Return the configured bot username for the landing page."""
        return JSONResponse({"username": app.state.bot_username})

    @app.get("/api/v1/stats")
    async def stats() -> JSONResponse:
        """Return aggregate pool statistics for the landing page.

        Every number here answers one question — *what will I get if I import
        this subscription?* — so the counts come from the published generation,
        not from the `nodes` table. Those are different sets, and the page
        described the wrong one:

        * `nodes` accumulates every probe result ever recorded (832 rows on
          this install), including rows whose `state` column is NULL because
          they predate the column. A row without `state` cannot be rebuilt into
          a node and is never published — `pipeline._carry_forward` skips it by
          design — yet it was counted in `verified`, `by_protocol` and
          `by_country`.
        * The generation holds what actually shipped (150 nodes), because the
          `verified` tier is capped at `target=150` and the per-source cap
          trims further.

        Live, this produced a landing page claiming **NL has 235 nodes** while
        the NL shard a visitor downloads contains 24 — the page was off by an
        order of magnitude on the one comparison a visitor makes first. Worse
        for the country links: the page drew **43 country cards**, the
        generation held **29 shards**, so 14 cards led to a 404. The country
        picker is the feature; a quarter of its entries were dead.

        `verified` therefore counts the whole-tier `verified` payload's nodes,
        and `by_country` counts the shards — both read from `publishes`, which
        is written from the same `payloads` list that writes the generation
        directory. `known` stays the size of the index, because "how big is
        the pool we check" is a different and still useful number; the labels
        on the page say which is which.
        """
        return JSONResponse(vpn_payload(store))

    def _legacy_index() -> str:
        return _UI_DIR.joinpath("index.html").read_text(encoding="utf-8")

    # The platform surface registers last, so every core route above wins over
    # its catch-all. `legacy_index`/`legacy_status` keep a standalone hub
    # install — one without `web/site` — serving its own pages.
    register_gateway(
        app,
        store=store,
        site_dir=site_dir,
        legacy_index=_legacy_index,
        legacy_status=_status_html,
    )

    # Outermost of the app's own wrappers so a HEAD is rewritten before routing
    # decides whether the method is allowed. Added last, and therefore runs
    # first: Starlette builds its middleware stack in reverse order of
    # `add_middleware` calls.
    app.add_middleware(_HeadAsGet)

    return app


def _token_status(token: str, subscriptions: dict, store: Store) -> str | None:
    """Resolve a bearer token to active/revoked without retaining its value."""
    if not token or not token.isascii():
        return None
    operator = os.environ.get("HUB_TOKEN", "")
    if operator and hmac.compare_digest(token, operator):
        return "active"
    legacy = subscriptions.get(token)
    if legacy:
        return str(legacy.get("status", "active"))
    return store.subscription_status(token)


def _token_exists(token: str, subscriptions: dict, store: Store) -> bool:
    return _token_status(token, subscriptions, store) == "active"


#: The operator panel, read from disk on first use so a `git pull` that changes
#: it does not need a Python edit. Same reason `index.html` is a file: markup in
#: a string literal is markup nobody can lint, diff, or open in a browser.
_ADMIN_HTML: str = ""


#: The public status page, read from disk on first use for the same reasons as
#: `_admin_html`: markup in a string literal is markup nobody can lint or diff,
#: and a module-level `read_text()` would break the "imports with no UI
#: directory" property.
_STATUS_HTML: str = ""


def _status_html() -> str:
    global _STATUS_HTML
    if not _STATUS_HTML:
        _STATUS_HTML = (_UI_DIR / "status.html").read_text(encoding="utf-8")
    return _STATUS_HTML


_ADMIN_LOGIN_HTML: str = ""


def _admin_login_html(error: str = "") -> str:
    """The login form, with an optional error line.

    The error is substituted into the markup rather than rendered client-side:
    the page is one field and one message, and a message that only appears after
    a failed fetch is one the operator has to trigger again to read.

    Escaped, because it is the one string on this page that is not a literal —
    it comes from the handler rather than from the template, and a handler that
    ever passes a user-supplied value here must not be able to inject markup.
    """
    global _ADMIN_LOGIN_HTML
    if not _ADMIN_LOGIN_HTML:
        _ADMIN_LOGIN_HTML = (_UI_DIR / "login.html").read_text(encoding="utf-8")
    if not error:
        return _ADMIN_LOGIN_HTML
    import html as _html

    banner = f'<p class="error">{_html.escape(error)}</p>\n'
    return _ADMIN_LOGIN_HTML.replace("<form", banner + "<form", 1)


def _admin_html() -> str:
    """The panel markup, read once.

    Deferred rather than read at import: `hub.api` must import on a host with no
    FastAPI and no UI directory (the property `test_imports.py` pins), and a
    module-level `read_text()` would make the import itself fail there.
    """
    global _ADMIN_HTML
    if not _ADMIN_HTML:
        _ADMIN_HTML = (_UI_DIR / "admin.html").read_text(encoding="utf-8")
    return _ADMIN_HTML


#: Cookie name for the operator session. `__Host-` is not used because the panel
#: is reached over plain HTTP on loopback; the prefix requires `Secure` and a
#: `Path=/`, which would stop it working through an SSH tunnel.
_ADMIN_COOKIE = "hub_admin"


def _admin_cookie_value(secret: str) -> str:
    """A signed session token: `<issued-at>.<hmac>`.

    The session lives entirely in the cookie — no server-side table, nothing to
    persist, nothing to clean up on restart. That works because the token is
    *verified* rather than looked up: an attacker who can write cookies to their
    own browser still cannot mint one without the key.

    The timestamp is in the signed payload so a rotation of the secret
    invalidates every existing cookie, which is the entire point of rotating.
    It is not an expiry — an expiry would need a clock comparison that a
    stateless token cannot do meaningfully without also storing the issue time
    server-side. Rotation is the revocation mechanism, and the panel says so.
    """
    import hashlib
    import hmac as _hmac

    issued = str(int(time.time()))
    mac = _hmac.new(secret.encode(), issued.encode(), hashlib.sha256).hexdigest()
    return f"{issued}.{mac}"


def _admin_cookie_valid(value: str, secret: str) -> bool:
    """Constant-time verification of the session token."""
    import hashlib
    import hmac as _hmac

    if not value or "." not in value or not value.isascii():
        return False
    issued, _, mac = value.partition(".")
    try:
        age = time.time() - int(issued)
    except ValueError:
        return False
    if age < -300 or age > 12 * 3600:
        return False
    expected = _hmac.new(secret.encode(), issued.encode(), hashlib.sha256).hexdigest()
    return _hmac.compare_digest(mac, expected)


def _admin_session(request: Request) -> str | None:
    """The secret to use, from the cookie or the header, or `None` if absent.

    The cookie is checked first because that is the browser path; the header
    stays for `curl` and cron, where setting a cookie is awkward and the header
    is the natural thing to write.
    """
    secret = os.environ.get("HUB_BOT_SECRET", "")
    if not secret:
        return None
    cookie = request.cookies.get(_ADMIN_COOKIE, "")
    if cookie and _admin_cookie_valid(cookie, secret):
        return secret
    supplied = request.headers.get("x-hub-secret", "")
    if supplied and hmac.compare_digest(secret, supplied):
        return secret
    return None


def _admin_peer_allowed(request: Request) -> bool:
    """Whether the panel may answer this peer at all.

    The panel is served on the public domain and protected by the operator
    secret plus a login rate limit. `HUB_ADMIN_IPS` is an optional *restriction*
    for an operator who wants the panel reachable only from known addresses:
    when it is set, every peer (including loopback) must match it. The check uses
    the resolved socket address, never a client-supplied header.
    """
    import ipaddress

    allowlist = {
        item.strip()
        for item in os.environ.get("HUB_ADMIN_IPS", "").split(",")
        if item.strip()
    }
    if not allowlist:
        return True
    peer = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        # A unix socket, or the test transport (`testclient`): not an address,
        # so it cannot prove membership of an allowlist.
        return False
    return address.is_loopback or str(address) in allowlist


def _admin_refusal(request: Request):
    """`None` when the request may see the panel, else the response to send.

    Returns the refusal rather than raising, so both call sites can `return` it
    without a try/except and neither can forget to.

    Three layers, and all three matter:

    * **the socket peer must be local or allowlisted** — the only layer that
      can tell a local request from a remote one when a proxy sits in front;
      non-local peers get the same 404 as a missing page, so the panel does not
      advertise itself;
    * **an unset secret closes the panel** — with both sides empty,
      `compare_digest("", "")` is True and a host that never configured a secret
      would serve the token list to any local caller;
    * **the session comes from a cookie or a header** — cookie for browsers,
      header for scripts. The first version accepted only the header, which made
      the panel unreachable from a browser at all: an operator told to "open
      /admin" got 403 with no way to find out why.
    """
    if not _admin_peer_allowed(request):
        return PlainTextResponse("not found", status_code=404)
    if _admin_session(request) is None:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return None


def _generation_age(store: Store, generation: str | None) -> float | None:
    """Seconds since the current generation was written, or `None`."""
    if not generation:
        return None
    manifest = store.generation_path(generation) / "manifest.json"
    if not manifest.exists():
        return None
    return round(time.time() - manifest.stat().st_mtime)


def _status_runs(store: Store, limit: int = 200) -> list[dict]:
    """Funnel counts per probing run, oldest first, for the history chart.

    From the event log rather than the `checks` table: the stages are a property
    of one *run*, and `checks` keeps a row per node per stage across all
    history, so counting there mixes runs and reports a funnel wider than any
    single pass.

    Only runs that actually probed are included — a fetch-only pass carries no
    stages, and plotting it as zero would draw a cliff in a trend line where
    nothing happened. Oldest first, because that is the order a time axis reads.

    Bounded by `limit` from the *end*: the file grows without bound and the page
    needs the recent shape, not the first week of it.
    """
    import json

    runs: list[dict] = []
    try:
        with store.log.open("r", encoding="utf-8") as handle:
            for line in handle:
                if '"run_done"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("kind") != "run_done":
                    continue
                stages = event.get("stage_survivors") or {}
                tcp = stages.get("survivors.tcp")
                if tcp is None:
                    continue
                runs.append(
                    {
                        "at": event.get("finished_at") or event.get("started_at") or "",
                        "raw": event.get("nodes_raw", 0),
                        "parsed": event.get("nodes_parsed", 0),
                        "tcp": tcp,
                        "tls": stages.get("survivors.tls", 0),
                        "config": stages.get("survivors.config", 0),
                        "http": stages.get("survivors.http", 0),
                        "published": event.get("published", 0),
                    }
                )
    except OSError:
        return []
    return runs[-limit:]


def _status_sources(conn) -> dict:
    """Source counts by state, with no URL.

    The panel names the URLs and this does not, and the difference is the whole
    reason the two pages are separate: a URL on a public page tells a reader
    where to fetch the same pool without passing through the hub.
    """
    rows = conn.execute(
        "SELECT enabled, empty_rounds FROM sources"
    ).fetchall()
    total = len(rows)
    disabled = sum(1 for enabled, _ in rows if not enabled)
    # The same threshold the fetcher disables on, so the page and the logic
    # cannot disagree about what "failing" means.
    failing = sum(
        1
        for enabled, empty in rows
        if enabled and int(empty or 0) >= 20
    )
    return {
        "total": total,
        "working": total - disabled - failing,
        "failing": failing,
        "disabled": disabled,
    }


def _admin_health(store: Store, generation: str | None) -> dict:
    """Generation age and staleness, as `/healthz` reports them."""
    if generation is None:
        return {"status": "no-generation", "generation": "", "age_s": None}
    manifest = store.generation_path(generation) / "manifest.json"
    if not manifest.exists():
        return {"status": "missing-manifest", "generation": generation, "age_s": None}
    age = time.time() - manifest.stat().st_mtime
    return {
        "status": "ok" if age < _stale_after_hours() * 3600 else "stale",
        "generation": generation,
        "age_s": round(age),
    }


def _admin_sources(conn) -> list[dict]:
    """Per-source health: rounds, streak of empties, last success.

    The URL is included, unlike everywhere else in this API. That is deliberate
    and safe: the operator wrote those URLs in `config/sources.yaml`, so
    returning them tells them nothing they do not have, and a health table
    without the name is unusable.
    """
    rows = conn.execute(
        "SELECT url, enabled, rounds, empty_rounds, last_ok FROM sources ORDER BY url"
    ).fetchall()
    out = []
    for url, enabled, rounds, empty_rounds, last_ok in rows:
        out.append(
            {
                "url": url,
                "enabled": bool(enabled),
                "rounds": int(rounds or 0),
                "empty_rounds": int(empty_rounds or 0),
                "last_ok": last_ok or "",
                # The same threshold the fetcher disables on, so the panel and
                # the disable logic cannot disagree about what "failing" means.
                "disabled_soon": int(empty_rounds or 0) >= 20,
            }
        )
    return out


def _admin_generations(conn, limit: int = 20) -> list[dict]:
    """Recent publishes, newest first, one row per generation.

    Grouped by generation rather than listed per payload: a generation writes
    ~20 payloads, and twenty rows all naming the same generation is a wall the
    operator has to read past to find the previous one.
    """
    rows = conn.execute(
        "SELECT generation, MIN(created_at) AS at,"
        " COUNT(*) AS payloads, MAX(node_count) AS nodes"
        " FROM publishes GROUP BY generation ORDER BY at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "generation": gen,
            "at": at or "",
            "payloads": int(payloads or 0),
            "nodes": int(nodes or 0),
        }
        for gen, at, payloads, nodes in rows
    ]


def _admin_token_state(status: str, expires_at: str | None) -> str:
    """active / expired / revoked, with expiry evaluated at read time."""
    if status != "active" or not expires_at:
        return status
    try:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
    except ValueError:
        return "expired"
    return "expired" if expiry <= datetime.now(timezone.utc) else "active"


def _admin_tokens(conn) -> list[dict]:
    """Issued subscriptions: digest prefixes, holder, source and term.

    Only the first 12 hex characters of the digest — enough to tell two keys
    apart and useless as a credential. The full token never exists here: the
    store keeps hashes, and a panel that could show it would be a leak.
    """
    rows = conn.execute(
        "SELECT substr(token_hash, 1, 12), telegram_id, status, created_at, label,"
        " expires_at, username, source, last_seen"
        " FROM subscription_tokens ORDER BY created_at DESC LIMIT 500"
    ).fetchall()
    return [
        {
            "id": prefix,
            "telegram_id": int(tid or 0),
            "status": _admin_token_state(str(status), expires),
            "created_at": created,
            "expires_at": expires or "",
            "username": username or "",
            "label": label or "",
            "source": source or ("bot" if int(tid or 0) else "panel"),
            "last_seen": last_seen or "",
        }
        for prefix, tid, status, created, label, expires, username, source, last_seen in rows
    ]


def _admin_subscription_stats(conn) -> dict:
    """Aggregates for the subscriptions dashboard, evaluated now."""
    now = datetime.now(timezone.utc)
    week = now + timedelta(days=7)
    day = now - timedelta(days=1)
    rows = conn.execute(
        "SELECT status, expires_at, created_at FROM subscription_tokens"
    ).fetchall()
    out = {
        "total": len(rows),
        "active": 0,
        "expired": 0,
        "revoked": 0,
        "expiring_7d": 0,
        "issued_24h": 0,
        "by_source": {},
    }
    for status, expires_at, created_at in rows:
        state = _admin_token_state(str(status), expires_at)
        out[state if state in ("active", "expired", "revoked") else "revoked"] += 1
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")) if expires_at else None
        except ValueError:
            expiry = None
        if state == "active" and expiry is not None and now < expiry <= week:
            out["expiring_7d"] += 1
        try:
            created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            created = None
        if created is not None and created >= day:
            out["issued_24h"] += 1
    # Source counts are cheap here; the panel groups them without another query.
    for _prefix, _tid, status, _created, _label, expires, _user, source, _seen in conn.execute(
        "SELECT substr(token_hash,1,12), telegram_id, status, created_at, label,"
        " expires_at, username, source, last_seen FROM subscription_tokens"
    ):
        if _admin_token_state(str(status), expires) != "active":
            continue
        key = source or ("bot" if int(_tid or 0) else "panel")
        out["by_source"][key] = out["by_source"].get(key, 0) + 1
    return out


def _rotated_payload(store: Store, generation: str, tier: str) -> str | None:
    """One rotation variant's prefix, advancing on every call.

    This is the whole of the rotation mechanism on the serving side. The
    variants are pre-rendered files (`{tier}-unique-rot{N}.base64`); this picks
    one by a counter, so **the same subscription URL returns a different exit
    over time**. A client that refetches — Happ does, on the
    `profile-update-interval` this hub already sends — therefore lands on a
    different node each round without the user doing anything.

    What this is and is not, stated plainly because the distinction is the
    reason the mechanism is server-side at all:

    * It rotates on *fetch*, not on *connection failure*. The server is not in
      the data path — it never sees whether a node works for this client — so it
      cannot react to a drop mid-session. A client that never refetches stays on
      one node until it does.
    * Failover *between* fetches is what the sing-box and mihomo payloads
      provide, with real `urltest` groups. For those clients the rotation is a
      convenience, not the mechanism.
    * Dead nodes leave the pool at the next probe regardless, so a rotated pick
      cannot hand back a node that has already been measured dead.

    Returns `None` when no variant exists, so the caller falls back to the
    unrotated lookup rather than 404-ing a request that used to work.
    """
    rot = next(_ROTATION)
    # Any round the caller lands on is a valid answer, and the file names are
    # contiguous from 0, so listing the directory tells us whether this tier
    # has variants at all.
    probes = sorted(
        p.name
        for p in store.generation_path(generation).iterdir()
        if p.name.startswith(f"{tier}-unique-rot") and p.name.endswith(".base64")
    )
    if not probes:
        return None
    return probes[rot % len(probes)].rsplit(".", 1)[0]


#: Monotonic per-process counter behind `_rotated_payload`. Deliberately *not*
#: keyed by token or client: the point is that everyone advances together, so a
#: shared link spreads its users across the pool instead of pinning them all to
#: whichever node the first fetch happened to pick. A per-client counter would
#: leave two users who imported at the same moment on the same node forever.
_ROTATION = itertools.count()


def _wants_unique(request) -> bool:
    """True when the caller asked for one node per country.

    Read as a flag, not a value: `?unique=1`, `?unique=true`, `?unique=yes` and
    a bare `?unique=` all mean yes. A bare `?unique` is what a user types when
    guessing at a parameter, and treating it as "no" would silently serve the
    full list while looking like it was honoured — the worst of the three
    possible behaviours.
    """
    raw = request.query_params.get("unique")
    if raw is None:
        return False
    return raw.strip().lower() in ("", "1", "true", "yes", "on")


def _payload_path(store: Store, generation: str, prefix: str, ext: str) -> Path | None:
    """Resolve a payload file in a generation, trying every known shape.

    Two shapes, because `pipeline._publish` writes both:

    * `{prefix}-{core}.{ext}`   — a whole-tier payload.
    * `{prefix}.{ext}`          — anything whose name ends at the prefix.

    The naming scheme lives in `pipeline._publish`; this function is the only
    other place that knows it. A payload that a generation does not contain
    returns `None` so the caller can 404 with the list of what *does* exist.

    `prefix` is `{tier}` or `{tier}-{CC}`, which is why it is a string and not a
    `Tier`: the country caller already holds the code, and threading it through
    a keyword most callers cannot fill would make the common path carry a
    parameter it has no use for.
    """
    directory = store.generation_path(generation)
    for core in _CORES:
        candidate = directory / f"{prefix}-{core}.{ext}"
        if candidate.is_file():
            return candidate
    bare = directory / f"{prefix}.{ext}"
    if bare.is_file():
        return bare
    return None


def _mint_token(telegram_id: int) -> str:
    """128-bit random token, not derived from anything about the user.

    A sequential or time-derived token is enumerable; a random one is not, at
    any scale that matters for a free service.
    """
    del telegram_id  # identity is stored separately; bearer secrets stay opaque
    return secrets.token_urlsafe(32)
