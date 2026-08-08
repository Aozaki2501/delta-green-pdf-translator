import json
from dataclasses import replace

import pytest
from PIL import Image

from core.typeset_models import (
    PAGE_CONTENT_SCHEMA_VERSION,
    PAGE_STRUCTURE_SCHEMA_VERSION,
    BackgroundLayer,
    ContentBlock,
    ImageElement,
    PageContent,
    PageContentDocument,
    PageStructure,
    PageStructureDocument,
    PageType,
    SemanticRole,
    StyledTextRun,
    TextRegionBBox,
    TypesetConfig,
)
from core.typeset_pipeline import TypesetPipeline, _is_image_overlay_text_block


def _content_doc():
    return PageContentDocument(
        schema_version=PAGE_CONTENT_SCHEMA_VERSION,
        source_pdf="book.pdf",
        page_count=1,
        pages=[
            PageContent(
                page_index=0,
                page_type=PageType.SINGLE,
                columns=[],
                blocks=[
                    ContentBlock(
                        id="b1",
                        region_id="r1",
                        role=SemanticRole.BODY_COLUMN,
                        runs=[StyledTextRun("A", 10.9, False, False, "#000000")],
                        source_text="A",
                        translated_text=None,
                        translatable=True,
                    ),
                    ContentBlock(
                        id="b2",
                        region_id="r2",
                        role=SemanticRole.BODY_COLUMN,
                        runs=[StyledTextRun("B", 10.9, False, False, "#000000")],
                        source_text="B",
                        translated_text=None,
                        translatable=True,
                    ),
                ],
            )
        ],
    )


def _structure_doc():
    return PageStructureDocument(
        schema_version=PAGE_STRUCTURE_SCHEMA_VERSION,
        source_pdf="book.pdf",
        page_count=1,
        pages=[
            PageStructure(
                page_index=0,
                width=612.0,
                height=792.0,
                background=BackgroundLayer(),
                images=[],
                decorations=[],
                text_regions=[
                    TextRegionBBox("r1", [10.0, 20.0, 110.0, 60.0], ["t1"]),
                    TextRegionBBox("r2", [120.0, 20.0, 220.0, 60.0], ["t2"]),
                ],
            )
        ],
    )


class _Stats:
    input_tokens = 100
    output_tokens = 40
    cached_tokens = 10
    total_tokens = 140
    api_calls = 3
    failed_calls = 1
    translation_cache_hits = 2
    cost_usd = 0.00125


class _Translator:
    stats = _Stats()


def test_pipeline_result_includes_token_usage(tmp_path):
    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=_Translator(),
        glossary={},
    )
    content = _content_doc()
    content.pages[0].blocks[0] = replace(
        content.pages[0].blocks[0],
        translated_text="A-cn",
    )

    result = pipeline._build_result(_structure_doc(), content, "out.html", "out.pdf")

    assert result.input_tokens == 100
    assert result.output_tokens == 40
    assert result.cached_tokens == 10
    assert result.total_tokens == 140
    assert result.api_calls == 3
    assert result.failed_calls == 1
    assert result.translation_cache_hits == 2
    assert result.cost_usd == 0.00125


def test_fixed_html_output_runs_browser_layout_gate(tmp_path, monkeypatch):
    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=_Translator(),
        glossary={},
    )
    content = _content_doc()
    content.pages[0].blocks[:] = [
        replace(block, translated_text=f"{block.source_text}-cn")
        for block in content.pages[0].blocks
    ]
    calls = []
    monkeypatch.setattr(pipeline, "_ensure_typeset_fonts", lambda: None)
    monkeypatch.setattr(pipeline, "_load_page_visuals_for_structure", lambda _structure: None)
    from exporters.typeset_pdf import TypesetPDFExporter
    monkeypatch.setattr(
        TypesetPDFExporter,
        "validate_html_layout",
        lambda _self, path, **_kwargs: calls.append(path),
    )

    result = pipeline.run_phase_d(_structure_doc(), content)

    assert calls == [result]


def test_kult_merges_built_in_swedish_terms_and_user_override(tmp_path):
    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=_Translator(),
        glossary={"zelother": "用户指定译名"},
        config=TypesetConfig(profile_id="kult", source_language="Swedish"),
    )

    assert pipeline.glossary["gransanghtir"] == "千魂水蛭"
    assert pipeline.glossary["zelother"] == "用户指定译名"


