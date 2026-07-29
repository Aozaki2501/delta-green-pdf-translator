"""
Page structure extraction for the typeset reflow pipeline (Phase A).

Extracts all visual elements from PDF pages: background color, images,
vector decorations (lines, rects), and text region bounding boxes.
Outputs a PageStructureDocument that can be serialized to page_structure.json.
"""

from dataclasses import replace
from io import BytesIO
import hashlib
import math
from pathlib import Path
from statistics import median

from PIL import Image, ImageChops

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
    DisplayListObject,
    ImageElement,
    PageStructure,
    PageStructureDocument,
    TextLineBBox,
    TextSpanBBox,
    TextRegionBBox,
)
from core.utils import ensure_output_parent

# Plausible baseline-to-baseline distance for body text, used to tell a wrapped
# line apart from a real paragraph break.
_MIN_LINE_PITCH_PT = 3.0
_MAX_LINE_PITCH_PT = 40.0


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


def _json_value(value):
    """Convert PyMuPDF geometry values into JSON-safe primitives."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "x") and hasattr(value, "y"):
        return [round(float(value.x), 3), round(float(value.y), 3)]
    if all(hasattr(value, attr) for attr in ("x0", "y0", "x1", "y1")):
        return [round(float(value.x0), 3), round(float(value.y0), 3),
                round(float(value.x1), 3), round(float(value.y1), 3)]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


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


def _bbox_covers_page(bbox: list[float], page_rect) -> bool:
    if len(bbox) != 4:
        return False
    x0, y0, x1, y1 = [float(v) for v in bbox]
    width = max(0.0, x1 - x0)
    height = max(0.0, y1 - y0)
    return width >= float(page_rect.width) * 0.9 and height >= float(page_rect.height) * 0.9


def _image_has_single_color(image: Image.Image) -> bool:
    extrema = image.getextrema()
    if not extrema:
        return False
    if isinstance(extrema[0], tuple):
        return all(low == high for low, high in extrema)
    low, high = extrema
    return low == high


def _is_mostly_dark_opaque_image(image: Image.Image) -> bool:
    rgba = image.convert("RGBA")
    total = max(1, rgba.width * rgba.height)
    alpha = rgba.getchannel("A")
    lightness = rgba.convert("L")
    opaque_mask = alpha.point(lambda value: 255 if value >= 250 else 0)
    dark_mask = lightness.point(lambda value: 255 if value <= 24 else 0)
    dark_opaque_mask = ImageChops.multiply(opaque_mask, dark_mask)
    opaque = opaque_mask.histogram()[255]
    dark = dark_opaque_mask.histogram()[255]
    return opaque / total >= 0.9 and dark / total >= 0.85


def _is_redundant_full_page_stencil_overlay(
    block: dict,
    bbox: list[float],
    image: Image.Image,
    page_rect,
    previous_images: list[ImageElement],
    text_regions: list[TextRegionBBox],
) -> bool:
    if int(block.get("bpc") or 0) != 1:
        return False
    if not _bbox_covers_page(bbox, page_rect):
        return False
    if not text_regions:
        return False
    has_full_page_base = any(
        _bbox_covers_page(previous.bbox, page_rect)
        for previous in previous_images
    )
    if not has_full_page_base:
        return False
    return _image_has_single_color(image) or _is_mostly_dark_opaque_image(image)


def _line_angle(line) -> float:
    direction = line.get("dir", (1.0, 0.0))
    if not direction or len(direction) != 2:
        return 0.0
    return math.degrees(math.atan2(float(direction[1]), float(direction[0])))


def _dominant_text_angle(lines) -> float:
    angles = []
    for line in lines:
        if not any(_span_text(span).strip() for span in line.get("spans", [])):
            continue
        angle = _line_angle(line)
        if abs(angle) >= 0.5:
            angles.append(angle)
    if not angles:
        return 0.0
    return round(sum(angles) / len(angles), 2)


def _span_text(span) -> str:
    text = span.get("text")
    if text is not None:
        return str(text)
    return "".join(str(char.get("c", "")) for char in span.get("chars", []))


def _line_text(line) -> str:
    return "".join(_span_text(span) for span in line.get("spans", []))


def _line_style(line) -> tuple[float, bool, bool, str]:
    spans = [span for span in line.get("spans", []) if _span_text(span).strip()]
    if not spans:
        return 11.0, False, False, "#000000"

    total_weight = 0
    weighted_size = 0.0
    bold = False
    italic = False
    color = "#000000"
    for span in spans:
        text = _span_text(span)
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


def _origin_key(origin) -> tuple[float, float]:
    return round(float(origin[0]), 3), round(float(origin[1]), 3)


def _trace_matches_span(trace: dict, span: dict) -> bool:
    """Match one semantic span to its exact PDF paint operation.

    PDF ``ActualText`` may intentionally expose a different semantic
    character than the glyph recorded by ``get_texttrace``. Font style and
    glyph origin remain the shared identity. The raw extractor may derive the
    superscript bit from line geometry even though the paint trace omits it.
    """
    if trace.get("font") != span.get("font"):
        return False
    font_flags_mask = ~int(pymupdf.TEXT_FONT_SUPERSCRIPT)
    if (
        int(trace.get("flags", 0)) & font_flags_mask
        != int(span.get("flags", 0)) & font_flags_mask
    ):
        return False
    raw_origins = {
        _origin_key(char["origin"])
        for char in span.get("chars", [])
    }
    trace_origins = {
        _origin_key(char[2])
        for char in trace.get("chars", ())
    }
    return bool(raw_origins & trace_origins)


def _match_traces(span: dict, traces: list[dict]) -> list[dict]:
    """Map a raw span to every paint operation sharing exact glyph origins."""
    if not span.get("chars"):
        raise ValueError("raw text span has no character geometry")

    candidates = []
    for trace in traces:
        if _trace_matches_span(trace, span):
            candidates.append(trace)
    if not candidates:
        raise ValueError(
            f"raw text span has no matching text trace: {_span_text(span)!r}"
        )
    return candidates


def _common_trace_value(traces: list[dict], key: str):
    values = [trace.get(key) for trace in traces]
    return values[0] if all(value == values[0] for value in values) else None


def _line_spans(line, traces: list[dict]) -> list[TextSpanBBox]:
    spans: list[TextSpanBBox] = []
    for span in line.get("spans", []):
        text = _span_text(span)
        if not text.strip():
            continue
        font_size, bold, italic, color = _span_style(span)
        matched_traces = _match_traces(span, traces)
        trace = matched_traces[0]
        seqnos = sorted({
            int(item["seqno"])
            for item in matched_traces
            if item.get("seqno") is not None
        })
        chars = [_json_value(char) for char in span.get("chars", [])]
        origin = span.get("origin")
        spans.append(TextSpanBBox(
            bbox=_round_bbox(span.get("bbox", [0, 0, 0, 0])),
            text=text,
            font_size=font_size,
            bold=bold,
            italic=italic,
            color=color,
            font=span.get("font") or (trace or {}).get("font"),
            origin=_json_value(origin) if origin is not None else _json_value((trace or {}).get("chars", [{}])[0].get("origin") if (trace or {}).get("chars") else None),
            alpha=span.get("alpha", _common_trace_value(matched_traces, "opacity")),
            ascender=span.get("ascender", _common_trace_value(matched_traces, "ascender")),
            descender=span.get("descender", _common_trace_value(matched_traces, "descender")),
            chars=chars or [
                {"origin": _json_value(char[2]), "bbox": _json_value(char[3]), "c": chr(int(char[0]))}
                for char in (trace or {}).get("chars", ())
            ],
            seqno=seqnos[0] if len(seqnos) == 1 else None,
            seqnos=seqnos,
        ))
    return spans


def _text_lines(lines, traces: list[dict]) -> list[TextLineBBox]:
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
            spans=_line_spans(line, traces),
        ))
    return result


def _dominant_font_size(lines: list[TextLineBBox]) -> float:
    sizes = [float(line.font_size) for line in lines if line.font_size]
    return median(sizes) if sizes else 0.0


def _line_pitch(lines: list[TextLineBBox]) -> float | None:
    tops = sorted(float(line.bbox[1]) for line in lines)
    advances = [
        later - earlier
        for earlier, later in zip(tops, tops[1:])
        if _MIN_LINE_PITCH_PT < later - earlier < _MAX_LINE_PITCH_PT
    ]
    return median(advances) if advances else None


def _is_paragraph_continuation(previous: TextRegionBBox, following: TextRegionBBox) -> bool:
    """Return True when two adjacent PDF text blocks are one flowing paragraph.

    PyMuPDF splits a hanging-indent paragraph into one block per line, which makes
    every line its own translation unit and cuts sentences apart mid-clause.
    """
    previous_size = _dominant_font_size(previous.lines)
    following_size = _dominant_font_size(following.lines)
    if previous_size <= 0 or following_size <= 0:
        return False
    if abs(previous_size - following_size) > max(previous_size, following_size) * 0.12:
        return False

    horizontal_overlap = (
        min(float(previous.bbox[2]), float(following.bbox[2]))
        - max(float(previous.bbox[0]), float(following.bbox[0]))
    )
    if horizontal_overlap <= 0:
        return False

    # Starting further left than the previous block marks a new indent regime
    # (a bullet list giving way to body text), not a wrapped line.
    if (
        min(float(line.bbox[0]) for line in following.lines)
        < min(float(line.bbox[0]) for line in previous.lines) - previous_size * 0.8
    ):
        return False

    vertical_gap = float(following.bbox[1]) - float(previous.bbox[3])
    if vertical_gap < 0:
        return False
    pitch = (
        _line_pitch(previous.lines)
        or _line_pitch(following.lines)
        or previous_size * 1.6
    )
    return vertical_gap <= pitch * 0.6


def _merge_flowing_text_regions(regions: list[TextRegionBBox]) -> list[TextRegionBBox]:
    """Merge adjacent regions that PyMuPDF split out of a single paragraph.

    Regions keep their original paint order: reordering them by position would
    break the reading order of multi-column pages.
    """
    merged: list[TextRegionBBox] = []
    for region in regions:
        if merged and _is_paragraph_continuation(merged[-1], region):
            previous = merged[-1]
            merged[-1] = replace(
                previous,
                bbox=_round_bbox([
                    min(float(previous.bbox[0]), float(region.bbox[0])),
                    min(float(previous.bbox[1]), float(region.bbox[1])),
                    max(float(previous.bbox[2]), float(region.bbox[2])),
                    max(float(previous.bbox[3]), float(region.bbox[3])),
                ]),
                block_ids=list(previous.block_ids) + list(region.block_ids),
                lines=list(previous.lines) + list(region.lines),
            )
            continue
        merged.append(region)
    return merged


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

    @staticmethod
    def _get_texttrace(page) -> list[dict]:
        return list(page.get_texttrace())

    def extract(
        self,
        start_page: int = 0,
        end_page: int | None = None,
        include_images: bool = True,
    ) -> PageStructureDocument:
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

        pages = [
            self.extract_page(i, include_images=include_images)
            for i in range(start_page, end_page)
        ]
        return PageStructureDocument(
            schema_version=PAGE_STRUCTURE_SCHEMA_VERSION,
            source_pdf=Path(self.pdf_path).name,
            page_count=len(pages),
            pages=pages,
            source_sha256=hashlib.sha256(Path(self.pdf_path).read_bytes()).hexdigest(),
        )

    def extract_page(self, page_index: int, include_images: bool = True) -> PageStructure:
        """Extract structure for a single page.

        Args:
            page_index: Zero-based page index.

        Returns:
            PageStructure with background, images, decorations, and text regions.
        """
        page = self.doc[page_index]
        background = self.extract_background(page)
        decorations = self.extract_decorations(page)
        text_traces = self._get_texttrace(page)
        text_regions = self.extract_text_regions(page, text_traces=text_traces)
        images = (
            self.extract_images(page, page_index, text_regions=text_regions)
            if include_images else []
        )
        display_list = self.extract_display_list(
            page,
            page_index,
            images=images,
            decorations=decorations,
            text_regions=text_regions,
        )

        media_box = _round_bbox(page.mediabox)
        crop_box = _round_bbox(page.cropbox)
        user_unit = self._page_user_unit(page)

        return PageStructure(
            page_index=page_index,
            width=round(float(page.rect.width), 3),
            height=round(float(page.rect.height), 3),
            background=background,
            images=images,
            decorations=decorations,
            text_regions=text_regions,
            media_box=media_box,
            crop_box=crop_box,
            rotation=int(page.rotation),
            user_unit=user_unit,
            display_list=display_list,
        )

    @staticmethod
    def _page_user_unit(page) -> float:
        direct = getattr(page, "user_unit", None)
        if direct is not None:
            return float(direct or 1.0)
        try:
            kind, value = page.parent.xref_get_key(page.xref, "UserUnit")
            if kind not in ("null", "none") and value:
                return float(value)
        except (AttributeError, RuntimeError, ValueError, TypeError):
            pass
        return 1.0

    def extract_background(self, page) -> BackgroundLayer:
        """Extract page background color.

        Checks for filled rectangles covering the full page (common in designed PDFs)
        or falls back to None (white background).
        """
        page_rect = page.rect
        page_area = page_rect.width * page_rect.height

        # Check drawings for a large filled rect that covers most of the page
        drawings = page.get_drawings(extended=True)

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

    def extract_images(
        self,
        page,
        page_index: int,
        text_regions: list[TextRegionBBox] | None = None,
    ) -> list[ImageElement]:
        """Extract independent images from the page and save pixel data.

        Args:
            page: PyMuPDF page object.
            page_index: Zero-based page index.

        Returns:
            List of ImageElement with saved image paths.
        """
        images: list[ImageElement] = []
        page_dict = page.get_text("dict")
        image_infos = list(page.get_image_info(hashes=True, xrefs=True))
        source_image_xrefs = self._source_image_xrefs(image_infos)
        image_blocks = [
            block for block in page_dict.get("blocks", [])
            if block.get("type") == 1 and block.get("image")
        ]

        for img_idx, block in enumerate(image_blocks):
            bbox = block.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            x0, y0, x1, y1 = [float(v) for v in bbox]
            if x1 <= x0 or y1 <= y0:
                continue

            pix = pymupdf.Pixmap(block["image"])
            # get_image_info() hashes the original samples before mask composition.
            image_digest = hashlib.md5(pix.samples).digest()
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
                image_transform = _round_bbox(transform) if transform else None
            else:
                image = Image.open(BytesIO(pix.tobytes("png")))
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA" if pix.alpha else "RGB")
                width_px = image.width
                height_px = image.height
                image_transform = _round_bbox(transform)
            if width_px <= 0 or height_px <= 0 or image.width <= 0 or image.height <= 0:
                continue
            if _is_redundant_full_page_stencil_overlay(
                block,
                _round_bbox(bbox),
                image,
                page.rect,
                images,
                text_regions or [],
            ):
                continue

            # Save images as PNG so Chromium can render them from HTML.
            img_id = f"p{page_index + 1:04d}_img{img_idx + 1:04d}"
            self.image_dir.mkdir(parents=True, exist_ok=True)
            img_filename = f"{img_id}.png"
            img_path = self.image_dir / img_filename
            image.save(str(img_path))

            # Relative path from output_dir
            relative_path = f"assets/typeset_images/{img_filename}"

            image_info = self._match_image_info(
                block,
                image_infos,
                image_digest,
                source_image_xrefs,
            )
            digest = image_info.get("digest") if image_info else None
            if isinstance(digest, bytes):
                digest = digest.hex()
            images.append(ImageElement(
                id=img_id,
                bbox=_round_bbox(bbox),
                image_path=relative_path,
                width_px=int(width_px),
                height_px=int(height_px),
                transform=image_transform,
                xref=image_info.get("xref") if image_info else None,
                digest=digest,
                bpc=image_info.get("bpc") if image_info else block.get("bpc"),
                colorspace=(image_info or {}).get("colorspace") or block.get("colorspace"),
                xres=(image_info or {}).get("xres") or block.get("xres"),
                yres=(image_info or {}).get("yres") or block.get("yres"),
                has_mask=bool((image_info or {}).get("has-mask") or block.get("mask")),
            ))

        return images

    def _source_image_xrefs(self, image_infos: list[dict]) -> dict[bytes, set[int]]:
        """Map encoded image bytes to their PDF xrefs without lossy pixel conversion."""
        result: dict[bytes, set[int]] = {}
        for info in image_infos:
            xref = info.get("xref")
            if not isinstance(xref, int) or xref <= 0:
                continue
            extracted = self.doc.extract_image(xref)
            payload = extracted.get("image") if extracted else None
            if not payload:
                continue
            digest = hashlib.md5(payload).digest()
            result.setdefault(digest, set()).add(xref)
        return result

    @staticmethod
    def _match_image_info(
        block: dict,
        image_infos: list[dict],
        image_digest: bytes,
        source_image_xrefs: dict[bytes, set[int]] | None = None,
    ) -> dict:
        """Match metadata by exact PDF source bytes, geometry, and dimensions."""
        transform = tuple(block.get("transform") or ())
        width = block.get("width")
        height = block.get("height")
        geometry_candidates = [
            info for info in image_infos
            if tuple(info.get("transform") or ()) == transform
            and info.get("width") == width
            and info.get("height") == height
        ]
        source_digest = hashlib.md5(block["image"]).digest() if block.get("image") else None
        xrefs = (source_image_xrefs or {}).get(source_digest, set())
        candidates = [
            info for info in geometry_candidates
            if info.get("xref") in xrefs
        ]
        if not xrefs:
            candidates = [
                info for info in geometry_candidates
                if info.get("digest") == image_digest
            ]
        if not candidates:
            raise ValueError(
                f"image block {block.get('number')!r} exact identity maps to 0 image metadata entries"
            )
        reference = {
            key: value for key, value in candidates[0].items()
            if key != "number"
        }
        if any(
            {key: value for key, value in candidate.items() if key != "number"}
            != reference
            for candidate in candidates[1:]
        ):
            raise ValueError(
                f"image block {block.get('number')!r} exact identity has conflicting metadata"
            )
        return candidates[0]

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

        drawings = page.get_drawings(extended=True)

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
            seqno = drawing.get("seqno")
            opacity = drawing.get("stroke_opacity")
            if opacity is None:
                opacity = drawing.get("fill_opacity")
            raw_cap = drawing.get("lineCap")
            cap = list(raw_cap) if isinstance(raw_cap, tuple) else raw_cap
            join = drawing.get("lineJoin")
            dash = drawing.get("dashes")
            even_odd = drawing.get("even_odd")
            close_path = drawing.get("closePath")
            clip = _json_value(drawing.get("clip"))
            scissor = _json_value(drawing.get("scissor"))
            path_commands = [_json_value(item) for item in items]

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
                        seqno=seqno,
                        opacity=opacity,
                        blend=drawing.get("blend"),
                        cap=cap,
                        join=join,
                        dash=dash,
                        even_odd=even_odd,
                        close_path=close_path,
                        clip=clip,
                        scissor=scissor,
                        path_commands=path_commands,
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
                        seqno=seqno,
                        opacity=opacity,
                        blend=drawing.get("blend"),
                        cap=cap,
                        join=join,
                        dash=dash,
                        even_odd=even_odd,
                        close_path=close_path,
                        clip=clip,
                        scissor=scissor,
                        path_commands=path_commands,
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
                            seqno=seqno,
                            opacity=opacity,
                            blend=drawing.get("blend"),
                            cap=cap,
                            join=join,
                            dash=dash,
                            even_odd=even_odd,
                            close_path=close_path,
                            clip=clip,
                            scissor=scissor,
                            path_commands=path_commands,
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
                        seqno=seqno,
                        opacity=opacity,
                        blend=drawing.get("blend"),
                        cap=cap,
                        join=join,
                        dash=dash,
                        even_odd=even_odd,
                        close_path=close_path,
                        clip=clip,
                        scissor=scissor,
                        path_commands=path_commands,
                    ))
                    dec_idx += 1

        return decorations

    def extract_text_regions(self, page, text_traces: list[dict] | None = None) -> list[TextRegionBBox]:
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
        page_dict = page.get_text("rawdict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)

        for block_idx, block in enumerate(page_dict.get("blocks", [])):
            block_type = block.get("type")
            if block_type != 0:  # Only text blocks
                continue

            # Check if block has actual text content
            has_text = False
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if _span_text(span).strip():
                        has_text = True
                        break
                if has_text:
                    break

            if not has_text:
                continue

            text_regions.append(TextRegionBBox(
                id="",
                bbox=_round_bbox(block["bbox"]),
                # Generate a block_id referencing the layout text block
                block_ids=[f"p{page_index + 1:04d}_t{block_idx:04d}"],
                angle=_dominant_text_angle(block.get("lines", [])),
                lines=_text_lines(block.get("lines", []), text_traces or []),
            ))

        return [
            replace(region, id=f"p{page_index + 1:04d}_r{region_idx + 1:04d}")
            for region_idx, region in enumerate(_merge_flowing_text_regions(text_regions))
        ]

    def extract_display_list(
        self,
        page,
        page_index: int,
        *,
        images: list[ImageElement],
        decorations: list[DecorationElement],
        text_regions: list[TextRegionBBox],
    ) -> list[DisplayListObject]:
        """Extract the canonical paint order from PyMuPDF's bbox log.

        ``get_bboxlog`` deliberately exposes the PDF objects as an ordered log;
        unknown kinds are preserved and marked unsupported instead of being
        silently discarded.
        """
        entries = page.get_bboxlog(layers=True)

        supported = {
            "fill-text", "stroke-text", "ignore-text", "fill-path", "stroke-path",
            "fill-image", "stroke-image", "image", "fill-shade", "stroke-shade",
            "group-bbox",
        }
        objects: list[DisplayListObject] = []
        for seqno, entry in enumerate(entries):
            if not isinstance(entry, (tuple, list)) or len(entry) < 2:
                kind = "unknown"
                bbox = [0.0, 0.0, 0.0, 0.0]
                layer = None
            else:
                kind = str(entry[0])
                bbox = _round_bbox(entry[1])
                layer = entry[2] if len(entry) > 2 else None
            source_ref = self._display_source_ref(
                kind,
                bbox,
                seqno,
                images,
                decorations,
                text_regions,
            )
            objects.append(DisplayListObject(
                id=f"p{page_index + 1:04d}_dl{seqno + 1:04d}",
                kind=kind,
                bbox=bbox,
                transform=self._display_transform(kind, bbox, images),
                seqno=seqno,
                layer=layer or None,
                clip=None,
                opacity=None,
                blend=None,
                source_ref=source_ref,
                unsupported=kind not in supported,
            ))
        return objects

    @staticmethod
    def _display_transform(kind, bbox, images):
        if "image" in kind:
            for image in images:
                if image.transform and all(abs(float(a) - float(b)) <= 1.0 for a, b in zip(image.bbox, bbox)):
                    return image.transform
        # bboxlog does not expose other operator matrices. Keep unknown
        # transforms absent rather than fabricating a matrix.
        return None

    @staticmethod
    def _display_source_ref(
        kind,
        bbox,
        seqno,
        images,
        decorations,
        text_regions,
    ) -> str | None:
        if "text" in kind:
            for region in text_regions:
                if any(
                    span.seqno == seqno or seqno in span.seqnos
                    for line in region.lines
                    for span in line.spans
                ):
                    return region.id
            return None
        if "path" in kind:
            for decoration in decorations:
                if decoration.seqno == seqno:
                    return decoration.id
                if (
                    kind == "stroke-path"
                    and decoration.fill_color is not None
                    and decoration.stroke_color is not None
                    and decoration.seqno is not None
                    and decoration.seqno + 1 == seqno
                ):
                    return decoration.id
            return None
        if "image" in kind:
            candidates = images
        else:
            candidates = []
        for item in candidates:
            item_bbox = getattr(item, "bbox", None)
            if item_bbox and all(abs(float(a) - float(b)) <= 5.0 for a, b in zip(item_bbox, bbox)):
                return getattr(item, "id", None)
        return None


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
