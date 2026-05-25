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
    normalize_page_range, is_failed_translation, build_extraction_diagnostics_report
)
from core.layout_extractor import extract_layout_to_file
from core.layout_translation import (
    apply_translations_file,
    translate_layout_to_template,
    write_overflow_report,
)
from exporters.pdf_html import render_layout_html
from exporters.pdf_playwright import export_layout_pdf
from webui.components import (
    make_dossier_id,
    render_audit_grid,
    render_completion_stamp,
    render_dossier_card,
    render_output_history,
    render_status_flow,
    render_system_log,
)
from webui.history import write_audit_record
from webui.theme import render_workstation_effects


APP_DIR = Path(__file__).resolve().parent
DEFAULT_GLOSSARY_PATH = APP_DIR / "glossary.tsv"
OUTPUT_FORMAT_LABELS = {
    "markdown": "纯文本稿",
    "html": "网页排版",
    "word": "文档排版",
    "replica_pdf": "原版坐标 PDF",
}


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
    page_title="三角洲翻译终端",
    page_icon="🖧",
    layout="wide",
)

st.markdown("""
<style>
    :root {
        --bg: #030604;
        --panel: rgba(5, 13, 8, 0.86);
        --panel-strong: rgba(8, 22, 13, 0.94);
        --line: rgba(69, 255, 129, 0.24);
        --line-hot: rgba(81, 255, 137, 0.72);
        --green: #52ff91;
        --green-soft: #9dffc1;
        --amber: #ffd166;
        --red: #ff4d4d;
        --text: #c8d8c9;
        --muted: #7f9b85;
        --shadow: rgba(82, 255, 145, 0.18);
    }

    .stApp, .stAppHeader {
        background:
            linear-gradient(rgba(82, 255, 145, 0.035) 1px, transparent 1px),
            linear-gradient(90deg, rgba(82, 255, 145, 0.025) 1px, transparent 1px),
            radial-gradient(circle at 12% 8%, rgba(82, 255, 145, 0.12), transparent 30%),
            radial-gradient(circle at 88% 28%, rgba(255, 77, 77, 0.08), transparent 26%),
            var(--bg) !important;
        background-size: 28px 28px, 28px 28px, auto, auto, auto !important;
        color: var(--text) !important;
        font-family: "SimHei", "Microsoft YaHei", "Noto Sans SC", sans-serif !important;
    }

    #MainMenu,
    footer,
    header[data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    .stDeployButton {
        display: none !important;
        visibility: hidden !important;
    }

    .stApp::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        z-index: 9999;
        background:
            linear-gradient(rgba(255, 255, 255, 0.018) 50%, rgba(0, 0, 0, 0.12) 50%),
            linear-gradient(90deg, rgba(255, 0, 0, 0.018), rgba(0, 255, 64, 0.012), rgba(0, 96, 255, 0.018));
        background-size: 100% 4px, 6px 100%;
        mix-blend-mode: screen;
        opacity: 0.32;
    }

    .stApp::after {
        content: "";
        position: fixed;
        left: 0;
        right: 0;
        top: -20%;
        height: 18%;
        pointer-events: none;
        z-index: 9998;
        background: linear-gradient(180deg, transparent, rgba(82, 255, 145, 0.12), transparent);
        animation: dg-scan 6.5s linear infinite;
    }

    @keyframes dg-scan {
        0% { transform: translateY(-10vh); }
        100% { transform: translateY(130vh); }
    }

    @keyframes panel-in {
        from { opacity: 0; transform: translateY(14px); }
        to { opacity: 1; transform: translateY(0); }
    }

    @keyframes pulse-line {
        0%, 100% { box-shadow: 0 0 0 rgba(82, 255, 145, 0); }
        50% { box-shadow: 0 0 28px var(--shadow); }
    }

    @media (prefers-reduced-motion: reduce) {
        .stApp::after, .boot-screen, .classified-hero, .section-card, .intel-tile { animation: none !important; }
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(4, 12, 7, 0.98), rgba(2, 7, 4, 0.98)) !important;
        border-right: 1px solid var(--line) !important;
        box-shadow: 12px 0 36px rgba(0, 0, 0, 0.42);
    }

    h1, h2, h3, .hero-title {
        color: var(--green) !important;
        font-family: "SimHei", "Microsoft YaHei", "Noto Sans SC", sans-serif !important;
        letter-spacing: 0;
        font-weight: 900;
    }

    p, label, .stMarkdown {
        color: var(--text) !important;
        font-size: 0.95rem;
    }

    .block-container {
        max-width: 1220px;
        padding-top: 1.5rem;
        padding-bottom: 4rem;
    }

    .classified-hero {
        position: relative;
        overflow: hidden;
        border: 1px solid var(--line-hot);
        background:
            linear-gradient(135deg, rgba(82, 255, 145, 0.13), transparent 42%),
            linear-gradient(180deg, rgba(7, 28, 14, 0.92), rgba(3, 8, 5, 0.86));
        padding: 26px 28px;
        margin-bottom: 18px;
        animation: panel-in 420ms ease-out, pulse-line 5s ease-in-out infinite;
    }

    .classified-hero::before {
        content: "绝密";
        position: absolute;
        right: -44px;
        top: 28px;
        transform: rotate(34deg);
        color: rgba(255, 77, 77, 0.24);
        border: 2px solid rgba(255, 77, 77, 0.24);
        padding: 6px 44px;
        font: 26px "SimHei", "Microsoft YaHei", sans-serif;
        letter-spacing: 0;
    }

    .hero-title {
        font-size: 3rem;
        line-height: 0.9;
        margin-bottom: 10px;
        text-shadow: 0 0 18px rgba(82, 255, 145, 0.34);
    }

    .hero-subtitle {
        color: var(--green-soft);
        font-size: 0.96rem;
        line-height: 1.65;
    }

    .terminal-line {
        color: var(--muted);
        margin-top: 14px;
        font-size: 0.86rem;
    }

    .terminal-cursor {
        display: inline-block;
        width: 9px;
        height: 1.05em;
        margin-left: 4px;
        background: var(--green);
        vertical-align: -0.15em;
        animation: blink 1s steps(1) infinite;
    }

    @keyframes blink {
        50% { opacity: 0; }
    }

    .intel-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
        margin-bottom: 18px;
    }

    .intel-tile, .section-card {
        border: 1px solid var(--line);
        background: var(--panel);
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.24);
        animation: panel-in 520ms ease-out both;
    }

    .intel-tile {
        padding: 12px 14px;
    }

    .intel-label {
        color: var(--muted);
        font-size: 0.72rem;
        text-transform: uppercase;
    }

    .intel-value {
        color: var(--green-soft);
        font: 1.5rem "SimHei", "Microsoft YaHei", sans-serif;
        margin-top: 2px;
    }

    .section-card {
        position: relative;
        padding: 20px;
        margin: 16px 0;
    }

    .section-card::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        width: 4px;
        height: 100%;
        background: linear-gradient(var(--green), transparent);
    }

    div[data-testid="stFileUploader"] {
        background: rgba(5, 18, 9, 0.7) !important;
        border: 1px dashed var(--line-hot) !important;
        border-radius: 0 !important;
        padding: 16px;
        transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
    }

    div[data-testid="stFileUploader"]:hover {
        border-color: var(--green) !important;
        box-shadow: 0 0 28px rgba(82, 255, 145, 0.16);
        transform: translateY(-1px);
    }

    .stTextInput input,
    .stNumberInput input,
    .stSelectbox div[data-baseweb="select"],
    .stMultiSelect div[data-baseweb="select"] {
        background-color: rgba(3, 9, 5, 0.95) !important;
        border: 1px solid var(--line) !important;
        border-radius: 0 !important;
        color: var(--green-soft) !important;
        font-family: "Courier Prime", monospace !important;
    }

    div[data-testid="stFileUploader"] button {
        font-size: 0 !important;
    }

    div[data-testid="stFileUploader"] button::after {
        content: "导入";
        font-size: 0.95rem;
    }

    div[data-testid="stFileUploader"] small {
        font-size: 0 !important;
    }

    .stTextInput input:focus,
    .stNumberInput input:focus {
        border-color: var(--green) !important;
        box-shadow: 0 0 0 1px rgba(82, 255, 145, 0.35) !important;
    }

    .stButton>button {
        position: relative;
        overflow: hidden;
        background: linear-gradient(90deg, rgba(82, 255, 145, 0.08), rgba(82, 255, 145, 0.02)) !important;
        color: var(--green) !important;
        border: 1px solid var(--line-hot) !important;
        border-radius: 0 !important;
        height: 48px;
        font-weight: bold;
        letter-spacing: 0;
        transition: all 0.18s ease;
        text-transform: uppercase;
    }

    .stButton>button:hover {
        background: var(--green) !important;
        color: #031006 !important;
        box-shadow: 0 0 26px rgba(82, 255, 145, 0.34);
    }

    .stProgress > div > div > div {
        background-color: var(--green) !important;
        box-shadow: 0 0 16px rgba(82, 255, 145, 0.52);
    }

    div[data-testid="stMetric"] {
        background: var(--panel-strong) !important;
        border: 1px solid var(--line) !important;
        border-radius: 0 !important;
        padding: 15px;
    }
    
    div[data-testid="stMetricValue"] {
        color: var(--green) !important;
    }

    [data-testid="stExpander"] {
        background: rgba(4, 12, 7, 0.74) !important;
        border: 1px solid var(--line) !important;
        border-radius: 0 !important;
    }

    .stAlert {
        border-radius: 0 !important;
    }

    textarea {
        background: rgba(2, 8, 4, 0.95) !important;
        color: var(--green-soft) !important;
        border: 1px solid var(--line) !important;
        font-family: "Courier Prime", monospace !important;
    }

    .boot-screen {
        position: fixed;
        inset: 0;
        z-index: 10000;
        pointer-events: none;
        display: grid;
        place-items: center;
        background:
            linear-gradient(rgba(82, 255, 145, 0.05) 1px, transparent 1px),
            linear-gradient(90deg, rgba(82, 255, 145, 0.04) 1px, transparent 1px),
            #020503;
        background-size: 30px 30px;
        animation: boot-hide 3.7s ease forwards;
    }

    .boot-panel {
        width: min(680px, calc(100vw - 44px));
        border: 1px solid var(--line-hot);
        background: rgba(3, 12, 6, 0.92);
        box-shadow: 0 0 52px rgba(82, 255, 145, 0.18);
        padding: 28px;
        font-family: "SimHei", "Microsoft YaHei", sans-serif;
    }

    .boot-title {
        color: var(--green);
        font-size: 2.2rem;
        font-weight: 900;
        letter-spacing: 0;
        margin-bottom: 14px;
    }

    .boot-lines {
        color: var(--green-soft);
        font-family: "Courier New", monospace;
        line-height: 1.8;
        font-size: 0.95rem;
    }

    .boot-bar {
        height: 8px;
        margin-top: 22px;
        border: 1px solid var(--line);
        background: rgba(82, 255, 145, 0.06);
        overflow: hidden;
    }

    .boot-bar::before {
        content: "";
        display: block;
        height: 100%;
        width: 0;
        background: var(--green);
        box-shadow: 0 0 18px rgba(82, 255, 145, 0.65);
        animation: boot-load 2.45s steps(18) forwards;
    }

    .boot-stamp {
        margin-top: 16px;
        color: rgba(255, 77, 77, 0.82);
        border: 1px solid rgba(255, 77, 77, 0.56);
        display: inline-block;
        padding: 4px 10px;
        transform: rotate(-2deg);
        font-weight: 900;
    }

    @keyframes boot-load {
        to { width: 100%; }
    }

    @keyframes boot-hide {
        0%, 72% { opacity: 1; visibility: visible; }
        100% { opacity: 0; visibility: hidden; }
    }

    @media (max-width: 760px) {
        .intel-grid {
            grid-template-columns: 1fr;
        }
        .hero-title {
            font-size: 2.2rem;
        }
    }
</style>
""", unsafe_allow_html=True)
reduce_motion = bool(st.session_state.get("reduce_motion", False))
try:
    render_workstation_effects(reduced_motion=reduce_motion)
