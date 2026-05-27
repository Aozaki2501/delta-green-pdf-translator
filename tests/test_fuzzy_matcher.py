"""
Unit tests for FuzzyMatcher and fuzzy matching integration in ACGlossaryMatcher.

Tests OCR character substitution detection, edit count limits, and integration
with the AC automaton second-pass scanning.

Requirements: 2.4, 2.5, 2.10
"""

import pytest

from core.glossary import FuzzyMatcher, ACGlossaryMatcher, GlossaryMatch


# ---------------------------------------------------------------------------
# Tests for FuzzyMatcher.is_fuzzy_match
# ---------------------------------------------------------------------------


class TestFuzzyMatcherBasic:
    """Test FuzzyMatcher.is_fuzzy_match with OCR substitutions."""

    def test_zero_to_O_substitution(self):
        """0 and O are recognized as OCR substitution pair."""
        fm = FuzzyMatcher(max_edits=2)
        # "B0SS" is OCR-corrupted "BOSS" (0→O)
        is_match, edits = fm.is_fuzzy_match("B0SS", "BOSS")
        assert is_match is True
        assert edits == 1

    def test_one_to_l_substitution(self):
        """1 and l are recognized as OCR substitution pair."""
        fm = FuzzyMatcher(max_edits=2)
        # "he1lo" is OCR-corrupted "hello" (1→l)
        is_match, edits = fm.is_fuzzy_match("he1lo", "hello")
        assert is_match is True
        assert edits == 1

    def test_one_to_I_substitution(self):
        """1 and I are recognized as OCR substitution pair."""
        fm = FuzzyMatcher(max_edits=2)
        # "1nvestigator" is OCR-corrupted "Investigator" (1→I)
        is_match, edits = fm.is_fuzzy_match("1nvestigator", "Investigator")
        assert is_match is True
        assert edits == 1

    def test_five_to_S_substitution(self):
        """5 and S are recognized as OCR substitution pair."""
        fm = FuzzyMatcher(max_edits=2)
        # "5anity" is OCR-corrupted "Sanity" (5→S)
        is_match, edits = fm.is_fuzzy_match("5anity", "Sanity")
        assert is_match is True
        assert edits == 1

    def test_eight_to_B_substitution(self):
        """8 and B are recognized as OCR substitution pair."""
        fm = FuzzyMatcher(max_edits=2)
        # "8lack" is OCR-corrupted "Black" (8→B)
        is_match, edits = fm.is_fuzzy_match("8lack", "Black")
        assert is_match is True
        assert edits == 1

    def test_two_substitutions_allowed(self):
        """Two OCR substitutions within limit are accepted."""
        fm = FuzzyMatcher(max_edits=2)
        # "8O55" is OCR-corrupted "BOSS" (8→B, 5→S)
        is_match, edits = fm.is_fuzzy_match("8O5S", "BOSS")
        assert is_match is True
        assert edits == 2

    def test_three_substitutions_rejected(self):
        """Three OCR substitutions exceed limit and are rejected."""
        fm = FuzzyMatcher(max_edits=2)
        # "80S5" has 3 substitutions: 8→B, 0→O, 5→S
        is_match, edits = fm.is_fuzzy_match("80S5", "BOSS")
        assert is_match is False

    def test_exact_match_not_fuzzy(self):
        """Exact match (0 edits) is not considered a fuzzy match."""
        fm = FuzzyMatcher(max_edits=2)
        is_match, edits = fm.is_fuzzy_match("BOSS", "BOSS")
        assert is_match is False
        assert edits == 0

    def test_different_length_rejected(self):
        """Different length strings are never a fuzzy match."""
        fm = FuzzyMatcher(max_edits=2)
        is_match, edits = fm.is_fuzzy_match("BOSS", "BO")
        assert is_match is False

    def test_non_ocr_difference_rejected(self):
        """Characters that differ but aren't in OCR_SUBSTITUTIONS are rejected."""
        fm = FuzzyMatcher(max_edits=2)
        # "BXSS" - X is not an OCR substitute for O
        is_match, edits = fm.is_fuzzy_match("BXSS", "BOSS")
        assert is_match is False

    def test_case_insensitive_exact_chars(self):
        """Case-insensitive exact matches don't count as edits."""
        fm = FuzzyMatcher(max_edits=2)
        # "b0ss" vs "BOSS" - b/B and s/S are case-insensitive exact, 0/O is OCR
        is_match, edits = fm.is_fuzzy_match("b0ss", "BOSS")
        assert is_match is True
        assert edits == 1

    def test_l_to_I_substitution(self):
        """l and I are recognized as OCR substitution pair."""
        fm = FuzzyMatcher(max_edits=2)
        is_match, edits = fm.is_fuzzy_match("lntelligence", "Intelligence")
        assert is_match is True
        assert edits == 1

    def test_max_edits_one(self):
        """Custom max_edits=1 rejects 2 substitutions."""
        fm = FuzzyMatcher(max_edits=1)
        # Two substitutions with max_edits=1
        is_match, edits = fm.is_fuzzy_match("8O5S", "BOSS")
        assert is_match is False


