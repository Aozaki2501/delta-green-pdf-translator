"""
Semantic analysis for the typeset reflow pipeline (Phase B).

Analyzes text regions from page_structure.json to determine semantic roles
(title, body_column, header, footer, footnote, table, list), classifies
page types, extracts styled text, and detects dual-column layouts.
Outputs a PageContentDocument that can be serialized to page_content.json.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        raise ImportError("PyMuPDF not installed. Run: pip install pymupdf")

from core.typeset_models import (
    PAGE_CONTENT_SCHEMA_VERSION,
    ColumnInfo,
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
from core.utils import ensure_output_parent


@dataclass
class PageContext:
    """Context information for classifying regions within a page."""

    page_width: float
    page_height: float
    page_type: PageType
    median_font_size: float
    image_coverage: float  # fraction of page area covered by images
    gutter_x: float | None  # x-coordinate of column gutter, if detected


class SemanticAnalyzer:
    """Text region semantic analyzer for the typeset reflow pipeline (Phase B).

    Analyzes text regions to determine their semantic roles, classifies page
    types, extracts styled text with font information, and detects dual-column
    layouts.
    """

    def __init__(self, pdf_path: str, output_dir: str):
        """
        Args:
            pdf_path: Path to the source PDF file (needed for font info extraction).
            output_dir: Output directory for the page_content.json file.
        """
        self.pdf_path = str(pdf_path)
        self.output_dir = Path(output_dir)
        self.doc = pymupdf.open(self.pdf_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        """Close the underlying PDF document."""
        self.doc.close()

    def analyze_document(self, structure: PageStructureDocument) -> PageContentDocument:
        """Analyze the entire document's text regions for semantic roles.

        Args:
            structure: The page structure document from Phase A.

        Returns:
            PageContentDocument containing semantic content for all pages.
        """
        pages = [self.analyze_page(page) for page in structure.pages]
        return PageContentDocument(
            schema_version=PAGE_CONTENT_SCHEMA_VERSION,
            source_pdf=structure.source_pdf,
            page_count=len(pages),
            pages=pages,
        )

    def analyze_page(self, page_structure: PageStructure) -> PageContent:
        """Analyze a single page's text regions for semantic roles.

        Args:
            page_structure: The page structure for a single page.

        Returns:
            PageContent with classified blocks and column information.
        """
        page_index = page_structure.page_index
        page = self.doc[page_index]

        # Extract styled text for all regions first to compute median font size
        region_runs: dict[str, list[StyledTextRun]] = {}
        for region in page_structure.text_regions:
            runs = self.extract_styled_text(region, page)
            region_runs[region.id] = runs

        # Compute median body font size across all regions
        all_font_sizes = []
        for runs in region_runs.values():
            for run in runs:
                if run.text.strip():
                    all_font_sizes.append(run.font_size)
        median_font_size = median(all_font_sizes) if all_font_sizes else 11.0

        # Compute image coverage
        page_area = page_structure.width * page_structure.height
        image_area = sum(
            _bbox_area(img.bbox) for img in page_structure.images
        )
        image_coverage = image_area / page_area if page_area > 0 else 0.0

        # Classify page type
        page_type = self.classify_page_type(page_structure, median_font_size, image_coverage)

        # Detect dual-column layout (gutter)
        gutter_x = self._detect_gutter(page_structure)

        # Build page context
        context = PageContext(
            page_width=page_structure.width,
            page_height=page_structure.height,
            page_type=page_type,
            median_font_size=median_font_size,
            image_coverage=image_coverage,
            gutter_x=gutter_x,
        )

        # Classify each region and build content blocks
        blocks: list[ContentBlock] = []
        for region in page_structure.text_regions:
            runs = region_runs[region.id]
            if not runs:
                continue

            role = self.classify_region(region, context, runs)
            source_text = "".join(run.text for run in runs)
            translatable = not _is_fixed_nontranslatable_text(source_text, role)

            block_id = f"{region.id}_b0001"
            blocks.append(ContentBlock(
                id=block_id,
                region_id=region.id,
                role=role,
                runs=runs,
                source_text=source_text,
                translated_text=None,
                translatable=translatable,
            ))

        # Build column info for dual-column pages
        columns = self._build_column_info(blocks, page_structure, gutter_x, page_type)

        return PageContent(
            page_index=page_index,
            page_type=page_type,
            columns=columns,
            blocks=blocks,
        )

    def classify_region(
        self,
        region: TextRegionBBox,
        page_context: PageContext,
        runs: list[StyledTextRun] | None = None,
    ) -> SemanticRole:
        """Classify a text region into a semantic role.

        Classification rules:
        - header: top of page (y < 10% of page height)
        - footer: bottom of page (y > 90% of page height)
        - title: large font size (>= 1.5x median body font size)
        - body_column: default for text in column areas
        - footnote: small text at bottom of page
        - table/list: based on text structure patterns

        Args:
            region: The text region bounding box.
            page_context: Context about the page (dimensions, type, etc.).
            runs: Pre-extracted styled text runs (optional, for font size check).

        Returns:
            SemanticRole enum value.
        """
        x0, y0, x1, y1 = region.bbox
        page_height = page_context.page_height

        # Header detection: top 10% of page
        if y0 < page_height * 0.10 and y1 < page_height * 0.15:
            return SemanticRole.HEADER

        # Footer detection: bottom 10% of page
        if y0 > page_height * 0.90:
            return SemanticRole.FOOTER

        # Title detection: large font size (>= 1.5x median)
        if runs:
            avg_font_size = _weighted_avg_font_size(runs)
            if avg_font_size >= page_context.median_font_size * 1.5:
                return SemanticRole.TITLE

        # Footnote detection: small text near bottom
        if runs and y0 > page_height * 0.80:
            avg_font_size = _weighted_avg_font_size(runs)
            if avg_font_size < page_context.median_font_size * 0.85:
                return SemanticRole.FOOTNOTE

        # Table detection: look for tab-separated or aligned patterns
        if runs:
            text = "".join(run.text for run in runs)
            if _looks_like_table(text):
                return SemanticRole.TABLE

        # List detection: look for bullet/number patterns
        if runs:
            text = "".join(run.text for run in runs)
            if _looks_like_list(text):
                return SemanticRole.LIST

        # Default: body_column
        return SemanticRole.BODY_COLUMN

    def classify_page_type(
        self,
        page_structure: PageStructure,
        median_font_size: float = 11.0,
        image_coverage: float = 0.0,
    ) -> PageType:
        """Classify the page type based on layout characteristics.

        Reuses logic from existing page_classifier.py:
        - art: minimal text + large images (images cover >50% of page area)
        - cover: centered large-font text with few blocks
        - columns: text blocks distributed in two vertical columns (detect gutter)
        - single: text blocks spanning full page width
        - mixed: both full-width and column blocks

        Args:
            page_structure: The page structure to classify.
            median_font_size: Median font size across the page.
            image_coverage: Fraction of page area covered by images.

        Returns:
            PageType enum value.
        """
        text_regions = page_structure.text_regions
        page_width = page_structure.width

        # Art page: minimal text + large images (>50% coverage)
        if image_coverage > 0.50 and len(text_regions) <= 2:
            return PageType.ART

        # Very few text regions
        if len(text_regions) <= 1:
            if image_coverage > 0.30:
                return PageType.ART
            return PageType.SINGLE

        # Cover page: few blocks, mostly centered or large-font
        if len(text_regions) <= 3:
            # Check if blocks are centered
            centered_count = 0
            for region in text_regions:
                x0, _, x1, _ = region.bbox
                region_center = (x0 + x1) / 2
                page_center = page_width / 2
                if abs(region_center - page_center) < page_width * 0.15:
                    centered_count += 1
            if centered_count >= len(text_regions) * 0.6:
                return PageType.COVER

        # Detect two-column layout
        page_mid = page_width / 2
        margin_threshold = page_width * 0.08

        left_regions = []
        right_regions = []
        full_width_regions = []

        for region in text_regions:
            x0, _, x1, _ = region.bbox
            region_width = x1 - x0

            # Full-width region spans most of the page
            if region_width > page_width * 0.65:
                full_width_regions.append(region)
                continue

            center = (x0 + x1) / 2
            if center < page_mid - margin_threshold:
                left_regions.append(region)
            elif center > page_mid + margin_threshold:
                right_regions.append(region)
            else:
                full_width_regions.append(region)

        # Two-column detection
        if (len(left_regions) >= 1 and len(right_regions) >= 1
                and (len(left_regions) + len(right_regions)) >= 3):
            if full_width_regions:
                return PageType.MIXED
            return PageType.COLUMNS

        # Single column
        return PageType.SINGLE

    def extract_styled_text(
        self,
        region: TextRegionBBox,
        page=None,
    ) -> list[StyledTextRun]:
        """Extract styled text runs from a text region using PyMuPDF.

        Uses page.get_text("dict") to get font information for each span.

        Args:
            region: The text region bounding box.
            page: PyMuPDF page object. If None, uses self.doc with region ID.

        Returns:
            List of StyledTextRun with font size, bold, italic, and color info.
        """
        if page is None:
            # Extract page index from region ID (e.g., "p0001_r0001" -> page 0)
            page_idx = int(region.id[1:5]) - 1
            page = self.doc[page_idx]

        runs: list[StyledTextRun] = []
        x0, y0, x1, y1 = region.bbox
        region_rect = pymupdf.Rect(x0, y0, x1, y1)

        # Get text dict for the page
        page_dict = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)

        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:  # Only text blocks
                continue

            block_bbox = block.get("bbox", [0, 0, 0, 0])
            block_rect = pymupdf.Rect(block_bbox)

            # Check if this block overlaps with our region
            if not block_rect.intersects(region_rect):
                continue

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    span_bbox = span.get("bbox", [0, 0, 0, 0])
                    span_rect = pymupdf.Rect(span_bbox)

                    # Check if span is within the region
                    if not span_rect.intersects(region_rect):
                        continue

                    text = span.get("text", "")
                    if not text:
                        continue

                    font_size = float(span.get("size", 11.0))
                    flags = int(span.get("flags", 0))
                    # PyMuPDF flags: bit 0 = superscript, bit 1 = italic,
                    # bit 2 = serif, bit 3 = monospace, bit 4 = bold
                    bold = bool(flags & (1 << 4))
                    italic = bool(flags & (1 << 1))
                    color_int = int(span.get("color", 0))
                    color = f"#{color_int & 0xFFFFFF:06x}"

                    runs.append(StyledTextRun(
                        text=text,
                        font_size=round(font_size, 2),
                        bold=bold,
                        italic=italic,
                        color=color,
                    ))

        return _dedupe_styled_runs(runs)

    def _detect_gutter(self, page_structure: PageStructure) -> float | None:
        """Detect the vertical gutter separating two columns.

        Finds a vertical gap between text regions that separates them into
        left and right groups.

        Args:
            page_structure: The page structure to analyze.

        Returns:
            X-coordinate of the gutter center, or None if not detected.
        """
        text_regions = page_structure.text_regions
        page_width = page_structure.width

        if len(text_regions) < 3:
            return None

        page_mid = page_width / 2
        margin_threshold = page_width * 0.08

        left_regions = []
        right_regions = []

        for region in text_regions:
            x0, _, x1, _ = region.bbox
            region_width = x1 - x0

            # Skip full-width regions
            if region_width > page_width * 0.65:
                continue

            center = (x0 + x1) / 2
            if center < page_mid - margin_threshold:
                left_regions.append(region)
            elif center > page_mid + margin_threshold:
                right_regions.append(region)

        if not left_regions or not right_regions:
            return None

        # Find gutter as midpoint between left column right edges and right column left edges
        left_right_edges = sorted(r.bbox[2] for r in left_regions)
        right_left_edges = sorted(r.bbox[0] for r in right_regions)

        median_left_edge = left_right_edges[len(left_right_edges) // 2]
        median_right_edge = right_left_edges[len(right_left_edges) // 2]

        # Gutter must be a meaningful gap
        if median_right_edge <= median_left_edge:
            return None

        return (median_left_edge + median_right_edge) / 2

    def _build_column_info(
        self,
        blocks: list[ContentBlock],
        page_structure: PageStructure,
        gutter_x: float | None,
        page_type: PageType,
    ) -> list[ColumnInfo]:
        """Build column information for dual-column pages.

        Args:
            blocks: The classified content blocks.
            page_structure: The page structure.
            gutter_x: The detected gutter x-coordinate.
            page_type: The classified page type.

        Returns:
            List of ColumnInfo (2 entries for column pages, empty otherwise).
        """
        if page_type not in (PageType.COLUMNS, PageType.MIXED):
            return []

        if gutter_x is None:
            return []

        # Build a lookup from region_id to region bbox
        region_bbox_map: dict[str, list[float]] = {
            r.id: r.bbox for r in page_structure.text_regions
        }

        left_block_ids: list[str] = []
        right_block_ids: list[str] = []
        left_bboxes: list[list[float]] = []
        right_bboxes: list[list[float]] = []

        for block in blocks:
            if block.role in (SemanticRole.HEADER, SemanticRole.FOOTER):
                continue
            if block.role != SemanticRole.BODY_COLUMN:
                continue

            region_bbox = region_bbox_map.get(block.region_id)
            if region_bbox is None:
                continue

            x0, y0, x1, y1 = region_bbox
            center_x = (x0 + x1) / 2

            if center_x < gutter_x:
                left_block_ids.append(block.id)
                left_bboxes.append(region_bbox)
            else:
                right_block_ids.append(block.id)
                right_bboxes.append(region_bbox)

        if not left_block_ids and not right_block_ids:
            return []

        columns: list[ColumnInfo] = []

        if left_block_ids:
            left_bbox = [
                min(b[0] for b in left_bboxes),
                min(b[1] for b in left_bboxes),
                max(b[2] for b in left_bboxes),
                max(b[3] for b in left_bboxes),
            ]
            columns.append(ColumnInfo(
                side="left",
                bbox=left_bbox,
                block_ids=left_block_ids,
            ))

        if right_block_ids:
            right_bbox = [
                min(b[0] for b in right_bboxes),
                min(b[1] for b in right_bboxes),
                max(b[2] for b in right_bboxes),
                max(b[3] for b in right_bboxes),
            ]
            columns.append(ColumnInfo(
                side="right",
                bbox=right_bbox,
                block_ids=right_block_ids,
            ))

        return columns


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------


def _bbox_area(bbox: list[float]) -> float:
    """Calculate the area of a bounding box [x0, y0, x1, y1]."""
    if len(bbox) != 4:
        return 0.0
    width = abs(bbox[2] - bbox[0])
    height = abs(bbox[3] - bbox[1])
    return width * height


def _weighted_avg_font_size(runs: list[StyledTextRun]) -> float:
    """Calculate weighted average font size based on text length."""
    total_chars = 0
    weighted_sum = 0.0
    for run in runs:
        chars = len(run.text.strip())
        if chars > 0:
            weighted_sum += run.font_size * chars
            total_chars += chars
    return weighted_sum / total_chars if total_chars > 0 else 11.0


def _dedupe_styled_runs(runs: list[StyledTextRun]) -> list[StyledTextRun]:
    """Remove duplicate overprinted spans, keeping the visible brighter color."""
    deduped: list[StyledTextRun] = []
    for run in runs:
        if deduped and _same_text_style(deduped[-1], run):
            if _color_luminance(run.color) >= _color_luminance(deduped[-1].color):
                deduped[-1] = run
            continue
        deduped.append(run)
    return deduped


def _is_fixed_nontranslatable_text(text: str, role: SemanticRole) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if role == SemanticRole.FOOTER and stripped.isdigit():
        return True
    if role == SemanticRole.HEADER and "//" in stripped:
        return True
    return False


def _same_text_style(a: StyledTextRun, b: StyledTextRun) -> bool:
    return (
        a.text == b.text
        and abs(a.font_size - b.font_size) < 0.01
        and a.bold == b.bold
        and a.italic == b.italic
    )


def _color_luminance(color: str) -> float:
    if not color or not color.startswith("#") or len(color) != 7:
        return 0.0
    try:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
    except ValueError:
        return 0.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _looks_like_table(text: str) -> bool:
    """Heuristic: detect table-like text patterns.

    Looks for multiple lines with consistent tab/space-separated columns.
    """
    lines = text.strip().split("\n")
    if len(lines) < 3:
        return False

    # Check for tab-separated content
    tab_lines = sum(1 for line in lines if "\t" in line)
    if tab_lines >= len(lines) * 0.6:
        return True

    # Check for consistent multi-space separation (aligned columns)
    multi_space_lines = sum(1 for line in lines if "   " in line.strip())
    if multi_space_lines >= len(lines) * 0.6:
        return True

    return False


def _looks_like_list(text: str) -> bool:
    """Heuristic: detect list-like text patterns.

    Looks for lines starting with bullets, numbers, or dashes.
    """
    import re

    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    if len(lines) < 2:
        return False

    list_pattern = re.compile(r"^(\d+[\.\)]\s|[-•●◦▪]\s|[a-zA-Z][\.\)]\s)")
    list_lines = sum(1 for line in lines if list_pattern.match(line))

    return list_lines >= len(lines) * 0.5


# ---------------------------------------------------------------------------
# Public convenience function
# ---------------------------------------------------------------------------


def analyze_page_content_to_file(
    pdf_path: str,
    output_dir: str,
    structure: PageStructureDocument,
) -> PageContentDocument:
    """Analyze page content and save to page_content.json.

    Args:
        pdf_path: Path to the source PDF file.
        output_dir: Output directory for the JSON file.
        structure: The page structure document from Phase A.

    Returns:
        The analyzed PageContentDocument.
    """
    output_path = Path(output_dir) / "page_content.json"
    ensure_output_parent(str(output_path))

    with SemanticAnalyzer(pdf_path, output_dir) as analyzer:
        content = analyzer.analyze_document(structure)

    output_path.write_text(content.to_json(), encoding="utf-8")
    return content
