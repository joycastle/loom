---
name: loom-topic-triage
description: "Classify loom entries into topic leaves with a gather-to-TSV-to-apply workflow and post-apply verification. Use when the user asks to triage topics, build or refine the topic DAG, run loom topic gather/apply/show, review topic assignments, or classify historical entries without keyword overreach."
---

# Loom Topic Triage

## Core Rules

- Classify by actual content, not title, first sentence, or keyword hits.
- Assign only the most specific leaf topics. Topic hierarchy belongs in `vault/notes/topics/<topic>.md` frontmatter `parent:`.
- Use existing topics when they fit. Create new short leaf topics only when the content clearly needs them.
- Use `none-of-these` for uncertain rows. Do not force-fit ambiguous sessions.
- Do not put daily reports into a single topic. They summarize many topics and pollute rollups.
- Do not classify topic pages themselves.
- For long or vague sessions, follow `ref` and read the raw transcript for that day before assigning.

## Gather

Refresh first only when the data may be stale:

```bash
loom sync
loom topic ls
loom topic gather --limit 80
loom topic gather <keyword> --since YYYY-MM-DD --project <project> --limit 80
```

Read the current topic tree and every candidate snippet. For high-risk or vague rows, inspect the source file or transcript referenced by `ref`.

## Write TSV

Create a TSV mapping with no header:

```text
entry_id<TAB>leaf-topic-1,leaf-topic-2
entry_id<TAB>none-of-these
```

Before applying, self-review the TSV:

- Every `entry_id` must be copied exactly from `gather`.
- Every selected topic must be supported by the row's actual content.
- Multi-topic assignment is allowed only when the row materially covers multiple topics.
- New topics must be leaf names, not broad umbrella categories.

## Apply

Run:

```bash
loom topic apply --file <mapping.tsv>
```

Use `--push` only after explicit user confirmation.

## Verify

Run:

```bash
loom topic ls
loom topic show <each-touched-topic>
```

Read the members under each touched topic. If a wrong assignment slipped through, fix only the affected IDs in `~/.loom/data/topic_map.json` after making a timestamped backup of that file. For broad corrections, ask the user before editing the map.

If new topics were created, update their topic pages with the right `parent: [[...]]` values, then rerun `loom topic ls` and `loom topic show <parent-topic>`.
