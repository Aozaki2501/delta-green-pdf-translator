"""Behavior tests for structured table detection and HTML rendering.

These fixtures deliberately use only the public typeset models.  The semantic
test uses a blank, temporary PDF because ``SemanticAnalyzer`` needs a page
handle, but all geometry and text under test comes from the constructed
``PageStructure``.
"""

from __future__ import annotations

from dataclasses import replace
import re

import pymupdf

from core.semantic_analyzer import SemanticAnalyzer
from core.typeset_models import (
    BackgroundLayer,
    ContentBlock,
    DecorationElement,
    FontRole,
    PAGE_CONTENT_SCHEMA_VERSION,
    PAGE_STRUCTURE_SCHEMA_VERSION,
    PageContent,
    PageContentDocument,
    PageStructure,
    PageStructureDocument,
    PageType,
    SemanticRole,
    StyledTextRun,
    TextLineBBox,
    TextRegionBBox,
    TextSpanBBox,
)
from exporters.typeset_html import TypesetHTMLRebuilder


PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0
TABLE_X0 = 40.0
TABLE_X1 = 540.0
TABLE_COLUMNS = 7
CELL_WIDTH = (TABLE_X1 - TABLE_X0) / TABLE_COLUMNS


def _span(text: str, bbox: list[float], *, size: float = 9.0, bold: bool = False) -> TextSpanBBox:
    return TextSpanBBox(
        bbox=bbox,
        text=text,
        font_size=size,
        bold=bold,
        italic=False,
        color="#000000",
        font="DG Noto Serif SC",
        origin=[bbox[0], bbox[3]],
    )


def _table_line(row: list[str], y0: float, *, angle: float = 2.0) -> TextLineBBox:
    """Build one seven-column source line with authoritative cell geometry."""
    spans = [
        _span(
            text,
            [TABLE_X0 + index * CELL_WIDTH, y0,
             TABLE_X0 + (index + 1) * CELL_WIDTH, y0 + 12.0],
            bold=y0 == 120.0,
        )
        for index, text in enumerate(row)
    ]
    return TextLineBBox(
        bbox=[TABLE_X0, y0, TABLE_X1, y0 + 12.0],
        text="\t".join(row),
        font_size=9.0,
        bold=y0 == 120.0,
        italic=False,
        color="#000000",
        angle=angle,
        spans=spans,
    )


def _table_region_for_semantics() -> TextRegionBBox:
    lines = [
        _table_line([f"H{index}" for index in range(1, 8)], 120.0),
        _table_line([f"A{index}" for index in range(1, 8)], 134.0),
        _table_line([f"B{index}" for index in range(1, 8)], 148.0),
        _table_line([f"C{index}" for index in range(1, 8)], 162.0),
    ]
    return TextRegionBBox(
        id="p0001_r_table",
        bbox=[TABLE_X0, 116.0, TABLE_X1, 180.0],
        block_ids=["p0001_r_table"],
        angle=2.0,
        lines=lines,
    )


def _dense_grid() -> list[DecorationElement]:
    return [
        DecorationElement(
            id=f"p0001_grid_{index:03d}",
            element_type="line",
            bbox=[TABLE_X0 + index * 6.0, 100.0, TABLE_X0 + index * 6.0, 200.0],
            stroke_color="#000000",
            fill_color=None,
            stroke_width=1.0,
        )
        for index in range(80)
    ]


def _semantic_fixture() -> PageStructure:
    # The title is tilted by the same small amount as the table, but its
    # ordinary top-page position must not turn it into a running header.
    tilted_title = TextRegionBBox(
        id="p0001_r_title",
        bbox=[100.0, 20.0, 510.0, 48.0],
        block_ids=["p0001_r_title"],
        angle=2.0,
        lines=[
            TextLineBBox(
                bbox=[100.0, 20.0, 510.0, 48.0],
                text="倾斜章节标题",
                font_size=22.0,
                bold=True,
                italic=False,
                color="#000000",
                angle=2.0,
                spans=[_span("倾斜章节标题", [100.0, 20.0, 250.0, 48.0], size=22.0, bold=True)],
            )
        ],
    )
    ordinary_header = TextRegionBBox(
        id="p0001_r_header",
        bbox=[40.0, 52.0, 260.0, 62.0],
        block_ids=["p0001_r_header"],
        angle=0.0,
        lines=[
            TextLineBBox(
                bbox=[40.0, 52.0, 260.0, 62.0],
                text="DELTA GREEN",
                font_size=8.0,
                bold=False,
                italic=False,
                color="#000000",
                angle=0.0,
                spans=[_span("DELTA GREEN", [40.0, 52.0, 130.0, 62.0], size=8.0)],
            )
        ],
    )
    return PageStructure(
        page_index=0,
        width=PAGE_WIDTH,
        height=PAGE_HEIGHT,
        background=BackgroundLayer(),
        images=[],
        decorations=_dense_grid(),
        text_regions=[tilted_title, ordinary_header, _table_region_for_semantics()],
    )


