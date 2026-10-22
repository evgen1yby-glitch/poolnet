"""Направление A — «Вахта»: экраны.

Каждый экран — функция, возвращающая полный HTML-документ. Стили в него не
вложены: их подставляет сборщик, чтобы один и тот же `a.css` был и в макете, и
в отдельном файле, открытом из `file://`.

Копирайт — часть макета, а не заполнитель. Он написан от лица продукта,
называет вещи тем, чем они являются, и не обещает того, чего хаб не делает:
он не проксирует трафик и не гарантирует честность чужих узлов.
"""

from __future__ import annotations

import html
import math
from types import SimpleNamespace

from data import PROTO_CLIENT, RU, STAGES, exits, nodes, num, places, share
import maplab
from geo import project
from worldpath import LAND_PATH


def e(s) -> str:
    return html.escape(str(s), quote=True)


def doc(title: str, body: str, *, cls: str = "") -> str:
    return (
        '<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{e(title)}</title>\n"
        "<link rel=\"stylesheet\" href=\"a.css\">\n</head>\n"
        f'<body class="{cls}">\n{body}\n</body>\n</html>\n'
    )


# --------------------------------------------------------------------------- #
# общие части
# --------------------------------------------------------------------------- #


def rail(active: str) -> str:
    items = [
        ("/", "free", "free"),
        ("/$1", "за $1", "dollar"),
        ("/status", "состояние", "status"),
    ]
    nav = "".join(
        f'<a href="#"{" aria-current" if key == active else ""}>{e(label)}</a>'
        for _, label, key in items
    )
    return (
        '<div class="rail">'
        '<a class="wordmark" href="#">hub<b>.</b></a>'
        f'<nav aria-label="Разделы">{nav}</nav>'
        '<div class="stamp">v0.9 · ip-only</div>'
        "</div>"
    )


def topbar(d: SimpleNamespace, *, where: str = "публичный реестр") -> str:
    health = {"ok": ("ok", "свежее"), "stale": ("warn", "устарело")}.get(
        d.health, ("fail", "нет данных")
    )
    if health[0] == "fail" and d.mode == "empty":
        # Новая установка — не отказ. Красная точка на пустой странице читалась
        # бы как поломка ровно в тот момент, когда всё идёт по плану.
        health = ("warn", "первый обход")
    return (
        '<div class="topbar">'
        f'<div class="where"><b>{e(where)}</b>'
        f"<span>обход {e(stamp(d.last.get('at', '')))} UTC</span></div>"
        '<div class="lang" role="group" aria-label="Язык">'
        '<button type="button" aria-pressed="true">RU</button>'
        '<button type="button" aria-pressed="false">EN</button>'
        "</div>"
        f'<span class="state" data-s="{health[0]}">{health[1]}</span>'
        "</div>"
    )


def stamp(iso: str) -> str:
    """`2026-10-17T04:25:05+00:00` → `17.10 04:25`."""
    if not iso or len(iso) < 16:
        return "—"
    return iso[8:10] + "." + iso[5:7] + " " + iso[11:16]


def board(d: SimpleNamespace) -> str:
    """Воронка: шесть ступеней, полоса каждой — доля от предыдущей."""
    rows = []
    prev = 0
    for i, (key, label, hint) in enumerate(STAGES):
        n = d.funnel.get(key, 0)
        pct = 100.0 if i == 0 else (n / prev * 100 if prev else 0.0)
        width = max(0.6, pct) if n else 0
        lost = 0 if i == 0 else max(0, prev - n)
        prev = n
        rows.append(
            '<div class="board-row">'
            f'<div class="k">{e(label)}<small>{e(hint)}</small></div>'
            f'<div class="n{" live" if key == "http" else ""}">{num(n)}</div>'
            f'<div class="track"><i{" class=live" if key == "http" else ""} '
            f'style="width:{width:.2f}%"></i></div>'
            f'<div class="d{" drop" if lost else ""}">{("−" + num(lost)) if lost else "вход"}</div>'
            "</div>"
        )
    survivors = d.funnel.get("http", 0)
    return (
        '<div class="board">' + "".join(rows) + "</div>"
        '<div class="board-foot">'
        f"<span>выживаемость <b>{share(survivors, d.funnel.get('raw', 0))}</b></span>"
        f"<span>ниже этой ступени <b>не публикуется</b></span>"
        f"<span>следующий обход <b>через 6 ч</b></span>"
        "</div>"
    )


def ledger(d: SimpleNamespace) -> str:
    if not d.countries:
        return (
            '<div class="empty-note"><h3>Стран пока нет</h3>'
            "<p>Ни один узел не прошёл все проверки в последнем обходе. "
            "Список появится после следующего прогона — он идёт каждые шесть часов.</p>"
            "</div>"
        )
    rows = []
    for c in d.countries:
        w = max(2, round(c.n / d.top * 100))
        rows.append(
            f'<a class="row" href="#" title="{e(c.name)} — {e(nodes(c.n))}">'
            f'<span class="cc">{e(c.code)}</span>'
            f'<span class="nm">{e(c.name)}</span>'
            f'<span class="ct">{c.n}</span>'
            f'<span class="gauge"><i style="width:{w}%"></i></span>'
            "</a>"
        )
    return '<div class="ledger">' + "".join(rows) + "</div>"


