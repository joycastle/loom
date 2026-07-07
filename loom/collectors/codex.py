# -*- coding: utf-8 -*-
"""Codex 采集器:~/.codex/sessions/**/*.jsonl(完整对话) + state_5.sqlite(元数据兜底)。

真相在 JSONL:每行一个事件,response_item 里有完整 user/assistant 消息。
sqlite 的 threads 表只是可重建的索引,用来补 JSONL 里缺失的 cwd/title 信息。
"""
import glob
import json
import os
from collections import defaultdict

from .. import util

INTENT_CAP  = 180
OPENING_CAP = 1200
BODY_CAP    = 8000
_CANDIDATES = ("state_5.sqlite", "state.sqlite", "state_4.sqlite")


def _find_db(home):
    for name in _CANDIDATES:
        p = os.path.join(home, name)
        if os.path.exists(p):
            return p
    hits = sorted(glob.glob(os.path.join(home, "state*.sqlite")))
    return hits[-1] if hits else None


def _is_real(t):
    s = (t or "").strip()
    if not s or s[0] in "<[":
        return False
    low = s.lower()
    if low.startswith("caveat") or "tool_result" in low:
        return False
    return True


def _iter_text(item):
    """从 response_item payload 的 content 列表里提取纯文本。"""
    content = item.get("content") or []
    if isinstance(content, str):
        yield content
        return
    for c in content:
        if isinstance(c, dict):
            for key in ("text", "output_text", "input_text"):
                t = c.get(key) if c.get("type") in (key, "text", "output_text", "input_text") else None
                if not t:
                    t = c.get("text")   # 直接取 text 字段
                if t:
                    yield t
                    break


def _load_jsonl_sessions(home, since):
    """扫描 ~/.codex/sessions/**/*.jsonl,按 session_id + 日期分桶,返回条目列表。"""
    session_dir = os.path.join(home, "sessions")
    if not os.path.isdir(session_dir):
        return []

    # session_id → {day → {ts, users, n_user, n_asst, cwd}}
    sessions = defaultdict(lambda: defaultdict(
        lambda: {"ts": [], "users": [], "asst": [], "n_user": 0, "n_asst": 0, "cwd": ""}
    ))
    session_meta = {}  # session_id → {title, cwd}

    pattern = os.path.join(session_dir, "**", "*.jsonl")
    for fp in glob.glob(pattern, recursive=True):
        sid = None
        # 从文件名提取 session_id(格式: rollout-<date>-<uuid>.jsonl)
        fname = os.path.splitext(os.path.basename(fp))[0]
        parts = fname.split("-", 2)  # rollout / date / uuid
        file_sid = parts[-1] if len(parts) >= 3 else fname

        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    evt = d.get("type") or d.get("event_type") or ""
                    payload = d.get("payload") or {}

                    if evt == "session_meta":
                        sid = payload.get("id") or file_sid
                        meta = session_meta.setdefault(sid, {})
                        if payload.get("cwd"):
                            meta["cwd"] = payload["cwd"]
                        if payload.get("title"):
                            meta["title"] = payload["title"]

                    if not sid:
                        sid = file_sid   # 兜底用文件名里的 uuid

                    if evt in ("response_item", "message"):
                        item = payload if payload.get("role") else (d.get("item") or d)
                        role = item.get("role") or ""
                        ts_raw = d.get("timestamp") or d.get("created_at") or ""
                        lts = util.iso_utc_to_local(ts_raw) if ts_raw else None
                        if not lts:
                            continue
                        day = lts[:10]
                        bucket = sessions[sid][day]
                        bucket["ts"].append(lts)
                        if not bucket["cwd"] and (session_meta.get(sid) or {}).get("cwd"):
                            bucket["cwd"] = session_meta[sid]["cwd"]

                        texts = list(_iter_text(item))
                        if role == "user":
                            bucket["n_user"] += 1
                            bucket["users"].extend(texts)
                        elif role == "assistant":
                            bucket["n_asst"] += 1
                            bucket["asst"].extend(texts)
        except Exception as e:
            util.log(f"  [codex] {os.path.basename(fp)} 读取失败: {e}")

    entries = []
    for sid, days in sessions.items():
        meta = session_meta.get(sid, {})
        cwd = meta.get("cwd", "")
        project = os.path.basename(cwd.rstrip("/")) if cwd else "codex"
        title = meta.get("title", "")
        earliest = min(days)
        for day, b in sorted(days.items()):
            if day < since:
                continue
            b["ts"].sort()
            reals = [t.strip() for t in b["users"] if _is_real(t)]
            opening = reals[0] if reals else ""
            intent = " ".join((title if day == earliest and title else opening).split())[:INTENT_CAP]
            body = " / ".join(" ".join(t.split()) for t in reals)[:BODY_CAP]
            entries.append({
                "id": f"codex:jsonl:{sid}:{day}", "date": day, "ts": b["ts"][0],
                "project": project, "tool": "codex", "kind": "session",
                "summary": intent or "(codex 会话)",
                "ref": os.path.join(home, "sessions"),
                "detail": {"start": b["ts"][0], "end": b["ts"][-1],
                           "user": b["n_user"], "asst": b["n_asst"],
                           "opening": opening[:OPENING_CAP], "body": body},
            })
    return entries


def _load_sqlite_sessions(home, since):
    """从 state_5.sqlite 读 threads 元数据(兜底:JSONL 不存在时)。"""
    db = _find_db(home)
    if not db:
        return []
    rows = util.read_sqlite(db,
        "SELECT id, created_at_ms, updated_at_ms, cwd, title, "
        "first_user_message, git_branch FROM threads")
    entries = []
    for r in rows:
        start = util.ms_to_iso(r.get("created_at_ms"))
        end   = util.ms_to_iso(r.get("updated_at_ms")) or start
        if not start:
            continue
        cwd = r.get("cwd") or ""
        project = os.path.basename(cwd.rstrip("/")) if cwd else "unknown"
        opening = (r.get("first_user_message") or "").strip()
        intent  = (r.get("title") or opening).strip()
        intent  = " ".join(intent.split())[:INTENT_CAP] or "(会话)"
        detail  = {"start": start, "end": end, "git_branch": r.get("git_branch"),
                   "opening": opening[:OPENING_CAP]}
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


def collect(cfg, since):
    src = cfg["sources"].get("codex", {})
    if not src.get("enabled"):
        return []
    home = util.expand(src.get("home", "~/.codex"))

    jsonl_entries = _load_jsonl_sessions(home, since)
    if jsonl_entries:
        return jsonl_entries
    # JSONL 不存在(旧版 Codex)→ 退回 sqlite 元数据
    return _load_sqlite_sessions(home, since)
