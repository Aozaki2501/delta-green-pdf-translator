# Requirements Document

## Introduction

本文档定义了普通翻译管线（非 PDF 坐标复刻模式）的三项增强需求：递归任务拆分、AC 自动机术语匹配、并发翻译调度。这些改进旨在提高翻译成功率、术语匹配效率和整体吞吐量，同时保持与现有 Web UI 进度显示的兼容性。

## Glossary

- **Translation_Pipeline**: 从文本提取到 API 调用再到译文写入的完整翻译流程，包括 Markdown 和 Word 两种输入格式
- **Block_Group**: 多个文本块（MdBlock）合并为一组，通过 `[BLOCK N]...[/BLOCK N]` 标记一次性发送给翻译 API 的单位
- **Recursive_Splitter**: 当 Block_Group 翻译失败时，将其递归二分拆分并重试的容错机制
- **AC_Automaton**: 基于 Aho-Corasick 算法的多模式匹配自动机，用于在 O(n) 时间内同时匹配所有术语表条目
- **Fuzzy_Matcher**: 针对 OCR 错误的模糊匹配组件，处理字符替换（如数字替代字母）的情况
- **Plural_Normalizer**: 英文复数归一化组件，去除 -s/-es/-ed 后缀后再进行术语匹配
- **Article_Filter**: 冠词过滤组件，在匹配术语时忽略前置的 the/a/an
- **Concurrent_Dispatcher**: 管理多个并行 API 调用的调度器，包含速率限制和冷却机制
- **Rate_Limiter**: 控制单位时间内 API 调用次数的限流器
- **Cooldown**: 批次之间的冷却等待时间，防止触发 API 速率限制
- **Progress_Tracker**: 现有的进度跟踪系统（ProgressTracker 类），负责断点续跑和进度持久化
- **Translator**: 现有的翻译引擎类，封装 OpenAI 兼容 API 的调用逻辑
- **TokenStats**: 现有的 token 用量和费用统计数据类

## Requirements

### Requirement 1: Recursive Task Splitting on Failure

**User Story:** As a translator operator, I want failed block groups to be automatically split and retried, so that partial failures do not waste the entire group's translation effort.

#### Acceptance Criteria

1. WHEN a Block_Group translation API call returns a failure (timeout, network error, or empty response), THE Recursive_Splitter SHALL split the Block_Group into two approximately equal halves and retry each half independently
2. WHEN a Block_Group translation returns a response with missing or malformed `[BLOCK N]` markers, THE Recursive_Splitter SHALL split the Block_Group into two halves and retry each half independently
3. WHILE recursively splitting, THE Recursive_Splitter SHALL continue splitting failed halves until each sub-group contains exactly one block
4. WHEN a single-block sub-group fails after retry, THE Recursive_Splitter SHALL mark that individual block as failed and continue processing remaining blocks
5. THE Recursive_Splitter SHALL preserve the original block ordering when reassembling successful translations from split sub-groups
6. THE Recursive_Splitter SHALL reuse the existing Translator retry logic (3 attempts with exponential backoff) for each sub-group before deciding to split further
7. WHEN a Block_Group of size 1 fails all retry attempts, THE Recursive_Splitter SHALL record the failure in Progress_Tracker using the existing `mark_failed` interface
8. THE Recursive_Splitter SHALL report progress for each successfully translated sub-group through the existing progress_callback mechanism
9. IF the recursive splitting depth exceeds 10 levels, THEN THE Recursive_Splitter SHALL abort the current group and mark all remaining blocks as failed

### Requirement 2: AC Automaton Glossary Matching

**User Story:** As a translator operator, I want glossary term matching to be fast and tolerant of OCR errors, so that large glossaries do not slow down translation and OCR-damaged text still gets correct terminology.

#### Acceptance Criteria

