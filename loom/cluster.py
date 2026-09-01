# -*- coding: utf-8 -*-
"""跨源聚类派生层:把多源条目聚成「一件事」的簇。

日报质量差的根因是"没聚类就直接写"——git 改某表 / codex 调该表 / 飞书讨论它
被平铺成三段、从不关联。这里先做**确定性聚类**(纯 stdlib,不靠 LLM/embedding),
让日报能拿"一件事"来写。

思路对齐实体解析(dedupe/Splink)+ 事件分组(Alertmanager/Sentry 级联判据):
  Blocking(按 project 粗分组)→ 边(强:共享标识符 / 中:relations 结构边 /
  弱:关键词 Jaccard / 主题标签)→ 连通分量 + 标签传播社区发现 = 簇。

**源码只留机制**:所有词表/权重/阈值都来自配置(report.cluster.*),下面 _policy()
从 config 读、给通用默认。派生产物(可重算),不入 entries.jsonl。
"""
import os
import re
from collections import Counter, defaultdict

from . import config as _config
from . import relations
from .collectors import feishu_user

# 标识符/关键词抽取的正则(纯机制:PR号/文件名/ASCII 长标识符)。停用词复用飞书那套。
_ID_ASCII = feishu_user._IDENT_RE                       # [A-Za-z][A-Za-z0-9_]{4,}
_ID_ISSUE = re.compile(r"#\d+")
_ID_FILE = re.compile(r"[\w./-]+\.(?:py|sql|md|ts|tsx|js|jsx|go|java|json|ya?ml|sh|rb)")
_STOP = feishu_user._IDENT_STOP


def _policy(cfg):
    """解析聚类策略:用户 config 覆盖内置默认。源码只读这里,不写死任何数值/词表。"""
    default = _config.DEFAULT_CONFIG["report"]["cluster"]
    pol = ((cfg or {}).get("report", {}) or {}).get("cluster", {}) or {}

    def num(key):
        v = pol.get(key, default[key])
        return v if isinstance(v, (int, float)) else default[key]

    def wmap(key):
        m = dict(default[key])
        if isinstance(pol.get(key), dict):
            m.update({k: v for k, v in pol[key].items() if isinstance(v, (int, float))})
        return m

    generic = set(pol.get("generic_ids", default["generic_ids"]))
    generic |= {x.lower() for x in pol.get("generic_ids_extra", []) if isinstance(x, str)}
    return {
        "jaccard_min": num("jaccard_min"), "edge_min": num("edge_min"),
        "id_owners_max": int(num("id_owners_max")),
        "topic_owners_max": int(num("topic_owners_max")),
        "big_cluster": int(num("big_cluster")),
        "w": wmap("weights"), "sw": wmap("score_weights"), "generic": generic,
    }


class _UF:
    """并查集(路径压缩 + 记录成员),~连通分量聚类。"""
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def groups(self):
        g = defaultdict(list)
        for x in self.parent:
            g[self.find(x)].append(x)
        return list(g.values())


_PR_SUFFIX = re.compile(r"\s*\(#\d+\)\s*$")


def _fingerprint(e):
    """条目内容指纹:同一件东西被采两遍 → 同指纹。覆盖所有来源,不只 git:
      - 跨仓镜像提交(开源仓 + 私有镜像仓):subject 去掉 PR 号后 + 文件数/增删行相同;
      - 续接/重复同步的会话、转发或重复入库的消息、同步两遍的文档:同 kind 内正文文本一致。
    **只抓文本几乎一模一样的**——跨源'讲同一件事'(文本不同)不是重复,交给聚类连,别在这误折叠。"""
    kind = e.get("kind", "")
    d = e.get("detail") or {}
    if kind == "commit" and d.get("files") is not None:
        subj = _PR_SUFFIX.sub("", (e.get("summary") or "").strip())
        return ("commit", subj, d.get("files"), d.get("ins"), d.get("del"))
    # 文本去重只给 chat(消息正文进了 _text,转发·重复入库的同一条消息可靠判重)。
    # 刻意排除 session/doc/note:
    #   - session 有 sid 强身份(store 已按 id 去重),开场白/摘要雷同 ≠ 同一会话;
    #   - doc/note 的条目只带标题、正文不在 _text 里,按标题去重会把同名不同内容的文档
    #     (如两个项目各自的 README.md)误折叠。要安全去重它们得采集时带内容哈希(TODO)。
    if kind != "chat":
        return None
    text = " ".join(_text(e).split()).lower()
    return (kind, text) if text else None


