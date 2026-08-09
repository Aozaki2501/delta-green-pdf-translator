"""
Typeset HTML rebuilder for the pure-reflow pipeline.

Rebuilds each PDF page from scratch as HTML/CSS, placing background, images,
decorations, and reflowed Chinese text in proper z-order layers. The output
is a complete HTML document ready for Playwright PDF export.
"""

from __future__ import annotations

import html
import re
from dataclasses import replace
from pathlib import Path

from core.typeset_models import (
    BackgroundLayer,
    ContentBlock,
    DecorationElement,
    FontRole,
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
from core.typeset_visibility import occluded_duplicate_block_ids
from core.typeset_templates import select_typeset_template
from exporters.typeset_browser_contract import build_typeset_browser_contract

# PDF points → CSS pixels conversion factor (96 DPI / 72 DPI)
CSS_PX_PER_PT = 96.0 / 72.0

# z-index layer constants
Z_BACKGROUND = 1
Z_PAGE_IMAGES = 2
Z_DECORATIONS = 3
Z_IMAGES = 4
Z_TEXT = 5


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


_TIMELINE_DATE_LINE_RE = re.compile(
    r"^(?:"
    r"\d{1,2}\s+[A-Z]{3,9}\s+\d{4}"
    r"|\d{4}年\d{1,2}月\d{1,2}日"
    r"|\d{4}(?:[–—-]\d{4})?"
    r")$"
)


def _union_block_bboxes(
    blocks: list[ContentBlock],
    region_map: dict[str, list[float]],
) -> list[float]:
    boxes = [block.bbox or region_map[block.region_id] for block in blocks]
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


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

    def _document_title(self, structure: PageStructureDocument) -> str:
        """Return the user-facing title stored with the source document."""
        title = (self.config.document_title or "").strip()
        if title:
            return title
        return Path(structure.source_pdf).stem

    def rebuild_document(
        self,
        structure: PageStructureDocument,
        content: PageContentDocument,
        page_visuals: dict[int, str] | None = None,
    ) -> str:
        """
        Rebuild the entire document as a complete HTML string.

        Args:
            structure: Page structure document with visual elements.
            content: Page content document with translated text.

        Returns:
            Complete HTML document string.
        """
        structure_page_list = [page.page_index for page in structure.pages]
        content_page_list = [page.page_index for page in content.pages]
        if structure.page_count != len(structure_page_list):
            raise ValueError("PageStructureDocument.page_count 与页面数量不一致")
        if content.page_count != len(content_page_list):
            raise ValueError("PageContentDocument.page_count 与页面数量不一致")
        if len(set(structure_page_list)) != len(structure_page_list):
            raise ValueError("PageStructureDocument 包含重复页面编号")
        if len(set(content_page_list)) != len(content_page_list):
            raise ValueError("PageContentDocument 包含重复页面编号")
        structure_page_ids = set(structure_page_list)
        content_page_ids = set(content_page_list)
        if page_visuals is not None and (
            not structure.source_sha256
            or structure.source_sha256 != content.source_sha256
        ):
            raise ValueError("页面结构与翻译内容来源 PDF 哈希不一致")
        if structure_page_ids != content_page_ids:
            missing = sorted(structure_page_ids - content_page_ids)
            extra = sorted(content_page_ids - structure_page_ids)
            raise ValueError(
                f"页面内容不完整：缺少 {missing}，多出 {extra}"
            )
        if page_visuals is not None and set(page_visuals) != structure_page_ids:
            missing = sorted(structure_page_ids - set(page_visuals))
            extra = sorted(set(page_visuals) - structure_page_ids)
            raise ValueError(
                f"页面视觉资源不完整：缺少 {missing}，多出 {extra}"
            )

        structure_map = {page.page_index: page for page in structure.pages}
        for page in content.pages:
            region_ids = {
                region.id for region in structure_map[page.page_index].text_regions
            }
            if len(region_ids) != len(structure_map[page.page_index].text_regions):
                raise ValueError(f"第 {page.page_index + 1} 页包含重复文本区域编号")
            block_ids: set[str] = set()
            for block in page.blocks:
                if block.id in block_ids:
                    raise ValueError(
                        f"第 {page.page_index + 1} 页包含重复内容块编号：{block.id}"
                    )
                block_ids.add(block.id)
                if block.region_id not in region_ids:
                    raise ValueError(
                        f"内容块 {block.id} 的 region 不存在：{block.region_id}"
                    )
                if block.translatable and not (block.translated_text or "").strip():
                    raise ValueError(f"内容块 {block.id} 缺少 translated_text")

        # Build page sections
        page_sections: list[str] = []
        content_map = {page.page_index: page for page in content.pages}

        for page_struct in structure.pages:
            page_content = content_map.get(page_struct.page_index)
            page_sections.append(
                self.rebuild_page(
                    page_struct,
                    page_content,
                    page_visual=(page_visuals or {}).get(page_struct.page_index),
                )
            )

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
            '<link rel="icon" href="data:,">',
            f"<title>{html.escape(self._document_title(structure))}</title>",
            f"<style>{css}</style>",
            "</head>",
            f'<body class="typeset-profile-{html.escape(self.config.profile_id)}">',
        ]
        if self.config.reading_html_href:
            parts.append(
                '<nav class="typeset-view-toolbar" aria-label="阅读视图">'
                f'<a href="{html.escape(self.config.reading_html_href, quote=True)}">切换到阅读版</a>'
                '</nav>'
            )
        parts.extend(page_sections)
        parts.append(build_typeset_browser_contract())
        parts.extend([
            "</body>",
            "</html>",
        ])
        return "\n".join(parts)

    def _build_fit_script(self) -> str:
        """Backward-compatible delegate to the browser contract module."""
        return build_typeset_browser_contract()

    def _build_global_css(self, page_width_in: float, page_height_in: float) -> str:
        """Build the global CSS stylesheet."""
        font_stack = self._font_stack()
        heading_font_stack = self._heading_font_stack()
        body_font_px = self._body_font_size_px()
        min_font_px = self._min_font_size_px()
        line_height = self.config.line_height
        text_indent = self.config.text_indent
        column_gap_px = _pt_to_px(self.config.column_gap_pt)

        font_dir = self.config.embedded_font_dir.replace("\\", "/").strip("/")
        return f"""
@font-face {{
    font-family: "DG Fandol Song";
    src: url("{font_dir}/fusion-fandol-song.woff2") format("woff2");
    font-style: normal;
    font-weight: 400;
    font-display: block;
}}
@font-face {{
    font-family: "DG Fandol Kai";
    src: url("{font_dir}/fusion-fandol-kai.woff2") format("woff2");
    font-style: normal;
    font-weight: 400;
    font-display: block;
}}
@font-face {{
    font-family: "DG Moushi Meili";
    src: url("{font_dir}/fusion-moushi-meili.woff2") format("woff2");
    font-style: normal;
    font-weight: 400;
    font-display: block;
}}
@font-face {{
    font-family: "DG Lanting Kanhei";
    src: url("{font_dir}/fusion-lanting-kanhei.woff2") format("woff2");
    font-style: normal;
    font-weight: 400;
    font-display: block;
}}
@font-face {{
    font-family: "DG Noto Serif SC";
    src: url("{font_dir}/noto-serif-sc-400.woff2") format("woff2");
    font-style: normal;
    font-weight: 400;
    font-display: block;
}}
@font-face {{
    font-family: "DG Noto Serif SC";
    src: url("{font_dir}/noto-serif-sc-700.woff2") format("woff2");
    font-style: normal;
    font-weight: 700;
    font-display: block;
}}
@font-face {{
    font-family: "DG Noto Sans SC";
    src: url("{font_dir}/noto-sans-sc-400.woff2") format("woff2");
    font-style: normal;
    font-weight: 400;
    font-display: block;
}}
@font-face {{
    font-family: "DG Noto Sans SC";
    src: url("{font_dir}/noto-sans-sc-700.woff2") format("woff2");
    font-style: normal;
    font-weight: 700;
    font-display: block;
}}
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
.typeset-view-toolbar {{
    width: min(100%, 960px);
    margin: 0 auto 12px;
    text-align: right;
}}
.typeset-view-toolbar a {{
    display: inline-block;
    padding: 7px 11px;
    border-radius: 4px;
    background: #f7f3eb;
    color: #231f20;
    font-family: {heading_font_stack};
    font-size: 14px;
    line-height: 1;
    text-decoration: none;
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
.typeset-page-visual-layer {{
    position: absolute;
    inset: 0;
    z-index: {Z_BACKGROUND};
    pointer-events: none;
}}
.typeset-page-visual {{
    display: block;
    width: 100%;
    height: 100%;
}}
.typeset-page-image-layer {{
    position: absolute;
    inset: 0;
    z-index: {Z_PAGE_IMAGES};
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
    overflow: visible;
}}
.typeset-positioned-block .typeset-body-text {{
    margin: 0;
    line-height: 1.4;
    text-indent: 0;
    overflow-wrap: anywhere;
    word-break: break-word;
}}
.typeset-positioned-block .typeset-heading {{
    margin: 0;
    line-height: 1.2;
    text-indent: 0;
    text-align: center;
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: normal;
}}
.typeset-kult-credit-block {{
    position: absolute;
    margin: 0;
    text-align: center;
    text-indent: 0;
    overflow-wrap: anywhere;
    word-break: break-word;
}}
.typeset-kult-credit-block--title {{
    font-family: {heading_font_stack};
    font-weight: 700;
    line-height: 1.05;
}}
.typeset-kult-credit-block--legal {{
    line-height: 1.18;
}}
.typeset-reflow-area {{
    position: absolute;
    overflow: visible;
    color: {self.config.body_color};
    font-size: {body_font_px:.3f}px;
}}
.typeset-reflow-columns {{
    display: flex;
    gap: {_pt_to_px(24.0):.3f}px;
    height: 100%;
}}
.typeset-reflow-column {{
    flex: 1;
    overflow: visible;
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
.typeset-full-width-hero-title {{
    position: absolute;
    margin: 0;
    overflow: hidden;
    font-family: {heading_font_stack};
    font-size: {_pt_to_px(self.config.display_font_size_pt):.3f}px;
    line-height: 1.05;
    font-weight: 700;
    text-align: left;
    text-indent: 0;
    overflow-wrap: anywhere;
}}
.typeset-full-width-hero-intro {{
    position: absolute;
    margin: 0;
    overflow: hidden;
    font-size: {body_font_px:.3f}px;
    line-height: {line_height};
    text-align: left;
    text-indent: 0;
    overflow-wrap: anywhere;
}}
.typeset-full-width-hero-intro.typeset-drop-cap::first-letter {{
    float: left;
    font-family: {heading_font_stack};
    font-size: 4.6em;
    line-height: .78;
    padding: .08em .06em 0 0;
    color: {self.config.subtitle_color};
}}
.typeset-reflow-section {{
    font-family: {heading_font_stack};
    font-size: {_pt_to_px(self.config.section_font_size_pt):.3f}px;
    line-height: 1.2;
    margin: 0 0 {_pt_to_px(7.0):.3f}px 0;
    font-weight: 700;
    text-indent: 0;
    text-align: left;
    color: {self.config.title_color};
}}
.typeset-reflow-subtitle {{
    font-family: {heading_font_stack};
    font-size: 1.37em;
    line-height: 1.25;
    margin: {_pt_to_px(10.0):.3f}px 0 {_pt_to_px(2.5):.3f}px 0;
    font-weight: 700;
    text-indent: 0;
    color: {self.config.subtitle_color};
}}
.typeset-reflow-subsection {{
    font-family: {heading_font_stack};
    font-size: {_pt_to_px(self.config.subsection_font_size_pt):.3f}px;
    line-height: 1.25;
    margin: {_pt_to_px(7.0):.3f}px 0 {_pt_to_px(4.0):.3f}px 0;
    font-weight: 700;
    text-indent: 0;
    color: inherit;
}}
.typeset-reflow-callout {{
    font-family: {heading_font_stack};
    font-size: {_pt_to_px(16.0):.3f}px;
    line-height: 1.2;
    margin: 0;
    font-weight: 700;
    text-indent: 0;
    text-align: center;
    color: {self.config.title_color};
}}
.typeset-reflow-body {{
    font-size: 1em;
    line-height: {line_height};
    margin: 0 0 0.34em 0;
    text-indent: {text_indent};
    text-align: left;
    line-break: strict;
    word-break: normal;
    overflow-wrap: anywhere;
}}
.font-role-display,
.font-role-section,
.font-role-subsection,
.font-role-running-header,
.font-role-callout {{
    font-family: {heading_font_stack};
}}
.font-role-body,
.font-role-meta {{
    font-family: {font_stack};
}}
.source-font-display-condensed {{
    font-family: "DG Moushi Meili", {font_stack} !important;
    font-weight: 400;
    letter-spacing: 0.015em;
}}
.source-font-geometric {{
    font-family: "DG Lanting Kanhei", {heading_font_stack} !important;
}}
.source-font-typewriter {{
    font-family: "DG Fandol Kai", {font_stack} !important;
    font-style: normal;
    letter-spacing: 0.025em;
}}
.source-font-literary {{
    font-family: {font_stack} !important;
}}
.source-style-italic {{
    font-style: italic;
}}
.source-style-bold {{
    font-weight: 700;
}}
.typeset-region-flow {{
    position: absolute;
    overflow: visible;
    color: {self.config.body_color};
    font-size: {body_font_px:.3f}px;
    line-height: {line_height};
}}
.typeset-region-flow .typeset-reflow-body {{
    line-height: {line_height};
    margin-bottom: 0.34em;
}}
.typeset-region-flow > :first-child {{
    margin-top: 0;
}}
.typeset-region-flow > :last-child {{
    margin-bottom: 0;
}}
.typeset-region-flow .typeset-reflow-body.source-font-geometric {{
    font-size: {_pt_to_px(10.0):.3f}px;
    line-height: 1.25;
    margin-bottom: 0.18em;
}}
.typeset-region-flow .typeset-reflow-title {{
    margin: {_pt_to_px(10.0):.3f}px 0 {_pt_to_px(10.0):.3f}px 0;
}}
.typeset-page[data-template="single_source_flow"] .typeset-reflow-area {{
    font-size: {_pt_to_px(10.0):.3f}px;
    line-height: 1.35;
}}
.typeset-page[data-template="single_source_flow"] .typeset-reflow-area .typeset-reflow-body {{
    line-height: 1.35;
    margin-bottom: 0.15em;
}}
.typeset-region-flow.typeset-list-flow {{
    font-size: {_pt_to_px(10.0):.3f}px;
    line-height: 1.35;
}}
.typeset-region-flow.typeset-list-flow .typeset-reflow-body {{
    font-size: {_pt_to_px(10.0):.3f}px;
    line-height: 1.35;
    margin-bottom: 0.1em;
}}
.typeset-region-flow.typeset-compact-flow {{
    font-size: {_pt_to_px(9.0):.3f}px;
    line-height: 1.25;
}}
.typeset-region-flow.typeset-compact-flow .typeset-reflow-body {{
    font-size: {_pt_to_px(9.0):.3f}px;
    line-height: 1.25;
    margin-bottom: 0.05em;
    text-indent: 0;
}}
.typeset-rotated-flow {{
    position: absolute;
    overflow: visible;
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
.typeset-rotated-flow.typeset-rotated-compact {{
    font-size: {_pt_to_px(8.25):.3f}px;
    line-height: 1.15;
}}
.typeset-rotated-flow.typeset-rotated-compact .typeset-reflow-body {{
    line-height: 1.15;
    margin-bottom: 0.08em;
}}
.typeset-timeline-intro {{
    position: absolute;
    overflow: visible;
    font-size: {body_font_px:.3f}px;
    line-height: 1.35;
    color: {self.config.body_color};
}}
.typeset-timeline-flow {{
    position: absolute;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    overflow: visible;
    font-size: {_pt_to_px(8.8):.3f}px;
    line-height: 1.28;
    color: {self.config.body_color};
}}
.typeset-timeline-event {{
    margin: 0 0 {_pt_to_px(5.0):.3f}px 0;
    text-indent: 0;
    background: rgba(239, 235, 220, 0.92);
}}
.typeset-timeline-date {{
    padding: 0 {_pt_to_px(2.0):.3f}px {_pt_to_px(1.5):.3f}px;
    border-bottom: 1px solid #1d1d1d;
    font-family: {heading_font_stack};
    font-size: 1.08em;
    font-weight: 700;
    line-height: 1.12;
}}
.typeset-timeline-body {{
    padding: {_pt_to_px(2.0):.3f}px {_pt_to_px(5.0):.3f}px 0;
    line-height: 1.25;
}}
.typeset-line-track-flow {{
    position: absolute;
    inset: 0;
    color: {self.config.body_color};
}}
.typeset-structured-table {{
    position: absolute;
    overflow: visible;
    z-index: 2;
    background: #f2f0ea;
    border: 1px solid #202426;
    box-shadow: 0 2px 5px rgba(0, 0, 0, 0.22);
    color: #17191a;
    font-family: {font_stack};
    font-size: {_pt_to_px(self.config.table_font_size_pt):.3f}px;
    line-height: 1.15;
}}
.typeset-structured-table table {{
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
}}
.typeset-structured-table th {{
    padding: {_pt_to_px(2.4):.3f}px {_pt_to_px(3.0):.3f}px;
    background: #282d2f;
    border-right: 1px solid rgba(255, 255, 255, 0.22);
    color: #fff;
    font-family: {heading_font_stack};
    font-weight: 700;
    line-height: 1.05;
    text-align: left;
    vertical-align: bottom;
}}
.typeset-structured-table td {{
    padding: {_pt_to_px(1.7):.3f}px {_pt_to_px(3.0):.3f}px;
    border-right: 1px solid rgba(34, 38, 40, 0.18);
    border-bottom: 1px solid rgba(34, 38, 40, 0.25);
    vertical-align: top;
    overflow-wrap: anywhere;
}}
.typeset-structured-table.typeset-table-compact {{
    font-size: {_pt_to_px(7.5):.3f}px;
    line-height: 1.05;
}}
.typeset-structured-table.typeset-table-compact th {{
    padding: {_pt_to_px(1.4):.3f}px {_pt_to_px(2.0):.3f}px;
    line-height: 1.0;
}}
.typeset-structured-table.typeset-table-compact td {{
    padding: {_pt_to_px(1.0):.3f}px {_pt_to_px(2.0):.3f}px;
}}
.typeset-structured-table tbody tr:nth-child(even):not(.typeset-table-note) td {{
    background: rgba(183, 188, 190, 0.48);
}}
.typeset-structured-table .typeset-table-note td {{
    padding-top: {_pt_to_px(3.0):.3f}px;
    padding-bottom: {_pt_to_px(3.0):.3f}px;
    background: #f2f0ea;
    font-size: 0.86em;
    font-style: italic;
    line-height: 1.2;
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
    margin-bottom: 0.72em;
}}
.typeset-drop-cap::first-letter {{
    float: left;
    font-family: {heading_font_stack};
    font-size: 3.15em;
    font-weight: 700;
    line-height: 0.78;
    margin: 0.06em 0.10em 0 0;
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
        zoom: 1 !important;
    }}
    .typeset-view-toolbar {{ display: none; }}
}}
@media screen and (max-width: 840px) {{
    body {{
        padding: 12px;
        overflow-x: hidden;
    }}
}}
"""

    def rebuild_page(
        self,
        page_structure: PageStructure,
        page_content: PageContent,
        page_visual: str | None = None,
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

        # A clean page SVG is the authoritative visual layer.  It preserves
        # the PDF's images, vector art, clipping, masks and paint order while
        # the translated text remains searchable HTML above it.
        if page_visual:
            parts.append(self.render_page_visual_layer(page_visual, page_structure.page_index))
        else:
            parts.append(self.render_background_layer(page_structure.background))
            page_images = [] if self._is_dense_line_grid_page(page_structure) else page_structure.images
            parts.append(self.render_image_layer(page_images, page_structure))
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

    def render_image_layer(
        self,
        images: list[ImageElement],
        page_structure: PageStructure | None = None,
    ) -> str:
        """
        Render the image layer HTML, placing images at original coordinates.

        Args:
            images: List of image elements with bounding boxes.

        Returns:
            HTML string for the image layer.
        """
        images = [image for image in images if self._is_valid_image_bbox(image.bbox)]
        if not images:
            return '<div class="typeset-image-layer"></div>'

        if page_structure is not None:
            page_images = [
                image for image in images
                if self._is_full_page_image(image.bbox, page_structure)
            ]
            foreground_images = [
                image for image in images
                if not self._is_full_page_image(image.bbox, page_structure)
            ]
            return "\n".join([
                self._render_image_layer_div(page_images, "typeset-page-image-layer"),
                self._render_image_layer_div(foreground_images, "typeset-image-layer"),
            ])

        return self._render_image_layer_div(images, "typeset-image-layer")

    def _render_image_layer_div(
        self,
        images: list[ImageElement],
        class_name: str,
    ) -> str:
        parts: list[str] = [f'<div class="{class_name}">']
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
            hidden_ids = occluded_duplicate_block_ids(page_content, page_structure)
            if hidden_ids:
                page_content = replace(
                    page_content,
                    blocks=[
                        block
                        for block in page_content.blocks
                        if block.id not in hidden_ids
                    ],
                )
            self._current_template = select_typeset_template(page_content, page_structure)
            if page_content.page_type == PageType.ART:
                parts.append(self._render_art_fixed_text(page_content, page_structure))
                parts.append("</div>")
                return "\n".join(parts)
            if page_content.page_type == PageType.COVER:
                parts.append(self._render_art_fixed_text(page_content, page_structure))
                parts.append("</div>")
                return "\n".join(parts)
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

    def _render_art_fixed_text(
        self,
        page_content: PageContent,
        page_structure: PageStructure,
    ) -> str:
        """Keep fixed chrome and translated cover naming on art pages."""
        region_map = {region.id: region.bbox for region in page_structure.text_regions}
        parts: list[str] = []
        is_cover = self._is_art_cover_page(page_content)
        for block in page_content.blocks:
            bbox = block.bbox or region_map.get(block.region_id)
            if bbox is None:
                continue
            if self._is_running_header(block):
                parts.append(self._render_running_header(block, page_structure, bbox))
            elif self._is_fixed_page_number(block):
                parts.append(self._render_fixed_page_number(block, bbox))
            elif is_cover and self._display_text_for_block(block):
                parts.append(self._render_art_cover_block(block, page_structure, bbox))
        return "\n".join(parts)

    def _is_art_cover_page(self, page_content: PageContent) -> bool:
        if page_content.page_index != 0:
            return False
        naming_blocks = [
            block
            for block in page_content.blocks
            if block.translatable
            and block.role not in {SemanticRole.HEADER, SemanticRole.FOOTER}
            and self._display_text_for_block(block)
        ]
        return (
            len(naming_blocks) >= 2
            and any(self._get_block_font_size(block) >= 24.0 for block in naming_blocks)
        )

    def _render_art_cover_block(
        self,
        block: ContentBlock,
        page_structure: PageStructure,
        bbox: list[float],
    ) -> str:
        x0, y0, x1, y1 = bbox
        source_size = self._get_block_font_size(block)
        is_title = source_size >= 24.0
        text = self._display_text_for_block(block)
        if is_title:
            text = text.removeprefix("《").removesuffix("》")
        font_size_pt = (
            min(source_size, self.config.display_font_size_pt)
            if is_title
            else min(source_size, self.config.accent_font_size_pt)
        )
        is_kult_cover = self.config.profile_id == "kult"
        if is_kult_cover:
            font_size_pt = source_size
        background = "background:rgba(22,30,30,.92);" if is_title and not is_kult_cover else ""
        color = self.config.subtitle_color if is_kult_cover else "#ffffff"
        text_shadow = "none" if is_kult_cover else "0 1px 3px rgba(0,0,0,.95)"
        return (
            f'<div class="typeset-positioned-block '
            f'{"source-font-display-condensed" if is_title else "source-font-geometric"}" '
            f'data-block-id="{html.escape(block.id)}" '
            f'data-region-id="{html.escape(block.region_id)}" '
            f'data-fit="text" '
            f'style="left:{_pt_to_px_str(x0)};top:{_pt_to_px_str(y0)};'
            f'width:{_pt_to_px_str(max(1.0, x1 - x0))};'
            f'height:{_pt_to_px_str(max(1.0, y1 - y0))};'
            f'font-size:{_pt_to_px_str(font_size_pt)};line-height:1;'
            f'display:flex;align-items:center;justify-content:center;'
            f'{background}'
            f'text-align:center;white-space:normal;overflow-wrap:anywhere;line-height:1.2;color:{color};'
            f'font-weight:400;text-shadow:{text_shadow}">'
            f"{html.escape(text)}</div>"
        )

    def render_page_visual_layer(self, page_visual: str, page_index: int) -> str:
        """Render the verified text-free SVG for one source page."""
        return (
            '<div class="typeset-page-visual-layer">'
            f'<img class="typeset-page-visual" '
            f'src="{html.escape(page_visual)}" alt="" '
            f'data-visual-page="{page_index + 1}">'
            '</div>'
        )

    def _is_valid_image_bbox(self, bbox: list[float]) -> bool:
        if len(bbox) != 4:
            return False
        x0, y0, x1, y1 = bbox
        return x1 > x0 and y1 > y0

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
        if self._is_kult_credits_page(page_content, page_structure, region_map):
            return self._render_kult_credits_page(page_content, page_structure, region_map)
        fixed_parts: list[str] = []
        fixed_obstacles: list[list[float]] = []
        rotated_blocks: list[ContentBlock] = []
        content_blocks: list[ContentBlock] = []
        source_page_blocks = [
            block for block in page_content.blocks if block.region_id in region_map
        ]
        template = getattr(self, "_current_template", None)
        is_full_width_hero = bool(template and template.id == "full_width_hero")
        table_groups: list[list[ContentBlock]] = []
        current_table_group: list[ContentBlock] = []
        for block in source_page_blocks:
            if block.role == SemanticRole.TABLE:
                current_table_group.append(block)
                continue
            if current_table_group:
                table_groups.append(current_table_group)
                current_table_group = []
        if current_table_group:
            table_groups.append(current_table_group)
        likely_events_groups = self._likely_events_table_groups(source_page_blocks, region_map)
        table_groups.extend(likely_events_groups)
        likely_events_keys = {
            tuple(block.id for block in group)
            for group in likely_events_groups
        }
        table_block_ids = {
            block.id
            for group in table_groups
            for block in group
        }

        if not table_block_ids and self._is_timeline_page(source_page_blocks):
            timeline_blocks: list[ContentBlock] = []
            for block in source_page_blocks:
                bbox = block.bbox or region_map.get(block.region_id)
                if bbox is None:
                    continue
                if self._is_running_header(block):
                    fixed_parts.append(self._render_running_header(block, page_structure, bbox))
                elif self._is_fixed_page_number(block):
                    fixed_parts.append(self._render_fixed_page_number(block, bbox))
                elif block.role != SemanticRole.FOOTER and self._display_text_for_block(block):
                    timeline_blocks.append(block)
            return "\n".join([
                self._render_timeline_page(timeline_blocks, region_map, page_structure),
                *fixed_parts,
            ])
        table_blocks = [block for group in table_groups for block in group]
        if self._is_dense_line_grid_page(page_structure) and not table_blocks:
            parts = []
            for block in source_page_blocks:
                render_block = block
                if abs(self._region_angle(block.region_id, page_structure)) >= 1.0:
                    render_block = self._source_text_block(block)
                if not self._display_text_for_block(render_block):
                    continue
                parts.append(
                    self._render_positioned_single_block(
                        render_block,
                        page_structure,
                        block.bbox or region_map[block.region_id],
                    )
                )
            return "\n".join(parts)
        page_blocks = self._dedupe_content_blocks(
            [block for block in source_page_blocks if block.id not in table_block_ids],
            region_map,
        ) + table_blocks
        for table_group in table_groups:
            table_bbox = _union_block_bboxes(table_group, region_map)
            fixed_parts.append(
                self._render_structured_table(
                    table_group,
                    page_structure,
                    compact=tuple(block.id for block in table_group) in likely_events_keys,
                )
            )
            fixed_obstacles.append(table_bbox)
        rotated_flow_count = sum(
            1
            for block in page_blocks
            if self._is_flow_body_block(block)
            and abs(self._region_angle(block.region_id, page_structure)) >= 1.0
        )
        tilted_card_count = sum(
            1
            for block in page_blocks
            if self._is_tilted_card_block(block, page_structure)
        )

        for block in page_blocks:
            bbox = block.bbox or region_map.get(block.region_id)
            if bbox is None:
                continue
            if block.id in table_block_ids:
                continue
            if self._is_running_header(block):
                fixed_parts.append(self._render_running_header(block, page_structure, bbox))
                fixed_obstacles.append(bbox)
                continue
            if self._is_fixed_page_number(block):
                fixed_parts.append(self._render_fixed_page_number(block, bbox))
                fixed_obstacles.append(bbox)
                continue
            if block.role == SemanticRole.FOOTER:
                continue
            if block.role == SemanticRole.TABLE:
                continue
            if block.role == SemanticRole.TITLE:
                if is_full_width_hero:
                    fixed_parts.append(self._render_full_width_hero_title(block, bbox))
                else:
                    fixed_parts.append(self._render_source_positioned_block(block, page_structure, bbox))
                fixed_obstacles.append(bbox)
                continue
            if is_full_width_hero and block.layout_mode == "drop_cap":
                fixed_parts.append(self._render_full_width_hero_intro(block, bbox))
                fixed_obstacles.append(bbox)
                continue
            if self._is_bottom_credit_block(block, bbox, page_structure):
                fixed_parts.append(self._render_source_positioned_block(block, page_structure, bbox))
                fixed_obstacles.append(bbox)
                continue
            if self._should_position_light_foreground_block(block, bbox, page_structure):
                if not self._is_same_region_reflow_block(block, page_blocks, region_map):
                    fixed_parts.append(self._render_source_positioned_block(block, page_structure, bbox))
                    fixed_obstacles.append(bbox)
                    continue
            if abs(self._region_angle(block.region_id, page_structure)) >= 1.0:
                if tilted_card_count >= 3 and self._is_tilted_card_block(block, page_structure):
                    rotated_blocks.append(block)
                    continue
                if self._is_flow_body_block(block) and rotated_flow_count >= 3:
                    if self._display_text_for_block(block):
                        rotated_blocks.append(block)
                elif self._display_text_for_block(block):
                    fixed_parts.append(self._render_positioned_single_block(block, page_structure, bbox))
                    fixed_obstacles.append(bbox)
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
            key=lambda block: (
                (block.bbox or region_map[block.region_id])[1],
                (block.bbox or region_map[block.region_id])[0],
                block.order,
            ),
        )
        flow_items = self._build_reflow_items(content_blocks)
        if not flow_items:
            return "\n".join(fixed_parts)
        content_blocks = [block for block, _ in flow_items]
        text_by_id = {block.id: text for block, text in flow_items}
        same_region_parts, content_blocks, same_region_bboxes = self._render_same_region_flows(
            content_blocks,
            text_by_id,
            region_map,
            page_structure,
        )
        fixed_parts.extend(same_region_parts)
        fixed_obstacles.extend(same_region_bboxes)
        if not content_blocks:
            return "\n".join(fixed_parts)
        if self._is_stacked_card_page(content_blocks, region_map, page_structure):
            return "\n".join([
                *[
                    self._render_positioned_single_block(
                        block,
                        page_structure,
                        block.bbox or region_map[block.region_id],
                    )
                    for block in content_blocks
                ],
                *fixed_parts,
            ])
        if self._is_centered_stack_page(content_blocks, region_map, page_structure):
            return "\n".join([
                *[
                    self._render_source_positioned_block(
                        block,
                        page_structure,
                        block.bbox or region_map[block.region_id],
                    )
                    for block in content_blocks
                ],
                *fixed_parts,
            ])

        source_region_html = self._render_source_region_flows(
            page_content,
            page_structure,
            content_blocks,
            text_by_id,
            region_map,
            fixed_parts,
            fixed_obstacles,
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

    def _render_full_width_hero_title(
        self,
        block: ContentBlock,
        bbox: list[float],
    ) -> str:
        """Render a chapter opener title as one deliberate display region."""
        x0, y0, x1, y1 = bbox
        text = self._display_text_for_block(block)
        return (
            '<h1 class="typeset-full-width-hero-title" '
            f'data-block-id="{html.escape(block.id)}" data-fit="text" '
            f'style="left:{_pt_to_px_str(x0)};top:{_pt_to_px_str(y0)};'
            f'width:{_pt_to_px_str(x1 - x0)};height:{_pt_to_px_str(y1 - y0)};'
            f'color:{html.escape(self.config.title_color)}">'
            f'{html.escape(text)}</h1>'
        )

    def _render_full_width_hero_intro(
        self,
        block: ContentBlock,
        bbox: list[float],
    ) -> str:
        """Render the opening paragraph separately so the drop cap stays intact."""
        x0, y0, x1, y1 = bbox
        text = self._display_text_for_block(block)
        return (
            '<p class="typeset-full-width-hero-intro typeset-drop-cap" '
            f'data-block-id="{html.escape(block.id)}" data-fit="reflow" '
            f'style="left:{_pt_to_px_str(x0)};top:{_pt_to_px_str(y0)};'
            f'width:{_pt_to_px_str(x1 - x0)};height:{_pt_to_px_str(y1 - y0)};'
            f'color:{html.escape(self._block_text_color(block))}">'
            f'{self._format_body_text(block, text)}</p>'
        )

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

    def _is_kult_credits_page(
        self,
        page_content: PageContent,
        page_structure: PageStructure,
        region_map: dict[str, list[float]],
    ) -> bool:
        """Recognize the KULT imprint page from its source geometry, not its page number."""
        if self.config.profile_id != "kult":
            return False
        visible = [
            block for block in page_content.blocks
            if block.region_id in region_map and self._display_text_for_block(block)
        ]
        title_count = sum(
            self._get_block_font_size(block) >= 30.0
            for block in visible
        )
        credit_count = sum(
            0.14 * page_structure.height <= (block.bbox or region_map[block.region_id])[1]
            <= 0.62 * page_structure.height
            for block in visible
        )
        return title_count == 1 and credit_count >= 12

    def _render_kult_credits_page(
        self,
        page_content: PageContent,
        page_structure: PageStructure,
        region_map: dict[str, list[float]],
    ) -> str:
        """Render KULT's three-column imprint without forcing it through body reflow."""
        parts: list[str] = []
        width = page_structure.width
        for block in page_content.blocks:
            bbox = block.bbox or region_map.get(block.region_id)
            text = self._display_text_for_block(block)
            if bbox is None or not text or block.role in {SemanticRole.HEADER, SemanticRole.FOOTER}:
                continue
            x0, y0, x1, _ = bbox
            source_size = self._get_block_font_size(block)
            center = (x0 + x1) / 2.0
            classes = ["typeset-kult-credit-block"]
            if source_size >= 30.0:
                left, block_width = width * 0.12, width * 0.76
                font_size = source_size
                classes.append("typeset-kult-credit-block--title")
            elif y0 >= page_structure.height * 0.72:
                left, block_width = width * 0.12, width * 0.76
                font_size = min(max(source_size, 7.2), 8.2)
                classes.append("typeset-kult-credit-block--legal")
            else:
                lane_width = width * 0.255
                if center < width / 3.0:
                    left = width * 0.07
                elif center > width * 2.0 / 3.0:
                    left = width * 0.675
                else:
                    left = (width - lane_width) / 2.0
                block_width = lane_width
                font_size = min(max(source_size, 8.0), 9.4)
            parts.append(
                f'<div class="{" ".join(classes)}" '
                f'data-block-id="{html.escape(block.id)}" '
                f'style="left:{_pt_to_px_str(left)};top:{_pt_to_px_str(y0)};'
                f'width:{_pt_to_px_str(block_width)};'
                f'font-size:{_pt_to_px_str(font_size)};'
                f'color:{html.escape(self._block_text_color(block))}">'
                f'{self._format_text(text)}</div>'
            )
        return "\n".join(parts)

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
        if self._box_area_ratio(flow_area, page_structure) > 0.12:
            return ""
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
        fixed_obstacles: list[list[float]],
    ) -> str:
        """Render Chinese text in source-derived regions instead of one large box."""
        if len(page_content.columns) < 2:
            return ""

        region_by_id = {region.id: region for region in page_structure.text_regions}
        self._current_region_by_id = region_by_id
        parts = list(fixed_parts)
        consumed: set[str] = set()
        positioned_bboxes: list[list[float]] = list(fixed_obstacles)

        for block in content_blocks:
            region = region_by_id.get(block.region_id)
            bbox = block.bbox or region_map.get(block.region_id)
            if region is None or bbox is None:
                continue
            if self._is_source_positioned_heading(block, region, page_structure, page_content):
                block_bbox = block.bbox or bbox
                parts.append(self._render_source_positioned_block(block, page_structure, block_bbox))
                positioned_bboxes.append(block_bbox)
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
                        block.bbox or region_map[block.region_id],
                        [block],
                        text_by_id,
                        region_map,
                        page_structure,
                        collision_bbox=block.bbox or region_map[block.region_id],
                    ))
                consumed.update(block.id for block in column_blocks)
                continue
            for flow_bbox, flow_blocks in self._split_column_at_obstacles(
                column.bbox,
                column_blocks,
                positioned_bboxes,
                region_map,
            ):
                column_parts.append(self._render_source_column_flow(
                    column.side,
                    flow_bbox,
                    flow_blocks,
                    text_by_id,
                    region_map,
                    page_structure,
                    collision_bbox=flow_bbox,
                ))
            consumed.update(block.id for block in column_blocks)

        for block in content_blocks:
            if block.id in consumed:
                continue
            bbox = block.bbox or region_map.get(block.region_id)
            if bbox is None:
                continue
            parts.append(self._render_source_positioned_block(block, page_structure, bbox))
            consumed.add(block.id)

        if not column_parts:
            return ""
        return "\n".join([*column_parts, *parts])

    def _is_same_region_reflow_block(
        self,
        block: ContentBlock,
        page_blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
    ) -> bool:
        group = [
            item
            for item in page_blocks
            if item.region_id == block.region_id and item.role == SemanticRole.BODY_COLUMN
        ]
        return self._is_same_region_reflow_group(group, region_map)

    def _is_same_region_reflow_group(
        self,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
    ) -> bool:
        if len(blocks) < 3 or any(block.role != SemanticRole.BODY_COLUMN for block in blocks):
            return False
        boxes = [block.bbox or region_map[block.region_id] for block in blocks]
        return max(box[3] for box in boxes) - min(box[1] for box in boxes) >= 24.0

    def _render_same_region_flows(
        self,
        content_blocks: list[ContentBlock],
        text_by_id: dict[str, str],
        region_map: dict[str, list[float]],
        page_structure: PageStructure,
    ) -> tuple[list[str], list[ContentBlock], list[list[float]]]:
        """Keep fragmented text inside one source region in one natural flow."""
        groups: dict[str, list[ContentBlock]] = {}
        for block in content_blocks:
            if block.id in text_by_id:
                groups.setdefault(block.region_id, []).append(block)

        consumed: set[str] = set()
        parts: list[str] = []
        bboxes: list[list[float]] = []
        for group in groups.values():
            if not self._is_same_region_reflow_group(group, region_map):
                continue
            ordered = sorted(
                group,
                key=lambda block: (
                    (block.bbox or region_map[block.region_id])[1],
                    (block.bbox or region_map[block.region_id])[0],
                    block.order,
                ),
            )
            flow_bbox = _union_block_bboxes(ordered, region_map)
            heading_blocks = [block for block in ordered if self._block_is_short_heading(block)]
            body_blocks = [block for block in ordered if block not in heading_blocks]
            inner_parts = [
                part
                for block in heading_blocks
                if (part := self._render_reflow_block(block, text_by_id[block.id]))
            ]
            if body_blocks:
                flow_text = " ".join(text_by_id[block.id] for block in body_blocks).strip()
                if flow_text:
                    part = self._render_reflow_block(body_blocks[0], flow_text)
                    if part:
                        inner_parts.append(part)
            inner = "\n".join(inner_parts)
            if not inner:
                continue
            x0, y0, x1, y1 = self._expanded_column_bbox(flow_bbox)
            flow_block_ids = ",".join(block.id for block in ordered)
            parts.append(
                '<div class="typeset-region-flow typeset-same-region-flow" '
                f'data-region-id="{html.escape(ordered[0].region_id)}" '
                f'data-flow-blocks="{html.escape(flow_block_ids)}" '
                f'data-fit="reflow" '
                f'style="left:{_pt_to_px_str(x0)};top:{_pt_to_px_str(y0)};'
                f'width:{_pt_to_px_str(x1 - x0)};height:{_pt_to_px_str(y1 - y0)};'
                f'color:{html.escape(self._group_text_color(ordered))}">'
                f"{inner}</div>"
            )
            bboxes.append([x0, y0, x1, y1])
            consumed.update(block.id for block in ordered)

        return (
            parts,
            [block for block in content_blocks if block.id not in consumed],
            bboxes,
        )

    def _split_column_at_obstacles(
        self,
        column_bbox: list[float],
        blocks: list[ContentBlock],
        positioned_bboxes: list[list[float]],
        region_map: dict[str, list[float]],
    ) -> list[tuple[list[float], list[ContentBlock]]]:
        x0, y0, x1, y1 = column_bbox
        obstacles = sorted(
            [
                obstacle
                for obstacle in positioned_bboxes
                if (
                    obstacle[3] > y0
                    and obstacle[1] < y1
                    and min(x1, obstacle[2]) - max(x0, obstacle[0])
                    >= min(x1 - x0, obstacle[2] - obstacle[0]) * 0.2
                )
            ],
            key=lambda obstacle: obstacle[1],
        )
        ordered = sorted(
            blocks,
            key=lambda block: (
                (block.bbox or region_map[block.region_id])[1],
                (block.bbox or region_map[block.region_id])[0],
                block.order,
            ),
        )
        groups: dict[int, list[ContentBlock]] = {}
        for block in ordered:
            bbox = block.bbox or region_map[block.region_id]
            center_y = (bbox[1] + bbox[3]) / 2
            section = sum(1 for obstacle in obstacles if center_y >= obstacle[3])
            groups.setdefault(section, []).append(block)

        result: list[tuple[list[float], list[ContentBlock]]] = []
        for section, group in sorted(groups.items()):
            group_boxes = [block.bbox or region_map[block.region_id] for block in group]
            top = max(y0, min(bbox[1] for bbox in group_boxes))
            next_obstacle_top = (
                obstacles[section][1]
                if section < len(obstacles)
                else y1
            )
            bottom = min(y1, max(max(bbox[3] for bbox in group_boxes), next_obstacle_top - 3.0))
            if bottom <= top:
                raise ValueError("正文分段区域高度无效")
            result.append(([x0, top, x1, bottom], group))
        return result

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
        block_bbox = block.bbox or region_map.get(block.region_id)
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
            text_color = self._group_text_color(ordered)
            flow_class = "typeset-rotated-flow"
            if (
                text_color.lower() == "#ffffff"
                or self._overlaps_foreground_image([x0, y0, x1, y1], page_structure)
            ):
                flow_class += " typeset-rotated-compact"
            flow_block_ids = ",".join(block.id for block in ordered)
            rendered.append(
                f'<div class="{flow_class}" '
                f'data-flow-blocks="{html.escape(flow_block_ids)}" '
                f'data-fit="reflow" '
                f'style="left:{_px(left)};top:{_px(top)};'
                f'width:{_px(width)};height:{_px(height)};'
                f'color:{html.escape(text_color)};'
                f'transform-origin:center center;'
                f'transform:rotate({self._reflow_group_angle(ordered, angle):.3f}deg)">'
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
        collision_bbox: list[float] | None = None,
    ) -> str:
        x0, y0, x1, y1 = self._expanded_column_bbox(bbox)
        left = _pt_to_px(x0)
        top = _pt_to_px(y0)
        width = _pt_to_px(max(0.0, x1 - x0))
        height = _pt_to_px(max(0.0, y1 - y0))
        ordered = sorted(
            blocks,
            key=lambda block: (
                (block.bbox or region_map[block.region_id])[1],
                (block.bbox or region_map[block.region_id])[0],
                block.order,
            ),
        )
        inner = "\n".join(
            self._render_reflow_block(block, text_by_id[block.id])
            for block in ordered
            if block.id in text_by_id
        )
        body_blocks = [
            block for block in ordered
            if block.font_role in {FontRole.BODY, FontRole.META}
        ]
        flow_classes = (
            " typeset-image-float-flow"
            if any(block.layout_mode == "image_float" for block in body_blocks)
            else ""
        )
        if any("»" in (block.source_text or "") for block in body_blocks):
            flow_classes += " typeset-list-flow"
        is_stat_flow = any(
            re.search(r"\bSTR\s+\d", block.source_text or "")
            for block in body_blocks
        )
        if body_blocks and (
            is_stat_flow
            or bool(flow_classes)
            or all(
                self._source_font_class(block) == "source-font-geometric"
                for block in body_blocks
            )
        ):
            flow_classes += " typeset-compact-flow"
        return (
            f'<div class="typeset-region-flow{flow_classes}" '
            f'data-column="{html.escape(side)}" '
            f'data-fit="reflow" '
            f'style="left:{_px(left)};top:{_px(top)};'
            f'width:{_px(width)};height:{_px(height)};'
            f'color:{html.escape(self._group_text_color(ordered))}">'
            f"{inner}</div>"
        )

    def _is_timeline_page(self, blocks: list[ContentBlock]) -> bool:
        return sum(
            len(self._timeline_date_lines(block.source_text or block.translated_text or ""))
            for block in blocks
        ) >= 5

    def _likely_events_table_groups(
        self,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
    ) -> list[list[ContentBlock]]:
        """Find the four-column Likely Events tables from their source geometry."""
        by_region: dict[str, list[ContentBlock]] = {}
        for block in blocks:
            if block.region_id in region_map:
                by_region.setdefault(block.region_id, []).append(block)
        region_groups = sorted(
            by_region.values(),
            key=lambda group: min((block.bbox or region_map[block.region_id])[1] for block in group),
        )

        tables: list[list[ContentBlock]] = []
        index = 0
        while index < len(region_groups):
            header = self._table_data_blocks(region_groups[index])
            if not self._is_likely_events_table_header(header, region_map):
                index += 1
                continue
            header_centers = self._table_group_centers(header, region_map)
            rows = [header]
            cursor = index + 1
            while cursor < len(region_groups):
                row = self._table_data_blocks(region_groups[cursor])
                if self._is_likely_events_table_header(row, region_map):
                    break
                if not self._matches_likely_events_table_row(row, header_centers, region_map):
                    break
                rows.append(row)
                cursor += 1
            if len(rows) >= 2:
                tables.append([block for row in rows for block in row])
                index = cursor
            else:
                index += 1
        return tables

    def _table_data_blocks(self, blocks: list[ContentBlock]) -> list[ContentBlock]:
        """Exclude titles that share a PDF text region with a table row.

        Page numbers at the bottom of the source page may be classified as
        footers even though they are the second column of the last table rows;
        keeping them here lets the structured-table mapper place them back in
        the page column.
        """
        return [
            block
            for block in blocks
            if block.role != SemanticRole.TITLE
        ]

    def _is_likely_events_table_header(
        self,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
    ) -> bool:
        if len(blocks) != 4:
            return False
        labels = [
            _normalized_text(block.source_text).lower()
            for block in sorted(blocks, key=lambda block: (block.bbox or region_map[block.region_id])[0])
        ]
        return labels == ["reaction", "page", "likeliestdate", "location"]

    def _table_group_centers(
        self,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
    ) -> list[float]:
        return [
            ((block.bbox or region_map[block.region_id])[0] + (block.bbox or region_map[block.region_id])[2]) / 2
            for block in sorted(blocks, key=lambda block: (block.bbox or region_map[block.region_id])[0])
        ]

    def _matches_likely_events_table_row(
        self,
        blocks: list[ContentBlock],
        header_centers: list[float],
        region_map: dict[str, list[float]],
    ) -> bool:
        if len(blocks) < 4 or len(header_centers) != 4:
            return False
        centers = self._table_group_centers(blocks, region_map)
        if any(right - left < 4.0 for left, right in zip(centers, centers[1:])):
            return False
        assignments = [
            min(range(len(header_centers)), key=lambda column: abs(center - header_centers[column]))
            for center in centers
        ]
        if set(assignments) != set(range(len(header_centers))):
            return False
        return all(
            abs(center - header_centers[column]) <= 100.0
            for center, column in zip(centers, assignments)
        )

    def _looks_like_timeline_event(self, block: ContentBlock) -> bool:
        return bool(self._timeline_date_lines(block.source_text or block.translated_text or ""))

    def _timeline_date_lines(self, text: str) -> list[str]:
        return [
            line
            for line in (part.strip() for part in text.replace("\r", "").split("\n"))
            if _TIMELINE_DATE_LINE_RE.fullmatch(line)
        ]

    def _timeline_events_for_blocks(
        self,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
    ) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        current_date = ""
        description: list[str] = []
        ordered = sorted(
            blocks,
            key=lambda block: (
                (block.bbox or region_map[block.region_id])[1],
                (block.bbox or region_map[block.region_id])[0],
                block.order,
            ),
        )
        for block in ordered:
            text = self._display_text_for_block(block)
            for line in (part.strip() for part in text.replace("\r", "").split("\n")):
                if not line:
                    continue
                if _TIMELINE_DATE_LINE_RE.fullmatch(line):
                    if current_date:
                        events.append((current_date, " ".join(description).strip()))
                    current_date = line
                    description = []
                else:
                    description.append(line)
        if current_date:
            events.append((current_date, " ".join(description).strip()))
        return events

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
            parts.extend(
                self._render_source_positioned_block(
                    block,
                    page_structure,
                    block.bbox or region_map[block.region_id],
                )
                for block in intro_blocks
            )

        midpoint = page_structure.width / 2
        column_blocks = [
            [
                block
                for block in event_blocks
                if ((block.bbox or region_map[block.region_id])[0] + (block.bbox or region_map[block.region_id])[2]) / 2 < midpoint
            ],
            [
                block
                for block in event_blocks
                if ((block.bbox or region_map[block.region_id])[0] + (block.bbox or region_map[block.region_id])[2]) / 2 >= midpoint
            ],
        ]
        for side, blocks_in_column in zip(("left", "right"), column_blocks):
            if not blocks_in_column:
                continue
            boxes = [block.bbox or region_map[block.region_id] for block in blocks_in_column]
            x0 = max(36.0, min(bbox[0] for bbox in boxes))
            y0 = min(bbox[1] for bbox in boxes)
            x1 = min(page_structure.width - 36.0, max(bbox[2] for bbox in boxes))
            y1 = min(page_structure.height - 50.0, max(bbox[3] for bbox in boxes))
            rendered_events = []
            for date, description in self._timeline_events_for_blocks(blocks_in_column, region_map):
                body = (
                    f'<div class="typeset-timeline-body">{html.escape(description)}</div>'
                    if description else ""
                )
                rendered_events.append(
                    '<div class="typeset-timeline-event">'
                    f'<div class="typeset-timeline-date">{html.escape(date)}</div>'
                    f"{body}</div>"
                )
            parts.append(
                f'<div class="typeset-timeline-flow" data-column="{side}" data-fit="reflow" '
                f'style="left:{_pt_to_px_str(x0)};top:{_pt_to_px_str(y0)};'
                f'width:{_pt_to_px_str(x1 - x0)};height:{_pt_to_px_str(y1 - y0)}">'
                f"{''.join(rendered_events)}</div>"
            )
        return "\n".join(parts)

    def _is_stacked_card_page(
        self,
        blocks: list[ContentBlock],
        region_map: dict[str, list[float]],
        page_structure: PageStructure,
    ) -> bool:
        wide_boxes = sorted(
            [
                block.bbox or region_map[block.region_id]
                for block in blocks
                if (block.bbox or region_map[block.region_id])[2]
                - (block.bbox or region_map[block.region_id])[0]
                >= page_structure.width * 0.65
            ],
            key=lambda bbox: bbox[1],
        )
        if len(wide_boxes) < 3:
            return False
        large_gaps = sum(
            1
            for previous, current in zip(wide_boxes, wide_boxes[1:])
            if current[1] - previous[3] >= 20.0
        )
        vertical_span = wide_boxes[-1][3] - wide_boxes[0][1]
        return large_gaps >= 2 and vertical_span >= page_structure.height * 0.55

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

    def _is_dense_line_grid_page(self, page_structure: PageStructure) -> bool:
        grid_lines = [
            decoration
            for decoration in page_structure.decorations
            if self._is_table_grid_line(decoration)
        ]
        return len(grid_lines) >= 80

    def _is_table_grid_line(self, decoration: DecorationElement) -> bool:
        if decoration.element_type != "line" or len(decoration.bbox) != 4:
            return False
        if not self._is_dark_or_unspecified_stroke(decoration.stroke_color):
            return False
        x0, y0, x1, y1 = decoration.bbox
        return abs(x1 - x0) >= 8.0 or abs(y1 - y0) >= 8.0

    def _is_dark_or_unspecified_stroke(self, color: str | None) -> bool:
        if color is None:
            return True
        match = re.fullmatch(r"#?([0-9a-fA-F]{6})", color.strip())
        if not match:
            return False
        value = match.group(1)
        red = int(value[0:2], 16)
        green = int(value[2:4], 16)
        blue = int(value[4:6], 16)
        return max(red, green, blue) <= 80

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
        ordered_blocks = sorted(
            blocks,
            key=lambda block: (
                (block.bbox or region_map[block.region_id])[1],
                (block.bbox or region_map[block.region_id])[0],
                block.order,
            ),
        )
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
            allowed_line_ids = set(block.line_ids)
            for line_index, line in enumerate(lines):
                line_id = f"{block.region_id}_l{line_index + 1:04d}"
                if allowed_line_ids and line_id not in allowed_line_ids:
                    continue
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

    def _render_structured_table(
        self,
        blocks: list[ContentBlock],
        page_structure: PageStructure,
        *,
        compact: bool = False,
    ) -> str:
        """Rebuild PDF-native table cells as one accessible HTML table."""
        region_map = {region.id: region.bbox for region in page_structure.text_regions}
        groups: list[list[ContentBlock]] = []
        group_by_region: dict[str, list[ContentBlock]] = {}
        for block in blocks:
            if block.region_id not in group_by_region:
                group_by_region[block.region_id] = []
                groups.append(group_by_region[block.region_id])
            group_by_region[block.region_id].append(block)
        for group in groups:
            group.sort(key=lambda item: (item.bbox or region_map[item.region_id])[0])

        raw_column_count = max((len(group) for group in groups), default=0)
        if raw_column_count < 2:
            raise ValueError("表格至少需要两个可识别的列")
        anchor_index = next(
            index for index, group in enumerate(groups) if len(group) == raw_column_count
        )
        anchor_group = groups[anchor_index]
        anchor_boxes: list[list[float]] = []
        for item in anchor_group:
            box = list(item.bbox or region_map[item.region_id])
            if anchor_boxes and box[0] < anchor_boxes[-1][2] - 1.0:
                anchor_boxes[-1] = [
                    min(anchor_boxes[-1][0], box[0]),
                    min(anchor_boxes[-1][1], box[1]),
                    max(anchor_boxes[-1][2], box[2]),
                    max(anchor_boxes[-1][3], box[3]),
                ]
            else:
                anchor_boxes.append(box)
        column_count = len(anchor_boxes)
        if column_count < 2:
            raise ValueError("表格至少需要两个可识别的列")
        centers = [(box[0] + box[2]) / 2 for box in anchor_boxes]
        table_x0 = min(box[0] for box in anchor_boxes)
        table_x1 = max(box[2] for box in anchor_boxes)
        table_blocks_bbox = _union_block_bboxes(blocks, region_map)

        if anchor_index:
            header_groups = groups[:anchor_index]
            data_groups = groups[anchor_index:]
        else:
            header_groups = [anchor_group]
            data_groups = groups[1:]

        headers = ["" for _ in range(column_count)]
        for group in header_groups:
            for block in group:
                column = self._table_column_for_block(block, centers, region_map)
                headers[column] = self._join_table_cell_text(
                    headers[column], self._display_text_for_block(block)
                )
        if any(not text for text in headers):
            raise ValueError("表格表头无法完整映射到所有列")

        rows: list[tuple[str, list[str] | str]] = []
        current: list[str] | None = None
        for group in data_groups:
            first = group[0]
            first_box = first.bbox or region_map[first.region_id]
            if (
                len(group) == 1
                and first_box[2] - first_box[0] >= (table_x1 - table_x0) * 0.5
            ):
                note = "".join(self._display_text_for_block(item) for item in group).strip()
                rows.append(("note", note))
                current = None
                continue

            assignments = [
                (self._table_column_for_block(block, centers, region_map), block)
                for block in group
            ]
            starts_row = any(column == 0 for column, _ in assignments)
            if starts_row:
                current = ["" for _ in range(column_count)]
                rows.append(("cells", current))
            if current is None:
                raise ValueError(f"表格续行缺少起始单元格：{first.region_id}")
            for column, block in assignments:
                current[column] = self._join_table_cell_text(
                    current[column], self._display_text_for_block(block)
                )

        if not any(kind == "cells" for kind, _ in rows):
            raise ValueError("表格没有可识别的数据行")

        table_left = table_blocks_bbox[0]
        table_right = table_blocks_bbox[2]
        boundaries = [table_left]
        boundaries.extend((centers[index] + centers[index + 1]) / 2 for index in range(column_count - 1))
        boundaries.append(table_right)
        column_widths = [
            max(1.0, boundaries[index + 1] - boundaries[index])
            for index in range(column_count)
        ]
        total_width = sum(column_widths)
        colgroup = "".join(
            f'<col style="width:{width / total_width * 100:.3f}%">'
            for width in column_widths
        )
        thead = "".join(f"<th>{html.escape(text)}</th>" for text in headers)
        body_rows: list[str] = []
        for kind, value in rows:
            if kind == "note":
                body_rows.append(
                    f'<tr class="typeset-table-note"><td colspan="{column_count}">'
                    f"{html.escape(str(value))}</td></tr>"
                )
            else:
                cells = value
                body_rows.append(
                    "<tr>" + "".join(f"<td>{html.escape(text)}</td>" for text in cells) + "</tr>"
                )

        angles = [
            self._region_angle(block.region_id, page_structure)
            for block in blocks
            if abs(self._region_angle(block.region_id, page_structure)) >= 1.0
        ]
        angle = sum(angles) / len(angles) if angles else 0.0
        transform = (
            f"transform-origin:0 0;transform:rotate({angle:.3f}deg);"
            if abs(angle) >= 1.0 else ""
        )
        table_class = "typeset-structured-table"
        if compact:
            table_class += " typeset-table-compact"
        return (
            f'<div class="{table_class}" data-fit="table" '
            f'style="left:{_pt_to_px_str(table_left - 2.0)};'
            f'top:{_pt_to_px_str(max(0.0, table_blocks_bbox[1] - 6.0))};'
            f'width:{_pt_to_px_str(table_right - table_left + 4.0)};{transform}">'
            f'<table><colgroup>{colgroup}</colgroup><thead><tr>{thead}</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody></table></div>'
        )

    def _table_column_for_block(
        self,
        block: ContentBlock,
        centers: list[float],
        region_map: dict[str, list[float]],
    ) -> int:
        bbox = block.bbox or region_map[block.region_id]
        center = (bbox[0] + bbox[2]) / 2
        return min(range(len(centers)), key=lambda index: abs(centers[index] - center))

    def _join_table_cell_text(self, previous: str, current: str) -> str:
        previous = previous.strip()
        current = current.strip()
        if not previous:
            return current
        if not current:
            return previous
        separator = " " if previous[-1].isascii() and current[0].isascii() else ""
        return previous + separator + current

    def _render_table_line_track_block(
        self,
        block: ContentBlock,
        page_structure: PageStructure,
    ) -> str:
        region = {item.id: item for item in page_structure.text_regions}.get(block.region_id)
        if region is None or not getattr(region, "lines", None):
            bbox = region.bbox if region is not None else [0.0, 0.0, 0.0, 0.0]
            return self._render_positioned_single_block(block, page_structure, bbox)

        slots: list[str] = []
        for index, line in enumerate(region.lines):
            bbox = list(getattr(line, "bbox", []))
            if len(bbox) != 4:
                continue
            x0, y0, x1, y1 = bbox
            font_size_pt = float(getattr(line, "font_size", 9.0) or 9.0)
            font_size = _pt_to_px(max(7.0, min(font_size_pt, self.config.body_font_size_pt)))
            source_color = str(getattr(line, "color", "#000000") or "#000000")
            text_color = "#ffffff" if source_color.lower() == "#ffffff" else self.config.body_color
            slots.append(
                f'<span class="typeset-line-slot" '
                f'data-line-index="{index}" '
                f'data-bold="{str(bool(getattr(line, "bold", False))).lower()}" '
                f'data-italic="{str(bool(getattr(line, "italic", False))).lower()}" '
                f'style="left:{_pt_to_px_str(x0)};top:{_pt_to_px_str(y0)};'
                f'width:{_pt_to_px_str(max(0.0, x1 - x0))};'
                f'height:{_pt_to_px_str(max(8.0, y1 - y0))};'
                f'font-size:{_px(font_size)};color:{html.escape(text_color)}"></span>'
            )
        text = self._display_text_for_block(block)
        if not slots or not text:
            return ""
        return (
            f'<div class="typeset-line-track-flow typeset-table-line-flow" '
            f'data-table-block="{html.escape(block.id)}" '
            f'data-flow-text="{html.escape(text)}">{"".join(slots)}</div>'
        )

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
        span_html = self._render_source_span_block(block, page_structure, bbox)
        if span_html:
            return span_html
        x0, y0, x1, y1 = bbox
        if self._block_renders_as_heading(block):
            center_x = (x0 + x1) / 2
            half_width = min(center_x, page_structure.width - center_x)
            x0 = center_x - half_width
            x1 = center_x + half_width
        left = _pt_to_px(x0)
        top = _pt_to_px(y0)
        width = _pt_to_px(max(0.0, x1 - x0))
        height = _pt_to_px(max(0.0, y1 - y0))
        inner = self._render_block(block, preserve_source_size=True)
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
            self._render_angle_for_block(block, page_structure),
            self._positioned_mask_style(page_structure, bbox, block),
        )

    def _render_source_span_block(
        self,
        block: ContentBlock,
        page_structure: PageStructure,
        bbox: list[float],
    ) -> str:
        if block.translatable:
            return ""
        region = {item.id: item for item in page_structure.text_regions}.get(block.region_id)
        if region is None or not getattr(region, "lines", None):
            return ""
        target_bbox = block.bbox or bbox
        spans_html: list[str] = []
        for line in region.lines:
            for span in getattr(line, "spans", []):
                text = getattr(span, "text", "")
                if not text or not self._boxes_overlap(target_bbox, span.bbox):
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
        # Semantic analysis owns duplicate classification.  The renderer must
        # never infer that one translated block is disposable from text overlap.
        return list(blocks)

    def _build_reflow_items(self, blocks: list[ContentBlock]) -> list[tuple[ContentBlock, str]]:
        return [
            (block, text)
            for block in blocks
            if (text := self._display_text_for_block(block))
        ]

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
        color = self._block_text_color(block)
        block_attrs = (
            f' data-block-id="{html.escape(block.id)}"'
            f' data-region-id="{html.escape(block.region_id)}"'
        )
        if self._renders_as_accent_heading(block):
            escaped = self._format_text(text)
            size_px = _pt_to_px(self.config.accent_font_size_pt)
            return (
                f'<h2 class="typeset-reflow-subtitle {self._heading_role_class(block)}"{block_attrs} '
                f'style="font-size:{_px(size_px)};color:{html.escape(color)}">{escaped}</h2>'
            )
        role_class = f"{self._font_role_class(block)} {self._source_font_class(block)}"
        if block.font_role == FontRole.DISPLAY or block.role == SemanticRole.TITLE:
            escaped = self._format_text(text)
            return (
                f'<h1 class="typeset-reflow-title {role_class}"{block_attrs} '
                f'style="color:{html.escape(color)}">{escaped}</h1>'
            )
        if block.font_role == FontRole.SECTION:
            escaped = self._format_text(text)
            return (
                f'<h2 class="typeset-reflow-section {role_class}"{block_attrs} '
                f'style="color:{html.escape(color)}">{escaped}</h2>'
            )
        if block.font_role == FontRole.CALLOUT:
            escaped = self._format_text(text)
            return (
                f'<h3 class="typeset-reflow-callout {role_class}"{block_attrs} '
                f'style="color:{html.escape(color)}">{escaped}</h3>'
            )
        if block.font_role == FontRole.SUBSECTION or block.role == SemanticRole.SUBTITLE:
            escaped = self._format_text(text)
            return (
                f'<h3 class="typeset-reflow-subtitle {role_class}"{block_attrs} '
                f'style="color:{html.escape(color)}">{escaped}</h3>'
            )
        escaped = self._format_body_text(block, text)
        class_name = f"typeset-reflow-body {role_class}{self._source_style_classes(block)}"
        if block.layout_mode == "drop_cap":
            class_name += " typeset-drop-cap"
        if self._looks_like_timeline_text(block, text):
            class_name += " typeset-timeline-text"
        paragraph_attr = (
            f' data-paragraph-id="{html.escape(block.paragraph_id)}"'
            if block.paragraph_id else ""
        )
        indent = self.config.text_indent if self._source_paragraph_is_indented(block) else "0"
        return (
            f'<p class="{class_name}"{block_attrs}{paragraph_attr} '
            f'style="text-indent:{html.escape(indent)}">{escaped}</p>'
        )

    def _font_role_class(self, block: ContentBlock) -> str:
        return f"font-role-{block.font_role.value.replace('_', '-')}"

    def _heading_role_class(self, block: ContentBlock) -> str:
        """Force a heading font class so accent labels keep the heading font
        stack instead of inheriting the body font class of BODY-role blocks."""
        if block.font_role in {FontRole.DISPLAY, FontRole.SECTION, FontRole.SUBSECTION}:
            return f"{self._font_role_class(block)} {self._source_font_class(block)}"
        return f"font-role-section {self._source_font_class(block)}"

    def _block_is_short_heading(self, block: ContentBlock) -> bool:
        """True for a block that should render as its own heading instead of
        being merged into the surrounding same-region body flow."""
        if block.role in (SemanticRole.TITLE, SemanticRole.SUBTITLE):
            return True
        if block.font_role in (
            FontRole.DISPLAY,
            FontRole.SECTION,
            FontRole.SUBSECTION,
            FontRole.CALLOUT,
        ):
            return True
        source = _normalized_text(block.source_text or block.translated_text or "")
        return bool(source) and len(source) <= 48 and self._block_is_accent_heading(block)

    def _source_font_class(self, block: ContentBlock) -> str:
        if self._block_renders_as_heading(block):
            return "source-font-default"
        source_font = (block.source_font or "").lower()
        if "industria" in source_font:
            return (
                "source-font-geometric"
                if self._block_is_accent_heading(block)
                else "source-font-display-condensed"
            )
        if "vt323" in source_font or "mono" in source_font or "courier" in source_font:
            return "source-font-typewriter"
        if "futura" in source_font:
            return "source-font-geometric"
        if "sabon" in source_font or "serif" in source_font:
            return "source-font-literary"
        return "source-font-default"

    def _source_paragraph_is_indented(self, block: ContentBlock) -> bool:
        return block.first_line_indent_pt >= max(6.0, self.config.body_font_size_pt * 0.7)

    def _source_style_classes(self, block: ContentBlock) -> str:
        visible = [run for run in block.runs if run.text.strip()]
        if not visible:
            return ""
        total_chars = sum(len(run.text.strip()) for run in visible)
        classes = []
        italic_chars = sum(len(run.text.strip()) for run in visible if run.italic)
        bold_chars = sum(len(run.text.strip()) for run in visible if run.bold)
        if italic_chars / max(1, total_chars) >= 0.8:
            classes.append("source-style-italic")
        if bold_chars / max(1, total_chars) >= 0.8:
            classes.append("source-style-bold")
        return "" if not classes else " " + " ".join(classes)

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
            f'<h2 class="typeset-reflow-title" data-block-id="{html.escape(block.id)}" '
            f'data-region-id="{html.escape(block.region_id)}">{self._format_text(title)}</h2>'
        ]
        if body:
            parts.append(
                f'<p class="typeset-reflow-body" data-block-id="{html.escape(block.id)}" '
                f'data-region-id="{html.escape(block.region_id)}">'
                f'{self._format_body_text(block, body)}</p>'
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
        if len(text) <= 32 and font_size >= self.config.body_font_size_pt * 1.15:
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
            inner = self._render_block(block, preserve_source_size=True)
            if not inner:
                continue

            parts.append(self._positioned_block_html(
                block.region_id, left, top, width, height, color, inner,
                self._render_angle_for_block(block, page_structure),
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
        inner = self._render_block(block, preserve_source_size=True)
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
            self._render_angle_for_block(block, page_structure),
            self._positioned_mask_style(page_structure, bbox, block),
        )

    def _source_text_block(self, block: ContentBlock) -> ContentBlock:
        return replace(block, translated_text=block.source_text, translatable=False)

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
            transform = (
                f"transform-origin:center center;transform:rotate({angle:.3f}deg);"
            )
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
        if self._box_area_ratio(bbox, page_structure) > 0.12:
            return ""
        if block is not None and self._block_renders_as_heading(block):
            return ""
        if block is not None and self._is_light_color(self._block_text_color(block)):
            return ""
        if block is not None and self._is_long_translated_body(block):
            return ""
        for image in page_structure.images:
            if self._is_full_page_image(image.bbox, page_structure):
                continue
            if self._boxes_overlap(bbox, image.bbox):
                return "background:#f4eedc;"
        return ""

    def _box_area_ratio(
        self,
        bbox: list[float],
        page_structure: PageStructure,
    ) -> float:
        if len(bbox) != 4:
            return 0.0
        x0, y0, x1, y1 = bbox
        box_area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        page_area = max(1.0, page_structure.width * page_structure.height)
        return box_area / page_area

    def _render_angle_for_block(
        self,
        block: ContentBlock,
        page_structure: PageStructure,
    ) -> float:
        return self._region_angle(block.region_id, page_structure)

    def _reflow_group_angle(
        self,
        blocks: list[ContentBlock],
        angle: float,
    ) -> float:
        return angle

    def _is_long_translated_body(self, block: ContentBlock) -> bool:
        text = block.translated_text or ""
        return (
            block.role == SemanticRole.BODY_COLUMN
            and _contains_cjk(text)
            and len(_normalized_text(text)) >= 80
        )

    def _block_renders_as_heading(self, block: ContentBlock) -> bool:
        return (
            block.role in (SemanticRole.TITLE, SemanticRole.SUBTITLE)
            or self._is_heading(self._get_block_font_size(block))
            or self._looks_like_subtitle(block)
        )

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

    def _is_tilted_card_block(
        self,
        block: ContentBlock,
        page_structure: PageStructure,
    ) -> bool:
        text = self._display_text_for_block(block)
        return (
            block.role in (SemanticRole.BODY_COLUMN, SemanticRole.TITLE, SemanticRole.SUBTITLE)
            and _contains_cjk(text)
            and abs(self._region_angle(block.region_id, page_structure)) >= 1.0
        )

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
            self._render_body_block(
                block,
                text,
                self._get_block_font_size(block),
                enforce_minimum=False,
            )
            for block, text in flow_items
        )
        ids = ",".join(block.id for block in blocks)
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
        return (
            block.role == SemanticRole.HEADER
            or block.font_role == FontRole.RUNNING_HEADER
        )

    def _render_running_header(
        self,
        block: ContentBlock,
        page_structure: PageStructure,
        bbox: list[float],
    ) -> str:
        """Render fixed left/right running headers in their original slots."""
        x0, y0, x1, y1 = bbox
        left_side = (x0 + x1) / 2 < page_structure.width / 2
        slot_x0 = x0 if left_side else max(page_structure.width / 2, x0 - 80.0)
        slot_x1 = min(page_structure.width / 2, x1 + 80.0) if left_side else x1
        label = self._display_text_for_block(block)
        label = re.sub(r"^(?:\s*/+\s*)+", "", label)
        label = re.sub(r"(?:\s*/+\s*)+$", "", label).strip()
        text = html.escape(f"// {label} //")
        return (
            f'<div class="typeset-positioned-block source-font-display-condensed '
            f'{self._font_role_class(block)}" '
            f'data-block-id="{html.escape(block.id)}" '
            f'data-region-id="{html.escape(block.region_id)}" '
            f'style="left:{_pt_to_px_str(slot_x0)};top:{_pt_to_px_str(y0)};'
            f'width:{_pt_to_px_str(max(1.0, slot_x1 - slot_x0))};'
            f'height:{_pt_to_px_str(max(14.0, y1 - y0))};'
            f'font-size:{_pt_to_px_str(self.config.running_header_font_size_pt)};'
            f'font-weight:400;line-height:1;display:flex;align-items:flex-end;'
            f'justify-content:{"flex-start" if left_side else "flex-end"};'
            f'text-align:{"left" if left_side else "right"};padding-bottom:2px;'
            f'white-space:nowrap;color:{html.escape(self.config.title_color)}">'
            f"{text}</div>"
        )

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
        if source_color:
            return source_color
        if block.role == SemanticRole.TITLE and (block.source_text or "").lstrip().startswith(">>"):
            return self.config.subtitle_color
        if block.role == SemanticRole.TITLE:
            return self.config.title_color
        if block.role == SemanticRole.SUBTITLE or self._looks_like_subtitle(block):
            return self.config.subtitle_color
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

    def _block_is_accent_heading(self, block: ContentBlock) -> bool:
        accent_colors = {
            self.config.subtitle_color.lower(),
            "#eb4f24",
            "#ed1c24",
            "#ed1d24",
            "#dc2527",
        }
        return any(
            run.text.strip() and run.color.lower() in accent_colors
            for run in block.runs
        )

    def _renders_as_accent_heading(self, block: ContentBlock) -> bool:
        """Recognize short red DG section labels even when extraction marks them BODY."""
        if block.font_role in {FontRole.DISPLAY, FontRole.SECTION}:
            return self._block_is_accent_heading(block)
        if block.font_role not in {FontRole.BODY, FontRole.META}:
            return False
        source = _normalized_text(block.source_text or block.translated_text or "")
        return bool(source) and len(source) <= 48 and self._block_is_accent_heading(block)

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

    def _render_block(
        self,
        block: ContentBlock,
        is_cover: bool = False,
        preserve_source_size: bool = False,
    ) -> str:
        """Render a single content block as HTML."""
        # Determine the text to display
        text = self._display_text_for_block(block)
        if not text:
            return ""

        block_font_size_pt = self._target_font_size_pt(block)
        if preserve_source_size and block.font_role in {FontRole.BODY, FontRole.META}:
            block_font_size_pt = self._get_block_font_size(block)

        if self._renders_as_accent_heading(block):
            return self._render_subtitle_block(block, text, block_font_size_pt)
        if block.font_role == FontRole.DISPLAY or block.role == SemanticRole.TITLE:
            return self._render_heading_block(block, text, block_font_size_pt)
        if block.font_role in {FontRole.SECTION, FontRole.SUBSECTION, FontRole.CALLOUT}:
            return self._render_subtitle_block(block, text, block_font_size_pt)
        if block.role == SemanticRole.SUBTITLE:
            return self._render_subtitle_block(block, text, block_font_size_pt)
        return self._render_body_block(
            block,
            text,
            block_font_size_pt,
            enforce_minimum=not preserve_source_size,
        )

    def _target_font_size_pt(self, block: ContentBlock) -> float:
        if self._renders_as_accent_heading(block):
            return self.config.accent_font_size_pt
        if block.font_role == FontRole.DISPLAY or block.role == SemanticRole.TITLE:
            return min(self.config.display_font_size_pt, self._get_block_font_size(block))
        if block.font_role == FontRole.SECTION:
            return self.config.section_font_size_pt
        if block.font_role == FontRole.SUBSECTION:
            return self.config.subsection_font_size_pt
        if block.font_role == FontRole.RUNNING_HEADER:
            return self.config.running_header_font_size_pt
        if block.font_role == FontRole.TABLE:
            return self.config.table_font_size_pt
        if block.font_role == FontRole.CALLOUT:
            return 16.0
        if block.role == SemanticRole.SUBTITLE:
            return self.config.section_font_size_pt
        return self.config.body_font_size_pt

    def _get_block_font_size(self, block: ContentBlock) -> float:
        """Get the representative font size for a block (median of runs)."""
        if not block.runs:
            return self.config.body_font_size_pt
        sizes = sorted(run.font_size for run in block.runs if run.font_size > 0)
        if not sizes:
            return self.config.body_font_size_pt
        return sizes[len(sizes) // 2]

    def _display_text_for_block(self, block: ContentBlock) -> str:
        if block.layout_mode in {"image_overlay_text", "hidden_source_text"}:
            return ""
        if block.translatable:
            text = (block.translated_text or "").strip()
        else:
            text = (block.translated_text or block.source_text or "").strip()
        return self._normalize_symbol_font_text(block, text)

    def _normalize_symbol_font_text(self, block: ContentBlock, text: str) -> str:
        """Convert the Wingdings codepoints emitted by PDF text extraction to Unicode."""
        if not text or not any("wingdings" in (run.font or "").lower() for run in block.runs):
            return text
        return text.replace("\uf0a1", "○").replace("\uf04e", "☠")

    def _render_heading_block(
        self, block: ContentBlock, text: str, font_size_pt: float
    ) -> str:
        """Render a block as a heading element."""
        tag = "h1" if block.font_role == FontRole.DISPLAY else self._heading_level(font_size_pt)
        font_size_px = _pt_to_px(font_size_pt)
        font_size_px = max(font_size_px, self._min_font_size_px())
        escaped_text = self._format_text(text)
        style_parts = [
            f"font-size:{_px(font_size_px)}",
            f"font-weight:{self._source_font_weight(block)}",
        ]

        return (
            f'<{tag} class="typeset-heading {self._font_role_class(block)} '
            f'{self._source_font_class(block)}" '
            f'data-block-id="{html.escape(block.id)}" '
            f'style="{";".join(style_parts)};color:{html.escape(self._block_text_color(block))}">'
            f"{escaped_text}"
            f"</{tag}>"
        )

    def _render_subtitle_block(
        self, block: ContentBlock, text: str, font_size_pt: float
    ) -> str:
        font_size_px = _pt_to_px(font_size_pt)
        escaped_text = self._format_text(text)
        is_accent_heading = self._block_is_accent_heading(block)
        extra_class = (
            "typeset-source-subtitle" if is_accent_heading
            else "typeset-reflow-section" if block.font_role == FontRole.SECTION
            else "typeset-reflow-callout" if block.font_role == FontRole.CALLOUT
            else "typeset-reflow-subsection"
        )
        role_class = self._heading_role_class(block) if is_accent_heading else self._font_role_class(block)
        tag = "h2" if is_accent_heading else "h3"
        return (
            f'<{tag} class="typeset-heading {extra_class} {role_class} '
            f'{self._source_font_class(block)}" '
            f'data-block-id="{html.escape(block.id)}" '
            f'style="font-size:{_px(font_size_px)};'
            f'font-weight:{self._source_font_weight(block)};'
            f'color:{html.escape(self._block_text_color(block))}">'
            f"{escaped_text}</{tag}>"
        )

    def _source_font_weight(self, block: ContentBlock) -> str:
        source_font = (block.source_font or "").lower()
        is_heavy_family = "bold" in source_font or "solid" in source_font
        return "700" if is_heavy_family or any(run.bold for run in block.runs if run.text.strip()) else "400"

    def _render_body_block(
        self,
        block: ContentBlock,
        text: str,
        font_size_pt: float,
        enforce_minimum: bool = True,
    ) -> str:
        """Render a block as a body paragraph."""
        font_size_px = _pt_to_px(font_size_pt)
        if enforce_minimum:
            font_size_px = max(font_size_px, self._min_font_size_px())
        escaped_text = self._format_body_text(block, text)

        style_parts: list[str] = []
        # Only add font-size if different from body default
        body_px = self._body_font_size_px()
        if abs(font_size_px - body_px) > 0.1:
            style_parts.append(f"font-size:{_px(font_size_px)}")
        style_parts.append(
            f"text-indent:{self.config.text_indent if self._source_paragraph_is_indented(block) else '0'}"
        )
        if self._looks_like_timeline_text(block, text):
            style_parts.append("text-indent:0")
            style_parts.append("line-height:1.25")

        style_attr = f' style="{";".join(style_parts)}"' if style_parts else ""
        class_name = (
            f"typeset-body-text {self._font_role_class(block)} {self._source_font_class(block)}"
            f"{self._source_style_classes(block)}"
        )
        if self._looks_like_timeline_text(block, text):
            class_name += " typeset-timeline-text"
        if block.layout_mode == "drop_cap":
            class_name += " typeset-drop-cap"

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
                self._escape_emphasis_markup(part.strip())
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
        return "<br><br>".join(
            self._escape_emphasis_markup(paragraph)
            for paragraph in paragraphs
        )

    @staticmethod
    def _escape_emphasis_markup(text: str) -> str:
        escaped = html.escape(text)
        return (
            escaped.replace("&lt;strong&gt;", "<strong>")
            .replace("&lt;/strong&gt;", "</strong>")
            .replace("&lt;em&gt;", "<em>")
            .replace("&lt;/em&gt;", "</em>")
        )
