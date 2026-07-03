# -*- coding: utf-8 -*-
"""git 采集器(脊柱):遍历所有仓,抓【本人】的提交。"""
import os
import re
import subprocess

from .. import util

US = "\x1f"
RS = "\x1e"
GS = "\x1d"      # 消息(header+%b)与 numstat 之间的哨兵,防正文里的 numstat 样式行被误判
_STASH = re.compile(r"^(index on |untracked files on |WIP on )")
_NUMSTAT = re.compile(r"^(?:\d+|-)\t(?:\d+|-)\t")
_TRAILER = re.compile(r"^(Co-Authored-By|Signed-off-by|Change-Id):", re.I)
BODY_CAP = 4000    # 正文封顶(极端长正文防爆;实测中位 367、最大 ~1200)
FILES_CAP = 40     # 每提交存的文件明细上限(渲染时再截更短)


def collect(cfg, since):
    emails = {e.lower() for e in cfg["identities"]["emails"]}
    names = {n.lower() for n in cfg["identities"]["names"]}
    entries = []
    # header 单行(US 分隔)+ 换行 %b 正文 + GS 哨兵;GS 之后才是 --numstat 文件明细。
    fmt = RS + US.join(["%H", "%aI", "%ae", "%an", "%s"]) + "\n%b" + GS
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
            msg, _, numstat = chunk.partition(GS)   # GS 之前=header+正文,之后=文件明细
            mlines = msg.split("\n")
            head = mlines[0].split(US)
            if len(head) < 5:
                continue
            h, aiso, ae, an, subj = head[:5]
            if ae.lower() not in emails and an.lower() not in names:
                continue
            if _STASH.match(subj):
                continue
            # 文件明细:只在 GS 之后解析,正文里的 numstat 样式行不会被误判。
            ins = dele = files = 0
            file_list = []
            for nl in numstat.split("\n"):
                if not _NUMSTAT.match(nl):
                    continue
                p = nl.split("\t")
                if len(p) == 3:
                    files += 1
                    a = int(p[0]) if p[0].isdigit() else 0
                    d = int(p[1]) if p[1].isdigit() else 0
                    ins += a
                    dele += d
                    if len(file_list) < FILES_CAP:
                        file_list.append({"path": p[2], "ins": a, "del": d})
            # 正文 = 消息里除首行 header 外的部分;去掉纯噪声 trailer。
            body_lines = [b for b in mlines[1:] if not _TRAILER.match(b)]
            body = "\n".join(body_lines).strip()[:BODY_CAP]
            entries.append({
                "id": f"git:{project}:{h[:12]}", "date": aiso[:10], "ts": aiso,
                "project": project, "tool": "git", "kind": "commit",
                "summary": subj, "ref": h[:12],
                "detail": {"files": files, "ins": ins, "del": dele,
                           "body": body, "file_list": file_list},
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
