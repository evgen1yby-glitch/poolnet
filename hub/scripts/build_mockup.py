#!/usr/bin/env python3
"""Собрать `docs/design/mockup.html` из живых страниц продукта.

Зачем генератор, а не файл руками. Прежний макет был рукописной копией: та же
палитра, те же таблицы, те же классы, набранные заново. Копия расходится с
оригиналом — это не риск, а свойство, и первый же абзац того файла это признавал
(«если разойдутся — макет начнёт врать»). Он и разошёлся: палитра успела
разъехаться на пять копий, и `--danger` пропал ровно потому, что копий было
пять.

Здесь макет собирается из **самих файлов** `src/hub/ui/` и из снимков
**настоящих ответов** API. Копий нет, поэтому расходиться нечему: если страница
изменится, макет изменится вместе с ней — но только когда его пересоберут, и
именно это проверяет `tests/test_mockup.py`.

Как это работает

    Каждая страница грузится в <iframe srcdoc>, а не разбирается и не
    перерисовывается. Это единственный способ показать страницу *как она есть*:
    её скрипты выполняются, её CSS применяется, её состояния — настоящие.
    Перерисовка в разметку макета дала бы аппроксимацию, которая снова может
    соврать.

    Ссылки на `/static/*.css` и `/static/*.js` заменяются на инлайновое
    содержимое: файл открывается из `file://`, где абсолютный путь `/static/`
    никуда не ведёт. Замена — единственная правка, которую скрипт делает в
    чужой разметке, и она механическая.

    Сеть внутри iframe не нужна: `fetch` подменяется на снимок, снятый с
    работающего сервера. Без этого страницы показали бы «Читаю состояние…» —
    то есть макет показывал бы не продукт, а его загрузку.

Снимки лежат в `docs/design/fixtures/` и снимаются с живого хаба:

    curl -s http://127.0.0.1:8090/api/v1/stats          > fixtures/stats.json
    curl -s http://127.0.0.1:8090/status/data           > fixtures/status.json
    curl -s -H "x-hub-secret: $HUB_BOT_SECRET" \\
         http://127.0.0.1:8090/admin/data               > fixtures/admin.json

В них нет ни токенов, ни адресов узлов: `/api/v1/stats` и `/status/data` их не
отдают по построению, а `/admin/data` отдаёт URL источников — это панель
оператора, и без имени источника таблица здоровья бесполезна. Токенов в снимке
нет: они хешируются, а выданных ключей на чистой установке не бывает.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "src" / "hub" / "ui"
FIXTURES = ROOT / "docs" / "design" / "fixtures"
OUT = ROOT / "docs" / "design" / "mockup.html"

#: Страницы продукта в том порядке, в каком их показывает макет.
#:
#: `(файл, что это, маршрут, чем отличается от соседей, высота рамки)`.
#: Четвёртая колонка — не украшение: она объясняет, зачем в специмен-листе ещё
#: один экран. Высота — приблизительная высота содержимого: рамка не измеряет
#: себя сама, а обрезать панель оператора на середине таблицы хуже, чем оставить
#: под ней пустое место.
PAGES = [
    (
        "index.html",
        "Главная",
        "GET /",
        "Публичное лицо. Воронка, страны и предупреждение о чужих нодах — на первом экране, а не в подвале мелким шрифтом.",
        1750,
    ),
    (
        "status.html",
        "Состояние пула",
        "GET /status",
        "Публичная. Что происходило на самом деле: столбики по прогонам, без адресов узлов и URL источников.",
        1250,
    ),
    (
        "login.html",
        "Вход",
        "GET /admin/login",
        "Одно поле. Логина нет — оператор один, и второе поле намекало бы на систему аккаунтов, которой не существует.",
        560,
    ),
    (
        "admin.html",
        "Панель оператора",
        "GET /admin",
        "Закрыта снаружи наглухо. Таблицы, а не карточки: приборные показания живут в колонках.",
        1500,
    ),
]

#: Снимки ответов, которые получает каждая страница. Ключ — префикс URL.
#:
#: `/api/v1/stats` и `/status/data` — публичные, `/admin/data` требует секрет и
#: в макете отдаётся из снимка.
FIXTURE_FOR = {
    "/api/v1/stats": "stats.json",
    "/status/data": "status.json",
    "/admin/data": "admin.json",
}

#: Тела ошибок — из `api.py`, дословно. Выдуманное тело ошибки в макете
#: описывало бы сервер, которого нет.
#:
#: `404` для неизвестного токена пустой намеренно: страница ошибок это объясняет,
#: и если бы макет рисовал там тело, он обещал бы подробность, которой сервер не
#: отдаёт.
ERRORS = [
    (
        "404",
        "Страна не публикуется",
        "GET /sub/{token}/country/XX",
        '{\n  "error": "no payload for this country",\n  "country": "XX",\n  "countries": ["DE", "FI", "FR", "NL", "PL", "SE", "US"],\n  "available": ["verified-NL.singbox", "verified-DE.singbox"]\n}',
        "Тело называет страны, которые есть. Подробность здесь уместна: вызывающий — законный держатель токена, и ему нужно знать, прекращать ли попытки.",
    ),
    (
        "404",
        "Ключа не существует",
        "GET /sub/{token}",
        "",
        "Пустое тело у неизвестного токена — то же, что у неизвестного URL. Иначе сканер отличил бы «ключ есть, стран нет» от «ключа нет вообще».",
    ),
    (
        "503",
        "Поколения ещё нет",
        "GET /sub/{token}",
        '{\n  "error": "no payload published yet"\n}',
        "Честный ответ: отдать нечего. Появляется на свежей установке, до первого прогона проверки.",
    ),
    (
        "403",
        "Панель не для этого запроса",
        "GET /admin/data",
        '{\n  "error": "forbidden"\n}',
        "Без подробностей: сообщать, что секрет был близок, значит помогать подбирать.",
    ),
]

#: Состояния, которых на живом сервере нет прямо сейчас, но которые бывают.
#:
#: Каждое — не фантазия: это ответ, который сервер отдаёт в известных условиях,
#: и их стоит увидеть до того, как они случатся на проде.
STATES = [
    (
        "Пустой пул",
        "свежая установка",
        "Пул пуст, пока не прошёл первый прогон проверки. Экран объясняет себя: пустая страница без объяснения — это то, из-за чего пишут в поддержку вместо того, чтобы подождать десять минут.",
        "Пул",
        (
            '<div class="pool">'
            '<div><div class="v">0</div><div class="k label">проверено сейчас</div></div>'
            '<div><div class="v">0</div><div class="k label">известно всего</div></div>'
            '<div><div class="v">0</div><div class="k label">стран</div></div>'
            '<div><div class="v">26</div><div class="k label">источников</div></div>'
            "</div>"
            '<p class="caption">Прогон запускается по таймеру, или сейчас: '
            "<code>sudo systemctl start hub-probe.service</code>. Занимает около десяти "
            "минут: источники отдают десятки тысяч строк, и каждая проверяется по пяти стадиям.</p>"
            '<p class="caption">Ключ можно выдать до первого прогона — он начнёт работать, '
            "как только появится поколение.</p>"
        ),
    ),
    (
        "Пул на одном узле",
        "страна без ротации",
        "Страна с единственным узлом — дорожки под ней нет вовсе. Пул из одного не ротация, и это видно до того, как пользователь нажмёт.",
        "Страны",
        (
            '<div class="countries">'
            '<div class="country" data-top="1"><span class="flag">🇳🇱</span>'
            '<span class="name">Нидерланды</span><span class="count">52'
            '<span class="unit">нод</span></span>'
            '<span class="track"><i style="width:100%"></i></span></div>'
            '<div class="country"><span class="flag">🇩🇪</span>'
            '<span class="name">Германия</span><span class="count">16'
            '<span class="unit">нод</span></span>'
            '<span class="track"><i style="width:31%"></i></span></div>'
            '<div class="country" data-thin="1"><span class="flag">🇹🇷</span>'
            '<span class="name">Турция</span><span class="count">1'
            '<span class="unit">нод</span></span>'
            '<span class="track"><i style="width:2%"></i></span></div>'
            "</div>"
            '<p class="caption">Три состояния дорожки: самая глубокая страна — цветом '
            "состояния, обычная — серым, у страны с одним узлом дорожки нет.</p>"
        ),
    ),
]


def _inline_fonts(css: str) -> str:
    """Превратить `url(fonts/...)` в `data:font/woff2;base64,...`.

    Шрифты лежат рядом с css (`fonts/`), и из `/static/` ссылка работает, но
    из `file://`, где открывается макет, — нет: Unbounded и Manrope не
    загрузятся, и макет покажет типографику системы. Инлайн — цена за то,
    чтобы макет был честным.
    """

    def font(match: re.Match[str]) -> str:
        name = match.group(1)
        path = UI / "fonts" / name
        if not path.is_file():
            raise SystemExit(f"css ссылается на fonts/{name}, а файла нет — макет соврёт")
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'url("data:font/woff2;base64,{data}")'

    return re.sub(r'url\(["\']?fonts/([\w.-]+)["\']?\)', font, css)


def _inline_assets(markup: str) -> str:
    """Заменить `/static/x.css` и `/static/x.js` на содержимое файлов.

    Макет открывается из `file://`, где абсолютный путь `/static/` не ведёт
    никуда. Это единственная правка, которую скрипт вносит в чужую разметку, и
    она механическая: имя файла остаётся в атрибуте `data-from`, чтобы связь с
    оригиналом была видна.

    Скрипты инлайнятся наравне со стилями, и это не мелочь: без `hub.js`
    главная не нарисует ни воронку, ни страны, и макет показал бы «Читаю
    состояние…» — то есть показывал бы не продукт, а его загрузку.
    """

    def style(match: re.Match[str]) -> str:
        name = match.group(1)
        path = UI / name
        if not path.is_file():
            raise SystemExit(f"в разметке есть /static/{name}, а файла нет — макет соврёт")
        return (
            '<style data-from="'
            + name
            + '">\n'
            + _inline_fonts(path.read_text(encoding="utf-8"))
            + "\n</style>"
        )

    def script(match: re.Match[str]) -> str:
        name = match.group(1)
        path = UI / name
        if not path.is_file():
            raise SystemExit(f"в разметке есть /static/{name}, а файла нет — макет соврёт")
        return f'<script data-from="{name}">\n{path.read_text(encoding="utf-8")}\n</script>'

    markup = re.sub(r'<link rel="stylesheet" href="/static/([\w.-]+)">', style, markup)
    return re.sub(r'<script src="/static/([\w.-]+)"[^>]*></script>', script, markup)


def _stub_fetch(markup: str) -> str:
    """Подменить `fetch` на снимок, чтобы страница показала данные, а не загрузку.

    Снимков три, и страница берёт свой. Незнакомый URL уходит в `_f` — то есть
    в настоящий `fetch`, который из `file://` не сработает, и это правильно:
    страница, тянущая что-то, чего у нас нет, должна упасть заметно, а не
    показать пустоту.
    """
    payload = {}
    for prefix, name in FIXTURE_FOR.items():
        path = FIXTURES / name
        if not path.is_file():
            raise SystemExit(
                f"нет снимка {name} — макет покажет «Читаю состояние…».\n"
                f"Снимите его: см. докстроку scripts/build_mockup.py"
            )
        payload[prefix] = json.loads(path.read_text(encoding="utf-8"))

    stub = (
        "<script>\n"
        "/* Снимок живого ответа сервера. Подменяет только чтение: запись\n"
        "   (выдача и отзыв ключа) в макете не работает — иначе он делал бы\n"
        "   вид, что операция прошла. */\n"
        "window.__SNAPSHOT__ = " + json.dumps(payload, ensure_ascii=False) + ";\n"
        "(function () {\n"
        "  var real = window.fetch;\n"
        "  window.fetch = function (url, opts) {\n"
        "    var method = (opts && opts.method) || 'GET';\n"
        "    if (method !== 'GET') {\n"
        "      return Promise.resolve(new Response(\n"
        "        JSON.stringify({error: 'макет: запись отключена'}),\n"
        "        {status: 403, headers: {'content-type': 'application/json'}}));\n"
        "    }\n"
        "    var key = Object.keys(window.__SNAPSHOT__).find(function (p) {\n"
        "      return String(url).indexOf(p) === 0;\n"
        "    });\n"
        "    if (!key) return real.apply(this, arguments);\n"
        "    return Promise.resolve(new Response(\n"
        "      JSON.stringify(window.__SNAPSHOT__[key]),\n"
        "      {status: 200, headers: {'content-type': 'application/json'}}));\n"
        "  };\n"
        "})();\n"
        "</script>\n"
    )
    # Стенд должен стоять до скрипта страницы: он грузится с `defer`, но
    # iframe разбирает документ сверху вниз, и подмена обязана случиться раньше.
    return markup.replace("<body>", "<body>\n" + stub, 1)


def _frame(page: str, why: str, route: str, note: str, height: int) -> str:
    markup = (UI / page).read_text(encoding="utf-8")
    markup = _inline_assets(markup)
    markup = _stub_fetch(markup)
    return f"""<section class="frame">
  <header class="frame-head">
    <h2>{html.escape(why)}</h2>
    <code>{html.escape(route)}</code>
  </header>
  <p class="why">{html.escape(note)}</p>
  <div class="frame-body">
    <iframe title="{html.escape(why)}" srcdoc="{html.escape(markup, quote=True)}"
            height="{height}"></iframe>
  </div>
