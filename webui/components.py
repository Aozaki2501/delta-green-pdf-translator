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
)


STATUS_STEPS = ("接收档案", "提取文本", "匹配术语", "编译译文", "生成输出", "归档完成")


def make_dossier_id(filename: str, file_digest: str, created_at: float | None = None) -> str:
    timestamp = time.strftime("%Y%m%d-%H%M", time.localtime(created_at or time.time()))
    seed = f"{filename}:{file_digest}".encode("utf-8")
    suffix = hashlib.sha256(seed).hexdigest()[:6].upper()
    return f"DG-{timestamp}-{suffix}"


def render_dossier_card(dossier_id: str, filename: str, file_digest: str,
                        glossary_name: str = "", loaded: bool = False) -> None:
    state_class = " loaded" if loaded else ""
    digest = file_digest[:12].upper() if file_digest else "待接收"
    glossary = glossary_name or "默认术语表"
    st.markdown(
        f"""
<div class="dossier-card{state_class}">
    <div class="dossier-kicker">CLASSIFIED DOSSIER</div>
    <div class="dossier-id">{html.escape(dossier_id)}</div>
    <div class="dossier-meta">
        <span>文件：{html.escape(filename or "待导入")}</span>
        <span>校验：{html.escape(digest)}</span>
        <span>术语：{html.escape(glossary)}</span>
        <span>密级：绝密 / 待校对</span>
    </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_status_flow(active_index: int = 0, failed: bool = False) -> None:
    parts = ['<div class="status-flow">']
    for idx, label in enumerate(STATUS_STEPS):
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
    st.markdown("\n".join(parts), unsafe_allow_html=True)


def render_system_log(lines: list[tuple[str, str]]) -> None:
    parts = ['<div class="system-log">']
    for level, text in lines:
        safe_level = level if level in {"warn", "fail"} else ""
        parts.append(f'<div class="system-log-line {safe_level}">&gt; {html.escape(text)}</div>')
    parts.append("</div>")
    st.markdown("\n".join(parts), unsafe_allow_html=True)


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


def render_output_history(output_dir: Path, limit: int = 8) -> None:
    history_entries = collect_output_history(output_dir, limit=limit)
    if history_entries:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("输出历史")
        st.caption("这里列出本机 output 目录里的旧结果，只提供查看和下载，不会重新调用翻译接口。")

        for entry in history_entries:
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
                    "档案号": audit.get("dossier_id", "未记录"),
                    "文件": audit.get("source_file", entry["title"]),
                    "模型": audit.get("model", progress.get("model", "未记录")),
                    "页码": audit.get("page_range", "未记录"),
                }
                audit_failed = audit.get("failed_pages", [])
                if audit_failed:
                    audit_items["失败页"] = ", ".join(str(page) for page in audit_failed[:12])
                render_audit_grid(audit_items)
                st.caption(f"目录：{entry['folder']}")

                for file_path in download_files:
                    if not is_final_output_file(file_path):
                        continue
                    label = history_file_label(file_path)
                    button_label = f"下载{label}：{file_path.name}"
                    with open(file_path, "rb") as f:
                        st.download_button(
                            button_label,
                            f,
                            file_name=file_path.name,
                            key="history_" + hashlib.sha256(str(file_path).encode("utf-8")).hexdigest(),
                        )
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("输出历史")
        st.caption("还没有发现历史输出。完成一次翻译后，这里会列出可下载的旧结果。")
        st.markdown("</div>", unsafe_allow_html=True)
