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


def test_fodg_monospace_stat_card_is_detected_from_split_blocks():
    extractor = PDFExtractor.__new__(PDFExtractor)
    body = _block("Ordinary body text outside the stat card.", 45, 90, 202, 120, font="FuturaPT-Book")
    title = _block("MING YUAN", 91, 288, 154, 303, font="CourierPrime-Bold")
    stats = [
        _block("General Abilities:", 54, 310, 174, 323, font="CourierPrime-Bold"),
        _block("Athletics 8, Fighting 8, Health 6", 63, 322, 195, 347, font="CourierPrime"),
        _block("Hypergeometry: 12", 54, 351, 156, 364, font="CourierPrime-Bold"),
        _block("Hit Threshold: 4", 54, 367, 150, 380, font="CourierPrime-Bold"),
        _block("Alertness Modifier: +2", 54, 384, 180, 397, font="CourierPrime-Bold"),
        _block("Stealth Modifier: +0", 54, 400, 168, 413, font="CourierPrime-Bold"),
        _block("Attack: Sacrificial", 54, 417, 168, 430, font="CourierPrime-Bold"),
        _block("Dagger (-1)", 63, 429, 129, 442, font="CourierPrime"),
        _block("Armor: His bizarre", 54, 445, 168, 458, font="CourierPrime-Bold"),
        _block("flesh means he’s got Armour 2.", 63, 457, 183, 482, font="CourierPrime"),
    ]

    body_blocks, card_groups, _ = extractor._split_card_blocks(
        _FakePage(),
        [body, title] + stats,
        page_width=612,
        page_height=792,
    )
    sections = extractor._interleaved_body_and_card_sections(
        body_blocks,
        card_groups,
        page_width=612,
        page_height=792,
    )

    text = "\n\n".join(sections)
    assert body in body_blocks
    assert "[STAT_BLOCK]" in text
    assert "MING YUAN" in text
    assert "General Abilities" in text


def test_fodg_futura_stat_card_is_detected_from_split_blocks():
    extractor = PDFExtractor.__new__(PDFExtractor)
    body = _block("The caster writes a ritual sign on the wall.", 399, 376, 553, 571, font="FuturaPT-Book")
    title = _block("Large Poppet", 399, 149, 496, 170, font="FuturaPT-Demi")
    stats = [
        _block("Abilities: Athletics 4,", 399, 172, 494, 186, font="FuturaPT-Demi"),
        _block("Health 5, Melee Weapons 3, Unarmed Combat 5 Hit Threshold: 4 Alertness Modifier: -1 Stealth Modifier: +1 Attack: Paper Cut (d-1) or knife", 399, 186, 538, 270, font="FuturaPT-Book"),
        _block("(d-1) Armor: Resilient (anything", 399, 270, 516, 298, font="FuturaPT-Book"),
        _block("except fire) Stability Loss: +0", 399, 298, 476, 326, font="FuturaPT-Book"),
    ]

    body_blocks, card_groups, _ = extractor._split_card_blocks(
        _FakePage(),
        [title] + stats + [body],
        page_width=612,
        page_height=792,
    )
    sections = extractor._interleaved_body_and_card_sections(
        body_blocks,
        card_groups,
        page_width=612,
        page_height=792,
    )

    text = "\n\n".join(sections)
    assert body in body_blocks
    assert "[STAT_BLOCK]" in text
    assert "Large Poppet" in text
    assert "Stability Loss" in text


def test_fodg_skill_list_without_stat_labels_is_not_stat_block():
    extractor = PDFExtractor.__new__(PDFExtractor)
    skill_lines = [
        _block("Drive", 84, 465, 130, 477, font="FuturaPT-Book"),
        _block("5", 150, 465, 160, 477, font="FuturaPT-Book"),
        _block("Firearms", 84, 525, 145, 537, font="FuturaPT-Book"),
        _block("12", 150, 525, 163, 537, font="FuturaPT-Book"),
        _block("Melee Weapons", 84, 585, 150, 597, font="FuturaPT-Book"),
        _block("9", 155, 585, 162, 597, font="FuturaPT-Book"),
        _block("Unarmed Combat", 84, 719, 156, 731, font="FuturaPT-Book"),
        _block("8", 160, 719, 166, 731, font="FuturaPT-Book"),
    ]

    body_blocks, card_groups, _ = extractor._split_card_blocks(
        _FakePage(),
        skill_lines,
        page_width=612,
        page_height=792,
    )

    assert body_blocks == skill_lines
    assert card_groups == []


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


