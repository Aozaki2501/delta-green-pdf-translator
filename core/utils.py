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


def output_base_in_own_dir(output_path: str) -> str:
    """Return an output stem placed inside a same-named folder."""
    path = Path(output_path).expanduser()
    if path.suffix.lower() in {".md", ".html", ".docx", ".pdf"}:
        path = path.with_suffix("")
    if path.parent.name == path.name:
        return str(path)
    return str(path.parent / path.name / path.name)


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


def count_cjk_chars(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def count_latin_chars(text: str) -> int:
    return len(re.findall(r"[A-Za-z]", text or ""))


def looks_untranslated_page(source_text: str, translated_text: str, layout: str = "") -> bool:
    if layout == "art":
        return False
    if is_failed_translation(translated_text):
        return False

    source = str(source_text or "").strip()
    translated = str(translated_text or "").strip()
    if not source or not translated or "[[TOC]]" in source:
        return False

    source_latin = count_latin_chars(source)
    source_words = re.findall(r"[A-Za-z]{3,}", source)
    if source_latin < 80 or len(source_words) < 20:
        return False

    translated_cjk = count_cjk_chars(translated)
    translated_latin = count_latin_chars(translated)
    if translated_latin < 80:
        return False

    visible_len = len(re.sub(r"\s+", "", translated))
    cjk_floor = max(24, int(visible_len * 0.18))
    if translated_cjk >= cjk_floor:
        return False

    latin_ratio = translated_latin / max(translated_latin + translated_cjk, 1)
    return latin_ratio >= 0.72


def looks_incomplete_translation(source_text: str, translated_text: str, layout: str = "") -> bool:
    if layout == "art":
        return False
    if is_failed_translation(translated_text):
        return False

    source = str(source_text or "").strip()
    translated = str(translated_text or "").strip()
    if not source or not translated or "[[TOC]]" in source:
        return False

    source_visible_len = len(re.sub(r"\s+", "", source))
    translated_visible_len = len(re.sub(r"\s+", "", translated))
    if source_visible_len < 1200:
        return False

    source_latin = count_latin_chars(source)
    source_words = re.findall(r"[A-Za-z]{3,}", source)
    if source_latin < 700 or len(source_words) < 120:
        return False

    translated_cjk = count_cjk_chars(translated)
    if translated_cjk < 80:
        return False

    return translated_visible_len / max(source_visible_len, 1) < 0.15


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
