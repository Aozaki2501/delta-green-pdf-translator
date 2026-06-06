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


def _import_with_fresh_package(module_name: str, package_prefix: str):
    """Import a module after clearing its package, then restore test state."""
    original_modules = {
        key: value for key, value in sys.modules.items()
        if key.startswith(package_prefix)
    }
    modules_to_remove = [
        key for key in sys.modules if key.startswith(package_prefix)
    ]
    for key in modules_to_remove:
        del sys.modules[key]

    try:
        return importlib.import_module(module_name)
    finally:
        current_modules = [
            key for key in sys.modules if key.startswith(package_prefix)
        ]
        for key in current_modules:
            del sys.modules[key]
        sys.modules.update(original_modules)


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
        "core.layout_adapters",
        "core.layout_hints",
        "core.translator",
        "core.progress",
        "core.dispatcher",
        "core.page_structure",
        "core.recursive_splitter",
        "core.semantic_analyzer",
        "core.typeset_models",
        "core.typeset_pipeline",
        "core.typeset_translation",
    ]

    @pytest.mark.parametrize("module_name", CORE_MODULES)
    def test_core_module_importable(self, module_name):
        """Each core module should import without circular import errors."""
        try:
            mod = _import_with_fresh_package(module_name, "core")
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
        "exporters.word",
        "exporters.markdown",
        "exporters.typeset_html",
        "exporters.typeset_pdf",
    ]

    @pytest.mark.parametrize("module_name", EXPORTER_MODULES)
    def test_exporter_module_importable(self, module_name):
        """Each exporter module should import without circular import errors."""
        try:
            mod = _import_with_fresh_package(module_name, "exporters")
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
