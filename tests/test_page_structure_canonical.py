"""Behavior tests for canonical page-structure schema v2."""

import hashlib
import json

import pymupdf
import pytest
from PIL import Image

from core.page_structure import PageStructureExtractor, _trace_matches_span
from core.typeset_models import (
    BackgroundLayer,
    DisplayListObject,
    PageStructure,
    PageStructureDocument,
    VisualAnchor,
)


def _make_pdf(path, image_path):
    doc = pymupdf.open()
    page = doc.new_page(width=240, height=180)
    page.set_cropbox(pymupdf.Rect(10, 20, 230, 170))
    page.set_rotation(90)
    page.insert_image(pymupdf.Rect(20, 30, 100, 110), filename=str(image_path))
    page.insert_text((40, 60), "Rotated text", fontsize=16, color=(1, 0, 0), rotate=90)
    page.draw_rect(
        pymupdf.Rect(120, 40, 200, 100),
        color=(0, 0, 1),
        fill=(0, 1, 0),
        width=2,
    )
    doc.save(path)
    doc.close()


def test_canonical_fields_are_extracted_and_roundtrip(tmp_path):
    image_path = tmp_path / "source.png"
    Image.new("RGBA", (32, 24), (255, 0, 0, 128)).save(image_path)
    pdf_path = tmp_path / "canonical.pdf"
    _make_pdf(pdf_path, image_path)

    with PageStructureExtractor(str(pdf_path), str(tmp_path / "out")) as extractor:
        document = extractor.extract()

    page = document.pages[0]
    assert document.source_sha256 == hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assert page.media_box == [0.0, 0.0, 240.0, 180.0]
    assert page.crop_box == [10.0, 20.0, 230.0, 170.0]
    assert page.rotation == 90
    assert page.user_unit == 1.0
    assert page.display_list
    assert [obj.seqno for obj in page.display_list] == list(range(len(page.display_list)))
    assert all(set(obj.__dict__) == {
        "id", "kind", "bbox", "transform", "seqno", "layer", "clip",
        "opacity", "blend", "source_ref", "unsupported",
    } for obj in page.display_list)
    text_objects = [obj for obj in page.display_list if "text" in obj.kind]
    assert text_objects and text_objects[0].source_ref == page.text_regions[0].id
    assert all(
        obj.source_ref
        for obj in page.display_list
        if "image" in obj.kind or "path" in obj.kind
    )
    assert page.images[0].transform
    assert page.images[0].xref
    assert page.images[0].digest
    assert page.images[0].bpc == 8
    assert page.images[0].xres == 96
    assert page.images[0].yres == 96
    span = page.text_regions[0].lines[0].spans[0]
    assert span.font
    assert span.origin
    assert span.ascender is not None
    assert span.descender is not None
    assert span.chars and span.chars[0]["bbox"]
    assert span.seqno is not None
    assert span.seqnos == [span.seqno]
    assert page.decorations[0].seqno is not None
    assert page.decorations[0].path_commands
    assert page.visual_anchors == []

    restored = PageStructureDocument.from_json(document.to_json())
    assert restored == document


def test_display_list_preserves_unsupported_objects_and_visual_anchor_defaults():
    obj = DisplayListObject(
        id="p0001_dl0001", kind="future-op", bbox=[0, 0, 1, 1], unsupported=True,
    )
    page = PageStructure(
        page_index=0,
        width=1,
        height=1,
        background=BackgroundLayer(),
        images=[],
        decorations=[],
        text_regions=[],
        display_list=[obj],
        visual_anchors=[VisualAnchor("a1", 0, "asset", placement=[1, 2])],
    )
    # Existing constructor compatibility permits a missing background value.
    document = PageStructureDocument(2, "x.pdf", 1, [page], source_sha256="abc")
    data = json.loads(document.to_json())
    assert data["source_sha256"] == "abc"
    assert data["pages"][0]["display_list"][0]["unsupported"] is True
    assert PageStructureDocument.from_json(document.to_json()) == document


