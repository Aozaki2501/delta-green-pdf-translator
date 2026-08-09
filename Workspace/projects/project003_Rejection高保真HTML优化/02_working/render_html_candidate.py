"""Render the rebuilt HTML pages and a contact sheet for visual review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from render_baseline import _contact_sheet, _content_ownership_report, _render_html


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--content", type=Path)
    parser.add_argument("--structure", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    evidence = _render_html(args.html, args.output / "pages")
    if args.content:
        evidence["content_ownership"] = _content_ownership_report(
            args.content, evidence, args.structure
        )
    page_paths = [args.output / "pages" / name for name in evidence["page_images"]]
    _contact_sheet(page_paths, args.output / "contact-sheet.jpg")
    (args.output / "browser-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