except TypeError:
    render_workstation_effects()
    if reduce_motion:
        st.markdown(
            """
<style>
    .stApp::after,
    .boot-screen,
    .classified-hero,
    .section-card,
    .intel-tile,
    .dossier-card.loaded::after,
    .status-flow::before,
    .status-step.active,
    .system-log-line,
    .archive-stamp,
    div[data-testid="stMetric"]::after,
    div[data-testid="stAlert"]::before,
    div[data-testid="stExpander"] details[open] > div,
    .stDownloadButton > button::before {
        animation: none !important;
    }
</style>
            """,
            unsafe_allow_html=True,
        )
st.markdown(
    """
<style>
    div[data-testid="stAlert"] {
        border-radius: 0 !important;
        border: 1px solid var(--line) !important;
        background: rgba(4, 12, 7, 0.92) !important;
        box-shadow: none !important;
        position: relative;
        overflow: hidden;
    }
    div[data-testid="stAlert"] > div {
        background: transparent !important;
        color: var(--text) !important;
    }
    div[data-testid="stAlert"] [data-testid="stMarkdownContainer"],
    div[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {
        color: var(--text) !important;
    }
    div[data-testid="stAlert"] * {
        border-radius: 0 !important;
    }
    div[data-testid="stAlert"]::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 4px;
        pointer-events: none;
        background: var(--green);
    }
</style>
    """,
    unsafe_allow_html=True,
)

