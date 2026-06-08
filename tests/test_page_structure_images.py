from pathlib import Path

import pymupdf
from PIL import Image

from core.page_structure import PageStructureExtractor


def test_axis_aligned_image_is_cropped_to_visible_page_bbox(tmp_path):
    image_path = tmp_path / "wide.png"
    image = Image.new("RGB", (200, 100), "red")
    for x in range(100, 200):
        for y in range(100):
            image.putpixel((x, y), (0, 0, 255))
    image.save(image_path)

    pdf_path = tmp_path / "partial-image.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=100, height=100)
    page.insert_image(pymupdf.Rect(-100, 0, 100, 100), filename=str(image_path))
    doc.save(pdf_path)
    doc.close()

    output_dir = tmp_path / "out"
    with PageStructureExtractor(str(pdf_path), str(output_dir)) as extractor:
        structure = extractor.extract()

    extracted = structure.pages[0].images[0]
    extracted_image = Image.open(output_dir / extracted.image_path).convert("RGB")

    assert extracted.bbox == [0.0, 0.0, 100.0, 100.0]
    assert extracted_image.size == (100, 100)
    assert extracted_image.getpixel((50, 50)) == (0, 0, 255)


def test_extract_can_skip_image_assets_for_reading_layout_analysis(tmp_path):
    image_path = tmp_path / "image.png"
    Image.new("RGB", (20, 20), "red").save(image_path)

    pdf_path = tmp_path / "skip-images.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=100, height=100)
    page.insert_image(pymupdf.Rect(10, 10, 60, 60), filename=str(image_path))
    doc.save(pdf_path)
    doc.close()

    output_dir = tmp_path / "out"
    with PageStructureExtractor(str(pdf_path), str(output_dir)) as extractor:
        structure = extractor.extract(include_images=False)

    assert structure.pages[0].images == []
    assert not (output_dir / "assets" / "typeset_images").exists()


def test_text_regions_keep_line_geometry_and_style(tmp_path):
    pdf_path = tmp_path / "line-style.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=240, height=180)
    page.insert_text((30, 60), "Red title", fontsize=16, color=(1, 0, 0))
    page.insert_text((30, 86), "Body text", fontsize=11, color=(0, 0, 0))
    doc.save(pdf_path)
    doc.close()

    output_dir = tmp_path / "out"
    with PageStructureExtractor(str(pdf_path), str(output_dir)) as extractor:
        structure = extractor.extract()

    region = structure.pages[0].text_regions[0]

    assert region.lines
    assert region.lines[0].text.strip() == "Red title"
    assert region.lines[0].font_size == 16.0
    assert region.lines[0].color == "#ff0000"
    assert region.lines[0].spans
    assert region.lines[0].spans[0].text.strip() == "Red title"
    assert region.lines[0].spans[0].color == "#ff0000"
