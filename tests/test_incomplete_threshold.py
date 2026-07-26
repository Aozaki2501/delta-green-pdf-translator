"""Calibration of the "translation looks truncated" ratio.

The threshold was 0.15, which only caught translations that had lost ~85% of
their content. It was raised to 0.25 using the ratios measured on a real
completed run (31 healthy pages of Delta Green Presence ranged 0.383-0.542),
leaving roughly a 1.5x margin below the worst healthy page. This matters in
both directions: too low misses truncations, and too high marks healthy pages
as failed and blocks them from the exported document.
"""

from core.utils import (
    INCOMPLETE_RATIO_BY_LAYOUT,
    INCOMPLETE_RATIO_DEFAULT,
    incomplete_ratio_threshold,
    looks_incomplete_translation,
)


class TestThresholdSelection:
    def test_default_threshold(self):
        assert incomplete_ratio_threshold() == INCOMPLETE_RATIO_DEFAULT

    def test_unknown_layout_uses_the_default(self):
        assert incomplete_ratio_threshold("columns") == INCOMPLETE_RATIO_DEFAULT

    def test_dense_layouts_use_a_looser_threshold(self):
        """A table of contents is mostly numbers, so its ratio is legitimately low."""
        assert incomplete_ratio_threshold("toc") < INCOMPLETE_RATIO_DEFAULT
        assert incomplete_ratio_threshold("handout") < INCOMPLETE_RATIO_DEFAULT

    def test_empty_layout_is_tolerated(self):
        assert incomplete_ratio_threshold("") == INCOMPLETE_RATIO_DEFAULT
        assert incomplete_ratio_threshold(None) == INCOMPLETE_RATIO_DEFAULT

    def test_threshold_stays_below_observed_healthy_ratios(self):
        """Guard against re-tightening past what real pages actually produce."""
        worst_healthy_ratio = 0.383
        assert INCOMPLETE_RATIO_DEFAULT < worst_healthy_ratio
        for value in INCOMPLETE_RATIO_BY_LAYOUT.values():
            assert value < worst_healthy_ratio

    def test_threshold_is_stricter_than_the_old_value(self):
        assert INCOMPLETE_RATIO_DEFAULT > 0.15


class TestLooksIncompleteTranslation:
    # 40 repetitions give 1600 visible chars, enough to clear the function's
    # minimum-length guards (>=1200 visible, >=700 latin, >=120 words).
    SOURCE = "The agent walks into the room and finds the body. " * 40
    # One repetition is 13 visible chars, so the ratio is 13 * n / 1600.
    SENTENCE = "特工走进房间，发现了尸体。"

    def test_severely_truncated_translation_is_flagged(self):
        # ratio ~0.07
        assert looks_incomplete_translation(self.SOURCE, self.SENTENCE * 8)

    def test_healthy_translation_is_not_flagged(self):
        # ratio ~0.47, inside the 0.383-0.542 band measured on real pages.
        assert not looks_incomplete_translation(self.SOURCE, self.SENTENCE * 58)

    def test_worst_observed_healthy_ratio_is_not_flagged(self):
        # ratio ~0.38, the lowest healthy page in the measured run.
        assert not looks_incomplete_translation(self.SOURCE, self.SENTENCE * 47)

    def test_ratio_between_old_and_new_threshold_is_now_caught(self):
        """A page at ratio ~0.2 slipped through under 0.15 and is caught under 0.25."""
        assert looks_incomplete_translation(self.SOURCE, self.SENTENCE * 25)

    def test_short_pages_are_never_flagged(self):
        """A caption or a title page has no length signal worth trusting."""
        assert not looks_incomplete_translation("A short line of text.", "一行短文本。")

    def test_art_pages_are_exempt(self):
        assert not looks_incomplete_translation(self.SOURCE, self.SENTENCE, layout="art")
