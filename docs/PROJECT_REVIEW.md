# 项目风险、优化与前端重构记录

更新时间：2026-07-26

## 当前结论

项目已经具备可用的 PDF、Markdown、Word 翻译流水线，断点续跑、术语匹配、质量报告和 TRPG 规则检查是主要优势。当前重点不是继续增加零散功能，而是先保证译文完整、术语一致、状态可信，再重构前端工作流。

本次复查的核心判断：**真正的风险不是功能缺失，而是静默的正确性问题**——译文截断不报错、术语冲突不报错、进度损坏不报错。`AGENTS.md` 里写的"尽早暴露错误，不要用静默降级掩盖问题"，正是当前最该补的一条。

已有独立证据支持这个判断。`Workspace/projects/project002_Delta_Green_PDF质量检查/03_outputs/质量检查报告.md` 对一次真实成品做了逐页人工检查，结论是：第 5 页时间线整块为空、第 15 页两栏正文消失、7 处文字溢出。**这些页在质量报告里没有告警**。代码层自评与成品层实测指向同一个问题。

## 已确认风险

### 先处理

1. **模型返回长度截断时不检查 `finish_reason`。** `core/translator.py:285` 和 `:376` 取到 `message.content` 后只判断非空，从不读 `finish_reason`。`max_tokens` 为 4096（`core/translator.py:273`）和 8192（`:364`）。截断产生的半页译文会被当成成功，并写入 `translation_cache`（`:291`、`:382`）持久化，重跑也不会自愈。这是当前最高优先级问题。
2. **截断兜底检测阈值过宽。** `core/utils.py:149` 要求 `译文可见长度 / 原文可见长度 < 0.15` 才判定为截断。译文缩水到原文一半长度仍能干净通过。与第 1 条叠加，等于两道防线同时失效。
3. **Markdown 和 Word 命令行仍默认使用即将停用的 `deepseek-chat`。** `translate_md.py:102`、`:233`；`translate_docx.py:105`、`:241`。
4. **费用使用固定单价计算，界面显示的人民币金额不可信。** 单价硬编码在 `core/translator.py:42-44`（1.0 / 4.0 / 0.1 元每百万 token），但用户可填任意模型与任意 `base_url`。`app.py` 有 6 处显示金额（`:1039`、`:1443`、`:1537`、`:1586`、`:1753`、`:1759`、`:2028`），`core/run_report.py:36` 还会据此算"每页成本"写进报告。
5. **同一英文词只有一个译名能生效，且是静默的。** 机制分两种，修复方式不同：
   - **精确重复被覆盖**：`core/glossary.py:39` 是 `glossary[english] = chinese`，同大小写的后一条直接盖掉前一条。`glossary.tsv` 实测仅 1 例——`Owlshead Mountain`（`glossary.tsv:513` 奥尔斯海德山 / `:956` 枭首山），前者彻底丢失。
   - **仅大小写不同的条目在字典里共存，但只有文件里靠前的能命中**：匹配大小写不敏感，且 `core/glossary.py:611-617` 明确规定先插入的条目"拥有"该小写键的所有位置。实测 `The Agent` / `The agent` / `AGENT` 三种写法全部返回 `Agent -> 特工`。同类共 4 组，靠后的那条是死条目、永远不会命中：

     - `glossary.tsv:118` `Agent` -> 特工 **生效**；`:120` `agent` -> 探员 失效
     - `:63` `ifrit` -> 火灵 **生效**；`:302` `Ifrit` -> 炎魔 失效
     - `:398` `metoh-kangmi` -> 人熊雪人 **生效**；`:399` `Metoh-Kangmi` -> 雪人 失效
     - `:709` `unnatural` -> 非自然 **生效**；`:934` `Unnatural` -> 非自然知识 失效

   注意：这不是随机择一，而是**行序决定、完全确定**。因此光加冲突检测不够，还需决定是否支持大小写敏感区分（`Agent` 作专有身份、`agent` 作普通名词，在 Delta Green 语境里是有意义的区分）。
