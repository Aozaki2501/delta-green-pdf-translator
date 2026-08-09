from __future__ import annotations

import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "01_inputs"
WORKING = ROOT / "02_working"
HTML = INPUTS / "Delta_Green_Presence_PDF_1_cn_typeset.html"
ORIGINAL_PDF = INPUTS / "Delta_Green_Presence_PDF_1_original.pdf"
RENDERED = WORKING / "html_pages"
RENDERED.mkdir(exist_ok=True)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=1)
        page.goto(HTML.as_uri(), wait_until="networkidle")
        page.evaluate(
            """async () => {
                if (document.fonts) await document.fonts.ready;
                await Promise.all(Array.from(document.images).map(async (image) => {
                    if (!image.complete) await new Promise((resolve, reject) => {
                        image.addEventListener('load', resolve, {once: true});
                        image.addEventListener('error', reject, {once: true});
                    });
                    if (image.decode) await image.decode();
                }));
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            }"""
        )
        page.evaluate("window.typesetFitPositionedBlocks && window.typesetFitPositionedBlocks()")
        issues = page.evaluate("window.typesetCollectLayoutIssues ? window.typesetCollectLayoutIssues() : []")
        total_pages = page.locator(".typeset-page").count()
        for index in range(total_pages):
            page.locator(".typeset-page").nth(index).screenshot(path=str(RENDERED / f"page-{index + 1:02d}.png"))
        page.pdf(
            path=str(WORKING / "Delta_Green_Presence_PDF_1_cn_typeset_unchecked.pdf"),
            width="8.5in",
            height="11in",
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            print_background=True,
            prefer_css_page_size=True,
        )
        browser.close()
    (WORKING / "layout_issues.json").write_text(
        json.dumps({"total_pages": total_pages, "issues": issues}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def contact_sheets() -> None:
    original_dir = WORKING / "original_pages"
    rendered = sorted(RENDERED.glob("page-*.png"))
    originals = sorted(original_dir.glob("page-*.png"))
    for group_start in range(0, len(rendered), 3):
        indices = range(group_start, min(group_start + 3, len(rendered)))
        rows = []
        for index in indices:
            left = Image.open(originals[index]).convert("RGB")
            right = Image.open(rendered[index]).convert("RGB")
            left_scale = 700 / left.width
            right_scale = 700 / right.width
            left = left.resize((round(left.width * left_scale), round(left.height * left_scale)))
            right = right.resize((round(right.width * right_scale), round(right.height * right_scale)))
            row = Image.new("RGB", (left.width + right.width + 24, max(left.height, right.height) + 36), "white")
            row.paste(left, (0, 36))
            row.paste(right, (left.width + 24, 36))
            draw = ImageDraw.Draw(row)
            draw.text((0, 8), f"第 {index + 1} 页：原 PDF", fill="black")
            draw.text((left.width + 24, 8), f"第 {index + 1} 页：中文 HTML", fill="black")
            rows.append(row)
        width = max(row.width for row in rows)
        height = sum(row.height for row in rows) + 16 * (len(rows) - 1)
        sheet = Image.new("RGB", (width, height), "#dddddd")
        offset = 0
        for row in rows:
            sheet.paste(row, (0, offset))
            offset += row.height + 16
        sheet.save(WORKING / f"compare_{group_start // 3 + 1:02d}.png")


def render_original() -> None:
    original_dir = WORKING / "original_pages"
    original_dir.mkdir(exist_ok=True)
    document = fitz.open(ORIGINAL_PDF)
    try:
        for index, pdf_page in enumerate(document):
            pixmap = pdf_page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            pixmap.save(original_dir / f"page-{index + 1:02d}.png")
    finally:
        document.close()


if __name__ == "__main__":
    main()
    render_original()
    contact_sheets()
