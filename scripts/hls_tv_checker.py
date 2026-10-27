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
import gzip
import html
import http.client
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import zlib
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
    "витебск": "Региональные", "гагснетворк": "Юмор", "дача": "Образ жизни",
    "дождь": "Новости", "квн тв": "Юмор", "санкт петербург": "Региональные", "терра": "Общие",
}



# Latin display names that are Russian transliterations are converted to
# Cyrillic. International brands stay Latin, because "CNN" is not "СНН".
FOREIGN_NAMES = {
    "cnn", "dw", "euronews", "bbc", "france 24", "cgtn", "al jazeera",
    "bloomberg", "cnbc", "disney xd", "foxkids", "fx", "epic drama", "hollywood",
    "fashion", "fashion tv", "national geographic", "discovery", "sony", "mtv",
    "vh1", "mezzo", "bollywood", "rt", "rt arabic", "rt balkan", "rt en espanol",
    "tv brics", "tv brics russian", "jibek joly", "ktk", "ktk 42", "uzreport tv",
    "dunyo boylab", "dunyo bo'ylab", "o'zbekiston", "armenia tv satellite", "tdk 42", "fashion lifestyle", "fashion&lifestyle", "channel 9", "rt documentary russian",
}
NAME_OVERRIDES = {
    "amedia 1": "Амедиа 1", "amedia 2": "Амедиа 2", "amedia hit": "Амедиа Хит",
    "amedia premium": "Амедиа Премиум", "viju tv1000": "Вижу TV1000",
    "viju tv1000 action": "Вижу TV1000 Action", "viju tv1000 novella": "Вижу TV1000 Новелла",
    "viju tv1000 romantica": "Вижу TV1000 Романтика", "viju+ megahit": "Вижу+ Мегахит",
    "viju+ premiere": "Вижу+ Премьера", "viju+ serial": "Вижу+ Сериал",
    "star cinema": "Стар Синема", "star family": "Стар Фэмили", "start air": "Старт Эйр",
    "illusion+": "Иллюзион+", "kinowalk": "Киноволк",
    "black sea tv": "Чёрное море ТВ", "big asia": "Большая Азия",
    "current time tv": "Настоящее время", "freedom": "Свобода",
    "silk way": "Шёлковый путь", "silk way cinema": "Шёлковый путь Кино",
    "amedia": "Амедиа", "viju": "Вижу", "city eden": "Сити Эден",
    "dom kino": "Дом кино", "dom kino premium": "Дом кино Премиум",
    "muzhskoe kino": "Мужское кино", "nash kinopokaz": "Наш кинопоказ",
    "nashe novoe kino": "Наше новое кино", "rodnoe kino": "Родное кино",
    "russkiy roman": "Русский роман", "indiyskoye kino": "Индийское кино",
    "ostrosyuzhetnoye": "Остросюжетное", "retro": "Ретро", "retrovision": "Ретровижн",
    "retrovision classic": "Ретровижн Классика", "retrovision movies": "Ретровижн Кино",
    "retrovision motor": "Ретровижн Мото", "kinopremyera": "Кинопремьера",
    "kinosemja": "Киносемья", "kinosvidanie": "Киносвидание", "kino hit": "Кинохит",
    "kinohit": "Кинохит", "kinomix 1": "КиноМикс 1", "kinomix 2": "КиноМикс 2",
    "tv 21": "ТВ 21", "tv 21 international": "ТВ 21 International",
    "7 tv": "7 ТВ", "a media": "Амедиа", "a media hit": "Амедиа Хит",
    "astrahan": "Астрахань", "astrahan 24": "Астрахань 24",
    "astrahan ru tv": "Астрахань.Ру ТВ", "groznyj": "Грозный",
    "nizhniy novgorod": "Нижний Новгород", "nizhniy novgorod 24": "Нижний Новгород 24",
    "sankt-peterburg": "Санкт-Петербург", "yakutsk": "Якутск",
    "yakutia": "Якутия", "yakutiya 24": "Якутия 24", "osetiya iryston": "Осетия-Ирыстон",
    "moskva 24": "Москва 24", "moskva doveriye": "Москва. Доверие",
    "pervyy gorodskoy odessa": "Первый городской. Одесса",
    "pervyy respublikanskiy": "Первый Республиканский",
    "obshchestvennoe nezavisimoe televidenie": "Общественное Независимое Телевидение",
    "vesti fm": "Вести FM", "izvestia": "Известия", "sochi24": "Сочи24",
    "tavriya": "Таврия", "tolk": "Толк", "krik-tv": "Крик-ТВ", "mir 24": "Мир 24",
    "belarus-1": "Беларусь 1", "belarus-24": "Беларусь 24",
    "tv brics russian": "ТВ БРИКС", "channel 5": "5 канал", "channel 12": "12 канал",
    "channel 8": "8 канал", "channel one": "Первый канал", "belarus-1": "Беларусь 1", "belarus 1": "Беларусь 1",
    "belarus-24": "Беларусь 24", "belarus 24": "Беларусь 24", "kino 1": "Кино 1", "kino tv": "Кино ТВ",
    "moldova 1": "Молдова 1", "moldova 2": "Молдова 2", "silk way": "Шёлковый путь",
    "silk way cinema": "Шёлковый путь Кино", "dasturxon tv": "Дастурхон ТВ",
    "channel one russia europa": "Первый канал Европа", "channel one europa": "Первый канал Европа",
    "channel 5 international": "5 канал Международный",
    "ren tv international": "РЕН ТВ Международный",
    "sts international": "СТС Международный",
    "rtr planeta europe": "РТР-Планета Европа", "rtvi us": "РТВи США",
    "ulytau": "Улытау", "tsv": "ТСВ", "tv rain": "Дождь",
    "ntv russia 1": "НТВ +1", "ntv russia 2": "НТВ +2",
    "ntv russia 4": "НТВ +4", "ntv russia 7": "НТВ +7",
    "ntv 1": "НТВ +1", "ntv 2": "НТВ +2", "ntv 4": "НТВ +4", "ntv 7": "НТВ +7",
}
TRANSLIT_WORDS = {
    "tv": "ТВ", "hd": "HD", "sd": "SD", "channel": "канал", "one": "первый",
    "kino": "кино", "cinema": "кино", "movies": "кино", "movie": "кино",
    "dom": "дом", "mir": "мир", "radio": "радио", "music": "музыка",
    "news": "новости", "sport": "спорт", "sports": "спорт", "kids": "детям",
    "family": "семья", "retro": "ретро", "classic": "классика", "premium": "премиум",
    "russia": "Россия", "rossiya": "Россия", "russian": "русский",
    "moskva": "Москва", "moscow": "Москва", "peterburg": "Петербург",
    "sankt": "Санкт", "novgorod": "Новгород", "nizhniy": "Нижний",
    "krasnodar": "Краснодар", "krasnoyarsk": "Красноярск", "novosibirsk": "Новосибирск",
    "ekaterinburg": "Екатеринбург", "chelyabinsk": "Челябинск", "omsk": "Омск",
    "tomsk": "Томск", "tyumen": "Тюмень", "surgut": "Сургут", "irkutsk": "Иркутск",
    "perm": "Пермь", "tula": "Тула", "tver": "Тверь", "yaroslavl": "Ярославль",
    "vladivostok": "Владивосток", "khabarovsk": "Хабаровск", "abakan": "Абакан",
    "stavropol": "Ставрополь", "barnaul": "Барнаул", "ufa": "Уфа", "kazan": "Казань",
    "samara": "Самара", "saratov": "Саратов", "rostov": "Ростов", "volgograd": "Волгоград",
    "belgorod": "Белгород", "groznyj": "Грозный", "grozny": "Грозный",
    "astrahan": "Астрахань", "yakutiya": "Якутия", "osetiya": "Осетия",
    "svoboda": "Свобода", "vremya": "Время", "zhivaya": "Живая", "priroda": "Природа",
    "muzhskoe": "Мужское", "semja": "Семья", "semia": "Семья", "kinopokaz": "Кинопоказ",
    "kinopremyera": "Кинопремьера", "kinosvidanie": "Киносвидание",
    "ostrosyuzhetnoye": "Остросюжетное", "indiyskoye": "Индийское",
    "russkiy": "Русский", "roman": "Роман", "rodnoe": "Родное", "nashe": "Наше",
    "novoe": "Новое", "retrovision": "Ретровижн", "kinohit": "Кинохит",
    "telekanal": "Телеканал", "oblast": "Область", "respublika": "Республика",
    "informatsionnyy": "Информационный", "informacionnyy": "Информационный",
    "sputnik": "Спутник", "zvezda": "Звезда", "pervyy": "Первый", "pervyi": "Первый",
    "kultura": "Культура", "karusel": "Карусель", "match": "Матч", "spas": "Спас",
    "otr": "ОТР", "ntv": "НТВ", "ren": "РЕН", "sts": "СТС", "tnt": "ТНТ",
}
TRANSLIT_PAIRS = (
    ("shch", "щ"), ("sch", "щ"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"),
    ("ch", "ч"), ("sh", "ш"), ("yu", "ю"), ("ya", "я"), ("yo", "ё"),
    ("ye", "е"), ("iy", "ий"), ("yy", "ый"), ("ay", "ай"), ("oy", "ой"),
    ("ey", "ей"), ("a", "а"), ("b", "б"), ("v", "в"), ("g", "г"), ("d", "д"),
    ("e", "е"), ("z", "з"), ("i", "и"), ("j", "й"), ("k", "к"), ("l", "л"),
    ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"), ("r", "р"), ("s", "с"),
    ("t", "т"), ("u", "у"), ("f", "ф"), ("h", "х"), ("c", "к"), ("q", "к"),
    ("w", "в"), ("x", "кс"), ("y", "и"),
)


def translit_word(word: str) -> str:
    lower = word.lower()
    out = []
    index = 0
    while index < len(lower):
        for source, target in TRANSLIT_PAIRS:
            if lower.startswith(source, index):
                out.append(target)
                index += len(source)
                break
        else:
            out.append(lower[index])
            index += 1
    result = "".join(out)
    if word.isupper():
        return result.upper()
    if word[:1].isupper():
        return result[:1].upper() + result[1:]
    return result


def translit_name(name: str) -> str:
    parts = re.split(r"([A-Za-z]+)", name)
    out = []
    for part in parts:
        if re.fullmatch(r"[A-Za-z]+", part or ""):
            mapped = TRANSLIT_WORDS.get(part.lower())
            if mapped and part[:1].isupper() and mapped[:1].islower():
                mapped = mapped[:1].upper() + mapped[1:]
            out.append(mapped if mapped else translit_word(part))
        else:
            out.append(part or "")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def localize_name(name: str, country: str, aliases: dict) -> str:
    cleaned = clean_name(name)
    if cleaned in NAME_OVERRIDES:
        return NAME_OVERRIDES[cleaned]
    if cleaned in aliases:
        return aliases[cleaned]
    if country not in ALLOWED_COUNTRIES or CYRILLIC.search(name):
        return name
    if cleaned in FOREIGN_NAMES or any(cleaned.startswith(item + " ") for item in FOREIGN_NAMES):
        return name
    localized = translit_name(name)
    return localized if CYRILLIC.search(localized) else name

def preferred_name(channel: dict) -> str:
    names = [channel.get("name") or ""] + list(channel.get("alt_names") or [])
    for name in names:
        if CYRILLIC.search(name or ""):
            return name
    return channel.get("name") or ""


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
BLOCKED_URL_PARTS = ("cache1.cinerama.uz", "stream8.cinerama.uz", "/blocked/")
CURATED_STREAMS = {
    "Nauka.ru": ("https://stream1.cinerama.uz/1248/index.m3u8", "curated"),
}


def blocked_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(part in lowered for part in BLOCKED_URL_PARTS)


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
            encoding = (response.headers.get("Content-Encoding") or "").lower()
            if encoding == "gzip":
                data = gzip.decompress(data)
            elif encoding == "deflate":
                data = zlib.decompress(data)
            return response.status, dict(response.headers), data, response.geturl()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), b"", url
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError, ssl.SSLError, EOFError, zlib.error) as exc:
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
    text = re.sub(r"\s*\[(?:geo-blocked|not\s*24/7|24/7)\]\s*", " ", text, flags=re.I)
    text = QUALITY_SUFFIX.sub("", text)
    text = COUNTRY_SUFFIX.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" -—|,")
    return text or "Без названия"


