"""Направление D — «Созвездие»: тёмный премиум: экраны.

Ночной синий фон, стеклянные панели, сигнальный циан для живого сигнала
и первичного действия, Unbounded для заголовков, Manrope для текста,
JetBrains Mono для показаний. Метaфора — карта выходов старлайт: точки
светятся, как звёзды; свет стоит только на карте и на кнопке-действии.

Данные — те же снимки `docs/design/fixtures/` через `data.py`; геометрия
карты — `geo`, подписи — `maplab`, контур суши — `worldpath`.
"""

from __future__ import annotations

import html
import math
from types import SimpleNamespace

import maplab
from geo import project
from worldpath import LAND_PATH

from data import STAGES, nodes, num, places, share


def e(s) -> str:
    return html.escape(str(s), quote=True)


def doc(title: str, body: str) -> str:
    return (
        '<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{e(title)}</title>\n"
        '<link rel="stylesheet" href="d.css">\n</head>\n'
        f"{body}\n</body>\n</html>\n"
    )


def stamp(iso: str) -> str:
    if not iso or len(iso) < 16:
        return "—"
    return iso[8:10] + "." + iso[5:7] + " " + iso[11:16]


def dur(s: int) -> str:
    if s < 90:
        return f"{s} с"
    if s < 5400:
        return f"{s / 60:.1f} мин"
    if s < 172800:
        return f"{s / 3600:.1f} ч"
    return f"{s / 86400:.1f} дн"


def wordmark() -> str:
    return '<a class="wordmark" href="#"><i>p</i>poolnet</a>'


def topbar(active: str = "landing") -> str:
    items = [("landing", "Как это работает"), ("pool", "Пул"), ("status", "Состояние")]
    links = ""
    for key, label in items:
        cur = ' aria-current="page"' if key == active else ""
        links += f'<a href="#"{cur}>{e(label)}</a>'
    return (
        '<div class="topbar"><div class="topbar-in">'
        + wordmark()
        + f"<nav>{links}</nav>"
        + '<a class="btn" href="https://t.me/" target="_blank" rel="noopener">'
        "Получить подписку</a>"
        + "</div></div>"
    )


def ttable(headers: list[tuple[str, str]], rows: list[list[str]]) -> str:
    head = "".join(f'<th class="{cls}">{e(t)}</th>' for t, cls in headers)
    body = "".join(
        "<tr>" + "".join(f'<td class="{headers[i][1]}">{c}</td>' for i, c in enumerate(r)) + "</tr>"
        for r in rows
    )
    return (
        '<div class="tbl-wrap"><table class="tbl"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table></div>"
    )


def sec(title: str, aside: str, body: str) -> str:
    return (
        f'<section class="sec"><div class="sec-head"><h2>{e(title)}</h2>'
        f'<span class="aside">{e(aside)}</span></div>{body}</section>'
    )


# --------------------------------------------------------------------------- #
# карта-созвездие
# --------------------------------------------------------------------------- #

LABEL_MIN = 500.0
LABEL_ASPECT = 0.4


def starfield(d: SimpleNamespace, *, empty: bool = False) -> str:
    projects = [(c, project(c.code)) for c in d.countries]
    projects = [(c, p) for c, p in projects if p]
    named = maplab.place(
        [(c.code, p[0], p[1], (7 + 11 * math.sqrt(c.n / max(1, d.top))) / 2) for c, p in projects],
        [c.code for c, _ in projects],
        min_width=LABEL_MIN,
        aspect=LABEL_ASPECT,
        char_w=5.9,
    )
    delay = 0.0
    dots = []
    for c, p in projects:
        size = 7 + 11 * math.sqrt(c.n / max(1, d.top))
        small = " data-small" if c.n < 3 else ""
        side = named.get(c.code)
        lab = f' data-side="{side}"' if side else ""
        dots.append(
            f'<span class="dot" data-c="{e(c.code)}"{small}{lab} '
            f'style="left:{p[0]:.2f}%;top:{p[1]:.2f}%;width:{size:.0f}px;'
            f'height:{size:.0f}px;animation-delay:{delay:.2f}s" '
            f'title="{e(c.name)} — {e(nodes(c.n))}"></span>'
        )
        delay += 0.06
    if empty:
        dots = [
            (
                '<div style="position:absolute;inset:0;display:grid;place-items:center;'
                "text-align:center;color:var(--txt-2);font-size:.9rem;padding:0 32px\">"
                '<p style="margin:0;max-width:44ch">Небо пока пустое: ни один узел ещё '
                "не прошёл все проверки. Карта заполнится после первого обхода — "
                "он идёт каждые шесть часов.</p></div>"
            )
        ]
    outline = (
        '<svg class="land" viewBox="0 0 1000 400" preserveAspectRatio="none" '
        'aria-hidden="true" focusable="false">'
        f'<path d="{LAND_PATH}"/></svg>'
    )
    return (
        '<div class="map-box" role="img" aria-label="Страны, где есть проверенная '
        'точка выхода">' + outline + "".join(dots) + "</div>"
        '<p class="map-cap"><span>проекция равнопромежуточная · '
        "<b>точка = страна выхода</b></span>"
        "<span>контур берега — ориентир из Natural Earth: страна выхода "
        "измеряется через <code>cdn-cgi/trace</code>, координат узел не отдаёт"
        "</span></p>"
    )