6. **进度 JSON 损坏时静默从头开始，并会覆盖原文件。** `core/progress.py:115-116` 捕获异常后只 print 一行就继续，此时内存容器仍是 `__init__` 里的空值（`:68-71`），不存在半加载脏状态。但随后任何 `mark_completed()` 触发的 `save()`（`:118-142`）会用空数据原子覆盖原文件，可抢救的译文永久销毁。该分支**不设** `ignored_existing_progress` 标记，而 `app.py:1608` 只检查 `metadata_mismatches`，所以界面上没有任何告警——用户只会看到整本重译和全额重复付费。
7. **进度指纹漏掉会改变译文的设置。** `core/progress.py:23-39` 只记 9 个字段，缺：`fuzzy_matching`（`translate_pdf.py:696`、`app.py:226`）、`max_workers`（会改变上下文构成，见"随后处理 1"）、Word 页眉翻译 `translate_headers`（`app.py:136` 硬编码 True）、`temperature`（`core/translator.py:272`）。另外 `core/utils.py:184-186` 的 `file_sha256` 对不存在的路径返回空串，导致"术语表文件丢失"与"本来没有术语表"指纹相同。
8. **Markdown 和 Word 命令行共用一个进度文件。** `translate_md.py:160` 与 `translate_docx.py:166` 都写死 `Path(output_path).parent / ".progress.json"`。两个不同文档输出到同一目录时共用该文件，指纹不匹配 → 丢弃对方译文 → 首次 `save()` 覆盖 → 缓存永久销毁。这两个入口还**从不检查** `metadata_mismatches`（只有 `translate_pdf.py:196` 和 `app.py:1608` 检查），用户拿不到提示。触发条件有限：默认输出目录是每文档独立的 `{stem}_translated/`（`translate_md.py:127`），只有显式用 `--output` 指向同一目录才会撞。

### 随后处理

1. **串行与并行的上下文策略不一致，改并发数就会改译文。**
   - PDF 并发路径：每页各取相邻页**原文**前后 900 字符（`translate_pdf.py:292-298`）。
   - PDF 串行路径：prev 用的是**上一页译文**尾部（`translate_pdf.py:342-343`）。
   - Markdown / Word 走 `ConcurrentDispatcher`：`core/dispatcher.py:210-211` 注释即 "all groups in batch share it"，`:235` 把同一份 `batch_context` 提交给整批；批末只取本批最大 index 的译文末段更新窗口，中间片段不贡献上下文，窗口以并发数为步长跳进。

   叠加"先处理 7"（并发数不在指纹内），改并发后仍复用旧缓存，同一份输出里会混杂两种策略的译文。
2. **质量检查覆盖面窄。** 主要依赖字符比例（`core/quality.py`）。规则符号只校验骰子和 `SAN`/`HP`/`WP` 三项（`core/rule_symbols.py:11`、`:152`、`:160`），不校验技能值、伤害、护甲、射程、致死率。段落遗漏、线索错位、数值改写目前查不出来。
3. **`uploads/` 和 `output/` 没有清理入口或保存期限。** 全仓库搜不到任何清理逻辑（无 `rmtree`、无保留期、无 UI 入口）。实际留存内容比预期多：
   - `uploads/`：原始版权 PDF 明文长期留存（`webui/runtime.py:167-169`）。
   - `output/*/page_content.json`、`page_content_translated.json`：逐字英文原文 + 译文（`core/typeset_pipeline.py:266`）。
   - `output/*/*.progress.json`：全量译文 + `translation_cache` + `base_url`（`core/progress.py:140`），实测单文件 210 KB。
   - 单个排版任务另有两份 5.6 MB assets zip。
