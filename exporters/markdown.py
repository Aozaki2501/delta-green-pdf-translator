"""
Markdown exporter module.

Provides write_markdown_output for generating paginated Markdown translation
files with reading-page structure, table of contents, and source-page annotations.

Dependencies: core.utils (ensure_output_parent), exporters._shared (pagination and helpers)
"""

from core.utils import atomic_output_path, ensure_output_parent
from pathlib import Path
from exporters._shared import (
    paginate_translated_blocks,
    _format_page_ranges,
    _is_plain_heading_line,
    _looks_like_stat_block,
    _normalize_heading_markup,
    _normalize_marker_line,
)


# ---------------------------------------------------------------------------
# Markdown-specific helpers
# ---------------------------------------------------------------------------

def _image_asset_path(asset) -> str:
    if isinstance(asset, dict):
        return str(asset.get("path") or "")
    return str(asset or "")


def _format_markdown_block(text: str, image_paths=None, image_cursor=None, md_output: str = "") -> str:
    lines = []
    in_full_title = False
    in_stat = False
    stat_is_real = True
    in_image = False
    for line in text.split("\n"):
        line = _normalize_heading_markup(line)
        stripped = _normalize_marker_line(line)
        if stripped == "[FULL_WIDTH_TITLE]":
            in_full_title = True
            lines.append("<div style=\"page-break-before: always;\"></div>")
        elif stripped == "[/FULL_WIDTH_TITLE]":
            in_full_title = False
        elif stripped == "[STAT_BLOCK]":
            in_stat = True
            stat_is_real = _looks_like_stat_block(text)
            lines.append("> **人物数据**" if stat_is_real else "[CARD]")
        elif stripped == "[/STAT_BLOCK]":
            if not stat_is_real:
                lines.append("[/CARD]")
            in_stat = False
        elif stripped == "[IMAGE]":
            in_image = True
            image_path = ""
            if image_paths is not None and image_cursor is not None:
                cursor = image_cursor[0]
                if cursor < len(image_paths):
                    image_path = _image_asset_path(image_paths[cursor])
                image_cursor[0] = cursor + 1
            if image_path:
                try:
                    rel = Path(image_path).resolve().relative_to(Path(md_output).resolve().parent).as_posix()
                except ValueError:
                    rel = Path(image_path).as_posix()
                lines.append(f"![图片]({rel})")
            else:
                lines.append("> [图片占位]")
        elif stripped == "[/IMAGE]":
            in_image = False
        elif stripped in ("[CARD]", "[/CARD]"):
            lines.append(stripped)
        elif in_full_title:
            lines.append(stripped)
        elif in_stat or in_image:
            lines.append("> " + stripped if stripped else ">")
        elif _is_plain_heading_line(stripped):
            lines.append(f"### {stripped}")
        else:
            lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_markdown_output(translated_pages, md_output: str, title: str, toc: str = "",
                          min_chars=1000, max_chars=1500, page_layouts=None,
                          image_assets=None):
    ensure_output_parent(md_output)
    reading_pages = paginate_translated_blocks(
        translated_pages,
        min_chars,
        max_chars,
        page_layouts=page_layouts,
        split_on_layout=True,
    )
    with atomic_output_path(md_output) as candidate:
        with candidate.open("w", encoding="utf-8") as f:
            f.write(f"# {title} — 中文翻译\n\n---\n\n")

            if toc:
                f.write(toc)
                f.write("\n---\n\n")

            image_cursors = {}
            for page_idx, page in enumerate(reading_pages, 1):
                blocks = page["blocks"]
                layout = page.get("layout", "columns")
                source_pages = _format_page_ranges([b["source_page"] for b in blocks])
                f.write(f"<!-- Reading Page {page_idx}; Layout: {layout}; Source PDF Pages: {source_pages} -->\n\n")
                for block in blocks:
                    source_page = block.get("source_page")
                    image_paths = (image_assets or {}).get(source_page, [])
                    cursor = image_cursors.setdefault(source_page, [0])
                    f.write(_format_markdown_block(block["text"], image_paths, cursor, md_output))
                    f.write("\n\n")
                f.write("---\n\n")
