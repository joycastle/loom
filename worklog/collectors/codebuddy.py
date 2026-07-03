# -*- coding: utf-8 -*-
"""CodeBuddy 采集器(占位):本机暂无本地会话缓存,产出由 git 脊柱兜底。
留 hook:若某机器在 ItemTable 里存了会话,可在此解析。"""
import json
import os

from .. import util


def collect(cfg, since):
    src = cfg["sources"].get("codebuddy", {})
    if not src.get("enabled"):
        return []
    base = util.expand(src.get("app_support", "~/Library/Application Support/CodeBuddy"))
    db = os.path.join(base, "User", "globalStorage", "state.vscdb")
    if not os.path.exists(db):
        return []
    rows = util.read_sqlite(db,
        "SELECT value FROM ItemTable WHERE key = 'interactive.sessions'")
    sessions = []
    if rows:
        v = rows[0].get("value")
        if isinstance(v, (bytes, bytearray)):
            v = v.decode("utf-8", errors="ignore")
        try:
            sessions = json.loads(v)
        except Exception:
            sessions = []
    if not sessions:
        util.log("  [codebuddy] 检测到但无本地会话缓存;产出已由 git 脊柱覆盖")
        return []
    # TODO: 若某机器确有会话结构,在此按 codex/cursor 同构映射
    util.log(f"  [codebuddy] 发现 {len(sessions)} 条会话,但解析规则未实现(TODO)")
    return []
