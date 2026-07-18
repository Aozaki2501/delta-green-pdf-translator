import pytest

from core.typeset_models import (
    BackgroundLayer,
    ContentBlock,
    DecorationElement,
    FontRole,
    ImageElement,
    PageContent,
    PageStructure,
    PageType,
    SemanticRole,
    StyledTextRun,
    TextRegionBBox,
)
from exporters.typeset_html import TypesetHTMLRebuilder
from exporters.typeset_pdf import TypesetPDFExporter


def test_long_translated_body_over_image_is_upright_without_mask():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[
            ImageElement(
                id="p0001_img0001",
                bbox=[80.0, 100.0, 560.0, 340.0],
                image_path="assets/typeset_images/card.png",
                width_px=960,
                height_px=480,
            )
        ],
        decorations=[],
        text_regions=[
            TextRegionBBox(
                id="p0001_r0001",
                bbox=[90.0, 110.0, 550.0, 330.0],
                block_ids=["t1"],
                angle=-4.75,
            )
        ],
    )
    block = ContentBlock(
        id="p0001_r0001_b0001",
        region_id="p0001_r0001",
        role=SemanticRole.BODY_COLUMN,
        runs=[StyledTextRun("Long body", 10.9, False, False, "#000000")],
        source_text="Long body",
        translated_text="\u4e2d" * 90,
        translatable=True,
    )

    html = rebuilder._render_positioned_single_block(
        block,
        structure,
        structure.text_regions[0].bbox,
    )

    assert "rotate(-4.750deg)" not in html
    assert "background:#f4eedc" not in html


def test_long_translated_heading_is_upright_and_respects_source_display_size():
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
                bbox=[120.0, 200.0, 380.0, 250.0],
                block_ids=["t1"],
                angle=-4.75,
            )
        ],
    )
    block = ContentBlock(
        id="p0001_r0001_b0001",
        region_id="p0001_r0001",
        role=SemanticRole.TITLE,
        runs=[StyledTextRun("WHEN FIREPOWER FAILS", 24.0, False, False, "#000000")],
        source_text="WHEN FIREPOWER FAILS",
        translated_text="\u5f53\u706b\u529b\u5931\u6548\u65f6\u4e00\u4e2a\u6d1b\u592b\u514b\u62c9\u592b\u7279\u5f0f\u6050\u6016\u7684\u89d2\u8272\u626e\u6f14\u6e38\u620f",
        translatable=True,
    )

    html = rebuilder._render_positioned_single_block(
        block,
        structure,
        structure.text_regions[0].bbox,
    )

    assert "rotate(-4.750deg)" not in html
    assert "font-size:32.000px" in html
    assert "white-space:nowrap" not in html


def test_large_source_font_does_not_promote_a_body_segment():
    rebuilder = TypesetHTMLRebuilder()
    block = ContentBlock(
        id="p0001_r0001_b0001",
        region_id="p0001_r0001",
        role=SemanticRole.BODY_COLUMN,
        runs=[StyledTextRun("WHEN FIREPOWER FAILS", 24.0, False, False, "#000000")],
        source_text="WHEN FIREPOWER FAILS",
        translated_text="\u5f53\u706b\u529b\u5931\u6548\u65f6\u4e00\u4e00\u6d1b\u592b\u514b\u62c9\u592b\u7279\u5f0f\u6050\u6016\u7684\u89d2\u8272\u626e\u6f14\u6e38\u620f",
        translatable=True,
    )

    html = rebuilder._render_block(block)

    assert "font-role-body" in html
    assert "white-space:nowrap" not in html


def test_large_flow_area_does_not_use_foreground_mask():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[
            ImageElement(
                id="p0001_img0001",
                bbox=[100.0, 100.0, 500.0, 500.0],
                image_path="assets/typeset_images/photo.png",
                width_px=800,
                height_px=800,
            )
        ],
        decorations=[],
        text_regions=[],
    )

    assert rebuilder._flow_mask_style(structure, [80.0, 80.0, 540.0, 560.0]) == ""
    assert rebuilder._flow_mask_style(structure, [100.0, 100.0, 180.0, 170.0]) == "background:#f4eedc;"


def test_fit_script_exposes_layout_issue_collector():
    script = TypesetHTMLRebuilder()._build_fit_script()

    assert "function typesetCollectLayoutIssues()" in script
    assert "typesetElementOverflows" in script