4. **审计文件的绝对路径只修了一半。** `_audit.json` 已经干净（只有文件名和 SHA256）。但 `_typeset_report.json` 仍写入本机绝对路径 `"html_output": "E:\\DGtranslate\\output\\..."`（`core/typeset_pipeline.py:822` 取值、`:845` 落盘）。
5. **`base_url` 没有协议校验。** `app.py:917` 和 `translate_pdf.py:125` 只检查非空，未做 scheme 检查、HTTPS 强制或 host 白名单，随后直接传入 `core/translator.py:148`。填入 `http://` 远程地址，API Key（Authorization 头）与全文原文会明文出网。允许任意兼容接口是设计意图，但至少应拦住非 HTTPS 的远程地址。
6. **`layout_hints.json` 路径无目录约束。** `core/typeset_pipeline.py:688-692` 只检查 `exists()` 后 `resolve()`，`core/layout_hints.py:66-68` 直接 `read_text()`。本地单用户自己填路径时影响有限；若把 Streamlit 暴露到网络，则构成任意本地 JSON 文件读取与存在性探测。
7. **仓库缺少 CI、依赖锁文件和 LICENSE。** 无 `.github/`。`requirements.txt` 混用 `==` 与 `>=`（`google-genai>=`、`hypothesis>=`、`pyahocorasick>=`），换机器装出的环境不保证一致。`google-genai` 是必装依赖，却只被 `experiments/gemini_layout_review.py` 使用，应移为可选。
8. **界面与业务流程集中在两个大文件。** `app.py` 2298 行却只有 8 个函数，基本是一条直线的 Streamlit 脚本，UI、校验、任务编排、报告渲染混在顶层。`webui/theme.py` 2718 行维护两套结构不同的 CSS（`:9` 二选一、`:809` `OFFICE_THEME_CSS`、`:1197` `OFFICE_COMPONENT_CSS`）。
9. **仓库里有一份完整的代码副本。** `scratch/integrate-dg-trans/` 含 102 个 py 文件，与主干只有 5 个文件有差异（`core/translation_validation.py`、`core/typeset_models.py`、`core/typeset_pipeline.py`、`exporters/__init__.py`、`exporters/typeset_html.py`）。已被 gitignore，但留在磁盘上，搜索与排查时极易读错文件。根目录另有 5 个游离脚本：`diag_38_51.py`、`diag_cards.py`、`test_card_38_51.py`、`test_card_68_98.py`、`test_card_detect.py`。

### 性能

1. **进度文件每次都全量重写。** `ProgressTracker.save()`（`core/progress.py:118-142`）序列化整个 JSON，而 `mark_completed()`（`:157`）和 `mark_cached_prompt_translation()`（`:242`）各会触发一次；`core/dispatcher.py:260` 每个块也调一次。实测进度文件 210 KB，一本 200 页的书要重写约 400 次 200 KB+ 的文件，是 O(n²) 的磁盘写入。可改为按批次或定时落盘。
2. **每次上传都对目录内同后缀文件做完整 SHA256。** `webui/runtime.py:164-166` 为去重遍历 `uploads/` 下所有同后缀文件并逐个全量哈希。目录里 PDF 一多就明显变慢，可缓存 `(文件名, 大小, mtime) -> 哈希`。

## TRPG 翻译优化方向

### 译文完整性

1. 检查模型停止原因。`finish_reason == "length"` 时直接判为失败并抛出，交给已有的 `core/recursive_splitter.py` 拆分重译，**且不写入缓存**。
2. 把 `core/utils.py:149` 的截断阈值 0.15 收紧到 0.45 左右，并按版面类型分档。
3. 对标题、表格、卡片、数据块和 `[BLOCK]` 标记做数量与顺序校验。当前只验证"这一页有译文"，不验证"块数对得上"。
4. 对百分比、骰子、SAN 损失、HP、WP、护甲、伤害、致死率、射程和技能值做源译文逐项对照。
5. `_load()` 遇到损坏 JSON 时，先把原文件改名备份（如 `.corrupt.bak`）再从头开始，绝不静默覆盖；同时设置告警标记让界面能显示。

### 长篇一致性

1. 术语表加载时检测冲突并**直接报错**，不再静默取一个。先把 `glossary.tsv` 的 1 例精确重复和 4 组大小写重复定稿。
2. 决定大小写策略：要么统一为大小写不敏感并合并重复项，要么支持大小写敏感区分并让匹配尊重它。
3. 术语表升级为实体表，记录标准译名、别名、类别、性别、组织关系、语境、证据页和备注。
4. 先抽取全书高频人物、地点、组织和行动代号，再开始正文翻译。
5. 以章节或场景为并行单位；章节内部按顺序翻译，并维护人物、地点和语气摘要。
6. 统一串行与并发的上下文策略，让译文不随并发数变化；在统一前先把 `max_workers` 补进指纹。
7. 术语变化后只重翻受影响的页或块。

### 真实质量验证

