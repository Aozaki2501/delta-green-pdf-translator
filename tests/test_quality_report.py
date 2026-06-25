from core.quality import build_quality_report, render_quality_report_markdown


def test_quality_report_flags_failed_missing_and_glossary_miss():
    pages_text = {
        0: "The Agent reports to Delta Green.",
        1: "The Handler waits outside.",
        2: "The agents enter the chamber.",
    }
    translations = {
        0: "特工向组织报告。",
        2: "",
    }
    glossary = {
        "Agent": "特工",
        "Delta Green": "绿色三角洲",
        "Handler": "管理者",
    }

    report = build_quality_report(
        pages_text=pages_text,
        translations=translations,
        glossary=glossary,
        failed_reasons={1: "API timeout"},
        title="测试报告",
    )

    assert report.total_pages == 3
    assert report.translated_pages == 1
    assert report.failed_pages == [2]
    assert any(issue.kind == "glossary_miss" and issue.page_num == 1 for issue in report.issues)
    assert any(issue.kind == "failed" and issue.page_num == 2 for issue in report.issues)
    assert any(issue.kind == "missing" and issue.page_num == 3 for issue in report.issues)


def test_quality_report_flags_english_residue_without_blocking():
    source = " ".join(["The agents enter the chamber and study the wall."] * 20)
    translated = "中文说明。" * 10 + " " + " ".join(
        ["The agents enter the chamber and study the wall."] * 20
    )

    report = build_quality_report(
        pages_text={0: source},
        translations={0: translated},
        page_layouts={0: "columns"},
    )

    assert any(issue.kind == "english_residue" for issue in report.issues)
    assert not report.failed_pages


def test_quality_report_markdown_contains_summary_and_issues():
    report = build_quality_report(
        pages_text={0: "The Agent reports."},
        translations={0: "特工报告。"},
        glossary={"Agent": "特工"},
        title="测试报告",
    )

    markdown = render_quality_report_markdown(report)

    assert markdown.startswith("# 测试报告")
    assert "检查页数：1" in markdown
    assert "暂无" in markdown


def test_quality_report_includes_rule_symbol_issues():
    report = build_quality_report(
        pages_text={0: "The blast costs 1D6 SAN."},
        translations={0: "爆炸造成理智损失。"},
    )

    assert any(issue.kind == "rule_symbol" for issue in report.issues)
