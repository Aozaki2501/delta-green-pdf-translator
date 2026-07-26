"""Rule symbol checks for TRPG translations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


ATTRIBUTES = ("STR", "CON", "DEX", "INT", "POW", "CHA", "SIZ", "APP", "EDU")
SECONDARY_STATS = ("SAN", "HP", "WP")
SKILL_WORDS = (
    "Accounting", "Alertness", "Anthropology", "Archaeology", "Art", "Athletics",
    "Bureaucracy", "Computer Science", "Criminology", "Disguise", "Dodge",
    "Drive", "Firearms", "First Aid", "Forensics", "Heavy Machinery", "History",
    "HUMINT", "Law", "Medicine", "Melee Weapons", "Navigate", "Occult",
    "Persuade", "Pharmacy", "Psychotherapy", "Ride", "Science", "Search",
    "SIGINT", "Stealth", "Surgery", "Survival", "Swim", "Unarmed Combat",
    "Unnatural",
)

# Numbers that carry game rules. Each pattern captures the digits that must
# survive translation; the surrounding English label is expected to be
# translated, so only the captured value is checked against the Chinese text.
RULE_VALUE_PATTERNS = (
    ("百分比", re.compile(r"(?<![\d.])(\d{1,3})\s*%")),
    ("伤害修正", re.compile(r"\d+\s*[dD]\s*\d+\s*[+\-]\s*(\d+)")),
    ("护甲", re.compile(r"\bArmou?r\b\s*:?\s*(\d+)", re.IGNORECASE)),
    ("致死率", re.compile(r"\bLethality\b\s*:?\s*(\d{1,3})", re.IGNORECASE)),
    (
        "射程",
        re.compile(
            r"(?<![\d.])(\d+)\s*(?:m|km|ft|yd|meters?|metres?|kilometers?|kilometres?|feet|yards?)(?![A-Za-z])",
            re.IGNORECASE,
        ),
    ),
    (
        "技能值",
        re.compile(
            r"\b(?:" + "|".join(re.escape(skill) for skill in SKILL_WORDS) + r")\b\s*:?\s*(\d{1,3})"
        ),
    ),
)


@dataclass
class RuleSymbolIssue:
    page_num: int
    kind: str
    symbol: str
    message: str
    source_excerpt: str = ""
    translation_excerpt: str = ""


def build_rule_symbol_issues(
    pages_text: dict[int, str],
    translations: dict[int, str],
) -> list[RuleSymbolIssue]:
    issues: list[RuleSymbolIssue] = []
    for page_num in sorted(set(pages_text) | set(translations)):
        source = str(pages_text.get(page_num, "") or "")
        translation = str(translations.get(page_num, "") or "")
        if not source or not translation:
            continue
        display_page = page_num + 1
        issues.extend(_missing_source_symbols(display_page, source, translation))
        issues.extend(_missing_rule_values(display_page, source, translation))
        issues.extend(_translated_abbreviation_issues(display_page, source, translation))
        issues.extend(_skill_name_residue_issues(display_page, source, translation))
    issues.sort(key=lambda item: (item.page_num, item.kind, item.symbol))
    return issues


def render_rule_symbol_report(issues: list[RuleSymbolIssue], title: str = "") -> str:
    heading = f"# {title} — 规则符号检查" if title else "# 规则符号检查"
    lines = [
        heading,
        "",
        f"- 问题数：{len(issues)}",
        f"- 涉及页数：{len({issue.page_num for issue in issues})}",
        "",
        "## 问题清单",
        "",
    ]
    if not issues:
        lines.append("- 暂无。")
    else:
        lines.extend(["| 页码 | 类型 | 符号 | 问题 |", "| ---: | --- | --- | --- |"])
        for issue in issues:
            lines.append(
                f"| {issue.page_num} | {issue.kind} | {_escape_table(issue.symbol)} | "
                f"{_escape_table(issue.message)} |"
            )
    lines.append("")
    return "\n".join(lines)


def write_rule_symbol_report(issues: list[RuleSymbolIssue], output_path: str, title: str = "") -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(render_rule_symbol_report(issues, title))


def _missing_source_symbols(page_num: int, source: str, translation: str) -> list[RuleSymbolIssue]:
    issues = []
    for kind, symbols in _source_symbols(source).items():
        for symbol in sorted(symbols):
            if _symbol_present(symbol, translation):
                continue
            issues.append(RuleSymbolIssue(
                page_num=page_num,
                kind=kind,
                symbol=symbol,
                message="原文有该规则符号，译文未保留。",
                source_excerpt=_excerpt_around(source, symbol),
                translation_excerpt=_excerpt(translation),
            ))
    return issues


def _missing_rule_values(page_num: int, source: str, translation: str) -> list[RuleSymbolIssue]:
    """Check that rule numbers (skill %, damage, armor, lethality, range) survive.

    Only the number is checked: labels like "Armor" or "Lethality" are supposed
    to be translated, but a Chinese rules text that changes or drops the value
    itself is a mistranslation the character-ratio check cannot see.
    """
    issues = []
    normalized_source = re.sub(r"\s+", " ", source)
    seen: set[tuple[str, str]] = set()
    for kind, pattern in RULE_VALUE_PATTERNS:
        for match in pattern.finditer(normalized_source):
            value = match.group(1)
            if (kind, value) in seen:
                continue
            seen.add((kind, value))
            if re.search(rf"(?<!\d){re.escape(value)}(?!\d)", translation):
                continue
            issues.append(RuleSymbolIssue(
                page_num=page_num,
                kind=kind,
                symbol=match.group(0).strip(),
                message=f"原文规则数值 {value} 在译文中找不到，需人工核对。",
                source_excerpt=_excerpt_around(source, match.group(0).strip()),
                translation_excerpt=_excerpt(translation),
            ))
    return issues


def _translated_abbreviation_issues(page_num: int, source: str, translation: str) -> list[RuleSymbolIssue]:
    issues = []
    source_upper = source.upper()
    checks = [
        ("SAN", ("理智", "理智值")),
        ("HP", ("生命值", "生命")),
        ("WP", ("意志力", "意志点")),
        ("STR", ("力量",)),
        ("CON", ("体质",)),
        ("DEX", ("敏捷",)),
        ("INT", ("智力",)),
        ("POW", ("意志",)),
        ("CHA", ("魅力",)),
    ]
    for symbol, chinese_words in checks:
        if symbol not in source_upper:
            continue
        if _symbol_present(symbol, translation):
            continue
        for word in chinese_words:
            if word in translation:
                issues.append(RuleSymbolIssue(
                    page_num=page_num,
                    kind="缩写翻译",
                    symbol=symbol,
                    message=f"疑似把 {symbol} 翻成“{word}”，应保留英文缩写。",
                    source_excerpt=_excerpt_around(source, symbol),
                    translation_excerpt=_excerpt_around(translation, word),
                ))
                break
    return issues


def _skill_name_residue_issues(page_num: int, source: str, translation: str) -> list[RuleSymbolIssue]:
    issues = []
    for skill in SKILL_WORDS:
        if not re.search(rf"(?<![A-Za-z]){re.escape(skill)}(?![A-Za-z])", source):
            continue
        if not re.search(rf"(?<![A-Za-z]){re.escape(skill)}(?![A-Za-z])", translation):
            continue
        issues.append(RuleSymbolIssue(
            page_num=page_num,
            kind="技能残留",
            symbol=skill,
            message="技能名仍是英文，需人工确认是否应翻译。",
            source_excerpt=_excerpt_around(source, skill),
            translation_excerpt=_excerpt_around(translation, skill),
        ))
    return issues


def _source_symbols(text: str) -> dict[str, set[str]]:
    symbols = {
        "骰子": set(re.findall(r"\b\d+[dD]\d+\b", text)),
        "损失": set(re.findall(r"\b\d+/\d+[dD]\d+\s+SAN\b", text, flags=re.IGNORECASE)),
        "属性": set(re.findall(r"\b(?:" + "|".join(ATTRIBUTES) + r")\b", text)),
        "数值": set(re.findall(r"\b(?:" + "|".join(SECONDARY_STATS) + r")\b", text)),
    }
    return {kind: values for kind, values in symbols.items() if values}


def _symbol_present(symbol: str, text: str) -> bool:
    if re.fullmatch(r"\d+[dD]\d+", symbol) or re.fullmatch(r"\d+/\d+[dD]\d+\s+SAN", symbol, re.IGNORECASE):
        return re.search(rf"\b{re.escape(symbol)}\b", text, flags=re.IGNORECASE) is not None
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9])", text) is not None


def _excerpt_around(text: str, needle: str, limit: int = 160) -> str:
    source = str(text or "")
    pos = source.lower().find(str(needle).lower())
    if pos < 0:
        return _excerpt(source, limit)
    start = max(0, pos - limit // 2)
    end = min(len(source), pos + len(needle) + limit // 2)
    return _excerpt(source[start:end], limit)


def _excerpt(text: str, limit: int = 160) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "..."


def _escape_table(text: str) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")
