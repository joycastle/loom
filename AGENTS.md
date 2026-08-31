# AGENTS.md — 给 AI 编码助手的项目指引

> 跨工具开放标准文件。Codex / Cursor / GitHub Copilot / Windsurf / Gemini / Aider / Zed
> 原生读取;**CodeBuddy** 在无 CODEBUDDY.md 时自动全量加载本文件;**Claude Code** 见 CLAUDE.md。

## 这是什么
**loom** —— 单人、零依赖(纯标准库 Python)的跨来源工作台账:采集 git 提交 / AI 对话
(Claude·Cursor·Codex·CodeBuddy·pi·OpenCode)/ 文档 / 代码 / 数据 / 日报,归一成一份扁平记录,派生出
检索索引、按天日记、主题关联、私有云备份。
- **代码**在本仓;**用户数据**在 `~/.loom/`(config/.env/data/vault),两者物理分离。
- 命令:`loom sync | search | related | doc add | data add | note | report | session | topic | deprecate | init`。
- **两种关联**:`topic`(人工语义 DAG,一件事)+ `related`(自动结构边:会话产出的提交/共改文件/文档↔提交/对话续接,从条目字段派生、零人工)。
- **分类工作流**:`topic gather`(未归类→AI 出 TSV)→ `apply`;`gather --refine`(回看已归类,补更细/更多主题,apply 追加不覆盖);`gather --hierarchy`(AI 提父子边)→ `set-parents --file`(校验无环后写父级)。
- **serve/mcp-serve**:`loom serve` 本地管理页(浏览器);`loom mcp-serve` 把 loom 暴露成 MCP 原生工具
  (`claude mcp add loom -- loom mcp-serve`),供 Claude/Codex 等直接调用 `loom_search`/`loom_note` 等。

## ⭐ 首次上手 / 整理历史 → 读 ONBOARDING.md
如果用户是**刚拿到本项目**、要你带他完成配置并把历史资料整理好,
**打开 [ONBOARDING.md](./ONBOARDING.md) 并逐步执行**——那是一份面向 AI 的执行剧本
(环境配置 → 首次采集 → 收编散落资料 → 私有云备份 → 主题层完整分类 → 日常)。

## 🩺 帮用户配置 → 跑 `loom doctor`
用户说"帮我配 loom / 配一下信息源 / 看看还缺什么"时,**跑 `loom doctor --json`**,
它只读、可反复跑、每条建议自带一条 `fix_command`。按 `risk` 分流处理:
- **`risk: "zero"`**(探测到的路径、可开启的源):可以 `loom doctor --apply --dry-run`
  给用户看一眼要做什么,点头后 `loom doctor --apply` 批量落地(或逐条跑各自 `fix_command`)。
- **`risk: "needs_confirmation"`**(飞书登录、关注词/静音/VIP 个性化、任何写 `.env` 的):
  **必须逐条读给用户、拿到明确同意才执行**对应 `fix_command`,不能因为在批处理里就一起过
  (对齐铁律 1「外发/写入先确认」)。
- `fix_command` 原样执行,别自己拼命令行。`loom doctor --source <名>` 可只体检某一个源。
- 飞书关注词候选在 `detail.candidates` 里(据用户近期编码/笔记数据抽的),挑完用
  `loom feishu watch <词>` 写入——**这些个性化只进本地 `~/.loom/config.json`,绝不进仓库**。

## 全程铁律(任何操作都遵守)
1. **不可逆 / 外发操作先向用户确认**:删除、移动、`git push`、对外分享。
2. **凭证只进 `~/.loom/.env`(chmod 600),绝不写入任何仓**;采集内容入库前已自动打码。
3. **原始数据不上云**:csv/xlsx 等留本地 `_data/`(gitignore),只有文本知识层进私有云。
4. **分类/归类看内容,别图快**:AI 主题分类要读条目实际内容(不是标题/首句),关键词会
   系统性过采;大规模分类用"逐条判 + 对抗复核",拿不准不硬塞,分完逐主题核对。详见 ONBOARDING.md。
5. 改动代码后跑 `python3 -m pytest tests/test_loom.py`(纯标准库,零依赖)。
