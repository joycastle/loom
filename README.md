<div align="center">

<img src="assets/logo.svg" width="116" alt="loom" />

# loom

**把散落各处的工作痕迹 —— git 提交 · AI 对话 · 文档 · 代码 · 数据 —— 织成一本可检索、可关联的台账**

一份扁平真相 → 派生按天日记 · 全文检索 · 主题关联 · 私有云备份;每条带**回链**,一跳回原文。

<br>

![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white)
![dependencies](https://img.shields.io/badge/dependencies-0-5AA9A0)
![stdlib only](https://img.shields.io/badge/stdlib-only-5AA9A0)
![tests](https://img.shields.io/badge/tests-112%20passing-3FB950)
![single-user](https://img.shields.io/badge/private-first-E0A84E)
[![license](https://img.shields.io/badge/license-MIT-8A93A3)](./LICENSE)

[**⚡ 快速落地**](#-5-分钟落地让你的-ai-助手带你走推荐) · [🎨 设计亮点](#-设计亮点为什么是这样) · [🧵 主题层](#主题层把散痕迹聚成一件事) · [⌨️ 命令](#命令) · [🤖 给 AI 助手](./AGENTS.md)

</div>

---

> 🧵 **loom(织机)** 把散落在「多个 git 仓 + 多个 AI 工具会话(Claude / Codex / Cursor / CodeBuddy)+ 文档 / 代码 / 数据 / 飞书」里的
> **你自己**的工作痕迹,自动归一成一份扁平记录,再织出可检索、可按主题追溯、可私有云备份的台账。纯标准库 Python,**零第三方依赖**。

## ⚡ 5 分钟落地:让你的 AI 助手带你走(推荐)

loom 自带**跨工具的 AI 入口文件**,不挑助手。你几乎不用读文档——把项目交给 AI,它自己知道怎么带你。

```bash
git clone https://github.com/joycastle/loom.git ~/Documents/loom
```

然后**用你惯用的 AI 编码助手打开这个目录**,说一句:

> **「读 ONBOARDING.md,带我一步步完成配置,并把我的历史资料整理好。」**

它会自动读到本仓为它准备的规则文件,照 [`ONBOARDING.md`](./ONBOARDING.md)(一份**面向 AI 的执行剧本**)带你走完:
**A 环境配置 → B 首次采集 → C 收编散落的文档/代码/数据 → D 私有云备份 → E 主题层完整分类 → F 日常一条命令**。

| 你的助手 | 自动读取的入口 | 状态 |
|---|---|---|
| Cursor / Codex / Copilot / Windsurf / Gemini / Aider / Zed | [`AGENTS.md`](./AGENTS.md)(跨工具开放标准) | ✅ 原生识别 |
| CodeBuddy | 无 `CODEBUDDY.md` 时**自动全量加载 `AGENTS.md`** | ✅ |
| Claude Code | [`CLAUDE.md`](./CLAUDE.md)(`@import AGENTS.md`) | ✅ |
| Cursor(额外保险) | [`.cursor/rules/loom.mdc`](./.cursor/rules/loom.mdc) | ✅ |

> 不想用 AI?直接 `cd ~/Documents/loom && ./install.sh`(装 CLI + 交互引导配置 + 首次同步),
> 之后日常只需一条 `loom sync --push`。

---

## 🎨 设计亮点(为什么是这样)

loom 的价值不在"又一个笔记工具",而在几个刻意的设计取舍。看**成果与完整设计说明** →
在 AI 助手里打开项目并让它渲染 `loom_showcase.html`,或读下面速览:

- **① 扁平存储,按需成视图。** 只按稳定 `id` 存一份真相(`entries.jsonl`),
  "按天""按主题""按项目""按时段"全是对同一份数据的**不同切法**。加一次,多轴皆可见——绝不重复录入。

- **② 只存「摘要 + 回链」,全文留原处。** 每条记录留最值钱的短文本(标题、提问、提交理由)+ 一个 `ref` 指针;
  完整对话 / 整个 diff / 原始文件都留在原地,搜到后一跳还原。**库塞得下上千条却依然轻,每条都可溯源。**

- **③ 入库前自动打码。** token / 密钥 / webhook 在采集**写入前**就被抹掉(只抹值、留变量名),推云端不泄露。
  凭证只进 `~/.loom/.env`(chmod 600),**绝不进任何仓**。

- **④ 分层上云:知识层上云,原始资料留本地。** 数据文件蒸馏成可检索的"数据卡"(列/统计/样例/血缘)上云;
  原始 csv/xlsx 大文件与敏感明细 `gitignore` **留本地 `_data/`**,不出机器。

- **⑤ 主题层是 DAG,把散痕迹缝成「一件事」。** 条目只打最细的**叶子**标签,层级写在主题页(`parent` 可多 = 多父);
  查询时**上卷整棵子树**。关键词搜"素材"给你一锅粥;主题 `show` 精确到那件事的一条决策链(对话+提交+文档+数据)。

- **⑥ 日报 / 会话摘要是 AI 合成的产出。** `loom report gen` 聚合当天真实痕迹喂 AI 写日报;
  `loom session gen` 读某天会话的**问 + 答**原文,让 AI 写出准确标题 + 可检索摘要,回填到那条会话上
  ——补上"长会话首问含糊、答案侧内容搜不到"的洞。二者都是**派生**,不是采集源,存独立 sidecar、重采不丢。
  > 真实一例(全库 129/129 会话已生成):首问 `拉取最新代码了吗` → ✦标题
  > `梳理 Google Ads Asset 数据从 DWD 到 DWS 的全链路 ETL 流程`;连答案侧才有的 `auto_stop_mins` 等词都能搜到。

- **⑦ 零依赖 · 纯标准库 · 112 单测全绿。** clone 即用,不装环境;打码/路径穿越/FTS 召回/原子写/主题上卷都有端到端测试守护。

---

## 架构一图

```
6 股采集来源                    归一 + 打码            派生
─────────────                 ──────────            ──────────────
git 提交        ┐                                  ┌ 全文检索 FTS5(中文子串)
Claude 会话     │                                  │ 按天日记(markdown)
Cursor 会话     ├──►  loom  ──►  entries.jsonl ──► ├ 主题关联(DAG,可上卷)
Codex 会话      │   (归一·打码)     一份真相         │ 日报(AI 读库合成,非采集源)
仓库文档 .md    │                                  └ 私有云备份(git push)
数据·代码·散信息 ┘
```

## 代码 / 数据分离(两个私有仓,物理隔离)

```
<本仓>/                     共享代码(clone 后一键装,可公开分享设计)
  loom/  bin/loom  install.sh  config.example.json
  AGENTS.md  CLAUDE.md  ONBOARDING.md   ← 给 AI 的入口 + 执行剧本

~/.loom/                你自己的实例(init 生成,不入代码仓)
  config.json              身份 / 仓 / 需求池 / 源开关(命令管理)
  .env                     FEISHU_APP_ID/SECRET(gitignored,绝不进 vault)
  data/entries.jsonl       归一化条目(可再生)
  data/index.sqlite        FTS5 检索索引(可删可重建)
  vault/journal/*.md       日记 + notes/ 文档 → 独立 git 仓 → push 私有 GitHub
```
可用环境变量 `LOOM_HOME` 覆盖 `~/.loom`。

## 安装(手动路径)

```bash
git clone https://github.com/joycastle/loom.git ~/Documents/loom
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

loom doc add <路径…> [--to 类目] [--tags a,b] [--move] [--push]
                               # 一键入库 notes/(打码;默认 inbox/)。docx/pdf 自动提取文本成可检索 .md + 留原件
loom data add <csv|xlsx…> [--to 主题] [--kind source|derived] [--from 上游…] [--code a.sql b.py] [--used-by 文档]
                               # 数据→数据卡(列/统计/样例,上云可检索)+ 原始入 _data/(本地不上云)+ 绑代码/血缘
loom note "<文本>" [--to 类目] [--tags a,b]   # 随手/外部散信息入库(打码+可检索+可主题打标)
loom report import <日报.xlsx> | gen <日期> | set   # 日报:导历史种子 / AI 合成 / 回库
loom session gen <日期> | set <日期> | ls           # AI 会话摘要:读当天问+答→写准标题+可检索摘要
loom topic ls | gather <主题> | apply | show <主题>  # 主题层:看/聚/打标/上卷查一件事
loom deprecate <notes相对路径> [--mark]        # 过时/判错内容移进 _attic(移出检索,git 历史仍在)
loom repo add|rm|scan|ls [值]  # 灵活增删 git 仓(scan 自动发现)
loom feishu add <url>|rm|ls    # 增删需求池(URL 解析 app_token/table_id)
loom identity add <邮箱/名>|ls  # 增补 git 身份
loom source enable|disable <name>
```

## 采集来源(从哪读)

下表是**采集器从哪读、读到什么**;每种数据**怎么处理、怎么取舍、进哪些检索字段**见下一节。

| 源 | 取自 | 内容 |
|---|---|---|
| git | 所有配置仓 `git log --all`(按你的邮箱/名字过滤) | 提交(标题 + **正文** + 每文件改动;整 diff 走回链) |
| claude | `~/.claude/projects/*/*.jsonl` | 会话:意图标题 + **开场提问 + 当天全部提问**(按天拆分;完整对话走回链) |
| codex | `~/.codex/state_5.sqlite` threads | 会话:cwd/标题/**开场提问全文** + 时间(两端归属) |
| cursor | `Cursor/.../globalStorage/state.vscdb` composer 头 | 会话:标题 + 改动量(无消息级正文) |
| codebuddy | `CodeBuddy/.../state.vscdb` | 占位;本地无缓存时由 git 兜底 |
| docs | 各配置仓里的 `*.md` | 全文归档进 `notes/_archive/`(打码、永不裁剪 → **删源也不丢**)+ 标题/大纲索引;不进日记 |
| notes | `vault/notes/`(手动加的) | 把 `loom doc add`/`note` 的内容纳入 `loom search`(闭环);跳过 `_archive`/`_attic` |
| feishu | 多维表格 `bitable/v1 list records` | 需求 / 记事:按「负责人=你」+ 日期筛 |

隐私:vault 只存**元数据 + 意图/正文**,不存完整对话;token/密钥值在**采集入库前自动打码**(`redact`,默认开),推云端不泄露。

## 每种数据:怎么处理 · 存成啥 · 取舍

统一原则:**只存摘要 + 回链 + 可检索文本,全文 / 整 diff / 原始文件留原处按需回溯**;文本知识层上云,重 / 敏感的留本地。

| 类型 | 怎么处理 | 存成啥 · 取舍 | 进检索 |
|---|---|---|---|
| **git 提交** | 解析标题 + 正文(为什么改)+ 每文件增删;哨兵分隔正文与 numstat;重命名取新路径;同题同改动量去重 | body≤4000、file_list≤40;**不存完整 diff**(ref=hash,`git show` 看全)——库轻又留住决策理由 | summary · body |
| **Claude 会话** | UTC→本地,**按天分桶**(跨天长会话拆到每天);跳过命令/工具/压缩摘要;取当天首个真实提问作标题 | opening + **当天全部提问** body≤8000;只索引**你的提问**,ref 指原 jsonl | summary · opening · body · *digest* |
| **Cursor / Codex 会话** | 先把库拷到临时目录**避开锁**;只有会话级时间→按**开始日 + 最后活跃日**两端归属 | 标题 + 改动量/分支 + opening;**拿不到消息级文本**(工具存储限制,中间天可能漏,已在码里注明) | summary · opening |
| **仓库文档 .md** | 取 H1 + 大纲 + 全文(≤200k);全文快照写进 `notes/_archive`,**永不裁剪** | headings + content;**删源也不丢**;不进按天日记(量大),只留最新版(旧版在 git 历史) | headings · content |
| **数据 csv / xlsx** | 纯标准库解析(csv 模块 / xlsx 用 zip+xml,含**日期序列号还原**)→ 蒸馏"数据卡" | **数据卡**(列/类型/统计/前5行样例 + 血缘)上云;**原始文件拷进 `_data/` 留本地**、gitignore | 数据卡(schema+样例+血缘) |
| **代码 sql / py 等** | 入库**打码**(只抹值不动变量名);日期优先级 frontmatter > 文件名日期 > mtime | 原样存(可检索);无可靠日期的标 `dated=False`**不塞进某天日记**(免得虚胖导入当天) | 代码全文 |
| **日报** | 派生 · **AI 合成**:聚合当天真实痕迹 → AI 写三段;同天多条合并不覆盖 | id=report:日期(幂等);渲染进当天日记**顶部**作总述。**不是采集源** | 三段全文 |
| **AI 会话摘要** | 派生 · **AI 合成**:读当天会话**问 + 答**原文 → AI 写准标题 + 摘要 | 存独立 sidecar,每次 sync **叠加回条目(重采不丢)**;日记里该会话标题带 ✦ | 标题 · 摘要 |
| **散信息 / 飞书表** | `loom note` 或薄脚本喂 `intake.note`(**非专用采集器**)→ 打码 + 补 frontmatter | 统一成 note → `notes/inbox`,和文档同管线:进检索 / 进日记 / 可主题打标 | 正文 |

**可检索字段词典**(一条 entry 的 `detail` 里因源而异的文本槽,标 ◆ 进 FTS):

| 字段 | 含义 | 谁有 | 检索 |
|---|---|---|---|
| `summary` | 一句话标题 / 摘要 | 全部 | ◆ |
| `opening` | 会话开场首问全文 | AI 会话 | ◆ |
| `body` | 长正文(git 提交正文 / 当天全部提问) | git · claude | ◆ |
| `headings` | 文档大纲(各级标题) | 文档 | ◆ |
| `content` | 全文快照(≤10 万字) | 文档 · 代码 · 数据卡 · 散信息 | ◆ |
| `digest` | AI 会话摘要(读问+答生成,可选) | AI 会话 | ◆ |
| `ref` | 回链指针(hash / 路径),点回原文看全 | 全部 | ○ 只溯源 |

## 主题层:把散痕迹聚成「一件事」

一件事的痕迹散在四类里(对话 / 提交 / 文档 / 数据),关键词搜"素材"给你一锅粥。主题层把它们缝成一条决策链。

**机制(三层,各司其职):**
- **条目只打最细的「叶子」标签** —— 存 `~/.loom/data/topic_map.json`(条目 id → 叶子主题);**条目本身不记层级**。
- **层级写在「主题页」** —— `vault/notes/topics/<主题>.md` 的 frontmatter `parent:`(**列表 = DAG,可多父**);
  移动 / 重挂子树只改这一处,不碰任何条目。
- **查询时「上卷」整棵子树** —— `loom topic show 数仓建设` 递归收集所有后代主题的成员(带环保护),
  一次看全一个域;`loom topic show 素材匹配重构` 只看那一件事。

**为什么这样设计:**
- **叶子 + 页层级分离**:重组主题树只改主题页,条目标签保持稳定,不用批量改条目。
- **DAG 多父**:跨两个域的东西(如"净额"既属 BF三方支付、又被素材匹配重构引用)不必二选一,两个 `parent` 都写;
  查询任一祖先都能上卷到它。同一条记录照常出现在它那天的日记里。

**怎么分类(核心原则:看内容,别靠关键词):**
关键词 / 正则会**系统性过采**("cohort / 周报 / 素材"一按就把整条卷进来)。正确做法是**闭集 + 逐条 AI 判 + 对抗复核**:
1. `loom topic gather` → 输出现有主题 + 待归类条目(带内容片段 / 会话正文);
2. **逐条读内容**判到骨架叶子——长会话某天首句可能是"继续",要读当天全部提问、必要时顺 `ref` 读原始 transcript;
3. `loom topic apply --file <映射.tsv>`(每行 `条目id<TAB>叶子1,叶子2`,缺失主题自动建页);
4. **对抗复核**剔除误挂,再**逐主题 `loom topic show` 读成员核对**。

> **必守纪律**(反复踩坑换来):日报不入单一主题(多主题叙事会污染);会话只在当天明显单一时才分;
> 拿不准就不分(宁缺勿滥);主题页不自指;展示只用 `topic show` 能复现的真实数字。1000+ 条用分类工作流并行跑。
> 详见 [ONBOARDING.md](./ONBOARDING.md) 阶段 E。

**真实骨架示例**(**某数据仓库工程师**的真实工作**脱敏示例**,仅作参考——换个人跑会按各自工作长出完全不同的树):
```
数仓建设(伞) ├ 素材归因 › 素材匹配重构 › serial兜底 ├ 成本分摊 ├ BF三方支付 › 净额*/三方对账
              ├ Cohort回收 ├ 渠道再归因 ├ 数仓底座
分析排查      ├ 反作弊 › 作弊排查 / 假单检测 / 渠道拉黑 ├ 临时排查
报表周报 · 受众运营 · loom工具开发 › loom-飞书drive
                                   * 净额 = DAG 多父(BF三方支付 + 素材匹配重构)
```

## 一次 sync 的六步

`① 采集`(各源读近 N 天,一个源崩不掀翻全局)→ `② 打码`(入库前抹 token/密钥/webhook)→
`③ upsert`(按 id 合并,原子写)→ `④ 建索引`(从真相重建 FTS,可删可再生)→
`⑤ 渲染`(生成日记,手写笔记区永不覆盖)→ `⑥ 推云`(vault git push,原始数据留本地)。

## 已知边界(诚实的取舍)

- **检索是关键词,不是语义** — "cohort" 召不回"留存";语义检索要向量模型,会破坏零依赖,暂不上。
- **只 Claude 能逐条拆会话** — Cursor/Codex 无消息级文本,只能标题级 + 两端归属。
- **助手回答默认不进检索** — 采集只索引你的提问;需要时 `loom session gen` 让 AI 读问+答补摘要。
- **全量重建** — 每次 sync 全量重扫;单人无感,超大历史才需增量。
- **AI 分类 / 摘要非全自动** — 闭集 + 人过目 + 审计控准,不图快(见 ONBOARDING 阶段 E)。

### 飞书打点走独立机器人(不在 loom 内读 IM)

loom 只做**拉取式读多维表格**这一条飞书链路(scope 仅需 `bitable:app:readonly`)。
「在话题里 @ 机器人 → 总结后写进多维表格」由一个**独立的飞书应用(机器人)**负责,它订阅消息事件、AI 总结、写入多维表格(带**原消息链接**回链);loom 随后当作普通需求池表读取。这样捕获(实时 push)与聚合(loom 拉取)彻底解耦。完整蓝图见 `docs/loom-bot-design.md`。

## 云端 + 检索底座

```bash
cd ~/.loom/vault && gh repo create loom-vault --private --source=. --remote=origin --push
# 之后 loom sync --push 自动上云

uvx basic-memory project add loom ~/.loom/vault   # 日记 + 手写文档一起语义检索
# 各 AI 工具接 Basic Memory MCP:见 adapters(claude/cursor/codex 的 mcp 配置)
```

## 扩展新采集器

在 `loom/collectors/` 加 `xxx.py`,实现 `collect(cfg, since) -> [entry]`,在 `collectors/__init__.py` 注册即可。
条目 schema:`{id, date, ts, project, tool, kind, summary, ref, detail}`。

## 许可

[MIT](./LICENSE) —— 随便用、随便改、随便分发,不担保。

---
**给拿到本项目的 AI 助手**:先读 [`AGENTS.md`](./AGENTS.md)(或 `CLAUDE.md`),首次上手照 [`ONBOARDING.md`](./ONBOARDING.md) 执行。
