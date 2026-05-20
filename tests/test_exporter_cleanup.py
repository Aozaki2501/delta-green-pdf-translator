from exporters._shared import (
    _clean_translated_block,
    _is_plain_heading_line,
    _translation_blocks,
    paginate_translated_blocks,
)
from exporters.markdown import _format_markdown_block
from exporters.html import _html_block
from exporters.word import _split_card_segments


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


def test_html_renders_stat_and_image_blocks():
    html = _html_block(
        "[STAT_BLOCK]\nRobyn Bullock\nSTR 11 CON 10 DEX 9 INT 14 POW 16 CHA 13\n[/STAT_BLOCK]\n"
        "[IMAGE]\nIllustration placeholder\n[/IMAGE]"
    )

    assert 'class="stat-block"' in html
    assert 'class="image-placeholder"' in html


def test_html_uses_extracted_image_asset():
    html = _html_block(
        "[IMAGE]\nIllustration placeholder\n[/IMAGE]",
        image_paths=["output/assets/page.png"],
        image_cursor=[0],
        html_output="output/book.html",
    )

    assert 'class="source-image"' in html
    assert 'src="assets/page.png"' in html


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
