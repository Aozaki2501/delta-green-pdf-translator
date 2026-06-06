"""
Page structure extraction for the typeset reflow pipeline (Phase A).

Extracts all visual elements from PDF pages: background color, images,
vector decorations (lines, rects), and text region bounding boxes.
Outputs a PageStructureDocument that can be serialized to page_structure.json.
"""

from io import BytesIO
import math
from pathlib import Path

from PIL import Image

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        raise ImportError("PyMuPDF not installed. Run: pip install pymupdf")

from core.typeset_models import (
    PAGE_STRUCTURE_SCHEMA_VERSION,
    BackgroundLayer,
    DecorationElement,
    ImageElement,
    PageStructure,
    PageStructureDocument,
    TextLineBBox,
    TextSpanBBox,
    TextRegionBBox,
)
from core.utils import ensure_output_parent


def _round_bbox(bbox) -> list[float]:
    """Round bbox values to 3 decimal places."""
    return [round(float(v), 3) for v in bbox]


def _color_int_to_css(value: int) -> str:
    """Convert an integer color value to CSS hex string."""
    rgb = int(value) & 0xFFFFFF
    return f"#{rgb:06x}"


def _color_tuple_to_css(color_tuple) -> str | None:
    """Convert a PyMuPDF color tuple (0-1 floats) to CSS hex string."""
    if color_tuple is None:
        return None
    if len(color_tuple) == 0:
        return None
    if len(color_tuple) == 1:
        # Grayscale
        g = int(color_tuple[0] * 255)
        return f"#{g:02x}{g:02x}{g:02x}"
    if len(color_tuple) == 3:
        r = int(color_tuple[0] * 255)
        g = int(color_tuple[1] * 255)
        b = int(color_tuple[2] * 255)
        return f"#{r:02x}{g:02x}{b:02x}"
    if len(color_tuple) == 4:
        # CMYK → approximate RGB
        c, m, y, k = color_tuple
        r = int(255 * (1 - c) * (1 - k))
        g = int(255 * (1 - m) * (1 - k))
        b = int(255 * (1 - y) * (1 - k))
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _crop_axis_aligned_pixmap_to_bbox(pix, transform, bbox) -> tuple[Image.Image, int, int]:
    """Crop an axis-aligned PDF image to the visible page bbox using its transform."""
    image = Image.open(BytesIO(pix.tobytes("png")))
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if pix.alpha else "RGB")

    if not transform or len(transform) != 6:
        return image, pix.width, pix.height

    a, b, c, d, e, f = [float(v) for v in transform]
    if abs(b) > 1e-6 or abs(c) > 1e-6 or abs(a) < 1e-6 or abs(d) < 1e-6:
        return image, pix.width, pix.height

    x0, y0, x1, y1 = [float(v) for v in bbox]
    display_left = min(e, e + a)
    display_top = min(f, f + d)
    display_width = abs(a)
    display_height = abs(d)

    left_frac = max(0.0, min(1.0, (x0 - display_left) / display_width))
    right_frac = max(0.0, min(1.0, (x1 - display_left) / display_width))
    top_frac = max(0.0, min(1.0, (y0 - display_top) / display_height))
    bottom_frac = max(0.0, min(1.0, (y1 - display_top) / display_height))

    if right_frac <= left_frac or bottom_frac <= top_frac:
        return image, pix.width, pix.height

    if a >= 0:
        crop_left = left_frac * pix.width
        crop_right = right_frac * pix.width
    else:
        crop_left = (1.0 - right_frac) * pix.width
        crop_right = (1.0 - left_frac) * pix.width

    if d >= 0:
        crop_top = top_frac * pix.height
        crop_bottom = bottom_frac * pix.height
    else:
        crop_top = (1.0 - bottom_frac) * pix.height
        crop_bottom = (1.0 - top_frac) * pix.height

    crop_box = (
        max(0, min(pix.width - 1, round(crop_left))),
        max(0, min(pix.height - 1, round(crop_top))),
        max(1, min(pix.width, round(crop_right))),
        max(1, min(pix.height, round(crop_bottom))),
    )

    image = image.crop(crop_box)
    if a < 0:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if d < 0:
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return image, image.width, image.height


def _is_axis_aligned_transform(transform) -> bool:
    if not transform or len(transform) != 6:
        return True
    _, b, c, _, _, _ = [float(v) for v in transform]
    return abs(b) <= 1e-6 and abs(c) <= 1e-6


def _line_angle(line) -> float:
    direction = line.get("dir", (1.0, 0.0))
    if not direction or len(direction) != 2:
        return 0.0
    return math.degrees(math.atan2(float(direction[1]), float(direction[0])))


