"""
Word/DOCX exporter module.

Provides write_word_output and all Word-specific helper functions for
generating translated DOCX documents with proper layout, columns,
headers/footers, and card formatting.

Dependencies: python-docx (optional), exporters._shared
"""

import re
import os
from typing import Optional

from exporters._shared import (
    _is_plain_heading_line,
    _looks_like_stat_block,
    paginate_translated_blocks,
    _layout_uses_columns,
    _normalize_heading_markup,
    _normalize_marker_line,
)
from core.utils import ensure_output_parent

# ---------------------------------------------------------------------------
# Optional python-docx import
# ---------------------------------------------------------------------------

try:
    from docx import Document as DocxDocument
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.section import WD_SECTION
    from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False


# ---------------------------------------------------------------------------
# Word layout helpers
# ---------------------------------------------------------------------------

def set_section_columns(section, num=2, space_twips=720):
    """
    设置 Word 分栏。
    space_twips=720 约等于 0.5 英寸，可按需要调小到 360。
    """
    sectPr = section._sectPr
    cols = sectPr.xpath("./w:cols")
    if cols:
        cols = cols[0]
    else:
        cols = OxmlElement("w:cols")
        sectPr.append(cols)

    cols.set(qn("w:num"), str(num))
    cols.set(qn("w:space"), str(space_twips))


def set_cell_width(cell, width):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.first_child_found_in("w:tcW")
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(int(width.inches * 1440)))
    tc_w.set(qn("w:type"), "dxa")


def remove_table_borders(table):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = "w:" + edge
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), "nil")


def set_table_borders(table, color="B8B8B8", val="dashed", size="8"):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = "w:" + edge
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), val)
        element.set(qn("w:sz"), size)
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), color)


def set_section_page_layout(section, columns=1):
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)

    section.top_margin = Inches(0.82)
    section.bottom_margin = Inches(0.6)
    section.left_margin = Inches(0.55)
    section.right_margin = Inches(0.55)
    section.header_distance = Inches(0.22)
    section.footer_distance = Inches(0.25)

    set_section_columns(section, num=columns, space_twips=520)


def _columns_for_layout(layout: str, default_columns: int) -> int:
    return int(default_columns) if _layout_uses_columns(layout) else 1


def _add_word_field(paragraph, instruction: str):
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_end)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    run.font.size = Pt(9)


def _add_page_number(paragraph):
    _add_word_field(paragraph, "PAGE")


def _header_title(title: str) -> str:
    clean = re.sub(r"[_]+", " ", title).strip()
    if " - " in clean:
        clean = clean.split(" - ", 1)[1].strip()
    return clean[:32]


def clear_header_footer_part(part):
    element = part._element
    for child in list(element):
        element.remove(child)


def set_running_header_footer(doc, title: str, header_left: str = "绿色三角洲",
                              header_right: Optional[str] = None):
    right_title = header_right.strip() if header_right else _header_title(title)
    left_title = header_left.strip() if header_left else "绿色三角洲"
    for section in doc.sections:
        section.header.is_linked_to_previous = False
        section.footer.is_linked_to_previous = False

        clear_header_footer_part(section.header)

        table = section.header.add_table(rows=1, cols=2, width=Inches(7.4))
        table.autofit = False
        remove_table_borders(table)
        set_cell_width(table.cell(0, 0), Inches(3.2))
        set_cell_width(table.cell(0, 1), Inches(4.2))

        left_para = table.cell(0, 0).paragraphs[0]
        right_para = table.cell(0, 1).paragraphs[0]
        right_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        left_para.paragraph_format.space_before = Pt(0)
        left_para.paragraph_format.space_after = Pt(0)
        left_para.paragraph_format.line_spacing = 1.0
        run = left_para.add_run(f"// {left_title} //")
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        run.font.size = Pt(9)

        right_para.paragraph_format.space_before = Pt(0)
        right_para.paragraph_format.space_after = Pt(0)
        right_para.paragraph_format.line_spacing = 1.0
        run = right_para.add_run(f"// {right_title} //")
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        run.font.size = Pt(9)

        clear_header_footer_part(section.footer)
        footer_para = section.footer.add_paragraph()
        footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        footer_para.paragraph_format.space_before = Pt(0)
        footer_para.paragraph_format.space_after = Pt(0)
        _add_page_number(footer_para)


