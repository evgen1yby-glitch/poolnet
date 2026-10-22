"""Направление B — «Атлас выходов»: экраны.

Общая структура с направлением A (те же экраны, те же данные), но другой
ответ на вопрос «что здесь главное». У A главное — табло отсева; у B — карта
измеренных точек выхода. Поэтому здесь герой страницы не заголовок с кнопкой,
а карта, а заголовок её комментирует.
"""

from __future__ import annotations

import html
import math
from types import SimpleNamespace

from data import PROTO_CLIENT, STAGES, nodes, num, places, share
from worldpath import LAND_PATH


def e(s) -> str:
    return html.escape(str(s), quote=True)


def doc(title: str, body: str, *, cls: str = "") -> str:
    return (
        '<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{e(title)}</title>\n"
        "<link rel=\"stylesheet\" href=\"b.css\">\n</head>\n"
        f'<body class="{cls}">\n{body}\n</body>\n</html>\n'
    )


def stamp(iso: str) -> str:
    if not iso or len(iso) < 16:
        return "—"
    return iso[8:10] + "." + iso[5:7] + " " + iso[11:16]


def dur(s: int) -> str:
    if s < 90:
        return f"{s} с"
    if s < 5400:
        return f"{s / 60:.1f} мин".replace(".", ".")
    if s < 172800:
        return f"{s / 3600:.1f} ч"
    return f"{s / 86400:.1f} дн"


import maplab  # noqa: E402  (общая расстановка подписей карты)
from geo import project  # noqa: E402  (общая геометрия с картой направления A)


