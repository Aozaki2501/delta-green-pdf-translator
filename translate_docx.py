#!/usr/bin/env python3
"""
Word/DOCX Translator — CLI Entry Point
========================================
Translates a Word document from English to Chinese, preserving formatting.

Usage:
    python translate_docx.py input.docx --api-key YOUR_KEY
    python translate_docx.py input.docx --api-key YOUR_KEY --model deepseek-chat --workers 8
    python translate_docx.py input.docx --api-key YOUR_KEY --glossary glossary.tsv
"""

import argparse
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from core.docx_extractor import (
    DocxExtractor, DocxBlock, serialize_runs_with_markers,
)
from core.translator import Translator, TokenStats
from core.progress import ProgressTracker
from core.glossary import load_glossary
from core.utils import file_sha256, configure_console_output
from core.constants import TRANSLATION_FAILURE_PREFIX, PROMPT_VERSION
from exporters.docx_inplace import write_docx_inplace

configure_console_output()

APP_DIR = Path(__file__).resolve().parent
DEFAULT_GLOSSARY_PATH = APP_DIR / "glossary.tsv"


def _docx_block_text(block: DocxBlock) -> str:
    if block.runs and any(r.bold or r.italic for r in block.runs):
        return serialize_runs_with_markers(block.runs)
    return block.text


def _marked_docx_group_text(group: list[DocxBlock]) -> str:
    parts = []
    for block in group:
        parts.append(f"[BLOCK {block.index}]\n{_docx_block_text(block)}\n[/BLOCK {block.index}]")
    return "\n\n".join(parts)


def _parse_marked_docx_translation(translated: str, group: list[DocxBlock]) -> dict[int, str]:
    if len(group) == 1 and "[BLOCK " not in (translated or ""):
        text = (translated or "").strip()
        if not text:
            raise ValueError(f"Word 翻译块为空：{group[0].index}")
        return {group[0].index: text}

    expected = [block.index for block in group]
    found: dict[int, str] = {}
    pattern = re.compile(r"\[BLOCK (\d+)\]\s*(.*?)\s*\[/BLOCK \1\]", re.DOTALL)
    for match in pattern.finditer(translated or ""):
        block_index = int(match.group(1))
        if block_index in found:
            raise ValueError(f"重复返回 Word 翻译块：{block_index}")
        found[block_index] = match.group(2).strip()

    missing = [idx for idx in expected if idx not in found]
    extra = [idx for idx in found if idx not in expected]
    empty = [idx for idx in expected if idx in found and not found[idx]]
    errors = []
    if missing:
        errors.append("缺少块 " + ", ".join(map(str, missing[:10])))
    if extra:
        errors.append("多余块 " + ", ".join(map(str, extra[:10])))
    if empty:
        errors.append("空译文块 " + ", ".join(map(str, empty[:10])))
    if errors:
        raise ValueError("Word 翻译块标记不匹配；" + "；".join(errors))
    return found


def _report_progress(progress_callback, block_idx: int, text: str,
                     completed: int, total: int, stats: TokenStats) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(block_idx, text, completed, total, stats)
    except TypeError as exc:
        try:
            progress_callback(block_idx, text, completed, total)
        except TypeError:
            raise exc


def build_docx_progress_metadata(docx_path: str, glossary_path: str | None,
                                   model: str, base_url: str) -> dict:
    """Build metadata fingerprint for a Word translation session."""
    return {
        "schema": 1,
        "source_type": "docx",
        "source_sha256": file_sha256(docx_path),
        "glossary_sha256": file_sha256(glossary_path) if glossary_path else "",
        "model": model,
        "base_url": base_url,
        "prompt_version": PROMPT_VERSION,
    }


