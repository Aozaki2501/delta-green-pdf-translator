"""Streamlit view for the storage cleanup entry point.

Kept separate from webui.storage so the scanning and deletion logic stays
testable without importing Streamlit.
"""

from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

from webui.storage import (
    delete_entry,
    entries_older_than,
    format_size,
    scan_storage,
    total_size,
)


def render_storage_manager(upload_dir: Path, output_dir: Path) -> None:
    """Show what uploads/ and output/ hold, and offer deletion."""
    st.caption(
        "原始文件、逐页英文原文和全部译文都保存在本机。"
        "这里可以查看占用并按任务或按时间清理。"
    )

    for label, root in (("上传原件", upload_dir), ("输出任务", output_dir)):
        entries = scan_storage(root)
        st.markdown(f"**{label}** — {len(entries)} 项，共 {format_size(total_size(entries))}")

        if not entries:
            st.caption("暂无内容。")
            continue

        _render_age_cleanup(label, root, entries)

        options = {
            f"{entry.name}（{format_size(entry.size_bytes)}，"
            f"{time.strftime('%Y-%m-%d', time.localtime(entry.modified_at))}）": entry
            for entry in entries
        }
        selected_labels = st.multiselect(
            f"选择要删除的{label}",
            list(options),
            key=f"storage_select_{label}",
        )
        if selected_labels and st.button(
            f"删除选中的 {len(selected_labels)} 项{label}",
            key=f"storage_delete_{label}",
        ):
            _delete_and_report([options[name] for name in selected_labels], root)


def _render_age_cleanup(label: str, root: Path, entries: list) -> None:
    days = st.number_input(
        f"清理超过多少天未修改的{label}",
        value=0,
        min_value=0,
        step=7,
        help="0 表示不按时间清理。",
        key=f"storage_days_{label}",
    )
    if days <= 0:
        return

    stale = entries_older_than(entries, float(days))
    if not stale:
        st.caption(f"没有超过 {days} 天未修改的{label}。")
        return

    st.warning(
        f"有 {len(stale)} 项{label}超过 {days} 天未修改，"
        f"共 {format_size(total_size(stale))}。"
    )
    if st.button(f"删除这 {len(stale)} 项{label}", key=f"storage_delete_old_{label}"):
        _delete_and_report(stale, root)


def _delete_and_report(entries: list, root: Path) -> None:
    freed = 0
    errors = []
    for entry in entries:
        try:
            freed += delete_entry(entry.path, root)
        except (OSError, ValueError) as exc:
            errors.append(f"{entry.name}：{exc}")

    if freed:
        st.success(f"已释放 {format_size(freed)}。")
    if errors:
        st.error("以下项目删除失败：\n" + "\n".join(f"- {item}" for item in errors))
    if not errors:
        st.rerun()
