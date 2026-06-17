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
    GlossaryCandidate,
    load_glossary,
    find_relevant_glossary_terms,
    select_core_glossary_terms,
    build_glossary_candidates,
    build_glossary_report,
    render_glossary_candidate_report,
    render_glossary_candidate_tsv,
    write_glossary_report,
    write_glossary_candidate_report,
    write_glossary_candidate_tsv,
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

# quality — depends on glossary and utils
from core.quality import (
    QualityIssue,
    QualityReport,
    build_quality_report,
    render_quality_report_markdown,
    write_quality_report,
)

# run reports — plain helpers for manifest and effect report output
from core.run_report import (
    build_run_effect,
    build_run_manifest,
    render_run_effect_markdown,
    write_run_effect_report,
    write_run_manifest,
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
    "GlossaryCandidate",
    "load_glossary",
    "find_relevant_glossary_terms",
    "select_core_glossary_terms",
    "build_glossary_candidates",
    "build_glossary_report",
    "render_glossary_candidate_report",
    "render_glossary_candidate_tsv",
    "write_glossary_report",
    "write_glossary_candidate_report",
    "write_glossary_candidate_tsv",
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
    # quality
    "QualityIssue",
    "QualityReport",
    "build_quality_report",
    "render_quality_report_markdown",
    "write_quality_report",
    # run reports
    "build_run_effect",
    "build_run_manifest",
    "render_run_effect_markdown",
    "write_run_effect_report",
    "write_run_manifest",
]
