# -*- coding: utf-8 -*-
"""本地浏览页:`loom serve` 起零依赖 HTTP 服务(仅 127.0.0.1),网页里
搜索 / 主题树 / 按天 三个视角浏览自己的台账。

- 派生只读:页面只是 entries/topic_map 的视图,不写任何数据。
- 纯函数出 JSON(可测),BaseHTTPRequestHandler 只做路由;前端单文件
  vanilla JS(loom/assets/browse.html),无构建无 CDN。
"""
import json
import os
import urllib.parse
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, search, store, topics, util

_ASSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "browse.html")


def _fix(v):
    """http.server 按 latin-1 解 requestline:裸 UTF-8 查询参数会成乱码,兜底转回。"""
    try:
        return v.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return v


# ---------------------------------------------------------------- JSON 构建(纯函数,可测)
def _card(e, tmap=None):
    """条目 → 列表卡片(不含长 detail)。"""
    return {"id": e["id"], "date": e.get("date", ""), "ts": e.get("ts", ""),
            "project": e.get("project", ""), "tool": e.get("tool", ""),
            "kind": e.get("kind", ""), "summary": e.get("summary", ""),
            "ref": e.get("ref", ""), "topics": (tmap or {}).get(e["id"], [])}


def api_search(cfg, q, project=None, tool=None, since=None, until=None, limit=60):
    tmap = topics.load_map()
    hits = search.query(q or "", limit=limit, project=project or None,
                        tool=tool or None, since=since or None, until=until or None)
    out = []
    for h in hits:
        c = _card(h, tmap)
        c["snip"] = h.get("snip", "")
        out.append(c)
    return {"hits": out}


def api_topics(cfg):
    """主题树(DAG:多父节点会在每个父下出现,标 multi)。"""
    pgs = topics.pages(cfg)
    m = topics.load_map()
    direct = defaultdict(int)
    for _eid, ts in m.items():
        for t in ts:
            direct[topics.resolve(t, pgs)] += 1
    children = defaultdict(set)
    has_parent = set()
    for tid, p in pgs.items():
        for par in p["parents"]:
            children[topics.resolve(par, pgs)].add(tid)
            has_parent.add(tid)

    resolved = [set(topics.resolve(t, pgs) for t in ts) for ts in m.values()]

    def roll(tid):                                          # 上卷计数(子树内条目,DAG 去重)
        desc = topics.descendants(tid, pgs)
        return sum(1 for ts in resolved if ts & desc)

    rolls = {tid: roll(tid) for tid in pgs}

    def node(tid, seen):
        multi = len(pgs.get(tid, {}).get("parents", [])) > 1
        if tid in seen:                                     # 防环
            return {"name": tid, "count": rolls.get(tid, direct.get(tid, 0)),
                    "direct": direct.get(tid, 0), "multi": multi, "children": []}
        kids = sorted(children.get(tid, ()), key=lambda k: -rolls.get(k, 0))
        return {"name": tid, "count": rolls.get(tid, direct.get(tid, 0)),
                "direct": direct.get(tid, 0), "multi": multi,
                "children": [node(k, seen | {tid}) for k in kids]}

    roots = sorted((t for t in pgs if t not in has_parent),
                   key=lambda t: -rolls.get(t, 0))
    unfiled = [t for t in direct if t not in pgs]           # 有条目但没建页的散主题
    nodes = [{"name": t, "count": rolls.get(t, 0), "direct": direct.get(t, 0),
              "multi": len(pgs[t]["parents"]) > 1} for t in pgs]
    edges = [[topics.resolve(par, pgs), t]                  # 图视图:扁平节点+边(DAG 全边)
             for t, p in pgs.items() for par in p["parents"]]
    return {"tree": [node(r, set()) for r in roots],
            "nodes": nodes, "edges": edges,
            "loose": sorted(unfiled, key=lambda t: -direct[t]),
            "total_tagged": len(m)}


