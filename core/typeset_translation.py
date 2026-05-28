"""
Translation integration for the typeset reflow pipeline (Phase C).

Translates semantic content blocks from page_content.json, producing
page_content_translated.json. Reuses existing Translator.translate_chunk()
interface, glossary matching, translation caching, and checkpoint/resume.

Dependencies: core.typeset_models, core.translator, core.glossary, core.constants
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from core.constants import TRANSLATION_FAILURE_PREFIX
from core.glossary import find_relevant_glossary_terms
from core.typeset_models import (
    ContentBlock,
    PageContent,
    PageContentDocument,
    PageType,
    SemanticRole,
    PAGE_CONTENT_SCHEMA_VERSION,
)


# ---------------------------------------------------------------------------
# TypesetTranslationProgress — checkpoint/resume for typeset translation
# ---------------------------------------------------------------------------


class TypesetTranslationProgress:
    """Progress file for typeset pipeline block-level translation.

    Stores completed translations, failed blocks, and prompt-level cache.
    Supports checkpoint/resume: on restart, already-translated blocks are skipped.
    """

    def __init__(self, progress_file: str):
        if not progress_file:
            raise ValueError("progress_file 不能为空")
        self.progress_file = progress_file
        self.translations: dict[str, str] = {}
        self.failed_blocks: dict[str, str] = {}
        self.translation_cache: dict[str, str] = {}
        self.completed_phases: list[str] = []
        self.last_translated_page: int = -1
        self._lock = threading.RLock()
        self._load()

    def _load(self):
        path = Path(self.progress_file)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
        except (OSError, json.JSONDecodeError, ValueError):
            return
        self.translations = dict(data.get("translations") or {})
        self.failed_blocks = dict(data.get("failed_blocks") or {})
        self.translation_cache = dict(data.get("translation_cache") or {})
        self.completed_phases = list(data.get("completed_phases") or [])
        self.last_translated_page = int(data.get("last_translated_page", -1))

    def save(self):
        with self._lock:
            data = {
                "schema": 1,
                "pipeline": "typeset",
                "translations": self.translations,
                "failed_blocks": self.failed_blocks,
                "translation_cache": self.translation_cache,
                "completed_phases": self.completed_phases,
                "last_translated_page": self.last_translated_page,
            }
            progress_path = Path(self.progress_file)
            progress_path.parent.mkdir(parents=True, exist_ok=True)
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

    # -- Query methods --

    def is_completed(self, block_id: str) -> bool:
        with self._lock:
            return block_id in self.translations

    def get_translation(self, block_id: str) -> str:
        with self._lock:
            return self.translations.get(block_id, "")

    def get_failed_blocks(self) -> set[str]:
        with self._lock:
            return set(self.failed_blocks)

    # -- Cache interface (compatible with Translator.translate_chunk cache param) --

    def get_cached_prompt_translation(self, cache_key: str) -> str:
        with self._lock:
            return self.translation_cache.get(cache_key, "")

    def mark_cached_prompt_translation(self, cache_key: str, translation: str):
        if cache_key and translation:
            with self._lock:
                self.translation_cache[cache_key] = translation
                self.save()

    # -- Mutation methods --

    def mark_completed(self, block_id: str, translation: str):
        if not block_id:
            raise ValueError("block_id 不能为空")
        if not translation:
            raise ValueError(f"译文为空：{block_id}")
        with self._lock:
            self.translations[block_id] = translation
            self.failed_blocks.pop(block_id, None)
            self.save()

    def mark_failed(self, block_id: str, message: str):
        if not block_id:
            raise ValueError("block_id 不能为空")
        with self._lock:
            self.translations.pop(block_id, None)
            self.failed_blocks[block_id] = str(message or "translation failed")
            self.save()

    def clear_failed_blocks(self, block_ids=None) -> int:
        with self._lock:
            block_filter = None if block_ids is None else set(block_ids)
            cleared = 0
            for block_id in list(self.failed_blocks):
                if block_filter is not None and block_id not in block_filter:
                    continue
                self.failed_blocks.pop(block_id, None)
                cleared += 1
            if cleared:
                self.save()
            return cleared

    def mark_phase_completed(self, phase: str):
        with self._lock:
            if phase not in self.completed_phases:
                self.completed_phases.append(phase)
                self.save()

    def is_phase_completed(self, phase: str) -> bool:
        with self._lock:
            return phase in self.completed_phases


# ---------------------------------------------------------------------------
# Translation cache key helper
# ---------------------------------------------------------------------------


def _source_text_hash(text: str) -> str:
    """SHA-256 hash of source text for translation cache lookup."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Block marker formatting and parsing
