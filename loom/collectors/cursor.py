# -*- coding: utf-8 -*-
"""Cursor 采集器:globalStorage 的 composer.composerHeaders(会话头,无正文)。"""
import json
import os

from .. import util


def _load_headers(db):
    rows = util.read_sqlite(db,
        "SELECT value FROM ItemTable WHERE key = 'composer.composerHeaders'")
    if not rows:
        return []
    v = rows[0].get("value")
    if isinstance(v, (bytes, bytearray)):
        v = v.decode("utf-8", errors="ignore")
    try:
        return json.loads(v).get("allComposers", [])
    except Exception:
        return []


def _basename(p):
    return os.path.basename(str(p).rstrip("/"))


def _is_scratch(p):
    # 排除 worktree/临时目录(否则项目会误挂到 wt-xxx / scratchpad 名下)
    return "/private/tmp/" in p or "/scratchpad/" in p or "/wt-" in p


def _project(c):
    # 首选:workspaceIdentifier.uri.fsPath —— 打开会话时的工作区根目录(最准、覆盖最广)。
    wi = c.get("workspaceIdentifier")
    uri = wi.get("uri") if isinstance(wi, dict) else None
    if isinstance(uri, dict):
        p = uri.get("fsPath") or uri.get("path")
        if p and not _is_scratch(str(p)):
            return _basename(p)
    # 次选:trackedGitRepos[].repoPath(跳过临时 worktree)。
    for r in (c.get("trackedGitRepos") or []):
        p = r.get("repoPath") if isinstance(r, dict) else None
        if p and not _is_scratch(str(p)):
            return _basename(p)
    return "cursor"  # 无工作区信息(无文件夹的临时对话)时归到 cursor 桶,而非误挂项目


def collect(cfg, since):
    src = cfg["sources"].get("cursor", {})
    if not src.get("enabled"):
        return []
    base = util.expand(src.get("app_support", "~/Library/Application Support/Cursor"))
    db = os.path.join(base, "User", "globalStorage", "state.vscdb")
    entries = []
    for c in _load_headers(db):
        cid = c.get("composerId")
        end = util.ms_to_iso(c.get("lastUpdatedAt"))
        start = util.ms_to_iso(c.get("createdAt")) or end
        if not cid or not end or end[:10] < since:
            continue
        intent = " ".join((c.get("name") or "").split())[:180] or "(会话)"
        entries.append({
            "id": f"cursor:{cid}", "date": (start or end)[:10], "ts": start or end,
            "project": _project(c), "tool": "cursor", "kind": "session",
            "summary": intent, "ref": f"composer:{cid}",
            "detail": {"start": start, "end": end,
                       "files": c.get("filesChangedCount", 0),
                       "add": c.get("totalLinesAdded", 0),
                       "del": c.get("totalLinesRemoved", 0)},
        })
    return entries
