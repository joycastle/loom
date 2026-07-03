# -*- coding: utf-8 -*-
"""通用工具:路径、.env、HTTP(urllib 零依赖)、只读 sqlite(copy-to-temp 防锁)。"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta

HOME = os.path.expanduser(os.environ.get("LOOM_HOME", "~/.loom"))
CONFIG_PATH = os.path.join(HOME, "config.json")
ENV_PATH = os.path.join(HOME, ".env")
DATA_PATH = os.path.join(HOME, "data", "entries.jsonl")


def expand(p):
    return os.path.expanduser(os.path.expandvars(p)) if p else p


def log(msg):
    sys.stderr.write(msg + "\n")


def since_date(days):
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


# ---- .env(KEY=VALUE 每行;供飞书凭证等,绝不进 vault)----
def load_env():
    if not os.path.exists(ENV_PATH):
        return
    for line in open(ENV_PATH, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ---- HTTP JSON(urllib)----
def http_json(method, url, headers=None, body=None, timeout=30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---- 只读 sqlite:先把库(含 -wal/-shm)copy 到临时目录,避免锁 ----
def read_sqlite(path, query, params=()):
    path = expand(path)
    if not os.path.exists(path):
        return []
    tmp = tempfile.mkdtemp(prefix="loom_sq_")
    try:
        base = os.path.join(tmp, "db.sqlite")
        shutil.copy2(path, base)
        for ext in ("-wal", "-shm"):
            if os.path.exists(path + ext):
                shutil.copy2(path + ext, base + ext)
        conn = sqlite3.connect(base)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(query, params).fetchall()]
        finally:
            conn.close()
    except Exception as e:
        log(f"  [sqlite] {os.path.basename(path)} 读取失败: {e}")
        return []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ms_to_iso(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None
