# -*- coding: utf-8 -*-
"""loom MCP server:把台账暴露成 AI 编码工具(Claude Code / Codex / Cursor)可直接调用的原生工具。

skill 是「教 AI 怎么敲 loom 命令」;MCP 是「让 AI 直接调用 loom」——省掉记命令、拼 bash 的一层。
在 Claude Code 里注册后,写代码时可以边查台账边归档:

    claude mcp add loom -- loom mcp-serve
    # 或写进项目 .mcp.json: {"mcpServers": {"loom": {"command": "loom", "args": ["mcp-serve"]}}}

传输:MCP stdio —— 换行分隔的 JSON-RPC 2.0。stdout 只走协议消息,日志一律走 stderr。
纯标准库(json + sys),不引入任何依赖,不破 loom 的零依赖约束。
"""
import json
import sys

PROTOCOL_VERSION = "2025-06-18"
SERVER_VERSION = "1.0.0"


# ---------------------------------------------------------------- 工具实现
# 每个工具:fn(cfg, args) -> str(人类可读文本,回给 AI 当 tool result)。
# 读多写少:search/topic/today 只读;note 是写操作,由 MCP 客户端(Claude Code)的
# 工具批准 UI 向用户确认后才执行,契合「向台账写入前先确认」的纪律。

def _tool_search(cfg, args):
    from . import search
    term = (args.get("term") or "").strip()
    hits = search.query(term, limit=int(args.get("limit") or 40),
                        project=args.get("project"), tool=args.get("tool"),
                        since=args.get("since"), until=args.get("until"))
    if not hits:
        return f"(无命中:{term or '空查询'})"
    out = []
    for e in hits:
        line = f"{e['date']} [{e['project']}/{e['tool']}] {e['summary']}  ({e['ref']})"
        snip = e.get("snip", "")
        if snip and snip not in (e.get("summary") or ""):
            line += f"\n    ↳ {snip}"
        out.append(line)
    out.append(f"\n共 {len(hits)} 条命中")
    return "\n".join(out)


def _tool_topic_ls(cfg, args):
    from . import topics
    return topics.tree(cfg)


def _tool_topic_show(cfg, args):
    from . import store, topics
    topic = (args.get("topic") or "").strip()
    if not topic:
        return "用法:topic 参数为主题名(先用 loom_topic_ls 看有哪些)"
    return topics.show(cfg, topic, store.load())


def _tool_related(cfg, args):
    from . import relations, store
    eid = (args.get("id") or "").strip()
    by_id = store.load()
    if eid not in by_id:
        return f"(无此条目 id:{eid};先用 loom_search 找到 id)"
    hits = relations.neighbors(by_id, eid, limit=int(args.get("limit") or 20))
    if not hits:
        return "(暂无自动派生的关联)"
    out = []
    for h in hits:
        out.append(f"{h['date']} [{h['project']}/{h['tool']}] {h['summary'][:56]}  "
                   f"({h['ref']})\n    ↳ {' · '.join(h['reasons'])}  id={h['id']}")
    return "\n".join(out)


def _tool_today(cfg, args):
    import os
    from datetime import datetime
    from . import config
    date = (args.get("date") or "").strip() or datetime.now().strftime("%Y-%m-%d")
    fp = os.path.join(config.journal_dir(cfg), f"{date}.md")
    if os.path.exists(fp):
        return open(fp, encoding="utf-8").read()
    return f"{date} 暂无记录(先跑 loom sync)"


def _tool_note(cfg, args):
    from . import intake
    text = (args.get("text") or "").strip()
    if not text:
        return "用法:text 参数为随手信息内容"
    tags = args.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    dest, msg = intake.note(cfg, text, to=args.get("to"), tags=tags,
                            title=args.get("title"))
    return ("✓ " if dest else "· ") + msg + \
        ("\n(下次 loom sync 后进检索 / 可被 loom topic 打标)" if dest else "")