def clean_name(name: str) -> str:
    name = display_name(name)
    text = name.strip().lower().replace("ё", "е")
    if text == "nauka":
        text = "наука"
    elif text.startswith("nauka "):
        text = "наука " + text[6:]
    text = QUALITY_WORDS.sub(" ", text)
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)
    text = re.sub(r"[^a-zа-я0-9]+", " ", text)
    return " ".join(text.split())


def base_name(name: str) -> str:
    text = RESERVE_WORDS.sub(" ", name)
    text = re.sub(r"\s+", " ", text).strip(" -—|")
    return text or name.strip()


def codec_score(variant: dict) -> int:
    codecs = (variant.get("codecs") or "").lower()
    if any(token in codecs for token in ("avc1", "avc3", "hvc1", "hev1", "vp09", "av01")):
        return 3
    if any(token in codecs for token in ("mp2v", "mpeg2")):
        return -2
    return 0


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
    if status != 200 or blocked_url(final_url) or not body.lstrip().startswith(b"#EXTM3U"):
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
            if status2 != 200 or blocked_url(playlist_url) or not body2.lstrip().startswith(b"#EXTM3U"):
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



# HTML portals whose players expose a public HLS URL. These are crawled as
# sources, not embedded: the checker never proxies their video.
VITS_COUNTRY = {"Россия": "RU", "Беларусь": "BY", "Казахстан": "KZ"}


