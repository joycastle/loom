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

Write in first person with these sections:

```markdown
## 今日工作与进度

## 今日思考

## 明日计划
```

Rules:

- Use concrete work traces from commits, sessions, notes, and data cards.
- Combine repeated traces into one coherent item.
- Preserve uncertainty. Say "未看到明确证据" rather than filling gaps.
- Omit a section if there is truly no supported content.
- Do not classify the daily report into a narrow topic.

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
