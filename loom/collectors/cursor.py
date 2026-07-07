# -*- coding: utf-8 -*-
"""Cursor 采集器:state.vscdb 的 composerData + bubbleId 键(完整对话内容)。

composerData:<composerId>  → session 元数据(标题/时间/工作区)
bubbleId:<composerId>:<bubbleId> → 单条消息(type=1 user, type=2 assistant)
"""
import json
import os
from collections import defaultdict

from .. import util

INTENT_CAP  = 180
OPENING_CAP = 1200
BODY_CAP    = 8000


def _is_scratch(p):
    return "/private/tmp/" in p or "/scratchpad/" in p or "/wt-" in p


def _basename(p):
    return os.path.basename(str(p).rstrip("/"))


def _project(c):
    wi = c.get("workspaceIdentifier")
    uri = wi.get("uri") if isinstance(wi, dict) else None
    if isinstance(uri, dict):
        p = uri.get("fsPath") or uri.get("path")
        if p and not _is_scratch(str(p)):
            return _basename(p)
    for r in (c.get("trackedGitRepos") or []):
        p = r.get("repoPath") if isinstance(r, dict) else None
        if p and not _is_scratch(str(p)):
            return _basename(p)
    return "cursor"


def _is_real(t):
    s = (t or "").strip()
    if not s or s[0] in "<[":
        return False
    low = s.lower()
    if low.startswith("caveat") or "tool_result" in low:
        return False
    return True


def _load_composers(db):
    """读 composerData:* 键,返回 {composerId → composer_dict}。"""
    rows = util.read_sqlite(db, "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'")
    composers = {}
    for r in rows:
        v = r.get("value")
        if isinstance(v, (bytes, bytearray)):
            v = v.decode("utf-8", errors="ignore")
        try:
            d = json.loads(v)
            cid = d.get("composerId") or r["key"].split(":", 1)[-1]
            composers[cid] = d
        except Exception:
            pass
    # 兜底:旧格式 composer.composerHeaders
    if not composers:
        rows2 = util.read_sqlite(db, "SELECT value FROM ItemTable WHERE key = 'composer.composerHeaders'")
        for r in rows2:
            v = r.get("value")
            if isinstance(v, (bytes, bytearray)):
                v = v.decode("utf-8", errors="ignore")
            try:
                for c in json.loads(v).get("allComposers", []):
                    cid = c.get("composerId")
                    if cid:
                        composers[cid] = c
            except Exception:
                pass
    return composers


def _load_bubbles(db):
    """读 bubbleId:*:* 键,返回 {composerId → [bubble_dict sorted by createdAt]}。"""
    rows = util.read_sqlite(db, "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'")
    by_composer = defaultdict(list)
    for r in rows:
        parts = r["key"].split(":")
        if len(parts) < 3:
            continue
        cid = parts[1]
        v = r.get("value")
        if isinstance(v, (bytes, bytearray)):
            v = v.decode("utf-8", errors="ignore")
        try:
            b = json.loads(v)
            by_composer[cid].append(b)
        except Exception:
            pass
    # 按 createdAt 排序
    for cid in by_composer:
        by_composer[cid].sort(key=lambda x: str(x.get("createdAt") or ""))
    return by_composer


def collect(cfg, since):
    src = cfg["sources"].get("cursor", {})
    if not src.get("enabled"):
        return []
    base = util.expand(src.get("app_support", "~/Library/Application Support/Cursor"))
    db = os.path.join(base, "User", "globalStorage", "state.vscdb")
    if not os.path.exists(db):
        return []

    composers = _load_composers(db)
    bubbles   = _load_bubbles(db)

    entries = []
    for cid, c in composers.items():
        end   = util.ms_to_iso(c.get("lastUpdatedAt"))
        start = util.ms_to_iso(c.get("createdAt")) or end
        if not end:
            continue
        start = start or end
        project = _project(c)
        title   = " ".join((c.get("name") or "").split())[:INTENT_CAP]

        # 从 bubbles 提取消息内容
        msgs = bubbles.get(cid, [])
        user_texts = []
        asst_texts = []
        for b in msgs:
            btype = b.get("type")  # 1=user, 2=assistant
            text  = (b.get("text") or "").strip()
            if not text:
                # 尝试 richText / codeBlocks 拼合
                parts = []
                for cb in (b.get("codeBlocks") or []):
                    if isinstance(cb, dict) and cb.get("code"):
                        parts.append(cb["code"])
                text = " ".join(parts).strip()
            if btype == 1 and text:
                user_texts.append(text)
            elif btype == 2 and text:
                asst_texts.append(text)

        reals   = [t for t in user_texts if _is_real(t)]
        opening = reals[0] if reals else ""
        intent  = title or (" ".join(opening.split())[:INTENT_CAP]) or "(cursor 会话)"
        body    = " / ".join(" ".join(t.split()) for t in reals)[:BODY_CAP]

        detail = {
            "start": start, "end": end,
            "files": c.get("filesChangedCount", 0),
            "add":   c.get("totalLinesAdded", 0),
            "del":   c.get("totalLinesRemoved", 0),
            "opening": opening[:OPENING_CAP],
            "body": body,
            "user": len(user_texts), "asst": len(asst_texts),
        }

        for day in sorted({start[:10], end[:10]}):
            if day < since:
                continue
            ts = start if day == start[:10] else end
            entries.append({
                "id": f"cursor:{cid}:{day}", "date": day, "ts": ts,
                "project": project, "tool": "cursor", "kind": "session",
                "summary": intent, "ref": f"composer:{cid}", "detail": detail,
            })
    return entries
