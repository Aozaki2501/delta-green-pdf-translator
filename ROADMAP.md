# ROADMAP.md

Development plan for Delta Green PDF Translator.

This file tracks feature work that improves reliability, proofreading speed, and long-document workflow.

## Status Legend

- `[ ]` Not started
- `[~]` In progress
- `[x]` Done

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

Status: `[x]`

Goal:
- Reduce the size and coupling of `translate_pdf.py`.

Ideas:
- `extractor.py`
- `translator.py`
- `progress.py`
- `exporters/word.py`
- `exporters/markdown.py`
- `exporters/pdf_overlay.py`

Implemented:
- `translate_pdf.py` now acts as the CLI/orchestrator and compatibility re-export layer.
- Core logic is split into `core/`.
- Markdown, HTML, and Word output are split into `exporters/`.

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

Status: `[x]`

Goal:
- Make Web UI feel like a local translation workstation.

Ideas:
- List recent files in `output/`.
- Show generated time, size, and format.
- Provide download buttons for previous outputs.

Implemented:
- Web UI lists recent output folders.
- Each history item shows generated time, total size, available formats, image count, completed pages, and failed pages.
- Previous Markdown, HTML, Word, progress, extraction report, and glossary report files can be downloaded again.

### 10. Classified Workstation Polish

Status: `[x]`

Goal:
- Make the Web UI feel like a real classified local workstation, not just a themed upload form.

Priority:
- Task dossier ID.
- Task status flow.
- Audit summary in current task and output history.
- Animated system log.
- File scan line when a PDF is loaded.
- Completion stamp.
- Download authorization feedback.

Decision:
- Split Web UI helpers into `webui/` modules so `app.py` does not keep growing.

Implemented:
- Added `webui/` modules for history scanning, audit helpers, visual effects, and reusable Streamlit components.
- Uploading a PDF shows a dossier ID, file digest, glossary source, scan animation, status flow, and system log.
- Translation runs write an `_audit.json` record with dossier ID, source file, model, page range, formats, completed pages, failed pages, and output files.
- Output history reads audit records and shows the dossier ID plus audit summary.
- Completion shows an archive stamp, and download buttons have authorization feedback.
- Added second-pass motion polish: status signal sweep, alert ping, metric sweep, history drawer animation, staggered log lines, and a low-motion mode.
