# Implementation Plan: Module Refactor

## Overview

Decompose the monolithic `translate_pdf.py` (~2625 lines) into a well-organized package structure with `core/` and `exporters/` packages, preserving all existing functionality via a backward-compatible re-export layer. Implementation follows the dependency graph: constants first, then utils, then other core modules, then exporters, then the re-export layer, then tests.

## Tasks

- [x] 1. Create package structure and leaf-node modules
  - [x] 1.1 Create `core/` package with `__init__.py` and `constants.py`
    - Create `core/` directory with empty `__init__.py`
    - Extract `PROMPT_VERSION`, `EXTRACTOR_VERSION`, `SUPPORTED_OUTPUT_FORMATS`, and `TRANSLATION_FAILURE_PREFIX` from `translate_pdf.py` into `core/constants.py`
    - Ensure `constants.py` has no imports from other project modules (leaf node)
    - _Requirements: 1.1, 9.1_

  - [x] 1.2 Create `core/utils.py` with utility functions
    - Extract `configure_console_output`, `ensure_output_parent`, `normalize_page_range`, `is_failed_translation`, `parse_page_selection`, and `file_sha256` from `translate_pdf.py` into `core/utils.py`
    - Add import of `TRANSLATION_FAILURE_PREFIX` from `core.constants`
    - Verify no other intra-project dependencies exist
    - _Requirements: 1.1, 9.2, 9.3_

- [x] 2. Extract core domain modules
  - [x] 2.1 Create `core/glossary.py`
    - Extract `load_glossary`, `find_relevant_glossary_terms`, `build_glossary_report`, and `write_glossary_report` from `translate_pdf.py` into `core/glossary.py`
    - Add import of `ensure_output_parent` from `core.utils`
    - Ensure no dependency on extractor, translator, or UI modules
    - _Requirements: 1.1, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [x] 2.2 Create `core/extractor.py`
    - Extract `PDFExtractor`, `ChapterDetector`, and `HeadingInfo` from `translate_pdf.py` into `core/extractor.py`
    - Add imports from `core.constants` as needed
    - Preserve all public method signatures, constructor parameters, and context manager protocol
    - _Requirements: 1.1, 5.1, 5.2, 5.3, 5.4_

  - [x] 2.3 Create `core/translator.py`
    - Extract `Translator`, `TokenStats`, and `translate_batch_concurrent` from `translate_pdf.py` into `core/translator.py`
    - Add imports from `core.constants` and `core.glossary` (for `find_relevant_glossary_terms`)
    - Preserve retry logic (3 attempts with 5s/10s/15s delays), failure-prefix behavior, and concurrency control
    - _Requirements: 1.1, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 2.4 Create `core/progress.py`
    - Extract `ProgressTracker`, `build_progress_metadata`, and `compare_progress_metadata` from `translate_pdf.py` into `core/progress.py`
    - Add import of `file_sha256` from `core.utils`
    - Preserve thread-safe locking, atomic file writes, and metadata fingerprint logic
    - _Requirements: 1.1, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [x] 3. Create `core/__init__.py` public interface
  - [x] 3.1 Populate `core/__init__.py` with re-exports
    - Import and re-export all public symbols from `constants`, `utils`, `glossary`, `extractor`, `translator`, and `progress` submodules
    - Ensure all symbols listed in the Public_API glossary are accessible via `from core import ...`
    - Verify no circular import errors by importing `core` in isolation
    - _Requirements: 1.4, 9.3_

- [x] 4. Create exporter modules
  - [x] 4.1 Create `exporters/` package with `__init__.py` and `_shared.py`
    - Create `exporters/` directory with empty `__init__.py`
    - Extract shared text-processing helpers (`_split_translation_chunks`, `_translation_blocks`, `_clean_translated_block`, `_clean_decorative_slash_line`, `_dedupe_adjacent_repeated_units`, `_visible_text_length`, `_is_markdown_heading`, `_is_plain_heading_line`, `_format_page_ranges`, `paginate_translated_blocks`) into `exporters/_shared.py`
    - Add imports from `core.constants` and `core.utils` as needed
    - _Requirements: 8.9, 11.1, 11.2, 11.4_

  - [x] 4.2 Create `exporters/html.py`
    - Extract `write_html_output` and all HTML-specific internal helpers from `translate_pdf.py` into `exporters/html.py`
    - Add import of shared helpers from `exporters._shared`
    - _Requirements: 8.1, 8.5_

  - [x] 4.3 Create `exporters/word.py`
    - Extract `write_word_output`, `HAS_DOCX`, `set_section_columns`, `set_cell_width`, `remove_table_borders`, `set_section_page_layout`, `set_running_header_footer`, and `set_document_base_layout` from `translate_pdf.py` into `exporters/word.py`
    - Implement `HAS_DOCX` as a module-level boolean based on `python-docx` importability
    - Add import of shared helpers from `exporters._shared`
    - _Requirements: 8.2, 8.6, 8.8_

  - [x] 4.4 Create `exporters/markdown.py`
    - Extract `write_markdown_output` and Markdown-specific helpers from `translate_pdf.py` into `exporters/markdown.py`
    - Add import of shared helpers from `exporters._shared`
    - _Requirements: 8.3, 8.7_

  - [x] 4.5 Populate `exporters/__init__.py` with re-exports
    - Import and re-export `write_html_output`, `write_word_output`, `write_markdown_output`, and `paginate_translated_blocks`
    - Verify no circular import errors by importing `exporters` in isolation
    - _Requirements: 1.5, 8.4, 9.4_

