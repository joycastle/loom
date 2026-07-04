# -*- coding: utf-8 -*-
"""日报导入:飞书日报 xlsx → 每行一天的 `report` 条目(今日工作/思考/明日计划)。

日报是 git 提交/AI 会话都抓不到的【叙事层】——为什么这么做、当天的思考、明天的打算。
作为一等条目入库(entries.jsonl → 可检索 + 渲染进当天日记),不碰手写 notes.md。
可重复导入:id=report:<date>,upsert 幂等。纯标准库(复用 dataset 的 xlsx 解析)。
"""
import re

from . import dataset, store, util

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

    # 同一天可能有多条(改稿重交 / 一天交两次)——按日期聚合合并,绝不让后一条覆盖前一条
    # (id=report:date 幂等,但同天多条必须合并而非丢弃)。
    agg = {}
    order = []
    for r in rows[1:]:
        m = re.match(r"(\d{4}-\d{2}-\d{2})[ T]?(\d{2}:\d{2})?", cell(r, "date"))
        if not m:
            continue
        date = m.group(1)
        ts = f"{date}T{m.group(2)}" if m.group(2) else f"{date}T18:00:00"
        work, thinking, plan = cell(r, "work"), cell(r, "thinking"), cell(r, "plan")
        if not (work or thinking or plan):
            continue
        if date not in agg:
            agg[date] = {"ts": ts, "work": [], "thinking": [], "plan": []}
            order.append(date)
        a = agg[date]
        a["ts"] = min(a["ts"], ts)                      # 一天多条取最早提交时刻
        for k, v in (("work", work), ("thinking", thinking), ("plan", plan)):
            if v and v not in a[k]:                     # 去重后按出现顺序拼接
                a[k].append(v)

    out = []
    for date in order:
        a = agg[date]
        work = "\n\n".join(a["work"])
        thinking = "\n\n".join(a["thinking"])
        plan = "\n\n".join(a["plan"])
        content = "\n".join(x for x in (work, thinking, plan) if x)  # search 用(_aux_of 读 content)
        out.append({
            "id": f"report:{date}", "date": date, "ts": a["ts"],
            "project": "日报", "tool": "日报", "kind": "report",
            "summary": " ".join(work.split())[:80] or "日报", "ref": f"日报:{date}",
            "detail": {"work": work, "thinking": thinking, "plan": plan, "content": content},
        })
    return out


# ---------------------------------------------------------------- AI 生成日报
def _day_items(date):
    return [e for e in store.load().values()
            if e.get("date") == date and e.get("kind") not in ("doc", "report")]


def gen_material(cfg, date):
    """聚合某天原材料(提交+body、AI会话+开场、数据/代码),交给 AI 写日报。"""
    items = _day_items(date)
    if not items:
        return f"({date} 无可汇总的活动;先 loom sync)"
    commits = [e for e in items if e["tool"] == "git"]
    sessions = [e for e in items if e["kind"] == "session"]
    assets = [e for e in items if e["kind"] == "note" and e["tool"] == "notes"]
    L = [f"# {date} 原材料(供 AI 写日报)", ""]
    if commits:
        L.append(f"## 提交 ({len(commits)})")
        for e in sorted(commits, key=lambda x: x["ts"]):
            d = e.get("detail", {})
            L.append(f"- {e['summary']}  ({d.get('files',0)}文件 +{d.get('ins',0)}/-{d.get('del',0)})")
            for bl in (d.get("body") or "").strip().splitlines():
                if bl.strip():
                    L.append(f"  {bl}")
        L.append("")
    if sessions:
        L.append(f"## AI 会话 ({len(sessions)})")
        for e in sorted(sessions, key=lambda x: x["ts"]):
            L.append(f"- [{e['tool']}] {e['summary']}")
            op = (e.get("detail", {}).get("opening") or "").strip()
            if op and not op.startswith(e["summary"][:20]):
                L.append(f"  开场:{' '.join(op.split())[:300]}")
        L.append("")
    if assets:
        L.append(f"## 数据/代码 ({len(assets)})")
        for e in sorted(assets, key=lambda x: x["ts"]):
            L.append(f"- {e['summary']}  ({(e.get('detail') or {}).get('path','')})")
        L.append("")
    L += ["---", "请基于以上真实痕迹,以第一人称写这天的日报,分三段(无内容可省):",
          "## 今日工作与进度", "## 今日思考", "## 明日计划",
          f"写好存回:loom report set {date} --file <日报.md>(或管道 stdin)"]
    return "\n".join(L)


_SEC = [("work", re.compile(r"工作|进度|完成|做了")),
        ("thinking", re.compile(r"思考|心得|问题|复盘")),
        ("plan", re.compile(r"明日|明天|计划|下一步|next|todo", re.I))]


def _split_sections(text):
    cur, buf = "work", {"work": [], "thinking": [], "plan": []}
    for line in text.splitlines():
        m = re.match(r"#{1,6}\s*(.+)|\*\*(.+?)\*\*\s*$", line.strip())
        head = (m.group(1) or m.group(2)) if m else None
        if head:
            for k, pat in _SEC:
                if pat.search(head):
                    cur = k
                    break
            continue
        buf[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in buf.items()}


def set_from_text(cfg, date, text):
    """把 AI 写好的日报文本存成 report 条目(按 ## 工作/思考/计划 切段;切不出就整段作工作)。"""
    secs = _split_sections(text)
    work = secs.get("work") or text.strip()
    thinking, plan = secs.get("thinking", ""), secs.get("plan", "")
    content = "\n".join(x for x in (work, thinking, plan) if x)
    return {
        "id": f"report:{date}", "date": date, "ts": f"{date}T18:00:00",
        "project": "日报", "tool": "日报", "kind": "report",
        "summary": " ".join(work.split())[:80] or "日报(AI)", "ref": f"日报:{date}",
        "detail": {"work": work, "thinking": thinking, "plan": plan,
                   "content": content, "ai_generated": True},
    }
