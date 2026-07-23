# -*- coding: utf-8 -*-
"""OpenCode 会话采集器。

OpenCode 新版把会话放在 ``~/.local/share/opencode/opencode.db``，旧版则使用
``storage/{session,message,part}`` 分层 JSON。两种格式会长期并存（升级后旧文件不会
立刻消失），因此这里同时读取并按稳定 entry id 合并，SQLite 版本优先。
"""
import glob
import json
import os
import re
from collections import defaultdict

from .. import util


INTENT_CAP = 180
OPENING_CAP = 1200
BODY_CAP = 8000


def _json(value, default=None):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {} if default is None else default


def _local_time(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        return util.ms_to_iso(value)
    return util.iso_utc_to_local(str(value))


def _is_real(text):
    s = (text or "").strip()
    # OpenCode 插件会把真实提问包装成 [analyze-mode]/[search-mode]；part.synthetic
    # 才是可靠的系统注入标记，不能因方括号前缀丢掉整条用户问题。
    if not s or s.startswith("<"):
        return False
    if s.startswith("/") and " " not in s[:20]:
        return False
    low = s.lower()
    return "tool_result" not in low and "system-reminder" not in low


def _session(meta, ref):
    return {
        "id": meta.get("id") or meta.get("session_id") or "",
        "cwd": meta.get("directory") or "",
        "title": meta.get("title") or "",
        "created": meta.get("time_created"),
        "updated": meta.get("time_updated"),
        "additions": meta.get("summary_additions") or 0,
        "deletions": meta.get("summary_deletions") or 0,
        "files": meta.get("summary_files") or 0,
        "ref": ref,
        "days": defaultdict(lambda: {"ts": [], "users": [], "user_ids": set(),
                                      "asst_ids": set()}),
    }


def _add_message(session, message_id, role, created, texts=()):
    if role not in ("user", "assistant"):
        return
    ts = _local_time(created)
    if not ts:
        return
    bucket = session["days"][ts[:10]]
    bucket["ts"].append(ts)
    if role == "user":
        bucket["user_ids"].add(message_id)
        bucket["users"].extend(t for t in texts if isinstance(t, str))
    else:
        bucket["asst_ids"].add(message_id)


def _emit(sessions, since):
    entries = []
    for sid, session in sessions.items():
        if not sid or not session["days"]:
            continue
        cwd = session["cwd"]
        project = os.path.basename(cwd.rstrip(os.sep)) if cwd.rstrip(os.sep) else "opencode"
        earliest = min(session["days"])
        for day, bucket in sorted(session["days"].items()):
            if day < since:
                continue
            bucket["ts"].sort()
            real = [t.strip() for t in bucket["users"] if _is_real(t)]
            opening = real[0] if real else ""
            intent = re.sub(r"\s+", " ", opening)[:INTENT_CAP]
            if day == earliest and session["title"]:
                intent = re.sub(r"\s+", " ", str(session["title"]))[:INTENT_CAP]
            body = " / ".join(" ".join(t.split()) for t in real)[:BODY_CAP]
            entries.append({
                "id": f"opencode:{sid}:{day}", "date": day, "ts": bucket["ts"][0],
                "project": project, "tool": "opencode", "kind": "session",
                "summary": intent or "(OpenCode 会话)", "ref": session["ref"],
                "detail": {"start": bucket["ts"][0], "end": bucket["ts"][-1],
                           "user": len(bucket["user_ids"]),
                           "asst": len(bucket["asst_ids"]),
                           "opening": opening[:OPENING_CAP], "body": body,
                           "additions": session["additions"],
                           "deletions": session["deletions"], "files": session["files"]},
            })
    return entries


def _load_sqlite(data_dir, since):
    db = os.path.join(data_dir, "opencode.db")
    if not os.path.exists(db):
        return []
    # 一次快照、一次查询：util.read_sqlite 会复制 DB/WAL 避锁；分三次读会在大历史上
    # 重复复制整库，也可能跨到三个不同写入时点。
    rows = util.read_sqlite(
        db, "SELECT s.id AS session_id, s.directory, s.title, "
            "s.time_created AS session_created, s.time_updated AS session_updated, "
            "s.summary_additions, s.summary_deletions, s.summary_files, "
            "m.id AS message_id, m.time_created AS message_created, m.data AS message_data, "
            "p.id AS part_id, p.data AS part_data "
            "FROM session s LEFT JOIN message m ON m.session_id=s.id "
            "LEFT JOIN part p ON p.message_id=m.id "
            "ORDER BY s.id, m.time_created, m.id, p.time_created, p.id")
    sessions, messages = {}, {}
    for row in rows:
        sid = row.get("session_id")
        if not sid:
            continue
        if sid not in sessions:
            meta = {"id": sid, "directory": row.get("directory"),
                    "title": row.get("title"),
                    "time_created": row.get("session_created"),
                    "time_updated": row.get("session_updated"),
                    "summary_additions": row.get("summary_additions"),
                    "summary_deletions": row.get("summary_deletions"),
                    "summary_files": row.get("summary_files")}
            sessions[sid] = _session(meta, f"opencode:{sid}")
        mid = row.get("message_id")
        if not mid:
            continue
        message = messages.setdefault(mid, {"session_id": sid,
                                            "created": row.get("message_created"),
                                            "role": "", "texts": []})
        data = _json(row.get("message_data"))
        message["role"] = data.get("role") or message["role"]
        times = data.get("time") if isinstance(data.get("time"), dict) else {}
        message["created"] = times.get("created") or message["created"]
        part = _json(row.get("part_data"))
        if part.get("type") == "text" and not part.get("synthetic") \
                and isinstance(part.get("text"), str):
            message["texts"].append(part["text"])

    for mid, message in messages.items():
        session = sessions.get(message["session_id"])
        if session:
            _add_message(session, mid, message["role"], message["created"],
                         message["texts"])
    return _emit(sessions, since)


def _load_legacy_json(data_dir, since):
    storage = os.path.join(data_dir, "storage")
    if not os.path.isdir(storage):
        return []
    sessions = {}
    for fp in glob.glob(os.path.join(storage, "session", "**", "*.json"), recursive=True):
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                meta = json.load(f)
        except Exception:
            continue
        sid = meta.get("id")
        if not sid:
            continue
        times = meta.get("time") or {}
        normalized = dict(meta, time_created=times.get("created"),
                          time_updated=times.get("updated"),
                          summary_additions=(meta.get("summary") or {}).get("additions", 0),
                          summary_deletions=(meta.get("summary") or {}).get("deletions", 0),
                          summary_files=(meta.get("summary") or {}).get("files", 0))
        sessions[sid] = _session(normalized, f"opencode:{sid}")

    for sid, session in sessions.items():
        message_dir = os.path.join(storage, "message", sid)
        for fp in sorted(glob.glob(os.path.join(message_dir, "*.json"))):
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    message = json.load(f)
            except Exception:
                continue
            mid = message.get("id") or os.path.splitext(os.path.basename(fp))[0]
            texts = []
            for part_fp in sorted(glob.glob(os.path.join(storage, "part", mid, "*.json"))):
                try:
                    with open(part_fp, encoding="utf-8", errors="replace") as f:
                        part = json.load(f)
                except Exception:
                    continue
                if part.get("type") == "text" and not part.get("synthetic") \
                        and isinstance(part.get("text"), str):
                    texts.append(part["text"])
            created = (message.get("time") or {}).get("created")
            _add_message(session, mid, message.get("role"), created, texts)
    return _emit(sessions, since)


def collect(cfg, since):
    src = cfg.get("sources", {}).get("opencode", {})
    if not src.get("enabled"):
        return []
    data_dir = util.expand(src.get("data_dir", "~/.local/share/opencode"))
    if not os.path.isdir(data_dir):
        return []

    # 升级后的机器往往两种存储并存。旧历史先入，SQLite 同 id/day 覆盖它。
    merged = {entry["id"]: entry for entry in _load_legacy_json(data_dir, since)}
    merged.update({entry["id"]: entry for entry in _load_sqlite(data_dir, since)})
    return sorted(merged.values(), key=lambda entry: (entry["ts"], entry["id"]))
