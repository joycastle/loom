---
name: loom-vault-ops
description: "Inspect loom vault backup safety before git push or cloud backup. Use when the user asks to check vault state, gitignore coverage, remote configuration, tracked raw data, push risk, private backup readiness, or whether loom sync --push is safe."
---

# Loom Vault Ops

## Safety Boundary

Do not run `loom sync --push`, `git push`, create remotes, or share vault contents without explicit user confirmation. Do not print `.env` values or raw sensitive files.

## Resolve Vault

Find `LOOM_HOME` and the vault directory from `~/.loom/config.json` or the `LOOM_HOME` override. Print only paths and whether a remote is configured; never print secrets.

If the vault does not exist yet and the user wants a live check, run:

```bash
loom sync
```

This initializes and commits the vault locally, enforces `.gitignore`, and does not push.

## Required Gitignore

The code requires these patterns in `vault/.gitignore` before adding files:

```text
_data/
.env
*.xlsx
*.pptx
*.numbers
*.pages
*.key
*.parquet
*.pdf
*.docx
```

Check that all are present. If missing, run `loom sync` so loom's own `_ensure_gitignore` adds them.

## Tracked-Risk Checks

Run against the resolved vault directory:

```bash
git -C <vault> status --short
git -C <vault> remote -v
git -C <vault> ls-files -i -c --exclude-standard
git -C <vault> ls-files '_data/*' '*.xlsx' '*.pptx' '*.numbers' '*.pages' '*.key' '*.parquet' '*.pdf' '*.docx' '.env'
```

Interpretation:

- `ls-files -i -c --exclude-standard` should be empty. If not, those files are tracked despite ignore rules.
- The explicit `ls-files` risk scan should be empty before any push.
- A dirty status is acceptable after sync only if the user understands what will be committed. Review the filenames, not file contents, unless needed.
- Remote must point to a private destination before backup. If privacy cannot be verified, say so and do not push.

## Push Readiness

Only recommend `loom sync --push` when all are true:

- User explicitly confirmed external backup.
- Vault remote exists and is intended to be private.
- Required ignores are present.
- No ignored raw data, binary source files, or `.env` are tracked.
- The pending `git status --short` changes are expected.

If any condition fails, report the specific blocker and the least invasive fix. Prefer `loom sync` for normal local repair because it untracks ignored files with `git rm --cached` while preserving local files.
