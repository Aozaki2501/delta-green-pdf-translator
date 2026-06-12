# 当前计划

- 目标：修复普通 Word/HTML 输出里的目录排版，重点处理 Patrol PDF 第 5-7 页。
- 已确认：Patrol 原 PDF 的目录标题是 `Index`，目录项是“标题行 + 下一行页码”，旧规则未识别成 `toc`。
- 已完成：`Index` 和“标题/页码分行”的目录结构会识别为 `toc`，并合并成标准点线目录行。
- 已完成：TOC 清理时不再合并换行；HTML/Word 目录按“标题 / 点线 / 页码”结构化输出，Word 强制双栏。
- 已处理：已用新版逻辑重排 `output/486357395-Patrol-Vietnam-War-Roleplay-pdf_cn` 的 HTML/Word/Markdown，不调用翻译 API。
- 已验证：Patrol HTML 生成 407 条目录行；Word 有双栏和点线制表位；全量测试 486 个通过。
- 关键决定：目录页不依赖模型翻译，导出层固定处理结构；旧坏 progress 已备份为 `*.progress.before_toc_fix.json`。

# Millennium 目录复查

- 目标：修复 Millennium 目录 HTML 看起来单栏、目录项残留旧点线、部分目录页未中文化的问题。
- 已确认：HTML 已识别为 `toc`，但 `.toc-card` 禁止栏内拆分，导致长目录块只能占一栏。
- 已完成：HTML 目录卡片允许跨栏拆分，单条目录行仍避免拆开；目录标题会清理旧点线。
- 已完成：翻译提示已改为目录项标题要翻译成中文，但保留 `[[TOC]]`、```toc、点线结构和页码。
- 已处理：已重排 Millennium HTML；原 Word 文件被占用，已另存新版到 `millennium_text_2026-05-11_cn_tocfix/`。
- 已验证：Millennium HTML 有 6 个目录 section、326 条目录行；旧点线残留已清理；全量测试 487 个通过。
