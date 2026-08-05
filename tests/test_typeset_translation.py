"""
Unit tests for core/typeset_translation.py.

Tests cover:
- TypesetTranslationProgress checkpoint/resume
- Translation cache hit logic (source text hash)
- Failed translation recording and retry
- Block marker building and parsing
- translate_typeset_content end-to-end with mock translator
"""

import json
import os
import tempfile
import threading
import time

import pytest

from core.typeset_translation import (
    TypesetTranslationProgress,
    _build_marked_text,
    _parse_marked_translations,
    _source_text_hash,
    _translate_typeset_unit,
    translate_typeset_content,
    save_translated_content,
)
from core.typeset_models import (
    ContentBlock,
    ColumnInfo,
    PageContent,
    PageContentDocument,
    PageType,
    SemanticRole,
    StyledTextRun,
    PAGE_CONTENT_SCHEMA_VERSION,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_block(block_id: str, source_text: str, translatable: bool = True,
                role: SemanticRole = SemanticRole.BODY_COLUMN) -> ContentBlock:
    return ContentBlock(
        id=block_id,
        region_id="r001",
        role=role,
        runs=[StyledTextRun(text=source_text, font_size=11.0, bold=False, italic=False, color="#000000")],
        source_text=source_text,
        translated_text=None,
        translatable=translatable,
    )


def _make_content_doc(blocks_per_page: list[list[ContentBlock]]) -> PageContentDocument:
    pages = []
    for i, blocks in enumerate(blocks_per_page):
        pages.append(PageContent(
            page_index=i,
            page_type=PageType.SINGLE,
            columns=[],
            blocks=blocks,
        ))
    return PageContentDocument(
        schema_version=PAGE_CONTENT_SCHEMA_VERSION,
        source_pdf="test.pdf",
        page_count=len(pages),
        pages=pages,
    )


class MockTranslator:
    """Mock translator that returns predictable translations with [BLOCK] markers."""

    def __init__(self, fail_ids: set[str] | None = None):
        self.fail_ids = fail_ids or set()
        self.glossary = {}
        self.call_count = 0

    def set_glossary(self, glossary: dict):
        self.glossary = glossary

    def translate_chunk(self, text: str, page_num=None, prev_context="", cache=None):
        self.call_count += 1
        # Check if any block in this request should fail
        if self.fail_ids:
            for fail_id in self.fail_ids:
                if f"[BLOCK {fail_id}]" in text:
                    return "[Translation failed: mock failure]"

        # Parse block IDs from the request and return mock translations
        import re
        pattern = re.compile(r"\[BLOCK ([^\]\s]+)\]\n(.*?)\n\[/BLOCK \1\]", re.DOTALL)
        parts = []
        for match in pattern.finditer(text):
            block_id = match.group(1)
            source = match.group(2).strip()
            parts.append(f"[BLOCK {block_id}]\n翻译：{source}\n[/BLOCK {block_id}]")
        return "\n\n".join(parts)


class SlowMockTranslator(MockTranslator):
    def __init__(self, delay: float):
        super().__init__()
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def translate_chunk(self, text: str, page_num=None, prev_context="", cache=None):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay)
            return super().translate_chunk(text, page_num=page_num, prev_context=prev_context, cache=cache)
        finally:
            with self._lock:
                self.active -= 1


class MissingMarkerOnceTranslator(MockTranslator):
    def translate_chunk(self, text: str, page_num=None, prev_context="", cache=None):
        if self.call_count == 0:
            self.call_count += 1
            return "translated text without block markers"
        return super().translate_chunk(text, page_num=page_num, prev_context=prev_context, cache=cache)


# ---------------------------------------------------------------------------
# TypesetTranslationProgress tests
# ---------------------------------------------------------------------------


