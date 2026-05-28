# PDF Translation Upgrade Plan

## Goal

吸收成熟 PDF 翻译项目的经验，但不做完整 PDF 复刻。当前目标是提高本项目作为 TRPG 翻译工作台的可靠性、校对效率和输出可读性。

## Scope

1. 失败页管理：失败页单独记录，可只重试失败页，失败内容不混入完成缓存。
2. 提取诊断：每页输出版面、表格、卡片、图片、风险提示，翻译前暴露问题。
3. 图片资源：从原 PDF 裁出正文图片，HTML/Word 输出时尽量放回占位位置。
4. 表格增强：更稳定地识别和渲染表格，避免表格被普通段落打散。
5. 多后端配置：把 OpenAI 兼容接口的 base URL、模型和服务名配置化。

## Out Of Scope

- 不做原文/译文对照 HTML。
- 不做术语表冲突检查。
- 不做原版 PDF 坐标级复刻。

## Progress

- Started: 2026-05-20.
- Done: 失败页写入 `failed_pages`，Web/CLI 可只重试失败页。
- Done: 提取诊断对象、诊断报告、Web 预览风险提示。
- Done: PDF 正文图片裁剪到 assets 目录，并传给 HTML/Word/Markdown 输出。
- Done: 表格识别放宽到单栏表格，并保留结构化 Markdown 表格输出。
- Done: 翻译后端 provider/base URL 配置进入 Web、CLI、config 和进度指纹。
- Checked: full test suite passes.
- Done: 跨页断句导出前会先接完整句子；中文卡片短行不再被合并成一坨；HTML 卡片样式改为轻量边栏纸条。
- Done: 新输出按文件名自动创建独立目录，正文、进度、报告和 assets 不再散落在 output 根目录。
- Done: Web 字体改回黑体栈，并加入绝密系统接入开场动画。
