# -*- coding: utf-8 -*-
"""CodeBuddy IDE 采集器。

CodeBuddy IDE 把会话元数据放在 ``codebuddy-sessions.vscdb``，完整的本地
历史则由 CodeBuddyExtension 按 workspace / conversation / message 分层保存。
本采集器只记录主 ``craft`` 会话，跳过 ``team-member`` 子会话，并从
CodeBuddy 包装的消息里只提取 ``<user_query>``，不把项目上下文或工具
返回带进 loom。
"""
from collections import defaultdict
import glob
import json
import os
import re

from .. import util


INTENT_CAP = 180
OPENING_CAP = 1200
BODY_CAP = 8000
_CID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_USER_QUERY_RE = re.compile(r"<user_query\b[^>]*>(.*?)</user_query>", re.I | re.S)


def source_paths(cfg):
    """返回 CodeBuddy IDE 的两个本地数据根。

    extension_data 可显式配置；旧配置只有 app_support 时，从其同级
    目录推导 CodeBuddyExtension/Data。
    """
    src = cfg.get("sources", {}).get("codebuddy", {})
    app_support = util.expand(
        src.get("app_support", "~/Library/Application Support/CodeBuddy"))
    extension_data = src.get("extension_data", "")
    if extension_data:
        extension_data = util.expand(extension_data)
    else:
        extension_data = os.path.join(
            os.path.dirname(app_support), "CodeBuddyExtension", "Data")
    return {
        "app_support": app_support,
        "session_db": os.path.join(app_support, "codebuddy-sessions.vscdb"),
        "extension_data": extension_data,
    }


def _error(errors, message):
    # 单机历史可能因版本升级留下很多腐化文件；结果只保留有限
    # 的可操作错误，避免一次 sync 产生巨大响应。
    if len(errors) < 40:
        errors.append(message)


def _read_json(path, errors, label):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        _error(errors, f"{label}读取失败:{os.path.basename(path)}:{exc}")
        return None


def _session_metadata(db, errors):
    """读取 conversationId -> cwd/title 元数据；DB 不存在不算失败。"""
    if not os.path.exists(db):
        return {}
    rows = util.read_sqlite(
        db, "SELECT key, value FROM ItemTable WHERE key LIKE 'session:%'")
    result = {}
    for row in rows:
        raw = row.get("value")
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        try:
            item = json.loads(raw)
        except Exception as exc:
            _error(errors, f"会话元数据损坏:{row.get('key', '')}:{exc}")
            continue
        if not isinstance(item, dict):
            _error(errors, f"会话元数据格式错误:{row.get('key', '')}")
            continue
        cid = str(item.get("conversationId") or "")
        if not cid and str(row.get("key", "")).startswith("session:"):
            cid = str(row["key"]).split(":", 1)[1]
        if cid:
            result[cid] = item
    return result


def _history_index_paths(extension_data):
    if not os.path.isdir(extension_data):
        return []
    paths = glob.glob(
        os.path.join(extension_data, "**", "history", "*", "index.json"),
        recursive=True)
    # 也支持用户直接把 extension_data 指向 history 目录。
    if os.path.basename(extension_data.rstrip(os.sep)) == "history":
        paths.extend(glob.glob(os.path.join(extension_data, "*", "index.json")))
    return sorted(set(paths))


def _discover_conversations(extension_data, errors):
    """找到所有 craft 会话，按 id 去重并保留更新的那份索引。"""
    found = {}
    for index_path in _history_index_paths(extension_data):
        data = _read_json(index_path, errors, "CodeBuddy workspace 索引")
        if data is None:
            continue
        conversations = data.get("conversations") if isinstance(data, dict) else None
        if not isinstance(conversations, list):
            _error(errors, f"CodeBuddy workspace 索引格式错误:{index_path}")
            continue
        for conversation in conversations:
            if not isinstance(conversation, dict) or conversation.get("type") != "craft":
                continue
            cid = str(conversation.get("id") or "")
            if not _CID_RE.match(cid):
                _error(errors, f"CodeBuddy 会话 id 无效:{cid[:40]}")
                continue
            candidate = {
                "meta": conversation,
                "index": os.path.join(os.path.dirname(index_path), cid, "index.json"),
            }
            old = found.get(cid)
            if old is None or str(conversation.get("lastMessageAt") or "") > \
                    str(old["meta"].get("lastMessageAt") or ""):
                found[cid] = candidate
    return found


def probe(cfg):
    """轻量诊断：管理页只需路径和会话数，不读消息正文。"""
    paths = source_paths(cfg)
    errors = []
    conversations = _discover_conversations(paths["extension_data"], errors)
    sessions = _session_metadata(paths["session_db"], errors)
    return dict(paths,
                history_exists=os.path.isdir(paths["extension_data"]),
                session_db_exists=os.path.isfile(paths["session_db"]),
                conversations=len(conversations),
                session_metadata=len(sessions),
                errors=errors)


