#!/usr/bin/env python3
"""01_extract.py —— 把 sources/ 下的 HTML / PDF 转成结构化 Markdown 文本。

用法:
    python pipeline/01_extract.py                 # 默认读 sources/ 写 build/text/
    python pipeline/01_extract.py --force        # 忽略缓存，全部重抽

产出:
    build/text/<slug>.md     带 front-matter 的正文（标题/列表/代码块保留）
    build/manifest.json      抽取清单：来源、URL、字节数、sha256
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "aside", "form", "iframe", "button"}
BLOCK = {"p", "div", "section", "article", "main", "header", "li", "tr", "td", "th", "blockquote", "pre"}


class ToMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self.buf: list[str] = []
        self.cur = "p"
        self.skip = 0
        self.pre = 0

    def _flush(self, kind: str | None = None) -> None:
        text = "".join(self.buf)
        self.buf = []
        if kind == "pre":
            code = text.strip("\n")
            if code.strip():
                self.blocks.append(("pre", code))
            return
        text = re.sub(r"[ \t\u00a0]+", " ", text.replace("\n", " ")).strip()
        if text:
            self.blocks.append((kind or self.cur, text))

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "pre":
            self._flush()
            self.pre += 1
            self.buf = []
            return
        if self.pre:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self.cur = tag
        elif tag == "li":
            self._flush()
            self.cur = "li"
        elif tag == "blockquote":
            self._flush()
            self.cur = "quote"
        elif tag in BLOCK:
            self._flush()
            self.cur = "p"
        elif tag == "br":
            self.buf.append("\n")
        elif tag == "code":
            self.buf.append("`")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.buf.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "pre":
            self.pre = max(0, self.pre - 1)
            if self.pre == 0:
                self._flush("pre")
                self.cur = "p"
            return
        if self.pre:
            return
        if tag in BLOCK or tag in ("ul", "ol") or re.fullmatch(r"h[1-6]", tag):
            self._flush()
            if tag in ("ul", "ol"):
                self.cur = "p"
        elif tag == "code":
            self.buf.append("`")

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)

    def render(self) -> str:
        self._flush()
        lines: list[str] = []
        for kind, text in self.blocks:
            if kind == "pre":
                lines.append("```\n" + text + "\n```")
            elif re.fullmatch(r"h[1-6]", kind):
                lines.append("#" * int(kind[1]) + " " + text)
            elif kind == "li":
                lines.append("- " + text)
            elif kind == "quote":
                lines.append("> " + text)
            else:
                lines.append(text)
        out: list[str] = []
        for ln in lines:
            if out and out[-1] == ln:
                continue
            out.append(ln)
        md = "\n\n".join(out)
        return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


def html_to_md(raw: str) -> str:
    p = ToMarkdown()
    p.feed(raw)
    return p.render()


def pdf_to_md(path: Path) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print(f"  ! 未安装 PyMuPDF，跳过 {path.name}（pip install pymupdf）", file=sys.stderr)
        return ""
    doc = fitz.open(path)
    pages = []
    for i, page in enumerate(doc, 1):
        txt = page.get_text("text").strip()
        if txt:
            pages.append(f"<!-- page {i} -->\n\n{txt}")
    return "\n\n".join(pages) + "\n"


def load_url_map(src: Path) -> dict[str, str]:
    m = src / "CS146S_offline" / "page_map.json"
    if m.exists():
        return {v: k for k, v in json.loads(m.read_text(encoding="utf-8")).items()}
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "sources"))
    ap.add_argument("--out", default=str(ROOT / "build" / "text"))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    url_map = load_url_map(src)
    manifest, skipped = [], 0

    targets = sorted(src.rglob("*.html")) + sorted(src.rglob("*.pdf"))
    for path in targets:
        if "site/" in path.as_posix():          # 站点导航壳，非课程正文
            continue
        rel = path.relative_to(src).as_posix()
        slug = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")
        if path.stem == "Vibe_Coding_Playbook":
            slug = "vibe-coding-playbook"
        dst = out / f"{slug}.md"

        body = html_to_md(path.read_text(encoding="utf-8", errors="ignore")) if path.suffix == ".html" else pdf_to_md(path)
        if not body.strip():
            skipped += 1
            print(f"  - 跳过 {rel}（无正文）")
            continue

        url = url_map.get(path.name, "")
        head = (
            "---\n"
            f"source_file: {rel}\n"
            f"source_url: {url}\n"
            f"source_sha256: {hashlib.sha256(path.read_bytes()).hexdigest()}\n"
            f"extracted_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
            "---\n\n"
        )
        dst.write_text(head + body, encoding="utf-8")
        manifest.append({
            "doc": slug, "source_file": rel, "source_url": url, "kind": path.suffix.lstrip("."),
            "chars": len(body), "words": len(body.split()), "out": dst.relative_to(ROOT).as_posix(),
        })
        print(f"  + {slug:<42} {len(body):>7} 字符  {len(body.split()):>6} 词")

    (ROOT / "build" / "manifest.json").write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "docs": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
    total_chars = sum(d["chars"] for d in manifest)
    print(f"\n抽取完成：{len(manifest)} 篇，{total_chars:,} 字符（约 {total_chars // 5:,} 英文词），跳过 {skipped} 篇")
    print(f"清单：build/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
