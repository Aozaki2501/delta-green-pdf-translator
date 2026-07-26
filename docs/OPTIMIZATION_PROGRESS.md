# 优化进度（依据 docs/PROJECT_REVIEW.md）

更新时间：2026-07-26
测试基线：改动前 **640 passed / 31.85s** → 当前 **760 passed / 32.5s**（新增 120 条测试，无失败）

---

## 一、总体进度

| 分组 | 条目数 | 已完成 | 未完成 | 说明 |
| --- | ---: | ---: | ---: | --- |
| 先处理（P0） | 8 | 8 | 0 | 全部完成 |
| 随后处理（P1） | 9 | 7 | 2 | B7 未做、B8 按约定不做 |
| 性能 | 2 | 2 | 0 | 全部完成 |
| 排版层（T1–T6） | 6 | 2 | 4 | T1 / T2 已完成，T3–T6 未做 |
| 合计 | 25 | 19 | 6 | — |

核心目标已达成：文档提出的"静默正确性问题"（译文截断不报错、术语冲突不报错、进度损坏不报错）全部改为**显式报错 + 补测试**。排版层的 T1 / T2 也已按同一原则修复。


---

## 二、先处理（P0）— 8/8 完成

| # | 事项 | 状态 | 落点 |
| --- | --- | --- | --- |
| 1 | 译文截断检测（`finish_reason == "length"`） | ✅ | `core/translator.py` 新增 `TruncatedResponseError` + `_read_completion()`；截断不入缓存、不重试、计入失败 |
| 2 | 收紧"译文疑似不完整"阈值 | ✅（并修正了文档的错误建议） | `core/utils.py`：`0.15 → 0.25`，TOC/handout 用 0.18 |
| 3 | `deepseek-chat` 默认模型改为 `deepseek-v4-pro` | ✅ | `translate_md.py`、`translate_docx.py`（含 `DEFAULT_MODEL` 常量与 `--model` 默认值、docstring 示例） |
| 4 | 硬编码单价改为可配置 | ✅ | 新增 `core/pricing.py`；`TokenStats.cost_yuan` 可为 `None`；6 处 UI + 报告显示改为 `format_cost_yuan()`；Web UI 高级区新增 3 个单价输入框 |
| 5 | `base_url` 校验（拒绝非 http(s)、远程明文 HTTP） | ✅ | `core/utils.py::validate_base_url()`；接入 PDF/MD/DOCX 入口与 Web UI 启动校验 |
| 6 | 提示词与并发数解耦 | ✅ | `core/dispatcher.py`：滑动窗口改为**开跑前一次性算好的上一组"原文"尾部**，同一文档任意并发数产出一致 |
| 7 | 进度指纹补齐设置项 | ✅ | `core/progress.py` schema → 2，新增 `temperature` / `fuzzy_matching`；MD/DOCX 指纹同步补齐（DOCX 另加 `translate_headers`） |
| 8 | 进度文件按文档命名 + 损坏兜底 | ✅ | MD/DOCX 从共享 `.progress.json` 改为 `<输出名>.progress.json`；损坏文件备份为 `.corrupt.bak` 并提示，不再静默丢弃 |

### 值得单独说明的一条

**文档里的阈值建议是错的，我按实测数据改了。**

文档第 2 条建议把阈值从 0.15 提到"0.45 左右"。我用真实产物核对了同一段代码路径（`uploads/_upload_Delta_Green_Presence_PDF_1_8764dab4.pdf` 的 PDFExtractor 原文 vs `output/Delta_Green_Presence_PDF_1_cn/...progress.json` 里已存的译文）：

- 31 个**健康**页面的比值区间是 **0.383 – 0.542**（最低 p34 = 0.383，最高 p5 = 0.542）
- 若按 0.45，**29/31 个健康页会被判为失败**
- 而 `translate_pdf.py` 对判定失败的页面会**标记 failed 并阻止其进入输出**

