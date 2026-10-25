#!/usr/bin/env python3
"""Keep sitemap.xml honest as pages are added or renamed.

`--check` (the CI mode) verifies that the sitemap lists exactly the public,
indexable clean URLs and uses no legacy `.html` spelling. `--write` regenerates
the file with today's `lastmod`; run it after adding a page.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "web" / "site"
SITEMAP = SITE / "sitemap.xml"
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
# (path, priority, changefreq): the public, indexable surface. 404 stays out.
PAGES = [
    ("/", "1.0", "daily"),
    ("/en/", "0.9", "daily"),
    ("/proxy", "0.9", "daily"),
    ("/en/proxy", "0.8", "daily"),
    ("/free", "0.9", "weekly"),
    ("/en/free", "0.8", "weekly"),
    ("/vpn", "0.8", "weekly"),
    ("/en/vpn", "0.7", "weekly"),
    ("/verify", "0.6", "monthly"),
    ("/en/verify", "0.5", "monthly"),
    ("/check", "0.5", "monthly"),
    ("/en/check", "0.4", "monthly"),
    ("/status", "0.6", "daily"),
    ("/en/status", "0.5", "daily"),
    ("/legal", "0.4", "yearly"),
    ("/en/legal", "0.3", "yearly"),
    ("/download", "0.8", "weekly"),
    ("/en/download", "0.7", "weekly"),
]
BASE = "https://poolnet.online"


def render() -> str:
    stamp = date.today().isoformat()
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, priority, freq in PAGES:
        lines.append(
            f"  <url><loc>{BASE}{path}</loc><lastmod>{stamp}</lastmod>"
            f"<changefreq>{freq}</changefreq><priority>{priority}</priority></url>"
        )
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def fail(message: str) -> int:
    print(f"sitemap: {message}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write:
        SITEMAP.write_text(render(), encoding="utf-8")
        print(f"sitemap: wrote {SITEMAP}")
        return 0
    try:
        root = ET.parse(SITEMAP).getroot()
    except (OSError, ET.ParseError) as exc:
        return fail(f"cannot read {SITEMAP}: {exc}")
    locs = [node.text or "" for node in root.findall(f"{NS}url/{NS}loc")]
    expected = {BASE + path for path, _, _ in PAGES}
    actual = set(locs)
    if len(locs) != len(actual):
        return fail("duplicate URL")
    if any(".html" in loc for loc in locs):
        return fail("legacy .html URL in sitemap")
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        return fail(f"missing={missing} extra={extra}; run --write")
    print(f"sitemap: {len(expected)} public URLs clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