def _content_text(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
            texts.append(str(part["text"]))
    return "\n".join(texts)


def _user_text(message):
    """从 CodeBuddy 的双层 JSON 中只提取真实用户问题。"""
    raw = message.get("message")
    if isinstance(raw, dict):
        text = _content_text(raw.get("content"))
    elif isinstance(raw, str):
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            # 早期版本也会把纯文本直接放在 message；看起来像损坏
            # JSON 的内容仍按坏消息上报，避免把半截上下文误收入库。
            if raw.lstrip().startswith(("{", "[")):
                raise
            text = raw
        else:
            if isinstance(envelope, dict):
                text = _content_text(envelope.get("content"))
            elif isinstance(envelope, str):
                text = envelope
            else:
                raise ValueError("user message 内层不是 object/string")
    else:
        raise ValueError("user message 缺少 message 字段")
    queries = [q.strip() for q in _USER_QUERY_RE.findall(text) if q.strip()]
    if queries:
        return "\n".join(queries)
    # 早期纯文本消息可直接使用；如果仍带 XML 上下文包装却没有
    # user_query，宁可跳过，避免把环境信息当成用户意图。
    if re.search(r"</?[A-Za-z][^>]*>", text):
        return ""
    return text.strip()


def _clean_line(text):
    return " ".join(str(text or "").split())


def _load_conversation(cid, record, session, since, errors):
    index_path = record["index"]
    index = _read_json(index_path, errors, f"CodeBuddy 会话 {cid[:8]}")
    if index is None:
        return []
    messages = index.get("messages") if isinstance(index, dict) else None
    if not isinstance(messages, list):
        _error(errors, f"CodeBuddy 会话索引格式错误:{cid[:8]}")
        return []

    by_day = defaultdict(lambda: {
        "ts": [], "users": [], "n_user": 0, "n_asst": 0, "n_tool": 0,
    })
    message_dir = os.path.join(os.path.dirname(index_path), "messages")
    for pointer in messages:
        if not isinstance(pointer, dict):
            _error(errors, f"CodeBuddy 消息索引格式错误:{cid[:8]}")
            continue
        mid = str(pointer.get("id") or "")
        if not _CID_RE.match(mid):
            _error(errors, f"CodeBuddy 消息 id 无效:{cid[:8]}")
            continue
        message_path = os.path.join(message_dir, f"{mid}.json")
        message = _read_json(message_path, errors, f"CodeBuddy 消息 {cid[:8]}")
        if not isinstance(message, dict):
            continue
        lts = util.iso_utc_to_local(message.get("createdAt"))
        day = str(lts or "")[:10]
        if not _DAY_RE.match(day):
            _error(errors, f"CodeBuddy 消息时间无效:{cid[:8]}:{mid[:8]}")
            continue
        bucket = by_day[day]
        bucket["ts"].append(lts)
        role = str(message.get("role") or pointer.get("role") or "")
        if role == "user":
            bucket["n_user"] += 1
            try:
                text = _user_text(message)
            except Exception as exc:
                _error(errors, f"CodeBuddy 用户消息解析失败:{cid[:8]}:{mid[:8]}:{exc}")
                continue
            if text:
                bucket["users"].append(text)
        elif role == "assistant":
            bucket["n_asst"] += 1
        elif role == "tool":
            bucket["n_tool"] += 1

    if not by_day:
        return []
    cwd = str(session.get("cwd") or "")
    project = os.path.basename(cwd.rstrip(os.sep)) if cwd else "codebuddy"
    conversation = record["meta"]
    title = (session.get("customTitle") or conversation.get("name") or
             session.get("title") or "")
    title = _clean_line(title)[:INTENT_CAP]
    earliest = min(by_day)
    entries = []
    for day in sorted(by_day):
        if day < since:
            continue
        bucket = by_day[day]
        bucket["ts"].sort()
        real = [text.strip() for text in bucket["users"] if text.strip()]
        opening = real[0] if real else ""
        intent = title if day == earliest and title else _clean_line(opening)[:INTENT_CAP]
        body = " / ".join(_clean_line(text) for text in real)[:BODY_CAP]
        entries.append({
            "id": f"codebuddy:{cid}:{day}",
            "date": day,
            "ts": bucket["ts"][0],
            "project": project,
            "tool": "codebuddy",
            "kind": "session",
            "summary": intent or "(CodeBuddy 续聊)",
            "ref": index_path,
            "detail": {
                "start": bucket["ts"][0], "end": bucket["ts"][-1],
                "user": bucket["n_user"], "asst": bucket["n_asst"],
                "tool": bucket["n_tool"], "opening": opening[:OPENING_CAP],
                "body": body,
            },
        })
    return entries


def collect_diagnostic(cfg, since):
    src = cfg.get("sources", {}).get("codebuddy", {})
    if not src.get("enabled"):
        return {"entries": [], "errors": [], "status": "success",
                "message": "CodeBuddy 已关闭", "sessions": 0}

    paths = source_paths(cfg)
    errors = []
    sessions = _session_metadata(paths["session_db"], errors)
    conversations = _discover_conversations(paths["extension_data"], errors)
    entries = []
    for cid, record in sorted(conversations.items()):
        session = sessions.get(cid, {})
        if session.get("deletedAt"):
            continue
        entries.extend(_load_conversation(cid, record, session, since, errors))

    status = "partial" if errors else "success"
    message = (f"发现 {len(conversations)} 个 CodeBuddy 会话，生成 {len(entries)} 条记录"
               if conversations else "未发现 CodeBuddy 本地会话")
    if errors:
        message += f"，{len(errors)} 项本地历史未能读取"
    return {"entries": entries, "errors": errors, "status": status,
            "message": message, "sessions": len(conversations),
            "path": paths["extension_data"]}


def collect(cfg, since):
    """保持历史 collector 契约：CLI 仍只接收 entry 列表。"""
    return collect_diagnostic(cfg, since)["entries"]