def set_document_base_layout(doc, columns=1, body_font_size=12.0, line_spacing=1.5,
                             h1_size=None, h2_size=None, h3_size=None, h4_size=None):
    set_section_page_layout(doc.sections[0], columns=columns)
    body_font_size = float(body_font_size)
    h1_size = float(h1_size) if h1_size else 20
    h2_size = float(h2_size) if h2_size else 18
    h3_size = float(h3_size) if h3_size else 16
    h4_size = float(h4_size) if h4_size else 16

    styles = doc.styles

    # 正文
    normal = styles["Normal"]
    normal.font.name = "宋体"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.font.size = Pt(body_font_size)
    normal.paragraph_format.first_line_indent = Pt(body_font_size * 2)
    normal.paragraph_format.line_spacing = line_spacing
    normal.paragraph_format.space_after = Pt(max(3, body_font_size / 2))
    # 一级标题
    h1 = styles["Heading 1"]
    h1.font.name = "黑体"
    h1._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    h1.font.size = Pt(h1_size)
    h1.font.bold = False
    h1.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(12)
    h1.paragraph_format.keep_with_next = True

    # 二级标题
    h2 = styles["Heading 2"]
    h2.font.name = "黑体"
    h2._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    h2.font.size = Pt(h2_size)
    h2.font.bold = True
    h2.font.color.rgb = RGBColor(0xD8, 0x00, 0x00)
    h2.paragraph_format.space_before = Pt(12)
    h2.paragraph_format.space_after = Pt(6)
    h2.paragraph_format.keep_with_next = True

    # 三级标题
    h3 = styles["Heading 3"]
    h3.font.name = "黑体"
    h3._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    h3.font.size = Pt(h3_size)
    h3.font.bold = True
    h3.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    h3.paragraph_format.space_before = Pt(10)
    h3.paragraph_format.space_after = Pt(5)
    h3.paragraph_format.keep_with_next = True

    # 四级标题
    h4 = styles["Heading 4"]
    h4.font.name = "黑体"
    h4._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    h4.font.size = Pt(h4_size)
    h4.font.bold = True
    h4.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    h4.paragraph_format.space_before = Pt(8)
    h4.paragraph_format.space_after = Pt(4)
    h4.paragraph_format.keep_with_next = True

    # 项目符号
    if "List Bullet" in styles:
        bullet = styles["List Bullet"]
        bullet.font.name = "宋体"
        bullet._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        bullet.font.size = Pt(body_font_size)
        bullet.paragraph_format.left_indent = Pt(22)
        bullet.paragraph_format.first_line_indent = Pt(-12)
        bullet.paragraph_format.line_spacing = line_spacing
        bullet.paragraph_format.space_after = Pt(4)


# ---------------------------------------------------------------------------
# Word content writing helpers
# ---------------------------------------------------------------------------

def _is_table_line(line: str) -> bool:
    """Check if a line is part of a Markdown table."""
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3


