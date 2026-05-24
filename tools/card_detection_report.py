#!/usr/bin/env python3
"""Run DGtranslate extraction on selected pages and report detected card markers."""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.extractor import PDFExtractor


def parse_pages(value: str) -> list[int]:
    pages = []
    for raw_part in value.replace("，", ",").split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                start, end = end, start
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def card_excerpt(text: str, limit: int = 300) -> str:
    start = text.find("[CARD]")
    if start < 0:
        return text[:limit].replace("\n", "\\n")
    end = text.find("[/CARD]", start)
    if end < 0:
        return text[start:start + limit].replace("\n", "\\n")
    return text[start:end + len("[/CARD]")][:limit].replace("\n", "\\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="PDF file to inspect")
    parser.add_argument("--pages", required=True, help="1-based pages, such as 35 or 38,51 or 33-36")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    extractor = PDFExtractor(str(pdf_path))
    try:
        for page_number in parse_pages(args.pages):
            page_index = page_number - 1
            if page_index < 0 or page_index >= extractor.total_pages:
                raise ValueError(f"page {page_number} is outside 1-{extractor.total_pages}")
            text = extractor.extract_page(page_index)
            notes = extractor.get_layout_notes(page_index)
            diagnostics = extractor.get_page_diagnostics(page_index, text)
            print()
            print("=" * 72)
            print(f"Page {page_number}")
            print("=" * 72)
            print(f"layout_notes={notes}")
            print(f"has_card={'[CARD]' in text}")
            print(f"card_count={text.count('[CARD]')}")
            print(f"risks={diagnostics['risks']}")
            print(f"excerpt={card_excerpt(text)}")
    finally:
        extractor.close()


if __name__ == "__main__":
    main()
