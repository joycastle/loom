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
- 采集入库前对自由文本(summary + detail 递归 str/list/dict)跑 `util.redact` 抹掉 token/密钥值(`cfg.redact` 默认 true;私有可信仓可设 false;`redact_entry` 递归)——`entries.jsonl` 与 vault 两处都不留机密。`safe_join`(realpath)防 triage/归档路径穿越写出 vault。
  - **覆盖**:私钥块(含 PGP)/ JWT / AWS AKIA / GitHub ghp/gho/ghs/ghu/ghr/pat / Stripe / Google AIza·ya29 / Slack token·webhook / Azure AccountKey / OpenAI sk- / bearer·Basic / URL 密码 / `键=值`(键像密钥;引号值更激进,裸值需数字/base64尾/超长以免误伤散文)。
  - **已知限制(低危)**:markdown 表格单元格里的弱密码、裸的全小写长口令 可能漏(权衡了对散文的误伤);二进制文件(pdf/docx/xlsx)`loom doc add` 原样拷、不扫描(CLI 会提示)。真机密多含数字/固定前缀 → 绝大多数被覆盖。原文永远在 transcript/git,回链可查。
- `~/.loom/data/entries.jsonl`:归一化条目(可再生,不必手改)。
- `~/.loom/data/index.sqlite`:从 entries 派生的 FTS5 检索索引(可删可再生,`loom search` 会自动重建)。
- `~/.loom/vault/`:**独立 git 仓** → push 私有 GitHub(`loom-vault`),Basic Memory / Obsidian 的索引对象。分区:`journal/*.md`(自动生成,勿手改)+ `notes/`(手写文档区,loom 从不碰)+ 仓根 `README.md`(说明布局)。
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
    search.py              # 从 entries.jsonl 派生的 SQLite FTS5(trigram)检索索引;可再生
    intake.py              # loom doc add:外来文档快速入库 notes/(补 frontmatter + 打码)
    render.py              # 按天渲染 markdown;自动区({date}.md)与手写区({date}.notes.md)物理分离
    util.py                # 路径/LOOM_HOME、load_env、http_json(urllib)、read_sqlite(copy-to-temp 防锁)、ms_to_iso、redact(密钥打码)
    collectors/
      __init__.py          # REGISTRY: name -> collect(cfg,since)->[entry];加源在此注册
      git.py claude.py codex.py cursor.py codebuddy.py feishu.py docs.py notes.py
  tests/test_loom.py       # 纯标准库 unittest;跑:python3 -m unittest discover tests
