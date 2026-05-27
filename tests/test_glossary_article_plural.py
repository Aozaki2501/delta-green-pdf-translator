"""
Unit tests for plural normalization and article filtering in ACGlossaryMatcher.

Tests that:
- Plural forms (e.g., "Agents") match the singular glossary entry ("Agent")
- Articles (the/a/an) preceding terms don't prevent matching
- The original glossary dict is never mutated
- normalize_plurals=False disables plural matching
- filter_articles flag controls match_type annotation

Requirements: 2.6, 2.7, 2.8
"""

import pytest

from core.glossary import ACGlossaryMatcher, GlossaryMatch


# ---------------------------------------------------------------------------
# Tests for plural normalization
# ---------------------------------------------------------------------------


class TestPluralNormalization:
    """Test that plural variants of glossary terms are matched."""

    def test_simple_s_plural_matches(self):
        """'Agents' matches glossary entry 'Agent'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True,
                                    filter_articles=False)
        text = "The Agents were dispatched."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Agent" in result
        assert result["Agent"] == "特工"

    def test_es_plural_matches(self):
        """'Watches' matches glossary entry 'Watch'."""
        glossary = {"Watch": "监视"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True,
                                    filter_articles=False)
        text = "Multiple Watches were set up."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Watch" in result
        assert result["Watch"] == "监视"

    def test_ies_plural_matches(self):
        """'Entities' matches glossary entry 'Entity'."""
        glossary = {"Entity": "实体"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True,
                                    filter_articles=False)
        text = "Several Entities appeared."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Entity" in result
        assert result["Entity"] == "实体"

    def test_ed_suffix_matches(self):
        """'Handled' matches glossary entry 'Handle'."""
        glossary = {"Handle": "处理"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True,
                                    filter_articles=False)
        text = "The situation was Handled."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Handle" in result
        assert result["Handle"] == "处理"

    def test_ing_suffix_matches(self):
        """'Handling' matches glossary entry 'Handle'."""
        glossary = {"Handle": "处理"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True,
                                    filter_articles=False)
        text = "They were Handling the case."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Handle" in result
        assert result["Handle"] == "处理"

    def test_normalize_plurals_false_disables_plural_matching(self):
        """When normalize_plurals=False, 'Agents' does NOT match 'Agent'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False,
                                    filter_articles=False)
        text = "The Agents were dispatched."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Agent" not in result

    def test_singular_still_matches_with_plurals_enabled(self):
        """The original singular form still matches when plurals are enabled."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True,
                                    filter_articles=False)
        text = "The Agent was dispatched."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Agent" in result
        assert result["Agent"] == "特工"

    def test_plural_annotated_match_type(self):
        """Annotated results mark plural matches with match_type='plural'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True,
                                    filter_articles=False)
        text = "The Agents were dispatched."
        results = matcher.find_relevant_glossary_terms_annotated(text)
        assert len(results) == 1
        match = results[0]
        assert match.canonical_term == "Agent"
        assert match.matched_text == "Agents"
        assert match.match_type == "plural"

    def test_case_insensitive_plural(self):
        """Plural matching is case-insensitive."""
        glossary = {"Handler": "管理者"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True,
                                    filter_articles=False)
        text = "The handlers reported in."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Handler" in result


# ---------------------------------------------------------------------------
# Tests for article filtering
# ---------------------------------------------------------------------------


