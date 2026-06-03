"""
HTML exporter — generates a printable dual-column HTML document from
translated page blocks.

Dependencies: exporters._shared (for pagination and text helpers)
"""

import html
import re
from pathlib import Path
from typing import Optional

from exporters._shared import (
    paginate_translated_blocks,
    _is_plain_heading_line,
    _is_soft_subheading_line,
    _format_page_ranges,
    _format_source_page_note,
    _without_image_blocks,
    _header_title,
    _display_title,
    attach_running_headers,
    _looks_like_stat_block,
    _looks_like_markdown_table_row,
    _is_markdown_table_separator_row,
    _layout_uses_columns,
    _normalize_heading_markup,
    _normalize_marker_line,
    _strip_list_marker,
    _strip_quote_prefix,
)
from core.utils import ensure_output_parent


# ---------------------------------------------------------------------------
# HTML-specific internal helpers
# ---------------------------------------------------------------------------

def _html_inline(text: str) -> str:
    text = html.escape(text.strip())
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return text


def _is_markdown_table_separator(line: str) -> bool:
    return _is_markdown_table_separator_row(line)


def _table_cells(line: str) -> list[str]:
    stripped = _strip_quote_prefix(line).strip().strip("|")
    cells = [cell.strip() for cell in stripped.split("|")]
    return [re.sub(r"^#{1,6}\s*", "", cell).strip() for cell in cells]