def _dedup(items):
    """按内容指纹去重(纯机制,去重完全相同的内容,不涉及个人策略);不改 store,只影响
    聚类/日报材料。不修它的话,重复采集会灌高 member_count/边数、造一堆'N条'假簇。"""
    seen = {}
    out = []
    for eid, e in items:
        fp = _fingerprint(e)
        if fp is not None:
            if fp in seen:
                continue
            seen[fp] = eid
        out.append((eid, e))
    return out


def _text(e):
    d = e.get("detail") or {}
    return " ".join([e.get("summary", ""), str(d.get("body", "")),
                     str(d.get("opening", ""))])


def _identifiers(e, generic):
    """从条目抽共享标识符集合(小写)。不 tokenize ref(session 的 ref 是含 dizai/
    loom 的 transcript 路径,会把所有会话假连成一团)。generic 里的泛化词剔除。"""
    blob = _text(e)
    ids = set()
    for m in _ID_ISSUE.findall(blob):
        ids.add(m)
    for m in _ID_FILE.findall(blob):
        low = m.lower()
        if os.path.basename(low) not in generic:
            ids.add(low)
    for m in _ID_ASCII.findall(blob):
        low = m.lower()
        if low not in _STOP and low not in generic:
            ids.add(low)
    for path in relations._files(e):
        low = path.lower()
        if os.path.basename(low) not in generic:
            ids.add(low)
    return ids - generic


def _keywords(e):
    return {t.lower() for t in _ID_ASCII.findall(_text(e)) if t.lower() not in _STOP}


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def _edges(items, pol):
    """items: [(eid, entry)]。产出去重边 {(a,b): {'reasons':set,'score':float}}。"""
    ids = {eid for eid, _ in items}
    idmap = dict(items)
    w = pol["w"]
    edges = defaultdict(lambda: {"reasons": set(), "score": 0.0})

    def add(a, b, reason, weight):
        if a == b or a not in ids or b not in ids or weight <= 0:
            return
        k = tuple(sorted((a, b)))
        edges[k]["reasons"].add(reason)
        edges[k]["score"] += weight

    # 强边:共享**特定**标识符(倒排);太泛化的(>N 条共享)跳过
    by_ident = defaultdict(list)
    for eid, e in items:
        for tok in _identifiers(e, pol["generic"]):
            by_ident[tok].append(eid)
    for tok, owners in by_ident.items():
        owners = sorted(set(owners))
        if len(owners) < 2 or len(owners) > pol["id_owners_max"]:
            continue
        for i in range(len(owners)):
            for j in range(i + 1, len(owners)):
                add(owners[i], owners[j], f"共享标识符 {tok}", w["strong"])

    # 中边:复用 relations 结构边,按证据强度重新赋权(relations 的分数反映不了"是否
    # 同一件具体事",如"会话产出"只是同项目+时间重叠,很弱)。
    for ed in relations.all_edges(idmap):
        for r in ed["reasons"]:
            if "续接" in r:
                wt = w["rel_continue"]
            elif "改动了" in r:
                wt = w["rel_touch"]
            elif "共改" in r:
                wt = min(w["rel_shared_file"], ed["score"])
            else:
                wt = w["rel_time"]
            add(ed["source"], ed["target"], r, wt)

    # 主题标签边:共享同一 AI 语义主题(中↔英都能桥)。按窗口内共享条数分级降权。
    from . import topics
    tmap = topics.load_map()
    by_topic = defaultdict(list)
    for eid, _ in items:
        for t in tmap.get(eid, []):
            by_topic[t].append(eid)
    for t, owners in by_topic.items():
        owners = sorted(set(owners))
        n = len(owners)
        if n < 2 or n > pol["topic_owners_max"]:
            continue
        wt = w["topic_rare"] if n <= 3 else w["topic_common"]
        for i in range(n):
            for j in range(i + 1, n):
                add(owners[i], owners[j], f"同主题「{t}」", wt)

    # 弱边:同 project 内关键词 Jaccard
    by_proj = defaultdict(list)
    for eid, e in items:
        by_proj[e.get("project", "")].append((eid, _keywords(e)))
    for _, group in by_proj.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                sim = _jaccard(group[i][1], group[j][1])
                if sim >= pol["jaccard_min"]:
                    add(group[i][0], group[j][0], f"关键词重叠{sim:.0%}", w["weak"] * sim)
    return edges


