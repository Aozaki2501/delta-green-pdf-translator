"""Page template selection for the typeset PDF renderer."""

from __future__ import annotations

from dataclasses import dataclass

from core.typeset_models import PageContent, PageStructure, PageType, SemanticRole


@dataclass(frozen=True)
class TypesetPageTemplate:
    id: str
    use_line_tracks: bool
    use_source_columns: bool
    keep_fixed_regions: bool


def select_typeset_template(
    page_content: PageContent,
    page_structure: PageStructure,
) -> TypesetPageTemplate:
    """Select a deterministic renderer template from page semantics and geometry."""
    if page_content.page_type in (PageType.ART, PageType.COVER):
        return TypesetPageTemplate(
            id="fixed_art",
            use_line_tracks=False,
            use_source_columns=False,
            keep_fixed_regions=True,
        )

    has_columns = len(page_content.columns) >= 2
    body_region_ids = {
        block.region_id
        for block in page_content.blocks
        if block.role == SemanticRole.BODY_COLUMN
    }
    body_regions = [
        region for region in page_structure.text_regions
        if region.id in body_region_ids
    ]
    has_line_tracks = bool(body_regions) and all(region.lines for region in body_regions)

    if has_columns and has_line_tracks:
        return TypesetPageTemplate(
            id="line_track_columns",
            use_line_tracks=True,
            use_source_columns=True,
            keep_fixed_regions=True,
        )
    if has_columns:
        return TypesetPageTemplate(
            id="source_columns",
            use_line_tracks=False,
            use_source_columns=True,
            keep_fixed_regions=True,
        )
    return TypesetPageTemplate(
        id="single_source_flow",
        use_line_tracks=False,
        use_source_columns=False,
        keep_fixed_regions=True,
    )