def protocols(d: SimpleNamespace) -> str:
    rows = []
    for p in d.protocols:
        w = max(2, round(p.n / d.proto_max * 100))
        rows.append(
            '<div class="board-row">'
            f'<div class="k">{e(p.name)}<small>{e(PROTO_CLIENT.get(p.name, "—"))}</small></div>'
            f'<div class="n">{num(p.n)}</div>'
            f'<div class="track"><i style="width:{w}%"></i></div>'
            f'<div class="d">{share(p.n, d.known)}</div>'
            "</div>"
        )
    return '<div class="board">' + "".join(rows) + "</div>"


# --------------------------------------------------------------------------- #
# карта выходов
# --------------------------------------------------------------------------- #


#: Ширина карты, при которой подписи ещё показываются. Ровно эта же граница
#: стоит в `@container` в `a.css`; два числа обязаны совпадать, иначе
#: расстановка считалась бы для одного кадра, а показывалась на другом.
LABEL_MIN = 940.0

#: Кадр карты 5:2 — тот же, что у берега.
LABEL_ASPECT = 0.4


def exits_map(d: SimpleNamespace, *, limit: int = 12) -> str:
    """Точки по странам на той же сетке, что и берег.

    Карта структурирует страницу, но измерением является только точка: хаб
    знает страну выхода, а не координаты узла. Подпись под картой говорит это
    прямо, потому что карта — единственный элемент, который может соврать
    незаметно.

    Подписаны не первые двенадцать стран, а первые двенадцать, которым
    хватило места: подпись проверяется на пересечение с каждой точкой и с
    каждой уже поставленной подписью. Если для крупной точки места нет
    (Нидерланды и Германия стоят в 11 px друг от друга), она остаётся без
    подписи — точка видна и называет себя во всплывающей подсказке, а полный
    реестр с числами стоит ниже. Молчаливая потеря подписи лучше подписи,
    закрывающей чужое измерение.

    Расстановка считается для самого узкого кадра, на котором подписи ещё
    видны (`LABEL_MIN`). На широком экране точки разъезжаются, а размеры
    остаются прежними — значит место, свободное на 940 px, свободно и на
    1240 px. Обратное неверно, и именно это ломалось.
    """
    projects = [(c, project(c.code)) for c in d.countries]
    projects = [(c, p) for c, p in projects if p]
    if not projects:
        return (
            '<div class="empty-note"><h3>Точек пока нет</h3>'
            "<p>Ни один узел ещё не прошёл проверку. Карта заполнится после "
            "первого обхода — он идёт каждые шесть часов.</p></div>"
        )

    radius = lambda n: (7 + 13 * math.sqrt(n / max(1, d.top))) / 2  # noqa: E731
    named = maplab.place(
        [(c.code, x, y, radius(c.n)) for c, (x, y) in projects],
        [c.code for c, _ in projects[:limit]],
        min_width=LABEL_MIN,
        aspect=LABEL_ASPECT,
        char_w=5.76,  # моноширинный 0.56 rem с трекингом .04em на два знака
    )

    dots = []
    for c, (x, y) in projects:
        size = 7 + 13 * math.sqrt(c.n / max(1, d.top))
        side = named.get(c.code)
        lab = f' data-lab data-side="{side}"' if side else ""
        dots.append(
            f'<span class="dot"{lab} data-c="{e(c.code)}" '
            f'style="left:{x:.2f}%;top:{y:.2f}%;'
            f'width:{size:.0f}px;height:{size:.0f}px" '
            f'title="{e(c.name)} — {e(nodes(c.n))}"></span>'
        )
    outline = (
        '<svg class="land" viewBox="0 0 1000 400" preserveAspectRatio="none" '
        'aria-hidden="true" focusable="false">'
        f'<path d="{LAND_PATH}"/></svg>'
    )
    return (
        '<div class="map-wrap">'
        '<div class="map-box" role="img" aria-label="Страны, где есть '
        'проверенная точка выхода">' + outline + "".join(dots) + "</div>"
        '<p class="map-cap"><span>проекция равнопромежуточная · '
        "<b>точка = страна выхода</b></span>"
        "<span>берег — ориентир из Natural Earth, не измерение: "
        "координат узлов хаб не знает</span></p>"
        "</div>"
    )


# --------------------------------------------------------------------------- #
# главная — два информационных поля
# --------------------------------------------------------------------------- #
#
# Один и тот же экран, две разные посылки. Разница не в заголовке: у каждого
# варианта свой порядок разделов, потому что разные обещания требуют разных
# доказательств.
#
# «Бесплатно» доказывается честностью ограничений: если не сказать, чего сервис
# не даёт, слово «бесплатно» читается как приманка. Поэтому у этого варианта
# отдельный раздел «что значит бесплатно» с двумя колонками — что даётся и что
# нет, — и он стоит выше воронки: сначала снимаем подозрение, потом показываем
# работу.
#
# «$1» доказывается объяснением цены: дешёвая подписка без объяснения выглядит
# либо приманкой, либо признаком того, что за неё платят данные. Поэтому у этого
# варианта раздел «почему доллар» отвечает, за что именно взяты деньги, — за
# измерение, а не за серверы, которых у хаба нет.


