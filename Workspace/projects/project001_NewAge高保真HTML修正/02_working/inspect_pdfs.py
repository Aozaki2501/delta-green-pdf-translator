from __future__ import annotations

import json
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "01_inputs"
WORKING = ROOT / "02_working"


def inspect_pdf(path: Path, label: str) -> dict:
    document = fitz.open(path)
    pages = []
    for index, page in enumerate(document):
        text = page.get_text("text")
        pages.append(
            {
                "page_index": index,
                "page_number": index + 1,
                "width": round(page.rect.width, 2),
                "height": round(page.rect.height, 2),
                "text_sample": " ".join(text.split())[:240],
            }
        )
    return {"label": label, "page_count": len(document), "pages": pages}


def search_pdf(path: Path, terms: list[str]) -> dict[str, list[int]]:
    document = fitz.open(path)
    hits = {term: [] for term in terms}
    for index, page in enumerate(document):
        text = page.get_text("text")
        normalized = "".join(text.split())
        for term in terms:
            if "".join(term.split()) in normalized:
                hits[term].append(index + 1)
    return hits


def render_pages(path: Path, page_numbers: list[int], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open(path)
    matrix = fitz.Matrix(1.5, 1.5)
    for page_number in page_numbers:
        page = document[page_number - 1]
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        pixmap.save(output_dir / f"page_{page_number:03d}.png")


def main() -> None:
    english = INPUTS / "newage_english.pdf"
    chinese = INPUTS / "融合_chinese.pdf"
    result = {
        "english": inspect_pdf(english, "english"),
        "chinese": inspect_pdf(chinese, "chinese"),
        "search": {
            "english": search_pdf(
                english,
                ["The New Age", "A Brief History of the Conspiracy", "Timeline"],
            ),
            "chinese": search_pdf(
                chinese,
                ["新时代", "关于恩洛斯", "过往事件", "恩洛斯的故事", "绿色三角洲"],
            ),
        },
    }
    WORKING.joinpath("pdf_inventory.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    render_pages(english, list(range(1, min(15, result["english"]["page_count"]) + 1)), WORKING / "rendered" / "english")
    chinese_hits = sorted({page for pages in result["search"]["chinese"].values() for page in pages})
    if chinese_hits:
        render_pages(chinese, chinese_hits, WORKING / "rendered" / "chinese_hits")
    print(json.dumps({"counts": {"english": result["english"]["page_count"], "chinese": result["chinese"]["page_count"]}, "search": result["search"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
