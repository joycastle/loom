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
        "claude":    {"enabled": True, "projects_dir": "~/.claude/projects"},
        "codex":     {"enabled": True, "home": "~/.codex"},
        "cursor":    {"enabled": True, "app_support": "~/Library/Application Support/Cursor"},
        "codebuddy": {"enabled": True, "app_support": "~/Library/Application Support/CodeBuddy"},
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
    _deep_update(merged, cfg)
    return merged


def save(cfg):
    os.makedirs(util.HOME, exist_ok=True)
    with open(util.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _deep_update(base, overlay):
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def vault_dir(cfg):
    return util.expand(cfg["vault"]["dir"])


def journal_dir(cfg):
    return os.path.join(vault_dir(cfg), "journal")


def notes_dir(cfg):
    return os.path.join(vault_dir(cfg), "notes")


# ---- 增删助手 ----
def add_repo(cfg, path):
    path = os.path.abspath(util.expand(path))
    r = subprocess.run(["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True)
    if r.returncode != 0 or r.stdout.strip() != "true":
        raise ValueError(f"{path} 不是 git 仓")
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
    for dirpath, dirnames, _ in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth > 3:
            dirnames[:] = []
            continue
        if ".git" in dirnames:
            found.append(dirpath)
            dirnames[:] = [d for d in dirnames if d != ".git"]
    return sorted(found)


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
