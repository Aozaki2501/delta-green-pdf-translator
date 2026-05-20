#!/usr/bin/env python3
"""
Delta Green PDF Translator — Web UI (Streamlit)
"""
import streamlit as st
import hashlib
import os
import re
import time
import uuid
from pathlib import Path
from translate_pdf import (
    PDFExtractor, Translator, ProgressTracker, TokenStats,
    load_glossary, translate_batch_concurrent,
    write_markdown_output, write_html_output, write_word_output, HAS_DOCX,
    build_progress_metadata, parse_page_selection, write_glossary_report,
    normalize_page_range, is_failed_translation
)


APP_DIR = Path(__file__).resolve().parent
DEFAULT_GLOSSARY_PATH = APP_DIR / "glossary.tsv"


def make_output_path(output_base, extension):
    """Return a non-overwriting output path for Web downloads."""
    path = output_base + extension
    if not os.path.exists(path):
        return path
    return f"{output_base}_{uuid.uuid4().hex[:8]}{extension}"


def format_duration(seconds):
    if seconds is None:
        return "估算中"
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def safe_filename_stem(filename: str, default: str = "document") -> str:
    stem = Path(filename or default).stem
    stem = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", stem).strip("._-")
    return stem or default


def uploaded_file_digest(uploaded_file) -> str:
    return hashlib.sha256(uploaded_file.getvalue()).hexdigest()


def save_uploaded_pdf_for_preview(uploaded_file) -> Path:
    upload_dir = APP_DIR / "uploads"
    ensure_dir(upload_dir)
    digest = uploaded_file_digest(uploaded_file)[:12]
    target = upload_dir / f"_preview_{safe_filename_stem(uploaded_file.name)}_{digest}.pdf"
    if not target.exists():
        with open(target, "wb") as f:
            f.write(uploaded_file.getvalue())
    return target


# === UI THEME ===
st.set_page_config(
    page_title="DG Translator Terminal",
    page_icon="🖧",
    layout="wide",
)

