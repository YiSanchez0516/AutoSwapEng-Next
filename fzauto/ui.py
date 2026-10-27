"""把 OCR 结果解析成界面元素, 并判断当前处于哪个题型."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import Config
from .ocr import Line, normalize_text
from .screen import Rect

CN_RE = re.compile(r"[\u4e00-\u9fff]")
POS_RE = re.compile(r"\b(vt|vi|v|n|adj|adv|prep|pron|conj|num|art|int|aux)\.")
OPTION_RE = re.compile(r"^([A-Ea-e])\s*[.、．,，:：)）]?\s*(.+)$")
PHONETIC_RE = re.compile(r"^[\[/／].{1,40}[\]/／]$")
LATIN_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'’\- ]{1,30}$")

DONE_WORDS = ("恭喜你完成卡包学习", "恭喜完成", "当前卡包已完成", "任务已完成",
              "已完成今日", "学习完成", "今日任务已完成", "全部完成", "恭喜你完成")
POPUP_WORDS = ("温馨提示", "我知道了", "知道了")
SPELL_WORDS = ("请输入", "输入答案", "输入单词", "点击输入", "拼写", "写一写",
               "根据释义", "写出单词", "请输入单词")
WRITE_WORDS = ("手写", "书写", "手写板", "笔迹", "重写", "清除重写", "写字")
LISTEN_WORDS = ("听力", "播放", "录音", "听音", "听写", "停止录音")
STUDY_WORDS = ("点击卡片", "点击查看", "学习卡片")
SUBMIT_WORDS = ("提交", "确定", "确认", "完成", "下一步", "下一题", "继续",
                "识别", "保存", "开始")
INSTRUCTION_WORDS = ("请", "根据", "释义", "下列", "单词", "提示", "输入", "写出",
                     "选择", "意思", "中文", "英文", "听", "句子", "把", "手写",
                     "书写", "字母", "拼写", "正确", "形式")


@dataclass
class Option:
    letter: str
    text: str
    line: Line

    @property
    def x(self) -> int:
        return self.line.cx

    @property
    def y(self) -> int:
        return self.line.cy


@dataclass
class Keyboard:
    keys: dict[str, tuple[int, int]] = field(default_factory=dict)
    caps: tuple[int, int] | None = None
    delete: tuple[int, int] | None = None
    clear: tuple[int, int] | None = None
    space: tuple[int, int] | None = None
    bbox: Rect | None = None

    def __bool__(self) -> bool:
        return len(self.keys) >= 8


@dataclass
class SceneState:
    kind: str
    word: str | None = None
    options: list[Option] = field(default_factory=list)
    prompt: list[str] = field(default_factory=list)
    keyboard: Keyboard | None = None
    current: int | None = None
    total: int | None = None


class Scene:
    def __init__(self, lines: list[Line], width: int, height: int, cfg: Config):
        self.lines = lines
        self.width = width
        self.height = height
        self.cfg = cfg
        self.text = "".join(normalize_text(line.text) for line in lines)
        self.compact = re.sub(r"\s+", "", self.text)

    # ---------- 基础查询 ----------
    def find_all(self, *keywords: str, region: tuple[float, float, float, float] | None = None) -> list[Line]:
        result = []
        for line in self.lines:
            if region and not self._in_region(line, region):
                continue
            text = line.text.replace(" ", "")
            if all(keyword in text for keyword in keywords):
                result.append(line)
        return result

    def find(self, *keywords: str, region: tuple[float, float, float, float] | None = None) -> Line | None:
        found = self.find_all(*keywords, region=region)
        if not found:
            return None
        found.sort(key=lambda line: (line.cy, line.cx))
        return found[0]

    def has(self, *keywords: str) -> bool:
        return any(all(keyword in line.text.replace(" ", "") for keyword in keywords)
                   for line in self.lines)

    def _in_region(self, line: Line, region: tuple[float, float, float, float]) -> bool:
        fx1, fy1, fx2, fy2 = region
        return (self.width * fx1 <= line.cx <= self.width * fx2
                and self.height * fy1 <= line.cy <= self.height * fy2)

    def progress(self) -> tuple[int | None, int | None]:
        for line in self.lines:
            match = re.search(r"(\d{1,3})\s*/\s*(\d{1,3})", line.text)
            if match:
                return int(match.group(1)), int(match.group(2))
        return None, None

    # ---------- 选择题 ----------
    def options(self) -> list[Option]:
        candidates: list[Option] = []
        for line in self.lines:
            if line.cy < self.height * 0.38:
                continue
            match = OPTION_RE.match(line.text.strip())
            if not match:
                continue
            body = match.group(2).strip()
            if not body:
                continue
            candidates.append(Option(match.group(1).upper(), body, line))

        candidates = self._merge_same_row(candidates)
        candidates = [opt for opt in candidates if CN_RE.search(opt.text)]
        candidates = [opt for opt in candidates
                      if "不确定" not in opt.text and opt.letter != "E"]
        candidates.sort(key=lambda opt: opt.line.cy)

        # 去掉重复行 (同一行被识别成两段)
        deduped: list[Option] = []
        for opt in candidates:
            if deduped and abs(opt.line.cy - deduped[-1].line.cy) < 26:
                if len(opt.text) > len(deduped[-1].text):
                    deduped[-1] = opt
                continue
            deduped.append(opt)

        # 字母缺失或错乱时按行序重排
        letters = [opt.letter for opt in deduped]
        if len(set(letters)) != len(letters) or letters != sorted(letters):
            for index, opt in enumerate(deduped):
                opt.letter = chr(65 + index)
        if len(deduped) >= 2:
            # 选项应左对齐且行距均匀, 否则多半是别的页面
            xs = [opt.line.x1 for opt in deduped]
            ys = sorted(opt.line.cy for opt in deduped)
            gaps = [b - a for a, b in zip(ys, ys[1:])]
            if max(xs) - min(xs) > max(60, self.width * 0.09):
                return []
            if gaps and min(gaps) < max(28, self.height * 0.033):
                return []
        return deduped

    def _merge_same_row(self, options: list[Option]) -> list[Option]:
        merged: list[Option] = []
        for opt in sorted(options, key=lambda o: (o.line.cy, o.line.cx)):
            if merged and abs(opt.line.cy - merged[-1].line.cy) < 24:
                prev = merged[-1]
                if opt.line.x1 < prev.line.x1:
                    opt.text = opt.text + prev.text
                    opt.line = Line(opt.text, opt.line.score, opt.line.x1,
                                    min(opt.line.y1, prev.line.y1), prev.line.x2,
                                    max(opt.line.y2, prev.line.y2))
                    merged[-1] = opt
                else:
                    prev.text += opt.text
                    prev.line = Line(prev.text, prev.line.score, prev.line.x1,
                                     min(prev.line.y1, opt.line.y1), opt.line.x2,
                                     max(prev.line.y2, opt.line.y2))
                continue
            merged.append(opt)
        return merged

    def quiz_word(self, option_list: list[Option] | None = None) -> str | None:
        options = option_list if option_list is not None else self.options()
        ceiling = min((opt.line.cy for opt in options), default=self.height * 0.52) - 24
        best, best_height = None, 0
        for line in self.lines:
            if line.y1 < self.height * 0.08 or line.cy > ceiling:
                continue
            text = line.text.strip()
            if not LATIN_WORD_RE.match(text):
                continue
            letters = re.sub(r"[^A-Za-z]", "", text)
            if len(letters) < 2:
                continue
            if len(letters) < len(text.replace(" ", "")) * 0.6:
                continue
            if line.height > best_height:
                best, best_height = text, line.height
        return best

    def word_anywhere(self) -> str | None:
        """整屏字号最大的英文单词 (学习卡片/拼写页)."""
        best, best_height = None, 0
        for line in self.lines:
            text = line.text.strip()
            if not LATIN_WORD_RE.match(text):
                continue
            letters = re.sub(r"[^A-Za-z]", "", text)
            if len(letters) < 2 or len(letters) < len(text.replace(" ", "")) * 0.6:
                continue
            if line.cy > self.height * 0.82:
                continue
            if line.height > best_height:
                best, best_height = text, line.height
        return best

    def has_phonetic(self, below: str | None = None) -> bool:
        for line in self.lines:
            if PHONETIC_RE.match(line.text.strip()):
                return True
            if re.fullmatch(r"[\[\(/／].{0,20}[\]\)/／]", line.text.strip()):
                return True
        return False

    # ---------- 拼写/手写提示 ----------
    def prompt_segments(self, keyboard_top: int | None = None) -> list[str]:
        """取页面中部的中文提示, 去掉操作说明, 返回释义片段."""
        limit = keyboard_top if keyboard_top else int(self.height * 0.62)
        segments: list[str] = []
        for line in self.lines:
            if line.cy < self.height * 0.10 or line.cy > limit:
                continue
            text = line.text.strip()
            if not CN_RE.search(text):
                continue
            if len(text) > 60:
                continue
            cleaned = re.sub(r"[（(][^）)]*[）)]", "", text)
            for part in re.split(r"[；;，,、/|]", cleaned):
                part = part.strip()
                if not part or not CN_RE.search(part):
                    continue
                part = re.sub(r"^(vt|vi|v|n|adj|adv|prep|pron|conj|num|art|int|aux)"
                              r"[.·．]\s*", "", part, flags=re.I).strip()
                residual = part
                for word in INSTRUCTION_WORDS:
                    residual = residual.replace(word, "")
                if not CN_RE.search(residual):
                    continue  # 整行都是操作说明
                part = re.sub(r"^(请|根据|写出|下列|单词|释义|提示)[:：]?", "", part).strip()
                if part and len(part) <= 24:
                    segments.append(part)
        # 去重并保留顺序
        seen: set[str] = set()
        result = []
        for segment in segments:
            key = re.sub(r"\s+", "", segment)
            if key in seen:
                continue
            seen.add(key)
            result.append(segment)
        return result

    # ---------- 键盘 ----------
    def keyboard(self) -> Keyboard | None:
        kb = Keyboard()
        rows: list[tuple[float, Line, str]] = []
        for line in self.lines:
            if line.cy < self.height * 0.50:
                continue
            text = re.sub(r"\s+", "", line.text)
            if re.fullmatch(r"[a-z]{6,}", text):
                rows.append((line.cy, line, text))
            elif re.fullmatch(r"[a-z]", text.lower()):
                kb.keys[text.lower()] = (line.cx, line.cy)

        for _, line, text in rows:
            step = line.width / len(text)
            for index, char in enumerate(text):
                kb.keys.setdefault(char, (int(line.x1 + step * (index + 0.5)), line.cy))

        for line in self.lines:
            text = line.text.replace(" ", "")
            if any(word in text for word in ("大写", "SHIFT", "Shift", "shift", "⇧")):
                kb.caps = (line.cx, line.cy)
            elif any(word in text for word in ("删除", "退格", "⌫", "←")):
                kb.delete = (line.cx, line.cy)
            elif "清空" in text:
                kb.clear = (line.cx, line.cy)
            elif "空格" in text or "space" in text.lower():
                kb.space = (line.cx, line.cy)

        if len(kb.keys) >= 8 and (len(rows) >= 2 or len(kb.keys) >= 20):
            xs = [point[0] for point in kb.keys.values()]
            ys = [point[1] for point in kb.keys.values()]
            kb.bbox = Rect(min(xs), min(ys), max(xs), max(ys))
            self._fill_missing_keys(kb)
            return kb

        configured = self.cfg.get("keyboard.bbox")
        if configured and self.cfg.get("keyboard.template", True):
            return self.template_keyboard(Rect.from_list(configured))
        return None

    def _fill_missing_keys(self, kb: Keyboard) -> None:
        bbox = Rect.from_list(self.cfg.get("keyboard.bbox"))
        if bbox is None or not bbox.contains(*kb.bbox.center):
            # OCR 只认出一部分键时, 用识别出的键盘范围套 QWERTY 模板
            bbox = kb.bbox.expand(0.02, 0.02) if kb.bbox else None
        if bbox is None:
            return
        for char, point in template_keys(bbox).items():
            kb.keys.setdefault(char, point)

    def keyboard_template_points(self) -> dict[str, tuple[int, int]] | None:
        bbox = Rect.from_list(self.cfg.get("keyboard.bbox"))
        if bbox is None:
            return None
        return template_keys(bbox)

    def template_keyboard(self, bbox: Rect | None) -> Keyboard | None:
        if bbox is None:
            return None
        kb = Keyboard(bbox=bbox)
        kb.keys = template_keys(bbox)
        kb.caps = bbox.point(0.0813, 0.6500)
        kb.delete = bbox.point(0.9315, 0.6045)
        kb.space = bbox.point(0.5000, 0.6800)
        return kb if kb.keys else None

    # ---------- 按钮 ----------
    def submit_line(self) -> Line | None:
        for keyword in ("提交", "确定", "确认", "完成", "下一步", "下一题", "继续", "识别", "保存"):
            found = [line for line in self.lines
                     if keyword in line.text.replace(" ", "") and line.cy > self.height * 0.35]
            if found:
                found.sort(key=lambda line: line.cy, reverse=True)
                return found[0]
        return None

    def button(self, *keywords: str) -> Line | None:
        for line in self.lines:
            text = line.text.replace(" ", "")
            if all(keyword in text for keyword in keywords):
                return line
        return None

    # ---------- 状态 ----------
    def detect(self) -> SceneState:
        current, total = self.progress()

        if any(word in self.compact for word in DONE_WORDS):
            return SceneState("done", current=current, total=total)

        popup = self.button("确定") or self.button("继续") or self.button("我知道了")
        pack_lines = [line for line in self.lines if "卡包" in line.text]
        if popup and (any(word in self.compact for word in POPUP_WORDS)
                      or "选择卡包" in self.compact
                      or len(pack_lines) >= 3):
            # 温馨提示弹窗, 或卡包列表页(标题/多个卡包条目 + 底部确定)
            return SceneState("popup", current=current, total=total)

        options = self.options()
        word = self.quiz_word(options)
        if len(options) >= 2:
            # 单词可能被 OCR 漏读, 交给上层放大补识别
            return SceneState("choice", word=word, options=options,
                              current=current, total=total)

        keyboard = self.keyboard()
        spell_hint = any(word in self.compact for word in SPELL_WORDS)
        if keyboard or spell_hint:
            word = self.word_anywhere()
            if keyboard and keyboard.bbox and word:
                # 键盘行 "qwertyuiop" 会被当成最大英文行, 不能当题目单词
                for line in self.lines:
                    if line.text.strip() == word and keyboard.bbox.contains(line.cx, line.cy):
                        word = None
                        break
            state = SceneState("spell", word=word, keyboard=keyboard,
                               current=current, total=total)
            state.prompt = self.prompt_segments(
                keyboard.bbox.y1 if keyboard and keyboard.bbox else None
            )
            return state

        if any(word in self.compact for word in WRITE_WORDS):
            state = SceneState("write", word=self.word_anywhere(), current=current, total=total)
            state.prompt = self.prompt_segments()
            return state

        # 没有键盘、有中文提示、还有提交/识别按钮: 多半是手写题
        submit = self.submit_line()
        if submit and any(word in submit.text for word in ("提交", "识别", "保存")):
            prompt = self.prompt_segments()
            if prompt:
                return SceneState("write", prompt=prompt, current=current, total=total)

        if any(word in self.compact for word in LISTEN_WORDS):
            return SceneState("listen", current=current, total=total)

        word = self.word_anywhere()
        if word and self.has_phonetic():
            return SceneState("study", word=word, current=current, total=total)
        if any(word in self.compact for word in STUDY_WORDS):
            return SceneState("study", word=word, current=current, total=total)
        return SceneState("unknown", word=word, current=current, total=total)


def template_keys(bbox: Rect) -> dict[str, tuple[int, int]]:
    """原项目校准出的 QWERTY 相对坐标."""
    coords = {
        "a": (0.1081, 2), "b": (0.5959, 3), "c": (0.4008, 3), "d": (0.3048, 2),
        "e": (0.2577, 1), "f": (0.4016, 2), "g": (0.5048, 2), "h": (0.6008, 2),
        "i": (0.7471, 1), "j": (0.6991, 2), "k": (0.7967, 2), "l": (0.8943, 2),
        "m": (0.7910, 3), "n": (0.6934, 3), "o": (0.8447, 1), "p": (0.9463, 1),
        "q": (0.0609, 1), "r": (0.3601, 1), "s": (0.2056, 2), "t": (0.4536, 1),
        "u": (0.6487, 1), "v": (0.4983, 3), "w": (0.1593, 1), "x": (0.3032, 3),
        "y": (0.5520, 1), "z": (0.2056, 3),
    }
    rows = {1: 0.1675, 2: 0.3832, 3: 0.6091}
    return {char: bbox.point(x, rows[row]) for char, (x, row) in coords.items()}
