"""Render the Rejection baseline and collect browser layout evidence.

This script is intentionally project-local.  It never changes the source PDFs,
the current generated output, or application state.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT))


def _render_pdf(pdf_path: Path, output_dir: Path, scale: float) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    with fitz.open(pdf_path) as document:
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            path = output_dir / f"page-{index + 1:03d}.png"
            pixmap.save(path)
            paths.append(path)
    return paths


def _contact_sheet(
    image_paths: list[Path],
    output_path: Path,
    *,
    columns: int = 5,
    thumb_width: int = 245,
) -> None:
    if not image_paths:
        raise ValueError("contact sheet 不能为空")
    border = 12
    label_height = 28
    thumbnails: list[Image.Image] = []
    max_height = 0
    for path in image_paths:
        with Image.open(path) as loaded:
            image = loaded.convert("RGB")
        height = max(1, round(image.height * thumb_width / image.width))
        image = image.resize((thumb_width, height), Image.Resampling.LANCZOS)
        thumbnails.append(image)
        max_height = max(max_height, height)

    rows = math.ceil(len(thumbnails) / columns)
    cell_width = thumb_width + border * 2
    cell_height = max_height + label_height + border * 2
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "#2b2b2b")
    draw = ImageDraw.Draw(sheet)
    for index, image in enumerate(thumbnails):
        column = index % columns
        row = index // columns
        x = column * cell_width + border
        y = row * cell_height + border + label_height
        sheet.paste(image, (x, y))
        draw.text((x, row * cell_height + border), f"{index + 1}", fill="white")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, optimize=True)


def _render_html(html_path: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    page_paths: list[Path] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            browser_page = browser.new_page(viewport={"width": 1200, "height": 1200})
            browser_page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            browser_page.evaluate(
                """async () => {
                    if (document.fonts) await document.fonts.ready;
                    await Promise.all(Array.from(document.images).map(async (image) => {
                        if (!image.complete) {
                            await new Promise((resolve, reject) => {
                                image.addEventListener('load', resolve, {once: true});
                                image.addEventListener('error', reject, {once: true});
                            });
                        }
                        if (image.decode) await image.decode();
                    }));
                    if (window.typesetFitPositionedBlocks) {
                        window.typesetFitPositionedBlocks();
                    }
                    await new Promise((resolve) => requestAnimationFrame(
                        () => requestAnimationFrame(resolve)
                    ));
                }"""
            )
            pages = browser_page.locator(".typeset-page")
            for index in range(pages.count()):
                path = output_dir / f"page-{index + 1:03d}.png"
                pages.nth(index).screenshot(path=str(path))
                page_paths.append(path)

            evidence = browser_page.evaluate(
                """() => {
                    const pageNumber = (element) =>
                        element.closest('.typeset-page')?.dataset.page || '';
                    const splitIds = (value) => String(value || '')
                        .split(/[,\s]+/).map((item) => item.trim()).filter(Boolean);
                    const owners = [];
                    for (const element of document.querySelectorAll('[data-flow-blocks]')) {
                        for (const blockId of splitIds(element.dataset.flowBlocks)) {
                            owners.push({
                                block_id: blockId,
                                page: pageNumber(element),
                                owner: element.dataset.regionId || element.dataset.flowBlocks,
                                source: 'flow',
                            });
                        }
                    }
                    for (const element of document.querySelectorAll('[data-block-id]')) {
                        if (element.closest('[data-flow-blocks]')) continue;
                        owners.push({
                            block_id: element.dataset.blockId,
                            page: pageNumber(element),
                            owner: element.dataset.regionId || element.dataset.blockId,
                            source: 'element',
                        });
                    }
                    const byBlock = {};
                    for (const owner of owners) {
                        (byBlock[owner.block_id] ||= []).push(owner);
                    }
                    const duplicateOwners = Object.fromEntries(
                        Object.entries(byBlock).filter(([, values]) => values.length !== 1)
                    );
                    const issues = window.typesetCollectLayoutIssues
                        ? window.typesetCollectLayoutIssues()
                        : [];
                    return {
                        page_count: document.querySelectorAll('.typeset-page').length,
                        owners,
                        duplicate_owners: duplicateOwners,
                        layout_issues: issues,
                        fonts: {
                            status: document.fonts?.status || 'unsupported',
                            noto_serif_sc: document.fonts
                                ? document.fonts.check('16px "Noto Serif SC"') : false,
                            noto_sans_sc: document.fonts
                                ? document.fonts.check('16px "Noto Sans SC"') : false,
                        },
                        broken_images: Array.from(document.images)
                            .filter((image) => !image.complete || image.naturalWidth === 0)
                            .map((image) => image.getAttribute('src') || ''),
                    };
                }"""
            )
        finally:
            browser.close()
    evidence["page_images"] = [path.name for path in page_paths]
    return evidence


def _content_ownership_report(
    content_path: Path,
    browser_evidence: dict,
    structure_path: Path | None = None,
) -> dict:
    if structure_path is not None:
        from core.typeset_models import PageContentDocument, PageStructureDocument
        from core.typeset_visibility import expected_render_blocks

        content_doc = PageContentDocument.from_json(
            content_path.read_text(encoding="utf-8")
        )
        structure_doc = PageStructureDocument.from_json(
            structure_path.read_text(encoding="utf-8")
        )
        expected = expected_render_blocks(content_doc, structure_doc)
    else:
        content = json.loads(content_path.read_text(encoding="utf-8"))
        expected = {}
        for page in content.get("pages", []):
            page_number = int(page["page_index"]) + 1
            for block in page.get("blocks", []):
                if (
                    block.get("translatable")
                    and str(block.get("translated_text") or "").strip()
                    and block.get("layout_mode") not in {
                        "image_overlay_text", "hidden_source_text"
                    }
                ):
                    expected[str(block["id"])] = page_number

    owners: dict[str, list[dict]] = {}
    for owner in browser_evidence.get("owners", []):
        owners.setdefault(str(owner["block_id"]), []).append(owner)
    missing = [
        {"block_id": block_id, "page": page}
        for block_id, page in expected.items()
        if block_id not in owners
    ]
    duplicate = {
        block_id: values
        for block_id, values in owners.items()
        if block_id in expected and len(values) != 1
    }
    wrong_page = [
        {
            "block_id": block_id,
            "expected_page": page,
            "owner_page": values[0].get("page", ""),
        }
        for block_id, page in expected.items()
        if len(values := owners.get(block_id, [])) == 1
        and str(values[0].get("page", "")) != str(page)
    ]
    unexpected = sorted(block_id for block_id in owners if block_id not in expected)
    return {
        "expected_count": len(expected),
        "owned_count": sum(1 for block_id in expected if block_id in owners),
        "missing": missing,
        "duplicate": duplicate,
        "wrong_page": wrong_page,
        "unexpected": unexpected,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--human", type=Path, required=True)
    parser.add_argument("--style", type=Path, required=True)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    pdf_sets = {
        "original": _render_pdf(args.original, args.output / "original", 1.0),
        "human": _render_pdf(args.human, args.output / "human", 1.0),
        "style": _render_pdf(args.style, args.output / "style", 1.0),
    }
    for name, paths in pdf_sets.items():
        _contact_sheet(paths, args.output / f"{name}-contact-sheet.jpg")

    browser_evidence = _render_html(args.html, args.output / "html")
    _contact_sheet(
        [args.output / "html" / name for name in browser_evidence["page_images"]],
        args.output / "html-contact-sheet.jpg",
    )
    report = {
        "inputs": {
            "original": str(args.original.resolve()),
            "human": str(args.human.resolve()),
            "style": str(args.style.resolve()),
            "html": str(args.html.resolve()),
            "content": str(args.content.resolve()),
        },
        "page_counts": {name: len(paths) for name, paths in pdf_sets.items()},
        "browser": browser_evidence,
        "content_ownership": _content_ownership_report(args.content, browser_evidence),
    }
    (args.output / "baseline-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
