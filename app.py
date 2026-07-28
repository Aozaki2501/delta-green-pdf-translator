#!/usr/bin/env python3
"""
Delta Green PDF Translator — Web UI (Streamlit)
"""
import streamlit as st
import html
import time
from pathlib import Path
from translate_pdf import (
    PDFExtractor, Translator, ProgressTracker, TokenStats,
    load_glossary, translate_batch_concurrent,
    write_markdown_output, write_html_output, write_word_output, HAS_DOCX,
    build_progress_metadata, parse_page_selection, write_glossary_report,
    normalize_page_range, build_extraction_diagnostics_report,
    select_core_glossary_terms, build_glossary_candidates,
    write_glossary_candidate_report, write_glossary_candidate_tsv
)
from webui.components import (
    make_dossier_id,
    render_audit_grid,
    render_completion_stamp,
    render_dossier_card,
    render_output_history,
    reset_runtime_component_slots,
    render_status_flow,
    render_system_log,
)
from webui.history import write_audit_record
from webui.runtime import (
    contains_cjk,
    ensure_dir,
    existing_output_files,
    format_duration,
    install_playwright_chromium,
    make_html_asset_bundle,
    make_output_path,
    playwright_chromium_installed,
    render_downloads,
    safe_filename_stem,
    save_uploaded_file_once,
    save_uploaded_pdf_for_preview,
    uploaded_file_digest,
)
from webui.glossary_review import (
    ACTION_ADD,
    ACTION_IGNORE,
    ACTION_UPDATE,
    glossary_candidates_to_review_rows,
    write_reviewed_glossary,
)
from webui.theme import render_app_theme, render_government_theme_override, render_workstation_effects

# MD / DOCX translation support
from webui.storage_ui import render_storage_manager
from core.pricing import build_pricing, format_cost_yuan
from core.utils import validate_base_url
from translate_md import translate_md_file
from translate_docx import translate_docx_file
from core.md_extractor import MarkdownExtractor
from core.docx_extractor import DocxExtractor
from core.glossary import build_glossary_matcher
from core.layout_adapters import build_pdf_output_layout_context, merge_output_page_layouts
from core.quality import build_quality_report, write_quality_report
from core.run_report import (
    build_run_effect,
    build_run_manifest,
    write_run_effect_report,
    write_run_manifest,
)
from core.output_validation import validate_translation_completeness
from core.risk_workbench import (
    build_risk_workbench_items,
    ignored_risk_pages,
    risk_workbench_rows,
    write_risk_workbench_report,
)
from core.rule_symbols import build_rule_symbol_issues, write_rule_symbol_report
from core.word_review import write_word_review_docx, write_word_review_markdown, build_word_review_items
from core.utils import file_sha256, looks_incomplete_translation, looks_untranslated_page
from core.constants import EXTRACTOR_VERSION, PROMPT_VERSION


APP_DIR = Path(__file__).resolve().parent
DEFAULT_GLOSSARY_PATH = APP_DIR / "glossary.tsv"
OUTPUT_FORMAT_LABELS = {
    "markdown": "纯文本稿",
    "html": "网页排版",
    "word": "文档排版",
    "typeset_html": "高保真 HTML（_typeset）",
    "typeset_reading_html": "图文阅读 HTML（_reading）",
    "typeset_pdf": "纯重绘 PDF（_typeset）",
}
TYPESET_FORMATS = frozenset({"typeset_html", "typeset_reading_html", "typeset_pdf"})


def _typeset_formats_selected(formats) -> bool:
    """Return whether any high-fidelity typeset format was selected."""
    return bool(TYPESET_FORMATS.intersection(formats or ()))


def _typeset_formats_are_exclusive(formats) -> bool:
    """Return whether selected typeset formats are separate from page outputs."""
    selected = set(formats or ())
    return bool(selected & TYPESET_FORMATS) and selected <= TYPESET_FORMATS
office_mode = bool(st.session_state.get("office_mode", False))
dossier_id_prefix = "DOC" if office_mode else "DG"
subject_label = "文件" if office_mode else "档案"
id_label = "任务号" if office_mode else "档案号"


def _extract_texts_for_glossary_review(
    source_type: str,
    source_path: str,
    *,
    start_page: int,
    display_end_page: int | None,
    max_blocks: int,
) -> dict[int, str]:
    if source_type == "pdf":
        extractor = PDFExtractor(source_path)
        try:
            start, end = normalize_page_range(start_page, display_end_page, extractor.total_pages)
            return {
                pn: extractor.extract_page(pn, include_images=False)
                for pn in range(start, end)
            }
        finally:
            extractor.close()

    if source_type == "markdown":
        extractor = MarkdownExtractor(source_path)
        extractor.extract()
        blocks = extractor.get_translatable_blocks()
        if max_blocks > 0:
            blocks = blocks[:max_blocks]
        return {idx: block.text for idx, block in enumerate(blocks)}

    if source_type == "docx":
        extractor = DocxExtractor(source_path, translate_headers=True)
        extractor.extract()
        blocks = extractor.get_translatable_blocks()
        if max_blocks > 0:
            blocks = blocks[:max_blocks]
        return {idx: block.text for idx, block in enumerate(blocks)}

    return {}


def _base_url_error(base_url: str) -> str:
    """Return a user-facing problem with the endpoint, or "" when it is fine."""
    try:
        validate_base_url(base_url)
    except ValueError as exc:
        return str(exc)
    return ""


def _has_review_changes(review_rows: list[dict]) -> bool:
    if review_rows is None:
        return False
    if hasattr(review_rows, "to_dict"):
        rows = review_rows.to_dict("records")
    else:
        rows = review_rows
    return any(
        str(row.get("动作", ACTION_IGNORE) or ACTION_IGNORE).strip() != ACTION_IGNORE
        for row in rows
    )


def _queue_retranslate_pages(page_nums: list[int]) -> None:
    st.session_state["quality_retranslate_pages"] = ", ".join(str(page) for page in page_nums)
    st.session_state["auto_launch_translation"] = True


def _mark_ignored_risk_pages(session_key: str, current_pages: list[int], selected_pages: list[int]) -> None:
    merged = {int(page) for page in current_pages or []}
    merged.update(int(page) for page in selected_pages or [])
    st.session_state[session_key] = sorted(merged)
    st.session_state["auto_launch_translation"] = True


def _clear_ignored_risk_pages(session_key: str) -> None:
    st.session_state[session_key] = []
    st.session_state["auto_launch_translation"] = True


