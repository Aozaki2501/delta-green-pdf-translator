#!/usr/bin/env python3
"""
Delta Green PDF Translator — Web UI (Streamlit)
"""
import streamlit as st
import os
import time
import uuid
from pathlib import Path
from translate_pdf import (
    PDFExtractor, Translator, ProgressTracker, TokenStats,
    PDFOverlayWriter, load_glossary, translate_batch_concurrent,
    write_markdown_output, write_word_output, HAS_DOCX
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
        将英文 TRPG PDF 提取、翻译并输出为 Markdown、Word 或实验性排版 PDF。
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
        ["Markdown", "PDF", "Word"],
        default=["Word"],
    )

    start_page = st.number_input("起始页", value=0, min_value=0)
    end_page_str = st.text_input("结束页", value="", placeholder="留空表示全部")

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

if st.button("🔺 开始翻译", type="primary", use_container_width=True):
    if not pdf_file:
        st.error("✗ 请上传 PDF 文件")
    elif not api_key:
        st.error("✗ 请输入 API Key")
    else:
        # Create organized directories
        upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
        os.makedirs(upload_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        # Save uploaded files to uploads/
        pdf_upload_name = f"_upload_{Path(pdf_file.name).stem}_{uuid.uuid4().hex[:8]}{Path(pdf_file.name).suffix}"
        pdf_path = os.path.join(upload_dir, pdf_upload_name)
        with open(pdf_path, "wb") as f:
            f.write(pdf_file.read())

        glossary_path = str(DEFAULT_GLOSSARY_PATH) if DEFAULT_GLOSSARY_PATH.exists() else None
        if glossary_file:
            glossary_upload_name = f"_upload_{Path(glossary_file.name).stem}_{uuid.uuid4().hex[:8]}{Path(glossary_file.name).suffix}"
            glossary_path = os.path.join(upload_dir, glossary_upload_name)
            with open(glossary_path, "wb") as f:
                f.write(glossary_file.read())

        end_page = int(end_page_str) if end_page_str.strip() else None
        output_base = os.path.join(output_dir, f"{Path(pdf_file.name).stem}_cn")

        # Init
        stats = TokenStats()
        extractor = PDFExtractor(pdf_path)
        total = extractor.total_pages
        if end_page is None or end_page > total:
            end_page = total

        glossary = load_glossary(glossary_path) if glossary_path else {}
        if glossary_path:
            glossary_source = Path(glossary_path).name
            st.info(f"📚 术语表: {glossary_source} ({len(glossary)} 条)")
        else:
            st.warning("未使用术语表。")
        translator = Translator(api_key=api_key, model=model, stats=stats)
        translator.set_glossary(glossary)

        progress_file = output_base + ".progress.json"
        tracker = ProgressTracker(progress_file)

        # Extract
        st.info(f"📑 提取文本: {total} 页, 翻译 {start_page+1}-{end_page} 页")
        pages_text = {}
        for pn in range(start_page, end_page):
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
            pages_data.append((pn, text, prev_text[-300:] if prev_text else ""))
            if text.strip():
                prev_text = text

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

        # Stats
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("📄 页数", f"{len(translated_pages_sorted)}")
        col_b.metric("💰 费用", f"¥{stats.cost_yuan:.3f}")
        col_c.metric("🔢 Token", f"{stats.total_tokens:,}")

                # Output & Download
        if "Markdown" in formats:
            md_path = make_output_path(output_base, ".md")
            write_markdown_output(translated_pages_sorted, md_path, Path(pdf_file.name).stem, toc)

            with open(md_path, "rb") as f:
                st.download_button(
                    "📥 下载 Markdown",
                    f,
                    file_name=Path(md_path).name,
                )

        if "PDF" in formats:
            pdf_out_path = make_output_path(output_base, ".pdf")
            try:
                writer = PDFOverlayWriter(pdf_path, pdf_out_path)

                for pn, t in translated_pages_sorted:
                    if t.strip():
                        writer.overlay_page(pn, t)

                writer.save()

                with open(pdf_out_path, "rb") as f:
                    st.download_button(
                        "📥 下载 PDF",
                        f,
                        file_name=Path(pdf_out_path).name,
                    )
            except Exception as e:
                st.error(f"PDF 输出失败：{e}")

        if "Word" in formats:
            if not HAS_DOCX:
                st.warning("Word 输出需要 python-docx，请运行：pip install python-docx")
            else:
                docx_path = make_output_path(output_base, ".docx")
                write_word_output(translated_pages_sorted, docx_path, Path(pdf_file.name).stem)

                with open(docx_path, "rb") as f:
                    st.download_button(
                        "📥 下载 Word",
                        f,
                        file_name=Path(docx_path).name,
                    )

        extractor.close()
