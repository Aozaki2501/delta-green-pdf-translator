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
import zipfile
from pathlib import Path
from translate_pdf import (
    PDFExtractor, Translator, ProgressTracker, TokenStats,
    load_glossary, translate_batch_concurrent,
    write_markdown_output, write_html_output, write_word_output, HAS_DOCX,
    build_progress_metadata, parse_page_selection, write_glossary_report,
    normalize_page_range, is_failed_translation, build_extraction_diagnostics_report
)
from webui.components import (
    make_dossier_id,
    render_audit_grid,
    render_completion_stamp,
    render_dossier_card,
    render_output_history,
    render_status_flow,
    render_system_log,
)
from webui.history import is_final_output_file, write_audit_record
from webui.theme import render_workstation_effects

# MD / DOCX translation support
from translate_md import translate_md_file
from translate_docx import translate_docx_file
from core.md_extractor import MarkdownExtractor
from core.docx_extractor import DocxExtractor, HAS_DOCX as HAS_DOCX_LIB
from core.layout_adapters import build_pdf_output_layout_context, merge_output_page_layouts
from core.utils import looks_untranslated_page


APP_DIR = Path(__file__).resolve().parent
DEFAULT_GLOSSARY_PATH = APP_DIR / "glossary.tsv"
OUTPUT_FORMAT_LABELS = {
    "markdown": "纯文本稿",
    "html": "网页排版",
    "word": "文档排版",
    "typeset_pdf": "纯重绘 PDF（_typeset）",
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


def existing_output_files(paths, final_only: bool = False):
    files = [Path(path) for path in paths if Path(path).exists()]
    if final_only:
        files = [path for path in files if is_final_output_file(path)]
    return [str(path) for path in files]


def render_downloads(paths, label_prefix="下载"):
    for path in existing_output_files(paths, final_only=True):
        file_path = Path(path)
        with open(file_path, "rb") as f:
            st.download_button(
                f"📥 {label_prefix} {file_path.name}",
                f,
                file_name=file_path.name,
            )


def make_html_asset_bundle(html_path: str | Path) -> str | None:
    html_file = Path(html_path)
    if not html_file.exists():
        return None
    assets_dir = html_file.parent / "assets"
    if not assets_dir.exists():
        return None

    bundle_path = html_file.with_suffix(".html_assets.zip")
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(html_file, arcname=html_file.name)
        for asset in sorted(assets_dir.rglob("*")):
            if asset.is_file():
                zf.write(asset, arcname=str(asset.relative_to(html_file.parent)))
    return str(bundle_path)


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


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
        .stApp::after, .classified-hero, .section-card, .intel-tile, .launch-panel, .terminal-cursor, .radar-fill, .radar-step::before { animation: none !important; }
        .boot-screen { display: none !important; opacity: 0 !important; visibility: hidden !important; }
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
            linear-gradient(120deg, rgba(82, 255, 145, 0.18), transparent 35%),
            linear-gradient(180deg, rgba(7, 28, 14, 0.94), rgba(3, 8, 5, 0.88));
        padding: 30px;
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
        font-size: 3.25rem;
        line-height: 0.9;
        margin-bottom: 10px;
        text-shadow: 0 0 18px rgba(82, 255, 145, 0.34);
    }

    .hero-grid {
        position: relative;
        z-index: 1;
        display: grid;
        grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.75fr);
        gap: 24px;
        align-items: end;
    }

    .hero-seal {
        min-height: 176px;
        border: 1px solid rgba(82, 255, 145, 0.28);
        background:
            linear-gradient(135deg, rgba(82, 255, 145, 0.08), transparent 58%),
            repeating-linear-gradient(0deg, rgba(82, 255, 145, 0.05) 0 1px, transparent 1px 14px),
            rgba(1, 5, 3, 0.58);
        padding: 18px;
        display: grid;
        align-content: space-between;
    }

    .hero-seal-code {
        color: var(--muted);
        font-family: "Courier New", monospace;
        font-size: 0.78rem;
        line-height: 1.7;
    }

    .hero-seal-mark {
        color: rgba(255, 77, 77, 0.78);
        border: 1px solid rgba(255, 77, 77, 0.42);
        display: inline-block;
        width: fit-content;
        padding: 6px 12px;
        font-weight: 900;
        transform: rotate(-3deg);
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

    .status-radar {
        width: min(520px, 100%);
        margin-top: 16px;
    }

    .radar-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
    }

    .radar-label {
        color: var(--green-soft);
        font-family: "Courier New", monospace;
        font-weight: 700;
    }

    .radar-step {
        position: relative;
        border: 1px solid rgba(82, 255, 145, 0.24);
        background: rgba(2, 8, 4, 0.7);
        color: var(--muted);
        padding: 4px 8px 4px 18px;
        font-family: "Courier New", monospace;
        font-size: 0.72rem;
    }

    .radar-step::before {
        content: "";
        position: absolute;
        left: 7px;
        top: 50%;
        width: 5px;
        height: 5px;
        transform: translateY(-50%);
        background: var(--green);
        box-shadow: 0 0 10px rgba(82, 255, 145, 0.72);
        animation: radar-pulse 1.8s ease-in-out infinite;
    }

    .radar-step:nth-child(3)::before { animation-delay: 220ms; }
    .radar-step:nth-child(4)::before { animation-delay: 440ms; }

    .radar-track {
        height: 8px;
        margin-top: 10px;
        border: 1px solid rgba(82, 255, 145, 0.28);
        background:
            repeating-linear-gradient(90deg, rgba(82, 255, 145, 0.08) 0 8px, transparent 8px 16px),
            rgba(1, 7, 3, 0.82);
        overflow: hidden;
    }

    .radar-fill {
        display: block;
        height: 100%;
        width: 38%;
        background: linear-gradient(90deg, transparent, var(--green), var(--green-soft), transparent);
        box-shadow: 0 0 18px rgba(82, 255, 145, 0.54);
        animation: radar-sweep 2.6s ease-in-out infinite;
    }

    @keyframes radar-sweep {
        0% { transform: translateX(-105%); }
        48% { transform: translateX(84%); }
        100% { transform: translateX(180%); }
    }

    @keyframes radar-pulse {
        0%, 100% { opacity: 0.4; }
        50% { opacity: 1; }
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
        grid-template-columns: 1.25fr 1fr 1fr;
        gap: 14px;
        margin-bottom: 20px;
    }

    .intel-tile, .section-card {
        border: 1px solid var(--line);
        background: var(--panel);
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.24);
        animation: panel-in 520ms ease-out both;
    }

    .intel-tile {
        min-height: 96px;
        padding: 18px;
        display: grid;
        align-content: space-between;
        background:
            linear-gradient(160deg, rgba(82, 255, 145, 0.09), transparent 54%),
            rgba(5, 13, 8, 0.86);
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
        padding: 24px;
        margin: 18px 0;
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

    .task-dock {
        border-color: rgba(82, 255, 145, 0.42);
        background:
            linear-gradient(135deg, rgba(82, 255, 145, 0.1), transparent 34%),
            linear-gradient(180deg, rgba(6, 18, 10, 0.92), rgba(3, 9, 5, 0.88));
    }

    .section-heading {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        align-items: flex-start;
        margin-bottom: 18px;
    }

    .section-kicker,
    .launch-kicker,
    .sidebar-kicker {
        color: var(--muted);
        font-family: "Courier New", monospace;
        font-size: 0.74rem;
        text-transform: uppercase;
    }

    .section-title,
    .launch-title {
        color: var(--green);
        font-size: 1.55rem;
        font-weight: 900;
        margin-top: 4px;
    }

    .section-note {
        color: var(--green-soft);
        max-width: 520px;
        line-height: 1.6;
        font-size: 0.92rem;
    }

    .launch-panel {
        display: grid;
        grid-template-columns: minmax(240px, 0.75fr) minmax(0, 1.25fr);
        gap: 18px;
        align-items: center;
        border: 1px solid rgba(82, 255, 145, 0.46);
        background:
            linear-gradient(90deg, rgba(82, 255, 145, 0.14), transparent 44%),
            rgba(4, 13, 7, 0.92);
        padding: 20px 22px;
        margin: 18px 0 10px;
        box-shadow: 0 18px 42px rgba(0, 0, 0, 0.34);
        animation: panel-in 520ms ease-out both;
    }

    .launch-status {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
    }

    .launch-status span {
        min-height: 46px;
        display: flex;
        align-items: center;
        border: 1px solid var(--line);
        background: rgba(2, 8, 4, 0.7);
        color: var(--green-soft);
        padding: 9px 11px;
        font-size: 0.86rem;
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

    .stMultiSelect [data-baseweb="tag"] {
        background:
            linear-gradient(180deg, rgba(6, 24, 11, 0.96), rgba(1, 8, 4, 0.96)) !important;
        border: 1px solid rgba(82, 255, 145, 0.48) !important;
        border-radius: 0 !important;
        color: var(--green-soft) !important;
        box-shadow: inset 0 0 0 1px rgba(157, 255, 193, 0.06);
        min-height: 28px;
    }

    .stMultiSelect [data-baseweb="tag"] span {
        color: var(--green-soft) !important;
        border-radius: 0 !important;
        font-family: "Courier Prime", "Consolas", monospace !important;
        font-size: 0.82rem !important;
    }

    .stMultiSelect [data-baseweb="tag"] span:last-child {
        border-left: 1px solid rgba(255, 77, 77, 0.32) !important;
        background: rgba(255, 77, 77, 0.1) !important;
        color: var(--red) !important;
    }

    div[data-testid="stFileUploader"] button {
        font-size: 0 !important;
    }

    div[data-testid="stFileUploader"] button * {
        font-size: 0 !important;
        line-height: 0 !important;
    }

    div[data-testid="stFileUploader"] button::after {
        content: "导入";
        font-size: 0.95rem;
        line-height: 1;
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
        border-radius: 3px !important;
        min-height: 52px;
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

    .stButton>button[kind="primary"] {
        background:
            linear-gradient(180deg, rgba(6, 24, 11, 0.98), rgba(1, 9, 4, 0.98)) !important;
        color: var(--green-soft) !important;
        border: 1px solid var(--green) !important;
        box-shadow:
            inset 0 0 0 1px rgba(157, 255, 193, 0.1),
            0 0 24px rgba(82, 255, 145, 0.22);
        font-size: 1.04rem;
        text-shadow: 0 0 12px rgba(82, 255, 145, 0.52);
    }

    .stButton>button[kind="primary"]:hover {
        background:
            linear-gradient(180deg, rgba(16, 48, 25, 0.98), rgba(4, 17, 8, 0.98)) !important;
        color: #ffffff !important;
        border-color: var(--green-soft) !important;
        box-shadow:
            inset 0 0 0 1px rgba(157, 255, 193, 0.18),
            0 0 34px rgba(82, 255, 145, 0.34);
    }

    .stButton>button[kind="primary"] p {
        color: var(--green-soft) !important;
        font-weight: 900 !important;
        text-shadow: 0 0 12px rgba(82, 255, 145, 0.52);
    }

    .stButton>button[kind="primary"]:hover p {
        color: #ffffff !important;
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
        background: rgba(4, 12, 7, 0.78) !important;
        border: 1px solid var(--line) !important;
        border-radius: 3px !important;
    }

    section[data-testid="stSidebar"] [data-testid="stExpander"] {
        background: rgba(2, 8, 4, 0.84) !important;
        border-color: rgba(82, 255, 145, 0.22) !important;
    }

    section[data-testid="stSidebar"] .block-container,
    section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.65rem;
    }

    section[data-testid="stSidebar"] label {
        color: var(--green-soft) !important;
        font-size: 0.82rem !important;
    }

    .sidebar-console {
        border: 1px solid rgba(82, 255, 145, 0.38);
        background:
            linear-gradient(135deg, rgba(82, 255, 145, 0.11), transparent 60%),
            rgba(1, 6, 3, 0.72);
        padding: 15px;
        margin: 4px 0 12px;
    }

    .sidebar-title {
        color: var(--green);
        font-size: 1.15rem;
        font-weight: 900;
        margin-top: 3px;
    }

    .sidebar-note {
        color: var(--muted);
        font-size: 0.82rem;
        line-height: 1.5;
        margin-top: 8px;
    }

    .sidebar-help {
        display: grid;
        grid-template-columns: 28px minmax(0, 1fr);
        gap: 10px;
        align-items: start;
        border-top: 1px solid rgba(82, 255, 145, 0.18);
        margin-top: 14px;
        padding-top: 12px;
        color: var(--muted);
    }

    .sidebar-help-badge {
        width: 24px;
        height: 24px;
        display: grid;
        place-items: center;
        border: 1px solid rgba(82, 255, 145, 0.46);
        color: var(--green-soft);
        font-family: "Courier New", monospace;
        font-weight: 900;
    }

    .sidebar-help-title {
        color: var(--green-soft);
        font-size: 0.82rem;
        font-weight: 800;
        margin-bottom: 4px;
    }

    .sidebar-help-copy {
        color: var(--muted);
        font-size: 0.76rem;
        line-height: 1.45;
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
            linear-gradient(rgba(82, 255, 145, 0.04) 1px, transparent 1px),
            linear-gradient(90deg, rgba(82, 255, 145, 0.035) 1px, transparent 1px),
            rgba(2, 5, 3, 0.88);
        background-size: 30px 30px;
        animation: boot-hide 1.55s ease forwards;
        contain: layout paint style;
        will-change: opacity;
    }

    .boot-panel {
        width: min(680px, calc(100vw - 44px));
        border: 1px solid var(--line-hot);
        background: rgba(3, 12, 6, 0.84);
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
        animation: boot-load 0.92s steps(18) forwards;
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
        0%, 46% { opacity: 1; visibility: visible; }
        100% { opacity: 0; visibility: hidden; }
    }

    @media (max-width: 760px) {
        .hero-grid,
        .launch-panel,
        .launch-status {
            grid-template-columns: 1fr;
        }
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
    .launch-panel,
    .terminal-cursor,
    .radar-fill,
    .radar-step::before,
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
    .boot-screen {
        display: none !important;
        opacity: 0 !important;
        visibility: hidden !important;
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
boot_screen = "" if reduce_motion else """
<div class="boot-screen" aria-hidden="true">
    <div class="boot-panel">
        <div class="boot-title">DELTA GREEN TERMINAL</div>
        <div class="boot-lines">
            &gt; 装载档案协议<br>
            &gt; 校验术语索引<br>
            &gt; 建立隔离翻译通道
        </div>
        <div class="boot-bar"></div>
        <div class="boot-stamp">AUTHORIZED ACCESS</div>
    </div>
</div>
"""
st.markdown(f"""
{boot_screen}
<div class="classified-hero">
    <div class="hero-grid">
        <div>
            <div class="hero-title">三角洲翻译终端</div>
            <div class="hero-subtitle">
                > 访问等级：黑色绝密<br>
                > 执行协议：文本提取 / 术语锁定 / 译文编译<br>
                > 终端状态：等待导入档案
            </div>
            <div class="status-radar">
                <div class="radar-row">
                    <span class="radar-label">系统巡检</span>
                    <span class="radar-step">档案通道</span>
                    <span class="radar-step">术语索引</span>
                    <span class="radar-step">输出协议</span>
                </div>
                <div class="radar-track"><span class="radar-fill"></span></div>
            </div>
        </div>
        <div class="hero-seal">
            <div class="hero-seal-code">
                NODE: HK-26<br>
                CHANNEL: PRIVATE REVIEW<br>
                ARCHIVE: LOCAL OUTPUT
            </div>
            <div class="hero-seal-mark">BLACK FILE</div>
        </div>
    </div>
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
    st.markdown(
        """
    <div class="sidebar-console">
    <div class="sidebar-kicker">CONTROL DRAWER</div>
    <div class="sidebar-title">任务参数</div>
    <div class="sidebar-note">参数频道已接入。确认密钥、页码与输出协议后，终端将按当前授权执行档案编译。</div>
</div>
        """,
        unsafe_allow_html=True,
    )

    provider = "deepseek"
    base_url = "https://api.deepseek.com"
    model = "deepseek-v4-pro"
    workers = 32
    rate_limit = 60
    cooldown = 1.0
    max_split_depth = 10
    fuzzy_matching = False
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
    st.caption("开启后会关闭入场遮罩和主要动画，适合远程部署或低性能浏览器。")

    st.caption("必要项")
    api_key = st.text_input("接口密钥", type="password", placeholder="sk-...")

    formats = st.multiselect(
        "输出格式",
        ["markdown", "html", "word", "typeset_pdf"],
        default=["html", "word"],
        format_func=lambda value: OUTPUT_FORMAT_LABELS[value],
    )
    if "typeset_pdf" in formats:
        st.caption("纯重绘 PDF 会单独运行，从 PDF 提取结构后用 HTML/CSS 重建页面并导出。")

    display_start_page = st.number_input("PDF 文件页起始页（从 1 开始）", value=1, min_value=1)
    end_page_str = st.text_input("PDF 文件页结束页（含，从 1 开始）", value="", placeholder="留空表示全部")
    max_blocks_input = st.number_input(
        "翻译块数上限（MD/Word）",
        value=0, min_value=0, step=10,
        help="仅对 Markdown 和 Word 文件生效。0 表示翻译全部。设为如 50 则只翻译前 50 个文本块。"
    )

    with st.expander("高级任务控制", expanded=False):
        base_url = st.text_input("接口地址", value=base_url, placeholder="https://api.deepseek.com")
        model = st.text_input("模型名称", value=model)
        workers = st.slider("并发数", 1, 64, 32, help="并行 API 调用数量")
        rate_limit = st.number_input(
            "速率限制（次/分钟）", value=60, min_value=1, max_value=1000, step=10,
            help="每分钟最大 API 调用次数"
        )
        cooldown = st.slider(
            "批次冷却（秒）", 0.0, 5.0, 1.0, 0.1,
            help="每批次翻译之间的等待时间"
        )
        max_split_depth = st.slider(
            "最大拆分深度", 1, 20, 10,
            help="递归拆分失败组的最大深度"
        )
        fuzzy_matching = st.checkbox(
            "模糊术语匹配", value=False,
            help="启用 OCR 字符替换容错匹配（0↔O, 1↔l↔I, 5↔S, 8↔B）"
        )
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

    # Typeset PDF font configuration
    typeset_font_family = "Noto Serif SC"
    typeset_layout_hints_path = ""
    typeset_auto_layout_hints = False
    typeset_layout_review_provider = "gemini"
    typeset_layout_review_api_key = ""
    typeset_layout_review_base_url = "https://api.openai.com/v1"
    typeset_layout_review_model = "gemini-2.5-flash"
    typeset_layout_review_pages = ""
    if "typeset_pdf" in formats:
        with st.expander("纯重绘排版配置", expanded=False):
            typeset_font_family = st.text_input(
                "中文字体",
                value="Noto Serif SC",
                help="用于纯重绘 PDF 的中文字体。如字体不可用，将自动回退到 Source Han Serif CN 等备选字体。",
            )
            typeset_layout_hints_path = st.text_input(
                "layout_hints.json 路径",
                value="",
                placeholder=r"例如：E:\DG\output\book\layout_hints.json",
                help="可选。填写后，纯重绘 PDF 会按该文件修正阅读顺序、分栏和跳过块。",
            )
            typeset_auto_layout_hints = st.checkbox(
                "自动生成 layout hints",
                value=False,
                help="可选。让多模态模型审稿页面布局，并把结果用于本次纯重绘 PDF。",
            )
            if typeset_auto_layout_hints:
                typeset_layout_review_provider = st.selectbox(
                    "审稿接口",
                    ["gemini", "openai-compatible"],
                    format_func=lambda value: "Gemini 官方接口" if value == "gemini" else "OpenAI 兼容多模态接口",
                )
                typeset_layout_review_api_key = st.text_input(
                    "审稿 API Key",
                    type="password",
                    placeholder="AIza... 或 sk-...",
                )
                if typeset_layout_review_provider == "openai-compatible":
                    typeset_layout_review_base_url = st.text_input(
                        "审稿 Base URL",
                        value=typeset_layout_review_base_url,
                        placeholder="https://api.openai.com/v1",
                    )
                    typeset_layout_review_model = "gpt-4o-mini"
                typeset_layout_review_model = st.text_input(
                    "审稿模型",
                    value=typeset_layout_review_model,
                )
                typeset_layout_review_pages = st.text_input(
                    "审稿页码",
                    value="",
                    placeholder="留空表示本次页码范围；如：1, 3-5",
                    help="从 1 开始，建议先选少量问题页测试。",
                )

    st.markdown(
        """
<div class="sidebar-help">
    <div class="sidebar-help-badge">?</div>
    <div>
        <div class="sidebar-help-title">断点续跑</div>
        <div class="sidebar-help-copy">
            相同文件、术语表、模型和页码会复用进度。中断后用同样设置重新执行即可继续；只补失败页时，在高级任务控制里勾选“只重试失败页”。
        </div>
    </div>
</div>
        """,
        unsafe_allow_html=True,
    )

# === MAIN ===
st.markdown(
    """
<div class="section-card task-dock">
    <div class="section-heading">
        <div>
            <div class="section-kicker">INTAKE BAY</div>
            <div class="section-title">导入机密档案</div>
        </div>
        <div class="section-note">
            上传 PDF、Markdown 或 Word。默认使用本地 glossary.tsv，只有需要替换术语时再上传自定义术语表。
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

col1, col2 = st.columns([1.2, 1])
with col1:
    source_file = st.file_uploader("源文件", type=["pdf", "md", "txt", "docx"], label_visibility="collapsed")
with col2:
    glossary_file = st.file_uploader("替换术语表，可选", type=["tsv", "txt", "csv"], label_visibility="collapsed")
    if glossary_file:
        st.caption(f"将使用上传术语表：{glossary_file.name}")
    elif DEFAULT_GLOSSARY_PATH.exists():
        st.caption("将使用默认术语表：glossary.tsv")
    else:
        st.caption("未找到默认术语表；可上传自定义术语表。")

# Detect file type
pdf_file = None
md_file = None
docx_file = None
source_type = None
if source_file:
    ext = Path(source_file.name).suffix.lower()
    if ext == ".pdf":
        pdf_file = source_file
        source_type = "pdf"
    elif ext in (".md", ".txt"):
        md_file = source_file
        source_type = "markdown"
    elif ext == ".docx":
        docx_file = source_file
        source_type = "docx"

st.markdown("</div>", unsafe_allow_html=True)

if source_file:
    current_digest = uploaded_file_digest(source_file)
    current_dossier_id = make_dossier_id(source_file.name, current_digest)
    glossary_name = glossary_file.name if glossary_file else "glossary.tsv"
    source_type_label = {"pdf": "PDF", "markdown": "Markdown", "docx": "Word"}.get(source_type, "")
    render_dossier_card(
        current_dossier_id,
        f"{source_file.name} [{source_type_label}]",
        current_digest,
        glossary_name=glossary_name,
        loaded=True,
    )
    render_status_flow(active_index=0)
    render_system_log([
        ("info", "档案接收完成"),
        ("info", f"档案号 {current_dossier_id} 已生成"),
        ("info", f"文件类型：{source_type_label}"),
        ("info", "等待执行翻译任务"),
    ])

ready_state = "档案已接收" if source_file else "等待档案"
key_state = "密钥已录入" if api_key else "等待密钥"
format_state = " / ".join(OUTPUT_FORMAT_LABELS[value] for value in formats) if formats else "未选择输出"
st.markdown(
    f"""
<div class="launch-panel">
    <div>
        <div class="launch-kicker">MISSION CONTROL</div>
        <div class="launch-title">启动翻译任务</div>
    </div>
    <div class="launch-status">
        <span>{ready_state}</span>
        <span>{key_state}</span>
        <span>{format_state}</span>
    </div>
</div>
    """,
    unsafe_allow_html=True,
)
launch_pressed = st.button("执行翻译任务", type="primary", use_container_width=True)

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

if launch_pressed:
    if not source_file:
        st.error("✗ 请上传文件（PDF / Markdown / Word）")
    elif not api_key:
        st.error("✗ 请输入接口密钥")
    elif not base_url.strip():
        st.error("✗ 请输入接口地址")
    elif not model.strip():
        st.error("✗ 请输入模型名称")
    elif source_type == "pdf" and not formats:
        st.error("✗ 请至少选择一种输出格式")
    elif source_type == "pdf" and "typeset_pdf" in formats and len(formats) > 1:
        st.error("✗ 纯重绘 PDF 请单独运行，避免和其他输出重复调用接口。")
    elif (
        source_type == "pdf"
        and "typeset_pdf" in formats
        and typeset_auto_layout_hints
        and not typeset_layout_hints_path.strip()
        and not typeset_layout_review_api_key.strip()
    ):
        st.error("✗ 自动生成 layout hints 需要填写审稿 API Key")
    elif source_type in ("markdown", "docx"):
        # ============================================================
        # MARKDOWN / DOCX TRANSLATION FLOW
        # ============================================================
        run_started_at = time.time()
        source_digest = uploaded_file_digest(source_file)
        dossier_id = make_dossier_id(source_file.name, source_digest, created_at=run_started_at)
        source_type_label = "Markdown" if source_type == "markdown" else "Word"
        render_dossier_card(
            dossier_id,
            f"{source_file.name} [{source_type_label}]",
            source_digest,
            glossary_name=glossary_file.name if glossary_file else "glossary.tsv",
            loaded=True,
        )
        render_status_flow(active_index=1)
        render_system_log([
            ("info", "接收档案完成"),
            ("info", f"档案号 {dossier_id}"),
            ("info", f"文件类型：{source_type_label}"),
            ("info", "准备提取文本块"),
        ])

        # Save uploaded files
        upload_dir = APP_DIR / "uploads"
        output_dir = APP_DIR / "output"
        ensure_dir(upload_dir)
        ensure_dir(output_dir)

        file_stem = safe_filename_stem(source_file.name)
        file_ext = Path(source_file.name).suffix.lower()
        upload_name = f"_upload_{file_stem}_{uuid.uuid4().hex[:8]}{file_ext}"
        source_path = str(upload_dir / upload_name)
        with open(source_path, "wb") as f:
            f.write(source_file.getvalue())

        glossary_path = str(DEFAULT_GLOSSARY_PATH) if DEFAULT_GLOSSARY_PATH.exists() else None
        if glossary_file:
            glossary_suffix = Path(glossary_file.name).suffix.lower() or ".tsv"
            glossary_upload_name = f"_upload_{safe_filename_stem(glossary_file.name, 'glossary')}_{uuid.uuid4().hex[:8]}{glossary_suffix}"
            glossary_path = str(upload_dir / glossary_upload_name)
            with open(glossary_path, "wb") as f:
                f.write(glossary_file.getvalue())

        document_output_dir = output_dir / f"{file_stem}_cn"
        ensure_dir(document_output_dir)

        if source_type == "markdown":
            output_path = str(document_output_dir / f"{file_stem}_zh.md")
        else:
            output_path = str(document_output_dir / f"{file_stem}_zh.docx")

        generated_files = []
        audit_path = Path(make_output_path(str(document_output_dir / f"{file_stem}_cn"), "_audit.json"))
        write_audit_record(audit_path, {
            "dossier_id": dossier_id,
            "source_file": source_file.name,
            "source_type": source_type,
            "source_sha256": source_digest,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run_started_at)),
            "finished_at": "",
            "status": "running",
            "model": model,
            "outputs": [],
        })

        # Progress UI
        render_status_flow(active_index=3)
        st.subheader("翻译进度")
        progress_bar = st.progress(0)
        status_text = st.empty()
        metric_cols = st.columns(4)
        progress_metric = metric_cols[0].empty()
        elapsed_metric = metric_cols[1].empty()
        speed_metric = metric_cols[2].empty()
        cost_metric = metric_cols[3].empty()
        translation_started_at = time.time()

        def md_docx_progress_callback(block_idx, text, completed_count, total_count, stats=None):
            pct = completed_count / total_count if total_count else 1.0
            elapsed = time.time() - translation_started_at
            avg_seconds = elapsed / completed_count if completed_count else None
            speed = 60 / avg_seconds if avg_seconds else None
            try:
                progress_bar.progress(min(pct, 1.0), text=f"{completed_count}/{total_count} 块 ({pct * 100:.0f}%)")
            except TypeError:
                progress_bar.progress(min(pct, 1.0))
            status_text.text(f"翻译中: {completed_count}/{total_count} 块")
            progress_metric.metric("进度", f"{completed_count}/{total_count}")
            elapsed_metric.metric("已用时", format_duration(elapsed))
            speed_metric.metric("速度", f"{speed:.1f} 块/分钟" if speed else "估算中")
            cost_metric.metric("费用", f"¥{stats.cost_yuan:.3f}" if stats else "估算中")

        try:
            if source_type == "markdown":
                result = translate_md_file(
                    md_path=source_path,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    glossary_path=glossary_path,
                    output_path=output_path,
                    max_workers=max(1, int(workers)),
                    max_blocks=max_blocks_input if max_blocks_input > 0 else None,
                    progress_callback=md_docx_progress_callback,
                    rate_limit=rate_limit,
                    cooldown=cooldown,
                    max_split_depth=max_split_depth,
                    fuzzy_matching=fuzzy_matching,
                )
            else:
                result = translate_docx_file(
                    docx_path=source_path,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    glossary_path=glossary_path,
                    output_path=output_path,
                    max_workers=max(1, int(workers)),
                    max_blocks=max_blocks_input if max_blocks_input > 0 else None,
                    translate_headers=True,
                    progress_callback=md_docx_progress_callback,
                    rate_limit=rate_limit,
                    cooldown=cooldown,
                    max_split_depth=max_split_depth,
                    fuzzy_matching=fuzzy_matching,
                )

            if result.get("block_count", 0) and not result.get("translated_count", 0):
                failed_count = result.get("failed_count", 0)
                raise RuntimeError(f"没有生成任何译文，失败组数：{failed_count}")

            generated_files.append(result["output_path"])

            # Final progress
            elapsed = time.time() - translation_started_at
            try:
                progress_bar.progress(1.0, text="完成")
            except TypeError:
                progress_bar.progress(1.0)
            status_text.text(f"✓ 翻译完成! 总用时 {format_duration(elapsed)}")

            # Stats
            col_a, col_b = st.columns(2)
            col_a.metric("📄 翻译块数", f"{result['translated_count']}/{result['block_count']}")
            col_b.metric("📁 输出文件", Path(result["output_path"]).name)

            if result.get("stats_summary"):
                with st.expander("Token 统计", expanded=False):
                    st.text(result["stats_summary"])

            # Audit
            write_audit_record(audit_path, {
                "dossier_id": dossier_id,
                "source_file": source_file.name,
                "source_type": source_type,
                "source_sha256": source_digest,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run_started_at)),
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "status": "completed",
                "model": model,
                "block_count": result["block_count"],
                "translated_count": result["translated_count"],
                "failed_count": result.get("failed_count", 0),
                "glossary": Path(glossary_path).name if glossary_path else "",
                "outputs": [Path(p).name for p in existing_output_files(generated_files, final_only=True)],
            })
            generated_files.append(str(audit_path))

            render_status_flow(active_index=5)
            render_completion_stamp("已归档")
            render_audit_grid({
                "档案号": dossier_id,
                "翻译块": result["translated_count"],
                "成品数": len(existing_output_files(generated_files, final_only=True)),
            })
            render_downloads(generated_files)

        except Exception as e:
            st.error(f"翻译过程出错：{e}")
            write_audit_record(audit_path, {
                "dossier_id": dossier_id,
                "source_file": source_file.name,
                "source_type": source_type,
                "source_sha256": source_digest,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run_started_at)),
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "status": "failed",
                "model": model,
                "reason": str(e),
                "outputs": [],
            })
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
        audit_path = Path(make_output_path(output_base, "_audit.json"))
        write_audit_record(audit_path, {
            "dossier_id": dossier_id,
            "source_file": pdf_file.name,
            "source_sha256": source_digest,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run_started_at)),
            "finished_at": "",
            "status": "running",
            "provider": provider,
            "model": model,
            "formats": formats,
            "outputs": [],
        })

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

        if formats == ["typeset_pdf"]:
            # ============================================================
            # TYPESET PDF PIPELINE FLOW
            # ============================================================
            import logging as _logging
            from core.typeset_pipeline import TypesetPipeline
            from core.typeset_models import TypesetConfig

            # Check font availability and set up fallback
            layout_hints_path = typeset_layout_hints_path.strip() or None
            if layout_hints_path and typeset_auto_layout_hints:
                st.warning("已填写 layout_hints.json 路径，本次优先使用该文件，不再自动生成。")
            typeset_config = TypesetConfig(
                font_family=typeset_font_family,
                layout_hints_path=layout_hints_path,
            )
            _font_warning_issued = False

            def _check_font_available(font_name: str) -> bool:
                """Check if a font is likely available on the system."""
                try:
                    from matplotlib.font_manager import findSystemFonts, FontProperties, findfont
                    prop = FontProperties(family=font_name)
                    result = findfont(prop, fallback_to_default=False)
                    return result is not None
                except Exception:
                    # matplotlib not available; skip font check
                    return True

            if not _check_font_available(typeset_font_family):
                # Try fallback fonts
                _fallback_used = None
                for fallback in typeset_config.fallback_fonts:
                    if _check_font_available(fallback):
                        _fallback_used = fallback
                        break
                if _fallback_used:
                    _logging.getLogger(__name__).warning(
                        f"字体 '{typeset_font_family}' 不可用，回退到 '{_fallback_used}'"
                    )
                    st.warning(
                        f"⚠️ 字体 '{typeset_font_family}' 不可用，"
                        f"已回退到 '{_fallback_used}'。"
                    )
                    typeset_config = TypesetConfig(
                        font_family=_fallback_used,
                        layout_hints_path=layout_hints_path,
                    )
                else:
                    _logging.getLogger(__name__).warning(
                        f"字体 '{typeset_font_family}' 及所有备选字体均不可用，将使用默认配置"
                    )
                    st.warning(
                        f"⚠️ 字体 '{typeset_font_family}' 及备选字体均不可用，"
                        "将使用系统默认 serif 字体。"
                    )

            render_status_flow(active_index=1)
            st.info(f"📐 纯重绘管线：第 {start_page + 1}-{end_page} 页")

            # Progress UI for typeset pipeline
            typeset_progress_bar = st.progress(0)
            typeset_status = st.empty()
            typeset_metric_cols = st.columns(5)
            typeset_phase_metric = typeset_metric_cols[0].empty()
            typeset_elapsed_metric = typeset_metric_cols[1].empty()
            typeset_detail_metric = typeset_metric_cols[2].empty()
            typeset_token_metric = typeset_metric_cols[3].empty()
            typeset_cost_metric = typeset_metric_cols[4].empty()
            typeset_started_at = time.time()

            phase_names = {
                "pipeline": "管线",
                "layout_hints": "版面审稿",
                "translation": "翻译",
            }

            def update_typeset_progress(phase: str, done: int, total: int):
                elapsed = time.time() - typeset_started_at
                phase_label = phase_names.get(phase, phase)
                if phase == "pipeline":
                    pct = done / total if total else 1.0
                    phase_desc = ["结构提取", "语义分析", "翻译", "HTML 重建", "PDF 导出"]
                    current_desc = phase_desc[done] if done < len(phase_desc) else "完成"
                    try:
                        typeset_progress_bar.progress(
                            min(pct, 1.0),
                            text=f"阶段 {done}/{total}: {current_desc}",
                        )
                    except TypeError:
                        typeset_progress_bar.progress(min(pct, 1.0))
                    typeset_status.text(f"纯重绘管线：{current_desc}")
                    typeset_phase_metric.metric("阶段", f"{done}/{total}")
                elif phase == "translation":
                    pct = done / total if total else 1.0
                    try:
                        typeset_progress_bar.progress(
                            min(0.4 + pct * 0.2, 1.0),
                            text=f"翻译 {done}/{total} 区域",
                        )
                    except TypeError:
                        typeset_progress_bar.progress(min(0.4 + pct * 0.2, 1.0))
                    typeset_status.text(f"翻译中：{done}/{total} 区域")
                    typeset_phase_metric.metric("翻译区域", f"{done}/{total}")
                else:
                    pct = done / total if total else 1.0
                    try:
                        typeset_progress_bar.progress(
                            min(0.3 + pct * 0.1, 1.0),
                            text=f"{phase_label} {done}/{total}",
                        )
                    except TypeError:
                        typeset_progress_bar.progress(min(0.3 + pct * 0.1, 1.0))
                    typeset_status.text(f"{phase_label}：{done}/{total}")
                    typeset_phase_metric.metric(phase_label, f"{done}/{total}")
                typeset_elapsed_metric.metric("已用时", format_duration(elapsed))
                typeset_detail_metric.metric(
                    "API 调用",
                    f"{stats.api_calls} 次"
                    if not stats.failed_calls
                    else f"{stats.api_calls} 次 / 失败 {stats.failed_calls}",
                )
                typeset_token_metric.metric("Token", f"{stats.total_tokens:,}")
                typeset_cost_metric.metric("费用", f"¥{stats.cost_yuan:.3f}")

            layout_hints_generator = None
            if typeset_auto_layout_hints and not layout_hints_path:
                try:
                    if typeset_layout_review_pages.strip():
                        review_pages = parse_page_selection(typeset_layout_review_pages, total)
                    else:
                        review_pages = set(range(start_page, end_page))
                except ValueError as e:
                    st.error(f"审稿页码格式错误：{e}")
                    extractor.close()
                    st.stop()
                review_pages = sorted(p for p in review_pages if start_page <= p < end_page)
                if not review_pages:
                    st.error("审稿页码不在本次 PDF 页码范围内。")
                    extractor.close()
                    st.stop()

                def layout_hints_generator(structure, content, output_path):
                    from experiments.gemini_layout_review import generate_layout_hints_for_pages

                    st.info(f"正在生成 layout hints：{len(review_pages)} 页")
                    return generate_layout_hints_for_pages(
                        pdf_path=pdf_path,
                        structure=structure,
                        content=content,
                        page_indexes=review_pages,
                        output_path=output_path,
                        api_key=typeset_layout_review_api_key.strip(),
                        model=typeset_layout_review_model.strip(),
                        provider=typeset_layout_review_provider,
                        base_url=typeset_layout_review_base_url.strip() or None,
                        progress_callback=lambda done, total_count, page_index: update_typeset_progress(
                            "layout_hints",
                            done,
                            total_count,
                        ),
                    )

            pipeline = TypesetPipeline(
                pdf_path=pdf_path,
                output_dir=str(document_output_dir),
                translator=translator,
                glossary=glossary,
                config=typeset_config,
                layout_hints_generator=layout_hints_generator,
            )

            result = pipeline.run(
                start_page=start_page,
                end_page=end_page,
                progress_callback=update_typeset_progress,
            )

            # Collect generated files
            if result.pdf_path:
                generated_files.append(result.pdf_path)
            if result.html_path:
                generated_files.append(result.html_path)
                html_bundle_path = make_html_asset_bundle(result.html_path)
                if html_bundle_path:
                    generated_files.append(html_bundle_path)
            if result.page_structure_path:
                generated_files.append(result.page_structure_path)
            if result.page_content_path:
                generated_files.append(result.page_content_path)
            hints_path = document_output_dir / "layout_hints.json"
            hinted_path = document_output_dir / "page_content_hinted.json"
            if hints_path.exists():
                generated_files.append(str(hints_path))
            if hinted_path.exists():
                generated_files.append(str(hinted_path))

            # Report results
            elapsed_total = time.time() - typeset_started_at
            typeset_progress_bar.progress(1.0)
            typeset_status.text(
                "✓ 纯重绘完成! "
                f"总用时 {format_duration(elapsed_total)} | "
                f"Token {result.total_tokens:,} | 费用 ¥{result.cost_yuan:.3f}"
            )

            if result.export_errors:
                st.warning(
                    f"管线完成，但有 {len(result.export_errors)} 个错误：\n"
                    + "\n".join(f"- {e}" for e in result.export_errors[:10])
                )

            render_downloads(generated_files)

            audit_record = {
                "dossier_id": dossier_id,
                "source_file": pdf_file.name,
                "source_sha256": source_digest,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run_started_at)),
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "status": "completed" if not result.export_errors else "completed_with_errors",
                "provider": provider,
                "model": model,
                "page_range": f"{start_page + 1}-{end_page}",
                "formats": formats,
                "completed_pages": result.total_pages,
                "translated_regions": result.translated_regions,
                "failed_regions": result.failed_regions,
                "export_errors": len(result.export_errors),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cached_tokens": result.cached_tokens,
                "total_tokens": result.total_tokens,
                "api_calls": result.api_calls,
                "failed_calls": result.failed_calls,
                "translation_cache_hits": result.translation_cache_hits,
                "cost_yuan": result.cost_yuan,
                "glossary": Path(glossary_path).name if glossary_path else "",
                "font_family": typeset_config.font_family,
                "outputs": [Path(path).name for path in existing_output_files(generated_files, final_only=True)],
            }
            write_audit_record(audit_path, audit_record)
            generated_files.append(str(audit_path))
            render_status_flow(active_index=5, failed=bool(result.export_errors))
            render_completion_stamp("已归档" if not result.export_errors else "待检查")
            render_audit_grid({
                "档案号": dossier_id,
                "总页数": result.total_pages,
                "翻译区域": result.translated_regions,
                "失败区域": result.failed_regions,
                "API 调用": result.api_calls,
                "Token": f"{result.total_tokens:,}",
                "费用": f"¥{result.cost_yuan:.3f}",
                "成品数": len(existing_output_files(generated_files, final_only=True)),
            })
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
        tracker.save()
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
        source_page_labels = {}
        base_page_layouts = {}
        page_diagnostics = []
        for pn in range(start_page, end_page):
            source_page_labels[pn] = extractor.get_page_label(pn)
            base_page_layouts[pn] = extractor.detect_page_layout(pn)
            pages_text[pn] = extractor.extract_page(pn, include_images=False)
            page_diagnostics.append(extractor.get_page_diagnostics(pn, pages_text[pn]))
        layout_context = build_pdf_output_layout_context(
            pdf_path,
            start_page=start_page,
            end_page=end_page,
        )
        page_layouts = merge_output_page_layouts(
            base_page_layouts,
            layout_context.page_layouts,
        )
        for item in page_diagnostics:
            page_index = int(item.get("page", -1))
            item["layout"] = page_layouts.get(page_index, item.get("layout", "unknown"))
            item.setdefault("notes", []).extend(layout_context.notes.get(page_index, []))
        extractor.finalize_chapters()
        toc = extractor.chapter_detector.get_toc_markdown()
        risky_pages = [item for item in page_diagnostics if item.get("risks")]
        if risky_pages:
            st.warning(
                "提取诊断发现风险页："
                + ", ".join(str(item["page"] + 1) for item in risky_pages[:30])
            )
        extraction_log = [
            ("info", f"检测到 {total} 页"),
            ("info", f"本次处理第 {start_page + 1}-{end_page} 页"),
        ]
        if risky_pages:
            extraction_log.append(("warn", f"风险页 {len(risky_pages)} 个"))
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
        for pn in range(start_page, end_page):
            translation = tracker.get_translation(pn)
            if not translation.strip():
                continue
            if looks_untranslated_page(
                pages_text.get(pn, ""),
                translation,
                page_layouts.get(pn, ""),
            ):
                tracker.mark_failed(pn, "页面疑似整页未翻译，已拦截输出")

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
        if not translated_pages_sorted:
            write_audit_record(audit_path, {
                "dossier_id": dossier_id,
                "source_file": pdf_file.name,
                "source_sha256": source_digest,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run_started_at)),
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "status": "failed",
                "provider": provider,
                "model": model,
                "page_range": f"{start_page + 1}-{end_page}",
                "formats": formats,
                "reason": "没有生成任何译文",
                "outputs": [Path(path).name for path in existing_output_files(generated_files, final_only=True)],
            })
            st.error("没有生成任何译文，已停止输出。请检查 API、页码范围、PDF 是否有可提取文本，或查看失败页。")
            extractor.close()
            st.stop()
        if not any(contains_cjk(text) for _, text in translated_pages_sorted):
            write_audit_record(audit_path, {
                "dossier_id": dossier_id,
                "source_file": pdf_file.name,
                "source_sha256": source_digest,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run_started_at)),
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "status": "failed",
                "provider": provider,
                "model": model,
                "page_range": f"{start_page + 1}-{end_page}",
                "formats": formats,
                "reason": "译文没有中文字符",
                "outputs": [Path(path).name for path in existing_output_files(generated_files, final_only=True)],
            })
            st.error("译文没有中文字符，已停止输出，避免产出全英文文件。")
            extractor.close()
            st.stop()

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

        if glossary:
            report_path = make_output_path(output_base, "_glossary_report.md")
            write_glossary_report(pages_text, glossary, report_path, pdf_stem)
            generated_files.append(report_path)

        if "markdown" in formats:
            md_path = make_output_path(output_base, ".md")
            write_markdown_output(
                translated_pages_sorted,
                md_path,
                pdf_stem,
                toc,
                page_layouts=page_layouts,
            )
            generated_files.append(md_path)

        if "html" in formats:
            html_path = make_output_path(output_base, ".html")
            try:
                write_html_output(
                    translated_pages_sorted,
                    html_path,
                    pdf_stem,
                    source_page_labels=source_page_labels,
                    page_layouts=page_layouts,
                )
                generated_files.append(html_path)
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
                    source_page_labels=source_page_labels,
                    page_layouts=page_layouts,
                )
                generated_files.append(docx_path)

        audit_record = {
            "dossier_id": dossier_id,
            "source_file": pdf_file.name,
            "source_sha256": source_digest,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run_started_at)),
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "status": "completed" if not failed_pages else "completed_with_failures",
            "provider": provider,
            "model": model,
            "page_range": f"{start_page + 1}-{end_page}",
            "formats": formats,
            "completed_pages": len(translated_pages_sorted),
            "failed_pages": failed_pages,
            "glossary": Path(glossary_path).name if glossary_path else "",
            "outputs": [Path(path).name for path in existing_output_files(generated_files, final_only=True)],
        }
        write_audit_record(audit_path, audit_record)
        generated_files.append(str(audit_path))
        render_status_flow(active_index=5, failed=bool(failed_pages))
        render_completion_stamp("待校对" if failed_pages else "已归档")
        final_audit_items = {
            "档案号": dossier_id,
            "完成页": len(translated_pages_sorted),
            "成品数": len(existing_output_files(generated_files, final_only=True)),
        }
        if failed_pages:
            final_audit_items["失败页"] = ", ".join(map(str, failed_pages[:12]))
        render_audit_grid(final_audit_items)
        render_downloads(generated_files)
        extractor.close()

with st.expander("档案库", expanded=False):
    render_output_history(APP_DIR / "output")
