"""
Coordinate-level layout extraction.

This extractor keeps original page coordinates instead of turning the PDF into
reading-order prose. It is the first stage of the original-page PDF pipeline.
"""

from pathlib import Path

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        raise ImportError("PyMuPDF not installed. Run: pip install pymupdf")

from core.layout_model import (
    LAYOUT_SCHEMA_VERSION,
    LayoutDocument,
    LayoutImageBlock,
    LayoutPage,
    LayoutSpan,
    LayoutTextBlock,
)
from core.utils import ensure_output_parent


def _round_bbox(bbox) -> list[float]:
    return [round(float(value), 3) for value in bbox]


def _color_to_hex(value: int) -> str:
    rgb = int(value) & 0xFFFFFF
    return f"#{rgb:06X}"


class PDFLayoutExtractor:
    """Extract strict coordinate-level page layout from a PDF."""

    def __init__(self, pdf_path: str):
        self.pdf_path = str(pdf_path)
        self.doc = pymupdf.open(pdf_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        self.doc.close()

    def extract(self, start_page: int = 0, end_page: int | None = None) -> LayoutDocument:
        total = len(self.doc)
        if end_page is None:
            end_page = total
        if start_page < 0 or start_page >= total:
            raise ValueError(f"起始页超出范围：PDF 共 {total} 页")
        if end_page <= start_page:
            raise ValueError("结束页必须大于起始页")
        if end_page > total:
            end_page = total

        pages = [self._extract_page(page_index) for page_index in range(start_page, end_page)]
        return LayoutDocument(
            schema_version=LAYOUT_SCHEMA_VERSION,
            source_pdf=str(Path(self.pdf_path).name),
            page_count=len(pages),
            pages=pages,
        )

    def _extract_page(self, page_index: int) -> LayoutPage:
        page = self.doc[page_index]
        page_dict = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
        text_blocks = []
        image_blocks = []
        text_idx = 0
        image_idx = 0

        for block in page_dict.get("blocks", []):
            block_type = block.get("type")
            if block_type == 0:
                spans = self._extract_spans(page_index, text_idx, block)
                if spans:
                    text_blocks.append(LayoutTextBlock(
                        id=f"p{page_index + 1:04d}_t{text_idx:04d}",
                        bbox=_round_bbox(block["bbox"]),
                        spans=spans,
                    ))
                    text_idx += 1
            elif block_type == 1:
                image_blocks.append(LayoutImageBlock(
                    id=f"p{page_index + 1:04d}_i{image_idx:04d}",
                    bbox=_round_bbox(block["bbox"]),
                ))
                image_idx += 1

        return LayoutPage(
            index=page_index,
            width=round(float(page.rect.width), 3),
            height=round(float(page.rect.height), 3),
            text_blocks=text_blocks,
            image_blocks=image_blocks,
        )

    def _extract_spans(self, page_index: int, block_index: int, block: dict) -> list[LayoutSpan]:
        spans = []
        span_idx = 0
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span.get("text", ""))
                if not text:
                    continue
                spans.append(LayoutSpan(
                    id=f"p{page_index + 1:04d}_t{block_index:04d}_s{span_idx:04d}",
                    text=text,
                    bbox=_round_bbox(span.get("bbox", line.get("bbox", block["bbox"]))),
                    font=str(span.get("font", "")),
                    size=round(float(span.get("size", 0)), 3),
                    color=_color_to_hex(span.get("color", 0)),
                    flags=int(span.get("flags", 0)),
                ))
                span_idx += 1
        return spans


def extract_layout_to_file(pdf_path: str, output_path: str,
                           start_page: int = 0, end_page: int | None = None) -> LayoutDocument:
    ensure_output_parent(output_path)
    with PDFLayoutExtractor(pdf_path) as extractor:
        layout = extractor.extract(start_page=start_page, end_page=end_page)
    Path(output_path).write_text(layout.to_json(), encoding="utf-8")
    return layout
