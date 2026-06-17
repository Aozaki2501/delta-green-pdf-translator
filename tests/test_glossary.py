"""
Unit tests for core.glossary module.

Tests load_glossary TSV parsing, edge cases (None/empty/nonexistent paths),
and find_relevant_glossary_terms with in-memory glossary dicts.

Requirements: 10.4, 10.7
"""

import pytest

from core.glossary import (
    build_glossary_candidates,
    find_relevant_glossary_terms,
    load_glossary,
    render_glossary_candidate_report,
    render_glossary_candidate_tsv,
    select_core_glossary_terms,
)


# ---------------------------------------------------------------------------
# Tests for load_glossary: TSV parsing with tab-separated pairs
# ---------------------------------------------------------------------------


class TestLoadGlossaryParsing:
    """Test load_glossary with valid TSV content."""

    def test_basic_tab_separated_pairs(self, tmp_path):
        """Tab-separated Chinese\\tEnglish pairs are parsed correctly."""
        tsv = tmp_path / "glossary.tsv"
        tsv.write_text(
            "绿色三角洲\tDelta Green\n"
            "管理者\tHandler\n"
            "特工\tAgent\n",
            encoding="utf-8",
        )
        result = load_glossary(str(tsv))
        assert result == {
            "Delta Green": "绿色三角洲",
            "Handler": "管理者",
            "Agent": "特工",
        }

    def test_comment_lines_skipped(self, tmp_path):
        """Lines starting with # are treated as comments and skipped."""
        tsv = tmp_path / "glossary.tsv"
        tsv.write_text(
            "# This is a comment\n"
            "# Another comment\n"
            "绿色三角洲\tDelta Green\n",
            encoding="utf-8",
        )
        result = load_glossary(str(tsv))
        assert result == {"Delta Green": "绿色三角洲"}

    def test_blank_lines_skipped(self, tmp_path):
        """Blank lines (empty or whitespace-only) are skipped."""
        tsv = tmp_path / "glossary.tsv"
        tsv.write_text(
            "绿色三角洲\tDelta Green\n"
            "\n"
            "   \n"
            "管理者\tHandler\n",
            encoding="utf-8",
        )
        result = load_glossary(str(tsv))
        assert result == {
            "Delta Green": "绿色三角洲",
            "Handler": "管理者",
        }

    def test_mixed_comments_blanks_and_entries(self, tmp_path):
        """Comments, blanks, and valid entries are handled together."""
        tsv = tmp_path / "glossary.tsv"
        tsv.write_text(
            "# Header comment\n"
            "\n"
            "绿色三角洲\tDelta Green\n"
            "# Mid-file comment\n"
            "\n"
            "管理者\tHandler\n"
            "特工\tAgent\n",
            encoding="utf-8",
        )
        result = load_glossary(str(tsv))
        assert len(result) == 3
        assert result["Delta Green"] == "绿色三角洲"
        assert result["Handler"] == "管理者"
        assert result["Agent"] == "特工"

    def test_corrupted_chinese_column_raises(self, tmp_path):
        """Question marks in the Chinese column mean the glossary is corrupted."""
        tsv = tmp_path / "glossary.tsv"
        tsv.write_text(
            "绿色三角洲\tDelta Green\n"
            "??????\tLast Things Last\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="术语表疑似编码损坏"):
            load_glossary(str(tsv))

    def test_question_mark_in_english_column_is_allowed(self, tmp_path):
        """Only the Chinese column is checked for encoding damage."""
        tsv = tmp_path / "glossary.tsv"
        tsv.write_text("未知问题\tUnknown?\n", encoding="utf-8")
        result = load_glossary(str(tsv))
        assert result == {"Unknown?": "未知问题"}


# ---------------------------------------------------------------------------
# Tests for load_glossary: None, empty, and nonexistent path
# ---------------------------------------------------------------------------


class TestLoadGlossaryEdgeCases:
    """Test load_glossary with invalid/missing paths."""

    def test_none_path_returns_empty_dict(self):
        """None path returns empty dict without exception."""
        result = load_glossary(None)
        assert result == {}

    def test_empty_string_path_returns_empty_dict(self):
        """Empty string path returns empty dict without exception."""
        result = load_glossary("")
        assert result == {}

    def test_nonexistent_path_returns_empty_dict(self, tmp_path):
        """Nonexistent file path returns empty dict without exception."""
        result = load_glossary(str(tmp_path / "does_not_exist.tsv"))
        assert result == {}


# ---------------------------------------------------------------------------
# Tests for find_relevant_glossary_terms: in-memory glossary dicts
# ---------------------------------------------------------------------------


class TestFindRelevantGlossaryTerms:
    """Test find_relevant_glossary_terms with in-memory glossary dicts."""

    def test_basic_term_matching(self):
        """Terms present in text are found and returned."""
        glossary = {"Delta Green": "绿色三角洲", "Handler": "管理者"}
        text = "The Handler reported to Delta Green headquarters."
        result = find_relevant_glossary_terms(text, glossary)
        assert result == {"Delta Green": "绿色三角洲", "Handler": "管理者"}

    def test_term_not_in_text(self):
        """Terms not present in text are not returned."""
        glossary = {"Delta Green": "绿色三角洲", "Handler": "管理者"}
        text = "Nothing relevant here."
        result = find_relevant_glossary_terms(text, glossary)
        assert result == {}

    def test_longest_match_first(self):
        """When glossary has 'Delta Green' and 'Green', 'Delta Green' wins."""
        glossary = {"Delta Green": "绿色三角洲", "Green": "绿色"}
        text = "Delta Green is a secret organization."
        result = find_relevant_glossary_terms(text, glossary)
        # "Delta Green" should match, not just "Green"
        assert "Delta Green" in result
        assert result["Delta Green"] == "绿色三角洲"
        # "Green" alone should NOT match since it's consumed by "Delta Green"
        assert "Green" not in result

    def test_non_overlapping_spans(self):
        """Matched spans do not overlap — shorter term excluded when inside longer."""
        glossary = {
            "New York": "纽约",
            "New York City": "纽约市",
        }
        text = "Welcome to New York City."
        result = find_relevant_glossary_terms(text, glossary)
        # Longest match "New York City" should win
        assert "New York City" in result
        # "New York" overlaps with "New York City" and should be excluded
        assert "New York" not in result

    def test_multiple_non_overlapping_matches(self):
        """Multiple terms at different positions are all matched."""
        glossary = {
            "Delta Green": "绿色三角洲",
            "Handler": "管理者",
            "Agent": "特工",
        }
        text = "The Agent met the Handler at Delta Green HQ."
        result = find_relevant_glossary_terms(text, glossary)
        assert result == {
            "Delta Green": "绿色三角洲",
            "Handler": "管理者",
            "Agent": "特工",
        }

    def test_case_insensitive_matching(self):
        """Matching is case-insensitive."""
        glossary = {"Delta Green": "绿色三角洲"}
        text = "DELTA GREEN is mentioned here."
        result = find_relevant_glossary_terms(text, glossary)
        assert "Delta Green" in result

    def test_empty_glossary_returns_empty(self):
        """Empty glossary dict returns empty result."""
        result = find_relevant_glossary_terms("Some text here.", {})
        assert result == {}

    def test_empty_text_returns_empty(self):
        """Empty text returns empty result."""
        glossary = {"Delta Green": "绿色三角洲"}
        result = find_relevant_glossary_terms("", glossary)
        assert result == {}

    def test_word_boundary_respected(self):
        """Terms only match at word boundaries, not inside other words."""
        glossary = {"Green": "绿色"}
        # "Greenhouse" contains "Green" but should not match due to boundary
        text = "The Greenhouse was empty."
        result = find_relevant_glossary_terms(text, glossary)
        assert "Green" not in result


class TestSelectCoreGlossaryTerms:
    def test_selects_terms_by_source_chunk_frequency(self):
        glossary = {
            "Agent": "特工",
            "Delta Green": "绿色三角洲",
            "Handler": "管理者",
        }
        texts = [
            "The Agent met a Handler from Delta Green.",
            "Another Agent reported to Delta Green.",
            "The Agent waited.",
        ]

        result = select_core_glossary_terms(texts, glossary, limit=2)

        assert list(result) == ["Agent", "Delta Green"]
        assert result == {
            "Agent": "特工",
            "Delta Green": "绿色三角洲",
        }

    def test_empty_or_zero_limit_returns_empty(self):
        assert select_core_glossary_terms([], {"Agent": "特工"}) == {}
        assert select_core_glossary_terms(["Agent"], {"Agent": "特工"}, limit=0) == {}


class TestGlossaryCandidates:
    def test_builds_candidates_by_page_frequency(self):
        pages = {
            0: "The Borellus Connection mentions Agent Smith.",
            1: "Borellus Connection returns with Agent Smith.",
            2: "Agent Smith appears here.",
        }
        glossary = {"Agent": "特工"}

        candidates = build_glossary_candidates(pages, glossary, min_pages=2)

        assert candidates[0].term == "Agent Smith"
        assert candidates[0].count == 3
        assert candidates[0].pages == [0, 1, 2]
        assert any(row.term == "Borellus Connection" for row in candidates)
        assert all(row.term != "Agent" for row in candidates)

    def test_candidate_outputs_are_manual_templates(self):
        candidates = build_glossary_candidates(
            {
                0: "Borellus Connection appears.",
                1: "Borellus Connection appears again.",
            },
            {},
            min_pages=2,
        )

        report = render_glossary_candidate_report(candidates, "测试")
        tsv = render_glossary_candidate_tsv(candidates)

        assert "术语候选报告" in report
        assert "Borellus Connection" in report
        assert "# 中文\t英文" in tsv
        assert "\tBorellus Connection" in tsv
