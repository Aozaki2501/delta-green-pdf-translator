"""Quality-report adapter for block-based high-fidelity translations."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from core.quality import (
    QualityIssue,
    QualityReport,
    build_quality_report,
    render_quality_report_markdown,
)
from core.typeset_models import PageContentDocument
from core.utils import atomic_output_path


def build_typeset_quality_report(
    content: PageContentDocument,
    glossary: dict | None = None,
    *,
    title: str = "高保真译文质量检查",
) -> QualityReport:
    source_pages = {
        page.page_index: "\n".join(
            block.source_text
            for block in page.blocks
            if block.translatable and block.source_text.strip()
        )
        for page in content.pages
    }
    translated_pages = {
        page.page_index: "\n".join(
            block.translated_text or ""
            for block in page.blocks
            if block.translatable
        )
        for page in content.pages
    }
    report = build_quality_report(
        source_pages,
        translated_pages,
        glossary=glossary or {},
        title=title,
    )
    report.issues.extend(_mixed_emphasis_issues(content))
    report.issues.sort(key=lambda issue: (issue.page_num, issue.kind, issue.detail))
    return report


def _mixed_emphasis_issues(
    content: PageContentDocument,
) -> list[QualityIssue]:
    """Flag mixed source emphasis that an old translation cannot reconstruct."""
    issues: list[QualityIssue] = []
    for page in content.pages:
        missing: list[str] = []
        for block in page.blocks:
            translated = block.translated_text or ""
            if not block.translatable or not translated:
                continue
            visible_runs = [run for run in block.runs if run.text.strip()]
            if len(visible_runs) < 2:
                continue
            source_from_runs = "".join(run.text for run in block.runs).replace("\u00ad", "")
            if source_from_runs != block.source_text.replace("\u00ad", ""):
                continue
            mixed_italic = any(run.italic for run in visible_runs) and any(
                not run.italic for run in visible_runs
            )
            mixed_bold = any(run.bold for run in visible_runs) and any(
                not run.bold for run in visible_runs
            )
            absent = []
            if mixed_italic and "<em>" not in translated:
                absent.append("斜体")
            if mixed_bold and "<strong>" not in translated:
                absent.append("粗体")
            if absent:
                missing.append(f"{block.id}（{'、'.join(absent)}）")
        if missing:
            issues.append(QualityIssue(
                page_num=page.page_index + 1,
                kind="emphasis_unmapped",
                message="混排强调样式未映射到译文",
                detail="；".join(missing[:8]),
            ))
    return issues


def write_typeset_quality_report(
    report: QualityReport,
    markdown_path: str | Path,
    json_path: str | Path,
) -> None:
    markdown = Path(markdown_path)
    payload = Path(json_path)
    with atomic_output_path(markdown) as candidate:
        candidate.write_text(
            render_quality_report_markdown(report), encoding="utf-8"
        )
    with atomic_output_path(payload) as candidate:
        candidate.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )


__all__ = ["build_typeset_quality_report", "write_typeset_quality_report"]
