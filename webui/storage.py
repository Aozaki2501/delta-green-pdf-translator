"""Storage inspection and cleanup for uploads/ and output/.

Both directories accumulate copyrighted source PDFs, full English source text
and full translations, and multi-megabyte asset bundles. Nothing in the project
ever removed them, so this module provides the listing and deletion primitives
the Web UI needs to offer a cleanup entry point.

Dependencies: standard library only.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StorageEntry:
    """One deletable unit: an upload file or one task's output folder."""

    path: Path
    name: str
    size_bytes: int
    modified_at: float
    is_dir: bool

    @property
    def age_days(self) -> float:
        return max(0.0, (time.time() - self.modified_at) / 86400.0)


def directory_size(path: Path) -> int:
    """Total size of a file, or of every file under a directory."""
    target = Path(path)
    if target.is_file():
        return target.stat().st_size
    total = 0
    for item in target.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def scan_storage(root: str | Path) -> list[StorageEntry]:
    """List the top-level entries under ``root``, newest first.

    Output tasks are one folder each and uploads are single files, so the top
    level is exactly the granularity a user deletes at.
    """
    root_path = Path(root)
    if not root_path.exists():
        return []

    entries = []
    for item in root_path.iterdir():
        try:
            stat = item.stat()
        except OSError:
            continue
        entries.append(StorageEntry(
            path=item,
            name=item.name,
            size_bytes=directory_size(item),
            modified_at=stat.st_mtime,
            is_dir=item.is_dir(),
        ))
    entries.sort(key=lambda entry: entry.modified_at, reverse=True)
    return entries


def total_size(entries: list[StorageEntry]) -> int:
    return sum(entry.size_bytes for entry in entries)


def entries_older_than(entries: list[StorageEntry], days: float) -> list[StorageEntry]:
    """Entries untouched for at least ``days`` days."""
    if days <= 0:
        return list(entries)
    return [entry for entry in entries if entry.age_days >= days]


def format_size(size_bytes: int) -> str:
    size = float(max(0, size_bytes))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def delete_entry(path: str | Path, root: str | Path) -> int:
    """Delete one entry, refusing anything outside ``root``.

    Returns the number of bytes freed. The containment check keeps a crafted or
    mistyped path from reaching the rest of the disk.
    """
    root_path = Path(root).resolve()
    target = Path(path).resolve()

    if target == root_path:
        raise ValueError(f"不能删除根目录本身：{target}")
    if root_path not in target.parents:
        raise ValueError(f"路径超出允许范围，拒绝删除：{target}")
    if not target.exists():
        return 0

    freed = directory_size(target)
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return freed
