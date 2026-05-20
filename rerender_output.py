"""
Offline output rerenderer.

Rebuilds Markdown/HTML/Word files from an existing .progress.json file without
calling the translation API.
"""

import argparse
import json
import os
from pathlib import Path

from core.constants import SUPPORTED_OUTPUT_FORMATS
from core.extractor import PDFExtractor
from core.utils import ensure_output_parent, output_base_in_own_dir
from exporters.html import write_html_output
from exporters.markdown import write_markdown_output
from exporters.word import HAS_DOCX, write_word_output


def load_progress_translations(progress_path: str) -> list[tuple[int, str]]:
    with open(progress_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("progress 文件格式错误：根节点不是对象")
    translations = data.get("translations", {})
    if not isinstance(translations, dict) or not translations:
        raise ValueError("progress 文件里没有可用译文")

    pages = []
    for page_num, text in translations.items():
        try:
            page_index = int(page_num)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"progress 页码无效：{page_num!r}") from exc
        if text and str(text).strip():
            pages.append((page_index, str(text)))
    if not pages:
        raise ValueError("progress 文件里的译文为空")
    return sorted(pages, key=lambda item: item[0])


def infer_output_base(progress_path: str, output_base: str | None) -> str:
    if output_base:
        return output_base_in_own_dir(output_base)
    progress = Path(progress_path)
    name = progress.name
    if name.endswith(".progress.json"):
        return output_base_in_own_dir(str(progress.with_name(name[:-len(".progress.json")])))
    return output_base_in_own_dir(str(progress.with_suffix("")))


def detect_pdf_page_context(pdf_path: str | None, translated_pages: list[tuple[int, str]],
                            asset_dir: str | None = None,
                            asset_stem: str = "assets") -> tuple[dict[int, str], dict[int, str], dict[int, list[str]]]:
    if not pdf_path:
        return {}, {}, {}
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF 文件不存在：{pdf_path}")
    layouts = {}
    pages_text = {}
    image_assets = {}
    with PDFExtractor(pdf_path) as extractor:
        for page_num, _ in translated_pages:
            if 0 <= page_num < extractor.total_pages:
                layouts[page_num] = extractor.detect_page_layout(page_num)
                pages_text[page_num] = extractor.extract_page(page_num)
                if asset_dir:
                    images = extractor.export_page_images(page_num, asset_dir, asset_stem)
                    if images:
                        image_assets[page_num] = images
    return layouts, pages_text, image_assets


def rerender_outputs(progress_path: str, output_base: str | None = None,
                     pdf_path: str | None = None, output_format: str = "all",
                     title: str | None = None, markdown_min_chars: int = 1000,
                     markdown_max_chars: int = 1500, html_min_chars: int = 1200,
                     html_max_chars: int = 1800, word_min_chars: int = 1000,
                     word_max_chars: int = 1500, columns: int = 2,
                     word_hard_page_breaks: bool = False) -> list[str]:
    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        raise ValueError(f"不支持的输出格式：{output_format}")

    translated_pages = load_progress_translations(progress_path)
    base = infer_output_base(progress_path, output_base)
    ensure_output_parent(base + ".tmp")
    doc_title = title or Path(base).stem
    page_layouts, pages_text, image_assets = detect_pdf_page_context(
        pdf_path,
        translated_pages,
        asset_dir=str(Path(base).parent / "assets") if pdf_path else None,
        asset_stem=Path(base).stem,
    )

    written = []
    if output_format in ("html", "both", "all"):
        html_path = base + ".html"
        write_html_output(
            translated_pages,
            html_path,
            doc_title,
            min_chars=html_min_chars,
            max_chars=html_max_chars,
            columns=columns,
            page_layouts=page_layouts,
            image_assets=image_assets,
        )
        written.append(html_path)

    if output_format in ("markdown", "both", "all"):
        md_path = base + ".md"
        write_markdown_output(
            translated_pages,
            md_path,
            doc_title,
            min_chars=markdown_min_chars,
            max_chars=markdown_max_chars,
            page_layouts=page_layouts,
            image_assets=image_assets,
        )
        written.append(md_path)

    if output_format in ("word", "all"):
        if not HAS_DOCX:
            raise RuntimeError("Word 输出需要安装 python-docx")
        docx_path = base + ".docx"
        write_word_output(
            translated_pages,
            docx_path,
            doc_title,
            min_chars=word_min_chars,
            max_chars=word_max_chars,
            columns=columns,
            hard_page_breaks=word_hard_page_breaks,
            source_pages_text=pages_text,
            page_layouts=page_layouts,
            image_assets=image_assets,
        )
        written.append(docx_path)

    return written


def main():
    parser = argparse.ArgumentParser(
        description="从现有 progress.json 离线重新生成输出文件，不调用翻译 API。"
    )
    parser.add_argument("--progress", required=True, help="现有 .progress.json 路径")
    parser.add_argument("--pdf", default=None, help="可选：原 PDF 路径，用于 HTML 版面识别")
    parser.add_argument("--output-base", default=None, help="可选：输出路径，不含扩展名")
    parser.add_argument("--format", default="all", choices=sorted(SUPPORTED_OUTPUT_FORMATS))
    parser.add_argument("--title", default=None, help="可选：输出标题")
    parser.add_argument("--columns", type=int, default=2, choices=(1, 2))
    parser.add_argument("--word-hard-page-breaks", action="store_true")
    args = parser.parse_args()

    print("离线重排：不会调用翻译 API。")
    print("注意：如果旧 progress 里的译文本身已经错序，重排只能套新版样式，不能自动修正文顺序。")
    written = rerender_outputs(
        progress_path=args.progress,
        output_base=args.output_base,
        pdf_path=args.pdf,
        output_format=args.format,
        title=args.title,
        columns=args.columns,
        word_hard_page_breaks=args.word_hard_page_breaks,
    )
    for path in written:
        print(f"已生成：{path}")


if __name__ == "__main__":
    main()
