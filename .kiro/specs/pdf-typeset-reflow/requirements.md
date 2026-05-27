# Requirements Document

## Introduction

本功能为 TRPG PDF 翻译工具新增"纯重绘"（typeset reflow）输出管线。与现有的 `_replica`（底图+遮罩+铺字）管线不同，纯重绘管线从 PDF 中提取所有视觉元素，用 HTML/CSS 从零重建每一页，使中文译文在 CSS 排版中自然流动，最终通过 Playwright 导出专业品质的中文排版 PDF。

现有 `_replica` 管线保留为"快速预览/检查稿"，新的 `_typeset` 管线作为"最终成品"。两者共享布局提取、翻译和进度文件。

## Glossary

- **Typeset_Pipeline**: 纯重绘管线，从 PDF 提取结构后用 HTML/CSS 重建页面并导出 PDF 的完整处理流程
- **Replica_Pipeline**: 现有的底图+遮罩+铺字管线，保留为快速预览用途
- **Page_Structure_Extractor**: 增强版页面结构提取器，负责从 PDF 提取背景、图片、装饰元素和文本区域
- **Semantic_Analyzer**: 文本区域语义化分析器，识别每个文本区域的角色（正文栏、标题、页眉等）
- **HTML_Rebuilder**: HTML/CSS 页面重建器，将提取的结构和翻译后的文本组装为完整 HTML 页面
- **PDF_Exporter**: PDF 导出器，使用 Playwright 将 HTML 渲染为最终 PDF
- **Page_Structure_JSON**: 页面结构中间文件（`page_structure.json`），存储背景层、图片层、文本区域层
- **Page_Content_JSON**: 页面内容中间文件（`page_content.json`），存储语义化的文本结构
- **Page_Type**: 页面类型分类结果，包括 cover（封面）、art（整页插图）、columns（双栏正文）、single（单栏正文）、mixed（混合）
- **Gutter**: 双栏页面中左右栏之间的间距区域
- **PyMuPDF**: Python PDF 处理库，用于从 PDF 提取文本、图片和矢量元素
- **Playwright**: 浏览器自动化工具，用于将 HTML 渲染为 PDF
- **Translator**: 现有的翻译模块，负责调用 AI 翻译服务

## Requirements

### Requirement 1: 页面结构提取

**User Story:** As a translator, I want to extract all visual elements from a PDF page, so that I can rebuild the page from scratch with proper layering.

#### Acceptance Criteria

1. WHEN a PDF file is provided, THE Page_Structure_Extractor SHALL extract the page background color for each page
2. WHEN a PDF page contains independent images, THE Page_Structure_Extractor SHALL extract each image with its bounding box coordinates and pixel data
3. WHEN a PDF page contains vector decorative elements, THE Page_Structure_Extractor SHALL extract lines and boxes with their coordinates, stroke color, and thickness
4. WHEN a PDF page contains text regions, THE Page_Structure_Extractor SHALL extract the bounding box of each text region
5. THE Page_Structure_Extractor SHALL output a valid Page_Structure_JSON file containing background layer, image layer, and text region layer for each page
6. THE Page_Structure_Extractor SHALL preserve the original page dimensions (width and height in PDF points) in the output

### Requirement 2: 文本区域语义化

**User Story:** As a translator, I want each text region to be classified by its semantic role, so that the HTML rebuild can apply appropriate layout styles.

#### Acceptance Criteria

1. WHEN a text region is analyzed, THE Semantic_Analyzer SHALL classify it as one of: body_column, title, header, footer, footnote, table, or list
2. WHEN a text region contains text content, THE Semantic_Analyzer SHALL extract the text with its basic styles including font size, bold, italic, and color
3. WHEN a page contains two body columns, THE Semantic_Analyzer SHALL identify the left and right columns separately with their respective text blocks
4. THE Semantic_Analyzer SHALL output a valid Page_Content_JSON file containing the semantic structure for each page
5. WHEN a text region is classified as header or footer, THE Semantic_Analyzer SHALL mark it as non-translatable

### Requirement 3: 页面类型分类

**User Story:** As a translator, I want each page to be classified by its layout type, so that the HTML rebuild can apply the correct page template.

#### Acceptance Criteria

1. WHEN a page has minimal text and large images, THE Semantic_Analyzer SHALL classify the page as Page_Type art
2. WHEN a page has centered large-font text with few blocks, THE Semantic_Analyzer SHALL classify the page as Page_Type cover
3. WHEN a page has text blocks distributed in two vertical columns, THE Semantic_Analyzer SHALL classify the page as Page_Type columns
4. WHEN a page has text blocks spanning the full page width, THE Semantic_Analyzer SHALL classify the page as Page_Type single
5. WHEN a page has both full-width blocks and column blocks, THE Semantic_Analyzer SHALL classify the page as Page_Type mixed

### Requirement 4: 翻译集成

**User Story:** As a translator, I want the typeset pipeline to reuse existing translation capabilities, so that glossary, cache, and checkpoint features are preserved.

#### Acceptance Criteria

1. THE Typeset_Pipeline SHALL use the existing Translator module for text translation
2. THE Typeset_Pipeline SHALL apply the existing glossary file during translation
3. WHEN a translation has been cached in a previous run, THE Typeset_Pipeline SHALL reuse the cached translation without calling the API
4. WHEN a translation fails, THE Typeset_Pipeline SHALL record the failure and allow retry on subsequent runs
5. THE Typeset_Pipeline SHALL translate text by semantic region, preserving structure markers between regions
6. IF the translation process is interrupted, THEN THE Typeset_Pipeline SHALL resume from the last completed region on the next run

