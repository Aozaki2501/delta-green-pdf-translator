"""
Extract coordinate-level PDF layout to JSON.
"""

import argparse

from core.layout_extractor import extract_layout_to_file


def main():
    parser = argparse.ArgumentParser(description="提取 PDF 坐标级 layout.json")
    parser.add_argument("pdf", help="输入 PDF")
    parser.add_argument("-o", "--output", required=True, help="输出 layout.json")
    parser.add_argument("--start-page", type=int, default=0, help="起始页，0-based")
    parser.add_argument("--end-page", type=int, default=None, help="结束页，0-based，不包含")
    args = parser.parse_args()

    layout = extract_layout_to_file(
        args.pdf,
        args.output,
        start_page=args.start_page,
        end_page=args.end_page,
    )
    print(f"已写入 {args.output}，页面 {layout.page_count} 页")


if __name__ == "__main__":
    main()
