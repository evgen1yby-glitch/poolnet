#!/usr/bin/env python3
"""Собрать направление D «Созвездие» (тёмный премиум) в лист для оценки.

    python3 docs/design/src/build_dark.py

Пишет `docs/design/dark.html` и страницы `docs/design/pages/d-*.html`.
Схема та же, что у `build_fresh.py`: страницы собираются из снимков
`docs/design/fixtures/` (ни одного числа руками), стилевой файл кладётся
рядом с страницами, лист показывает каждую страницу в рамке — с настоящим
viewport 390px для телефона.
"""

from __future__ import annotations

import datetime
import html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PAGES = ROOT / "docs" / "design" / "pages"
OUT = ROOT / "docs" / "design" / "dark.html"

sys.path.insert(0, str(HERE))

import dir_d

import data


def frame(src: str, key: str, note: str) -> str:
    return (
        f'<a class="frame-link" href="{src}" target="_blank" rel="noopener" '
        f'data-label="{html.escape(note, quote=True)}">'
        f'<iframe class="frame frame-{key}" title="{html.escape(note, quote=True)}" '
        f'src="{src}" loading="lazy"></iframe></a>'
    )


SHEET_CSS = """\
@font-face{font-family:"Unbounded";src:url("assets/fonts/unbounded-cyrillic.woff2") format("woff2");
  unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116;font-weight:200 900}
@font-face{font-family:"Unbounded";src:url("assets/fonts/unbounded-latin.woff2") format("woff2");
  unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,
  U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD;
  font-weight:200 900}
@font-face{font-family:"Manrope";src:url("assets/fonts/manrope-cyrillic-wght-normal.woff2") format("woff2");
  unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116;font-weight:300 800}
@font-face{font-family:"Manrope";src:url("assets/fonts/manrope-latin-wght-normal.woff2") format("woff2");
  unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,
  U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD;
  font-weight:300 800}
@font-face{font-family:"JetBrains Mono";src:url("assets/fonts/jbmono-cyrillic.woff2") format("woff2");
  unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116;font-weight:100 800}
@font-face{font-family:"JetBrains Mono";src:url("assets/fonts/jbmono-latin.woff2") format("woff2");
  unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,
  U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD;
  font-weight:100 800}

:root{--void:#070b13;--panel:#0d1522;--glass:#111a2c;
  --line:rgba(148,180,240,.10);--line-2:rgba(148,180,240,.16);
  --txt:#eaf2ff;--txt-2:#9db1d4;--txt-3:#5f7395;
  --sig:#6be1ff;--sig-deep:#2fb9ff;--sig-wash:rgba(107,225,255,.09);
  --ok:#58e6a6;--warn:#f4c469;--fail:#ff8a8a;
  --disp:"Unbounded","Manrope",system-ui,sans-serif;
  --sans:"Manrope",system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,monospace}
*{box-sizing:border-box}
html{background:var(--void)}
body{margin:0;background:var(--void);color:var(--txt);
  font:15px/1.6 var(--sans);letter-spacing:.005em;-webkit-font-smoothing:antialiased}
code{font-family:var(--mono);font-size:.88em}

header.sheet{padding:52px clamp(20px,4vw,54px) 24px;max-width:1180px;margin:0 auto}
header.sheet .kicker{
  display:inline-flex;align-items:center;gap:8px;padding:6px 14px;
  background:var(--sig-wash);color:var(--sig);border:1px solid rgba(107,225,255,.3);
  border-radius:999px;font-size:.78rem;font-family:var(--mono)}
header.sheet h1{margin:20px 0 0;font:460 clamp(1.9rem,3.6vw,2.9rem)/1.12 var(--disp)}
header.sheet p{margin:14px 0 0;max-width:72ch;color:var(--txt-2)}
.dir-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);
  gap:clamp(20px,4vw,60px);align-items:start;
  padding:24px clamp(20px,4vw,54px) 22px;max-width:1180px;margin:0 auto;
  border-bottom:1px solid var(--line)}
.dir-grid h2{margin:0;font:460 1.35rem/1.2 var(--disp)}
.dir-grid .say{margin:12px 0 0;color:var(--txt-2);max-width:56ch}
.dir-grid dl{margin:0;display:grid;grid-template-columns:86px minmax(0,1fr);
  gap:7px 16px;font-size:.82rem}
.dir-grid dt{color:var(--txt-3);font-family:var(--mono);font-size:.7rem}
.dir-grid dd{margin:0}
.dir-grid code{font-size:.76rem}
.swatches{display:flex;gap:6px;margin-top:14px;flex-wrap:wrap;align-items:center}
.swatches i{width:25px;height:25px;border-radius:6px;border:1px solid rgba(234,242,255,.16)}
.swatches em{font:400 .66rem/1.5 var(--mono);color:var(--txt-3);font-style:normal;margin-left:4px}
.screens{display:grid;gap:18px;margin-top:26px;
  padding:0 clamp(20px,4vw,54px) 16px;max-width:1280px;margin-left:auto;margin-right:auto}
.frame-link{display:block;text-decoration:none}
.frame{width:100%;border:1px solid var(--line-2);border-radius:14px;background:var(--void);
  display:block;box-shadow:0 1px 2px rgba(0,0,0,.4),0 12px 36px rgba(0,0,0,.35)}
.frame-wide{height:6280px}
.frame-empty{height:1760px}
.frame-status{height:2650px}
.frame-admin{height:2130px}
.frame-keys{height:1390px}
.frame-login{height:1000px}
.frame-phone{width:390px;height:844px;border-radius:22px;
  border:1px solid var(--line-2);box-shadow:0 12px 40px rgba(0,0,0,.45)}
.pair{display:flex;gap:26px;align-items:flex-start;flex-wrap:wrap}
.cap{margin:9px 0 6px;font-size:.78rem;color:var(--txt-2);max-width:86ch}
.cap b{font-weight:650;color:var(--txt)}
.phone-wrap{width:390px}
footer{padding:36px clamp(20px,4vw,54px) 80px;max-width:1180px;margin:0 auto;
  color:var(--txt-3);font-size:.78rem;border-top:1px solid var(--line);font-family:var(--mono)}
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
    border:1px solid var(--line);border-radius:10px;background:var(--panel);
    color:var(--txt);font-size:.86rem;line-height:1.3;text-decoration:none}
  .frame-link::after{content:"открыть";font-family:var(--mono);font-size:.7rem;
    color:var(--txt-3);flex:none}
  .frame-link[data-label]::before{content:attr(data-label)}
  .screens{gap:0}
  .cap{margin:8px 0 18px}
  .phone-wrap{width:100%}
}
"""