def _page_text(url: str, timeout: float = 25) -> str:
    status, _, body, _ = fetch(url, timeout, max_bytes=3_000_000)
    return body.decode("utf-8", "replace") if status == 200 else ""


def _vits_items() -> tuple[list[dict], dict]:
    first = _page_text("https://vits.tv/ru/tv/")
    if not first:
        return [], {"id": "vits-tv", "url": "https://vits.tv/ru/tv/", "ok": False, "items": 0, "error": "index"}
    pages = [int(number) for number in re.findall(r"/ru/tv/page/(\d+)/", first)]
    links = set(re.findall(r'href="(/ru/tv/[^"/]+/)"', first))
    for number in range(2, (max(pages) if pages else 1) + 1):
        page = _page_text(f"https://vits.tv/ru/tv/page/{number}/")
        links.update(re.findall(r'href="(/ru/tv/[^"/]+/)"', page))
    links = sorted(link for link in links if not link.startswith("/ru/tv/page/"))

    def one(path: str) -> dict | None:
        page = _page_text("https://vits.tv" + path)
        if not page:
            return None
        match = re.search(r'player-config="([^"]+)"', page)
        if not match:
            return None
        try:
            config = json.loads(html.unescape(match.group(1)))
        except (ValueError, TypeError):
            return None
        driver = config.get("driver") or {}
        source = driver.get("src") or (config.get("meta") or {}).get("stream_url") or ""
        if not source or blocked_url(source):
            return None
        country_name = ""
        country_match = re.search(r'"areaServed"\s*:\s*\{[^{}]*"name"\s*:\s*"([^"]+)"', page)
        if country_match:
            country_name = html.unescape(country_match.group(1))
        country = VITS_COUNTRY.get(country_name, "")
        if not country:
            return None
        category_match = re.search(r"Категория:\s*(?:<[^>]+>\s*)*([^<]+)", page)
        category = html.unescape(category_match.group(1)).strip() if category_match else "Общие"
        title = (config.get("title") or "").strip()
        if not title:
            return None
        return {
            "name": title,
            "tvg_id": "",
            "country": country,
            "logo": (config.get("poster") or "").strip(),
            "group": category,
            "source": "vits-tv",
            "url": source,
        }

    items = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        for item in pool.map(one, links):
            if item:
                items.append(item)
    return items, {"id": "vits-tv", "url": "https://vits.tv/ru/tv/", "ok": True, "items": len(items)}


