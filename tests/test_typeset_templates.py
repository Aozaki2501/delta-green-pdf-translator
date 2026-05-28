from core.typeset_models import (
    BackgroundLayer,
    ColumnInfo,
    ContentBlock,
    PageContent,
    PageStructure,
    PageType,
    SemanticRole,
    StyledTextRun,
    TextLineBBox,
    TextRegionBBox,
)
from core.typeset_templates import select_typeset_template
from exporters.typeset_html import TypesetHTMLRebuilder


def test_selects_line_track_columns_template():
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox(
                id="r1",
                bbox=[36.0, 80.0, 270.0, 140.0],
                block_ids=["t1"],
                lines=[TextLineBBox([36.0, 80.0, 270.0, 93.0], "Line", 10.9, False, False, "#000000")],
            ),
            TextRegionBBox(
                id="r2",
                bbox=[306.0, 80.0, 540.0, 140.0],
                block_ids=["t2"],
                lines=[TextLineBBox([306.0, 80.0, 540.0, 93.0], "Line", 10.9, False, False, "#000000")],
            ),
        ],
    )
    content = PageContent(
        page_index=0,
        page_type=PageType.COLUMNS,
        columns=[
            ColumnInfo("left", [36.0, 80.0, 270.0, 140.0], ["r1_b0001"]),
            ColumnInfo("right", [306.0, 80.0, 540.0, 140.0], ["r2_b0001"]),
        ],
        blocks=[
            ContentBlock("r1_b0001", "r1", SemanticRole.BODY_COLUMN, [StyledTextRun("A", 10.9, False, False, "#000000")], "A", "甲", True),
            ContentBlock("r2_b0001", "r2", SemanticRole.BODY_COLUMN, [StyledTextRun("B", 10.9, False, False, "#000000")], "B", "乙", True),
        ],
    )

    template = select_typeset_template(content, structure)

    assert template.id == "line_track_columns"
    assert template.use_line_tracks is True

    html = TypesetHTMLRebuilder().rebuild_page(structure, content)
    assert 'data-template="line_track_columns"' in html
