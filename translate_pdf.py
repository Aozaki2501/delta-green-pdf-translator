#!/usr/bin/env python3
"""
DG TRPG PDF Translator — THE MILLENNIUM
========================================
Translates English PDF (dual-column TRPG layout) to Chinese Markdown
using DeepSeek V4 API with TRPG-specific terminology.

Usage:
    python translate_pdf.py input.pdf --output output.md --api-key YOUR_KEY

Features:
    - Intelligent dual-column text extraction (handles TRPG book layouts)
    - TRPG glossary support (术语表)
    - Breakpoint resume (断点续翻)
    - Progress tracking
    - Markdown structured output
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

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
# PDF TEXT EXTRACTION — Dual Column Handler
# ============================================================

class PDFExtractor:
    """Extracts text from dual-column TRPG PDFs with intelligent layout detection."""

    def __init__(self, pdf_path: str):
        self.doc = pymupdf.open(pdf_path)
        self.total_pages = len(self.doc)

    def _detect_columns(self, blocks, page_width):
        """
        Detect if the page is dual-column by analyzing text block X positions.
        Returns the column split X coordinate, or None if single-column.
        """
        if not blocks:
            return None

        # Get X midpoints of all text blocks
        x_midpoints = []
        for b in blocks:
            if b["type"] == 0:  # text block
                x_mid = (b["bbox"][0] + b["bbox"][2]) / 2
                x_midpoints.append(x_mid)

        if not x_midpoints:
            return None

        # If most blocks cluster into two groups (left half / right half), it's dual-column
        page_center = page_width / 2
        left_count = sum(1 for x in x_midpoints if x < page_center * 0.85)
        right_count = sum(1 for x in x_midpoints if x > page_center * 1.15)

        # If both sides have meaningful content, treat as dual-column
        if left_count >= 2 and right_count >= 2:
            return page_center

        return None

    def _sort_blocks_by_column(self, blocks, split_x):
        """Sort blocks: left column top-to-bottom, then right column top-to-bottom."""
        left_blocks = []
        right_blocks = []

        for b in blocks:
            if b["type"] != 0:  # skip non-text (images, etc.)
                continue
            block_center_x = (b["bbox"][0] + b["bbox"][2]) / 2
            if block_center_x < split_x:
                left_blocks.append(b)
            else:
                right_blocks.append(b)

        # Sort each column by Y position (top to bottom)
        left_blocks.sort(key=lambda b: b["bbox"][1])
        right_blocks.sort(key=lambda b: b["bbox"][1])

        return left_blocks + right_blocks

    def _extract_block_text(self, block):
        """Extract text from a block, preserving paragraph structure."""
        lines = []
        for line in block.get("lines", []):
            line_text = ""
            for span in line.get("spans", []):
                line_text += span["text"]
            lines.append(line_text.strip())
        return " ".join(lines)

    def _is_header_footer(self, block, page_height, margin_ratio=0.06):
        """Check if a block is likely a header or footer (by position)."""
        top_margin = page_height * margin_ratio
        bottom_margin = page_height * (1 - margin_ratio)
        block_y = block["bbox"][1]
        block_y_bottom = block["bbox"][3]

        # Footer detection: very bottom + short text (page number, chapter title)
        if block_y > bottom_margin:
            text = self._extract_block_text(block)
            # Page numbers or very short footer text
            if len(text.strip()) < 60:
                return True

        # Header detection: very top + short text
        if block_y_bottom < top_margin:
            text = self._extract_block_text(block)
            if len(text.strip()) < 80:
                return True

        return False

    def _clean_text(self, text):
        """Clean up common PDF extraction artifacts."""
        # Fix hyphenated line breaks: "Aero-\nspace" -> "Aerospace"
        text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)
        # Collapse multiple spaces
        text = re.sub(r'  +', ' ', text)
        # Remove isolated page numbers on their own line
        text = re.sub(r'^\s*\d{1,3}\s*$', '', text, flags=re.MULTILINE)
        # Clean up extra blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def extract_page(self, page_num: int) -> str:
        """
        Extract text from a single page with intelligent column handling.
        Returns cleaned text with proper reading order.
        """
        page = self.doc[page_num]
        page_width = page.rect.width
        page_height = page.rect.height

        # Get text as dictionary with position info
        page_dict = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
        blocks = page_dict.get("blocks", [])

        if not blocks:
            return ""

        # Filter out headers and footers
        content_blocks = [
            b for b in blocks
            if b["type"] == 0 and not self._is_header_footer(b, page_height)
        ]

        if not content_blocks:
            return ""

        # Detect column layout
        split_x = self._detect_columns({"type": 0, **b} if "type" not in b else b
                                        for b in content_blocks) if False else \
                  self._detect_columns(content_blocks, page_width)

        # Sort blocks by proper reading order
        if split_x:
            sorted_blocks = self._sort_blocks_by_column(content_blocks, split_x)
        else:
            # Single column: just sort top to bottom
            sorted_blocks = sorted(content_blocks, key=lambda b: b["bbox"][1])

        # Extract text from sorted blocks
        paragraphs = []
        for block in sorted_blocks:
            text = self._extract_block_text(block)
            if text.strip():
                paragraphs.append(text)

        # Join and clean
        full_text = "\n\n".join(paragraphs)
        return self._clean_text(full_text)

    def extract_all(self, start_page=0, end_page=None):
        """Extract all pages, returns list of (page_num, text) tuples."""
        if end_page is None:
            end_page = self.total_pages
        end_page = min(end_page, self.total_pages)

        results = []
        for i in range(start_page, end_page):
            text = self.extract_page(i)
            if text.strip():
                results.append((i, text))
        return results

    def close(self):
        self.doc.close()


# ============================================================
# GLOSSARY LOADER
# ============================================================

def load_glossary(glossary_path: str) -> dict:
    """
    Load glossary from a TSV/CSV file.
    Expected format per line: Chinese_term<TAB>English_term
    or: Chinese_term,English_term
    """
    glossary = {}
    if not glossary_path or not os.path.exists(glossary_path):
        return glossary

    with open(glossary_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # Try tab separator first, then comma
            if '\t' in line:
                parts = line.split('\t', 1)
            elif ',' in line:
                parts = line.split(',', 1)
            else:
                continue
            if len(parts) == 2:
                chinese = parts[0].strip()
                english = parts[1].strip()
                if english and chinese:
                    glossary[english] = chinese

    return glossary


# ============================================================
# TRANSLATOR — DeepSeek V4 API
# ============================================================

class Translator:
    """Translates text using DeepSeek V4 API with TRPG-specific prompting."""

    SYSTEM_PROMPT = """你是一位专业的桌面角色扮演游戏（TRPG）翻译专家，正在翻译《绿色三角洲（Delta Green）》的扩展规则书《THE MILLENNIUM》。

