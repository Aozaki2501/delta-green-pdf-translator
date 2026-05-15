"""
Core package for DGtranslate.

Re-exports all public symbols from submodules so consumers can use:
    from core import PDFExtractor, Translator, ProgressTracker, ...
"""

# constants — leaf node, no project dependencies
from core.constants import (
    PROMPT_VERSION,
    EXTRACTOR_VERSION,
    SUPPORTED_OUTPUT_FORMATS,
    TRANSLATION_FAILURE_PREFIX,
)

# utils — depends only on constants
from core.utils import (
    configure_console_output,
    ensure_output_parent,
    normalize_page_range,
    is_failed_translation,
    parse_page_selection,
    file_sha256,
)

# glossary — depends on utils
from core.glossary import (
    load_glossary,
    find_relevant_glossary_terms,
    build_glossary_report,
    write_glossary_report,
)

# extractor — depends on constants
from core.extractor import (
    PDFExtractor,
    ChapterDetector,
    HeadingInfo,
)

# translator — depends on constants, glossary
from core.translator import (
    Translator,
    TokenStats,
    translate_batch_concurrent,
)

# progress — depends on constants, utils
from core.progress import (
    ProgressTracker,
    build_progress_metadata,
    compare_progress_metadata,
)

__all__ = [
    # constants
    "PROMPT_VERSION",
    "EXTRACTOR_VERSION",
    "SUPPORTED_OUTPUT_FORMATS",
    "TRANSLATION_FAILURE_PREFIX",
    # utils
    "configure_console_output",
    "ensure_output_parent",
    "normalize_page_range",
    "is_failed_translation",
    "parse_page_selection",
    "file_sha256",
    # glossary
    "load_glossary",
    "find_relevant_glossary_terms",
    "build_glossary_report",
    "write_glossary_report",
    # extractor
    "PDFExtractor",
    "ChapterDetector",
    "HeadingInfo",
    # translator
    "Translator",
    "TokenStats",
    "translate_batch_concurrent",
    # progress
    "ProgressTracker",
    "build_progress_metadata",
    "compare_progress_metadata",
]
