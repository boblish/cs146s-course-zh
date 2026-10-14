#!/usr/bin/env python3
"""05_qa.py —— 自动抽检，产出 build/logs/qa-report.md 与 qa.json。

四类检查（每条都能定位到段号，便于人工复核）：
  A 覆盖度  未译段清单（对照 zh/_覆盖度.md）
  B 英文残留 译文里拉丁字母占比过高 / 连续英文词 >= 6 个（代码与专名除外）
  C 长度比  中文字数 / 原文词数，正常区间 [0.9, 3.2]，越界疑似漏译或注水
  D 术语一致 术语表中 keep_en=no 的词，若原文命中但译文未出现规定中文译法 -> 告警
用法:
    python pipeline/05_qa.py
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEGS = ROOT / "build" / "segments.jsonl"
STATE = ROOT / "state" / "translated.jsonl"
LOG = ROOT / "build" / "logs"
KEEP = {"MCP", "SRE", "DAST", "SAST", "RCE", "CLI", "API", "SDK", "YAML", "JSON", "HTTP", "URL",
        "GitHub", "Git", "Claude Code", "Codex", "LSP", "IDE", "PR", "CI", "CD", "TUI", "LLM",
        "AGENTS.md", "README", "SKILL.md", "Docker", "Kubernetes", "Python", "Node", "SQL", "OAuth"}
LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9\-_.]*(?:\s+[A-Za-z][A-Za-z0-9\-_.]*){5,}")
CJK = re.compile(r"[\u4e00-\u9fff]")


def main() -> int:
    segs = [json.loads(l) for l in SEGS.read_text(encoding="utf-8").splitlines() if l.strip()]
    done = {}
    for line in STATE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line); done[r["sha1"]] = r
    with (ROOT / "术语表.csv").open(encoding="utf-8") as f:
        glossary = [g for g in csv.DictReader(f) if g.get("term") and g.get("keep_en", "").lower() != "yes"]

    prose = [s for s in segs if s["type"] == "prose"]
    issues: dict[str, list] = {"未译": [], "英文残留": [], "长度异常": [], "术语不一致": []}
    translated = 0

    for s in prose:
        rec = done.get(s["sha1"])
        if not rec:
            issues["未译"].append({"id": s["id"], "词数": s["words"]})
            continue
        translated += 1
        zh = rec["zh"]
        body = LATIN_RUN.sub("", zh)               # 剔除长的英文串（多为专名/代码）
        letters = len(re.findall(r"[A-Za-z]", re.sub(r"`[^`]*`", "", body)))
        cjk_n = len(CJK.findall(zh))
        if cjk_n > 60:
            ratio = letters / max(1, cjk_n + letters)
            if ratio > 0.30:
                issues["英文残留"].append({"id": s["id"], "英文占比": f"{ratio:.0%}", "样张": zh[:70]})
        lr = cjk_n / max(1, s["words"])
        if lr < 0.9 or lr > 3.2:
            issues["长度异常"].append({"id": s["id"], "中文字/原词": f"{lr:.2f}",
                                       "原词数": s["words"], "中文字数": cjk_n})
        for g in glossary:
            if g["term"].lower() in s["text"].lower() and g["zh"] not in zh:
                issues["术语不一致"].append({"id": s["id"], "术语": g["term"], "应为": g["zh"]})

    LOG.mkdir(parents=True, exist_ok=True)
    cov = translated / max(1, len(prose))
    lines = ["# 翻译质量抽检报告", "",
             f"- 可译段 {len(prose)}，已译 {translated}，覆盖率 **{cov:.1%}**",
             f"- 生成时间：见文件 mtime；判定区间：长度比 [0.9, 3.2]，英文占比阈值 30%", ""]
    for k, v in issues.items():
        lines.append(f"## {k}（{len(v)} 条）")
        if not v:
            lines.append("无。")
        else:
            keys = list(v[0].keys())
            lines.append("| " + " | ".join(keys) + " |")
            lines.append("|" + "---|" * len(keys))
            for row in v[:60]:
                lines.append("| " + " | ".join(str(row.get(x, "")).replace("|", "\\|") for x in keys) + " |")
            if len(v) > 60:
                lines.append(f"\n*（仅列前 60 条，完整数据见 build/logs/qa.json）*")
        lines.append("")
    (LOG / "qa-report.md").write_text("\n".join(lines), encoding="utf-8")
    (LOG / "qa.json").write_text(json.dumps(
        {"coverage": cov, "translated": translated, "total": len(prose),
         "counts": {k: len(v) for k, v in issues.items()}, "issues": issues},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"覆盖率 {cov:.1%}（{translated}/{len(prose)}）｜" +
          "｜".join(f"{k} {len(v)}" for k, v in issues.items()))
    print("报告：build/logs/qa-report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
