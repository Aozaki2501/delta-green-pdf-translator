"""Ask Gemini to review one PDF page and propose layout_hints.json.

This is an experiment script. It does not run as part of the normal pipeline.
It sends a rendered page image plus local PyMuPDF block facts to Gemini, then
validates the returned hints against page_content.json before writing them.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf

from core.layout_hints import LAYOUT_HINTS_SCHEMA_VERSION, LayoutHints
from core.typeset_models import PageContentDocument, PageStructureDocument


DEFAULT_MODEL = "gemini-3.5-flash"
GEMINI_GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def render_page_png_base64(pdf_path: Path, page_index: int, dpi: int) -> str:
    doc = pymupdf.open(str(pdf_path))
    try:
        if page_index < 0 or page_index >= len(doc):
            raise ValueError(f"页码超出范围：PDF 共 {len(doc)} 页，收到 {page_index}")
        page = doc[page_index]
        matrix = pymupdf.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return base64.b64encode(pix.tobytes("png")).decode("ascii")
    finally:
        doc.close()


def build_page_block_summary(
    structure: PageStructureDocument,
    content: PageContentDocument,
    page_index: int,
) -> dict:
    structure_page = next((page for page in structure.pages if page.page_index == page_index), None)
    content_page = next((page for page in content.pages if page.page_index == page_index), None)
    if structure_page is None:
        raise ValueError(f"page_structure.json 中没有第 {page_index} 页")
    if content_page is None:
        raise ValueError(f"page_content.json 中没有第 {page_index} 页")

    region_bbox = {region.id: region.bbox for region in structure_page.text_regions}
    blocks = []
    for block in content_page.blocks:
        text = " ".join((block.source_text or "").split())
        blocks.append({
            "id": block.id,
            "region_id": block.region_id,
            "role": block.role.value,
            "bbox": region_bbox.get(block.region_id),
            "translatable": block.translatable,
            "text_preview": text[:260],
        })

    return {
        "page_index": page_index,
        "page_type": content_page.page_type.value,
        "blocks": blocks,
    }


def layout_hints_response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "schema_version": {"type": "integer"},
            "source_pdf": {"type": "string"},
            "pages": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "page_type": {
                            "type": "string",
                            "enum": ["columns", "single", "cover", "art", "mixed"],
                        },
                        "reading_order": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "skip_blocks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "reason": {"type": "string"},
                                },
                                "required": ["id", "reason"],
                            },
                        },
                        "columns": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "blocks": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["id", "blocks"],
                            },
                        },
                        "special_regions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "blocks": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["type", "blocks"],
                            },
                        },
                    },
                    "required": [
                        "page_type",
                        "reading_order",
                        "skip_blocks",
                        "columns",
                        "special_regions",
                    ],
                },
            },
        },
        "required": ["schema_version", "source_pdf", "pages"],
    }


def build_prompt(source_pdf: str, page_summary: dict) -> str:
    return (
        "You are reviewing a TRPG PDF page layout for a Chinese re-typeset PDF.\n"
        "Use the image for visual judgement, but use only the provided block IDs.\n"
        "Do not invent IDs, coordinates, or text.\n"
        "Return layout_hints JSON only.\n\n"
        "Decide:\n"
        "- page_type: columns, single, cover, art, or mixed.\n"
        "- reading_order: block IDs in the natural reading order.\n"
        "- skip_blocks: page numbers, running headers, footers, copyright marks.\n"
        "- columns: left/right body columns when visible.\n"
        "- special_regions: sidebars, tables, captions, or stat blocks.\n\n"
        f"schema_version must be {LAYOUT_HINTS_SCHEMA_VERSION}.\n"
        f"source_pdf: {source_pdf}\n"
        f"Page facts:\n{json.dumps(page_summary, ensure_ascii=False, indent=2)}"
    )


def call_gemini_layout_review(
    api_key: str,
    model: str,
    prompt: str,
    image_base64: str,
    timeout: int,
) -> dict:
    quoted_model = urllib.parse.quote(model, safe="")
    url = GEMINI_GENERATE_URL.format(model=quoted_model)
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": image_base64,
                    }
                },
            ]
        }],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseJsonSchema": layout_hints_response_schema(),
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API 请求失败：HTTP {exc.code}: {body}") from exc

    text = _extract_response_text(data)
    return json.loads(text)


def generate_layout_hints_for_pages(
    pdf_path: str | Path,
    structure: PageStructureDocument,
    content: PageContentDocument,
    page_indexes: list[int],
    output_path: str | Path,
    api_key: str,
    model: str = DEFAULT_MODEL,
    dpi: int = 144,
    timeout: int = 90,
    progress_callback=None,
) -> Path:
    """Generate and validate one layout_hints.json file for selected pages."""
    if not api_key:
        raise ValueError("缺少 Gemini API Key")
    if not page_indexes:
        raise ValueError("Gemini 审稿页码不能为空")

    source_pdf = structure.source_pdf
    pages: dict[str, dict] = {}
    pdf = Path(pdf_path)
    total = len(page_indexes)
    for done, page_index in enumerate(page_indexes, start=1):
        page_summary = build_page_block_summary(structure, content, page_index)
        image_base64 = render_page_png_base64(pdf, page_index, dpi)
        prompt = build_prompt(source_pdf, page_summary)
        hints_data = call_gemini_layout_review(
            api_key=api_key,
            model=model,
            prompt=prompt,
            image_base64=image_base64,
            timeout=timeout,
        )
        hints = LayoutHints.from_json(json.dumps(hints_data, ensure_ascii=False))
        page_hint = hints.get_page_hint(page_index)
        if page_hint is None:
            raise ValueError(f"Gemini 输出缺少第 {page_index} 页 hints")
        pages[str(page_index)] = _page_hint_to_dict(page_hint)
        if progress_callback:
            progress_callback(done, total, page_index)

    combined = {
        "schema_version": LAYOUT_HINTS_SCHEMA_VERSION,
        "source_pdf": source_pdf,
        "pages": pages,
    }
    validated = LayoutHints.from_json(json.dumps(combined, ensure_ascii=False))
    validated.validate_against_content(content)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _extract_response_text(response: dict) -> str:
    candidates = response.get("candidates")
    if not candidates:
        raise RuntimeError("Gemini API 没有返回 candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts = [part.get("text", "") for part in parts if part.get("text")]
    text = "".join(text_parts).strip()
    if not text:
        raise RuntimeError("Gemini API 没有返回 JSON 文本")
    return text


def _page_hint_to_dict(page_hint) -> dict:
    return {
        "page_type": page_hint.page_type,
        "reading_order": list(page_hint.reading_order),
        "skip_blocks": [
            {"id": item.id, "reason": item.reason}
            for item in page_hint.skip_blocks
        ],
        "columns": [
            {"id": item.id, "blocks": list(item.blocks)}
            for item in page_hint.columns
        ],
        "special_regions": [
            {"type": item.type, "blocks": list(item.blocks)}
            for item in page_hint.special_regions
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, help="源 PDF 路径")
    parser.add_argument("--page-structure", required=True, help="page_structure.json 路径")
    parser.add_argument("--page-content", required=True, help="page_content.json 路径")
    parser.add_argument("--page", type=int, required=True, help="0-based 页码")
    parser.add_argument("--output", required=True, help="输出 layout_hints.json 路径")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default=os.environ.get("GEMINI_API_KEY", ""))
    parser.add_argument("--dpi", type=int, default=144)
    parser.add_argument("--timeout", type=int, default=90)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.api_key:
        raise ValueError("缺少 Gemini API Key：请设置 GEMINI_API_KEY 或传入 --api-key")

    pdf_path = Path(args.pdf)
    structure = PageStructureDocument.from_json(
        Path(args.page_structure).read_text(encoding="utf-8")
    )
    content = PageContentDocument.from_json(
        Path(args.page_content).read_text(encoding="utf-8")
    )
    output_path = generate_layout_hints_for_pages(
        pdf_path=pdf_path,
        structure=structure,
        content=content,
        page_indexes=[args.page],
        output_path=args.output,
        api_key=args.api_key,
        model=args.model,
        dpi=args.dpi,
        timeout=args.timeout,
    )
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
