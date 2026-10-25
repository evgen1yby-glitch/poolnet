"""The platform gateway: the site, both pools' status and the public data.

`api.py` is the hub's core — subscriptions, the operator panel, the bot
endpoints, health. This module is what the merge added around it, and keeping
the two apart is the point: a reader changing subscription behaviour should not
scroll past map dots, and a reader changing page markup should not risk the
feed.

The gateway registers last, so every core route wins over its catch-all. It is
still one app and one process: splitting it into a second service would add a
network hop and a second deployment for no benefit on a single box.

Nothing here raises on missing published data. The site renders its static
fallbacks, `/api/status.json` reports `pool.available: false`, and the pool
file route answers 404 for anything outside its allow-list.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import logging
import threading
from pathlib import Path
from typing import Callable

try:  # FastAPI stays optional for pipeline-only installs; see `api.py`.
    from fastapi import Request
    from fastapi.responses import (
        FileResponse,
        HTMLResponse,
        JSONResponse,
        PlainTextResponse,
        RedirectResponse,
        Response,
    )
except ImportError:  # pragma: no cover - only reached without FastAPI installed
    Request = None  # type: ignore[assignment]

from .checkproxy import check_proxy, parse_proxy
from .gate import RateLimiter
from .poolstatus import SiteDataSource, combined, pool_dir, query_proxies
from .siteview import SiteRenderer
from .store import Store

#: What the site tree may hand out. An allow-list of suffixes, not a blocklist
#: of names: these are the only kinds of file the site directory contains, and
#: a request for anything else is a mistake or a probe.
SITE_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
}

#: The published proxy files a visitor may download. A fixed allow-list:
#: these are the only names the pool's data dir contains that a reader is
#: pointed at. `country/XX.txt` is the one wildcard — two uppercase letters,
#: exactly the shard naming the generator writes.
POOL_FILES = {
    "http.txt": "text/plain; charset=utf-8",
    "socks4.txt": "text/plain; charset=utf-8",
    "socks5.txt": "text/plain; charset=utf-8",
    "all.txt": "text/plain; charset=utf-8",
    "top100.txt": "text/plain; charset=utf-8",
    "top1000.txt": "text/plain; charset=utf-8",
    "proxies.json": "application/json",
    "manifest.json": "application/json",
    "benchmark.json": "application/json",
    "history.json": "application/json",
    "meta.json": "application/json",
    "stats.json": "application/json",
}

#: Extensionless page paths the site owns, for the cache policy in `api.py`.
PAGE_SLUGS = ("vpn", "proxy", "verify", "check", "free", "status", "legal")

_COUNTRY_SHARD = re.compile(r"^[A-Z]{2}\.txt$")

#: VPN generation payloads are public subscriptions, but only the files the
#: manifest declares. A suffix allow-list alone would let an internal temp file
#: through if one ever appeared beside them.
VPN_TYPES = {
    ".base64": "text/plain; charset=utf-8",
    ".singbox": "application/json",
    ".json": "application/json",
    ".clash": "text/yaml; charset=utf-8",
    ".yaml": "text/yaml; charset=utf-8",
}
_CHECK_ADDR = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}:\d{1,5}$")


def client_address(request) -> str:
    """Trust `X-Forwarded-For` only from a loopback nginx peer."""
    peer = request.client.host if request.client else ""
    try:
        if ipaddress.ip_address(peer).is_loopback:
            # nginx overwrites X-Real-IP with `$remote_addr`; prefer it over a
            # client-supplied X-Forwarded-For chain. This keeps the free-key
            # one-per-IP rule tied to the actual peer instead of a spoofable
            # header, and it works even when several proxies append to XFF.
            real = request.headers.get("x-real-ip", "").strip()
            if real:
                return str(ipaddress.ip_address(real))
            forwarded = request.headers.get("x-forwarded-for", "").strip()
            if forwarded and "," not in forwarded:
                return str(ipaddress.ip_address(forwarded))
    except ValueError:
        pass
    return peer


def hash_ip(address: str) -> str:
    """Hash a per-/24 IPv4 or per-/64 IPv6 subnet, never retaining the IP."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return "unknown"
    network = ipaddress.ip_network(f"{ip}/{24 if ip.version == 4 else 64}", strict=False)
    return hashlib.sha256(str(network).encode()).hexdigest()[:16]


