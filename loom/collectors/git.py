# -*- coding: utf-8 -*-
"""git 采集器(脊柱):遍历所有仓,抓【本人】的提交。"""
import os
import re
import subprocess

from .. import config, util

US = "\x1f"
RS = "\x1e"
GS = "\x1d"      # 消息(header+%b)与 numstat 之间的哨兵,防正文里的 numstat 样式行被误判
_STASH = re.compile(r"^(index on |untracked files on |WIP on )")
_NUMSTAT = re.compile(r"^(?:\d+|-)\t(?:\d+|-)\t")
_TRAILER = re.compile(r"^(Co-Authored-By|Signed-off-by|Change-Id):", re.I)
_BRACE_RENAME = re.compile(r"\{(.*?) => (.*?)\}")   # dir/{old => new}/x 花括号重命名


def _norm_path(p):
    """规整 numstat 的重命名路径:'old => new' 或 'dir/{a => b}/x' → 取新路径。"""
    if "=>" not in p:
        return p
    m = _BRACE_RENAME.search(p)
    if m:
        return (p[:m.start()] + m.group(2) + p[m.end():]).replace("//", "/")
    return p.split("=>")[-1].strip()
BODY_CAP = 4000    # 正文封顶(极端长正文防爆;实测中位 367、最大 ~1200)
FILES_CAP = 40     # 每提交存的文件明细上限(渲染时再截更短)


def _collect(cfg, since, errors):
    if not cfg.get("sources", {}).get("git", {}).get("enabled", True):
        return []
    emails = {e.lower() for e in cfg["identities"]["emails"]}
    names = {n.lower() for n in cfg["identities"]["names"]}
    entries = []
    seen_common_dirs = set()
    # header 单行(US 分隔)+ 换行 %b 正文 + GS 哨兵;GS 之后才是 --numstat 文件明细。
    fmt = RS + US.join(["%H", "%aI", "%ae", "%an", "%s"]) + "\n%b" + GS
    for repo in cfg["repos"]:
        repo = util.expand(repo)
        project = os.path.basename(repo.rstrip("/")) or repo
        info = config.git_worktree_info(repo)
        if not info:
            errors.append(f"{project}:不是可采集的 Git 仓库")
            continue
        if info["common_dir"] in seen_common_dirs:
            continue
        seen_common_dirs.add(info["common_dir"])
        if os.path.basename(info["common_dir"]) == ".git":
            project = os.path.basename(os.path.dirname(info["common_dir"])) or project
        else:
            project = os.path.basename(info["root"]) or project
        try:
            result = subprocess.run(
                ["git", "-C", repo, "log", "--all", "--no-merges",
                 "--since=" + since, "--pretty=format:" + fmt, "--numstat"],
                capture_output=True, text=True, timeout=60)
        except Exception as e:
            util.log(f"  [git] {project} 读取失败: {e}")
            errors.append(f"{project}:{e}")
            continue
        if result.returncode != 0:
            detail = (result.stderr or "git log 失败").strip().splitlines()[-1]
            util.log(f"  [git] {project} 读取失败: {detail}")
            errors.append(f"{project}:{detail}")
            continue
        out = result.stdout
        for chunk in out.split(RS):
            chunk = chunk.strip("\n")
            if not chunk:
                continue
            msg, _, numstat = chunk.rpartition(GS)  # 用 rpartition:真哨兵总在最后(正文含 GS 也不误判)
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
                        file_list.append({"path": _norm_path(p[2].strip()), "ins": a, "del": d})
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
    # 收敛 rebase/cherry-pick 重复:只有 (项目,日期,标题,改动量) 完全相同才算重复
    # (加 ins/del/files 进 key,避免同一天两个真实但同名的提交如 wip/fix 被误合并丢掉)。
    best = {}
    for e in entries:
        d = e["detail"]
        k = (e["project"], e["date"], e["summary"], d["ins"], d["del"], d["files"])
        if k not in best:
            best[k] = e
    return list(best.values())


def collect_diagnostic(cfg, since):
    errors = []
    entries = _collect(cfg, since, errors)
    return {"entries": entries, "errors": errors}


def collect(cfg, since):
    return collect_diagnostic(cfg, since)["entries"]
