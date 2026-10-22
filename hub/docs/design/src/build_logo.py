#!/usr/bin/env python3
"""Лист логотипа PoolNet: варианты знака, размеры, локап, favicon.

    python3 docs/design/src/build_logo.py

Пишет `docs/design/logo.html`. Токены направления D «Созвездие», шрифты —
те же само-хостящиеся файлы; ни одного внешнего запроса. Геометрия знака
считается в питоне (дуги, круги, углы) и собирается в SVG-строку: пропорции
пересчитываются от размера, поэтому полоса размеров показывает честно.
"""

import datetime
import html
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "design" / "logo.html"

VOID, PANEL, GLASS = "#070b13", "#0d1522", "#111a2c"
SIG, SIG_DEEP, TXT, TXT2 = "#6be1ff", "#2fb9ff", "#eaf2ff", "#9db1d4"
OK = "#58e6a6"
MARGIN = 0.09  # поля под glow

#: Счётчик экземпляров знака: фильтр свечения объявляется в каждом SVG со
#: своим id. Один id на весь документ перехватывался первым фильтром с
#: чужим stdDeviation, и мелкие знаки мылись в кашу.
_INSTANCE = 0


def _map(v: float, size: int) -> float:
    return round(MARGIN + v * (1 - 2 * MARGIN) * size, 1)


def _pt(v: tuple[float, float], size: int) -> tuple[float, float]:
    return (_map(v[0], size), _map(v[1], size))


def _node(x: float, y: float, r: float, size: int, filled: bool, sw: float,
          fref: str) -> str:
    return (
        f'<circle cx="{round(x, 1)}" cy="{round(y, 1)}" r="{round(r, 1)}" '
        f'fill="{SIG if filled else VOID}" stroke="{SIG}" stroke-width="{sw}" '
        f'filter="{fref}"/>'
    )


def _stroke(x1: float, y1: float, x2: float, y2: float, w: float,
            opacity: float = 1.0) -> str:
    """Прямой штрих с нарисованным свечением, БЕЗ filter.

    У вертикальной (и любой осевой) линии bbox нулевой ширины или высоты,
    поэтому фильтр с units по bounding box (x=-120%; width=340%) схлопывает
    регион в ноль и элемент рендерится как ничего. Свечение рисуется
    двухслойным штрихом: широкая тихая подложка + тонкое ядро.
    """
    pos = (
        f'x1="{round(x1, 1)}" y1="{round(y1, 1)}" '
        f'x2="{round(x2, 1)}" y2="{round(y2, 1)}" stroke="{SIG}"'
    )
    if opacity < 1.0:
        return f'<line {pos} stroke-opacity="{opacity}" stroke-width="{w}"/>'
    return (
        f'<line {pos} stroke-opacity=".22" stroke-width="{round(w * 2.7, 1)}" '
        f'stroke-linecap="round"/>'
        f'<line {pos} stroke-width="{w}" stroke-linecap="round"/>'
    )


