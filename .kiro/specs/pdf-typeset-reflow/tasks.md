# Implementation Plan: PDF Typeset Reflow（纯重绘管线）

## Overview

将 PDF 纯重绘管线的设计分解为可增量执行的编码任务。管线分为五个阶段（A-E），每个阶段独立运行，通过 JSON 中间文件传递数据。实现顺序为：数据模型 → 结构提取 → 语义分析 → 翻译集成 → HTML 重建 → PDF 导出 → 管线编排 → Web UI 集成。

## Tasks

- [x] 1. 建立项目结构与核心数据模型
  - [x] 1.1 创建数据模型文件 `core/typeset_models.py`
    - 定义 `BackgroundLayer`、`ImageElement`、`DecorationElement`、`TextRegionBBox`、`PageStructure`、`PageStructureDocument` 数据类
    - 定义 `SemanticRole` 枚举、`PageType` 枚举、`StyledTextRun`、`ContentBlock`、`ColumnInfo`、`PageContent`、`PageContentDocument` 数据类
    - 定义 `TypesetConfig` 配置数据类（字体、行距、缩进等默认值）
    - 定义 `TypesetResult` 结果数据类
    - 实现 `PageStructureDocument.to_json()` 和 `PageStructureDocument.from_json()` 序列化方法
    - 实现 `PageContentDocument.to_json()` 和 `PageContentDocument.from_json()` 序列化方法
    - 确保 JSON 输出为 UTF-8 编码、带缩进的人类可读格式
    - 实现 schema 版本号常量 `PAGE_STRUCTURE_SCHEMA_VERSION = 1` 和 `PAGE_CONTENT_SCHEMA_VERSION = 1`
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 10.1, 10.2, 10.3_

  - [x]* 1.2 编写属性测试：Page_Structure_JSON 序列化往返
    - **Property 1: Page_Structure_JSON 序列化往返**
    - 使用 hypothesis 生成随机 `PageStructureDocument` 实例，验证 `to_json()` → `from_json()` 往返一致性
    - **Validates: Requirements 11.5, 1.5, 1.6**

  - [x]* 1.3 编写属性测试：Page_Content_JSON 序列化往返
    - **Property 2: Page_Content_JSON 序列化往返**
    - 使用 hypothesis 生成随机 `PageContentDocument` 实例，验证 `to_json()` → `from_json()` 往返一致性
    - **Validates: Requirements 11.6, 2.4**

  - [x]* 1.4 编写单元测试：TypesetConfig 默认值与字体配置
    - 测试默认字体为 "Noto Serif SC"
    - 测试 fallback 字体包含 "Source Han Serif CN"
    - 测试 schema 版本校验逻辑（不兼容版本报错）
    - 测试 JSON 输出为 UTF-8 编码且带缩进
    - _Requirements: 10.1, 10.2, 10.3, 11.1, 11.2, 11.3, 11.4_

- [x] 2. 实现阶段 A：页面结构提取
  - [x] 2.1 创建 `core/page_structure.py` 实现 `PageStructureExtractor`
    - 实现 `__init__(self, pdf_path, output_dir)` 初始化方法
    - 实现 `extract(start_page, end_page)` 批量提取方法
    - 实现 `extract_page(page_index)` 单页提取方法
    - 实现 `extract_background(page)` 提取页面背景色
    - 实现 `extract_images(page, page_index)` 提取独立图片并保存到 `assets/typeset_images/`
    - 实现 `extract_decorations(page)` 提取矢量装饰元素（线条、框）
    - 实现 `extract_text_regions(page)` 提取文本区域边界框
    - 使用 PyMuPDF 读取 PDF，复用现有 `layout_extractor.py` 的页面遍历逻辑
    - 保留原始页面尺寸（宽高，PDF 点）
    - 输出 `page_structure.json` 文件
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x]* 2.2 编写单元测试：页面结构提取
    - 测试背景色提取（有色/白色页面）
    - 测试图片提取（含 bbox 坐标和像素数据保存）
    - 测试装饰元素提取（线条、矩形）
    - 测试文本区域 bbox 提取
    - 测试页面尺寸保留
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6_

