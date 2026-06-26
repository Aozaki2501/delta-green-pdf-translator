from exporters._shared import (
    _clean_translated_block,
    _display_title,
    _is_plain_heading_line,
    _normalize_export_line,
    _translation_blocks,
    _without_image_blocks,
    attach_running_headers,
    paginate_translated_blocks,
)
from exporters.markdown import _format_markdown_block
from exporters.html import _html_block, write_html_output
from exporters.word import _split_card_segments, _image_asset_path, _image_asset_placement


def test_soft_wrapped_chinese_lines_are_merged():
    text = _clean_translated_block("即绿色三角洲仍是一个官方组织，而\n庄严会则不是。")

    assert text == "即绿色三角洲仍是一个官方组织，而庄严会则不是。"


def test_card_title_stays_separate_when_soft_lines_merge():
    text = _clean_translated_block(
        "[CARD]\n"
        "球体之谜\n"
        "这艘完好的太空飞船正在发出一种人\n"
        "类科学无法探测到的信号。\n"
        "[/CARD]"
    )

    assert "球体之谜\n" in text
    assert "人类科学" in text


def test_full_width_title_starts_new_reading_page():
    pages = paginate_translated_blocks([
        (0, "前一页正文很多内容。"),
        (1, "[FULL_WIDTH_TITLE]\n# 香盖虫族\n[/FULL_WIDTH_TITLE]\n\n新的正文。"),
    ], min_chars=1, max_chars=500)

    assert len(pages) == 2
    assert pages[1]["blocks"][0]["text"].startswith("[FULL_WIDTH_TITLE]")


def test_display_title_prefers_first_heading_in_reading_order():
    reading_pages = [
        {
            "layout": "columns",
            "blocks": [{"text": "### Scenario: A Yellow and Unpleasant Land\n\nBody."}],
        },
        {
            "layout": "full_title",
            "blocks": [{"text": "[FULL_WIDTH_TITLE]\n# The Kingdom of Yellow: Background\n[/FULL_WIDTH_TITLE]"}],
        },
    ]

    assert _display_title("Apocthulhu Core Rules", reading_pages) == "Scenario: A Yellow and Unpleasant Land"


def test_html_renders_full_width_title():
    html = _html_block("[FULL_WIDTH_TITLE]\n# 香盖虫族\n副标题\n[/FULL_WIDTH_TITLE]")

    assert 'class="full-width-title"' in html
    assert "<h1>香盖虫族</h1>" in html
    assert "<p>副标题</p>" in html


def test_word_segments_full_width_title():
    segments = _split_card_segments("[FULL_WIDTH_TITLE]\n# 香盖虫族\n[/FULL_WIDTH_TITLE]\n\n正文")

    assert segments[0] == ("full_title", "# 香盖虫族")
    assert segments[1] == ("normal", "正文")


def test_stat_and_image_blocks_stay_structural():
    pages = paginate_translated_blocks([
        (0, "[STAT_BLOCK]\nRobyn Bullock\nSTR 11 CON 10 DEX 9 INT 14 POW 16 CHA 13\n[/STAT_BLOCK]\n\n[IMAGE]\nIllustration placeholder\n[/IMAGE]"),
    ], min_chars=1, max_chars=500)

    texts = [block["text"] for block in pages[0]["blocks"]]
    assert texts[0].startswith("[STAT_BLOCK]")
    assert texts[1].startswith("[IMAGE]")


def test_reading_outputs_can_remove_image_blocks():
    pages = _without_image_blocks([
        (0, "前文。\n\n[IMAGE]\nIllustration placeholder\n[/IMAGE]\n\n后文。"),
    ])

    assert pages == [(0, "前文。\n\n后文。")]


def test_removing_image_blocks_rejects_unclosed_marker():
    try:
        _without_image_blocks([(0, "前文。\n\n[IMAGE]\nIllustration placeholder")])
    except ValueError as exc:
        assert "未结束" in str(exc)
    else:
        raise AssertionError("未结束的图片标记应直接报错")


def test_html_renders_stat_and_image_blocks():
    html = _html_block(
        "[STAT_BLOCK]\nRobyn Bullock\nSTR 11 CON 10 DEX 9 INT 14 POW 16 CHA 13\n[/STAT_BLOCK]\n"
        "[IMAGE]\nIllustration placeholder\n[/IMAGE]"
    )

    assert 'class="stat-block"' in html
    assert 'class="image-placeholder"' in html


