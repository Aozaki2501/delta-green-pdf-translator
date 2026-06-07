# 当前进度

- 目标：修复 `aemeath-mini` 安装后不出现在宠物列表的问题。
- 已定位：安装目录存在，图集正确；问题是 `pet.json` 带 UTF-8 BOM，Codex 桌面端会跳过该配置。
- 已修复：`C:\Users\cytd\.codex\pets\aemeath-mini\pet.json` 已重写为无 BOM 合法 JSON，并补齐 `kind/source/sourceId` 字段。
- 已验证：配置读取通过；`spritesheet.webp` 存在，尺寸为 `1536x1872`，格式为 RGBA。
- 当前状态：点击宠物面板里的“刷新”，或重启 Codex 后应显示 `Aemeath Mini`。
# 当前进度

- 目标：更新仓库并打开本地 Web 项目。
- 已完成：`main` 已快进到 `origin/main` 最新提交 `bcaffda`。
- 已完成：已启动本地 Web，地址为 `http://localhost:8501`。
- 已验证：页面 HTTP 200，浏览器标题为“三角洲翻译终端”。
- 关键决定：只执行拉取、启动和记录；不修改业务代码。
- 目标：安装公开宠物包 `ameath`。
- 已完成：`npx codex-pet-installer add ameath` 因本机到 Supabase 的 HTTPS 握手失败而无法完成；已改用公开页面里的准确资源地址手动安装。
- 已验证：`C:\Users\cytd\.codex\pets\ameath` 已包含 `pet.json` 和 `spritesheet.webp`；清单 id 为 `ameath`，图片尺寸为 `1536x1872`。
- 关键决定：不修改项目代码；只结束旧终端里卡住的 `codex-pet-installer add ameath` 进程。

- 目标：安装 Codex skill `hatch-pet`。
- 已完成：已从官方 `openai/skills` curated 列表安装到 `C:\Users\cytd\.codex\skills\hatch-pet`。
- 已验证：本地目录包含 `SKILL.md`、`scripts/`、`references/` 和 `agents/`。
- 关键决定：只安装指定 skill，不改项目代码；需要重启 Codex 后才能加载新 skill。
- 目标：处理深色背景上的标题译文仍显示黑字的问题�?
- 已确认：�?PDF 已提取到该标题原始颜色为 `#ffffff`，不是识别不到，而是渲染阶段把标题强制套成主题黑/红色�?
- 已修复：固定定位标题/小标题如果源文字是浅色，会保留源浅色；普通标题仍沿用主题色�?
- 已验证：Presence 对比 PDF �?10 页黑底标题已变为白字；全量测�?439 个通过�?

- 目标：检查最�?Presence 纯重�?PDF/HTML，和�?PDF、甜心汉化参考进行版面对比�?
- 已确认：本次任务页码范围�?`9-15`，所�?`_typeset.pdf` 只有 7 页是正常范围输出，不是整本丢页�?
- 已定位：怪换行和行距挤压主要来自 `line_track_columns` 把中文硬塞进英文原始行轨道；这不�?Gemini hints 能单独修好的问题�?
- 已修复：普通中文双栏正文默认改用自然栏内重排；只有前景图片切入正文栏时才保留原行轨道，避免文字压到图片�?
- 已生成：对比文件 `output/Delta_Green_Presence_PDF_1_cn/_upload_Delta_Green_Presence_PDF_1_5190a2a4_typeset_after.pdf` �?`.html`�?
- 已验证：新对比版换行和行距明显改善，图片页没有明显文字覆盖；全量测试 438 个通过�?
- 关键决定：Gemini hints 适合修正阅读顺序、栏目、跳过块和语义分类；不适合直接解决中文行距、自然换行和段落排版�?

- 目标：评估并补充 Codex skills，重点增强前端审美和界面验收�?
- 已完成：查看官方可安�?skills 列表；当前已具备 Figma、Playwright、截图、PDF、安全、Netlify/Vercel 等核心能力�?
- 已完成：新增本地 skill `frontend-aesthetic-review`，用于前端视觉质量、响应式布局、截图验收和交互细节审查�?
- 已验证：`frontend-aesthetic-review` 通过 skill 校验�?
- 关键决定：不照营销图全量安装；暂不安装 Notion、Linear、Render、Cloudflare、Sentry、语音类和重�?GitHub 工作�?skills�?

- 目标：拉取仓库最新更新，并打开本地 Web 项目�?
- 已完成：`main` 已快进到 `origin/main` 的最新提�?`7daf6d5`�?
- 已完成：按最新依赖重新启�?Streamlit Web，地址�?`http://localhost:8501`�?
- 已验证：本地页面 HTTP 200，浏览器标题为“三角洲翻译终端”�?
- 关键决定：不合并其他分支，不改业务代码，只执行拉取、启动和记录�?

