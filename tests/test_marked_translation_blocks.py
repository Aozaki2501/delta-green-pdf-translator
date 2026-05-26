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
    group = [
        DocxBlock(index=1, block_type="paragraph", text="First paragraph.", translatable=True),
        DocxBlock(index=2, block_type="paragraph", text="Second paragraph.", translatable=True),
    ]

    with pytest.raises(ValueError, match="缺少块 2"):
        _parse_marked_docx_translation("[BLOCK 1]\n第一段。\n[/BLOCK 1]", group)


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


def test_markdown_marked_group_rejects_extra_block():
    group = [MdBlock(index=3, block_type="paragraph", content="Alpha", text="Alpha", translatable=True)]

    with pytest.raises(ValueError, match="多余块 9"):
        _parse_marked_md_translation(
            "[BLOCK 3]\n甲\n[/BLOCK 3]\n\n[BLOCK 9]\n多余\n[/BLOCK 9]",
            group,
        )
