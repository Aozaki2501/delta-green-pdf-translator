import pytest

from core.docx_extractor import DocxBlock
from core.md_extractor import MdBlock
from translate_docx import _marked_docx_group_text, _parse_marked_docx_translation
from translate_md import _marked_md_group_text, _parse_marked_md_translation


def test_docx_marked_group_round_trip():
    group = [
        DocxBlock(index=1, block_type="paragraph", text="First paragraph.", translatable=True),
        DocxBlock(index=2, block_type="paragraph", text="Second paragraph.", translatable=True),
    ]

    source = _marked_docx_group_text(group)
    assert "[BLOCK 1]" in source
    parsed = _parse_marked_docx_translation(
        "[BLOCK 1]\n第一段。\n[/BLOCK 1]\n\n[BLOCK 2]\n第二段。\n[/BLOCK 2]",
        group,
    )

    assert parsed == {1: "第一段。", 2: "第二段。"}


def test_docx_marked_group_rejects_missing_block():
    """When one block is missing from a multi-block group, only the found block is returned."""
    group = [
        DocxBlock(index=1, block_type="paragraph", text="First paragraph.", translatable=True),
        DocxBlock(index=2, block_type="paragraph", text="Second paragraph.", translatable=True),
    ]

    # Now returns partial results instead of raising
    parsed = _parse_marked_docx_translation("[BLOCK 1]\n第一段。\n[/BLOCK 1]", group)
    assert parsed == {1: "第一段。"}
    assert 2 not in parsed


def test_docx_single_block_accepts_plain_translation():
    group = [DocxBlock(index=9, block_type="paragraph", text="First paragraph.", translatable=True)]

    parsed = _parse_marked_docx_translation("第一段。", group)

    assert parsed == {9: "第一段。"}


def test_markdown_marked_group_round_trip():
    group = [
        MdBlock(index=3, block_type="paragraph", content="Alpha", text="Alpha", translatable=True),
        MdBlock(index=4, block_type="paragraph", content="Beta", text="Beta", translatable=True),
    ]

    source = _marked_md_group_text(group)
    assert "[BLOCK 3]" in source
    parsed = _parse_marked_md_translation(
        "[BLOCK 3]\n甲\n[/BLOCK 3]\n\n[BLOCK 4]\n乙\n[/BLOCK 4]",
        group,
    )

    assert parsed == {3: "甲", 4: "乙"}


def test_markdown_single_block_accepts_plain_translation():
    """Single-block group accepts plain text without BLOCK markers."""
    group = [MdBlock(index=5, block_type="paragraph", content="Hello", text="Hello", translatable=True)]

    parsed = _parse_marked_md_translation("你好", group)
    assert parsed == {5: "你好"}


def test_markdown_single_heading_strips_prefix():
    """Single heading block strips # prefix that AI might add."""
    group = [MdBlock(index=10, block_type="heading", content="# Weather", text="Weather", translatable=True)]

    parsed = _parse_marked_md_translation("# 天气", group)
    assert parsed == {10: "天气"}


def test_markdown_marked_group_rejects_extra_block():
    """Extra blocks not in the expected list are silently ignored."""
    group = [MdBlock(index=3, block_type="paragraph", content="Alpha", text="Alpha", translatable=True)]

    # Now extra blocks are filtered out instead of raising
    parsed = _parse_marked_md_translation(
        "[BLOCK 3]\n甲\n[/BLOCK 3]\n\n[BLOCK 9]\n多余\n[/BLOCK 9]",
        group,
    )
    assert parsed == {3: "甲"}
    assert 9 not in parsed


def test_markdown_completely_unparseable_raises():
    """When no BLOCK markers can be found at all in a multi-block group, ValueError is raised."""
    group = [
        MdBlock(index=3, block_type="paragraph", content="Alpha", text="Alpha", translatable=True),
        MdBlock(index=4, block_type="paragraph", content="Beta", text="Beta", translatable=True),
    ]

    with pytest.raises(ValueError, match="完全无法解析"):
        _parse_marked_md_translation("这是一段没有任何标记的翻译文本", group)


def test_docx_completely_unparseable_raises():
    """When no BLOCK markers can be found at all for multi-block group, ValueError is raised."""
    group = [
        DocxBlock(index=1, block_type="paragraph", text="First.", translatable=True),
        DocxBlock(index=2, block_type="paragraph", text="Second.", translatable=True),
    ]

    with pytest.raises(ValueError, match="完全无法解析"):
        _parse_marked_docx_translation("这是一段没有任何标记的翻译文本", group)


def test_markdown_partial_success():
    """When some blocks are found but others missing, returns partial results."""
    group = [
        MdBlock(index=5, block_type="paragraph", content="A", text="A", translatable=True),
        MdBlock(index=6, block_type="paragraph", content="B", text="B", translatable=True),
        MdBlock(index=7, block_type="paragraph", content="C", text="C", translatable=True),
    ]

    # Only blocks 5 and 7 are returned by the AI
    parsed = _parse_marked_md_translation(
        "[BLOCK 5]\n甲\n[/BLOCK 5]\n\n[BLOCK 7]\n丙\n[/BLOCK 7]",
        group,
    )
    assert parsed == {5: "甲", 7: "丙"}
    assert 6 not in parsed


def test_docx_empty_block_filtered():
    """Empty translated blocks are filtered out."""
    group = [
        DocxBlock(index=1, block_type="paragraph", text="First.", translatable=True),
        DocxBlock(index=2, block_type="paragraph", text="Second.", translatable=True),
    ]

    # Block 2 has empty content
    parsed = _parse_marked_docx_translation(
        "[BLOCK 1]\n第一段。\n[/BLOCK 1]\n\n[BLOCK 2]\n\n[/BLOCK 2]",
        group,
    )
    assert parsed == {1: "第一段。"}
    assert 2 not in parsed


def test_markdown_rejects_prompt_leak():
    group = [MdBlock(index=5, block_type="paragraph", content="Hello", text="Hello", translatable=True)]

    with pytest.raises(ValueError, match="内部翻译指令"):
        _parse_marked_md_translation(
            "您是专业的TRPG翻译，翻译规则包括：严格遵循术语表，输出Markdown。",
            group,
        )


def test_docx_rejects_prompt_leak():
    group = [DocxBlock(index=1, block_type="paragraph", text="First.", translatable=True)]

    with pytest.raises(ValueError, match="内部翻译指令"):
        _parse_marked_docx_translation(
            "您是专业的TRPG翻译，翻译规则包括：严格遵循术语表，输出Markdown。",
            group,
        )
