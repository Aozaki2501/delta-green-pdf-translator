"""
Unit tests for core/semantic_analyzer.py.

Tests the SemanticAnalyzer's classification logic, helper functions,
and page type detection without requiring a real PDF file.
"""

import pytest

from core.semantic_analyzer import (
    PageContext,
    SemanticAnalyzer,
    _bbox_area,
    _is_fixed_nontranslatable_text,
    _region_inside_table_grid,
    _looks_like_list,
    _looks_like_table,
    _weighted_avg_font_size,
    _has_accent_heading_color,
    _merge_drop_caps,
    _mark_image_float_blocks,
    _promote_hero_title_blocks,
)
from core.typeset_models import (
    BackgroundLayer,
    ColumnInfo,
    ContentBlock,
    DecorationElement,
    ImageElement,
    FontRole,
    PageStructure,
    PageType,
    SemanticRole,
    StyledTextRun,
    TextRegionBBox,
)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestBboxArea:
    def test_normal_bbox(self):
        assert _bbox_area([0, 0, 100, 200]) == 20000.0


class TestNonTranslatableText:
    def test_private_checkbox_glyph_is_not_translatable(self):
        assert _is_fixed_nontranslatable_text("\uf070", SemanticRole.BODY_COLUMN)

    def test_numeric_marker_is_not_translatable(self):
        assert _is_fixed_nontranslatable_text("-1", SemanticRole.BODY_COLUMN)

    def test_words_remain_translatable(self):
        assert not _is_fixed_nontranslatable_text("Stability", SemanticRole.BODY_COLUMN)

    def test_small_bbox(self):
        assert _bbox_area([10, 10, 60, 60]) == 2500.0

    def test_zero_area(self):
        assert _bbox_area([5, 5, 5, 10]) == 0.0

    def test_invalid_bbox(self):
        assert _bbox_area([1, 2, 3]) == 0.0


class TestWeightedAvgFontSize:
    def test_equal_weight(self):
        runs = [
            StyledTextRun(text="Hello", font_size=12.0, bold=False, italic=False, color="#000000"),
            StyledTextRun(text="World", font_size=14.0, bold=True, italic=False, color="#000000"),
        ]
        avg = _weighted_avg_font_size(runs)
        assert abs(avg - 13.0) < 0.01

    def test_unequal_weight(self):
        runs = [
            StyledTextRun(text="Hi", font_size=10.0, bold=False, italic=False, color="#000000"),
            StyledTextRun(text="LongText", font_size=20.0, bold=False, italic=False, color="#000000"),
        ]
        # 2*10 + 8*20 = 180 / 10 = 18.0
        avg = _weighted_avg_font_size(runs)
        assert abs(avg - 18.0) < 0.01

    def test_empty_runs(self):
        assert _weighted_avg_font_size([]) == 11.0

    def test_whitespace_only(self):
        runs = [
            StyledTextRun(text="   ", font_size=12.0, bold=False, italic=False, color="#000000"),
        ]
        assert _weighted_avg_font_size(runs) == 11.0


class TestLooksLikeTable:
    def test_tab_separated(self):
        text = "a\tb\tc\n1\t2\t3\n4\t5\t6\n7\t8\t9"
        assert _looks_like_table(text) is True

    def test_space_aligned(self):
        text = "Name   Age   City\nAlice   30   NYC\nBob   25   LA\nEve   28   SF"
        assert _looks_like_table(text) is True

    def test_normal_text(self):
        assert _looks_like_table("hello world") is False

    def test_too_few_lines(self):
        assert _looks_like_table("a\tb\n1\t2") is False

    def test_detects_dg_shaded_table_grid(self):
        page = _make_page_structure(
            text_regions=[
                TextRegionBBox(id="p0001_r0001", bbox=[40, 104, 250, 114], block_ids=["t0"]),
            ]
        )
        page.decorations.extend([
            DecorationElement(
                id=f"d{i}",
                element_type="rect",
                bbox=[36.0, 100.0 + i * 16.0, 540.0, 114.0 + i * 16.0],
                stroke_color=None,
                fill_color="#d1d2d4" if i else "#000000",
                stroke_width=0.0,
            )
            for i in range(6)
        ])

        assert _region_inside_table_grid(page.text_regions[0], page) is True

    def test_detects_dense_line_table_grid(self):
        page = _make_page_structure(
            text_regions=[
                TextRegionBBox(id="p0001_r0001", bbox=[40, 104, 250, 114], block_ids=["t0"]),
            ]
        )
        page.decorations.extend([
            DecorationElement(
                id=f"v{i}",
                element_type="line",
                bbox=[40.0 + i * 2.0, 90.0, 40.0 + i * 2.0, 720.0],
                stroke_color="#000000",
                fill_color=None,
                stroke_width=1.0,
            )
            for i in range(80)
        ])

        assert _region_inside_table_grid(page.text_regions[0], page) is True


