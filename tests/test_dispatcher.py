"""
Unit tests for core.dispatcher.ConcurrentDispatcher.

Tests cover:
- Basic dispatch with mock translator (all succeed)
- Circuit breaker triggers after threshold failures
- Results are ordered by block index
- Cooldown is inserted between batches
- Context window is truncated to 500 chars
"""

import time
import threading
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from core.dispatcher import ConcurrentDispatcher, DispatcherConfig, _CONTEXT_WINDOW_SIZE


# ---------------------------------------------------------------------------
# Helpers: Mock block and translator
# ---------------------------------------------------------------------------

@dataclass
class MockBlock:
    """Minimal block with index and text attributes."""
    index: int
    text: str


class MockTranslator:
    """Mock translator that returns predictable translations."""

    def __init__(self, fail_indices=None, delay=0.0):
        """
        Args:
            fail_indices: set of block indices that should fail
            delay: artificial delay per call (seconds)
        """
        self.fail_indices = fail_indices or set()
        self.delay = delay
        self.call_log = []
        self._lock = threading.Lock()

    def translate_block(self, text, block_index=None, prev_context="",
                        source_type="markdown", cache=None):
        if self.delay:
            time.sleep(self.delay)
        with self._lock:
            self.call_log.append({
                "text": text,
                "block_index": block_index,
                "prev_context": prev_context,
                "source_type": source_type,
            })
        if block_index in self.fail_indices:
            return ""
        return f"translated_{block_index}: {text[:20]}"


class MockTracker:
    """Mock ProgressTracker with mark_completed, mark_failed and batch saving."""

    def __init__(self):
        self.completed = {}
        self.failed = {}
        self.save_calls = 0
        self.flush_calls = 0
        self._lock = threading.Lock()

    def mark_completed(self, page_num, translation):
        with self._lock:
            self.completed[page_num] = translation
            self.save_calls += 1

    def mark_completed_many(self, translations):
        if not translations:
            return
        with self._lock:
            self.completed.update(translations)
            self.save_calls += 1

    def mark_failed(self, page_num, message):
        with self._lock:
            self.failed[page_num] = message
            self.save_calls += 1

    def flush(self):
        with self._lock:
            self.flush_calls += 1

    def get_cached_prompt_translation(self, cache_key):
        return ""

    def mark_cached_prompt_translation(self, cache_key, translation):
        pass


class MockStats:
    """Mock TokenStats with thread-safe add methods."""

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.api_calls = 0
        self._lock = threading.Lock()

    def add(self, input_tok, output_tok, cached_tok=0):
        with self._lock:
            self.input_tokens += input_tok
            self.output_tokens += output_tok
            self.api_calls += 1

    def add_failure(self):
        with self._lock:
            self.api_calls += 1


def simple_build_text_fn(group):
    """Build text from a group of blocks using BLOCK markers."""
    parts = []
    for block in group:
        parts.append(f"[BLOCK {block.index}]\n{block.text}\n[/BLOCK {block.index}]")
    return "\n\n".join(parts)


def simple_parse_fn(translated, group):
    """Parse function that returns all blocks as successfully translated.

    For single-block groups, returns the translated text directly.
    For multi-block groups, returns each block's translation.
    """
    if len(group) == 1:
        return {group[0].index: translated}
    # For multi-block, simulate successful parsing
    result = {}
    for block in group:
        result[block.index] = f"parsed_{block.index}"
    return result


# ---------------------------------------------------------------------------
# Tests: Basic dispatch (all succeed)
# ---------------------------------------------------------------------------