def test_html_stat_block_strips_markdown_heading_prefix():
    html = _html_block(
        "[STAT_BLOCK]\n#### Sewer Angel\nSTR 11 CON 10 DEX 9 INT 14 POW 16 CHA 13\n[/STAT_BLOCK]"
    )

    assert "<h3>Sewer Angel</h3>" in html
    assert "#### Sewer Angel" not in html


def test_html_uses_extracted_image_asset():
    html = _html_block(
        "[IMAGE]\nIllustration placeholder\n[/IMAGE]",
        image_paths=["output/assets/page.png"],
        image_cursor=[0],
        html_output="output/book.html",
    )

    assert 'class="source-image source-image-full"' in html
    assert 'src="assets/page.png"' in html


def test_html_uses_image_asset_placement():
    html = _html_block(
        "[IMAGE]\nIllustration placeholder\n[/IMAGE]",
        image_paths=[{"path": "output/assets/page.png", "placement": "right"}],
        image_cursor=[0],
        html_output="output/book.html",
    )

    assert 'class="source-image source-image-right"' in html
    assert 'src="assets/page.png"' in html


def test_markdown_uses_image_asset_dict_path():
    markdown = _format_markdown_block(
        "[IMAGE]\nIllustration placeholder\n[/IMAGE]",
        image_paths=[{"path": "output/assets/page.png", "placement": "left"}],
        image_cursor=[0],
        md_output="output/book.md",
    )

    assert "![图片](assets/page.png)" in markdown


def test_word_image_asset_helpers_accept_dict_and_old_path():
    asset = {"path": "output/assets/page.png", "placement": "left"}

    assert _image_asset_path(asset) == "output/assets/page.png"
    assert _image_asset_placement(asset) == "left"
    assert _image_asset_path("output/assets/page.png") == "output/assets/page.png"
    assert _image_asset_placement("output/assets/page.png") == "full"


def test_word_segments_stat_and_image_blocks():
    segments = _split_card_segments(
        "[STAT_BLOCK]\nRobyn Bullock\nSTR 11 CON 10\n[/STAT_BLOCK]\n"
        "[IMAGE]\nIllustration placeholder\n[/IMAGE]"
    )

    assert segments[0][0] == "stat"
    assert segments[1] == ("image", "Illustration placeholder")


def test_localized_card_markers_stay_structural():
    text = "[卡片]\n姓名\n职位\n背景\n[/卡片]"

    html = _html_block(text)
    markdown = _format_markdown_block(text)
    segments = _split_card_segments(text)

    assert 'class="handout-card"' in html
    assert "<h2>姓名</h2>" not in html
    assert "[CARD]" in markdown
    assert "[卡片]" not in markdown
    assert segments == [("card", "姓名\n职位\n背景")]


def test_short_chinese_fields_are_not_promoted_to_headings():
    assert not _is_plain_heading_line("姓名")
    assert not _is_plain_heading_line("达娜·加斯蒂诺")


def test_card_list_lines_are_not_collapsed():
    text = _clean_translated_block(
        "[CARD]\n"
        "生态乌托邦员工\n"
        "姓名\n"
        "职位\n"
        "背景\n"
        "基斯·巴斯\n"
        "特约编辑\n"
        "邋遢的社会主义者\n"
        "[/CARD]"
    )

    assert "姓名\n职位\n背景" in text
    assert "姓名职位背景" not in text


def test_cross_page_sentence_continuation_moves_before_leading_card():
    blocks = _translation_blocks([
        (0, "菲奥娜愿意自我介绍。她并不"),
        (1, "[CARD]\n>>生态乌托邦员工\n姓名\n职位\n背景\n[/CARD]\n\n她不会单独见他们，尤其当特工不止一名时更是如此。"),
    ])

    texts = [block["text"] for block in blocks]

    assert texts[0] == "菲奥娜愿意自我介绍。"
    assert texts[1].startswith("她并不会单独见他们")
    assert texts[2].startswith("[CARD]")


def test_stat_block_line_breaks_are_preserved():
    text = _clean_translated_block(
        "[STAT_BLOCK]\n"
        "罗宾·布洛克\n"
        "STR 11 CON 10 DEX 9 INT 14 POW 16 CHA 13\n"
        "HP 11 WP 17 SAN 65\n"
        "[/STAT_BLOCK]"
    )

    assert "布洛克\nSTR 11" in text
    assert "CHA 13\nHP 11" in text


