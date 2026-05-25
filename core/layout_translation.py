"""
Translation helpers for coordinate-level layout JSON.

These functions do not call an AI service. They provide the strict data path:
export block text, apply translated text by block ID, and report overflow.
"""

from dataclasses import dataclass
import html
import json
import os
from pathlib import Path
import re
import tempfile
import time

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        raise ImportError("PyMuPDF not installed. Run: pip install pymupdf")

from core.layout_model import (
    LayoutDocument,
    LayoutPage,
    LayoutTextBlock,
    layout_document_from_json,
)
from core.utils import ensure_output_parent
from core.constants import TRANSLATION_FAILURE_PREFIX


@dataclass(frozen=True)
class LayoutFitIssue:
    page: int
    block_id: str
    width: float
    height: float
    text_length: int


class LayoutTranslationProgress:
    """Progress file for block-level replica layout translation."""

    def __init__(self, progress_file: str):
        if not progress_file:
            raise ValueError("progress_file 不能为空")
        self.progress_file = progress_file
        self.translations: dict[str, str] = {}
        self.failed_blocks: dict[str, str] = {}
        self.translation_cache: dict[str, str] = {}
        self._load()

    def _load(self):
        progress_path = Path(self.progress_file)
        candidates = []
        if progress_path.exists():
            candidates.append(progress_path)
        candidates.extend(sorted(
            progress_path.parent.glob(progress_path.name + ".*.tmp"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        ))
        if not candidates:
            return

        loaded = []
        for path in candidates:
            try:
                data = _read_progress_data(path)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            loaded.append(data)
        if not loaded:
            return
        data = max(loaded, key=_progress_data_score)
        self.translations = dict(data.get("translations") or {})
        self.failed_blocks = dict(data.get("failed_blocks") or {})
        self.translation_cache = dict(data.get("translation_cache") or {})

    def save(self):
        data = {
            "schema": 1,
            "translations": self.translations,
            "failed_blocks": self.failed_blocks,
            "translation_cache": self.translation_cache,
        }
        progress_path = Path(self.progress_file)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(progress_path.parent),
            prefix=progress_path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_path = Path(f.name)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        _replace_with_retry(tmp_path, progress_path)

    def is_completed(self, block_id: str) -> bool:
        return block_id in self.translations

    def get_translation(self, block_id: str) -> str:
        return self.translations.get(block_id, "")

    def mark_completed(self, block_id: str, translation: str):
        if not block_id:
            raise ValueError("block_id 不能为空")
        if not translation:
            raise ValueError(f"译文为空：{block_id}")
        self.translations[block_id] = translation
        self.failed_blocks.pop(block_id, None)
        self.save()

    def mark_failed(self, block_id: str, message: str):
        if not block_id:
            raise ValueError("block_id 不能为空")
        self.translations.pop(block_id, None)
        self.failed_blocks[block_id] = str(message or "translation failed")
        self.save()

    def get_failed_blocks(self) -> set[str]:
        return set(self.failed_blocks)

    def clear_failed_blocks(self, block_ids=None) -> int:
        block_filter = None if block_ids is None else set(block_ids)
        cleared = 0
        for block_id in list(self.failed_blocks):
            if block_filter is not None and block_id not in block_filter:
                continue
            self.failed_blocks.pop(block_id, None)
            cleared += 1
        if cleared:
            self.save()
        return cleared

    def get_cached_prompt_translation(self, cache_key: str) -> str:
        return self.translation_cache.get(cache_key, "")

    def mark_cached_prompt_translation(self, cache_key: str, translation: str):
        if cache_key and translation:
            self.translation_cache[cache_key] = translation
            self.save()


def _replace_with_retry(tmp_path: Path, target_path: Path, attempts: int = 20):
    """Atomically replace a progress file, tolerating short Windows file locks."""
    last_error = None
    for attempt in range(max(1, attempts)):
        try:
            os.replace(tmp_path, target_path)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(min(0.05 * (attempt + 1), 0.5))
    raise PermissionError(
        f"无法写入进度文件，目标可能被其他程序占用：{target_path}"
    ) from last_error


def _read_progress_data(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("坐标翻译进度文件根节点必须是对象")
    return data


def _progress_data_score(data: dict) -> int:
    translations = data.get("translations", {})
    failed_blocks = data.get("failed_blocks", {})
    translation_cache = data.get("translation_cache", {})
    return (
        len(translations) if isinstance(translations, dict) else 0
    ) * 3 + (
        len(translation_cache) if isinstance(translation_cache, dict) else 0
    ) + (
        len(failed_blocks) if isinstance(failed_blocks, dict) else 0
    )


def _line_key(span) -> float:
    return round(float(span.bbox[1]), 1)


def block_source_text(block: LayoutTextBlock) -> str:
    lines: list[list] = []
    for span in sorted(block.spans, key=lambda item: (item.bbox[1], item.bbox[0])):
        if not lines or abs(_line_key(lines[-1][0]) - _line_key(span)) > max(span.size * 0.45, 1.0):
            lines.append([span])
        else:
            lines[-1].append(span)
    rendered_lines = []
    for line in lines:
        rendered_lines.append("".join(span.text for span in sorted(line, key=lambda item: item.bbox[0])))
    return "\n".join(rendered_lines).strip()


def export_translation_template(layout: LayoutDocument, output_path: str):
    ensure_output_parent(output_path)
    translations = []
    for page in layout.pages:
        for block in page.text_blocks:
            source_text = block_source_text(block)
            if not source_text:
                continue
            translations.append({
                "id": block.id,
                "page": page.index + 1,
                "source_text": source_text,
                "text": block.translated_text or "",
            })
    data = {
        "source_pdf": layout.source_pdf,
        "translations": translations,
    }
    Path(output_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_translation_map(path: str) -> dict[str, str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("translations"), list):
        raise ValueError("翻译文件必须包含 translations 列表")
    result: dict[str, str] = {}
    for item in data["translations"]:
        if not isinstance(item, dict):
            raise ValueError("translations 里的每一项都必须是对象")
        if "id" not in item or "text" not in item:
            raise ValueError("每条翻译必须包含 id 和 text")
        block_id = str(item["id"])
        if block_id in result:
            raise ValueError(f"重复的翻译块 ID：{block_id}")
        text = str(item["text"])
        if text.strip():
            result[block_id] = text
    return result


def _translated_block(block: LayoutTextBlock, translated_text: str | None) -> LayoutTextBlock:
    return LayoutTextBlock(
        id=block.id,
        bbox=block.bbox,
        spans=block.spans,
        translated_text=translated_text,
    )


def apply_translation_map(layout: LayoutDocument, translations: dict[str, str]) -> LayoutDocument:
    known_ids = {block.id for page in layout.pages for block in page.text_blocks}
    unknown_ids = sorted(set(translations) - known_ids)
    if unknown_ids:
        raise ValueError("翻译文件包含未知块 ID：" + ", ".join(unknown_ids[:10]))

    pages = []
    for page in layout.pages:
        text_blocks = [
            _translated_block(block, translations.get(block.id, block.translated_text))
            for block in page.text_blocks
        ]
        pages.append(LayoutPage(
            index=page.index,
            width=page.width,
            height=page.height,
            text_blocks=text_blocks,
            image_blocks=page.image_blocks,
        ))
    return LayoutDocument(
        schema_version=layout.schema_version,
        source_pdf=layout.source_pdf,
        page_count=layout.page_count,
        pages=pages,
    )


def apply_translations_file(layout_json_path: str, translations_json_path: str,
                            output_path: str) -> LayoutDocument:
    layout = layout_document_from_json(Path(layout_json_path).read_text(encoding="utf-8"))
    translations = _load_translation_map(translations_json_path)
    translated = apply_translation_map(layout, translations)
    ensure_output_parent(output_path)
    Path(output_path).write_text(translated.to_json(), encoding="utf-8")
    return translated


def _layout_page_units(layout: LayoutDocument, progress: LayoutTranslationProgress,
                       failed_filter: set[str] | None = None):
    units = []
    for page in layout.pages:
        blocks = [
            block for block in page.text_blocks
            if block_source_text(block)
        ]
        if failed_filter is not None:
            blocks = [block for block in blocks if block.id in failed_filter]
        else:
            blocks = [block for block in blocks if not progress.is_completed(block.id)]
        if blocks:
            units.append((page, blocks))
    return units


def _marked_layout_text(blocks: list[LayoutTextBlock]) -> str:
    parts = [
        "Translate each block below. Preserve every block marker line exactly. "
        "Return one translated block for each source block. Do not merge blocks, remove markers, "
        "or add commentary."
    ]
    for block in blocks:
        parts.append(f"[BLOCK {block.id}]\n{block_source_text(block)}\n[/BLOCK {block.id}]")
    return "\n\n".join(parts)


def _parse_marked_translations(text: str, expected_ids: set[str]) -> dict[str, str]:
    pattern = re.compile(
        r"\[BLOCK ([^\]\s]+)\]\s*(.*?)\s*\[/BLOCK \1\]",
        re.DOTALL,
    )
    parsed = {}
    for match in pattern.finditer(text):
        block_id = match.group(1).strip()
        translated = match.group(2).strip()
        if block_id in parsed:
            raise ValueError(f"重复的翻译块标记：{block_id}")
        parsed[block_id] = translated
    missing = sorted(expected_ids - set(parsed))
    extra = sorted(set(parsed) - expected_ids)
    if missing or extra:
        parts = []
        if missing:
            parts.append("缺少：" + ", ".join(missing[:10]))
        if extra:
            parts.append("多余：" + ", ".join(extra[:10]))
        raise ValueError("坐标翻译块标记不匹配；" + "；".join(parts))
    empty = [block_id for block_id, translated in parsed.items() if not translated]
    if empty:
        raise ValueError("译文为空：" + ", ".join(sorted(empty)[:10]))
    return parsed


def translate_layout_blocks(layout: LayoutDocument, translator, progress: LayoutTranslationProgress,
                            retry_failed: bool = False, progress_callback=None) -> dict[str, str]:
    failed_filter = progress.get_failed_blocks() if retry_failed else None
    if retry_failed:
        progress.clear_failed_blocks(failed_filter)

    translations: dict[str, str] = {}
    units = _layout_page_units(layout, progress, failed_filter=failed_filter)

    total = len(units)
    previous_context = ""
    for done, (page, blocks) in enumerate(units, start=1):
        unit_id = f"p{page.index + 1:04d}"
        expected_ids = {block.id for block in blocks}
        source_text = _marked_layout_text(blocks)
        translation = translator.translate_chunk(
            source_text,
            page_num=page.index,
            prev_context=previous_context[-900:],
            cache=progress,
        )
        if translation.lstrip().startswith(TRANSLATION_FAILURE_PREFIX):
            for block in blocks:
                progress.mark_failed(block.id, translation)
            if progress_callback:
                progress_callback(done, total, unit_id, False)
            continue
        try:
            parsed = _parse_marked_translations(translation, expected_ids)
        except ValueError as exc:
            message = f"{TRANSLATION_FAILURE_PREFIX} {exc}]"
            for block in blocks:
                progress.mark_failed(block.id, message)
            if progress_callback:
                progress_callback(done, total, unit_id, False)
            continue
        for block_id, block_translation in parsed.items():
            progress.mark_completed(block_id, block_translation)
            translations[block_id] = block_translation
        previous_context = "\n".join(
            block_source_text(block)
            for block in page.text_blocks
            if block_source_text(block)
        )
        if progress_callback:
            progress_callback(done, total, f"{unit_id} / {len(blocks)} 块", True)

    if progress.failed_blocks:
        failed_ids = ", ".join(sorted(progress.failed_blocks)[:10])
        raise RuntimeError(f"存在失败文本块：{failed_ids}")
    merged = dict(progress.translations)
    merged.update(translations)
    return merged


def translate_layout_to_template(layout: LayoutDocument, translator,
                                 progress_file: str, output_path: str,
                                 retry_failed: bool = False,
                                 progress_callback=None) -> dict[str, str]:
    progress = LayoutTranslationProgress(progress_file)
    translations = translate_layout_blocks(
        layout,
        translator,
        progress,
        retry_failed=retry_failed,
        progress_callback=progress_callback,
    )
    translated_layout = apply_translation_map(layout, translations)
    export_translation_template(translated_layout, output_path)
    return translations


def _block_font_size(block: LayoutTextBlock) -> float:
    sizes = sorted(span.size for span in block.spans if span.size > 0)
    if not sizes:
        raise ValueError(f"文本块缺少有效字号：{block.id}")
    return sizes[len(sizes) // 2]


def _story_html(text: str, font_size: float) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        lines = [text]
    content = "<br>".join(html.escape(line) for line in lines)
    return (
        "<body style='margin:0; padding:0'>"
        f"<div style='font-size:{font_size}pt; line-height:1.12; margin:0; padding:0'>"
        f"{content}"
        "</div>"
        "</body>"
    )


def check_translated_overflow(layout: LayoutDocument) -> list[LayoutFitIssue]:
    issues = []
    for page in layout.pages:
        for block in page.text_blocks:
            if not block.translated_text:
                continue
            x0, y0, x1, y1 = block.bbox
            width = max(0, x1 - x0)
            height = max(0, y1 - y0)
            if width <= 0 or height <= 0:
                raise ValueError(f"文本块坐标无效：{block.id}")
            story = pymupdf.Story(_story_html(block.translated_text, _block_font_size(block)))
            more, filled = story.place(pymupdf.Rect(0, 0, width, height))
            filled_width = max(0, float(filled[2]) - float(filled[0]))
            filled_height = max(0, float(filled[3]) - float(filled[1]))
            if more or filled_width > width or filled_height > height:
                issues.append(LayoutFitIssue(
                    page=page.index + 1,
                    block_id=block.id,
                    width=round(width, 3),
                    height=round(height, 3),
                    text_length=len(block.translated_text),
                ))
    return issues


def write_overflow_report(layout: LayoutDocument, output_path: str) -> list[LayoutFitIssue]:
    issues = check_translated_overflow(layout)
    ensure_output_parent(output_path)
    lines = [f"# 译文溢出报告：{layout.source_pdf}", ""]
    if not issues:
        lines.append("未发现译文溢出。")
    else:
        lines.append(f"发现 {len(issues)} 个溢出文本块。")
        lines.append("")
        for issue in issues:
            lines.append(
                f"- 第 {issue.page} 页 `{issue.block_id}`："
                f"{issue.width:.1f} x {issue.height:.1f} pt，译文 {issue.text_length} 字"
            )
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return issues