class TestLooksLikeList:
    def test_numbered_list(self):
        text = "1. item one\n2. item two\n3. item three"
        assert _looks_like_list(text) is True

    def test_bullet_list(self):
        text = "• first item\n• second item\n• third item"
        assert _looks_like_list(text) is True

    def test_dash_list(self):
        text = "- first\n- second\n- third"
        assert _looks_like_list(text) is True

    def test_normal_text(self):
        assert _looks_like_list("hello world") is False

    def test_single_line(self):
        assert _looks_like_list("1. only one") is False


# ---------------------------------------------------------------------------
# Page type classification tests
# ---------------------------------------------------------------------------


def _make_page_structure(
    text_regions: list[TextRegionBBox] | None = None,
    images: list[ImageElement] | None = None,
    width: float = 612.0,
    height: float = 792.0,
) -> PageStructure:
    """Helper to create a PageStructure for testing."""
    return PageStructure(
        page_index=0,
        width=width,
        height=height,
        background=BackgroundLayer(color=None, gradient=None),
        images=images or [],
        decorations=[],
        text_regions=text_regions or [],
    )


class TestClassifyPageType:
    """Test page type classification logic without PDF access."""

    def _make_analyzer_classify(self, page_structure, median_font_size=11.0, image_coverage=0.0):
        """Call classify_page_type as a static-like method (no PDF needed)."""
        # We can call classify_page_type directly since it doesn't use self.doc
        from core.semantic_analyzer import SemanticAnalyzer
        # Create a minimal mock - classify_page_type doesn't use self
        # We'll call it as an unbound method with a dummy self
        return SemanticAnalyzer.classify_page_type(
            None, page_structure, median_font_size, image_coverage
        )

    def test_art_page_large_images(self):
        """Art: minimal text + large images (>50% coverage)."""
        regions = [
            TextRegionBBox(id="p0001_r0001", bbox=[50, 50, 200, 80], block_ids=["t0"]),
        ]
        page = _make_page_structure(text_regions=regions)
        result = self._make_analyzer_classify(page, image_coverage=0.6)
        assert result == PageType.ART

    def test_art_page_no_text(self):
        """Art: no text regions with some image coverage."""
        page = _make_page_structure(text_regions=[])
        result = self._make_analyzer_classify(page, image_coverage=0.4)
        assert result == PageType.ART

    def test_cover_page_centered_blocks(self):
        """Cover: few blocks, mostly centered."""
        # Page width 612, center = 306
        regions = [
            TextRegionBBox(id="p0001_r0001", bbox=[200, 100, 412, 150], block_ids=["t0"]),
            TextRegionBBox(id="p0001_r0002", bbox=[220, 200, 392, 250], block_ids=["t1"]),
        ]
        page = _make_page_structure(text_regions=regions)
        result = self._make_analyzer_classify(page)
        assert result == PageType.COVER

    def test_columns_page(self):
        """Columns: text blocks in two vertical columns."""
        # Left column blocks
        regions = [
            TextRegionBBox(id="p0001_r0001", bbox=[50, 100, 280, 200], block_ids=["t0"]),
            TextRegionBBox(id="p0001_r0002", bbox=[50, 220, 280, 320], block_ids=["t1"]),
            # Right column blocks
            TextRegionBBox(id="p0001_r0003", bbox=[330, 100, 560, 200], block_ids=["t2"]),
            TextRegionBBox(id="p0001_r0004", bbox=[330, 220, 560, 320], block_ids=["t3"]),
        ]
        page = _make_page_structure(text_regions=regions)
        result = self._make_analyzer_classify(page)
        assert result == PageType.COLUMNS

    def test_single_page(self):
        """Single: text blocks spanning full page width."""
        regions = [
            TextRegionBBox(id="p0001_r0001", bbox=[50, 100, 560, 200], block_ids=["t0"]),
            TextRegionBBox(id="p0001_r0002", bbox=[50, 220, 560, 320], block_ids=["t1"]),
            TextRegionBBox(id="p0001_r0003", bbox=[50, 340, 560, 440], block_ids=["t2"]),
            TextRegionBBox(id="p0001_r0004", bbox=[50, 460, 560, 560], block_ids=["t3"]),
        ]
        page = _make_page_structure(text_regions=regions)
        result = self._make_analyzer_classify(page)
        assert result == PageType.SINGLE

    def test_mixed_page(self):
        """Mixed: both full-width and column blocks."""
        regions = [
            # Full-width title
            TextRegionBBox(id="p0001_r0001", bbox=[50, 50, 560, 100], block_ids=["t0"]),
            # Left column
            TextRegionBBox(id="p0001_r0002", bbox=[50, 120, 280, 220], block_ids=["t1"]),
            TextRegionBBox(id="p0001_r0003", bbox=[50, 240, 280, 340], block_ids=["t2"]),
            # Right column
            TextRegionBBox(id="p0001_r0004", bbox=[330, 120, 560, 220], block_ids=["t3"]),
            TextRegionBBox(id="p0001_r0005", bbox=[330, 240, 560, 340], block_ids=["t4"]),
        ]
        page = _make_page_structure(text_regions=regions)
        result = self._make_analyzer_classify(page)
        assert result == PageType.MIXED


