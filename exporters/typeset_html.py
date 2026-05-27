"""
Typeset HTML rebuilder for the pure-reflow pipeline.

Rebuilds each PDF page from scratch as HTML/CSS, placing background, images,
decorations, and reflowed Chinese text in proper z-order layers. The output
is a complete HTML document ready for Playwright PDF export.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from core.typeset_models import (
    BackgroundLayer,
    ContentBlock,
    DecorationElement,
    ImageElement,
    PageContent,
    PageContentDocument,
    PageStructure,
    PageStructureDocument,
    PageType,
    SemanticRole,
    TypesetConfig,
)

# PDF points → CSS pixels conversion factor (96 DPI / 72 DPI)
CSS_PX_PER_PT = 96.0 / 72.0

# z-index layer constants
Z_BACKGROUND = 1
Z_IMAGES = 2
Z_DECORATIONS = 3
Z_TEXT = 4


def _pt_to_px(value: float) -> float:
    """Convert PDF points to CSS pixels."""
    return value * CSS_PX_PER_PT


def _px(value: float) -> str:
    """Format a CSS pixel value."""
    return f"{value:.3f}px"


def _pt_to_px_str(value: float) -> str:
    """Convert PDF points to CSS pixel string."""
    return _px(_pt_to_px(value))


class TypesetHTMLRebuilder:
    """HTML/CSS page rebuilder for the typeset reflow pipeline."""

    def __init__(self, config: TypesetConfig | None = None):
        """
        Initialize the rebuilder with typeset configuration.

        Args:
            config: Typeset configuration (fonts, line height, etc.).
                    Uses defaults if None.
        """
        self.config = config or TypesetConfig()

    def _font_stack(self) -> str:
        """Build the CSS font-family string from config."""
        fonts = [f'"{self.config.font_family}"']
        for fallback in self.config.fallback_fonts:
            if fallback in ("serif", "sans-serif", "monospace"):
                fonts.append(fallback)
            else:
                fonts.append(f'"{fallback}"')
        return ", ".join(fonts)

    def _body_font_size_px(self) -> float:
        """Get the body font size in CSS pixels, respecting minimum."""
        size_pt = max(self.config.body_font_size_pt, self.config.min_body_font_size_pt)
        return _pt_to_px(size_pt)

    def _min_font_size_px(self) -> float:
        """Get the minimum font size in CSS pixels."""
        return _pt_to_px(self.config.min_body_font_size_pt)

    def _is_heading(self, font_size_pt: float) -> bool:
        """Check if a font size qualifies as a heading (>= 1.5x body size)."""
        return font_size_pt >= 1.5 * self.config.body_font_size_pt

    def _heading_level(self, font_size_pt: float) -> str:
        """Determine heading tag based on font size ratio to body."""
        ratio = font_size_pt / max(self.config.body_font_size_pt, 1.0)
        if ratio >= 2.0:
            return "h2"
        return "h3"

    def rebuild_document(
        self,
        structure: PageStructureDocument,
        content: PageContentDocument,
    ) -> str:
        """
        Rebuild the entire document as a complete HTML string.

        Args:
            structure: Page structure document with visual elements.
            content: Page content document with translated text.

        Returns:
            Complete HTML document string.
        """
        # Build page sections
        page_sections: list[str] = []
        content_map = {page.page_index: page for page in content.pages}

        for page_struct in structure.pages:
            page_content = content_map.get(page_struct.page_index)
            if page_content is None:
                # Create empty page content if missing
                page_content = PageContent(
                    page_index=page_struct.page_index,
                    page_type=PageType.SINGLE,
                    columns=[],
                    blocks=[],
                )
            page_sections.append(self.rebuild_page(page_struct, page_content))

        # Determine page size from first page for @page rule
        if structure.pages:
            first = structure.pages[0]
            page_width_in = first.width / 72.0
            page_height_in = first.height / 72.0
        else:
            page_width_in = 8.5
            page_height_in = 11.0

        css = self._build_global_css(page_width_in, page_height_in)

        parts = [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{html.escape(structure.source_pdf)} typeset</title>",
            f"<style>{css}</style>",
            "</head>",
            "<body>",
        ]
        parts.extend(page_sections)
        parts.extend([
            "</body>",
            "</html>",
        ])
        return "\n".join(parts)

    def _build_global_css(self, page_width_in: float, page_height_in: float) -> str:
        """Build the global CSS stylesheet."""
        font_stack = self._font_stack()
        body_font_px = self._body_font_size_px()
        min_font_px = self._min_font_size_px()
        line_height = self.config.line_height
        text_indent = self.config.text_indent
        column_gap_px = _pt_to_px(self.config.column_gap_pt)

        return f"""
