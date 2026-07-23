# -*- coding: utf-8 -*-
"""临时文档快速入库:`loom doc add <路径>` —— 从任意位置(下载/别处)拉进 notes/。

零摩擦:自动补 frontmatter(title/date/tags/source/status)、跑密钥打码、放进
`notes/<类目>`(默认 `inbox/`,先收后归类)。文本类抽正文;docx/pdf 提取文本成可检索
.md(并留原件保真);其余二进制原样拷。
"""
import json
import hashlib
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
CODE_EXT = (".sql", ".py", ".sh", ".r", ".js", ".ts", ".scala")  # 代码/脚本:原样存 + 打码 + 可检索
EXTRACTABLE_EXT = (".docx", ".pptx", ".pdf", ".ipynb")  # 提取文本→可检索 .md(打码)+ 留原件保真
BINARY_EXT = (".xlsx", ".numbers", ".pages", ".key", ".parquet")  # 原样拷,无法提取/打码
DOC_EXT = TEXT_EXT + TEXTDATA_EXT + CODE_EXT + EXTRACTABLE_EXT + BINARY_EXT
SKIP_DIRS = {"node_modules", ".git", "venv", ".venv", "__pycache__", "site-packages",
             "dist", "build", ".next", "target", "vendor", ".cache"}
MAX_TEXT_CHARS = 2_000_000   # 单文档纳入字符上限:超大文件截断标注,防内存/检索被拖垮
# 原始文件抽取上限:抽取(docx/pptx/pdf/ipynb)在把整份内容读进内存之前先按原文件
# 大小卡一道,防拖入超大/恶意文档把 sidecar 撑爆(OOM)。50MB 足够覆盖正常文档。
MAX_INGEST_BYTES = 50 * 1024 * 1024
# docx/pptx 是 zip:单个 XML 部件解压后的上限,防"解压炸弹"(小文件解压出巨大 XML)。
MAX_ZIP_PART_BYTES = 30 * 1024 * 1024
_H1 = re.compile(r"^#\s+(.+)")
_DOCX_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_PPTX_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _too_big(path):
    """原文件是否超过抽取上限(超限则跳过抽取,避免整份读进内存)。"""
    try:
        return os.path.getsize(path) > MAX_INGEST_BYTES
    except OSError:
        return False


def _safe_zip_read(z, name):
    """读取 zip 成员,但先按未压缩大小(ZipInfo.file_size,无需真解压即可得知)
    卡上限,防解压炸弹。超限抛异常,由调用方按"抽取失败"降级。"""
    if z.getinfo(name).file_size > MAX_ZIP_PART_BYTES:
        raise ValueError(f"zip part too large: {name}")
    return z.read(name)


def _cap_text(text):
    """超长正文截断并标注(避免把多 GB 日志/导出整体读进内存、撑爆检索索引)。"""
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return text[:MAX_TEXT_CHARS].rstrip() + f"\n\n… (超出 {MAX_TEXT_CHARS} 字符已截断)\n"


def _docx_paras(root):
    return ["".join(t.text for t in p.iter(_DOCX_NS + "t") if t.text)
            for p in root.iter(_DOCX_NS + "p")]


def _docx_text(path):
    """纯标准库提取 docx:正文段落 + 表格单元 + 页眉/页脚(独立部件,否则丢失)。失败返回 ""。"""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            paras = _docx_paras(ET.fromstring(_safe_zip_read(z, "word/document.xml")))
            for n in sorted(names):        # 页眉/页脚在 word/header*.xml、footer*.xml,不在正文里
                if re.match(r"word/(header|footer)\d*\.xml$", n):
                    try:
                        paras += _docx_paras(ET.fromstring(_safe_zip_read(z, n)))
                    except Exception:
                        pass
        return "\n".join(x for x in paras if x).strip()
    except Exception:
        return ""


def _pptx_text(path):
    """纯标准库提取 pptx 正文(zip + xml,按幻灯片顺序拼接)。失败返回 ""。"""
    try:
        with zipfile.ZipFile(path) as z:
            names = sorted(
                (n for n in z.namelist()
                 if n.startswith("ppt/slides/slide") and n.endswith(".xml")),
                key=lambda n: int(re.sub(r"\D", "", n.rsplit("/", 1)[-1]) or "0"))
            slides = []
            for name in names:
                root = ET.fromstring(_safe_zip_read(z, name))
                texts = [t.text for t in root.iter(_PPTX_NS + "t") if t.text]
                if texts:
                    slides.append(" ".join(texts).strip())
        return "\n\n".join(slides).strip()
    except Exception:
        return ""