def hero(
    d: SimpleNamespace,
    *,
    title: str,
    text: str,
    primary: str,
    secondary: str,
    note: str,
) -> str:
    return (
        '<section class="pier"><div><h1>' + title + "</h1></div>"
        '<div class="read"><p>' + text + "</p>"
        '<div class="actions">'
        f'<a class="btn primary" href="#">{e(primary)}</a>'
        f'<a class="btn ghost" href="#">{e(secondary)}</a>'
        "</div>"
        f'<span class="meta-note">{note}</span>'
        "</div></section>"
    )


def pool_section(d: SimpleNamespace) -> str:
    """Карта и реестр — один раздел: карта отвечает «где», реестр — «сколько»."""
    return (
        '<section class="sec" id="pool" aria-labelledby="pool-h">'
        '<div class="sec-h">'
        '<h2 id="pool-h">Где есть выход</h2>'
        f'<span class="aside">{nodes(d.verified)} · {places(len(d.countries))}</span>'
        "</div>"
        "<p class=\"lede\">Страна измерена, а не взята из имени хоста: узел, "
        "прошедший проверку, открывает <code>cdn-cgi/trace</code>, и настоящая "
        "точка выхода попадает в конфиг. Подделанная страна снижает оценку и в "
        "список не попадает.</p>"
        + exits_map(d)
        + ledger(d)
        + "</section>"
    )


def faq(items: list[tuple[str, str]]) -> str:
    rows = "".join(
        f'<div class="qa"><dt>{q}</dt><dd>{a}</dd></div>' for q, a in items
    )
    return '<dl class="faq">' + rows + "</dl>"


def clients_section(d: SimpleNamespace) -> str:
    return (
        '<section class="sec" aria-labelledby="clients-h">'
        '<div class="sec-h"><h2 id="clients-h">Куда вставить подписку</h2>'
        '<span class="aside">один URL, обновляется сам</span></div>'
        '<div class="clients">'
        "<div><b>sing-box · Happ</b><span>JSON с группами по странам</span></div>"
        "<div><b>v2rayNG · v2rayN</b><span>base64-список</span></div>"
        "<div><b>Clash · Mihomo</b><span>YAML с группами по странам</span></div>"
        "<div><b>Karing · Shadowrocket</b><span>базовый список</span></div>"
        "</div>"
        '<p class="note">Для клиентов, которые не умеют группировать, есть '
        "<code>?unique=1</code>: один узел на страну — список становится выбором "
        "страны, а не списком из четырёх «Финляндий».</p>"
        "</section>"
    )


def warning() -> str:
    return (
        '<p class="warn"><span class="mark">!</span><span><b>Узлы чужие.</b> '
        "Считай их враждебными: не передавай пароли и сессии, не проводи "
        "денежные операции. Проверяется доступность и то, что трафик идёт, — "
        "не честность владельца. Бесплатно здесь означает «без гарантий».</span></p>"
    )


def page_footer(d: SimpleNamespace, extra: str = "") -> str:
    return (
        "<footer><span>hub не проксирует и не хранит твои данные. "
        "Исходники открыты, формула оценки публичная и пересчитываемая."
        + extra
        + '</span><span class="m">' + e(d.generation) + "</span></footer>"
    )


