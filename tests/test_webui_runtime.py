from pathlib import Path

from webui.runtime import (
    contains_cjk,
    existing_output_files,
    format_duration,
    install_playwright_chromium,
    make_html_asset_bundle,
    playwright_chromium_installed,
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
