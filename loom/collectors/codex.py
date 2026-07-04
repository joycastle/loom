# -*- coding: utf-8 -*-
"""Codex 采集器:~/.codex/state_5.sqlite 的 threads 表。"""
import glob
import os

from .. import util

_CANDIDATES = ("state_5.sqlite", "state.sqlite", "state_4.sqlite")


def _find_db(home):
    for name in _CANDIDATES:
        p = os.path.join(home, name)
        if os.path.exists(p):
            return p
    hits = sorted(glob.glob(os.path.join(home, "state*.sqlite")))
    return hits[-1] if hits else None


def collect(cfg, since):
    src = cfg["sources"].get("codex", {})
    if not src.get("enabled"):
        return []
    home = util.expand(src.get("home", "~/.codex"))
    db = _find_db(home)
    if not db:
        return []
    rows = util.read_sqlite(db,
        "SELECT id, created_at_ms, updated_at_ms, cwd, title, "
        "first_user_message, git_branch FROM threads")
    entries = []
    for r in rows:
        start = util.ms_to_iso(r.get("created_at_ms"))
        end = util.ms_to_iso(r.get("updated_at_ms")) or start
        if not start:
            continue
        end = end or start
        cwd = r.get("cwd") or ""
        project = os.path.basename(cwd.rstrip("/")) if cwd else "unknown"
        opening = (r.get("first_user_message") or "").strip()
        intent = (r.get("title") or opening).strip()
        intent = " ".join(intent.split())[:180] or "(会话)"
        detail = {"start": start, "end": end, "git_branch": r.get("git_branch"),
                  "opening": opening[:1200]}
        # 无逐条消息时间 → 按【开始日 + 最后活跃日】两端归属(跨天 session 两天都出现)
        for day in sorted({start[:10], end[:10]}):
            if day < since:
                continue
            ts = start if day == start[:10] else end
            entries.append({
                "id": f"codex:{r['id']}:{day}", "date": day, "ts": ts,
                "project": project, "tool": "codex", "kind": "session",
                "summary": intent, "ref": f"threads:{r['id']}", "detail": detail,
            })
    return entries
