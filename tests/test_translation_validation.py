import pytest

from core.translation_validation import (
    contains_elision_placeholder,
    contains_japanese_kana,
    contains_prompt_leak,
    ensure_no_elision_placeholder,
    ensure_no_japanese_kana,
    ensure_no_prompt_leak,
)


def test_detects_prompt_leak_like_user_screenshot():
    text = (
        "您是专业的TRPG翻译，正在处理Delta Green原始资料。"
        "翻译规则包括：1. 严格遵循术语表；2. 保留未翻译的游戏术语；"
        "3. 输出Markdown；4. 专业流畅中文，保持恐怖氛围。"
    )

    assert contains_prompt_leak(text) is True
    with pytest.raises(ValueError, match="内部翻译指令"):
        ensure_no_prompt_leak(text)


def test_allows_normal_translation_text():
    text = "调查员走进档案室，墙上的照片已经泛黄。"

    assert contains_prompt_leak(text) is False
    ensure_no_prompt_leak(text)


def test_detects_japanese_output_returned_unchanged():
    text = "探索者がよく知っている先生が2人いる。"

    assert contains_japanese_kana(text) is True
    with pytest.raises(ValueError, match="日文假名"):
        ensure_no_japanese_kana(text)


def test_allows_chinese_translation_with_japanese_names_transliterated():
    text = "调查员熟悉两位老师：凯瑟琳与川崎克也。"

    assert contains_japanese_kana(text) is False
    ensure_no_japanese_kana(text)


def test_detects_elision_placeholder_from_split_sentence():
    """Observed in a real artifact when one sentence spanned two columns."""
    text = "《新时代》的触发事件是[...]之间的信任丧失，"

    assert contains_elision_placeholder(text) is True
    with pytest.raises(ValueError, match="省略占位符"):
        ensure_no_elision_placeholder(text)


@pytest.mark.parametrize("text", [
    "触发事件是（……）之间的信任丧失",
    "触发事件是【…】之间的信任丧失",
    "触发事件是(...)之间的信任丧失",
    "触发事件是[省略部分内容]之间的信任丧失",
])
def test_detects_elision_placeholder_variants(text):
    assert contains_elision_placeholder(text) is True


@pytest.mark.parametrize("text", [
    "调查员沉默了很久……然后开口。",
    "他低声说：“别过去……”",
    "[BLOCK p0001_r0001_b0001]",
    "伤害为1D6[穿甲]，射程30米。",
    "参见第7页的“觉醒”一节。",
])
def test_allows_legitimate_brackets_and_ellipses(text):
    assert contains_elision_placeholder(text) is False
    ensure_no_elision_placeholder(text)
