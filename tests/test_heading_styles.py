from core.extractor import PDFExtractor
from exporters.html import _html_block


def _line(text, size, y, flags=0):
    return {
        "bbox": (40, y, 260, y + size + 2),
        "spans": [
            {
                "text": text,
                "size": size,
                "flags": flags,
                "bbox": (40, y, 260, y + size + 2),
            }
        ],
    }


def test_extract_block_marks_four_heading_levels():
    extractor = PDFExtractor.__new__(PDFExtractor)
    block = {
        "bbox": (40, 40, 300, 220),
        "lines": [
            _line("Book Part", 24, 40),
            _line("Red Feature", 18, 70),
            _line("Tall Section", 15, 100),
            _line("Small Card Title", 13, 130, flags=2),
            _line("Regular body text continues here.", 10, 160),
        ],
    }

    text = extractor._extract_block_text(block, page_median_size=10)

    assert "# Book Part" in text
    assert "## Red Feature" in text
    assert "### Tall Section" in text
    assert "#### Small Card Title" in text
    assert "Regular body text continues here." in text


def test_html_renders_fourth_level_heading():
    html = _html_block("#### 小标题\n这是一段正文。")

    assert "<h4>小标题</h4>" in html
    assert "<p>这是一段正文。</p>" in html
