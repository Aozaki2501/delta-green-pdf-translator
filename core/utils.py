"""
Core utility functions for the DGtranslate project.

Provides console configuration, path helpers, page-range normalization,
failure detection, page selection parsing, and file hashing.

Dependencies: core.constants (for TRANSLATION_FAILURE_PREFIX)
"""

import hashlib
import os
import re
import sys
from pathlib import Path

from core.constants import TRANSLATION_FAILURE_PREFIX


def configure_console_output():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except AttributeError:
            pass


def ensure_output_parent(path: str):
    parent = Path(path).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)


def normalize_page_range(start_page, end_page, total_pages: int) -> tuple[int, int]:
    try:
        start = int(start_page or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("起始页必须是整数") from exc

    try:
        end = total_pages if end_page is None else int(end_page)
    except (TypeError, ValueError) as exc:
        raise ValueError("结束页必须是整数") from exc

    if total_pages < 1:
        raise ValueError("PDF 没有可处理页面")
    if start < 0:
        raise ValueError("起始页不能小于 0")
    if start >= total_pages:
        raise ValueError(f"起始页超出范围：PDF 共 {total_pages} 页")
    if end > total_pages:
        end = total_pages
    if end <= start:
        raise ValueError("结束页必须大于起始页")
    return start, end


def is_failed_translation(text: str) -> bool:
    return bool(text and text.lstrip().startswith(TRANSLATION_FAILURE_PREFIX))


def parse_page_selection(selection: str, total_pages: int) -> set[int]:
    """Parse 1-based page specs such as '8, 12-15' into zero-based page indexes."""
    pages = set()
    if not selection or not selection.strip():
        return pages

    for raw_part in re.split(r"[,\s，、]+", selection.strip()):
        part = raw_part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                start_text, end_text = part.split("-", 1)
                if not start_text.strip() or not end_text.strip():
                    raise ValueError
                start = int(start_text)
                end = int(end_text)
                if start > end:
                    start, end = end, start
                page_numbers = range(start, end + 1)
            else:
                page_numbers = [int(part)]
        except ValueError as exc:
            raise ValueError(f"无法解析页码片段：{part!r}") from exc

        for page_number in page_numbers:
            if page_number < 1 or page_number > total_pages:
                raise ValueError(f"页码 {page_number} 超出范围 1-{total_pages}")
            pages.add(page_number - 1)
    return pages


def file_sha256(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
