# ROADMAP.md

Development plan for Delta Green PDF Translator.

This file tracks feature work that improves reliability, proofreading speed, and long-document workflow.

## Status Legend

- `[ ]` Not started
- `[~]` In progress
- `[x]` Done
- `[-]` Not planned

## Current Priority

### 1. Progress Fingerprint

Status: `[x]`

Goal:
- Avoid accidentally reusing stale translations when the PDF, glossary, model, prompt, or extraction logic changes.

Planned behavior:
- Save metadata inside each `.progress.json`.
- Metadata should include PDF hash, glossary hash, model, prompt version, extractor version, and requested page range.
- Web UI should warn when existing progress metadata does not match current settings.
- Existing progress files must not be deleted automatically.

### 2. Retranslate Selected Pages

Status: `[x]`

Goal:
- Let the operator retranslate only bad pages without manually editing progress files.

Planned behavior:
- Add a Web input such as `8, 12-15`.
- Convert those visible page numbers to internal zero-based page indexes.
- Remove those pages from the active progress cache before translation.
- Keep all other completed pages.

### 3. Extraction Preview And Diagnostics

Status: `[x]`

Goal:
- Make PDF extraction problems visible before spending API calls.

Planned behavior:
- Add a Web preview panel for one selected page.
- Show extracted text after layout sorting and cleanup.
- Show detected source page count and selected translation range.
- Optionally show blocked/empty extraction warnings.

## Next Candidates

### 4. Glossary Hit Report

Status: `[x]`

Goal:
- Explain which glossary terms were actually sent to the model for each page.

Ideas:
- Export `glossary_report.md`.
- Show missing capitalized terms that may need glossary entries.
- Detect possible conflicts or overlapping terms.

Implemented:
- Web and CLI generate `_glossary_report.md` when a glossary is active.
- Report includes glossary hits by page, summary by term, and suspected unlisted proper nouns.

### 5. Word Export Controls

Status: `[x]`

Goal:
- Make Word layout adjustable without editing code.

Ideas:
- Body font size.
- Line spacing.
- Single/double column.
- Reading page character range.
- Running header text.

Implemented:
- Web controls body font size, line spacing, one/two columns, reading page character range, and running header text.
- Defaults preserve the current proofreading-friendly layout.

### 6. Failed Page Management

Status: `[x]`

Goal:
- Separate failed pages from completed pages.

Ideas:
- Store `failed_pages` in progress.
- Web button for retrying failed pages only.
- Avoid writing API error text into final output as normal translation.

Implemented:
- Failed pages are saved under `failed_pages`.
- Web and CLI can retry failed pages only.
- Failed text is not stored as a completed translation.

### 7. Core Module Split

Status: `[-]`

Goal:
- Reduce the size and coupling of `translate_pdf.py`.

Ideas:
- `extractor.py`
- `translator.py`
- `progress.py`
- `exporters/word.py`
- `exporters/markdown.py`
- `exporters/pdf_overlay.py`

Decision:
- Not needed for the current workflow. Keep this off the active plan unless maintenance pressure returns.

### 8. Minimal Regression Tests

Status: `[~]`

Goal:
- Protect the fragile PDF layout and glossary behavior.

Ideas:
- Dual-column block sorting.
- Full-width heading ordering.
- Header/footer filtering.
- Longest glossary match.
- Word output smoke test.

Implemented:
- Added focused tests for failed-page tracking, extraction diagnostics, and image asset rendering.

### 9. Output History

Status: `[~]`

Goal:
- Make Web UI feel like a local translation workstation.

Ideas:
- List recent files in `output/`.
- Show generated time, size, format, page count, failed page count, and estimated cost.
- Provide download buttons for previous Word, HTML, Markdown, extraction report, and glossary report files.
- Allow reopening an old task from its progress file.

