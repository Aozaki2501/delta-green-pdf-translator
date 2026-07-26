"""Regression tests for merging PyMuPDF text blocks back into paragraphs.

PyMuPDF splits a hanging-indent paragraph into one text block per line. Left
as-is, every line becomes its own translation unit and sentences get cut apart
mid-clause, so the model can only translate line by line.

Geometry here mirrors page 4 of the real New Age artifact (9pt body, 15pt line
pitch, 48/54pt hanging indent) without reading any user document.
"""

from core.page_structure import _merge_flowing_text_regions
from core.typeset_models import TextLineBBox, TextRegionBBox


def _region(region_id: str, lines: list[tuple[str, float, float]]) -> TextRegionBBox:
    """Build a region from (text, x0, y0) triples using 9pt/15pt body metrics."""
    text_lines = [
        TextLineBBox(
            bbox=[x0, y0, x0 + 470.0, y0 + 11.7],
            text=text,
            font_size=9.0,
            bold=False,
            italic=False,
            color="#231f20",
        )
        for text, x0, y0 in lines
    ]
    return TextRegionBBox(
        id=region_id,
        bbox=[
            min(line.bbox[0] for line in text_lines),
            min(line.bbox[1] for line in text_lines),
            max(line.bbox[2] for line in text_lines),
            max(line.bbox[3] for line in text_lines),
        ],
        block_ids=[f"{region_id}_t"],
        lines=text_lines,
    )


def test_one_line_per_block_hanging_indent_is_merged_into_one_region():
    regions = [
        _region("r1", [("ETERNAL: Ghroth could, theoretically, be destroyed", 45.8, 401.9)]),
        _region("r2", [("enough force could shatter the thing's flesh into", 54.3, 416.9)]),
        _region("r3", [("require is not within humanity's grasp. Even if", 54.4, 431.9)]),
    ]

    merged = _merge_flowing_text_regions(regions)

    assert len(merged) == 1
    assert [line.text for line in merged[0].lines] == [
        "ETERNAL: Ghroth could, theoretically, be destroyed",
        "enough force could shatter the thing's flesh into",
        "require is not within humanity's grasp. Even if",
    ]
    assert merged[0].bbox[1] == 401.9
    assert merged[0].bbox[3] == 443.6
    assert merged[0].block_ids == ["r1_t", "r2_t", "r3_t"]


def test_merged_region_keeps_the_first_region_identity():
    regions = [
        _region("r1", [("first line of the paragraph", 54.0, 100.0)]),
        _region("r2", [("second line of the paragraph", 54.0, 115.0)]),
    ]

    merged = _merge_flowing_text_regions(regions)

    assert [region.id for region in merged] == ["r1"]


def test_paragraph_break_is_not_merged():
    regions = [
        _region("r1", [("End of the previous paragraph.", 54.0, 100.0)]),
        # A full blank line of separation is a real paragraph break.
        _region("r2", [("Start of the next paragraph.", 54.0, 140.0)]),
    ]

    assert len(_merge_flowing_text_regions(regions)) == 2


def test_side_by_side_columns_are_not_merged():
    regions = [
        _region("left", [("left column body text", 72.0, 120.0)]),
        _region("right", [("right column body text", 340.0, 120.0)]),
    ]

    assert len(_merge_flowing_text_regions(regions)) == 2


def test_heading_is_not_absorbed_into_following_body_text():
    heading = TextLineBBox(
        bbox=[54.0, 100.0, 200.0, 122.0],
        text="Ghroth",
        font_size=15.0,
        bold=True,
        italic=False,
        color="#231f20",
    )
    regions = [
        TextRegionBBox(id="heading", bbox=[54.0, 100.0, 200.0, 122.0], block_ids=["h"], lines=[heading]),
        _region("body", [("Ghroth has few worshippers, limited mostly to", 54.0, 126.0)]),
    ]

    assert [region.id for region in _merge_flowing_text_regions(regions)] == ["heading", "body"]


def test_bullet_list_is_not_merged_into_following_body_paragraph():
    """A block starting further left is a new indent regime, not a wrapped line."""
    regions = [
        _region("bullet", [
            ("> Any other Agent loses time in her stare.", 80.0, 400.0),
            ("extreme nightmare. The details are forgotten.", 90.4, 415.0),
        ]),
        _region("body", [("The Agent comes around after only a few seconds", 72.4, 430.0)]),
    ]

    assert [region.id for region in _merge_flowing_text_regions(regions)] == ["bullet", "body"]
