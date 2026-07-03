# -*- coding: utf-8 -*-
"""飞书 IM 采集器(主动打点)。

mode=at_bot:遍历机器人所在群 → 拉时间窗内消息 → 只留「@了本机器人」的 →
作为「记事」条目入库(kind=note)。你在话题里 @ 机器人写一句,下次 loom sync
就把它记进当天日记。凭证从 env 读,gated(feishu.im.enabled)。

需要的飞书权限(scope):
  im:message:readonly (或 im:message.group_at_msg:readonly)  读群消息
  im:chat:readonly                                            列机器人所在群
  contact:user.base:readonly                                 可选,解析名字
  im:message:send_as_bot                                     可选,回执「已记录」
"""
import json
import time
import urllib.parse
from datetime import datetime

from .. import util
from .feishu import token


def _bot_open_id(base_url, tok):
    try:
        data = util.http_json("GET", f"{base_url}/bot/v3/info",
                              headers={"Authorization": f"Bearer {tok}"})
        return (data.get("bot") or {}).get("open_id")
    except Exception as e:
        util.log(f"  [feishu_im] 取机器人 open_id 失败: {e}")
        return None


def _list_chats(base_url, tok):
    chats, page_token = [], None
    while True:
        q = {"page_size": 100}
        if page_token:
            q["page_token"] = page_token
        url = f"{base_url}/im/v1/chats?{urllib.parse.urlencode(q)}"
        data = util.http_json("GET", url, headers={"Authorization": f"Bearer {tok}"})
        if data.get("code") != 0:
            util.log(f"  [feishu_im] 列群失败: {data.get('msg')}")
            break
        d = data.get("data", {})
        chats.extend(d.get("items", []))
        if d.get("has_more") and d.get("page_token"):
            page_token = d["page_token"]
        else:
            break
    return chats


def _list_messages(base_url, tok, chat_id, start_sec, end_sec):
    msgs, page_token = [], None
    while True:
        q = {"container_id_type": "chat", "container_id": chat_id,
             "start_time": str(start_sec), "end_time": str(end_sec), "page_size": 50}
        if page_token:
            q["page_token"] = page_token
        url = f"{base_url}/im/v1/messages?{urllib.parse.urlencode(q)}"
        data = util.http_json("GET", url, headers={"Authorization": f"Bearer {tok}"})
        if data.get("code") != 0:
            util.log(f"  [feishu_im] 拉消息失败(chat={chat_id}): {data.get('msg')}")
            break
        d = data.get("data", {})
        msgs.extend(d.get("items", []))
        if d.get("has_more") and d.get("page_token"):
            page_token = d["page_token"]
        else:
            break
    return msgs


def _mention_ids(msg):
    out = []
    for m in msg.get("mentions") or []:
        mid = m.get("id")
        if isinstance(mid, dict):
            out.append(mid.get("open_id") or "")
        elif isinstance(mid, str):
            out.append(mid)
    return [x for x in out if x]


def _msg_text(msg):
    body = msg.get("body") or {}
    content = body.get("content")
    if not content:
        return ""
    try:
        c = json.loads(content)
    except Exception:
        return str(content)[:180]
    if isinstance(c, dict):
        if "text" in c:
            return c["text"]
        # post/富文本:拼接所有 text 段
        parts = []

        def walk(x):
            if isinstance(x, dict):
                if x.get("tag") == "text" and x.get("text"):
                    parts.append(x["text"])
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(c)
        if parts:
            return " ".join(parts)
    return ""


def _sender_open_id(msg):
    s = msg.get("sender") or {}
    sid = s.get("id")
    if isinstance(sid, dict):
        return sid.get("open_id", "")
    return sid or ""


def collect(cfg, since):
    fs = cfg.get("feishu", {})
    im = fs.get("im", {}) or {}
    if not im.get("enabled"):
        return []
    util.load_env()
    base_url = fs.get("base_url", "https://open.feishu.cn/open-apis")
    tok = token(base_url)
    if not tok:
        return []
    bot_oid = _bot_open_id(base_url, tok)
    if not bot_oid:
        util.log("  [feishu_im] 拿不到机器人 open_id,跳过")
        return []

    start_sec = int(datetime.strptime(since, "%Y-%m-%d").timestamp())
    end_sec = int(time.time())
    allow = set(im.get("chat_allowlist") or [])

    entries = []
    for chat in _list_chats(base_url, tok):
        cid = chat.get("chat_id")
        cname = chat.get("name") or "群聊"
        if allow and cid not in allow and cname not in allow:
            continue
        for msg in _list_messages(base_url, tok, cid, start_sec, end_sec):
            if bot_oid not in _mention_ids(msg):
                continue
            mid = msg.get("message_id", "")
            ct = util.ms_to_iso(msg.get("create_time"))
            if not ct:
                continue
            text = " ".join(_msg_text(msg).split())[:180] or "(记事)"
            entries.append({
                "id": f"feishu_im:{mid}",
                "date": ct[:10], "ts": ct,
                "project": cname, "tool": "feishu", "kind": "note",
                "summary": text,
                "ref": f"chat:{cid} msg:{mid}",
                "detail": {"chat": cname, "chat_id": cid,
                           "thread_id": msg.get("thread_id") or msg.get("root_id"),
                           "from_open_id": _sender_open_id(msg)},
            })
    return entries