def map_card(d: SimpleNamespace, *, empty: bool = False) -> str:
    return '<div class="card map-card">' + starfield(d, empty=empty) + "</div>"


# --------------------------------------------------------------------------- #
# блоки
# --------------------------------------------------------------------------- #


def board(d: SimpleNamespace) -> str:
    """Одна панель, три числа: сколько вошло, сколько дошло, какая доля."""
    raw = d.funnel.get("raw", 0)
    out = d.funnel.get("http", 0)
    src_total = d.sources_on + d.sources_off
    return (
        '<div class="board">'
        '<div class="cell"><div class="k">строк из источников</div>'
        f'<div class="v">{num(raw)}</div>'
        f'<span class="hl">один прогон · {src_total} источников</span></div>'
        '<div class="cell"><div class="k">прошли все проверки</div>'
        f'<div class="v live">{num(out)}</div>'
        "<span class=\"hl\">TCP · TLS · конфигурация · трафик</span></div>"
        '<div class="cell"><div class="k">доля выживших</div>'
        f'<div class="v">{share(out, raw)}</div>'
        "<span class=\"hl\">остальное — мёртвые и вредные узлы</span></div>"
        "</div>"
    )


def rail(d: SimpleNamespace) -> str:
    """Конвейер списком со светящейся дорожкой: полоса — доля от входа."""
    raw = max(1, d.funnel.get("raw", 0))
    rows = []
    for i, (key, label, hint) in enumerate(STAGES, start=1):
        n = max(0, d.funnel.get(key, 0))
        w = max(1.5, n / raw * 100)
        pass_ = " http" if key == "http" else ""
        rows.append(
            f'<div class="row{pass_}">'
            f'<span class="idx">0{i}</span>'
            f'<span class="lab">{e(label)}<small>{e(hint)}</small></span>'
            f'<span class="beam"><i style="width:{w:.1f}%"></i></span>'
            f'<span class="val">{num(n)}</span>'
            f'<span class="pct">{share(n, raw)}</span>'
            "</div>"
        )
    return (
        '<div class="card rail">' + "".join(rows) + "</div>"
        '<p class="note"><b>Ширина дорожки — доля ступени от входа</b>, '
        "не от предыдущей: главный процент — доля «до тебя дошло» — читается "
        "с любой строки, а не выводится из разности ступеней.</p>"
    )


def dir_card(d: SimpleNamespace) -> str:
    if not d.countries:
        return (
            '<div class="card"><div class="dir-head"><span class="search">Поиск '
            "по странам…</span><span>стран пока нет</span></div>"
            '<p class="note" style="margin:0;padding:0 2px 8px">Так выглядит '
            "установка до первого обхода.</p></div>"
        )
    rows = []
    for c in d.countries:
        rows.append(
            f'<a class="cc-row" href="#" title="{e(c.name)} — {e(nodes(c.n))}">'
            f'<span class="cc">{e(c.code)}</span><span class="nm">{e(c.name)}</span>'
            f'<span class="ld"></span><span class="ct">{c.n}</span></a>'
        )
    return (
        '<div class="card">'
        '<div class="dir-head"><span class="search">Поиск по странам…</span>'
        f"<span>{len(d.countries)} стран · по числу узлов</span></div>"
        '<div class="dir-cols">' + "".join(rows) + "</div>"
        "</div>"
    )