```

**测试**:`python3 -m unittest discover tests`(或 `-m unittest tests.test_loom`)。零外部依赖。测试**必须**在导入 loom 前把 `LOOM_HOME` 指向临时目录(`util` 在导入时就固化了 `HOME`/`DATA_PATH`/`INDEX_PATH`);`test_loom.py` 顶部已这么做。覆盖:store upsert/排序、config(飞书 URL 解析 / add_bitable 去重 / 非 git 仓拒绝 / 默认键合并)、cursor `_project` 归属优先级、render 手写区不被覆盖 + 旧哨兵迁移、search FTS/LIKE 兜底/过滤/自动重建。

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
**渲染分组**:日记按 `date → project` 分组;每项目下分「提交 / 需求 / 飞书记事 / AI 会话」小节。

**自动区 / 手写区物理分离**(消灭「重渲染吃掉手写正文」的不可逆风险):
- `{date}.md`:自动日志,每次 `sync` **整体重写**(可再生)。
- `{date}.notes.md`:手写笔记,loom **永不覆盖**——`render._ensure_notes_file` 只在文件缺失时建空模板,或从旧版 `{date}.md` 哨兵(`LEGACY_MARK`)下的遗留正文**一次性迁移**过来;已存在则一个字都不动。
- `{date}.md` 末尾用 Obsidian 内嵌 `![[{date}.notes]]` 把笔记显示在一起;两文件对 Basic Memory 也各自独立可检索。
- (旧版是把手写正文内联在 `{date}.md` 哨兵之下、随重渲染保留 —— 现已废弃,因为渲染 bug 会不可逆地吃掉手写正文。)

**扩展新源**:在 `collectors/` 加 `xxx.py` 实现 `collect(cfg, since)->[entry]`,在 `__init__.py` 注册即可;CLI 的 `--source` 选项自动含它。

---

## 4. 各采集器现状(读哪 / 产出 / 坑)

### git(脊柱,最可靠)
- 读:`cfg.repos` 每个仓 `git log --all --no-merges --since --numstat`。
- 过滤:作者 email ∈ `identities.emails` 或 name ∈ `identities.names`(只抓**本人**)。
- 去噪:滤掉 stash 内部提交(`index on/untracked files on/WIP on`);同 `(项目,日期,标题)` 只留改动最大一条(收敛 rebase/cherry-pick 重复)。
- 产出:`kind=commit`,detail=`{files,ins,del, body, file_list}`。**body**=提交正文(`%b`,「为什么这么改」;剥掉 Co-Authored-By/Signed-off-by 等 trailer,封顶 4000 字);**file_list**=每文件 `{path,ins,del}`(封顶 40)。渲染:正文作引用块挂在提交下,文件明细列前 8 个 + 折叠计数。
- **解析要点**:format 为 `header\n%b`,`%b` 多行 → 用 numstat 正则(`^(\d+|-)\t(\d+|-)\t`)区分「文件明细行」与「正文行」(正文在文件明细开始前)。改这段小心别让正文里的制表符误判。
- **不存整 diff**:行级 diff 由回链 `git show <hash>` 一跳可得(无损层),不塞进 vault —— 否则单个 +800 提交就是 ~900 行,爆 vault 且与无损层重复。
- 坑:`--all` 会含所有分支(含 WIP 分支,期望内);跨机器多身份需把所有 email 加进 identities。

### claude(Claude Code)
- 读:`~/.claude/projects/*/*.jsonl`,每文件一个 session。取 cwd(→项目)、min/max timestamp、`ai-title` 或首条真实用户消息(意图)。
- 产出:`kind=session`,detail=`{start,end,user,asst, opening}`。**opening**=首条实质用户消息**全文**(封顶 1200 字,保留换行)—— summary 只是 180 字短意图,opening 是「开场我要干什么」。渲染:opening 比 summary 多出的部分作引用块挂在会话下(标题前缀相同则不重复渲染)。
- **不存完整对话**:transcript 动辄 40–120MB(单会话用户消息就 ~1MB),是无损层;`ref`=jsonl 全路径,一跳可 `cat`/打开看全。
- 坑:意图提取过滤了系统提醒/命令包裹/tool_result;无 cwd 时从目录名兜底。opening/body 里粘贴的 token/密钥值会在**采集入库前自动打码**(`cfg.redact`,默认开;见 §3 util.redact)——变量名/代码引用保留,只抹「键=值」的值。

### codex
- 读:`~/.codex/state_5.sqlite` 的 `threads` 表(`cwd/title/first_user_message/created_at_ms/updated_at_ms/git_branch`)。`_find_db` 兼容 `state_5/state/state_4/state*.sqlite`。
- 产出:`kind=session`,意图=title 或 first_user_message;detail 含 **opening**=`first_user_message` 全文(封顶 1200,渲染同 claude)。
- 坑:sqlite 先 copy-to-temp(含 -wal/-shm)防锁;表名/版本变了要调 `_CANDIDATES`。

### cursor
- 读:`Cursor/User/globalStorage/state.vscdb` 的 `ItemTable['composer.composerHeaders']` → `allComposers[]`(name/createdAt/lastUpdatedAt/trackedGitRepos/filesChangedCount/lines±)。**只有元数据,无对话正文**(符合隐私决策)。
- 产出:`kind=session`,detail=`{start,end,files,add,del}`。
- 项目归属(`_project`):首选 `workspaceIdentifier.uri.fsPath`(打开会话时的工作区根,覆盖最广),次选 `trackedGitRepos[].repoPath`,两者都跳过临时 worktree(`/private/tmp/`、`/scratchpad/`、`/wt-`)。都无 → `"cursor"` 桶(无文件夹的临时对话,合理)。
- ✅ **已修(原「60/80 落 cursor 桶」)**:旧 `_project_from_repos` 只看 `trackedGitRepos`,而 360 个 composer 里仅 20 个有该字段;真实工作区在 `workspaceIdentifier.uri.fsPath`。改用它后实测 **79/80 正确归到真实项目**,仅 1 条为无文件夹对话。

### codebuddy(腾讯 coding-copilot;本地无历史)
- **已查清(2026-07)**:会话历史**不落本地**,三处本地存储实测全空 —— globalStorage 的 `interactive.sessions`=`[]`、专用 `codebuddy-sessions.vscdb` 无行、每个 `workspaceStorage/*/state.vscdb` 的 `history.entries`/chat memento=`[]`/`{}`。即 CodeBuddy 存服务端,git 脊柱已覆盖其产出。
- 采集器已探测这三处已知位置,有数据则汇总(结构待补映射),无则 log 一句返回 `[]`。
- 待办:仅当某机器/某版本确有本地会话时,按 codex/cursor 同构映射(TODO hook 在模块注释旁)。

### feishu(多维表格 / 需求池)
- 读:`cfg.feishu.bitables` 每张表 `bitable/v1/apps/{app_token}/tables/{table_id}/records` 分页全量。
- 过滤:**客户端**按 `person_field`(如"需求负责人",逗号分隔可多人)包含 `owner.feishu_name`;日期取 `date_field` 否则 `last_modified_time`,`< since` 丢弃。(飞书 filter 不支持人员字段,故客户端过滤。)
- 产出:`kind=requirement`,summary=标题+[状态]。
- 坑:应用须被加为该多维表格协作者;`token()` 用 env 凭证,进程内缓存。**目前 `feishu.enabled=false`,未跑通**(见 §8)。

### docs(各仓 .md 全文归档 + 索引)
- 读:每个配置仓递归扫 `*.md`(跳过 node_modules/dist/vendor 等,深度≤4)。抽标题(首个 `#`)+ 大纲(≤20)+ **全文**(封顶 200KB)。
- 日期:一次 `git log --all --name-only -- '*.md'` 拿每文件最近提交日期;无则 mtime。**不受 `since` 窗口限制**(全量索引)。
- 产出:`kind=doc, tool=docs`,`ref`=原文件绝对路径,detail=`{path,headings,repo,content}`。**不进日记**(render 跳过 `kind=doc`)。
- **全文归档(解决"不敢删")**:`render._write_archives` 把全文(打码)写进 `vault/notes/_archive/<repo>/<相对路径>`,带 `type: loom-archive` frontmatter。**永不裁剪**——entries 只 upsert 不 prune,删了源文件其条目仍在→归档仍写;即便清空 entries.jsonl,已落盘的归档文件也不动。**故删任何源 .md 都安全**(实测:删源+重建后归档全文仍在)。归档随 vault 上 GitHub、被 Basic Memory 检索。
- 检索:`loom search <词> --tool docs` 跨项目搜;标题/大纲/全文经 FTS `aux` 列(见 §3)。
- 坑:只认 `.md`;`_archive` 是派生镜像(live 文件每次 sync 刷新为当前版;已删源保留最后一版),`harvest_taxonomy`/`loom doc ls`/triage 都跳过它。

