#!/usr/bin/env python3
"""Build the `lists` branch snapshot from the live PoolNet publication.

The repository itself does not commit generated data to `main`: a fresh
`proxies.json` every fifteen minutes would bloat history and bury the code.
A GitHub Actions job fetches the current manifests and payloads, writes this
flat snapshot, and force-pushes it to the `lists` branch, where raw URLs stay
stable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fetch(path: str, base: str) -> bytes:
    url = base.rstrip("/") + path
    request = urllib.request.Request(url, headers={"User-Agent": "PoolNet-lists/1"})
    last: Exception | None = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except (OSError, urllib.error.URLError) as exc:
            last = exc
    raise RuntimeError(f"cannot fetch {url}: {last}")


def safe_name(name: str) -> str:
    rel = Path(name)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe manifest name: {name!r}")
    return rel.as_posix()


def write(out: Path, rel: str, body: bytes) -> None:
    target = out / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("POOLNET_BASE_URL", "https://poolnet.online"))
    parser.add_argument("--out", default=str(ROOT / ".lists"))
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    proxy_manifest = json.loads(fetch("/pool/manifest.json", args.base))
    proxy_files = [safe_name(str(item["name"])) for item in proxy_manifest.get("files", [])]
    for name in proxy_files:
        write(out, f"pool/{name}", fetch(f"/pool/{name}", args.base))
    write(out, "pool/manifest.json", json.dumps(proxy_manifest, ensure_ascii=False, indent=2).encode())
    proxy_count = proxy_manifest.get("count")
    write(
        out,
        "pool/badges/alive.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "label": "proxies",
                "message": str(proxy_count if proxy_count is not None else "?"),
                "color": "brightgreen",
            }
        ).encode(),
    )
    for extra in ("meta.json", "stats.json", "benchmark.json", "history.json"):
        try:
            write(out, f"pool/{extra}", fetch(f"/pool/{extra}", args.base))
        except RuntimeError as exc:
            print(f"warning: {exc}", file=sys.stderr)

    vpn_manifest = json.loads(fetch("/vpn/manifest.json", args.base))
    vpn_files = [safe_name(str(item["name"])) for item in vpn_manifest.get("payloads", [])]
    for name in vpn_files:
        write(out, f"vpn/{name}", fetch(f"/vpn/{name}", args.base))
    write(out, "vpn/manifest.json", json.dumps(vpn_manifest, ensure_ascii=False, indent=2).encode())
    nodes = max(
        (int(item.get("nodes") or 0) for item in vpn_manifest.get("payloads", []) if isinstance(item, dict)),
        default=0,
    )
    write(
        out,
        "vpn/badges/verified.json",
        json.dumps(
            {"schemaVersion": 1, "label": "VPN nodes", "message": str(nodes), "color": "blue"}
        ).encode(),
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    repo = os.environ.get("GITHUB_REPOSITORY", "evgen1yby-glitch/poolnet")
    raw = f"https://raw.githubusercontent.com/{repo}/lists"
    readme = f"""# PoolNet — автообновляемые списки

Снимок: **{now}**. Данные проверены реальными соединениями на
[poolnet.online](https://poolnet.online); это не оператор узлов и не гарантия
безопасности. Узлы сторонние, трафик идёт напрямую клиент → узел.

## Прокси

- [Все прокси]({raw}/pool/all.txt)
- [HTTP]({raw}/pool/http.txt) · [SOCKS5]({raw}/pool/socks5.txt) · [SOCKS4]({raw}/pool/socks4.txt)
- [Метаданные JSON]({raw}/pool/proxies.json) · [Статистика]({raw}/pool/stats.json)
- Записей в снимке: **{proxy_manifest.get("count", "?")}**

## VPN

- [sing-box / Hiddify / Happ (base64)]({raw}/vpn/verified-sing-box.base64)
- [Xray / v2rayNG (base64)]({raw}/vpn/verified-xray.base64)
- [sing-box JSON]({raw}/vpn/verified-sing-box.singbox)
- [Clash / mihomo]({raw}/vpn/verified-sing-box.clash)
- Манифест: [vpn/manifest.json]({raw}/vpn/manifest.json)

Импортируйте ссылку в клиенте как подписку. Для личного ключа на 7 дней:
[poolnet.online/free](https://poolnet.online/free).

## Лицензии

Код и данные — по лицензиям из основного репозитория: `hub/` AGPL-3.0,
`pool/` MIT. Списки узлов предоставляются как есть, без SLA и гарантий.
"""
    write(out, "README.md", readme.encode())
    write(out, ".nojekyll", b"")
    write(
        out,
        "last-updated.json",
        json.dumps(
            {"at": now, "proxy_count": proxy_manifest.get("count"), "vpn_payloads": len(vpn_files)},
            ensure_ascii=False,
            indent=2,
        ).encode(),
    )
    print(f"lists: {len(proxy_files)} proxy files, {len(vpn_files)} VPN payloads -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
