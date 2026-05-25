import json

import pymupdf

from core.layout_extractor import PDFLayoutExtractor
from core.layout_model import (
    LAYOUT_SCHEMA_VERSION,
    LayoutDocument,
    LayoutImageBlock,
    LayoutPage,
    LayoutSpan,
    LayoutTextBlock,
    layout_document_from_json,
)
from core.layout_translation import (
    LayoutTranslationProgress,
    apply_translation_map,
    block_source_text,
    export_translation_template,
    fit_translated_font_size,
    translate_layout_blocks,
    translate_layout_to_template,
    write_overflow_report,
)
from exporters.pdf_html import render_layout_html


def _sample_layout():
    return LayoutDocument(
        schema_version=LAYOUT_SCHEMA_VERSION,
        source_pdf="sample.pdf",
        page_count=1,
        pages=[
            LayoutPage(
                index=0,
                width=612,
                height=792,
                text_blocks=[
                    LayoutTextBlock(
                        id="p0001_t0000",
                        bbox=[72, 90, 180, 110],
                        spans=[
                            LayoutSpan(
                                id="p0001_t0000_s0000",
                                text="Delta Green",
                                bbox=[72, 90, 180, 110],
                                font="Times-Roman",
                                size=12,
                                color="#111111",
                                flags=0,
                            )
                        ],
                    )
                ],
                image_blocks=[
                    LayoutImageBlock(
                        id="p0001_i0000",
                        bbox=[200, 120, 300, 220],
                    )
                ],
            )
        ],
    )


def test_layout_document_json_round_trip():
    layout = _sample_layout()

    restored = layout_document_from_json(layout.to_json())

    assert restored.page_count == 1
    assert restored.pages[0].width == 612
    assert restored.pages[0].text_blocks[0].spans[0].text == "Delta Green"
    assert restored.pages[0].image_blocks[0].bbox == [200, 120, 300, 220]


def test_layout_document_rejects_wrong_page_count():
    data = _sample_layout().to_dict()
    data["page_count"] = 2

    try:
        layout_document_from_json(json.dumps(data))
    except ValueError as exc:
        assert "page_count" in str(exc)
    else:
        raise AssertionError("wrong page_count should fail")


def test_render_layout_html_uses_source_coordinates(tmp_path):
    out = tmp_path / "replica.html"

    render_layout_html(_sample_layout(), str(out), show_boxes=True)

    html = out.read_text(encoding="utf-8")
    assert 'class="replica-page"' in html
    assert 'data-span-id="p0001_t0000_s0000"' in html
    assert "left:96.000px;top:120.000px" in html
    assert "Delta Green" in html
    assert 'data-block-id="p0001_i0000"' in html


def test_translation_template_exports_block_text(tmp_path):
    out = tmp_path / "translations.json"

    export_translation_template(_sample_layout(), str(out))

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["source_pdf"] == "sample.pdf"
    assert data["translations"][0]["id"] == "p0001_t0000"
    assert data["translations"][0]["source_text"] == "Delta Green"
    assert data["translations"][0]["text"] == ""


def test_apply_translation_map_sets_block_translation():
    translated = apply_translation_map(
        _sample_layout(),
        {"p0001_t0000": "绿色三角洲"},
    )

    block = translated.pages[0].text_blocks[0]
    assert block.translated_text == "绿色三角洲"
    assert block_source_text(block) == "Delta Green"


def test_apply_translation_map_rejects_unknown_id():
    try:
        apply_translation_map(_sample_layout(), {"missing": "译文"})
    except ValueError as exc:
        assert "未知块 ID" in str(exc)
    else:
        raise AssertionError("unknown translation ID should fail")


def test_render_layout_html_uses_translated_block_when_present(tmp_path):
    out = tmp_path / "translated.html"
    translated = apply_translation_map(_sample_layout(), {"p0001_t0000": "绿色三角洲"})

    render_layout_html(translated, str(out), show_boxes=True)

    html = out.read_text(encoding="utf-8")
    assert 'class="replica-translation replica-translation-box"' in html
    assert 'data-base-font-px="' in html
    assert "replicaFitTranslations" in html
    assert "绿色三角洲" in html
    assert 'data-span-id="p0001_t0000_s0000"' not in html


def test_overflow_check_shrinks_translation_before_reporting(tmp_path):
    out = tmp_path / "overflow.md"
    block = LayoutTextBlock(
        id="p0001_t0000",
        bbox=[72, 90, 292, 170],
        spans=[
            LayoutSpan(
                id="p0001_t0000_s0000",
                text="Delta Green",
                bbox=[72, 90, 292, 110],
                font="Times-Roman",
                size=12,
                color="#111111",
                flags=0,
            )
        ],
        translated_text="translated text " * 30,
    )
    layout = LayoutDocument(
        schema_version=LAYOUT_SCHEMA_VERSION,
        source_pdf="sample.pdf",
        page_count=1,
        pages=[
            LayoutPage(
                index=0,
                width=612,
                height=792,
                text_blocks=[block],
                image_blocks=[],
            )
        ],
    )

    font_size, fits = fit_translated_font_size(block)
    issues = write_overflow_report(layout, str(out))

    assert fits is True
    assert font_size < 12
    assert issues == []


