# -*- coding: utf-8 -*-
"""配置读写 + 增删助手 + 飞书 URL 解析。config.json 靠子命令管理,免手编。"""
import json
import os
import re
import subprocess

from . import util

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
        # 新增本地会话源默认关闭，避免升级后未经选择就扩大采集范围。
        "pi":        {"enabled": False, "sessions_dir": "~/.pi/agent/sessions"},
        "opencode":  {"enabled": False, "data_dir": "~/.local/share/opencode"},
        "docs":      {"enabled": True},   # 索引各仓 .md(全文归档,不进日记)
        "notes":     {"enabled": True},   # 索引 vault/notes/ 手动加的文档(loom doc add 闭环)
    },
    "feishu": {
        "enabled": False,
        "base_url": "https://open.feishu.cn/open-apis",
        "bitables": [],
    },
    "vault": {"dir": "~/.loom/vault", "remote": ""},
}


def load():
    if not os.path.exists(util.CONFIG_PATH):
        return json.loads(json.dumps(DEFAULT_CONFIG))
    with open(util.CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    # 补齐缺省键,便于旧配置平滑升级
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    # 旧版本允许单独关闭 docs。迁移到“项目文档并入 Git”之前先继承这项
    # 明确选择，不能因为补入默认 git=true 就悄悄恢复全文采集。
    old_sources = cfg.get("sources", {})
    old_docs = old_sources.get("docs", {}) if isinstance(old_sources, dict) else {}
    _deep_update(merged, cfg)
    if isinstance(old_docs, dict) and "enabled" in old_docs:
        if old_docs["enabled"] is False:
            # 隐私上采取保守迁移：旧 docs=false 优先，宁可暂停组合来源，
            # 也不能在升级后扩大采集范围。用户重新开启 Git 时会同时对齐两项。
            merged["sources"]["git"]["enabled"] = False
        elif isinstance(old_sources, dict) and "git" not in old_sources:
            merged["sources"]["git"]["enabled"] = True
    return merged


def save(cfg):
    os.makedirs(util.HOME, exist_ok=True)
    tmp = f"{util.CONFIG_PATH}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, util.CONFIG_PATH)


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
    path = os.path.abspath(util.expand(path))
    info = git_worktree_info(path)
    if not info:
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
