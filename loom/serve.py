# -*- coding: utf-8 -*-
"""本地浏览页:`loom serve` 起零依赖 HTTP 服务(仅 127.0.0.1),网页里
搜索 / 主题树 / 按天 三个视角浏览自己的台账。

- 派生只读:页面只是 entries/topic_map 的视图,不写任何数据。
- 纯函数出 JSON(可测),BaseHTTPRequestHandler 只做路由;前端单文件
  vanilla JS(loom/assets/browse.html),无构建无 CDN。
"""
import json
import os
import contextlib
import io
import secrets
import shutil
import subprocess
import threading
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import (collectors, config, digest, render, report, search, skillsync,
               store, topics, util)

_ASSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "browse.html")
# React admin frontend (prototype/chat-ui build). When a valid dist dir exists,
# `loom serve` serves it (index.html + /assets/*) as the admin console; the
# vanilla browse.html is the zero-build fallback when no build is present.
_UI_STATIC_TYPES = {
    ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
    ".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp",
    ".ico": "image/x-icon", ".json": "application/json", ".map": "application/json",
    ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf",
}


def _ui_dir():
    """Locate the React admin build to serve, or "" to fall back to browse.html.

    Build chain: ``cd prototype/chat-ui && npm run build`` writes its output to
    ``loom/assets/ui`` (vite ``outDir``), which is what ``loom serve`` serves by
    default — no env var required. ``LOOM_DESKTOP_UI_DIR`` still overrides for
    source-served development.
    """
    # 1) explicit override (source-served during development, or a custom build)
    directory = os.environ.get("LOOM_DESKTOP_UI_DIR", "")
    if directory and os.path.isfile(os.path.join(directory, "index.html")):
        return os.path.realpath(directory)
    # 2) bundled build inside the package (loom/assets/ui) — the default admin UI.
    bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "ui")
    if os.path.isfile(os.path.join(bundled, "index.html")):
        return os.path.realpath(bundled)
    return ""
_CLOUD_IGNORE_RULES = ["_data/", ".env", "*.xlsx", "*.pptx", "*.numbers",
                       "*.pages", "*.key", "*.parquet", "*.pdf", "*.docx"]
_BINARY_CLOUD_EXTS = (".xlsx", ".pptx", ".numbers", ".pages", ".key", ".parquet",
                      ".pdf", ".docx")
_MAX_ADMIN_BODY = 64 * 1024
_WRITE_LOCK = threading.RLock()


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


def _search_page_size(page_size=None, legacy_limit=None):
    """规范搜索页大小；显式 page_size 默认 20，旧 limit 参数继续可用。"""
    raw = page_size if page_size not in (None, "") else legacy_limit
    try:
        size = int(raw) if raw not in (None, "") else 20
    except (TypeError, ValueError):
        size = 20
    if size <= 0:
        # 旧 limit 的 0/负数过去会被 search.query 夹到 1，保留这个边界行为；
        # 新分页参数无效时则回到产品默认值。
        return 1 if page_size in (None, "") and legacy_limit not in (None, "") else 20
    return min(size, 100)


def _search_page(page):
    try:
        return max(1, int(page))
    except (TypeError, ValueError):
        return 1


