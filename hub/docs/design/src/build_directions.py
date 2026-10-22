#!/usr/bin/env python3
"""Собрать два макета направлений в один лист для оценки.

    python3 docs/design/src/build_directions.py

Пишет `docs/design/directions.html` и `docs/design/pages/*.html`. Лист
открывается из `file://` и не делает ни одного внешнего запроса: шрифты лежат
рядом в `assets/fonts/`, картинок и CDN нет.

Почему сборщик, а не шесть страниц руками. У направлений общий набор данных и
общий принцип: ни одно число на экране не набрано рукой. Оба направления
читают одни и те же снимки с сервера (`docs/design/fixtures/`), поэтому
разница между макетами — это разница композиции, а не разница цифр. Если
снимок обновили, оба макета меняются вместе; будь они отдельными файлами, они
бы разъехались.

Почему рамки, а не картинки. `<iframe src="pages/a-1.html">` показывает
страницу как есть — со своими медиазапросами, со своими шрифтами. Узкая рамка
телефона — это настоящий viewport 390px, а не уменьшенная копия десктопной
страницы. Скриншот пришлось бы переснимать после каждой правки, и он врал бы
о поведении на узком экране ровно в тот момент, когда это важно.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ASSETS = ROOT / "docs" / "design" / "assets"
PAGES = ROOT / "docs" / "design" / "pages"
OUT = ROOT / "docs" / "design" / "directions.html"

sys.path.insert(0, str(HERE))

import data  # noqa: E402
import dir_a  # noqa: E402
import dir_b  # noqa: E402


def frame(src: str, key: str, note: str) -> str:
    """Рамка поверх собранной страницы, кликабельная на полный экран.

    `data-label` нужен узкому экрану: там рамки не показываются (см. медиазапрос
    в `SHELL`), и ссылка обязана называть себя сама.
    """
    return (
        f'<a class="frame-link" href="{src}" target="_blank" rel="noopener" '
        f'data-label="{html.escape(note, quote=True)}">'
        f'<iframe class="frame frame-{key}" title="{html.escape(note, quote=True)}" '
        f'src="{src}" loading="lazy"></iframe></a>'
    )


SHELL = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>hub — два направления дизайна</title>
<style>
@font-face{font-family:"Golos Text";src:url("assets/fonts/golos-cyrillic.woff2") format("woff2");
  unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116;font-weight:400 900}
@font-face{font-family:"Golos Text";src:url("assets/fonts/golos-latin.woff2") format("woff2");
  unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,
  U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD;
  font-weight:400 900}
@font-face{font-family:"Unbounded";src:url("assets/fonts/unbounded-cyrillic.woff2") format("woff2");
  unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116;font-weight:200 900}
@font-face{font-family:"Unbounded";src:url("assets/fonts/unbounded-latin.woff2") format("woff2");
  unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,
  U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD;
  font-weight:200 900}
@font-face{font-family:"JetBrains Mono";src:url("assets/fonts/jbmono-cyrillic.woff2") format("woff2");
  unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116;font-weight:100 800}
@font-face{font-family:"JetBrains Mono";src:url("assets/fonts/jbmono-latin.woff2") format("woff2");
  unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,
  U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD;
  font-weight:100 800}

:root{--ink:#14161a;--soft:#3d4238;--mute:#7b8073;--paper:#e9e9e4;--rule:#c9cabf;
  --mono:"JetBrains Mono",ui-monospace,monospace}
*{box-sizing:border-box}
html{background:var(--paper)}
body{margin:0;background:var(--paper);color:var(--ink);
  font:15px/1.55 "Golos Text",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
header.sheet{padding:52px clamp(20px,4vw,54px) 24px;max-width:1180px;margin:0 auto}
header.sheet h1{margin:0;font:600 clamp(1.8rem,3.4vw,2.8rem)/1.06 "Unbounded",sans-serif;
  letter-spacing:-.03em;max-width:20ch}
header.sheet p{margin:14px 0 0;max-width:72ch;color:var(--soft)}
.tabs{position:sticky;top:0;z-index:20;display:flex;gap:2px;padding:10px clamp(20px,4vw,54px);
  background:rgba(233,233,228,.94);backdrop-filter:blur(8px);border-bottom:1px solid var(--rule)}
.tabs a{padding:9px 15px;border-radius:3px;font-size:.82rem;color:#565b50;text-decoration:none;
  font-family:var(--mono)}
.tabs a b{font-weight:700;color:var(--ink)}
.tabs a:first-child{background:var(--ink);color:#fff}
.tabs a:first-child b{color:#fff}
section.dir{padding:38px clamp(20px,4vw,54px) 16px;max-width:1180px;margin:0 auto}
.dir-head{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:clamp(20px,4vw,60px);
  align-items:start;padding-bottom:22px;border-bottom:1px solid var(--rule)}
.dir-head h2{margin:0;font:600 1.5rem/1.15 "Unbounded",sans-serif;letter-spacing:-.02em}
.dir-head h2 span{display:block;font:400 .7rem/1 var(--mono);
  letter-spacing:.06em;color:var(--mute);margin-bottom:10px}
.dir-head .say{margin:12px 0 0;color:var(--soft);max-width:50ch}
.dir-head dl{margin:0;display:grid;grid-template-columns:86px minmax(0,1fr);gap:7px 16px;font-size:.82rem}
.dir-head dt{color:var(--mute);font-family:var(--mono);font-size:.7rem;letter-spacing:.02em}
.dir-head dd{margin:0}
.dir-head code{font-family:var(--mono);font-size:.76rem}
.swatches{display:flex;gap:6px;margin-top:14px;flex-wrap:wrap;align-items:center}
.swatches i{width:25px;height:25px;border-radius:2px;border:1px solid rgba(0,0,0,.14)}
.swatches em{font:400 .66rem/1.4 var(--mono);color:var(--mute);font-style:normal;margin-left:4px}
.screens{display:grid;gap:16px;margin-top:24px}
.frame-link{display:block;text-decoration:none}
.frame{width:100%;border:1px solid #bfc1b3;border-radius:3px;background:#fff;display:block}
.frame-wide{height:1240px}
.frame-status{height:1120px}
.frame-admin{height:1160px}
.frame-login{height:540px}
.frame-phone{width:390px;height:844px;border-radius:18px;border:6px solid #1b1e18;
  box-shadow:0 10px 34px rgba(0,0,0,.16)}
.pair{display:flex;gap:26px;align-items:flex-start;flex-wrap:wrap}
.cap{margin:9px 0 6px;font-size:.76rem;color:var(--mute);max-width:80ch}
.cap b{font-weight:600;color:#33372e}
.phone-wrap{width:390px}
.note-row{margin:26px 0 0;padding:14px 16px;border-left:2px solid var(--ink);
  background:#e1e2da;font-size:.8rem;color:var(--soft);max-width:80ch}
footer{padding:36px clamp(20px,4vw,54px) 80px;max-width:1180px;margin:0 auto;
  color:var(--mute);font-size:.78rem;border-top:1px solid var(--rule);font-family:var(--mono)}
@media (max-width:820px){
  .dir-head{grid-template-columns:1fr}
  .pair{flex-direction:column}
  .frame-phone{width:100%;height:800px}
  .phone-wrap{width:100%}
}
/* Телефон: рамки заменяются списком ссылок.
   Рамка шириной 390 px на экране 390 px — это страница внутри страницы,
   прочитанная в масштабе телефона: 17 000 px пустоты и ни одного различимого
   экрана. Ссылка открывает ту же страницу на весь экран, где её видно.
   `min-height`/`border` убираются вместе с содержимым, иначе остались бы
   высокие пустые прямоугольники. */
@media (max-width:600px){
  .frame{display:none}
  .frame-link{
    display:flex;align-items:center;justify-content:space-between;gap:12px;
    min-height:0;padding:13px 14px;margin-top:8px;
    border:1px solid #bfc1b3;border-radius:3px;background:#f4f4ef;
    color:var(--ink);font-size:.86rem;line-height:1.3;text-decoration:none}
  .frame-link::after{content:"открыть";font-family:var(--mono);font-size:.7rem;
    color:var(--mute);flex:none}
  .frame-link[data-label]::before{content:attr(data-label)}
  /* Подпись остаётся под своей ссылкой и жмётся к ней: сверху 8 px, снизу
     18 px. Раньше она шла через 20 px после вырезанной рамки и читалась как
     подпись к следующему экрану. */
  .screens{gap:0}
  .cap{margin:8px 0 18px}
  .phone-wrap{width:100%}
}
</style>
</head>
<body>
<header class="sheet">
  <h1>Два направления, один предмет</h1>
  <p>Оба макета показывают один и тот же момент жизни хаба — то же поколение,
     тот же последний обход, те же источники. Цифры не набраны руками: они
     приходят из снимков, снятых с работающего сервера, поэтому сравнивать можно
     композицию, а не данные. Пустые состояния — отдельные экраны: «ещё нет
     поколения» это не ноль, и показывать его нулём было бы враньём.</p>
  <p>У направления A главная собрана в двух версиях, чтобы выбирать не эпитет,
     а весь порядок доказательства: <b>Free VPN</b> снимает подозрение списком
     того, чего сервис не даёт, <b>VPN за $1</b> объясняет, за что платят.
     Остальные экраны у обеих версий общие. Карта выходов у A — гибрид: взята
     из направления B и перекрашена в палитру «Вахты».</p>
</header>
<div class="tabs"><a href="#a"><b>A</b> · Вахта</a><a href="#b"><b>B</b> · Атлас выходов</a></div>

<section class="dir" id="a">
  <div class="dir-head">
    <div>
      <h2><span>Направление A</span>Вахта</h2>
      <p class="say">Хаб — приборная комната: тёмный грунт, одна шкала,
        показания за прошлый обход. Главный артефакт — табло воронки, потому что
        продукт здесь не список адресов, а работа сита.</p>
      <p class="say"><b>Гибрид (отмечен, не реализован).</b> Карта выходов взята
        из направления B — равнопромежуточная проекция, берег Natural Earth,
        точки по измеренным странам — и перекрашена в палитру «Вахты». В
        продуктовый фронтенд (<code>src/hub/ui/</code>) это не переносилось:
        отметка сделана только в макете.</p>
    </div>
    <div>
      <dl>
        <dt>цвет</dt><dd>синий грунт <code>#0b101a</code>, единственный акцент
          <code>#8f9bff</code> — только для подтверждённых измерений</dd>
        <dt>шрифт</dt><dd>Unbounded · Golos Text · JetBrains Mono</dd>
        <dt>сетка</dt><dd>вертикальный рельс навигации и полотно 1240&nbsp;px;
          разделы открываются линией, а не карточкой</dd>
        <dt>принцип</dt><dd>акцент никогда не на кнопке: кнопка — действие,
          цвет — измерение</dd>
      </dl>
      <div class="swatches">
        <i style="background:#0b101a"></i><i style="background:#111826"></i>
        <i style="background:#8f9bff"></i><i style="background:#9aa7bf"></i>
        <i style="background:#e9eef7"></i><i style="background:#f0b45e"></i>
        <em>грунт · панель · подтверждено · текст · бумага · отказ</em>
      </div>
    </div>
  </div>
  <div class="screens">
    {a_free}
    <p class="cap"><b>Главная · Free VPN.</b> Обещание бесплатности стоит
      первым, и сразу за ним — раздел «что здесь значит бесплатно»: восемь
      пунктов в две колонки, что даётся и чего нет. Сначала снимается
      подозрение, потом показывается работа. Карта и реестр — один раздел:
      карта отвечает «где», реестр — «сколько».</p>
    {a_dollar}
    <p class="cap"><b>Главная · VPN за $1.</b> Цена — главный артефакт: она
      стоит числом, и рядом расшифровка, за что именно. Следом воронка, потому
      что за доллар покупают измерение, а не серверы. FAQ здесь не общий, а о
      цене.</p>
    {a_status}
    <p class="cap"><b>Состояние пула.</b> История обходов столбиками: разброс в
      разы виден как форма, а не читается как «данные сломались».</p>
    <div class="pair">
      <div class="phone-wrap">
        {a_phone}
        <p class="cap"><b>Телефон · Free.</b> Рельс уходит, карта становится
          выше, реестр — одноколоночным.</p>
      </div>
      <div class="phone-wrap">
        {a_phone_d}
        <p class="cap"><b>Телефон · $1.</b> Тот же экран в другой посылке:
          цена над сгибом.</p>
      </div>
      <div style="flex:1 1 420px;min-width:300px">
        {a_login}
        <p class="cap"><b>Вход.</b> Один секрет, без пользователя. Поле набрано
          моноширинно: секрет читают по символу.</p>
      </div>
    </div>
    {a_admin}
    <p class="cap"><b>Панель оператора.</b> Показания, воронка, страны,
      источники — одним рабочим листом.</p>
    {a_keys}
    <p class="cap"><b>Ключи.</b> Выданный ключ выглядит квитанцией: его
      забирают, а не пролистывают.</p>
    {a_empty}
    <p class="cap"><b>Пустое состояние.</b> Новая установка: «ещё не готово»
      показано как порядок действий, а не как ноль.</p>
  </div>
</section>

<section class="dir" id="b">
  <div class="dir-head">
    <div>
      <h2><span>Направление B</span>Атлас выходов</h2>
      <p class="say">Хаб — карта, на которой отмечено только измеренное. Светлый
        лист, крупная антиква, координатная сетка вместо линейки и точки по
        реальным странам выхода — без береговых линий, потому что хаб знает
        страны, а не берега.</p>
    </div>
    <div>
      <dl>
        <dt>цвет</dt><dd>холодный белый <code>#f7f7f3</code>, чернила
          <code>#14161a</code>, единственный акцент — оксид меди
          <code>#0f6b5c</code></dd>
        <dt>шрифт</dt><dd>Literata (одна антиква на всё, переменная по кеглю) ·
          JetBrains Mono (координаты)</dd>
        <dt>сетка</dt><dd>двенадцать видимых колонок, асимметричный герой:
          узкий текст слева, карта справа</dd>
        <dt>принцип</dt><dd>структурная линия = координата. Ничего не заключено
          в рамку; карта держит страницу, текст её комментирует</dd>
      </dl>
      <div class="swatches">
        <i style="background:#f7f7f3"></i><i style="background:#ebece4"></i>
        <i style="background:#0f6b5c"></i><i style="background:#14161a"></i>
        <i style="background:#5c6157"></i><i style="background:#a5502a"></i>
        <em>лист · подложка · выход · чернила · подпись · отказ</em>
      </div>
    </div>
  </div>
  <div class="screens">
    {b_landing}
    <p class="cap"><b>Главная.</b> Карта измеренных точек выхода как герой
      страницы; реестр стран — оглавление атласа с отточиями.</p>
    {b_status}
    <p class="cap"><b>Состояние пула.</b> Та же история обходов, но как панель
      с осью времени и подписями на полях.</p>
    <div class="pair">
      <div class="phone-wrap">
        {b_phone}
        <p class="cap"><b>Телефон.</b> Сетка становится двумя колонками, карта
          сжимается в полосу, строки атласа идут в один столбец.</p>
      </div>
      <div style="flex:1 1 420px;min-width:300px">
        {b_login}
        <p class="cap"><b>Вход.</b> Форма как бланк: подпись над полем, линия
          вместо рамки.</p>
      </div>
    </div>
    {b_admin}
    <p class="cap"><b>Панель оператора.</b> Тот же бланк, но плотный: показания
      поколения, воронка, страны и источники в двух колонках.</p>
    {b_keys}
    <p class="cap"><b>Ключи.</b> Выданный ключ как отрывной талон с перфорацией.</p>
    {b_empty}
    <p class="cap"><b>Пустое состояние.</b> Пустой атлас с настоящей сеткой и
      пояснением, чего в нём ещё нет.</p>
  </div>
</section>

<p class="note-row">Обе страницы открываются отдельно — щёлкните рамку. Собрано
  <code>docs/design/src/build_directions.py</code> из снимков
  <code>docs/design/fixtures/</code>; внешних запросов нет, шрифты лежат в
  <code>assets/fonts/</code>.</p>

<footer>hub · два направления · один набор данных · собрано {date}</footer>
</body>
</html>
"""


