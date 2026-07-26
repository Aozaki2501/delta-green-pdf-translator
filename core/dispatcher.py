"""
Concurrent translation dispatcher with rate limiting and circuit breaker.

Provides DispatcherConfig (configuration dataclass), RateLimiter (token-bucket
rate limiter), and ConcurrentDispatcher (parallel translation orchestrator).

Dependencies: core.recursive_splitter, core.translator, core.progress.
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

from core.recursive_splitter import recursive_translate_group


@dataclass
class DispatcherConfig:
    """并发调度器配置。

    Attributes:
        concurrency: 并行 API 调用数 (1-64)
        rate_limit: 每分钟最大调用数
        cooldown: 批次间冷却秒数
        max_split_depth: 递归拆分最大深度
        fuzzy_matching: 是否启用模糊术语匹配
        backoff_threshold: 连续失败触发暂停的阈值
        backoff_seconds: 暂停时长（秒）
    """

    concurrency: int = 4
    rate_limit: int = 60
    cooldown: float = 1.0
    max_split_depth: int = 10
    fuzzy_matching: bool = False
    backoff_threshold: int = 10
    backoff_seconds: float = 30.0

    def __post_init__(self):
        self.concurrency = max(1, min(64, self.concurrency))
        self.rate_limit = max(1, self.rate_limit)
        self.cooldown = max(0.0, self.cooldown)
        self.max_split_depth = max(1, min(20, self.max_split_depth))
        self.backoff_threshold = max(1, self.backoff_threshold)
        self.backoff_seconds = max(0.0, self.backoff_seconds)


class RateLimiter:
    """滑动窗口令牌桶速率限制器（线程安全）。

    Uses a sliding window approach: tracks timestamps of recent calls within
    the last 60 seconds. When the window is full (calls_per_minute reached),
    new requests must wait until the oldest timestamp expires from the window.

    This avoids the burst-at-boundary problem of fixed-window rate limiters.

    Attributes:
        _max_calls: Maximum number of calls allowed per window.
        _window_seconds: Duration of the sliding window (60 seconds).
        _timestamps: List of timestamps for recent calls within the window.
        _lock: Threading lock for thread-safe access.
    """

    def __init__(self, calls_per_minute: int = 60):
        """Initialize the rate limiter.

        Args:
            calls_per_minute: Maximum number of API calls allowed per minute.
                              Must be at least 1.
        """
        self._max_calls = max(1, calls_per_minute)
        self._window_seconds = 60.0
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Attempt to acquire a call permit.

        Checks whether a new call can be made immediately. If the sliding
        window is not full, records the current timestamp and returns 0.
        If the window is full, calculates how long the caller must wait
        until the oldest call expires from the window.

        Returns:
            0.0 if the call can proceed immediately, or the number of
            seconds the caller should wait before retrying.
        """
        with self._lock:
            now = time.monotonic()
            # Purge expired timestamps outside the sliding window
            cutoff = now - self._window_seconds
            self._timestamps = [ts for ts in self._timestamps if ts > cutoff]

            if len(self._timestamps) < self._max_calls:
                # Window has capacity — record this call and proceed
                self._timestamps.append(now)
                return 0.0
            else:
                # Window is full — calculate wait time until oldest expires
                oldest = self._timestamps[0]
                wait_time = oldest + self._window_seconds - now
                return max(0.0, wait_time)

    def wait_if_needed(self):
        """Block until a call can be made.

        Repeatedly calls acquire() and sleeps if the rate limit is reached,
        until a permit is successfully obtained.
        """
        while True:
            wait_time = self.acquire()
            if wait_time == 0.0:
                return
            time.sleep(wait_time)


# Maximum characters to keep from the last completed translation as context
_CONTEXT_WINDOW_SIZE = 500


