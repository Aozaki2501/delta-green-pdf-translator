"""Runtime helpers for the Streamlit app."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
import zipfile
from pathlib import Path

import streamlit as st

from webui.history import is_final_output_file


APP_DIR = Path(__file__).resolve().parent.parent


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


def safe_filename_stem(filename: str, default: str = "document") -> str:
    stem = Path(filename or default).stem
    stem = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", stem).strip("._-")
    return stem or default


def uploaded_file_digest(uploaded_file) -> str:
    return hashlib.sha256(uploaded_file.getvalue()).hexdigest()


def save_uploaded_pdf_for_preview(uploaded_file) -> Path:
    upload_dir = APP_DIR / "uploads"
    ensure_dir(upload_dir)
    digest = uploaded_file_digest(uploaded_file)[:12]
    target = upload_dir / f"_preview_{safe_filename_stem(uploaded_file.name)}_{digest}.pdf"
    if not target.exists():
        with open(target, "wb") as f:
            f.write(uploaded_file.getvalue())
    return target
