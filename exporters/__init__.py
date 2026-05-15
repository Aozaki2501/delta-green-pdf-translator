"""
Exporters package — public interface.

Re-exports the main output functions and the shared pagination helper
so consumers can do:

    from exporters import write_html_output, write_word_output, ...
"""

from exporters.html import write_html_output
from exporters.word import write_word_output
from exporters.markdown import write_markdown_output
from exporters._shared import paginate_translated_blocks

__all__ = [
    "write_html_output",
    "write_word_output",
    "write_markdown_output",
    "paginate_translated_blocks",
]
