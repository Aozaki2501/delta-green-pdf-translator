# Requirements Document

## Introduction

Refactor the DGtranslate project by decomposing the monolithic `translate_pdf.py` (~2625 lines) into well-organized modules grouped by responsibility domain. The refactoring preserves all existing functionality, CLI arguments, user workflows, and backward compatibility for both the CLI entry point and the Streamlit Web UI (`app.py`).

## Glossary

- **Monolith**: The current single-file implementation `translate_pdf.py` containing all project logic
- **Re_Export_Layer**: A backward-compatible shim in `translate_pdf.py` that imports and re-exports all public symbols from the new modules
- **Core_Package**: The `core/` Python package containing domain logic modules (extractor, translator, progress, glossary, constants, utils)
- **Exporters_Package**: The `exporters/` Python package containing output format writers (HTML, Word, Markdown)
- **Public_API**: The set of symbols currently imported by `app.py`: PDFExtractor, Translator, ProgressTracker, TokenStats, load_glossary, translate_batch_concurrent, write_markdown_output, write_html_output, write_word_output, HAS_DOCX, build_progress_metadata, parse_page_selection, write_glossary_report, normalize_page_range, is_failed_translation
- **CLI_Entry_Point**: The `main()` function and `translate_pdf()` orchestrator invoked via `python translate_pdf.py`
- **Progress_File**: The `.progress.json` file storing translation state, metadata fingerprint, and completed page translations
- **Glossary_File**: The TSV file mapping English TRPG terms to Chinese translations

## Requirements

### Requirement 1: Module Decomposition

**User Story:** As a developer, I want translate_pdf.py split into focused modules by responsibility domain, so that I can navigate, test, and maintain each concern independently.

#### Acceptance Criteria

1. THE Core_Package SHALL contain one Python file per responsibility domain: `constants.py` (configuration constants and prompt versions), `utils.py` (console configuration, path helpers, page-range normalization), `extractor.py` (PDFExtractor and ChapterDetector classes), `translator.py` (API client, prompt construction, retry logic, and batch concurrency), `progress.py` (ProgressTracker and progress-reporting logic), and `glossary.py` (glossary loading, parsing, and term-matching)
2. THE Exporters_Package SHALL contain one Python file per output format: `html.py` for HTML output, `word.py` for Word/DOCX output, and `markdown.py` for Markdown output
3. WHEN a module is created, THE module SHALL contain only classes, functions, and module-level constants that operate within its single declared responsibility, and SHALL NOT define symbols whose primary purpose belongs to another module's domain
4. THE Core_Package SHALL expose a public interface via `core/__init__.py` that re-exports every class and function currently imported by `app.py` and the CLI entry point, so that consumer import paths resolve without modification beyond updating the package prefix
5. THE Exporters_Package SHALL expose a public interface via `exporters/__init__.py` that re-exports the top-level output-generation function from each writer module (HTML, Word, and Markdown)
6. WHEN all modules are assembled, THE system SHALL produce identical output for a given PDF input as the original monolithic `translate_pdf.py`, verifiable by running the existing test suite or CLI with no functional regression
7. THE Core_Package and Exporters_Package SHALL contain no circular import dependencies between their constituent modules

### Requirement 2: Backward-Compatible Re-Export Layer

**User Story:** As a Web UI maintainer, I want existing import statements in app.py to continue working without modification, so that the refactoring does not break the Streamlit interface.

#### Acceptance Criteria

1. THE Re_Export_Layer SHALL import and re-export every symbol listed in criterion 2 from the refactored submodules, exposed at the `translate_pdf` import path
2. WHEN `app.py` executes `from translate_pdf import PDFExtractor, Translator, ProgressTracker, TokenStats, load_glossary, translate_batch_concurrent, write_markdown_output, write_html_output, write_word_output, HAS_DOCX, build_progress_metadata, parse_page_selection, write_glossary_report, normalize_page_range, is_failed_translation`, THE Re_Export_Layer SHALL resolve all 15 symbols without raising ImportError, and each symbol SHALL reference the same class, function, or constant object as the pre-refactor `translate_pdf.py`
3. THE Re_Export_Layer SHALL expose `HAS_DOCX` as a module-level boolean that evaluates to `True` when the `python-docx` package is importable at runtime and `False` otherwise
4. IF a refactored submodule fails to import due to a missing dependency other than `python-docx`, THEN THE Re_Export_Layer SHALL raise ImportError with an error message indicating which dependency is missing

