# -*- coding: utf-8 -*-
"""loom 测试:纯标准库 unittest,零外部依赖。

关键:LOOM_HOME 必须在导入 loom 之前指向临时目录 —— util 在导入时就把 HOME/
DATA_PATH/INDEX_PATH 定死了,晚设会污染真实实例。
"""
import json
import os
import sys
import tempfile
import unittest

_TMP_HOME = tempfile.mkdtemp(prefix="loom-test-home-")
os.environ["LOOM_HOME"] = _TMP_HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loom import config, render, search, store, util          # noqa: E402
from loom.collectors import cursor as cursor_col               # noqa: E402
from loom.collectors import git as git_col                     # noqa: E402
from loom.collectors import claude as claude_col                # noqa: E402
import subprocess                                              # noqa: E402


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _entry(id, date, project, tool, kind, summary, ref="", **detail):
    ts = detail.pop("ts", date + "T09:00:00")
    return {"id": id, "date": date, "ts": ts, "project": project, "tool": tool,
            "kind": kind, "summary": summary, "ref": ref or id, "detail": detail}


class StoreTest(unittest.TestCase):
    def setUp(self):
        if os.path.exists(util.DATA_PATH):
            os.remove(util.DATA_PATH)

    def test_save_load_roundtrip_and_upsert(self):
        by_id = {}
        store.upsert(by_id, [_entry("git:a", "2026-06-01", "p1", "git", "commit", "第一条")])
        store.save(by_id)
        loaded = store.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded["git:a"]["summary"], "第一条")

        # 同 id 覆盖(幂等),不同 id 追加
        store.upsert(loaded, [_entry("git:a", "2026-06-01", "p1", "git", "commit", "改后"),
                              _entry("git:b", "2026-06-02", "p1", "git", "commit", "新增")])
        store.save(loaded)
        again = store.load()
        self.assertEqual(len(again), 2)
        self.assertEqual(again["git:a"]["summary"], "改后")

    def test_save_sorted_by_ts(self):
        by_id = {}
        store.upsert(by_id, [
            _entry("x", "2026-06-03", "p", "git", "commit", "晚", ts="2026-06-03T10:00:00"),
            _entry("y", "2026-06-01", "p", "git", "commit", "早", ts="2026-06-01T10:00:00")])
        store.save(by_id)
        lines = [json.loads(l) for l in _read(util.DATA_PATH).splitlines()]
        self.assertEqual([r["id"] for r in lines], ["y", "x"])  # 按 ts 升序落盘


