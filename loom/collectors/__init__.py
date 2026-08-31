# -*- coding: utf-8 -*-
"""采集器注册表。加新工具 = 写一个 collect(cfg, since)->[entry] 并在此注册。"""
from . import (git, claude, codex, cursor, codebuddy, pi, opencode, feishu,
               feishu_user, codex_feishu_bridge, docs, notes)

REGISTRY = {
    "git": git.collect,
    "claude": claude.collect,
    "codex": codex.collect,
    "cursor": cursor.collect,
    "codebuddy": codebuddy.collect,
    "pi": pi.collect,
    "opencode": opencode.collect,
    "feishu": feishu.collect,
    "feishu_user": feishu_user.collect,
    "codex_feishu_bridge": codex_feishu_bridge.collect,
    "docs": docs.collect,
    "notes": notes.collect,
}

# The CLI keeps the long-standing collect()->[entry] contract. Surfaces that need
# trustworthy per-source status can opt into richer diagnostics without breaking it.
DIAGNOSTIC_REGISTRY = {
    "git": git.collect_diagnostic,
    "codebuddy": codebuddy.collect_diagnostic,
    "feishu": feishu.collect_diagnostic,
    "feishu_user": feishu_user.collect_diagnostic,
    "codex_feishu_bridge": codex_feishu_bridge.collect_diagnostic,
}

# 每个源可选暴露 suggest(cfg)->[finding],供 `loom doctor` 统一检测+调用。
# 加新源自带 suggest 就会被 doctor 自动发现,不用改 doctor。
SUGGEST_REGISTRY = {
    "git": git.suggest,
    "claude": claude.suggest,
    "codex": codex.suggest,
    "cursor": cursor.suggest,
    "pi": pi.suggest,
    "opencode": opencode.suggest,
    "feishu_user": feishu_user.suggest,
    "docs": docs.suggest,
    "notes": notes.suggest,
}

SOURCE_CATEGORIES = {
    "git": "development", "claude": "development", "codex": "development",
    "cursor": "development", "codebuddy": "development",
    "pi": "development", "opencode": "development",
    "feishu": "collaboration", "feishu_user": "collaboration",
    "codex_feishu_bridge": "collaboration",
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
