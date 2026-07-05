<div align="center">

<img src="assets/logo.svg" width="116" alt="loom" />

# loom

**Weave your scattered work traces — git commits · AI chats · docs · code · data — into one searchable, connected ledger**

One flat source of truth → daily journals · full-text search · topic graph · private cloud backup. Every entry carries a **back-link** to its origin.

<br>

![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white)
![dependencies](https://img.shields.io/badge/dependencies-0-5AA9A0)
![stdlib only](https://img.shields.io/badge/stdlib-only-5AA9A0)
![tests](https://img.shields.io/badge/tests-117%20passing-3FB950)
![single-user](https://img.shields.io/badge/private-first-E0A84E)
[![license](https://img.shields.io/badge/license-MIT-8A93A3)](./LICENSE)

![Claude Code](https://img.shields.io/badge/Claude_Code-8A2BE2?logo=anthropic&logoColor=white)
![Codex](https://img.shields.io/badge/Codex-000000?logo=openai&logoColor=white)
![Cursor](https://img.shields.io/badge/Cursor-1a1a2e)
![Copilot](https://img.shields.io/badge/Copilot-24292e?logo=githubcopilot&logoColor=white)
![CodeBuddy](https://img.shields.io/badge/CodeBuddy-0052d9)
![Windsurf](https://img.shields.io/badge/Windsurf-0e7c66)

[简体中文](./README.md) | **English**

<br><img src="assets/banner.svg" width="100%" alt="loom banner" />

</div>

---

> 🧵 **loom** collects *your own* work traces scattered across multiple git repos, AI coding sessions (Claude / Codex / Cursor / CodeBuddy), documents, code, data files and Feishu — normalizes them into one flat record stream, then weaves out search, daily journals, a topic DAG, and a private cloud backup. Pure-stdlib Python, **zero third-party dependencies**.

## ⚡ 5-minute setup: let your AI assistant drive (recommended)

loom ships **cross-tool AI entry files** — any assistant will find its way.

```bash
git clone https://github.com/joycastle/loom.git ~/Documents/loom
```

Open the folder with your favorite AI coding assistant and say:

> **"Read ONBOARDING.md and walk me through setup, then organize my history."**

It will pick up the rules files (`AGENTS.md` for Codex/Cursor/Copilot/Windsurf/CodeBuddy, `CLAUDE.md` for Claude Code) and follow [`ONBOARDING.md`](./ONBOARDING.md) — an AI-facing runbook: **setup → first collection → ingest loose files → private cloud backup → full topic classification → daily routine**.

Prefer manual? `cd ~/Documents/loom && ./install.sh`, then just `loom sync --push` daily.

## 🎨 Design highlights

Full illustrated walkthrough: [`docs/loom_showcase.html`](./docs/loom_showcase.html) ([view online](https://htmlpreview.github.io/?https://github.com/joycastle/loom/blob/main/docs/loom_showcase.html)).

- **① Flat storage, views on demand.** One truth file keyed by stable `id` (`entries.jsonl`); "by day", "by topic", "by project" are just different cuts. Capture once, visible on every axis.
- **② Summary + back-link only.** Each entry keeps the valuable short text (title, questions, commit rationale) plus a `ref` pointer; full transcripts / diffs / raw files stay where they live. Thousands of entries, still lightweight, always traceable.
- **③ Redaction before storage.** Tokens / secrets / webhooks are masked *before* anything is written (values only — variable names survive). Credentials live in `~/.loom/.env` (chmod 600), never in any repo.
- **④ Layered cloud sync.** Data files are distilled into searchable "data cards" (schema / stats / samples / lineage) that sync to your private repo; raw csv/xlsx stay local in gitignored `_data/`.
- **⑤ Topic layer is a DAG.** Entries carry only leaf tags; hierarchy lives on topic pages (`parent:` list = multi-parent). Queries roll up whole subtrees — one topic view stitches chats + commits + docs + data of "one thing" into a single decision trail.
- **⑥ Daily reports & session digests are AI-synthesized outputs**, not collection sources. `loom report gen` feeds a day's real traces to an AI; `loom session gen` reads a session's **questions and answers** to produce an accurate title + searchable digest (stored in a sidecar, survives re-collection).
- **⑦ Zero dependencies · 117 green tests.** Clone and run; redaction, path traversal, FTS recall, atomic writes and topic roll-up are all covered end-to-end.

## Commands

```bash
loom init                      # interactive setup
loom sync [--push] [--since]   # collect all sources → render → commit (--push to cloud)
loom search <term> [--project P] [--tool T] [--since D] [--until D]
loom serve [--port 8787]       # local browse UI (127.0.0.1): search / topic tree / by-day
loom doc add | data add | note # ingest docs / data files (→ data cards) / loose notes
loom report import|gen|set     # daily reports (AI-synthesized)
loom session gen|set|ls        # AI session digests (reads Q&A, writes title+digest)
loom topic ls|gather|apply|show
loom deprecate <path> [--mark] # retire stale/wrong content (out of search, history kept)
loom repo add|rm|scan|ls · feishu add|rm|ls · identity add|ls · source enable|disable
```

## Architecture

```
6 collection sources           normalize + redact         derived views
──────────────────            ──────────────────         ─────────────────────
git commits        ┐                                    ┌ FTS5 search (CJK substring)
Claude sessions    │                                    │ daily journals (markdown)
Cursor sessions    ├──►  loom  ──►  entries.jsonl  ──►  ├ topic DAG (roll-up queries)
Codex sessions     │   (one truth, redacted)            │ daily reports (AI-synthesized)
repo docs (.md)    │                                    ├ local browse UI (loom serve)
data·code·notes    ┘                                    └ private cloud backup (git)
```

Code lives in this repo; your instance lives in `~/.loom/` (config / .env / data / vault) — physically separate. `LOOM_HOME` overrides.

## Let AI in *any* project query your ledger

Add a one-paragraph global rule to your assistants (Claude Code `~/.claude/CLAUDE.md`, Codex `~/.codex/AGENTS.md`, Cursor user rules) so history questions hit `loom search` first. See [`docs/ai-global-access.md`](./docs/ai-global-access.md).

## Extending

Drop `xxx.py` into `loom/collectors/` implementing `collect(cfg, since) -> [entry]`, register it, done. Entry schema: `{id, date, ts, project, tool, kind, summary, ref, detail}`.

## License

[MIT](./LICENSE)

## 🤝 Contributing

Issues / PRs welcome: new collectors (just implement `collect(cfg, since)`), docs in other languages, pitfall notes.
Run `python3 -m pytest tests/test_loom.py` after changes (zero deps, should stay green).


---
**For AI assistants landing here**: read [`AGENTS.md`](./AGENTS.md) first; for first-time setup follow [`ONBOARDING.md`](./ONBOARDING.md).
