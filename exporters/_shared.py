"""
Shared text-processing helpers used by multiple exporter modules.

Provides block splitting, cleaning, deduplication, pagination, and
text-length measurement utilities consumed by html.py, word.py, and
markdown.py exporters.

Dependencies: core.constants (for future use), core.utils (for future use)
"""

import re
from typing import Optional

SINGLE_COLUMN_LAYOUTS = {
    "single",
    "handout",
    "toc",
    "character",
    "document",
    "credits",
    "art",
}

MARKER_ALIASES = {
    "[卡片]": "[CARD]",
    "[/卡片]": "[/CARD]",
    "[属性块]": "[STAT_BLOCK]",
    "[/属性块]": "[/STAT_BLOCK]",
    "[图片]": "[IMAGE]",
    "[/图片]": "[/IMAGE]",
    "[整页标题]": "[FULL_WIDTH_TITLE]",
    "[/整页标题]": "[/FULL_WIDTH_TITLE]",
}

LIST_MARKER_RE = re.compile(r"^(?:[-\u2022•]\s+|(?:»\s*){1,3})(.+)$")


# ---------------------------------------------------------------------------
# Block splitting and cleaning
# ---------------------------------------------------------------------------

def _layout_uses_columns(layout: str) -> bool:
    return (layout or "columns") not in SINGLE_COLUMN_LAYOUTS


def _normalize_heading_markup(line: str) -> str:
    stripped = line.strip()
    match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
    if not match:
        return line
    prefix, title = match.groups()
    title = re.sub(r"\s*#{1,6}\s*", " ", title)
    title = re.sub(r"\*\*(.+?)\*\*", r"\1", title)
    title = re.sub(r"\*(.+?)\*", r"\1", title)
    title = re.sub(r"\s+", " ", title).strip()
    return f"{prefix} {title}" if title else stripped


def _normalize_marker_line(line: str) -> str:
    stripped = line.strip()
    return MARKER_ALIASES.get(stripped, stripped)


def _strip_list_marker(line: str) -> Optional[str]:
    stripped = line.strip()
    match = LIST_MARKER_RE.match(stripped)
    if not match:
        return None
    item = re.sub(r"\s+", " ", match.group(1)).strip()
    return item or None


def _strip_quote_prefix(line: str) -> str:
    return re.sub(r"^(?:>\s*)+", "", line.strip())


def _looks_like_markdown_table_row(line: str) -> bool:
    stripped = _strip_quote_prefix(line).strip()
    if "|" not in stripped:
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if len(cells) < 2:
        return False
    return any(cell for cell in cells)


def _is_markdown_table_separator_row(line: str) -> bool:
    stripped = _strip_quote_prefix(line).strip()
    if "|" not in stripped:
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)

def _split_translation_chunks(text: str) -> list[str]:
    chunks = []
    normal_lines = []
    card_lines = []
    stat_lines = []
    image_lines = []
    full_title_lines = []
    in_card = False
    in_stat = False
    in_image = False
    in_full_title = False

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

    def flush_stat():
        nonlocal stat_lines
        stat_text = "\n".join(stat_lines).strip()
        if stat_text:
            chunks.append(stat_text)
        stat_lines = []

    def flush_image():
        nonlocal image_lines
        image_text = "\n".join(image_lines).strip()
        if image_text:
            chunks.append(image_text)
        image_lines = []

    def flush_full_title():
        nonlocal full_title_lines
        title_text = "\n".join(full_title_lines).strip()
        if title_text:
            chunks.append(title_text)
        full_title_lines = []

    for raw_line in text.splitlines():
        line = _normalize_marker_line(raw_line)
        raw_line = line if line != raw_line.strip() else raw_line
        if line == "[FULL_WIDTH_TITLE]":
            flush_normal()
            flush_card()
            flush_stat()
            flush_image()
            in_full_title = True
            full_title_lines = [raw_line]
            continue
        if line == "[/FULL_WIDTH_TITLE]":
            full_title_lines.append(raw_line)
            flush_full_title()
            in_full_title = False
            continue
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
        if line == "[STAT_BLOCK]":
            flush_normal()
            in_stat = True
            stat_lines = [raw_line]
            continue
        if line == "[/STAT_BLOCK]":
            stat_lines.append(raw_line)
            flush_stat()
            in_stat = False
            continue
        if line == "[IMAGE]":
            flush_normal()
            in_image = True
            image_lines = [raw_line]
            continue
        if line == "[/IMAGE]":
            image_lines.append(raw_line)
            flush_image()
            in_image = False
            continue
        if in_full_title:
            full_title_lines.append(raw_line)
            continue
        if in_card:
            card_lines.append(raw_line)
        elif in_stat:
            stat_lines.append(raw_line)
        elif in_image:
            image_lines.append(raw_line)
        else:
            normal_lines.append(raw_line)

    if in_full_title:
        flush_full_title()
    elif in_card:
        flush_card()
    elif in_stat:
        flush_stat()
    elif in_image:
        flush_image()
    else:
        flush_normal()
    return chunks


