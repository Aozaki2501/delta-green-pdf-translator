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

PAGE_STRUCTURE_SCHEMA_VERSION = 2
PAGE_CONTENT_SCHEMA_VERSION = 2


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
    xref: int | None = None
    digest: str | None = None
    bpc: int | None = None
    colorspace: str | int | None = None
    xres: float | None = None
    yres: float | None = None
    has_mask: bool = False


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
    seqno: int | None = None
    opacity: float | None = None
    blend: str | None = None
    cap: list[int] | int | None = None
    join: float | int | None = None
    dash: str | None = None
    even_odd: bool | None = None
    close_path: bool | None = None
    clip: list[float] | None = None
    scissor: list[float] | None = None
    path_commands: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class TextSpanBBox:
    """A source text span with geometry and style."""

    bbox: list[float]
    text: str
    font_size: float
    bold: bool
    italic: bool
    color: str
    font: str | None = None
    origin: list[float] | None = None
    alpha: float | int | None = None
    ascender: float | None = None
    descender: float | None = None
    chars: list[dict[str, Any]] = field(default_factory=list)
    seqno: int | None = None
    seqnos: list[int] = field(default_factory=list)

    @property
    def char_geometry(self) -> list[dict[str, Any]]:
        return self.chars


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
class DisplayListObject:
    """Strict canonical display-list object preserving PDF paint order."""

    id: str
    kind: str
    bbox: list[float]
    transform: list[float] | None = None
    seqno: int | None = None
    layer: str | None = None
    clip: list[float] | None = None
    opacity: float | None = None
    blend: str | None = None
    source_ref: str | None = None
    unsupported: bool = False


@dataclass(frozen=True)
class VisualAnchor:
    """Optional link from an extracted visual asset to a semantic region."""

    id: str
    page_index: int
    asset_id: str
    anchor_region_id: str | None = None
    placement: Any = None
    order: int = 0
    role: str | None = None
    ambiguous: bool = False


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
    media_box: list[float] = field(default_factory=list)
    crop_box: list[float] = field(default_factory=list)
    rotation: int = 0
    user_unit: float = 1.0
    display_list: list[DisplayListObject] = field(default_factory=list)
    visual_anchors: list[VisualAnchor] = field(default_factory=list)


@dataclass(frozen=True)
class PageStructureDocument:
    """整个文档的页面结构。"""

    schema_version: int
    source_pdf: str
    page_count: int
    pages: list[PageStructure]
    source_sha256: str = ""
    visual_anchors: list[VisualAnchor] = field(default_factory=list)

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


# Canonical-schema names used by integrations that do not depend on the
# historical ``PageStructure``/``DisplayListObject`` names.
Page = PageStructure
DisplayObject = DisplayListObject


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


class FontRole(Enum):
    """稳定的中文排版字体角色。"""

    BODY = "body"
    DISPLAY = "display"
    SECTION = "section"
    SUBSECTION = "subsection"
    RUNNING_HEADER = "running_header"
    FOOTER = "footer"
    TABLE = "table"
    CALLOUT = "callout"
    META = "meta"


@dataclass(frozen=True)
class StyledTextRun:
    """带样式的文本片段。"""

    text: str
    font_size: float           # pt
    bold: bool
    italic: bool
    color: str                 # CSS 颜色值
    font: str | None = None
    bbox: list[float] | None = None
    line_index: int | None = None
    baseline: float | None = None


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
    bbox: list[float] | None = None
    line_ids: list[str] = field(default_factory=list)
    paragraph_id: str | None = None
    font_role: FontRole = FontRole.BODY
    source_font: str | None = None
    column_id: str | None = None
    order: int = 0
    layout_mode: str = "paragraph"
    first_line_indent_pt: float = 0.0
    line_height_pt: float | None = None


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
    source_sha256: str = ""

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

    profile_id: str = "delta_green"
    source_language: str = "English"
    document_title: str | None = None
    font_family: str = "DG Fandol Song"
    fallback_fonts: list[str] = field(default_factory=lambda: ["Noto Serif SC", "Source Han Serif CN", "SimSun", "serif"])
    heading_font_family: str = "DG Lanting Kanhei"
    heading_fallback_fonts: list[str] = field(default_factory=lambda: ["Noto Sans SC", "Source Han Sans CN", "SimHei", "sans-serif"])
    body_font_size_pt: float = 10.9
    min_body_font_size_pt: float = 10.5
    line_height: float = 17.0 / 10.9
    column_gap_pt: float = 31.0
    text_indent: str = "2em"
    title_color: str = "#231f20"
    subtitle_color: str = "#dc2527"
    accent_heading_colors: tuple[str, ...] = ("#ed1c24", "#dc2527", "#eb4f24")
    body_color: str = "#231f20"
    display_font_size_pt: float = 30.0
    section_font_size_pt: float = 20.0
    accent_font_size_pt: float = 15.0
    subsection_font_size_pt: float = 13.0
    running_header_font_size_pt: float = 11.0
    table_font_size_pt: float = 9.0
    embedded_font_dir: str = "assets/typeset_fonts"
    translation_concurrency: int = 4
    layout_hints_path: str | None = None
    reading_html_href: str | None = None


