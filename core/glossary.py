"""
Glossary loading, term matching, and report generation.

Provides functions for loading TRPG glossary TSV files, finding relevant
glossary terms in source text (longest-match-first, non-overlapping), and
generating Markdown glossary reports.

Dependencies: core.utils (for ensure_output_parent), standard library only.
"""

import os
import re
from dataclasses import dataclass

from core.utils import ensure_output_parent


def load_glossary(glossary_path: str) -> dict:
    """Load a glossary TSV, refusing to silently drop conflicting entries.

    Matching is case-sensitive-preferred (see ``ACGlossaryMatcher``), so terms
    that differ only in case — ``Agent`` vs ``agent`` — are kept as separate,
    both-live entries. Two rows with the *identical* English term, however, can
    only ever resolve to one translation, so the loser used to disappear without
    a word. That is now a hard error.
    """
    glossary = {}
    if not glossary_path or not os.path.exists(glossary_path):
        return glossary
    corrupted_entries = []
    seen_lines = {}
    duplicate_entries = []
    with open(glossary_path, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "\t" in line:
                parts = line.split("\t", 1)
            else:
                parts = re.split(r"\s{2,}", line, maxsplit=1)
            if len(parts) == 2:
                chinese = parts[0].strip()
                english = parts[1].strip()
                if english and chinese:
                    if "?" in chinese:
                        corrupted_entries.append((line_number, chinese, english))
                        continue
                    if english in glossary and glossary[english] != chinese:
                        duplicate_entries.append(
                            (english, seen_lines[english], glossary[english],
                             line_number, chinese)
                        )
                        continue
                    seen_lines[english] = line_number
                    glossary[english] = chinese
    if corrupted_entries:
        examples = "; ".join(
            f"第 {line_number} 行 {chinese} -> {english}"
            for line_number, chinese, english in corrupted_entries[:10]
        )
        raise ValueError(
            f"术语表疑似编码损坏：{glossary_path}。"
            f"中文列含英文问号的词条 {len(corrupted_entries)} 条，例如：{examples}"
        )
    if duplicate_entries:
        examples = "; ".join(
            f"{english}：第 {first_line} 行 {first_chinese} / 第 {line_number} 行 {chinese}"
            for english, first_line, first_chinese, line_number, chinese in duplicate_entries[:10]
        )
        raise ValueError(
            f"术语表存在同一英文词条的冲突译名：{glossary_path}。"
            f"冲突 {len(duplicate_entries)} 组，请合并或删除其中一条，例如：{examples}"
        )
    return glossary


def _resolve_case_preferred_entry(entries, matched_text: str):
    """Pick the glossary entry whose written form matches the source casing.

    ``entries`` are ``(english, chinese, surface)`` triples that all collapse to
    the same lowercase key. When the source text reproduces one entry's exact
    casing that entry wins, so ``Agent`` (特工, the Delta Green role) and
    ``agent`` (探员, the common noun) can coexist. Anything else — ``AGENT`` in a
    heading, for instance — falls back to the first entry in file order.
    """
    for english, chinese, surface in entries:
        if surface == matched_text:
            return english, chinese
    return entries[0][0], entries[0][1]


def _find_relevant_glossary_terms_regex(text: str, glossary: dict) -> dict:
    """Regex-based glossary matching (longest-match-first, non-overlapping).

    This is the internal implementation preserved for backward compatibility and
    as a fallback when pyahocorasick is not installed. It resolves case-different
    entries exactly like ``ACGlossaryMatcher`` so both paths agree.
    """
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for eng, chn in glossary.items():
        groups.setdefault(eng.lower(), []).append((eng, chn, eng))

    matches = []
    for key in sorted(groups, key=len, reverse=True):
        pattern = re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(key) + r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            eng, chn = _resolve_case_preferred_entry(groups[key], match.group(0))
            matches.append((match.start(), match.end(), eng, chn))

    relevant = {}
    occupied_spans = []
    for start, end, eng, chn in matches:
        if any(start < occupied_end and end > occupied_start for occupied_start, occupied_end in occupied_spans):
            continue
        relevant[eng] = chn
        occupied_spans.append((start, end))
    return relevant


def build_glossary_matcher(glossary: dict, **kwargs) -> "ACGlossaryMatcher":
    """构建 AC 自动机匹配器（每会话调用一次）。

    Args:
        glossary: {english_term: chinese_translation}
        **kwargs: 传递给 ACGlossaryMatcher 的额外参数
                  (fuzzy, max_fuzzy_edits, normalize_plurals, filter_articles)

    Returns:
        ACGlossaryMatcher 实例，可跨所有块复用。
    """
    return ACGlossaryMatcher(glossary, **kwargs)


def find_relevant_glossary_terms(text: str, glossary: dict,
                                 matcher: "ACGlossaryMatcher | None" = None) -> dict:
    """向后兼容接口：在源文本中查找相关术语表条目。

    如果提供 matcher 则使用 AC 自动机（O(n) 性能），否则回退到旧的正则逻辑。
    现有调用方使用 (text, glossary) 两参数签名无需任何修改。

    Args:
        text: 源文本
        glossary: {english_term: chinese_translation}
        matcher: 可选的 ACGlossaryMatcher 实例

    Returns:
        {english_term: chinese_translation} 匹配到的术语字典
    """
    if matcher is not None:
        return matcher.find_relevant_glossary_terms(text)
    return _find_relevant_glossary_terms_regex(text, glossary)


def select_core_glossary_terms(texts, glossary: dict, limit: int = 80,
                               matcher: "ACGlossaryMatcher | None" = None) -> dict:
    """Select frequently used glossary terms for a stable prompt prefix.

    Frequency is counted by how many source chunks actually hit each term,
    using the same matching path as normal per-chunk glossary injection.
    """
    if not glossary or limit <= 0:
        return {}

    if isinstance(texts, dict):
        iterable = (texts[key] for key in sorted(texts))
    else:
        iterable = texts

    hit_counts = {}
    for text in iterable:
        if not text:
            continue
        hits = find_relevant_glossary_terms(str(text), glossary, matcher=matcher)
        for eng in hits:
            hit_counts[eng] = hit_counts.get(eng, 0) + 1

    selected = sorted(
        hit_counts,
        key=lambda eng: (-hit_counts[eng], eng.lower(), eng),
    )[:limit]
    return {eng: glossary[eng] for eng in selected}


@dataclass
class GlossaryCandidate:
    term: str
    count: int
    pages: list[int]


def build_glossary_candidates(
    pages_text: dict[int, str],
    glossary: dict,
    matcher: "ACGlossaryMatcher | None" = None,
    min_pages: int = 2,
    limit: int = 80,
) -> list[GlossaryCandidate]:
    if limit <= 0:
        return []

    known_terms = {term.lower() for term in glossary or {}}
    stats: dict[str, dict] = {}
    for page_num in sorted(pages_text):
        text = pages_text.get(page_num, "")
        if not text:
            continue
        hits = find_relevant_glossary_terms(text, glossary or {}, matcher=matcher)
        known_on_page = known_terms | {term.lower() for term in hits}
        for candidate in _iter_unlisted_proper_noun_candidates(text, known_on_page):
            item = stats.setdefault(candidate, {"count": 0, "pages": set()})
            item["count"] += 1
            item["pages"].add(page_num)

    rows = [
        GlossaryCandidate(term=term, count=item["count"], pages=sorted(item["pages"]))
        for term, item in stats.items()
        if len(item["pages"]) >= max(1, min_pages)
    ]
    rows.sort(key=lambda row: (-len(row.pages), -row.count, row.term.lower(), row.term))
    return rows[:limit]


def render_glossary_candidate_report(candidates: list[GlossaryCandidate], title: str = "") -> str:
    lines = [
        f"# {title} — 术语候选报告" if title else "# 术语候选报告",
        "",
        "本报告只列出疑似未收录专名，不会自动修改术语表。",
        "",
        "## 候选清单",
        "",
    ]
    if not candidates:
        lines.append("- 暂无。")
        lines.append("")
        return "\n".join(lines)

    lines.extend([
        "| 候选英文 | 出现次数 | 页码 |",
        "| --- | ---: | --- |",
    ])
    for row in candidates:
        pages = _format_page_ranges(row.pages)
        lines.append(f"| `{row.term}` | {row.count} | {pages} |")
    lines.append("")
    return "\n".join(lines)


def render_glossary_candidate_tsv(candidates: list[GlossaryCandidate]) -> str:
    lines = [
        "# 填好中文列后，可把非注释行复制到 glossary.tsv",
        "# 中文\t英文",
    ]
    for row in candidates:
        lines.append(f"\t{row.term}")
    lines.append("")
    return "\n".join(lines)


def write_glossary_candidate_report(
    candidates: list[GlossaryCandidate],
    report_output: str,
    title: str = "",
) -> None:
    ensure_output_parent(report_output)
    with open(report_output, "w", encoding="utf-8") as f:
        f.write(render_glossary_candidate_report(candidates, title))


def write_glossary_candidate_tsv(candidates: list[GlossaryCandidate], output_path: str) -> None:
    ensure_output_parent(output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(render_glossary_candidate_tsv(candidates))


def _find_unlisted_proper_nouns(text: str, glossary_hits: dict) -> list[str]:
    known = {term.lower() for term in glossary_hits}
    candidates = {}
    for candidate in _iter_unlisted_proper_noun_candidates(text, known):
        candidates[candidate] = candidates.get(candidate, 0) + 1
    return [
        term for term, _ in sorted(candidates.items(), key=lambda item: (-item[1], item[0].lower()))[:20]
    ]


def _iter_unlisted_proper_noun_candidates(text: str, known: set[str]):
    stopwords = {
        "A", "An", "And", "Are", "As", "At", "Be", "But", "By", "For", "From", "He",
        "Her", "His", "If", "In", "Into", "Is", "It", "Its", "Of", "On", "Or", "She",
        "The", "Their", "They", "This", "To", "Was", "Were", "When", "With", "You",
        "Chapter", "Page", "Table", "Figure",
    }
    pattern = re.compile(r"\b(?:[A-Z][A-Za-z''.-]+)(?:\s+(?:of|the|and|&|[A-Z][A-Za-z''.-]+))*\b")
    for match in pattern.finditer(text):
        candidate = match.group(0).strip(" -.,:;!?()[]{}\"""")
        candidate = re.sub(r"^(The|A|An)\s+", "", candidate)
        if len(candidate) < 3 or candidate in stopwords:
            continue
        if candidate.isupper() and len(candidate) <= 6:
            continue
        if candidate.lower() in known:
            continue
        yield candidate


def _format_page_ranges(page_nums):
    nums = sorted({p + 1 for p in page_nums})
    if not nums:
        return ""
    ranges = []
    start = prev = nums[0]
    for num in nums[1:]:
        if num == prev + 1:
            prev = num
            continue
        ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
        start = prev = num
    ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(ranges)


def build_glossary_report(pages_text: dict, glossary: dict, title: str = "") -> str:
    lines = [
        f"# {title} — 术语命中报告" if title else "# 术语命中报告",
        "",
        "本报告基于提取后的英文原文生成，用于检查每页实际命中的术语。",
        "",
    ]
    if not glossary:
        lines.append("未使用术语表。")
        return "\n".join(lines)

    summary = {}
    page_reports = []
    missing_candidates = {}

    for page_num in sorted(pages_text):
        text = pages_text.get(page_num, "")
        hits = find_relevant_glossary_terms(text, glossary)
        for eng, chn in hits.items():
            summary.setdefault(eng, {"chinese": chn, "pages": set()})
            summary[eng]["pages"].add(page_num + 1)
        missing = _find_unlisted_proper_nouns(text, hits)
        for term in missing:
            missing_candidates.setdefault(term, set()).add(page_num + 1)
        page_reports.append((page_num + 1, hits, missing))

    lines.append("## 汇总")
    lines.append("")
    if summary:
        for eng, info in sorted(summary.items(), key=lambda item: item[0].lower()):
            pages = _format_page_ranges([p - 1 for p in info["pages"]])
            lines.append(f"- `{eng}` -> `{info['chinese']}`；页：{pages}")
    else:
        lines.append("- 未命中任何术语。")

    lines.append("")
    lines.append("## 逐页命中")
    lines.append("")
    for page_num, hits, missing in page_reports:
        lines.append(f"### 第 {page_num} 页")
        if hits:
            for eng, chn in sorted(hits.items(), key=lambda item: item[0].lower()):
                lines.append(f"- `{eng}` -> `{chn}`")
        else:
            lines.append("- 无术语命中")
        if missing:
            lines.append(f"- 疑似未收录专名：{', '.join(missing[:10])}")
        lines.append("")

    lines.append("## 疑似未收录专名")
    lines.append("")
    if missing_candidates:
        for term, pages in sorted(missing_candidates.items(), key=lambda item: item[0].lower())[:100]:
            page_text = _format_page_ranges([p - 1 for p in pages])
            lines.append(f"- `{term}`；页：{page_text}")
    else:
        lines.append("- 暂无。")
    lines.append("")
    return "\n".join(lines)


def write_glossary_report(pages_text: dict, glossary: dict, report_output: str, title: str = ""):
    ensure_output_parent(report_output)
    report = build_glossary_report(pages_text, glossary, title)
    with open(report_output, "w", encoding="utf-8") as f:
        f.write(report)


# ============================================================
# AC AUTOMATON GLOSSARY MATCHER
# ============================================================

@dataclass
class GlossaryMatch:
    """单个术语匹配结果"""
    start: int              # 在源文本中的起始位置
    end: int                # 在源文本中的结束位置
    matched_text: str       # 实际匹配到的文本（可能是变体或 OCR 损坏形式）
    canonical_term: str     # 术语表中的标准英文形式
    chinese: str            # 中文翻译
    is_fuzzy: bool = False  # 是否为模糊匹配
    fuzzy_edits: int = 0    # OCR 替换字符数
    match_type: str = "exact"  # exact | plural | article | fuzzy


# Attempt to import pyahocorasick; if unavailable, set flag for fallback
try:
    import ahocorasick as _ahocorasick
    _HAS_AHOCORASICK = True
except ImportError:
    _ahocorasick = None
    _HAS_AHOCORASICK = False


class ACGlossaryMatcher:
    """基于 Aho-Corasick 自动机的术语匹配器。

    每个翻译会话构建一次，跨所有块复用。当 pyahocorasick 未安装时，
    自动回退到旧的正则匹配逻辑并打印警告。
    """

    # English articles to filter when filter_articles is enabled
    _ARTICLES_PATTERN = re.compile(r'\b(the|a|an)\s$', re.IGNORECASE)

    def __init__(self, glossary: dict[str, str], *,
                 fuzzy: bool = False,
                 max_fuzzy_edits: int = 2,
                 normalize_plurals: bool = True,
                 filter_articles: bool = True):
        """
        构建 AC 自动机。每个翻译会话构建一次，跨所有块复用。

        Args:
            glossary: {english_term: chinese_translation}
            fuzzy: 是否启用 OCR 模糊匹配（第二遍扫描未匹配区域）
            max_fuzzy_edits: 最大允许的 OCR 字符替换数
            normalize_plurals: 是否归一化英文复数后缀
            filter_articles: 是否忽略前置冠词（the/a/an）
        """
        # Store a shallow copy to guarantee we never mutate the caller's dict
        self._glossary = dict(glossary)
        self._fuzzy = fuzzy
        self._max_edits = max_fuzzy_edits
        self._normalize_plurals = normalize_plurals
        self._filter_articles = filter_articles
        self._fallback = not _HAS_AHOCORASICK
        self._automaton = None
        # Maps lowercase key -> list of (canonical_eng, chinese, pattern_length, surface)
        # Multiple entries possible when the glossary has case-different terms
        # ("Agent" vs "agent"). `surface` is the original-cased spelling that
        # produced this key, used to prefer the entry matching the source casing.
        self._variant_map: dict[str, list[tuple[str, str, int, str]]] = {}

        if self._fallback:
            print(
                "[WARNING] pyahocorasick 未安装，ACGlossaryMatcher 将回退到正则匹配。"
                "请运行 pip install pyahocorasick 以获得最佳性能。"
            )
        else:
            self._build_automaton()

    def _build_automaton(self):
        """构建 AC 自动机，插入所有术语的小写形式及其复数变体。"""
        self._automaton = _ahocorasick.Automaton()

        for eng, chn in self._glossary.items():
            key = eng.lower()
            # Multiple glossary entries may share the same lowercase key
            # (e.g. "Agent" -> "特工" and "agent" -> "探员")
            if key not in self._variant_map:
                self._variant_map[key] = []
            self._variant_map[key].append((eng, chn, len(key), eng))

            # Insert plural variants if enabled
            if self._normalize_plurals:
                for variant in self._generate_plural_variants(eng):
                    vkey = variant.lower()
                    if vkey != key:
                        if vkey not in self._variant_map:
                            self._variant_map[vkey] = []
                        # Only add if this canonical term isn't already mapped for this variant
                        if not any(e == eng for e, _, _, _ in self._variant_map[vkey]):
                            self._variant_map[vkey].append((eng, chn, len(vkey), variant))

        # Insert all keys into automaton; store the key itself as value
        # (we'll look up the variant_map during matching to resolve ambiguity)
        for key, entries in self._variant_map.items():
            # Store the first entry's pattern_length (all entries for same key have same length)
            self._automaton.add_word(key, (key, entries[0][2]))

        if self._variant_map:
            self._automaton.make_automaton()

    def find_relevant_glossary_terms(self, text: str) -> dict[str, str]:
        """
        兼容接口：返回 {english: chinese} 字典。
        与现有 find_relevant_glossary_terms(text, glossary) 结果一致
        （最长匹配优先、非重叠）。

        When fuzzy=True, performs a second pass over unmatched regions to find
        OCR-corrupted terms.
        """
        if self._fallback:
            return _find_relevant_glossary_terms_regex(text, self._glossary)

        if not self._glossary or not text or not self._variant_map:
            return {}

        # First pass: exact AC automaton matching
        raw_matches = self._collect_raw_matches(text)

        # Sort by length descending (longest first), then by start position
        if raw_matches:
            raw_matches.sort(key=lambda m: (-m[2], m[0]))

        # Select non-overlapping matches (longest-match-first)
        selected = {}
        occupied_spans = []
        for start, end, _length, eng, chn in raw_matches:
            if any(start < occ_end and end > occ_start
                   for occ_start, occ_end in occupied_spans):
                continue
            # Only keep first occurrence of each canonical term
            if eng not in selected:
                selected[eng] = chn
            occupied_spans.append((start, end))

        # Second pass: fuzzy matching over unmatched regions
        if self._fuzzy:
            fuzzy_matches = self._fuzzy_scan(text, occupied_spans)
            if fuzzy_matches:
                fuzzy_matches.sort(key=lambda m: (-m[2], m[0]))
                for start, end, _length, eng, chn in fuzzy_matches:
                    if any(start < occ_end and end > occ_start
                           for occ_start, occ_end in occupied_spans):
                        continue
                    if eng not in selected:
                        selected[eng] = chn
                    occupied_spans.append((start, end))

        return selected

    def find_relevant_glossary_terms_annotated(self, text: str) -> list[GlossaryMatch]:
        """
        增强接口：返回带位置和匹配类型注释的匹配列表。

        When fuzzy=True, includes fuzzy matches annotated with is_fuzzy=True,
        the original corrupted text, and the canonical glossary term.
        """
        if self._fallback:
            # Fallback: use regex and wrap results
            result = _find_relevant_glossary_terms_regex(text, self._glossary)
            matches = []
            for eng, chn in result.items():
                # Find position in text for annotation
                pattern = re.compile(
                    r"(?<![A-Za-z0-9])" + re.escape(eng) + r"(?![A-Za-z0-9])",
                    re.IGNORECASE,
                )
                m = pattern.search(text)
                if m:
                    matches.append(GlossaryMatch(
                        start=m.start(), end=m.end(),
                        matched_text=m.group(0),
                        canonical_term=eng, chinese=chn,
                    ))
            return matches

        if not self._glossary or not text or not self._variant_map:
            return []

        # First pass: exact AC automaton matching
        raw_matches = self._collect_raw_matches(text)

        if raw_matches:
            # Sort by length descending (longest first), then by start position
            raw_matches.sort(key=lambda m: (-m[2], m[0]))

        # Select non-overlapping matches (longest-match-first)
        results = []
        occupied_spans = []
        for start, end, _length, eng, chn in raw_matches:
            if any(start < occ_end and end > occ_start
                   for occ_start, occ_end in occupied_spans):
                continue
            occupied_spans.append((start, end))
            matched_text = text[start:end]
            # Determine match type
            if matched_text.lower() == eng.lower():
                # Check if preceded by article
                if self._filter_articles and self._is_preceded_by_article(text, start):
                    match_type = "article"
                else:
                    match_type = "exact"
            else:
                match_type = "plural"
            results.append(GlossaryMatch(
                start=start, end=end,
                matched_text=matched_text,
                canonical_term=eng, chinese=chn,
                match_type=match_type,
            ))

        # Second pass: fuzzy matching over unmatched regions
        if self._fuzzy:
            fuzzy_raw = self._fuzzy_scan(text, occupied_spans)
            if fuzzy_raw:
                fuzzy_raw.sort(key=lambda m: (-m[2], m[0]))
                fuzzy_matcher = FuzzyMatcher(max_edits=self._max_edits)
                for start, end, _length, eng, chn in fuzzy_raw:
                    if any(start < occ_end and end > occ_start
                           for occ_start, occ_end in occupied_spans):
                        continue
                    occupied_spans.append((start, end))
                    matched_text = text[start:end]
                    # Get the actual edit count for annotation
                    _, edits = fuzzy_matcher.is_fuzzy_match(matched_text, eng)
                    results.append(GlossaryMatch(
                        start=start, end=end,
                        matched_text=matched_text,
                        canonical_term=eng, chinese=chn,
                        is_fuzzy=True,
                        fuzzy_edits=edits,
                        match_type="fuzzy",
                    ))

        return results

    def _is_preceded_by_article(self, text: str, match_start: int) -> bool:
        """
        Check if the match at match_start is immediately preceded by an English
        article (the/a/an) followed by a space.

        Examples:
            "the Agent" → True (match_start points to 'A')
            "a Handler" → True
            "an Investigator" → True
            "Delta Green" → False
        """
        if match_start < 2:
            return False
        # Look at the text before the match (up to 4 chars: "the " is longest)
        prefix = text[max(0, match_start - 4):match_start]
        return bool(self._ARTICLES_PATTERN.search(prefix))

    def _collect_raw_matches(self, text: str) -> list[tuple[int, int, int, str, str]]:
        """
        Collect all valid matches from the AC automaton with word boundary checks.

        Returns list of (start, end, length, canonical_eng, chinese).

        When multiple glossary entries share the same lowercase key (e.g. "Agent"
        and "agent"), matching is case-sensitive-preferred: the entry whose
        written form equals the matched text wins, so both entries stay live and
        each keeps its own meaning. Only when no spelling matches (e.g. "AGENT"
        in an all-caps heading) does the first entry in file order win.
        """
        text_lower = text.lower()
        raw_matches = []

        for end_idx, (key, pattern_len) in self._automaton.iter(text_lower):
            # ahocorasick returns end_idx as the index of the last character
            start = end_idx - pattern_len + 1
            end = end_idx + 1

            # Word boundary check: replicate (?<![A-Za-z0-9]) and (?![A-Za-z0-9])
            if start > 0:
                char_before = text[start - 1]
                if char_before.isalnum():
                    continue
            if end < len(text):
                char_after = text[end]
                if char_after.isalnum():
                    continue

            # Resolve which canonical entry to use, preferring the one whose
            # spelling matches how the term is actually written here.
            entries = [
                (english, chinese, surface)
                for english, chinese, _length, surface in self._variant_map[key]
            ]
            eng, chn = _resolve_case_preferred_entry(entries, text[start:end])

            raw_matches.append((start, end, end - start, eng, chn))

        return raw_matches

    def _fuzzy_scan(self, text: str, occupied_spans: list[tuple[int, int]]) -> list[tuple[int, int, int, str, str]]:
        """
        Perform a second-pass fuzzy scan over unmatched regions of text.

        For each glossary term, slide a window of the term's length over unmatched
        regions and check if the substring is an OCR-corrupted version of the term.

        Returns list of (start, end, length, canonical_eng, chinese) for fuzzy matches.
        """
        if not self._fuzzy or not self._glossary:
            return []

        fuzzy_matcher = FuzzyMatcher(max_edits=self._max_edits)
        fuzzy_matches = []

        # Build list of unmatched regions
        unmatched_regions = self._get_unmatched_regions(text, occupied_spans)

        for region_start, region_end in unmatched_regions:
            region_text = text[region_start:region_end]
            # For each glossary term, slide a window over the region
            for eng, chn in self._glossary.items():
                term_len = len(eng)
                if term_len > len(region_text):
                    continue
                for i in range(len(region_text) - term_len + 1):
                    candidate = region_text[i:i + term_len]
                    is_match, edits = fuzzy_matcher.is_fuzzy_match(candidate, eng)
                    if not is_match:
                        continue
                    # Word boundary check
                    abs_start = region_start + i
                    abs_end = abs_start + term_len
                    if abs_start > 0:
                        char_before = text[abs_start - 1]
                        if char_before.isalnum():
                            continue
                    if abs_end < len(text):
                        char_after = text[abs_end]
                        if char_after.isalnum():
                            continue
                    fuzzy_matches.append((abs_start, abs_end, term_len, eng, chn))

        return fuzzy_matches

    @staticmethod
    def _get_unmatched_regions(text: str, occupied_spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """
        Given the text and a list of occupied (matched) spans, return the
        complementary unmatched regions.
        """
        if not occupied_spans:
            return [(0, len(text))]

        # Sort spans by start position
        sorted_spans = sorted(occupied_spans, key=lambda s: s[0])
        regions = []
        prev_end = 0
        for span_start, span_end in sorted_spans:
            if prev_end < span_start:
                regions.append((prev_end, span_start))
            prev_end = max(prev_end, span_end)
        if prev_end < len(text):
            regions.append((prev_end, len(text)))
        return regions

    @staticmethod
    def _generate_plural_variants(term: str) -> list[str]:
        """生成术语的复数/时态变体用于匹配。

        Handles English morphological rules:
        - -s plural: Agent -> Agents
        - -es plural: Watch -> Watches
        - -ies plural: Entity -> Entities (consonant + y)
        - -ed past: Handle -> Handled (silent e), Investigate -> Investigated
        - -ing gerund: Handle -> Handling (silent e), Run -> Running
        """
        variants = []
        # -s plural
        if not term.endswith('s'):
            variants.append(term + 's')
        # -es plural
        if not term.endswith('es'):
            variants.append(term + 'es')
        # -ies plural (consonant + y -> ies)
        if term.endswith('y') and len(term) > 1 and term[-2] not in 'aeiou':
            variants.append(term[:-1] + 'ies')
        # -ed past tense
        if not term.endswith('ed'):
            if term.endswith('e'):
                # Silent e: Handle -> Handled
                variants.append(term + 'd')
            else:
                variants.append(term + 'ed')
        # -ing gerund
        if not term.endswith('ing'):
            if term.endswith('e') and not term.endswith('ee'):
                # Silent e: Handle -> Handling (drop e, add ing)
                variants.append(term[:-1] + 'ing')
            else:
                variants.append(term + 'ing')
        return variants


# ============================================================
# FUZZY MATCHER - OCR Character Substitution
# ============================================================


class FuzzyMatcher:
    """OCR 字符替换模糊匹配器。

    检测常见 OCR 字符替换（如数字替代字母）并判断候选文本是否为
    术语表条目的 OCR 损坏形式。限制最多 max_edits 个字符替换以避免误报。
    """

    # Bidirectional OCR substitution mapping.
    # Each character maps to a set of characters it can be confused with.
    OCR_SUBSTITUTIONS: dict[str, set[str]] = {
        '0': {'O', 'o'},
        'O': {'0'},
        'o': {'0'},
        '1': {'l', 'I', 'i'},
        'l': {'1', 'I', 'i'},
        'I': {'1', 'l', 'i'},
        'i': {'1', 'l', 'I'},
        '5': {'S', 's'},
        'S': {'5'},
        's': {'5'},
        '8': {'B', 'b'},
        'B': {'8'},
        'b': {'8'},
    }

    def __init__(self, max_edits: int = 2):
        self._max_edits = max_edits

    def is_fuzzy_match(self, candidate: str, target: str) -> tuple[bool, int]:
        """
        判断 candidate 是否为 target 的 OCR 损坏形式。

        比较逐字符进行（大小写不敏感的精确匹配优先，然后检查 OCR 替换）。
        返回 (是否匹配, 替换字符数)。

        Rules:
        - candidate and target must have the same length
        - Characters that match exactly (case-insensitive) count as 0 edits
        - Characters that differ but are in OCR_SUBSTITUTIONS count as 1 edit each
        - Characters that differ and are NOT in OCR_SUBSTITUTIONS → not a match
        - Total edits must be >= 1 (pure exact matches are not fuzzy) and <= max_edits
        """
        if len(candidate) != len(target):
            return (False, 0)

        edits = 0
        for c_char, t_char in zip(candidate, target):
            # Exact match (case-insensitive)
            if c_char.lower() == t_char.lower():
                continue
            # Check OCR substitution
            subs = self.OCR_SUBSTITUTIONS.get(c_char)
            if subs and t_char in subs:
                edits += 1
                if edits > self._max_edits:
                    return (False, 0)
            else:
                # Not an OCR substitution - not a fuzzy match
                return (False, 0)

        # Must have at least 1 edit to be a "fuzzy" match (otherwise it's exact)
        if edits == 0:
            return (False, 0)

        return (True, edits)