### notes(vault/notes/ 手动文档索引)
- 读:扫 `vault/notes/`(跳过 `_archive`)每个 `.md`。解析 frontmatter 标题/标签,取全文。
- 产出:`kind=note, tool=notes`,`project`=类目(相对路径首段,如 `attribution`/`inbox`),`ref`=文件路径,detail=`{path,tags,content}`。
- **补齐 `loom doc add` 闭环**:此前手动加的 doc 只在 vault(Basic Memory 可搜)、`loom search` 搜不到;有了本采集器,`loom search`(含 `--project 类目`)也能搜到手动加的文档。不进日记、不再归档(它们本就是 vault 原件)。
- 日期:frontmatter `date` 否则 mtime。跳过 `_archive`(那是 docs 源的全文镜像,避免重复索引)。

### ~~feishu_im~~(已退役)
- **决策**:loom 不再直接读 IM。「话题里 @ 机器人 → 总结 → 写多维表格」交给**独立飞书机器人**(它做实时事件订阅 + AI 总结 + 写表并带原消息回链);loom 只当作普通需求池表读回来。捕获(push)与聚合(pull)解耦,loom 的飞书 scope 收敛到仅 `bitable:app:readonly`。
- 已删:`collectors/feishu_im.py`、`REGISTRY` 注册、`config.feishu.im` 默认块、`loom feishu im on/off` 子命令。机器人蓝图见 `docs/loom-bot-design.md`。