def _translation_blocks(translated_pages):
    blocks = []
    for page_num, translation in _stitch_translated_page_continuations(translated_pages):
        if not translation.strip():
            continue
        for chunk in _split_translation_chunks(translation):
            text = _clean_translated_block(chunk.strip())
            if not text or text == "---" or text.startswith("<!--"):
                continue
            blocks.append({"source_page": page_num, "text": text})
    return blocks


def _text_ends_sentence(text: str) -> bool:
    return bool(re.search(r"[。！？!?；;：:」』”）)\]]\s*$", text.strip()))


def _trailing_incomplete_fragment(text: str) -> Optional[str]:
    stripped = text.rstrip()
    if not stripped:
        return None
    parts = [part.strip() for part in re.split(r"\n\s*\n", stripped) if part.strip()]
    if not parts:
        return None
    tail = parts[-1]
    normalized_tail = _normalize_marker_line(tail)
    sentence_marks = list(re.finditer(r"[。！？!?；;：:」』”）)\]]", normalized_tail))
    if sentence_marks and sentence_marks[-1].end() < len(normalized_tail):
        tail = tail[sentence_marks[-1].end():].strip()
        normalized_tail = _normalize_marker_line(tail)
    visible = re.sub(r"\s+", "", normalized_tail)
    if not re.search(r"[\u4e00-\u9fff]", normalized_tail):
        return None
    if _text_ends_sentence(normalized_tail):
        return None
    if _is_structural_line(normalized_tail):
        return None
    if not (2 <= len(visible) <= 24):
        return None
    return tail


def _remove_trailing_fragment(text: str, fragment: str) -> str:
    pattern = re.escape(fragment) + r"\s*$"
    return re.sub(pattern, "", text.rstrip()).rstrip()


def _is_structural_chunk(text: str) -> bool:
    stripped = _normalize_marker_line(text.strip())
    return (
        stripped.startswith(("[CARD]", "[STAT_BLOCK]", "[IMAGE]", "[FULL_WIDTH_TITLE]", "[[TOC]]", "|"))
        or _is_markdown_heading(stripped)
    )


def _merge_page_sentence_fragment(left: str, right: str) -> str:
    left = left.strip()
    right = right.lstrip()
    for pronoun in ("他们", "她们", "它们", "他", "她", "它"):
        if left.endswith(("并不", "并未", "并没有")) and right.startswith(pronoun + "不"):
            return left + right[len(pronoun) + 1:]
        if left.endswith(("并不", "并未", "并没有")) and right.startswith(pronoun):
            return left + right[len(pronoun):]
    return _join_wrapped_text(left, right)


def _prepend_fragment_to_chunk(fragment: str, chunk: str) -> str:
    parts = re.split(r"\n\s*\n", chunk.strip(), maxsplit=1)
    first = _merge_page_sentence_fragment(fragment, parts[0])
    if len(parts) == 1:
        return first
    return first + "\n\n" + parts[1].strip()


def _apply_pending_continuation(fragment: str, text: str) -> str:
    chunks = _split_translation_chunks(text)
    if not chunks:
        return fragment + "\n\n" + text
    target_idx = next(
        (idx for idx, chunk in enumerate(chunks) if not _is_structural_chunk(chunk)),
        None,
    )
    if target_idx is None:
        return fragment + "\n\n" + text
    chunks[target_idx] = _prepend_fragment_to_chunk(fragment, chunks[target_idx])
    if target_idx > 0:
        target = chunks.pop(target_idx)
        chunks.insert(0, target)
    return "\n\n".join(chunk.strip() for chunk in chunks if chunk.strip())


