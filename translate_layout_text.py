"""
Translate coordinate-level layout text blocks into translations.json.
"""

import argparse
from pathlib import Path

from core.glossary import load_glossary
from core.layout_model import layout_document_from_json
from core.layout_translation import translate_layout_to_template
from core.translator import TokenStats, Translator


def main():
    parser = argparse.ArgumentParser(description="自动翻译 layout.json 里的坐标文本块")
    parser.add_argument("layout_json", help="输入 layout.json")
    parser.add_argument("-o", "--output", required=True, help="输出 translations.json")
    parser.add_argument("--api-key", required=True, help="接口密钥")
    parser.add_argument("--model", default="deepseek-v4-pro", help="模型名称")
    parser.add_argument("--provider", default="deepseek", help="服务名称，仅用于显示")
    parser.add_argument("--base-url", default="https://api.deepseek.com", help="OpenAI 兼容接口地址")
    parser.add_argument("--glossary", help="术语表 TSV")
    parser.add_argument("--progress", help="块级进度 JSON，默认跟输出文件同名")
    parser.add_argument("--retry-failed", action="store_true", help="只重试上次失败的文本块")
    args = parser.parse_args()

    if not args.provider.strip():
        raise ValueError("服务名称不能为空")
    layout = layout_document_from_json(Path(args.layout_json).read_text(encoding="utf-8"))
    glossary = load_glossary(args.glossary) if args.glossary else {}
    progress_file = args.progress or str(Path(args.output).with_suffix(".progress.json"))

    stats = TokenStats()
    translator = Translator(
        api_key=args.api_key,
        model=args.model,
        base_url=args.base_url,
        stats=stats,
    )
    translator.set_glossary(glossary)

    print(f"Engine: {args.provider} ({args.model})")
    print(f"Blocks: {sum(len(page.text_blocks) for page in layout.pages)}")
    if glossary:
        print(f"Glossary: {len(glossary)} terms")

    translate_layout_to_template(
        layout,
        translator,
        progress_file=progress_file,
        output_path=args.output,
        retry_failed=args.retry_failed,
    )
    print(f"已写入 {args.output}")
    print(f"进度文件：{progress_file}")
    print(stats.summary())


if __name__ == "__main__":
    main()
