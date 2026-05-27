"""
Unit tests for core.recursive_splitter.recursive_translate_group.

Tests cover:
- Single-block success and failure
- Multi-block full success
- Multi-block partial success with recursive retry
- Complete failure triggering binary split
- Depth limit enforcement
- Progress callback invocation
- API call and split count tracking
"""

from dataclasses import dataclass

from core.recursive_splitter import recursive_translate_group, SplitResult


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeBlock:
    """Minimal block with .index and .text for testing."""
    index: int
    text: str


def make_group(n: int, start_index: int = 0) -> list[FakeBlock]:
    """Create a group of n fake blocks."""
    return [FakeBlock(index=start_index + i, text=f"Block {start_index + i} text") for i in range(n)]


def build_text_fn(group: list[FakeBlock]) -> str:
    """Serialize blocks with BLOCK markers (multi-block format)."""
    return "\n\n".join(
        f"[BLOCK {b.index}]\n{b.text}\n[/BLOCK {b.index}]"
        for b in group
    )


def make_always_succeed_translate(response_map: dict[str, str] | None = None):
    """Create a translate_fn that always returns a valid translation."""
    calls = []

    def translate_fn(text, block_index=None, prev_context="", source_type="markdown", cache=None):
        calls.append({"text": text, "block_index": block_index})
        if response_map and text in response_map:
            return response_map[text]
        # For single blocks, return translated text directly
        if "[BLOCK" not in text:
            return f"翻译: {text}"
        # For multi-block, return all BLOCK markers with translations
        import re
        result_parts = []
        for m in re.finditer(r"\[BLOCK (\d+)\]\n(.*?)\n\[/BLOCK \1\]", text, re.DOTALL):
            idx = m.group(1)
            result_parts.append(f"[BLOCK {idx}]\n翻译: {m.group(2)}\n[/BLOCK {idx}]")
        return "\n\n".join(result_parts)

    return translate_fn, calls


def make_always_fail_translate():
    """Create a translate_fn that always returns empty string (failure)."""
    calls = []

    def translate_fn(text, block_index=None, prev_context="", source_type="markdown", cache=None):
        calls.append({"text": text, "block_index": block_index})
        return ""

    return translate_fn, calls


def make_partial_success_translate(success_indices: set[int]):
    """Create a translate_fn that only succeeds for certain block indices."""
    calls = []

    def translate_fn(text, block_index=None, prev_context="", source_type="markdown", cache=None):
        calls.append({"text": text, "block_index": block_index})
        # Single block
        if "[BLOCK" not in text:
            if block_index in success_indices:
                return f"翻译: {text}"
            return ""
        # Multi-block: only return markers for success_indices
        import re
        result_parts = []
        for m in re.finditer(r"\[BLOCK (\d+)\]\n(.*?)\n\[/BLOCK \1\]", text, re.DOTALL):
            idx = int(m.group(1))
            if idx in success_indices:
                result_parts.append(f"[BLOCK {idx}]\n翻译: {m.group(2)}\n[/BLOCK {idx}]")
        if not result_parts:
            return ""
        return "\n\n".join(result_parts)

    return translate_fn, calls