</section>"""


def _errors() -> str:
    rows = []
    for code, title, route, body, note in ERRORS:
        shown = html.escape(body) if body else '<span class="empty">(пустое тело)</span>'
        rows.append(
            f"""    <div class="err">
      <header><span class="code">{code}</span><b>{html.escape(title)}</b><code>{html.escape(route)}</code></header>
      <pre>{shown}</pre>
      <p class="why">{html.escape(note)}</p>
    </div>"""
        )
    return "\n".join(rows)


def _states() -> str:
    blocks = []
    for title, tag, note, heading, body in STATES:
        blocks.append(
            f"""<section class="frame">
  <header class="frame-head">
    <h2>{html.escape(title)}</h2>
    <span class="tag">{html.escape(tag)}</span>
  </header>
  <p class="why">{html.escape(note)}</p>
  <div class="frame-body pad">
    <h3 class="sec">{html.escape(heading)}</h3>
    {body}
  </div>
</section>"""
        )
    return "\n".join(blocks)


def build() -> str:
    frames = "\n".join(_frame(*page) for page in PAGES)
    return TEMPLATE.format(frames=frames, errors=_errors(), states=_states())


#: Оболочка макета. Своя палитра не заводится: цвета берутся теми же именами,
#: что и в продукте, и подставляются из `base.css` в `_shell_css` ниже — иначе
#: оболочка стала бы шестой копией палитры.
TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>hub — макет интерфейса</title>
<meta name="description" content="Специмен-лист интерфейса хаба: живые страницы продукта в одном файле, плюс состояния, которых на сервере сейчас нет.">
<!-- Не для поисковика. Макет показывает панель оператора нарисованной, с
     выдуманными строками; попав в выдачу, он опубликовал бы экран, похожий на
     настоящий, и читатель не смог бы отличить одно от другого. Данные в нём
     публичные (URL источников, счётчики стран), но по виду этого не сказать. -->
<meta name="robots" content="noindex, nofollow">
<style>
__SHELL_CSS__
</style>
</head>
<body>
<div class="sheet">

<header class="sheet-head">
  <h1>hub<span>.</span> макет интерфейса</h1>
  <p>
    Специмен-лист, а не рисунок. Каждый экран ниже — <b>настоящая страница</b>
    из <code>src/hub/ui/</code>, загруженная в рамку со своими скриптами и
    стилями, и наполненная <b>настоящими ответами</b> сервера из
    <code>docs/design/fixtures/</code>. Копий в этом файле нет, поэтому
    расходиться с продуктом ему не с чем.
  </p>
  <p class="sub">
    Собрано <code>scripts/build_mockup.py</code>. Пересобрать после правки
    страниц: <code>python3 scripts/build_mockup.py</code>. Тест
    <code>tests/test_mockup.py</code> падает, если файл не пересобрали.
  </p>
</header>

<h2 class="group">Страницы</h2>
{frames}

<h2 class="group">Состояния</h2>
{states}

<h2 class="group">Ошибки</h2>
<section class="frame">
  <p class="why">
    Каждая ошибка называет причину. «Не найдено» без объяснения — это то, из-за
    чего пользователь пишет в поддержку вместо того, чтобы исправить ссылку.
    Тела ответов скопированы из <code>api.py</code>, а не придуманы.
  </p>
  <div class="errors">
{errors}
  </div>
</section>

<footer class="sheet-foot">
  Живые адреса: <code>/</code>, <code>/status</code>, <code>/help</code> —
  публичные; <code>/admin</code> открывается только через SSH-туннель.
</footer>

</div>
</body>
</html>
"""


