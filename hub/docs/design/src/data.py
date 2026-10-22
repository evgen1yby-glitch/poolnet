"""Один набор данных для двух направлений.

Оба макета показывают ОДИН И ТОТ ЖЕ момент жизни хаба: то же поколение, тот же
последний обход, те же источники. Иначе сравнивать пришлось бы не дизайн, а
разные цифры — и разница в композиции объяснялась бы разницей в данных.

Источник — снимки в `docs/design/fixtures/`, снятые с работающего сервера.
Числа в разметке страниц не набираются руками: всё, что выглядит как измерение,
приходит отсюда.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


#: Русские названия стран. Только те коды, которые встречаются в пуле; имя
#: нужно для человеческого чтения, код — для ссылки.
RU = {
    "AE": "ОАЭ", "AT": "Австрия", "BG": "Болгария", "BR": "Бразилия",
    "BY": "Беларусь", "CA": "Канада", "CH": "Швейцария", "CZ": "Чехия",
    "DE": "Германия", "EE": "Эстония", "ES": "Испания", "FI": "Финляндия",
    "FR": "Франция", "GB": "Великобритания", "HK": "Гонконг", "HU": "Венгрия",
    "ID": "Индонезия", "IE": "Ирландия", "IN": "Индия", "IT": "Италия",
    "JP": "Япония", "KR": "Южная Корея", "KZ": "Казахстан", "LT": "Литва",
    "LV": "Латвия", "MD": "Молдова", "MX": "Мексика", "NL": "Нидерланды",
    "NO": "Норвегия", "PL": "Польша", "PT": "Португалия", "RO": "Румыния",
    "RS": "Сербия", "RU": "Россия", "SE": "Швеция", "SG": "Сингапур",
    "SK": "Словакия", "TH": "Таиланд", "TR": "Турция", "UA": "Украина",
    "US": "США", "VN": "Вьетнам", "ZA": "ЮАР",
}

#: Протокол → расширение подписки, которое получает клиент этой семьи.
PROTO_CLIENT = {
    "vless": "sing-box · Happ",
    "vmess": "v2rayNG · Shadowrocket",
    "trojan": "Clash · Mihomo",
    "ss": "Karing · Hiddink",
}

#: Подписи ступеней воронки. Порядок совпадает с ключами `funnel` / `status`.
STAGES = [
    ("raw", "Строки из источников", "всё, что отдали списки"),
    ("parsed", "Разобрано в конфиги", "синтаксис понят"),
    ("tcp", "Порт открыт", "кто-то слушает"),
    ("tls", "TLS отвечает", "рукопожатие прошло"),
    ("config", "Конфиг принят ядром", "sing-box не ругается"),
    ("http", "Трафик реально идёт", "через узел прошёл запрос"),
]


def num(n: int) -> str:
    """`59013` → `59 013`: группы разделены узким неразрывным пробелом."""
    return f"{n:,}".replace(",", " ")


def share(part: int, whole: int) -> str:
    if not whole:
        return "—"
    return f"{part / whole * 100:.1f}".replace(".", ",") + "%"


def plural(n: int, one: str, few: str, many: str) -> str:
    """Русская форма при числе: `1 узел`, `2 узла`, `150 узлов`.

    Нужна, потому что подписи собираются сложением строк, и «29 стран» рядом
    с «150 узлов» — не мелочь: склонение приходит из счётчика, а не из шаблона.
    """
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def nodes(n: int) -> str:
    return f"{num(n)} {plural(n, 'узел', 'узла', 'узлов')}"


def places(n: int) -> str:
    return f"{num(n)} {plural(n, 'страна', 'страны', 'стран')}"


def exits(n: int) -> str:
    return f"{num(n)} {plural(n, 'выход', 'выхода', 'выходов')}"


def load() -> SimpleNamespace:
    stats = _load("stats.json")
    status = _load("status.json")
    admin = _load("admin.json")

    runs = status.get("runs") or []
    last = runs[-1] if runs else {}
    funnel = {k: int(last.get(k) or 0) for k, _, _ in STAGES}
    funnel["raw"] = funnel["raw"] or int(admin.get("funnel", {}).get("raw") or 0)

    # Страны пула: только те, что опубликованы, и без `unknown` — «не измерено»
    # это не страна, и предлагать её как точку выхода нельзя.
    countries = [
        SimpleNamespace(code=c["name"], name=RU.get(c["name"], c["name"]), n=int(c["n"]))
        for c in stats.get("by_country", [])
        if c.get("name") not in (None, "", "unknown")
    ]
    countries.sort(key=lambda c: (-c.n, c.name))
    top = countries[0].n if countries else 1

    protocols = [SimpleNamespace(name=p["name"], n=int(p["n"])) for p in stats.get("by_protocol", [])]
    protocols.sort(key=lambda p: -p.n)
    pmax = protocols[0].n if protocols else 1

    gens = admin.get("generations", [])[:8]
    tokens = admin.get("tokens", [])
    sources = admin.get("sources", [])

    now = status.get("now", {})
    return SimpleNamespace(
        generation=stats.get("generation", ""),
        verified=int(stats.get("verified", 0)),
        known=int(stats.get("known", 0)),
        countries=countries,
        top=top,
        protocols=protocols,
        proto_max=pmax,
        funnel=funnel,
        runs=runs,
        last=last,
        generations=gens,
        tokens=tokens,
        sources=sources,
        sources_on=sum(1 for s in sources if s.get("enabled")),
        sources_off=sum(1 for s in sources if not s.get("enabled")),
        age_s=int(now.get("age_s", 0)),
        status_countries=int(now.get("countries", len(countries))),
        health=admin.get("health", {}).get("status", "ok"),
        #: Окно переноса узлов, проверенных в прошлых обходах. Это не настройка
        #: макета: `HUB_RECENT_HOURS` в `cli.py` по умолчанию 8, а страница
        #: обязана называть ту цифру, по которой пул собирается на самом деле.
        recent_hours=8,
        mode="demo",
    )


def empty() -> SimpleNamespace:
    """Тот же набор, но в состоянии «поколения ещё нет».

    Отдельный конструктор, а не флаг в разметке: пустое состояние — это не
    вариант отрисовки данных, а их отсутствие, и страница должна уметь его
    показать, не притворяясь, что ноль — это измерение.
    """
    base = load()
    base.generation = ""
    base.verified = base.known = 0
    base.countries = []
    base.protocols = []
    base.top = 1
    base.funnel = {k: 0 for k, _, _ in STAGES}
    base.runs = []
    base.generations = []
    base.tokens = []
    base.sources_on = base.sources_off = 0
    base.status_countries = 0
    base.health = "fail"
    base.mode = "empty"
    return base