def _pdftotext_exe():
    """定位 pdftotext:先查 PATH,再兜底常见安装位置。GUI/打包应用继承的 PATH
    往往只有 /usr/bin:/bin,不含 Homebrew,导致 shutil.which 找不到 → PDF 无法提取。"""
    exe = shutil.which("pdftotext")
    if exe:
        return exe
    for cand in ("/opt/homebrew/bin/pdftotext", "/usr/local/bin/pdftotext",
                 "/usr/bin/pdftotext", "/opt/local/bin/pdftotext"):
        if os.path.exists(cand):
            return cand
    return ""


def _pdf_text(path):
    """PDF 文本抽取,按可靠性排序:
    1) pypdf —— 纯 Python,随 App(pyinstaller)打包分发,**不依赖用户本机装任何东西**;
    2) pdftotext(poppler)—— 若本机恰好有,作为兜底(排版更好);
    3) 都没有 → ""(优雅降级)。
    这样打包后的桌面端在任何机器上都能解析文本型 PDF,不再靠本地环境。"""
    try:
        import pypdf  # 打包进 sidecar;base loom(纯 stdlib)没装则走下面的兜底
        reader = pypdf.PdfReader(path)
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(parts).strip()
        if text:
            return text
    except Exception:
        pass
    exe = _pdftotext_exe()
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "-layout", "-q", path, "-"],
                             capture_output=True, timeout=120)
        return out.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _nb_outputs(outputs, max_lines=30):
    """从 notebook 单元输出提取文本结果:流/执行结果的 text/plain(截断);图丢弃标注。"""
    chunks = []
    for o in outputs or []:
        if not isinstance(o, dict):
            continue
        t = o.get("output_type")
        txt = ""
        if t == "stream":
            txt = o.get("text", "")
        elif t in ("execute_result", "display_data"):
            data = o.get("data", {})
            if "text/plain" in data:
                txt = data["text/plain"]
            elif any(k.startswith("image/") for k in data):
                txt = "[图表]"
        elif t == "error":
            txt = "\n".join(o.get("traceback", [])) or o.get("evalue", "")
        if isinstance(txt, list):
            txt = "".join(txt)
        txt = txt.strip()
        if txt and txt != "[图表]":
            lines = txt.splitlines()
            if len(lines) > max_lines:
                txt = "\n".join(lines[:max_lines]) + f"\n… (+{len(lines) - max_lines} 行)"
            chunks.append("> 结果:\n```\n" + txt + "\n```")
        elif txt:
            chunks.append("> 结果:[图表]")
    return "\n".join(chunks)


def _ipynb_text(path):
    """把 .ipynb 渲染成 narrative markdown:md 单元原样 + 代码块 + 截断的结果块。"""
    try:
        nb = json.loads(_read(path))
    except Exception:
        return ""
    if not isinstance(nb, dict):        # 合法 JSON 但非 notebook 结构(list/null/…)→ 不崩
        return ""
    md = nb.get("metadata")
    li = md.get("language_info") if isinstance(md, dict) else None
    lang = li.get("name", "python") if isinstance(li, dict) else "python"
    out = []
    for cell in nb.get("cells", []) or []:
        if not isinstance(cell, dict):
            continue
        src = cell.get("source", "")
        if isinstance(src, list):
            src = "".join(src)
        src = src.strip()
        if cell.get("cell_type") == "markdown":
            if src:
                out.append(src)
        elif cell.get("cell_type") == "code":
            if src:
                out.append(f"```{lang}\n{src}\n```")
            res = _nb_outputs(cell.get("outputs", []))
            if res:
                out.append(res)
    return "\n\n".join(out).strip()


