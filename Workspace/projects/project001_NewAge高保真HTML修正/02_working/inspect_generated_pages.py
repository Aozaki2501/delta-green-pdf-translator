from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "01_inputs" / "current_output"
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO))

from core.typeset_models import PageContentDocument, PageStructureDocument
from exporters.typeset_html import TypesetHTMLRebuilder


def load(name: str):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def normalize_pages(payload):
    if isinstance(payload, list):
        return payload
    for key in ("pages", "page_contents", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    raise ValueError("Unsupported page payload")


def main() -> None:
    translated = normalize_pages(load("page_content_translated.json"))
    structures = normalize_pages(load("page_structure.json"))
    output = {}
    for page_index in (5, 13):
        page = translated[page_index]
        structure = structures[page_index]
        blocks = page.get("blocks") or page.get("regions") or []
        output[str(page_index)] = {
            "page": page,
            "structure": structure,
            "columns": page.get("columns"),
            "images": structure.get("images"),
            "block_summary": [
                {
                    "index": index,
                    "id": block.get("id") or block.get("block_id"),
                    "role": block.get("role"),
                    "font_role": block.get("font_role"),
                    "bbox": block.get("bbox"),
                    "source": block.get("source_text") or block.get("text"),
                    "translation": block.get("translated_text") or block.get("translation"),
                }
                for index, block in enumerate(blocks)
            ],
        }
    (ROOT / "02_working" / "generated_problem_pages.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for page_index, details in output.items():
        print(f"\nPAGE INDEX {page_index}")
        print(f"type={details['page'].get('page_type')} blocks={len(details['block_summary'])}")
        print(f"columns={json.dumps(details['columns'], ensure_ascii=False)}")
        print(f"images={json.dumps(details['images'], ensure_ascii=False)}")
        for block in details["block_summary"]:
            print(
                f"{block['index']:02d} {block['role']}/{block['font_role']} "
                f"{block['bbox']} | {str(block['source'])[:80]} => {str(block['translation'])[:80]}"
            )
    document = PageContentDocument.from_json(
        DATA_DIR.joinpath("page_content_translated.json").read_text(encoding="utf-8")
    )
    structure_document = PageStructureDocument.from_json(
        DATA_DIR.joinpath("page_structure.json").read_text(encoding="utf-8")
    )
    timeline_blocks = document.pages[13].blocks
    rebuilder = TypesetHTMLRebuilder()
    print(
        "timeline_date_count=",
        sum(
            len(rebuilder._timeline_date_lines(block.source_text or block.translated_text or ""))
            for block in timeline_blocks
        ),
    )
    region_map = {
        region.id: region.bbox for region in structure_document.pages[13].text_regions
    }
    source_page_blocks = [
        block for block in timeline_blocks if block.region_id in region_map
    ]
    filtered = [
        block
        for block in source_page_blocks
        if (
            block.role not in {
                block.role.HEADER,
                block.role.FOOTER,
                block.role.TABLE,
                block.role.TITLE,
            }
            and rebuilder._display_text_for_block(block)
        )
    ]
    deduped = rebuilder._dedupe_content_blocks(filtered, region_map)
    print(
        "timeline_after_filter=",
        sum(len(rebuilder._timeline_date_lines(block.source_text or "")) for block in filtered),
        "timeline_after_dedupe=",
        sum(len(rebuilder._timeline_date_lines(block.source_text or "")) for block in deduped),
    )


if __name__ == "__main__":
    main()
