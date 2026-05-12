# 绿色三角洲 PDF 翻译工具 v2.0

专为《绿色三角洲（Delta Green）》TRPG 扩展资料设计的 AI 翻译工具。  
使用 DeepSeek V4 API，支持双栏排版识别、术语表、并发翻译、多格式输出。

## ✨ 功能特点

| 功能 | 说明 |
|------|------|
| 智能双栏提取 | 自动检测 TRPG 书籍的双栏排版，按正确阅读顺序提取 |
| 上下文窗口 | 翻译每页时携带前页译文末尾，保证跨页内容连贯 |
| 章节目录检测 | 通过字号/加粗自动识别章节标题，生成目录 |
| 多格式输出 | 支持 Markdown / Word (.docx) / 保留排版 PDF |
| 批量并发 | 多线程同时翻译多页，大幅提升速度 |
| 术语表 | TSV 格式术语表，只传入当前页相关术语，节省 token |
| 断点续翻 | 中断后重新运行自动跳过已完成页面 |
| 费用统计 | 实时显示 token 用量和预估费用（¥） |
| 配置文件 | 所有参数写入 `config.json`，一条命令即可运行 |

## 📦 安装

```bash
pip install pymupdf openai python-docx
```

> `python-docx` 用于 Word 输出，如果你只需要 Markdown 或 PDF 可以不装。

## 🚀 快速开始

### 方式一：使用配置文件（推荐）

首次运行时，创建一个 `config.json`：

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

然后只需一条命令：

```bash
python translate_pdf.py --config config.json
```

搞定！所有参数从配置文件读取，不用每次敲一长串。

### 方式二：命令行参数

```bash
python translate_pdf.py "THE MILLENNIUM.pdf" \
    --api-key sk-你的密钥 \
    --glossary glossary.tsv \
    --format all \
    --workers 4
```

## 📋 完整参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `pdf` | 输入 PDF 文件路径 | 必填 |
| `--config`, `-c` | 配置文件路径（有此参数时其他参数均可省略） | 无 |
| `--api-key` | DeepSeek API Key | 必填 |
| `--output`, `-o` | 输出文件路径（不含扩展名） | `{文件名}_cn` |
| `--glossary`, `-g` | 术语表路径（TSV） | 无 |
| `--model` | 模型名 | `deepseek-v4-pro` |
| `--format`, `-f` | 输出格式（见下表） | `markdown` |
| `--workers`, `-w` | 并发线程数（1-16） | `1` |
| `--start` | 起始页码（从0开始） | `0` |
| `--end` | 结束页码（不含） | 全部 |

### 输出格式选项

| 值 | 输出文件 |
|----|----------|
| `markdown` | `.md` 文件 |
| `pdf` | 保留原排版的中文 PDF |
| `word` | Word `.docx` 文件 |
| `both` | Markdown + PDF |
| `all` | Markdown + PDF + Word（推荐） |

## 📚 术语表格式

TSV 文件，每行一条，Tab 分隔：

```
中文译名	英文原名
```

示例：
```
绿色三角洲	Delta Green
旧日支配者	Great Old One
阿撒托斯	Azathoth
火灵	ifrit
```

- 以 `#` 开头的行为注释
- 脚本自动匹配当前页出现的术语，只将相关条目传入 prompt

### 术语表生成

如果你的术语表也是 PDF 格式：
1. **推荐**：截图发给多模态 AI（GPT-4o、Claude），让它直接输出 TSV 格式
2. **备选**：手动复制后使用 `convert_glossary.py` 辅助转换：
   ```bash
   python convert_glossary.py raw_glossary.txt -o glossary.tsv
   ```

## 💰 费用参考

以 320 页 PDF 为例（DeepSeek V4 Pro，75% 折扣期至 2026/05/31）：

| 模式 | 预估费用 | 耗时 |
|------|----------|------|
| 单线程 Pro | ¥5-15 | ~40 分钟 |
| 4线程 Pro | ¥5-15 | ~12 分钟 |
| 4线程 Flash | ¥1-3 | ~8 分钟 |

翻译完成后会显示精确的 token 统计和费用。

## 🔄 断点续翻

- 进度自动保存到 `{输出文件}.progress.json`
- 中断后重新运行相同命令即可继续
- 已完成的页面自动跳过
- 如需重翻：删除进度文件或指定新输出文件名

## ⚠️ 已知限制

1. **PDF 排版输出**：效果取决于原 PDF 文本层质量，复杂背景/图片上的文字可能显示不佳
2. **双栏检测**：对绝大多数 TRPG 书籍有效，但极端排版（多层嵌套方框）可能需调整
3. **并发与上下文**：高并发时上下文连贯性略有降低（每组内共享上下文）
4. **Word 输出**：需安装 `python-docx`，排版为简洁的标题+正文样式

## 📄 许可

本工具仅供个人学习使用。请尊重原作版权。
