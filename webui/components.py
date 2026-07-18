"""Reusable Streamlit components for the classified workstation UI."""

from __future__ import annotations

import hashlib
import html
import time
from pathlib import Path
from typing import Any

import streamlit as st

from webui.history import (
    collect_output_history,
    format_file_size,
    format_file_time,
    history_file_label,
    is_final_output_file,
    write_audit_record,
)


STATUS_STEPS = ("接收档案", "提取文本", "匹配术语", "编译译文", "生成输出", "归档完成")
OFFICE_STATUS_STEPS = ("接收文件", "提取文本", "匹配术语", "编译译文", "生成输出", "完成")
RUNTIME_SLOT_KEYS = ("_dg_dossier_slot", "_dg_status_flow_slot", "_dg_system_log_slot")


def reset_runtime_component_slots() -> None:
    """Start a fresh set of update-in-place runtime panels for this rerun."""
    for key in RUNTIME_SLOT_KEYS:
        st.session_state.pop(key, None)


def _runtime_slot(key: str):
    slot = st.session_state.get(key)
    if slot is None:
        slot = st.empty()
        st.session_state[key] = slot
    return slot


def _retryable_formats(audit: dict[str, Any]) -> list[str]:
    raw_formats = audit.get("formats", [])
    if isinstance(raw_formats, str):
        raw_formats = [raw_formats]
    if not isinstance(raw_formats, list):
        return []
    return [
        str(item)
        for item in raw_formats
        if str(item) in {"markdown", "html", "word"}
    ]


def _can_retry_export(audit: dict[str, Any]) -> bool:
    return (
        audit.get("status") == "export_failed"
        and bool(audit.get("retryable_export"))
        and bool(audit.get("progress_path"))
        and bool(_retryable_formats(audit))
    )