# ---------------------------------------------------------------------------


def _build_marked_text(blocks: list[ContentBlock]) -> str:
    """Build translation request text with [BLOCK id] markers."""
    parts = [
        "Translate each block below. Preserve every block marker line exactly. "
        "Return one translated block for each source block. Do not merge blocks, remove markers, "
        "or add commentary. Inside each block, output plain translated text only. "
        "Do not add Markdown heading markers, bullet markers, notes, explanations, or formatting "
        "unless that exact marker exists in the source block. Keep the translation concise so it "
        "fits back into the original PDF text box."
    ]
    for block in blocks:
        parts.append(f"[BLOCK {block.id}]\n{block.source_text}\n[/BLOCK {block.id}]")
    return "\n\n".join(parts)


def _parse_marked_translations(text: str, expected_ids: set[str]) -> dict[str, str]:
    """Parse translation response to extract per-block translations."""
    pattern = re.compile(
        r"\[BLOCK ([^\]\s]+)\]\s*(.*?)\s*\[/BLOCK \1\]",
        re.DOTALL,
    )
    parsed = {}
    for match in pattern.finditer(text):
        block_id = match.group(1).strip()
        translated = match.group(2).strip()
        if block_id in parsed:
            raise ValueError(f"重复的翻译块标记：{block_id}")
        parsed[block_id] = translated

    missing = sorted(expected_ids - set(parsed))
    extra = sorted(set(parsed) - expected_ids)
    if missing or extra:
        parts = []
        if missing:
            parts.append("缺少：" + ", ".join(missing[:10]))
        if extra:
            parts.append("多余：" + ", ".join(extra[:10]))
        raise ValueError("翻译块标记不匹配；" + "；".join(parts))

    empty = [block_id for block_id, translated in parsed.items() if not translated]
    if empty:
        raise ValueError("译文为空：" + ", ".join(sorted(empty)[:10]))
    return parsed


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds


def _translate_with_retry(
    translator,
    source_text: str,
    page_num: int,
    prev_context: str,
    cache,
) -> str:
    """Call translator.translate_chunk with retry logic (3 retries, exponential backoff).

    The Translator class already has internal retry logic, but this provides
    an additional layer for transient failures at the pipeline level.
    """
    last_error = None
    for attempt in range(MAX_RETRIES):
        result = translator.translate_chunk(
            source_text,
            page_num=page_num,
            prev_context=prev_context,
            cache=cache,
        )
        # If the translator returns a failure marker, retry
        if result and result.lstrip().startswith(TRANSLATION_FAILURE_PREFIX):
            last_error = result
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                continue
        return result
    # All retries exhausted — return the last failure
    return last_error or f"{TRANSLATION_FAILURE_PREFIX} max retries exceeded]"


# ---------------------------------------------------------------------------
# Main translation function
# ---------------------------------------------------------------------------