def exits_form(n: int) -> str:
    """Форма слова «выход» при числе стран: 21 выход, 22 выхода, 29 выходов."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return "выход"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "выхода"
    return "выходов"


#: Карта атласа вдвое уже приборной — она стоит в полосе рядом с текстом, а
#: не во всю ширину. Поэтому и порог подписей ниже; то же число стоит в
#: `@container` в `b.css`.
LABEL_MIN = 500.0
LABEL_ASPECT = 0.4


def map_box(d: SimpleNamespace, *, empty: bool = False) -> str:
    # Подписи ставит общий `maplab`, тот же, что в направлении A. Атлас
    # подписывает больше точек, чем приборная карта, но принцип один: подпись
    # ставится только туда, где она не закрывает ни точку, ни другую подпись.
    # Раньше здесь подписывались все 29 стран — на карте шириной 623 px это
    # давало 23 наложенные пары на десктопе и 125 на телефоне, то есть
    # подписи перекрывали ровно те точки, которые объясняли.
    projects = [(c, project(c.code)) for c in d.countries]
    projects = [(c, p) for c, p in projects if p]
    named = maplab.place(
        [(c.code, p[0], p[1], (6 + 11 * math.sqrt(c.n / max(1, d.top))) / 2)
         for c, p in projects],
        [c.code for c, _ in projects],
        min_width=LABEL_MIN,
        aspect=LABEL_ASPECT,
        char_w=5.76,  # 0.56 rem с трекингом .02em на два знака
    )
    dots = []
    for c, p in projects:
        size = 6 + 11 * math.sqrt(c.n / max(1, d.top))
        small = " data-small" if c.n < 3 else ""
        side = named.get(c.code)
        lab = f' data-side="{side}"' if side else ""
        dots.append(
            f'<span class="dot" data-c="{e(c.code)}"{small}{lab} '
            f'style="left:{p[0]:.2f}%;'
            f'top:{p[1]:.2f}%;width:{size:.0f}px;height:{size:.0f}px" '
            f'title="{e(c.name)} — {e(nodes(c.n))}"></span>'
        )
    if empty:
        dots = [
            '<div class="empty-map" style="border:0;background:none;position:absolute;inset:0">'
            "<p>Точек нет: ни один узел ещё не прошёл проверку. Атлас заполнится "
            "после первого обхода — он идёт каждые шесть часов.</p></div>"
        ]
    # Берег — система отсчёта, а не измерение: он нарисован цветом сетки, и
    # подпись это говорит. Точка на карте значит «отсюда вышел проверенный
    # запрос»; берег значит только «вот где это на свете». Смешать их в одном
    # цвете значило бы выдать карту за данные хаба.
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
        "<span>берег — ориентир из Natural Earth, не измерение хаба: "
        "координаты узлов он не знает</span></p>"
    )


def legend(d: SimpleNamespace) -> str:
    return (
        '<div class="legend"><div class="in">'
        f"<span><b>hub</b> · публичный реестр выходов</span>"
        f'<span class="right"><span>обход {e(stamp(d.last.get("at", "")))} UTC</span>'
        f"<span>{nodes(d.verified)}</span>"
        f"<span>{places(len(d.countries))}</span>"
        f"<span>обновление 6 ч</span></span>"
        "</div></div>"
    )


def masthead(active: str = "landing") -> str:
    items = [("Пул", "landing"), ("Состояние", "status"), ("Клиенты", "clients")]
    nav = "".join(
        f'<a href="#"{" aria-current" if key == active else ""}>{e(label)}</a>'
        for label, key in items
    )
    return (
        '<header class="masthead"><a class="wordmark" href="#">hub<b>.</b></a>'
        f'<nav aria-label="Разделы">{nav}</nav></header>'
    )


def profile(d: SimpleNamespace) -> str:
    """Воронка столбиками. Высота — логарифм, и это подписано."""
    bars, xs = [], []
    counts = [max(1, d.funnel.get(k, 0)) for k, _, _ in STAGES]
    logs = [math.log10(c) for c in counts]
    lo, hi = min(logs), max(logs)
    for (key, label, hint), n, lg in zip(STAGES, counts, logs):
        h = 8 + (lg - lo) / max(0.0001, hi - lo) * 86
        live = " live" if key == "http" else ""
        bars.append(
            f'<div class="col{live}"><span class="n">{num(n)}</span>'
            f'<span class="bar" style="height:{h:.1f}%"></span></div>'
        )
        xs.append(f'<div>{e(label)}<span>{e(hint)}</span></div>')
    return (
        '<div class="profile"><div class="bars">'
        + "".join(bars)
        + '</div><div class="x">'
        + "".join(xs)
        + '</div><div class="scale"><span>высота столбика — логарифм числа, '
        "иначе последняя ступень была бы ниже пикселя</span>"
        f"<span>выживаемость {share(d.funnel.get('http', 0), d.funnel.get('raw', 0))}</span>"
        "</div></div>"
    )


def atlas(d: SimpleNamespace) -> str:
    if not d.countries:
        return (
            '<div class="empty-note"><h3>Оглавление пустое</h3>'
            "<p>Стран нет, пока ни один узел не прошёл все проверки. Это не "
            "ошибка: так выглядит новая установка до первого обхода.</p></div>"
        )
    rows = []
    for c in d.countries:
        rows.append(
            f'<a class="row" href="#" title="{e(c.name)} — {e(nodes(c.n))}">'
            f'<span class="cc">{e(c.code)}</span><span class="nm">{e(c.name)}</span>'
            f'<span class="ld"></span><span class="ct">{c.n}</span></a>'
        )
    return '<div class="atlas">' + "".join(rows) + "</div>"


def sec(no: str, title: str, aside: str, body: str) -> str:
    return (
        f'<section class="sec"><div class="sec-h"><span class="no">{e(no)}</span>'
        f"<h2>{e(title)}</h2><span class=\"aside\">{e(aside)}</span></div>{body}</section>"
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]]) -> str:
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


# --------------------------------------------------------------------------- #
# главная
# --------------------------------------------------------------------------- #


def landing(d: SimpleNamespace) -> str:
    body = (
        legend(d)
        + '<div class="wrap">'
        + masthead("landing")
        + """
