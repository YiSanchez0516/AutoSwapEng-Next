"""词库与词典查询: 正查(英->中)、反查(中->英)、缓存、ECDICT、在线兜底."""

from __future__ import annotations

import json
import math
import pickle
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

from .config import CACHE_DIR, Config

CN_RE = re.compile(r"[\u4e00-\u9fff]")
POS_RE = re.compile(r"\b(vt|vi|v|n|adj|adv|prep|pron|conj|num|art|int|aux)\.")
POS_HEAD_RE = re.compile(r"^(vt|vi|v|n|adj|adv|prep|pron|conj|num|art|int|aux)[.·．]", re.I)
ECDICT_POS_RE = re.compile(r"^(vt|vi|v|n|adj|adv|a|ad|prep|pron|conj|num|art|int|aux|abbr)\.", re.I)
SEG_SPLIT_RE = re.compile(r"[；;，,、/|]")
NOISE_RE = re.compile(r"[\[【（(][^\]】）)]*[\]】）)]")

VOCAB_FILE = CACHE_DIR / "vocab.json"
STUDY_FILE = CACHE_DIR / "study.json"
LEARNED_FILE = CACHE_DIR / "learned.json"
DICT_CACHE_FILE = CACHE_DIR / "dict_cache.json"
REVERSE_CACHE = CACHE_DIR / "reverse_index.pkl"


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def clean_segment(text: str) -> str:
    text = NOISE_RE.sub("", text)
    text = POS_RE.sub("", text)
    return "".join(CN_RE.findall(text))


def split_segments(text: str) -> list[str]:
    segments: list[str] = []
    for part in SEG_SPLIT_RE.split(POS_RE.sub("", text)):
        segment = clean_segment(part)
        if segment:
            segments.append(segment)
    return segments


def parse_pos(text: str) -> str | None:
    head = text.strip().lower()
    head = POS_RE.sub("", head)
    match = POS_HEAD_RE.match(head)
    if not match:
        match = re.search(r"\b(vt|vi|v|n|adj|adv|prep|pron|conj|num|art|int|aux)\b",
                          text.lower())
        if not match:
            return None
    pos = match.group(1).lower()
    return "v" if pos in ("vt", "vi") else pos