# === HEADER ===
st.markdown("""
<div class="boot-screen">
    <div class="boot-panel">
        <div class="boot-title">绝密系统接入中</div>
        <div class="boot-lines">
            > 正在校验操作员密钥<br>
            > 正在载入译文编译协议<br>
            > 正在建立黑色档案通道
        </div>
        <div class="boot-bar"></div>
        <div class="boot-stamp">TOP SECRET</div>
    </div>
</div>
<div class="classified-hero">
    <div class="hero-title">三角洲翻译终端</div>
    <div class="hero-subtitle">
        > 访问等级：黑色绝密<br>
        > 执行协议：文本提取 / 术语锁定 / 译文编译<br>
        > 终端状态：等待导入档案
    </div>
    <div class="terminal-line">系统就绪<span class="terminal-cursor"></span></div>
</div>
<div class="intel-grid">
    <div class="intel-tile">
        <div class="intel-label">任务</div>
        <div class="intel-value">翻译</div>
    </div>
    <div class="intel-tile">
        <div class="intel-label">输出</div>
        <div class="intel-value">网页 / 文档</div>
    </div>
    <div class="intel-tile">
        <div class="intel-label">模式</div>
        <div class="intel-value">私密校对</div>
    </div>
</div>
""", unsafe_allow_html=True)
with st.sidebar:
    st.header("任务控制台")

    provider = "deepseek"
    base_url = "https://api.deepseek.com"
    model = "deepseek-v4-pro"
    workers = 4
    retranslate_pages_str = ""
    retry_failed_pages = False
    reuse_mismatched_progress = False
    show_extraction_preview = False
    preview_page = 1
    word_body_font_size = 12.0
    word_line_spacing = 1.5
    word_columns = 2
    word_min_chars = 1000
    word_max_chars = 1500
    word_hard_page_breaks = False
    word_header_left = "绿色三角洲"
    word_header_right = ""

    st.checkbox("低动效模式", value=False, key="reduce_motion")

    st.caption("必要项")
    api_key = st.text_input("接口密钥", type="password", placeholder="sk-...")

    formats = st.multiselect(
        "输出格式",
        ["markdown", "html", "word", "replica_pdf"],
        default=["html", "word"],
        format_func=lambda value: OUTPUT_FORMAT_LABELS[value],
    )
    if "replica_pdf" in formats:
        st.caption("原版坐标 PDF 会单独运行，图片先保留占位框，不嵌回原图像素。")

    display_start_page = st.number_input("起始页（从 1 开始）", value=1, min_value=1)
    end_page_str = st.text_input("结束页（含，从 1 开始）", value="", placeholder="留空表示全部")

    with st.expander("高级任务控制", expanded=False):
        model = st.text_input("模型名称", value=model)
        workers = st.slider("并发线程", 1, 16, 4)
        retranslate_pages_str = st.text_input("重翻页码", value="", placeholder="如：8, 12-15")
        retry_failed_pages = st.checkbox("只重试失败页", value=False)
        show_extraction_preview = st.checkbox("显示提取预览", value=False)
        if show_extraction_preview:
            preview_page = st.number_input("预览页（从 1 开始）", value=1, min_value=1)

    if "word" in formats:
        with st.expander("文档档案输出", expanded=False):
            word_body_font_size = st.slider("正文字号", 9.0, 14.0, 12.0, 0.5)
            word_line_spacing = st.slider("正文行距", 1.0, 2.0, 1.5, 0.05)
            word_columns = st.selectbox("正文分栏", [1, 2], index=1, format_func=lambda n: f"{n} 栏")
            word_min_chars = st.number_input("阅读页最少字数", value=1000, min_value=300, max_value=3000, step=100)
            word_max_chars = st.number_input("阅读页最多字数", value=1500, min_value=500, max_value=5000, step=100)
            word_hard_page_breaks = st.checkbox(
                "按阅读页强制分页",
                value=False,
                help="关闭时文档会自然续排，减少半页空白；开启时每个阅读页后插入分页符。",
            )
            word_header_left = st.text_input("页眉左侧", value="绿色三角洲")
            word_header_right = st.text_input("页眉右侧", value="", placeholder="留空则使用文件名")

