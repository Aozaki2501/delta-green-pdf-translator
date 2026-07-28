# Delta Green PDF Translator

一个本地运行的 TRPG 英文文档中文翻译工具。

它适合翻译 Delta Green、规则书、模组、设定集这类资料：术语多、双栏多、页数长，普通网页翻译很难稳定处理。本工具会读取 PDF、Markdown 或 Word，调用 DeepSeek 或其他 OpenAI 兼容接口翻译，再输出 HTML、Word、Markdown，并生成一组校对报告，方便后续修正。

注意：扫描版、纯图片 PDF 需要先做 OCR。本项目不负责 OCR。

## 最快开始

适合 Windows 用户。

1. 安装 Python 3.10 或更高版本。
2. 下载或解压本项目。
3. 双击：

```text
start_web.bat
```

第一次启动会自动创建 `.venv`、安装依赖，然后打开：

```text
http://localhost:8501
```

如果网页没有自动打开，就把上面的地址复制到浏览器里。

不要直接运行 `python app.py`。手动启动 Web 时请用：

```powershell
python -m streamlit run app.py
```

## 它能做什么

| 需求 | 推荐入口 | 输出 |
| --- | --- | --- |
| 翻译 PDF 模组或规则书 | Web 界面 | HTML / Word / Markdown |
| 翻译 Markdown | Web 上传 `.md` 或 `translate_md.py` | Markdown |
| 翻译 Word | Web 上传 `.docx` 或 `translate_docx.py` | Word |
| 中途失败后继续跑 | Web 或命令行 | 复用 `.progress.json` |
| 只重翻问题页 | Web 质量检查页或 `--retranslate-pages` | 只更新指定页 |
| 只重试失败页 | Web 高级任务控制或 `--retry-failed` | 只处理失败页 |
| 不重新花钱，只重新导出 | 档案库“重试导出”或 `rerender_output.py` | HTML / Word / Markdown |
| 保留原 PDF 美术与版面 | 图文重绘 | `_typeset.html` / `_reading.html` / `_typeset.pdf` |

默认最推荐输出 HTML 和 Word。HTML 适合阅读，Word 适合人工校对。

## 近期功能变化

- 翻译接口返回被截断内容、`[...]` 等省略占位符时，任务会直接报错，不再把不完整译文写入成品或缓存。
- 新增 API 地址校验：只接受 HTTP(S)，远程接口必须使用 HTTPS；默认 DeepSeek 模型更新为 `deepseek-v4-pro`。
- 术语表现在区分大小写；同一英文词条对应多个中文译名时会指出冲突行，不再悄悄任选一个。
- 断点文件改为按文档独立保存；损坏的断点文件会备份为 `.corrupt.bak` 并提示，而不是静默丢弃。
- 新增任务存储清理、上传文件摘要缓存，以及 DeepSeek / Gemini 的模型下拉选择；内置模型会按官方美元单价自动估算费用。
- 高保真排版已修复“逐行翻译”、跨栏句子断裂、过紧行高、标题字体不一致和未翻译的大写正文标签；旧产物不会自动变更，需重新运行任务才会应用新规则。
- 新增翻译前术语确认：上传 PDF、Markdown 或 Word 后，可以逐条新增、修改或忽略候选术语，本次选择不会改动仓库里的原术语表。
- 新增办公模式：侧栏开启后切换为中性浅色界面，并自动关闭主要动画。
- 新增可选的翻译后校对区：集中查看规则符号疑点、失败页和风险页，可选择问题页重翻或标记忽略。
- 新增高保真 HTML 和图文阅读 HTML，两种输出共用同一份稳定译文，不会重复翻译。
- 上传文件名过长时会自动截短可读部分并保留哈希，避免 Windows 路径过长导致术语扫描失败。
- 普通翻译不再生成时间线、备团清单和模组结构文件；这些中间能力尚未作为正式功能开放。

## Web 使用流程

1. 启动 `start_web.bat`。
2. 上传 PDF、Markdown 或 Word。
3. 填入 API Key。
4. 可选：在侧栏开启“办公界面”。
5. 选择模型、页码范围和输出格式。
6. 可选：上传术语表。
7. 如果页面显示“翻译前术语确认”，逐条选择新增、修改或忽略。
8. 如需集中检查问题页，开启“显示翻译后校对区”。
9. 点击“开始翻译任务”。
10. 完成后下载成品和报告。

PDF 页码在 Web 里从 1 开始，和阅读器看到的页码更接近。

“重翻页码”支持这种写法：

```text
8, 12-15
```

表示重翻第 8、12、13、14、15 页。

## 输出文件

默认输出在 `output/`。每个任务会按文件名创建独立目录。

常见成品：

| 文件 | 用途 |
| --- | --- |
| `.html` | 浏览器阅读版，带屏幕版、打印版、手机版切换 |
| `.docx` | Word 校对版 |
| `.md` | Markdown 译文 |
| `_typeset.html` | 高保真固定页 HTML，保留原页美术、坐标和打印尺寸 |
| `_reading.html` | 图文阅读 HTML，原页美术与响应式译文逐页对应 |
| `_typeset.pdf` | 纯重绘 PDF，成本更高，适合复杂版面实验 |

常见报告：

| 文件 | 用途 |
| --- | --- |
| `.progress.json` | 断点续跑和离线重排用的进度文件 |
| `_quality_report.md` | 质量检查：失败页、缺译文、疑似未翻、疑似截断等 |
| `_risk_workbench.md` | 风险页工作台：集中列出需要处理的问题页 |
| `_rule_symbols.md` | 规则符号检查：骰子、SAN、HP、属性缩写等 |
| `_glossary_report.md` | 术语命中报告 |
| `_glossary_candidates.md` | 疑似新术语候选 |
| `_word_review.md` / `_word_review.docx` | Word 校对包 |
| `_run_report.md` | 本次运行效果报告 |
| `_manifest.json` | 本次任务清单 |
| `_typeset_report.json` | 高保真排版报告：页数、翻译区域、导出状态和错误信息 |