def test_non_stat_marker_can_fall_back_to_card_rendering():
    html = _html_block(
        "[STAT_BLOCK]\n"
        "关于心灵仪式\n"
        "这是一段很长的规则说明，提到了体质、敏捷、智力和魅力。\n"
        "[/STAT_BLOCK]"
    )

    assert 'class="handout-card"' in html
    assert 'class="stat-block"' not in html


def test_html_renders_quote_table_inside_card():
    html = _html_block(
        ">> ## 特纳前进作战基地人员\n"
        ">> | 姓名 | 职务 |\n"
        ">> |---|---|\n"
        ">> | 拜尔斯 | 指挥官 |"
    )

    assert 'class="handout-card"' in html
    assert 'class="aid-table card-table"' in html
    assert "| 姓名 | 职务 |" not in html


def test_html_does_not_turn_pipe_fragments_into_tables():
    html = _html_block(
        "[CARD]\n"
        "| Tip |\n"
        "| --- |\n"
        "Body text.\n"
        "[/CARD]\n\n"
        "| Loose row |\n"
        "More text."
    )

    assert 'class="aid-table' not in html
    assert "<h3>Tip</h3>" in html
    assert "---" not in html
    assert "Loose row" in html


def test_word_segments_require_markdown_table_separator():
    segments = _split_card_segments(
        "| Tip |\n"
        "| --- |\n"
        "Body text.\n\n"
        "| Name | Role |\n"
        "|---|---|\n"
        "| Bell | Commander |"
    )

    assert segments[0] == ("normal", "| Tip |\n| --- |\nBody text.")
    assert segments[1][0] == "table"


def test_html_renders_guillemet_lines_as_list():
    html = _html_block("» 第一项\n» 第二项")

    assert "<ul>" in html
    assert "<li>第一项</li>" in html
    assert "<li>第二项</li>" in html


def test_narrative_markdown_heading_is_demoted_to_paragraph():
    line = _normalize_export_line("#### 随着美国仇恨暴力事件的增加")

    assert line == "随着美国仇恨暴力事件的增加"
    assert "<h4" not in _html_block("#### 随着美国仇恨暴力事件的增加")


def test_damaged_heading_prefix_is_removed_or_dropped():
    assert _normalize_export_line("### ADAM GAUNUf- RD]N") == ""
    assert _normalize_export_line("### GHUNTL-网络；为了保持一致性，他继续随身携带公文包。") == (
        "为了保持一致性，他继续随身携带公文包。"
    )


def test_damaged_heading_is_not_used_as_running_header():
    pages = [{
        "layout": "columns",
        "blocks": [{"text": "### GHUNTL-网络；为了保持一致性，他继续随身携带公文包。"}],
    }]

    attach_running_headers(pages, "See No Evil")

    assert "GHUNTL" not in pages[0]["running_header"]


def test_stat_number_heading_is_demoted_to_paragraph():
    html = _html_block("#### 11 INT")

    assert "<h4" not in html
    assert "<p>11 INT</p>" in html


def test_target_dossier_renders_as_card_in_html_and_word_segments():
    text = (
        "#### 目标档案\n\n"
        "**彼得·哈姆斯**。化名：无。\n"
        "年龄：76岁。职业：已退休。\n\n"
        "**岛屿**。\n"
        "后续正文。"
    )

    html = _html_block(text)
    segments = _split_card_segments(text)

    assert 'class="handout-card"' in html
    assert "彼得·哈姆斯" in html
    assert "岛屿" in html
    assert segments[0][0] == "card"
    assert "目标档案" in segments[0][1]
    assert segments[1][0] == "normal"
    assert "岛屿" in segments[1][1]


def test_standalone_dossier_entry_renders_as_card():
    text = "**彼得·哈姆斯**。化名：无。年龄：76岁。职业：已退休。外貌特征：白人男性。"

    html = _html_block(text)
    segments = _split_card_segments(text)

    assert 'class="handout-card"' in html
    assert segments[0][0] == "card"
    assert "彼得·哈姆斯" in segments[0][1]
    assert "化名" in segments[0][1]