def mark(kind: str, size: int) -> str:
    """Знак в квадрате `size`×`size` как SVG-строка."""
    global _INSTANCE
    _INSTANCE += 1
    f = f"#g{_INSTANCE}"
    sw = max(round(0.014 * size, 1), 1.0)     # обводка узлов
    dot = 0.048 * size                        # обычный узел
    hub = 0.088 * size                        # узел-хаб (светится, залит)

    body = ""
    if kind == "p":
        # «Р»: путь, а не набросок. Стем вертикалью, чаша — дуга радиусом.
        # Совместные точки пути становятся узлами: путь рисуют линии, узлы
        # стоят на изгибах, как станции сети. sweep=1 идёт по часовой:
        # из вершины направо и вниз — чаша выпуклая направо.
        small = size < 48
        sw_node = max(round(0.02 * size, 1), 1.0) if small else sw
        dot = 0.072 * size if small else dot
        bx, top, bot = 0.32, 0.04, 1.0      # стем: x и края по вертикали
        bw = 0.34                            # полуширина чаши (радиус дуги)
        bore = top + 2 * bw                  # низ чаши (0.72)
        x0, y0, y1, yr, nb = (_map(bx, size), _map(top, size),
                              _map(bot, size), _map(bore, size),
                              _map(bx + bw, size))
        r = bw * (1 - 2 * MARGIN) * size
        stem_w = max(round(0.055 * size, 1), 2)
        # стем — прямой штрих: свечение и подложка, фильтра нет.
        body += _stroke(x0, y0, x0, y1, stem_w)
        # чаша — дуга, bbox у неё ненулевой: фильтр допустим.
        body += (
            f'<path d="M{x0},{y0} A{round(r, 1)},{round(r, 1)} 0 0 1 {x0},{yr}" '
            f'stroke="{SIG}" stroke-width="{stem_w}" '
            f'stroke-linecap="round" fill="none" filter="url({f})"/>'
        )
        # узлы: вершина стема, конец чаши (хаб — залит), нога внизу; смычка
        # чаши без своего узла — дуга и так закрывается на стем, точка среди
        # вертикали читалась как «скобка».
        body += _node(x0, y0, dot, size, False, sw_node, f)
        body += _node(nb, round((y0 + yr) / 2, 1), hub, size, True, sw_node, f)
        if not small:
            body += _node(x0, y1, dot, size, False, sw, f)
        # узлы на смычке чаши нет и на больших размерах: дуга закрывается
        # на стем сама, точка посреди вертикали читалась как «скобка».
    elif kind == "ring":
        # Пул: кольцо из шести узлов, соединённых дугой. Выделенный узел —
        # выход: он крупнее, залит и чуть выведен наружу с коротким хвостом.
        c, R = (0.47, 0.44), 0.38
        cxs, cys = _pt(c, size)
        rr = R * (1 - 2 * MARGIN) * size
        body += (
            f'<circle cx="{round(cxs, 1)}" cy="{round(cys, 1)}" '
            f'r="{round(rr, 1)}" fill="none" stroke="{SIG}" '
            f'stroke-opacity=".28" stroke-width="{max(round(0.02 * size, 1), 1)}" '
            f'stroke-dasharray="{round(0.07 * size, 1)} {round(0.055 * size, 1)}"/>'
        )
        for i in range(6):
            a = math.pi / 2 + i * math.pi / 3
            full = i == 0
            x, y = cxs + rr * math.cos(a), cys - rr * math.sin(a)
            if full:
                tail = 0.15
                tx, ty = (cxs + (rr + tail * size) * math.cos(a),
                          cys - (rr + tail * size) * math.sin(a))
                body += _stroke(x, y, tx, ty, max(round(0.04 * size, 1), 1.5),
                                opacity=0.85)
            body += _node(x, y, hub if full else dot, size, full, sw, f)
    elif kind == "mesh":
        # Сеть: хаб в центре, спицы к шести узлам. Самый прямой знак сети —
        # и самый шаблонный: так рисуют буквально всех.
        cxs, cys = _pt((0.5, 0.5), size)
        rr = 0.38 * (1 - 2 * MARGIN) * size
        sat = []
        for i in range(6):
            a = math.pi / 6 + i * math.pi / 3
            x, y = cxs + rr * math.cos(a), cys - rr * math.sin(a)
            body += _stroke(cxs, cys, x, y, max(round(0.02 * size, 1), 1),
                            opacity=0.3)
            sat.append(_node(x, y, dot, size, False, sw, f))
        body += "".join(sat)
        body += _node(cxs, cys, hub, size, True, sw, f)
    elif kind == "tunnel":
        # туннель: два параллельных рельса снизу-слева наверх-направо и
        # три стяга между ними. Узлы — на концах рельсов.
        x0, y0, x1, y1 = 0.06, 0.92, 0.94, 0.10
        dx = 0.22

        def pair(t: float) -> tuple[tuple[float, float], tuple[float, float]]:
            xa, ya = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            return ((xa - dx / 2, ya), (xa + dx / 2, ya))

        rail = max(round(0.05 * size, 1), 2)
        for side in ("left", "right"):
            ax, ay = pair(0.0)[0 if side == "left" else 1]
            bx, by = pair(1.0)[0 if side == "left" else 1]
            body += _stroke(_map(ax, size), _map(ay, size),
                            _map(bx, size), _map(by, size), rail, opacity=0.85)
        for t, hub_side in ((0.0, "left"), (0.5, None), (1.0, "right")):
            (ax, ay), (bx, by) = pair(t)
            if hub_side == "left":
                body += _node(_map(ax, size), _map(ay, size), hub, size, True, sw, f)
            elif hub_side == "right":
                body += _node(_map(bx, size), _map(by, size), hub, size, True, sw, f)
            else:
                body += _node(_map(ax, size), _map(ay, size), dot, size, False, sw, f)
                body += _node(_map(bx, size), _map(by, size), dot, size, False, sw, f)
    else:
        raise ValueError(kind)

    return (
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
        f'role="img" aria-label="Знак PoolNet — вариант {html.escape(kind)}">'
        f'<defs><filter id="g{_INSTANCE}" x="-120%" y="-120%" width="340%" '
        f'height="340%">'
        f'<feGaussianBlur stdDeviation="{round(0.055 * size, 1)}" result="b"/>'
        f'<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>'
        f'</filter></defs>{body}</svg>'
    )


def strip(kind: str) -> str:
    return "".join(
        f'<span class="cell" style="width:{s + 20}px">{mark(kind, s)}</span>'
        for s in (64, 40, 24, 16)
    )


def lockup(kind: str) -> str:
    return (
        '<span class="lockup">' + mark(kind, 46)
        + '<span class="word"><i>p</i>oolnet<i class="tld">.online</i></span></span>'
    )


