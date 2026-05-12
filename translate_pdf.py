#!/usr/bin/env python3
"""
DG TRPG PDF Translator — THE MILLENNIUM (v2.0)
===============================================
Translates English PDF (dual-column TRPG layout) to Chinese Markdown/PDF
using DeepSeek V4 API with TRPG-specific terminology.

v2.0 Features:
    - Context window: carries previous page context for cross-page coherence
    - Chapter detection: auto-detects headings by font size/bold for TOC generation
    - Layout-preserving PDF output: overlays Chinese text on original PDF
    - Batch concurrency: translates multiple pages in parallel
    - Token cost tracking: real-time usage and cost display
    - Breakpoint resume
    - TRPG glossary support

Usage:
    python translate_pdf.py input.pdf --api-key YOUR_KEY
    python translate_pdf.py input.pdf --api-key YOUR_KEY --format pdf --workers 4
"""

import argparse
import json
import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

try:
    import pymupdf  # PyMuPDF >= 1.24
except ImportError:
    try:
        import fitz as pymupdf  # PyMuPDF < 1.24
    except ImportError:
        print("Error: PyMuPDF not installed. Run: pip install pymupdf")
        sys.exit(1)

try:
    from openai import OpenAI
except ImportError:
    print("Error: openai package not installed. Run: pip install openai")
    sys.exit(1)


# ============================================================
# TOKEN COST TRACKER
# ============================================================

@dataclass
class TokenStats:
    """Tracks token usage and estimated cost."""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    api_calls: int = 0
    failed_calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    PRICE_INPUT_PER_M = 1.0
    PRICE_OUTPUT_PER_M = 4.0
    PRICE_CACHED_PER_M = 0.1

    def add(self, input_tok: int, output_tok: int, cached_tok: int = 0):
        with self._lock:
            self.input_tokens += input_tok
            self.output_tokens += output_tok
            self.cached_tokens += cached_tok
            self.api_calls += 1

    def add_failure(self):
        with self._lock:
            self.failed_calls += 1

    @property
    def total_tokens(self):
        return self.input_tokens + self.output_tokens

    @property
    def cost_yuan(self):
        cost = (
            (self.input_tokens - self.cached_tokens) * self.PRICE_INPUT_PER_M / 1_000_000 +
            self.output_tokens * self.PRICE_OUTPUT_PER_M / 1_000_000 +
            self.cached_tokens * self.PRICE_CACHED_PER_M / 1_000_000
        )
        return cost

    def summary(self) -> str:
        return (
            f"Token Stats:\n"
            f"   Input: {self.input_tokens:,} tokens\n"
            f"   Output: {self.output_tokens:,} tokens\n"
            f"   Cache hit: {self.cached_tokens:,} tokens\n"
            f"   API calls: {self.api_calls} (failed {self.failed_calls})\n"
            f"   Est. cost: Y{self.cost_yuan:.3f}"
        )


# ============================================================
# CHAPTER / HEADING DETECTION
# ============================================================

@dataclass
class HeadingInfo:
    """Stores detected heading information."""
    page_num: int
    text: str
    level: int
    y_position: float