def warn_block() -> str:
    return (
        '<div class="warn"><b>Узлы — чужие.</b> '
        "Проверяется доступность и то, что трафик идёт, — не честность "
        "владельца. Не вводите пароли и не проводите платежи через узлы. "
        "Бесплатно здесь означает «без гарантий».</div>"
    )


# --------------------------------------------------------------------------- #
# главная
# --------------------------------------------------------------------------- #


def landing(d: SimpleNamespace) -> str:
    """Полный лонгрид о бесплатном VPN: что это, почему бесплатно,
    что можно и нельзя, клиенты, FAQ, финальный CTA. Все числа — из
    снимка,修辞 — исходя из предметной области."""
    body = (
        topbar("landing")
        + '<div class="wrap">'
        + '<section class="hero">'
        + '<span class="flag">бесплатно · без аккаунтов · открытый код</span>'
        + "<h1>Бесплатный VPN, собранный из проверенных узлов</h1>"
        + '<p class="lede">poolnet.online не продаёт трафик и не арендует '
        "серверы: сеть собрана из публичных узлов, каждый из которых прошёл "
        "шесть проверок — от записи в списке до запроса через узел прямо "
        "сейчас. Вы получаете одну ссылку-подписку; клиент обновляет её сам.</p>"
        + '<div class="cta">'
        + '<a class="btn" href="https://t.me/" target="_blank" rel="noopener">Получить подписку</a>'
        + '<a class="btn line" href="#cull">Как это работает</a>'
        + "</div>"
        + f'<p class="meta">проверка ~10 минут · {nodes(d.verified)} узлов сейчас · '
        f"{places(len(d.countries))} · poolnet.online</p>"
        + "</section>"
        # --- что такое PoolNet
        + sec(
            "Что такое PoolNet",
            "сервис бесплатного VPN",
            '<p class="lede">Это не сеть одного владельца: платных тарифов '
            "нет, и продавать нечего. Пул — общий, а техника проверки — "
            "открытая.</p>"
            + '<div class="values">'
            + '<div class="card"><span class="mark">0₽</span>'
            "<h3>Бесплатно, <em>без «премиум»-выводов</em></h3>"
            '<p>Не просят карту, не дают пробный период и не прячут лучшие '
            "страны за плату: во всех странах один доступ — по одному "
            "адресу подписки.</p></div>"
            + '<div class="card"><span class="mark">≡</span>'
            "<h3>Без аккаунтов, <em>без регистрации</em></h3>"
            '<p>Подписка — обычный URL без привязки к личности. Нечего '
            "регистрировать, нечего и терять: ссылка отдаёт свежий список "
            "узлов в твоём клиенте.</p></div>"
            + '<div class="card"><span class="mark">✓</span>'
            "<h3>Проверка, <em>а не обещание</em></h3>"
            '<p>Каждый узел проходит TCP, TLS, разбор конфига и пробу '
            "трафика. Формула оценки публичная — каждый может её перечитать "
            "и перепроверить результаты.</p></div>"
            + "</div>",
        )
        + '<div style="margin-top:34px">' + map_card(d) + "</div>"
        + board(d)
        + sec(
            "Как узел становится выходом",
            "последний прогон",
            '<p class="lede">Шесть ступеней — от чужой строки в списке до '
            "узла в подписке. Не прошедший любую из них не публикуется; "
            "проценты — доля от входа.</p>"
            + '<div id="cull" style="margin-top:18px">' + rail(d) + "</div>",
        )
        + sec(
            "Где выходы — и сколько их",
            f"{places(len(d.countries))}",
            '<p class="lede">Страна выхода измеряется: прошедший проверку '
            "узел отвечает фактической страной, и она попадает в конфиг. "
            "Хочешь нидерландский выход — берёшь только Нидерланды.</p>"
            + '<div style="margin-top:18px">' + dir_card(d) + "</div>",
        )
        + sec(
            "Почему это бесплатно",
            "устройство сервиса",
            "<p class=\"lede\">Бесплатность здесь не промо-акция, а следствие "
            "устройства: главных статей расходов обычного VPN у сервиса "
            "просто нет.</p>"
            + '<div class="why">'
            + '<div class="card"><span class="mark">∞</span>'
            "<h3>Нет аренды серверов</h3>"
            '<p>Трафик идёт через узлы самих участников. Сервер poolnet.online '
            "только находит и проверяет узлы — это дешевле на порядки, чем "
            "содержать ферму выходов.</p></div>"
            + '<div class="card"><span class="mark">1</span>'
            "<h3>Нет биллинга и поддержки</h3>"
            '<p>Аккаунтов нет, тарифов нет — нечего продавать и некому писать: '
            "интерфейс — это одна страница и ссылка-подписка.</p></div>"
            + '<div class="card"><span class="mark">§</span>'
            "<h3>Открытость вместо маркетинга</h3>"
            '<p>Исходники открыты, формула оценки публична, фиксироваться '
            "не на чем: зеркало оффера — цифры на этой странице, а не "
            "слоган.</p></div>"
            + "</div>",
        )
        + sec(
            "Что можно и что нельзя через узел",
            "без предупреждения не работает",
            '<p class="lede">Узел — чужой сервер. Проверяется доступность '
            "и то, что трафик идёт, — не честность владельца.</p>"
            + '<div class="duo">'
            + '<div class="card allow"><span class="tag">можно без опаски</span>'
            + '<ul class="list">'
            + '<li>Просмотр сайтов, медиа и соцсетей</li>'
            + '<li>Госуслуги и сервисы, не связанные с платежами</li>'
            + '<li>Мессенджеры и голос без ввода ключевых данных</li>'
            + '<li>Проверка выдачи по стране выхода</li>'
            + '</ul></div>'
            + '<div class="card deny"><span class="tag">нельзя</span>'
            + '<ul class="list no">'
            + '<li>Вводить пароли и коды от личных кабинетов</li>'
            + '<li>Проводить банковские платежи через выход</li>'
            + '<li>Считать выход приватным туннелем — это не гарантия</li>'
            + '<li>Ожидать скорости конкретного узла: узлы разные</li>'
            + '</ul></div>'
            + "</div>"
            + '<p class="note"><b>Бесплатно здесь означает «без гарантий».</b> '
            "Пул публичный и нестабильный по природе — узлы умирают, подписка "
            "обновляет список сама.</p>",
        )
        + sec(
            "Куда вставить подписку",
            "один URL",
            '<p class="lede">Любой клиент, умеющий обновляться из ссылки, '
            "импортирует адрес один раз: дальше список обновляется сам, "
            "без ручных выгрузок.</p>"
            + '<div class="grid-4" style="margin-top:18px">'
            "<div class=\"card\"><b>sing-box · Happ</b>"
            "<small>JSON с группами по странам</small></div>"
            "<div class=\"card\"><b>v2rayNG · v2rayN</b>"
            "<small>base64-список</small></div>"
            "<div class=\"card\"><b>Clash · Mihomo</b>"
            "<small>YAML с группами по странам</small></div>"
            "<div class=\"card\"><b>Karing · Shadowrocket</b>"
            "<small>базовый список</small></div>"
            "</div>"
            + '<p class="note">Клиентам без группировки — <code>?unique=1</code>: '
              "один узел на страну.</p>",
        )
        # --- FAQ
        + sec(
            "Частые вопросы",
            "без маркетинга",
            '<div class="card faq">'
            + "<details><summary>Сколько это стоит?</summary>"
            "<p>Ничего. Нет платных тарифов и нет «премиум»-выходов: "
            "в любой стране доступ одинаков.</p></details>"
            + "<details><summary>Нужна ли регистрация?</summary>"
            "<p>Нет. Подписка — обычный URL: вставил в клиент и обновляешься. "
            "Аккаунт с паролем не создаётся, привязки к личности нет.</p></details>"
            + "<details><summary>Почему это бесплатно?</summary>"
            "<p>Нет аренды серверов, биллинга и маркетинга: узлы — участников, "
            "сервис только находит и проверяет их. Бесплатность — следствие "
            "устройства, а не уловка.</p></details>"
            + "<details><summary>Есть ли лимит скорости?</summary>"
            "<p>Со стороны сервиса ограничений нет. Скорость задает сам узел: "
            "это чужие бесплатные серверы, и они различаются — клиент умеет "
            "перебирать выходы.</p></details>"
            + "<details><summary>Какие данные вы храните обо мне?</summary>"
            "<p>Только счётчики проверок и время. Адресов узлов и токенов в "
            "публичном виде нет по построению; подписка отдаёт конфиг без "
            "истории запросов.</p></details>"
            + "<details><summary>На каких приложениях работает подписка?</summary>"
            "<p>sing-box и Happ, v2rayNG и v2rayN, Clash и Mihomo, Karing и "
            "Shadowrocket — везде вставьте в адрес подписки один URL.</p></details>"
            + "<details><summary>Что делать, если узел умер?</summary>"
            "<p>Он пропадёт из списка при следующем обновлении подписки — "
            "клиент сделает это сам. Пул живой: за сутки можно уйти с двух "
            "узлов и прийти на другие.</p></details>"
            + "<details><summary>Насколько это безопасно?</summary>"
            "<p>Настолько, насколько можно доверять публичным узлам: проверка "
            "подтверждает, что узел жив и трафик идёт, — не честность "
            "владельца. пароли и платежи через выход не вводите.</p></details>"
            + "</div>",
        )
        # --- финальный CTA
        + '<div class="cta-final">'
        + "<h2>Одна ссылка — и весь проверенный пул в твоём клиенте</h2>"
        + '<p>Света достаточно: <b style="color:var(--txt)">' + f"{nodes(d.verified)} узлов в "
        f"{places(len(d.countries))}</b> прошли все проверки сегодня.</p>"
        + '<a class="btn" href="https://t.me/" target="_blank" rel="noopener">Получить подписку</a>'
        + '<div class="place">бесплатно · без аккаунтов · poolnet.online</div>'
        + "</div>"
        + "<footer><span>poolnet.online не проксирует твои данные и не хранит "
        "их. Исходники открыты, формула оценки публичная.</span>"
        f'<span class="m">{e(d.generation)}</span></footer>'
        + "</div>"
    )
    return doc("PoolNet — бесплатный VPN без оплаты и регистрации", body)


