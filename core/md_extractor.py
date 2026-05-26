"""
Markdown text extraction and block splitting.

Parses a Markdown file into ordered translation units (blocks) for
the translation engine. Each block has a type, content, and metadata
needed to reassemble the translated output.

Dependencies: none (stdlib only)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ============================================================
# BLOCK DATA MODEL
# ============================================================

@dataclass
class MdBlock:
    """A single translation unit extracted from a Markdown file."""
    index: int
    block_type: str  # heading, paragraph, list_item, table, blockquote,
                     # code_block, front_matter, html_block, horizontal_rule,
                     # image_link, empty_line
    content: str           # Raw Markdown content (including syntax markers)
    text: str              # Translatable text (without syntax markers)
    translatable: bool     # Whether this block should be translated
    prefix: str = ""       # Structural prefix (e.g. "## ", "- ", "> ")
    indent: str = ""       # Leading whitespace for nested lists
    line_start: int = 0    # Starting line number in source file
    line_end: int = 0      # Ending line number in source file


# ============================================================
# MARKDOWN EXTRACTOR
# ============================================================

class MarkdownExtractor:
    """Parses a Markdown file into translation blocks."""

    # Patterns
    _HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$')
    _LIST_BULLET_RE = re.compile(r'^(\s*)([-*+])\s+(.+)$')
    _LIST_ORDERED_RE = re.compile(r'^(\s*)(\d+\.)\s+(.+)$')
    _BLOCKQUOTE_RE = re.compile(r'^(\s*>+\s?)(.*)')
    _HR_RE = re.compile(r'^(\s*)([-*_])\s*\2\s*\2[\s\2]*$')
    _CODE_FENCE_RE = re.compile(r'^(\s*)(```|~~~)(.*)$')
    _IMAGE_RE = re.compile(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$')
    _TABLE_SEP_RE = re.compile(r'^\|[\s:]*-+[\s:|-]*\|?\s*$')
    _TABLE_ROW_RE = re.compile(r'^\|(.+)\|?\s*$')
    _FRONT_MATTER_RE = re.compile(r'^---\s*$')
    _HTML_BLOCK_START_RE = re.compile(r'^<(div|table|pre|p|ul|ol|dl|fieldset|form|h[1-6]|hr|blockquote|address|article|aside|details|figcaption|figure|footer|header|hgroup|main|nav|section|summary)\b', re.IGNORECASE)

    def __init__(self, md_path: str):
        self.md_path = Path(md_path)
        self.blocks: list[MdBlock] = []
        self.total_lines = 0
        self._lines: list[str] = []

    def extract(self) -> list[MdBlock]:
        """Parse the file and return ordered blocks."""
        text = self.md_path.read_text(encoding="utf-8")
        self._lines = text.splitlines()
        self.total_lines = len(self._lines)
        self.blocks = []

        i = 0
        block_index = 0

        while i < self.total_lines:
            line = self._lines[i]

            # Empty line
            if not line.strip():
                self.blocks.append(MdBlock(
                    index=block_index, block_type="empty_line",
                    content=line, text="", translatable=False,
                    line_start=i, line_end=i,
                ))
                block_index += 1
                i += 1
                continue

            # Front matter (only at the very start)
            if i == 0 and self._FRONT_MATTER_RE.match(line):
                end = self._find_front_matter_end(i)
                content = "\n".join(self._lines[i:end + 1])
                self.blocks.append(MdBlock(
                    index=block_index, block_type="front_matter",
                    content=content, text="", translatable=False,
                    line_start=i, line_end=end,
                ))
                block_index += 1
                i = end + 1
                continue

            # Code fence
            m = self._CODE_FENCE_RE.match(line)
            if m:
                end = self._find_code_fence_end(i, m.group(2))
                content = "\n".join(self._lines[i:end + 1])
                self.blocks.append(MdBlock(
                    index=block_index, block_type="code_block",
                    content=content, text="", translatable=False,
                    line_start=i, line_end=end,
                ))
                block_index += 1
                i = end + 1
                continue

            # Horizontal rule
            if self._HR_RE.match(line):
                self.blocks.append(MdBlock(
                    index=block_index, block_type="horizontal_rule",
                    content=line, text="", translatable=False,
                    line_start=i, line_end=i,
                ))
                block_index += 1
                i += 1
                continue

            # Image link (standalone line)
            if self._IMAGE_RE.match(line):
                self.blocks.append(MdBlock(
                    index=block_index, block_type="image_link",
                    content=line, text="", translatable=False,
                    line_start=i, line_end=i,
                ))
                block_index += 1
                i += 1
                continue

            # Heading
            m = self._HEADING_RE.match(line)
            if m:
                prefix = m.group(1) + " "
                text = m.group(2).strip()
                self.blocks.append(MdBlock(
                    index=block_index, block_type="heading",
                    content=line, text=text, translatable=True,
                    prefix=prefix,
                    line_start=i, line_end=i,
                ))
                block_index += 1
                i += 1
                continue

            # Table (starts with | and has a separator row nearby)
            if self._TABLE_ROW_RE.match(line):
                end = self._find_table_end(i)
                if end > i:  # At least 2 lines for a valid table
                    content = "\n".join(self._lines[i:end + 1])
                    self.blocks.append(MdBlock(
                        index=block_index, block_type="table",
                        content=content, text=content, translatable=True,
                        line_start=i, line_end=end,
                    ))
                    block_index += 1
                    i = end + 1
                    continue

            # Blockquote
            m = self._BLOCKQUOTE_RE.match(line)
            if m:
                end = self._find_blockquote_end(i)
                lines = self._lines[i:end + 1]
                content = "\n".join(lines)
                # Extract text without > prefix
                text_lines = []
                for bq_line in lines:
                    bq_m = self._BLOCKQUOTE_RE.match(bq_line)
                    if bq_m:
                        text_lines.append(bq_m.group(2))
                    else:
                        text_lines.append(bq_line)
                text = "\n".join(text_lines)
                self.blocks.append(MdBlock(
                    index=block_index, block_type="blockquote",
                    content=content, text=text, translatable=True,
                    prefix="> ",
                    line_start=i, line_end=end,
                ))
                block_index += 1
                i = end + 1
                continue

            # List item (bullet or ordered)
            m = self._LIST_BULLET_RE.match(line) or self._LIST_ORDERED_RE.match(line)
            if m:
                indent = m.group(1)
                marker = m.group(2)
                text = m.group(3).strip()
                # Collect continuation lines
                end = i
                continuation_lines = [text]
                j = i + 1
                while j < self.total_lines:
                    next_line = self._lines[j]
                    # Continuation: indented further than marker, or empty line followed by indented
                    if next_line.strip() and not self._is_new_block_start(next_line, len(indent) + len(marker) + 1):
                        # Check if it's indented continuation
                        stripped = next_line.lstrip()
                        leading = len(next_line) - len(stripped)
                        if leading > len(indent):
                            continuation_lines.append(stripped)
                            end = j
                            j += 1
                            continue
                    break
                end = max(end, i)
                full_text = " ".join(continuation_lines)
                content = "\n".join(self._lines[i:end + 1])
                self.blocks.append(MdBlock(
                    index=block_index, block_type="list_item",
                    content=content, text=full_text, translatable=True,
                    prefix=f"{marker} ", indent=indent,
                    line_start=i, line_end=end,
                ))
                block_index += 1
                i = end + 1
                continue

            # HTML block
            if self._HTML_BLOCK_START_RE.match(line):
                end = self._find_html_block_end(i)
                content = "\n".join(self._lines[i:end + 1])
                # HTML tables with text content should be translatable
                has_text = self._html_block_has_translatable_text(content)
                self.blocks.append(MdBlock(
                    index=block_index, block_type="html_block",
                    content=content, text=content if has_text else "",
                    translatable=has_text,
                    line_start=i, line_end=end,
                ))
                block_index += 1
                i = end + 1
                continue

            # Paragraph (default: collect until empty line or new block type)
            end = self._find_paragraph_end(i)
            content = "\n".join(self._lines[i:end + 1])
            self.blocks.append(MdBlock(
                index=block_index, block_type="paragraph",
                content=content, text=content, translatable=True,
                line_start=i, line_end=end,
            ))
            block_index += 1
            i = end + 1

        return self.blocks

    def get_translatable_blocks(self) -> list[MdBlock]:
        """Return only blocks that need translation."""
        return [b for b in self.blocks if b.translatable]

    def get_context_text(self, block_index: int) -> str:
        """Get previous translated block's text for context window."""
        for i in range(block_index - 1, -1, -1):
            if self.blocks[i].translatable and self.blocks[i].text.strip():
                return self.blocks[i].text[:500]
        return ""

    # ----------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------

    def _is_new_block_start(self, line: str, min_indent: int = 0) -> bool:
        """Check if a line starts a new block type."""
        if not line.strip():
            return True
        if self._HEADING_RE.match(line):
            return True
        if self._HR_RE.match(line):
            return True
        if self._CODE_FENCE_RE.match(line):
            return True
        if self._IMAGE_RE.match(line):
            return True
        # New list item at same or less indentation
        m = self._LIST_BULLET_RE.match(line) or self._LIST_ORDERED_RE.match(line)
        if m and len(m.group(1)) < min_indent:
            return True
        return False

    def _find_front_matter_end(self, start: int) -> int:
        """Find closing --- of front matter."""
        for i in range(start + 1, self.total_lines):
            if self._FRONT_MATTER_RE.match(self._lines[i]):
                return i
        return self.total_lines - 1

    def _find_code_fence_end(self, start: int, fence: str) -> int:
        """Find matching closing code fence."""
        for i in range(start + 1, self.total_lines):
            if self._lines[i].strip().startswith(fence) and \
               len(self._lines[i].strip().rstrip('`~')) == 0 or \
               self._lines[i].strip() == fence:
                return i
        return self.total_lines - 1

    def _find_table_end(self, start: int) -> int:
        """Find end of a Markdown table."""
        i = start
        while i < self.total_lines and self._TABLE_ROW_RE.match(self._lines[i]):
            i += 1
        # Also accept separator rows
        while i < self.total_lines and (
            self._TABLE_ROW_RE.match(self._lines[i]) or
            self._TABLE_SEP_RE.match(self._lines[i])
        ):
            i += 1
        return i - 1 if i > start else start

    def _find_blockquote_end(self, start: int) -> int:
        """Find end of a blockquote section."""
        i = start + 1
        while i < self.total_lines:
            line = self._lines[i]
            if not line.strip():
                break
            if not self._BLOCKQUOTE_RE.match(line):
                break
            i += 1
        return i - 1

    def _find_html_block_end(self, start: int) -> int:
        """Find end of an HTML block."""
        # Simple: find closing tag or empty line
        tag_match = re.match(r'^<(\w+)', self._lines[start])
        if not tag_match:
            return start
        close_tag = f"</{tag_match.group(1)}"
        # Check if closing tag is on the same line
        if close_tag in self._lines[start].lower():
            return start
        for i in range(start + 1, self.total_lines):
            if close_tag in self._lines[i].lower():
                return i
            if not self._lines[i].strip():
                return i - 1
        return self.total_lines - 1

    @staticmethod
    def _html_block_has_translatable_text(content: str) -> bool:
        """Check if an HTML block contains meaningful text worth translating.

        Returns True for HTML tables/blocks that contain English prose
        (character sheets, stat blocks, descriptions, etc.)
        Returns False for purely structural/empty HTML.
        """
        # Strip all HTML tags to get just the text content
        text_only = re.sub(r'<[^>]+>', ' ', content)
        # Remove extra whitespace
        text_only = re.sub(r'\s+', ' ', text_only).strip()
        # If there's substantial text (more than just numbers/symbols), it's translatable
        # Count alphabetic characters as a proxy for English prose
        alpha_chars = sum(1 for c in text_only if c.isalpha())
        return alpha_chars > 30  # At least 30 letters = meaningful text
        return self.total_lines - 1

    def _find_paragraph_end(self, start: int) -> int:
        """Find end of a paragraph (until empty line or new block type)."""
        i = start + 1
        while i < self.total_lines:
            line = self._lines[i]
            if not line.strip():
                break
            if self._HEADING_RE.match(line):
                break
            if self._HR_RE.match(line):
                break
            if self._CODE_FENCE_RE.match(line):
                break
            if self._IMAGE_RE.match(line):
                break
            if self._TABLE_ROW_RE.match(line):
                break
            if self._LIST_BULLET_RE.match(line) or self._LIST_ORDERED_RE.match(line):
                break
            if self._BLOCKQUOTE_RE.match(line):
                break
            if self._HTML_BLOCK_START_RE.match(line):
                break
            i += 1
        return i - 1


# ============================================================
# BLOCK MERGING FOR API EFFICIENCY
# ============================================================

def merge_blocks_for_translation(blocks: list[MdBlock], max_chars: int = 3000) -> list[list[MdBlock]]:
    """
    Merge consecutive translatable paragraph/list blocks into groups
    for more efficient API calls.

    Rules:
    - headings are always sent alone (they define section boundaries)
    - tables are always sent alone (structure must be preserved exactly)
    - blockquotes are always sent alone
    - consecutive paragraphs and list items can be merged
    - merged group total chars <= max_chars
    """
    groups: list[list[MdBlock]] = []
    current_group: list[MdBlock] = []
    current_chars = 0

    for block in blocks:
        if not block.translatable:
            continue

        # These types always go alone
        if block.block_type in ("heading", "table", "blockquote", "html_block"):
            if current_group:
                groups.append(current_group)
                current_group = []
                current_chars = 0
            groups.append([block])
            continue

        # Mergeable types: paragraph, list_item
        block_chars = len(block.text)
        if current_group and current_chars + block_chars > max_chars:
            groups.append(current_group)
            current_group = []
            current_chars = 0

        current_group.append(block)
        current_chars += block_chars

    if current_group:
        groups.append(current_group)

    return groups
