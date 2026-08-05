"""Responsive, illustrated reading HTML renderer.

This renderer consumes the canonical page structure and translated page
content documents.  It deliberately keeps page visuals as a single clean SVG
asset per source page while presenting the translated blocks as accessible,
searchable HTML text beside it.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from typing import Any

from core.typeset_models import (
    ContentBlock,
    PageContent,
    PageContentDocument,
    PageStructure,
    PageStructureDocument,
    PageType,
    SemanticRole,
)


def _number(value: float | int) -> str:
    """Format a geometry number for HTML attributes without losing its value."""

    number = float(value)
    if number.is_integer():
        return str(int(number))
    return format(number, ".15g")


def _page_number(page_index: int) -> int:
    """Return the user-facing (one-based) source page number."""

    return int(page_index) + 1


def _role_value(role: SemanticRole | str) -> str:
    return role.value if isinstance(role, SemanticRole) else str(role)


def _escaped_text(text: str) -> str:
    """Escape text while preserving paragraphs and explicit line breaks."""

    # A blank line starts a new paragraph.  A single line break remains a
    # visible break.  Empty paragraphs are omitted, never invented.
    paragraphs = re.split(r"\n\s*\n+", str(text))
    return "".join(
        f"<p>{_escaped_emphasis_markup(paragraph).replace(chr(10), '<br>')}</p>"
        for paragraph in paragraphs
        if paragraph != ""
    ) or "<p></p>"


def _escaped_inline_text(text: str) -> str:
    """Escape heading text without creating invalid block elements inside it."""

    escaped = _escaped_emphasis_markup(str(text))
    return re.sub(r"\n+", "<br>", escaped)


def _escaped_emphasis_markup(text: str) -> str:
    escaped = html.escape(str(text), quote=True)
    return (
        escaped.replace("&lt;strong&gt;", "<strong>")
        .replace("&lt;/strong&gt;", "</strong>")
        .replace("&lt;em&gt;", "<em>")
        .replace("&lt;/em&gt;", "</em>")
    )


def _text_for_block(block: ContentBlock) -> str:
    if block.translatable:
        # Validation happens before rendering; keep this explicit so a missing
        # translation can never silently fall back to source text.
        assert block.translated_text is not None
        return block.translated_text
    return block.translated_text if block.translated_text is not None else block.source_text


class ReadingHTMLRenderer:
    """Build a complete Chinese reading-page HTML document."""

    def render(
        self,
        structure: PageStructureDocument,
        content: PageContentDocument,
        page_visuals: dict[int, str],
        fixed_html_href: str | None = None,
    ) -> str:
        """Render ``structure`` and translated ``content`` into HTML.

        ``page_visuals`` is required: every source page must have exactly one
        clean SVG path.  All consistency errors raise ``ValueError`` before
        any HTML is produced.
        """

        self._validate_documents(structure, content, page_visuals)
        content_by_page = {page.page_index: page for page in content.pages}
        pages = [
            self._render_page(
                page_structure,
                content_by_page[page_structure.page_index],
                page_visuals[page_structure.page_index],
            )
            for page_structure in structure.pages
        ]

        title = html.escape(str(structure.source_pdf), quote=False)
        return "\n".join(
            [
                "<!doctype html>",
                '<html lang="zh-CN">',
                "<head>",
                '<meta charset="utf-8">',
                '<meta name="viewport" content="width=device-width, initial-scale=1">',
                f"<title>图文阅读版 · {title}</title>",
                f"<style>{self._css()}</style>",
                "</head>",
                '<body class="reading-body">',
                self._toolbar(fixed_html_href),
                '<main class="reading-document" aria-label="图文阅读内容">',
                *pages,
                "</main>",
                self._script(),
                "</body>",
                "</html>",
            ]
        )

    # Common names used by callers of the existing typeset HTML exporter.
    rebuild_document = render
    render_document = render
    build_document = render

    def __call__(
        self,
        structure: PageStructureDocument,
        content: PageContentDocument,
        page_visuals: dict[int, str],
        fixed_html_href: str | None = None,
    ) -> str:
        return self.render(structure, content, page_visuals, fixed_html_href=fixed_html_href)

    @staticmethod
    def _validate_documents(
        structure: PageStructureDocument,
        content: PageContentDocument,
        page_visuals: Mapping[int, str],
    ) -> None:
        if not isinstance(page_visuals, Mapping):
            raise ValueError("page_visuals 必须是按源页编号索引的映射")

        if not structure.source_sha256 or structure.source_sha256 != content.source_sha256:
            raise ValueError("页面结构与翻译内容来源 PDF 哈希不一致")
        if structure.page_count != len(structure.pages):
            raise ValueError("PageStructureDocument.page_count 与页面数量不一致")
        if content.page_count != len(content.pages):
            raise ValueError("PageContentDocument.page_count 与页面数量不一致")

        structure_ids = [page.page_index for page in structure.pages]
        content_ids = [page.page_index for page in content.pages]
        if len(set(structure_ids)) != len(structure_ids):
            raise ValueError("PageStructureDocument 包含重复页面编号")
        if len(set(content_ids)) != len(content_ids):
            raise ValueError("PageContentDocument 包含重复页面编号")
        structure_set = set(structure_ids)
        content_set = set(content_ids)
        visual_set = set(page_visuals)
        if structure_set != content_set:
            missing = sorted(structure_set - content_set)
            extra = sorted(content_set - structure_set)
            raise ValueError(f"页面集合不一致：content 缺少 {missing}，多出 {extra}")
        if structure_set != visual_set:
            missing = sorted(structure_set - visual_set)
            extra = sorted(visual_set - structure_set)
            raise ValueError(f"页面视觉资源集合不一致：缺少 {missing}，多出 {extra}")
        if any(not isinstance(path, str) or not path.strip() for path in page_visuals.values()):
            raise ValueError("每个源页必须提供非空 SVG 视觉资源路径")

        structure_by_page = {page.page_index: page for page in structure.pages}
        for page in content.pages:
            region_ids = {region.id for region in structure_by_page[page.page_index].text_regions}
            if len(region_ids) != len(structure_by_page[page.page_index].text_regions):
                raise ValueError(f"第 {_page_number(page.page_index)} 页包含重复文本区域编号")
            block_ids: set[str] = set()
            for block in page.blocks:
                if block.id in block_ids:
                    raise ValueError(f"第 {_page_number(page.page_index)} 页包含重复内容块编号：{block.id}")
                block_ids.add(block.id)
                if block.region_id not in region_ids:
                    raise ValueError(
                        f"第 {_page_number(page.page_index)} 页内容块 {block.id} 的 region 不存在：{block.region_id}"
                    )
                if block.translatable and (
                    block.translated_text is None or not block.translated_text.strip()
                ):
                    raise ValueError(f"内容块 {block.id} 缺少 translated_text")
            column_ids: list[str] = []
            for column in page.columns:
                for block_id in column.block_ids:
                    if block_id not in block_ids:
                        raise ValueError(
                            f"第 {_page_number(page.page_index)} 页栏引用不存在的内容块：{block_id}"
                        )
                    column_ids.append(block_id)
            duplicates = sorted({block_id for block_id in column_ids if column_ids.count(block_id) > 1})
            if duplicates:
                raise ValueError(
                    f"第 {_page_number(page.page_index)} 页栏重复引用内容块：{duplicates}"
                )

    @staticmethod
    def _reading_order(
        page_structure: PageStructure,
        page_content: PageContent,
    ) -> tuple[list[ContentBlock], list[tuple[str, list[ContentBlock]]]]:
        blocks_by_id = {block.id: block for block in page_content.blocks}
        regions = {region.id: region for region in page_structure.text_regions}
        listed: list[str] = []
        columns: list[tuple[str, list[ContentBlock]]] = []
        for column in page_content.columns:
            current = [blocks_by_id[block_id] for block_id in column.block_ids]
            listed.extend(column.block_ids)
            columns.append((column.side, current))

        unlisted = [block for block in page_content.blocks if block.id not in set(listed)]
        try:
            unlisted.sort(key=lambda block: (float(regions[block.region_id].bbox[1]), float(regions[block.region_id].bbox[0])))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"无法按 region bbox 排序第 {_page_number(page_content.page_index)} 页内容块") from exc
        order = [block for column in columns for block in column[1]] + unlisted
        return order, columns

    def _render_page(
        self,
        page_structure: PageStructure,
        page_content: PageContent,
        visual_path: str,
    ) -> str:
        number = _page_number(page_structure.page_index)
        page_type = page_content.page_type.value if isinstance(page_content.page_type, PageType) else str(page_content.page_type)
        order, columns = self._reading_order(page_structure, page_content)
        block_html = {block.id: self._render_block(block) for block in order}

        if page_content.columns:
            column_parts = [
                f'<section class="reading-column" data-column="{html.escape(side, quote=True)}">'
                + "".join(block_html[block.id] for block in column_blocks)
                + "</section>"
                for side, column_blocks in columns
            ]
            listed = {block.id for _, column_blocks in columns for block in column_blocks}
            unlisted = [block for block in order if block.id not in listed]
            if unlisted:
                column_parts.append(
                    '<section class="reading-column reading-column--unassigned" data-column="unassigned">'
                    + "".join(block_html[block.id] for block in unlisted)
                    + "</section>"
                )
            text_body = '<div class="reading-columns">' + "".join(column_parts) + "</div>"
        else:
            text_body = '<div class="reading-flow">' + "".join(block_html[block.id] for block in order) + "</div>"

        visual_only = not order

        visual_src = html.escape(str(visual_path), quote=True)
        anchor = f"page-{number}"
        dialog_id = f"reading-dialog-{number}"
        image_alt = html.escape(f"第{number}页视觉", quote=True)
        visual = (
            '<figure class="reading-visual">'
            f'<button type="button" class="reading-zoom-trigger" data-dialog-target="{dialog_id}" '
            f'aria-controls="{dialog_id}" aria-label="放大第{number}页视觉">'
            f'<img class="reading-visual-image" src="{visual_src}" data-visual-anchor="{anchor}" '
            f'loading="lazy" width="{_number(page_structure.width)}" height="{_number(page_structure.height)}" '
            f'alt="{image_alt}">'
            '<span class="reading-zoom-hint">点击放大</span>'
            "</button>"
            f'<figcaption>第{number}页 · 原始视觉</figcaption>'
            f'<dialog class="reading-dialog" id="{dialog_id}" aria-labelledby="{dialog_id}-title">'
            f'<h2 id="{dialog_id}-title">第{number}页视觉预览</h2>'
            '<button type="button" class="reading-dialog-close" data-dialog-close aria-label="关闭放大预览">关闭</button>'
            f'<div class="reading-dialog-image" data-dialog-image role="img" aria-label="{image_alt}"></div>'
            "</dialog>"
            "</figure>"
        )
        page_classes = f"reading-page page-type-{page_type}"
        if visual_only:
            page_classes += " reading-page--visual-only"
        text_section = (
            f'<section class="reading-text" aria-label="第{number}页译文">{text_body}</section>'
            if not visual_only
            else ""
        )
        return (
            f'<article class="{html.escape(page_classes, quote=True)}" data-page="{number}">'
            f'<header class="reading-page-heading"><span>源页 {number}</span><span>{html.escape(page_type.upper(), quote=True)}</span></header>'
            '<div class="reading-page-main">'
            + visual
            + text_section
            + "</div></article>"
        )

    @staticmethod
    def _render_block(block: ContentBlock) -> str:
        block_id = html.escape(block.id, quote=True)
        region_id = html.escape(block.region_id, quote=True)
        role = _role_value(block.role)
        role_class = html.escape(role.replace("_", "-"), quote=True)
        raw_text = _text_for_block(block)
        text = _escaped_text(raw_text)
        inline_text = _escaped_inline_text(raw_text)
        attrs = f'data-block-id="{block_id}" data-region-id="{region_id}"'

        if role == SemanticRole.TITLE.value:
            element = f'<h2>{inline_text}</h2>'
        elif role == SemanticRole.HEADER.value:
            element = f'<h2 class="reading-header">{inline_text}</h2>'
        elif role == SemanticRole.SUBTITLE.value:
            element = f"<h3>{inline_text}</h3>"
        elif role == SemanticRole.FOOTNOTE.value:
            element = f'<aside class="reading-footnote">{text}</aside>'
        elif role == SemanticRole.FOOTER.value:
            element = f'<footer class="reading-footer">{text}</footer>'
        elif role == SemanticRole.LIST.value:
            element = f'<ul class="reading-list"><li>{text}</li></ul>'
        elif role == SemanticRole.TABLE.value:
            element = f'<div class="reading-table">{text}</div>'
        else:
            element = text
        return f'<div class="reading-block role-{role_class}" {attrs}>{element}</div>'

    @staticmethod
    def _toolbar(fixed_html_href: str | None = None) -> str:
        fixed_link = ""
        if fixed_html_href:
            fixed_link = (
                f'<a class="reading-fixed-link" href="{html.escape(fixed_html_href, quote=True)}">'
                '原版排版</a>'
            )
        return (
            '<nav class="reading-toolbar" aria-label="阅读工具">'
            '<div class="reading-toolbar-title">图文阅读</div>'
            '<div class="reading-toolbar-controls">'
            '<button type="button" class="reading-mode-button" data-reading-mode="parallel" aria-pressed="true">图文并排</button>'
            '<button type="button" class="reading-mode-button" data-reading-mode="focus" aria-pressed="false">专注阅读</button>'
            '<span class="reading-toolbar-divider" aria-hidden="true"></span>'
            '<button type="button" class="reading-font-button" data-font-step="-1" aria-label="减小字体">A−</button>'
            '<button type="button" class="reading-font-button" data-font-step="1" aria-label="增大字体">A＋</button>'
            f'{fixed_link}'
            '</div></nav>'
        )

    @staticmethod
    def _css() -> str:
        return r"""
