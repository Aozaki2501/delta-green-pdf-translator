"""
Glossary loading, term matching, and report generation.

Provides functions for loading TRPG glossary TSV files, finding relevant
glossary terms in source text (longest-match-first, non-overlapping), and
generating Markdown glossary reports.

Dependencies: core.utils (for ensure_output_parent), standard library only.
"""

import os
import re

from core.utils import ensure_output_parent


def load_glossary(glossary_path: str) -> dict:
    glossary = {}
    if not glossary_path or not os.path.exists(glossary_path):
        return glossary
    with open(glossary_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "\t" in line:
                parts = line.split("\t", 1)
            else:
                parts = re.split(r"\s{2,}", line, maxsplit=1)
            if len(parts) == 2:
                chinese = parts[0].strip()
                english = parts[1].strip()
                if english and chinese:
                    glossary[english] = chinese
    return glossary


def find_relevant_glossary_terms(text: str, glossary: dict) -> dict:
    matches = []
    for eng, chn in sorted(glossary.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(eng) + r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            matches.append((match.start(), match.end(), eng, chn))

    selected = []
    occupied_spans = []
    for start, end, eng, chn in matches:
        if any(start < occupied_end and end > occupied_start for occupied_start, occupied_end in occupied_spans):
            continue
        selected.append((eng, chn))
        occupied_spans.append((start, end))

    relevant = {}
    for eng, chn in selected:
        relevant[eng] = chn
    return relevant


def _find_unlisted_proper_nouns(text: str, glossary_hits: dict) -> list[str]:
    known = {term.lower() for term in glossary_hits}
    stopwords = {
        "A", "An", "And", "Are", "As", "At", "Be", "But", "By", "For", "From", "He",
        "Her", "His", "If", "In", "Into", "Is", "It", "Its", "Of", "On", "Or", "She",
        "The", "Their", "They", "This", "To", "Was", "Were", "When", "With", "You",
        "Chapter", "Page", "Table", "Figure",
    }
    candidates = {}
    pattern = re.compile(r"\b(?:[A-Z][A-Za-z''.-]+)(?:\s+(?:of|the|and|&|[A-Z][A-Za-z''.-]+))*\b")
    for match in pattern.finditer(text):
        candidate = match.group(0).strip(" -.,:;!?()[]{}\"""")
        if len(candidate) < 3 or candidate in stopwords:
            continue
        if candidate.isupper() and len(candidate) <= 6:
            continue
        if candidate.lower() in known:
            continue
        candidates[candidate] = candidates.get(candidate, 0) + 1
    return [
        term for term, _ in sorted(candidates.items(), key=lambda item: (-item[1], item[0].lower()))[:20]
    ]


def _format_page_ranges(page_nums):
    nums = sorted({p + 1 for p in page_nums})
    if not nums:
        return ""
    ranges = []
    start = prev = nums[0]
    for num in nums[1:]:
        if num == prev + 1:
            prev = num
            continue
        ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
        start = prev = num
    ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(ranges)


def build_glossary_report(pages_text: dict, glossary: dict, title: str = "") -> str:
    lines = [
        f"# {title} — 术语命中报告" if title else "# 术语命中报告",
        "",
        "本报告基于提取后的英文原文生成，用于检查每页实际命中的术语。",
        "",
    ]
    if not glossary:
        lines.append("未使用术语表。")
        return "\n".join(lines)

    summary = {}
    page_reports = []
    missing_candidates = {}

    for page_num in sorted(pages_text):
        text = pages_text.get(page_num, "")
        hits = find_relevant_glossary_terms(text, glossary)
        for eng, chn in hits.items():
            summary.setdefault(eng, {"chinese": chn, "pages": set()})
            summary[eng]["pages"].add(page_num + 1)
        missing = _find_unlisted_proper_nouns(text, hits)
        for term in missing:
            missing_candidates.setdefault(term, set()).add(page_num + 1)
        page_reports.append((page_num + 1, hits, missing))

    lines.append("## 汇总")
    lines.append("")
    if summary:
        for eng, info in sorted(summary.items(), key=lambda item: item[0].lower()):
            pages = _format_page_ranges([p - 1 for p in info["pages"]])
            lines.append(f"- `{eng}` -> `{info['chinese']}`；页：{pages}")
    else:
        lines.append("- 未命中任何术语。")

    lines.append("")
    lines.append("## 逐页命中")
    lines.append("")
    for page_num, hits, missing in page_reports:
        lines.append(f"### 第 {page_num} 页")
        if hits:
            for eng, chn in sorted(hits.items(), key=lambda item: item[0].lower()):
                lines.append(f"- `{eng}` -> `{chn}`")
        else:
            lines.append("- 无术语命中")
        if missing:
            lines.append(f"- 疑似未收录专名：{', '.join(missing[:10])}")
        lines.append("")

    lines.append("## 疑似未收录专名")
    lines.append("")
    if missing_candidates:
        for term, pages in sorted(missing_candidates.items(), key=lambda item: item[0].lower())[:100]:
            page_text = _format_page_ranges([p - 1 for p in pages])
            lines.append(f"- `{term}`；页：{page_text}")
    else:
        lines.append("- 暂无。")
    lines.append("")
    return "\n".join(lines)


def write_glossary_report(pages_text: dict, glossary: dict, report_output: str, title: str = ""):
    ensure_output_parent(report_output)
    report = build_glossary_report(pages_text, glossary, title)
    with open(report_output, "w", encoding="utf-8") as f:
        f.write(report)
