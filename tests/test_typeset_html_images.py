from core.typeset_models import (
    BackgroundLayer,
    ColumnInfo,
    ContentBlock,
    DecorationElement,
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


def test_format_text_keeps_soft_newlines_soft():
    rebuilder = TypesetHTMLRebuilder()

    html = rebuilder._format_text("第一行\n第二行\n\n第三段")

    assert "第一行\n第二行" in html
    assert "第一行<br>第二行" not in html
    assert "第二行<br><br>第三段" in html


def test_timeline_text_breaks_at_timestamps():
    rebuilder = TypesetHTMLRebuilder()
    block = ContentBlock(
        id="p0001_r0001_b0001",
        region_id="p0001_r0001",
        role=SemanticRole.BODY_COLUMN,
        runs=[StyledTextRun("Timeline", 10.0, False, False, "#000000")],
        source_text="02:03 First. 03:07 Second. 04:09 Third. 07:36 Fourth.",
        translated_text="02:03 第一。03:07 第二。04:09 第三。07:36 第四。",
        translatable=True,
    )

    html = rebuilder._render_body_block(block, block.translated_text, 10.0)

    assert "typeset-timeline-text" in html
    assert "02:03 第一。<br>03:07 第二。" in html


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


def test_chinese_page_keeps_main_title_positioned():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[
            ImageElement(
                id="p0001_img0001",
                bbox=[0.0, 238.0, 320.0, 249.0],
                image_path="assets/typeset_images/p0001_img0001.png",
                width_px=640,
                height_px=22,
            )
        ],
        decorations=[],
        text_regions=[
            TextRegionBBox(id="p0001_r0001", bbox=[200.0, 220.0, 310.0, 245.0], block_ids=["p0001_t0001"]),
            TextRegionBBox(id="p0001_r0002", bbox=[70.0, 260.0, 310.0, 680.0], block_ids=["p0001_t0002"]),
            TextRegionBBox(id="p0001_r0003", bbox=[330.0, 120.0, 560.0, 680.0], block_ids=["p0001_t0003"]),
        ],
    )
    content = PageContent(
        page_index=0,
        page_type=PageType.COLUMNS,
        columns=[
            ColumnInfo(side="left", bbox=[70.0, 260.0, 310.0, 680.0], block_ids=["p0001_r0002_b0001"]),
            ColumnInfo(side="right", bbox=[330.0, 120.0, 560.0, 680.0], block_ids=["p0001_r0003_b0001"]),
        ],
        blocks=[
            ContentBlock(
                id="p0001_r0001_b0001",
                region_id="p0001_r0001",
                role=SemanticRole.TITLE,
                runs=[StyledTextRun("Introduction", 18.0, False, False, "#000000")],
                source_text="Introduction",
                translated_text="\u5f15\u8a00",
                translatable=True,
            ),
            ContentBlock(
                id="p0001_r0002_b0001",
                region_id="p0001_r0002",
                role=SemanticRole.BODY_COLUMN,
                runs=[StyledTextRun("Left body", 10.0, False, False, "#000000")],
                source_text="Left body",
                translated_text="\u5de6\u680f\u6b63\u6587",
                translatable=True,
            ),
            ContentBlock(
                id="p0001_r0003_b0001",
                region_id="p0001_r0003",
                role=SemanticRole.BODY_COLUMN,
                runs=[StyledTextRun("Right body", 10.0, False, False, "#000000")],
                source_text="Right body",
                translated_text="\u53f3\u680f\u6b63\u6587",
                translatable=True,
            ),
        ],
    )

    html = rebuilder.render_text_layer(content, structure)

    assert 'data-region-id="p0001_r0001"' in html
    assert 'data-column="left"' in html
    assert 'data-column="right"' in html
    assert html.index('data-region-id="p0001_r0001"') > html.index('data-column="right"')
    assert "background:#f4eedc;" not in html
    assert '<h2 class="typeset-reflow-title">\u5f15\u8a00</h2>' not in html


