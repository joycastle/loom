# -*- coding: utf-8 -*-
"""归一化条目存储:entries.jsonl,按 id upsert。条目可再生。"""
import json
import os

from . import util


def load():
    out = {}
    if os.path.exists(util.DATA_PATH):
        for line in open(util.DATA_PATH, encoding="utf-8"):
            try:
                e = json.loads(line)
                out[e["id"]] = e
            except Exception:
                pass
    return out


def save(by_id):
    os.makedirs(os.path.dirname(util.DATA_PATH), exist_ok=True)
    rows = sorted(by_id.values(), key=lambda e: (e.get("ts", ""), e["id"]))
    with open(util.DATA_PATH, "w", encoding="utf-8") as f:
        for e in rows:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def upsert(by_id, entries):
    for e in entries:
        by_id[e["id"]] = e
    return by_id
