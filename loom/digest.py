# -*- coding: utf-8 -*-
"""AI 会话摘要:把一天里某个 AI 会话的【问 + 答】原文喂 AI,生成一句准确标题 +
一段可检索摘要,回填到那条 session 条目上。

为什么需要:采集器只索引【你的提问】,长会话里"继续梳理""这个再改改"这类首问代表
不了当天真的在干嘛(summary 糊、答案侧内容搜不到)。本模块补这个洞。

存哪:摘要不写进 entries.jsonl(那是采集器每次 sync 重建的),而是存独立 sidecar
`~/.loom/data/session_digests.json`(键=条目 id),每次采集后由 apply_all() 覆盖回条目
——和 topic_map 一样的"独立层 + 查询时叠加"模式,重采不会清掉摘要。

派生产出、非采集源:和日报同性质,按需跑 AI,默认不动。纯标准库。
"""
import json
import os

from . import store, util
from .collectors import claude as _cl

DIGEST_PATH = os.path.join(util.HOME, "data", "session_digests.json")

TITLE_CAP = 120
ABSTRACT_CAP = 1500
MSG_CAP = 1200          # 单条消息节选上限(避免一条超长回答吃满预算)
TRANSCRIPT_CAP = 24000  # 每个会话·天喂给 AI 的问答总量上限


def load():
    if os.path.exists(DIGEST_PATH):
        try:
            return json.load(open(DIGEST_PATH, encoding="utf-8"))
        except Exception:
            util.log("  [digest] session_digests.json 损坏,忽略")
    return {}


def save(d):
    os.makedirs(os.path.dirname(DIGEST_PATH), exist_ok=True)
    tmp = f"{DIGEST_PATH}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=0)
    os.replace(tmp, DIGEST_PATH)


def apply_all(by_id):
    """把已生成的会话摘要覆盖到对应条目:summary←title、detail.digest←abstract。

    幂等,在每次采集后调用 → 采集器重建的糊标题被真实摘要盖掉,且不丢失。
    保留原始首问到 detail.summary_raw(可回看采集器原判)。返回覆盖条数。"""
    d = load()
    n = 0
    for eid, dg in d.items():
        e = by_id.get(eid)
        if not e:
            continue
        det = e.setdefault("detail", {})
        if dg.get("title"):
            if "summary_raw" not in det:
                det["summary_raw"] = e.get("summary", "")
            e["summary"] = dg["title"]
        det["digest"] = dg.get("abstract", "")
        det["ai_digest"] = True
        n += 1
    return n


# ---------------------------------------------------------------- 生成原材料
def _day_session_entries(date):
    """当天所有可摘要的 claude 会话条目(有完整 transcript 可回读的)。"""
    return sorted(
        [e for e in store.load().values()
         if e.get("kind") == "session" and e.get("tool") == "claude"
         and e.get("date") == date],
        key=lambda x: x.get("ts", ""))


def _transcript_for_day(fp, day):
    """从原始 jsonl 抽取某本地日期的【问 + 答】文本,按时序返回 [(ts, who, text)]。"""
    msgs = []
    try:
        with open(fp, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                typ = d.get("type")
                if typ not in ("user", "assistant"):
                    continue
                lts = util.iso_utc_to_local(d.get("timestamp"))
                if not lts or lts[:10] != day:
                    continue
                txt = " ".join(_cl._iter_text((d.get("message") or {}).get("content"))).strip()
                if not txt:
                    continue
                if typ == "user" and not _cl._is_real(txt):
                    continue          # 命令/工具回传/系统提醒不算对话
                msgs.append((lts, typ, txt))
    except Exception as e:
        util.log(f"  [digest] 读 transcript 失败 {os.path.basename(fp)}: {e}")
    msgs.sort()
    return msgs


def gen_material(cfg, date):
    """聚合当天每个会话的问答节选,产出给 AI 的提示。AI 按 TSV 逐会话回写标题+摘要。"""
    ents = _day_session_entries(date)
    if not ents:
        return f"({date} 没有可摘要的 claude 会话;先 loom sync)"
    L = [f"# {date} 会话原文(供 AI 写会话摘要)", "",
         f"当天有 {len(ents)} 个会话。请**逐个**为每个 SESSION 输出一行 TSV(勿加表头):",
         "  <session_id> <TAB> <标题:一句话≤40字,准确说清这天这个会话在干嘛> "
         "<TAB> <摘要:2–4句,目标/做了什么/结论,便于日后检索>",
         "标题别用'继续/这个/修一下'这类空话;要能一眼看出主题。", ""]
    for e in ents:
        d = e.get("detail", {})
        L.append(f"## SESSION {e['id']}  项目={e.get('project','?')}  "
                 f"({d.get('user',0)}问/{d.get('asst',0)}答)")
        msgs = _transcript_for_day(e.get("ref", ""), date)
        budget = TRANSCRIPT_CAP
        for _ts, typ, txt in msgs:
            who = "我" if typ == "user" else "AI"
            seg = f"[{who}] {' '.join(txt.split())[:MSG_CAP]}"
            if budget - len(seg) < 0:
                L.append("…(超长,后续省略;完整见 transcript)")
                break
            L.append(seg)
            budget -= len(seg)
        L.append("")
    L += ["---",
          f"写好存回:loom session set {date} --file <摘要.tsv>(或管道 stdin)。",
          "每行三列(id / 标题 / 摘要),用真实 Tab 分隔;id 照抄上面 SESSION 后那串。"]
    return "\n".join(L)


# ---------------------------------------------------------------- 回写
def set_from_text(cfg, date, text):
    """解析 AI 回写的 TSV(id\\t标题\\t摘要),存入 sidecar。返回成功写入的 id 列表。

    只接受【当天真实存在】的会话 id,AI 编造的 id 一律丢弃(防幻觉污染)。"""
    valid = {e["id"] for e in _day_session_entries(date)}
    redact = cfg.get("redact", True)
    d = load()
    applied = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        eid = parts[0].strip()
        if eid not in valid:
            continue
        title = parts[1].strip()[:TITLE_CAP]
        abstract = (parts[2].strip() if len(parts) > 2 else "")[:ABSTRACT_CAP]
        if not title:
            continue
        if redact:                       # 摘要可能带敏感串,入库前打码(和其它路径一致)
            title, abstract = util.redact(title), util.redact(abstract)
        d[eid] = {"title": title, "abstract": abstract, "date": date}
        applied.append(eid)
    if applied:
        save(d)
    return applied