- 目标：更新到最新仓库，查看纯重�?PDF 功能，并补充 README 使用说明�?
- 已完成：执行 `git pull --ff-only`，当�?`main` 已快进到远端最新提�?`be361f9`�?
- 已确认：纯重�?PDF 已在 Web 输出格式中开放；可手动填�?`layout_hints.json`，也可勾�?Gemini 自动生成 hints�?
- 已调整：README 新增“纯重绘 PDF”说明，明确单独运行、输�?`_typeset.pdf`、hints 用途和错误处理方式�?
- 已修复：远端最新代码里 `exporters/html.py` 有一�?f-string 语法错误，会导致项目无法导入；已改成先计算文本再生成 HTML�?
- 已验证：重绘和导入相关测�?65 个通过；全量测�?426 个通过�?
- 当前状态：项目已可启动，准备打开 Web 界面�?
- 已修复：Gemini 审稿请求体改用官�?`responseMimeType` �?`responseSchema`，移除会触发 HTTP 400 �?`responseFormat.text.mimeType`�?
- 已验证：Gemini/重绘相关测试 21 个通过；全量测�?427 个通过；Web 服务已重启�?
- 已修复：Gemini �?`responseSchema` 不支�?`additionalProperties`，已移除远端 schema 约束；请求只要求返回 JSON，具�?layout_hints 结构继续由本地严格校验�?
- 已验证：Gemini/重绘相关测试 21 个通过；全量测�?427 个通过；Web 服务已重启�?
- 已调整：Gemini 默认模型改为官方稳定�?`gemini-2.5-flash`；HTTP 503 会提示模型繁忙和当前模型名，不再输出整段接口 JSON�?
- 已验证：Gemini/重绘相关测试 23 个通过；全量测�?429 个通过；Web 服务已重启�?
- 已调整：Gemini 审稿提示词现在明确要�?`pages` 只返回当�?0 基页码键，并给出精确 JSON 示例；缺页错误会显示 Gemini 实际返回的页码键�?
- 已验证：Gemini/重绘相关测试 24 个通过；全量测�?430 个通过；Web 服务已重启�?
- 已调整：Gemini 审稿提示词明�?`skip_blocks`、`columns`、`special_regions` 必须返回对象数组，不允许返回字符串数组；模型输出格式错误会显示为 Gemini 输出错误�?
- 已验证：Gemini/重绘相关测试 25 个通过；全量测�?431 个通过；Web 服务已重启�?
- 已重查：官方 Gemini Python 示例使用 `google-genai` SDK；当前手�?`urllib` �?Windows 下暴露了不稳定的 URL/HTTPS 错误�?
- 已调整：Gemini 审稿调用改为官方 SDK，图片用 `types.Part.from_bytes` 传入，JSON 输出�?`GenerateContentConfig(response_mime_type="application/json")`�?
- 已验证：`.venv` 已安�?`google-genai`；Gemini/重绘相关测试 24 个通过；全量测�?430 个通过；Web 服务已重启�?
- 已调整：Gemini 审稿遇到超时�?03、UNAVAILABLE�?29/5xx 会对同一请求自动重试 3 次；模型返回 JSON 但结构错误仍直接失败�?
- 已验证：Gemini/重绘相关测试 25 个通过；全量测�?431 个通过；Web 服务已重启�?
- 已调整：Gemini 审稿�?SSL EOF、协议中断、`_ssl` 相关错误也视为临时网络错误，纳入同一套自动重试�?
- 已验证：Gemini/重绘相关测试 26 个通过；全量测�?432 个通过；Web 服务已重启�?
- 已排查：最�?Presence `_typeset.pdf/html` 实际复用�?5 �?28 日旧 `page_structure/page_content/page_content_translated`，旧结构来源 PDF 与本次上传文件名不一致，且文本区域没有行�?tracks�?
- 已修复：typeset 管线复用 `page_structure.json`、`page_content.json`、`page_content_translated.json` 前会校验 `source_pdf` 是否等于当前上传 PDF 文件名，不一致就重新提取/分析/翻译�?
- 已验证：新增缓存污染测试；Gemini/重绘相关测试 28 个通过；全量测�?434 个通过；Web 服务已重启�?
- 已排查：最�?Presence 重绘翻译 65 个区域全部失败，根因是正文翻译接口返�?401：API Key 无效；这�?Gemini Key 无关�?
- 已修复：typeset 翻译阶段如果可翻译区�?0 个成功，会直接停止并报告首个错误，不再继续导出全失败 PDF�?
- 已验证：新增全失败保护测试；typeset 相关测试 34 个通过；全量测�?436 个通过；Web 服务已重启�?
- 已排查：typeset HTML 图片引用为相对路�?`assets/typeset_images/...`，单独下�?HTML 时不会带�?`assets`，因此图片全不显示�?
- 已修复：纯重�?HTML 生成后会额外生成 `*.html_assets.zip`，包�?HTML �?`assets/`；历史下载区也把 zip 识别为成品资源包�?
- 已验证：Web 历史测试 6 个通过；全量测�?437 个通过；Web 服务已重启�?