def api_topic(cfg, name, by_id):
    """某主题(含子树上卷)的成员,按类型分组。"""
    tmap = topics.load_map()
    ms = topics.members(cfg, name, by_id)
    groups = defaultdict(list)
    for e in sorted(ms, key=lambda x: x.get("ts", ""), reverse=True):
        groups[e.get("kind", "其它")].append(_card(e, tmap))
    pgs = topics.pages(cfg)
    tid = topics.resolve(name, pgs)
    return {"name": tid, "parents": pgs.get(tid, {}).get("parents", []),
            "total": len(ms), "groups": groups}


def api_days(by_id):
    """日期 → 条数(倒序;日记视图的目录)。"""
    cnt = defaultdict(int)
    for e in by_id.values():
        if e.get("date"):
            cnt[e["date"]] += 1
    return {"days": [{"date": d, "count": cnt[d]} for d in sorted(cnt, reverse=True)]}


def api_day(date, by_id):
    tmap = topics.load_map()
    es = sorted((e for e in by_id.values() if e.get("date") == date),
                key=lambda x: x.get("ts", ""))
    groups = defaultdict(list)
    for e in es:
        groups[e.get("kind", "其它")].append(_card(e, tmap))
    return {"date": date, "total": len(es), "groups": groups}


def api_stats(cfg, by_id):
    """总览:体量数字 + 工具分布 + 最近条目(首页 Dashboard 用)。"""
    tools, days, projects = defaultdict(int), set(), set()
    for e in by_id.values():
        tools[e.get("tool", "?")] += 1
        if e.get("date"):
            days.add(e["date"])
        projects.add(e.get("project", ""))
    recent = sorted(by_id.values(), key=lambda x: x.get("ts", ""), reverse=True)[:6]
    tmap = topics.load_map()
    return {"entries": len(by_id), "days": len(days),
            "topics": len(topics.pages(cfg)), "projects": len(projects),
            "tagged": len(tmap),
            "tools": dict(sorted(tools.items(), key=lambda kv: -kv[1])),
            "recent": [_card(e, tmap) for e in recent]}


def api_entry(eid, by_id):
    e = by_id.get(eid)
    if not e:
        return {"error": "not found"}
    out = dict(e)
    out["topics"] = topics.load_map().get(eid, [])
    return out


# ---------------------------------------------------------------- HTTP 层
def _make_handler(cfg):
    by_id_cache = {}

    def fresh():
        by_id_cache.clear()
        by_id_cache.update(store.load())
        return by_id_cache

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):                          # 安静;错误仍会打到 stderr
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = {k: _fix(v[0]) for k, v in urllib.parse.parse_qs(u.query).items()}
            try:
                if u.path == "/":
                    body = open(_ASSET, "rb").read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif u.path == "/api/search":
                    self._json(api_search(cfg, q.get("q", ""), q.get("project"),
                                          q.get("tool"), q.get("since"), q.get("until"),
                                          int(q.get("limit", 60))))
                elif u.path == "/api/topics":
                    self._json(api_topics(cfg))
                elif u.path == "/api/topic":
                    self._json(api_topic(cfg, q.get("name", ""), fresh()))
                elif u.path == "/api/days":
                    self._json(api_days(fresh()))
                elif u.path == "/api/day":
                    self._json(api_day(q.get("date", ""), fresh()))
                elif u.path == "/api/stats":
                    self._json(api_stats(cfg, fresh()))
                elif u.path == "/api/entry":
                    self._json(api_entry(q.get("id", ""), fresh()))
                else:
                    self._json({"error": "no route"}, 404)
            except BrokenPipeError:
                pass
            except Exception as e:                          # 单请求失败别带崩服务
                util.log(f"  [serve] {u.path} 失败: {e}")
                try:
                    self._json({"error": str(e)}, 500)
                except Exception:
                    pass

    return H


def serve(cfg, port=8787):
    srv = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(cfg))
    print(f"loom 浏览页:http://127.0.0.1:{port}  (仅本机可访问,Ctrl-C 退出)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
