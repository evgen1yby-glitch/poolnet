"""Направление C — «Лист показаний», чистый светлый SaaS: экраны.

Третье направление после A («Вахта», тёмная приборная) и B («Атлас выходов»,
антиква). Общая структура с ними — те же экраны, те же данные из `data.py`,
та же геометрия карты — и своя вёрстка: белая карточка на нейтральном
грунте, один шрифт Inter, один синий акцент для действия.
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
        '<link rel="stylesheet" href="c.css">\n</head>\n'
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
    return '<a class="wordmark" href="#"><i>h</i>hub</a>'


def nav(active: str = "landing") -> str:
    items = [("landing", "Как это работает"), ("pool", "Пул"), ("status", "Состояние")]
    links = "".join(
        '<a href="#"%s>%s</a>'
        % (' aria-current="page"' if key == active else "", e(label))
        for key, label in items
    )
    return (
        '<div class="nav"><div class="nav-in">'
        + wordmark()
        + f"<nav>{links}</nav>"
        + '<a class="btn" href="https://t.me/" target="_blank" rel="noopener">'
        "Получить подписку</a>"
        + "</div></div>"
    )


def ttable(headers: list[tuple[str, str]], rows: list[list[str]]) -> str:
    """Таблица-карточка: голова слева, числа справа.

    Второй элемент каждой пары заголовка — класс ячейки; числа выровнены
    вправо по табличным цифрам, чтобы 58 013 читалось рядом с 150.
    """
    head = "".join(
        f'<th class="{cls}">{e(t)}</th>' for t, cls in headers
    )
    body = "".join(
        "<tr>"
        + "".join(f'<td class="{headers[i][1]}">{c}</td>' for i, c in enumerate(r))
        + "</tr>"
        for r in rows
    )
    return (
        '<table class="tbl"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table>"
    )


# --------------------------------------------------------------------------- #
# карта
# --------------------------------------------------------------------------- #

#: Карта стоит внутри карточки в полосе со справочником, поэтому порог
#: подписей тот же, что у атласа: знак, что она вдвое уже, чем приборная.
LABEL_MIN = 500.0
LABEL_ASPECT = 0.4


def map_box(d: SimpleNamespace, *, empty: bool = False) -> str:
    projects = [(c, project(c.code)) for c in d.countries]
    projects = [(c, p) for c, p in projects if p]
    named = maplab.place(
        [(c.code, p[0], p[1], (7 + 11 * math.sqrt(c.n / max(1, d.top))) / 2)
         for c, p in projects],
        [c.code for c, _ in projects],
        min_width=LABEL_MIN,
        aspect=LABEL_ASPECT,
        char_w=5.9,  # 9.5px моноширинного на два знака
    )
    dots = []
    for c, p in projects:
        size = 7 + 11 * math.sqrt(c.n / max(1, d.top))
        small = " data-small" if c.n < 3 else ""
        side = named.get(c.code)
        lab = f' data-side="{side}"' if side else ""
        dots.append(
            f'<span class="dot" data-c="{e(c.code)}"{small}{lab} '
            f'style="left:{p[0]:.2f}%;top:{p[1]:.2f}%;'
            f'width:{size:.0f}px;height:{size:.0f}px" '
            f'title="{e(c.name)} — {e(nodes(c.n))}"></span>'
        )
    if empty:
        dots = [
            '<div style="position:absolute;inset:0;display:grid;place-items:center;'
            "text-align:center;color:var(--ink-2);font-size:.9rem;padding:0 32px\">"
            '<p style="margin:0;max-width:42ch">Точек нет: ни один узел ещё не '
            "прошёл все проверки. Карта заполнится после первого обхода — "
            "он идёт каждые шесть часов.</p></div>"
        ]
    # Берег — ориентир из Natural Earth, не измерение хаба. Поэтому он
    # нейтральным серо-голубым, и подпись под картой это говорит: хаб знает
    # страну выхода, но не координаты узла.
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
        "<span>берег — ориентир из Natural Earth: страна выхода измеряется "
        "через <code>cdn-cgi/trace</code>, координат узел не отдаёт</span></p>"
    )


# --------------------------------------------------------------------------- #
# секции и блоки
# --------------------------------------------------------------------------- #


def sec(no: str, title: str, aside: str, body: str) -> str:
    return (
        f'<section class="sec"><div class="sec-head"><span class="no">{e(no)}</span>'
        f"<h2>{e(title)}</h2><span class=\"aside\">{e(aside)}</span></div>"
        f"{body}</section>"
    )


def funnel_card(d: SimpleNamespace) -> str:
    """Шесть ступеней списком: полоса — доля ступени от входа.

    Пропорциональные высоты столбиков не существовали бы визуально: 58 813
    и 150 в один масштаб не ложатся. Здесь доля подписана у каждой строки —
    и полоса по ней же, поэтому главная доля (http от raw) читается прямо.
    """
    raw = max(1, d.funnel.get("raw", 0))
    rows = []
    for i, (key, label, hint) in enumerate(STAGES, start=1):
        n = max(0, d.funnel.get(key, 0))
        w = max(1.5, n / raw * 100)
        pass_ = " pass" if key == "http" else ""
        rows.append(
            f'<div class="row{pass_}">'
            f'<span class="idx">0{i}</span>'
            f'<span class="lab">{e(label)}<small>{e(hint)}</small></span>'
            f'<span class="track"><i style="width:{w:.1f}%"></i></span>'
            f'<span class="val">{num(n)}</span>'
            f'<span class="pct">{share(n, raw)}</span>'
            "</div>"
        )
    return (
        '<div class="card funnel" style="padding-top:12px">' + "".join(rows) + "</div>"
        '<p class="note" style="margin:14px 2px 0"><b>Ширина полосы — доля '
        "ступени от входа</b>, не от предыдущей: и главный процент — доля "
        "«до тебя дошло» — читается с любой строки, а не выводится "
        "из разности ступеней.</p>"
    )


def summary(d: SimpleNamespace) -> str:
    """Одна карточка, три числа, вертикальные линейки.

    Не три соседние карточки: это одно измерение — сколько вошло, сколько
    осталось, какая доля — прочитанное частями.
    """
    raw = d.funnel.get("raw", 0)
    out = d.funnel.get("http", 0)
    src_total = d.sources_on + d.sources_off
    return (
        '<div class="card summary">'
        '<div class="cell"><div class="k">Строк из источников</div>'
        f'<div class="v">{num(raw)}</div>'
        f'<span class="hl">один прогон · {src_total} источников</span></div>'
        '<div class="cell"><div class="k">Прошли все проверки</div>'
        f'<div class="v out">{num(out)}</div>'
        "<span class=\"hl\">TCP · TLS · конфигурация · трафик</span></div>"
        '<div class="cell"><div class="k">Доля выживших</div>'
        f'<div class="v">{share(out, raw)}</div>'
        "<span class=\"hl\">остальное — мёртвые и вредные узлы</span></div>"
        "</div>"
    )


def countries_card(d: SimpleNamespace) -> str:
    if not d.countries:
        return (
            '<div class="card dir-countries">'
            '<div class="head" style="border-bottom:0;padding-bottom:2px">справочник стран</div>'
            '<p class="note" style="margin:0">Стран пока нет: так выглядит '
            "установка до первого обхода.</p></div>"
        )
    rows = []
    for c in d.countries:
        rows.append(
            f'<a class="cc-row" href="#" title="{e(c.name)} — {e(nodes(c.n))}">'
            f'<span class="cc">{e(c.code)}</span><span class="nm">{e(c.name)}</span>'
            '<span class="ld"></span>'
            f'<span class="ct">{c.n}</span></a>'
        )
    return (
        f'<div class="card dir-countries">'
        "<div class=\"head\"><div class=\"search\">Поиск по странам…</div>"
        f"<span>{len(d.countries)} стран · сортировка по числу узлов</span></div>"
        '<div class="dir-cols">' + "".join(rows) + "</div>"
        + "</div>"
    )


def warn_block() -> str:
    return (
        '<div class="warn"><p style="margin:0"><b>Узлы — чужие.</b> '
        "Проверяется доступность и то, что трафик идёт, — не честность "
        "владельца. Не вводите пароли и не проводите платежи через узлы. "
        "Бесплатно здесь означает «без гарантий».</p></div>"
    )


# --------------------------------------------------------------------------- #
# главная
# --------------------------------------------------------------------------- #


def landing(d: SimpleNamespace) -> str:
    body = (
        nav("landing")
        + '<div class="wrap">'
        + '<section class="hero">'
        + '<span class="eyebrow">Публичный реестр · без аккаунтов</span>'
        + "<h1>Бесплатный VPN, который <b>проверяет</b> каждый узел</h1>"
        + '<p class="lede">Хаб читает публичные списки прокси, прогоняет '
        "каждый узел через шесть проверок и публикует только выжившие. "
        "Трафик идёт через узлы самих участников — сервер их только "
        "находит и проверяет.</p>"
        + '<div class="cta">'
        + '<a class="btn" href="https://t.me/" target="_blank" rel="noopener">Получить подписку</a>'
        + '<a class="btn line" href="#cull">Как это работает</a>'
        + "</div>"
        + f"<p class=\"meta\">проверка занимает ~10 минут · {nodes(d.verified)} в подписке · "
        f"{places(len(d.countries))}</p>"
        + "</section>"
        + summary(d)
        + sec("01", "Что происходит с узлом по дороге", "последний прогон",
              '<p class="lede">Шесть проверок подряд — от записи в чужом '
              'списке до запроса, прошедшего через узел прямо сейчас. Не '
              "прошедший любую из них в подписку не попадает.</p>"
              + funnel_card(d))
        + sec("02", "Где выходы — и сколько их",
              f"{places(len(d.countries))}",
              '<p class="lede">Страна измеряется, а не берётся из имени '
              "хоста: прошедший проверку узел отвечает фактической страной "
              "выхода, и она попадает в конфиг. Клиенту, который хочет "
              "нидерландский выход, не надо листать весь пул целиком.</p>"
              + '<div class="card map-card">' + map_box(d) + "</div>"
              + '<div style="margin-top:14px">' + countries_card(d) + "</div>")
        + sec("03", "Куда вставить подписку", "один URL",
              '<p class="lede">Подписка — обычный URL, который импортирует '
              "любой клиент, умеющий обновляться из ссылки: один адрес "
              "отдаёт список, который обновляется сам.</p>"
              + '<div class="grid-4">'
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
                "один узел на страну.</p>")
        + warn_block()
        + "<footer><span>hub не проксирует твои данные и не хранит их. "
        "Исходники открыты, формула оценки публичная.</span>"
        f'<span class="m">{e(d.generation)}</span></footer>'
        + "</div>"
    )
    return doc("hub — децентрализованная бесплатная VPN-платформа", body)


def landing_empty(d: SimpleNamespace) -> str:
    steps = (
        '<div class="card steps" style="padding-top:10px">'
        '<div class="row"><span class="idx">1</span>'
        '<span class="lab">Списки читаются<small>25 источников</small></span>'
        '<span class="track done"><i></i></span>'
        '<span class="state" data-s="ok">идёт</span></div>'
        '<div class="row wait"><span class="idx">2</span>'
        '<span class="lab">Узлы проверяются<small>TCP · TLS · конфиг · трафик</small></span>'
        '<span class="track"><i></i></span>'
        '<span class="state" data-s="off">ждёт</span></div>'
        '<div class="row wait"><span class="idx">3</span>'
        '<span class="lab">Поколение публикуется<small>атомарно, с откатом</small></span>'
        '<span class="track"><i></i></span>'
        '<span class="state" data-s="off">ждёт</span></div>'
        "</div>"
        '<p class="note" style="margin:16px 2px 0">Пока поколения нет, страна '
        "не показывается и ключ не выдаётся: пустой список выглядит как "
        "сломанный, а как «ещё не готово» его держит отдельный экран.</p>"
    )
    body = (
        nav("landing")
        + '<div class="wrap">'
        + '<section class="hero">'
        + '<span class="pill-empty">Первый обход не закончился</span>'
        + "<h1>Пул ещё проверяется</h1>"
        + '<p class="lede">Показаний ещё нет: конвейер читает источники, '
        "проверяет узлы и публикует первое поколение — обычно около "
        "десяти минут после установки. Страница обновится сама, ставить "
        "напоминание не нужно.</p>"
        + '<div class="cta">'
        + '<a class="btn" href="#">Состояние обхода</a>'
        + '<a class="btn line" href="#">Как это работает</a>'
        + "</div>"
        + '<p class="meta">новая установка · поколения нет</p>'
        + "</section>"
        + '<div class="card map-card">' + map_box(d, empty=True) + "</div>"
        + sec("01", "Что произойдёт дальше", "порядок действий", steps)
        + "<footer><span>hub не проксирует твои данные и не хранит их.</span>"
        '<span class="m">нет поколения</span></footer>'
        "</div>"
    )
    return doc("hub — новый сервер, пул проверяется", body)


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
            cols.append('<div class="best">'
                        f'<i data-n="{max(int(r.get("http") or 0), 0)}" '
                        f'style="height:{h:.1f}%"></i></div>')
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
        src_rows.append([
            f'<div class="url">{e(s.get("url", ""))}</div>', st,
            str(int(s.get("rounds") or 0)), str(int(s.get("empty_rounds") or 0)),
        ])

    reads = (
        '<div class="card readings">'
        f'<div><div class="v live">{num(d.verified)}</div>'
        f'<div class="k">{nodes(d.verified)} в подписке</div></div>'
        f'<div><div class="v">{num(d.status_countries)}</div>'
        f'<div class="k">{places(d.status_countries)} с выходом</div></div>'
        f'<div><div class="v">{e(dur(d.age_s))}</div>'
        '<div class="k">с последнего обхода</div></div>'
        f'<div><div class="v">{d.sources_on}/{d.sources_on + d.sources_off}</div>'
        '<div class="k">источников работают</div></div>'
        "</div>"
    )

    last_at = stamp(runs[-1]["at"]) if runs else "—"
    body = (
        '<div class="wrap">'
        + '<div style="display:flex;align-items:center;gap:14px;padding:26px 0 0">'
        + wordmark()
        + '<span style="color:var(--ink-3);font-size:.85rem">— состояние пула</span>'
        + '<a style="margin-left:auto;font-size:.9rem;font-weight:550" href="#">На главную</a>'
        + "</div>"
        + '<section style="margin-top:26px">'
        + "<h1 style=\"margin:0;font-size:clamp(1.8rem,3.6vw,2.4rem);font-weight:640;"
        "letter-spacing:-0.03em\">Что происходило на самом деле</h1>"
        + '<p class="lede" style="margin-top:14px">Пул публичный и '
        "нестабильный по природе: узлы — чужие серверы, и они умирают. "
        "Здесь история обходов, а не только число узлов сейчас.</p>"
        + reads
        + "</section>"
        + sec("01", "Сколько узлов проходит все проверки",
              f"{len(d.runs)} обходов",
              '<div class="card chart"><div class="plot">' + "".join(cols)
              + f'</div><div class="axis"><span>{e(stamp(runs[0]["at"]))}</span>'
              + f"<span>{e(last_at)}</span></div></div>"
              + '<p class="note" style="margin:14px 2px 0">Каждый столбик — '
                "один обход, тёмный — лучший за период. Разброс в разы — "
                "норма для публичного пула, а не сбой.</p>")
        + sec("02", "Публикации", "адресуются содержимым",
              '<div class="card tbl-wrap">'
              + ttable(
                  [("Поколение", ""), ("Опубликовано", ""),
                   ("Узлов", "num"), ("Payload-ов", "num")],
                  gens)
              + "</div>"
              + '<p class="note">Одинаковый пул всегда даёт один номер '
                "поколения, поэтому откат — смена указателя, а не пересборка.</p>")
        + sec("03", "Источники", f"{d.sources_on + d.sources_off} всего",
              '<div class="card tbl-wrap">'
              + ttable(
                  [("Адрес", ""), ("Состояние", ""),
                   ("Обходов", "num"), ("Пустых", "num")],
                  src_rows)
              + "</div>"
              + f'<p class="note">Работает {d.sources_on}, остальные отключены '
                "после серии пустых обходов. Полные адреса здесь не "
                "публикуются: иначе страница стала бы указателем в обход "
                "хаба.</p>")
        + "<footer><span>Только счётчики и время; адресов узлов и токенов "
        "нет по построению.</span>"
        f'<span class="m">{e(d.generation)}</span></footer>'
        + "</div>"
    )
    return doc("hub — состояние пула", body)


# --------------------------------------------------------------------------- #
# вход
# --------------------------------------------------------------------------- #


def login() -> str:
    body = (
        '<div class="login-shell">'
        + '<div class="card login-card">'
        + wordmark()
        + "<h1>Вход в панель</h1>"
        + '<p class="sub">Секрет оператора лежит в <code>/etc/hub/hub.env</code> '
        "как <code>HUB_BOT_SECRET</code>. Пользователя нет: это одна вахта.</p>"
        + "<form>"
        + '<label for="secret">Секрет оператора</label>'
        + '<input id="secret" type="password" value="························">'
        + '<button class="btn" type="submit">Войти</button>'
        + "</form>"
        + '<p class="login-foot">Панель доступна только с этой машины: '
        "снаружи её закрывает nginx, внутри проверяется, что запрос пришёл "
        "с localhost.</p>"
        + "</div></div>"
    )
    return doc("hub — вход", body)


# --------------------------------------------------------------------------- #
# панель оператора
# --------------------------------------------------------------------------- #


def admin_shell(active: str, title: str, inner: str, d: SimpleNamespace) -> str:
    health = {"ok": ("ok", "свежее"), "stale": ("warn", "устарело")}.get(
        d.health, ("fail", "нет данных")
    )
    groups = [
        ("Потребитель", [("overview", "Обзор"), ("countries", "Страны")]),
        ("Конвейер", [("sources", "Источники"), ("generations", "Поколения")]),
        ("Доступ", [("keys", "Ключи")]),
    ]
    side = ""
    for group_name, items in groups:
        side += f'<div class="group">{e(group_name)}</div>'
        for key, label in items:
            cur = ' aria-current="page"' if key == active else ""
            side += f'<a href="#"{cur}>{e(label)}</a>'
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
    return doc(f"hub — {title}", body)


def stat_grid(d: SimpleNamespace) -> str:
    return (
        '<div class="stat-grid">'
        '<div class="card stat"><div class="k">В подписке сейчас</div>'
        f'<div class="v live">{num(d.verified)}</div>'
        "<div class=\"delta\">включая проверенные ранее, не устаревшие</div></div>"
        '<div class="card stat"><div class="k">Узлов в индексе</div>'
        f'<div class="v">{num(d.known)}</div>'
        "<div class=\"delta\">разобрано за всю историю</div></div>"
        '<div class="card stat"><div class="k">Стран с шардом</div>'
        f'<div class="v">{len(d.countries)}</div>'
        "<div class=\"delta\">«/country/{cc}» отдаёт одну страну</div></div>"
        '<div class="card stat"><div class="k">Источников работают</div>'
        f'<div class="v">{d.sources_on}</div>'
        f"<div class=\"delta\">из {d.sources_on + d.sources_off} в списке</div></div>"
        "</div>"
    )


def admin(d: SimpleNamespace) -> str:
    country_rows = [
        [f"<code>{e(c.code)}</code>", e(c.name), str(c.n),
         share(c.n, max(1, d.verified))]
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
        src_rows.append([
            f'<div class="url">{e(s.get("url", ""))}</div>', st,
            str(int(s.get("rounds") or 0)), str(int(s.get("empty_rounds") or 0)),
        ])

    last_run = stamp(d.last.get("at", ""))
    country_aside = f"{len(d.countries)} шардов"
    source_aside = f"{len(d.sources)} в списке"

    inner = (
        stat_grid(d)
        + '<section style="margin-top:38px">'
        + '<div class="sec-head" style="margin:0 0 12px"><span class="no">01</span>'
        + "<h2>Воронка обхода</h2>"
        + f'<span class="aside">последний прогон · {e(last_run)}</span></div>'
        + funnel_card(d)
        + '<p class="note" style="margin:14px 2px 0">Каждая следующая проверка '
        "дороже предыдущей: мёртвый порт отсекается до рукопожатия, а "
        "трафик проверяется только у тех, кто дошёл.</p>"
        + "</section>"
        + '<div class="admin-2col">'
        + '<section><div class="sec-head" style="margin:0 0 12px">'
        + '<span class="no">02</span><h2>Страны</h2>'
        + f'<span class="aside">{e(country_aside)}</span></div>'
        + '<div class="card tbl-wrap">'
        + ttable(
            [("Код", ""), ("Страна", ""), ("Узлов", "num"), ("Доля", "num")],
            country_rows)
        + "</div></section>"
        + '<section><div class="sec-head" style="margin:0 0 12px">'
        + '<span class="no">03</span><h2>Источники</h2>'
        + f'<span class="aside">{e(source_aside)}</span></div>'
        + '<div class="card tbl-wrap">'
        + ttable(
            [("Адрес", ""), ("Состояние", ""),
             ("Обходов", "num"), ("Пустых", "num")],
            src_rows)
        + "</div></section>"
        + "</div>"
    )
    return admin_shell("overview", "Обзор", inner, d)


def keys(d: SimpleNamespace) -> str:
    rows = []
    for t in d.tokens:
        active = t.get("status") == "active"
        rows.append([
            f"<code>{e(t.get('id', ''))}</code>",
            e(t.get("label") or "—"),
            e("телеграм" if t.get("source") == "bot" else "панель"),
            f'<span class="state" data-s="{"ok" if active else "off"}">'
            f'{e("активен" if active else "отозван")}</span>',
            f'<span class="m">{e(stamp(t.get("created_at", "")))}</span>',
            '<button class="btn mini danger">отозвать</button>' if active else "",
        ])

    inner = (
        '<section>'
        + '<div class="sec-head" style="margin:0 0 12px"><span class="no">01</span>'
        + '<h2>Выдать ключ</h2><span class="aside">показывается один раз</span></div>'
        + '<div class="card" style="padding-bottom:24px">'
        + '<form class="issue">'
        + '<div class="field"><label for="lbl">Метка — чтобы через месяц '
        'понять, чей это ключ</label><input id="lbl" placeholder="happ-verify"></div>'
        + '<button class="btn" type="submit">Выдать ключ</button>'
        + "</form>"
        + '<div class="slip" style="margin:0 26px 24px">'
        + '<div class="k">Ключ выдан. Скопируйте сейчас — второй раз показать нельзя.</div>'
        + '<div class="v">hb_7Kq2v9LmXa4TfR8sNc3PeW6yBd1GjHsU</div>'
        + '<div class="k" style="font-weight:560;color:var(--ink-3);font-size:.78rem">'
        "Ссылка для клиента</div>"
        + '<div class="v">https://193.34.212.154:8444/sub/'
        "hb_7Kq2v9LmXa4TfR8sNc3PeW6yBd1GjHsU</div>"
        + '<div class="meta"><span>метка: happ-verify</span>'
        "<span>источник: панель</span><span>срок: бессрочно</span></div>"
        + "</div></div>"
        + '<p class="note" style="margin:14px 2px 0">В базе хранится только '
        "SHA-256 ключа. Восстановить выданный ключ нельзя — ни вам, ни нам; "
        "это свойство хранилища, а не ограничение интерфейса.</p>"
        + "</section>"
        + '<section style="margin-top:44px">'
        + '<div class="sec-head" style="margin:0 0 12px">'
        + "<span class=\"no\">02</span><h2>Выданные ключи</h2>"
        + "<span class=\"aside\">%d всего</span></div>" % len(d.tokens)
        + '<div class="card tbl-wrap">'
        + ttable(
            [("ID", ""), ("Метка", ""), ("Источник", ""),
             ("Статус", ""), ("Выдан", ""), ("", "")],
            rows)
        + "</div>"
        + '<p class="note" style="margin:14px 2px 0">Показаны двенадцать '
        "символов идентификатора: достаточно, чтобы отличить два ключа "
        "при отзыве, недостаточно — чтобы восстановить ключ.</p>"
        + "</section>"
        + '<section style="margin-top:44px">'
        + '<div class="sec-head" style="margin:0 0 12px">'
        + "<span class=\"no\">03</span><h2>Если ключ потерян</h2>"
        + '<span class="aside">отзыв и выдача</span></div>'
        + '<div class="card"><div class="empty-note" style="margin:0">'
        + "<h3>Выпустите новый</h3>"
        + "<p style=\"margin:0\">Отзовите старый — он перестанет работать "
        "сразу — и выдайте новый. Подписка у клиента это URL с ключом "
        "внутри, поэтому после отзыва её нужно заменить.</p></div></div>"
        + "</section>"
    )
    return admin_shell("keys", "Ключи", inner, d)