def _split_card_segments(text: str):
    """Split block text into segments: normal (dual-column), card (single-column),
    and table (single-column). This allows the Word renderer to switch column
    layout around cards and tables."""
    segments = []
    normal_lines = []
    card_lines = []
    stat_lines = []
    image_lines = []
    full_title_lines = []
    table_lines = []
    in_card = False
    in_stat = False
    in_image = False
    in_full_title = False

    def flush_normal():
        nonlocal normal_lines
        if any(line.strip() for line in normal_lines):
            segments.append(("normal", "\n".join(normal_lines).strip()))
        normal_lines = []

    def flush_card():
        nonlocal card_lines
        if any(line.strip() for line in card_lines):
            segments.append(("card", "\n".join(card_lines).strip()))
        card_lines = []

    def flush_stat():
        nonlocal stat_lines
        if any(line.strip() for line in stat_lines):
            segments.append(("stat", "\n".join(stat_lines).strip()))
        stat_lines = []

    def flush_image():
        nonlocal image_lines
        if any(line.strip() for line in image_lines):
            segments.append(("image", "\n".join(image_lines).strip()))
        image_lines = []

    def flush_full_title():
        nonlocal full_title_lines
        if any(line.strip() for line in full_title_lines):
            segments.append(("full_title", "\n".join(full_title_lines).strip()))
        full_title_lines = []

    def flush_table():
        nonlocal table_lines
        if table_lines:
            segments.append(("table", "\n".join(table_lines).strip()))
        table_lines = []

    for raw_line in text.splitlines():
        line = _normalize_marker_line(raw_line)
        if line == "[FULL_WIDTH_TITLE]":
            flush_normal()
            flush_table()
            flush_card()
            flush_stat()
            flush_image()
            in_full_title = True
            continue
        if line == "[/FULL_WIDTH_TITLE]":
            flush_full_title()
            in_full_title = False
            continue
        if line == "[CARD]":
            flush_normal()
            flush_table()
            in_card = True
            continue
        if line == "[/CARD]":
            flush_card()
            in_card = False
            continue
        if line == "[STAT_BLOCK]":
            flush_normal()
            flush_table()
            in_stat = True
            continue
        if line == "[/STAT_BLOCK]":
            flush_stat()
            in_stat = False
            continue
        if line == "[IMAGE]":
            flush_normal()
            flush_table()
            in_image = True
            continue
        if line == "[/IMAGE]":
            flush_image()
            in_image = False
            continue
        if in_card:
            card_lines.append(raw_line)
            continue
        if in_stat:
            stat_lines.append(raw_line)
            continue
        if in_image:
            image_lines.append(raw_line)
            continue
        if in_full_title:
            full_title_lines.append(raw_line)
            continue

        # Detect table lines
        if _is_table_line(line):
            if not table_lines:
                flush_normal()
            table_lines.append(raw_line)
        else:
            if table_lines:
                flush_table()
            normal_lines.append(raw_line)

    if in_full_title:
        flush_full_title()
    elif in_card:
        flush_card()
    elif in_stat:
        flush_stat()
    elif in_image:
        flush_image()
    else:
        flush_table()
        flush_normal()
    return segments


def _write_word_block(doc, text: str, layout: str = "columns"):
    plain_indent = layout == "columns"
    centered = layout in {"credits", "art"}

    def tune_paragraph(paragraph):
        if not plain_indent:
            paragraph.paragraph_format.first_line_indent = Pt(0)
        if centered:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for line in text.split("\n"):
        line = line.strip()
        if not line or line == "---" or line.startswith("<!--"):
            continue
        line = _normalize_heading_markup(line)
        line = _normalize_marker_line(line)

        clean_line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        clean_line = re.sub(r"\*(.+?)\*", r"\1", clean_line)

        if clean_line.startswith("#### "):
            p = doc.add_heading(clean_line[5:], level=4)
            p.paragraph_format.first_line_indent = Pt(0)
            tune_paragraph(p)
        elif clean_line.startswith("### "):
            p = doc.add_heading(clean_line[4:], level=3)
            p.paragraph_format.first_line_indent = Pt(0)
            tune_paragraph(p)
        elif clean_line.startswith("## "):
            p = doc.add_heading(clean_line[3:], level=2)
            p.paragraph_format.first_line_indent = Pt(0)
            tune_paragraph(p)
        elif clean_line.startswith("# "):
            p = doc.add_heading(clean_line[2:], level=1)
            p.paragraph_format.first_line_indent = Pt(0)
            tune_paragraph(p)
        elif clean_line.startswith(">"):
            card_text = clean_line.lstrip(">").strip()
            if not card_text:
                continue
            p = doc.add_paragraph(card_text)
            p.paragraph_format.left_indent = Pt(14)
            p.paragraph_format.right_indent = Pt(8)
            p.paragraph_format.first_line_indent = Pt(0)
            _set_paragraph_left_rule(p)
            _set_paragraph_shading(p)
            tune_paragraph(p)
        elif _is_plain_heading_line(clean_line):
            p = doc.add_heading(clean_line, level=2)
            p.paragraph_format.first_line_indent = Pt(0)
            tune_paragraph(p)
        elif clean_line.startswith("- ") or clean_line.startswith("\u2022 "):
            p = doc.add_paragraph(clean_line[2:], style="List Bullet")
            p.paragraph_format.first_line_indent = Pt(-8)
            tune_paragraph(p)
        else:
            p = doc.add_paragraph(clean_line)
            tune_paragraph(p)


