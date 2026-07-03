# -*- coding: utf-8 -*-
"""按天渲染 markdown 日记(Basic Memory / Obsidian 友好),保留手写区。"""
import os
from collections import defaultdict

from . import config

NOTES_MARK = "<!-- ✍️ 手写区(loom sync 不会覆盖下方内容)-->"


def _preserve_notes(path):
    if os.path.exists(path):
        txt = open(path, encoding="utf-8").read()
        idx = txt.find(NOTES_MARK)
        if idx != -1:
            return txt[idx:]
    return NOTES_MARK + "\n\n"


def build(cfg, by_id):
    jdir = config.journal_dir(cfg)
    os.makedirs(jdir, exist_ok=True)
    by_date = defaultdict(list)
    for e in by_id.values():
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
            sessions = [e for e in evs if e["tool"] != "git" and e["kind"] != "requirement"]
            lines.append(f"## [[{proj}]]")
            lines.append("")
            if commits:
                lines.append(f"### 提交 ({len(commits)})")
                for e in sorted(commits, key=lambda x: x["ts"]):
                    d = e.get("detail", {})
                    lines.append(f"- `{e['ref']}` {e['summary']}  "
                                 f"(+{d.get('ins',0)}/-{d.get('del',0)}, {d.get('files',0)} 文件)")
                lines.append("")
            if reqs:
                lines.append(f"### 需求 ({len(reqs)})")
                for e in sorted(reqs, key=lambda x: x["ts"]):
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
                lines.append("")
        path = os.path.join(jdir, f"{date}.md")
        lines.append(_preserve_notes(path).rstrip("\n") + "\n")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        written += 1
    return written
