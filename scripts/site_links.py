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
    "meta.json",
    "stats.json",
}
COUNTRY = re.compile(r"^country/[A-Z]{2}\.txt$")
HREF = re.compile(r'href="([^"]+)"')


def main() -> int:
    problems: list[str] = []
    pages = sorted(SITE.glob("*.html"))
    required = {
        "index.html",
        "vpn.html",
        "proxy.html",
        "verify.html",
        "check.html",
        "premium.html",
        "status.html",
        "404.html",
    }
    missing = required - {p.name for p in pages}
    if missing:
        problems.append(f"missing pages: {sorted(missing)}")

    for page in pages:
        html = page.read_text(encoding="utf-8")
        if "8931" in html:
            problems.append(f"{page.name}: retired demo port 8931 is back")
        if 'href="#"' in html:
            problems.append(f"{page.name}: dead link href=\"#\"")
        for href in HREF.findall(html):
            if href.startswith(("http://", "https://", "data:", "mailto:", "#")):
                continue
            path = href.split("#")[0]
            if not path:
                continue
            if path.startswith("/pool/"):
                name = path[len("/pool/") :]
                if name not in POOL_NAMES and not COUNTRY.match(name):
                    problems.append(f"{page.name}: unknown pool path {path}")
                continue
            target = SITE / (path[1:] if path.startswith("/") else path)
            if not target.exists():
                problems.append(f"{page.name}: broken link {path}")

    if problems:
        print("\n".join(problems))
        return 1
    print(f"site linkcheck: {len(pages)} pages clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