- 目标：拉取仓库，整理根目录杂乱文件，保留一键启动入口�?
- 已完成：执行 `git pull --ff-only`，当前分支已经是最新�?
- 关键决定：不切换分支，不改业务逻辑；只整理文档、临时测试和缓存这类不影响运行的文件�?
- 已完成：文档移到 `docs/`，开发计划移�?`docs/plans/`，临时试验脚本移�?`scratch/`，缓存已清理�?
- 已完成：新增 `start.bat`；`start_web.ps1` 会补�?Playwright Chromium，保证一键启动包�?PDF 导出依赖�?
- 已完成：修复测试里的模块缓存污染问题；全量测�?357 个通过�?
- 当前状态：根目录已收敛，双�?`start.bat` �?`start_web.bat` 都能一键启动�?

# 合入远端 main

- 目标：把 `origin/main` 的新提交合入当前功能分支�?
- 已确认：当前分支�?`feature/pdf-typeset-reflow`，`origin/main` 比当前分支多 3 个提交�?
- 关键决定：先临时保存本地未提交改动，再快进到 `origin/main`，最后恢复本地整理改动并检查冲突�?
- 已完成：当前分支已快进到 `origin/main` �?`935c998`�?
- 已处理：恢复本地改动�?`tests/test_imports.py` 有冲突，已保留远端新增测试和本地缓存恢复修复�?
- 已验证：全量测试 367 个通过�?
- 当前状态：当前分支�?`origin/feature/pdf-typeset-reflow` �?3 个远�?main 提交；本地整理改动仍未提交�?

# Kali Ghati 重绘 PDF 排查

- 目标：逐步定位 `output/Delta_Green_-_Kali_Ghati..._cn` 里重�?PDF 效果差的原因�?
- 已定位：最终文件是 `_upload_Delta_Green_-_Kali_Ghati..._typeset.pdf`，同时有 `page_structure.json`、`page_content.json`、`page_content_translated.json` �?`_typeset_report.json`�?
- 当前计划：先读报告和结构统计，再抽样查看页面类型、图片和文本块，最后再决定修复点�?
- 已确认：坏图主因是跨页图片对象被整张压进单页；PDF �?`transform` 被丢掉，只用了可�?`bbox`�?
- 已修复：未旋转图片会�?`transform` 精确裁到页面可见区域后再保存，避免跨页底图串页�?
- 已修复：旋转/倾斜图片会用�?PDF transform 生成 CSS matrix，不再当普通矩形硬塞�?
- 已修复：图片 mask 会合�?alpha；装饰层改到图片层下方，避免黑色装饰块盖住纸张�?
- 已修复：typeset 翻译改为单块请求，避免第 11/13 页这类大页因为漏 `[BLOCK]` 标记整页失败�?
- 已验证：全量测试 369 个通过；调�?PDF �?`output/_kali_typeset_layer_debug/`�?

# Typeset 文字排版方向

- 当前判断：图片问题基本可控，文字排版乱的主因是只按矩形文本块重排，丢失了双栏顺序、旋转角、逐行位置和异形区域�?
- 关键决定：要做接近原版的重绘，必须把文字层升级为“行/span 坐标层”，不能继续只靠普通段落重排�?
- 可实现范围：双栏可以稳定实现；倾斜文字可以实现；异形排版可以按原始行位置实现，复杂文字绕图需要后续单独建模�?

# 参考版式与行级重建

- 目标：参�?`绿色三角�?来自遗忘.pdf`，让 typeset 输出具备正常标题、小标题、正文行距、双栏和倾斜文字表现�?
- 已完成：默认样式改为参考书的正文约 10.9pt、行�?1.6、栏�?30pt、小标题红色 `#ed1c24`�?
- 已完成：`page_structure.json` 的文本区域现在保存每一行的 bbox、文字、字号、颜色、粗斜体和角度�?
- 已完成：中文重绘时优先按原始左右栏分别建立流动文本框；大标题和倾斜区域保留原位�?
- 已验证：重新生成调试 PDF `output/_kali_line_region_debug/kali_line_region_debug.pdf`；全量测�?372 个通过�?
- 已完成：从第 3 点推进到�?6 点，正文可按�?PDF 行轨道灌排，图片旁变窄的行会自然绕开图片�?
- 已完成：结构层新�?span �?bbox 与样式；固定非翻译文本可�?span 坐标和粗斜体颜色绘制�?
- 已完成：语义分析新增红色/短粗小标题识别，角色�?`subtitle`�?
- 已完成：新增页面模板选择器，当前支持 `line_track_columns`、`source_columns`、`single_source_flow`、`fixed_art`�?
- 已验证：重新生成调试 PDF `output/_kali_line_track_debug/kali_line_track_debug.pdf`；全量测�?376 个通过�?

# Typeset 翻译并发

- 已确认：Kali Ghati �?1-20 页有 460 个可翻译块，来自 PDF 原始文本区域，不是行/span 被误当成翻译块�?
- 已确认：此前 typeset 翻译为了稳定改成单块串行，因此并发没有生效�?
- 已修复：typeset 翻译现在保留单块请求，但�?`ThreadPoolExecutor` 并发执行，默认并发数�?`TypesetConfig.translation_concurrency = 4`�?
- 已修复：进度条按实际完成数量推进，进度文件写入加锁，避免并发保存互相覆盖�?
- 已验证：新增并发测试；全量测�?377 个通过�?

# 网页端改�?

