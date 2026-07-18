"""Regression tests for segment-aware typeset HTML output."""

from core.typeset_models import (
    BackgroundLayer,
    ContentBlock,
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
    TextRegionBBox,
)
from exporters.typeset_html import TypesetHTMLRebuilder


def _segment(block_id: str, role: SemanticRole, font_role: FontRole, text: str, bbox: list[float]):
    return ContentBlock(
        id=block_id,
        region_id="p0001_r0001",
        role=role,
        runs=[
            StyledTextRun(
                text=text,
                font_size={
                    FontRole.DISPLAY: 46.0,
                    FontRole.SECTION: 30.0,
                    FontRole.BODY: 10.5,
                }[font_role],
                bold=font_role != FontRole.BODY,
                italic=False,
                color="#231f20",
                font="DG Noto Serif SC",
                bbox=bbox,
                line_index=0,
                baseline=bbox[3] - 2.0,
            )
        ],
        source_text=text,
        translated_text=text,
        translatable=True,
        bbox=bbox,
        line_ids=[f"{block_id}_l0001"],
        paragraph_id=f"{block_id}_p0001",
        font_role=font_role,
        source_font="DG Noto Serif SC",
        column_id="p0001_col_single",
        order=int(block_id[-4:]),
        layout_mode="positioned" if font_role == FontRole.DISPLAY else "paragraph",
        first_line_indent_pt=0.0 if font_role != FontRole.BODY else 21.0,
        line_height_pt=46.0 if font_role == FontRole.DISPLAY else 30.0 if font_role == FontRole.SECTION else 18.0,
    )


def _html_fixture() -> tuple[PageStructureDocument, PageContentDocument]:
    region = TextRegionBBox(
        id="p0001_r0001",
        bbox=[60.0, 70.0, 480.0, 340.0],
        block_ids=[
            "p0001_r0001_b0000",
            "p0001_r0001_b0001",
            "p0001_r0001_b0002",
            "p0001_r0001_b0003",
        ],
    )
    structure = PageStructureDocument(
        schema_version=PAGE_STRUCTURE_SCHEMA_VERSION,
        source_pdf="synthetic-segments.pdf",
        page_count=1,
        pages=[
            PageStructure(
                page_index=0,
                width=612.0,
                height=792.0,
                background=BackgroundLayer(),
                images=[],
                decorations=[],
                text_regions=[region],
            )
        ],
    )
    blocks = [
        _segment("p0001_r0001_b0000", SemanticRole.TITLE, FontRole.DISPLAY, "DISPLAY TITLE", [60.0, 70.0, 480.0, 116.0]),
        _segment("p0001_r0001_b0001", SemanticRole.SUBTITLE, FontRole.SECTION, "SECTION TITLE", [60.0, 132.0, 480.0, 162.0]),
        _segment("p0001_r0001_b0002", SemanticRole.BODY_COLUMN, FontRole.BODY, "第一段正文。", [60.0, 192.0, 480.0, 228.0]),
        _segment("p0001_r0001_b0003", SemanticRole.BODY_COLUMN, FontRole.BODY, "第二段正文。", [60.0, 264.0, 480.0, 300.0]),
    ]
    content = PageContentDocument(
        schema_version=PAGE_CONTENT_SCHEMA_VERSION,
        source_pdf="synthetic-segments.pdf",
        page_count=1,
        pages=[PageContent(0, PageType.SINGLE, [], blocks)],
    )
    return structure, content


def test_segment_roles_font_faces_and_paragraphs_are_emitted():
    structure, content = _html_fixture()
    output = TypesetHTMLRebuilder().rebuild_document(structure, content)

    assert "@font-face" in output
    assert "assets/typeset_fonts" in output
    for role in ("display", "section", "body"):
        assert f"font-role-{role}" in output
    assert output.count("<p ") >= 2
    for block_id in (
        "p0001_r0001_b0000",
        "p0001_r0001_b0001",
        "p0001_r0001_b0002",
        "p0001_r0001_b0003",
    ):
        assert output.count(f'data-block-id="{block_id}"') == 1
    assert "第一段正文。" in output
    assert "第二段正文。" in output


def test_fit_script_reports_overflow_without_silent_font_shrinking():
    script = TypesetHTMLRebuilder()._build_fit_script()

    assert "typesetCollectLayoutIssues" in script
    assert "typesetElementOverflows" in script
    assert "item.style.fontSize = size + 'px'" not in script
    assert "size - 0.5" not in script
