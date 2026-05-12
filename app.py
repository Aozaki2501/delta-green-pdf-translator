#!/usr/bin/env python3
"""
Delta Green PDF Translator — Web UI
=====================================
Gradio-based web interface with Delta Green themed styling.
Dark background, green accents, military/conspiracy aesthetic.

Usage:
    python app.py
    Then open http://localhost:7860 in your browser.
"""

import gradio as gr
import os
import re
import sys
import json
import time
import threading
from pathlib import Path

# Import translator components
from translate_pdf import (
    PDFExtractor, Translator, ProgressTracker, TokenStats,
    PDFOverlayWriter, load_glossary, translate_batch_concurrent
)

try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False


# ============================================================
# DELTA GREEN THEME — CSS
# ============================================================

DG_CSS = """
/* === DELTA GREEN THEMED UI === */

/* Root variables */
:root {
    --dg-black: #0a0a0a;
    --dg-dark: #111411;
    --dg-panel: #1a1f1a;
    --dg-border: #2a3a2a;
    --dg-green: #00cc44;
    --dg-green-dim: #1a5c2a;
    --dg-green-glow: #00ff55;
    --dg-amber: #cc8800;
    --dg-red: #cc2222;
    --dg-text: #c8d0c8;
    --dg-text-dim: #667766;
    --dg-text-bright: #e0ffe0;
}

/* Global dark background */
.gradio-container {
    background: var(--dg-dark) !important;
    font-family: 'Courier New', 'Consolas', monospace !important;
    max-width: 1000px !important;
}

/* Main body */
.main, .contain {
    background: var(--dg-dark) !important;
}

/* Header banner */
#header-banner {
    background: linear-gradient(135deg, #0a0f0a 0%, #1a2a1a 50%, #0a0f0a 100%) !important;
    border: 1px solid var(--dg-green-dim) !important;
    border-radius: 4px !important;
    padding: 20px !important;
    margin-bottom: 16px !important;
    text-align: center !important;
    position: relative !important;
    overflow: hidden !important;
}

#header-banner::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--dg-green), transparent);
}

#header-banner::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--dg-green-dim), transparent);
}

/* Title text */
#title-text {
    color: var(--dg-green) !important;
    font-size: 1.8em !important;
    font-weight: bold !important;
    letter-spacing: 3px !important;
    text-transform: uppercase !important;
    text-shadow: 0 0 10px rgba(0, 204, 68, 0.3) !important;
    margin-bottom: 4px !important;
}

#subtitle-text {
    color: var(--dg-text-dim) !important;
    font-size: 0.85em !important;
    letter-spacing: 1px !important;
}

/* Panel styling */
.panel, .block, .form {
    background: var(--dg-panel) !important;
    border: 1px solid var(--dg-border) !important;
    border-radius: 4px !important;
}

/* Labels */
label, .label-wrap span {
    color: var(--dg-green) !important;
    font-weight: bold !important;
    text-transform: uppercase !important;
    font-size: 0.75em !important;
    letter-spacing: 1px !important;
}

/* Input fields */
input, textarea, select, .wrap {
    background: var(--dg-black) !important;
    border: 1px solid var(--dg-border) !important;
    color: var(--dg-text) !important;
    border-radius: 2px !important;
}

input:focus, textarea:focus {
    border-color: var(--dg-green) !important;
    box-shadow: 0 0 5px rgba(0, 204, 68, 0.2) !important;
}

/* Buttons */
.primary, button.primary {
    background: linear-gradient(180deg, #1a5c2a 0%, #0a3a1a 100%) !important;
    border: 1px solid var(--dg-green) !important;
    color: var(--dg-green-glow) !important;
    font-weight: bold !important;
    text-transform: uppercase !important;
    letter-spacing: 2px !important;
    border-radius: 2px !important;
    text-shadow: 0 0 5px rgba(0, 255, 85, 0.3) !important;
}

.primary:hover, button.primary:hover {
    background: linear-gradient(180deg, #2a7c3a 0%, #1a5c2a 100%) !important;
    box-shadow: 0 0 15px rgba(0, 204, 68, 0.3) !important;
}

.secondary, button.secondary {
    background: var(--dg-panel) !important;
    border: 1px solid var(--dg-border) !important;
    color: var(--dg-text-dim) !important;
}

/* Tabs */
.tab-nav button {
    background: var(--dg-panel) !important;
    border: 1px solid var(--dg-border) !important;
    color: var(--dg-text-dim) !important;
    border-radius: 2px 2px 0 0 !important;
}

.tab-nav button.selected {
    background: var(--dg-dark) !important;
    border-bottom: 2px solid var(--dg-green) !important;
    color: var(--dg-green) !important;
}

/* Checkbox */
input[type="checkbox"] {
    accent-color: var(--dg-green) !important;
}

/* Slider */
input[type="range"] {
    accent-color: var(--dg-green) !important;
}

/* File upload area */
.upload-button, .file-preview {
    background: var(--dg-black) !important;
    border: 1px dashed var(--dg-border) !important;
    color: var(--dg-text-dim) !important;
}

/* Log / output textbox */
#log-output textarea {
    background: var(--dg-black) !important;
    color: var(--dg-green) !important;
    font-family: 'Courier New', monospace !important;
    font-size: 0.8em !important;
    border: 1px solid var(--dg-green-dim) !important;
}

/* Progress section */
#progress-display {
    background: var(--dg-black) !important;
    border: 1px solid var(--dg-green-dim) !important;
    padding: 10px !important;
    border-radius: 2px !important;
    color: var(--dg-green) !important;
    font-family: 'Courier New', monospace !important;
}

/* Stats panel */
#stats-display {
    background: var(--dg-black) !important;
    border: 1px solid var(--dg-border) !important;
    padding: 12px !important;
    border-radius: 2px !important;
    color: var(--dg-amber) !important;
    font-family: 'Courier New', monospace !important;
}

/* Classification markers */
.classified-banner {
    text-align: center;
    color: var(--dg-red);
    font-size: 0.7em;
    letter-spacing: 3px;
    text-transform: uppercase;
    padding: 4px;
    border-top: 1px solid var(--dg-red);
    border-bottom: 1px solid var(--dg-red);
    margin: 8px 0;
    opacity: 0.7;
}

/* Accordion */
.accordion {
    border: 1px solid var(--dg-border) !important;
    background: var(--dg-panel) !important;
}

/* Markdown output */
.prose {
    color: var(--dg-text) !important;
}

/* Footer */
#footer-text {
    color: var(--dg-text-dim) !important;
    font-size: 0.7em !important;
    text-align: center !important;
    letter-spacing: 1px !important;
    margin-top: 16px !important;
}
"""


