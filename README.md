# loom — 跨项目 / 跨 session / 跨 AI 工具 的全量成果台账

把散落在「多个 git 仓 + 多个 AI 工具会话(Claude / Codex / Cursor / CodeBuddy)+ 飞书需求池」里的**你自己**的工作,自动汇成按天的 markdown 日记,带回链、可检索、可云端同步。

## 为什么

- **无损原文层(零维护)**:git 提交 + 各 AI 工具 transcript + 飞书需求池,本来就在,自动产生。
- **采集器(本项目)**:拉取式扫描 → 归一化 `(日期, 项目, 工具)` 条目 → 渲染日记,每条带回链。
- **底座(Basic Memory)**:markdown vault 交 Basic Memory(MCP)→ 各 AI 工具即插即用读写/检索;`git push` → 云端 + 版本。

## 代码 / 配置分离

```
<本仓>/                     共享代码(clone 后一键装)
  loom/  bin/loom  install.sh  config.example.json

~/.loom/                每人自己(init 生成,不入代码仓)
  config.json              身份 / 仓 / 需求池 / 源开关(命令管理)
  .env                     FEISHU_APP_ID/SECRET(gitignored,绝不进 vault)
  data/entries.jsonl       归一化条目(可再生)
  vault/journal/*.md       独立 git 仓 → push 私有 GitHub
```
可用环境变量 `LOOM_HOME` 覆盖 `~/.loom`。

## 安装

```bash
git clone <本仓> ~/Documents/loom
cd ~/Documents/loom && ./install.sh      # 装 CLI 到 PATH + 引导配置 + 首次同步
```

## 命令

```bash
loom init                      # 交互引导:身份/扫仓/飞书
loom sync [--push] [--since]   # 采集全部源 → 渲染 → 提交(--push 上云)。日常就这条
loom collect --source <name>   # 单源采集:git|claude|codex|cursor|codebuddy|feishu|all
loom build | today
loom search <词> [--project P] [--tool T] [--since D] [--until D]
                               # SQLite FTS5(trigram):≥3 字符 bm25 排序,<3 字符回退子串;空词+过滤=浏览

loom repo add|rm|scan|ls [值]  # 灵活增删 git 仓(scan 自动发现)
loom feishu add <url>|rm|ls    # 增删需求池(URL 解析 app_token/table_id)
loom identity add <邮箱/名>|ls  # 增补 git 身份
loom source enable|disable <name>
```

## 各源采集说明

| 源 | 取自 | 内容 |
|---|---|---|
| git | 所有配置仓 `git log --all`(按你的邮箱/名字过滤) | 提交(标题 + **正文** + 每文件改动;整 diff 走回链) |
| claude | `~/.claude/projects/*/*.jsonl` | 会话:意图标题 + 时间 + 项目 |
| codex | `~/.codex/state_5.sqlite` threads | 会话:cwd/标题/首句意图 + 时间 |
| cursor | `Cursor/.../globalStorage/state.vscdb` composer 头 | 会话:标题 + 改动量(无正文) |
| codebuddy | `CodeBuddy/.../state.vscdb` | 占位;本地无缓存时由 git 兜底 |
| feishu | 多维表格 `bitable/v1 list records` | 需求 / 记事:按「负责人=你」+ 日期筛 |

隐私:vault 只存**元数据 + 意图标题**,不存完整对话、不含密钥。

### 飞书打点走独立机器人(不在 loom 内读 IM)

loom 只做**拉取式读多维表格**这一条飞书链路(scope 仅需 `bitable:app:readonly`)。
「在话题里 @ 机器人 → 总结后写进多维表格」由一个**独立的飞书应用(机器人)**负责:
它订阅消息事件、AI 总结、写入多维表格(并带**原消息链接**回链)。loom 随后当作普通需求池表读取即可。
这样捕获(实时 push)与聚合(loom 拉取)彻底解耦。托管多租户形态的完整蓝图见 `docs/loom-bot-design.md`。

## 云端 + 检索底座

```bash
cd ~/.loom/vault && gh repo create loom-vault --private --source=. --remote=origin --push
# 之后 loom sync --push 自动上云

uvx basic-memory project add loom ~/.loom/vault/journal   # 语义检索
# 各 AI 工具接 Basic Memory MCP:见 adapters(claude/cursor/codex 的 mcp 配置)
```

## 扩展新采集器

在 `loom/collectors/` 加 `xxx.py`,实现 `collect(cfg, since) -> [entry]`,在 `collectors/__init__.py` 注册即可。条目 schema:`{id, date, ts, project, tool, kind, summary, ref, detail}`。