<section class="hero">
  <div class="title">
    <h1>""" + num(len(d.countries)) + """<br>измеренных <b>""" + exits_form(len(d.countries)) + """</b>.</h1>
    <p class="stand">Хаб читает публичные списки прокси и проверяет каждый узел.
       Здесь остаются только те, через которые действительно прошёл трафик, —
       и только те страны, где такой узел есть. Аккаунт не нужен.</p>
    <div class="cta">
      <a class="btn" href="#">Получить подписку</a>
      <a class="btn line" href="#atlas">Открыть атлас</a>
    </div>
  </div>
  <div class="map">""" + map_box(d) + """</div>
</section>

""" + sec("01", "Откуда берутся точки", "последний обход",
          '<p class="lede">Шесть проверок подряд. Узел, не прошедший любую из '
          'них, в атлас не попадает — поэтому точка на карте означает не '
          '«кто-то заявил страну», а «отсюда действительно вышел запрос».</p>'
          + profile(d))

        + sec("02", "Оглавление атласа", f"{places(len(d.countries))}",
              '<p class="lede">Страна измерена через <code>cdn-cgi/trace</code>, '
              'а не взята из имени хоста. Подделанная страна снижает оценку '
              'узла и в список не попадает.</p>' + atlas(d))

        + sec("03", "Какими протоколами", f"{num(d.known)} в индексе",
              '<dl class="facts">' + "".join(
                  f"<dt>{e(p.name)}</dt><dd>{nodes(p.n)} · {e(PROTO_CLIENT.get(p.name, '—'))}</dd>"
                  for p in d.protocols
              ) + "</dl>"
              '<p class="note">В индекс попадает всё, что удалось разобрать; в '
              'подписку — только прошедшее проверки. Числа не совпадают, и не '
              'должны.</p>')

        + sec("04", "Куда вставить подписку", "один URL",
              '<div class="clients">'
              "<div><b>sing-box · Happ</b><span>JSON с группами по странам</span></div>"
              "<div><b>v2rayNG · v2rayN</b><span>base64-список</span></div>"
              "<div><b>Clash · Mihomo</b><span>YAML с группами</span></div>"
              "<div><b>Karing · Shadowrocket</b><span>базовый список</span></div>"
              "</div>"
              '<p class="note">Клиентам без группировки — <code>?unique=1</code>: '
              "один узел на страну.</p>")

        + '<p class="warn"><b>Узлы чужие.</b> Проверяется доступность и то, что '
          "трафик идёт, — не честность владельца. Не вводите пароли и не "
          "проводите платежи через узлы. Бесплатно здесь означает «без гарантий».</p>"

        + "<footer><span>hub не проксирует и не хранит трафик. Исходники открыты, "
          "формула оценки публичная.</span>"
          f'<span class="m">{e(d.generation)}</span></footer>'
        + "</div>"
    )
    return doc("hub — атлас измеренных выходов", body)


def landing_empty(d: SimpleNamespace) -> str:
    body = (
        legend(d)
        + '<div class="wrap">'
        + masthead("landing")
        + """
<section class="hero">
  <div class="title">
    <h1>Атлас ещё<br>не нанесён.</h1>
    <p class="stand">Первый обход не закончился. Точки появятся, когда конвейер
       проверит узлы и опубликует поколение, — обычно в пределах десяти минут
       после установки.</p>
    <div class="cta">
      <a class="btn" href="#">Состояние обхода</a>
      <a class="btn line" href="#">Как это работает</a>
    </div>
  </div>
  <div class="map">""" + map_box(d, empty=True) + """</div>
</section>