- 目标：按“千禧年秘密组织控制台”方向优化网页端，不影响翻译核心逻辑�?
- 已完成：恢复普通模式入场动画；低动效模式不渲染入场遮罩，并关闭主要动画�?
- 已完成：执行按钮提前到首屏任务区；历史文件移到后面的档案库，不再挡住开始任务�?
- 已完成：主界面改成英雄区、导入任务舱、启动控制条、档案库；侧栏改成参数抽屉风格�?
- 当前状态：代码语法检查通过，正在本地预览和细调�?

# Targets of Opportunity 输出排查

- 目标：检�?`output` 里新生成�?Targets of Opportunity HTML/Word，修复双栏偶发失效和误截正文图片�?
- 已确认：双栏失效主因是页面分类规则太早把“多单行�?非正文字体”的双栏页判成单栏�?
- 已修复：双栏信号优先于单栏、角色页等判断；有左右栏文本时保持双栏�?
- 已确认：误截图片主因�?PDF 里部分正文卡片也以图片块存在，旧逻辑只看图片块尺寸，没有判断文字层覆盖�?
- 已修复：图片导出会排除被可选文字层明显覆盖的区域，也会排除纯文字卡片式截图�?
- 已修复：导出的图片带有左栏、右栏、整页位置；HTML �?Word 会按位置放图，不再全部铺满打断双栏�?
- 已验证：离线生成 `output/too_fix/too_fix.html`、`.docx`、`.md`；图片资产从旧输出的杂乱截图减少�?9 张主要视觉图�?
- 已验证：全量测试 387 个通过�?
- 后续计划：如果重新翻�?PDF，只需要用当前代码重新导出；旧 progress 里的译文错序不会被重排自动修正�?

# 可转发运行包

- 已生成：`dist/DGtranslate-20260601-101403-03de99d.zip`�?
- 已检查：压缩包包含一键启动脚本、主程序、依赖清单和术语表，不包�?API Key、上传文件、输出文件或本地虚拟环境�?
- 已验证：解压后的 Python 文件可编译，核心模块可导入，PowerShell 启动脚本语法正常�?
- 使用条件：朋友的 Windows 电脑需要先安装 Python 3.10+；首次双�?`start_web.bat` 时需要联网安装依赖�?

# 原版坐标 PDF 隐藏

- 已调整：普通输出格式列表不再展示“原版坐�?PDF”�?
- 已保留：高级任务控制里可以开启“原版坐�?PDF 调试检查稿”；开启后本次任务只生成该检查稿�?
- 关键决定：原版坐�?PDF 继续作为排查坐标、遮盖和翻译块问题的开发工具，不作为普通用户输出�?

# 项目级协作规�?

- 已新增：根目�?`AGENTS.md`�?
- 已合并：第一性原理、极简沟通、尽早暴露错误、阶段更�?`context.md`，以�?`karpathy-guidelines` 的四条编码原则�?
- 关键决定：规则作为仓库默认约束生效，不需要每次任务单独提及技能名称�?

# Iconoclasts 排版修复

- 目标：阅读版忽略图片，保证目录、表格、卡片、双栏、页眉和页码顺畅�?
- 已完成：普�?Word/HTML 不再导出或插入图片；卡片留在当前栏；表格可跨栏；正文自然流动�?
- 已完成：目录识别不再依赖等宽字体；目录续页可识别；封面和页眉排除目录标题污染�?
- 已完成：Word 只在封面后重置一次页码，后续分节连续计数；前端档案库折叠到任务区后方�?
- 已验证：Iconoclasts 已离线重排；Word 从旧�?53 页降�?33 页，图片�?0，页码从 1 连续�?32；HTML 图片�?0，卡片保�?9 个�?
- 关键决定：旧 progress 里少数已粘连的目录文本不做猜测拆分；新翻译会使用新版目录提取规则�?

# PDF 多模态重绘调�?