class Lexicon:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.vocab: dict[str, tuple[list[str], set[str]]] = {}
        self.study: dict[str, list[str]] = {}
        self.learned: dict[str, str] = {}
        self.dict_cache: dict[str, tuple[list[str], set[str]]] = {}
        self._entry_cache: dict[str, tuple[list[str], set[str]]] = {}
        self._reverse: dict[str, list[str]] | None = None
        self._conn: sqlite3.Connection | None = None
        self._freq_cache: dict[str, int] = {}
        self._dirty = False
        self.load()

    # ---------- 载入 ----------
    def load(self) -> None:
        data = None
        pkl = VOCAB_FILE.with_suffix(".pkl")
        try:
            if pkl.exists() and (not VOCAB_FILE.exists()
                                 or pkl.stat().st_mtime >= VOCAB_FILE.stat().st_mtime):
                with pkl.open("rb") as handle:
                    data = pickle.load(handle)
            elif VOCAB_FILE.exists():
                data = json.loads(VOCAB_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, pickle.PickleError, EOFError):
            data = None
        if isinstance(data, dict):
            for word, value in data.items():
                if isinstance(value, list) and len(value) >= 2:
                    self.vocab[word.lower()] = (list(value[0]), set(value[1]))

        for path, target in ((STUDY_FILE, self.study), (LEARNED_FILE, None)):
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if target is None:
                self.learned = {str(k).lower(): str(v) for k, v in payload.items()}
            else:
                target.update({str(k).lower(): [str(i) for i in v]
                               for k, v in payload.items() if isinstance(v, list)})

        if DICT_CACHE_FILE.exists():
            try:
                payload = json.loads(DICT_CACHE_FILE.read_text(encoding="utf-8"))
                self.dict_cache = {
                    str(k).lower(): (list(v[0]), set(v[1]))
                    for k, v in payload.items() if isinstance(v, list) and len(v) == 2
                }
            except (OSError, json.JSONDecodeError):
                pass

    def __len__(self) -> int:
        return len(self.vocab)

    def has_word(self, word: str) -> bool:
        """快速判断本地是否有该词 (不触发联网查询)."""
        key = word.lower().strip()
        if not key:
            return False
        if key in self.vocab or key in self.study or key in self.learned:
            return True
        return self._ecdict(key) is not None

    # ---------- 正查 ----------
    def entry(self, word: str) -> tuple[list[str], set[str]]:
        key = word.lower().strip()
        if key in self._entry_cache:
            return self._entry_cache[key]
        segments: list[str] = []
        pos: set[str] = set()
        found = False

        for candidate in self._candidates(key):
            data = self._ecdict(candidate)
            if data:
                segments.extend(seg for seg in data[0] if seg not in segments)
                pos |= data[1]
                found = True
                break
        if key in self.vocab:
            for seg in self.vocab[key][0]:
                if seg not in segments:
                    segments.append(seg)
            pos |= self.vocab[key][1]
            found = True
        if key in self.study:
            for seg in self.study[key]:
                if seg not in segments:
                    segments.append(seg)
            found = True
        if key in self.learned:
            for seg in split_segments(self.learned[key]):
                if seg not in segments:
                    segments.append(seg)
            found = True

        if not segments and key in self.dict_cache:
            segments, pos = list(self.dict_cache[key][0]), set(self.dict_cache[key][1])
            found = True

        if not found and self.cfg.get("solver.online", True):
            segments, pos = self._online(candidate=key)
            if segments:
                self.dict_cache[key] = (segments, pos)
                self._dirty = True

        self._entry_cache[key] = (segments, pos)
        return segments, pos

    def _candidates(self, word: str) -> list[str]:
        values = [word]
        for variant in (word.replace(" ", ""), word.replace("-", "")):
            if variant and variant not in values:
                values.append(variant)
        return values

    def _ecdict(self, word: str) -> tuple[list[str], set[str]] | None:
        path = self.cfg.ecdict_path
        if path is None:
            return None
        if self._conn is None:
            try:
                self._conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            except sqlite3.Error:
                return None
        try:
            row = self._conn.execute(
                "SELECT translation, pos FROM stardict WHERE word = ? LIMIT 1", (word,)
            ).fetchone()
        except sqlite3.Error:
            return None
        if not row or not row[0]:
            return None
        segments, pos = self._parse_translation(str(row[0]))
        if row[1]:
            pos |= {p.strip().lower() for p in str(row[1]).split("/") if p.strip()}
        return (segments, pos) if segments else None

    @staticmethod
    def _parse_translation(text: str) -> tuple[list[str], set[str]]:
        segments: list[str] = []
        pos: set[str] = set()
        for line in re.split(r"[\n\r]+", text):
            line = NOISE_RE.sub("", line.strip())
            if not line:
                continue
            match = ECDICT_POS_RE.match(line)
            if match:
                value = match.group(1).lower()
                pos.add("v" if value in ("vt", "vi") else
                        ("adj" if value == "a" else ("adv" if value == "ad" else value)))
                line = line[match.end():]
            for part in SEG_SPLIT_RE.split(line):
                segment = clean_segment(part)
                if segment and segment not in segments:
                    segments.append(segment)
        return segments, pos

    def _online(self, candidate: str) -> tuple[list[str], set[str]]:
        for attempt in range(2):
            data = self._youdao(candidate)
            if data:
                segments, pos = self._parse_youdao(data)
                if segments:
                    return segments, pos
            if attempt == 0:
                time.sleep(1.0)
        for source in (self._youdao_suggest, self._bing):
            explain = source(candidate)
            if not explain:
                continue
            segments = split_segments(explain)
            if segments:
                return segments, set()
        return [], set()

    @staticmethod
    def _youdao(word: str) -> dict | None:
        url = "https://dict.youdao.com/jsonapi?q=" + urllib.parse.quote(word)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                return json.loads(response.read().decode("utf-8", "ignore"))
        except Exception:
            return None

    @staticmethod
    def _parse_youdao(data: dict) -> tuple[list[str], set[str]]:
        parts: list[str] = []
        pos: set[str] = set()

        def collect(value) -> None:
            if isinstance(value, str):
                if CN_RE.search(value):
                    parts.append(value)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, dict):
                for key in ("tr", "tran", "trans", "l", "i"):
                    if key in value:
                        collect(value[key])

        for item in data.get("individual", {}).get("trs", []) or []:
            collect(item.get("tran"))
        for word_entry in data.get("ec", {}).get("word", []) or []:
            collect(word_entry.get("trs"))
        for word_entry in data.get("expand_ec", {}).get("word", []) or []:
            collect(word_entry.get("transList"))
        for word_entry in data.get("simple", {}).get("word", []) or []:
            collect([word_entry.get("trans")])

        segments: list[str] = []
        for part in parts:
            for segment in split_segments(part):
                if segment not in segments:
                    segments.append(segment)
            if POS_HEAD_RE.match(part.strip()):
                pos_value = POS_HEAD_RE.match(part.strip()).group(1).lower()  # type: ignore[union-attr]
                pos.add("v" if pos_value in ("vt", "vi") else pos_value)
        return segments, pos

    @staticmethod
    def _youdao_suggest(word: str) -> str | None:
        url = "https://dict.youdao.com/suggest?num=5&doctype=json&q=" + urllib.parse.quote(word)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8", "ignore"))
            for item in data.get("data", {}).get("entries", []) or []:
                if str(item.get("entry", "")).lower() == word.lower():
                    return item.get("explain")
        except Exception:
            return None
        return None

    @staticmethod
    def _bing(word: str) -> str | None:
        url = "https://cn.bing.com/dict/search?q=" + urllib.parse.quote(word)
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"})
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                html = response.read().decode("utf-8", "ignore")
            match = re.search(r'<meta name="description" content="([^"]+)"', html)
            if not match:
                return None
            text = re.sub(r"^.*?释义[，,]", "", match.group(1))
            text = text.split("网络释义")[0]
            text = re.sub(r"[美英]\[[^\]]*\]", "", text)
            return text.strip("；; ")
        except Exception:
            return None

    # ---------- 反查 ----------
    def ensure_reverse(self, verbose: bool = False) -> dict[str, list[str]]:
        if self._reverse is not None:
            return self._reverse
        if REVERSE_CACHE.exists():
            try:
                with REVERSE_CACHE.open("rb") as handle:
                    payload = pickle.load(handle)
                if isinstance(payload, dict) and payload:
                    self._reverse = payload
                    self._merge_reverse_cache()
                    return payload
            except (OSError, pickle.PickleError, EOFError):
                pass
        if verbose:
            print(f"  正在建立中文反查索引 ({len(self.vocab)} 词, 首次约需数秒)...", flush=True)
        reverse: dict[str, list[str]] = {}
        for word, (segments, _pos) in self.vocab.items():
            for segment in segments:
                segment = segment.strip()
                if not segment or len(segment) > 12:
                    continue
                bucket = reverse.setdefault(segment, [])
                if len(bucket) < 3000:
                    bucket.append(word)
        for word, segments in self.study.items():
            for segment in segments:
                bucket = reverse.setdefault(segment.strip(), [])
                if len(bucket) < 3000 and word not in bucket:
                    bucket.append(word)
        for word, text in self.learned.items():
            for segment in split_segments(text):
                bucket = reverse.setdefault(segment, [])
                if len(bucket) < 3000 and word not in bucket:
                    bucket.append(word)
        self._reverse = reverse
        try:
            with REVERSE_CACHE.open("wb") as handle:
                pickle.dump(reverse, handle, protocol=pickle.HIGHEST_PROTOCOL)
        except OSError:
            pass
        return reverse

    def _merge_reverse_cache(self) -> None:
        """把运行中新增的学习记录并入已缓存的反查索引."""
        if self._reverse is None:
            return
        for word, segments in self.study.items():
            for segment in segments:
                bucket = self._reverse.setdefault(segment.strip(), [])
                if word not in bucket:
                    bucket.append(word)
        for word, text in self.learned.items():
            for segment in split_segments(text):
                bucket = self._reverse.setdefault(segment, [])
                if word not in bucket:
                    bucket.append(word)

    def reverse_lookup(
        self, query_segments: Iterable[str], recent: Iterable[str] = (),
        limit: int = 8,
    ) -> list[tuple[str, float]]:
        """中文释义 -> 英文候选, 返回 [(单词, 分数)]."""
        reverse = self.ensure_reverse(verbose=True)
        recent_set = {word.lower() for word in recent}
        queries = []
        for segment in query_segments:
            cleaned = clean_segment(segment)
            if cleaned:
                queries.append(cleaned)
        if not queries:
            return []

        scores: dict[str, float] = {}
        hit_count: dict[str, int] = {}

        for query in queries:
            matched: dict[str, float] = {}
            for word in reverse.get(query, ()):  # 完全一致
                matched[word] = max(matched.get(word, 0.0), 1.0)
            if not matched:
                # 包含关系 (释义被 OCR 拆开/合并)
                for segment, words in reverse.items():
                    if len(segment) < 2:
                        continue
                    if query in segment or segment in query:
                        ratio = min(len(query), len(segment)) / max(len(query), len(segment))
                        for word in words:
                            matched[word] = max(matched.get(word, 0.0), 0.72 * ratio)
                    if len(matched) > 4000:
                        break
            for word, value in matched.items():
                scores[word] = scores.get(word, 0.0) + value
                hit_count[word] = hit_count.get(word, 0) + 1

        if not scores:
            return []

        ranked: list[tuple[str, float]] = []
        for word, total in scores.items():
            score = total / max(1, len(queries))
            if hit_count.get(word, 0) == len(queries):
                score += 0.25
            if word in recent_set:
                score += 1.6
            if word in self.study or word in self.learned:
                score += 0.25
            if " " in word:
                score -= 0.15
            score += self._frequency_bonus(word)
            ranked.append((word, score))
        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked[:limit]

    def _frequency_bonus(self, word: str) -> float:
        if word in self._freq_cache:
            rank = self._freq_cache[word]
        else:
            rank = 0
            path = self.cfg.ecdict_path
            if path is not None:
                if self._conn is None:
                    try:
                        self._conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
                    except sqlite3.Error:
                        self._conn = None
                if self._conn is not None:
                    try:
                        row = self._conn.execute(
                            "SELECT bnc, frq FROM stardict WHERE word = ? LIMIT 1", (word,)
                        ).fetchone()
                        values = [int(v) for v in (row or (0, 0)) if v]
                        rank = min(values) if values else 0
                    except sqlite3.Error:
                        rank = 0
            self._freq_cache[word] = rank
        if not rank:
            return 0.0
        return max(0.0, 0.22 - math.log10(rank) * 0.055)

    # ---------- 学习缓存 ----------
    def remember_study(self, word: str, text: str) -> None:
        key = word.lower().strip()
        segments = split_segments(text)
        if not key or not segments:
            return
        self.study[key] = segments
        try:
            payload = json.loads(STUDY_FILE.read_text(encoding="utf-8")) \
                if STUDY_FILE.exists() else {}
        except (OSError, json.JSONDecodeError):
            payload = {}
        payload[key] = segments
        STUDY_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        if self._reverse is not None:
            for segment in segments:
                bucket = self._reverse.setdefault(segment, [])
                if key not in bucket:
                    bucket.append(key)

    def remember_learned(self, word: str, text: str) -> None:
        key = word.lower().strip()
        if not key or not split_segments(text):
            return
        self.learned[key] = text
        try:
            payload = json.loads(LEARNED_FILE.read_text(encoding="utf-8")) \
                if LEARNED_FILE.exists() else {}
        except (OSError, json.JSONDecodeError):
            payload = {}
        payload[key] = text
        LEARNED_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        if self._reverse is not None:
            for segment in split_segments(text):
                bucket = self._reverse.setdefault(segment, [])
                if key not in bucket:
                    bucket.append(key)

    def flush(self) -> None:
        if not self._dirty:
            return
        try:
            data = {key: [value[0], sorted(value[1])] for key, value in self.dict_cache.items()}
            DICT_CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False),
                                       encoding="utf-8")
        except OSError:
            pass
        self._dirty = False