class ConfigTest(unittest.TestCase):
    def test_parse_bitable_url(self):
        at, tid = config.parse_bitable_url(
            "https://x.feishu.cn/base/Abc123def456ghi789jk?table=tblXYZ&view=vew1")
        self.assertEqual(at, "Abc123def456ghi789jk")
        self.assertEqual(tid, "tblXYZ")

        # wiki 形态 + 无 table
        at2, tid2 = config.parse_bitable_url(
            "https://x.feishu.cn/wiki/Wiki0000000000000000tok")
        self.assertEqual(at2, "Wiki0000000000000000tok")
        self.assertIsNone(tid2)

    def test_add_bitable_dedup_and_enable(self):
        cfg = json.loads(json.dumps(config.DEFAULT_CONFIG))
        self.assertFalse(cfg["feishu"]["enabled"])
        config.add_bitable(cfg, "池A", "tok1", "tbl1")
        config.add_bitable(cfg, "池A", "tok2", "tbl2")  # 同名应替换,不重复
        self.assertTrue(cfg["feishu"]["enabled"])
        self.assertEqual(len(cfg["feishu"]["bitables"]), 1)
        self.assertEqual(cfg["feishu"]["bitables"][0]["app_token"], "tok2")

    def test_add_repo_rejects_non_git(self):
        cfg = json.loads(json.dumps(config.DEFAULT_CONFIG))
        with self.assertRaises(ValueError):
            config.add_repo(cfg, _TMP_HOME)  # 不是 git 仓

    def test_load_merges_defaults(self):
        # 只写部分配置,load 应补齐默认键(旧配置平滑升级)
        partial = {"owner": {"name": "测试"}}
        with open(util.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(partial, f)
        try:
            cfg = config.load()
            self.assertEqual(cfg["owner"]["name"], "测试")
            self.assertIn("cursor", cfg["sources"])       # 默认键补齐
            self.assertIn("bitables", cfg["feishu"])
        finally:
            os.remove(util.CONFIG_PATH)


class CursorProjectTest(unittest.TestCase):
    def test_prefers_workspace_fspath(self):
        c = {"workspaceIdentifier": {"uri": {"fsPath": "/Users/x/Documents/proj-a"}},
             "trackedGitRepos": [{"repoPath": "/Users/x/Documents/other"}]}
        self.assertEqual(cursor_col._project(c), "proj-a")

    def test_skips_scratch_worktree_falls_to_repo(self):
        c = {"workspaceIdentifier": {"uri": {"fsPath": "/private/tmp/xxx/scratchpad/wt-1"}},
             "trackedGitRepos": [{"repoPath": "/Users/x/Documents/real-repo"}]}
        self.assertEqual(cursor_col._project(c), "real-repo")

    def test_all_scratch_returns_cursor_bucket(self):
        c = {"workspaceIdentifier": {"uri": {"fsPath": "/private/tmp/a/wt-9"}},
             "trackedGitRepos": [{"repoPath": "/private/tmp/b/scratchpad/wt-2"}]}
        self.assertEqual(cursor_col._project(c), "cursor")

    def test_no_workspace_no_repos(self):
        self.assertEqual(cursor_col._project({"workspaceIdentifier": {"id": "1782980336368"}}),
                         "cursor")


class GitCollectorTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="loom-repo-")
        env = dict(os.environ, GIT_AUTHOR_NAME="tester", GIT_AUTHOR_EMAIL="me@test.dev",
                   GIT_COMMITTER_NAME="tester", GIT_COMMITTER_EMAIL="me@test.dev")
        def g(*a):
            subprocess.run(["git", "-C", self.repo, *a], check=True, env=env,
                           capture_output=True)
        g("init", "-q")
        for name, txt in (("a.txt", "l1\nl2\nl3\n"), ("b.txt", "x\ny\n")):
            with open(os.path.join(self.repo, name), "w") as f:
                f.write(txt)
        g("add", "-A")
        # 带多行正文 + trailer 的提交
        msg = ("feat: 加两个文件\n\n"
               "这是正文第一行,解释为什么。\n第二行细节。\n\n"
               "Co-Authored-By: bot <b@x>")
        g("commit", "-q", "-m", msg)
        self.cfg = {"repos": [self.repo],
                    "identities": {"emails": ["me@test.dev"], "names": []}}

    def test_captures_body_files_and_strips_trailer(self):
        out = git_col.collect(self.cfg, "2000-01-01")
        self.assertEqual(len(out), 1)
        d = out[0]["detail"]
        self.assertEqual(out[0]["summary"], "feat: 加两个文件")
        self.assertIn("为什么", d["body"])           # 正文被抓到
        self.assertIn("第二行细节", d["body"])
        self.assertNotIn("Co-Authored-By", d["body"])  # trailer 被剥掉
        self.assertEqual(d["files"], 2)               # numstat 未被正文干扰
        paths = {f["path"] for f in d["file_list"]}
        self.assertEqual(paths, {"a.txt", "b.txt"})

    def test_filters_by_identity(self):
        cfg = {"repos": [self.repo], "identities": {"emails": ["other@x"], "names": []}}
        self.assertEqual(git_col.collect(cfg, "2000-01-01"), [])  # 非本人 → 不抓


class ClaudeCollectorTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="loom-claude-")
        proj = os.path.join(self.root, "-Users-x-proj-z")
        os.makedirs(proj)
        lines = [
            {"cwd": "/Users/x/proj-z", "timestamp": "2026-06-01T09:00:00Z",
             "type": "user", "message": {"content": "我要重构归因管道,先梳理现状再动手"}},
            {"timestamp": "2026-06-01T09:05:00Z", "type": "assistant",
             "message": {"content": "好的"}},
            {"type": "ai-title", "title": "归因管道重构"},
        ]
        with open(os.path.join(proj, "sid-1.jsonl"), "w", encoding="utf-8") as f:
            for d in lines:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        self.cfg = {"sources": {"claude": {"enabled": True, "projects_dir": self.root}}}

    def test_captures_title_and_full_opening(self):
        out = claude_col.collect(self.cfg, "2000-01-01")
        self.assertEqual(len(out), 1)
        e = out[0]
        self.assertEqual(e["summary"], "归因管道重构")            # 标题优先
        self.assertTrue(e["detail"]["opening"].startswith("我要重构归因管道"))  # 开场全文
        self.assertEqual(e["project"], "proj-z")
        self.assertEqual(e["detail"]["user"], 1)

    def test_disabled_returns_empty(self):
        cfg = {"sources": {"claude": {"enabled": False}}}
        self.assertEqual(claude_col.collect(cfg, "2000-01-01"), [])


