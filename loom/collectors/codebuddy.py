# -*- coding: utf-8 -*-
"""CodeBuddy(腾讯 coding-copilot)采集器。

实测(2026-07):会话历史**不落本地**——本机三处本地存储均为空:
  - globalStorage/state.vscdb 的 `interactive.sessions` = `[]`
  - 专用 `codebuddy-sessions.vscdb` 的 ItemTable 无行
  - 每个 workspaceStorage/*/state.vscdb 的 `history.entries` / chat memento = `[]` / `{}`
即 CodeBuddy 把会话存在服务端,git 脊柱已覆盖这些工作产出。故本采集器探测已知
的本地存储位置,若确有数据(未来某机器/某版本)则解析,否则安静返回 []。
"""
import json
import os

from .. import util


def _load_json(db, query):
    rows = util.read_sqlite(db, query)
    if not rows:
        return None
    v = rows[0].get("value")
    if isinstance(v, (bytes, bytearray)):
        v = v.decode("utf-8", errors="ignore")
    try:
        return json.loads(v)
    except Exception:
        return None


def collect(cfg, since):
    src = cfg["sources"].get("codebuddy", {})
    if not src.get("enabled"):
        return []
    base = util.expand(src.get("app_support", "~/Library/Application Support/CodeBuddy"))

    # 汇总所有已知本地会话存储位置的候选数据(结构随发现再补映射)。
    found = []
    global_db = os.path.join(base, "User", "globalStorage", "state.vscdb")
    if os.path.exists(global_db):
        s = _load_json(global_db, "SELECT value FROM ItemTable WHERE key = 'interactive.sessions'")
        if isinstance(s, list):
            found += s
    sessions_db = os.path.join(base, "codebuddy-sessions.vscdb")
    if os.path.exists(sessions_db):
        s = _load_json(sessions_db, "SELECT value FROM ItemTable LIMIT 1")
        if s:
            found.append(s)
    ws_root = os.path.join(base, "User", "workspaceStorage")
    if os.path.isdir(ws_root):
        for d in os.listdir(ws_root):
            wdb = os.path.join(ws_root, d, "state.vscdb")
            if os.path.exists(wdb):
                h = _load_json(wdb, "SELECT value FROM ItemTable WHERE key = 'history.entries'")
                if isinstance(h, list) and h:
                    found += h

    if not found:
        util.log("  [codebuddy] 本地无会话历史(存服务端);git 脊柱已覆盖")
        return []
    # TODO: 某机器确有本地会话时,在此按 codex/cursor 同构映射为 entry
    util.log(f"  [codebuddy] 发现 {len(found)} 条本地会话数据,映射规则待补(见模块注释)")
    return []