class TestTypesetTranslationProgress:

    def test_empty_progress_file(self, tmp_path):
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        assert progress.translations == {}
        assert progress.failed_blocks == {}
        assert progress.translation_cache == {}
        assert progress.completed_phases == []
        assert progress.last_translated_page == -1

    def test_save_and_reload(self, tmp_path):
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        progress.mark_completed("block_1", "翻译文本")
        progress.mark_failed("block_2", "API timeout")
        progress.translation_cache["hash123"] = "cached text"
        progress.mark_phase_completed("A")
        progress.last_translated_page = 3
        progress.save()

        # Reload
        progress2 = TypesetTranslationProgress(progress_file)
        assert progress2.translations == {"block_1": "翻译文本"}
        assert progress2.failed_blocks == {"block_2": "API timeout"}
        assert progress2.translation_cache == {"hash123": "cached text"}
        assert progress2.completed_phases == ["A"]
        assert progress2.last_translated_page == 3

    def test_is_completed(self, tmp_path):
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        assert not progress.is_completed("block_1")
        progress.mark_completed("block_1", "text")
        assert progress.is_completed("block_1")

    def test_source_hash_prevents_reusing_translation_for_changed_segment(self, tmp_path):
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        progress.mark_completed("block_1", "旧译文", "old source")

        assert progress.is_completed("block_1", "old source")
        assert not progress.is_completed("block_1", "new source")

    def test_old_untranslated_label_is_not_reused(self, tmp_path):
        progress = TypesetTranslationProgress(str(tmp_path / "progress.json"))
        source = "ETERNAL: In theory, Ghroth can be destroyed."
        progress.translations["block_1"] = "ETERNAL: 理论上，格赫罗斯可以被摧毁。"
        progress.source_hashes["block_1"] = _source_text_hash(source)
        progress.translation_cache[_source_text_hash(source)] = progress.translations["block_1"]

        assert not progress.is_completed("block_1", source)
        assert progress.get_translation("block_1", source) == ""
        assert progress.get_cached_prompt_translation(_source_text_hash(source), source) == ""

    def test_legacy_progress_schema_is_not_reused(self, tmp_path):
        progress_file = tmp_path / "progress.json"
        progress_file.write_text(
            '{"schema":1,"translations":{"block_1":"旧译文"}}',
            encoding="utf-8",
        )

        progress = TypesetTranslationProgress(str(progress_file))
        assert not progress.is_completed("block_1", "source")

    def test_mark_completed_clears_failed(self, tmp_path):
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        progress.mark_failed("block_1", "error")
        assert "block_1" in progress.failed_blocks
        progress.mark_completed("block_1", "success")
        assert "block_1" not in progress.failed_blocks
        assert progress.translations["block_1"] == "success"

    def test_mark_failed_clears_translation(self, tmp_path):
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        progress.mark_completed("block_1", "text")
        progress.mark_failed("block_1", "error")
        assert "block_1" not in progress.translations
        assert progress.failed_blocks["block_1"] == "error"

    def test_clear_failed_blocks(self, tmp_path):
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        progress.mark_failed("b1", "err1")
        progress.mark_failed("b2", "err2")
        progress.mark_failed("b3", "err3")
        cleared = progress.clear_failed_blocks({"b1", "b3"})
        assert cleared == 2
        assert progress.failed_blocks == {"b2": "err2"}

    def test_cache_interface(self, tmp_path):
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        assert progress.get_cached_prompt_translation("key1") == ""
        progress.mark_cached_prompt_translation("key1", "cached")
        assert progress.get_cached_prompt_translation("key1") == "cached"

    def test_empty_block_id_raises(self, tmp_path):
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        with pytest.raises(ValueError):
            progress.mark_completed("", "text")
        with pytest.raises(ValueError):
            progress.mark_failed("", "error")

    def test_empty_translation_raises(self, tmp_path):
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        with pytest.raises(ValueError):
            progress.mark_completed("block_1", "")


# ---------------------------------------------------------------------------
# Block marker tests
# ---------------------------------------------------------------------------