def translate_typeset_content(
    content: PageContentDocument,
    translator,
    progress: TypesetTranslationProgress,
    glossary: dict,
    progress_callback: Callable[[int, int, str, bool], None] | None = None,
    max_workers: int = 4,
) -> PageContentDocument:
    """Translate typeset content blocks, producing a translated PageContentDocument.

    - Skips blocks where translatable = False (header/footer)
    - Uses [BLOCK id] markers to keep region correspondence
    - Reuses existing Translator.translate_chunk() interface
    - Applies glossary via translator.set_glossary()
    - Translation cache: hash source_text, check progress file
    - Failed translations: record in progress file with error message
    - Checkpoint/resume: skip already-translated blocks from progress file
    - Output: same structure as input but with translated_text filled in

    Args:
        content: PageContentDocument from Phase B (page_content.json)
        translator: Translator instance with translate_chunk() method
        progress: TypesetTranslationProgress for checkpoint/resume
        glossary: {english_term: chinese_translation} dict
        progress_callback: Optional callback(done, total, unit_id, success)

    Returns:
        PageContentDocument with translated_text populated
    """
    # Apply glossary to translator
    if glossary:
        translator.set_glossary(glossary)

    # Collect translatable blocks grouped by page
    page_units = _collect_translation_units(content, progress)

    total_units = len(page_units)
    max_workers = max(1, int(max_workers or 1))
    completed_units = 0

    futures = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for page_index, blocks in page_units:
            unit_id = blocks[0].id if len(blocks) == 1 else f"p{page_index + 1:04d}"
            cached_result = _finish_cached_unit(page_index, blocks, progress)
            if cached_result is not None:
                completed_units += 1
                if progress_callback:
                    progress_callback(completed_units, total_units, f"{unit_id} ({cached_result})", True)
                continue

            pending_blocks = [b for b in blocks if not progress.is_completed(b.id)]
            if not pending_blocks:
                completed_units += 1
                if progress_callback:
                    progress_callback(completed_units, total_units, f"{unit_id} (resumed)", True)
                progress.last_translated_page = page_index
                progress.save()
                continue

            future = executor.submit(
                _translate_typeset_unit,
                translator,
                page_index,
                pending_blocks,
            )
            futures[future] = (page_index, unit_id, pending_blocks)

        for future in as_completed(futures):
            page_index, unit_id, pending_blocks = futures[future]
            completed_units += 1
            try:
                parsed = future.result()
            except Exception as exc:
                message = f"{TRANSLATION_FAILURE_PREFIX} {exc}]"
                for block in pending_blocks:
                    progress.mark_failed(block.id, message)
                if progress_callback:
                    progress_callback(completed_units, total_units, unit_id, False)
                continue

            for block in pending_blocks:
                block_translation = parsed.get(block.id)
                if not block_translation:
                    progress.mark_failed(block.id, f"{TRANSLATION_FAILURE_PREFIX} missing translation]")
                    continue
                progress.mark_completed(block.id, block_translation)
                progress.mark_cached_prompt_translation(_source_text_hash(block.source_text), block_translation)

            progress.last_translated_page = page_index
            progress.save()

            if progress_callback:
                progress_callback(completed_units, total_units, f"{unit_id} / {len(pending_blocks)} 块", True)

    # Build translated document
    return _build_translated_document(content, progress)


def _finish_cached_unit(
    page_index: int,
    blocks: list[ContentBlock],
    progress: TypesetTranslationProgress,
) -> str | None:
    all_cached = True
    for block in blocks:
        cache_key = _source_text_hash(block.source_text)
        cached = progress.get_cached_prompt_translation(cache_key)
        if cached:
            if not progress.is_completed(block.id):
                progress.mark_completed(block.id, cached)
        else:
            all_cached = False

    if all_cached and all(progress.is_completed(b.id) for b in blocks):
        progress.last_translated_page = page_index
        progress.save()
        return "cached"
    if all(progress.is_completed(b.id) for b in blocks):
        progress.last_translated_page = page_index
        progress.save()
        return "resumed"
    return None


def _translate_typeset_unit(
    translator,
    page_index: int,
    pending_blocks: list[ContentBlock],
) -> dict[str, str]:
    source_text = _build_marked_text(pending_blocks)
    pending_ids = {block.id for block in pending_blocks}
    translation = _translate_with_retry(
        translator,
        source_text,
        page_num=page_index,
        prev_context="",
        cache=None,
    )
    if translation and translation.lstrip().startswith(TRANSLATION_FAILURE_PREFIX):
        raise RuntimeError(translation)
    return _parse_marked_translations(translation, pending_ids)