class RenderNotesTest(unittest.TestCase):
    def setUp(self):
        # vault.dir → journal_dir = vault.dir + '/journal'(render 用 config.journal_dir)
        self.cfg = {"vault": {"dir": tempfile.mkdtemp(prefix="loom-vault-")}}

    def _build(self, entries):
        return render.build(self.cfg, {e["id"]: e for e in entries})

    def test_build_creates_journal_and_notes(self):
        self._build([_entry("git:1", "2026-06-30", "p", "git", "commit", "干活")])
        jdir = config.journal_dir(self.cfg)
        self.assertTrue(os.path.exists(os.path.join(jdir, "2026-06-30.md")))
        self.assertTrue(os.path.exists(os.path.join(jdir, "2026-06-30.notes.md")))
        body = _read(os.path.join(jdir, "2026-06-30.md"))
        self.assertIn("![[2026-06-30.notes]]", body)   # 内嵌回链

    def test_notes_never_overwritten(self):
        self._build([_entry("git:1", "2026-06-30", "p", "git", "commit", "v1")])
        jdir = config.journal_dir(self.cfg)
        notes = os.path.join(jdir, "2026-06-30.notes.md")
        with open(notes, "a", encoding="utf-8") as f:
            f.write("\n我手写的重要结论,绝不能被吃掉。\n")
        # 再次渲染(内容变了)
        self._build([_entry("git:1", "2026-06-30", "p", "git", "commit", "v2"),
                     _entry("git:2", "2026-06-30", "p", "git", "commit", "又一条")])
        self.assertIn("我手写的重要结论", _read(notes))
        # 自动区确实更新了
        self.assertIn("又一条", _read(os.path.join(jdir, "2026-06-30.md")))

    def test_session_opening_rendered_only_when_additive(self):
        jdir = config.journal_dir(self.cfg)
        adds = _entry("claude:1", "2026-07-01", "p", "claude", "session", "归因重构",
                      start="2026-07-01T09:00:00", end="2026-07-01T10:00:00",
                      opening="其实我想重构整个管道,还有一大段展开的上下文,标题没覆盖到。")
        same = _entry("claude:2", "2026-07-01", "p", "claude", "session", "梳理现状",
                      start="2026-07-01T11:00:00", end="2026-07-01T12:00:00",
                      opening="梳理现状")  # opening 等于 summary → 不重复渲染
        self._build([adds, same])
        body = _read(os.path.join(jdir, "2026-07-01.md"))
        self.assertIn("还有一大段展开的上下文", body)   # 追加信息被渲染
        self.assertEqual(body.count("  > 梳理现状"), 0)  # 冗余的不渲染

    def test_migrates_legacy_sentinel_content(self):
        jdir = config.journal_dir(self.cfg)
        os.makedirs(jdir, exist_ok=True)
        # 造一个旧版内联手写正文的 {date}.md
        with open(os.path.join(jdir, "2026-05-01.md"), "w", encoding="utf-8") as f:
            f.write("# 旧日志\n\n" + render.LEGACY_MARK + "\n\n迁移前写的字。\n")
        self._build([_entry("git:9", "2026-05-01", "p", "git", "commit", "x")])
        notes = _read(os.path.join(jdir, "2026-05-01.notes.md"))
        self.assertIn("迁移前写的字", notes)


class SearchTest(unittest.TestCase):
    def setUp(self):
        for p in (util.DATA_PATH, util.INDEX_PATH):
            if os.path.exists(p):
                os.remove(p)
        entries = [
            _entry("git:1", "2026-06-30", "data-marketing", "git", "commit",
                   "fix(cohort): 优化 Vertica 慢查询", ts="2026-06-30T09:00:00"),
            _entry("git:2", "2026-06-25", "data-insights", "git", "commit",
                   "feat: 注册 cohort autoloader", ts="2026-06-25T09:00:00"),
            _entry("cur:1", "2026-04-14", "data-marketing", "cursor", "session",
                   "需求评审会议纪要", ts="2026-04-14T09:00:00"),
        ]
        store.save({e["id"]: e for e in entries})
        search.rebuild()

    def test_fts_match_3plus_chars(self):
        hits = search.query("cohort")
        ids = {h["id"] for h in hits}
        self.assertEqual(ids, {"git:1", "git:2"})

    def test_short_cjk_falls_back_to_like(self):
        # "需求" 2 字符 → trigram 不命中 → LIKE 子串兜底
        hits = search.query("需求")
        self.assertEqual({h["id"] for h in hits}, {"cur:1"})

    def test_filters(self):
        self.assertEqual({h["id"] for h in search.query("cohort", tool="cursor")}, set())
        self.assertEqual({h["id"] for h in search.query("cohort", project="data-insights")},
                         {"git:2"})
        self.assertEqual({h["id"] for h in search.query("cohort", since="2026-06-28")},
                         {"git:1"})

    def test_empty_term_browses_by_filter(self):
        hits = search.query("", project="data-marketing")
        self.assertEqual({h["id"] for h in hits}, {"git:1", "cur:1"})

    def test_auto_rebuild_when_index_missing(self):
        os.remove(util.INDEX_PATH)
        self.assertTrue(len(search.query("cohort")) == 2)  # ensure() 自动重建
        self.assertTrue(os.path.exists(util.INDEX_PATH))


if __name__ == "__main__":
    unittest.main(verbosity=2)
