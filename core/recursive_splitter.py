"""
Recursive binary splitter for failed translation block groups.

When a block group translation fails, this module splits it into halves and
retries each half independently, recursing until single-block level.

Provides SplitResult (result dataclass), TranslateFunc and ParseFunc (Protocol
types for dependency injection).

Dependencies: core.translator (via Protocol), core.progress (via Protocol).
"""

from dataclasses import dataclass, field
from typing import Callable, Protocol

from core.constants import TRANSLATION_FAILURE_PREFIX


class TranslateFunc(Protocol):
    """翻译函数签名，兼容 Translator.translate_block。"""

    def __call__(
        self,
        text: str,
        block_index: int | None = None,
        prev_context: str = "",
        source_type: str = "markdown",
        cache=None,
    ) -> str: ...


class ParseFunc(Protocol):
    """解析函数签名，兼容 _parse_marked_md_translation。

    接收翻译后的文本和原始 group 列表，返回 {block_index: translated_text} 字典。
    缺失的 block index 表示该块翻译失败或标记缺失。
    """

    def __call__(self, translated: str, group: list) -> dict[int, str]: ...


@dataclass
class SplitResult:
    """递归拆分的最终结果。

    Attributes:
        translations: 成功翻译的 {block_index: translated_text}
        failed_indices: 最终失败的 block index 列表
        split_count: 实际发生的拆分次数
        total_api_calls: 总 API 调用次数（含重试）
    """

    translations: dict[int, str] = field(default_factory=dict)
    failed_indices: list[int] = field(default_factory=list)
    split_count: int = 0
    total_api_calls: int = 0


def _is_failed_translation(text: str) -> bool:
    """Check if a translation result is a failure marker."""
    return bool(text and text.lstrip().startswith(TRANSLATION_FAILURE_PREFIX))


def recursive_translate_group(
    group: list,
    translate_fn: TranslateFunc,
    parse_fn: ParseFunc,
    build_text_fn: Callable[[list], str],
    prev_context: str = "",
    source_type: str = "markdown",
    cache=None,
    max_depth: int = 10,
    progress_callback: Callable[[int, str], None] | None = None,
) -> SplitResult:
    """
    递归翻译一个 block group。

    流程：
    1. 尝试翻译整组（translate_fn 内部已有 3 次重试）
    2. 解析返回的 BLOCK 标记（parse_fn）
    3. 如果全部成功 → 返回
    4. 如果部分成功 → 保留成功部分，对缺失块递归
    5. 如果完全失败 → 二分拆分，对每半递归
    6. 递归深度超过 max_depth → 标记所有剩余块为失败

    Args:
        group: block 列表（每个 block 需有 .index 和 .text 属性）
        translate_fn: 翻译函数（兼容 Translator.translate_block）
        parse_fn: 解析函数（兼容 _parse_marked_md_translation）
        build_text_fn: 将 block 列表序列化为 API 请求文本的函数
        prev_context: 前一组的翻译上下文（最多 500 字符）
        source_type: "markdown" 或 "docx"
        cache: ProgressTracker 缓存实例
        max_depth: 最大递归深度（默认 10）
        progress_callback: 成功时的进度回调 fn(block_index, translated_text)

    Returns:
        SplitResult 包含成功翻译和失败索引
    """
    result = SplitResult()
    _recursive_translate(
        group=group,
        translate_fn=translate_fn,
        parse_fn=parse_fn,
        build_text_fn=build_text_fn,
        prev_context=prev_context,
        source_type=source_type,
        cache=cache,
        max_depth=max_depth,
        current_depth=0,
        progress_callback=progress_callback,
        result=result,
    )
    return result