def _dominant_text_angle(lines) -> float:
    angles = []
    for line in lines:
        if not any(span.get("text", "").strip() for span in line.get("spans", [])):
            continue
        angle = _line_angle(line)
        if abs(angle) >= 0.5:
            angles.append(angle)
    if not angles:
        return 0.0
    return round(sum(angles) / len(angles), 2)


def _line_text(line) -> str:
    return "".join(span.get("text", "") for span in line.get("spans", []))


def _line_style(line) -> tuple[float, bool, bool, str]:
    spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
    if not spans:
        return 11.0, False, False, "#000000"

    total_weight = 0
    weighted_size = 0.0
    bold = False
    italic = False
    color = "#000000"
    for span in spans:
        text = span.get("text", "")
        weight = max(1, len(text.strip()))
        size = float(span.get("size", 11.0))
        flags = int(span.get("flags", 0))
        weighted_size += size * weight
        total_weight += weight
        bold = bold or bool(flags & (1 << 4))
        italic = italic or bool(flags & (1 << 1))
        if color == "#000000":
            color = _color_int_to_css(int(span.get("color", 0)))
    return round(weighted_size / max(1, total_weight), 2), bold, italic, color


def _span_style(span) -> tuple[float, bool, bool, str]:
    flags = int(span.get("flags", 0))
    return (
        round(float(span.get("size", 11.0)), 2),
        bool(flags & (1 << 4)),
        bool(flags & (1 << 1)),
        _color_int_to_css(int(span.get("color", 0))),
    )


def _line_spans(line) -> list[TextSpanBBox]:
    spans: list[TextSpanBBox] = []
    for span in line.get("spans", []):
        text = span.get("text", "")
        if not text:
            continue
        font_size, bold, italic, color = _span_style(span)
        spans.append(TextSpanBBox(
            bbox=_round_bbox(span.get("bbox", [0, 0, 0, 0])),
            text=text,
            font_size=font_size,
            bold=bold,
            italic=italic,
            color=color,
        ))
    return spans


def _text_lines(lines) -> list[TextLineBBox]:
    result: list[TextLineBBox] = []
    for line in lines:
        text = _line_text(line)
        if not text.strip():
            continue
        font_size, bold, italic, color = _line_style(line)
        result.append(TextLineBBox(
            bbox=_round_bbox(line.get("bbox", [0, 0, 0, 0])),
            text=text,
            font_size=font_size,
            bold=bold,
            italic=italic,
            color=color,
            angle=round(_line_angle(line), 2),
            spans=_line_spans(line),
        ))
    return result


