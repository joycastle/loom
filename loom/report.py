# -*- coding: utf-8 -*-
"""日报导入:飞书日报 xlsx → 每行一天的 `report` 条目(今日工作/思考/明日计划)。

日报是 git 提交/AI 会话都抓不到的【叙事层】——为什么这么做、当天的思考、明天的打算。
作为一等条目入库(entries.jsonl → 可检索 + 渲染进当天日记),不碰手写 notes.md。
可重复导入:id=report:<date>,upsert 幂等。纯标准库(复用 dataset 的 xlsx 解析)。
"""
import re

from . import dataset, util

# 列名模糊匹配(含关键词即可,容忍表头措辞变化)
_COL_KW = {"date": ("提交时间", "日期"), "work": ("今日工作", "工作与进度", "今日进度"),
           "thinking": ("今日思考", "思考", "问题与心得"), "plan": ("明日", "明天", "计划")}


def _find_cols(header):
    idx = {}
    for key, kws in _COL_KW.items():
        for i, h in enumerate(header):
            if any(kw in (h or "") for kw in kws):
                idx[key] = i
                break
    return idx


def import_xlsx(cfg, path):
    """解析日报 xlsx,返回 report 条目列表。找不到日期列 → ValueError。"""
    rows, _ = dataset._xlsx_rows(util.expand(path))
    if not rows:
        return []
    idx = _find_cols(rows[0])
    if "date" not in idx:
        raise ValueError("日报 xlsx 找不到「提交时间/日期」列")

    def cell(r, key):
        i = idx.get(key)
        return (r[i].strip() if i is not None and i < len(r) and r[i] else "")

    out = []
    for r in rows[1:]:
        raw = cell(r, "date")
        m = re.match(r"(\d{4}-\d{2}-\d{2})[ T]?(\d{2}:\d{2})?", raw)
        if not m:
            continue
        date = m.group(1)
        ts = f"{date}T{m.group(2)}" if m.group(2) else f"{date}T18:00:00"
        work, thinking, plan = cell(r, "work"), cell(r, "thinking"), cell(r, "plan")
        if not (work or thinking or plan):
            continue
        summary = " ".join(work.split())[:80] or "日报"
        content = "\n".join(x for x in (work, thinking, plan) if x)  # search 用(_aux_of 读 content)
        out.append({
            "id": f"report:{date}", "date": date, "ts": ts,
            "project": "日报", "tool": "日报", "kind": "report",
            "summary": summary, "ref": f"日报:{date}",
            "detail": {"work": work, "thinking": thinking, "plan": plan, "content": content},
        })
    return out