class TestBlockMarkers:

    def test_build_marked_text(self):
        blocks = [
            _make_block("b1", "Hello world"),
            _make_block("b2", "Second block"),
        ]
        result = _build_marked_text(blocks)
        assert "Translate each block below" not in result
        assert "[BLOCK b1]" in result
        assert "Hello world" in result
        assert "[/BLOCK b1]" in result
        assert "[BLOCK b2]" in result
        assert "Second block" in result
        assert "[/BLOCK b2]" in result

    def test_build_marked_text_removes_pdf_soft_hyphens(self):
        result = _build_marked_text([_make_block("b1", "Ze\u00adlother")])

        assert "Zelother" in result
        assert "\u00ad" not in result

    def test_build_marked_text_can_preserve_exact_source_emphasis(self):
        block = ContentBlock(
            id="b1", region_id="r1", role=SemanticRole.BODY_COLUMN,
            runs=[
                StyledTextRun("普通", 10.0, False, False, "#000"),
                StyledTextRun("重点", 10.0, True, False, "#000"),
            ],
            source_text="普通重点", translated_text=None, translatable=True,
        )

        result = _build_marked_text([block], preserve_emphasis=True)

        assert "普通<strong>重点</strong>" in result

    def test_parse_marked_translations_success(self):
        text = "[BLOCK b1]\n翻译1\n[/BLOCK b1]\n\n[BLOCK b2]\n翻译2\n[/BLOCK b2]"
        result = _parse_marked_translations(text, {"b1", "b2"})
        assert result == {"b1": "翻译1", "b2": "翻译2"}

    def test_parse_marked_translations_removes_soft_hyphens(self):
        result = _parse_marked_translations("[BLOCK b1]\n千魂\u00ad水蛭\n[/BLOCK b1]", {"b1"})

        assert result == {"b1": "千魂水蛭"}

    def test_parse_marked_translations_accepts_only_balanced_emphasis_tags(self):
        result = _parse_marked_translations("[BLOCK b1]\n<strong>重点</strong>\n[/BLOCK b1]", {"b1"})

        assert result == {"b1": "<strong>重点</strong>"}
        with pytest.raises(ValueError, match="不允许的 HTML 标记"):
            _parse_marked_translations("[BLOCK b1]\n<a>重点</a>\n[/BLOCK b1]", {"b1"})

    def test_parse_marked_translations_missing_block(self):
        text = "[BLOCK b1]\n翻译1\n[/BLOCK b1]"
        with pytest.raises(ValueError, match="缺少"):
            _parse_marked_translations(text, {"b1", "b2"})

    def test_parse_marked_translations_extra_block(self):
        text = "[BLOCK b1]\n翻译1\n[/BLOCK b1]\n\n[BLOCK b2]\n翻译2\n[/BLOCK b2]\n\n[BLOCK b3]\n翻译3\n[/BLOCK b3]"
        with pytest.raises(ValueError, match="多余"):
            _parse_marked_translations(text, {"b1", "b2"})

    def test_parse_marked_translations_empty_translation(self):
        text = "[BLOCK b1]\n\n[/BLOCK b1]"
        with pytest.raises(ValueError, match="译文为空"):
            _parse_marked_translations(text, {"b1"})

    def test_parse_marked_translations_duplicate(self):
        text = "[BLOCK b1]\n翻译1\n[/BLOCK b1]\n\n[BLOCK b1]\n翻译2\n[/BLOCK b1]"
        with pytest.raises(ValueError, match="重复"):
            _parse_marked_translations(text, {"b1"})

    def test_parse_marked_translations_rejects_elision_placeholder(self):
        text = "[BLOCK b1]\n《新时代》的触发事件是[...]之间的信任丧失。\n[/BLOCK b1]"
        with pytest.raises(ValueError, match="省略占位符"):
            _parse_marked_translations(text, {"b1"})

    def test_parse_marked_translations_rejects_untranslated_prose_label(self):
        text = "[BLOCK b1]\nETERNAL: 理论上，格赫罗斯可以被摧毁。\n[/BLOCK b1]"
        with pytest.raises(ValueError, match="ETERNAL"):
            _parse_marked_translations(
                text,
                {"b1"},
                {"b1": "ETERNAL: In theory, Ghroth can be destroyed."},
            )

    def test_parse_marked_translations_rejects_prompt_leak(self):
        text = (
            "[BLOCK b1]\n您是专业的TRPG翻译，翻译规则包括："
            "严格遵循术语表，输出Markdown。\n[/BLOCK b1]"
        )
        with pytest.raises(ValueError, match="内部翻译指令"):
            _parse_marked_translations(text, {"b1"})


# ---------------------------------------------------------------------------
# Source text hash tests
# ---------------------------------------------------------------------------


class TestSourceTextHash:

    def test_deterministic(self):
        h1 = _source_text_hash("hello")
        h2 = _source_text_hash("hello")
        assert h1 == h2

    def test_different_text_different_hash(self):
        h1 = _source_text_hash("hello")
        h2 = _source_text_hash("world")
        assert h1 != h2

    def test_soft_hyphen_does_not_change_translation_cache_key(self):
        assert _source_text_hash("Ze\u00adlother") == _source_text_hash("Zelother")


# ---------------------------------------------------------------------------
# translate_typeset_content integration tests
# ---------------------------------------------------------------------------