""" + sec("01", "Что произойдёт дальше", "порядок",
          '<div class="profile"><div class="bars">'
          '<div class="col"><span class="n">идёт</span><span class="bar" style="height:42%"></span></div>'
          '<div class="col"><span class="n">ждёт</span><span class="bar" style="height:8%"></span></div>'
          '<div class="col"><span class="n">ждёт</span><span class="bar" style="height:8%"></span></div>'
          '</div><div class="x"><div>Списки читаются<span>25 источников</span></div>'
          '<div>Узлы проверяются<span>TCP · TLS · конфиг · трафик</span></div>'
          '<div>Поколение публикуется<span>атомарно, с откатом</span></div>'
          '</div></div>'
          '<p class="note">Пока поколения нет, страна не показывается и ключ не '
          "выдаётся: пустой список выглядел бы как сломанный, а не как «ещё не "
          "готово».</p>")

        + sec("02", "Оглавление атласа", "пусто",
              '<div class="empty-note"><h3>Стран пока нет</h3>'
              "<p>Страница обновится сама после первой публикации. Обход идёт "
              "каждые шесть часов, первый запускается сразу после установки.</p></div>")

        + "<footer><span>hub не проксирует и не хранит трафик.</span>"
          '<span class="m">нет поколения</span></footer>'
        + "</div>"
    )
    return doc("hub — атлас ещё не нанесён", body)


# --------------------------------------------------------------------------- #
# состояние пула
# --------------------------------------------------------------------------- #


def status(d: SimpleNamespace) -> str:
    runs = d.runs[-18:]
    peak = max((r.get("http") or 0) for r in runs) if runs else 1
    best = max(runs, key=lambda r: r.get("http") or 0) if runs else None
    plot = []
    for r in runs:
        h = max(2.0, (r.get("http") or 0) / peak * 100)
        cls = ' class="best"' if r is best else ""
        plot.append(f'<div{cls}><i style="height:{h:.1f}%"></i></div>')

    gens = [
        [
            f'<code>{e(g.get("generation", ""))}</code>'
            + (' <span class="state" data-s="ok">текущее</span>'
               if g.get("generation") == d.generation else ""),
            f'<span class="m">{e(stamp(g.get("at", "")))}</span>',
            num(int(g.get("nodes") or 0)),
            str(int(g.get("payloads") or 0)),
        ]
        for g in d.generations[:8]
    ]

    body = (
        legend(d)
        + '<div class="wrap">'
        + masthead("status")
        + """
<section class="status-head">
  <h1>Что происходило на самом деле</h1>
  <p>Пул публичный и нестабильный по природе: узлы — чужие серверы, и они
     умирают. Здесь история обходов, а не только число узлов сейчас.</p>
</section>

<div class="readings">
  <div><div class="v live">""" + num(d.verified) + """</div><div class="k">""" + nodes(d.verified) + """ в подписке</div></div>
  <div><div class="v">""" + str(d.status_countries) + """</div><div class="k">""" + places(d.status_countries) + """ с выходом</div></div>
  <div><div class="v">""" + e(dur(d.age_s)) + """</div><div class="k">с последнего обхода</div></div>
  <div><div class="v">""" + f"{d.sources_on}/{d.sources_on + d.sources_off}" + """</div><div class="k">источников работают</div></div>
</div>

<section class="sec" style="margin-top:0">
  <div class="sec-h"><span class="no">01</span><h2>Сколько узлов проходит все проверки</h2>
    <span class="aside">""" + str(len(d.runs)) + """ обходов</span></div>
  <div class="history">
    <div class="plot">""" + "".join(plot) + """</div>
    <div class="axis"><span>""" + e(stamp(runs[0]["at"])) + """</span>
      <span>""" + e(stamp(runs[-1]["at"])) + """</span></div>
    <p class="foot">Каждый столбик — один обход. Тёмный — лучший за период
      (""" + str(max(int(r.get("http") or 0) for r in runs)) + """ узлов). Разброс в разы — норма
      для публичного пула, а не сбой.</p>
  </div>
</section>

<section class="sec">
  <div class="sec-h"><span class="no">02</span><h2>Публикации</h2>
    <span class="aside">адресуются содержимым</span></div>
  """ + table(
      [("Поколение", ""), ("Опубликовано", ""), ("Узлов", "num"), ("Payload-ов", "num")],
      gens,
  ) + """
  <p class="note">Одинаковый пул всегда даёт один номер поколения, поэтому
     откат — смена указателя, а не пересборка.</p>
</section>

