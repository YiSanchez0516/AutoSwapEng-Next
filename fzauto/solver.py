"""答题决策: 选择题选项匹配 + 拼写题中英反查."""

from __future__ import annotations

import re
import sqlite3

from .ui import Option
from .words import CN_RE, Lexicon, compact, split_segments

CONFUSABLE = {
    "i": "l1", "l": "i1", "1": "il", "o": "0", "0": "o",
    "j": "y", "y": "j", "c": "e", "e": "c", "u": "v", "v": "u",
    "s": "5", "5": "s", "b": "6", "6": "b",
}
OPTION_POS_RE = re.compile(r"^(n|vt|vi|v|adj|adv|prep|pron|conj|num|art|int|aux)[.·．]")


def longest_common_substring(a: str, b: str) -> int:
    if not a or not b:
        return 0
    previous = [0] * (len(b) + 1)
    best = 0
    for char in a:
        current = [0] * (len(b) + 1)
        for index, other in enumerate(b, 1):
            if char == other:
                current[index] = previous[index - 1] + 1
                best = max(best, current[index])
        previous = current
    return best


def score_option(option_cn: str, segments: list[str]) -> float:
    if not option_cn or not segments:
        return 0.0
    best = 0.0
    for index, segment in enumerate(segments):
        bias = index * 0.001
        if option_cn == segment:
            best = max(best, 1.0 - bias)
        elif len(option_cn) >= 2 and len(segment) >= 2 and (
                option_cn in segment or segment in option_cn):
            best = max(best, 0.9 - bias)
        else:
            common = longest_common_substring(option_cn, segment)
            if common >= 2:
                best = max(best, min(0.8, common / len(option_cn)) - bias)
            elif common == 1 and len(option_cn) <= 3:
                best = max(best, 0.4 - bias)
    if len(option_cn) == 1:
        best = min(best, 0.35)
    return max(best, 0.0)


def option_pos(text: str) -> str | None:
    match = OPTION_POS_RE.match(compact(text).lower())
    if not match:
        return None
    pos = match.group(1)
    return "v" if pos in ("vt", "vi") else pos


def option_segments(text: str) -> list[str]:
    cleaned = re.sub(r"\b(vt|vi|v|n|adj|adv|prep|pron|conj|num|art|int|aux)\.",
                     "", text)
    cleaned = re.sub(r"[（(][^）)]*[）)]", "", cleaned)
    segments = []
    for part in re.split(r"[；;，,、/]", cleaned):
        cn = "".join(CN_RE.findall(part))
        if cn:
            segments.append(cn)
    return segments or [""]


def pick_best(options: list[Option], segments: list[str],
              pos_set: set[str] | None = None) -> tuple[float, Option | None]:
    best_score, best_option = 0.0, None
    for option in options:
        score = max((score_option(cn, segments) for cn in option_segments(option.text)),
                    default=0.0)
        pos = option_pos(option.text)
        if pos and pos_set and pos not in pos_set:
            score *= 0.45
        if score > best_score:
            best_score, best_option = score, option
    return best_score, best_option


def word_variants(word: str) -> list[str]:
    base = word.replace(" ", "").replace("-", "").lower()
    out: list[str] = []

    def add(value: str) -> None:
        if value != base and value not in out:
            out.append(value)

    positions = [(index, alt) for index, char in enumerate(base)
                 for alt in CONFUSABLE.get(char, "")]
    for index, alt in positions:
        add(base[:index] + alt + base[index + 1:])
    for i, (index1, alt1) in enumerate(positions):
        if len(out) >= 48:
            break
        for index2, alt2 in positions[i + 1:]:
            if index1 == index2:
                continue
            chars = list(base)
            chars[index1] = alt1
            chars[index2] = alt2
            add("".join(chars))
            if len(out) >= 48:
                break
    if "rn" in base:
        add(base.replace("rn", "m"))
    if "m" in base:
        add(base.replace("m", "rn"))
    return out[:48]


def _is_subsequence(short: str, long: str) -> bool:
    index = 0
    for char in long:
        if index < len(short) and char == short[index]:
            index += 1
    return index == len(short)