# === MAIN ===
st.markdown('<div class="section-card">', unsafe_allow_html=True)

st.subheader("导入机密档案")
st.caption("上传原始 PDF。默认加载本地 glossary.tsv；只有需要替换术语时再上传自定义文件。")

col1, col2 = st.columns([1.2, 1])
with col1:
    pdf_file = st.file_uploader("PDF 档案", type=["pdf"], label_visibility="collapsed")
with col2:
    glossary_file = st.file_uploader("替换术语表，可选", type=["tsv", "txt", "csv"], label_visibility="collapsed")
    if glossary_file:
        st.caption(f"将使用上传术语表：{glossary_file.name}")
    elif DEFAULT_GLOSSARY_PATH.exists():
        st.caption("将使用默认术语表：glossary.tsv")
    else:
        st.caption("未找到默认术语表；可上传自定义术语表。")

st.markdown("</div>", unsafe_allow_html=True)

if pdf_file:
    current_digest = uploaded_file_digest(pdf_file)
    current_dossier_id = make_dossier_id(pdf_file.name, current_digest)
    glossary_name = glossary_file.name if glossary_file else "glossary.tsv"
    render_dossier_card(
        current_dossier_id,
        pdf_file.name,
        current_digest,
        glossary_name=glossary_name,
        loaded=True,
    )
    render_status_flow(active_index=0)
    render_system_log([
        ("info", "档案接收完成"),
        ("info", f"档案号 {current_dossier_id} 已生成"),
        ("info", "等待执行翻译任务"),
    ])

