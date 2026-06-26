"""Runtime helpers for the Streamlit app."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path

import streamlit as st

from webui.history import is_final_output_file


APP_DIR = Path(__file__).resolve().parent.parent
PLAYWRIGHT_PERCENT_PATTERN = re.compile(r"(\d{1,3})%")
MAX_WINDOWS_PATH_LENGTH = 240


def make_output_path(output_base, extension):
    """Return a non-overwriting output path for Web downloads."""
    path = output_base + extension
    if not os.path.exists(path):
        return path
    return f"{output_base}_{uuid.uuid4().hex[:8]}{extension}"


def format_duration(seconds):
    if seconds is None:
        return "估算中"
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def existing_output_files(paths, final_only: bool = False):
    files = [Path(path) for path in paths if Path(path).exists()]
    if final_only:
        files = [path for path in files if is_final_output_file(path)]
    return [str(path) for path in files]


def render_downloads(paths, label_prefix="下载"):
    for path in existing_output_files(paths, final_only=True):
        file_path = Path(path)
        with open(file_path, "rb") as f:
            st.download_button(
                f"📥 {label_prefix} {file_path.name}",
                f,
                file_name=file_path.name,
            )


def make_html_asset_bundle(html_path: str | Path) -> str | None:
    html_file = Path(html_path)
    if not html_file.exists():
        return None
    assets_dir = html_file.parent / "assets"
    if not assets_dir.exists():
        return None

    bundle_path = html_file.with_suffix(".html_assets.zip")
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(html_file, arcname=html_file.name)
        for asset in sorted(assets_dir.rglob("*")):
            if asset.is_file():
                zf.write(asset, arcname=str(asset.relative_to(html_file.parent)))
    return str(bundle_path)


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def safe_filename_stem(filename: str, default: str = "document", max_length: int = 96) -> str:
    stem = Path(filename or default).stem
    stem = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", stem).strip("._-")
    if not stem:
        return default
    return stem[:max_length].strip("._-") or default


def _stem_length_for_path(directory: Path, prefix: str, digest: str, suffix: str) -> int:
    directory_length = len(str(directory.resolve()))
    fixed_length = len(prefix) + 1 + len(digest) + len(suffix)
    max_length = MAX_WINDOWS_PATH_LENGTH - directory_length - fixed_length
    if max_length < 12:
        raise ValueError(f"上传目录路径过长：{directory}")
    return min(96, max_length)


def uploaded_file_digest(uploaded_file) -> str:
    return hashlib.sha256(uploaded_file.getvalue()).hexdigest()


def file_digest(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_uploaded_file_once(uploaded_file, upload_dir: Path, default_name: str = "document") -> Path:
    ensure_dir(upload_dir)
    data = uploaded_file.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    suffix = Path(uploaded_file.name or "").suffix.lower()
    prefix = "_upload_"
    stem = safe_filename_stem(
        uploaded_file.name,
        default_name,
        max_length=_stem_length_for_path(upload_dir, prefix, digest, suffix),
    )

    for existing in sorted(upload_dir.glob(f"*{suffix}")):
        if existing.is_file() and file_digest(existing) == digest:
            return existing

    target = upload_dir / f"{prefix}{stem}_{digest}{suffix}"
    with open(target, "wb") as f:
        f.write(data)
    return target


def save_uploaded_pdf_for_preview(uploaded_file) -> Path:
    upload_dir = APP_DIR / "uploads"
    ensure_dir(upload_dir)
    digest = uploaded_file_digest(uploaded_file)[:12]
    prefix = "_preview_"
    stem = safe_filename_stem(
        uploaded_file.name,
        max_length=_stem_length_for_path(upload_dir, prefix, digest, ".pdf"),
    )
    target = upload_dir / f"{prefix}{stem}_{digest}.pdf"
    if not target.exists():
        with open(target, "wb") as f:
            f.write(uploaded_file.getvalue())
    return target


def _playwright_chromium_executable_path() -> str | None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        return p.chromium.executable_path


def playwright_chromium_installed() -> bool:
    try:
        executable = _playwright_chromium_executable_path()
    except Exception:
        return False
    return bool(executable) and Path(executable).exists()


def _extract_playwright_progress_percent(line: str) -> int | None:
    match = PLAYWRIGHT_PERCENT_PATTERN.search(line or "")
    if not match:
        return None
    value = int(match.group(1))
    if 0 <= value <= 100:
        return value
    return None


def install_playwright_chromium(progress_callback=None, python_executable: str | None = None):
    command = [
        python_executable or sys.executable,
        "-m",
        "playwright",
        "install",
        "chromium",
    ]
    logs = []

    def emit(message: str, percent: int | None = None):
        if progress_callback is not None:
            progress_callback(message, percent)

    emit("准备加载浏览器内核插件…", 0)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            logs.append(line)
            emit(line, _extract_playwright_progress_percent(line))

    return_code = process.wait()
    if return_code != 0:
        emit("浏览器内核插件加载失败。", None)
        return False, logs

    if not playwright_chromium_installed():
        message = "安装命令已完成，但没有检测到 Chromium 内核。"
        logs.append(message)
        emit(message, None)
        return False, logs

    emit("浏览器内核插件加载完成。", 100)
    return True, logs
