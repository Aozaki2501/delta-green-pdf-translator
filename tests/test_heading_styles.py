from core.extractor import PDFExtractor, build_extraction_diagnostics_report
from exporters.html import _html_block


def _line(text, size, y, flags=0, color=0, font="TestFont"):
    return {
        "bbox": (40, y, 260, y + size + 2),
        "spans": [
            {
                "text": text,
                "size": size,
                "flags": flags,
                "color": color,
                "font": font,
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


def test_right_column_card_follows_left_column_body():
    extractor = PDFExtractor.__new__(PDFExtractor)
    left_top = _block("Left column starts.", 36, 64, 274, 560)
    left_bottom = _block("Left column continues at bottom.", 36, 618, 274, 720)
    right_top = _block("Right column starts.", 303, 64, 541, 180)
    right_card = _block("Right column stat card.", 313, 526, 529, 614)

    sections = extractor._interleaved_body_and_card_sections(
        [left_top, left_bottom, right_top],
        [[right_card]],
        page_width=612,
        page_height=792,
    )
    text = "\n\n".join(sections)

    assert text.index("Left column continues") < text.index("Right column starts")
    assert text.index("Right column starts") < text.index("[CARD]")


def test_stat_group_uses_stat_block_marker():
    extractor = PDFExtractor.__new__(PDFExtractor)
    stat = _block("STR 11 CON 10 DEX 9 INT 14 POW 16 CHA 13", 313, 542, 529, 554)

    sections = extractor._interleaved_body_and_card_sections(
        [],
        [[stat]],
        page_width=612,
        page_height=792,
    )

    assert sections[0].startswith("[STAT_BLOCK]")


def test_image_region_uses_image_marker():
    extractor = PDFExtractor.__new__(PDFExtractor)
    rect = extractor._rect_from_bbox((70, 120, 540, 260))

    sections = extractor._interleaved_body_and_card_sections(
        [],
        [],
        page_width=612,
        page_height=792,
        image_regions=[rect],
    )

    assert sections == ["[IMAGE]\nIllustration placeholder\n[/IMAGE]"]


def test_extraction_diagnostics_report_lists_risks():
    report = build_extraction_diagnostics_report([
        {
            "page": 0,
            "layout": "columns",
            "notes": ["layout: columns"],
            "text_length": 0,
            "image_count": 0,
            "risks": ["未提取到正文"],
        }
    ], "book")

    assert "提取诊断报告" in report
    assert "未提取到正文" in report


def test_disinformation_in_body_sentence_is_not_card_label():
    extractor = PDFExtractor.__new__(PDFExtractor)

    assert not extractor._has_card_label("They pass disinformation to the Russians.")
    assert extractor._has_card_label("DISINFORMATION\nCase summary follows.")


def _block(text, x0, y0, x1, y1, size=10, font="TestFont"):
    return {
        "bbox": (x0, y0, x1, y1),
        "type": 0,
        "lines": [_line(text, size, y0, font=font)],
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


def test_right_column_heading_is_not_title_card():
    extractor = PDFExtractor.__new__(PDFExtractor)
    right_heading = _block("Important Individuals", 340, 70, 500, 120, size=28)
    centered_title = _block("Centered Scenario Title", 210, 70, 405, 120, size=28)
    left_title = _block("Presence", 72, 28, 342, 88, size=28)

    assert not extractor._is_title_card_block(
        right_heading,
        page_width=612,
        page_height=792,
        median_size=10,
    )
    assert extractor._is_title_card_block(
        centered_title,
        page_width=612,
        page_height=792,
        median_size=10,
    )
    assert extractor._is_title_card_block(
        left_title,
        page_width=612,
        page_height=792,
        median_size=10,
    )


def test_title_card_block_is_marked_full_width_title():
    extractor = PDFExtractor.__new__(PDFExtractor)
    block = dict(_block("The Insects from Shaggai", 210, 70, 405, 120, size=28))
    block["_dg_title_card"] = True

    text = extractor._extract_block_text(block, page_median_size=10)

    assert text.startswith("[FULL_WIDTH_TITLE]")
    assert "# The Insects from Shaggai" in text
    assert "# # " not in text
    assert text.endswith("[/FULL_WIDTH_TITLE]")


class _FakePage:
    def get_drawings(self):
        return []

    def get_images(self, full=True):
        return []


def test_card_grouping_does_not_swallow_other_column_heading():
    extractor = PDFExtractor.__new__(PDFExtractor)
    body = _block("Body text in the left column.", 36, 64, 274, 560, font="Sabon")
    body["lines"] = [
        _line("Body text in the left column.", 10, 64, font="Sabon"),
        _line("More body text in the left column.", 10, 78, font="Sabon"),
        _line("Even more body text in the left column.", 10, 92, font="Sabon"),
    ]
    left_heading = _block("The Tinderbox", 35, 598, 122, 616, size=18, font="Futura")
    left_body = _block("The left column continues here.", 36, 618, 274, 720, font="Sabon")
    stat_blocks = [
        _block("Robyn Bullock", 304, 506, 380, 520, font="Sabon"),
        _block("Distraught keeper of weird talents, age 19", 313, 526, 478, 538, font="Futura"),
        _block("STR 11 CON 10 DEX 9 INT 14 POW 16 CHA 13", 313, 542, 529, 554, font="Futura"),
        _block("HP 11 WP 17 SAN 65 BREAKING POINT 51", 313, 558, 508, 570, font="Futura"),
        _block("DISORDER: Depersonalization disorder.", 313, 574, 468, 586, font="Futura"),
        _block("SKILLS: Accounting 21%, Art 40%, Occult 39%.", 313, 590, 533, 614, font="Futura"),
        _block("ATTACKS: Unarmed 40%, damage 1D4-1.", 313, 618, 483, 630, font="Futura"),
    ]

    body_blocks, card_groups, _ = extractor._split_card_blocks(
        _FakePage(),
        [body, left_heading, left_body] + stat_blocks,
        page_width=612,
        page_height=792,
    )
    card_text = "\n".join(
        extractor._extract_block_text(block)
        for group in card_groups
        for block in group
    )

    assert left_heading in body_blocks
    assert "The Tinderbox" not in card_text
    assert "STR 11" in card_text


def test_adjacent_same_level_heading_lines_are_merged():
    extractor = PDFExtractor.__new__(PDFExtractor)

    text = extractor._merge_adjacent_heading_paragraphs("# Haley Production Company\n\n# and Arthur Tallent")

    assert text == "# Haley Production Company and Arthur Tallent"


def _mono_line(cells, xs, y):
    spans = []
    x1 = xs[0]
    for text, x in zip(cells, xs):
        width = max(len(text) * 5, 12)
        spans.append({
            "text": text,
            "size": 10,
            "flags": 0,
            "color": 0,
            "font": "Courier",
            "bbox": (x, y, x + width, y + 12),
        })
        x1 = max(x1, x + width)
    return {
        "bbox": (xs[0], y, x1, y + 12),
        "spans": spans,
    }


def _mono_table_block():
    return {
        "bbox": (40, 80, 560, 140),
        "type": 0,
        "lines": [
            _mono_line(["Name", "Position", "Background"], [40, 190, 330], 80),
            _mono_line(["Keith Bass", "Editor", "Scruffy socialist"], [40, 190, 330], 98),
        ],
    }


def test_non_body_font_table_is_not_grouped_as_card():
    extractor = PDFExtractor.__new__(PDFExtractor)
    body = _block("Body text.", 40, 180, 260, 240, font="Sabon")
    body["lines"] = [
        _line("Body text line one.", 10, 180, font="Sabon"),
        _line("Body text line two.", 10, 194, font="Sabon"),
        _line("Body text line three.", 10, 208, font="Sabon"),
    ]
    table = _mono_table_block()

    body_blocks, card_groups, _ = extractor._split_card_blocks(
        _FakePage(),
        [table, body],
        page_width=612,
        page_height=792,
    )

    assert table in body_blocks
    assert card_groups == []


def test_markdown_table_does_not_merge_with_following_body():
    extractor = PDFExtractor.__new__(PDFExtractor)
    table = _mono_table_block()
    body = _block("meet them alone, especially if there is more than one Agent.", 40, 160, 300, 190)

    text = extractor._blocks_to_extracted_text(
        [table, body],
        page_width=612,
        page_height=792,
        layout_aware=False,
    )

    assert "| Keith Bass | Editor | Scruffy socialist |" in text
    assert "| Keith Bass | Editor | Scruffy socialist | meet them alone" not in text
    assert "\n\nmeet them alone" in text