SHEET_BODY = """\
<header class="sheet">
  <span class="kicker">направление D · тёмный премиум</span>
  <h1>Созвездие</h1>
  <p>Абстракт-слайд: выходы читаются как звёзды на ночном небе — свет стоит
     только на карте и на кнопке-действии, остальное страницы держит в
     дисциплине тёмного стекла. Заголовки — Unbounded, текст — Manrope,
     показания — JetBrains Mono. Данные — те же снимки, ни одного числа
     руками.</p>
</header>
<div class="dir-grid">
  <div>
    <h2>Направление D — «Созвездие»</h2>
    <p class="say">Тёмная тема не как режим, а как позиционирование: сеть
      публичная, зато небо тёмное, и светится на нём только проверенный
      выход. Главная — карта-герой снизу вверх, панель и реестр живут на
      стеклянных панелях с одной сигнальной краской.</p>
  </div>
  <div>
    <dl>
      <dt>цвет</dt><dd>фон <code>#070b13</code>, панель <code>#0d1522</code>,
        сигнальный циан <code>#6be1ff</code> (действие и живой сигнал);
        статусы — зелёный, янтарный, красный</dd>
      <dt>шрифт</dt><dd>Unbounded (голос) · Manrope (текст) ·
        JetBrains Mono (показания, ID, URL)</dd>
      <dt>сетка</dt><dd>стеклянные панели радиусом 18/15 px, волосные
        границы, глоу только на карте, кнопке и живых числах</dd>
      <dt>принцип</dt><dd>свет несёт смысл: чем ярче элемент, тем ближе
        он к живому сигналу; прочая отделка — контраст и волосные линии</dd>
    </dl>
    <div class="swatches">
      <i style="background:#070b13"></i><i style="background:#111a2c"></i>
      <i style="background:#6be1ff"></i><i style="background:#58e6a6"></i>
      <i style="background:#f4c469"></i><i style="background:#eaf2ff"></i>
      <em>пустота · стекло · сигнал · работает · предупреждение · чернила</em>
    </div>
  </div>
</div>
<div class="screens">
  {d_landing}
  <p class="cap"><b>Главная.</b> Герой-высказывание, карта-созвездие с
    светящимися точками выходов, сводка из трёх чисел, конвейер дорожкой,
    справочник стран, клиенты, предупреждение.</p>
  {d_phone}
  <p class="cap"><b>Телефон.</b> Навигация в шапке остаётся только кнопкой,
    сводка в одну колонку, дорожки конвейера сжимаются.</p>
  {d_status}
  <p class="cap"><b>Состояние пула.</b> Показания стеклом, столбики истории
    с подсветкой лучшего обхода, публикации и источники тёмными таблицами.</p>
  {d_status_phone}
  <p class="cap"><b>Телефон · состояние.</b> Показания в одну колонку,
    столбики сжимаются по числу обходов.</p>
  {d_login}
  <p class="cap"><b>Вход.</b> Стеклянная карточка над сеткой с ореолом,
    секрет набирается моноширинно: его читают по символу.</p>
  {d_admin}
  <p class="cap"><b>Панель оператора.</b> Тёмный рельс, активный пункт
    подсвечен сигнальной краской; показания, воронка, страны и источники
    панелями.</p>
  {d_keys}
  <p class="cap"><b>Ключи.</b> Форма выдачи и разовый сейф — пунктирная
    рамка: «второй раз показать нельзя»; ниже таблица выданных.</p>
  {d_empty}
  <p class="cap"><b>Пустое состояние.</b> Новая установка: пустое небо,
    первый шаг уже светится зелёным.</p>
</div>
"""


