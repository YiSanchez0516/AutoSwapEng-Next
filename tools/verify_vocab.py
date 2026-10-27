"""校验本地词库结构、已知单词和 ECDICT 一致性.

用法:
    python tools/verify_vocab.py --vocab cache/vocab.json
    python tools/verify_vocab.py --vocab data/vocab.json --ecdict D:/dict/stardict.db
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CN_RE = re.compile(r"[\u4e00-\u9fff]")
KEY_RE = re.compile(r"^[a-z][a-z'\- ./]{0,40}$")
SUSPICIOUS_RE = re.compile(r"[A-Za-z0-9\s]")

EXPECTED = {
    "bridge": ("桥",),
    "intense": ("强烈", "紧张"),
    "shape": ("形状", "身材", "体形"),
    "register": ("注册", "登记"),
    "built": ("建造", "建立", "建设"),
    "caught": ("抓住", "捕捉", "接住"),
    "chosen": ("选择",),
    "men": ("男人", "人"),
    "summer": ("夏",),
    "able": ("能够", "能力"),
}


def load_vocab(path: Path) -> dict[str, list]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("词库格式错误")
    return data


def verify_structure(vocab: dict[str, list], report: list[str]) -> bool:
    report.append(f"总词数: {len(vocab)}")
    bad_keys = [key for key in vocab if not KEY_RE.match(key)]
    report.append(f"异常键名: {len(bad_keys)} {bad_keys[:10]}")
    empty, bad_segments, duplicate = 0, 0, 0
    sense_total = 0
    for key, value in vocab.items():
        if not isinstance(value, list) or len(value) < 2 or not value[0]:
            empty += 1
            continue
        segments = value[0]
        sense_total += len(segments)
        if len(set(segments)) != len(segments):
            duplicate += 1
        for segment in segments:
            if (not isinstance(segment, str) or not CN_RE.search(segment)
                    or len(segment) > 24 or SUSPICIOUS_RE.search(segment)):
                bad_segments += 1
                if bad_segments <= 10:
                    report.append(f"  可疑义项: {key} -> {segment!r}")
    report.append(f"总义项: {sense_total}")
    report.append(f"空词条: {empty}")
    report.append(f"重复义项词条: {duplicate}")
    report.append(f"可疑义项数: {bad_segments}")
    return empty == 0 and bad_segments == 0 and not bad_keys


def verify_known(vocab: dict[str, list], report: list[str]) -> bool:
    ok = True
    report.append("已知单词检查:")
    for word, expects in EXPECTED.items():
        entry = vocab.get(word)
        if not entry:
            report.append(f"  [NG] {word}: 缺失")
            ok = False
            continue
        segments = entry[0] if isinstance(entry, list) else []
        hit = next((exp for exp in expects if any(exp in seg for seg in segments)), None)
        mark = "OK" if hit else "NG"
        if not hit:
            ok = False
        report.append(f"  [{mark}] {word}: {segments[:4]}")
    return ok


def verify_ecdict(vocab: dict[str, list], ecdict: Path, report: list[str],
                  samples: int = 200) -> bool:
    if not ecdict.exists():
        report.append(f"跳过 ECDICT 对比: 未找到 {ecdict}")
        return True
    conn = sqlite3.connect(f"file:{ecdict.as_posix()}?mode=ro", uri=True)
    keys = list(vocab)
    random.seed(20261027)
    random.shuffle(keys)
    checked = passed = 0
    failures: list[str] = []
    for key in keys:
        if checked >= samples:
            break
        row = conn.execute("SELECT translation FROM stardict WHERE word = ? LIMIT 1",
                           (key,)).fetchone()
        if not row or not row[0]:
            continue
        checked += 1
        ecdict_cn = "".join(CN_RE.findall(str(row[0])))
        vocab_cn = "".join(CN_RE.findall("".join(vocab[key][0])))
        if len(vocab_cn) < 2:
            hit = bool(vocab_cn) and vocab_cn in ecdict_cn
        else:
            # 有一个两字以上公共片段即认为释义有交集
            hit = any(vocab_cn[i:i + 2] in ecdict_cn
                      for i in range(max(0, len(vocab_cn) - 1)))
        if hit:
            passed += 1
        elif len(failures) < 10:
            failures.append(f"{key}: {vocab[key][0][:3]} vs {str(row[0])[:60]}")
    conn.close()
    ratio = passed / checked if checked else 0
    report.append(f"ECDICT 抽样对比: {passed}/{checked} 有释义交集 ({ratio:.1%})")
    if failures:
        report.append("  差异样例 (多为变形词/生僻词, 需人工复核):")
        for item in failures:
            report.append(f"    {item}")
    # 变形词在 ECDICT 里常只有“xx的过去式”这类说明, 与词库用原形释义不同,
    # 因此这里允许 10% 的差异, 结构检查和已知单词检查才是硬性标准.
    return checked > 0 and ratio >= 0.90


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vocab", default=str(ROOT / "cache" / "vocab.json"))
    parser.add_argument("--ecdict",
                        default=os.environ.get("ECDICT_DB",
                                               str(ROOT / "ecdict" / "stardict.db")))
    parser.add_argument("--report", default=str(ROOT / "logs" / "vocab-report.txt"))
    args = parser.parse_args()

    path = Path(args.vocab)
    if not path.exists():
        raise SystemExit(f"找不到词库: {path}")
    vocab = load_vocab(path)
    report: list[str] = [f"词库: {path}", f"大小: {path.stat().st_size / 1024 / 1024:.2f} MB"]
    ok_structure = verify_structure(vocab, report)
    ok_known = verify_known(vocab, report)
    ok_ecdict = verify_ecdict(vocab, Path(args.ecdict), report)
    report.append("")
    report.append("结果: " + ("通过" if ok_structure and ok_known and ok_ecdict else "存在问题"))
    text = "\n".join(report)
    print(text)
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"\n报告: {out}")
    raise SystemExit(0 if ok_structure and ok_known and ok_ecdict else 1)


if __name__ == "__main__":
    main()