def main() -> int:
    PAGES.mkdir(parents=True, exist_ok=True)

    # Стили кладутся рядом со страницами, а не читаются из `src/`. Причина —
    # относительные `url("../assets/fonts/…")`: из `pages/` этот путь ведёт в
    # `docs/design/assets/fonts`, и страница открывается прямо из `file://`.
    # Копию пишет сборщик, а не человек: `cp` после правки CSS — это ровно та
    # связка, которая однажды забывается, и макет начинает показывать старую
    # вёрстку с новой разметкой. Здесь это уже случилось — карта получила
    # берег, а страница отрисовала его чёрным, потому что `pages/b.css` был
    # снят до правки.
    for name, src in (("a.css", HERE / "a" / "a.css"), ("b.css", HERE / "b" / "b.css")):
        (PAGES / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    d = data.load()
    empty = data.empty()
    stamp = (PAGES.parent / "src" / "data.py").stat().st_mtime

    pages = {
        "a-1-free": dir_a.landing_free(d),
        "a-2-dollar": dir_a.landing_dollar(d),
        "a-3-status": dir_a.status(d),
        "a-4-login": dir_a.login(),
        "a-5-admin": dir_a.admin(d),
        "a-6-keys": dir_a.keys(d),
        "a-7-empty": dir_a.landing_empty(empty),
        "b-1-landing": dir_b.landing(d),
        "b-2-status": dir_b.status(d),
        "b-3-login": dir_b.login(),
        "b-4-admin": dir_b.admin(d),
        "b-5-keys": dir_b.keys(d),
        "b-6-empty": dir_b.landing_empty(empty),
    }
    for name, markup in pages.items():
        (PAGES / f"{name}.html").write_text(markup, encoding="utf-8")

    # `pages/` — каталог сборки, а не склад. Страница, которую больше не
    # собирают, но которая осталась на диске, — это не «старый файл», а
    # вторая версия того же экрана, открываемая по прямой ссылке, и она
    # показывает вёрстку до правок. Так остались `a-1-landing.html` … после
    # того как экраны A переименовали: сборщик писал новые файлы, а старые
    # продолжали лежать рядом и отдаваться по `/design/pages/`.
    expected = {f"{name}.html" for name in pages}
    for old in PAGES.glob("*.html"):
        if old.name not in expected:
            old.unlink()

    import datetime

    out = SHELL
    for k, v in dict(
        a_free=frame("pages/a-1-free.html", "wide", "A · главная: Free VPN"),
        a_dollar=frame("pages/a-2-dollar.html", "wide", "A · главная: VPN за $1"),
        a_phone=frame("pages/a-1-free.html", "phone", "A · главная на телефоне"),
        a_phone_d=frame("pages/a-2-dollar.html", "phone", "A · $1 на телефоне"),
        a_status=frame("pages/a-3-status.html", "status", "A · состояние пула"),
        a_login=frame("pages/a-4-login.html", "login", "A · вход"),
        a_admin=frame("pages/a-5-admin.html", "admin", "A · панель"),
        a_keys=frame("pages/a-6-keys.html", "admin", "A · ключи"),
        a_empty=frame("pages/a-7-empty.html", "wide", "A · пустое состояние"),
        b_landing=frame("pages/b-1-landing.html", "wide", "B · главная"),
        b_status=frame("pages/b-2-status.html", "status", "B · состояние пула"),
        b_phone=frame("pages/b-1-landing.html", "phone", "B · главная на телефоне"),
        b_login=frame("pages/b-3-login.html", "login", "B · вход"),
        b_admin=frame("pages/b-4-admin.html", "admin", "B · панель"),
        b_keys=frame("pages/b-5-keys.html", "admin", "B · ключи"),
        b_empty=frame("pages/b-6-empty.html", "wide", "B · пустое состояние"),
        date=datetime.date.fromtimestamp(stamp).isoformat(),
    ).items():
        out = out.replace("{" + k + "}", v)
    OUT.write_text(out, encoding="utf-8")
    size = sum(p.stat().st_size for p in PAGES.glob("*.html"))
    print(f"{OUT} · {OUT.stat().st_size / 1024:.0f} КБ · страниц {len(pages)} · {size / 1024:.0f} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