def _extract_text(path, ext):
    if _too_big(path):   # 超大原文件不抽取,防 OOM;原件仍会被保真拷贝
        return ""
    if ext == ".docx":
        return _docx_text(path)
    if ext == ".pptx":
        return _pptx_text(path)
    if ext == ".pdf":
        return _pdf_text(path)
    if ext == ".ipynb":
        return _ipynb_text(path)
    return ""


def _read(path):
    # 有界读:任何单文件最多读 MAX_INGEST_BYTES,杜绝无界 read() 被超大/恶意文件
    # 拖垮内存(正文另有 _cap_text 截到 MAX_TEXT_CHARS)。
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read(MAX_INGEST_BYTES)


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


def note_update(cfg, keyword, text):
    """搜索匹配 keyword 的 note 文件,把新文本追加到末尾(保留 frontmatter)。

    返回 (dest_path, message)。找到多条时取最近修改的那个。
    """
    notes_dir = config.notes_dir(cfg)
    kw = keyword.lower()
    matches = []
    for root, dirs, files in os.walk(notes_dir):
        dirs[:] = [d for d in dirs if d not in {"_attic"}]
        for fn in files:
            if fn.endswith(".md") and kw in fn.lower():
                matches.append(os.path.join(root, fn))
    if not matches:
        # 也搜文件内容的 title 行
        for root, dirs, files in os.walk(notes_dir):
            dirs[:] = [d for d in dirs if d not in {"_attic"}]
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                fp = os.path.join(root, fn)
                try:
                    with open(fp, encoding="utf-8", errors="replace") as f:
                        head = f.read(512)
                    if kw in head.lower():
                        matches.append(fp)
                except OSError:
                    pass
    if not matches:
        return None, f"未找到包含 {keyword!r} 的 note"
    # 取最近修改的
    target = max(matches, key=os.path.getmtime)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    append_text = f"\n\n---\n*更新 {now}*\n\n{text.strip()}\n"
    if cfg.get("redact", True):
        append_text = util.redact(append_text)
    with open(target, "a", encoding="utf-8") as f:
        f.write(append_text)
    rel = os.path.relpath(target, config.vault_dir(cfg))
    if len(matches) > 1:
        return target, f"更新 {rel}(共 {len(matches)} 个匹配,取最近修改)"
    return target, f"更新 {rel}"


def note_update_exact(cfg, relative_path, text, expected_sha256=""):
    """Append to one already-reviewed note, rejecting retargeting races."""
    target = util.safe_join(config.notes_dir(cfg), str(relative_path or ""))
    if target is None or not os.path.isfile(target) or not target.endswith(".md"):
        return None, "已确认的 note 目标不再可用"
    try:
        before = open(target, "rb").read()
    except OSError as exc:
        return None, f"读取 note 失败:{exc}"
    if expected_sha256 and hashlib.sha256(before).hexdigest() != expected_sha256:
        return None, "note 在确认前已发生变化，请重新生成提案"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    append_text = f"\n\n---\n*更新 {now}*\n\n{str(text or '').strip()}\n"
    if cfg.get("redact", True):
        append_text = util.redact(append_text)
    try:
        with open(target, "a", encoding="utf-8") as stream:
            stream.write(append_text)
    except OSError as exc:
        return None, f"更新 note 失败:{exc}"
    return target, f"更新 {os.path.relpath(target, config.vault_dir(cfg))}"


