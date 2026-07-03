# -*- coding: utf-8 -*-
"""loom CLI:采集/渲染/检索 + 配置管理 + init 引导。"""
import argparse
import os
import subprocess
import sys
from datetime import datetime

from . import config, dataset, intake, render, search, store, util
from . import collectors


# ---------------------------------------------------------------- 采集/渲染
def _since(cfg, arg):
    return arg or util.since_date(cfg.get("default_since_days", 100))


def do_collect(cfg, sources, since):
    by_id = store.load()
    redact = cfg.get("redact", True)
    total = 0
    for s in sources:
        got = collectors.REGISTRY[s](cfg, since)
        if got:
            if redact:
                got = [util.redact_entry(e) for e in got]  # 入库前抹密钥
            store.upsert(by_id, got)
            print(f"  [{s}] 采集 {len(got)} 条")
        total += len(got)
    store.save(by_id)
    search.rebuild()  # 派生检索索引随采集同步重建
    print(f"采集完成:本轮 {total} 条,库内共 {len(by_id)} 条(since {since})")
    return by_id


def do_build(cfg):
    n = render.build(cfg, store.load())
    print(f"渲染完成:{n} 个日记 → {config.journal_dir(cfg)}")


def vault_git(cfg, push):
    vd = config.vault_dir(cfg)
    os.makedirs(vd, exist_ok=True)
    if not os.path.isdir(os.path.join(vd, ".git")):
        subprocess.run(["git", "-C", vd, "init", "-q"])
    subprocess.run(["git", "-C", vd, "add", "-A"])
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    r = subprocess.run(["git", "-C", vd, "commit", "-q", "-m", f"loom sync {stamp}"])
    print(f"已提交 vault ({stamp})" if r.returncode == 0 else "无变更,跳过提交")
    if push:
        remote = subprocess.run(["git", "-C", vd, "remote"],
                                capture_output=True, text=True).stdout.strip()
        if remote:
            subprocess.run(["git", "-C", vd, "push", "-q"])
            print("已 push 到云端")
        else:
            print("未配置 remote,跳过 push(loom 或 gh 里配 vault.remote)")


# ---------------------------------------------------------------- 命令
def cmd_sync(cfg, a):
    srcs = [a.source] if a.source and a.source != "all" else collectors.names()
    by_id = do_collect(cfg, srcs, _since(cfg, a.since))
    n = render.build(cfg, by_id)
    print(f"渲染完成:{n} 个日记")
    vault_git(cfg, a.push)


def cmd_collect(cfg, a):
    srcs = [a.source] if a.source and a.source != "all" else collectors.names()
    do_collect(cfg, srcs, _since(cfg, a.since))


def cmd_build(cfg, a):
    do_build(cfg)


def cmd_today(cfg, a):
    today = datetime.now().strftime("%Y-%m-%d")
    fp = os.path.join(config.journal_dir(cfg), f"{today}.md")
    print(open(fp, encoding="utf-8").read() if os.path.exists(fp)
          else f"{today} 暂无记录(先跑 loom sync)")


def cmd_search(cfg, a):
    hits = search.query(a.term, limit=a.limit, project=a.project,
                        tool=a.tool, since=a.since, until=a.until)
    for e in hits:
        print(f"{e['date']} [{e['project']}/{e['tool']}] {e['summary']}  ({e['ref']})")
        snip = e.get("snip", "")
        if snip and snip not in (e.get("summary") or ""):   # 命中片段(与标题重复则不赘)
            print(f"    ↳ {snip}")
    print(f"\n共 {len(hits)} 条命中" + ("(达上限,--limit 调大)" if len(hits) == a.limit else ""))


def cmd_repo(cfg, a):
    if a.action == "ls":
        for r in cfg["repos"]:
            print(r)
    elif a.action == "add":
        print("已加:", config.add_repo(cfg, a.value)); config.save(cfg)
    elif a.action == "rm":
        config.rm_repo(cfg, a.value); config.save(cfg); print("已删")
    elif a.action == "scan":
        found = config.scan_repos(a.value or "~/Documents")
        added = []
        for r in found:
            try:
                config.add_repo(cfg, r); added.append(r)
            except ValueError:
                pass
        config.save(cfg)
        print(f"扫描到 {len(found)} 仓,纳入 {len(added)}:")
        for r in added:
            print(" +", r)


