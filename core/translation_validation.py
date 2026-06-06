"""
Validation for model output before it is persisted.

Prompt text must never be treated as translated content. These checks are
signature-based and fail closed: callers retry or mark the unit as failed.
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