- 目标：评估引入多模�?API 改善纯重�?PDF 排版�?
- 已确认：当前 `main` �?`origin/main` 一致，工作区开始时干净；最新提交是 `f288458 修改排版`�?
- 已确认：纯重绘已具备 PyMuPDF 结构提取、语义分析、逐块翻译、HTML/CSS 重建、Playwright 导出�?
- 关键判断：不要让多模态模型直接生成精确坐标；PyMuPDF 继续负责几何事实，多模态只负责阅读顺序、页眉页脚、栏、标题、边栏、表格等语义提示�?
- 推荐方向：先新增严格校验�?`layout_hints.json` 中间层，再做 Gemini/marker/Docling/MinerU 实验脚本；验证稳定后才接�?`typeset_pdf`�?
- 已完成：新增 `core/layout_hints.py`，支持读�?hints、按页查询，并校�?hints 引用�?block id 是否存在�?
- 已完成：新增最小单元测试，覆盖缺省字段、完�?hints、非�?page_type、不存在 block id 和不存在页面�?
- 已验证：全量测试 413 个通过�?
- 关键决定：第一阶段只建立中间层，不接主流程，不调用外部 API�?
- 已完成：`layout_hints.json` 已可选接入纯重绘管线；应用位置在语义分析之后、翻译之前�?
- 已完成：hints 现在可影�?page_type、阅读顺序、跳过翻译块和左右栏分组，并输出 `page_content_hinted.json` 便于检查�?
- 已完成：网页端“纯重绘排版配置”新�?`layout_hints.json 路径`，填入路径即可生成受 hints 影响�?`_typeset.pdf`�?
- 已验证：新增管线测试；全量测�?418 个通过�?
- 关键决定：没�?hints 时旧流程不变；有 hints 但路径或 ID 错误时直接失败�?
- 已完成：新增 `experiments/gemini_layout_review.py`，可把单�?PDF 截图和本�?block 简表发送给 Gemini，生�?`layout_hints.json` 片段�?
- 已完成：Gemini 输出仍会经过本地 `LayoutHints` 校验；脚本不接主流程，不默认调用外部 API�?
- 已验证：新增 Gemini 实验脚本本地测试；全量测�?423 个通过�?
- 关键决定：多模态只做语义审稿，不生成坐标、字号或最�?PDF�?
- 已完成：网页端已整合 Gemini 自动生成 layout hints；勾选后填写 Gemini Key 和审稿页码即可自动生成并应用到本�?`_typeset.pdf`�?
- 已完成：管线新增可�?`layout_hints_generator`，生成器运行在语义分析之后、翻译之前；手动 hints 路径优先于自动生成�?
- 已验证：新增网页接入相关测试；全量测�?426 个通过�?
- 剩余内容：真�?Gemini 联调、疑难页批量选择体验、原页与重绘页视觉对比报告、表�?边栏更细�?hints 应用�?
# God's Law 输出检�?

- 当前计划：对比最�?`_typeset.pdf/html`、原 PDF `uploads/_upload_Delta_Green_God_s_Law_full_proof_2_f1e89edc.pdf`、汉化参�?`uploads/绿色三角�?甜心.pdf`�?
- 验证方式：渲染页面截图，读取结构/译文数据，检查重叠、深底文字颜色、特殊排版、页码范围和 HTML/PDF 一致性�?
- 当前决定：本轮只做检查和记录 bug，不修改排版代码�?
- 已完成检查：最新输出只�?1-10 页；�?PDF �?55 页，若目标是全书则输出不完整�?
- 已确�?bug：任务状态为 completed_with_errors�? 个翻译块失败；第 2 页和�?8 页有英文残留�?
- 已确�?bug：第 2 页斜纸条区域重复翻译、英文碎片残留、文字压到黄色标注上�?
- 已确�?bug：第 3 页深色背景右栏仍是黑字，几乎不可读�?
- 已确�?bug：第 6-7 页时间线结构丢失，文字堆叠重叠�?
- 已确�?bug：第 8 页三角层级卡片被压平成普通正文，徽章压住文字，卡片层级丢失�?
- 已确�?bug：第 9 页小表格/便签区域黑白字混用，表格行列结构丢失，局部文字重叠�?
- 对比结论：甜心只能作为中文排版风格参考，不是 God's Law 的对应译文�?

# God's Law 排版修复

- 当前计划：不处理页数问题；只修第 2/3/6/8/9 页暴露的真实排版和翻译失败展示问题�?
- 验证方式：复用前 10 页最新产物重新生�?PDF/HTML，截图检查问题页，并运行 typeset 相关测试�?
- 关键决定：优先修复输出逻辑，不引入兜底猜测；无法翻译的块必须显式失败或不导出坏成品�?
- 已修复：任意 typeset 翻译块失败都会停止，不再导出带英文残留的�?PDF/HTML�?
- 已修复：斜排文字组按同角度合并为自然文本流，�?2 页不再逐框重叠�?
- 已修复：混合深浅源文字会优先保留可读浅色，第 3 页深底右栏已变浅色�?
- 已修复：日期密集页面按时间线三栏事件流渲染，�?6-7 页不再大面积重叠�?
- 已修复：居中层级卡片按源区域定位，第 8 页三角层级不再压成普通整页正文�?
- 已修复：旋转便签/表格进入自动缩字，第 9 页内容不再裁掉�?
- 已验证：调试 PDF `output/Delta_Green_God_s_Law_full_proof_2_cn/_debug_after_fix_typeset.pdf` 已截图复查；全量测试 441 个通过�?
- 追加检查：�?3 页左栏小标题仍压住正文；�?6 页时间线页首说明整段红字过重，均不正常�?
- 当前计划：让栏内小标题进入栏流避免重叠；时间线页首说明改为普通可读说明，不整段强制红色�?

# God's Law 断点续查

- 已确认：最新调�?PDF �?6 页页首说明已恢复普通黑字，�?8 页卡片层级、第 9 页便�?正文未见明显回归�?
- 已修复：�?3 页左栏栏内标题增加上下留白，不再贴住正文�?
- 已清理：删除 `_group_text_color` 中上次改动留下的无效 `return`�?
- 已验证：重新生成 `output/Delta_Green_God_s_Law_full_proof_2_cn/_debug_after_spacing_fix_typeset.pdf`，导�?10 页成功；全量测试 442 个通过�?
- 关键决定：只补标题间距，不改识别逻辑；现有输出仍是前 10 页调试范围，不代表全�?55 页已导出�?
- 已上传：分支 `codex/gods-law-typeset-fix`，草�?PR `#11`；随后按要求直推�?`main`�?
# Presence PDF/HTML 换行检�?

