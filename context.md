# 当前计划

1. 整理项目现状 -> 对齐功能入口、测试现状、主要流程
2. 检查风险和隐患 -> 找出会误导使用或增加维护成本的问题
3. 收口无用开发内容 -> 先清理明显过期的脚本说明和重复文档

# 当前进度

- 已确认主线功能：PDF / Markdown / Word 输入，输出 HTML / Word / Markdown，另有独立的 `_typeset.pdf` 流程
- 已确认测试现状：`.venv` 下 `pytest` 487 通过；系统 Python 直接跑 `pytest` 失败，说明实际工作流依赖项目虚拟环境
- 已完成整理：`test_setup.py` 改为检查 Streamlit；`docs/GUIDE.md` 改成精简版；`README.md` 的开发自检命令改为使用 `.venv`
- 已完成修复：`start_web.ps1` 不再在启动时强制下载 Chromium；Web 端导出 `_typeset.pdf` 时会按需提示加载浏览器内核插件并显示进度

# 关键决定

- 先不碰主翻译逻辑，只修会误导使用和维护的旧内容
- `README.md` 作为唯一完整使用说明，`docs/GUIDE.md` 只保留最短入口
- 输出目录、打包产物、实验样本先只标记为可清理对象，不直接删除用户数据
- 浏览器内核改为按需安装：普通 Web 启动不依赖 Chromium，只有纯重绘 PDF 流程才触发加载