class ConcurrentDispatcher:
    """并发翻译调度器。

    将 block groups 分为批次，每批内使用 ThreadPoolExecutor 并行调度翻译。
    集成 RecursiveSplitter 处理失败组，维护滑动上下文窗口，并通过熔断机制
    防止 API 限流导致雪崩。

    Attributes:
        _config: DispatcherConfig 配置实例
        _translator: Translator 实例（有 translate_block 方法）
        _tracker: ProgressTracker 实例（有 mark_completed, mark_failed）
        _stats: TokenStats 实例（用于累加 token 用量）
        _progress_callback: 可选的进度回调 fn(block_idx, text, completed_count, total_count, stats)
        _rate_limiter: RateLimiter 实例
        _consecutive_failures: 连续失败计数
        _failure_lock: 保护 _consecutive_failures 的线程锁

    Note on TokenStats thread safety:
        TokenStats is accumulated via the shared Translator instance. Since
        Translator.translate_block calls stats.add() which uses an internal
        threading.Lock, token counts are safely accumulated across all
        concurrent worker threads without additional synchronization here.
    """

    def __init__(self, config: DispatcherConfig, translator, tracker,
                 stats, progress_callback: Callable | None = None):
        """初始化并发调度器。

        Args:
            config: DispatcherConfig 配置
            translator: Translator 实例（有 translate_block 方法）
            tracker: ProgressTracker 实例
            stats: TokenStats 实例（Translator 内部通过 _lock 线程安全累加）
            progress_callback: 可选回调，签名兼容 Streamlit Web UI:
                fn(block_idx, text, completed_count, total_count, stats)
                也兼容简化签名: fn(completed_count, total_count, block_idx)
        """
        self._config = config
        self._translator = translator
        self._tracker = tracker
        self._stats = stats
        self._progress_callback = progress_callback
        self._rate_limiter = RateLimiter(config.rate_limit)
        self._consecutive_failures = 0
        self._failure_lock = threading.Lock()

    def dispatch_all(
        self,
        groups: list[list],
        build_text_fn: Callable,
        parse_fn: Callable,
        source_type: str = "markdown",
    ) -> dict[int, str]:
        """调度所有翻译组的并发执行。

        将 groups 分为顺序批次（每批 concurrency 个），每批内并行执行。
        失败的组交给 RecursiveSplitter 处理。批次间插入 cooldown。
        维护滑动上下文窗口（500 字符）。最终结果按 block index 排序。

        Args:
            groups: block group 列表，每个 group 是 block 列表
            build_text_fn: 将 block 列表序列化为 API 请求文本的函数
            parse_fn: 解析翻译结果的函数
            source_type: "markdown" 或 "docx"

        Returns:
            {block_index: translated_text} 按 block index 排序
        """
        all_translations: dict[int, str] = {}
        total_blocks = sum(len(g) for g in groups)
        completed_count = 0
        # Lock for thread-safe updates to shared state
        results_lock = threading.Lock()

        # Context is the tail of the preceding group's *source* text, computed up
        # front. Using translations instead made the prompt depend on which
        # results happened to be ready, so the same document translated with a
        # different concurrency produced different text — and reused the old
        # cache anyway. Source text is known before any call, so every group gets
        # the same context no matter how the batches are scheduled.
        group_contexts = self._build_group_contexts(groups)

        batch_size = self._config.concurrency
        batches = [groups[i:i + batch_size] for i in range(0, len(groups), batch_size)]

        for batch_idx, batch in enumerate(batches):
            # Check circuit breaker before each batch
            self._check_circuit_breaker()

            # Insert cooldown between batches (not before the first one)
            if batch_idx > 0 and self._config.cooldown > 0:
                time.sleep(self._config.cooldown)

            def _dispatch_group(group, prev_context):
                """Dispatch a single group through RecursiveSplitter."""
                # Rate limit before making API call
                self._rate_limiter.wait_if_needed()

                translate_fn = self._translator.translate_block
                result = recursive_translate_group(
                    group=group,
                    translate_fn=translate_fn,
                    parse_fn=parse_fn,
                    build_text_fn=build_text_fn,
                    prev_context=prev_context,
                    source_type=source_type,
                    cache=self._tracker,
                    max_depth=self._config.max_split_depth,
                )
                return result

            # Execute batch concurrently
            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                futures = {}
                for group_offset, group in enumerate(batch):
                    group_index = batch_idx * batch_size + group_offset
                    future = executor.submit(
                        _dispatch_group, group, group_contexts[group_index]
                    )
                    futures[future] = group

                for future in as_completed(futures):
                    group = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        # Worker raised an unexpected exception — mark all blocks failed
                        self._record_failure()
                        for block in group:
                            self._tracker.mark_failed(block.index, str(exc))
                            with results_lock:
                                completed_count += 1
                                current_count = completed_count
                            self._report_progress(block.index, str(exc),
                                                  current_count, total_blocks)
                        continue

                    # Process successful translations
                    if result.translations:
                        self._record_success()
                        with results_lock:
                            all_translations.update(result.translations)
                        self._tracker.mark_completed_many(result.translations)
                        for idx, text in result.translations.items():
                            with results_lock:
                                completed_count += 1
                                current_count = completed_count
                            self._report_progress(idx, text,
                                                  current_count, total_blocks)

                    # Process failed blocks
                    if result.failed_indices:
                        self._record_failure()
                        for idx in result.failed_indices:
                            self._tracker.mark_failed(idx, "translation failed after recursive split")
                            with results_lock:
                                completed_count += 1
                                current_count = completed_count
                            self._report_progress(idx, "translation failed after recursive split",
                                                  current_count, total_blocks)

        self._tracker.flush()
        # Return results sorted by block index
        return dict(sorted(all_translations.items()))

    @staticmethod
    def _build_group_contexts(groups: list[list]) -> list[str]:
        """Return, for each group, the source-text tail of the group before it."""
        contexts = []
        previous_tail = ""
        for group in groups:
            contexts.append(previous_tail)
            source = "\n\n".join(str(getattr(block, "text", "") or "") for block in group)
            previous_tail = source[-_CONTEXT_WINDOW_SIZE:] if source else previous_tail
        return contexts

    def _report_progress(self, block_idx: int, text: str,
                         completed_count: int, total_count: int) -> None:
        """调用进度回调，兼容两种签名。

        优先尝试 Streamlit Web UI 签名:
            fn(block_idx, text, completed_count, total_count, stats)
        如果失败则回退到简化签名:
            fn(completed_count, total_count, block_idx)

        Args:
            block_idx: 当前完成的 block index
            text: 翻译文本（成功时为译文，失败时为错误信息）
            completed_count: 已完成的 block 总数
            total_count: 需要处理的 block 总数
        """
        if not self._progress_callback:
            return
        try:
            self._progress_callback(block_idx, text, completed_count, total_count, self._stats)
        except TypeError:
            try:
                self._progress_callback(block_idx, text, completed_count, total_count)
            except TypeError:
                # Legacy signature: (completed_count, total_count, block_idx)
                self._progress_callback(completed_count, total_count, block_idx)

    def _check_circuit_breaker(self):
        """检查是否需要触发熔断暂停。

        当连续失败次数达到阈值时，暂停所有 worker 一段时间后重置计数器。
        """
        should_pause = False
        pause_seconds = 0.0
        with self._failure_lock:
            if self._consecutive_failures >= self._config.backoff_threshold:
                self._consecutive_failures = 0
                should_pause = True
                pause_seconds = self._config.backoff_seconds
        if should_pause:
            time.sleep(pause_seconds)

    def _record_success(self):
        """记录成功，重置连续失败计数。"""
        with self._failure_lock:
            self._consecutive_failures = 0

    def _record_failure(self):
        """记录失败，递增连续失败计数。"""
        with self._failure_lock:
            self._consecutive_failures += 1
