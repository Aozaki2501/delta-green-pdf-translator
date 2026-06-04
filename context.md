# 当前进度

- 目标：处理深色背景上的标题译文仍显示黑字的问题。
- 已确认：源 PDF 已提取到该标题原始颜色为 `#ffffff`，不是识别不到，而是渲染阶段把标题强制套成主题黑/红色。
- 已修复：固定定位标题/小标题如果源文字是浅色，会保留源浅色；普通标题仍沿用主题色。
- 已验证：Presence 对比 PDF 第 10 页黑底标题已变为白字；全量测试 439 个通过。

- 目标：检查最新 Presence 纯重绘 PDF/HTML，和原 PDF、甜心汉化参考进行版面对比。
- 已确认：本次任务页码范围是 `9-15`，所以 `_typeset.pdf` 只有 7 页是正常范围输出，不是整本丢页。
- 已定位：怪换行和行距挤压主要来自 `line_track_columns` 把中文硬塞进英文原始行轨道；这不是 Gemini hints 能单独修好的问题。
- 已修复：普通中文双栏正文默认改用自然栏内重排；只有前景图片切入正文栏时才保留原行轨道，避免文字压到图片。
- 已生成：对比文件 `output/Delta_Green_Presence_PDF_1_cn/_upload_Delta_Green_Presence_PDF_1_5190a2a4_typeset_after.pdf` 和 `.html`。
- 已验证：新对比版换行和行距明显改善，图片页没有明显文字覆盖；全量测试 438 个通过。
- 关键决定：Gemini hints 适合修正阅读顺序、栏目、跳过块和语义分类；不适合直接解决中文行距、自然换行和段落排版。

- 目标：评估并补充 Codex skills，重点增强前端审美和界面验收。
- 已完成：查看官方可安装 skills 列表；当前已具备 Figma、Playwright、截图、PDF、安全、Netlify/Vercel 等核心能力。
- 已完成：新增本地 skill `frontend-aesthetic-review`，用于前端视觉质量、响应式布局、截图验收和交互细节审查。
- 已验证：`frontend-aesthetic-review` 通过 skill 校验。
- 关键决定：不照营销图全量安装；暂不安装 Notion、Linear、Render、Cloudflare、Sentry、语音类和重复 GitHub 工作流 skills。

- 目标：拉取仓库最新更新，并打开本地 Web 项目。
- 已完成：`main` 已快进到 `origin/main` 的最新提交 `7daf6d5`。
- 已完成：按最新依赖重新启动 Streamlit Web，地址为 `http://localhost:8501`。
- 已验证：本地页面 HTTP 200，浏览器标题为“三角洲翻译终端”。
- 关键决定：不合并其他分支，不改业务代码，只执行拉取、启动和记录。

