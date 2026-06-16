# 全局工作台

本文件是当前 workspace 的总入口，用来约束 Codex 的行为、项目命名、文档使用和目录结构。

## 总规则

1. 所有项目内容必须放在 `Workspace/projects/` 下对应项目文件夹内。
2. 每个项目必须先建项目文件夹，再开始处理资料、代码、输出、日志。
3. 项目文件夹命名必须使用：`projectNNN_项目名称`。
4. `NNN` 使用三位数字，从 `001` 开始递增。
5. 项目名称只用中文、英文、数字、下划线，空格改成下划线。
6. 不把项目资料散落到桌面、下载目录、系统临时目录或 workspace 其它位置。
7. 如果工具被迫生成临时文件，任务结束前必须移入对应项目文件夹，或在项目日志说明原因。
8. 每次踩坑、返工、误判、绕路，都要记录到 `01_COMPOUND_LESSONS_LOG.md`。
9. 每次新项目启动，必须按 `02_NEW_PROJECT_SOP.md` 执行。

## Codex 行为规则

1. 先确认目标、完成条件和验证方式。
2. 先查已有文档和项目目录，再行动。
3. 不做无关重构，不顺手清理用户资料。
4. 不用猜测、兜底、静默降级掩盖问题。
5. 发现路径、命名、范围不符合规则时，先纠正再继续。
6. 每个阶段结束后更新项目内日志；涉及全局经验时更新复利日志。
7. 完成前做一次自检：文件是否放对、命名是否正确、是否有更简单做法、验证是否通过。

## 文档清单

- `00_GLOBAL_WORKBENCH.md`：总入口，汇总所有规则。
- `01_COMPOUND_LESSONS_LOG.md`：复利与踩坑日志，记录错误、原因、修正、可复用方法。
- `02_NEW_PROJECT_SOP.md`：新项目启动和归档流程。
- `projects/README.md`：项目容器说明。

## 目录结构

```text
Workspace/
  00_GLOBAL_WORKBENCH.md
  01_COMPOUND_LESSONS_LOG.md
  02_NEW_PROJECT_SOP.md
  projects/
    README.md
    project001_项目名称/
      00_project_brief.md
      01_inputs/
      02_working/
      03_outputs/
      04_logs/
      context.md
```

## 新项目文件夹规则

项目文件夹必须长这样：

```text
project001_示例项目
project002_PDF翻译检查
project003_网站重构
```

不允许：

```text
新建文件夹
test
项目资料
project1
project_001
```

## 项目内固定结构

每个项目至少包含：

```text
00_project_brief.md
01_inputs/
02_working/
03_outputs/
04_logs/
context.md
```

用途：

- `00_project_brief.md`：目标、范围、完成标准。
- `01_inputs/`：原始资料、用户给的文件、参考材料。
- `02_working/`：中间产物、草稿、临时处理文件。
- `03_outputs/`：最终交付物。
- `04_logs/`：过程记录、问题记录、检查记录。
- `context.md`：当前项目的进度和关键决定。

## 复利日志使用规则

以下情况必须写入 `01_COMPOUND_LESSONS_LOG.md`：

- 犯过的错误。
- 踩过的坑。
- 走过的弯路。
- 用户纠正过的问题。
- 未来可复用的方法。
- 值得写进 SOP 的规则。

每条记录必须包含：

```text
日期
场景
问题
原因
修正
以后复用的方法
```

## 执行顺序

每次开始新任务时：

1. 读本文件。
2. 判断是否属于新项目。
3. 如果是新项目，按 `02_NEW_PROJECT_SOP.md` 创建项目文件夹。
4. 所有文件只放入该项目文件夹。
5. 任务结束时更新项目 `context.md`。
6. 有可复用经验时更新 `01_COMPOUND_LESSONS_LOG.md`。