def landing_free(d: SimpleNamespace) -> str:
    """Поле «Free VPN для всех»: обещание бесплатности, доказанное границами."""
    note = (
        "в подписке " + nodes(d.verified) + " · " + places(len(d.countries))
        + " · обход " + e(stamp(d.last.get("at", ""))) + " UTC"
    )
    body = (
        '<div class="shell">' + rail("free") + '<div class="page"><div class="wrap">'
        + topbar(d, where="бесплатный реестр")
        + hero(
            d,
            title="Бесплатный VPN<br>без аккаунта<br>и без оплаты.",
            text="Хаб собирает публичные списки прокси, проверяет каждый узел и "
                 "отдаёт подписку, в которой остаются только те, через которые "
                 "действительно прошёл трафик. Платить не за что: серверы не "
                 "его, а работу по проверке он делает для всех.",
            primary="Получить подписку",
            secondary="Посмотреть пул",
            note=note,
        )
        # Подозрение снимается раньше доказательства: человек, который ищет
        # «бесплатный VPN», уже видел десяток приманок, и первое, что ему
        # нужно, — честный список того, чего здесь нет.
        + """
<section class="sec" aria-labelledby="what-h">
  <div class="sec-h">
    <h2 id="what-h">Что здесь значит «бесплатно»</h2>
    <span class="aside">без мелкого шрифта</span>
  </div>
  <div class="cols">
    <div class="yes">
      <h3>Вот это — да</h3>
      <ul>
        <li>Без аккаунта, почты и карты: подписка — это один URL</li>
        <li>Без лимита трафика со стороны хаба: ограничивает только сам узел</li>
        <li>Подписка обновляется сама, обход идёт каждые шесть часов</li>
        <li>Один URL на телефоне, компьютере и роутере</li>
        <li>Исходники открыты: правило отбора можно пересчитать</li>
      </ul>
    </div>
    <div class="no">
      <h3>А вот этого — нет</h3>
      <ul>
        <li>Своих серверов: узлы принадлежат их владельцам, а не хабу</li>
        <li>Гарантии скорости и того, что узел доживёт до утра</li>
        <li>Защиты от владельца узла: он видит, куда ты ходишь</li>
        <li>Гарантии для банка, почты и аккаунтов с деньгами</li>
        <li>Возврата денег: их не было</li>
      </ul>
    </div>
  </div>
  <p class="note">Бесплатно не потому, что щедро: хаб ничего не покупает и не
     продаёт. Он читает публичные списки, отсеивает мёртвое и отдаёт то, что
     осталось. Стоимость этой работы — сервер хаба и трафик на проверки.</p>
</section>
"""
        + pool_section(d)
        + """
<section class="sec" aria-labelledby="cull-h">
  <div class="sec-h">
    <h2 id="cull-h">Что происходит с узлом по дороге</h2>
    <span class="aside">последний обход · выжило """ + e(share(d.funnel.get("http", 0), d.funnel.get("raw", 0))) + """</span>
  </div>
  <p class="lede">Каждая ступень отсеивает по своей причине. Полоса заполнена
     на долю от предыдущей ступени, а не от входа: иначе после третьей ступени
     все полосы стали бы уже пикселя, и табло перестало бы показывать, где
     теряется больше всего.</p>
  """ + board(d) + """
</section>
"""
        + clients_section(d)
        + """
<section class="sec" aria-labelledby="faq-h">
  <div class="sec-h"><h2 id="faq-h">Вопросы, которые задают первыми</h2>
  <span class="aside">коротко</span></div>
"""
        + faq([
            ("Это правда бесплатно?",
             "Да. Ни аккаунта, ни карты: подписка — URL, который хаб отдаёт "
             "сразу. Стоимость работы покрывает владелец хаба, а не посетитель."),
            ("В чём подвох?",
             "В узлах. Их владельцы видят твой исходящий трафик и могут его "
             "читать, если нет TLS. Поэтому через такой VPN не входят в банк и "
             "почту, а используют его для чтения и обхода блокировок. Это "
             "граница, а не мелкий шрифт."),
            ("Это децентрализованный VPN?",
             "Нет. Децентрализованным называют VPN, где узлы принадлежат "
             "независимым операторам с собственной системой стимулов и "
             "проверок. Здесь узлы тоже чужие, но их никто не координирует: "
             "хаб — открытый реестр, который измеряет чужие серверы и не "
             "обещает между ними никакой общей гарантии."),
            ("Почему узлы умирают?",
             "Публичные прокси живут недолго: их закрывают, они перегружаются, "
             "у них истекает сертификат. Обход из шести проверок идёт каждые "
             "шесть часов, поэтому подписка догоняет изменения, но не мгновенно."),
            ("Хаб видит мой трафик?",
             "Нет. Трафик идёт от тебя прямо к узлу из подписки, а не через "
             "сервер хаба. Хаб знает только то, что кто-то скачал подписку; "
             "журналы загрузок сервер не ведёт."),
            ("Можно ли смотреть видео?",
             "Иногда. Скорость зависит от узла и его загрузки, и хаб её не "
             "гарантирует. Для стриминга обычно нужен выделенный сервер, а не "
             "публичный прокси."),
        ])
        + "</section>\n"
        + warning()
        + page_footer(d)
        + "</div></div></div>"
    )
    return doc("hub — бесплатный VPN из открытых узлов", body)


