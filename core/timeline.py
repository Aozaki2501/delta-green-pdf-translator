"""Timeline extraction helpers for TRPG modules."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class TimelineEvent:
    page_num: int
    marker: str
    event: str
    source_excerpt: str = ""


TIME_MARKER_RE = re.compile(
    r"\bD[-+]\d+\b|"
    r"\bDay\s+\d+\b|"
    r"\bNight\s+\d+\b|"
    r"\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\b|"
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b|"
    r"\b(?:midnight|noon|dawn|dusk|sunrise|sunset)\b|"
    r"第\s*(?:\d+|一|二|三|四|五|六|七|八|九|十|十一|十二)\s*天|"
    r"\d{1,2}\s*[:：]\s*\d{2}|"
    r"午夜|正午|黎明|黄昏|日出|日落|清晨|傍晚|深夜"
)


def build_timeline_events(pages_text: dict[int, str], translations: dict[int, str]) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for page_num in sorted(set(pages_text) | set(translations)):
        source = str(pages_text.get(page_num, "") or "")
        translation = str(translations.get(page_num, "") or "")
        text = translation or source
        display_page = page_num + 1
        for sentence in _split_sentences(text):
            marker = _first_marker(sentence)
            if not marker:
                continue
            events.append(TimelineEvent(
                page_num=display_page,
                marker=marker,
                event=_compact(sentence),
                source_excerpt=_excerpt(source),
            ))
    return _dedupe_events(events)


def render_timeline_markdown(events: list[TimelineEvent], title: str = "") -> str:
    heading = f"# {title} — 场景时间线" if title else "# 场景时间线"
    lines = [
        heading,
        "",
        f"- 事件数：{len(events)}",
        f"- 涉及页数：{len({event.page_num for event in events})}",
        "",
        "## 时间线",
        "",
    ]
    if not events:
        lines.append("- 暂无。")
    else:
        lines.extend(["| 页码 | 时间标记 | 事件 |", "| ---: | --- | --- |"])
        for event in events:
            lines.append(
                f"| {event.page_num} | {_escape_table(event.marker)} | {_escape_table(event.event)} |"
            )
    lines.append("")
    return "\n".join(lines)


def write_timeline_markdown(events: list[TimelineEvent], output_path: str, title: str = "") -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(render_timeline_markdown(events, title))


def write_timeline_json(events: list[TimelineEvent], output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([asdict(event) for event in events], f, ensure_ascii=False, indent=2)
        f.write("\n")


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。.!?！？])\s+|\n+", str(text or ""))
    return [_compact(part) for part in parts if _compact(part)]


def _first_marker(text: str) -> str:
    match = TIME_MARKER_RE.search(text or "")
    return match.group(0) if match else ""


def _dedupe_events(events: list[TimelineEvent]) -> list[TimelineEvent]:
    seen = set()
    result = []
    for event in events:
        key = (event.page_num, event.marker.lower(), event.event)
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    return result


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _excerpt(text: str, limit: int = 220) -> str:
    clean = _compact(text)
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "..."


def _escape_table(text: str) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")
