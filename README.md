# Delta Green PDF Translator

一个面向 Delta Green / TRPG 英文 PDF 的中文翻译工具。从 PDF 中提取文本，结合术语表调用 DeepSeek API 翻译，输出 HTML、Word 或 Markdown。

适用于含文本层的英文 TRPG 规则书、模组、设定集。扫描版纯图片 PDF 需先 OCR。

---

## 项目架构

```
DGtranslate/
├── app.py                  # Streamlit Web 界面（主要使用入口）
├── translate_pdf.py        # CLI 入口 + 兼容层（re-export shim）
├── core/                   # 核心逻辑包
│   ├── constants.py        #   版本号、格式集合、失败前缀等常量
│   ├── utils.py            #   工具函数（页码解析、路径处理、SHA256）
│   ├── extractor.py        #   PDF 提取（PDFExtractor、ChapterDetector）
│   ├── translator.py       #   翻译引擎（Translator、TokenStats、并发翻译）
│   ├── progress.py         #   进度追踪（断点续翻、线程安全、原子写入）
│   └── glossary.py         #   术语表（加载、匹配、报告生成）
├── exporters/              # 输出格式包
│   ├── _shared.py          #   共享文本处理（分块、去重、分页）
│   ├── html.py             #   HTML 双栏输出
│   ├── word.py             #   Word 文档输出
│   └── markdown.py         #   Markdown 输出
├── tests/                  # 单元测试（pytest，80 个用例）
├── convert_glossary.py     # 术语表格式转换工具
├── test_setup.py           # 环境检测脚本
├── glossary.tsv            # 默认术语表（~500 条 Delta Green 术语）
├── config.example.json     # CLI 配置模板
├── start_web.bat           # 一键启动器（Windows，自动建虚拟环境）
├── start_web.ps1           # 启动器 PowerShell 实现
├── requirements.txt        # Python 依赖锁定
├── uploads/                # Web 上传文件暂存
├── output/                 # 翻译输出目录
├── DESIGN.md               # Web UI 设计规范
├── GUIDE.md                # 面向新手的完整使用教程
├── ROADMAP.md              # 开发路线图
└── TASKS.md                # 当前开发任务
```

### 模块职责

| 模块 | 职责 |
| --- | --- |
| `core/extractor.py` | PDF 打开、版面检测、双栏排序、页眉页脚过滤、章节检测、卡片区块识别 |
| `core/translator.py` | 调用 DeepSeek API，携带上下文窗口，术语注入，重试逻辑，并发翻译调度 |
| `core/progress.py` | 断点续跑，进度元数据指纹校验，线程安全，原子写入 |
| `core/glossary.py` | 术语表加载、最长匹配、术语命中报告生成 |
| `core/constants.py` | 全局常量（prompt 版本、extractor 版本、格式集合） |
| `core/utils.py` | 页码解析、路径处理、文件哈希、失败检测 |
| `exporters/html.py` | 双栏 HTML 阅读版输出 |
| `exporters/word.py` | 可配置版式的 Word 文档输出 |
| `exporters/markdown.py` | Markdown 分页输出 |
| `exporters/_shared.py` | 文本分块、清洗、去重、分页（多格式共用） |
| `translate_pdf.py` | CLI 参数解析、翻译调度、向后兼容 re-export |

> **向后兼容**：`app.py` 的 `from translate_pdf import ...` 无需修改，所有公开符号通过 re-export 层保持可用。

---

## 核心数据流

```
PDF 文件
  │
  ▼
PDFExtractor（PyMuPDF）
  ├─ 版面检测（双栏 / 单栏 / 手册页 / 目录页）
  ├─ 文本块按阅读顺序排序
  ├─ 卡片区块（玩家资料、档案）独立提取
  ├─ 页眉页脚过滤
  └─ 章节标题检测
  │
  ▼
每页文本 + 术语表匹配
  ├─ load_glossary() 加载 TSV
  └─ find_relevant_glossary_terms() 最长匹配，只注入当页命中术语
  │
  ▼
Translator（DeepSeek API）
  ├─ 系统提示词：TRPG 翻译规则（保留骰子记法、属性缩写、卡片标记等）
  ├─ 上一页译文尾部 300 字作为上下文
  ├─ 3 次重试 + 指数退避
  └─ TokenStats 实时统计
  │
  ▼
ProgressTracker
  ├─ 每页完成即写入 progress.json
  ├─ 元数据指纹（PDF hash / 术语表 hash / 模型 / prompt 版本）
  └─ 中断后自动跳过已完成页
  │
  ▼
输出生成
  ├─ HTML：双栏阅读版，卡片独立排版，可打印
  ├─ Word：双栏正文，页眉页脚，可配置字号/行距/分栏
  ├─ Markdown：分页阅读，含 TOC
  └─ 术语命中报告：逐页命中 + 疑似未收录专名
```

