# -*- coding: utf-8 -*-
"""Codex Feishu Bridge 话题采集器。

从 ``~/.feishu-codex-bridge/bots/*/projects.json`` 发现 Bridge 绑定的飞书群，
通过已登录的 lark-cli 用户身份读取话题。用“本人是否真实发言”决定是否采集，
再逐页读取完整话题：保留所有真人消息与非卡片机器人文本，附件只记录元数据，
不下载二进制原件。
"""
import glob
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta

from .. import util

TITLE_CAP = 180
OPENING_CAP = 1200
PAGE_SIZE = 50
MAX_PAGES = 1000     # 分页硬上限(1000×50=5万条),防服务端一直 has_more+新 token 时无限翻页

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]*)\)")
_PLAIN_IMAGE_RE = re.compile(r"\[Image:\s*([^\]]+)\]", re.I)
_RESOURCE_RE = re.compile(r"<(file|video|audio|media)\b([^>]*)/?>", re.I)
_ATTR_RE = re.compile(r"([\w-]+)=(?:\"([^\"]*)\"|'([^']*)')")
_MEDIA_RE = re.compile(r"<(?:file|video|audio|media|sticker)\b[^>]*?/?>", re.I)
_BOT_TEXT_TYPES = {"text", "post"}


def _json_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def bridge_projects(home):
    """返回 Bridge 绑定群，按 chat_id 去重。"""
    paths = [os.path.join(home, "projects.json")]
    paths += sorted(glob.glob(os.path.join(home, "bots", "*", "projects.json")))
    projects = {}
    for path in paths:
        data = _json_file(path)
        for raw in data.get("projects", []) if isinstance(data, dict) else []:
            chat_id = str(raw.get("chatId") or "").strip()
            if not chat_id:
                continue
            cwd = str(raw.get("cwd") or "").strip()
            projects[chat_id] = {
                "chat_id": chat_id,
                "name": str(raw.get("name") or "飞书话题").strip(),
                "cwd": cwd,
                "project": os.path.basename(cwd.rstrip(os.sep)) if cwd else
                           str(raw.get("name") or "codex-feishu-bridge").strip(),
            }
    return list(projects.values())


def probe(cfg):
    src = cfg.get("sources", {}).get("codex_feishu_bridge", {})
    home = util.expand(src.get("home", "~/.feishu-codex-bridge"))
    return {"home": home, "exists": os.path.isdir(home),
            "projects": len(bridge_projects(home)),
            "lark_cli": shutil.which(src.get("lark_cli", "lark-cli")) or ""}


def _decode_output(result):
    for text in (result.stdout, result.stderr):
        text = (text or "").strip()
        if not text:
            continue
        try:
            return json.loads(text)
        except Exception:
            pass
    detail = (result.stderr or result.stdout or "lark-cli 调用失败").strip()
    raise RuntimeError(detail[:1000])


def _run_lark(binary, args, timeout):
    try:
        result = subprocess.run([binary] + args, capture_output=True, text=True,
                                timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError("未找到 lark-cli")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"lark-cli 读取超时（{timeout}s）")
    data = _decode_output(result)
    if result.returncode != 0 or (isinstance(data, dict) and data.get("ok") is False):
        err = data.get("error", {}) if isinstance(data, dict) else {}
        msg = err.get("message") or err.get("hint") or "lark-cli 调用失败"
        raise RuntimeError(str(msg))
    return data


def _owner_open_id(src, binary, timeout):
    configured = str(src.get("user_open_id") or "").strip()
    if configured:
        return configured
    data = _run_lark(binary, ["auth", "status", "--json"], timeout)
    user = ((data.get("identities") or {}).get("user") or {})
    open_id = str(user.get("openId") or user.get("open_id") or "").strip()
    if not open_id:
        raise RuntimeError("lark-cli 用户身份未登录，无法识别本人 open_id")
    return open_id


def _list_chat_roots(binary, chat_id, since, end, timeout):
    roots, page_token = [], ""
    seen_tokens, pages = set(), 0
    while True:
        args = ["im", "+chat-messages-list", "--as", "user",
                "--chat-id", chat_id, "--start", since, "--end", end,
                "--order", "asc", "--page-size", str(PAGE_SIZE), "--no-reactions",
                "--format", "json"]
        if page_token:
            args += ["--page-token", page_token]
        raw = _run_lark(binary, args, timeout)
        data = raw.get("data", raw) if isinstance(raw, dict) else {}
        roots.extend(data.get("messages") or [])
        pages += 1
        if not data.get("has_more"):
            break
        if pages >= MAX_PAGES:
            raise RuntimeError(f"飞书消息分页超过 {MAX_PAGES} 页上限,疑似异常,已中止(不静默截断)")
        next_token = str(data.get("page_token") or "")
        if not next_token or next_token in seen_tokens:
            raise RuntimeError("飞书消息分页未返回有效 page_token")
        seen_tokens.add(next_token)
        page_token = next_token
    return roots


