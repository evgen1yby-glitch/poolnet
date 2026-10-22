#!/usr/bin/env python3
"""Собрать третье направление «Лист показаний» в лист для оценки.

    python3 docs/design/src/build_fresh.py

Пишет `docs/design/fresh.html` и `docs/design/pages/c-*.html`. Схема — та же,
что у `build_directions.py`: страницы собираются из снимков
`docs/design/fixtures/` (ни одного числа руками), стилевой файл кладётся
рядом с страницами, чтобы относительный путь `../assets/fonts/…` работал из
`file://`, а лист показывает каждую страницу в рамке — с настоящими
медиазапросами и настоящим viewport 390px для телефона.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ASSETS = ROOT / "docs" / "design" / "assets"
PAGES = ROOT / "docs" / "design" / "pages"
OUT = ROOT / "docs" / "design" / "fresh.html"

sys.path.insert(0, str(HERE))

import dir_c

import data


def frame(src: str, key: str, note: str) -> str:
    """Рамка поверх собранной страницы, кликабельная на полный экран."""
    return (
        f'<a class="frame-link" href="{src}" target="_blank" rel="noopener" '
        f'data-label="{html.escape(note, quote=True)}">'
        f'<iframe class="frame frame-{key}" title="{html.escape(note, quote=True)}" '
        f'src="{src}" loading="lazy"></iframe></a>'
    )


SHEET_CSS = """\
@font-face{font-family:"Inter";src:url("assets/fonts/inter-cyrillic.woff2") format("woff2");
  unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116;font-weight:100 900}
@font-face{font-family:"Inter";src:url("assets/fonts/inter-latin.woff2") format("woff2");
  unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,
  U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD;
  font-weight:100 900}
@font-face{font-family:"IBM Plex Mono";src:url("assets/fonts/plexmono-cyrillic-400.woff2") format("woff2");
  unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116;font-weight:400}
@font-face{font-family:"IBM Plex Mono";src:url("assets/fonts/plexmono-latin-400.woff2") format("woff2");
  unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,
  U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD;
  font-weight:400}

:root{--page:#f6f7f9;--card:#fff;--ink:#0f172a;--ink-2:#475569;--ink-3:#8792a8;
  --line:#e4e8ef;--line-2:#edf0f4;--acc:#2563eb;--acc-deep:#1e50c8;
  --acc-wash:#eaf0fe;--acc-line:#c7d7fa;--mono:"IBM Plex Mono",ui-monospace,monospace}
*{box-sizing:border-box}
html{background:var(--page)}
body{margin:0;background:var(--page);color:var(--ink);
  font:15px/1.55 "Inter",system-ui,sans-serif;letter-spacing:-.011em;
  -webkit-font-smoothing:antialiased}
code{font-family:var(--mono);font-size:.85em}
header.sheet{padding:52px clamp(20px,4vw,54px) 24px;max-width:1180px;margin:0 auto}
header.sheet .kicker{
  display:inline-flex;align-items:center;gap:8px;padding:6px 14px;
  background:var(--acc-wash);color:var(--acc-deep);border:1px solid var(--acc-line);
  border-radius:999px;font-size:.78rem;font-weight:600}
header.sheet h1{margin:18px 0 0;font:640 clamp(1.9rem,3.6vw,2.9rem)/1.08 "Inter",sans-serif;
  letter-spacing:-.035em;max-width:26ch}
header.sheet p{margin:14px 0 0;max-width:72ch;color:var(--ink-2)}
.dir-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);
  gap:clamp(20px,4vw,60px);align-items:start;
  padding:24px clamp(20px,4vw,54px) 22px;max-width:1180px;margin:0 auto;
  border-bottom:1px solid var(--line)}
.dir-grid h2{margin:0;font:620 1.35rem/1.2 "Inter",sans-serif;letter-spacing:-.02em}
.dir-grid .say{margin:12px 0 0;color:var(--ink-2);max-width:56ch}
.dir-grid dl{margin:0;display:grid;grid-template-columns:86px minmax(0,1fr);
  gap:7px 16px;font-size:.82rem}
