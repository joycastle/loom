# -*- coding: utf-8 -*-
"""通用工具:路径、.env、HTTP(urllib 零依赖)、只读 sqlite(copy-to-temp 防锁)。"""
import json
import os
import re
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
INDEX_PATH = os.path.join(HOME, "data", "index.sqlite")  # 派生的 FTS5 检索索引,可删可再生


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


# ---- 密钥打码:采集入库前抹掉 token/密钥【值】,保证推 GitHub / Basic Memory 不泄露 ----
# 只打码「值」,不动变量名/代码引用(如 Variable.get("secret_xxx") 里的 secret_xxx 保留)。
# 原文永远在 transcript / git 里,回链可查;这里只保证 loom 的派生文件干净。
_MASK = "«已打码»"


def _mask_kv(m):  # 键像密钥时,只替换其值,保留键名做上下文
    return f"{m.group(1)}{m.group(2)}{m.group(3)}{_MASK}{m.group(3)}"


_REDACTORS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.S), "«已打码-私钥»"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}\b"), "«已打码-jwt»"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), _MASK),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), _MASK),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), _MASK),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), _MASK),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), _MASK),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"), "bearer " + _MASK),
    (re.compile(r"(://[^:/\s@]+:)([^@/\s]{3,})@"), r"\1" + _MASK + "@"),  # url 里的密码
    # 键名像密钥、且后面跟 =值 / :值 —— 只抹值。
    # 键允许前后缀(FEISHU_APP_SECRET、db_password);但纯变量名引用(无 =值)不命中。
    (re.compile(r"(?i)((?:[A-Za-z0-9]+[_-])?"
                r"(?:pass(?:word|wd)?|secret|token|api[_-]?key|access[_-]?key|"
                r"access[_-]?token|client[_-]?secret|private[_-]?key|auth[_-]?token)"
                r"(?:[_-][A-Za-z0-9]+)?)(\s*[:=]\s*)(['\"]?)([^\s'\"`,;)]{4,})\3",
                re.I), _mask_kv),
]


def redact(text):
    if not text:
        return text
    for pat, repl in _REDACTORS:
        text = pat.sub(repl, text)
    return text


def redact_entry(e):
    """就地打码条目里的自由文本(summary + detail 里的字符串值);ref/回链保持原样。"""
    if e.get("summary"):
        e["summary"] = redact(e["summary"])
    d = e.get("detail")
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, str):
                d[k] = redact(v)
    return e
