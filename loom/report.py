# -*- coding: utf-8 -*-
"""日报导入:飞书日报 xlsx → 每行一天的 `report` 条目(今日工作/思考/明日计划)。

日报是 git 提交/AI 会话都抓不到的【叙事层】——为什么这么做、当天的思考、明天的打算。
作为一等条目入库(entries.jsonl → 可检索 + 渲染进当天日记),不碰手写 notes.md。
可重复导入:id=report:<date>,upsert 幂等。纯标准库(复用 dataset 的 xlsx 解析)。
"""
import re

from . import cluster, config, dataset, store, util


def _rcfg(cfg):
    """report 策略:用户 config 覆盖内置默认(词表/阈值全走这里,源码不写死)。"""
    default = config.DEFAULT_CONFIG["report"]
    rc = (cfg or {}).get("report", {}) if isinstance((cfg or {}).get("report"), dict) else {}
    return {k: rc.get(k, default[k]) for k in default}


def _find_cols(header, col_kw):
    idx = {}
    for key, kws in col_kw.items():
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
    idx = _find_cols(rows[0], _rcfg(cfg)["column_keywords"])
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


def _tier(score, tiers):
    return "高" if score >= tiers["high"] else ("中" if score >= tiers["mid"] else "低")


# 来源展示名(纯标签,非策略):把采集器内部名换成人看的词。未知源原样显示。
_TOOL_LABEL = {"feishu_user": "飞书", "feishu": "飞书", "claude": "Claude",
               "codex": "Codex", "cursor": "Cursor", "git": "git",
               "codebuddy": "CodeBuddy", "opencode": "OpenCode", "pi": "pi"}


def _coverage(items):
    """本日素材按来源计数——写日报前的'对账清单',逼 AI 别只凭当前 session 记忆写。"""
    from collections import Counter
    c = Counter(e.get("tool") or "?" for e in items)
    parts = [f"{_TOOL_LABEL.get(t, t)} {n}" for t, n in c.most_common()]
    return parts, len(items)


def _member_detail(m, by_id):
    """一条簇成员的证据行(带 ref 回链;ref 跟着 member 走,AI 只表达不编造)。"""
    e = by_id.get(m["id"], {})
    d = e.get("detail") or {}
    tag = {"commit": "提交", "session": "会话", "chat": "聊天", "note": "笔记"}.get(
        m["kind"], m["kind"])         # 来源由 m['tool'] 展示,不把 kind 绑死某产品
    line = f"  - [{tag}/{m['tool']}] {m['summary']}  (ref: {m['ref']})"
    extra = ""
    if m["kind"] == "commit":
        extra = f"{d.get('files',0)}文件 +{d.get('ins',0)}/-{d.get('del',0)}"
    elif m["kind"] == "session":
        op = " ".join((d.get("opening") or "").split())[:200]
        extra = f"开场:{op}" if op and not op.startswith(m["summary"][:20]) else ""
    elif m["kind"] == "chat":
        extra = " ".join((d.get("body") or "").split())[:200]
    if extra:
        line += f"\n      {extra}"
    return line


