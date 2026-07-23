# -*- coding: utf-8 -*-
"""关系层:从 entries **自动派生**条目间的直连边,和手工的主题 DAG 互补。

主题 DAG(topics.py)= 人工的、语义的边(「一件事」);
关系层(本模块)= 自动的、结构的边(谁产出谁、谁碰了同一份东西),从条目**已有字段**推,
重采即刷新、零人工维护——像检索索引、日记一样是 derived 层。

beachhead 边(用现有字段就能推,不新增采集):
- **会话 → 它产出的提交**:commit 的 ts 落在 session 的 [start, end] 时段内且同项目。
- **提交 ↔ 提交(共改)**:两条 commit 的 file_list 有共同文件路径(文件是天然连接点)。
- **提交 ↔ 文档/资料(碰同一文件)**:doc/note 的 path 出现在某 commit 的改动文件里。
- **同一对话的跨天续接**:session id `{tool}:{sid}:{day}` 里相同的 sid。

纯标准库;单人规模下按需 O(N) 扫描,不落额外索引。
"""
from collections import defaultdict


def _files(e):
    return [f.get("path", "") for f in (e.get("detail") or {}).get("file_list") or []
            if f.get("path")]


def _sid_day(eid):
    """会话 id `{tool}:{sid}:{day}` → (sid, day);非此形状返回 (None, None)。"""
    parts = (eid or "").split(":")
    if len(parts) < 3:
        return None, None
    return ":".join(parts[1:-1]), parts[-1]


def _view(e, reasons, score):
    return {"id": e["id"], "score": round(score, 3),
            "reasons": sorted(reasons),
            "date": e.get("date", ""), "project": e.get("project", ""),
            "tool": e.get("tool", ""), "kind": e.get("kind", ""),
            "summary": e.get("summary", ""), "ref": e.get("ref", "")}


def neighbors(by_id, eid, limit=30):
    """给一个条目,返回自动派生的相关条目 [{id, score, reasons, …}],按分数倒序。"""
    e = by_id.get(eid)
    if not e:
        return []
    project = e.get("project")
    detail = e.get("detail") or {}
    kind = e.get("kind")
    acc = defaultdict(lambda: {"reasons": set(), "score": 0.0})

    def add(other_id, reason, weight):
        if other_id and other_id != eid and other_id in by_id:
            acc[other_id]["reasons"].add(reason)
            acc[other_id]["score"] += weight

    my_files = set(_files(e))
    my_sid, _ = _sid_day(eid)

    for oid, o in by_id.items():
        if oid == eid:
            continue
        od = o.get("detail") or {}
        okind = o.get("kind")
        same_proj = o.get("project") == project

        # 会话 ↔ 提交:commit.ts 落在 session 时段内(哪边是会话都成立)
        if same_proj:
            sess, commit = None, None
            if kind == "session" and okind == "commit":
                sess, commit = e, o
            elif kind == "commit" and okind == "session":
                sess, commit = o, e
            if sess is not None:
                sd = sess.get("detail") or {}
                start, end = sd.get("start"), sd.get("end")
                cts = commit.get("ts")
                if start and end and cts and start <= cts <= end:
                    add(oid, "会话产出/来自会话", 3.0)

        # 提交 ↔ 提交:共改文件
        if kind == "commit" and okind == "commit" and my_files:
            shared = my_files & set(_files(o))
            if shared:
                sample = sorted(shared)[0]
                add(oid, f"共改 {len(shared)} 文件(如 {sample})", 1.0 + 0.3 * len(shared))

        # 提交 ↔ 文档/资料:doc/note 的 path 在提交的改动文件里
        opath = od.get("path")
        if kind == "commit" and opath and opath in my_files:
            add(oid, f"改动了 {opath}", 2.0)
        if okind == "commit" and detail.get("path") and detail["path"] in set(_files(o)):
            add(oid, f"被提交改动 {o.get('ref','')}", 2.0)

        # 同一对话跨天续接
        if kind == "session" and okind == "session" and my_sid:
            osid, _ = _sid_day(oid)
            if osid and osid == my_sid:
                add(oid, "同一对话续接", 2.5)

    ranked = sorted(acc.items(), key=lambda kv: (-kv[1]["score"], kv[0]))
    out = []
    for oid, meta in ranked[:limit]:
        out.append(_view(by_id[oid], meta["reasons"], meta["score"]))
    return out
