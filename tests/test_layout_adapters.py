import re
import zipfile

from core.layout_adapters import (
    build_output_layout_context_from_content,
    merge_output_page_layouts,
)
from core.typeset_models import (
    PAGE_CONTENT_SCHEMA_VERSION,
    ColumnInfo,
    ContentBlock,
    PageContent,
    PageContentDocument,
    PageType,
    SemanticRole,
    StyledTextRun,
)
from exporters._shared import _layout_uses_columns, paginate_translated_blocks
from exporters.html import write_html_output
from exporters.markdown import write_markdown_output
from exporters.word import HAS_DOCX, write_word_output


def _typeset_block(block_id="b1", region_id="r1", role=SemanticRole.BODY_COLUMN):
    return ContentBlock(
        id=block_id,
        region_id=region_id,
        role=role,
        runs=[StyledTextRun("Text", 10.0, False, False, "#000000")],
        source_text="Text",
        translated_text=None,
        translatable=True,
    )


def test_layout_helper_distinguishes_columns_from_single_column_modes():
    assert _layout_uses_columns("columns") is True
    assert _layout_uses_columns("three_columns") is True
    assert _layout_uses_columns("character") is False
    assert _layout_uses_columns("document") is False
    assert _layout_uses_columns("credits") is False
    assert _layout_uses_columns("art") is False


def test_typeset_semantics_become_reading_page_layouts():
    content = PageContentDocument(
        schema_version=PAGE_CONTENT_SCHEMA_VERSION,
        source_pdf="book.pdf",
        page_count=2,
        pages=[
            PageContent(
                page_index=0,
                page_type=PageType.SINGLE,
                columns=[],
                blocks=[_typeset_block()],
            ),
            PageContent(
                page_index=1,
                page_type=PageType.MIXED,
                columns=[
                    ColumnInfo("left", [0, 0, 100, 100], ["b2"]),
                    ColumnInfo("right", [120, 0, 220, 100], ["b3"]),
                ],
                blocks=[
                    _typeset_block("b2", "r2"),
                    _typeset_block("b3", "r3"),
                ],
            ),
        ],
    )

    context = build_output_layout_context_from_content(content)

    assert context.page_layouts == {0: "single", 1: "columns"}
    assert "typeset_page_type: single" in context.notes[0]
    assert "typeset_columns: 2" in context.notes[1]


def test_typeset_layout_merge_preserves_special_reading_layouts():
    merged = merge_output_page_layouts(
        {
            0: "toc",
            1: "handout",
            2: "character",
            3: "columns",
            5: "columns",
        },
        {
            0: "single",
            1: "columns",
            2: "single",
            3: "single",
            4: "art",
            5: "three_columns",
        },
    )

    assert merged[0] == "toc"
    assert merged[1] == "handout"
    assert merged[2] == "character"
    assert merged[3] == "single"
    assert merged[4] == "art"
    assert merged[5] == "three_columns"


def test_paginate_translated_blocks_splits_when_layout_changes():
    translated_pages = [
        (0, "第一段正文。"),
        (1, "第二段正文。"),
        (2, "人物卡内容。"),
    ]
    page_layouts = {
        0: "columns",
        1: "columns",
        2: "character",
    }

    pages = paginate_translated_blocks(
        translated_pages,
        min_chars=1,
        max_chars=1000,
        page_layouts=page_layouts,
        split_on_layout=True,
    )

    assert len(pages) == 2
    assert pages[0]["layout"] == "columns"
    assert pages[1]["layout"] == "character"


def test_html_output_emits_layout_class(tmp_path):
    out = tmp_path / "layout.html"
    translated_pages = [
        (0, "普通正文。"),
        (1, "角色页内容。"),
        (2, "名单页内容。"),
    ]
    page_layouts = {
        0: "columns",
        1: "character",
        2: "credits",
    }

    write_html_output(
        translated_pages,
        str(out),
        "Layout Demo",
        page_layouts=page_layouts,
    )

    html = out.read_text(encoding="utf-8")
    assert 'class="sheet character"' in html
    assert 'class="sheet credits"' in html


def test_html_output_supports_three_column_layout(tmp_path):
    out = tmp_path / "three.html"

    write_html_output(
        [(0, "第一段正文。")],
        str(out),
        "Layout Demo",
        columns=3,
        page_layouts={0: "three_columns"},
    )

    html = out.read_text(encoding="utf-8")
    assert 'class="sheet three_columns"' in html
    assert ".sheet.three_columns .content" in html
    assert "column-count: 3" in html


def test_html_output_uses_source_page_labels_in_footer(tmp_path):
    out = tmp_path / "layout.html"

    write_html_output(
        [(2, "第一段正文。"), (3, "第二段正文。")],
        str(out),
        "Layout Demo",
        min_chars=1,
        max_chars=1000,
        source_page_labels={2: "1", 3: "2"},
    )

    html = out.read_text(encoding="utf-8")
    assert "阅读版 1" in html
    assert "原书页 1-2" in html
    assert "Source PDF Pages" not in html


