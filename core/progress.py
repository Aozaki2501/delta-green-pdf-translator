"""
Progress tracking with thread-safe persistence.

Provides ProgressTracker for resumable translation sessions, plus
metadata fingerprint construction and comparison utilities.

Dependencies: core.constants (for PROMPT_VERSION, EXTRACTOR_VERSION),
              core.utils (for file_sha256)
"""

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from core.constants import EXTRACTOR_VERSION, PROMPT_VERSION
from core.translation_validation import contains_prompt_leak, ensure_no_prompt_leak
from core.utils import file_sha256


def build_progress_metadata(pdf_path: str, glossary_path: Optional[str], model: str,
                            start_page: int, end_page: int | None,
                            provider: str = "deepseek",
                            base_url: str = "https://api.deepseek.com") -> dict:
    """Build a metadata fingerprint dict for a translation session."""
    return {
        "schema": 1,
        "pdf_sha256": file_sha256(pdf_path),
        "glossary_sha256": file_sha256(glossary_path) if glossary_path else "",
        "model": model,
        "provider": provider,
        "base_url": base_url,
        "prompt_version": PROMPT_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "start_page": start_page,
        "end_page": end_page,
    }


def compare_progress_metadata(expected: dict, actual: dict) -> list[str]:
    """Compare two metadata dicts and return a list of mismatch descriptions."""
    if not expected:
        return []
    if not actual:
        return ["进度文件缺少版本指纹"]

    mismatches = []
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if actual_value != expected_value:
            mismatches.append(f"{key}: {actual_value!r} -> {expected_value!r}")
    return mismatches