def _iso_day(day):
    """消息搜索要求显式时区；使用运行 Loom 的本地时区。"""
    offset = datetime.now().astimezone().strftime("%z") or "+0000"
    offset = f"{offset[:3]}:{offset[3:]}"
    return f"{day}T00:00:00{offset}"


def _paged_messages(binary, base_args, timeout):
    """手动翻完 lark-cli 消息分页；任何坏 token 都报错，禁止静默截断。"""
    messages, page_token, seen_tokens, pages = [], "", set(), 0
    while True:
        args = list(base_args)
        if page_token:
            args += ["--page-token", page_token]
        raw = _run_lark(binary, args, timeout)
        data = raw.get("data", raw) if isinstance(raw, dict) else {}
        messages.extend(data.get("messages") or [])
        pages += 1
        if not data.get("has_more"):
            return messages, pages
        if pages >= MAX_PAGES:
            raise RuntimeError(f"飞书消息分页超过 {MAX_PAGES} 页上限,疑似异常,已中止(不静默截断)")
        next_token = str(data.get("page_token") or "")
        if not next_token or next_token in seen_tokens:
            raise RuntimeError("飞书消息分页未返回有效 page_token")
        seen_tokens.add(next_token)
        page_token = next_token


def _search_owner_messages(binary, chat_id, owner_open_id, since, end, timeout):
    """按真实 sender 搜索本人消息，避免“只被 @”误判，也能发现旧根话题的新回复。"""
    args = ["im", "+messages-search", "--as", "user", "--query", "",
            "--chat-id", chat_id, "--sender", owner_open_id,
            "--start", _iso_day(since), "--end", _iso_day(end),
            "--page-size", str(PAGE_SIZE), "--no-reactions", "--format", "json"]
    return _paged_messages(binary, args, timeout)[0]


def _list_thread_replies(binary, thread_id, timeout):
    """完整读取一个话题的回复；话题 API 无时间过滤，只能逐页翻完。"""
    args = ["im", "+threads-messages-list", "--as", "user",
            "--thread", thread_id, "--order", "asc",
            "--page-size", str(PAGE_SIZE), "--no-reactions", "--format", "json"]
    return _paged_messages(binary, args, timeout)


def _clean_content(value):
    text = str(value or "").replace("\r", "").strip()
    return text


