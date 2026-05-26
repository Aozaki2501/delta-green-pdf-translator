# Markdown / Word 输入翻译开发计划

## 目标

支持 Markdown 文件和 Word 文档作为翻译输入源，翻译后输出**保持原文排版格式**的同类型文件。

核心原则：
- Markdown 输入 → 翻译 → 输出同结构的 Markdown（标题层级、列表、表格、代码块完整保留）
- Word 输入 → 翻译 → 输出同排版的 Word（样式、字号、颜色、分栏、表格格式完整保留）
- 复用现有翻译引擎、术语表、断点续跑、Token 统计等全部基础设施
- Web UI 统一入口，用户选择上传文件类型即可

## 现状

当前项目只支持 PDF 作为输入源。翻译引擎按"页"为单位工作：
- `PDFExtractor` 提取每页文本
- `Translator.translate_chunk()` 翻译单个文本块
- `ProgressTracker` 按页号记录进度
- 输出器按页号组装最终文件

扩展为 Markdown/Word 输入需要：
1. 新的提取器（按段落/章节拆分，而非按页）
2. 适配进度追踪器（从"页"到"块"）
3. 新的"保留格式"输出器（读取原文件结构，替换为译文）

## 开发计划

### Phase 1：Markdown 输入 → 翻译 → Markdown 输出

#### 1.1 Markdown 提取器 `core/md_extractor.py`

职责：
- 解析 Markdown 文件为有序的翻译单元（块）列表
- 每个块包含：块类型、原文、在文件中的位置信息

块类型划分：
| 类型 | 翻译策略 |
|------|----------|
| `heading` | 翻译文本，保留 `#` 层级 |
| `paragraph` | 翻译全段 |
| `list_item` | 翻译文本，保留 `- ` / `1. ` 前缀和缩进 |
| `table` | 逐单元格翻译，保留表格结构 |
| `blockquote` | 翻译文本，保留 `> ` 前缀 |
| `code_block` | 不翻译，原样保留 |
| `front_matter` | 不翻译，原样保留（YAML header） |
| `html_block` | 不翻译，原样保留 |
| `horizontal_rule` | 不翻译，原样保留 |
| `image_link` | 不翻译，原样保留（`![alt](url)` 整行跳过） |
| `empty_line` | 不翻译，原样保留（保持段落间距） |

分块合并策略：
- 连续的 paragraph 块如果总 token 数 < 2000，合并为一个翻译请求
- heading 始终单独成块（保留上下文边界）
- table 整表作为一个翻译请求
- 合并时记录原始块边界，翻译完成后按边界拆回

#### 1.2 Markdown 输出器 `exporters/md_preserve.py`

职责：
- 接收翻译后的块列表
- 按原始文件结构重新组装 Markdown
- 保留原文中的空行、分隔线、代码块等非翻译内容的精确位置

#### 1.3 进度适配

- 将进度追踪从"页号"泛化为"块号"
- `ProgressTracker` 已有 `mark_completed(index, text)` 接口，只要 index 从页号改为块号即可
- 元数据中记录源文件 hash、块数、术语表 hash

#### 1.4 翻译 Prompt 适配

- 新增 Markdown 专用 system prompt（比 PDF prompt 简化，去掉双栏/卡片/属性块等规则）
- 保留术语表、TRPG 规则术语保留、Markdown 格式保留等核心指令
- 保留上下文窗口（前一个块的译文作为 context）

---

### Phase 2：Word 输入 → 翻译 → Word 输出（保留排版）

#### 2.1 Word 提取器 `core/docx_extractor.py`

职责：
- 用 `python-docx` 打开 Word 文件
- 遍历 `document.paragraphs`、`document.tables`、`document.sections`
- 为每个可翻译元素生成翻译单元

翻译单元结构：
```python
@dataclass
class DocxBlock:
    index: int              # 块序号
    block_type: str         # paragraph / table_cell / header / footer
    text: str               # 原文纯文本
    style_name: str         # Word 样式名（Heading 1, Normal, etc.）
    runs_metadata: list     # 每个 run 的字号/加粗/颜色/字体等
    parent_path: str        # 定位信息（如 table[2].row[1].cell[0]）
```

