"""
Export translated coordinate-level layout JSON to PDF.
"""

import argparse

from exporters.pdf_playwright import export_layout_json_pdf


def main():
    parser = argparse.ArgumentParser(description="把 translated.layout.json 导出为 replica.pdf")
    parser.add_argument("layout_json", help="输入 translated.layout.json")
    parser.add_argument("-o", "--output", required=True, help="输出 PDF")
    parser.add_argument("--html-output", help="同时写出的中间 HTML，默认跟 PDF 同名")
    parser.add_argument("--show-boxes", action="store_true", help="导出的 HTML/PDF 保留检查框")
    args = parser.parse_args()

    html_path = export_layout_json_pdf(
        args.layout_json,
        args.output,
        html_output=args.html_output,
        show_boxes=args.show_boxes,
    )
    print(f"已写入 {args.output}")
    print(f"中间 HTML：{html_path}")


if __name__ == "__main__":
    main()