def landing_empty(d: SimpleNamespace) -> str:
    steps = (
        '<div class="card steps">'
        '<div class="row now"><span class="idx">1</span>'
        '<span class="lab">Списки читаются<small>25 источников</small></span>'
        '<span class="track done"><i></i></span>'
        '<span class="state" data-s="ok">идёт</span></div>'
        '<div class="row"><span class="idx">2</span>'
        '<span class="lab">Узлы проверяются<small>TCP · TLS · конфиг · трафик</small></span>'
        '<span class="track"><i></i></span>'
        '<span class="state" data-s="off">ждёт</span></div>'
        '<div class="row"><span class="idx">3</span>'
        '<span class="lab">Поколение публикуется<small>атомарно, с откатом</small></span>'
        '<span class="track"><i></i></span>'
        '<span class="state" data-s="off">ждёт</span></div>'
        "</div>"
        '<p class="note">Пока поколения нет, страна не показывается и ключ не '
        "выдаётся: пустой список выглядит как сломанный, а как «ещё не готово» "
        "его держит отдельный экран.</p>"
    )
    body = (
        topbar("landing")
        + '<div class="wrap">'
        + '<section class="hero">'
        + '<span class="pill-wait">Первый обход не закончился</span>'
        + "<h1>Пул ещё проверяется</h1>"
        + '<p class="lede">Небо пока пустое: конвейер читает источники, '
        "проверяет узлы и публикует первое поколение — обычно около десяти "
        "минут после установки. Страница обновится сама, напоминание не нужно.</p>"
        + '<div class="cta">'
        + '<a class="btn" href="#">Состояние обхода</a>'
        + '<a class="btn line" href="#">Как это работает</a>'
        + "</div>"
        + '<p class="meta">новая установка · поколения нет</p>'
        + "</section>"
        + '<div style="margin-top:26px">' + map_card(d, empty=True) + "</div>"
        + sec("Что произойдёт дальше", "порядок действий", steps)
        + "<footer><span>poolnet.online не проксирует твои данные и не хранит их.</span>"
        '<span class="m">нет поколения</span></footer>'
        + "</div>"
    )
    return doc("PoolNet — новый сервер, пул проверяется", body)