def test_overwide_source_column_keeps_blocks_separate():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox(id="p0001_r0001", bbox=[80.0, 110.0, 560.0, 190.0], block_ids=["p0001_t0001"]),
            TextRegionBBox(id="p0001_r0002", bbox=[340.0, 230.0, 560.0, 520.0], block_ids=["p0001_t0002"]),
        ],
    )
    content = PageContent(
        page_index=0,
        page_type=PageType.COLUMNS,
        columns=[
            ColumnInfo(side="right", bbox=[80.0, 100.0, 570.0, 540.0], block_ids=[
                "p0001_r0001_b0001",
                "p0001_r0002_b0001",
            ]),
            ColumnInfo(side="left", bbox=[70.0, 230.0, 300.0, 520.0], block_ids=[]),
        ],
        blocks=[
            ContentBlock(
                id="p0001_r0001_b0001",
                region_id="p0001_r0001",
                role=SemanticRole.BODY_COLUMN,
                runs=[StyledTextRun("Credits", 10.0, False, True, "#000000")],
                source_text="Credits",
                translated_text="\u7248\u6743\u8bf4\u660e",
                translatable=True,
            ),
            ContentBlock(
                id="p0001_r0002_b0001",
                region_id="p0001_r0002",
                role=SemanticRole.BODY_COLUMN,
                runs=[StyledTextRun("Right body", 10.0, False, False, "#000000")],
                source_text="Right body",
                translated_text="\u53f3\u680f\u6b63\u6587",
                translatable=True,
            ),
        ],
    )

    html = rebuilder.render_text_layer(content, structure)

    assert html.count('data-column="right"') == 2
    assert "width:640.000px" in html
    assert "width:293.333px" in html


def test_chinese_text_uses_source_line_tracks_when_available():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[
            ImageElement(
                id="p0001_img0001",
                bbox=[72.0, 96.0, 180.0, 150.0],
                image_path="assets/typeset_images/p0001_img0001.png",
                width_px=200,
                height_px=100,
            )
        ],
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


def test_chinese_text_uses_natural_column_flow_without_foreground_images():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[
            ImageElement(
                id="p0001_img0001",
                bbox=[0.0, 0.0, 612.0, 792.0],
                image_path="assets/typeset_images/p0001_img0001.png",
                width_px=1224,
                height_px=1584,
            )
        ],
        decorations=[],
        text_regions=[
            TextRegionBBox(
                id="p0001_r0001",
                bbox=[36.0, 80.0, 270.0, 140.0],
                block_ids=["p0001_t0001"],
                lines=[
                    TextLineBBox([36.0, 80.0, 270.0, 93.0], "Line one", 10.9, False, False, "#000000"),
                    TextLineBBox([36.0, 98.0, 270.0, 111.0], "Line two", 10.9, False, False, "#000000"),
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
                translated_text="左栏正文应该自然重排，不再硬塞进英文原始行轨道。",
                translatable=True,
            ),
            ContentBlock(
                id="p0001_r0002_b0001",
                region_id="p0001_r0002",
                role=SemanticRole.BODY_COLUMN,
                runs=[StyledTextRun("Right", 10.9, False, False, "#000000")],
                source_text="Right",
                translated_text="右栏正文也应该自然重排。",
                translatable=True,
            ),
        ],
    )

    html = rebuilder.render_text_layer(content, structure)

    assert 'class="typeset-region-flow"' in html
    assert 'class="typeset-line-track-flow"' not in html


def test_source_region_flow_titles_have_spacing():
    rebuilder = TypesetHTMLRebuilder()

    css = rebuilder._build_global_css(8.5, 11.0)

    assert ".typeset-region-flow .typeset-reflow-title" in css
    assert "margin: 13.333px 0 13.333px 0" in css


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


