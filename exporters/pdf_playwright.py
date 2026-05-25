"""
Playwright PDF exporter for replica HTML.
"""

from pathlib import Path

from core.layout_model import LayoutDocument, layout_document_from_json
from core.utils import ensure_output_parent
from exporters.pdf_html import render_layout_html


def _file_url(path: str) -> str:
    return Path(path).resolve().as_uri()


def export_html_to_pdf(html_path: str, pdf_output: str,
                       width_pt: float, height_pt: float):
    if not Path(html_path).exists():
        raise FileNotFoundError(f"HTML 文件不存在：{html_path}")
    if width_pt <= 0 or height_pt <= 0:
        raise ValueError("PDF 页面尺寸无效")
    ensure_output_parent(pdf_output)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("缺少 playwright。请先运行：pip install playwright && playwright install chromium") from exc

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(_file_url(html_path), wait_until="load")
        page.pdf(
            path=pdf_output,
            width=f"{width_pt / 72.0}in",
            height=f"{height_pt / 72.0}in",
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            print_background=True,
            prefer_css_page_size=True,
        )
        browser.close()


def export_layout_pdf(layout: LayoutDocument, pdf_output: str,
                      html_output: str | None = None,
                      show_boxes: bool = False) -> str:
    if not layout.pages:
        raise ValueError("layout 没有页面")
    if html_output is None:
        html_output = str(Path(pdf_output).with_suffix(".replica.html"))
    render_layout_html(layout, html_output, show_boxes=show_boxes)
    first_page = layout.pages[0]
    export_html_to_pdf(
        html_output,
        pdf_output,
        width_pt=first_page.width,
        height_pt=first_page.height,
    )
    return html_output


def export_layout_json_pdf(layout_json_path: str, pdf_output: str,
                           html_output: str | None = None,
                           show_boxes: bool = False) -> str:
    layout = layout_document_from_json(Path(layout_json_path).read_text(encoding="utf-8"))
    return export_layout_pdf(
        layout,
        pdf_output,
        html_output=html_output,
        show_boxes=show_boxes,
    )
