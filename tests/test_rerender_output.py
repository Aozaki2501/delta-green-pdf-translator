import json

import pytest

from rerender_output import infer_output_base, load_progress_translations, rerender_outputs


def test_load_progress_translations_sorted(tmp_path):
    progress = tmp_path / "book.progress.json"
    progress.write_text(
        json.dumps({
            "translations": {
                "2": "page two",
                "0": "page zero",
                "1": "",
            }
        }),
        encoding="utf-8",
    )

    assert load_progress_translations(str(progress)) == [(0, "page zero"), (2, "page two")]


def test_load_progress_translations_rejects_empty(tmp_path):
    progress = tmp_path / "empty.progress.json"
    progress.write_text(json.dumps({"translations": {}}), encoding="utf-8")

    with pytest.raises(ValueError):
        load_progress_translations(str(progress))


def test_infer_output_base_strips_progress_suffix(tmp_path):
    progress = tmp_path / "book_cn.progress.json"

    assert infer_output_base(str(progress), None) == str(tmp_path / "book_cn")


def test_rerender_outputs_markdown(tmp_path):
    progress = tmp_path / "book_cn.progress.json"
    progress.write_text(
        json.dumps({
            "translations": {
                "0": "# 第一章\n\n正文。",
            }
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    written = rerender_outputs(
        progress_path=str(progress),
        output_format="markdown",
        title="book",
    )

    assert written == [str(tmp_path / "book_cn.md")]
    assert "正文" in (tmp_path / "book_cn.md").read_text(encoding="utf-8")
