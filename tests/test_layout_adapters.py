from exporters._shared import _layout_uses_columns, paginate_translated_blocks
from exporters.html import write_html_output
from exporters.markdown import write_markdown_output


def test_layout_helper_distinguishes_columns_from_single_column_modes():
    assert _layout_uses_columns("columns") is True
    assert _layout_uses_columns("character") is False
    assert _layout_uses_columns("document") is False
    assert _layout_uses_columns("credits") is False
    assert _layout_uses_columns("art") is False


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
