from collections import Counter, defaultdict
from pathlib import Path

import fitz


root = Path(__file__).resolve().parents[1]
pdf_path = root / "01_inputs" / "融合_chinese.pdf"
doc = fitz.open(pdf_path)

counts = Counter()
examples = defaultdict(list)
for page_index, page in enumerate(doc):
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                key = (
                    span.get("font", ""),
                    round(float(span.get("size", 0.0)), 2),
                    span.get("color", 0),
                )
                counts[key] += len(text)
                if len(examples[key]) < 3:
                    examples[key].append(f"p{page_index + 1}: {text[:60]}")

for (font, size, color), count in counts.most_common(40):
    sample = " | ".join(examples[(font, size, color)])
    print(f"{count:6d}  {font:32s} {size:6.2f}  #{color:06x}  {sample}")
