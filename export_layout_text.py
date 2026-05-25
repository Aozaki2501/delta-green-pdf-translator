"""
Export translatable text blocks from coordinate-level layout JSON.
"""

import argparse
from pathlib import Path

from core.layout_model import layout_document_from_json
from core.layout_translation import export_translation_template


def main():
    parser = argparse.ArgumentParser(description="从 layout.json 导出待翻译文本模板")
    parser.add_argument("layout_json", help="输入 layout.json")
    parser.add_argument("-o", "--output", required=True, help="输出 translations.json")
    args = parser.parse_args()

    layout = layout_document_from_json(Path(args.layout_json).read_text(encoding="utf-8"))
    export_translation_template(layout, args.output)
    print(f"已写入 {args.output}")


if __name__ == "__main__":
    main()
