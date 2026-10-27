"""把 CET4/CET6/高中 词表(JSONL)和 ECDICT 词条转换成 cache/vocab.json.

每个词条格式: "word": [中文释义片段列表, 词性列表, 详细释义]
详细释义形如 "n:跑,赛跑|v:跑,运行", 保留每个词性下的全部义项(含生僻义).
"""

import argparse
import json
import os
import pickle
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cache" / "vocab.json"
ECDICT_DB = Path(os.environ.get("ECDICT_DB", ROOT / "ecdict" / "stardict.db"))

SOURCES = [
    ROOT / "vocab_tmp" / "cet4" / "CET4_3.json",
    ROOT / "vocab_tmp" / "cet6" / "CET6_3.json",
    ROOT / "vocab_tmp" / "gaozhong" / "GaoZhong_2.json",
]

CN_RE = re.compile(r"[\u4e00-\u9fff]")
POS_RE = re.compile(r"\b(vt|vi|v|n|adj|adv|a|ad|prep|pron|conj|num|art|int|aux|abbr)\.")
MAX_SENSE = 24  # 超过这个长度的句子多半是说明文字, 不是词义


def norm_pos(value) -> str | None:
    if not isinstance(value, str):
        return None
    pos = value.strip().lower().rstrip(".")
    if pos in ("vt", "vi"):
        pos = "v"
    elif pos == "a":
        pos = "adj"
    elif pos == "ad":
        pos = "adv"
    elif pos in ("modal", "auxiliary"):
        pos = "aux"
    return pos or None


def new_entry() -> dict:
    return {"segments": [], "pos": set(), "groups": {}}


def add_groups(data: dict, groups: list[tuple[str | None, list[str]]]) -> None:
    """把 (词性, 义项列表) 合并进词条, 同一词性的义项合并到一起."""
    for pos, meanings in groups:
        kept: list[str] = []
        for meaning in meanings:
            if 1 <= len(meaning) <= MAX_SENSE and meaning not in kept:
                kept.append(meaning)
        if not kept:
            continue
        for meaning in kept:
            if meaning not in data["segments"]:
                data["segments"].append(meaning)
        label = pos or "其他"
        if pos:
            data["pos"].add(pos)
        bucket = data["groups"].setdefault(label, [])
        for meaning in kept:
            if meaning not in bucket:
                bucket.append(meaning)


def split_meanings(text: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"[；;，,、/]", text or ""):
        cn = "".join(CN_RE.findall(part))
        if cn and cn not in out:
            out.append(cn)
    return out


def parse_translation(text: str) -> list[tuple[str | None, list[str]]]:
    """解析 ECDICT 的 translation, 按行拆出 (词性, 义项)."""
    groups: list[tuple[str | None, list[str]]] = []
    for line in re.split(r"[\n\r]+", text or ""):
        line = line.strip()
        if not line:
            continue
        # 去掉 [法]/[计]/（...）这类领域标注
        line = re.sub(r"[\[【（(][^\]】）)]*[\]】）)]", "", line).strip()
        if not line:
            continue
        # 跳过 "run的过去式和过去分词" 这类语法说明行, 它不是词义
        if re.search(r"的(过去式|过去分词|现在分词|第三人称单数|复数|比较级|最高级)", line):
            continue
        match = POS_RE.match(line)
        pos = None
        if match:
            pos = norm_pos(match.group(1))
            line = line[match.end():]
        meanings = split_meanings(line)
        if meanings:
            groups.append((pos, meanings))
    return groups


def parse_exchange(value: str) -> list[str]:
    """从 exchange 字段取变形词(p:过去式/d:过去分词/i:现在分词/3:三单/r:比较级/t:最高级/s:复数)."""
    forms: list[str] = []
    for part in (value or "").split("/"):
        code, _, form = part.partition(":")
        if code in ("p", "d", "i", "3", "r", "t", "s") and form:
            form = form.strip().lower()
            if form:
                forms.append(form)
    return forms


def clone_entry(data: dict) -> dict:
    return {
        "segments": list(data["segments"]),
        "pos": set(data["pos"]),
        "groups": {label: list(items) for label, items in data["groups"].items()},
    }


def parse_pos_column(value: str) -> list[str]:
    """解析 ECDICT 的 pos 列(如 "n:100/v:20"), 返回按权重排序的词性."""
    mapping = {"n": "n", "v": "v", "j": "adj", "r": "adv", "c": "conj", "p": "prep"}
    hits: list[tuple[int, str]] = []
    for part in (value or "").split("/"):
        code, _, weight = part.partition(":")
        mapped = mapping.get(code.strip().lower())
        if not mapped:
            continue
        try:
            score = int(weight)
        except ValueError:
            score = 0
        hits.append((score, mapped))
    hits.sort(reverse=True)
    out: list[str] = []
    for _score, pos in hits:
        if pos not in out:
            out.append(pos)
    return out


