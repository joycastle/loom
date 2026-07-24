# -*- coding: utf-8 -*-
"""配置读写 + 增删助手 + 飞书 URL 解析。config.json 靠子命令管理,免手编。"""
import copy
import json
import os
import re
import subprocess

from . import util

# 记录每个 config.json 上一次 load/save 时的 (mtime, 快照),用于保存前检测"自我们
# 加载以来是否有别的进程(并发的 CLI)改过磁盘"。GUI 常驻内存、CLI 随手写,二者
# 共用同一 ~/.loom;没有这道守卫,GUI 的下次 save 会用启动快照整体覆盖 CLI 的改动
# (last-writer-wins)。按路径分键,避免多 LOOM_HOME(测试)相互串。
_BASELINE = {}

DEFAULT_CONFIG = {
    "owner": {"name": "", "feishu_name": ""},
    "identities": {"emails": [], "names": []},
    "default_since_days": 100,
    "redact": True,          # 采集入库前抹掉 token/密钥值(推云端/Basic Memory 防泄露);私有可信仓可设 false
    "repos": [],
    "sources": {
        "git":       {"enabled": True},
        "claude":    {"enabled": True, "projects_dir": "~/.claude/projects"},
        "codex":     {"enabled": True, "home": "~/.codex"},
        "cursor":    {"enabled": True, "app_support": "~/Library/Application Support/Cursor"},
        "codebuddy": {
            "enabled": False,
            "app_support": "~/Library/Application Support/CodeBuddy",
            "extension_data": "~/Library/Application Support/CodeBuddyExtension/Data",
        },
        "pi":        {"enabled": False, "sessions_dir": "~/.pi/agent/sessions"},
        "opencode":  {"enabled": False, "data_dir": "~/.local/share/opencode"},
        # 通过已登录的 lark-cli 读取 Bridge 绑定群；默认关闭，避免升级后扩大采集。
        "codex_feishu_bridge": {
            "enabled": False,
            "home": "~/.feishu-codex-bridge",
            "user_open_id": "",
        },
        "docs":      {"enabled": True},   # 索引各仓 .md(全文归档,不进日记)
        "notes":     {"enabled": True},   # 索引 vault/notes/ 手动加的文档(loom doc add 闭环)
    },
    "feishu": {
        "enabled": False,
        "base_url": "https://open.feishu.cn/open-apis",
        "bitables": [],
    },
    # 从 util.HOME(尊重 LOOM_HOME)派生,而非硬编码 ~/.loom/vault——否则临时
    # LOOM_HOME 下 ~ 仍解析到真实家目录,测试会误写真实 vault(曾导致真配置被污染)。
    "vault": {"dir": os.path.join(util.HOME, "vault"), "remote": ""},
}


