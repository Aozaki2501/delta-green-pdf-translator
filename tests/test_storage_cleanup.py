"""Storage listing and deletion for uploads/ and output/.

Nothing in the project ever removed these directories, so copyrighted sources
and full translations accumulated indefinitely with no way to see or clear them.
"""

import time

import pytest

from webui.storage import (
    delete_entry,
    directory_size,
    entries_older_than,
    format_size,
    scan_storage,
    total_size,
)


def _make_file(path, size=100):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


class TestScanStorage:
    def test_missing_directory_is_empty(self, tmp_path):
        assert scan_storage(tmp_path / "nope") == []

    def test_files_and_folders_are_listed_at_top_level(self, tmp_path):
        _make_file(tmp_path / "a.pdf")
        _make_file(tmp_path / "task1" / "out.html")

        entries = scan_storage(tmp_path)

        assert {entry.name for entry in entries} == {"a.pdf", "task1"}
        assert {entry.is_dir for entry in entries} == {True, False}

    def test_folder_size_counts_nested_files(self, tmp_path):
        _make_file(tmp_path / "task1" / "a.html", size=100)
        _make_file(tmp_path / "task1" / "assets" / "b.png", size=250)

        entries = scan_storage(tmp_path)

        assert entries[0].size_bytes == 350

    def test_newest_entry_comes_first(self, tmp_path):
        old = _make_file(tmp_path / "old.pdf")
        new = _make_file(tmp_path / "new.pdf")
        past = time.time() - 86400 * 10
        import os
        os.utime(old, (past, past))

        entries = scan_storage(tmp_path)

        assert entries[0].name == "new.pdf"
        assert entries[1].name == "old.pdf"


class TestAgeFilter:
    def test_stale_entries_are_selected(self, tmp_path):
        import os
        old = _make_file(tmp_path / "old.pdf")
        _make_file(tmp_path / "new.pdf")
        past = time.time() - 86400 * 30
        os.utime(old, (past, past))

        stale = entries_older_than(scan_storage(tmp_path), days=7)

        assert [entry.name for entry in stale] == ["old.pdf"]

    def test_zero_days_selects_everything(self, tmp_path):
        _make_file(tmp_path / "a.pdf")
        _make_file(tmp_path / "b.pdf")

        assert len(entries_older_than(scan_storage(tmp_path), days=0)) == 2


class TestDeleteEntry:
    def test_deleting_a_file_frees_its_bytes(self, tmp_path):
        target = _make_file(tmp_path / "a.pdf", size=512)

        freed = delete_entry(target, tmp_path)

        assert freed == 512
        assert not target.exists()

    def test_deleting_a_folder_removes_it_recursively(self, tmp_path):
        _make_file(tmp_path / "task1" / "nested" / "a.html", size=64)

        freed = delete_entry(tmp_path / "task1", tmp_path)

        assert freed == 64
        assert not (tmp_path / "task1").exists()

    def test_path_outside_the_root_is_refused(self, tmp_path):
        """Containment is what keeps a bad path from reaching the rest of the disk."""
        outside = _make_file(tmp_path.parent / "outside_target.pdf")

        try:
            with pytest.raises(ValueError):
                delete_entry(outside, tmp_path / "root")
            assert outside.exists()
        finally:
            outside.unlink(missing_ok=True)

    def test_the_root_itself_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            delete_entry(tmp_path, tmp_path)

        assert tmp_path.exists()

    def test_missing_target_frees_nothing(self, tmp_path):
        assert delete_entry(tmp_path / "gone.pdf", tmp_path) == 0


class TestFormatting:
    def test_total_size_sums_entries(self, tmp_path):
        _make_file(tmp_path / "a.pdf", size=100)
        _make_file(tmp_path / "b.pdf", size=200)

        assert total_size(scan_storage(tmp_path)) == 300

    def test_sizes_are_human_readable(self):
        assert format_size(512) == "512 B"
        assert format_size(2048) == "2.0 KB"
        assert format_size(5 * 1024 * 1024) == "5.0 MB"

    def test_directory_size_of_a_single_file(self, tmp_path):
        target = _make_file(tmp_path / "a.pdf", size=77)

        assert directory_size(target) == 77