st.markdown("""
<style>
    /* 引入复古等宽字体 */
    @import url('https://fonts.googleapis.com/css2?family=Courier+Prime:ital,wght@0,400;0,700;1,400&family=VT323&display=swap');

    :root {
        --term-bg: #050505;
        --term-panel: #0a0c0a;
        --term-green: #33ff33;
        --term-dark-green: #114411;
        --term-text: #c8d6c8;
        --term-border: #1f3b22;
        --term-alert: #ff3333;
    }

    /* 强制覆盖全局背景和字体 */
    .stApp, .stAppHeader {
        background-color: var(--term-bg) !important;
        color: var(--term-text) !important;
        font-family: "Courier Prime", "Courier New", monospace !important;
    }

    /* 侧边栏样式 */
    section[data-testid="stSidebar"] {
        background-color: var(--term-panel) !important;
        border-right: 2px solid var(--term-border) !important;
    }
    
    /* 标题样式：更具复古电子感 */
    h1, h2, h3, .hero-title {
        color: var(--term-green) !important;
        font-family: "VT323", "Courier New", monospace !important;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        font-weight: normal;
    }

    p, label, .stMarkdown {
        color: var(--term-text) !important;
        font-size: 0.95rem;
    }

    /* 顶层 Hero 面板 */
    .hero {
        background-color: transparent;
        border: 1px solid var(--term-border);
        border-left: 6px solid var(--term-green);
        padding: 20px 24px;
        margin-bottom: 30px;
    }

    .hero-title {
        font-size: 2.2rem;
        margin-bottom: 8px;
    }

    .hero-subtitle {
        color: var(--term-text);
        opacity: 0.8;
    }

    /* 输入框与选择器样式 - 去除圆角，方正硬朗 */
    .stTextInput input,
    .stNumberInput input,
    .stSelectbox div[data-baseweb="select"],
    .stMultiSelect div[data-baseweb="select"] {
        background-color: var(--term-panel) !important;
        border: 1px solid var(--term-border) !important;
        border-radius: 0px !important;
        color: var(--term-green) !important;
        font-family: "Courier Prime", monospace !important;
    }

    /* 上传组件虚线框 */
    div[data-testid="stFileUploader"] {
        background-color: var(--term-panel) !important;
        border: 1px dashed var(--term-border) !important;
        border-radius: 0px !important;
        padding: 16px;
    }

    /* 主按钮样式：终端高亮效果 */
    .stButton>button {
        background-color: var(--term-bg) !important;
        color: var(--term-green) !important;
        border: 1px solid var(--term-green) !important;
        border-radius: 0px !important;
        height: 48px;
        font-weight: bold;
        letter-spacing: 0.1em;
        transition: all 0.2s ease;
        text-transform: uppercase;
    }

    .stButton>button:hover {
        background-color: var(--term-green) !important;
        color: var(--term-bg) !important;
    }

    /* 进度条变绿 */
    .stProgress > div > div > div {
        background-color: var(--term-green) !important;
    }

    /* 状态信息卡片 */
    div[data-testid="stMetric"] {
        background-color: var(--term-panel) !important;
        border: 1px solid var(--term-border) !important;
        border-radius: 0px !important;
        padding: 15px;
    }
    
    div[data-testid="stMetricValue"] {
        color: var(--term-green) !important;
    }

    /* 消除基础结构过大的留白 */
    .block-container {
        max-width: 1200px;
        padding-top: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# === HEADER ===
st.markdown("""
<div class="hero">
    <div class="hero-title">RESTRICTED // DG-TRANSLATOR-SYS</div>
    <div class="hero-subtitle">
        > INITIALIZING AUTOMATED TRANSLATION PROTOCOL...<br>
        > PURPOSE: EXTRACT, TRANSLATE AND COMPILE ENCRYPTED PDF DATA.<br>
        > STATUS: READY FOR OPERATOR INPUT.
    </div>
</div>
""", unsafe_allow_html=True)
st.markdown("""
<div class="hero">
    <div class="hero-title">Delta Green PDF Translator</div>
    <div class="hero-subtitle">
        将英文 TRPG PDF 提取、翻译并输出为 Markdown、HTML 或 Word。
        更适合先产出可校对译稿，再做人工排版。
    </div>
</div>
""", unsafe_allow_html=True)
with st.sidebar:
    st.header("翻译配置")

    api_key = st.text_input("API Key", type="password", placeholder="sk-...")
    model = st.selectbox("模型", ["deepseek-v4-pro", "deepseek-v4-flash"])
    workers = st.slider("并发线程", 1, 16, 4)

    formats = st.multiselect(
        "输出格式",
        ["Markdown", "HTML", "Word"],
        default=["HTML", "Word"],
    )

    display_start_page = st.number_input("起始页（从 1 开始）", value=1, min_value=1)
    end_page_str = st.text_input("结束页（含，从 1 开始）", value="", placeholder="留空表示全部")
    retranslate_pages_str = st.text_input("重翻页码", value="", placeholder="如：8, 12-15")
    reuse_mismatched_progress = st.checkbox(
        "允许复用设置不匹配的旧进度",
        value=False,
        help="默认不复用不同 PDF、术语表、模型或提取器版本生成的旧译文。",
    )
    show_extraction_preview = st.checkbox("显示提取预览", value=False)
    preview_page = st.number_input("预览页（从 1 开始）", value=1, min_value=1)
    open_output_when_done = st.checkbox("完成后打开 output 文件夹", value=False)

    with st.expander("Word 版式", expanded=False):
        word_body_font_size = st.slider("正文字号", 9.0, 14.0, 12.0, 0.5)
        word_line_spacing = st.slider("正文行距", 1.0, 2.0, 1.5, 0.05)
        word_columns = st.selectbox("正文分栏", [1, 2], index=1, format_func=lambda n: f"{n} 栏")
        word_min_chars = st.number_input("阅读页最少字数", value=1000, min_value=300, max_value=3000, step=100)
        word_max_chars = st.number_input("阅读页最多字数", value=1500, min_value=500, max_value=5000, step=100)
        word_hard_page_breaks = st.checkbox(
            "按阅读页强制分页",
            value=False,
            help="关闭时 Word 会自然续排，减少半页空白；开启时每个阅读页后插入分页符。",
        )
        word_header_left = st.text_input("页眉左侧", value="绿色三角洲")
        word_header_right = st.text_input("页眉右侧", value="", placeholder="留空则使用文件名")

# === MAIN ===
st.markdown('<div class="section-card">', unsafe_allow_html=True)

st.subheader("输入文件")
st.caption("上传原始 PDF。默认使用项目内 glossary.tsv；如需替换，可上传自定义 TSV / TXT / CSV。")

col1, col2 = st.columns([1.2, 1])
with col1:
    pdf_file = st.file_uploader("PDF 文件", type=["pdf"], label_visibility="collapsed")
with col2:
    glossary_file = st.file_uploader("自定义术语表，可选", type=["tsv", "txt", "csv"], label_visibility="collapsed")
    if glossary_file:
        st.caption(f"将使用上传术语表：{glossary_file.name}")
    elif DEFAULT_GLOSSARY_PATH.exists():
        st.caption("将使用默认术语表：glossary.tsv")
    else:
        st.caption("未找到默认术语表；可上传自定义术语表。")

st.markdown("</div>", unsafe_allow_html=True)

if pdf_file and show_extraction_preview:
    preview_path = save_uploaded_pdf_for_preview(pdf_file)
    preview_extractor = None
    try:
        preview_extractor = PDFExtractor(str(preview_path))
        total_preview_pages = preview_extractor.total_pages
        preview_index = min(max(int(preview_page) - 1, 0), total_preview_pages - 1)
        preview_text = preview_extractor.extract_page(preview_index)
        preview_notes = preview_extractor.get_layout_notes(preview_index)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("提取预览 / 诊断")
        st.caption(
            f"PDF 共 {total_preview_pages} 页；当前预览第 {preview_index + 1} 页。"
            "这里只展示提取和排序后的文本，不会调用翻译 API。"
        )
        if preview_notes:
            st.caption("版面识别：" + "；".join(preview_notes))
        if preview_text.strip():
            st.text_area("提取文本", preview_text, height=420)
        else:
            st.warning("这一页没有提取到正文文本。可能是图片页、扫描页，或文本被页眉页脚过滤规则排除了。")
        st.markdown("</div>", unsafe_allow_html=True)
    except Exception as e:
        st.warning(f"提取预览失败：{e}")
    finally:
        if preview_extractor:
            preview_extractor.close()

if st.button("🔺 开始翻译", type="primary", use_container_width=True):
    if not pdf_file:
        st.error("✗ 请上传 PDF 文件")
    elif not api_key:
        st.error("✗ 请输入 API Key")
    elif not formats:
        st.error("✗ 请至少选择一种输出格式")
    else:
        # Create organized directories
        upload_dir = APP_DIR / "uploads"
        output_dir = APP_DIR / "output"
        ensure_dir(upload_dir)
        ensure_dir(output_dir)

        # Save uploaded files to uploads/
        pdf_stem = safe_filename_stem(pdf_file.name)
        pdf_upload_name = f"_upload_{pdf_stem}_{uuid.uuid4().hex[:8]}.pdf"
        pdf_path = str(upload_dir / pdf_upload_name)
        with open(pdf_path, "wb") as f:
            f.write(pdf_file.getvalue())

        glossary_path = str(DEFAULT_GLOSSARY_PATH) if DEFAULT_GLOSSARY_PATH.exists() else None
        if glossary_file:
            glossary_suffix = Path(glossary_file.name).suffix.lower() or ".tsv"
            glossary_upload_name = f"_upload_{safe_filename_stem(glossary_file.name, 'glossary')}_{uuid.uuid4().hex[:8]}{glossary_suffix}"
            glossary_path = str(upload_dir / glossary_upload_name)
            with open(glossary_path, "wb") as f:
                f.write(glossary_file.getvalue())

        try:
            start_page = int(display_start_page) - 1
            display_end_page = int(end_page_str) if end_page_str.strip() else None
        except ValueError:
            st.error("结束页必须是整数，或留空表示全部。")
            st.stop()
        output_base = str(output_dir / f"{pdf_stem}_cn")

        # Init
        stats = TokenStats()
        extractor = PDFExtractor(pdf_path)
        total = extractor.total_pages
        try:
            start_page, end_page = normalize_page_range(start_page, display_end_page, total)
        except ValueError as e:
            st.error(str(e))
            extractor.close()
            st.stop()
        if "Word" in formats and word_max_chars < word_min_chars:
            st.error("Word 阅读页最多字数必须大于或等于最少字数。")
            extractor.close()
            st.stop()

        glossary = load_glossary(glossary_path) if glossary_path else {}
        if glossary_path:
            glossary_source = Path(glossary_path).name
            st.info(f"📚 术语表: {glossary_source} ({len(glossary)} 条)")
        else:
            st.warning("未使用术语表。")
        translator = Translator(api_key=api_key, model=model, stats=stats)
        translator.set_glossary(glossary)

        progress_file = output_base + ".progress.json"
        progress_metadata = build_progress_metadata(
            pdf_path=pdf_path,
            glossary_path=glossary_path,
            model=model,
            start_page=start_page,
            end_page=end_page,
        )
        tracker = ProgressTracker(
            progress_file,
            expected_metadata=progress_metadata,
            reuse_mismatched=reuse_mismatched_progress,
        )
        if tracker.metadata_mismatches:
            st.warning(
                "检测到 progress.json 与当前设置不一致："
                + "；".join(tracker.metadata_mismatches[:3])
            )
            if tracker.ignored_existing_progress:
                st.info("已保留原 progress 文件，但本次不会复用其中的旧译文。")

        try:
            retranslate_pages = parse_page_selection(retranslate_pages_str, total)
        except ValueError as e:
            st.error(f"重翻页码格式错误：{e}")
            extractor.close()
            st.stop()
        retranslate_pages = {p for p in retranslate_pages if start_page <= p < end_page}
        if retranslate_pages:
            cleared = tracker.clear_pages(retranslate_pages)
            display_pages = ", ".join(str(p + 1) for p in sorted(retranslate_pages))
            st.info(f"已标记重翻页：{display_pages}（清理 {cleared} 条旧进度）。")

        # Extract
        st.info(f"📑 提取文本: {total} 页, 翻译第 {start_page + 1}-{end_page} 页")
        pages_text = {}
        page_layouts = {}
        for pn in range(start_page, end_page):
            page_layouts[pn] = extractor.detect_page_layout(pn)
            pages_text[pn] = extractor.extract_page(pn)
        extractor.finalize_chapters()
        toc = extractor.chapter_detector.get_toc_markdown()

        # Translate
        st.subheader("翻译进度")
        progress_bar = st.progress(0)
        status_text = st.empty()
        metric_cols = st.columns(5)
        progress_metric = metric_cols[0].empty()
        elapsed_metric = metric_cols[1].empty()
        eta_metric = metric_cols[2].empty()
        speed_metric = metric_cols[3].empty()
        cost_metric = metric_cols[4].empty()
        pages_list = list(range(start_page, end_page))
        total_to_do = len(pages_list)
        pages_data = []
        prev_text = ""
        for pn in pages_list:
            text = pages_text.get(pn, "")
            pages_data.append((pn, text, prev_text[-900:] if prev_text else ""))
            context_text = extractor.get_context_text(pn)
            if context_text.strip():
                prev_text = context_text

        translation_started_at = time.time()

        def set_progress(value, text):
            try:
                progress_bar.progress(value, text=text)
            except TypeError:
                progress_bar.progress(value)

        def render_progress(completed_count, total_count, latest_page=None):
            pct = completed_count / total_count if total_count else 1.0
            elapsed = time.time() - translation_started_at
            avg_seconds = elapsed / completed_count if completed_count else None
            remaining_seconds = (
                avg_seconds * (total_count - completed_count)
                if avg_seconds is not None else None
            )
            speed = 60 / avg_seconds if avg_seconds else None
            latest_text = f" | 最新第 {latest_page + 1} 页" if latest_page is not None else ""
            progress_text = (
                f"{completed_count}/{total_count} 页 ({pct * 100:.0f}%)"
                f" | 已用 {format_duration(elapsed)}"
                f" | 剩余 {format_duration(remaining_seconds)}"
            )
            set_progress(min(pct, 1.0), progress_text)
            status_text.text(
                f"翻译中: 已完成 {completed_count}/{total_count} 页{latest_text} | "
                f"费用 ¥{stats.cost_yuan:.3f}"
            )
            progress_metric.metric("进度", f"{completed_count}/{total_count}")
            elapsed_metric.metric("已用时", format_duration(elapsed))
            eta_metric.metric("预计剩余", format_duration(remaining_seconds))
            speed_metric.metric("速度", f"{speed:.1f} 页/分钟" if speed else "估算中")
            cost_metric.metric("费用", f"¥{stats.cost_yuan:.3f}")

        def update_translation_progress(page_num, translation, completed_count, total_count):
            render_progress(completed_count, total_count, page_num)

        if total_to_do:
            render_progress(0, total_to_do)
            results = translate_batch_concurrent(
                pages_data,
                translator,
                tracker,
                max_workers=max(1, int(workers)),
                progress_callback=update_translation_progress,
            )
        else:
            results = {}

        render_progress(total_to_do, total_to_do)
        status_text.text(f"✓ 翻译完成! 总用时 {format_duration(time.time() - translation_started_at)}")
        translated_pages_sorted = sorted(
            [(pn, t) for pn, t in results.items() if t.strip()],
            key=lambda x: x[0],
        )
        failed_pages = [
            pn + 1 for pn, text in translated_pages_sorted if is_failed_translation(text)
        ]
        if failed_pages:
            st.warning(
                "以下页翻译失败，未写入进度缓存，修复网络/API 问题后可直接重跑："
                + ", ".join(map(str, failed_pages[:20]))
            )

        # Stats
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("📄 页数", f"{len(translated_pages_sorted)}")
        col_b.metric("💰 费用", f"¥{stats.cost_yuan:.3f}")
        col_c.metric("🔢 Token", f"{stats.total_tokens:,}")

        # Output & Download
        if glossary:
            report_path = make_output_path(output_base, "_glossary_report.md")
            write_glossary_report(pages_text, glossary, report_path, pdf_stem)
            with open(report_path, "rb") as f:
                st.download_button(
                    "📥 下载术语命中报告",
                    f,
                    file_name=Path(report_path).name,
                )

        if "Markdown" in formats:
            md_path = make_output_path(output_base, ".md")
            write_markdown_output(
                translated_pages_sorted,
                md_path,
                pdf_stem,
                toc,
                page_layouts=page_layouts,
            )

            with open(md_path, "rb") as f:
                st.download_button(
                    "📥 下载 Markdown",
                    f,
                    file_name=Path(md_path).name,
                )

        if "HTML" in formats:
            html_path = make_output_path(output_base, ".html")
            try:
                write_html_output(
                    translated_pages_sorted,
                    html_path,
                    pdf_stem,
                    page_layouts=page_layouts,
                )
                with open(html_path, "rb") as f:
                    st.download_button(
                        "📥 下载 HTML",
                        f,
                        file_name=Path(html_path).name,
                        mime="text/html",
                    )
            except Exception as e:
                st.error(f"HTML 输出失败：{e}")

        if "Word" in formats:
            if not HAS_DOCX:
                st.warning("Word 输出需要 python-docx，请运行：pip install python-docx")
            else:
                docx_path = make_output_path(output_base, ".docx")
                write_word_output(
                    translated_pages_sorted,
                    docx_path,
                    pdf_stem,
                    min_chars=int(word_min_chars),
                    max_chars=int(word_max_chars),
                    body_font_size=float(word_body_font_size),
                    line_spacing=float(word_line_spacing),
                    columns=int(word_columns),
                    header_left=word_header_left,
                    header_right=word_header_right or None,
                    hard_page_breaks=bool(word_hard_page_breaks),
                    page_layouts=page_layouts,
                )

                with open(docx_path, "rb") as f:
                    st.download_button(
                        "📥 下载 Word",
                        f,
                        file_name=Path(docx_path).name,
                    )

        if open_output_when_done:
            try:
                os.startfile(str(output_dir))
                st.info(f"已打开输出文件夹：{output_dir}")
            except Exception as e:
                st.warning(f"无法自动打开输出文件夹：{e}")

        extractor.close()
