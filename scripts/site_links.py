"""Linkcheck for the public site (`web/site`).

Runs in CI on the checkout alone: every relative link and asset must exist,
every `/pool/…` link must be one of the names the hub serves, and the retired
demo port must not come back into the markup.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "web" / "site"
POOL_NAMES = {
    "http.txt",
    "socks4.txt",
    "socks5.txt",
    "all.txt",
    "proxies.json",
    "manifest.json",
    "benchmark.json",
    "history.json",
    "meta.json",
    "stats.json",
}
COUNTRY = re.compile(r"^country/[A-Z]{2}\.txt$")
LINK = re.compile(r'(?:href|src)="([^"]+)"')


def main() -> int:
    problems: list[str] = []
    pages = sorted(SITE.glob("*.html")) + sorted((SITE / "en").glob("*.html"))
    required = {
        f"{tree}{name}.html"
        for tree in ("", "en/")
        for name in ("index", "vpn", "proxy", "tv", "verify", "check", "status", "404", "legal", "download")
    }
    seen = {p.relative_to(SITE).as_posix() for p in pages}
    missing = required - seen
    if missing:
        problems.append(f"missing pages: {sorted(missing)}")

    for page in pages:
        html = page.read_text(encoding="utf-8")
        if "8931" in html:
            problems.append(f"{page.name}: retired demo port 8931 is back")
        if 'href="#"' in html:
            problems.append(f"{page.relative_to(SITE)}: dead link href=\"#\"")
        if html.count('class="lang"') != 1:
            problems.append(f"{page.relative_to(SITE)}: expected one language switch")
        # A disabled control is a feature that looks shipped but does nothing.
        without_pager = re.sub(r'<button[^>]*id="pg-(?:prev|next)"[^>]*>', "", html)
        for href in LINK.findall(html):
            if href.startswith(("http://", "https://", "data:", "mailto:", "#")):
                continue
            path = href.split("#")[0].split("?")[0]
            if not path:
                continue
            if path.endswith(".html"):
                problems.append(f"{page.name}: legacy .html link {href}")
                continue
            if path.startswith("/pool/"):
                name = path[len("/pool/") :]
                if name not in POOL_NAMES and not COUNTRY.match(name):
                    problems.append(f"{page.name}: unknown pool path {path}")
                continue
            if path.startswith("/"):
                target = SITE / path[1:]
            else:
                target = (page.parent / path).resolve()
            if not target.exists() and target.suffix == "":
                html_target = target.with_suffix(".html")
                if html_target.is_file():
                    target = html_target
            if not target.exists():
                problems.append(f"{page.relative_to(SITE)}: broken link {path}")

    if problems:
        print("\n".join(problems))
        return 1
    print(f"site linkcheck: {len(pages)} pages clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
