from core.glossary_editor import (
    glossary_rows_to_tsv,
    parse_glossary_editor_text,
    read_glossary_editor_text,
)


def test_parse_glossary_editor_text_accepts_tabs_comments_and_spacing():
    text = """
# comment
绿色三角洲\tDelta Green
旧日支配者  Great Old One
"""
    rows, errors, warnings = parse_glossary_editor_text(text)

    assert errors == []
    assert warnings == []
    assert rows == [
        {"chinese": "绿色三角洲", "english": "Delta Green", "line": 3},
        {"chinese": "旧日支配者", "english": "Great Old One", "line": 4},
    ]


def test_parse_glossary_editor_text_blocks_bad_rows_and_duplicate_english():
    text = """
坏行
绿色三角洲\tDelta Green
绿三角\tdelta green
问?号\tBroken
"""
    rows, errors, warnings = parse_glossary_editor_text(text)

    assert len(rows) == 3
    assert warnings == []
    assert any("没有分成两列" in error for error in errors)
    assert any("英文原名重复" in error for error in errors)
    assert any("中文列含问号" in error for error in errors)


def test_parse_glossary_editor_text_warns_duplicate_chinese():
    text = "绿色三角洲\tDelta Green\n绿色三角洲\tDG\n"
    rows, errors, warnings = parse_glossary_editor_text(text)

    assert len(rows) == 2
    assert errors == []
    assert any("中文译名重复" in warning for warning in warnings)


def test_glossary_rows_to_tsv_normalizes_output():
    rows = [
        {"chinese": "绿色三角洲", "english": "Delta Green", "line": 1},
        {"chinese": "旧日支配者", "english": "Great Old One", "line": 2},
    ]

    assert glossary_rows_to_tsv(rows) == "绿色三角洲\tDelta Green\n旧日支配者\tGreat Old One\n"


def test_read_glossary_editor_text_returns_empty_for_missing_path(tmp_path):
    assert read_glossary_editor_text(tmp_path / "missing.tsv") == ""


def test_read_glossary_editor_text_reads_utf8(tmp_path):
    path = tmp_path / "glossary.tsv"
    path.write_text("绿色三角洲\tDelta Green\n", encoding="utf-8")

    assert read_glossary_editor_text(path) == "绿色三角洲\tDelta Green\n"
