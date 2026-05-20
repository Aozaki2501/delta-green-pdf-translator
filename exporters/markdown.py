"""
Markdown exporter module.

Provides write_markdown_output for generating paginated Markdown translation
files with reading-page structure, table of contents, and source-page annotations.

Dependencies: core.utils (ensure_output_parent), exporters._shared (pagination and helpers)
"""

from core.utils import ensure_output_parent
from exporters._shared import (
    paginate_translated_blocks,
    _format_page_ranges,
    _is_plain_heading_line,
    _looks_like_stat_block,
)


# ---------------------------------------------------------------------------
# Markdown-specific helpers
# ---------------------------------------------------------------------------

def _format_markdown_block(text: str) -> str:
    lines = []
    in_full_title = False
    in_stat = False
    stat_is_real = True
    in_image = False
    for line in text.split("\n"):
        stripped = line.strip()
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
                          min_chars=1000, max_chars=1500):
    ensure_output_parent(md_output)
    reading_pages = paginate_translated_blocks(translated_pages, min_chars, max_chars)
    with open(md_output, "w", encoding="utf-8") as f:
        f.write(f"# {title} — 中文翻译\n\n---\n\n")

        if toc:
            f.write(toc)
            f.write("\n---\n\n")

        for page_idx, page in enumerate(reading_pages, 1):
            blocks = page["blocks"]
            source_pages = _format_page_ranges([b["source_page"] for b in blocks])
            f.write(f"<!-- Reading Page {page_idx}; Source PDF Pages: {source_pages} -->\n\n")
            for block in blocks:
                f.write(_format_markdown_block(block["text"]))
                f.write("\n\n")
            f.write("---\n\n")
