#!/usr/bin/env python3
"""
DG TRPG PDF Translator — THE MILLENNIUM (v2.0)
===============================================
Translates English PDF (dual-column TRPG layout) to Chinese Markdown/HTML/Word
using DeepSeek V4 API with TRPG-specific terminology.

v2.0 Features:
    - Context window: carries previous page context for cross-page coherence
    - Chapter detection: auto-detects headings by font size/bold for TOC generation
    - HTML output: browser-readable dual-column layout for review and print
    - Batch concurrency: translates multiple pages in parallel
    - Token cost tracking: real-time usage and cost display
    - Breakpoint resume
    - TRPG glossary support

Usage:
    python translate_pdf.py input.pdf --api-key YOUR_KEY
    python translate_pdf.py input.pdf --api-key YOUR_KEY --format html --workers 32
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# ============================================================
# Re-export layer: backward-compatible public API
# ============================================================
# All symbols previously defined in this monolithic file are now
# imported from the core/ and exporters/ packages and re-exported
# so that existing consumers (app.py, tests, scripts) continue to
# work without modification.

from core import (
    # constants
    PROMPT_VERSION,
    EXTRACTOR_VERSION,
    SUPPORTED_OUTPUT_FORMATS,
    TRANSLATION_FAILURE_PREFIX,
    # utils
    configure_console_output,
    ensure_output_parent,
    output_base_in_own_dir,
    normalize_page_range,
    is_failed_translation,
    parse_page_selection,
    file_sha256,
    # extractor
    PDFExtractor,
    ChapterDetector,
    HeadingInfo,
    build_extraction_diagnostics_report,
    # translator
    Translator,
    TokenStats,
    translate_batch_concurrent,
    # progress
    ProgressTracker,
    build_progress_metadata,
    compare_progress_metadata,
    # glossary
    load_glossary,
    find_relevant_glossary_terms,
    build_glossary_report,
    write_glossary_report,
)

from exporters import (
    write_html_output,
    write_word_output,
    write_markdown_output,
    paginate_translated_blocks,
)

from exporters.word import HAS_DOCX
from core.utils import looks_untranslated_page

# Apply console output configuration at import time (preserves original behavior)
configure_console_output()


# ============================================================
# MAIN ORCHESTRATOR
# ============================================================

def translate_pdf(pdf_path, output_path, api_key, glossary_path=None,
                  model="deepseek-v4-pro", start_page=0, end_page=None,
                  output_format="markdown", max_workers=32,
                  provider="deepseek", base_url="https://api.deepseek.com",
                  retry_failed=False):
    print("=" * 60)
    print("  DG TRPG PDF Translator v2.0")
    print("=" * 60)
    print()

    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        raise ValueError(f"不支持的输出格式：{output_format}")
    if not pdf_path or not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF 文件不存在：{pdf_path}")
    if glossary_path and not os.path.exists(glossary_path):
        raise FileNotFoundError(f"术语表文件不存在：{glossary_path}")
    if not base_url or not str(base_url).strip():
        raise ValueError("Base URL 不能为空")
    if not provider or not str(provider).strip():
        raise ValueError("服务名称不能为空")
    max_workers = 32 if max_workers is None else int(max_workers)
    max_workers = max(1, min(64, max_workers))
    output_base = output_path
    for ext in (".md", ".pdf", ".docx", ".html"):
        if output_base.endswith(ext):
            output_base = output_base[:-len(ext)]
            break
    output_base = output_base_in_own_dir(output_base)
    ensure_output_parent(output_base + ".tmp")

    stats = TokenStats()

    print(f"Opening PDF: {pdf_path}")
    extractor = PDFExtractor(pdf_path)
    try:
        total = extractor.total_pages
        print(f"   Total pages: {total}")

        start_page, end_page = normalize_page_range(start_page, end_page, total)
        print(f"   Range: page {start_page + 1} to {end_page}")
        print(f"   Workers: {max_workers}")
        print(f"   Format: {output_format}")
        print()

        glossary = {}
        if glossary_path:
            print(f"Loading glossary: {glossary_path}")
            glossary = load_glossary(glossary_path)
            print(f"   Loaded {len(glossary)} terms")
            print()

        print(f"Engine: {provider} ({model})")
        translator = Translator(api_key=api_key, model=model, base_url=base_url, stats=stats)
        translator.set_glossary(glossary)
        print()

        progress_file = output_base + ".progress.json"
        progress_metadata = build_progress_metadata(
            pdf_path=pdf_path,
            glossary_path=glossary_path,
            model=model,
            provider=provider,
            base_url=base_url,
            start_page=start_page,
            end_page=end_page,
        )
        tracker = ProgressTracker(progress_file, expected_metadata=progress_metadata)
        if tracker.metadata_mismatches:
            print("⚠️  进度文件与当前设置不一致。")
            for mismatch in tracker.metadata_mismatches[:5]:
                print(f"   - {mismatch}")
            if tracker.ignored_existing_progress:
                print("   已保留文件但本次不复用旧译文。")
        if retry_failed:
            failed_retry_pages = {
                p for p in tracker.get_failed_pages()
                if start_page <= p < end_page
            }
            if failed_retry_pages:
                print(
                    "   只重试失败页: "
                    + ", ".join(str(p + 1) for p in sorted(failed_retry_pages))
                )
                start_end_pages = sorted(failed_retry_pages)
            else:
                print("   没有可重试的失败页。")
                start_end_pages = []
        else:
            start_end_pages = list(range(start_page, end_page))
        print()

        print("Extracting text and analyzing chapters...")
        pages_text = {}
        source_page_labels = {}
        page_layouts = {}
        page_diagnostics = []
        for page_num in range(start_page, end_page):
            source_page_labels[page_num] = extractor.get_page_label(page_num)
            page_layouts[page_num] = extractor.detect_page_layout(page_num)
            text = extractor.extract_page(page_num, include_images=False)
            pages_text[page_num] = text
            page_diagnostics.append(extractor.get_page_diagnostics(page_num, text))

        extractor.finalize_chapters()
        toc = extractor.chapter_detector.get_toc_markdown()
        if toc:
            print(f"   Detected {len(extractor.chapter_detector.headings)} headings")
        else:
            print("   No clear chapter structure detected")
        risky_pages = [item for item in page_diagnostics if item.get("risks")]
        if risky_pages:
            print(
                "   Extraction warnings: "
                + ", ".join(str(item["page"] + 1) for item in risky_pages[:20])
            )
        print()

        print("Translating...")
        print("-" * 40)
        start_time = time.time()

        if max_workers > 1:
            print(f"   Concurrent mode: {max_workers} workers")
            pages_data = []
            prev_text = ""
            for page_num in start_end_pages:
                text = pages_text.get(page_num, "")
                context = prev_text[-900:] if prev_text else ""
                pages_data.append((page_num, text, context))
                context_text = extractor.get_context_text(page_num)
                if context_text.strip():
                    prev_text = context_text
            results = translate_batch_concurrent(pages_data, translator, tracker, max_workers)
            translated_pages = [(pn, t) for pn, t in results.items() if t.strip()]
        else:
            translated_pages = []
            prev_translation_tail = ""
            pages_to_process = list(start_end_pages)
            total_to_do = len(pages_to_process)
            done_count = 0

            for page_num in pages_to_process:
                done_count += 1
                progress_pct = done_count / total_to_do * 100

                if tracker.is_completed(page_num):
                    translation = tracker.get_translation(page_num)
                    if translation:
                        translated_pages.append((page_num, translation))
                        prev_translation_tail = translation[-300:]
                    print(f"  [skip] Page {page_num + 1}/{total}")
                    continue

                text = pages_text.get(page_num, "")
                if not text.strip():
                    print(f"  [empty] Page {page_num + 1}/{total}")
                    tracker.mark_completed(page_num, "")
                    continue

                print(f"  [{progress_pct:.0f}%] Page {page_num + 1}/{total}", end="", flush=True)
                translation = translator.translate_chunk(
                    text,
                    page_num,
                    prev_context=prev_translation_tail,
                    cache=tracker,
                )

                if translation and not is_failed_translation(translation):
                    translated_pages.append((page_num, translation))
                    tracker.mark_completed(page_num, translation)
                    prev_translation_tail = translation[-300:]
                    print(f" done (Y{stats.cost_yuan:.3f})")
                elif is_failed_translation(translation):
                    translated_pages.append((page_num, translation))
                    tracker.mark_failed(page_num, translation)
                    print(" failed; not cached")
                else:
                    print(f" empty result")
                    tracker.mark_completed(page_num, "")
                time.sleep(0.3)

        elapsed = time.time() - start_time
        print("-" * 40)
        print()

        for page_num in range(start_page, end_page):
            translation = tracker.get_translation(page_num)
            if not translation.strip():
                continue
            if looks_untranslated_page(
                pages_text.get(page_num, ""),
                translation,
                page_layouts.get(page_num, ""),
            ):
                tracker.mark_failed(page_num, "页面疑似整页未翻译，已拦截输出")

        translated_pages_sorted = sorted(
            [
                (page_num, tracker.get_translation(page_num))
                for page_num in range(start_page, end_page)
                if tracker.get_translation(page_num).strip()
            ],
            key=lambda x: x[0],
        )
        failed_pages = [
            page_num + 1 for page_num in sorted(tracker.get_failed_pages())
            if start_page <= page_num < end_page
        ]
        if failed_pages:
            print("⚠️  以下页翻译失败且未写入进度缓存: " + ", ".join(map(str, failed_pages[:20])))

        diagnostics_output = output_base + "_extraction_report.md"
        print(f"  生成提取诊断报告: {diagnostics_output}")
        with open(diagnostics_output, "w", encoding="utf-8") as f:
            f.write(build_extraction_diagnostics_report(page_diagnostics, Path(pdf_path).stem))
            f.write("\n")
        print("   ✓ 提取诊断输出完成")

        if glossary:
            report_output = output_base + "_glossary_report.md"
            print(f"  生成术语命中报告: {report_output}")
            write_glossary_report(pages_text, glossary, report_output, Path(pdf_path).stem)
            print("   ✓ 术语报告输出完成")

        # HTML output
        if output_format in ("html", "both", "all"):
            html_output = output_base + ".html"
            print(f"  生成 HTML: {html_output}")
            try:
                write_html_output(
                    translated_pages_sorted,
                    html_output,
                    Path(pdf_path).stem,
                    source_page_labels=source_page_labels,
                    page_layouts=page_layouts,
                )
                print("   ✅ HTML 输出完成")
            except Exception as e:
                print(f"   ❌ HTML 输出失败: {e}")

        # Markdown output
        if output_format in ("markdown", "both", "all"):
            md_output = output_base + ".md"
            print(f"  生成 Markdown: {md_output}")
            write_markdown_output(
                translated_pages_sorted,
                md_output,
                Path(pdf_path).stem,
                toc,
                page_layouts=page_layouts,
            )
            print("   ✅ Markdown 输出完成")

        # Word output
        if output_format in ("word", "all"):
            if not HAS_DOCX:
                print("  ⚠️  Word 输出需要 python-docx，请运行: pip install python-docx")
            else:
                docx_output = output_base + ".docx"
                print(f"  生成 Word 文档: {docx_output}")
                try:
                    write_word_output(
                        translated_pages_sorted,
                        docx_output,
                        Path(pdf_path).stem,
                        source_pages_text=pages_text,
                        source_page_labels=source_page_labels,
                        page_layouts=page_layouts,
                    )
                    print("   ✓ Word 输出完成")

                except Exception as e:
                    print(f"   ❌ Word 输出失败: {e}")

        page_count = len([t for _, t in translated_pages_sorted if t.strip()])
        print(f"\n  共翻译 {page_count} 页")

        print()
        print(f"Time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
        print()
        print(stats.summary())
        print()
        print(f"Progress file: {progress_file}")
        print(f"Output folder: {Path(output_base).parent}")

    finally:
        extractor.close()


# ============================================================
# CLI with Config File Support
# ============================================================

def load_config(config_path: str) -> dict:
    """Load configuration from a JSON file."""
    if not os.path.exists(config_path):
        print(f"❌ 配置文件不存在: {config_path}")
        sys.exit(1)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"❌ 配置文件 JSON 格式错误: {exc}")
        sys.exit(1)
    if not isinstance(config, dict):
        print("❌ 配置文件顶层必须是 JSON 对象。")
        sys.exit(1)
    return config


def main():
    parser = argparse.ArgumentParser(
        description="绿色三角洲 PDF 翻译工具 v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 使用配置文件（推荐，最简单）
  python translate_pdf.py --config config.json

  # 命令行参数
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx --format html --workers 32

  # 指定术语表和范围
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx \
      --glossary glossary.tsv --start 0 --end 5

  # 使用更便宜的模型
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx \
      --model deepseek-v4-flash --workers 8
        """
    )

    parser.add_argument("pdf", nargs="?", default=None, help="输入 PDF 文件路径")
    parser.add_argument("--config", "-c", default=None, help="配置文件路径（JSON）")
    parser.add_argument("--api-key", default=None, help="DeepSeek API Key")
    parser.add_argument("--output", "-o", default=None, help="输出文件路径（不含扩展名）")
    parser.add_argument("--glossary", "-g", default=None, help="术语表文件路径（TSV 格式）")
    parser.add_argument("--model", default=None, help="模型名称（默认: deepseek-v4-pro）")
    parser.add_argument("--provider", default=None, help="服务名称，只用于记录进度指纹（默认: deepseek）")
    parser.add_argument("--base-url", default=None, help="OpenAI 兼容接口 Base URL")
    parser.add_argument("--format", "-f", choices=["markdown", "html", "word", "both", "all"],
                        default=None, help="输出格式: markdown/html/word/both/all（默认: markdown）")
    parser.add_argument("--workers", "-w", type=int, default=None,
                        help="并发线程数（默认: 32，上限: 64）")
    parser.add_argument("--start", type=int, default=None, help="起始页码（从0开始）")
    parser.add_argument("--end", type=int, default=None, help="结束页码（不含）")
    parser.add_argument("--retry-failed", action="store_true", help="只重试 progress.json 里记录的失败页")

    args = parser.parse_args()

    # Load config file if specified
    config = {}
    if args.config:
        config = load_config(args.config)

    # Merge: command line args override config file
    pdf_path = args.pdf or config.get("pdf")
    api_key = args.api_key or config.get("api_key")
    output_path = args.output or config.get("output")
    glossary_path = args.glossary or config.get("glossary")
    model = args.model or config.get("model", "deepseek-v4-pro")
    provider = args.provider or config.get("provider", "deepseek")
    base_url = args.base_url or config.get("base_url", "https://api.deepseek.com")
    output_format = args.format or config.get("format", "markdown")
    workers = args.workers if args.workers is not None else config.get("workers", 32)
    start_page = args.start if args.start is not None else config.get("start", 0)
    end_page = args.end if args.end is not None else config.get("end")

    # Validate required params
    if not pdf_path:
        print("❌ 缺少 PDF 文件路径。请通过参数或配置文件指定。")
        parser.print_help()
        sys.exit(1)
    if not api_key:
        print("❌ 缺少 API Key。请通过 --api-key 或配置文件指定。")
        sys.exit(1)
    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        print(f"❌ 不支持的输出格式: {output_format}")
        sys.exit(1)

    # Default output path
    if output_path is None:
        pdf_stem = Path(pdf_path).stem
        output_path = str(Path("output") / f"{pdf_stem}_cn.md")

    # Validate
    if not os.path.exists(pdf_path):
        print(f"❌ PDF 文件不存在: {pdf_path}")
        sys.exit(1)
    if glossary_path and not os.path.exists(glossary_path):
        print(f"❌ 术语表文件不存在: {glossary_path}")
        sys.exit(1)

    try:
        workers = int(workers)
        start_page = int(start_page or 0)
        end_page = None if end_page is None or end_page == "" else int(end_page)
    except (TypeError, ValueError):
        print("❌ workers/start/end 必须是整数。")
        sys.exit(1)

    if workers < 1:
        workers = 1
    elif workers > 64:
        print("⚠️  并发数上限为 64，已自动调整")
        workers = 64

    # Run
    translate_pdf(
        pdf_path=pdf_path,
        output_path=output_path,
        api_key=api_key,
        glossary_path=glossary_path,
        model=model,
        provider=provider,
        base_url=base_url,
        start_page=start_page,
        end_page=end_page,
        output_format=output_format,
        max_workers=workers,
        retry_failed=bool(args.retry_failed or config.get("retry_failed", False)),
    )


if __name__ == "__main__":
    main()
