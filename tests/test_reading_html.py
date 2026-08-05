import re

import pytest

from core.typeset_models import (
    PAGE_CONTENT_SCHEMA_VERSION,
    PAGE_STRUCTURE_SCHEMA_VERSION,
    BackgroundLayer,
    ColumnInfo,
    ContentBlock,
    PageContent,
    PageContentDocument,
    PageStructure,
    PageStructureDocument,
    PageType,
    SemanticRole,
    StyledTextRun,
    TextRegionBBox,
)
from exporters.reading_html import ReadingHTMLRenderer, render_reading_html


def _block(block_id, region_id, text, role=SemanticRole.BODY_COLUMN, translatable=True):
    return ContentBlock(
        id=block_id,
        region_id=region_id,
        role=role,
        runs=[StyledTextRun(text, 10, False, False, "#111111")],
        source_text=text,
        translated_text=text if translatable else None,
        translatable=translatable,
    )


def _documents(page_type=PageType.SINGLE, columns=None, blocks=None):
    blocks = blocks or [_block("b1", "r1", "第一段\n第二行\n\n第二段")]
    columns = columns or []
    structure = PageStructureDocument(
        schema_version=PAGE_STRUCTURE_SCHEMA_VERSION,
        source_pdf="阅读 & 测试.pdf",
        page_count=1,
        pages=[
            PageStructure(
                page_index=0,
                width=612,
                height=792,
                background=BackgroundLayer(),
                images=[],
                decorations=[],
                text_regions=[
                    TextRegionBBox("r1", [20, 120, 280, 300], ["b1"]),
                    TextRegionBBox("r2", [300, 40, 580, 300], ["b2"]),
                    TextRegionBBox("r3", [20, 360, 280, 500], ["b3"]),
                ],
            )
        ],
        source_sha256="fixture-sha256",
    )
    content = PageContentDocument(
        schema_version=PAGE_CONTENT_SCHEMA_VERSION,
        source_pdf="阅读 & 测试.pdf",
        page_count=1,
        pages=[PageContent(0, page_type, columns, blocks)],
        source_sha256="fixture-sha256",
    )
    return structure, content


def test_page_set_mismatch_is_rejected():
    structure, content = _documents()
    content = PageContentDocument(
        content.schema_version,
        content.source_pdf,
        0,
        [],
        source_sha256=content.source_sha256,
    )
    with pytest.raises(ValueError, match="页面集合不一致"):
        render_reading_html(structure, content, {0: "assets/page_visuals/p0001.svg"})


def test_missing_translation_is_rejected():
    structure, content = _documents(blocks=[_block("b1", "r1", "待译", translatable=True)])
    page = content.pages[0]
    missing = ContentBlock("b1", "r1", SemanticRole.BODY_COLUMN, [], "待译", None, True)
    content = PageContentDocument(
        content.schema_version,
        content.source_pdf,
        1,
        [PageContent(0, page.page_type, [], [missing])],
        source_sha256=content.source_sha256,
    )
    with pytest.raises(ValueError, match="缺少 translated_text"):
        ReadingHTMLRenderer().render(structure, content, {0: "assets/page_visuals/p0001.svg"})


def test_unknown_region_is_rejected():
    structure, content = _documents(blocks=[_block("b1", "not-a-region", "文字")])
    with pytest.raises(ValueError, match="region 不存在"):
        ReadingHTMLRenderer().render(structure, content, {0: "assets/page_visuals/p0001.svg"})


def test_explicit_columns_control_order_and_each_block_is_emitted_once():
    blocks = [
        _block("b1", "r1", "一"),
        _block("b2", "r2", "二"),
        _block("b3", "r3", "三"),
    ]
    columns = [ColumnInfo("left", [0, 0, 1, 1], ["b2"]), ColumnInfo("right", [1, 0, 2, 1], ["b1"])]
    structure, content = _documents(PageType.COLUMNS, columns, blocks)
    output = render_reading_html(structure, content, {0: "assets/page_visuals/p0001.svg"})
    assert output.index('data-block-id="b2"') < output.index('data-block-id="b1"') < output.index('data-block-id="b3"')
    for block_id in ("b1", "b2", "b3"):
        assert output.count(f'data-block-id="{block_id}"') == 1
    assert 'class="reading-columns"' in output


def test_visual_css_escape_and_dialog_controls_are_present():
    structure, content = _documents()
    output = render_reading_html(structure, content, {0: "assets/page_visuals/p0001.svg?x=1&y=2"})
    assert output.count('src="assets/page_visuals/p0001.svg?x=1&amp;y=2"') == 1
    assert output.count('class="reading-visual"') == 1
    assert 'loading="lazy" width="612" height="792"' in output
    assert 'data-visual-anchor="page-1"' in output
    assert '<dialog' in output and 'showModal' in output
    assert 'data-reading-mode="parallel"' in output and 'data-reading-mode="focus"' in output
    assert 'localStorage' in output and 'data-font-step="-1"' in output


def test_mobile_css_and_print_controls_are_included():
    structure, content = _documents()
    output = render_reading_html(structure, content, {0: "assets/page_visuals/p0001.svg"})
    assert "@media (max-width: 760px)" in output
    assert "grid-template-columns: minmax(0, 1fr)" in output


def test_reading_html_can_link_back_to_fixed_layout():
    structure, content = _documents()

    output = ReadingHTMLRenderer().render(
        structure,
        content,
        {0: "assets/page_visuals/p0001.svg"},
        fixed_html_href="book_typeset.html",
    )

    assert 'href="book_typeset.html"' in output
    assert "原版排版" in output


def test_reading_html_preserves_safe_translation_emphasis_markup():
    structure, content = _documents(blocks=[_block("b1", "r1", "<strong>重点</strong> <em>斜体</em>")])

    output = render_reading_html(structure, content, {0: "assets/page_visuals/p0001.svg"})

    assert "<strong>重点</strong>" in output
    assert "<em>斜体</em>" in output
    assert ".reading-zoom-trigger" in output and "@media print" in output
    assert "prefers-reduced-motion" in output


def test_visual_only_page_centers_art_without_empty_text_column():
    structure, content = _documents(page_type=PageType.ART)
    page = content.pages[0]
    content = PageContentDocument(
        content.schema_version,
        content.source_pdf,
        content.page_count,
        [PageContent(page.page_index, page.page_type, page.columns, [])],
        source_sha256=content.source_sha256,
    )
    output = render_reading_html(structure, content, {0: "assets/page_visuals/p0001.svg"})
    assert "reading-page--visual-only" in output
    assert 'class="reading-text"' not in output
    assert ".reading-page--visual-only .reading-page-main { display: block; }" in output


def test_translated_text_is_escaped_and_preserves_breaks():
    text = "<script>alert('x')</script>\n第二行\n\n第三段"
    structure, content = _documents(blocks=[_block("b1", "r1", text)])
    output = render_reading_html(structure, content, {0: "assets/page_visuals/p0001.svg"})
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in output
    assert "<script>alert" not in output
    assert "<br>" in output and "</p><p>" in output