- [x] 3. 实现阶段 B：文本区域语义化
  - [x] 3.1 创建 `core/semantic_analyzer.py` 实现 `SemanticAnalyzer`
    - 实现 `analyze_document(structure)` 分析整个文档
    - 实现 `analyze_page(page_structure)` 分析单页
    - 实现 `classify_region(region, page_context)` 将文本区域分类为语义角色
    - 实现 `classify_page_type(page_structure)` 分类页面类型，复用现有 `page_classifier.py` 逻辑
    - 实现 `extract_styled_text(region)` 提取带样式文本（字号、粗体、斜体、颜色）
    - 实现双栏识别逻辑：识别左右栏并分别记录
    - 标记 header/footer 区域为 `translatable = False`
    - 输出 `page_content.json` 文件
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x]* 3.2 编写属性测试：页面类型分类正确性
    - **Property 3: 页面类型分类正确性**
    - 使用 hypothesis 生成具有特定布局特征的页面，验证分类结果正确
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

  - [x]* 3.3 编写属性测试：语义角色分类有效性
    - **Property 4: 语义角色分类有效性**
    - 验证任何文本区域的分类结果都是有效的 SemanticRole 枚举值
    - **Validates: Requirements 2.1**

  - [x]* 3.4 编写属性测试：页眉页脚不可翻译标记
    - **Property 5: 页眉页脚不可翻译标记**
    - 验证 HEADER/FOOTER 角色的 ContentBlock 的 `translatable` 字段为 False
    - **Validates: Requirements 2.5**

  - [x]* 3.5 编写属性测试：样式提取完整性
    - **Property 12: 样式提取完整性**
    - 验证任何含文本的区域输出至少一个 StyledTextRun，且 font_size > 0、color 为有效 CSS 颜色、bold/italic 为布尔值
    - **Validates: Requirements 2.2**

  - [x]* 3.6 编写属性测试：双栏分离正确性
    - **Property 13: 双栏分离正确性**
    - 验证双栏页面产生恰好两个 ColumnInfo，左栏 x 坐标 < 右栏 x 坐标，每个 body_column 块恰好属于一个栏
    - **Validates: Requirements 2.3**

- [x] 4. Checkpoint - 确保数据模型和提取阶段测试通过
  - 确保所有测试通过，ask the user if questions arise.

- [x] 5. 实现阶段 C：翻译集成
  - [x] 5.1 创建 `core/typeset_translation.py` 实现翻译集成逻辑
    - 实现 `translate_typeset_content(content, translator, progress, glossary, progress_callback)` 函数
    - 按语义区域组织翻译请求，使用 `[BLOCK id]` 标记保持区域对应
    - 跳过 `translatable = False` 的区域（header/footer）
    - 复用现有 `Translator.translate_chunk()` 接口
    - 应用术语表（复用 `core/glossary.py`）
    - 实现翻译缓存命中逻辑（基于源文本 hash）
    - 实现翻译失败记录与重试机制
    - 实现断点续跑：从进度文件恢复，跳过已完成区域
    - 输出 `page_content_translated.json`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x]* 5.2 编写属性测试：翻译标记保持
    - **Property 14: 翻译标记保持**
    - 验证带 [BLOCK id] 标记的翻译结果包含与输入完全相同的块 ID 集合
    - **Validates: Requirements 4.5**

  - [x]* 5.3 编写单元测试：翻译集成
    - 测试翻译缓存命中（已缓存的文本不调用 API）
    - 测试翻译失败记录（失败区域写入进度文件）
    - 测试断点续跑（中断后从上次位置恢复）
    - 测试 header/footer 区域被跳过
    - _Requirements: 4.3, 4.4, 4.6, 2.5_