---

## 功能一览

| 功能 | 说明 |
| --- | --- |
| PDF 文本提取 | PyMuPDF 读取含文本层 PDF |
| 双栏排版处理 | 识别 TRPG 书籍双栏布局，按阅读顺序合并 |
| 卡片区块检测 | 玩家资料卡、档案等独立提取和排版 |
| 页眉页脚过滤 | 过滤页码、running title 等边缘文字 |
| DeepSeek 翻译 | 通过 OpenAI SDK 兼容接口调用 |
| 术语表强制统一 | TSV 格式，最长匹配，只注入当页相关术语 |
| 并发翻译 | 最多 16 线程 |
| 断点续跑 | progress.json 自动保存，中断后继续 |
| 进度指纹校验 | PDF/术语表/模型变更时警告，防止复用过期译文 |
| 选择性重翻 | 指定页码重新翻译，无需删除进度文件 |
| 失败页管理 | 失败页单独记录，可只重试失败页 |
| 提取预览 | Web 端可预览任意页提取结果 |
| 提取诊断报告 | 输出每页版面、图片、表格和风险提示 |
| 多格式输出 | HTML / Word / Markdown / 术语报告 |
| 图片回填 | 可裁出正文插图并回填到 HTML / Word / Markdown |
| Token 统计 | 实时显示 API 调用数、token 用量、费用 |
| 一键启动 | `start_web.bat` 自动建环境、装依赖、启动 Web |

---

## 环境要求

