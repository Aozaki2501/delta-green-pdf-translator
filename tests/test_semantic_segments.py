"""Synthetic regression tests for page-content schema v2 segmentation.

The fixture deliberately bypasses PDF extraction: the analyzer receives a
constructed region and constructed styled runs, so this test never opens a
user document.
"""

from types import MethodType

from core.semantic_analyzer import SemanticAnalyzer
from core.typeset_models import (
    BackgroundLayer,
    FontRole,
    PageType,
    PageStructure,
    SemanticRole,
    StyledTextRun,
    TextLineBBox,
    TextRegionBBox,
    TextSpanBBox,
)


def _line(
    *,
    text: str,
    bbox: list[float],
    font_size: float,
    bold: bool = False,
    color: str = "#231f20",
    font: str = "DG Noto Serif SC",
    line_index: int,
) -> tuple[TextLineBBox, StyledTextRun]:
    span = TextSpanBBox(
        bbox=bbox,
        text=text,
        font_size=font_size,
        bold=bold,
        italic=False,
        color=color,
        font=font,
        origin=[bbox[0], bbox[3] - 2.0],
    )
    line = TextLineBBox(
        bbox=bbox,
        text=text,
        font_size=font_size,
        bold=bold,
        italic=False,
        color=color,
        spans=[span],
    )
    run = StyledTextRun(
        text=text,
        font_size=font_size,
        bold=bold,
        italic=False,
        color=color,
        font=font,
        bbox=bbox,
        line_index=line_index,
        baseline=bbox[3] - 2.0,
    )
    return line, run


def _segmentation_fixture() -> tuple[PageStructure, dict[str, list[StyledTextRun]]]:
    lines_and_runs = [
        _line(
            text="DISPLAY TITLE",
            bbox=[60.0, 70.0, 480.0, 116.0],
            font_size=46.0,
            bold=True,
            line_index=0,
        ),
        _line(
            text="SECTION TITLE",
            bbox=[60.0, 132.0, 480.0, 162.0],
            font_size=30.0,
            bold=True,
            color="#dc2527",
            line_index=1,
        ),
        _line(
            text="第一段正文第一行",
            bbox=[84.0, 192.0, 480.0, 210.0],
            font_size=10.5,
            line_index=2,
        ),
        _line(
            text="第一段正文第二行",
            bbox=[60.0, 210.0, 480.0, 228.0],
            font_size=10.5,
            line_index=3,
        ),
        _line(
            text="第二段正文第一行",
            bbox=[84.0, 264.0, 480.0, 282.0],
            font_size=10.5,
            line_index=4,
        ),
        _line(
            text="第二段正文第二行",
            bbox=[60.0, 282.0, 480.0, 300.0],
            font_size=10.5,
            line_index=5,
        ),
    ]
    lines = [line for line, _ in lines_and_runs]
    runs = [run for _, run in lines_and_runs]
    region = TextRegionBBox(
        id="p0001_r0001",
        bbox=[60.0, 70.0, 480.0, 300.0],
        block_ids=[],
        lines=lines,
    )
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[region],
    )
    return structure, {region.id: runs}


def _analyzer_for_fixture(runs_by_region: dict[str, list[StyledTextRun]]) -> SemanticAnalyzer:
    """Create an analyzer without opening a private/user PDF."""
    analyzer = object.__new__(SemanticAnalyzer)
    analyzer.doc = [object()]

    def extract_styled_text(self, region, page=None):
        return runs_by_region[region.id]

    analyzer.extract_styled_text = MethodType(extract_styled_text, analyzer)
    return analyzer


