# -*- coding: utf-8 -*-
"""检索:从 entries.jsonl 派生的 SQLite FTS5(trigram)索引。

- **派生、可再生**:索引只是 entries 的镜像,删了自动重建,不违反「索引可再生」。
- **零新依赖**:sqlite3 是标准库;trigram tokenizer 支持中文子串匹配。
- **混合策略**:trigram 需 ≥3 字符,故 <3 字符的查询(如「需求」「飞书」)回退到
  LIKE 子串匹配——保证永不弱于旧版纯子串扫描,≥3 字符时又有 bm25 排序 + 结构化过滤。
"""
import json
import os
import re
import sqlite3

from . import util

# FTS5:summary/project 参与全文;其余列 UNINDEXED 仅存储/精确过滤。
_CREATE = """
CREATE VIRTUAL TABLE entries USING fts5(
    id UNINDEXED, date UNINDEXED, ts UNINDEXED,
    project, tool UNINDEXED, kind UNINDEXED,
    summary, ref UNINDEXED, aux,
    tokenize='trigram'
);
"""
_AUX_CAP = 100_000    # aux 索引正文/开场/大纲/文档全文;调大以便大参考文档也能全文检索
                      # (只有 docs/notes 会有长 aux;git 正文/AI 开场本就短。trigram 索引
                      #  约为文本长度的数倍,单人规模下体积无压力)


def _aux_of(e):
    d = e.get("detail") or {}
    parts = [" ".join(d.get("headings") or []), d.get("body") or "",
             d.get("opening") or "", d.get("content") or "", d.get("digest") or ""]
    return " ".join(p for p in parts if p)[:_AUX_CAP]


def _stale():
    """索引缺失或旧于 entries.jsonl → 需重建。"""
    if not os.path.exists(util.INDEX_PATH):
        return True
    if not os.path.exists(util.DATA_PATH):
        return False
    # <=:同一秒内改动也重建(mtime 常为秒级,严格 < 会漏)
    return os.path.getmtime(util.INDEX_PATH) <= os.path.getmtime(util.DATA_PATH)


def rebuild():
    """从 entries.jsonl 全量重建索引。快(单人规模),整体重写即可。"""
    os.makedirs(os.path.dirname(util.INDEX_PATH), exist_ok=True)
    tmp = f"{util.INDEX_PATH}.tmp.{os.getpid()}"   # 进程独占临时名,避免并发重建互撞
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    try:
        con.execute(_CREATE)
        rows = []
        if os.path.exists(util.DATA_PATH):
            for line in open(util.DATA_PATH, encoding="utf-8"):
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                rows.append((e.get("id", ""), e.get("date", ""), e.get("ts", ""),
                             e.get("project", ""), e.get("tool", ""), e.get("kind", ""),
                             e.get("summary", ""), e.get("ref", ""), _aux_of(e)))
        con.executemany(
            "INSERT INTO entries(id,date,ts,project,tool,kind,summary,ref,aux) "
            "VALUES (?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
    finally:
        con.close()
    os.replace(tmp, util.INDEX_PATH)  # 原子替换,避免半截索引
    return len(rows)


def ensure():
    if _stale():
        rebuild()


def _cjk_len(s):
    return len(re.sub(r"\s", "", s))   # 只数非空白字符:"a b" 算 2 → 走 LIKE 而非死 FTS 短语


def _py_snip(term, *texts, pad=42):
    """LIKE 路径的片段:在文本里找到 term,截取前后一段(折叠空白)。"""
    t = term.strip().lower()
    if not t:
        return ""
    for tx in texts:
        if not tx:
            continue
        i = tx.lower().find(t)
        if i >= 0:
            s, e = max(0, i - pad), min(len(tx), i + len(term) + pad)
            frag = " ".join(tx[s:e].split())
            return ("…" if s > 0 else "") + frag + ("…" if e < len(tx) else "")
    return ""


def _finish(cur, term):
    """统一收尾:取行 → 用 Python 提片段(避免 SQL snippet 跨列串味)→ 去掉 aux。"""
    hits = []
    for r in cur.fetchall():
        h = dict(r)
        aux = h.pop("aux", "")
        h["snip"] = _py_snip(term, h.get("summary", ""), aux)
        hits.append(h)
    return hits


def query(term, limit=40, project=None, tool=None, since=None, until=None):
    """返回按相关度排序的条目 dict 列表(含匹配片段 `snip`)。≥3 字符走 FTS5+bm25,否则 LIKE。"""
    ensure()
    limit = max(1, int(limit))     # 负数→SQLite 视为无限;0→空结果 —— 都夹住
    con = sqlite3.connect(util.INDEX_PATH)
    con.row_factory = sqlite3.Row
    cols = "id,date,ts,project,tool,kind,summary,ref,aux"   # 带 aux,片段用
    where, params = [], []
    if project:
        where.append("project = ?"); params.append(project)
    if tool:
        where.append("tool = ?"); params.append(tool)
    if since:
        where.append("date >= ?"); params.append(since)
    if until:
        where.append("date <= ?"); params.append(until)

    term = (term or "").strip()
    try:
        if _cjk_len(term) >= 3:
            # FTS5 MATCH:把查询当短语,双引号包裹并转义内部引号,避免语法错误/注入。
            phrase = '"' + term.replace('"', '""') + '"'
            sql = f"SELECT {cols} FROM entries WHERE entries MATCH ?"
            if where:
                sql += " AND " + " AND ".join(where)
            sql += " ORDER BY bm25(entries) LIMIT ?"
            try:
                return _finish(con.execute(sql, [phrase] + params + [limit]), term)
            except sqlite3.OperationalError:
                pass  # 罕见 MATCH 语法问题 → 落到 LIKE
        # <3 字符 或 MATCH 失败:LIKE 子串(转义 % _ \ 元字符),按时间倒序。
        esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{esc}%"
        clause = "(summary LIKE ? ESCAPE '\\' OR project LIKE ? ESCAPE '\\' OR aux LIKE ? ESCAPE '\\')"
        sql = f"SELECT {cols} FROM entries WHERE {clause}"
        if where:
            sql += " AND " + " AND ".join(where)
        sql += " ORDER BY ts DESC LIMIT ?"
        return _finish(con.execute(sql, [like, like, like] + params + [limit]), term)
    finally:
        con.close()