class TestArticleFiltering:
    """Test that articles (the/a/an) before terms don't prevent matching."""

    def test_the_before_term_matches(self):
        """'the Agent' matches glossary entry 'Agent'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False,
                                    filter_articles=True)
        text = "Contact the Agent immediately."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Agent" in result
        assert result["Agent"] == "特工"

    def test_a_before_term_matches(self):
        """'a Handler' matches glossary entry 'Handler'."""
        glossary = {"Handler": "管理者"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False,
                                    filter_articles=True)
        text = "She is a Handler for the cell."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Handler" in result
        assert result["Handler"] == "管理者"

    def test_an_before_term_matches(self):
        """'an Investigator' matches glossary entry 'Investigator'."""
        glossary = {"Investigator": "调查员"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False,
                                    filter_articles=True)
        text = "He is an Investigator."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Investigator" in result
        assert result["Investigator"] == "调查员"

    def test_article_annotated_match_type(self):
        """Annotated results mark article-preceded matches with match_type='article'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False,
                                    filter_articles=True)
        text = "Contact the Agent immediately."
        results = matcher.find_relevant_glossary_terms_annotated(text)
        assert len(results) == 1
        match = results[0]
        assert match.canonical_term == "Agent"
        assert match.match_type == "article"

    def test_filter_articles_false_still_matches(self):
        """When filter_articles=False, 'the Agent' still matches due to word boundaries."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False,
                                    filter_articles=False)
        text = "Contact the Agent immediately."
        result = matcher.find_relevant_glossary_terms(text)
        # Still matches because space is a word boundary
        assert "Agent" in result
        assert result["Agent"] == "特工"

    def test_filter_articles_false_annotated_type_is_exact(self):
        """When filter_articles=False, match_type is 'exact' not 'article'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False,
                                    filter_articles=False)
        text = "Contact the Agent immediately."
        results = matcher.find_relevant_glossary_terms_annotated(text)
        assert len(results) == 1
        assert results[0].match_type == "exact"

    def test_no_article_match_type_is_exact(self):
        """Without preceding article, match_type is 'exact'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False,
                                    filter_articles=True)
        text = "Contact Agent Smith immediately."
        results = matcher.find_relevant_glossary_terms_annotated(text)
        assert len(results) == 1
        assert results[0].match_type == "exact"


# ---------------------------------------------------------------------------
# Tests for glossary immutability
# ---------------------------------------------------------------------------


class TestGlossaryImmutability:
    """Test that the original glossary dict is never modified."""

    def test_original_glossary_unchanged_after_construction(self):
        """Original glossary dict is not modified during ACGlossaryMatcher construction."""
        glossary = {"Agent": "特工", "Handler": "管理者"}
        original_copy = dict(glossary)
        _ = ACGlossaryMatcher(glossary, normalize_plurals=True,
                              filter_articles=True)
        assert glossary == original_copy

    def test_original_glossary_unchanged_after_matching(self):
        """Original glossary dict is not modified after find_relevant_glossary_terms."""
        glossary = {"Agent": "特工", "Handler": "管理者"}
        original_copy = dict(glossary)
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True,
                                    filter_articles=True)
        text = "The Agents met the Handlers at Delta Green HQ."
        _ = matcher.find_relevant_glossary_terms(text)
        assert glossary == original_copy

    def test_original_glossary_unchanged_after_annotated_matching(self):
        """Original glossary dict is not modified after find_relevant_glossary_terms_annotated."""
        glossary = {"Agent": "特工", "Handler": "管理者", "Investigator": "调查员"}
        original_copy = dict(glossary)
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True,
                                    filter_articles=True, fuzzy=True)
        text = "The Agents and an Investigator met a Handler."
        _ = matcher.find_relevant_glossary_terms_annotated(text)
        assert glossary == original_copy

    def test_modifying_original_does_not_affect_matcher(self):
        """Modifying the original glossary after construction doesn't affect the matcher."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True,
                                    filter_articles=True)
        # Modify original
        glossary["NewTerm"] = "新术语"
        # Matcher should still only know about "Agent"
        text = "The Agent and NewTerm."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Agent" in result
        assert "NewTerm" not in result


# ---------------------------------------------------------------------------
# Tests for combined plural + article scenarios
# ---------------------------------------------------------------------------


class TestCombinedPluralArticle:
    """Test combined plural normalization and article filtering."""

    def test_article_with_plural(self):
        """'the Agents' matches glossary entry 'Agent'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True,
                                    filter_articles=True)
        text = "Contact the Agents immediately."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Agent" in result
        assert result["Agent"] == "特工"

    def test_multiple_terms_with_articles_and_plurals(self):
        """Multiple terms with various articles and plural forms all match."""
        glossary = {
            "Agent": "特工",
            "Handler": "管理者",
            "Investigator": "调查员",
        }
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True,
                                    filter_articles=True)
        text = "The Agents reported to a Handler. An Investigator was assigned."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Agent" in result
        assert "Handler" in result
        assert "Investigator" in result
