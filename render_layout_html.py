"""
Render coordinate-level layout JSON to absolute-positioned HTML.
"""

import argparse

from exporters.pdf_html import render_layout_json_html


def main():
    parser = argparse.ArgumentParser(description="把 layout.json 渲染为原页坐标 HTML")
    parser.add_argument("layout_json", help="输入 layout.json")
    parser.add_argument("-o", "--output", required=True, help="输出 HTML")
    parser.add_argument("--show-boxes", action="store_true", help="显示文本和图片框，方便检查")
    args = parser.parse_args()

    render_layout_json_html(args.layout_json, args.output, show_boxes=args.show_boxes)
    print(f"已写入 {args.output}")


if __name__ == "__main__":
    main()
