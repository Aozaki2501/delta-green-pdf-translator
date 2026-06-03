"""
Typeset reflow data models.

Data models for the typeset reflow pipeline, including page structure,
page content, configuration, and result types. All dataclasses use
frozen=True for immutability.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Schema version constants
# ---------------------------------------------------------------------------

PAGE_STRUCTURE_SCHEMA_VERSION = 1
PAGE_CONTENT_SCHEMA_VERSION = 1


# ===========================================================================
# Page Structure models (page_structure.json)
# ===========================================================================


@dataclass(frozen=True)
class BackgroundLayer:
    """页面背景层。"""

    color: str | None = None       # CSS 颜色值，如 "#1a1a2e" 或 None（白色）
    gradient: str | None = None    # CSS 渐变值，如 "linear-gradient(...)" 或 None


@dataclass(frozen=True)
class ImageElement:
    """独立图片元素。"""

    id: str                    # 如 "p0001_img0001"
    bbox: list[float]          # [x0, y0, x1, y1] PDF 点坐标
    image_path: str            # 相对路径，如 "assets/typeset_images/p0001_img0001.png"
    width_px: int              # 图片像素宽度
    height_px: int             # 图片像素高度
    transform: list[float] | None = None


@dataclass(frozen=True)
class DecorationElement:
    """矢量装饰元素（线条、框）。"""

    id: str                        # 如 "p0001_dec0001"
    element_type: str              # "line" | "rect" | "path"
    bbox: list[float]              # [x0, y0, x1, y1]
    stroke_color: str | None       # CSS 颜色值
    fill_color: str | None         # CSS 颜色值
    stroke_width: float            # 线宽（PDF 点）
    points: list[list[float]] | None = None  # 路径点（仅 path 类型）


@dataclass(frozen=True)
class TextSpanBBox:
    """A source text span with geometry and style."""

    bbox: list[float]
    text: str
    font_size: float
    bold: bool
    italic: bool
    color: str


@dataclass(frozen=True)
class TextLineBBox:
    """A source text line with geometry and dominant style."""

    bbox: list[float]
    text: str
    font_size: float
    bold: bool
    italic: bool
    color: str
    angle: float = 0.0
    spans: list[TextSpanBBox] = field(default_factory=list)


@dataclass(frozen=True)
class TextRegionBBox:
    """文本区域边界框。"""

    id: str                    # 如 "p0001_r0001"
    bbox: list[float]          # [x0, y0, x1, y1]
    block_ids: list[str]       # 对应的 layout.json 文本块 ID 列表
    angle: float = 0.0
    lines: list[TextLineBBox] = field(default_factory=list)


@dataclass(frozen=True)
class PageStructure:
    """单页结构。"""

    page_index: int
    width: float               # 页面宽度（PDF 点）
    height: float              # 页面高度（PDF 点）
    background: BackgroundLayer
    images: list[ImageElement]
    decorations: list[DecorationElement]
    text_regions: list[TextRegionBBox]


@dataclass(frozen=True)
class PageStructureDocument:
    """整个文档的页面结构。"""

    schema_version: int
    source_pdf: str
    page_count: int
    pages: list[PageStructure]

    def to_json(self) -> str:
        """Serialize to JSON string (UTF-8, indented, human-readable)."""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> PageStructureDocument:
        """Deserialize from JSON string with schema version validation."""
        data = json.loads(text)
        version = data.get("schema_version")
        if version != PAGE_STRUCTURE_SCHEMA_VERSION:
            raise ValueError(
                f"不兼容的 page_structure schema 版本：期望 "
                f"{PAGE_STRUCTURE_SCHEMA_VERSION}，实际 {version}"
            )
        return _page_structure_document_from_dict(data)


# ===========================================================================
# Page Content models (page_content.json)
# ===========================================================================


class SemanticRole(Enum):
    """文本区域语义角色。"""

    BODY_COLUMN = "body_column"
    TITLE = "title"
    SUBTITLE = "subtitle"
    HEADER = "header"
    FOOTER = "footer"
    FOOTNOTE = "footnote"
    TABLE = "table"
    LIST = "list"


class PageType(Enum):
    """页面类型。"""

    COVER = "cover"
    ART = "art"
    COLUMNS = "columns"
    SINGLE = "single"
    MIXED = "mixed"


@dataclass(frozen=True)
class StyledTextRun:
    """带样式的文本片段。"""

    text: str
    font_size: float           # pt
    bold: bool
    italic: bool
    color: str                 # CSS 颜色值


@dataclass(frozen=True)
class ContentBlock:
    """语义化的内容块。"""

    id: str                        # 如 "p0001_r0001_b0001"
    region_id: str                 # 对应 TextRegionBBox.id
    role: SemanticRole
    runs: list[StyledTextRun]      # 原文带样式文本
    source_text: str               # 纯文本（用于翻译）
    translated_text: str | None    # 翻译后的文本
    translatable: bool             # 是否需要翻译


@dataclass(frozen=True)
class ColumnInfo:
    """栏信息。"""

    side: str                  # "left" | "right"
    bbox: list[float]          # 栏的边界框
    block_ids: list[str]       # 属于该栏的 ContentBlock ID 列表


@dataclass(frozen=True)
class PageContent:
    """单页语义化内容。"""

    page_index: int
    page_type: PageType
    columns: list[ColumnInfo]      # 双栏页面的栏信息，非双栏为空
    blocks: list[ContentBlock]


@dataclass(frozen=True)
class PageContentDocument:
    """整个文档的语义化内容。"""

    schema_version: int
    source_pdf: str
    page_count: int
    pages: list[PageContent]

    def to_json(self) -> str:
        """Serialize to JSON string (UTF-8, indented, human-readable)."""
        data = _page_content_document_to_dict(self)
        return json.dumps(data, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> PageContentDocument:
        """Deserialize from JSON string with schema version validation."""
        data = json.loads(text)
        version = data.get("schema_version")
        if version != PAGE_CONTENT_SCHEMA_VERSION:
            raise ValueError(
                f"不兼容的 page_content schema 版本：期望 "
                f"{PAGE_CONTENT_SCHEMA_VERSION}，实际 {version}"
            )
        return _page_content_document_from_dict(data)


# ===========================================================================
# Configuration and Result models
# ===========================================================================


@dataclass
class TypesetConfig:
    """纯重绘管线配置。"""

    font_family: str = "FandolSong"
    fallback_fonts: list[str] = field(default_factory=lambda: ["FandolSong-Regular", "Noto Serif SC", "Source Han Serif CN", "SimSun", "serif"])
    heading_font_family: str = "FZZJ-MSMLJW"
    heading_fallback_fonts: list[str] = field(default_factory=lambda: ["FandolHei", "Noto Serif CJK SC", "SimHei", "sans-serif"])
    body_font_size_pt: float = 10.9
    min_body_font_size_pt: float = 8.0
    line_height: float = 1.6
    column_gap_pt: float = 30.0
    text_indent: str = "2em"
    title_color: str = "#000000"
    subtitle_color: str = "#ed1c24"
    body_color: str = "#111111"
    translation_concurrency: int = 4
    layout_hints_path: str | None = None


@dataclass
class TypesetResult:
    """管线执行结果。"""

    pdf_path: str | None = None
    html_path: str | None = None
    page_structure_path: str = ""
    page_content_path: str = ""
    total_pages: int = 0
    translated_regions: int = 0
    failed_regions: int = 0
    export_errors: list[str] = field(default_factory=list)


# ===========================================================================
# Internal serialization helpers
# ===========================================================================


def _page_structure_document_from_dict(data: dict[str, Any]) -> PageStructureDocument:
    """Reconstruct a PageStructureDocument from a plain dict."""
    pages: list[PageStructure] = []
    for p in data["pages"]:
        background = BackgroundLayer(
            color=p["background"].get("color"),
            gradient=p["background"].get("gradient"),
        )
        images = [
            ImageElement(
                id=img["id"],
                bbox=img["bbox"],
                image_path=img["image_path"],
                width_px=img["width_px"],
                height_px=img["height_px"],
                transform=img.get("transform"),
            )
            for img in p["images"]
        ]
        decorations = [
            DecorationElement(
                id=dec["id"],
                element_type=dec["element_type"],
                bbox=dec["bbox"],
                stroke_color=dec.get("stroke_color"),
                fill_color=dec.get("fill_color"),
                stroke_width=dec["stroke_width"],
                points=dec.get("points"),
            )
            for dec in p["decorations"]
        ]
        text_regions = [
            TextRegionBBox(
                id=tr["id"],
                bbox=tr["bbox"],
                block_ids=tr["block_ids"],
                angle=float(tr.get("angle", 0.0)),
                lines=[
                    TextLineBBox(
                        bbox=line["bbox"],
                        text=line.get("text", ""),
                        font_size=float(line.get("font_size", 11.0)),
                        bold=bool(line.get("bold", False)),
                        italic=bool(line.get("italic", False)),
                        color=line.get("color", "#000000"),
                        angle=float(line.get("angle", 0.0)),
                        spans=[
                            TextSpanBBox(
                                bbox=span["bbox"],
                                text=span.get("text", ""),
                                font_size=float(span.get("font_size", line.get("font_size", 11.0))),
                                bold=bool(span.get("bold", line.get("bold", False))),
                                italic=bool(span.get("italic", line.get("italic", False))),
                                color=span.get("color", line.get("color", "#000000")),
                            )
                            for span in line.get("spans", [])
                        ],
                    )
                    for line in tr.get("lines", [])
                ],
            )
            for tr in p["text_regions"]
        ]
        pages.append(
            PageStructure(
                page_index=p["page_index"],
                width=p["width"],
                height=p["height"],
                background=background,
                images=images,
                decorations=decorations,
                text_regions=text_regions,
            )
        )
    return PageStructureDocument(
        schema_version=data["schema_version"],
        source_pdf=data["source_pdf"],
        page_count=data["page_count"],
        pages=pages,
    )


def _page_content_document_to_dict(doc: PageContentDocument) -> dict[str, Any]:
    """Convert a PageContentDocument to a plain dict for JSON serialization."""
    pages = []
    for page in doc.pages:
        blocks = []
        for block in page.blocks:
            runs = [
                {
                    "text": run.text,
                    "font_size": run.font_size,
                    "bold": run.bold,
                    "italic": run.italic,
                    "color": run.color,
                }
                for run in block.runs
            ]
            blocks.append(
                {
                    "id": block.id,
                    "region_id": block.region_id,
                    "role": block.role.value,
                    "runs": runs,
                    "source_text": block.source_text,
                    "translated_text": block.translated_text,
                    "translatable": block.translatable,
                }
            )
        columns = [
            {
                "side": col.side,
                "bbox": col.bbox,
                "block_ids": col.block_ids,
            }
            for col in page.columns
        ]
        pages.append(
            {
                "page_index": page.page_index,
                "page_type": page.page_type.value,
                "columns": columns,
                "blocks": blocks,
            }
        )
    return {
        "schema_version": doc.schema_version,
        "source_pdf": doc.source_pdf,
        "page_count": doc.page_count,
        "pages": pages,
    }


def _page_content_document_from_dict(data: dict[str, Any]) -> PageContentDocument:
    """Reconstruct a PageContentDocument from a plain dict."""
    pages: list[PageContent] = []
    for p in data["pages"]:
        blocks: list[ContentBlock] = []
        for b in p["blocks"]:
            runs = [
                StyledTextRun(
                    text=r["text"],
                    font_size=r["font_size"],
                    bold=r["bold"],
                    italic=r["italic"],
                    color=r["color"],
                )
                for r in b["runs"]
            ]
            blocks.append(
                ContentBlock(
                    id=b["id"],
                    region_id=b["region_id"],
                    role=SemanticRole(b["role"]),
                    runs=runs,
                    source_text=b["source_text"],
                    translated_text=b.get("translated_text"),
                    translatable=b["translatable"],
                )
            )
        columns = [
            ColumnInfo(
                side=c["side"],
                bbox=c["bbox"],
                block_ids=c["block_ids"],
            )
            for c in p["columns"]
        ]
        pages.append(
            PageContent(
                page_index=p["page_index"],
                page_type=PageType(p["page_type"]),
                columns=columns,
                blocks=blocks,
            )
        )
    return PageContentDocument(
        schema_version=data["schema_version"],
        source_pdf=data["source_pdf"],
        page_count=data["page_count"],
        pages=pages,
    )