- 目标：检查最�?`_typeset.html` �?`_typeset.pdf` 里异常回�?换行�?
- 已确认：源文没有硬换行；译文里有一个块带了普通硬换行，HTML 把它转成 `<br>` 后导�?PDF 出现不自然断行�?
- 已修复：纯重�?HTML 只保留空行形成的段落间隔，普通单换行交给浏览器自然排版�?
- 已顺手修复：`exporters/html.py` �?Python 3.10 不兼容的 f-string 写法，否则测试无法运行�?
- 已验证：重新生成最�?HTML/PDF，PDF 导出 0 失败；全量测�?427 个通过�?

# Presence 最新重绘对比检查

- 目标：对比最新 `_typeset.pdf/html`、英文原 PDF 和正式汉化参考《凛冬狂恋》，重点看标题粗细与颜色、黑底背景文字、文字重叠和换行。
- 已确认：普通双栏页已经接近可用，正文换行和行距整体稳定，红色小标题与黑色主标题在多数正文页表现正常。
- 仍需改善：第 2/3 页大标题识别弱，标题被当成普通正文；第 3 页“引言”附近仍有标题线与正文挤压。
- 仍需改善：第 12/22 页黑底说明框正文没有继承白字，黑底上出现黑字或文字消失。
- 仍需改善：第 31 页左侧窄正文条被扩成大浅色卡片，遮住右侧黑底人物图和页码。
- 仍需改善：第 33 页上方两栏文字横向重叠，底部卡片正文过密且留下大块空白。
- 关键判断：下一版优先修特殊版面识别，不需要大改普通双栏正文。
# Presence 标题与过宽栏修复

- 目标：修复第 3 页 `Introduction` 主标题被放进正文流、横线和正文挤到一起的问题。
- 已确认：第 3 页整页背景图文件存在并被 HTML 引用；背景本身是很淡的纸纹加右下角图片。
- 已修复：主标题固定在源位置；普通栏内小标题继续随正文流动。
- 已修复：固定标题和页码改为后绘制，避免被正文流盖住。
- 已修复：过宽栏不再合并成一个大框，版权区和右栏正文按源块各自排版。
- 已修复：固定块遇到前景横线/图片时加背景遮罩，避免线条穿过标题。
- 已验证：重新生成 `_debug_after_overwide_split_typeset.pdf`，第 3 页标题和正文不再重叠；PDF 导出失败 0 个；全量测试 447 个通过。

# Presence 标题样式与黑底遮罩修复

- 目标：检查并改进标题颜色、粗细，以及黑底说明框被浅色遮罩盖住的问题。
- 已确认：浅色遮罩规则过宽，只要文本框碰到前景图片就加浅底；黑底说明框本身也是前景图片，所以之前修好的黑底白字被误伤。
- 已修复：浅色文字不再加浅色遮罩，黑底说明框恢复黑底白字。
- 已修复：固定标题按源文字 bold 标记输出字重，不再所有标题统一强制粗体。
- 已验证：重新生成 `_debug_after_style_mask_typeset.pdf`，第 12/22 页黑底框恢复；第 3/4 页标题字重更接近原版；PDF 导出失败 0 个；全量测试 448 个通过。

# Meridian 重绘继续

- 当前目标：修复 Meridian 最新重绘里封面叠字、整页图层、正文重复吸入和特殊表格页压字问题。
- 已修复：整页图片独立放到底图层，装饰和前景图片不再被整页图盖住。
- 已修复：艺术页/封面不再叠加翻译文字，避免封面标题和底部说明被中文覆盖。
- 已修复：相邻文本框只按 span 中心归属，避免同一段被多个区域重复吸入。
- 已修复：灰底表格和密集线框表可识别为表格；密集角色表页不再强塞中文翻译。
- 已验证：Meridian HTML/PDF 重新导出 34 页成功、0 页失败；全量测试 455 个通过。
- 关键决定：最后几页角色表不是正常阅读内容，不继续追求中文化，只避免生成明显坏页。

# Meridian 输出重新生成

- 目标：用户反馈只有封面页变化，要求重新生成 PDF 和 HTML。
- 已完成：基于现有 `page_structure.json` 重新跑语义分析，并按块 ID 合回已有译文，未重新调用翻译接口。
- 已完成：重新生成 `_upload_Delta_Green_Meridian_8adbbcc9_typeset.html`、`_typeset.pdf` 和 `_typeset.html_assets.zip`。
- 已修正：密集角色表页标记为不翻译，不再计入失败翻译块。
- 已验证：PDF 导出 34 页成功、0 页失败；报告 `failed_regions=0`；全量测试 455 个通过。
- 关键决定：最后几页角色表不追求中文化，只保证不把输出做坏。

# Meridian 标题遮罩调整

