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
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Callable, Mapping

from core.constants import TRANSLATION_FAILURE_PREFIX
from core.translation_validation import (
    contains_damaged_placeholder,
    contains_elision_placeholder,
    contains_japanese_kana,
    contains_prompt_leak,
    ensure_no_damaged_placeholder,
    ensure_no_elision_placeholder,
    ensure_no_japanese_kana,
    ensure_no_prompt_leak,
    ensure_no_untranslated_leading_labels,
    untranslated_leading_labels,
)
from core.utils import replace_with_retry
from core.typeset_models import (
    ContentBlock,
    PageContent,
    PageContentDocument,
)


# ---------------------------------------------------------------------------
# TypesetTranslationProgress — checkpoint/resume for typeset translation
# ---------------------------------------------------------------------------


def _is_unusable_translation(text: str, source_text: str | None = None) -> bool:
    """Stored translations from an older run may predate current validation."""
    return (
        contains_prompt_leak(text)
        or contains_damaged_placeholder(text)
        or contains_elision_placeholder(text)
        or contains_japanese_kana(text)
        or "\u00ad" in text
        or bool(source_text and untranslated_leading_labels(source_text, text))
    )


class TypesetTranslationProgress:
    """Progress file for typeset pipeline block-level translation.

    Stores completed translations, failed blocks, and prompt-level cache.
    Supports checkpoint/resume: on restart, already-translated blocks are skipped.
    """

    def __init__(self, progress_file: str, context_signature: str = ""):
        if not progress_file:
            raise ValueError("progress_file 不能为空")
        self.progress_file = progress_file
        self.context_signature = context_signature
        self.translations: dict[str, str] = {}
        self.source_hashes: dict[str, str] = {}
        self.failed_blocks: dict[str, str] = {}
        self.translation_cache: dict[str, str] = {}
        # Targeted overflow repairs must never reuse a normal translation merely
        # because the source text is the same.  These entries are keyed by the
        # caller-supplied layout target signature as well as the source text.
        self.targeted_translation_cache: dict[str, str] = {}
        self.targeted_translation_contexts: dict[str, str] = {}
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
        if data.get("schema") != 2:
            return
        if self.context_signature and data.get("context_signature") != self.context_signature:
            return
        self.translations = dict(data.get("translations") or {})
        self.source_hashes = dict(data.get("source_hashes") or {})
        self.failed_blocks = dict(data.get("failed_blocks") or {})
        self.translation_cache = dict(data.get("translation_cache") or {})
        self.targeted_translation_cache = dict(
            data.get("targeted_translation_cache") or {}
        )
        self.targeted_translation_contexts = dict(
            data.get("targeted_translation_contexts") or {}
        )
        self.completed_phases = list(data.get("completed_phases") or [])
        self.last_translated_page = int(data.get("last_translated_page", -1))

    def save(self):
        with self._lock:
            data = {
                "schema": 2,
                "pipeline": "typeset",
                "context_signature": self.context_signature,
                "translations": self.translations,
                "source_hashes": self.source_hashes,
                "failed_blocks": self.failed_blocks,
                "translation_cache": self.translation_cache,
                "targeted_translation_cache": self.targeted_translation_cache,
                "targeted_translation_contexts": self.targeted_translation_contexts,
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
            replace_with_retry(tmp_path, progress_path)

    # -- Query methods --

    def is_completed(self, block_id: str, source_text: str | None = None) -> bool:
        with self._lock:
            if block_id not in self.translations:
                return False
            if source_text is not None:
                stored_hash = self.source_hashes.get(block_id)
                if stored_hash not in {"*", _source_text_hash(source_text)}:
                    return False
            return not _is_unusable_translation(
                self.translations.get(block_id, ""), source_text
            )

    def get_translation(self, block_id: str, source_text: str | None = None) -> str:
        with self._lock:
            translation = self.translations.get(block_id, "")
        if _is_unusable_translation(translation, source_text):
            return ""
        return translation

    def get_failed_blocks(self) -> set[str]:
        with self._lock:
            return set(self.failed_blocks)

    # -- Cache interface (compatible with Translator.translate_chunk cache param) --

    def get_cached_prompt_translation(
        self,
        cache_key: str,
        source_text: str | None = None,
    ) -> str:
        with self._lock:
            translation = self.translation_cache.get(cache_key, "")
        if _is_unusable_translation(translation, source_text):
            return ""
        return translation

    def mark_cached_prompt_translation(
        self,
        cache_key: str,
        translation: str,
        source_text: str | None = None,
    ):
        translation = _translation_source_text(translation)
        if cache_key and translation:
            ensure_no_prompt_leak(translation, "缓存译文")
            ensure_no_damaged_placeholder(translation, "缓存译文")
            ensure_no_elision_placeholder(translation, "缓存译文")
            ensure_no_japanese_kana(translation, "缓存译文")
            if source_text is not None:
                ensure_no_untranslated_leading_labels(
                    source_text, translation, "缓存译文"
                )
            with self._lock:
                self.translation_cache[cache_key] = translation
                self.save()

    def delete_cached_prompt_translation(self, cache_key: str):
        if not cache_key:
            return
        with self._lock:
            removed = self.translation_cache.pop(cache_key, None)
            if removed is not None:
                self.save()

    def get_targeted_translation(
        self,
        block_id: str,
        source_text: str,
        target_signature: str,
    ) -> str:
        """Return a cached overflow repair only for the exact layout target."""
        cache_key = _targeted_translation_cache_key(
            block_id, source_text, target_signature
        )
        with self._lock:
            if self.targeted_translation_contexts.get(cache_key) != target_signature:
                return ""
            translation = self.targeted_translation_cache.get(cache_key, "")
        if _is_unusable_translation(translation, source_text):
            return ""
        return translation

    def mark_targeted_translation(
        self,
        block_id: str,
        source_text: str,
        target_signature: str,
        translation: str,
    ) -> None:
        """Persist a repair result under its exact layout target signature."""
        if not block_id:
            raise ValueError("block_id 不能为空")
        if not target_signature:
            raise ValueError("目标签名不能为空")
        translation = _translation_source_text(translation)
        if not translation:
            raise ValueError(f"译文为空：{block_id}")
        ensure_no_prompt_leak(translation)
        ensure_no_damaged_placeholder(translation)
        ensure_no_elision_placeholder(translation)
        ensure_no_japanese_kana(translation)
        ensure_no_untranslated_leading_labels(source_text, translation)
        cache_key = _targeted_translation_cache_key(
            block_id, source_text, target_signature
        )
        with self._lock:
            self.targeted_translation_cache[cache_key] = translation
            self.targeted_translation_contexts[cache_key] = target_signature
            self.save()

    def get_targeted_group_translations(
        self,
        blocks: list[ContentBlock],
        target_signature: str,
    ) -> dict[str, str]:
        """Return a cached repair only when the whole shared target matches."""
        cache_key = _targeted_group_cache_key(blocks, target_signature)
        with self._lock:
            if self.targeted_translation_contexts.get(cache_key) != target_signature:
                return {}
            raw = self.targeted_translation_cache.get(cache_key, "")
        try:
            translations = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
        expected_ids = [block.id for block in blocks]
        if not isinstance(translations, dict) or set(translations) != set(expected_ids):
            return {}
        normalized = {block_id: str(translations[block_id]) for block_id in expected_ids}
        if any(
            _is_unusable_translation(normalized[block.id], block.source_text)
            for block in blocks
        ):
            return {}
        return normalized

    def mark_targeted_group_translations(
        self,
        blocks: list[ContentBlock],
        target_signature: str,
        translations: Mapping[str, str],
    ) -> None:
        """Persist one atomic shared-target translation result."""
        expected_ids = [block.id for block in blocks]
        if set(translations) != set(expected_ids):
            raise ValueError("成组溢出译文的块 ID 不完整")
        normalized = {
            block.id: _translation_source_text(str(translations[block.id]))
            for block in blocks
        }
        for block in blocks:
            translation = normalized[block.id]
            if not translation:
                raise ValueError(f"译文为空：{block.id}")
            ensure_no_prompt_leak(translation)
            ensure_no_damaged_placeholder(translation)
            ensure_no_elision_placeholder(translation)
            ensure_no_japanese_kana(translation)
            ensure_no_untranslated_leading_labels(block.source_text, translation)
        cache_key = _targeted_group_cache_key(blocks, target_signature)
        with self._lock:
            self.targeted_translation_cache[cache_key] = json.dumps(
                normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            self.targeted_translation_contexts[cache_key] = target_signature
            self.save()

    # -- Mutation methods --

    def mark_completed(
        self,
        block_id: str,
        translation: str,
        source_text: str | None = None,
    ):
        if not block_id:
            raise ValueError("block_id 不能为空")
        translation = _translation_source_text(translation)
        if not translation:
            raise ValueError(f"译文为空：{block_id}")
        ensure_no_prompt_leak(translation)
        ensure_no_damaged_placeholder(translation)
        ensure_no_elision_placeholder(translation)
        ensure_no_japanese_kana(translation)
        if source_text is not None:
            ensure_no_untranslated_leading_labels(source_text, translation)
        with self._lock:
            self.translations[block_id] = translation
            self.source_hashes[block_id] = (
                _source_text_hash(source_text) if source_text is not None else "*"
            )
            self.failed_blocks.pop(block_id, None)
            self.save()

    def mark_failed(self, block_id: str, message: str):
        if not block_id:
            raise ValueError("block_id 不能为空")
        with self._lock:
            self.translations.pop(block_id, None)
            self.source_hashes.pop(block_id, None)
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
    return hashlib.sha256(_translation_source_text(text).encode("utf-8")).hexdigest()


def _overflow_target_signature(target_metadata: Mapping[str, object]) -> str:
    """Create a deterministic signature for a caller-defined layout target."""
    _validate_overflow_target_metadata(target_metadata)
    encoded = json.dumps(
        dict(target_metadata), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _targeted_translation_cache_key(
    block_id: str,
    source_text: str,
    target_signature: str,
) -> str:
    payload = {
        "block_id": block_id,
        "source_hash": _source_text_hash(source_text),
        "target_signature": target_signature,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _targeted_group_cache_key(
    blocks: list[ContentBlock],
    target_signature: str,
) -> str:
    payload = {
        "block_ids": [block.id for block in blocks],
        "source_hashes": [_source_text_hash(block.source_text) for block in blocks],
        "target_signature": target_signature,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_overflow_target_metadata(target_metadata: Mapping[str, object]) -> None:
    """Require explicit constraints instead of inventing a text-length budget."""
    if not isinstance(target_metadata, Mapping):
        raise ValueError("溢出目标元数据必须是映射")
    required = ("capacity", "template_signature", "constraint_prompt")
    missing = [key for key in required if not str(target_metadata.get(key, "")).strip()]
    if missing:
        raise ValueError("溢出目标元数据缺少：" + "、".join(missing))


def _validate_overflow_group_metadata(group_metadata: Mapping[str, object]) -> list[str]:
    _validate_overflow_target_metadata(group_metadata)
    block_ids = group_metadata.get("block_ids")
    if not isinstance(block_ids, list) or not block_ids or not all(
        isinstance(block_id, str) and block_id for block_id in block_ids
    ):
        raise ValueError("溢出目标组必须包含非空 block_ids")
    if len(set(block_ids)) != len(block_ids):
        raise ValueError("溢出目标组包含重复 block_id")
    return list(block_ids)


def _overflow_constraint_context(target_metadata: Mapping[str, object]) -> str:
    """Supply the caller's layout instruction as non-translated model context."""
    _validate_overflow_target_metadata(target_metadata)
    return (
        "[Layout constraint for this block - DO NOT translate]\n"
        + str(target_metadata["constraint_prompt"]).strip()
    )


def _translation_source_text(text: str) -> str:
    """Remove PDF soft hyphens before translation and cache matching."""
    return (text or "").replace("\u00ad", "")


# ---------------------------------------------------------------------------
# Block marker formatting and parsing
# ---------------------------------------------------------------------------


def _build_marked_text(
    blocks: list[ContentBlock],
    preserve_emphasis: bool = False,
) -> str:
    """Build translation request text with [BLOCK id] markers."""
    parts = []
    for block in blocks:
        source_text = (
            _source_text_with_emphasis(block)
            if preserve_emphasis
            else _translation_source_text(block.source_text)
        )
        parts.append(
            f"[BLOCK {block.id}]\n{source_text}\n[/BLOCK {block.id}]"
        )
    return "\n\n".join(parts)


def _source_text_with_emphasis(block: ContentBlock) -> str:
    """Annotate source emphasis only when the extracted runs exactly cover the block."""
    source = _translation_source_text(block.source_text)
    runs_text = "".join(_translation_source_text(run.text) for run in block.runs)
    if not source or runs_text != source:
        return source
    parts: list[str] = []
    for run in block.runs:
        text = _translation_source_text(run.text)
        if not text:
            continue
        if run.bold:
            text = f"<strong>{text}</strong>"
        if run.italic:
            text = f"<em>{text}</em>"
        parts.append(text)
    return "".join(parts)


def _parse_marked_translations(
    text: str,
    expected_ids: set[str],
    source_text_by_id: dict[str, str] | None = None,
) -> dict[str, str]:
    """Parse translation response to extract per-block translations."""
    ensure_no_prompt_leak(text, "模型返回")
    ensure_no_japanese_kana(text, "模型返回")
    pattern = re.compile(
        r"\[BLOCK ([^\]\s]+)\]\s*(.*?)\s*\[/BLOCK \1\]",
        re.DOTALL,
    )
    parsed = {}
    for match in pattern.finditer(text):
        block_id = match.group(1).strip()
        translated = _translation_source_text(match.group(2)).strip()
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
    for block_id, translated in parsed.items():
        _ensure_valid_emphasis_markup(translated, f"译文块 {block_id}")
        ensure_no_prompt_leak(translated, f"译文块 {block_id}")
        ensure_no_damaged_placeholder(translated, f"译文块 {block_id}")
        ensure_no_elision_placeholder(translated, f"译文块 {block_id}")
        ensure_no_japanese_kana(translated, f"译文块 {block_id}")
        if source_text_by_id is not None:
            ensure_no_untranslated_leading_labels(
                source_text_by_id[block_id], translated, f"译文块 {block_id}"
            )
    return parsed


def _ensure_valid_emphasis_markup(text: str, context: str) -> None:
    tags = re.findall(r"<[^>]*>", text)
    stack: list[str] = []
    for tag in tags:
        match = re.fullmatch(r"<(\/)?(strong|em)>", tag)
        if not match:
            raise ValueError(f"{context} 包含不允许的 HTML 标记：{tag}")
        is_closing, name = match.groups()
        if is_closing:
            if not stack or stack.pop() != name:
                raise ValueError(f"{context} 的强调标记未正确闭合")
        else:
            stack.append(name)
    if stack:
        raise ValueError(f"{context} 的强调标记未正确闭合")


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
    preserve_emphasis: bool = False,
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

            pending_blocks = [
                b for b in blocks
                if not progress.is_completed(b.id, b.source_text)
            ]
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
                preserve_emphasis,
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
                progress.mark_completed(block.id, block_translation, block.source_text)
                progress.mark_cached_prompt_translation(
                    _source_text_hash(block.source_text),
                    block_translation,
                    block.source_text,
                )

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
        cached = progress.get_cached_prompt_translation(cache_key, block.source_text)
        if cached:
            if not progress.is_completed(block.id, block.source_text):
                progress.mark_completed(block.id, cached, block.source_text)
        else:
            all_cached = False

    if all_cached and all(progress.is_completed(b.id, b.source_text) for b in blocks):
        progress.last_translated_page = page_index
        progress.save()
        return "cached"
    if all(progress.is_completed(b.id, b.source_text) for b in blocks):
        progress.last_translated_page = page_index
        progress.save()
        return "resumed"
    return None


def _translate_typeset_unit(
    translator,
    page_index: int,
    pending_blocks: list[ContentBlock],
    preserve_emphasis: bool = False,
    constraint_context: str = "",
    cache=None,
) -> dict[str, str]:
    source_text = _build_marked_text(pending_blocks, preserve_emphasis=preserve_emphasis)
    pending_ids = {block.id for block in pending_blocks}
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        translation = _translate_with_retry(
            translator,
            source_text,
            page_num=page_index,
            prev_context=constraint_context,
            cache=cache,
        )
        if translation and translation.lstrip().startswith(TRANSLATION_FAILURE_PREFIX):
            last_error = RuntimeError(translation)
        else:
            try:
                return _parse_marked_translations(
                    translation,
                    pending_ids,
                    {block.id: block.source_text for block in pending_blocks},
                )
            except ValueError as exc:
                last_error = exc
        if attempt < MAX_RETRIES - 1:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            time.sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"{TRANSLATION_FAILURE_PREFIX} empty translation]")


def translate_overflow_groups(
    content: PageContentDocument,
    translator,
    progress: TypesetTranslationProgress,
    glossary: dict,
    target_groups: Mapping[str, Mapping[str, object]],
    progress_callback: Callable[[int, int, str, bool], None] | None = None,
    preserve_emphasis: bool = False,
) -> PageContentDocument:
    """Retranslate one shared layout target at a time.

    A group owns one measured container.  Its blocks must therefore be
    translated together: passing the full marked group to the model prevents
    every child from incorrectly consuming the container's full capacity.
    """
    if not target_groups:
        raise ValueError("至少指定一个溢出目标组")
    if glossary:
        translator.set_glossary(glossary)

    blocks_by_id = {
        block.id: (page.page_index, block)
        for page in content.pages
        for block in page.blocks
    }
    replacements: dict[str, str] = {}
    assigned_block_ids: set[str] = set()
    selected_groups: list[tuple[str, int, list[ContentBlock], Mapping[str, object]]] = []
    for group_id, metadata in target_groups.items():
        if not isinstance(group_id, str) or not group_id:
            raise ValueError("溢出目标组 ID 无效")
        block_ids = _validate_overflow_group_metadata(metadata)
        unknown = sorted(set(block_ids) - set(blocks_by_id))
        if unknown:
            raise ValueError("溢出目标不存在：" + "、".join(unknown[:10]))
        overlap = sorted(assigned_block_ids.intersection(block_ids))
        if overlap:
            raise ValueError("溢出目标组重复包含文字块：" + "、".join(overlap[:10]))
        assigned_block_ids.update(block_ids)
        selected = [blocks_by_id[block_id] for block_id in block_ids]
        page_indexes = {page_index for page_index, _ in selected}
        if len(page_indexes) != 1:
            raise ValueError(f"溢出目标组跨页：{group_id}")
        blocks = [block for _, block in selected]
        invalid = [block.id for block in blocks if not block.translatable or not block.source_text.strip()]
        if invalid:
            raise ValueError("溢出目标不可翻译：" + "、".join(invalid[:10]))
        selected_groups.append((group_id, page_indexes.pop(), blocks, metadata))

    total = len(selected_groups)
    for done, (group_id, page_index, blocks, metadata) in enumerate(selected_groups, start=1):
        target_signature = _overflow_target_signature(metadata)
        cached = progress.get_targeted_group_translations(blocks, target_signature)
        if cached:
            for block in blocks:
                progress.mark_completed(block.id, cached[block.id], block.source_text)
                replacements[block.id] = cached[block.id]
            if progress_callback:
                progress_callback(done, total, f"{group_id} (target cached)", True)
            continue

        try:
            parsed = _translate_typeset_unit(
                translator,
                page_index,
                blocks,
                preserve_emphasis=preserve_emphasis,
                constraint_context=_overflow_constraint_context(metadata),
                cache=None,
            )
            progress.mark_targeted_group_translations(blocks, target_signature, parsed)
            for block in blocks:
                progress.mark_completed(block.id, parsed[block.id], block.source_text)
                replacements[block.id] = parsed[block.id]
        except Exception as exc:
            message = f"{TRANSLATION_FAILURE_PREFIX} {exc}]"
            for block in blocks:
                progress.mark_failed(block.id, message)
            if progress_callback:
                progress_callback(done, total, group_id, False)
            raise RuntimeError(f"溢出区域翻译失败：{group_id}") from exc
        if progress_callback:
            progress_callback(done, total, group_id, True)

    return _replace_translations(content, replacements)


def translate_overflow_targets(
    content: PageContentDocument,
    translator,
    progress: TypesetTranslationProgress,
    glossary: dict,
    target_metadata_by_block: Mapping[str, Mapping[str, object]],
    progress_callback: Callable[[int, int, str, bool], None] | None = None,
    preserve_emphasis: bool = False,
) -> PageContentDocument:
    """Backward-compatible one-block wrapper for legacy callers."""
    groups = {
        f"legacy:{block_id}": {**dict(metadata), "block_ids": [block_id]}
        for block_id, metadata in target_metadata_by_block.items()
    }
    return translate_overflow_groups(
        content,
        translator,
        progress,
        glossary,
        groups,
        progress_callback=progress_callback,
        preserve_emphasis=preserve_emphasis,
    )

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
            if not progress.is_completed(block.id, block.source_text):
                units.append((page.page_index, [block]))
    return units


def _build_translated_document(
    content: PageContentDocument,
    progress: TypesetTranslationProgress,
) -> PageContentDocument:
    """Build a new PageContentDocument with translated_text filled from progress."""
    from core.typeset_models import PageContent, PageContentDocument

    translated_pages = []
    for page in content.pages:
        translated_blocks = []
        for block in page.blocks:
            if block.translatable and progress.is_completed(block.id, block.source_text):
                translated_text = progress.get_translation(block.id, block.source_text)
            else:
                translated_text = block.translated_text
            translated_blocks.append(replace(block, translated_text=translated_text))
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
        source_sha256=content.source_sha256,
    )


def _replace_translations(
    content: PageContentDocument,
    replacements: Mapping[str, str],
) -> PageContentDocument:
    """Return a copy with only the requested block translations changed."""
    translated_pages = []
    for page in content.pages:
        translated_pages.append(
            replace(
                page,
                blocks=[
                    replace(block, translated_text=replacements[block.id])
                    if block.id in replacements else block
                    for block in page.blocks
                ],
            )
        )
    return replace(content, pages=translated_pages)


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------


def save_translated_content(content: PageContentDocument, output_path: str):
    """Save translated PageContentDocument to page_content_translated.json."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.to_json(), encoding="utf-8")