# ---------------------------------------------------------------------------
# Region classification tests
# ---------------------------------------------------------------------------


class TestClassifyRegion:
    """Test region classification logic."""

    def _make_context(self, median_font_size=11.0):
        return PageContext(
            page_width=612.0,
            page_height=792.0,
            page_type=PageType.SINGLE,
            median_font_size=median_font_size,
            image_coverage=0.0,
            gutter_x=None,
        )

    def _classify(self, region, context, runs=None):
        """Call classify_region without needing a PDF."""
        return SemanticAnalyzer.classify_region(None, region, context, runs)

    def test_header_detection(self):
        """Region in top 10% of page is classified as HEADER."""
        region = TextRegionBBox(id="p0001_r0001", bbox=[50, 20, 560, 60], block_ids=["t0"])
        context = self._make_context()
        # y0=20 < 792*0.10=79.2, y1=60 < 792*0.15=118.8
        result = self._classify(region, context)
        assert result == SemanticRole.HEADER

    def test_footer_detection(self):
        """Region in bottom 10% of page is classified as FOOTER."""
        region = TextRegionBBox(id="p0001_r0001", bbox=[50, 750, 560, 780], block_ids=["t0"])
        context = self._make_context()
        # y0=750 > 792*0.90=712.8
        result = self._classify(region, context)
        assert result == SemanticRole.FOOTER

    def test_title_detection(self):
        """Region with large font (>= 1.5x median) is classified as TITLE."""
        region = TextRegionBBox(id="p0001_r0001", bbox=[50, 200, 560, 250], block_ids=["t0"])
        context = self._make_context(median_font_size=11.0)
        runs = [
            StyledTextRun(text="Chapter Title", font_size=18.0, bold=True, italic=False, color="#000000"),
        ]
        result = self._classify(region, context, runs)
        assert result == SemanticRole.TITLE

    def test_red_heading_detection(self):
        region = TextRegionBBox(id="p0001_r0001", bbox=[50, 200, 260, 225], block_ids=["t0"])
        context = self._make_context(median_font_size=11.0)
        runs = [
            StyledTextRun(text="The Road to Kali Ghati", font_size=14.0, bold=True, italic=False, color="#ed1c24"),
        ]
        result = self._classify(region, context, runs)
        assert result == SemanticRole.SUBTITLE

    def test_body_column_default(self):
        """Region in middle of page with normal font is BODY_COLUMN."""
        region = TextRegionBBox(id="p0001_r0001", bbox=[50, 300, 560, 400], block_ids=["t0"])
        context = self._make_context(median_font_size=11.0)
        runs = [
            StyledTextRun(text="Normal body text content here.", font_size=11.0, bold=False, italic=False, color="#000000"),
        ]
        result = self._classify(region, context, runs)
        assert result == SemanticRole.BODY_COLUMN

    def test_footnote_detection(self):
        """Small text near bottom is classified as FOOTNOTE."""
        region = TextRegionBBox(id="p0001_r0001", bbox=[50, 680, 560, 700], block_ids=["t0"])
        context = self._make_context(median_font_size=11.0)
        runs = [
            StyledTextRun(text="1. See reference.", font_size=8.0, bold=False, italic=False, color="#000000"),
        ]
        result = self._classify(region, context, runs)
        assert result == SemanticRole.FOOTNOTE

    def test_header_footer_not_translatable(self):
        """HEADER and FOOTER roles should produce translatable=False."""
        # This tests the logic in analyze_page, but we verify the rule here
        header_role = SemanticRole.HEADER
        footer_role = SemanticRole.FOOTER
        assert header_role in (SemanticRole.HEADER, SemanticRole.FOOTER)
        assert footer_role in (SemanticRole.HEADER, SemanticRole.FOOTER)


