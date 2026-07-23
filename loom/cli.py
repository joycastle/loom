# -*- coding: utf-8 -*-
"""loom CLI:采集/渲染/检索 + 配置管理 + init 引导。"""
import argparse
import os
import subprocess
import sys
from datetime import datetime

from . import agents, config, dataset, digest, intake, render, report, search, serve, skillsync, store, topics, util
from . import collectors


# ---------------------------------------------------------------- 采集/渲染
def _since(cfg, arg):
    return arg or util.since_date(cfg.get("default_since_days", 100))


def _sync_sources(cfg, requested="all"):
    """Resolve CLI sources with the same grouped switches as the console."""
    if requested and requested != "all":
        if requested == "git":
            return [name for name in ("git", "docs")
                    if name in collectors.REGISTRY and collectors.is_syncable(name)]
        return [requested]
    return [name for name in collectors.sync_names()
            if config.source_enabled(cfg, name)]


def do_collect(cfg, sources, since):
    by_id = store.load()
    redact = cfg.get("redact", True)
    total = 0
    for s in sources:
        try:                                    # 一个源坏了不该掀翻整个 sync(个人数据源会腐烂)
            collector_cfg = cfg
            if s == "docs":
                # docs 已折入 Git；覆盖旧配置中的独立开关，保持 CLI/管理页语义一致。
                collector_cfg = dict(cfg)
                collector_cfg["sources"] = dict(cfg.get("sources", {}))
                collector_cfg["sources"]["docs"] = dict(
                    cfg.get("sources", {}).get("docs", {}),
                    enabled=config.source_enabled(cfg, "docs"))
            got = collectors.REGISTRY[s](collector_cfg, since)
        except Exception as e:
            util.log(f"  [{s}] 采集失败,跳过: {e}")
            continue
        if got:
            if redact:
                got = [util.redact_entry(e) for e in got]  # 入库前抹密钥
            store.upsert(by_id, got)
            print(f"  [{s}] 采集 {len(got)} 条")
        total += len(got)
    nd = digest.apply_all(by_id)         # 会话摘要叠加回条目(采集器重建后再覆盖,不丢)
    if nd:
        print(f"  [digest] 覆盖 {nd} 条会话摘要")
    store.save(by_id)
    search.rebuild()  # 派生检索索引随采集同步重建
    print(f"采集完成:本轮 {total} 条,库内共 {len(by_id)} 条(since {since})")
    return by_id


def do_build(cfg):
    n = render.build(cfg, store.load())
    print(f"渲染完成:{n} 个日记 → {config.journal_dir(cfg)}")


# 上云前必须被 git 忽略的东西:原始数据(_data/)、密钥(.env)、无法打码的二进制原件。
# 由代码保证存在——绝不能依赖用户手工建 .gitignore(否则换台机器就把原始数据推上云)。
_REQUIRED_IGNORES = ["_data/", ".env", "*.xlsx", "*.pptx", "*.numbers",
                     "*.pages", "*.key", "*.parquet", "*.pdf", "*.docx"]