1. THE AC_Automaton SHALL build a multi-pattern automaton from all glossary entries and match all terms in a single O(n) pass over the source text, where n is the length of the source text
2. THE AC_Automaton SHALL produce the same longest-match-first, non-overlapping results as the current `find_relevant_glossary_terms` function for identical inputs without fuzzy matching enabled
3. WHEN multiple glossary terms overlap at the same position, THE AC_Automaton SHALL select the longest matching term
4. THE Fuzzy_Matcher SHALL detect common OCR character substitutions (0↔O, 1↔l↔I, 5↔S, 8↔B) and match glossary terms despite these errors
5. THE Fuzzy_Matcher SHALL limit fuzzy matching to at most 2 character substitutions per term to avoid false positives
6. THE Plural_Normalizer SHALL strip English suffixes (-s, -es, -ed, -ing) from source text tokens before matching against glossary entries
7. THE Plural_Normalizer SHALL not modify glossary entries themselves, only normalize the source text for matching purposes
8. THE Article_Filter SHALL ignore English articles (the, a, an) immediately preceding a potential glossary term when determining matches
9. THE AC_Automaton SHALL be constructed once per translation session and reused across all blocks within that session
10. WHEN fuzzy matching produces a match, THE AC_Automaton SHALL annotate the match with the original (possibly corrupted) text and the canonical glossary term
11. THE AC_Automaton SHALL expose a `find_relevant_glossary_terms` compatible interface so existing callers can switch without code changes beyond initialization
12. IF the glossary is empty, THEN THE AC_Automaton SHALL return an empty result without error

### Requirement 3: Concurrent Translation Dispatch

**User Story:** As a translator operator, I want multiple translation API calls to run in parallel with rate limiting, so that large documents translate faster without triggering API rate limits.

#### Acceptance Criteria

1. THE Concurrent_Dispatcher SHALL accept a configurable concurrency level (number of parallel API calls) with a default of 4 and a maximum of 64
2. THE Concurrent_Dispatcher SHALL dispatch up to the configured number of Block_Group translations simultaneously
3. THE Rate_Limiter SHALL enforce a configurable maximum number of API calls per minute, defaulting to 60 calls per minute
4. WHEN the rate limit is reached, THE Rate_Limiter SHALL queue pending requests and dispatch them as capacity becomes available
5. THE Concurrent_Dispatcher SHALL insert a configurable cooldown period (default 1 second) between consecutive batches of dispatched requests
6. THE Concurrent_Dispatcher SHALL report translation progress (completed count, total count, current block identifier) through the existing progress_callback interface compatible with the Streamlit Web UI
7. THE Concurrent_Dispatcher SHALL update Progress_Tracker atomically for each completed or failed block group, maintaining thread safety
8. WHEN a block group fails within the Concurrent_Dispatcher, THE Concurrent_Dispatcher SHALL invoke the Recursive_Splitter for that group before marking blocks as failed
9. THE Concurrent_Dispatcher SHALL maintain a sliding context window, passing the most recent translated text (up to 500 characters) as prev_context to subsequent translation calls within the same sequential batch
10. THE Concurrent_Dispatcher SHALL integrate with the existing TokenStats tracking, accumulating token usage and cost across all concurrent workers
11. THE Concurrent_Dispatcher SHALL replace the current serial translation loop in `translate_md_file` and `translate_docx_file` while preserving the same function signatures and return values
12. IF all workers encounter consecutive failures exceeding 10 total failures within a single batch, THEN THE Concurrent_Dispatcher SHALL pause all workers for a configurable backoff period (default 30 seconds) before resuming
13. THE Concurrent_Dispatcher SHALL ensure that the final translation output is ordered by original block index regardless of completion order

### Requirement 4: Configuration Interface

**User Story:** As a translator operator, I want to configure the new features through the existing config and UI, so that I can tune behavior without modifying code.

#### Acceptance Criteria

1. THE Translation_Pipeline SHALL expose the following configuration parameters: concurrency level, rate limit (calls/minute), cooldown between batches (seconds), recursive split max depth, and fuzzy matching toggle
2. THE Translation_Pipeline SHALL accept configuration parameters through function arguments with sensible defaults, requiring no configuration file changes for basic usage
3. WHEN the Streamlit Web UI is used, THE Translation_Pipeline SHALL expose concurrency level and rate limit as sidebar controls in the "高级任务控制" expander
4. THE Translation_Pipeline SHALL log configuration values at the start of each translation session for debugging purposes
