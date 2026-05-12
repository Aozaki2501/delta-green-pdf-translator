# DG TRPG PDF 翻译工具

专为《绿色三角洲（Delta Green）》TRPG 扩展资料设计的 AI 翻译工具。  
使用 DeepSeek V4 API 进行翻译，支持双栏 PDF 排版识别和 TRPG 术语表。

## 功能特点

- **智能双栏提取**：自动检测 TRPG 书籍常见的双栏排版，按正确阅读顺序提取文本
- **页眉页脚过滤**：自动过滤页码、章节标题等非正文内容
- **TRPG 术语表**：支持加载 TSV 格式术语表，确保专有名词翻译一致
- **断点续翻**：翻译进度自动保存，中断后重新运行会从上次位置继续
- **Markdown 输出**：结构化输出，方便在 Obsidian/Typora 等工具中阅读

## 安装依赖

```bash
pip install pymupdf openai
```

## 使用方法

### 基础用法

```bash
python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-你的密钥
```

### 完整参数

```bash
python translate_pdf.py "THE MILLENNIUM.pdf" \
    --api-key sk-你的密钥 \
    --glossary glossary.tsv \
    --output millennium_cn.md \
    --model deepseek-v4-pro \
    --start 0 \
    --end 320
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `pdf` | 输入 PDF 文件路径 | （必填） |
| `--api-key` | DeepSeek API Key | （必填） |
| `--output`, `-o` | 输出 Markdown 文件路径 | `{输入文件名}_cn.md` |
| `--glossary`, `-g` | 术语表文件路径 | 无 |
| `--model` | 模型名称 | `deepseek-v4-pro` |
| `--start` | 起始页码（从 0 开始） | 0 |
| `--end` | 结束页码（不含） | 全部 |

### 使用 deepseek-v4-flash（更快更便宜）

```bash
python translate_pdf.py "THE MILLENNIUM.pdf" --api-key sk-xxx --model deepseek-v4-flash
```

## 术语表格式

术语表为 TSV（Tab 分隔）文件，每行格式：

```
中文译名\t英文原名
```

示例：
```
绿色三角洲	Delta Green
旧日支配者	Great Old One
阿撒托斯	Azathoth
```

- 以 `#` 开头的行为注释
- 空行会被忽略
- 脚本会自动匹配当前页面出现的术语，只将相关术语传入 prompt

## 断点续翻

翻译进度会自动保存到 `{输出文件}.progress.json`。如果翻译中断：

1. 直接重新运行相同命令即可
2. 已翻译的页面会自动跳过
3. 翻译全部完成后，进度文件会保留供参考

如需重新翻译某些页面，删除进度文件或指定新的输出文件名即可。

## 费用估算

以 320 页 PDF 为例（DeepSeek V4 Pro 当前 75% 折扣期）：

- 平均每页约 500-800 token 输入 + system prompt
- 估计总消耗：约 40-60 万 token（含 prompt 开销）
- 预估费用：约 ¥5-15（取决于实际文本密度）

使用 `deepseek-v4-flash` 可进一步降低费用（约为 Pro 的 1/5）。

## 输出示例

```markdown
# THE MILLENNIUM — 中文翻译

---

<!-- Page 1 -->

## 科尔瓦兹之剑（The Sword of Korvaz）

这件三千年历史的青铜圣物，其名称源自北落师门（Fomalhaut）的古称——
旧日支配者库图克瓦（Qu-Tugkwa）栖息于此星。

### 特殊属性（仅对持剑者生效）

- **燃烧（COMBUSTION）**：持剑者将剑刃触碰物体，即可点燃任何可燃物...
- **烈焰伤害（FIERY DAMAGE）**：通常造成 1D8 伤害。消耗 1 WP...

---
```

## 已知限制

1. **图片和表格**：当前版本不处理 PDF 中的图片和复杂表格
2. **极端排版错误**：如果 PDF 本身文本层有严重错误（如 OCR 质量极差），提取结果可能不理想
3. **超大页面**：单页文本超过 DeepSeek 上下文窗口时可能需要分段处理（一般 TRPG 书籍不会出现此问题）

## 许可

本工具仅供个人学习使用。请尊重原作版权。
