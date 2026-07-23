# -*- coding: utf-8 -*-
"""pi 采集器:~/.pi/agent/sessions/**/*.jsonl。

pi 的 session 是树状 JSONL；每条消息有自己的时间，因此和 Claude 一样按真实本地日期
拆分。分支上的用户消息也是实际工作痕迹，全部保留；工具结果、思考、压缩摘要不入库。
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


def _is_real(text):
    """过滤命令、注入上下文和压缩续接提示，只留下用户的真实提问。"""
    s = (text or "").strip()
    if not s or s.startswith("<"):
        return False
    if s.startswith("/") and " " not in s[:20]:
        return False
    low = s.lower()
    if "tool_result" in low or "system-reminder" in low:
        return False
    if low.startswith("this session is being continued") \
            or "that ran out of context" in low \
            or low.startswith("continue from where"):
        return False
    return True


def _iter_text(content):
    if isinstance(content, str):
        yield content
        return
    if not isinstance(content, list):
        return
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
            yield part["text"]


def _entry_time(row, message=None):
    ts = util.iso_utc_to_local(row.get("timestamp"))
    if ts:
        return ts
    return util.ms_to_iso((message or {}).get("timestamp"))


def collect(cfg, since):
    src = cfg.get("sources", {}).get("pi", {})
    if not src.get("enabled"):
        return []
    root = util.expand(src.get("sessions_dir", "~/.pi/agent/sessions"))
    if not os.path.isdir(root):
        return []

    entries = []
    for fp in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        sid = os.path.splitext(os.path.basename(fp))[0].split("_", 1)[-1]
        cwd, title = "", ""
        by_day = defaultdict(lambda: {"ts": [], "users": [], "n_user": 0,
                                      "n_asst": 0})
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    typ = row.get("type")
                    if typ == "session":
                        sid = row.get("id") or sid
                        cwd = row.get("cwd") or cwd
                        continue
                    if typ == "session_info" and row.get("name"):
                        title = str(row["name"]).strip()
                        continue
                    if typ != "message":
                        continue
                    message = row.get("message") or {}
                    role = message.get("role")
                    if role not in ("user", "assistant"):
                        continue
                    ts = _entry_time(row, message)
                    if not ts:
                        continue
                    bucket = by_day[ts[:10]]
                    bucket["ts"].append(ts)
                    if role == "user":
                        bucket["n_user"] += 1
                        bucket["users"].extend(_iter_text(message.get("content")))
                    else:
                        bucket["n_asst"] += 1
        except Exception as exc:
            util.log(f"  [pi] {os.path.basename(fp)} 读取失败: {exc}")
            continue

        if not by_day:
            continue
        project = os.path.basename(cwd.rstrip(os.sep)) if cwd else "pi"
        earliest = min(by_day)
        for day, bucket in sorted(by_day.items()):
            if day < since:
                continue
            bucket["ts"].sort()
            real = [t.strip() for t in bucket["users"] if _is_real(t)]
            opening = real[0] if real else ""
            intent = re.sub(r"\s+", " ", opening)[:INTENT_CAP]
            if day == earliest and title:
                intent = title[:INTENT_CAP]
            body = " / ".join(" ".join(t.split()) for t in real)[:BODY_CAP]
            entries.append({
                "id": f"pi:{sid}:{day}", "date": day, "ts": bucket["ts"][0],
                "project": project, "tool": "pi", "kind": "session",
                "summary": intent or "(pi 会话)", "ref": fp,
                "detail": {"start": bucket["ts"][0], "end": bucket["ts"][-1],
                           "user": bucket["n_user"], "asst": bucket["n_asst"],
                           "opening": opening[:OPENING_CAP], "body": body},
            })
    return entries