## 翻译要求

1. **术语规范**：严格按照提供的术语表翻译专有名词。术语表中未出现的专名，首次出现时使用"中文译名（English）"格式，之后可仅用中文。

2. **保持不翻译的内容**：
   - 所有骰子记法：1D4, 1D6, 1D8, 1D10, 1D12, 1D20, 1D100, 2D6, 3D6 等
   - 所有属性缩写：STR, CON, DEX, INT, POW, CHA, SAN, WP, HP
   - 所有技能检定格式：如 "1/1D6 SAN", "SAN loss 1/1D10"
   - 英文缩写和代号：如 FBI, CIA, NSA, MJ-12, A-Cell 等

3. **格式要求**：
   - 输出为 Markdown 格式
   - 章节标题用 ## 或 ### 标记
   - 项目符号条目保持列表格式（用 - 或 •）
   - 游戏机制数据（伤害、属性值等）保持原格式
   - 段落之间用空行分隔

4. **翻译风格**：
   - 使用专业但流畅的中文，避免翻译腔
   - 恐怖/超自然描述保持原文氛围
   - 规则说明要精确清晰

5. **文本质量问题处理**：
   - 如果原文有明显的OCR错误或乱码（如字母随机混合），请根据上下文推断正确含义并翻译
   - 如果某段完全无法辨认，标注为 [原文损坏，无法翻译]