* {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}}
body {{
    margin: 0;
    padding: 24px;
    background: #444;
    font-family: {font_stack};
    font-size: {body_font_px:.3f}px;
    line-height: {line_height};
}}
.typeset-page {{
    position: relative;
    overflow: hidden;
    margin: 0 auto 24px;
    background: #fff;
    box-shadow: 0 3px 18px rgba(0, 0, 0, 0.35);
    page-break-after: always;
}}
.typeset-bg-layer {{
    position: absolute;
    inset: 0;
    z-index: {Z_BACKGROUND};
}}
.typeset-image-layer {{
    position: absolute;
    inset: 0;
    z-index: {Z_IMAGES};
    pointer-events: none;
}}
.typeset-image {{
    position: absolute;
    display: block;
}}
.typeset-decoration-layer {{
    position: absolute;
    inset: 0;
    z-index: {Z_DECORATIONS};
    pointer-events: none;
}}
.typeset-decoration {{
    position: absolute;
}}
.typeset-text-layer {{
    position: absolute;
    inset: 0;
    z-index: {Z_TEXT};
}}
.typeset-columns {{
    display: flex;
    gap: {column_gap_px:.3f}px;
    height: 100%;
    padding: 0;
}}
.typeset-column {{
    flex: 1;
    overflow: hidden;
}}
.typeset-single {{
    height: 100%;
    padding: 0;
    overflow: hidden;
}}
.typeset-cover {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    text-align: center;
    padding: 10%;
}}
.typeset-body-text {{
    font-size: {body_font_px:.3f}px;
    line-height: {line_height};
    text-indent: {text_indent};
    word-wrap: break-word;
    overflow-wrap: break-word;
    white-space: normal;
    margin-bottom: 0.4em;
}}
.typeset-heading {{
    font-weight: bold;
    line-height: 1.3;
    margin: 0.6em 0 0.3em 0;
    text-indent: 0;
    word-wrap: break-word;
    overflow-wrap: break-word;
    white-space: normal;
}}
.typeset-heading:first-child {{
    margin-top: 0;
}}
.typeset-cover .typeset-heading {{
    margin: 0.3em 0;
}}
.typeset-cover .typeset-body-text {{
    text-indent: 0;
    text-align: center;
}}
@page {{
    size: {page_width_in:.6f}in {page_height_in:.6f}in;
    margin: 0;
}}
@media print {{
    body {{
        padding: 0;
        background: #fff;
    }}
    .typeset-page {{
        margin: 0;
        box-shadow: none;
    }}
}}
"""

    def rebuild_page(
        self,
        page_structure: PageStructure,
        page_content: PageContent,
    ) -> str:
        """
        Rebuild a single page as an HTML section.

        Args:
            page_structure: Page structure with visual elements.
            page_content: Page content with translated text blocks.

        Returns:
            HTML string for the page section.
        """
        width_px = _pt_to_px(page_structure.width)
        height_px = _pt_to_px(page_structure.height)

        parts: list[str] = []
        parts.append(
            f'<section class="typeset-page" '
            f'data-page="{page_structure.page_index + 1}" '
            f'style="width:{_px(width_px)};height:{_px(height_px)}">'
        )

        # Render layers in z-order
        parts.append(self.render_background_layer(page_structure.background))
        parts.append(self.render_image_layer(page_structure.images))
        parts.append(self.render_decoration_layer(page_structure.decorations))
        parts.append(self.render_text_layer(page_content))

        parts.append("</section>")
        return "\n".join(parts)

    def render_background_layer(self, background: BackgroundLayer) -> str:
        """
        Render the background layer HTML.

        Args:
            background: Background layer data.

        Returns:
            HTML string for the background layer div.
        """
        styles: list[str] = []
        if background.color:
            styles.append(f"background-color:{background.color}")
        if background.gradient:
            styles.append(f"background:{background.gradient}")

        style_attr = ";".join(styles) if styles else ""
        if style_attr:
            return f'<div class="typeset-bg-layer" style="{style_attr}"></div>'
        return '<div class="typeset-bg-layer"></div>'

    def render_image_layer(self, images: list[ImageElement]) -> str:
        """
        Render the image layer HTML, placing images at original coordinates.

        Args:
            images: List of image elements with bounding boxes.

        Returns:
            HTML string for the image layer.
        """
        if not images:
            return '<div class="typeset-image-layer"></div>'

        parts: list[str] = ['<div class="typeset-image-layer">']
        for img in images:
            x0, y0, x1, y1 = img.bbox
            left = _pt_to_px(x0)
            top = _pt_to_px(y0)
            width = _pt_to_px(x1 - x0)
            height = _pt_to_px(y1 - y0)
            parts.append(
                f'<img class="typeset-image" '
                f'src="{html.escape(img.image_path)}" '
                f'alt="" '
                f'data-image-id="{html.escape(img.id)}" '
                f'style="left:{_px(left)};top:{_px(top)};'
                f'width:{_px(width)};height:{_px(height)}">'
            )
        parts.append("</div>")
        return "\n".join(parts)

    def render_decoration_layer(self, decorations: list[DecorationElement]) -> str:
        """
        Render the decoration layer HTML (CSS borders or SVG).

        Args:
            decorations: List of decoration elements.

        Returns:
            HTML string for the decoration layer.
        """
        if not decorations:
            return '<div class="typeset-decoration-layer"></div>'

        parts: list[str] = ['<div class="typeset-decoration-layer">']
        for dec in decorations:
            parts.append(self._render_single_decoration(dec))
        parts.append("</div>")
        return "\n".join(parts)

    def _render_single_decoration(self, dec: DecorationElement) -> str:
        """Render a single decoration element."""
        x0, y0, x1, y1 = dec.bbox
        left = _pt_to_px(x0)
        top = _pt_to_px(y0)
        width = _pt_to_px(x1 - x0)
        height = _pt_to_px(y1 - y0)
        stroke_width_px = _pt_to_px(dec.stroke_width)

        if dec.element_type == "path" and dec.points:
            # Render as SVG for complex paths
            return self._render_svg_path(dec, left, top, width, height)
        elif dec.element_type == "line":
            return self._render_css_line(dec, left, top, width, height, stroke_width_px)
        else:
            # rect or fallback
            return self._render_css_rect(dec, left, top, width, height, stroke_width_px)

    def _render_svg_path(
        self, dec: DecorationElement, left: float, top: float, width: float, height: float
    ) -> str:
        """Render a path decoration as SVG."""
        x0, y0 = dec.bbox[0], dec.bbox[1]
        stroke_color = dec.stroke_color or "transparent"
        fill_color = dec.fill_color or "none"
        stroke_width_px = _pt_to_px(dec.stroke_width)

        # Build SVG path data from points
        path_data = ""
        if dec.points:
            for i, point in enumerate(dec.points):
                px = _pt_to_px(point[0] - x0)
                py = _pt_to_px(point[1] - y0)
                cmd = "M" if i == 0 else "L"
                path_data += f"{cmd}{px:.3f},{py:.3f} "

        return (
            f'<svg class="typeset-decoration" '
            f'data-dec-id="{html.escape(dec.id)}" '
            f'style="left:{_px(left)};top:{_px(top)};'
            f'width:{_px(width)};height:{_px(height)}" '
            f'viewBox="0 0 {width:.3f} {height:.3f}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<path d="{path_data.strip()}" '
            f'stroke="{html.escape(stroke_color)}" '
            f'stroke-width="{stroke_width_px:.3f}" '
            f'fill="{html.escape(fill_color)}"/>'
            f"</svg>"
        )

    def _render_css_line(
        self, dec: DecorationElement, left: float, top: float,
        width: float, height: float, stroke_width_px: float
    ) -> str:
        """Render a line decoration as a CSS border element."""
        stroke_color = dec.stroke_color or "#000"
        # For lines, use border-bottom on a thin div
        border_style = f"{max(stroke_width_px, 1.0):.3f}px solid {stroke_color}"

        if width >= height:
            # Horizontal line
            return (
                f'<div class="typeset-decoration" '
                f'data-dec-id="{html.escape(dec.id)}" '
                f'style="left:{_px(left)};top:{_px(top)};'
                f'width:{_px(width)};height:0;'
                f'border-bottom:{border_style}"></div>'
            )
        else:
            # Vertical line
            return (
                f'<div class="typeset-decoration" '
                f'data-dec-id="{html.escape(dec.id)}" '
                f'style="left:{_px(left)};top:{_px(top)};'
                f'width:0;height:{_px(height)};'
                f'border-left:{border_style}"></div>'
            )

    def _render_css_rect(
        self, dec: DecorationElement, left: float, top: float,
        width: float, height: float, stroke_width_px: float
    ) -> str:
        """Render a rect decoration as a CSS border element."""
        stroke_color = dec.stroke_color or "#000"
        fill_color = dec.fill_color or "transparent"
        border_style = f"{max(stroke_width_px, 1.0):.3f}px solid {stroke_color}"

        return (
            f'<div class="typeset-decoration" '
            f'data-dec-id="{html.escape(dec.id)}" '
            f'style="left:{_px(left)};top:{_px(top)};'
            f'width:{_px(width)};height:{_px(height)};'
            f'border:{border_style};'
            f'background:{fill_color}"></div>'
        )

    def render_text_layer(self, page_content: PageContent) -> str:
        """
        Render the text layer HTML based on page type.

        Args:
            page_content: Page content with text blocks.

        Returns:
            HTML string for the text layer.
        """
        parts: list[str] = ['<div class="typeset-text-layer">']

        if page_content.page_type == PageType.COLUMNS:
            parts.append(self._render_columns_page(page_content))
        elif page_content.page_type == PageType.COVER:
            parts.append(self._render_cover_page(page_content))
        elif page_content.page_type == PageType.ART:
            parts.append(self._render_art_page(page_content))
        else:
            # SINGLE or MIXED
            parts.append(self.render_single_layout(page_content.blocks))

        parts.append("</div>")
        return "\n".join(parts)

    def _render_columns_page(self, page_content: PageContent) -> str:
        """Render a columns page with dual-column layout."""
        if not page_content.columns or len(page_content.columns) < 2:
            # Fallback to single layout if columns info is missing
            return self.render_single_layout(page_content.blocks)

        # Build block lookup
        block_map = {b.id: b for b in page_content.blocks}

        # Separate blocks into left and right columns
        left_col_blocks: list[ContentBlock] = []
        right_col_blocks: list[ContentBlock] = []

        for col in page_content.columns:
            col_blocks = [block_map[bid] for bid in col.block_ids if bid in block_map]
            if col.side == "left":
                left_col_blocks = col_blocks
            elif col.side == "right":
                right_col_blocks = col_blocks

        return self.render_column_layout(left_col_blocks, right_col_blocks)

    def _render_cover_page(self, page_content: PageContent) -> str:
        """Render a cover page with centered large text."""
        parts: list[str] = ['<div class="typeset-cover">']
        for block in page_content.blocks:
            parts.append(self._render_block(block, is_cover=True))
        parts.append("</div>")
        return "\n".join(parts)

    def _render_art_page(self, page_content: PageContent) -> str:
        """Render an art page with minimal text."""
        # Art pages have mostly images; render any text blocks simply
        if not page_content.blocks:
            return ""
        parts: list[str] = ['<div class="typeset-single">']
        for block in page_content.blocks:
            parts.append(self._render_block(block))
        parts.append("</div>")
        return "\n".join(parts)

    def render_column_layout(
        self, left_col: list[ContentBlock], right_col: list[ContentBlock]
    ) -> str:
        """
        Render dual-column CSS layout.

        Args:
            left_col: Content blocks for the left column.
            right_col: Content blocks for the right column.

        Returns:
            HTML string for the dual-column layout.
        """
        parts: list[str] = ['<div class="typeset-columns">']

        # Left column
        parts.append('<div class="typeset-column">')
        for block in left_col:
            parts.append(self._render_block(block))
        parts.append("</div>")

        # Right column
        parts.append('<div class="typeset-column">')
        for block in right_col:
            parts.append(self._render_block(block))
        parts.append("</div>")

        parts.append("</div>")
        return "\n".join(parts)

    def render_single_layout(self, blocks: list[ContentBlock]) -> str:
        """
        Render single-column CSS layout.

        Args:
            blocks: Content blocks for the single column.

        Returns:
            HTML string for the single-column layout.
        """
        parts: list[str] = ['<div class="typeset-single">']
        for block in blocks:
            parts.append(self._render_block(block))
        parts.append("</div>")
        return "\n".join(parts)

    def _render_block(self, block: ContentBlock, is_cover: bool = False) -> str:
        """Render a single content block as HTML."""
        # Determine the text to display
        text = block.translated_text if block.translated_text else block.source_text
        if not text:
            return ""

        # Determine font size from runs
        block_font_size_pt = self._get_block_font_size(block)

        # Check if this is a heading
        if self._is_heading(block_font_size_pt) or block.role == SemanticRole.TITLE:
            return self._render_heading_block(block, text, block_font_size_pt)
        else:
            return self._render_body_block(block, text, block_font_size_pt)

    def _get_block_font_size(self, block: ContentBlock) -> float:
        """Get the representative font size for a block (median of runs)."""
        if not block.runs:
            return self.config.body_font_size_pt
        sizes = sorted(run.font_size for run in block.runs if run.font_size > 0)
        if not sizes:
            return self.config.body_font_size_pt
        return sizes[len(sizes) // 2]

    def _render_heading_block(
        self, block: ContentBlock, text: str, font_size_pt: float
    ) -> str:
        """Render a block as a heading element."""
        tag = self._heading_level(font_size_pt)
        font_size_px = _pt_to_px(font_size_pt)
        # Ensure minimum font size
        font_size_px = max(font_size_px, self._min_font_size_px())
        escaped_text = self._format_text(text)

        return (
            f'<{tag} class="typeset-heading" '
            f'data-block-id="{html.escape(block.id)}" '
            f'style="font-size:{_px(font_size_px)}">'
            f"{escaped_text}"
            f"</{tag}>"
        )

    def _render_body_block(
        self, block: ContentBlock, text: str, font_size_pt: float
    ) -> str:
        """Render a block as a body paragraph."""
        font_size_px = _pt_to_px(font_size_pt)
        # Enforce minimum font size
        font_size_px = max(font_size_px, self._min_font_size_px())
        escaped_text = self._format_text(text)

        style_parts: list[str] = []
        # Only add font-size if different from body default
        body_px = self._body_font_size_px()
        if abs(font_size_px - body_px) > 0.1:
            style_parts.append(f"font-size:{_px(font_size_px)}")

        style_attr = f' style="{";".join(style_parts)}"' if style_parts else ""

        return (
            f'<p class="typeset-body-text" '
            f'data-block-id="{html.escape(block.id)}"'
            f"{style_attr}>"
            f"{escaped_text}"
            f"</p>"
        )

    def _format_text(self, text: str) -> str:
        """Format text for HTML output, preserving line breaks."""
        lines = text.splitlines() or [text]
        return "<br>".join(html.escape(line) for line in lines)