# --------------------------------------------------------------------------- #
# состояние пула
# --------------------------------------------------------------------------- #


def status(d: SimpleNamespace) -> str:
    runs = d.runs[-18:]
    peak = max((r.get("http") or 0) for r in runs) if runs else 1
    best = max(runs, key=lambda r: r.get("http") or 0) if runs else None
    cols = []
    for r in runs:
        h = max(3.0, (r.get("http") or 0) / peak * 100)
        if r is best:
            cols.append(
                '<div class="best">'
                f'<i data-n="{max(int(r.get("http") or 0), 0)}" '
                f'style="height:{h:.1f}%"></i></div>'
            )
        else:
            cols.append(f"<div><i style=\"height:{h:.1f}%\"></i></div>")

    gens = [
        [
            f"<code>{e(g.get('generation', ''))}</code>"
            + (' <span class="state" data-s="ok">текущее</span>'
               if g.get("generation") == d.generation else ""),
            f'<span class="m">{e(stamp(g.get("at", "")))}</span>',
            num(int(g.get("nodes") or 0)),
            str(int(g.get("payloads") or 0)),
        ]
        for g in d.generations[:8]
    ]

    src_rows = []
    for s in d.sources[:6]:
        if not s.get("enabled"):
            st = '<span class="state" data-s="off">выключен</span>'
        elif s.get("disabled_soon"):
            st = '<span class="state" data-s="warn">отключится</span>'
        else:
            st = '<span class="state" data-s="ok">работает</span>'
        src_rows.append(
            [
                f'<div class="url">{e(s.get("url", ""))}</div>', st,
                str(int(s.get("rounds") or 0)), str(int(s.get("empty_rounds") or 0)),
            ]
        )

    reads = (
        '<div class="readings">'
        f'<div class="cell"><div class="v live">{num(d.verified)}</div>'
        f'<div class="k">{nodes(d.verified)} в подписке</div></div>'
        f'<div class="cell"><div class="v">{num(d.status_countries)}</div>'
        f'<div class="k">{places(d.status_countries)} с выходом</div></div>'
        f'<div class="cell"><div class="v">{e(dur(d.age_s))}</div>'
        '<div class="k">с последнего обхода</div></div>'
        f'<div class="cell"><div class="v">{d.sources_on}/{d.sources_on + d.sources_off}</div>'
        '<div class="k">источников работают</div></div>'
        "</div>"
    )

    last_at = stamp(runs[-1]["at"]) if runs else "—"
    body = (
        topbar("status")
        + '<div class="wrap">'
        + '<section class="hero" style="padding-top:34px;margin-bottom:0">'
        + "<h1>Что происходило на самом деле</h1>"
        + '<p class="lede">Пул публичный и нестабильный по природе: узлы — '
        "чужие серверы, и они умирают. Здесь история обходов, а не только "
        "число узлов сейчас.</p>"
        + reads
        + "</section>"
        + sec(
            "Сколько узлов проходит все проверки",
            f"{len(d.runs)} обходов",
            '<div class="card chart"><div class="plot">' + "".join(cols)
            + '</div><div class="axis"><span>' + e(stamp(runs[0]["at"])) + "</span>"
            + f"<span>{e(last_at)}</span></div></div>"
            + '<p class="note">Каждый столбик — один обход; подсвеченный — лучший '
              "за период. Разброс в разы — норма для публичного пула, а не сбой.</p>",
        )
        + sec(
            "Публикации",
            "адресуются содержимым",
            ttable(
                [("Поколение", ""), ("Опубликовано", ""), ("Узлов", "num"), ("Payload-ов", "num")],
                gens,
            )
            + '<p class="note">Одинаковый пул всегда даёт один номер поколения, '
              "поэтому откат — смена указателя, а не пересборка.</p>",
        )
        + sec(
            "Источники",
            f"{d.sources_on + d.sources_off} всего",
            ttable(
                [("Адрес", ""), ("Состояние", ""), ("Обходов", "num"), ("Пустых", "num")],
                src_rows,
            )
            + f'<p class="note">Работает {d.sources_on}, остальные отключены после '
              "серии пустых обходов. Полные адреса не публикуются: иначе страница "
              "стала бы указателем в обход хаба.</p>",
        )
        + "<footer><span>Только счётчики и время; адресов узлов и токенов "
        "нет по построению.</span>"
        f'<span class="m">{e(d.generation)}</span></footer>'
        + "</div>"
    )
    return doc("PoolNet — состояние пула", body)


