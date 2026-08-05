"""
Typeset PDF exporter using Playwright headless Chromium.

Renders the typeset HTML (produced by TypesetHTMLRebuilder) into a
professional-quality PDF with correct page dimensions and embedded fonts.
Uses Playwright headless Chromium for PDF generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.utils import ensure_output_parent


@dataclass
class ExportResult:
    """PDF export result with page-level status tracking."""

    success_pages: int = 0
    failed_pages: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    layout_issues: list[dict] = field(default_factory=list)


def _file_url(path: str) -> str:
    """Convert a local file path to a file:// URL."""
    return Path(path).resolve().as_uri()


class TypesetPDFExporter:
    """
    Typeset PDF exporter.

    Uses Playwright headless Chromium to render the typeset HTML into PDF.
    Page dimensions are specified in PDF points and converted to inches
    for the Playwright PDF API (divide by 72).
    """

    def validate_html_layout(self, html_path: str) -> list[dict]:
        """Fail HTML-only output when the browser finds a layout overflow."""
        if not Path(html_path).exists():
            raise FileNotFoundError(f"HTML 文件不存在：{html_path}")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "缺少 playwright。请先运行：pip install playwright && playwright install chromium"
            ) from exc

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(_file_url(html_path), wait_until="networkidle")
                self._wait_for_render_assets(page)
                issues = self._fit_and_collect_layout_issues(page)
                self._raise_for_layout_issues(issues)
                return issues
            finally:
                browser.close()

    def export(
        self,
        html_path: str,
        pdf_output: str,
        page_width_pt: float,
        page_height_pt: float,
    ) -> ExportResult:
        """
        Render the full typeset HTML to PDF using Playwright.

        Args:
            html_path: Path to the typeset HTML file.
            pdf_output: Output PDF file path (should end with _typeset.pdf).
            page_width_pt: Page width in PDF points.
            page_height_pt: Page height in PDF points.

        Returns:
            ExportResult with success/failure information.

        Raises:
            FileNotFoundError: If html_path does not exist.
            ValueError: If page dimensions are invalid.
            RuntimeError: If Playwright is not installed.
        """
        if not Path(html_path).exists():
            raise FileNotFoundError(f"HTML 文件不存在：{html_path}")
        if page_width_pt <= 0 or page_height_pt <= 0:
            raise ValueError("PDF 页面尺寸无效")
        ensure_output_parent(pdf_output)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "缺少 playwright。请先运行：pip install playwright && playwright install chromium"
            ) from exc

        result = ExportResult()

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(_file_url(html_path), wait_until="networkidle")
            self._wait_for_render_assets(page)
            result.layout_issues = self._fit_and_collect_layout_issues(page)
            self._raise_for_layout_issues(result.layout_issues)

            page.pdf(
                path=pdf_output,
                width=f"{page_width_pt / 72.0}in",
                height=f"{page_height_pt / 72.0}in",
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                print_background=True,
                prefer_css_page_size=True,
            )
            browser.close()

        # Count pages in the output PDF to report success
        result.success_pages = self._count_pdf_pages(pdf_output)
        return result

    def export_with_fallback(
        self,
        html_path: str,
        pdf_output: str,
        page_width_pt: float,
        page_height_pt: float,
    ) -> ExportResult:
        """
        Export PDF strictly.

        The old public method name is kept for callers, but failures are
        reported instead of silently skipping pages.

        Args:
            html_path: Path to the typeset HTML file.
            pdf_output: Output PDF file path (should end with _typeset.pdf).
            page_width_pt: Page width in PDF points.
            page_height_pt: Page height in PDF points.

        Returns:
            ExportResult with success/failure information per page.

        Raises:
            FileNotFoundError: If html_path does not exist.
            ValueError: If page dimensions are invalid.
            RuntimeError: If Playwright is not installed.
        """
        if not Path(html_path).exists():
            raise FileNotFoundError(f"HTML 文件不存在：{html_path}")
        if page_width_pt <= 0 or page_height_pt <= 0:
            raise ValueError("PDF 页面尺寸无效")
        ensure_output_parent(pdf_output)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "缺少 playwright。请先运行：pip install playwright && playwright install chromium"
            ) from exc

        result = ExportResult()

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()

            try:
                page.goto(_file_url(html_path), wait_until="networkidle")
                self._wait_for_render_assets(page)
                result.layout_issues = self._fit_and_collect_layout_issues(page)
                self._raise_for_layout_issues(result.layout_issues)

                # Get total page count from the HTML (count .typeset-page sections)
                total_pages = page.evaluate(
                    "document.querySelectorAll('.typeset-page').length"
                )

                # Try full export first
                try:
                    page.pdf(
                        path=pdf_output,
                        width=f"{page_width_pt / 72.0}in",
                        height=f"{page_height_pt / 72.0}in",
                        margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                        print_background=True,
                        prefer_css_page_size=True,
                    )
                    result.success_pages = total_pages if total_pages > 0 else self._count_pdf_pages(pdf_output)
                except Exception as e:
                    error_msg = f"完整导出失败：{e}"
                    result.errors.append(error_msg)
            except Exception as e:
                result.errors.append(f"页面加载失败：{e}")
            finally:
                browser.close()

        return result

    def _wait_for_render_assets(self, page) -> None:
        """Wait until fonts, SVG/image decoding and paint frames are complete."""
        page.evaluate("""async () => {
            if (document.fonts) await document.fonts.ready;
            await Promise.all(Array.from(document.images).map(async (image) => {
                if (!image.complete) {
                    await new Promise((resolve, reject) => {
                        image.addEventListener('load', resolve, {once: true});
                        image.addEventListener('error', reject, {once: true});
                    });
                }
                if (image.decode) await image.decode();
            }));
            await new Promise((resolve) => {
                requestAnimationFrame(() => requestAnimationFrame(resolve));
            });
        }""")

    def _fit_and_collect_layout_issues(self, page) -> list[dict]:
        page.evaluate(
            "window.typesetFitPositionedBlocks ? window.typesetFitPositionedBlocks() : undefined"
        )
        issues = page.evaluate(
            "window.typesetCollectLayoutIssues ? window.typesetCollectLayoutIssues() : []"
        )
        return issues if isinstance(issues, list) else []

    def _raise_for_layout_issues(self, issues: list[dict]) -> None:
        if not issues:
            return
        preview: list[str] = []
        for issue in issues[:5]:
            page = issue.get("page") or "?"
            kind = issue.get("kind") or "unknown"
            item_id = issue.get("id") or ""
            preview.append(f"page {page} {kind} {item_id}".strip())
        raise RuntimeError(
            "typeset layout overflow: "
            f"{len(issues)} issue(s); "
            + "; ".join(preview)
        )

    @staticmethod
    def _count_pdf_pages(pdf_path: str) -> int:
        """Count pages in a PDF file using PyMuPDF."""
        try:
            import fitz
            doc = fitz.open(pdf_path)
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return 0
