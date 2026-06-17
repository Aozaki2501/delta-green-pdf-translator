#!/usr/bin/env python3
"""
Markdown Translator — CLI Entry Point
======================================
Translates a Markdown file from English to Chinese, preserving structure.

Usage:
    python translate_md.py input.md --api-key YOUR_KEY
    python translate_md.py input.md --api-key YOUR_KEY --model deepseek-chat --workers 8
    python translate_md.py input.md --api-key YOUR_KEY --glossary glossary.tsv
"""

import argparse
import re
import sys
import time
from pathlib import Path

from core.md_extractor import MarkdownExtractor, MdBlock, merge_blocks_for_translation
from core.translator import Translator, TokenStats
from core.progress import ProgressTracker
from core.glossary import load_glossary, build_glossary_matcher, select_core_glossary_terms
from core.dispatcher import ConcurrentDispatcher, DispatcherConfig
from core.utils import file_sha256, configure_console_output
from core.constants import PROMPT_VERSION
from core.translation_validation import ensure_no_prompt_leak
from exporters.md_preserve import write_md_output

configure_console_output()

APP_DIR = Path(__file__).resolve().parent
DEFAULT_GLOSSARY_PATH = APP_DIR / "glossary.tsv"


def _marked_md_group_text(group: list[MdBlock]) -> str:
    return "\n\n".join(
        f"[BLOCK {block.index}]\n{block.text}\n[/BLOCK {block.index}]"
        for block in group
    )