所以最终取 **0.25**：比最差健康页留约 1.5 倍余量，同时比原来的 0.15 灵敏约 1.7 倍。代码里写了标定来源注释，测试 `tests/test_incomplete_threshold.py` 用 0.383 做了回归护栏，防止以后有人再往上调。

---

## 三、随后处理（P1）— 7/9

| # | 事项 | 状态 | 落点 |
| --- | --- | --- | --- |
| B1 | 术语大小写敏感 + 冲突报错 | ✅ | `core/glossary.py`：新增 `surface` 字段与 `_resolve_case_preferred_entry()`；AC 与 regex 两条路径结果一致；同一英文词条译名冲突时 `load_glossary` 报错并给出行号 |
| B2 | 规则数值保真检查 | ✅ | `core/rule_symbols.py` 新增 `RULE_VALUE_PATTERNS` + `_missing_rule_values()`：百分比 / 伤害修正 / 护甲 / 致死率 / 射程 / 技能值 |
| B3 | 存储管理入口 | ✅ | 新增 `webui/storage.py`（纯逻辑，可测）+ `webui/storage_ui.py`（Streamlit 视图）；`app.py` 增加"存储清理"折叠区，支持按任务勾选删除与按天数批量清理 |
| B4 | 报告不外泄本机绝对路径 | ✅ | `core/typeset_pipeline.py::_report_file_name()`，`_typeset_report.json` 的 4 个路径字段只保留文件名 |
| B5 | `base_url` 校验接入各入口 | ✅ | 见 P0 第 5 条 |
| B6 | 限制 `layout_hints.json` 读取范围 | ✅ | `core/typeset_pipeline.py::_ensure_path_allowed()`：只允许项目目录或输出目录之内 |
| B7 | CI / 依赖固定 / LICENSE | ⛔ 未做 | 见下节"仍未完成" |
| B8 | `app.py` / `theme.py` 拆分 | ⛔ 按约定跳过 | 你在开始时明确排除了前端重构，这条**有意不做** |
| B9 | 清理 `scratch/integrate-dg-trans/` 与根目录残留脚本 | ⛔ 未做 | 见下节 |

---

## 四、性能 — 2/2 完成

| # | 事项 | 状态 | 落点 |
| --- | --- | --- | --- |
| C1 | 进度文件每次全量重写（O(n²) 磁盘写入） | ✅ | `core/progress.py` 新增 `mark_completed_many()`（一组块一次写盘）与 `flush()`；`mark_cached_prompt_translation` 改为延迟落盘；`core/dispatcher.py` 由"每块一次 save"改为"每组一次 save"，`dispatch_all` 结束前 `flush()` |
| C2 | 上传去重不再全量重算哈希 | ✅ | `webui/runtime.py::cached_file_digest()`：优先从 `_upload_{stem}_{sha256}{suffix}` 文件名直接取摘要，无摘要的文件按 `(路径, 大小, mtime)` 缓存 |

---

## 五、仍未完成 / 仍存在的风险

### 1. B7：CI 与依赖固定（未做）
- 没有 `.github/workflows/ci.yml`，742 条测试目前只能靠本地手跑
- `requirements.txt` 的固定策略未统一，也没有 lock 文件
- `google-genai` 仍是硬依赖，未改为可选
- **LICENSE 有意留空**：选哪个许可证是你的决定，我不代选

### 2. B9：仓库残留未清理（未做）
- `scratch/integrate-dg-trans/`（102 个 py 文件，其中 5 个与主干有差异：`core/translation_validation.py`、`core/typeset_models.py`、`core/typeset_pipeline.py`、`exporters/__init__.py`、`exporters/typeset_html.py`）
- 根目录 5 个散落脚本：`diag_38_51.py`、`diag_cards.py`、`test_card_38_51.py`、`test_card_68_98.py`、`test_card_detect.py`
- 风险：`test_card_*.py` 的命名会被 pytest 收集规则误认，删除前需要逐个 diff 确认没有主干缺失的逻辑

### 3. B8：前端体积（按约定跳过）
`app.py` 2298 行、`webui/theme.py` 2718 行仍未拆分。这是你明确排除的范围，但风险仍在：单文件过大，改动容易互相牵连。

