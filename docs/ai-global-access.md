# 让任意项目里的 AI 都能访问你的台账

loom 装好后 CLI 就是全局的——**任何**有 shell 能力的 AI 编码助手,在**任何**项目目录里
都能直接查你的台账。缺的只是"告知层":让 AI 知道有这个东西、什么时候该用。

## 一段话接入(复制下面片段到各工具的全局规则)

```markdown
# 全局:个人工作台账 loom(任何项目可用)

我有一个跨项目的个人工作台账 `loom`(CLI 已在 PATH)。当我问"我之前/某天/某件事
做过什么、结论是什么、相关文档/数据在哪"这类历史问题时,先用它查,别只翻当前仓:

    loom search <关键词> [--project P] [--tool T] [--since D]   # 全文检索(中文子串可用)
    loom topic ls / loom topic show <主题>    # 主题树 / 一件事的全景(对话+提交+文档+数据)
    loom today                                # 今天的日记

数据在 ~/.loom/(日记 vault: ~/.loom/vault/journal/*.md 可直接读);命中条目带 ref 回链,
要细节顺回链读原文。纪律:~/.loom/.env 是凭证,不读不引用;向台账写入前先问我。
```

## 各工具落点

| 工具 | 全局规则位置 | 做法 |
|---|---|---|
| **Claude Code** | `~/.claude/CLAUDE.md` | 建文件贴入片段(每个会话自动加载) |
| **Codex** | `~/.codex/AGENTS.md` | 同上 |
| **Cursor** | `~/.cursor/rules/loom.mdc`(新版)或 Settings → Rules → User Rules(通用) | 文件方式加 frontmatter `alwaysApply: true`;旧版本在 GUI 里粘贴 |
| 其它/兜底 | — | 对话里说一句「用 `loom search xxx` 查我的台账」即可,CLI 天然可用 |

## 效果

在任何仓里问 AI:"我 6 月底关于净额口径的结论是什么?" → 它会先
`loom search 净额` / `loom topic show <主题>`,拿到**带回链**的真实历史,而不是在当前仓里瞎翻。

## 可选升级:语义检索(Basic Memory MCP)

FTS 是关键词检索("cohort"召不回"留存")。要语义检索,把 vault 挂给 Basic Memory:

```bash
uvx basic-memory project add loom ~/.loom/vault
# 再在各 AI 工具的 MCP 配置里接入 basic-memory server
```