def gen_material(cfg, date):
    """聚合某天原材料 → **先跨源聚类成「一件事」的簇**、按重要度排序,再交给 AI 写。

    对比旧版按信息源类型平铺:这里把 git/会话/飞书/笔记里"同一件事"的条目聚成一簇
    (共享标识符/结构边/关键词),让 AI 只做表达、不用自己现场做聚类+取舍。
    """
    items = _day_items(date)
    if not items:
        return f"({date} 无可汇总的活动;先 loom sync)"
    tiers = _rcfg(cfg)["importance_tiers"]
    by_id = {e["id"]: e for e in items}
    clusters = cluster.cluster(by_id, cfg)               # 聚类策略走 cfg
    clusters.sort(key=lambda c: -c["importance"]["score"])
    multi = [c for c in clusters if not c["singleton"]]
    singles = [c for c in clusters if c["singleton"]]

    L = [f"# {date} 原材料(已跨源聚类,供 AI 写日报)", ""]
    parts, total = _coverage(items)
    L.append(f"## 本日素材覆盖 · 共 {total} 条 · {' / '.join(parts)}")
    L.append("> ⚠️ 写日报前先对账:**日报要覆盖上面每一个来源**,别只把你此刻正在用的那个 AI 会话"
             "(不管是 Claude / Codex / Cursor,即你现在这个)总结进去。凡当前会话之外的来源"
             "(git 提交 / 其它 AI 工具的会话 / 飞书),都要么在日报里有所体现,要么被明确判为"
             "次要——不能因为不在你此刻的对话记忆里就漏掉。")
    L.append("")
    L.append("## 重要度表(决定详略:高=展开,低=一句带过)")
    for c in multi:
        f = c["importance"]
        clue = c["members"][0]["summary"]
        L.append(f"- **{c['label_hint']}** · {_tier(f['score'], tiers)}(分{f['score']}) · "
                 f"{' '.join(clue.split())[:40]}"
                 f"  〔跨{f['features']['kind_diversity']}源/{f['features']['member_count']}条〕")
    if not multi:
        L.append("- (今天没有跨源聚到一起的'一件事',多为独立单条,见下)")
    L.append("")

    for c in multi:
        f = c["importance"]
        L.append(f"## 【{c['label_hint']}】重要度 {f['score']}({_tier(f['score'], tiers)}) "
                 f"· 跨{f['features']['kind_diversity']}源 {f['features']['member_count']}条")
        reasons = sorted({r for ed in c["edges"] for r in ed["reasons"]})
        if reasons:
            L.append(f"  关联依据:{' / '.join(reasons[:4])}")
        shown = c["members"][:6]                          # 超大簇只列前几条,防刷屏
        for m in shown:
            L.append(_member_detail(m, by_id))
        if len(c["members"]) > len(shown):
            L.append(f"  …及其余 {len(c['members']) - len(shown)} 条(同一件事)")
        L.append("")

    if singles:
        L.append(f"## 其他独立单条 ({len(singles)},次要,建议一句话打包)")
        for c in sorted(singles, key=lambda x: x["members"][0]["ts"]):
            m = c["members"][0]
            L.append(f"- [{m['kind']}/{m['tool']}] {m['summary']}  (ref: {m['ref']})")
        L.append("")

    L += ["---",
          "请基于以上**已聚类**的真实痕迹,以第一人称写这天的日报。写法(稳定 SOP):",
          "1. 开头总线(BLUF):点出这天**并行的几条线**(常有 2~3 条,别硬压成'主线只有一件事');"
          "重要度看'跨源多样 + 对本职的分量',**不是提交数量**——你此刻这个 AI 会话一直在干的事"
          "(哪怕提交最多)也不天然是头条,别让 session 偏见带偏排序。",
          "2. 「今日工作与进度」:**按上面的簇、每簇写成一条**——先给结论(加粗),"
          "再跟 2~4 条带 ref 的证据(把同一件事的多源信号合并成一条,别拆开)。"
          "高优先簇≤5 个;没有 ref 证据支撑的结论要降级或标注「未见明确证据」。",
          "3. 次要的独立单条:合并成「其他事项:A、B、C」一句话带过,不逐条展开。",
          "4. 「今日思考」「明日计划」:只写材料里有依据的,不虚构。",
          "5. 存回前对账:回到顶部「本日素材覆盖」,逐来源确认每个来源都已体现或已判次要——"
          "尤其别漏掉当前会话之外的 git/Codex/飞书/其它 AI 会话。",
          f"写好存回:loom report set {date} --file <日报.md>(或管道 stdin)"]
    return "\n".join(L)


def _split_sections(text, section_kw):
    """按标题关键词把日报切成 work/thinking/plan 段;关键词表由配置给,源码不写死。"""
    order = ["work", "thinking", "plan"]
    cur, buf = "work", {"work": [], "thinking": [], "plan": []}
    for line in text.splitlines():
        m = re.match(r"#{1,6}\s*(.+)|\*\*(.+?)\*\*\s*$", line.strip())
        head = (m.group(1) or m.group(2)) if m else None
        if head:
            low = head.lower()
            for k in order:
                if any(kw.lower() in low for kw in section_kw.get(k, [])):
                    cur = k
                    break
            continue
        buf[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in buf.items()}


def set_from_text(cfg, date, text):
    """把 AI 写好的日报文本存成 report 条目(按 ## 工作/思考/计划 切段;切不出就整段作工作)。"""
    secs = _split_sections(text, _rcfg(cfg)["section_keywords"])
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
