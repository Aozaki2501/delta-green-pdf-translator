"""
Coordinate-level PDF layout model.

This model is intentionally strict and small. It stores the page geometry,
text spans, and image regions needed by the original-page replica pipeline.
"""

from dataclasses import asdict, dataclass
import json
from typing import Any


LAYOUT_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class LayoutSpan:
    id: str
    text: str
    bbox: list[float]
    font: str
    size: float
    color: str
    flags: int


@dataclass(frozen=True)
class LayoutTextBlock:
    id: str
    bbox: list[float]
    spans: list[LayoutSpan]
    translated_text: str | None = None


@dataclass(frozen=True)
class LayoutImageBlock:
    id: str
    bbox: list[float]


@dataclass(frozen=True)
class LayoutPage:
    index: int
    width: float
    height: float
    page_image_path: str
    text_blocks: list[LayoutTextBlock]
    image_blocks: list[LayoutImageBlock]


@dataclass(frozen=True)
class LayoutDocument:
    schema_version: int
    source_pdf: str
    page_count: int
    pages: list[LayoutPage]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def _require_keys(data: dict[str, Any], keys: tuple[str, ...], label: str):
    missing = [key for key in keys if key not in data]
    if missing:
        raise ValueError(f"{label} 缺少字段：{', '.join(missing)}")


def _number_list(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{label} 必须是 4 个数字")
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是 4 个数字") from exc


def layout_document_from_dict(data: dict[str, Any]) -> LayoutDocument:
    _require_keys(data, ("schema_version", "source_pdf", "page_count", "pages"), "layout")
    if int(data["schema_version"]) != LAYOUT_SCHEMA_VERSION:
        raise ValueError(f"不支持的 layout schema：{data['schema_version']}")

    pages = []
    for page_data in data["pages"]:
        _require_keys(
            page_data,
            ("index", "width", "height", "page_image_path", "text_blocks", "image_blocks"),
            "page",
        )
        text_blocks = []
        for block_data in page_data["text_blocks"]:
            _require_keys(block_data, ("id", "bbox", "spans"), "text block")
            spans = []
            for span_data in block_data["spans"]:
                _require_keys(span_data, ("id", "text", "bbox", "font", "size", "color", "flags"), "span")
                spans.append(LayoutSpan(
                    id=str(span_data["id"]),
                    text=str(span_data["text"]),
                    bbox=_number_list(span_data["bbox"], "span.bbox"),
                    font=str(span_data["font"]),
                    size=float(span_data["size"]),
                    color=str(span_data["color"]),
                    flags=int(span_data["flags"]),
                ))
            text_blocks.append(LayoutTextBlock(
                id=str(block_data["id"]),
                bbox=_number_list(block_data["bbox"], "text_block.bbox"),
                spans=spans,
                translated_text=(
                    None
                    if block_data.get("translated_text") is None
                    else str(block_data["translated_text"])
                ),
            ))

        image_blocks = []
        for image_data in page_data["image_blocks"]:
            _require_keys(image_data, ("id", "bbox"), "image block")
            image_blocks.append(LayoutImageBlock(
                id=str(image_data["id"]),
                bbox=_number_list(image_data["bbox"], "image_block.bbox"),
            ))

        pages.append(LayoutPage(
            index=int(page_data["index"]),
            width=float(page_data["width"]),
            height=float(page_data["height"]),
            page_image_path=str(page_data["page_image_path"]),
            text_blocks=text_blocks,
            image_blocks=image_blocks,
        ))

    page_count = int(data["page_count"])
    if page_count != len(pages):
        raise ValueError("page_count 与 pages 数量不一致")

    return LayoutDocument(
        schema_version=LAYOUT_SCHEMA_VERSION,
        source_pdf=str(data["source_pdf"]),
        page_count=page_count,
        pages=pages,
    )


def layout_document_from_json(text: str) -> LayoutDocument:
    return layout_document_from_dict(json.loads(text))
