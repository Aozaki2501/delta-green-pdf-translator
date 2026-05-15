"""
PDF text extraction and layout analysis.

Contains PDFExtractor, ChapterDetector, and HeadingInfo for extracting
text from dual-column TRPG PDFs with intelligent layout detection.
"""

import re
from dataclasses import dataclass
from typing import Optional

try:
    import pymupdf  # PyMuPDF >= 1.24
except ImportError:
    try:
        import fitz as pymupdf  # PyMuPDF < 1.24
    except ImportError:
        raise ImportError(
            "PyMuPDF not installed. Run: pip install pymupdf"
        )

from core.constants import EXTRACTOR_VERSION


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
        self._page_body_context: dict[int, str] = {}
        self._page_layout_notes: dict[int, list[str]] = {}

    def get_context_text(self, page_num: int) -> str:
        return self._page_body_context.get(page_num, "")

    def get_layout_notes(self, page_num: int) -> list[str]:
        return self._page_layout_notes.get(page_num, [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def _sort_blocks_layout_aware(self, blocks, page_width, page_height=None):
        sorted_input = sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))
        non_full_blocks = [
            b for b in sorted_input
            if (
                b.get("type") == 0
                and (b["bbox"][2] - b["bbox"][0]) <= page_width * 0.6
                and not self._is_title_card_block(b, page_width, page_height)
            )
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
        median_size = self._median_font_size(sorted_input)

        def flush_columns():
            nonlocal left_blocks, right_blocks
            output_blocks.extend(self._merge_columns_for_reading(left_blocks, right_blocks, median_size))
            left_blocks = []
            right_blocks = []

        for block in sorted_input:
            if block.get("type") != 0:
                continue

            x0, _, x1, _ = block["bbox"]
            block_width = x1 - x0
            is_full_width = block_width > page_width * 0.6
            is_title_card = self._is_title_card_block(block, page_width, page_height, median_size)

            if is_full_width or is_title_card:
                flush_columns()
                if is_title_card:
                    block = dict(block)
                    block["_dg_title_card"] = True
                output_blocks.append(block)
                continue

            block_center_x = (x0 + x1) / 2
            if block_center_x < page_width / 2:
                left_blocks.append(block)
            else:
                right_blocks.append(block)

        flush_columns()
        return output_blocks

    def _merge_columns_for_reading(self, left_blocks, right_blocks, median_size):
        left_sorted = sorted(left_blocks, key=lambda b: b["bbox"][1])
        right_sorted = sorted(right_blocks, key=lambda b: b["bbox"][1])
        if not left_sorted or not right_sorted:
            return left_sorted + right_sorted

        merged = []
        right_idx = 0

        for idx, left_block in enumerate(left_sorted):
            merged.append(left_block)
            next_left = left_sorted[idx + 1] if idx + 1 < len(left_sorted) else None
            if not next_left:
                continue

            if not self._is_heading_block(next_left, median_size):
                continue
            if self._ends_like_complete_sentence(self._extract_block_text(left_block)):
                continue

            heading_y = next_left["bbox"][1]
            while right_idx < len(right_sorted):
                right_block = right_sorted[right_idx]
                if right_block["bbox"][1] >= heading_y:
                    break
                right_text = self._extract_block_text(right_block)
                if not self._starts_with_lowercase(right_text):
                    break
                merged.append(right_block)
                right_idx += 1

        merged.extend(right_sorted[right_idx:])
        return merged

    def _median_font_size(self, blocks):
        sizes = []
        for block in blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size")
                    if size:
                        sizes.append(size)
        if not sizes:
            return 10
        sizes.sort()
        return sizes[len(sizes) // 2]

    def _block_avg_font_size(self, block):
        sizes = [
            span.get("size", 0)
            for line in block.get("lines", [])
            for span in line.get("spans", [])
            if span.get("size")
        ]
        if not sizes:
            return 0
        return sum(sizes) / len(sizes)

    def _block_width(self, block):
        x0, _, x1, _ = block["bbox"]
        return x1 - x0

    def _block_height(self, block):
        _, y0, _, y1 = block["bbox"]
        return y1 - y0

    def _block_center_x(self, block):
        x0, _, x1, _ = block["bbox"]
        return (x0 + x1) / 2

    def _block_line_count(self, block):
        return sum(
            1 for line in block.get("lines", [])
            if self._extract_line_text(line).strip()
        )

    def _rect_from_bbox(self, bbox):
        return pymupdf.Rect(*bbox)

    def _rect_contains_block(self, rect, block, tolerance=4):
        x0, y0, x1, y1 = block["bbox"]
        return (
            x0 >= rect.x0 - tolerance
            and y0 >= rect.y0 - tolerance
            and x1 <= rect.x1 + tolerance
            and y1 <= rect.y1 + tolerance
        )

    def _rects_touch_or_overlap(self, left, right, tolerance=10):
        return not (
            left.x1 < right.x0 - tolerance
            or right.x1 < left.x0 - tolerance
            or left.y1 < right.y0 - tolerance
            or right.y1 < left.y0 - tolerance
        )

    def _union_rect(self, rects):
        x0 = min(rect.x0 for rect in rects)
        y0 = min(rect.y0 for rect in rects)
        x1 = max(rect.x1 for rect in rects)
        y1 = max(rect.y1 for rect in rects)
        return pymupdf.Rect(x0, y0, x1, y1)

    def _block_fonts(self, block):
        return {
            span.get("font", "")
            for line in block.get("lines", [])
            for span in line.get("spans", [])
            if span.get("font")
        }

    def _is_monospace_block(self, block):
        fonts = self._block_fonts(block)
        return any("VT323" in font or "Mono" in font or "Courier" in font for font in fonts)

    def _line_words(self, line):
        words = []
        for span in line.get("spans", []):
            text = span.get("text", "").strip()
            if not text:
                continue
            x0, y0, x1, y1 = span.get("bbox", line.get("bbox", (0, 0, 0, 0)))
            words.append({"text": text, "x": x0, "y": y0, "bbox": (x0, y0, x1, y1)})
        return words

    def _extract_monospace_lines(self, block):
        lines = []
        for line in block.get("lines", []):
            words = self._line_words(line)
            if not words:
                continue
            words.sort(key=lambda word: word["x"])
            lines.append(words)
        return lines

    def _block_to_markdown_table(self, block):
        return self._blocks_to_markdown_table([block])

    def _blocks_to_markdown_table(self, blocks):
        row_candidates = []
        for block in blocks:
            block_words = []
            for words in self._extract_monospace_lines(block):
                row_text = " ".join(word["text"] for word in words)
                if re.fullmatch(r"[_+\-\s|]+", row_text):
                    continue
                block_words.extend(words)
            if block_words:
                row_candidates.append(sorted(block_words, key=lambda word: (word["y"], word["x"])))

        if len(row_candidates) < 2:
            return None

        header_words = row_candidates[0]
        header = [re.sub(r"^[| ]+|[| ]+$", "", word["text"]).strip() for word in header_words]
        header = [cell for cell in header if cell]
        if len(header) < 2:
            return None

        col_count = len(header)
        col_positions = sorted(word["x"] for word in header_words[:col_count])
        table_rows = []
        for words in row_candidates[1:]:
            cells = ["" for _ in range(col_count)]
            for word in words:
                idx = min(range(col_count), key=lambda i: abs(word["x"] - col_positions[i]))
                clean_word = re.sub(r"^[| ]+|[| ]+$", "", word["text"]).strip()
                if clean_word:
                    cells[idx] = (cells[idx] + " " + clean_word).strip()
            if any(cells):
                table_rows.append(cells)

        if not table_rows:
            return None

        markdown = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for cells in table_rows:
            markdown.append("| " + " | ".join(cells) + " |")
        return "\n".join(markdown)

    def _is_table_block(self, block, page_width):
        if not self._is_monospace_block(block):
            return False
        x0, _, x1, _ = block["bbox"]
        if x1 - x0 < page_width * 0.55:
            return False
        text = self._extract_block_text(block)
        return "|" in text or "CLUE" in text.upper() or re.search(r"_{8,}|\+[-_ ]+", text)

    def _is_contents_block(self, block):
        if not self._is_monospace_block(block):
            return False
        text = self._extract_block_text(block)
        return bool(re.search(r"\bContents\b", text, re.IGNORECASE)) or (
            text.count(".") >= 20 and bool(re.search(r"\.{4,}\s*\d{1,3}", text))
        )

    def _is_handout_block(self, block):
        if not self._is_monospace_block(block):
            return False
        text = self._extract_block_text(block)
        if not text:
            return False
        return bool(re.search(r"\b(SUBJECT|Records?|Stories?|Profile)\b", text, re.IGNORECASE))

    def _has_card_label(self, text: str) -> bool:
        patterns = [
            r"\b(?:YELLOW|GREEN|RED|BLUE|WHITE|BLACK)\s+CARD\b",
            r"\bPLAYER\s+AID\b",
            r"\bSUBJECT\s*:",
            r"\bPROFILE\s+OF\b",
            r"\b(?:Birth|Medical|Police|USMC|Military|News|School|Juvenile)\s+Records?\b",
            r"^\s*(?:Timeline|Briefing|Report|Memo|Evidence|Clue|Handout|Photograph|Letter|Note)\b",
        ]
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

    def _is_card_text_block(self, block, page_width, page_height, median_size=None):
        text = self._extract_block_text(block).strip()
        if not text:
            return False
        if self._is_contents_block(block) or self._is_table_block(block, page_width):
            return False
        width = self._block_width(block)
        line_count = self._block_line_count(block)
        avg_size = self._block_avg_font_size(block)
        median_size = median_size or avg_size or 10
        if self._is_handout_block(block):
            return True
        if self._has_card_label(text) and (width >= page_width * 0.28 or line_count >= 2):
            return True
        if (
            self._is_monospace_block(block)
            and line_count >= 4
            and width >= page_width * 0.42
            and self._block_height(block) >= page_height * 0.08
        ):
            return True
        if (
            width >= page_width * 0.68
            and line_count >= 5
            and avg_size <= median_size * 1.35
            and self._has_card_label(text[:300])
        ):
            return True
        return False

    def _visual_card_regions(self, page, content_blocks, page_width, page_height):
        page_area = page_width * page_height
        regions = []

        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            if not rect:
                continue
            area = rect.width * rect.height
            if area < page_area * 0.025 or area > page_area * 0.78:
                continue
            if rect.width < page_width * 0.24 or rect.height < page_height * 0.08:
                continue
            regions.append(rect)

        for image in page.get_images(full=True):
            xref = image[0]
            for rect in page.get_image_rects(xref):
                area = rect.width * rect.height
                if area < page_area * 0.035 or area > page_area * 0.78:
                    continue
                if rect.width < page_width * 0.28 or rect.height < page_height * 0.10:
                    continue
                regions.append(rect)

        median_size = self._median_font_size(content_blocks)
        accepted = []
        for rect in regions:
            inside = [
                block for block in content_blocks
                if self._rect_contains_block(rect, block, tolerance=8)
            ]
            if not inside:
                continue
            has_card_text = any(
                self._is_card_text_block(block, page_width, page_height, median_size)
                for block in inside
            )
            monospace_lines = sum(
                self._block_line_count(block) for block in inside
                if self._is_monospace_block(block)
            )
            if has_card_text or monospace_lines >= 4:
                accepted.append(rect)

        merged = []
        for rect in sorted(accepted, key=lambda item: (item.y0, item.x0)):
            for idx, existing in enumerate(merged):
                if self._rects_touch_or_overlap(existing, rect, tolerance=14):
                    merged[idx] = self._union_rect([existing, rect])
                    break
            else:
                merged.append(rect)
        return merged

    def _group_card_blocks(self, card_blocks, page_width, page_height):
        groups = []
        for block in sorted(card_blocks, key=lambda item: (item["bbox"][1], item["bbox"][0])):
            rect = self._rect_from_bbox(block["bbox"])
            placed = False
            for group in groups:
                group_rect = self._union_rect([self._rect_from_bbox(b["bbox"]) for b in group])
                same_band = abs(rect.y0 - group_rect.y1) <= page_height * 0.08
                horizontal_overlap = min(rect.x1, group_rect.x1) - max(rect.x0, group_rect.x0)
                overlap_ratio = horizontal_overlap / max(min(rect.width, group_rect.width), 1)
                if same_band and overlap_ratio >= 0.35:
                    group.append(block)
                    placed = True
                    break
            if not placed:
                groups.append([block])
        return groups

    def _split_card_blocks(self, page, content_blocks, page_width, page_height):
        median_size = self._median_font_size(content_blocks)
        card_ids = set()
        card_groups = []
        notes = []

        for rect in self._visual_card_regions(page, content_blocks, page_width, page_height):
            group = [
                block for block in content_blocks
                if id(block) not in card_ids and self._rect_contains_block(rect, block, tolerance=8)
            ]
            if not group:
                continue
            for block in group:
                card_ids.add(id(block))
            card_groups.append(group)

        loose_card_blocks = [
            block for block in content_blocks
            if id(block) not in card_ids
            and self._is_card_text_block(block, page_width, page_height, median_size)
        ]
        for group in self._group_card_blocks(loose_card_blocks, page_width, page_height):
            for block in group:
                card_ids.add(id(block))
            card_groups.append(group)

        body_blocks = [
            block for block in content_blocks
            if id(block) not in card_ids
        ]
        if card_groups:
            card_blocks_count = sum(len(group) for group in card_groups)
            notes.append(f"{len(card_groups)} card section(s), {card_blocks_count} block(s)")
        return body_blocks, card_groups, notes

    def _is_heading_block(self, block, median_size):
        text = self._extract_block_text(block).strip()
        if not text or len(text) > 90:
            return False
        if re.search(r"[.!?。！？]$", text):
            return False
        return self._block_avg_font_size(block) >= median_size * 1.25

    def _is_title_card_block(self, block, page_width, page_height=None, median_size=None):
        text = self._extract_block_text(block).strip()
        text = re.sub(r"^#\s*", "", text).strip()
        if not text or len(text) > 120:
            return False
        if re.search(r"[.!?。！？]$", text):
            return False

        x0, y0, x1, _ = block["bbox"]
        center_x = (x0 + x1) / 2
        page_center = page_width / 2
        avg_size = self._block_avg_font_size(block)
        size_floor = (median_size * 2.0) if median_size else 22
        near_top = True if page_height is None else y0 < page_height * 0.22
        centered = abs(center_x - page_center) <= page_width * 0.22
        return near_top and centered and avg_size >= size_floor

    def _ends_like_complete_sentence(self, text):
        return bool(re.search(r"[.!?\u3002\uff01\uff1f\u201d\\\"\u2019')\]]\s*$", text.strip()))

    def _starts_with_lowercase(self, text):
        match = re.search(r"[A-Za-z]", text.strip())
        return bool(match and match.group(0).islower())

    def _extract_line_text(self, line):
        spans_text = []
        last_span_norm = ""
        for span in line.get("spans", []):
            span_text = span["text"]
            span_norm = re.sub(r"\s+", " ", span_text).strip().lower()
            if span_norm and span_norm == last_span_norm:
                continue
            spans_text.append(span_text)
            last_span_norm = span_norm
        return "".join(spans_text).strip()

    def _line_avg_font_size(self, line):
        sizes = [
            span.get("size", 0)
            for span in line.get("spans", [])
            if span.get("size")
        ]
        if not sizes:
            return 0
        return sum(sizes) / len(sizes)

    def _join_line_into_paragraph(self, paragraph, line_text):
        if not paragraph:
            return line_text
        tail = paragraph.rstrip()
        if tail.endswith("-") and re.search(r"[A-Za-z]-$", tail) and re.match(r"^[A-Za-z]", line_text):
            return tail[:-1] + line_text
        return tail + " " + line_text

    def _extract_block_text(self, block):
        raw_lines = []
        for line in block.get("lines", []):
            line_text = self._extract_line_text(line)
            if not line_text:
                continue
            if raw_lines and line_text == raw_lines[-1]["text"]:
                continue
            raw_lines.append({
                "text": line_text,
                "bbox": line.get("bbox", block["bbox"]),
                "size": self._line_avg_font_size(line),
            })
        if not raw_lines:
            return ""

        body_sizes = sorted(l["size"] for l in raw_lines if l["size"])
        median_size = body_sizes[len(body_sizes) // 2] if body_sizes else 10
        left_edge = min(l["bbox"][0] for l in raw_lines)

        paragraphs = []
        current = ""

        def flush():
            nonlocal current
            if current.strip():
                paragraphs.append(current.strip())
                current = ""

        for idx, line in enumerate(raw_lines):
            text = line["text"]
            indent = line["bbox"][0] - left_edge
            visible = re.sub(r"\s+", "", text)
            is_heading = (
                line["size"] >= median_size * 1.6
                and 2 <= len(visible) <= 40
                and not re.search(r"[.!?。！？]$", text)
            )
            is_indented_para = idx > 0 and indent >= max(10, median_size * 1.2)

            if is_heading:
                flush()
                paragraphs.append(text)
                continue
            if is_indented_para:
                flush()

            current = self._join_line_into_paragraph(current, text)

        flush()
        text = "\n\n".join(paragraphs)
        if block.get("_dg_title_card"):
            title = re.sub(r"\s+", " ", text).strip()
            return f"# {title}" if title else ""
        return text

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

        running_titles = ("DELTA GREEN", "PISCES", "THE MILLENNIUM", "THE NEW AGE", "THE LABYRINTH")
        if in_margin and any(title in normalized for title in running_titles):
            return True
        if in_margin and "//" in compact:
            return True

        if in_bottom and len(compact) <= 80:
            return True
        return False

    def detect_page_layout(self, page_num: int) -> str:
        """Return 'handout', 'single', or 'columns' for source page layout."""
        page = self.doc[page_num]
        page_width = page.rect.width
        page_height = page.rect.height
        page_dict = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
        content_blocks = [
            b for b in page_dict.get("blocks", [])
            if b.get("type") == 0 and not self._is_header_footer(b, page_height)
        ]
        if not content_blocks:
            return "columns"

        if any(self._is_contents_block(block) for block in content_blocks):
            return "toc"

        handout_blocks = [
            block for block in content_blocks
            if self._is_handout_block(block)
        ]
        top_blocks = sorted(content_blocks, key=lambda block: (block["bbox"][1], block["bbox"][0]))
        top_text = self._extract_block_text(top_blocks[0]) if top_blocks else ""
        if len(handout_blocks) >= 3 or re.match(r"\s*Player Aid\b", top_text, re.IGNORECASE):
            return "handout"

        left_count = 0
        right_count = 0
        full_width_height = 0
        total_height = 0

        for block in content_blocks:
            x0, y0, x1, y1 = block["bbox"]
            width = x1 - x0
            height = max(0, y1 - y0)
            center = (x0 + x1) / 2
            total_height += height

            spans_most_page = (
                width >= page_width * 0.72
                and x0 <= page_width * 0.20
                and x1 >= page_width * 0.80
            )
            if spans_most_page:
                full_width_height += height
                continue

            if width <= page_width * 0.62:
                if center < page_width / 2:
                    left_count += 1
                else:
                    right_count += 1

        has_two_column_signal = left_count >= 1 and right_count >= 1
        full_width_ratio = full_width_height / max(total_height, 1)
        if full_width_ratio >= 0.45:
            return "single"
        if has_two_column_signal:
            return "columns"
        if len(content_blocks) <= 3 and full_width_height > page_height * 0.18:
            return "single"
        return "columns"

    def _clean_text(self, text):
        text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
        text = re.sub(r"  +", " ", text)
        text = re.sub(r"^\s*\d{1,3}\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _layout_notes_for_page(self, layout: str, content_blocks, page_width: float) -> list[str]:
        notes = [f"layout: {layout}"]
        table_count = sum(1 for block in content_blocks if self._is_table_block(block, page_width))
        handout_count = sum(1 for block in content_blocks if self._is_handout_block(block))
        if any(self._is_contents_block(block) for block in content_blocks):
            notes.append("contents page preserved as TOC")
        if table_count:
            notes.append(f"{table_count} table-like block(s)")
        if handout_count:
            notes.append(f"{handout_count} handout block(s)")
        return notes

    def _context_from_extracted_text(self, text: str, layout: str) -> str:
        if layout == "toc":
            return ""
        context_lines = []
        in_fenced_block = False
        in_card_block = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("```"):
                in_fenced_block = not in_fenced_block
                continue
            if in_fenced_block:
                continue
            if line == "[CARD]":
                in_card_block = True
                continue
            if line == "[/CARD]":
                in_card_block = False
                continue
            if in_card_block:
                continue
            if line == "[[TOC]]":
                continue
            if line.startswith("|") and line.count("|") >= 2:
                continue
            if line.startswith(">"):
                line = line.lstrip(">").strip()
            context_lines.append(line)
        return self._clean_text("\n".join(context_lines))[-1200:]

    def _quote_card_text(self, text: str) -> str:
        quoted = []
        for line in text.splitlines():
            quoted.append("> " + line.strip() if line.strip() else ">")
        return "\n".join(quoted).strip()

    def _card_block_text(self, text: str) -> str:
        clean = self._clean_text(text)
        if not clean:
            return ""
        return "[CARD]\n" + clean + "\n[/CARD]"

    def _blocks_to_extracted_text(self, blocks, page_width, page_height, layout_aware=True,
                                  mark_handouts=True) -> str:
        if not blocks:
            return ""
        if layout_aware:
            sorted_blocks = self._sort_blocks_layout_aware(blocks, page_width, page_height)
        else:
            sorted_blocks = sorted(blocks, key=lambda item: (item["bbox"][1], item["bbox"][0]))

        processed_blocks = []
        idx = 0
        while idx < len(sorted_blocks):
            block = sorted_blocks[idx]
            if self._is_table_block(block, page_width):
                table_blocks = []
                while idx < len(sorted_blocks) and self._is_monospace_block(sorted_blocks[idx]):
                    table_blocks.append(sorted_blocks[idx])
                    idx += 1
                table_text = self._blocks_to_markdown_table(table_blocks)
                if not table_text:
                    table_text = "\n".join(
                        self._extract_block_text(b).strip()
                        for b in table_blocks
                        if self._extract_block_text(b).strip()
                    )
                processed_blocks.append({"text": table_text, "title_card": False})
                continue

            if mark_handouts and self._is_handout_block(block):
                text = self._extract_block_text(block).strip()
                if text:
                    text = self._quote_card_text(text)
                processed_blocks.append({"text": text, "title_card": False})
                idx += 1
                continue

            processed_blocks.append({
                "text": self._extract_block_text(block).strip(),
                "title_card": bool(block.get("_dg_title_card")),
            })
            idx += 1

        paragraphs = []
        current_para = ""
        current_is_title_card = False

        for item in processed_blocks:
            text = item["text"].strip()
            if not text:
                continue
            is_title_card = item["title_card"]

            if not current_para:
                current_para = text
                current_is_title_card = is_title_card
                continue

            if current_is_title_card and is_title_card:
                left = re.sub(r"^#\s*", "", current_para).strip()
                right = re.sub(r"^#\s*", "", text).strip()
                current_para = "# " + " ".join(part for part in (left, right) if part)
                continue

            current_tail = current_para.rstrip()
            first_alpha = re.search(r"[A-Za-z]", text)
            starts_lower = bool(first_alpha and first_alpha.group(0).islower())
            joins_from_punctuation = current_tail.endswith((",", ":", ";", "-"))

            if joins_from_punctuation or starts_lower:
                if current_tail.endswith("-"):
                    current_para = current_tail[:-1].rstrip() + text
                else:
                    current_para = current_tail + " " + text
                current_is_title_card = current_is_title_card and is_title_card
            else:
                paragraphs.append(current_para)
                current_para = text
                current_is_title_card = is_title_card

        if current_para:
            paragraphs.append(current_para)
        return self._clean_text("\n\n".join(paragraphs))

    def extract_page(self, page_num: int) -> str:
        page = self.doc[page_num]
        page_width = page.rect.width
        page_height = page.rect.height
        page_dict = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
        blocks = page_dict.get("blocks", [])
        self.chapter_detector.analyze_page(page_num, page_dict)
        if not blocks:
            self._page_body_context[page_num] = ""
            self._page_layout_notes[page_num] = ["empty page"]
            return ""
        content_blocks = [
            b for b in blocks
            if b.get("type") == 0 and not self._is_header_footer(b, page_height)
        ]
        if not content_blocks:
            self._page_body_context[page_num] = ""
            self._page_layout_notes[page_num] = ["no content blocks"]
            return ""
        layout = self.detect_page_layout(page_num)
        self._page_layout_notes[page_num] = self._layout_notes_for_page(layout, content_blocks, page_width)
        if layout == "toc":
            toc_text = self._extract_contents_page(content_blocks)
            clean_toc = self._clean_text(toc_text)
            self._page_body_context[page_num] = ""
            return clean_toc

        body_blocks, card_groups, card_notes = self._split_card_blocks(
            page, content_blocks, page_width, page_height
        )
        self._page_layout_notes[page_num].extend(card_notes)

        body_text = self._blocks_to_extracted_text(
            body_blocks, page_width, page_height, layout_aware=True, mark_handouts=True
        )
        sections = []
        if body_text:
            sections.append(body_text)
        for group in sorted(card_groups, key=lambda group: min(block["bbox"][1] for block in group)):
            card_text = self._blocks_to_extracted_text(
                group, page_width, page_height, layout_aware=False, mark_handouts=False
            )
            if card_text:
                sections.append(self._card_block_text(card_text))

        clean_text = self._clean_text("\n\n".join(sections))
        self._page_body_context[page_num] = self._context_from_extracted_text(body_text, layout)
        return clean_text

    def _extract_contents_page(self, content_blocks):
        toc_blocks = [
            block for block in content_blocks
            if self._is_monospace_block(block)
        ]
        title_blocks = [block for block in toc_blocks if self._is_contents_block(block) and "Contents" in self._extract_block_text(block)]
        body_blocks = [block for block in toc_blocks if block not in title_blocks]
        body_blocks = sorted(body_blocks, key=lambda b: (b["bbox"][0], b["bbox"][1]))

        parts = []
        if title_blocks:
            title = self._extract_block_text(sorted(title_blocks, key=lambda b: b["bbox"][1])[0])
            title = re.sub(r"_+", "", title).strip()
            if title:
                parts.append(f"[[TOC]]\n# {title}")
        else:
            parts.append("[[TOC]]")

        for block in body_blocks:
            text = self._extract_contents_block_lines(block).strip()
            if text:
                parts.append("```toc\n" + text + "\n```")
        return "\n\n".join(parts)

    def _extract_contents_block_lines(self, block):
        lines = []
        for line in block.get("lines", []):
            text = self._extract_line_text(line)
            text = re.sub(r"\s+", " ", text).rstrip()
            if text:
                lines.append(text)
        return "\n".join(lines)

    def finalize_chapters(self):
        self.chapter_detector.finalize()

    def close(self):
        if self.doc is not None:
            self.doc.close()
            self.doc = None