<section class="sec">
  <div class="sec-h"><span class="no">03</span><h2>Источники</h2>
    <span class="aside">""" + str(d.sources_on + d.sources_off) + """ всего</span></div>
  <dl class="facts">
    <dt>работают</dt><dd>""" + str(d.sources_on) + """</dd>
    <dt>отключены</dt><dd>""" + str(d.sources_off) + """ — двадцать пустых обходов подряд</dd>
  </dl>
  <p class="note">Адреса списков здесь не публикуются: иначе страница стала бы
     указателем в обход хаба.</p>
</section>

<footer><span>Только счётчики и время. Адресов узлов и URL источников нет по
   построению.</span><span class="m">""" + e(d.generation) + """</span></footer>
</div>"""
    )
    return doc("hub — состояние пула", body)


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
       <code>HUB_BOT_SECRET</code>. Пользователя нет: это одна вахта.</p>
    <form>
      <label for="secret">Секрет оператора</label>
      <input id="secret" type="password" value="························">
      <button class="btn" type="submit">Войти</button>
    </form>
    <p class="foot">Панель доступна только с этой машины: снаружи её закрывает
       nginx, внутри проверяется, что запрос пришёл с localhost.</p>
  </main>
</div>"""
    return doc("hub — вход", body)


# --------------------------------------------------------------------------- #
# панель оператора
# --------------------------------------------------------------------------- #


def admin_bar(d: SimpleNamespace) -> str:
    health = {"ok": ("ok", "свежее"), "stale": ("warn", "устарело")}.get(
        d.health, ("fail", "нет данных")
    )
    return (
        '<div class="admin-bar"><div class="id"><b>hub<i>.</i></b>'
        "<span>панель оператора</span></div>"
        '<div class="live"><span class="state" data-s="' + health[0] + '">'
        + health[1] + "</span><span>" + e(d.generation) + " · " + e(dur(d.age_s))
        + "</span></div></div>"
    )


def admin_tabs(active: str) -> str:
    items = [("Обзор", "overview"), ("Страны", "countries"), ("Источники", "sources"),
             ("Ключи", "keys"), ("Поколения", "gens")]
    return (
        '<nav class="tabs" aria-label="Панель">'
        + "".join(
            '<a href="#"%s>%s</a>'
            % (' aria-current="page"' if key == active else "", e(label))
            for label, key in items
        )
        + "</nav>"
    )


def stat_rail(d: SimpleNamespace) -> str:
    return (
        '<div class="stat-rail">'
        f'<div><div class="v live">{num(d.verified)}</div><div class="k">в подписке сейчас</div></div>'
        f'<div><div class="v">{num(d.known)}</div><div class="k">узлов в индексе</div></div>'
        f'<div><div class="v">{len(d.countries)}</div><div class="k">стран с шардом</div></div>'
        f'<div><div class="v">{d.sources_on}</div><div class="k">источников работают</div></div>'
        "</div>"
    )


def admin(d: SimpleNamespace) -> str:
    country_rows = [
        [
            f"<code>{e(c.code)}</code>",
            e(c.name),
            c.n,
            share(c.n, d.verified),
        ]
        for c in d.countries[:18]
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
            f'<div class="url">{e(s.get("url", ""))}</div>',
            st,
            str(int(s.get("rounds") or 0)),
            str(int(s.get("empty_rounds") or 0)),
        ])

    body = (
        admin_bar(d)
        + '<div class="admin">'
        + admin_tabs("overview")
        + '<div class="sec-h" style="border-top:0;padding-top:0"><span class="no">01</span>'
        f'<h2>Поколение</h2><span class="aside">{e(d.generation)}</span></div>'
        + stat_rail(d)
        + '<section class="sec" style="margin-top:32px">'
        + '<div class="sec-h"><span class="no">02</span><h2>Воронка обхода</h2>'
        + f'<span class="aside">{e(stamp(d.last.get("at", "")))}</span></div>'
        + profile(d)
        + '<p class="note">Порядок проверок не случаен: каждая следующая дороже '
        + "предыдущей, поэтому мёртвый порт отсекается до рукопожатия, а "
        + "трафик проверяется только у тех, кто дошёл.</p></section>"
        + '<div class="two"><section class="sec" style="margin-top:34px">'
        + '<div class="sec-h"><span class="no">03</span><h2>Страны</h2>'
        + f'<span class="aside">{len(d.countries)} шардов</span></div>'
        + table([("Код", ""), ("Страна", ""), ("Узлов", "num"), ("Доля", "num")], country_rows)
        + "</section>"
        + '<section class="sec" style="margin-top:34px">'
        + '<div class="sec-h"><span class="no">04</span><h2>Источники</h2>'
        + f'<span class="aside">{len(d.sources)} в списке</span></div>'
        + table([("Адрес", ""), ("Состояние", ""), ("Обходов", "num"), ("Пустых", "num")], src_rows)
        + "</section></div>"
        + "</div>"
    )
    return doc("hub — панель оператора", body, cls="admin-doc")