def _stitch_translated_page_continuations(translated_pages):
    stitched = []
    pending = None
    for page_num, translation in translated_pages:
        text = str(translation)
        if pending:
            text = _apply_pending_continuation(pending, text)
            pending = None
        tail = _trailing_incomplete_fragment(text)
        if tail:
            text = _remove_trailing_fragment(text, tail)
            pending = tail
        stitched.append((page_num, text))
    if pending and stitched:
        last_page, last_text = stitched[-1]
        stitched[-1] = (last_page, (last_text.rstrip() + "\n\n" + pending).strip())
    return stitched


def _card_content_looks_like_list(lines: list[str]) -> bool:
    content = [line for line in lines if line.strip()]
    if len(content) >= 3 and content[0].lstrip().startswith(">>"):
        return True
    if any(_strip_list_marker(line) for line in content[1:]):
        return True
    if len(content) < 5:
        return False
    short_lines = [
        line for line in content
        if len(re.sub(r"\s+", "", line)) <= 24 and not _text_ends_sentence(line)
    ]
    return len(short_lines) >= len(content) * 0.65


def _clean_translated_block(text: str) -> str:
    lines = []
    for raw_line in text.split("\n"):
        line = _normalize_marker_line(raw_line)
        if not line:
            continue
        line = _clean_decorative_slash_line(line)
        lines.append(line)

    if lines and lines[0] in ("[STAT_BLOCK]", "[IMAGE]", "[FULL_WIDTH_TITLE]"):
        return "\n".join(lines).strip()

    if lines and lines[0] == "[CARD]":
        end_marker = "[/CARD]" if lines[-1] == "[/CARD]" else ""
        content = lines[1:-1] if end_marker else lines[1:]
        if content:
            if _card_content_looks_like_list(content):
                merged_content = content
            else:
                merged_content = [content[0]]
                merged_content.extend(_merge_soft_wrapped_lines(content[1:]))
            result = ["[CARD]"] + merged_content
            if end_marker:
                result.append(end_marker)
            return "\n".join(result).strip()
        return "\n".join(lines).strip()

    lines = _merge_soft_wrapped_lines(lines)
    text = "\n".join(lines)
    text = _dedupe_adjacent_repeated_units(text)
    return text.strip()