def test_translated_content_cache_requires_matching_translation_context(tmp_path, monkeypatch):
    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=_Translator(),
        glossary={},
    )
    content = _content_doc()
    content.pages[0].blocks[:] = [
        replace(block, translated_text=f"{block.source_text}-cn")
        for block in content.pages[0].blocks
    ]
    (tmp_path / "page_content_translated.json").write_text(content.to_json(), encoding="utf-8")
    monkeypatch.setattr(pipeline, "_matches_current_source", lambda *_args: True)

    assert pipeline._load_existing_translated_content() is None
    pipeline._write_translation_context()
    assert pipeline._load_existing_translated_content() is not None


def test_overflow_repair_reuses_existing_translation_without_full_phase_c(tmp_path, monkeypatch):
    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=_Translator(),
        glossary={},
    )
    existing = _content_doc()
    existing.pages[0].blocks[:] = [
        replace(block, translated_text=f"{block.source_text}-cn")
        for block in existing.pages[0].blocks
    ]
    (tmp_path / "page_content_translated.json").write_text(
        existing.to_json(), encoding="utf-8"
    )
    pipeline._write_translation_context()
    monkeypatch.setattr(pipeline, "_matches_current_source", lambda *_args: True)
    calls = []

    def fake_repair(content, **kwargs):
        calls.append((content, kwargs["target_metadata_by_block"]))
        blocks = list(content.pages[0].blocks)
        blocks[0] = replace(blocks[0], translated_text="short-cn")
        return replace(content, pages=[replace(content.pages[0], blocks=blocks)])

    monkeypatch.setattr(
        "core.typeset_translation.translate_overflow_targets", fake_repair
    )

    repaired = pipeline.repair_overflow_translations({
        "b1": {
            "capacity": "90px",
            "template_signature": "template-a",
            "constraint_prompt": "完整表达且必须放入已测得的区域容量。",
        }
    })

    assert len(calls) == 1
    assert calls[0][0].pages[0].blocks[1].translated_text == "B-cn"
    assert repaired.pages[0].blocks[0].translated_text == "short-cn"
    saved = PageContentDocument.from_json(
        (tmp_path / "page_content_translated.json").read_text(encoding="utf-8")
    )
    assert saved.pages[0].blocks[1].translated_text == "B-cn"


def test_pipeline_uses_layout_hints_from_output_dir(tmp_path):
    (tmp_path / "layout_hints.json").write_text(
        json.dumps({
            "schema_version": 1,
            "pages": {
                "0": {
                    "page_type": "columns",
                    "reading_order": ["b2", "b1"],
                    "skip_blocks": [{"id": "b2", "reason": "running_header"}],
                }
            },
        }),
        encoding="utf-8",
    )
    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=None,
        glossary={},
    )

    hinted = pipeline.apply_layout_hints(_structure_doc(), _content_doc())

    assert hinted.pages[0].page_type == PageType.COLUMNS
    assert [block.id for block in hinted.pages[0].blocks] == ["b2", "b1"]
    assert hinted.pages[0].blocks[0].translatable is False
    assert (tmp_path / "page_content_hinted.json").exists()


def test_tiny_text_over_foreground_image_is_not_translatable():
    page = PageStructure(
        page_index=0,
        width=612.0,
        height=792.0,
        background=BackgroundLayer(),
        images=[ImageElement("overlay", [500.0, 50.0, 612.0, 700.0], "overlay.png", 100, 100)],
        decorations=[],
        text_regions=[],
    )
    block = _content_doc().pages[0].blocks[0]
    block = replace(
        block,
        source_text="X",
        bbox=[590.0, 120.0, 604.0, 138.0],
        role=SemanticRole.BODY_COLUMN,
    )

    assert _is_image_overlay_text_block(block, page) is True


def test_pipeline_without_layout_hints_keeps_content(tmp_path):
    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=None,
        glossary={},
    )
    content = _content_doc()

    assert pipeline.apply_layout_hints(_structure_doc(), content) is content