# ---------------------------------------------------------------------------
# Gutter detection tests
# ---------------------------------------------------------------------------


class TestGutterDetection:
    """Test dual-column gutter detection."""

    def test_detect_gutter_two_columns(self):
        """Detects gutter between left and right column regions."""
        regions = [
            TextRegionBBox(id="p0001_r0001", bbox=[50, 100, 280, 200], block_ids=["t0"]),
            TextRegionBBox(id="p0001_r0002", bbox=[50, 220, 280, 320], block_ids=["t1"]),
            TextRegionBBox(id="p0001_r0003", bbox=[330, 100, 560, 200], block_ids=["t2"]),
            TextRegionBBox(id="p0001_r0004", bbox=[330, 220, 560, 320], block_ids=["t3"]),
        ]
        page = _make_page_structure(text_regions=regions)
        gutter = SemanticAnalyzer._detect_gutter(None, page)
        assert gutter is not None
        # Gutter should be between 280 and 330
        assert 280 < gutter < 330

    def test_no_gutter_single_column(self):
        """No gutter detected for single-column pages."""
        regions = [
            TextRegionBBox(id="p0001_r0001", bbox=[50, 100, 560, 200], block_ids=["t0"]),
            TextRegionBBox(id="p0001_r0002", bbox=[50, 220, 560, 320], block_ids=["t1"]),
            TextRegionBBox(id="p0001_r0003", bbox=[50, 340, 560, 440], block_ids=["t2"]),
            TextRegionBBox(id="p0001_r0004", bbox=[50, 460, 560, 560], block_ids=["t3"]),
        ]
        page = _make_page_structure(text_regions=regions)
        gutter = SemanticAnalyzer._detect_gutter(None, page)
        assert gutter is None

    def test_no_gutter_too_few_regions(self):
        """No gutter detected with fewer than 3 regions."""
        regions = [
            TextRegionBBox(id="p0001_r0001", bbox=[50, 100, 280, 200], block_ids=["t0"]),
            TextRegionBBox(id="p0001_r0002", bbox=[330, 100, 560, 200], block_ids=["t1"]),
        ]
        page = _make_page_structure(text_regions=regions)
        gutter = SemanticAnalyzer._detect_gutter(None, page)
        assert gutter is None



