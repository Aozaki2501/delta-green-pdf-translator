"""
Page classification for the replica PDF pipeline.

Analyzes text block positions to determine page layout type:
- columns: Two-column body text (most common for TRPG content)
- single: Single-column body text
- cover: Cover/title page with minimal text
- art: Full-page illustration with little or no text
- mixed: Page with both column and non-column regions
"""

from dataclasses import dataclass
from enum import Enum

from core.layout_model import LayoutPage, LayoutTextBlock
from core.layout_translation import block_source_text


class PageType(Enum):
    COLUMNS = "columns"
    SINGLE = "single"
    COVER = "cover"
    ART = "art"
    MIXED = "mixed"


@dataclass(frozen=True)
class ColumnRegion:
    """A detected column region on a page."""
    x0: float
    y0: float
    x1: float
    y1: float
    block_ids: list[str]


@dataclass(frozen=True)
class PageClassification:
    """Classification result for a single page."""
    page_index: int
    page_type: PageType
    columns: list[ColumnRegion]  # Empty for non-column pages
    gutter_x: float | None  # X position of the column divider, if detected


def _text_block_has_content(block: LayoutTextBlock) -> bool:
    """Check if a block has meaningful translatable content."""
    text = block_source_text(block)
    return bool(text and len(text.strip()) > 2)


def _block_center_x(block: LayoutTextBlock) -> float:
    return (block.bbox[0] + block.bbox[2]) / 2


def _block_width(block: LayoutTextBlock) -> float:
    return block.bbox[2] - block.bbox[0]


def classify_page(page: LayoutPage) -> PageClassification:
    """Classify a page's layout type based on text block positions."""
    content_blocks = [b for b in page.text_blocks if _text_block_has_content(b)]

    # Art page: very few text blocks
    if len(content_blocks) <= 1:
        return PageClassification(
            page_index=page.index,
            page_type=PageType.ART,
            columns=[],
            gutter_x=None,
        )

    # Cover page: few blocks, mostly centered or large title blocks
    if len(content_blocks) <= 3:
        avg_width = sum(_block_width(b) for b in content_blocks) / len(content_blocks)
        if avg_width > page.width * 0.6:
            return PageClassification(
                page_index=page.index,
                page_type=PageType.COVER,
                columns=[],
                gutter_x=None,
            )

    # Detect two-column layout by analyzing x-position distribution
    page_mid = page.width / 2
    margin_threshold = page.width * 0.08  # 8% margin tolerance

    left_blocks = []
    right_blocks = []
    full_width_blocks = []

    for block in content_blocks:
        x0, _, x1, _ = block.bbox
        block_w = x1 - x0

        # Full-width block spans most of the page
        if block_w > page.width * 0.65:
            full_width_blocks.append(block)
            continue

        center = _block_center_x(block)
        # Block is in left half
        if center < page_mid - margin_threshold:
            left_blocks.append(block)
        # Block is in right half
        elif center > page_mid + margin_threshold:
            right_blocks.append(block)
        else:
            # Block is centered - could be title or single-column
            full_width_blocks.append(block)

    # Two-column detection: need blocks on both sides
    if len(left_blocks) >= 1 and len(right_blocks) >= 1 and (len(left_blocks) + len(right_blocks)) >= 3:
        # Find the gutter position
        left_right_edges = sorted(b.bbox[2] for b in left_blocks)
        right_left_edges = sorted(b.bbox[0] for b in right_blocks)
        gutter_x = (left_right_edges[len(left_right_edges) // 2] +
                    right_left_edges[len(right_left_edges) // 2]) / 2

        left_col = ColumnRegion(
            x0=min(b.bbox[0] for b in left_blocks),
            y0=min(b.bbox[1] for b in left_blocks),
            x1=max(b.bbox[2] for b in left_blocks),
            y1=max(b.bbox[3] for b in left_blocks),
            block_ids=[b.id for b in left_blocks],
        )
        right_col = ColumnRegion(
            x0=min(b.bbox[0] for b in right_blocks),
            y0=min(b.bbox[1] for b in right_blocks),
            x1=max(b.bbox[2] for b in right_blocks),
            y1=max(b.bbox[3] for b in right_blocks),
            block_ids=[b.id for b in right_blocks],
        )

        page_type = PageType.MIXED if full_width_blocks else PageType.COLUMNS
        return PageClassification(
            page_index=page.index,
            page_type=page_type,
            columns=[left_col, right_col],
            gutter_x=gutter_x,
        )

    # Single column
    return PageClassification(
        page_index=page.index,
        page_type=PageType.SINGLE,
        columns=[],
        gutter_x=None,
    )


def classify_document(pages: list[LayoutPage]) -> list[PageClassification]:
    """Classify all pages in a document."""
    return [classify_page(page) for page in pages]
