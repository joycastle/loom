# loom 交接文档(HANDOFF)

> 读者:接手的同事或其他 AI 工具。读完即可维护 / 部署 / 续做。
> 代码仓:`~/Documents/loom`(独立 git 仓)。个人实例:`~/.loom/`。
> 姊妹愿景:`docs/loom-bot-design.md`(托管多租户机器人,未实现)。

---

## 目录

1. 它解决什么 + 第一性
2. 代码 / 配置分离
3. 架构与目录 + 条目 schema
4. 各采集器现状(读哪 / 产出 / 坑)
5. 命令
6. 迪仔实例现状 + 迁移历史
7. loom-bot 愿景
8. 待办 / 开放项(逐条含状态)
9. 部署 + Basic Memory 接入

---

## 1. 它解决什么 + 第一性

**问题**:一个人的工作散落在多个 git 仓、多个 AI 工具会话(Claude/Codex/Cursor/CodeBuddy)、飞书需求池/群聊里。要回顾「我做过什么」(写周报/绩效/交接)时,得跨源考古。「全」和「可维护」天生打架:靠人手写,写全就维护不动。

**第一性拆法(全 / 好检索 / 可维护 三者兼得)**:

- **无损原文层(零维护,自动产生)**:git 提交、各 AI 工具 transcript、飞书表/消息。它们本来就在,不需要任何人去维护。这是「全」的来源。
- **采集器(本项目,派生索引)**:拉取式扫描无损层 → 归一化成 `(日期,项目,工具)` 条目 → 渲染成按天 markdown 日记,每条带**回链**(commit hash / transcript 路径 / 需求链接)。索引是浓缩的,但一跳可回无损原文 → 「全」不丢。
- **底座(白拿检索 + 云端)**:markdown vault 交 **Basic Memory**(MCP,各 AI 工具即插即用读写/语义检索);vault 是 git 仓,`git push` 私有 GitHub = 云端 + 版本。

**结论**:无损层不维护(自动)、索引由采集器派生(不靠手写)、检索与云同步由底座白拿。人日常只需 `loom sync` 一条命令。

---

## 2. 代码 / 配置分离

| | 代码仓 `~/Documents/loom` | 个人实例 `~/.loom/` |
|---|---|---|
| 内容 | Python 包 + bin + install.sh + docs | config.json / .env / data / vault |
| 依赖 | **纯标准库,零外部依赖**(飞书走 urllib) | 无 |
| 入 git? | 是(可 clone 分发) | config/vault 各自的 git;`.env` **gitignored 绝不入库** |

- `~/.loom/config.json`:身份 / 仓 / 需求池 / 源开关(靠子命令管理,免手编)。
- `~/.loom/.env`:`FEISHU_APP_ID/SECRET` 等凭证,**永不进 vault / 代码仓**。
- `~/.loom/data/entries.jsonl`:归一化条目(可再生,不必手改)。
- `~/.loom/vault/journal/*.md`:按天日记,是**独立 git 仓** → push 私有 GitHub;也是 Basic Memory / Obsidian 的索引对象。
- 环境变量 **`LOOM_HOME`** 可覆盖 `~/.loom`(多实例 / 测试用)。

---

## 3. 架构与目录 + 条目 schema

```
~/Documents/loom/
  bin/loom                 # 瘦入口:解析 realpath → 把仓根加 sys.path → 跑 loom.cli.main
  install.sh               # 一键部署
  config.example.json  README.md
  docs/{loom-bot-design,HANDOFF}.md
  loom/                    # python 包(纯标准库)
    cli.py                 # argparse 分发 + init 引导 + 配置子命令
    config.py              # 读写 config.json + 增删助手 + 飞书 URL 解析
    store.py               # entries.jsonl 按 id upsert(load/save/upsert)
    render.py              # 按天渲染 markdown,保留「手写区」哨兵
    util.py                # 路径/LOOM_HOME、load_env、http_json(urllib)、read_sqlite(copy-to-temp 防锁)、ms_to_iso
    collectors/
      __init__.py          # REGISTRY: name -> collect(cfg,since)->[entry];加源在此注册
      git.py claude.py codex.py cursor.py codebuddy.py feishu.py feishu_im.py
```