{glossary_section}"""

    def __init__(self, api_key: str, model: str = "deepseek-v4-pro",
                 base_url: str = "https://api.deepseek.com"):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.glossary = {}
        self.retry_count = 3
        self.retry_delay = 5  # seconds

    def set_glossary(self, glossary: dict):
        """Set the glossary for translation."""
        self.glossary = glossary

    def _build_system_prompt(self) -> str:
        """Build the system prompt with glossary."""
        if self.glossary:
            # Include top glossary entries relevant to context
            glossary_lines = [f"   - {eng} → {chn}" for eng, chn in self.glossary.items()]
            glossary_text = "\n".join(glossary_lines)
            glossary_section = f"\n## 术语表\n以下是必须遵循的术语对照：\n{glossary_text}"
        else:
            glossary_section = ""

        return self.SYSTEM_PROMPT.format(glossary_section=glossary_section)

    def _build_glossary_for_chunk(self, text: str) -> str:
        """Build a focused glossary containing only terms that appear in this chunk."""
        if not self.glossary:
            return ""

        relevant = {}
        text_lower = text.lower()
        for eng, chn in self.glossary.items():
            if eng.lower() in text_lower:
                relevant[eng] = chn

        if not relevant:
            return ""

        glossary_lines = [f"   - {eng} → {chn}" for eng, chn in relevant.items()]
        glossary_text = "\n".join(glossary_lines)
        return f"\n## 术语表（本段相关）\n{glossary_text}"

    def translate_chunk(self, text: str, page_num: int = None) -> str:
        """Translate a chunk of text with retry logic."""
        if not text.strip():
            return ""

        # Build focused glossary for this chunk
        glossary_section = self._build_glossary_for_chunk(text)
        system_prompt = self.SYSTEM_PROMPT.format(glossary_section=glossary_section)

        page_info = f"（第 {page_num + 1} 页）" if page_num is not None else ""
        user_prompt = f"请翻译以下内容{page_info}：\n\n{text}"

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
                return response.choices[0].message.content.strip()

            except Exception as e:
                if attempt < self.retry_count - 1:
                    wait = self.retry_delay * (attempt + 1)
                    print(f"  ⚠️  API 调用失败 (尝试 {attempt + 1}/{self.retry_count}): {e}")
                    print(f"     {wait} 秒后重试...")
                    time.sleep(wait)
                else:
                    print(f"  ❌ API 调用最终失败: {e}")
                    return f"[翻译失败: {e}]\n\n原文:\n{text[:200]}..."

        return ""


# ============================================================
# PROGRESS TRACKER — Resume Support
# ============================================================

class ProgressTracker:
    """Tracks translation progress for resume capability."""

    def __init__(self, progress_file: str):
        self.progress_file = progress_file
        self.completed_pages = set()
        self.translations = {}
        self._load()

    def _load(self):
        """Load existing progress."""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.completed_pages = set(data.get("completed_pages", []))
                self.translations = data.get("translations", {})
                print(f"📂 已加载进度文件，已完成 {len(self.completed_pages)} 页")
            except (json.JSONDecodeError, IOError):
                print("⚠️  进度文件损坏，将重新开始")

    def save(self):
        """Save current progress."""
        data = {
            "completed_pages": sorted(self.completed_pages),
            "translations": self.translations
        }
        with open(self.progress_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def is_completed(self, page_num: int) -> bool:
        return page_num in self.completed_pages

    def mark_completed(self, page_num: int, translation: str):
        self.completed_pages.add(page_num)
        self.translations[str(page_num)] = translation
        # Auto-save every page
        self.save()

    def get_translation(self, page_num: int) -> str:
        return self.translations.get(str(page_num), "")


# ============================================================
# MAIN ORCHESTRATOR
# ============================================================

def translate_pdf(
    pdf_path: str,
    output_path: str,
    api_key: str,
    glossary_path: str = None,
    model: str = "deepseek-v4-pro",
    start_page: int = 0,
    end_page: int = None,
    pages_per_chunk: int = 1,
):
    """Main translation pipeline."""

    print("=" * 60)
    print("  🎲 DG TRPG PDF 翻译工具 — THE MILLENNIUM")
    print("=" * 60)
    print()

    # 1. Initialize PDF extractor
    print(f"📖 打开 PDF: {pdf_path}")
    extractor = PDFExtractor(pdf_path)
    total = extractor.total_pages
    print(f"   总页数: {total}")

    if end_page is None or end_page > total:
        end_page = total
    print(f"   翻译范围: 第 {start_page + 1} 页 → 第 {end_page} 页")
    print()

    # 2. Load glossary
    glossary = {}
    if glossary_path:
        print(f"📚 加载术语表: {glossary_path}")
        glossary = load_glossary(glossary_path)
        print(f"   已加载 {len(glossary)} 条术语")
        print()

    # 3. Initialize translator
    print(f"🤖 翻译引擎: DeepSeek V4 ({model})")
    translator = Translator(api_key=api_key, model=model)
    translator.set_glossary(glossary)
    print()

    # 4. Initialize progress tracker
    progress_file = output_path + ".progress.json"
    tracker = ProgressTracker(progress_file)
    print()

    # 5. Extract and translate page by page
    print("🔄 开始翻译...")
    print("-" * 40)

    translated_pages = []
    pages_to_process = list(range(start_page, end_page))
    total_to_do = len(pages_to_process)
    done_count = 0

    for page_num in pages_to_process:
        done_count += 1

        # Check if already translated (resume)
        if tracker.is_completed(page_num):
            translation = tracker.get_translation(page_num)
            if translation:
                translated_pages.append((page_num, translation))
            print(f"  ⏭️  第 {page_num + 1}/{total} 页 — 已完成（跳过）")
            continue

        # Extract text
        text = extractor.extract_page(page_num)
        if not text.strip():
            print(f"  ⬜ 第 {page_num + 1}/{total} 页 — 空页（跳过）")
            tracker.mark_completed(page_num, "")
            continue

        # Translate
        progress_pct = done_count / total_to_do * 100
        print(f"  🔄 第 {page_num + 1}/{total} 页 [{progress_pct:.0f}%] — 翻译中...", end="", flush=True)

        translation = translator.translate_chunk(text, page_num)

        if translation:
            translated_pages.append((page_num, translation))
            tracker.mark_completed(page_num, translation)
            print(f" ✅")
        else:
            print(f" ⚠️ 空结果")
            tracker.mark_completed(page_num, "")

        # Rate limiting: small delay between API calls
        time.sleep(0.5)

    print("-" * 40)
    print()

    # 6. Assemble final Markdown
    print(f"📝 生成 Markdown 文件: {output_path}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# THE MILLENNIUM — 中文翻译\n\n")
        f.write("> 由 DeepSeek V4 AI 翻译，术语参照绿色三角洲官方译名表\n\n")
        f.write("---\n\n")

        for page_num, translation in sorted(translated_pages, key=lambda x: x[0]):
            if translation.strip():
                f.write(f"<!-- Page {page_num + 1} -->\n\n")
                f.write(translation)
                f.write("\n\n---\n\n")

    print(f"   ✅ 完成！共翻译 {len([t for _, t in translated_pages if t.strip()])} 页")
    print()

    # 7. Cleanup progress file on success
    if done_count == total_to_do:
        print("🎉 全部翻译完成！")
        # Keep progress file for reference, user can delete manually
        print(f"   进度文件保留于: {progress_file}")
    else:
        print(f"⚠️  部分完成。下次运行将从断点继续。")

    extractor.close()
    print()
    print(f"📄 输出文件: {output_path}")


# ============================================================
# CLI ENTRY POINT
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="DG TRPG PDF Translator — 使用 DeepSeek V4 翻译绿色三角洲PDF资料",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基础用法
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx

  # 指定术语表和输出文件
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx \\
      --glossary glossary.tsv --output millennium_cn.md

  # 只翻译某个范围（第10页到第50页）
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx \\
      --start 10 --end 50

  # 使用 deepseek-v4-flash 模型（更快更便宜）
  python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx \\
      --model deepseek-v4-flash
        """
    )

    parser.add_argument("pdf", help="输入 PDF 文件路径")
    parser.add_argument("--api-key", required=True, help="DeepSeek API Key")
    parser.add_argument("--output", "-o", default=None, help="输出 Markdown 文件路径（默认: 输入文件名_cn.md）")
    parser.add_argument("--glossary", "-g", default=None, help="术语表文件路径（TSV 格式: 中文<TAB>英文）")
    parser.add_argument("--model", default="deepseek-v4-pro", help="模型名称（默认: deepseek-v4-pro）")
    parser.add_argument("--start", type=int, default=0, help="起始页码（从0开始，默认0）")
    parser.add_argument("--end", type=int, default=None, help="结束页码（不含，默认全部）")

    args = parser.parse_args()

    # Default output path
    if args.output is None:
        pdf_stem = Path(args.pdf).stem
        args.output = f"{pdf_stem}_cn.md"

    # Validate PDF exists
    if not os.path.exists(args.pdf):
        print(f"❌ PDF 文件不存在: {args.pdf}")
        sys.exit(1)

    # Run translation
    translate_pdf(
        pdf_path=args.pdf,
        output_path=args.output,
        api_key=args.api_key,
        glossary_path=args.glossary,
        model=args.model,
        start_page=args.start,
        end_page=args.end,
    )


if __name__ == "__main__":
    main()
