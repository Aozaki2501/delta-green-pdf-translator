"""
Typeset HTML rebuilder for the pure-reflow pipeline.

Rebuilds each PDF page from scratch as HTML/CSS, placing background, images,
decorations, and reflowed Chinese text in proper z-order layers. The output
is a complete HTML document ready for Playwright PDF export.
"""

from __future__ import annotations

import html
import re
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
    TextRegionBBox,
    TypesetConfig,
)
from core.typeset_templates import select_typeset_template

# PDF points → CSS pixels conversion factor (96 DPI / 72 DPI)
CSS_PX_PER_PT = 96.0 / 72.0

# z-index layer constants
Z_BACKGROUND = 1
Z_DECORATIONS = 2
Z_IMAGES = 3
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


def _same_text_flow(previous: list[float], current: list[float]) -> bool:
    """Return True when two text boxes belong to the same vertical text flow."""
    px0, py0, px1, py1 = previous
    cx0, cy0, cx1, cy1 = current
    horizontal_overlap = max(0.0, min(px1, cx1) - max(px0, cx0))
    narrower_width = max(1.0, min(px1 - px0, cx1 - cx0))
    if horizontal_overlap / narrower_width < 0.45:
        return False
    vertical_gap = cy0 - py1
    return -18.0 <= vertical_gap <= 18.0


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


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

    def _heading_font_stack(self) -> str:
        fonts = [f'"{self.config.heading_font_family}"']
        for fallback in self.config.heading_fallback_fonts:
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
        parts.append(self._build_fit_script())
        parts.extend([
            "</body>",
            "</html>",
        ])
        return "\n".join(parts)

    def _build_fit_script(self) -> str:
        """Build deterministic text fitting for fixed PDF text boxes."""
        return """
<script>
function typesetFitPositionedBlocks() {
  typesetFlowLineTracks();
  const boxes = document.querySelectorAll('.typeset-positioned-block[data-fit="text"]');
  for (const box of boxes) {
    const child = box.firstElementChild;
    if (!child) continue;
    let size = parseFloat(getComputedStyle(child).fontSize) || 12;
    const minSize = 6;
    let guard = 0;
    while (
      guard < 80 &&
      size > minSize &&
      (box.scrollHeight > box.clientHeight + 1 || box.scrollWidth > box.clientWidth + 1)
    ) {
      size = Math.max(minSize, size - 0.5);
      for (const item of box.children) {
        item.style.fontSize = size + 'px';
        item.style.lineHeight = '1.1';
      }
      guard += 1;
    }
  }
  const reflowAreas = document.querySelectorAll(
    '.typeset-reflow-area[data-fit="reflow"], .typeset-region-flow[data-fit="reflow"], .typeset-rotated-flow[data-fit="reflow"], .typeset-timeline-flow'
  );
  for (const area of reflowAreas) {
    let size = parseFloat(getComputedStyle(area).fontSize) || 14;
    const minSize = (
      area.classList.contains('typeset-rotated-flow') ||
      area.classList.contains('typeset-timeline-flow')
    ) ? 8 : 11;
    let guard = 0;
    while (
      guard < 80 &&
      size > minSize &&
      (area.scrollHeight > area.clientHeight + 1 || area.scrollWidth > area.clientWidth + 1)
    ) {
      size = Math.max(minSize, size - 0.5);
      area.style.fontSize = size + 'px';
      guard += 1;
    }
  }
}
function typesetFlowLineTracks() {
  const flows = document.querySelectorAll('.typeset-line-track-flow');
  for (const flow of flows) {
    const rawText = flow.dataset.flowText || '';
    const slots = Array.from(flow.querySelectorAll('.typeset-line-slot'));
    const tokens = typesetTokenizeFlowText(rawText);
    let cursor = 0;
    for (const slot of slots) {
      slot.textContent = '';
      if (cursor >= tokens.length) continue;
      let low = 0;
      let high = tokens.length - cursor;
      let best = 0;
      while (low <= high) {
        const mid = Math.floor((low + high) / 2);
        slot.textContent = tokens.slice(cursor, cursor + mid).join('');
        if (slot.scrollWidth <= slot.clientWidth + 1 && slot.scrollHeight <= slot.clientHeight + 1) {
          best = mid;
          low = mid + 1;
        } else {
          high = mid - 1;
        }
      }
      if (best <= 0) best = 1;
      slot.textContent = tokens.slice(cursor, cursor + best).join('');
      cursor += best;
    }
    flow.dataset.overflow = cursor < tokens.length ? 'true' : 'false';
  }
}
function typesetTokenizeFlowText(text) {
  const source = (text || '').replace(/\\s+/g, ' ').trim();
  if (!source) return [];
  if (/[\u4e00-\u9fff]/.test(source)) {
    const matches = source.match(/[\u4e00-\u9fff]|[^\u4e00-\u9fff\\s]+|\\s+/g) || [];
    return matches.map((item) => /^\\s+$/.test(item) ? ' ' : item);
  }
  const parts = source.split(/(\\s+)/).filter(Boolean);
  return parts.length ? parts : Array.from(source);
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', typesetFitPositionedBlocks);
} else {
  typesetFitPositionedBlocks();
}
</script>
"""

    def _build_global_css(self, page_width_in: float, page_height_in: float) -> str:
        """Build the global CSS stylesheet."""
        font_stack = self._font_stack()
        heading_font_stack = self._heading_font_stack()
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
.typeset-positioned-block {{
    position: absolute;
    overflow: hidden;
}}
.typeset-positioned-block .typeset-body-text {{
    margin: 0;
    line-height: 1.15;
    text-indent: 0;
}}
.typeset-positioned-block .typeset-heading {{
    margin: 0;
    line-height: 1.15;
    text-indent: 0;
}}
.typeset-reflow-area {{
    position: absolute;
    overflow: hidden;
    color: {self.config.body_color};
    font-size: {_pt_to_px(10.8):.3f}px;
}}
.typeset-reflow-columns {{
    display: flex;
    gap: {_pt_to_px(24.0):.3f}px;
    height: 100%;
}}
.typeset-reflow-column {{
    flex: 1;
    overflow: hidden;
}}
.typeset-reflow-title {{
    font-family: {heading_font_stack};
    font-size: 2em;
    line-height: 1.25;
    margin: 0 0 {_pt_to_px(8.0):.3f}px 0;
    text-align: center;
    font-weight: 700;
    text-indent: 0;
    color: {self.config.title_color};
}}
.typeset-reflow-subtitle {{
    font-family: {heading_font_stack};
    font-size: 1.37em;
    line-height: 1.25;
    margin: {_pt_to_px(10.0):.3f}px 0 {_pt_to_px(5.0):.3f}px 0;
    font-weight: 700;
    text-indent: 0;
    color: {self.config.subtitle_color};
}}
.typeset-reflow-body {{
    font-size: 1em;
    line-height: 1.58;
    margin: 0 0 0.18em 0;
    text-indent: 2em;
    text-align: left;
    word-break: normal;
    overflow-wrap: break-word;
}}
.typeset-region-flow {{
    position: absolute;
    overflow: hidden;
    color: {self.config.body_color};
    font-size: {body_font_px:.3f}px;
    line-height: {line_height};
}}
.typeset-region-flow .typeset-reflow-body {{
    line-height: {line_height};
}}
.typeset-region-flow .typeset-reflow-title {{
    margin: {_pt_to_px(10.0):.3f}px 0 {_pt_to_px(10.0):.3f}px 0;
}}
.typeset-rotated-flow {{
    position: absolute;
    overflow: hidden;
    font-size: {body_font_px:.3f}px;
    line-height: 1.35;
}}
.typeset-rotated-flow .typeset-reflow-title {{
    font-size: 1.7em;
    margin-bottom: {_pt_to_px(5.0):.3f}px;
}}
.typeset-rotated-flow .typeset-reflow-subtitle {{
    font-size: 1.28em;
    margin: 0 0 {_pt_to_px(4.0):.3f}px 0;
}}
.typeset-rotated-flow .typeset-reflow-body {{
    line-height: 1.35;
    margin-bottom: 0.25em;
    text-indent: 0;
}}
.typeset-timeline-intro {{
    position: absolute;
    overflow: hidden;
    font-size: {body_font_px:.3f}px;
    line-height: 1.35;
    color: {self.config.body_color};
}}
.typeset-timeline-flow {{
    position: absolute;
    overflow: hidden;
    column-gap: {_pt_to_px(18.0):.3f}px;
    font-size: {_pt_to_px(8.8):.3f}px;
    line-height: 1.28;
    color: {self.config.body_color};
}}
.typeset-timeline-event {{
    break-inside: avoid;
    margin: 0 0 {_pt_to_px(6.0):.3f}px 0;
    text-indent: 0;
}}
.typeset-line-track-flow {{
    position: absolute;
    inset: 0;
    color: {self.config.body_color};
}}
.typeset-line-slot {{
    position: absolute;
    overflow: hidden;
    white-space: nowrap;
    word-break: keep-all;
    text-indent: 0;
    font-size: {body_font_px:.3f}px;
    line-height: 1.18;
}}
.typeset-line-slot[data-bold="true"] {{
    font-weight: 700;
}}
.typeset-line-slot[data-italic="true"] {{
    font-style: italic;
}}
.typeset-source-span {{
    position: absolute;
    display: block;
    overflow: hidden;
    white-space: nowrap;
}}
.typeset-source-title {{
    font-family: {heading_font_stack};
    font-weight: 700;
    line-height: 1.18;
    text-indent: 0;
    color: {self.config.title_color};
}}
.typeset-source-subtitle {{
    font-family: {heading_font_stack};
    font-weight: 700;
    line-height: 1.2;
    text-indent: 0;
    color: {self.config.subtitle_color};
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
    font-family: {heading_font_stack};
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
        template = select_typeset_template(page_content, page_structure)

        parts: list[str] = []
        parts.append(
            f'<section class="typeset-page" '
            f'data-page="{page_structure.page_index + 1}" '
            f'data-template="{html.escape(template.id)}" '
            f'style="width:{_px(width_px)};height:{_px(height_px)}">'
        )

        # Render layers in z-order
        parts.append(self.render_background_layer(page_structure.background))
        parts.append(self.render_image_layer(page_structure.images))
        parts.append(self.render_decoration_layer(page_structure.decorations))
        parts.append(self.render_text_layer(page_content, page_structure))

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
            if img.transform:
                parts.append(self._render_transformed_image(img))
                continue
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

    def render_text_layer(
        self,
        page_content: PageContent,
        page_structure: PageStructure | None = None,
    ) -> str:
        """
        Render the text layer HTML based on page type.

        Args:
            page_content: Page content with text blocks.
            page_structure: Page structure with original text region boxes.

        Returns:
            HTML string for the text layer.
        """
        parts: list[str] = ['<div class="typeset-text-layer">']

        if page_structure is not None:
            self._current_template = select_typeset_template(page_content, page_structure)
            if self._should_reflow_chinese_page(page_content):
                parts.append(self._render_chinese_reflow_page(page_content, page_structure))
            else:
                parts.append(self._render_positioned_blocks(page_content, page_structure))
            parts.append("</div>")
            return "\n".join(parts)

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

    def _render_transformed_image(self, img: ImageElement) -> str:
        """Render an image with the original PDF transform matrix."""
        a, b, c, d, e, f = [float(v) for v in img.transform or [1, 0, 0, 1, 0, 0]]
        css_a = _pt_to_px(a) / max(1, img.width_px)
        css_b = _pt_to_px(b) / max(1, img.width_px)
        css_c = _pt_to_px(c) / max(1, img.height_px)
        css_d = _pt_to_px(d) / max(1, img.height_px)
        css_e = _pt_to_px(e)
        css_f = _pt_to_px(f)
        matrix = f"matrix({css_a:.9f},{css_b:.9f},{css_c:.9f},{css_d:.9f},{css_e:.3f},{css_f:.3f})"
        return (
            f'<img class="typeset-image" '
            f'src="{html.escape(img.image_path)}" '
            f'alt="" '
            f'data-image-id="{html.escape(img.id)}" '
            f'style="left:0;top:0;'
            f'width:{max(1, img.width_px)}px;height:{max(1, img.height_px)}px;'
            f'transform-origin:0 0;transform:{matrix}">'
        )

    def _should_reflow_chinese_page(self, page_content: PageContent) -> bool:
        if page_content.page_type in (PageType.ART, PageType.COVER):
            return False
        return any(_contains_cjk(block.translated_text or "") for block in page_content.blocks)

    def _render_chinese_reflow_page(
        self,
        page_content: PageContent,
        page_structure: PageStructure,
    ) -> str:
        """Render translated Chinese like a typeset text page."""
        region_map = {region.id: region.bbox for region in page_structure.text_regions}
        fixed_parts: list[str] = []
        rotated_blocks: list[ContentBlock] = []
        content_blocks: list[ContentBlock] = []
        page_blocks = self._dedupe_content_blocks(
            [block for block in page_content.blocks if block.region_id in region_map],
            region_map,
        )
        rotated_flow_count = sum(
            1
            for block in page_blocks
            if self._is_flow_body_block(block)
            and abs(self._region_angle(block.region_id, page_structure)) >= 1.0
        )

        for block in page_blocks:
            bbox = region_map.get(block.region_id)
            if bbox is None:
                continue
            if self._is_running_header(block):
                fixed_parts.append(self._render_running_header(block, page_structure, bbox))
                continue
            if self._is_fixed_page_number(block):
                fixed_parts.append(self._render_fixed_page_number(block, bbox))
                continue
            if block.role == SemanticRole.FOOTER:
                continue
            if block.role == SemanticRole.TITLE:
                fixed_parts.append(self._render_source_positioned_block(block, page_structure, bbox))
                continue
            if self._is_bottom_credit_block(block, bbox, page_structure):
                fixed_parts.append(self._render_source_positioned_block(block, page_structure, bbox))
                continue
            if self._should_position_light_foreground_block(block, bbox, page_structure):
                fixed_parts.append(self._render_source_positioned_block(block, page_structure, bbox))
                continue
            if abs(self._region_angle(block.region_id, page_structure)) >= 1.0:
                if self._is_flow_body_block(block) and rotated_flow_count >= 3:
                    if self._display_text_for_block(block):
                        rotated_blocks.append(block)
                elif self._display_text_for_block(block):
                    fixed_parts.append(self._render_positioned_single_block(block, page_structure, bbox))
                continue
            if (
                not self._display_text_for_block(block)
            ):
                continue
            content_blocks.append(block)

        fixed_parts.extend(
            self._render_rotated_reflow_groups(rotated_blocks, page_structure, region_map)
        )
        content_blocks = self._dedupe_content_blocks(content_blocks, region_map)
        content_blocks = sorted(
            content_blocks,
            key=lambda block: (region_map[block.region_id][1], region_map[block.region_id][0]),
        )
        if self._is_timeline_page(content_blocks):
            return "\n".join([
                self._render_timeline_page(content_blocks, region_map, page_structure),
                *fixed_parts,
            ])
        if self._is_centered_stack_page(content_blocks, region_map, page_structure):
            return "\n".join([
                *[
                    self._render_source_positioned_block(block, page_structure, region_map[block.region_id])
                    for block in content_blocks
                ],
                *fixed_parts,
            ])
        flow_items = self._build_reflow_items(content_blocks)
        if not flow_items:
            return "\n".join(fixed_parts)
        content_blocks = [block for block, _ in flow_items]
        text_by_id = {block.id: text for block, text in flow_items}

        source_region_html = self._render_source_region_flows(
            page_content,
            page_structure,
            content_blocks,
            text_by_id,
            region_map,
            fixed_parts,
        )
        if source_region_html:
            return source_region_html

        flow_area = self._flow_area_bbox(content_blocks, region_map, page_structure)
        x0, y0, x1, y1 = flow_area
        left = _pt_to_px(x0)
        top = _pt_to_px(y0)
        width = _pt_to_px(x1 - x0)
        height = _pt_to_px(y1 - y0)

        columns = self._content_columns(page_content, content_blocks, region_map, flow_area)
        if len(columns) >= 2:
            inner = self._render_reflow_mixed_columns(content_blocks, text_by_id, region_map, flow_area)
        else:
            inner = "\n".join(
                self._render_reflow_block(block, text_by_id[block.id])
                for block in content_blocks
                if block.id in text_by_id
            )

        flow = (
            f'<div class="typeset-reflow-area" '
            f'data-fit="reflow" '
            f'style="left:{_px(left)};top:{_px(top)};'
            f'width:{_px(width)};height:{_px(height)};'
            f'{self._flow_mask_style(page_structure, flow_area)}">'
            f"{inner}</div>"
        )
        return "\n".join([flow, *fixed_parts])

    def _is_bottom_credit_block(
        self,
        block: ContentBlock,
        bbox: list[float],
        page_structure: PageStructure,
    ) -> bool:
        text = (block.source_text or "") + " " + (block.translated_text or "")
        if bbox[1] < page_structure.height * 0.72:
            return False
        return any(marker in text for marker in ("ISBN", "Publishing", "APU", "delta-green.com"))

    def _should_position_light_foreground_block(
        self,
        block: ContentBlock,
        bbox: list[float],
        page_structure: PageStructure,
    ) -> bool:
        if not self._is_light_color(self._source_text_color(block)):
            return False
        return self._overlaps_foreground_image(bbox, page_structure)

    def _flow_mask_style(self, page_structure: PageStructure, flow_area: list[float]) -> str:
        for image in page_structure.images:
            if self._is_full_page_image(image.bbox, page_structure):
                continue
            if self._boxes_overlap(flow_area, image.bbox):
                return "background:#f4eedc;"
        return ""

    def _render_source_region_flows(
        self,
        page_content: PageContent,
        page_structure: PageStructure,
        content_blocks: list[ContentBlock],
        text_by_id: dict[str, str],
        region_map: dict[str, list[float]],
        fixed_parts: list[str],
    ) -> str:
        """Render Chinese text in source-derived regions instead of one large box."""
        if len(page_content.columns) < 2:
            return ""

        region_by_id = {region.id: region for region in page_structure.text_regions}
        self._current_region_by_id = region_by_id
        parts = list(fixed_parts)
        consumed: set[str] = set()

        for block in content_blocks:
            region = region_by_id.get(block.region_id)
            bbox = region_map.get(block.region_id)
            if region is None or bbox is None:
                continue
            if self._is_source_positioned_heading(block, region, page_structure, page_content):
                parts.append(self._render_source_positioned_block(block, page_structure, bbox))
                consumed.add(block.id)

        block_by_id = {block.id: block for block in content_blocks if block.id not in consumed}
        column_parts: list[str] = []
        for column in page_content.columns:
            column_blocks = [
                block_by_id[block_id]
                for block_id in column.block_ids
                if block_id in block_by_id and block_id in text_by_id and block_id not in consumed
            ]
            if not self._is_overwide_column_bbox(column.bbox, page_structure):
                column_blocks.extend(
                    block
                    for block in block_by_id.values()
                    if (
                        block.id not in column.block_ids
                        and block.id not in consumed
                        and block.id in text_by_id
                        and self._block_center_in_bbox(block, column.bbox, region_map)
                    )
                )
            if not column_blocks:
                continue
            if self._is_overwide_column_bbox(column.bbox, page_structure):
                for block in column_blocks:
                    column_parts.append(self._render_source_column_flow(
                        column.side,
                        region_map[block.region_id],
                        [block],
                        text_by_id,
                        region_map,
                        page_structure,
                    ))
                consumed.update(block.id for block in column_blocks)
                continue
            column_parts.append(self._render_source_column_flow(
                column.side,
                column.bbox,
                column_blocks,
                text_by_id,
                region_map,
                page_structure,
            ))
            consumed.update(block.id for block in column_blocks)

        for block in content_blocks:
            if block.id in consumed:
                continue
            bbox = region_map.get(block.region_id)
            if bbox is None:
                continue
            parts.append(self._render_source_positioned_block(block, page_structure, bbox))
            consumed.add(block.id)

        if not column_parts:
            return ""
        return "\n".join([*column_parts, *parts])

    def _is_overwide_column_bbox(
        self,
        bbox: list[float],
        page_structure: PageStructure,
    ) -> bool:
        return (bbox[2] - bbox[0]) >= page_structure.width * 0.6

    def _block_center_in_bbox(
        self,
        block: ContentBlock,
        bbox: list[float],
        region_map: dict[str, list[float]],
    ) -> bool:
        block_bbox = region_map.get(block.region_id)
        if block_bbox is None:
            return False
        x0, y0, x1, y1 = bbox
        bx0, by0, bx1, by1 = block_bbox
        center_x = (bx0 + bx1) / 2
        center_y = (by0 + by1) / 2
        return x0 <= center_x <= x1 and y0 - 8.0 <= center_y <= y1 + 8.0

    def _render_rotated_reflow_groups(
        self,
        blocks: list[ContentBlock],
        page_structure: PageStructure,
        region_map: dict[str, list[float]],
    ) -> list[str]:
        """Render a tilted source page/card as one readable text flow."""
        groups: dict[float, list[ContentBlock]] = {}
        singles: list[ContentBlock] = []
        for block in blocks:
            angle = self._region_angle(block.region_id, page_structure)
            if abs(angle) < 1.0:
                singles.append(block)
                continue
            groups.setdefault(round(angle * 2.0) / 2.0, []).append(block)

        rendered: list[str] = []
        for angle, group in groups.items():
            if len(group) < 3:
                singles.extend(group)
                continue
            ordered = sorted(group, key=lambda block: (region_map[block.region_id][1], region_map[block.region_id][0]))
            bboxes = [region_map[block.region_id] for block in ordered]
            x0 = min(bbox[0] for bbox in bboxes)
            y0 = min(bbox[1] for bbox in bboxes)
            x1 = max(bbox[2] for bbox in bboxes)
            y1 = max(bbox[3] for bbox in bboxes)
            pad_x = 4.0
            pad_y = 4.0
            left = _pt_to_px(max(0.0, x0 - pad_x))
            top = _pt_to_px(max(0.0, y0 - pad_y))
            width = _pt_to_px(min(page_structure.width, x1 + pad_x) - max(0.0, x0 - pad_x))
            height = _pt_to_px(min(page_structure.height, y1 + pad_y) - max(0.0, y0 - pad_y))
            inner = "\n".join(
                self._render_rotated_reflow_block(block, text, index == 0)
                for index, (block, text) in enumerate(self._build_reflow_items(ordered))
            )
            rendered.append(
                f'<div class="typeset-rotated-flow" '
                f'data-fit="reflow" '
                f'style="left:{_px(left)};top:{_px(top)};'
                f'width:{_px(width)};height:{_px(height)};'
                f'color:{html.escape(self._group_text_color(ordered))};'
                f'transform-origin:0 0;transform:rotate({angle:.3f}deg)">'
                f"{inner}</div>"
            )

        for block in singles:
            bbox = region_map.get(block.region_id)
            if bbox is not None:
                rendered.append(self._render_positioned_single_block(block, page_structure, bbox))
        return rendered

    def _render_source_column_flow(
        self,
        side: str,
        bbox: list[float],
        blocks: list[ContentBlock],
        text_by_id: dict[str, str],
        region_map: dict[str, list[float]],
        page_structure: PageStructure,
    ) -> str:
        template = getattr(self, "_current_template", None)
        line_flow = self._render_source_column_line_flow(side, blocks, text_by_id, region_map)
        if (
            line_flow
            and (template is None or template.use_line_tracks)
            and self._column_needs_line_tracks(bbox, page_structure)
        ):
            return line_flow

        x0, y0, x1, y1 = self._expanded_column_bbox(bbox)
        left = _pt_to_px(x0)
        top = _pt_to_px(y0)
        width = _pt_to_px(max(0.0, x1 - x0))
        height = _pt_to_px(max(0.0, y1 - y0))
        ordered = sorted(blocks, key=lambda block: (region_map[block.region_id][1], region_map[block.region_id][0]))
        inner = "\n".join(
            self._render_reflow_block(block, text_by_id[block.id])
            for block in ordered
            if block.id in text_by_id
        )
        return (
            f'<div class="typeset-region-flow" '
            f'data-column="{html.escape(side)}" '
            f'data-fit="reflow" '
            f'style="left:{_px(left)};top:{_px(top)};'
            f'width:{_px(width)};height:{_px(height)};'
            f'color:{html.escape(self._group_text_color(ordered))}">'
            f"{inner}</div>"
        )

    def _is_timeline_page(self, blocks: list[ContentBlock]) -> bool:
        date_blocks = [block for block in blocks if self._looks_like_timeline_event(block)]
        return len(date_blocks) >= 5

    def _looks_like_timeline_event(self, block: ContentBlock) -> bool:
        text = (block.source_text or block.translated_text or "").strip()
        return bool(re.match(r"^\d{1,2}\s+[A-Z][A-Z]+\s+\d{4}\b", text))

    def _render_timeline_page(
        self,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
        page_structure: PageStructure,
    ) -> str:
        date_blocks = [block for block in blocks if self._looks_like_timeline_event(block)]
        first_date_y = min(region_map[block.region_id][1] for block in date_blocks)
        intro_blocks = [
            block
            for block in blocks
            if (
                block not in date_blocks
                and region_map[block.region_id][1] < first_date_y
                and region_map[block.region_id][2] - region_map[block.region_id][0]
                >= page_structure.width * 0.55
            )
        ]
        event_blocks = [block for block in blocks if block not in intro_blocks]

        parts: list[str] = []
        if intro_blocks:
            intro_boxes = [region_map[block.region_id] for block in intro_blocks]
            x0 = min(bbox[0] for bbox in intro_boxes)
            y0 = min(bbox[1] for bbox in intro_boxes)
            x1 = max(bbox[2] for bbox in intro_boxes)
            y1 = max(bbox[3] for bbox in intro_boxes)
            intro = "".join(
                f'<p class="typeset-timeline-event">{self._format_text(self._display_text_for_block(block))}</p>'
                for block in intro_blocks
            )
            parts.append(
                f'<div class="typeset-timeline-intro" '
                f'style="left:{_pt_to_px_str(x0)};top:{_pt_to_px_str(y0)};'
                f'width:{_pt_to_px_str(x1 - x0)};height:{_pt_to_px_str(y1 - y0)}">'
                f"{intro}</div>"
            )

        boxes = [region_map[block.region_id] for block in event_blocks]
        x0 = max(42.0, min(bbox[0] for bbox in boxes))
        y0 = min(bbox[1] for bbox in boxes)
        x1 = min(page_structure.width - 42.0, max(bbox[2] for bbox in boxes))
        y1 = min(page_structure.height - 50.0, max(bbox[3] for bbox in boxes))
        columns = 3 if x1 - x0 >= page_structure.width * 0.65 else 2
        column_width = max(1.0, (x1 - x0) / columns)
        ordered = sorted(
            event_blocks,
            key=lambda block: (
                int((((region_map[block.region_id][0] + region_map[block.region_id][2]) / 2) - x0) / column_width),
                region_map[block.region_id][1],
            ),
        )
        events = "".join(
            f'<p class="typeset-timeline-event">{self._format_text(self._display_text_for_block(block))}</p>'
            for block in ordered
            if self._display_text_for_block(block)
        )
        parts.append(
            f'<div class="typeset-timeline-flow" '
            f'style="left:{_pt_to_px_str(x0)};top:{_pt_to_px_str(y0)};'
            f'width:{_pt_to_px_str(x1 - x0)};height:{_pt_to_px_str(y1 - y0)};'
            f'column-count:{columns}">{events}</div>'
        )
        return "\n".join(parts)

    def _is_centered_stack_page(
        self,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
        page_structure: PageStructure,
    ) -> bool:
        body_blocks = [
            block for block in blocks
            if block.role == SemanticRole.BODY_COLUMN
            and region_map[block.region_id][1] > page_structure.height * 0.22
        ]
        if len(body_blocks) < 4:
            return False
        page_center = page_structure.width / 2
        centered = [
            block for block in body_blocks
            if abs(((region_map[block.region_id][0] + region_map[block.region_id][2]) / 2) - page_center)
            <= page_structure.width * 0.18
        ]
        return len(centered) >= 4 and len(centered) / len(body_blocks) >= 0.6

    def _column_needs_line_tracks(
        self,
        column_bbox: list[float],
        page_structure: PageStructure,
    ) -> bool:
        for image in page_structure.images:
            if self._is_full_page_image(image.bbox, page_structure):
                continue
            if self._is_thin_decoration_image(image.bbox):
                continue
            if self._overlap_ratio(column_bbox, image.bbox) >= 0.08:
                return True
        return False

    def _is_full_page_image(
        self,
        bbox: list[float],
        page_structure: PageStructure,
    ) -> bool:
        if len(bbox) != 4:
            return False
        x0, y0, x1, y1 = bbox
        width = max(0.0, x1 - x0)
        height = max(0.0, y1 - y0)
        return (
            width >= page_structure.width * 0.9
            and height >= page_structure.height * 0.9
        )

    def _is_thin_decoration_image(self, bbox: list[float]) -> bool:
        if len(bbox) != 4:
            return False
        x0, y0, x1, y1 = bbox
        width = max(0.0, x1 - x0)
        height = max(0.0, y1 - y0)
        return height <= 14.0 and width >= 80.0

    def _overlap_ratio(self, a: list[float], b: list[float]) -> float:
        if len(a) != 4 or len(b) != 4:
            return 0.0
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        overlap_width = max(0.0, min(ax1, bx1) - max(ax0, bx0))
        overlap_height = max(0.0, min(ay1, by1) - max(ay0, by0))
        overlap_area = overlap_width * overlap_height
        column_area = max(1.0, max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0))
        return overlap_area / column_area

    def _render_source_column_line_flow(
        self,
        side: str,
        blocks: list[ContentBlock],
        text_by_id: dict[str, str],
        region_map: dict[str, list[float]],
    ) -> str:
        tracks = self._source_line_tracks(blocks, region_map)
        if len(tracks) < 3:
            return ""
        ordered_blocks = sorted(blocks, key=lambda block: (region_map[block.region_id][1], region_map[block.region_id][0]))
        flow_text = self._join_line_flow_text(
            text_by_id[block.id]
            for block in ordered_blocks
            if block.id in text_by_id
        )
        if not flow_text:
            return ""

        slots = []
        for index, track in enumerate(tracks):
            x0, y0, x1, y1 = track["bbox"]
            left = _pt_to_px(x0)
            top = _pt_to_px(y0)
            width = _pt_to_px(max(0.0, x1 - x0))
            height = max(_pt_to_px(max(0.0, y1 - y0)), _pt_to_px(self.config.body_font_size_pt * 1.15))
            font_size = _pt_to_px(max(self.config.min_body_font_size_pt, min(track["font_size"], self.config.body_font_size_pt)))
            color = self.config.subtitle_color if track["color"].lower() == self.config.subtitle_color.lower() else self.config.body_color
            slots.append(
                f'<span class="typeset-line-slot" '
                f'data-line-index="{index}" '
                f'data-bold="{str(track["bold"]).lower()}" '
                f'data-italic="{str(track["italic"]).lower()}" '
                f'style="left:{_px(left)};top:{_px(top)};'
                f'width:{_px(width)};height:{_px(height)};'
                f'font-size:{_px(font_size)};color:{html.escape(color)}"></span>'
            )
        return (
            f'<div class="typeset-line-track-flow" '
            f'data-column="{html.escape(side)}" '
            f'data-flow-text="{html.escape(flow_text)}">'
            f'{"".join(slots)}</div>'
        )

    def _source_line_tracks(
        self,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
    ) -> list[dict[str, object]]:
        region_by_id = getattr(self, "_current_region_by_id", {})
        tracks: list[dict[str, object]] = []
        for block in blocks:
            region = region_by_id.get(block.region_id)
            if region is None:
                continue
            lines = getattr(region, "lines", [])
            if not lines:
                continue
            for line in lines:
                angle = float(getattr(line, "angle", 0.0) or 0.0)
                if abs(angle) >= 1.0:
                    continue
                bbox = list(getattr(line, "bbox", []))
                if len(bbox) != 4:
                    continue
                tracks.append({
                    "bbox": bbox,
                    "font_size": float(getattr(line, "font_size", self.config.body_font_size_pt) or self.config.body_font_size_pt),
                    "bold": bool(getattr(line, "bold", False)),
                    "italic": bool(getattr(line, "italic", False)),
                    "color": str(getattr(line, "color", self.config.body_color) or self.config.body_color),
                })
        tracks.sort(key=lambda track: (track["bbox"][1], track["bbox"][0]))
        return tracks

    def _join_line_flow_text(self, texts) -> str:
        parts = [str(text).strip() for text in texts if str(text).strip()]
        return "".join(parts)

    def _expanded_column_bbox(self, bbox: list[float]) -> list[float]:
        x0, y0, x1, y1 = bbox
        return [x0, max(0.0, y0 - 2.0), x1, y1 + 4.0]

    def _is_source_positioned_heading(
        self,
        block: ContentBlock,
        region: TextRegionBBox,
        page_structure: PageStructure,
        page_content: PageContent | None = None,
    ) -> bool:
        if block.role == SemanticRole.TITLE:
            return True
        if page_content and (
            self._block_belongs_to_column(block, page_content)
            or self._region_center_in_any_column(region.bbox, page_content)
        ):
            return False
        if block.role in (SemanticRole.HEADER, SemanticRole.SUBTITLE):
            return True
        if self._get_block_font_size(block) >= self.config.body_font_size_pt * 1.45:
            return True
        x0, _, x1, _ = region.bbox
        width_ratio = (x1 - x0) / max(1.0, page_structure.width)
        return width_ratio >= 0.65 and self._looks_like_subtitle(block)

    def _block_belongs_to_column(
        self,
        block: ContentBlock,
        page_content: PageContent,
    ) -> bool:
        return any(block.id in column.block_ids for column in page_content.columns)

    def _region_center_in_any_column(
        self,
        region_bbox: list[float],
        page_content: PageContent,
    ) -> bool:
        bx0, by0, bx1, by1 = region_bbox
        center_x = (bx0 + bx1) / 2
        center_y = (by0 + by1) / 2
        for column in page_content.columns:
            x0, y0, x1, y1 = column.bbox
            if x0 <= center_x <= x1 and y0 - 8.0 <= center_y <= y1 + 8.0:
                return True
        return False

    def _render_source_positioned_block(
        self,
        block: ContentBlock,
        page_structure: PageStructure,
        bbox: list[float],
    ) -> str:
        span_html = self._render_source_span_block(block, page_structure)
        if span_html:
            return span_html
        x0, y0, x1, y1 = bbox
        left = _pt_to_px(x0)
        top = _pt_to_px(y0)
        width = _pt_to_px(max(0.0, x1 - x0))
        height = _pt_to_px(max(0.0, y1 - y0))
        inner = self._render_block(block)
        if not inner:
            return ""
        return self._positioned_block_html(
            block.region_id,
            left,
            top,
            width,
            height,
            self._block_text_color(block),
            inner,
            self._region_angle(block.region_id, page_structure),
            self._positioned_mask_style(page_structure, bbox, block),
        )

    def _render_source_span_block(
        self,
        block: ContentBlock,
        page_structure: PageStructure,
    ) -> str:
        if block.translated_text and block.translated_text.strip() != (block.source_text or "").strip():
            return ""
        region = {item.id: item for item in page_structure.text_regions}.get(block.region_id)
        if region is None or not getattr(region, "lines", None):
            return ""
        spans_html: list[str] = []
        for line in region.lines:
            for span in getattr(line, "spans", []):
                text = getattr(span, "text", "")
                if not text:
                    continue
                x0, y0, x1, y1 = span.bbox
                font_size_px = _pt_to_px(float(span.font_size))
                style = (
                    f"left:{_pt_to_px_str(x0)};top:{_pt_to_px_str(y0)};"
                    f"width:{_pt_to_px_str(max(0.0, x1 - x0))};"
                    f"height:{_pt_to_px_str(max(0.0, y1 - y0))};"
                    f"font-size:{_px(font_size_px)};"
                    f"line-height:1.05;color:{html.escape(span.color)};"
                    f"font-weight:{'700' if span.bold else '400'};"
                    f"font-style:{'italic' if span.italic else 'normal'}"
                )
                spans_html.append(
                    f'<span class="typeset-source-span" '
                    f'data-region-id="{html.escape(block.region_id)}" '
                    f'style="{style}">{html.escape(text)}</span>'
                )
        if not spans_html:
            return ""
        return "".join(spans_html)

    def _dedupe_content_blocks(
        self,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
    ) -> list[ContentBlock]:
        result: list[ContentBlock] = []
        for block in blocks:
            text = _normalized_text(block.source_text)
            if len(text) < 8:
                result.append(block)
                continue
            replaced = False
            skip = False
            for index, kept in enumerate(result):
                kept_text = _normalized_text(kept.source_text)
                if not kept_text:
                    continue
                if not self._boxes_overlap(region_map[block.region_id], region_map[kept.region_id]):
                    continue
                if text in kept_text:
                    skip = True
                    break
                if kept_text in text:
                    result[index] = block
                    replaced = True
                    break
            if not skip and not replaced:
                result.append(block)
        return result

    def _build_reflow_items(self, blocks: list[ContentBlock]) -> list[tuple[ContentBlock, str]]:
        items: list[tuple[ContentBlock, str]] = []
        seen_text = ""

        for block in blocks:
            original_text = self._display_text_for_block(block)
            if not original_text:
                continue

            text = original_text
            trimmed = False
            if _contains_cjk(text):
                text = self._trim_repeated_prefix(text, seen_text)
                trimmed = text != original_text
                if not text:
                    continue

            if (
                items
                and self._is_mergeable_reflow_body(items[-1][0], block)
                and (trimmed or self._source_text_windows_overlap(items[-1][0], block))
            ):
                previous_block, previous_text = items[-1]
                items[-1] = (previous_block, self._join_reflow_text(previous_text, text))
            else:
                items.append((block, text))

            seen_text += _normalized_text(text)

        return items

    def _trim_repeated_prefix(self, text: str, seen_text: str) -> str:
        normalized = _normalized_text(text)
        if len(normalized) < 8:
            return text

        max_prefix = min(len(normalized), 120)
        for size in range(max_prefix, 7, -1):
            if normalized[:size] in seen_text:
                return text[size:].lstrip("，。；：、,. ;:")
        return text

    def _is_mergeable_reflow_body(self, previous: ContentBlock, current: ContentBlock) -> bool:
        return (
            previous.role == SemanticRole.BODY_COLUMN
            and current.role == SemanticRole.BODY_COLUMN
            and not self._looks_like_subtitle(previous)
            and not self._looks_like_subtitle(current)
        )

    def _source_text_windows_overlap(self, previous: ContentBlock, current: ContentBlock) -> bool:
        previous_text = _normalized_text(previous.source_text)
        current_text = _normalized_text(current.source_text)
        if len(previous_text) < 24 or len(current_text) < 24:
            return False
        if previous_text in current_text or current_text in previous_text:
            return True
        max_size = min(len(previous_text), len(current_text), 160)
        for size in range(max_size, 23, -1):
            if previous_text[-size:] == current_text[:size]:
                return True
        return False

    def _join_reflow_text(self, previous: str, current: str) -> str:
        if not previous:
            return current
        if not current:
            return previous
        if previous[-1] in "。！？.!?":
            return previous + current
        return previous + current

    def _boxes_overlap(self, a: list[float], b: list[float]) -> bool:
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        overlap_w = max(0.0, min(ax1, bx1) - max(ax0, bx0))
        overlap_h = max(0.0, min(ay1, by1) - max(ay0, by0))
        return overlap_w > 0 and overlap_h > 0

    def _flow_area_bbox(
        self,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
        page_structure: PageStructure,
    ) -> list[float]:
        bboxes = [region_map[block.region_id] for block in blocks]
        x0 = max(34.0, min(bbox[0] for bbox in bboxes))
        y0 = max(64.0, min(bbox[1] for bbox in bboxes))
        x1 = min(page_structure.width - 34.0, max(bbox[2] for bbox in bboxes))
        y1 = min(page_structure.height - 54.0, max(bbox[3] for bbox in bboxes))
        max_block_width = max((bbox[2] - bbox[0]) for bbox in bboxes)
        is_narrow_source_flow = max_block_width < page_structure.width * 0.45
        if x1 - x0 < page_structure.width * 0.55 and not is_narrow_source_flow:
            x0 = 54.0
            x1 = page_structure.width - 54.0
        if y1 - y0 < page_structure.height * 0.35:
            y1 = page_structure.height - 84.0
        return [x0, y0, x1, y1]

    def _content_columns(
        self,
        page_content: PageContent,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
        flow_area: list[float],
    ) -> list[list[ContentBlock]]:
        if len(page_content.columns) < 2:
            return [blocks]
        mid = (flow_area[0] + flow_area[2]) / 2
        left: list[ContentBlock] = []
        right: list[ContentBlock] = []
        for block in blocks:
            bbox = region_map[block.region_id]
            center = (bbox[0] + bbox[2]) / 2
            if center < mid:
                left.append(block)
            else:
                right.append(block)
        if not left or not right:
            return [blocks]
        return [left, right]

    def _render_reflow_mixed_columns(
        self,
        blocks: list[ContentBlock],
        text_by_id: dict[str, str],
        region_map: dict[str, list[float]],
        flow_area: list[float],
    ) -> str:
        parts: list[str] = []
        pending: list[ContentBlock] = []

        for block in blocks:
            if self._is_full_width_reflow_block(block, region_map, flow_area):
                parts.append(self._render_reflow_column_pair(pending, text_by_id, region_map, flow_area))
                pending = []
                parts.append(self._render_reflow_block(block, text_by_id[block.id]))
            else:
                pending.append(block)

        parts.append(self._render_reflow_column_pair(pending, text_by_id, region_map, flow_area))
        return "\n".join(part for part in parts if part)

    def _render_reflow_column_pair(
        self,
        blocks: list[ContentBlock],
        text_by_id: dict[str, str],
        region_map: dict[str, list[float]],
        flow_area: list[float],
    ) -> str:
        if not blocks:
            return ""
        columns = self._content_columns_for_blocks(blocks, region_map, flow_area)
        if len(columns) < 2:
            return "\n".join(
                self._render_reflow_block(block, text_by_id[block.id])
                for block in blocks
                if block.id in text_by_id
            )

        rendered = ['<div class="typeset-reflow-columns">']
        for col_blocks in columns:
            rendered.append('<div class="typeset-reflow-column">')
            rendered.extend(
                self._render_reflow_block(block, text_by_id[block.id])
                for block in col_blocks
                if block.id in text_by_id
            )
            rendered.append("</div>")
        rendered.append("</div>")
        return "\n".join(rendered)

    def _content_columns_for_blocks(
        self,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
        flow_area: list[float],
    ) -> list[list[ContentBlock]]:
        mid = (flow_area[0] + flow_area[2]) / 2
        left = []
        right = []
        for block in blocks:
            bbox = region_map[block.region_id]
            center = (bbox[0] + bbox[2]) / 2
            if center < mid:
                left.append(block)
            else:
                right.append(block)
        if not left or not right:
            return [blocks]
        return [left, right]

    def _is_full_width_reflow_block(
        self,
        block: ContentBlock,
        region_map: dict[str, list[float]],
        flow_area: list[float],
    ) -> bool:
        bbox = region_map[block.region_id]
        mid = (flow_area[0] + flow_area[2]) / 2
        width = bbox[2] - bbox[0]
        flow_width = flow_area[2] - flow_area[0]
        return width >= flow_width * 0.65 or (bbox[0] < mid < bbox[2])

    def _render_reflow_block(self, block: ContentBlock, text: str | None = None) -> str:
        text = (text if text is not None else self._display_text_for_block(block)).strip()
        if not text:
            return ""
        if block.role in (SemanticRole.TITLE, SemanticRole.HEADER):
            escaped = self._format_text(text)
            return f'<h2 class="typeset-reflow-title">{escaped}</h2>'
        if block.role == SemanticRole.SUBTITLE or self._looks_like_subtitle(block):
            escaped = self._format_text(text)
            return f'<h3 class="typeset-reflow-subtitle">{escaped}</h3>'
        escaped = self._format_body_text(block, text)
        class_name = "typeset-reflow-body"
        if self._looks_like_timeline_text(block, text):
            class_name += " typeset-timeline-text"
        return f'<p class="{class_name}">{escaped}</p>'

    def _render_rotated_reflow_block(
        self,
        block: ContentBlock,
        text: str,
        is_first: bool,
    ) -> str:
        if not (is_first and self._source_starts_with_display_heading(block)):
            return self._render_reflow_block(block, text)
        title, body = self._split_leading_title_text(text)
        if not title:
            return self._render_reflow_block(block, text)
        parts = [
            f'<h2 class="typeset-reflow-title">{self._format_text(title)}</h2>'
        ]
        if body:
            parts.append(
                f'<p class="typeset-reflow-body">{self._format_body_text(block, body)}</p>'
            )
        return "".join(parts)

    def _source_starts_with_display_heading(self, block: ContentBlock) -> bool:
        source = (block.source_text or "").strip()
        match = re.match(r"^[A-Z0-9][A-Z0-9 '\-:,.]{10,}", source)
        if not match:
            return False
        heading = match.group(0).strip()
        return len(heading) >= 10 and sum(ch.isalpha() for ch in heading) >= 8

    def _split_leading_title_text(self, text: str) -> tuple[str, str]:
        cleaned = text.strip()
        for separator in ("。", "！", "？", "；", "，"):
            index = cleaned.find(separator)
            if 1 <= index <= 16:
                return cleaned[:index].strip(), cleaned[index + 1:].strip()
        return "", cleaned

    def _looks_like_subtitle(self, block: ContentBlock) -> bool:
        text = (block.source_text or block.translated_text or "").strip()
        font_size = self._get_block_font_size(block)
        if any(run.color.lower() == self.config.subtitle_color.lower() for run in block.runs):
            return True
        if len(text) <= 32 and font_size >= self.config.body_font_size_pt:
            return True
        return block.role in (SemanticRole.SUBTITLE, SemanticRole.LIST)

    def _render_positioned_blocks(
        self,
        page_content: PageContent,
        page_structure: PageStructure,
    ) -> str:
        """Render text blocks back into their source PDF region boxes."""
        region_map = {region.id: region.bbox for region in page_structure.text_regions}
        parts: list[str] = []
        consumed: set[str] = set()
        blocks_with_regions = [
            block for block in page_content.blocks
            if block.region_id in region_map
        ]
        blocks = self._dedupe_content_blocks(blocks_with_regions, region_map)
        for index, block in enumerate(blocks):
            if block.id in consumed:
                continue
            bbox = region_map.get(block.region_id)
            if bbox is None:
                parts.append(self._render_block(block))
                consumed.add(block.id)
                continue

            if self._is_running_header(block):
                parts.append(self._render_running_header(block, page_structure, bbox))
                consumed.add(block.id)
                continue
            if self._is_fixed_page_number(block):
                parts.append(self._render_fixed_page_number(block, bbox))
                consumed.add(block.id)
                continue
            if self._is_flow_body_block(block):
                group = self._collect_flow_group(blocks, index, region_map, consumed)
                if len(group) > 1:
                    parts.append(self._render_positioned_flow_group(group, region_map, page_structure))
                    consumed.update(item.id for item in group)
                    continue

            x0, y0, x1, y1 = bbox
            left = _pt_to_px(x0)
            top = _pt_to_px(y0)
            width = _pt_to_px(max(0.0, x1 - x0))
            height = _pt_to_px(max(0.0, y1 - y0))
            color = self._block_text_color(block)
            inner = self._render_block(block)
            if not inner:
                continue

            parts.append(self._positioned_block_html(
                block.region_id, left, top, width, height, color, inner,
                self._region_angle(block.region_id, page_structure),
                self._positioned_mask_style(page_structure, bbox, block),
            ))
            consumed.add(block.id)
        return "\n".join(parts)

    def _render_positioned_single_block(
        self,
        block: ContentBlock,
        page_structure: PageStructure,
        bbox: list[float],
    ) -> str:
        x0, y0, x1, y1 = bbox
        left = _pt_to_px(x0)
        top = _pt_to_px(y0)
        width = _pt_to_px(max(0.0, x1 - x0))
        height = _pt_to_px(max(0.0, y1 - y0))
        inner = self._render_block(block)
        if not inner:
            return ""
        return self._positioned_block_html(
            block.region_id,
            left,
            top,
            width,
            height,
            self._block_text_color(block),
            inner,
            self._region_angle(block.region_id, page_structure),
            self._positioned_mask_style(page_structure, bbox, block),
        )

    def _positioned_block_html(
        self,
        region_id: str,
        left: float,
        top: float,
        width: float,
        height: float,
        color: str,
        inner: str,
        angle: float = 0.0,
        extra_style: str = "",
    ) -> str:
        transform = ""
        if abs(angle) >= 1.0:
            transform = f"transform-origin:0 0;transform:rotate({angle:.3f}deg);"
        return (
            f'<div class="typeset-positioned-block" '
            f'data-region-id="{html.escape(region_id)}" '
            f'data-fit="text" '
            f'style="left:{_px(left)};top:{_px(top)};'
            f'width:{_px(width)};height:{_px(height)};'
            f'color:{html.escape(color)};{transform}{extra_style}">'
            f"{inner}</div>"
        )

    def _positioned_mask_style(
        self,
        page_structure: PageStructure,
        bbox: list[float],
        block: ContentBlock | None = None,
    ) -> str:
        if block is not None and self._is_light_color(self._block_text_color(block)):
            return ""
        for image in page_structure.images:
            if self._is_full_page_image(image.bbox, page_structure):
                continue
            if self._boxes_overlap(bbox, image.bbox):
                return "background:#f4eedc;"
        return ""

    def _overlaps_foreground_image(
        self,
        bbox: list[float],
        page_structure: PageStructure,
    ) -> bool:
        return any(
            self._boxes_overlap(bbox, image.bbox)
            for image in page_structure.images
            if not self._is_full_page_image(image.bbox, page_structure)
        )

    def _is_flow_body_block(self, block: ContentBlock) -> bool:
        if block.role != SemanticRole.BODY_COLUMN:
            return False
        return self._get_block_font_size(block) < self.config.body_font_size_pt * 1.25

    def _region_angle(self, region_id: str, page_structure: PageStructure) -> float:
        for region in page_structure.text_regions:
            if region.id == region_id:
                return float(getattr(region, "angle", 0.0) or 0.0)
        return 0.0

    def _collect_flow_group(
        self,
        blocks: list[ContentBlock],
        start_index: int,
        region_map: dict[str, list[float]],
        consumed: set[str],
    ) -> list[ContentBlock]:
        group = [blocks[start_index]]
        last_bbox = region_map[blocks[start_index].region_id]
        for block in blocks[start_index + 1:]:
            if block.id in consumed or not self._is_flow_body_block(block):
                break
            bbox = region_map.get(block.region_id)
            if bbox is None or not _same_text_flow(last_bbox, bbox):
                break
            group.append(block)
            last_bbox = bbox
        return group

    def _render_positioned_flow_group(
        self,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
        page_structure: PageStructure,
    ) -> str:
        bboxes = [region_map[block.region_id] for block in blocks]
        x0 = min(bbox[0] for bbox in bboxes)
        y0 = min(bbox[1] for bbox in bboxes)
        x1 = max(bbox[2] for bbox in bboxes)
        y1 = max(bbox[3] for bbox in bboxes)
        left = _pt_to_px(x0)
        top = _pt_to_px(y0)
        width = _pt_to_px(max(0.0, x1 - x0))
        height = _pt_to_px(max(0.0, y1 - y0))
        color = self._block_text_color(blocks[0])
        flow_items = self._build_reflow_items(blocks)
        inner = "\n".join(
            self._render_body_block(block, text, self._get_block_font_size(block))
            for block, text in flow_items
        )
        ids = " ".join(block.id for block in blocks)
        return (
            f'<div class="typeset-positioned-block" '
            f'data-flow-blocks="{html.escape(ids)}" '
            f'data-fit="text" '
            f'style="left:{_px(left)};top:{_px(top)};'
            f'width:{_px(width)};height:{_px(height)};'
            f'color:{html.escape(color)};'
            f'{self._positioned_mask_style(page_structure, [x0, y0, x1, y1], blocks[0])}">'
            f"{inner}</div>"
        )

    def _is_running_header(self, block: ContentBlock) -> bool:
        """Detect the fixed running header line, not normal section titles."""
        text = block.source_text or ""
        return block.role == SemanticRole.HEADER and "//" in text

    def _render_running_header(
        self,
        block: ContentBlock,
        page_structure: PageStructure,
        bbox: list[float],
    ) -> str:
        """Render fixed left/right running headers in their original slots."""
        marker_runs = [
            run for run in block.runs
            if run.text.strip().startswith("//") and run.text.strip().endswith("//")
        ]
        if not marker_runs:
            marker_runs = block.runs[:1]

        x0, y0, x1, y1 = bbox
        top = _pt_to_px(y0)
        height = max(_pt_to_px(y1 - y0), _pt_to_px(12.0))
        left_margin = x0
        right_margin = max(0.0, page_structure.width - x1)
        slot_width = min(180.0, max(80.0, page_structure.width / 2 - left_margin - 8.0))
        font_size_pt = self._get_block_font_size(block)
        font_size_px = _pt_to_px(font_size_pt)

        parts: list[str] = []
        for index, run in enumerate(marker_runs[:2]):
            text = html.escape(run.text.strip())
            if index == 0:
                left = _pt_to_px(left_margin)
                align = "left"
            else:
                left = _pt_to_px(page_structure.width - right_margin - slot_width)
                align = "right"
            parts.append(
                f'<div class="typeset-positioned-block" '
                f'data-block-id="{html.escape(block.id)}" '
                f'style="left:{_px(left)};top:{_px(top)};'
                f'width:{_pt_to_px_str(slot_width)};height:{_px(height)};'
                f'font-size:{_px(font_size_px)};line-height:1;'
                f'text-align:{align};white-space:nowrap;color:#000000">'
                f"{text}</div>"
            )
        return "\n".join(parts)

    def _is_fixed_page_number(self, block: ContentBlock) -> bool:
        """Detect the fixed page number, which sits inside the printed square."""
        return block.role == SemanticRole.FOOTER and (block.source_text or "").strip().isdigit()

    def _render_fixed_page_number(self, block: ContentBlock, bbox: list[float]) -> str:
        """Render page numbers without body indentation or paragraph margins."""
        text = html.escape((block.source_text or "").strip())
        x0, y0, x1, y1 = bbox
        center_x = _pt_to_px((x0 + x1) / 2)
        center_y = _pt_to_px((y0 + y1) / 2)
        width = _pt_to_px(16.0)
        height = _pt_to_px(13.0)
        left = center_x - width / 2
        top = center_y - height / 2
        font_size = _pt_to_px(self._get_block_font_size(block))
        return (
            f'<div class="typeset-positioned-block" '
            f'data-block-id="{html.escape(block.id)}" '
            f'style="left:{_px(left)};top:{_px(top)};'
            f'width:{_px(width)};height:{_px(height)};'
            f'font-size:{_px(font_size)};line-height:{_px(height)};'
            f'text-align:center;text-indent:0;color:#000000">'
            f"{text}</div>"
        )

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

    def _block_text_color(self, block: ContentBlock) -> str:
        """Pick the source text color that should carry over to translated text."""
        source_color = self._source_text_color(block)
        if source_color and self._is_light_color(source_color):
            return source_color
        if block.role == SemanticRole.TITLE:
            return self.config.title_color
        if block.role == SemanticRole.SUBTITLE or self._looks_like_subtitle(block):
            return self.config.subtitle_color
        if source_color:
            return source_color
        return "#000000"

    def _source_text_color(self, block: ContentBlock) -> str:
        colors = [
            run.color
            for run in block.runs
            if run.text.strip() and run.color
        ]
        if not colors:
            return ""
        light_count = sum(1 for color in colors if self._is_light_color(color))
        if light_count and light_count >= len(colors) / 3:
            return next(color for color in colors if self._is_light_color(color))
        for color in colors:
            if not self._is_light_color(color):
                return color
        return colors[0]

    def _group_text_color(self, blocks: list[ContentBlock]) -> str:
        colors = [self._source_text_color(block) for block in blocks]
        colors = [color for color in colors if color]
        if not colors:
            return self.config.body_color
        light_count = sum(1 for color in colors if self._is_light_color(color))
        if light_count and light_count >= len(colors) / 2:
            return next(color for color in colors if self._is_light_color(color))
        return self.config.body_color

    def _is_light_color(self, color: str) -> bool:
        match = re.fullmatch(r"#?([0-9a-fA-F]{6})", (color or "").strip())
        if not match:
            return False
        value = match.group(1)
        red = int(value[0:2], 16)
        green = int(value[2:4], 16)
        blue = int(value[4:6], 16)
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        return luminance >= 180

    def _render_block(self, block: ContentBlock, is_cover: bool = False) -> str:
        """Render a single content block as HTML."""
        # Determine the text to display
        text = self._display_text_for_block(block)
        if not text:
            return ""

        # Determine font size from runs
        block_font_size_pt = self._get_block_font_size(block)

        # Check if this is a heading
        if self._is_heading(block_font_size_pt) or block.role == SemanticRole.TITLE:
            return self._render_heading_block(block, text, block_font_size_pt)
        if block.role == SemanticRole.SUBTITLE:
            return self._render_subtitle_block(block, text, block_font_size_pt)
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

    def _display_text_for_block(self, block: ContentBlock) -> str:
        if block.translatable:
            return (block.translated_text or "").strip()
        return (block.translated_text or block.source_text or "").strip()

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
            f'style="font-size:{_px(font_size_px)};'
            f'font-weight:{self._source_font_weight(block)}">'
            f"{escaped_text}"
            f"</{tag}>"
        )

    def _render_subtitle_block(
        self, block: ContentBlock, text: str, font_size_pt: float
    ) -> str:
        font_size_px = _pt_to_px(max(font_size_pt, self.config.body_font_size_pt * 1.2))
        escaped_text = self._format_text(text)
        return (
            f'<h3 class="typeset-heading typeset-source-subtitle" '
            f'data-block-id="{html.escape(block.id)}" '
            f'style="font-size:{_px(font_size_px)};'
            f'font-weight:{self._source_font_weight(block)}">'
            f"{escaped_text}</h3>"
        )

    def _source_font_weight(self, block: ContentBlock) -> str:
        return "700" if any(run.bold for run in block.runs if run.text.strip()) else "400"

    def _render_body_block(
        self, block: ContentBlock, text: str, font_size_pt: float
    ) -> str:
        """Render a block as a body paragraph."""
        font_size_px = _pt_to_px(font_size_pt)
        # Enforce minimum font size
        font_size_px = max(font_size_px, self._min_font_size_px())
        escaped_text = self._format_body_text(block, text)

        style_parts: list[str] = []
        # Only add font-size if different from body default
        body_px = self._body_font_size_px()
        if abs(font_size_px - body_px) > 0.1:
            style_parts.append(f"font-size:{_px(font_size_px)}")
        if self._looks_like_timeline_text(block, text):
            style_parts.append("text-indent:0")
            style_parts.append("line-height:1.25")

        style_attr = f' style="{";".join(style_parts)}"' if style_parts else ""
        class_name = "typeset-body-text"
        if self._looks_like_timeline_text(block, text):
            class_name += " typeset-timeline-text"

        return (
            f'<p class="{class_name}" '
            f'data-block-id="{html.escape(block.id)}"'
            f"{style_attr}>"
            f"{escaped_text}"
            f"</p>"
        )

    def _format_body_text(self, block: ContentBlock, text: str) -> str:
        if self._looks_like_timeline_text(block, text):
            return "<br>".join(
                html.escape(part.strip())
                for part in re.split(r"(?=\b\d{2}:\d{2}\s+)", text)
                if part.strip()
            )
        return self._format_text(text)

    def _looks_like_timeline_text(self, block: ContentBlock, text: str) -> bool:
        source = block.source_text or ""
        combined = f"{source}\n{text}"
        return len(re.findall(r"\b\d{2}:\d{2}\s+", combined)) >= 4

    def _format_text(self, text: str) -> str:
        """Format text for HTML output, preserving only paragraph breaks."""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        paragraphs = re.split(r"\n{2,}", normalized)
        return "<br><br>".join(html.escape(paragraph) for paragraph in paragraphs)
