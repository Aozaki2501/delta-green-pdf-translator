from dataclasses import replace

from core.typeset_models import (
    BackgroundLayer,
    ColumnInfo,
    ContentBlock,
    DecorationElement,
    FontRole,
    PageContent,
    PageStructure,
    PageType,
    SemanticRole,
    StyledTextRun,
    TextRegionBBox,
)
from exporters.typeset_html import TypesetHTMLRebuilder


def _block(index, bbox, source, translated, font_role=FontRole.BODY, role=SemanticRole.BODY_COLUMN):
    region_id = f"r{index}"
    return (
        TextRegionBBox(id=region_id, bbox=bbox, block_ids=[f"b{index}"]),
        ContentBlock(
            id=f"b{index}",
            region_id=region_id,
            role=role,
            runs=[StyledTextRun(source, 10.5, False, False, "#000000")],
            source_text=source,
            translated_text=translated,
            translatable=True,
            bbox=bbox,
            font_role=font_role,
            order=index,
        ),
    )


def _page(pairs, page_type=PageType.MIXED):
    return (
        PageContent(
            page_index=0,
            page_type=page_type,
            columns=[],
            blocks=[block for _, block in pairs],
        ),
        PageStructure(
            page_index=0,
            width=612.0,
            height=792.0,
            background=BackgroundLayer(),
            images=[],
            decorations=[],
            text_regions=[region for region, _ in pairs],
        ),
    )


def test_newage_timeline_recognizes_dates_at_block_ends_and_keeps_two_columns():
    pairs = [
        _block(0, [40, 63, 550, 100], "Timeline of Past Events", "过往事件时间线", FontRole.SECTION, SemanticRole.SUBTITLE),
        _block(1, [40, 105, 125, 130], "15 OCT 1962", "1962年10月15日"),
        _block(2, [45, 130, 280, 180], "* First event.\n26 FEB 1964", "* 第一件事。\n1964年2月26日"),
        _block(3, [45, 180, 280, 230], "* Second event.\n1972", "* 第二件事。\n1972"),
        _block(4, [45, 230, 280, 280], "* Third event.\n13 MAY 1980", "* 第三件事。\n1980年5月13日"),
        _block(5, [300, 110, 385, 135], "18 SEPT 1992", "1992年9月18日"),
        _block(6, [305, 135, 535, 190], "* Fourth event.\n27 SEPT 1992", "* 第四件事。\n1992年9月27日"),
        _block(7, [305, 190, 535, 245], "* Fifth event.\n11 FEB 1995", "* 第五件事。\n1995年2月11日"),
    ]
    content, structure = _page(pairs)
    structure = replace(
        structure,
        decorations=[
            DecorationElement(
                id=f"line-{index}",
                element_type="line",
                bbox=[40.0, 100.0 + index, 540.0, 100.0 + index],
                stroke_color="#000000",
                fill_color=None,
                stroke_width=1.0,
            )
            for index in range(80)
        ],
    )

    html = TypesetHTMLRebuilder().render_text_layer(content, structure)

    assert html.count('class="typeset-timeline-flow"') == 2
    assert 'data-column="left"' in html
    assert 'data-column="right"' in html
    assert "typeset-timeline-date" in html
    assert "1964年2月26日" in html
    assert "typeset-reflow-columns" not in html


def test_newage_stacked_cards_keep_independent_source_regions():
    pairs = [
        _block(0, [36, 86, 540, 128], "Intro", "导语" * 20),
        _block(1, [230, 155, 345, 176], "About", "关于", FontRole.SUBSECTION, SemanticRole.SUBTITLE),
        _block(2, [35, 176, 540, 226], "First card", "第一张卡片" * 18),
        _block(3, [40, 269, 235, 287], "Subject one", "主题一"),
        _block(4, [33, 299, 540, 465], "Second card", "第二张卡片" * 40),
        _block(5, [42, 505, 150, 523], "Subject two", "主题二"),
        _block(6, [41, 536, 542, 701], "Third card", "第三张卡片" * 40),
    ]
    content, structure = _page(pairs, PageType.SINGLE)

    html = TypesetHTMLRebuilder().render_text_layer(content, structure)

    assert html.count('class="typeset-positioned-block"') == len(pairs)
    assert "typeset-reflow-area" not in html
    assert "typeset-region-flow" not in html


