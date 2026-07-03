# -*- coding: utf-8 -*-
"""Claude Code 采集器:~/.claude/projects/*/*.jsonl 每文件一个 session。"""
import glob
import json
import os
import re

from .. import util


def _first_intent(texts):
    for t in texts:
        s = (t or "").strip()
        if not s or s[0] in "<[":
            continue
        if s.startswith("/") and " " not in s[:20]:
            continue
        low = s.lower()
        if low.startswith("caveat") or "tool_result" in low or "system-reminder" in low:
            continue
        return re.sub(r"\s+", " ", s)[:180]
    return ""


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
        tmin = tmax = None
        title = ""
        texts = []
        n_user = n_asst = 0
        sid = os.path.splitext(os.path.basename(fp))[0]
        try:
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if not cwd and d.get("cwd"):
                        cwd = d["cwd"]
                    ts = d.get("timestamp")
                    if ts:
                        tmin = ts if tmin is None or ts < tmin else tmin
                        tmax = ts if tmax is None or ts > tmax else tmax
                    typ = d.get("type")
                    if typ == "ai-title":
                        title = d.get("title") or (d.get("message") or {}).get("content") or title
                    elif typ == "user":
                        n_user += 1
                        if len(texts) < 8:
                            texts.extend(_iter_text((d.get("message") or {}).get("content")))
                    elif typ == "assistant":
                        n_asst += 1
        except Exception as e:
            util.log(f"  [claude] {sid[:8]} 读取失败: {e}")
            continue
        if tmin is None or (tmax or "") < since:
            continue
        project = os.path.basename(cwd.rstrip("/")) if cwd else \
            os.path.basename(os.path.dirname(fp)).split("-")[-1]
        intent = title.strip() if title else _first_intent(texts)
        entries.append({
            "id": f"claude:{sid}", "date": tmin[:10], "ts": tmin,
            "project": project, "tool": "claude", "kind": "session",
            "summary": intent or "(会话)", "ref": fp,
            "detail": {"start": tmin, "end": tmax, "user": n_user, "asst": n_asst},
        })
    return entries