def test_html_cover_is_compact(tmp_path):
    out = tmp_path / "book.html"

    write_html_output([(0, "正文。")], str(out), "See No Evil", min_chars=1, max_chars=1000)
    html = out.read_text(encoding="utf-8")

    assert ".sheet.cover" in html
    assert "min-height: 3.2in" in html


def test_html_includes_reading_mode_switcher(tmp_path):
    out = tmp_path / "book.html"

    write_html_output([(0, "正文。")], str(out), "See No Evil", min_chars=1, max_chars=1000)
    html = out.read_text(encoding="utf-8")

    assert 'class="reading-toolbar"' in html
    assert 'data-mode="screen"' in html
    assert 'data-mode="print"' in html
    assert 'data-mode="mobile"' in html
    assert "dg-html-reading-mode" in html


def test_html_reading_modes_have_mobile_and_print_rules(tmp_path):
    out = tmp_path / "book.html"

    write_html_output([(0, "正文。")], str(out), "See No Evil", min_chars=1, max_chars=1000)
    html = out.read_text(encoding="utf-8")

    assert "body.mode-mobile .content" in html
    assert "body.mode-mobile .sheet.three_columns .content" in html
    assert ".reading-toolbar {\n            display: none;" in html


def test_html_renders_toc_as_compact_rows():
    html = _html_block("[[TOC]]\n# Contents\n\n```toc\nChapter One ........ 12\nAppendix ----- 203\n```")

    assert '<div class="toc-card">' in html
    assert '<span class="toc-title">Chapter One</span>' in html
    assert '<span class="toc-page">12</span>' in html
    assert "```toc" not in html


def test_html_renders_inline_toc_fence_as_compact_rows():
    html = _html_block("# Contents```tocChapter One ........ 12\n```")

    assert "<h1>Contents</h1>" in html
    assert '<span class="toc-title">Chapter One</span>' in html
    assert "```toc" not in html


def test_html_toc_preserves_abbreviation_periods():
    html = _html_block("```toc\nM.O.S. ........ 13\nPlaying V.C. ........ 176\n```")

    assert '<span class="toc-title">M.O.S.</span>' in html
    assert '<span class="toc-title">Playing V.C.</span>' in html


def test_html_toc_strips_existing_leader_dots_from_title():
    html = _html_block("```toc\n起源........................................... ........ 8\n```")

    assert '<span class="toc-title">起源</span>' in html
    assert "起源................................" not in html


def test_toc_lines_are_not_soft_merged():
    text = _clean_translated_block(
        "[[TOC]]\n"
        "# Index\n"
        "```toc\n"
        "Introduction ........ 8\n"
        "Basic Training ........ 8\n"
        "```"
    )

    assert "Introduction ........ 8\nBasic Training ........ 8" in text


def test_display_title_prefers_primary_heading_over_filename():
    reading_pages = paginate_translated_blocks(
        [(0, "# 《卡利山口》\n\n正文。")],
        min_chars=1,
        max_chars=500,
    )

    assert _display_title(
        "Delta_Green_-_Kali_Ghati._Shane_Ivey_z-library.sk_1lib.sk_z-lib.sk",
        reading_pages,
    ) == "《卡利山口》"


def test_display_title_ignores_contents_heading():
    reading_pages = [{
        "layout": "toc",
        "blocks": [{"text": "[FULL_WIDTH_TITLE]\n# // 目录 // 《碎神者》 // 目录 //\n[/FULL_WIDTH_TITLE]"}],
    }, {
        "layout": "single",
        "blocks": [{"text": "# 前言"}],
    }, {
        "layout": "columns",
        "blocks": [{"text": "[FULL_WIDTH_TITLE]\n# // 《碎神者》 //\n[/FULL_WIDTH_TITLE]"}],
    }]

    assert _display_title(
        "Delta_Green_-_Iconoclasts._Adam_Scott_Glancy._Z-Library",
        reading_pages,
    ) == "《碎神者》"


def test_running_header_ignores_contents_heading():
    pages = [{
        "layout": "toc",
        "blocks": [{"text": "# // 目录 // 《碎神者》 // 目录 //"}],
    }, {
        "layout": "columns",
        "blocks": [{"text": "正文。"}],
    }]

    attach_running_headers(
        pages,
        "Delta_Green_-_Iconoclasts._Adam_Scott_Glancy._Z-Library",
    )

    assert pages[0]["running_header"] == "Iconoclasts"
    assert pages[1]["running_header"] == "Iconoclasts"
