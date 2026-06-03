"""Output history and audit helpers for the Web UI."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


HISTORY_SUFFIX_LABELS = (
    ("_extraction_report.md", "提取诊断"),
    ("_glossary_report.md", "术语报告"),
    ("_replica.overflow.md", "坐标溢出报告"),
    ("_replica.layout_report.md", "坐标排版报告"),
    ("_replica.translated.layout.json", "坐标译文"),
    ("_replica.translations.json", "坐标译文模板"),
    ("_replica.layout.json", "坐标版面"),
    ("_replica.progress.json", "坐标进度"),
    ("_replica.html", "坐标网页"),
    ("_replica.pdf", "坐标PDF"),
    ("_audit.json", "审计记录"),
    (".progress.json", "进度"),
    (".pdf", "PDF"),
    (".html", "网页"),
    (".docx", "文档"),
    (".zip", "资源包"),
    (".md", "纯文本"),
)


INTERNAL_OUTPUT_SUFFIXES = (
    "_extraction_report.md",
    "_glossary_report.md",
    "_replica.overflow.md",
    "_replica.layout_report.md",
    "_replica.translated.layout.json",
    "_replica.translations.json",
    "_replica.layout.json",
    "_replica.progress.json",
    "_audit.json",
    ".progress.json",
)

FINAL_OUTPUT_SUFFIXES = (
    "_replica.pdf",
    "_replica.html",
    ".pdf",
    ".html",
    ".docx",
    ".zip",
    ".md",
)


def history_file_label(path: Path) -> str:
    name = path.name
    for suffix, label in HISTORY_SUFFIX_LABELS:
        if name.endswith(suffix):
            return label
    return path.suffix.lstrip(".").upper() or "文件"


def is_history_file(path: Path) -> bool:
    return path.is_file() and any(path.name.endswith(suffix) for suffix, _ in HISTORY_SUFFIX_LABELS)


def is_final_output_file(path: Path) -> bool:
    name = path.name
    if not path.is_file():
        return False
    if any(name.endswith(suffix) for suffix in INTERNAL_OUTPUT_SUFFIXES):
        return False
    return any(name.endswith(suffix) for suffix in FINAL_OUTPUT_SUFFIXES)


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
    failed_blocks = data.get("failed_blocks", {})
    translations = data.get("translations", {})
    if not completed and isinstance(failed_blocks, dict):
        return {
            "completed": len(translations) if isinstance(translations, dict) else 0,
            "failed": len(failed_blocks),
            "translated": len([v for v in translations.values() if str(v).strip()])
            if isinstance(translations, dict) else 0,
            "model": metadata.get("model", ""),
            "provider": metadata.get("provider", ""),
            "start_page": metadata.get("start_page"),
            "end_page": metadata.get("end_page"),
        }
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


def _asset_count(folder: Path) -> int:
    assets_dir = folder / "assets"
    if not assets_dir.exists():
        return 0
    return len([path for path in assets_dir.rglob("*") if path.is_file()])


def _files_for_audit(folder: Path, audit_path: Path, all_files: list[Path]) -> list[Path]:
    audit = read_json_file(audit_path)
    output_names = audit.get("outputs", [])
    if not isinstance(output_names, list) or not output_names:
        return _dedupe_paths(all_files)
    wanted = {str(name) for name in output_names}
    wanted.add(audit_path.name)
    files = [path for path in all_files if path.name in wanted]
    return _dedupe_paths(files or [audit_path])


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen = set()
    result = []
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


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
        if audit_files:
            for audit_path in audit_files:
                audit = read_json_file(audit_path)
                audit_files_for_entry = _files_for_audit(folder, audit_path, files)
                entry_progress_files = [
                    path for path in audit_files_for_entry
                    if path.name.endswith(".progress.json")
                ] or progress_files
                entries.append({
                    "title": folder.name,
                    "folder": folder,
                    "files": audit_files_for_entry,
                    "download_files": [path for path in audit_files_for_entry if is_final_output_file(path)],
                    "mtime": audit_path.stat().st_mtime,
                    "size": sum(path.stat().st_size for path in audit_files_for_entry),
                    "assets": _asset_count(folder),
                    "progress": read_progress_summary(entry_progress_files[0]) if entry_progress_files else {},
                    "audit": audit,
                })
        else:
            entries.append({
                "title": folder.name,
                "folder": folder,
                "files": files,
                "download_files": [path for path in files if is_final_output_file(path)],
                "mtime": max(path.stat().st_mtime for path in files),
                "size": sum(path.stat().st_size for path in files),
                "assets": _asset_count(folder),
                "progress": read_progress_summary(progress_files[0]) if progress_files else {},
                "audit": {},
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
            "download_files": [path for path in loose_files[:20] if is_final_output_file(path)],
            "mtime": max(path.stat().st_mtime for path in loose_files),
            "size": sum(path.stat().st_size for path in loose_files),
            "assets": 0,
            "progress": read_progress_summary(progress_files[0]) if progress_files else {},
            "audit": read_json_file(audit_files[0]) if audit_files else {},
        })

    return sorted(entries, key=lambda item: item["mtime"], reverse=True)[:limit]
