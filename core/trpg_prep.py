"""TRPG prep checklist and structured extraction helpers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class PrepChecklistItem:
    category: str
    title: str
    page_num: int | None = None
    detail: str = ""


@dataclass
class ModuleEntity:
    name: str
    kind: str
    page_num: int
    excerpt: str = ""


@dataclass
class ModuleStructure:
    title: str = ""
    headings: list[ModuleEntity] = field(default_factory=list)
    stat_blocks: list[ModuleEntity] = field(default_factory=list)
    cards: list[ModuleEntity] = field(default_factory=list)
    rule_refs: list[ModuleEntity] = field(default_factory=list)
    prep_items: list[PrepChecklistItem] = field(default_factory=list)


def build_module_structure(
    pages_text: dict[int, str],
    translations: dict[int, str],
    *,
    quality_report=None,
    glossary_candidates=None,
    title: str = "",
) -> ModuleStructure:
    structure = ModuleStructure(title=title)
    for page_num in sorted(set(pages_text) | set(translations)):
        text = str(translations.get(page_num) or pages_text.get(page_num) or "")
        display_page = page_num + 1
        structure.headings.extend(_extract_headings(text, display_page))
        structure.stat_blocks.extend(_extract_marked_blocks(text, display_page, "STAT_BLOCK", "数据块"))
        structure.cards.extend(_extract_marked_blocks(text, display_page, "CARD", "卡片"))
        structure.rule_refs.extend(_extract_rule_refs(text, display_page))

    _append_quality_items(structure, quality_report)
    _append_glossary_items(structure, glossary_candidates)
    for entity in structure.stat_blocks:
        structure.prep_items.append(PrepChecklistItem(
            category="核对数据",
            title=f"核对 {entity.name}",
            page_num=entity.page_num,
            detail="确认属性、技能、攻击、护甲和损失值没有翻译错位。",
        ))
    for entity in structure.cards:
        structure.prep_items.append(PrepChecklistItem(
            category="准备材料",
            title=f"检查卡片：{entity.name}",
            page_num=entity.page_num,
            detail="判断是否需要作为玩家材料、线索卡或主持人备注单独整理。",
        ))
    for entity in structure.rule_refs:
        structure.prep_items.append(PrepChecklistItem(
            category="标记规则",
            title=entity.name,
            page_num=entity.page_num,
            detail=entity.excerpt,
        ))
    return structure


def render_prep_checklist_markdown(structure: ModuleStructure) -> str:
    title = structure.title or "模组"
    lines = [
        f"# {title} — 备团校对清单",
        "",
        "## 概览",
        "",
        f"- 标题数：{len(structure.headings)}",
        f"- 数据块：{len(structure.stat_blocks)}",
        f"- 卡片：{len(structure.cards)}",
        f"- 规则提示：{len(structure.rule_refs)}",
        f"- 待处理项：{len(structure.prep_items)}",
        "",
        "## 待处理",
        "",
    ]
    if not structure.prep_items:
        lines.append("- 暂无。")
    else:
        for item in structure.prep_items:
            page = f"第 {item.page_num} 页" if item.page_num else "无页码"
            detail = f"：{item.detail}" if item.detail else ""
            lines.append(f"- [{item.category}] {page}｜{item.title}{detail}")
    lines.append("")
    return "\n".join(lines)


def render_module_structure_markdown(structure: ModuleStructure) -> str:
    title = structure.title or "模组"
    lines = [
        f"# {title} — 结构化资料",
        "",
        "## 标题",
        "",
    ]
    _append_entity_lines(lines, structure.headings)
    lines.extend(["", "## 数据块", ""])
    _append_entity_lines(lines, structure.stat_blocks)
    lines.extend(["", "## 卡片", ""])
    _append_entity_lines(lines, structure.cards)
    lines.extend(["", "## 规则提示", ""])
    _append_entity_lines(lines, structure.rule_refs)
    lines.append("")
    return "\n".join(lines)


def write_prep_checklist(structure: ModuleStructure, output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(render_prep_checklist_markdown(structure))


def write_module_structure_markdown(structure: ModuleStructure, output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(render_module_structure_markdown(structure))


def write_module_structure_json(structure: ModuleStructure, output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(asdict(structure), f, ensure_ascii=False, indent=2)
        f.write("\n")


def _extract_headings(text: str, page_num: int) -> list[ModuleEntity]:
    rows = []
    for line in str(text or "").splitlines():
        clean = line.strip()
        match = re.match(r"^(#{1,4})\s+(.+)$", clean)
        if not match:
            continue
        name = _compact(match.group(2))
        if name:
            rows.append(ModuleEntity(name=name, kind="标题", page_num=page_num))
    return rows


def _extract_marked_blocks(text: str, page_num: int, marker: str, kind: str) -> list[ModuleEntity]:
    pattern = re.compile(rf"^\[{marker}\]\s*(.*?)^\[/{marker}\]", re.MULTILINE | re.DOTALL)
    rows = []
    for match in pattern.finditer(str(text or "")):
        body = match.group(1).strip()
        name = _first_content_line(body) or kind
        rows.append(ModuleEntity(
            name=name,
            kind=kind,
            page_num=page_num,
            excerpt=_excerpt(body),
        ))
    return rows


def _extract_rule_refs(text: str, page_num: int) -> list[ModuleEntity]:
    rows = []
    seen = set()
    pattern = re.compile(
        r"\b\d+d\d+\b|\b\d+D\d+\b|\bSAN\b|\bHP\b|\bWP\b|检定|技能|损失|roll|test",
        re.IGNORECASE,
    )
    for sentence in re.split(r"(?<=[。.!?！？])\s+|\n+", str(text or "")):
        clean = _compact(sentence)
        if not clean or not pattern.search(clean):
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(ModuleEntity(
            name="规则/检定提示",
            kind="规则",
            page_num=page_num,
            excerpt=_excerpt(clean, limit=180),
        ))
    return rows[:12]


def _append_quality_items(structure: ModuleStructure, quality_report) -> None:
    if not quality_report:
        return
    for issue in getattr(quality_report, "issues", []) or []:
        structure.prep_items.append(PrepChecklistItem(
            category="翻译复核",
            title=str(getattr(issue, "message", "") or "检查翻译问题"),
            page_num=int(getattr(issue, "page_num", 0) or 0) or None,
            detail=str(getattr(issue, "detail", "") or ""),
        ))


def _append_glossary_items(structure: ModuleStructure, glossary_candidates) -> None:
    for candidate in list(glossary_candidates or [])[:20]:
        pages = ", ".join(str(page + 1) for page in getattr(candidate, "pages", [])[:8])
        structure.prep_items.append(PrepChecklistItem(
            category="术语确认",
            title=str(getattr(candidate, "term", "") or ""),
            detail=f"出现 {getattr(candidate, 'count', 0)} 次；页码：{pages}",
        ))


def _append_entity_lines(lines: list[str], entities: list[ModuleEntity]) -> None:
    if not entities:
        lines.append("- 暂无。")
        return
    for entity in entities:
        excerpt = f"：{entity.excerpt}" if entity.excerpt else ""
        lines.append(f"- 第 {entity.page_num} 页｜{entity.name}{excerpt}")


def _first_content_line(text: str) -> str:
    for line in str(text or "").splitlines():
        clean = _compact(line)
        if clean:
            return clean[:80]
    return ""


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _excerpt(text: str, limit: int = 220) -> str:
    clean = _compact(text)
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "..."