class TestBasicDispatch:
    def test_all_groups_succeed(self):
        """All groups translate successfully and results are returned."""
        config = DispatcherConfig(concurrency=2, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()

        groups = [
            [MockBlock(index=0, text="Hello world")],
            [MockBlock(index=1, text="Second block")],
            [MockBlock(index=2, text="Third block")],
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)
        results = dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        # All 3 blocks should be in results
        assert len(results) == 3
        assert 0 in results
        assert 1 in results
        assert 2 in results

    def test_multi_block_group_succeeds(self):
        """A group with multiple blocks translates successfully."""
        config = DispatcherConfig(concurrency=2, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()

        groups = [
            [MockBlock(index=0, text="Block A"), MockBlock(index=1, text="Block B")],
            [MockBlock(index=2, text="Block C")],
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)
        results = dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        assert len(results) == 3
        assert 0 in results
        assert 1 in results
        assert 2 in results

    def test_progress_callback_called(self):
        """Progress callback is invoked for each completed block."""
        config = DispatcherConfig(concurrency=4, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()
        progress_calls = []

        def progress_cb(block_idx, text, completed, total, stats=None):
            progress_calls.append((block_idx, text, completed, total, stats))

        groups = [
            [MockBlock(index=0, text="A")],
            [MockBlock(index=1, text="B")],
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats, progress_cb)
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        # Should have been called for each block
        assert len(progress_calls) == 2
        # Total should be 2 for all calls
        assert all(total == 2 for _, _, _, total, _ in progress_calls)
        # Stats should be passed
        assert all(s is stats for _, _, _, _, s in progress_calls)
        # Block indices should be present
        block_indices = {call[0] for call in progress_calls}
        assert block_indices == {0, 1}


# ---------------------------------------------------------------------------
# Tests: Circuit breaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_circuit_breaker_triggers_after_threshold(self):
        """Circuit breaker pauses after consecutive failures reach threshold."""
        threshold = 3
        backoff = 0.1  # Short for testing
        config = DispatcherConfig(
            concurrency=1,
            rate_limit=1000,
            cooldown=0.0,
            backoff_threshold=threshold,
            backoff_seconds=backoff,
        )
        # All blocks fail
        translator = MockTranslator(fail_indices={0, 1, 2, 3, 4, 5})
        tracker = MockTracker()
        stats = MockStats()

        groups = [
            [MockBlock(index=i, text=f"Block {i}")] for i in range(6)
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)

        start = time.monotonic()
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)
        elapsed = time.monotonic() - start

        # With 6 failures and threshold=3, circuit breaker should trigger at least once
        # causing at least one backoff_seconds pause
        assert elapsed >= backoff * 0.8  # Allow some timing tolerance

    def test_success_resets_failure_count(self):
        """A successful translation resets the consecutive failure counter."""
        config = DispatcherConfig(
            concurrency=1,
            rate_limit=1000,
            cooldown=0.0,
            backoff_threshold=5,
            backoff_seconds=0.5,
        )
        # Blocks 0,1 fail, block 2 succeeds, blocks 3,4 fail
        translator = MockTranslator(fail_indices={0, 1, 3, 4})
        tracker = MockTracker()
        stats = MockStats()

        groups = [
            [MockBlock(index=i, text=f"Block {i}")] for i in range(5)
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)

        start = time.monotonic()
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)
        elapsed = time.monotonic() - start

        # Threshold is 5, but success at block 2 resets counter
        # So we never reach 5 consecutive failures → no backoff pause
        assert elapsed < 0.4  # Should be fast (no 0.5s pause)


# ---------------------------------------------------------------------------
# Tests: Output ordering
# ---------------------------------------------------------------------------

class TestOutputOrdering:
    def test_results_ordered_by_block_index(self):
        """Final results are sorted by block index regardless of completion order."""
        config = DispatcherConfig(concurrency=4, rate_limit=1000, cooldown=0.0)
        # Add varying delays to make completion order non-deterministic
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()

        # Create blocks with indices in non-sequential order
        groups = [
            [MockBlock(index=5, text="E")],
            [MockBlock(index=2, text="B")],
            [MockBlock(index=8, text="H")],
            [MockBlock(index=0, text="A")],
            [MockBlock(index=3, text="C")],
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)
        results = dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        # Keys should be in sorted order
        keys = list(results.keys())
        assert keys == sorted(keys)
        assert keys == [0, 2, 3, 5, 8]

    def test_results_contain_all_successful_blocks(self):
        """All successfully translated blocks appear in the output."""
        config = DispatcherConfig(concurrency=2, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator(fail_indices={2})  # Block 2 fails
        tracker = MockTracker()
        stats = MockStats()

        groups = [
            [MockBlock(index=0, text="A")],
            [MockBlock(index=1, text="B")],
            [MockBlock(index=2, text="C")],
            [MockBlock(index=3, text="D")],
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)
        results = dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        # Block 2 failed, so only 0, 1, 3 should be in results
        assert 0 in results
        assert 1 in results
        assert 2 not in results
        assert 3 in results


# ---------------------------------------------------------------------------
# Tests: Cooldown between batches
# ---------------------------------------------------------------------------

class TestCooldown:
    def test_cooldown_inserted_between_batches(self):
        """Cooldown delay is inserted between consecutive batches."""
        cooldown = 0.15
        config = DispatcherConfig(concurrency=2, rate_limit=1000, cooldown=cooldown)
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()

        # 4 groups with concurrency=2 → 2 batches → 1 cooldown
        groups = [
            [MockBlock(index=i, text=f"Block {i}")] for i in range(4)
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)

        start = time.monotonic()
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)
        elapsed = time.monotonic() - start

        # Should have at least 1 cooldown period
        assert elapsed >= cooldown * 0.8

    def test_no_cooldown_before_first_batch(self):
        """No cooldown is inserted before the first batch."""
        cooldown = 0.5
        config = DispatcherConfig(concurrency=10, rate_limit=1000, cooldown=cooldown)
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()

        # All fit in one batch → no cooldown
        groups = [
            [MockBlock(index=i, text=f"Block {i}")] for i in range(3)
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)

        start = time.monotonic()
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)
        elapsed = time.monotonic() - start

        # Should be fast (no cooldown since only 1 batch)
        assert elapsed < cooldown * 0.5

    def test_multiple_cooldowns_for_many_batches(self):
        """Multiple cooldowns are inserted for multiple batches."""
        cooldown = 0.1
        config = DispatcherConfig(concurrency=1, rate_limit=1000, cooldown=cooldown)
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()

        # 4 groups with concurrency=1 → 4 batches → 3 cooldowns
        groups = [
            [MockBlock(index=i, text=f"Block {i}")] for i in range(4)
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)

        start = time.monotonic()
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)
        elapsed = time.monotonic() - start

        # Should have at least 3 cooldown periods
        assert elapsed >= cooldown * 3 * 0.7


