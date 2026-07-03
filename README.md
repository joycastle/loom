# worklog — 跨项目 / 跨 session / 跨 AI 工具 的全量成果台账

把散落在「多个 git 仓 + 多个 AI 工具会话(Claude / Codex / Cursor / CodeBuddy)+ 飞书需求池」里的**你自己**的工作,自动汇成按天的 markdown 日记,带回链、可检索、可云端同步。

## 为什么

- **无损原文层(零维护)**:git 提交 + 各 AI 工具 transcript + 飞书需求池,本来就在,自动产生。
- **采集器(本项目)**:拉取式扫描 → 归一化 `(日期, 项目, 工具)` 条目 → 渲染日记,每条带回链。
- **底座(Basic Memory)**:markdown vault 交 Basic Memory(MCP)→ 各 AI 工具即插即用读写/检索;`git push` → 云端 + 版本。

## 代码 / 配置分离

```
<本仓>/                     共享代码(clone 后一键装)
  worklog/  bin/worklog  install.sh  config.example.json

~/.worklog/                每人自己(init 生成,不入代码仓)
  config.json              身份 / 仓 / 需求池 / 源开关(命令管理)
  .env                     FEISHU_APP_ID/SECRET(gitignored,绝不进 vault)
  data/entries.jsonl       归一化条目(可再生)
  vault/journal/*.md       独立 git 仓 → push 私有 GitHub
```
可用环境变量 `WORKLOG_HOME` 覆盖 `~/.worklog`。

## 安装

```bash
git clone <本仓> ~/Documents/worklog
cd ~/Documents/worklog && ./install.sh      # 装 CLI 到 PATH + 引导配置 + 首次同步
```

## 命令

```bash
worklog init                      # 交互引导:身份/扫仓/飞书
worklog sync [--push] [--since]   # 采集全部源 → 渲染 → 提交(--push 上云)。日常就这条
worklog collect --source <name>   # 单源采集:git|claude|codex|cursor|codebuddy|feishu|all
worklog build | today | search <词>

worklog repo add|rm|scan|ls [值]  # 灵活增删 git 仓(scan 自动发现)
worklog feishu add <url>|rm|ls    # 增删需求池(URL 解析 app_token/table_id)
worklog identity add <邮箱/名>|ls  # 增补 git 身份
worklog source enable|disable <name>
```

## 各源采集说明

| 源 | 取自 | 内容 |
|---|---|---|
| git | 所有配置仓 `git log --all`(按你的邮箱/名字过滤) | 提交(标题 + 改动量) |
| claude | `~/.claude/projects/*/*.jsonl` | 会话:意图标题 + 时间 + 项目 |
| codex | `~/.codex/state_5.sqlite` threads | 会话:cwd/标题/首句意图 + 时间 |
| cursor | `Cursor/.../globalStorage/state.vscdb` composer 头 | 会话:标题 + 改动量(无正文) |
| codebuddy | `CodeBuddy/.../state.vscdb` | 占位;本地无缓存时由 git 兜底 |
| feishu | 多维表格 `bitable/v1 list records` | 需求:按「负责人=你」+ 日期筛 |

隐私:vault 只存**元数据 + 意图标题**,不存完整对话、不含密钥。

## 云端 + 检索底座

```bash
cd ~/.worklog/vault && gh repo create worklog-vault --private --source=. --remote=origin --push
# 之后 worklog sync --push 自动上云

uvx basic-memory project add worklog ~/.worklog/vault/journal   # 语义检索
# 各 AI 工具接 Basic Memory MCP:见 adapters(claude/cursor/codex 的 mcp 配置)
```

## 扩展新采集器

在 `worklog/collectors/` 加 `xxx.py`,实现 `collect(cfg, since) -> [entry]`,在 `collectors/__init__.py` 注册即可。条目 schema:`{id, date, ts, project, tool, kind, summary, ref, detail}`。
