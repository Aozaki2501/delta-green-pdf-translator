"""Rule numbers must survive translation, not just rule symbols.

The existing checks covered dice notation and abbreviations like SAN. A model
that rewrote "Armor 3" as "护甲 5", or dropped a skill percentage entirely,
produced a fluent Chinese page that no check objected to — and the length-ratio
heuristic cannot see a single wrong digit.
"""

from core.rule_symbols import build_rule_symbol_issues


def _kinds(source, translation):
    issues = build_rule_symbol_issues({0: source}, {0: translation})
    return {issue.kind for issue in issues}


class TestValuesPreserved:
    def test_all_values_kept_raises_nothing(self):
        source = (
            "Firearms 40%. Armor 3. Lethality 10%. Range 50 meters. Damage 1D6+2."
        )
        translation = "枪械 40%。护甲 3。致死率 10%。射程 50 米。伤害 1D6+2。"

        assert build_rule_symbol_issues({0: source}, {0: translation}) == []

    def test_translated_unit_is_accepted(self):
        """Only the number is checked; "meters" is supposed to become "米"."""
        assert _kinds("Range 50 meters.", "射程 50 米。") == set()

    def test_calibre_is_not_treated_as_a_range(self):
        assert _kinds("He drew a 9mm pistol.", "他掏出一把 9mm 手枪。") == set()


class TestMissingValues:
    def test_dropped_skill_percentage_is_flagged(self):
        assert "百分比" in _kinds("His Firearms 40% is enough.", "他的枪械足够了。")

    def test_rewritten_armor_value_is_flagged(self):
        assert "护甲" in _kinds("Armor 3 protects him.", "护甲 5 保护了他。")

    def test_dropped_lethality_is_flagged(self):
        assert "致死率" in _kinds("Lethality 20% weapon.", "这是致命武器。")

    def test_dropped_range_is_flagged(self):
        assert "射程" in _kinds("The rifle has Range 400 meters.", "步枪射程很远。")

    def test_dropped_damage_modifier_is_flagged(self):
        assert "伤害修正" in _kinds("It deals 1D6+4 damage.", "它造成 1D6 伤害。")

    def test_skill_value_is_flagged(self):
        assert "技能值" in _kinds(
            "Occult 55 lets him recognize the sigil.",
            "神秘学让他认出了这个符号。",
        )

    def test_british_spelling_of_armour_is_covered(self):
        assert "护甲" in _kinds("Armour 4 plating.", "装甲板。")


class TestIssueContent:
    def test_message_names_the_missing_value(self):
        issues = build_rule_symbol_issues(
            {0: "Armor 3 protects him."}, {0: "护甲 5 保护了他。"}
        )
        armor = [issue for issue in issues if issue.kind == "护甲"]

        assert armor
        assert "3" in armor[0].message

    def test_issue_carries_the_page_number(self):
        issues = build_rule_symbol_issues(
            {7: "Armor 3 protects him."}, {7: "护甲 5 保护了他。"}
        )

        assert all(issue.page_num == 8 for issue in issues)

    def test_repeated_value_is_reported_once_per_kind(self):
        issues = build_rule_symbol_issues(
            {0: "Armor 3. Armor 3. Armor 3."}, {0: "装甲板。"}
        )
        armor = [issue for issue in issues if issue.kind == "护甲"]

        assert len(armor) == 1
