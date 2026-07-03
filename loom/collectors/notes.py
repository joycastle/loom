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


def collect(cfg, since):
    src = cfg["sources"].get("notes", {})
    if not src.get("enabled"):
        return []
    nd = config.notes_dir(cfg)
    if not os.path.isdir(nd):
        return []
    entries = []
    for dp, dns, fns in os.walk(nd):
        dns[:] = [d for d in dns if d != "_archive" and not d.startswith(".")]
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
            d = fm.get("date", "").strip()
            if _DATE.match(d):
                date10, ts = d[:10], d[:10] + "T12:00:00"
            else:
                ts = util.ms_to_iso(os.path.getmtime(fp) * 1000) or ""
                date10 = ts[:10]
            parts = rel.split(os.sep)
            project = parts[0] if len(parts) > 1 else "notes"
            entries.append({
                "id": f"note:{rel}", "date": date10, "ts": ts,
                "project": project, "tool": "notes", "kind": "note",
                "summary": title, "ref": fp,
                "detail": {"path": rel, "tags": fm.get("tags", ""),
                           "content": text[body_at:]},
            })
    return entries