Implemented:
- Web UI shows recent tasks from `output/`.
- History rows show status, update time, translated page count, failed page count, page range, model, worker count, and cost when recorded.
- Previous Word, HTML, Markdown, extraction report, and glossary report files can be downloaded from the history panel.
- New Web translation tasks write a `.history.json` manifest with generated files, cost, token count, model, provider, and worker count.
- Damaged progress files are shown as damaged instead of being silently ignored.

Remaining:
- Reopen an old task directly from its progress file.

### 10. Preflight Check Before API Calls

Status: `[x]`

Goal:
- Let the operator understand cost and risk before spending API quota.

Ideas:
- Scan the selected page range before translation starts.
- Show selected page count, extracted text coverage, risky pages, empty pages, image count, and glossary hit count.
- Estimate cost and rough duration from page count, selected model, and current worker count.
- Require one explicit start action after the preflight result is visible.

Implemented:
- Web UI requires a preflight scan for the current task before the translation button is enabled.
- Preflight scans the selected page range without calling the translation API.
- The report shows page count, risky pages, empty pages, image count, glossary hit count, model, worker count, estimated cost, and estimated duration.
- Changing the PDF, glossary, page range, model, provider, base URL, output formats, retry mode, retranslation pages, or worker count invalidates the old preflight result.

### 11. Side-by-side Proofreading View

Status: `[ ]`

Goal:
- Make proofreading and targeted retranslation faster inside the Web UI.

Ideas:
- Show source text and translated text side by side for each page.
- Let the operator mark pages as good, suspicious, or needing retranslation.
- Send marked pages directly into the existing selected-page retranslation flow.
- Keep the final Word/HTML export separate from the proofreading view.

### 12. Glossary Manager

Status: `[x]`

Goal:
- Make `glossary.tsv` editable without leaving the Web UI.

Ideas:
- Show glossary entries in a searchable table.
- Add, edit, delete, and save TSV entries.
- Detect duplicate English terms, duplicate Chinese translations, empty fields, and suspicious encoding damage.
- Surface unlisted proper nouns from the glossary report as candidate entries.

Implemented:
- Web UI can open and edit the default `glossary.tsv`.
- Entries can be searched, appended, validated, normalized, and saved from the browser.
- Empty fields, duplicate English terms, replacement characters, and suspicious question marks in the Chinese column block saving.
- Duplicate Chinese translations are shown as warnings.

Remaining:
- Surface unlisted proper nouns from glossary reports as one-click candidate entries.

### 13. Failed And Suspicious Page Action Panel

Status: `[x]`

Goal:
- Make recovery actions obvious after a long translation task finishes.

Ideas:
- After translation, list failed pages, extraction-risk pages, empty pages, and user-marked suspicious pages.
- Provide direct buttons to retry failed pages or retranslate selected risky pages.
- Keep failed translations out of final exports until they are successfully retried.

Implemented:
- After translation, Web UI lists failed pages, extraction-risk pages, empty pages, and the combined action target count.
- The panel produces a ready-to-use page selection for retranslation.
- Buttons can fill the selected pages into the retranslation field or enable failed-page retry for the next run.

Remaining:
- Include user-marked suspicious pages after the proofreading view exists.

### 14. Promote Diagnostic Scripts

Status: `[x]`

Goal:
- Make useful local debugging scripts available on other machines and in Codex sessions.

Ideas:
- Review current ignored scripts: `diag_*.py` and `test_card_*.py`.
- Move still-useful checks into `tests/` or `tools/`.
- Delete or keep ignored any one-off scripts that no longer describe a stable workflow.
- Document how to run the promoted checks.

Implemented:
- Replaced hardcoded local diagnostics with reusable tools under `tools/`.
- Added `tools/pdf_block_report.py` for text blocks, fonts, drawings, and image diagnostics.
- Added `tools/card_detection_report.py` for card-marker extraction diagnostics.
- Added `tools/README.md` with usage examples.
- Added tests for glossary editor validation and tool script help output.