# ---------------------------------------------------------------------------
# Tests for FuzzyMatcher integration with ACGlossaryMatcher
# ---------------------------------------------------------------------------


class TestFuzzyMatcherIntegration:
    """Test fuzzy matching as second pass in ACGlossaryMatcher."""

    def test_fuzzy_finds_ocr_corrupted_term(self):
        """Fuzzy scan finds OCR-corrupted term in unmatched region."""
        glossary = {"BOSS": "老板"}
        matcher = ACGlossaryMatcher(glossary, fuzzy=True, normalize_plurals=False,
                                    filter_articles=False)
        text = "The B0SS arrived."
        result = matcher.find_relevant_glossary_terms(text)
        assert "BOSS" in result
        assert result["BOSS"] == "老板"

    def test_fuzzy_disabled_does_not_find_corrupted(self):
        """With fuzzy=False, OCR-corrupted terms are not found."""
        glossary = {"BOSS": "老板"}
        matcher = ACGlossaryMatcher(glossary, fuzzy=False, normalize_plurals=False,
                                    filter_articles=False)
        text = "The B0SS arrived."
        result = matcher.find_relevant_glossary_terms(text)
        assert "BOSS" not in result

    def test_fuzzy_annotated_has_correct_metadata(self):
        """Fuzzy matches in annotated results have is_fuzzy=True and correct edits."""
        glossary = {"Sanity": "理智"}
        matcher = ACGlossaryMatcher(glossary, fuzzy=True, normalize_plurals=False,
                                    filter_articles=False)
        text = "Check your 5anity."
        results = matcher.find_relevant_glossary_terms_annotated(text)
        assert len(results) == 1
        match = results[0]
        assert match.is_fuzzy is True
        assert match.fuzzy_edits == 1
        assert match.matched_text == "5anity"
        assert match.canonical_term == "Sanity"
        assert match.chinese == "理智"
        assert match.match_type == "fuzzy"

    def test_exact_match_preferred_over_fuzzy(self):
        """Exact matches from first pass take priority over fuzzy matches."""
        glossary = {"BOSS": "老板", "Handler": "管理者"}
        matcher = ACGlossaryMatcher(glossary, fuzzy=True, normalize_plurals=False,
                                    filter_articles=False)
        text = "The BOSS and the Hand1er met."
        result = matcher.find_relevant_glossary_terms(text)
        assert "BOSS" in result  # exact match
        assert "Handler" in result  # fuzzy match (1→l)

    def test_fuzzy_respects_word_boundaries(self):
        """Fuzzy matches must respect word boundaries."""
        glossary = {"SOS": "求救"}
        matcher = ACGlossaryMatcher(glossary, fuzzy=True, normalize_plurals=False,
                                    filter_articles=False)
        # "5OS" inside "a5OSome" should NOT match due to word boundary
        text = "a5OSome thing"
        result = matcher.find_relevant_glossary_terms(text)
        assert "SOS" not in result

    def test_fuzzy_does_not_overlap_exact(self):
        """Fuzzy matches don't overlap with already-matched exact spans."""
        glossary = {"Delta Green": "绿色三角洲", "Green": "绿色"}
        matcher = ACGlossaryMatcher(glossary, fuzzy=True, normalize_plurals=False,
                                    filter_articles=False)
        text = "Delta Green is here."
        result = matcher.find_relevant_glossary_terms(text)
        # "Delta Green" should match exactly, "Green" should not match
        # (it's consumed by the longer match)
        assert "Delta Green" in result
        assert "Green" not in result

    def test_fuzzy_two_edits_found(self):
        """Term with 2 OCR substitutions is found by fuzzy scan."""
        glossary = {"Investigator": "调查员"}
        matcher = ACGlossaryMatcher(glossary, fuzzy=True, normalize_plurals=False,
                                    filter_articles=False)
        # 1→I, 0→o: "1nvest1gator" → "Investigator" (but 'i' case-insensitive match)
        # Let's use: "1nvestigat0r" → I→1, o→0
        text = "The 1nvestigat0r found clues."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Investigator" in result

    def test_fuzzy_three_edits_rejected(self):
        """Term with 3 OCR substitutions is rejected by fuzzy scan."""
        glossary = {"Investigator": "调查员"}
        matcher = ACGlossaryMatcher(glossary, fuzzy=True, normalize_plurals=False,
                                    filter_articles=False, max_fuzzy_edits=2)
        # "1nve5tigat0r" has 3 substitutions: 1→I, 5→s, 0→o
        text = "The 1nve5tigat0r found clues."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Investigator" not in result

    def test_empty_glossary_with_fuzzy(self):
        """Empty glossary with fuzzy=True returns empty without error."""
        matcher = ACGlossaryMatcher({}, fuzzy=True, normalize_plurals=False,
                                    filter_articles=False)
        result = matcher.find_relevant_glossary_terms("Some text here.")
        assert result == {}
