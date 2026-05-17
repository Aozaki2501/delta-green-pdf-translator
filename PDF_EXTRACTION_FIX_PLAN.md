# PDF Extraction Layout Fix Plan

## Goal

Fix text extraction order for two-column PDFs, especially pages where images, right-column headings, or boxed story text confuse the current block sorter.

## Plan

1. Inspect `uploads/Delta Green Presence PDF 1.pdf` and find suspicious pages.
2. Fix right-column headings being treated as full-page title cards.
3. Improve two-column ordering so body text stays in natural reading order.
4. Tighten card detection so ordinary character/story blocks are not boxed as cards.
5. Run focused extraction checks and unit tests.

## Progress

- Started: inspect current extraction behavior.
- Updated: right-column headings no longer qualify as full-page title cards.
- Updated: non-body card grouping now keeps blocks in the same column before boxing them.
- Updated: card sections now use the same two-column reading order as normal body text.
- Checked: `uploads/Delta Green Presence PDF 1.pdf` no longer shows left/right/left reading-order jumps in the extraction scan.
- Checked: full test suite passes.
- Updated: full-width section titles are marked during extraction and start a new reading page in exported Markdown, HTML, and Word.
