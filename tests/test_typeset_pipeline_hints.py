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
from core.typeset_pipeline import TypesetPipeline


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
    cost_yuan = 0.00125


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
    assert result.cost_yuan == 0.00125


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
