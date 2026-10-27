"""配置读写: 所有可调参数集中在这里, 保存在项目根目录 config.json."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config.json"
CACHE_DIR = ROOT / "cache"
CAPTURE_DIR = ROOT / "captures"
LOG_DIR = ROOT / "logs"

DEFAULTS: dict[str, Any] = {
    # 投屏窗口标题片段; 为空时使用 bbox
    "window_title": "",
    # 投屏窗口区域 [x1, y1, x2, y2], 屏幕物理像素
    "bbox": None,
    "ocr": {
        "lang": "ch",
        "min_score": 0.45,
        "use_gpu": False,
        "upscale": 1.0,
        # 检测时把长边放大到该尺寸, 手机屏幕小字更清楚
        "det_limit_side_len": 1600,
    },
    # 拼写页的屏幕键盘; bbox 可手动校准, 不填时自动从 OCR 识别
    "keyboard": {"bbox": None, "template": True},
    # 拼写页输入框的大致点击位置 [x, y], 不填时自动推断
    "spell_input": None,
    # 听力页按钮的屏幕坐标 {"play": [x,y], "record": [x,y], "submit": [x,y], "next": [x,y]}
    "listen": {
        "play": None,
        "record": None,
        "submit": None,
        "next": None,
        # true: 播放 -> 录音 -> 评分 -> 下一题; false: 只播放并等待
        "auto_flow": True,
    },
    # 学习结算后自动进入“强化/巩固”阶段
    "auto_enter_reinforce": True,
    # 跨运行记住当前卡包的学习单词/错词
    "pack_memory": True,
    # 手写板区域 [x1, y1, x2, y2], 不填时自动取中部空白区域
    "write_canvas": None,
    "delays": {
        "click": 0.03,
        "after_click": 0.7,
        "after_swipe": 0.9,
        "between_steps": 0.25,
        "wait_anim": 0.35,
    },
    # tap: 点击屏幕键盘; type: 直接用电脑键盘输入
    "type_method": "tap",
    "handwriting": {
        "speed": 0.004,
        "letter_gap": 0.12,
        "line_gap": 0.06,
        "mode": "word",  # word: 整个单词连续写; letter: 逐字母写在同一区域
        "letter_boxes": 0,  # >1 时把书写区横向等分成 N 格, 每格写一个字母
        "tries": 1,
    },
    "solver": {
        # ECDICT 离线词库路径, 留空则不使用 (见 README)
        "ecdict": "",
        "online": True,
    },
    "max_steps": 300,
    "log_ocr": False,
}


class Config:
    def __init__(self, data: dict[str, Any] | None = None):
        self.data = copy.deepcopy(DEFAULTS)
        if data:
            _deep_update(self.data, data)

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> "Config":
        if not path.exists():
            return cls()
        try:
            return cls(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return cls()

    def save(self, path: Path = CONFIG_FILE) -> None:
        path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for key in dotted.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def set(self, dotted: str, value: Any) -> None:
        keys = dotted.split(".")
        node = self.data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value

    @property
    def bbox(self) -> tuple[int, int, int, int] | None:
        value = self.get("bbox")
        if not value or len(value) != 4:
            return None
        return tuple(int(v) for v in value)  # type: ignore[return-value]

    @property
    def ecdict_path(self) -> Path | None:
        raw = self.get("solver.ecdict") or ""
        path = Path(raw)
        return path if raw and path.exists() else None


def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def ensure_dirs() -> None:
    for folder in (CACHE_DIR, CAPTURE_DIR, LOG_DIR):
        folder.mkdir(parents=True, exist_ok=True)
