"""Unit tests for core.progress module.

Tests cover:
- ProgressTracker save/load round-trip
- Metadata mismatch detection and discard behavior
- Invalid JSON recovery (start with empty state)
- completed_pages stored as sorted integer array
"""

import json

import pytest

from core.progress import ProgressTracker, compare_progress_metadata


class TestSaveLoadRoundTrip:
    """Test that saving and loading a ProgressTracker preserves state."""

    def test_round_trip_completed_pages_and_translations(self, tmp_path):
        """Save a tracker with completed pages, load from same file -> identical state."""
        progress_file = str(tmp_path / "test.progress.json")
        metadata = {"schema": 1, "model": "test-model", "prompt_version": "v1"}

        # Create tracker and mark pages completed
        tracker = ProgressTracker(progress_file, expected_metadata=metadata)
        tracker.mark_completed(3, "Translation for page 3")
        tracker.mark_completed(1, "Translation for page 1")
        tracker.mark_completed(7, "Translation for page 7")

        # Load from same file with same metadata
        tracker2 = ProgressTracker(progress_file, expected_metadata=metadata)

        assert tracker2.completed_pages == {1, 3, 7}
        assert tracker2.get_translation(1) == "Translation for page 1"
        assert tracker2.get_translation(3) == "Translation for page 3"
        assert tracker2.get_translation(7) == "Translation for page 7"

    def test_round_trip_empty_tracker(self, tmp_path):
        """A tracker with no completed pages saves and loads correctly."""
        progress_file = str(tmp_path / "empty.progress.json")
        metadata = {"schema": 1, "model": "m"}

        tracker = ProgressTracker(progress_file, expected_metadata=metadata)
        tracker.save()

        tracker2 = ProgressTracker(progress_file, expected_metadata=metadata)
        assert tracker2.completed_pages == set()
        assert tracker2.translations == {}
        assert tracker2.translation_cache == {}

    def test_round_trip_translation_cache(self, tmp_path):
        """Exact prompt translation cache is saved and loaded."""
        progress_file = str(tmp_path / "cache.progress.json")
        metadata = {"schema": 1, "model": "m"}

        tracker = ProgressTracker(progress_file, expected_metadata=metadata)
        tracker.mark_cached_prompt_translation("abc123", "cached translation")
        tracker.flush()

        tracker2 = ProgressTracker(progress_file, expected_metadata=metadata)
        assert tracker2.get_cached_prompt_translation("abc123") == "cached translation"
        assert tracker2.get_cached_prompt_translation("missing") == ""

    def test_prompt_cache_write_is_flushed_by_mark_completed(self, tmp_path):
        """A deferred prompt-cache write lands on the next forced save.

        mark_cached_prompt_translation defers its write because every caller
        records the same text through mark_completed immediately afterwards;
        that forced save must persist both.
        """
        progress_file = str(tmp_path / "deferred.progress.json")

        tracker = ProgressTracker(progress_file)
        tracker.mark_cached_prompt_translation("key-1", "翻译结果")
        tracker.mark_completed(3, "翻译结果")

        tracker2 = ProgressTracker(progress_file)
        assert tracker2.get_cached_prompt_translation("key-1") == "翻译结果"
        assert tracker2.get_translation(3) == "翻译结果"

    def test_mark_completed_many_persists_all_blocks_in_one_write(self, tmp_path):
        progress_file = str(tmp_path / "batch.progress.json")

        tracker = ProgressTracker(progress_file)
        tracker.mark_completed_many({0: "第一块", 1: "第二块", 2: "第三块"})

        tracker2 = ProgressTracker(progress_file)
        assert tracker2.completed_pages == {0, 1, 2}
        assert tracker2.get_translation(1) == "第二块"

    def test_delete_cached_prompt_translations_by_value(self, tmp_path):
        progress_file = str(tmp_path / "cache_value.progress.json")

        tracker = ProgressTracker(progress_file)
        tracker.mark_cached_prompt_translation("bad-1", "short translation")
        tracker.mark_cached_prompt_translation("good", "complete translation")
        tracker.mark_cached_prompt_translation("bad-2", "short translation")

        assert tracker.delete_cached_prompt_translations_by_value("short translation") == 2

        tracker2 = ProgressTracker(progress_file)
        assert tracker2.get_cached_prompt_translation("bad-1") == ""
        assert tracker2.get_cached_prompt_translation("bad-2") == ""
        assert tracker2.get_cached_prompt_translation("good") == "complete translation"

    def test_clear_pages_removes_matching_prompt_cache(self, tmp_path):
        progress_file = str(tmp_path / "clear_page_cache.progress.json")

        tracker = ProgressTracker(progress_file)
        tracker.mark_completed(1, "old page translation")
        tracker.mark_completed(2, "kept page translation")
        tracker.mark_cached_prompt_translation("old-cache", "old page translation")
        tracker.mark_cached_prompt_translation("kept-cache", "kept page translation")

        assert tracker.clear_pages({1}) == 1

        tracker2 = ProgressTracker(progress_file)
        assert tracker2.is_completed(1) is False
        assert tracker2.get_translation(1) == ""
        assert tracker2.is_completed(2) is True
        assert tracker2.get_cached_prompt_translation("old-cache") == ""
        assert tracker2.get_cached_prompt_translation("kept-cache") == "kept page translation"

    def test_prompt_leak_cache_is_not_reused(self, tmp_path):
        progress_file = str(tmp_path / "cache_leak.progress.json")

        tracker = ProgressTracker(progress_file)
        tracker.translation_cache["abc123"] = (
            "您是专业的TRPG翻译，翻译规则包括：严格遵循术语表，输出Markdown。"
        )
        tracker.save()

        tracker2 = ProgressTracker(progress_file)
        assert tracker2.get_cached_prompt_translation("abc123") == ""

    def test_prompt_leak_translation_is_not_completed(self, tmp_path):
        progress_file = str(tmp_path / "translation_leak.progress.json")

        tracker = ProgressTracker(progress_file)
        tracker.completed_pages.add(1)
        tracker.translations["1"] = (
            "您是专业的TRPG翻译，翻译规则包括：严格遵循术语表，输出Markdown。"
        )
        tracker.save()

        tracker2 = ProgressTracker(progress_file)
        assert tracker2.is_completed(1) is False
        assert tracker2.get_translation(1) == ""

    def test_completed_pages_sorted_in_json(self, tmp_path):
        """The saved JSON file stores completed_pages as a sorted integer array."""
        progress_file = str(tmp_path / "sorted.progress.json")

        tracker = ProgressTracker(progress_file)
        tracker.mark_completed(10, "p10")
        tracker.mark_completed(2, "p2")
        tracker.mark_completed(5, "p5")

        with open(progress_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["completed_pages"] == [2, 5, 10]

    def test_failed_pages_are_saved_separately(self, tmp_path):
        progress_file = str(tmp_path / "failed.progress.json")

        tracker = ProgressTracker(progress_file)
        tracker.mark_failed(4, "API timeout")

        tracker2 = ProgressTracker(progress_file)
        assert tracker2.get_failed_pages() == {4}
        assert tracker2.is_completed(4) is False
        assert tracker2.get_translation(4) == ""

    def test_completed_page_clears_failed_marker(self, tmp_path):
        progress_file = str(tmp_path / "failed_then_done.progress.json")

        tracker = ProgressTracker(progress_file)
        tracker.mark_failed(2, "failed")
        tracker.mark_completed(2, "done")

        tracker2 = ProgressTracker(progress_file)
        assert tracker2.get_failed_pages() == set()
        assert tracker2.is_completed(2) is True
        assert tracker2.get_translation(2) == "done"

    def test_save_retries_windows_replace_lock(self, tmp_path, monkeypatch):
        progress_file = str(tmp_path / "retry.progress.json")
        real_replace = __import__("os").replace
        calls = {"count": 0}

        def flaky_replace(src, dst):
            calls["count"] += 1
            if calls["count"] == 1:
                raise PermissionError("locked")
            return real_replace(src, dst)

        monkeypatch.setattr("core.progress.os.replace", flaky_replace)

        tracker = ProgressTracker(progress_file)
        tracker.mark_completed(1, "done")

        assert calls["count"] == 2
        assert ProgressTracker(progress_file).get_translation(1) == "done"


class TestMetadataMismatch:
    """Test metadata mismatch detection and discard behavior."""

    def test_mismatch_discards_translations(self, tmp_path):
        """Loading with different metadata discards cached translations."""
        progress_file = str(tmp_path / "mismatch.progress.json")
        original_metadata = {"schema": 1, "model": "model-a", "prompt_version": "v1"}

        # Create and save with original metadata
        tracker = ProgressTracker(progress_file, expected_metadata=original_metadata)
        tracker.mark_completed(0, "Page 0 translation")
        tracker.mark_completed(1, "Page 1 translation")

        # Load with different metadata
        new_metadata = {"schema": 1, "model": "model-b", "prompt_version": "v1"}
        tracker2 = ProgressTracker(progress_file, expected_metadata=new_metadata)

        assert tracker2.metadata_mismatches != []
        assert tracker2.completed_pages == set()
        assert tracker2.translations == {}
        assert tracker2.translation_cache == {}
        assert tracker2.ignored_existing_progress is True

    def test_mismatch_with_reuse_preserves_translations(self, tmp_path):
        """Loading with different metadata but reuse_mismatched=True keeps translations."""
        progress_file = str(tmp_path / "reuse.progress.json")
        original_metadata = {"schema": 1, "model": "model-a", "prompt_version": "v1"}

        # Create and save with original metadata
        tracker = ProgressTracker(progress_file, expected_metadata=original_metadata)
        tracker.mark_completed(2, "Page 2 translation")
        tracker.mark_completed(4, "Page 4 translation")

        # Load with different metadata but reuse_mismatched=True
        new_metadata = {"schema": 1, "model": "model-b", "prompt_version": "v1"}
        tracker2 = ProgressTracker(
            progress_file, expected_metadata=new_metadata, reuse_mismatched=True
        )

        assert tracker2.metadata_mismatches != []
        assert tracker2.completed_pages == {2, 4}
        assert tracker2.get_translation(2) == "Page 2 translation"
        assert tracker2.get_translation(4) == "Page 4 translation"

    def test_compare_progress_metadata_detects_differences(self):
        """compare_progress_metadata returns mismatch descriptions for differing fields."""
        expected = {"schema": 1, "model": "a", "prompt_version": "v1"}
        actual = {"schema": 1, "model": "b", "prompt_version": "v1"}

        mismatches = compare_progress_metadata(expected, actual)
        assert len(mismatches) == 1
        assert "model" in mismatches[0]

    def test_compare_progress_metadata_no_mismatch(self):
        """compare_progress_metadata returns empty list when metadata matches."""
        metadata = {"schema": 1, "model": "x", "prompt_version": "v2"}
        mismatches = compare_progress_metadata(metadata, metadata)
        assert mismatches == []


class TestInvalidJsonRecovery:
    """Test that invalid/corrupt progress files are handled gracefully."""

    def test_garbage_content_starts_empty(self, tmp_path):
        """A progress file with garbage content results in empty state, no exception."""
        progress_file = str(tmp_path / "garbage.progress.json")

        with open(progress_file, "w", encoding="utf-8") as f:
            f.write("this is not valid json {{{[[[")

        tracker = ProgressTracker(progress_file)
        assert tracker.completed_pages == set()
        assert tracker.translations == {}

    def test_non_dict_root_starts_empty(self, tmp_path):
        """A progress file with a non-dict root (e.g. array) starts with empty state."""
        progress_file = str(tmp_path / "array.progress.json")

        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)

        tracker = ProgressTracker(progress_file)
        assert tracker.completed_pages == set()
        assert tracker.translations == {}

    def test_nonexistent_file_starts_empty(self, tmp_path):
        """A nonexistent progress file results in empty state (normal first-run)."""
        progress_file = str(tmp_path / "does_not_exist.progress.json")

        tracker = ProgressTracker(progress_file)
        assert tracker.completed_pages == set()
        assert tracker.translations == {}