class PageStructureExtractor:
    """Extract page structure (background, images, decorations, text regions) from a PDF.

    This is Phase A of the typeset reflow pipeline.
    """

    def __init__(self, pdf_path: str, output_dir: str):
        """
        Args:
            pdf_path: Path to the source PDF file.
            output_dir: Output directory for extracted assets (images, JSON).
        """
        self.pdf_path = str(pdf_path)
        self.output_dir = Path(output_dir)
        self.doc = pymupdf.open(self.pdf_path)
        self.image_dir = self.output_dir / "assets" / "typeset_images"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        """Close the underlying PDF document."""
        self.doc.close()

    def extract(self, start_page: int = 0, end_page: int | None = None) -> PageStructureDocument:
        """Extract page structure for a range of pages.

        Args:
            start_page: First page index (0-based, inclusive).
            end_page: Last page index (exclusive). Defaults to total page count.

        Returns:
            PageStructureDocument containing all extracted page structures.
        """
        total = len(self.doc)
        if end_page is None:
            end_page = total
        if start_page < 0 or start_page >= total:
            raise ValueError(f"起始页超出范围：PDF 共 {total} 页")
        if end_page <= start_page:
            raise ValueError("结束页必须大于起始页")
        if end_page > total:
            end_page = total

        pages = [self.extract_page(i) for i in range(start_page, end_page)]
        return PageStructureDocument(
            schema_version=PAGE_STRUCTURE_SCHEMA_VERSION,
            source_pdf=Path(self.pdf_path).name,
            page_count=len(pages),
            pages=pages,
        )

    def extract_page(self, page_index: int) -> PageStructure:
        """Extract structure for a single page.

        Args:
            page_index: Zero-based page index.

        Returns:
            PageStructure with background, images, decorations, and text regions.
        """
        page = self.doc[page_index]
        background = self.extract_background(page)
        images = self.extract_images(page, page_index)
        decorations = self.extract_decorations(page)
        text_regions = self.extract_text_regions(page)

        return PageStructure(
            page_index=page_index,
            width=round(float(page.rect.width), 3),
            height=round(float(page.rect.height), 3),
            background=background,
            images=images,
            decorations=decorations,
            text_regions=text_regions,
        )

    def extract_background(self, page) -> BackgroundLayer:
        """Extract page background color.

        Checks for filled rectangles covering the full page (common in designed PDFs)
        or falls back to None (white background).
        """
        page_rect = page.rect
        page_area = page_rect.width * page_rect.height

        # Check drawings for a large filled rect that covers most of the page
        try:
            drawings = page.get_drawings()
        except Exception:
            return BackgroundLayer(color=None, gradient=None)

        for drawing in drawings:
            # Look for filled rectangles that cover >= 90% of the page
            if drawing.get("fill") is None:
                continue
            items = drawing.get("items", [])
            if not items:
                continue
            # Check if this drawing has a rect item covering the page
            for item in items:
                if item[0] == "re":  # rectangle item
                    rect = item[1]
                    rect_area = abs(rect.width * rect.height)
                    if rect_area >= page_area * 0.9:
                        fill_color = _color_tuple_to_css(drawing.get("fill"))
                        if fill_color and fill_color != "#ffffff":
                            return BackgroundLayer(color=fill_color, gradient=None)

        return BackgroundLayer(color=None, gradient=None)

    def extract_images(self, page, page_index: int) -> list[ImageElement]:
        """Extract independent images from the page and save pixel data.

        Args:
            page: PyMuPDF page object.
            page_index: Zero-based page index.

        Returns:
            List of ImageElement with saved image paths.
        """
        images: list[ImageElement] = []
        page_dict = page.get_text("dict")
        image_blocks = [
            block for block in page_dict.get("blocks", [])
            if block.get("type") == 1 and block.get("image")
        ]

        for img_idx, block in enumerate(image_blocks):
            bbox = block.get("bbox")
            if not bbox or len(bbox) != 4:
                continue

            pix = pymupdf.Pixmap(block["image"])
            if block.get("mask"):
                mask = pymupdf.Pixmap(block["mask"])
                pix = pymupdf.Pixmap(pix, mask)
            if pix.n - pix.alpha > 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)

            transform = block.get("transform")
            if _is_axis_aligned_transform(transform):
                image, width_px, height_px = _crop_axis_aligned_pixmap_to_bbox(
                    pix, transform, bbox
                )
                image_transform = None
            else:
                image = Image.open(BytesIO(pix.tobytes("png")))
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA" if pix.alpha else "RGB")
                width_px = image.width
                height_px = image.height
                image_transform = _round_bbox(transform)

            # Save images as PNG so Chromium can render them from HTML.
            img_id = f"p{page_index + 1:04d}_img{img_idx + 1:04d}"
            self.image_dir.mkdir(parents=True, exist_ok=True)
            img_filename = f"{img_id}.png"
            img_path = self.image_dir / img_filename
            image.save(str(img_path))

            # Relative path from output_dir
            relative_path = f"assets/typeset_images/{img_filename}"

            images.append(ImageElement(
                id=img_id,
                bbox=_round_bbox(bbox),
                image_path=relative_path,
                width_px=int(width_px),
                height_px=int(height_px),
                transform=image_transform,
            ))

        return images

    def extract_decorations(self, page) -> list[DecorationElement]:
        """Extract vector decorative elements (lines, rectangles, paths).

        Args:
            page: PyMuPDF page object.

        Returns:
            List of DecorationElement for lines, rects, and paths.
        """
        decorations: list[DecorationElement] = []
        page_rect = page.rect
        page_area = page_rect.width * page_rect.height

        try:
            drawings = page.get_drawings()
        except Exception:
            return decorations

        dec_idx = 0
        page_index = page.number

        for drawing in drawings:
            items = drawing.get("items", [])
            if not items:
                continue

            stroke_color = _color_tuple_to_css(drawing.get("color"))
            fill_color = _color_tuple_to_css(drawing.get("fill"))
            raw_width = drawing.get("width")
            stroke_width = float(raw_width) if raw_width is not None else 0.0

            # Skip background-sized filled rects (already handled as background)
            rect_obj = drawing.get("rect")
            if rect_obj and fill_color:
                rect_area = abs(rect_obj.width * rect_obj.height)
                if rect_area >= page_area * 0.9:
                    continue

            for item in items:
                item_type = item[0]

                if item_type == "l":  # line
                    # item[1] = start point, item[2] = end point
                    p1, p2 = item[1], item[2]
                    x0 = min(p1.x, p2.x)
                    y0 = min(p1.y, p2.y)
                    x1 = max(p1.x, p2.x)
                    y1 = max(p1.y, p2.y)
                    dec_id = f"p{page_index + 1:04d}_dec{dec_idx + 1:04d}"
                    decorations.append(DecorationElement(
                        id=dec_id,
                        element_type="line",
                        bbox=_round_bbox([x0, y0, x1, y1]),
                        stroke_color=stroke_color,
                        fill_color=None,
                        stroke_width=stroke_width,
                        points=[[round(p1.x, 3), round(p1.y, 3)],
                                [round(p2.x, 3), round(p2.y, 3)]],
                    ))
                    dec_idx += 1

                elif item_type == "re":  # rectangle
                    rect = item[1]
                    rect_area = abs(rect.width * rect.height)
                    # Skip page-sized rects (backgrounds)
                    if rect_area >= page_area * 0.9:
                        continue
                    dec_id = f"p{page_index + 1:04d}_dec{dec_idx + 1:04d}"
                    decorations.append(DecorationElement(
                        id=dec_id,
                        element_type="rect",
                        bbox=_round_bbox([rect.x0, rect.y0, rect.x1, rect.y1]),
                        stroke_color=stroke_color,
                        fill_color=fill_color,
                        stroke_width=stroke_width,
                    ))
                    dec_idx += 1

                elif item_type == "c":  # curve (bezier)
                    # Curves have 4 points: item[1..4]
                    points = []
                    for pt_idx in range(1, min(len(item), 5)):
                        pt = item[pt_idx]
                        points.append([round(pt.x, 3), round(pt.y, 3)])
                    if points:
                        xs = [p[0] for p in points]
                        ys = [p[1] for p in points]
                        dec_id = f"p{page_index + 1:04d}_dec{dec_idx + 1:04d}"
                        decorations.append(DecorationElement(
                            id=dec_id,
                            element_type="path",
                            bbox=_round_bbox([min(xs), min(ys), max(xs), max(ys)]),
                            stroke_color=stroke_color,
                            fill_color=fill_color,
                            stroke_width=stroke_width,
                            points=points,
                        ))
                        dec_idx += 1

                elif item_type == "qu":  # quad (4-point polygon)
                    quad = item[1]
                    points = [[round(quad.ul.x, 3), round(quad.ul.y, 3)],
                              [round(quad.ur.x, 3), round(quad.ur.y, 3)],
                              [round(quad.lr.x, 3), round(quad.lr.y, 3)],
                              [round(quad.ll.x, 3), round(quad.ll.y, 3)]]
                    xs = [p[0] for p in points]
                    ys = [p[1] for p in points]
                    dec_id = f"p{page_index + 1:04d}_dec{dec_idx + 1:04d}"
                    decorations.append(DecorationElement(
                        id=dec_id,
                        element_type="path",
                        bbox=_round_bbox([min(xs), min(ys), max(xs), max(ys)]),
                        stroke_color=stroke_color,
                        fill_color=fill_color,
                        stroke_width=stroke_width,
                        points=points,
                    ))
                    dec_idx += 1

        return decorations

    def extract_text_regions(self, page) -> list[TextRegionBBox]:
        """Extract text region bounding boxes from the page.

        Uses page.get_text("dict") to find text blocks and their bboxes,
        using the same coordinate rules as the page structure extractor.

        Args:
            page: PyMuPDF page object.

        Returns:
            List of TextRegionBBox with block IDs.
        """
        text_regions: list[TextRegionBBox] = []
        page_index = page.number
        page_dict = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)

        region_idx = 0
        for block in page_dict.get("blocks", []):
            block_type = block.get("type")
            if block_type != 0:  # Only text blocks
                continue

            # Check if block has actual text content
            has_text = False
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        has_text = True
                        break
                if has_text:
                    break

            if not has_text:
                continue

            region_id = f"p{page_index + 1:04d}_r{region_idx + 1:04d}"
            # Generate a block_id referencing the layout text block
            block_id = f"p{page_index + 1:04d}_t{region_idx:04d}"

            text_regions.append(TextRegionBBox(
                id=region_id,
                bbox=_round_bbox(block["bbox"]),
                block_ids=[block_id],
                angle=_dominant_text_angle(block.get("lines", [])),
                lines=_text_lines(block.get("lines", [])),
            ))
            region_idx += 1

        return text_regions


def extract_page_structure_to_file(
    pdf_path: str,
    output_dir: str,
    start_page: int = 0,
    end_page: int | None = None,
) -> PageStructureDocument:
    """Extract page structure from a PDF and save to page_structure.json.

    Args:
        pdf_path: Path to the source PDF file.
        output_dir: Output directory for the JSON file and assets.
        start_page: First page index (0-based, inclusive).
        end_page: Last page index (exclusive). Defaults to all pages.

    Returns:
        The extracted PageStructureDocument.
    """
    output_path = Path(output_dir) / "page_structure.json"
    ensure_output_parent(str(output_path))

    with PageStructureExtractor(pdf_path, output_dir) as extractor:
        structure = extractor.extract(start_page=start_page, end_page=end_page)

    output_path.write_text(structure.to_json(), encoding="utf-8")
    return structure
