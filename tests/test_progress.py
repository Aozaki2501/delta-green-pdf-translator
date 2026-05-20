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

        tracker2 = ProgressTracker(progress_file, expected_metadata=metadata)
        assert tracker2.get_cached_prompt_translation("abc123") == "cached translation"
        assert tracker2.get_cached_prompt_translation("missing") == ""

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
