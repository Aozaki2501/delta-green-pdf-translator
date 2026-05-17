"""
HTML exporter — generates a printable dual-column HTML document from
translated page blocks.

Dependencies: exporters._shared (for pagination and text helpers)
"""

import html
import re
from typing import Optional

from exporters._shared import (
    paginate_translated_blocks,
    _is_plain_heading_line,
    _format_page_ranges,
    _header_title,
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
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _html_table(lines: list[str]) -> str:
    rows = []
    for raw_line in lines:
        cells = [cell.strip() for cell in raw_line.strip().strip("|").split("|")]
        if cells:
            rows.append(cells)
    if not rows:
        return ""

    header = rows[0]
    body = rows[2:] if len(rows) > 1 and _is_markdown_table_separator(lines[1]) else rows[1:]
    parts = ['<table class="aid-table">', "<thead><tr>"]
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


def _html_handout_card(lines: list[str]) -> str:
    parts = ['<div class="handout-card">']
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


def _html_block(text: str) -> str:
    parts = []
    lines = text.split("\n")
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        clean_line = line.strip()
        idx += 1
        if not clean_line or clean_line == "---" or clean_line.startswith("<!--"):
            continue

        if clean_line == "[[TOC]]":
            continue

        if clean_line == "[FULL_WIDTH_TITLE]":
            title_lines = []
            while idx < len(lines) and lines[idx].strip() != "[/FULL_WIDTH_TITLE]":
                title_lines.append(lines[idx].strip())
                idx += 1
            if idx < len(lines) and lines[idx].strip() == "[/FULL_WIDTH_TITLE]":
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
            while idx < len(lines) and lines[idx].strip() != "[/CARD]":
                card_lines.append(lines[idx].strip())
                idx += 1
            if idx < len(lines) and lines[idx].strip() == "[/CARD]":
                idx += 1
            parts.append(_html_handout_card(card_lines))
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

        if clean_line.startswith("|"):
            table_lines = [clean_line]
            while idx < len(lines) and lines[idx].strip().startswith("|"):
                table_lines.append(lines[idx].strip())
                idx += 1
            parts.append(_html_table(table_lines))
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
        elif clean_line.startswith("- ") or clean_line.startswith("\u2022 "):
            parts.append(f"<ul><li>{_html_inline(clean_line[2:])}</li></ul>")
        else:
            parts.append(f"<p>{_html_inline(clean_line)}</p>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_html_output(translated_pages, html_output: str, title: str, subtitle: str = "中文翻译",
                      min_chars=1200, max_chars=1800, columns=2,
                      header_left="绿色三角洲", header_right=None,
                      page_layouts: Optional[dict] = None):
    """Write translated content as a printable dual-column HTML document."""
    min_chars = int(min_chars)
    max_chars = int(max_chars)
    columns = int(columns)
    if min_chars < 1 or max_chars < min_chars:
        raise ValueError("HTML 阅读页字数范围无效")
    if columns not in (1, 2):
        raise ValueError("HTML 正文分栏只支持 1 或 2 栏")

    ensure_output_parent(html_output)
    right_title = html.escape((header_right or _header_title(title)).strip())
    left_title = html.escape((header_left or "绿色三角洲").strip())
    safe_title = html.escape(title)
    safe_subtitle = html.escape(subtitle or "")
    reading_pages = paginate_translated_blocks(
        translated_pages,
        min_chars,
        max_chars,
        page_layouts=page_layouts,
        split_on_layout=True,
    )

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
        column-span: all;
        margin: 0.16in 0 0.26in;
        padding: 0.16in 0.22in;
        background: rgba(244, 225, 125, 0.62);
        border: 1px solid rgba(145, 126, 55, 0.42);
        box-shadow: 0 0.06in 0.12in rgba(0, 0, 0, 0.14);
        font-family: "Courier New", "VT323", monospace;
        break-inside: avoid;
        page-break-inside: avoid;
    }}
    .handout-card h3 {{
        margin: 0 0 0.08in;
        color: var(--ink);
        font-family: "Courier New", "VT323", monospace;
        font-size: 13pt;
        text-transform: uppercase;
    }}
    .handout-card p {{
        margin: 0 0 0.06in;
        text-indent: 0;
        font-size: 10.5pt;
        line-height: 1.5;
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
    .source-pages {{
        column-span: all;
        margin-top: 0.24in;
        color: var(--muted);
        font: 8.5pt "Courier New", monospace;
        text-align: right;
    }}
    .cover .content {{
        column-count: 1;
    }}
    .sheet.single .content {{
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
    .sheet.single .source-pages {{
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
        f'<header class="running-head"><span>// {left_title} //</span><span>// {right_title} //</span></header>',
        '<main class="content">',
        f'<h1 class="cover-title">{safe_title}</h1>',
        f'<p class="cover-subtitle">{safe_subtitle}</p>' if safe_subtitle else "",
        "</main>",
        "</section>",
    ]

    for page_idx, page in enumerate(reading_pages, 1):
        blocks = page["blocks"]
        layout = page.get("layout", "columns")
        source_pages = _format_page_ranges([b["source_page"] for b in blocks])
        chunks.extend([
            f'<section class="sheet {html.escape(layout)}">',
            f'<header class="running-head"><span>// {left_title} //</span><span>// {right_title} //</span></header>',
            '<main class="content">',
        ])
        for block in blocks:
            chunks.append(_html_block(block["text"]))
        chunks.append(f'<div class="source-pages">Reading Page {page_idx}; Source PDF Pages: {html.escape(source_pages)}</div>')
        chunks.extend(["</main>", "</section>"])

    chunks.extend(["</body>", "</html>", ""])
    with open(html_output, "w", encoding="utf-8") as f:
        f.write("\n".join(chunk for chunk in chunks if chunk != ""))