def landing_dollar(d: SimpleNamespace) -> str:
    """Поле «VPN за $1»: обещание цены, доказанное объяснением, за что она."""
    note = (
        nodes(d.verified) + " · " + places(len(d.countries))
        + " · обход " + e(stamp(d.last.get("at", ""))) + " UTC"
    )
    body = (
        '<div class="shell">' + rail("dollar") + '<div class="page"><div class="wrap">'
        + topbar(d, where="подписка")
        + hero(
            d,
            title="Один доллар<br>в месяц.<br>Серверы не<br>продаются.",
            text="Вы платите не за машины, которых у хаба нет, а за проверку: "
                 "шесть обходов в сутки и подписку, в которой остаются только "
                 "узлы, через которые действительно прошёл трафик.",
            primary="Оформить за $1",
            secondary="Что входит",
            note=note,
        )
        # Цена — главный артефакт этого варианта, поэтому она стоит на экране
        # числом, а не в тексте, и рядом с ней — расшифровка, за что.
        + """
<section class="sec" aria-labelledby="price-h">
  <div class="sec-h"><h2 id="price-h">Что покупается за доллар</h2>
  <span class="aside">без автопродления по умолчанию</span></div>
  <div class="price">
    <div>
      <div class="v">$1<small>/ месяц</small></div>
      <p class="sub">Один ключ. Без лимита трафика со стороны хаба — ограничивает
         только сам узел.</p>
    </div>
    <div>
      <dl>
        <dt>Проверка</dt>
        <dd>Шесть ступеней, каждые шесть часов: порт, TLS, конфиг ядра, реальный
            запрос через узел.</dd>
        <dt>Подписка</dt>
        <dd>Один URL для sing-box, Happ, Clash, v2rayNG и Karing. Группы по
            странам — там, где клиент их понимает.</dd>
        <dt>Страны</dt>
        <dd>Шард на страну: выбор страны в клиенте, а не список из четырёх
            «Финляндий».</dd>
        <dt>Чего в цене нет</dt>
        <dd>Своих серверов, гарантии скорости и обещания, что узел доживёт до
            утра. Это граница продукта, а не мелкий шрифт.</dd>
      </dl>
    </div>
  </div>
</section>
"""
        + pool_section(d)
        + """
<section class="sec" aria-labelledby="why-h">
  <div class="sec-h"><h2 id="why-h">Почему доллар, а не десять</h2>
  <span class="aside">из чего складывается</span></div>
  <p class="lede">Цена отражает то, что хаб делает: измерение. У него нет
     собственных серверов, отдела поддержки на двадцать человек и рекламного
     бюджета — нет и причины брать с пользователя больше. Обходы, хостинг хаба
     и трафик на проверки — вот весь набор затрат, и он не растёт от числа
     стран в подписке.</p>
  <p class="note">Доллар — не «дешёвый тариф» и не промо: это цена работы,
     которую видно на табло ниже. Если проверки станут дороже, честной будет
     другая цена, и она будет названа, а не спрятана в мелком шрифте.</p>
</section>

<section class="sec" aria-labelledby="cull-h">
  <div class="sec-h">
    <h2 id="cull-h">За что платится: воронка</h2>
    <span class="aside">последний обход · выжило """ + e(share(d.funnel.get("http", 0), d.funnel.get("raw", 0))) + """</span>
  </div>
  <p class="lede">Каждая ступень отсеивает по своей причине, и полоса заполнена
     на долю от предыдущей ступени. Это то, что куплено за доллар: чужие
     списки, приведённые к тем узлам, через которые действительно идёт трафик.</p>
  """ + board(d) + """
</section>
"""
        + clients_section(d)
        + """
<section class="sec" aria-labelledby="faq-h">
  <div class="sec-h"><h2 id="faq-h">Вопросы о цене</h2>
  <span class="aside">коротко</span></div>
"""
        + faq([
            ("Почему так дёшево?",
             "Потому что нечего продавать дорого: серверы не наши. Доллар "
             "оплачивает проверку и инфраструктуру реестра, а не машины. "
             "Подписка за десять долларов обещала бы гарантии, которых здесь "
             "нет."),
            ("Это безопасно?",
             "Соединение шифруется так же, как в любом VPN, — протоколы те же. "
             "Но узел чужой: его владелец видит исходящий трафик. Для банка и "
             "почты такой пул не годится, и мы говорим это прямо."),
            ("Это децентрализованный VPN?",
             "Нет. Это каталог чужих узлов с измерением, а не сеть с "
             "независимыми операторами и общей системой стимулов. Слово "
             "«децентрализованный» обещало бы доверие без посредника — здесь "
             "посредник как раз и есть, и это хаб."),
            ("Что будет, если узел умрёт?",
             "Подписка обновится после следующего обхода: он идёт каждые шесть "
             "часов. Между обходами клиент увидит узел, который уже не отвечает, "
             "и переключится на следующий — это свойство публичного пула."),
            ("Что если я перестану платить?",
             "Ключ перестаёт обновлять подписку. Уже скачанный список продолжит "
             "работать до тех пор, пока живы узлы в нём: хаб не может отозвать "
             "то, что уже лежит у клиента, и не делает вид, что может."),
            ("Гарантируете скорость?",
             "Нет. Скорость зависит от узла и его загрузки. Хаб измеряет, что "
             "трафик идёт, а не насколько быстро."),
        ])
        + "</section>\n"
        + warning()
        + page_footer(
            d,
            " Платишь за измерение, а не за серверы."
        )
        + "</div></div></div>"
    )
    return doc("hub — VPN за доллар в месяц", body)


def landing(d: SimpleNamespace) -> str:
    """Совместимость: старый вызов главной = вариант «бесплатно»."""
    return landing_free(d)