# --------------------------------------------------------------------------- #
# вход
# --------------------------------------------------------------------------- #


def login() -> str:
    body = (
        '<div class="login-shell">'
        + '<div class="login-card">'
        + wordmark()
        + "<h1>Вход в панель</h1>"
        + '<p class="sub">Секрет оператора лежит в <code>/etc/hub/hub.env</code> '
        "как <code>HUB_BOT_SECRET</code>. Пользователя нет: это одна вахта.</p>"
        + "<form>"
        + '<label for="secret">Секрет оператора</label>'
        + '<input id="secret" type="password" value="························">'
        + '<button class="btn" type="submit">Войти</button>'
        + "</form>"
        + '<p class="login-foot">Панель доступна только с этой машины: снаружи '
        "её закрывает nginx, внутри проверяется, что запрос пришёл с localhost.</p>"
        + "</div></div>"
    )
    return doc("PoolNet — вход", body)


# --------------------------------------------------------------------------- #
# панель оператора
# --------------------------------------------------------------------------- #


def admin_shell(active: str, title: str, inner: str, d: SimpleNamespace) -> str:
    health = {"ok": ("ok", "свежее"), "stale": ("warn", "устарело")}.get(
        d.health, ("fail", "нет данных")
    )
    groups = [
        ("потребитель", [("overview", "Обзор"), ("countries", "Страны")]),
        ("конвейер", [("sources", "Источники"), ("generations", "Поколения")]),
        ("доступ", [("keys", "Ключи")]),
    ]
    side = ""
    for group_name, items in groups:
        side += f'<div class="group">{e(group_name)}</div>'
        for key, label in items:
            cur = ' aria-current="page"' if key == active else ""
            side += f'<a class="side-link" href="#"{cur}>{e(label)}</a>'
    side += '<div class="spacer"></div>'
    side += f'<div class="ver">{e(d.generation)}</div>'

    body = (
        '<div class="admin-shell">'
        + f'<aside class="admin-side">{wordmark()}{side}</aside>'
        + '<main class="admin-main">'
        + '<div class="admin-top"><h1>' + e(title) + "</h1>"
        + '<div class="gen">'
        + f'<span class="state" data-s="{health[0]}">{health[1]}</span>'
        + f"<span>{e(d.generation)} · {e(dur(d.age_s))} назад</span>"
        + "</div></div>"
        + inner
        + "</main></div>"
    )
    return doc(f"PoolNet — {title}", body)