def add_ecdict(vocab: dict[str, dict]) -> None:
    """把 ECDICT 里的考试词汇/柯林斯/牛津/词频词条及变形词并入本地词库."""
    if not ECDICT_DB.exists():
        print(f"skip ecdict {ECDICT_DB}")
        return
    conn = sqlite3.connect(f"file:{ECDICT_DB.as_posix()}?mode=ro", uri=True)
    rows = conn.execute(
        "select word, translation, exchange, pos from stardict "
        "where translation is not null and translation <> '' "
        "and ((tag is not null and tag <> '') or collins > 0 or oxford = 1 "
        "or frq > 0 or bnc > 0)"
    )
    count = 0
    pending_forms: list[tuple[str, str]] = []
    for word, translation, exchange, pos_col in rows:
        key = (word or "").strip().lower()
        if not key:
            continue
        data = vocab.setdefault(key, new_entry())
        add_groups(data, parse_translation(translation))
        # 用 ECDICT 的 pos 列补全词性, 并把没有词性的义项归到最可能的词性下
        mapped = parse_pos_column(pos_col)
        for pos in mapped:
            data["pos"].add(pos)
        if "其他" in data["groups"]:
            target = mapped[0] if mapped else (next(iter(data["pos"])) if len(data["pos"]) == 1 else None)
            if target:
                items = data["groups"].pop("其他")
                bucket = data["groups"].setdefault(target, [])
                for meaning in items:
                    if meaning not in bucket:
                        bucket.append(meaning)
        count += 1
        if exchange:
            pending_forms.append((key, exchange))
    conn.close()

    # 第二遍补变形词(复数/过去式/比较级等)
    # 注意: ECDICT 里很多变形词自己也有条目, 但释义只有“build的过去式”这类语法说明,
    # 解析后为空. 这里允许用原形释义补全这些空词条, 否则 built/caught/chosen 会缺失.
    derived = 0
    filled = 0
    for key, exchange in pending_forms:
        data = vocab.get(key)
        if not data or not data["segments"]:
            continue
        for form in parse_exchange(exchange):
            if form == key or not form.isalpha() or not (2 <= len(form) <= 24):
                continue
            existing = vocab.get(form)
            if existing is None:
                vocab[form] = clone_entry(data)
                derived += 1
            elif not existing["segments"]:
                vocab[form] = clone_entry(data)
                filled += 1
    print(f"ecdict: {count} entries, {derived} derived forms, {filled} empty forms filled")


def add_cet_source(vocab: dict[str, dict], path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            word = item.get("headWord")
            content = item.get("content", {}).get("word", {}).get("content", {})
            if not word or not content:
                continue
            data = vocab.setdefault(word.lower(), new_entry())
            groups: list[tuple[str | None, list[str]]] = []
            for trans in content.get("trans", []):
                pos = norm_pos(trans.get("pos"))
                meanings = split_meanings(POS_RE.sub("", trans.get("tranCn") or ""))
                if meanings:
                    groups.append((pos, meanings))
            for syno in content.get("syno", {}).get("synos", []):
                pos = norm_pos(syno.get("pos"))
                meanings = split_meanings(POS_RE.sub("", syno.get("tran") or ""))
                if meanings:
                    groups.append((pos, meanings))
            add_groups(data, groups)
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local vocabulary.")
    parser.add_argument("--out", default=str(OUT), help="output vocab.json path")
    parser.add_argument("--ecdict-only", action="store_true",
                        help="do not read CET4/CET6/high-school sources")
    args = parser.parse_args()

    vocab: dict[str, dict] = {}
    sources = [] if args.ecdict_only else SOURCES
    for path in sources:
        if not path.exists():
            print(f"skip missing {path}")
            continue
        print(f"{path.name}: {add_cet_source(vocab, path)} entries")

    add_ecdict(vocab)

    # 整理输出: [义项列表, 词性列表, 详细释义], 按 A→Z 排序
    out: dict[str, list] = {}
    dropped = 0
    sense_total = 0
    multi_pos = 0
    for key in sorted(vocab):
        data = vocab[key]
        segments = data["segments"]
        if not segments:
            dropped += 1
            continue
        detail = "|".join(
            f"{label}:{','.join(items)}" for label, items in data["groups"].items()
        )
        pos_list = sorted(data["pos"])
        if len(pos_list) > 1:
            multi_pos += 1
        sense_total += len(segments)
        out[key] = [segments, pos_list, detail or "其他:" + ",".join(segments)]

    OUT.parent.mkdir(exist_ok=True)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    # 同时输出 pickle, 脚本启动时优先读取, 加载速度更快
    with out_path.with_suffix(".pkl").open("wb") as handle:
        pickle.dump(out, handle, protocol=pickle.HIGHEST_PROTOCOL)

    print(
        f"total {len(out)} words, {sense_total} senses, "
        f"{multi_pos} multi-pos words, dropped {dropped} empty -> {out_path}"
    )


if __name__ == "__main__":
    main()