- 目标：更新到最新仓库，查看纯重绘 PDF 功能，并补充 README 使用说明。
- 已完成：执行 `git pull --ff-only`，当前 `main` 已快进到远端最新提交 `be361f9`。
- 已确认：纯重绘 PDF 已在 Web 输出格式中开放；可手动填写 `layout_hints.json`，也可勾选 Gemini 自动生成 hints。
- 已调整：README 新增“纯重绘 PDF”说明，明确单独运行、输出 `_typeset.pdf`、hints 用途和错误处理方式。
- 已修复：远端最新代码里 `exporters/html.py` 有一处 f-string 语法错误，会导致项目无法导入；已改成先计算文本再生成 HTML。
- 已验证：重绘和导入相关测试 65 个通过；全量测试 426 个通过。
- 当前状态：项目已可启动，准备打开 Web 界面。
- 已修复：Gemini 审稿请求体改用官方 `responseMimeType` 和 `responseSchema`，移除会触发 HTTP 400 的 `responseFormat.text.mimeType`。
- 已验证：Gemini/重绘相关测试 21 个通过；全量测试 427 个通过；Web 服务已重启。
- 已修复：Gemini 的 `responseSchema` 不支持 `additionalProperties`，已移除远端 schema 约束；请求只要求返回 JSON，具体 layout_hints 结构继续由本地严格校验。
- 已验证：Gemini/重绘相关测试 21 个通过；全量测试 427 个通过；Web 服务已重启。
- 已调整：Gemini 默认模型改为官方稳定的 `gemini-2.5-flash`；HTTP 503 会提示模型繁忙和当前模型名，不再输出整段接口 JSON。
- 已验证：Gemini/重绘相关测试 23 个通过；全量测试 429 个通过；Web 服务已重启。
- 已调整：Gemini 审稿提示词现在明确要求 `pages` 只返回当前 0 基页码键，并给出精确 JSON 示例；缺页错误会显示 Gemini 实际返回的页码键。
- 已验证：Gemini/重绘相关测试 24 个通过；全量测试 430 个通过；Web 服务已重启。
- 已调整：Gemini 审稿提示词明确 `skip_blocks`、`columns`、`special_regions` 必须返回对象数组，不允许返回字符串数组；模型输出格式错误会显示为 Gemini 输出错误。
- 已验证：Gemini/重绘相关测试 25 个通过；全量测试 431 个通过；Web 服务已重启。
- 已重查：官方 Gemini Python 示例使用 `google-genai` SDK；当前手写 `urllib` 在 Windows 下暴露了不稳定的 URL/HTTPS 错误。
- 已调整：Gemini 审稿调用改为官方 SDK，图片用 `types.Part.from_bytes` 传入，JSON 输出用 `GenerateContentConfig(response_mime_type="application/json")`。
- 已验证：`.venv` 已安装 `google-genai`；Gemini/重绘相关测试 24 个通过；全量测试 430 个通过；Web 服务已重启。
- 已调整：Gemini 审稿遇到超时、503、UNAVAILABLE、429/5xx 会对同一请求自动重试 3 次；模型返回 JSON 但结构错误仍直接失败。
- 已验证：Gemini/重绘相关测试 25 个通过；全量测试 431 个通过；Web 服务已重启。
- 已调整：Gemini 审稿将 SSL EOF、协议中断、`_ssl` 相关错误也视为临时网络错误，纳入同一套自动重试。
- 已验证：Gemini/重绘相关测试 26 个通过；全量测试 432 个通过；Web 服务已重启。
- 已排查：最新 Presence `_typeset.pdf/html` 实际复用了 5 月 28 日旧 `page_structure/page_content/page_content_translated`，旧结构来源 PDF 与本次上传文件名不一致，且文本区域没有行级 tracks。
- 已修复：typeset 管线复用 `page_structure.json`、`page_content.json`、`page_content_translated.json` 前会校验 `source_pdf` 是否等于当前上传 PDF 文件名，不一致就重新提取/分析/翻译。
- 已验证：新增缓存污染测试；Gemini/重绘相关测试 28 个通过；全量测试 434 个通过；Web 服务已重启。
- 已排查：最新 Presence 重绘翻译 65 个区域全部失败，根因是正文翻译接口返回 401：API Key 无效；这与 Gemini Key 无关。
- 已修复：typeset 翻译阶段如果可翻译区域 0 个成功，会直接停止并报告首个错误，不再继续导出全失败 PDF。
- 已验证：新增全失败保护测试；typeset 相关测试 34 个通过；全量测试 436 个通过；Web 服务已重启。
- 已排查：typeset HTML 图片引用为相对路径 `assets/typeset_images/...`，单独下载 HTML 时不会带上 `assets`，因此图片全不显示。
- 已修复：纯重绘 HTML 生成后会额外生成 `*.html_assets.zip`，包含 HTML 和 `assets/`；历史下载区也把 zip 识别为成品资源包。
- 已验证：Web 历史测试 6 个通过；全量测试 437 个通过；Web 服务已重启。

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

# 网页端改版

- 目标：按“千禧年秘密组织控制台”方向优化网页端，不影响翻译核心逻辑。
- 已完成：恢复普通模式入场动画；低动效模式不渲染入场遮罩，并关闭主要动画。
- 已完成：执行按钮提前到首屏任务区；历史文件移到后面的档案库，不再挡住开始任务。
- 已完成：主界面改成英雄区、导入任务舱、启动控制条、档案库；侧栏改成参数抽屉风格。
- 当前状态：代码语法检查通过，正在本地预览和细调。

# Targets of Opportunity 输出排查

- 目标：检查 `output` 里新生成的 Targets of Opportunity HTML/Word，修复双栏偶发失效和误截正文图片。
- 已确认：双栏失效主因是页面分类规则太早把“多单行块/非正文字体”的双栏页判成单栏。
- 已修复：双栏信号优先于单栏、角色页等判断；有左右栏文本时保持双栏。
- 已确认：误截图片主因是 PDF 里部分正文卡片也以图片块存在，旧逻辑只看图片块尺寸，没有判断文字层覆盖。
- 已修复：图片导出会排除被可选文字层明显覆盖的区域，也会排除纯文字卡片式截图。
- 已修复：导出的图片带有左栏、右栏、整页位置；HTML 和 Word 会按位置放图，不再全部铺满打断双栏。
- 已验证：离线生成 `output/too_fix/too_fix.html`、`.docx`、`.md`；图片资产从旧输出的杂乱截图减少为 9 张主要视觉图。
- 已验证：全量测试 387 个通过。
- 后续计划：如果重新翻译 PDF，只需要用当前代码重新导出；旧 progress 里的译文错序不会被重排自动修正。

