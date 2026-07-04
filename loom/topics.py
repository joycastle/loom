# -*- coding: utf-8 -*-
"""主题层:把散落的对话/提交/文档/数据聚成「一件事」,支持多层(DAG)+ 多主题。

设计(参考 Obsidian 嵌套标签 / MOC、Logseq 命名空间、Notion relations+rollup、Zettelkasten
结构笔记后定稿的混合式):
- **条目只打最细的叶子主题**(扁平 id,非路径):存 `~/.loom/data/topic_map.json`
  {entry_id: [leaf_id,...]}。对 git 提交/AI 会话这种无 frontmatter 的条目也统一适用。
- **层级只在主题页** `notes/topics/<id>.md` 的 frontmatter:`parent: [[..]]`(列表→多父 DAG)。
  移子树 = 改一处 parent,不用回去重标条目。
- **上卷(roll-up)查询时算**:看父主题 → 递归展开整棵子树,把后代的条目都汇上来(防环)。
- 规范化 id + `aliases:` 防泛滥;AI 分类走闭集(见 gather 输出的指令)+ apply 时人过目。
纯标准库。
"""
import json
import os
import re
from collections import defaultdict

from . import config, util
from .intake import _parse_frontmatter, _read


def _map_path():
    return os.path.join(util.HOME, "data", "topic_map.json")


def _audit_path():
    return os.path.join(util.HOME, "data", "topic_audit.jsonl")


def topics_dir(cfg):
    return os.path.join(config.notes_dir(cfg), "topics")


def canon(name):
    """规范化主题 id:去 [[]]、空白转连字符、拉丁转小写(中文保持原样)。"""
    s = (name or "").strip().strip("[]").strip()
    s = re.sub(r"\s+", "-", s)
    return s.lower() if s.isascii() else s


def _parse_list(v):
    return [canon(x) for x in re.findall(r"[^\[\],\s]+", v or "") if x.strip()]


# ---- 主题页(层级 / 别名的唯一真相)----
def pages(cfg):
    """读 notes/topics/*.md → {id: {title, parents:[..], aliases:[..]}}。"""
    d, out = topics_dir(cfg), {}
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        fm, _ = _parse_frontmatter(_read(os.path.join(d, fn)))
        tid = canon(os.path.splitext(fn)[0])
        out[tid] = {"title": (fm.get("title") or tid).strip(),
                    "parents": _parse_list(fm.get("parent", "")),
                    "aliases": _parse_list(fm.get("aliases", ""))}
    return out


def _alias_index(pgs):
    idx = {}
    for tid, p in pgs.items():
        idx[tid] = tid
        for a in p["aliases"]:
            idx[a] = tid
    return idx


def resolve(name, pgs):
    """别名/规范化 → 权威 id(无匹配则返回规范化后的原名)。"""
    return _alias_index(pgs).get(canon(name), canon(name))


def descendants(topic, pgs):
    """topic + 全部后代(child.parents 指向 parent,反向建 children 图;DAG 去重防环)。"""
    children = defaultdict(set)
    for tid, p in pgs.items():
        for par in p["parents"]:
            children[par].add(tid)
    seen, stack = set(), [resolve(topic, pgs)]
    while stack:
        t = stack.pop()
        if t in seen:
            continue
        seen.add(t)
        stack.extend(children.get(t, ()))
    return seen


# ---- 条目 ↔ 主题 映射 ----
def load_map():
    p = _map_path()
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_map(m):
    os.makedirs(os.path.dirname(_map_path()), exist_ok=True)
    tmp = f"{_map_path()}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=0)
    os.replace(tmp, _map_path())


def members(cfg, topic, by_id):
    """某主题(含整棵子树)下的所有条目。"""
    pgs = pages(cfg)
    sub = descendants(topic, pgs)
    m = load_map()
    out = []
    for eid, ts in m.items():
        if eid in by_id and any(resolve(t, pgs) in sub for t in ts):
            out.append(by_id[eid])
    return out


def _create_topic_page(cfg, tid, parents=None):
    d = topics_dir(cfg)
    os.makedirs(d, exist_ok=True)
    dest = util.safe_join(d, tid + ".md")
    if dest is None or os.path.exists(dest):
        return
    par = "[" + ", ".join(f"[[{p}]]" for p in (parents or [])) + "]"
    with open(dest, "w", encoding="utf-8") as f:
        f.write(f"---\ntitle: {tid}\ntype: loom-topic\nparent: {par}\naliases: []\n---\n\n"
                f"> 主题:{tid}。(概述可手写;成员见 `loom topic show {tid}`)\n")


def apply(cfg, mapping):
    """应用 AI 的映射 [(entry_id, [主题名..]), ..]:写 map + 缺失主题建页 + 记审计。
    忽略 none-of-these(留待人工)。返回 (已分配数, 新建主题列表)。"""
    pgs = pages(cfg)
    m = load_map()
    created, assigned, audit = [], 0, []
    for eid, tnames in mapping:
        tids = [resolve(t, pgs) for t in tnames
                if t and canon(t) not in ("none-of-these", "待定")]
        if not tids:
            continue
        for tid in tids:
            if tid not in pgs and tid not in created:
                _create_topic_page(cfg, tid)
                created.append(tid)
        m[eid] = sorted(set(m.get(eid, []) + tids))
        assigned += 1
        audit.append({"id": eid, "topics": tids})
    save_map(m)
    if audit:
        os.makedirs(os.path.dirname(_audit_path()), exist_ok=True)
        with open(_audit_path(), "a", encoding="utf-8") as f:
            for a in audit:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")
    return assigned, created