### 4. `glossary.tsv` 的冲突取舍（已确认，记录备查）
冲突报错上线后，`glossary.tsv` 里有一组真实冲突挡住了加载：`Owlshead Mountain` 同时映射到"奥尔斯海德山"（第 513 行）和"枭首山"（第 956 行）。

**删掉第 513 行的音译，保留"枭首山"**——第 956 行位于战役标题块，战役本身以这座山命名，用同一个中文形式更一致。术语表现在加载 977 条。此取舍已由你确认。

### 5. 提示缓存写入改为延迟落盘
`mark_cached_prompt_translation` 现在不再每次强制写盘（`save(force=False)`），改为攒到下一次强制保存或 `flush()`。原因：`translate_block` 每个块都会调它一次，不延迟的话 `mark_completed_many` 的批量优化在 3000 块的文档上等于没有。

`mark_completed` / `mark_failed` / `clear_*` 仍然强制写盘，且每个真实调用点后面紧跟一次强制保存，`dispatch_all` 结束前也会 `flush()`。**残余风险**：如果进程在"只写了提示缓存、还没走到任何强制保存"的极窄窗口里被硬杀，会丢掉那一条缓存记录（下次重译该块，不会产生错误译文）。

### 6. 排版层的同类静默问题（T1 / T2 已修，T3–T6 仍在）
本轮清理的是**翻译层**的静默失败。复查排版产物后发现**排版层还有一批性质相同的问题**——报告显示 `failed_regions: 0`，但译文里存在被切碎的句子和 `[...]` 占位符，现有检查一条都发现不了。
其中 **T1（整页逐行退化）与 T2（跨栏段落切开 + `[...]`）已于 2026-07-26 修复**，
**T3–T6 仍未处理**。详见第六节。

---

## 六、排版产物复查发现的问题（T1 / T2 已修，T3–T6 待修）

审查对象：`output/Delta_Green_The_New_Age_2026_FIXED_cn/..._typeset.html`
（15 页 / 114 KB / 209 个翻译区域，`_typeset_report.json` 报 `failed_regions: 0`）

**关键背景：报告说 0 失败，但下面 P0/P1 的问题现有检查一条都发现不了。**
这批问题的性质和本轮修的一样——都是静默的正确性问题，只是发生在排版层而不是翻译层。

> 注：该 HTML 是 07-18 生成的旧产物。T1 / T2 的修复已进代码，
> 但要在产物上看到效果需要重跑排版任务（进度缓存已失效，会重新调 API）。

### T1（P0）整页退化成"逐行翻译" —— ✅ 已修复（2026-07-26）

**现象.** 各页区域数：`p1:2 p2:8 p3:11 **p4:40** p5:4 p6:10 … p15:7`。
第 4 页 40 个区域，其余页 2–13 个。该页每个 `typeset-positioned-block` 都是原 PDF 的**一行**，
`top` 以 20px 等差递增，每行一个独立 `data-region-id`——即**每行单独调了一次 API**。

**后果.** 句子被按行切开，模型只能逐行硬译：

| HTML 行 | 译文 | 问题 |
| --- | --- | --- |
| 552→553 | 「…它是一颗"复仇之星"，一颗行星」→「一个由气体、灰烬与熔铁构成的、行星大小的实体。」 | "a planet-sized entity" 拦腰截断，「一颗行星」成悬空碎片 |
| 557 | 「火山爆发，大气层剥离…降临。」 | 「降临。」是下一句开头，被留在上一行末 |
| 567 | 「已再生。」 | 整行只剩一个残句 |
| 568→569 | 「当通过……传播时」→「氛围。」 | 原文应为 "transmitted through the … atmosphere"，切开后完全不成句 |

