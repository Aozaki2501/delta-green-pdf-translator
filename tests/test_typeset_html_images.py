from core.typeset_models import (
    BackgroundLayer,
    ColumnInfo,
    ContentBlock,
    ImageElement,
    PageContent,
    PageStructure,
    PageType,
    SemanticRole,
    StyledTextRun,
    TextLineBBox,
    TextRegionBBox,
    TextSpanBBox,
)
from exporters.typeset_html import TypesetHTMLRebuilder


def test_transformed_image_uses_pdf_matrix():
    rebuilder = TypesetHTMLRebuilder()
    html = rebuilder.render_image_layer([
        ImageElement(
            id="p0001_img0001",
            bbox=[0.0, 0.0, 100.0, 100.0],
            image_path="assets/typeset_images/p0001_img0001.png",
            width_px=200,
            height_px=100,
            transform=[100.0, 20.0, -10.0, 80.0, 5.0, 7.0],
        )
    ])

    assert "transform-origin:0 0" in html
    assert "matrix(" in html
    assert 'data-image-id="p0001_img0001"' in html


def test_rotated_text_region_uses_source_angle():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox(
                id="p0001_r0001",
                bbox=[100.0, 120.0, 300.0, 160.0],
                block_ids=["p0001_t0001"],
                angle=-4.0,
            )
        ],
    )
    content = PageContent(
        page_index=0,
        page_type=PageType.MIXED,
        columns=[],
        blocks=[
            ContentBlock(
                id="p0001_r0001_b0001",
                region_id="p0001_r0001",
                role=SemanticRole.BODY_COLUMN,
                runs=[StyledTextRun("Hello", 10.9, False, False, "#000000")],
                source_text="Hello",
                translated_text="你好",
                translatable=True,
            )
        ],
    )

    html = rebuilder.render_text_layer(content, structure)

    assert "rotate(-4.000deg)" in html
    assert 'data-region-id="p0001_r0001"' in html


def test_chinese_text_uses_source_column_flows():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox(id="p0001_r0001", bbox=[36.0, 80.0, 270.0, 240.0], block_ids=["p0001_t0001"]),
            TextRegionBBox(id="p0001_r0002", bbox=[306.0, 80.0, 540.0, 240.0], block_ids=["p0001_t0002"]),
        ],
    )
    content = PageContent(
        page_index=0,
        page_type=PageType.COLUMNS,
        columns=[
            ColumnInfo(side="left", bbox=[36.0, 80.0, 270.0, 240.0], block_ids=["p0001_r0001_b0001"]),
            ColumnInfo(side="right", bbox=[306.0, 80.0, 540.0, 240.0], block_ids=["p0001_r0002_b0001"]),
        ],
        blocks=[
            ContentBlock(
                id="p0001_r0001_b0001",
                region_id="p0001_r0001",
                role=SemanticRole.BODY_COLUMN,
                runs=[StyledTextRun("Left", 10.9, False, False, "#000000")],
                source_text="Left",
                translated_text="左栏正文",
                translatable=True,
            ),
            ContentBlock(
                id="p0001_r0002_b0001",
                region_id="p0001_r0002",
                role=SemanticRole.BODY_COLUMN,
                runs=[StyledTextRun("Right", 10.9, False, False, "#000000")],
                source_text="Right",
                translated_text="右栏正文",
                translatable=True,
            ),
        ],
    )

    html = rebuilder.render_text_layer(content, structure)

    assert 'class="typeset-region-flow"' in html
    assert 'data-column="left"' in html
    assert 'data-column="right"' in html
    assert "typeset-reflow-columns" not in html


def test_chinese_text_uses_source_line_tracks_when_available():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox(
                id="p0001_r0001",
                bbox=[36.0, 80.0, 270.0, 140.0],
                block_ids=["p0001_t0001"],
                lines=[
                    TextLineBBox([36.0, 80.0, 270.0, 93.0], "Line one", 10.9, False, False, "#000000"),
                    TextLineBBox([72.0, 98.0, 270.0, 111.0], "Indented around image", 10.9, False, False, "#000000"),
                    TextLineBBox([36.0, 116.0, 270.0, 129.0], "Line three", 10.9, False, False, "#000000"),
                ],
            ),
            TextRegionBBox(
                id="p0001_r0002",
                bbox=[306.0, 80.0, 540.0, 140.0],
                block_ids=["p0001_t0002"],
                lines=[
                    TextLineBBox([306.0, 80.0, 540.0, 93.0], "Right one", 10.9, False, False, "#000000"),
                    TextLineBBox([306.0, 98.0, 540.0, 111.0], "Right two", 10.9, False, False, "#000000"),
                    TextLineBBox([306.0, 116.0, 540.0, 129.0], "Right three", 10.9, False, False, "#000000"),
                ],
            ),
        ],
    )
    content = PageContent(
        page_index=0,
        page_type=PageType.COLUMNS,
        columns=[
            ColumnInfo(side="left", bbox=[36.0, 80.0, 270.0, 140.0], block_ids=["p0001_r0001_b0001"]),
            ColumnInfo(side="right", bbox=[306.0, 80.0, 540.0, 140.0], block_ids=["p0001_r0002_b0001"]),
        ],
        blocks=[
            ContentBlock(
                id="p0001_r0001_b0001",
                region_id="p0001_r0001",
                role=SemanticRole.BODY_COLUMN,
                runs=[StyledTextRun("Left", 10.9, False, False, "#000000")],
                source_text="Left",
                translated_text="左栏正文会按原始行宽排布",
                translatable=True,
            ),
            ContentBlock(
                id="p0001_r0002_b0001",
                region_id="p0001_r0002",
                role=SemanticRole.BODY_COLUMN,
                runs=[StyledTextRun("Right", 10.9, False, False, "#000000")],
                source_text="Right",
                translated_text="右栏正文",
                translatable=True,
            ),
        ],
    )

    html = rebuilder.render_text_layer(content, structure)

    assert 'class="typeset-line-track-flow"' in html
    assert 'class="typeset-line-slot"' in html
    assert "left:96.000px;top:130.667px" in html


def test_fixed_source_text_renders_span_geometry():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox(
                id="p0001_r0001",
                bbox=[36.0, 24.0, 200.0, 40.0],
                block_ids=["p0001_t0001"],
                lines=[
                    TextLineBBox(
                        bbox=[36.0, 24.0, 200.0, 40.0],
                        text="// Delta Green //",
                        font_size=8.0,
                        bold=False,
                        italic=True,
                        color="#000000",
                        spans=[
                            TextSpanBBox(
                                bbox=[36.0, 24.0, 100.0, 40.0],
                                text="// Delta",
                                font_size=8.0,
                                bold=False,
                                italic=True,
                                color="#000000",
                            )
                        ],
                    )
                ],
            )
        ],
    )
    content = PageContent(
        page_index=0,
        page_type=PageType.MIXED,
        columns=[],
        blocks=[
            ContentBlock(
                id="p0001_r0001_b0001",
                region_id="p0001_r0001",
                role=SemanticRole.HEADER,
                runs=[StyledTextRun("// Delta Green //", 8.0, False, True, "#000000")],
                source_text="// Delta Green //",
                translated_text=None,
                translatable=False,
            )
        ],
    )

    html = rebuilder._render_source_positioned_block(content.blocks[0], structure, structure.text_regions[0].bbox)

    assert 'class="typeset-source-span"' in html
    assert "font-style:italic" in html
    assert "// Delta" in html
