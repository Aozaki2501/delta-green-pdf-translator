from core.rule_symbols import (
    build_rule_symbol_issues,
    render_rule_symbol_report,
    write_rule_symbol_report,
)


def test_rule_symbol_check_flags_missing_dice_and_san():
    issues = build_rule_symbol_issues(
        {0: "The failed ritual costs 1D6 SAN."},
        {0: "失败的仪式造成理智损失。"},
    )

    symbols = {issue.symbol for issue in issues}
    assert "1D6" in symbols
    assert "SAN" in symbols
    assert any(issue.kind == "缩写翻译" and issue.symbol == "SAN" for issue in issues)


def test_rule_symbol_check_accepts_preserved_symbols_case_insensitive_dice():
    issues = build_rule_symbol_issues(
        {0: "The failed ritual costs 1D6 SAN."},
        {0: "失败的仪式造成 1d6 SAN 损失。"},
    )

    assert issues == []


def test_rule_symbol_check_accepts_preserved_san_loss_case_insensitive():
    issues = build_rule_symbol_issues(
        {0: "The failed ritual costs 1/1D6 SAN."},
        {0: "失败的仪式造成 1/1d6 SAN 损失。"},
    )

    assert issues == []


def test_rule_symbol_check_flags_missing_attributes():
    issues = build_rule_symbol_issues(
        {0: "STR 11 CON 10 DEX 9 INT 14 POW 16 CHA 13"},
        {0: "力量 11 体质 10 敏捷 9 智力 14 意志 16 魅力 13"},
    )

    symbols = {issue.symbol for issue in issues}
    assert {"STR", "CON", "DEX", "INT", "POW", "CHA"}.issubset(symbols)
    assert any(issue.kind == "缩写翻译" for issue in issues)


def test_rule_symbol_check_flags_skill_name_residue():
    issues = build_rule_symbol_issues(
        {0: "An Agent who succeeds at a HUMINT roll knows the truth."},
        {0: "通过 HUMINT roll 的特工知道真相。"},
    )

    assert any(issue.kind == "技能残留" and issue.symbol == "HUMINT" for issue in issues)


def test_rule_symbol_report_renders_summary(tmp_path):
    issues = build_rule_symbol_issues(
        {0: "Lose 1/1D6 SAN."},
        {0: "损失理智。"},
    )
    output = tmp_path / "rules.md"

    write_rule_symbol_report(issues, str(output), "测试")
    markdown = output.read_text(encoding="utf-8")

    assert markdown.startswith("# 测试")
    assert "规则符号检查" in markdown
    assert "问题数" in render_rule_symbol_report(issues)