def translate_docx_file(
    docx_path: str,
    api_key: str,
    model: str = "deepseek-chat",
    base_url: str = "https://api.deepseek.com",
    glossary_path: str | None = None,
    output_path: str | None = None,
    max_workers: int = 4,
    cjk_font: str = "Microsoft YaHei",
    translate_headers: bool = False,
    progress_callback=None,
) -> dict:
    """
    Translate a Word document end-to-end.

    Returns dict with keys: output_path, stats_summary, block_count, translated_count
    """
    docx_path = str(Path(docx_path).resolve())

    # Default output path
    if not output_path:
        stem = Path(docx_path).stem
        out_dir = Path(docx_path).parent / f"{stem}_translated"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(out_dir / f"{stem}_zh.docx")
    output_file = Path(output_path)
    if output_file.exists():
        output_file.unlink()

    # Load glossary
    glossary = {}
    if glossary_path and Path(glossary_path).exists():
        glossary = load_glossary(glossary_path)
        print(f"Loaded glossary: {len(glossary)} terms")
    elif DEFAULT_GLOSSARY_PATH.exists():
        glossary = load_glossary(str(DEFAULT_GLOSSARY_PATH))
        glossary_path = str(DEFAULT_GLOSSARY_PATH)
        print(f"Loaded default glossary: {len(glossary)} terms")

    # Extract blocks
    print(f"Extracting blocks from: {docx_path}")
    extractor = DocxExtractor(docx_path, translate_headers=translate_headers)
    all_blocks = extractor.extract()
    translatable = extractor.get_translatable_blocks()
    print(f"  Total blocks: {len(all_blocks)}, translatable: {len(translatable)}")

    if not translatable:
        raise RuntimeError("Word 文档没有可翻译文本，未生成输出")

    # Setup progress tracker
    progress_file = str(Path(output_path).parent / ".progress.json")
    metadata = build_docx_progress_metadata(docx_path, glossary_path, model, base_url)
    tracker = ProgressTracker(progress_file, expected_metadata=metadata)

    # Setup translator
    stats = TokenStats()
    translator = Translator(api_key=api_key, model=model, base_url=base_url, stats=stats)
    translator.set_glossary(glossary)

    # Translate Word blocks one by one. Grouped DOCX requests are faster, but
    # models often drop block markers and cause silent partial English output.
    groups = [[block] for block in translatable]
    print(f"  Translation groups: {len(groups)}")

    # Translate
    translations: dict[int, str] = {}
    completed = 0
    total = len(groups)

    def translate_group(group: list[DocxBlock], prev_ctx: str):
        first_idx = group[0].index

        # Check cache
        if tracker.is_completed(first_idx):
            return first_idx, tracker.get_translation(first_idx), True

        text = _docx_block_text(group[0]) if len(group) == 1 else _marked_docx_group_text(group)

        result = translator.translate_block(
            text, block_index=None,
            prev_context=prev_ctx, source_type="docx",
            cache=tracker,
        )
        return first_idx, result, False

    prev_context = ""
    max_workers = max(1, int(max_workers))

    for group_start in range(0, len(groups), max_workers):
        batch = groups[group_start:group_start + max_workers]

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for group in batch:
                first_idx = group[0].index

                # Check if already done
                if tracker.is_completed(first_idx):
                    cached = tracker.get_translation(first_idx)
                    translations.update(_parse_marked_docx_translation(cached, group))
                    completed += 1
                    _report_progress(progress_callback, first_idx, cached, completed, total, stats)
                    continue

                future = executor.submit(translate_group, group, prev_context)
                futures[future] = group

            for future in as_completed(futures):
                group = futures[future]
                try:
                    first_idx, result, was_cached = future.result()
                except Exception as exc:
                    first_idx = group[0].index
                    result = f"{TRANSLATION_FAILURE_PREFIX} {exc}]"
                    was_cached = False

                if result and not result.startswith(TRANSLATION_FAILURE_PREFIX):
                    try:
                        parsed_translations = _parse_marked_docx_translation(result, group)
                    except ValueError as exc:
                        result = f"{TRANSLATION_FAILURE_PREFIX} {exc}]"
                        if not was_cached:
                            tracker.mark_failed(first_idx, result)
                    else:
                        translations.update(parsed_translations)
                        if not was_cached:
                            tracker.mark_completed(first_idx, result)
                        prev_context = "\n\n".join(parsed_translations.values())[:500]
                else:
                    if not was_cached:
                        tracker.mark_failed(first_idx, result)

                completed += 1
                _report_progress(progress_callback, first_idx, result or "", completed, total, stats)
                print(f"  [{completed}/{total}] block {first_idx + 1} {'(cached)' if was_cached else 'done'}")

    failed_count = len(tracker.get_failed_pages())
    if translatable and not translations:
        raise RuntimeError(f"所有 Word 翻译块都失败了，未生成有效译文；失败组数：{failed_count}")
    if failed_count:
        raise RuntimeError(f"Word 翻译有 {failed_count} 个块失败，未生成不完整的 Word 输出")
    if len(translations) != len(translatable):
        missing_count = len(translatable) - len(translations)
        raise RuntimeError(f"Word 翻译缺少 {missing_count} 个块，未生成不完整的 Word 输出")

    # Write output
    print(f"\nWriting output to: {output_path}")
    write_docx_inplace(all_blocks, translations, docx_path, output_path, cjk_font=cjk_font)

    summary = stats.summary()
    print(f"\n{summary}")

    return {
        "output_path": output_path,
        "stats_summary": summary,
        "block_count": len(translatable),
        "translated_count": len(translations),
        "failed_count": failed_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Translate Word document (EN → ZH)")
    parser.add_argument("input", help="Input .docx file path")
    parser.add_argument("--api-key", required=True, help="API key")
    parser.add_argument("--model", default="deepseek-chat", help="Model name")
    parser.add_argument("--base-url", default="https://api.deepseek.com", help="API base URL")
    parser.add_argument("--glossary", default=None, help="Glossary TSV file path")
    parser.add_argument("--output", default=None, help="Output file path")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent workers")
    parser.add_argument("--cjk-font", default="Microsoft YaHei", help="Chinese font name")
    parser.add_argument("--translate-headers", action="store_true", help="Also translate headers/footers")

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)

    start = time.time()
    result = translate_docx_file(
        docx_path=args.input,
        api_key=args.api_key,
        model=args.model,
        base_url=args.base_url,
        glossary_path=args.glossary,
        output_path=args.output,
        max_workers=args.workers,
        cjk_font=args.cjk_font,
        translate_headers=args.translate_headers,
    )
    elapsed = time.time() - start
    print(f"\nCompleted in {elapsed:.1f}s")
    print(f"Output: {result['output_path']}")


if __name__ == "__main__":
    main()