def _write_word_table(doc, text: str):
    """Render a Markdown table as a Word table."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        # Not enough lines for a table, fall back to plain text
        for line in lines:
            doc.add_paragraph(line.strip("| "))
        return

    # Parse header
    header_cells = [cell.strip() for cell in lines[0].strip("|").split("|")]

    # Skip separator line (e.g. |---|---|---|)
    data_start = 1
    if len(lines) > 1 and re.fullmatch(r"\|[\s:|-]+\|", lines[1]):
        data_start = 2

    # Parse data rows
    data_rows = []
    for line in lines[data_start:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        data_rows.append(cells)

    col_count = len(header_cells)
    if col_count < 1:
        return

    # Create Word table
    table = doc.add_table(rows=1 + len(data_rows), cols=col_count)
    table.style = "Table Grid"

    # Write header
    for idx, cell_text in enumerate(header_cells):
        if idx < col_count:
            cell = table.rows[0].cells[idx]
            cell.text = cell_text
            # Bold header
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.first_line_indent = Pt(0)
                paragraph.paragraph_format.space_before = Pt(2)
                paragraph.paragraph_format.space_after = Pt(2)
                for run in paragraph.runs:
                    run.bold = True

    # Write data rows
    for row_idx, row_cells in enumerate(data_rows):
        for col_idx in range(col_count):
            cell_text = row_cells[col_idx] if col_idx < len(row_cells) else ""
            cell = table.rows[row_idx + 1].cells[col_idx]
            cell.text = cell_text
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.first_line_indent = Pt(0)
                paragraph.paragraph_format.space_before = Pt(2)
                paragraph.paragraph_format.space_after = Pt(2)

    # Add spacing after table
    doc.add_paragraph()


def _set_paragraph_left_rule(paragraph, color="B0891C"):
    p_pr = paragraph._p.get_or_add_pPr()
    borders = p_pr.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        p_pr.append(borders)
    left = borders.find(qn("w:left"))
    if left is None:
        left = OxmlElement("w:left")
        borders.append(left)
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "14")
    left.set(qn("w:space"), "6")
    left.set(qn("w:color"), color)


def _set_paragraph_shading(paragraph, fill="FFF7D6"):
    p_pr = paragraph._p.get_or_add_pPr()
    shading = p_pr.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        p_pr.append(shading)
    shading.set(qn("w:fill"), fill)


def _write_word_card(doc, text: str):
    for idx, line in enumerate(text.split("\n")):
        clean_line = line.strip()
        if not clean_line:
            continue
        clean_line = re.sub(r"^#{1,6}\s*", "", clean_line)
        clean_line = re.sub(r"\*\*(.+?)\*\*", r"\1", clean_line)
        clean_line = re.sub(r"\*(.+?)\*", r"\1", clean_line)
        p = doc.add_paragraph(clean_line)
        p.paragraph_format.left_indent = Pt(12)
        p.paragraph_format.right_indent = Pt(12)
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.space_before = Pt(6 if idx == 0 else 0)
        p.paragraph_format.space_after = Pt(3)
        _set_paragraph_left_rule(p)
        _set_paragraph_shading(p)
        for run in p.runs:
            run.font.name = "宋体"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
            run.font.size = Pt(10.5)
            if idx == 0:
                run.bold = True


def _write_word_stat_block(doc, text: str):
    if not _looks_like_stat_block(text):
        _write_word_card(doc, text)
        return
    for idx, line in enumerate(text.split("\n")):
        clean_line = line.strip()
        if not clean_line:
            continue
        clean_line = re.sub(r"\*\*(.+?)\*\*", r"\1", clean_line)
        clean_line = re.sub(r"\*(.+?)\*", r"\1", clean_line)
        p = doc.add_paragraph(clean_line)
        p.paragraph_format.left_indent = Pt(10)
        p.paragraph_format.right_indent = Pt(10)
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.space_before = Pt(5 if idx == 0 else 0)
        p.paragraph_format.space_after = Pt(3)
        for run in p.runs:
            run.font.name = "Courier New"
            run.font.size = Pt(9)
            if idx == 0:
                run.bold = True
        p_pr = p._p.get_or_add_pPr()
        borders = OxmlElement("w:pBdr")
        top = OxmlElement("w:top")
        top.set(qn("w:val"), "single")
        top.set(qn("w:sz"), "8")
        top.set(qn("w:space"), "2")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "8")
        bottom.set(qn("w:space"), "2")
        borders.append(top)
        borders.append(bottom)
        p_pr.append(borders)


def _write_word_image_placeholder(doc, text: str, image_path: str = ""):
    if image_path:
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"图片资源不存在：{image_path}")
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Pt(0)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(image_path, width=Inches(6.6))
        return
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_table_borders(table)
    row = table.rows[0]
    row.height = Inches(1.35)
    row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
    cell = row.cells[0]
    set_cell_width(cell, Inches(7.15))
    para = cell.paragraphs[0]
    para.paragraph_format.first_line_indent = Pt(0)
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.space_after = Pt(0)
    para.add_run(" ")
    doc.add_paragraph()


def _write_word_full_title(doc, text: str):
    lines = [
        re.sub(r"^\s*#{1,6}\s*", "", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]
    lines = [re.sub(r"\s+", " ", line) for line in lines if line]
    if not lines:
        return
    p = doc.add_heading(lines[0], level=1)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Pt(0)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(6 if len(lines) > 1 else 18)
    if len(lines) > 1:
        subtitle = doc.add_paragraph(" ".join(lines[1:]))
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
        subtitle.paragraph_format.first_line_indent = Pt(0)
        subtitle.paragraph_format.space_after = Pt(18)


def _with_missing_image_placeholders(translated_pages, source_pages_text=None):
    if not source_pages_text:
        return translated_pages
    patched = []
    placeholder = "[IMAGE]\nIllustration placeholder\n[/IMAGE]"
    for page_num, text in translated_pages:
        source_text = source_pages_text.get(page_num, "")
        missing_count = source_text.count("[IMAGE]") - str(text).count("[IMAGE]")
        if missing_count > 0:
            extra = "\n\n".join(placeholder for _ in range(missing_count))
            text = f"{text.rstrip()}\n\n{extra}"
        patched.append((page_num, text))
    return patched


# ---------------------------------------------------------------------------
# Main Word output function
# ---------------------------------------------------------------------------

def write_word_output(translated_pages, docx_output: str, title: str, subtitle: str = "中文翻译",
                      min_chars=1000, max_chars=1500, body_font_size=12.0,
                      line_spacing=1.5, columns=2, header_left="绿色三角洲",
                      header_right=None, hard_page_breaks=False,
                      source_pages_text=None, page_layouts=None,
                      image_assets: Optional[dict] = None):
    """Write translated Markdown-like page content to a Word document."""
    if not HAS_DOCX:
        raise RuntimeError("Word output requires python-docx")
    min_chars = int(min_chars)
    max_chars = int(max_chars)
    columns = int(columns)
    body_font_size = float(body_font_size)
    line_spacing = float(line_spacing)
    if min_chars < 1 or max_chars < min_chars:
        raise ValueError("Word 阅读页字数范围无效")
    if columns not in (1, 2):
        raise ValueError("Word 正文分栏只支持 1 或 2 栏")
    if not 6 <= body_font_size <= 24:
        raise ValueError("Word 正文字号超出支持范围")
    if not 0.8 <= line_spacing <= 3.0:
        raise ValueError("Word 行距超出支持范围")
    ensure_output_parent(docx_output)
    translated_pages = _with_missing_image_placeholders(translated_pages, source_pages_text)

    doc = DocxDocument()
    set_document_base_layout(doc, columns=1, body_font_size=body_font_size, line_spacing=line_spacing)

    title_para = doc.add_heading(title.upper(), level=1)
    title_para.alignment = WD_ALIGN_PARAGRAPH.LEFT

    if subtitle:
        subtitle_para = doc.add_paragraph(subtitle)
        subtitle_para.style = doc.styles["Normal"]
        subtitle_para.paragraph_format.first_line_indent = Pt(0)
        if subtitle_para.runs:
            subtitle_para.runs[0].font.color.rgb = RGBColor(0x2D, 0x73, 0xB9)
            subtitle_para.runs[0].font.bold = True
        doc.add_paragraph()

    body_section = doc.add_section(WD_SECTION.CONTINUOUS)
    set_section_page_layout(body_section, columns=columns)
    set_running_header_footer(doc, title, header_left=header_left, header_right=header_right)

    reading_pages = paginate_translated_blocks(
        translated_pages,
        min_chars,
        max_chars,
        page_layouts=page_layouts,
        split_on_layout=True,
    )
    current_page_columns = columns
    image_cursors = {}
    for page_idx, page in enumerate(reading_pages):
        blocks = page["blocks"]
        layout = page.get("layout", "columns")
        page_columns = _columns_for_layout(layout, columns)
        if hard_page_breaks and page_idx > 0:
            doc.add_page_break()
        if page_idx == 0:
            set_section_page_layout(body_section, columns=page_columns)
        elif page_columns != current_page_columns:
            body_section = doc.add_section(WD_SECTION.CONTINUOUS)
            set_section_page_layout(body_section, columns=page_columns)
        current_page_columns = page_columns
        for block in blocks:
            for kind, content in _split_card_segments(block["text"]):
                if kind == "card":
                    card_section = doc.add_section(WD_SECTION.CONTINUOUS)
                    set_section_page_layout(card_section, columns=1)
                    _write_word_card(doc, content)
                    body_section = doc.add_section(WD_SECTION.CONTINUOUS)
                    set_section_page_layout(body_section, columns=page_columns)
                elif kind == "stat":
                    stat_section = doc.add_section(WD_SECTION.CONTINUOUS)
                    set_section_page_layout(stat_section, columns=1)
                    _write_word_stat_block(doc, content)
                    body_section = doc.add_section(WD_SECTION.CONTINUOUS)
                    set_section_page_layout(body_section, columns=page_columns)
                elif kind == "image":
                    image_section = doc.add_section(WD_SECTION.CONTINUOUS)
                    set_section_page_layout(image_section, columns=1)
                    source_page = block.get("source_page")
                    image_paths = (image_assets or {}).get(source_page, [])
                    cursor = image_cursors.setdefault(source_page, 0)
                    image_path = image_paths[cursor] if cursor < len(image_paths) else ""
                    image_cursors[source_page] = cursor + 1
                    _write_word_image_placeholder(doc, content, image_path)
                    body_section = doc.add_section(WD_SECTION.CONTINUOUS)
                    set_section_page_layout(body_section, columns=page_columns)
                elif kind == "full_title":
                    doc.add_page_break()
                    title_section = doc.add_section(WD_SECTION.CONTINUOUS)
                    set_section_page_layout(title_section, columns=1)
                    _write_word_full_title(doc, content)
                    body_section = doc.add_section(WD_SECTION.CONTINUOUS)
                    set_section_page_layout(body_section, columns=page_columns)
                elif kind == "table":
                    table_section = doc.add_section(WD_SECTION.CONTINUOUS)
                    set_section_page_layout(table_section, columns=1)
                    _write_word_table(doc, content)
                    body_section = doc.add_section(WD_SECTION.CONTINUOUS)
                    set_section_page_layout(body_section, columns=page_columns)
                else:
                    _write_word_block(doc, content, layout=layout)

    doc.save(docx_output)
