---
name: loom-daily-report
description: "Generate and write back AI-authored loom daily reports from real collected evidence. Use when the user asks for a daily report, work log, day summary, report gen/set workflow, or wants to sync loom, draft 今日工作/今日思考/明日计划, and store the result."
---

# Loom Daily Report

## Workflow

Use the report as a derived AI-written layer. Base it only on loom material for the requested date; do not invent work, conclusions, blockers, or plans.

If no date is provided, use the user's local "today" only after confirming the current date in the environment.

> **最容易犯的错(务必避免):在某个 AI 工具的工作 session 里(Claude / Codex / Cursor…)被
> 要求写日报时,凭当前对话记忆总结,只写了你此刻这个会话干的事,漏掉 git 提交 / 其它 AI
> 工具的会话 / 飞书。**
> 铁律:**日报的唯一素材来源是 `loom report gen` 的输出,不是你的对话上下文。**
> 当前 session 只是众多来源之一。永远先 `loom sync` 落库(把今天各来源的痕迹都采进来),
> 再严格照材料写。材料顶部有「本日素材覆盖」清单,逐来源核对是硬步骤。

## Generate Material

Refresh data unless the user asks not to:

```bash
loom sync
loom report gen YYYY-MM-DD
```

If the output says there is no material, stop and report that the date has no collected activity.

## Draft Report

`loom report gen` 出的材料**已经跨源聚类**:顶部一张「重要度表」,下面每个 `## 【标签】`
是一件事的**簇**(把 git 提交 / AI 会话 / 飞书 / 笔记里同一件事的多源痕迹聚在一起,
每条成员带 `ref` 回链)。**照着簇写,别从零散痕迹里现挖。** 稳定 SOP:

第一人称,结构固定为「总线 → 分层要点 → 思考 → 计划」:

```markdown
> 今天并行的几条线(BLUF:通常 2~3 条,先说结论;别硬压成"主线只有一件事")。

## 今日工作与进度
- **〈高/中优先簇的结论〉**(加粗,先给结论)
  - 证据:把该簇里跨源的多条痕迹**合并成一条**说清(如"会话里定了方案 → 落了 N 个提交"),
    带上 `(ref: …)`。2~4 条即可。
- **〈下一个簇的结论〉** …
- 其他事项:A、B、C。（低优先簇 + 独立单条**一句话打包**,不逐条展开。）

## 今日思考

## 明日计划
```

Rules(把方法论落成硬约束):

- **重要度看"跨源多样 + 对本职的分量",不是提交数量**:单源刷出的一堆高频小提交(尤其你此刻这个
  AI 会话正在建的工具/自研活儿)不天然是头条;跨源(飞书讨论+提交+设计)、有生产/成本影响的,即使
  提交少也应靠前。**别让 session 偏见和数量把排序带偏**——重要度表分数仅供参考,自己判分量。
- **详略由重要度决定**:高优先簇展开(结论 + 证据),低优先/单条一句话带过。**高优先条目 ≤5 个**。
- **先结论后证据**(BLUF/金字塔):每条先给"做成了什么/结论",再跟证据;别一上来堆细节。
- **一件事只写一条**:同一簇的跨源痕迹合并,别按 git/会话/飞书拆成几条重复说。
- **忠实性**:每条展开的结论必须有 ≥1 条带 `ref` 的证据支撑;没有就降级进"其他事项"或写"未见明确证据"。`ref` 原样保留,不要转述/编造链接或 id。
- 次要提交(重构/依赖升级/格式化)默认进"其他事项",不展开(类比 changelog 只写可感知的变化)。
- 无支撑内容的段落整段省略;不给日报打窄主题标签。

## Self-check(写完过一遍再存)

- [ ] 开头总线是不是点了**并行的几条线**(不是硬压成"主线只有一件事")?
- [ ] 头条/排序是不是被"你这个 session 正在干的事"或"提交数量"带偏了?跨源、有生产/成本分量的排在前了吗?
- [ ] 「今日工作」是不是**按簇**、每簇先结论?高优先 ≤5 个?
- [ ] 有没有残留"按 git/会话/飞书 分节机械罗列"?——有则说明没按簇写,回头重组。
- [ ] 每条展开结论都有 `ref` 证据?没有的已降级或标注"未见明确证据"?
- [ ] 次要事项是不是一句话打包、没逐条展开?
- [ ] **逐来源对账**:材料顶部「本日素材覆盖」里的每个来源(git/Codex/飞书/其它会话),
      在日报里都有所体现或被明确判为次要了吗?——**没漏掉当前 session 之外的来源?**

## Store Back

Write the markdown to a temporary local file, then run:

```bash
loom report set YYYY-MM-DD --file <report.md>
```

Use `--push` only after explicit user confirmation.

## Verify

Run one or more:

```bash
loom today
loom search <distinct-report-keyword>
```

Confirm that the report was written, rendered into the journal, and is searchable.
