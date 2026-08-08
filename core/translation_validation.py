"""
Validation for model output before it is persisted.

Prompt text must never be treated as translated content, and neither must an
elision placeholder standing in for text the model could not reconstruct. These
checks are signature-based and fail closed: callers retry or mark the unit as
failed.
"""

from __future__ import annotations

import re


_PRIMARY_PROMPT_SIGNATURES = (
    "You are a professional TRPG translator",
    "professional TRPG translator",
    "Translation rules",
    "Translate each block below",
    "Previous context - DO NOT translate",
    "Glossary (this section)",
    "Translate ONLY the text content",
    "Return one translated block for each source block",
    "Do not merge blocks, remove markers",
    "您是专业的TRPG翻译",
    "你是专业的TRPG翻译",
    "专业的TRPG翻译",
    "正在处理Delta Green原始资料",
    "翻译规则包括",
    "翻译规则如下",
    "我将根据这些规则翻译",
)

_SECONDARY_PROMPT_SIGNATURES = (
    "Follow the glossary strictly",
    "Keep untranslated",
    "Output in Markdown format",
    "Professional, fluent Chinese",
    "Maintain horror atmosphere",
    "Do not translate page headers",
    "Preserve Markdown tables",
    "Preserve blockquotes",
    "Preserve [BLOCK",
    "严格遵循术语表",
    "保留未翻译",
    "输出Markdown",
    "专业流畅中文",
    "保持恐怖氛围",
    "简明翻译",
    "不翻译页眉页脚",
    "保留标题层级",
    "推测OCR错误",
    "保持上下文",
    "保留Markdown表格",
    "表格、卡片等标记",
    "待翻译文本",
)


def _compact(text: str) -> str:
    return re.sub(r"[\W_]+", "", str(text or ""), flags=re.UNICODE).lower()


_PRIMARY_COMPACT = tuple(_compact(signature) for signature in _PRIMARY_PROMPT_SIGNATURES)
_SECONDARY_COMPACT = tuple(_compact(signature) for signature in _SECONDARY_PROMPT_SIGNATURES)


def contains_prompt_leak(text: str) -> bool:
    """Return True when text contains known internal prompt signatures."""
    compact_text = _compact(text)
    if not compact_text:
        return False
    if any(signature and signature in compact_text for signature in _PRIMARY_COMPACT):
        return True
    secondary_hits = sum(
        1 for signature in _SECONDARY_COMPACT
        if signature and signature in compact_text
    )
    return secondary_hits >= 2


def ensure_no_prompt_leak(text: str, label: str = "译文") -> None:
    """Raise when translated text contains internal prompt signatures."""
    if contains_prompt_leak(text):
        raise ValueError(f"{label}包含内部翻译指令")


_JAPANESE_KANA = re.compile(r"[\u3040-\u30ff]")


def contains_japanese_kana(text: str) -> bool:
    """Return True when purported Chinese output still contains Japanese kana."""
    return bool(_JAPANESE_KANA.search(str(text or "")))


def ensure_no_japanese_kana(text: str, label: str = "译文") -> None:
    """Reject output that was returned in Japanese instead of Chinese."""
    if contains_japanese_kana(text):
        raise ValueError(f"{label}包含日文假名，原文可能未翻译")


# A sentence split across two translation units cannot be reconstructed from
# either half alone, and the model fills the missing clause with an ellipsis
# placeholder instead of failing. Bracketed ASCII/CJK ellipses and "省略" notes
# cover every form observed in real output.
_ELISION_PLACEHOLDER = re.compile(
    r"[\[\(（【]\s*(?:\.{2,}|。{2,}|…+|省略[^\]\)）】]*)\s*[\]\)）】]"
)
_DAMAGED_PLACEHOLDER = re.compile(r"\[\s*damaged\s*\]", re.IGNORECASE)

# These are the only all-caps labels the translator is explicitly told to keep
# in English. Other labels introduce prose and must be translated rather than
# leaking into the Chinese output.
_PRESERVED_LEADING_LABELS = frozenset({
    "STR", "CON", "DEX", "INT", "POW", "CHA", "SAN", "WP", "HP",
    "FBI", "CIA", "MJ-12", "A-CELL",
})
_LEADING_ALL_CAPS_LABEL = re.compile(r"(?m)^\s*([A-Z][A-Z0-9 _-]*)\s*:")


def contains_elision_placeholder(text: str) -> bool:
    """Return True when text contains an elision placeholder such as ``[...]``."""
    return bool(_ELISION_PLACEHOLDER.search(str(text or "")))


def ensure_no_elision_placeholder(text: str, label: str = "译文") -> None:
    """Raise when translated text elides content it failed to reconstruct."""
    if contains_elision_placeholder(text):
        raise ValueError(f"{label}包含省略占位符，原文可能被切断")


def contains_damaged_placeholder(text: str) -> bool:
    """Return True when extraction or translation uses the ``[damaged]`` marker."""
    return bool(_DAMAGED_PLACEHOLDER.search(str(text or "")))


def ensure_no_damaged_placeholder(text: str, label: str = "译文") -> None:
    """Reject unresolved ``[damaged]`` text instead of accepting it as content."""
    if contains_damaged_placeholder(text):
        raise ValueError(f"{label}包含[damaged]损坏占位符，不能视为完成翻译")


def untranslated_leading_labels(source: str, translation: str) -> tuple[str, ...]:
    """Return source labels that were copied into Chinese output unchanged.

    The rule deliberately covers only the exact ``ALL CAPS:`` syntax used for
    prose labels. Game abbreviations have an explicit allowlist above; unknown
    labels fail closed so they can be translated or added to that allowlist.
    """
    source_labels = {
        match.group(1).strip()
        for match in _LEADING_ALL_CAPS_LABEL.finditer(str(source or ""))
    }
    translated_labels = {
        match.group(1).strip()
        for match in _LEADING_ALL_CAPS_LABEL.finditer(str(translation or ""))
    }
    return tuple(sorted(
        label
        for label in source_labels & translated_labels
        if label not in _PRESERVED_LEADING_LABELS
    ))


def ensure_no_untranslated_leading_labels(
    source: str,
    translation: str,
    label: str = "译文",
) -> None:
    """Raise when a prose label was copied into the Chinese translation."""
    labels = untranslated_leading_labels(source, translation)
    if labels:
        raise ValueError(f"{label}保留了未翻译标签：{', '.join(labels)}")
