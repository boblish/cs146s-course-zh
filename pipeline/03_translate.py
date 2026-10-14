#!/usr/bin/env python3
"""03_translate.py —— 带术语表约束、断点续跑的翻译驱动。

两种 driver（pipeline/config.json 里切换）:
  batch : 导出成批 prompt 文件 -> 交给任意 AI 工具 -> 回填。无需 API key。默认。
  api   : OpenAI 兼容 /chat/completions 直连（需 OPENAI_API_KEY）。

常用命令:
  python pipeline/03_translate.py --stats                 # 看进度
  python pipeline/03_translate.py --export --limit 40     # 导出前 40 段待译
  python pipeline/03_translate.py --import                # 回填 state/outbox/
  python pipeline/03_translate.py --run                   # api 模式直接跑全部待译
状态: state/translated.jsonl 以段 sha1 为键 —— 已译的段永远跳过，换源可复用。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEGS = ROOT / "build" / "segments.jsonl"
STATE = ROOT / "state" / "translated.jsonl"
INBOX = ROOT / "state" / "inbox"
OUTBOX = ROOT / "state" / "outbox"
MARK = "<<<SEG {sid}>>>"

SYSTEM = (
    "你是资深中英技术翻译，长期翻译 AI 工程与软件工程方向的技术文章。"
    "你的译文准确、通顺、没有翻译腔，并且严格遵守给定的术语表。"
)


def load_cfg() -> dict:
    return json.loads((ROOT / "pipeline" / "config.json").read_text(encoding="utf-8"))


def load_glossary() -> list[dict]:
    with (ROOT / "术语表.csv").open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("term")]


def load_segments() -> list[dict]:
    return [json.loads(l) for l in SEGS.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_state() -> dict[str, dict]:
    if not STATE.exists():
        return {}
    out = {}
    for line in STATE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["sha1"]] = r
    return out


def append_state(rec: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with STATE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def pick_glossary(text: str, glossary: list[dict]) -> list[dict]:
    low = text.lower()
    return [g for g in glossary if g["term"].lower() in low]


def build_user(text: str, glossary_rows: list[dict], cfg: dict) -> str:
    gl = "\n".join(
        f"- {g['term']} => {g['zh']}" + ("（保留英文）" if g.get("keep_en", "").lower() == "yes" else "")
        for g in glossary_rows) or "（本段无强制术语）"
    rules = "\n".join(f"{i}. {s}" for i, s in enumerate(cfg["style"], 1))
    return (
        f"【翻译规则】\n{rules}\n\n"
        f"【术语表（必须遵守）】\n{gl}\n\n"
        f"【原文】\n{text}\n\n"
        "【输出】只输出译文本身，不要任何前言、解释、原文复述或 Markdown 代码围栏包裹。"
    )


def do_stats(cfg: dict) -> int:
    segs = [s for s in load_segments() if s["type"] == "prose"]
    done = load_state()
    hit = [s for s in segs if s["sha1"] in done]
    docs_all = {s["doc"] for s in segs}
    docs_done = {s["doc"] for s in hit}
    print(f"可译段 {len(segs)}，已译 {len(hit)}，覆盖度 {len(hit)/max(1,len(segs)):.1%}")
    print(f"文档 {len(docs_all)} 篇，已开始译 {len(docs_done)} 篇")
    pend_w = sum(s["words"] for s in segs if s["sha1"] not in done)
    print(f"剩余约 {pend_w:,} 词")
    return 0


def do_export(cfg: dict, limit: int, docs: list[str]) -> int:
    segs = [s for s in load_segments() if s["type"] == "prose"]
    done = load_state()
    pend = [s for s in segs if s["sha1"] not in done and (not docs or s["doc"] in docs)]
    if limit:
        pend = pend[:limit]
    if not pend:
        print("没有待译段。")
        return 0
    glossary = load_glossary()
    INBOX.mkdir(parents=True, exist_ok=True)
    # 按「字符预算」装箱：段长差异很大，固定段数会产出 100KB 的巨型批或 9KB 的空批
    max_items = cfg.get("batch_size", 20)
    max_chars = cfg.get("max_batch_chars", 24000)
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    cur_chars = 0
    for s in pend:
        n = len(s["text"])
        if cur and (len(cur) >= max_items or cur_chars + n > max_chars):
            chunks.append(cur)
            cur, cur_chars = [], 0
        cur.append(s)
        cur_chars += n
    if cur:
        chunks.append(cur)
    files = []
    for idx, chunk in enumerate(chunks, 1):
        gl = sorted({g["term"]: g for g in sum((pick_glossary(c["text"], glossary) for c in chunk), [])}.values(),
                    key=lambda g: g["term"])
        gl_lines = "\n".join(f"- {g['term']} => {g['zh']}" + ("（保留英文）" if g.get("keep_en", "").lower() == "yes" else "")
                             for g in gl) or "（无）"
        rules = "\n".join(f"{n}. {s}" for n, s in enumerate(cfg["style"], 1))
        body = [
            "# 翻译任务（请把下面每个 <<<SEG ...>>> 段落译成简体中文）",
            "", "【翻译规则】", rules, "", "【术语表（必须遵守）】", gl_lines, "",
            "【输出格式】严格按原样的 <<<SEG id>>> 标记分段输出，标记行保持英文、不可改动、不可增删；",
            "每个标记后紧跟该段译文；不要输出解释、不要输出原文。", "", "---", "",
        ]
        for c in chunk:
            body.append(MARK.format(sid=c["id"]))
            body.append(c["text"])
            body.append("")
        p = INBOX / f"batch-{idx:03d}.md"
        p.write_text("\n".join(body), encoding="utf-8")
        files.append(p)
    print(f"已导出 {len(files)} 个批次文件（共 {len(pend)} 段）到 state/inbox/")
    for f in files[:5]:
        print(f"  - {f.relative_to(ROOT)}")
    if len(files) > 5:
        print(f"  ... 其余 {len(files)-5} 个")
    print("\n下一步：把 batch-*.md 逐个发给任意 AI（Claude / GPT / 本机模型），"
          "把回复原样存成 state/outbox/同名.md，然后执行 --import")
    return 0


def do_import(cfg: dict) -> int:
    if not OUTBOX.exists():
        print("state/outbox/ 不存在，先导出并回填。")
        return 1
    segs = {s["id"]: s for s in load_segments()}
    done = load_state()
    n_ok = n_skip = 0
    for p in sorted(OUTBOX.glob("*.md")):
        raw = p.read_text(encoding="utf-8")
        parts = re.split(r"<<<SEG\s+([^>]+?)\s*>>>", raw)
        for sid, body in zip(parts[1::2], parts[2::2]):
            sid = sid.strip()
            seg = segs.get(sid)
            if not seg:
                print(f"  ! 未知段号 {sid}（{p.name}）"); continue
            if seg["sha1"] in done:
                n_skip += 1; continue
            zh = body.strip()
            if not zh:
                continue
            rec = {"sha1": seg["sha1"], "id": sid, "doc": seg["doc"], "zh": zh,
                   "model": cfg.get("model") or "batch", "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
            append_state(rec); done[seg["sha1"]] = rec; n_ok += 1
    print(f"回填完成：新增 {n_ok} 段，跳过已存在 {n_skip} 段")
    return do_stats(cfg)


def call_api(cfg: dict, user: str) -> str:
    import urllib.request
    key = os.environ.get(cfg["api_key_env"], "")
    base = cfg.get("base_url") or os.environ.get(cfg.get("base_url_env", ""), "https://api.openai.com/v1")
    if not key or not cfg.get("model"):
        sys.exit(f"api 模式需要 {cfg['api_key_env']} 与 config.json 中的 model")
    payload = {"model": cfg["model"], "temperature": cfg.get("temperature", 0.2),
               "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()


def do_run(cfg: dict, limit: int, docs: list[str]) -> int:
    segs = [s for s in load_segments() if s["type"] == "prose"]
    done = load_state()
    pend = [s for s in segs if s["sha1"] not in done and (not docs or s["doc"] in docs)]
    if limit:
        pend = pend[:limit]
    glossary = load_glossary()
    print(f"api 模式：待译 {len(pend)} 段")
    for n, seg in enumerate(pend, 1):
        user = build_user(seg["text"], pick_glossary(seg["text"], glossary), cfg)
        for attempt in range(1, cfg.get("max_retries", 3) + 1):
            try:
                zh = call_api(cfg, user)
                append_state({"sha1": seg["sha1"], "id": seg["id"], "doc": seg["doc"], "zh": zh,
                              "model": cfg["model"], "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
                print(f"  [{n}/{len(pend)}] {seg['id']} ok")
                break
            except Exception as e:                      # noqa: BLE001
                print(f"  [{n}/{len(pend)}] {seg['id']} 第 {attempt} 次失败：{e}")
                time.sleep(2 * attempt)
    return do_stats(cfg)


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--stats", action="store_true")
    g.add_argument("--export", action="store_true")
    g.add_argument("--import", dest="do_import", action="store_true")
    g.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--docs", default="")
    args = ap.parse_args()
    cfg = load_cfg()
    docs = [d.strip() for d in args.docs.split(",") if d.strip()]
    if args.stats:
        return do_stats(cfg)
    if args.export:
        return do_export(cfg, args.limit, docs)
    if args.do_import:
        return do_import(cfg)
    return do_run(cfg, args.limit, docs)


if __name__ == "__main__":
    raise SystemExit(main())
