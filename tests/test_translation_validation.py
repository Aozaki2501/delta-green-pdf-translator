import pytest

from core.translation_validation import contains_prompt_leak, ensure_no_prompt_leak


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