def test_text_layer_over_image_region_is_not_exported_as_art():
    extractor = PDFExtractor.__new__(PDFExtractor)
    rect = extractor._rect_from_bbox((80, 100, 540, 360))
    blocks = [
        _block("A long table or card line that is real selectable text.", 100, 120 + idx * 36, 500, 138 + idx * 36)
        for idx in range(6)
    ]

    assert extractor._image_region_contains_text_layer(rect, blocks)


def test_overlapping_text_layer_without_centers_blocks_image_export():
    extractor = PDFExtractor.__new__(PDFExtractor)
    rect = extractor._rect_from_bbox((120, 100, 360, 220))
    blocks = [
        _block("Selectable text overlaps the raster card and should not be exported.", 40, 112 + idx * 24, 320, 130 + idx * 24)
        for idx in range(4)
    ]

    assert extractor._image_region_contains_text_layer(rect, blocks)


def test_sparse_caption_does_not_block_image_export():
    extractor = PDFExtractor.__new__(PDFExtractor)
    rect = extractor._rect_from_bbox((80, 100, 540, 360))
    blocks = [
        _block("Figure 1.", 210, 330, 330, 346),
    ]

    assert not extractor._image_region_contains_text_layer(rect, blocks)


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


class _FakeRect:
    width = 612
    height = 792


class _FakeLayoutPage:
    rect = _FakeRect()

    def __init__(self, blocks):
        self._blocks = blocks

    def get_text(self, kind, flags=0):
        return {"blocks": self._blocks}

    def get_drawings(self):
        return []

    def get_images(self, full=True):
        return []


class _FakeDoc:
    def __init__(self, pages):
        self._pages = pages

    def __getitem__(self, index):
        return self._pages[index]


class _NoopChapterDetector:
    def analyze_page(self, page_num, page_dict):
        return None


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


def test_monospace_table_block_is_detected():
    extractor = PDFExtractor.__new__(PDFExtractor)

    assert extractor._is_table_block(_mono_table_block(), page_width=612)


def test_monospace_body_paragraph_is_not_detected_as_table():
    extractor = PDFExtractor.__new__(PDFExtractor)
    paragraph = {
        "bbox": (63, 120, 519, 158),
        "type": 0,
        "lines": [
            _mono_line(
                [
                    "Almousin is a holy name used in the Grand Grimoire to conjure demons.",
                    "th",
                    "-century",
                ],
                [63, 464, 471],
                120,
            ),
            _mono_line(
                ["ry", "Grand Grimoire", "to conjure and command demons."],
                [63, 81, 165],
                134,
            ),
            _mono_line(
                ["Arabic", "al-Muhsi,", "the Numberer, one of the Names of Allah."],
                [63, 105, 159],
                148,
            ),
        ],
    }
    name_paragraph = _block(
        "Metraton is a less common spelling of Metatron, in Kabbalah the name of an emanation of God.",
        63,
        162,
        519,
        198,
        font="Courier",
    )

    assert not extractor._is_table_block(paragraph, page_width=612)
    assert not extractor._is_table_block(name_paragraph, page_width=612)


def test_monospace_body_with_plus_sign_is_not_detected_as_table():
    extractor = PDFExtractor.__new__(PDFExtractor)
    paragraph = _block(
        "After a long flight (10+ hours), check for jet lag. A blade does 4+ Health damage.",
        101,
        399,
        387,
        461,
        font="Courier",
    )

    assert not extractor._is_table_block(paragraph, page_width=612)


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