TOOLS = [
    {
        "name": "loom_search",
        "description": "全文检索个人工作台账(git 提交 / AI 会话 / 文档 / 数据 / 需求)。"
                       "查历史「我之前做过什么、结论是什么、相关文档在哪」时优先用。中文子串可用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "检索词(空串+过滤=浏览)"},
                "project": {"type": "string", "description": "限定项目名"},
                "tool": {"type": "string", "description": "限定来源:git/claude/codex/cursor/…"},
                "since": {"type": "string", "description": "起始日期 YYYY-MM-DD"},
                "until": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                "limit": {"type": "integer", "description": "上限,默认 40"},
            },
            "required": ["term"],
        },
        "fn": _tool_search,
    },
    {
        "name": "loom_related",
        "description": "查一个条目自动派生的关联条目:会话产出的提交、共改同一文件的提交、"
                       "改动某文档的提交、同一对话的跨天续接。用于顺着一条记录追它的上下游。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "条目 id(loom_search 结果里的 id)"},
                "limit": {"type": "integer", "description": "上限,默认 20"},
            },
            "required": ["id"],
        },
        "fn": _tool_related,
    },
    {
        "name": "loom_topic_ls",
        "description": "列出主题树(把一件事的对话+提交+文档缝在一起的层级标签)。",
        "inputSchema": {"type": "object", "properties": {}},
        "fn": _tool_topic_ls,
    },
    {
        "name": "loom_topic_show",
        "description": "看一个主题的全景:该主题(含子主题)下的所有对话/提交/文档/数据,一条决策链。",
        "inputSchema": {
            "type": "object",
            "properties": {"topic": {"type": "string", "description": "主题名"}},
            "required": ["topic"],
        },
        "fn": _tool_topic_show,
    },
    {
        "name": "loom_today",
        "description": "读某天的工作日记 markdown(默认今天)。写日报/回顾时先读。",
        "inputSchema": {
            "type": "object",
            "properties": {"date": {"type": "string", "description": "日期 YYYY-MM-DD,默认今天"}},
        },
        "fn": _tool_today,
    },
    {
        "name": "loom_note",
        "description": "把一条随手信息(想法/结论/待办)记进台账。写操作——由你的 AI 客户端向用户确认后执行。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "记录内容"},
                "to": {"type": "string", "description": "归入的类目(可空)"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签"},
                "title": {"type": "string", "description": "标题(可空,默认取首句)"},
            },
            "required": ["text"],
        },
        "fn": _tool_note,
    },
]
_DISPATCH = {t["name"]: t["fn"] for t in TOOLS}


# ---------------------------------------------------------------- JSON-RPC
def _ok(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle(msg, cfg):
    """处理一条 JSON-RPC 请求,返回响应 dict;通知(无 id)返回 None。"""
    method = msg.get("method")
    rid = msg.get("id")
    is_notification = "id" not in msg

    if method == "initialize":
        return _ok(rid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "loom", "version": SERVER_VERSION},
        })
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None                       # 通知,不回
    if method == "ping":
        return _ok(rid, {})
    if method == "tools/list":
        listed = [{"name": t["name"], "description": t["description"],
                   "inputSchema": t["inputSchema"]} for t in TOOLS]
        return _ok(rid, {"tools": listed})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        fn = _DISPATCH.get(name)
        if not fn:
            return _err(rid, -32602, f"未知工具:{name}")
        try:
            text = fn(cfg, params.get("arguments") or {})
            return _ok(rid, {"content": [{"type": "text", "text": text}]})
        except Exception as e:            # 工具内部错误 → 作为工具结果回给 AI,别崩掉连接
            return _ok(rid, {"content": [{"type": "text", "text": f"工具出错:{e}"}],
                             "isError": True})

    if is_notification:
        return None
    return _err(rid, -32601, f"未知方法:{method}")


def serve(cfg, stdin=None, stdout=None):
    """stdio 主循环:逐行读 JSON-RPC 请求,逐行写响应。EOF 退出。"""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            # 解析失败:JSON-RPC parse error(无法确定 id)
            resp = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": "Parse error"}}
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()
            continue
        resp = handle(msg, cfg)
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()