class CheckGuard:
    """Bound the on-demand proxy check: an expensive, outbound-connecting route.

    Each request opens a TCP connection to an address a stranger chose and can
    hold it for the full timeout, so two limits apply: a per-subnet token
    bucket (5/min, burst 3 — a person trying several nodes fits, a scanner
    does not) and a global ceiling of concurrent probes (8) so a burst cannot
    exhaust the process's threads or the host's sockets.
    """

    def __init__(self, per_minute: int = 5, burst: int = 3, concurrent: int = 8) -> None:
        self.limiter = RateLimiter(
            rate=per_minute / 60.0, burst=burst, max_buckets=4096
        )
        self.slots = threading.BoundedSemaphore(concurrent)

    def acquire(self, address: str) -> tuple[bool, str]:
        # Take the slot first: a request refused for capacity must not also
        # burn the caller's rate token, or a burst would leave them throttled
        # after the burst cleared.
        if not self.slots.acquire(blocking=False):
            return False, "too many checks in flight: try again shortly"
        if not self.limiter.allow(hash_ip(address)):
            self.release()
            return False, "rate limited: try again in a minute"
        return True, ""

    def release(self) -> None:
        try:
            self.slots.release()
        except ValueError:  # pragma: no cover - defensive: double release
            pass


def register_gateway(
    app,
    *,
    store: Store,
    site_dir: Path,
    pool_directory: Path | None = None,
    legacy_index: Callable[[], str],
    legacy_status: Callable[[], str],
    guard: CheckGuard | None = None,
) -> None:
    """Register the platform routes on `app`, before its catch-all.

    `legacy_index` and `legacy_status` are the hub's own pages, used when the
    merged site is absent — a standalone hub install keeps its landing and its
    status page exactly as before the merge.
    """
    site_dir = Path(site_dir)
    pinned_pool_dir = Path(pool_directory) if pool_directory is not None else None

    def _pool_dir() -> Path:
        return pinned_pool_dir or pool_dir(store)

    renderer = SiteRenderer(site_dir)
    source = SiteDataSource(store, pinned_pool_dir)
    guard = guard or CheckGuard()

    def _render(name: str) -> str | None:
        """Render one page against the current data snapshot, with fallback.

        A broken store or an unreadable publication is an API problem, not a
        reason for the marketing pages to answer 500: the static copy is a
        real, dated snapshot, so serving it is the honest degradation. The
        exception is logged rather than swallowed silently.
        """
        if not (site_dir / name).is_file():
            return None
        try:
            data, version = source.get()
            return renderer.render(name, data, version)
        except Exception as exc:  # noqa: BLE001 - degradation boundary by design
            logging.getLogger(__name__).warning(
                "site render fell back to static %s: %s", name, exc
            )
            return None

    def _page(name: str, status_code: int = 200) -> Response:
        rendered = _render(name)
        if rendered is not None:
            return HTMLResponse(rendered, status_code=status_code)
        path = site_dir / name
        return FileResponse(str(path), media_type="text/html", status_code=status_code)

    def _site_file(rel: str) -> Path | None:
        """Resolve a path inside the site directory, or `None`.

        `resolve()` follows `..` and symlinks before the containment check, so
        a link pointing out of the tree is refused rather than followed; the
        suffix allow-list runs on the resolved name.
        """
        if not site_dir.is_dir():
            return None
        try:
            candidate = (site_dir / rel).resolve()
            candidate.relative_to(site_dir.resolve())
        except (OSError, ValueError):
            return None
        if candidate.suffix not in SITE_TYPES or not candidate.is_file():
            return None
        return candidate

    @app.get("/", response_class=HTMLResponse)
    async def index() -> Response:
        """The merged site's landing, or the hub's own on a standalone install."""
        if (site_dir / "index.html").is_file():
            return _page("index.html")
        return HTMLResponse(legacy_index())

    @app.get("/en", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/en/", response_class=HTMLResponse, include_in_schema=False)
    async def english_index() -> Response:
        """The English landing page.

        English lives in its own tree (`web/site/en/`) rather than behind a
        client-side dictionary: the pages carry server-rendered numbers inside
        sentences, and a DOM swap would either drop the numbers or need a
        template layer. Two trees keep the copy honest and let the renderer
        inject data into both.
        """
        if (site_dir / "en" / "index.html").is_file():
            return _page("en/index.html")
        return _page("index.html")

    @app.get("/status", response_class=HTMLResponse)
    async def status_page() -> Response:
        """`/status` belongs to the merged page when a site is deployed.

        Both projects published a status page under this path; the site's
        carries both pools and is what the navigation points at, so it wins.
        Without a site the hub keeps its own, exactly as before the merge.
        """
        if (site_dir / "status.html").is_file():
            return _page("status.html")
        return HTMLResponse(legacy_status())

    @app.get("/api/status.json", include_in_schema=False)
    async def unified_status() -> JSONResponse:
        """Both pools in one request — what the status page reads.

        `vpn` is the same payload `/api/v1/stats` publishes (one builder, one
        key set); `pool` is the TypeScript engine's published aggregates. With
        no proxy base, `pool.available` is `false` and the page keeps its
        static copy instead of lying with an empty section.
        """
        return JSONResponse(
            combined(store, _pool_dir()),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/proxies", include_in_schema=False)
    def proxy_list(
        page: int = 1,
        per: int = 50,
        proto: str = "",
        grade: str = "",
        country: str = "",
        q: str = "",
    ) -> JSONResponse:
        """One filtered, paginated page of the published pool.

        The browser never downloads the full 32k-row publication: it asks for
        a slice and the controls' counts come from the same scan. Parameters
        are validated here so a typo becomes a 400 with a reason instead of an
        empty list that reads like "no proxies".
        """
        protocols = tuple(part.strip() for part in proto.split(",") if part.strip())
        grades = tuple(part.strip() for part in grade.split(",") if part.strip())
        if any(value not in ("http", "socks4", "socks5") for value in protocols):
            return JSONResponse(
                {"error": "proto must be http, socks4 or socks5"}, status_code=400
            )
        if any(
            value not in ("elite", "anonymous", "transparent", "unknown")
            for value in grades
        ):
            return JSONResponse({"error": "unknown grade"}, status_code=400)
        cc = country.strip().upper()
        if cc and not re.fullmatch(r"[A-Z]{2}", cc):
            return JSONResponse({"error": "country must be a two-letter code"}, status_code=400)
        payload = query_proxies(
            _pool_dir(),
            page=page,
            per=per,
            protocols=protocols,
            grades=grades,
            country=cc,
            query=q[:100],
        )
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/pool/{name:path}", include_in_schema=False)
    async def pool_file(name: str) -> Response:
        """The proxy base's published files from the shared data dir.

        Line lists and JSON are streamed (`FileResponse`): `proxies.json` is
        several megabytes and a full read per request would not scale. The
        allow-list keeps the route a distribution surface, not a file server
        over the engine's whole working directory.
        """
        rel = Path(name)
        ctype = None
        if rel.parent == Path("country"):
            if _COUNTRY_SHARD.fullmatch(rel.name):
                ctype = "text/plain; charset=utf-8"
        else:
            ctype = POOL_FILES.get(name)
        directory = _pool_dir()
        candidate = directory / name
        if ctype is None or not candidate.is_file():
            return PlainTextResponse("нет такой страницы", status_code=404)
        # The allow-list constrains the name; resolve-then-contain also refuses
        # a symlink planted inside the publication dir that points elsewhere.
        try:
            candidate.resolve().relative_to(directory.resolve())
        except (OSError, ValueError):
            return PlainTextResponse("нет такой страницы", status_code=404)
        return FileResponse(
            candidate,
            media_type=ctype,
            headers={"Cache-Control": "max-age=60", "Content-Disposition": "inline"},
        )

    @app.get("/vpn/{name:path}", include_in_schema=False)
    async def vpn_file(name: str) -> Response:
        """The current VPN generation's public subscription payloads.

        Only names listed in the generation manifest are served. Tokens are
        still what the website hands out for a short-term personal link; this
        route is the failover snapshot the GitHub `lists` branch mirrors, so a
        client that cannot reach the API can still import the same nodes.
        """
        generation = store.current_generation()
        if not generation:
            return PlainTextResponse("нет такой страницы", status_code=404)
        directory = store.generation_path(generation)
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return PlainTextResponse("нет такой страницы", status_code=404)
        allowed = {
            str(item.get("name"))
            for item in manifest.get("payloads", [])
            if isinstance(item, dict) and item.get("name")
        }
        if name != "manifest.json" and name not in allowed:
            return PlainTextResponse("нет такой страницы", status_code=404)
        ctype = "application/json" if name == "manifest.json" else VPN_TYPES.get(Path(name).suffix)
        candidate = directory / name
        if ctype is None or not candidate.is_file():
            return PlainTextResponse("нет такой страницы", status_code=404)
        try:
            candidate.resolve().relative_to(directory.resolve())
        except (OSError, ValueError):
            return PlainTextResponse("нет такой страницы", status_code=404)
        return FileResponse(
            candidate,
            media_type=ctype,
            headers={"Cache-Control": "max-age=60", "Content-Disposition": "inline"},
        )

    @app.get("/api/check", include_in_schema=False)
    def check_one(
        request: Request, proxy: str = "", proto: str = "socks5"
    ) -> JSONResponse:
        """Live check of one address the visitor pasted into the check page.

        A blocking probe (socket handshake, one HTTP GET through the tunnel),
        hence a sync handler: FastAPI runs it in its threadpool instead of
        stalling the event loop. `no-store` because a verdict describes this
        moment and caching it would make a dead proxy look alive later.
        """
        address = client_address(request)
        parsed = parse_proxy(proxy, proto)
        if isinstance(parsed, str):
            return JSONResponse(
                {"error": parsed}, status_code=400, headers={"Cache-Control": "no-store"}
            )
        protocol, host, port = parsed
        allowed, reason = guard.acquire(address)
        if not allowed:
            return JSONResponse(
                {"error": reason},
                status_code=429 if "rate" in reason else 503,
                headers={"Cache-Control": "no-store", "Retry-After": "60"},
            )
        try:
            outcome = check_proxy(protocol, host, port)
        finally:
            guard.release()
        return JSONResponse(
            {"proxy": f"{protocol}://{host}:{port}", **outcome},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/data/{name:path}", include_in_schema=False)
    async def old_data_path(name: str) -> RedirectResponse:
        """The retired demo's data URLs, kept as redirects to `/pool/`."""
        return RedirectResponse(f"/pool/{name}", status_code=307)

    @app.get("/{path:path}", include_in_schema=False)
    async def site_page(path: str, request: Request) -> Response:
        """Every public page and asset of the merged site.

        Registered after every other route, so nothing is shadowed. The public
        spelling of a page is extensionless (`/vpn`); `.html` URLs from old
        links and search results answer a permanent redirect instead of
        creating a second indexable copy. Anything the site does not have is
        the site's 404 page, never a directory listing.
        """
        if path.endswith(".html"):
            clean = path[:-5]
            if clean == "index":
                target = "/"
            elif clean.endswith("/index"):
                target = "/" + clean[:-6] + "/"
            else:
                target = "/" + clean
            if request.url.query:
                target += "?" + request.url.query
            return RedirectResponse(target, status_code=301)
        rel = (
            f"{path}.html"
            if (site_dir / f"{path}.html").is_file() and not (site_dir / path).is_file()
            else path
        )
        found = _site_file(rel)
        if found is None:
            not_found = "en/404.html" if path == "en" or path.startswith("en/") else "404.html"
            if (site_dir / not_found).is_file():
                return _page(not_found, status_code=404)
            return PlainTextResponse("нет такой страницы", status_code=404)
        if found.suffix == ".html":
            # The path relative to the site root, not the bare filename: the
            # renderer derives the language from the `en/` prefix, and losing
            # it rendered English pages with Russian generated labels.
            return _page(found.relative_to(site_dir).as_posix())
        return FileResponse(str(found), media_type=SITE_TYPES[found.suffix])
