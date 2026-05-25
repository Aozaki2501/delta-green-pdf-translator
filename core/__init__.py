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
    output_base_in_own_dir,
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
    build_extraction_diagnostics_report,
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

# coordinate-level replica layout
from core.layout_model import (
    LayoutDocument,
    LayoutPage,
    LayoutTextBlock,
    LayoutSpan,
    LayoutImageBlock,
    layout_document_from_json,
    layout_document_from_dict,
)
from core.layout_extractor import (
    PDFLayoutExtractor,
    extract_layout_to_file,
)
from core.layout_translation import (
    LayoutFitIssue,
    LayoutTranslationProgress,
    block_source_text,
    export_translation_template,
    apply_translation_map,
    apply_translations_file,
    translate_layout_blocks,
    translate_layout_to_template,
    check_translated_overflow,
    write_overflow_report,
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
    "output_base_in_own_dir",
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
    "build_extraction_diagnostics_report",
    # translator
    "Translator",
    "TokenStats",
    "translate_batch_concurrent",
    # progress
    "ProgressTracker",
    "build_progress_metadata",
    "compare_progress_metadata",
    # replica layout
    "LayoutDocument",
    "LayoutPage",
    "LayoutTextBlock",
    "LayoutSpan",
    "LayoutImageBlock",
    "layout_document_from_json",
    "layout_document_from_dict",
    "PDFLayoutExtractor",
    "extract_layout_to_file",
    "LayoutFitIssue",
    "LayoutTranslationProgress",
    "block_source_text",
    "export_translation_template",
    "apply_translation_map",
    "apply_translations_file",
    "translate_layout_blocks",
    "translate_layout_to_template",
    "check_translated_overflow",
    "write_overflow_report",
]
