# -*- coding: utf-8 -*-
"""Claude Code 采集器:~/.claude/projects/*/*.jsonl。

按【消息的真实本地日期】把一个 session 拆到各天:跨天续聊的长 session,每个有活动的
天都单独出一条,带那天的第一句真实提问——避免长 session 只挂在开聊那天、后面几天看不见。
"""
import glob
import json
import os
import re
from collections import Counter, defaultdict

from .. import util


INTENT_CAP = 180     # 标题行的短意图
OPENING_CAP = 1200   # 开场提问全文(「我要干什么」),保留换行
BODY_CAP = 8000      # 当天全部用户提问拼进检索(开场一句代表不了整段对话)


def _is_real(t):
    """是否为一条实质用户消息:滤掉命令/工具回传/系统提醒/压缩续接摘要。"""
    s = (t or "").strip()
    if not s or s[0] in "<[":
        return False
    if s.startswith("/") and " " not in s[:20]:
        return False
    low = s.lower()
    if low.startswith("caveat") or "tool_result" in low or "system-reminder" in low:
        return False
    if low.startswith("this session is being continued") \
            or "that ran out of context" in low \
            or low.startswith("请继续") or low.startswith("continue from where"):
        return False
    return True


def _substantive(texts):
    """返回首条实质用户消息(原文,未截断)。"""
    for t in texts:
        if _is_real(t):
            return t.strip()
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
        # branches/pr 抓 Claude Code 记的 git 上下文(gitBranch / prNumber / prUrl),
        # 用于把「这次对话」按 (项目+分支+天) 缝到同期 git 提交上,喂主题 DAG 的决策链。
        by_day = defaultdict(lambda: {"ts": [], "users": [], "n_user": 0,
                                      "n_asst": 0, "branches": Counter(), "pr": None})
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
                    br = d.get("gitBranch")
                    if br:
                        bucket["branches"][br] += 1
                    if not bucket["pr"] and d.get("prNumber"):
                        bucket["pr"] = {"number": d.get("prNumber"),
                                        "url": d.get("prUrl") or "",
                                        "repo": d.get("prRepository") or ""}
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
            reals = [t.strip() for t in b["users"] if _is_real(t)]
            opening = reals[0] if reals else ""
            intent = re.sub(r"\s+", " ", opening)[:INTENT_CAP]
            if day == earliest and title:      # 开聊那天用 AI 生成的整会话标题;续聊天用当天首问
                intent = title.strip()
            # 当天全部用户提问拼进 body → 进检索(整段对话的话题都能搜到,不止开场)
            body = " / ".join(" ".join(t.split()) for t in reals)[:BODY_CAP]
            branch = b["branches"].most_common(1)[0][0] if b["branches"] else ""
            detail = {"start": b["ts"][0], "end": b["ts"][-1],
                      "user": b["n_user"], "asst": b["n_asst"],
                      "opening": opening[:OPENING_CAP], "body": body}
            if branch:
                detail["branch"] = branch          # 当天对话主要所在的 git 分支
            if b["pr"]:
                detail["pr"] = b["pr"]              # 关联 PR(number/url/repo)
            entries.append({
                "id": f"claude:{sid}:{day}", "date": day, "ts": b["ts"][0],
                "project": project, "tool": "claude", "kind": "session",
                "summary": intent or "(续聊)", "ref": fp,
                "detail": detail,
            })
    return entries
