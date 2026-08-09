"""Deterministic visibility rules shared by semantic cleanup and HTML QA."""

from __future__ import annotations

import re
from collections import defaultdict

from core.typeset_models import (
    PageContent,
    PageContentDocument,
    PageStructure,
    PageStructureDocument,
)


def _normalized_source(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text or "").casefold()


def _bbox_area(bbox: list[float] | None) -> float:
    if not bbox or len(bbox) != 4:
        return 0.0
    return max(0.0, float(bbox[2]) - float(bbox[0])) * max(
        0.0, float(bbox[3]) - float(bbox[1])
    )


def _intersection_ratio(first: list[float], second: list[float]) -> float:
    area = _bbox_area(first)
    if area <= 0:
        return 0.0
    width = max(
        0.0,
        min(float(first[2]), float(second[2]))
        - max(float(first[0]), float(second[0])),
    )
    height = max(
        0.0,
        min(float(first[3]), float(second[3]))
        - max(float(first[1]), float(second[1])),
    )
    return width * height / area


def _later_image_coverage(
    region_id: str,
    bbox: list[float],
    page_structure: PageStructure,
) -> float:
    text_seqnos = [
        int(item.seqno)
        for item in page_structure.display_list
        if item.seqno is not None
        and item.source_ref == region_id
        and "text" in item.kind
    ]
    if not text_seqnos:
        return 0.0
    last_text_seqno = max(text_seqnos)
    return max(
        (
            _intersection_ratio(bbox, item.bbox)
            for item in page_structure.display_list
            if item.seqno is not None
            and int(item.seqno) > last_text_seqno
            and "image" in item.kind
        ),
        default=0.0,
    )


def occluded_duplicate_block_ids(
    page_content: PageContent,
    page_structure: PageStructure,
    *,
    coverage_threshold: float = 0.85,
) -> set[str]:
    """Return duplicate source blocks hidden by a later-painted image.

    The duplicate requirement keeps this strict: a unique block is never
    discarded merely because an image bounding box may contain transparency.
    """
    if not page_structure.display_list:
        return set()
    region_bboxes = {
        region.id: region.bbox for region in page_structure.text_regions
    }
    groups: dict[str, list] = defaultdict(list)
    for block in page_content.blocks:
        normalized = _normalized_source(block.source_text)
        if len(normalized) >= 5:
            groups[normalized].append(block)

    hidden: set[str] = set()
    for blocks in groups.values():
        if len(blocks) < 2:
            continue
        coverage = {
            block.id: _later_image_coverage(
                block.region_id,
                block.bbox or region_bboxes.get(block.region_id, []),
                page_structure,
            )
            for block in blocks
        }
        if not any(value < coverage_threshold for value in coverage.values()):
            continue
        hidden.update(
            block_id
            for block_id, value in coverage.items()
            if value >= coverage_threshold
        )
    return hidden


def expected_render_blocks(
    content: PageContentDocument,
    structure: PageStructureDocument,
) -> dict[str, str]:
    """Return every translated block that must have one browser render owner."""
    structure_by_page = {page.page_index: page for page in structure.pages}
    expected: dict[str, str] = {}
    for page in content.pages:
        page_structure = structure_by_page.get(page.page_index)
        hidden = (
            occluded_duplicate_block_ids(page, page_structure)
            if page_structure is not None
            else set()
        )
        for block in page.blocks:
            if (
                block.id not in hidden
                and block.translatable
                and block.translated_text
                and block.layout_mode not in {
                    "image_overlay_text", "hidden_source_text"
                }
            ):
                expected[block.id] = str(page.page_index + 1)
    return expected


__all__ = ["expected_render_blocks", "occluded_duplicate_block_ids"]
