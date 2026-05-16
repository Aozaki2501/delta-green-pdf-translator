"""
Core constants used across the DGtranslate project.

This module is a leaf node in the dependency graph — it has no imports
from other project modules.
"""

PROMPT_VERSION = "2026-05-16-preserve-heading-levels-v6"
EXTRACTOR_VERSION = "2026-05-16-image-top-column-order-v5"
SUPPORTED_OUTPUT_FORMATS = {"markdown", "html", "word", "both", "all"}
TRANSLATION_FAILURE_PREFIX = "[Translation failed:"