# 可转发运行包

- 已生成：`dist/DGtranslate-20260601-101403-03de99d.zip`。
- 已检查：压缩包包含一键启动脚本、主程序、依赖清单和术语表，不包含 API Key、上传文件、输出文件或本地虚拟环境。
- 已验证：解压后的 Python 文件可编译，核心模块可导入，PowerShell 启动脚本语法正常。
- 使用条件：朋友的 Windows 电脑需要先安装 Python 3.10+；首次双击 `start_web.bat` 时需要联网安装依赖。

# 原版坐标 PDF 隐藏

- 已调整：普通输出格式列表不再展示“原版坐标 PDF”。
- 已保留：高级任务控制里可以开启“原版坐标 PDF 调试检查稿”；开启后本次任务只生成该检查稿。
- 关键决定：原版坐标 PDF 继续作为排查坐标、遮盖和翻译块问题的开发工具，不作为普通用户输出。

# 项目级协作规则

- 已新增：根目录 `AGENTS.md`。
- 已合并：第一性原理、极简沟通、尽早暴露错误、阶段更新 `context.md`，以及 `karpathy-guidelines` 的四条编码原则。
- 关键决定：规则作为仓库默认约束生效，不需要每次任务单独提及技能名称。

# Iconoclasts 排版修复

- 目标：阅读版忽略图片，保证目录、表格、卡片、双栏、页眉和页码顺畅。
- 已完成：普通 Word/HTML 不再导出或插入图片；卡片留在当前栏；表格可跨栏；正文自然流动。
- 已完成：目录识别不再依赖等宽字体；目录续页可识别；封面和页眉排除目录标题污染。
- 已完成：Word 只在封面后重置一次页码，后续分节连续计数；前端档案库折叠到任务区后方。
- 已验证：Iconoclasts 已离线重排；Word 从旧版 53 页降到 33 页，图片为 0，页码从 1 连续到 32；HTML 图片为 0，卡片保留 9 个。
- 关键决定：旧 progress 里少数已粘连的目录文本不做猜测拆分；新翻译会使用新版目录提取规则。

# PDF 多模态重绘调研

- 目标：评估引入多模态 API 改善纯重绘 PDF 排版。
- 已确认：当前 `main` 与 `origin/main` 一致，工作区开始时干净；最新提交是 `f288458 修改排版`。
- 已确认：纯重绘已具备 PyMuPDF 结构提取、语义分析、逐块翻译、HTML/CSS 重建、Playwright 导出。
- 关键判断：不要让多模态模型直接生成精确坐标；PyMuPDF 继续负责几何事实，多模态只负责阅读顺序、页眉页脚、栏、标题、边栏、表格等语义提示。
- 推荐方向：先新增严格校验的 `layout_hints.json` 中间层，再做 Gemini/marker/Docling/MinerU 实验脚本；验证稳定后才接入 `typeset_pdf`。
- 已完成：新增 `core/layout_hints.py`，支持读取 hints、按页查询，并校验 hints 引用的 block id 是否存在。
- 已完成：新增最小单元测试，覆盖缺省字段、完整 hints、非法 page_type、不存在 block id 和不存在页面。
- 已验证：全量测试 413 个通过。
- 关键决定：第一阶段只建立中间层，不接主流程，不调用外部 API。
- 已完成：`layout_hints.json` 已可选接入纯重绘管线；应用位置在语义分析之后、翻译之前。
- 已完成：hints 现在可影响 page_type、阅读顺序、跳过翻译块和左右栏分组，并输出 `page_content_hinted.json` 便于检查。
- 已完成：网页端“纯重绘排版配置”新增 `layout_hints.json 路径`，填入路径即可生成受 hints 影响的 `_typeset.pdf`。
- 已验证：新增管线测试；全量测试 418 个通过。
- 关键决定：没有 hints 时旧流程不变；有 hints 但路径或 ID 错误时直接失败。
- 已完成：新增 `experiments/gemini_layout_review.py`，可把单页 PDF 截图和本地 block 简表发送给 Gemini，生成 `layout_hints.json` 片段。
- 已完成：Gemini 输出仍会经过本地 `LayoutHints` 校验；脚本不接主流程，不默认调用外部 API。
- 已验证：新增 Gemini 实验脚本本地测试；全量测试 423 个通过。
- 关键决定：多模态只做语义审稿，不生成坐标、字号或最终 PDF。
- 已完成：网页端已整合 Gemini 自动生成 layout hints；勾选后填写 Gemini Key 和审稿页码即可自动生成并应用到本次 `_typeset.pdf`。
- 已完成：管线新增可选 `layout_hints_generator`，生成器运行在语义分析之后、翻译之前；手动 hints 路径优先于自动生成。
- 已验证：新增网页接入相关测试；全量测试 426 个通过。
- 剩余内容：真实 Gemini 联调、疑难页批量选择体验、原页与重绘页视觉对比报告、表格/边栏更细的 hints 应用。
# God's Law 输出检查

