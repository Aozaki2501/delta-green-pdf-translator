"""
Semantic analysis for the typeset reflow pipeline (Phase B).

Analyzes text regions from page_structure.json to determine semantic roles
(title, body_column, header, footer, footnote, table, list), classifies
page types, extracts styled text, and detects dual-column layouts.
Outputs a PageContentDocument that can be serialized to page_content.json.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
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
    DecorationElement,
    FontRole,
    PageContent,
    PageContentDocument,
    PageStructure,
    PageStructureDocument,
    PageType,
    SemanticRole,
    StyledTextRun,
    TextLineBBox,
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
    max_font_size: float = 0.0


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
            source_sha256=structure.source_sha256,
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

        # Phase A already preserves the authoritative line/span geometry.
        # Semantic analysis must not re-read and flatten the PDF text blocks.
        all_font_sizes = [
            float(span.font_size)
            for region in page_structure.text_regions
            for line in region.lines
            for span in line.spans
            if span.text.strip()
        ]
        median_font_size = median(all_font_sizes) if all_font_sizes else 11.0
        max_font_size = max(all_font_sizes) if all_font_sizes else median_font_size

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
        if gutter_x is None and page_type == PageType.COLUMNS and len(page_structure.text_regions) == 2:
            left_region, right_region = sorted(
                page_structure.text_regions,
                key=lambda region: region.bbox[0],
            )
            if left_region.bbox[2] < right_region.bbox[0]:
                gutter_x = (left_region.bbox[2] + right_region.bbox[0]) / 2

        # Build page context
        context = PageContext(
            page_width=page_structure.width,
            page_height=page_structure.height,
            page_type=page_type,
            median_font_size=median_font_size,
            max_font_size=max_font_size,
            image_coverage=image_coverage,
            gutter_x=gutter_x,
        )

        # Split every source region into stable semantic segments. A single
        # PDF text block may contain a heading followed by several paragraphs.
        blocks: list[ContentBlock] = []
        for region in page_structure.text_regions:
            if not region.lines:
                raise ValueError(f"文本区域缺少行级结构：{region.id}")
            region_blocks = self._segment_region(region, context, gutter_x)
            if (
                _region_inside_table_grid(region, page_structure)
                and not any(
                    block.role in {
                        SemanticRole.TITLE,
                        SemanticRole.HEADER,
                        SemanticRole.FOOTER,
                    }
                    or (block.source_text or "").lstrip().startswith(">>")
                    or (block.source_text or "").strip().startswith("//")
                    for block in region_blocks
                )
            ):
                region_blocks = [
                    replace(
                        block,
                        role=SemanticRole.TABLE,
                        font_role=FontRole.TABLE,
                        layout_mode="table",
                        translatable=block.translatable,
                    )
                    for block in region_blocks
                ]
            blocks.extend(region_blocks)

        blocks = _dedupe_overprinted_blocks(blocks)
        if _structured_table_grid_bounds(page_structure) is not None:
            blocks = _coalesce_structured_table_cells(blocks, page_structure)
        blocks = [replace(block, order=index) for index, block in enumerate(blocks)]

        # Build column info for dual-column pages
        columns = self._build_column_info(blocks, page_structure, gutter_x, page_type)

        return PageContent(
            page_index=page_index,
            page_type=page_type,
            columns=columns,
            blocks=blocks,
        )

    def _segment_region(
        self,
        region: TextRegionBBox,
        context: PageContext,
        gutter_x: float | None,
    ) -> list[ContentBlock]:
        """Split one PDF region into headings and real paragraphs."""
        line_specs: list[dict] = []
        for line_index, line in enumerate(region.lines):
            runs = _styled_runs_from_line(line, line_index)
            if not runs:
                continue
            font_role, role = _classify_line_style(line, runs, context)
            line_specs.append({
                "line_index": line_index,
                "line_id": f"{region.id}_l{line_index + 1:04d}",
                "line": line,
                "runs": runs,
                "font_role": font_role,
                "role": role,
            })
        if not line_specs:
            return []

        body_x0 = min(
            (spec["line"].bbox[0] for spec in line_specs if spec["font_role"] == FontRole.BODY),
            default=region.bbox[0],
        )
        groups: list[list[dict]] = []
        current: list[dict] = []
        for spec in line_specs:
            if current and _starts_new_segment(current, spec, body_x0, context.median_font_size):
                groups.append(current)
                current = []
            current.append(spec)
        if current:
            groups.append(current)

        result: list[ContentBlock] = []
        paragraph_index = 0
        for block_index, group in enumerate(groups, start=1):
            paragraph_index += 1
            runs = [run for spec in group for run in spec["runs"]]
            role = group[0]["role"]
            font_role = group[0]["font_role"]
            bbox = _union_bboxes([spec["line"].bbox for spec in group])
            source_text = "\n".join(spec["line"].text.strip() for spec in group).strip()
            column_id = _column_id_for_bbox(
                bbox,
                context.page_width,
                gutter_x,
                font_role=font_role,
            )
            first_indent = max(0.0, float(group[0]["line"].bbox[0]) - body_x0)
            line_height = _median_line_advance(group)
            source_font = _dominant_font(runs)
            translatable = not _is_fixed_nontranslatable_text(source_text, role)
            layout_mode = (
                "positioned"
                if font_role in {FontRole.DISPLAY, FontRole.RUNNING_HEADER, FontRole.FOOTER}
                else "paragraph"
            )
            result.append(ContentBlock(
                id=f"{region.id}_b{block_index:04d}",
                region_id=region.id,
                role=role,
                runs=runs,
                source_text=source_text,
                translated_text=None,
                translatable=translatable,
                bbox=bbox,
                line_ids=[spec["line_id"] for spec in group],
                paragraph_id=f"{region.id}_p{paragraph_index:04d}",
                font_role=font_role,
                source_font=source_font,
                column_id=column_id,
                layout_mode=layout_mode,
                first_line_indent_pt=first_indent,
                line_height_pt=line_height,
            ))
        return result

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
            if _has_accent_heading_color(runs) and avg_font_size >= page_context.median_font_size * 0.95:
                return SemanticRole.SUBTITLE
            if avg_font_size >= page_context.median_font_size * 1.5:
                return SemanticRole.TITLE
            if _short_styled_heading(region, page_context, runs):
                return SemanticRole.SUBTITLE

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

        Uses simple page geometry signals:
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
        substantial_left = any(
            region.bbox[3] - region.bbox[1] >= page_structure.height * 0.20
            for region in left_regions
        )
        substantial_right = any(
            region.bbox[3] - region.bbox[1] >= page_structure.height * 0.20
            for region in right_regions
        )
        if (
            left_regions
            and right_regions
            and (
                len(left_regions) + len(right_regions) >= 3
                or (substantial_left and substantial_right)
            )
        ):
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

                    # Use the span center, not any intersection. Adjacent PDF
                    # regions often touch; intersection duplicated whole
                    # paragraphs across neighboring boxes.
                    center_x = (span_rect.x0 + span_rect.x1) / 2
                    center_y = (span_rect.y0 + span_rect.y1) / 2
                    if not region_rect.contains(pymupdf.Point(center_x, center_y)):
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
                        font=span.get("font"),
                        bbox=[round(float(value), 3) for value in span_bbox],
                        baseline=(
                            round(float(span["origin"][1]), 3)
                            if span.get("origin") and len(span["origin"]) >= 2
                            else None
                        ),
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

        left_block_ids: list[str] = []
        right_block_ids: list[str] = []
        left_bboxes: list[list[float]] = []
        right_bboxes: list[list[float]] = []

        for block in blocks:
            if block.role in (SemanticRole.HEADER, SemanticRole.FOOTER):
                continue
            if block.column_id not in {"left", "right"}:
                continue

            block_bbox = block.bbox
            if block_bbox is None:
                continue

            if block.column_id == "left":
                left_block_ids.append(block.id)
                left_bboxes.append(block_bbox)
            else:
                right_block_ids.append(block.id)
                right_bboxes.append(block_bbox)

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


def _styled_runs_from_line(line: TextLineBBox, line_index: int) -> list[StyledTextRun]:
    runs = [
        StyledTextRun(
            text=span.text,
            font_size=round(float(span.font_size), 2),
            bold=bool(span.bold),
            italic=bool(span.italic),
            color=span.color,
            font=span.font,
            bbox=list(span.bbox),
            line_index=line_index,
            baseline=(float(span.origin[1]) if span.origin and len(span.origin) >= 2 else None),
        )
        for span in line.spans
        if span.text.strip()
    ]
    if runs:
        return _dedupe_styled_runs(runs)
    if not line.text.strip():
        return []
    return [StyledTextRun(
        text=line.text,
        font_size=round(float(line.font_size), 2),
        bold=bool(line.bold),
        italic=bool(line.italic),
        color=line.color,
        bbox=list(line.bbox),
        line_index=line_index,
        baseline=float(line.bbox[3]),
    )]


def _classify_line_style(
    line: TextLineBBox,
    runs: list[StyledTextRun],
    context: PageContext,
) -> tuple[FontRole, SemanticRole]:
    size = _weighted_avg_font_size(runs)
    y0, y1 = float(line.bbox[1]), float(line.bbox[3])
    text = "".join(run.text for run in runs).strip()
    if y1 <= context.page_height * 0.085 and abs(float(line.angle or 0.0)) < 1.0:
        return FontRole.RUNNING_HEADER, SemanticRole.HEADER
    if y0 >= context.page_height * 0.90 and text.isdigit():
        return FontRole.FOOTER, SemanticRole.FOOTER
    if size >= context.max_font_size * 0.85 and size >= context.median_font_size * 1.55:
        return FontRole.DISPLAY, SemanticRole.TITLE
    if _has_accent_heading_color(runs):
        return FontRole.SECTION, SemanticRole.SUBTITLE
    if (
        any(run.bold for run in runs)
        and re.fullmatch(
            r"(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|"
            r"SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d{1,2}"
            r"(?:\s+\([^)]+\))?",
            text,
            flags=re.IGNORECASE,
        )
    ):
        return FontRole.SUBSECTION, SemanticRole.SUBTITLE
    if size >= context.median_font_size * 1.75:
        return FontRole.SECTION, SemanticRole.SUBTITLE
    if (
        size >= context.median_font_size * 1.15
        and len(text) <= 72
        and any(run.bold for run in runs)
    ):
        center_x = (float(line.bbox[0]) + float(line.bbox[2])) / 2
        if (
            y0 >= context.page_height * 0.75
            and abs(center_x - context.page_width / 2) <= context.page_width * 0.10
        ):
            return FontRole.CALLOUT, SemanticRole.SUBTITLE
        return FontRole.SUBSECTION, SemanticRole.SUBTITLE
    return FontRole.BODY, SemanticRole.BODY_COLUMN


def _starts_new_segment(
    current: list[dict],
    next_spec: dict,
    body_x0: float,
    body_font_size: float,
) -> bool:
    previous = current[-1]
    if next_spec["font_role"] != previous["font_role"]:
        return True
    if next_spec["role"] != previous["role"]:
        return True
    if next_spec["font_role"] != FontRole.BODY:
        return True

    current_x0 = float(next_spec["line"].bbox[0])
    if current_x0 - body_x0 >= body_font_size * 0.8:
        return True
    advances = [
        float(current[index]["line"].bbox[1]) - float(current[index - 1]["line"].bbox[1])
        for index in range(1, len(current))
        if float(current[index]["line"].bbox[1]) > float(current[index - 1]["line"].bbox[1])
    ]
    expected = median(advances) if advances else max(body_font_size * 1.35, 1.0)
    actual = float(next_spec["line"].bbox[1]) - float(previous["line"].bbox[1])
    return actual > expected * 1.35


def _union_bboxes(bboxes: list[list[float]]) -> list[float]:
    if not bboxes:
        raise ValueError("无法合并空 bbox 列表")
    return [
        min(float(bbox[0]) for bbox in bboxes),
        min(float(bbox[1]) for bbox in bboxes),
        max(float(bbox[2]) for bbox in bboxes),
        max(float(bbox[3]) for bbox in bboxes),
    ]


def _column_id_for_bbox(
    bbox: list[float],
    page_width: float,
    gutter_x: float | None,
    font_role: FontRole,
) -> str | None:
    if font_role in {
        FontRole.DISPLAY,
        FontRole.RUNNING_HEADER,
        FontRole.FOOTER,
        FontRole.CALLOUT,
        FontRole.TABLE,
    }:
        return None
    center_x = (bbox[0] + bbox[2]) / 2
    if font_role == FontRole.SUBSECTION and abs(center_x - page_width / 2) <= page_width * 0.08:
        return None
    if gutter_x is None or bbox[2] - bbox[0] >= page_width * 0.65:
        return None
    return "left" if center_x < gutter_x else "right"


def _median_line_advance(group: list[dict]) -> float | None:
    advances = [
        float(group[index]["line"].bbox[1]) - float(group[index - 1]["line"].bbox[1])
        for index in range(1, len(group))
        if float(group[index]["line"].bbox[1]) > float(group[index - 1]["line"].bbox[1])
    ]
    return round(float(median(advances)), 3) if advances else None


def _dominant_font(runs: list[StyledTextRun]) -> str | None:
    weights: dict[str, int] = {}
    for run in runs:
        if run.font and run.text.strip():
            weights[run.font] = weights.get(run.font, 0) + len(run.text.strip())
    if not weights:
        return None
    return max(weights, key=weights.get)


def _dedupe_overprinted_blocks(blocks: list[ContentBlock]) -> list[ContentBlock]:
    result: list[ContentBlock] = []
    for block in blocks:
        normalized = "".join(block.source_text.split())
        duplicate = False
        for kept in result:
            if "".join(kept.source_text.split()) != normalized:
                continue
            if not block.bbox or not kept.bbox:
                continue
            if all(abs(float(a) - float(b)) <= 0.5 for a, b in zip(block.bbox, kept.bbox)):
                duplicate = True
                break
        if not duplicate:
            result.append(block)
    return result


def _has_accent_heading_color(runs: list[StyledTextRun]) -> bool:
    return any(
        run.text.strip() and run.color.lower() in {"#ed1c24", "#dc2527", "#eb4f24"}
        for run in runs
    )


def _short_styled_heading(
    region: TextRegionBBox,
    page_context: PageContext,
    runs: list[StyledTextRun],
) -> bool:
    text = "".join(run.text for run in runs).strip()
    if not text or "\n" in text:
        return False
    avg_font_size = _weighted_avg_font_size(runs)
    x0, _, x1, _ = region.bbox
    width = x1 - x0
    if width > page_context.page_width * 0.55:
        return False
    has_style = any(run.bold or run.italic for run in runs)
    return has_style and len(text) <= 48 and avg_font_size >= page_context.median_font_size * 1.1


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
    if not any(ch.isalpha() for ch in stripped):
        return True
    return False


def _same_text_style(a: StyledTextRun, b: StyledTextRun) -> bool:
    return (
        a.text == b.text
        and abs(a.font_size - b.font_size) < 0.01
        and a.bold == b.bold
        and a.italic == b.italic
        and a.font == b.font
        and a.bbox == b.bbox
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


def _region_inside_table_grid(
    region: TextRegionBBox,
    page_structure: PageStructure,
) -> bool:
    """Return True when a text region sits on a DG-style shaded table grid."""
    structured_bounds = _structured_table_grid_bounds(page_structure)
    if structured_bounds is not None:
        return _region_center_inside_bounds(region, structured_bounds, 4.0)

    if _page_has_dense_line_grid(page_structure):
        grid_lines = [
            decoration
            for decoration in page_structure.decorations
            if _is_table_grid_line(decoration)
        ]
        return _region_center_inside_decoration_bounds(region, grid_lines)

    table_rects = [
        decoration
        for decoration in page_structure.decorations
        if _is_table_grid_decoration(decoration)
    ]
    if len(table_rects) < 6:
        return False

    grid_x0 = min(decoration.bbox[0] for decoration in table_rects)
    grid_y0 = min(decoration.bbox[1] for decoration in table_rects)
    grid_x1 = max(decoration.bbox[2] for decoration in table_rects)
    grid_y1 = max(decoration.bbox[3] for decoration in table_rects)

    return _region_center_inside_bounds(region, [grid_x0, grid_y0, grid_x1, grid_y1], 4.0)


def _structured_table_grid_bounds(page_structure: PageStructure) -> list[float] | None:
    """Locate a PDF-native table made from repeated filled quadrilateral cells."""
    bands = []
    for decoration in page_structure.decorations:
        commands = decoration.path_commands or []
        if decoration.element_type != "line" or len(commands) < 24:
            continue
        if decoration.stroke_color or decoration.fill_color:
            continue
        if any(command[0] != "l" for command in commands if command):
            continue
        bands.append(decoration)
    if len(bands) < 28:
        return None
    bounds = [
        min(item.bbox[0] for item in bands),
        min(item.bbox[1] for item in bands),
        max(item.bbox[2] for item in bands),
        max(item.bbox[3] for item in bands),
    ]
    if bounds[2] - bounds[0] < page_structure.width * 0.50:
        return None
    if not 20.0 <= bounds[3] - bounds[1] <= page_structure.height * 0.50:
        return None

    border_lines = [
        item for item in page_structure.decorations
        if _is_table_grid_line(item)
        and item.bbox[2] >= bounds[0] - 4.0
        and item.bbox[0] <= bounds[2] + 4.0
        and item.bbox[1] <= bounds[3] + 40.0
        and item.bbox[3] >= bounds[1] - 4.0
    ]
    if border_lines:
        bounds[0] = min(bounds[0], min(item.bbox[0] for item in border_lines))
        bounds[2] = max(bounds[2], max(item.bbox[2] for item in border_lines))
        bounds[3] = max(bounds[3], max(item.bbox[3] for item in border_lines))
    return bounds


def _coalesce_structured_table_cells(
    blocks: list[ContentBlock],
    page_structure: PageStructure,
) -> list[ContentBlock]:
    """Join wrapped PDF text fragments into complete cells before translation."""
    result: list[ContentBlock] = []
    segment: list[ContentBlock] = []
    for block in blocks:
        if block.role == SemanticRole.TABLE:
            segment.append(block)
            continue
        if segment:
            result.extend(_coalesce_structured_table_segment(segment))
            segment = []
        result.append(block)
    if segment:
        result.extend(_coalesce_structured_table_segment(segment))
    return result


def _coalesce_structured_table_segment(
    table_blocks: list[ContentBlock],
) -> list[ContentBlock]:
    groups: list[list[ContentBlock]] = []
    by_region: dict[str, list[ContentBlock]] = {}
    for block in table_blocks:
        if block.region_id not in by_region:
            by_region[block.region_id] = []
            groups.append(by_region[block.region_id])
        by_region[block.region_id].append(block)
    for group in groups:
        group.sort(key=lambda item: (item.bbox or [0.0, 0.0, 0.0, 0.0])[0])

    column_count = max((len(group) for group in groups), default=0)
    if column_count < 2:
        return table_blocks
    anchor_index = next(index for index, group in enumerate(groups) if len(group) == column_count)
    anchors = groups[anchor_index]
    centers = [((block.bbox or [0.0, 0.0, 0.0, 0.0])[0] + (block.bbox or [0.0, 0.0, 0.0, 0.0])[2]) / 2 for block in anchors]
    table_x0 = min((block.bbox or [0.0, 0.0, 0.0, 0.0])[0] for block in anchors)
    table_x1 = max((block.bbox or [0.0, 0.0, 0.0, 0.0])[2] for block in anchors)

    rebuilt = [block for group in groups[:anchor_index] for block in group]
    current: list[ContentBlock | None] | None = None
    current_region = ""
    for group in groups[anchor_index:]:
        first = group[0]
        first_bbox = first.bbox or [0.0, 0.0, 0.0, 0.0]
        if (
            len(group) == 1
            and first_bbox[2] - first_bbox[0] >= (table_x1 - table_x0) * 0.5
        ):
            if current is not None:
                rebuilt.extend(block for block in current if block is not None)
            current = None
            rebuilt.extend(group)
            continue

        assignments = [
            (
                min(
                    range(column_count),
                    key=lambda index: abs(
                        ((block.bbox or [0.0, 0.0, 0.0, 0.0])[0] + (block.bbox or [0.0, 0.0, 0.0, 0.0])[2]) / 2
                        - centers[index]
                    ),
                ),
                block,
            )
            for block in group
        ]
        if any(column == 0 for column, _ in assignments):
            if current is not None:
                rebuilt.extend(block for block in current if block is not None)
            current = [None] * column_count
            current_region = first.region_id
        if current is None:
            raise ValueError(f"表格续行缺少起始单元格：{first.region_id}")
        for column, block in assignments:
            existing = current[column]
            if existing is None:
                current[column] = replace(block, region_id=current_region)
                continue
            current[column] = replace(
                existing,
                runs=[*existing.runs, *block.runs],
                source_text=_join_source_cell_text(existing.source_text, block.source_text),
                bbox=_union_bboxes([existing.bbox, block.bbox]),
                line_ids=[*existing.line_ids, *block.line_ids],
                translatable=existing.translatable or block.translatable,
            )
    if current is not None:
        rebuilt.extend(block for block in current if block is not None)

    return rebuilt


def _join_source_cell_text(previous: str, current: str) -> str:
    previous = previous.strip()
    current = current.strip()
    if not previous:
        return current
    if not current:
        return previous
    return f"{previous} {current}"


def _region_center_inside_decoration_bounds(
    region: TextRegionBBox,
    decorations: list[DecorationElement],
) -> bool:
    if not decorations:
        return False
    grid_x0 = min(decoration.bbox[0] for decoration in decorations)
    grid_y0 = min(decoration.bbox[1] for decoration in decorations)
    grid_x1 = max(decoration.bbox[2] for decoration in decorations)
    grid_y1 = max(decoration.bbox[3] for decoration in decorations)
    return _region_center_inside_bounds(region, [grid_x0, grid_y0, grid_x1, grid_y1], 4.0)


def _region_center_inside_bounds(
    region: TextRegionBBox,
    bounds: list[float],
    tolerance: float,
) -> bool:
    x0, y0, x1, y1 = region.bbox
    center_x = (x0 + x1) / 2
    center_y = (y0 + y1) / 2
    grid_x0, grid_y0, grid_x1, grid_y1 = bounds
    return (
        grid_x0 - tolerance <= center_x <= grid_x1 + tolerance
        and grid_y0 - tolerance <= center_y <= grid_y1 + tolerance
    )


def _page_has_dense_line_grid(page_structure: PageStructure) -> bool:
    grid_lines = [
        decoration
        for decoration in page_structure.decorations
        if _is_table_grid_line(decoration)
    ]
    return len(grid_lines) >= 80


def _is_table_grid_line(decoration: DecorationElement) -> bool:
    if decoration.element_type != "line" or len(decoration.bbox) != 4:
        return False
    if (decoration.stroke_color or "").lower() != "#000000":
        return False
    x0, y0, x1, y1 = decoration.bbox
    width = abs(x1 - x0)
    height = abs(y1 - y0)
    return width >= 8.0 or height >= 8.0


def _is_table_grid_decoration(decoration: DecorationElement) -> bool:
    if decoration.element_type != "rect" or len(decoration.bbox) != 4:
        return False
    fill = (decoration.fill_color or "").lower()
    if fill not in {"#d1d2d4", "#000000"}:
        return False
    x0, y0, x1, y1 = decoration.bbox
    width = x1 - x0
    height = y1 - y0
    return width >= 20.0 and 8.0 <= height <= 32.0


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