def landing_empty(d: SimpleNamespace) -> str:
    """Пустое состояние: «ещё не готово» — это порядок, а не ноль."""
    body = (
        '<div class="shell">' + rail("free") + '<div class="page"><div class="wrap">'
        + topbar(d, where="бесплатный реестр")
        + """
<section class="pier">
  <div><h1>Поколение ещё<br>не опубликовано.</h1></div>
  <div class="read">
    <p>Первый обход не закончился. Пул появится здесь после того, как конвейер
       проверит узлы и опубликует поколение: обычно это занимает до десяти минут
       после установки.</p>
    <div class="actions">
      <a class="btn primary" href="#">Проверить состояние</a>
      <a class="btn ghost" href="#">Как это работает</a>
    </div>
    <span class="meta-note">проверка каждые 6 ч · сейчас идёт первый прогон</span>
  </div>
</section>

<section class="sec" aria-labelledby="next-h">
  <div class="sec-h"><h2 id="next-h">Что произойдёт дальше</h2><span class="aside">порядок</span></div>
  <div class="board">
    <div class="board-row"><div class="k">Списки читаются<small>25 источников</small></div>
      <div class="n">—</div><div class="track"><i style="width:100%"></i></div><div class="d">идёт</div></div>
    <div class="board-row"><div class="k">Узлы проверяются<small>TCP · TLS · конфиг · трафик</small></div>
      <div class="n">—</div><div class="track"></div><div class="d">ждёт</div></div>
    <div class="board-row"><div class="k">Поколение публикуется<small>атомарно, с откатом</small></div>
      <div class="n">—</div><div class="track"></div><div class="d">ждёт</div></div>
  </div>
  <p class="note">Пока поколения нет, страна не показывается и подписка не
     выдаётся: пустой список выглядел бы как сломанный, а не как «ещё не готово».</p>
</section>

<section class="sec" aria-labelledby="pool-h">
  <div class="sec-h"><h2 id="pool-h">Где есть выход</h2><span class="aside">нет данных</span></div>
  """ + exits_map(d) + """
  <div class="empty-note">
    <h3>Стран пока нет</h3>
    <p>Это нормальное состояние новой установки. Страница обновится сама
       после публикации первого поколения; обход идёт каждые шесть часов.</p>
  </div>
</section>

<footer><span>hub не проксирует и не хранит твои данные.</span><span class="m">нет поколения</span></footer>
</div></div></div>"""
    )
    return doc("hub — поколение ещё не опубликовано", body)


# --------------------------------------------------------------------------- #
# состояние пула
# --------------------------------------------------------------------------- #


def status(d: SimpleNamespace) -> str:
    runs = d.runs[-18:]
    peak = max((r.get("http") or 0) for r in runs) if runs else 1
    best = max(runs, key=lambda r: r.get("http") or 0) if runs else None
    rows = []
    for r in reversed(runs):
        w = max(1.0, (r.get("http") or 0) / peak * 100)
        rows.append(
            '<div class="run">'
            f'<span class="at">{e(stamp(r.get("at", "")))}</span>'
            f'<span class="rail"><i class="{"best" if r is best else ""}" style="width:{w:.2f}%"></i></span>'
            f'<span class="n">{num(int(r.get("http") or 0))}</span>'
            f'<span class="p">{num(int(r.get("published") or 0))}</span>'
            "</div>"
        )

    gens = []
    for g in d.generations[:8]:
        cur = g.get("generation") == d.generation
        gens.append(
            "<tr>"
            f'<td><code>{e(g.get("generation", ""))}</code>'
            + (' <span class="state" data-s="ok">текущее</span>' if cur else "")
            + f'</td><td class="m">{e(stamp(g.get("at", "")))}</td>'
            f'<td class="num">{num(int(g.get("nodes") or 0))}</td>'
            f'<td class="num">{int(g.get("payloads") or 0)}</td></tr>'
        )

    body = (
        '<div class="shell">'
        + rail("status")
        + '<div class="page"><div class="wrap">'
        + topbar(d, where="состояние пула")
        + """
<section class="status-head">
  <h1>Что происходило на самом деле</h1>
  <p>Пул публичный и нестабильный по своей природе: узлы — чужие серверы, и они
     умирают. Эта страница показывает историю обходов, а не только число узлов
     сейчас, — чтобы разброс в разы не выглядел как поломка.</p>
</section>

<div class="readings" style="margin-bottom:34px">
  <div><div class="v live">""" + num(d.verified) + """</div><div class="k">""" + nodes(d.verified) + """ в подписке</div></div>
  <div><div class="v">""" + str(d.status_countries) + """</div><div class="k">""" + places(d.status_countries) + """ с точкой выхода</div></div>
  <div><div class="v">""" + e(dur(d.age_s)) + """</div><div class="k">с последнего обхода</div></div>
  <div><div class="v">""" + str(d.sources_on) + "/" + str(d.sources_on + d.sources_off) + """</div><div class="k">источников работают</div></div>
</div>

<section class="sec" style="margin-top:0">
  <div class="sec-h"><h2>Сколько узлов проходит все проверки</h2>
    <span class="aside">""" + str(len(d.runs)) + """ обходов</span></div>
  <div class="runs">
    <div class="run-head"><span>обход</span><span>прошло трафик</span>
      <span>узлов</span><span>опубл.</span></div>
    """ + "".join(rows) + """
    <div class="foot">Каждый столбик — один обход. Правый столбец — сколько
      узлов попало в подписку после этого обхода; он меньше, потому что
      публикуются только узлы, прошедшие все шесть проверок.</div>
  </div>
</section>

<section class="sec">
  <div class="sec-h"><h2>Публикации</h2><span class="aside">адресуются содержимым</span></div>
  <div class="tbl-wrap"><table class="tbl">
    <thead><tr><th>Поколение</th><th>Опубликовано</th>
      <th class="num">Узлов</th><th class="num">Payload-ов</th></tr></thead>
    <tbody>""" + "".join(gens) + """</tbody>
  </table></div>
  <p class="note">Одинаковый пул всегда даёт один и тот же номер поколения.
     Поэтому откат — это смена указателя, а не пересборка.</p>
</section>

<section class="sec">
  <div class="sec-h"><h2>Источники</h2>
    <span class="aside">""" + str(d.sources_on + d.sources_off) + """ всего</span></div>
  <div class="readings">
    <div><div class="v live">""" + str(d.sources_on) + """</div><div class="k">работают</div></div>
    <div><div class="v">""" + str(d.sources_off) + """</div><div class="k">отключены</div></div>
  </div>
  <p class="note">Источник отключается, если двадцать обходов подряд не отдал
     ничего. Адреса списков здесь не публикуются: иначе страница стала бы
     указателем в обход хаба.</p>
</section>

<footer><span>Только счётчики и время. Адресов узлов и URL источников здесь нет
   по построению.</span><span class="m">""" + e(d.generation) + """</span></footer>
</div></div></div>"""
    )
    return doc("hub — состояние пула", body)