def test_positioned_translated_title_preserves_light_source_color():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[
            ImageElement(
                id="p0001_img0001",
                bbox=[290.0, 450.0, 510.0, 500.0],
                image_path="assets/typeset_images/p0001_img0001.png",
                width_px=440,
                height_px=100,
            )
        ],
        decorations=[],
        text_regions=[
            TextRegionBBox(
                id="p0001_r0001",
                bbox=[300.0, 460.0, 500.0, 486.0],
                block_ids=["p0001_t0001"],
                lines=[
                    TextLineBBox(
                        [300.0, 460.0, 500.0, 486.0],
                        "If They Miss Indian Rocks",
                        15.0,
                        True,
                        False,
                        "#ffffff",
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
                role=SemanticRole.TITLE,
                runs=[
                    StyledTextRun(
                        "If They Miss Indian Rocks",
                        15.0,
                        True,
                        False,
                        "#ffffff",
                    )
                ],
                source_text="If They Miss Indian Rocks",
                translated_text="如果错失印第安岩",
                translatable=True,
            )
        ],
    )

    html = rebuilder._render_source_positioned_block(
        content.blocks[0],
        structure,
        structure.text_regions[0].bbox,
    )

    assert "color:#ffffff" in html
    assert "background:#f4eedc" not in html
    assert "如果错失印第安岩" in html


def test_positioned_title_uses_source_bold_weight():
    rebuilder = TypesetHTMLRebuilder()
    normal = ContentBlock(
        id="p0001_r0001_b0001",
        region_id="p0001_r0001",
        role=SemanticRole.TITLE,
        runs=[StyledTextRun("Introduction", 18.0, False, False, "#000000")],
        source_text="Introduction",
        translated_text="引言",
        translatable=True,
    )
    bold = ContentBlock(
        id="p0001_r0002_b0001",
        region_id="p0001_r0002",
        role=SemanticRole.TITLE,
        runs=[StyledTextRun("If They Miss Indian Rocks", 15.0, True, False, "#ffffff")],
        source_text="If They Miss Indian Rocks",
        translated_text="如果他们错过了印第安岩",
        translatable=True,
    )

    assert "font-weight:400" in rebuilder._render_block(normal)
    assert "font-weight:700" in rebuilder._render_block(bold)


def test_positioned_title_does_not_use_foreground_mask():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[
            ImageElement(
                id="p0001_img0001",
                bbox=[100.0, 100.0, 360.0, 140.0],
                image_path="assets/typeset_images/rule.png",
                width_px=520,
                height_px=80,
            )
        ],
        decorations=[],
        text_regions=[
            TextRegionBBox(id="p0001_r0001", bbox=[120.0, 105.0, 300.0, 135.0], block_ids=["t1"]),
        ],
    )
    block = ContentBlock(
        id="p0001_r0001_b0001",
        region_id="p0001_r0001",
        role=SemanticRole.TITLE,
        runs=[StyledTextRun("Personal Reactions", 18.0, True, False, "#000000")],
        source_text="Personal Reactions",
        translated_text="个人反应",
        translatable=True,
    )

    html = rebuilder._render_source_positioned_block(
        block,
        structure,
        structure.text_regions[0].bbox,
    )

    assert "background:#f4eedc" not in html
    assert "个人反应" in html


def test_missing_translatable_text_does_not_render_source_english():
    rebuilder = TypesetHTMLRebuilder()
    block = ContentBlock(
        id="p0001_r0001_b0001",
        region_id="p0001_r0001",
        role=SemanticRole.BODY_COLUMN,
        runs=[StyledTextRun("Untranslated English sentence", 10.9, False, False, "#000000")],
        source_text="Untranslated English sentence",
        translated_text=None,
        translatable=True,
    )

    assert rebuilder._render_block(block) == ""


def test_mixed_light_source_colors_prefer_readable_light_text():
    rebuilder = TypesetHTMLRebuilder()
    block = ContentBlock(
        id="p0001_r0001_b0001",
        region_id="p0001_r0001",
        role=SemanticRole.BODY_COLUMN,
        runs=[
            StyledTextRun("Dark duplicate", 9.0, False, False, "#141314"),
            StyledTextRun("Light original", 9.0, False, False, "#ffffff"),
            StyledTextRun("Light original", 9.0, False, False, "#ffffff"),
        ],
        source_text="Light original",
        translated_text="浅色文字",
        translatable=True,
    )

    assert rebuilder._block_text_color(block) == "#ffffff"


def test_rebuild_splits_full_page_images_under_decorations():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[
            ImageElement(
                id="p0001_img0001",
                bbox=[0.0, 0.0, 612.0, 792.0],
                image_path="assets/typeset_images/page.png",
                width_px=1224,
                height_px=1584,
            ),
            ImageElement(
                id="p0001_img0002",
                bbox=[72.0, 600.0, 180.0, 680.0],
                image_path="assets/typeset_images/logo.png",
                width_px=216,
                height_px=160,
            ),
        ],
        decorations=[],
        text_regions=[],
    )

    html = rebuilder.render_image_layer(structure.images, structure)

    assert 'class="typeset-page-image-layer"' in html
    assert 'class="typeset-image-layer"' in html
    assert html.index("p0001_img0001") < html.index("p0001_img0002")


def test_invalid_image_bbox_is_not_rendered():
    rebuilder = TypesetHTMLRebuilder()
    html = rebuilder.render_image_layer([
        ImageElement(
            id="bad",
            bbox=[620.0, 100.0, 612.0, 120.0],
            image_path="bad.png",
            width_px=10,
            height_px=10,
        )
    ])

    assert "bad.png" not in html


