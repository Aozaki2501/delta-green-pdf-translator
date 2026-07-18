# 高保真 HTML 当前进度

更新时间：2026-07-17

## 最终目标

把 TRPG PDF 转换成接近《全知之眼》人工中文版质量的 HTML：

- 保留原页美术、图片和装饰。
- 中文正文稳定分栏，不裁切、不重叠。
- 标题、卡片、表格和时间线按各自结构重建。
- 页眉也要翻译，并保持原有左右位置。

## 已完成

- 完成 Dead Letter 前 16 页与原 PDF、现有 HTML、《全知之眼》标杆文件的逐页对比。
- 当前代码已经明显改善普通双栏页、信息卡和部分人物数据页。
- 已把下一阶段的五个问题写成回归测试，避免后续修复再次退化。

## 当前还未修复

1. 只有两个正文区域的页面会被误判为单栏。
2. 运行页眉目前被当成不可翻译文字。
3. 纯美术页会直接丢掉需要翻译的页眉和页码。
4. Dead Letter 使用的橙红色 `#eb4f24` 没有被识别为标题强调色。
5. `JANUARY 2`、`SEPTEMBER 4 (Friday)` 这类时间线日期没有被识别为稳定标题块。

## 测试状态

执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_semantic_segments.py tests\test_typeset_local_rendering_fixes.py
```

结果：9 个通过，5 个失败。

这 5 个失败正好对应上面的五个待修问题，是为了固定问题而先写的测试；生产代码尚未开始修改。

## 下一步

1. 修正双栏判断、页眉翻译和美术页文字层。
2. 补齐 Dead Letter 标题色与时间线日期识别。
3. 让 5 个回归测试全部通过。
4. 重新生成 Dead Letter 前 16 页，逐页与《全知之眼》的中文排版质量对照。
5. Review 查 Bug，再做一次简化检查和全量测试。

## 继续工作时重点查看

- `core/semantic_analyzer.py`
- `core/typeset_translation.py`
- `exporters/typeset_html.py`
- `tests/test_semantic_segments.py`
- `tests/test_typeset_local_rendering_fixes.py`

说明：原 PDF、标杆 PDF、页面截图和生成预览只保留在本机工作区，不提交到仓库。
