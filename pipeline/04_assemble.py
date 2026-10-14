#!/usr/bin/env python3
"""04_assemble.py —— 把译文按原顺序回填成 zh/<doc>.md。

规则:
  * code 段原样搬运（不翻译）
  * prose 段取 translated.jsonl 中的译文；缺失则保留原文并加 <!-- TODO:未译 --> 标记
  * 文档头部写入来源信息与覆盖度，便于溯源
用法:
    python pipeline/04_assemble.py
产出:
    zh/<doc>.md        zh/_覆盖度.md
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEGS = ROOT / "build" / "segments.jsonl"
STATE = ROOT / "state" / "translated.jsonl"
ZH = ROOT / "zh"


def main() -> int:
    segs = [json.loads(l) for l in SEGS.read_text(encoding="utf-8").splitlines() if l.strip()]
    done = {}
    if STATE.exists():
        for line in STATE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["sha1"]] = r

    ZH.mkdir(exist_ok=True)
    docs: dict[str, dict] = {}
    cur = None
    for s in sorted(segs, key=lambda x: (x["doc"], x["ord"])):
        if s["doc"] != cur:
            cur = s["doc"]
            docs[cur] = {"parts": [], "prose": 0, "code": 0, "translated": 0, "missing": 0}
        d = docs[cur]
        if s["type"] == "code":
            d["code"] += 1
            d["parts"].append(s["text"])
        else:
            d["prose"] += 1
            rec = done.get(s["sha1"])
            if rec:
                d["translated"] += 1
                d["parts"].append(rec["zh"])
            else:
                d["missing"] += 1
                d["parts"].append(f"<!-- TODO:未译 -->\n\n{s['text']}")

    cov_lines = ["# 翻译覆盖度报告", "",
                 "| 文档 | 可译段 | 已译 | 未译 | 覆盖率 | 代码段 |",
                 "|---|---|---|---|---|---|"]
    tot_p = tot_t = 0
    for doc, d in sorted(docs.items()):
        rate = d["translated"] / max(1, d["prose"])
        tot_p += d["prose"]; tot_t += d["translated"]
        cov_lines.append(f"| `{doc}` | {d['prose']} | {d['translated']} | {d['missing']} "
                         f"| {rate:.0%} | {d['code']} |")
        head = (f"<!-- 自动生成：pipeline/04_assemble.py -->\n"
                f"<!-- 来源：sources/ ; 覆盖率 {rate:.0%}（{d['translated']}/{d['prose']} 段） -->\n\n")
        (ZH / f"{doc}.md").write_text(head + "\n\n".join(d["parts"]) + "\n", encoding="utf-8")

    overall = tot_t / max(1, tot_p)
    cov_lines += ["", f"**合计：{tot_t}/{tot_p} 段，总体覆盖率 {overall:.1%}**"]
    (ZH / "_覆盖度.md").write_text("\n".join(cov_lines) + "\n", encoding="utf-8")
    print(f"回填完成：{len(docs)} 篇 -> zh/，总体覆盖率 {overall:.1%}（{tot_t}/{tot_p} 段）")
    print("覆盖度报告：zh/_覆盖度.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