def _title(value):
    text = _IMAGE_RE.sub(" ", _clean_content(value))
    text = _MEDIA_RE.sub(" ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    return text[:TITLE_CAP]


def _is_card(message):
    # 旧 Bridge/转发场景里机器人卡片偶尔显示成 user sender，所以类型和正文双检。
    return (str(message.get("msg_type") or "").lower() == "interactive" or
            _clean_content(message.get("content")).lower().startswith("<card"))


def _human(message):
    sender = message.get("sender") or {}
    return (not message.get("deleted") and sender.get("sender_type") == "user" and
            bool(sender.get("id")) and not _is_card(message))


def _retained(message):
    """保留所有真人消息，以及机器人的非卡片文本；系统消息和机器人附件不入正文。"""
    if message.get("deleted") or _is_card(message):
        return False
    sender = message.get("sender") or {}
    if sender.get("sender_type") == "user" and sender.get("id"):
        return True
    return (sender.get("sender_type") in ("app", "bot") and
            str(message.get("msg_type") or "").lower() in _BOT_TEXT_TYPES and
            bool(_clean_content(message.get("content"))))


def _attrs(text):
    return {m.group(1).lower(): (m.group(2) if m.group(2) is not None else m.group(3))
            for m in _ATTR_RE.finditer(text or "")}


def _attachments(message):
    """从渲染后的资源标记提取元数据；绝不下载附件原件。"""
    content = _clean_content(message.get("content"))
    found, seen = [], set()

    def add(kind, key="", **extra):
        item = {"message_id": str(message.get("message_id") or ""),
                "type": kind, "key": str(key or "")}
        item.update({k: str(v) for k, v in extra.items() if v not in (None, "")})
        marker = (item["message_id"], item["type"], item["key"], item.get("name", ""))
        if marker not in seen:
            seen.add(marker)
            found.append(item)

    for match in _IMAGE_RE.finditer(content):
        add("image", match.group(1))
    for match in _PLAIN_IMAGE_RE.finditer(content):
        add("image", match.group(1).strip())
    for match in _RESOURCE_RE.finditer(content):
        kind, attrs = match.group(1).lower(), _attrs(match.group(2))
        add(kind, attrs.get("key", ""), name=attrs.get("name"),
            duration=attrs.get("duration"))
    if str(message.get("msg_type") or "").lower() == "sticker" and not found:
        add("sticker")
    return found


def _message_meta(message):
    sender = message.get("sender") or {}
    out = {
        "id": str(message.get("message_id") or ""),
        "ts": _message_ts(message),
        "sender": str(sender.get("name") or sender.get("id") or ""),
        "sender_id": str(sender.get("id") or ""),
        "sender_type": str(sender.get("sender_type") or ""),
        "msg_type": str(message.get("msg_type") or ""),
    }
    if message.get("updated"):
        out["updated_at"] = str(message.get("update_time") or "")
    return out


def _message_ts(message):
    raw = str(message.get("create_time") or "").strip()
    if not raw:
        return ""
    if len(raw) == 16 and raw[10] == " ":
        return raw.replace(" ", "T") + ":00"
    if " " in raw and "T" not in raw:
        return raw.replace(" ", "T", 1)
    return raw


def _topic_messages(root):
    messages = [root] + list(root.get("thread_replies") or [])
    unique = {}
    for message in messages:
        if not isinstance(message, dict) or message.get("deleted"):
            continue
        key = message.get("message_id") or f"{_message_ts(message)}:{len(unique)}"
        unique[key] = message
    return sorted(unique.values(), key=lambda x: (_message_ts(x), x.get("message_id", "")))


def topic_entries(project, roots, owner_open_id, since):
    """把完整话题转成按天条目；参与资格看本人发言，正文保留完整对话。"""
    entries = []
    for root in roots:
        thread_id = str(root.get("thread_id") or "").strip()
        if not thread_id:
            continue
        messages = _topic_messages(root)
        humans = [m for m in messages if _human(m)]
        human_ids = {str((m.get("sender") or {}).get("id") or "") for m in humans}
        # 只被 @ 不算参与；本人必须真实发送过非卡片消息。
        if owner_open_id not in human_ids:
            continue
        retained = [m for m in messages if _retained(m)]
        if not retained:
            continue

        participant_names, bot_names = [], []
        for message in retained:
            sender = message.get("sender") or {}
            name = str(sender.get("name") or sender.get("id") or "").strip()
            target = participant_names if sender.get("sender_type") == "user" else bot_names
            if name and name not in target:
                target.append(name)

        opening_message = root if _retained(root) else retained[0]
        opening = _clean_content(opening_message.get("content"))
        summary = _title(opening)
        if not summary:
            summary = next((_title(m.get("content")) for m in retained
                            if _title(m.get("content"))), "飞书话题")
        by_day = {}
        for message in retained:
            ts = _message_ts(message)
            if not ts or ts[:10] < since:
                continue
            by_day.setdefault(ts[:10], []).append((ts, message))
        ref = str(root.get("message_app_link") or root.get("_message_app_link") or "").strip()
        cards = sum(1 for m in messages if _is_card(m))
        root_available = bool(root.get("_root_available", True))
        # fetch_complete 表示飞书当前可见的话题流已翻到末页；群消息列表未返回独立
        # 根消息时，root_available 单独标 false，但 position=0 起的完整话题流仍算完成。
        fetch_complete = bool(root.get("_thread_complete", True))
        topic_start = _message_ts(retained[0])
        topic_end = _message_ts(retained[-1])
        for day, rows in sorted(by_day.items()):
            lines, attachments, message_meta = [], [], []
            for ts, message in rows:
                sender = message.get("sender") or {}
                name = str(sender.get("name") or sender.get("id") or "某人")
                content = _clean_content(message.get("content"))
                if not content:
                    content = f"[{message.get('msg_type') or 'message'}]"
                lines.append(f"{ts[11:16]} {name}: {content}")
                attachments.extend(_attachments(message))
                message_meta.append(_message_meta(message))
            entries.append({
                "id": f"codex_feishu_bridge:{thread_id}:{day}",
                "date": day, "ts": rows[0][0],
                "project": (project.get("project") or project.get("name") or
                            "codex-feishu-bridge"),
                "tool": "codex_feishu_bridge", "kind": "topic", "summary": summary,
                "ref": ref or thread_id,
                "detail": {
                    "chat": project.get("name") or "",
                    "thread_id": thread_id,
                    "participants": participant_names,
                    "bots": bot_names,
                    "start": rows[0][0], "end": rows[-1][0],
                    "topic_start": topic_start, "topic_end": topic_end,
                    "opening": opening[:OPENING_CAP],
                    # 真相层保存完整正文；FTS 自己有独立的 100k 索引上限。
                    "body": "\n".join(lines),
                    "message_count": len(rows),
                    "topic_message_count": len(retained),
                    "source_message_count": len(messages),
                    "excluded_card_count": cards,
                    "fetch_pages": int(root.get("_thread_pages", 1)),
                    "root_available": root_available,
                    "fetch_complete": fetch_complete,
                    "attachments": attachments,
                    "message_meta": message_meta,
                },
            })
    return entries


def collect_diagnostic(cfg, since):
    src = cfg.get("sources", {}).get("codex_feishu_bridge", {})
    if not src.get("enabled"):
        return {"entries": [], "errors": []}
    home = util.expand(src.get("home", "~/.feishu-codex-bridge"))
    projects = bridge_projects(home)
    if not projects:
        return {"entries": [], "errors": [f"未发现 Bridge 绑定项目:{home}"]}
    binary = src.get("lark_cli", "lark-cli")
    timeout = int(src.get("timeout_seconds", 120))
    try:
        owner = _owner_open_id(src, binary, timeout)
    except Exception as exc:
        return {"entries": [], "errors": [str(exc)]}

    end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    entries, errors = [], []
    for project in projects:
        try:
            owner_messages = _search_owner_messages(
                binary, project["chat_id"], owner, since, end, timeout)
        except Exception as exc:
            errors.append(f"{project['name']}:搜索本人消息失败:{exc}")
            continue

        owner_by_thread = {}
        for item in owner_messages:
            thread_id = str(item.get("thread_id") or "").strip()
            sender_id = str((item.get("sender") or {}).get("id") or "")
            if thread_id and sender_id == owner and _human(item):
                owner_by_thread.setdefault(thread_id, []).append(item)
        if not owner_by_thread:
            continue

        # 群消息列表提供话题根消息；其自动展开的回复有上限，明确丢弃，下面逐话题分页。
        roots_by_thread = {}
        try:
            chat_items = _list_chat_roots(binary, project["chat_id"], since, end, timeout)
            for item in chat_items:
                thread_id = str(item.get("thread_id") or "").strip()
                if not thread_id:
                    continue
                root = dict(item)
                root.pop("thread_replies", None)
                roots_by_thread[thread_id] = root
        except Exception as exc:
            # 根消息缺失不影响回复分页，保留数据但显式标 root_available=false。
            errors.append(f"{project['name']}:读取话题根消息失败:{exc}")

        expanded_roots = []
        for thread_id, owner_hits in sorted(owner_by_thread.items()):
            try:
                replies, pages = _list_thread_replies(binary, thread_id, timeout)
            except Exception as exc:
                # 分页不完整时绝不拿半截结果覆盖旧数据。
                errors.append(f"{project['name']}:{thread_id}:读取完整回复失败:{exc}")
                continue
            real_root = roots_by_thread.get(thread_id)
            candidates = ([real_root] if real_root else []) + replies + owner_hits
            candidates = [m for m in candidates if isinstance(m, dict)]
            if not candidates:
                continue
            seed = dict(real_root or min(candidates,
                                         key=lambda m: (_message_ts(m),
                                                        m.get("message_id", ""))))
            seed["thread_id"] = thread_id
            seed_id = str(seed.get("message_id") or "")
            merged = replies + owner_hits
            seed["thread_replies"] = [m for m in merged
                                      if str(m.get("message_id") or "") != seed_id]
            seed["_thread_pages"] = pages
            seed["_thread_complete"] = True
            seed["_root_available"] = bool(real_root)
            if not seed.get("message_app_link"):
                seed["_message_app_link"] = next(
                    (str(m.get("message_app_link") or "") for m in candidates
                     if m.get("message_app_link")), "")
            expanded_roots.append(seed)
        entries.extend(topic_entries(project, expanded_roots, owner, since))
    message = (f"{len(projects)} 个 Codex Feishu Bridge 项目群；"
               "完整收集本人实际发言的话题")
    return {"entries": entries, "errors": errors, "message": message}


def collect(cfg, since):
    result = collect_diagnostic(cfg, since)
    for error in result.get("errors", []):
        util.log(f"  [codex_feishu_bridge] {error}")
    return result["entries"]