1. 建立小型真实模组回归集，覆盖双栏、跨页段落、数据块、玩家手册、线索卡、时间线、表格和异常字体。这是做任何重构之前最该先补的安全网。
2. 每次改动检查文本完整性、规则数字、阅读顺序和输出版式，不要求译文逐字相同。
3. 把 project002 已发现的失败页（第 2、5、15 页：英文残留叠字、时间线整块为空、正文消失）固化为回归用例。
4. 扫描件先做明确预检；OCR 通过外部适配器接入，不在本项目内重造完整 OCR 引擎。

## 安全与数据卫生方向

1. `base_url` 校验协议，远程非 HTTPS 地址给出明确警告或直接拦下。
2. 费用问题修复前，界面与 `_run_report.md` 只显示 token 数和 API 调用次数，不显示金额；要保留金额就把单价做成可配置项并与 `base_url` 绑定。
3. 增加存储管理入口：列出 `uploads/`、`output/` 占用，支持按任务或按时间删除。
4. 去掉 `_typeset_report.json` 里的本机绝对路径，只保留相对路径或文件名。
5. `layout_hints.json` 路径限制在项目目录或输出目录内。
6. 清理 `scratch/` 副本与根目录游离脚本（先确认那 5 个有差异的文件里没有未合并的改动）。
7. `google-genai` 移为可选依赖；`requirements.txt` 统一 pin 策略并补依赖锁文件。

## 前端重构方向

### 产品定位

界面应定位为"TRPG 翻译与校对工作台"，不是宣传页，也不是模拟终端。Delta Green 氛围可以保留为颜色和少量文案，但不能干扰上传、配置、校对和重翻。

### 推荐信息结构

1. **新建任务**：上传文件 → 选择范围和输出 → 确认术语 → 提取预检 → 开始翻译。
2. **执行中**：只显示总进度、当前步骤、失败项、预计时间和暂停/继续操作。
3. **校对**：风险列表在左，原文与译文并排，右侧显示术语和规则数值；支持勾选后重翻。
4. **档案库**：按任务展示状态、时间、源文件、输出、失败页和离线重导出。

### 视觉原则

1. 使用一个稳定设计系统，提供浅色/深色主题，不再维护两套不同结构的"终端模式"和"办公模式"。
2. 去掉启动遮罩、大型英雄区、雷达和重复状态卡；首屏三秒内应看到上传区和主操作。
3. 采用中性灰背景、白色内容区、深绿色主色；红色只表示失败，琥珀色表示警告。
4. 圆角控制在 6–8px，减少卡片套卡片；用分组标题和留白表达层级。
5. 正文字号保持 14–16px，参数标签清楚，避免密集面板中的大标题。
6. 动画只用于进度和状态变化；完整支持低动效、键盘焦点和足够的文字对比度。

### 交互原则

1. 默认只展示必要设置，高级设置按输入类型和输出格式动态出现。
2. API 地址、模型和密钥放入独立的"连接设置"，新建任务只显示当前连接摘要。
3. 在执行前提供一张最终确认摘要：页数、输出、术语表、模型、并发和预计调用量。
4. 费用计算修复前不显示金额，只显示 Token 和 API 调用次数。
5. 错误信息必须说明下一步，例如"重新提取""只重试失败页"或"离线重导出"。

### 代码拆分建议

1. `app.py` 只保留路由和会话状态。
2. 新建 `webui/pages/`，分别承载新建任务、执行、校对和档案库。
3. 新建可复用组件：任务摘要、步骤条、连接状态、术语表、质量问题列表、原译文对照、输出文件列表。
4. 主题文件只保留变量、基础控件和响应式规则，删除重复的两套大段 CSS。
5. 重构时先保持业务行为不变，再逐页迁移；每个页面完成后做桌面和窄屏截图检查。

## 验证基线

- 640 个测试通过（`.venv\Scripts\python.exe -m pytest`，约 67 秒）。
- 语法和环境检查通过。
- 术语表匹配行为已用实测确认（`load_glossary` + `ACGlossaryMatcher` 对大小写变体的实际返回值）。
- 当前缺少真实 API、真实 PDF 和浏览器端到端回归，这部分应在重构前补最小基线。
