#!/usr/bin/env python3
"""
Delta Green PDF Translator — Web UI (Streamlit)
"""
import streamlit as st
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
from webui.theme import render_app_theme, render_workstation_effects

# MD / DOCX translation support
from translate_md import translate_md_file
from translate_docx import translate_docx_file
from core.glossary import build_glossary_matcher
from core.layout_adapters import build_pdf_output_layout_context, merge_output_page_layouts
from core.quality import build_quality_report, write_quality_report
from core.run_report import (
    build_run_effect,
    build_run_manifest,
    write_run_effect_report,
    write_run_manifest,
)
from core.utils import file_sha256, looks_incomplete_translation, looks_untranslated_page
from core.constants import EXTRACTOR_VERSION, PROMPT_VERSION


APP_DIR = Path(__file__).resolve().parent
DEFAULT_GLOSSARY_PATH = APP_DIR / "glossary.tsv"
OUTPUT_FORMAT_LABELS = {
    "markdown": "纯文本稿",
    "html": "网页排版",
    "word": "文档排版",
    "typeset_pdf": "纯重绘 PDF（_typeset）",
}


# === UI THEME ===
st.set_page_config(
    page_title="三角洲翻译终端",
    page_icon="🖧",
    layout="wide",
)

render_app_theme()
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
    workers = 8
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
    requested_quality_retranslate = st.session_state.pop("quality_retranslate_pages", "")
    if requested_quality_retranslate:
        st.session_state["retranslate_pages_input"] = requested_quality_retranslate
        st.session_state["retry_failed_pages_input"] = False
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
        workers = st.slider("并发数", 1, 64, 8, help="并行 API 调用数量")
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
            help="仅 Markdown 和 Word 翻译失败拆分时生效"
        )
        fuzzy_matching = st.checkbox(
            "模糊术语匹配", value=False,
            help="启用 OCR 字符替换容错匹配（0↔O, 1↔l↔I, 5↔S, 8↔B）"
        )
        retranslate_pages_str = st.text_input(
            "重翻页码",
            key="retranslate_pages_input",
            placeholder="如：8, 12-15",
        )
        retry_failed_pages = st.checkbox("只重试失败页", value=False, key="retry_failed_pages_input")
        show_extraction_preview = st.checkbox("显示提取预览", value=False)
        if show_extraction_preview:
            preview_page = st.number_input("预览页（从 1 开始）", value=1, min_value=1)
    if "word" in formats:
        with st.expander("文档档案输出", expanded=False):
            word_body_font_size = st.slider("正文字号", 9.0, 14.0, 12.0, 0.5)
            word_line_spacing = st.slider("正文行距", 1.0, 2.0, 1.5, 0.05)
            word_columns = st.selectbox(
                "正文分栏",
                [1, 2, 3],
                index=1,
                format_func=lambda n: {1: "单栏", 2: "双栏", 3: "三栏"}[n],
            )
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
auto_launch_translation = bool(st.session_state.pop("auto_launch_translation", False))
launch_pressed = st.button("执行翻译任务", type="primary", use_container_width=True) or auto_launch_translation
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
                    from matplotlib.font_manager import FontProperties, findfont
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

            if not playwright_chromium_installed():
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
            else:
                st.caption("浏览器内核已就绪，将直接执行纯重绘 PDF。")

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
        if glossary:
            translator.set_core_glossary(
                select_core_glossary_terms(
                    (pages_text.get(pn, "") for pn in pages_list),
                    glossary,
                    matcher=glossary_matcher,
                )
            )
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
        st.subheader("质量检查")
        qa_cols = st.columns(5)
        qa_cols[0].metric("检查页", quality_report.total_pages)
        qa_cols[1].metric("有译文", quality_report.translated_pages)
        qa_cols[2].metric("失败页", len(quality_report.failed_pages))
        qa_cols[3].metric("待检查", quality_report.warning_count)
        qa_cols[4].metric("术语遗漏", quality_report.glossary_misses)
        if quality_report.issues:
            with st.expander("查看问题页", expanded=True):
                issues_by_page = {}
                for issue in quality_report.issues:
                    issues_by_page.setdefault(issue.page_num, []).append(issue)
                selected_quality_pages = []
                for page_num in quality_report.issue_pages:
                    checked = st.checkbox(
                        f"第 {page_num} 页",
                        value=True,
                        key=f"quality_retry_page_{dossier_id}_{page_num}",
                    )
                    if checked:
                        selected_quality_pages.append(page_num)
                    for issue_index, issue in enumerate(issues_by_page[page_num]):
                        detail = f"；{issue.detail}" if issue.detail else ""
                        st.markdown(f"**{issue.message}{detail}**")
                        left, right = st.columns(2)
                        left.caption("英文原文")
                        left.text_area(
                            f"source_{issue.page_num}_{issue.kind}_{issue_index}",
                            issue.source_excerpt or "无",
                            height=140,
                            label_visibility="collapsed",
                            disabled=True,
                        )
                        right.caption("中文译文")
                        right.text_area(
                            f"translation_{issue.page_num}_{issue.kind}_{issue_index}",
                            issue.translation_excerpt or "无",
                            height=140,
                            label_visibility="collapsed",
                            disabled=True,
                        )
                if st.button("重翻选中的问题页", disabled=not selected_quality_pages):
                    st.session_state["quality_retranslate_pages"] = ", ".join(
                        str(page_num) for page_num in selected_quality_pages
                    )
                    st.session_state["auto_launch_translation"] = True
                    st.rerun()
        else:
            st.success("质量检查未发现明显问题。")

        glossary_candidates = build_glossary_candidates(
            pages_text,
            glossary,
            matcher=glossary_matcher,
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
        col_a.metric("📄 页数", f"{len(translated_pages_sorted)}")
        col_b.metric("💰 费用", f"¥{stats.cost_yuan:.3f}")
        col_c.metric("🔢 Token", f"{stats.total_tokens:,}")

        # Output & Download
        render_status_flow(active_index=4)
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
        if glossary_candidates:
            with open(candidates_tsv_path, "rb") as f:
                st.download_button(
                    "下载术语候选 TSV",
                    f,
                    file_name=Path(candidates_tsv_path).name,
                )

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
            translated_pages=len(translated_pages_sorted),
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
                "completed_pages": len(translated_pages_sorted),
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
            render_status_flow(active_index=4, failed=True)
            st.error("导出失败，已拦住成品。译文进度已保留，可在档案库里点击“重试导出”。")
            render_audit_grid({
                "档案号": dossier_id,
                "完成页": len(translated_pages_sorted),
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
                "completed_pages": len(translated_pages_sorted),
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