def _recursive_translate(
    group: list,
    translate_fn: TranslateFunc,
    parse_fn: ParseFunc,
    build_text_fn: Callable[[list], str],
    prev_context: str,
    source_type: str,
    cache,
    max_depth: int,
    current_depth: int,
    progress_callback: Callable[[int, str], None] | None,
    result: SplitResult,
) -> None:
    """递归翻译的内部实现，直接修改 result 对象。"""

    if not group:
        return

    # 深度限制：超限时标记所有剩余块为失败
    if current_depth > max_depth:
        for block in group:
            result.failed_indices.append(block.index)
        return

    # 单块组：直接翻译，不使用 BLOCK 标记
    if len(group) == 1:
        block = group[0]
        result.total_api_calls += 1
        translated = translate_fn(
            block.text,
            block_index=block.index,
            prev_context=prev_context,
            source_type=source_type,
            cache=cache,
        )

        # 判断翻译是否成功
        if translated and not _is_failed_translation(translated) and translated.strip():
            result.translations[block.index] = translated.strip()
            if progress_callback:
                progress_callback(block.index, translated.strip())
        else:
            result.failed_indices.append(block.index)
        return

    # 多块组：使用 build_text_fn 序列化，然后翻译
    text = build_text_fn(group)
    first_idx = group[0].index
    result.total_api_calls += 1
    translated = translate_fn(
        text,
        block_index=first_idx,
        prev_context=prev_context,
        source_type=source_type,
        cache=cache,
    )

    # 完全失败：空响应或失败标记
    if not translated or _is_failed_translation(translated) or not translated.strip():
        # 二分拆分
        result.split_count += 1
        mid = len(group) // 2
        left_half = group[:mid]
        right_half = group[mid:]

        _recursive_translate(
            group=left_half,
            translate_fn=translate_fn,
            parse_fn=parse_fn,
            build_text_fn=build_text_fn,
            prev_context=prev_context,
            source_type=source_type,
            cache=cache,
            max_depth=max_depth,
            current_depth=current_depth + 1,
            progress_callback=progress_callback,
            result=result,
        )
        _recursive_translate(
            group=right_half,
            translate_fn=translate_fn,
            parse_fn=parse_fn,
            build_text_fn=build_text_fn,
            prev_context=prev_context,
            source_type=source_type,
            cache=cache,
            max_depth=max_depth,
            current_depth=current_depth + 1,
            progress_callback=progress_callback,
            result=result,
        )
        return

    # 尝试解析 BLOCK 标记
    try:
        parsed = parse_fn(translated, group)
    except (ValueError, Exception):
        # 解析完全失败 → 二分拆分
        result.split_count += 1
        mid = len(group) // 2
        left_half = group[:mid]
        right_half = group[mid:]

        _recursive_translate(
            group=left_half,
            translate_fn=translate_fn,
            parse_fn=parse_fn,
            build_text_fn=build_text_fn,
            prev_context=prev_context,
            source_type=source_type,
            cache=cache,
            max_depth=max_depth,
            current_depth=current_depth + 1,
            progress_callback=progress_callback,
            result=result,
        )
        _recursive_translate(
            group=right_half,
            translate_fn=translate_fn,
            parse_fn=parse_fn,
            build_text_fn=build_text_fn,
            prev_context=prev_context,
            source_type=source_type,
            cache=cache,
            max_depth=max_depth,
            current_depth=current_depth + 1,
            progress_callback=progress_callback,
            result=result,
        )
        return

    # 检查解析结果
    expected_indices = {block.index for block in group}
    found_indices = set(parsed.keys())
    missing_indices = expected_indices - found_indices

    # 保留成功解析的块
    for idx, text_val in parsed.items():
        if text_val and idx in expected_indices:
            result.translations[idx] = text_val

    # 报告成功的子组进度
    if parsed and progress_callback:
        for idx, text_val in parsed.items():
            if text_val and idx in expected_indices:
                progress_callback(idx, text_val)

    # 全部成功
    if not missing_indices:
        return

    # 部分成功：对缺失块递归
    missing_blocks = [block for block in group if block.index in missing_indices]

    if len(missing_blocks) == len(group):
        # 所有块都缺失（parsed 为空但没抛异常的情况）→ 二分拆分
        result.split_count += 1
        mid = len(group) // 2
        left_half = group[:mid]
        right_half = group[mid:]

        _recursive_translate(
            group=left_half,
            translate_fn=translate_fn,
            parse_fn=parse_fn,
            build_text_fn=build_text_fn,
            prev_context=prev_context,
            source_type=source_type,
            cache=cache,
            max_depth=max_depth,
            current_depth=current_depth + 1,
            progress_callback=progress_callback,
            result=result,
        )
        _recursive_translate(
            group=right_half,
            translate_fn=translate_fn,
            parse_fn=parse_fn,
            build_text_fn=build_text_fn,
            prev_context=prev_context,
            source_type=source_type,
            cache=cache,
            max_depth=max_depth,
            current_depth=current_depth + 1,
            progress_callback=progress_callback,
            result=result,
        )
    else:
        # 部分缺失：对缺失块组递归（视为新的子组）
        result.split_count += 1
        _recursive_translate(
            group=missing_blocks,
            translate_fn=translate_fn,
            parse_fn=parse_fn,
            build_text_fn=build_text_fn,
            prev_context=prev_context,
            source_type=source_type,
            cache=cache,
            max_depth=max_depth,
            current_depth=current_depth + 1,
            progress_callback=progress_callback,
            result=result,
        )