class ProgressTracker:
    """Thread-safe progress tracker with atomic file persistence."""

    def __init__(self, progress_file: str, expected_metadata: Optional[dict] = None,
                 reuse_mismatched: bool = False):
        self.progress_file = progress_file
        self.expected_metadata = expected_metadata or {}
        self.reuse_mismatched = reuse_mismatched
        self.metadata = dict(self.expected_metadata)
        self.metadata_mismatches: list[str] = []
        self.ignored_existing_progress = False
        self.completed_pages = set()
        self.failed_pages = {}
        self.translations = {}
        self.translation_cache = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("progress root must be an object")
                loaded_metadata = data.get("metadata", {})
                self.metadata_mismatches = compare_progress_metadata(
                    self.expected_metadata,
                    loaded_metadata,
                )
                if self.metadata_mismatches and not self.reuse_mismatched:
                    self.ignored_existing_progress = True
                    self.completed_pages = set()
                    self.failed_pages = {}
                    self.translations = {}
                    self.translation_cache = {}
                    self.metadata = dict(self.expected_metadata)
                    print("Progress metadata mismatch, ignoring cached translations")
                    return

                self.metadata = loaded_metadata or dict(self.expected_metadata)
                self.completed_pages = {
                    int(page_num)
                    for page_num in data.get("completed_pages", [])
                    if str(page_num).isdigit()
                }
                loaded_translations = data.get("translations", {})
                self.translations = (
                    loaded_translations if isinstance(loaded_translations, dict) else {}
                )
                loaded_failed = data.get("failed_pages", {})
                self.failed_pages = loaded_failed if isinstance(loaded_failed, dict) else {}
                loaded_cache = data.get("translation_cache", {})
                self.translation_cache = loaded_cache if isinstance(loaded_cache, dict) else {}
                print(
                    f"Loaded progress: {len(self.completed_pages)} pages done, "
                    f"{len(self.failed_pages)} failed"
                )
            except (json.JSONDecodeError, IOError, ValueError, TypeError):
                print("Progress file corrupted, starting fresh")

    def save(self):
        """Persist progress to disk atomically (write temp file, then os.replace)."""
        with self._lock:
            data = {
                "metadata": self.metadata,
                "completed_pages": sorted(self.completed_pages),
                "translations": self.translations,
                "failed_pages": self.failed_pages,
                "translation_cache": self.translation_cache,
            }
            progress_path = Path(self.progress_file)
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = None
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(progress_path.parent),
                prefix=progress_path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as f:
                tmp_path = Path(f.name)
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            _replace_with_retry(tmp_path, progress_path)

    def is_completed(self, page_num: int) -> bool:
        """Check whether a page has already been translated."""
        if page_num not in self.completed_pages:
            return False
        return not contains_prompt_leak(self.translations.get(str(page_num), ""))

    def mark_completed(self, page_num: int, translation: str):
        """Record a page translation and persist immediately."""
        ensure_no_prompt_leak(translation)
        with self._lock:
            self.completed_pages.add(page_num)
            self.translations[str(page_num)] = translation
            self.failed_pages.pop(str(page_num), None)
        self.save()

    def mark_failed(self, page_num: int, message: str):
        """Record a failed page without treating it as completed."""
        with self._lock:
            self.completed_pages.discard(page_num)
            self.translations.pop(str(page_num), None)
            self.failed_pages[str(page_num)] = str(message or "translation failed")
        self.save()

    def get_failed_pages(self) -> set[int]:
        """Return failed page numbers as zero-based indexes."""
        with self._lock:
            return {
                int(page_num)
                for page_num in self.failed_pages
                if str(page_num).isdigit()
            }

    def clear_failed_pages(self, page_nums=None) -> int:
        """Clear failed-page markers. Returns count cleared."""
        cleared = 0
        page_filter = None if page_nums is None else {str(p) for p in page_nums}
        with self._lock:
            for page_num in list(self.failed_pages):
                if page_filter is not None and page_num not in page_filter:
                    continue
                self.failed_pages.pop(page_num, None)
                cleared += 1
        if cleared:
            self.save()
        return cleared

    def clear_pages(self, page_nums) -> int:
        """Remove specified pages from completed state. Returns count cleared."""
        cleared = 0
        with self._lock:
            for page_num in page_nums:
                page_cleared = False
                if page_num in self.completed_pages:
                    self.completed_pages.remove(page_num)
                    page_cleared = True
                if str(page_num) in self.translations:
                    self.translations.pop(str(page_num), None)
                    page_cleared = True
                if str(page_num) in self.failed_pages:
                    self.failed_pages.pop(str(page_num), None)
                    page_cleared = True
                if page_cleared:
                    cleared += 1
        if cleared:
            self.save()
        return cleared

    def get_translation(self, page_num: int) -> str:
        """Retrieve the cached translation for a page, or empty string."""
        translation = self.translations.get(str(page_num), "")
        if contains_prompt_leak(translation):
            return ""
        return translation

    def get_cached_prompt_translation(self, cache_key: str) -> str:
        """Retrieve a cached translation for an exact prompt key."""
        if not cache_key:
            return ""
        with self._lock:
            translation = self.translation_cache.get(cache_key, "")
        if contains_prompt_leak(translation):
            return ""
        return translation

    def mark_cached_prompt_translation(self, cache_key: str, translation: str):
        """Persist a translation for an exact prompt key."""
        if not cache_key or not translation:
            return
        ensure_no_prompt_leak(translation, "缓存译文")
        with self._lock:
            self.translation_cache[cache_key] = translation
        self.save()

    def delete_cached_prompt_translation(self, cache_key: str):
        """Remove one exact prompt cache entry."""
        if not cache_key:
            return
        with self._lock:
            removed = self.translation_cache.pop(cache_key, None)
        if removed is not None:
            self.save()

    def delete_cached_prompt_translations_by_value(self, translation: str) -> int:
        """Remove exact-prompt cache entries that contain a rejected translation."""
        if not translation:
            return 0
        with self._lock:
            cache_keys = [
                key for key, value in self.translation_cache.items()
                if value == translation
            ]
            for key in cache_keys:
                self.translation_cache.pop(key, None)
        if cache_keys:
            self.save()
        return len(cache_keys)


def _replace_with_retry(tmp_path: Path, target_path: Path, attempts: int = 20):
    """Atomically replace a progress file, tolerating short Windows file locks."""
    last_error = None
    for attempt in range(max(1, attempts)):
        try:
            os.replace(tmp_path, target_path)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(min(0.05 * (attempt + 1), 0.5))
    raise PermissionError(f"无法写入进度文件，目标可能被其他程序占用：{target_path}") from last_error
