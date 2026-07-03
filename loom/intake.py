# -*- coding: utf-8 -*-
"""临时文档快速入库:`loom doc add <路径>` —— 从任意位置(下载/别处)拉进 notes/。

零摩擦:自动补 frontmatter(title/date/tags/source/status)、跑密钥打码、放进
`notes/<类目>`(默认 `inbox/`,先收后归类)。文本类抽正文,二进制(pdf/docx)原样拷。
"""
import os
import re
import shutil
from datetime import datetime

from . import config, util

TEXT_EXT = (".md", ".txt", ".rst", ".org", ".markdown")
DOC_EXT = TEXT_EXT + (".pdf", ".docx", ".pptx", ".xlsx", ".numbers", ".pages", ".key")
_H1 = re.compile(r"^#\s+(.+)")


def _slug(name):
    return re.sub(r"\s+", "-", name.strip())


def _has_frontmatter(text):
    return text.lstrip().startswith("---")


def _title_of(text, fallback):
    for line in text.splitlines():
        m = _H1.match(line.strip())
        if m:
            return m.group(1).strip()
        if line.strip():
            break
    return fallback


def _uniq(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(f"{stem}-{n}{ext}"):
        n += 1
    return f"{stem}-{n}{ext}"


def _frontmatter(title, date, tags, source, status):
    tg = "[" + ", ".join(tags) + "]" if tags else "[]"
    return (f"---\ntitle: {title}\ndate: {date}\ntags: {tg}\n"
            f"source: {source}\nstatus: {status}\ntype: loom-note\n---\n\n")


def _one(cfg, src, to, tags, title, move, redact):
    src = os.path.abspath(util.expand(src))
    if not os.path.isfile(src):
        return None, f"跳过(非文件):{src}"
    ext = os.path.splitext(src)[1].lower()
    dest_dir = os.path.join(config.notes_dir(cfg), to or "inbox")
    os.makedirs(dest_dir, exist_ok=True)
    date = datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d")
    status = to or "inbox"

    if ext in TEXT_EXT:
        with open(src, encoding="utf-8", errors="replace") as f:
            body = f.read()
        if redact:
            body = util.redact(body)
        stem = os.path.splitext(os.path.basename(src))[0]
        dest = _uniq(os.path.join(dest_dir, _slug(stem) + ".md"))
        with open(dest, "w", encoding="utf-8") as f:
            if _has_frontmatter(body):
                f.write(body)                       # 已有 frontmatter,尊重原样
            else:
                f.write(_frontmatter(title or _title_of(body, stem), date,
                                     tags, src, status))
                f.write(body if body.endswith("\n") else body + "\n")
    elif ext in DOC_EXT:                             # 二进制:原样拷,不注 frontmatter
        dest = _uniq(os.path.join(dest_dir, _slug(os.path.basename(src))))
        shutil.copy2(src, dest)
    else:
        return None, f"跳过(非文档类型 {ext}):{src}"

    if move:
        try:
            os.remove(src)
        except OSError:
            pass
    verb = "移入" if move else "拷入"
    return dest, f"{verb} {os.path.relpath(dest, config.vault_dir(cfg))}"


def ingest(cfg, paths, to=None, tags=None, title=None, move=False):
    """把一个或多个文件/目录拉进 notes/。返回 [(dest, msg)]。"""
    redact = cfg.get("redact", True)
    tags = [t.strip() for t in (tags or "").split(",") if t.strip()]
    results = []
    for p in paths:
        p = util.expand(p)
        if os.path.isdir(p):                         # 目录:纳入其中的文档文件
            for dp, _, fns in os.walk(p):
                for fn in sorted(fns):
                    if fn.lower().endswith(DOC_EXT) and not fn.startswith("."):
                        results.append(_one(cfg, os.path.join(dp, fn), to, tags,
                                            None, move, redact))
        else:
            results.append(_one(cfg, p, to, tags, title, move, redact))
    return results
