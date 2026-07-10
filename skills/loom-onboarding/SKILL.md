---
name: loom-onboarding
description: "Guide a new or returning user through loom setup, configuration, first sync, history intake, and the code-vs-data boundary. Use when the user asks to initialize loom, follow ONBOARDING.md, configure sources, collect historical work traces, or explain what lives in the repo versus ~/.loom."
---

# Loom Onboarding

## Workflow

Use `ONBOARDING.md` as the source-of-truth runbook. Work one phase at a time, inspect command output before proceeding, and do not skip the privacy boundaries.

If `loom` is not on PATH, run commands from the repo root with `python3 -m loom`.

## Guardrails

- Confirm before irreversible or external actions: deleting or moving files, `--push`, creating a remote repo, sharing data, or writing cron/automation.
- Put credentials only in `~/.loom/.env` with mode `600`. Never paste secrets into repo files, markdown notes, logs, or chat output.
- Explain the split early: this repo is tool code; `~/.loom/` is the private instance containing `config.json`, `.env`, `data/`, and `vault/`.
- Treat `loom sync` as local collection/render/vault commit. Treat `loom sync --push` as external backup and require confirmation.

## Phase A: Environment

Run:

```bash
loom --help || python3 -m loom --help
python3 -m pytest tests/ -q
```

Ask for the user's name, git author emails or names, and the root directory to scan for git repos. Default the scan root to `~/Documents` if the user has no preference.

Run:

```bash
loom init
```

Let the user enter secrets interactively when Feishu is configured.

## Phase B: First Sync

Run without push:

```bash
loom sync
loom today
loom search <keyword>
```

Explain the result in concrete terms: entries live in `~/.loom/data/entries.jsonl`, search index and journals are derived, and collection is read-only except for writing the loom instance.

## Phase C: Intake

Use explicit commands for loose material:

```bash
loom doc add <paths...> --to <category> --tags <tags>
loom data add <csv-or-xlsx...> --to <topic> --from <upstream> --code <code-files>
loom note "<text>" --to <category> --tags <tags>
loom report import <daily-report.xlsx>
```

Do not bulk-import raw data by directory. CSV/XLSX files must go through `loom data add` so raw files remain local under `_data/` and only data cards become searchable.

## Phase D: Backup

Only after the user confirms private backup, verify the vault remote and risk with `$loom-vault-ops`. Then run:

```bash
loom sync --push
```

Do not set cron or recurring automation without explicit confirmation.

## Phase E: Next Skills

For topic classification, switch to `$loom-topic-triage`. For daily reports, use `$loom-daily-report`. For session summaries, use `$loom-session-digest`.
