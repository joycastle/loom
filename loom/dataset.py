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


def _xlsx_rows(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.iter(_XL_NS + "si"):
                shared.append("".join(t.text or "" for t in si.iter(_XL_NS + "t")))
        sheets = sorted(n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
        if not sheets:
            return [], False
        root = ET.fromstring(z.read(sheets[0]))
        rows, capped = [], False
        for i, row in enumerate(root.iter(_XL_NS + "row")):
            if i >= SCAN_CAP:
                capped = True
                break
            cells = []
            for c in row.iter(_XL_NS + "c"):
                v = c.find(_XL_NS + "v")
                if v is None or v.text is None:
                    cells.append("")
                elif c.get("t") == "s":
                    cells.append(shared[int(v.text)] if v.text.isdigit()
                                 and int(v.text) < len(shared) else "")
                else:
                    cells.append(v.text)
            cells = [x for x in cells]
            rows.append(cells)
    return rows, capped


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
    """从行(首行=表头)算每列类型 + 简单统计。"""
    if not rows:
        return [], []
    header = [h or f"col{i}" for i, h in enumerate(rows[0])]
    data = rows[1:]
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
    return cols, data[:SAMPLE]


_LANG = {".sql": "sql", ".py": "python", ".sh": "bash", ".r": "r", ".R": "r",
         ".ipynb": "json", ".js": "javascript", ".scala": "scala"}


def _card(name, src, ext, nrows, capped, cols, sample, size, date, tags,
          code_files, used_by, raw_rel, redact):
    tg = "[" + ", ".join(tags) + "]" if tags else "[]"
    L = ["---", f"title: {name}", "type: loom-datacard", f"source: {src}",
         f"rows: {'≥' if capped else ''}{nrows} · cols: {len(cols)} · size: {size}",
         f"date: {date}", f"tags: {tg}", f"raw: {raw_rel}"]
    if code_files:
        L.append("produced_by: [" + ", ".join(c["fname"] for c in code_files) + "]")
    if used_by:
        L.append(f"used_by: [[{used_by}]]")
    L += ["---", "",
          f"> 数据卡。原始 {ext[1:]} 在 `{raw_rel}`(本地留存、不上云);"
          + (f"产出/相关代码见 {', '.join('`' + c['fname'] + '`' for c in code_files)}。"
             if code_files else ""), "",
          f"## 列({len(cols)})", "", "| 列 | 类型 | 统计 |", "|---|---|---|"]
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


def add(cfg, datafile, to=None, code=None, used_by=None, tags=None):
    """纳入一个数据文件:写数据卡(上云)+ 拷原始到 _data/(gitignore)+ 存产出代码(sql/py/…)。"""
    redact = cfg.get("redact", True)
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
    cols, sample = _profile(rows)
    nrows = max(0, len(rows) - 1)
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
                 code_files, used_by, raw_rel, redact)
    card_path = os.path.join(topic_dir, stem + ".card.md")
    with open(card_path, "w", encoding="utf-8") as f:
        f.write(card)
    return card_path, (f"数据卡 {os.path.relpath(card_path, config.vault_dir(cfg))} "
                       f"({nrows} 行 × {len(cols)} 列;原始入 _data/"
                       + (f";+{len(code_files)} 代码" if code_files else "") + ")")