class TestTranslateTypesetContent:

    def test_basic_translation(self, tmp_path):
        """Translatable blocks get translated, non-translatable blocks are skipped."""
        blocks = [
            _make_block("b1", "Hello world", translatable=True),
            _make_block("b2", "Page header", translatable=False, role=SemanticRole.HEADER),
            _make_block("b3", "Another paragraph", translatable=True),
        ]
        content = _make_content_doc([blocks])
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        translator = MockTranslator()

        result = translate_typeset_content(content, translator, progress, {})

        # b1 and b3 should be translated
        page = result.pages[0]
        b1 = next(b for b in page.blocks if b.id == "b1")
        b2 = next(b for b in page.blocks if b.id == "b2")
        b3 = next(b for b in page.blocks if b.id == "b3")
        assert b1.translated_text == "翻译：Hello world"
        assert b2.translated_text is None  # header, not translated
        assert b3.translated_text == "翻译：Another paragraph"
        assert translator.call_count == 2

    def test_checkpoint_resume(self, tmp_path):
        """Already-translated blocks are skipped on resume."""
        blocks = [
            _make_block("b1", "Hello world"),
            _make_block("b2", "Second block"),
        ]
        content = _make_content_doc([blocks])
        progress_file = str(tmp_path / "progress.json")

        # Pre-populate progress with b1 already done
        progress = TypesetTranslationProgress(progress_file)
        progress.mark_completed("b1", "已翻译")
        progress.save()

        # Reload and translate
        progress = TypesetTranslationProgress(progress_file)
        translator = MockTranslator()
        result = translate_typeset_content(content, translator, progress, {})

        page = result.pages[0]
        b1 = next(b for b in page.blocks if b.id == "b1")
        b2 = next(b for b in page.blocks if b.id == "b2")
        assert b1.translated_text == "已翻译"  # from progress, not re-translated
        assert b2.translated_text == "翻译：Second block"

    def test_translation_failure_recorded(self, tmp_path):
        """Failed translations are recorded in progress."""
        blocks = [_make_block("b1", "Hello world")]
        content = _make_content_doc([blocks])
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        translator = MockTranslator(fail_ids={"b1"})

        result = translate_typeset_content(content, translator, progress, {})

        assert "b1" in progress.failed_blocks
        page = result.pages[0]
        b1 = next(b for b in page.blocks if b.id == "b1")
        assert b1.translated_text is None  # failed, no translation

    def test_missing_marker_is_retried(self):
        block = _make_block("b1", "Hello world")
        translator = MissingMarkerOnceTranslator()

        parsed = _translate_typeset_unit(translator, 0, [block])

        assert parsed == {"b1": "翻译：Hello world"}
        assert translator.call_count == 2

    def test_glossary_applied(self, tmp_path):
        """Glossary is set on translator."""
        blocks = [_make_block("b1", "The Agent investigates")]
        content = _make_content_doc([blocks])
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        glossary = {"Agent": "特工", "Delta Green": "绿色三角洲"}
        translator = MockTranslator()

        translate_typeset_content(content, translator, progress, glossary)
        assert translator.glossary == glossary

    def test_translation_cache_hit(self, tmp_path):
        """Cached translations by source hash are reused."""
        blocks = [_make_block("b1", "Hello world")]
        content = _make_content_doc([blocks])
        progress_file = str(tmp_path / "progress.json")

        # Pre-populate cache with hash of "Hello world"
        progress = TypesetTranslationProgress(progress_file)
        cache_key = _source_text_hash("Hello world")
        progress.translation_cache[cache_key] = "缓存翻译"
        progress.save()

        # Reload and translate
        progress = TypesetTranslationProgress(progress_file)
        translator = MockTranslator()
        result = translate_typeset_content(content, translator, progress, {})

        page = result.pages[0]
        b1 = next(b for b in page.blocks if b.id == "b1")
        assert b1.translated_text == "缓存翻译"
        # Translator should not have been called (cache hit)
        assert translator.call_count == 0

    def test_progress_callback_called(self, tmp_path):
        """Progress callback is invoked for each page unit."""
        blocks = [_make_block("b1", "Hello")]
        content = _make_content_doc([blocks])
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        translator = MockTranslator()

        callbacks = []
        def cb(done, total, unit_id, success):
            callbacks.append((done, total, unit_id, success))

        translate_typeset_content(content, translator, progress, {}, progress_callback=cb)
        assert len(callbacks) == 1
        assert callbacks[0][0] == 1  # done
        assert callbacks[0][1] == 1  # total
        assert callbacks[0][3] is True  # success

    def test_single_block_units_run_concurrently(self, tmp_path):
        blocks = [_make_block(f"b{i}", f"Block {i}") for i in range(4)]
        content = _make_content_doc([blocks])
        progress_file = str(tmp_path / "progress.json")
        progress = TypesetTranslationProgress(progress_file)
        translator = SlowMockTranslator(delay=0.08)

        start = time.perf_counter()
        result = translate_typeset_content(
            content,
            translator,
            progress,
            {},
            max_workers=4,
        )
        elapsed = time.perf_counter() - start

        assert translator.call_count == 4
        assert translator.max_active > 1
        assert elapsed < 0.28
        assert all(block.translated_text for block in result.pages[0].blocks)


# ---------------------------------------------------------------------------
# save_translated_content tests
# ---------------------------------------------------------------------------


class TestSaveTranslatedContent:

    def test_save_and_load(self, tmp_path):
        blocks = [_make_block("b1", "Hello", translatable=True)]
        content = _make_content_doc([blocks])
        output_path = str(tmp_path / "output" / "page_content_translated.json")
        save_translated_content(content, output_path)

        assert os.path.exists(output_path)
        loaded = PageContentDocument.from_json(
            open(output_path, "r", encoding="utf-8").read()
        )
        assert loaded.pages[0].blocks[0].source_text == "Hello"
