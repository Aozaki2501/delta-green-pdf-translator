"""
Import smoke tests for the module-refactor.

Verifies:
- All 15 Public_API symbols are importable from translate_pdf
- Each core module can be imported individually without circular import errors
- Each exporter module can be imported individually without circular import errors
- HAS_DOCX is a boolean

Requirements: 10.1, 10.6
"""

import importlib
import sys

import pytest


# The 15 Public_API symbols that app.py imports from translate_pdf
PUBLIC_API_SYMBOLS = [
    "PDFExtractor",
    "Translator",
    "ProgressTracker",
    "TokenStats",
    "load_glossary",
    "translate_batch_concurrent",
    "write_markdown_output",
    "write_html_output",
    "write_word_output",
    "HAS_DOCX",
    "build_progress_metadata",
    "parse_page_selection",
    "write_glossary_report",
    "normalize_page_range",
    "is_failed_translation",
]


class TestPublicAPIImports:
    """Test that all 15 Public_API symbols are importable from translate_pdf."""

    @pytest.mark.parametrize("symbol", PUBLIC_API_SYMBOLS)
    def test_symbol_importable_from_translate_pdf(self, symbol):
        """Each Public_API symbol should be importable from translate_pdf."""
        import translate_pdf

        assert hasattr(translate_pdf, symbol), (
            f"translate_pdf module is missing expected symbol: {symbol}"
        )
        # Verify the attribute is not None
        attr = getattr(translate_pdf, symbol)
        assert attr is not None, (
            f"translate_pdf.{symbol} is None"
        )

    def test_all_15_symbols_present(self):
        """Verify exactly all 15 Public_API symbols are accessible."""
        import translate_pdf

        missing = [
            s for s in PUBLIC_API_SYMBOLS
            if not hasattr(translate_pdf, s)
        ]
        assert missing == [], (
            f"Missing Public_API symbols from translate_pdf: {missing}"
        )

    def test_has_docx_is_boolean(self):
        """HAS_DOCX must be a boolean value."""
        from translate_pdf import HAS_DOCX

        assert isinstance(HAS_DOCX, bool), (
            f"HAS_DOCX should be a bool, got {type(HAS_DOCX).__name__}"
        )


class TestCoreModuleImports:
    """Test that each core module can be imported individually without circular imports."""

    CORE_MODULES = [
        "core.constants",
        "core.utils",
        "core.glossary",
        "core.extractor",
        "core.layout_model",
        "core.layout_extractor",
        "core.layout_translation",
        "core.translator",
        "core.progress",
    ]

    @pytest.mark.parametrize("module_name", CORE_MODULES)
    def test_core_module_importable(self, module_name):
        """Each core module should import without circular import errors."""
        # Remove cached module to force a fresh import
        modules_to_remove = [
            key for key in sys.modules if key.startswith("core")
        ]
        for key in modules_to_remove:
            del sys.modules[key]

        try:
            mod = importlib.import_module(module_name)
            assert mod is not None
        except ImportError as e:
            # Allow missing optional dependencies (pymupdf, openai)
            # but not circular import errors
            error_msg = str(e)
            assert "circular" not in error_msg.lower(), (
                f"Circular import detected in {module_name}: {e}"
            )
            # Re-raise if it's not a known optional dependency
            if "pymupdf" not in error_msg.lower() and "fitz" not in error_msg.lower() and "openai" not in error_msg.lower():
                raise

    def test_core_package_importable(self):
        """The core package itself should import without errors."""
        import core

        assert core is not None


class TestExporterModuleImports:
    """Test that each exporter module can be imported individually without circular imports."""

    EXPORTER_MODULES = [
        "exporters._shared",
        "exporters.html",
        "exporters.pdf_html",
        "exporters.pdf_playwright",
        "exporters.word",
        "exporters.markdown",
    ]

    @pytest.mark.parametrize("module_name", EXPORTER_MODULES)
    def test_exporter_module_importable(self, module_name):
        """Each exporter module should import without circular import errors."""
        # Remove cached modules to force a fresh import
        modules_to_remove = [
            key for key in sys.modules if key.startswith("exporters")
        ]
        for key in modules_to_remove:
            del sys.modules[key]

        try:
            mod = importlib.import_module(module_name)
            assert mod is not None
        except ImportError as e:
            error_msg = str(e)
            assert "circular" not in error_msg.lower(), (
                f"Circular import detected in {module_name}: {e}"
            )
            # Allow missing optional dependency (python-docx)
            if "docx" not in error_msg.lower():
                raise

    def test_exporters_package_importable(self):
        """The exporters package itself should import without errors."""
        import exporters

        assert exporters is not None
