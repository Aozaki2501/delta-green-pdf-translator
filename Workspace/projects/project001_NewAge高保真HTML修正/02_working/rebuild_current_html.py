from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PROJECT = Path(__file__).resolve().parents[1]
SOURCE = REPO / "output" / "Delta_Green_The_New_Age_2026_FIXED_cn"
sys.path.insert(0, str(REPO))

from core.typeset_models import PageContentDocument, PageStructureDocument
from exporters.typeset_html import TypesetHTMLRebuilder


def main() -> None:
    structure = PageStructureDocument.from_json(
        SOURCE.joinpath("page_structure.json").read_text(encoding="utf-8")
    )
    content = PageContentDocument.from_json(
        SOURCE.joinpath("page_content_translated.json").read_text(encoding="utf-8")
    )
    visual_payload = json.loads(SOURCE.joinpath("page_visuals.json").read_text(encoding="utf-8"))
    visuals = {
        int(item["page"]) - 1: item["svg"]
        for item in visual_payload["pages"]
    }
    rebuilder = TypesetHTMLRebuilder()
    print("timeline_source_detected=", rebuilder._is_timeline_page(content.pages[13].blocks))
    rebuilt = rebuilder.rebuild_document(structure, content, visuals)
    print("timeline_html_count=", rebuilt.count('class="typeset-timeline-flow"'))

    source_html = next(SOURCE.glob("*_typeset.html"))
    preview_path = source_html.with_name(source_html.stem + "_fixed.html")
    preview_path.write_text(rebuilt, encoding="utf-8")

    project_output = PROJECT / "03_outputs" / preview_path.name
    project_output.parent.mkdir(parents=True, exist_ok=True)
    project_output.write_text(rebuilt, encoding="utf-8")
    print(preview_path)


if __name__ == "__main__":
    main()