---

## 5. 命令

```bash
loom init                       # 交互引导:名字/飞书名、探测+补 git 邮箱、扫仓、飞书凭证与需求池 URL
loom sync [--push] [--since]    # 采集全部源 → 渲染日记 → 提交 vault(--push 上云)。★日常就这条
loom collect --source <name>    # 单源采集:git|claude|codex|cursor|codebuddy|feishu|all
loom build                      # 只重渲染日记(不重新采集)
loom today                      # 打印今天的日记
loom search <词> [--project P] [--tool T] [--since D] [--until D] [--limit N]
                                # SQLite FTS5(trigram)检索:≥3 字符走 bm25 排序,<3 字符回退 LIKE 子串;
                                #   空词 + 过滤 = 按项目/工具/日期浏览。索引随采集重建、缺失/过期自动重建。
                                #   检索不只标题:FTS 的 aux 列还索引【文档大纲 / commit 正文 / AI 开场】。
                                #   (更强的语义检索仍可另接 Basic Memory,见 §9)

loom doc add <路径…> [--to 类目] [--tags a,b] [--title T] [--move] [--push]
                                # 临时/外来文档快速入库 notes/:自动补 frontmatter + 密钥打码;
                                #   默认进 notes/inbox/(先收后归类),--to 指定类目,目录会递归纳入。
loom doc ls                     # 列 notes/ 下所有文档
loom doc triage                 # 【AI 辅助归类】打印清单(现有类目/标签 + inbox 待分类文档头部,已打码)
loom doc triage --apply <tsv>   #   应用 AI 给的映射(每行 相对路径<TAB>类目<TAB>标签),移到类目 + 更新标签

loom repo add|rm|scan|ls [值]   # 增删 git 仓(scan <dir> 自动发现 .git 深度≤3)
loom feishu add <url>|rm|ls     # 增删需求池(URL 解析 app_token/table_id;缺 table 会追问)
loom identity add <邮箱/名>|ls   # 增补 git 身份(带 @ 入 emails 否则入 names)
loom source enable|disable <name>
```

**AI 辅助归类的闭环**(捕获 → AI 提议 → 人批 → loom 执行):
1. `loom doc add <散落文档…>` → 全进 `notes/inbox/`(自动 frontmatter + 打码)。
2. `loom doc triage` → 打印清单:**现有类目/标签词表**(约束 AI 分进已有体系,别乱造)+ 每篇待分类文档的头部(已打码)。
3. 把清单交给已接入的 AI(Claude Code / Cursor via MCP,或直接问我)→ 它回一份 TSV(`路径<TAB>类目<TAB>标签`)。
4. `loom doc triage --apply <tsv> [--push]` → loom 移文件到类目 + 更新 frontmatter 标签。
> 设计取舍:loom **不内置 LLM 调用**(零依赖、隐私灵活)——AI 能力借已接入的 MCP 会话,是「AI 提议、人确认、工具执行」而非静默自动归档。同类开源方案作参考:**paperless-ngx + paperless-ai**(扫描件 DMS,本地 Ollama 打标)、**llama-fs / Local-File-Organizer**(LLM 盯 Downloads 自动分流)、**Karakeep**(AI 多标签收藏)。它们都是独立栈;loom 复用其**模式**(dropzone + AI 建议 + 多标签 + 本地/打码),不引入其栈。

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

