# Delta Green PDF Translator

一个面向 Delta Green / TRPG 英文 PDF 的中文翻译工具。它会从 PDF 中提取文本，结合术语表调用 DeepSeek API 翻译，并输出 Markdown、Word 或实验性的排版保留 PDF。

项目提供两个入口：

- `app.py`：Streamlit Web 界面，适合日常使用。
- `translate_pdf.py`：命令行入口，适合批处理和配置文件运行。

## 功能概览

| 功能 | 说明 |
| --- | --- |
| PDF 文本提取 | 使用 PyMuPDF 读取含文本层的 PDF |
| 双栏排版处理 | 尝试识别 TRPG 书籍常见双栏布局，按阅读顺序合并文本 |
| 页眉页脚过滤 | 过滤页码、running title，以及 `DELTA GREEN`、`PISCES`、`THE MILLENNIUM` 等常见页边文字 |
| DeepSeek 翻译 | 通过 OpenAI SDK 兼容接口调用 DeepSeek 模型 |
| 术语表 | 使用 `glossary.tsv` 强制统一专名翻译 |
| 并发翻译 | Web 和 CLI 都支持多线程翻译 |
| 断点续跑 | 自动保存 `{输出名}.progress.json`，中断后可继续 |
| 多格式输出 | 支持 Markdown、Word `.docx`、实验性 PDF 覆写输出 |
| Token 统计 | 显示 API 调用、token 用量和预估费用 |

## 环境要求

- Python 3.9+
- DeepSeek API Key
- 一个含文本层的 PDF 文件

扫描版纯图片 PDF 需要先 OCR，否则本工具无法直接提取文字。

## 安装

推荐在项目目录中使用虚拟环境。Windows PowerShell 示例：

```powershell
cd E:\DG
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install pymupdf openai python-docx streamlit
```

如果 PowerShell 不允许激活虚拟环境，先在当前窗口临时放开执行策略：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

如果系统找不到 `pip`，不要直接运行 `pip install ...`，改用：

```powershell
python -m pip install pymupdf openai python-docx streamlit
```

如果 `python -m pip` 也不可用：

```powershell
python -m ensurepip --upgrade
python -m pip install pymupdf openai python-docx streamlit
```

安装验证：

```powershell
python -c "import pymupdf, openai, docx, streamlit; print('OK')"
```

## Web 界面用法

不要用 `python app.py` 启动 Streamlit 应用。请使用：

```powershell
python -m streamlit run app.py
```

打开浏览器后：

1. 上传 PDF。
2. 输入 DeepSeek API Key。
3. 选择模型、并发线程数和输出格式。
4. 可选上传术语表。
5. 点击开始翻译，完成后下载结果。

Web 输出默认写入：

```text
uploads/
output/
```

这些目录已在 `.gitignore` 中忽略。

## 命令行用法

最简单的方式是复制配置模板：

```powershell
Copy-Item config.example.json config.json
```

编辑 `config.json`：

```json
{
  "pdf": "THE MILLENNIUM.pdf",
  "api_key": "sk-你的 DeepSeek API Key",
  "glossary": "glossary.tsv",
  "model": "deepseek-v4-pro",
  "format": "all",
  "workers": 4,
  "start": 0,
  "end": null
}
```

运行：

```powershell
python translate_pdf.py --config config.json
```

也可以直接传参：

```powershell
python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx --glossary glossary.tsv --format all --workers 4
```

只翻译部分页，适合先测试效果：

```powershell
python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx --start 0 --end 5
```

页码参数从 `0` 开始，`--end` 不包含该页。

## 输出格式

| 参数 | 输出 |
| --- | --- |
| `markdown` | `.md` |
| `word` | `.docx` |
| `pdf` | 在原 PDF 上覆盖写入中文，实验性功能 |
| `both` | Markdown + PDF |
| `all` | Markdown + PDF + Word |

建议校对和继续排版时优先使用 Word 或 Markdown。PDF 覆写适合快速预览，但复杂背景、图文混排和文字框空间不足时效果可能不稳定。

## 术语表

默认术语表是 `glossary.tsv`。

格式：

```text
中文译名<TAB>英文原名
```

示例：

```text
绿色三角洲	Delta Green
旧日支配者	Great Old One
阿撒托斯	Azathoth
星之彩	Colour Out of Space
```

程序会在每页文本中查找命中的英文术语，只把相关术语加入当前翻译请求，减少 token 占用。

如果你有从 PDF 复制出来的原始术语文本，可以尝试转换：

```powershell
python convert_glossary.py raw_glossary.txt -o glossary.tsv
```

## 断点续跑

翻译进度会保存到：

```text
{输出文件名}.progress.json
```

中断后重新运行同样任务，会自动跳过已完成页。不要手动删除 progress 文件，除非你想从头重翻或更换输出名。

## 环境检查

```powershell
python test_setup.py
python test_setup.py --pdf your_file.pdf
python test_setup.py --api-key sk-xxx
```

注意：不要把真实 API Key 提交到 Git。建议把真实配置写在本地 `config.json`，不要改 `config.example.json`。

## 常见问题

### 提示 `PyMuPDF not installed`

当前 Python 环境缺少 `pymupdf`：

```powershell
python -m pip install pymupdf
```

### PowerShell 提示找不到 `pip`

使用：

```powershell
python -m pip install pymupdf openai python-docx streamlit
```

### 安装时出现 `Scripts is not on PATH`

这是警告，不一定是错误。只要下面命令可以导入依赖，就可以继续：

```powershell
python -c "import pymupdf, openai, docx, streamlit; print('OK')"
```

### 应该怎么启动 Web？

使用：

```powershell
python -m streamlit run app.py
```

不要使用：

```powershell
python app.py
```

## 项目结构

```text
.
├── app.py                 # Streamlit Web 界面
├── translate_pdf.py       # PDF 提取、翻译、进度、导出核心逻辑
├── glossary.tsv           # 默认术语表
├── convert_glossary.py    # 术语表转换脚本
├── test_setup.py          # 环境检测脚本
├── config.example.json    # 配置模板
├── GUIDE.md              # 更详细的使用说明
└── README.md             # 当前文档
```

## 开发检查

修改 Python 文件后可以运行：

```powershell
python -m py_compile translate_pdf.py app.py
```

## 使用提醒

本工具仅供个人学习、研究和私下校对使用。请尊重原作版权，不要公开分发或商业使用未经授权的译文。