- 当前计划：对比最新 `_typeset.pdf/html`、原 PDF `uploads/_upload_Delta_Green_God_s_Law_full_proof_2_f1e89edc.pdf`、汉化参考 `uploads/绿色三角洲-甜心.pdf`。
- 验证方式：渲染页面截图，读取结构/译文数据，检查重叠、深底文字颜色、特殊排版、页码范围和 HTML/PDF 一致性。
- 当前决定：本轮只做检查和记录 bug，不修改排版代码。
- 已完成检查：最新输出只有 1-10 页；原 PDF 有 55 页，若目标是全书则输出不完整。
- 已确认 bug：任务状态为 completed_with_errors，3 个翻译块失败；第 2 页和第 8 页有英文残留。
- 已确认 bug：第 2 页斜纸条区域重复翻译、英文碎片残留、文字压到黄色标注上。
- 已确认 bug：第 3 页深色背景右栏仍是黑字，几乎不可读。
- 已确认 bug：第 6-7 页时间线结构丢失，文字堆叠重叠。
- 已确认 bug：第 8 页三角层级卡片被压平成普通正文，徽章压住文字，卡片层级丢失。
- 已确认 bug：第 9 页小表格/便签区域黑白字混用，表格行列结构丢失，局部文字重叠。
- 对比结论：甜心只能作为中文排版风格参考，不是 God's Law 的对应译文。

# God's Law 排版修复

- 当前计划：不处理页数问题；只修第 2/3/6/8/9 页暴露的真实排版和翻译失败展示问题。
- 验证方式：复用前 10 页最新产物重新生成 PDF/HTML，截图检查问题页，并运行 typeset 相关测试。
- 关键决定：优先修复输出逻辑，不引入兜底猜测；无法翻译的块必须显式失败或不导出坏成品。
- 已修复：任意 typeset 翻译块失败都会停止，不再导出带英文残留的坏 PDF/HTML。
- 已修复：斜排文字组按同角度合并为自然文本流，第 2 页不再逐框重叠。
- 已修复：混合深浅源文字会优先保留可读浅色，第 3 页深底右栏已变浅色。
- 已修复：日期密集页面按时间线三栏事件流渲染，第 6-7 页不再大面积重叠。
- 已修复：居中层级卡片按源区域定位，第 8 页三角层级不再压成普通整页正文。
- 已修复：旋转便签/表格进入自动缩字，第 9 页内容不再裁掉。
- 已验证：调试 PDF `output/Delta_Green_God_s_Law_full_proof_2_cn/_debug_after_fix_typeset.pdf` 已截图复查；全量测试 441 个通过。
- 追加检查：第 3 页左栏小标题仍压住正文；第 6 页时间线页首说明整段红字过重，均不正常。
- 当前计划：让栏内小标题进入栏流避免重叠；时间线页首说明改为普通可读说明，不整段强制红色。

# God's Law 断点续查

- 已确认：最新调试 PDF 第 6 页页首说明已恢复普通黑字，第 8 页卡片层级、第 9 页便签/正文未见明显回归。
- 已修复：第 3 页左栏栏内标题增加上下留白，不再贴住正文。
- 已清理：删除 `_group_text_color` 中上次改动留下的无效 `return`。
- 已验证：重新生成 `output/Delta_Green_God_s_Law_full_proof_2_cn/_debug_after_spacing_fix_typeset.pdf`，导出 10 页成功；全量测试 442 个通过。
- 关键决定：只补标题间距，不改识别逻辑；现有输出仍是前 10 页调试范围，不代表全书 55 页已导出。
- 已上传：分支 `codex/gods-law-typeset-fix`，草稿 PR `#11`；随后按要求直推到 `main`。