def _parse_marked_md_translation(translated: str, group: list[MdBlock]) -> dict[int, str]:
    """Parse BLOCK markers from translated text. Returns found translations.

    For single-block groups, accepts plain text without markers.
    Raises ValueError only when NO blocks could be parsed at all.
    If some blocks are found but others are missing, returns partial results
    (caller handles retry for missing blocks).
    """
    ensure_no_prompt_leak(translated or "", "模型返回")
    # 单块组：直接使用返回文本（不需要 BLOCK 标记）
    if len(group) == 1:
        text = (translated or "").strip()
        if not text:
            raise ValueError(f"Markdown 翻译块为空：{group[0].index}")
        # 如果 AI 仍然返回了 BLOCK 标记，剥离它
        m = re.search(r"\[BLOCK \d+\]\s*(.*?)\s*\[/BLOCK \d+\]", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
        # 剥离 AI 可能添加的 # 前缀（heading 重组时会加回来）
        if group[0].block_type == "heading":
            text = re.sub(r'^#{1,6}\s*', '', text)
        ensure_no_prompt_leak(text)
        return {group[0].index: text} if text else {}

    expected = [block.index for block in group]
    found: dict[int, str] = {}
    pattern = re.compile(r"\[BLOCK (\d+)\]\s*(.*?)\s*\[/BLOCK \1\]", re.DOTALL)
    for match in pattern.finditer(translated or ""):
        block_index = int(match.group(1))
        if block_index in found:
            continue  # 重复块取第一个
        found[block_index] = match.group(2).strip()

    # 过滤掉空译文和不在预期列表中的块
    found = {idx: text for idx, text in found.items() if idx in expected and text}
    for idx, text in found.items():
        ensure_no_prompt_leak(text, f"Markdown 译文块 {idx}")

    if not found:
        raise ValueError("Markdown 翻译块标记完全无法解析，未找到任何有效 [BLOCK n] 标记")
    return found


def build_md_progress_metadata(md_path: str, glossary_path: str | None,
                                model: str, base_url: str) -> dict:
    """Build metadata fingerprint for a Markdown translation session."""
    return {
        "schema": 1,
        "source_type": "markdown",
        "source_sha256": file_sha256(md_path),
        "glossary_sha256": file_sha256(glossary_path) if glossary_path else "",
        "model": model,
        "base_url": base_url,
        "prompt_version": PROMPT_VERSION,
    }


def translate_md_file(
    md_path: str,
    api_key: str,
    model: str = "deepseek-chat",
    base_url: str = "https://api.deepseek.com",
    glossary_path: str | None = None,
    output_path: str | None = None,
    max_workers: int = 4,
    max_blocks: int | None = None,
    progress_callback=None,
    rate_limit: int = 60,
    cooldown: float = 1.0,
    max_split_depth: int = 10,
    fuzzy_matching: bool = False,
) -> dict:
    """
    Translate a Markdown file end-to-end.

    Args:
        max_blocks: If set, only translate the first N translatable blocks.
                    Useful for testing or partial translation.

    Returns dict with keys: output_path, stats_summary, block_count, translated_count
    """
    md_path = str(Path(md_path).resolve())

    # Default output path
    if not output_path:
        stem = Path(md_path).stem
        out_dir = Path(md_path).parent / f"{stem}_translated"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(out_dir / f"{stem}_zh.md")

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
    print(f"Extracting blocks from: {md_path}")
    extractor = MarkdownExtractor(md_path)
    all_blocks = extractor.extract()
    translatable = extractor.get_translatable_blocks()
    print(f"  Total blocks: {len(all_blocks)}, translatable: {len(translatable)}")

    # Apply block limit if specified
    if max_blocks and max_blocks > 0 and len(translatable) > max_blocks:
        print(f"  Limiting to first {max_blocks} translatable blocks (of {len(translatable)})")
        translatable = translatable[:max_blocks]

    if not translatable:
        print("No translatable content found.")
        write_md_output(all_blocks, {}, output_path)
        return {"output_path": output_path, "stats_summary": "", "block_count": 0, "translated_count": 0}

    # Setup progress tracker
    progress_file = str(Path(output_path).parent / ".progress.json")
    metadata = build_md_progress_metadata(md_path, glossary_path, model, base_url)
    tracker = ProgressTracker(progress_file, expected_metadata=metadata)

    # Setup translator with AC glossary matcher
    stats = TokenStats()
    glossary_matcher = build_glossary_matcher(glossary, fuzzy=fuzzy_matching) if glossary else None
    translator = Translator(api_key=api_key, model=model, base_url=base_url, stats=stats,
                            glossary_matcher=glossary_matcher)
    translator.set_glossary(glossary)
    if glossary:
        translator.set_core_glossary(
            select_core_glossary_terms(
                (block.text for block in translatable),
                glossary,
                matcher=glossary_matcher,
            )
        )

    # Merge blocks for API efficiency
    groups = merge_blocks_for_translation(translatable)
    print(f"  Translation groups: {len(groups)}")

    # Log configuration
    print(f"  Config: workers={max_workers}, rate_limit={rate_limit}/min, "
          f"cooldown={cooldown}s, max_split_depth={max_split_depth}, "
          f"fuzzy_matching={fuzzy_matching}")

    # Dispatch translation via ConcurrentDispatcher
    config = DispatcherConfig(
        concurrency=max_workers,
        rate_limit=rate_limit,
        cooldown=cooldown,
        max_split_depth=max_split_depth,
        fuzzy_matching=fuzzy_matching,
    )
    dispatcher = ConcurrentDispatcher(config, translator, tracker, stats, progress_callback)
    translations = dispatcher.dispatch_all(
        groups,
        build_text_fn=_marked_md_group_text,
        parse_fn=_parse_marked_md_translation,
        source_type="markdown",
    )

    failed_count = len(tracker.get_failed_pages())
    if translatable and not translations:
        raise RuntimeError(f"所有 Markdown 翻译块都失败了，未生成有效译文；失败组数：{failed_count}")
    missing_count = len(translatable) - len(translations)
    if missing_count > 0:
        raise RuntimeError(
            f"Markdown 翻译未完成：{missing_count}/{len(translatable)} 个块没有合格译文"
        )

    # Write output
    print(f"\nWriting output to: {output_path}")
    write_md_output(all_blocks, translations, output_path)

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
    parser = argparse.ArgumentParser(description="Translate Markdown file (EN → ZH)")
    parser.add_argument("input", help="Input .md file path")
    parser.add_argument("--api-key", required=True, help="API key")
    parser.add_argument("--model", default="deepseek-chat", help="Model name")
    parser.add_argument("--base-url", default="https://api.deepseek.com", help="API base URL")
    parser.add_argument("--glossary", default=None, help="Glossary TSV file path")
    parser.add_argument("--output", default=None, help="Output file path")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent workers")

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)

    start = time.time()
    result = translate_md_file(
        md_path=args.input,
        api_key=args.api_key,
        model=args.model,
        base_url=args.base_url,
        glossary_path=args.glossary,
        output_path=args.output,
        max_workers=args.workers,
    )
    elapsed = time.time() - start
    print(f"\nCompleted in {elapsed:.1f}s")
    print(f"Output: {result['output_path']}")


if __name__ == "__main__":
    main()
