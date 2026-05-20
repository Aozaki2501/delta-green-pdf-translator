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
    is_failed_translation,
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


def test_output_base_uses_same_named_folder():
    assert output_base_in_own_dir("output/book_cn.html") == str(Path("output") / "book_cn" / "book_cn")


def test_output_base_does_not_double_nest_existing_folder():
    assert output_base_in_own_dir(str(Path("output") / "book_cn" / "book_cn")) == str(Path("output") / "book_cn" / "book_cn")