def _retry_export_from_audit(entry: dict[str, Any]) -> list[str]:
    audit = entry.get("audit", {})
    audit_path = entry.get("audit_path")
    if not audit_path:
        raise ValueError("审计记录缺少路径，不能重试导出")

    progress_path = Path(str(audit.get("progress_path", "")))
    if not progress_path.exists():
        raise FileNotFoundError(f"进度文件不存在：{progress_path}")

    output_options = audit.get("output_options", {})
    if not isinstance(output_options, dict):
        output_options = {}

    from rerender_output import rerender_selected_outputs

    written = rerender_selected_outputs(
        progress_path=str(progress_path),
        output_base=audit.get("output_base") or None,
        pdf_path=audit.get("source_path") or None,
        output_formats=_retryable_formats(audit),
        title=Path(str(audit.get("source_file") or entry.get("title") or "document")).stem,
        markdown_min_chars=int(output_options.get("markdown_min_chars", 1000)),
        markdown_max_chars=int(output_options.get("markdown_max_chars", 1500)),
        html_min_chars=int(output_options.get("html_min_chars", 1200)),
        html_max_chars=int(output_options.get("html_max_chars", 1800)),
        word_min_chars=int(output_options.get("word_min_chars", 1000)),
        word_max_chars=int(output_options.get("word_max_chars", 1500)),
        columns=int(output_options.get("columns", 2)),
        body_font_size=float(output_options.get("body_font_size", 12.0)),
        line_spacing=float(output_options.get("line_spacing", 1.5)),
        header_left=str(output_options.get("header_left", "绿色三角洲")),
        header_right=output_options.get("header_right") or None,
        word_hard_page_breaks=bool(output_options.get("word_hard_page_breaks", False)),
    )

    updated = dict(audit)
    updated["status"] = "completed"
    updated["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    updated["retryable_export"] = False
    updated["export_errors"] = []
    updated["outputs"] = [Path(path).name for path in written]
    write_audit_record(Path(audit_path), updated)
    return written


def make_dossier_id(
    filename: str,
    file_digest: str,
    created_at: float | None = None,
    prefix: str = "DG",
) -> str:
    timestamp = time.strftime("%Y%m%d-%H%M", time.localtime(created_at or time.time()))
    seed = f"{filename}:{file_digest}".encode("utf-8")
    suffix = hashlib.sha256(seed).hexdigest()[:6].upper()
    clean_prefix = prefix.strip().upper() if prefix and prefix.strip() else "DG"
    return f"{clean_prefix}-{timestamp}-{suffix}"


def render_dossier_card(dossier_id: str, filename: str, file_digest: str,
                        glossary_name: str = "", loaded: bool = False,
                        office_mode: bool = False) -> None:
    state_class = " loaded" if loaded else ""
    digest = file_digest[:12].upper() if file_digest else "待接收"
    glossary = glossary_name or "默认术语表"
    kicker = "DOCUMENT" if office_mode else "CLASSIFIED DOSSIER"
    status_label = "状态：待校对" if office_mode else "密级：绝密 / 待校对"
    _runtime_slot("_dg_dossier_slot").markdown(
        f"""
<div class="dossier-card{state_class}">
    <div class="dossier-identity">
        <div class="dossier-kicker">{kicker}</div>
        <div class="dossier-id">{html.escape(dossier_id)}</div>
    </div>
    <div class="dossier-meta">
        <span>文件：{html.escape(filename or "待导入")}</span>
        <span>校验：{html.escape(digest)}</span>
        <span>术语：{html.escape(glossary)}</span>
        <span>{html.escape(status_label)}</span>
    </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_status_flow(active_index: int = 0, failed: bool = False, office_mode: bool = False) -> None:
    steps = OFFICE_STATUS_STEPS if office_mode else STATUS_STEPS
    parts = ['<div class="status-flow">']
    for idx, label in enumerate(steps):
        if failed and idx == active_index:
            state = "failed"
        elif idx < active_index:
            state = "done"
        elif idx == active_index:
            state = "active"
        else:
            state = ""
        parts.append(f'<div class="status-step {state}">{html.escape(label)}</div>')
    parts.append("</div>")
    _runtime_slot("_dg_status_flow_slot").markdown("\n".join(parts), unsafe_allow_html=True)


def render_system_log(lines: list[tuple[str, str]], office_mode: bool = False) -> None:
    prefix = ""
    parts = ['<div class="system-log">']
    for level, text in lines:
        safe_level = level if level in {"warn", "fail"} else ""
        parts.append(f'<div class="system-log-line {safe_level}">{prefix}{html.escape(text)}</div>')
    parts.append("</div>")
    _runtime_slot("_dg_system_log_slot").markdown("\n".join(parts), unsafe_allow_html=True)


def render_completion_stamp(text: str = "已归档") -> None:
    st.markdown(f'<div class="archive-stamp">{html.escape(text)}</div>', unsafe_allow_html=True)


def render_audit_grid(items: dict[str, Any]) -> None:
    parts = ['<div class="audit-grid">']
    for label, value in items.items():
        parts.append(
            '<div class="audit-cell">'
            f'<div class="audit-label">{html.escape(str(label))}</div>'
            f'<div class="audit-value">{html.escape(str(value))}</div>'
            '</div>'
        )
    parts.append("</div>")
    st.markdown("\n".join(parts), unsafe_allow_html=True)


def render_output_history(output_dir: Path, limit: int = 8, office_mode: bool = False) -> None:
    history_entries = collect_output_history(output_dir, limit=limit)
    if history_entries:
        section_kicker = "HISTORY" if office_mode else "ARCHIVE VAULT"
        section_title = "历史输出" if office_mode else "档案库"
        section_note = "旧输出只保留下载入口，不参与新任务。"
        id_label = "任务号" if office_mode else "档案号"
        st.markdown(
            f"""
<div class="section-card archive-vault">
    <div class="section-heading">
        <div>
            <div class="section-kicker">{section_kicker}</div>
            <div class="section-title">{section_title}</div>
        </div>
        <div class="section-note">{section_note}</div>
    </div>
            """,
            unsafe_allow_html=True,
        )

        for entry_index, entry in enumerate(history_entries):
            progress = entry["progress"]
            audit = entry.get("audit", {})
            download_files = entry.get("download_files", [])
            formats_text = " / ".join(
                sorted({
                    history_file_label(path)
                    for path in download_files
                })
            ) or "无最终成品"
            dossier_id = audit.get("dossier_id") or entry["title"]
            header = (
                f"{dossier_id} ｜ {format_file_time(entry['mtime'])} ｜ "
                f"{format_file_size(entry['size'])} ｜ {formats_text}"
            )
            with st.expander(header, expanded=False):
                failed_count = int(progress.get("failed", 0) or 0)
                metric_cols = st.columns(4 if failed_count else 3)
                metric_cols[0].metric("成品文件", f"{len(download_files)}")
                metric_cols[1].metric("图片资源", f"{entry['assets']}")
                metric_cols[2].metric("完成页", f"{progress.get('completed', 0)}")
                if failed_count:
                    metric_cols[3].metric("失败页", f"{failed_count}")

                audit_items = {
                    id_label: audit.get("dossier_id", "未记录"),
                    "文件": audit.get("source_file", entry["title"]),
                    "模型": audit.get("model", progress.get("model", "未记录")),
                    "页码": audit.get("page_range", "未记录"),
                }
                audit_failed = audit.get("failed_pages", [])
                if audit_failed:
                    audit_items["失败页"] = ", ".join(str(page) for page in audit_failed[:12])
                render_audit_grid(audit_items)
                st.caption(f"目录：{entry['folder']}")

                if _can_retry_export(audit):
                    retry_key = "retry_export_" + hashlib.sha256(
                        str(entry.get("audit_path", "")).encode("utf-8")
                    ).hexdigest()
                    if st.button("重试导出", key=retry_key):
                        try:
                            with st.spinner("正在重试导出，不会调用翻译 API。"):
                                written = _retry_export_from_audit(entry)
                            st.success(f"重试导出完成：{len(written)} 个成品。")
                        except Exception as exc:
                            st.error(f"重试导出失败：{exc}")

                for file_index, file_path in enumerate(download_files):
                    if not is_final_output_file(file_path):
                        continue
                    label = history_file_label(file_path)
                    button_label = f"下载{label}：{file_path.name}"
                    key_seed = f"{entry_index}:{file_index}:{file_path}"
                    with open(file_path, "rb") as f:
                        st.download_button(
                            button_label,
                            f,
                            file_name=file_path.name,
                            key="history_" + hashlib.sha256(key_seed.encode("utf-8")).hexdigest(),
                        )
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        section_kicker = "HISTORY" if office_mode else "ARCHIVE VAULT"
        section_title = "历史输出" if office_mode else "档案库"
        section_note = "还没有历史输出。"
        st.markdown(
            f"""
<div class="section-card archive-vault">
    <div class="section-heading">
        <div>
            <div class="section-kicker">{section_kicker}</div>
            <div class="section-title">{section_title}</div>
        </div>
        <div class="section-note">{section_note}</div>
    </div>
</div>
            """,
            unsafe_allow_html=True,
        )
