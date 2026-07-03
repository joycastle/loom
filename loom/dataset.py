# -*- coding: utf-8 -*-
"""数据文件纳入记忆:`loom data add <csv|xlsx>` —— 蒸馏「数据卡」+ 绑定 SQL/文档。

分层:知识层(数据卡 .md:列/类型/统计/样例 + 链接)进 vault 上云、可检索;
资料层(原始 csv/xlsx)拷进同主题的 `_data/`(gitignore,本地留存不上云)。
把「数据 ↔ 产出它的代码(SQL/Python/…)↔ 用它的文档」钉成一个分析单元
(同一主题文件夹 + frontmatter 互链)。纯标准库:csv 模块 + xlsx 的 zip/xml。
"""
import csv
import os
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime

from . import config, util

SCAN_CAP = 50000     # 剖析/计数扫描上限(超大文件只取前 N 估算)
SAMPLE = 5
_XL_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NUM = re.compile(r"^-?\d+(\.\d+)?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2})?")


def _slug(name):
    return re.sub(r"\s+", "-", name.strip())


def _csv_rows(path):
    rows, capped = [], False
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for i, row in enumerate(csv.reader(f)):
            if i >= SCAN_CAP:
                capped = True
                break
            rows.append(row)
    return rows, capped


def _col_idx(ref):
    """单元格引用 'B3' → 列序号 1(处理稀疏单元格对齐)。"""
    m = re.match(r"[A-Z]+", ref or "")
    if not m:
        return 0
    idx = 0
    for ch in m.group(0):
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _sheet_rows(root, shared):
    rows = []
    for row in root.iter(_XL_NS + "row"):
        cells, maxc = {}, -1
        for c in row.iter(_XL_NS + "c"):
            ci = _col_idx(c.get("r"))
            t = c.get("t")
            if t == "inlineStr":                        # 内联字符串 <is><t>
                is_ = c.find(_XL_NS + "is")
                val = "".join(x.text or "" for x in is_.iter(_XL_NS + "t")) if is_ is not None else ""
            else:
                v = c.find(_XL_NS + "v")
                if v is None or v.text is None:
                    val = ""
                elif t == "s":                          # sharedStrings 索引
                    val = shared[int(v.text)] if v.text.isdigit() and int(v.text) < len(shared) else ""
                else:
                    val = v.text
            cells[ci] = val
            maxc = max(maxc, ci)
        rows.append([cells.get(i, "") for i in range(maxc + 1)])
        if len(rows) >= SCAN_CAP:
            break
    return rows


