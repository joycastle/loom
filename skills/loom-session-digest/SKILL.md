---
name: loom-session-digest
description: "Generate accurate loom AI session digest TSVs from real question-and-answer transcripts and write them back. Use when the user asks to summarize sessions, improve vague AI conversation titles, run loom session gen/set/ls, batch process Claude sessions, or make answer-side content searchable."
---

# Loom Session Digest

## Scope

This workflow currently summarizes Claude sessions with readable local transcripts. Cursor and Codex entries may not have message-level text available, so do not promise full transcript digests for them.

Session digests are derived sidecar data in `~/.loom/data/session_digests.json`. They are applied back onto entries after sync, so regenerated collection does not erase them.

## Generate Material

Refresh first unless the user asks not to:

```bash
loom sync
loom session gen YYYY-MM-DD
```

If the output says there are no summarizable Claude sessions, stop and report that fact.

## Write TSV

For each `SESSION <id>` block, write exactly one TSV row:

```text
session_id<TAB>准确标题<TAB>2-4句可检索摘要
```

Rules:

- Copy the session ID exactly. `loom session set` rejects IDs that are not real sessions for that date.
- Use real tab characters. Do not add a header.
- Keep titles concise, specific, and useful for scanning. Avoid empty titles like "继续", "修一下", "这个问题".
- Base the summary only on the shown question-and-answer material.
- Include answer-side concepts and concrete results that future search should find.
- If the material is truncated or ambiguous, follow the entry `ref` to inspect the raw transcript for that date before writing.
- Redact or omit secrets even if they appear in the transcript.

## Store Back

Save the TSV locally, then run:

```bash
loom session set YYYY-MM-DD --file <digest.tsv>
```

Use `--push` only after explicit user confirmation.

## Verify

Run:

```bash
loom session ls
loom search <distinct-digest-keyword>
```

Confirm that titles are updated, the digest text is searchable, and the journal now shows improved session titles.

For bulk history work, process by date in small batches and verify after each batch before moving on.
