from core.typeset_models import (
    BackgroundLayer,
    ContentBlock,
    DisplayListObject,
    PageContent,
    PageStructure,
    PageType,
    SemanticRole,
    StyledTextRun,
    TextRegionBBox,
)
from core.typeset_visibility import occluded_duplicate_block_ids


def _block(block_id: str, region_id: str, text: str, bbox: list[float]):
    return ContentBlock(
        id=block_id,
        region_id=region_id,
        role=SemanticRole.TITLE,
        runs=[StyledTextRun(text, 24.0, False, False, "#000000")],
        source_text=text,
        translated_text="拒绝",
        translatable=True,
        bbox=bbox,
    )


def _structure():
    first_bbox = [100.0, 100.0, 220.0, 140.0]
    second_bbox = [40.0, 40.0, 160.0, 80.0]
    return PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[
            TextRegionBBox("r_hidden", first_bbox, ["t1"]),
            TextRegionBBox("r_visible", second_bbox, ["t2"]),
        ],
        display_list=[
            DisplayListObject("d1", "fill-text", first_bbox, seqno=1, source_ref="r_hidden"),
            DisplayListObject("d2", "fill-image", [95.0, 95.0, 230.0, 150.0], seqno=2),
            DisplayListObject("d3", "fill-text", second_bbox, seqno=3, source_ref="r_visible"),
        ],
    )


def test_duplicate_hidden_by_later_image_is_not_rendered_twice():
    content = PageContent(
        page_index=0,
        page_type=PageType.MIXED,
        columns=[],
        blocks=[
            _block("b_hidden", "r_hidden", "REJECTION", [100.0, 100.0, 220.0, 140.0]),
            _block("b_visible", "r_visible", "Rejection", [40.0, 40.0, 160.0, 80.0]),
        ],
    )

    assert occluded_duplicate_block_ids(content, _structure()) == {"b_hidden"}


def test_unique_text_is_not_removed_from_a_possibly_transparent_image_bbox():
    content = PageContent(
        page_index=0,
        page_type=PageType.MIXED,
        columns=[],
        blocks=[
            _block("b_hidden", "r_hidden", "UNIQUE TITLE", [100.0, 100.0, 220.0, 140.0]),
            _block("b_visible", "r_visible", "Different title", [40.0, 40.0, 160.0, 80.0]),
        ],
    )

    assert occluded_duplicate_block_ids(content, _structure()) == set()
