# Delta Green PDF Translator

这是一个面向 Delta Green / TRPG 英文 PDF 的中文翻译工具。

它会从带文本层的 PDF 中提取正文，调用 DeepSeek 或其他 OpenAI 兼容接口翻译，并生成 Markdown、HTML、Word 文档。它适合规则书、模组、设定集这类双栏排版的英文 TRPG PDF。

注意：扫描版纯图片 PDF 需要先做 OCR。本项目不负责 OCR。

## 主要功能

- Web 界面：上传 PDF、填写 API Key、选择模型和输出格式后直接翻译。
- 命令行：适合长文档、批量处理和自动化。
- 双栏 PDF 提取：尽量按正常阅读顺序合并双栏正文。
- 标题识别：自动识别章节标题，并在 Markdown 中生成目录。
- 卡片和属性块：保留 `[CARD]`、`[STAT_BLOCK]` 等结构标记，避免内容被揉成一段。
- 表格保留：尽量把表格保留为 Markdown 表格。
- 图片回填：提取正文图片到 `assets` 目录，并在 HTML、Word、Markdown 中放回。
- 术语表：用 `glossary.tsv` 统一专名译法，只把当前页命中的术语发给模型。
- 断点续跑：翻译进度保存到 `.progress.json`，中断后可继续。
- 失败页重试：失败页会单独记录，可只重试失败页。
- 诊断报告：每次输出提取诊断报告，提示空页、图片、表格、乱码等风险。
- 离线重排：已有 `.progress.json` 时，可不调用 API，重新生成 HTML、Word、Markdown。
- Token 统计：记录调用次数、token 用量和估算费用。

## 目录说明

```text
DGtranslate/
├─ app.py                         Web 界面入口
├─ translate_pdf.py               命令行入口
├─ rerender_output.py             离线重新生成输出文件
├─ glossary.tsv                   默认术语表
├─ config.example.json            命令行配置模板
├─ start_web.bat                  Windows 一键启动
├─ start_web.ps1                  PowerShell 启动脚本
├─ core/                          PDF 提取、翻译、进度、术语表等核心逻辑
├─ exporters/                     Markdown、HTML、Word 输出逻辑
├─ tests/                         自动测试
├─ uploads/                       Web 上传临时目录
└─ output/                        默认输出目录
```

## 环境要求

- Python 3.9 或更高版本
- DeepSeek API Key，或其他 OpenAI 兼容接口的 API Key
- 带文本层的英文 PDF

依赖见 `requirements.txt`：

```text
pymupdf
openai
python-docx
streamlit
```

## 快速开始

### 方法一：一键启动 Web

在 Windows 上双击：

```text
start_web.bat
```

脚本会自动创建虚拟环境、安装依赖，并启动 Web 界面。

启动后浏览器打开：

```text
http://localhost:8501
```

