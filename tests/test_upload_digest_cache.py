"""Upload deduplication must not re-hash the whole library on every rerun.

save_uploaded_file_once hashed every same-suffix file in uploads/ to find a
duplicate. With a few dozen stored PDFs that is hundreds of megabytes read on
each Streamlit rerun. Files this code writes already carry their sha256 in the
name, so the digest can be read from the filename instead.
"""

from pathlib import Path

import webui.runtime as runtime
from webui.runtime import cached_file_digest, file_digest, save_uploaded_file_once


class _Upload:
    def __init__(self, name, data):
        self.name = name
        self._data = data

    def getvalue(self):
        return self._data


class TestCachedFileDigest:
    def test_digest_is_read_from_the_filename(self, tmp_path, monkeypatch):
        data = b"pdf bytes"
        digest = file_digest_of(tmp_path, data)
        target = tmp_path / f"_upload_Book_{digest}.pdf"
        target.write_bytes(data)

        def fail(_path):
            raise AssertionError("file must not be re-read")

        monkeypatch.setattr(runtime, "file_digest", fail)

        assert cached_file_digest(target) == digest

    def test_digest_matches_the_real_hash(self, tmp_path):
        data = b"pdf bytes"
        digest = file_digest_of(tmp_path, data)
        target = tmp_path / f"_upload_Book_{digest}.pdf"
        target.write_bytes(data)

        assert cached_file_digest(target) == file_digest(target)

    def test_file_without_a_digest_in_the_name_is_hashed(self, tmp_path):
        target = tmp_path / "manual_copy.pdf"
        target.write_bytes(b"pdf bytes")

        assert cached_file_digest(target) == file_digest(target)

    def test_second_lookup_is_served_from_cache(self, tmp_path, monkeypatch):
        target = tmp_path / "manual_copy.pdf"
        target.write_bytes(b"pdf bytes")
        first = cached_file_digest(target)

        calls = []
        real = runtime.file_digest

        def counting(path):
            calls.append(path)
            return real(path)

        monkeypatch.setattr(runtime, "file_digest", counting)
        second = cached_file_digest(target)

        assert second == first
        assert calls == []

    def test_rewritten_file_is_rehashed(self, tmp_path):
        """The cache keys on size and mtime, so edited content must not go stale."""
        target = tmp_path / "manual_copy.pdf"
        target.write_bytes(b"first version")
        first = cached_file_digest(target)

        target.write_bytes(b"second version, different length")
        second = cached_file_digest(target)

        assert second != first
        assert second == file_digest(target)

    def test_missing_file_returns_empty(self, tmp_path):
        assert cached_file_digest(tmp_path / "gone.pdf") == ""


class TestSaveUploadedFileOnce:
    def test_same_content_reuses_the_stored_file(self, tmp_path):
        upload = _Upload("Book.pdf", b"pdf bytes")

        first = save_uploaded_file_once(upload, tmp_path)
        second = save_uploaded_file_once(_Upload("Other Name.pdf", b"pdf bytes"), tmp_path)

        assert first == second
        assert len(list(tmp_path.glob("*.pdf"))) == 1

    def test_different_content_is_stored_separately(self, tmp_path):
        first = save_uploaded_file_once(_Upload("Book.pdf", b"one"), tmp_path)
        second = save_uploaded_file_once(_Upload("Book.pdf", b"two"), tmp_path)

        assert first != second
        assert len(list(tmp_path.glob("*.pdf"))) == 2

    def test_dedup_does_not_read_stored_files(self, tmp_path, monkeypatch):
        save_uploaded_file_once(_Upload("A.pdf", b"one"), tmp_path)
        save_uploaded_file_once(_Upload("B.pdf", b"two"), tmp_path)

        def fail(_path):
            raise AssertionError("stored uploads must not be re-hashed")

        monkeypatch.setattr(runtime, "file_digest", fail)

        assert save_uploaded_file_once(_Upload("A.pdf", b"one"), tmp_path).exists()

    def test_stored_name_carries_the_digest(self, tmp_path):
        target = save_uploaded_file_once(_Upload("Book.pdf", b"pdf bytes"), tmp_path)

        assert cached_file_digest(target) == file_digest(target)


def file_digest_of(tmp_path: Path, data: bytes) -> str:
    probe = tmp_path / "_probe.bin"
    probe.write_bytes(data)
    digest = file_digest(probe)
    probe.unlink()
    return digest
