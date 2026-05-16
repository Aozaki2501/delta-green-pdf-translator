from core.extractor import PDFExtractor
from exporters.html import _html_block


def _line(text, size, y, flags=0, color=0):
    return {
        "bbox": (40, y, 260, y + size + 2),
        "spans": [
            {
                "text": text,
                "size": size,
                "flags": flags,
                "color": color,
                "bbox": (40, y, 260, y + size + 2),
            }
        ],
    }


def test_extract_block_marks_four_heading_levels():
    extractor = PDFExtractor.__new__(PDFExtractor)
    block = {
        "bbox": (40, 40, 300, 220),
        "lines": [
            _line("Book Part", 27, 40),
            _line("Red Feature", 18, 70, color=0xEB4F24),
            _line("Tall Section", 20, 100),
            _line("Small Card Title", 13, 130, flags=2),
            _line("Regular body text continues here.", 10, 160),
        ],
    }

    text = extractor._extract_block_text(block, page_median_size=10)

    assert "# Book Part" in text
    assert "## Red Feature" in text
    assert "### Tall Section" in text
    assert "#### Small Card Title" in text
    assert "Regular body text continues here." in text


def test_large_heading_with_abbreviation_period_is_preserved():
    extractor = PDFExtractor.__new__(PDFExtractor)
    block = {
        "bbox": (40, 40, 300, 130),
        "lines": [
            _line("MAJESTIC is not.", 10, 40),
            _line("After the U.S.S.R.", 30, 70),
            _line("Since the breakup of the U.S.S.R., SV-8 has fallen on hard times.", 10, 105),
        ],
    }

    text = extractor._extract_block_text(block, page_median_size=10)

    assert "MAJESTIC is not." in text
    assert "# After the U.S.S.R." in text
    assert "not. After" not in text


def test_html_renders_fourth_level_heading():
    html = _html_block("#### 小标题\n这是一段正文。")

    assert "<h4>小标题</h4>" in html
    assert "<p>这是一段正文。</p>" in html


def test_card_sections_keep_page_order_and_context():
    extractor = PDFExtractor.__new__(PDFExtractor)
    before = {
        "bbox": (40, 40, 260, 60),
        "lines": [_line("Body before card.", 10, 40)],
    }
    card = {
        "bbox": (40, 90, 260, 120),
        "lines": [_line("Card information.", 10, 90)],
    }
    after = {
        "bbox": (40, 150, 260, 170),
        "lines": [_line("Body after card.", 10, 150)],
    }

    sections = extractor._interleaved_body_and_card_sections(
        [before, after],
        [[card]],
        page_width=612,
        page_height=792,
    )
    text = "\n\n".join(sections)
    context = extractor._context_from_extracted_text(text, "columns")

    assert text.index("Body before card.") < text.index("[CARD]")
    assert text.index("[/CARD]") < text.index("Body after card.")
    assert "Card information." in context


def test_disinformation_in_body_sentence_is_not_card_label():
    extractor = PDFExtractor.__new__(PDFExtractor)

    assert not extractor._has_card_label("They pass disinformation to the Russians.")
    assert extractor._has_card_label("DISINFORMATION\nCase summary follows.")


def _block(text, x0, y0, x1, y1, size=10):
    return {
        "bbox": (x0, y0, x1, y1),
        "type": 0,
        "lines": [_line(text, size, y0)],
    }


def test_single_block_per_column_still_reads_left_column_first():
    extractor = PDFExtractor.__new__(PDFExtractor)
    left_top = _block("left top", 70, 100, 300, 140)
    right = _block("right column", 340, 110, 560, 300)
    left_bottom = _block("left bottom", 72, 180, 300, 240)

    sorted_blocks = extractor._sort_blocks_layout_aware(
        [left_top, right, left_bottom],
        page_width=612,
        page_height=792,
    )

    assert sorted_blocks == [left_top, left_bottom, right]


def test_adjacent_same_level_heading_lines_are_merged():
    extractor = PDFExtractor.__new__(PDFExtractor)

    text = extractor._merge_adjacent_heading_paragraphs("# Haley Production Company\n\n# and Arthur Tallent")

    assert text == "# Haley Production Company and Arthur Tallent"