def test_same_region_is_split_into_stable_display_and_paragraph_blocks():
    structure, runs_by_region = _segmentation_fixture()
    analyzer = _analyzer_for_fixture(runs_by_region)

    first = analyzer.analyze_page(structure)
    second = analyzer.analyze_page(structure)

    assert [block.id for block in first.blocks] == [
        "p0001_r0001_b0001",
        "p0001_r0001_b0002",
        "p0001_r0001_b0003",
        "p0001_r0001_b0004",
    ]
    assert [block.id for block in second.blocks] == [block.id for block in first.blocks]
    assert [block.paragraph_id for block in second.blocks] == [
        block.paragraph_id for block in first.blocks
    ]

    display, section, paragraph_one, paragraph_two = first.blocks
    assert display.role == SemanticRole.TITLE
    assert display.font_role == FontRole.DISPLAY
    assert display.source_text == "DISPLAY TITLE"
    assert display.bbox == [60.0, 70.0, 480.0, 116.0]
    assert display.layout_mode == "positioned"
    assert display.source_font == "DG Noto Serif SC"
    assert display.runs[0].font == "DG Noto Serif SC"
    assert display.runs[0].bbox == [60.0, 70.0, 480.0, 116.0]
    assert display.runs[0].line_index == 0
    assert display.runs[0].baseline == 114.0

    assert section.role == SemanticRole.SUBTITLE
    assert section.font_role == FontRole.SECTION
    assert section.source_text == "SECTION TITLE"
    assert section.bbox == [60.0, 132.0, 480.0, 162.0]
    assert section.layout_mode == "paragraph"

    assert paragraph_one.role == SemanticRole.BODY_COLUMN
    assert paragraph_one.font_role == FontRole.BODY
    assert paragraph_one.source_text == "第一段正文第一行\n第一段正文第二行"
    assert paragraph_one.bbox == [60.0, 192.0, 480.0, 228.0]
    assert paragraph_one.first_line_indent_pt == 24.0
    assert paragraph_one.line_height_pt == 18.0
    assert len(paragraph_one.line_ids) == 2
    assert paragraph_one.source_font == "DG Noto Serif SC"

    assert paragraph_two.role == SemanticRole.BODY_COLUMN
    assert paragraph_two.font_role == FontRole.BODY
    assert paragraph_two.source_text == "第二段正文第一行\n第二段正文第二行"
    assert paragraph_two.bbox == [60.0, 264.0, 480.0, 300.0]
    assert paragraph_two.first_line_indent_pt == 24.0
    assert paragraph_two.line_height_pt == 18.0
    assert len(paragraph_two.line_ids) == 2

    assert [block.order for block in first.blocks] == [0, 1, 2, 3]
    assert all(hasattr(block, "column_id") for block in first.blocks)
    assert all(block.paragraph_id for block in first.blocks)
    assert [block.line_ids for block in first.blocks] == [
        block.line_ids for block in second.blocks
    ]


def test_two_substantial_side_by_side_regions_form_columns():
    left_line, left_run = _line(
        text="Left column body",
        bbox=[48.0, 90.0, 284.0, 450.0],
        font_size=10.0,
        line_index=0,
    )
    right_line, right_run = _line(
        text="Right column body",
        bbox=[328.0, 90.0, 564.0, 450.0],
        font_size=10.0,
        line_index=0,
    )
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox("left", [48.0, 90.0, 284.0, 450.0], [], lines=[left_line]),
            TextRegionBBox("right", [328.0, 90.0, 564.0, 450.0], [], lines=[right_line]),
        ],
    )
    analyzer = _analyzer_for_fixture({"left": [left_run], "right": [right_run]})

    page = analyzer.analyze_page(structure)

    assert page.page_type == PageType.COLUMNS
    assert [column.side for column in page.columns] == ["left", "right"]
    assert [len(column.block_ids) for column in page.columns] == [1, 1]


def test_running_header_is_translatable():
    header_line, header_run = _line(
        text="DELTA GREEN",
        bbox=[72.0, 27.0, 142.0, 50.0],
        font_size=14.0,
        line_index=0,
    )
    body_line, body_run = _line(
        text="Body text",
        bbox=[72.0, 100.0, 540.0, 140.0],
        font_size=10.0,
        line_index=0,
    )
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox("header", [72.0, 27.0, 142.0, 50.0], [], lines=[header_line]),
            TextRegionBBox("body", [72.0, 100.0, 540.0, 140.0], [], lines=[body_line]),
        ],
    )
    analyzer = _analyzer_for_fixture({"header": [header_run], "body": [body_run]})

    page = analyzer.analyze_page(structure)
    header = next(block for block in page.blocks if block.role == SemanticRole.HEADER)

    assert header.font_role == FontRole.RUNNING_HEADER
    assert header.translatable is True


