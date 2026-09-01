# -*- coding: utf-8 -*-
"""关联层物化(入库时派生,不是出报告时临时算)。

痛点:去重、关联边过去在**每个消费方各算各的**(日报聚类、`related` 邻域、浏览图谱),
不一致也重复计算。这里在 `loom sync` 入库后算一次、存进 sidecar,三方共用同一份。

范式对齐 digest.py:纯派生、**不改 store 原始条目**、可重算;sidecar 带 `sig`(库指纹),
消费方拿到的 by_id 与 sig 对不上就**现算兜底**——缓存缺失/过期永远不会让功能坏掉。

产物两块:
- `dup_of`: {重复条目 id: 代表 id}——同一件东西被采两遍(跨仓镜像提交 / 续接·重复同步的
  会话 / 转发·重复入库的消息文档),文本一模一样才判重(见 cluster._fingerprint)。
- `edges`: relations.all_edges 在**去重后**的可见条目上的结构边。
"""
import hashlib
import json
import os

from . import cluster, relations, util

RELATE_PATH = os.path.join(util.HOME, "data", "relate.json")


def _sig(by_id):
    """库指纹:条目 id 集合变了就失效(增删条目都会变),便于消费方判缓存新鲜度。"""
    h = hashlib.sha1()
    for eid in sorted(by_id):
        h.update(eid.encode("utf-8"))
        h.update(b"\0")
    return f"{len(by_id)}:{h.hexdigest()[:16]}"


def _dup_of(by_id):
    """确定性去重:按 id 排序取第一个作代表,其余重复指向它。"""
    seen, dup = {}, {}
    for eid in sorted(by_id):
        fp = cluster._fingerprint(by_id[eid])
        if fp is None:
            continue
        if fp in seen:
            dup[eid] = seen[fp]
        else:
            seen[fp] = eid
    return dup


def build(by_id):
    """算出完整关联层(去重 + 去重后的结构边)。纯函数,不落盘。"""
    dup = _dup_of(by_id)
    visible = {eid: e for eid, e in by_id.items() if eid not in dup}
    return {"sig": _sig(by_id), "dup_of": dup, "edges": relations.all_edges(visible)}


def load():
    try:
        return json.load(open(RELATE_PATH, encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        util.log("  [relate] relate.json 损坏,忽略(将现算)")
        return None


def save(data):
    os.makedirs(os.path.dirname(RELATE_PATH), exist_ok=True)
    with open(RELATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def apply_all(by_id):
    """入库后调用:算好关联层写 sidecar。返回 (去重条数, 边数)。"""
    data = build(by_id)
    save(data)
    return len(data["dup_of"]), len(data["edges"])


def _fresh(by_id):
    """取当前库对应的关联层:sidecar 新鲜就用,否则现算兜底(永不因缓存缺失而坏)。"""
    d = load()
    if d and d.get("sig") == _sig(by_id):
        return d.get("dup_of", {}), d.get("edges", [])
    d = build(by_id)
    return d["dup_of"], d["edges"]


def dup_of(by_id):
    return _fresh(by_id)[0]


def visible(by_id):
    """去掉重复条目后的可见台账(消费方用它,别再看见镜像/重复)。"""
    dup = dup_of(by_id)
    return {eid: e for eid, e in by_id.items() if eid not in dup}


def neighbors(by_id, eid, limit=30):
    """某条目的关联邻域,直接从物化边过滤(与浏览/日报同源、去重后一致)。"""
    dup, edges = _fresh(by_id)
    eid = dup.get(eid, eid)                       # 查重复条目 → 落到它的代表
    hits = []
    for ed in edges:
        if ed["source"] == eid:
            other = ed["target"]
        elif ed["target"] == eid:
            other = ed["source"]
        else:
            continue
        if other in by_id and other not in dup:
            hits.append((ed["score"], ed["reasons"], other))
    hits.sort(key=lambda x: (-x[0], x[2]))
    return [relations._view(by_id[o], reasons, score)
            for score, reasons, o in hits[:limit]]


def all_edges(by_id):
    return _fresh(by_id)[1]


def global_graph(by_id, max_nodes=60, max_edges=120):
    dup, edges = _fresh(by_id)
    vis = {eid: e for eid, e in by_id.items() if eid not in dup}
    return relations.graph_from_edges(vis, edges, max_nodes, max_edges)