def keys(d: SimpleNamespace) -> str:
    rows = []
    for t in d.tokens:
        active = t.get("status") == "active"
        rows.append([
            f'<code>{e(t.get("id", ""))}</code>',
            e(t.get("label") or "—"),
            e("телеграм" if t.get("source") == "bot" else "панель"),
            f'<span class="state" data-s="{"ok" if active else "off"}">'
            f'{e("активен" if active else "отозван")}</span>',
            f'<span class="m">{e(stamp(t.get("created_at", "")))}</span>',
            '<button class="btn mini danger">отозвать</button>' if active else "",
        ])

    body = (
        admin_bar(d)
        + '<div class="admin">'
        + admin_tabs("keys")
        + '<section class="sec" style="margin-top:28px">'
        + '<div class="sec-h" style="border-top:0;padding-top:0"><span class="no">01</span>'
        + "<h2>Выдать ключ</h2><span class=\"aside\">показывается один раз</span></div>"
        + '<form class="issue"><div style="flex:1 1 260px"><label for="lbl">'
        + "Метка — чтобы через месяц понять, чей это ключ</label>"
        + '<input id="lbl" placeholder="happ-verify"></div>'
        + '<button class="btn" type="submit">Выдать ключ</button></form>'
        + '<p class="note">В базе хранится только SHA-256 ключа. Восстановить '
        + "выданный ключ нельзя — ни вам, ни нам; это свойство хранилища, а не "
        + "ограничение интерфейса.</p>"
        + '<div class="slip"><div class="k">Ключ выдан. Скопируйте сейчас — '
        + "второй раз показать нельзя.</div>"
        + '<div class="v">hb_7Kq2v9LmXa4TfR8sNc3PeW6yBd1GjHsU</div>'
        + '<div class="k">Ссылка для клиента</div>'
        + '<div class="u">https://193.34.212.154:8444/sub/hb_7Kq2v9LmXa4TfR8sNc3PeW6yBd1GjHsU</div>'
        + '<div class="meta"><span>метка: happ-verify</span><span>источник: панель</span>'
        + "<span>срок: бессрочно</span></div></div>"
        + "</section>"
        + '<section class="sec"><div class="sec-h"><span class="no">02</span>'
        + f'<h2>Выданные ключи</h2><span class="aside">{len(d.tokens)} всего</span></div>'
        + table([("ID", ""), ("Метка", ""), ("Источник", ""), ("Статус", ""),
                 ("Выдан", ""), ("", "")], rows)
        + '<p class="note">Показаны двенадцать символов идентификатора: этого '
        + "достаточно, чтобы отличить два ключа при отзыве, и недостаточно, "
        + "чтобы восстановить ключ.</p></section>"
        + '<section class="sec"><div class="sec-h"><span class="no">03</span>'
        + '<h2>Если ключ потерян</h2><span class="aside">отзыв и выдача</span></div>'
        + '<div class="empty-note"><h3>Выпустите новый</h3>'
        + "<p>Отзовите старый — он перестанет работать сразу — и выдайте новый. "
        + "Подписка у клиента это URL с ключом внутри, поэтому после отзыва её "
        + "нужно заменить.</p></div></section>"
        + "</div>"
    )
    return doc("hub — ключи", body, cls="admin-doc")
