"""
Translation engine: API client, prompt construction, retry logic, and batch concurrency.

Provides the Translator class (DeepSeek V4 API wrapper with context window),
TokenStats dataclass (token usage and cost tracking), and
translate_batch_concurrent (parallel page translation with progress tracking).

Dependencies: openai, core.constants, core.glossary (for find_relevant_glossary_terms).
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from openai import OpenAI

from core.constants import TRANSLATION_FAILURE_PREFIX, PROMPT_VERSION
from core.glossary import find_relevant_glossary_terms


# ============================================================
# TOKEN COST TRACKER
# ============================================================

@dataclass
class TokenStats:
    """Tracks token usage and estimated cost."""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    api_calls: int = 0
    failed_calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    PRICE_INPUT_PER_M = 1.0
    PRICE_OUTPUT_PER_M = 4.0
    PRICE_CACHED_PER_M = 0.1

    def add(self, input_tok: int, output_tok: int, cached_tok: int = 0):
        with self._lock:
            self.input_tokens += input_tok
            self.output_tokens += output_tok
            self.cached_tokens += cached_tok
            self.api_calls += 1

    def add_failure(self):
        with self._lock:
            self.failed_calls += 1

    @property
    def total_tokens(self):
        return self.input_tokens + self.output_tokens

    @property
    def cost_yuan(self):
        cost = (
            (self.input_tokens - self.cached_tokens) * self.PRICE_INPUT_PER_M / 1_000_000 +
            self.output_tokens * self.PRICE_OUTPUT_PER_M / 1_000_000 +
            self.cached_tokens * self.PRICE_CACHED_PER_M / 1_000_000
        )
        return cost

    def summary(self) -> str:
        return (
            f"Token Stats:\n"
            f"   Input: {self.input_tokens:,} tokens\n"
            f"   Output: {self.output_tokens:,} tokens\n"
            f"   Cache hit: {self.cached_tokens:,} tokens\n"
            f"   API calls: {self.api_calls} (failed {self.failed_calls})\n"
            f"   Est. cost: Y{self.cost_yuan:.3f}"
        )


# ============================================================
# TRANSLATOR — DeepSeek V4 API with Context Window
# ============================================================

class Translator:
    """Translates text using DeepSeek V4 API with context window and cost tracking."""

    SYSTEM_PROMPT = """You are a professional TRPG translator working on Delta Green sourcebooks.

Translation rules:
0. If the source starts with [[TOC]], preserve the table of contents structure. Do not translate entries; keep dotted leaders and page numbers.
1. Follow the glossary strictly for proper nouns. If glossary entries overlap, the longest matching phrase wins.
2. Keep untranslated: dice notations (1D6, 3D6), attributes (STR, CON, DEX, INT, POW, CHA, SAN, WP, HP), skill checks (1/1D6 SAN), abbreviations (FBI, CIA, MJ-12, A-Cell).
3. Output in Markdown format with ## headings, - bullet lists, paragraph spacing.
4. Professional, fluent Chinese. Maintain horror atmosphere. Precise rule descriptions.
5. Keep the Chinese translation concise. Do not expand, explain, embellish, or add information not present in the source.
6. Do not translate page headers, footers, page numbers, or running titles such as DELTA GREEN, PISCES, and THE MILLENNIUM when they appear as standalone navigation text.
7. Preserve section and subsection headings. Output article titles as ## headings and smaller section headings as ### headings.
8. If decorative title-card text, drop shadows, or stylized text is extracted twice, translate it only once.
9. If OCR errors/garbled text exists, infer meaning from context. Mark unreadable as [damaged].
10. If previous context is provided, ensure continuity. Do not re-translate previous content.
11. Preserve Markdown tables as Markdown tables. Translate cell text but keep the same columns.
12. Preserve blockquotes starting with > for handouts/player aids.
13. Preserve [CARD] and [/CARD] marker lines exactly. Text inside a card must stay inside the card and must not be merged into surrounding body text.

