import json

import pytest

from core.layout_hints import (
    LAYOUT_HINTS_SCHEMA_VERSION,
    LayoutHints,
    apply_hints_to_content,
    block_ids_by_page_from_content,
    block_ids_by_page_from_structure,
)
from core.typeset_models import (
    PAGE_CONTENT_SCHEMA_VERSION,
    PAGE_STRUCTURE_SCHEMA_VERSION,
    BackgroundLayer,
    ContentBlock,
    PageContent,
    PageContentDocument,
    PageStructure,
    PageStructureDocument,
    PageType,
    SemanticRole,
    StyledTextRun,
    TextRegionBBox,
)


def _content_doc(block_ids=("b1", "b2", "b3", "b4")):
    return PageContentDocument(
        schema_version=PAGE_CONTENT_SCHEMA_VERSION,
        source_pdf="book.pdf",
        page_count=1,
        pages=[
            PageContent(
                page_index=0,
                page_type=PageType.COLUMNS,
                columns=[],
                blocks=[
                    ContentBlock(
                        id=block_id,
                        region_id=f"r{index}",
                        role=SemanticRole.BODY_COLUMN,
                        runs=[
                            StyledTextRun(
                                text="Text",
                                font_size=10.9,
                                bold=False,
                                italic=False,
                                color="#000000",
                            )
                        ],
                        source_text="Text",
                        translated_text=None,
                        translatable=True,
                    )
                    for index, block_id in enumerate(block_ids, start=1)
                ],
            )
        ],
    )


def _structure_doc():
    return PageStructureDocument(
        schema_version=PAGE_STRUCTURE_SCHEMA_VERSION,
        source_pdf="book.pdf",
        page_count=1,
        pages=[
            PageStructure(
                page_index=0,
                width=612.0,
                height=792.0,
                background=BackgroundLayer(),
                images=[],
                decorations=[],
                text_regions=[
                    TextRegionBBox("r1", [10.0, 20.0, 110.0, 60.0], ["t1"]),
                    TextRegionBBox("r2", [120.0, 20.0, 220.0, 60.0], ["t2"]),
                    TextRegionBBox("r3", [10.0, 80.0, 110.0, 120.0], ["t3"]),
                    TextRegionBBox("r4", [120.0, 80.0, 220.0, 120.0], ["t4"]),
                ],
            )
        ],
    )


def test_loads_minimal_hints_with_defaults(tmp_path):
    path = tmp_path / "layout_hints.json"
    path.write_text(
        json.dumps({
            "schema_version": LAYOUT_HINTS_SCHEMA_VERSION,
            "source_pdf": "book.pdf",
            "pages": {"0": {}},
        }),
        encoding="utf-8",
    )

    hints = LayoutHints.from_file(path)
    page = hints.get_page_hint(0)

    assert page is not None
    assert page.page_index == 0
    assert page.page_type is None
    assert page.reading_order == []
    assert page.skip_blocks == []
    assert page.columns == []
    assert page.special_regions == []
    assert hints.get_page_hint(1) is None


def test_loads_full_hints_and_validates_content():
    hints = LayoutHints.from_json(json.dumps({
        "schema_version": LAYOUT_HINTS_SCHEMA_VERSION,
        "source_pdf": "book.pdf",
        "pages": {
            "0": {
                "page_type": "columns",
                "reading_order": ["b1", "b3"],
                "skip_blocks": [{"id": "b2", "reason": "running_header"}],
                "columns": [
                    {"id": "left", "blocks": ["b1"]},
                    {"id": "right", "blocks": ["b3"]},
                ],
                "special_regions": [
                    {"type": "sidebar", "blocks": ["b4"]},
                ],
            }
        },
    }))

    page = hints.get_page_hint(0)

    assert page is not None
    assert page.page_type == "columns"
    assert page.skip_blocks[0].reason == "running_header"
    assert page.columns[1].id == "right"
    hints.validate_against_content(_content_doc())


