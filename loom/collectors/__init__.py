# -*- coding: utf-8 -*-
"""采集器注册表。加新工具 = 写一个 collect(cfg, since)->[entry] 并在此注册。"""
from . import git, claude, codex, cursor, codebuddy, feishu, docs, notes

REGISTRY = {
    "git": git.collect,
    "claude": claude.collect,
    "codex": codex.collect,
    "cursor": cursor.collect,
    "codebuddy": codebuddy.collect,
    "feishu": feishu.collect,
    "docs": docs.collect,
    "notes": notes.collect,
}

# The CLI keeps the long-standing collect()->[entry] contract. Surfaces that need
# trustworthy per-source status can opt into richer diagnostics without breaking it.
DIAGNOSTIC_REGISTRY = {
    "git": git.collect_diagnostic,
    "codebuddy": codebuddy.collect_diagnostic,
    "feishu": feishu.collect_diagnostic,
}

SOURCE_CATEGORIES = {
    "git": "development", "claude": "development", "codex": "development",
    "cursor": "development", "codebuddy": "development",
    "feishu": "collaboration",
    "docs": "knowledge", "notes": "knowledge",
}


def names():
    return list(REGISTRY)


def is_syncable(name):
    return name in REGISTRY


def sync_names():
    return [name for name in REGISTRY if is_syncable(name)]


def source_category(name):
    return SOURCE_CATEGORIES.get(name, "other")