def test_image_metadata_matching_uses_exact_content_and_geometry_identity():
    block = {
        "number": 8,
        "width": 765,
        "height": 169,
        "transform": (366.72, 0.0, -0.0, -80.88, 198.36, 792.36),
    }
    wrong_same_number = {
        "number": 8,
        "width": 32,
        "height": 32,
        "transform": (32.0, 0.0, 0.0, 32.0, 0.0, 0.0),
        "digest": b"wrong",
        "xref": 7,
    }
    exact_different_number = {
        "number": 10,
        "width": 765,
        "height": 169,
        "transform": block["transform"],
        "digest": b"exact",
        "xref": 28,
    }

    matched = PageStructureExtractor._match_image_info(
        block,
        [wrong_same_number, exact_different_number],
        b"exact",
    )

    assert matched is exact_different_number


def test_image_metadata_matching_accepts_equivalent_duplicate_draws():
    block = {
        "number": 8,
        "width": 20,
        "height": 10,
        "transform": (20.0, 0.0, 0.0, 10.0, 1.0, 2.0),
    }
    duplicate = {
        "number": 9,
        "width": 20,
        "height": 10,
        "transform": block["transform"],
        "digest": b"same",
        "xref": 17,
    }

    matched = PageStructureExtractor._match_image_info(
        block,
        [duplicate, dict(duplicate, number=10)],
        b"same",
    )

    assert matched["xref"] == 17


def test_image_metadata_matching_rejects_conflicting_exact_identity():
    block = {
        "number": 8,
        "width": 20,
        "height": 10,
        "transform": (20.0, 0.0, 0.0, 10.0, 1.0, 2.0),
    }
    candidate = {
        "number": 9,
        "width": 20,
        "height": 10,
        "transform": block["transform"],
        "digest": b"same",
        "xref": 17,
    }

    with pytest.raises(ValueError, match="conflicting metadata"):
        PageStructureExtractor._match_image_info(
            block,
            [candidate, dict(candidate, number=10, xref=18)],
            b"same",
        )


def test_image_metadata_matching_handles_page_outside_text_number_shift(tmp_path):
    image_path = tmp_path / "source.png"
    Image.new("RGB", (16, 12), (255, 0, 0)).save(image_path)
    pdf_path = tmp_path / "shifted-image-number.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=100, height=100)
    for index in range(8):
        page.insert_text((1, 5 + index * 10), f"V{index}", fontsize=6)
    page.insert_text((1, 120), "OUT", fontsize=8)
    page.insert_image(pymupdf.Rect(10, 40, 60, 90), filename=str(image_path))
    doc.save(pdf_path)
    doc.close()

    with pymupdf.open(pdf_path) as check_doc:
        check_page = check_doc[0]
        image_block = next(
            block for block in check_page.get_text("dict")["blocks"]
            if block.get("type") == 1
        )
        image_info = check_page.get_image_info(hashes=True, xrefs=True)[0]
        assert image_block["number"] != image_info["number"]

    with PageStructureExtractor(str(pdf_path), str(tmp_path / "out")) as extractor:
        document = extractor.extract()

    assert len(document.pages[0].images) == 1
    assert document.pages[0].images[0].xref == image_info["xref"]
    assert document.pages[0].images[0].digest == image_info["digest"].hex()


def test_text_trace_matching_models_actualtext_by_font_flags_and_origin():
    span = {
        "font": "FuturaStd-Book",
        "flags": 4,
        "chars": [{"c": "»", "origin": (1.0, 2.0)}],
    }
    trace = {
        "font": "FuturaStd-Book",
        "flags": 4,
        "chars": ((32, 1, (1.0, 2.0), (0.0, 0.0, 1.0, 1.0)),),
    }

    assert _trace_matches_span(trace, span)
    superscript_span = dict(span, flags=span["flags"] | pymupdf.TEXT_FONT_SUPERSCRIPT)
    assert _trace_matches_span(trace, superscript_span)
    assert not _trace_matches_span(dict(trace, font="Other"), span)
    assert not _trace_matches_span(dict(trace, flags=0), span)
    shifted = dict(trace, chars=((32, 1, (1.0, 2.01), (0.0, 0.0, 1.0, 1.0)),))
    assert not _trace_matches_span(shifted, span)
