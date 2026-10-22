#!/usr/bin/env python3
"""Собрать контур суши для карты направления B.

    python3 docs/design/src/make_world.py

Читает `docs/design/assets/land-110m.json` (Natural Earth 1:110m через
`world-atlas@2`, public domain) и пишет `docs/design/src/worldpath.py` — одну
строку SVG-пути в той же проекции, что и точки стран:

    x = (lon - LON0) / (LON1 - LON0) * 1000
    y = (LAT0 - lat) / (LAT0 - LAT1) * 400

Рамка 1000 × 400 — это ровно 5:2, и диапазон широт 144° при диапазоне долгот
360° даёт равномасштабную равнопромежуточную проекцию: один градус по
горизонтали и по вертикали — одно и то же число пикселей. Иначе карта была бы
растянута по вертикали, и точки стран стояли бы не там, где их берег.

Зачем вообще берег. Сетка без суши читается как незаконченная карта, а не как
честная: у сетки нет ни одного ориентира, и точка «где-то в Атлантике» ничем
не отличается от точки «в Германии». Берег — это система отсчёта, а не данные
хаба: хаб знает страну выхода, и только её. Поэтому берег рисуется цветом
сетки, а цветом выхода — только измеренная точка.

Упрощение: Дуглас — Пекер с допуском 1,1 из 1000 (≈ 0,4° ≈ 45 км). На 1000 px
это меньше пикселя; выше точность не видна, а путь растёт вдвое.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "assets" / "land-110m.json"
OUT = HERE / "worldpath.py"

LON0, LON1 = -170.0, 190.0
LAT0, LAT1 = 84.0, -60.0
W, H = 1000.0, 400.0
TOL = 1.1


def xy(lon: float, lat: float) -> tuple[float, float]:
    return (
        (lon - LON0) / (LON1 - LON0) * W,
        (LAT0 - lat) / (LAT0 - LAT1) * H,
    )


def _dp(points: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Дуглас — Пекер. Итеративный, чтобы не упираться в предел рекурсии."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        norm = (dx * dx + dy * dy) ** 0.5
        far, idx = -1.0, a
        for i in range(a + 1, b):
            px, py = points[i]
            if norm == 0:
                d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                d = abs(dy * (px - ax) - dx * (py - ay)) / norm
            if d > far:
                far, idx = d, i
        if far > tol:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, k in zip(points, keep) if k]


def rings() -> list[list[tuple[float, float]]]:
    topo = json.loads(SRC.read_text(encoding="utf-8"))
    tr = topo["transform"]
    sx, sy = tr["scale"]
    tx, ty = tr["translate"]

    # Топология хранит точки дельтой: каждая следующая — приращение в квантах.
    # Раскодированные дуги кэшируются, потому что соседние полигоны делят их.
    arcs: list[list[tuple[float, float]]] = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append(xy(tx + x * sx, ty + y * sy))
        arcs.append(pts)

    def ring(indexes: list[int]) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for i in indexes:
            pts = arcs[~i][::-1] if i < 0 else arcs[i]
            out.extend(pts if not out else pts[1:])
        return out

    land = topo["objects"]["land"]["geometries"][0]
    out = []
    for poly in land["arcs"]:
        for r in poly:
            out.append(_dp(ring(r), TOL))
    return out


def path() -> str:
    parts = []
    for r in rings():
        if len(r) < 3:
            continue
        # Замкнутый контур: первый угол округляется до целого, чтобы замыкание
        # совпало побайтно и браузер не рисовал лишний сегмент.
        xs = " ".join(f"{x:.1f},{y:.1f}" for x, y in r)
        parts.append("M" + xs.replace(",", " ") + "Z")
    return "".join(parts)


def main() -> int:
    d = path()
    OUT.write_text(
        '"""Контур суши для карты направления B. Сгенерировано make_world.py.\n\n'
        "Natural Earth 1:110m, public domain, через world-atlas@2.\n"
        f"Проекция: x = (lon + 170) / 360 * 1000, y = (84 − lat) / 144 * 400.\n"
        'Допуск упрощения 1,1 из 1000.\n"""\n\n'
        f'LAND_PATH = (\n    "{d}"\n)\n',
        encoding="utf-8",
    )
    print(f"{OUT} · {len(d) / 1024:.1f} КБ · контуров {d.count('M')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
