# -*- coding: utf-8 -*-
"""按天渲染 markdown 日记(Basic Memory / Obsidian 友好)。

自动区与手写区**物理分离**为两个文件,消灭「重渲染吃掉手写正文」的不可逆风险:
  {date}.md         自动日志,每次 sync 整体重写(可再生)
  {date}.notes.md   手写笔记,loom **永不覆盖**(只在缺失时建空模板 / 从旧哨兵迁移)
日志末尾用 Obsidian 内嵌 `![[{date}.notes]]` 把笔记显示在一起;两文件对 Basic Memory
也各自独立可检索。
"""
import os
from collections import defaultdict

from . import config

# 旧版:手写正文曾内联在 {date}.md 的此哨兵之下。保留用于一次性迁移。
LEGACY_MARK = "<!-- ✍️ 手写区(loom sync 不会覆盖下方内容)-->"


def _notes_stem(date):
    return f"{date}.notes"


def _notes_template(date):
    return (f"---\ndate: {date}\ntype: loom-notes\ntags: [loom, notes]\n---\n\n"
            f"# {date} 手写笔记\n\n"
            f"<!-- 这个文件 loom 永不覆盖,随手记在这里。 -->\n")


def _ensure_notes_file(jdir, date):
    """保证 {date}.notes.md 存在且**绝不覆盖**已有内容。

    首次建立时:若旧 {date}.md 的哨兵下有手写正文,则迁移过来;否则写空模板。
    返回内嵌用的文件名 stem(如 '2026-07-03.notes')。
    """
    stem = _notes_stem(date)
    notes_path = os.path.join(jdir, f"{stem}.md")
    if os.path.exists(notes_path):
        return stem  # 已存在 → 一个字都不动

    migrated = ""
    legacy_path = os.path.join(jdir, f"{date}.md")
    if os.path.exists(legacy_path):
        old = open(legacy_path, encoding="utf-8").read()
        i = old.find(LEGACY_MARK)
        if i != -1:
            below = old[i + len(LEGACY_MARK):].strip()
            if below:
                migrated = below

    with open(notes_path, "w", encoding="utf-8") as f:
        f.write(_notes_template(date))
        if migrated:
            f.write("\n" + migrated + "\n")
    return stem


def build(cfg, by_id):
    jdir = config.journal_dir(cfg)
    os.makedirs(jdir, exist_ok=True)
    by_date = defaultdict(list)
    for e in by_id.values():
        if e.get("kind") == "doc":      # 文档是参考,只进检索索引,不进按天日记
            continue
        by_date[e["date"]].append(e)
    written = 0
    for date, items in by_date.items():
        by_proj = defaultdict(list)
        for e in items:
            by_proj[e["project"]].append(e)
        lines = ["---", f"date: {date}", "type: loom", "tags: [loom]", "---",
                 "", f"# {date} 工作日志", ""]
        for proj in sorted(by_proj):
            evs = by_proj[proj]
            commits = [e for e in evs if e["tool"] == "git"]
            reqs = [e for e in evs if e["kind"] == "requirement"]
            notes = [e for e in evs if e["kind"] == "note"]
            sessions = [e for e in evs if e["tool"] != "git"
                        and e["kind"] not in ("requirement", "note")]
            lines.append(f"## [[{proj}]]")
            lines.append("")
            if commits:
                lines.append(f"### 提交 ({len(commits)})")
                for e in sorted(commits, key=lambda x: x["ts"]):
                    d = e.get("detail", {})
                    lines.append(f"- `{e['ref']}` {e['summary']}  "
                                 f"(+{d.get('ins',0)}/-{d.get('del',0)}, {d.get('files',0)} 文件)")
                    # 正文(「为什么这么改」):缩进为引用块挂在提交下
                    body = (d.get("body") or "").strip()
                    if body:
                        for bl in body.splitlines():
                            lines.append(f"  > {bl}" if bl.strip() else "  >")
                    # 文件明细:显示前 N 个,其余折叠计数(`git show <hash>` 看完整 diff)
                    fl = d.get("file_list") or []
                    for f in fl[:8]:
                        lines.append(f"    - `{f['path']}` (+{f.get('ins',0)}/-{f.get('del',0)})")
                    if len(fl) > 8:
                        lines.append(f"    - …及其余 {len(fl) - 8} 个文件")
                lines.append("")
            if reqs:
                lines.append(f"### 需求 ({len(reqs)})")
                for e in sorted(reqs, key=lambda x: x["ts"]):
                    lines.append(f"- {e['summary']}  \n  ↳ {e['ref']}")
                lines.append("")
            if notes:
                lines.append(f"### 飞书记事 ({len(notes)})")
                for e in sorted(notes, key=lambda x: x["ts"]):
                    lines.append(f"- {e['summary']}  \n  ↳ {e['ref']}")
                lines.append("")
            if sessions:
                lines.append(f"### AI 会话 ({len(sessions)})")
                for e in sorted(sessions, key=lambda x: x["ts"]):
                    d = e.get("detail", {})
                    span = ""
                    if d.get("start") and d.get("end"):
                        span = f"{d['start'][11:16]}–{d['end'][11:16]} · "
                    lines.append(f"- **{e['tool']}** {span}{e['summary']}  \n  ↳ `{e['ref']}`")
                    # 开场提问全文(比标题多的信息才渲染,避免和 summary 重复)
                    op = (d.get("opening") or "").strip()
                    op_norm = " ".join(op.split())
                    sum_norm = " ".join((e["summary"] or "").split())
                    if op_norm and not op_norm.startswith(sum_norm):
                        shown = op[:600]
                        for ol in shown.splitlines():
                            lines.append(f"  > {ol}" if ol.strip() else "  >")
                        if len(op) > len(shown):
                            lines.append("  > …")
                lines.append("")

        stem = _ensure_notes_file(jdir, date)
        lines += ["---", "",
                  f"> ✍️ **手写笔记**(loom 永不覆盖):[[{stem}]]", "",
                  f"![[{stem}]]", ""]

        path = os.path.join(jdir, f"{date}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        written += 1
    return written
