"""
Original-page HTML renderer for coordinate-level PDF layouts.

The output is an inspection target for the replica pipeline. It keeps each PDF
page at its original point size and places text spans by their source bbox.
"""

import html
import os
from pathlib import Path
from urllib.parse import quote

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

from core.layout_model import LayoutDocument, LayoutPage, LayoutTextBlock, layout_document_from_json
from core.utils import ensure_output_parent


CSS_PX_PER_PDF_POINT = 96.0 / 72.0


def _css_px_from_pt(value: float) -> str:
    return f"{float(value) * CSS_PX_PER_PDF_POINT:.3f}px"


def _raw_css_px_from_pt(value: float) -> float:
    return float(value) * CSS_PX_PER_PDF_POINT


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


def _mask_padding_px(block: LayoutTextBlock) -> float:
    return max(1.5, _raw_css_px_from_pt(_block_font_size(block)) * 0.16)


def _sample_block_bg_color(page_image_path: Path, block: LayoutTextBlock,
                           page_width: float, page_height: float) -> str | None:
    """Sample the dominant background color behind a text block from the page image.

    Returns an rgba() CSS color string, or None if sampling is not possible.
    """
    if not _HAS_PIL or not page_image_path.exists():
        return None
    try:
        img = Image.open(page_image_path)
    except Exception:
        return None
    img_w, img_h = img.size
    if img_w == 0 or img_h == 0 or page_width <= 0 or page_height <= 0:
        return None

    # Convert PDF points to image pixels
    scale_x = img_w / page_width
    scale_y = img_h / page_height
    x0, y0, x1, y1 = block.bbox
    # Sample a slightly inset region to avoid edge artifacts
    inset = 2.0  # PDF points
    px_x0 = max(0, int((x0 + inset) * scale_x))
    px_y0 = max(0, int((y0 + inset) * scale_y))
    px_x1 = min(img_w, int((x1 - inset) * scale_x))
    px_y1 = min(img_h, int((y1 - inset) * scale_y))
    if px_x1 <= px_x0 or px_y1 <= px_y0:
        return None

    # Sample edges of the block region (top/bottom strips) for background color
    # This avoids sampling the text itself
    strip_h = max(2, (px_y1 - px_y0) // 8)
    regions = []
    # Top strip
    regions.append((px_x0, px_y0, px_x1, min(px_y1, px_y0 + strip_h)))
    # Bottom strip
    regions.append((px_x0, max(px_y0, px_y1 - strip_h), px_x1, px_y1))
    # Left strip
    strip_w = max(2, (px_x1 - px_x0) // 8)
    regions.append((px_x0, px_y0, min(px_x1, px_x0 + strip_w), px_y1))
    # Right strip
    regions.append((max(px_x0, px_x1 - strip_w), px_y0, px_x1, px_y1))

    r_total, g_total, b_total, count = 0, 0, 0, 0
    img_rgb = img.convert("RGB")
    for rx0, ry0, rx1, ry1 in regions:
        crop = img_rgb.crop((rx0, ry0, rx1, ry1))
        pixels = list(crop.getdata())
        for r, g, b in pixels:
            r_total += r
            g_total += g
            b_total += b
            count += 1

    if count == 0:
        return None
    avg_r = r_total // count
    avg_g = g_total // count
    avg_b = b_total // count
    return f"rgba({avg_r}, {avg_g}, {avg_b}, 0.92)"


def _sample_region_bg(page_image_path: Path, x0: float, y0: float, x1: float, y1: float,
                      page_width: float, page_height: float) -> tuple[str, bool]:
    """Sample background color for an arbitrary region.

    Returns (css_color, is_dark) where is_dark indicates if text should be light.
    """
    default = ("rgba(255, 255, 255, 0.92)", False)
    if not _HAS_PIL or not page_image_path.exists():
        return default
    try:
        img = Image.open(page_image_path).convert("RGB")
    except Exception:
        return default
    img_w, img_h = img.size
    if img_w == 0 or img_h == 0 or page_width <= 0 or page_height <= 0:
        return default

    scale_x = img_w / page_width
    scale_y = img_h / page_height
    px_x0 = max(0, int(x0 * scale_x))
    px_y0 = max(0, int(y0 * scale_y))
    px_x1 = min(img_w, int(x1 * scale_x))
    px_y1 = min(img_h, int(y1 * scale_y))
    if px_x1 <= px_x0 or px_y1 <= px_y0:
        return default

    # Sample a grid of points across the region
    step_x = max(1, (px_x1 - px_x0) // 10)
    step_y = max(1, (px_y1 - px_y0) // 10)
    r_total, g_total, b_total, count = 0, 0, 0, 0
    for sy in range(px_y0, px_y1, step_y):
        for sx in range(px_x0, px_x1, step_x):
            r, g, b = img.getpixel((sx, sy))
            r_total += r
            g_total += g
            b_total += b
            count += 1
    if count == 0:
        return default
    avg_r = r_total // count
    avg_g = g_total // count
    avg_b = b_total // count
    brightness = (avg_r * 299 + avg_g * 587 + avg_b * 114) / 1000
    is_dark = brightness < 128
    return f"rgba({avg_r}, {avg_g}, {avg_b}, 0.92)", is_dark


def _load_page_bg_colors(page: LayoutPage, asset_base_dir: Path) -> dict[str, str]:
    """Pre-compute background colors for all translated blocks on a page."""
    image_path = Path(page.page_image_path)
    if not image_path.is_absolute():
        image_path = asset_base_dir / image_path
    colors = {}
    for block in page.text_blocks:
        if not block.translated_text:
            continue
        color = _sample_block_bg_color(image_path, block, page.width, page.height)
        if color:
            colors[block.id] = color
    return colors


def _page_image_path(page: LayoutPage, asset_base_dir: Path) -> Path:
    """Resolve the page image path."""
    image_path = Path(page.page_image_path)
    if not image_path.is_absolute():
        image_path = asset_base_dir / image_path
    return image_path


def _asset_url(page_image_path: str, output_dir: Path, asset_base_dir: Path) -> str:
    image_path = Path(page_image_path)
    if not image_path.is_absolute():
        image_path = asset_base_dir / image_path
    relative_path = Path(os.path.relpath(image_path.resolve(), output_dir.resolve())).as_posix()
    return quote(relative_path, safe="/._-")


def _render_page(page: LayoutPage, show_boxes: bool, output_dir: Path, asset_base_dir: Path,
                 bg_colors: dict[str, str] | None = None,
                 classification: "PageClassification | None" = None) -> str:
    from core.page_classifier import PageType
    page_image_src = _asset_url(page.page_image_path, output_dir, asset_base_dir)
    parts = [
        (
            f'<section class="replica-page" '
            f'data-page="{page.index + 1}" '
            f'style="width:{_css_px_from_pt(page.width)};height:{_css_px_from_pt(page.height)}">'
        ),
        (
            '<img class="replica-page-image" '
            f'src="{html.escape(page_image_src)}" '
            f'alt="page {page.index + 1}">'
        ),
    ]
    for image in page.image_blocks:
        x0, y0, x1, y1 = image.bbox
        parts.append(
            '<div class="replica-image" '
            f'data-block-id="{html.escape(image.id)}" '
            f'style="left:{_css_px_from_pt(x0)};top:{_css_px_from_pt(y0)};'
            f'width:{_css_px_from_pt(x1 - x0)};height:{_css_px_from_pt(y1 - y0)}"></div>'
        )

    # Determine which blocks belong to columns (for flow rendering)
    column_block_ids: set[str] = set()
    if classification and classification.columns:
        for col in classification.columns:
            column_block_ids.update(col.block_ids)

    # Render column flow regions for pages with detected columns
    if classification and classification.columns and column_block_ids:
        block_map = {b.id: b for b in page.text_blocks}
        for col_idx, col in enumerate(classification.columns):
            col_blocks = [block_map[bid] for bid in col.block_ids if bid in block_map]
            # Only render flow if there are translated blocks in this column
            translated_col_blocks = [b for b in col_blocks if b.translated_text]
            if not translated_col_blocks:
                # Fall through to per-block rendering for untranslated column blocks
                continue

            # Compute column mask region (union of blocks in this column only)
            col_pad = 4.0  # PDF points padding around column
            col_x0 = min(b.bbox[0] for b in col_blocks) - col_pad
            col_y0 = min(b.bbox[1] for b in col_blocks) - col_pad
            col_x1 = max(b.bbox[2] for b in col_blocks) + col_pad
            col_y1 = max(b.bbox[3] for b in col_blocks) + col_pad

            # Sample background color for the column region
            img_path = _page_image_path(page, asset_base_dir)
            mask_bg, is_dark = _sample_region_bg(
                img_path, col_x0, col_y0, col_x1, col_y1, page.width, page.height
            )
            text_color = "#f0f0f0" if is_dark else "#1a1a1a"

            mask_class = " replica-mask-box" if show_boxes else ""
            parts.append(
                f'<div class="replica-mask replica-column-mask{mask_class}" '
                f'data-column="{col_idx}" '
                f'style="left:{_raw_css_px_from_pt(col_x0):.3f}px;'
                f'top:{_raw_css_px_from_pt(col_y0):.3f}px;'
                f'width:{_raw_css_px_from_pt(col_x1 - col_x0):.3f}px;'
                f'height:{_raw_css_px_from_pt(col_y1 - col_y0):.3f}px;'
                f'background:{mask_bg}"></div>'
            )

            # Determine font sizes for this column:
            # - Find the dominant body font size in the original PDF
            # - Map it to a readable Chinese font size
            body_sizes = [_block_font_size(b) for b in col_blocks]
            original_body_pt = sorted(body_sizes)[len(body_sizes) // 2]
            # Chinese text at the same pt as English is harder to read,
            # so we use a slightly larger base. Target: 11pt CSS for body.
            cn_body_pt = max(11.0, original_body_pt * 1.05)
            cn_body_px = _raw_css_px_from_pt(cn_body_pt)
            font_scale = cn_body_pt / max(original_body_pt, 1)

            box_class = " replica-column-flow-box" if show_boxes else ""
            parts.append(
                f'<div class="replica-column-flow{box_class}" '
                f'data-column="{col_idx}" '
                f'data-base-font-px="{cn_body_px:.3f}" '
                f'style="left:{_raw_css_px_from_pt(col_x0):.3f}px;'
                f'top:{_raw_css_px_from_pt(col_y0):.3f}px;'
                f'width:{_raw_css_px_from_pt(col_x1 - col_x0):.3f}px;'
                f'height:{_raw_css_px_from_pt(col_y1 - col_y0):.3f}px;'
                f'font-size:{cn_body_px:.3f}px;'
                f'color:{text_color}">'
            )

            # Sort blocks by vertical position and render as flow content
            sorted_blocks = sorted(col_blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
            for block in sorted_blocks:
                if block.translated_text:
                    block_font_pt = _block_font_size(block)
                    # Classify block role by comparing to body font
                    ratio = block_font_pt / max(original_body_pt, 1)
                    if ratio >= 1.5:
                        # Large heading
                        tag = "h2"
                        block_px = _raw_css_px_from_pt(block_font_pt * font_scale)
                        style_attr = f' style="font-size:{block_px:.3f}px"'
                    elif ratio >= 1.2:
                        # Sub-heading
                        tag = "h3"
                        block_px = _raw_css_px_from_pt(block_font_pt * font_scale)
                        style_attr = f' style="font-size:{block_px:.3f}px"'
                    else:
                        # Body text - use the column's base font
                        tag = "p"
                        style_attr = ""
                    parts.append(
                        f'<{tag} class="replica-flow-block" '
                        f'data-block-id="{html.escape(block.id)}"{style_attr}>'
                        f'{_translated_html(block.translated_text)}'
                        f'</{tag}>'
                    )
                # Mark this block as handled
                column_block_ids.discard(block.id)

            parts.append('</div>')
            # Remove handled blocks from column_block_ids so they don't get rendered again
            for b in col_blocks:
                column_block_ids.discard(b.id)

    # Render remaining blocks (non-column or unhandled) with flow or absolute positioning
    # Collect remaining translated blocks for potential single-column flow rendering
    remaining_translated = []
    remaining_untranslated = []
    for block in page.text_blocks:
        if block.id in column_block_ids:
            remaining_untranslated.append(block)
            continue
        if classification and classification.columns:
            already_rendered = any(
                block.id in col.block_ids
                for col in classification.columns
            )
            if already_rendered:
                continue
        if block.translated_text:
            remaining_translated.append(block)
        else:
            remaining_untranslated.append(block)

    # For single/cover pages with multiple translated blocks, use flow rendering
    # Do NOT use single flow for MIXED/COLUMNS pages - those already have column flow
    from core.page_classifier import PageType
    use_single_flow = (
        classification
        and classification.page_type in (PageType.SINGLE, PageType.COVER)
        and len(remaining_translated) >= 2
    )

    if use_single_flow:
        # Compute the bounding box of all remaining translated blocks only
        col_pad = 4.0
        flow_x0 = min(b.bbox[0] for b in remaining_translated) - col_pad
        flow_y0 = min(b.bbox[1] for b in remaining_translated) - col_pad
        flow_x1 = max(b.bbox[2] for b in remaining_translated) + col_pad
        flow_y1 = max(b.bbox[3] for b in remaining_translated) + col_pad

        # Sample background color and determine text color
        img_path = _page_image_path(page, asset_base_dir)
        mask_bg, is_dark = _sample_region_bg(
            img_path, flow_x0, flow_y0, flow_x1, flow_y1, page.width, page.height
        )
        text_color = "#f0f0f0" if is_dark else "#1a1a1a"

        mask_class = " replica-mask-box" if show_boxes else ""
        parts.append(
            f'<div class="replica-mask replica-column-mask{mask_class}" '
            f'data-column="single" '
            f'style="left:{_raw_css_px_from_pt(flow_x0):.3f}px;'
            f'top:{_raw_css_px_from_pt(flow_y0):.3f}px;'
            f'width:{_raw_css_px_from_pt(flow_x1 - flow_x0):.3f}px;'
            f'height:{_raw_css_px_from_pt(flow_y1 - flow_y0):.3f}px;'
            f'background:{mask_bg}"></div>'
        )

        # Determine font sizes
        body_sizes = [_block_font_size(b) for b in remaining_translated]
        original_body_pt = sorted(body_sizes)[len(body_sizes) // 2]
        cn_body_pt = max(11.0, original_body_pt * 1.05)
        cn_body_px = _raw_css_px_from_pt(cn_body_pt)
        font_scale = cn_body_pt / max(original_body_pt, 1)

        box_class = " replica-column-flow-box" if show_boxes else ""
        parts.append(
            f'<div class="replica-column-flow{box_class}" '
            f'data-column="single" '
            f'data-base-font-px="{cn_body_px:.3f}" '
            f'style="left:{_raw_css_px_from_pt(flow_x0):.3f}px;'
            f'top:{_raw_css_px_from_pt(flow_y0):.3f}px;'
            f'width:{_raw_css_px_from_pt(flow_x1 - flow_x0):.3f}px;'
            f'height:{_raw_css_px_from_pt(flow_y1 - flow_y0):.3f}px;'
            f'font-size:{cn_body_px:.3f}px;'
            f'color:{text_color}">'
        )

        sorted_blocks = sorted(remaining_translated, key=lambda b: (b.bbox[1], b.bbox[0]))
        for block in sorted_blocks:
            block_font_pt = _block_font_size(block)
            ratio = block_font_pt / max(original_body_pt, 1)
            if ratio >= 1.5:
                tag = "h2"
                block_px = _raw_css_px_from_pt(block_font_pt * font_scale)
                style_attr = f' style="font-size:{block_px:.3f}px"'
            elif ratio >= 1.2:
                tag = "h3"
                block_px = _raw_css_px_from_pt(block_font_pt * font_scale)
                style_attr = f' style="font-size:{block_px:.3f}px"'
            else:
                tag = "p"
                style_attr = ""
            parts.append(
                f'<{tag} class="replica-flow-block" '
                f'data-block-id="{html.escape(block.id)}"{style_attr}>'
                f'{_translated_html(block.translated_text)}'
                f'</{tag}>'
            )

        parts.append('</div>')
    else:
        # Fall back to per-block absolute positioning for remaining translated blocks
        for block in remaining_translated:
            x0, y0, x1, y1 = block.bbox
            box_class = " replica-translation-box" if show_boxes else ""
            base_font_px = _raw_css_px_from_pt(_block_font_size(block))
            mask_pad_px = _mask_padding_px(block)
            mask_left_px = _raw_css_px_from_pt(x0) - mask_pad_px
            mask_top_px = _raw_css_px_from_pt(y0) - mask_pad_px
            mask_width_px = _raw_css_px_from_pt(x1 - x0) + (mask_pad_px * 2)
            mask_height_px = _raw_css_px_from_pt(y1 - y0) + (mask_pad_px * 2)
            mask_class = " replica-mask-box" if show_boxes else ""
            mask_bg = (bg_colors or {}).get(block.id, "rgba(255, 255, 255, 0.92)")
            parts.append(
                f'<div class="replica-mask{mask_class}" '
                f'data-block-id="{html.escape(block.id)}" '
                f'style="left:{mask_left_px:.3f}px;top:{mask_top_px:.3f}px;'
                f'width:{mask_width_px:.3f}px;height:{mask_height_px:.3f}px;'
                f'background:{mask_bg}"></div>'
            )
            parts.append(
                f'<div class="replica-translation{box_class}" '
                f'data-block-id="{html.escape(block.id)}" '
                f'data-base-font-px="{base_font_px:.3f}" '
                f'style="left:{_css_px_from_pt(x0)};top:{_css_px_from_pt(y0)};'
                f'width:{_css_px_from_pt(x1 - x0)};height:{_css_px_from_pt(y1 - y0)};'
                f'font-family:{_font_family(_block_font(block))};'
                f'font-size:{base_font_px:.3f}px">'
                f'{_translated_html(block.translated_text)}'
                '</div>'
            )

    # Render untranslated blocks with original spans
    # Only render if no flow mask is covering this page (i.e. no translations at all)
    has_flow_mask = use_single_flow or (classification and classification.columns and
                                         any(b.translated_text for b in page.text_blocks))
    if not has_flow_mask:
        for block in remaining_untranslated:
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


def render_layout_html(layout: LayoutDocument, output_path: str, show_boxes: bool = False,
                       asset_base_dir: str | None = None):
    from core.page_classifier import classify_document
    ensure_output_parent(output_path)
    if not layout.pages:
        raise ValueError("layout 没有页面")
    output_dir = Path(output_path).expanduser().resolve().parent
    asset_base = Path(asset_base_dir).expanduser().resolve() if asset_base_dir else output_dir
    first_page = layout.pages[0]

    # Classify all pages
    classifications = classify_document(layout.pages)
    class_map = {c.page_index: c for c in classifications}

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
    .replica-page-image {{
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        object-fit: fill;
        user-select: none;
        pointer-events: none;
    }}
    .replica-span {{
        position: absolute;
        display: block;
        white-space: pre;
        line-height: 1;
        overflow: visible;
        transform-origin: left top;
        z-index: 2;
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
        z-index: 3;
    }}
    .replica-mask {{
        position: absolute;
        display: block;
        pointer-events: none;
        z-index: 2;
    }}
    .replica-mask-box {{
        outline: 0.75px dashed rgba(255, 183, 0, 0.88);
        background: rgba(255, 248, 220, 0.82);
    }}
    .replica-translation-box {{
        outline: 0.75px solid rgba(216, 0, 0, 0.75);
        background: rgba(216, 0, 0, 0.045);
    }}
    .replica-overflow {{
        outline: 1.25px solid rgba(255, 0, 0, 0.95);
    }}
    .replica-image {{
        position: absolute;
        border: {("0.75px dashed rgba(0, 92, 255, 0.65)" if show_boxes else "0")};
        background: {("rgba(0, 92, 255, 0.08)" if show_boxes else "transparent")};
        z-index: 1;
    }}
    .replica-column-flow {{
        position: absolute;
        display: block;
        overflow: hidden;
        z-index: 3;
        line-height: 1.6;
        font-family: "Noto Serif SC", "Source Han Serif SC", "SimSun", serif;
        text-align: justify;
        padding: 2px 0;
    }}
    .replica-column-flow-box {{
        outline: 1px solid rgba(0, 128, 0, 0.6);
    }}
    .replica-flow-block {{
        margin: 0 0 0.3em 0;
        padding: 0;
        text-indent: 2em;
    }}
    .replica-flow-block:first-child {{
        margin-top: 0;
    }}
    h2.replica-flow-block,
    h3.replica-flow-block {{
        text-indent: 0;
        font-weight: bold;
        margin: 0.5em 0 0.2em 0;
        line-height: 1.3;
    }}
    h2.replica-flow-block:first-child,
    h3.replica-flow-block:first-child {{
        margin-top: 0;
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
        bg_colors = _load_page_bg_colors(page, asset_base) if _HAS_PIL else {}
        classification = class_map.get(page.index)
        chunks.append(_render_page(page, show_boxes=show_boxes, output_dir=output_dir,
                                   asset_base_dir=asset_base, bg_colors=bg_colors,
                                   classification=classification))
    chunks.extend([
        """
<script>
(function () {
    const MIN_FONT_PX = 5 * 96 / 72;

    function overflows(el) {
        return el.scrollHeight > el.clientHeight + 0.5 || el.scrollWidth > el.clientWidth + 0.5;
    }

    function fitElement(el, baseKey) {
        const base = Number(el.dataset[baseKey] || window.getComputedStyle(el).fontSize.replace("px", ""));
        el.style.fontSize = `${base}px`;
        el.classList.remove("replica-overflow");
        if (!overflows(el)) {
            el.dataset.fitFontPx = base.toFixed(3);
            return { fontPx: base, overflow: false };
        }

        el.style.fontSize = `${MIN_FONT_PX}px`;
        if (overflows(el)) {
            el.dataset.fitFontPx = MIN_FONT_PX.toFixed(3);
            el.dataset.fitOverflow = "true";
            el.classList.add("replica-overflow");
            return { fontPx: MIN_FONT_PX, overflow: true };
        }

        let low = MIN_FONT_PX;
        let high = base;
        for (let i = 0; i < 16; i += 1) {
            const mid = (low + high) / 2;
            el.style.fontSize = `${mid}px`;
            if (overflows(el)) {
                high = mid;
            } else {
                low = mid;
            }
        }
        el.style.fontSize = `${low}px`;
        el.dataset.fitFontPx = low.toFixed(3);
        return { fontPx: low, overflow: false };
    }

    window.replicaFitTranslations = function () {
        const results = [];

        // Fit per-block absolute positioned translations
        document.querySelectorAll(".replica-translation").forEach((el) => {
            const result = fitElement(el, "baseFontPx");
            results.push({
                blockId: el.dataset.blockId,
                page: el.closest(".replica-page")?.dataset.page,
                ...result
            });
        });

        // Fit column flow containers
        document.querySelectorAll(".replica-column-flow").forEach((el) => {
            const result = fitElement(el, "baseFontPx");
            results.push({
                blockId: `column-${el.dataset.column}`,
                page: el.closest(".replica-page")?.dataset.page,
                ...result
            });
        });

        window.replicaFitResults = results;
        return results;
    };

    window.replicaFitTranslations();
}());
</script>
""",
        "</body>",
        "</html>",
    ])
    Path(output_path).write_text("\n".join(chunks), encoding="utf-8")


def render_layout_json_html(layout_json_path: str, output_path: str, show_boxes: bool = False):
    layout_path = Path(layout_json_path).expanduser().resolve()
    layout = layout_document_from_json(layout_path.read_text(encoding="utf-8"))
    render_layout_html(layout, output_path, show_boxes=show_boxes, asset_base_dir=str(layout_path.parent))
