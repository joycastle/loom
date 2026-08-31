# -*- coding: utf-8 -*-
"""飞书「主动采集」collector(阶段2:user OAuth)。

以**用户身份**(user_access_token)主动拉取「我」加入的群、我参与的会话消息 ——
不需要机器人在场。应用身份只能看到应用已加入的群;用户身份才能枚举账号可见的全部
会话(飞书隐私边界:别人之间、我不在场的私聊任何身份都读不到)。

凭证:自带飞书应用(BYO),读 env `FEISHU_APP_ID` / `FEISHU_APP_SECRET`(值绝不入库,
只从 ~/.loom/.env 或环境变量来)。用户 token 存本地私密文件(600)。

默认 enabled=False。真正拉数据前需要:①应用开「网页应用」授权、配 redirect、申请
user scope 并发版;②`loom feishu login` 走一次授权拿 refresh_token。都没做好时,
collect() 返回空 + 诊断说明,不报错、不阻塞其它来源。
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse

from .. import util

# token / IM 端点在 open.feishu.cn;但**授权页**(第一步拿 code)当前飞书文档用的是
# accounts.feishu.cn 域名(path 相同)——两个域名刻意分开,别混。base_url 存不含
# /open-apis 的根,与旧 feishu(bitable)collector 的 base(已含 /open-apis)也刻意区分。
_DEFAULT_BASE = "https://open.feishu.cn"
_DEFAULT_AUTH_BASE = "https://accounts.feishu.cn"
_TOKEN_PATH = os.path.join(util.HOME, "feishu_user_token.json")

# 阶段2 需要的用户 scope(在开发者后台申请并发版后才生效)。
# 注意:列会话历史 GET /im/v1/messages 认的是 im:message:readonly(实测错误码
# 99991679 列出的可选项之一;后台没有 im:message.history:readonly 这条,历史读取
# 就含在 im:message:readonly 里),不是 ...:get_as_user(那是按 message_id 读单条
# 用的)。一个 im:message:readonly 同时覆盖我参与的群聊 + 私聊历史。
DEFAULT_SCOPES = [
    "im:chat:readonly",       # 枚举我加入的全部群
    "im:message:readonly",    # 读我参与的会话历史(群 + 私聊)
    "offline_access",         # 拿 refresh_token,免每 2 小时重登
]

TEXT_CAP = 1200
BODY_CAP = 8000

# 相关性打分:达标或"我自己发的"才把原文留进台账,其余群内他人闲聊只计数不留原文
# ——既做高信噪比,也顺带减少他人发言的沉淀(隐私)。信号权重见 _score()。
KEEP_SCORE = 8
_NOISE_PREFIX = ("欢迎", "入职", "收到", "好的", "谢谢", "辛苦", "哈哈", "赞")


# ------------------------------------------------------------------ 凭证 / 配置
def _cfg(cfg):
    return cfg.get("sources", {}).get("feishu_user", {})


def _base(cfg):
    return (_cfg(cfg).get("base_url") or _DEFAULT_BASE).rstrip("/")


def _auth_base(cfg):
    return (_cfg(cfg).get("authorize_base") or _DEFAULT_AUTH_BASE).rstrip("/")


def _app_creds():
    """自带飞书应用(BYO):从 env 读。只读不入库;缺失返回 (None, None)。"""
    return os.environ.get("FEISHU_APP_ID"), os.environ.get("FEISHU_APP_SECRET")


# ------------------------------------------------------------------ token 存取
def _load_token():
    if not os.path.exists(_TOKEN_PATH):
        return {}
    try:
        with open(_TOKEN_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_token(tok):
    """user token 等同长期以我身份读飞书 → 按凭证对待:600 权限,和 .env 同级,
    绝不落进 vault(vault 会被 git add -A)。"""
    os.makedirs(util.HOME, exist_ok=True)
    with open(_TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(tok, f, ensure_ascii=False, indent=2)
    os.chmod(_TOKEN_PATH, 0o600)


def clear_token():
    if os.path.exists(_TOKEN_PATH):
        os.remove(_TOKEN_PATH)


def token_status():
    """给 `loom feishu status` 用:是否已登录 + 过期信息(不打印 token 本身)。"""
    tok = _load_token()
    if not tok.get("refresh_token"):
        return {"logged_in": False}
    now = int(time.time())
    return {
        "logged_in": True,
        "access_expires_in": max(0, int(tok.get("access_expires_at", 0)) - now),
        "refresh_expires_in": max(0, int(tok.get("refresh_expires_at", 0)) - now),
        "scopes": tok.get("scope", ""),
    }


# ------------------------------------------------------------------ HTTP(可被测试打桩)
def _request(cfg, method, path, token=None, params=None, body=None):
    """所有飞书请求的唯一出口(测试打桩此函数)。飞书惯例:HTTP 200 + body.code。"""
    url = _base(cfg) + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    return util.http_json(method, url, headers=headers, body=body)


# ------------------------------------------------------------------ OAuth flow
def authorize_url(cfg, redirect_uri, state="loom", scopes=None):
    """拼授权页 URL,用户在浏览器登录同意后飞书会带 code 回调 redirect_uri。"""
    app_id, _ = _app_creds()
    scopes = scopes or _cfg(cfg).get("scopes") or DEFAULT_SCOPES
    q = urllib.parse.urlencode({
        "client_id": app_id or "",
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    })
    return _auth_base(cfg) + "/open-apis/authen/v1/authorize?" + q


def _oauth_token(cfg, payload):
    app_id, secret = _app_creds()
    body = dict(payload, client_id=app_id, client_secret=secret)
    resp = _request(cfg, "POST", "/open-apis/authen/v2/oauth/token", body=body)
    # v2 走 OAuth2 标准返回(顶层字段);个别网关会包一层 data,两种都兼容。
    data = resp.get("data") if isinstance(resp.get("data"), dict) else resp
    if not data.get("access_token"):
        raise RuntimeError(f"飞书 token 交换失败: code={resp.get('code')} "
                           f"msg={resp.get('error_description') or resp.get('msg')}")
    now = int(time.time())
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "scope": data.get("scope", ""),
        "access_expires_at": now + int(data.get("expires_in", 0)),
        "refresh_expires_at": now + int(data.get("refresh_token_expires_in", 0)),
    }


def exchange_code(cfg, code, redirect_uri):
    """授权码 → token,存盘。`loom feishu login` 拿到 code 后调用。"""
    tok = _oauth_token(cfg, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    })
    _save_token(tok)
    return tok


def _valid_access_token(cfg):
    """返回可用的 access_token;快过期就用 refresh_token 续期并存盘。无 token 返回 None。"""
    tok = _load_token()
    if not tok.get("refresh_token"):
        return None
    if tok.get("access_token") and int(tok.get("access_expires_at", 0)) - int(time.time()) > 120:
        return tok["access_token"]
    fresh = _oauth_token(cfg, {
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
    })
    # refresh_token 一次性:飞书会返新的,没返就沿用旧的。
    if not fresh.get("refresh_token"):
        fresh["refresh_token"] = tok["refresh_token"]
        fresh["refresh_expires_at"] = tok.get("refresh_expires_at", 0)
    _save_token(fresh)
    return fresh["access_token"]


# ------------------------------------------------------------------ 拉取
def _paged(cfg, token, path, params):
    """飞书分页:data.items[] + data.page_token/has_more。汇总所有页的 items。"""
    items, page_token = [], None
    for _ in range(50):   # 硬上限,防异常翻页死循环
        p = dict(params)
        if page_token:
            p["page_token"] = page_token
        resp = _request(cfg, "GET", path, token=token, params=p)
        data = resp.get("data") or {}
        items.extend(data.get("items") or [])
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break
    return items


def list_chats(cfg, token):
    """以用户身份枚举「我」加入的全部群(应用身份只能看到 bot 在的群)。"""
    return _paged(cfg, token, "/open-apis/im/v1/chats",
                  {"page_size": 50, "user_id_type": "open_id"})


def list_messages(cfg, token, chat_id, start_time=None):
    """拉某会话的消息;start_time(秒)做增量游标。"""
    params = {"container_id_type": "chat", "container_id": chat_id,
              "page_size": 50, "sort_type": "ByCreateTimeAsc"}
    if start_time:
        params["start_time"] = str(start_time)
    return _paged(cfg, token, "/open-apis/im/v1/messages", params)


def _my_open_id(cfg, token):
    """当前登录用户的 open_id(用于判定 @我/我发的);拿到后缓存进 token 文件。"""
    tok = _load_token()
    if tok.get("open_id"):
        return tok["open_id"]
    try:
        resp = _request(cfg, "GET", "/open-apis/authen/v1/user_info", token=token)
        oid = ((resp.get("data") or {}).get("open_id")) or ""
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError):
        oid = ""
    if oid:
        tok = _load_token()          # 取最新(可能刚被刷新过),只补 open_id 再存
        tok["open_id"] = oid
        _save_token(tok)
    return oid


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def chat_detail(cfg, token, chat_id, cache):
    """取群 chat_mode / user_count(list_chats 的轻量对象没有);按 chat_id 缓存。"""
    if chat_id in cache:
        return cache[chat_id]
    meta = {}
    try:
        resp = _request(cfg, "GET", "/open-apis/im/v1/chats/" + chat_id,
                        token=token, params={"user_id_type": "open_id"})
        d = resp.get("data") or {}
        meta = {"chat_mode": d.get("chat_mode"), "user_count": _to_int(d.get("user_count"))}
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError):
        meta = {}
    cache[chat_id] = meta
    return meta


def _msg_record(m):
    """把一条飞书消息抽成打分需要的结构(文本 + 发送者/@提及/回复链等信号)。"""
    body = m.get("body") or {}
    text = ""
    raw = body.get("content")
    if raw and m.get("msg_type") == "text":
        try:
            text = (json.loads(raw).get("text") or "").strip()
        except Exception:
            text = ""
    # 其它类型(post 富文本/图片/文件/卡片)暂不抽正文,避免把二进制/结构塞进台账。
    sender = m.get("sender") or {}
    mention_ids, mention_all = set(), False
    for mn in (m.get("mentions") or []):
        mid, name, key = mn.get("id") or "", mn.get("name") or "", mn.get("key") or ""
        if name in ("所有人", "all", "All", "everyone") or key == "@_all" or mid == "all":
            mention_all = True
        if mid:
            mention_ids.add(mid)
    return {
        "id": m.get("message_id") or m.get("id") or "",
        "ts_ms": m.get("create_time"),
        "text": text,
        "sender_id": sender.get("id") or "",
        "sender_type": sender.get("sender_type") or "",
        "mention_ids": mention_ids,
        "mention_all": mention_all,
        "parent_id": m.get("parent_id") or "",
        "root_id": m.get("root_id") or m.get("thread_id") or "",
    }


def _is_noise(text):
    """模板噪音:极短应答、纯表情接龙、欢迎/收到类客套。"""
    t = (text or "").strip()
    if len(t) <= 2:
        return True
    stripped = re.sub(r"\[[^\]]{1,8}\]", "", t)          # 去表情 [比心][鼓掌]
    stripped = re.sub(r"[\s，。！？、~…!?.]+", "", stripped)
    if len(stripped) <= 2:
        return True
    return any(t.startswith(p) for p in _NOISE_PREFIX) and len(t) < 12


def _score(rec, ctx):
    """算一条消息和「我」的相关性。我自己发的返回 None(始终保留,不打分)。"""
    me = ctx["me"]
    if me and rec["sender_id"] == me:
        return None, ["我发的"]
    s, sig = 0, []
    if me and me in rec["mention_ids"] and not rec["mention_all"]:
        s += 30; sig.append("@我")
    if rec["parent_id"] and rec["parent_id"] in ctx["my_msg_ids"]:
        s += 25; sig.append("回复我")
    if rec["root_id"] and rec["root_id"] in ctx["my_roots"]:
        s += 15; sig.append("我在此话题")
    mode, uc = ctx["chat_mode"], ctx["user_count"]
    if mode == "p2p":
        s += 10; sig.append("单聊")
    elif uc and uc <= 5:
        s += 8; sig.append("小群")
    elif uc and uc <= 15:
        s += 4
    if rec["mention_all"]:
        s -= 20; sig.append("@all公告")
    if rec["sender_type"] == "app":
        s -= 10; sig.append("机器人")
    if _is_noise(rec["text"]):
        s -= 15
    return s, sig


def _to_entries(cfg, chats, messages_by_chat, me, chat_meta):
    """按 群+本地日 汇成 entry,但只留「和我相关的消息 + 我自己的发言」原文。

    某群某天若没有任何达标消息、我也没发过言 → 不生成 entry(周报里就不会出现
    这个与我无关的群)。他人未达标发言只计入 dropped 计数,不落原文。
    """
    names = {c.get("chat_id"): (c.get("name") or c.get("chat_id")) for c in chats}
    entries = []
    for chat_id, msgs in messages_by_chat.items():
        recs = [r for r in (_msg_record(m) for m in msgs) if r["ts_ms"]]
        # 先算"我在这个群发过的消息 id / 话题根",供回复/话题信号判定用
        my_msg_ids = {r["id"] for r in recs if me and r["sender_id"] == me}
        my_roots = {r["root_id"] for r in recs
                    if me and r["sender_id"] == me and r["root_id"]}
        meta = chat_meta.get(chat_id, {})
        ctx = {"me": me, "my_msg_ids": my_msg_ids, "my_roots": my_roots,
               "chat_mode": meta.get("chat_mode"), "user_count": meta.get("user_count")}
        byday = {}
        for r in recs:
            lts = util.iso_utc_to_local(_ms_to_iso(r["ts_ms"]))
            if lts:
                byday.setdefault(lts[:10], []).append((lts, r))
        for day, items in byday.items():
            items.sort(key=lambda x: x[0])
            kept, dropped, best = [], 0, 0
            for lts, r in items:
                score, sig = _score(r, ctx)
                if score is None:                         # 我发的
                    if r["text"]:
                        kept.append((lts, r["text"]))
                    best = max(best, KEEP_SCORE)
                elif score >= KEEP_SCORE:
                    if r["text"]:
                        kept.append((lts, r["text"]))
                    best = max(best, score)
                elif r["text"]:
                    dropped += 1
            if not kept:
                continue                                  # 这天这个群与我无关
            name = names.get(chat_id, chat_id)
            texts = [t for _, t in kept]
            joined = " / ".join(texts)
            entries.append({
                "id": f"feishu_user:{chat_id}:{day}", "date": day, "ts": kept[0][0],
                "project": name, "tool": "feishu_user", "kind": "chat",
                "summary": " ".join(texts[0].split())[:TEXT_CAP] or "(飞书会话)",
                "ref": f"feishu:chat:{chat_id}",
                "detail": {"start": kept[0][0], "end": kept[-1][0], "chat": name,
                           "msgs": len(items), "kept": len(kept), "dropped": dropped,
                           "score": best, "body": joined[:BODY_CAP]},
            })
    return entries


def _ms_to_iso(ms):
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)\
            .strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


# ------------------------------------------------------------------ collector 接口
def collect_diagnostic(cfg, since):
    src = _cfg(cfg)
    if not src.get("enabled"):
        return {"entries": [], "errors": []}
    app_id, secret = _app_creds()
    if not (app_id and secret):
        return {"entries": [], "errors": ["缺 FEISHU_APP_ID/FEISHU_APP_SECRET(在 ~/.loom/.env 配置你的飞书应用凭证)"]}
    try:
        token = _valid_access_token(cfg)
    except Exception as e:
        return {"entries": [], "errors": [f"刷新用户 token 失败:{e}"]}
    if not token:
        return {"entries": [], "errors": ["未登录,请先运行 loom feishu login"]}

    # since(YYYY-MM-DD)→ 秒级游标,做增量。
    start_time = None
    try:
        from datetime import datetime
        start_time = int(datetime.strptime(since, "%Y-%m-%d").timestamp())
    except Exception:
        pass

    errors = []
    try:
        chats = list_chats(cfg, token)
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as e:
        return {"entries": [], "errors": [f"拉群列表失败:{e}"]}

    me = _my_open_id(cfg, token)            # 用于判定 @我 / 我发的 / 我在的话题
    if not me:
        errors.append("拿不到本人 open_id,相关性过滤降级(仅按群大小)")

    messages_by_chat, chat_meta = {}, {}
    for c in chats:
        cid = c.get("chat_id")
        if not cid:
            continue
        try:
            messages_by_chat[cid] = list_messages(cfg, token, cid, start_time)
            chat_detail(cfg, token, cid, chat_meta)   # 补群大小/类型,供打分用
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as e:
            errors.append(f"群 {c.get('name') or cid} 消息拉取失败:{e}")
    entries = _to_entries(cfg, chats, messages_by_chat, me, chat_meta)
    return {"entries": [e for e in entries if e["date"] >= since], "errors": errors}


def collect(cfg, since):
    return collect_diagnostic(cfg, since)["entries"]
