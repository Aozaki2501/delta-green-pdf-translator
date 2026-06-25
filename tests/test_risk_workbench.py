from core.quality import QualityIssue, QualityReport
from core.risk_workbench import (
    build_risk_workbench_items,
    ignored_risk_pages,
    render_risk_workbench_markdown,
    risk_workbench_rows,
)


def test_build_risk_workbench_items_merges_quality_and_diagnostics():
    report = QualityReport(
        issues=[
            QualityIssue(page_num=2, kind="failed", message="翻译失败", detail="timeout"),
            QualityIssue(page_num=3, kind="glossary_miss", message="术语遗漏", detail="Agent->特工"),
        ]
    )
    diagnostics = [
        {"page": 1, "risks": ["疑似乱码或 OCR 损坏"], "layout": "columns", "text_length": 12, "image_count": 1},
        {"page": 4, "risks": [], "layout": "single", "text_length": 100, "image_count": 0},
    ]

    items = build_risk_workbench_items(report, diagnostics)

    assert [(item.page_num, item.category) for item in items] == [
        (2, "提取风险"),
        (2, "翻译失败"),
        (3, "术语冲突"),
    ]


def test_unextracted_page_is_not_retryable():
    items = build_risk_workbench_items(
        page_diagnostics=[
            {"page": 0, "risks": ["未提取到正文"], "layout": "art", "text_length": 0, "image_count": 1},
        ]
    )

    assert items[0].retryable is False


def test_ignored_risk_pages_filters_by_page():
    items = build_risk_workbench_items(
        QualityReport(issues=[
            QualityIssue(page_num=1, kind="missing", message="没有译文"),
            QualityIssue(page_num=2, kind="untranslated", message="疑似未翻页"),
        ])
    )

    remaining = ignored_risk_pages(items, [1])

    assert [item.page_num for item in remaining] == [2]


def test_risk_workbench_rows_are_table_ready():
    items = build_risk_workbench_items(
        QualityReport(issues=[QualityIssue(page_num=1, kind="english_residue", message="英文残留")])
    )

    rows = risk_workbench_rows(items)

    assert rows == [
        {"页码": 1, "类别": "英文残留", "问题": "英文残留", "说明": "", "可重翻": "是"}
    ]


def test_risk_workbench_markdown_renders_summary():
    items = build_risk_workbench_items(
        QualityReport(issues=[QualityIssue(page_num=1, kind="missing", message="没有译文")])
    )

    markdown = render_risk_workbench_markdown(items, "测试")

    assert markdown.startswith("# 测试")
    assert "风险条目：1" in markdown
    assert "| 1 | 无译文 | 没有译文 |  |" in markdown