@dataclass
class TypesetResult:
    """管线执行结果。"""

    pdf_path: str | None = None
    html_path: str | None = None
    reading_html_path: str | None = None
    page_structure_path: str = ""
    page_content_path: str = ""
    total_pages: int = 0
    translated_regions: int = 0
    failed_regions: int = 0
    export_errors: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0
    failed_calls: int = 0
    translation_cache_hits: int = 0
    cost_usd: float | None = None


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
                xref=img.get("xref"),
                digest=img.get("digest"),
                bpc=img.get("bpc"),
                colorspace=img.get("colorspace"),
                xres=img.get("xres"),
                yres=img.get("yres"),
                has_mask=bool(img.get("has_mask", False)),
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
                seqno=dec.get("seqno"),
                opacity=dec.get("opacity"),
                blend=dec.get("blend"),
                cap=dec.get("cap"),
                join=dec.get("join"),
                dash=dec.get("dash"),
                even_odd=dec.get("even_odd"),
                close_path=dec.get("close_path"),
                clip=dec.get("clip"),
                scissor=dec.get("scissor"),
                path_commands=dec.get("path_commands", []),
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
                                font=span.get("font"),
                                origin=span.get("origin"),
                                alpha=span.get("alpha"),
                                ascender=span.get("ascender"),
                                descender=span.get("descender"),
                                chars=span.get("chars", span.get("char_geometry", [])),
                                seqno=span.get("seqno"),
                                seqnos=span.get("seqnos", []),
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
                media_box=p.get("media_box", []),
                crop_box=p.get("crop_box", []),
                rotation=int(p.get("rotation", 0)),
                user_unit=float(p.get("user_unit", 1.0)),
                display_list=[
                    DisplayListObject(
                        id=obj["id"],
                        kind=obj["kind"],
                        bbox=obj.get("bbox", [0.0, 0.0, 0.0, 0.0]),
                        transform=obj.get("transform"),
                        seqno=obj.get("seqno"),
                        layer=obj.get("layer"),
                        clip=obj.get("clip"),
                        opacity=obj.get("opacity"),
                        blend=obj.get("blend"),
                        source_ref=obj.get("source_ref"),
                        unsupported=bool(obj.get("unsupported", False)),
                    )
                    for obj in p.get("display_list", [])
                ],
                visual_anchors=[
                    VisualAnchor(
                        id=anchor["id"],
                        page_index=int(anchor.get("page_index", p["page_index"])),
                        asset_id=anchor.get("asset_id", ""),
                        anchor_region_id=anchor.get("anchor_region_id"),
                        placement=anchor.get("placement"),
                        order=int(anchor.get("order", 0)),
                        role=anchor.get("role"),
                        ambiguous=bool(anchor.get("ambiguous", False)),
                    )
                    for anchor in p.get("visual_anchors", [])
                ],
            )
        )
    return PageStructureDocument(
        schema_version=data["schema_version"],
        source_pdf=data["source_pdf"],
        page_count=data["page_count"],
        pages=pages,
        source_sha256=data.get("source_sha256", ""),
        visual_anchors=[
            VisualAnchor(
                id=anchor["id"],
                page_index=int(anchor.get("page_index", 0)),
                asset_id=anchor.get("asset_id", ""),
                anchor_region_id=anchor.get("anchor_region_id"),
                placement=anchor.get("placement"),
                order=int(anchor.get("order", 0)),
                role=anchor.get("role"),
                ambiguous=bool(anchor.get("ambiguous", False)),
            )
            for anchor in data.get("visual_anchors", [])
        ],
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
                    "font": run.font,
                    "bbox": run.bbox,
                    "line_index": run.line_index,
                    "baseline": run.baseline,
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
                    "bbox": block.bbox,
                    "line_ids": block.line_ids,
                    "paragraph_id": block.paragraph_id,
                    "font_role": block.font_role.value,
                    "source_font": block.source_font,
                    "column_id": block.column_id,
                    "order": block.order,
                    "layout_mode": block.layout_mode,
                    "first_line_indent_pt": block.first_line_indent_pt,
                    "line_height_pt": block.line_height_pt,
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
        "source_sha256": doc.source_sha256,
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
                    font=r.get("font"),
                    bbox=r.get("bbox"),
                    line_index=r.get("line_index"),
                    baseline=r.get("baseline"),
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
                    bbox=b.get("bbox"),
                    line_ids=b.get("line_ids", []),
                    paragraph_id=b.get("paragraph_id"),
                    font_role=FontRole(b.get("font_role", FontRole.BODY.value)),
                    source_font=b.get("source_font"),
                    column_id=b.get("column_id"),
                    order=int(b.get("order", 0)),
                    layout_mode=b.get("layout_mode", "paragraph"),
                    first_line_indent_pt=float(b.get("first_line_indent_pt", 0.0)),
                    line_height_pt=(
                        float(b["line_height_pt"])
                        if b.get("line_height_pt") is not None
                        else None
                    ),
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
        source_sha256=data.get("source_sha256", ""),
    )
