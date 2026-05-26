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
                       width_pt: float, height_pt: float,
                       layout_report_output: str | None = None):
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
        page.evaluate("document.fonts ? document.fonts.ready : Promise.resolve()")
        fit_results = page.evaluate("window.replicaFitTranslations ? window.replicaFitTranslations() : []")
        if layout_report_output is not None:
            write_browser_layout_report(fit_results, layout_report_output)
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
                      show_boxes: bool = False,
                      asset_base_dir: str | None = None,
                      layout_report_output: str | None = None) -> str:
    if not layout.pages:
        raise ValueError("layout 没有页面")
    if html_output is None:
        html_output = str(Path(pdf_output).with_suffix(".replica.html"))
    render_layout_html(
        layout,
        html_output,
        show_boxes=show_boxes,
        asset_base_dir=asset_base_dir,
    )
    first_page = layout.pages[0]
    export_html_to_pdf(
        html_output,
        pdf_output,
        width_pt=first_page.width,
        height_pt=first_page.height,
        layout_report_output=layout_report_output,
    )
    return html_output


def export_layout_json_pdf(layout_json_path: str, pdf_output: str,
                           html_output: str | None = None,
                           show_boxes: bool = False,
                           layout_report_output: str | None = None) -> str:
    layout_json = Path(layout_json_path).expanduser().resolve()
    layout = layout_document_from_json(layout_json.read_text(encoding="utf-8"))
    return export_layout_pdf(
        layout,
        pdf_output,
        html_output=html_output,
        show_boxes=show_boxes,
        asset_base_dir=str(layout_json.parent),
        layout_report_output=layout_report_output,
    )


def write_browser_layout_report(results, output_path: str) -> int:
    ensure_output_parent(output_path)
    rows = results if isinstance(results, list) else []
    overflow_count = len([row for row in rows if isinstance(row, dict) and row.get("overflow")])
    lines = [
        "# 浏览器排版报告",
        "",
        f"- 文本块：{len(rows)}",
        f"- 仍然溢出：{overflow_count}",
        "",
        "| 页码 | 块 ID | 最终字号(px) | 溢出 |",
        "| --- | --- | ---: | --- |",
    ]
    for row in rows:
        if not isinstance(row, dict):
            continue
        page = row.get("page", "")
        block_id = row.get("blockId", "")
        font_px = row.get("fontPx", "")
        overflow = "是" if row.get("overflow") else "否"
        try:
            font_text = f"{float(font_px):.3f}"
        except (TypeError, ValueError):
            font_text = str(font_px)
        lines.append(f"| {page} | `{block_id}` | {font_text} | {overflow} |")
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return overflow_count


def read_browser_layout_report_overflow_count(path: str) -> int:
    report_path = Path(path)
    if not report_path.exists():
        return 0
    text = report_path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("- 仍然溢出："):
            try:
                return int(line.split("：", 1)[1].strip())
            except ValueError:
                return 0
    return 0