def _html_table(lines: list[str], class_name: str = "aid-table") -> str:
    rows = []
    for raw_line in lines:
        cells = _table_cells(raw_line)
        if cells:
            rows.append(cells)
    if not rows:
        return ""

    header = rows[0]
    body = rows[2:] if len(rows) > 1 and _is_markdown_table_separator(lines[1]) else rows[1:]
    parts = [f'<table class="{class_name}">', "<thead><tr>"]
    for cell in header:
        parts.append(f"<th>{_html_inline(cell)}</th>")
    parts.append("</tr></thead><tbody>")
    for row in body:
        parts.append("<tr>")
        for idx in range(len(header)):
            cell = row[idx] if idx < len(row) else ""
            parts.append(f"<td>{_html_inline(cell)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _html_list(items: list[str], class_name: str = "") -> str:
    class_attr = f' class="{class_name}"' if class_name else ""
    inner = "".join(f"<li>{_html_inline(item)}</li>" for item in items if item)
    return f"<ul{class_attr}>{inner}</ul>" if inner else ""


def _clean_card_line(line: str) -> str:
    clean = _strip_quote_prefix(line)
    clean = _normalize_heading_markup(clean)
    clean = _normalize_marker_line(clean)
    return clean.strip()


def _card_title_text(line: str) -> str:
    return re.sub(r"^#{1,6}\s*", "", _clean_card_line(line)).strip()


def _append_card_body(parts: list[str], lines: list[str]):
    idx = 0
    while idx < len(lines):
        clean = _clean_card_line(lines[idx])
        if not clean:
            idx += 1
            continue

        if _looks_like_markdown_table_row(clean):
            table_lines = [clean]
            idx += 1
            while idx < len(lines):
                peek = _clean_card_line(lines[idx])
                if _looks_like_markdown_table_row(peek) or _is_markdown_table_separator(peek):
                    table_lines.append(peek)
                    idx += 1
                    continue
                break
            parts.append(_html_table(table_lines, "aid-table card-table"))
            continue

        list_item = _strip_list_marker(clean)
        if list_item:
            items = [list_item]
            idx += 1
            while idx < len(lines):
                peek = _clean_card_line(lines[idx])
                next_item = _strip_list_marker(peek)
                if next_item:
                    items.append(next_item)
                    idx += 1
                    continue
                break
            parts.append(_html_list(items, "card-list"))
            continue

        if re.match(r"^#{1,6}\s+", clean) or _is_soft_subheading_line(clean):
            heading_text = re.sub(r"^#{1,6}\s*", "", clean)
            parts.append(f'<h4 class="card-subheading">{_html_inline(heading_text)}</h4>')
            idx += 1
            continue

        paragraph_text = re.sub(r"^#{1,6}\s*", "", clean)
        parts.append(f"<p>{_html_inline(paragraph_text)}</p>")
        idx += 1


def _html_handout_card(lines: list[str]) -> str:
    clean_lines = [_clean_card_line(line) for line in lines if _clean_card_line(line)]
    card_class = "handout-card"
    if len(clean_lines) >= 8:
        card_class += " handout-card-long"
    parts = [f'<div class="{card_class}">']
    body_lines = clean_lines
    if clean_lines and len(re.sub(r"\s+", "", _card_title_text(clean_lines[0]))) <= 80:
        parts.append(f"<h3>{_html_inline(_card_title_text(clean_lines[0]))}</h3>")
        body_lines = clean_lines[1:]
    _append_card_body(parts, body_lines)
    parts.append("</div>")
    return "".join(parts)


def _html_stat_block(lines: list[str]) -> str:
    if not _looks_like_stat_block("\n".join(lines)):
        return _html_handout_card(lines)
    parts = ['<div class="stat-block">']
    for idx, line in enumerate(lines):
        clean = line.strip()
        if not clean:
            continue
        if idx == 0 and len(re.sub(r"\s+", "", clean)) <= 80:
            parts.append(f"<h3>{_html_inline(clean)}</h3>")
        else:
            parts.append(f"<p>{_html_inline(clean)}</p>")
    parts.append("</div>")
    return "".join(parts)


def _relative_asset_path(asset_path: str, output_path: str) -> str:
    try:
        return Path(asset_path).resolve().relative_to(Path(output_path).resolve().parent).as_posix()
    except ValueError:
        return Path(asset_path).as_posix()


def _image_asset_path(asset) -> str:
    if isinstance(asset, dict):
        return str(asset.get("path") or "")
    return str(asset or "")


def _image_asset_placement(asset) -> str:
    if isinstance(asset, dict):
        placement = str(asset.get("placement") or "full").lower()
        if placement in {"left", "right", "full"}:
            return placement
    return "full"


def _html_image_placeholder(lines: list[str], image_path="", html_output: str = "") -> str:
    label = " ".join(line.strip() for line in lines if line.strip()) or "插图"
    if label.lower() == "illustration placeholder":
        label = "插图"
    asset_path = _image_asset_path(image_path)
    if asset_path:
        src = html.escape(_relative_asset_path(asset_path, html_output))
        placement = _image_asset_placement(image_path)
        return (
            f'<figure class="source-image source-image-{placement}">'
            f'<img src="{src}" alt="{_html_inline(label)}">'
            f'<figcaption>{_html_inline(label)}</figcaption>'
            '</figure>'
        )
    return f'<figure class="image-placeholder"><div></div><figcaption>{_html_inline(label)}</figcaption></figure>'


def _html_block(text: str, image_paths=None, image_cursor=None, html_output: str = "") -> str:
    parts = []
    lines = text.split("\n")
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        clean_line = line.strip()
        idx += 1
        if not clean_line or clean_line == "---" or clean_line.startswith("<!--"):
            continue
        clean_line = _normalize_heading_markup(clean_line)
        clean_line = _normalize_marker_line(clean_line)

        if clean_line == "[[TOC]]":
            continue

        if clean_line == "[FULL_WIDTH_TITLE]":
            title_lines = []
            while idx < len(lines) and _normalize_marker_line(lines[idx]) != "[/FULL_WIDTH_TITLE]":
                title_lines.append(lines[idx].strip())
                idx += 1
            if idx < len(lines) and _normalize_marker_line(lines[idx]) == "[/FULL_WIDTH_TITLE]":
                idx += 1
            clean_title_lines = [
                re.sub(r"^#{1,6}\s*", "", line).strip()
                for line in title_lines
                if line.strip()
            ]
            clean_title_lines = [line for line in clean_title_lines if line]
            if clean_title_lines:
                title = clean_title_lines[0]
                subtitle = " ".join(clean_title_lines[1:])
                subtitle_html = f'<p>{_html_inline(subtitle)}</p>' if subtitle else ""
                parts.append(
                    '<div class="full-width-title"><span></span><div>'
                    f'<h1>{_html_inline(title)}</h1>{subtitle_html}'
                    '</div><span></span></div>'
                )
            continue

        if clean_line == "[CARD]":
            card_lines = []
            while idx < len(lines) and _normalize_marker_line(lines[idx]) != "[/CARD]":
                card_lines.append(lines[idx].strip())
                idx += 1
            if idx < len(lines) and _normalize_marker_line(lines[idx]) == "[/CARD]":
                idx += 1
            parts.append(_html_handout_card(card_lines))
            continue

        if clean_line == "[STAT_BLOCK]":
            stat_lines = []
            while idx < len(lines) and _normalize_marker_line(lines[idx]) != "[/STAT_BLOCK]":
                stat_lines.append(lines[idx].strip())
                idx += 1
            if idx < len(lines) and _normalize_marker_line(lines[idx]) == "[/STAT_BLOCK]":
                idx += 1
            parts.append(_html_stat_block(stat_lines))
            continue

        if clean_line == "[IMAGE]":
            image_lines = []
            while idx < len(lines) and _normalize_marker_line(lines[idx]) != "[/IMAGE]":
                image_lines.append(lines[idx].strip())
                idx += 1
            if idx < len(lines) and _normalize_marker_line(lines[idx]) == "[/IMAGE]":
                idx += 1
            image_path = ""
            if image_paths is not None and image_cursor is not None:
                cursor = image_cursor[0]
                if cursor < len(image_paths):
                    image_path = image_paths[cursor]
                image_cursor[0] = cursor + 1
            parts.append(_html_image_placeholder(image_lines, image_path, html_output))
            continue

        if clean_line.startswith("```toc"):
            toc_lines = []
            while idx < len(lines) and not lines[idx].strip().startswith("```"):
                toc_lines.append(lines[idx].rstrip())
                idx += 1
            if idx < len(lines) and lines[idx].strip().startswith("```"):
                idx += 1
            parts.append('<pre class="toc-card">' + html.escape("\n".join(toc_lines)) + "</pre>")
            continue

        if _looks_like_markdown_table_row(clean_line):
            table_lines = [clean_line]
            while idx < len(lines):
                peek = _normalize_marker_line(lines[idx].strip())
                if _looks_like_markdown_table_row(peek) or _is_markdown_table_separator(peek):
                    table_lines.append(peek)
                    idx += 1
                    continue
                break
            parts.append(_html_table(table_lines))
            continue

        list_item = _strip_list_marker(clean_line)
        if list_item:
            items = [list_item]
            while idx < len(lines):
                peek = _normalize_marker_line(lines[idx].strip())
                next_item = _strip_list_marker(peek)
                if next_item:
                    items.append(next_item)
                    idx += 1
                    continue
                break
            parts.append(_html_list(items))
            continue

        if clean_line.startswith(">"):
            quote_lines = [clean_line.lstrip(">").strip()]
            while idx < len(lines) and lines[idx].strip().startswith(">"):
                quote_lines.append(lines[idx].strip().lstrip(">").strip())
                idx += 1
            parts.append(_html_handout_card(quote_lines))
            continue

        if clean_line.startswith("#### "):
            parts.append(f"<h4>{_html_inline(clean_line[5:])}</h4>")
        elif clean_line.startswith("### "):
            parts.append(f"<h3>{_html_inline(clean_line[4:])}</h3>")
        elif clean_line.startswith("## "):
            parts.append(f"<h2>{_html_inline(clean_line[3:])}</h2>")
        elif clean_line.startswith("# "):
            parts.append(f"<h1>{_html_inline(clean_line[2:])}</h1>")
        elif _is_plain_heading_line(clean_line):
            parts.append(f"<h2>{_html_inline(clean_line)}</h2>")
        elif _is_soft_subheading_line(clean_line):
            parts.append(f'<h4 class="soft-subheading">{_html_inline(clean_line)}</h4>')
        else:
            parts.append(f"<p>{_html_inline(clean_line)}</p>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_html_output(translated_pages, html_output: str, title: str, subtitle: str = "中文翻译",
                      min_chars=1200, max_chars=1800, columns=2,
                      header_left="绿色三角洲", header_right=None,
                      source_page_labels: Optional[dict] = None,
                      page_layouts: Optional[dict] = None,
                      image_assets: Optional[dict] = None):
    """Write translated content as a printable dual-column HTML document."""
    min_chars = int(min_chars)
    max_chars = int(max_chars)
    columns = int(columns)
    if min_chars < 1 or max_chars < min_chars:
        raise ValueError("HTML 阅读页字数范围无效")
    if columns not in (1, 2):
        raise ValueError("HTML 正文分栏只支持 1 或 2 栏")

    ensure_output_parent(html_output)
    translated_pages = _without_image_blocks(translated_pages)
    reading_pages = attach_running_headers(paginate_translated_blocks(
        translated_pages,
        min_chars,
        max_chars,
        page_layouts=page_layouts,
        split_on_layout=True,
    ), title)
    display_title = _display_title(title, reading_pages)
    default_right_title = (header_right or _header_title(display_title)).strip()
    right_title = html.escape(default_right_title)
    left_title = html.escape((header_left or "绿色三角洲").strip())
    safe_title = html.escape(display_title)
    safe_subtitle = html.escape(subtitle or "")

    css = f"""
    :root {{
        color-scheme: light;
        --paper: #f7f2e8;
        --ink: #111111;
        --red: #d80000;
        --muted: #77716a;
        --rule: #b9b0a5;
    }}
    * {{ box-sizing: border-box; }}
    body {{
        margin: 0;
        background: #d8d2cc;
        color: var(--ink);
        font-family: "Noto Serif SC", "Songti SC", "SimSun", serif;
        line-height: 1.72;
    }}
    .sheet {{
        width: 8.5in;
        min-height: 11in;
        margin: 18px auto;
        padding: 0.34in 0.48in 0.52in;
        background:
            radial-gradient(circle at 12% 18%, rgba(160, 132, 93, 0.11), transparent 22%),
            radial-gradient(circle at 85% 70%, rgba(126, 96, 62, 0.08), transparent 24%),
            var(--paper);
        box-shadow: 0 4px 18px rgba(0, 0, 0, 0.22);
        break-after: page;
        page-break-after: always;
    }}
    .running-head {{
        display: flex;
        justify-content: space-between;
        gap: 2rem;
        align-items: baseline;
        margin-bottom: 0.28in;
        padding-bottom: 0.08in;
        border-bottom: 1px solid var(--rule);
        color: var(--muted);
        font: 10pt "Courier New", monospace;
        letter-spacing: 0;
    }}
    .running-head span:last-child {{
        text-align: right;
    }}
    .content {{
        column-count: {columns};
        column-gap: 0.52in;
        font-size: 12pt;
    }}
    h1, h2, h3, h4 {{
        break-after: avoid;
        page-break-after: avoid;
        font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif;
        line-height: 1.12;
        letter-spacing: 0;
    }}
    h1 {{
        column-span: all;
        margin: 0 0 0.28in;
        font-size: 20pt;
        font-weight: 500;
        color: var(--ink);
    }}
    .full-width-title {{
        column-span: all;
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
        align-items: center;
        gap: 0.14in;
        margin: 0.04in 0 0.28in;
        break-after: avoid;
        page-break-after: avoid;
    }}
    .full-width-title span {{
        height: 0.08in;
        background: var(--ink);
    }}
    .full-width-title h1 {{
        margin: 0;
        font-size: 24pt;
        font-weight: 700;
        white-space: normal;
        text-align: center;
    }}
    .full-width-title p {{
        margin: 0.04in 0 0;
        text-indent: 0;
        text-align: center;
        font-family: "Courier New", "VT323", monospace;
        font-size: 11pt;
        line-height: 1.25;
    }}
    h2 {{
        margin: 0.06in 0 0.18in;
        color: var(--red);
        font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif;
        font-size: 18pt;
        font-weight: 700;
        padding-bottom: 0.04in;
        border-bottom: 2px solid var(--rule);
    }}
    h3 {{
        margin: 0.16in 0 0.08in;
        color: var(--ink);
        font-family: "Courier New", "VT323", monospace;
        font-size: 16pt;
        font-weight: 700;
    }}
    h4 {{
        margin: 0.12in 0 0.06in;
        color: var(--ink);
        font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif;
        font-size: 16pt;
        font-weight: 700;
    }}
    p {{
        margin: 0 0 0.11in;
        text-indent: 2em;
    }}
    h1 + p, h2 + p, h3 + p, h4 + p {{
        text-indent: 0;
    }}
    ul {{
        margin: 0 0 0.12in 1.2em;
        padding: 0;
    }}
    li {{
        margin-bottom: 0.04in;
    }}
    .aid-table {{
        column-span: all;
        width: 100%;
        margin: 0.18in 0 0.24in;
        border-collapse: collapse;
        font-family: "Courier New", "VT323", monospace;
        font-size: 9pt;
        line-height: 1.35;
        background: rgba(232, 226, 204, 0.58);
    }}
    .aid-table th,
    .aid-table td {{
        padding: 0.06in 0.08in;
        border-top: 1px dashed #5f574f;
        border-bottom: 1px dashed #5f574f;
        vertical-align: top;
    }}
    .aid-table th {{
        text-transform: uppercase;
        letter-spacing: 0.04em;
        font-weight: 700;
    }}
    .handout .content {{
        column-count: 1;
        max-width: 7.25in;
        margin: 0 auto;
    }}
    .handout-card {{
        margin: 0.12in 0 0.18in;
        padding: 0.10in 0.16in 0.11in;
        background: rgba(246, 224, 111, 0.24);
        border-left: 4px solid rgba(176, 137, 28, 0.72);
        border-top: 1px solid rgba(176, 137, 28, 0.22);
        border-bottom: 1px solid rgba(176, 137, 28, 0.22);
        font-family: "Noto Serif SC", "Songti SC", "SimSun", serif;
        break-inside: auto;
        page-break-inside: auto;
    }}
    .handout-card-long {{
        background: rgba(246, 224, 111, 0.16);
        padding-top: 0.08in;
        padding-bottom: 0.08in;
    }}
    .handout-card h3 {{
        margin: 0 0 0.06in;
        color: var(--ink);
        font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif;
        font-size: 12pt;
        font-weight: 700;
    }}
    .handout-card p {{
        margin: 0 0 0.045in;
        text-indent: 0;
        font-size: 10.4pt;
        line-height: 1.48;
    }}
    .handout-card .card-subheading,
    .soft-subheading {{
        margin: 0.12in 0 0.05in;
        color: var(--ink);
        font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif;
        font-size: 11.5pt;
        font-weight: 700;
        text-indent: 0;
    }}
    .card-list {{
        margin: 0 0 0.08in 1.15em;
    }}
    .card-list li {{
        margin-bottom: 0.045in;
        font-size: 10.2pt;
        line-height: 1.45;
    }}
    .card-table {{
        margin: 0.08in 0 0.14in;
        background: rgba(255, 255, 255, 0.36);
    }}
    .stat-block {{
        margin: 0.12in 0 0.22in;
        padding: 0.12in 0.18in;
        border-top: 2px solid var(--ink);
        border-bottom: 2px solid var(--ink);
        background: rgba(255, 255, 255, 0.34);
        font-family: "Courier New", "VT323", monospace;
        break-inside: avoid;
        page-break-inside: avoid;
    }}
    .stat-block h3 {{
        margin: 0 0 0.06in;
        font-size: 12pt;
        text-transform: uppercase;
    }}
    .stat-block p {{
        margin: 0 0 0.04in;
        text-indent: 0;
        font-size: 9.2pt;
        line-height: 1.35;
    }}
    .image-placeholder {{
        column-span: all;
        margin: 0.16in 0 0.22in;
        break-inside: avoid;
        page-break-inside: avoid;
    }}
    .image-placeholder div {{
        min-height: 1.15in;
        border: 1px dashed var(--muted);
        background: rgba(0, 0, 0, 0.035);
    }}
    .image-placeholder figcaption {{
        margin-top: 0.04in;
        color: var(--muted);
        font: 8.5pt "Courier New", monospace;
        text-align: center;
    }}
    .source-image {{
        margin: 0.16in 0 0.22in;
        break-inside: avoid;
        page-break-inside: avoid;
    }}
    .source-image-full {{
        column-span: all;
    }}
    .source-image-left,
    .source-image-right {{
        column-span: none;
        width: 48%;
        max-width: 2.8in;
        margin-top: 0.04in;
        margin-bottom: 0.12in;
    }}
    .source-image-left {{
        float: left;
        margin-right: 0.14in;
    }}
    .source-image-right {{
        float: right;
        margin-left: 0.14in;
    }}
    .source-image img {{
        display: block;
        max-width: 100%;
        max-height: 3.8in;
        margin: 0 auto;
        object-fit: contain;
    }}
    .source-image figcaption {{
        margin-top: 0.04in;
        color: var(--muted);
        font: 8.5pt "Courier New", monospace;
        text-align: center;
    }}
    .toc .content {{
        column-count: 2;
        column-gap: 0.38in;
        font-size: 10pt;
    }}
    .toc h1 {{
        column-span: all;
        margin-bottom: 0.18in;
        color: var(--ink);
        font-family: "Courier New", "VT323", monospace;
        font-size: 24pt;
    }}
    .toc-card {{
        margin: 0;
        white-space: pre-wrap;
        font-family: "Courier New", "VT323", monospace;
        font-size: 8.7pt;
        line-height: 1.22;
        break-inside: avoid;
        page-break-inside: avoid;
    }}
    .page-meta {{
        column-span: all;
        margin-top: 0.24in;
        padding-top: 0.06in;
        border-top: 1px solid var(--rule);
        color: var(--muted);
        font: 8.5pt "Courier New", monospace;
        display: flex;
        justify-content: space-between;
        gap: 1rem;
    }}
    .page-meta span:last-child {{
        text-align: right;
    }}
    .cover .content {{
        column-count: 1;
    }}
    .sheet.single .content,
    .sheet.character .content,
    .sheet.document .content,
    .sheet.credits .content,
    .sheet.art .content {{
        column-count: 1;
        max-width: 7.25in;
        margin: 0 auto;
        font-size: 12pt;
        line-height: 1.74;
    }}
    .sheet.single h2 {{
        margin-top: 0.08in;
        padding-bottom: 0.05in;
        border-bottom: 1px solid var(--rule);
    }}
    .sheet.character .content {{
        max-width: 7.35in;
        font-size: 11pt;
        line-height: 1.62;
    }}
    .sheet.character p,
    .sheet.document p,
    .sheet.credits p,
    .sheet.art p {{
        text-indent: 0;
    }}
    .sheet.character h2,
    .sheet.document h2 {{
        margin-top: 0.08in;
        padding-bottom: 0.05in;
        border-bottom: 1px solid var(--rule);
    }}
    .sheet.document .content {{
        max-width: 6.55in;
        font-size: 11.2pt;
        line-height: 1.58;
    }}
    .sheet.document p {{
        font-family: "Courier New", "VT323", monospace;
    }}
    .sheet.credits .content {{
        max-width: 6.2in;
        font-size: 10.8pt;
        line-height: 1.46;
    }}
    .sheet.credits h1,
    .sheet.credits h2,
    .sheet.credits h3,
    .sheet.credits h4,
    .sheet.credits p {{
        text-align: center;
    }}
    .sheet.art .content {{
        max-width: 5.9in;
        margin-top: 1.55in;
        text-align: center;
    }}
    .sheet.art h1,
    .sheet.art h2,
    .sheet.art h3,
    .sheet.art h4 {{
        text-align: center;
        border: 0;
        padding-bottom: 0;
    }}
    .sheet.art p {{
        text-align: center;
        color: var(--muted);
    }}
    .sheet.single .page-meta {{
        column-span: none;
    }}
    .page-meta.no-span {{
        column-span: none;
    }}
    .cover-title {{
        margin-top: 1.15in;
        font: 32pt "Noto Sans SC", "Microsoft YaHei", sans-serif;
        letter-spacing: 0;
    }}
    .cover-subtitle {{
        color: #2d73b9;
        font: 14pt "Noto Sans SC", "Microsoft YaHei", sans-serif;
        text-indent: 0;
    }}
    @page {{
        size: Letter;
        margin: 0;
    }}
    @media print {{
        body {{ background: white; }}
        .sheet {{
            margin: 0;
            box-shadow: none;
            width: 8.5in;
            min-height: 11in;
        }}
    }}
    """

    chunks = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{safe_title} - 中文翻译</title>",
        f"<style>{css}</style>",
        "</head>",
        "<body>",
        '<section class="sheet cover">',
        '<main class="content">',
        f'<h1 class="cover-title">{safe_title}</h1>',
        f'<p class="cover-subtitle">{safe_subtitle}</p>' if safe_subtitle else "",
        "</main>",
        "</section>",
    ]
    image_cursors = {}

    for page_idx, page in enumerate(reading_pages, 1):
        blocks = page["blocks"]
        layout = page.get("layout", "columns")
        page_right_title = html.escape(page.get("running_header") or default_right_title)
        source_pages = _format_page_ranges([b["source_page"] for b in blocks], source_page_labels)
        source_note = html.escape(_format_source_page_note([b["source_page"] for b in blocks], source_page_labels))
        source_class = "" if _layout_uses_columns(layout) else " no-span"
        chunks.extend([
            f'<section class="sheet {html.escape(layout)}">',
            (
                ""
                if layout == "toc"
                else f'<header class="running-head"><span>// {left_title} //</span><span>// {page_right_title} //</span></header>'
            ),
            '<main class="content">',
        ])
        for block in blocks:
            source_page = block.get("source_page")
            image_paths = (image_assets or {}).get(source_page, [])
            cursor = image_cursors.setdefault(source_page, [0])
            chunks.append(_html_block(block["text"], image_paths, cursor, html_output))
        chunks.append(
            f'<footer class="page-meta{source_class}"><span>阅读版 {page_idx}</span><span>{source_note or html.escape(source_pages)}</span></footer>'
        )
        chunks.extend(["</main>", "</section>"])

    chunks.extend(["</body>", "</html>", ""])
    with open(html_output, "w", encoding="utf-8") as f:
        f.write("\n".join(chunk for chunk in chunks if chunk != ""))
