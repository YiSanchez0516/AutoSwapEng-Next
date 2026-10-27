"""单笔画英文字母表, 用于在手写板上"写"出单词.

坐标: x 向右, y 向下; 基线 0.82, 小写高度顶 0.50, 上伸部 0.10, 下伸部 1.06.
每个字母 = (advance 宽度, [笔画, 笔画, ...]), 笔画是折线点列.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

BASELINE = 0.82
X_HEIGHT = 0.50
CAP_TOP = 0.12
DESCENDER = 1.06
UNIT_HEIGHT = 1.18


def _arc(cx: float, cy: float, rx: float, ry: float,
         start: float, end: float, count: int = 18) -> list[tuple[float, float]]:
    points = []
    for index in range(count + 1):
        angle = math.radians(start + (end - start) * index / count)
        points.append((cx + rx * math.cos(angle), cy + ry * math.sin(angle)))
    return points


def _line(*points: tuple[float, float]) -> list[tuple[float, float]]:
    return list(points)


def _dot(x: float, y: float) -> list[tuple[float, float]]:
    return [(x, y), (x + 0.005, y + 0.005)]


def _circle(cx: float, cy: float, rx: float, ry: float) -> list[tuple[float, float]]:
    return _arc(cx, cy, rx, ry, -90, 270)


GLYPHS: dict[str, tuple[float, list[list[tuple[float, float]]]]] = {
    "a": (0.62, [
        _circle(0.30, 0.67, 0.18, 0.15),
        _line((0.48, 0.50), (0.48, 0.82)),
    ]),
    "b": (0.62, [
        _line((0.10, 0.10), (0.10, 0.82)),
        _arc(0.30, 0.67, 0.18, 0.15, 180, 540),
    ]),
    "c": (0.62, [
        _arc(0.32, 0.67, 0.18, 0.15, 40, 320),
    ]),
    "d": (0.62, [
        _arc(0.30, 0.67, 0.18, 0.15, 180, 540),
        _line((0.50, 0.10), (0.50, 0.82)),
    ]),
    "e": (0.62, [
        [(0.12, 0.66), (0.50, 0.66)] + _arc(0.31, 0.72, 0.18, 0.13, 0, -300),
    ]),
    "f": (0.52, [
        _line((0.40, 0.15), (0.32, 0.10), (0.22, 0.12), (0.19, 0.22), (0.19, 0.82)),
        _line((0.08, 0.45), (0.36, 0.45)),
    ]),
    "g": (0.62, [
        _circle(0.30, 0.67, 0.18, 0.15),
        _line((0.48, 0.50), (0.48, 0.92)) + _arc(0.36, 0.92, 0.12, 0.10, 0, 150),
    ]),
    "h": (0.60, [
        _line((0.10, 0.10), (0.10, 0.82)),
        _line((0.10, 0.58), (0.14, 0.51), (0.24, 0.49), (0.34, 0.53),
              (0.38, 0.61), (0.38, 0.82)),
    ]),
    "i": (0.30, [
        _dot(0.20, 0.42),
        _line((0.20, 0.54), (0.20, 0.82)),
    ]),
    "j": (0.32, [
        _dot(0.28, 0.42),
        _line((0.28, 0.54), (0.28, 0.98), (0.24, 1.04), (0.16, 1.04), (0.11, 0.98)),
    ]),
    "k": (0.58, [
        _line((0.10, 0.10), (0.10, 0.82)),
        _line((0.10, 0.62), (0.36, 0.44)),
        _line((0.20, 0.55), (0.40, 0.82)),
    ]),
    "l": (0.34, [
        _line((0.20, 0.10), (0.20, 0.74), (0.24, 0.81), (0.30, 0.82)),
    ]),
    "m": (0.78, [
        _line((0.09, 0.50), (0.09, 0.82)),
        _line((0.09, 0.58), (0.14, 0.50), (0.23, 0.49), (0.30, 0.55), (0.30, 0.82)),
        _line((0.30, 0.58), (0.36, 0.50), (0.45, 0.49), (0.52, 0.56), (0.52, 0.82)),
    ]),
    "n": (0.58, [
        _line((0.12, 0.50), (0.12, 0.82)),
        _line((0.12, 0.58), (0.18, 0.50), (0.29, 0.49), (0.37, 0.55),
              (0.38, 0.64), (0.38, 0.82)),
    ]),
    "o": (0.62, [
        _circle(0.30, 0.67, 0.18, 0.15),
    ]),
    "p": (0.62, [
        _line((0.10, 0.50), (0.10, 1.06)),
        _arc(0.28, 0.67, 0.18, 0.15, 180, 540),
    ]),
    "q": (0.62, [
        _arc(0.28, 0.67, 0.18, 0.15, 180, 540),
        _line((0.46, 0.50), (0.46, 1.06)),
    ]),
    "r": (0.48, [
        _line((0.12, 0.50), (0.12, 0.82)),
        _line((0.12, 0.62), (0.18, 0.53), (0.28, 0.50), (0.38, 0.52)),
    ]),
    "s": (0.56, [
        _line((0.40, 0.55), (0.34, 0.50), (0.24, 0.49), (0.17, 0.53),
              (0.17, 0.60), (0.23, 0.65), (0.33, 0.68), (0.40, 0.73),
              (0.40, 0.79), (0.33, 0.83), (0.22, 0.83), (0.14, 0.78)),
    ]),
    "t": (0.46, [
        _line((0.24, 0.14), (0.24, 0.74), (0.28, 0.81), (0.35, 0.82)),
        _line((0.10, 0.38), (0.40, 0.38)),
    ]),
    "u": (0.58, [
        _line((0.10, 0.50), (0.10, 0.72), (0.14, 0.80), (0.24, 0.83),
              (0.34, 0.80), (0.38, 0.72), (0.38, 0.82)),
    ]),
    "v": (0.56, [
        _line((0.10, 0.50), (0.28, 0.82), (0.46, 0.50)),
    ]),
    "w": (0.72, [
        _line((0.08, 0.50), (0.20, 0.82), (0.30, 0.58), (0.40, 0.82), (0.52, 0.50)),
    ]),
    "x": (0.56, [
        _line((0.10, 0.50), (0.42, 0.82)),
        _line((0.42, 0.50), (0.10, 0.82)),
    ]),
    "y": (0.58, [
        _line((0.10, 0.50), (0.28, 0.82)),
        _line((0.44, 0.50), (0.30, 0.86), (0.24, 0.98), (0.18, 1.03), (0.12, 1.02)),
    ]),
    "z": (0.56, [
        _line((0.12, 0.52), (0.42, 0.52), (0.14, 0.80), (0.42, 0.80)),
    ]),
    "0": (0.58, [_circle(0.29, 0.48, 0.16, 0.36)]),
    "1": (0.36, [_line((0.10, 0.22), (0.22, 0.14), (0.22, 0.82))]),
    "2": (0.56, [
        [(0.12, 0.28), (0.20, 0.16), (0.34, 0.14), (0.44, 0.22), (0.44, 0.32),
         (0.34, 0.44), (0.12, 0.82), (0.46, 0.82)],
    ]),
    "3": (0.56, [
        [(0.12, 0.16), (0.36, 0.16), (0.24, 0.40), (0.38, 0.44), (0.44, 0.58),
         (0.38, 0.76), (0.24, 0.82), (0.12, 0.78)],
    ]),
    "4": (0.58, [
        _line((0.36, 0.14), (0.10, 0.60), (0.48, 0.60)),
        _line((0.36, 0.14), (0.36, 0.82)),
    ]),
    "5": (0.56, [
        [(0.42, 0.16), (0.18, 0.16), (0.16, 0.42), (0.30, 0.38), (0.42, 0.46),
         (0.44, 0.62), (0.36, 0.78), (0.22, 0.82), (0.10, 0.76)],
    ]),
    "6": (0.56, [
        [(0.40, 0.16), (0.26, 0.18), (0.16, 0.34), (0.14, 0.58), (0.20, 0.74),
         (0.32, 0.82), (0.42, 0.76), (0.44, 0.62), (0.36, 0.50), (0.22, 0.50),
         (0.14, 0.58)],
    ]),
    "7": (0.54, [
        _line((0.10, 0.16), (0.44, 0.16), (0.22, 0.82)),
    ]),
    "8": (0.58, [
        _circle(0.29, 0.30, 0.13, 0.14),
        _circle(0.29, 0.66, 0.15, 0.16),
    ]),
    "9": (0.56, [
        [(0.42, 0.40), (0.34, 0.30), (0.22, 0.28), (0.14, 0.36), (0.14, 0.48),
         (0.22, 0.56), (0.36, 0.56), (0.42, 0.48), (0.42, 0.30), (0.34, 0.16),
         (0.20, 0.14)],
    ]),
    "-": (0.42, [_line((0.08, 0.66), (0.34, 0.66))]),
    "'": (0.24, [_line((0.14, 0.12), (0.10, 0.24))]),
    "’": (0.24, [_line((0.14, 0.12), (0.10, 0.24))]),
    " ": (0.34, []),
}


def glyph(char: str) -> tuple[float, list[list[tuple[float, float]]]]:
    if char in GLYPHS:
        return GLYPHS[char]
    lower = char.lower()
    if lower in GLYPHS:
        return GLYPHS[lower]
    return GLYPHS["?"] if "?" in GLYPHS else (0.4, [])


def word_strokes(
    word: str, width: float, height: float,
    margin_x: float = 0.08, margin_y: float = 0.12,
    letter_gap: float = 0.10,
) -> list[list[tuple[float, float]]]:
    """把单词转成像素坐标的笔画列表 (相对画布左上角)."""
    chars = [char for char in word if char in GLYPHS or char.lower() in GLYPHS]
    if not chars:
        return []
    advances = [glyph(char)[0] + letter_gap for char in chars]
    total_advance = sum(advances) - letter_gap
    avail_w = width * (1 - margin_x * 2)
    avail_h = height * (1 - margin_y * 2)
    scale = min(avail_w / total_advance, avail_h / UNIT_HEIGHT)
    total_w = total_advance * scale
    total_h = UNIT_HEIGHT * scale
    offset_x = (width - total_w) / 2
    offset_y = (height - total_h) / 2 + 0.10 * scale

    strokes: list[list[tuple[float, float]]] = []
    cursor = 0.0
    for char, advance in zip(chars, advances):
        for stroke in glyph(char)[1]:
            points = [(offset_x + (cursor + x) * scale, offset_y + y * scale)
                      for x, y in stroke]
            if len(points) >= 2:
                strokes.append(points)
        cursor += advance
    return strokes


def render_preview(word: str, path: Path, width: int = 900, height: int = 360) -> Path:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for stroke in word_strokes(word, width, height, margin_x=0.05, margin_y=0.10):
        draw.line(stroke, fill=(20, 20, 30), width=4, joint="curve")
        draw.ellipse([stroke[0][0] - 3, stroke[0][1] - 3,
                      stroke[0][0] + 3, stroke[0][1] + 3], fill=(220, 60, 60))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def render_grid(path: Path, chars: str = "abcdefghijklmnopqrstuvwxyz") -> Path:
    """把字母表画成网格, 方便检查字形."""
    cell_w, cell_h = 150, 190
    cols = 7
    rows = math.ceil(len(chars) / cols) + 1
    image = Image.new("RGB", (cell_w * cols, cell_h * rows), "white")
    draw = ImageDraw.Draw(image)
    for index, char in enumerate(chars):
        col, row = index % cols, index // cols
        ox, oy = col * cell_w, row * cell_h
        draw.rectangle([ox, oy, ox + cell_w, oy + cell_h], outline=(230, 230, 230))
        draw.text((ox + 6, oy + 4), char, fill=(150, 150, 150))
        factor = min((cell_w - 30) / 0.80, (cell_h - 40) / UNIT_HEIGHT)
        for stroke in glyph(char)[1]:
            points = [(ox + 15 + x * factor, oy + 20 + y * factor) for x, y in stroke]
            if len(points) >= 2:
                draw.line(points, fill=(20, 20, 30), width=3, joint="curve")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path
