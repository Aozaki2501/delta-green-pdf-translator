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
from pathlib import Path
from typing import Optional

from core.constants import EXTRACTOR_VERSION, PROMPT_VERSION, TRANSLATION_TEMPERATURE
from core.translation_validation import (
    contains_japanese_kana,
    contains_prompt_leak,
    ensure_no_japanese_kana,
    ensure_no_prompt_leak,
)
from core.utils import file_sha256, replace_with_retry

# Fingerprint schema. Bumped to 2 when fuzzy_matching/temperature were added and
# missing input files stopped hashing to the same value as "no file at all".
PROGRESS_SCHEMA_VERSION = 2


def fingerprint_file(path: Optional[str]) -> str:
    """Hash a fingerprint input, distinguishing "no file" from "file is gone".

    ``file_sha256`` returns "" for both cases, which made a deleted glossary
    look identical to never having used one — the run would silently reuse
    translations produced with terminology that is no longer on disk.
    """
    if not path:
        return ""
    return file_sha256(path) or "missing"


def build_progress_metadata(pdf_path: str, glossary_path: Optional[str], model: str,
                            start_page: int, end_page: int | None,
                            provider: str = "deepseek",
                            base_url: str = "https://api.deepseek.com",
                            fuzzy_matching: bool = False) -> dict:
    """Build a metadata fingerprint dict for a translation session.

    Every field here changes the produced translation. ``max_workers`` is
    deliberately absent: context is now built from adjacent *source* text on
    both the serial and concurrent paths, so concurrency no longer affects the
    prompts and changing it must not throw away paid-for translations.
    """
    return {
        "schema": PROGRESS_SCHEMA_VERSION,
        "pdf_sha256": fingerprint_file(pdf_path),
        "glossary_sha256": fingerprint_file(glossary_path),
        "model": model,
        "provider": provider,
        "base_url": base_url,
        "prompt_version": PROMPT_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "temperature": TRANSLATION_TEMPERATURE,
        "fuzzy_matching": bool(fuzzy_matching),
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
        self.progress_corrupted = False
        self.corrupt_backup_path = ""
        self.completed_pages = set()
        self.failed_pages = {}
        self.translations = {}
        self.translation_cache = {}
        self._lock = threading.Lock()
        self._pending_save = False
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
            except (json.JSONDecodeError, IOError, ValueError, TypeError) as exc:
                self._backup_corrupt_file(exc)

    def _backup_corrupt_file(self, exc: Exception):
        """Move an unreadable progress file aside before starting fresh.

        Starting fresh is fine; overwriting is not. The first ``save()`` after a
        failed load would replace the file with empty data, destroying
        translations that a human could still have salvaged by hand.
        """
        backup_path = Path(f"{self.progress_file}.corrupt.bak")
        replace_with_retry(Path(self.progress_file), backup_path)
        self.progress_corrupted = True
        self.corrupt_backup_path = str(backup_path)
        print(
            f"进度文件无法解析（{exc}），已备份为 {backup_path}，本次从头开始翻译。"
        )

    def save(self, force: bool = True):
        """Persist progress to disk atomically (write temp file, then os.replace).

        ``force=False`` defers the write: the caller is about to record the same
        content through a path that does force a write, so serializing the whole
        file twice in a row is pure waste. Any forced save flushes the deferral.
        """
        if not force:
            with self._lock:
                self._pending_save = True
            return
        with self._lock:
            self._pending_save = False
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
            replace_with_retry(tmp_path, progress_path)

    def is_completed(self, page_num: int) -> bool:
        """Check whether a page has already been translated."""
        if page_num not in self.completed_pages:
            return False
        translation = self.translations.get(str(page_num), "")
        return not contains_prompt_leak(translation) and not contains_japanese_kana(translation)

    def flush(self):
        """Write out any deferred save. Safe to call when nothing is pending."""
        if self._pending_save:
            self.save()

    def mark_completed(self, page_num: int, translation: str):
        """Record a page translation and persist immediately."""
        ensure_no_prompt_leak(translation)
        ensure_no_japanese_kana(translation)
        with self._lock:
            self.completed_pages.add(page_num)
            self.translations[str(page_num)] = translation
            self.failed_pages.pop(str(page_num), None)
        self.save()

    def mark_completed_many(self, translations: dict[int, str]):
        """Record several translations with a single write.

        Block-level callers finish a whole group at once. Saving per block made
        a 3000-block document rewrite the entire progress file 3000 times; one
        write per group keeps the same crash safety at a fraction of the I/O.
        """
        if not translations:
            return
        for translation in translations.values():
            ensure_no_prompt_leak(translation)
            ensure_no_japanese_kana(translation)
        with self._lock:
            for page_num, translation in translations.items():
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
        rejected_translations = []
        with self._lock:
            for page_num in page_nums:
                page_cleared = False
                if page_num in self.completed_pages:
                    self.completed_pages.remove(page_num)
                    page_cleared = True
                if str(page_num) in self.translations:
                    old_translation = self.translations.pop(str(page_num), None)
                    if old_translation:
                        rejected_translations.append(old_translation)
                    page_cleared = True
                if str(page_num) in self.failed_pages:
                    self.failed_pages.pop(str(page_num), None)
                    page_cleared = True
                if page_cleared:
                    cleared += 1
            for old_translation in rejected_translations:
                for cache_key, cached_translation in list(self.translation_cache.items()):
                    if cached_translation == old_translation:
                        self.translation_cache.pop(cache_key, None)
        if cleared:
            self.save()
        return cleared

    def get_translation(self, page_num: int) -> str:
        """Retrieve the cached translation for a page, or empty string."""
        translation = self.translations.get(str(page_num), "")
        if contains_prompt_leak(translation) or contains_japanese_kana(translation):
            return ""
        return translation

    def get_cached_prompt_translation(self, cache_key: str) -> str:
        """Retrieve a cached translation for an exact prompt key."""
        if not cache_key:
            return ""
        with self._lock:
            translation = self.translation_cache.get(cache_key, "")
        if contains_prompt_leak(translation) or contains_japanese_kana(translation):
            return ""
        return translation

    def mark_cached_prompt_translation(self, cache_key: str, translation: str):
        """Persist a translation for an exact prompt key."""
        if not cache_key or not translation:
            return
        ensure_no_prompt_leak(translation, "缓存译文")
        ensure_no_japanese_kana(translation, "缓存译文")
        with self._lock:
            self.translation_cache[cache_key] = translation
        # Deferred: the caller records this same text via mark_completed a moment
        # later, and that write persists this entry too.
        self.save(force=False)

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