def test_rejects_invalid_page_type():
    with pytest.raises(ValueError, match="page_type"):
        LayoutHints.from_json(json.dumps({
            "schema_version": LAYOUT_HINTS_SCHEMA_VERSION,
            "pages": {"0": {"page_type": "two_columnish"}},
        }))


def test_rejects_missing_block_ids():
    hints = LayoutHints.from_json(json.dumps({
        "schema_version": LAYOUT_HINTS_SCHEMA_VERSION,
        "pages": {"0": {"reading_order": ["b1", "missing"]}},
    }))

    with pytest.raises(ValueError, match="missing"):
        hints.validate_against_content(_content_doc(block_ids=("b1",)))


def test_rejects_hint_page_not_in_document():
    hints = LayoutHints.from_json(json.dumps({
        "schema_version": LAYOUT_HINTS_SCHEMA_VERSION,
        "pages": {"2": {"reading_order": ["b1"]}},
    }))

    with pytest.raises(ValueError, match="不存在"):
        hints.validate_against_content(_content_doc())


def test_collects_structure_region_and_block_ids():
    structure = PageStructureDocument(
        schema_version=PAGE_STRUCTURE_SCHEMA_VERSION,
        source_pdf="book.pdf",
        page_count=1,
        pages=[
            PageStructure(
                page_index=0,
                width=612.0,
                height=792.0,
                background=BackgroundLayer(),
                images=[],
                decorations=[],
                text_regions=[
                    TextRegionBBox(
                        id="r1",
                        bbox=[10.0, 20.0, 30.0, 40.0],
                        block_ids=["t1"],
                    )
                ],
            )
        ],
    )

    ids = block_ids_by_page_from_structure(structure)

    assert ids == {0: {"r1", "t1"}}


def test_collects_content_block_ids():
    ids = block_ids_by_page_from_content(_content_doc(block_ids=("b1", "b2")))

    assert ids == {0: {"b1", "b2"}}


def test_apply_hints_to_content_changes_semantics():
    hints = LayoutHints.from_json(json.dumps({
        "schema_version": LAYOUT_HINTS_SCHEMA_VERSION,
        "pages": {
            "0": {
                "page_type": "columns",
                "reading_order": ["b2", "b1"],
                "skip_blocks": [{"id": "b2", "reason": "running_header"}],
                "columns": [
                    {"id": "left", "blocks": ["b1", "b3"]},
                    {"id": "right", "blocks": ["b2", "b4"]},
                ],
            }
        },
    }))

    hinted = apply_hints_to_content(_content_doc(), hints, _structure_doc())
    page = hinted.pages[0]

    assert page.page_type == PageType.COLUMNS
    assert [block.id for block in page.blocks] == ["b2", "b1", "b3", "b4"]
    assert page.blocks[0].translatable is False
    assert page.columns[0].side == "left"
    assert page.columns[0].bbox == [10.0, 20.0, 110.0, 120.0]
    assert page.columns[0].block_ids == ["b1", "b3"]


def test_apply_hints_requires_column_bboxes():
    structure = PageStructureDocument(
        schema_version=PAGE_STRUCTURE_SCHEMA_VERSION,
        source_pdf="book.pdf",
        page_count=1,
        pages=[
            PageStructure(
                page_index=0,
                width=612.0,
                height=792.0,
                background=BackgroundLayer(),
                images=[],
                decorations=[],
                text_regions=[],
            )
        ],
    )
    hints = LayoutHints.from_json(json.dumps({
        "schema_version": LAYOUT_HINTS_SCHEMA_VERSION,
        "pages": {
            "0": {
                "columns": [{"id": "left", "blocks": ["b1"]}],
            }
        },
    }))

    with pytest.raises(ValueError, match="无坐标"):
        apply_hints_to_content(_content_doc(block_ids=("b1",)), hints, structure)
