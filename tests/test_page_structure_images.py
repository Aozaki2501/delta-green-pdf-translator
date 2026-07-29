import hashlib
from pathlib import Path

import pymupdf
import pytest
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


def test_zero_area_image_blocks_are_skipped(tmp_path):
    image_path = tmp_path / "image.png"
    Image.new("RGB", (20, 20), "red").save(image_path)

    pdf_path = tmp_path / "zero-area-image.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=100, height=100)
    page.insert_image(pymupdf.Rect(-20, 0, 0, 100), filename=str(image_path))
    doc.save(pdf_path)
    doc.close()

    output_dir = tmp_path / "out"
    with PageStructureExtractor(str(pdf_path), str(output_dir)) as extractor:
        structure = extractor.extract()

    assert structure.pages[0].images == []


def test_empty_cropped_images_are_skipped(tmp_path, monkeypatch):
    import core.page_structure as page_structure

    image_path = tmp_path / "image.png"
    Image.new("RGB", (20, 20), "red").save(image_path)

    pdf_path = tmp_path / "empty-crop-image.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=100, height=100)
    page.insert_image(pymupdf.Rect(10, 10, 60, 60), filename=str(image_path))
    doc.save(pdf_path)
    doc.close()

    def empty_crop(*args):
        image = Image.new("RGB", (10, 10), "red").crop((0, 0, 0, 10))
        return image, 0, 10

    monkeypatch.setattr(page_structure, "_crop_axis_aligned_pixmap_to_bbox", empty_crop)

    output_dir = tmp_path / "out"
    with PageStructureExtractor(str(pdf_path), str(output_dir)) as extractor:
        structure = extractor.extract()

    assert structure.pages[0].images == []


def test_redundant_solid_full_page_stencil_is_skipped(tmp_path):
    base_path = tmp_path / "base.png"
    stencil_path = tmp_path / "stencil.png"
    Image.new("RGB", (100, 100), (240, 240, 240)).save(base_path)
    Image.new("1", (100, 100), 0).save(stencil_path)

    pdf_path = tmp_path / "solid-stencil.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=100, height=100)
    page.insert_image(pymupdf.Rect(0, 0, 100, 100), filename=str(base_path))
    page.insert_text((20, 50), "Body text", fontsize=10)
    page.insert_image(pymupdf.Rect(0, 0, 100, 100), filename=str(stencil_path))
    doc.save(pdf_path)
    doc.close()

    output_dir = tmp_path / "out"
    with PageStructureExtractor(str(pdf_path), str(output_dir)) as extractor:
        structure = extractor.extract()

    assert len(structure.pages[0].images) == 1
    extracted_image = Image.open(output_dir / structure.pages[0].images[0].image_path).convert("RGB")
    assert extracted_image.getpixel((50, 50)) == (240, 240, 240)


def test_redundant_dark_full_page_border_stencil_is_skipped(tmp_path):
    base_path = tmp_path / "base.png"
    border_path = tmp_path / "border.png"
    Image.new("RGB", (100, 100), (240, 240, 240)).save(base_path)
    border = Image.new("1", (100, 100), 0)
    for x in range(96, 100):
        for y in range(0, 100):
            border.putpixel((x, y), 1)
    border.save(border_path)

    pdf_path = tmp_path / "dark-border-stencil.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=100, height=100)
    page.insert_image(pymupdf.Rect(0, 0, 100, 100), filename=str(base_path))
    page.insert_text((20, 50), "Body text", fontsize=10)
    page.insert_image(pymupdf.Rect(0, 0, 100, 100), filename=str(border_path))
    doc.save(pdf_path)
    doc.close()

    output_dir = tmp_path / "out"
    with PageStructureExtractor(str(pdf_path), str(output_dir)) as extractor:
        structure = extractor.extract()

    assert len(structure.pages[0].images) == 1


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



def test_image_metadata_prefers_exact_encoded_pdf_bytes_over_decoded_digest():
    encoded = b"encoded-pdf-image"
    block = {
        "number": 0,
        "image": encoded,
        "transform": (12.0, 0.0, 0.0, 10.0, 20.0, 30.0),
        "width": 120,
        "height": 100,
    }
    infos = [
        {
            "number": 0,
            "xref": 17,
            "digest": b"incompatible-decoded-samples",
            "transform": block["transform"],
            "width": 120,
            "height": 100,
        }
    ]

    matched = PageStructureExtractor._match_image_info(
        block,
        infos,
        b"different-pixmap-digest",
        {hashlib.md5(encoded).digest(): {17}},
    )

    assert matched["xref"] == 17


def test_image_metadata_rejects_mismatched_encoded_pdf_bytes():
    block = {
        "number": 0,
        "image": b"encoded-pdf-image",
        "transform": (12.0, 0.0, 0.0, 10.0, 20.0, 30.0),
        "width": 120,
        "height": 100,
    }
    infos = [
        {
            "number": 0,
            "xref": 17,
            "digest": b"incompatible-decoded-samples",
            "transform": block["transform"],
            "width": 120,
            "height": 100,
        }
    ]

    with pytest.raises(ValueError, match="exact identity maps to 0"):
        PageStructureExtractor._match_image_info(
            block,
            infos,
            b"different-pixmap-digest",
            {hashlib.md5(block["image"]).digest(): {18}},
        )