def _is_structural_line(line: str) -> bool:
    stripped = _normalize_marker_line(line)
    if not stripped:
        return True
    if stripped in (
        "[CARD]", "[/CARD]",
        "[STAT_BLOCK]", "[/STAT_BLOCK]",
        "[IMAGE]", "[/IMAGE]",
        "[FULL_WIDTH_TITLE]", "[/FULL_WIDTH_TITLE]",
        "[[TOC]]",
    ):
        return True
    if stripped.startswith(("#", "-", "\u2022", "|", ">", "```")):
        return True
    if _strip_list_marker(stripped):
        return True
    if _is_soft_subheading_line(stripped):
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
    text = re.sub(r"^\[/?STAT_BLOCK\]\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\[/?IMAGE\]\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\[/?FULL_WIDTH_TITLE\]\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"\s+", "", text)
    return len(text)


def _is_markdown_heading(text: str) -> bool:
    return bool(re.match(r"^#{1,6}\s+", text.strip()))


def _is_full_width_title_block(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("[FULL_WIDTH_TITLE]") and "[/FULL_WIDTH_TITLE]" in stripped


def _is_plain_heading_line(text: str) -> bool:
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", text.strip())
    clean = re.sub(r"\*(.+?)\*", r"\1", clean)
    clean = _normalize_marker_line(clean)
    if clean in (
        "[CARD]", "[/CARD]",
        "[STAT_BLOCK]", "[/STAT_BLOCK]",
        "[IMAGE]", "[/IMAGE]",
        "[FULL_WIDTH_TITLE]", "[/FULL_WIDTH_TITLE]",
    ):
        return False
    if clean.startswith(("#", "-", "\u2022", "//", "——", "“", "\"")):
        return False
    visible = re.sub(r"\s+", "", clean)
    if not (4 <= len(visible) <= 18):
        return False
    if re.search(r"[\u4e00-\u9fff]", clean):
        return False
    if re.search(r"[。！？!?；;：:，,、（）()《》\"“”]", clean):
        return False
    if re.search(r"\d", clean):
        return False
    return True


def _is_soft_subheading_line(text: str) -> bool:
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", text.strip())
    clean = re.sub(r"\*(.+?)\*", r"\1", clean)
    clean = _normalize_marker_line(clean)
    if not re.search(r"[\u4e00-\u9fff]", clean):
        return False
    if _strip_list_marker(clean):
        return False
    if clean.startswith(("[", "#", "|", ">", "`")):
        return False
    visible = re.sub(r"\s+", "", clean)
    if not (5 <= len(visible) <= 28):
        return False
    if re.search(r"[。；：，、（）【】《》\"“”]$", clean):
        return False
    return clean.endswith(("？", "?", "：", ":"))


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
    clean = re.sub(
        r"\b(?:upload|z-library(?:\.[a-z]+)?|1lib(?:\.[a-z]+)?|z-lib(?:\.[a-z]+)?|full proof \d+)\b",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\bcn\b$", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\b[a-f0-9]{8,}\b", "", clean, flags=re.IGNORECASE)
    if " - " in clean:
        clean = clean.split(" - ", 1)[1].strip()
    if not re.search(r"[\u4e00-\u9fff]", clean):
        parts = [part.strip() for part in re.split(r"[.·]", clean) if part.strip()]
        if parts:
            clean = parts[0]
    clean = re.sub(r"\s+", " ", clean).strip(" ._-")
    return clean[:32]


def _heading_text_from_block(text: str) -> Optional[str]:
    stripped = text.strip()
    if _is_full_width_title_block(stripped):
        inner = re.sub(r"^\[FULL_WIDTH_TITLE\]\s*", "", stripped)
        inner = re.sub(r"\s*\[/FULL_WIDTH_TITLE\]$", "", inner)
        first_line = next((line.strip() for line in inner.splitlines() if line.strip()), "")
        return re.sub(r"^#{1,6}\s*", "", first_line).strip() or None

    first_line = next((line.strip() for line in stripped.splitlines() if line.strip()), "")
    if re.match(r"^#{1,3}\s+", first_line):
        return re.sub(r"^#{1,3}\s*", "", first_line).strip() or None
    return None


def _primary_title_from_reading_pages(reading_pages) -> Optional[str]:
    for page in reading_pages:
        for block in page.get("blocks", []):
            stripped = (block.get("text") or "").strip()
            if not stripped:
                continue
            if _is_full_width_title_block(stripped):
                inner = re.sub(r"^\[FULL_WIDTH_TITLE\]\s*", "", stripped)
                inner = re.sub(r"\s*\[/FULL_WIDTH_TITLE\]$", "", inner)
                first_line = next((line.strip() for line in inner.splitlines() if line.strip()), "")
                title = re.sub(r"^#{1,6}\s*", "", first_line).strip()
                if title:
                    return title
            first_line = next((line.strip() for line in stripped.splitlines() if line.strip()), "")
            if re.match(r"^#\s+", first_line):
                return re.sub(r"^#\s*", "", first_line).strip() or None
    return None


def _display_title(title: str, reading_pages) -> str:
    primary = _primary_title_from_reading_pages(reading_pages)
    if primary:
        return primary
    if re.search(r"[\u4e00-\u9fff]", title):
        return title.strip()
    return _header_title(title) or title.strip()


def _looks_like_stat_block(text: str) -> bool:
    upper = text.upper()
    attributes = ("STR", "CON", "DEX", "INT", "POW", "CHA")
    attr_number_hits = sum(1 for attr in attributes if re.search(rf"\b{attr}\s*\d+", upper))
    has_secondary_stats = bool(re.search(r"\b(?:HP|WP|SAN)\s*\d+", upper))
    has_game_sections = bool(re.search(r"(?:SKILLS|ATTACKS|ARMOR|DISORDER|技能|攻击|护甲|障碍)\s*[：:]", text, re.IGNORECASE))
    return (
        attr_number_hits >= 4
        or (attr_number_hits >= 2 and has_secondary_stats)
        or (attr_number_hits >= 1 and has_game_sections)
    )


def attach_running_headers(reading_pages, fallback_title: str):
    current = _display_title(fallback_title, reading_pages)
    for page in reading_pages:
        for block in page.get("blocks", []):
            heading = _heading_text_from_block(block.get("text", ""))
            if heading:
                current = heading[:48]
                break
        page["running_header"] = current
    return reading_pages


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

        if _is_full_width_title_block(block["text"]) and current:
            flush()
        elif starts_heading and current and current_len >= min_chars:
            flush()
        elif current and current_len + block_len > max_chars and current_len >= min_chars:
            flush()

        if current_layout is None:
            current_layout = block_layout
        current.append(block)
        current_len += block_len

    flush()
    return pages
