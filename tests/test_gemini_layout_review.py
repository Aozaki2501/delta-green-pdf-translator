import json

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
from experiments.gemini_layout_review import (
    DEFAULT_MODEL,
    _extract_response_text,
    build_page_block_summary,
    build_prompt,
    generate_layout_hints_for_pages,
    is_retryable_gemini_error,
    layout_hints_response_schema,
    make_gemini_sdk_error,
)


def test_build_page_block_summary_uses_local_ids_and_bboxes():
    structure = PageStructureDocument(
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
                ],
            )
        ],
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
                        runs=[StyledTextRun("Source text", 10.9, False, False, "#000000")],
                        source_text="Source text",
                        translated_text=None,
                        translatable=True,
                    )
                ],
            )
        ],
    )

    summary = build_page_block_summary(structure, content, 0)

    assert summary["page_index"] == 0
    assert summary["blocks"][0]["id"] == "b1"
    assert summary["blocks"][0]["bbox"] == [10.0, 20.0, 110.0, 60.0]
    assert summary["blocks"][0]["text_preview"] == "Source text"


def test_response_schema_requires_layout_hints_shape():
    schema = layout_hints_response_schema()

    assert schema["required"] == ["schema_version", "source_pdf", "pages"]
    page_schema = schema["properties"]["pages"]["additionalProperties"]
    assert "reading_order" in page_schema["required"]
    assert page_schema["properties"]["page_type"]["enum"] == [
        "columns",
        "single",
        "cover",
        "art",
        "mixed",
    ]


def test_default_gemini_model_uses_stable_flash():
    assert DEFAULT_MODEL == "gemini-2.5-flash"


def test_gemini_503_error_is_actionable():
    error = make_gemini_sdk_error(RuntimeError("503 UNAVAILABLE"), "gemini-2.5-flash")

    assert "模型当前繁忙" in str(error)
    assert "已自动重试" in str(error)


def test_gemini_timeout_error_is_retryable_and_actionable():
    timeout_error = TimeoutError("The read operation timed out")

    assert is_retryable_gemini_error(timeout_error) is True
    error = make_gemini_sdk_error(timeout_error, "gemini-2.5-flash", attempts=3)
    assert "临时请求失败" in str(error)
    assert "已自动重试 3 次" in str(error)


def test_gemini_ssl_eof_error_is_retryable():
    ssl_error = RuntimeError("EOF occurred in violation of protocol (_ssl.c:997)")

    assert is_retryable_gemini_error(ssl_error) is True
    error = make_gemini_sdk_error(ssl_error, "gemini-2.5-flash", attempts=3)
    assert "临时请求失败" in str(error)
    assert "已自动重试 3 次" in str(error)


def test_extract_response_text_reads_first_candidate_text():
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": json.dumps({"schema_version": 1})},
                    ]
                }
            }
        ]
    }

    assert _extract_response_text(payload) == '{"schema_version": 1}'


def test_extract_response_text_fails_on_empty_response():
    with pytest.raises(RuntimeError, match="candidates"):
        _extract_response_text({})


def test_prompt_tells_model_not_to_invent_ids():
    prompt = build_prompt("book.pdf", {"page_index": 0, "blocks": []})

    assert "Do not invent IDs" in prompt
    assert "layout_hints" in prompt
    assert 'exactly one key: "0"' in prompt
    assert "zero-based page indexes" in prompt
    assert "skip_blocks must be an array of objects" in prompt
    assert "Never return skip_blocks" in prompt


def test_missing_requested_page_hint_reports_returned_keys(tmp_path, monkeypatch):
    pdf_path = tmp_path / "book.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")
    structure = PageStructureDocument(
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
                ],
            )
        ],
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
                        runs=[StyledTextRun("Source text", 10.9, False, False, "#000000")],
                        source_text="Source text",
                        translated_text=None,
                        translatable=True,
                    )
                ],
            )
        ],
    )
    monkeypatch.setattr(
        "experiments.gemini_layout_review.render_page_png_base64",
        lambda pdf, page, dpi: "image",
    )
    monkeypatch.setattr(
        "experiments.gemini_layout_review.call_gemini_layout_review",
        lambda **kwargs: {
            "schema_version": 1,
            "source_pdf": "book.pdf",
            "pages": {
                "1": {
                    "page_type": "single",
                    "reading_order": ["b1"],
                    "skip_blocks": [],
                    "columns": [],
                    "special_regions": [],
                }
            },
        },
    )

    with pytest.raises(ValueError, match="实际返回页码键"):
        generate_layout_hints_for_pages(
            pdf_path=pdf_path,
            structure=structure,
            content=content,
            page_indexes=[0],
            output_path=tmp_path / "layout_hints.json",
            api_key="key",
        )


def test_invalid_gemini_skip_blocks_shape_reports_model_output_error(tmp_path, monkeypatch):
    pdf_path = tmp_path / "book.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")
    structure = PageStructureDocument(
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
                ],
            )
        ],
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
                        runs=[StyledTextRun("Source text", 10.9, False, False, "#000000")],
                        source_text="Source text",
                        translated_text=None,
                        translatable=True,
                    )
                ],
            )
        ],
    )
    monkeypatch.setattr(
        "experiments.gemini_layout_review.render_page_png_base64",
        lambda pdf, page, dpi: "image",
    )
    monkeypatch.setattr(
        "experiments.gemini_layout_review.call_gemini_layout_review",
        lambda **kwargs: {
            "schema_version": 1,
            "source_pdf": "book.pdf",
            "pages": {
                "0": {
                    "page_type": "single",
                    "reading_order": ["b1"],
                    "skip_blocks": ["b1"],
                    "columns": [],
                    "special_regions": [],
                }
            },
        },
    )

    with pytest.raises(ValueError, match="Gemini 输出 layout_hints 格式错误"):
        generate_layout_hints_for_pages(
            pdf_path=pdf_path,
            structure=structure,
            content=content,
            page_indexes=[0],
            output_path=tmp_path / "layout_hints.json",
            api_key="key",
        )


def test_generate_layout_hints_for_pages_writes_valid_file(tmp_path, monkeypatch):
    pdf_path = tmp_path / "book.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")
    structure = PageStructureDocument(
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
                ],
            )
        ],
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
                        runs=[StyledTextRun("Source text", 10.9, False, False, "#000000")],
                        source_text="Source text",
                        translated_text=None,
                        translatable=True,
                    )
                ],
            )
        ],
    )
    monkeypatch.setattr(
        "experiments.gemini_layout_review.render_page_png_base64",
        lambda pdf, page, dpi: "image",
    )
    monkeypatch.setattr(
        "experiments.gemini_layout_review.call_gemini_layout_review",
        lambda **kwargs: {
            "schema_version": 1,
            "source_pdf": "book.pdf",
            "pages": {
                "0": {
                    "page_type": "single",
                    "reading_order": ["b1"],
                    "skip_blocks": [],
                    "columns": [],
                    "special_regions": [],
                }
            },
        },
    )

    output = generate_layout_hints_for_pages(
        pdf_path=pdf_path,
        structure=structure,
        content=content,
        page_indexes=[0],
        output_path=tmp_path / "layout_hints.json",
        api_key="key",
    )

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["pages"]["0"]["reading_order"] == ["b1"]
