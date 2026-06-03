"""Validated layout hints for PDF typeset rendering.

This module defines the small JSON contract used between automatic rules,
multimodal review, and the local renderer. It only records semantic choices;
PDF geometry still comes from PyMuPDF extraction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from core.typeset_models import PageContentDocument, PageStructureDocument, PageType
from core.typeset_models import ColumnInfo, ContentBlock, PageContent


LAYOUT_HINTS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SkipBlockHint:
    id: str
    reason: str


@dataclass(frozen=True)
class ColumnHint:
    id: str
    blocks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SpecialRegionHint:
    type: str
    blocks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PageHint:
    page_index: int
    page_type: str | None = None
    reading_order: list[str] = field(default_factory=list)
    skip_blocks: list[SkipBlockHint] = field(default_factory=list)
    columns: list[ColumnHint] = field(default_factory=list)
    special_regions: list[SpecialRegionHint] = field(default_factory=list)

    def referenced_block_ids(self) -> set[str]:
        ids = set(self.reading_order)
        ids.update(item.id for item in self.skip_blocks)
        for column in self.columns:
            ids.update(column.blocks)
        for region in self.special_regions:
            ids.update(region.blocks)
        return ids


@dataclass(frozen=True)
class LayoutHints:
    schema_version: int
    source_pdf: str | None
    pages: dict[int, PageHint]

    @classmethod
    def from_file(cls, path: str | Path) -> "LayoutHints":
        hints_path = Path(path)
        return cls.from_json(hints_path.read_text(encoding="utf-8"))

    @classmethod
    def from_json(cls, text: str) -> "LayoutHints":
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("layout_hints 必须是 JSON object")

        version = data.get("schema_version")
        if version != LAYOUT_HINTS_SCHEMA_VERSION:
            raise ValueError(
                f"不兼容的 layout_hints schema 版本：期望 "
                f"{LAYOUT_HINTS_SCHEMA_VERSION}，实际 {version}"
            )

        pages_data = data.get("pages", {})
        if not isinstance(pages_data, dict):
            raise ValueError("layout_hints.pages 必须是 object")

        pages: dict[int, PageHint] = {}
        for raw_page_index, raw_hint in pages_data.items():
            page_index = _parse_page_index(raw_page_index)
            pages[page_index] = _parse_page_hint(page_index, raw_hint)

        source_pdf = data.get("source_pdf")
        if source_pdf is not None and not isinstance(source_pdf, str):
            raise ValueError("layout_hints.source_pdf 必须是 string 或 null")

        return cls(
            schema_version=version,
            source_pdf=source_pdf,
            pages=pages,
        )

    def get_page_hint(self, page_index: int) -> PageHint | None:
        return self.pages.get(page_index)

    def validate_page_block_ids(
        self,
        page_block_ids: Mapping[int, Iterable[str]],
    ) -> None:
        errors: list[str] = []
        normalized = {
            int(page_index): set(block_ids)
            for page_index, block_ids in page_block_ids.items()
        }

        for page_index, page_hint in sorted(self.pages.items()):
            if page_index not in normalized:
                errors.append(f"第 {page_index} 页不存在于目标文档")
                continue
            existing_ids = normalized[page_index]
            missing = sorted(page_hint.referenced_block_ids() - existing_ids)
            if missing:
                preview = ", ".join(missing[:10])
                errors.append(f"第 {page_index} 页引用了不存在的 block id：{preview}")

        if errors:
            raise ValueError("layout_hints 校验失败：" + "；".join(errors))

    def validate_against_content(self, content: PageContentDocument) -> None:
        self.validate_page_block_ids(block_ids_by_page_from_content(content))

    def validate_against_structure(self, structure: PageStructureDocument) -> None:
        self.validate_page_block_ids(block_ids_by_page_from_structure(structure))


def block_ids_by_page_from_content(
    content: PageContentDocument,
) -> dict[int, set[str]]:
    return {
        page.page_index: {block.id for block in page.blocks}
        for page in content.pages
    }


def block_ids_by_page_from_structure(
    structure: PageStructureDocument,
) -> dict[int, set[str]]:
    result: dict[int, set[str]] = {}
    for page in structure.pages:
        ids: set[str] = set()
        for region in page.text_regions:
            ids.add(region.id)
            ids.update(region.block_ids)
        result[page.page_index] = ids
    return result


def apply_hints_to_content(
    content: PageContentDocument,
    hints: LayoutHints,
    structure: PageStructureDocument,
) -> PageContentDocument:
    """Return page content with validated layout hints applied."""
    hints.validate_against_content(content)
    region_bboxes = _region_bboxes_by_page(structure)

    pages: list[PageContent] = []
    for page in content.pages:
        page_hint = hints.get_page_hint(page.page_index)
        if page_hint is None:
            pages.append(page)
            continue

        page_type = PageType(page_hint.page_type) if page_hint.page_type else page.page_type
        skip_ids = {item.id for item in page_hint.skip_blocks}
        blocks = [_apply_block_hint(block, skip_ids) for block in page.blocks]

        if page_hint.reading_order:
            blocks = _order_blocks(blocks, page_hint.reading_order)

        columns = page.columns
        if page_hint.columns:
            page_region_bboxes = region_bboxes.get(page.page_index, {})
            columns = _build_hint_columns(page_hint, blocks, page_region_bboxes)

        pages.append(PageContent(
            page_index=page.page_index,
            page_type=page_type,
            columns=columns,
            blocks=blocks,
        ))

    return PageContentDocument(
        schema_version=content.schema_version,
        source_pdf=content.source_pdf,
        page_count=content.page_count,
        pages=pages,
    )


def _parse_page_index(value) -> int:
    if isinstance(value, int):
        page_index = value
    elif isinstance(value, str) and value.isdigit():
        page_index = int(value)
    else:
        raise ValueError(f"layout_hints.pages 页码键必须是非负整数字符串：{value!r}")
    if page_index < 0:
        raise ValueError(f"layout_hints.pages 页码不能为负数：{page_index}")
    return page_index


def _parse_page_hint(page_index: int, value) -> PageHint:
    if not isinstance(value, dict):
        raise ValueError(f"layout_hints.pages.{page_index} 必须是 object")

    page_type = value.get("page_type")
    if page_type is not None:
        if not isinstance(page_type, str):
            raise ValueError(f"layout_hints.pages.{page_index}.page_type 必须是 string")
        allowed = {item.value for item in PageType}
        if page_type not in allowed:
            raise ValueError(
                f"layout_hints.pages.{page_index}.page_type 无效：{page_type}"
            )

    return PageHint(
        page_index=page_index,
        page_type=page_type,
        reading_order=_parse_string_list(
            value.get("reading_order", []),
            f"layout_hints.pages.{page_index}.reading_order",
        ),
        skip_blocks=_parse_skip_blocks(
            value.get("skip_blocks", []),
            f"layout_hints.pages.{page_index}.skip_blocks",
        ),
        columns=_parse_columns(
            value.get("columns", []),
            f"layout_hints.pages.{page_index}.columns",
        ),
        special_regions=_parse_special_regions(
            value.get("special_regions", []),
            f"layout_hints.pages.{page_index}.special_regions",
        ),
    )


def _parse_string_list(value, path: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{path} 必须是 array")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ValueError(f"{path}[{index}] 必须是非空 string")
        result.append(item)
    return result


def _apply_block_hint(block: ContentBlock, skip_ids: set[str]) -> ContentBlock:
    if block.id not in skip_ids:
        return block
    return ContentBlock(
        id=block.id,
        region_id=block.region_id,
        role=block.role,
        runs=block.runs,
        source_text=block.source_text,
        translated_text=block.translated_text,
        translatable=False,
    )


def _order_blocks(blocks: list[ContentBlock], reading_order: list[str]) -> list[ContentBlock]:
    block_by_id = {block.id: block for block in blocks}
    ordered: list[ContentBlock] = []
    seen: set[str] = set()
    for block_id in reading_order:
        block = block_by_id[block_id]
        ordered.append(block)
        seen.add(block_id)
    ordered.extend(block for block in blocks if block.id not in seen)
    return ordered


def _build_hint_columns(
    page_hint: PageHint,
    blocks: list[ContentBlock],
    region_bboxes: dict[str, list[float]],
) -> list[ColumnInfo]:
    block_by_id = {block.id: block for block in blocks}
    columns: list[ColumnInfo] = []
    for column in page_hint.columns:
        bboxes: list[list[float]] = []
        for block_id in column.blocks:
            region_id = block_by_id[block_id].region_id
            bbox = region_bboxes.get(region_id)
            if bbox is None:
                raise ValueError(f"layout_hints 引用了无坐标的 block id：{block_id}")
            bboxes.append(bbox)
        columns.append(ColumnInfo(
            side=column.id,
            bbox=_union_bbox(bboxes),
            block_ids=list(column.blocks),
        ))
    return columns


def _region_bboxes_by_page(
    structure: PageStructureDocument,
) -> dict[int, dict[str, list[float]]]:
    return {
        page.page_index: {region.id: region.bbox for region in page.text_regions}
        for page in structure.pages
    }


def _union_bbox(bboxes: list[list[float]]) -> list[float]:
    if not bboxes:
        raise ValueError("layout_hints.columns.blocks 不能为空")
    return [
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    ]


def _parse_skip_blocks(value, path: str) -> list[SkipBlockHint]:
    if not isinstance(value, list):
        raise ValueError(f"{path} 必须是 array")
    result: list[SkipBlockHint] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{path}[{index}] 必须是 object")
        block_id = item.get("id")
        reason = item.get("reason")
        if not isinstance(block_id, str) or not block_id:
            raise ValueError(f"{path}[{index}].id 必须是非空 string")
        if not isinstance(reason, str) or not reason:
            raise ValueError(f"{path}[{index}].reason 必须是非空 string")
        result.append(SkipBlockHint(id=block_id, reason=reason))
    return result


def _parse_columns(value, path: str) -> list[ColumnHint]:
    if not isinstance(value, list):
        raise ValueError(f"{path} 必须是 array")
    result: list[ColumnHint] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{path}[{index}] 必须是 object")
        column_id = item.get("id")
        if not isinstance(column_id, str) or not column_id:
            raise ValueError(f"{path}[{index}].id 必须是非空 string")
        result.append(ColumnHint(
            id=column_id,
            blocks=_parse_string_list(item.get("blocks", []), f"{path}[{index}].blocks"),
        ))
    return result


def _parse_special_regions(value, path: str) -> list[SpecialRegionHint]:
    if not isinstance(value, list):
        raise ValueError(f"{path} 必须是 array")
    result: list[SpecialRegionHint] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{path}[{index}] 必须是 object")
        region_type = item.get("type")
        if not isinstance(region_type, str) or not region_type:
            raise ValueError(f"{path}[{index}].type 必须是非空 string")
        result.append(SpecialRegionHint(
            type=region_type,
            blocks=_parse_string_list(item.get("blocks", []), f"{path}[{index}].blocks"),
        ))
    return result