def cmd_feishu(cfg, a):
    if a.action == "ls":
        for b in cfg["feishu"]["bitables"]:
            print(f"{b['name']}  app_token={b['app_token']} table={b['table_id']}")
    elif a.action == "add":
        app_token, table_id = config.parse_bitable_url(a.value)
        if not table_id:
            table_id = input("URL 未含 table_id,请手输 table_id: ").strip()
        name = input("给这个需求池起个名(如 数据中台需求池): ").strip() or "需求池"
        config.add_bitable(cfg, name, app_token, table_id)
        config.save(cfg)
        print(f"已加飞书表 {name}: app_token={app_token} table={table_id}")
    elif a.action == "rm":
        cfg["feishu"]["bitables"] = [b for b in cfg["feishu"]["bitables"]
                                     if b["name"] != a.value]
        config.save(cfg); print("已删")


def cmd_identity(cfg, a):
    if a.action == "ls":
        print("emails:", cfg["identities"]["emails"])
        print("names :", cfg["identities"]["names"])
    elif a.action == "add":
        v = a.value
        bucket = "emails" if "@" in v else "names"
        if v not in cfg["identities"][bucket]:
            cfg["identities"][bucket].append(v)
        config.save(cfg); print(f"已加 {bucket}: {v}")


def cmd_doc(cfg, a):
    if a.action == "triage":
        if a.apply:
            mapping = intake.parse_mapping_tsv(a.apply)
            for dest, msg in intake.apply_triage(cfg, mapping):
                print(("  ✓ " if dest else "  · ") + msg)
            if a.push:
                vault_git(cfg, True)
        else:
            print(intake.triage_manifest(cfg, subdir=a.to or "inbox"))
        return
    if a.action == "ls":
        nd = config.notes_dir(cfg)
        if not os.path.isdir(nd):
            print("(notes/ 还没有文档,用 loom doc add <路径> 添加)")
            return
        for dp, dns, fns in sorted(os.walk(nd)):
            dns[:] = [d for d in dns if d != "_archive"]   # 档案区不在此列(量大)
            for fn in sorted(fns):
                print(os.path.relpath(os.path.join(dp, fn), nd))
        return
    if not a.path:
        print("用法:loom doc add <路径…> [--to 类目] [--tags a,b] [--title T] [--move] [--push]")
        return
    results = intake.ingest(cfg, a.path, to=a.to, tags=a.tags, title=a.title, move=a.move)
    ok = 0
    for dest, msg in results:
        print(("  ✓ " if dest else "  · ") + msg)
        if dest and os.path.splitext(dest)[1].lower() in intake.BINARY_EXT:
            print("      ⚠ 二进制文件原样拷入,未做密钥扫描——确认不含机密再上云")
        ok += 1 if dest else 0
    print(f"入库 {ok}/{len(results)} 个 → {config.notes_dir(cfg)}/{a.to or 'inbox'}")
    if a.push and ok:
        vault_git(cfg, True)


def cmd_data(cfg, a):
    if not a.path:
        print("用法:loom data add <csv|xlsx…> [--to 主题] [--code a.sql b.py] "
              "[--used-by 文档标题] [--tags t]")
        return
    ok = 0
    for p in a.path:
        dest, msg = dataset.add(cfg, p, to=a.to, code=a.code, used_by=a.used_by, tags=a.tags)
        print(("  ✓ " if dest else "  · ") + msg)
        ok += 1 if dest else 0
    print(f"数据入库 {ok}/{len(a.path)} 个 → {config.notes_dir(cfg)}/{a.to or 'data'}"
          "(数据卡上云,原始留 _data/ 本地)")
    if a.push and ok:
        vault_git(cfg, True)


def cmd_source(cfg, a):
    cfg["sources"].setdefault(a.name, {})["enabled"] = (a.action == "enable")
    config.save(cfg); print(f"{a.name} -> {a.action}")


# ---------------------------------------------------------------- init 引导
def _detect_git_emails():
    out = set()
    try:
        e = subprocess.run(["git", "config", "--global", "user.email"],
                           capture_output=True, text=True).stdout.strip()
        if e:
            out.add(e)
    except Exception:
        pass
    return out


