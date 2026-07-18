import hashlib
import json
import xml.etree.ElementTree as ET

import pymupdf
from PIL import Image
import pytest

from core.page_visuals import PageVisualExtractor


SVG_NS = "http://www.w3.org/2000/svg"


def _local_names(svg_bytes: bytes) -> list[str]:
    root = ET.fromstring(svg_bytes)
    return [node.tag.rsplit("}", 1)[-1] for node in root.iter()]


def _make_visual_pdf(tmp_path, *, with_text: bool = True):
    image_path = tmp_path / "background.png"
    Image.new("RGB", (40, 30), (240, 180, 80)).save(image_path)
    pdf_path = tmp_path / ("visual.pdf" if with_text else "image-only.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=160, height=120)
    page.insert_image(pymupdf.Rect(0, 0, 160, 120), filename=str(image_path))
    page.draw_rect(
        pymupdf.Rect(20, 20, 90, 70),
        color=(0, 0, 1),
        fill=(1, 0, 0),
        width=2,
    )
    if with_text:
        page.insert_text((28, 100), "Remove this text", fontsize=14)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def test_clean_svg_removes_text_and_keeps_visual_nodes(tmp_path):
    pdf_path = _make_visual_pdf(tmp_path)
    output_dir = tmp_path / "out"

    with PageVisualExtractor(pdf_path, output_dir) as extractor:
        manifest = extractor.extract(0, 1)[0]

    svg_path = output_dir / "assets" / "page_visuals" / "p0001.svg"
    manifest_path = output_dir / "assets" / "page_visuals" / "p0001.manifest.json"
    svg_bytes = svg_path.read_bytes()
    names = _local_names(svg_bytes)
    assert "text" not in [name.lower() for name in names]
    assert "image" in names
    assert "path" in names
    assert manifest["width"] == 160
    assert manifest["height"] == 120
    assert manifest["removed_text_nodes"] >= 1
    assert manifest["text_trace_count"] == manifest["removed_text_nodes"]
    assert manifest["remaining_text_nodes"] == 0
    assert manifest["sha256"] == hashlib.sha256(svg_bytes).hexdigest()
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == manifest

    # A second extraction must produce byte-for-byte identical SVG and hash.
    second_dir = tmp_path / "out-second"
    with PageVisualExtractor(pdf_path, second_dir) as extractor:
        second_manifest = extractor.extract(0, 1)[0]
    assert second_manifest["sha256"] == manifest["sha256"]
    assert (second_dir / "assets" / "page_visuals" / "p0001.svg").read_bytes() == svg_bytes


def test_pure_image_page_allows_zero_removed_text_nodes(tmp_path):
    pdf_path = _make_visual_pdf(tmp_path, with_text=False)
    output_dir = tmp_path / "out"

    with PageVisualExtractor(pdf_path, output_dir) as extractor:
        manifest = extractor.extract()[0]

    assert manifest["removed_text_nodes"] == 0
    assert manifest["remaining_text_nodes"] == 0


def test_malformed_svg_fails_without_writing_asset(tmp_path, monkeypatch):
    pdf_path = _make_visual_pdf(tmp_path)
    output_dir = tmp_path / "out"
    monkeypatch.setattr(PageVisualExtractor, "_render_page", lambda self, page: "<svg>")

    with PageVisualExtractor(pdf_path, output_dir) as extractor:
        with pytest.raises(ValueError, match="parse SVG"):
            extractor.extract()
    assert not (output_dir / "assets" / "page_visuals" / "p0001.svg").exists()


def test_text_trace_without_svg_text_is_mapping_failure(tmp_path, monkeypatch):
    pdf_path = _make_visual_pdf(tmp_path)
    output_dir = tmp_path / "out"
    clean_svg = (
        f'<svg xmlns="{SVG_NS}" width="160" height="120" viewBox="0 0 160 120">'
        "<path d=\"M0 0\"/></svg>"
    )
    monkeypatch.setattr(PageVisualExtractor, "_render_page", lambda self, page: clean_svg)

    with PageVisualExtractor(pdf_path, output_dir) as extractor:
        with pytest.raises(ValueError, match="text mapping mismatch"):
            extractor.extract()


def test_partial_svg_text_mapping_is_rejected(tmp_path, monkeypatch):
    pdf_path = _make_visual_pdf(tmp_path)
    one_text_svg = (
        f'<svg xmlns="{SVG_NS}" width="160" height="120" viewBox="0 0 160 120">'
        '<text x="1" y="1">one</text><text x="2" y="2">extra</text></svg>'
    )
    monkeypatch.setattr(PageVisualExtractor, "_render_page", lambda self, page: one_text_svg)

    with PageVisualExtractor(pdf_path, tmp_path / "out") as extractor:
        with pytest.raises(ValueError, match="text mapping mismatch"):
            extractor.extract()


def test_missing_viewbox_fails(tmp_path, monkeypatch):
    pdf_path = _make_visual_pdf(tmp_path, with_text=False)
    svg_without_viewbox = (
        f'<svg xmlns="{SVG_NS}" width="160" height="120"><image width="1" height="1"/></svg>'
    )
    monkeypatch.setattr(
        PageVisualExtractor,
        "_render_page",
        lambda self, page: svg_without_viewbox,
    )
    with PageVisualExtractor(pdf_path, tmp_path / "out") as extractor:
        with pytest.raises(ValueError, match="viewBox"):
            extractor.extract()
