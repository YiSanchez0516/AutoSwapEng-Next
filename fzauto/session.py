"""卡包会话: 识别学习/答题/强化阶段, 记住本卡包单词与错词."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .config import CACHE_DIR
from .ui import Scene, SceneState

SESSION_FILE = CACHE_DIR / "session.json"
STAGE_PROGRESS_RE = re.compile(r"(学习|强化)\s*(\d{1,3})\s*/\s*(\d{1,3})")
PACK_TITLE_RE = re.compile(r"(卡包|词书|词汇)")


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (char_a != char_b),
            ))
        previous = current
    return previous[-1]


def normalize_word(word: str) -> str:
    word = word.lower().replace("’", "'")
    word = re.sub(r"[^a-z'\- ]", "", word)
    return re.sub(r"\s+", " ", word).strip()


@dataclass
class PackSession:
    pack: str = ""
    stage: str = "unknown"  # study / quiz / reinforce / summary / done
    current: int = 0
    total: int = 0
    words: list[str] = field(default_factory=list)
    wrong: list[str] = field(default_factory=list)
    reinforce_entered: bool = False
    updated: float = 0.0

    @classmethod
    def load(cls) -> "PackSession":
        if not SESSION_FILE.exists():
            return cls()
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls(
            pack=str(data.get("pack", "")),
            stage=str(data.get("stage", "unknown")),
            current=int(data.get("current", 0) or 0),
            total=int(data.get("total", 0) or 0),
            words=[str(w) for w in data.get("words", []) if str(w).strip()],
            wrong=[str(w) for w in data.get("wrong", []) if str(w).strip()],
            reinforce_entered=bool(data.get("reinforce_entered", False)),
            updated=float(data.get("updated", 0) or 0),
        )

    def save(self) -> None:
        self.updated = time.time()
        try:
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            SESSION_FILE.write_text(json.dumps({
                "pack": self.pack,
                "stage": self.stage,
                "current": self.current,
                "total": self.total,
                "words": self.words,
                "wrong": self.wrong,
                "reinforce_entered": self.reinforce_entered,
                "updated": self.updated,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---------- 阶段识别 ----------
    def observe(self, scene: Scene, state: SceneState) -> str:
        pack = self._read_pack(scene)
        if pack and pack != self.pack:
            self.pack = pack
            self.words = []
            self.wrong = []
            self.reinforce_entered = False
            self.stage = "unknown"

        header_stage = ""
        for label, current, total in STAGE_PROGRESS_RE.findall(scene.compact):
            if label == "强化":
                header_stage = "reinforce"
                self.current, self.total = int(current), int(total)
                break
            if not header_stage:
                header_stage = "learning"
                self.current, self.total = int(current), int(total)
        if not header_stage:
            current, total = scene.progress()
            if current is not None and total is not None:
                self.current, self.total = current, total

        if state.kind == "done":
            stage = "done"
        elif state.kind == "summary":
            stage = "summary"
        elif "待强化单词" in scene.compact or "遇到错词不要怕" in scene.compact:
            stage = "reinforce"
        elif header_stage == "reinforce" or (self.reinforce_entered and stage_is_reinforce(self.stage)):
            stage = "reinforce"
        elif state.kind == "study":
            stage = "study"
            # 新卡包重新从 0/25 开始学习时, 清掉上一个卡包的单词
            if self.current == 0 and self.words and self.stage not in ("study",):
                self.words = []
                self.wrong = []
                self.reinforce_entered = False
        elif state.kind in ("choice", "spell", "write", "listen"):
            stage = "reinforce" if self.reinforce_entered else "quiz"
        else:
            stage = self.stage if self.stage != "unknown" else "unknown"

        if stage != self.stage:
            self.stage = stage
            self.save()
        return stage

    def _read_pack(self, scene: Scene) -> str:
        for line in scene.lines:
            text = line.text.strip()
            if line.cy > scene.height * 0.18:
                continue
            if len(text) > 42 or not PACK_TITLE_RE.search(text):
                continue
            if "学习" in text or "强化" in text:
                continue
            return text
        return ""

    def mark_reinforce(self) -> None:
        self.reinforce_entered = True
        self.stage = "reinforce"
        self.save()

    def finish(self) -> None:
        self.stage = "done"
        self.save()

    # ---------- 单词记忆 ----------
    def add_word(self, word: str) -> None:
        word = normalize_word(word)
        if word and word not in self.words:
            self.words.append(word)
            self.save()

    def add_wrong(self, word: str) -> None:
        word = normalize_word(word)
        if word and word not in self.wrong:
            self.wrong.append(word)
            self.save()

    def remove_wrong(self, word: str) -> None:
        word = normalize_word(word)
        if word in self.wrong:
            self.wrong.remove(word)
            self.save()

    def correct_word(self, word: str) -> tuple[str, bool]:
        """用本卡包学习过的单词纠正 OCR 误读 (只接受唯一且接近的候选)."""
        cleaned = normalize_word(word)
        if not cleaned or not self.words or cleaned in self.words:
            return cleaned or word, False
        scored = sorted((edit_distance(cleaned, known), known) for known in self.words)
        best_distance, best = scored[0]
        if sum(1 for distance, _ in scored if distance == best_distance) != 1:
            return cleaned, False
        ratio = SequenceMatcher(None, cleaned, best).ratio()
        # 短单词不做纠正, 避免 so/to、on/no 这类误改
        if best_distance == 1 and len(cleaned) >= 3 and cleaned[:1] == best[:1]:
            return best, True
        if best_distance == 2 and len(cleaned) >= 6 and cleaned[:2] == best[:2]:
            return best, True
        if ratio >= 0.90 and len(cleaned) >= 4:
            return best, True
        return cleaned, False


def stage_is_reinforce(stage: str) -> bool:
    return stage == "reinforce"
