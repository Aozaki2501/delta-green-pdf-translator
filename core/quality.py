"""
Translation quality report helpers.

Builds a compact deterministic report for PDF translation runs so Web UI and
CLI can show the same post-translation checks.
"""

import re
from dataclasses import dataclass, field

from core.glossary import find_relevant_glossary_terms
from core.rule_symbols import build_rule_symbol_issues
from core.utils import (
    count_cjk_chars,
    count_latin_chars,
    is_failed_translation,
    looks_incomplete_translation,
    looks_untranslated_page,
)


@dataclass
class QualityIssue:
    page_num: int
    kind: str
    message: str
    detail: str = ""
    source_excerpt: str = ""
    translation_excerpt: str = ""


@dataclass
class QualityReport:
    title: str = ""
    total_pages: int = 0
    translated_pages: int = 0
    failed_pages: list[int] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
    glossary_hits: int = 0
    glossary_misses: int = 0

    @property
    def issue_pages(self) -> list[int]:
        return sorted({issue.page_num for issue in self.issues})

    @property
    def warning_count(self) -> int:
        return len(self.issues)


def build_quality_report(
    pages_text: dict[int, str],
    translations: dict[int, str],
    page_layouts: dict[int, str] | None = None,
    glossary: dict | None = None,
    glossary_matcher=None,
    failed_reasons: dict[int, str] | None = None,
    title: str = "",
) -> QualityReport:
    page_layouts = page_layouts or {}
    glossary = glossary or {}
    failed_reasons = failed_reasons or {}
    rule_symbol_issues = build_rule_symbol_issues(pages_text, translations)
    rule_issues_by_page = {}
    for issue in rule_symbol_issues:
        rule_issues_by_page.setdefault(issue.page_num, []).append(issue)
    page_nums = sorted(set(pages_text) | set(translations) | set(failed_reasons))
    report = QualityReport(
        title=title,
        total_pages=len(page_nums),
        translated_pages=sum(1 for text in translations.values() if str(text or "").strip()),
        failed_pages=[page_num + 1 for page_num in sorted(failed_reasons)],
    )

    for page_num in page_nums:
        source = pages_text.get(page_num, "")
        translation = translations.get(page_num, "")
        layout = page_layouts.get(page_num, "")
        display_page = page_num + 1

        failed_reason = failed_reasons.get(page_num)
        if failed_reason:
            report.issues.append(QualityIssue(
                page_num=display_page,
                kind="failed",
                message="翻译失败",
                detail=failed_reason,
                source_excerpt=_excerpt(source),
                translation_excerpt=_excerpt(translation),
            ))
            continue
        if not str(translation or "").strip():
            report.issues.append(QualityIssue(
                page_num=display_page,
                kind="missing",
                message="没有译文",
                source_excerpt=_excerpt(source),
            ))
            continue
        if is_failed_translation(translation):
            report.issues.append(QualityIssue(
                page_num=display_page,
                kind="failed",
                message="翻译失败",
                detail=translation,
                source_excerpt=_excerpt(source),
                translation_excerpt=_excerpt(translation),
            ))
            continue

        if looks_untranslated_page(source, translation, layout):
            report.issues.append(QualityIssue(
                page_num=display_page,
                kind="untranslated",
                message="疑似整页未翻译",
                source_excerpt=_excerpt(source),
                translation_excerpt=_excerpt(translation),
            ))
        elif looks_incomplete_translation(source, translation, layout):
            report.issues.append(QualityIssue(
                page_num=display_page,
                kind="incomplete",
                message="疑似译文截断",
                source_excerpt=_excerpt(source),
                translation_excerpt=_excerpt(translation),
            ))

        residue_detail = _english_residue_detail(translation)
        if residue_detail:
            report.issues.append(QualityIssue(
                page_num=display_page,
                kind="english_residue",
                message="英文残留较多",
                detail=residue_detail,
                source_excerpt=_excerpt(source),
                translation_excerpt=_excerpt(translation),
            ))

        glossary_hits = (
            find_relevant_glossary_terms(source, glossary, matcher=glossary_matcher)
            if glossary else {}
        )
        report.glossary_hits += len(glossary_hits)
        missing_terms = [
            f"{eng}->{chn}"
            for eng, chn in glossary_hits.items()
            if _is_glossary_target_missing(str(translation), str(chn))
        ]
        if missing_terms:
            report.glossary_misses += len(missing_terms)
            report.issues.append(QualityIssue(
                page_num=display_page,
                kind="glossary_miss",
                message="术语可能未按表翻译",
                detail=", ".join(missing_terms[:8]),
                source_excerpt=_excerpt(source),
                translation_excerpt=_excerpt(translation),
            ))

        for rule_issue in rule_issues_by_page.get(display_page, []):
            report.issues.append(QualityIssue(
                page_num=display_page,
                kind="rule_symbol",
                message="规则符号疑点",
                detail=f"{rule_issue.kind}：{rule_issue.symbol}；{rule_issue.message}",
                source_excerpt=rule_issue.source_excerpt,
                translation_excerpt=rule_issue.translation_excerpt,
            ))

    return report


def render_quality_report_markdown(report: QualityReport) -> str:
    title = report.title or "质量检查报告"
    lines = [
        f"# {title}",
        "",
        "## 汇总",
        "",
        f"- 检查页数：{report.total_pages}",
        f"- 有译文页数：{report.translated_pages}",
        f"- 失败页数：{len(report.failed_pages)}",
        f"- 待检查问题：{report.warning_count}",
        f"- 术语命中：{report.glossary_hits}",
        f"- 术语可能遗漏：{report.glossary_misses}",
        "",
        "## 问题页",
        "",
    ]
    if not report.issues:
        lines.append("- 暂无。")
    else:
        for issue in report.issues:
            detail = f"；{issue.detail}" if issue.detail else ""
            lines.append(f"- 第 {issue.page_num} 页：{issue.message}{detail}")
            if issue.source_excerpt:
                lines.append(f"  - 原文片段：{issue.source_excerpt}")
            if issue.translation_excerpt:
                lines.append(f"  - 译文片段：{issue.translation_excerpt}")
    lines.append("")
    return "\n".join(lines)


def write_quality_report(report: QualityReport, output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(render_quality_report_markdown(report))


def _english_residue_detail(text: str) -> str:
    compact = re.sub(r"\s+", "", text or "")
    if len(compact) < 160:
        return ""
    cjk = count_cjk_chars(compact)
    latin = count_latin_chars(compact)
    if latin < 160:
        return ""
    ratio = latin / max(cjk + latin, 1)
    if ratio < 0.35:
        return ""
    return f"英文字符约 {latin} 个，占中英文字符 {ratio:.0%}"


def _is_glossary_target_missing(translation: str, chinese: str) -> bool:
    target = chinese.strip()
    if not target:
        return False
    if not re.search(r"[\u4e00-\u9fff]", target):
        return False
    return target not in translation


def _excerpt(text: str, limit: int = 420) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."
