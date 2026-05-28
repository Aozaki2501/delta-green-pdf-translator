# 🎲 使用教程 — 绿色三角洲 PDF 翻译工具

> 本教程面向 Windows 用户，从零开始，手把手带你跑通整个翻译流程。

---

## 📋 目录

1. [环境准备](#1-环境准备)
2. [下载项目](#2-下载项目)
3. [准备术语表](#3-准备术语表)
4. [测试翻译（5页）](#4-测试翻译5页)
5. [检查翻译质量](#5-检查翻译质量)
6. [正式翻译全书](#6-正式翻译全书)
7. [使用 Web 界面](#7-使用-web-界面)
8. [常见问题](#8-常见问题)

---

## 1. 环境准备

### 1.1 确认 Python 已安装

打开 **PowerShell**（Win+X → Windows PowerShell），输入：

```powershell
python --version
```

如果显示 `Python 3.9` 或更高版本就行。如果提示找不到命令：
- 去 https://www.python.org/downloads/ 下载安装
- 安装时 **一定要勾选** "Add Python to PATH"

### 1.2 安装依赖

在 PowerShell 中运行：

```powershell
pip install pymupdf openai python-docx gradio
```

等几分钟装完就行。如果提示权限问题，改用：

```powershell
pip install --user pymupdf openai python-docx gradio
```

### 1.3 准备 API Key

1. 打开 https://platform.deepseek.com/
2. 注册/登录
3. 进入 "API Keys" 页面
4. 点击 "创建 API Key"
5. 复制保存（以 `sk-` 开头的一串字符）

> ⚠️ API Key 像密码一样重要，不要分享给别人。

---

## 2. 下载项目

### 方式 A：直接下载 ZIP（最简单）

1. 打开 https://github.com/Aozaki2501/delta-green-pdf-translator
2. 点击绿色的 **Code** 按钮 → **Download ZIP**
3. 解压到你喜欢的位置（比如桌面）

### 方式 B：用 Git

```powershell
git clone https://github.com/Aozaki2501/delta-green-pdf-translator.git
```

### 项目结构

解压/克隆后你会看到：

```
delta-green-pdf-translator/
├── translate_pdf.py       ← 主翻译脚本
├── app.py                 ← Web 界面
├── convert_glossary.py    ← 术语表转换辅助
├── glossary.tsv           ← 预置术语表（不完整，需你补充）
├── config.example.json    ← 配置文件模板
└── README.md              ← 说明文档
```

---

## 3. 准备术语表

### 3.1 生成术语表（推荐方法）

1. 打开你的术语表 PDF
2. 截图每一页
3. 发给多模态 AI（GPT-4o / Claude / Gemini），prompt：

```
请将这页术语表转为 TSV 格式，每行一条：
中文译名[Tab]英文原名
不要添加标题行或注释，直接输出数据。
```

4. 把 AI 输出的内容保存为 `glossary.tsv`

### 3.2 验证格式

用记事本打开 `glossary.tsv`，确认格式是：

```
绿色三角洲	Delta Green
旧日支配者	Great Old One
阿撒托斯	Azathoth
```

> 中文和英文之间是一个 **Tab 键**（不是空格）。

---

## 4. 测试翻译（5页）

### 4.1 创建配置文件

把 `config.example.json` 复制一份，改名为 `config.json`，用记事本编辑：

```json
{
    "pdf": "THE MILLENNIUM.pdf",
    "api_key": "sk-在这里粘贴你的API Key",
    "glossary": "glossary.tsv",
    "model": "deepseek-v4-pro",
    "format": "markdown",
    "workers": 32,
    "start": 0,
    "end": 5
}
```

> ⚠️ 把你的 PDF 文件放到**同一个文件夹**里，或者写完整路径。

### 4.2 运行翻译

在 PowerShell 中进入项目文件夹并运行：

```powershell
cd 桌面\delta-green-pdf-translator
python translate_pdf.py --config config.json
```

### 4.3 预期输出

```
============================================================
  DG TRPG PDF Translator v2.0 - THE MILLENNIUM
============================================================

Opening PDF: THE MILLENNIUM.pdf
   Total pages: 320
   Range: page 1 to 5
   Workers: 1
   Format: markdown

Loading glossary: glossary.tsv
   Loaded 139 terms

Engine: DeepSeek V4 (deepseek-v4-pro)

Extracting text and analyzing chapters...
   Detected 3 headings

Translating...
----------------------------------------
  [20%] Page 1/320 done (¥0.008)
  [40%] Page 2/320 done (¥0.019)
  [60%] Page 3/320 done (¥0.031)
  [80%] Page 4/320 done (¥0.042)
  [100%] Page 5/320 done (¥0.054)
----------------------------------------

  生成 Markdown: THE MILLENNIUM_cn.md
   ✅ Markdown 输出完成

  共翻译 5 页

Time: 23.4s (0.4 min)

Token Stats:
   Input: 8,432 tokens
   Output: 6,218 tokens
   Cache hit: 0 tokens
   API calls: 5 (failed 0)
   Est. cost: ¥0.054
```

### 4.4 查看结果

翻译完成后，文件夹里会多出一个 `THE MILLENNIUM_cn.md`，用以下任一工具打开：

- **VS Code**（推荐，装 Markdown Preview 插件）
- **Typora**
- **Obsidian**
- 或直接用记事本看

---

## 5. 检查翻译质量

打开翻译结果，重点检查：

| 检查项 | 正确示例 | 错误示例 |
|--------|----------|----------|
| 骰子记法保留 | `造成 3D6 伤害` | `造成三D六伤害` |
| 属性缩写保留 | `失去 1/1D6 SAN` | `失去1/1D6理智` |
| 术语一致 | `旧日支配者` | `古老者`/`旧神` |
| 跨页连贯 | 下一页接上文意思 | 突然语义断裂 |
| 乱码处理 | `[原文损坏]` 标注 | 翻译出无意义文字 |

### 如果质量不满意

- **术语不对** → 检查/补充 `glossary.tsv`
- **翻译太生硬** → 可以试试 `deepseek-v4-flash`，有时候反而更通顺
- **有乱码段落** → PDF 提取问题，属于正常现象，忽略即可
- **跨页不连贯** → 确认 `workers` 为 1 时效果最好

---

## 6. 正式翻译全书

测试满意后，修改 `config.json`：

```json
{
    "pdf": "THE MILLENNIUM.pdf",
    "api_key": "sk-你的密钥",
    "glossary": "glossary.tsv",
    "model": "deepseek-v4-pro",
    "format": "all",
    "workers": 32,
    "start": 0,
    "end": null
}
```

变化：
- `"format": "all"` → 同时输出 Markdown + PDF + Word
- `"workers": 32` → 32线程并发，速度更快
- `"end": null` → 翻译到最后一页

运行：

```powershell
python translate_pdf.py --config config.json
```

> 💡 翻译过程中如果需要中断（关窗口 / Ctrl+C），下次运行同一命令会自动从断点继续，不会重复翻译。

### 预估

| 项目 | 数值 |
|------|------|
| 总时间 | 10-15 分钟（4线程） |
| 费用 | ¥5-15（Pro）/ ¥1-3（Flash） |
| 输出文件 | `.md` + `.pdf` + `.docx` 三个 |

---

## 7. 使用 Web 界面

如果你觉得命令行不方便，可以用 Web 界面：

```powershell
python app.py
```

浏览器会自动打开 `http://localhost:7860`，然后：

1. 上传 PDF 文件
2. 上传术语表（可选）
3. 填入 API Key
4. 选择模型、格式、并发数
5. 设置页码范围（测试时结束页填 `5`）
6. 点击 **🔺 开始翻译**
7. 翻译完成后点 **📥 下载** 按钮获取文件

---

## 8. 常见问题

### Q: 运行时报错 `ModuleNotFoundError: No module named 'pymupdf'`

```powershell
pip install pymupdf
```

### Q: 报错 `openai.AuthenticationError` 或 `401`

API Key 不对。检查：
- 是否完整复制了（以 `sk-` 开头）
- DeepSeek 账号是否有余额
- Key 是否过期

### Q: 报错 `429 Too Many Requests`

DeepSeek API 限速了。解决方案：
- 把 `workers` 降低到 `2` 或 `1`
- 等一分钟再运行，脚本会自动重试

### Q: 翻译到一半断了怎么办

直接重新运行同一条命令即可。脚本会自动跳过已完成的页面。

### Q: PDF 输出效果不好

保留排版 PDF 是"尽力而为"的——对于 DG 这种复杂排版（双栏+背景图+方框），效果可能不完美。建议以 **Markdown** 或 **Word** 为主要阅读格式。

### Q: 想换一个 PDF 翻译

修改 `config.json` 里的 `"pdf"` 路径即可。术语表是通用的，不需要改。

### Q: 想只重翻某几页

1. 删除 `THE MILLENNIUM_cn.md.progress.json` 文件（或直接删除进度文件中对应页码）
2. 设置 `start` 和 `end` 到你想重翻的范围
3. 重新运行

---

## 📎 速查表

| 操作 | 命令 |
|------|------|
| 安装依赖 | `pip install pymupdf openai python-docx gradio` |
| 测试5页 | 修改 config.json `"end": 5` → `python translate_pdf.py --config config.json` |
| 翻译全书 | 修改 config.json `"end": null` → `python translate_pdf.py --config config.json` |
| 启动界面 | `python app.py` |
| 转换术语表 | `python convert_glossary.py raw.txt -o glossary.tsv` |

---

*▲ DELTA GREEN — THE WORKING GROUP DOES NOT EXIST*
