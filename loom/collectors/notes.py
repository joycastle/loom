# -*- coding: utf-8 -*-
"""notes 采集器:把 vault/notes/ 下手动加/收编的文档纳入检索,补齐 loom doc add 的闭环。

缺口:`loom doc add` 只把文件写进 notes/,没进 entries.jsonl → `loom search` 搜不到
(只有 Basic Memory 能搜)。本采集器扫 notes/ → 产出 kind=note → 进 FTS。
- 跳过 `_archive`(那是 docs 源的全文镜像,避免重复索引)。
- 不进日记(参考,非当天活动);不再归档(它们本就是 vault 里的原件)。
- project 取类目(相对路径首段,如 attribution / inbox),便于 `loom search --project`。
"""
import os
import re

from .. import config, util
from ..intake import _parse_frontmatter, CODE_EXT

CONTENT_CAP = 200_000
INDEX_EXT = (".md",) + CODE_EXT     # 索引 markdown + 代码/脚本(sql/py…),让 pull recipe 可检索
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# 从文件名/路径里抠日期(代码文件无 frontmatter、入库 mtime 又都落在导入当天,靠名字定日更准)
_NAME_DATE = re.compile(r"(20\d{2})[-_]?(0[1-9]|1[0-2])[-_]?(0[1-9]|[12]\d|3[01])")
_NAME_YM = re.compile(r"(20\d{2})(0[1-9]|1[0-2])(?!\d)")   # 只到月的(如 202605)→ 当月 1 号


def _date_from_name(s):
    m = _NAME_DATE.search(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _NAME_YM.search(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-01"
    return None


def collect(cfg, since):
    src = cfg["sources"].get("notes", {})
    if not src.get("enabled"):
        return []
    nd = config.notes_dir(cfg)
    if not os.path.isdir(nd):
        return []
    entries = []
    for dp, dns, fns in os.walk(nd):
        # _archive:docs 源全文镜像;_attic:已废弃/判错内容(loom deprecate 移入)——都不进检索
        dns[:] = [d for d in dns if d not in ("_archive", "_attic") and not d.startswith(".")]
        for fn in fns:
            if not fn.lower().endswith(INDEX_EXT):
                continue
            fp = os.path.join(dp, fn)
            rel = os.path.relpath(fp, nd)
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    text = f.read()[:CONTENT_CAP]
            except Exception:
                continue
            fm, body_at = _parse_frontmatter(text)
            title = fm.get("title") or os.path.splitext(fn)[0]
            if fm.get("status") == "deprecated" or fm.get("deprecated", "").lower() == "true":
                title = "⚠[废弃] " + title      # 就地标记的废弃项:检索里显式标出,避免误信
            d = fm.get("date", "").strip()
            name_d = _date_from_name(rel)             # 文件名/路径里的日期
            # dated=有真实日期(数据卡 frontmatter / 名字带日期)→ 可进当天日记;
            # 否则只有入库 mtime,不可靠 → 仅进检索,不塞进任意一天日记(避免虚胖)。
            if _DATE.match(d):                        # ① frontmatter 日期(数据卡有,最准)
                date10, ts, dated = d[:10], d[:10] + "T12:00:00", True
            elif name_d:                              # ② 文件名里的日期(代码文件常带)
                date10, ts, dated = name_d, name_d + "T12:00:00", True
            else:                                     # ③ 兜底:文件 mtime(不进日记)
                ts = util.ms_to_iso(os.path.getmtime(fp) * 1000) or ""
                date10, dated = ts[:10], False
            parts = rel.split(os.sep)
            project = parts[0] if len(parts) > 1 else "notes"
            entries.append({
                "id": f"note:{rel}", "date": date10, "ts": ts,
                "project": project, "tool": "notes", "kind": "note",
                "summary": title, "ref": fp,
                "detail": {"path": rel, "tags": fm.get("tags", ""),
                           "dated": dated, "content": text[body_at:]},
            })
    return entries