### Requirement 5: HTML/CSS 页面重建

**User Story:** As a translator, I want each page rebuilt as HTML/CSS from scratch, so that Chinese text flows naturally without overflow issues.

#### Acceptance Criteria

1. THE HTML_Rebuilder SHALL generate one HTML section per PDF page with dimensions matching the original page
2. WHEN a page has a background color, THE HTML_Rebuilder SHALL render the background color as the base layer
3. WHEN a page has independent images, THE HTML_Rebuilder SHALL place each image at its original coordinates as an image layer
4. WHEN a page is classified as Page_Type columns, THE HTML_Rebuilder SHALL render the translated text in a dual-column CSS layout
5. WHEN a page is classified as Page_Type single, THE HTML_Rebuilder SHALL render the translated text in a single-column CSS layout
6. THE HTML_Rebuilder SHALL use a configurable Chinese font family, defaulting to "Noto Serif SC"
7. THE HTML_Rebuilder SHALL set font sizes appropriate for Chinese readability, with body text no smaller than 10pt
8. THE HTML_Rebuilder SHALL allow Chinese text to wrap naturally within its container without overflow

### Requirement 6: 双栏正文排版

**User Story:** As a translator, I want dual-column body text to flow naturally in the Chinese layout, so that the output approaches manually typeset quality.

#### Acceptance Criteria

1. WHEN a columns page is rebuilt, THE HTML_Rebuilder SHALL create two separate column containers with a Gutter between them
2. THE HTML_Rebuilder SHALL set paragraph text-indent to 2em for body paragraphs in column layout
3. WHEN a text block has a font size significantly larger than body text, THE HTML_Rebuilder SHALL render it as a heading element
4. THE HTML_Rebuilder SHALL set line-height to at least 1.5 for Chinese body text in columns
5. WHEN translated text exceeds the column height, THE HTML_Rebuilder SHALL allow the text to flow naturally rather than truncating

### Requirement 7: PDF 导出

**User Story:** As a translator, I want the rebuilt HTML to be exported as a professional PDF, so that I get a final deliverable file.

#### Acceptance Criteria

1. WHEN the HTML rebuild is complete, THE PDF_Exporter SHALL render the HTML using Playwright headless browser
2. THE PDF_Exporter SHALL produce a PDF with page dimensions matching the original PDF
3. THE PDF_Exporter SHALL embed all fonts used in the HTML into the output PDF
4. THE PDF_Exporter SHALL output the file with a `_typeset.pdf` suffix to distinguish from the replica pipeline output
5. IF Playwright fails to render a page, THEN THE PDF_Exporter SHALL report the error with the page number and continue with remaining pages

### Requirement 8: 管线隔离与共享

**User Story:** As a developer, I want the typeset pipeline to coexist with the replica pipeline without interference, so that both outputs remain available.

#### Acceptance Criteria

1. THE Typeset_Pipeline SHALL output files with `_typeset` suffix, separate from `_replica` suffix files
2. THE Typeset_Pipeline SHALL not modify or delete any files produced by the Replica_Pipeline
3. THE Typeset_Pipeline SHALL reuse the existing layout extraction results when available
4. THE Typeset_Pipeline SHALL reuse existing translation progress files when the source text matches
5. WHEN both pipelines are available, THE Typeset_Pipeline SHALL be selectable as a separate output format in the Web interface

### Requirement 9: 图片与装饰元素保留

**User Story:** As a translator, I want images and decorative elements preserved at their correct positions, so that the typeset output retains the visual identity of the original PDF.

#### Acceptance Criteria

1. WHEN a page contains independent images, THE HTML_Rebuilder SHALL render each image at its original bounding box coordinates
2. WHEN a page contains decorative lines, THE HTML_Rebuilder SHALL render them as CSS borders or SVG elements at their original positions
3. THE HTML_Rebuilder SHALL preserve the z-order of visual elements: background layer, then image layer, then text layer on top
4. WHEN an image overlaps with a text region, THE HTML_Rebuilder SHALL place the text layer above the image layer

### Requirement 10: 中文字体配置

**User Story:** As a translator, I want to configure the Chinese font used in the typeset output, so that I can match the visual style of different TRPG products.

#### Acceptance Criteria

1. THE Typeset_Pipeline SHALL accept a font family configuration parameter
2. WHEN no font is configured, THE Typeset_Pipeline SHALL default to "Noto Serif SC" as the primary font
3. THE Typeset_Pipeline SHALL include "Source Han Serif CN" as a fallback font
4. WHEN the configured font is not available on the system, THE Typeset_Pipeline SHALL fall back to the next available font in the font stack and log a warning

### Requirement 11: 页面结构 JSON 序列化

**User Story:** As a developer, I want the page structure and content to be serialized as JSON, so that each pipeline phase can run independently and intermediate results can be inspected.

#### Acceptance Criteria

1. THE Page_Structure_Extractor SHALL serialize Page_Structure_JSON using UTF-8 encoding with human-readable indentation
2. THE Semantic_Analyzer SHALL serialize Page_Content_JSON using UTF-8 encoding with human-readable indentation
3. WHEN Page_Structure_JSON is loaded, THE Typeset_Pipeline SHALL validate the schema version and report errors for incompatible versions
4. WHEN Page_Content_JSON is loaded, THE Typeset_Pipeline SHALL validate the schema version and report errors for incompatible versions
5. FOR ALL valid Page_Structure_JSON files, serializing then deserializing SHALL produce an equivalent data structure (round-trip property)
6. FOR ALL valid Page_Content_JSON files, serializing then deserializing SHALL produce an equivalent data structure (round-trip property)
