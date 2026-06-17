#!/usr/bin/env python3
"""
环境测试脚本
============
运行此脚本检查你的环境是否配置正确，以及各组件是否能正常工作。

使用方法:
    python test_setup.py
    python test_setup.py --api-key sk-xxx    (可选：测试 API 连通性)
"""

import sys
import os
import argparse


def configure_console_output():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except AttributeError:
            pass


configure_console_output()

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"

def test_section(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")

def check(desc, condition, fix=""):
    if condition:
        print(f"  {PASS} {desc}")
        return True
    else:
        print(f"  {FAIL} {desc}")
        if fix:
            print(f"     修复: {fix}")
        return False


def main():
    parser = argparse.ArgumentParser(description="检查翻译工具的运行环境")
    parser.add_argument("--api-key", default=None, help="可选：填入 API Key 测试连通性")
    parser.add_argument("--pdf", default=None, help="可选：填入 PDF 路径测试提取")
    args = parser.parse_args()

    print()
    print("  🎲 绿色三角洲 PDF 翻译工具 — 环境检测")
    print("  " + "=" * 46)

    all_pass = True
    critical_fail = False

    # ============ Python 版本 ============
    test_section("1. Python 环境")

    py_ver = sys.version_info
    ok = check(
        f"Python 版本: {py_ver.major}.{py_ver.minor}.{py_ver.micro}",
        py_ver >= (3, 10),
        "需要 Python 3.10+，请升级: https://python.org"
    )
    if not ok:
        critical_fail = True

    # ============ 依赖检查 ============
    test_section("2. 依赖包")

    # PyMuPDF
    try:
        import pymupdf
        ver = pymupdf.VersionBind
        check(f"PyMuPDF: {ver}", True)
    except ImportError:
        try:
            import fitz
            check(f"PyMuPDF (fitz): OK", True)
        except ImportError:
            check("PyMuPDF: 未安装", False, "pip install pymupdf")
            critical_fail = True

    # openai
    try:
        import openai
        check(f"openai: {openai.__version__}", True)
    except ImportError:
        check("openai: 未安装", False, "pip install openai")
        critical_fail = True

    # python-docx
    try:
        import docx
        check(f"python-docx: OK", True)
    except ImportError:
        check("python-docx: 未安装（Word输出不可用）", False, "pip install python-docx")
        print(f"     {WARN} 这不是必须的，只影响 Word 输出")

    # streamlit
    try:
        import streamlit
        check(f"Streamlit: {streamlit.__version__}", True)
    except ImportError:
        check("Streamlit: 未安装（Web界面不可用）", False, "pip install streamlit")
        print(f"     {WARN} 这不是必须的，命令行翻译不受影响")

    # ============ 项目文件 ============
    test_section("3. 项目文件")

    script_dir = os.path.dirname(os.path.abspath(__file__))

    files_to_check = [
        ("translate_pdf.py", True, "主翻译脚本"),
        ("app.py", False, "Web 界面"),
        ("convert_glossary.py", False, "术语表转换"),
        ("glossary.tsv", False, "术语表"),
        ("config.json", False, "配置文件"),
    ]

    for filename, required, desc in files_to_check:
        filepath = os.path.join(script_dir, filename)
        exists = os.path.exists(filepath)
        if exists:
            size = os.path.getsize(filepath)
            check(f"{filename} ({size:,} bytes) — {desc}", True)
        else:
            if required:
                check(f"{filename} — {desc}", False, "文件缺失，请重新下载项目")
                critical_fail = True
            else:
                print(f"  {WARN} {filename} — {desc}（未找到，可选）")

    # ============ 术语表格式 ============
    test_section("4. 术语表检查")

    glossary_path = os.path.join(script_dir, "glossary.tsv")
    if os.path.exists(glossary_path):
        with open(glossary_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

        valid_count = 0
        error_lines = []
        for i, line in enumerate(lines[:500], 1):
            if "\t" in line:
                parts = line.split("\t", 1)
                if len(parts) == 2 and parts[0] and parts[1]:
                    valid_count += 1
                else:
                    error_lines.append(i)
            else:
                error_lines.append(i)

        check(f"术语表: {valid_count} 条有效术语", valid_count > 0)
        if error_lines:
            print(f"  {WARN} {len(error_lines)} 行格式有误（前5行: {error_lines[:5]}）")
    else:
        print(f"  {WARN} 术语表文件不存在（翻译时不使用术语对照）")

    # ============ PDF 提取测试 ============
    if args.pdf:
        test_section("5. PDF 提取测试")

        if not os.path.exists(args.pdf):
            check(f"PDF 文件存在: {args.pdf}", False, "文件路径不正确")
        else:
            try:
                from translate_pdf import PDFExtractor
                extractor = PDFExtractor(args.pdf)
                total = extractor.total_pages
                check(f"PDF 打开成功: {total} 页", True)

                # Test extract first page
                text = extractor.extract_page(0)
                text_len = len(text)
                check(f"第1页文本提取: {text_len} 字符", text_len > 10)

                if text_len > 0:
                    print(f"\n  --- 第1页前200字预览 ---")
                    print(f"  {text[:200]}")
                    print(f"  --- 预览结束 ---\n")

                # Test column detection
                text_p5 = extractor.extract_page(min(4, total - 1))
                check(f"第5页文本提取: {len(text_p5)} 字符", len(text_p5) > 0)

                extractor.close()
            except Exception as e:
                check(f"PDF 提取", False, f"错误: {e}")

    # ============ API 连通测试 ============
    if args.api_key:
        test_section("6. API 连通测试")

        try:
            from openai import OpenAI
            client = OpenAI(api_key=args.api_key, base_url="https://api.deepseek.com")

            print(f"  正在测试 API 连接...")
            response = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[
                    {"role": "user", "content": "Say 'OK' in one word."}
                ],
                max_tokens=10,
            )
            result = response.choices[0].message.content.strip()
            check(f"API 响应正常: '{result}'", True)

            # Check token usage
            if response.usage:
                print(f"  {PASS} Token 计费正常: 输入 {response.usage.prompt_tokens}, 输出 {response.usage.completion_tokens}")

        except Exception as e:
            check(f"API 连接", False, f"错误: {e}")
            if "401" in str(e) or "auth" in str(e).lower():
                print(f"     → API Key 无效或已过期")
            elif "429" in str(e):
                print(f"     → 请求过快，请稍后重试")
            elif "connection" in str(e).lower():
                print(f"     → 网络连接失败，检查是否需要代理")

    # ============ 总结 ============
    test_section("检测总结")

    if critical_fail:
        print(f"\n  {FAIL} 存在关键问题，请先修复后再运行翻译工具。")
        print(f"     通常只需要: pip install pymupdf openai")
    else:
        print(f"\n  {PASS} 环境检测通过！可以开始翻译了。")
        print()
        print("  快速开始:")
        print("    1. 复制 config.example.json → config.json")
        print("    2. 填入你的 API Key")
        print("    3. 运行: python translate_pdf.py --config config.json")
        print()
        if not args.api_key:
            print(f"  {WARN} 提示：加 --api-key sk-xxx 可测试 API 是否连通")
        if not args.pdf:
            print(f"  {WARN} 提示：加 --pdf 你的文件.pdf 可测试 PDF 提取效果")

    print()


if __name__ == "__main__":
    main()
