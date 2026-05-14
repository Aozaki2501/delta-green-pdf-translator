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

try:
    from docx import Document as DocxDocument
    from docx.shared import Pt, Inches, Mm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.section import WD_SECTION
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False


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

    def _sort_blocks_layout_aware(self, blocks, page_width):
        sorted_input = sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))
        non_full_blocks = [
            b for b in sorted_input
            if b.get("type") == 0 and (b["bbox"][2] - b["bbox"][0]) <= page_width * 0.6
        ]
        left_count = sum(
            1 for b in non_full_blocks
            if ((b["bbox"][0] + b["bbox"][2]) / 2) < page_width / 2
        )
        right_count = len(non_full_blocks) - left_count
        if left_count < 2 or right_count < 2:
            return sorted_input

        output_blocks = []
        left_blocks = []
        right_blocks = []

        def flush_columns():
            nonlocal left_blocks, right_blocks
            output_blocks.extend(sorted(left_blocks, key=lambda b: b["bbox"][1]))
            output_blocks.extend(sorted(right_blocks, key=lambda b: b["bbox"][1]))
            left_blocks = []
            right_blocks = []

        for block in sorted_input:
            if block.get("type") != 0:
                continue

            x0, _, x1, _ = block["bbox"]
            block_width = x1 - x0
            is_full_width = block_width > page_width * 0.6

            if is_full_width:
                flush_columns()
                output_blocks.append(block)
                continue

            block_center_x = (x0 + x1) / 2
            if block_center_x < page_width / 2:
                left_blocks.append(block)
            else:
                right_blocks.append(block)

        flush_columns()
        return output_blocks

    def _extract_block_text(self, block):
        lines = []
        for line in block.get("lines", []):
            spans_text = []
            last_span_norm = ""
            for span in line.get("spans", []):
                span_text = span["text"]
                span_norm = re.sub(r"\s+", " ", span_text).strip().lower()
                if span_norm and span_norm == last_span_norm:
                    continue
                spans_text.append(span_text)
                last_span_norm = span_norm
            line_text = "".join(spans_text).strip()
            if line_text and (not lines or line_text != lines[-1]):
                lines.append(line_text)
        return " ".join(lines)

    def _is_header_footer(self, block, page_height, margin_ratio=0.08):
        top_margin = page_height * margin_ratio
        bottom_margin = page_height * (1 - margin_ratio)
        block_y = block["bbox"][1]
        block_y_bottom = block["bbox"][3]
        text = self._extract_block_text(block).strip()
        if not text:
            return True

        compact = re.sub(r"\s+", " ", text)
        normalized = re.sub(r"[^A-Z0-9 ]+", "", compact.upper()).strip()
        in_top = block_y_bottom < top_margin
        in_bottom = block_y > bottom_margin
        in_margin = in_top or in_bottom

        if re.fullmatch(r"\d{1,4}", compact):
            return True

        running_titles = ("DELTA GREEN", "PISCES", "THE MILLENNIUM")
        if in_margin and any(title in normalized for title in running_titles):
            return True

        if in_margin and len(compact) <= 80:
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
        sorted_blocks = self._sort_blocks_layout_aware(content_blocks, page_width)
        paragraphs = []
        current_para = ""

        for block in sorted_blocks:
            text = self._extract_block_text(block).strip()
            if not text:
                continue

            if not current_para:
                current_para = text
                continue

            current_tail = current_para.rstrip()
            first_alpha = re.search(r"[A-Za-z]", text)
            starts_lower = bool(first_alpha and first_alpha.group(0).islower())
            joins_from_punctuation = current_tail.endswith((",", ":", ";", "—", "-"))

            if joins_from_punctuation or starts_lower:
                if current_tail.endswith("-"):
                    current_para = current_tail[:-1].rstrip() + text
                else:
                    current_para = current_tail + " " + text
            else:
                paragraphs.append(current_para)
                current_para = text

        if current_para:
            paragraphs.append(current_para)

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
                parts = re.split(r"\s{2,}", line, maxsplit=1)
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

    SYSTEM_PROMPT = """You are a professional TRPG translator working on Delta Green sourcebooks.

Translation rules:
1. Follow the glossary strictly for proper nouns. If glossary entries overlap, the longest matching phrase wins.
2. Keep untranslated: dice notations (1D6, 3D6), attributes (STR, CON, DEX, INT, POW, CHA, SAN, WP, HP), skill checks (1/1D6 SAN), abbreviations (FBI, CIA, MJ-12, A-Cell).
3. Output in Markdown format with ## headings, - bullet lists, paragraph spacing.
4. Professional, fluent Chinese. Maintain horror atmosphere. Precise rule descriptions.
5. Keep the Chinese translation concise. Do not expand, explain, embellish, or add information not present in the source.
6. Do not translate page headers, footers, page numbers, or running titles such as DELTA GREEN, PISCES, and THE MILLENNIUM when they appear as standalone navigation text.
7. Preserve section and subsection headings. Output article titles as ## headings and smaller section headings as ### headings.
8. If decorative title-card text, drop shadows, or stylized text is extracted twice, translate it only once.
9. If OCR errors/garbled text exists, infer meaning from context. Mark unreadable as [damaged].
10. If previous context is provided, ensure continuity. Do not re-translate previous content.

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
        relevant = self._find_relevant_glossary_terms(text)
        if not relevant:
            return ""
        glossary_lines = [f"   - {eng} -> {chn}" for eng, chn in relevant.items()]
        return "\nGlossary (this section):\n" + "\n".join(glossary_lines)

    def _find_relevant_glossary_terms(self, text: str) -> dict:
        matches = []
        for eng, chn in sorted(self.glossary.items(), key=lambda item: len(item[0]), reverse=True):
            pattern = re.compile(
                r"(?<![A-Za-z0-9])" + re.escape(eng) + r"(?![A-Za-z0-9])",
                re.IGNORECASE,
            )
            for match in pattern.finditer(text):
                matches.append((match.start(), match.end(), eng, chn))

        selected = []
        occupied_spans = []
        for start, end, eng, chn in matches:
            if any(start < occupied_end and end > occupied_start for occupied_start, occupied_end in occupied_spans):
                continue
            selected.append((eng, chn))
            occupied_spans.append((start, end))

        relevant = {}
        for eng, chn in selected:
            relevant[eng] = chn
        return relevant

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

def translate_batch_concurrent(pages_data, translator, tracker, max_workers=4, progress_callback=None):
    results = {}
    completed_count = 0
    total_count = len(pages_data)

    def report(page_num, translation):
        nonlocal completed_count
        completed_count += 1
        if progress_callback:
            progress_callback(page_num, translation or "", completed_count, total_count)

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
            for page_num, text, page_context in group:
                if tracker.is_completed(page_num):
                    translation = tracker.get_translation(page_num)
                    results[page_num] = translation
                    report(page_num, translation)
                    continue
                if not text.strip():
                    tracker.mark_completed(page_num, "")
                    results[page_num] = ""
                    report(page_num, "")
                    continue
                future = executor.submit(translate_one, page_num, text, prev_context or page_context)
                futures[future] = page_num

            for future in as_completed(futures):
                page_num, translation = future.result()
                results[page_num] = translation or ""
                report(page_num, translation)
                print(f" p{page_num + 1} done", end="", flush=True)

        if group:
            last_page_num = group[-1][0]
            last_translation = results.get(last_page_num, "")
            if last_translation:
                prev_context = last_translation[-300:]
        print()

    return results
def set_section_columns(section, num=2, space_twips=720):
    """
    设置 Word 分栏。
    space_twips=720 约等于 0.5 英寸，可按需要调小到 360。
    """
    sectPr = section._sectPr
    cols = sectPr.xpath("./w:cols")
    if cols:
        cols = cols[0]
    else:
        cols = OxmlElement("w:cols")
        sectPr.append(cols)

    cols.set(qn("w:num"), str(num))
    cols.set(qn("w:space"), str(space_twips))


def set_section_page_layout(section, columns=1):
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)

    section.top_margin = Inches(0.55)
    section.bottom_margin = Inches(0.55)
    section.left_margin = Inches(0.45)
    section.right_margin = Inches(0.45)

    set_section_columns(section, num=columns, space_twips=620)


def set_document_base_layout(doc, columns=1):
    set_section_page_layout(doc.sections[0], columns=columns)

    styles = doc.styles

    # 正文
    normal = styles["Normal"]
    normal.font.name = "宋体"
    normal.font.size = Pt(9)
    normal.paragraph_format.first_line_indent = Pt(12)
    normal.paragraph_format.line_spacing = 1.02
    normal.paragraph_format.space_after = Pt(3)
    # 一级标题
    h1 = styles["Heading 1"]
    h1.font.name = "黑体"
    h1._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    h1.font.size = Pt(18)
    h1.font.bold = False
    h1.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    h1.paragraph_format.space_before = Pt(10)
    h1.paragraph_format.space_after = Pt(8)
    h1.paragraph_format.keep_with_next = True

    # 二级标题
    h2 = styles["Heading 2"]
    h2.font.name = "黑体"
    h2._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    h2.font.size = Pt(14)
    h2.font.bold = True
    h2.font.color.rgb = RGBColor(0xD8, 0x00, 0x00)
    h2.paragraph_format.space_before = Pt(8)
    h2.paragraph_format.space_after = Pt(4)
    h2.paragraph_format.keep_with_next = True

    # 三级标题
    h3 = styles["Heading 3"]
    h3.font.name = "黑体"
    h3._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    h3.font.size = Pt(11)
    h3.font.bold = True
    h3.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    h3.paragraph_format.space_before = Pt(6)
    h3.paragraph_format.space_after = Pt(3)
    h3.paragraph_format.keep_with_next = True

    # 项目符号
    if "List Bullet" in styles:
        bullet = styles["List Bullet"]
        bullet.font.name = "宋体"
        bullet._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        bullet.font.size = Pt(9.2)
        bullet.paragraph_format.left_indent = Pt(14)
        bullet.paragraph_format.first_line_indent = Pt(-8)
        bullet.paragraph_format.space_after = Pt(2)


def _translation_blocks(translated_pages):
    blocks = []
    for page_num, translation in translated_pages:
        if not translation.strip():
            continue
        chunks = re.split(r"\n\s*\n", translation)
        for chunk in chunks:
            text = _clean_translated_block(chunk.strip())
            if not text or text == "---" or text.startswith("<!--"):
                continue
            blocks.append({"source_page": page_num, "text": text})
    return blocks


def _clean_translated_block(text: str) -> str:
    lines = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        line = _clean_decorative_slash_line(line)
        lines.append(line)

    text = "\n".join(lines)
    text = _dedupe_adjacent_repeated_units(text)
    return text.strip()


def _clean_decorative_slash_line(line: str) -> str:
    if line.count("//") < 2:
        return line

    parts = [p.strip(" /") for p in line.split("//") if p.strip(" /")]
    if not parts:
        return line

    unique_parts = []
    for part in parts:
        normalized = re.sub(r"\s+", "", part).lower()
        if unique_parts and normalized == re.sub(r"\s+", "", unique_parts[-1]).lower():
            continue
        unique_parts.append(part)

    if len(unique_parts) == len(parts):
        return line
    return "// " + " / ".join(unique_parts) + " //"


def _dedupe_adjacent_repeated_units(text: str) -> str:
    patterns = [
        r"([“\"][^”\"\n]{2,120}[”\"])(?:\s*[，,、]?\s*\1)+",
        r"(——[^—\n]{2,60})(?:\s+\1)+",
        r"([^。！？!?\n]{2,120}[。！？!?])(?:\s*\1)+",
    ]
    previous = None
    while previous != text:
        previous = text
        for pattern in patterns:
            text = re.sub(pattern, r"\1", text)
    return text


def _visible_text_length(text: str) -> int:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"\s+", "", text)
    return len(text)


def _is_markdown_heading(text: str) -> bool:
    return bool(re.match(r"^#{1,6}\s+", text.strip()))


def _is_plain_heading_line(text: str) -> bool:
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", text.strip())
    clean = re.sub(r"\*(.+?)\*", r"\1", clean)
    if clean.startswith(("#", "-", "\u2022", "//", "——", "“", "\"")):
        return False
    visible = re.sub(r"\s+", "", clean)
    if not (2 <= len(visible) <= 18):
        return False
    if re.search(r"[。！？!?；;：:，,、（）()《》\"“”]", clean):
        return False
    if re.search(r"\d", clean):
        return False
    return True


def _format_page_ranges(page_nums):
    nums = sorted({p + 1 for p in page_nums})
    if not nums:
        return ""
    ranges = []
    start = prev = nums[0]
    for num in nums[1:]:
        if num == prev + 1:
            prev = num
            continue
        ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
        start = prev = num
    ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(ranges)


def paginate_translated_blocks(translated_pages, min_chars=1000, max_chars=1500):
    """Group translated Markdown blocks into reading pages without splitting blocks."""
    pages = []
    current = []
    current_len = 0

    def flush():
        nonlocal current, current_len
        if current:
            pages.append(current)
            current = []
            current_len = 0

    for block in _translation_blocks(translated_pages):
        block_len = _visible_text_length(block["text"])
        starts_heading = _is_markdown_heading(block["text"])

        if starts_heading and current and current_len >= min_chars:
            flush()
        elif current and current_len + block_len > max_chars and current_len >= min_chars:
            flush()

        current.append(block)
        current_len += block_len

    flush()
    return pages


def write_markdown_output(translated_pages, md_output: str, title: str, toc: str = "",
                          min_chars=1000, max_chars=1500):
    reading_pages = paginate_translated_blocks(translated_pages, min_chars, max_chars)
    with open(md_output, "w", encoding="utf-8") as f:
        f.write(f"# {title} — 中文翻译\n\n---\n\n")

        if toc:
            f.write(toc)
            f.write("\n---\n\n")

        for page_idx, blocks in enumerate(reading_pages, 1):
            source_pages = _format_page_ranges([b["source_page"] for b in blocks])
            f.write(f"<!-- Reading Page {page_idx}; Source PDF Pages: {source_pages} -->\n\n")
            for block in blocks:
                f.write(_format_markdown_block(block["text"]))
                f.write("\n\n")
            f.write("---\n\n")


def _format_markdown_block(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if _is_plain_heading_line(stripped):
            lines.append(f"### {stripped}")
        else:
            lines.append(line)
    return "\n".join(lines)


def _write_word_block(doc, text: str):
    for line in text.split("\n"):
        line = line.strip()
        if not line or line == "---" or line.startswith("<!--"):
            continue

        clean_line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        clean_line = re.sub(r"\*(.+?)\*", r"\1", clean_line)

        if clean_line.startswith("### "):
            p = doc.add_heading(clean_line[4:], level=3)
            p.paragraph_format.first_line_indent = Pt(0)
        elif clean_line.startswith("## "):
            p = doc.add_heading(clean_line[3:], level=2)
            p.paragraph_format.first_line_indent = Pt(0)
        elif clean_line.startswith("# "):
            p = doc.add_heading(clean_line[2:], level=1)
            p.paragraph_format.first_line_indent = Pt(0)
        elif _is_plain_heading_line(clean_line):
            p = doc.add_heading(clean_line, level=2)
            p.paragraph_format.first_line_indent = Pt(0)
        elif clean_line.startswith("- ") or clean_line.startswith("\u2022 "):
            p = doc.add_paragraph(clean_line[2:], style="List Bullet")
            p.paragraph_format.first_line_indent = Pt(-8)
        else:
            doc.add_paragraph(clean_line)


def write_word_output(translated_pages, docx_output: str, title: str, subtitle: str = "\u4e2d\u6587\u7ffb\u8bd1",
                      min_chars=1000, max_chars=1500):
    """Write translated Markdown-like page content to a Word document."""
    if not HAS_DOCX:
        raise RuntimeError("Word output requires python-docx")

    doc = DocxDocument()
    set_document_base_layout(doc)

    title_para = doc.add_heading(title.upper(), level=1)
    title_para.alignment = WD_ALIGN_PARAGRAPH.LEFT

    if subtitle:
        subtitle_para = doc.add_paragraph(subtitle)
        subtitle_para.style = doc.styles["Normal"]
        subtitle_para.paragraph_format.first_line_indent = Pt(0)
        if subtitle_para.runs:
            subtitle_para.runs[0].font.color.rgb = RGBColor(0x2D, 0x73, 0xB9)
            subtitle_para.runs[0].font.bold = True
        doc.add_paragraph()

    body_section = doc.add_section(WD_SECTION.CONTINUOUS)
    set_section_page_layout(body_section, columns=2)

    reading_pages = paginate_translated_blocks(translated_pages, min_chars, max_chars)
    for page_idx, blocks in enumerate(reading_pages):
        if page_idx > 0:
            doc.add_page_break()
        for block in blocks:
            _write_word_block(doc, block["text"])

    doc.save(docx_output)
# ============================================================
# MAIN ORCHESTRATOR
# ============================================================

def translate_pdf(pdf_path, output_path, api_key, glossary_path=None,
                  model="deepseek-v4-pro", start_page=0, end_page=None,
                  output_format="markdown", max_workers=1):
    print("=" * 60)
    print("  DG TRPG PDF Translator v2.0")
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

    # Determine output base name (without extension)
    output_base = output_path
    for ext in (".md", ".pdf", ".docx"):
        if output_base.endswith(ext):
            output_base = output_base[:-len(ext)]
            break

    # PDF output
    if output_format in ("pdf", "both", "all"):
        pdf_output = output_base + ".pdf"
        print(f"  生成保留排版 PDF: {pdf_output}")
        try:
            writer = PDFOverlayWriter(pdf_path, pdf_output)
            for page_num, translation in translated_pages_sorted:
                writer.overlay_page(page_num, translation)
            writer.save()
            print("   ✅ PDF 输出完成")
        except Exception as e:
            print(f"   ❌ PDF 输出失败: {e}")

    # Markdown output
    if output_format in ("markdown", "both", "all"):
        md_output = output_base + ".md"
        print(f"  生成 Markdown: {md_output}")
        write_markdown_output(translated_pages_sorted, md_output, Path(pdf_path).stem, toc)
        print("   ✅ Markdown 输出完成")

    # Word output
    if output_format in ("word", "all"):
        if not HAS_DOCX:
            print("  ⚠️  Word 输出需要 python-docx，请运行: pip install python-docx")
        else:
            docx_output = output_base + ".docx"
            print(f"  生成 Word 文档: {docx_output}")
            try:
                write_word_output(translated_pages_sorted, docx_output, Path(pdf_path).stem)
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
    print(f"Output: {output_path}")

    extractor.close()


# ============================================================
# CLI with Config File Support
# ============================================================

def load_config(config_path: str) -> dict:
    """Load configuration from a JSON file."""
    if not os.path.exists(config_path):
        print(f"❌ 配置文件不存在: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
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
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx --format all --workers 4

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
    parser.add_argument("--format", "-f", choices=["markdown", "pdf", "word", "both", "all"],
                        default=None, help="输出格式: markdown/pdf/word/both/all（默认: markdown）")
    parser.add_argument("--workers", "-w", type=int, default=None,
                        help="并发线程数（默认: 1，推荐: 4）")
    parser.add_argument("--start", type=int, default=None, help="起始页码（从0开始）")
    parser.add_argument("--end", type=int, default=None, help="结束页码（不含）")

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
    output_format = args.format or config.get("format", "markdown")
    workers = args.workers if args.workers is not None else config.get("workers", 1)
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

    # Default output path
    if output_path is None:
        pdf_stem = Path(pdf_path).stem
        output_path = f"{pdf_stem}_cn.md"

    # Validate
    if not os.path.exists(pdf_path):
        print(f"❌ PDF 文件不存在: {pdf_path}")
        sys.exit(1)

    if workers < 1:
        workers = 1
    elif workers > 16:
        print("⚠️  并发数上限为 16，已自动调整")
        workers = 16

    # Run
    translate_pdf(
        pdf_path=pdf_path,
        output_path=output_path,
        api_key=api_key,
        glossary_path=glossary_path,
        model=model,
        start_page=start_page,
        end_page=end_page,
        output_format=output_format,
        max_workers=workers,
    )


if __name__ == "__main__":
    main()