- [x] 6. 实现阶段 D：HTML/CSS 页面重建
  - [x] 6.1 创建 `exporters/typeset_html.py` 实现 `TypesetHTMLRebuilder`
    - 实现 `__init__(self, config)` 接受 TypesetConfig 配置
    - 实现 `rebuild_document(structure, content)` 重建整个文档为 HTML
    - 实现 `rebuild_page(page_structure, page_content)` 重建单页为 HTML section
    - 实现 `render_background_layer(background)` 渲染背景层
    - 实现 `render_image_layer(images)` 按原坐标放置图片
    - 实现 `render_decoration_layer(decorations)` 渲染装饰元素（CSS borders 或 SVG）
    - 实现 `render_text_layer(page_content)` 按页面类型渲染文本层
    - 实现 `render_column_layout(left_col, right_col)` 双栏 CSS 布局
    - 实现 `render_single_layout(blocks)` 单栏 CSS 布局
    - 页面 section 尺寸匹配原始 PDF 页面尺寸（PDF 点 → CSS 像素，96/72 比率）
    - 使用可配置中文字体，默认 "Noto Serif SC"
    - 正文字号不小于 10pt
    - 中文正文行距 ≥ 1.5
    - 段落首行缩进 2em
    - 文本自然换行，不截断
    - 字号 ≥ 1.5× 正文字号的文本块渲染为标题元素
    - 视觉层级 z-order：背景 < 图片 < 装饰 < 文本
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 6.1, 6.2, 6.3, 6.4, 6.5, 9.1, 9.2, 9.3, 9.4_

  - [x]* 6.2 编写属性测试：HTML 页面尺寸保持
    - **Property 6: HTML 页面尺寸保持**
    - 验证生成的 HTML section 尺寸匹配原始页面尺寸（96/72 转换）
    - **Validates: Requirements 5.1**

  - [x]* 6.3 编写属性测试：HTML 布局与页面类型匹配
    - **Property 7: HTML 布局与页面类型匹配**
    - 验证 COLUMNS 页面生成双栏结构，SINGLE 页面生成单栏结构
    - **Validates: Requirements 5.4, 5.5, 6.1**

  - [x]* 6.4 编写属性测试：图片坐标保持
    - **Property 8: 图片坐标保持**
    - 验证图片元素在 HTML 中的 CSS 坐标对应原始 PDF bbox（96/72 转换）
    - **Validates: Requirements 5.3, 9.1**

  - [x]* 6.5 编写属性测试：视觉层级 z-order 不变量
    - **Property 9: 视觉层级 z-order 不变量**
    - 验证 z-index 满足：背景 < 图片 < 装饰 < 文本
    - **Validates: Requirements 9.3, 9.4**

  - [x]* 6.6 编写属性测试：正文字号下限
    - **Property 10: 正文字号下限**
    - 验证正文文本 font-size ≥ 10pt（13.333px）
    - **Validates: Requirements 5.7**

  - [x]* 6.7 编写属性测试：标题检测一致性
    - **Property 11: 标题检测一致性**
    - 验证字号 ≥ 1.5× 正文字号的文本块渲染为 heading 元素
    - **Validates: Requirements 6.3**

  - [x]* 6.8 编写属性测试：背景色渲染
    - **Property 15: 背景色渲染**
    - 验证非空背景色页面的 HTML 包含对应的 CSS background-color
    - **Validates: Requirements 5.2**

  - [x]* 6.9 编写属性测试：装饰元素坐标保持
    - **Property 16: 装饰元素坐标保持**
    - 验证装饰元素在 HTML 中的位置匹配原始 bbox
    - **Validates: Requirements 9.2**

  - [x]* 6.10 编写单元测试：HTML 重建
    - 测试 CSS 行距 ≥ 1.5
    - 测试段落首行缩进 2em
    - 测试文本溢出时自然换行不截断
    - 测试字体配置应用
    - _Requirements: 6.2, 6.4, 6.5, 5.8_

- [x] 7. Checkpoint - 确保 HTML 重建阶段测试通过
  - 确保所有测试通过，ask the user if questions arise.

