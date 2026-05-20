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
    _normalize_heading_markup,
)


# ---------------------------------------------------------------------------
# Markdown-specific helpers
# ---------------------------------------------------------------------------

def _format_markdown_block(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        line = _normalize_heading_markup(line)
        stripped = line.strip()
        if stripped in ("[CARD]", "[/CARD]"):
            lines.append(stripped)
        elif _is_plain_heading_line(stripped):
            lines.append(f"### {stripped}")
        else:
            lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_markdown_output(translated_pages, md_output: str, title: str, toc: str = "",
                          min_chars=1000, max_chars=1500, page_layouts=None):
    ensure_output_parent(md_output)
    reading_pages = paginate_translated_blocks(
        translated_pages,
        min_chars,
        max_chars,
        page_layouts=page_layouts,
        split_on_layout=True,
    )
    with open(md_output, "w", encoding="utf-8") as f:
        f.write(f"# {title} — 中文翻译\n\n---\n\n")

        if toc:
            f.write(toc)
            f.write("\n---\n\n")

        for page_idx, page in enumerate(reading_pages, 1):
            blocks = page["blocks"]
            layout = page.get("layout", "columns")
            source_pages = _format_page_ranges([b["source_page"] for b in blocks])
            f.write(f"<!-- Reading Page {page_idx}; Layout: {layout}; Source PDF Pages: {source_pages} -->\n\n")
            for block in blocks:
                f.write(_format_markdown_block(block["text"]))
                f.write("\n\n")
            f.write("---\n\n")
