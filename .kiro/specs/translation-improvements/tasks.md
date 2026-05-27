# Implementation Plan: Translation Improvements

## Overview

本实现计划将三项翻译管线增强（递归任务拆分、AC 自动机术语匹配、并发翻译调度）分解为可增量执行的编码任务。每个任务构建在前一步之上，最终通过集成层将所有组件连接到现有的 `translate_md.py` 和 `translate_docx.py` 入口。

## Tasks

- [x] 1. 安装依赖并创建核心数据模型
  - [x] 1.1 添加新依赖并创建 DispatcherConfig 和 SplitResult 数据模型
    - 在项目根目录的 `requirements.txt`（或等效依赖文件）中添加 `hypothesis>=6.100.0` 和 `pyahocorasick>=2.0.0`
    - 创建 `core/dispatcher.py`，定义 `DispatcherConfig` 数据类（含 `__post_init__` 验证）
    - 创建 `core/recursive_splitter.py`，定义 `SplitResult` 数据类
    - 定义 `TranslateFunc` 和 `ParseFunc` Protocol 类型
    - _Requirements: 3.1, 1.9, 4.1_

- [x] 2. 实现 AC 自动机术语匹配器
  - [x] 2.1 实现 ACGlossaryMatcher 核心类
    - 在 `core/glossary.py` 中新增 `GlossaryMatch` 数据类
    - 实现 `ACGlossaryMatcher.__init__` 和 `_build_automaton` 方法
    - 实现 `find_relevant_glossary_terms` 兼容接口（最长匹配优先、非重叠）
    - 实现 `find_relevant_glossary_terms_annotated` 增强接口
    - 实现 `_generate_plural_variants` 静态方法
    - 添加 pyahocorasick 未安装时的 fallback 逻辑（打印警告，回退到旧正则）
    - _Requirements: 2.1, 2.2, 2.3, 2.9, 2.11, 2.12_

  - [ ]* 2.2 编写属性测试：AC 自动机与正则等价性
    - **Property 4: AC automaton oracle equivalence**
    - **Validates: Requirements 2.2, 2.3**

  - [x] 2.3 实现 FuzzyMatcher OCR 模糊匹配器
    - 在 `core/glossary.py` 中实现 `FuzzyMatcher` 类
    - 定义 `OCR_SUBSTITUTIONS` 映射表（0↔O, 1↔l↔I, 5↔S, 8↔B）
    - 实现 `is_fuzzy_match` 方法，限制最多 2 个字符替换
    - 将模糊匹配集成到 `ACGlossaryMatcher` 作为第二遍扫描
    - _Requirements: 2.4, 2.5, 2.10_

  - [ ]* 2.4 编写属性测试：模糊 OCR 匹配正确性
    - **Property 5: Fuzzy OCR matching finds corrupted terms**
    - **Validates: Requirements 2.4**

  - [ ]* 2.5 编写属性测试：模糊匹配拒绝过多替换
    - **Property 6: Fuzzy match rejects excessive substitutions**
    - **Validates: Requirements 2.5**

  - [x] 2.6 实现复数归一化和冠词过滤
    - 在 `ACGlossaryMatcher._build_automaton` 中插入复数变体
    - 实现冠词过滤逻辑（匹配时忽略前置 the/a/an）
    - 确保不修改原始术语表字典
    - _Requirements: 2.6, 2.7, 2.8_

  - [ ]* 2.7 编写属性测试：复数和冠词归一化
    - **Property 7: Plural and article normalization finds variants**
    - **Validates: Requirements 2.6, 2.8**

  - [ ]* 2.8 编写属性测试：术语表不可变性
    - **Property 8: Glossary immutability**
    - **Validates: Requirements 2.7**

  - [ ]* 2.9 编写属性测试：模糊匹配注释完整性
    - **Property 9: Fuzzy match annotation completeness**
    - **Validates: Requirements 2.10**

  - [x] 2.10 重构 glossary.py 向后兼容入口
    - 将现有 `find_relevant_glossary_terms` 重命名为 `_find_relevant_glossary_terms_regex`
    - 新增 `build_glossary_matcher` 工厂函数
    - 新增兼容签名的 `find_relevant_glossary_terms(text, glossary, matcher=None)` 入口
    - 确保所有现有调用方无需修改即可工作
    - _Requirements: 2.11, 2.12_

- [x] 3. Checkpoint - 确保术语匹配器测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. 实现递归任务拆分器
  - [x] 4.1 实现 recursive_translate_group 核心函数
    - 在 `core/recursive_splitter.py` 中实现完整的递归拆分逻辑
    - 实现二分拆分：失败时将组分为两个近似相等的子组
    - 实现部分成功处理：保留已解析的块，对缺失块递归
    - 实现深度限制（max_depth=10）：超限时标记所有剩余块为失败
    - 实现 progress_callback 报告每个成功的子组
    - 单块组不使用 BLOCK 标记（与现有行为一致）
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9_

  - [ ]* 4.2 编写属性测试：拆分保留所有块
    - **Property 1: Split preserves all blocks**
    - **Validates: Requirements 1.1, 1.2**

  - [ ]* 4.3 编写属性测试：递归终止于单块级别
    - **Property 2: Recursive termination at single-block level**
    - **Validates: Requirements 1.3**

  - [ ]* 4.4 编写属性测试：拆分重组保持顺序
    - **Property 3: Split reassembly preserves ordering**
    - **Validates: Requirements 1.5**

