# -*- coding: utf-8 -*-
"""git 采集器(脊柱):遍历所有仓,抓【本人】的提交。"""
import os
import re
import subprocess

from .. import util

US = "\x1f"
RS = "\x1e"
_STASH = re.compile(r"^(index on |untracked files on |WIP on )")


def collect(cfg, since):
    emails = {e.lower() for e in cfg["identities"]["emails"]}
    names = {n.lower() for n in cfg["identities"]["names"]}
    entries = []
    fmt = RS + US.join(["%H", "%aI", "%ae", "%an", "%s"])
    for repo in cfg["repos"]:
        repo = util.expand(repo)
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        project = os.path.basename(repo.rstrip("/"))
        try:
            out = subprocess.run(
                ["git", "-C", repo, "log", "--all", "--no-merges",
                 "--since=" + since, "--pretty=format:" + fmt, "--numstat"],
                capture_output=True, text=True, timeout=60).stdout
        except Exception as e:
            util.log(f"  [git] {project} 读取失败: {e}")
            continue
        for chunk in out.split(RS):
            chunk = chunk.strip("\n")
            if not chunk:
                continue
            ls = chunk.split("\n")
            head = ls[0].split(US)
            if len(head) < 5:
                continue
            h, aiso, ae, an, subj = head[:5]
            if ae.lower() not in emails and an.lower() not in names:
                continue
            if _STASH.match(subj):
                continue
            ins = dele = files = 0
            for nl in ls[1:]:
                p = nl.split("\t")
                if len(p) == 3:
                    files += 1
                    ins += int(p[0]) if p[0].isdigit() else 0
                    dele += int(p[1]) if p[1].isdigit() else 0
            entries.append({
                "id": f"git:{project}:{h[:12]}", "date": aiso[:10], "ts": aiso,
                "project": project, "tool": "git", "kind": "commit",
                "summary": subj, "ref": h[:12],
                "detail": {"files": files, "ins": ins, "del": dele},
            })
    # 同 (项目,日期,标题) 只留改动最大一条(收敛 rebase/cherry-pick 重复)
    best = {}
    for e in entries:
        k = (e["project"], e["date"], e["summary"])
        d = e["detail"]
        score = d["ins"] + d["del"] + d["files"]
        if k not in best or score > best[k][0]:
            best[k] = (score, e)
    return [v[1] for v in best.values()]
