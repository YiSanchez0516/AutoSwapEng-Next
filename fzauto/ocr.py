"""PaddleOCR 封装.

只在这里依赖 paddleocr; 其它模块离线可运行. 兼容 PaddleOCR 2.x / 3.x
两套返回结构, 统一成 Line 列表.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .config import Config

# 在导入 paddle 之前限制线程数, 避免 OpenBLAS 多线程警告
if os.environ.get("OMP_NUM_THREADS") not in ("1", "2", "4", "8"):
    os.environ["OMP_NUM_THREADS"] = "1"


@dataclass
class Line:
    text: str
    score: float
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def cx(self) -> int:
        return (self.x1 + self.x2) // 2

    @property
    def cy(self) -> int:
        return (self.y1 + self.y2) // 2

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    def distance_to(self, x: int, y: int) -> int:
        return abs(self.cx - x) + abs(self.cy - y)


_LATIN_SINGLE = re.compile(r"^(?:[A-Za-z]\s+){2,}[A-Za-z]$")


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ").strip()
    text = re.sub(r"[ \t]{2,}", " ", text)
    # 中文之间被 OCR 插入的空格去掉, 便于匹配与显示
    text = re.sub(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])", "", text)
    if _LATIN_SINGLE.match(text):
        text = text.replace(" ", "")
    return text


class OcrEngine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.lang = cfg.get("ocr.lang", "ch")
        self.min_score = float(cfg.get("ocr.min_score", 0.45))
        self.upscale = float(cfg.get("ocr.upscale", 1.0) or 1.0)
        self._engine = None
        self._mode = ""

    @staticmethod
    def available() -> bool:
        try:
            import paddleocr  # noqa: F401
            return True
        except Exception:
            return False

    def _build(self) -> None:
        if self._engine is not None:
            return
        os.environ.setdefault("GLOG_minloglevel", "3")
        os.environ.setdefault("FLAGS_call_stack_level", "2")
        logging.getLogger("ppocr").setLevel(logging.ERROR)
        try:
            from paddleocr import PaddleOCR
        except Exception as exc:  # pragma: no cover - 环境问题
            raise RuntimeError(
                "未安装 PaddleOCR, 请先运行 install.ps1 或 pip install paddleocr paddlepaddle"
            ) from exc

        attempts = [
            dict(lang=self.lang, use_angle_cls=True, show_log=False,
                 use_gpu=bool(self.cfg.get("ocr.use_gpu", False)),
                 det_limit_side_len=int(self.cfg.get("ocr.det_limit_side_len", 1600)),
                 det_limit_type="max"),
            dict(lang=self.lang, use_angle_cls=True,
                 det_limit_side_len=int(self.cfg.get("ocr.det_limit_side_len", 1600))),
            dict(lang=self.lang, use_angle_cls=True),
            dict(lang=self.lang),
        ]
        last_error: Exception | None = None
        for kwargs in attempts:
            try:
                self._engine = PaddleOCR(**kwargs)
                self._mode = "v2"
                return
            except Exception as exc:  # 3.x 的参数体系不同
                last_error = exc
        # 3.x: 只传 lang, 关闭文档方向/矫正, 减少首次加载时间
        for kwargs in (
            dict(lang=self.lang, use_doc_orientation_classify=False,
                 use_doc_unwarping=False, use_textline_orientation=False),
            dict(lang=self.lang),
        ):
            try:
                self._engine = PaddleOCR(**kwargs)
                self._mode = "v3"
                return
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"PaddleOCR 初始化失败: {last_error}")

    def read(self, image: Image.Image) -> list[Line]:
        self._build()
        assert self._engine is not None
        work = image.convert("RGB")
        if self.upscale and self.upscale > 1.01:
            work = work.resize(
                (int(work.width * self.upscale), int(work.height * self.upscale)),
                Image.LANCZOS,
            )
        try:
            import numpy as np
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("缺少 numpy, 请重新安装依赖") from exc
        array = np.array(work)

        result = None
        error: Exception | None = None
        for call in (
            lambda: self._engine.ocr(array, cls=True),
            lambda: self._engine.ocr(array),
            lambda: self._engine.predict(array),
        ):
            try:
                result = call()
                if result is not None:
                    break
            except TypeError as exc:
                error = exc
                continue
            except Exception as exc:  # 识别失败时换下一种调用方式
                error = exc
                continue
        if result is None:
            if error is not None:
                raise RuntimeError(f"OCR 识别失败: {error}")
            return []

        lines = _parse_result(result, self.min_score)
        scale = self.upscale if self.upscale > 1.01 else 1.0
        if scale != 1.0:
            for line in lines:
                line.x1 = int(line.x1 / scale)
                line.y1 = int(line.y1 / scale)
                line.x2 = int(line.x2 / scale)
                line.y2 = int(line.y2 / scale)
        lines.sort(key=lambda item: (item.cy, item.cx))
        return lines

    def read_zoom(
        self, image: Image.Image, box: tuple[int, int, int, int],
        scale: int = 2, pad: int = 24,
    ) -> list[Line]:
        """放大局部再识别, 用于短单词/小字号区域."""
        cropped = image.crop(box)
        cropped = cropped.resize(
            (cropped.width * scale, cropped.height * scale), Image.LANCZOS
        )
        gray = ImageOps.autocontrast(cropped.convert("L")).convert("RGB")
        padded = Image.new("RGB", (gray.width + pad * 2, gray.height + pad * 2), "white")
        padded.paste(gray, (pad, pad))
        lines = self.read(padded)
        ox, oy = box[0] - pad / scale, box[1] - pad / scale
        for line in lines:
            line.x1 = int(line.x1 / scale + ox)
            line.x2 = int(line.x2 / scale + ox)
            line.y1 = int(line.y1 / scale + oy)
            line.y2 = int(line.y2 / scale + oy)
        return lines


def _parse_result(result, min_score: float) -> list[Line]:
    lines: list[Line] = []

    def add(text, score, points):
        text = normalize_text(str(text))
        if not text or float(score) < min_score:
            return
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        lines.append(Line(
            text=text, score=float(score),
            x1=int(min(xs)), y1=int(min(ys)),
            x2=int(max(xs)), y2=int(max(ys)),
        ))

    def walk(node, depth: int = 0) -> None:
        if node is None or depth > 5:
            return
        if isinstance(node, dict):
            texts = node.get("rec_texts") or node.get("texts")
            scores = node.get("rec_scores") or node.get("scores") or []
            polys = (node.get("rec_polys") or node.get("dt_polys")
                     or node.get("rec_boxes") or node.get("boxes"))
            if texts and polys is not None:
                for index, text in enumerate(texts):
                    score = scores[index] if index < len(scores) else 1.0
                    box = polys[index]
                    points = _to_points(box)
                    if points:
                        add(text, score, points)
                return
            if "res" in node:
                walk(node["res"], depth + 1)
                return
            for value in node.values():
                if isinstance(value, (dict, list, tuple)):
                    walk(value, depth + 1)
            return
        if isinstance(node, (list, tuple)):
            if len(node) == 2 and isinstance(node[1], (list, tuple)) \
                    and len(node[1]) >= 2 and isinstance(node[1][0], str):
                points = _to_points(node[0])
                if points:
                    add(node[1][0], node[1][1], points)
                return
            for item in node:
                walk(item, depth + 1)

    walk(result)
    return lines


def _to_points(box) -> list[tuple[float, float]]:
    try:
        if hasattr(box, "tolist"):
            box = box.tolist()
        if isinstance(box, (list, tuple)):
            if len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                x1, y1, x2, y2 = box
                return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            points = []
            for point in box:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    points.append((float(point[0]), float(point[1])))
            if len(points) >= 2:
                return points
    except Exception:
        pass
    return []


def draw_debug(image: Image.Image, lines: list[Line], path: Path) -> Path:
    canvas = image.convert("RGB").copy()
    draw = ImageDraw.Draw(canvas)
    font = _font(16)
    for index, line in enumerate(lines):
        draw.rectangle([line.x1, line.y1, line.x2, line.y2], outline=(0, 160, 220), width=2)
        label = f"{index}:{line.text}"
        draw.text((line.x1, max(0, line.y1 - 18)), label, fill=(200, 0, 0), font=font)
        draw.ellipse([line.cx - 3, line.cy - 3, line.cx + 3, line.cy + 3], fill=(0, 200, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)
    return path


def _font(size: int):
    for name in ("msyh.ttc", "simhei.ttf", "arial.ttf"):
        path = Path(r"C:\Windows\Fonts") / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def warm_up(cfg: Config) -> float:
    """预加载模型, 返回耗时秒数, 让用户知道 OCR 是否可用."""
    engine = OcrEngine(cfg)
    started = time.time()
    engine._build()
    return time.time() - started
