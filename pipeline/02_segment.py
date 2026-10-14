#!/usr/bin/env python3
"""02_segment.py —— 把 build/text/*.md 清洗 + 切成可翻译的段，输出 build/segments.jsonl。

v2 规则（相对 v1 的修正）:
  * 前置清洗：丢掉页脚/导航样板行（© 版权、Product/Follow/Legal 栏目名、链接堆叠），
    丢弃明细记入 build/cleaned-report.md 可审计
  * 标题不再单独成段：标题与其后正文合并为一段，译文自然保留层级结构且带上下文
  * 段长收敛到 [min-words, max-words] 词窗口：碎屑向后归并，超长行按句边界切开
  * 围栏代码块 -> type=code（不翻译，原样搬运），保证「格式保持」
  * 连续重复行去重（同一段被抽两次的情况）

用法:
    python pipeline/02_segment.py [--min-words 60] [--max-words 350]
产出:
    build/segments.jsonl       id / doc / ord / type / text / words / chars / sha1
    build/cleaned-report.md    清洗丢弃明细
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)

# 页脚栏目名：抽出来是孤零零一个标题，正文里没有对应内容
BOILER_HEAD = re.compile(
    r"^#{1,3}\s*(product|follow|company|legal|resources|docs|status|contact|privacy|"
    r"terms|security|about|careers|changelog|community|support|pricing|blog)\s*$",
    re.I,
)
# 版权 / 隐私声明行
BOILER_COPY = re.compile(
    r"©\s*\d{4}|\(c\)\s*\d{4}|all rights reserved|privacy\s*[∙·]\s*terms", re.I
)


def boiler_reason(s: str) -> str | None:
    """返回样板行原因；不是样板行返回 None。"""
    t = s.strip()
    if not t:
        return None
    if BOILER_HEAD.match(t):
        return "页脚栏目名"
    if BOILER_COPY.search(t) and len(t) < 140:
        return "版权/隐私行"
    # 导航链接堆叠：几乎无空格 + 多段大写驼峰（如 DatabaseSyncEnterprisePackage…）
    if (
        len(t) >= 20
        and t.count(" ") <= 1
        and sum(1 for c in t if c.isupper()) >= 4
        and not t.endswith((".", "!", "?", ":", "…"))
    ):
        return "导航链接堆叠"
    return None


def parse_doc(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    if (m := FM.match(raw)):
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        raw = raw[m.end():]
    return meta, raw


def lines_of(md: str) -> list[tuple[str, str]]:
    """-> [(kind, line)]，kind ∈ {code, text}。空行丢弃，代码块整体作为一条 code。"""
    out: list[tuple[str, str]] = []
    in_code = False
    code: list[str] = []
    prev: str | None = None
    for line in md.split("\n"):
        s = line.strip()
        if s.startswith("```"):
            if in_code:
                code.append(line)
                out.append(("code", "\n".join(code)))
                code = []
                in_code = False
            else:
                in_code = True
                code = [line]
            continue
        if in_code:
            code.append(line)
            continue
        if not s or s == prev:
            continue
        prev = s
        out.append(("text", s))
    if in_code:
        out.append(("code", "\n".join(code)))
    return out


def split_long(line: str, max_words: int) -> list[str]:
    """单行超长时按句边界切开，避免出现 8KB 巨段被 AI 截断。"""
    parts = [p for p in re.split(r"(?<=[.!?。！？；;])\s+", line) if p.strip()]
    out: list[str] = []
    buf: list[str] = []
    w = 0
    for p in parts:
        pw = len(p.split())
        if buf and w + pw > max_words:
            out.append(" ".join(buf))
            buf, w = [], 0
        buf.append(p)
        w += pw
    if buf:
        out.append(" ".join(buf))
    return out or [line]


def sha1_of(text: str) -> str:
    return hashlib.sha1(re.sub(r"\s+", " ", text).strip().encode("utf-8")).hexdigest()[:16]


def build_doc(md: str, doc: str, min_words: int, max_words: int,
              dropped: list[tuple[str, str, str]]) -> list[dict]:
    records: list[dict] = []
    buf: list[str] = []
    bufw = 0
    ordn = 0

    def emit(kind: str, text: str) -> None:
        nonlocal ordn
        text = text.strip("\n")
        if not text.strip():
            return
        ordn += 1
        records.append({
            "id": f"{doc}#{ordn:04d}", "doc": doc, "ord": ordn, "type": kind,
            "words": len(text.split()) if kind == "prose" else 0,
            "chars": len(text), "sha1": sha1_of(text), "text": text,
        })

    def flush() -> None:
        nonlocal buf, bufw
        if buf:
            emit("prose", "\n".join(buf))
            buf, bufw = [], 0

    for kind, line in lines_of(md):
        if kind == "code":
            flush()
            emit("code", line)
            continue
        if (reason := boiler_reason(line)):
            dropped.append((doc, reason, line))
            continue
        lw = len(line.split())
        # 标题：前面已攒够一段就断开，让「标题 + 正文」自成一节
        if re.match(r"#{1,6}\s", line) and bufw >= min_words:
            flush()
        if lw > max_words:                      # 超长行单独切开
            flush()
            for piece in split_long(line, max_words):
                emit("prose", piece)
            continue
        if buf and bufw + lw > max_words:       # 顶到上限，先收一段
            flush()
        buf.append(line)
        bufw += lw

    # 尾巴过短 -> 并入上一段，不产生无上下文的碎段
    if buf and bufw < min_words and records and records[-1]["type"] == "prose":
        merged = records[-1]["text"] + "\n" + "\n".join(buf)
        records[-1].update(text=merged, words=len(merged.split()),
                           chars=len(merged), sha1=sha1_of(merged))
    else:
        flush()
    return records


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-dir", default=str(ROOT / "build" / "text"))
    ap.add_argument("--min-words", type=int, default=60)
    ap.add_argument("--max-words", type=int, default=350)
    args = ap.parse_args()

    text_dir = Path(args.text_dir)
    records: list[dict] = []
    dropped: list[tuple[str, str, str]] = []
    stats: list[tuple[str, int, int, int, int]] = []

    for path in sorted(text_dir.glob("*.md")):
        _meta, md = parse_doc(path)
        recs = build_doc(md, path.stem, args.min_words, args.max_words, dropped)
        records.extend(recs)
        prose = [r for r in recs if r["type"] == "prose"]
        code = [r for r in recs if r["type"] == "code"]
        sizes = sorted(len(r["text"]) for r in prose) or [0]
        stats.append((path.stem, len(prose), len(code), sizes[len(sizes) // 2], sizes[-1]))

    out = ROOT / "build" / "segments.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"{'文档':<42}{'可译段':>7}{'代码段':>7}{'中位B':>7}{'最大B':>7}")
    for doc, prose, code, med, mx in stats:
        print(f"{doc:<42}{prose:>7}{code:>7}{med:>7}{mx:>7}")

    n_prose = sum(1 for r in records if r["type"] == "prose")
    total_words = sum(r["words"] for r in records if r["type"] == "prose")
    print(f"\n合计 {len(records)} 段（可译 {n_prose} 段 / {total_words:,} 词） -> build/segments.jsonl")

    rep = ["# 清洗报告（02_segment.py）", "",
           f"- 丢弃样板行：{len(dropped)} 行",
           f"- 段长窗口：{args.min_words}–{args.max_words} 词", ""]
    from collections import Counter
    for reason, n in Counter(r for _, r, _ in dropped).most_common():
        rep.append(f"- {reason}：{n} 行")
    rep += ["", "| 文档 | 原因 | 内容 |", "| --- | --- | --- |"]
    rep += [f"| {d} | {r} | `{t[:90]}` |" for d, r, t in dropped]
    (ROOT / "build" / "cleaned-report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print(f"清洗明细 -> build/cleaned-report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