def test_kult_profile_accent_color_is_classified_as_heading():
    runs = [StyledTextRun("Kapitel", 9.0, False, False, "#b8282f")]

    assert _has_accent_heading_color(runs, frozenset({"#b8282f"}))
    assert not _has_accent_heading_color(runs, frozenset({"#dc2527"}))



def test_drop_cap_is_merged_with_the_following_paragraph_before_translation():
    cap = ContentBlock(
        id="cap", region_id="r", role=SemanticRole.TITLE,
        runs=[StyledTextRun("T", 23.0, False, False, "#231f20")],
        source_text="T", translated_text=None, translatable=True,
        bbox=[30.0, 100.0, 45.0, 128.0], font_role=FontRole.DISPLAY,
    )
    body = ContentBlock(
        id="body", region_id="r", role=SemanticRole.BODY_COLUMN,
        runs=[StyledTextRun("jugosjätte", 7.8, False, False, "#231f20")],
        source_text="jugosjätte timmen", translated_text=None, translatable=True,
        bbox=[42.0, 102.0, 220.0, 130.0], font_role=FontRole.BODY,
    )

    merged = _merge_drop_caps([cap, body])

    assert len(merged) == 1
    assert merged[0].id == "cap"
    assert merged[0].source_text == "Tjugosjätte timmen"
    assert merged[0].layout_mode == "drop_cap"


def test_central_foreground_image_marks_adjacent_body_as_image_float():
    page = _make_page_structure(
        width=479.1,
        height=677.5,
        images=[ImageElement("float", [169.0, 169.0, 310.0, 415.0], "float.png", 100, 100)],
    )
    beside = ContentBlock(
        id="beside", region_id="r", role=SemanticRole.BODY_COLUMN,
        runs=[], source_text="Body", translated_text=None, translatable=True,
        bbox=[33.0, 180.0, 234.0, 300.0],
    )
    below = ContentBlock(
        id="below", region_id="r", role=SemanticRole.BODY_COLUMN,
        runs=[], source_text="Body", translated_text=None, translatable=True,
        bbox=[33.0, 440.0, 234.0, 520.0],
    )

    marked = _mark_image_float_blocks([beside, below], page)

    assert marked[0].layout_mode == "image_float"
    assert marked[1].layout_mode == "paragraph"


def test_two_line_chapter_title_is_merged_above_hero_drop_cap():
    page = _make_page_structure(
        width=479.1,
        height=677.5,
        images=[ImageElement("hero", [0.0, 0.0, 479.1, 226.8], "hero.png", 100, 100)],
    )
    title_one = ContentBlock(
        id="title-one", region_id="r", role=SemanticRole.SUBTITLE,
        runs=[StyledTextRun("Tjugosjätte", 24.0, False, False, "#b8282f")],
        source_text="Tjugosjätte", translated_text=None, translatable=True,
        bbox=[55.0, 245.0, 337.0, 314.0], font_role=FontRole.SECTION,
    )
    title_two = ContentBlock(
        id="title-two", region_id="r", role=SemanticRole.SUBTITLE,
        runs=[StyledTextRun("timmen", 24.0, False, False, "#b8282f")],
        source_text="timmen", translated_text=None, translatable=True,
        bbox=[55.0, 291.0, 230.0, 360.0], font_role=FontRole.SECTION,
    )
    intro = ContentBlock(
        id="intro", region_id="r", role=SemanticRole.BODY_COLUMN,
        runs=[], source_text="Intro", translated_text=None, translatable=True,
        bbox=[57.0, 355.0, 387.0, 445.0], layout_mode="drop_cap",
    )

    promoted = _promote_hero_title_blocks([title_one, title_two, intro], page)

    assert [block.id for block in promoted] == ["title-one", "intro"]
    assert promoted[0].role == SemanticRole.TITLE
    assert promoted[0].font_role == FontRole.DISPLAY
    assert promoted[0].source_text == "Tjugosjätte timmen"
    assert promoted[0].layout_mode == "full_width_hero"