def note(cfg, text, to=None, tags=None, title=None):
    """随手信息:把一段文本写成 notes/<类目>(默认 inbox)下一条 note(打码 + frontmatter)。

    通用的「零碎信息」入口——不只飞书,任何来源(随手记/链接/结论/别处喂来)都走这条,
    统一成 note:进检索、进日记、可被主题层打标。外部来源写个薄脚本循环调它即可。
    """
    text = (text or "").strip()
    if not text:
        return None, "空内容"
    dest_dir = util.safe_join(config.notes_dir(cfg), to or "inbox")   # --to 越界防护
    if dest_dir is None:
        return None, f"跳过(类目越界):{to}"
    os.makedirs(dest_dir, exist_ok=True)
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "note")
    ttl = (title or " ".join(first.split()))[:40]
    fname = re.sub(r"[/\\:]", "-", _slug(ttl)) or "note"
    date = datetime.now().strftime("%Y-%m-%d")
    body = util.redact(text) if cfg.get("redact", True) else text
    dest = _uniq(os.path.join(dest_dir, fname + ".md"))
    with open(dest, "w", encoding="utf-8") as f:
        f.write(_frontmatter(ttl, date, tags or [], "loom note", to or "inbox"))
        f.write(body if body.endswith("\n") else body + "\n")
    return dest, f"记入 {os.path.relpath(dest, config.vault_dir(cfg))}"


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
            body = _cap_text(f.read(MAX_TEXT_CHARS + 1))
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
    elif ext in TEXTDATA_EXT or ext in CODE_EXT:     # 数据/代码:保留原扩展名,仍打码
        dest = _uniq(os.path.join(dest_dir, _slug(os.path.basename(src))))
        with open(src, encoding="utf-8", errors="replace") as f:
            data = _cap_text(f.read(MAX_TEXT_CHARS + 1))
        with open(dest, "w", encoding="utf-8") as f:
            f.write(util.redact(data) if redact else data)
    elif ext in EXTRACTABLE_EXT:                      # docx/pdf:提取文本→可检索 .md + 留原件
        stem = os.path.splitext(os.path.basename(src))[0]
        raw = _uniq(os.path.join(dest_dir, _slug(os.path.basename(src))))
        shutil.copy2(src, raw)                        # 原件保真
        text = _cap_text(_extract_text(src, ext))
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
            dest = raw                                # 提取失败 → 只留原件
            # pypdf 已随 App 打包,提取不到多半是扫描/图片型 PDF(无文本层),需 OCR,
            # 而非缺 pdftotext;文案据此区分,避免误导用户去装 poppler。
            if ext == ".pdf":
                note = "(未能提取文本,仅原件;可能是扫描/图片型 PDF,需 OCR)"
            else:
                note = "(未能提取文本,仅原件)"
    elif ext in BINARY_EXT:                          # 其余二进制:无法提取/打码 → 进本地 _data/,不上云
        ddir = os.path.join(dest_dir, "_data")
        os.makedirs(ddir, exist_ok=True)
        dest = _uniq(os.path.join(ddir, _slug(os.path.basename(src))))
        shutil.copy2(src, dest)
        note = "(二进制:存本地 _data/,不上云)"
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


def deprecate(cfg, relpath, superseded_by=None, mark=False):
    """把已知过时/判错的 notes 内容降级。

    默认:移进 `notes/_attic/`(采集器跳过 → 移出检索/Basic Memory,本地+git 历史仍在,可溯源)。
    --mark:留原处只打 `status: deprecated`(+superseded_by),检索里带 ⚠ 标记(用于轻微过时)。
    """
    nd = config.notes_dir(cfg)
    src = util.safe_join(nd, relpath)
    if src is None or not os.path.isfile(src):
        return None, f"跳过(不存在/路径越界):{relpath}"
    updates = {"status": "deprecated", "deprecated": "true"}
    if superseded_by:
        updates["superseded_by"] = f"[[{superseded_by}]]"
    if src.endswith(".md"):                       # 只有 .md 能写 frontmatter 墓碑
        # 必须先读后写:open(...,"w") 会立刻把文件截断为空,若在其中再 _read(src)
        # 读到的就是空内容,会把正文和原 frontmatter 一起抹掉(数据丢失)。
        tombstone = _set_fm_fields(_read(src), updates)
        with open(src, "w", encoding="utf-8") as f:
            f.write(tombstone)
    if mark:
        return src, f"标记 deprecated(留原处,检索标 ⚠):{relpath}"
    dest = util.safe_join(nd, "_attic", relpath)  # 保留子路径,溯源清晰
    if dest is None:
        return None, f"跳过(路径越界):{relpath}"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    dest = _uniq(dest)
    shutil.move(src, dest)
    return dest, f"移入 _attic(移出检索,本地/历史仍在):{relpath} → {os.path.relpath(dest, nd)}"


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
    # 目录递归收文档 + 代码(md/txt/docx/pdf/sql/py…),但**不扫数据文件**(csv/json/xlsx),
    # 免得把一个分析项目里几十个数据 CSV 一起拖进来;数据文件请显式点名或用 loom data add。
    dir_ext = TEXT_EXT + EXTRACTABLE_EXT + CODE_EXT
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
