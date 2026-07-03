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


def _parse_frontmatter(text):
    """极简 frontmatter 解析:返回 (fields dict, 正文起始 index)。无 fm 则 ({}, 0)。"""
    if not text.lstrip().startswith("---"):
        return {}, 0
    lines = text.splitlines(keepends=True)
    out, end = {}, None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
        m = re.match(r"([A-Za-z_]+):\s*(.*)", lines[i])
        if m:
            out[m.group(1)] = m.group(2).strip()
    if end is None:
        return {}, 0
    return out, sum(len(x) for x in lines[:end + 1])


def harvest_taxonomy(cfg):
    """收集 notes/ 现有类目(子目录)+ 标签词表(扫 frontmatter)。约束 AI 分进已有体系。"""
    nd = config.notes_dir(cfg)
    cats, tags = set(), set()
    if not os.path.isdir(nd):
        return [], []
    for dp, dns, fns in os.walk(nd):
        dns[:] = [d for d in dns if not d.startswith(".")]
        rel = os.path.relpath(dp, nd)
        if rel != "." and rel != "inbox":
            cats.add(rel)
        for fn in fns:
            if fn.lower().endswith(TEXT_EXT):
                fm, _ = _parse_frontmatter(open(os.path.join(dp, fn),
                                                encoding="utf-8", errors="replace").read())
                for t in re.findall(r"[^\[\],\s]+", fm.get("tags", "")):
                    tags.add(t)
    return sorted(cats), sorted(tags)


def triage_manifest(cfg, subdir="inbox", head=14):
    """给 AI 的清单:现有类目/标签 + 待分类文档的头部(已打码)。"""
    nd = config.notes_dir(cfg)
    src_dir = os.path.join(nd, subdir)
    cats, tags = harvest_taxonomy(cfg)
    out = [f"# loom doc triage — 待归类({subdir})\n",
           "## 现有类目(尽量复用)", ", ".join(cats) or "(无,可新建)", "",
           "## 现有标签词表(尽量复用)", ", ".join(tags) or "(无)", "",
           "## 待分类文档"]
    docs = []
    if os.path.isdir(src_dir):
        for fn in sorted(os.listdir(src_dir)):
            fp = os.path.join(src_dir, fn)
            if not os.path.isfile(fp) or not fn.lower().endswith(TEXT_EXT):
                continue
            docs.append(fn)
            txt = util.redact(open(fp, encoding="utf-8", errors="replace").read())
            fm, body_at = _parse_frontmatter(txt)
            body = txt[body_at:].strip().splitlines()[:head]
            rel = os.path.relpath(fp, nd)
            out += [f"\n### {rel}",
                    f"current-title: {fm.get('title', '(无)')}  current-tags: {fm.get('tags', '[]')}",
                    "```", *body, "```"]
    if not docs:
        out.append(f"\n(空:{src_dir} 下没有待分类文档;先 `loom doc add <路径>`)")
    out += ["\n---",
            "AI:为每篇给「目标类目 + 标签」,尽量复用上面的类目/标签词表;",
            "写成 TSV 每行 `相对路径<TAB>类目<TAB>标签,逗号分隔`,存文件后运行:",
            "  loom doc triage --apply <该文件>"]
    return "\n".join(out)


def _set_fm_fields(text, updates):
    """更新/插入 frontmatter 字段;无 fm 则新建。updates: {key: value}。"""
    fm, body_at = _parse_frontmatter(text)
    if body_at == 0:  # 无 frontmatter → 造一个
        lines = [f"{k}: {v}" for k, v in updates.items()]
        return "---\n" + "\n".join(lines) + "\n---\n\n" + text.lstrip()
    head = text[:body_at].splitlines()
    body = text[body_at:]
    keys_done = set()
    for i, ln in enumerate(head):
        m = re.match(r"([A-Za-z_]+):", ln)
        if m and m.group(1) in updates:
            head[i] = f"{m.group(1)}: {updates[m.group(1)]}"
            keys_done.add(m.group(1))
    ins = [f"{k}: {v}" for k, v in updates.items() if k not in keys_done]
    head = head[:-1] + ins + [head[-1]]  # 在收尾 --- 前插新字段
    return "\n".join(head) + "\n" + body


def apply_triage(cfg, mapping):
    """应用 AI 的映射:[(relpath, category, tags_list)] → 移到类目 + 更新 frontmatter。"""
    nd = config.notes_dir(cfg)
    results = []
    for rel, cat, tags in mapping:
        src = os.path.join(nd, rel)
        if not os.path.isfile(src):
            results.append((None, f"跳过(不存在):{rel}"))
            continue
        dest_dir = os.path.join(nd, cat)
        os.makedirs(dest_dir, exist_ok=True)
        dest = _uniq(os.path.join(dest_dir, os.path.basename(src)))
        txt = open(src, encoding="utf-8", errors="replace").read()
        txt = _set_fm_fields(txt, {"tags": "[" + ", ".join(tags) + "]", "status": cat})
        with open(dest, "w", encoding="utf-8") as f:
            f.write(txt)
        os.remove(src)
        results.append((dest, f"{rel} → {os.path.relpath(dest, nd)}  [{', '.join(tags)}]"))
    return results


def parse_mapping_tsv(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        rel, cat = parts[0].strip(), parts[1].strip()
        tags = [t.strip() for t in (parts[2] if len(parts) > 2 else "").split(",") if t.strip()]
        rows.append((rel, cat, tags))
    return rows


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