> ⚠️ **本节原先写的根因是错的，2026-07-26 已订正。**
> 原文写的是「区域分割（`core/semantic_analyzer.py::_segment_region`）按左边缘一致性聚合，
> 三档缩进让它判定每行自成一段」。核对真实产物后确认：
> **第 4 页 40 个区域里有 39 个在 Phase A 就已经是「一行一个区域」**
> （`page_structure.json` 里 `p0004_r0004` … `p0004_r0040` 每个只有 1 条 line）。
> `_segment_region` 只在**单个区域内部**切分，跨区域它根本不参与，
> 它拿到的输入已经是碎的。照原描述去改会改错地方。

**真正的根因（两层，缺一不可）.**

1. **Phase A** —— `core/page_structure.py::extract_text_regions` 原样采纳 PyMuPDF 的
   text block 划分。悬挂缩进的怪物数据块让 PyMuPDF 把每一行拆成独立 block。
2. **Phase B** —— 即使把行合回一个区域，`_starts_new_segment`
   （`core/semantic_analyzer.py`）用「x0 比基线深 ≥ 0.8×字号 → 新段」判断。
   悬挂缩进段落里**多数行都比首行更深**，规则正好判反，于是仍会每行一段。

**修复.**

1. `core/page_structure.py` 新增 `_merge_flowing_text_regions()`：合并相邻区域，
   条件为「垂直间隙 ≤ 0.6×行距 + 水平投影有重叠 + 字号差 ≤ 12%」。
   **保持 PyMuPDF 原始顺序**，不按 y 重排——重排会打乱分栏页的阅读顺序。
   另有一条保护：起点比前一区域更靠左的区域视为新的缩进层级（项目符号列表接正文），不合并。
2. `core/semantic_analyzer.py` 新增 `_hanging_indent_baseline()`：先求区域内 x0 的主导聚类作为基线，
   判定是否悬挂缩进；是则**浅于基线**的行才是新段起点。
   判定要求「浅于基线的行后面跟着更深的续行」，否则普通首行缩进段落和末尾短行会被误判。

**实测效果（两份真实产物 + 原 PDF 端到端）.**

| 文档 | 区域数 | 翻译块数 |
| --- | --- | --- |
| New Age（66 页） | 511 → 381 | 1043 → 952 |
| Presence（34 页） | 237 → 177 | 506 → 506 |
| 第 4 页单页 | 40 → 8 | 41 → 16 |

第 4 页现在切成 6 个语义段，正好对应
`Nemesis…` / `ETERNAL:` / `CELESTIAL PIPING:` / `GRAVITATIONAL FIELD:` / `PERCEIVING:` / `SAN LOSS:`，与原文结构一致。

**测试.** `tests/test_region_merge.py`（6 条，含分栏不误合、标题不被吸收、项目符号列表不误合）；
`tests/test_semantic_segments.py` 新增悬挂缩进用例。

### T2（P0）跨栏 / 跨区域段落被切开单独翻译 —— ✅ 已修复（2026-07-26）

**现象.** 第 3 页 HTML 第 532 行，译文里**真的印着 `[...]` 占位符**：

> 「《新时代》的触发事件是**[...]**之间的信任丧失，」

下一区域（533 行）才接上「庄严会与灰人，…」。同页另有两处：
534→535（「甚至让彗星都」→「苏梅克-列维9号彗星…」）、
535→536（「…联系了」→「庄严会，并向人类保证…」）。

**根因.** 英文一句话从左栏底流到右栏顶，两个区域各自独立翻译。
英中语序不同，切点在中文里必然错位，模型猜不出来就吐 `[...]`。

**修复.**

1. **T1 的区域合并顺带解决了本条**。第 3 页 `r0004+r0005`、`r0006+r0007` 各自合并后，
   被切断的那句 "trigger event for 'The New Age' is the loss of faith between…"
   落进同一个翻译块，`[...]` 的成因直接消失（区域 7 → 5，翻译块 12 → 10）。
2. `core/translation_validation.py` 新增 `contains_elision_placeholder()` /
   `ensure_no_elision_placeholder()`，把 `[...]`、`（……）`、`【…】`、`[省略…]`
   判为**硬失败**，与 prompt 泄漏同级。接进 `core/typeset_translation.py` 的
   `_parse_marked_translations()` 逐块校验、`mark_completed()` 与缓存写入。
   读取侧（`is_completed` / `get_translation` / `get_cached_prompt_translation`）
   同样过滤，让旧进度里已存的占位符译文重译，而不是直接让整次运行报错。

