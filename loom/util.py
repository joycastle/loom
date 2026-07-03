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


def safe_join(base, *parts):
    """把 parts 拼到 base 下;若结果逃出 base(绝对路径 / `..` 穿越 / 符号链接)返回 None。
    用 realpath 解析符号链接,防止 vault 内被植入 symlink 把文件写到/删到 vault 之外。"""
    base = os.path.realpath(base)
    dest = os.path.realpath(os.path.join(base, *parts))
    return dest if dest == base or dest.startswith(base + os.sep) else None


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


def iso_utc_to_local(iso):
    """把带时区的 ISO(如 claude 的 ...Z / 带偏移)转成【本地】朴素 ISO,统一各源日期口径。

    各采集器日期必须同一时区,否则午夜前后同一晚的活动会落到不同日记
    (codex/cursor 走 ms_to_iso 已是本地;claude 原始是 UTC 的 Z)。
    无时区信息 / 解析失败 → 原样返回(视为已是本地)。"""
    if not iso:
        return iso
    s = iso.strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return s
    if dt.tzinfo is None:
        return s
    return dt.astimezone().replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")


# ---- 密钥打码:采集入库前抹掉 token/密钥【值】,保证推 GitHub / Basic Memory 不泄露 ----
# 只打码「值」,不动变量名/代码引用(如 Variable.get("secret_xxx") 里的 secret_xxx 保留)。
# 原文永远在 transcript / git 里,回链可查;这里只保证 loom 的派生文件干净。
_MASK = "«已打码»"


def _looks_secret(v, quoted=False):
    """值是否像机密。带引号(JSON/YAML 的数据值)→ 一律抹(≥8);裸值 → 保守,排除
    纯字母/连字符散文,要求带数字 / base64 尾 `=` / 很长,避免误伤 `token: TODO/later`。"""
    v = v.strip().strip("'\"")
    if len(v) < 8:
        return False
    if quoted:
        return True
    if "(" in v:                                   # 裸值含括号=代码调用(如 x = get_secret(...)),非机密字面量
        return False
    if re.fullmatch(r"[A-Za-z][A-Za-z\-]*", v):   # 纯字母/连字符词 → 散文,不打码
        return False
    return bool(re.search(r"\d", v) or v.endswith("=") or len(v) >= 32)


def _mask_kv(m):  # 键像密钥、值也像机密时,只替换值,保留键名做上下文(带引号更激进)
    return m.group(0) if not _looks_secret(m.group(3), bool(m.group(2))) \
        else m.group(1) + m.group(2) + _MASK + m.group(4)


_REDACTORS = [
    # 私钥块(含 OpenSSH/RSA/EC/PGP;PGP 结尾是 KEY BLOCK)
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?"
                r"-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----"), "«已打码-私钥»"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}\b"), "«已打码-jwt»"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), _MASK),                      # AWS access key id
    (re.compile(r"\bgh[opsur]_[A-Za-z0-9]{20,}\b"), _MASK),           # GitHub ghp/gho/ghs/ghu/ghr
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), _MASK),
    (re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{10,}\b"), _MASK),  # Stripe
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), _MASK),               # Google API key
    (re.compile(r"\bya29\.[0-9A-Za-z_\-]{10,}"), _MASK),             # Google OAuth
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), _MASK),         # Slack token
    (re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+"), _MASK),  # Slack webhook
    (re.compile(r"https://open\.(?:feishu\.cn|larksuite\.com)/open-apis/bot/v2/hook/"
                r"[A-Za-z0-9-]+"), _MASK),                       # 飞书/Lark 机器人 webhook
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), _MASK),                  # OpenAI 风格
    (re.compile(r"(?i)\bAccountKey=[A-Za-z0-9+/=]{20,}"), _MASK),     # Azure
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"), "bearer " + _MASK),
    (re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=]{16,}"), "Basic " + _MASK),   # HTTP Basic 凭证
    (re.compile(r"(://[^:/\s@]+:)([^@/\s]{3,})@"), r"\1" + _MASK + "@"),  # url 里的密码
    # 键名像密钥、后跟 =值/:值(允许键/值带引号,覆盖 JSON/YAML)—— 值也像机密才抹。
    (re.compile(r"(?i)((?:[A-Za-z0-9]+[_-])?"
                r"(?:pass(?:word|wd)?|secret|token|api[_-]?key|access[_-]?key|"
                r"access[_-]?token|client[_-]?secret|private[_-]?key|auth[_-]?token|accountkey)"
                r"(?:[_-][A-Za-z0-9]+)?[\"']?\s*[:=]\s*)([\"']?)([^\s\"'`,;)]{4,})(\2)"),
     _mask_kv),
]


def redact(text):
    if not text:
        return text
    for pat, repl in _REDACTORS:
        text = pat.sub(repl, text)
    return text


def _redact_val(v):
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, list):
        return [_redact_val(x) for x in v]
    if isinstance(v, dict):
        return {k: _redact_val(x) for k, x in v.items()}
    return v


def redact_entry(e):
    """就地打码条目自由文本:summary + detail(递归 str/list/dict);ref/回链保持原样。"""
    if e.get("summary"):
        e["summary"] = redact(e["summary"])
    if isinstance(e.get("detail"), dict):
        e["detail"] = {k: _redact_val(v) for k, v in e["detail"].items()}
    return e
