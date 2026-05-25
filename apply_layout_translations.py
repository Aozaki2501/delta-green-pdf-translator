"""
Apply translated text blocks to coordinate-level layout JSON.
"""

import argparse

from core.layout_translation import apply_translations_file, write_overflow_report


def main():
    parser = argparse.ArgumentParser(description="把 translations.json 回填到 layout.json")
    parser.add_argument("layout_json", help="输入 layout.json")
    parser.add_argument("translations_json", help="输入 translations.json")
    parser.add_argument("-o", "--output", required=True, help="输出 translated.layout.json")
    parser.add_argument("--overflow-report", help="输出译文溢出报告")
    args = parser.parse_args()

    translated = apply_translations_file(args.layout_json, args.translations_json, args.output)
    print(f"已写入 {args.output}")

    if args.overflow_report:
        issues = write_overflow_report(translated, args.overflow_report)
        if issues:
            raise SystemExit(f"发现 {len(issues)} 个溢出文本块，详见 {args.overflow_report}")
        print(f"已写入 {args.overflow_report}")


if __name__ == "__main__":
    main()
