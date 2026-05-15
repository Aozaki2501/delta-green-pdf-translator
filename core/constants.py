"""
Core constants used across the DGtranslate project.

This module is a leaf node in the dependency graph — it has no imports
from other project modules.
"""

PROMPT_VERSION = "2026-05-15-preserve-layout-markers-v5"
EXTRACTOR_VERSION = "2026-05-15-card-sections-v2"
SUPPORTED_OUTPUT_FORMATS = {"markdown", "html", "word", "both", "all"}
TRANSLATION_FAILURE_PREFIX = "[Translation failed:"