{glossary_section}"""

    def __init__(self, api_key: str, model: str = "deepseek-v4-pro",
                 base_url: str = "https://api.deepseek.com", stats: TokenStats = None):
        if not api_key or not str(api_key).strip():
            raise ValueError("API Key 不能为空")
        if not model or not str(model).strip():
            raise ValueError("模型名称不能为空")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.glossary = {}
        self.retry_count = 3
        self.retry_delay = 5
        self.stats = stats or TokenStats()

    def set_glossary(self, glossary: dict):
        self.glossary = glossary

    def _build_glossary_for_chunk(self, text: str) -> str:
        if not self.glossary:
            return ""
        relevant = self._find_relevant_glossary_terms(text)
        if not relevant:
            return ""
        glossary_lines = [f"   - {eng} -> {chn}" for eng, chn in relevant.items()]
        return "\nGlossary (this section):\n" + "\n".join(glossary_lines)

    def _find_relevant_glossary_terms(self, text: str) -> dict:
        return find_relevant_glossary_terms(text, self.glossary)

    def translate_chunk(self, text: str, page_num: int = None, prev_context: str = "") -> str:
        if not text.strip():
            return ""
        glossary_section = self._build_glossary_for_chunk(text)
        system_prompt = self.SYSTEM_PROMPT.format(glossary_section=glossary_section)

        page_info = f" (page {page_num + 1})" if page_num is not None else ""
        if prev_context:
            user_prompt = (
                f"[Previous context - DO NOT translate, for reference only]\n"
                f"{prev_context}\n\n---\n\n"
                f"Translate the following{page_info}:\n\n{text}"
            )
        else:
            user_prompt = f"Translate the following{page_info}:\n\n{text}"

        for attempt in range(self.retry_count):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=4096,
                )
                usage = response.usage
                if usage:
                    cached = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
                    self.stats.add(
                        getattr(usage, "prompt_tokens", 0) or 0,
                        getattr(usage, "completion_tokens", 0) or 0,
                        cached,
                    )
                if not response.choices:
                    raise RuntimeError("API 返回空 choices")
                content = response.choices[0].message.content or ""
                content = content.strip()
                if not content:
                    raise RuntimeError("API 返回空译文")
                return content
            except Exception as e:
                self.stats.add_failure()
                if attempt < self.retry_count - 1:
                    wait = self.retry_delay * (attempt + 1)
                    print(f"\n  API error (attempt {attempt+1}/{self.retry_count}): {e}")
                    print(f"     Retrying in {wait}s...", end="", flush=True)
                    time.sleep(wait)
                else:
                    print(f"\n  API failed permanently: {e}")
                    return f"{TRANSLATION_FAILURE_PREFIX} {e}]\n\nOriginal:\n{text[:200]}..."
        return ""


# ============================================================
# BATCH CONCURRENT TRANSLATOR
# ============================================================

def _is_failed_translation(text: str) -> bool:
    """Check if a translation result is a failure marker."""
    return bool(text and text.lstrip().startswith(TRANSLATION_FAILURE_PREFIX))


def translate_batch_concurrent(pages_data, translator, tracker, max_workers=4, progress_callback=None):
    results = {}
    completed_count = 0
    total_count = len(pages_data)
    max_workers = max(1, int(max_workers or 1))

    def report(page_num, translation):
        nonlocal completed_count
        completed_count += 1
        if progress_callback:
            progress_callback(page_num, translation or "", completed_count, total_count)

    def translate_one(page_num, text, prev_ctx):
        translation = translator.translate_chunk(text, page_num, prev_ctx)
        if translation and not _is_failed_translation(translation):
            tracker.mark_completed(page_num, translation)
        return page_num, translation

    group_size = max_workers
    prev_context = ""

    for group_start in range(0, len(pages_data), group_size):
        group = pages_data[group_start:group_start + group_size]
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for page_num, text, page_context in group:
                if tracker.is_completed(page_num):
                    translation = tracker.get_translation(page_num)
                    results[page_num] = translation
                    report(page_num, translation)
                    continue
                if not text.strip():
                    tracker.mark_completed(page_num, "")
                    results[page_num] = ""
                    report(page_num, "")
                    continue
                future = executor.submit(translate_one, page_num, text, prev_context or page_context)
                futures[future] = page_num

            for future in as_completed(futures):
                page_num = futures[future]
                try:
                    page_num, translation = future.result()
                except Exception as exc:
                    translation = f"{TRANSLATION_FAILURE_PREFIX} {exc}]"
                    print(f" p{page_num + 1} failed: {exc}", end="", flush=True)
                results[page_num] = translation or ""
                report(page_num, translation)
                if not _is_failed_translation(translation):
                    print(f" p{page_num + 1} done", end="", flush=True)

        if group:
            last_page_num = group[-1][0]
            last_translation = results.get(last_page_num, "")
            if last_translation:
                prev_context = last_translation[-300:]
        print()

    return results
