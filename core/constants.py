"""
Core constants used across the DGtranslate project.

This module is a leaf node in the dependency graph — it has no imports
from other project modules.
"""

PROMPT_VERSION = "2026-07-26-source-context-v16"
EXTRACTOR_VERSION = "2026-06-18-bold-subheadings-v2"
SUPPORTED_OUTPUT_FORMATS = {"markdown", "html", "word", "both", "all"}
TRANSLATION_FAILURE_PREFIX = "[Translation failed:"

# Sampling temperature for every translation request. Kept here (instead of
# inline in core.translator) so progress fingerprints can record it.
TRANSLATION_TEMPERATURE = 0.3