def api_search(cfg, q, project=None, tool=None, since=None, until=None, limit=None,
               page=1, page_size=None):
    """搜索/浏览台账，并返回稳定的分页元数据。

    ``limit`` 是旧客户端参数；未传 ``page_size`` 时仍把它当作页大小使用。
    新客户端默认每页 20 条，服务端统一封顶 100 条。
    """
    tmap = topics.load_map()
    size = _search_page_size(page_size, limit)
    requested_page = _search_page(page)
    hits, total = search.query_page(
        q or "", limit=size, offset=(requested_page - 1) * size,
        project=project or None, tool=tool or None,
        since=since or None, until=until or None)
    pages = max(1, (total + size - 1) // size)
    current_page = min(requested_page, pages)
    if current_page != requested_page:
        # 页码在删除记录或修改筛选条件后可能过期；自动落到最后一页，避免
        # 明明有数据却返回空白列表。
        hits, _ = search.query_page(
            q or "", limit=size, offset=(current_page - 1) * size,
            project=project or None, tool=tool or None,
            since=since or None, until=until or None)
    out = []
    for h in hits:
        c = _card(h, tmap)
        c["snip"] = h.get("snip", "")
        out.append(c)
    return {"hits": out, "total": total, "page": current_page,
            "page_size": size, "pages": pages}


def api_topics(cfg, by_id=None):
    """主题树(DAG:多父节点会在每个父下出现,标 multi)。

    计数只统计仍存在于事实库(store)的条目,与 ``api_topic`` /
    ``topics.members`` 完全对齐:topic_map 里指向已删除条目的陈旧映射不计入,
    否则节点角标(上卷数)会大于点开后能展示的成员数(members 只返回还在
    store 里的条目)。``by_id`` 缺省时自行加载当前快照。
    """
    if by_id is None:
        by_id = store.load()
    pgs = topics.pages(cfg)
    m = topics.load_map()
    direct = defaultdict(int)
    for eid, ts in m.items():
        if eid not in by_id:
            continue
        for t in ts:
            direct[topics.resolve(t, pgs)] += 1
    children = defaultdict(set)
    has_parent = set()
    for tid, p in pgs.items():
        for par in p["parents"]:
            children[topics.resolve(par, pgs)].add(tid)
            has_parent.add(tid)

    resolved = [set(topics.resolve(t, pgs) for t in ts)
                for eid, ts in m.items() if eid in by_id]

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
    tagged_in_store = sum(1 for eid in m if eid in by_id)
    return {"tree": [node(r, set()) for r in roots],
            "nodes": nodes, "edges": edges,
            "loose": sorted(unfiled, key=lambda t: -direct[t]),
            "total_tagged": tagged_in_store}


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


def api_home(cfg, by_id):
    """Lightweight workbench payload for the desktop/web home screen.

    Keep this deliberately cheaper than ``api_console_overview``: the home
    screen must not wait for repository probes, disk-size walks or backup
    diagnostics before it can show today's work.  Deeper checks stay in
    Settings and load only when the user opens that page.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    today_rows = [e for e in by_id.values() if e.get("date") == today]
    recent = sorted(today_rows or by_id.values(),
                    key=lambda x: x.get("ts", ""), reverse=True)[:6]
    tmap = topics.load_map()
    source_counts = defaultdict(int)
    for entry in today_rows:
        source_counts[entry.get("tool", "?")] += 1

    source_names = [name for name in collectors.names() if name != "docs"]
    available_sources = [name for name in source_names if collectors.is_syncable(name)]
    active_sources = [name for name in available_sources if _source_enabled(cfg, name)]
    latest_ts = max((e.get("ts", "") for e in by_id.values()), default="")
    return {
        "today": today,
        "today_entries": len(today_rows),
        "summarized": sum(1 for e in today_rows if (e.get("detail") or {}).get("digest")),
        "classified": sum(1 for e in today_rows if tmap.get(e.get("id", ""))),
        "source_counts": dict(sorted(source_counts.items(), key=lambda kv: -kv[1])),
        "active_sources": len(active_sources),
        "available_sources": len(available_sources),
        "total_entries": len(by_id),
        "last_record_at": latest_ts,
        "recent": [_card(e, tmap) for e in recent],
    }


def api_entry(eid, by_id):
    # 记录 id 原样即主键(git 提交为 ``git:<项目>:<短哈希>``,含冒号;文档/笔记还含
    # 斜杠、CJK)。这些字符经查询串编解码后能原样回来,直接精确命中即可;仅对偶发的
    # 首尾空白做归一,避免 Ledger 传入带换行/空格的 id 时误判「not found」。
    eid = (eid or "").strip()
    e = by_id.get(eid)
    if not e:
        return {"error": "not found"}
    out = dict(e)
    out["topics"] = topics.load_map().get(eid, [])
    out["related"] = api_related(eid, by_id, limit=12)
    return out


def api_related(eid, by_id, limit=30):
    """条目的自动派生关联(会话↔提交、共改、文档↔提交、对话续接)。"""
    from . import relations
    return relations.neighbors(by_id, (eid or "").strip(), limit=limit)


def _record_state(e, tmap):
    """给 Console 一个稳定、可解释的派生状态，不改写原始条目。"""
    detail = e.get("detail") or {}
    if detail.get("digest"):
        return "summarized"
    if tmap.get(e.get("id", "")):
        return "classified"
    return "local"


def api_console_records(by_id, q="", source="", state="", period="today", limit=100):
    """Console 记录列表；过滤只影响视图，不改变事实库。"""
    tmap = topics.load_map()
    now = datetime.now()
    since = ""
    if period == "today":
        since = now.strftime("%Y-%m-%d")
    elif period == "7d":
        since = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    elif period == "30d":
        since = (now - timedelta(days=29)).strftime("%Y-%m-%d")
    needle = (q or "").strip().lower()
    rows = []
    for e in sorted(by_id.values(), key=lambda x: x.get("ts", ""), reverse=True):
        item_state = _record_state(e, tmap)
        if since and e.get("date", "") < since:
            continue
        if source and e.get("tool", "") != source:
            continue
        if state and item_state != state:
            continue
        if needle:
            detail = e.get("detail") or {}
            hay = " ".join([e.get("summary", ""), e.get("project", ""),
                            e.get("tool", ""), e.get("kind", ""),
                            detail.get("digest", "") or ""]).lower()
            if needle not in hay:
                continue
        card = _card(e, tmap)
        card["state"] = item_state
        rows.append(card)
        if len(rows) >= max(1, min(int(limit), 500)):
            break
    return {"records": rows, "count": len(rows)}


def _path_size(path, ignore_dirs=None):
    """统计本地占用；忽略 git 对象和原始数据目录，避免把非 loom 缓存算进去。"""
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    ignored = set(ignore_dirs or ())
    total = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ignored]
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _process_rss():
    try:
        r = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())],
                           capture_output=True, text=True, timeout=3)
        return int((r.stdout or "0").strip() or "0") * 1024
    except Exception:
        return 0


def api_console_resources(cfg, by_id):
    recent_since = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    recent_bytes = sum(len(json.dumps(e, ensure_ascii=False).encode("utf-8")) + 1
                       for e in by_id.values() if e.get("date", "") >= recent_since)
    vault = config.vault_dir(cfg)
    disk = shutil.disk_usage(util.HOME if os.path.exists(util.HOME) else os.path.expanduser("~"))
    items = [
        {"id": "records", "label": "结构化记录", "bytes": _path_size(util.DATA_PATH),
         "detail": "entries.jsonl · 本地事实层"},
        {"id": "index", "label": "检索索引", "bytes": _path_size(util.INDEX_PATH),
         "detail": "SQLite FTS · 可安全重建"},
        {"id": "vault", "label": "日记与知识文档", "bytes": _path_size(vault, {".git", "_data"}),
         "detail": "不含 Git 对象与原始数据"},
        {"id": "rss", "label": "当前服务内存", "bytes": _process_rss(),
         "detail": "loom serve 进程 RSS"},
        {"id": "growth", "label": "近 7 天新增载荷", "bytes": recent_bytes,
         "detail": "按条目 JSON 大小估算"},
    ]
    return {"items": items, "disk_free": disk.free, "disk_total": disk.total}


def api_console_overview(cfg, by_id):
    # Console 首屏共享同一份主题映射和管理诊断；响应同时携带资源数据，
    # 前端无需再为同一次渲染重复请求 admin/resources。
    tmap = topics.load_map()
    admin = api_admin_overview(cfg, by_id, tmap=tmap)
    # Console 只需要连接状态，不把 app_token/table_id 等配置细节返回浏览器。
    feishu_cfg = admin.get("feishu", {})
    admin["feishu"] = {"enabled": bool(feishu_cfg.get("enabled")),
                        "bitables": [{"name": b.get("name", "")}
                                     for b in feishu_cfg.get("bitables", [])]}
    today = datetime.now().strftime("%Y-%m-%d")
    today_rows = [e for e in by_id.values() if e.get("date") == today]
    recent = sorted(today_rows or by_id.values(), key=lambda x: x.get("ts", ""), reverse=True)[:6]
    active = sum(1 for s in admin["sources"] if s["enabled"] and s["available"])
    available = sum(1 for s in admin["sources"] if s["available"])
    summarized = sum(1 for e in today_rows if (e.get("detail") or {}).get("digest"))
    classified = sum(1 for e in today_rows if tmap.get(e.get("id", "")))
    resources = api_console_resources(cfg, by_id)
    local_bytes = sum(x["bytes"] for x in resources["items"] if x["id"] in
                      ("records", "index", "vault"))
    return {
        "today": today,
        "today_entries": len(today_rows),
        "active_sources": active,
        "available_sources": available,
        "issues": len(admin["broken"]),
        "summarized": summarized,
        "classified": classified,
        "local_bytes": local_bytes,
        "recent": [dict(_card(e, tmap), state=_record_state(e, tmap)) for e in recent],
        "admin": admin,
        "resources": resources,
        "feishu_bridge": {
            "connected": False,
            "status": "planned",
            "message": "飞书账号连接与证据上传将在下一阶段接入",
        },
    }


# ---------------------------------------------------------------- 管理控制台 API(本地、显式动作、敏感动作二次确认)
def _fmt_mtime(path):
    if not os.path.exists(path):
        return ""
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")


def _git(vd, args, timeout=20):
    try:
        r = subprocess.run(["git", "-C", vd] + args, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def _is_git_repo(path):
    return config.git_worktree_info(path) is not None


def _env_key_state():
    keys = {"FEISHU_APP_ID": bool(os.environ.get("FEISHU_APP_ID")),
            "FEISHU_APP_SECRET": bool(os.environ.get("FEISHU_APP_SECRET"))}
    if os.path.exists(util.ENV_PATH):
        try:
            for line in open(util.ENV_PATH, encoding="utf-8"):
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                k = line.split("=", 1)[0].strip()
                if k in keys:
                    keys[k] = True
        except Exception:
            pass
    return keys


def _repo_rows(cfg):
    def inspect(raw):
        path = util.expand(raw)
        exists = os.path.isdir(path)
        is_git = _is_git_repo(path) if exists else False
        code, branch, _ = _git(path, ["branch", "--show-current"], timeout=5) if exists else (1, "", "")
        code2, dirty, _ = _git(path, ["status", "--short"], timeout=5) if is_git else (1, "", "")
        return {"path": path, "exists": exists, "git": is_git,
                "branch": branch if code == 0 else "",
                "dirty": bool(dirty) if code2 == 0 else False,
                "dirty_count": len([x for x in dirty.splitlines() if x.strip()])}

    repos = list(cfg.get("repos", []))
    if len(repos) < 2:
        return [inspect(raw) for raw in repos]
    # 各仓库的 git 子进程彼此独立；有限并发可显著缩短管理页等待，map 保持配置顺序。
    with ThreadPoolExecutor(max_workers=min(4, len(repos))) as pool:
        return list(pool.map(inspect, repos))


def _source_enabled(cfg, name):
    return config.source_enabled(cfg, name)


def _source_diagnostics(cfg, repos=None):
    rows, env = [], _env_key_state()
    # api_admin_overview 已经扫描过仓库时复用结果；保留独立调用兼容性。
    repos = _repo_rows(cfg) if repos is None else repos
    for name in collectors.names():
        # docs collector 和历史记录中的 tool=docs 继续保留，但管理页归入 Git 来源。
        if name == "docs":
            continue
        enabled = _source_enabled(cfg, name)
        available = collectors.is_syncable(name)
        status, msg, checks = ("off", "已关闭", [])
        if not available:
            enabled = False
            status, msg = "unavailable", "当前版本暂不支持该来源"
        elif name == "git":
            bad = [r["path"] for r in repos if not r["git"]]
            if not enabled:
                status, msg = "off", "已关闭（Git 提交与项目文档配置仍保留）"
            elif not cfg.get("repos"):
                status, msg = "warn", "未配置仓库，无法采集 Git 提交与项目文档"
            elif bad:
                status, msg = "error", f"{len(bad)} 个仓库不可采集 Git 提交与项目文档"
            else:
                status, msg = "ok", f"{len(repos)} 个仓库 · 采集 Git 提交与项目文档"
            checks = [{"label": "仓库数", "ok": bool(cfg.get("repos")), "value": len(repos)},
                      {"label": "Git 提交与项目文档", "ok": bool(repos) and not bad,
                       "value": "可采集" if repos and not bad else "不可采集"},
                      {"label": "无效仓库", "ok": not bad, "value": len(bad)}]
        elif name == "codebuddy":
            probe = collectors.codebuddy.probe(cfg)
            path = probe["extension_data"]
            count = probe["conversations"]
            if not enabled:
                status, msg = "off", f"已关闭 · 本地发现 {count} 个会话 · {path}"
            elif not probe["history_exists"]:
                status, msg = "warn", f"历史目录不存在:{path}"
            elif probe["errors"]:
                status, msg = "warn", f"发现 {count} 个会话，部分索引无法读取 · {path}"
            else:
                status, msg = "ok", f"{count} 个本地会话 · {path}"
            checks = [
                {"label": "会话历史", "ok": probe["history_exists"], "value": path},
                {"label": "会话数", "ok": not probe["errors"], "value": count},
                {"label": "元数据库", "ok": probe["session_db_exists"],
                 "value": probe["session_db"]},
            ]
        elif name == "feishu":
            fs = cfg.get("feishu", {})
            bits = fs.get("bitables", [])
            missing_secret = [k for k, v in env.items() if not v]
            broken_bits = [b.get("name", "") for b in bits
                           if not b.get("app_token") or not b.get("table_id")]
            if not enabled:
                status, msg = "off", "未启用"
            elif missing_secret:
                status, msg = "error", "缺 FEISHU_APP_ID/FEISHU_APP_SECRET"
            elif not bits:
                status, msg = "warn", "已启用但未配置多维表格"
            elif broken_bits:
                status, msg = "error", f"{len(broken_bits)} 个表缺 token/table"
            else:
                status, msg = "ok", f"{len(bits)} 个多维表格"
            checks = [{"label": "凭证在 .env", "ok": not missing_secret,
                       "value": "齐全" if not missing_secret else ",".join(missing_secret)},
                      {"label": "表配置", "ok": bool(bits) and not broken_bits, "value": len(bits)}]
        else:
            src = cfg.get("sources", {}).get(name, {})
            if name in ("claude", "codex", "cursor", "pi", "opencode"):
                key = {"claude": "projects_dir", "codex": "home",
                       "cursor": "app_support", "pi": "sessions_dir",
                       "opencode": "data_dir"}[name]
                path = util.expand(src.get(key, ""))
                ok = bool(path and os.path.exists(path))
                if not enabled:
                    status, msg = "off", f"已关闭 · {path or key}"
                else:
                    status, msg = ("ok", path) if ok else ("warn", f"路径不存在:{path or key}")
                checks = [{"label": key, "ok": ok, "value": path}]
            elif not enabled:
                status, msg = "off", "已关闭"
            elif name == "notes":
                path = config.notes_dir(cfg)
                ok = os.path.isdir(path)
                status, msg = ("ok", path) if ok else ("warn", f"目录不存在:{path}")
                checks = [{"label": "notes 目录", "ok": ok, "value": path}]
        rows.append({"name": name, "category": collectors.source_category(name),
                     "enabled": enabled, "configured_enabled": _source_enabled(cfg, name),
                     "available": available,
                     "status": status,
                     "message": msg, "checks": checks})
    return rows


def _collection_status(cfg, by_id, tmap=None):
    tools, kinds, projects, dates = defaultdict(int), defaultdict(int), defaultdict(int), []
    for e in by_id.values():
        tools[e.get("tool", "?")] += 1
        kinds[e.get("kind", "?")] += 1
        projects[e.get("project", "") or "(空)"] += 1
        if e.get("date"):
            dates.append(e["date"])
    data_m = os.path.getmtime(util.DATA_PATH) if os.path.exists(util.DATA_PATH) else 0
    idx_m = os.path.getmtime(util.INDEX_PATH) if os.path.exists(util.INDEX_PATH) else 0
    recent = sorted(by_id.values(), key=lambda x: x.get("ts", ""), reverse=True)[:8]
    tmap = topics.load_map() if tmap is None else tmap
    return {"entries": len(by_id), "date_start": min(dates) if dates else "",
            "date_end": max(dates) if dates else "",
            "tools": dict(sorted(tools.items(), key=lambda kv: -kv[1])),
            "kinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
            "projects": dict(sorted(projects.items(), key=lambda kv: -kv[1])[:12]),
            "data_path": util.DATA_PATH, "data_mtime": _fmt_mtime(util.DATA_PATH),
            "index_path": util.INDEX_PATH, "index_mtime": _fmt_mtime(util.INDEX_PATH),
            "index_ready": os.path.exists(util.INDEX_PATH) and idx_m >= data_m,
            "recent": [_card(e, tmap) for e in recent]}


def _is_cloud_risky(path):
    p = path.strip("/")
    return p == ".env" or p.startswith("_data/") or p.endswith(_BINARY_CLOUD_EXTS)


def _vault_status(cfg):
    vd = config.vault_dir(cfg)
    exists = os.path.isdir(vd)
    is_git = os.path.isdir(os.path.join(vd, ".git"))
    gi = os.path.join(vd, ".gitignore")
    lines = open(gi, encoding="utf-8").read().splitlines() if os.path.exists(gi) else []
    have = {ln.strip() for ln in lines}
    tracked, ignored, dirty, remotes = [], [], "", []
    if is_git:
        _, out, _ = _git(vd, ["ls-files"], timeout=10)
        tracked = [x for x in out.splitlines() if x.strip()]
        _, out, _ = _git(vd, ["ls-files", "-i", "-c", "--exclude-standard"], timeout=10)
        ignored = [x for x in out.splitlines() if x.strip()]
        _, dirty, _ = _git(vd, ["status", "--short"], timeout=10)
        _, rout, _ = _git(vd, ["remote", "-v"], timeout=10)
        remotes = [x for x in rout.splitlines() if x.strip()]
    return {"dir": vd, "exists": exists, "git": is_git, "dirty": bool(dirty),
            "dirty_count": len([x for x in dirty.splitlines() if x.strip()]),
            "remote_config": cfg.get("vault", {}).get("remote", ""),
            "git_remotes": remotes,
            "gitignore": {"path": gi, "exists": os.path.exists(gi),
                          "missing": [p for p in _CLOUD_IGNORE_RULES if p not in have]},
            "tracked_count": len(tracked),
            "tracked_sample": tracked[:80],
            "tracked_risky": [p for p in tracked if _is_cloud_risky(p)][:80],
            "tracked_ignored": ignored[:80],
            "will_cloud": ["journal/*.md", "notes/**/*.md", "notes/topics/*.md",
                           ".gitignore", "其它未被 .gitignore 排除的文本知识层文件"],
            "local_only": [util.ENV_PATH, util.DATA_PATH, util.INDEX_PATH,
                           os.path.join(vd, "_data/"), "*.xlsx/*.pdf/*.docx 等原始/二进制文件"]}


def _broken_items(sources, repos, vault, collected):
    items = []
    for s in sources:
        if s["status"] in ("error", "warn"):
            items.append({"severity": "error" if s["status"] == "error" else "warn",
                          "area": "source", "title": s["name"], "detail": s["message"]})
    for r in repos:
        if not r["exists"] or not r["git"]:
            items.append({"severity": "error", "area": "repo",
                          "title": os.path.basename(r["path"]) or r["path"],
                          "detail": "路径不存在或不是普通 .git 仓"})
    if vault["gitignore"]["missing"]:
        items.append({"severity": "warn", "area": "cloud", "title": "vault .gitignore 不完整",
                      "detail": ", ".join(vault["gitignore"]["missing"])})
    if vault["tracked_risky"]:
        items.append({"severity": "error", "area": "cloud", "title": "有本地专属文件已被 git 跟踪",
                      "detail": ", ".join(vault["tracked_risky"][:5])})
    if not collected["index_ready"]:
        items.append({"severity": "warn", "area": "search", "title": "检索索引缺失或落后",
                      "detail": "运行 loom sync 或在控制台手动 sync"})
    return items


def api_admin_overview(cfg, by_id, tmap=None):
    repos = _repo_rows(cfg)
    sources = _source_diagnostics(cfg, repos)
    vault = _vault_status(cfg)
    collected = _collection_status(cfg, by_id, tmap=tmap)
    env = _env_key_state()
    cfg_exists = os.path.exists(util.CONFIG_PATH)
    env_mode = ""
    if os.path.exists(util.ENV_PATH):
        env_mode = oct(os.stat(util.ENV_PATH).st_mode & 0o777)
    return {"config": {"home": util.HOME, "config_path": util.CONFIG_PATH,
                       "config_exists": cfg_exists, "env_path": util.ENV_PATH,
                       "env_exists": os.path.exists(util.ENV_PATH),
                       "env_mode": env_mode, "env_keys": env,
                       "redact": cfg.get("redact", True),
                       "default_since_days": cfg.get("default_since_days", 100),
                       "owner": cfg.get("owner", {})},
            "collected": collected, "sources": sources, "repos": repos,
            "identities": cfg.get("identities", {"emails": [], "names": []}),
            "feishu": cfg.get("feishu", {}),
            "vault": vault,
            "broken": _broken_items(sources, repos, vault, collected)}


def api_skills(cfg):
    """loom-skill 安装状态(每个 AI 助手一行)。只读,不写任何文件。"""
    return {"ok": True, "agents": skillsync.status(cfg)}


def _capture(fn, *args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = fn(*args, **kwargs)
    text = out.getvalue().strip()
    etext = err.getvalue().strip()
    return result, (text + ("\n" + etext if etext else "")).strip()


def _confirm(payload, word):
    return str(payload.get("confirm", "")).strip().lower() == word


def _finish_action(cfg, ok=True, message="", output="", **extra):
    # 旧前端只用 overview 的 truthy 值触发 loadAdmin；返回轻量刷新信号，
    # 避免动作结束时先完整扫描一次、随后页面刷新又扫描一次。
    result = {"ok": ok, "message": message, "output": output,
              "overview": {"refresh": True}, "refresh": True}
    result.update(extra)
    return result


def _sync_source_result(name, raw):
    """Normalize old list collectors and newer diagnostic collector results."""
    if not isinstance(raw, dict):
        return list(raw or []), {"name": name, "status": "success", "count": len(raw or []),
                                 "message": "", "errors": []}
    entries = list(raw.get("entries") or [])
    errors = [str(e).strip() for e in (raw.get("errors") or []) if str(e).strip()]
    status = raw.get("status")
    if status not in ("success", "partial", "error"):
        status = "partial" if entries and errors else "error" if errors else "success"
    message = str(raw.get("message") or ("; ".join(errors[:3]) if errors else ""))
    return entries, {"name": name, "status": status, "count": len(entries),
                     "message": message, "errors": errors}


def _manual_sync(cfg, payload):
    source = payload.get("source") or "all"
    if source != "all" and source not in collectors.REGISTRY:
        return _finish_action(cfg, False, f"未知来源:{source}")
    push = bool(payload.get("push"))
    if push and not _confirm(payload, "push"):
        return {"ok": False, "needs_confirm": "push",
                "message": "push 会把 vault git 推到 remote,需要二次确认"}
    util.load_env()
    since = payload.get("since") or util.since_date(cfg.get("default_since_days", 100))
    requested_sources = payload.get("sources")
    if requested_sources is not None:
        if not isinstance(requested_sources, list):
            return _finish_action(cfg, False, "sources 必须是来源名称数组")
        srcs = []
        for value in requested_sources[:20]:
            name = str(value or "")
            if name not in collectors.REGISTRY or not collectors.is_syncable(name):
                return _finish_action(cfg, False, f"未知或不可采集来源:{name}")
            if name not in srcs:
                srcs.append(name)
        # Git and repository documents are one product source.  A scoped first
        # sync therefore refreshes both halves without widening to other sources.
        if "git" in srcs and "docs" in collectors.REGISTRY and "docs" not in srcs:
            srcs.append("docs")
    elif source == "all":
        srcs = [s for s in collectors.sync_names() if _source_enabled(cfg, s)]
    elif source == "git":
        # 管理页只展示 Git；单独同步 Git 时仍同时更新仓库内项目文档索引。
        srcs = ["git"]
        if "docs" in collectors.REGISTRY and collectors.is_syncable("docs"):
            srcs.append("docs")
    else:
        srcs = [source]
    if not srcs:
        sync = {"requested": source, "since": since, "status": "error", "collected": 0,
                "library_total": len(store.load()), "sources": []}
        return _finish_action(cfg, False, "没有已开启的数据来源", status="error", sync=sync)
    by_id = store.load()
    lines, total, source_results = [], 0, []
    for s in srcs:
        try:
            collector = getattr(collectors, "DIAGNOSTIC_REGISTRY", {}).get(
                s, collectors.REGISTRY[s])
            collector_cfg = cfg
            if s == "docs":
                # 兼容曾经单独关闭 docs 的旧配置；管理端以 Git 开关为唯一真相源。
                collector_cfg = dict(cfg)
                collector_cfg["sources"] = dict(cfg.get("sources", {}))
                collector_cfg["sources"]["docs"] = dict(
                    cfg.get("sources", {}).get("docs", {}),
                    enabled=_source_enabled(cfg, "docs"))
            got, result = _sync_source_result(s, collector(collector_cfg, since))
        except Exception as e:
            result = {"name": s, "status": "error", "count": 0,
                      "message": str(e), "errors": [str(e)]}
            source_results.append(result)
            lines.append(f"[{s}] 采集失败:{e}")
            continue
        if cfg.get("redact", True):
            got = [util.redact_entry(e) for e in got]
        if got:
            store.upsert(by_id, got)
        total += len(got)
        source_results.append(result)
        if result["status"] == "success":
            lines.append(f"[{s}] {len(got)} 条")
        elif result["status"] == "partial":
            lines.append(f"[{s}] 部分完成:{len(got)} 条; {result['message']}")
        else:
            lines.append(f"[{s}] 采集失败:{result['message']}")
    nd = digest.apply_all(by_id)
    store.save(by_id)
    search.rebuild()
    days = render.build(cfg, by_id)
    lines.append(f"[digest] 覆盖 {nd} 条")
    lines.append(f"[render] {days} 个日记")
    lines.append(f"采集完成:本轮 {total} 条,库内共 {len(by_id)} 条(since {since})")
    backup_result = None
    if payload.get("backup", True):
        from . import cli as cli_mod
        backup_result, out = _capture(cli_mod.vault_git, cfg, push)
        if out:
            lines.append(out)
    statuses = [r["status"] for r in source_results]
    status = ("success" if statuses and all(s == "success" for s in statuses)
              else "error" if statuses and all(s == "error" for s in statuses)
              else "partial")
    if backup_result and not backup_result.get("ok") and status != "error":
        status = "partial"
    message = {"success": "同步完成", "partial": "同步部分完成",
               "error": "同步失败"}[status]
    sync = {"requested": source, "since": since, "status": status, "collected": total,
            "library_total": len(by_id), "sources": source_results}
    if backup_result is not None:
        sync["backup"] = backup_result
    return _finish_action(cfg, status == "success", message, "\n".join(lines),
                          status=status, sync=sync)


def api_admin_action(cfg, payload):
    """所有管理写操作串行化，避免 ThreadingHTTPServer 并发写同一份状态。"""
    with _WRITE_LOCK:
        return _api_admin_action(cfg, payload)


def _api_admin_action(cfg, payload):
    payload = payload or {}
    action = payload.get("action", "")
    try:
        if action == "sync":
            return _manual_sync(cfg, payload)
        if action == "vault_backup":
            push = bool(payload.get("push"))
            if push and not _confirm(payload, "push"):
                return {"ok": False, "needs_confirm": "push",
                        "message": "push 会把 vault git 推到 remote,需要二次确认"}
            from . import cli as cli_mod
            backup, out = _capture(cli_mod.vault_git, cfg, push)
            status = "success" if backup.get("ok") else "error"
            return _finish_action(cfg, backup.get("ok", False), backup.get("message", ""), out,
                                  status=status, backup=backup)
        if action == "repo_add":
            path = config.add_repo(cfg, payload.get("path", ""))
            config.save(cfg)
            return _finish_action(cfg, True, f"已加入 repo:{path}")
        if action == "repo_remove":
            if not _confirm(payload, "remove"):
                return {"ok": False, "needs_confirm": "remove",
                        "message": "移除 repo 配置需要二次确认(不删除本地仓库)"}
            config.rm_repo(cfg, payload.get("path", ""))
            config.save(cfg)
            return _finish_action(cfg, True, "已移除 repo 配置")
        if action == "identity_add":
            v = str(payload.get("value", "")).strip()
            if not v:
                return _finish_action(cfg, False, "身份不能为空")
            bucket = "emails" if "@" in v else "names"
            cfg.setdefault("identities", {}).setdefault(bucket, [])
            if v not in cfg["identities"][bucket]:
                cfg["identities"][bucket].append(v)
            config.save(cfg)
            return _finish_action(cfg, True, f"已加入 {bucket}:{v}")
        if action == "identity_remove":
            if not _confirm(payload, "remove"):
                return {"ok": False, "needs_confirm": "remove",
                        "message": "移除身份会影响后续 git 采集过滤,需要二次确认"}
            v = str(payload.get("value", "")).strip()
            ids = cfg.setdefault("identities", {"emails": [], "names": []})
            ids["emails"] = [x for x in ids.get("emails", []) if x != v]
            ids["names"] = [x for x in ids.get("names", []) if x != v]
            config.save(cfg)
            return _finish_action(cfg, True, "已移除身份")
        if action == "source_set":
            name = payload.get("name")
            enabled = bool(payload.get("enabled"))
            if name == "feishu":
                cfg.setdefault("feishu", {})["enabled"] = enabled
            elif name == "git":
                sources = cfg.setdefault("sources", {})
                sources.setdefault("git", {})["enabled"] = enabled
                # 同步写回兼容字段，避免旧版 CLI/第三方调用绕过产品级 Git 开关。
                sources.setdefault("docs", {})["enabled"] = enabled
            elif name in collectors.REGISTRY:
                cfg.setdefault("sources", {}).setdefault(name, {})["enabled"] = enabled
            else:
                return _finish_action(cfg, False, f"未知来源:{name}")
            config.save(cfg)
            return _finish_action(cfg, True, f"{name} -> {'enable' if enabled else 'disable'}")
        if action == "source_path_set":
            name = str(payload.get("name", ""))
            keys = {"claude": "projects_dir", "codex": "home",
                    "cursor": "app_support", "codebuddy": "extension_data",
                    "pi": "sessions_dir", "opencode": "data_dir", "notes": "dir"}
            if name not in keys:
                return _finish_action(cfg, False, f"该来源不支持独立路径:{name}")
            path = os.path.abspath(util.expand(str(payload.get("path", "")).strip()))
            if not os.path.isdir(path):
                return _finish_action(cfg, False, f"目录不存在:{path}")
            cfg.setdefault("sources", {}).setdefault(name, {})[keys[name]] = path
            config.save(cfg)
            return _finish_action(cfg, True, f"已更新 {name} 扫描目录")
        if action == "feishu_add":
            url = str(payload.get("url", "")).strip()
            app_token = str(payload.get("app_token", "")).strip()
            table_id = str(payload.get("table_id", "")).strip()
            if url:
                parsed_token, table_id_from_url = config.parse_bitable_url(url)
                app_token = parsed_token or app_token or url
                table_id = table_id or (table_id_from_url or "")
            name = str(payload.get("name", "")).strip() or "需求池"
            if not app_token or not table_id:
                return _finish_action(cfg, False, "缺 app_token/table_id")
            config.add_bitable(cfg, name, app_token, table_id)
            config.save(cfg)
            return _finish_action(cfg, True, f"已加入飞书表:{name}")
        if action == "feishu_remove":
            if not _confirm(payload, "remove"):
                return {"ok": False, "needs_confirm": "remove",
                        "message": "移除飞书表配置需要二次确认"}
            name = str(payload.get("name", ""))
            fs = cfg.setdefault("feishu", {})
            fs["bitables"] = [b for b in fs.get("bitables", []) if b.get("name") != name]
            config.save(cfg)
            return _finish_action(cfg, True, "已移除飞书表配置")
        if action == "owner_set":
            owner = cfg.setdefault("owner", {})
            owner["name"] = str(payload.get("name", owner.get("name", ""))).strip()
            owner["feishu_name"] = str(payload.get("feishu_name", owner.get("feishu_name", ""))).strip()
            config.save(cfg)
            return _finish_action(cfg, True, "已更新身份负责人")
        if action == "pref_set":
            # 界面偏好(主题/语言)只影响管理页渲染,不改变采集内容。
            ui = cfg.setdefault("ui", {})
            theme = str(payload.get("theme", ui.get("theme", "system"))).strip()
            lang = str(payload.get("lang", ui.get("lang", "system"))).strip()
            if theme not in ("system", "light", "dark"):
                return _finish_action(cfg, False, f"未知主题:{theme}")
            if lang not in ("system", "zh", "en"):
                return _finish_action(cfg, False, f"未知语言:{lang}")
            ui["theme"], ui["lang"] = theme, lang
            config.save(cfg)
            return {"ok": True, "message": "已保存界面偏好", "ui": ui}
        if action in ("skill_install", "skill_uninstall"):
            # 把 loom-skill 装进/移出 AI 助手(可逆、会先备份)。复用 CLI 的 skillsync。
            do_install = action == "skill_install"
            selector = str(payload.get("agent", "")).strip() or "all"
            try:
                keys = skillsync.resolve_agents(selector, cfg, for_install=do_install)
            except Exception:
                return _finish_action(cfg, False, f"未知 agent:{selector}")
            if do_install:
                results = [skillsync.install(k, cfg) for k in keys]
            else:
                force = bool(payload.get("force"))
                results = [skillsync.uninstall(k, cfg, force=force) for k in keys]
            ok = all(r.get("ok", True) for r in results)
            return {"ok": ok, "results": results, "agents": skillsync.status(cfg),
                    "refresh": True, "overview": {"refresh": True}}
        if action == "report_material":
            # 导出某天的原材料(供外部 AI / 飞书 agent 写日报)。本地只读聚合,不做生成。
            date = str(payload.get("date", "")).strip() or datetime.now().strftime("%Y-%m-%d")
            material = report.gen_material(cfg, date)
            return {"ok": True, "date": date, "material": material}
        return _finish_action(cfg, False, f"未知动作:{action}")
    except Exception as e:
        return _finish_action(cfg, False, str(e))


# ---------------------------------------------------------------- HTTP 层
def _make_handler(cfg, admin_token=None):
    admin_token = admin_token or secrets.token_urlsafe(32)

    def fresh():
        # ThreadingHTTPServer 的并发请求各自持有独立快照，避免一个请求在
        # 另一个请求迭代期间 clear/update 同一字典。
        return store.load()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):                          # 安静;错误仍会打到 stderr
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _loopback_host(self):
            """Host 头是否指向本机回环。挡 DNS-rebinding:恶意站点把自己的域名
            重绑到 127.0.0.1 后,浏览器发来的 Host 仍是攻击者域名(非回环),据此拒绝。"""
            host = self.headers.get("Host", "")
            return (host.startswith("127.0.0.1:") or host.startswith("localhost:")
                    or host in ("127.0.0.1", "localhost"))

        def _console_authorized(self):
            token_ok = secrets.compare_digest(self.headers.get("X-Loom-Token", ""),
                                              admin_token)
            return self._loopback_host() and token_ok

        def _html(self, body):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "img-src 'self' data:; "
                             "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _static(self, root, path):
            rel = path.lstrip("/")
            full = os.path.realpath(os.path.join(root, rel))
            if not (full == root or full.startswith(root + os.sep)) or not os.path.isfile(full):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            ctype = _UI_STATIC_TYPES.get(os.path.splitext(full)[1].lower(),
                                         "application/octet-stream")
            with open(full, "rb") as handle:
                body = handle.read()
            self.send_response(200)
            self.send_header("Content-Type",
                             ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = {k: _fix(v[0]) for k, v in urllib.parse.parse_qs(u.query).items()}
            ui = _ui_dir()
            try:
                # 所有数据端点仅限本机回环访问,挡 DNS-rebinding 跨站读取台账。
                # 静态资源(/、/assets)不含数据,不受影响。
                if u.path.startswith("/api/") and not self._loopback_host():
                    self._json({"error": "forbidden", "message": "仅限本机访问"}, 403)
                    return
                if ui and (u.path.startswith("/assets/")
                           or u.path in ("/favicon.svg", "/favicon.ico", "/vite.svg")):
                    self._static(ui, u.path)
                elif u.path in ("/", "/browse"):
                    source = os.path.join(ui, "index.html") if ui else _ASSET
                    with open(source, "rb") as handle:
                        body = handle.read()
                    self._html(body)
                elif u.path == "/api/search":
                    self._json(api_search(cfg, q.get("q", ""), q.get("project"),
                                          q.get("tool"), q.get("since"), q.get("until"),
                                          limit=q.get("limit"), page=q.get("page", 1),
                                          page_size=q.get("page_size")))
                elif u.path == "/api/topics":
                    self._json(api_topics(cfg, fresh()))
                elif u.path == "/api/topic":
                    self._json(api_topic(cfg, q.get("name", ""), fresh()))
                elif u.path == "/api/days":
                    self._json(api_days(fresh()))
                elif u.path == "/api/day":
                    self._json(api_day(q.get("date", ""), fresh()))
                elif u.path == "/api/stats":
                    self._json(api_stats(cfg, fresh()))
                elif u.path == "/api/home":
                    self._json(api_home(cfg, fresh()))
                elif u.path == "/api/entry":
                    self._json(api_entry(q.get("id", ""), fresh()))
                elif u.path == "/api/related":
                    self._json({"related": api_related(q.get("id", ""), fresh())})
                elif u.path == "/api/admin/overview":
                    if not self._console_authorized():
                        self._json({"error": "forbidden", "message": "Console 会话无效"}, 403)
                    else:
                        self._json(api_admin_overview(cfg, fresh()))
                elif u.path == "/api/admin/skills":
                    if not self._console_authorized():
                        self._json({"error": "forbidden", "message": "Console 会话无效"}, 403)
                    else:
                        self._json(api_skills(cfg))
                elif u.path.startswith("/api/console/v1/") and not self._console_authorized():
                    self._json({"error": "forbidden", "message": "Console 会话无效"}, 403)
                elif u.path == "/api/console/v1/overview":
                    self._json(api_console_overview(cfg, fresh()))
                elif u.path == "/api/console/v1/records":
                    self._json(api_console_records(fresh(), q.get("q", ""),
                                                   q.get("source", ""),
                                                   q.get("state", ""),
                                                   q.get("period", "today"),
                                                   int(q.get("limit", 100))))
                elif u.path == "/api/console/v1/resources":
                    self._json(api_console_resources(cfg, fresh()))
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

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            try:
                if u.path != "/api/admin/action":
                    self._json({"error": "no route"}, 404)
                    return
                if not secrets.compare_digest(self.headers.get("X-Loom-Token", ""),
                                              admin_token):
                    self._json({"ok": False, "error": "forbidden",
                                "message": "管理会话无效,请使用本次 loom serve 输出的地址重新打开"}, 403)
                    return
                origin = self.headers.get("Origin", "")
                if origin:
                    parsed = urllib.parse.urlparse(origin)
                    if parsed.scheme != "http" or parsed.netloc != self.headers.get("Host", ""):
                        self._json({"ok": False, "error": "bad_origin",
                                    "message": "拒绝来自其它网页的管理请求"}, 403)
                        return
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json":
                    self._json({"ok": False, "error": "unsupported_media_type",
                                "message": "管理接口只接受 application/json"}, 415)
                    return
                n = int(self.headers.get("Content-Length", "0") or "0")
                if n <= 0 or n > _MAX_ADMIN_BODY:
                    self._json({"ok": False, "error": "invalid_body_size",
                                "message": "管理请求体为空或超过 64 KiB"}, 413)
                    return
                raw = self.rfile.read(n)
                payload = json.loads(raw.decode("utf-8"))
                self._json(api_admin_action(cfg, payload))
            except BrokenPipeError:
                pass
            except Exception as e:
                util.log(f"  [serve] {u.path} 失败: {e}")
                try:
                    self._json({"error": str(e)}, 500)
                except Exception:
                    pass

    return H


def serve(cfg, port=8787):
    admin_token = secrets.token_urlsafe(32)
    srv = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(cfg, admin_token))
    url = f"http://127.0.0.1:{port}/?token={urllib.parse.quote(admin_token)}"
    print(f"loom 浏览页:{url}  (仅本机可访问,Ctrl-C 退出)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
