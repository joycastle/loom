# AGENTS.md — 给 AI 编码助手的项目指引

> 跨工具开放标准文件。Codex / Cursor / GitHub Copilot / Windsurf / Gemini / Aider / Zed
> 原生读取;**CodeBuddy** 在无 CODEBUDDY.md 时自动全量加载本文件;**Claude Code** 见 CLAUDE.md。

## 这是什么
**loom** —— 单人、零依赖(纯标准库 Python)的跨来源工作台账:采集 git 提交 / AI 对话
(Claude·Cursor·Codex·CodeBuddy·pi·OpenCode)/ 文档 / 代码 / 数据 / 日报,归一成一份扁平记录,派生出
检索索引、按天日记、主题关联、私有云备份。
- **代码**在本仓;**用户数据**在 `~/.loom/`(config/.env/data/vault),两者物理分离。
- 命令:`loom sync | search | doc add | data add | note | report | session | topic | deprecate | init`。

## ⭐ 首次上手 / 整理历史 → 读 ONBOARDING.md
如果用户是**刚拿到本项目**、要你带他完成配置并把历史资料整理好,
**打开 [ONBOARDING.md](./ONBOARDING.md) 并逐步执行**——那是一份面向 AI 的执行剧本
(环境配置 → 首次采集 → 收编散落资料 → 私有云备份 → 主题层完整分类 → 日常)。

## 全程铁律(任何操作都遵守)
1. **不可逆 / 外发操作先向用户确认**:删除、移动、`git push`、对外分享。
2. **凭证只进 `~/.loom/.env`(chmod 600),绝不写入任何仓**;采集内容入库前已自动打码。
3. **原始数据不上云**:csv/xlsx 等留本地 `_data/`(gitignore),只有文本知识层进私有云。
4. **分类/归类看内容,别图快**:AI 主题分类要读条目实际内容(不是标题/首句),关键词会
   系统性过采;大规模分类用"逐条判 + 对抗复核",拿不准不硬塞,分完逐主题核对。详见 ONBOARDING.md。
5. 改动代码后跑 `python3 -m pytest tests/test_loom.py`(纯标准库,零依赖)。