def standard_parse_fn(translated: str, group: list[FakeBlock]) -> dict[int, str]:
    """Parse BLOCK markers from translated text (mirrors _parse_marked_md_translation)."""
    import re

    if len(group) == 1:
        text = (translated or "").strip()
        if not text:
            raise ValueError("Empty translation")
        m = re.search(r"\[BLOCK \d+\]\s*(.*?)\s*\[/BLOCK \d+\]", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
        return {group[0].index: text} if text else {}

    expected = {block.index for block in group}
    found = {}
    pattern = re.compile(r"\[BLOCK (\d+)\]\s*(.*?)\s*\[/BLOCK \1\]", re.DOTALL)
    for match in pattern.finditer(translated or ""):
        block_index = int(match.group(1))
        if block_index in found:
            continue
        found[block_index] = match.group(2).strip()

    found = {idx: text for idx, text in found.items() if idx in expected and text}

    if not found:
        raise ValueError("No valid BLOCK markers found")
    return found


# ---------------------------------------------------------------------------
# Tests: Single-block groups
# ---------------------------------------------------------------------------

class TestSingleBlock:
    def test_single_block_success(self):
        """Single block translates successfully without BLOCK markers."""
        group = make_group(1, start_index=5)
        translate_fn, calls = make_always_succeed_translate()

        result = recursive_translate_group(
            group=group,
            translate_fn=translate_fn,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
        )

        assert 5 in result.translations
        assert result.translations[5] == "翻译: Block 5 text"
        assert result.failed_indices == []
        assert result.split_count == 0
        assert result.total_api_calls == 1
        # Should NOT have used BLOCK markers for single block
        assert "[BLOCK" not in calls[0]["text"]

    def test_single_block_failure(self):
        """Single block that fails is marked in failed_indices."""
        group = make_group(1, start_index=3)
        translate_fn, calls = make_always_fail_translate()

        result = recursive_translate_group(
            group=group,
            translate_fn=translate_fn,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
        )

        assert result.translations == {}
        assert result.failed_indices == [3]
        assert result.split_count == 0
        assert result.total_api_calls == 1


# ---------------------------------------------------------------------------
# Tests: Multi-block groups - full success
# ---------------------------------------------------------------------------

class TestMultiBlockSuccess:
    def test_all_blocks_translated(self):
        """All blocks in a multi-block group translate successfully."""
        group = make_group(4, start_index=0)
        translate_fn, calls = make_always_succeed_translate()

        result = recursive_translate_group(
            group=group,
            translate_fn=translate_fn,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
        )

        assert len(result.translations) == 4
        for i in range(4):
            assert i in result.translations
        assert result.failed_indices == []
        assert result.split_count == 0
        assert result.total_api_calls == 1


# ---------------------------------------------------------------------------
# Tests: Multi-block groups - partial success
# ---------------------------------------------------------------------------

class TestPartialSuccess:
    def test_partial_success_retries_missing(self):
        """When some blocks are missing from response, recurse on missing ones."""
        group = make_group(4, start_index=0)
        # Only blocks 0 and 2 succeed on first try; 1 and 3 will succeed on retry
        translate_fn, calls = make_partial_success_translate({0, 1, 2, 3})

        # Custom translate that fails blocks 1,3 on first multi-block call
        call_count = [0]

        def custom_translate(text, block_index=None, prev_context="", source_type="markdown", cache=None):
            call_count[0] += 1
            import re
            if "[BLOCK" not in text:
                # Single block always succeeds
                return f"翻译: {text}"
            # First multi-block call: only return blocks 0 and 2
            result_parts = []
            for m in re.finditer(r"\[BLOCK (\d+)\]\n(.*?)\n\[/BLOCK \1\]", text, re.DOTALL):
                idx = int(m.group(1))
                if call_count[0] == 1 and idx in {1, 3}:
                    continue  # Skip these on first call
                result_parts.append(f"[BLOCK {idx}]\n翻译: {m.group(2)}\n[/BLOCK {idx}]")
            return "\n\n".join(result_parts) if result_parts else ""

        result = recursive_translate_group(
            group=group,
            translate_fn=custom_translate,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
        )

        # All 4 blocks should eventually succeed
        assert len(result.translations) == 4
        assert result.failed_indices == []
        assert result.split_count >= 1  # At least one split for missing blocks


# ---------------------------------------------------------------------------
# Tests: Complete failure triggers binary split
# ---------------------------------------------------------------------------

class TestBinarySplit:
    def test_complete_failure_splits_in_half(self):
        """When translation completely fails, group is split in half."""
        group = make_group(4, start_index=0)
        # Fail on multi-block, succeed on single-block
        call_count = [0]

        def split_translate(text, block_index=None, prev_context="", source_type="markdown", cache=None):
            call_count[0] += 1
            if "[BLOCK" not in text:
                return f"翻译: {text}"
            return ""  # Fail all multi-block calls

        result = recursive_translate_group(
            group=group,
            translate_fn=split_translate,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
        )

        # All blocks should eventually succeed via single-block retry
        assert len(result.translations) == 4
        assert result.failed_indices == []
        assert result.split_count >= 1  # At least one binary split occurred

    def test_all_fail_marks_all_failed(self):
        """When everything fails including single blocks, all are marked failed."""
        group = make_group(3, start_index=10)
        translate_fn, calls = make_always_fail_translate()

        result = recursive_translate_group(
            group=group,
            translate_fn=translate_fn,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
        )

        assert result.translations == {}
        assert sorted(result.failed_indices) == [10, 11, 12]
        assert result.split_count >= 1


# ---------------------------------------------------------------------------
# Tests: Depth limit
# ---------------------------------------------------------------------------

class TestDepthLimit:
    def test_depth_limit_marks_remaining_as_failed(self):
        """When max_depth is exceeded, remaining blocks are marked as failed."""
        group = make_group(4, start_index=0)
        translate_fn, _ = make_always_fail_translate()

        result = recursive_translate_group(
            group=group,
            translate_fn=translate_fn,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
            max_depth=1,  # Very shallow limit
        )

        # With depth=1, the first call fails and splits, then depth=1 calls
        # also fail and split to depth=2 which exceeds limit
        assert len(result.failed_indices) > 0
        # All blocks should be accounted for
        all_indices = set(result.translations.keys()) | set(result.failed_indices)
        assert all_indices == {0, 1, 2, 3}

    def test_depth_zero_immediately_fails(self):
        """max_depth=0 means the first level can try, depth=1 is over limit."""
        group = make_group(2, start_index=0)
        translate_fn, _ = make_always_fail_translate()

        result = recursive_translate_group(
            group=group,
            translate_fn=translate_fn,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
            max_depth=0,
        )

        # First call at depth=0 fails, splits to depth=1 which exceeds max_depth=0
        # So all blocks should be failed
        assert sorted(result.failed_indices) == [0, 1]


# ---------------------------------------------------------------------------
# Tests: Progress callback
# ---------------------------------------------------------------------------

class TestProgressCallback:
    def test_progress_callback_called_on_success(self):
        """progress_callback is called for each successfully translated block."""
        group = make_group(3, start_index=0)
        translate_fn, _ = make_always_succeed_translate()
        progress_calls = []

        def on_progress(block_index: int, text: str):
            progress_calls.append((block_index, text))

        result = recursive_translate_group(
            group=group,
            translate_fn=translate_fn,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
            progress_callback=on_progress,
        )

        assert len(progress_calls) == 3
        reported_indices = {idx for idx, _ in progress_calls}
        assert reported_indices == {0, 1, 2}

    def test_progress_callback_not_called_on_failure(self):
        """progress_callback is NOT called for failed blocks."""
        group = make_group(1, start_index=7)
        translate_fn, _ = make_always_fail_translate()
        progress_calls = []

        def on_progress(block_index: int, text: str):
            progress_calls.append((block_index, text))

        result = recursive_translate_group(
            group=group,
            translate_fn=translate_fn,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
            progress_callback=on_progress,
        )

        assert progress_calls == []
        assert result.failed_indices == [7]


# ---------------------------------------------------------------------------
# Tests: API call and split count tracking
# ---------------------------------------------------------------------------

class TestTracking:
    def test_api_calls_counted(self):
        """total_api_calls tracks every translate_fn invocation."""
        group = make_group(2, start_index=0)
        translate_fn, calls = make_always_succeed_translate()

        result = recursive_translate_group(
            group=group,
            translate_fn=translate_fn,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
        )

        assert result.total_api_calls == 1  # One successful multi-block call

    def test_split_count_on_failure(self):
        """split_count increments each time a binary split occurs."""
        group = make_group(2, start_index=0)

        def fail_multi(text, block_index=None, prev_context="", source_type="markdown", cache=None):
            if "[BLOCK" not in text:
                return f"翻译: {text}"
            return ""

        result = recursive_translate_group(
            group=group,
            translate_fn=fail_multi,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
        )

        assert result.split_count == 1  # One split from 2-block group
        assert result.total_api_calls == 3  # 1 multi + 2 single


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_group(self):
        """Empty group returns empty result."""
        translate_fn, _ = make_always_succeed_translate()

        result = recursive_translate_group(
            group=[],
            translate_fn=translate_fn,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
        )

        assert result.translations == {}
        assert result.failed_indices == []
        assert result.split_count == 0
        assert result.total_api_calls == 0

    def test_prev_context_passed_through(self):
        """prev_context is passed to translate_fn."""
        group = make_group(1, start_index=0)
        received_contexts = []

        def capture_translate(text, block_index=None, prev_context="", source_type="markdown", cache=None):
            received_contexts.append(prev_context)
            return f"翻译: {text}"

        recursive_translate_group(
            group=group,
            translate_fn=capture_translate,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
            prev_context="之前的翻译内容",
        )

        assert received_contexts[0] == "之前的翻译内容"

    def test_source_type_passed_through(self):
        """source_type is passed to translate_fn."""
        group = make_group(1, start_index=0)
        received_types = []

        def capture_translate(text, block_index=None, prev_context="", source_type="markdown", cache=None):
            received_types.append(source_type)
            return f"翻译: {text}"

        recursive_translate_group(
            group=group,
            translate_fn=capture_translate,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
            source_type="docx",
        )

        assert received_types[0] == "docx"

    def test_cache_passed_through(self):
        """cache parameter is passed to translate_fn."""
        group = make_group(1, start_index=0)
        received_caches = []
        fake_cache = object()

        def capture_translate(text, block_index=None, prev_context="", source_type="markdown", cache=None):
            received_caches.append(cache)
            return f"翻译: {text}"

        recursive_translate_group(
            group=group,
            translate_fn=capture_translate,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
            cache=fake_cache,
        )

        assert received_caches[0] is fake_cache

    def test_failure_prefix_treated_as_failure(self):
        """Translation starting with TRANSLATION_FAILURE_PREFIX is treated as failure."""
        from core.constants import TRANSLATION_FAILURE_PREFIX
        group = make_group(1, start_index=0)

        def fail_with_prefix(text, block_index=None, prev_context="", source_type="markdown", cache=None):
            return f"{TRANSLATION_FAILURE_PREFIX} timeout]"

        result = recursive_translate_group(
            group=group,
            translate_fn=fail_with_prefix,
            parse_fn=standard_parse_fn,
            build_text_fn=build_text_fn,
        )

        assert result.translations == {}
        assert result.failed_indices == [0]
