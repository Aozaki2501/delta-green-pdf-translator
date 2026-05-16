from exporters._shared import _clean_translated_block


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