- 目标：去掉标题/小标题背后的浅色遮罩，避免标题像贴了一块白膏药。
- 已完成：凡是按标题样式渲染的块，都不再添加前景遮罩。
- 已确认：封面/艺术页没有额外文字层；封面底部糊字来自原 PDF 图像本身，不是重绘层新增。
- 已生成：重新刷新 Meridian `_typeset.html`、`_typeset.pdf` 和 `_typeset.html_assets.zip`。
- 已验证：PDF 导出 34 页成功、0 页失败；报告 `failed_regions=0`；全量测试 456 个通过。
- 关键决定：遮罩只保留给正文/地图这类需要防止文字压图的区域，标题不再使用。

# Kali Ghati typeset check

- Goal: explain why latest `_typeset.html/pdf` has tilted text overflow, beige masks, page overlap, and table failures.
- Confirmed: report says 12 pages exported, 0 failed translation regions; this is not a stale refresh issue.
- Confirmed: renderer rebuilds pages from original PDF coordinates; complex tilted, image-heavy, and table pages relied only on automatic rules, with no `layout_hints.json` correction.
- Decision: fix by failing visible bad layout first, then narrowing rules for tilted flows, masks, columns, and tables; no silent fallback.
# Gemini role in typeset workflow

- Goal: explain whether Gemini helps Kali Ghati layout issues.
- Decision: Gemini is useful as a visual/layout reviewer that outputs validated `layout_hints.json`; it is not the renderer, translator, or PDF fix itself.
- Key point: use Gemini to classify special pages, reading order, skipped decorative text, columns, and table-like regions before translation/rendering.
# Kali Ghati local renderer fixes

- Goal: fix deterministic issues that multimodal API should not handle.
- Done: long translated fixed text no longer keeps source tilt; long translated headings use smaller fixed-box font.
- Done: beige foreground mask is blocked for large text areas and long translated body blocks.
- Done: typeset PDF export now runs browser layout checks before PDF output; overflow is reported instead of silently exporting bad pages.
- Verified: rebuilt Kali Ghati debug HTML/PDF from existing JSON; 12 pages exported, 0 layout issues. Full test suite: 462 passed.
- Decision: remaining special-page choices such as line-crossed cover text and dark image regions should be handled by validated Gemini `layout_hints.json`, not local guessing.
# Kali Ghati tilted card small text fix

- User clarified: the lower small text on page 2 should use the blank card space instead of staying as a separate tilted fixed box.
- Done: tilted Chinese card blocks are grouped into one readable flow when at least three related tilted blocks are present.
- Result: page 2 title/body/small note now flow together; the small note moves into the main card text flow and no longer leaves the large blank gap above it.
- Verified: rebuilt `_debug_local_fix_typeset.pdf`; 12 pages exported, 0 layout issues. Full test suite: 462 passed.

# 原坐标 PDF 清理与重绘费用显示

- 目标：废弃原坐标 PDF 功能，并让纯重绘 PDF 显示 token 用量和费用。
- 已完成：移除 Web 里的原坐标 PDF 调试入口和执行分支；`_typeset` 不再读取 `_replica.progress.json`。
- 已完成：删除原坐标 PDF 的旧脚本、旧模块和旧测试；README 不再介绍该功能。
- 已完成：纯重绘 PDF 结果、页面进度、审计记录和 `_typeset_report.json` 增加 token、API 调用和费用字段。
- 已验证：全量测试 438 个通过。

# 重绘 PDF 优化检查

- 目标：检查纯重绘 PDF 还有哪些优化点，以及是否能惠及普通 Word/HTML 排版。
- 结论：重绘 PDF 已经形成“页面结构、语义块、模板渲染、导出前溢出检查”的独立链路；普通 Word/HTML 目前仍主要使用翻译文本块和字数分页。
- 可复用方向：语义识别、阅读顺序、页面类型、表格/卡片/图片块识别可以抽成共同中间层，直接提升 Word/HTML；PDF 坐标级复刻、固定框缩字、源页面背景层不适合直接迁移。
- 已验证：相关测试 46 个通过。
# 重绘 PDF 排版能力普及到普通输出

- 目标：让普通 Word/HTML 输出复用重绘 PDF 的页面语义能力，而不是只靠字数分页。
- 已完成：新增 `core/layout_adapters.py`，把 typeset 页面语义转换成普通输出可用的布局标签。
- 已完成：CLI、Web、离线重排都接入新布局上下文；保留 `toc/handout/character/art` 等普通输出已有的特殊布局判断。
- 已完成：新增测试覆盖语义布局转换和特殊布局不被覆盖。
- 已验证：相关测试 56 个通过；全量测试 441 个通过。
# 降临 Word/HTML 输出检查

- 目标：检查 `uploads` 里的降临 PDF 与 `output/Delta_Green_Presence_PDF_1_cn` 里的 Word/HTML 是否有明显问题。
- 已确认：上传源 PDF 为 34 页；第二次审计记录为完成，输出了 HTML 和 Word，失败页为空。
- 已确认：HTML 和 Word 都不是乱码；未发现残留 `[CARD]`、Markdown 标记、未翻译占位或异常乱码标记。
- 已确认：第 25 页原 PDF 只有极少文本、主要是美术分隔页；译文为空符合当前抽取报告风险说明。
- 需要注意：同一输出目录还保留了第一次失败的旧审计记录，容易让人误以为最终任务失败；应以 `Delta_Green_Presence_PDF_1_cn_cbad524b_audit.json` 为准。
# 提示词泄露拦截