**统一条目 schema**(所有采集器产出同构,render/store 只认这个):
```python
{
  "id":      "git:<repo>:<hash>" / "claude:<sid>" / "feishu:<table>:<rid>" ...,  # 幂等主键
  "date":    "2026-07-02",           # 归到哪天(渲染分组键)
  "ts":      "2026-07-02T09:45:00",  # 排序用
  "project": "data-marketing",       # 归到哪个项目 [[wikilink]]
  "tool":    "git|claude|codex|cursor|codebuddy|feishu",
  "kind":    "commit|session|requirement|note",
  "summary": "标题/意图/需求名(截断)",
  "ref":     "回链:commit hash / transcript 路径 / 需求链接 / 消息定位",
  "detail":  { ... }                 # 工具特有:改动量 / 起止时间 / 状态 / thread_id 等
}
```
**渲染分组**:日记按 `date → project` 分组;每项目下分「提交 / 需求 / 飞书记事 / AI 会话」小节。`render._preserve_notes` 用哨兵 `<!-- ✍️ 手写区 -->` 保护哨兵以下的**手写正文**,`sync` 只重写自动区块。

**扩展新源**:在 `collectors/` 加 `xxx.py` 实现 `collect(cfg, since)->[entry]`,在 `__init__.py` 注册即可;CLI 的 `--source` 选项自动含它。

---

## 4. 各采集器现状(读哪 / 产出 / 坑)

### git(脊柱,最可靠)
- 读:`cfg.repos` 每个仓 `git log --all --no-merges --since --numstat`。
- 过滤:作者 email ∈ `identities.emails` 或 name ∈ `identities.names`(只抓**本人**)。
- 去噪:滤掉 stash 内部提交(`index on/untracked files on/WIP on`);同 `(项目,日期,标题)` 只留改动最大一条(收敛 rebase/cherry-pick 重复)。
- 产出:`kind=commit`,detail=`{files,ins,del}`。
- 坑:`--all` 会含所有分支(含 WIP 分支,期望内);跨机器多身份需把所有 email 加进 identities。

### claude(Claude Code)
- 读:`~/.claude/projects/*/*.jsonl`,每文件一个 session。取 cwd(→项目)、min/max timestamp、`ai-title` 或首条真实用户消息(意图)。
- 产出:`kind=session`,detail=`{start,end,user,asst}`。
- 坑:意图提取过滤了系统提醒/命令包裹/tool_result;无 cwd 时从目录名兜底。

### codex
- 读:`~/.codex/state_5.sqlite` 的 `threads` 表(`cwd/title/first_user_message/created_at_ms/updated_at_ms/git_branch`)。`_find_db` 兼容 `state_5/state/state_4/state*.sqlite`。
- 产出:`kind=session`,意图=title 或 first_user_message。
- 坑:sqlite 先 copy-to-temp(含 -wal/-shm)防锁;表名/版本变了要调 `_CANDIDATES`。

### cursor
- 读:`Cursor/User/globalStorage/state.vscdb` 的 `ItemTable['composer.composerHeaders']` → `allComposers[]`(name/createdAt/lastUpdatedAt/trackedGitRepos/filesChangedCount/lines±)。**只有元数据,无对话正文**(符合隐私决策)。
- 产出:`kind=session`,detail=`{start,end,files,add,del}`。
- **⚠ 已知问题**:`_project_from_repos` 猜的 `trackedGitRepos` 字段名(repoPath/path/rootPath/relativePath)与真实结构不符 → 实测约 **60/80 会话落到 "cursor" 桶**而非真实项目。**待办**:摸清 composerHeaders 里 trackedGitRepos 的真实 JSON 结构(`sqlite3` 打开 globalStorage/state.vscdb 看该 key 的 value),修 `_project_from_repos`。

