"""
Helpers for editing glossary TSV content.

These functions are intentionally UI-free so both Streamlit and tests can use
the same validation rules.
"""

import re
from pathlib import Path


def read_glossary_editor_text(path: Path) -> str:
    if not path.exists():
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_glossary_editor_text(text: str) -> tuple[list[dict], list[str], list[str]]:
    rows = []
    errors = []
    warnings = []
    english_seen = {}
    chinese_seen = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            parts = line.split("\t", 1)
        else:
            parts = re.split(r"\s{2,}", line, maxsplit=1)
        if len(parts) != 2:
            errors.append(f"第 {line_number} 行没有分成两列")
            continue
        chinese = parts[0].strip()
        english = parts[1].strip()
        if not chinese or not english:
            errors.append(f"第 {line_number} 行有空字段")
            continue
        if "\ufffd" in chinese or "\ufffd" in english:
            errors.append(f"第 {line_number} 行疑似编码损坏")
        if "?" in chinese:
            errors.append(f"第 {line_number} 行中文列含问号，疑似编码损坏")
        english_key = english.lower()
        chinese_key = chinese
        if english_key in english_seen:
            errors.append(f"第 {line_number} 行英文原名重复：{english}")
        else:
            english_seen[english_key] = line_number
        if chinese_key in chinese_seen:
            warnings.append(f"第 {line_number} 行中文译名重复：{chinese}")
        else:
            chinese_seen[chinese_key] = line_number
        rows.append({"chinese": chinese, "english": english, "line": line_number})
    return rows, errors, warnings


def glossary_rows_to_tsv(rows: list[dict]) -> str:
    lines = [f"{row['chinese']}\t{row['english']}" for row in rows]
    return "\n".join(lines) + ("\n" if lines else "")
