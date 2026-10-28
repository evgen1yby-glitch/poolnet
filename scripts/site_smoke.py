#!/usr/bin/env python3
"""Browser smoke test for the static site, used by CI.

Serves web/site with a throwaway local HTTP server and checks every page at a
desktop and a phone viewport: no uncaught JS errors, no horizontal overflow,
one meta description, one skip-link and a focusable `<main>`. The proxy page's
API calls are expected to 404 in this fixture; page errors are not.
"""
from __future__ import annotations

import http.server
import re
import socket
import sys
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "web" / "site"
PAGES = [
    "/", "/vpn", "/proxy", "/status", "/verify", "/check", "/legal", "/download", "/404",
    "/en/", "/en/vpn", "/en/proxy", "/en/status", "/en/verify",
    "/en/check", "/en/legal", "/en/download", "/en/404",
]


def serve() -> tuple[http.server.ThreadingHTTPServer, str]:
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(SITE), **kwargs)

        def log_message(self, *_args) -> None:
            pass

        def do_GET(self) -> None:
            # The repository stores templates with `{{key|fallback}}`; the hub
            # fills them from live data. For a static smoke test the fallback is
            # enough, and it avoids a 5,000-character placeholder distorting
            # the width check.
            rel = "index.html" if self.path in ("/", "/en/") else self.path.lstrip("/")
            if not (SITE / rel).is_file() and (SITE / f"{rel}.html").is_file():
                rel = f"{rel}.html"
            if rel.endswith(".html"):
                source = SITE / rel
                if source.is_file():
                    body = re.sub(
                        r"\{\{[^}|]+\|([^}]*)\}\}", r"\1", source.read_text(encoding="utf-8")
                    )
                    body = re.sub(r"\{\{[^}]+\}\}", "", body)
                    payload = body.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
            super().do_GET()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{port}"


def main() -> int:
    server, base = serve()
    failures: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            for width, height, mobile in ((1440, 900, False), (390, 844, True)):
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    is_mobile=mobile,
                    has_touch=mobile,
                )
                for path in PAGES:
                    page = context.new_page()
                    errors: list[str] = []
                    page.on("pageerror", lambda exc: errors.append(str(exc)))
                    page.goto(base + path, wait_until="load", timeout=20_000)
                    time.sleep(0.25)
                    overflow = page.evaluate(
                        "document.documentElement.scrollWidth > window.innerWidth + 1"
                    )
                    if errors:
                        failures.append(f"{width}{path}: page errors {errors[:2]}")
                    if overflow:
                        failures.append(f"{width}{path}: horizontal overflow")
                    if page.locator('meta[name="description"]').count() != 1:
                        failures.append(f"{width}{path}: meta description")
                    if page.locator("a.skip").count() != 1:
                        failures.append(f"{width}{path}: skip link")
                    if page.locator("main#main").count() != 1:
                        failures.append(f"{width}{path}: main target")
                    page.close()
                context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"site smoke: {len(PAGES)} pages x 2 viewports clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
