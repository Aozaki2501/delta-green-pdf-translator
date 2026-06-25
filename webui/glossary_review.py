"""Helpers for pre-translation glossary review in the Web UI."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

ACTION_IGNORE = "忽略"
ACTION_ADD = "新增"
ACTION_UPDATE = "修改"
VALID_ACTIONS = {ACTION_IGNORE, ACTION_ADD, ACTION_UPDATE}


def _iter_review_rows(review_rows):
    if review_rows is None:
        return []
    if hasattr(review_rows, "to_dict"):
        return review_rows.to_dict("records")
    return review_rows


def glossary_candidates_to_review_rows(candidates, limit: int = 30) -> list[dict]:
    rows = []
    for candidate in list(candidates)[:limit]:
        pages = ", ".join(str(page + 1) for page in candidate.pages)
        rows.append(
            {
                "动作": ACTION_IGNORE,
                "中文译名": "",
                "英文原名": candidate.term,
                "出现次数": candidate.count,
                "位置": pages,
            }
        )
    return rows


def merge_reviewed_glossary(base_glossary: dict[str, str], review_rows: Iterable[dict]) -> dict[str, str]:
    merged = dict(base_glossary or {})
    for row in _iter_review_rows(review_rows):
        action = str(row.get("动作", ACTION_IGNORE) or ACTION_IGNORE).strip()
        english = str(row.get("英文原名", "") or "").strip()
        chinese = str(row.get("中文译名", "") or "").strip()

        if action not in VALID_ACTIONS:
            raise ValueError(f"术语动作无效：{action}")
        if action == ACTION_IGNORE:
            continue
        if not english:
            raise ValueError("术语英文原名不能为空。")
        if not chinese:
            raise ValueError(f"术语 {english} 的中文译名不能为空。")
        if "\t" in english or "\n" in english or "\t" in chinese or "\n" in chinese:
            raise ValueError(f"术语 {english} 含有制表符或换行，不能写入 TSV。")

        exists = english in merged
        if action == ACTION_ADD and exists:
            raise ValueError(f"术语 {english} 已存在；如需改名，请选择“修改”。")
        if action == ACTION_UPDATE and not exists:
            raise ValueError(f"术语 {english} 不存在；如需新增，请选择“新增”。")
        merged[english] = chinese
    return merged


def write_reviewed_glossary(
    base_glossary: dict[str, str],
    review_rows: Iterable[dict],
    output_path: str | Path,
) -> dict[str, str]:
    merged = merge_reviewed_glossary(base_glossary, review_rows)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for english, chinese in merged.items():
            f.write(f"{chinese}\t{english}\n")
    return merged