def test_two_column_single_line_blocks_stay_columns():
    extractor = PDFExtractor.__new__(PDFExtractor)
    blocks = []
    for idx in range(8):
        blocks.append(_block(f"Left column line {idx} keeps flowing.", 54, 110 + idx * 22, 270, 124 + idx * 22, font="Futura"))
        blocks.append(_block(f"Right column line {idx} keeps flowing.", 330, 110 + idx * 22, 550, 124 + idx * 22, font="Futura"))
    extractor.doc = _FakeDoc([_FakeLayoutPage(blocks)])

    assert extractor.detect_page_layout(0) == "columns"


def test_three_column_blocks_are_detected_and_sorted_left_to_right():
    extractor = PDFExtractor.__new__(PDFExtractor)
    blocks = []
    for idx in range(3):
        y = 100 + idx * 30
        blocks.append(_block(f"left {idx}", 70, y, 220, y + 18, font="Futura"))
        blocks.append(_block(f"middle {idx}", 248, y, 398, y + 18, font="Futura"))
        blocks.append(_block(f"right {idx}", 426, y, 576, y + 18, font="Futura"))
    extractor.doc = _FakeDoc([_FakeLayoutPage(blocks)])

    sorted_blocks = extractor._sort_blocks_layout_aware(
        blocks,
        page_width=612,
        page_height=792,
    )

    assert extractor.detect_page_layout(0) == "three_columns"
    assert [extractor._extract_block_text(block) for block in sorted_blocks] == [
        "left 0",
        "left 1",
        "left 2",
        "middle 0",
        "middle 1",
        "middle 2",
        "right 0",
        "right 1",
        "right 2",
    ]


def test_body_text_with_contents_word_is_not_classified_as_toc():
    extractor = PDFExtractor.__new__(PDFExtractor)
    body = _block(
        "The bizarre contents of the vessel are dangerous but this is ordinary body text.",
        54,
        110,
        540,
        160,
        font="Futura",
    )
    extractor.doc = _FakeDoc([_FakeLayoutPage([body])])

    assert not extractor._is_contents_block(body)
    assert extractor.detect_page_layout(0) != "toc"


def test_contents_phrase_heading_is_not_classified_as_toc_title():
    extractor = PDFExtractor.__new__(PDFExtractor)

    assert not extractor._looks_like_contents_title("contents of the next shipment")
    assert extractor._looks_like_contents_title("// Contents // // Iconoclasts //")


def test_table_numbers_without_contents_title_are_not_classified_as_toc():
    extractor = PDFExtractor.__new__(PDFExtractor)
    table = _block("", 54, 110, 540, 220, font="Futura")
    table["lines"] = [
        _line("Buddhist Militia Buddhist Militia", 10, 110, font="Futura"),
        _line("4", 10, 124, font="Futura"),
        _line("Buddhist Militia Viet Cong", 10, 138, font="Futura"),
        _line("5", 10, 152, font="Futura"),
        _line("Cowboys Ghouls", 10, 166, font="Futura"),
        _line("6", 10, 180, font="Futura"),
    ]
    extractor.doc = _FakeDoc([_FakeLayoutPage([table])])

    assert not extractor._is_contents_block(table)
    assert extractor.detect_page_layout(0) != "toc"


def test_contents_title_with_decorators_is_classified_as_toc():
    extractor = PDFExtractor.__new__(PDFExtractor)
    title = _block("// Contents // // Iconoclasts // Contents", 40, 40, 540, 70, font="Courier")
    title["lines"] = [_line("// Contents // // Iconoclasts // Contents", 12, 40, font="Courier")]
    toc = _block("Introduction ........ 2\nThe Cornucopia House ........ 4", 40, 100, 540, 150, font="Courier")
    toc["lines"] = [
        _line("Introduction ........ 2", 10, 100, font="Courier"),
        _line("The Cornucopia House ........ 4", 10, 114, font="Courier"),
    ]
    extractor.doc = _FakeDoc([_FakeLayoutPage([title, toc])])

    assert extractor.detect_page_layout(0) == "toc"


