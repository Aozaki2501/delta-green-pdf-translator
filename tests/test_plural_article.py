"""
Tests for plural normalization and article filtering in ACGlossaryMatcher.

Covers:
- Plural forms ("Agents") match singular glossary entry ("Agent")
- Articles (the/a/an) preceding terms don't prevent matching
- Original glossary dict is never mutated
- Combined plural + article scenarios

Requirements: 2.6, 2.7, 2.8
"""

import pytest

from core.glossary import ACGlossaryMatcher, GlossaryMatch


# ---------------------------------------------------------------------------
# Plural normalization
# ---------------------------------------------------------------------------


class TestPluralNormalization:
    """Plural variants of glossary terms are correctly matched."""

    def test_s_plural(self):
        """'Agents' matches glossary 'Agent'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=False)
        result = matcher.find_relevant_glossary_terms("The Agents arrived.")
        assert result == {"Agent": "特工"}

    def test_es_plural(self):
        """'Watches' matches glossary 'Watch'."""
        glossary = {"Watch": "监视"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=False)
        result = matcher.find_relevant_glossary_terms("Set up Watches around the perimeter.")
        assert result == {"Watch": "监视"}

    def test_ies_plural(self):
        """'Entities' matches glossary 'Entity' (consonant+y -> ies)."""
        glossary = {"Entity": "实体"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=False)
        result = matcher.find_relevant_glossary_terms("Multiple Entities were detected.")
        assert result == {"Entity": "实体"}

    def test_ed_past_tense(self):
        """'Handled' matches glossary 'Handle' (silent-e + d)."""
        glossary = {"Handle": "处理"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=False)
        result = matcher.find_relevant_glossary_terms("The case was Handled quickly.")
        assert result == {"Handle": "处理"}

    def test_ing_gerund(self):
        """'Handling' matches glossary 'Handle' (drop e, add ing)."""
        glossary = {"Handle": "处理"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=False)
        result = matcher.find_relevant_glossary_terms("They were Handling the situation.")
        assert result == {"Handle": "处理"}

    def test_plural_disabled(self):
        """When normalize_plurals=False, 'Agents' does NOT match 'Agent'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False, filter_articles=False)
        result = matcher.find_relevant_glossary_terms("The Agents arrived.")
        assert "Agent" not in result

    def test_singular_still_works(self):
        """Original singular form still matches when plurals enabled."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=False)
        result = matcher.find_relevant_glossary_terms("One Agent was sent.")
        assert result == {"Agent": "特工"}

    def test_case_insensitive_plural(self):
        """Lowercase plural 'agents' matches glossary 'Agent'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=False)
        result = matcher.find_relevant_glossary_terms("The agents reported in.")
        assert result == {"Agent": "特工"}

    def test_plural_match_type_annotated(self):
        """Annotated interface marks plural matches with match_type='plural'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=False)
        results = matcher.find_relevant_glossary_terms_annotated("The Agents arrived.")
        assert len(results) == 1
        assert results[0].canonical_term == "Agent"
        assert results[0].matched_text == "Agents"
        assert results[0].match_type == "plural"


# ---------------------------------------------------------------------------
# Article filtering
# ---------------------------------------------------------------------------


class TestArticleFiltering:
    """Articles (the/a/an) before terms don't prevent matching."""

    def test_the_agent(self):
        """'the Agent' finds glossary term 'Agent'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False, filter_articles=True)
        result = matcher.find_relevant_glossary_terms("Contact the Agent now.")
        assert result == {"Agent": "特工"}

    def test_a_handler(self):
        """'a Handler' finds glossary term 'Handler'."""
        glossary = {"Handler": "管理者"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False, filter_articles=True)
        result = matcher.find_relevant_glossary_terms("She is a Handler for the cell.")
        assert result == {"Handler": "管理者"}

    def test_an_investigator(self):
        """'an Investigator' finds glossary term 'Investigator'."""
        glossary = {"Investigator": "调查员"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False, filter_articles=True)
        result = matcher.find_relevant_glossary_terms("He is an Investigator.")
        assert result == {"Investigator": "调查员"}

    def test_article_match_type_annotated(self):
        """Annotated interface marks article-preceded matches with match_type='article'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False, filter_articles=True)
        results = matcher.find_relevant_glossary_terms_annotated("Contact the Agent now.")
        assert len(results) == 1
        assert results[0].match_type == "article"

    def test_no_article_is_exact(self):
        """Without preceding article, match_type is 'exact'."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False, filter_articles=True)
        results = matcher.find_relevant_glossary_terms_annotated("Agent Smith arrived.")
        assert len(results) == 1
        assert results[0].match_type == "exact"

    def test_filter_articles_false_still_matches_term(self):
        """With filter_articles=False, 'the Agent' still matches (space is word boundary)."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=False, filter_articles=False)
        result = matcher.find_relevant_glossary_terms("Contact the Agent now.")
        assert result == {"Agent": "特工"}


# ---------------------------------------------------------------------------
# Glossary immutability
# ---------------------------------------------------------------------------


class TestGlossaryImmutability:
    """Original glossary dict is never mutated."""

    def test_unchanged_after_construction(self):
        glossary = {"Agent": "特工", "Handler": "管理者"}
        original = dict(glossary)
        ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=True)
        assert glossary == original

    def test_unchanged_after_matching(self):
        glossary = {"Agent": "特工", "Handler": "管理者"}
        original = dict(glossary)
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=True)
        matcher.find_relevant_glossary_terms("The Agents met the Handlers.")
        assert glossary == original

    def test_external_mutation_does_not_affect_matcher(self):
        """Mutating the original dict after construction doesn't affect matcher."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=True)
        glossary["NewTerm"] = "新术语"
        result = matcher.find_relevant_glossary_terms("Agent and NewTerm here.")
        assert "Agent" in result
        assert "NewTerm" not in result


# ---------------------------------------------------------------------------
# Combined scenarios
# ---------------------------------------------------------------------------


class TestCombinedPluralArticle:
    """Combined plural + article scenarios."""

    def test_the_agents(self):
        """'the Agents' matches glossary 'Agent' (article + plural)."""
        glossary = {"Agent": "特工"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=True)
        result = matcher.find_relevant_glossary_terms("Contact the Agents immediately.")
        assert result == {"Agent": "特工"}

    def test_multiple_terms_mixed(self):
        """Multiple terms with various articles and plurals all match."""
        glossary = {"Agent": "特工", "Handler": "管理者", "Investigator": "调查员"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=True)
        text = "The Agents reported to a Handler. An Investigator was assigned."
        result = matcher.find_relevant_glossary_terms(text)
        assert "Agent" in result
        assert "Handler" in result
        assert "Investigator" in result

    def test_an_with_plural_entities(self):
        """'the Entities' matches glossary 'Entity'."""
        glossary = {"Entity": "实体"}
        matcher = ACGlossaryMatcher(glossary, normalize_plurals=True, filter_articles=True)
        result = matcher.find_relevant_glossary_terms("Beware the Entities lurking below.")
        assert result == {"Entity": "实体"}