def test_overflow_report_detects_long_translation(tmp_path):
    out = tmp_path / "overflow.md"
    translated = apply_translation_map(
        _sample_layout(),
        {"p0001_t0000": "非常长的译文" * 80},
    )

    issues = write_overflow_report(translated, str(out))

    assert len(issues) == 1
    assert issues[0].block_id == "p0001_t0000"
    assert "发现 1 个溢出文本块" in out.read_text(encoding="utf-8")


def test_layout_extractor_merges_adjacent_body_lines(tmp_path):
    pdf_path = tmp_path / "lines.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=300)
    page.insert_text((50, 60), "First body line", fontsize=10)
    page.insert_text((50, 74), "Second body line", fontsize=10)
    page.insert_text((240, 60), "Right column line", fontsize=10)
    page.insert_text((50, 120), "Separate paragraph", fontsize=10)
    doc.save(pdf_path)
    doc.close()

    with PDFLayoutExtractor(str(pdf_path)) as extractor:
        layout = extractor.extract()

    blocks = layout.pages[0].text_blocks
    texts = [block_source_text(block) for block in blocks]
    assert "First body line\nSecond body line" in texts
    assert "Right column line" in texts
    assert "Separate paragraph" in texts


class FakeTranslator:
    def __init__(self):
        self.calls = 0

    def translate_chunk(self, text, page_num=None, prev_context="", cache=None):
        import re
        self.calls += 1
        parts = []
        for match in re.finditer(r"\[BLOCK ([^\]\s]+)\]\s*(.*?)\s*\[/BLOCK \1\]", text, re.DOTALL):
            block_id = match.group(1)
            source = match.group(2).strip()
            parts.append(f"[BLOCK {block_id}]\n译：{source}\n[/BLOCK {block_id}]")
        return "\n\n".join(parts)


def test_translate_layout_blocks_uses_block_progress(tmp_path):
    progress = LayoutTranslationProgress(str(tmp_path / "layout.progress.json"))
    translator = FakeTranslator()

    translations = translate_layout_blocks(_sample_layout(), translator, progress)

    assert translations == {"p0001_t0000": "译：Delta Green"}
    assert progress.get_translation("p0001_t0000") == "译：Delta Green"

    translator_again = FakeTranslator()
    translations_again = translate_layout_blocks(_sample_layout(), translator_again, progress)
    assert translations_again == {"p0001_t0000": "译：Delta Green"}
    assert translator_again.calls == 0


def test_translate_layout_to_template_reports_progress(tmp_path):
    calls = []

    translate_layout_to_template(
        _sample_layout(),
        FakeTranslator(),
        progress_file=str(tmp_path / "layout.progress.json"),
        output_path=str(tmp_path / "translations.json"),
        progress_callback=lambda done, total, block_id, success: calls.append(
            (done, total, block_id, success)
        ),
    )

    assert calls == [(1, 1, "p0001 / 1 块", True)]


class BrokenMarkerTranslator:
    def translate_chunk(self, text, page_num=None, prev_context="", cache=None):
        return "没有块标记的译文"


def test_translate_layout_blocks_fails_when_markers_are_missing(tmp_path):
    progress = LayoutTranslationProgress(str(tmp_path / "layout.progress.json"))

    try:
        translate_layout_blocks(_sample_layout(), BrokenMarkerTranslator(), progress)
    except RuntimeError as exc:
        assert "存在失败文本块" in str(exc)
    else:
        raise AssertionError("missing block markers should fail")

    assert "p0001_t0000" in progress.get_failed_blocks()


def test_layout_progress_retries_windows_replace_lock(tmp_path, monkeypatch):
    progress = LayoutTranslationProgress(str(tmp_path / "layout.progress.json"))
    real_replace = __import__("os").replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr("core.layout_translation.os.replace", flaky_replace)

    progress.mark_completed("p0001_t0000", "译文")

    assert calls["count"] == 2
    assert progress.get_translation("p0001_t0000") == "译文"


def test_layout_progress_recovers_newer_temp_file(tmp_path):
    progress_path = tmp_path / "layout.progress.json"
    progress_path.write_text(
        json.dumps({
            "schema": 1,
            "translations": {"old": "旧译文"},
            "failed_blocks": {},
            "translation_cache": {},
        }),
        encoding="utf-8",
    )
    temp_path = tmp_path / "layout.progress.json.recovered.tmp"
    temp_path.write_text(
        json.dumps({
            "schema": 1,
            "translations": {"old": "旧译文", "new": "新译文"},
            "failed_blocks": {},
            "translation_cache": {},
        }),
        encoding="utf-8",
    )

    progress = LayoutTranslationProgress(str(progress_path))

    assert progress.get_translation("old") == "旧译文"
    assert progress.get_translation("new") == "新译文"