def _blank_pdf(tmp_path) -> str:
    pdf_path = tmp_path / "structured-table-blank.pdf"
    document = pymupdf.open()
    document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    document.save(pdf_path)
    document.close()
    return str(pdf_path)


def test_rotated_table_grid_is_table_but_ordinary_header_stays_running_header(tmp_path):
    structure = _semantic_fixture()
    with SemanticAnalyzer(_blank_pdf(tmp_path), str(tmp_path / "out")) as analyzer:
        content = analyzer.analyze_page(structure)

    table_blocks = [block for block in content.blocks if block.role is SemanticRole.TABLE]
    assert table_blocks, "dense seven-column grid should produce TABLE blocks"
    assert all(block.font_role is FontRole.TABLE for block in table_blocks)
    assert all(block.translatable for block in table_blocks)
    assert max(len(block.runs) for block in table_blocks) >= TABLE_COLUMNS
    assert sum(len(block.line_ids) for block in table_blocks) >= 3

    title_blocks = [block for block in content.blocks if block.region_id == "p0001_r_title"]
    assert title_blocks
    assert all(block.font_role is not FontRole.RUNNING_HEADER for block in title_blocks)

    header_blocks = [block for block in content.blocks if block.region_id == "p0001_r_header"]
    assert len(header_blocks) == 1
    assert header_blocks[0].font_role is FontRole.RUNNING_HEADER


def _cell_block(
    block_id: str,
    row_id: str,
    text: str,
    translated: str,
    bbox: list[float],
    *,
    bold: bool = False,
) -> ContentBlock:
    return ContentBlock(
        id=block_id,
        region_id=row_id,
        role=SemanticRole.TABLE,
        runs=[StyledTextRun(
            text=text,
            font_size=9.0,
            bold=bold,
            italic=False,
            color="#000000",
            font="DG Noto Serif SC",
            bbox=bbox,
        )],
        source_text=text,
        translated_text=translated,
        translatable=True,
        bbox=bbox,
        line_ids=[],
        paragraph_id=f"{row_id}_p0001",
        font_role=FontRole.TABLE,
        source_font="DG Noto Serif SC",
        column_id=None,
        layout_mode="table",
        line_height_pt=12.0,
    )


def _table_row_region(row_id: str, y0: float, y1: float) -> TextRegionBBox:
    return TextRegionBBox(
        id=row_id,
        bbox=[TABLE_X0, y0, TABLE_X1, y1],
        block_ids=[],
        lines=[],
    )


