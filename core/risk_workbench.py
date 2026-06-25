"""Failure and risk workbench helpers for PDF translation runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RiskWorkbenchItem:
    page_num: int
    category: str
    title: str
    detail: str = ""
    source_excerpt: str = ""
    translation_excerpt: str = ""
    retryable: bool = True


def build_risk_workbench_items(quality_report=None, page_diagnostics=None) -> list[RiskWorkbenchItem]:
    items: list[RiskWorkbenchItem] = []
    if quality_report:
        for issue in getattr(quality_report, "issues", []) or []:
            items.append(RiskWorkbenchItem(
                page_num=int(getattr(issue, "page_num", 0) or 0),
                category=_quality_category(str(getattr(issue, "kind", "") or "")),
                title=str(getattr(issue, "message", "") or "质量问题"),
                detail=str(getattr(issue, "detail", "") or ""),
                source_excerpt=str(getattr(issue, "source_excerpt", "") or ""),
                translation_excerpt=str(getattr(issue, "translation_excerpt", "") or ""),
                retryable=True,
            ))

    for diagnostic in page_diagnostics or []:
        risks = [str(risk) for risk in diagnostic.get("risks", []) if str(risk).strip()]
        if not risks:
            continue
        page_num = int(diagnostic.get("page", 0) or 0) + 1
        items.append(RiskWorkbenchItem(
            page_num=page_num,
            category="提取风险",
            title="；".join(risks),
            detail=(
                f"版面：{diagnostic.get('layout', 'unknown')}；"
                f"文本量：{diagnostic.get('text_length', 0)}；"
                f"图片：{diagnostic.get('image_count', 0)}"
            ),
            retryable=not any("未提取到正文" in risk for risk in risks),
        ))

    items = [item for item in items if item.page_num > 0]
    items.sort(key=lambda item: (item.page_num, item.category, item.title))
    return items


def ignored_risk_pages(items: list[RiskWorkbenchItem], ignored_pages) -> list[RiskWorkbenchItem]:
    ignored = {int(page) for page in ignored_pages or []}
    return [item for item in items if item.page_num not in ignored]


def risk_workbench_rows(items: list[RiskWorkbenchItem]) -> list[dict]:
    return [
        {
            "页码": item.page_num,
            "类别": item.category,
            "问题": item.title,
            "说明": item.detail,
            "可重翻": "是" if item.retryable else "否",
        }
        for item in items
    ]


def render_risk_workbench_markdown(items: list[RiskWorkbenchItem], title: str = "") -> str:
    heading = f"# {title} — 失败页/风险页工作台" if title else "# 失败页/风险页工作台"
    lines = [
        heading,
        "",
        f"- 风险条目：{len(items)}",
        f"- 涉及页数：{len({item.page_num for item in items})}",
        "",
        "## 清单",
        "",
    ]
    if not items:
        lines.append("- 暂无。")
    else:
        lines.extend(["| 页码 | 类别 | 问题 | 说明 |", "| ---: | --- | --- | --- |"])
        for item in items:
            lines.append(
                f"| {item.page_num} | {item.category} | "
                f"{_escape_table(item.title)} | {_escape_table(item.detail)} |"
            )
    lines.append("")
    return "\n".join(lines)


def write_risk_workbench_report(items: list[RiskWorkbenchItem], output_path: str, title: str = "") -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(render_risk_workbench_markdown(items, title))


def _quality_category(kind: str) -> str:
    return {
        "failed": "翻译失败",
        "missing": "无译文",
        "untranslated": "疑似未翻页",
        "incomplete": "疑似截断",
        "english_residue": "英文残留",
        "glossary_miss": "术语冲突",
        "rule_symbol": "规则符号",
    }.get(kind, "质量问题")


def _escape_table(text: str) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")
