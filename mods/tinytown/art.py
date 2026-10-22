"""Vector art sold by TinyTown's Art Market.

Each piece is drawn from whiteboard strokes, so hanging art uses the same
server-authoritative surface pipeline as any player-made whiteboard drawing.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from server.content.surface_props import validate_whiteboard


WIDTH = 1024
HEIGHT = 640


@dataclass(frozen=True, slots=True)
class ArtPiece:
    id: str
    label: str
    description: str
    price: int
    tags: tuple[str, ...]
    surface: dict[str, object]


def _stroke(points: Iterable[tuple[float, float]], color: str, width: float) -> dict[str, object]:
    clean: list[list[float]] = []
    for x, y in points:
        point = [round(max(0.0, min(WIDTH, float(x))), 1), round(max(0.0, min(HEIGHT, float(y))), 1)]
        if not clean or clean[-1] != point:
            clean.append(point)
    if len(clean) > 400:
        step = max(1, len(clean) // 399)
        clean = clean[::step][:399] + [clean[-1]]
    return {"color": color.lower(), "width": max(1.0, min(40.0, float(width))), "points": clean}


def _line(x1: float, y1: float, x2: float, y2: float, color: str, width: float) -> dict[str, object]:
    return _stroke(((x1, y1), (x2, y2)), color, width)


def _polyline(points: Iterable[tuple[float, float]], color: str, width: float) -> dict[str, object]:
    return _stroke(points, color, width)


def _polygon(points: Iterable[tuple[float, float]], color: str, width: float) -> dict[str, object]:
    pts = list(points)
    return _stroke([*pts, pts[0]], color, width) if pts else _stroke((), color, width)


def _fill_polygon(points: list[tuple[float, float]], color: str, step: float = 12.0) -> list[dict[str, object]]:
    if len(points) < 3:
        return []
    y_min = max(0.0, min(y for _x, y in points))
    y_max = min(HEIGHT, max(y for _x, y in points))
    strokes: list[dict[str, object]] = []
    y = y_min + step / 2
    while y < y_max:
        intersections: list[float] = []
        for index, (x1, y1) in enumerate(points):
            x2, y2 = points[(index + 1) % len(points)]
            if (y1 <= y < y2) or (y2 <= y < y1):
                intersections.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        intersections.sort()
        for start, end in zip(intersections[0::2], intersections[1::2]):
            if end - start > 0.5:
                strokes.append(_line(start, y, end, y, color, step + 1))
        y += step
    return strokes


def _fill_rect(x1: float, y1: float, x2: float, y2: float, color: str, step: float = 12.0) -> list[dict[str, object]]:
    return _fill_polygon([(x1, y1), (x2, y1), (x2, y2), (x1, y2)], color, step)


def _circle_points(cx: float, cy: float, radius: float, count: int = 40) -> list[tuple[float, float]]:
    return [
        (cx + math.cos(index / count * math.tau) * radius, cy + math.sin(index / count * math.tau) * radius)
        for index in range(count)
    ]


def _fill_circle(cx: float, cy: float, radius: float, color: str, step: float = 12.0) -> list[dict[str, object]]:
    strokes: list[dict[str, object]] = []
    y = cy - radius + step / 2
    while y < cy + radius:
        half = math.sqrt(max(0.0, radius * radius - (y - cy) * (y - cy)))
        if half > 0.4:
            strokes.append(_line(cx - half, y, cx + half, y, color, step + 1))
        y += step
    return strokes


def _outline_circle(cx: float, cy: float, radius: float, color: str, width: float = 8, count: int = 40) -> dict[str, object]:
    return _stroke(_circle_points(cx, cy, radius, count), color, width)


def _poly_outline(points: list[tuple[float, float]], color: str, width: float = 8) -> dict[str, object]:
    return _polygon(points, color, width)


def _stars(count: int, color: str, seed: int = 1, top: float = 20, bottom: float = 260) -> list[dict[str, object]]:
    strokes: list[dict[str, object]] = []
    value = seed
    for index in range(count):
        value = (value * 1103515245 + 12345) % 2147483647
        x = 30 + (value % 950)
        value = (value * 1103515245 + 12345) % 2147483647
        y = top + (value % int(bottom - top))
        size = 3 + (index % 3) * 2
        strokes.append(_line(x - size, y, x + size, y, color, 3))
        strokes.append(_line(x, y - size, x, y + size, color, 3))
    return strokes


def _sunset_stroll() -> dict[str, object]:
    strokes: list[dict[str, object]] = []
    stops = [(0, 390, "#f9c46b"), (150, 320, "#f58f6f"), (300, 250, "#d96a7a"), (420, 180, "#7d5b8e")]
    for index, (top, bottom, color) in enumerate(stops):
        next_top = stops[index + 1][1] if index + 1 < len(stops) else 0
        strokes.extend(_fill_rect(0, next_top, WIDTH, bottom, color, 14))
    strokes.extend(_fill_circle(790, 275, 72, "#ffe7a3", 10))
    strokes.append(_outline_circle(790, 275, 72, "#fff1c4", 6))
    strokes.extend(_fill_polygon([(0, 470), (210, 360), (410, 480), (580, 380), (820, 500), (1024, 410), (1024, 640), (0, 640)], "#426b66", 12))
    strokes.extend(_fill_polygon([(0, 540), (180, 470), (350, 560), (560, 500), (760, 580), (1024, 520), (1024, 640), (0, 640)], "#244a4c", 12))
    strokes.append(_polyline([(430, 640), (520, 570), (580, 560), (670, 640)], "#e6c28b", 34))
    strokes.append(_polyline([(360, 430), (330, 360), (345, 300)], "#232f39", 4))
    strokes.append(_polyline([(410, 440), (450, 365), (435, 305)], "#232f39", 4))
    strokes.extend(_fill_circle(385, 430, 20, "#2d3b45", 10))
    strokes.append(_line(375, 448, 370, 500, "#2d3b45", 12))
    strokes.append(_line(398, 448, 410, 500, "#2d3b45", 12))
    strokes.append(_line(350, 395, 430, 390, "#e8e0c8", 9))
    strokes.extend(_stars(14, "#ffe9b3", 7, 30, 260))
    return {"strokes": strokes, "texts": []}


def _midnight_harbor() -> dict[str, object]:
    strokes = _fill_rect(0, 0, WIDTH, 420, "#101a36", 14)
    strokes += _stars(38, "#f4d98b", 21, 24, 250)
    strokes += _fill_circle(790, 180, 76, "#f4e7b0", 11)
    strokes.append(_outline_circle(790, 180, 76, "#fff6d3", 7))
    strokes += _fill_rect(0, 420, WIDTH, 640, "#173653", 13)
    horizon = [(0, 420), (1024, 420)]
    strokes.append(_line(*horizon[0], *horizon[1], "#87b8c4", 5))
    for index in range(9):
        y = 450 + index * 20
        strokes.append(_polyline([(40 + (index % 3) * 50, y), (380, y - 6), (760, y + 3), (990, y - 4)], "#3b7690", 4))
    strokes += _fill_polygon([(560, 400), (730, 400), (700, 460), (590, 460)], "#e0c28a", 10)
    strokes.append(_polyline([(610, 400), (610, 260), (640, 245), (670, 260), (670, 400)], "#d6b27b", 9))
    strokes.append(_line(640, 245, 640, 310, "#ffd77d", 8))
    strokes.append(_polyline([(660, 220), (700, 220)], "#f4ce76", 4))
    strokes.append(_polyline([(680, 220), (680, 200), (700, 200)], "#f4ce76", 4))
    strokes += _fill_polygon([(80, 470), (220, 470), (245, 510), (55, 510)], "#203647", 10)
    strokes.append(_polyline([(150, 470), (150, 350), (178, 350), (178, 470)], "#223f58", 5))
    strokes.append(_polygon([(150, 350), (205, 410), (150, 410)], "#f0d394", 5))
    strokes += _fill_polygon([(105, 520), (275, 520), (255, 600), (125, 600)], "#1a2c3c", 11)
    strokes.append(_line(135, 535, 235, 535, "#f1c76e", 6))
    strokes.append(_line(145, 560, 230, 560, "#c48b57", 4))
    strokes.append(_line(190, 600, 190, 640, "#804d3b", 8))
    return {"strokes": strokes, "texts": []}


def _hilltop_bloom() -> dict[str, object]:
    strokes = _fill_rect(0, 0, WIDTH, 300, "#b8d9d2", 13)
    strokes += _fill_circle(210, 145, 54, "#ffe18a", 10)
    strokes += _fill_polygon([(0, 430), (220, 260), (430, 410), (610, 250), (900, 420), (1024, 330), (1024, 640), (0, 640)], "#7f9e63", 13)
    strokes += _fill_polygon([(0, 520), (270, 390), (500, 500), (730, 420), (1024, 520), (1024, 640), (0, 640)], "#4f7557", 13)
    strokes += _fill_rect(0, 600, WIDTH, 640, "#314e41", 12)
    strokes.append(_polyline([(360, 500), (360, 360), (310, 300)], "#59432e", 14))
    strokes.append(_polyline([(360, 380), (420, 310)], "#59432e", 11))
    for cx, cy, color in ((320, 300, "#f6f0df"), (425, 305, "#f6f0df"), (345, 275, "#f4c9d8"), (405, 345, "#f4c9d8"), (365, 335, "#f3e19a")):
        strokes.extend(_fill_circle(cx, cy, 26, color, 10))
        strokes.append(_outline_circle(cx, cy, 26, "#d8a9a1", 3))
    for index in range(20):
        x = 70 + (index * 47) % 900
        y = 560 + (index * 31) % 65
        color = ("#f3d36f", "#e6a2b4", "#f7f1e4", "#c6d986")[index % 4]
        strokes.append(_line(x, y, x, y - 24, "#315b45", 4))
        strokes.extend(_fill_circle(x, y - 28, 7, color, 7))
    strokes.append(_polyline([(470, 640), (540, 570), (680, 560), (790, 640)], "#d6bd8a", 30))
    return {"strokes": strokes, "texts": []}


def _city_lights() -> dict[str, object]:
    strokes = _fill_rect(0, 0, WIDTH, 640, "#18213b", 14)
    strokes += _stars(26, "#f7d97c", 4, 24, 240)
    strokes += _fill_circle(850, 130, 50, "#f5e4a5", 10)
    colors = ("#243149", "#2d3b58", "#394666", "#1d293f", "#41536c")
    buildings = [(40, 250, 160, 620), (180, 320, 290, 620), (310, 190, 430, 620), (450, 360, 545, 620), (560, 230, 690, 620), (710, 290, 820, 620), (840, 170, 980, 620)]
    for index, (x1, y1, x2, y2) in enumerate(buildings):
        strokes += _fill_rect(x1, y1, x2, y2, colors[index % len(colors)], 12)
        strokes.append(_poly_outline([(x1, y1), (x2, y1), (x2, y2), (x1, y2)], "#0e1525", 4))
        for row in range(3):
            for col in range(3):
                wx = x1 + 14 + col * ((x2 - x1 - 28) / 2.7)
                wy = y1 + 18 + row * 34
                lit = (index + row + col) % 3 != 1
                strokes.append(_line(wx, wy, wx + 15, wy, "#ffd979" if lit else "#566177", 7))
    strokes += _fill_polygon([(0, 620), (1024, 620), (1024, 640), (0, 640)], "#0a0f1d", 8)
    strokes.append(_polyline([(80, 620), (120, 590), (160, 620)], "#5f86a5", 5))
    strokes.append(_line(120, 590, 120, 550, "#5f86a5", 4))
    return {"strokes": strokes, "texts": []}


def _tidepool() -> dict[str, object]:
    strokes = _fill_rect(0, 0, WIDTH, 340, "#f7e6c4", 13)
    strokes += _fill_polygon([(0, 340), (260, 300), (510, 350), (760, 290), (1024, 340), (1024, 640), (0, 640)], "#4f9aa0", 13)
    strokes += _fill_polygon([(0, 420), (230, 370), (460, 430), (700, 390), (1024, 445), (1024, 640), (0, 640)], "#347f8c", 13)
    for index in range(16):
        y = 350 + index * 18
        strokes.append(_polyline([(30, y), (250, y - 8), (500, y + 5), (760, y - 4), (990, y + 7)], "#9bd2cf", 4))
    strokes += _fill_polygon([(80, 500), (320, 430), (520, 520), (700, 450), (940, 530), (1024, 600), (1024, 640), (0, 640)], "#e9d29d", 12)
    strokes.extend(_fill_circle(360, 560, 74, "#d9b97c", 11))
    strokes.append(_outline_circle(360, 560, 74, "#b28a52", 5))
    for index in range(12):
        angle = index / 12 * math.tau
        strokes.append(_polyline([(360, 560), (360 + math.cos(angle) * 64, 560 + math.sin(angle) * 64)], "#b28a52", 3))
    strokes += _fill_circle(770, 540, 42, "#f0bb91", 10)
    strokes.append(_outline_circle(770, 540, 42, "#c98767", 5))
    strokes.append(_polyline([(750, 528), (790, 528), (780, 550), (760, 550), (750, 528)], "#c98767", 3))
    strokes.extend(_fill_circle(650, 585, 20, "#f3e4c7", 9))
    strokes.append(_outline_circle(650, 585, 20, "#c3a46f", 4))
    return {"strokes": strokes, "texts": []}


def _cosmic_cat() -> dict[str, object]:
    strokes = _fill_rect(0, 0, WIDTH, 640, "#2a2147", 14)
    strokes += _stars(44, "#f5d47e", 13, 24, 610)
    strokes.extend(_fill_circle(760, 160, 88, "#f0dda2", 11))
    strokes.append(_outline_circle(760, 160, 88, "#fff1c4", 5))
    stars = [(160, 170, 10), (360, 90, 6), (520, 230, 8), (910, 350, 7), (100, 440, 5)]
    for x, y, size in stars:
        strokes.append(_polyline([(x - size, y), (x + size, y)], "#ffe8a2", 4))
        strokes.append(_polyline([(x, y - size), (x, y + size)], "#ffe8a2", 4))
    strokes += _fill_polygon([(300, 610), (300, 420), (340, 340), (380, 360), (420, 300), (500, 300), (540, 360), (600, 340), (640, 420), (640, 610)], "#15172b", 11)
    strokes.append(_poly_outline([(300, 610), (300, 420), (340, 340), (380, 360), (420, 300), (500, 300), (540, 360), (600, 340), (640, 420), (640, 610)], "#7f6ab0", 5))
    strokes.append(_polyline([(640, 520), (760, 470), (820, 380), (880, 390), (900, 450)], "#15172b", 28))
    strokes.append(_polyline([(900, 450), (870, 480), (890, 510)], "#7f6ab0", 6))
    strokes.extend(_fill_circle(405, 440, 12, "#f4df9f", 8))
    strokes.extend(_fill_circle(505, 440, 12, "#f4df9f", 8))
    strokes.append(_line(405, 438, 405, 444, "#2a2147", 4))
    strokes.append(_line(505, 438, 505, 444, "#2a2147", 4))
    strokes.append(_polyline([(440, 480), (455, 490), (470, 480)], "#d98aa5", 4))
    return {"strokes": strokes, "texts": []}


def _little_cottage() -> dict[str, object]:
    strokes = _fill_rect(0, 0, WIDTH, 350, "#cfe4df", 13)
    strokes += _fill_polygon([(0, 410), (240, 320), (470, 400), (720, 310), (1024, 400), (1024, 640), (0, 640)], "#9ebf7f", 13)
    strokes += _fill_rect(0, 470, WIDTH, 640, "#7fa565", 12)
    strokes += _fill_rect(310, 300, 690, 560, "#f0dfbd", 12)
    strokes += _fill_polygon([(270, 310), (500, 150), (730, 310)], "#b95745", 12)
    strokes.append(_polyline([(270, 310), (500, 150), (730, 310)], "#84392e", 7))
    strokes += _fill_rect(455, 430, 545, 560, "#6f4a35", 10)
    strokes.extend(_fill_circle(525, 500, 5, "#e5c879", 6))
    strokes += _fill_rect(355, 365, 425, 420, "#8ac2c4", 10)
    strokes += _fill_rect(575, 365, 645, 420, "#8ac2c4", 10)
    strokes.append(_line(390, 365, 390, 420, "#507d7f", 3))
    strokes.append(_line(610, 365, 610, 420, "#507d7f", 3))
    strokes.append(_polyline([(665, 180), (700, 180), (700, 250), (665, 250), (665, 180)], "#7a4c39", 4))
    strokes.append(_polyline([(680, 180), (680, 130)], "#7a4c39", 3))
    for x, color in ((170, "#e6a2b4"), (245, "#f3d36f"), (780, "#f7f1e4"), (850, "#d8a1c4")):
        strokes.append(_line(x, 575, x, 520, "#416a49", 4))
        strokes.extend(_fill_circle(x, 510, 18, color, 9))
        strokes.extend(_fill_circle(x - 12, 520, 12, color, 9))
    strokes.append(_polyline([(430, 640), (470, 590), (560, 590), (610, 640)], "#d0b987", 28))
    strokes += _stars(10, "#f7f1e4", 8, 30, 250)
    return {"strokes": strokes, "texts": []}


def _golden_orchard() -> dict[str, object]:
    strokes = _fill_rect(0, 0, WIDTH, 260, "#f5e0b3", 13)
    strokes += _fill_circle(170, 120, 46, "#f3b95d", 10)
    strokes += _fill_polygon([(0, 400), (250, 300), (500, 390), (760, 290), (1024, 380), (1024, 640), (0, 640)], "#b9a45f", 13)
    strokes += _fill_rect(0, 520, WIDTH, 640, "#72875a", 12)
    for base_x, scale in ((180, 1.0), (510, 1.25), (840, 0.9)):
        strokes.append(_line(base_x, 560, base_x, 350 * scale + 200, "#654934", 16))
        strokes.append(_line(base_x, 450, base_x - 70 * scale, 370 * scale + 190, "#654934", 9))
        strokes.append(_line(base_x, 470, base_x + 80 * scale, 390 * scale + 180, "#654934", 9))
        for index in range(10):
            angle = index / 10 * math.tau
            fx = base_x + math.cos(angle) * 95 * scale
            fy = 330 * scale + 170 + math.sin(angle) * 75 * scale
            strokes.extend(_fill_circle(fx, fy, 17 * scale, "#e2a33c", 10))
            strokes.extend(_fill_circle(fx, fy, 24 * scale, "#6e8b4e", 14))
    for index in range(10):
        x = 80 + index * 90
        strokes.append(_line(x, 610, x, 570, "#536f45", 4))
        strokes.extend(_fill_circle(x, 562, 9, "#f6e5a8", 9))
    return {"strokes": strokes, "texts": []}


def _abstract_joy() -> dict[str, object]:
    strokes = _fill_rect(0, 0, WIDTH, 640, "#f5efe0", 15)
    strokes += _fill_circle(270, 260, 150, "#ef8b6f", 13)
    strokes += _fill_polygon([(420, 160), (720, 120), (650, 390), (450, 360)], "#5aa6a1", 13)
    strokes += _fill_circle(720, 430, 105, "#f0c85a", 12)
    strokes += _fill_polygon([(80, 610), (220, 380), (330, 610)], "#6f6aa8", 13)
    strokes += _fill_polygon([(540, 610), (660, 430), (820, 610)], "#d7789b", 13)
    strokes.append(_outline_circle(270, 260, 150, "#8a3c2f", 7))
    strokes.append(_poly_outline([(420, 160), (720, 120), (650, 390), (450, 360)], "#2f6664", 7))
    strokes.append(_outline_circle(720, 430, 105, "#8a641c", 7))
    strokes.append(_poly_outline([(80, 610), (220, 380), (330, 610)], "#423d76", 7))
    strokes.append(_poly_outline([(540, 610), (660, 430), (820, 610)], "#8a3c5f", 7))
    for index in range(7):
        x = 160 + index * 118
        y = 90 + (index % 3) * 45
        strokes.append(_polyline([(x - 24, y), (x, y - 24), (x + 24, y), (x, y + 24), (x - 24, y)], "#2f5b67", 5))
    return {"strokes": strokes, "texts": []}


def _dream_train() -> dict[str, object]:
    strokes = _fill_rect(0, 0, WIDTH, 640, "#1e2b4c", 14)
    strokes += _stars(42, "#f4d98b", 31, 24, 400)
    strokes += _fill_circle(180, 120, 54, "#f1dfa8", 10)
    strokes += _fill_polygon([(0, 500), (200, 430), (400, 505), (620, 440), (850, 505), (1024, 460), (1024, 640), (0, 640)], "#162039", 13)
    strokes += _fill_rect(230, 400, 760, 530, "#b24e4e", 11)
    strokes += _fill_rect(230, 400, 350, 470, "#e1b64d", 10)
    strokes += _fill_rect(360, 400, 760, 430, "#e8d6ae", 10)
    for x in (390, 490, 590, 690):
        strokes += _fill_rect(x, 440, x + 62, 495, "#83bcc2", 10)
        strokes.append(_poly_outline([(x, 440), (x + 62, 440), (x + 62, 495), (x, 495)], "#1e2b4c", 4))
    for x in (330, 470, 610, 720):
        strokes.extend(_fill_circle(x, 540, 27, "#1b1d2b", 9))
        strokes.append(_outline_circle(x, 540, 27, "#e0bb66", 4))
        strokes.append(_outline_circle(x, 540, 13, "#e0bb66", 3))
    strokes.append(_polyline([(230, 470), (180, 500), (180, 530), (230, 530)], "#b24e4e", 8))
    strokes.append(_polyline([(760, 450), (820, 450), (820, 510), (760, 500)], "#b24e4e", 6))
    strokes.append(_polyline([(100, 640), (300, 570), (600, 610), (900, 560), (1000, 640)], "#d2ba82", 32))
    for index in range(10):
        x = 250 + index * 62
        sparks = (x, 360 - (index % 3) * 18)
        strokes.append(_line(*sparks, sparks[0] + 10, sparks[1] - 10, "#f0cf72", 4))
    return {"strokes": strokes, "texts": []}


def _friendly_monster() -> dict[str, object]:
    strokes = _fill_rect(0, 0, WIDTH, 640, "#efe3c9", 14)
    strokes += _fill_circle(530, 350, 205, "#84b978", 12)
    strokes += _fill_circle(455, 240, 52, "#84b978", 10)
    strokes += _fill_circle(620, 235, 50, "#84b978", 10)
    strokes.append(_outline_circle(530, 350, 205, "#40633d", 7))
    strokes.append(_outline_circle(455, 240, 52, "#40633d", 5))
    strokes.append(_outline_circle(620, 235, 50, "#40633d", 5))
    strokes.extend(_fill_circle(455, 325, 33, "#fdf6dd", 9))
    strokes.extend(_fill_circle(605, 325, 33, "#fdf6dd", 9))
    strokes.extend(_fill_circle(460, 330, 14, "#27322c", 7))
    strokes.extend(_fill_circle(610, 330, 14, "#27322c", 7))
    strokes.append(_polyline([(430, 450), (500, 480), (570, 455), (635, 485)], "#40633d", 6))
    for x, y in ((390, 555), (460, 590), (600, 585), (660, 545)):
        strokes.extend(_fill_circle(x, y, 26, "#d6a45f", 9))
    strokes.append(_polyline([(320, 370), (260, 330), (250, 285)], "#84b978", 18))
    strokes.append(_polyline([(740, 365), (805, 320), (820, 270)], "#84b978", 18))
    for index in range(8):
        x = 100 + index * 115
        strokes.append(_polyline([(x, 100), (x + 12, 130), (x + 4, 125), (x + 18, 160)], "#e0a35d", 5))
    return {"strokes": strokes, "texts": []}


def _starlight_library() -> dict[str, object]:
    strokes = _fill_rect(0, 0, WIDTH, 640, "#2b2338", 14)
    strokes += _stars(34, "#e9d18a", 17, 24, 300)
    strokes += _fill_rect(80, 250, 410, 590, "#4b3540", 11)
    strokes += _fill_rect(430, 310, 710, 590, "#4b3540", 11)
    for shelf_y in (290, 370, 450, 530):
        strokes.append(_line(95, shelf_y, 395, shelf_y, "#c69a63", 6))
    for shelf_y in (350, 430, 510):
        strokes.append(_line(445, shelf_y, 695, shelf_y, "#c69a63", 6))
    palette = ("#d9846d", "#6fa29b", "#e7c66e", "#9b7fb1", "#d7d2ba")
    for index in range(28):
        x = 110 + (index % 7) * 39
        row = (index // 7) % 4 if index < 25 else 0
        y = 295 + row * 80
        strokes += _fill_rect(x, y - 44, x + 22, y - 4, palette[index % len(palette)], 8)
    for index in range(12):
        x = 458 + (index % 6) * 36
        y = 356 + (index // 6) * 80
        strokes += _fill_rect(x, y - 40, x + 20, y - 4, palette[(index + 2) % len(palette)], 8)
    strokes += _fill_polygon([(760, 550), (990, 550), (950, 590), (800, 590)], "#6b4c3e", 10)
    strokes.append(_polyline([(800, 550), (800, 440), (820, 420), (840, 440), (840, 550)], "#6b4c3e", 9))
    strokes += _fill_polygon([(775, 440), (865, 440), (820, 385)], "#e2c47e", 9)
    strokes += _fill_circle(820, 420, 24, "#f7e7b3", 8)
    strokes.append(_polyline([(740, 590), (730, 640)], "#5b3f34", 10))
    strokes.append(_polyline([(980, 590), (995, 640)], "#5b3f34", 10))
    strokes.append(_polyline([(840, 160), (880, 120), (930, 140), (970, 100)], "#d8b56e", 4))
    return {"strokes": strokes, "texts": []}


def _seed_packet() -> dict[str, object]:
    strokes = _fill_rect(0, 0, WIDTH, 640, "#f2ead8", 14)
    strokes += _fill_polygon([(215, 100), (730, 100), (785, 570), (170, 570)], "#e6c879", 13)
    strokes.append(_poly_outline([(215, 100), (730, 100), (785, 570), (170, 570)], "#7b5d32", 7))
    strokes.extend(_fill_circle(480, 305, 88, "#f3f1dc", 11))
    strokes.append(_outline_circle(480, 305, 88, "#577a45", 5))
    strokes.append(_polyline([(480, 390), (480, 470)], "#577a45", 8))
    strokes.append(_polyline([(480, 420), (430, 375)], "#577a45", 6))
    strokes.append(_polyline([(480, 435), (535, 380)], "#577a45", 6))
    for x, y in ((455, 320), (505, 320), (480, 280), (430, 350), (530, 350)):
        strokes.extend(_fill_circle(x, y, 21, "#6d9c6a", 8))
    for index in range(6):
        x = 300 + index * 75
        strokes.extend(_fill_circle(x, 490, 11, "#e3a53c", 8))
    for index in range(9):
        x = 215 + index * 61
        strokes.append(_line(x, 135, x + 16, 165, "#b99a55", 4))
    return {"strokes": strokes, "texts": []}


def _paper_boats() -> dict[str, object]:
    strokes = _fill_rect(0, 0, WIDTH, 640, "#dcebea", 14)
    strokes += _fill_rect(0, 330, WIDTH, 640, "#5a9ba8", 13)
    for index in range(12):
        y = 360 + index * 23
        strokes.append(_polyline([(30, y), (290, y - 8), (580, y + 4), (860, y - 5), (1000, y + 3)], "#8bc2c7", 4))
    boats = ((240, 410, 1.0), (520, 480, 1.3), (780, 380, 0.85))
    for x, y, scale in boats:
        strokes += _fill_polygon([(x - 95 * scale, y), (x + 105 * scale, y), (x + 55 * scale, y + 55 * scale), (x - 55 * scale, y + 55 * scale)], "#f7f1df", 10)
        strokes.append(_polyline([(x - 90 * scale, y), (x + 100 * scale, y)], "#4d7e8d", 5))
        strokes.append(_polyline([(x, y), (x, y - 120 * scale)], "#775a44", 5))
        strokes += _fill_polygon([(x, y - 115 * scale), (x + 90 * scale, y - 55 * scale), (x, y - 55 * scale)], "#e39a74", 9)
        strokes.append(_polyline([(x - 55 * scale, y + 55 * scale), (x + 55 * scale, y + 55 * scale)], "#8fb5ba", 4))
    strokes += _fill_circle(860, 120, 58, "#f4d88b", 11)
    strokes.append(_outline_circle(860, 120, 58, "#d6a94f", 5))
    strokes += _stars(9, "#6f98a0", 6, 40, 240)
    return {"strokes": strokes, "texts": []}


ART_PIECES = tuple(
    ArtPiece(
        **{
            "id": piece_id,
            "label": label,
            "description": description,
            "price": price,
            "tags": tags,
            "surface": validate_whiteboard(surface),
        }
    )
    for piece_id, label, description, price, tags, surface in (
        ("sunset-stroll", "Sunset Stroll", "A warm evening walk beneath layered hills and a very patient sun.", 25, ("landscape", "warm"), _sunset_stroll()),
        ("midnight-harbor", "Midnight Harbor", "The lighthouse keeps its shift while the boats sleep.", 40, ("sea", "night"), _midnight_harbor()),
        ("hilltop-bloom", "Hilltop Bloom", "Wildflowers holding the last light on a green ridge.", 45, ("landscape", "floral"), _hilltop_bloom()),
        ("city-lights", "City Lights", "A pocket skyline with every window keeping a tiny secret.", 55, ("downtown", "night"), _city_lights()),
        ("tidepool", "Tidepool Treasures", "A shell, a swirl, and the quiet maths of the tide.", 35, ("sea", "nature"), _tidepool()),
        ("cosmic-cat", "Cosmic Cat", "A small cat with an extremely large personal galaxy.", 70, ("space", "cat"), _cosmic_cat()),
        ("little-cottage", "Little Cottage", "A storybook house with flowers that refuse to stay in rows.", 50, ("home", "storybook"), _little_cottage()),
        ("golden-orchard", "Golden Orchard", "Late-season apples and a path that knows the way home.", 60, ("hills", "nature"), _golden_orchard()),
        ("abstract-joy", "Abstract Joy", "A bright argument between shape, colour, and good manners.", 80, ("abstract", "colorful"), _abstract_joy()),
        ("dream-train", "Dream Train", "The last train to somewhere invented, running right on time.", 90, ("night", "travel"), _dream_train()),
        ("friendly-monster", "Friendly Monster", "Large, green, and deeply committed to being liked.", 65, ("character", "playful"), _friendly_monster()),
        ("starlight-library", "Starlight Library", "A reading chair, a tall shelf, and the stars browsing overhead.", 120, ("home", "books"), _starlight_library()),
        ("seed-packet", "Seed Packet", "A cheerful packet of possibility. Plant generously.", 35, ("garden", "botanical"), _seed_packet()),
        ("paper-boats", "Paper Boats", "Three brave little boats crossing a very blue afternoon.", 45, ("sea", "playful"), _paper_boats()),
    )
)

ART_BY_ID = {piece.id: piece for piece in ART_PIECES}


def art_payload(piece: ArtPiece) -> dict[str, object]:
    """Serialize one art piece for the Art Market iframe."""

    return {
        "id": piece.id,
        "label": piece.label,
        "description": piece.description,
        "price": piece.price,
        "tags": list(piece.tags),
        "surface": piece.surface,
    }
