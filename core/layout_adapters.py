"""Adapters from typeset page semantics to ordinary reading outputs.

The pure typeset PDF pipeline knows more about the source page than the
ordinary Markdown/HTML/Word exporters can use directly. This module keeps the
shared part small: convert semantic page analysis into reading-layout labels
that the ordinary exporters already understand.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from tempfile import TemporaryDirectory

from core.typeset_models import PageContent, PageContentDocument, PageType


SPECIALIZED_READING_LAYOUTS = frozenset({
    "toc",
    "handout",
    "character",
    "document",
    "credits",
    "art",
})

ORDINARY_READING_LAYOUTS = frozenset({
    "columns",
    "three_columns",
    "single",
    "art",
})


@dataclass(frozen=True)
class OutputLayoutContext:
    """Layout facts that ordinary exporters can consume safely."""

    page_layouts: dict[int, str] = field(default_factory=dict)
    notes: dict[int, list[str]] = field(default_factory=dict)


def build_pdf_output_layout_context(
    pdf_path: str,
    start_page: int = 0,
    end_page: int | None = None,
) -> OutputLayoutContext:
    """Analyze a PDF with the typeset semantic stack for ordinary outputs."""
    from core.page_structure import PageStructureExtractor
    from core.semantic_analyzer import SemanticAnalyzer

    with TemporaryDirectory(prefix="dgtranslate_layout_") as temp_dir:
        with PageStructureExtractor(pdf_path, temp_dir) as extractor:
            structure = extractor.extract(
                start_page=start_page,
                end_page=end_page,
                include_images=False,
            )
        with SemanticAnalyzer(pdf_path, temp_dir) as analyzer:
            content = analyzer.analyze_document(structure)
    return build_output_layout_context_from_content(content)


def build_output_layout_context_from_content(
    content: PageContentDocument,
) -> OutputLayoutContext:
    """Build ordinary-export layout labels from semantic page content."""
    page_layouts: dict[int, str] = {}
    notes: dict[int, list[str]] = {}
    for page in content.pages:
        layout = layout_label_from_page_content(page)
        page_layouts[page.page_index] = layout
        notes[page.page_index] = _notes_for_page(page, layout)
    return OutputLayoutContext(page_layouts=page_layouts, notes=notes)


def layout_label_from_page_content(page: PageContent) -> str:
    """Return a layout label supported by ordinary HTML/Word exporters."""
    if page.page_type == PageType.ART:
        return "art"
    if page.page_type in (PageType.COVER, PageType.SINGLE):
        return "single"
    if page.page_type == PageType.COLUMNS:
        return "three_columns" if len(page.columns) >= 3 else "columns"
    if page.page_type == PageType.MIXED:
        if len(page.columns) >= 3:
            return "three_columns"
        return "columns" if len(page.columns) >= 2 else "single"
    return "columns"


def merge_page_layout_label(base_layout: str | None, semantic_layout: str | None) -> str:
    """Prefer specialized extractor labels, otherwise use semantic labels."""
    base = (base_layout or "").strip() or "columns"
    semantic = (semantic_layout or "").strip()
    if base in SPECIALIZED_READING_LAYOUTS:
        return base
    if semantic in ORDINARY_READING_LAYOUTS:
        return semantic
    return base


def merge_output_page_layouts(
    base_layouts: dict[int, str],
    semantic_layouts: dict[int, str],
) -> dict[int, str]:
    """Merge extractor and semantic page-layout maps."""
    page_indexes = set(base_layouts) | set(semantic_layouts)
    return {
        page_index: merge_page_layout_label(
            base_layouts.get(page_index),
            semantic_layouts.get(page_index),
        )
        for page_index in page_indexes
    }


def _notes_for_page(page: PageContent, layout: str) -> list[str]:
    role_counts = Counter(block.role.value for block in page.blocks)
    role_summary = ", ".join(
        f"{role}={count}" for role, count in sorted(role_counts.items())
    )
    notes = [
        f"typeset_semantic_layout: {layout}",
        f"typeset_page_type: {page.page_type.value}",
    ]
    if page.columns:
        notes.append(f"typeset_columns: {len(page.columns)}")
    if role_summary:
        notes.append(f"typeset_roles: {role_summary}")
    return notes