- 目标：避免模型把内部翻译规则当成译文写进 Markdown、Word 或纯重绘 PDF 输出。
- 已完成：新增译文污染检查；模型返回、解析结果、进度缓存和写回前都会拦截类似“您是专业的TRPG翻译/翻译规则包括/输出Markdown”的内容。
- 已完成：纯重绘 PDF 请求文本不再把额外说明混入待翻译正文；Markdown 和 Word 缺少合格译文时直接失败，不再写入原文占位。
- 已验证：相关测试 102 个通过。

# API 通用化

- 目标：降低纯重绘自动审稿对 Gemini 免费额度的依赖，并确认翻译 API 能通用。
- 已完成：自动 layout hints 支持 Gemini 官方接口和 OpenAI 兼容多模态接口；模型返回仍必须是合法 `layout_hints.json`，格式错误直接失败。
- 已完成：Web 里增加审稿接口、审稿 Base URL、审稿模型；翻译高级设置补出接口地址输入。
- 已完成：README 和配置示例更新为通用 API 说明。
- 已验证：相关测试 54 个通过；语法检查通过。

# 全项目优化检查

- 目标：检查当前项目还有哪些优化、重构和新增能力方向，本轮不改功能代码。
- 已确认：当前主线功能分为 PDF/Markdown/Word 翻译、普通输出、纯重绘 PDF、术语表、断点进度和 Web 工作台。
- 发现：Web/CLI 里有 `fuzzy_matching` 配置，但普通 PDF 翻译没有接入 AC 术语匹配器；该开关目前主要对 Markdown/Word 生效。
- 发现：普通 PDF 的 HTML/Word 导出失败时仍会继续流程；纯重绘 PDF 已经更严格，应统一为失败即暴露。
- 发现：`app.py`、`exporters/typeset_html.py`、`core/extractor.py` 仍是主要大文件，后续重构应优先按“任务流程、渲染策略、版面识别规则”拆分。
- 发现：输出历史会按多个审计记录生成多条历史，旧失败记录仍可能干扰用户判断最新结果。
- 已验证：全量测试 451 个通过。
- 关键决定：本轮只记录检查结论，不做功能改动；后续若开发，优先修复“开关无效”和“导出失败仍继续”这两类会误导用户的问题。

# 导出重试与输出健康优化

- 目标：推进全项目优化项，优先处理会误导用户的行为。
- 已完成：普通 PDF 翻译接入 `fuzzy_matching`，Web 和 CLI 都会把模糊术语匹配器传给翻译器。
- 已完成：普通 PDF 的 HTML/Word 导出失败不再静默继续；Web 会记录 `export_failed`，CLI 会直接抛错。
- 已完成：新增离线指定格式重排能力，Web 档案库里的“重试导出”会复用 `.progress.json`，不会重新调用翻译 API。
- 已完成：档案库同一输出目录只展示最新审计记录，旧审计记录不再抢占主状态。
- 已完成：新增 `docs/plans/EXPORT_RETRY_AND_OUTPUT_HEALTH_PLAN.md` 记录计划和进度。
- 已验证：相关测试 39 个通过；全量测试 458 个通过。
- 关键决定：大文件拆分暂不混入本轮，等行为稳定后再按小步拆分。

# 大文件拆分第一轮

- 目标：降低 `app.py` 职责混杂，先做低风险搬迁，不改变业务行为。
- 已完成：新增 `webui/runtime.py`，承接 Web 路径、下载、文件名、时长、HTML 资源包和中文字符检查等运行时小工具。
- 已完成：`app.py` 的主主题 CSS 已搬到 `webui/theme.py` 的 `render_app_theme()`，`app.py` 只保留调用入口。
- 已完成：新增 `docs/plans/LARGE_FILE_SPLIT_PLAN.md` 记录拆分原则和进度。
- 已完成：新增 `tests/test_webui_runtime.py` 覆盖拆出的运行时工具和主题渲染入口。
- 已验证：相关测试 22 个通过；全量测试 464 个通过。
- 关键决定：`typeset_html.py` 和 `core/extractor.py` 涉及版面识别/渲染规则，本轮不继续硬拆，避免混入行为变化。

# README 使用手册化

- 目标：把 README 改成新用户能直接照着操作的使用手册，并补充图文说明。
- 已完成：README 重组为安装启动、Web 流程、命令行、输出文件、术语表、断点续跑、导出重试、纯重绘 PDF、打包分享、排错和开发检查。
- 已完成：加入 Mermaid 工作流图、纯重绘流程图、界面示意、输出目录树和速查表。
- 已完成：补充最近新增能力：模糊术语匹配、导出失败拦截、档案库重试导出、OpenAI 兼容接口和多模态 layout hints。
- 已完成：新增 `docs/plans/README_MANUAL_PLAN.md` 记录文档更新计划。
