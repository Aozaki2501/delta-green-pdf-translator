import pytest

from core.glossary import load_glossary
from webui.glossary_review import (
    ACTION_ADD,
    ACTION_IGNORE,
    ACTION_UPDATE,
    glossary_candidates_to_review_rows,
    merge_reviewed_glossary,
    write_reviewed_glossary,
)


class Candidate:
    def __init__(self, term, count, pages):
        self.term = term
        self.count = count
        self.pages = pages


def test_review_rows_default_to_ignore():
    rows = glossary_candidates_to_review_rows([Candidate("Delta Green", 3, [0, 2])])

    assert rows == [
        {
            "动作": ACTION_IGNORE,
            "中文译名": "",
            "英文原名": "Delta Green",
            "出现次数": 3,
            "位置": "1, 3",
        }
    ]


def test_merge_reviewed_glossary_add_update_ignore():
    merged = merge_reviewed_glossary(
        {"Delta Green": "绿色三角洲"},
        [
            {"动作": ACTION_IGNORE, "英文原名": "Ignored", "中文译名": ""},
            {"动作": ACTION_ADD, "英文原名": "The Program", "中文译名": "项目组"},
            {"动作": ACTION_UPDATE, "英文原名": "Delta Green", "中文译名": "三角洲绿"},
        ],
    )

    assert merged == {"Delta Green": "三角洲绿", "The Program": "项目组"}


def test_merge_reviewed_glossary_rejects_add_existing():
    with pytest.raises(ValueError, match="已存在"):
        merge_reviewed_glossary(
            {"Delta Green": "绿色三角洲"},
            [{"动作": ACTION_ADD, "英文原名": "Delta Green", "中文译名": "三角洲绿"}],
        )


def test_merge_reviewed_glossary_rejects_update_missing():
    with pytest.raises(ValueError, match="不存在"):
        merge_reviewed_glossary(
            {},
            [{"动作": ACTION_UPDATE, "英文原名": "Delta Green", "中文译名": "绿色三角洲"}],
        )


def test_merge_reviewed_glossary_requires_chinese_for_changes():
    with pytest.raises(ValueError, match="中文译名不能为空"):
        merge_reviewed_glossary(
            {},
            [{"动作": ACTION_ADD, "英文原名": "Delta Green", "中文译名": ""}],
        )


def test_write_reviewed_glossary_round_trips(tmp_path):
    output_path = tmp_path / "reviewed.tsv"

    write_reviewed_glossary(
        {"Delta Green": "绿色三角洲"},
        [{"动作": ACTION_ADD, "英文原名": "The Program", "中文译名": "项目组"}],
        output_path,
    )

    assert load_glossary(str(output_path)) == {
        "Delta Green": "绿色三角洲",
        "The Program": "项目组",
    }