def dur(s: int) -> str:
    if s < 90:
        return f"{s} с"
    if s < 5400:
        return f"{s / 60:.1f} мин".replace(".", ",")
    if s < 172800:
        return f"{s / 3600:.1f} ч".replace(".", ",")
    return f"{s / 86400:.1f} дн".replace(".", ",")


# --------------------------------------------------------------------------- #
# вход
# --------------------------------------------------------------------------- #


def login() -> str:
    body = """
<div class="login-shell">
  <main class="login">
    <a class="wordmark" href="#">hub<b>.</b></a>
    <h1>Вход в панель</h1>
    <p>Секрет оператора лежит в <code>/etc/hub/hub.env</code> как
       <code>HUB_BOT_SECRET</code>. Пользователя нет: это одна вахта, а не
       таблица аккаунтов.</p>
    <form>
      <label for="secret">Секрет оператора</label>
      <input id="secret" type="password" value="························" autocomplete="current-password">
      <button class="btn primary" type="submit">Войти</button>
    </form>
    <p class="foot">Панель доступна только с этой машины. Снаружи её закрывает
       nginx, внутри проверяется, что запрос пришёл с localhost.</p>
  </main>
</div>"""
    return doc("hub — вход", body)


# --------------------------------------------------------------------------- #
# панель оператора
# --------------------------------------------------------------------------- #


def admin_bar(d: SimpleNamespace) -> str:
    health = {"ok": ("ok", "данные свежие"), "stale": ("warn", "данные устарели")}.get(
        d.health, ("fail", "требует внимания")
    )
    return (
        '<div class="admin-bar">'
        '<div class="id"><b>hub<i>.</i></b><span>панель оператора</span></div>'
        '<div class="live"><span class="state" data-s="' + health[0] + '">'
        + health[1] + "</span><span>" + e(d.generation) + " · " + e(dur(d.age_s))
        + ' назад</span></div>'
        "</div>"
    )


def admin_nav(active: str) -> str:
    groups = [
        ("Смотреть", [("Обзор", "overview"), ("Страны", "countries"), ("Источники", "sources")]),
        ("Управлять", [("Ключи", "keys"), ("Поколения", "gens")]),
    ]
    out = []
    for title, items in groups:
        out.append(f'<div class="grp">{e(title)}</div>')
        for label, key in items:
            cur = " aria-current" if key == active else ""
            out.append(f'<a href="#"{cur}>{e(label)}</a>')
    return '<nav aria-label="Панель">' + "".join(out) + "</nav>"


def stat_rail(d: SimpleNamespace) -> str:
    cn = len(d.countries)
    return (
        '<div class="stat-rail">'
        f'<div><div class="v live">{num(d.verified)}</div><div class="k">в подписке сейчас</div></div>'
        f'<div><div class="v">{num(d.known)}</div><div class="k">узлов в индексе</div></div>'
        f'<div><div class="v">{cn}</div><div class="k">стран с шардом</div></div>'
        f'<div><div class="v">{d.sources_on}</div><div class="k">источников работают</div></div>'
        "</div>"
    )