def test_art_page_keeps_source_visual_without_text_overlay():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox(id="p0001_r0001", bbox=[200.0, 200.0, 400.0, 230.0], block_ids=["t1"]),
        ],
    )
    content = PageContent(
        page_index=0,
        page_type=PageType.ART,
        columns=[],
        blocks=[
            ContentBlock(
                id="p0001_r0001_b0001",
                region_id="p0001_r0001",
                role=SemanticRole.TITLE,
                runs=[StyledTextRun("MERIDIAN", 30.0, True, False, "#ffffff")],
                source_text="MERIDIAN",
                translated_text="子午线",
                translatable=True,
            )
        ],
    )

    html = rebuilder.render_text_layer(content, structure)

    assert "子午线" not in html


def test_first_art_page_renders_translated_cover_title_and_module_label():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox(id="title", bbox=[210.0, 172.0, 410.0, 212.0], block_ids=["title-block"]),
            TextRegionBBox(id="module", bbox=[115.0, 740.0, 508.0, 762.0], block_ids=["module-block"]),
        ],
    )
    content = PageContent(
        page_index=0,
        page_type=PageType.ART,
        columns=[],
        blocks=[
            ContentBlock(
                id="title-block",
                region_id="title",
                role=SemanticRole.BODY_COLUMN,
                runs=[StyledTextRun("THE NEW AGE", 32.0, False, False, "#ffffff")],
                source_text="THE NEW AGE",
                translated_text="《新时代》",
                translatable=True,
            ),
            ContentBlock(
                id="module-block",
                region_id="module",
                role=SemanticRole.BODY_COLUMN,
                runs=[StyledTextRun("A Scenario for Delta Green", 16.0, False, False, "#ffffff")],
                source_text="A Scenario for Delta Green",
                translated_text="《绿色三角洲：角色扮演游戏》模组",
                translatable=True,
            ),
        ],
    )

    html = rebuilder.render_text_layer(content, structure)

    assert ">新时代</div>" in html
    assert "《绿色三角洲：角色扮演游戏》模组" in html
    assert "font-size:40.000px" in html


def test_table_block_uses_source_line_slots():
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
                bbox=[36.0, 100.0, 540.0, 120.0],
                block_ids=["t1"],
                lines=[
                    TextLineBBox([40.0, 102.0, 60.0, 114.0], "1", 9.0, False, False, "#000000"),
                    TextLineBBox([78.0, 102.0, 160.0, 114.0], "Fallen trees", 9.0, False, False, "#000000"),
                    TextLineBBox([170.0, 102.0, 300.0, 114.0], "-10%", 9.0, False, False, "#000000"),
                ],
            )
        ],
    )
    block = ContentBlock(
        id="p0001_r0001_b0001",
        region_id="p0001_r0001",
        role=SemanticRole.TABLE,
        runs=[StyledTextRun("1Fallen trees-10%", 9.0, False, False, "#000000")],
        source_text="1Fallen trees-10%",
        translated_text="1倒下的树木下次检定-10%",
        translatable=True,
    )

    html = rebuilder._render_table_line_track_block(block, structure)

    assert "typeset-table-line-flow" in html
    assert html.count('class="typeset-line-slot"') == 3
    assert "1倒下的树木下次检定-10%" in html


def test_dense_line_grid_page_keeps_rotated_blocks_positioned():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[
            DecorationElement(
                id=f"d{i}",
                element_type="line",
                bbox=[40.0 + i * 2.0, 90.0, 40.0 + i * 2.0, 720.0],
                stroke_color="#000000",
                fill_color=None,
                stroke_width=1.0,
            )
            for i in range(80)
        ],
        text_regions=[
            TextRegionBBox(
                id="p0001_r0001",
                bbox=[106.0, 537.0, 375.0, 747.0],
                block_ids=["t1"],
                angle=-90.0,
                lines=[
                    TextLineBBox([106.0, 537.0, 125.0, 747.0], "You should be ascending", 9.0, False, False, "#000000", -90.0),
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
                role=SemanticRole.BODY_COLUMN,
                runs=[StyledTextRun("You should be ascending", 9.0, False, False, "#000000")],
                source_text="You should be ascending",
                translated_text="你本应步步高升，登上调查局的顶峰。",
                translatable=True,
            )
        ],
    )

    html = rebuilder.render_text_layer(content, structure)

    assert "typeset-rotated-flow" not in html
    assert "typeset-positioned-block" in html
    assert "rotate(-90.000deg)" in html
    assert "You should be ascending" in html
    assert "你本应步步高升" not in html
