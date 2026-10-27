"""把本地学习记录(study.json / learned.json)中可靠的释义并入 cache/vocab.json.

只接受与词库现有释义有交集的片段, 避免把 OCR 误读(如 agree -> 同思)写进词库.
"""

from __future__ import annotations

import json
import os
import pickle
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fzauto.words import split_segments  # noqa: E402

CACHE = ROOT / "cache"
VOCAB = CACHE / "vocab.json"
STUDY = CACHE / "study.json"
LEARNED = CACHE / "learned.json"
CN_RE = re.compile(r"[\u4e00-\u9fff]")

ECDICT_CANDIDATES = [
    Path(os.environ.get("ECDICT_DB", "")),
    ROOT / "ecdict" / "stardict.db",
    Path(r"D:\22232\Downloads\ecdict-sqlite-28\stardict.db"),
]


def open_ecdict() -> sqlite3.Connection | None:
    for path in ECDICT_CANDIDATES:
        if path and path.exists():
            try:
                return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            except sqlite3.Error:
                continue
    return None


def _contained(candidate: str, item: str) -> bool:
    if candidate == item:
        return True
    if candidate not in item:
        return False
    # “朗的”“部的”这类截断的“X的”碎片不要
    if candidate.endswith("的") and len(candidate) <= 2:
        return False
    return True


def splittable(text: str, known: set[str]) -> bool:
    """判断 text 是否能由两个以上已知义项拼起来 (如 水+给浇水)."""
    parts = {item for item in known if item and item != text}
    if len(text) < 4:
        return False
    reachable = [False] * (len(text) + 1)
    reachable[0] = True
    for start in range(len(text)):
        if not reachable[start]:
            continue
        for end in range(start + 1, len(text) + 1):
            if text[start:end] in parts:
                reachable[end] = True
    return reachable[-1]


def acceptable(segment: str, existing: list[str], ecdict_segments: list[str]) -> bool:
    """只接受与 ECDICT 或现有释义能对上的片段, 过滤 OCR 拼接/误读."""
    if len(segment) < 2:
        # 单字释义噪声太大 (如“的”“在”), 不并入词库
        return False
    if re.fullmatch(r"(.{1,3})\1", segment):
        # “咳嗽咳嗽”这类重复拼接
        return False
    if splittable(segment, set(existing) | set(ecdict_segments)):
        # “水给浇水”“顾客主顾”这类把两个义项粘在一起的结果
        return False
    # 候选必须是某个已有释义的一部分, 不能反过来 (否则“顾客主顾”这类拼接会被接受)
    if any(_contained(segment, item) for item in ecdict_segments):
        return True
    if any(_contained(segment, item) for item in existing):
        return True
    return False


def main() -> None:
    if not VOCAB.exists():
        raise SystemExit("找不到 cache/vocab.json")
    vocab = json.loads(VOCAB.read_text(encoding="utf-8"))

    (CACHE / "vocab.before-merge.json").write_text(
        json.dumps(vocab, ensure_ascii=False, indent=0), encoding="utf-8"
    )
    pkl = VOCAB.with_suffix(".pkl")
    if pkl.exists():
        (CACHE / "vocab.before-merge.pkl").write_bytes(pkl.read_bytes())

    report: list[str] = [f"起始词数: {len(vocab)}"]
    accepted_total = rejected_total = missing_total = 0
    accepted_examples: list[str] = []
    rejected_examples: list[str] = []

    conn = open_ecdict()
    report.append("ECDICT: 已启用" if conn else "ECDICT: 未找到, 只按现有词库校验")
    ecdict_cache: dict[str, list[str]] = {}

    def ecdict_segments(key: str) -> list[str]:
        if key in ecdict_cache:
            return ecdict_cache[key]
        segments: list[str] = []
        if conn is not None:
            try:
                row = conn.execute(
                    "SELECT translation FROM stardict WHERE word = ? LIMIT 1", (key,)
                ).fetchone()
            except sqlite3.Error:
                row = None
            if row and row[0]:
                segments = split_segments(str(row[0]))
        ecdict_cache[key] = segments
        return segments

    sources: list[tuple[str, dict, bool]] = []
    if STUDY.exists():
        sources.append(("study", json.loads(STUDY.read_text(encoding="utf-8")), False))
    if LEARNED.exists():
        sources.append(("learned", json.loads(LEARNED.read_text(encoding="utf-8")), True))

    for name, data, is_text in sources:
        accepted = rejected = missing = 0
        for raw_key, raw_value in data.items():
            key = str(raw_key).strip().lower()
            if key not in vocab:
                missing += 1
                continue
            candidates = split_segments(raw_value) if is_text else [
                str(item).strip() for item in raw_value
            ]
            existing = list(vocab[key][0])
            ecdict_segs = ecdict_segments(key)
            added: list[str] = []
            for segment in candidates:
                if not segment or not CN_RE.search(segment) or len(segment) > 24:
                    continue
                if segment in existing:
                    continue
                if acceptable(segment, existing, ecdict_segs):
                    existing.append(segment)
                    added.append(segment)
                else:
                    rejected += 1
                    if len(rejected_examples) < 15:
                        rejected_examples.append(f"{key}: {segment} (现有: {existing[:4]})")
            if added:
                accepted += 1
                vocab[key][0] = existing[:24]
                detail = vocab[key][2] if len(vocab[key]) > 2 else ""
                vocab[key][2] = (detail + "|应用:" + ",".join(added)).strip("|")
                if len(accepted_examples) < 15:
                    accepted_examples.append(f"{key}: +{added}")
            if not added and candidates:
                # 全部片段都未通过校验
                pass
        accepted_total += accepted
        rejected_total += rejected
        missing_total += missing
        report.append(f"{name}: 合并词条 {accepted}, 拒绝片段 {rejected}, 词库缺失词 {missing}")

    report.append(f"合并后词数: {len(vocab)}")
    report.append(f"接受片段词条: {accepted_total}, 拒绝片段: {rejected_total}, 缺失词: {missing_total}")
    report.append("接受样例:")
    report.extend(f"  {item}" for item in accepted_examples)
    report.append("拒绝样例 (OCR/释义不可靠):")
    report.extend(f"  {item}" for item in rejected_examples)
    if conn is not None:
        conn.close()

    VOCAB.write_text(json.dumps(vocab, ensure_ascii=False, indent=0), encoding="utf-8")
    with pkl.open("wb") as handle:
        pickle.dump(vocab, handle, protocol=pickle.HIGHEST_PROTOCOL)
    reverse = CACHE / "reverse_index.pkl"
    if reverse.exists():
        reverse.unlink()

    text = "\n".join(report)
    print(text)
    out = ROOT / "logs" / "vocab-merge-report.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"\n报告: {out}")


if __name__ == "__main__":
    main()