def _mtime_ns(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def _remember(cfg):
    """记下本次 load/save 的 (mtime, 快照),作为下次 save 的三方合并基线。"""
    _BASELINE[util.CONFIG_PATH] = {
        "mtime": _mtime_ns(util.CONFIG_PATH),
        "snapshot": copy.deepcopy(cfg),
    }


def _merge_external(ours, base, theirs):
    """把磁盘上 `theirs` 相对 `base` 的外部改动就地并入内存 `ours`。
    规则:本次(ours 相对 base)改过的键 → 保留 ours(本次操作优先);ours 没碰过的键
    → 采纳 theirs 的外部改动(含新增/删除)。dict 递归,list/标量整体处理。"""
    if not (isinstance(ours, dict) and isinstance(base, dict) and isinstance(theirs, dict)):
        return
    for k, tv in theirs.items():
        bv = base.get(k)
        ov = ours.get(k)
        if isinstance(tv, dict) and isinstance(ov, dict) and isinstance(bv, dict):
            _merge_external(ov, bv, tv)
        elif k not in ours or ov == bv:
            ours[k] = copy.deepcopy(tv)   # ours 没动 → 采纳外部值
        # else: ours 改过(ov != bv)→ 冲突,保留 ours
    for k in list(ours.keys()):           # theirs 删掉、且 ours 没改的键 → 一并删
        if k in base and k not in theirs and ours.get(k) == base.get(k):
            del ours[k]


def load():
    if not os.path.exists(util.CONFIG_PATH):
        fresh = json.loads(json.dumps(DEFAULT_CONFIG))
        _remember(fresh)
        return fresh
    with open(util.CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    # 补齐缺省键,便于旧配置平滑升级
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    # 旧版本允许单独关闭 docs。迁移到“项目文档并入 Git”之前先继承这项
    # 明确选择，不能因为补入默认 git=true 就悄悄恢复全文采集。
    old_sources = cfg.get("sources", {})
    old_docs = old_sources.get("docs", {}) if isinstance(old_sources, dict) else {}
    _deep_update(merged, cfg)
    # 早期开发版使用了含糊的 feishu_bridge 名称；迁到项目全称，避免以后
    # 接入其它 Bridge 时配置和记录来源撞名。
    if isinstance(old_sources, dict) and "feishu_bridge" in old_sources:
        if "codex_feishu_bridge" not in old_sources:
            merged["sources"]["codex_feishu_bridge"] = old_sources["feishu_bridge"]
        merged["sources"].pop("feishu_bridge", None)
    if isinstance(old_docs, dict) and "enabled" in old_docs:
        if old_docs["enabled"] is False:
            # 隐私上采取保守迁移：旧 docs=false 优先，宁可暂停组合来源，
            # 也不能在升级后扩大采集范围。用户重新开启 Git 时会同时对齐两项。
            merged["sources"]["git"]["enabled"] = False
        elif isinstance(old_sources, dict) and "git" not in old_sources:
            merged["sources"]["git"]["enabled"] = True
    _remember(merged)
    return merged


def save(cfg):
    os.makedirs(util.HOME, exist_ok=True)
    # 并发守卫:若磁盘自我们加载以来被别的进程(CLI)改过,先把它的外部改动并进来,
    # 再落盘——避免用陈旧的内存快照整体覆盖(last-writer-wins),保持 App↔CLI 一致。
    prev = _BASELINE.get(util.CONFIG_PATH)
    if prev and prev["mtime"] is not None:
        cur = _mtime_ns(util.CONFIG_PATH)
        if cur is not None and cur != prev["mtime"]:
            try:
                with open(util.CONFIG_PATH, encoding="utf-8") as f:
                    theirs = json.load(f)
            except Exception:
                theirs = None
            if isinstance(theirs, dict):
                _merge_external(cfg, prev["snapshot"], theirs)
    tmp = f"{util.CONFIG_PATH}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, util.CONFIG_PATH)
    _remember(cfg)


def _deep_update(base, overlay):
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def source_enabled(cfg, name):
    """Return the product-level switch state for a collector.

    Repository documents are presented as part of Git in the console, so Git is
    their single source of truth even when an older config still contains a
    separate ``sources.docs.enabled`` value.
    """
    if name in ("git", "docs"):
        sources = cfg.get("sources", {})
        docs = sources.get("docs", {})
        if isinstance(docs, dict) and docs.get("enabled") is False:
            return False
        if "git" in sources:
            return bool(sources.get("git", {}).get("enabled", True))
        # 未经 config.load() 合并的旧配置也要尊重显式 docs 选择。
        if isinstance(docs, dict) and "enabled" in docs:
            return bool(docs["enabled"])
        return True
    if name == "feishu":
        return bool(cfg.get("feishu", {}).get("enabled"))
    return bool(cfg.get("sources", {}).get(name, {}).get("enabled"))


def vault_dir(cfg):
    return util.expand(cfg["vault"]["dir"])


def journal_dir(cfg):
    return os.path.join(vault_dir(cfg), "journal")


def notes_dir(cfg):
    custom = cfg.get("sources", {}).get("notes", {}).get("dir", "")
    return util.expand(custom) if custom else os.path.join(vault_dir(cfg), "notes")


# ---- 增删助手 ----
def git_worktree_info(path):
    """Return canonical Git worktree metadata; reject bare and non-repositories."""
    path = os.path.abspath(util.expand(path))
    if not os.path.isdir(path):
        return None
    try:
        inside = subprocess.run(
            ["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        common = subprocess.run(
            ["git", "-C", path, "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=10)
        root = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if common.returncode != 0 or root.returncode != 0:
        return None
    common_dir = common.stdout.strip()
    if not os.path.isabs(common_dir):
        common_dir = os.path.join(path, common_dir)
    return {"path": path, "root": os.path.realpath(root.stdout.strip()),
            "common_dir": os.path.realpath(common_dir)}


def add_repo(cfg, path):
    requested = os.path.abspath(util.expand(path))
    path = requested
    info = git_worktree_info(path)
    if not info:
        raise ValueError(f"{path} 不是 git 仓")
    # Always persist the canonical worktree root.  Callers such as the local
    # Agent may discover a nested directory inside a repository; saving that
    # arbitrary child path makes later diagnostics and deduplication unstable.
    # Preserve the user's lexical spelling when they selected the worktree root
    # itself (macOS commonly aliases /var to /private/var).  Nested selections
    # are still normalized to the repository root.
    try:
        selected_root = os.path.samefile(requested, info["root"])
    except OSError:
        selected_root = False
    path = requested if selected_root else info["root"]
    info = git_worktree_info(path)
    if not info:  # Repository state changed between the two fixed probes.
        raise ValueError(f"{path} 不是 git 仓")
    for existing in cfg["repos"]:
        other = git_worktree_info(existing)
        if other and other["common_dir"] == info["common_dir"] and other["path"] != path:
            raise ValueError(f"{path} 与已配置的 {other['path']} 属于同一 Git 仓库")
    if path not in cfg["repos"]:
        cfg["repos"].append(path)
    return path


def rm_repo(cfg, path):
    path = os.path.abspath(util.expand(path))
    cfg["repos"] = [r for r in cfg["repos"] if r != path]


def scan_repos(root):
    """在 root 下(深度<=3)找所有 .git 仓,返回仓根路径列表。"""
    root = util.expand(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth > 3:
            dirnames[:] = []
            continue
        if ".git" in dirnames or ".git" in filenames:
            if git_worktree_info(dirpath):
                found.append(dirpath)
        if ".git" in dirnames:
            dirnames[:] = [d for d in dirnames if d != ".git"]
    return sorted(set(found))


FEISHU_TOKEN_RE = re.compile(r"(?:/base/|/wiki/|obj_token=)([A-Za-z0-9]{20,})")
FEISHU_TABLE_RE = re.compile(r"[?&]table=([A-Za-z0-9]+)")


def parse_bitable_url(url):
    """从多维表格 URL 解析 (app_token, table_id)。table 缺失时返回 None,需另填。"""
    m = FEISHU_TOKEN_RE.search(url)
    app_token = m.group(1) if m else None
    t = FEISHU_TABLE_RE.search(url)
    table_id = t.group(1) if t else None
    return app_token, table_id


def add_bitable(cfg, name, app_token, table_id, **fields):
    b = {
        "name": name,
        "app_token": app_token,
        "table_id": table_id,
        "person_field": fields.get("person_field", "需求负责人"),
        "date_field": fields.get("date_field", "预计完成时间"),
        "title_field": fields.get("title_field", "需求描述"),
        "status_field": fields.get("status_field", "需求状态"),
    }
    cfg["feishu"]["enabled"] = True
    cfg["feishu"]["bitables"] = [x for x in cfg["feishu"]["bitables"] if x["name"] != name]
    cfg["feishu"]["bitables"].append(b)
    return b