def main() -> int:
    PAGES.mkdir(parents=True, exist_ok=True)

    (PAGES / "d.css").write_text(
        (HERE / "d" / "d.css").read_text(encoding="utf-8"), encoding="utf-8")

    d = data.load()
    empty = data.empty()
    stamp_mtime = (HERE / "data.py").stat().st_mtime

    pages = {
        "d-1-landing": dir_d.landing(d),
        "d-2-status": dir_d.status(d),
        "d-3-login": dir_d.login(),
        "d-4-admin": dir_d.admin(d),
        "d-5-keys": dir_d.keys(d),
        "d-6-empty": dir_d.landing_empty(empty),
    }
    for name, markup in pages.items():
        (PAGES / f"{name}.html").write_text(markup, encoding="utf-8")

    expected = {f"{name}.html" for name in pages} | {"d.css"}
    for old in PAGES.glob("d-*"):
        if old.name not in expected:
            old.unlink()

    out = (
        '<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        "<title>poolnet.online — направление D, «Созвездие»</title>\n"
        "<style>" + SHEET_CSS + "</style>\n</head>\n<body>\n"
        + SHEET_BODY
        + "</body>\n</html>\n"
    )
    for k, v in {
        "d_landing": frame("pages/d-1-landing.html", "wide", "D · главная"),
        "d_phone": frame("pages/d-1-landing.html", "phone", "D · главная на телефоне"),
        "d_status": frame("pages/d-2-status.html", "status", "D · состояние пула"),
        "d_status_phone": frame("pages/d-2-status.html", "phone", "D · состояние на телефоне"),
        "d_login": frame("pages/d-3-login.html", "login", "D · вход"),
        "d_admin": frame("pages/d-4-admin.html", "admin", "D · панель"),
        "d_keys": frame("pages/d-5-keys.html", "keys", "D · ключи"),
        "d_empty": frame("pages/d-6-empty.html", "empty", "D · пустое состояние"),
        "date": datetime.date.fromtimestamp(stamp_mtime).isoformat(),
    }.items():
        out = out.replace("{" + k + "}", v)
    OUT.write_text(out, encoding="utf-8")
    size = sum(p.stat().st_size for p in PAGES.glob("d-*.html"))
    print(f"{OUT} · {OUT.stat().st_size / 1024:.0f} КБ · страниц {len(pages)} · {size / 1024:.0f} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
