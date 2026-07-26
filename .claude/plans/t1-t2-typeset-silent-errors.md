# T1 + T2：修排版层的静默正确性问题

## 背景与关键发现

`docs/OPTIMIZATION_PROGRESS.md` 第八节把 T1 + T2 列为下一步。我用两份真实产物
（`output/Delta_Green_The_New_Age_2026_FIXED_cn/`、`output/Delta_Green_Presence_PDF_1_cn/`）
核对后，**发现文档对 T1 根因的判断是错的**：

- 文档说根因在 `core/semantic_analyzer.py::_segment_region`（按左边缘精确相等聚合）。
- 实测：第 4 页 40 个区域里 **39 个在 Phase A 就已经是「一行一个区域」**
  （`page_structure.json` 里 `p0004_r0004` … `p0004_r0040` 每个只有 1 条 line）。
  `_segment_region` 拿到的输入已经是碎的，它本身没有机会合并——跨区域它根本不参与。

真正的成因分两层：

1. **Phase A**：`core/page_structure.py::extract_text_regions` 原样采纳 PyMuPDF 的
   text block 划分。悬挂缩进的怪物数据块让 PyMuPDF 把每一行拆成独立 block。
2. **Phase B**：即使把行合回一个区域，`_segment_region` 的
   `_starts_new_segment`（`core/semantic_analyzer.py:758`）用
   「x0 比 body_x0 深 ≥ 0.8×字号 → 新段」判断。悬挂缩进段落里**多数行都比首行更深**，
   于是仍会每行一段。

两层都要修，缺一不可。

## 实测验证（已在计划阶段跑过）

合并规则（相邻区域：垂直间隙 ≤ 0.6×行距、水平有重叠、字号差 ≤ 12%）：

| 页 | 区域数 改前→改后 |
| --- | --- |
| 第 4 页 | 40 → 8 |
| 第 14 页 | 26 → 15 |
| 第 3 页 | 7 → 5 |
| 全文合计 | 141 → 93 |

接着走真实 `SemanticAnalyzer.analyze_page`：

- 第 4 页翻译块 40 → 29，但**段落切分仍不对**（`ETERNAL:`/`CELESTIAL PIPING:` 等
  标签段被从中间切开）。加上悬挂缩进感知的切分规则后 → **6 个语义段**，
  正好对应 `Nemesis…` / `ETERNAL:` / `CELESTIAL PIPING:` / `GRAVITATIONAL FIELD:` /
  `PERCEIVING:` / `SAN LOSS:`，与原文结构一致。
- 第 3 页（T2 那句 `[...]`）：`r0004+r0005`、`r0006+r0007` 各自合并，
  被切断的那句「trigger event for "The New Age" is the loss of faith between…」
  **合并后落进同一个翻译块**，`[...]` 的成因直接消失。

悬挂缩进检测在两份产物上的误报核对：≥3 行的区域共 105 个，被判为悬挂缩进的 9 个，
逐个看过都确实是悬挂缩进块（怪物数据 / 表格式条目），无误伤普通段落。

`[...]` 在两份产物的**原文里出现 0 次**，译文里出现 1 次 → 判为硬失败不会误伤原文。

## 改动计划

### 1. Phase A：相邻文本区域合并 → `core/page_structure.py`

在 `extract_text_regions`（:849）返回前加一步合并，**保持 PyMuPDF 的原始顺序**
（不按 y 重排，否则会打乱分栏的阅读顺序）。相邻两区域合并的条件全部满足时才合：

- 垂直间隙 `next.y0 - prev.y1` 在 `[0, 0.6 × 行距]` 之间
- 水平投影有重叠
- 主导字号相差 ≤ 12%

行距取前一区域自身的行间距中位数，单行区域退化为 `1.6 × 字号`。

验证：新增 `tests/test_region_merge.py`，用构造的悬挂缩进区域（不读用户 PDF，
沿用 `tests/test_semantic_segments.py` 的合成 fixture 风格）断言
「一行一区域」被合成一个区域，且分栏页的左右栏**不会**被跨栏合并。

### 2. Phase B：悬挂缩进感知的段落切分 → `core/semantic_analyzer.py`

改 `_starts_new_segment`（:758）：把「深于基线 → 新段」改为**先判定基线方向**。

- 先在区域内求 x0 的主导聚类（容差 0.8×字号）作为基线。
- 若 `min(x0) < 基线 - 容差`，判定该区域是**悬挂缩进**块：
  此时**浅于基线**的行才是新段起点，深于基线的行是续行。
- 否则维持现有行为（深于基线 = 新段）。

垂直间距那条规则（`actual > expected * 1.35`）保持不变。

验证：在 `tests/test_semantic_segments.py` 增加悬挂缩进用例，断言
`ETERNAL:` / `CELESTIAL PIPING:` 这类标签各自成段、续行不被切开；
现有 5 个用例必须继续通过（护住普通段落的行为不变）。

### 3. T2：`[...]` 判为硬失败 → `core/translation_validation.py`

新增占位符检测，与现有 `contains_prompt_leak` 同级：模型吐 `[...]` / `[…]`
表示它没能补全被切断的句子，属于静默的正确性问题，应当报错重试而不是入库。
接进 `core/typeset_translation.py::_parse_marked_translations` 的逐块校验。

验证：`tests/test_translation_validation.py` 增加用例；
并断言原文里合法出现的方括号内容（如 `[BLOCK ...]` 标记、正常方括号）不误伤。

### 4. 文档

更新 `docs/OPTIMIZATION_PROGRESS.md`：把 T1/T2 标为已完成，
并**订正文档里对 T1 根因的错误描述**（这一条很重要，否则后来人会照着错的方向改）。
按 `AGENTS.md` 要求更新 `context.md`。

## 已确认的取舍

- **进度缓存失效不做迁移**（你已确认）。区域划分改变后 block_id 变化，
  两份已有产物的 `*_typeset.progress.json` 大面积失效，重跑会重新调 API。
  合并后源文本本身也变了，按源文本哈希迁移基本迁不上，写迁移代码收益极低。
  已有 HTML 产物保留不动。
- **不动 T3/T4/T5/T6**：本次范围只到 T1 + T2。

## 验证方式

1. `.\.venv\Scripts\python.exe -m pytest -q` —— 基线 **742 passed**，改完必须
   全绿且只多不少。重点看 `test_semantic_segments.py`、`test_semantic_analyzer.py`、
   `test_typeset_html_segments.py`、`test_reading_html.py`、`test_layout_hints.py`。
2. 离线回归：用两份现有 `page_structure.json` 跑新分割，人工核对
   第 4 页 40→8 区域、第 3 页那句 `[...]` 的源文本已落进同一块。
3. 不重跑线上翻译任务（不消耗 API）。

## 风险

- 区域合并会改变**所有文档**的区域划分，`exporters/typeset_html.py:204` 与
  `exporters/reading_html.py:176` 都会校验 block 的 region 必须存在——合并后
  区域数变少但 ID 仍来自被保留的那个区域，需确认这两处校验不会报错（测试会覆盖）。
- 合并过激会把标题吸进正文。已用「字号差 ≤ 12%」挡住，
  并在两份真实产物上核对过标题未被吸收。