- Python 3.9+
- DeepSeek API Key（[申请地址](https://platform.deepseek.com/)）
- 含文本层的英文 PDF

---

## 快速开始

### 方式一：一键启动（推荐）

双击 `start_web.bat`，脚本会自动：
1. 创建 `.venv` 虚拟环境
2. 安装所有依赖
3. 启动 Streamlit Web 界面（http://localhost:8501）

### 方式二：手动安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

启动 Web：

```powershell
python -m streamlit run app.py
```

### 方式三：命令行

```powershell
# 使用配置文件
copy config.example.json config.json
# 编辑 config.json 填入 API Key 和 PDF 路径
python translate_pdf.py --config config.json

# 或直接传参
python translate_pdf.py "book.pdf" --api-key sk-xxx --glossary glossary.tsv --format all --workers 4
```

---

## Web 界面用法

启动后在浏览器中操作：

1. 上传 PDF 文件
2. 在侧边栏输入 API Key
3. 选择模型（`deepseek-v4-pro` 质量优先 / `deepseek-v4-flash` 速度优先）
4. 设置并发线程数（推荐 4）和输出格式
5. 可选：上传自定义术语表，设置页码范围
6. 点击「开始翻译」，实时查看进度
7. 完成后下载输出文件

Web 界面额外支持：
- 提取预览（翻译前检查 PDF 提取质量）
- 选择性重翻（输入页码如 `8, 12-15`）
- Word 版式调整（字号、行距、分栏、页眉）
- 完成后自动打开输出文件夹

---

## 命令行用法

### 配置文件

```json
{
  "pdf": "THE MILLENNIUM.pdf",
  "api_key": "sk-你的Key",
  "glossary": "glossary.tsv",
  "provider": "deepseek",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-v4-pro",
  "format": "all",
  "workers": 4,
  "start": 0,
  "end": null
}
```

### 参数说明

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `pdf` | PDF 文件路径 | 必填 |
| `api_key` | DeepSeek API Key | 必填 |
| `glossary` | 术语表路径 | 无 |
| `provider` | 服务名称，用于进度指纹 | `deepseek` |
| `base_url` | OpenAI 兼容接口地址 | `https://api.deepseek.com` |
| `model` | 模型名称 | `deepseek-v4-pro` |
| `format` | 输出格式：`markdown` / `html` / `word` / `both` / `all` | `markdown` |
| `workers` | 并发线程数（1-16） | 1 |
| `start` | 起始页码（从 0 开始） | 0 |
| `end` | 结束页码（不含），`null` 表示全部 | `null` |

命令行参数会覆盖配置文件中的同名字段。

---

## 术语表

默认术语表 `glossary.tsv` 包含约 500 条 Delta Green 专有术语。

格式（TSV，Tab 分隔）：

```
中文译名	英文原名
```

示例：

```
绿色三角洲	Delta Green
旧日支配者	Great Old One
阿撒托斯	Azathoth
```

程序会在每页文本中查找命中的英文术语，只把相关术语加入当前翻译请求，减少 token 占用。

### 转换术语表

如果你有从 PDF 复制出来的原始术语文本：

```powershell
python convert_glossary.py raw_glossary.txt -o glossary.tsv
```

---

## 断点续跑

翻译进度保存在 `{输出文件名}.progress.json`。中断后重新运行同样任务会自动跳过已完成页。

进度文件包含元数据指纹（PDF hash、术语表 hash、模型版本等）。当设置变更时会提示不一致，防止误用过期译文。

### 离线重排

如果已经翻译完成，只想用现有 `.progress.json` 重新生成 Word / HTML / Markdown，可以运行：

```powershell
python rerender_output.py --progress output\book_cn.progress.json --pdf "book.pdf" --format all
```

这不会调用翻译 API。注意：如果旧 progress 里的译文本身已经因为旧提取顺序而错序，重排只能套新版样式，不能自动修正译文顺序；这种页需要用新版提取器重新提取并重翻。

### 失败页与诊断

翻译失败的页会写入 progress.json 的 `failed_pages`，不会当作完成页混入最终译文。Web 端可勾选「只重试失败页」，CLI 可使用：

```powershell
python translate_pdf.py "book.pdf" --api-key sk-xxx --retry-failed
```

每次输出会同时生成 `_extraction_report.md`，用于检查每页版面、图片、表格和明显提取风险。

---

## 依赖

| 包 | 版本 | 用途 |
| --- | --- | --- |
| pymupdf | 1.27.2.3 | PDF 文本提取 |
| openai | 2.36.0 | DeepSeek API 调用（OpenAI 兼容接口） |
| python-docx | 1.2.0 | Word 文档生成 |
| streamlit | 1.57.0 | Web 界面 |

---

## 环境检查

```powershell
python test_setup.py
python test_setup.py --pdf your_file.pdf    # 测试 PDF 提取
python test_setup.py --api-key sk-xxx       # 测试 API 连通
```

---

## 常见问题

### 提示 `PyMuPDF not installed`

```powershell
pip install pymupdf
```

### PowerShell 不允许激活虚拟环境

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 怎么启动 Web？

使用 `python -m streamlit run app.py`，不要用 `python app.py`。

或者直接双击 `start_web.bat`。

### 翻译中断了怎么办？

直接重新运行同一命令，会自动从断点继续。

### 想重翻某几页？

Web 界面：在「重翻页码」输入框填入页码（如 `8, 12-15`）。

CLI：删除 progress.json 中对应条目，或设置 `--start` / `--end` 到目标范围。

---

## 开发与测试

运行单元测试：

```powershell
pip install pytest
python -m pytest tests/ -v
```

测试覆盖：导入兼容性、页码解析、术语匹配、进度文件读写等，共 80 个用例，无需 API Key 或 PDF 文件。

---

## 开发状态

已完成：进度指纹校验、选择性重翻、提取预览、术语命中报告、Word 版式控制、卡片区块检测、一键启动器、**核心模块拆分**。

计划中：失败页管理、回归测试、输出历史。

详见 [ROADMAP.md](ROADMAP.md)。

---

## 使用提醒

本工具仅供个人学习、研究和私下校对使用。请尊重原作版权，不要公开分发或商业使用未经授权的译文。