def parse_mapping_tsv(path):
    """TSV:每行 `entry_id<TAB>主题1,主题2`(# 注释、空行跳过)。"""
    rows = []
    for line in _read(path).splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        ts = [t.strip() for t in parts[1].split(",") if t.strip()]
        rows.append((parts[0].strip(), ts))
    return rows


# ---- 给 AI 的候选清单(闭集分类)----
def _text(e):
    d = e.get("detail") or {}
    return " ".join([e.get("summary", ""), d.get("body", ""), d.get("opening", ""),
                     (d.get("content") or "")[:400], d.get("path", "")])


def gather(cfg, by_id, query=None, project=None, since=None, limit=60):
    """产出待归类清单 + 现有主题(供 AI 闭集分类)。默认只挑【尚未归类】的条目。"""
    pgs = pages(cfg)
    mapped = set(load_map())
    q = (query or "").lower()
    cand = []
    for eid, e in by_id.items():
        if eid in mapped or e.get("kind") == "doc":
            continue
        if (e.get("detail") or {}).get("path","").startswith("topics/"):
            continue   # 主题页自身不参与分类(防自指)
        if project and e.get("project") != project:
            continue
        if since and e.get("date", "") < since:
            continue
        if q and q not in _text(e).lower():
            continue
        cand.append(e)
    cand.sort(key=lambda e: e.get("ts", ""), reverse=True)
    cand = cand[:limit]

    out = ["# loom topic — 待归类到主题(AI 闭集分类)", ""]
    out.append("## 现有主题(尽量复用;层级见各主题页 parent)")
    if pgs:
        for tid, p in sorted(pgs.items()):
            par = ("  ⊂ " + ", ".join(p["parents"])) if p["parents"] else ""
            out.append(f"- {tid}{par}")
    else:
        out.append("(还没有主题,可新建)")
    # 给 AI 足够内部信息判断——尤其会话:带当天【全部】提问,不只首句(否则"继续梳理"这种
    # 首句会让人误判"太泛"。提交带完整改动理由,文档/数据带正文/schema)。
    _CAP = {"session": 800, "commit": 500, "report": 500}
    out += ["", f"## 待归类条目({len(cand)})"]
    for e in cand:
        d = e.get("detail") or {}
        out.append(f"- `{e['id']}`  [{e['tool']}/{e['kind']}] {e['date']} "
                   f"{e.get('summary','')[:60]}")
        raw = d.get("body") or d.get("opening") or d.get("content") or ""
        snip = " ".join(raw.split())[:_CAP.get(e.get("kind"), 220)]
        if snip:
            out.append(f"    ↳ {snip}")
    out += ["", "---",
            "AI:给每条选【最具体的叶子主题】(可多个,逗号分隔),尽量复用上面已有主题;",
            "实在不匹配才提**新叶子主题**(简短 kebab/中文名);拿不准写 `none-of-these`。",
            "输出 TSV 每行 `entry_id<TAB>主题1,主题2`,存文件后:loom topic apply --file <该文件>"]
    return "\n".join(out)


# ---- 「一件事」全景(上卷渲染)----
_TYPE_ORDER = [("report", "📋 日报"), ("session", "💬 对话"),
               ("commit", "💻 提交"), ("doc", "📄 文档"),
               ("note", "📎 数据/代码/资料")]


def show(cfg, topic, by_id):
    pgs = pages(cfg)
    tid = resolve(topic, pgs)
    if tid not in pgs:
        return f"(无此主题:{topic};loom topic ls 看已有)"
    sub = descendants(tid, pgs)
    mem = members(cfg, tid, by_id)
    info = pgs[tid]
    L = [f"# 主题:{info['title']}  ({len(mem)} 条)"]
    if info["parents"]:
        L.append("上级:" + ", ".join(info["parents"]))
    kids = sorted(t for t in sub if t != tid)
    if kids:
        L.append("子主题:" + ", ".join(kids))
    L.append("")
    by_kind = defaultdict(list)
    for e in mem:
        by_kind[e.get("kind")].append(e)
    for kind, label in _TYPE_ORDER:
        evs = by_kind.get(kind)
        if not evs:
            continue
        L.append(f"## {label} ({len(evs)})")
        for e in sorted(evs, key=lambda x: x.get("ts", "")):
            ref = (e.get("detail") or {}).get("path") or e.get("ref", "")
            L.append(f"- {e['date']} {e.get('summary','')[:56]}")
            L.append(f"    ↳ {ref}")
        L.append("")
    return "\n".join(L)


def tree(cfg):
    """列出主题树(顶层→子)。"""
    pgs = pages(cfg)
    if not pgs:
        return "(还没有主题;loom topic gather 开始归类)"
    children = defaultdict(list)
    roots = []
    for tid, p in pgs.items():
        if p["parents"]:
            for par in p["parents"]:
                children[par].append(tid)
        else:
            roots.append(tid)
    m = load_map()
    cnt = defaultdict(int)
    for ts in m.values():
        for t in ts:
            cnt[canon(t)] += 1
    lines, seen = [], set()

    def walk(t, depth):
        if t in seen:
            lines.append("  " * depth + f"- {t} ↺")
            return
        seen.add(t)
        lines.append("  " * depth + f"- {t}" + (f"  ({cnt[t]})" if cnt[t] else ""))
        for c in sorted(children.get(t, [])):
            walk(c, depth + 1)
    for r in sorted(roots):
        walk(r, 0)
    return "\n".join(lines)