:root { --reading-font-scale: 1; --reading-ink: #1c2930; --reading-muted: #5a6a70; --reading-paper: #f5f1e9; --reading-accent: #b85c38; }
*, *::before, *::after { box-sizing: border-box; }
html { background: #dfe5e2; }
body { margin: 0; min-width: 0; overflow-x: hidden; background: var(--reading-paper); color: var(--reading-ink); font-family: "Noto Serif SC", "Source Han Serif CN", "SimSun", serif; font-size: calc(1rem * var(--reading-font-scale)); line-height: 1.7; }
button { font: inherit; }
button:focus-visible, dialog:focus-visible { outline: 3px solid #e19a54; outline-offset: 2px; }
.reading-toolbar { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; justify-content: space-between; gap: 1rem; max-width: 1180px; margin: 0 auto; padding: .75rem 1rem; border-bottom: 1px solid #c7d0cc; background: rgba(245,241,233,.96); box-shadow: 0 2px 8px rgba(28,41,48,.08); }
.reading-toolbar-title { font-weight: 700; letter-spacing: .08em; color: var(--reading-accent); white-space: nowrap; }
.reading-toolbar-controls { display: flex; align-items: center; gap: .45rem; }
.reading-toolbar button { min-height: 2.25rem; padding: .35rem .7rem; border: 1px solid #9eaaa7; border-radius: .4rem; background: #fffdf9; color: var(--reading-ink); cursor: pointer; }
.reading-fixed-link { display: inline-flex; align-items: center; min-height: 2.25rem; padding: .35rem .7rem; border: 1px solid var(--reading-accent); border-radius: .4rem; color: var(--reading-accent); text-decoration: none; white-space: nowrap; }
.reading-toolbar button[aria-pressed="true"] { border-color: var(--reading-accent); background: var(--reading-accent); color: white; }
.reading-toolbar-divider { width: 1px; height: 1.5rem; margin: 0 .2rem; background: #c7d0cc; }
.reading-document { width: min(100%, 1180px); margin: 0 auto; padding: 1.5rem 1rem 4rem; }
.reading-page { margin: 0 auto 2rem; padding: clamp(1rem, 2.4vw, 2rem); border: 1px solid #d2d8d3; border-radius: .75rem; background: #fffdf9; box-shadow: 0 10px 28px rgba(28,41,48,.09); overflow: hidden; break-after: page; }
.reading-page-heading { display: flex; justify-content: space-between; gap: 1rem; margin-bottom: 1rem; color: var(--reading-muted); font: .78rem/1.3 "Noto Sans SC", "Microsoft YaHei", sans-serif; letter-spacing: .08em; text-transform: uppercase; }
.reading-page-main { display: grid; grid-template-columns: minmax(0, 42%) minmax(0, 58%); gap: clamp(1rem, 2.8vw, 2.5rem); align-items: start; }
.reading-page.page-type-art .reading-page-main, .reading-page.page-type-cover .reading-page-main { grid-template-columns: minmax(0, 54%) minmax(0, 46%); }
.reading-page--visual-only .reading-page-main { display: block; }
.reading-page--visual-only .reading-visual { width: min(100%, 612px); margin: 0 auto; }
.reading-visual { min-width: 0; margin: 0; transition: opacity .2s ease, transform .2s ease; }
.reading-zoom-trigger { display: block; width: 100%; padding: 0; border: 0; background: transparent; color: inherit; text-align: left; cursor: zoom-in; }
.reading-visual-image { display: block; width: 100%; height: auto; max-width: 100%; border: 1px solid #d2d8d3; border-radius: .35rem; background: #e9eeeb; object-fit: contain; }
.reading-zoom-hint { display: block; margin-top: .35rem; color: var(--reading-muted); font: .8rem/1.3 "Noto Sans SC", "Microsoft YaHei", sans-serif; }
.reading-visual figcaption { margin-top: .5rem; color: var(--reading-muted); font: .78rem/1.3 "Noto Sans SC", "Microsoft YaHei", sans-serif; }
.reading-text { min-width: 0; overflow-wrap: anywhere; word-break: break-word; }
.reading-flow, .reading-columns { min-width: 0; }
.reading-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: clamp(1rem, 2.2vw, 2rem); }
.reading-column { min-width: 0; }
.reading-block { margin: 0 0 1rem; min-width: 0; }
.reading-block > p { margin: 0 0 .65rem; text-indent: 2em; }
.reading-block > p + p { margin-top: .65rem; }
.reading-block h2, .reading-block h3 { margin: .1rem 0 .55rem; line-height: 1.35; text-indent: 0; overflow-wrap: anywhere; }
.reading-block h2 { font-size: 1.45em; color: #233f45; }
.reading-block h3 { font-size: 1.2em; color: var(--reading-accent); }
.reading-header { border-left: .25rem solid var(--reading-accent); padding-left: .65rem; }
.reading-footnote, .reading-footer { display: block; margin: .8rem 0; padding: .65rem .8rem; color: var(--reading-muted); border-left: 3px solid #a9b8b2; font-size: .9em; }
.reading-footer { border-left: 0; border-top: 1px solid #d2d8d3; font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif; }
.reading-list { margin: 0; padding-left: 1.5rem; }
.reading-list li { margin: 0 0 .5rem; }
.reading-table { padding: .65rem .8rem; border: 1px solid #c7d0cc; border-radius: .3rem; background: #f3f6f3; }
.reading-focus .reading-visual { opacity: .34; transform: scale(.97); }
.reading-focus .reading-page-main { grid-template-columns: minmax(0, 22%) minmax(0, 78%); }
.reading-focus .reading-page.page-type-art .reading-page-main, .reading-focus .reading-page.page-type-cover .reading-page-main { grid-template-columns: minmax(0, 30%) minmax(0, 70%); }
.reading-dialog { width: min(94vw, 1100px); max-width: none; padding: 1rem; border: 1px solid #9eaaa7; border-radius: .55rem; background: #17252a; color: #f8faf7; }
.reading-dialog::backdrop { background: rgba(10,18,20,.8); }
.reading-dialog h2 { margin: 0 0 .6rem; font-size: 1rem; }
.reading-dialog-close { position: absolute; top: .75rem; right: .75rem; padding: .3rem .65rem; border: 1px solid #b7c5c0; border-radius: .35rem; background: transparent; color: inherit; cursor: pointer; }
.reading-dialog-image { min-height: min(76vh, 760px); background-position: center; background-repeat: no-repeat; background-size: contain; }
@media (max-width: 760px) {
  .reading-toolbar { align-items: flex-start; flex-direction: column; gap: .6rem; }
  .reading-toolbar-controls { width: 100%; overflow-x: auto; }
  .reading-document { padding: 0 0 2rem; }
  .reading-page { margin: 0 0 1rem; border-right: 0; border-left: 0; border-radius: 0; box-shadow: none; padding: 1rem; }
  .reading-page-main, .reading-focus .reading-page-main, .reading-page.page-type-art .reading-page-main, .reading-page.page-type-cover .reading-page-main, .reading-focus .reading-page.page-type-art .reading-page-main, .reading-focus .reading-page.page-type-cover .reading-page-main { grid-template-columns: minmax(0, 1fr); }
  .reading-visual { order: -1; }
  .reading-columns { display: block; }
  .reading-column { margin-bottom: 1rem; }
}
@media print {
  html, body { background: white; }
  .reading-toolbar, .reading-zoom-hint, .reading-dialog { display: none !important; }
  .reading-zoom-trigger { display: block; pointer-events: none; }
  .reading-document { width: 100%; margin: 0; padding: 0; }
  .reading-page { margin: 0; border: 0; border-radius: 0; box-shadow: none; break-after: page; }
  .reading-page-main, .reading-page.page-type-art .reading-page-main, .reading-page.page-type-cover .reading-page-main { display: block; }
  .reading-visual { margin-bottom: 1rem; opacity: 1; transform: none; }
  .reading-columns { display: grid; }
}
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; animation: none !important; } }
"""

    @staticmethod
    def _script() -> str:
        return r"""
<script>
(function () {
  "use strict";
  var body = document.body;
  var modeKey = "dg-reading-mode";
  var fontKey = "dg-reading-font-scale";
  var modeButtons = Array.prototype.slice.call(document.querySelectorAll("[data-reading-mode]"));
  var fontButtons = Array.prototype.slice.call(document.querySelectorAll("[data-font-step]"));
  function read(key, fallback) { try { return window.localStorage.getItem(key) || fallback; } catch (error) { return fallback; } }
  function write(key, value) { try { window.localStorage.setItem(key, value); } catch (error) {} }
  function applyMode(mode, persist) {
    var focus = mode === "focus";
    body.classList.toggle("reading-focus", focus);
    modeButtons.forEach(function (button) { button.setAttribute("aria-pressed", button.getAttribute("data-reading-mode") === mode ? "true" : "false"); });
    if (persist) { write(modeKey, mode); }
  }
  function applyFont(value, persist) {
    var scale = Math.max(.8, Math.min(1.35, Number(value) || 1));
    body.style.setProperty("--reading-font-scale", scale.toFixed(2));
    if (persist) { write(fontKey, scale.toFixed(2)); }
  }
  modeButtons.forEach(function (button) { button.addEventListener("click", function () { applyMode(button.getAttribute("data-reading-mode"), true); }); });
  fontButtons.forEach(function (button) { button.addEventListener("click", function () { var current = parseFloat(getComputedStyle(body).getPropertyValue("--reading-font-scale")) || 1; applyFont(current + Number(button.getAttribute("data-font-step")) * .1, true); }); });
  applyMode(read(modeKey, "parallel"), false);
  applyFont(read(fontKey, "1"), false);
  document.querySelectorAll("[data-dialog-target]").forEach(function (trigger) {
    var dialog = document.getElementById(trigger.getAttribute("data-dialog-target"));
    var image = trigger.querySelector("img");
    var zoom = dialog && dialog.querySelector("[data-dialog-image]");
    if (!dialog || !image || !zoom) { return; }
    trigger.addEventListener("click", function () { zoom.style.backgroundImage = "url(\"" + (image.currentSrc || image.src).replace(/\"/g, "\\\"") + "\")"; if (typeof dialog.showModal === "function") { dialog.showModal(); } else { dialog.setAttribute("open", ""); } });
    dialog.querySelectorAll("[data-dialog-close]").forEach(function (close) { close.addEventListener("click", function () { dialog.close(); }); });
    dialog.addEventListener("click", function (event) { if (event.target === dialog) { dialog.close(); } });
  });
}());
</script>
"""


# Alias matching the existing class name used by the high-fidelity exporter.
ReadingHTMLRebuilder = ReadingHTMLRenderer


def render_reading_html(
    structure: PageStructureDocument,
    content: PageContentDocument,
    page_visuals: dict[int, str],
) -> str:
    """Convenience function for one-shot rendering."""

    return ReadingHTMLRenderer().render(structure, content, page_visuals)


build_reading_html = render_reading_html
