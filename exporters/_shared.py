"""
Shared text-processing helpers used by multiple exporter modules.

Provides block splitting, cleaning, deduplication, pagination, and
text-length measurement utilities consumed by html.py, word.py, and
markdown.py exporters.

Dependencies: core.constants (for future use), core.utils (for future use)
"""

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Block splitting and cleaning
# ---------------------------------------------------------------------------

def _split_translation_chunks(text: str) -> list[str]:
    chunks = []
    normal_lines = []
    card_lines = []
    in_card = False

    def flush_normal():
        nonlocal normal_lines
        normal_text = "\n".join(normal_lines).strip()
        if normal_text:
            chunks.extend(part.strip() for part in re.split(r"\n\s*\n", normal_text) if part.strip())
        normal_lines = []

    def flush_card():
        nonlocal card_lines
        card_text = "\n".join(card_lines).strip()
        if card_text:
            chunks.append(card_text)
        card_lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "[CARD]":
            flush_normal()
            in_card = True
            card_lines = [raw_line]
            continue
        if line == "[/CARD]":
            card_lines.append(raw_line)
            flush_card()
            in_card = False
            continue
        if in_card:
            card_lines.append(raw_line)
        else:
            normal_lines.append(raw_line)

    if in_card:
        flush_card()
    else:
        flush_normal()
    return chunks


def _translation_blocks(translated_pages):
    blocks = []
    for page_num, translation in translated_pages:
        if not translation.strip():
            continue
        for chunk in _split_translation_chunks(translation):
            text = _clean_translated_block(chunk.strip())
            if not text or text == "---" or text.startswith("<!--"):
                continue
            blocks.append({"source_page": page_num, "text": text})
    return blocks


def _clean_translated_block(text: str) -> str:
    lines = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        line = _clean_decorative_slash_line(line)
        lines.append(line)

    lines = _merge_soft_wrapped_lines(lines)
    text = "\n".join(lines)
    text = _dedupe_adjacent_repeated_units(text)
    return text.strip()


def _is_structural_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped in ("[CARD]", "[/CARD]", "[[TOC]]"):
        return True
    if stripped.startswith(("#", "-", "\u2022", "|", ">", "```")):
        return True
    visible = re.sub(r"\s+", "", stripped)
    return len(visible) <= 10 and _is_plain_heading_line(stripped)


def _join_wrapped_text(left: str, right: str) -> str:
    if not left:
        return right
    if re.search(r"[\u4e00-\u9fff]$", left) or re.match(r"^[\u4e00-\u9fff，。！？；：、）】》”]", right):
        return left + right
    return left + " " + right


def _merge_soft_wrapped_lines(lines: list[str]) -> list[str]:
    merged = []
    current = ""

    def flush():
        nonlocal current
        if current:
            merged.append(current)
            current = ""

    for line in lines:
        if _is_structural_line(line):
            flush()
            merged.append(line)
            continue
        if not current:
            current = line
            continue
        current = _join_wrapped_text(current, line)

    flush()
    return merged


def _clean_decorative_slash_line(line: str) -> str:
    if line.count("//") < 2:
        return line

    parts = [p.strip(" /") for p in line.split("//") if p.strip(" /")]
    if not parts:
        return line

    unique_parts = []
    for part in parts:
        normalized = re.sub(r"\s+", "", part).lower()
        if unique_parts and normalized == re.sub(r"\s+", "", unique_parts[-1]).lower():
            continue
        unique_parts.append(part)

    if len(unique_parts) == len(parts):
        return line
    return "// " + " / ".join(unique_parts) + " //"


def _dedupe_adjacent_repeated_units(text: str) -> str:
    patterns = [
        r"([“\"][^”\"\n]{2,120}[”\"])(?:\s*[，,、]?\s*\1)+",
        r"(——[^—\n]{2,60})(?:\s+\1)+",
        r"([^。！？!?\n]{2,120}[。！？!?])(?:\s*\1)+",
    ]
    previous = None
    while previous != text:
        previous = text
        for pattern in patterns:
            text = re.sub(pattern, r"\1", text)
    return text


def _visible_text_length(text: str) -> int:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"^\[/?CARD\]\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"\s+", "", text)
    return len(text)


def _is_markdown_heading(text: str) -> bool:
    return bool(re.match(r"^#{1,6}\s+", text.strip()))


def _is_plain_heading_line(text: str) -> bool:
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", text.strip())
    clean = re.sub(r"\*(.+?)\*", r"\1", clean)
    if clean in ("[CARD]", "[/CARD]"):
        return False
    if clean.startswith(("#", "-", "\u2022", "//", "——", "“", "\"")):
        return False
    visible = re.sub(r"\s+", "", clean)
    if not (2 <= len(visible) <= 18):
        return False
    if re.search(r"[。！？!?；;：:，,、（）()《》\"“”]", clean):
        return False
    if re.search(r"\d", clean):
        return False
    return True


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


def _header_title(title: str) -> str:
    clean = re.sub(r"[_]+", " ", title).strip()
    if " - " in clean:
        clean = clean.split(" - ", 1)[1].strip()
    return clean[:32]


def paginate_translated_blocks(translated_pages, min_chars=1000, max_chars=1500,
                               page_layouts: Optional[dict] = None,
                               split_on_layout=False):
    """Group translated Markdown blocks into reading pages without splitting blocks."""
    pages = []
    current = []
    current_len = 0
    current_layout = None

    def flush():
        nonlocal current, current_len, current_layout
        if current:
            pages.append({
                "layout": current_layout or "columns",
                "blocks": current,
            })
            current = []
            current_len = 0
            current_layout = None

    for block in _translation_blocks(translated_pages):
        block_len = _visible_text_length(block["text"])
        starts_heading = _is_markdown_heading(block["text"])
        block_layout = "columns"
        if page_layouts:
            block_layout = page_layouts.get(block["source_page"], "columns")

        if split_on_layout and current and block_layout != current_layout:
            flush()

        if starts_heading and current and current_len >= min_chars:
            flush()
        elif current and current_len + block_len > max_chars and current_len >= min_chars:
            flush()

        if current_layout is None:
            current_layout = block_layout
        current.append(block)
        current_len += block_len

    flush()
    return pages