**误伤核对.** `[...]` 在两份真实产物的**原文里出现 0 次**，译文里 1 次。
测试覆盖了合法的方括号与省略号：`1D6[穿甲]`、`[BLOCK …]` 标记、
中文行文里的 `沉默了很久……` 均不误判。

**测试.** `tests/test_translation_validation.py` 新增 11 条；
`tests/test_typeset_translation.py` 新增解析边界用例。

**未做的部分.** 原建议第 2 条「把相邻区域作为只读上下文塞进 prompt
（`translate_chunk` 已有 `prev_context` / `next_context`，图文管线没用上）」本轮**未做**。
区域合并已消除本文档观察到的全部 `[...]`，先不叠加改动；
若后续仍有跨栏切断，再考虑接上下文。

### T3（P1）`overflow:hidden` 会静默吞掉正文

```css
.typeset-reflow-area   { overflow: hidden; }   /* HTML 第 152 行 */
.typeset-reflow-column { overflow: hidden; }   /* 第 164 行 */
.typeset-region-flow   { overflow: hidden; }   /* 第 259 行 */
```

中文通常比英文短，所以多数情况不出事。**但一旦超框，超出的正文直接消失——不报错、不留痕。**
这正是本轮刚清理掉的那类静默失败，只是换了个地方。

**建议.** 导出后用 Playwright（已在依赖内）量一次 `scrollHeight > clientHeight`，
超框就写进 `_typeset_report.json` 的 `errors`，并在质量报告里列出页码。

同理 `.typeset-heading` 的 `white-space:nowrap` + `overflow:visible`（第 147 / 133 行）：
标题超宽不换行，会**压到旁边正文上**。

### T4（P1）CJK 行高偏紧

```css
.typeset-positioned-block .typeset-body-text { line-height: 1.15; }   /* 第 137 行 */
```

body 是 1.56，定位块却覆盖为 1.15。中文没有 ascender/descender 的呼吸空间，1.15 明显发挤；
第 4 页那 30 多行正文全走这条规则。**建议定位块正文至少 1.4。**

### T5（P2）一致性问题

- **`ETERNAL:` 未翻译**（第 563 行）。同一数据块的兄弟标签「天体笛音」「引力场」「感知」「SAN损失」都翻了，只有它留着英文。
- **同一个「格赫罗斯」标题两种字体**：第 547 行 `source-font-geometric`，第 561 行 `source-font-literary`。同语义角色应同字体。
- **续段缩进错位**：第 533 行是被切断句子的**后半截**，却给了 `text-indent:0`（新段落样式），而 534 行反给 `2em`。视觉上把半句话渲染成了新段落。

### T6（P2）产物卫生

- **`_typeset_fixed.html` 与 `_typeset.html` 逐字节相同**（`cmp` 已验证）。白存两份 114 KB，且无法判断哪个是"正本"。
- **`<title>` 是 64 位哈希文件名**：`_upload_..._481550fbf9…bddf.pdf typeset`。浏览器标签页与打印 PDF 的元数据全是这串，应改用文档标题。
- **浮点精度过剩**：`line-height:1.5596330275229358`、`width:522.493px`。保留 3 位小数即可，能明显缩小文件并让 diff 可读。
- ~~报告内含绝对路径 `E:\DGtranslate\...`~~ —— **本轮已修**（B4）。这份产物是 07-18 生成的旧文件，新任务不会再有。

### 处理顺序与现状

1. ~~**T1**（逐行退化）~~ —— ✅ 已完成（2026-07-26）
2. ~~**T2**（跨区域段落合并 + `[...]` 硬失败）~~ —— ✅ 已完成（2026-07-26）
3. **T3**（溢出检测）—— 未做，让静默裁切变成报告里的一行字
4. **T4 / T5 / T6** —— 未做，可合并为一次小改动

