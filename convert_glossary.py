#!/usr/bin/env python3
"""
Glossary Format Converter
=========================
Converts raw PDF-copied glossary (alternating Chinese/English lines or blocks)
into TSV format for the translator script.

Usage:
    python convert_glossary.py raw_glossary.txt -o glossary.tsv
"""

import argparse
import re


def has_chinese(text):
    return bool(re.search(r'[一-鿿㐀-䶿]', text))


def try_split_inline(line):
    match = re.match(r'^(.*[一-鿿㐀-䶿））"\u300d\u300b\u3011\uff09].{0,8}?)\s{2,}([A-Za-z"\'\(].+)$', line)
    if match:
        return (match.group(1).strip(), match.group(2).strip())
    if '\t' in line:
        parts = line.split('\t', 1)
        if len(parts) == 2 and has_chinese(parts[0]):
            return (parts[0].strip(), parts[1].strip())
    return None


def convert_glossary(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]

    pairs = []
    i = 0
    skipped = []

    while i < len(lines):
        line = lines[i]
        inline = try_split_inline(line)
        if inline:
            pairs.append(inline)
            i += 1
            continue

        if has_chinese(line):
            cn_block = []
            j = i
            while j < len(lines):
                if try_split_inline(lines[j]):
                    break
                if has_chinese(lines[j]):
                    cn_block.append(lines[j])
                    j += 1
                else:
                    break

            en_block = []
            while j < len(lines):
                if try_split_inline(lines[j]):
                    break
                if has_chinese(lines[j]):
                    break
                en_block.append(lines[j])
                j += 1

            if len(cn_block) == len(en_block):
                for cn, en in zip(cn_block, en_block):
                    pairs.append((cn, en))
            elif cn_block and en_block:
                merged_en = []
                for en_line in en_block:
                    if merged_en and (
                        en_line[0:1].islower() or en_line.startswith("d\'") or
                        en_line.startswith("Inc") or
                        (merged_en[-1].endswith(",") or merged_en[-1].endswith("-"))
                    ):
                        merged_en[-1] = merged_en[-1] + " " + en_line
                    else:
                        merged_en.append(en_line)
                min_len = min(len(cn_block), len(merged_en))
                for k in range(min_len):
                    pairs.append((cn_block[k], merged_en[k]))
                if len(cn_block) != len(merged_en):
                    skipped.append(f"Block mismatch at line {i+1}: {len(cn_block)} CN vs {len(merged_en)} EN")
            else:
                if cn_block:
                    skipped.append(f"No EN pair for: {cn_block[0]}")
            i = j
            continue

        skipped.append(f"Skipped line {i+1}: {line[:50]}")
        i += 1

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# Delta Green Glossary - Auto converted\n#\n")
        for chinese, english in pairs:
            f.write(f"{chinese}\t{english}\n")

    print(f"\nDone! {len(lines)} lines -> {len(pairs)} term pairs")
    print(f"Output: {output_path}")
    if skipped:
        print(f"\nWarnings ({len(skipped)}):")
        for s in skipped[:20]:
            print(f"  {s}")


def main():
    parser = argparse.ArgumentParser(description="Convert raw glossary to TSV format")
    parser.add_argument("input", help="Input raw text file")
    parser.add_argument("-o", "--output", default="glossary.tsv", help="Output TSV file")
    args = parser.parse_args()
    convert_glossary(args.input, args.output)


if __name__ == "__main__":
    main()