render_output_history(APP_DIR / "output")

if pdf_file and show_extraction_preview:
    preview_path = save_uploaded_pdf_for_preview(pdf_file)
    preview_extractor = None
    try:
        preview_extractor = PDFExtractor(str(preview_path))
        total_preview_pages = preview_extractor.total_pages
        preview_index = min(max(int(preview_page) - 1, 0), total_preview_pages - 1)
        preview_text = preview_extractor.extract_page(preview_index)
        preview_notes = preview_extractor.get_layout_notes(preview_index)
        preview_diag = preview_extractor.get_page_diagnostics(preview_index, preview_text)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("提取预览 / 诊断")
        st.caption(
            f"PDF 共 {total_preview_pages} 页；当前预览第 {preview_index + 1} 页。"
            "这里只展示提取和排序后的文本，不会调用翻译 API。"
        )
        if preview_notes:
            st.caption("版面识别：" + "；".join(preview_notes))
        if preview_diag["risks"]:
            st.warning("风险提示：" + "；".join(preview_diag["risks"]))
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

if st.button("执行翻译任务", type="primary", use_container_width=True):
    if not pdf_file:
        st.error("✗ 请上传 PDF 文件")
    elif not api_key:
        st.error("✗ 请输入接口密钥")
    elif not base_url.strip():
        st.error("✗ 请输入接口地址")
    elif not model.strip():
        st.error("✗ 请输入模型名称")
    elif not formats:
        st.error("✗ 请至少选择一种输出格式")
    elif "replica_pdf" in formats and len(formats) > 1:
        st.error("✗ 原版坐标 PDF 请单独运行，避免和阅读版输出重复调用接口。")
    else:
        run_started_at = time.time()
        source_digest = uploaded_file_digest(pdf_file)
        dossier_id = make_dossier_id(pdf_file.name, source_digest, created_at=run_started_at)
        render_dossier_card(
            dossier_id,
            pdf_file.name,
            source_digest,
            glossary_name=glossary_file.name if glossary_file else "glossary.tsv",
            loaded=True,
        )
        render_status_flow(active_index=1)
        render_system_log([
            ("info", "接收档案完成"),
            ("info", f"档案号 {dossier_id}"),
            ("info", "准备提取文本"),
        ])

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
        document_output_dir = output_dir / f"{pdf_stem}_cn"
        ensure_dir(document_output_dir)
        output_base = str(document_output_dir / f"{pdf_stem}_cn")
        generated_files = []

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
        if "word" in formats and word_max_chars < word_min_chars:
            st.error("文档排版的阅读页最多字数必须大于或等于最少字数。")
            extractor.close()
            st.stop()

        glossary = load_glossary(glossary_path) if glossary_path else {}
        if glossary_path:
            glossary_source = Path(glossary_path).name
            st.info(f"📚 术语表: {glossary_source} ({len(glossary)} 条)")
        else:
            st.warning("未使用术语表。")
        translator = Translator(api_key=api_key, model=model, base_url=base_url, stats=stats)
        translator.set_glossary(glossary)

        if formats == ["replica_pdf"]:
            layout_path = make_output_path(output_base, "_replica.layout.json")
            translations_path = make_output_path(output_base, "_replica.translations.json")
            translated_layout_path = make_output_path(output_base, "_replica.translated.layout.json")
            overflow_path = make_output_path(output_base, "_replica.overflow.md")
            replica_html_path = make_output_path(output_base, "_replica.html")
            replica_pdf_path = make_output_path(output_base, "_replica.pdf")
            replica_progress_path = make_output_path(output_base, "_replica.progress.json")

            render_status_flow(active_index=1)
            st.info(f"📐 提取坐标版面：第 {start_page + 1}-{end_page} 页")
            layout = extract_layout_to_file(
                pdf_path,
                layout_path,
                start_page=start_page,
                end_page=end_page,
            )
            generated_files.append(layout_path)

            render_status_flow(active_index=3)
            st.info("正在按文本块翻译坐标版面。")
            replica_progress_bar = st.progress(0)
            replica_status = st.empty()
            replica_metric_cols = st.columns(4)
            replica_done_metric = replica_metric_cols[0].empty()
            replica_elapsed_metric = replica_metric_cols[1].empty()
            replica_speed_metric = replica_metric_cols[2].empty()
            replica_cost_metric = replica_metric_cols[3].empty()
            replica_started_at = time.time()

            def update_replica_progress(done_count, total_count, block_id, success):
                pct = done_count / total_count if total_count else 1.0
                elapsed = time.time() - replica_started_at
                avg_seconds = elapsed / done_count if done_count else None
                speed = 60 / avg_seconds if avg_seconds else None
                state_text = "完成" if success else "失败"
                try:
                    replica_progress_bar.progress(
                        min(pct, 1.0),
                        text=f"{done_count}/{total_count} 块 ({pct * 100:.0f}%)",
                    )
                except TypeError:
                    replica_progress_bar.progress(min(pct, 1.0))
                replica_status.text(
                    f"坐标翻译：{state_text} {block_id} | "
                    f"已用 {format_duration(elapsed)} | 费用 ¥{stats.cost_yuan:.3f}"
                )
                replica_done_metric.metric("翻译组", f"{done_count}/{total_count}")
                replica_elapsed_metric.metric("已用时", format_duration(elapsed))
                replica_speed_metric.metric("速度", f"{speed:.1f} 组/分钟" if speed else "估算中")
                replica_cost_metric.metric("费用", f"¥{stats.cost_yuan:.3f}")

            translate_layout_to_template(
                layout,
                translator,
                progress_file=replica_progress_path,
                output_path=translations_path,
                retry_failed=retry_failed_pages,
                progress_callback=update_replica_progress,
            )
            generated_files.extend([translations_path, replica_progress_path])

            translated_layout = apply_translations_file(
                layout_path,
                translations_path,
                translated_layout_path,
            )
            generated_files.append(translated_layout_path)

            issues = write_overflow_report(translated_layout, overflow_path)
            generated_files.append(overflow_path)
            render_layout_html(translated_layout, replica_html_path, show_boxes=True)
            generated_files.append(replica_html_path)

            if issues:
                render_status_flow(active_index=4, failed=True)
                st.warning(
                    f"发现 {len(issues)} 个译文溢出文本块。已生成 HTML 和溢出报告，"
                    "请先缩短译文或手动调整后再导出 PDF。"
                )
            else:
                render_status_flow(active_index=4)
                export_layout_pdf(
                    translated_layout,
                    replica_pdf_path,
                    html_output=replica_html_path,
                    show_boxes=False,
                )
                generated_files.append(replica_pdf_path)

            for path in generated_files:
                file_path = Path(path)
                with open(file_path, "rb") as f:
                    st.download_button(
                        f"📥 下载 {file_path.name}",
                        f,
                        file_name=file_path.name,
                    )

            audit_path = Path(make_output_path(output_base, "_audit.json"))
            audit_record = {
                "dossier_id": dossier_id,
                "source_file": pdf_file.name,
                "source_sha256": source_digest,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run_started_at)),
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "provider": provider,
                "model": model,
                "page_range": f"{start_page + 1}-{end_page}",
                "formats": formats,
                "completed_pages": len(layout.pages),
                "failed_pages": [],
                "overflow_blocks": len(issues),
                "glossary": Path(glossary_path).name if glossary_path else "",
                "outputs": [Path(path).name for path in generated_files],
            }
            write_audit_record(audit_path, audit_record)
            generated_files.append(str(audit_path))
            render_status_flow(active_index=5, failed=bool(issues))
            render_completion_stamp("待处理溢出" if issues else "已归档")
            render_audit_grid({
                "档案号": dossier_id,
                "坐标页": len(layout.pages),
                "溢出块": len(issues),
                "输出数": len(generated_files),
            })
            with open(audit_path, "rb") as f:
                st.download_button("📥 下载审计记录", f, file_name=audit_path.name)
            extractor.close()
            st.stop()

        progress_file = output_base + ".progress.json"
        progress_metadata = build_progress_metadata(
            pdf_path=pdf_path,
            glossary_path=glossary_path,
            model=model,
            provider=provider,
            base_url=base_url,
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

        failed_from_progress = {
            p for p in tracker.get_failed_pages()
            if start_page <= p < end_page
        }
        if failed_from_progress:
            st.info(
                "进度文件中记录的失败页："
                + ", ".join(str(p + 1) for p in sorted(failed_from_progress)[:30])
            )

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
        if retry_failed_pages:
            if failed_from_progress:
                pages_filter = failed_from_progress
                tracker.clear_failed_pages(pages_filter)
                st.info(
                    "本次只重试失败页："
                    + ", ".join(str(p + 1) for p in sorted(pages_filter))
                )
            else:
                pages_filter = set()
                st.warning("没有可重试的失败页。")
        else:
            pages_filter = set(range(start_page, end_page))

        # Extract
        render_status_flow(active_index=1)
        st.info(f"📑 提取文本: {total} 页, 翻译第 {start_page + 1}-{end_page} 页")
        pages_text = {}
        page_layouts = {}
        page_diagnostics = []
        image_assets = {}
        asset_dir = str(document_output_dir / "assets")
        for pn in range(start_page, end_page):
            page_layouts[pn] = extractor.detect_page_layout(pn)
            pages_text[pn] = extractor.extract_page(pn)
            page_diagnostics.append(extractor.get_page_diagnostics(pn, pages_text[pn]))
            images = extractor.export_page_images(pn, asset_dir, pdf_stem)
            if images:
                image_assets[pn] = images
        extractor.finalize_chapters()
        toc = extractor.chapter_detector.get_toc_markdown()
        risky_pages = [item for item in page_diagnostics if item.get("risks")]
        if risky_pages:
            st.warning(
                "提取诊断发现风险页："
                + ", ".join(str(item["page"] + 1) for item in risky_pages[:30])
            )
        extracted_image_count = sum(len(v) for v in image_assets.values())
        if image_assets:
            st.info(f"已裁出图片资源：{extracted_image_count} 张")
        extraction_log = [
            ("info", f"检测到 {total} 页"),
            ("info", f"本次处理第 {start_page + 1}-{end_page} 页"),
        ]
        if risky_pages:
            extraction_log.append(("warn", f"风险页 {len(risky_pages)} 个"))
        if extracted_image_count:
            extraction_log.append(("info", f"图片资源 {extracted_image_count} 张"))
        render_system_log(extraction_log)

        # Translate
        render_status_flow(active_index=3)
        st.subheader("翻译进度")
        progress_bar = st.progress(0)
        status_text = st.empty()
        metric_cols = st.columns(5)
        progress_metric = metric_cols[0].empty()
        elapsed_metric = metric_cols[1].empty()
        eta_metric = metric_cols[2].empty()
        speed_metric = metric_cols[3].empty()
        cost_metric = metric_cols[4].empty()
        pages_list = sorted(pages_filter)
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
            [
                (pn, tracker.get_translation(pn))
                for pn in range(start_page, end_page)
                if tracker.get_translation(pn).strip()
            ],
            key=lambda x: x[0],
        )
        failed_pages = [
            pn + 1 for pn in sorted(tracker.get_failed_pages())
            if start_page <= pn < end_page
        ]
        if failed_pages:
            render_status_flow(active_index=3, failed=True)
            st.warning(
                "以下页翻译失败，已记录为失败页，修复网络/API 问题后可勾选“只重试失败页”："
                + ", ".join(map(str, failed_pages[:20]))
            )

        # Stats
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("📄 页数", f"{len(translated_pages_sorted)}")
        col_b.metric("💰 费用", f"¥{stats.cost_yuan:.3f}")
        col_c.metric("🔢 Token", f"{stats.total_tokens:,}")

        # Output & Download
        render_status_flow(active_index=4)
        diagnostics_path = make_output_path(output_base, "_extraction_report.md")
        with open(diagnostics_path, "w", encoding="utf-8") as f:
            f.write(build_extraction_diagnostics_report(page_diagnostics, pdf_stem))
            f.write("\n")
        generated_files.append(diagnostics_path)
        with open(diagnostics_path, "rb") as f:
            st.download_button(
                "📥 下载提取诊断报告",
                f,
                file_name=Path(diagnostics_path).name,
            )

        if glossary:
            report_path = make_output_path(output_base, "_glossary_report.md")
            write_glossary_report(pages_text, glossary, report_path, pdf_stem)
            generated_files.append(report_path)
            with open(report_path, "rb") as f:
                st.download_button(
                    "📥 下载术语命中报告",
                    f,
                    file_name=Path(report_path).name,
                )

        if "markdown" in formats:
            md_path = make_output_path(output_base, ".md")
            write_markdown_output(
                translated_pages_sorted,
                md_path,
                pdf_stem,
                toc,
                page_layouts=page_layouts,
                image_assets=image_assets,
            )
            generated_files.append(md_path)

            with open(md_path, "rb") as f:
                st.download_button(
                    "📥 下载纯文本稿",
                    f,
                    file_name=Path(md_path).name,
                )

        if "html" in formats:
            html_path = make_output_path(output_base, ".html")
            try:
                write_html_output(
                    translated_pages_sorted,
                    html_path,
                    pdf_stem,
                    page_layouts=page_layouts,
                    image_assets=image_assets,
                )
                generated_files.append(html_path)
                with open(html_path, "rb") as f:
                    st.download_button(
                        "📥 下载网页排版",
                        f,
                        file_name=Path(html_path).name,
                        mime="text/html",
                    )
            except Exception as e:
                st.error(f"网页排版输出失败：{e}")

        if "word" in formats:
            if not HAS_DOCX:
                st.warning("文档排版需要 python-docx，请运行：pip install python-docx")
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
                    source_pages_text=pages_text,
                    page_layouts=page_layouts,
                    image_assets=image_assets,
                )
                generated_files.append(docx_path)

                with open(docx_path, "rb") as f:
                    st.download_button(
                        "📥 下载文档排版",
                        f,
                        file_name=Path(docx_path).name,
                    )

        audit_path = Path(make_output_path(output_base, "_audit.json"))
        audit_record = {
            "dossier_id": dossier_id,
            "source_file": pdf_file.name,
            "source_sha256": source_digest,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run_started_at)),
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "provider": provider,
            "model": model,
            "page_range": f"{start_page + 1}-{end_page}",
            "formats": formats,
            "completed_pages": len(translated_pages_sorted),
            "failed_pages": failed_pages,
            "glossary": Path(glossary_path).name if glossary_path else "",
            "outputs": [Path(path).name for path in generated_files],
        }
        write_audit_record(audit_path, audit_record)
        generated_files.append(str(audit_path))
        render_status_flow(active_index=5, failed=bool(failed_pages))
        render_completion_stamp("待校对" if failed_pages else "已归档")
        final_audit_items = {
            "档案号": dossier_id,
            "完成页": len(translated_pages_sorted),
            "输出数": len(generated_files),
        }
        if failed_pages:
            final_audit_items["失败页"] = ", ".join(map(str, failed_pages[:12]))
        render_audit_grid(final_audit_items)
        with open(audit_path, "rb") as f:
            st.download_button(
                "📥 下载审计记录",
                f,
                file_name=audit_path.name,
            )
        extractor.close()
