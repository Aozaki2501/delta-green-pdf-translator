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
                            )
                        ],
                        source_text="Hello world",
                        translated_text=None,
                        translatable=True,
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
    assert cfg.font_family == "FandolSong"
    assert "FandolSong-Regular" in cfg.fallback_fonts
    assert "Source Han Serif CN" in cfg.fallback_fonts
    assert "SimSun" in cfg.fallback_fonts
    assert "serif" in cfg.fallback_fonts
    assert cfg.heading_font_family == "FZZJ-MSMLJW"
    assert "SimHei" in cfg.heading_fallback_fonts
    assert cfg.body_font_size_pt == 10.9
    assert cfg.min_body_font_size_pt == 8.0
    assert cfg.line_height == 1.6
    assert cfg.column_gap_pt == 30.0
    assert cfg.text_indent == "2em"
    assert cfg.subtitle_color == "#ed1c24"
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
    assert PAGE_STRUCTURE_SCHEMA_VERSION == 1
    assert PAGE_CONTENT_SCHEMA_VERSION == 1


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
