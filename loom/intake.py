# -*- coding: utf-8 -*-
"""临时文档快速入库:`loom doc add <路径>` —— 从任意位置(下载/别处)拉进 notes/。

零摩擦:自动补 frontmatter(title/date/tags/source/status)、跑密钥打码、放进
`notes/<类目>`(默认 `inbox/`,先收后归类)。文本类抽正文;docx/pdf 提取文本成可检索
.md(并留原件保真);其余二进制原样拷。
"""
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime

from . import config, util

TEXT_EXT = (".md", ".txt", ".rst", ".org", ".markdown")   # 补 frontmatter + 打码 → .md
TEXTDATA_EXT = (".json", ".yaml", ".yml", ".csv", ".tsv", ".toml")  # 原样存但打码(仍是文本)
EXTRACTABLE_EXT = (".docx", ".pdf")   # 提取文本→可检索 .md(打码)+ 留原件保真
BINARY_EXT = (".pptx", ".xlsx", ".numbers", ".pages", ".key", ".parquet")  # 原样拷,无法提取/打码
DOC_EXT = TEXT_EXT + TEXTDATA_EXT + EXTRACTABLE_EXT + BINARY_EXT
SKIP_DIRS = {"node_modules", ".git", "venv", ".venv", "__pycache__", "site-packages",
             "dist", "build", ".next", "target", "vendor", ".cache"}
_H1 = re.compile(r"^#\s+(.+)")
_DOCX_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_text(path):
    """纯标准库提取 docx 正文(zip + xml,按段落)。失败返回 ""。"""
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("word/document.xml"))
        paras = ["".join(t.text for t in p.iter(_DOCX_NS + "t") if t.text)
                 for p in root.iter(_DOCX_NS + "p")]
        return "\n".join(x for x in paras).strip()
    except Exception:
        return ""


def _pdf_text(path):
    """PDF 文本:有 pdftotext(poppler)则用,否则返回 ""(优雅降级,不引入依赖)。"""
    exe = shutil.which("pdftotext")
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "-layout", "-q", path, "-"],
                             capture_output=True, timeout=120)
        return out.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _extract_text(path, ext):
    return _docx_text(path) if ext == ".docx" else _pdf_text(path) if ext == ".pdf" else ""


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


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
    dest_dir = util.safe_join(config.notes_dir(cfg), to or "inbox")   # --to 越界防护
    if dest_dir is None:
        return None, f"跳过(类目路径越界):{to}"
    os.makedirs(dest_dir, exist_ok=True)
    date = datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d")
    status = to or "inbox"
    note = ""

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
    elif ext in TEXTDATA_EXT:                        # 数据文件:保留原扩展名,仍打码(值级)
        dest = _uniq(os.path.join(dest_dir, _slug(os.path.basename(src))))
        with open(src, encoding="utf-8", errors="replace") as f:
            data = f.read()
        with open(dest, "w", encoding="utf-8") as f:
            f.write(util.redact(data) if redact else data)
    elif ext in EXTRACTABLE_EXT:                      # docx/pdf:提取文本→可检索 .md + 留原件
        stem = os.path.splitext(os.path.basename(src))[0]
        raw = _uniq(os.path.join(dest_dir, _slug(os.path.basename(src))))
        shutil.copy2(src, raw)                        # 原件保真
        text = _extract_text(src, ext)
        if text:
            if redact:
                text = util.redact(text)
            dest = _uniq(os.path.join(dest_dir, _slug(stem) + ".md"))
            with open(dest, "w", encoding="utf-8") as f:
                f.write(_frontmatter(title or stem, date, tags, src, status))
                f.write(f"> 从 {ext[1:]} 提取的文本;原件同目录 `{os.path.basename(raw)}`\n\n")
                f.write(text + ("" if text.endswith("\n") else "\n"))
            note = f"(提取文本 + 原件 {os.path.basename(raw)})"
        else:
            dest = raw                                # 提取失败(如无 pdftotext)→ 只留原件
            note = "(未能提取文本,仅原件;pdf 需 pdftotext)"
    elif ext in BINARY_EXT:                          # 其余二进制:原样拷,无法提取/打码
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
    return dest, f"{verb} {os.path.relpath(dest, config.vault_dir(cfg))} {note}".rstrip()


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
        m = re.match(r"([A-Za-z0-9_-]+):\s*(.*)", lines[i])
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
        dns[:] = [d for d in dns if not d.startswith((".", "_"))]  # 跳过 _archive 等
        rel = os.path.relpath(dp, nd)
        if rel not in (".", "inbox") and not rel.startswith("_"):
            cats.add(rel)
        for fn in fns:
            if fn.lower().endswith(TEXT_EXT):
                fm, _ = _parse_frontmatter(_read(os.path.join(dp, fn)))
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
            txt = util.redact(_read(fp))
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
    if body_at == 0:
        if text.lstrip().startswith("---"):
            return text          # 疑似残缺 frontmatter(无收尾 ---)→ 别再包一层污染
        lines = [f"{k}: {v}" for k, v in updates.items()]   # 无 fm → 新建
        return "---\n" + "\n".join(lines) + "\n---\n\n" + text.lstrip()
    head = text[:body_at].splitlines()
    body = text[body_at:]
    keys_done = set()
    for i, ln in enumerate(head):
        m = re.match(r"([A-Za-z0-9_-]+):", ln)
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
        src = util.safe_join(nd, rel)          # 拒绝 .. / 绝对路径穿越(否则会删/写 vault 外)
        dest_dir = util.safe_join(nd, cat)
        if src is None or dest_dir is None:
            results.append((None, f"跳过(路径越界):{rel} → {cat}"))
            continue
        if not os.path.isfile(src):
            results.append((None, f"跳过(不存在):{rel}"))
            continue
        os.makedirs(dest_dir, exist_ok=True)
        dest = _uniq(os.path.join(dest_dir, os.path.basename(src)))
        txt = _set_fm_fields(_read(src), {"tags": "[" + ", ".join(tags) + "]", "status": cat})
        with open(dest, "w", encoding="utf-8") as f:
            f.write(txt)
        os.remove(src)
        results.append((dest, f"{rel} → {os.path.relpath(dest, nd)}  [{', '.join(tags)}]"))
    return results


def parse_mapping_tsv(path):
    rows = []
    for line in _read(path).splitlines():
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
    # 目录递归**只收文档类**(md/txt/docx/pdf),不扫数据文件(csv/json/xlsx…),
    # 免得把一个分析项目里几十个数据 CSV 一起拖进来;数据文件请显式点名单个文件。
    dir_ext = TEXT_EXT + EXTRACTABLE_EXT
    for p in paths:
        p = util.expand(p)
        if os.path.isdir(p):                         # 目录:只纳入文档类文件
            for dp, dns, fns in os.walk(p):
                dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
                for fn in sorted(fns):
                    if fn.lower().endswith(dir_ext) and not fn.startswith("."):
                        results.append(_one(cfg, os.path.join(dp, fn), to, tags,
                                            None, move, redact))
        else:
            results.append(_one(cfg, p, to, tags, title, move, redact))
    return results
