"""Output history and audit helpers for the Web UI."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


HISTORY_SUFFIX_LABELS = (
    ("_extraction_report.md", "提取诊断"),
    ("_glossary_report.md", "术语报告"),
    ("_audit.json", "审计记录"),
    (".progress.json", "进度"),
    (".html", "网页"),
    (".docx", "文档"),
    (".md", "纯文本"),
)


def history_file_label(path: Path) -> str:
    name = path.name
    for suffix, label in HISTORY_SUFFIX_LABELS:
        if name.endswith(suffix):
            return label
    return path.suffix.lstrip(".").upper() or "文件"


def is_history_file(path: Path) -> bool:
    return path.is_file() and any(path.name.endswith(suffix) for suffix, _ in HISTORY_SUFFIX_LABELS)


def format_file_size(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


def format_file_time(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def read_progress_summary(progress_path: Path) -> dict[str, Any]:
    data = read_json_file(progress_path)
    if not data:
        return {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    completed = data.get("completed_pages", [])
    failed = data.get("failed_pages", {})
    translations = data.get("translations", {})
    return {
        "completed": len(completed) if isinstance(completed, list) else 0,
        "failed": len(failed) if isinstance(failed, dict) else 0,
        "translated": len([v for v in translations.values() if str(v).strip()])
        if isinstance(translations, dict) else 0,
        "model": metadata.get("model", ""),
        "provider": metadata.get("provider", ""),
        "start_page": metadata.get("start_page"),
        "end_page": metadata.get("end_page"),
    }


def write_audit_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
        f.write("\n")


def collect_output_history(output_dir: Path, limit: int = 8) -> list[dict[str, Any]]:
    if not output_dir.exists():
        return []

    entries = []
    for folder in output_dir.iterdir():
        if not folder.is_dir():
            continue
        files = sorted(
            [path for path in folder.iterdir() if is_history_file(path)],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not files:
            continue
        progress_files = [path for path in files if path.name.endswith(".progress.json")]
        audit_files = [path for path in files if path.name.endswith("_audit.json")]
        assets_dir = folder / "assets"
        asset_count = (
            len([path for path in assets_dir.iterdir() if path.is_file()])
            if assets_dir.exists() else 0
        )
        entries.append({
            "title": folder.name,
            "folder": folder,
            "files": files,
            "mtime": max(path.stat().st_mtime for path in files),
            "size": sum(path.stat().st_size for path in files),
            "assets": asset_count,
            "progress": read_progress_summary(progress_files[0]) if progress_files else {},
            "audit": read_json_file(audit_files[0]) if audit_files else {},
        })

    loose_files = sorted(
        [path for path in output_dir.iterdir() if is_history_file(path)],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if loose_files:
        progress_files = [path for path in loose_files if path.name.endswith(".progress.json")]
        audit_files = [path for path in loose_files if path.name.endswith("_audit.json")]
        entries.append({
            "title": "根目录旧输出",
            "folder": output_dir,
            "files": loose_files[:20],
            "mtime": max(path.stat().st_mtime for path in loose_files),
            "size": sum(path.stat().st_size for path in loose_files),
            "assets": 0,
            "progress": read_progress_summary(progress_files[0]) if progress_files else {},
            "audit": read_json_file(audit_files[0]) if audit_files else {},
        })

    return sorted(entries, key=lambda item: item["mtime"], reverse=True)[:limit]