def stat_grid(d: SimpleNamespace) -> str:
    return (
        '<div class="stat-grid">'
        '<div class="stat"><div class="k">В подписке сейчас</div>'
        f'<div class="v live">{num(d.verified)}</div>'
        "<div class=\"delta\">включая проверенные ранее, не устаревшие</div></div>"
        '<div class="stat"><div class="k">Узлов в индексе</div>'
        f'<div class="v">{num(d.known)}</div>'
        "<div class=\"delta\">разобрано за всю историю</div></div>"
        '<div class="stat"><div class="k">Стран с шардом</div>'
        f'<div class="v">{len(d.countries)}</div>'
        "<div class=\"delta\">«/country/{cc}» отдаёт одну страну</div></div>"
        '<div class="stat"><div class="k">Источников работают</div>'
        f'<div class="v">{d.sources_on}</div>'
        f"<div class=\"delta\">из {d.sources_on + d.sources_off} в списке</div></div>"
        "</div>"
    )


def admin(d: SimpleNamespace) -> str:
    country_rows = [
        [f"<code>{e(c.code)}</code>", e(c.name), str(c.n), share(c.n, max(1, d.verified))]
        for c in d.countries[:14]
    ]
    src_rows = []
    for s in d.sources[:8]:
        if not s.get("enabled"):
            st = '<span class="state" data-s="off">выключен</span>'
        elif s.get("disabled_soon"):
            st = '<span class="state" data-s="warn">отключится</span>'
        else:
            st = '<span class="state" data-s="ok">работает</span>'
        src_rows.append(
            [
                f'<div class="url">{e(s.get("url", ""))}</div>', st,
                str(int(s.get("rounds") or 0)), str(int(s.get("empty_rounds") or 0)),
            ]
        )

    last_run = stamp(d.last.get("at", ""))

    inner = (
        stat_grid(d)
        + sec(
            "Воронка обхода",
            f"последний прогон · {last_run}",
            rail(d)
            + '<p class="note">Каждая следующая проверка дороже предыдущей: '
              "мёртвый порт отсекается до рукопожатия, а трафик проверяется "
              "только у тех, кто дошёл.</p>",
        )
        + '<div class="admin-2col">'
        + "<section>"
        + '<div class="sec-head" style="margin-bottom:16px"><h2 style="font:460 1.15rem/1.25 var(--disp)">Страны</h2>'
        + f'<span class="aside">{len(d.countries)} шардов</span></div>'
        + ttable(
            [("Код", ""), ("Страна", ""), ("Узлов", "num"), ("Доля", "num")],
            country_rows,
        )
        + "</section>"
        + "<section>"
        + '<div class="sec-head" style="margin-bottom:16px"><h2 style="font:460 1.15rem/1.25 var(--disp)">Источники</h2>'
        + f'<span class="aside">{len(d.sources)} в списке</span></div>'
        + ttable(
            [("Адрес", ""), ("Состояние", ""), ("Обходов", "num"), ("Пустых", "num")],
            src_rows,
        )
        + "</section>"
        + "</div>"
    )
    return admin_shell("overview", "Обзор", inner, d)


