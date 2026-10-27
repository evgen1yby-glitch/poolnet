#!/usr/bin/env python3
"""Build the public HLS TV catalog from public playlists.

The output is a static JSON document consumed by /tv. The checker is
deliberately independent from the proxy pipeline: it only reads public
playlists, never hosts or proxies video, and stores no credentials. A stream is
published only after its master playlist, media playlist and first media
segment all answer over HTTP(S).

Usage:
    python3 scripts/hls_tv_checker.py --output web/site/tv/channels.json
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API = "https://iptv-org.github.io/api"
UA = "PoolNet-HLS-TV/1.0 (+https://poolnet.online/tv)"
ALLOWED_COUNTRIES = ("RU", "BY", "KZ")
COUNTRY_ORDER = {"RU": 0, "BY": 1, "KZ": 2}
COUNTRY_NAMES = {"RU": "Россия", "BY": "Беларусь", "KZ": "Казахстан"}
CATEGORY_NAMES = {
    "general": "Общие", "news": "Новости", "movies": "Кино", "series": "Сериалы",
    "sports": "Спорт", "music": "Музыка", "kids": "Детям", "animation": "Детям",
    "documentary": "Документальные", "entertainment": "Развлекательные", "comedy": "Юмор",
    "culture": "Культура", "science": "Наука", "education": "Образование",
    "lifestyle": "Образ жизни", "auto": "Авто", "travel": "Путешествия",
    "outdoor": "Путешествия", "cooking": "Кулинария", "business": "Бизнес",
    "shopping": "Магазины", "shop": "Магазины", "religious": "Религия", "family": "Семья",
    "weather": "Погода", "legislative": "Политика", "classic": "Кино",
    "regional": "Региональные", "other": "Прочее",
}
CATEGORY_ORDER = (
    "Общие", "Новости", "Кино", "Сериалы", "Развлекательные", "Спорт", "Музыка",
    "Детям", "Документальные", "Наука", "Познавательные", "Культура", "Религия",
    "Образ жизни", "Авто", "Путешествия", "Кулинария", "Бизнес", "Магазины",
    "Семья", "Погода", "Политика", "Образование", "Юмор", "Региональные", "Прочее",
)
CATEGORY_ALIASES = {
    "общие": "Общие", "основные": "Общие", "популярные": "Общие", "россия": "Общие",
    "russia": "Общие", "беларусь": "Общие", "belarus": "Общие", "undefined": "Прочее",
    "региональные": "Региональные", "основные региональные": "Региональные",
    "популярные региональные": "Региональные", "regional": "Региональные",
    "кино": "Кино", "кино и сериалы": "Кино", "кинозалы": "Кино", "классика": "Кино",
    "кинозалы kinowalk": "Кино", "кинозалы catcast": "Кино", "кинозалы смотрим": "Кино",
    "movies": "Кино", "film": "Кино", "сериалы": "Сериалы", "series": "Сериалы",
    "развлечения": "Развлекательные", "развлекательные": "Развлекательные",
    "entertainment": "Развлекательные", "комедии": "Юмор", "comedy": "Юмор",
    "новости": "Новости", "информационные": "Новости", "news": "Новости",
    "спорт": "Спорт", "спортивные": "Спорт", "sports": "Спорт",
    "детям": "Детям", "детские": "Детям", "kids": "Детям", "анимация": "Детям",
    "animation": "Детям", "музыка": "Музыка", "music": "Музыка",
    "документальное": "Документальные", "документальные": "Документальные",
    "documentary": "Документальные", "познавательные": "Документальные",
    "наука": "Наука", "science": "Наука", "культура": "Культура", "culture": "Культура",
    "религиозные": "Религия", "религия": "Религия", "religious": "Религия",
    "образ жизни": "Образ жизни", "lifestyle": "Образ жизни", "авто": "Авто", "auto": "Авто",
    "путешествия": "Путешествия", "travel": "Путешествия", "outdoor": "Путешествия",
    "кулинария": "Кулинария", "cooking": "Кулинария", "бизнес": "Бизнес", "business": "Бизнес",
    "магазины": "Магазины", "shop": "Магазины", "shopping": "Магазины", "семья": "Семья",
    "family": "Семья", "погода": "Погода", "weather": "Погода", "политика": "Политика",
    "legislative": "Политика", "образование": "Образование", "education": "Образование",
}
REGIONAL_TOKENS = (
    "омск", "геленджик", "башкортостан", "гомель", "брянск", "братск", "уфа", "грозный",
    "лен тв", "липецк", "муром", "осетия", "челябинск", "первоуральск", "ростов", "тульск",
    "рифей", "забайкал", "тверской", "черемхов", "тюмен", "якут", "абакан", "арис", "бст",
    "12 канал", "gln 24", "vitebsk", "алмазный край", "барс", "отс", "тст", "эхо тв",
)
NAME_CATEGORY = {
    "первый канал": "Общие", "тв центр": "Общие", "звезда": "Общие", "спас": "Религия",
    "tv rain": "Новости", "квн tv": "Юмор", "tvoye tv yumor": "Юмор", "kinokomedija": "Юмор",
    "dacha": "Образ жизни", "первый вегетарианский": "Образ жизни", "dushevnoe": "Общие",
    "наш дом": "Общие", "новое телевидение": "Общие", "terra": "Общие",
    "kvn tv": "Юмор", "viju comedy": "Юмор", "gagsnetwork": "Юмор", "komedia": "Юмор", "prima": "Общие",
}


def refine_category(name: str, category: str) -> str:
    key = clean_name(name)
    if key in NAME_CATEGORY:
        return NAME_CATEGORY[key]
    if any(token in key for token in REGIONAL_TOKENS):
        return "Региональные"
    if any(token in key for token in ("nauka", "наука", "science", "науч")):
        return "Наука"
    if any(token in key for token in ("documentary", "документ", "discovery", "history", "история")):
        return "Документальные"
    return category


def category_of(value: str) -> str:
    key = " ".join(str(value or "").lower().replace("ё", "е").split())
    if not key:
        return "Прочее"
    if key in CATEGORY_NAMES:
        return CATEGORY_NAMES[key]
    if key in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[key]
    for needle, name in CATEGORY_ALIASES.items():
        if needle in key:
            return name
    return "Прочее"

ADULT_WORDS = re.compile(r"\b(?:xxx|adult|porn|erotic|эрот|18\+|sex)\b", re.I)
QUALITY_WORDS = re.compile(
    r"\b(?:fullhd|full\s*hd|uhd|4k|2160p|1440p|1080p|1080i|720p|720i|576p|576i|480p|480i|360p|hd|sd)\b",
    re.I,
)
RESERVE_WORDS = re.compile(r"\b(?:резерв|reserve|backup|зеркало|mirror|alt)\b", re.I)
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
M3U_HEADER = re.compile(r"^#EXTM3U", re.I)
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
QUALITY_HEIGHT = {
    "2160p": 2160, "1440p": 1440, "1080p": 1080, "1080i": 1080,
    "720p": 720, "720i": 720, "576p": 576, "576i": 576,
    "480p": 480, "480i": 480, "360p": 360,
}

M3U_SOURCES = (
    {"id": "iptv-org-rus", "url": "https://iptv-org.github.io/iptv/languages/rus.m3u", "country": None},
    {"id": "iptv-org-ru", "url": "https://iptv-org.github.io/iptv/countries/ru.m3u", "country": "RU"},
    {"id": "iptv-org-by", "url": "https://iptv-org.github.io/iptv/countries/by.m3u", "country": "BY"},
    {"id": "iptv-org-kz", "url": "https://iptv-org.github.io/iptv/countries/kz.m3u", "country": "KZ"},
    {"id": "free-tv-russia", "url": "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_russia.m3u8", "country": "RU"},
    {"id": "free-tv-belarus", "url": "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_belarus.m3u8", "country": "BY"},
    {"id": "free-tv-kazakhstan", "url": "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_kazakhstan.m3u8", "country": "KZ"},
    {"id": "ngrch-ru", "url": "https://raw.githubusercontent.com/ngrch/iptv/main/ru.m3u", "country": "RU"},
    {"id": "maxviazov-ru", "url": "https://raw.githubusercontent.com/maxviazov/aptv-playlists/main/rus.m3u", "country": "RU"},
    {"id": "smolnp-ru", "url": "https://smolnp.github.io/IPTVru/IPTVru.m3u", "country": "RU"},
    {"id": "ntvampire-ru", "url": "https://raw.githubusercontent.com/ntvampire/IPTV/main/index.m3u", "country": "RU"},
    {"id": "utmax-kzrus", "url": "https://utmax.github.io/KazRusIPTV/KazRusIPTV.m3u8", "country": "KZ"},
    {"id": "naggdd-ru", "url": "https://raw.githubusercontent.com/naggdd/iptv/main/ru.m3u", "country": "RU"},
)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def fetch(url: str, timeout: float, max_bytes: int = 2_000_000, headers: dict | None = None) -> tuple[int, dict, bytes, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/vnd.apple.mpegurl, application/json, text/plain, */*",
            "Accept-Encoding": "identity",
            **(headers or {}),
        },
    )
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
            data = response.read(max_bytes)
            return response.status, dict(response.headers), data, response.geturl()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), b"", url
    except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as exc:
        return 0, {"x-error": str(exc)[:120]}, b"", url


def fetch_json(url: str, timeout: float) -> Any:
    status, _, body, _ = fetch(url, timeout, max_bytes=40_000_000)
    if status != 200:
        raise RuntimeError(f"{url}: HTTP {status}")
    return json.loads(body.decode("utf-8-sig"))


def parse_m3u(text: str, source: dict) -> list[dict]:
    items: list[dict] = []
    meta: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTINF"):
            attrs = {key.lower(): value for key, value in ATTR.findall(line)}
            matches = list(ATTR.finditer(line))
            start = matches[-1].end() if matches else line.find(":") + 1
            comma = line.find(",", start)
            name = line[comma + 1 :].strip() if comma >= 0 else attrs.get("tvg-name", "")
            meta = {
                "name": display_name(name),
                "tvg_id": attrs.get("tvg-id", ""),
                "country": (attrs.get("tvg-country") or attrs.get("tvg-country-code") or source.get("country") or "").upper(),
                "logo": attrs.get("tvg-logo", ""),
                "group": attrs.get("group-title", ""),
                "source": source["id"],
            }
        elif line.startswith("#"):
            continue
        elif meta is not None:
            if line.lower().startswith(("http://", "https://")):
                items.append({**meta, "url": line})
            meta = None
    return items


JUNK_NAME = re.compile(
    r"(?:like\s+Gecko\)|AppleWebKit/|Chrome/\d|Safari/\d|Mozilla/|http-user-agent=)",
    re.I,
)
QUALITY_SUFFIX = re.compile(
    r"\s*[\(\[]\s*(?:\d{3,4}[pi]|fullhd|uhd|4k|hd|sd|not\s*24/7|24/7)\s*[\)\]]",
    re.I,
)
COUNTRY_SUFFIX = re.compile(r"\s*\((?:Ukraine|Russia|Belarus|Kazakhstan|Moldova|Georgia|Armenia|Azerbaijan)\)\s*$", re.I)


def display_name(name: str) -> str:
    text = html.unescape(str(name or "")).replace("\ufeff", "").strip()
    text = re.sub(r"^.*?(?:Safari/\d+(?:\.\d+)*|group-title=\"[^\"]*\")\s*,?\s*", "", text, flags=re.I)
    text = re.sub(r"^.*?group-title=\"[^\"]*\"\s*,?\s*", "", text, flags=re.I)
    text = QUALITY_SUFFIX.sub("", text)
    text = COUNTRY_SUFFIX.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" -—|,")
    return text or "Без названия"


def clean_name(name: str) -> str:
    name = display_name(name)
    text = name.strip().lower().replace("ё", "е")
    text = QUALITY_WORDS.sub(" ", text)
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)
    text = re.sub(r"[^a-zа-я0-9]+", " ", text)
    return " ".join(text.split())


def base_name(name: str) -> str:
    text = RESERVE_WORDS.sub(" ", name)
    text = re.sub(r"\s+", " ", text).strip(" -—|")
    return text or name.strip()


def quality_from_text(text: str) -> str:
    match = QUALITY_WORDS.search(text or "")
    return match.group(0).lower() if match else ""


def logo_ok(url: str, timeout: float) -> str:
    """Return a usable absolute logo URL, or an empty string.

    A dead or HTML-hotlink logo is worse than a clean channel monogram: the
    card falls back to initials when this returns empty.
    """
    if not url.lower().startswith("https://"):
        return ""
    status, headers, body, final_url = fetch(url, timeout, max_bytes=80_000)
    if status != 200 or len(body) < 64:
        return ""
    content_type = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
    if "image/" not in content_type and not body.lstrip().startswith(b"<svg"):
        return ""
    head = body[:64]
    image = head.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF87a", b"GIF89a"))
    image = image or head.startswith(b"RIFF") and body[8:12] == b"WEBP"
    image = image or head.lstrip().startswith((b"<svg", b"<?xml"))
    return final_url if image else ""


def quality_from_height(height: int | None) -> str:
    if not height:
        return ""
    for label, value in QUALITY_HEIGHT.items():
        if height >= value:
            return label
    return f"{height}p"


def normalize_url(url: str) -> str:
    return url.strip().replace("&amp;", "&")


def channel_key(channel: dict) -> str:
    tvg_id = (channel.get("tvg_id") or "").split("@", 1)[0].strip().lower()
    if tvg_id:
        return f"id:{tvg_id}"
    country = (channel.get("country") or "").upper()
    return f"name:{country}:{clean_name(base_name(channel.get('name', '')))}"


def parse_master(text: str) -> list[dict]:
    variants: list[dict] = []
    pending: dict | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = {key.lower(): value for key, value in ATTR.findall(line)}
            pending = {
                "bandwidth": int(attrs.get("bandwidth") or 0),
                "resolution": attrs.get("resolution", ""),
                "codecs": attrs.get("codecs", ""),
            }
        elif not line.startswith("#") and pending is not None:
            variants.append({**pending, "url": line})
            pending = None
    return variants


def parse_media(text: str) -> tuple[list[str], bool]:
    segments: list[str] = []
    endlist = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line == "#EXT-X-ENDLIST":
            endlist = True
        elif not line.startswith("#"):
            segments.append(line)
    return segments, endlist


def cors_ok(headers: dict) -> bool:
    value = (headers.get("Access-Control-Allow-Origin") or headers.get("access-control-allow-origin") or "").strip()
    return value == "*" or value.startswith("https://poolnet.online")


def resolve(base: str, child: str) -> str:
    return urllib.parse.urljoin(base, child)


def probe_hls(url: str, timeout: float) -> dict | None:
    started = time.monotonic()
    status, headers, body, final_url = fetch(url, timeout, max_bytes=1_500_000)
    if status != 200 or not body.lstrip().startswith(b"#EXTM3U"):
        return None
    text = body.decode("utf-8-sig", "replace")
    manifest_cors = cors_ok(headers)
    master = parse_master(text)
    candidates = master[:4]
    if not candidates:
        candidates = [{"url": final_url, "bandwidth": 0, "resolution": "", "codecs": ""}]
    else:
        candidates.sort(key=lambda item: (item.get("bandwidth") or 0, item.get("resolution") or ""), reverse=True)
    for variant in candidates:
        playlist_url = resolve(final_url, variant["url"]) if variant["url"] != final_url else final_url
        if playlist_url != final_url:
            status2, headers2, body2, playlist_url = fetch(playlist_url, timeout, max_bytes=1_200_000)
            if status2 != 200 or not body2.lstrip().startswith(b"#EXTM3U"):
                continue
            text2 = body2.decode("utf-8-sig", "replace")
            variant_cors = cors_ok(headers2)
        else:
            body2, text2 = body, text
            variant_cors = manifest_cors
        segments, endlist = parse_media(text2)
        if not segments:
            continue
        segment_url = resolve(playlist_url, segments[-1])
        status3, headers3, segment, _ = fetch(segment_url, timeout, max_bytes=8192, headers={"Range": "bytes=0-8191"})
        if status3 not in (200, 206) or not segment:
            continue
        content_type = (headers3.get("Content-Type") or headers3.get("content-type") or "").lower()
        if "text/html" in content_type or segment.lstrip().startswith((b"<!doctype", b"<html")):
            continue
        looks_media = segment[0] == 0x47 or b"ftyp" in segment[:64] or b"moof" in segment[:128] or b"styp" in segment[:64]
        if not looks_media:
            continue
        resolution = variant.get("resolution") or ""
        height = 0
        match = re.search(r"x(\d+)", resolution)
        if match:
            height = int(match.group(1))
        quality = quality_from_height(height)
        https = playlist_url.lower().startswith("https://")
        return {
            "url": playlist_url,
            "quality": quality,
            "height": height,
            "bandwidth": variant.get("bandwidth") or 0,
            "codecs": variant.get("codecs") or "",
            "latency_ms": round((time.monotonic() - started) * 1000),
            "live": not endlist,
            "web_playable": bool(https and manifest_cors and variant_cors and cors_ok(headers3)),
            "https": https,
            "segment_type": content_type or "unknown",
        }
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="web/site/tv/channels.json")
    parser.add_argument("--timeout", type=float, default=9.0)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--max-variants", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    started = time.monotonic()
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)

    log("fetching iptv-org metadata")
    channels = fetch_json(f"{API}/channels.json", 45)
    streams = fetch_json(f"{API}/streams.json", 45)
    feeds = fetch_json(f"{API}/feeds.json", 45)
    logos = fetch_json(f"{API}/logos.json", 45)
    countries = {item["code"]: item for item in fetch_json(f"{API}/countries.json", 30)}
    categories = {item["id"]: item["name"] for item in fetch_json(f"{API}/categories.json", 30)}

    channels_by_id = {item["id"]: item for item in channels}
    languages_by_channel: dict[str, set[str]] = defaultdict(set)
    for feed in feeds:
        if feed.get("channel") and feed.get("languages"):
            languages_by_channel[feed["channel"]].update(feed["languages"])
    logo_by_channel: dict[str, str] = {}
    for logo in logos:
        channel_id = logo.get("channel")
        if channel_id and logo.get("url") and channel_id not in logo_by_channel:
            logo_by_channel[channel_id] = logo["url"]
    stream_by_channel: dict[str, list[dict]] = defaultdict(list)
    for stream in streams:
        if stream.get("channel") in channels_by_id:
            stream_by_channel[stream["channel"]].append(stream)

    # M3U playlists add fallback URLs and curated channels. The language list
    # supplies the Russian-language channel IDs even where feeds are sparse.
    m3u_items: list[dict] = []
    source_stats: dict[str, dict] = {}
    for source in M3U_SOURCES:
        status, _, body, _ = fetch(source["url"], 35, max_bytes=20_000_000)
        if status != 200:
            source_stats[source["id"]] = {"ok": False, "items": 0, "error": f"HTTP {status}"}
            log(f"  {source['id']}: HTTP {status}")
            continue
        items = parse_m3u(body.decode("utf-8-sig", "replace"), source)
        source_stats[source["id"]] = {"ok": True, "items": len(items)}
        m3u_items.extend(items)
        log(f"  {source['id']}: {len(items)}")

    russian_ids = {
        item["tvg_id"].split("@", 1)[0].lower()
        for item in m3u_items
        if item.get("tvg_id") and item.get("source") == "iptv-org-rus"
    }

    merged: dict[str, dict] = {}
    for channel_id, channel in channels_by_id.items():
        country = (channel.get("country") or "").upper()
        if country not in ALLOWED_COUNTRIES or channel.get("is_nsfw"):
            continue
        languages = languages_by_channel.get(channel_id, set())
        names = [channel.get("name", ""), *(channel.get("alt_names") or [])]
        russian_name = any(CYRILLIC.search(name or "") for name in names)
        russian = "rus" in languages or channel_id in russian_ids or (country == "RU")
        if not russian:
            continue
        if country in ("BY", "KZ") and not russian_name and "rus" not in languages:
            continue
        key = f"id:{channel_id.lower()}"
        merged[key] = {
            "id": channel_id,
            "name": display_name(channel.get("name") or channel_id),
            "country": country,
            "country_name": COUNTRY_NAMES.get(country, country),
            "languages": sorted(languages),
            "categories": channel.get("categories") or [],
            "category": category_of((channel.get("categories") or ["general"])[0]),
            "logo": logo_by_channel.get(channel_id, ""),
            "tvg_id": channel_id,
            "sources": {"iptv-org"},
            "variants": [],
        }

    def add_variant(channel: dict, url: str, source: str, quality: str = "") -> None:
        url = normalize_url(url)
        if not url.startswith(("http://", "https://")):
            return
        if any(item["url"] == url for item in channel["variants"]):
            return
        channel["variants"].append({"url": url, "source": source, "quality": quality})
        channel["sources"].add(source)

    for channel_id, items in stream_by_channel.items():
        key = f"id:{channel_id.lower()}"
        channel = merged.get(key)
        if not channel:
            continue
        for item in items:
            add_variant(channel, item.get("url", ""), "iptv-org", item.get("quality") or "")

    for item in m3u_items:
        country = (item.get("country") or "").upper()
        if country not in ALLOWED_COUNTRIES:
            continue
        if ADULT_WORDS.search(item.get("name", "")) or ADULT_WORDS.search(item.get("group", "")):
            continue
        tvg_id = (item.get("tvg_id") or "").split("@", 1)[0].strip()
        key = f"id:{tvg_id.lower()}" if tvg_id else ""
        channel = merged.get(key)
        if channel is None:
            russian_name = bool(CYRILLIC.search(item.get("name", "")))
            if country != "RU" and not russian_name:
                continue
            key = f"name:{country}:{clean_name(base_name(item.get('name', '')))}"
            channel = merged.get(key)
            if channel is None:
                channel = {
                    "id": key,
                    "name": display_name(base_name(item.get("name", ""))),
                    "country": country,
                    "country_name": COUNTRY_NAMES.get(country, country),
                    "languages": ["rus"] if russian_name else [],
                    "categories": [],
                    "category": category_of(item.get("group")),
                    "logo": item.get("logo") or "",
                    "tvg_id": tvg_id,
                    "sources": set(),
                    "variants": [],
                }
                merged[key] = channel
        item_category = category_of(item.get("group"))
        if item_category not in ("Общие", "Прочее") and channel.get("category") in ("Общие", "Прочее", "Документальные"):
            channel["category"] = item_category
        add_variant(channel, item.get("url", ""), item["source"], quality_from_text(item.get("name", "")))

    candidates = []
    for channel in merged.values():
        channel["sources"] = sorted(channel["sources"])
        channel["variants"] = channel["variants"][: max(1, args.max_variants)]
        if not channel["variants"]:
            continue
        channel["category"] = category_of(channel["category"])
        candidates.append(channel)
    candidates.sort(key=lambda item: (COUNTRY_ORDER.get(item["country"], 9), item["category"], item["name"].lower()))
    if args.limit:
        candidates = candidates[: args.limit]
    log(f"probing {len(candidates)} channels / {sum(len(c['variants']) for c in candidates)} streams")

    def probe_channel(channel: dict) -> dict | None:
        ranked = sorted(
            channel["variants"],
            key=lambda item: (item["url"].lower().startswith("https://"), QUALITY_HEIGHT.get(item.get("quality", ""), 0), -len(item["url"])),
            reverse=True,
        )
        live_variants = []
        for variant in ranked:
            result = probe_hls(variant["url"], args.timeout)
            if result:
                live_variants.append({**variant, **result})
        if not live_variants:
            return None
        live_variants.sort(key=lambda item: (item["https"], item["web_playable"], item["height"], -item["latency_ms"]), reverse=True)
        best = live_variants[0]
        if not best["live"]:
            return None
        quality = best["quality"] or quality_from_text(channel["name"]) or "HLS"
        logo = logo_ok(channel.get("logo") or "", args.timeout)
        return {
            **channel,
            "category": refine_category(channel["name"], channel["category"]),
            "logo": logo,
            "logo_status": "image" if logo else "monogram",
            "url": best["url"],
            "quality": quality,
            "latency_ms": best["latency_ms"],
            "live": True,
            "https": best["https"],
            "web_playable": best["web_playable"],
            "variants": live_variants,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    live: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for channel in pool.map(probe_channel, candidates):
            if channel is not None:
                live.append(channel)
                if len(live) % 25 == 0:
                    log(f"  live {len(live)}")

    # Two source lists can repeat a channel under a slightly different label or
    # point two labels at one CDN edge. Merge by canonical name first, then by
    # the best stream URL. The surviving record keeps all variants and sources.
    by_name: dict[str, dict] = {}
    for item in live:
        key = clean_name(base_name(item["name"]))
        current = by_name.get(key)
        if current is None:
            by_name[key] = item
            continue
        current["variants"].extend(item["variants"])
        current["sources"] = sorted(set(current["sources"]) | set(item["sources"]))
        if item["category"] not in ("Общие", "Прочее") and current["category"] in ("Общие", "Прочее", "Документальные"):
            current["category"] = item["category"]
        if not current.get("logo") and item.get("logo"):
            current["logo"] = item["logo"]
            current["logo_status"] = item.get("logo_status", "image")
        if len(item["name"]) < len(current["name"]):
            current["name"] = item["name"]

    by_url: dict[str, dict] = {}
    for item in by_name.values():
        current = by_url.get(item["url"])
        if current is None:
            by_url[item["url"]] = item
            continue
        current["sources"] = sorted(set(current["sources"]) | set(item["sources"]))
        if not current.get("logo") and item.get("logo"):
            current["logo"] = item["logo"]
        if not current.get("quality") and item.get("quality"):
            current["quality"] = item["quality"]
    live = list(by_url.values())
    category_rank = {name: index for index, name in enumerate(CATEGORY_ORDER)}
    live.sort(key=lambda item: (category_rank.get(item["category"], 999), item["name"].lower()))
    by_country = Counter(item["country"] for item in live)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_s": round(time.monotonic() - started, 1),
        "sources": [
            {"id": "iptv-org-api", "url": API, "ok": True, "items": len(channels_by_id)},
            *[
                {"id": source["id"], "url": source["url"], **source_stats.get(source["id"], {"ok": False, "items": 0, "error": "not fetched"})}
                for source in M3U_SOURCES
            ],
        ],
        "category_order": list(CATEGORY_ORDER),
        "stats": {
            "channels": len(live),
            "web_playable": sum(1 for item in live if item["web_playable"]),
            "countries": {country: by_country.get(country, 0) for country in ALLOWED_COUNTRIES},
            "with_logo": sum(1 for item in live if item.get("logo")),
        },
        "channels": live,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    m3u = output.with_suffix(".m3u")
    lines = ["#EXTM3U", f"#PLAYLIST:PoolNet HLS TV — {len(live)} live channels"]
    for channel in live:
        variants = [item for item in channel.get("variants", []) if item.get("url")]
        if not variants:
            continue
        for index, variant in enumerate(variants):
            suffix = "" if index == 0 else f" · резерв {index + 1}"
            attrs = [
                f'tvg-id="{channel.get("tvg_id", "")}"',
                f'tvg-logo="{channel.get("logo", "")}"',
                f'group-title="{channel.get("category", "Прочее")}{" · резерв" if index else ""}"',
            ]
            lines.append(f'#EXTINF:-1 {" ".join(attrs)},{channel["name"]}{suffix}')
            lines.append(variant["url"])
    m3u.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"wrote {output} and {m3u} · {len(live)} live · {payload['stats']['web_playable']} web-playable · {payload['duration_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