def test_dead_letter_orange_heading_keeps_accent_role():
    heading_line, heading_run = _line(
        text="Prospectus and Rumors",
        bbox=[72.0, 100.0, 240.0, 126.0],
        font_size=15.0,
        color="#eb4f24",
        line_index=0,
    )
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox("heading", [72.0, 100.0, 240.0, 126.0], [], lines=[heading_line]),
        ],
    )
    analyzer = _analyzer_for_fixture({"heading": [heading_run]})

    page = analyzer.analyze_page(structure)

    assert page.blocks[0].font_role == FontRole.SECTION
    assert page.blocks[0].role == SemanticRole.SUBTITLE


def test_timeline_dates_are_split_into_stable_heading_blocks():
    specs = [
        _line(
            text="JANUARY 2",
            bbox=[96.0, 170.0, 180.0, 184.0],
            font_size=9.0,
            bold=True,
            line_index=0,
        ),
        _line(
            text="First event body",
            bbox=[104.0, 188.0, 300.0, 202.0],
            font_size=9.0,
            line_index=1,
        ),
        _line(
            text="SEPTEMBER 4 (Friday)",
            bbox=[96.0, 220.0, 260.0, 234.0],
            font_size=9.0,
            bold=True,
            line_index=2,
        ),
        _line(
            text="Second event body",
            bbox=[104.0, 238.0, 300.0, 252.0],
            font_size=9.0,
            line_index=3,
        ),
    ]
    lines = [line for line, _ in specs]
    runs = [run for _, run in specs]
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox("timeline", [96.0, 170.0, 300.0, 252.0], [], lines=lines),
        ],
    )
    analyzer = _analyzer_for_fixture({"timeline": runs})

    page = analyzer.analyze_page(structure)

    assert [block.source_text for block in page.blocks] == [
        "JANUARY 2",
        "First event body",
        "SEPTEMBER 4 (Friday)",
        "Second event body",
    ]
    assert [block.font_role for block in page.blocks] == [
        FontRole.SUBSECTION,
        FontRole.BODY,
        FontRole.SUBSECTION,
        FontRole.BODY,
    ]


def test_hanging_indent_block_splits_on_outdented_lines_only():
    """Monster stat blocks hang their continuation lines to the right.

    Geometry mirrors page 4 of the real New Age artifact: paragraph starts sit at
    x0=45.7 and wrapped lines at x0=54.4. Applying the usual "indented line starts
    a paragraph" rule here would make every wrapped line its own block, which is
    what forced the page into line-by-line translation.
    """
    rows = [
        ("ETERNAL: Ghroth could, theoretically, be destroyed", 45.7, 401.9),
        ("enough force could shatter the thing's flesh into", 54.4, 416.9),
        ("require is not within humanity's grasp. Even if", 54.4, 431.9),
        ("CELESTIAL PIPING: Ghroth obeys the vibrations", 45.7, 446.9),
        ("atmosphere, that call manifests to human ears as", 54.4, 461.9),
        ("technology to re-create that control signal.", 54.4, 476.9),
    ]
    specs = [
        _line(
            text=text,
            bbox=[x0, y0, 540.0, y0 + 11.7],
            font_size=9.0,
            line_index=index,
        )
        for index, (text, x0, y0) in enumerate(rows)
    ]
    lines = [line for line, _ in specs]
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox("stats", [45.7, 401.9, 540.0, 488.6], [], lines=lines),
        ],
    )
    analyzer = _analyzer_for_fixture({"stats": [run for _, run in specs]})

    page = analyzer.analyze_page(structure)

    assert [block.source_text for block in page.blocks] == [
        "ETERNAL: Ghroth could, theoretically, be destroyed\n"
        "enough force could shatter the thing's flesh into\n"
        "require is not within humanity's grasp. Even if",
        "CELESTIAL PIPING: Ghroth obeys the vibrations\n"
        "atmosphere, that call manifests to human ears as\n"
        "technology to re-create that control signal.",
    ]
