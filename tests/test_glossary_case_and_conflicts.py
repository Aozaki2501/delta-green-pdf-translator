"""Case-sensitive term matching and loud rejection of conflicting entries.

Matching used to lowercase everything, so a glossary holding both
"Agent -> 特工" and "agent -> 探员" silently resolved to whichever entry the
dictionary happened to yield first — different every load. Exact duplicates of
the same English term were equally silent.
"""

import pytest

from core.glossary import (
    ACGlossaryMatcher,
    _find_relevant_glossary_terms_regex,
    load_glossary,
)


def _write_glossary(tmp_path, lines):
    path = tmp_path / "glossary.tsv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


class TestConflictDetection:
    def test_duplicate_english_term_raises(self, tmp_path):
        path = _write_glossary(tmp_path, [
            "特工\tAgent",
            "探员\tAgent",
        ])

        with pytest.raises(ValueError) as exc:
            load_glossary(path)

        assert "冲突" in str(exc.value)

    def test_error_names_both_line_numbers_and_translations(self, tmp_path):
        path = _write_glossary(tmp_path, [
            "绿色三角洲\tDelta Green",
            "特工\tAgent",
            "探员\tAgent",
        ])

        with pytest.raises(ValueError) as exc:
            load_glossary(path)

        message = str(exc.value)
        assert "第 2 行" in message
        assert "第 3 行" in message
        assert "特工" in message
        assert "探员" in message

    def test_case_differing_terms_are_not_a_conflict(self, tmp_path):
        """Different casing is a legitimate distinction, not a duplicate."""
        path = _write_glossary(tmp_path, [
            "特工\tAgent",
            "探员\tagent",
        ])

        glossary = load_glossary(path)

        assert glossary["Agent"] == "特工"
        assert glossary["agent"] == "探员"

    def test_identical_repeated_line_is_benign(self, tmp_path):
        """A verbatim repeat says nothing contradictory, so it must not block a run."""
        path = _write_glossary(tmp_path, [
            "特工\tAgent",
            "特工\tAgent",
        ])

        assert load_glossary(path) == {"Agent": "特工"}


class TestCaseSensitiveMatching:
    GLOSSARY = {"Agent": "特工", "agent": "探员", "Handler": "管理者"}

    def test_regex_path_prefers_the_matching_case(self):
        upper = _find_relevant_glossary_terms_regex("The Agent reports.", self.GLOSSARY)
        lower = _find_relevant_glossary_terms_regex("A lone agent reports.", self.GLOSSARY)

        assert upper.get("Agent") == "特工"
        assert lower.get("agent") == "探员"

    def test_ac_path_prefers_the_matching_case(self):
        matcher = ACGlossaryMatcher(self.GLOSSARY)

        upper = matcher.find_relevant_glossary_terms("The Agent reports.")
        lower = matcher.find_relevant_glossary_terms("A lone agent reports.")

        assert upper.get("Agent") == "特工"
        assert lower.get("agent") == "探员"

    def test_both_paths_agree(self):
        matcher = ACGlossaryMatcher(self.GLOSSARY)
        text = "The Agent met another agent and the Handler."

        assert matcher.find_relevant_glossary_terms(text) == _find_relevant_glossary_terms_regex(
            text, self.GLOSSARY
        )

    def test_plurals_resolve_to_the_matching_case(self):
        matcher = ACGlossaryMatcher(self.GLOSSARY)

        assert matcher.find_relevant_glossary_terms("Two Agents arrived.").get("Agent") == "特工"
        assert matcher.find_relevant_glossary_terms("Two agents arrived.").get("agent") == "探员"

    def test_unmatched_case_still_falls_back_to_a_translation(self):
        """An all-caps heading must still receive a term, not be skipped."""
        matcher = ACGlossaryMatcher(self.GLOSSARY)

        found = matcher.find_relevant_glossary_terms("AGENT BRIEFING")

        assert found
        assert set(found.values()) <= {"特工", "探员"}