### 方法二：手动启动 Web

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m streamlit run app.py
```

### 方法三：命令行翻译

先复制配置文件：

```powershell
copy config.example.json config.json
```

编辑 `config.json`，填入 PDF 路径和 API Key，然后运行：

```powershell
python translate_pdf.py --config config.json
```

也可以直接传参数：

```powershell
python translate_pdf.py "book.pdf" --api-key sk-xxx --glossary glossary.tsv --format all --workers 32
```

### 开发中：原版坐标 PDF

这条链路用于开发“接近原版 PDF”的输出。它不会替代现有阅读版 HTML/Word。
Web 界面里也可以在“输出格式”中单独选择“原版坐标 PDF”运行。

注意：

- 这个模式必须单独运行，不要和纯文本稿、网页排版、文档排版一起勾选。
- 图片目前只保留原位置占位，不嵌回原图像素，方便后续手动处理。
- 翻译会按同页文本块合并成“翻译组”，减少 API 调用，并保持同页上下文连贯。
- 如果模型没有按块标记返回译文，任务会直接记录失败块，不会猜测拆分。

先提取坐标级版面：

```powershell
python extract_layout.py "book.pdf" -o "output/book.layout.json"
```

再渲染为按原页坐标摆放的 HTML：

```powershell
python render_layout_html.py "output/book.layout.json" -o "output/book.replica.html" --show-boxes
```

导出待翻译文本模板：

```powershell
python export_layout_text.py "output/book.layout.json" -o "output/book.translations.json"
```

也可以直接调用翻译接口生成译文模板：

```powershell
python translate_layout_text.py "output/book.layout.json" -o "output/book.translations.json" --api-key "sk-xxx" --glossary glossary.tsv
```

把译文回填到 layout，并生成溢出报告：

```powershell
python apply_layout_translations.py "output/book.layout.json" "output/book.translations.json" -o "output/book.translated.layout.json" --overflow-report "output/book.overflow.md"
python render_layout_html.py "output/book.translated.layout.json" -o "output/book.translated.replica.html" --show-boxes
```

最后导出 PDF：

```powershell
python export_replica_pdf.py "output/book.translated.layout.json" -o "output/book.replica.pdf"
```

当前阶段支持坐标提取、自动翻译、译文回填、HTML 检查、溢出报告和 PDF 导出。

## Web 使用流程

1. 启动 Web 页面。
2. 上传 PDF。
3. 填入 API Key。
4. 选择服务、接口地址、模型、并发数和输出格式。
5. 可选：上传自己的术语表，或指定页码范围。
6. 先用提取预览检查 PDF 是否被正确读取。
7. 点击开始翻译。
8. 完成后在页面下载输出文件。

Web 界面支持选择性重翻。页码可以写成：

```text
8, 12-15
```

## 命令行参数

常用参数：

| 参数 | 说明 |
| --- | --- |
| `pdf` | 输入 PDF 路径 |
| `--config` | JSON 配置文件 |
| `--api-key` | API Key |
| `--output` | 输出路径，不需要写扩展名 |
| `--glossary` | 术语表路径 |
| `--provider` | 服务名，只用于记录进度指纹 |
| `--base-url` | OpenAI 兼容接口地址 |
| `--model` | 模型名，默认 `deepseek-v4-pro` |
| `--format` | 输出格式：`markdown`、`html`、`word`、`both`、`all` |
| `--workers` | 并发数，范围 1 到 64，默认 32 |
| `--start` | 起始页，从 0 开始 |
| `--end` | 结束页，不包含这一页 |
| `--retry-failed` | 只重试进度文件里记录的失败页 |

配置文件示例：

```json
{
  "pdf": "THE MILLENNIUM.pdf",
  "api_key": "sk-在这里填入你的DeepSeek API Key",
  "glossary": "glossary.tsv",
  "provider": "deepseek",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-v4-pro",
  "format": "all",
  "workers": 32,
  "start": 0,
  "end": null
}
```

命令行参数会覆盖配置文件中的同名字段。

## 输出文件

默认输出在 `output` 目录下。每个任务会按文件名创建独立目录，避免多个任务互相混在一起。

常见输出：

```text
output/book_cn/book_cn.md
output/book_cn/book_cn.html
output/book_cn/book_cn.docx
output/book_cn/book_cn.progress.json
output/book_cn/book_cn_extraction_report.md
output/book_cn/book_cn_glossary_report.md
output/book_cn/assets/
```

说明：

- `.md` 是 Markdown 译文。
- `.html` 是浏览器阅读版。
- `.docx` 是 Word 文档。
- `.progress.json` 是断点续跑文件。
- `_extraction_report.md` 是 PDF 提取诊断报告。
- `_glossary_report.md` 是术语命中报告。
- `assets/` 保存从 PDF 裁出的正文图片。

## 术语表

术语表使用 TSV 格式，也就是用 Tab 分隔两列。

格式：

```text
中文译名	英文原名
```

示例：

```text
绿色三角洲	Delta Green
旧日支配者	Great Old One
阿撒托斯	Azathoth
```

程序会在每页英文原文中查找术语。只有当前页命中的术语会加入翻译请求，减少 token 占用。

如果有从 PDF 复制出来的原始术语文本，可以用转换脚本：

```powershell
python convert_glossary.py raw_glossary.txt -o glossary.tsv
```

## 断点续跑和失败页

翻译进度保存在：

```text
输出文件名.progress.json
```

同一个 PDF、同一个术语表、同一个模型和同一段页码再次运行时，程序会跳过已经完成的页。

如果某些页调用 API 失败，会写入 `failed_pages`，不会当作正常译文混进最终结果。

只重试失败页：

```powershell
python translate_pdf.py "book.pdf" --api-key sk-xxx --retry-failed
```

## 离线重新生成输出

如果翻译已经完成，只想用现有进度文件重新生成 Word、HTML 或 Markdown，可以运行：

```powershell
python rerender_output.py --progress output\book_cn\book_cn.progress.json --pdf "book.pdf" --format all
```

这个命令不会调用翻译 API。

注意：离线重排只能重新套用输出样式，不能修正旧译文本身的顺序错误。

## 环境检查

检查依赖：

```powershell
python test_setup.py
```

检查 PDF 提取：

```powershell
python test_setup.py --pdf "book.pdf"
```

检查 API 连通：

```powershell
python test_setup.py --api-key sk-xxx
```

## 测试

运行全部测试：

```powershell
python -m pytest
```

当前测试覆盖导入兼容、页码解析、术语匹配、进度文件、输出清理、标题样式、离线重排等核心逻辑。

## 常见问题

### Web 怎么启动？

使用：

```powershell
python -m streamlit run app.py
```

不要直接运行 `python app.py`。

### PDF 没有文字怎么办？

先用 OCR 工具把 PDF 转成带文本层的文件，再交给本项目处理。

### 翻译中断怎么办？

直接重新运行同一个任务。程序会读取 `.progress.json` 并跳过已完成页。

### 想只翻译几页怎么办？

命令行使用 `--start` 和 `--end`。注意页码从 0 开始。

示例：只翻译第 1 到第 5 页：

```powershell
python translate_pdf.py "book.pdf" --api-key sk-xxx --start 0 --end 5
```

### PowerShell 不能激活虚拟环境怎么办？

当前窗口临时放开执行策略：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 使用提醒

本工具只适合个人学习、研究和私下校对。请尊重原书版权，不要公开分发或商业使用未经授权的译文。
