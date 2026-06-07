from pathlib import Path

from webui.runtime import (
    contains_cjk,
    existing_output_files,
    format_duration,
    make_html_asset_bundle,
    safe_filename_stem,
)
from webui.theme import render_app_theme


def test_safe_filename_stem_keeps_readable_name():
    assert safe_filename_stem("Delta Green: God's Law.pdf") == "Delta_Green_God_s_Law"
    assert safe_filename_stem("???.pdf") == "document"


def test_format_duration_compacts_seconds():
    assert format_duration(None) == "估算中"
    assert format_duration(59) == "59s"
    assert format_duration(61) == "1m 1s"
    assert format_duration(3661) == "1h 1m"


def test_contains_cjk_detects_chinese_text():
    assert contains_cjk("正文 mixed text") is True
    assert contains_cjk("plain text") is False


def test_existing_output_files_can_filter_internal_files(tmp_path):
    html = tmp_path / "book.html"
    progress = tmp_path / "book.progress.json"
    missing = tmp_path / "missing.md"
    html.write_text("<html></html>", encoding="utf-8")
    progress.write_text("{}", encoding="utf-8")

    assert existing_output_files([html, progress, missing]) == [str(html), str(progress)]
    assert existing_output_files([html, progress], final_only=True) == [str(html)]


def test_make_html_asset_bundle_includes_html_and_assets(tmp_path):
    html = tmp_path / "book.html"
    assets = tmp_path / "assets"
    nested = assets / "img"
    nested.mkdir(parents=True)
    html.write_text("<html></html>", encoding="utf-8")
    (nested / "p1.png").write_bytes(b"png")

    bundle = make_html_asset_bundle(html)

    assert bundle == str(tmp_path / "book.html_assets.zip")
    assert Path(bundle).exists()


def test_render_app_theme_calls_streamlit_markdown(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "webui.theme.st.markdown",
        lambda body, unsafe_allow_html=False: calls.append((body, unsafe_allow_html)),
    )

    render_app_theme()

    assert calls
    assert "<style>" in calls[0][0]
    assert calls[0][1] is True