def _render_task_controls(office_mode: bool) -> dict:
    api_key = st.text_input("接口密钥", type="password", placeholder="sk-...", key="api_key_input")
    formats = st.multiselect(
        "输出格式",
        ["markdown", "html", "word", "typeset_html", "typeset_reading_html", "typeset_pdf"],
        default=["html", "word"],
        format_func=lambda value: OUTPUT_FORMAT_LABELS[value],
        key="output_formats_input",
    )
    range_col, limit_col = st.columns([1, 1])
    with range_col:
        display_start_page = st.number_input(
            "PDF 文件页起始页（从 1 开始）", value=1, min_value=1, key="start_page_input"
        )
        end_page_str = st.text_input(
            "PDF 文件页结束页（含，从 1 开始）",
            value="",
            placeholder="留空表示全部",
            key="end_page_input",
        )
    with limit_col:
        max_blocks_input = st.number_input(
            "翻译块数上限（MD/Word）",
            value=0,
            min_value=0,
            step=10,
            help="仅对 Markdown 和 Word 文件生效。0 表示翻译全部。",
            key="max_blocks_input",
        )
        workers = st.slider("并发数", 1, 64, 8, help="并行 API 调用数量", key="workers_input")

    base_url = "https://api.deepseek.com"
    model = "deepseek-v4-pro"
    rate_limit = 60
    cooldown = 1.0
    max_split_depth = 10
    fuzzy_matching = False
    retranslate_pages_str = ""
    retry_failed_pages = False
    show_review_workbench = False
    show_extraction_preview = False
    preview_page = 1
    with st.expander("高级任务控制", expanded=False):
        base_url = st.text_input("接口地址", value=base_url, key="base_url_input")
        model = st.text_input("模型名称", value=model, key="model_input")
        rate_limit = st.number_input(
            "速率限制（次/分钟）", value=60, min_value=1, max_value=1000, step=10, key="rate_limit_input"
        )
        cooldown = st.slider("批次冷却（秒）", 0.0, 5.0, 1.0, 0.1, key="cooldown_input")
        max_split_depth = st.slider("最大拆分深度", 1, 20, 10, key="split_depth_input")
        fuzzy_matching = st.checkbox("模糊术语匹配", value=False, key="fuzzy_matching_input")
        st.caption(
            "费用单价（可选）。留空或 0 表示不显示金额，只显示 Token 与调用次数。"
            "单价按上面填写的接口地址生效，换接口后请重新填写。"
        )
        price_cols = st.columns(3)
        price_input_per_m = price_cols[0].number_input(
            "输入 ¥/百万 token", value=0.0, min_value=0.0, step=0.1,
            format="%.3f", key="price_input_per_m",
        )
        price_output_per_m = price_cols[1].number_input(
            "输出 ¥/百万 token", value=0.0, min_value=0.0, step=0.1,
            format="%.3f", key="price_output_per_m",
        )
        price_cached_per_m = price_cols[2].number_input(
            "缓存 ¥/百万 token", value=0.0, min_value=0.0, step=0.1,
            format="%.3f", key="price_cached_per_m",
        )
        retranslate_pages_str = st.text_input(
            "重翻页码", key="retranslate_pages_input", placeholder="如：8, 12-15"
        )
        retry_failed_pages = st.checkbox("只重试失败页", value=False, key="retry_failed_pages_input")
        show_review_workbench = st.checkbox(
            "显示翻译后校对区", value=False, key="show_review_workbench_input"
        )
        show_extraction_preview = st.checkbox("显示提取预览", value=False, key="show_extraction_preview_input")
        if show_extraction_preview:
            preview_page = st.number_input("预览页（从 1 开始）", value=1, min_value=1, key="preview_page_input")

    word_body_font_size = 12.0
    word_line_spacing = 1.5
    word_columns = 2
    word_min_chars = 1000
    word_max_chars = 1500
    word_hard_page_breaks = False
    word_header_left = "绿色三角洲"
    word_header_right = ""
    if "word" in formats:
        with st.expander("文档输出设置" if office_mode else "文档档案输出", expanded=False):
            word_body_font_size = st.slider("正文字号", 9.0, 14.0, 12.0, 0.5, key="word_font_size_input")
            word_line_spacing = st.slider("正文行距", 1.0, 2.0, 1.5, 0.05, key="word_spacing_input")
            word_columns = st.selectbox(
                "正文分栏",
                [1, 2, 3],
                index=1,
                format_func=lambda n: {1: "单栏", 2: "双栏", 3: "三栏"}[n],
                key="word_columns_input",
            )
            word_min_chars = st.number_input(
                "阅读页最少字数", value=1000, min_value=300, max_value=3000, step=100, key="word_min_chars_input"
            )
            word_max_chars = st.number_input(
                "阅读页最多字数", value=1500, min_value=500, max_value=5000, step=100, key="word_max_chars_input"
            )
            word_hard_page_breaks = st.checkbox(
                "按阅读页强制分页", value=False, key="word_page_breaks_input"
            )
            word_header_left = st.text_input("页眉左侧", value="绿色三角洲", key="word_header_left_input")
            word_header_right = st.text_input(
                "页眉右侧", value="", placeholder="留空则使用文件名", key="word_header_right_input"
            )

    typeset_font_family = "DG Fandol Song"
    typeset_layout_hints_path = ""
    typeset_auto_layout_hints = False
    typeset_layout_review_provider = "gemini"
    typeset_layout_review_api_key = ""
    typeset_layout_review_base_url = "https://api.openai.com/v1"
    typeset_layout_review_model = "gemini-2.5-flash"
    typeset_layout_review_pages = ""
    if _typeset_formats_selected(formats):
        with st.expander("图文重绘排版配置", expanded=False):
            typeset_font_family = st.text_input("中文字体", value=typeset_font_family, key="typeset_font_input")
            typeset_layout_hints_path = st.text_input(
                "layout_hints.json 路径", value="", key="typeset_hints_input"
            )
            typeset_auto_layout_hints = st.checkbox(
                "自动生成 layout hints", value=False, key="typeset_auto_hints_input"
            )
            if typeset_auto_layout_hints:
                typeset_layout_review_provider = st.selectbox(
                    "审稿接口", ["gemini", "openai-compatible"], key="typeset_review_provider_input"
                )
                typeset_layout_review_api_key = st.text_input(
                    "审稿 API Key", type="password", key="typeset_review_key_input"
                )
                if typeset_layout_review_provider == "openai-compatible":
                    typeset_layout_review_base_url = st.text_input(
                        "审稿 Base URL", value=typeset_layout_review_base_url, key="typeset_review_url_input"
                    )
                    typeset_layout_review_model = "gpt-4o-mini"
                typeset_layout_review_model = st.text_input(
                    "审稿模型", value=typeset_layout_review_model, key="typeset_review_model_input"
                )
                typeset_layout_review_pages = st.text_input("审稿页码", value="", key="typeset_review_pages_input")

    return locals()


# === UI THEME ===
st.set_page_config(
    page_title="文档翻译工作台" if office_mode else "GREENFILE · 文件净化系统",
    page_icon="📄" if office_mode else "△",
    layout="wide",
)

render_app_theme(office_mode=office_mode)
reduce_motion = bool(st.session_state.get("reduce_motion", False)) or office_mode
try:
    render_workstation_effects(reduced_motion=reduce_motion, office_mode=office_mode)
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
if office_mode:
    st.markdown(
        """
<style>
    div[data-testid="stAlert"] {
        border-radius: 8px !important;
        border: 1px solid var(--line) !important;
        background: #ffffff !important;
        box-shadow: none !important;
    }
    div[data-testid="stAlert"] > div,
    div[data-testid="stAlert"] [data-testid="stMarkdownContainer"],
    div[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {
        background: transparent !important;
        color: var(--text) !important;
    }
    div[data-testid="stAlert"]::before {
        background: var(--green) !important;
    }
</style>
        """,
        unsafe_allow_html=True,
    )
else:
    render_government_theme_override()

