# Tools

Small diagnostics used while tuning PDF extraction.

```powershell
python tools\pdf_block_report.py "book.pdf" --pages 35,38,51
python tools\card_detection_report.py "book.pdf" --pages 33-36
```

These tools do not call the translation API.