### Requirement 3: CLI Preservation

**User Story:** As an end user, I want the CLI interface to remain identical after refactoring, so that my existing scripts and GUIDE.md instructions continue to work.

#### Acceptance Criteria

1. WHEN invoked as `python translate_pdf.py <args>`, THE CLI_Entry_Point SHALL accept the following arguments with identical names, short aliases, types, and defaults: positional `pdf` (optional, default None), `--config`/`-c` (default None), `--api-key` (default None), `--output`/`-o` (default None), `--glossary`/`-g` (default None), `--model` (default None, resolved default "deepseek-v4-pro"), `--format`/`-f` (choices: markdown, html, word, both, all; default None, resolved default "markdown"), `--workers`/`-w` (int, default None, resolved default 1), `--start` (int, default None, resolved default 0), `--end` (int, default None)
2. WHEN the `--config` argument specifies a JSON configuration file, THE CLI_Entry_Point SHALL load that file and apply the precedence rule: command-line arguments override config file values, and config file values override built-in defaults
3. WHEN no `--output` path is provided, THE CLI_Entry_Point SHALL derive the output base path as `{pdf_stem}_cn` in the current working directory, appending the appropriate extension (`.md`, `.html`, `.docx`) based on the selected format
4. WHEN the `--format` argument specifies a format and the same PDF input and API responses are provided, THE CLI_Entry_Point SHALL generate output files with content identical to the pre-refactoring version
5. IF a required parameter (pdf path or api_key) is missing after merging CLI arguments and config file, THEN THE CLI_Entry_Point SHALL print a diagnostic message to stdout and exit with a non-zero exit code

### Requirement 4: Progress File Compatibility

**User Story:** As a translator, I want existing progress files to remain usable after the refactoring, so that I do not lose completed translation work.

#### Acceptance Criteria

1. THE ProgressTracker SHALL read and write `.progress.json` files as JSON objects containing three top-level keys: `metadata` (object), `completed_pages` (sorted integer array), and `translations` (object keyed by string page number)
2. WHEN a pre-refactoring progress file is loaded, THE ProgressTracker SHALL restore all entries from `completed_pages` and `translations` and skip re-translation of those pages
3. THE ProgressTracker SHALL generate metadata fingerprints using SHA-256 file hashes (PDF, glossary) combined with model name, prompt version, extractor version, start page, and end page, and SHALL include a `schema` version field
4. IF the loaded progress file metadata does not match the current expected metadata, THEN THE ProgressTracker SHALL report the mismatched fields and discard cached translations unless `reuse_mismatched` is enabled
5. WHILE multiple translation threads access the ProgressTracker, THE ProgressTracker SHALL serialize access to in-memory state via a lock and persist changes atomically using a temporary file followed by an atomic rename
6. IF the progress file contains invalid JSON or an unexpected root type, THEN THE ProgressTracker SHALL discard the file contents and start with empty state without raising an unhandled exception

### Requirement 5: PDF Extraction Module

**User Story:** As a developer, I want PDF extraction logic isolated in its own module, so that I can test layout detection and text extraction independently.

#### Acceptance Criteria

1. THE `core/extractor.py` module SHALL contain the PDFExtractor class and ChapterDetector class with the same public method signatures and constructor parameters as the monolithic `translate_pdf.py` version
2. WHEN PDFExtractor.extract_page is called for any given page number, THE `core/extractor.py` PDFExtractor SHALL return a string that is character-for-character equal to the string returned by the monolithic version for the same PDF page
3. THE PDFExtractor SHALL preserve dual-column layout detection, header/footer filtering, card section detection, and table extraction behavior such that detect_page_layout returns the same layout classification and extracted card/body sections contain the same text content as the monolithic version for any given page
4. WHEN ChapterDetector.get_toc_markdown is called after processing the same set of pages, THE `core/extractor.py` ChapterDetector SHALL return a string that is character-for-character equal to the string returned by the monolithic version
5. WHEN PDFExtractor or ChapterDetector is imported from `translate_pdf.py`, THE system SHALL re-export the classes from `core/extractor.py` so that existing code using the monolithic import path continues to function without modification

### Requirement 6: Translation Engine Module