def test_three_stacked_cards_do_not_leave_the_last_card_blank():
    pairs = [
        _block(0, [35, 100, 540, 210], "First card", "第一张卡片" * 30),
        _block(1, [35, 260, 540, 430], "Second card", "第二张卡片" * 35),
        _block(2, [35, 500, 540, 700], "Third card", "第三张卡片" * 40),
    ]
    content, structure = _page(pairs, PageType.SINGLE)

    html = TypesetHTMLRebuilder().render_text_layer(content, structure)

    assert html.count('class="typeset-positioned-block"') == 3
    assert "第三张卡片" in html
    assert "typeset-reflow-area" not in html


def test_source_font_family_and_heading_color_survive_translation():
    _, title = _block(
        0,
        [36, 61, 215, 85],
        "Player Aid",
        "玩家协助",
        FontRole.DISPLAY,
        SemanticRole.TITLE,
    )
    title = replace(
        title,
        source_font="Industria-Solid",
        runs=[
            StyledTextRun(
                "Player Aid",
                20.0,
                False,
                False,
                "#eb4f24",
                font="Industria-Solid",
            )
        ],
    )

    html = TypesetHTMLRebuilder()._render_block(title)

    assert "source-font-geometric" in html
    assert "color:#eb4f24" in html
    assert "font-weight:400" in html


def test_typewriter_source_uses_distinct_chinese_font_role():
    _, body = _block(0, [36, 260, 540, 460], "SUBJECT", "主题")
    body = replace(body, source_font="VT323-Regular")

    html = TypesetHTMLRebuilder()._render_block(body)

    assert "source-font-typewriter" in html


def test_source_paragraph_indent_is_not_forced_on_flush_paragraphs():
    _, flush = _block(0, [36, 100, 270, 180], "First", "第一段")
    _, indented = _block(1, [36, 190, 270, 270], "Second", "第二段")
    indented = replace(indented, first_line_indent_pt=18.0)
    rebuilder = TypesetHTMLRebuilder()

    flush_html = rebuilder._render_reflow_block(flush)
    indented_html = rebuilder._render_reflow_block(indented)

    assert 'style="text-indent:0"' in flush_html
    assert 'style="text-indent:2em"' in indented_html


def test_title_is_not_deduplicated_by_body_text_from_the_same_region():
    region, title = _block(
        0,
        [72, 69, 202, 101],
        "The Loose Cannon",
        "脱缰野马",
        FontRole.DISPLAY,
        SemanticRole.TITLE,
    )
    _, body = _block(
        1,
        [72, 102, 306, 293],
        "Ronald Valiant is the loose cannon that may sink the foundation.",
        "罗纳德·瓦利安特是一颗可能毁掉基金会的脱缰野马。",
    )
    body = replace(body, region_id=title.region_id)
    region = replace(region, bbox=[72, 69, 306, 293])

    kept = TypesetHTMLRebuilder()._dedupe_content_blocks(
        [title, body],
        {region.id: region.bbox},
    )

    assert [block.id for block in kept] == [title.id, body.id]


def test_two_column_body_is_split_around_internal_headings():
    pairs = [
        _block(0, [36, 71, 276, 260], "Left", "左栏正文" * 25),
        _block(1, [303, 71, 540, 173], "Before", "标题前正文" * 15),
        _block(2, [304, 196, 382, 220], "Enter Enolsis", "进入恩洛斯", FontRole.DISPLAY, SemanticRole.TITLE),
        _block(3, [303, 221, 542, 428], "After one", "标题后正文一" * 25),
        _block(4, [303, 431, 537, 563], "After two", "标题后正文二" * 20),
    ]
    content = PageContent(
        page_index=0,
        page_type=PageType.COLUMNS,
        columns=[
            ColumnInfo("left", [36, 71, 276, 728], ["b0"]),
            ColumnInfo("right", [303, 71, 542, 728], ["b1", "b2", "b3", "b4"]),
        ],
        blocks=[block for _, block in pairs],
    )
    structure = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[region for region, _ in pairs],
    )

    html = TypesetHTMLRebuilder().render_text_layer(content, structure)

    assert html.count('class="typeset-region-flow" data-column="right"') == 2
    assert "进入恩洛斯" in html