特殊处理：
- 表格：逐单元格翻译，保留合并单元格结构、交替行色、边框样式
- 页眉页脚：可选翻译（默认不翻译）
- 图片/嵌入对象：原样保留，不处理
- 空段落：跳过（用于排版间距，直接保留）
- **文本框（Text Box / Sidebar）**：Phase 2 必须支持。通过操作底层 XML（`w:txbxContent`）提取文本框内段落，翻译后回填。文本框的边框、底色、位置信息全部保留
- 形状中的文本（SmartArt 等）：Phase 2 暂不处理

#### 2.2 Word "原地替换"输出器 `exporters/docx_inplace.py`

核心思路：**不从零生成新 Word，而是复制原文件，替换文本内容**。

流程：
1. 复制原 `.docx` 到输出目录
2. 用 `python-docx` 打开副本
3. 按 `parent_path` 定位到每个段落/单元格
4. 清空原 runs，写入译文
5. 恢复原 runs 的格式属性（字号、加粗、颜色、字体）
6. 保存

格式保留策略：
- 如果原段落只有 1 个 run → 译文写入该 run，保留所有格式
- 如果原段落有多个 run（混合格式，如粗体术语 + 普通文本）→ **逐 run 策略**：
  - 将 runs 序列化为带标记的文本（如 `<b>HUMINT or Psychotherapy 40%</b>: He's talking like...`）
  - AI 翻译时保留内联标记
  - 翻译结果按标记拆分，映射回对应 run 的格式属性
  - 回退方案：如果标记对应失败，使用第一个 run 的格式应用到全段
- 中文字体回退：如果原字体不支持中文，自动替换为中文可用字体（如"Microsoft YaHei"或"SimSun"），仅修改字体名，其余格式不变
- 表格列宽、行高、边框、交替行色：全部保留（不修改表格结构）
- 分栏、页边距、页面大小：全部保留（不修改 section 属性）

#### 2.3 中文字号自动调整

中文翻译通常比英文更长。处理策略：
- 如果译文字符数 > 原文字符数 × 1.5，且原字号 > 10pt → 可选自动缩小 1-2pt
- 默认不自动缩小，只在溢出报告中提示
- 用户可在 Web UI 开启"自动缩字"选项

---

### Phase 3：Web UI 集成

#### 3.1 文件上传扩展

- 上传区域支持 `.pdf` / `.md` / `.docx` 三种类型
- 自动检测文件类型，切换对应的提取器和输出器
- 非 PDF 输入时隐藏 PDF 专用选项（如双栏检测、坐标 PDF 导出）

#### 3.2 输出格式联动

| 输入 | 可选输出格式 |
|------|-------------|
| PDF | Markdown, HTML, Word, 原版坐标 PDF |
| Markdown | Markdown（保留格式）, HTML, Word |
| Word | Word（保留格式）, Markdown, HTML |

#### 3.3 预览面板

- Markdown 输入：显示前 N 个块的原文预览
- Word 输入：显示段落列表 + 样式标注

#### 3.4 进度和审计

- 审计记录扩展 `source_type` 字段（pdf / markdown / docx）
- 输出历史显示源文件类型图标

---

### Phase 4：进阶功能（可选）

#### 4.1 双语对照输出

- Markdown：原文段落后紧跟译文段落（用 `> ` 或颜色区分）
- Word：原文段落 + 译文段落交替排列，译文使用不同颜色

#### 4.2 Word SmartArt / 复杂形状翻译

- 提取 Word 中嵌入的 SmartArt、流程图等形状内文本
- 翻译后回填

#### 4.3 批量文件翻译

- 上传一个文件夹（zip）包含多个 .md 或 .docx
- 按文件逐个翻译，统一输出

#### 4.4 MinerU Markdown 特殊处理

- 识别 MinerU 导出格式的特征（远程 CDN 图片链接、特定标题结构）
- 可选：翻译后自动下载远程图片到本地 assets/ 目录
- 可选：清理 MinerU 导出的冗余空行和格式噪音

---

## 文件结构变更

