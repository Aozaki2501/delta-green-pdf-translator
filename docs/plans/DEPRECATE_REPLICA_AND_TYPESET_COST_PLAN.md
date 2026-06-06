# 原坐标 PDF 清理与重绘费用显示计划

1. 已完成：清理原坐标 PDF 用户入口 -> Web 页面不再出现或执行 `_replica.pdf`
2. 已完成：清理重绘流程对 `_replica.progress.json` 的依赖 -> `_typeset` 只使用自己的进度文件
3. 已完成：给重绘 PDF 记录 token 和费用 -> 页面、审计记录和 `_typeset_report.json` 都能看到用量
4. 已完成：清理旧说明和旧测试 -> 全量测试通过