def admin(d: SimpleNamespace) -> str:
    rows = []
    for c in d.countries[:16]:
        w = max(2, round(c.n / d.top * 100))
        rows.append(
            "<tr>"
            f'<td><code>{e(c.code)}</code></td><td>{e(c.name)}</td>'
            f'<td class="num">{c.n}</td>'
            f'<td class="num">{share(c.n, d.verified)}</td>'
            f'<td><span class="gauge" style="display:block;height:4px;background:var(--panel-2)">'
            f'<i style="display:block;height:100%;width:{w}%;background:var(--live)"></i></span></td>'
            "</tr>"
        )

    srcs = []
    for s in d.sources[:8]:
        if not s.get("enabled"):
            st = '<span class="state" data-s="off">выключен</span>'
        elif s.get("disabled_soon"):
            st = '<span class="state" data-s="warn">отключится</span>'
        else:
            st = '<span class="state" data-s="ok">работает</span>'
        srcs.append(
            f'<tr><td><div class="url">{e(s.get("url", ""))}</div></td>'
            f"<td>{st}</td>"
            f'<td class="num">{int(s.get("rounds") or 0)}</td>'
            f'<td class="num">{int(s.get("empty_rounds") or 0)}</td>'
            f'<td class="m">{e(stamp(s.get("last_ok", "")))}</td></tr>'
        )

    body = (
        admin_bar(d)
        + '<div class="admin">'
        + admin_nav("overview")
        + '<main><div class="sec" style="margin-top:0">'
        + '<div class="sec-h"><h2>Обзор</h2><span class="aside">поколение '
        + e(d.generation)
        + "</span></div>"
        + stat_rail(d)
        + "</div>"
        + '<div class="sec"><div class="sec-h"><h2>Воронка последнего обхода</h2>'
        + f'<span class="aside">{e(stamp(d.last.get("at", "")))}</span></div>'
        + board(d)
        + '<p class="note">Каждая ступень отсеивает по своей причине: мёртвый '
        + "порт, просроченный сертификат, конфиг, который не приняло ядро, "
        + "и узел, через который не пошёл ни один запрос.</p></div>"
        + '<div class="sec"><div class="sec-h"><h2>Страны</h2>'
        + f'<span class="aside">{len(d.countries)} шардов</span></div>'
        + '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Код</th>'
        + '<th>Страна</th><th class="num">Узлов</th><th class="num">Доля</th>'
        + "<th>Распределение</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div></div>"
        + '<div class="sec"><div class="sec-h"><h2>Источники</h2>'
        + f'<span class="aside">{len(d.sources)} в списке</span></div>'
        + '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Источник</th>'
        + '<th>Состояние</th><th class="num">Обходов</th>'
        + '<th class="num">Пустых подряд</th><th>Последний успех</th></tr></thead><tbody>'
        + "".join(srcs)
        + "</tbody></table></div>"
        + '<p class="note">Источник отключается после двадцати пустых обходов '
        + "подряд — тот же порог, что применяет загрузчик.</p></div>"
        + "</main></div>"
    )
    return doc("hub — панель оператора", body, cls="admin-doc")


def keys(d: SimpleNamespace) -> str:
    toks = []
    for t in d.tokens:
        active = t.get("status") == "active"
        toks.append(
            "<tr>"
            f'<td><code>{e(t.get("id", ""))}</code></td>'
            f'<td>{e(t.get("label") or "—")}</td>'
            f'<td>{e("телеграм" if t.get("source") == "bot" else "панель")}</td>'
            f'<td><span class="state" data-s="{"ok" if active else "off"}">'
            f'{e("активен" if active else "отозван")}</span></td>'
            f'<td class="m">{e(stamp(t.get("created_at", "")))}</td>'
            "<td>" + ('<button class="btn danger mini">отозвать</button>' if active else "") + "</td>"
            "</tr>"
        )

    body = (
        admin_bar(d)
        + '<div class="admin">'
        + admin_nav("keys")
        + """<main>
<div class="sec" style="margin-top:0">
  <div class="sec-h"><h2>Ключи</h2><span class="aside">ключ показывается один раз</span></div>
  <form class="issue">
    <input placeholder="метка — чтобы через месяц понять, чей это ключ" aria-label="Метка ключа">
    <button class="btn primary" type="submit">Выдать ключ</button>
  </form>
  <p class="note">В базе хранится только SHA-256 ключа. Восстановить выданный
     ключ нельзя — ни вами, ни нами; это не ограничение интерфейса, а свойство
     хранилища.</p>
  <div class="receipt">
    <div class="rk">Ключ выдан. Скопируйте сейчас — второй раз показать нельзя.</div>
    <div class="rv">hb_7Kq2v9LmXa4TfR8sNc3PeW6yBd1GjHsU</div>
    <div class="rk">Ссылка для клиента</div>
    <div class="ru">https://193.34.212.154:8444/sub/hb_7Kq2v9LmXa4TfR8sNc3PeW6yBd1GjHsU</div>
    <div class="rk2">метка: happ-verify · источник: панель · срок: бессрочно</div>
  </div>
</div>

<div class="sec">
  <div class="sec-h"><h2>Выданные ключи</h2><span class="aside">""" + str(len(d.tokens)) + """ всего</span></div>
  <div class="tbl-wrap"><table class="tbl"><thead><tr><th>ID</th><th>Метка</th>
    <th>Источник</th><th>Статус</th><th>Выдан</th><th></th></tr></thead>
    <tbody>""" + "".join(toks) + """</tbody></table></div>
  <p class="note">Показаны первые двенадцать символов дайджеста: этого хватает,
     чтобы отличить два ключа при отзыве, и недостаточно, чтобы ключ
     восстановить.</p>
</div>

<div class="sec">
  <div class="sec-h"><h2>Если ключ потерян</h2><span class="aside">отзыв и выдача</span></div>
  <div class="empty-note">
    <h3>Выпустите новый</h3>
    <p>Отзовите старый ключ — он перестанет работать сразу — и выдайте новый.
       Подписка у клиента — это URL с ключом внутри, поэтому после отзыва её
       нужно заменить на новую.</p>
  </div>
</div>
</main></div>"""
    )
    return doc("hub — ключи", body, cls="admin-doc")