def keys(d: SimpleNamespace) -> str:
    rows = []
    for t in d.tokens:
        active = t.get("status") == "active"
        rows.append(
            [
                f"<code>{e(t.get('id', ''))}</code>",
                e(t.get("label") or "—"),
                e("телеграм" if t.get("source") == "bot" else "панель"),
                (
                    f'<span class="state" data-s="{"ok" if active else "off"}">'
                    f'{e("активен" if active else "отозван")}</span>'
                ),
                f'<span class="m">{e(stamp(t.get("created_at", "")))}</span>',
                '<button class="btn mini danger">отозвать</button>' if active else "",
            ]
        )

    inner = (
        sec(
            "Выдать ключ",
            "показывается один раз",
            '<div class="card">'
            '<form class="issue">'
            '<div class="field"><label for="lbl">Метка — чтобы через месяц '
            'понять, чей это ключ</label><input id="lbl" placeholder="happ-verify"></div>'
            '<button class="btn" type="submit">Выдать ключ</button>'
            "</form>"
            '<div class="slip">'
            '<div class="k">Ключ выдан. Скопируйте сейчас — второй раз показать нельзя.</div>'
            '<div class="v">hb_7Kq2v9LmXa4TfR8sNc3PeW6yBd1GjHsU</div>'
            '<div class="k" style="font-size:.78rem;color:var(--txt-3)">Ссылка для клиента</div>'
            '<div class="v">https://poolnet.online/sub/'
            "hb_7Kq2v9LmXa4TfR8sNc3PeW6yBd1GjHsU</div>"
            '<div class="meta"><span>метка: happ-verify</span>'
            "<span>источник: панель</span><span>срок: бессрочно</span></div>"
            "</div>"
            "</div>"
            '<p class="note">В базе хранится только SHA-256 ключа. Восстановить '
            "выданный ключ нельзя — ни вам, ни нам; это свойство хранилища, "
            "а не ограничение интерфейса.</p>",
        )
        + sec(
            "Выданные ключи",
            f"{len(d.tokens)} всего",
            ttable(
                [("ID", ""), ("Метка", ""), ("Источник", ""),
                 ("Статус", ""), ("Выдан", ""), ("", "")],
                rows,
            )
            + '<p class="note">Показаны двенадцать символов идентификатора: '
              "достаточно, чтобы отличить два ключа при отзыве, недостаточно — "
              "чтобы восстановить ключ.</p>",
        )
        + sec(
            "Если ключ потерян",
            "отзыв и выдача",
            '<div class="card empty-note">'
            "<h3>Выпустите новый</h3>"
            "<p>Отзовите старый — он перестанет работать сразу — и выдайте "
            "новый. Подписка у клиента это URL с ключом внутри, поэтому после "
            "отзыва её нужно заменить.</p></div>",
        )
    )
    return admin_shell("keys", "Ключи", inner, d)