`_risk_workbench.md`、`_rule_symbols.md` 和 Word 校对包只会在开启“显示翻译后校对区”时生成。普通使用时先看 HTML 或 Word；如果觉得有问题，再开启校对区重跑或查看 `_quality_report.md`。

## 术语表

术语表是 TSV 文件，也就是两列中间用 Tab 分隔。

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

Web 上传文件后，会在翻译前显示疑似术语候选。你可以选择：

- 新增：本次翻译使用这个新术语。
- 修改：把已有术语改成本次想要的译法。
- 忽略：不加入本次术语表。

这些选择只会生成本次任务的临时术语表，不会直接改仓库里的 `glossary.tsv`。

如果 PDF 文字层有 OCR 损坏，可以勾选“模糊术语匹配”。它会识别常见混淆字符，例如 `0/O`、`1/l/I`、`5/S`、`8/B`。

## 命令行常用入口

复制配置文件：

```powershell
copy config.example.json config.json
```

编辑 `config.json` 后运行：

```powershell
python translate_pdf.py --config config.json
```

直接翻译 PDF：

```powershell
python translate_pdf.py "book.pdf" --api-key sk-xxx --format all
```

只翻译前 10 页。命令行页码从 0 开始，`--end` 不包含这一页：

```powershell
python translate_pdf.py "book.pdf" --api-key sk-xxx --start 0 --end 10
```

只重翻指定页：

```powershell
python translate_pdf.py "book.pdf" --api-key sk-xxx --retranslate-pages "8,12-15"
```

只重试失败页：

```powershell
python translate_pdf.py "book.pdf" --api-key sk-xxx --retry-failed
```

翻译 Markdown 或 Word：

```powershell
python translate_md.py input.md --api-key sk-xxx --glossary glossary.tsv
python translate_docx.py input.docx --api-key sk-xxx --glossary glossary.tsv
```

离线重新生成输出，不重新调用翻译 API：

```powershell
python rerender_output.py --progress output\book_cn\book_cn.progress.json --pdf "book.pdf" --format html
```

## 图文重绘

普通 HTML / Word 主要追求可读和方便校对，不追求完全复刻原 PDF。

如果你想保留原书美术和版面，可以选择三种同源输出：

- “高保真 HTML”按原页尺寸和坐标覆盖中文，输出 `_typeset.html`。
- “图文阅读 HTML”逐页保留原始视觉，并把同一份译文排成桌面双栏、手机单栏，输出 `_reading.html`。
- “纯重绘 PDF”从高保真 HTML 打印，输出 `_typeset.pdf`。

解析阶段会生成移除原文文字的页面 SVG，保留图片、矢量、裁剪和遮罩；两套 HTML 使用同一份稳定 block ID 译文，不会重复翻译。

这个功能更挑 PDF 结构，也更慢。首次使用时，如果本机还没有浏览器内核，Web 会提示加载并显示进度。

高保真输出依赖原 PDF 的文字层。原文已经烧进图片、扫描页或版式错误时，不能保证直接得到可交付的重绘 PDF；请先查看 `_typeset_report.json`。

复杂页面可以配合 `layout_hints.json` 修正阅读顺序和块类型。这个文件只负责告诉程序“哪些块是什么、阅读顺序如何、哪些块跳过”，不负责生成坐标和译文。

## 常见问题

### Web 页面打不开

确认终端里有没有显示：

```text
http://localhost:8501
```

如果没有，手动运行：

```powershell
python -m streamlit run app.py
```

### PowerShell 不能激活虚拟环境

在当前窗口临时放开执行策略：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### PDF 提取不到文字

大概率是扫描版 PDF。先用 OCR 工具生成带文本层的 PDF，再交给本项目。

### 翻译中断

直接用同样设置重新运行。程序会读取 `.progress.json`，跳过已完成页。

如果提示断点文件损坏，程序会保留一份 `.corrupt.bak` 备份并从新的断点继续；不要手动覆盖该备份。

### 输出没有中文

程序会拦住这种结果，避免生成全英文成品。请检查 API Key、Base URL、模型名、页码范围，以及 PDF 是否能提取文字。

### 导出失败

如果翻译已经完成，但 HTML 或 Word 导出失败，不要重新翻译。打开 Web 的“档案库”，点击“重试导出”。它会复用 `.progress.json`，不会再次调用翻译 API。

### 术语没有生效

确认术语表是两列 TSV，中间必须是 Tab：

```text
中文译名	英文原名
```

还要确认英文原名确实出现在原文页里。

## 打包分享

如果要把可运行项目发给别人，可以在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\pack_release.ps1
```

它会在 `dist/` 生成 zip 包。

对方只需要：

1. 安装 Python 3.10 或更高版本。
2. 解压 zip。
3. 双击 `start_web.bat`。
4. 在网页里填自己的 API Key。

不要把自己的 `config.json`、`.env`、输出译文或 API Key 一起发出去。

## 开发者检查

项目风险、TRPG 优化方向和前端重构记录见 [`docs/PROJECT_REVIEW.md`](docs/PROJECT_REVIEW.md)。

运行全部测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

语法检查：

```powershell
.\.venv\Scripts\python.exe -m py_compile app.py translate_pdf.py rerender_output.py
```

环境检查：

```powershell
.\.venv\Scripts\python.exe test_setup.py
```

## 使用提醒

本工具只适合个人学习、研究和私下校对。请尊重原书版权，不要公开分发或商业使用未经授权的译文。
