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


def _project_from_repos(c):
    repos = c.get("trackedGitRepos") or []
    for r in repos:
        for key in ("repoPath", "path", "rootPath", "relativePath"):
            p = r.get(key) if isinstance(r, dict) else None
            if p:
                return os.path.basename(str(p).rstrip("/"))
    sub = c.get("subtitle") or ""
    return "cursor"  # 无仓信息时归到 cursor 桶,而非误挂项目


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
            "project": _project_from_repos(c), "tool": "cursor", "kind": "session",
            "summary": intent, "ref": f"composer:{cid}",
            "detail": {"start": start, "end": end,
                       "files": c.get("filesChangedCount", 0),
                       "add": c.get("totalLinesAdded", 0),
                       "del": c.get("totalLinesRemoved", 0)},
        })
    return entries
