import zipfile

from core.glossary import GlossaryCandidate
from core.quality import QualityIssue, QualityReport
from core.rule_symbols import RuleSymbolIssue
from core.timeline import TimelineEvent
from core.word_review import (
    HAS_DOCX,
    build_word_review_items,
    render_word_review_markdown,
    write_word_review_docx,
    write_word_review_markdown,
)


def test_word_review_items_collect_all_sources():
    quality = QualityReport(issues=[QualityIssue(page_num=2, kind="missing", message="没有译文")])
    glossary = [GlossaryCandidate(term="The Program", count=3, pages=[0, 2])]
    rules = [RuleSymbolIssue(page_num=1, kind="骰子", symbol="1D6", message="未保留")]
    timeline = [TimelineEvent(page_num=4, marker="D-1", event="D-1：事件开始。")]

    items = build_word_review_items(
        quality_report=quality,
        glossary_candidates=glossary,
        rule_symbol_issues=rules,
        timeline_events=timeline,
    )

    categories = {item.category for item in items}
    assert {"问题页索引", "术语疑点", "规则符号", "时间线"}.issubset(categories)


def test_word_review_markdown_renders_table(tmp_path):
    items = build_word_review_items(
        quality_report=QualityReport(issues=[QualityIssue(page_num=2, kind="missing", message="没有译文")])
    )
    path = tmp_path / "review.md"

    write_word_review_markdown(items, str(path), "测试")
    markdown = path.read_text(encoding="utf-8")

    assert markdown.startswith("# 测试")
    assert "Word 校对包" in render_word_review_markdown(items)
    assert "| 2 | 问题页索引 | 没有译文 |  |" in markdown


def test_word_review_docx_writes_table(tmp_path):
    if not HAS_DOCX:
        return
    items = build_word_review_items(
        quality_report=QualityReport(issues=[QualityIssue(page_num=2, kind="missing", message="没有译文")])
    )
    path = tmp_path / "review.docx"

    write_word_review_docx(items, str(path), "测试")

    with zipfile.ZipFile(path) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")
    assert "Word 校对包" in document_xml
    assert "没有译文" in document_xml