### codebuddy(占位)
- 读:`CodeBuddy/User/globalStorage/state.vscdb` 的 `interactive.sessions`。本机为空 → log 一句并返回 `[]`(其产出已由 git 脊柱覆盖)。
- 待办:有实际会话数据的机器上,确认结构后在此按 codex/cursor 同构映射(已留 TODO hook)。

### feishu(多维表格 / 需求池)
- 读:`cfg.feishu.bitables` 每张表 `bitable/v1/apps/{app_token}/tables/{table_id}/records` 分页全量。
- 过滤:**客户端**按 `person_field`(如"需求负责人",逗号分隔可多人)包含 `owner.feishu_name`;日期取 `date_field` 否则 `last_modified_time`,`< since` 丢弃。(飞书 filter 不支持人员字段,故客户端过滤。)
- 产出:`kind=requirement`,summary=标题+[状态]。
- 坑:应用须被加为该多维表格协作者;`token()` 用 env 凭证,进程内缓存。**目前 `feishu.enabled=false`,未跑通**(见 §8)。

### feishu_im(主动打点,**gated off**)
- 读:`im/v1/chats` 列 bot 所在群 → 每群 `im/v1/messages`(时间窗)→ 只留 `mentions` 含**机器人 open_id**(`bot/v3/info` 取)的消息。`chat_allowlist` 可收敛。
- 产出:`kind=note`,summary=消息正文(截断),detail=`{chat,chat_id,thread_id,from_open_id}`;`id=feishu_im:<message_id>` 幂等。
- 门控:`cfg.feishu.im.enabled`(默认 false)。未开或无凭证 → 安静返回 `[]`(已验 fail-safe)。
- 坑:窄 scope 下可能只能读到「@机器人」那条本身、读不到话题里其他消息;要整条话题需宽读权限。`fetch_thread` 目前只在 detail 存 thread_id,未真正拉取兄弟消息(留待增强)。

---

## 5. 命令

```bash
loom init                       # 交互引导:名字/飞书名、探测+补 git 邮箱、扫仓、飞书凭证与需求池 URL
loom sync [--push] [--since]    # 采集全部源 → 渲染日记 → 提交 vault(--push 上云)。★日常就这条
loom collect --source <name>    # 单源采集:git|claude|codex|cursor|codebuddy|feishu|feishu_im|all
loom build                      # 只重渲染日记(不重新采集)
loom today                      # 打印今天的日记
loom search <词>                # 在条目 summary/project 里查(语义检索走 Basic Memory)

loom repo add|rm|scan|ls [值]   # 增删 git 仓(scan <dir> 自动发现 .git 深度≤3)
loom feishu add <url>|rm|ls     # 增删需求池(URL 解析 app_token/table_id;缺 table 会追问)
loom identity add <邮箱/名>|ls   # 增补 git 身份(带 @ 入 emails 否则入 names)
loom source enable|disable <name>
```

---

## 6. 迪仔实例现状 + 迁移历史

- **实例**:`~/.loom/`(config 含 15 个仓 + 3 个 email 身份 + names dizai6266/dizai;feishu 默认关)。
- **已采**:近 100 天 **444 条**(git 336 / cursor 80 / claude 16 / codex 12),渲染 **62 个日记**;vault 在 `~/.loom/vault`(独立 git 仓,commit 信息 `loom sync <时间>`)。
- **迁移历史**:
  - v1 是 `~/worklog` 下的**单文件 CLI**(只采 git+claude),实例数据在 `~/.worklog`。
  - v2 重构为**包 + 多采集器**,代码搬到 `~/Documents/loom`,实例迁到 `~/.loom`。
  - 全量 **worklog → loom 改名**已完成(命令/包/`LOOM_HOME`/`~/.loom` 路径/frontmatter `type: loom`/文档)。曾有一坑:`mv ~/.worklog ~/.loom` 后 config.json 里 `vault.dir` 仍指旧路径,已修为 `~/.loom/vault`。
  - 旧 `~/worklog` 目录**仍在**(已被取代,可删,待用户点头)。
