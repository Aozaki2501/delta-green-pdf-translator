"""Smoke test for core/typeset_models.py - validates task 1.1 requirements."""

import json

from core.typeset_models import (
    PAGE_CONTENT_SCHEMA_VERSION,
    PAGE_STRUCTURE_SCHEMA_VERSION,
    BackgroundLayer,
    ColumnInfo,
    ContentBlock,
    DecorationElement,
    ImageElement,
    PageContent,
    PageContentDocument,
    PageStructure,
    PageStructureDocument,
    PageType,
    FontRole,
    SemanticRole,
    StyledTextRun,
    TextRegionBBox,
    TextLineBBox,
    TextSpanBBox,
    TypesetConfig,
    TypesetResult,
)


def test_page_structure_document_roundtrip():
    doc = PageStructureDocument(
        schema_version=PAGE_STRUCTURE_SCHEMA_VERSION,
        source_pdf="test.pdf",
        source_sha256="abc123",
        page_count=1,
        pages=[
            PageStructure(
                page_index=0,
                width=612.0,
                height=792.0,
                background=BackgroundLayer(color="#1a1a2e", gradient=None),
                images=[
                    ImageElement(
                        id="p0001_img0001",
                        bbox=[10.0, 20.0, 300.0, 400.0],
                        image_path="assets/typeset_images/p0001_img0001.png",
                        width_px=580,
                        height_px=760,
                        transform=[100.0, 0.0, 0.0, 80.0, 10.0, 20.0],
                    )
                ],
                decorations=[
                    DecorationElement(
                        id="p0001_dec0001",
                        element_type="line",
                        bbox=[0.0, 50.0, 612.0, 50.0],
                        stroke_color="#333333",
                        fill_color=None,
                        stroke_width=1.0,
                        points=None,
                    )
                ],
                text_regions=[
                    TextRegionBBox(
                        id="p0001_r0001",
                        bbox=[50.0, 100.0, 300.0, 700.0],
                        block_ids=["b001", "b002"],
                        angle=-4.0,
                        lines=[
                            TextLineBBox(
                                bbox=[50.0, 100.0, 260.0, 114.0],
                                text="Slanted heading",
                                font_size=14.9,
                                bold=True,
                                italic=True,
                                color="#ed1c24",
                                angle=-4.0,
                                spans=[
                                    TextSpanBBox(
                                        bbox=[50.0, 100.0, 160.0, 114.0],
                                        text="Slanted",
                                        font_size=14.9,
                                        bold=True,
                                        italic=True,
                                        color="#ed1c24",
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    json_str = doc.to_json()
    restored = PageStructureDocument.from_json(json_str)
    assert restored == doc


def test_page_content_document_roundtrip():
    doc = PageContentDocument(
        schema_version=PAGE_CONTENT_SCHEMA_VERSION,
        source_pdf="test.pdf",
        source_sha256="content123",
        page_count=1,
        pages=[
            PageContent(
                page_index=0,
                page_type=PageType.COLUMNS,
                columns=[
                    ColumnInfo(
                        side="left",
                        bbox=[50.0, 100.0, 290.0, 700.0],
                        block_ids=["p0001_r0001_b0001"],
                    )
                ],
                blocks=[
                    ContentBlock(
                        id="p0001_r0001_b0001",
                        region_id="p0001_r0001",
                        role=SemanticRole.BODY_COLUMN,
                        runs=[
                            StyledTextRun(
                                text="Hello world",
                                font_size=11.0,
                                bold=False,
                                italic=False,
                                color="#000000",
                                font="Source Han Serif CN",
                                bbox=[50.0, 100.0, 122.0, 114.0],
                                line_index=2,
                                baseline=112.5,
                            )
                        ],
                        source_text="Hello world",
                        translated_text=None,
                        translatable=True,
                        bbox=[50.0, 100.0, 300.0, 130.0],
                        line_ids=["p0001_r0001_l0003"],
                        paragraph_id="p0001_r0001_p0001",
                        font_role=FontRole.BODY,
                        source_font="Source Han Serif CN",
                        column_id="p0001_col_left",
                        order=7,
                        layout_mode="paragraph",
                        first_line_indent_pt=20.0,
                        line_height_pt=18.0,
                    )
                ],
            )
        ],
    )
    json_str = doc.to_json()
    restored = PageContentDocument.from_json(json_str)
    assert restored == doc


def test_schema_version_validation():
    doc = PageStructureDocument(
        schema_version=PAGE_STRUCTURE_SCHEMA_VERSION,
        source_pdf="test.pdf",
        page_count=0,
        pages=[],
    )
    data = json.loads(doc.to_json())
    data["schema_version"] = 99
    try:
        PageStructureDocument.from_json(json.dumps(data))
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "99" in str(e)


def test_page_content_schema_version_validation():
    doc = PageContentDocument(
        schema_version=PAGE_CONTENT_SCHEMA_VERSION,
        source_pdf="test.pdf",
        page_count=0,
        pages=[],
    )
    data = json.loads(doc.to_json())
    data["schema_version"] = 99
    try:
        PageContentDocument.from_json(json.dumps(data))
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "99" in str(e)


def test_typeset_config_defaults():
    cfg = TypesetConfig()
    assert cfg.font_family == "DG Fandol Song"
    assert "Noto Serif SC" in cfg.fallback_fonts
    assert "Source Han Serif CN" in cfg.fallback_fonts
    assert "SimSun" in cfg.fallback_fonts
    assert "serif" in cfg.fallback_fonts
    assert cfg.heading_font_family == "DG Lanting Kanhei"
    assert "SimHei" in cfg.heading_fallback_fonts
    assert cfg.body_font_size_pt == 10.9
    assert cfg.min_body_font_size_pt == 10.5
    assert cfg.line_height == 17.0 / 10.9
    assert cfg.column_gap_pt == 31.0
    assert cfg.text_indent == "2em"
    assert cfg.subtitle_color == "#dc2527"
    assert cfg.layout_hints_path is None


def test_json_format_utf8_indented():
    doc = PageStructureDocument(
        schema_version=PAGE_STRUCTURE_SCHEMA_VERSION,
        source_pdf="测试.pdf",
        page_count=0,
        pages=[],
    )
    json_str = doc.to_json()
    # Human-readable: has newlines and indentation
    assert "\n" in json_str
    assert "  " in json_str
    # UTF-8: Chinese characters are NOT escaped
    assert "测试.pdf" in json_str
    assert "\\u" not in json_str


def test_schema_version_constants():
    assert PAGE_STRUCTURE_SCHEMA_VERSION == 2
    assert PAGE_CONTENT_SCHEMA_VERSION == 2


def test_font_role_enum_is_stable():
    assert {role.value for role in FontRole} == {
        "body",
        "display",
        "section",
        "subsection",
        "running_header",
        "footer",
        "table",
        "callout",
        "meta",
    }


def test_page_content_v2_fields_are_serialized():
    block = ContentBlock(
        id="r_b0001",
        region_id="r",
        role=SemanticRole.BODY_COLUMN,
        runs=[
            StyledTextRun(
                "段落",
                10.5,
                False,
                False,
                "#111111",
                font="DG Noto Serif SC",
                bbox=[1.0, 2.0, 3.0, 4.0],
                line_index=0,
                baseline=11.5,
            )
        ],
        source_text="段落",
        translated_text="Paragraph",
        translatable=True,
        bbox=[1.0, 2.0, 30.0, 20.0],
        line_ids=["r_l0001"],
        paragraph_id="r_p0001",
        font_role=FontRole.SECTION,
        source_font="DG Noto Serif SC",
        column_id="left",
        order=1,
        layout_mode="paragraph",
        first_line_indent_pt=21.0,
        line_height_pt=18.0,
    )
    page = PageContent(0, PageType.SINGLE, [], [block])
    doc = PageContentDocument(PAGE_CONTENT_SCHEMA_VERSION, "fixture.pdf", 1, [page])
    data = json.loads(doc.to_json())
    serialized = data["pages"][0]["blocks"][0]
    assert serialized["font_role"] == "section"
    assert serialized["line_ids"] == ["r_l0001"]
    assert serialized["paragraph_id"] == "r_p0001"
    assert serialized["runs"][0]["font"] == "DG Noto Serif SC"
    assert serialized["runs"][0]["bbox"] == [1.0, 2.0, 3.0, 4.0]
    assert serialized["runs"][0]["line_index"] == 0
    assert serialized["runs"][0]["baseline"] == 11.5


def test_semantic_role_enum():
    assert SemanticRole.BODY_COLUMN.value == "body_column"
    assert SemanticRole.TITLE.value == "title"
    assert SemanticRole.SUBTITLE.value == "subtitle"
    assert SemanticRole.HEADER.value == "header"
    assert SemanticRole.FOOTER.value == "footer"
    assert SemanticRole.FOOTNOTE.value == "footnote"
    assert SemanticRole.TABLE.value == "table"
    assert SemanticRole.LIST.value == "list"


def test_page_type_enum():
    assert PageType.COVER.value == "cover"
    assert PageType.ART.value == "art"
    assert PageType.COLUMNS.value == "columns"
    assert PageType.SINGLE.value == "single"
    assert PageType.MIXED.value == "mixed"


def test_typeset_result_fields():
    result = TypesetResult(
        pdf_path="out.pdf",
        html_path="out.html",
        page_structure_path="ps.json",
        page_content_path="pc.json",
        total_pages=10,
        translated_regions=50,
        failed_regions=2,
        export_errors=["page 3 timeout"],
    )
    assert result.pdf_path == "out.pdf"
    assert result.total_pages == 10
    assert result.failed_regions == 2
    assert len(result.export_errors) == 1
