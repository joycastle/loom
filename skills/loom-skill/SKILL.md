---
name: loom
description: 同步/检索个人跨工具成果台账 loom。当用户想「记录今天做了什么」「同步 loom」「查我以前/某天/某件事做过什么、结论是什么、相关文档/数据在哪」「生成日报/周报/绩效素材」时使用;先用它查历史,别只翻当前仓。
---

# loom 技能

我有一个跨项目的个人工作台账 **loom**(CLI 已在 PATH)。它把散在多个 git 仓、多个
AI 工具会话(Claude / Codex / Cursor / CodeBuddy)、文档 / 代码 / 数据 / 飞书需求池里的
**本人**工作,逐日缝成一份可检索的 markdown 台账,并派生出检索索引、按天日记、主题关联、
私有云备份。

**当我问到「我之前/某天/某件事做过什么、结论是什么、相关文档/数据在哪」这类历史问题时,
先用它查,别只翻当前仓。**

## 查历史(最常用)

```bash
loom search <关键词> [--project P] [--tool T] [--since D]   # 全文检索(中文子串可用)
loom topic ls                       # 主题树(数仓建设/反作弊/素材归因…)
loom topic show <主题>              # 一件事的全景:相关对话+提交+文档+数据
loom today                          # 今天的日记
```

命中条目都带 `ref` 回链(git hash / transcript 路径 / 文件);需要细节就顺着回链读原文。

## 同步与单源采集

- **同步**:`loom sync`(采集全部源 → 渲染日记 → 提交)。上云再加 `--push`。
- **单源**:`loom collect --source git|claude|codex|cursor|feishu`。
- **增删配置**:`loom repo add|scan <dir>`、`loom feishu add <url>`、`loom identity add <邮箱>`。

## 记录范式

- **新事** → `loom note "<内容>" [--to 类目]`
- **进行中的事状态变了** → `loom note --update <关键词> "<更新内容>"`(追加到已有条目,不新建)
- 写日报/总结时先读当天日记 `~/.loom/vault/journal/$(date +%Y-%m-%d).md`,再对不上进度的
  条目用 `--update` 补最新状态。

## 生成日报 / 周报 / 绩效素材

先 `loom sync`,再读 `~/.loom/vault/journal/` 下相应日期的 md,按需归纳。每条带 commit hash /
transcript 路径 / 需求链接回链,可回溯原文。

## 数据在哪

- 用户数据在 `~/.loom/`:配置 `config.json`、凭证 `.env`、原始数据 `data/`、日记 vault 在
  `~/.loom/vault/journal/*.md`(可直接读)。
- 代码/文档在公开仓(github.com/joycastle/loom)。

## 纪律

- `~/.loom/.env` 是凭证(飞书等),**不读、不引用、绝不入库**。
- 向台账写入(`loom note`、`loom doc add` 等)或做不可逆/外发操作(删除、移动、`git push`、
  对外分享)**前先向用户确认**。
- vault 只存元数据 + 意图标题,不存完整对话、不含密钥;原始数据(csv/xlsx)留本地不上云。
- 只抓 `~/.loom/config.json` 里配置了身份的记录;加仓/加身份改 config(或用子命令)。
- 给某天补「为什么/结果」:直接在对应 md 的「手写区」哨兵下方追加,`loom sync` 不会覆盖。