def _rutv_items() -> tuple[list[dict], dict]:
    index = _page_text("http://rutv.pw/")
    if not index:
        return [], {"id": "rutv-pw", "url": "http://rutv.pw/", "ok": False, "items": 0, "error": "index"}
    paths = sorted(set(re.findall(r'href="(/[a-z0-9-]+)"', index)))
    paths = [path for path in paths if path not in ("/favicon.ico",)]

    def one(path: str) -> dict | None:
        page = _page_text("http://rutv.pw" + path)
        if not page:
            return None
        match = re.search(r'Playerjs\(\{id:"player", file:"([^"]+)"', page)
        if not match:
            return None
        source = html.unescape(match.group(1))
        if blocked_url(source):
            return None
        title = re.search(r"<title>(.*?)</title>", page, re.S)
        name = html.unescape(title.group(1)).split("—")[0].split("прямой")[0].strip() if title else ""
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            return None
        logo = re.search(r'src="(imgs/[^"]+)"', page)
        return {
            "name": name,
            "tvg_id": "",
            "country": "RU",
            "logo": urllib.parse.urljoin("http://rutv.pw/", html.unescape(logo.group(1))) if logo else "",
            "group": category_of(name),
            "source": "rutv-pw",
            "url": source,
        }

    items = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for item in pool.map(one, paths):
            if item:
                items.append(item)
    return items, {"id": "rutv-pw", "url": "http://rutv.pw/", "ok": True, "items": len(items)}

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
    api_aliases = {}
    for item in channels:
        if (item.get("country") or "").upper() not in ALLOWED_COUNTRIES:
            continue
        names = [item.get("name") or ""] + list(item.get("alt_names") or [])
        cyrillic = next((name for name in names if name and CYRILLIC.search(name)), "")
        if not cyrillic:
            continue
        for name in names:
            if name:
                api_aliases[clean_name(name)] = cyrillic
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

    html_items = []
    for scrape in (_vits_items, _rutv_items):
        items, stat = scrape()
        html_items.extend(items)
        source_stats[stat["id"]] = {"ok": stat.get("ok", False), "items": stat["items"], "error": stat.get("error", "")}
        log(f"  {stat['id']}: {stat['items']}")
    m3u_items.extend(html_items)

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
            "name": display_name(localize_name(preferred_name(channel) or channel_id, country, api_aliases)),
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
        if not url.startswith(("http://", "https://")) or blocked_url(url):
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
                    "name": display_name(localize_name(display_name(base_name(item.get("name", ""))), country, api_aliases)),
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
        item_name = display_name(localize_name(display_name(base_name(item.get("name", ""))), country, api_aliases))
        if item_name and not CYRILLIC.search(channel.get("name", "")) and CYRILLIC.search(item_name):
            channel["name"] = item_name
        add_variant(channel, item.get("url", ""), item["source"], quality_from_text(item.get("name", "")))

    for channel_id, (url, source) in CURATED_STREAMS.items():
        channel = merged.get(f"id:{channel_id.lower()}")
        if channel:
            add_variant(channel, url, source)

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
        live_variants.sort(
            key=lambda item: (
                item["https"],
                item["web_playable"],
                codec_score(item),
                item["height"],
                -item["latency_ms"],
            ),
            reverse=True,
        )
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
    for channel in live:
        channel["variants"] = [item for item in channel.get("variants", []) if not blocked_url(item.get("url", ""))]
        if not channel["variants"]:
            continue
        ordered = sorted(
            channel.get("variants", []),
            key=lambda item: (
                bool(item.get("https")),
                bool(item.get("web_playable")),
                codec_score(item),
                item.get("height") or 0,
                -(item.get("latency_ms") or 0),
            ),
            reverse=True,
        )
        if ordered:
            channel["variants"] = ordered
            best = ordered[0]
            channel["url"] = best["url"]
            channel["quality"] = best.get("quality") or channel.get("quality") or "HLS"
            channel["latency_ms"] = best.get("latency_ms", channel.get("latency_ms"))
            channel["web_playable"] = bool(best.get("web_playable"))
            channel["https"] = bool(best.get("https"))
    by_primary = {}
    for channel in live:
        current = by_primary.get(channel["url"])
        if current is None:
            by_primary[channel["url"]] = channel
            continue
        current["variants"].extend(channel.get("variants", []))
        current["sources"] = sorted(set(current["sources"]) | set(channel.get("sources", [])))
        if not current.get("logo") and channel.get("logo"):
            current["logo"] = channel["logo"]
            current["logo_status"] = channel.get("logo_status", "image")
    live = list(by_primary.values())
    category_rank = {name: index for index, name in enumerate(CATEGORY_ORDER)}
    live.sort(key=lambda item: (category_rank.get(item["category"], 999), item["name"].lower()))
    by_country = Counter(item["country"] for item in live)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_s": round(time.monotonic() - started, 1),
        "sources": [
            {"id": "iptv-org-api", "url": API, "ok": True, "items": len(channels_by_id)},
            {"id": "vits-tv", "url": "https://vits.tv/ru/tv/", "ok": True, "items": len([item for item in m3u_items if item.get("source") == "vits-tv"])},
            {"id": "rutv-pw", "url": "http://rutv.pw/", "ok": True, "items": len([item for item in m3u_items if item.get("source") == "rutv-pw"])},
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