def test_pipeline_does_not_reuse_structure_from_different_upload(tmp_path):
    (tmp_path / "page_structure.json").write_text(
        _structure_doc().to_json(),
        encoding="utf-8",
    )
    pipeline = TypesetPipeline(
        pdf_path="new_upload.pdf",
        output_dir=str(tmp_path),
        translator=None,
        glossary={},
    )

    assert pipeline._load_existing_structure() is None


def test_pipeline_does_not_reuse_structure_with_dark_full_page_overlay(tmp_path):
    image_dir = tmp_path / "assets" / "typeset_images"
    image_dir.mkdir(parents=True)
    Image.new("RGB", (100, 100), (240, 240, 240)).save(image_dir / "base.png")
    Image.new("RGB", (100, 100), (0, 0, 0)).save(image_dir / "overlay.png")
    structure = _structure_doc()
    page = structure.pages[0]
    structure = replace(
        structure,
        pages=[
            replace(
                page,
                images=[
                    ImageElement(
                        id="base",
                        bbox=[0.0, 0.0, page.width, page.height],
                        image_path="assets/typeset_images/base.png",
                        width_px=100,
                        height_px=100,
                    ),
                    ImageElement(
                        id="overlay",
                        bbox=[0.0, 0.0, page.width, page.height],
                        image_path="assets/typeset_images/overlay.png",
                        width_px=100,
                        height_px=100,
                    ),
                ],
            )
        ],
    )
    (tmp_path / "page_structure.json").write_text(
        structure.to_json(),
        encoding="utf-8",
    )
    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=None,
        glossary={},
    )

    assert pipeline._load_existing_structure() is None


def test_pipeline_does_not_reuse_content_from_different_upload(tmp_path):
    (tmp_path / "page_content.json").write_text(
        _content_doc().to_json(),
        encoding="utf-8",
    )
    (tmp_path / "page_content_translated.json").write_text(
        _content_doc().to_json(),
        encoding="utf-8",
    )
    pipeline = TypesetPipeline(
        pdf_path="new_upload.pdf",
        output_dir=str(tmp_path),
        translator=None,
        glossary={},
    )

    assert pipeline._load_existing_content() is None
    assert pipeline._load_existing_translated_content() is None


def test_pipeline_stops_when_any_typeset_translation_fails(tmp_path):
    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=None,
        glossary={},
    )
    progress = type("Progress", (), {
        "failed_blocks": {"b1": "401 invalid key"},
    })()

    with pytest.raises(RuntimeError, match="翻译未完成"):
        pipeline._ensure_no_translation_failed(_content_doc(), progress)


def test_pipeline_rejects_partial_typeset_translation_success(tmp_path):
    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=None,
        glossary={},
    )
    content = _content_doc()
    blocks = list(content.pages[0].blocks)
    blocks[0] = replace(blocks[0], translated_text="已翻译")
    content = replace(
        content,
        pages=[
            replace(content.pages[0], blocks=blocks),
        ],
    )
    progress = type("Progress", (), {"failed_blocks": {"b2": "timeout"}})()

    with pytest.raises(RuntimeError):
        pipeline._ensure_no_translation_failed(content, progress)


def test_pipeline_configured_missing_layout_hints_path_fails(tmp_path):
    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=None,
        glossary={},
        config=TypesetConfig(layout_hints_path=str(tmp_path / "missing.json")),
    )

    with pytest.raises(FileNotFoundError):
        pipeline.apply_layout_hints(_structure_doc(), _content_doc())


def test_pipeline_generator_writes_hints_before_apply(tmp_path):
    calls = []

    def generator(structure, content, output_path):
        calls.append((structure.source_pdf, content.source_pdf))
        output_path.write_text(
            json.dumps({
                "schema_version": 1,
                "pages": {
                    "0": {
                        "page_type": "columns",
                        "reading_order": ["b2", "b1"],
                        "skip_blocks": [],
                        "columns": [],
                        "special_regions": [],
                    }
                },
            }),
            encoding="utf-8",
        )
        return output_path

    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=None,
        glossary={},
        layout_hints_generator=generator,
    )
    structure = _structure_doc()
    content = _content_doc()

    generated = pipeline.generate_layout_hints(structure, content)
    hinted = pipeline.apply_layout_hints(structure, content)

    assert calls == [("book.pdf", "book.pdf")]
    assert generated == tmp_path / "layout_hints.json"
    assert hinted.pages[0].page_type == PageType.COLUMNS
    assert [block.id for block in hinted.pages[0].blocks] == ["b2", "b1"]


