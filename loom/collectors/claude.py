# -*- coding: utf-8 -*-
"""Claude Code 采集器:~/.claude/projects/*/*.jsonl。

按【消息的真实本地日期】把一个 session 拆到各天:跨天续聊的长 session,每个有活动的
天都单独出一条,带那天的第一句真实提问——避免长 session 只挂在开聊那天、后面几天看不见。
"""
import glob
import json
import os
import re
from collections import defaultdict

from .. import util


INTENT_CAP = 180     # 标题行的短意图
OPENING_CAP = 1200   # 开场提问全文(「我要干什么」),保留换行


def _substantive(texts):
    """返回首条实质用户消息(原文,未截断);滤掉命令/工具回传/系统提醒。"""
    for t in texts:
        s = (t or "").strip()
        if not s or s[0] in "<[":
            continue
        if s.startswith("/") and " " not in s[:20]:
            continue
        low = s.lower()
        if low.startswith("caveat") or "tool_result" in low or "system-reminder" in low:
            continue
        return s
    return ""


def _first_intent(texts):
    return re.sub(r"\s+", " ", _substantive(texts))[:INTENT_CAP]


def _iter_text(content):
    if isinstance(content, str):
        yield content
    elif isinstance(content, list):
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text" and p.get("text"):
                yield p["text"]


def collect(cfg, since):
    src = cfg["sources"].get("claude", {})
    if not src.get("enabled"):
        return []
    root = util.expand(src["projects_dir"])
    entries = []
    for fp in glob.glob(os.path.join(root, "*", "*.jsonl")):
        cwd = None
        title = ""
        sid = os.path.splitext(os.path.basename(fp))[0]
        # 每条消息:(本地时间, 类型, 用户文本);按天分桶
        by_day = defaultdict(lambda: {"ts": [], "users": [], "n_user": 0, "n_asst": 0})
        try:
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if not cwd and d.get("cwd"):
                        cwd = d["cwd"]
                    typ = d.get("type")
                    if typ == "ai-title":
                        title = d.get("title") or (d.get("message") or {}).get("content") or title
                        continue
                    lts = util.iso_utc_to_local(d.get("timestamp"))  # UTC→本地,按本地日期分桶
                    if not lts:
                        continue
                    bucket = by_day[lts[:10]]
                    bucket["ts"].append(lts)
                    if typ == "user":
                        bucket["n_user"] += 1
                        bucket["users"].extend(_iter_text((d.get("message") or {}).get("content")))
                    elif typ == "assistant":
                        bucket["n_asst"] += 1
        except Exception as e:
            util.log(f"  [claude] {sid[:8]} 读取失败: {e}")
            continue
        if not by_day:
            continue
        project = os.path.basename(cwd.rstrip("/")) if cwd else \
            os.path.basename(os.path.dirname(fp)).split("-")[-1]
        earliest = min(by_day)
        for day in sorted(by_day):
            if day < since:
                continue
            b = by_day[day]
            b["ts"].sort()
            opening = _substantive(b["users"])
            intent = re.sub(r"\s+", " ", opening)[:INTENT_CAP]
            if day == earliest and title:      # 开聊那天用 AI 生成的整会话标题;续聊天用当天首问
                intent = title.strip()
            entries.append({
                "id": f"claude:{sid}:{day}", "date": day, "ts": b["ts"][0],
                "project": project, "tool": "claude", "kind": "session",
                "summary": intent or "(续聊)", "ref": fp,
                "detail": {"start": b["ts"][0], "end": b["ts"][-1],
                           "user": b["n_user"], "asst": b["n_asst"],
                           "opening": opening[:OPENING_CAP]},
            })
    return entries