def _html_table_fixture(include_body: bool = True) -> tuple[PageStructureDocument, PageContentDocument]:
    row_specs = [
        ("p0001_table_header", 120.0, 132.0, [f"H{index}" for index in range(1, 8)], [f"表头{index}" for index in range(1, 8)], True),
        ("p0001_table_row1", 136.0, 148.0, [f"A{index}" for index in range(1, 8)], [f"甲{index}" for index in range(1, 8)], False),
        ("p0001_table_row2", 152.0, 164.0, [f"B{index}" for index in range(1, 8)], [f"乙{index}" for index in range(1, 8)], False),
    ]
    regions: list[TextRegionBBox] = []
    blocks: list[ContentBlock] = []
    for row_id, y0, y1, source_cells, translated_cells, bold in row_specs:
        regions.append(_table_row_region(row_id, y0, y1))
        for index, (source, translated) in enumerate(zip(source_cells, translated_cells)):
            bbox = [
                TABLE_X0 + index * CELL_WIDTH,
                y0,
                TABLE_X0 + (index + 1) * CELL_WIDTH,
                y1,
            ]
            blocks.append(_cell_block(
                f"{row_id}_c{index + 1:02d}", row_id, source, translated, bbox, bold=bold,
            ))

    note_row = "p0001_table_note"
    regions.append(_table_row_region(note_row, 168.0, 186.0))
    note_bbox = [TABLE_X0, 168.0, TABLE_X1, 186.0]
    blocks.append(_cell_block(
        f"{note_row}_c01",
        note_row,
        "* Note: source note spans the table",
        "* 注：这一行横跨整张表",
        note_bbox,
    ))

    if include_body:
        body_id = "p0001_body"
        regions.append(_table_row_region(body_id, 220.0, 300.0))
        body_bbox = [40.0, 220.0, 540.0, 300.0]
        blocks.append(ContentBlock(
            id=f"{body_id}_b0001",
            region_id=body_id,
            role=SemanticRole.BODY_COLUMN,
            runs=[StyledTextRun(
                text="Body paragraph",
                font_size=10.5,
                bold=False,
                italic=False,
                color="#000000",
                font="DG Noto Serif SC",
                bbox=body_bbox,
            )],
            source_text="Body paragraph",
            translated_text="这是同页的普通正文，用于验证自然重排和十八点行高。",
            translatable=True,
            bbox=body_bbox,
            paragraph_id=f"{body_id}_p0001",
            font_role=FontRole.BODY,
            source_font="DG Noto Serif SC",
            layout_mode="paragraph",
            line_height_pt=18.0,
        ))

    structure = PageStructureDocument(
        schema_version=PAGE_STRUCTURE_SCHEMA_VERSION,
        source_pdf="structured-table.html-fixture.pdf",
        page_count=1,
        pages=[PageStructure(
            page_index=0,
            width=PAGE_WIDTH,
            height=PAGE_HEIGHT,
            background=BackgroundLayer(),
            images=[],
            decorations=[],
            text_regions=regions,
        )],
    )
    content = PageContentDocument(
        schema_version=PAGE_CONTENT_SCHEMA_VERSION,
        source_pdf="structured-table.html-fixture.pdf",
        page_count=1,
        pages=[PageContent(
            page_index=0,
            page_type=PageType.SINGLE,
            columns=[],
            blocks=blocks,
        )],
    )
    return structure, content


def test_table_blocks_render_as_semantic_html_table_without_positioned_cells():
    structure, content = _html_table_fixture(include_body=True)
    html = TypesetHTMLRebuilder().rebuild_document(structure, content)

    assert html.count("<table") == 1
    assert len(re.findall(r"<th(?:\s|>)", html)) == 7
    assert html.count("<tr") >= 4  # header, two data rows, and the note
    assert re.search(r"<td[^>]*colspan=[\"']7[\"']", html)
    assert "* 注：这一行横跨整张表" in html
    assert not re.search(
        r"<[a-z0-9]+[^>]*class=\"[^\"]*typeset-positioned-block",
        html,
    )


def test_table_cell_continuations_do_not_create_extra_columns():
    structure, content = _html_table_fixture(include_body=False)
    blocks = content.pages[0].blocks
    continued = next(block for block in blocks if block.id == "p0001_table_row1_c02")
    blocks.append(replace(
        continued,
        id="p0001_table_row1_c02_continued",
        source_text="continued",
        translated_text="续行内容",
        bbox=[continued.bbox[0], continued.bbox[1] + 4.0, continued.bbox[2], continued.bbox[3] + 4.0],
    ))

    html = TypesetHTMLRebuilder().rebuild_document(structure, content)

    assert len(re.findall(r"<th(?:\\s|>)", html)) == TABLE_COLUMNS
    assert "甲2续行内容" in html