```
core/
    md_extractor.py          ← NEW: Markdown 解析和分块
    docx_extractor.py        ← NEW: Word 解析和分块
    translator.py            ← 修改: 新增 Markdown 专用 prompt
    progress.py              ← 修改: 泛化 index 类型
exporters/
    md_preserve.py           ← NEW: 保留格式的 Markdown 输出
    docx_inplace.py          ← NEW: 原地替换的 Word 输出
app.py                       ← 修改: 文件类型检测、UI 联动
```

## 依赖

- 无新依赖：`python-docx` 已在 requirements.txt 中
- Markdown 解析考虑使用标准库 `re` + 简单状态机（避免引入重型 Markdown AST 库）
- 如果需要更精确的 Markdown 解析，可选引入 `mistune` 或 `markdown-it-py`

## 完成标准

Phase 1 完成标准：
- 输入一个带标题、列表、表格、代码块的 Markdown 文件
- 翻译后输出的 Markdown 结构完全一致（diff 只有文本内容变化）
- 断点续跑正常工作
- 术语表正常命中

Phase 2 完成标准：
- 输入一个带样式、表格、分栏的 Word 文件
- 翻译后输出的 Word 视觉排版与原文一致（字号、颜色、分栏、表格结构）
- 中文字体正常显示
- 不丢失图片和嵌入对象

Phase 3 完成标准：
- Web UI 支持上传三种文件类型
- 输出格式联动正确
- 审计记录和输出历史正常显示

## 开发顺序建议

1. Phase 1（Markdown）→ 最简单，验证整体架构可行性
2. Phase 2（Word）→ 核心价值，TRPG 社区大量使用 Word 排版
3. Phase 3（Web UI）→ 体验完善
4. Phase 4（可选）→ 按需求优先级逐步添加



---

## 附录：已知输入文件格式分析

### Word 文件特征（Delta Green 模组）

基于实际样本观察到的排版元素：

| 元素 | 详情 | 处理难度 |
|------|------|----------|
| 正文段落 | 标准段落，无分栏 | ⭐ 低 |
| 多级列表 | `●` 一级 + `○` 二级嵌套 | ⭐ 低 |
| 粗体术语 | 如 **HUMINT or Psychotherapy 40%**，run 级别格式 | ⭐⭐ 中 |
| 斜体引用 | 如 *Handler's Guide p59*、*Le roi en jaune* | ⭐⭐ 中 |
| 带边框文本框 | Sidebar 类型，包含大段正文（如 STATIC Protocol 说明） | ⭐⭐⭐ 高 |
| 表格 | d10 随机表，带序号列 + 描述列，交替行色 | ⭐⭐ 中 |
| 表格内段落 | 单元格内有完整句子和多行文本 | ⭐⭐ 中 |
| 游戏术语内联 | 骰子记号（1D6）、属性缩写（SAN）内嵌在正文中 | ⭐ 低（已有规则） |
| 括号标注 | 如 (SIGINT 20%)、(HUMINT or Psychotherapy 40%) | ⭐ 低 |

**关键风险**：
- 文本框（Text Box）`python-docx` 不直接支持，需要操作底层 XML
- 粗体/斜体的 run 边界在翻译后可能对不上（中文句子结构变化）

### Markdown 文件特征（MinerU PDF 导出）

基于实际样本观察到的格式元素：

| 元素 | 详情 | 处理难度 |
|------|------|----------|
| `#` 标题 | 标准 ATX 标题，层级清晰 | ⭐ 低 |
| 段落文本 | 纯英文段落，无特殊内联标记 | ⭐ 低 |
| 远程图片 | `![image](https://cdn-mineru.openxlab.org.cn/...)` | ⭐ 低（跳过） |
| 无表格 | 样本中未见 Markdown 表格 | — |
| 无代码块 | 样本中未见 | — |
| 无 front matter | 样本中未见 YAML header | — |
| 空行分隔 | 段落间有空行分隔 | ⭐ 低 |

**MinerU 导出特征**：
- 第一行通常是 `![image](url)` 的封面图
- 标题使用标准 `#` 语法
- 结构非常干净，基本就是"标题 + 段落"
- 无复杂 Markdown 扩展语法（无 callout、wiki link、脚注等）

### 结论

- **Markdown 路径**：非常简单，基本是标题 + 段落的线性结构，Phase 1 可以快速完成
- **Word 路径**：中等复杂度，核心难点在于文本框提取和内联格式（粗体/斜体）保留
