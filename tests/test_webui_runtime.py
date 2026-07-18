from pathlib import Path

import zipfile

from webui.runtime import (
    contains_cjk,
    existing_output_files,
    format_duration,
    install_playwright_chromium,
    make_html_asset_bundle,
    playwright_chromium_installed,
    safe_filename_stem,
    save_uploaded_file_once,
)
from webui.theme import GOVERNMENT_THEME_OVERRIDE_CSS, render_app_theme, render_workstation_effects


def test_safe_filename_stem_keeps_readable_name():
    assert safe_filename_stem("Delta Green: God's Law.pdf") == "Delta_Green_God_s_Law"
    assert safe_filename_stem("???.pdf") == "document"


def test_safe_filename_stem_truncates_long_names():
    stem = safe_filename_stem("The Conspiracy against the Human Race " + "x" * 200 + ".pdf")

    assert stem.startswith("The_Conspiracy_against_the_Human_Race")
    assert len(stem) == 96


def test_format_duration_compacts_seconds():
    assert format_duration(None) == "估算中"
    assert format_duration(59) == "59s"
    assert format_duration(61) == "1m 1s"
    assert format_duration(3661) == "1h 1m"


def test_contains_cjk_detects_chinese_text():
    assert contains_cjk("正文 mixed text") is True
    assert contains_cjk("plain text") is False


def test_save_uploaded_file_once_reuses_same_content(tmp_path):
    class Upload:
        name = "Book.pdf"

        def __init__(self, data):
            self._data = data

        def getvalue(self):
            return self._data

    first = save_uploaded_file_once(Upload(b"same"), tmp_path)
    second = save_uploaded_file_once(Upload(b"same"), tmp_path)
    third = save_uploaded_file_once(Upload(b"different"), tmp_path)

    assert first == second
    assert third != first
    assert len(list(tmp_path.glob("*.pdf"))) == 2


def test_save_uploaded_file_once_keeps_path_short_for_long_names(tmp_path):
    class Upload:
        name = "The Conspiracy against the Human Race " + "x" * 220 + ".pdf"

        def getvalue(self):
            return b"book"

    saved = save_uploaded_file_once(Upload(), tmp_path)

    assert saved.exists()
    assert len(saved.name) < 180


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


def test_make_html_asset_bundle_can_include_only_referenced_assets(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "used.svg").write_text("<svg/>", encoding="utf-8")
    (assets / "unused.png").write_bytes(b"unused")
    html = tmp_path / "book_typeset.html"
    html.write_text(
        '<img src="assets/used.svg">',
        encoding="utf-8",
    )

    bundle = make_html_asset_bundle(html, referenced_only=True)

    with zipfile.ZipFile(bundle) as archive:
        assert archive.namelist() == ["book_typeset.html", "assets/used.svg"]


def test_typeset_formats_have_distinct_html_label_and_exclusive_branch():
    # Importing the Streamlit module is intentionally limited to this pure
    # format-policy check; no page rendering or widget text is asserted.
    import app

    assert app.OUTPUT_FORMAT_LABELS["typeset_html"] == "高保真 HTML（_typeset）"
    assert app.OUTPUT_FORMAT_LABELS["typeset_reading_html"] == "图文阅读 HTML（_reading）"
    assert app._typeset_formats_selected(["typeset_html"]) is True
    assert app._typeset_formats_selected(["typeset_reading_html"]) is True
    assert app._typeset_formats_selected(["typeset_pdf"]) is True
    assert app._typeset_formats_are_exclusive(
        ["typeset_html", "typeset_reading_html", "typeset_pdf"]
    ) is True
    assert app._typeset_formats_are_exclusive(["typeset_html", "html"]) is False


def test_playwright_chromium_installed_checks_executable_path(tmp_path, monkeypatch):
    browser = tmp_path / "chrome.exe"
    browser.write_bytes(b"")
    monkeypatch.setattr(
        "webui.runtime._playwright_chromium_executable_path",
        lambda: str(browser),
    )
    assert playwright_chromium_installed() is True

    monkeypatch.setattr(
        "webui.runtime._playwright_chromium_executable_path",
        lambda: str(tmp_path / "missing.exe"),
    )
    assert playwright_chromium_installed() is False


def test_install_playwright_chromium_streams_progress(monkeypatch):
    events = []
    commands = []

    class FakeProcess:
        stdout = iter(["Downloading Chromium 45%\n", "Download complete\n"])

        def wait(self):
            return 0

    def fake_popen(command, **kwargs):
        commands.append(command)
        return FakeProcess()

    monkeypatch.setattr("webui.runtime.subprocess.Popen", fake_popen)
    monkeypatch.setattr("webui.runtime.playwright_chromium_installed", lambda: True)

    ok, logs = install_playwright_chromium(
        progress_callback=lambda message, percent: events.append((message, percent)),
        python_executable="C:/Python/python.exe",
    )

    assert ok is True
    assert commands == [["C:/Python/python.exe", "-m", "playwright", "install", "chromium"]]
    assert logs == ["Downloading Chromium 45%", "Download complete"]
    assert events[0] == ("准备加载浏览器内核插件…", 0)
    assert ("Downloading Chromium 45%", 45) in events
    assert events[-1] == ("浏览器内核插件加载完成。", 100)


def test_install_playwright_chromium_reports_missing_browser_after_install(monkeypatch):
    events = []

    class FakeProcess:
        stdout = iter(["Download complete\n"])

        def wait(self):
            return 0

    monkeypatch.setattr("webui.runtime.subprocess.Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr("webui.runtime.playwright_chromium_installed", lambda: False)

    ok, logs = install_playwright_chromium(
        progress_callback=lambda message, percent: events.append((message, percent)),
        python_executable="C:/Python/python.exe",
    )

    assert ok is False
    assert logs[-1] == "安装命令已完成，但没有检测到 Chromium 内核。"
    assert events[-1] == ("安装命令已完成，但没有检测到 Chromium 内核。", None)


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


def test_render_app_theme_supports_office_mode(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "webui.theme.st.markdown",
        lambda body, unsafe_allow_html=False: calls.append((body, unsafe_allow_html)),
    )

    render_app_theme(office_mode=True)

    assert calls
    assert "--bg: #f6f7f9" in calls[0][0]
    assert "绝密" not in calls[0][0]
    assert calls[0][1] is True


def test_render_workstation_effects_supports_office_mode(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "webui.theme.st.markdown",
        lambda body, unsafe_allow_html=False: calls.append((body, unsafe_allow_html)),
    )

    render_workstation_effects(office_mode=True)

    assert calls
    assert ".dossier-card" in calls[0][0]
    assert "传输已授权" not in calls[0][0]
    assert calls[0][1] is True


def test_government_theme_keeps_uploader_buttons_and_multiselect_internals_readable():
    assert 'div[data-testid="stFileUploader"] button::after' in GOVERNMENT_THEME_OVERRIDE_CSS
    assert 'content: none !important;' in GOVERNMENT_THEME_OVERRIDE_CSS
    assert 'content: "选择文件" !important;' in GOVERNMENT_THEME_OVERRIDE_CSS
    assert '[data-baseweb="select"] > div:not([data-baseweb="tag"])' in GOVERNMENT_THEME_OVERRIDE_CSS
    assert ".term-scan-status" in GOVERNMENT_THEME_OVERRIDE_CSS
