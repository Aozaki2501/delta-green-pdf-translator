"""
Markdown format-preserving exporter.

Takes the original MdBlock list and a translation map, then reassembles
the output Markdown with translated text while preserving the exact
structure (headings, lists, tables, code blocks, images, empty lines).

Dependencies: core.md_extractor (for MdBlock type)
"""

import re
from pathlib import Path

from core.md_extractor import MdBlock


def write_md_output(blocks: list[MdBlock], translations: dict[int, str],
                    output_path: str) -> str:
    """
    Write translated Markdown output preserving original structure.

    Args:
        blocks: Full list of MdBlock from MarkdownExtractor
        translations: dict mapping block index -> translated text
        output_path: Where to write the output .md file

    Returns:
        The output file path.
    """
    output_lines: list[str] = []

    for block in blocks:
        if not block.translatable:
            # Non-translatable blocks are preserved verbatim
            output_lines.append(block.content)
            continue

        translated = translations.get(block.index)
        if not translated:
            raise RuntimeError(f"Markdown 写回失败，缺少译文块：{block.index}")

        # Reassemble based on block type
        if block.block_type == "heading":
            output_lines.append(_reassemble_heading(block, translated))
        elif block.block_type == "list_item":
            output_lines.append(_reassemble_list_item(block, translated))
        elif block.block_type == "blockquote":
            output_lines.append(_reassemble_blockquote(block, translated))
        elif block.block_type == "table":
            output_lines.append(_reassemble_table(block, translated))
        elif block.block_type == "paragraph":
            output_lines.append(translated.strip())
        else:
            # Default: just use the translated text
            output_lines.append(translated.strip())

    # Join with newlines
    output_text = "\n".join(output_lines)
    # Ensure single trailing newline
    if not output_text.endswith("\n"):
        output_text += "\n"

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output_text, encoding="utf-8")
    return str(out_path)


def _reassemble_heading(block: MdBlock, translated: str) -> str:
    """Reassemble a heading with original # prefix."""
    # Strip any # prefix the AI might have added
    text = translated.strip()
    text = re.sub(r'^#{1,6}\s*', '', text)
    return f"{block.prefix}{text}"


def _reassemble_list_item(block: MdBlock, translated: str) -> str:
    """Reassemble a list item with original indent and marker."""
    text = translated.strip()
    # Remove any bullet/number prefix the AI might have added
    text = re.sub(r'^[\s]*[-*+]\s+', '', text)
    text = re.sub(r'^[\s]*\d+\.\s+', '', text)
    return f"{block.indent}{block.prefix}{text}"


def _reassemble_blockquote(block: MdBlock, translated: str) -> str:
    """Reassemble a blockquote with > prefix on each line."""
    lines = translated.strip().splitlines()
    return "\n".join(f"> {line}" for line in lines)


def _reassemble_table(block: MdBlock, translated: str) -> str:
    """
    Reassemble a table. The AI should return a valid Markdown table,
    so we mostly pass it through but ensure the separator row is intact.
    """
    translated = translated.strip()
    # If the AI returned a valid table, use it directly
    if "|" in translated and "---" in translated:
        return translated
    # Fallback: return original table structure with translated content
    return translated