def cmd_init(cfg, a):
    print("=== loom init(直接回车用默认/跳过)===")
    name = input("你的名字(如 迪仔): ").strip()
    if name:
        cfg["owner"]["name"] = name
    fn = input(f"飞书里的负责人名(默认 {name or '空'}): ").strip() or name
    if fn:
        cfg["owner"]["feishu_name"] = fn

    emails = _detect_git_emails()
    print(f"探测到 git 邮箱: {sorted(emails) or '无'}")
    extra = input("补充你的 git 邮箱(逗号分隔,可空): ").strip()
    for e in [x.strip() for x in extra.split(",") if x.strip()]:
        emails.add(e)
    cfg["identities"]["emails"] = sorted(set(cfg["identities"]["emails"]) | emails)
    if name and name not in cfg["identities"]["names"]:
        cfg["identities"]["names"].append(name)

    root = input("扫描哪个目录找 git 仓?(默认 ~/Documents,空=跳过): ")
    root = root.strip() or "~/Documents"
    if root:
        found = config.scan_repos(root)
        print(f"扫到 {len(found)} 个仓")
        if found and input("全部纳入?[Y/n] ").strip().lower() != "n":
            for r in found:
                try:
                    config.add_repo(cfg, r)
                except ValueError:
                    pass

    if input("配置飞书需求池?[y/N] ").strip().lower() == "y":
        aid = input("FEISHU_APP_ID: ").strip()
        sec = input("FEISHU_APP_SECRET: ").strip()
        if aid and sec:
            os.makedirs(util.HOME, exist_ok=True)
            with open(util.ENV_PATH, "w", encoding="utf-8") as f:
                f.write(f"FEISHU_APP_ID={aid}\nFEISHU_APP_SECRET={sec}\n")
            os.chmod(util.ENV_PATH, 0o600)
            print(f"凭证写入 {util.ENV_PATH}(gitignored)")
        url = input("需求池多维表格 URL(可空,之后可 loom feishu add): ").strip()
        if url:
            app_token, table_id = config.parse_bitable_url(url)
            if not table_id:
                table_id = input("URL 未含 table_id,手输: ").strip()
            nm = input("需求池名(默认 需求池): ").strip() or "需求池"
            config.add_bitable(cfg, nm, app_token, table_id)

    config.save(cfg)
    print(f"\n✔ 配置已写 {util.CONFIG_PATH}")
    print(f"  仓 {len(cfg['repos'])} 个,身份邮箱 {len(cfg['identities']['emails'])} 个")
    print("  下一步:loom sync")


# ---------------------------------------------------------------- 入口
def build_parser():
    p = argparse.ArgumentParser(prog="loom", description="跨工具全量成果台账")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("sync", "collect"):
        sp = sub.add_parser(name)
        sp.add_argument("--since")
        sp.add_argument("--source", choices=collectors.names() + ["all"], default="all")
        if name == "sync":
            sp.add_argument("--push", action="store_true")
    sub.add_parser("build")
    sub.add_parser("today")
    sub.add_parser("init")
    sp = sub.add_parser("search")
    sp.add_argument("term")
    sp.add_argument("--limit", type=int, default=40)
    sp.add_argument("--project")
    sp.add_argument("--tool", choices=collectors.names())
    sp.add_argument("--since")
    sp.add_argument("--until")
    for cname, acts in (("repo", ("add", "rm", "scan", "ls")),
                        ("feishu", ("add", "rm", "ls")),
                        ("identity", ("add", "ls"))):
        sp = sub.add_parser(cname)
        sp.add_argument("action", choices=acts)
        sp.add_argument("value", nargs="?", default="")
    sp = sub.add_parser("source")
    sp.add_argument("action", choices=("enable", "disable"))
    sp.add_argument("name")
    sp = sub.add_parser("doc")
    sp.add_argument("action", choices=("add", "ls", "triage"))
    sp.add_argument("path", nargs="*")
    sp.add_argument("--to")
    sp.add_argument("--tags")
    sp.add_argument("--title")
    sp.add_argument("--apply")            # triage:应用 AI 给的映射 TSV
    sp.add_argument("--move", action="store_true")
    sp.add_argument("--push", action="store_true")
    sp = sub.add_parser("data")
    sp.add_argument("action", choices=("add",))
    sp.add_argument("path", nargs="*")    # csv/xlsx 数据文件
    sp.add_argument("--to")
    sp.add_argument("--code", nargs="*")  # 产出/相关代码(sql/py/…)
    sp.add_argument("--used-by", dest="used_by")
    sp.add_argument("--tags")
    sp.add_argument("--push", action="store_true")
    return p


def main(argv=None):
    util.load_env()
    args = build_parser().parse_args(argv)
    cfg = config.load()
    handlers = {
        "sync": cmd_sync, "collect": cmd_collect, "build": cmd_build,
        "today": cmd_today, "search": cmd_search, "init": cmd_init,
        "repo": cmd_repo, "feishu": cmd_feishu, "identity": cmd_identity,
        "source": cmd_source, "doc": cmd_doc, "data": cmd_data,
    }
    handlers[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