def test_html_output_omits_image_blocks(tmp_path):
    out = tmp_path / "layout.html"

    write_html_output(
        [(0, "前文。\n\n[IMAGE]\nIllustration placeholder\n[/IMAGE]\n\n后文。")],
        str(out),
        "Layout Demo",
        min_chars=1,
        max_chars=1000,
        image_assets={0: [{"path": "unused.png", "placement": "full"}]},
    )

    html = out.read_text(encoding="utf-8")
    assert "前文。" in html
    assert "后文。" in html
    assert "Illustration placeholder" not in html
    assert 'class="source-image' not in html
    assert 'class="image-placeholder"' not in html


def test_markdown_output_includes_layout_comment(tmp_path):
    out = tmp_path / "layout.md"
    translated_pages = [
        (0, "普通正文。"),
        (1, "整页文档内容。"),
    ]
    page_layouts = {
        0: "columns",
        1: "document",
    }

    write_markdown_output(
        translated_pages,
        str(out),
        "Layout Demo",
        page_layouts=page_layouts,
    )

    text = out.read_text(encoding="utf-8")
    assert "Layout: columns" in text
    assert "Layout: document" in text


def test_word_output_hides_cover_chrome_and_restarts_body_numbering(tmp_path):
    if not HAS_DOCX:
        return

    out = tmp_path / "layout.docx"
    write_word_output(
        [(2, "第一段正文。"), (3, "第二段正文。")],
        str(out),
        "Layout Demo",
        min_chars=1,
        max_chars=1000,
        source_page_labels={2: "1", 3: "2"},
    )

    with zipfile.ZipFile(out) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")
        footer_parts = [
            zf.read(name).decode("utf-8")
            for name in zf.namelist()
            if name.startswith("word/footer")
        ]
        footer_xml = "".join(footer_parts)
        header_xml = "".join(
            zf.read(name).decode("utf-8")
            for name in zf.namelist()
            if name.startswith("word/header")
        )

    assert '<w:pgNumType w:start="1"/>' in document_xml
    assert document_xml.count("<w:pgNumType") == 1
    assert len(footer_parts) >= 2
    assert any("PAGE" in footer for footer in footer_parts)
    assert any("PAGE" not in footer for footer in footer_parts)
    assert "// 绿色三角洲 //" in header_xml
    assert "原书页" not in footer_xml


def test_word_output_keeps_cards_inline_and_omits_image_blocks(tmp_path):
    if not HAS_DOCX:
        return

    out = tmp_path / "layout.docx"
    write_word_output(
        [(
            0,
            "前文。\n\n"
            "[CARD]\n卡片标题\n卡片正文。\n[/CARD]\n\n"
            "[IMAGE]\nIllustration placeholder\n[/IMAGE]\n\n"
            "后文。",
        )],
        str(out),
        "Layout Demo",
        min_chars=1,
        max_chars=1000,
    )

    with zipfile.ZipFile(out) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")

    assert "前文。" in document_xml
    assert "卡片标题" in document_xml
    assert "后文。" in document_xml
    assert "Illustration placeholder" not in document_xml
    assert document_xml.count("<w:sectPr") == 2


def test_word_output_keeps_page_numbering_continuous_across_table_sections(tmp_path):
    if not HAS_DOCX:
        return

    out = tmp_path / "layout.docx"
    write_word_output(
        [(0, "前文。\n\n| 名称 | 数值 |\n|---|---|\n| 示例 | 1 |\n\n后文。")],
        str(out),
        "Layout Demo",
        min_chars=1,
        max_chars=1000,
    )

    with zipfile.ZipFile(out) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")

    assert document_xml.count("<w:pgNumType") == 1


def test_word_output_renders_toc_as_two_column_compact_leaders(tmp_path):
    if not HAS_DOCX:
        return

    out = tmp_path / "toc.docx"
    write_word_output(
        [(0, "[[TOC]]\n# Contents\n\n```toc\nChapter One ........ 12\nAppendix ----- 203\n```")],
        str(out),
        "Layout Demo",
        min_chars=1,
        max_chars=1000,
        page_layouts={0: "toc"},
    )

    with zipfile.ZipFile(out) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")

    assert 'w:num="2"' in document_xml
    assert 'w:leader="dot"' in document_xml
    assert "Chapter One" in document_xml
    assert "Appendix" in document_xml
    assert "```toc" not in document_xml
    assert "[[TOC]]" not in document_xml


def test_word_output_renders_inline_toc_fence(tmp_path):
    if not HAS_DOCX:
        return

    out = tmp_path / "inline_toc.docx"
    write_word_output(
        [(0, "# Contents```tocChapter One ........ 12\n```")],
        str(out),
        "Layout Demo",
        min_chars=1,
        max_chars=1000,
        page_layouts={0: "toc"},
    )

    with zipfile.ZipFile(out) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")

    assert "Contents" in document_xml
    assert "Chapter One" in document_xml
    assert "```toc" not in document_xml


def test_word_output_supports_three_columns(tmp_path):
    if not HAS_DOCX:
        return

    out = tmp_path / "three.docx"
    write_word_output(
        [(0, "第一段正文。")],
        str(out),
        "Layout Demo",
        min_chars=1,
        max_chars=1000,
        columns=3,
        page_layouts={0: "three_columns"},
    )

    with zipfile.ZipFile(out) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")

    assert 'w:num="3"' in document_xml