> **T1 / T2 的实际影响面**：改动落在 `core/page_structure.py`（Phase A 区域合并）
> 与 `core/semantic_analyzer.py`（悬挂缩进切分），确实改变了所有文档的区域划分。
> 已有两份产物的 `*_typeset.progress.json` 按 block_id 存，因此大面积失效，
> 重跑会重新调 API。**已确认接受，不做缓存迁移**——合并后源文本本身也变了，
> 按源文本哈希基本迁不上。已有 HTML 产物保留不动。
> 回归对比用两份现有 `page_structure.json` 与两份原 PDF 端到端跑过，见 T1 小节的表格。

---

## 七、改动文件清单

### 新增（13）
```
core/pricing.py
webui/storage.py
webui/storage_ui.py
tests/test_truncation_detection.py        (8)
tests/test_pricing.py                     (14)
tests/test_glossary_case_and_conflicts.py (9)
tests/test_base_url_validation.py         (10)
tests/test_incomplete_threshold.py        (12)
tests/test_progress_corruption.py         (10)
tests/test_storage_cleanup.py             (13)
tests/test_rule_value_checks.py           (13)
tests/test_upload_digest_cache.py         (10)
tests/test_region_merge.py                (6)    ← T1
```

### 修改（20）
```
app.py                    费用显示、单价输入、base_url 校验、进度损坏提示、存储清理入口
core/constants.py         TRANSLATION_TEMPERATURE
core/dispatcher.py        组上下文改为原文尾部、批量落盘、flush
core/glossary.py          大小写敏感解析、冲突报错
core/page_structure.py    T1：相邻文本区域合并（Phase A）
core/progress.py          schema 2、损坏备份、mark_completed_many、flush
core/rule_symbols.py      规则数值保真检查
core/run_report.py        费用可为 None
core/semantic_analyzer.py T1：悬挂缩进感知的段落切分
core/translation_validation.py  T2：[...] 省略占位符判为硬失败
core/translator.py        截断检测、可配置单价、base_url 校验
core/typeset_models.py    cost_yuan: float | None
core/typeset_pipeline.py  报告去绝对路径、layout_hints 路径限制、费用
core/typeset_translation.py     T2：接入占位符校验（写入 + 读取两侧）
core/utils.py             validate_base_url、阈值标定
glossary.tsv              删除 Owlshead Mountain 冲突项（已确认）
translate_docx.py         默认模型、指纹、进度文件名、单价、base_url
translate_md.py           同上
translate_pdf.py          单价、指纹、串行路径上下文与并发对齐、flush
webui/runtime.py          上传摘要缓存
tests/test_dispatcher.py  MockTracker 补齐新接口、上下文测试改写
tests/test_progress.py    延迟落盘契约 + flush 持久化测试
tests/test_semantic_segments.py   T1：悬挂缩进段落切分用例
tests/test_translation_validation.py  T2：占位符检测 + 合法方括号不误伤
tests/test_typeset_translation.py     T2：解析阶段拒绝占位符
```

---

## 八、建议的下一步

按优先级：

1. **T3** 溢出检测 —— 成本低，收益是"再也不会静默丢正文"。
   导出后用 Playwright（已在依赖内）量一次 `scrollHeight > clientHeight`，超框写进报告 `errors`。
2. **B7** 补 CI，让 760 条测试自动跑起来；LICENSE 等你定。
3. **T4 / T5 / T6** 合并成一次排版小修。
4. **B9** 清残留（需逐个 diff，建议单独一次改动）。
5. **B8** 前端拆分若要做，独立分支，不与逻辑改动混在一起。

已无需你决策的事项：`glossary.tsv` 的取舍你已确认；T1 的进度缓存失效不做迁移你已确认。

### 重跑建议

T1 改变了区域划分，两份现有产物的翻译进度缓存已失效。若要看到修复后的 HTML，
需要重跑排版任务（会重新调 API 翻译）。已有 HTML 产物未被改动，可继续对照。
