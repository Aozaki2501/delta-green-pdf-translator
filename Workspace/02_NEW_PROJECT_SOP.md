# 新项目 SOP

本文件规定每个新项目如何创建、命名、存放资料、记录过程和归档。

## 必须遵守

1. 每执行一个新项目，必须先在 `Workspace/projects/` 下创建项目文件夹。
2. 项目文件夹命名必须是：`projectNNN_项目名称`。
3. 所有相关内容必须放进对应项目文件夹。
4. 不允许把项目资料放到电脑其它位置。
5. 项目开始前必须创建 `00_project_brief.md` 和 `context.md`。
6. 项目结束前必须更新 `context.md`，并把最终产物放到 `03_outputs/`。

## 编号规则

1. 查看 `Workspace/projects/` 下已有项目。
2. 取最大编号加 1。
3. 编号固定三位数。

示例：

```text
已有：project001_PDF翻译检查
新建：project002_术语表清理
```

## 命名规则

允许：

```text
project001_PDF翻译检查
project002_术语表清理
project003_WebUI改版
```

不允许：

```text
project1_PDF翻译检查
project_001_PDF翻译检查
PDF翻译检查
新建文件夹
project004 PDF 翻译检查
```

## 创建结构

每个项目固定创建：

```text
projectNNN_项目名称/
  00_project_brief.md
  01_inputs/
  02_working/
  03_outputs/
  04_logs/
  context.md
```

## 文件放置规则

- 原始文件、用户上传资料：放 `01_inputs/`。
- 临时处理、中间结果、草稿：放 `02_working/`。
- 最终交付文件：放 `03_outputs/`。
- 检查记录、错误记录、测试记录：放 `04_logs/`。
- 当前计划、进度、关键决定：写 `context.md`。
- 项目目标、范围、完成标准：写 `00_project_brief.md`。

## 项目启动步骤

1. 读 `Workspace/00_GLOBAL_WORKBENCH.md`。
2. 判断是否是新项目。
3. 创建 `projectNNN_项目名称` 文件夹。
4. 创建固定目录结构。
5. 填写 `00_project_brief.md`：

```text
# 项目简报

## 目标

## 范围

## 输入

## 输出

## 完成标准

## 验证方式
```

6. 填写项目 `context.md`：

```text
# 当前计划

1. 要做什么 -> 如何验证

# 当前进度

- 已创建项目目录

# 关键决定

- 所有资料只放在本项目目录内
```

## 项目执行步骤

1. 每完成一个阶段，更新项目 `context.md`。
2. 遇到错误或绕路，先写入项目 `04_logs/`。
3. 如果这个错误以后可能复用，再同步写入 `Workspace/01_COMPOUND_LESSONS_LOG.md`。
4. 产出文件只放 `03_outputs/`。
5. 不在根目录、桌面、下载目录、系统临时目录留下项目文件。

## 项目收尾步骤

1. 检查项目文件是否都在项目文件夹内。
2. 检查 `03_outputs/` 是否包含最终产物。
3. 检查 `context.md` 是否记录最终状态。
4. 检查 `04_logs/` 是否记录重要问题。
5. 有复用价值的经验，写入全局复利日志。

## 例外处理

如果某个工具必须临时使用系统目录：

1. 任务结束后把有价值文件移入项目文件夹。
2. 删除无用临时文件。
3. 在项目 `context.md` 记录原因。
4. 不把系统临时目录当作长期存放位置。