**User Story:** As a developer, I want the translation engine isolated in its own module, so that I can test API interaction and concurrency logic independently.

#### Acceptance Criteria

1. THE `core/translator.py` module SHALL contain the Translator class, TokenStats class, and translate_batch_concurrent function, and SHALL be importable without depending on PDF extraction, UI framework, or output-formatting modules
2. WHEN translate_batch_concurrent is called with the same pages_data list, Translator instance, ProgressTracker instance, max_workers value, and progress_callback function, THE function SHALL return a dictionary mapping page numbers to translation strings identical to those produced by the monolithic translate_batch_concurrent under the same API responses
3. THE Translator class SHALL accept api_key, model, base_url, and stats parameters at construction, expose a set_glossary method that accepts a dict, and expose a translate_chunk method that accepts text, page_num, and prev_context parameters with signatures matching the monolithic version
4. WHILE concurrent translation is active, THE translate_batch_concurrent function SHALL execute no more than max_workers concurrent API calls at any point in time
5. WHEN a page translation completes or is loaded from cache, THE translate_batch_concurrent function SHALL invoke progress_callback with four positional arguments: page_num (int), translation (str), completed_count (int), and total_count (int)
6. IF the API returns an error for a page translation, THEN THE Translator class SHALL retry up to 3 attempts with increasing delay before returning a failure-prefixed string, and translate_batch_concurrent SHALL exclude that page from being marked as completed in the ProgressTracker

### Requirement 7: Glossary Module

**User Story:** As a developer, I want glossary logic isolated in its own module, so that I can test term matching and report generation independently.

#### Acceptance Criteria

1. THE `core/glossary.py` module SHALL export load_glossary, find_relevant_glossary_terms, build_glossary_report, and write_glossary_report functions, each importable without requiring application-level dependencies such as Streamlit or the PDF extractor
2. WHEN load_glossary is called with a valid TSV file path, THE function SHALL return a dictionary mapping English terms (keys) to Chinese translations (values), skipping comment lines starting with "#" and blank lines, producing the same entries as the monolithic version in translate_pdf.py
3. IF load_glossary is called with a file path that is empty, None, or points to a nonexistent file, THEN THE function SHALL return an empty dictionary without raising an exception
4. WHEN find_relevant_glossary_terms is called with a text string and a glossary dictionary, THE function SHALL return a dictionary of matched terms using longest-match-first, non-overlapping span selection, such that for any given input text the returned keys and values are identical to those produced by the monolithic version
5. WHEN write_glossary_report is called with a pages_text dictionary, a glossary dictionary, an output file path, and an optional title, THE function SHALL write a Markdown report containing three sections: a per-term summary with page numbers, per-page glossary hits, and suspected unlisted proper nouns, matching the section structure and content of the monolithic build_glossary_report output
6. IF write_glossary_report is called with an output path whose parent directory does not exist, THEN THE function SHALL create the parent directory before writing the report file

### Requirement 8: Exporter Modules

**User Story:** As a developer, I want each output format writer in its own module, so that I can modify one format without risk to others.

#### Acceptance Criteria

1. THE `exporters/html.py` module SHALL contain write_html_output and all HTML-specific helper functions
2. THE `exporters/word.py` module SHALL contain write_word_output, HAS_DOCX flag, and all Word-specific helper functions (set_section_columns, set_cell_width, remove_table_borders, set_section_page_layout, set_running_header_footer, set_document_base_layout)
3. THE `exporters/markdown.py` module SHALL contain write_markdown_output and Markdown-specific helper functions
4. THE `exporters/__init__.py` module SHALL re-export write_html_output, write_word_output, write_markdown_output, and paginate_translated_blocks so that existing import paths continue to work
5. WHEN write_html_output is called with identical translated_pages list, output path, title, and formatting parameters, THE function SHALL produce byte-identical HTML file content as the same function in the monolithic translate_pdf.py
6. WHEN write_word_output is called with identical translated_pages list, output path, title, and formatting parameters, THE function SHALL produce a Word document with identical paragraph text, heading levels, styles, column layout, and header/footer content as the same function in the monolithic translate_pdf.py, excluding internal metadata such as timestamps or unique identifiers
7. WHEN write_markdown_output is called with identical translated_pages list, output path, title, and toc string, THE function SHALL produce byte-identical Markdown file content as the same function in the monolithic translate_pdf.py
8. IF write_word_output is called and the python-docx package is not installed, THEN THE `exporters/word.py` module SHALL set HAS_DOCX to False and write_word_output SHALL raise a RuntimeError indicating the missing dependency
9. THE paginate_translated_blocks function SHALL reside in a shared location importable by all three exporter modules without circular dependencies