- [x] 8. 实现阶段 E：PDF 导出
  - [x] 8.1 创建 `exporters/typeset_pdf.py` 实现 `TypesetPDFExporter`
    - 实现 `export(html_path, pdf_output, page_width_pt, page_height_pt)` 方法
    - 实现 `export_with_fallback(html_path, pdf_output, page_width_pt, page_height_pt)` 单页失败跳过方法
    - 使用 Playwright headless browser 渲染 HTML
    - PDF 页面尺寸匹配原始 PDF
    - 嵌入所有使用的字体
    - 输出文件使用 `_typeset.pdf` 后缀
    - 单页渲染失败时报告页码并继续
    - 复用现有 `exporters/pdf_playwright.py` 的 Playwright 调用逻辑
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x]* 8.2 编写单元测试：PDF 导出
    - 测试输出文件后缀为 `_typeset.pdf`
    - 测试单页渲染失败时继续处理其余页面
    - 测试 Playwright 未安装时抛出 RuntimeError 并提示安装命令
    - _Requirements: 7.4, 7.5_

- [x] 9. 实现管线编排与集成
  - [x] 9.1 创建 `core/typeset_pipeline.py` 实现 `TypesetPipeline`
    - 实现 `__init__(self, pdf_path, output_dir, translator, glossary, config)` 初始化
    - 实现 `run(start_page, end_page, progress_callback)` 执行完整管线
    - 实现 `run_phase_a()` → `run_phase_b()` → `run_phase_c()` → `run_phase_d()` → `run_phase_e()` 各阶段方法
    - 实现断点续跑：检查中间文件是否存在且版本匹配，跳过已完成阶段
    - 实现进度文件读写（`_typeset.progress.json`）
    - 确保 typeset 管线不修改或删除 replica 管线的文件
    - 复用现有布局提取结果（`layout.json`）
    - 复用现有翻译进度文件（源文本匹配时）
    - 生成 `_typeset_report.json` 错误报告
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 4.6_

  - [x]* 9.2 编写单元测试：管线编排
    - 测试文件命名使用 `_typeset` 后缀
    - 测试管线不修改 replica 文件
    - 测试复用现有 layout.json
    - 测试复用现有翻译进度
    - 测试断点续跑（中间文件存在时跳过阶段）
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 10. Web UI 集成
  - [x] 10.1 在 Web 界面添加 typeset 输出格式选项
    - 修改 `app.py` 添加 typeset 管线的路由/选项
    - 在输出格式选择中添加 "纯重绘 PDF（_typeset）" 选项
    - 添加字体配置参数输入（可选，默认 "Noto Serif SC"）
    - 调用 `TypesetPipeline.run()` 执行管线
    - 字体不可用时回退并记录警告
    - _Requirements: 8.5, 10.1, 10.2, 10.3, 10.4_

  - [x]* 10.2 编写单元测试：字体回退逻辑
    - 测试配置字体不可用时回退到下一个字体并记录警告
    - _Requirements: 10.4_

- [x] 11. Final checkpoint - 确保所有测试通过
  - 确保所有测试通过，ask the user if questions arise.

## Notes

- 标记 `*` 的子任务为可选测试任务，可跳过以加速 MVP 开发
- 每个任务引用具体需求编号以确保可追溯性
- 属性测试验证设计文档中定义的 16 个正确性属性
- 单元测试验证具体示例和边界条件
- Checkpoint 确保增量验证
- 项目使用 Python，测试框架为 pytest + hypothesis
- 需新增安装 `hypothesis>=6.100.0` 依赖

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4"] },
    { "id": 2, "tasks": ["2.1"] },
    { "id": 3, "tasks": ["2.2", "3.1"] },
    { "id": 4, "tasks": ["3.2", "3.3", "3.4", "3.5", "3.6"] },
    { "id": 5, "tasks": ["5.1"] },
    { "id": 6, "tasks": ["5.2", "5.3", "6.1"] },
    { "id": 7, "tasks": ["6.2", "6.3", "6.4", "6.5", "6.6", "6.7", "6.8", "6.9", "6.10"] },
    { "id": 8, "tasks": ["8.1"] },
    { "id": 9, "tasks": ["8.2", "9.1"] },
    { "id": 10, "tasks": ["9.2", "10.1"] },
    { "id": 11, "tasks": ["10.2"] }
  ]
}
```