def test_dense_grid_page_keeps_boxes_and_uses_translated_text():
    decorations = [
        DecorationElement(
            id=f"line-{index}",
            element_type="line",
            bbox=[20.0, 40.0 + index, 180.0, 40.0 + index],
            stroke_color=None,
            fill_color=None,
            stroke_width=0.5,
        )
        for index in range(80)
    ]
    structure = PageStructure(
        page_index=0,
        width=240.0,
        height=320.0,
        background=BackgroundLayer(),
        images=[],
        decorations=decorations,
        text_regions=[
            TextRegionBBox(
                id="p0001_r0001",
                bbox=[40.0, 60.0, 200.0, 100.0],
                block_ids=["t1"],
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
                runs=[StyledTextRun("Original sheet text", 9.0, False, False, "#000000")],
                source_text="Original sheet text",
                translated_text="角色表译文",
                translatable=True,
            )
        ],
    )

    html = TypesetHTMLRebuilder().rebuild_page(structure, content)

    assert 'data-template="single_source_flow"' in html
    assert "角色表译文" in html
    assert "Original sheet text" not in html
    assert 'data-region-id="p0001_r0001"' in html


def test_dense_grid_page_omits_extracted_image_layer():
    decorations = [
        DecorationElement(
            id=f"line-{index}",
            element_type="line",
            bbox=[20.0, 40.0 + index, 180.0, 40.0 + index],
            stroke_color="#000000",
            fill_color=None,
            stroke_width=0.5,
        )
        for index in range(80)
    ]
    structure = PageStructure(
        page_index=0,
        width=240.0,
        height=320.0,
        background=BackgroundLayer(),
        images=[
            ImageElement(
                id="p0001_img0001",
                bbox=[0.0, 0.0, 240.0, 320.0],
                image_path="assets/typeset_images/page.png",
                width_px=480,
                height_px=640,
            )
        ],
        decorations=decorations,
        text_regions=[
            TextRegionBBox(
                id="p0001_r0001",
                bbox=[40.0, 60.0, 200.0, 100.0],
                block_ids=["t1"],
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
                runs=[StyledTextRun("Original sheet text", 9.0, False, False, "#000000")],
                source_text="Original sheet text",
                translated_text="角色表译文",
                translatable=True,
            )
        ],
    )

    html = TypesetHTMLRebuilder().rebuild_page(structure, content)

    assert 'data-image-id="p0001_img0001"' not in html
    assert "角色表译文" in html


def test_pdf_exporter_raises_on_layout_issues():
    exporter = TypesetPDFExporter()

    with pytest.raises(RuntimeError, match="typeset layout overflow"):
        exporter._raise_for_layout_issues([
            {"page": "2", "kind": "typeset-positioned-block", "id": "p0002_r0001"}
        ])


def test_art_page_renders_translated_running_headers_and_page_number():
    rebuilder = TypesetHTMLRebuilder()
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox("left-header", [72.0, 27.0, 142.0, 50.0], []),
            TextRegionBBox("right-header", [508.0, 27.0, 578.0, 50.0], []),
            TextRegionBBox("footer", [564.0, 746.0, 571.0, 761.0], []),
        ],
    )
    content = PageContent(
        page_index=0,
        page_type=PageType.ART,
        columns=[],
        blocks=[
            ContentBlock(
                id="left-header-block",
                region_id="left-header",
                role=SemanticRole.HEADER,
                runs=[StyledTextRun("DELTA GREEN", 14.0, False, False, "#000000")],
                source_text="DELTA GREEN",
                translated_text="绿色三角洲",
                translatable=True,
                font_role=FontRole.RUNNING_HEADER,
            ),
            ContentBlock(
                id="right-header-block",
                region_id="right-header",
                role=SemanticRole.HEADER,
                runs=[StyledTextRun("Dead Letter", 14.0, False, False, "#000000")],
                source_text="Dead Letter",
                translated_text="死信",
                translatable=True,
                font_role=FontRole.RUNNING_HEADER,
            ),
            ContentBlock(
                id="footer-block",
                region_id="footer",
                role=SemanticRole.FOOTER,
                runs=[StyledTextRun("11", 10.0, False, False, "#000000")],
                source_text="11",
                translated_text=None,
                translatable=False,
                font_role=FontRole.FOOTER,
            ),
        ],
    )

    html = rebuilder.rebuild_page(structure, content)

    assert "绿色三角洲" in html
    assert "死信" in html
    assert "// 绿色三角洲 //" in html
    assert "// 死信 //" in html
    assert "source-font-display-condensed" in html
    assert "font-size:14.667px" in html
    assert "justify-content:flex-start" in html
    assert "justify-content:flex-end" in html
    assert "text-align:left" in html
    assert "text-align:right" in html
    assert "align-items:flex-end" in html
    assert ">11<" in html
    assert html.count('data-block-id="left-header-block"') == 1
    assert html.count('data-block-id="right-header-block"') == 1