### Requirement 9: Constants and Utilities Module

**User Story:** As a developer, I want shared constants and utility functions in dedicated modules, so that all other modules can import them without circular dependencies.

#### Acceptance Criteria

1. THE `core/constants.py` module SHALL export the following constants: PROMPT_VERSION (str), EXTRACTOR_VERSION (str), SUPPORTED_OUTPUT_FORMATS (set containing "markdown", "html", "word", "both", "all"), and TRANSLATION_FAILURE_PREFIX (str)
2. THE `core/utils.py` module SHALL export the following functions: ensure_output_parent(path: str) which creates parent directories, normalize_page_range(start_page, end_page, total_pages: int) which returns a validated (start, end) tuple, is_failed_translation(text: str) which returns True when text starts with TRANSLATION_FAILURE_PREFIX, parse_page_selection(selection: str, total_pages: int) which returns a set of zero-based page indexes, file_sha256(path: str) which returns the hex digest of a file or empty string if the file does not exist, and configure_console_output() which sets stream error handling to "replace"
3. THE Core_Package SHALL have no circular import dependencies between its modules, verifiable by importing each module individually without ImportError
4. THE Exporters_Package SHALL depend only on the Core_Package and standard library, with no circular dependencies, verifiable by importing each exporter module individually without ImportError
5. IF normalize_page_range receives a start_page that is negative or greater than or equal to total_pages, or an end_page less than or equal to start_page, THEN THE `core/utils.py` module SHALL raise a ValueError with a descriptive message

### Requirement 10: Test Infrastructure

**User Story:** As a developer, I want unit tests for the extracted modules, so that I can verify correctness after refactoring and catch regressions in future changes.

#### Acceptance Criteria

1. THE `tests/` package SHALL contain at least one test module for each of the following: glossary, extractor, progress, and utils
2. WHEN tests are executed, THE test suite SHALL verify that `normalize_page_range` returns the correct (start, end) tuple for valid inputs including boundary values (start=0, end=total_pages) and that `parse_page_selection` converts 1-based comma/range strings (e.g. "8, 12-15") into the expected zero-based index sets
3. WHEN tests are executed, THE test suite SHALL verify that `is_failed_translation` returns True only for strings starting with the `TRANSLATION_FAILURE_PREFIX` and False for normal text and empty strings
4. WHEN tests are executed, THE test suite SHALL verify that `load_glossary` parses a TSV file with tab-separated English→Chinese pairs, skips comment lines starting with "#", skips blank lines, and returns a dict mapping English terms to Chinese terms
5. IF invalid input is provided to `normalize_page_range` or `parse_page_selection` (e.g. start >= total_pages, out-of-range page numbers, non-numeric strings), THEN THE test suite SHALL verify that a `ValueError` is raised
6. THE test suite SHALL be runnable via `pytest` without requiring API keys, network access, or PDF files for unit-level tests
7. WHEN glossary term matching is tested, THE test suite SHALL use an in-memory glossary dict rather than loading external files

### Requirement 11: Shared Helper Accessibility

**User Story:** As a developer, I want helper functions used by multiple exporters to be accessible without duplication, so that formatting logic remains consistent across output formats.

#### Acceptance Criteria

1. WHEN multiple exporter modules (word, markdown, or any future output-format module) require the same helper function, THE helper function SHALL reside in a single shared module rather than being duplicated in each exporter
2. THE shared text-processing helpers (_clean_translated_block, _split_translation_chunks, _translation_blocks, _dedupe_adjacent_repeated_units, _visible_text_length, _is_markdown_heading, _is_plain_heading_line, _format_page_ranges) SHALL be importable by all exporter modules without circular import errors or runtime ImportError exceptions
3. IF a helper function is used by only one exporter module, THEN THE helper function SHALL reside in that exporter module rather than in shared code
4. WHEN an exporter module imports a shared helper, THE import SHALL succeed without requiring imports from other exporter modules (no inter-exporter dependencies)