.dir-grid dt{color:var(--ink-3);font-family:var(--mono);font-size:.7rem;letter-spacing:.02em}
.dir-grid dd{margin:0}
.dir-grid code{font-size:.76rem}
.swatches{display:flex;gap:6px;margin-top:14px;flex-wrap:wrap;align-items:center}
.swatches i{width:25px;height:25px;border-radius:6px;border:1px solid rgba(15,23,42,.12)}
.swatches em{font:400 .66rem/1.5 var(--mono);color:var(--ink-3);font-style:normal;margin-left:4px}
.screens{display:grid;gap:18px;margin-top:26px;
  padding:0 clamp(20px,4vw,54px) 16px;max-width:1280px;margin-left:auto;margin-right:auto}
.frame-link{display:block;text-decoration:none}
.frame{width:100%;border:1px solid var(--line);border-radius:12px;background:#fff;
  display:block;box-shadow:0 1px 2px rgba(15,23,42,.05),0 10px 30px rgba(15,23,42,.06)}
.frame-wide{height:3640px}
.frame-status{height:2260px}
.frame-admin{height:1860px}
.frame-keys{height:1300px}
.frame-empty{height:1720px}
.frame-login{height:760px}
.frame-phone{width:390px;height:844px;border-radius:22px;
  border:1px solid var(--line);box-shadow:0 10px 34px rgba(15,23,42,.12)}
.pair{display:flex;gap:26px;align-items:flex-start;flex-wrap:wrap}
.cap{margin:9px 0 6px;font-size:.76rem;color:var(--ink-2);max-width:86ch}
.cap b{font-weight:620;color:var(--ink)}
.phone-wrap{width:390px}
footer{padding:36px clamp(20px,4vw,54px) 80px;max-width:1180px;margin:0 auto;
  color:var(--ink-3);font-size:.78rem;border-top:1px solid var(--line);font-family:var(--mono)}
@media (max-width:820px){
  .dir-grid{grid-template-columns:1fr}
  .pair{flex-direction:column}
  .frame-phone{width:100%;height:800px}
  .phone-wrap{width:100%}
}
/* Телефон: рамки заменяются списком ссылок — рамка шириной 390px на экране
   390px это страница в масштабе телефона, прочитанная как крошечный прямоугольник. */
@media (max-width:600px){
  .frame{display:none}
  .frame-link{
    display:flex;align-items:center;justify-content:space-between;gap:12px;
    min-height:0;padding:13px 14px;margin-top:8px;
    border:1px solid var(--line);border-radius:10px;background:#fff;
    color:var(--ink);font-size:.86rem;line-height:1.3;text-decoration:none}
  .frame-link::after{content:"открыть";font-family:var(--mono);font-size:.7rem;
    color:var(--ink-3);flex:none}
  .frame-link[data-label]::before{content:attr(data-label)}
  .screens{gap:0}
  .cap{margin:8px 0 18px}
  .phone-wrap{width:100%}
}
"""

SHEET_BODY = """\
<header class="sheet">
  <span class="kicker">Направление C · чистый светлый SaaS</span>
  <h1>Лист показаний</h1>
  <p>«Вахта» — про состояние прибора: тёмная комната и одна шкала. «Атлас» —
     про координаты: антиква и сетка. Эта — про нейтральный продукт: белый
     лист, аккуратные карточки, один синий акцент, один шрифт Inter и
     моноширинный для технических вещей. Показания те же: один набор снимков,
     ни одного числа руками.</p>
</header>
<div class="dir-grid">
  <div>
    <h2>Направление C — «Лист показаний»</h2>
    <p class="say">Хаб — продукт, а не пульт: его страницы — реестр, состояние,
      панель — выглядят так, как выглядят опрятные продуктовые интерфейсы.
      Главный артефакт — сводка показаний: сколько вошло, сколько прошло,
      какая доля. Всё остальное страницы комментирует именно её.</p>
  </div>
  <div>
    <dl>
      <dt>цвет</dt><dd>грунт <code>#f6f7f9</code>, карточка <code>#ffffff</code>,
        чернила <code>#0f172a</code>, единственный акцент — действие
        <code>#2563eb</code>; статусы несут зелёный, янтарный и красный</dd>
      <dt>шрифт</dt><dd>Inter (один на всё, переменный) · IBM Plex Mono
        (ключи, URL, поколения)</dd>
      <dt>сетка</dt><dd>карточки на нейтральном грунте; радиус 10/8 px; тень
        одной высоты на все карточки</dd>
      <dt>принцип</dt><dd>акцент — только действие и подтверждение; статусы и
        измерения несут семантические цвета; краску несёт карточка, а не
        страница</dd>
    </dl>
    <div class="swatches">
      <i style="background:#f6f7f9"></i><i style="background:#ffffff"></i>
      <i style="background:#2563eb"></i><i style="background:#15803d"></i>
      <i style="background:#b45309"></i><i style="background:#0f172a"></i>
      <em>грунт · карточка · действие · подтверждено · предупреждение · чернила</em>
    </div>
  </div>
