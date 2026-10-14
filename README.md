# CS146S 课程中文翻译工程（C1 挑战成果）

把 Stanford CS146S《The Modern Software Developer》的课程正文做成**可读、可核、可复用**的中文版本。

这个仓库交付的不只是一批译文，而是一条**换语料即可重跑的翻译管线**：原文抽取 → 分段 → 术语约束下的翻译 → 幂等回填 → 自动抽检。下一批同学换个 `sources/` 就能直接开跑。

## 为什么需要一条管线，而不是直接丢给 AI

- **载体不统一**：同一门课的资料来自 Ghost 博客、Medium、厂商静态站、PDF、离线缓存站五种形态，正文位置和噪音各不相同，直接整篇投喂会夹带大量导航与页脚。
- **术语必须全文一致**：`Agent / Agentic AI / Context Engineering / SAST` 这类词一旦一篇一个译法，读者就要重新学习概念。
- **体量超出单轮上下文**：96,906 英文词无法一次处理，必须切块，且切块后人工参与的部分要能断点续跑。
- **质量需要可验证**：译文里混着未翻译的英文、长度异常段落、术语偏离，靠肉眼看不过来。

## 目录结构

```
C1-课程翻译/
├── pipeline/            # 管线：5 个脚本 + config.json
│   ├── 01_extract.py    #   源文件 → build/text/ 纯文本
│   ├── 02_segment.py    #   文本 → build/segments.jsonl 可译段
│   ├── 03_translate.py  #   --export / --import / --run / --stats
│   ├── 04_assemble.py   #   回填结果 → zh/<文档>.md + 覆盖度报告
│   └── 05_qa.py         #   抽检 → build/logs/qa-report.md
├── sources/             # 原始资料（离线缓存，37 份：33 HTML + 4 PDF）
├── build/               # 中间产物：manifest.json / segments.jsonl / logs/
├── state/               # 进度与批次：inbox/ outbox/ translated.jsonl / legacy（历史残留存档）
├── zh/                  # 中文成果 + _覆盖度.md
├── docs/                # 交付物：AI日志 / AAR / 拿来说明
├── 术语表.csv           # 73 条中英统一译法
└── 翻译作业手册.md       # 每天固定动作（模式 2）
```

> **发布说明（A 方案）**：本仓库公开的是**管线 + 术语表 + 中文译稿 + 四份交付物**。`sources/`（课程离线缓存，版权归原作者）、`build/`（中间产物）与 `state/`（进度账本）属于本地工作目录，**不随仓库分发**；复现或续译时，请按下文「来源与版权」自行获取原文后放入 `sources/`，管线即可直接重跑。

## 快速开始

```bash
# 首次（或更换语料后）
python3 pipeline/01_extract.py
python3 pipeline/02_segment.py

# 逐批翻译（模式 2：人译 + 管线回填）
python3 pipeline/03_translate.py --export      # 导出下一批 → state/inbox/batch-NNN.md
#   → 把批文件整份交给任意 AI，译文按原标记存回 state/outbox/batch-NNN.md
python3 pipeline/03_translate.py --import      # 回填（按段指纹去重）
python3 pipeline/04_assemble.py                # 重排成 zh/<文档>.md
python3 pipeline/05_qa.py                      # 抽检
python3 pipeline/03_translate.py --stats       # 进度

# 可选：API 全自动（模式 3）
export OPENAI_API_KEY=...        # 或自定义 OPENAI_BASE_URL
python3 pipeline/03_translate.py --run
```

`--docs <篇名>` 只导指定篇目，`--limit <段数>` 小步试跑。

## 三个关键设计决定

1. **段落即进度单位，以内容指纹（sha1）为键。** `state/translated.jsonl` 记录的是「这段文本已译」，不是「第几批已交」。重复提交不会重复计数，漏译的段下次导出自动重现——所以中断、合并、重译都不会把进度写坏。
2. **批文件自带规则与术语。** `state/inbox/batch-NNN.md` 抬头包含翻译规则、本批命中的术语表条目和输出格式要求，人工环节只需整份粘贴，不必每次重写提示词。
3. **抽检自动化。** `05_qa.py` 检查英文残留、长度异常（译文/原文长度比）、术语不一致，输出 `build/logs/qa-report.md`。

