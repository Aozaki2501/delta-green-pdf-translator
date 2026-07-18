from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "01_inputs" / "current_output" / "page_content_translated.json"


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    pages = payload["pages"] if isinstance(payload, dict) else payload
    for page_index in (5, 7, 8, 9, 10, 11, 12):
        print(f"\nPAGE {page_index + 1}")
        for block in pages[page_index]["blocks"]:
            if block["role"] in {"header", "footer"}:
                continue
            runs = [run for run in block.get("runs", []) if run.get("text", "").strip()]
            fonts = Counter(run.get("font") for run in runs)
            colors = Counter(run.get("color") for run in runs)
            print(
                block["id"],
                block["role"],
                block.get("font_role"),
                block.get("bbox"),
                "font=", block.get("source_font"),
                "runs=", fonts.most_common(2),
                "colors=", colors.most_common(2),
                "paragraph=", block.get("paragraph_id"),
                "indent=", block.get("first_line_indent_pt"),
                "|", (block.get("source_text") or "")[:90].replace("\n", " / "),
            )


if __name__ == "__main__":
    main()