def _translate_typeset_content_sequential_legacy(
    content: PageContentDocument,
    translator,
    progress: TypesetTranslationProgress,
    glossary: dict,
    progress_callback: Callable[[int, int, str, bool], None] | None = None,
) -> PageContentDocument:
    if glossary:
        translator.set_glossary(glossary)

    page_units = _collect_translation_units(content, progress)
    total_units = len(page_units)
    previous_context = ""

    for done, (page_index, blocks) in enumerate(page_units, start=1):
        unit_id = blocks[0].id if len(blocks) == 1 else f"p{page_index + 1:04d}"
        expected_ids = {block.id for block in blocks}

        # Check translation cache by source text hash
        all_cached = True
        for block in blocks:
            cache_key = _source_text_hash(block.source_text)
            cached = progress.translation_cache.get(cache_key)
            if cached:
                if not progress.is_completed(block.id):
                    progress.mark_completed(block.id, cached)
            else:
                all_cached = False

        if all_cached and all(progress.is_completed(b.id) for b in blocks):
            if progress_callback:
                progress_callback(done, total_units, f"{unit_id} (cached)", True)
            progress.last_translated_page = page_index
            progress.save()
            continue

        # Filter to only blocks not yet completed
        pending_blocks = [b for b in blocks if not progress.is_completed(b.id)]
        if not pending_blocks:
            if progress_callback:
                progress_callback(done, total_units, f"{unit_id} (resumed)", True)
            progress.last_translated_page = page_index
            progress.save()
            continue

        # Build marked translation request
        source_text = _build_marked_text(pending_blocks)
        pending_ids = {block.id for block in pending_blocks}

        # Call translator with retry
        translation = _translate_with_retry(
            translator,
            source_text,
            page_num=page_index,
            prev_context=previous_context[-900:],
            cache=progress,
        )

        # Handle translation failure
        if translation and translation.lstrip().startswith(TRANSLATION_FAILURE_PREFIX):
            for block in pending_blocks:
                progress.mark_failed(block.id, translation)
            if progress_callback:
                progress_callback(done, total_units, unit_id, False)
            continue

        # Parse marked translations
        try:
            parsed = _parse_marked_translations(translation, pending_ids)
        except ValueError as exc:
            message = f"{TRANSLATION_FAILURE_PREFIX} {exc}]"
            for block in pending_blocks:
                progress.mark_failed(block.id, message)
            if progress_callback:
                progress_callback(done, total_units, unit_id, False)
            continue

        # Record successful translations
        for block_id, block_translation in parsed.items():
            progress.mark_completed(block_id, block_translation)
            # Also cache by source text hash for future reuse
            source_block = next((b for b in pending_blocks if b.id == block_id), None)
            if source_block:
                cache_key = _source_text_hash(source_block.source_text)
                if cache_key not in progress.translation_cache:
                    progress.translation_cache[cache_key] = block_translation

        # Update context for next unit
        previous_context = "\n".join(
            block.source_text for block in blocks if block.source_text
        )

        # Update page progress
        progress.last_translated_page = page_index
        progress.save()

        if progress_callback:
            progress_callback(done, total_units, f"{unit_id} / {len(pending_blocks)} 块", True)

    # Build translated document
    return _build_translated_document(content, progress)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _collect_translation_units(
    content: PageContentDocument,
    progress: TypesetTranslationProgress,
) -> list[tuple[int, list[ContentBlock]]]:
    """Collect translatable blocks as single-block units, skipping completed ones.

    Returns list of (page_index, blocks) tuples where blocks need translation.
    """
    units = []
    for page in content.pages:
        translatable_blocks = [
            block for block in page.blocks
            if block.translatable and block.source_text.strip()
        ]
        for block in translatable_blocks:
            if not progress.is_completed(block.id):
                units.append((page.page_index, [block]))
    return units


def _build_translated_document(
    content: PageContentDocument,
    progress: TypesetTranslationProgress,
) -> PageContentDocument:
    """Build a new PageContentDocument with translated_text filled from progress."""
    from core.typeset_models import (
        ColumnInfo,
        ContentBlock,
        PageContent,
        PageContentDocument,
        StyledTextRun,
    )

    translated_pages = []
    for page in content.pages:
        translated_blocks = []
        for block in page.blocks:
            if block.translatable and progress.is_completed(block.id):
                translated_text = progress.get_translation(block.id)
            else:
                translated_text = block.translated_text
            # Rebuild block with translated_text
            translated_blocks.append(ContentBlock(
                id=block.id,
                region_id=block.region_id,
                role=block.role,
                runs=block.runs,
                source_text=block.source_text,
                translated_text=translated_text,
                translatable=block.translatable,
            ))
        translated_pages.append(PageContent(
            page_index=page.page_index,
            page_type=page.page_type,
            columns=page.columns,
            blocks=translated_blocks,
        ))

    return PageContentDocument(
        schema_version=content.schema_version,
        source_pdf=content.source_pdf,
        page_count=content.page_count,
        pages=translated_pages,
    )


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------


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
    raise PermissionError(
        f"无法写入进度文件，目标可能被其他程序占用：{target_path}"
    ) from last_error


def save_translated_content(content: PageContentDocument, output_path: str):
    """Save translated PageContentDocument to page_content_translated.json."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.to_json(), encoding="utf-8")
