from exporters._shared import _clean_translated_block, paginate_translated_blocks
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
