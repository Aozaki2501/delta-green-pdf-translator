"""Rebuild and validate a Rejection HTML candidate without API calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT))

from core.typeset_models import PageContentDocument, PageStructureDocument
from core.typeset_profiles import get_typeset_profile
from core.typeset_visibility import expected_render_blocks
from core.glossary import load_glossary
from core.typeset_translation import normalize_exact_glossary_labels
from core.typeset_quality import build_typeset_quality_report, write_typeset_quality_report
from core.utils import atomic_output_path
from exporters.typeset_html import TypesetHTMLRebuilder
from exporters.typeset_pdf import TypesetPDFExporter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--glossary",
        type=Path,
        default=REPOSITORY_ROOT / "glossary.tsv",
    )
    args = parser.parse_args()

    structure = PageStructureDocument.from_json(
        (args.input / "page_structure.json").read_text(encoding="utf-8")
    )
    content = PageContentDocument.from_json(
        (args.input / "page_content_translated.json").read_text(encoding="utf-8")
    )
    content = normalize_exact_glossary_labels(
        content,
        load_glossary(str(args.glossary)),
    )
    visual_manifest = json.loads(
        (args.input / "page_visuals.json").read_text(encoding="utf-8")
    )
    page_visuals = {
        int(item["page"]) - 1: str(item["svg"]).replace("\\", "/")
        for item in visual_manifest["pages"]
    }
    config = get_typeset_profile("delta_green").build_config(
        document_title="Delta Green: Rejection（高保真优化稿）",
        layout_hints_path=None,
    )
    html = TypesetHTMLRebuilder(config=config).rebuild_document(
        structure,
        content,
        page_visuals=page_visuals,
    )
    expected_blocks = expected_render_blocks(content, structure)
    with atomic_output_path(args.output) as candidate:
        candidate.write_text(html, encoding="utf-8")
        TypesetPDFExporter().validate_html_layout(
            str(candidate),
            report_path=str(args.output.with_suffix(".layout.json")),
            repair_manifest_path=str(args.output.with_suffix(".repair.json")),
            profile_id=config.profile_id,
            expected_blocks=expected_blocks,
            required_font_families=(config.font_family, config.heading_font_family),
        )
    revised_content_path = args.output.parent / "page_content_revised.json"
    with atomic_output_path(revised_content_path) as candidate:
        candidate.write_text(content.to_json(), encoding="utf-8")
    quality = build_typeset_quality_report(content, load_glossary(str(args.glossary)))
    write_typeset_quality_report(
        quality,
        args.output.with_suffix(".quality.md"),
        args.output.with_suffix(".quality.json"),
    )


if __name__ == "__main__":
    main()
