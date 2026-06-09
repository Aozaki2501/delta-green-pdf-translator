"""
Unit tests for core.utils module.

Covers:
- normalize_page_range: valid boundary values and invalid inputs
- parse_page_selection: 1-based string to zero-based index set conversion
- is_failed_translation: failure-prefix detection

Requirements: 10.2, 10.3, 10.5
"""

from pathlib import Path

import pytest

from core.utils import (
    count_cjk_chars,
    is_failed_translation,
    looks_incomplete_translation,
    looks_untranslated_page,
    normalize_page_range,
    output_base_in_own_dir,
    parse_page_selection,
)
from core.constants import TRANSLATION_FAILURE_PREFIX


# ---------------------------------------------------------------------------
# normalize_page_range — valid inputs
# ---------------------------------------------------------------------------


class TestNormalizePageRangeValid:
    def test_full_range(self):
        """start=0, end=total_pages returns (0, total_pages)."""
        assert normalize_page_range(0, 10, 10) == (0, 10)

    def test_end_none_defaults_to_total(self):
        """end=None defaults to total_pages."""
        assert normalize_page_range(5, None, 20) == (5, 20)

    def test_boundary_single_page(self):
        """Minimal valid range: one page document, start=0, end=1."""
        assert normalize_page_range(0, 1, 1) == (0, 1)

    def test_start_as_string(self):
        """String start_page is coerced to int."""
        assert normalize_page_range("3", 10, 20) == (3, 10)

    def test_end_clamped_to_total(self):
        """end > total_pages is clamped to total_pages."""
        assert normalize_page_range(0, 100, 10) == (0, 10)


# ---------------------------------------------------------------------------
# normalize_page_range — invalid inputs
# ---------------------------------------------------------------------------


class TestNormalizePageRangeInvalid:
    def test_negative_start(self):
        """Negative start raises ValueError."""
        with pytest.raises(ValueError):
            normalize_page_range(-1, 10, 20)

    def test_start_equals_total_pages(self):
        """start == total_pages is out of range."""
        with pytest.raises(ValueError):
            normalize_page_range(10, 15, 10)

    def test_start_exceeds_total_pages(self):
        """start > total_pages is out of range."""
        with pytest.raises(ValueError):
            normalize_page_range(20, 25, 10)

    def test_end_less_than_or_equal_start(self):
        """end <= start raises ValueError."""
        with pytest.raises(ValueError):
            normalize_page_range(5, 5, 10)

    def test_end_less_than_start(self):
        """end < start raises ValueError."""
        with pytest.raises(ValueError):
            normalize_page_range(5, 3, 10)

    def test_zero_total_pages(self):
        """total_pages < 1 raises ValueError."""
        with pytest.raises(ValueError):
            normalize_page_range(0, 0, 0)


# ---------------------------------------------------------------------------
# parse_page_selection
# ---------------------------------------------------------------------------


class TestParsePageSelection:
    def test_mixed_pages_and_ranges(self):
        """'8, 12-15' with total_pages=20 -> {7, 11, 12, 13, 14}."""
        result = parse_page_selection("8, 12-15", 20)
        assert result == {7, 11, 12, 13, 14}

    def test_single_page(self):
        """Single page '1' -> {0}."""
        result = parse_page_selection("1", 10)
        assert result == {0}

    def test_empty_string(self):
        """Empty string returns empty set."""
        result = parse_page_selection("", 10)
        assert result == set()

    def test_whitespace_only(self):
        """Whitespace-only returns empty set."""
        result = parse_page_selection("   ", 10)
        assert result == set()

    def test_out_of_range_page(self):
        """Page number exceeding total_pages raises ValueError."""
        with pytest.raises(ValueError):
            parse_page_selection("25", 20)

    def test_zero_page(self):
        """Page 0 is below valid range (1-based) and raises ValueError."""
        with pytest.raises(ValueError):
            parse_page_selection("0", 10)

    def test_non_numeric(self):
        """Non-numeric input raises ValueError."""
        with pytest.raises(ValueError):
            parse_page_selection("abc", 10)

    def test_reversed_range(self):
        """Reversed range '15-12' is auto-corrected to ascending."""
        result = parse_page_selection("15-12", 20)
        assert result == {11, 12, 13, 14}


# ---------------------------------------------------------------------------
# is_failed_translation
# ---------------------------------------------------------------------------


class TestIsFailedTranslation:
    def test_failure_prefix_string(self):
        """String starting with failure prefix returns True."""
        text = f"{TRANSLATION_FAILURE_PREFIX} timeout]"
        assert is_failed_translation(text) is True

    def test_failure_prefix_with_leading_whitespace(self):
        """Leading whitespace before prefix still returns True (lstrip)."""
        text = f"  {TRANSLATION_FAILURE_PREFIX} error]"
        assert is_failed_translation(text) is True

    def test_normal_text(self):
        """Normal text returns False."""
        assert is_failed_translation("Hello world") is False

    def test_empty_string(self):
        """Empty string returns False."""
        assert is_failed_translation("") is False

    def test_partial_prefix(self):
        """Partial prefix that doesn't fully match returns False."""
        assert is_failed_translation("[Translation") is False

    def test_prefix_in_middle(self):
        """Prefix appearing in the middle (not at start) returns False."""
        text = f"Some text {TRANSLATION_FAILURE_PREFIX} error]"
        assert is_failed_translation(text) is False


class TestLooksUntranslatedPage:
    def test_flags_full_english_page(self):
        source = " ".join(["The agents enter the chamber and study the wall."] * 8)
        translated = " ".join(["The agents enter the chamber and study the wall."] * 8)

        assert looks_untranslated_page(source, translated, "columns") is True

    def test_accepts_mostly_chinese_translation(self):
        source = " ".join(["The agents enter the chamber and study the wall."] * 8)
        translated = "特工进入房间，检查墙壁上的痕迹，并继续向前搜索。" * 8

        assert looks_untranslated_page(source, translated, "columns") is False

    def test_skips_art_pages(self):
        source = "The cover shows a ruined temple under the night sky."
        translated = "The cover shows a ruined temple under the night sky."

        assert looks_untranslated_page(source, translated, "art") is False

    def test_counts_cjk_chars(self):
        assert count_cjk_chars("中文 mixed English") == 2


class TestLooksIncompleteTranslation:
    def test_flags_long_source_with_tiny_chinese_translation(self):
        source = " ".join(["The agents enter the chamber and study the wall carefully."] * 160)
        translated = "这是一段明显被截断的中文译文。" * 12

        assert looks_incomplete_translation(source, translated, "columns") is True

    def test_accepts_normal_length_chinese_translation(self):
        source = " ".join(["The agents enter the chamber and study the wall carefully."] * 160)
        translated = "调查员进入房间，仔细检查墙面上的痕迹，并继续向前搜索。" * 80

        assert looks_incomplete_translation(source, translated, "columns") is False

    def test_skips_short_or_non_body_pages(self):
        source = "The cover shows a ruined house under the night sky."
        translated = "这是一座夜色中的废弃宅邸。"

        assert looks_incomplete_translation(source, translated, "art") is False
        assert looks_incomplete_translation("[[TOC]]\n" + source * 80, translated * 40, "columns") is False


def test_output_base_uses_same_named_folder():
    assert output_base_in_own_dir("output/book_cn.html") == str(Path("output") / "book_cn" / "book_cn")


def test_output_base_does_not_double_nest_existing_folder():
    assert output_base_in_own_dir(str(Path("output") / "book_cn" / "book_cn")) == str(Path("output") / "book_cn" / "book_cn")