def test_contents_page_does_not_require_monospace_font():
    extractor = PDFExtractor.__new__(PDFExtractor)
    title = _block("// Contents // // Iconoclasts // Contents", 40, 40, 540, 70, font="SourceSerif")
    title["lines"] = [_line("// Contents // // Iconoclasts // Contents", 12, 40, font="SourceSerif")]
    toc = _block("Introduction ........ 2\nThe Cornucopia House ........ 4", 40, 100, 540, 150, font="SourceSerif")
    toc["lines"] = [
        _line("Introduction ........ 2", 10, 100, font="SourceSerif"),
        _line("The Cornucopia House ........ 4", 10, 114, font="SourceSerif"),
    ]
    extractor.doc = _FakeDoc([_FakeLayoutPage([title, toc])])

    assert extractor.detect_page_layout(0) == "toc"


def test_contents_continuation_title_can_sit_in_top_margin():
    extractor = PDFExtractor.__new__(PDFExtractor)
    title = _block("// Contents // // Iconoclasts //", 40, 10, 540, 28, font="SourceSerif")
    title["lines"] = [_line("// Contents // // Iconoclasts //", 12, 10, font="SourceSerif")]
    toc = _block("Appendix ........ 174\nThe Father of War ........ 178", 40, 100, 540, 150, font="SourceSerif")
    toc["lines"] = [
        _line("Appendix ........ 174", 10, 100, font="SourceSerif"),
        _line("The Father of War ........ 178", 10, 114, font="SourceSerif"),
    ]
    extractor.doc = _FakeDoc([_FakeLayoutPage([title, toc])])

    assert extractor.detect_page_layout(0) == "toc"


def test_index_with_page_numbers_on_next_lines_is_classified_as_toc():
    extractor = PDFExtractor.__new__(PDFExtractor)
    title = _block("Index", 36, 30, 290, 44, font="Captureit")
    toc = _block("", 36, 60, 290, 210, font="SpecialElite-Regular")
    toc["lines"] = [
        _line("Introduction\b", 10, 60, font="SpecialElite-Regular"),
        _line("8", 10, 72, font="SpecialElite-Regular"),
        _line("•\tBasic Training\b", 10, 84, font="SpecialElite-Regular"),
        _line("8", 10, 96, font="SpecialElite-Regular"),
        _line("Character Creation\b", 10, 108, font="SpecialElite-Regular"),
        _line("12", 10, 120, font="SpecialElite-Regular"),
        _line("•\tPersonal Info\b", 10, 132, font="SpecialElite-Regular"),
        _line("12", 10, 144, font="SpecialElite-Regular"),
    ]
    extractor.doc = _FakeDoc([_FakeLayoutPage([title, toc])])

    assert extractor.detect_page_layout(0) == "toc"
    extracted = extractor._extract_contents_page([title, toc])
    assert "Introduction ........ 8" in extracted
    assert "Basic Training ........ 8" in extracted


def test_extract_page_keeps_full_page_art_placeholder_when_text_is_empty():
    extractor = PDFExtractor.__new__(PDFExtractor)
    extractor.doc = _FakeDoc([_FakeLayoutPage([])])
    extractor.chapter_detector = _NoopChapterDetector()
    extractor._page_body_context = {}
    extractor._page_layout_notes = {}
    extractor._page_image_regions = {}

    page = extractor.doc[0]
    page.get_images = lambda full=True: [(1,)]
    page.get_drawings = lambda: []

    text = extractor.extract_page(0)

    assert "[IMAGE]" in text
    assert len(extractor.get_image_regions(0)) == 1


def test_extract_page_can_skip_full_page_art_placeholder():
    extractor = PDFExtractor.__new__(PDFExtractor)
    extractor.doc = _FakeDoc([_FakeLayoutPage([])])
    extractor.chapter_detector = _NoopChapterDetector()
    extractor._page_body_context = {}
    extractor._page_layout_notes = {}
    extractor._page_image_regions = {}

    page = extractor.doc[0]
    page.get_images = lambda full=True: [(1,)]
    page.get_drawings = lambda: []

    text = extractor.extract_page(0, include_images=False)

    assert text == ""
    assert extractor.get_image_regions(0) == []