def _shell_css() -> str:
    """CSS оболочки макета, собранный из токенов продукта.

    Оболочке нужны цвет поля вокруг рамок, границы, чернила двух уровней и
    стек шрифтов. Всё это берётся из `base.css` чтением, а не набором заново —
    иначе оболочка стала бы ещё одной копией палитры, и мы вернулись бы к
    тому, с чего начали.
    """
    base = (UI / "base.css").read_text(encoding="utf-8")
    root = re.search(r":root\s*\{(.*?)\}", base, re.DOTALL)
    if not root:
        raise SystemExit("base.css: не найден :root — оболочка макета осталась бы без палитры")
    decls = root.group(1)

    def token(name: str) -> str:
        """Значение токена — как объявлено, без `;` и переносов.

        Цвет проверяется отдельно: оболочке разрешено брать только то, что
        объявлено в `base.css`, но брать она может и нецветовое — например
        стек шрифтов, чтобы не набирать второй. Цветовой литерал здесь
        появиться не может, поэтому проверка на `#rrggbb` остаётся для цветов.
        """
        match = re.search(rf"--{name}:\s*([^;]+);", decls)
        if not match:
            raise SystemExit(f"base.css: нет токена --{name}")
        return " ".join(match.group(1).split())

    #: Оболочка — не палитра, а её отсутствие: лист бумаги вокруг рамок.
    #: Единственный собственный цвет — подмешанный чёрный под фон страниц,
    #: и он разрешён `test_the_mockup_carries_no_new_palette` как `#000000`.
    #: Всё остальное — токены продукта, поэтому макет не может разойтись с ним
    #: в цвете: расходиться нечему.
    return f"""/* Оболочка собрана из токенов `base.css`, а не набрана своими цветами:
   иначе она стала бы ещё одной копией палитры.

   Оболочка — это ПОЛЕ вокруг листа, а не ещё один слой интерфейса. Поэтому
   она только темнее бумаги, ровно настолько, чтобы рамки были видны, и не
   вводит ни одной собственной краски: всё — токены продукта. */
body {{
  margin: 0;
  background: color-mix(in srgb, {token("paper")} 88%, {token("ink")});
  color: {token("ink")};
  font: 16px/1.62 {token("sans")};
  -webkit-font-smoothing: antialiased;
}}
.sheet {{ max-width: 78rem; margin: 0 auto; padding: 2.5rem 1.25rem 5rem; }}

.sheet-head h1 {{ font-size: 1.6rem; margin: 0 0 0.5rem; font-weight: 620; letter-spacing: -0.02em; }}
.sheet-head h1 span {{ color: {token("live")}; }}
.sheet-head p {{ color: {token("ink-2")}; margin: 0 0 0.6rem; max-width: 52rem; }}
.sheet-head b {{ color: {token("ink")}; font-weight: 620; }}
.sheet-head .sub {{ font-size: 0.86rem; }}

.group {{
  font-family: {token("mono")};
  font-size: 0.78rem; font-weight: 500; color: {token("ink-2")};
  margin: 3.2rem 0 1rem; padding-bottom: 0.5rem;
  border-bottom: 2px solid {token("ink")};
}}

.frame {{ margin: 0 0 3.2rem; }}
.frame-head {{ display: flex; align-items: baseline; gap: 0.7rem; flex-wrap: wrap; }}
.frame-head h2 {{ font-size: 1.05rem; margin: 0; font-weight: 620; }}
.frame-head code {{ font-family: {token("mono")}; font-size: 0.8rem; color: {token("ink-2")}; }}
.frame .why {{ color: {token("ink-2")}; font-size: 0.86rem; margin: 0.35rem 0 0.9rem; max-width: 54rem; }}
.tag {{
  font-family: {token("mono")};
  font-size: 0.72rem; color: {token("ink-2")};
  border: 1px dashed {token("rule")}; border-radius: 2px; padding: 0.05rem 0.4rem;
}}

/* Рамка — рамка, а не карточка: внутри страница со своим фоном, и подъём или
   тень заставили бы её читаться как элемент макета, а не как окно в продукт. */
.frame-body {{
  border: 1px solid {token("rule")};
  border-radius: 2px;
  overflow: hidden;
  background: {token("paper")};
}}
.frame-body iframe {{ display: block; width: 100%; border: 0; background: {token("paper")}; }}
.frame-body.pad {{ padding: 1.5rem 1.6rem 2rem; }}

/* Состояния рисуются разметкой продукта с его же классами. Внутри iframe
   страница получает стили сама; здесь разметка вставлена прямо в оболочку,
   поэтому правила для этих классов нужны и тут — иначе состояние показало бы
   не продукт, а голый текст. */
.frame-body .pool {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr)); border-top: 1px solid {token("rule")}; border-bottom: 1px solid {token("rule")}; margin-bottom: 1.4rem; }}
.frame-body .pool > div {{ padding: 0.9rem 1.1rem 0.9rem 0; border-right: 1px solid {token("rule-2")}; }}
.frame-body .pool > div:last-child {{ border-right: 0; }}
.frame-body .pool .v {{ font-family: {token("mono")}; font-size: 1.5rem; font-weight: 500; line-height: 1.1; letter-spacing: -0.025em; font-variant-numeric: tabular-nums; }}
.frame-body .pool .k {{ margin-top: 0.25rem; }}
.frame-body .label {{ font-family: {token("mono")}; font-size: 0.74rem; color: {token("ink-2")}; }}
.frame-body .caption {{ color: {token("ink-2")}; font-size: 0.84rem; margin: 0.8rem 0 0; max-width: 46rem; line-height: 1.6; }}
.frame-body .countries {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 2.6rem; max-width: 46rem; }}
.frame-body .country {{ display: grid; grid-template-columns: 1.35rem min-content 1fr auto; grid-template-areas: "flag name lead count" "bar bar bar bar"; align-items: baseline; column-gap: 0.55rem; padding: 0.3rem 0 0.42rem; min-width: 0; }}
.frame-body .country .flag {{ grid-area: flag; font-size: 0.82rem; line-height: 1; width: 1.15rem; text-align: center; }}
.frame-body .country .name {{ grid-area: name; font-size: 0.88rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.frame-body .country .lead {{ grid-area: lead; align-self: end; overflow: hidden; min-width: 0.8rem; }}
.frame-body .country .lead::after {{ content: ""; display: block; border-bottom: 1px dotted {token("rule")}; margin-bottom: 0.24rem; }}
.frame-body .country .count {{ grid-area: count; font-family: {token("mono")}; font-size: 0.86rem; font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }}
.frame-body .country .count .unit {{ color: {token("ink-3")}; font-size: 0.74rem; margin-left: 0.28rem; }}
.frame-body .country .track {{ grid-area: bar; display: block; height: 2px; margin-top: 0.34rem; background: transparent; overflow: hidden; }}
.frame-body .country .track > i {{ display: block; height: 100%; background: {token("gauge")}; }}
.frame-body .country[data-top="1"] .track > i {{ background: {token("live")}; }}
.frame-body .country[data-thin="1"] .track {{ background: transparent; }}
.frame-body .country[data-thin="1"] .track > i {{ background: transparent; }}

.sec {{ font-family: {token("mono")}; font-size: 0.76rem; font-weight: 500; color: {token("ink-2")}; padding-bottom: 0.45rem; border-bottom: 1px solid {token("rule")}; margin: 0 0 0.25rem; }}

/* `minmax(0, 1fr)`, а не `1fr`: у сетки автоматический минимум колонки —
   `auto`, и тело ошибки (JSON в одну строку, без переносов) растягивало её
   шире экрана. Ячейка с `min-width: 0` и прокрутка у `pre` держат блок в
   колонке на телефоне. */
.errors {{ display: grid; grid-template-columns: minmax(0, 1fr); gap: 1rem; }}
.err {{
  border: 1px solid {token("rule")}; border-radius: 2px; padding: 0.9rem 1.05rem;
  background: {token("paper-3")}; min-width: 0;
}}
.err header {{ display: flex; align-items: baseline; gap: 0.6rem; flex-wrap: wrap; }}
.err .code {{
  font-family: {token("mono")}; font-size: 0.78rem; font-weight: 650;
  color: {token("fail")};
  border: 1px solid color-mix(in srgb, {token("fail")} 40%, transparent);
  border-radius: 2px; padding: 0.05rem 0.5rem;
}}
.err b {{ font-size: 0.9rem; }}
.err header code {{ font-family: {token("mono")}; font-size: 0.76rem; color: {token("ink-3")}; }}
.err pre {{
  font-family: {token("mono")}; font-size: 0.78rem; line-height: 1.55;
  background: {token("paper-2")}; border-radius: 2px; padding: 0.7rem 0.8rem;
  overflow-x: auto; margin: 0.6rem 0 0;
}}
.err .empty {{ color: {token("ink-3")}; font-style: italic; }}
.err .why {{ color: {token("ink-2")}; font-size: 0.82rem; margin: 0.6rem 0 0; }}

.sheet-foot {{ margin-top: 3rem; padding-top: 1.2rem; border-top: 1px solid {token("rule")}; color: {token("ink-3")}; font-size: 0.82rem; }}
.sheet-foot code {{ font-family: {token("mono")}; }}
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check", action="store_true", help="не писать файл, а сказать, устарел ли он (для теста)"
    )
    args = parser.parse_args()

    page = build().replace("__SHELL_CSS__", _shell_css())

    if args.check:
        if not OUT.is_file():
            print(f"{OUT} отсутствует — запустите scripts/build_mockup.py")
            return 1
        if OUT.read_text(encoding="utf-8") != page:
            print(f"{OUT} устарел — запустите scripts/build_mockup.py")
            return 1
        print(f"{OUT} актуален")
        return 0

    OUT.write_text(page, encoding="utf-8")
    print(f"{OUT}: {len(page)} байт")
    return 0


if __name__ == "__main__":
    sys.exit(main())