</div>
<div class="screens">
  {c_landing}
  <p class="cap"><b>Главная.</b> Герой по центру, сводка показаний под ним,
    воронка строками, карта выходов в карточке со справочником стран под
    ней, клиенты, предупреждение. Порядок — от показаний к инструкции.</p>
  {c_phone}
  <p class="cap"><b>Телефон.</b> Навигация остаётся в шапке, сводка
    становится одной колонкой, справочник стран сжимается.</p>
  {c_status}
  <p class="cap"><b>Состояние пула.</b> Показания-карточки, столбики истории
    с пометкой лучшего обхода, публикации и источники таблицами.</p>
  {c_status_phone}
  <p class="cap"><b>Телефон · состояние.</b> Показания в одну колонку,
    столбики сжимаются по числу обходов.</p>
  {c_login}
  <p class="cap"><b>Вход.</b> Карточка по центру, поле набрано моноширинно:
    секрет читают по символу.</p>
  {c_admin}
  <p class="cap"><b>Панель оператора.</b> Левый рельс с группами, показания
    в карточках, воронка, страны и источники в две колонки.</p>
  {c_keys}
  <p class="cap"><b>Ключи.</b> Форма выдачи и квитанция «показывается один
    раз» одной карточкой; ниже — таблица выданных.</p>
  {c_empty}
  <p class="cap"><b>Пустое состояние.</b> Новая установка: карта без точек и
    порядок действий вместо нуля.</p>
</div>
"""


def main() -> int:
    PAGES.mkdir(parents=True, exist_ok=True)

    # CSS кладётся рядом с страницами, не читается из src/: относительный
    # url("../assets/fonts/…") из pages/ ведёт в docs/design/assets/fonts,
    # и страница открывается прямо из file://.
    (PAGES / "c.css").write_text(
        (HERE / "c" / "c.css").read_text(encoding="utf-8"), encoding="utf-8")

    d = data.load()
    empty = data.empty()
    stamp = (HERE / "data.py").stat().st_mtime

    pages = {
        "c-1-landing": dir_c.landing(d),
        "c-2-status": dir_c.status(d),
        "c-3-login": dir_c.login(),
        "c-4-admin": dir_c.admin(d),
        "c-5-keys": dir_c.keys(d),
        "c-6-empty": dir_c.landing_empty(empty),
    }
    for name, markup in pages.items():
        (PAGES / f"{name}.html").write_text(markup, encoding="utf-8")

    expected = {f"{name}.html" for name in pages} | {"c.css"}
    for old in PAGES.glob("c-*"):
        if old.name not in expected:
            old.unlink()

    import datetime

    out = (
        '<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        "<title>hub — направление C, «Лист показаний»</title>\n"
        "<style>" + SHEET_CSS + "</style>\n</head>\n<body>\n"
        + SHEET_BODY
        + "</body>\n</html>\n"
    )
    for k, v in dict(
        c_landing=frame("pages/c-1-landing.html", "wide", "C · главная"),
        c_phone=frame("pages/c-1-landing.html", "phone", "C · главная на телефоне"),
        c_status=frame("pages/c-2-status.html", "status", "C · состояние пула"),
        c_status_phone=frame("pages/c-2-status.html", "phone", "C · состояние на телефоне"),
        c_login=frame("pages/c-3-login.html", "login", "C · вход"),
        c_admin=frame("pages/c-4-admin.html", "admin", "C · панель"),
        c_keys=frame("pages/c-5-keys.html", "keys", "C · ключи"),
        c_empty=frame("pages/c-6-empty.html", "empty", "C · пустое состояние"),
        date=datetime.date.fromtimestamp(stamp).isoformat(),
    ).items():
        out = out.replace("{" + k + "}", v)
    OUT.write_text(out, encoding="utf-8")
    size = sum(p.stat().st_size for p in PAGES.glob("c-*.html"))
    print(f"{OUT} · {OUT.stat().st_size / 1024:.0f} КБ · страниц {len(pages)} · {size / 1024:.0f} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
