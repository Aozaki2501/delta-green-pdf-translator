# 当前进度

- 目标：拉取仓库，整理根目录杂乱文件，保留一键启动入口。
- 已完成：执行 `git pull --ff-only`，当前分支已经是最新。
- 关键决定：不切换分支，不改业务逻辑；只整理文档、临时测试和缓存这类不影响运行的文件。
- 已完成：文档移到 `docs/`，开发计划移到 `docs/plans/`，临时试验脚本移到 `scratch/`，缓存已清理。
- 已完成：新增 `start.bat`；`start_web.ps1` 会补装 Playwright Chromium，保证一键启动包含 PDF 导出依赖。
- 已完成：修复测试里的模块缓存污染问题；全量测试 357 个通过。
- 当前状态：根目录已收敛，双击 `start.bat` 或 `start_web.bat` 都能一键启动。

# 合入远端 main

- 目标：把 `origin/main` 的新提交合入当前功能分支。
- 已确认：当前分支是 `feature/pdf-typeset-reflow`，`origin/main` 比当前分支多 3 个提交。
- 关键决定：先临时保存本地未提交改动，再快进到 `origin/main`，最后恢复本地整理改动并检查冲突。
- 已完成：当前分支已快进到 `origin/main` 的 `935c998`。
- 已处理：恢复本地改动时 `tests/test_imports.py` 有冲突，已保留远端新增测试和本地缓存恢复修复。
- 已验证：全量测试 367 个通过。
- 当前状态：当前分支比 `origin/feature/pdf-typeset-reflow` 多 3 个远端 main 提交；本地整理改动仍未提交。

# Kali Ghati 重绘 PDF 排查

- 目标：逐步定位 `output/Delta_Green_-_Kali_Ghati..._cn` 里重绘 PDF 效果差的原因。
- 已定位：最终文件是 `_upload_Delta_Green_-_Kali_Ghati..._typeset.pdf`，同时有 `page_structure.json`、`page_content.json`、`page_content_translated.json` 和 `_typeset_report.json`。
- 当前计划：先读报告和结构统计，再抽样查看页面类型、图片和文本块，最后再决定修复点。
- 已确认：坏图主因是跨页图片对象被整张压进单页；PDF 的 `transform` 被丢掉，只用了可见 `bbox`。
- 已修复：未旋转图片会按 `transform` 精确裁到页面可见区域后再保存，避免跨页底图串页。
- 已修复：旋转/倾斜图片会用原 PDF transform 生成 CSS matrix，不再当普通矩形硬塞。
- 已修复：图片 mask 会合成 alpha；装饰层改到图片层下方，避免黑色装饰块盖住纸张。
- 已修复：typeset 翻译改为单块请求，避免第 11/13 页这类大页因为漏 `[BLOCK]` 标记整页失败。
- 已验证：全量测试 369 个通过；调试 PDF 在 `output/_kali_typeset_layer_debug/`。

# Typeset 文字排版方向

- 当前判断：图片问题基本可控，文字排版乱的主因是只按矩形文本块重排，丢失了双栏顺序、旋转角、逐行位置和异形区域。
- 关键决定：要做接近原版的重绘，必须把文字层升级为“行/span 坐标层”，不能继续只靠普通段落重排。
- 可实现范围：双栏可以稳定实现；倾斜文字可以实现；异形排版可以按原始行位置实现，复杂文字绕图需要后续单独建模。

# 参考版式与行级重建

- 目标：参考 `绿色三角洲-来自遗忘.pdf`，让 typeset 输出具备正常标题、小标题、正文行距、双栏和倾斜文字表现。
- 已完成：默认样式改为参考书的正文约 10.9pt、行距 1.6、栏距 30pt、小标题红色 `#ed1c24`。
- 已完成：`page_structure.json` 的文本区域现在保存每一行的 bbox、文字、字号、颜色、粗斜体和角度。
- 已完成：中文重绘时优先按原始左右栏分别建立流动文本框；大标题和倾斜区域保留原位。
- 已验证：重新生成调试 PDF `output/_kali_line_region_debug/kali_line_region_debug.pdf`；全量测试 372 个通过。
- 已完成：从第 3 点推进到第 6 点，正文可按源 PDF 行轨道灌排，图片旁变窄的行会自然绕开图片。
- 已完成：结构层新增 span 级 bbox 与样式；固定非翻译文本可按 span 坐标和粗斜体颜色绘制。
- 已完成：语义分析新增红色/短粗小标题识别，角色为 `subtitle`。
- 已完成：新增页面模板选择器，当前支持 `line_track_columns`、`source_columns`、`single_source_flow`、`fixed_art`。
- 已验证：重新生成调试 PDF `output/_kali_line_track_debug/kali_line_track_debug.pdf`；全量测试 376 个通过。

# Typeset 翻译并发

- 已确认：Kali Ghati 第 1-20 页有 460 个可翻译块，来自 PDF 原始文本区域，不是行/span 被误当成翻译块。
- 已确认：此前 typeset 翻译为了稳定改成单块串行，因此并发没有生效。
- 已修复：typeset 翻译现在保留单块请求，但用 `ThreadPoolExecutor` 并发执行，默认并发数为 `TypesetConfig.translation_concurrency = 4`。
- 已修复：进度条按实际完成数量推进，进度文件写入加锁，避免并发保存互相覆盖。
- 已验证：新增并发测试；全量测试 377 个通过。
