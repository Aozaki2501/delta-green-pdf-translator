import json
from pathlib import Path

import pymupdf
import pytest

from core.typeset_models import (
    PAGE_CONTENT_SCHEMA_VERSION,
    PAGE_STRUCTURE_SCHEMA_VERSION,
    BackgroundLayer,
    ContentBlock,
    PageContent,
    PageContentDocument,
    PageStructure,
    PageStructureDocument,
    PageType,
    SemanticRole,
    StyledTextRun,
    TextRegionBBox,
)
from core.typeset_pipeline import TypesetPipeline
from exporters.typeset_html import TypesetHTMLRebuilder


class _Translator:
    stats = None


def _documents():
    structure = PageStructureDocument(
        schema_version=PAGE_STRUCTURE_SCHEMA_VERSION,
        source_pdf="book.pdf",
        page_count=1,
        pages=[
            PageStructure(
                page_index=0,
                width=160.0,
                height=120.0,
                background=BackgroundLayer(),
                images=[],
                decorations=[],
                text_regions=[TextRegionBBox("r1", [20.0, 20.0, 140.0, 80.0], ["原文"])],
            )
        ],
        source_sha256="fixture-sha256",
    )
    content = PageContentDocument(
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
                        runs=[StyledTextRun("Source", 10.0, False, False, "#000000")],
                        source_text="Source",
                        translated_text="译文",
                        translatable=True,
                    )
                ],
            )
        ],
        source_sha256="fixture-sha256",
    )
    return structure, content


def _make_pdf(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=160, height=120)
    page.draw_rect(pymupdf.Rect(0, 0, 160, 120), fill=(0.9, 0.8, 0.6))
    page.insert_text((20, 60), "Source", fontsize=10)
    doc.save(path)
    doc.close()


def test_high_fidelity_html_uses_clean_page_svg_as_single_visual_base():
    structure, content = _documents()

    output = TypesetHTMLRebuilder().rebuild_document(
        structure,
        content,
        page_visuals={0: "assets/page_visuals/p0001.svg"},
    )

    assert 'class="typeset-page-visual"' in output
    assert 'src="assets/page_visuals/p0001.svg"' in output
    assert 'data-block-id="b1"' in output
    assert 'class="typeset-image-layer"' not in output
    assert 'class="typeset-decoration-layer"' not in output
    assert "typesetFitPagesToViewport" in output
    assert "zoom: 1 !important" in output


def test_high_fidelity_html_rejects_missing_page_content():
    structure, content = _documents()
    missing = PageContentDocument(
        schema_version=content.schema_version,
        source_pdf=content.source_pdf,
        page_count=0,
        pages=[],
        source_sha256=content.source_sha256,
    )

    with pytest.raises(ValueError, match="页面内容不完整"):
        TypesetHTMLRebuilder().rebuild_document(
            structure,
            missing,
            page_visuals={0: "assets/page_visuals/p0001.svg"},
        )


def test_high_fidelity_html_rejects_missing_block_translation():
    structure, content = _documents()
    block = content.pages[0].blocks[0]
    untranslated = PageContentDocument(
        schema_version=content.schema_version,
        source_pdf=content.source_pdf,
        page_count=1,
        pages=[
            PageContent(
                page_index=0,
                page_type=PageType.SINGLE,
                columns=[],
                blocks=[
                    ContentBlock(
                        id=block.id,
                        region_id=block.region_id,
                        role=block.role,
                        runs=block.runs,
                        source_text=block.source_text,
                        translated_text=None,
                        translatable=True,
                    )
                ],
            )
        ],
        source_sha256=content.source_sha256,
    )

    with pytest.raises(ValueError, match="缺少 translated_text"):
        TypesetHTMLRebuilder().rebuild_document(
            structure,
            untranslated,
            page_visuals={0: "assets/page_visuals/p0001.svg"},
        )


def test_pipeline_phase_a_writes_and_reuses_verified_page_visual_manifest(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    _make_pdf(pdf_path)
    pipeline = TypesetPipeline(
        pdf_path=str(pdf_path),
        output_dir=str(tmp_path / "out"),
        translator=_Translator(),
        glossary={},
    )
    pipeline._start_page = 0
    pipeline._end_page = 1

    structure = pipeline.run_phase_a()
    visual_map = pipeline._load_page_visuals_for_structure(structure)

    assert visual_map == {0: "assets/page_visuals/p0001.svg"}
    manifest_path = tmp_path / "out" / "page_visuals.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_sha256"] == structure.source_sha256
    assert manifest["pages"][0]["remaining_text_nodes"] == 0
    assert manifest["pages"][0]["text_trace_count"] == manifest["pages"][0]["removed_text_nodes"]
    assert (tmp_path / "out" / visual_map[0]).exists()


def test_pipeline_rejects_page_visual_manifest_with_wrong_source_hash(tmp_path):
    structure, _content = _documents()
    (tmp_path / "book.pdf").write_bytes(b"not-the-fixture")
    pipeline = TypesetPipeline(
        pdf_path=str(tmp_path / "book.pdf"),
        output_dir=str(tmp_path),
        translator=_Translator(),
        glossary={},
    )
    (tmp_path / "page_visuals.json").write_text(
        json.dumps({"schema_version": 1, "source_sha256": "wrong", "pages": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="来源 PDF 不匹配"):
        pipeline._load_page_visuals_for_structure(structure)


def test_existing_invalid_page_visual_manifest_is_not_silently_rebuilt(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    _make_pdf(pdf_path)
    pipeline = TypesetPipeline(
        pdf_path=str(pdf_path),
        output_dir=str(tmp_path / "out"),
        translator=_Translator(),
        glossary={},
    )
    pipeline._start_page = 0
    pipeline._end_page = 1
    structure = pipeline.run_phase_a()
    manifest = json.loads(pipeline._page_visuals_manifest_path.read_text(encoding="utf-8"))
    manifest["pages"][0]["sha256"] = "corrupt"
    pipeline._page_visuals_manifest_path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="哈希不匹配"):
        pipeline._ensure_page_visuals(structure)