CARDS = (
    ("p", "Знак-P", (
        "Р, вписанная в сетку узлов: стем и чаша рисуются путём, узлы стоят "
        "на изгибах, как станции сети. Единственный кандидат, где знак "
        "складывается с буквой названия. ИЗБРАН — шагает в продукт."
    ), True),
    ("ring", "Кольцо", (
        "Замкнутый пул из шести узлов, соединённых пунктирной дугой; узел-выход "
        "выведен наружу с коротким хвостом. На 16px остаётся кругом."
    ), True),
    ("mesh", "Сеть", (
        "Хаб со спицами к шести узлам. Самый прямой знак сети — и самый "
        "шаблонный: так рисуют целую отрасль."
    ), False),
    ("tunnel", "Туннель", (
        "Пучок из двух путей со стягами. Ассоциация с VPN наименее наглядная; "
        "включён для полноты выбора."
    ), False),
)

CSS = f"""\
{{FONT_FACES}}
:root{{--void:{VOID};--panel:{PANEL};--glass:{GLASS};--line:rgba(148,180,240,.10);
  --txt:{TXT};--txt-2:{TXT2};--txt-3:#5f7395;--sig:{SIG};--sig-deep:{SIG_DEEP};
  --ok:{OK};--disp:"Unbounded","Manrope",system-ui,sans-serif;
  --sans:"Manrope",system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,monospace}}
*{{box-sizing:border-box}}
html{{background:var(--void)}}
body{{margin:0;background:var(--void);color:var(--txt);font:15px/1.6 var(--sans);
  -webkit-font-smoothing:antialiased}}
header{{max-width:1180px;margin:0 auto;padding:64px 32px 8px}}
header p.kick{{margin:0;font-family:var(--mono);font-size:.78rem;color:var(--sig)}}
header h1{{margin:18px 0 0;font:460 clamp(1.7rem,3.2vw,2.6rem)/1.12 var(--disp)}}
header p{{color:var(--txt-2);max-width:62ch}}
main{{max-width:1180px;margin:0 auto;padding:20px 32px 90px;display:grid;gap:22px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;
  padding:26px 26px 30px;display:grid;grid-template-columns:250px 1fr;gap:26px}}
.card.winner{{border-color:rgba(107,225,255,.38)}}
.card h2{{margin:0;font:560 1.22rem/1.2 var(--disp)}}
.card p{{margin:14px 0 0;color:var(--txt-2);font-size:.9rem}}
.stage{{width:250px;height:250px;border-radius:12px;background:var(--glass);
  border:1px solid var(--line);display:grid;place-items:center}}
.cell{{display:grid;place-items:center;height:64px;border-radius:10px;
  background:var(--glass);border:1px solid var(--line)}}
.row{{display:flex;gap:12px;margin-top:16px;align-items:flex-end;flex-wrap:wrap}}
.lockup{{display:inline-grid;grid-template-columns:46px auto;align-items:center;
  column-gap:16px;padding:20px 24px;border-radius:12px;background:var(--void);
  border:1px solid var(--line);margin-top:18px}}
.word{{font:600 2.1rem/1 var(--disp);font-style:normal;letter-spacing:.01em;
  white-space:nowrap}}
.word i{{font-style:normal;color:var(--sig)}}
.word .tld{{font-weight:340;color:var(--txt-3)}}
@media (max-width:820px){{.card{{grid-template-columns:1fr}}}}
"""


# Шрифты те же, что у листа тёмного направления: само-хостинг рядом.
def _font_faces() -> str:
    faces = ""
    for fam, files in (
        ("Unbounded", ("unbounded-cyrillic.woff2", "unbounded-latin.woff2")),
        ("Manrope", ("manrope-cyrillic-wght-normal.woff2",
                     "manrope-latin-wght-normal.woff2")),
        ("JetBrains Mono", ("jbmono-cyrillic.woff2", "jbmono-latin.woff2")),
    ):
        for path in files:
            face = Path(__file__).resolve().parents[1] / "assets" / "fonts" / path
            assert face.is_file(), face
            faces += (
                f'@font-face{{font-family:"{fam}";src:url("assets/fonts/{path}") '
                f'format("woff2")}}\n'
            )
    return faces


def build() -> None:
    cards = []
    for key, name, note, won in CARDS:
        cards.append(
            f'<article class="card{" winner" if won else ""}">'
            f'<div class="stage">{mark(key, 176)}</div>'
            f'<div><h2>{html.escape(name)}{" — избран" if won else ""}</h2>'
            f'{lockup(key)}'
            f'<div class="row">{strip(key)}</div><p>{html.escape(note)}</p></div>'
            "</article>"
        )
    stamp = datetime.datetime.now(datetime.UTC).strftime("%d.%m.%Y %H:%M UTC")
    page = (
        '<!doctype html>\n<html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        "<title>PoolNet — логотип</title>"
        f"<style>{CSS.replace('{FONT_FACES}', _font_faces())}</style></head><body>"
        '<header><p class="kick">POOLNET — ЗНАК</p>'
        "<h1>Логотип PoolNet: четыре варианта знака</h1>"
        f"<p>Собрало {html.escape(stamp)}. Токены направления D «Созвездие».</p>"
        "</header><main>" + "".join(cards) + "</main></body></html>"
    )
    OUT.write_text(page, encoding="utf-8")
    print(f"written {OUT}")


if __name__ == "__main__":
    build()