- [x] 5. Checkpoint - Verify package imports
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Refactor `translate_pdf.py` into re-export layer + CLI
  - [x] 6.1 Replace monolithic code with re-export shim and CLI orchestration
    - Remove all extracted class/function definitions from `translate_pdf.py`
    - Add re-export imports from `core` and `exporters` packages for all 15 Public_API symbols plus `HAS_DOCX`
    - Keep `translate_pdf()` orchestrator function, `load_config()`, and `main()` in place
    - Ensure `if __name__ == "__main__": main()` remains at the bottom
    - Verify that `from translate_pdf import PDFExtractor, Translator, ...` resolves all 15 symbols
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 7. Checkpoint - Verify backward compatibility
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Create test infrastructure and unit tests
  - [x] 8.1 Create `tests/` package and `tests/test_imports.py`
    - Create `tests/` directory with `__init__.py`
    - Write import smoke tests verifying all 15 Public_API symbols importable from `translate_pdf`
    - Write tests verifying no circular imports by importing each module individually
    - _Requirements: 10.1, 10.6_

  - [x] 8.2 Create `tests/test_utils.py` with unit tests
    - Write tests for `normalize_page_range` with valid boundary values (start=0, end=total_pages)
    - Write tests for `normalize_page_range` with invalid inputs (negative start, start >= total_pages, end <= start) expecting ValueError
    - Write tests for `parse_page_selection` converting "8, 12-15" to zero-based index sets
    - Write tests for `is_failed_translation` returning True for failure-prefixed strings and False for normal/empty strings
    - _Requirements: 10.2, 10.3, 10.5_

  - [x] 8.3 Create `tests/test_glossary.py` with unit tests
    - Write tests for `load_glossary` parsing TSV with tab-separated pairs, skipping comments and blanks
    - Write tests for `load_glossary` with None/empty/nonexistent path returning empty dict
    - Write tests for `find_relevant_glossary_terms` using in-memory glossary dicts
    - _Requirements: 10.4, 10.7_

  - [x] 8.4 Create `tests/test_progress.py` with unit tests
    - Write tests for ProgressTracker save/load round-trip using temporary files
    - Write tests for metadata mismatch detection and discard behavior
    - Write tests for invalid JSON recovery (start with empty state)
    - _Requirements: 10.1_

  - [ ]* 8.5 Write property test for page range normalization
    - **Property 11: Page range normalization**
    - **Validates: Requirements 9.2, 9.5**

  - [ ]* 8.6 Write property test for is_failed_translation detection
    - **Property 12: is_failed_translation detection**
    - **Validates: Requirements 9.2**

  - [ ]* 8.7 Write property test for glossary TSV parsing
    - **Property 8: Glossary TSV parsing**
    - **Validates: Requirements 7.2**

  - [ ]* 8.8 Write property test for glossary term matching
    - **Property 9: Glossary term matching — longest-match-first, non-overlapping**
    - **Validates: Requirements 7.4**

  - [ ]* 8.9 Write property test for glossary report structure
    - **Property 10: Glossary report structure**
    - **Validates: Requirements 7.5**

  - [ ]* 8.10 Write property test for progress file round-trip
    - **Property 3: Progress file round-trip**
    - **Validates: Requirements 4.1, 4.2**

  - [ ]* 8.11 Write property test for metadata fingerprint determinism
    - **Property 4: Metadata fingerprint determinism**
    - **Validates: Requirements 4.3**

  - [ ]* 8.12 Write property test for metadata mismatch detection
    - **Property 5: Metadata mismatch detection**
    - **Validates: Requirements 4.4**

  - [ ]* 8.13 Write property test for thread-safe progress tracking
    - **Property 6: Thread-safe progress tracking**
    - **Validates: Requirements 4.5**

  - [ ]* 8.14 Write property test for concurrency limit
    - **Property 7: Concurrency limit**
    - **Validates: Requirements 6.4**

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The dependency order (constants → utils → core modules → exporters → re-export layer → tests) ensures each step builds on completed prior work
- No API keys, network access, or PDF files are required for unit-level tests

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "2.2"] },
    { "id": 3, "tasks": ["2.3", "2.4"] },
    { "id": 4, "tasks": ["3.1"] },
    { "id": 5, "tasks": ["4.1"] },
    { "id": 6, "tasks": ["4.2", "4.3", "4.4"] },
    { "id": 7, "tasks": ["4.5"] },
    { "id": 8, "tasks": ["6.1"] },
    { "id": 9, "tasks": ["8.1", "8.2", "8.3", "8.4"] },
    { "id": 10, "tasks": ["8.5", "8.6", "8.7", "8.8", "8.9", "8.10", "8.11", "8.12", "8.13", "8.14"] }
  ]
}
```