def _ensure_gitignore(vd):
    """确保 vault/.gitignore 含所有必需忽略项(缺啥补啥,保留用户已有行)。返回是否有改动。"""
    gi = os.path.join(vd, ".gitignore")
    lines = open(gi, encoding="utf-8").read().splitlines() if os.path.exists(gi) else []
    have = {ln.strip() for ln in lines}
    missing = [p for p in _REQUIRED_IGNORES if p not in have]
    if not missing:
        return False
    if not lines:
        lines = ["# loom:原始数据/二进制/密钥只在本地留存,不上云"]
    lines += missing
    with open(gi, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return True


def _untrack_ignored(vd):
    """把「已被跟踪但现在应忽略」的文件从 git 移出(保留本地文件)。返回被移出的路径列表。

    core.quotepath=false:否则 git 会把非 ASCII 路径转成八进制转义,`git rm` 匹配不上
    (且 git rm 会先校验所有 pathspec,一个不匹配就整批失败)。"""
    r = subprocess.run(["git", "-c", "core.quotepath=false", "-C", vd,
                        "ls-files", "-i", "-c", "--exclude-standard"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "读取已跟踪文件失败").strip())
    files = [f for f in r.stdout.splitlines() if f.strip()]
    if files:
        removed = subprocess.run(
            ["git", "-C", vd, "rm", "--cached", "--quiet", "--"] + files,
            capture_output=True, text=True)
        if removed.returncode != 0:
            raise RuntimeError((removed.stderr or removed.stdout or
                                "移出应本地留存文件失败").strip())
    return files


def vault_git(cfg, push):
    vd = config.vault_dir(cfg)
    os.makedirs(vd, exist_ok=True)
    result = {"ok": False, "status": "error", "stage": "not_started",
              "commit": "not_started",
              "push": "not_requested" if not push else "not_started", "message": "",
              "errors": []}

    def run(args):
        try:
            r = subprocess.run(["git", "-C", vd] + args, capture_output=True,
                               text=True, timeout=120)
            detail = (r.stderr or r.stdout or "").strip()
            return r, detail
        except Exception as e:
            return None, str(e)

    def fail(stage, detail):
        technical = detail or "未知错误"
        low = technical.lower()
        if "index.lock" in low:
            hint = "Git 仓库正被其它进程占用，请稍后重试"
        elif "未配置 remote" in technical:
            hint = technical
        elif stage == "推送":
            hint = "无法推送到远程仓库，请检查 remote、网络和权限"
        elif stage == "提交":
            hint = "无法创建本地提交，请检查 Git 身份或提交钩子"
        elif stage == "初始化":
            hint = "无法初始化本地 Git 仓库"
        else:
            hint = "无法准备待备份文件，请查看技术日志"
        message = f"{stage}失败:{hint}"
        result["errors"].append({"stage": stage, "message": detail or "未知错误"})
        result["stage"] = {"初始化": "init", "准备": "prepare",
                           "提交": "commit", "推送": "push"}.get(stage, "unknown")
        result["message"] = message
        if stage in ("初始化", "准备", "提交"):
            result["commit"] = "failed"
        if stage == "推送":
            result["push"] = "failed"
        print(message)
        if technical != hint:
            print(technical)
        return result

    probe, _ = run(["rev-parse", "--git-dir"])
    if not probe or probe.returncode != 0:
        initialized, detail = run(["init", "-q"])
        if not initialized or initialized.returncode != 0:
            return fail("初始化", detail)
    try:
        _ensure_gitignore(vd)                   # 先立规矩,再 add
        untracked = _untrack_ignored(vd)        # 历史误跟踪文件移出云端(本地保留)
    except Exception as e:
        return fail("准备", str(e))
    if untracked:
        print(f"已从云端移出 {len(untracked)} 个应本地留存的文件(本地仍在):")
        for f in untracked[:10]:
            print("  -", f)
        if len(untracked) > 10:
            print(f"  …及其余 {len(untracked) - 10} 个")
    added, detail = run(["add", "-A"])
    if not added or added.returncode != 0:
        return fail("准备", detail)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    changed, detail = run(["diff", "--cached", "--quiet"])
    if not changed or changed.returncode not in (0, 1):
        return fail("准备", detail)
    if changed.returncode == 1:
        committed, detail = run(["commit", "-q", "-m", f"loom sync {stamp}"])
        if not committed or committed.returncode != 0:
            return fail("提交", detail)
        result["commit"] = "created"
        print(f"已提交 vault ({stamp})")
    else:
        result["commit"] = "unchanged"
        print("无变更,跳过提交")
    if push:
        remotes, detail = run(["remote"])
        if not remotes or remotes.returncode != 0:
            return fail("推送", detail)
        if not remotes.stdout.strip():
            return fail("推送", "未配置 remote（请在 loom 或 gh 中配置 vault.remote）")
        pushed, detail = run(["push", "-q"])
        if not pushed or pushed.returncode != 0:
            return fail("推送", detail)
        result["push"] = "success"
        print("已 push 到云端")
    result["ok"] = True
    result["status"] = "success"
    result["stage"] = "complete"
    result["message"] = "备份并推送完成" if push else "本地备份完成"
    return result


def _vault_git_checked(cfg, push):
    """CLI commands must exit non-zero when an explicitly requested backup fails."""
    result = vault_git(cfg, push)
    if not result.get("ok"):
        raise SystemExit(1)
    return result


# ---------------------------------------------------------------- 命令
def cmd_sync(cfg, a):
    srcs = _sync_sources(cfg, a.source)
    by_id = do_collect(cfg, srcs, _since(cfg, a.since))
    n = render.build(cfg, by_id)
    print(f"渲染完成:{n} 个日记")
    _vault_git_checked(cfg, a.push)


def cmd_collect(cfg, a):
    srcs = _sync_sources(cfg, a.source)
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


def cmd_related(cfg, a):
    from . import relations
    by_id = store.load()
    if a.id not in by_id:
        print(f"(无此条目 id:{a.id};用 loom search 找到 id)")
        return
    e = by_id[a.id]
    print(f"# 与 [{e['tool']}/{e['kind']}] {e.get('summary','')[:56]} 相关的条目")
    print(f"  {a.id}\n")
    hits = relations.neighbors(by_id, a.id, limit=a.limit)
    if not hits:
        print("(暂无自动派生的关联;试试 loom topic show 看语义主题)")
        return
    for h in hits:
        print(f"{h['date']} [{h['project']}/{h['tool']}] {h['summary'][:56]}  ({h['ref']})")
        print(f"    ↳ {' · '.join(h['reasons'])}  [{h['score']}]  id={h['id']}")


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
                _vault_git_checked(cfg, True)
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
        ok += 1 if dest else 0
    print(f"入库 {ok}/{len(results)} 个 → {config.notes_dir(cfg)}/{a.to or 'inbox'}")
    if a.push and ok:
        _vault_git_checked(cfg, True)


def cmd_data(cfg, a):
    if not a.path:
        print("用法:loom data add <csv|xlsx…> [--to 主题] [--code a.sql b.py] "
              "[--used-by 文档标题] [--tags t]")
        return
    ok = 0
    for p in a.path:
        dest, msg = dataset.add(cfg, p, to=a.to, code=a.code, used_by=a.used_by,
                                tags=a.tags, kind=a.kind, frm=getattr(a, "frm", None))
        print(("  ✓ " if dest else "  · ") + msg)
        ok += 1 if dest else 0
    print(f"数据入库 {ok}/{len(a.path)} 个 → {config.notes_dir(cfg)}/{a.to or 'data'}"
          "(数据卡上云,原始留 _data/ 本地)")
    if a.push and ok:
        _vault_git_checked(cfg, True)


def _store_reports(cfg, entries, push):
    if cfg.get("redact", True):
        entries = [util.redact_entry(e) for e in entries]
    by_id = store.load()
    store.upsert(by_id, entries)
    store.save(by_id)
    search.rebuild()
    render.build(cfg, by_id)
    if push:
        _vault_git_checked(cfg, True)


def cmd_report(cfg, a):
    if a.action == "gen":
        if not a.path:
            print("用法:loom report gen <日期>(YYYY-MM-DD)")
            return
        print(report.gen_material(cfg, a.path))
        return
    if a.action == "set":
        if not a.path:
            print("用法:loom report set <日期> [--file 日报.md](无 --file 则读 stdin)")
            return
        text = open(util.expand(a.file), encoding="utf-8").read() if a.file else sys.stdin.read()
        if not text.strip():
            print("没有日报内容")
            return
        _store_reports(cfg, [report.set_from_text(cfg, a.path, text)], a.push)
        print(f"已写入 {a.path} 日报(AI 生成)→ 渲染进日记,已可检索")
        return
    if a.action != "import" or not a.path:
        print("用法:loom report <import 日报.xlsx | gen 日期 | set 日期> [--push]")
        return
    entries = report.import_xlsx(cfg, a.path)
    if not entries:
        print("没解析到日报(检查列名:提交时间/今日工作…)")
        return
    if cfg.get("redact", True):
        entries = [util.redact_entry(e) for e in entries]
    by_id = store.load()
    store.upsert(by_id, entries)
    store.save(by_id)
    search.rebuild()
    n = render.build(cfg, by_id)
    dates = sorted(e["date"] for e in entries)
    print(f"导入 {len(entries)} 篇日报({dates[0]}–{dates[-1]})→ 并入 {n} 个日记,已可检索")
    if a.push:
        _vault_git_checked(cfg, True)


def cmd_session(cfg, a):
    if a.action == "gen":
        if not a.path:
            print("用法:loom session gen <日期>(YYYY-MM-DD)")
            return
        print(digest.gen_material(cfg, a.path))
        return
    if a.action == "set":
        if not a.path:
            print("用法:loom session set <日期> [--file 摘要.tsv](无 --file 则读 stdin)")
            return
        text = open(util.expand(a.file), encoding="utf-8").read() if a.file else sys.stdin.read()
        applied = digest.set_from_text(cfg, a.path, text)
        if not applied:
            print("没写入摘要(检查 TSV:id<TAB>标题<TAB>摘要;id 需为当天真实会话)")
            return
        by_id = store.load()
        digest.apply_all(by_id)          # 立即叠加,无需等下次 sync
        store.save(by_id)
        search.rebuild()
        render.build(cfg, by_id)
        print(f"已写入 {len(applied)} 条会话摘要 → 覆盖标题、进检索、渲染进日记")
        if a.push:
            _vault_git_checked(cfg, True)
        return
    if a.action == "ls":
        d = digest.load()
        for eid in sorted(d, key=lambda k: (d[k].get("date", ""), k)):
            print(f"{d[eid].get('date','?')}  {eid}\n    {d[eid].get('title','')}")
        print(f"\n共 {len(d)} 条会话摘要")


def cmd_note(cfg, a):
    if a.update:
        if not a.text:
            print('用法:loom note --update <关键词> "<更新内容>"')
            return
        dest, msg = intake.note_update(cfg, a.update, a.text)
        print(("  ✓ " if dest else "  · ") + msg)
        if dest:
            do_collect(cfg, ["notes"], util.since_date(cfg.get("default_since_days", 100)))
            print("  (检索索引已更新)")
            if a.push:
                _vault_git_checked(cfg, True)
        return
    if not a.text:
        print('用法:loom note "<文本>" [--to 类目] [--tags a,b] [--title T] [--push]')
        print('     loom note --update <关键词> "<更新内容>"')
        return
    tags = [t.strip() for t in (a.tags or "").split(",") if t.strip()]
    dest, msg = intake.note(cfg, a.text, to=a.to, tags=tags, title=a.title)
    print(("  ✓ " if dest else "  · ") + msg)
    if dest:
        print("  (下次 loom sync 后进检索 / 可被 loom topic 打标)")
        if a.push:
            _vault_git_checked(cfg, True)


def cmd_topic(cfg, a):
    if a.action == "ls":
        print(topics.tree(cfg))
        return
    if a.action == "gather":
        if a.hierarchy:
            print(topics.hierarchy_prompt(cfg))
        else:
            print(topics.gather(cfg, store.load(), query=a.query, project=a.project,
                                since=a.since, limit=a.limit or 60, refine=a.refine))
        return
    if a.action == "set-parents":
        if not a.file:
            print("用法:loom topic set-parents --file <层级.tsv>(先 loom topic gather --hierarchy)")
            return
        try:
            n, created = topics.set_parents(cfg, topics.parse_mapping_tsv(a.file))
        except ValueError as e:
            print(f"层级校验失败(未写入):{e}")
            return
        print(f"已设置 {n} 个主题的父级" +
              (f";新建主题 {len(created)}:{', '.join(created)}" if created else ""))
        if a.push:
            _vault_git_checked(cfg, True)
        return
    if a.action == "apply":
        if not a.file:
            print("用法:loom topic apply --file <映射.tsv>")
            return
        n, created = topics.apply(cfg, topics.parse_mapping_tsv(a.file))
        print(f"已归类 {n} 条" + (f";新建主题 {len(created)}:{', '.join(created)}" if created else ""))
        search.rebuild()
        if a.push:
            _vault_git_checked(cfg, True)
        return
    if a.action == "show":
        if not a.query:
            print("用法:loom topic show <主题>")
            return
        print(topics.show(cfg, a.query, store.load()))
        return


def cmd_deprecate(cfg, a):
    if not a.path:
        print("用法:loom deprecate <notes 相对路径…> [--superseded-by 标题] [--mark] [--push]")
        return
    ok = 0
    for p in a.path:
        dest, msg = intake.deprecate(cfg, p, superseded_by=a.superseded_by, mark=a.mark)
        print(("  ✓ " if dest else "  · ") + msg)
        ok += 1 if dest else 0
    if not ok:
        return
    # 刷新索引:删掉指向已消失文件的 note 旧条目(移进 _attic 的),再重采 notes 让 ⚠ 标记入库
    by_id = store.load()
    nd = config.notes_dir(cfg)
    for eid in list(by_id):
        e = by_id[eid]
        relp = (e.get("detail") or {}).get("path")
        if e.get("tool") == "notes" and relp and not os.path.exists(os.path.join(nd, relp)):
            del by_id[eid]                       # 文件没了(移走/删了)→ 清残留条目(不再被搜到)
    fresh = collectors.REGISTRY["notes"](cfg, util.since_date(36500))
    if cfg.get("redact", True):
        fresh = [util.redact_entry(e) for e in fresh]
    store.upsert(by_id, fresh)
    store.save(by_id)
    search.rebuild()
    render.build(cfg, by_id)
    print(f"已处理 {ok} 项;索引已刷新(废弃内容移出检索)")
    if a.push:
        _vault_git_checked(cfg, True)


def cmd_serve(cfg, a):
    serve.serve(cfg, port=a.port)


def cmd_mcp_serve(cfg, a):
    from . import mcp
    mcp.serve(cfg)


_SKILL_STATUS_LABEL = {
    "installed": "已安装", "update_available": "有更新", "drifted": "⚠ 已被改动",
    "missing": "⚠ 文件缺失", "foreign": "⚠ 非 loom 内容", "not_installed": "未安装",
}


def cmd_skill(cfg, a):
    """把 loom-skill 一键装进 / 卸载出各 AI 助手(Claude/Codex/Cursor/CodeBuddy)。"""
    if a.action == "status":
        for row in skillsync.status(cfg):
            present = "在" if row["present"] else "无"
            label = _SKILL_STATUS_LABEL.get(row["status"], row["status"])
            print(f"{row['agent']:10s} [{present}] {label:10s} {row['target']}")
        return
    keys = skillsync.resolve_agents(a.agent, cfg, for_install=(a.action == "install"))
    if not keys:
        print("没有检测到可操作的 AI 助手(--agent all 只处理已安装的)")
        return
    for key in keys:
        if a.action == "install":
            r = skillsync.install(key, cfg, dry_run=a.dry_run)
        else:
            r = skillsync.uninstall(key, cfg, dry_run=a.dry_run, force=a.force)
        mark = ("  · " if r.get("action", "").startswith(
            ("would_", "unchanged", "not_", "skipped_")) else "  ✓ ")
        print(mark + r.get("message", ""))
        if r.get("backup"):
            print(f"      (已备份原文件 → {r['backup']})")


def cmd_source(cfg, a):
    if a.name == "docs":
        raise SystemExit("项目文档已并入 Git；请改用 loom source enable|disable git")
    enabled = (a.action == "enable")
    cfg["sources"].setdefault(a.name, {})["enabled"] = enabled
    if a.name == "git":
        cfg["sources"].setdefault("docs", {})["enabled"] = enabled
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
        sp.add_argument("--source", choices=collectors.sync_names() + ["all"], default="all")
        if name == "sync":
            sp.add_argument("--push", action="store_true")
    sub.add_parser("build")
    sub.add_parser("today")
    sp = sub.add_parser("serve")
    sp.add_argument("--port", type=int, default=8787)
    sub.add_parser("mcp-serve")
    sub.add_parser("init")
    sp = sub.add_parser("search")
    sp.add_argument("term")
    sp.add_argument("--limit", type=int, default=40)
    sp.add_argument("--project")
    sp.add_argument("--tool", choices=collectors.names())
    sp.add_argument("--since")
    sp.add_argument("--until")
    sp = sub.add_parser("related")
    sp.add_argument("id")                          # 条目 id(loom search 结果里的括号/id)
    sp.add_argument("--limit", type=int, default=30)
    for cname, acts in (("repo", ("add", "rm", "scan", "ls")),
                        ("feishu", ("add", "rm", "ls")),
                        ("identity", ("add", "ls"))):
        sp = sub.add_parser(cname)
        sp.add_argument("action", choices=acts)
        sp.add_argument("value", nargs="?", default="")
    sp = sub.add_parser("source")
    sp.add_argument("action", choices=("enable", "disable"))
    sp.add_argument("name")
    sp = sub.add_parser("skill")
    sp.add_argument("action", choices=("status", "install", "uninstall"))
    sp.add_argument("--agent", choices=agents.all_keys() + ["all"], default="all")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--force", action="store_true",
                    help="卸载时连同非 loom 安装的同路径文件一并删除")
    sp = sub.add_parser("doc")
    sp.add_argument("action", choices=("add", "ls", "triage"))
    sp.add_argument("path", nargs="*")
    sp.add_argument("--to")
    sp.add_argument("--tags")
    sp.add_argument("--title")
    sp.add_argument("--apply")            # triage:应用 AI 给的映射 TSV
    sp.add_argument("--move", action="store_true")
    sp.add_argument("--push", action="store_true")
    sp = sub.add_parser("report")
    sp.add_argument("action", choices=("import", "gen", "set"))
    sp.add_argument("path", nargs="?")
    sp.add_argument("--file")                      # report set:AI 写好的日报文件
    sp.add_argument("--push", action="store_true")
    sp = sub.add_parser("session")
    sp.add_argument("action", choices=("gen", "set", "ls"))
    sp.add_argument("path", nargs="?")             # 日期 YYYY-MM-DD
    sp.add_argument("--file")                       # session set:AI 写好的摘要 TSV
    sp.add_argument("--push", action="store_true")
    sp = sub.add_parser("note")
    sp.add_argument("text", nargs="?")             # 随手信息文本(--update 时是更新内容)
    sp.add_argument("--to")
    sp.add_argument("--tags")
    sp.add_argument("--title")
    sp.add_argument("--update", metavar="关键词")  # 更新已有 note:按关键词搜文件名/标题
    sp.add_argument("--push", action="store_true")
    sp = sub.add_parser("topic")
    sp.add_argument("action", choices=("ls", "gather", "apply", "show", "set-parents"))
    sp.add_argument("query", nargs="?")           # show:主题名;gather:关键词(--refine 时=限定主题)
    sp.add_argument("--project")
    sp.add_argument("--since")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--refine", action="store_true",   # 细化:回看【已归类】条目,补更细/更多主题
                    help="gather 细化模式:重看已归类条目,补更细的叶子/遗漏的侧面主题")
    sp.add_argument("--hierarchy", action="store_true",   # gather 层级模式:让 AI 提父子边
                    help="gather 层级模式:列现有主题让 AI 提议父子关系(配 set-parents 落地)")
    sp.add_argument("--file")                      # apply:AI 给的映射 TSV
    sp.add_argument("--push", action="store_true")
    sp = sub.add_parser("deprecate")
    sp.add_argument("path", nargs="*")            # notes 相对路径
    sp.add_argument("--superseded-by", dest="superseded_by")
    sp.add_argument("--mark", action="store_true")   # 留原处只标记(默认移入 _attic)
    sp.add_argument("--push", action="store_true")
    sp = sub.add_parser("data")
    sp.add_argument("action", choices=("add",))
    sp.add_argument("path", nargs="*")    # csv/xlsx 数据文件
    sp.add_argument("--to")
    sp.add_argument("--code", nargs="*")  # 产出/相关代码(sql/py/…)
    sp.add_argument("--kind", choices=("source", "derived"))   # 原始 / 派生
    sp.add_argument("--from", dest="frm", nargs="*")           # 派生数据的上游输入(血缘)
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
        "today": cmd_today, "search": cmd_search, "related": cmd_related, "init": cmd_init,
        "repo": cmd_repo, "feishu": cmd_feishu, "identity": cmd_identity,
        "source": cmd_source, "doc": cmd_doc, "data": cmd_data, "report": cmd_report,
        "deprecate": cmd_deprecate, "topic": cmd_topic, "note": cmd_note,
        "session": cmd_session, "serve": cmd_serve, "skill": cmd_skill,
        "mcp-serve": cmd_mcp_serve,
    }
    handlers[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
