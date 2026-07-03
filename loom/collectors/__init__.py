# -*- coding: utf-8 -*-
"""采集器注册表。加新工具 = 写一个 collect(cfg, since)->[entry] 并在此注册。"""
from . import git, claude, codex, cursor, codebuddy, feishu, feishu_im

REGISTRY = {
    "git": git.collect,
    "claude": claude.collect,
    "codex": codex.collect,
    "cursor": cursor.collect,
    "codebuddy": codebuddy.collect,
    "feishu": feishu.collect,
    "feishu_im": feishu_im.collect,
}


def names():
    return list(REGISTRY)