- [x] 5. Checkpoint - 确保递归拆分器测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. 实现并发翻译调度器
  - [x] 6.1 实现 RateLimiter 令牌桶速率限制器
    - 在 `core/dispatcher.py` 中实现 `RateLimiter` 类
    - 使用滑动窗口令牌桶算法（线程安全）
    - 实现 `acquire` 和 `wait_if_needed` 方法
    - _Requirements: 3.3, 3.4_

  - [x] 6.2 实现 ConcurrentDispatcher 调度器核心
    - 在 `core/dispatcher.py` 中实现 `ConcurrentDispatcher` 类
    - 使用 `ThreadPoolExecutor` 实现并发调度
    - 实现批次间 cooldown 插入
    - 实现熔断机制（连续 10 次失败暂停 30 秒）
    - 集成 `RecursiveSplitter` 处理失败组
    - 维护滑动上下文窗口（500 字符）
    - 确保最终结果按 block index 排序
    - _Requirements: 3.1, 3.2, 3.5, 3.7, 3.8, 3.9, 3.12, 3.13_

  - [x] 6.3 实现进度报告和 TokenStats 集成
    - 在 `ConcurrentDispatcher` 中实现 progress_callback 调用
    - 确保 TokenStats 跨所有 worker 线程安全累加
    - 兼容现有 Streamlit Web UI 的 progress_callback 签名
    - _Requirements: 3.6, 3.10_

  - [ ]* 6.4 编写属性测试：上下文窗口截断
    - **Property 10: Context window truncation**
    - **Validates: Requirements 3.9**

  - [ ]* 6.5 编写属性测试：Token 累加正确性
    - **Property 11: Token accumulation correctness**
    - **Validates: Requirements 3.10**

  - [ ]* 6.6 编写属性测试：输出排序不变性
    - **Property 12: Output ordering invariant**
    - **Validates: Requirements 3.13**

- [x] 7. Checkpoint - 确保调度器测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. 集成到现有翻译入口
  - [x] 8.1 集成 ACGlossaryMatcher 到 Translator 类
    - 修改 `core/translator.py` 的 `Translator.__init__`，接受可选 `glossary_matcher` 参数
    - 修改 `_find_relevant_glossary_terms` 方法，优先使用 AC 自动机
    - _Requirements: 2.9, 2.11_

  - [x] 8.2 集成 ConcurrentDispatcher 到 translate_md.py
    - 修改 `translate_md_file` 函数签名，添加 `rate_limit`、`cooldown`、`max_split_depth`、`fuzzy_matching` 参数
    - 替换现有翻译循环为 `ConcurrentDispatcher.dispatch_all` 调用
    - 在翻译开始前构建 `ACGlossaryMatcher` 并传入 `Translator`
    - 保持函数返回值格式不变
    - _Requirements: 3.11, 4.2_

  - [x] 8.3 集成 ConcurrentDispatcher 到 translate_docx.py
    - 修改 `translate_docx_file` 函数签名，添加相同的新参数
    - 替换现有翻译循环为 `ConcurrentDispatcher.dispatch_all` 调用
    - 在翻译开始前构建 `ACGlossaryMatcher` 并传入 `Translator`
    - 保持函数返回值格式不变
    - _Requirements: 3.11, 4.2_

  - [x] 8.4 添加 Web UI 配置控件
    - 在 `app.py` 的"高级任务控制"expander 中添加并发级别和速率限制滑块
    - 将新参数传递给 `translate_md_file` 和 `translate_docx_file` 调用
    - _Requirements: 4.3_

  - [x] 8.5 添加配置日志输出
    - 在 `translate_md_file` 和 `translate_docx_file` 翻译开始时打印所有配置值
    - 更新 `config.example.json` 添加新配置字段文档
    - _Requirements: 4.4_

- [x] 9. Final checkpoint - 确保所有测试通过
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- AC 自动机在 pyahocorasick 未安装时自动回退到旧正则逻辑，确保向后兼容
- 并发调度器使用 ThreadPoolExecutor 而非 asyncio，与现有代码风格一致

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "4.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "4.2", "4.3", "4.4"] },
    { "id": 3, "tasks": ["2.4", "2.5", "2.6"] },
    { "id": 4, "tasks": ["2.7", "2.8", "2.9", "2.10"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["6.2"] },
    { "id": 7, "tasks": ["6.3", "6.4", "6.5", "6.6"] },
    { "id": 8, "tasks": ["8.1"] },
    { "id": 9, "tasks": ["8.2", "8.3"] },
    { "id": 10, "tasks": ["8.4", "8.5"] }
  ]
}
```