# === HEADER ===
if office_mode:
    st.markdown(
        """
<div class="classified-hero">
    <div class="hero-grid">
        <div>
            <div class="hero-title">文档翻译工作台</div>
            <div class="hero-subtitle">
                上传 PDF、Markdown 或 Word，确认术语后生成网页、文档或纯文本稿。
            </div>
            <div class="status-radar">
                <div class="radar-row">
                    <span class="radar-label">当前流程</span>
                    <span class="radar-step">导入文件</span>
                    <span class="radar-step">确认术语</span>
                    <span class="radar-step">生成输出</span>
                </div>
            </div>
        </div>
        <div class="hero-seal">
            <div class="hero-seal-code">
                WORKSPACE: LOCAL<br>
                MODE: OFFICE<br>
                OUTPUT: HTML / WORD / MARKDOWN
            </div>
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
        <div class="intel-value">办公</div>
    </div>
</div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown("""
<div class="classification-strip">
    <span>TOP SECRET // GREEN</span>
    <span>AUTHORIZED PERSONNEL ONLY</span>
    <span>COMPARTMENT NIGHT GREEN</span>
</div>
<div class="workbench-topbar">
    <div>
        <div class="hero-kicker">DOCUMENT SANITIZATION DIRECTORATE · NODE 07</div>
        <div class="workbench-title">新建档案</div>
    </div>
    <div class="sealed-storage"><span></span>本地密封存储</div>
</div>
<div class="workbench-stepper" aria-label="任务流程">
    <a class="workbench-step active" href="#case-intake">
        <b>1</b><span><strong>上传文件</strong><small>选择翻译资料</small></span>
    </a>
    <a class="workbench-step" href="#range-output">
        <b>2</b><span><strong>范围与输出</strong><small>确认处理方式</small></span>
    </a>
    <a class="workbench-step" href="#term-review">
        <b>3</b><span><strong>术语确认</strong><small>锁定专名译法</small></span>
    </a>
    <a class="workbench-step" href="#operation-control">
        <b>4</b><span><strong>执行与校对</strong><small>检查并生成输出</small></span>
    </a>
</div>
<div class="workbench-brief">
    <div>
        <strong>高密级 TRPG 翻译与文件净化系统</strong>
        <span>接收档案、锁定术语、检查规则数据并生成可校对译文。</span>
    </div>
    <span class="clearance-chip">HANDLER · LEVEL 4</span>
</div>
""", unsafe_allow_html=True)
provider = "deepseek"
base_url = "https://api.deepseek.com"
model = "deepseek-v4-pro"
workers = 8
rate_limit = 60
cooldown = 1.0
max_split_depth = 10
fuzzy_matching = False
retranslate_pages_str = ""
retry_failed_pages = False
reuse_mismatched_progress = False
show_review_workbench = False
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
typeset_font_family = "DG Fandol Song"
typeset_layout_hints_path = ""
typeset_auto_layout_hints = False
typeset_layout_review_provider = "gemini"
typeset_layout_review_api_key = ""
typeset_layout_review_base_url = "https://api.openai.com/v1"
typeset_layout_review_model = "gemini-2.5-flash"
typeset_layout_review_pages = ""
requested_quality_retranslate = st.session_state.pop("quality_retranslate_pages", "")
if requested_quality_retranslate:
    st.session_state["retranslate_pages_input"] = requested_quality_retranslate
    st.session_state["retry_failed_pages_input"] = False

with st.sidebar:
    uplink_authorized = bool(st.session_state.get("api_key_input", ""))
    uplink_label = "加密链路正常" if uplink_authorized else "加密链路待授权"
    sidebar_brand = "" if office_mode else """
<div class="sidebar-brand">
    <div class="sidebar-brand-mark">△</div>
    <div><strong>GREENFILE</strong><small>LINGUISTIC OPERATIONS</small></div>
</div>
<nav class="workspace-nav" aria-label="工作区导航">
    <a class="active" href="#case-intake"><b>＋</b><span>新建档案<small>CASE INTAKE</small></span></a>
    <a href="#operation-control"><b>◌</b><span>执行队列<small>ACTIVE OPS</small></span></a>
    <a href="#risk-review"><b>✓</b><span>风险校对<small>REVIEW QUEUE</small></span></a>
    <a href="#secure-archive"><b>▤</b><span>封存档案<small>SECURE ARCHIVE</small></span></a>
</nav>
"""
    st.markdown(
        f"""
{sidebar_brand}
<div class="connection-card">
    <div class="sidebar-kicker">SECURE UPLINK</div>
    <div class="connection-status"><i></i><strong>DeepSeek</strong></div>
    <span>V4 Pro · {uplink_label}</span>
    <small>接口密钥在“范围与输出”中设置</small>
</div>
        """,
        unsafe_allow_html=True,
    )
    st.toggle("办公界面", value=False, key="office_mode")

# === MAIN ===
main_kicker = "UPLOAD" if office_mode else "CASE INTAKE"
main_title = "导入文件" if office_mode else "导入机密档案"
main_note = (
    "上传 PDF、Markdown 或 Word。默认使用本地 glossary.tsv，需要替换术语时再上传自定义术语表。"
    if office_mode
    else "上传 PDF、Markdown 或 Word。默认使用本地 glossary.tsv，只有需要替换术语时再上传自定义术语表。"
)
if office_mode:
    st.markdown(
        f"""
<div class="section-card task-dock">
    <div class="section-heading">
        <div>
            <div class="section-kicker">{main_kicker}</div>
            <div class="section-title">{main_title}</div>
        </div>
        <div class="section-note">{main_note}</div>
    </div>
        """,
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns([1.2, 1])
    with col1:
        source_file = st.file_uploader(
            "源文件", type=["pdf", "md", "txt", "docx"], label_visibility="collapsed"
        )
    with col2:
        glossary_file = st.file_uploader(
            "替换术语表，可选", type=["tsv", "txt", "csv"], label_visibility="collapsed"
        )
        if glossary_file:
            st.caption(f"将使用上传术语表：{glossary_file.name}")
        elif DEFAULT_GLOSSARY_PATH.exists():
            st.caption("将使用默认术语表：glossary.tsv")
        else:
            st.caption("未找到默认术语表；可上传自定义术语表。")
    with st.expander("范围与输出", expanded=True):
        controls = _render_task_controls(office_mode=True)
else:
    workspace_col, summary_col = st.columns([3.2, 1], gap="medium")
    with workspace_col:
        with st.container(border=True):
            st.markdown(
                f"""
<div class="workspace-section-heading" id="case-intake">
    <div><span>{main_kicker}</span><strong>{main_title}</strong></div>
    <p>{main_note}</p>
</div>
                """,
                unsafe_allow_html=True,
            )
            source_col, glossary_col = st.columns([1.2, 1])
            with source_col:
                st.markdown('<div class="upload-label">源档案</div>', unsafe_allow_html=True)
                source_file = st.file_uploader(
                    "源文件",
                    type=["pdf", "md", "txt", "docx"],
                    label_visibility="collapsed",
                    key="source_file_input",
                )
            with glossary_col:
                st.markdown('<div class="upload-label">替换术语表 <small>可选</small></div>', unsafe_allow_html=True)
                glossary_file = st.file_uploader(
                    "替换术语表，可选",
                    type=["tsv", "txt", "csv"],
                    label_visibility="collapsed",
                    key="glossary_file_input",
                )
                if glossary_file:
                    st.caption(f"使用上传术语表：{glossary_file.name}")
                elif DEFAULT_GLOSSARY_PATH.exists():
                    st.caption("默认术语表：glossary.tsv")
                else:
                    st.caption("未找到默认术语表")
            st.markdown('<span id="range-output"></span>', unsafe_allow_html=True)
            with st.expander("第二步 · 范围与输出", expanded=False):
                st.caption("接口、处理范围和输出格式都在这里设置；高级选项默认收起。")
                controls = _render_task_controls(office_mode=False)

    source_display = html.escape(source_file.name) if source_file else "等待接收"
    range_display = f"{controls['display_start_page']} - {controls['end_page_str'] or '全部'}"
    format_display = " / ".join(OUTPUT_FORMAT_LABELS[value] for value in controls["formats"]) or "未选择"
    with summary_col:
        st.markdown(
            f"""
<aside class="task-summary-panel">
    <div class="task-summary-kicker">CASE CONTROL</div>
    <h3>{source_display}</h3>
    <div class="summary-classification">TOP SECRET<br><small>NEW CASE / PENDING ID</small></div>
    <dl>
        <div><dt>来源</dt><dd>{'已载入' if source_file else '等待档案'}</dd></div>
        <div><dt>范围</dt><dd>{range_display}</dd></div>
        <div><dt>输出</dt><dd>{format_display}</dd></div>
        <div><dt>术语</dt><dd>{'自定义' if glossary_file else '默认表'}</dd></div>
        <div><dt>模型</dt><dd>{html.escape(controls['model'])}</dd></div>
        <div><dt>并发</dt><dd>{controls['workers']} 个任务</dd></div>
    </dl>
    <div class="summary-note"><strong>内容说明</strong><p>原文件和结果保存在本机；正文会发送到当前翻译接口。</p></div>
</aside>
            """,
            unsafe_allow_html=True,
        )

api_key = controls["api_key"]
formats = controls["formats"]
display_start_page = controls["display_start_page"]
end_page_str = controls["end_page_str"]
max_blocks_input = controls["max_blocks_input"]
base_url = controls["base_url"]
model = controls["model"]
workers = controls["workers"]
rate_limit = controls["rate_limit"]
cooldown = controls["cooldown"]
max_split_depth = controls["max_split_depth"]
fuzzy_matching = controls["fuzzy_matching"]
pricing_config = {
    "base_url": controls["base_url"],
    "input_per_m": controls.get("price_input_per_m", 0.0),
    "output_per_m": controls.get("price_output_per_m", 0.0),
    "cached_per_m": controls.get("price_cached_per_m", 0.0),
}
retranslate_pages_str = controls["retranslate_pages_str"]
retry_failed_pages = controls["retry_failed_pages"]
show_review_workbench = controls["show_review_workbench"]
show_extraction_preview = controls["show_extraction_preview"]
preview_page = controls["preview_page"]
word_body_font_size = controls["word_body_font_size"]
word_line_spacing = controls["word_line_spacing"]
word_columns = controls["word_columns"]
word_min_chars = controls["word_min_chars"]
word_max_chars = controls["word_max_chars"]
word_hard_page_breaks = controls["word_hard_page_breaks"]
word_header_left = controls["word_header_left"]
word_header_right = controls["word_header_right"]
typeset_font_family = controls["typeset_font_family"]
typeset_layout_hints_path = controls["typeset_layout_hints_path"]
typeset_auto_layout_hints = controls["typeset_auto_layout_hints"]
typeset_layout_review_provider = controls["typeset_layout_review_provider"]
typeset_layout_review_api_key = controls["typeset_layout_review_api_key"]
typeset_layout_review_base_url = controls["typeset_layout_review_base_url"]
typeset_layout_review_model = controls["typeset_layout_review_model"]
typeset_layout_review_pages = controls["typeset_layout_review_pages"]

# Detect file type
pdf_file = None
md_file = None
docx_file = None
source_type = None
reset_runtime_component_slots()
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

if office_mode:
    st.markdown("</div>", unsafe_allow_html=True)

if source_file:
    current_digest = uploaded_file_digest(source_file)
    current_dossier_id = make_dossier_id(source_file.name, current_digest, prefix=dossier_id_prefix)
    glossary_name = glossary_file.name if glossary_file else "glossary.tsv"
    source_type_label = {"pdf": "PDF", "markdown": "Markdown", "docx": "Word"}.get(source_type, "")
    render_dossier_card(
        current_dossier_id,
        f"{source_file.name} [{source_type_label}]",
        current_digest,
        glossary_name=glossary_name,
        loaded=True,
        office_mode=office_mode,
    )
    render_status_flow(active_index=0, office_mode=office_mode)
    render_system_log([
        ("info", f"{subject_label}接收完成"),
        ("info", f"{id_label} {current_dossier_id} 已生成"),
        ("info", f"文件类型：{source_type_label}"),
        ("info", "等待执行翻译任务"),
    ], office_mode=office_mode)

glossary_review_rows = []
glossary_review_error = ""
if source_file and source_type:
    st.markdown('<span id="term-review"></span>', unsafe_allow_html=True)
    st.subheader("翻译前术语确认")
    st.caption("先检查疑似专名。需要本次翻译强制使用的词，选择“新增”或“修改”；不需要的保持“忽略”。")
    review_loading = st.empty()
    review_loading.markdown(
        """
<div class="term-scan-status" role="status">
    <span class="term-scan-indicator" aria-hidden="true"></span>
    <div><span>CASE INTAKE</span><strong>正在接收档案并扫描术语…</strong></div>
</div>
        """,
        unsafe_allow_html=True,
    )
    try:
        review_upload_dir = APP_DIR / "uploads"
        ensure_dir(review_upload_dir)
        review_source_path = str(save_uploaded_file_once(source_file, review_upload_dir))
        review_glossary_path = str(DEFAULT_GLOSSARY_PATH) if DEFAULT_GLOSSARY_PATH.exists() else None
        review_glossary_digest = "none"
        if glossary_file:
            review_glossary_path = str(save_uploaded_file_once(glossary_file, review_upload_dir, "glossary"))
            review_glossary_digest = uploaded_file_digest(glossary_file)
        elif review_glossary_path:
            review_glossary_digest = file_sha256(review_glossary_path)

        try:
            review_start_page = int(display_start_page) - 1
            review_end_page = int(end_page_str) if end_page_str.strip() else None
        except ValueError:
            raise ValueError("结束页必须是整数，或留空表示全部。")

        review_glossary = load_glossary(review_glossary_path) if review_glossary_path else {}
        review_matcher = (
            build_glossary_matcher(review_glossary, fuzzy=bool(fuzzy_matching))
            if review_glossary else None
        )
        review_texts = _extract_texts_for_glossary_review(
            source_type,
            review_source_path,
            start_page=review_start_page,
            display_end_page=review_end_page,
            max_blocks=int(max_blocks_input),
        )
        review_candidates = build_glossary_candidates(
            review_texts,
            review_glossary,
            matcher=review_matcher,
        )
        review_rows = glossary_candidates_to_review_rows(review_candidates)
        if not review_rows:
            st.info("没有发现高频疑似未收录专名。仍可手动新增一行术语。")
            review_rows = [
                {"动作": ACTION_IGNORE, "中文译名": "", "英文原名": "", "出现次数": "", "位置": ""}
            ]
        review_key = (
            f"glossary_review_{current_digest[:12]}_{review_glossary_digest[:12]}_"
            f"{source_type}_{display_start_page}_{end_page_str}_{max_blocks_input}_{int(bool(fuzzy_matching))}"
        )
        glossary_review_rows = st.data_editor(
            review_rows,
            key=review_key,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            disabled=["出现次数", "位置"],
            column_config={
                "动作": st.column_config.SelectboxColumn(
                    "动作",
                    options=[ACTION_IGNORE, ACTION_ADD, ACTION_UPDATE],
                    required=True,
                ),
                "中文译名": st.column_config.TextColumn("中文译名"),
                "英文原名": st.column_config.TextColumn("英文原名"),
            },
        )
        st.caption(f"已扫描 {len(review_texts)} 个文本单元，找到 {len(review_candidates)} 个候选。")
    except Exception as e:
        glossary_review_error = str(e)
        st.error(f"术语候选扫描失败：{e}")
    finally:
        review_loading.empty()

ready_state = f"{subject_label}已接收" if source_file else f"等待{subject_label}"
key_state = "密钥已录入" if api_key else "等待密钥"
format_state = " / ".join(OUTPUT_FORMAT_LABELS[value] for value in formats) if formats else "未选择输出"
launch_kicker = "TASK" if office_mode else "OPERATION CONTROL"
if office_mode:
    st.markdown(
        f"""
<div class="launch-panel" id="operation-control">
    <div>
        <div class="launch-kicker">{launch_kicker}</div>
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
else:
    readiness_class = "ready" if source_file and api_key and formats else "pending"
    st.markdown(
        f"""
<section class="preflight-panel" id="operation-control">
    <div class="preflight-heading">
        <div><span>第四步 · PREFLIGHT</span><strong>提取预检与任务启动</strong></div>
        <b class="preflight-state {readiness_class}">{'可以开始' if readiness_class == 'ready' else '等待必要项'}</b>
    </div>
    <div class="preflight-grid">
        <div><small>档案状态</small><strong>{ready_state}</strong><span>支持 PDF / Word / Markdown</span></div>
        <div><small>接口授权</small><strong>{key_state}</strong><span>{html.escape(model)}</span></div>
        <div><small>输出协议</small><strong>{format_state}</strong><span>{workers} 个并发任务</span></div>
    </div>
    <div class="preflight-notice"><b>!</b><span>复杂版面、规则数值和术语冲突会在完成后自动加入风险校对。</span></div>
</section>
        """,
        unsafe_allow_html=True,
    )
auto_launch_translation = bool(st.session_state.pop("auto_launch_translation", False))
if office_mode:
    launch_pressed = st.button("执行翻译任务", type="primary", use_container_width=True) or auto_launch_translation
else:
    st.markdown('<div class="launch-action-separator" aria-hidden="true"></div>', unsafe_allow_html=True)
    action_spacer, action_button = st.columns([3, 1])
    with action_button:
        launch_pressed = st.button("开始翻译任务", type="primary", use_container_width=True) or auto_launch_translation
if auto_launch_translation:
    st.info("已从质量检查选择问题页，开始重翻。")

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
    elif glossary_review_error:
        st.error(f"✗ 术语候选扫描失败，请先处理：{glossary_review_error}")
    elif not api_key:
        st.error("✗ 请输入接口密钥")
    elif _base_url_error(base_url):
        st.error(f"✗ {_base_url_error(base_url)}")
    elif not model.strip():
        st.error("✗ 请输入模型名称")
    elif source_type == "pdf" and not formats:
        st.error("✗ 请至少选择一种输出格式")
    elif source_type == "pdf" and _typeset_formats_selected(formats) and not _typeset_formats_are_exclusive(formats):
        st.error("✗ 图文重绘请单独运行，避免和普通输出重复调用接口。")
    elif source_type != "pdf" and _typeset_formats_selected(formats):
        st.error("✗ 图文重绘仅支持 PDF 文件。")
    elif (
        source_type == "pdf"
        and _typeset_formats_selected(formats)
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
        dossier_id = make_dossier_id(
            source_file.name,
            source_digest,
            created_at=run_started_at,
            prefix=dossier_id_prefix,
        )
        source_type_label = "Markdown" if source_type == "markdown" else "Word"
        render_dossier_card(
            dossier_id,
            f"{source_file.name} [{source_type_label}]",
            source_digest,
            glossary_name=glossary_file.name if glossary_file else "glossary.tsv",
            loaded=True,
            office_mode=office_mode,
        )
        render_status_flow(active_index=1, office_mode=office_mode)
        render_system_log([
            ("info", f"接收{subject_label}完成"),
            ("info", f"{id_label} {dossier_id}"),
            ("info", f"文件类型：{source_type_label}"),
            ("info", "准备提取文本块"),
        ], office_mode=office_mode)

        # Save uploaded files
        upload_dir = APP_DIR / "uploads"
        output_dir = APP_DIR / "output"
        ensure_dir(upload_dir)
        ensure_dir(output_dir)

        file_stem = safe_filename_stem(source_file.name)
        source_path = str(save_uploaded_file_once(source_file, upload_dir))

        glossary_path = str(DEFAULT_GLOSSARY_PATH) if DEFAULT_GLOSSARY_PATH.exists() else None
        if glossary_file:
            glossary_path = str(save_uploaded_file_once(glossary_file, upload_dir, "glossary"))

        document_output_dir = output_dir / f"{file_stem}_cn"
        ensure_dir(document_output_dir)

        if source_type == "markdown":
            output_path = str(document_output_dir / f"{file_stem}_zh.md")
        else:
            output_path = str(document_output_dir / f"{file_stem}_zh.docx")

        if _has_review_changes(glossary_review_rows):
            try:
                base_glossary = load_glossary(glossary_path) if glossary_path else {}
                reviewed_glossary_path = document_output_dir / f"{file_stem}_reviewed_glossary.tsv"
                reviewed_glossary = write_reviewed_glossary(
                    base_glossary,
                    glossary_review_rows,
                    reviewed_glossary_path,
                )
                glossary_path = str(reviewed_glossary_path)
                st.info(f"已生成本次临时术语表：{len(reviewed_glossary)} 条")
            except ValueError as e:
                st.error(f"术语审核表有误：{e}")
                st.stop()

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
        render_status_flow(active_index=3, office_mode=office_mode)
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
            cost_metric.metric(
                "费用",
                format_cost_yuan(stats.cost_yuan) if stats else "估算中",
            )

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
                    pricing=pricing_config,
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
                    pricing=pricing_config,
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

            render_status_flow(active_index=5, office_mode=office_mode)
            render_completion_stamp("已归档")
            render_audit_grid({
                id_label: dossier_id,
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
        dossier_id = make_dossier_id(
            pdf_file.name,
            source_digest,
            created_at=run_started_at,
            prefix=dossier_id_prefix,
        )
        render_dossier_card(
            dossier_id,
            pdf_file.name,
            source_digest,
            glossary_name=glossary_file.name if glossary_file else "glossary.tsv",
            loaded=True,
            office_mode=office_mode,
        )
        render_status_flow(active_index=1, office_mode=office_mode)
        render_system_log([
            ("info", f"接收{subject_label}完成"),
            ("info", f"{id_label} {dossier_id}"),
            ("info", "准备提取文本"),
        ], office_mode=office_mode)

        # Create organized directories
        upload_dir = APP_DIR / "uploads"
        output_dir = APP_DIR / "output"
        ensure_dir(upload_dir)
        ensure_dir(output_dir)

        # Save uploaded files to uploads/
        pdf_stem = safe_filename_stem(pdf_file.name)
        pdf_path = str(save_uploaded_file_once(pdf_file, upload_dir))

        glossary_path = str(DEFAULT_GLOSSARY_PATH) if DEFAULT_GLOSSARY_PATH.exists() else None
        if glossary_file:
            glossary_path = str(save_uploaded_file_once(glossary_file, upload_dir, "glossary"))

        try:
            start_page = int(display_start_page) - 1
            display_end_page = int(end_page_str) if end_page_str.strip() else None
        except ValueError:
            st.error("结束页必须是整数，或留空表示全部。")
            st.stop()
        document_output_dir = output_dir / f"{pdf_stem}_cn"
        ensure_dir(document_output_dir)
        output_base = str(document_output_dir / f"{pdf_stem}_cn")
        if _has_review_changes(glossary_review_rows):
            try:
                base_glossary = load_glossary(glossary_path) if glossary_path else {}
                reviewed_glossary_path = document_output_dir / f"{pdf_stem}_reviewed_glossary.tsv"
                reviewed_glossary = write_reviewed_glossary(
                    base_glossary,
                    glossary_review_rows,
                    reviewed_glossary_path,
                )
                glossary_path = str(reviewed_glossary_path)
                st.info(f"已生成本次临时术语表：{len(reviewed_glossary)} 条")
            except ValueError as e:
                st.error(f"术语审核表有误：{e}")
                st.stop()
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
        stats = TokenStats(pricing=build_pricing(pricing_config, base_url))
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
        glossary_matcher = (
            build_glossary_matcher(glossary, fuzzy=bool(fuzzy_matching))
            if glossary else None
        )
        translator = Translator(
            api_key=api_key,
            model=model,
            base_url=base_url,
            stats=stats,
            glossary_matcher=glossary_matcher,
        )
        translator.set_glossary(glossary)

        if _typeset_formats_selected(formats):
            # ============================================================
            # HIGH-FIDELITY TYPESET PIPELINE FLOW
            # ============================================================
            import logging as _logging
            from core.typeset_pipeline import TypesetPipeline
            from core.typeset_models import TypesetConfig

            # Check font availability and set up fallback
            layout_hints_path = typeset_layout_hints_path.strip() or None
            if layout_hints_path and typeset_auto_layout_hints:
                st.warning("已填写 layout_hints.json 路径，本次优先使用该文件，不再自动生成。")
            typeset_config = TypesetConfig(
                document_title=Path(pdf_file.name).stem,
                font_family=typeset_font_family,
                layout_hints_path=layout_hints_path,
            )
            _font_warning_issued = False

            def _check_font_available(font_name: str) -> bool:
                """Check if a font is likely available on the system."""
                try:
                    from matplotlib.font_manager import FontProperties, findfont
                    prop = FontProperties(family=font_name)
                    result = findfont(prop, fallback_to_default=False)
                    return result is not None
                except Exception:
                    # matplotlib not available; skip font check
                    return True

            embedded_typeset_fonts = {
                "DG Fandol Song",
                "DG Fandol Kai",
                "DG Lanting Kanhei",
                "DG Moushi Meili",
                "DG Noto Serif SC",
                "DG Noto Sans SC",
            }
            if (
                typeset_font_family not in embedded_typeset_fonts
                and not _check_font_available(typeset_font_family)
            ):
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
                        document_title=Path(pdf_file.name).stem,
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

            export_pdf = "typeset_pdf" in formats
            export_typeset_html = "typeset_html" in formats
            export_reading_html = "typeset_reading_html" in formats
            if export_pdf and not playwright_chromium_installed():
                st.warning("本次导出纯重绘 PDF 需要先加载浏览器内核插件。")
                browser_progress_bar = st.progress(0)
                browser_status = st.empty()
                browser_log = st.empty()
                browser_progress_state = {"value": 0.02}
                browser_log_lines = []

                def update_browser_install_progress(message: str, percent: int | None):
                    browser_log_lines.append(message)
                    del browser_log_lines[:-12]
                    if percent is not None:
                        browser_progress_state["value"] = max(
                            browser_progress_state["value"],
                            min(percent / 100, 0.99),
                        )
                    else:
                        browser_progress_state["value"] = min(
                            browser_progress_state["value"] + 0.06,
                            0.9,
                        )
                    try:
                        browser_progress_bar.progress(
                            browser_progress_state["value"],
                            text=f"浏览器内核加载中 {int(browser_progress_state['value'] * 100)}%",
                        )
                    except TypeError:
                        browser_progress_bar.progress(browser_progress_state["value"])
                    browser_status.info(message)
                    browser_log.markdown(
                        "```text\n" + "\n".join(browser_log_lines) + "\n```"
                    )

                install_ok, _ = install_playwright_chromium(
                    progress_callback=update_browser_install_progress,
                )
                if not install_ok:
                    browser_status.error("浏览器内核插件加载失败，已停止本次纯重绘 PDF 导出。")
                    st.code(
                        r".\.venv\Scripts\python.exe -m playwright install chromium",
                        language="powershell",
                    )
                    extractor.close()
                    st.stop()
                try:
                    browser_progress_bar.progress(1.0, text="浏览器内核加载完成")
                except TypeError:
                    browser_progress_bar.progress(1.0)
                browser_status.success("浏览器内核插件已就绪，开始执行纯重绘 PDF。")
            elif export_pdf:
                st.caption("浏览器内核已就绪，将直接执行纯重绘 PDF。")
            else:
                st.caption("仅生成高保真 HTML，不加载浏览器内核。")

            render_status_flow(active_index=1, office_mode=office_mode)
            st.info(f"📐 图文重绘管线：第 {start_page + 1}-{end_page} 页")

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
                    phase_desc = ["结构提取", "语义分析", "翻译", "HTML 重建"]
                    if export_pdf:
                        phase_desc.append("PDF 导出")
                    current_desc = phase_desc[done] if done < len(phase_desc) else "完成"
                    try:
                        typeset_progress_bar.progress(
                            min(pct, 1.0),
                            text=f"阶段 {done}/{total}: {current_desc}",
                        )
                    except TypeError:
                        typeset_progress_bar.progress(min(pct, 1.0))
                    typeset_status.text(f"图文重绘管线：{current_desc}")
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
                typeset_cost_metric.metric("费用", format_cost_yuan(stats.cost_yuan))

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
                export_pdf=export_pdf,
                export_typeset_html=export_typeset_html,
                export_reading_html=export_reading_html,
            )

            # Collect generated files
            if result.pdf_path:
                generated_files.append(result.pdf_path)
            if result.html_path:
                generated_files.append(result.html_path)
                html_bundle_path = make_html_asset_bundle(
                    result.html_path,
                    referenced_only=True,
                )
                if html_bundle_path:
                    generated_files.append(html_bundle_path)
            if result.reading_html_path:
                generated_files.append(result.reading_html_path)
                reading_bundle_path = make_html_asset_bundle(
                    result.reading_html_path,
                    referenced_only=True,
                )
                if reading_bundle_path:
                    generated_files.append(reading_bundle_path)
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
                "✓ 图文重绘完成! "
                f"总用时 {format_duration(elapsed_total)} | "
                f"Token {result.total_tokens:,} | 费用 {format_cost_yuan(result.cost_yuan)}"
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
            render_status_flow(active_index=5, failed=bool(result.export_errors), office_mode=office_mode)
            render_completion_stamp("已归档" if not result.export_errors else "待检查")
            render_audit_grid({
                id_label: dossier_id,
                "总页数": result.total_pages,
                "翻译区域": result.translated_regions,
                "失败区域": result.failed_regions,
                "API 调用": result.api_calls,
                "Token": f"{result.total_tokens:,}",
                "费用": format_cost_yuan(result.cost_yuan),
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
            fuzzy_matching=fuzzy_matching,
        )
        tracker = ProgressTracker(
            progress_file,
            expected_metadata=progress_metadata,
            reuse_mismatched=reuse_mismatched_progress,
        )
        tracker.save()
        if tracker.progress_corrupted:
            st.error(
                f"原 progress.json 无法解析，已备份为 {Path(tracker.corrupt_backup_path).name}，"
                "本次会整本重译并重新计费。"
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
            pages_filter = failed_from_progress | retranslate_pages
            if pages_filter:
                tracker.clear_failed_pages(pages_filter)
                st.info(
                    "本次重试页："
                    + ", ".join(str(p + 1) for p in sorted(pages_filter))
                )
            else:
                pages_filter = set()
                st.warning("没有可重试的失败页。")
        else:
            pages_filter = set(range(start_page, end_page))

        # Extract
        render_status_flow(active_index=1, office_mode=office_mode)
        st.info(f"📑 提取文本: {total} 页, 翻译第 {start_page + 1}-{end_page} 页")
        pages_text = {}
        page_contexts = {}
        source_page_labels = {}
        base_page_layouts = {}
        page_diagnostics = []
        for pn in range(start_page, end_page):
            source_page_labels[pn] = extractor.get_page_label(pn)
            base_page_layouts[pn] = extractor.detect_page_layout(pn)
            pages_text[pn] = extractor.extract_page(pn, include_images=False)
            page_contexts[pn] = extractor.get_context_text(pn)
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
        render_system_log(extraction_log, office_mode=office_mode)

        # Translate
        render_status_flow(active_index=3, office_mode=office_mode)
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
        if glossary:
            translator.set_core_glossary(
                select_core_glossary_terms(
                    (pages_text.get(pn, "") for pn in pages_list),
                    glossary,
                    matcher=glossary_matcher,
                )
            )
        pages_data = []
        for pn in pages_list:
            text = pages_text.get(pn, "")
            prev_context = page_contexts.get(pn - 1, "")
            next_context = page_contexts.get(pn + 1, "")
            pages_data.append((
                pn,
                text,
                prev_context[-900:] if prev_context else "",
                next_context[:900] if next_context else "",
            ))

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
                f"费用 {format_cost_yuan(stats.cost_yuan)}"
            )
            progress_metric.metric("进度", f"{completed_count}/{total_count}")
            elapsed_metric.metric("已用时", format_duration(elapsed))
            eta_metric.metric("预计剩余", format_duration(remaining_seconds))
            speed_metric.metric("速度", f"{speed:.1f} 页/分钟" if speed else "估算中")
            cost_metric.metric("费用", format_cost_yuan(stats.cost_yuan))

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
                rate_limit=rate_limit,
                cooldown=cooldown,
            )
        else:
            results = {}

        render_progress(total_to_do, total_to_do)
        status_text.text(f"✓ 翻译完成! 总用时 {format_duration(time.time() - translation_started_at)}")
        for pn in range(start_page, end_page):
            translation = tracker.get_translation(pn)
            if not translation.strip():
                continue
            source_text = pages_text.get(pn, "")
            page_layout = page_layouts.get(pn, "")
            if looks_untranslated_page(
                source_text,
                translation,
                page_layout,
            ):
                tracker.delete_cached_prompt_translations_by_value(translation)
                tracker.mark_failed(pn, "页面疑似整页未翻译，已拦截输出")
                continue
            if looks_incomplete_translation(source_text, translation, page_layout):
                tracker.delete_cached_prompt_translations_by_value(translation)
                tracker.mark_failed(pn, "页面译文明显短于原文，疑似截断，已拦截输出")

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
        completeness = validate_translation_completeness(
            pages_text=pages_text,
            translated_pages=translated_pages_sorted,
            failed_page_indexes=tracker.get_failed_pages(),
            start_page=start_page,
            end_page=end_page,
        )
        if failed_pages:
            render_status_flow(active_index=3, failed=True, office_mode=office_mode)
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

        quality_report = build_quality_report(
            pages_text={pn: pages_text.get(pn, "") for pn in range(start_page, end_page)},
            translations={
                pn: tracker.get_translation(pn)
                for pn in range(start_page, end_page)
                if tracker.get_translation(pn).strip()
            },
            page_layouts=page_layouts,
            glossary=glossary,
            glossary_matcher=glossary_matcher,
            failed_reasons={
                pn: tracker.failed_pages.get(str(pn), "")
                for pn in tracker.get_failed_pages()
                if start_page <= pn < end_page
            },
            title=f"{pdf_stem} — 质量检查报告",
        )
        rule_symbol_issues = build_rule_symbol_issues(
            pages_text={pn: pages_text.get(pn, "") for pn in range(start_page, end_page)},
            translations={
                pn: tracker.get_translation(pn)
                for pn in range(start_page, end_page)
                if tracker.get_translation(pn).strip()
            },
        )
        risk_workbench_items = build_risk_workbench_items(quality_report, page_diagnostics)
        risk_ignored_key = f"risk_ignored_pages_{dossier_id}"
        risk_ignored_pages = {
            int(page) for page in st.session_state.get(risk_ignored_key, [])
        }
        active_risk_items = ignored_risk_pages(risk_workbench_items, risk_ignored_pages)

        glossary_candidates = build_glossary_candidates(
            pages_text,
            glossary,
            matcher=glossary_matcher,
        )
        if show_review_workbench:
            st.subheader("质量检查")
            qa_cols = st.columns(5)
            qa_cols[0].metric("检查页", quality_report.total_pages)
            qa_cols[1].metric("有译文", quality_report.translated_pages)
            qa_cols[2].metric("失败页", len(quality_report.failed_pages))
            qa_cols[3].metric("待检查", quality_report.warning_count)
            qa_cols[4].metric("术语遗漏", quality_report.glossary_misses)

            st.subheader("规则符号检查")
            if rule_symbol_issues:
                rule_cols = st.columns(3)
                rule_cols[0].metric("问题数", len(rule_symbol_issues))
                rule_cols[1].metric("涉及页数", len({issue.page_num for issue in rule_symbol_issues}))
                rule_cols[2].metric("技能残留", sum(1 for issue in rule_symbol_issues if issue.kind == "技能残留"))
                st.dataframe(
                    [
                        {
                            "页码": issue.page_num,
                            "类型": issue.kind,
                            "符号": issue.symbol,
                            "问题": issue.message,
                        }
                        for issue in rule_symbol_issues[:80]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.success("规则符号检查未发现明显问题。")

            st.markdown('<span id="risk-review"></span>', unsafe_allow_html=True)
            st.subheader("失败页/风险页工作台")
            risk_cols = st.columns(4)
            risk_cols[0].metric("风险条目", len(active_risk_items))
            risk_cols[1].metric("涉及页数", len({item.page_num for item in active_risk_items}))
            risk_cols[2].metric("可重翻页", len({item.page_num for item in active_risk_items if item.retryable}))
            risk_cols[3].metric("已忽略页", len(risk_ignored_pages))
            if active_risk_items:
                st.dataframe(
                    risk_workbench_rows(active_risk_items),
                    use_container_width=True,
                    hide_index=True,
                )
                risk_page_options = sorted({item.page_num for item in active_risk_items})
                retry_default_pages = sorted({item.page_num for item in active_risk_items if item.retryable})
                selected_risk_pages = st.multiselect(
                    "选择要处理的页",
                    options=risk_page_options,
                    default=retry_default_pages,
                    key=f"risk_workbench_pages_{dossier_id}",
                )
                retry_pages = sorted(
                    {
                        item.page_num
                        for item in active_risk_items
                        if item.page_num in selected_risk_pages and item.retryable
                    }
                )
                risk_actions = st.columns(3)
                risk_actions[0].button(
                    "重翻选中页",
                    disabled=not retry_pages,
                    on_click=_queue_retranslate_pages,
                    args=(retry_pages,),
                )
                risk_actions[1].button(
                    "标记忽略",
                    disabled=not selected_risk_pages,
                    on_click=_mark_ignored_risk_pages,
                    args=(risk_ignored_key, sorted(risk_ignored_pages), selected_risk_pages),
                )
                risk_actions[2].button(
                    "清除忽略",
                    disabled=not risk_ignored_pages,
                    on_click=_clear_ignored_risk_pages,
                    args=(risk_ignored_key,),
                )
            else:
                st.success("没有需要集中处理的失败页或风险页。")

            if quality_report.issues:
                with st.expander("问题详情", expanded=bool(active_risk_items)):
                    issues_by_page = {}
                    for issue in quality_report.issues:
                        if issue.page_num in risk_ignored_pages:
                            continue
                        issues_by_page.setdefault(issue.page_num, []).append(issue)
                    for page_num in sorted(issues_by_page):
                        st.markdown(f"**第 {page_num} 页**")
                        for issue_index, issue in enumerate(issues_by_page[page_num]):
                            detail = f"；{issue.detail}" if issue.detail else ""
                            st.markdown(f"**{issue.message}{detail}**")
                            left, right = st.columns(2)
                            left.caption("英文原文")
                            left.text_area(
                                f"source_{issue.page_num}_{issue.kind}_{issue_index}_{dossier_id}",
                                issue.source_excerpt or "无",
                                height=140,
                                label_visibility="collapsed",
                                disabled=True,
                            )
                            right.caption("中文译文")
                            right.text_area(
                                f"translation_{issue.page_num}_{issue.kind}_{issue_index}_{dossier_id}",
                                issue.translation_excerpt or "无",
                                height=140,
                                label_visibility="collapsed",
                                disabled=True,
                            )

            st.subheader("术语候选")
            if glossary_candidates:
                st.dataframe(
                    [
                        {
                            "英文候选": row.term,
                            "出现次数": row.count,
                            "页数": len(row.pages),
                        }
                        for row in glossary_candidates[:30]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("没有发现高频疑似未收录专名。")

        # Stats
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("📄 页数", f"{completeness.translated_pages}")
        col_b.metric("💰 费用", format_cost_yuan(stats.cost_yuan))
        col_c.metric("🔢 Token", f"{stats.total_tokens:,}")

        # Output & Download
        render_status_flow(active_index=4, office_mode=office_mode)
        output_options = {
            "markdown_min_chars": 1000,
            "markdown_max_chars": 1500,
            "html_min_chars": 1200,
            "html_max_chars": 1800,
            "word_min_chars": int(word_min_chars),
            "word_max_chars": int(word_max_chars),
            "columns": int(word_columns),
            "body_font_size": float(word_body_font_size),
            "line_spacing": float(word_line_spacing),
            "header_left": word_header_left,
            "header_right": word_header_right or None,
            "word_hard_page_breaks": bool(word_hard_page_breaks),
        }
        diagnostics_path = make_output_path(output_base, "_extraction_report.md")
        with open(diagnostics_path, "w", encoding="utf-8") as f:
            f.write(build_extraction_diagnostics_report(page_diagnostics, pdf_stem))
            f.write("\n")
        generated_files.append(diagnostics_path)

        quality_path = make_output_path(output_base, "_quality_report.md")
        write_quality_report(quality_report, quality_path)
        generated_files.append(quality_path)

        if show_review_workbench:
            risk_workbench_path = make_output_path(output_base, "_risk_workbench.md")
            write_risk_workbench_report(active_risk_items, risk_workbench_path, pdf_stem)
            generated_files.append(risk_workbench_path)

            rule_symbol_path = make_output_path(output_base, "_rule_symbols.md")
            write_rule_symbol_report(rule_symbol_issues, rule_symbol_path, pdf_stem)
            generated_files.append(rule_symbol_path)

        if glossary:
            report_path = make_output_path(output_base, "_glossary_report.md")
            write_glossary_report(pages_text, glossary, report_path, pdf_stem)
            generated_files.append(report_path)

        candidates_report_path = make_output_path(output_base, "_glossary_candidates.md")
        write_glossary_candidate_report(glossary_candidates, candidates_report_path, pdf_stem)
        generated_files.append(candidates_report_path)
        candidates_tsv_path = make_output_path(output_base, "_glossary_candidates.tsv")
        write_glossary_candidate_tsv(glossary_candidates, candidates_tsv_path)
        generated_files.append(candidates_tsv_path)
        if show_review_workbench and glossary_candidates:
            with open(candidates_tsv_path, "rb") as f:
                st.download_button(
                    "下载术语候选 TSV",
                    f,
                    file_name=Path(candidates_tsv_path).name,
                )

        if show_review_workbench:
            word_review_items = build_word_review_items(
                quality_report=quality_report,
                glossary_candidates=glossary_candidates,
                rule_symbol_issues=rule_symbol_issues,
                timeline_events=[],
            )
            word_review_md_path = make_output_path(output_base, "_word_review.md")
            write_word_review_markdown(word_review_items, word_review_md_path, pdf_stem)
            generated_files.append(word_review_md_path)
            if HAS_DOCX:
                word_review_docx_path = make_output_path(output_base, "_word_review.docx")
                write_word_review_docx(word_review_items, word_review_docx_path, pdf_stem)
                generated_files.append(word_review_docx_path)
            st.subheader("Word 校对包")
            st.metric("校对项", len(word_review_items))

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

        export_errors = []
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
                export_errors.append(f"网页排版输出失败：{e}")

        if "word" in formats:
            if not HAS_DOCX:
                export_errors.append("文档排版需要 python-docx")
            else:
                docx_path = make_output_path(output_base, ".docx")
                try:
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
                except Exception as e:
                    export_errors.append(f"文档排版输出失败：{e}")

        final_output_names = [
            Path(path).name
            for path in existing_output_files(generated_files, final_only=True)
        ]
        internal_report_names = [
            Path(path).name
            for path in existing_output_files(generated_files)
            if Path(path).name not in final_output_names
        ]
        run_effect = build_run_effect(
            stats,
            total_pages=end_page - start_page,
            translated_pages=completeness.translated_pages,
            failed_pages=failed_pages,
            quality_issues=quality_report.warning_count,
            glossary_candidates=len(glossary_candidates),
            elapsed_seconds=time.time() - translation_started_at,
        )
        run_report_path = make_output_path(output_base, "_run_report.md")
        write_run_effect_report(run_effect, run_report_path, pdf_stem)
        generated_files.append(run_report_path)
        internal_report_names.append(Path(run_report_path).name)
        manifest_path = make_output_path(output_base, "_manifest.json")
        write_run_manifest(
            build_run_manifest(
                source_file=pdf_file.name,
                source_sha256=source_digest,
                provider=provider,
                model=model,
                page_range=f"{start_page + 1}-{end_page}",
                formats=formats,
                prompt_version=PROMPT_VERSION,
                extractor_version=EXTRACTOR_VERSION,
                glossary_name=Path(glossary_path).name if glossary_path else "",
                glossary_sha256=file_sha256(glossary_path) if glossary_path else "",
                status="export_failed" if export_errors else (
                    "completed_with_failures" if failed_pages else "completed"
                ),
                effect=run_effect,
                output_files=final_output_names,
                internal_reports=internal_report_names,
                quality_report=Path(quality_path).name,
                run_report=Path(run_report_path).name,
            ),
            manifest_path,
        )
        generated_files.append(manifest_path)
        st.subheader("效果报告")
        effect_cols = st.columns(5)
        effect_cols[0].metric("缓存命中率", f"{run_effect['cache_hit_rate']:.1%}")
        effect_cols[1].metric("API 调用", run_effect["api_calls"])
        effect_cols[2].metric("API 失败", run_effect["failed_calls"])
        effect_cols[3].metric("平均每页", f"¥{run_effect['cost_per_page']:.3f}")
        effect_cols[4].metric("本地缓存", run_effect["translation_cache_hits"])

        if export_errors:
            audit_record = {
                "dossier_id": dossier_id,
                "source_file": pdf_file.name,
                "source_path": pdf_path,
                "source_sha256": source_digest,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run_started_at)),
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "status": "export_failed",
                "provider": provider,
                "model": model,
                "page_range": f"{start_page + 1}-{end_page}",
                "formats": formats,
                "completed_pages": completeness.translated_pages,
                "failed_pages": failed_pages,
                "glossary": Path(glossary_path).name if glossary_path else "",
                "progress_path": progress_file,
                "output_base": output_base,
                "output_options": output_options,
                "retryable_export": True,
                "export_errors": export_errors,
                "quality_issues": quality_report.warning_count,
                "quality_report": Path(quality_path).name,
                "glossary_candidates": len(glossary_candidates),
                "glossary_candidate_report": Path(candidates_report_path).name,
                "run_report": Path(run_report_path).name,
                "manifest": Path(manifest_path).name,
                "outputs": [],
            }
            write_audit_record(audit_path, audit_record)
            generated_files.append(str(audit_path))
            render_status_flow(active_index=4, failed=True, office_mode=office_mode)
            history_label = "历史输出" if office_mode else "档案库"
            st.error(f"导出失败，已拦住成品。译文进度已保留，可在{history_label}里点击“重试导出”。")
            render_audit_grid({
                id_label: dossier_id,
                "完成页": completeness.translated_pages,
                "导出错误": len(export_errors),
            })
            for message in export_errors[:5]:
                st.error(message)
            extractor.close()
        else:
            audit_record = {
                "dossier_id": dossier_id,
                "source_file": pdf_file.name,
                "source_path": pdf_path,
                "source_sha256": source_digest,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run_started_at)),
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "status": "completed" if not failed_pages else "completed_with_failures",
                "provider": provider,
                "model": model,
                "page_range": f"{start_page + 1}-{end_page}",
                "formats": formats,
                "completed_pages": completeness.translated_pages,
                "failed_pages": failed_pages,
                "glossary": Path(glossary_path).name if glossary_path else "",
                "progress_path": progress_file,
                "output_base": output_base,
                "output_options": output_options,
                "retryable_export": False,
                "export_errors": [],
                "quality_issues": quality_report.warning_count,
                "quality_report": Path(quality_path).name,
                "glossary_candidates": len(glossary_candidates),
                "glossary_candidate_report": Path(candidates_report_path).name,
                "run_report": Path(run_report_path).name,
                "manifest": Path(manifest_path).name,
                "outputs": [Path(path).name for path in existing_output_files(generated_files, final_only=True)],
            }
            write_audit_record(audit_path, audit_record)
            generated_files.append(str(audit_path))
            render_status_flow(active_index=5, failed=bool(failed_pages), office_mode=office_mode)
            render_completion_stamp("待校对" if failed_pages else "已归档")
            final_audit_items = {
                id_label: dossier_id,
                "完成页": completeness.translated_pages,
                "成品数": len(existing_output_files(generated_files, final_only=True)),
            }
            if failed_pages:
                final_audit_items["失败页"] = ", ".join(map(str, failed_pages[:12]))
            render_audit_grid(final_audit_items)
            render_downloads(generated_files)
            extractor.close()

if not office_mode:
    st.markdown('<span id="secure-archive"></span>', unsafe_allow_html=True)
with st.expander("历史输出" if office_mode else "档案库", expanded=False):
    render_output_history(APP_DIR / "output", office_mode=office_mode)

with st.expander("存储管理" if office_mode else "存储清理", expanded=False):
    render_storage_manager(APP_DIR / "uploads", APP_DIR / "output")