def _xlsx_rows(path):
    """解析 xlsx:处理 inlineStr/sharedStrings/数值 + 列位置;多 sheet 取数据最多的一张。"""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.iter(_XL_NS + "si"):
                shared.append("".join(t.text or "" for t in si.iter(_XL_NS + "t")))
        sheets = sorted(n for n in names
                        if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
        best, best_cells = [], -1
        for s in sheets:
            rows = _sheet_rows(ET.fromstring(z.read(s)), shared)
            ncells = sum(len(r) for r in rows)          # 选单元格最多的 sheet(真数据表)
            if ncells > best_cells:
                best, best_cells = rows, ncells
    return best, len(best) >= SCAN_CAP


def _coltype(vals):
    seen = [v for v in vals if v not in ("", None)]
    if not seen:
        return "empty"
    if all(_NUM.match(v) for v in seen):
        return "int" if all("." not in v for v in seen) else "float"
    if all(_DATE.match(v) for v in seen):
        return "date"
    return "str"


def _profile(rows):
    """算每列类型 + 简单统计。跳过前置标题/说明行(报表型表格首行常是单格标题)。"""
    if not rows:
        return [], [], 0
    start = 0                                    # 表头 = 首个「≥2 非空单元格」的行
    for i, r in enumerate(rows[:50]):
        if sum(1 for x in r if x not in ("", None)) >= 2:
            start = i
            break
    header = [h or f"col{i}" for i, h in enumerate(rows[start])]
    data = rows[start + 1:]
    ndata = len(data)
    ncol = len(header)
    cols = []
    for j in range(ncol):
        vals = [r[j] for r in data if j < len(r)]
        typ = _coltype(vals[:2000])
        nonempty = [v for v in vals if v not in ("", None)]
        if typ in ("int", "float") and nonempty:
            nums = [float(v) for v in nonempty if _NUM.match(v)]
            stat = f"{min(nums):g}–{max(nums):g}" if nums else ""
        else:
            distinct = len(set(nonempty))
            ex = nonempty[0] if nonempty else ""
            stat = f"{distinct} 个唯一" + (f",如「{ex[:20]}」" if ex else "")
        cols.append((header[j], typ, stat))
    return cols, data[:SAMPLE], ndata


_LANG = {".sql": "sql", ".py": "python", ".sh": "bash", ".r": "r", ".R": "r",
         ".ipynb": "json", ".js": "javascript", ".scala": "scala"}


def _card(name, src, ext, nrows, capped, cols, sample, size, date, tags,
          code_files, used_by, raw_rel, kind, inputs, redact):
    tg = "[" + ", ".join(tags) + "]" if tags else "[]"
    L = ["---", f"title: {name}", "type: loom-datacard", f"kind: {kind}",
         f"source: {src}",
         f"rows: {'≥' if capped else ''}{nrows} · cols: {len(cols)} · size: {size}",
         f"date: {date}", f"tags: {tg}", f"raw: {raw_rel}"]
    if inputs:                                        # 血缘:上游数据
        L.append("inputs: [" + ", ".join(f"[[{i}]]" for i in inputs) + "]")
    if code_files:
        L.append("produced_by: [" + ", ".join(c["fname"] for c in code_files) + "]")
    if used_by:
        L.append(f"used_by: [[{used_by}]]")
    L += ["---", ""]
    if kind == "derived":                             # 血缘一行:输入 →(代码)→ 本数据
        via = "、".join("`" + c["fname"] + "`" for c in code_files) or "(未记代码)"
        frm = "、".join(f"[[{i}]]" for i in inputs) or "(未记输入)"
        L += [f"> **派生数据**。血缘:{frm} —({via})→ 本数据。原始产物在 "
              f"`{raw_rel}`(本地不上云)。", ""]
    else:
        L += [f"> **原始数据**。在 `{raw_rel}`(本地留存、不上云);"
              + (f"拉取代码见 {', '.join('`' + c['fname'] + '`' for c in code_files)}。"
                 if code_files else ""), ""]
    L += [f"## 列({len(cols)})", "", "| 列 | 类型 | 统计 |", "|---|---|---|"]
    for c, t, s in cols:
        L.append(f"| {c} | {t} | {s} |")
    if sample:
        L += ["", f"## 前 {len(sample)} 行样例", "",
              "| " + " | ".join(c for c, _, _ in cols) + " |",
              "|" + "|".join("---" for _ in cols) + "|"]
        for r in sample:
            L.append("| " + " | ".join((r[i] if i < len(r) else "").replace("|", "\\|")
                                       for i in range(len(cols))) + " |")
    for c in code_files:                              # 产出/相关代码嵌入(可检索)
        L += ["", f"## {c['fname']}", "", f"```{c['lang']}", c["text"].strip(), "```"]
    text = "\n".join(L) + "\n"
    return util.redact(text) if redact else text


def add(cfg, datafile, to=None, code=None, used_by=None, tags=None, kind=None, frm=None):
    """纳入一个数据文件:数据卡(上云)+ 原始到 _data/(gitignore)+ 产出代码 + 血缘。

    kind: source(原始/拉取)| derived(本地加工);未指定则有 --from 视为 derived,否则 source。
    frm:  派生数据的上游输入(文件/名字),记为 inputs 血缘链。"""
    redact = cfg.get("redact", True)
    inputs = [_slug(os.path.splitext(os.path.basename(util.expand(x)))[0]) for x in (frm or [])]
    kind = kind or ("derived" if inputs else "source")
    tags = [t.strip() for t in (tags or "").split(",") if t.strip()]
    src = os.path.abspath(util.expand(datafile))
    if not os.path.isfile(src):
        return None, f"跳过(非文件):{src}"
    ext = os.path.splitext(src)[1].lower()
    if ext not in (".csv", ".tsv", ".xlsx"):
        return None, f"跳过(非数据文件 {ext};用 loom doc add):{src}"
    topic_dir = util.safe_join(config.notes_dir(cfg), to or "data")
    if topic_dir is None:
        return None, f"跳过(主题路径越界):{to}"
    data_dir = os.path.join(topic_dir, "_data")
    os.makedirs(data_dir, exist_ok=True)

    stem = _slug(os.path.splitext(os.path.basename(src))[0])
    try:
        rows, capped = (_xlsx_rows(src) if ext == ".xlsx" else _csv_rows(src))
    except Exception as e:
        return None, f"解析失败({ext}):{e}"
    cols, sample, nrows = _profile(rows)
    size = f"{os.path.getsize(src) / 1e6:.1f}MB" if os.path.getsize(src) >= 1e6 \
        else f"{os.path.getsize(src) // 1024}KB"
    date = datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d")

    # 原始文件拷进 _data/(本地、gitignore)
    raw_dest = os.path.join(data_dir, os.path.basename(src))
    shutil.copy2(src, raw_dest)
    raw_rel = os.path.relpath(raw_dest, topic_dir)

    # 产出/相关代码(sql/py/…):文件路径列表,存进主题目录并嵌入卡片
    code_files = []
    for c in (code or []):
        cp = util.expand(c)
        if not os.path.isfile(cp):
            continue
        cext = os.path.splitext(cp)[1].lower()
        text = open(cp, encoding="utf-8", errors="replace").read()
        if redact:
            text = util.redact(text)
        fname = _slug(os.path.basename(cp))
        with open(os.path.join(topic_dir, fname), "w", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        code_files.append({"fname": fname, "lang": _LANG.get(cext, "text"), "text": text})

    card = _card(stem, src, ext, nrows, capped, cols, sample, size, date, tags,
                 code_files, used_by, raw_rel, kind, inputs, redact)
    card_path = os.path.join(topic_dir, stem + ".card.md")
    with open(card_path, "w", encoding="utf-8") as f:
        f.write(card)
    return card_path, (f"数据卡[{kind}] {os.path.relpath(card_path, config.vault_dir(cfg))} "
                       f"({nrows} 行 × {len(cols)} 列;原始入 _data/"
                       + (f";←{len(inputs)} 输入" if inputs else "")
                       + (f";+{len(code_files)} 代码" if code_files else "") + ")")
