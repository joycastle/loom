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
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import collectors, config, digest, render, search, store, topics, util

_ASSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "browse.html")
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
    admin = api_admin_overview(cfg, by_id)
    # Console 只需要连接状态，不把 app_token/table_id 等配置细节返回浏览器。
    feishu_cfg = admin.get("feishu", {})
    admin["feishu"] = {"enabled": bool(feishu_cfg.get("enabled")),
                        "bitables": [{"name": b.get("name", "")}
                                     for b in feishu_cfg.get("bitables", [])]}
    today = datetime.now().strftime("%Y-%m-%d")
    tmap = topics.load_map()
    today_rows = [e for e in by_id.values() if e.get("date") == today]
    recent = sorted(today_rows or by_id.values(), key=lambda x: x.get("ts", ""), reverse=True)[:6]
    active = sum(1 for s in admin["sources"] if s["enabled"])
    summarized = sum(1 for e in today_rows if (e.get("detail") or {}).get("digest"))
    classified = sum(1 for e in today_rows if tmap.get(e.get("id", "")))
    resources = api_console_resources(cfg, by_id)
    local_bytes = sum(x["bytes"] for x in resources["items"] if x["id"] in
                      ("records", "index", "vault"))
    return {
        "today": today,
        "today_entries": len(today_rows),
        "active_sources": active,
        "issues": len(admin["broken"]),
        "summarized": summarized,
        "classified": classified,
        "local_bytes": local_bytes,
        "recent": [dict(_card(e, tmap), state=_record_state(e, tmap)) for e in recent],
        "admin": admin,
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
    code, out, _ = _git(path, ["rev-parse", "--is-inside-work-tree"], timeout=5)
    return code == 0 and out == "true"


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
    rows = []
    for raw in cfg.get("repos", []):
        path = util.expand(raw)
        exists = os.path.isdir(path)
        is_git = _is_git_repo(path) if exists else False
        code, branch, _ = _git(path, ["branch", "--show-current"], timeout=5) if exists else (1, "", "")
        code2, dirty, _ = _git(path, ["status", "--short"], timeout=5) if is_git else (1, "", "")
        rows.append({"path": path, "exists": exists, "git": is_git,
                     "branch": branch if code == 0 else "",
                     "dirty": bool(dirty) if code2 == 0 else False,
                     "dirty_count": len([x for x in dirty.splitlines() if x.strip()])})
    return rows


def _source_enabled(cfg, name):
    if name == "git":
        return bool(cfg.get("repos"))
    if name == "feishu":
        return bool(cfg.get("feishu", {}).get("enabled"))
    return bool(cfg.get("sources", {}).get(name, {}).get("enabled"))


def _source_diagnostics(cfg):
    rows, env = [], _env_key_state()
    repos = _repo_rows(cfg)
    for name in collectors.names():
        enabled = _source_enabled(cfg, name)
        status, msg, checks = ("off", "已关闭", [])
        if name == "git":
            bad = [r["path"] for r in repos if not r["git"]]
            if not cfg.get("repos"):
                status, msg = "warn", "未配置 repo"
            elif bad:
                status, msg = "error", f"{len(bad)} 个 repo 不可采集"
            else:
                status, msg = "ok", f"{len(repos)} 个 repo"
            checks = [{"label": "repo 数", "ok": bool(cfg.get("repos")), "value": len(repos)},
                      {"label": "无效 repo", "ok": not bad, "value": len(bad)}]
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
            if not enabled:
                status, msg = "off", "已关闭"
            elif name in ("claude", "codex", "cursor", "codebuddy"):
                key = "home" if name == "codex" else ("projects_dir" if name == "claude" else "app_support")
                path = util.expand(src.get(key, ""))
                ok = bool(path and os.path.exists(path))
                status, msg = ("ok", path) if ok else ("warn", f"路径不存在:{path or key}")
                checks = [{"label": key, "ok": ok, "value": path}]
            elif name == "notes":
                path = config.notes_dir(cfg)
                ok = os.path.isdir(path)
                status, msg = ("ok", path) if ok else ("warn", f"目录不存在:{path}")
                checks = [{"label": "notes 目录", "ok": ok, "value": path}]
            elif name == "docs":
                bad = [r["path"] for r in repos if not r["exists"]]
                status, msg = ("ok", f"{len(repos)} 个 repo") if repos and not bad else \
                              ("warn", "没有可扫的 repo")
                checks = [{"label": "repo 数", "ok": bool(repos), "value": len(repos)}]
        rows.append({"name": name, "enabled": enabled, "status": status,
                     "message": msg, "checks": checks})
    return rows


def _collection_status(cfg, by_id):
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
    return {"entries": len(by_id), "date_start": min(dates) if dates else "",
            "date_end": max(dates) if dates else "",
            "tools": dict(sorted(tools.items(), key=lambda kv: -kv[1])),
            "kinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
            "projects": dict(sorted(projects.items(), key=lambda kv: -kv[1])[:12]),
            "data_path": util.DATA_PATH, "data_mtime": _fmt_mtime(util.DATA_PATH),
            "index_path": util.INDEX_PATH, "index_mtime": _fmt_mtime(util.INDEX_PATH),
            "index_ready": os.path.exists(util.INDEX_PATH) and idx_m >= data_m,
            "recent": [_card(e, topics.load_map()) for e in recent]}


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


def api_admin_overview(cfg, by_id):
    repos = _repo_rows(cfg)
    sources = _source_diagnostics(cfg)
    vault = _vault_status(cfg)
    collected = _collection_status(cfg, by_id)
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


def _capture(fn, *args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = fn(*args, **kwargs)
    text = out.getvalue().strip()
    etext = err.getvalue().strip()
    return result, (text + ("\n" + etext if etext else "")).strip()


def _confirm(payload, word):
    return str(payload.get("confirm", "")).strip().lower() == word


def _finish_action(cfg, ok=True, message="", output=""):
    return {"ok": ok, "message": message, "output": output,
            "overview": api_admin_overview(cfg, store.load())}


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
    srcs = collectors.names() if source == "all" else [source]
    by_id = store.load()
    lines, total = [], 0
    for s in srcs:
        try:
            got = collectors.REGISTRY[s](cfg, since)
        except Exception as e:
            lines.append(f"[{s}] 采集失败:{e}")
            continue
        if cfg.get("redact", True):
            got = [util.redact_entry(e) for e in got]
        if got:
            store.upsert(by_id, got)
        total += len(got)
        lines.append(f"[{s}] {len(got)} 条")
    nd = digest.apply_all(by_id)
    store.save(by_id)
    search.rebuild()
    days = render.build(cfg, by_id)
    lines.append(f"[digest] 覆盖 {nd} 条")
    lines.append(f"[render] {days} 个日记")
    lines.append(f"采集完成:本轮 {total} 条,库内共 {len(by_id)} 条(since {since})")
    if payload.get("backup", True):
        from . import cli as cli_mod
        _, out = _capture(cli_mod.vault_git, cfg, push)
        if out:
            lines.append(out)
    return _finish_action(cfg, True, "sync 完成", "\n".join(lines))


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
            _, out = _capture(cli_mod.vault_git, cfg, push)
            return _finish_action(cfg, True, "vault 备份完成", out)
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
            if name == "git":
                return _finish_action(cfg, False, "git 来源由 repo 列表决定")
            if name == "feishu":
                cfg.setdefault("feishu", {})["enabled"] = enabled
            elif name in collectors.REGISTRY:
                cfg.setdefault("sources", {}).setdefault(name, {})["enabled"] = enabled
            else:
                return _finish_action(cfg, False, f"未知来源:{name}")
            config.save(cfg)
            return _finish_action(cfg, True, f"{name} -> {'enable' if enabled else 'disable'}")
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
        return _finish_action(cfg, False, f"未知动作:{action}")
    except Exception as e:
        return _finish_action(cfg, False, str(e))


# ---------------------------------------------------------------- HTTP 层
def _make_handler(cfg, admin_token=None):
    admin_token = admin_token or secrets.token_urlsafe(32)
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
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _console_authorized(self):
            host = self.headers.get("Host", "")
            local_host = host.startswith("127.0.0.1:") or host.startswith("localhost:")
            token_ok = secrets.compare_digest(self.headers.get("X-Loom-Token", ""),
                                              admin_token)
            return local_host and token_ok

        def _html(self, body):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = {k: _fix(v[0]) for k, v in urllib.parse.parse_qs(u.query).items()}
            try:
                if u.path in ("/", "/browse"):
                    body = open(_ASSET, "rb").read()
                    self._html(body)
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
                elif u.path == "/api/admin/overview":
                    self._json(api_admin_overview(cfg, fresh()))
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
