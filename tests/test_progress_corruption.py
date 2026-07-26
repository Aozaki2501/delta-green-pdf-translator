"""A corrupt progress file is backed up and reported, never silently discarded.

A truncated or invalid progress.json used to be swallowed: the tracker started
from scratch, the paid-for translations were gone, and the run looked normal.
"""

import json
from pathlib import Path

from core.progress import (
    PROGRESS_SCHEMA_VERSION,
    ProgressTracker,
    build_progress_metadata,
    fingerprint_file,
)


class TestCorruptProgressFile:
    def test_invalid_json_is_backed_up(self, tmp_path):
        progress_file = tmp_path / "run.progress.json"
        progress_file.write_text('{"completed_pages": [1, 2', encoding="utf-8")

        tracker = ProgressTracker(str(progress_file))

        backup = Path(str(progress_file) + ".corrupt.bak")
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == '{"completed_pages": [1, 2'

    def test_corruption_is_flagged_on_the_tracker(self, tmp_path):
        progress_file = tmp_path / "run.progress.json"
        progress_file.write_text("not json at all", encoding="utf-8")

        tracker = ProgressTracker(str(progress_file))

        assert tracker.progress_corrupted is True
        assert tracker.corrupt_backup_path.endswith(".corrupt.bak")

    def test_translation_work_continues_from_scratch(self, tmp_path):
        progress_file = tmp_path / "run.progress.json"
        progress_file.write_text("{{{", encoding="utf-8")

        tracker = ProgressTracker(str(progress_file))

        assert tracker.completed_pages == set()
        tracker.mark_completed(0, "译文")
        assert tracker.get_translation(0) == "译文"

    def test_a_healthy_file_is_not_flagged(self, tmp_path):
        progress_file = tmp_path / "run.progress.json"
        first = ProgressTracker(str(progress_file))
        first.mark_completed(0, "译文")

        second = ProgressTracker(str(progress_file))

        assert second.progress_corrupted is False
        assert second.corrupt_backup_path == ""
        assert second.get_translation(0) == "译文"


class TestProgressMetadata:
    def test_schema_version_is_recorded(self, tmp_path):
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"pdf bytes")

        metadata = build_progress_metadata(
            str(source), None, "deepseek-v4-pro", 0, 10
        )

        assert metadata["schema"] == PROGRESS_SCHEMA_VERSION

    def test_settings_that_change_output_are_fingerprinted(self, tmp_path):
        """A cached page must not be reused when the prompt that produced it changed."""
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"pdf bytes")

        metadata = build_progress_metadata(
            str(source), None, "deepseek-v4-pro", 0, 10, fuzzy_matching=True
        )

        assert metadata["fuzzy_matching"] is True
        assert "prompt_version" in metadata
        assert "extractor_version" in metadata
        assert "temperature" in metadata

    def test_worker_count_is_not_fingerprinted(self, tmp_path):
        """Prompts no longer depend on concurrency, so workers must not invalidate."""
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"pdf bytes")

        metadata = build_progress_metadata(
            str(source), None, "deepseek-v4-pro", 0, 10
        )

        assert "max_workers" not in metadata

    def test_fuzzy_matching_change_is_detected_as_a_mismatch(self, tmp_path):
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"pdf bytes")
        progress_file = tmp_path / "run.progress.json"

        strict = build_progress_metadata(str(source), None, "m", 0, 10, fuzzy_matching=False)
        first = ProgressTracker(str(progress_file), expected_metadata=strict)
        first.mark_completed(0, "译文")

        fuzzy = build_progress_metadata(str(source), None, "m", 0, 10, fuzzy_matching=True)
        second = ProgressTracker(str(progress_file), expected_metadata=fuzzy)

        assert second.metadata_mismatches


class TestFingerprintFile:
    def test_missing_path_is_distinguishable_from_no_path(self, tmp_path):
        """"" means no glossary was configured; "missing" means one vanished."""
        assert fingerprint_file(None) == ""
        assert fingerprint_file("") == ""
        assert fingerprint_file(str(tmp_path / "gone.tsv")) == "missing"

    def test_existing_file_hashes(self, tmp_path):
        target = tmp_path / "g.tsv"
        target.write_text("特工\tAgent\n", encoding="utf-8")

        digest = fingerprint_file(str(target))

        assert len(digest) == 64
        assert digest not in ("", "missing")