- **接入**:`/opt/homebrew/bin/loom` 软链 → `~/Documents/loom/bin/loom`;Claude Code skill 在 `~/.claude/skills/loom/`(输入 `/loom` 可用;旧 `worklog` skill 已移除)。

---

## 7. loom-bot 愿景

一句话:把「个人本地拉取」升级为**托管多租户机器人**——**任何人**在飞书话题 @ 机器人一句,它读上下文、为其**建/复用仅他可读的多维表格**记事并回执。完整蓝图(运行时/API 时序/权限模型/AI 接入点/分阶段路线)见 **`docs/loom-bot-design.md`**。它是 loom 的姊妹组件;loom 的 `feishu_im` 采集器是其「只有我、本地」最小切片。

---

## 8. 待办 / 开放项(逐条含状态)

1. **飞书需求池 + feishu_im 未跑通**(代码就绪,gated)。需:
   - `~/.loom/.env` 填 `FEISHU_APP_ID/FEISHU_APP_SECRET`;
   - 应用被加为需求池多维表格**协作者** / 机器人被拉进目标**群**;
   - scope:`bitable:app:readonly`(需求池)、`im:message:readonly`(或 `im:message.group_at_msg:readonly`)、`im:chat:readonly`、可选 `im:message:send_as_bot`(回执)、`contact:user.base:readonly`、可选 `docx:document:readonly`;
   - 然后 `loom feishu add <url>` + 把 `feishu.enabled` / `feishu.im.enabled` 置 true,用一个群/一张表实拉验证(可用已知的「迪仔负责」条数交叉校验)。
2. **cursor 项目归属修正**:`_project_from_repos` 待摸真实 `trackedGitRepos` 结构(见 §4 cursor)。
3. **云端 / 定时 / 检索底座**(均未做,**需用户点头**):
   - 云端:`cd ~/.loom/vault && gh repo create loom-vault --private --source=. --push`,并 `loom sync --push`;
   - 每日:crontab `0 19 * * * /opt/homebrew/bin/loom sync --push`(或 launchd);
   - Basic Memory:`uvx basic-memory project add loom ~/.loom/vault/journal` + 各 AI 工具接 MCP。
4. **`cli.py` 缺 `loom feishu im on/off` 子命令**:目前 `feishu` 子命令只管 bitable(add/rm/ls),IM 开关需手改 config.json,待补。
5. **codebuddy 解析**:待有本地会话数据的机器上确认结构后补(已留 TODO hook)。

---

## 9. 部署 + Basic Memory 接入

**一键部署** `./install.sh`:
1. 校验 python3;
2. 软链 `bin/loom` 到可写且在 PATH 的目录(`/opt/homebrew/bin` → `/usr/local/bin` → `~/.local/bin`);
3. 跑 `loom init`(引导配置);
4. 跑一次 `loom sync`;
5. 末尾打印云端 / cron / Basic Memory 的可选命令。

**各 AI 工具接 Basic Memory MCP**(共享同一批 vault markdown):
- 先 `uvx basic-memory project add loom ~/.loom/vault/journal`;
- Claude Code:`claude mcp add basic-memory -- uvx basic-memory mcp`;
- Cursor:`~/.cursor/mcp.json` 加 `{"mcpServers":{"basic-memory":{"command":"uvx","args":["basic-memory","mcp"]}}}`;
- Codex:`~/.codex/config.toml` 加 `[mcp_servers.basic-memory]\ncommand="uvx"\nargs=["basic-memory","mcp"]`。
(v1 曾在 `~/worklog/adapters/` 放过这些片段;v2 尚未在代码仓固化 adapters 目录——如需可补。)

---

_最后更新:随 feishu_im + loom-bot-design 一并提交。维护时改代码后同步更新本文对应小节。_
