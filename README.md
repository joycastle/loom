<div align="center">

<img src="assets/logo.svg" width="116" alt="loom" />

# loom

**把散落各处的工作痕迹 —— git 提交 · AI 对话 · 文档 · 代码 · 数据 —— 织成一本可检索、可关联的本地台账**

一份扁平真相 → 派生按天日记 · 全文检索 · 主题关联 · 私有云备份;每条带**回链**,一跳回原文。

<br>

![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white)
![dependencies](https://img.shields.io/badge/dependencies-0-5AA9A0)
![stdlib only](https://img.shields.io/badge/stdlib-only-5AA9A0)
![tests](https://img.shields.io/badge/tests-152%20passing-3FB950)
![local-first](https://img.shields.io/badge/private--first-E0A84E)
[![license](https://img.shields.io/badge/license-MIT-8A93A3)](./LICENSE)

![Claude Code](https://img.shields.io/badge/Claude_Code-8A2BE2?logo=anthropic&logoColor=white)
![Codex](https://img.shields.io/badge/Codex-000000?logo=openai&logoColor=white)
![Cursor](https://img.shields.io/badge/Cursor-1a1a2e)
![CodeBuddy](https://img.shields.io/badge/CodeBuddy-0052d9)
![pi](https://img.shields.io/badge/pi-coding_agent-5AA9A0)
![OpenCode](https://img.shields.io/badge/OpenCode-1a1a1a)

**简体中文** | [English](./README.en.md)

[🚀 快速开始](#-快速开始) · [📸 界面](#-界面预览loom-serve) · [🧵 设计](#-为什么是这样) · [⌨️ 命令](#️-常用命令) · [🛡️ 数据与安全](#️-数据与安全)

<br><img src="assets/banner.svg" width="100%" alt="loom banner" />

</div>

---

**loom(织机)** 把散落在多个 git 仓、多个 AI 工具会话(Claude / Codex / Cursor / CodeBuddy / pi / OpenCode)、文档、代码、数据里的**你自己**的工作痕迹,归一成一份扁平记录,再织出可检索、可按主题追溯、可私有云备份的台账。**纯标准库 Python,零第三方依赖**——clone 即用。

## 🚀 快速开始

装 loom = 两样东西:**`loom` 命令**(CLI,真正干活的)+ **loom 技能**(装进你的 AI 助手,让它会用 `loom`)。挑一种:

**① Claude Code —— 装成原生插件(最快)** · 在 Claude Code 会话里输入斜杠命令(不是终端):

```
/plugin marketplace add joycastle/loom
/plugin install loom@joycastle
```

**② Codex / Cursor / 任意终端 —— 一行装** · 装好 `loom` 命令 + 把技能装进在场的所有 AI 助手,零 pip、零打包:

```bash
curl -fsSL https://raw.githubusercontent.com/joycastle/loom/main/install.sh | sh
```

**③ 手动**:

```bash
git clone https://github.com/joycastle/loom.git ~/Documents/loom && cd ~/Documents/loom && ./install.sh
```

装完:`loom sync` 采集,`loom serve` 浏览器看管理页。日常就一条 `loom sync`(上云加 `--push`)。

> **想让 AI 帮你把历史资料也整理好?** `git clone` 后用你的 AI 助手打开这个目录,说一句「**读 ONBOARDING.md,带我配置并整理历史**」。它会自动读到入口文件(`AGENTS.md` / `CLAUDE.md`),照 [`ONBOARDING.md`](./ONBOARDING.md) 走完:配置 → 首次采集 → 收编散落文档/数据 → 私有云备份 → 主题分类 → 日常。

## 📸 界面预览(`loom serve`)

> 本地零依赖浏览页,仅 127.0.0.1,纯管理无聊天。下图 `loom serve` 实拍,**虚构演示数据**。

<img src="docs/shots/dashboard.png" width="100%" alt="首页工作台" />

| 台账(全文检索 + 筛选 + 分页) | 日历(月历热力 + 当天全景) | 主题(DAG,点主题看「一件事」) |
|:---:|:---:|:---:|
| <img src="docs/shots/ledger.png" alt="台账" /> | <img src="docs/shots/calendar.png" alt="日历" /> | <img src="docs/shots/topics.png" alt="主题" /> |

## 🧵 为什么是这样

loom 的价值不在"又一个笔记工具",而在几个刻意的设计取舍(完整技术细节见 [`docs/loom_showcase.html`](./docs/loom_showcase.html) · [产品导览](https://htmlpreview.github.io/?https://github.com/joycastle/loom/blob/main/docs/loom_tour.html)):

- **扁平存储,按需成视图** —— 只按稳定 `id` 存一份真相(`entries.jsonl`);"按天/按主题/按项目"都是同一份数据的不同切法,加一次多轴皆可见。
- **只存「摘要 + 回链」** —— 每条留最值钱的短文本 + 一个 `ref` 指针,全文/diff/原件留原地;上千条依然轻,每条可溯源。
- **入库前打码** —— token / 密钥 / webhook 写入前就抹掉(只抹值、留变量名);凭证只进 `~/.loom/.env`(chmod 600),绝不进任何仓。
- **主题层是 DAG** —— 条目只打叶子标签,层级写在主题页(可多父);查询上卷整棵子树,把一件事的对话+提交+文档+数据缝成一条决策链。
- **日报 / 会话摘要是 AI 合成的派生产出** —— 不是采集源;`loom report gen` 喂 AI 写日报,`loom session gen` 读会话问答写准标题+可检索摘要,存独立 sidecar、重采不丢。

## ⌨️ 常用命令

```bash
loom init                      # 交互引导:身份 / 扫仓 / 飞书
loom sync [--push]             # 采集全部源 → 渲染 → 提交(--push 上云)。日常就这条
loom serve [--port 8787]       # 本地管理页(仅 127.0.0.1):首页/台账/日历/主题/日报 + 设置
loom search <词> [--tool T] [--since D]   # 全文检索(中文子串;空词 + 过滤 = 浏览)
loom topic ls | show <主题>    # 主题树 / 上卷查一件事的全景
loom note "<文本>" [--to 类目] # 随手信息入库(--update <关键词> 追加到已有条目)
loom report gen <日期> | set   # 日报:AI 合成 → 回库
```

完整命令(`doc add` / `data add` / `session` / `deprecate` / `repo` / `identity` / `source` 等)与参数见 [`docs/`](./docs/) 或 `loom <命令> -h`。

## 🛡️ 数据与安全

```
多股采集来源                归一 + 打码          派生
git · Claude/Codex ┐                        ┌ 全文检索 FTS5(中文子串)
pi · OpenCode      ├─► loom ─► entries ────►│ 按天日记 · 主题 DAG(可上卷)
Cursor · CodeBuddy │   (归一·打码)  一份真相  │ 日报(AI 合成)
仓库文档 · 数据 · 散信息 ┘                    └ 私有云备份(git push)
```

- **原始数据不上云** —— 只有 `vault/` 的 markdown 走 `loom sync --push` 到**你自己的**私有 git remote;`entries.jsonl` 全文、原始 `detail`、`_data/` 的 csv/xlsx、`.env` 由代码强制的 `.gitignore` 留本地。
- **代码 / 数据物理隔离** —— 本仓 = 共享代码(可公开);你的实例在 `~/.loom/`(`init` 生成、不入代码仓:`config.json` 身份/源开关、`.env` 凭证、`data/` 归一条目+FTS 索引、`vault/` 日记+文档→独立私有仓)。`LOOM_HOME` 可覆盖 `~/.loom`。
- **诚实的取舍** —— 检索是关键词非语义;飞书打点走[独立机器人](./docs/loom-bot-design.md)不在 loom 内读 IM;日报由外部 AI 合成,loom 只出料。

## 许可

[MIT](./LICENSE) —— 随便用、随便改、随便分发,不担保。

---
**给拿到本仓的 AI 助手**:先读 [`AGENTS.md`](./AGENTS.md)(或 [`CLAUDE.md`](./CLAUDE.md));数据整理照 [`ONBOARDING.md`](./ONBOARDING.md) 执行;加采集器等扩展见 [`docs/`](./docs/)。