# ============================================================
# TRANSLATION LOGIC (GUI wrapper)
# ============================================================

class TranslationJob:
    """Manages a translation job with progress callbacks."""

    def __init__(self):
        self.is_running = False
        self.should_stop = False
        self.progress_log = []
        self.stats = None
        self.output_files = []

    def log(self, msg):
        self.progress_log.append(msg)

    def get_log_text(self):
        return "\n".join(self.progress_log[-50:])  # Last 50 lines


job = TranslationJob()


def run_translation(
    pdf_file, glossary_file, api_key, model, output_format,
    workers, start_page, end_page_str,
    progress=gr.Progress(track_tqdm=True)
):
    """Main translation function called by Gradio."""

    global job
    job = TranslationJob()
    job.is_running = True
    job.progress_log = []
    job.output_files = []

    # Validate inputs
    if not pdf_file:
        return "❌ 请上传 PDF 文件", "", [], ""
    if not api_key or not api_key.strip():
        return "❌ 请输入 API Key", "", [], ""

    pdf_path = pdf_file.name if hasattr(pdf_file, 'name') else pdf_file
    glossary_path = None
    if glossary_file:
        glossary_path = glossary_file.name if hasattr(glossary_file, 'name') else glossary_file

    # Parse end page
    end_page = None
    if end_page_str and end_page_str.strip():
        try:
            end_page = int(end_page_str)
        except ValueError:
            end_page = None

    start = int(start_page) if start_page else 0

    # Output base name
    pdf_stem = Path(pdf_path).stem
    output_dir = os.path.dirname(pdf_path) or "."
    output_base = os.path.join(output_dir, f"{pdf_stem}_cn")

    job.log("=" * 50)
    job.log("  ▲ DELTA GREEN PDF TRANSLATOR")
    job.log("  ▲ CLASSIFIED — EYES ONLY")
    job.log("=" * 50)
    job.log("")

    # Initialize
    stats = TokenStats()
    job.stats = stats

    job.log(f"[INIT] 打开 PDF: {os.path.basename(pdf_path)}")
    try:
        extractor = PDFExtractor(pdf_path)
    except Exception as e:
        job.is_running = False
        return f"❌ 无法打开 PDF: {e}", job.get_log_text(), [], ""

    total = extractor.total_pages
    if end_page is None or end_page > total:
        end_page = total

    job.log(f"[INIT] 总页数: {total}")
    job.log(f"[INIT] 翻译范围: 第 {start + 1} 页 → 第 {end_page} 页")
    job.log(f"[INIT] 并发数: {workers}")
    job.log("")

    # Glossary
    glossary = {}
    if glossary_path:
        glossary = load_glossary(glossary_path)
        job.log(f"[INIT] 术语表: 已加载 {len(glossary)} 条")

    # Translator
    job.log(f"[INIT] 模型: {model}")
    translator = Translator(api_key=api_key.strip(), model=model, stats=stats)
    translator.set_glossary(glossary)

    # Progress tracker
    progress_file = output_base + ".progress.json"
    tracker = ProgressTracker(progress_file)

    # Extract pages
    job.log("")
    job.log("[EXTRACT] 提取文本...")
    pages_text = {}
    for page_num in range(start, end_page):
        text = extractor.extract_page(page_num)
        pages_text[page_num] = text

    extractor.finalize_chapters()
    toc = extractor.chapter_detector.get_toc_markdown()
    if toc:
        job.log(f"[EXTRACT] 检测到 {len(extractor.chapter_detector.headings)} 个章节标题")

    # Translate
    job.log("")
    job.log("[TRANSLATE] 开始翻译...")
    job.log("-" * 40)

    start_time = time.time()
    translated_pages = []
    prev_translation_tail = ""
    pages_to_process = list(range(start, end_page))
    total_to_do = len(pages_to_process)

    if workers > 1:
        # Concurrent mode
        pages_data = []
        prev_text = ""
        for page_num in range(start, end_page):
            text = pages_text.get(page_num, "")
            context = prev_text[-300:] if prev_text else ""
            pages_data.append((page_num, text, context))
            if text.strip():
                prev_text = text

        results = translate_batch_concurrent(pages_data, translator, tracker, workers)
        translated_pages = [(pn, t) for pn, t in results.items() if t.strip()]
        job.log(f"[TRANSLATE] 并发翻译完成")

    else:
        # Sequential mode
        for idx, page_num in enumerate(pages_to_process):
            if job.should_stop:
                job.log("[STOP] 用户中止翻译")
                break

            pct = (idx + 1) / total_to_do * 100
            progress(pct / 100, desc=f"翻译中 {idx+1}/{total_to_do}")

            if tracker.is_completed(page_num):
                translation = tracker.get_translation(page_num)
                if translation:
                    translated_pages.append((page_num, translation))
                    prev_translation_tail = translation[-300:]
                continue

            text = pages_text.get(page_num, "")
            if not text.strip():
                tracker.mark_completed(page_num, "")
                continue

            translation = translator.translate_chunk(text, page_num, prev_context=prev_translation_tail)

            if translation:
                translated_pages.append((page_num, translation))
                tracker.mark_completed(page_num, translation)
                prev_translation_tail = translation[-300:]
                job.log(f"  ✓ 第 {page_num + 1} 页 [{pct:.0f}%] (¥{stats.cost_yuan:.3f})")
            else:
                tracker.mark_completed(page_num, "")
                job.log(f"  ⚠ 第 {page_num + 1} 页 — 空结果")

            time.sleep(0.2)

    elapsed = time.time() - start_time
    translated_pages_sorted = sorted(translated_pages, key=lambda x: x[0])
    page_count = len([t for _, t in translated_pages_sorted if t.strip()])

    job.log("-" * 40)
    job.log(f"[DONE] 翻译完成: {page_count} 页")
    job.log(f"[DONE] 耗时: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    job.log(f"[DONE] {stats.summary()}")
    job.log("")

    # === OUTPUT GENERATION ===
    output_files = []
    formats = output_format if isinstance(output_format, list) else [output_format]

    # Markdown
    if "Markdown" in formats or "全部" in formats:
        md_path = output_base + ".md"
        job.log(f"[OUTPUT] 生成 Markdown: {os.path.basename(md_path)}")
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("# THE MILLENNIUM — 中文翻译\n\n")
                f.write("> 由 DeepSeek V4 AI 翻译，术语参照绿色三角洲官方译名表\n\n---\n\n")
                if toc:
                    f.write(toc + "\n---\n\n")
                for page_num, translation in translated_pages_sorted:
                    if translation.strip():
                        f.write(f'<a id="page-{page_num + 1}"></a>\n\n')
                        f.write(f"<!-- Page {page_num + 1} -->\n\n")
                        f.write(translation)
                        f.write("\n\n---\n\n")
            output_files.append(md_path)
            job.log("  ✓ Markdown 完成")
        except Exception as e:
            job.log(f"  ✗ Markdown 失败: {e}")

    # PDF
    if "PDF" in formats or "全部" in formats:
        pdf_out_path = output_base + ".pdf"
        job.log(f"[OUTPUT] 生成 PDF: {os.path.basename(pdf_out_path)}")
        try:
            writer = PDFOverlayWriter(pdf_path, pdf_out_path)
            for page_num, translation in translated_pages_sorted:
                writer.overlay_page(page_num, translation)
            writer.save()
            output_files.append(pdf_out_path)
            job.log("  ✓ PDF 完成")
        except Exception as e:
            job.log(f"  ✗ PDF 失败: {e}")

    # Word
    if "Word" in formats or "全部" in formats:
        if not HAS_DOCX:
            job.log("  ⚠ Word 输出需要 python-docx: pip install python-docx")
        else:
            docx_path = output_base + ".docx"
            job.log(f"[OUTPUT] 生成 Word: {os.path.basename(docx_path)}")
            try:
                doc = DocxDocument()
                doc.add_heading("THE MILLENNIUM — 中文翻译", level=0)
                doc.add_paragraph("由 DeepSeek V4 AI 翻译，术语参照绿色三角洲官方译名表")
                doc.add_page_break()
                for page_num, translation in translated_pages_sorted:
                    if not translation.strip():
                        continue
                    for line in translation.split("\n"):
                        line = line.strip()
                        if not line or line == "---" or line.startswith("<!--"):
                            continue
                        if line.startswith("### "):
                            doc.add_heading(line[4:], level=3)
                        elif line.startswith("## "):
                            doc.add_heading(line[3:], level=2)
                        elif line.startswith("# "):
                            doc.add_heading(line[2:], level=1)
                        elif line.startswith("- ") or line.startswith("• "):
                            doc.add_paragraph(line[2:], style="List Bullet")
                        else:
                            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
                            clean = re.sub(r"\*(.+?)\*", r"\1", clean)
                            doc.add_paragraph(clean)
                doc.save(docx_path)
                output_files.append(docx_path)
                job.log("  ✓ Word 完成")
            except Exception as e:
                job.log(f"  ✗ Word 失败: {e}")

    job.log("")
    job.log("=" * 50)
    job.log("  ▲ 任务完成 — OPERATION COMPLETE")
    job.log("=" * 50)

    job.is_running = False
    job.output_files = output_files

    # Build stats display
    stats_text = (
        f"📊 Token: {stats.input_tokens:,} 入 / {stats.output_tokens:,} 出\n"
        f"💰 费用: ¥{stats.cost_yuan:.3f}\n"
        f"⏱️ 耗时: {elapsed:.0f}s\n"
        f"📄 页数: {page_count}"
    )

    extractor.close()

    return "✅ 翻译完成", job.get_log_text(), output_files, stats_text


# ============================================================
# GRADIO UI
# ============================================================

def build_ui():
    """Build the Gradio interface with Delta Green theme."""

    with gr.Blocks(
        css=DG_CSS,
        title="Delta Green PDF Translator",
        theme=gr.themes.Base(
            primary_hue="green",
            secondary_hue="gray",
            neutral_hue="gray",
            font=gr.themes.GoogleFont("JetBrains Mono"),
        )
    ) as app:

        # Header
        with gr.Column(elem_id="header-banner"):
            gr.HTML("""
                <div id="title-text">▲ DELTA GREEN</div>
                <div id="subtitle-text">PDF TRANSLATION SYSTEM — CLASSIFIED</div>
            """)
            gr.HTML('<div class="classified-banner">TOP SECRET // EYES ONLY // NEED TO KNOW</div>')

        # Main content
        with gr.Tabs():

            # === TAB 1: TRANSLATION ===
            with gr.TabItem("🔺 翻译任务"):

                with gr.Row():
                    with gr.Column(scale=2):
                        pdf_input = gr.File(
                            label="📁 PDF 文件",
                            file_types=[".pdf"],
                            type="filepath"
                        )
                        glossary_input = gr.File(
                            label="📚 术语表 (可选)",
                            file_types=[".tsv", ".csv", ".txt"],
                            type="filepath"
                        )

                    with gr.Column(scale=3):
                        api_key_input = gr.Textbox(
                            label="🔑 API KEY",
                            placeholder="sk-...",
                            type="password",
                            info="DeepSeek API 密钥"
                        )
                        model_input = gr.Dropdown(
                            label="🤖 模型",
                            choices=["deepseek-v4-pro", "deepseek-v4-flash"],
                            value="deepseek-v4-pro",
                            info="Pro=高质量, Flash=快速便宜"
                        )
                        format_input = gr.CheckboxGroup(
                            label="📄 输出格式",
                            choices=["Markdown", "PDF", "Word", "全部"],
                            value=["全部"],
                            info="选择需要的输出格式"
                        )

                with gr.Row():
                    workers_input = gr.Slider(
                        label="⚡ 并发线程",
                        minimum=1, maximum=16, step=1, value=4,
                        info="推荐4，越多越快但上下文连贯性略降"
                    )
                    start_input = gr.Number(
                        label="📖 起始页",
                        value=0, precision=0,
                        info="从0开始"
                    )
                    end_input = gr.Textbox(
                        label="📖 结束页",
                        value="",
                        placeholder="留空=全部",
                        info="不含此页"
                    )

                # Action buttons
                with gr.Row():
                    translate_btn = gr.Button(
                        "🔺 开始翻译",
                        variant="primary",
                        size="lg"
                    )

                # Status
                status_output = gr.Textbox(
                    label="状态",
                    interactive=False,
                    elem_id="progress-display"
                )

                # Stats
                stats_output = gr.Textbox(
                    label="📊 统计",
                    interactive=False,
                    lines=4,
                    elem_id="stats-display"
                )

                # Output files
                file_output = gr.File(
                    label="📥 下载译文",
                    file_count="multiple",
                    interactive=False
                )

            # === TAB 2: LOG ===
            with gr.TabItem("📋 运行日志"):
                log_output = gr.Textbox(
                    label="翻译日志",
                    lines=30,
                    interactive=False,
                    elem_id="log-output"
                )

            # === TAB 3: ABOUT ===
            with gr.TabItem("ℹ️ 关于"):
                gr.HTML("""
                <div style="color: #c8d0c8; padding: 20px; font-family: 'Courier New', monospace;">
                    <h2 style="color: #00cc44;">▲ DELTA GREEN PDF TRANSLATOR v2.0</h2>
                    <br>
                    <p>专为《绿色三角洲》TRPG 扩展资料设计的 AI 翻译工具。</p>
                    <br>
                    <h3 style="color: #00cc44;">功能</h3>
                    <ul>
                        <li>智能双栏 PDF 文本提取</li>
                        <li>上下文窗口 — 跨页翻译连贯</li>
                        <li>章节自动检测与目录生成</li>
                        <li>多格式输出：Markdown / PDF / Word</li>
                        <li>TRPG 术语表支持</li>
                        <li>多线程并发翻译</li>
                        <li>断点续翻</li>
                        <li>实时费用统计</li>
                    </ul>
                    <br>
                    <h3 style="color: #00cc44;">依赖</h3>
                    <pre style="color: #cc8800;">pip install pymupdf openai python-docx gradio</pre>
                    <br>
                    <div class="classified-banner">
                        THE WORKING GROUP DOES NOT EXIST<br>
                        THIS PROGRAM DOES NOT EXIST<br>
                        YOU ARE NOT READING THIS
                    </div>
                </div>
                """)

        # Footer
        gr.HTML("""
            <div id="footer-text">
                ▲ DELTA GREEN — UNAUTHORIZED ACCESS WILL BE PROSECUTED — v2.0
            </div>
        """)

        # === EVENT HANDLERS ===
        translate_btn.click(
            fn=run_translation,
            inputs=[
                pdf_input, glossary_input, api_key_input, model_input,
                format_input, workers_input, start_input, end_input
            ],
            outputs=[status_output, log_output, file_output, stats_output]
        )

    return app


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    app = build_ui()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
        show_api=False
    )
