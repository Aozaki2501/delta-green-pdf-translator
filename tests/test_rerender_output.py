import json
from pathlib import Path

import pytest

from rerender_output import (
    infer_output_base,
    load_progress_translations,
    normalize_output_formats,
    rerender_outputs,
    rerender_selected_outputs,
)


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

    assert infer_output_base(str(progress), None) == str(tmp_path / "book_cn" / "book_cn")


def test_infer_output_base_does_not_double_nest(tmp_path):
    folder = tmp_path / "book_cn"
    progress = folder / "book_cn.progress.json"

    assert infer_output_base(str(progress), None) == str(folder / "book_cn")


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

    out = tmp_path / "book_cn" / "book_cn.md"
    assert written == [str(out)]
    assert "正文" in out.read_text(encoding="utf-8")


def test_normalize_output_formats_accepts_web_format_list():
    assert normalize_output_formats(["html", "word", "html"]) == ["html", "word"]


def test_normalize_output_formats_rejects_typeset_pdf():
    with pytest.raises(ValueError):
        normalize_output_formats(["typeset_pdf"])


def test_rerender_selected_outputs_writes_only_requested_formats(tmp_path, monkeypatch):
    progress = tmp_path / "book_cn.progress.json"
    progress.write_text(
        json.dumps({
            "translations": {
                "0": "正文。",
            }
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    calls = []

    def fake_html(translated_pages, html_output, title, **kwargs):
        calls.append(("html", html_output, kwargs.get("columns")))
        Path(html_output).write_text("<html></html>", encoding="utf-8")

    def fake_word(translated_pages, docx_output, title, **kwargs):
        calls.append(("word", docx_output, kwargs.get("body_font_size")))
        Path(docx_output).write_bytes(b"docx")

    monkeypatch.setattr("rerender_output.write_html_output", fake_html)
    monkeypatch.setattr("rerender_output.write_word_output", fake_word)
    monkeypatch.setattr("rerender_output.HAS_DOCX", True)

    written = rerender_selected_outputs(
        progress_path=str(progress),
        output_formats=["html", "word"],
        columns=1,
        body_font_size=10.5,
    )

    assert [Path(path).suffix for path in written] == [".html", ".docx"]
    assert calls == [
        ("html", str(tmp_path / "book_cn" / "book_cn.html"), 1),
        ("word", str(tmp_path / "book_cn" / "book_cn.docx"), 10.5),
    ]


def test_rerender_selected_outputs_exposes_export_failure(tmp_path, monkeypatch):
    progress = tmp_path / "book_cn.progress.json"
    progress.write_text(
        json.dumps({"translations": {"0": "正文。"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    def broken_html(*args, **kwargs):
        raise RuntimeError("html failed")

    monkeypatch.setattr("rerender_output.write_html_output", broken_html)

    with pytest.raises(RuntimeError, match="html failed"):
        rerender_selected_outputs(
            progress_path=str(progress),
            output_formats=["html"],
        )
