# Delta Green PDF Translator

<p align="center">
  <strong>专为《绿色三角洲》TRPG 扩展资料设计的 AI 翻译工具</strong><br>
  DeepSeek V4 驱动 · 双栏智能提取 · 术语表对照 · 并发翻译 · 多格式输出
</p>

---

## 概述

本工具用于将 Delta Green TRPG 英文 PDF 规则书翻译为中文。针对 TRPG 书籍的双栏排版做了专门优化，支持术语表强制对照、跨页上下文连贯、断点续翻等特性。

提供命令行和 Web 两种使用方式，适合不同习惯的用户。

## 核心功能

| 功能 | 说明 |
|------|------|
| 双栏智能提取 | 自动检测双栏排版，按正确阅读顺序合并文本 |
| 上下文窗口 | 翻译时携带前一页译文尾部，保证跨页语义连贯 |
| 章节目录生成 | 通过字号/加粗自动识别标题层级，生成可跳转目录 |
| TRPG 术语表 | TSV 格式，仅传入当前页匹配的术语，节省 token |
| 并发翻译 | 多线程同时处理多页，4 线程约 12 分钟完成 320 页 |
| 断点续翻 | 中断后重新运行自动跳过已完成页面 |
| 多格式输出 | Markdown / Word (.docx) / 保留排版 PDF |
| 实时费用统计 | 显示 token 用量与预估花费（¥） |
| 配置文件 | 所有参数写入 `config.json`，一条命令运行 |
| Web 界面 | Streamlit 驱动的终端风格浏览器界面 |

## 环境要求

- Python 3.9+
- [DeepSeek API Key](https://platform.deepseek.com/)

## 安装

```bash
# 克隆项目
git clone https://github.com/Aozaki2501/delta-green-pdf-translator.git
cd delta-green-pdf-translator

# 安装依赖
pip install pymupdf openai python-docx streamlit
```

> `python-docx` 用于 Word 输出，`streamlit` 用于 Web 界面。如果只需命令行 + Markdown，可仅安装 `pymupdf openai`。

## 快速开始

### 1. 创建配置文件

```bash
cp config.example.json config.json
```

编辑 `config.json`：

```json
{
    "pdf": "THE MILLENNIUM.pdf",
    "api_key": "sk-你的DeepSeek密钥",
    "glossary": "glossary.tsv",
    "model": "deepseek-v4-pro",
    "format": "all",
    "workers": 4,
    "start": 0,
    "end": null
}
```

### 2. 运行翻译

```bash
python translate_pdf.py --config config.json
```

翻译完成后将在同目录生成 `_cn.md`、`_cn.pdf`、`_cn.docx` 三种格式的译文。

### 3. 测试少量页面（推荐先试 5 页）

将 `config.json` 中 `"end"` 改为 `5`，确认效果后再翻译全书。

## 命令行用法

```bash
# 使用配置文件（推荐）
python translate_pdf.py --config config.json

# 纯命令行参数
python translate_pdf.py "THE MILLENNIUM.pdf" \
    --api-key sk-xxx \
    --glossary glossary.tsv \
    --format all \
    --workers 4

# 翻译指定范围
python translate_pdf.py "THE MILLENNIUM.pdf" \
    --api-key sk-xxx \
    --start 10 --end 20
```

### 参数一览

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `pdf` | PDF 文件路径 | 必填 |
| `--config`, `-c` | 配置文件路径 | — |
| `--api-key` | DeepSeek API Key | 必填 |
| `--output`, `-o` | 输出路径（不含扩展名） | `{文件名}_cn` |
| `--glossary`, `-g` | 术语表 TSV 路径 | — |
| `--model` | 模型名称 | `deepseek-v4-pro` |
| `--format`, `-f` | 输出格式 | `markdown` |
| `--workers`, `-w` | 并发线程数 (1–16) | `1` |
| `--start` | 起始页码 (0-indexed) | `0` |
| `--end` | 结束页码（不含） | 全部 |

### 输出格式

| 值 | 输出 |
|----|------|
| `markdown` | `.md` |
| `pdf` | 保留原排版的中文 PDF |
| `word` | `.docx` |
| `both` | Markdown + PDF |
| `all` | Markdown + PDF + Word |

## Web 界面

```bash
streamlit run app.py
```

浏览器打开后上传 PDF、填入 API Key，即可在网页上完成翻译并下载结果。界面采用复古终端视觉风格。

## 术语表

项目附带 `glossary.tsv`，已收录 Delta Green: THE MILLENNIUM 的核心术语（组织、人物、神话存在、地点、法术、游戏术语等）。

### 格式规范

每行一条，Tab 分隔，`#` 开头为注释：

```
中文译名\t英文原名
```

示例：
```
绿色三角洲	Delta Green
旧日支配者	Great Old One
阿撒托斯	Azathoth
星之彩	Colour Out of Space
```

### 生成术语表

如果你的术语来源是 PDF：
1. **推荐**：截图发给多模态 AI（GPT-4o / Claude），让它直接输出 TSV
2. **备选**：手动复制后用 `convert_glossary.py` 转换：
   ```bash
   python convert_glossary.py raw_glossary.txt -o glossary.tsv
   ```

## 费用参考

以 320 页 PDF、DeepSeek V4 Pro 为例：

| 配置 | 预估费用 | 耗时 |
|------|----------|------|
| 单线程 Pro | ¥5–15 | ~40 min |
| 4 线程 Pro | ¥5–15 | ~12 min |
| 4 线程 Flash | ¥1–3 | ~8 min |

## 断点续翻

- 进度自动保存至 `{输出文件}.progress.json`
- 中断后重新运行相同命令即可继续
- 如需重翻某些页，删除进度文件或指定新输出名

## 环境检测

```bash
python test_setup.py
python test_setup.py --api-key sk-xxx        # 可选：测试 API 连通
python test_setup.py --pdf your_file.pdf      # 可选：测试 PDF 提取
```

## 项目结构

```
delta-green-pdf-translator/
├── translate_pdf.py       # 核心翻译引擎
├── app.py                 # Streamlit Web 界面
├── convert_glossary.py    # 术语表格式转换工具
├── glossary.tsv           # 预置 TRPG 术语表
├── test_setup.py          # 环境检测脚本
├── config.example.json    # 配置文件模板
├── GUIDE.md              # 详细使用教程（面向新手）
└── README.md             # 本文件
```

## 已知限制

- **PDF 排版输出**：实验性功能，复杂背景/图片上文字效果有限，建议以 Markdown 或 Word 为主
- **双栏检测**：对常规 TRPG 书籍有效，极端嵌套排版可能需手动调整
- **高并发与连贯性**：线程数越高，跨页语义连贯性略有下降（组内共享上下文）
- **扫描版 PDF**：仅支持含文本层的 PDF，纯图片扫描件需先 OCR

## 许可

本工具仅供个人学习与研究使用。请尊重原作版权，勿用于商业用途或公开分发译文。