class Solver:
    def __init__(self, lex: Lexicon):
        self.lex = lex
        self._by_len: dict[int, list[str]] = {}
        for word in lex.vocab:
            self._by_len.setdefault(len(word), []).append(word)

    # ---------- 选择题 ----------
    def resolve_word_key(self, word: str) -> str:
        key = compact(word).lower()
        if key in self.lex.vocab or key in self.lex.study:
            return key
        hits = [variant for variant in word_variants(word) if variant in self.lex.vocab]
        if not hits and len(key) >= 4:
            hits = self._fuzzy_hits(key)
        if not hits and len(key) >= 2:
            hits = [k for k in self.lex.study if len(k) == len(key) + 1 and k.endswith(key)]
        return hits[0] if len(hits) == 1 else key

    def _fuzzy_hits(self, key: str) -> list[str]:
        hits = []
        for length in (len(key) - 1, len(key), len(key) + 1):
            for word in self._by_len.get(length, ()):
                if len(word) == len(key) + 1 and _is_subsequence(key, word):
                    hits.append(word)
                elif len(word) == len(key) - 1 and _is_subsequence(word, key):
                    hits.append(word)
                elif len(word) == len(key) and sum(a != b for a, b in zip(word, key)) == 1:
                    hits.append(word)
        return hits

    @staticmethod
    def _learn_match(text: str, learned: str) -> bool:
        a, b = compact(text), compact(learned)
        if a == b:
            return True
        cn_a = "".join(CN_RE.findall(a))
        cn_b = "".join(CN_RE.findall(b))
        if len(cn_a) >= 3 and len(cn_b) >= 3:
            common = longest_common_substring(cn_a, cn_b)
            if common / max(len(cn_a), len(cn_b)) >= 0.7:
                return True
        return False

    def choose_choices(self, word: str, options: list[Option]) -> list[tuple[str, str]]:
        """返回按可信度排序的 [(选项字母, 说明)], 供答错时重试."""
        key = self.resolve_word_key(word)
        ranked: list[tuple[str, str]] = []

        learned = self.lex.learned.get(key)
        if learned and self.meaning_plausible(key, learned):
            for option in options:
                if self._learn_match(option.text, learned):
                    ranked.append((option.letter, "已记住的答案"))

        study = self.lex.study.get(key)
        if study:
            score, option = pick_best(options, study)
            if option is not None and score >= 0.6:
                ranked.append((option.letter, f"学习卡片释义 {score:.2f}"))

        used_word = word
        segments, pos_set = self.lex.entry(key)
        best_score, best_option = pick_best(options, segments, pos_set) if segments else (0, None)
        if best_score < 0.6 and key not in self.lex.vocab:
            for variant in word_variants(word):
                variant_segments, variant_pos = self.lex.entry(variant)
                score, option = pick_best(options, variant_segments, variant_pos)
                if score >= 0.6 and score > best_score + 0.1:
                    best_score, best_option, used_word = score, option, variant
                if best_score >= 0.9:
                    break

        if best_option is not None and best_score > 0:
            note = f"匹配度 {best_score:.2f}"
            if used_word.lower() != word.lower():
                note += f", 纠正为 {used_word}"
            ranked.append((best_option.letter, note))

        # 释义都不匹配时用词性兜底
        if pos_set:
            matched = [opt for opt in options if option_pos(opt.text) in pos_set]
            if len(matched) == 1:
                ranked.append((matched[0].letter, "仅词性匹配"))

        # 其余选项按行序补位, 保证总有可点的
        for option in options:
            ranked.append((option.letter, "保底顺序"))
        unique: list[tuple[str, str]] = []
        seen: set[str] = set()
        for letter, note in ranked:
            if letter not in seen:
                seen.add(letter)
                unique.append((letter, note))
        return unique

    # ---------- 拼写/手写 ----------
    def meaning_plausible(self, word: str, text: str) -> bool:
        """判断记住的释义与词典是否有交集, 防止 OCR 误读污染词库."""
        cn = "".join(CN_RE.findall(text))
        if len(cn) < 1:
            return False
        segments, _pos = self.lex.entry(word)
        if not segments:
            return True
        return any(longest_common_substring(cn, segment) >= 2
                   or cn in segment or segment in cn
                   for segment in segments)

    def spell_candidates(self, prompt: list[str], recent: list[str] = (),
                         limit: int = 4) -> list[str]:
        segments: list[str] = []
        for text in prompt:
            for segment in split_segments(text):
                if segment and segment not in segments:
                    segments.append(segment)
        if not segments:
            return []
        ranked = self.lex.reverse_lookup(segments, recent=recent, limit=limit)
        words = [word for word, _score in ranked if " " not in word]
        if words:
            return words[:limit]
        return self._ecdict_reverse(segments, limit)

    def _ecdict_reverse(self, segments: list[str], limit: int) -> list[str]:
        """词库没有收录时, 用 ECDICT 的 translation 字段做一次反查."""
        path = self.lex.cfg.ecdict_path
        if path is None or not segments:
            return []
        # 取最长的片段, 命中率最高
        query = max(segments, key=len)
        if len(query) < 2:
            return []
        conn = self.lex._conn
        close = False
        if conn is None:
            try:
                conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
                close = True
            except sqlite3.Error:
                return []
        try:
            rows = conn.execute(
                "SELECT word FROM stardict WHERE translation LIKE ? "
                "AND word NOT LIKE '% %' ORDER BY bnc LIMIT 400",
                (f"%{query}%",),
            ).fetchall()
        except sqlite3.Error:
            return []
        finally:
            if close and conn is not None:
                conn.close()
        words = []
        for (word,) in rows:
            word = str(word).strip().lower()
            if word.isalpha() and word not in words:
                words.append(word)
            if len(words) >= limit:
                break
        return words