def cluster(items, cfg=None):
    """把一批条目聚成簇。items 可为 [(eid, entry)] 或 {eid: entry}。策略走 cfg。"""
    if isinstance(items, dict):
        items = list(items.items())
    items = _dedup(items)                                 # 先按内容指纹去重(全源,不只 git)
    idmap = dict(items)
    if not items:
        return []
    pol = _policy(cfg)
    edges = _edges(items, pol)
    big, emin = pol["big_cluster"], pol["edge_min"]

    def components(member_ids, min_score):
        uf = _UF()
        for eid in member_ids:
            uf.find(eid)
        for (a, b), meta in edges.items():
            if a in member_ids and b in member_ids and meta["score"] >= min_score:
                uf.union(a, b)
        return uf.groups()

    def label_prop(nodes, min_score):
        """标签传播社区发现:把稠密大簇拆成"连得更紧"的子社区。确定性(排序+取最小标签)。"""
        cset = set(nodes)
        adj = defaultdict(list)
        for (a, b), m in edges.items():
            if a in cset and b in cset and m["score"] >= min_score:
                adj[a].append((b, m["score"]))
                adj[b].append((a, m["score"]))
        label = {n: n for n in nodes}
        for _ in range(10):
            changed = False
            for n in sorted(nodes):
                if not adj.get(n):
                    continue
                votes = defaultdict(float)
                for mnb, wt in adj[n]:
                    votes[label[mnb]] += wt
                top = max(votes.values())
                best = min(l for l, v in votes.items() if v == top)
                if label[n] != best:
                    label[n] = best
                    changed = True
            if not changed:
                break
        g = defaultdict(list)
        for n in nodes:
            g[label[n]].append(n)
        return list(g.values())

    def split(member_ids, min_score):
        out = []
        for comp in components(set(member_ids), min_score):
            if len(comp) <= big:
                out.append(comp)
                continue
            subs = label_prop(comp, min_score)
            if len(subs) > 1:
                for s in subs:
                    out.extend(split(s, min_score))
            elif min_score < 12.0:
                out.extend(split(comp, min_score + 1.5))
            else:
                out.append(comp)
        return out

    groups = split(list(idmap), emin)
    clusters = []
    for gi, members in enumerate(groups):
        member_set = set(members)
        c_edges = [{"a": a, "b": b, "reasons": sorted(m["reasons"]),
                    "score": round(m["score"], 2)}
                   for (a, b), m in edges.items()
                   if a in member_set and b in member_set]
        ents = [idmap[m] for m in members]
        ts_list = sorted(e.get("ts", "") for e in ents if e.get("ts"))
        clusters.append({
            "cluster_id": f"c{gi + 1}",
            "members": [{"id": m, "kind": idmap[m].get("kind", ""),
                         "tool": idmap[m].get("tool", ""), "ts": idmap[m].get("ts", ""),
                         "summary": idmap[m].get("summary", ""),
                         "ref": idmap[m].get("ref", "")}
                        for m in sorted(members, key=lambda x: idmap[x].get("ts", ""))],
            "edges": c_edges,
            "label_hint": _label(ents, pol["generic"]),
            "time_range": [ts_list[0], ts_list[-1]] if ts_list else ["", ""],
            "singleton": len(members) == 1,
        })
    for c in clusters:
        c["importance"] = score_cluster(c, idmap, cfg)
    clusters.sort(key=lambda c: -c["importance"]["score"])
    return clusters


def _label(ents, generic):
    freq = Counter()
    for e in ents:
        for tok in _identifiers(e, generic):
            freq[tok] += 1
    common = [t for t, n in freq.most_common() if n >= 2]
    if common:
        return common[0]
    s = ents[0].get("summary", "") if ents else ""
    return " ".join(s.split())[:24]


def score_cluster(c, idmap, cfg=None):
    """可解释线性加权重要度(权重走配置);特征全来自现有字段。"""
    sw = _policy(cfg)["sw"]
    ents = [idmap[m["id"]] for m in c["members"]]
    kinds = {e.get("kind", "") for e in ents}
    days = {(e.get("date") or e.get("ts", "")[:10]) for e in ents
            if e.get("ts") or e.get("date")}
    file_changes = sum(int((e.get("detail") or {}).get("files") or 0) for e in ents)
    watch = set()
    if cfg:
        ow = cfg.get("owner", {}) if isinstance(cfg.get("owner"), dict) else {}
        watch = {w.strip().lower() for w in (ow.get("watchlist") or []) if isinstance(w, str)}
    keyword_hit = sum(1 for e in ents if watch and any(w in _text(e).lower() for w in watch))
    feats = {"degree": len(c["edges"]), "member_count": len(ents),
             "kind_diversity": len(kinds), "span_days": len(days),
             "file_changes": file_changes, "keyword_hit": keyword_hit}
    score = sum(sw.get(k, 0) * v for k, v in feats.items())
    return {"score": round(score, 2), "features": feats}