def test_two_table_groups_on_one_page_render_as_two_tables():
    structure, content = _html_table_fixture(include_body=False)
    original_regions = list(structure.pages[0].text_regions)
    original_blocks = list(content.pages[0].blocks)
    title_region = TextRegionBBox(
        id="p0001_second_title",
        bbox=[40.0, 210.0, 360.0, 235.0],
        block_ids=[],
        lines=[],
    )
    title = ContentBlock(
        id="p0001_second_title_b0001",
        region_id=title_region.id,
        role=SemanticRole.TITLE,
        runs=[StyledTextRun(">> Second Table", 18.0, True, False, "#000000")],
        source_text=">> Second Table",
        translated_text=">> 第二张表",
        translatable=True,
        bbox=title_region.bbox,
        font_role=FontRole.DISPLAY,
    )
    duplicate_regions = [
        replace(
            region,
            id=f"{region.id}_second",
            bbox=[region.bbox[0], region.bbox[1] + 130.0, region.bbox[2], region.bbox[3] + 130.0],
        )
        for region in original_regions
    ]
    duplicate_blocks = [
        replace(
            block,
            id=f"{block.id}_second",
            region_id=f"{block.region_id}_second",
            bbox=[block.bbox[0], block.bbox[1] + 130.0, block.bbox[2], block.bbox[3] + 130.0],
        )
        for block in original_blocks
    ]
    structure.pages[0].text_regions[:] = [*original_regions, title_region, *duplicate_regions]
    content.pages[0].blocks[:] = [*original_blocks, title, *duplicate_blocks]

    html = TypesetHTMLRebuilder().rebuild_document(structure, content)

    assert html.count("<table") == 2


def test_non_table_body_keeps_reflow_and_fusion_style_line_height():
    structure, content = _html_table_fixture(include_body=True)
    html = TypesetHTMLRebuilder().rebuild_document(structure, content)

    assert "typeset-reflow-body" in html or "typeset-region-flow" in html
    # The stylesheet uses the 17pt / 10.9pt ratio measured from the
    # Chinese reference layout.
    body_rules = re.findall(
        r"(?:\.typeset-reflow-body|\.typeset-body-text)[^{]*\{(?P<body>.*?)\}",
        html,
        re.DOTALL,
    )
    assert body_rules
    assert any(
        re.search(r"line-height:\s*(?:1\.559|22\.667px|17pt)", rule)
        for rule in body_rules
    )


def test_positioned_display_respects_source_size_and_is_not_clipped():
    region_id = "p0001_display"
    bbox = [60.0, 100.0, 480.0, 132.0]
    structure = PageStructure(
        page_index=0,
        width=PAGE_WIDTH,
        height=PAGE_HEIGHT,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[TextRegionBBox(
            id=region_id,
            bbox=bbox,
            block_ids=[region_id],
            angle=0.0,
        )],
    )
    content = PageContent(
        page_index=0,
        page_type=PageType.SINGLE,
        columns=[],
        blocks=[ContentBlock(
            id=f"{region_id}_b0001",
            region_id=region_id,
            role=SemanticRole.TITLE,
            runs=[StyledTextRun(
                text="Small source display",
                font_size=18.0,
                bold=True,
                italic=False,
                color="#000000",
                font="DG Noto Serif SC",
                bbox=bbox,
            )],
            source_text="Small source display",
            translated_text="显示标题",
            translatable=True,
            bbox=bbox,
            font_role=FontRole.DISPLAY,
            source_font="DG Noto Serif SC",
            layout_mode="positioned",
        )],
    )
    html = TypesetHTMLRebuilder().rebuild_document(
        PageStructureDocument(PAGE_STRUCTURE_SCHEMA_VERSION, "display.pdf", 1, [structure]),
        PageContentDocument(PAGE_CONTENT_SCHEMA_VERSION, "display.pdf", 1, [content]),
    )
    display_style = re.search(
        r'<h[1-6][^>]*data-block-id="[^"]+"[^>]*style="[^\"]*font-size:([0-9.]+)px',
        html,
    )
    assert display_style
    assert float(display_style.group(1)) <= 18.0 * 96.0 / 72.0 + 0.01

    positioned_rule = re.search(
        r"\.typeset-positioned-block\s*\{(?P<body>.*?)\}", html, re.DOTALL,
    )
    assert positioned_rule
    assert "overflow:hidden" not in positioned_rule.group("body").replace(" ", "")


def test_html_body_prefers_registered_fandol_song_font():
    css = TypesetHTMLRebuilder()._build_global_css(8.5, 11.0)

    assert re.search(
        r"@font-face\s*\{[^}]*font-family:\s*[\"']DG Fandol Song[\"']",
        css,
        re.DOTALL,
    )
    body_rule = re.search(r"body\s*\{(?P<body>.*?)\}", css, re.DOTALL)
    assert body_rule
    assert re.search(r"font-family:\s*[\"']DG Fandol Song[\"']\s*,", body_rule.group("body"))
