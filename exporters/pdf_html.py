"""
Original-page HTML renderer for coordinate-level PDF layouts.

The output is an inspection target for the replica pipeline. It keeps each PDF
page at its original point size and places text spans by their source bbox.
"""

import html
from pathlib import Path

from core.layout_model import LayoutDocument, LayoutPage, LayoutTextBlock, layout_document_from_json
from core.utils import ensure_output_parent


CSS_PX_PER_PDF_POINT = 96.0 / 72.0


def _css_px_from_pt(value: float) -> str:
    return f"{float(value) * CSS_PX_PER_PDF_POINT:.3f}px"


def _css_in_from_pt(value: float) -> str:
    return f"{float(value) / 72.0:.6f}in"


def _font_family(font_name: str) -> str:
    safe_name = font_name.replace('"', "").strip()
    if not safe_name:
        return '"Noto Serif SC", "SimSun", serif'
    return f'"{safe_name}", "Noto Serif SC", "SimSun", serif'


def _block_font_size(block: LayoutTextBlock) -> float:
    sizes = sorted(span.size for span in block.spans if span.size > 0)
    return sizes[len(sizes) // 2] if sizes else 10.0


def _block_font(block: LayoutTextBlock) -> str:
    return block.spans[0].font if block.spans else ""


def _translated_html(text: str) -> str:
    lines = text.splitlines() or [text]
    return "<br>".join(html.escape(line) for line in lines)


def _render_page(page: LayoutPage, show_boxes: bool) -> str:
    parts = [
        (
            f'<section class="replica-page" '
            f'style="width:{_css_px_from_pt(page.width)};height:{_css_px_from_pt(page.height)}">'
        )
    ]
    for image in page.image_blocks:
        x0, y0, x1, y1 = image.bbox
        parts.append(
            '<div class="replica-image" '
            f'data-block-id="{html.escape(image.id)}" '
            f'style="left:{_css_px_from_pt(x0)};top:{_css_px_from_pt(y0)};'
            f'width:{_css_px_from_pt(x1 - x0)};height:{_css_px_from_pt(y1 - y0)}"></div>'
        )
    for block in page.text_blocks:
        if block.translated_text:
            x0, y0, x1, y1 = block.bbox
            box_class = " replica-translation-box" if show_boxes else ""
            parts.append(
                f'<div class="replica-translation{box_class}" '
                f'data-block-id="{html.escape(block.id)}" '
                f'style="left:{_css_px_from_pt(x0)};top:{_css_px_from_pt(y0)};'
                f'width:{_css_px_from_pt(x1 - x0)};height:{_css_px_from_pt(y1 - y0)};'
                f'font-family:{_font_family(_block_font(block))};'
                f'font-size:{_css_px_from_pt(_block_font_size(block))}">'
                f'{_translated_html(block.translated_text)}'
                '</div>'
            )
            continue
        for span in block.spans:
            x0, y0, x1, y1 = span.bbox
            box_class = " replica-span-box" if show_boxes else ""
            parts.append(
                f'<span class="replica-span{box_class}" '
                f'data-block-id="{html.escape(block.id)}" '
                f'data-span-id="{html.escape(span.id)}" '
                f'style="left:{_css_px_from_pt(x0)};top:{_css_px_from_pt(y0)};'
                f'width:{_css_px_from_pt(x1 - x0)};height:{_css_px_from_pt(y1 - y0)};'
                f'font-family:{_font_family(span.font)};'
                f'font-size:{_css_px_from_pt(span.size)};'
                f'color:{html.escape(span.color)}">'
                f'{html.escape(span.text)}'
                '</span>'
            )
    parts.append("</section>")
    return "\n".join(parts)


def render_layout_html(layout: LayoutDocument, output_path: str, show_boxes: bool = False):
    ensure_output_parent(output_path)
    if not layout.pages:
        raise ValueError("layout 没有页面")
    first_page = layout.pages[0]
    css = f"""
    * {{
        box-sizing: border-box;
    }}
    body {{
        margin: 0;
        padding: 24px;
        background: #444;
    }}
    .replica-page {{
        position: relative;
        overflow: hidden;
        margin: 0 auto 24px;
        background: #fff;
        box-shadow: 0 3px 18px rgba(0, 0, 0, 0.35);
        page-break-after: always;
    }}
    .replica-span {{
        position: absolute;
        display: block;
        white-space: pre;
        line-height: 1;
        overflow: visible;
        transform-origin: left top;
    }}
    .replica-span-box {{
        outline: 0.5px solid rgba(216, 0, 0, 0.45);
    }}
    .replica-translation {{
        position: absolute;
        display: block;
        white-space: normal;
        overflow: hidden;
        line-height: 1.12;
        transform-origin: left top;
    }}
    .replica-translation-box {{
        outline: 0.75px solid rgba(216, 0, 0, 0.75);
        background: rgba(216, 0, 0, 0.045);
    }}
    .replica-image {{
        position: absolute;
        border: {("0.75px dashed rgba(0, 92, 255, 0.65)" if show_boxes else "0")};
        background: {("rgba(0, 92, 255, 0.08)" if show_boxes else "transparent")};
    }}
    @page {{
        size: {_css_in_from_pt(first_page.width)} {_css_in_from_pt(first_page.height)};
        margin: 0;
    }}
    @media print {{
        body {{
            padding: 0;
            background: #fff;
        }}
        .replica-page {{
            margin: 0;
            box-shadow: none;
        }}
    }}
    """
    chunks = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(layout.source_pdf)} replica layout</title>",
        f"<style>{css}</style>",
        "</head>",
        "<body>",
    ]
    for page in layout.pages:
        chunks.append(_render_page(page, show_boxes=show_boxes))
    chunks.extend(["</body>", "</html>"])
    Path(output_path).write_text("\n".join(chunks), encoding="utf-8")


def render_layout_json_html(layout_json_path: str, output_path: str, show_boxes: bool = False):
    layout = layout_document_from_json(Path(layout_json_path).read_text(encoding="utf-8"))
    render_layout_html(layout, output_path, show_boxes=show_boxes)