一句话:把「个人本地拉取」升级为**托管多租户机器人**——**任何人**在飞书话题 @ 机器人一句,它读上下文、为其**建/复用仅他可读的多维表格**记事并回执。完整蓝图(运行时/API 时序/权限模型/AI 接入点/分阶段路线)见 **`docs/loom-bot-design.md`**。它是 loom 的姊妹组件:**机器人负责实时捕获+总结+写多维表格(带原消息回链),loom 只负责拉取式读表**——两侧以多维表格为契约解耦。(原 loom 内 `feishu_im` 采集器已退役,见 §4。)

---

## 8. 待办 / 开放项(逐条含状态)

1. **飞书需求池读取未跑通**(代码就绪,gated)。需:
   - `~/.loom/.env` 填 `FEISHU_APP_ID/FEISHU_APP_SECRET`;
   - 应用被加为需求池多维表格**协作者**;scope 仅需 `bitable:app:readonly`;
   - 然后 `loom feishu add <url>` + 把 `feishu.enabled` 置 true,用一张表实拉验证(可用已知的「迪仔负责」条数交叉校验)。
2. **独立飞书机器人(打点写表)** — 姊妹组件,尚未实现。「话题 @ 机器人 → 总结 → 写多维表格(带原消息回链)」。蓝图见 `docs/loom-bot-design.md`;写表的字段名(负责人/日期列)须对齐上面 `feishu` collector 的 `person_field`/`date_field`。
3. ✅ **cursor 项目归属修正(已完成)**:改用 `workspaceIdentifier.uri.fsPath`,79/80 正确归属(见 §4 cursor)。
4. **云端 / 定时 / 检索底座**:
   - ✅ **云端已建**:私有仓 `github.com/dizai6266/loom-vault`,`main` 跟踪 `origin/main`,`loom sync --push` 已验证上云。
   - **每日(待)**:crontab `0 19 * * * /opt/homebrew/bin/loom sync --push`(或 launchd);
   - **Basic Memory(待)**:`uvx basic-memory project add loom ~/.loom/vault`(指向仓根,日记 + `notes/` 一起检索)+ 各 AI 工具接 MCP。
6. **散碎文档收编**:vault 已分区 —— `journal/`(自动,勿手改)vs `notes/`(手写文档,loom 不碰)。把原先散落的笔记/设计迁进 `vault/notes/` 即可随 vault 上云 + 被 Basic Memory 检索。
5. ✅ **codebuddy 已查清(无本地历史)**:三处本地存储实测全空,存服务端;采集器已探测已知位置并优雅降级(见 §4 codebuddy)。仅当未来某机器有本地会话再补映射。

---

## 9. 部署 + Basic Memory 接入

**一键部署** `./install.sh`:
1. 校验 python3;
2. 软链 `bin/loom` 到可写且在 PATH 的目录(`/opt/homebrew/bin` → `/usr/local/bin` → `~/.local/bin`);
3. 跑 `loom init`(引导配置);
4. 跑一次 `loom sync`;
5. 末尾打印云端 / cron / Basic Memory 的可选命令。

**各 AI 工具接 Basic Memory MCP**(共享同一批 vault markdown):
- 先 `uvx basic-memory project add loom ~/.loom/vault`(指向仓根:日记 + `notes/` 手写文档一起检索);
- Claude Code:`claude mcp add basic-memory -- uvx basic-memory mcp`;
- Cursor:`~/.cursor/mcp.json` 加 `{"mcpServers":{"basic-memory":{"command":"uvx","args":["basic-memory","mcp"]}}}`;
- Codex:`~/.codex/config.toml` 加 `[mcp_servers.basic-memory]\ncommand="uvx"\nargs=["basic-memory","mcp"]`。
(v1 曾在 `~/worklog/adapters/` 放过这些片段;v2 尚未在代码仓固化 adapters 目录——如需可补。)

---

_最后更新:退役 feishu_im(读 IM 归独立机器人)+ 修 cursor 项目归属。维护时改代码后同步更新本文对应小节。_
