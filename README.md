# Delta Green PDF Translator v2.0

TRPG Delta Green expansion book AI translator using DeepSeek V4 API.
Supports dual-column layout detection, glossary, concurrency, and layout-preserving PDF output.

## Features

| Feature | Description |
|---------|-------------|
| Dual-column extraction | Auto-detects TRPG book dual-column layout |
| Context window | Carries previous page translation for cross-page coherence |
| Chapter/TOC detection | Auto-detects headings by font size/bold |
| Layout-preserving PDF | Overlays Chinese text on original PDF |
| Batch concurrency | Multi-threaded parallel translation |
| Glossary | TSV glossary, only relevant terms sent per page |
| Resume | Auto-saves progress, resumes on re-run |
| Cost tracking | Real-time token usage and cost display |

## Install

```bash
pip install pymupdf openai
```

## Usage

### Basic (single-thread, Markdown output)
```bash
python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-YOUR_KEY
```

### Recommended (4 workers + glossary)
```bash
python translate_pdf.py "THE MILLENNIUM.pdf" \\
    --api-key sk-YOUR_KEY \\
    --glossary glossary.tsv \\
    --workers 4
```

### Layout-preserving PDF output
```bash
python translate_pdf.py "THE MILLENNIUM.pdf" \\
    --api-key sk-YOUR_KEY \\
    --format pdf
```

### Both Markdown + PDF
```bash
python translate_pdf.py "THE MILLENNIUM.pdf" \\
    --api-key sk-YOUR_KEY \\
    --format both --workers 4
```

### Translate a range (test first 5 pages)
```bash
python translate_pdf.py "THE MILLENNIUM.pdf" \\
    --api-key sk-YOUR_KEY \\
    --start 0 --end 5
```

### Cheaper model (faster, lower quality)
```bash
python translate_pdf.py "THE MILLENNIUM.pdf" \\
    --api-key sk-YOUR_KEY \\
    --model deepseek-v4-flash --workers 8
```

## Parameters

| Param | Description | Default |
|-------|-------------|---------|
| `pdf` | Input PDF path | required |
| `--api-key` | DeepSeek API Key | required |
| `--output`, `-o` | Output file path | `{name}_cn.md` |
| `--glossary`, `-g` | Glossary TSV path | none |
| `--model` | Model name | `deepseek-v4-pro` |
| `--format`, `-f` | markdown / pdf / both | `markdown` |
| `--workers`, `-w` | Concurrent threads (1-16) | `1` |
| `--start` | Start page (0-indexed) | `0` |
| `--end` | End page (exclusive) | all |

## Glossary Format

TSV file, one entry per line:
```
Chinese_name[Tab]English_name
```

Example:
```
Green Delta\tDelta Green
Great Old One\tGreat Old One
Azathoth\tAzathoth
```

Lines starting with `#` are comments.

## Cost Estimate (320 pages)

| Mode | Est. Cost | Time |
|------|-----------|------|
| 1 worker, Pro | ~5-15 CNY | ~40 min |
| 4 workers, Pro | ~5-15 CNY | ~12 min |
| 4 workers, Flash | ~1-3 CNY | ~8 min |

## Resume

Progress auto-saves to `{output}.progress.json`. Re-run the same command to continue.
Delete progress file to restart from scratch.

## License

Personal use only. Respect original copyright.