# ---------------------------------------------------------------------------
# Tests: Context window
# ---------------------------------------------------------------------------

class TestContextWindow:
    def test_context_comes_from_previous_group_source(self):
        """Each group receives the tail of the previous group's source text."""
        config = DispatcherConfig(concurrency=1, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()

        groups = [
            [MockBlock(index=0, text="First block")],
            [MockBlock(index=1, text="Second block")],
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        calls = translator.call_log
        assert len(calls) >= 2
        assert calls[0]["prev_context"] == ""
        assert calls[1]["prev_context"] == "First block"

    def test_context_window_truncated_to_500_chars(self):
        """Context window is truncated to 500 characters maximum."""
        config = DispatcherConfig(concurrency=1, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()

        groups = [
            [MockBlock(index=0, text="A" * 1000)],
            [MockBlock(index=1, text="Second")],
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        assert len(translator.call_log) >= 2
        second_context = translator.call_log[1]["prev_context"]
        assert len(second_context) == _CONTEXT_WINDOW_SIZE
        assert second_context == "A" * _CONTEXT_WINDOW_SIZE

    def test_context_is_independent_of_concurrency(self):
        """The same document produces the same prompts at any worker count.

        Context used to be seeded from whichever translation finished last, so
        changing --workers silently changed the translated text while the old
        cache was still reused. Source-derived context removes that coupling.
        """
        groups_for = lambda: [
            [MockBlock(index=i, text=f"Block number {i} body text")]
            for i in range(6)
        ]

        contexts_by_concurrency = {}
        for concurrency in (1, 2, 4):
            config = DispatcherConfig(
                concurrency=concurrency, rate_limit=1000, cooldown=0.0
            )
            translator = MockTranslator()
            dispatcher = ConcurrentDispatcher(
                config, translator, MockTracker(), MockStats()
            )
            dispatcher.dispatch_all(groups_for(), simple_build_text_fn, simple_parse_fn)
            contexts_by_concurrency[concurrency] = {
                call["block_index"]: call["prev_context"]
                for call in translator.call_log
            }

        assert contexts_by_concurrency[1] == contexts_by_concurrency[2]
        assert contexts_by_concurrency[1] == contexts_by_concurrency[4]

    def test_failed_translations_do_not_change_context(self):
        """Context is source-derived, so failures upstream do not blank it."""
        config = DispatcherConfig(concurrency=1, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator(fail_indices={0})
        tracker = MockTracker()
        stats = MockStats()

        groups = [
            [MockBlock(index=0, text="Fail")],
            [MockBlock(index=1, text="Also fail")],
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        assert translator.call_log[0]["prev_context"] == ""
        assert translator.call_log[1]["prev_context"] == "Fail"


# ---------------------------------------------------------------------------
# Tests: Tracker integration
# ---------------------------------------------------------------------------

class TestTrackerIntegration:
    def test_successful_blocks_marked_completed(self):
        """Successfully translated blocks are marked completed in tracker."""
        config = DispatcherConfig(concurrency=2, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()

        groups = [
            [MockBlock(index=0, text="A")],
            [MockBlock(index=1, text="B")],
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        assert 0 in tracker.completed
        assert 1 in tracker.completed

    def test_failed_blocks_marked_failed(self):
        """Failed blocks are marked failed in tracker."""
        config = DispatcherConfig(concurrency=2, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator(fail_indices={1})
        tracker = MockTracker()
        stats = MockStats()

        groups = [
            [MockBlock(index=0, text="A")],
            [MockBlock(index=1, text="B")],
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        assert 0 in tracker.completed
        assert 1 in tracker.failed


# ---------------------------------------------------------------------------
# Tests: Progress reporting and TokenStats integration (Task 6.3)
# ---------------------------------------------------------------------------

class TestProgressReportingSignature:
    """Tests for progress_callback signature compatibility with Streamlit Web UI."""

    def test_progress_callback_receives_block_idx_and_text(self):
        """Progress callback receives block_idx and translated text."""
        config = DispatcherConfig(concurrency=2, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()
        progress_calls = []

        def progress_cb(block_idx, text, completed, total, stats_arg=None):
            progress_calls.append({
                "block_idx": block_idx,
                "text": text,
                "completed": completed,
                "total": total,
                "stats": stats_arg,
            })

        groups = [
            [MockBlock(index=0, text="Hello")],
            [MockBlock(index=1, text="World")],
            [MockBlock(index=2, text="Test")],
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats, progress_cb)
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        assert len(progress_calls) == 3
        # Each call should have the correct total
        assert all(call["total"] == 3 for call in progress_calls)
        # Stats should be passed to each call
        assert all(call["stats"] is stats for call in progress_calls)
        # Block indices should cover all blocks
        block_indices = {call["block_idx"] for call in progress_calls}
        assert block_indices == {0, 1, 2}
        # Text should be non-empty for successful translations
        for call in progress_calls:
            assert call["text"]  # translated text is non-empty

    def test_progress_callback_fallback_to_legacy_signature(self):
        """Dispatcher falls back to legacy (completed, total, block_id) signature."""
        config = DispatcherConfig(concurrency=2, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()
        progress_calls = []

        def legacy_progress_cb(completed, total, block_id):
            """Legacy signature without block text or stats."""
            progress_calls.append((completed, total, block_id))

        groups = [
            [MockBlock(index=0, text="A")],
            [MockBlock(index=1, text="B")],
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats, legacy_progress_cb)
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        # Should still work via fallback
        assert len(progress_calls) == 2
        assert all(total == 2 for _, total, _ in progress_calls)

    def test_progress_callback_reports_failure_text(self):
        """Progress callback receives error message for failed blocks."""
        config = DispatcherConfig(concurrency=1, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator(fail_indices={1})
        tracker = MockTracker()
        stats = MockStats()
        progress_calls = []

        def progress_cb(block_idx, text, completed, total, stats_arg=None):
            progress_calls.append({
                "block_idx": block_idx,
                "text": text,
                "completed": completed,
                "total": total,
            })

        groups = [
            [MockBlock(index=0, text="OK")],
            [MockBlock(index=1, text="Fail")],
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats, progress_cb)
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        assert len(progress_calls) == 2
        # Find the failed block's progress call
        failed_call = next(c for c in progress_calls if c["block_idx"] == 1)
        assert "failed" in failed_call["text"].lower()

    def test_completed_count_monotonically_increases(self):
        """Completed count in progress callbacks monotonically increases."""
        config = DispatcherConfig(concurrency=1, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()
        completed_counts = []

        def progress_cb(block_idx, text, completed, total, stats_arg=None):
            completed_counts.append(completed)

        groups = [
            [MockBlock(index=i, text=f"Block {i}")] for i in range(5)
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats, progress_cb)
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        # With concurrency=1, counts should be strictly increasing
        assert completed_counts == sorted(completed_counts)
        assert completed_counts[-1] == 5


class TestTokenStatsIntegration:
    """Tests for TokenStats thread-safe accumulation across workers."""

    def test_stats_shared_across_workers(self):
        """TokenStats instance is shared and accessible via progress callback."""
        config = DispatcherConfig(concurrency=4, rate_limit=1000, cooldown=0.0)
        translator = MockTranslator()
        tracker = MockTracker()
        stats = MockStats()
        received_stats = []

        def progress_cb(block_idx, text, completed, total, stats_arg=None):
            received_stats.append(stats_arg)

        groups = [
            [MockBlock(index=i, text=f"Block {i}")] for i in range(4)
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats, progress_cb)
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        # All callbacks should receive the same stats instance
        assert all(s is stats for s in received_stats)

    def test_token_stats_accumulates_from_translator(self):
        """TokenStats accumulates token counts from Translator calls."""
        from core.translator import TokenStats as RealTokenStats

        config = DispatcherConfig(concurrency=2, rate_limit=1000, cooldown=0.0)
        stats = RealTokenStats()

        class CountingTranslator:
            """Translator that simulates token usage."""
            def __init__(self, stats):
                self.stats = stats

            def translate_block(self, text, block_index=None, prev_context="",
                                source_type="markdown", cache=None):
                # Simulate API call adding tokens
                self.stats.add(input_tok=100, output_tok=50, cached_tok=10)
                return f"translated_{block_index}"

        translator = CountingTranslator(stats)
        tracker = MockTracker()

        groups = [
            [MockBlock(index=i, text=f"Block {i}")] for i in range(4)
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        # 4 blocks × 100 input tokens each = 400
        assert stats.input_tokens == 400
        # 4 blocks × 50 output tokens each = 200
        assert stats.output_tokens == 200
        # 4 blocks × 10 cached tokens each = 40
        assert stats.cached_tokens == 40
        # 4 API calls
        assert stats.api_calls == 4

    def test_token_stats_thread_safe_under_concurrency(self):
        """TokenStats accumulates correctly under concurrent access."""
        from core.translator import TokenStats as RealTokenStats

        config = DispatcherConfig(concurrency=8, rate_limit=1000, cooldown=0.0)
        stats = RealTokenStats()

        class SlowCountingTranslator:
            """Translator with slight delay to increase thread contention."""
            def __init__(self, stats):
                self.stats = stats

            def translate_block(self, text, block_index=None, prev_context="",
                                source_type="markdown", cache=None):
                import time
                time.sleep(0.01)  # Small delay to increase contention
                self.stats.add(input_tok=10, output_tok=5, cached_tok=0)
                return f"translated_{block_index}"

        translator = SlowCountingTranslator(stats)
        tracker = MockTracker()

        num_blocks = 16
        groups = [
            [MockBlock(index=i, text=f"Block {i}")] for i in range(num_blocks)
        ]

        dispatcher = ConcurrentDispatcher(config, translator, tracker, stats)
        dispatcher.dispatch_all(groups, simple_build_text_fn, simple_parse_fn)

        # All tokens should be correctly accumulated despite concurrency
        assert stats.input_tokens == num_blocks * 10
        assert stats.output_tokens == num_blocks * 5
        assert stats.api_calls == num_blocks
