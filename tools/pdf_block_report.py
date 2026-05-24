#!/usr/bin/env python3
"""Print PDF text block, font, drawing, and image diagnostics for selected pages."""

import argparse
from pathlib import Path

import pymupdf


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


def block_preview(block, limit: int = 80) -> str:
    text = ""
    for line in block.get("lines", [])[:2]:
        for span in line.get("spans", []):
            text += span.get("text", "")
    return text.strip()[:limit]


def print_page_report(doc, page_number: int):
    page_index = page_number - 1
    if page_index < 0 or page_index >= doc.page_count:
        raise ValueError(f"page {page_number} is outside 1-{doc.page_count}")
    page = doc[page_index]
    width = page.rect.width
    height = page.rect.height
    page_dict = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
    blocks = [block for block in page_dict.get("blocks", []) if block.get("type") == 0]
    drawings = page.get_drawings()
    images = page.get_images(full=True)

    print()
    print("=" * 72)
    print(
        f"Page {page_number} | size={width:.0f}x{height:.0f} | "
        f"text_blocks={len(blocks)} | drawings={len(drawings)} | images={len(images)}"
    )
    print("=" * 72)

    print("\nLarge drawings:")
    large_drawings = [
        drawing for drawing in drawings
        if drawing.get("rect")
        and drawing["rect"].width > width * 0.15
        and drawing["rect"].height > height * 0.04
    ]
    for index, drawing in enumerate(large_drawings[:12]):
        rect = drawing["rect"]
        print(
            f"  [{index}] ({rect.x0:.0f},{rect.y0:.0f})-({rect.x1:.0f},{rect.y1:.0f}) "
            f"w={rect.width:.0f} h={rect.height:.0f} fill={drawing.get('fill')}"
        )

    print("\nLarge images:")
    image_index = 0
    for image in images:
        xref = image[0]
        for rect in page.get_image_rects(xref):
            if rect.width > width * 0.15 and rect.height > height * 0.04:
                print(
                    f"  [{image_index}] xref={xref} "
                    f"({rect.x0:.0f},{rect.y0:.0f})-({rect.x1:.0f},{rect.y1:.0f}) "
                    f"w={rect.width:.0f} h={rect.height:.0f}"
                )
                image_index += 1

    print("\nText blocks:")
    for index, block in enumerate(blocks):
        fonts = set()
        line_count = 0
        for line in block.get("lines", []):
            line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if line_text:
                line_count += 1
            for span in line.get("spans", []):
                fonts.add(span.get("font", "?"))
        if not line_count:
            continue
        x0, y0, x1, y1 = block["bbox"]
        print(
            f"  [{index}] ({x0:.0f},{y0:.0f})-({x1:.0f},{y1:.0f}) "
            f"w={x1 - x0:.0f} h={y1 - y0:.0f} lines={line_count}"
        )
        print(f"      fonts={sorted(fonts)}")
        print(f"      text={block_preview(block)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="PDF file to inspect")
    parser.add_argument("--pages", required=True, help="1-based pages, such as 35 or 38,51 or 33-36")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    with pymupdf.open(str(pdf_path)) as doc:
        for page_number in parse_pages(args.pages):
            print_page_report(doc, page_number)


if __name__ == "__main__":
    main()
