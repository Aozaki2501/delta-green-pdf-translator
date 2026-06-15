# 使用指南

这份文档只保留最短入口，避免和根目录 `README.md` 维护两套说明。

## 最快开始

1. 安装 Python 3.10 或更高版本。
2. 在项目根目录双击 `start_web.bat`。
3. 首次启动会自动创建 `.venv`、安装依赖，然后打开：

```text
http://localhost:8501
```

4. 在网页里上传 PDF、Markdown 或 Word，填入 API Key，选择输出格式后执行。

## 命令行入口

```powershell
python translate_pdf.py "book.pdf" --api-key sk-xxx --format all
python translate_md.py input.md --api-key sk-xxx
python translate_docx.py input.docx --api-key sk-xxx
python rerender_output.py --progress output\book_cn\book_cn.progress.json --pdf "book.pdf" --format html
```

## 需要注意

- 不要直接运行 `python app.py`。
- Web 界面要用 `python -m streamlit run app.py`，或者直接双击 `start_web.bat`。
- Web 端第一次导出 `_typeset.pdf` 时，会提示加载浏览器内核插件并显示进度。
- 如果你想手动安装，也可以运行：

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

- 更完整的参数说明、输出说明、术语表格式和排错方式，统一看根目录 `README.md`。
