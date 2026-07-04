# -*- coding: utf-8 -*-
"""docs 采集器:索引各仓里散落的 .md(标题 + 大纲 + 回链),不搬文件、不进日记。

和 git 脊柱同理:文档留在仓里当唯一真相源,这里只建可检索的**索引**,`ref` 指原文件。
产出 kind=doc,`loom search --tool docs` 可跨所有项目搜文档;render 跳过 kind=doc。
"""
import os
import re
import subprocess

from .. import util

SKIP = {"node_modules", ".git", "venv", ".venv", "__pycache__", "site-packages",
        "dist", "build", ".next", "target", "vendor", ".cache", ".loom", "vault"}
MAXDEPTH = 4
CONTENT_CAP = 200_000    # 单文档全文封顶(防个别超大 md 撑爆)
_H = re.compile(r"^(#{1,3})\s+(.+)")


def _outline(path):
    """返回 (title, headings[])。title=首个 # 一级标题,否则文件名。"""
    title, heads = None, []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 400:
                    break
                m = _H.match(line.strip())
                if m:
                    text = " ".join(m.group(2).split())
                    if m.group(1) == "#" and title is None:
                        title = text
                    if len(heads) < 20:
                        heads.append(text)
    except Exception:
        pass
    return title, heads


def _git_dates(repo):
    """一次 git log 拿到每个 .md 的最近提交日期(newest-first,首见即最新)。"""
    out = {}
    try:
        raw = subprocess.run(
            ["git", "-C", repo, "log", "--all", "--format=%x1e%aI", "--name-only", "--", "*.md"],
            capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return out
    date = None
    for line in raw.split("\n"):
        if line.startswith("\x1e"):
            date = line[1:].strip()
        elif line.strip().endswith(".md") and date:
            out.setdefault(line.strip(), date)   # 相对仓根路径 → 最新提交 ISO
    return out


def collect(cfg, since):
    src = cfg["sources"].get("docs", {})
    if not src.get("enabled"):
        return []
    entries = []
    for repo in cfg["repos"]:
        repo = util.expand(repo)
        if not os.path.isdir(repo):
            continue
        project = os.path.basename(repo.rstrip("/"))
        dates = _git_dates(repo)
        for dp, dns, fns in os.walk(repo):
            dns[:] = [d for d in dns if d not in SKIP and not d.startswith(".")]
            if dp[len(repo):].count(os.sep) > MAXDEPTH:
                dns[:] = []
                continue
            for fn in fns:
                if not fn.lower().endswith(".md"):
                    continue
                fp = os.path.join(dp, fn)
                rel = os.path.relpath(fp, repo)
                title, heads = _outline(fp)
                try:
                    with open(fp, encoding="utf-8", errors="replace") as f:
                        content = f.read()[:CONTENT_CAP]
                except Exception:
                    content = ""
                # 日期:git 最近提交(可靠→可进日记),否则文件 mtime(未提交→仅检索)
                iso = dates.get(rel)
                dated = bool(iso)     # 有 git 提交日期才算"这天改过",可进当天日记
                if not iso:
                    iso = util.ms_to_iso(os.path.getmtime(fp) * 1000)
                entries.append({
                    "id": f"doc:{project}:{rel}",
                    "date": (iso or "")[:10], "ts": iso or "",
                    "project": project, "tool": "docs", "kind": "doc",
                    "summary": title or rel, "ref": fp,
                    "detail": {"path": rel, "headings": heads, "repo": project,
                               "dated": dated, "content": content},
                })
    return entries