## 文件命名契约（不要改）

| 位置 | 规则 |
| --- | --- |
| `state/inbox/batch-NNN.md` | 待译批次 |
| `state/outbox/batch-NNN.md` | 译文，**必须与 inbox 同名**，`<<<SEG …>>>` 标记行不可增删改 |
| `state/translated.jsonl` | 已完成段，**不要手改** |
| `state/legacy/` | 重分段前的历史账本存档（只读）；换源后可据此找回旧译文 |
| `build/segments.jsonl` | 分段结果（重跑 `02_segment.py` 会重置段 ID） |

缺标记的段视为未翻译，下次重新出现在批次里——这是特性，不是 bug。

## 当前进度

| 指标 | 数值 |
| --- | --- |
| 已抽取正文 | 33 篇（源资料 37 份） |
| 语料体量 | 96,906 英文词 |
| 切分结果 | 565 段，其中可译段 513、代码段 52 |
| 已译 | 2 段（0.4%）· 剩余约 95,590 词 |
| 待译批次 | 31 批（每批 ≤20 段 / ≤24KB） |
| 术语表 | 73 条 |

进度请以 `python3 pipeline/03_translate.py --stats` 和 `zh/_覆盖度.md` 为准（本表为 2026-09-30 快照）。

## 已知缺口（如实标注，不硬凑）

| 来源 | 情况 | 处理 |
| --- | --- | --- |
| `pages/lessons-from-ai-code-reviews.html` | 源文件 0 字节，抓取即失败 | 不计入覆盖度分母 |
| `pages/how-warp-uses-warp.html` | 有 HTML（15KB）但提取不出正文（正文由脚本注入） | 保留原文链接，标注待人工补录 |
| `Vibe_Coding_Playbook.pdf` | 7.9MB PDF 抽取为空（扫描/图片型版式） | 需 OCR，本轮未纳入 |
| `good-context-good-code` | 正文需 access code，公开侧只有标题 | 标注为部分获取（1 段） |
| `peeking-under-the-hood-of-claude-code` | Medium 反爬 | 保留原文链接 + 说明（1 段） |
| `prompt-engineering-guide` | 正文 JS 渲染，静态抓取仅得导语 | 标注为部分获取（1 段） |

## 复用指南（给下一批同学）

1. **换语料**：把新资料放进 `sources/`，更新 `pipeline/config.json` 的输入路径，重跑 `01_extract.py` + `02_segment.py`。
2. **换领域**：只改 `术语表.csv`（四列：term / zh / keep_en / notes），管线其余部分不动。
3. **沿用结构**：任何「多轮人工参与的批处理」都可以照搬这套「内容指纹 + 幂等回填 + 自动抽检」的骨架。
4. **先做样板行体检**：抓取新语料后先看长度分布与页脚/导航残留，再开工翻译。

## 运行环境

- Python 3（标准库即可，无第三方依赖；`sources/` 内的 `.venv` 仅为本地环境）
- 编码统一 UTF-8；输出文件均带「自动生成 / 来源 / 覆盖率」抬头注释

## 来源与版权

`sources/` 为个人学习用途的课程离线缓存（原站 the modernsoftware.dev，缓存于 2026-04-02），版权归原作者与 Stanford University 所有。本仓库的译文与管线代码仅用于学习交流，不作商业用途。

- **原始站点**：themodernsoftware.dev（Stanford CS146S《The Modern Software Developer》课程正文）
- **抓取日期**：2026-04-02
- **获取方式**：公开课程文章可直接访问原文获取；需 access code、被反爬、或图片型 PDF 的条目见上文「已知缺口」。因版权原因，本仓库**不随附** `sources/` 目录，复现时请自行获取原文后放入 `sources/`，再重跑 `pipeline/01_extract.py` 与 `02_segment.py`。
