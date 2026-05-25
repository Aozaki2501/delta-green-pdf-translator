"""
Exporters package — public interface.

Re-exports the main output functions and the shared pagination helper
so consumers can do:

    from exporters import write_html_output, write_word_output, ...
"""

from exporters.html import write_html_output
from exporters.word import write_word_output
from exporters.markdown import write_markdown_output
from exporters.pdf_html import render_layout_html, render_layout_json_html
from exporters.pdf_playwright import export_html_to_pdf, export_layout_pdf, export_layout_json_pdf
from exporters._shared import paginate_translated_blocks

__all__ = [
    "write_html_output",
    "write_word_output",
    "write_markdown_output",
    "render_layout_html",
    "render_layout_json_html",
    "export_html_to_pdf",
    "export_layout_pdf",
    "export_layout_json_pdf",
    "paginate_translated_blocks",
]
