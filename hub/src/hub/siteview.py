"""Server-side rendering for the public site.

The pages in `web/site` were static snapshots: every number was copied from one
run and went stale on the next cycle. This module renders the same files from
live published data without a template language. Pages stay valid standalone
HTML — tokens carry a static fallback and repeated blocks comment the old rows.

No dependencies beyond the standard library, and no exceptions on malformed
data: a missing number degrades to the page's own copy, an unknown token to an
em dash. `render()` caches per page by the file's mtime and the data version.
"""

from __future__ import annotations

import html
import math
import re
from pathlib import Path
from typing import Any, Callable

#: A token is `{{dotted.path}}` or `{{dotted.path|fallback copy}}`.
_TOKEN = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")

#: Blocks are HTML comments so the page remains valid when opened from disk.
_BLOCK = re.compile(r"<!--begin:([\w:.-]+)-->(.*?)<!--end:\1-->", re.S)

_MISSING = object()
_FUNNEL_STAGES = {
    "raw": ("ИСТОЧНИКИ", "адресов из 189 публичных источников"),
    "parsed": ("РАЗБОР", "записей распознаны по протоколу и адресу"),
    "tcp": ("TCP", "соединений установлено успешно"),
    "tls": ("TLS", "рукопожатий TLS завершено"),
    "config": ("КОНФИГ", "рабочих конфигураций VPN создано"),
    "http": ("HTTP", "HTTP-запросов выполнены через цепочку полностью"),
}
_FUNNEL_KEYS = tuple(_FUNNEL_STAGES)
_FUNNEL_STAGES_EN = {
    "raw": ("SOURCES", "addresses from public sources"),
    "parsed": ("PARSED", "entries recognised by protocol and address"),
    "tcp": ("TCP", "connections established"),
    "tls": ("TLS", "TLS handshakes completed"),
    "config": ("CONFIG", "working VPN configurations built"),
    "http": ("HTTP", "requests completed through the whole chain"),
}
_BLOCK_KEYS = {
    "rows:proxy": "proxy_rows", "rows:sources": "source_rows",
    "rows:protocols": "vpn.protocols", "map:dots": "map_dots",
    "rows:console": "country_rows", "rows:countries": "country_rows",
}


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _lookup(data: dict, path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not part or not isinstance(current, dict):
            return _MISSING
        current = current.get(part, _MISSING)
        if current is _MISSING:
            return _MISSING
    return current


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def _format(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return f"{value:,}".replace(",", " ")
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return "0" if text in ("", "-0") else text
    if isinstance(value, str):
        return value or None
    return None


def _plain(value: Any) -> str:
    text = _format(value)
    return "—" if text is None else text


def _text(value: Any) -> str:
    return _esc(_plain(value))


def _coord(value: Any) -> str:
    number = _as_number(value)
    return "0.00" if number is None else f"{number:.2f}"


def _render_tokens(text: str, data: dict) -> str:
    def replace(match: re.Match[str]) -> str:
        path, separator, fallback = match.group(1).partition("|")
        value = _lookup(data, path.strip())
        formatted = None if value is _MISSING else _format(value)
        if formatted is None:
            return _esc(fallback.strip()) if separator else "—"
        return _esc(formatted)
    text = _TOKEN.sub(replace, text)
    if "{{" in text:
        text = text.replace("{{", "—")
    return text


def _rows_proxy(rows: list, _inner: str) -> str:
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rank = _text(row.get("rank"))
        address = _text(row.get("address"))
        protocol = _esc(_plain(row.get("protocol")).upper())
        grade = _plain(row.get("grade"))
        grade_class = _esc("g-" + grade.lower()) if grade != "—" else "g-unknown"
        latency = _text(row.get("latency_ms"))
        uptime_text = _format(row.get("uptime_7d"))
        uptime = _esc(uptime_text) if uptime_text is not None else "—"
        uptime_width = _esc(uptime_text if uptime_text is not None else "0")
        country = _text(row.get("country"))
        out.append(
            f'<tr><td class="pa">{rank}</td>'
            f'<td class="addr">{address}</td>'
            f'<td><span class="pb">{protocol}</span></td>'
            f'<td><span class="pb {grade_class}">{_esc(grade)}</span></td>'
            f'<td class="num">{latency} ms</td>'
            f'<td class="up"><span class="upb"><i style="width:{uptime_width}%"></i></span>'
            f"{uptime}%</td>"
            f'<td class="num"><span class="ccx" data-cc="{country}">{country}</span></td></tr>'
        )
    return "".join(out)


def _rows_sources(rows: list, _inner: str) -> str:
    out: list[str] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        source = _text(row.get("id"))
        live_rate = _esc(_plain(row.get("live_rate")))
        candidates = _text(row.get("candidates"))
        alive = _text(row.get("alive"))
        median = _text(row.get("median_ms"))
        elite_rate = _esc(_plain(row.get("elite_rate")))
        published = _text(row.get("published"))
        out.append(
            f'<tr><td class="pa">{index}</td>'
            f'<td class="addr">{source}</td>'
            f'<td class="num">{live_rate}%</td>'
            f'<td class="num">{candidates} / {alive}</td>'
            f'<td class="num">{median} ms</td>'
            f'<td class="num">{elite_rate}%</td>'
            f'<td><span class="pb">{published}</span></td>'
            f'<td class="pa">—</td></tr>'
        )
    return "".join(out)


def _rows_protocols(rows: list, _inner: str) -> str:
    clean = [row for row in rows if isinstance(row, dict)]
    numbers = [_as_number(row.get("n")) for row in clean]
    peak = max((number or 0.0 for number in numbers), default=0.0)
    out: list[str] = []
    for row, number in zip(clean, numbers):
        name = _text(row.get("name"))
        value = _text(row.get("n"))
        percent = min(100.0, 100.0 * number / peak) if number and peak else 0.0
        width = f"{percent:.1f}".rstrip("0").rstrip(".") or "0"
        out.append(
            f'<div class="frow"><span class="fn"></span>'
            f'<span class="fl">{name}</span>'
            f'<span class="fb"><i style="width:{width}%"></i></span>'
            f'<span class="fv">{value}</span></div>'
        )
    return "".join(out)


def _rows_funnel(items: list, inner: str, lang: str = "ru") -> str:
    raw = _as_number(next((value for key, value in items if key == "raw"), None))
    cards = 'class="fcard' in inner
    stages = _FUNNEL_STAGES_EN if lang == "en" else _FUNNEL_STAGES
    out: list[str] = []
    for index, (key, value) in enumerate(items, start=1):
        label, description = stages.get(key, (key.upper(), ""))
        number = _as_number(value)
        if number is None or raw is None or raw <= 0:
            percent = 0.0
        else:
            percent = max(0.0, min(100.0, 100.0 * number / raw))
        if cards:
            final = " fr-final" if index == len(items) else ""
            title = ("END-TO-END REQUEST" if lang == "en" else "СКВОЗНОЙ ЗАПРОС") if key == "http" else label
            out.append(
                f'<div class="fcard{final}"><div class="fk">{index:02d} · {_esc(title)}</div>'
                f'<div class="fv">{_text(value)}</div>'
                f'<div class="fd">{_esc(description)}</div></div>'
            )
            continue
        width = _esc("100" if percent >= 100 else str(percent))
        out.append(
            f'<div class="frow"><span class="fn">{index:02d}</span>'
            f'<span class="fl">{_esc(label)}</span>'
            f'<span class="fb"><i style="width:{width}%"></i></span>'
            f'<span class="fv">{_text(value)}</span></div>'
        )
    return "".join(out)


def _flag_emoji(cc: str) -> str:
    """Regional-indicator pair for a country code; empty for anything else."""
    if not re.fullmatch(r"[A-Z]{2}", cc):
        return ""
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in cc)


def _rows_console(rows: list, _inner: str) -> str:
    out: list[str] = []
    for row in rows[:6]:
        if not isinstance(row, dict):
            continue
        cc = _plain(row.get("cc"))
        width = _esc(_coord(row.get("width")))
        out.append(
            f'<div class="crow"><span class="cc" data-cc="{cc}">{cc}</span>'
            f'<span class="cb"><i style="width:{width}%"></i></span>'
            f'<span class="cn">{_text(row.get("n"))}</span></div>'
        )
    return "".join(out)


def _rows_countries(rows: list, _inner: str) -> str:
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cc = _plain(row.get("cc"))
        out.append(
            f'<span class="cflag" data-cc="{cc}"><b>{_text(row.get("n"))}</b></span>'
        )
    return "".join(out)


def _rows_map(rows: list, _inner: str) -> str:
    dots = [row for row in rows if isinstance(row, dict)]
    out: list[str] = []
    for row in dots:
        x = _esc(_coord(row.get("x")))
        y = _esc(_coord(row.get("y")))
        r = _esc(_coord(row.get("r")))
        cc = _text(row.get("cc"))
        n = _text(row.get("n"))
        halo = _as_number(row.get("halo")) or 0.0
        if halo > 0:
            out.append(
                f'<circle class="ms-halo" cx="{x}" cy="{y}" r="{_esc(_coord(halo))}"/>'
            )
        flag = _flag_emoji(cc)
        out.append(
            f'<circle class="ms-dot" style="fill:#38bdf8" cx="{x}" cy="{y}" r="{r}">'
            f"<title>{_esc(flag + ' ' if flag else '')}{cc}: {n}</title></circle>"
        )
    return "".join(out)


_BLOCK_RENDERERS: dict[str, Callable[[list, str, str], str]] = {
    "rows:proxy": lambda rows, inner, _lang: _rows_proxy(rows, inner),
    "rows:sources": lambda rows, inner, _lang: _rows_sources(rows, inner),
    "rows:protocols": lambda rows, inner, _lang: _rows_protocols(rows, inner),
    "rows:funnel": _rows_funnel,
    "map:dots": lambda rows, inner, _lang: _rows_map(rows, inner),
    "rows:console": lambda rows, inner, _lang: _rows_console(rows, inner),
    "rows:countries": lambda rows, inner, _lang: _rows_countries(rows, inner),
}


def _block_items(name: str, data: dict) -> list[Any] | None:
    if name == "rows:funnel":
        funnel = _dict(_dict(data).get("vpn")).get("funnel")
        if not isinstance(funnel, dict) or not funnel:
            return []
        return [(key, funnel.get(key)) for key in _FUNNEL_KEYS]
    key = _BLOCK_KEYS.get(name)
    if key is None:
        return None
    current: Any = data
    for part in key.split("."):
        if not isinstance(current, dict):
            return []
        current = current.get(part)
    return current if isinstance(current, list) else []


def _render_blocks(text: str, data: dict, lang: str = "ru") -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        renderer = _BLOCK_RENDERERS.get(name)
        if renderer is None:
            return match.group(0)
        items = _block_items(name, data)
        if not items:
            return match.group(2)
        return renderer(items, match.group(2), lang)

    return _BLOCK.sub(replace, text)


class SiteRenderer:
    """Render one site page against a data snapshot, with a small cache.

    `render()` is safe from concurrent handlers: the cache is a plain dict and
    per-key assignment is atomic under CPython. A concurrent miss may render
    twice; both results are identical for the same file and version.
    """

    def __init__(self, site_dir: Path) -> None:
        self.site_dir = Path(site_dir)
        self._cache: dict[str, tuple[tuple[int, str], str]] = {}

    def render(self, name: str, data: dict, version: str) -> str | None:
        path = self.site_dir / name
        try:
            stat = path.stat()
        except OSError:
            self._cache.pop(name, None)
            return None
        key = (stat.st_mtime_ns, str(version))
        cached = self._cache.get(name)
        if cached is not None and cached[0] == key:
            return cached[1]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        lang = "en" if name.startswith("en/") else "ru"
        rendered = _render_tokens(_render_blocks(text, _dict(data), lang), _dict(data))
        self._cache[name] = (key, rendered)
        return rendered