def test_pipeline_configured_hints_path_skips_generator(tmp_path):
    configured_path = tmp_path / "custom_hints.json"
    configured_path.write_text(
        json.dumps({
            "schema_version": 1,
            "pages": {"0": {}},
        }),
        encoding="utf-8",
    )

    def generator(structure, content, output_path):
        raise AssertionError("generator should not run when path is configured")

    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=None,
        glossary={},
        config=TypesetConfig(layout_hints_path=str(configured_path)),
        layout_hints_generator=generator,
    )

    assert pipeline.generate_layout_hints(_structure_doc(), _content_doc()) is None


def _stub_pipeline_for_phase_control(tmp_path, monkeypatch):
    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=_Translator(),
        glossary={},
    )
    structure = _structure_doc()
    content = _content_doc()
    monkeypatch.setattr(pipeline, "run_phase_a", lambda: structure)
    monkeypatch.setattr(pipeline, "run_phase_b", lambda _structure: content)
    monkeypatch.setattr(pipeline, "run_phase_c", lambda _content: content)
    monkeypatch.setattr(
        pipeline,
        "run_phase_d",
        lambda _structure, _content: str(tmp_path / "book_typeset.html"),
    )
    return pipeline


def test_pipeline_without_pdf_export_skips_phase_e_and_reports_four_phases(tmp_path, monkeypatch):
    pipeline = _stub_pipeline_for_phase_control(tmp_path, monkeypatch)
    phase_events = []

    def fail_if_called(_html_path):
        raise AssertionError("Phase E must not run for HTML-only output")

    monkeypatch.setattr(pipeline, "run_phase_e", fail_if_called)

    result = pipeline.run(
        export_pdf=False,
        progress_callback=lambda phase, done, total: phase_events.append((phase, done, total)),
    )

    assert result.pdf_path is None
    assert result.html_path.endswith("book_typeset.html")
    assert [event for event in phase_events if event[0] == "pipeline"] == [
        ("pipeline", 0, 4),
        ("pipeline", 1, 4),
        ("pipeline", 2, 4),
        ("pipeline", 3, 4),
        ("pipeline", 4, 4),
    ]


def test_pipeline_with_pdf_export_runs_phase_e_and_reports_five_phases(tmp_path, monkeypatch):
    pipeline = _stub_pipeline_for_phase_control(tmp_path, monkeypatch)
    phase_events = []
    phase_e_calls = []
    monkeypatch.setattr(
        pipeline,
        "run_phase_e",
        lambda html_path: phase_e_calls.append(html_path) or str(tmp_path / "book_typeset.pdf"),
    )

    result = pipeline.run(
        export_pdf=True,
        progress_callback=lambda phase, done, total: phase_events.append((phase, done, total)),
    )

    assert phase_e_calls == [str(tmp_path / "book_typeset.html")]
    assert result.pdf_path.endswith("book_typeset.pdf")
    assert [event for event in phase_events if event[0] == "pipeline"][-1] == ("pipeline", 5, 5)


def test_pipeline_reading_only_uses_same_translation_without_fixed_html(tmp_path, monkeypatch):
    pipeline = _stub_pipeline_for_phase_control(tmp_path, monkeypatch)
    reading_calls = []
    monkeypatch.setattr(
        pipeline,
        "run_phase_reading_d",
        lambda structure, content: reading_calls.append((structure, content))
        or str(tmp_path / "book_reading.html"),
    )
    monkeypatch.setattr(
        pipeline,
        "run_phase_d",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("fixed HTML must not run for reading-only output")
        ),
    )

    result = pipeline.run(
        export_pdf=False,
        export_typeset_html=False,
        export_reading_html=True,
    )

    assert len(reading_calls) == 1
    assert result.html_path is None
    assert result.reading_html_path.endswith("book_reading.html")


def test_pipeline_rejects_empty_typeset_output_selection(tmp_path):
    pipeline = TypesetPipeline(
        pdf_path="book.pdf",
        output_dir=str(tmp_path),
        translator=_Translator(),
        glossary={},
    )

    with pytest.raises(ValueError, match="至少选择"):
        pipeline.run(
            export_pdf=False,
            export_typeset_html=False,
            export_reading_html=False,
        )
