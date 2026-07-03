# -*- coding: utf-8 -*-
"""归一化条目存储:entries.jsonl,按 id upsert。条目可再生。"""
import json
import os

from . import util


def load():
    out = {}
    dropped = 0
    if os.path.exists(util.DATA_PATH):
        for line in open(util.DATA_PATH, encoding="utf-8"):
            if not line.strip():
                continue
            try:
                e = json.loads(line)
                out[e["id"]] = e
            except Exception:
                dropped += 1   # 别静默:损坏行要让人看见(配合原子写,基本不该出现)
    if dropped:
        util.log(f"  [store] 跳过 {dropped} 条损坏记录(entries.jsonl)")
    return out


def save(by_id):
    """原子落盘:先写进程独占临时文件,再 os.replace 换上去。

    真相文件绝不能半截写:断电/kill/磁盘满/并发 sync 都不该把 entries.jsonl 截断
    (派生索引 rebuild 早就这么干了,真相文件更该如此)。"""
    os.makedirs(os.path.dirname(util.DATA_PATH), exist_ok=True)
    rows = sorted(by_id.values(), key=lambda e: (e.get("ts", ""), e["id"]))
    tmp = f"{util.DATA_PATH}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        for e in rows:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, util.DATA_PATH)


def upsert(by_id, entries):
    for e in entries:
        by_id[e["id"]] = e
    return by_id