class ChapterDetector:
    """Detects chapter/section headings by analyzing font size and weight."""

    def __init__(self):
        self.headings: list[HeadingInfo] = []
        self._font_sizes: list[float] = []

    def analyze_page(self, page_num: int, page_dict: dict):
        blocks = page_dict.get("blocks", [])
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                line_text = "".join(s["text"] for s in spans).strip()
                if not line_text or len(line_text) < 2:
                    continue
                avg_size = sum(s["size"] for s in spans) / len(spans)
                is_bold = any(s["flags"] & 2 for s in spans)
                is_all_caps = line_text == line_text.upper() and line_text != line_text.lower()
                self._font_sizes.append(avg_size)
                bbox = line.get("bbox", block["bbox"])
                h = HeadingInfo(page_num=page_num, text=line_text, level=0, y_position=bbox[1])
                h._size = avg_size
                h._bold = is_bold
                h._caps = is_all_caps
                self.headings.append(h)

    def finalize(self):
        if not self._font_sizes:
            self.headings = []
            return
        sizes = sorted(self._font_sizes)
        median_size = sizes[len(sizes) // 2]
        real_headings = []
        for h in self.headings:
            size = getattr(h, "_size", 0)
            bold = getattr(h, "_bold", False)
            caps = getattr(h, "_caps", False)
            if size >= median_size * 1.3:
                if size >= median_size * 1.8:
                    h.level = 1
                elif size >= median_size * 1.4:
                    h.level = 2
                else:
                    h.level = 3
                real_headings.append(h)
            elif bold and caps and size >= median_size * 1.1:
                h.level = 2
                real_headings.append(h)
        self.headings = real_headings

    def get_toc_markdown(self) -> str:
        if not self.headings:
            return ""
        lines = ["## Table of Contents\n"]
        for h in self.headings:
            indent = "  " * (h.level - 1)
            lines.append(f"{indent}- [{h.text}](#page-{h.page_num + 1})")
        lines.append("")
        return "\n".join(lines)

    def get_heading_for_page(self, page_num: int) -> Optional[str]:
        page_headings = [h for h in self.headings if h.page_num == page_num]
        if page_headings:
            return min(page_headings, key=lambda h: h.level).text
        return None


# ============================================================
# PDF TEXT EXTRACTION
# ============================================================

class PDFExtractor:
    """Extracts text from dual-column TRPG PDFs with intelligent layout detection."""

    def __init__(self, pdf_path: str):
        self.doc = pymupdf.open(pdf_path)
        self.total_pages = len(self.doc)
        self.chapter_detector = ChapterDetector()

    def _detect_columns(self, blocks, page_width):
        if not blocks:
            return None
        x_midpoints = []
        for b in blocks:
            if b.get("type") == 0:
                x_mid = (b["bbox"][0] + b["bbox"][2]) / 2
                x_midpoints.append(x_mid)
        if not x_midpoints:
            return None
        page_center = page_width / 2
        left_count = sum(1 for x in x_midpoints if x < page_center * 0.85)
        right_count = sum(1 for x in x_midpoints if x > page_center * 1.15)
        if left_count >= 2 and right_count >= 2:
            return page_center
        return None

    def _sort_blocks_by_column(self, blocks, split_x):
        left_blocks = []
        right_blocks = []
        for b in blocks:
            if b.get("type") != 0:
                continue
            block_center_x = (b["bbox"][0] + b["bbox"][2]) / 2
            if block_center_x < split_x:
                left_blocks.append(b)
            else:
                right_blocks.append(b)
        left_blocks.sort(key=lambda b: b["bbox"][1])
        right_blocks.sort(key=lambda b: b["bbox"][1])
        return left_blocks + right_blocks

    def _extract_block_text(self, block):
        lines = []
        for line in block.get("lines", []):
            line_text = ""
            for span in line.get("spans", []):
                line_text += span["text"]
            lines.append(line_text.strip())
        return " ".join(lines)

    def _is_header_footer(self, block, page_height, margin_ratio=0.06):
        top_margin = page_height * margin_ratio
        bottom_margin = page_height * (1 - margin_ratio)
        block_y = block["bbox"][1]
        block_y_bottom = block["bbox"][3]
        if block_y > bottom_margin:
            text = self._extract_block_text(block)
            if len(text.strip()) < 60:
                return True
        if block_y_bottom < top_margin:
            text = self._extract_block_text(block)
            if len(text.strip()) < 80:
                return True
        return False

    def _clean_text(self, text):
        text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
        text = re.sub(r"  +", " ", text)
        text = re.sub(r"^\s*\d{1,3}\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def extract_page(self, page_num: int) -> str:
        page = self.doc[page_num]
        page_width = page.rect.width
        page_height = page.rect.height
        page_dict = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
        blocks = page_dict.get("blocks", [])
        self.chapter_detector.analyze_page(page_num, page_dict)
        if not blocks:
            return ""
        content_blocks = [
            b for b in blocks
            if b.get("type") == 0 and not self._is_header_footer(b, page_height)
        ]
        if not content_blocks:
            return ""
        split_x = self._detect_columns(content_blocks, page_width)
        if split_x:
            sorted_blocks = self._sort_blocks_by_column(content_blocks, split_x)
        else:
            sorted_blocks = sorted(content_blocks, key=lambda b: b["bbox"][1])
        paragraphs = []
        for block in sorted_blocks:
            text = self._extract_block_text(block)
            if text.strip():
                paragraphs.append(text)
        full_text = "\n\n".join(paragraphs)
        return self._clean_text(full_text)

    def finalize_chapters(self):
        self.chapter_detector.finalize()

    def close(self):
        self.doc.close()


# ============================================================
# GLOSSARY LOADER
# ============================================================

def load_glossary(glossary_path: str) -> dict:
    glossary = {}
    if not glossary_path or not os.path.exists(glossary_path):
        return glossary
    with open(glossary_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "\t" in line:
                parts = line.split("\t", 1)
            else:
                continue
            if len(parts) == 2:
                chinese = parts[0].strip()
                english = parts[1].strip()
                if english and chinese:
                    glossary[english] = chinese
    return glossary


# ============================================================
# TRANSLATOR — DeepSeek V4 API with Context Window
# ============================================================

class Translator:
    """Translates text using DeepSeek V4 API with context window and cost tracking."""

    SYSTEM_PROMPT = """You are a professional TRPG translator working on Delta Green: THE MILLENNIUM.

Translation rules:
1. Follow the glossary strictly for proper nouns.
2. Keep untranslated: dice notations (1D6, 3D6), attributes (STR, CON, DEX, INT, POW, CHA, SAN, WP, HP), skill checks (1/1D6 SAN), abbreviations (FBI, CIA, MJ-12, A-Cell).
3. Output in Markdown format with ## headings, - bullet lists, paragraph spacing.
4. Professional, fluent Chinese. Maintain horror atmosphere. Precise rule descriptions.
5. If OCR errors/garbled text exists, infer meaning from context. Mark unreadable as [damaged].
6. If previous context is provided, ensure continuity. Do not re-translate previous content.

{glossary_section}"""

    def __init__(self, api_key: str, model: str = "deepseek-v4-pro",
                 base_url: str = "https://api.deepseek.com", stats: TokenStats = None):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.glossary = {}
        self.retry_count = 3
        self.retry_delay = 5
        self.stats = stats or TokenStats()

    def set_glossary(self, glossary: dict):
        self.glossary = glossary

    def _build_glossary_for_chunk(self, text: str) -> str:
        if not self.glossary:
            return ""
        relevant = {}
        text_lower = text.lower()
        for eng, chn in self.glossary.items():
            if eng.lower() in text_lower:
                relevant[eng] = chn
        if not relevant:
            return ""
        glossary_lines = [f"   - {eng} -> {chn}" for eng, chn in relevant.items()]
        return "\nGlossary (this section):\n" + "\n".join(glossary_lines)

    def translate_chunk(self, text: str, page_num: int = None, prev_context: str = "") -> str:
        if not text.strip():
            return ""
        glossary_section = self._build_glossary_for_chunk(text)
        system_prompt = self.SYSTEM_PROMPT.format(glossary_section=glossary_section)

        page_info = f" (page {page_num + 1})" if page_num is not None else ""
        if prev_context:
            user_prompt = (
                f"[Previous context - DO NOT translate, for reference only]\n"
                f"{prev_context}\n\n---\n\n"
                f"Translate the following{page_info}:\n\n{text}"
            )
        else:
            user_prompt = f"Translate the following{page_info}:\n\n{text}"

        for attempt in range(self.retry_count):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=4096,
                )
                usage = response.usage
                if usage:
                    cached = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
                    self.stats.add(usage.prompt_tokens, usage.completion_tokens, cached)
                return response.choices[0].message.content.strip()
            except Exception as e:
                self.stats.add_failure()
                if attempt < self.retry_count - 1:
                    wait = self.retry_delay * (attempt + 1)
                    print(f"\n  API error (attempt {attempt+1}/{self.retry_count}): {e}")
                    print(f"     Retrying in {wait}s...", end="", flush=True)
                    time.sleep(wait)
                else:
                    print(f"\n  API failed permanently: {e}")
                    return f"[Translation failed: {e}]\n\nOriginal:\n{text[:200]}..."
        return ""


# ============================================================
# PROGRESS TRACKER
# ============================================================

class ProgressTracker:
    def __init__(self, progress_file: str):
        self.progress_file = progress_file
        self.completed_pages = set()
        self.translations = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.completed_pages = set(data.get("completed_pages", []))
                self.translations = data.get("translations", {})
                print(f"Loaded progress: {len(self.completed_pages)} pages done")
            except (json.JSONDecodeError, IOError):
                print("Progress file corrupted, starting fresh")

    def save(self):
        with self._lock:
            data = {"completed_pages": sorted(self.completed_pages), "translations": self.translations}
            with open(self.progress_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def is_completed(self, page_num: int) -> bool:
        return page_num in self.completed_pages

    def mark_completed(self, page_num: int, translation: str):
        with self._lock:
            self.completed_pages.add(page_num)
            self.translations[str(page_num)] = translation
        self.save()

    def get_translation(self, page_num: int) -> str:
        return self.translations.get(str(page_num), "")


# ============================================================
# PDF OVERLAY OUTPUT
# ============================================================

class PDFOverlayWriter:
    """Writes translated text over the original PDF, preserving layout."""

    def __init__(self, source_pdf_path: str, output_pdf_path: str):
        self.source_path = source_pdf_path
        self.output_path = output_pdf_path
        self.doc = pymupdf.open(source_pdf_path)

    def overlay_page(self, page_num: int, translated_text: str):
        page = self.doc[page_num]
        page_dict = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
        blocks = page_dict.get("blocks", [])
        text_blocks = [b for b in blocks if b.get("type") == 0]
        if not text_blocks:
            return

        translated_paragraphs = [p.strip() for p in translated_text.split("\n") if p.strip()]
        clean_paragraphs = []
        for p in translated_paragraphs:
            p = re.sub(r"^#{1,4}\s*", "", p)
            p = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", p)
            if p.strip() == "---" or p.startswith("<!--"):
                continue
            if p.strip():
                clean_paragraphs.append(p)

        para_idx = 0
        for block in text_blocks:
            if para_idx >= len(clean_paragraphs):
                break
            bbox = block["bbox"]
            x0, y0, x1, y1 = bbox
            orig_size = 10
            if block.get("lines"):
                spans = block["lines"][0].get("spans", [])
                if spans:
                    orig_size = spans[0].get("size", 10)
            font_size = min(orig_size * 0.85, 9)
            font_size = max(font_size, 6)

            rect = pymupdf.Rect(x0, y0, x1, y1)
            page.draw_rect(rect, color=None, fill=(1, 1, 1))

            text_to_insert = clean_paragraphs[para_idx]
            try:
                avail_width = x1 - x0 - 4
                if avail_width < 20:
                    para_idx += 1
                    continue
                tw = pymupdf.TextWriter(page.rect)
                font = pymupdf.Font("china-s")
                tw.append((x0 + 2, y0 + font_size + 2), text_to_insert, font=font, fontsize=font_size)
                tw.write_text(page)
            except Exception:
                try:
                    page.insert_text((x0 + 2, y0 + font_size + 2), text_to_insert[:100],
                                     fontsize=font_size, fontname="china-s")
                except Exception:
                    pass
            para_idx += 1

    def save(self):
        self.doc.save(self.output_path, garbage=4, deflate=True)
        self.doc.close()


# ============================================================
# BATCH CONCURRENT TRANSLATOR
# ============================================================

def translate_batch_concurrent(pages_data, translator, tracker, max_workers=4):
    results = {}

    def translate_one(page_num, text, prev_ctx):
        translation = translator.translate_chunk(text, page_num, prev_ctx)
        if translation:
            tracker.mark_completed(page_num, translation)
        return page_num, translation

    group_size = max_workers
    prev_context = ""

    for group_start in range(0, len(pages_data), group_size):
        group = pages_data[group_start:group_start + group_size]
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for page_num, text, _ in group:
                if tracker.is_completed(page_num):
                    results[page_num] = tracker.get_translation(page_num)
                    continue
                if not text.strip():
                    tracker.mark_completed(page_num, "")
                    results[page_num] = ""
                    continue
                future = executor.submit(translate_one, page_num, text, prev_context)
                futures[future] = page_num

            for future in as_completed(futures):
                page_num, translation = future.result()
                results[page_num] = translation or ""
                print(f" p{page_num + 1} done", end="", flush=True)

        if group:
            last_page_num = group[-1][0]
            last_translation = results.get(last_page_num, "")
            if last_translation:
                prev_context = last_translation[-300:]
        print()

    return results


# ============================================================
# MAIN ORCHESTRATOR
# ============================================================

def translate_pdf(pdf_path, output_path, api_key, glossary_path=None,
                  model="deepseek-v4-pro", start_page=0, end_page=None,
                  output_format="markdown", max_workers=1):
    print("=" * 60)
    print("  DG TRPG PDF Translator v2.0 - THE MILLENNIUM")
    print("=" * 60)
    print()

    stats = TokenStats()

    print(f"Opening PDF: {pdf_path}")
    extractor = PDFExtractor(pdf_path)
    total = extractor.total_pages
    print(f"   Total pages: {total}")

    if end_page is None or end_page > total:
        end_page = total
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

    print(f"Engine: DeepSeek V4 ({model})")
    translator = Translator(api_key=api_key, model=model, stats=stats)
    translator.set_glossary(glossary)
    print()

    progress_file = output_path + ".progress.json"
    tracker = ProgressTracker(progress_file)
    print()

    print("Extracting text and analyzing chapters...")
    pages_text = {}
    for page_num in range(start_page, end_page):
        text = extractor.extract_page(page_num)
        pages_text[page_num] = text

    extractor.finalize_chapters()
    toc = extractor.chapter_detector.get_toc_markdown()
    if toc:
        print(f"   Detected {len(extractor.chapter_detector.headings)} headings")
    else:
        print("   No clear chapter structure detected")
    print()

    print("Translating...")
    print("-" * 40)
    start_time = time.time()

    if max_workers > 1:
        print(f"   Concurrent mode: {max_workers} workers")
        pages_data = []
        prev_text = ""
        for page_num in range(start_page, end_page):
            text = pages_text.get(page_num, "")
            context = prev_text[-300:] if prev_text else ""
            pages_data.append((page_num, text, context))
            if text.strip():
                prev_text = text
        results = translate_batch_concurrent(pages_data, translator, tracker, max_workers)
        translated_pages = [(pn, t) for pn, t in results.items() if t.strip()]
    else:
        translated_pages = []
        prev_translation_tail = ""
        pages_to_process = list(range(start_page, end_page))
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
            translation = translator.translate_chunk(text, page_num, prev_context=prev_translation_tail)

            if translation:
                translated_pages.append((page_num, translation))
                tracker.mark_completed(page_num, translation)
                prev_translation_tail = translation[-300:]
                print(f" done (Y{stats.cost_yuan:.3f})")
            else:
                print(f" empty result")
                tracker.mark_completed(page_num, "")
            time.sleep(0.3)

    elapsed = time.time() - start_time
    print("-" * 40)
    print()

    translated_pages_sorted = sorted(translated_pages, key=lambda x: x[0])

    if output_format in ("pdf", "both"):
        pdf_output = output_path if output_path.endswith(".pdf") else output_path.replace(".md", ".pdf")
        print(f"Generating overlay PDF: {pdf_output}")
        try:
            writer = PDFOverlayWriter(pdf_path, pdf_output)
            for page_num, translation in translated_pages_sorted:
                writer.overlay_page(page_num, translation)
            writer.save()
            print("   PDF output done")
        except Exception as e:
            print(f"   PDF output failed: {e}")
            print("   Falling back to markdown")
            output_format = "markdown"

    if output_format in ("markdown", "both"):
        md_output = output_path if output_path.endswith(".md") else output_path
        print(f"Generating Markdown: {md_output}")
        with open(md_output, "w", encoding="utf-8") as f:
            f.write("# THE MILLENNIUM - Chinese Translation\n\n")
            f.write("> Translated by DeepSeek V4 AI with Delta Green glossary\n\n")
            f.write("---\n\n")
            if toc:
                f.write(toc)
                f.write("\n---\n\n")
            for page_num, translation in translated_pages_sorted:
                if translation.strip():
                    f.write(f'<a id="page-{page_num + 1}"></a>\n\n')
                    f.write(f"<!-- Page {page_num + 1} -->\n\n")
                    f.write(translation)
                    f.write("\n\n---\n\n")
        page_count = len([t for _, t in translated_pages_sorted if t.strip()])
        print(f"   Done! {page_count} pages translated")

    print()
    print(f"Time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print()
    print(stats.summary())
    print()
    print(f"Progress file: {progress_file}")
    print(f"Output: {output_path}")

    extractor.close()


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="DG TRPG PDF Translator v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx --workers 4 --glossary glossary.tsv
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx --format pdf
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx --format both --workers 4
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx --start 10 --end 50
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx --model deepseek-v4-flash --workers 8
        """
    )

    parser.add_argument("pdf", help="Input PDF file path")
    parser.add_argument("--api-key", required=True, help="DeepSeek API Key")
    parser.add_argument("--output", "-o", default=None, help="Output file path")
    parser.add_argument("--glossary", "-g", default=None, help="Glossary TSV file path")
    parser.add_argument("--model", default="deepseek-v4-pro", help="Model name (default: deepseek-v4-pro)")
    parser.add_argument("--format", "-f", choices=["markdown", "pdf", "both"], default="markdown",
                        help="Output format (default: markdown)")
    parser.add_argument("--workers", "-w", type=int, default=1, help="Concurrent workers (default: 1, recommended: 4)")
    parser.add_argument("--start", type=int, default=0, help="Start page (0-indexed)")
    parser.add_argument("--end", type=int, default=None, help="End page (exclusive)")

    args = parser.parse_args()

    if args.output is None:
        pdf_stem = Path(args.pdf).stem
        if args.format == "pdf":
            args.output = f"{pdf_stem}_cn.pdf"
        else:
            args.output = f"{pdf_stem}_cn.md"

    if not os.path.exists(args.pdf):
        print(f"PDF not found: {args.pdf}")
        sys.exit(1)

    if args.workers < 1:
        args.workers = 1
    elif args.workers > 16:
        print("Max workers is 16")
        args.workers = 16

    translate_pdf(
        pdf_path=args.pdf,
        output_path=args.output,
        api_key=args.api_key,
        glossary_path=args.glossary,
        model=args.model,
        start_page=args.start,
        end_page=args.end,
        output_format=args.format,
        max_workers=args.workers,
    )


if __name__ == "__main__":
    main()
