---
name: loom-daily-report
description: "Generate and write back AI-authored loom daily reports from real collected evidence. Use when the user asks for a daily report, work log, day summary, report gen/set workflow, or wants to sync loom, draft 今日工作/今日思考/明日计划, and store the result."
---

# Loom Daily Report

## Workflow

Use the report as a derived AI-written layer. Base it only on loom material for the requested date; do not invent work, conclusions, blockers, or plans.

If no date is provided, use the user's local "today" only after confirming the current date in the environment.

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
> 今天最重要的一件事(BLUF:一句话结论,先说结论)。

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

- **详略由重要度表决定**:高优先簇展开(结论 + 证据),低优先/单条一句话带过。**高优先条目 ≤5 个**。
- **先结论后证据**(BLUF/金字塔):每条先给"做成了什么/结论",再跟证据;别一上来堆细节。
- **一件事只写一条**:同一簇的跨源痕迹合并,别按 git/会话/飞书拆成几条重复说。
- **忠实性**:每条展开的结论必须有 ≥1 条带 `ref` 的证据支撑;没有就降级进"其他事项"或写"未见明确证据"。`ref` 原样保留,不要转述/编造链接或 id。
- 次要提交(重构/依赖升级/格式化)默认进"其他事项",不展开(类比 changelog 只写可感知的变化)。
- 无支撑内容的段落整段省略;不给日报打窄主题标签。

## Self-check(写完过一遍再存)

- [ ] 开头是不是一句话总线(BLUF)?
- [ ] 「今日工作」是不是**按簇**、每簇先结论?高优先 ≤5 个?
- [ ] 有没有残留"按 git/会话/飞书 分节机械罗列"?——有则说明没按簇写,回头重组。
- [ ] 每条展开结论都有 `ref` 证据?没有的已降级或标注"未见明确证据"?
- [ ] 次要事项是不是一句话打包、没逐条展开?

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
