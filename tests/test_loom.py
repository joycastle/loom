# -*- coding: utf-8 -*-
"""loom 测试:纯标准库 unittest,零外部依赖。

关键:LOOM_HOME 必须在导入 loom 之前指向临时目录 —— util 在导入时就把 HOME/
DATA_PATH/INDEX_PATH 定死了,晚设会污染真实实例。
"""
import json
import os
import sqlite3
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
from loom.collectors import codebuddy as codebuddy_col          # noqa: E402
from loom.collectors import pi as pi_col                          # noqa: E402
from loom.collectors import opencode as opencode_col              # noqa: E402
from loom.collectors import docs as docs_col                    # noqa: E402
from loom.collectors import notes as notes_col                  # noqa: E402
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

    def test_save_is_atomic_no_tmp_left(self):
        store.save({"a": _entry("a", "2026-06-01", "p", "git", "commit", "x")})
        leftovers = [f for f in os.listdir(os.path.dirname(util.DATA_PATH))
                     if f.startswith("entries.jsonl.tmp")]
        self.assertEqual(leftovers, [])                # 临时文件被 os.replace 掉,不残留

    def test_load_skips_blank_and_corrupt_lines(self):
        os.makedirs(os.path.dirname(util.DATA_PATH), exist_ok=True)
        with open(util.DATA_PATH, "w", encoding="utf-8") as f:
            f.write(json.dumps(_entry("ok", "2026-06-01", "p", "git", "commit", "好")) + "\n")
            f.write("\n")                              # 空行
            f.write("{坏 json\n")                       # 损坏行:跳过而非崩
        loaded = store.load()
        self.assertEqual(set(loaded), {"ok"})


class RedactTest(unittest.TestCase):
    def test_masks_secret_values(self):
        cases = [
            "FEISHU_APP_SECRET=abcd1234efgh5678",
            'password: "hunter2xy"',
            "api_key = sk-ABCDEFGHIJKLMNOPQRSTUVWX",
            "Authorization: Bearer eyJhbGciOiZAAAAAAAA.bbbbbbbbbb.cccccccccc",
            "aws AKIAIOSFODNN7EXAMPLE key",
            "postgres://user:s3cretpw@host:5432/db",
            "token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
        ]
        for c in cases:
            out = util.redact(c)
            self.assertIn("已打码", out, f"未打码: {c} -> {out}")
        # 关键:真正的机密子串不残留
        self.assertNotIn("hunter2xy", util.redact('password: "hunter2xy"'))
        self.assertNotIn("s3cretpw", util.redact("postgres://user:s3cretpw@host/db"))

    def test_quoted_json_yaml_secrets_masked(self):
        for c in ['{"client_secret": "verySecretValue123456"}',
                  '"api_key":"AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"',
                  'password: "hunter2xyz"']:
            out = util.redact(c)
            self.assertIn("已打码", out, f"引号值未打码: {c}")
        self.assertNotIn("verySecretValue123456", util.redact('{"client_secret": "verySecretValue123456"}'))

    def test_more_token_formats(self):
        for c in ["sk_live_ABCDEFGHIJKLMNOP1234", "ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
                  "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456", "ya29.A0ARrdaM-abcdefghij",
                  "https://hooks.slack.com/services/T00/B00/xxxxAAAAbbbb",
                  "-----BEGIN PGP PRIVATE KEY BLOCK-----\nabc\n-----END PGP PRIVATE KEY BLOCK-----"]:
            self.assertIn("已打码", util.redact(c), f"未覆盖: {c[:30]}")

    def test_less_over_redaction_on_prose(self):
        # 散文/示例不该被抹(裸值不像机密)
        self.assertEqual(util.redact("token: 见 README 说明"), "token: 见 README 说明")
        self.assertEqual(util.redact("access_key: documentation"), "access_key: documentation")
        self.assertEqual(util.redact("secret: TODO/later"), "secret: TODO/later")  # 斜杠不再误伤
        # 但像机密的裸值仍抹
        self.assertIn("已打码", util.redact("token: aB3xY9zQ1234"))

    def test_quoted_value_masked_even_all_lowercase(self):
        # 带引号=数据值,即使全小写也抹(裸的全小写散文才放过)
        self.assertIn("已打码", util.redact('password: "correcthorsebattery"'))
        self.assertNotIn("已打码", util.redact("passphrase-note: correcthorsebattery"))

    def test_basic_auth_masked(self):
        self.assertIn("已打码", util.redact("Authorization: Basic dXNlcjpwYXNzd29yZDEyMw=="))

    def test_feishu_lark_webhook_masked(self):
        # 飞书/Lark 机器人 webhook 是能直接发消息的凭证,必须打码(真实归档里发现的缺口)
        fs = 'url: https://open.feishu.cn/open-apis/bot/v2/hook/c58904dd-9aca-4b92-8c5c-055c132aa420'
        self.assertIn("已打码", util.redact(fs))
        self.assertNotIn("c58904dd-9aca", util.redact(fs))
        self.assertIn("已打码", util.redact(
            "https://open.larksuite.com/open-apis/bot/v2/hook/abcDEF123456"))

    def test_safe_join_blocks_symlink_escape(self):
        base = tempfile.mkdtemp(prefix="loom-sj-")
        outside = tempfile.mkdtemp(prefix="loom-out-")
        os.symlink(outside, os.path.join(base, "escaped"))
        self.assertIsNone(util.safe_join(base, "escaped", "x.md"))   # 符号链接逃逸被拦
        self.assertIsNone(util.safe_join(base, "../x"))
        self.assertIsNotNone(util.safe_join(base, "sub", "x.md"))    # 正常子路径放行

    def test_redact_entry_recurses_lists_and_dicts(self):
        e = _entry("d:1", "2026-06-01", "p", "docs", "doc", "标题",
                   headings=["## api_key=Abc123Def456Ghi", "背景"],
                   file_list=[{"path": "x", "note": "secret=Zz99Zz99Zz99"}])
        util.redact_entry(e)
        self.assertIn("已打码", e["detail"]["headings"][0])
        self.assertIn("已打码", e["detail"]["file_list"][0]["note"])

    def test_leaves_code_and_varnames_intact(self):
        # 变量名/代码引用(非赋值)不该被动
        keep = 'c = Variable.get("secret_af_audience_apl")'
        self.assertEqual(util.redact(keep), keep)
        self.assertEqual(util.redact("SELECT app_id FROM appsflyer"),
                         "SELECT app_id FROM appsflyer")
        self.assertEqual(util.redact("fix(dwb): 补 net 分支"), "fix(dwb): 补 net 分支")

    def test_redact_entry_scrubs_detail(self):
        e = _entry("codex:1", "2026-06-01", "p", "codex", "session", "跑查询",
                   opening='conn = connect(token="sk-ABCDEFGHIJKLMNOPQRSTUV")')
        util.redact_entry(e)
        self.assertIn("已打码", e["detail"]["opening"])
        self.assertNotIn("sk-ABCDEFGHIJKLMNOPQRSTUV", e["detail"]["opening"])


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

    def test_add_repo_accepts_git_worktree(self):
        root = tempfile.mkdtemp(prefix="loom-config-repo-")
        wt = tempfile.mkdtemp(prefix="loom-config-wt-")
        env = {**os.environ, "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@x",
               "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@x"}
        subprocess.run(["git", "-C", root, "init", "-q"], check=True, env=env)
        with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as f:
            f.write("hello")
        subprocess.run(["git", "-C", root, "add", "README.md"], check=True, env=env)
        subprocess.run(["git", "-C", root, "commit", "-q", "-m", "init"],
                       check=True, env=env)
        os.rmdir(wt)
        subprocess.run(["git", "-C", root, "worktree", "add", "-q", wt],
                       check=True, env=env)

        cfg = json.loads(json.dumps(config.DEFAULT_CONFIG))
        self.assertEqual(config.add_repo(cfg, wt), wt)
        self.assertEqual(cfg["repos"], [wt])

    def test_scan_finds_worktree_and_add_rejects_same_common_repo_twice(self):
        parent = tempfile.mkdtemp(prefix="loom-config-scan-")
        root, wt = os.path.join(parent, "main"), os.path.join(parent, "linked")
        os.makedirs(root)
        env = {**os.environ, "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@x",
               "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@x"}
        subprocess.run(["git", "-C", root, "init", "-q"], check=True, env=env)
        with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as f:
            f.write("hello")
        subprocess.run(["git", "-C", root, "add", "README.md"], check=True, env=env)
        subprocess.run(["git", "-C", root, "commit", "-q", "-m", "init"],
                       check=True, env=env)
        subprocess.run(["git", "-C", root, "worktree", "add", "-q", wt],
                       check=True, env=env)

        self.assertEqual(set(config.scan_repos(parent)), {root, wt})
        cfg = json.loads(json.dumps(config.DEFAULT_CONFIG))
        config.add_repo(cfg, root)
        with self.assertRaisesRegex(ValueError, "属于同一 Git 仓库"):
            config.add_repo(cfg, wt)

    def test_load_merges_defaults(self):
        # 只写部分配置,load 应补齐默认键(旧配置平滑升级)
        partial = {"owner": {"name": "测试"}}
        with open(util.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(partial, f)
        try:
            cfg = config.load()
            self.assertEqual(cfg["owner"]["name"], "测试")
            self.assertIn("cursor", cfg["sources"])       # 默认键补齐
            self.assertIn("pi", cfg["sources"])
            self.assertIn("opencode", cfg["sources"])
            self.assertFalse(cfg["sources"]["pi"]["enabled"])
            self.assertFalse(cfg["sources"]["opencode"]["enabled"])
            self.assertIn("bitables", cfg["feishu"])
        finally:
            os.remove(util.CONFIG_PATH)

    def test_load_preserves_legacy_docs_opt_out(self):
        legacy = {"sources": {"git": {"enabled": True}, "docs": {"enabled": False}}}
        with open(util.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(legacy, f)
        try:
            cfg = config.load()
            self.assertFalse(cfg["sources"]["git"]["enabled"])
            self.assertFalse(config.source_enabled(cfg, "docs"))
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


class CursorCollectorTest(unittest.TestCase):
    def _headers(self, tmpbase, composers):
        import sqlite3
        d = os.path.join(tmpbase, "User", "globalStorage")
        os.makedirs(d)
        db = os.path.join(d, "state.vscdb")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
        con.execute("INSERT INTO ItemTable VALUES (?,?)",
                    ("composer.composerHeaders",
                     json.dumps({"allComposers": composers})))
        con.commit(); con.close()

    def test_cross_day_session_on_both_ends(self):
        base = tempfile.mkdtemp(prefix="loom-cur-")
        # createdAt 2026-06-01, lastUpdatedAt 2026-06-03(本地毫秒时间戳)
        import datetime as _dt
        def ms(y, mo, dd):
            return int(_dt.datetime(y, mo, dd, 12, 0).timestamp() * 1000)
        self._headers(base, [{
            "composerId": "cmp1", "name": "跨天会话",
            "workspaceIdentifier": {"uri": {"fsPath": "/Users/x/proj-a"}},
            "createdAt": ms(2026, 6, 1), "lastUpdatedAt": ms(2026, 6, 3)}])
        cfg = {"sources": {"cursor": {"enabled": True, "app_support": base}}}
        out = cursor_col.collect(cfg, "2000-01-01")
        by_date = {e["date"]: e for e in out}
        self.assertEqual(set(by_date), {"2026-06-01", "2026-06-03"})   # 开始日 + 最后活跃日
        self.assertEqual(by_date["2026-06-01"]["project"], "proj-a")
        self.assertTrue(all("cmp1" in e["id"] for e in out))

    def test_same_day_session_single_entry(self):
        base = tempfile.mkdtemp(prefix="loom-cur-")
        import datetime as _dt
        t = int(_dt.datetime(2026, 6, 1, 12, 0).timestamp() * 1000)
        self._headers(base, [{"composerId": "c2", "name": "当天会话",
                              "workspaceIdentifier": {"uri": {"fsPath": "/Users/x/p"}},
                              "createdAt": t, "lastUpdatedAt": t + 3600000}])
        cfg = {"sources": {"cursor": {"enabled": True, "app_support": base}}}
        out = cursor_col.collect(cfg, "2000-01-01")
        self.assertEqual(len(out), 1)   # 同一天只出一条


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

    def test_numstat_shaped_body_line_not_misparsed(self):
        # 正文里含 numstat 样式行(粘贴的 diff/表)——不该被当成文件,也不该截断正文
        env = dict(os.environ, GIT_AUTHOR_NAME="tester", GIT_AUTHOR_EMAIL="me@test.dev",
                   GIT_COMMITTER_NAME="tester", GIT_COMMITTER_EMAIL="me@test.dev")
        def g(*a):
            subprocess.run(["git", "-C", self.repo, *a], check=True, env=env, capture_output=True)
        with open(os.path.join(self.repo, "c.txt"), "w") as f:
            f.write("z\n")
        g("add", "-A")
        msg = "fix: 见下表\n\n10\t5\tfoo/bar\n真正的正文结论在最后一行"
        g("commit", "-q", "-m", msg)
        out = git_col.collect(self.cfg, "2000-01-01")
        e = [x for x in out if x["summary"] == "fix: 见下表"][0]
        self.assertEqual(e["detail"]["files"], 1)          # 只有真实改的 c.txt,非正文里的 foo/bar
        self.assertEqual({f["path"] for f in e["detail"]["file_list"]}, {"c.txt"})
        self.assertIn("真正的正文结论在最后一行", e["detail"]["body"])   # 正文没被截断
        self.assertIn("10\t5\tfoo/bar", e["detail"]["body"])           # 正文里的表格行保留

    def test_filters_by_identity(self):
        cfg = {"repos": [self.repo], "identities": {"emails": ["other@x"], "names": []}}
        self.assertEqual(git_col.collect(cfg, "2000-01-01"), [])  # 非本人 → 不抓

    def test_norm_path_resolves_renames(self):
        self.assertEqual(git_col._norm_path("old.txt => new.txt"), "new.txt")
        self.assertEqual(git_col._norm_path("dir/{a => b}/x.txt"), "dir/b/x.txt")
        self.assertEqual(git_col._norm_path("plain.txt"), "plain.txt")

    def _g(self, *a):
        env = dict(os.environ, GIT_AUTHOR_NAME="tester", GIT_AUTHOR_EMAIL="me@test.dev",
                   GIT_COMMITTER_NAME="tester", GIT_COMMITTER_EMAIL="me@test.dev")
        subprocess.run(["git", "-C", self.repo, *a], check=True, env=env, capture_output=True)

    def test_rename_commit_stores_new_path_not_arrow(self):
        self._g("mv", "a.txt", "a_renamed.txt")
        self._g("commit", "-q", "-m", "refactor: 改名")
        e = [x for x in git_col.collect(self.cfg, "2000-01-01")
             if x["summary"] == "refactor: 改名"][0]
        paths = {f["path"] for f in e["detail"]["file_list"]}
        self.assertIn("a_renamed.txt", paths)
        self.assertFalse(any("=>" in p for p in paths))   # 不再把 'old => new' 整个当路径

    def test_distinct_same_subject_same_day_both_kept(self):
        for name, txt in (("w1.txt", "a\n"), ("w2.txt", "a\nb\nc\n")):  # 改动量不同
            with open(os.path.join(self.repo, name), "w") as f:
                f.write(txt)
            self._g("add", "-A")
            self._g("commit", "-q", "-m", "wip")       # 同一天同标题的两个真实提交
        out = [x for x in git_col.collect(self.cfg, "2000-01-01") if x["summary"] == "wip"]
        self.assertEqual(len(out), 2)                  # 去重按改动量区分 → 都保留

    def test_collects_commits_from_git_worktree(self):
        wt = tempfile.mkdtemp(prefix="loom-worktree-")
        os.rmdir(wt)
        self._g("worktree", "add", "-q", "-b", "worktree-test", wt)
        env = dict(os.environ, GIT_AUTHOR_NAME="tester", GIT_AUTHOR_EMAIL="me@test.dev",
                   GIT_COMMITTER_NAME="tester", GIT_COMMITTER_EMAIL="me@test.dev")
        with open(os.path.join(wt, "worktree.txt"), "w", encoding="utf-8") as f:
            f.write("from worktree\n")
        subprocess.run(["git", "-C", wt, "add", "worktree.txt"], check=True,
                       env=env, capture_output=True)
        subprocess.run(["git", "-C", wt, "commit", "-q", "-m", "feat: worktree commit"],
                       check=True, env=env, capture_output=True)

        cfg = {"repos": [wt],
               "identities": {"emails": ["me@test.dev"], "names": []}}
        result = git_col.collect_diagnostic(cfg, "2000-01-01")
        self.assertEqual(result["errors"], [])
        self.assertIn("feat: worktree commit", {e["summary"] for e in result["entries"]})
        self.assertTrue(os.path.isfile(os.path.join(wt, ".git")))  # worktree 的 .git 是文件

        both = dict(cfg, repos=[self.repo, wt])
        deduped = git_col.collect_diagnostic(both, "2000-01-01")
        matched = [e for e in deduped["entries"] if e["summary"] == "feat: worktree commit"]
        self.assertEqual(len(matched), 1)              # 主仓 + worktree 不重复入库
        self.assertEqual(matched[0]["project"], os.path.basename(self.repo))

    def test_collect_diagnostic_rejects_bare_repo(self):
        bare = tempfile.mkdtemp(prefix="loom-bare-")
        subprocess.run(["git", "-C", bare, "init", "--bare", "-q"], check=True,
                       capture_output=True)
        cfg = {"repos": [bare],
               "identities": {"emails": ["me@test.dev"], "names": []}}
        result = git_col.collect_diagnostic(cfg, "2000-01-01")
        self.assertEqual(result["entries"], [])
        self.assertTrue(result["errors"])


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

    def test_all_user_questions_indexed_not_just_opening(self):
        # 整段对话的话题都进 body(可检索),不止开场那句
        proj = os.path.join(self.root, "-Users-x-proj-z")
        lines = [
            {"cwd": "/Users/x/proj-z", "timestamp": "2026-06-07T09:00:00Z", "type": "user",
             "message": {"content": "先帮我搭个归因管道"}},
            {"timestamp": "2026-06-07T09:30:00Z", "type": "assistant", "message": {"content": "ok"}},
            {"timestamp": "2026-06-07T10:00:00Z", "type": "user",
             "message": {"content": "顺便排查一下 acme 作弊订单"}},
        ]
        with open(os.path.join(proj, "sid-body.jsonl"), "w", encoding="utf-8") as f:
            for d in lines:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        e = [x for x in claude_col.collect(self.cfg, "2000-01-01") if "sid-body" in x["id"]][0]
        self.assertTrue(e["summary"].startswith("先帮我搭"))          # 开场做标题
        self.assertIn("acme 作弊订单", e["detail"]["body"])         # 后面的话题也进 body(可搜)
        self.assertIn("归因管道", e["detail"]["body"])

    def test_skips_compaction_summary_as_opening(self):
        # 压缩续接摘要不该被当成"当天首问",应取下一句真实提问
        proj = os.path.join(self.root, "-Users-x-proj-z")
        lines = [
            {"cwd": "/Users/x/proj-z", "timestamp": "2026-06-05T09:00:00Z", "type": "user",
             "message": {"content": "This session is being continued from a previous "
                         "conversation that ran out of context. Summary: ..."}},
            {"cwd": "/Users/x/proj-z", "timestamp": "2026-06-05T09:01:00Z", "type": "user",
             "message": {"content": "真实问题:帮我修 cohort 口径"}},
        ]
        with open(os.path.join(proj, "sid-compact.jsonl"), "w", encoding="utf-8") as f:
            for d in lines:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        e = [x for x in claude_col.collect(self.cfg, "2000-01-01")
             if "sid-compact" in x["id"]][0]
        self.assertTrue(e["detail"]["opening"].startswith("真实问题"))   # 跳过摘要取真问题
        self.assertNotIn("continued from", e["detail"]["opening"])

    def test_timestamps_converted_to_local(self):
        # claude 原始是 UTC 的 Z;入库后统一成本地朴素 ISO,不残留 Z(跨源日期口径一致)
        e = claude_col.collect(self.cfg, "2000-01-01")[0]
        self.assertNotIn("Z", e["ts"])
        self.assertNotIn("Z", e["detail"]["start"])
        self.assertEqual(len(e["ts"]), 19)
        self.assertEqual(e["date"], e["ts"][:10])

    def test_multiday_session_split_per_day(self):
        # 跨天续聊:同一 session 每个有活动的天各出一条,带那天的首问
        proj = os.path.join(self.root, "-Users-x-proj-z")
        # 用早上的 UTC 时间避免本地时区把日期推到前后天(09:00Z 在 UTC-9~+14 都还是当天)
        lines = [
            {"cwd": "/Users/x/proj-z", "timestamp": "2026-06-01T09:00:00Z",
             "type": "user", "message": {"content": "第一天:搭归因管道"}},
            {"timestamp": "2026-06-01T10:00:00Z", "type": "assistant", "message": {"content": "ok"}},
            {"timestamp": "2026-06-02T09:30:00Z", "type": "user",
             "message": {"content": "第二天:继续修 cohort 口径"}},
            {"timestamp": "2026-06-02T11:00:00Z", "type": "assistant", "message": {"content": "ok"}},
            {"type": "ai-title", "title": "归因管道"},
        ]
        with open(os.path.join(proj, "sid-multi.jsonl"), "w", encoding="utf-8") as f:
            for d in lines:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        out = [e for e in claude_col.collect(self.cfg, "2000-01-01")
               if "sid-multi" in e["id"]]
        by_date = {e["date"]: e for e in out}
        self.assertEqual(set(by_date), {"2026-06-01", "2026-06-02"})     # 拆成两天
        self.assertEqual(by_date["2026-06-01"]["summary"], "归因管道")     # 首日用整会话标题
        self.assertTrue(by_date["2026-06-02"]["summary"].startswith("第二天"))  # 续日用当天首问
        self.assertEqual(by_date["2026-06-02"]["detail"]["user"], 1)     # 只算当天的消息

    def test_captures_git_branch_and_pr(self):
        # 抓 Claude Code 记的 gitBranch / prNumber,用于按分支缝到同期提交
        proj = os.path.join(self.root, "-Users-x-proj-z")
        lines = [
            {"cwd": "/Users/x/proj-z", "timestamp": "2026-06-10T09:00:00Z", "type": "user",
             "gitBranch": "feat/attribution", "message": {"content": "在这条分支上改归因"}},
            {"timestamp": "2026-06-10T09:05:00Z", "type": "user", "gitBranch": "feat/attribution",
             "prNumber": 42, "prUrl": "https://x/pr/42", "prRepository": "org/repo",
             "message": {"content": "开了 PR"}},
        ]
        with open(os.path.join(proj, "sid-branch.jsonl"), "w", encoding="utf-8") as f:
            for d in lines:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        e = [x for x in claude_col.collect(self.cfg, "2000-01-01")
             if "sid-branch" in x["id"]][0]
        self.assertEqual(e["detail"]["branch"], "feat/attribution")   # 当天主分支
        self.assertEqual(e["detail"]["pr"]["number"], 42)             # 关联 PR
        self.assertEqual(e["detail"]["pr"]["url"], "https://x/pr/42")

    def test_no_branch_field_when_absent(self):
        # 原始无 gitBranch → detail 不塞 branch 键(不污染旧数据/无分支会话)
        e = claude_col.collect(self.cfg, "2000-01-01")[0]
        self.assertNotIn("branch", e["detail"])
        self.assertNotIn("pr", e["detail"])


class PiCollectorTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="loom-pi-")
        project_dir = os.path.join(self.root, "--Users-x-pi-project--")
        os.makedirs(project_dir)
        self.fp = os.path.join(project_dir, "2026-06-01T00-00-00Z_sid-pi.jsonl")
        rows = [
            {"type": "session", "version": 3, "id": "sid-pi",
             "timestamp": "2026-06-01T09:00:00Z", "cwd": "/Users/x/pi-project"},
            {"type": "message", "id": "u0", "parentId": None,
             "timestamp": "2026-06-01T09:00:00Z",
             "message": {"role": "user", "content": "/model"}},
            {"type": "message", "id": "u1", "parentId": "u0",
             "timestamp": "2026-06-01T09:01:00Z",
             "message": {"role": "user", "content": [
                 {"type": "text", "text": "第一天实现 pi 采集器"},
                 {"type": "image", "data": "base64", "mimeType": "image/png"}]}},
            {"type": "message", "id": "a1", "parentId": "u1",
             "timestamp": "2026-06-01T10:00:00Z",
             "message": {"role": "assistant", "content": [
                 {"type": "text", "text": "已实现"}]}},
            {"type": "message", "id": "u2", "parentId": "a1",
             "timestamp": "2026-06-02T09:00:00Z",
             "message": {"role": "user", "content": "第二天补分支与测试"}},
            {"type": "message", "id": "a2", "parentId": "u2",
             "timestamp": "2026-06-02T10:00:00Z",
             "message": {"role": "assistant", "content": "完成"}},
            {"type": "session_info", "id": "info", "parentId": "a2",
             "timestamp": "2026-06-02T10:01:00Z", "name": "pi 会话采集"},
        ]
        with open(self.fp, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.write("{损坏行\n")
        self.cfg = {"sources": {"pi": {"enabled": True,
                                                "sessions_dir": self.root}}}

    def test_collects_named_tree_session_by_real_message_day(self):
        out = pi_col.collect(self.cfg, "2000-01-01")
        by_date = {entry["date"]: entry for entry in out}
        self.assertEqual(set(by_date), {"2026-06-01", "2026-06-02"})
        self.assertEqual(by_date["2026-06-01"]["summary"], "pi 会话采集")
        self.assertEqual(by_date["2026-06-01"]["project"], "pi-project")
        self.assertEqual(by_date["2026-06-01"]["detail"]["opening"],
                         "第一天实现 pi 采集器")
        self.assertNotIn("/model", by_date["2026-06-01"]["detail"]["body"])
        self.assertTrue(by_date["2026-06-02"]["summary"].startswith("第二天"))
        self.assertEqual(by_date["2026-06-02"]["detail"]["asst"], 1)
        self.assertEqual(by_date["2026-06-02"]["ref"], self.fp)

    def test_since_and_disabled(self):
        out = pi_col.collect(self.cfg, "2026-06-02")
        self.assertEqual([entry["date"] for entry in out], ["2026-06-02"])
        self.assertEqual(pi_col.collect({"sources": {"pi": {"enabled": False}}},
                                        "2000-01-01"), [])


class OpenCodeCollectorTest(unittest.TestCase):
    @staticmethod
    def _ms(year, month, day, hour=9):
        import datetime
        return int(datetime.datetime(year, month, day, hour).timestamp() * 1000)

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="loom-opencode-")
        self._legacy()
        self._sqlite()
        self.cfg = {"sources": {"opencode": {"enabled": True,
                                                      "data_dir": self.root}}}

    def _legacy(self):
        storage = os.path.join(self.root, "storage")
        sid, mid = "ses_legacy", "msg_legacy_user"
        session_dir = os.path.join(storage, "session", "project-a")
        message_dir = os.path.join(storage, "message", sid)
        part_dir = os.path.join(storage, "part", mid)
        os.makedirs(session_dir); os.makedirs(message_dir); os.makedirs(part_dir)
        with open(os.path.join(session_dir, sid + ".json"), "w", encoding="utf-8") as f:
            json.dump({"id": sid, "directory": "/Users/x/legacy-project",
                       "title": "旧版 JSON 会话",
                       "time": {"created": self._ms(2026, 6, 1),
                                "updated": self._ms(2026, 6, 1)},
                       "summary": {"additions": 3, "deletions": 1, "files": 1}}, f)
        with open(os.path.join(message_dir, mid + ".json"), "w", encoding="utf-8") as f:
            json.dump({"id": mid, "sessionID": sid, "role": "user",
                       "time": {"created": self._ms(2026, 6, 1)}}, f)
        with open(os.path.join(part_dir, "prt_real.json"), "w", encoding="utf-8") as f:
            json.dump({"type": "text", "text": "读取旧版 OpenCode 历史"}, f,
                      ensure_ascii=False)

    def _sqlite(self):
        db = os.path.join(self.root, "opencode.db")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE session (id TEXT, directory TEXT, title TEXT, "
                     "time_created INTEGER, time_updated INTEGER, summary_additions INTEGER, "
                     "summary_deletions INTEGER, summary_files INTEGER)")
        conn.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, "
                     "data TEXT)")
        conn.execute("CREATE TABLE part (id TEXT, message_id TEXT, session_id TEXT, "
                     "time_created INTEGER, data TEXT)")
        sid = "ses_sqlite"
        conn.execute("INSERT INTO session VALUES (?,?,?,?,?,?,?,?)",
                     (sid, "/Users/x/sqlite-project", "SQLite 会话采集",
                      self._ms(2026, 6, 2), self._ms(2026, 6, 3), 12, 2, 4))
        rows = [
            ("msg_u1", sid, self._ms(2026, 6, 2),
             {"role": "user", "time": {"created": self._ms(2026, 6, 2)}}),
            ("msg_a1", sid, self._ms(2026, 6, 2, 10),
             {"role": "assistant", "time": {"created": self._ms(2026, 6, 2, 10)}}),
            ("msg_u2", sid, self._ms(2026, 6, 3),
             {"role": "user", "time": {"created": self._ms(2026, 6, 3)}}),
        ]
        for mid, session_id, created, data in rows:
            conn.execute("INSERT INTO message VALUES (?,?,?,?)",
                         (mid, session_id, created, json.dumps(data)))
        parts = [
            ("prt_synthetic", "msg_u1", self._ms(2026, 6, 2),
             {"type": "text", "text": "系统注入内容", "synthetic": True}),
            ("prt_u1", "msg_u1", self._ms(2026, 6, 2),
             {"type": "text", "text": "[analyze-mode]\n实现 SQLite 采集"}),
            ("prt_u2", "msg_u2", self._ms(2026, 6, 3),
             {"type": "text", "text": "继续补兼容测试"}),
        ]
        for pid, mid, created, data in parts:
            conn.execute("INSERT INTO part VALUES (?,?,?,?,?)",
                         (pid, mid, sid, created, json.dumps(data, ensure_ascii=False)))
        conn.commit(); conn.close()

    def test_merges_sqlite_and_legacy_json_and_splits_days(self):
        out = opencode_col.collect(self.cfg, "2000-01-01")
        by_id = {entry["id"]: entry for entry in out}
        self.assertIn("opencode:ses_legacy:2026-06-01", by_id)
        self.assertIn("opencode:ses_sqlite:2026-06-02", by_id)
        self.assertIn("opencode:ses_sqlite:2026-06-03", by_id)
        legacy = by_id["opencode:ses_legacy:2026-06-01"]
        self.assertEqual(legacy["summary"], "旧版 JSON 会话")
        self.assertEqual(legacy["detail"]["opening"], "读取旧版 OpenCode 历史")
        first = by_id["opencode:ses_sqlite:2026-06-02"]
        self.assertEqual(first["summary"], "SQLite 会话采集")
        self.assertEqual(first["project"], "sqlite-project")
        self.assertNotIn("系统注入内容", first["detail"]["body"])
        self.assertIn("实现 SQLite 采集", first["detail"]["body"])
        self.assertEqual(first["detail"]["files"], 4)
        second = by_id["opencode:ses_sqlite:2026-06-03"]
        self.assertEqual(second["summary"], "继续补兼容测试")
        self.assertEqual(second["detail"]["user"], 1)

    def test_since_and_disabled(self):
        out = opencode_col.collect(self.cfg, "2026-06-03")
        self.assertEqual([entry["date"] for entry in out], ["2026-06-03"])
        self.assertEqual(opencode_col.collect(
            {"sources": {"opencode": {"enabled": False}}}, "2000-01-01"), [])


class CodeBuddyCollectorTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="loom-codebuddy-")
        self.app_support = os.path.join(self.root, "CodeBuddy")
        self.extension_data = os.path.join(self.root, "CodeBuddyExtension", "Data")
        os.makedirs(self.app_support)

        self.cid = "craft-session-001"
        self.team_cid = "team-session-001"
        db = os.path.join(self.app_support, "codebuddy-sessions.vscdb")
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
            conn.execute("INSERT INTO ItemTable(key,value) VALUES (?,?)", (
                f"session:{self.cid}", json.dumps({
                    "conversationId": self.cid, "cwd": "/Users/test/data-marketing",
                    "title": "元数据标题", "createdAt": "2026-07-06T10:00:00",
                }, ensure_ascii=False)))

        history = os.path.join(
            self.extension_data, "user-a", "CodeBuddyIDE", "profile-a",
            "history", "workspace-a")
        os.makedirs(history)
        with open(os.path.join(history, "index.json"), "w", encoding="utf-8") as f:
            json.dump({"conversations": [
                {"id": self.cid, "type": "craft", "name": "归因模型修整",
                 "lastMessageAt": "2026-07-07T12:00:00"},
                {"id": self.team_cid, "type": "team-member", "name": "内部子任务",
                 "lastMessageAt": "2026-07-07T12:01:00"},
            ]}, f, ensure_ascii=False)

        self._write_conversation(history, self.cid, [
            ("user-message-001", "user", "2026-07-06T10:00:00",
             "<user_info>仓库和系统上下文不应入库</user_info>"
             "<user_query>修复归因模型</user_query>"),
            ("assistant-msg-001", "assistant", "2026-07-06T10:05:00", "已处理"),
            ("user-message-002", "user", "2026-07-07T11:30:00",
             "<user_query>继续补测试</user_query>"),
        ], broken_id="broken-message-001")
        self._write_conversation(history, self.team_cid, [
            ("team-message-001", "user", "2026-07-07T12:01:00",
             "<user_query>这条 team-member 不能进入台账</user_query>"),
        ])
        self.cfg = {"sources": {"codebuddy": {
            "enabled": True, "app_support": self.app_support,
            "extension_data": self.extension_data,
        }}}

    @staticmethod
    def _write_conversation(history, cid, rows, broken_id=None):
        conv_dir = os.path.join(history, cid)
        msg_dir = os.path.join(conv_dir, "messages")
        os.makedirs(msg_dir)
        pointers = []
        for mid, role, created_at, text in rows:
            pointers.append({"id": mid, "role": role, "type": "message", "isComplete": True})
            envelope = {"role": role, "content": [{"type": "text", "text": text}]}
            outer = {"role": role, "createdAt": created_at,
                     "message": json.dumps(envelope, ensure_ascii=False)}
            with open(os.path.join(msg_dir, mid + ".json"), "w", encoding="utf-8") as f:
                json.dump(outer, f, ensure_ascii=False)
        if broken_id:
            pointers.append({"id": broken_id, "role": "user", "type": "message"})
            with open(os.path.join(msg_dir, broken_id + ".json"), "w", encoding="utf-8") as f:
                f.write("{损坏的历史消息")
        with open(os.path.join(conv_dir, "index.json"), "w", encoding="utf-8") as f:
            json.dump({"messages": pointers, "requests": []}, f, ensure_ascii=False)

    def test_collects_craft_user_queries_by_day_and_reports_partial_history(self):
        result = codebuddy_col.collect_diagnostic(self.cfg, "2000-01-01")
        self.assertEqual(result["status"], "partial")               # 一条坏消息不拖垮其余历史
        self.assertTrue(result["errors"])
        self.assertEqual(result["sessions"], 1)                     # team-member 不算主会话
        by_date = {e["date"]: e for e in result["entries"]}
        self.assertEqual(set(by_date), {"2026-07-06", "2026-07-07"})

        first = by_date["2026-07-06"]
        self.assertEqual(first["id"], f"codebuddy:{self.cid}:2026-07-06")
        self.assertEqual(first["project"], "data-marketing")       # session DB 补工作区
        self.assertEqual(first["summary"], "归因模型修整")          # 首日采用会话标题
        self.assertEqual(first["detail"]["opening"], "修复归因模型")
        self.assertNotIn("user_info", first["detail"]["body"])
        self.assertNotIn("系统上下文", first["detail"]["body"])

        second = by_date["2026-07-07"]
        self.assertEqual(second["summary"], "继续补测试")            # 续日使用当天首问
        self.assertNotIn("team-member", json.dumps(result["entries"], ensure_ascii=False))
        self.assertNotIn("内部子任务", json.dumps(result["entries"], ensure_ascii=False))

    def test_collect_contract_since_filter_and_missing_history(self):
        entries = codebuddy_col.collect(self.cfg, "2026-07-07")
        self.assertIsInstance(entries, list)                         # 保持通用 collector 契约
        self.assertEqual([e["date"] for e in entries], ["2026-07-07"])

        missing = {"sources": {"codebuddy": {
            "enabled": True,
            "app_support": os.path.join(self.root, "missing-app"),
            "extension_data": os.path.join(self.root, "missing-history"),
        }}}
        result = codebuddy_col.collect_diagnostic(missing, "2000-01-01")
        self.assertEqual(result["status"], "success")               # 未安装/无历史是 0 条，不是假故障
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["sessions"], 0)


class DocsCollectorTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="loom-docsrepo-")
        os.makedirs(os.path.join(self.repo, "docs"))
        os.makedirs(os.path.join(self.repo, "node_modules", "pkg"))
        with open(os.path.join(self.repo, "README.md"), "w", encoding="utf-8") as f:
            f.write("# 项目说明\n\n## 背景\n正文\n## 用法\n")
        with open(os.path.join(self.repo, "docs", "design.md"), "w", encoding="utf-8") as f:
            f.write("# 归因设计\n细节")
        with open(os.path.join(self.repo, "node_modules", "pkg", "README.md"), "w") as f:
            f.write("# 第三方,不该被索引")
        self.cfg = {"sources": {"docs": {"enabled": True}}, "repos": [self.repo]}

    def test_indexes_md_with_title_outline_backlink(self):
        out = docs_col.collect(self.cfg, "2000-01-01")
        by_rel = {e["detail"]["path"]: e for e in out}
        self.assertIn("README.md", by_rel)
        self.assertIn("docs/design.md", by_rel)
        self.assertNotIn("node_modules/pkg/README.md", str(by_rel))  # 跳过 vendor
        r = by_rel["README.md"]
        self.assertEqual(r["summary"], "项目说明")            # 取 H1
        self.assertIn("背景", r["detail"]["headings"])         # 大纲
        self.assertEqual(r["kind"], "doc")
        self.assertEqual(r["tool"], "docs")
        self.assertTrue(r["ref"].endswith("README.md"))        # 回链到原文件
        self.assertTrue(os.path.isabs(r["ref"]))

    def test_disabled(self):
        self.assertEqual(docs_col.collect({"sources": {"docs": {"enabled": False}}, "repos": []},
                                          "2000-01-01"), [])


class NotesCollectorTest(unittest.TestCase):
    def setUp(self):
        from loom import intake
        self.cfg = {"vault": {"dir": tempfile.mkdtemp(prefix="loom-vault-")},
                    "sources": {"notes": {"enabled": True}}, "redact": True}
        # 一篇手动加进 attribution 的文档 + 一个 _archive 镜像(应被跳过)
        src = tempfile.mkdtemp()
        with open(os.path.join(src, "foo.md"), "w", encoding="utf-8") as f:
            f.write("# 手动加的归因笔记\n口径对齐问题。")
        intake.ingest(self.cfg, [os.path.join(src, "foo.md")], to="attribution", tags="applovin")
        adir = os.path.join(config.notes_dir(self.cfg), "_archive", "somerepo")
        os.makedirs(adir)
        with open(os.path.join(adir, "mirror.md"), "w", encoding="utf-8") as f:
            f.write("---\ntitle: 镜像\n---\n仓文档镜像,不该被 notes 源重复索引")

    def test_indexes_notes_skips_archive(self):
        out = notes_col.collect(self.cfg, "2000-01-01")
        paths = {e["detail"]["path"] for e in out}
        self.assertIn("attribution/foo.md", paths)
        self.assertNotIn("_archive/somerepo/mirror.md", str(paths))   # 跳过档案镜像
        e = next(e for e in out if e["detail"]["path"] == "attribution/foo.md")
        self.assertEqual(e["kind"], "note")
        self.assertEqual(e["project"], "attribution")     # 类目 = project(可 --project 过滤)
        self.assertEqual(e["summary"], "手动加的归因笔记")  # 取 frontmatter title
        self.assertIn("口径对齐", e["detail"]["content"])   # 全文可搜

    def test_disabled(self):
        self.assertEqual(notes_col.collect({"vault": self.cfg["vault"],
                                            "sources": {"notes": {"enabled": False}}},
                                           "2000-01-01"), [])

    def test_date_from_name(self):
        self.assertEqual(notes_col._date_from_name("check_2026_03_12_gap.sql"), "2026-03-12")
        self.assertEqual(notes_col._date_from_name("dryrun_material_20260702.sql"), "2026-07-02")
        self.assertEqual(notes_col._date_from_name("bf_channel_impact_202605.sql"), "2026-05-01")
        self.assertIsNone(notes_col._date_from_name("bf_ads_vs_dws_recon.sql"))   # 无日期→None(退回mtime)
        self.assertIsNone(notes_col._date_from_name("260129_bf.sql"))             # YYMMDD 太歧义,不认

    def test_code_file_dated_from_name_not_mtime(self):
        from loom import intake
        src = tempfile.mkdtemp()
        with open(os.path.join(src, "cost_split_dryrun_ms_20260501.sql"), "w") as f:
            f.write("SELECT 1")
        intake.ingest(self.cfg, [os.path.join(src, "cost_split_dryrun_ms_20260501.sql")],
                      to="scratch")
        e = next(e for e in notes_col.collect(self.cfg, "2000-01-01")
                 if "cost_split_dryrun" in e["detail"]["path"])
        self.assertEqual(e["date"], "2026-05-01")   # 用文件名日期,而非入库当天 mtime


class DatasetTest(unittest.TestCase):
    def setUp(self):
        from loom import dataset
        self.dataset = dataset
        self.cfg = {"vault": {"dir": tempfile.mkdtemp(prefix="loom-vault-")}, "redact": True}
        self.src = tempfile.mkdtemp(prefix="loom-src-")

    def _mk(self, name, content):
        p = os.path.join(self.src, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_csv_datacard_and_local_raw_and_code(self):
        csvp = self._mk("cost.csv", "ad_id,cost,day\nA1,10.5,2026-01-01\nA2,20,2026-01-02\n")
        sqlp = self._mk("q.sql", "SELECT ad_id, cost FROM t WHERE token='sk_live_ABCDEFGHIJ1234567'")
        dest, msg = self.dataset.add(self.cfg, csvp, to="ad-kill",
                                     code=[sqlp], used_by="斩杀报告", tags="cost")
        self.assertTrue(dest.endswith(".card.md"))
        card = _read(dest)
        self.assertIn("type: loom-datacard", card)
        self.assertIn("| cost | float |", card)          # 类型推断
        self.assertIn("| day | date |", card)
        self.assertIn("rows: 2 · cols: 3", card)
        self.assertIn("used_by: [[斩杀报告]]", card)       # 文档关联
        self.assertIn("produced_by: [q.sql]", card)       # 代码关联
        self.assertIn("```sql", card)                     # 代码嵌入(可检索)
        self.assertIn("已打码", card)                      # 代码里的密钥被抹
        nd = config.notes_dir(self.cfg)
        self.assertTrue(os.path.exists(os.path.join(nd, "ad-kill", "_data", "cost.csv")))  # 原始入 _data
        self.assertTrue(os.path.exists(os.path.join(nd, "ad-kill", "q.sql")))              # 代码存主题目录

    def test_code_can_be_python(self):
        csvp = self._mk("d.csv", "a,b\n1,2\n")
        pyp = self._mk("pull.py", "import pandas as pd\ndf = pd.read_sql('...', conn)")
        dest, _ = self.dataset.add(self.cfg, csvp, to="x", code=[pyp])
        card = _read(dest)
        self.assertIn("```python", card)                  # 按 .py 高亮
        self.assertIn("produced_by: [pull.py]", card)

    def test_source_vs_derived_and_lineage(self):
        raw = self._mk("raw_events.csv", "id,v\n1,2\n")
        proc = self._mk("daily_agg.csv", "day,total\n2026-01-01,5\n")
        tp = self._mk("agg.py", "df.groupby('day').sum()")
        # 原始(拉取):无 --from → kind=source
        d1, _ = self.dataset.add(self.cfg, raw, to="t", code=[self._mk("q.sql", "SELECT *")])
        self.assertIn("kind: source", _read(d1))
        # 派生(本地加工):有 --from → kind=derived + 血缘
        d2, _ = self.dataset.add(self.cfg, proc, to="t", frm=[raw], code=[tp])
        card = _read(d2)
        self.assertIn("kind: derived", card)
        self.assertIn("inputs: [[[raw_events]]]", card)   # 上游血缘链
        self.assertIn("produced_by: [agg.py]", card)
        self.assertIn("**派生数据**", card)
        self.assertIn("[[raw_events]] —", card)            # 血缘一行

    def test_many_to_many_lineage(self):
        # 多输入 + 多代码 → 一个产出;多产出各自成卡共享血缘
        ins = [self._mk("in_a.csv", "x\n1\n"), self._mk("in_b.csv", "y\n2\n")]
        codes = [self._mk("e.sql", "SELECT 1"), self._mk("t.py", "merge()")]
        out1 = self._mk("out1.csv", "a\n1\n")
        out2 = self._mk("out2.csv", "b\n2\n")
        for out in (out1, out2):
            d, _ = self.dataset.add(self.cfg, out, to="t", frm=ins, code=codes)
            card = _read(d)
            self.assertIn("inputs: [[[in_a]], [[in_b]]]", card)     # 多输入
            self.assertIn("produced_by: [e.sql, t.py]", card)       # 多代码
            self.assertIn("kind: derived", card)

    def test_explicit_kind_override(self):
        p = self._mk("m.csv", "a\n1\n")
        d, _ = self.dataset.add(self.cfg, p, to="t", kind="derived")   # 强制 derived 即使无 from
        self.assertIn("kind: derived", _read(d))

    def test_xlsx_inlinestr_columns_and_preamble_skip(self):
        import zipfile
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        def cell(r, txt, num=False):
            return (f'<c r="{r}"><v>{txt}</v></c>' if num
                    else f'<c r="{r}" t="inlineStr"><is><t>{txt}</t></is></c>')
        sheet = (f'<worksheet xmlns="{ns}"><sheetData>'
                 f'<row r="1">{cell("A1", "报表标题(单格)")}</row>'          # preamble
                 f'<row r="2">{cell("A2", "day")}{cell("B2", "total")}</row>'  # 真表头
                 f'<row r="3">{cell("A3", "2026-01-01")}{cell("B3", 120, True)}</row>'
                 f'<row r="4">{cell("A4", "2026-01-02")}{cell("B4", 95, True)}</row>'
                 '</sheetData></worksheet>')
        p = os.path.join(self.src, "报表.xlsx")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("xl/worksheets/sheet1.xml", sheet)
        dest, _ = self.dataset.add(self.cfg, p, to="t")
        card = _read(dest)
        self.assertIn("| day |", card)          # inlineStr 表头解析
        self.assertIn("| total | int |", card)  # 数值列 + 列位置对齐
        self.assertIn("rows: 2", card)          # 跳过标题行,数据 2 行
        self.assertNotIn("报表标题", card.split("## 列")[1] if "## 列" in card else card)

    def test_tsv_parsed_with_tab(self):
        p = self._mk("t.tsv", "ad_id\tcost\tday\nA1\t10\t2026-01-01\n")
        dest, _ = self.dataset.add(self.cfg, p, to="t")
        card = _read(dest)
        self.assertIn("cols: 3", card)            # 制表符分列 → 3 列,而非塌成 1 列
        self.assertIn("| ad_id |", card)
        self.assertIn("| cost | int |", card)

    def test_xlsx_date_serial_restored(self):
        import zipfile
        from datetime import datetime as _dt
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        d1, d2 = _dt(2026, 1, 1), _dt(2026, 1, 2)
        s1 = (d1 - _dt(1899, 12, 30)).days        # 从目标日期反推序列号,自洽
        s2 = (d2 - _dt(1899, 12, 30)).days
        styles = (f'<styleSheet xmlns="{ns}"><cellXfs count="2">'
                  '<xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>')  # 下标1=日期格式

        def c(r, v, s=None):
            sa = f' s="{s}"' if s is not None else ""
            return f'<c r="{r}"{sa}><v>{v}</v></c>'
        istr = lambda r, t: f'<c r="{r}" t="inlineStr"><is><t>{t}</t></is></c>'
        sheet = (f'<worksheet xmlns="{ns}"><sheetData>'
                 f'<row r="1">{istr("A1", "day")}{istr("B1", "n")}</row>'
                 f'<row r="2">{c("A2", s1, 1)}{c("B2", 5)}</row>'
                 f'<row r="3">{c("A3", s2, 1)}{c("B3", 7)}</row>'
                 '</sheetData></worksheet>')
        p = os.path.join(self.src, "dates.xlsx")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("xl/styles.xml", styles)
            z.writestr("xl/worksheets/sheet1.xml", sheet)
        card = _read(self.dataset.add(self.cfg, p, to="t")[0])
        self.assertIn("| day | date |", card)     # 日期样式的序列号列 → 识别为 date
        self.assertIn("2026-01-01", card)          # 序列号还原成可读日期
        self.assertIn("| n | int |", card)         # 非日期数值列不受影响

    def test_sample_cell_newline_does_not_break_table(self):
        p = self._mk("multi.csv", 'name,note\nA,"第一行\n第二行"\n')  # 引号内嵌换行
        card = _read(self.dataset.add(self.cfg, p, to="t")[0])
        sample = card.split("## 前")[1]
        self.assertNotIn("\n第二行", sample)        # 换行被折叠,表格不塌
        self.assertIn("第一行 第二行", sample)

    def test_rejects_non_data(self):
        p = self._mk("note.md", "# hi")
        dest, msg = self.dataset.add(self.cfg, p, to="x")
        self.assertIsNone(dest)
        self.assertIn("非数据文件", msg)


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

    def test_topic_backlinks_injected(self):
        # 有主题映射的条目 → 日记里挂 [[主题]] 反向链接(Obsidian/Logseq 成图)
        from loom import topics
        for p in (topics._map_path(), topics._audit_path()):
            if os.path.exists(p):
                os.remove(p)
        topics.save_map({"git:1": ["素材归因", "None-Of-These"], "git:2": []})
        try:
            self._build([_entry("git:1", "2026-06-30", "p", "git", "commit", "改归因"),
                         _entry("git:2", "2026-06-30", "p", "git", "commit", "没打标")])
            body = _read(os.path.join(config.journal_dir(self.cfg), "2026-06-30.md"))
            self.assertIn("🏷 [[素材归因]]", body)      # 打了标的挂链
            # 没映射的那条不挂(它的行是"没打标",其后不应紧跟 🏷)
            self.assertNotIn("没打标  🏷", body)
        finally:
            if os.path.exists(topics._map_path()):
                os.remove(topics._map_path())

    def test_session_branch_and_pr_shown(self):
        # 会话的 git 分支 / PR 显示在日记 AI 会话行
        s = _entry("claude:b:2026-06-30", "2026-06-30", "p", "claude", "session", "改归因",
                   start="2026-06-30T09:00:00", end="2026-06-30T10:00:00",
                   branch="feat/attribution", pr={"number": 42, "url": "u", "repo": "r"})
        self._build([s])
        body = _read(os.path.join(config.journal_dir(self.cfg), "2026-06-30.md"))
        self.assertIn("feat/attribution", body)
        self.assertIn("PR #42", body)

    def test_data_and_code_notes_appear_in_journal(self):
        # 数据卡/代码(kind=note, tool=notes)按各自日期进当天日记的「📎 数据/代码/资料」区
        card = _entry("note:data/bv/x.card.md", "2026-06-30", "data", "notes", "note",
                      "BV 付费对比", path="data/bv/x.card.md")
        code = _entry("note:scratch/q.sql", "2026-06-30", "scratch", "notes", "note",
                      "作弊排查", path="scratch/q.sql")
        self._build([card, code,
                     _entry("git:1", "2026-06-30", "data", "git", "commit", "改了")])
        body = _read(os.path.join(config.journal_dir(self.cfg), "2026-06-30.md"))
        self.assertIn("📎 数据/代码/资料", body)
        self.assertIn("[数据卡] BV 付费对比", body)
        self.assertIn("[代码] 作弊排查", body)

    def test_undated_code_note_excluded_from_journal(self):
        # 无日期的代码笔记(dated=False,只有 mtime)不进日记(仍可检索)
        undated = _entry("note:scratch/q.sql", "2026-07-04", "scratch", "notes", "note",
                         "无日期查询", path="scratch/q.sql", dated=False)
        dated = _entry("note:data/x.card.md", "2026-06-30", "data", "notes", "note",
                       "数据卡", path="data/x.card.md", dated=True)
        self._build([undated, dated])
        jdir = config.journal_dir(self.cfg)
        self.assertFalse(os.path.exists(os.path.join(jdir, "2026-07-04.md")))  # 无日期→不建当天
        self.assertIn("数据卡", _read(os.path.join(jdir, "2026-06-30.md")))     # 有日期→进日记

    def test_dated_doc_in_journal_undated_excluded(self):
        # 有 git 日期的文档(dated=True)进当天「📄 文档」区;未提交/无日期的(dated=False)不进,仅检索
        dated = _entry("doc:p:design.md", "2026-06-30", "p", "docs", "doc", "架构设计文档",
                       path="design.md", repo="p", content="正文", dated=True)
        undated = _entry("doc:p:draft.md", "2026-06-30", "p", "docs", "doc", "未提交草稿",
                         path="draft.md", repo="p", content="草", dated=False)
        self._build([dated, undated])
        body = _read(os.path.join(config.journal_dir(self.cfg), "2026-06-30.md"))
        self.assertIn("📄 文档", body)
        self.assertIn("架构设计文档", body)          # 当天改过的文档进日记
        self.assertNotIn("未提交草稿", body)         # 无 git 日期的不塞

    def test_doc_fulltext_archived_survives_source_deletion(self):
        # doc 条目带全文,ref 指向不存在的文件(模拟源已删)→ 快照仍落 _archive(永不裁剪)
        doc = _entry("doc:proj:notes/x.md", "2026-06-01", "proj", "docs", "doc", "重要标题",
                     ref="/nonexistent/x.md", path="notes/x.md", repo="proj",
                     content="# 重要标题\n源删了也要留住的内容。")
        render.build(self.cfg, {doc["id"]: doc})
        arch = os.path.join(config.notes_dir(self.cfg), "_archive", "proj", "notes", "x.md")
        self.assertTrue(os.path.exists(arch))
        body = _read(arch)
        self.assertIn("源删了也要留住的内容", body)      # 全文进 vault(与是否进日记无关)
        self.assertIn("archived: true", body)

    def test_migrates_legacy_sentinel_content(self):
        jdir = config.journal_dir(self.cfg)
        os.makedirs(jdir, exist_ok=True)
        # 造一个旧版内联手写正文的 {date}.md
        with open(os.path.join(jdir, "2026-05-01.md"), "w", encoding="utf-8") as f:
            f.write("# 旧日志\n\n" + render.LEGACY_MARK + "\n\n迁移前写的字。\n")
        self._build([_entry("git:9", "2026-05-01", "p", "git", "commit", "x")])
        notes = _read(os.path.join(jdir, "2026-05-01.notes.md"))
        self.assertIn("迁移前写的字", notes)


class IntakeTest(unittest.TestCase):
    def setUp(self):
        from loom import intake
        self.intake = intake
        self.cfg = {"vault": {"dir": tempfile.mkdtemp(prefix="loom-vault-")}, "redact": True}
        self.src = tempfile.mkdtemp(prefix="loom-src-")

    def _mk(self, name, content):
        p = os.path.join(self.src, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_add_text_stamps_frontmatter_and_redacts(self):
        p = self._mk("我的 笔记.md", "# 归因排查\n\ntoken=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345\n正文")
        (dest, msg), = self.intake.ingest(self.cfg, [p], to="attribution", tags="applovin, cost")
        self.assertTrue(dest.endswith(".md"))
        self.assertIn("notes/attribution", dest.replace(os.sep, "/"))
        self.assertNotIn(" ", os.path.basename(dest))       # 文件名去空格
        body = _read(dest)
        self.assertTrue(body.startswith("---"))             # 补了 frontmatter
        self.assertIn("title: 归因排查", body)               # 取 H1 作标题
        self.assertIn("tags: [applovin, cost]", body)
        self.assertIn("status: attribution", body)
        self.assertIn("已打码", body)                        # 密钥被抹
        self.assertNotIn("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ", body)

    def test_dir_recursion_only_docs_not_data(self):
        # 目录递归只收文档(md/txt/docx/pdf),不扫数据文件(csv/json)
        d = tempfile.mkdtemp(prefix="loom-proj-")
        os.makedirs(os.path.join(d, "node_modules"))
        for name, txt in (("report.md", "# 报告"), ("data.csv", "a,b\n1,2"),
                          ("conf.json", '{"x":1}'), ("notes.txt", "hi"),
                          ("node_modules/pkg.md", "# vendor")):
            with open(os.path.join(d, name), "w") as f:
                f.write(txt)
        res = [r for r in self.intake.ingest(self.cfg, [d], to="x") if r[0]]
        names = {os.path.basename(dest) for dest, _ in res}
        self.assertIn("report.md", names)
        self.assertIn("notes.md", names)       # notes.txt → notes.md
        self.assertNotIn("data.csv", names)    # 数据文件不随目录进
        self.assertNotIn("conf.json", names)
        self.assertFalse(any("vendor" in _read(dest) for dest, _ in res))  # node_modules 跳过

    def test_default_to_inbox_and_move(self):
        p = self._mk("draft.md", "随手记")
        (dest, _), = self.intake.ingest(self.cfg, [p], move=True)
        self.assertIn("notes/inbox", dest.replace(os.sep, "/"))
        self.assertFalse(os.path.exists(p))                  # --move 删原件

    def test_existing_frontmatter_respected(self):
        p = self._mk("has_fm.md", "---\ntitle: 已有\n---\n正文")
        (dest, _), = self.intake.ingest(self.cfg, [p])
        self.assertEqual(_read(dest).count("---\ntitle:"), 1)  # 不重复注入

    def test_code_file_ingested_and_redacted(self):
        p = self._mk("cohort_pull.sql", "SELECT * FROM t\n-- token=ghp_ABCDEFGHIJKLMNOPQRSTUV012345")
        (dest, _), = self.intake.ingest(self.cfg, [p], to="pulls")
        self.assertTrue(dest.endswith(".sql"))            # 保留扩展名
        body = _read(dest)
        self.assertIn("SELECT * FROM t", body)
        self.assertIn("已打码", body)                      # 代码里的密钥被抹
        self.assertNotIn("ghp_ABCDEFGHIJKLMNOPQRSTUV", body)

    def test_dir_recursion_includes_code_excludes_data(self):
        d = tempfile.mkdtemp(prefix="loom-scratch-")
        for name, txt in (("q.sql", "SELECT 1"), ("agg.py", "print(1)"),
                          ("out.csv", "a\n1"), ("readme.md", "# x")):
            with open(os.path.join(d, name), "w") as f:
                f.write(txt)
        names = {os.path.basename(dest) for dest, _ in self.intake.ingest(self.cfg, [d], to="p") if dest}
        self.assertIn("q.sql", names)          # 代码随目录进
        self.assertIn("agg.py", names)
        self.assertIn("readme.md", names)
        self.assertNotIn("out.csv", names)     # 数据仍不随目录进

    def test_ipynb_rendered_to_narrative_md(self):
        nb = {"metadata": {"language_info": {"name": "python"}}, "cells": [
            {"cell_type": "markdown", "source": ["# 分析标题"]},
            {"cell_type": "code", "source": ["df = spark.sql('SELECT 1')"],
             "outputs": [{"output_type": "execute_result",
                          "data": {"text/plain": ["   col\n0    1"]}}]},
            {"cell_type": "code", "source": ["df.show()"],
             "outputs": [{"output_type": "display_data", "data": {"image/png": "base64..."}}]},
        ]}
        p = self._mk("nb.ipynb", json.dumps(nb))
        (dest, _), = self.intake.ingest(self.cfg, [p], to="nb")
        self.assertTrue(dest.endswith(".md"))
        body = _read(dest)
        self.assertIn("# 分析标题", body)                  # markdown 单元
        self.assertIn("```python", body)                  # 代码单元
        self.assertIn("spark.sql", body)
        self.assertIn("> 结果:", body)                     # 查询结果块
        self.assertIn("col", body)
        self.assertIn("[图表]", body)                      # 图输出被标注而非嵌入

    def test_docx_extracted_to_searchable_md_and_redacted(self):
        import zipfile
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        doc = (f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>'
               '<w:p><w:r><w:t>归因结论段落</w:t></w:r></w:p>'
               '<w:p><w:r><w:t>token=sk_live_ABCDEFGHIJKLMNOP1234</w:t></w:r></w:p>'
               '</w:body></w:document>')
        p = os.path.join(self.src, "报告.docx")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", doc)
        (dest, msg), = self.intake.ingest(self.cfg, [p], to="refs")
        self.assertTrue(dest.endswith(".md"))                 # 提取成可检索 .md
        body = _read(dest)
        self.assertIn("归因结论段落", body)                    # 正文提取到
        self.assertIn("已打码", body)                          # 提取文本里的密钥被抹
        self.assertNotIn("sk_live_ABCDEFGHIJKLMNOP1234", body)
        files = os.listdir(os.path.join(config.notes_dir(self.cfg), "refs"))
        self.assertTrue(any(f.endswith(".docx") for f in files))   # 原件保真也在

    def test_pdf_text_graceful_without_extractor(self):
        # _pdf_text 对非 pdf/无法解析优雅返回 ""(不崩)
        self.assertEqual(self.intake._pdf_text(self._mk("x.pdf", "not really a pdf")), "")

    def test_data_file_kept_as_is_but_redacted(self):
        p = self._mk("catalog.json", '{"token": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", "n": 1}')
        (dest, _), = self.intake.ingest(self.cfg, [p], to="refs")
        self.assertTrue(dest.endswith(".json"))          # 保留扩展名(不转 .md)
        body = _read(dest)
        self.assertNotIn("---\ntitle:", body)            # 数据文件不注 frontmatter
        self.assertIn("已打码", body)                     # 但密钥值仍被抹
        self.assertNotIn("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ", body)

    def test_name_collision_gets_suffix(self):
        a = self._mk("dup.md", "一")
        r1 = self.intake.ingest(self.cfg, [a])
        b = self._mk("dup.md", "二")
        r2 = self.intake.ingest(self.cfg, [b])
        self.assertNotEqual(r1[0][0], r2[0][0])              # 第二个加了 -1

    def test_note_captures_loose_info_redacted(self):
        # 通用散信息:一段文本 → notes/inbox 一条 note(打码 + frontmatter),不限来源
        dest, msg = self.intake.note(
            self.cfg, "口径对齐结论:net 按订单精算\ntoken=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
            tags=["飞书", "口径"])
        self.assertTrue(dest.replace(os.sep, "/").endswith(".md"))
        self.assertIn("notes/inbox", dest.replace(os.sep, "/"))
        body = _read(dest)
        self.assertTrue(body.startswith("---"))              # 有 frontmatter
        self.assertIn("tags: [飞书, 口径]", body)
        self.assertIn("口径对齐结论", body)                   # 正文
        self.assertIn("已打码", body)                         # 密钥被抹
        self.assertNotIn("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ", body)

    def test_note_empty_and_to_category(self):
        self.assertIsNone(self.intake.note(self.cfg, "   ")[0])   # 空内容
        dest, _ = self.intake.note(self.cfg, "放到指定类目", to="refs")
        self.assertIn("notes/refs", dest.replace(os.sep, "/"))

    def test_binary_routed_to_local_data_dir(self):
        # 无法提取/打码的二进制(parquet 等)进本地 _data/,不落进会上云的类目目录
        p = self._mk("data.parquet", "PK-ish binary payload")
        (dest, _), = self.intake.ingest(self.cfg, [p], to="refs")
        self.assertTrue(dest.replace(os.sep, "/").endswith("refs/_data/data.parquet"))
        refs = os.path.join(config.notes_dir(self.cfg), "refs")
        self.assertNotIn("data.parquet", os.listdir(refs))     # 不在类目根(那会被推云)
        self.assertTrue(os.path.exists(os.path.join(refs, "_data", "data.parquet")))

class TriageTest(unittest.TestCase):
    def setUp(self):
        from loom import intake
        self.intake = intake
        self.cfg = {"vault": {"dir": tempfile.mkdtemp(prefix="loom-vault-")}, "redact": True}
        # 已有一个类目 + 标签(供 harvest / 约束)
        self.intake.ingest(self.cfg, [self._src("旧.md", "# 旧\n正文")],
                           to="attribution", tags="applovin,cost")
        # 一篇待分类进 inbox
        self.intake.ingest(self.cfg, [self._src("新下载.md", "# CPM 排查\ntoken=ghp_ABCDEFGHIJKLMNOPQRSTUV012345")])

    def _src(self, name, content):
        d = tempfile.mkdtemp(prefix="loom-src-")
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_harvest_taxonomy(self):
        cats, tags = self.intake.harvest_taxonomy(self.cfg)
        self.assertIn("attribution", cats)
        self.assertIn("applovin", tags)
        self.assertIn("cost", tags)

    def test_manifest_lists_inbox_and_existing(self):
        m = self.intake.triage_manifest(self.cfg)
        self.assertIn("attribution", m)           # 现有类目喂给 AI
        self.assertIn("新下载.md", m)              # 待分类文档
        self.assertIn("已打码", m)                 # 清单里也不泄密
        self.assertNotIn("ghp_ABCDEFGHIJKLMNOPQRSTUV", m)

    def test_apply_moves_and_retags(self):
        mapping = [("inbox/新下载.md", "attribution", ["cpm", "applovin"])]
        (dest, _), = self.intake.apply_triage(self.cfg, mapping)
        self.assertIn("notes/attribution", dest.replace(os.sep, "/"))
        self.assertFalse(os.path.exists(
            os.path.join(config.notes_dir(self.cfg), "inbox", "新下载.md")))
        body = _read(dest)
        self.assertIn("tags: [cpm, applovin]", body)   # 标签被 AI 决定更新
        self.assertIn("status: attribution", body)

    def test_deprecate_moves_to_attic_out_of_search(self):
        # 默认:移进 _attic → notes 采集器跳过 → 检索不到,但文件仍在
        (src, _), = self.intake.ingest(self.cfg, [self._src("旧口径.md", "# 旧口径\n已作废的算法")],
                                       to="analysis")
        rel = os.path.join("analysis", os.path.basename(src))
        dest, msg = self.intake.deprecate(self.cfg, rel, superseded_by="新口径")
        self.assertIn("_attic", dest)
        self.assertFalse(os.path.exists(src))                 # 原处已移走
        self.assertTrue(os.path.exists(dest))                 # _attic 里还在(可溯源)
        ncfg = dict(self.cfg, sources={"notes": {"enabled": True}})
        paths = {e["detail"]["path"] for e in notes_col.collect(ncfg, "2000-01-01")}
        self.assertFalse(any("_attic" in p for p in paths))   # 采集器跳过 _attic

    def test_deprecate_mark_keeps_but_flags(self):
        (src, _), = self.intake.ingest(self.cfg, [self._src("过时.md", "# 过时笔记\n轻微过时")],
                                       to="analysis")
        rel = os.path.join("analysis", os.path.basename(src))
        dest, _ = self.intake.deprecate(self.cfg, rel, mark=True)
        self.assertEqual(dest, src)                           # 留原处
        self.assertIn("status: deprecated", _read(src))
        ncfg = dict(self.cfg, sources={"notes": {"enabled": True}})
        e = next(e for e in notes_col.collect(ncfg, "2000-01-01")
                 if e["detail"]["path"] == rel)
        self.assertTrue(e["summary"].startswith("⚠[废弃]"))    # 检索里带 ⚠ 标记

    def test_parse_mapping_tsv(self):
        p = os.path.join(tempfile.mkdtemp(), "m.tsv")
        with open(p, "w", encoding="utf-8") as f:
            f.write("# 注释行\ninbox/a.md\tguides\tds, guide\n\n")
        rows = self.intake.parse_mapping_tsv(p)
        self.assertEqual(rows, [("inbox/a.md", "guides", ["ds", "guide"])])


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

    def test_like_wildcards_escaped(self):
        # "%" 不应匹配全部;"_" 不应当通配
        self.assertEqual(search.query("%"), [])          # 无字面 % 的条目
        self.assertEqual(search.query("_"), [])

    def test_limit_bounds(self):
        self.assertEqual(len(search.query("cohort", limit=1)), 1)   # 有 2 条,夹到 1
        self.assertTrue(len(search.query("cohort", limit=-1)) <= 2)  # 负数不放开
        self.assertTrue(len(search.query("cohort", limit=0)) >= 1)   # 0 夹到 1,不空

    def test_snippet_returned(self):
        hits = search.query("cohort")
        self.assertTrue(any(h.get("snip") for h in hits))            # 有命中片段

    def test_space_query_routes_to_like(self):
        # "fix 优化" 含空格,非空白字符可能<3 → 不该被当死 FTS 短语吞掉
        self.assertTrue(len(search.query("cohort 优化")) >= 0)       # 不崩即可

    def test_body_only_term_is_searchable_end_to_end(self):
        # 端到端过 FTS:只在 detail.body(整段对话)出现、summary 里没有的词也能搜到。
        # 这条才真正证明「整段可检索」——从 rebuild 索引到 query 命中,不是断言自己塞的字符串。
        e = _entry("claude:sx:2026-06-07", "2026-06-07", "p2", "claude", "session",
                   "搭归因管道", ts="2026-06-07T09:00:00",
                   opening="搭归因管道", body="搭归因管道 排查 acmefraud 作弊订单")
        store.save({e["id"]: e})
        search.rebuild()
        self.assertIn("claude:sx:2026-06-07",
                      {h["id"] for h in search.query("acmefraud")})   # 英文深处词
        self.assertIn("claude:sx:2026-06-07",
                      {h["id"] for h in search.query("作弊订单")})        # 中文深处词
        self.assertNotIn("搭归因管道", "acmefraud")                     # 词确实不在标题里
        self.assertEqual(search.query("acmefraud", project="nope"), [])  # 过滤生效→非空转

    def test_auto_rebuild_when_index_missing(self):
        os.remove(util.INDEX_PATH)
        self.assertTrue(len(search.query("cohort")) == 2)  # ensure() 自动重建
        self.assertTrue(os.path.exists(util.INDEX_PATH))


class ReportTest(unittest.TestCase):
    def setUp(self):
        from loom import report
        self.report = report
        self.src = tempfile.mkdtemp(prefix="loom-rep-")

    def _mk_xlsx(self):
        import zipfile
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        istr = lambda r, t: f'<c r="{r}" t="inlineStr"><is><t>{t}</t></is></c>'
        rows = [
            ("提交时间", "今日工作与进度情况", "今日思考（问题与心得）", "明日工作计划"),
            ("2026-06-30 21:39", "广告收入加 net 口径 + 回填", "口径要对齐下游", "跑历史回溯"),
            ("2026-06-29 18:43", "素材归因落码", "", ""),
        ]
        cells = []
        for ri, row in enumerate(rows, 1):
            cs = "".join(istr(f"{chr(65+ci)}{ri}", v) for ci, v in enumerate(row) if v)
            cells.append(f'<row r="{ri}">{cs}</row>')
        sheet = f'<worksheet xmlns="{ns}"><sheetData>{"".join(cells)}</sheetData></worksheet>'
        p = os.path.join(self.src, "日报.xlsx")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("xl/worksheets/sheet1.xml", sheet)
        return p

    def test_import_parses_reports(self):
        entries = self.report.import_xlsx({}, self._mk_xlsx())
        self.assertEqual(len(entries), 2)
        e = {x["id"]: x for x in entries}["report:2026-06-30"]
        self.assertEqual(e["kind"], "report")
        self.assertEqual(e["ts"], "2026-06-30T21:39")       # 提交时间 → ts
        self.assertEqual(e["project"], "日报")
        self.assertIn("net 口径", e["detail"]["work"])
        self.assertIn("跑历史回溯", e["detail"]["plan"])
        self.assertIn("口径要对齐", e["detail"]["content"])   # content 供检索

    def test_same_day_reports_merged_not_overwritten(self):
        import zipfile
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        istr = lambda r, t: f'<c r="{r}" t="inlineStr"><is><t>{t}</t></is></c>'
        rows = [
            ("提交时间", "今日工作与进度情况", "今日思考（问题与心得）", "明日工作计划"),
            ("2026-06-25 22:11", "cohort 回填", "", "素材上线"),
            ("2026-06-25 09:00", "商业报告调整", "现状调研", ""),   # 同一天第二条
        ]
        cells = []
        for ri, row in enumerate(rows, 1):
            cs = "".join(istr(f"{chr(65+ci)}{ri}", v) for ci, v in enumerate(row) if v)
            cells.append(f'<row r="{ri}">{cs}</row>')
        sheet = f'<worksheet xmlns="{ns}"><sheetData>{"".join(cells)}</sheetData></worksheet>'
        p = os.path.join(self.src, "dup.xlsx")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("xl/worksheets/sheet1.xml", sheet)
        out = self.report.import_xlsx({}, p)
        self.assertEqual(len(out), 1)                      # 同天合并为一条
        e = out[0]
        self.assertIn("cohort 回填", e["detail"]["work"])   # 两条内容都在,谁都没被覆盖
        self.assertIn("商业报告调整", e["detail"]["work"])
        self.assertEqual(e["ts"], "2026-06-25T09:00")      # 取最早提交时刻

    def test_import_idempotent(self):
        p = self._mk_xlsx()
        a = self.report.import_xlsx({}, p)
        b = self.report.import_xlsx({}, p)
        self.assertEqual({x["id"] for x in a}, {x["id"] for x in b})  # 同 id → upsert 幂等

    def test_report_rendered_into_journal(self):
        cfg = {"vault": {"dir": tempfile.mkdtemp(prefix="loom-vault-")}}
        entries = self.report.import_xlsx({}, self._mk_xlsx())
        render.build(cfg, {e["id"]: e for e in entries})
        jp = os.path.join(config.journal_dir(cfg), "2026-06-30.md")
        body = _read(jp)
        self.assertIn("## 📋 日报", body)
        self.assertIn("今日工作与进度", body)
        self.assertIn("广告收入加 net 口径", body)
        self.assertIn("明日计划", body)


class TopicTest(unittest.TestCase):
    def setUp(self):
        from loom import topics
        self.topics = topics
        self.cfg = {"vault": {"dir": tempfile.mkdtemp(prefix="loom-vault-")}}
        for p in (topics._map_path(), topics._audit_path()):
            if os.path.exists(p):
                os.remove(p)

    def _page(self, tid, parent="", aliases=""):
        d = self.topics.topics_dir(self.cfg)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, tid + ".md"), "w", encoding="utf-8") as f:
            f.write(f"---\ntitle: {tid}\ntype: loom-topic\n"
                    f"parent: {parent}\naliases: {aliases}\n---\n\n正文")

    def test_canon(self):
        self.assertEqual(self.topics.canon(" [[Serial Fallback]] "), "serial-fallback")
        self.assertEqual(self.topics.canon("素材匹配重构"), "素材匹配重构")

    def test_descendants_rollup_and_multiparent(self):
        self._page("素材")
        self._page("素材匹配重构", parent="[[素材]]")
        self._page("serial兜底", parent="[[素材匹配重构]]")
        self._page("净额", parent="[[bf三方支付]], [[素材匹配重构]]")  # 多父
        pgs = self.topics.pages(self.cfg)
        sub = self.topics.descendants("素材", pgs)
        self.assertEqual(sub, {"素材", "素材匹配重构", "serial兜底", "净额"})  # 整棵子树上卷
        self.assertIn("净额", self.topics.descendants("bf三方支付", pgs))     # 多父:另一棵也含它

    def test_descendants_cycle_safe(self):
        self._page("a", parent="[[b]]")
        self._page("b", parent="[[a]]")   # 环
        sub = self.topics.descendants("a", self.topics.pages(self.cfg))
        self.assertEqual(sub, {"a", "b"})   # 不死循环

    def test_alias_resolve(self):
        self._page("claude", aliases="[anthropic, claude-code]")
        pgs = self.topics.pages(self.cfg)
        self.assertEqual(self.topics.resolve("Anthropic", pgs), "claude")

    def test_gather_shows_full_session_body_not_just_first(self):
        # 会话候选要带当天【全部】提问,让 AI 判得准(教训:只看首句会误判"太泛")
        by = {"claude:s:2026-06-24": _entry(
            "claude:s:2026-06-24", "2026-06-24", "data-marketing", "claude", "session",
            "今天继续昨天的工作梳理",   # 首句很泛
            body="今天继续昨天的工作梳理 / 什么叫素材归因主题域 / AppLovin 的 af_ad_id creative_set 归因 / player 表 adset ad 粒度",
            opening="今天继续昨天的工作梳理")}
        out = self.topics.gather(self.cfg, by)
        self.assertIn("素材归因主题域", out)     # 首句之外的真信号也进了候选清单
        self.assertIn("creative_set", out)

    def test_gather_enriched_with_relations_defs_and_fewshot(self):
        # 升级后的 gather:候选带关系邻居(+邻居已有主题=传播先验)、主题定义、few-shot
        self._page("素材归因")
        by = {
            "claude:s1:2026-06-30": _entry(
                "claude:s1:2026-06-30", "2026-06-30", "p", "claude", "session", "改归因",
                ts="2026-06-30T09:00:00", start="2026-06-30T09:00:00",
                end="2026-06-30T10:00:00", body="梳理素材归因口径"),
            "git:p:aaa": _entry("git:p:aaa", "2026-06-30", "p", "git", "commit", "fix attr",
                                ref="aaa", ts="2026-06-30T09:30:00",
                                file_list=[{"path": "src/attr.py"}]),
        }
        # 提交 aaa 已归类 → 既进 few-shot,又是会话 s1 的传播先验
        self.topics.apply(self.cfg, [("git:p:aaa", ["素材归因"])])
        out = self.topics.gather(self.cfg, by)
        self.assertIn("最近的分类示例", out)          # few-shot 段在
        self.assertIn("关联:", out)                  # 候选 s1 带关系邻居
        self.assertIn("已归类 [素材归因]", out)        # 邻居 aaa 的主题作为传播先验暴露给 AI

    def test_gather_refine_revisits_classified_for_finer_topics(self):
        # 细化模式:回看【已归类】条目,喂现主题、让 AI 补更细/更多主题(默认模式看不到已归类的)
        self._page("素材归因")
        by = {"claude:s1:2026-06-30": _entry(
            "claude:s1:2026-06-30", "2026-06-30", "p", "claude", "session",
            "serial 兜底归因", body="serial 兜底口径")}
        self.topics.apply(self.cfg, [("claude:s1:2026-06-30", ["素材归因"])])
        # 默认模式:已归类 → 不进候选(待归类条目为 0;它只会作为 few-shot 出现)
        self.assertIn("待归类条目(0)", self.topics.gather(self.cfg, by))
        # 细化模式:出现,且带「现主题」+ 追加语义指令
        ref = self.topics.gather(self.cfg, by, refine=True)
        self.assertIn("claude:s1:2026-06-30", ref)
        self.assertIn("[素材归因]  ← 在此基础上补充", ref)   # 展示现主题,让 AI 在其上补充
        self.assertIn("补上遗漏的侧面主题", ref)             # 指令是"补充/更细",不是重判

    def test_set_parents_writes_edges_and_enables_rollup(self):
        for t in ("素材", "素材归因", "serial兜底"):
            self._page(t)
        n, created = self.topics.set_parents(
            self.cfg, [("素材归因", ["素材"]), ("serial兜底", ["素材归因"])])
        self.assertEqual(n, 2)
        pgs = self.topics.pages(self.cfg)
        self.assertEqual(pgs["素材归因"]["parents"], ["素材"])        # 父边写盘
        self.assertEqual(self.topics.descendants("素材", pgs),
                         {"素材", "素材归因", "serial兜底"})           # 上卷整棵树

    def test_set_parents_creates_missing_and_rejects_cycle(self):
        self._page("素材归因")
        # 父主题不存在 → 自动建页
        self.topics.set_parents(self.cfg, [("素材归因", ["素材"])])
        self.assertIn("素材", self.topics.pages(self.cfg))
        # 成环 → 抛错,不写盘
        with self.assertRaises(ValueError):
            self.topics.set_parents(self.cfg, [("素材", ["素材归因"])])

    def test_hierarchy_prompt_lists_topics_and_parents(self):
        self._page("素材")
        self._page("素材归因", parent="[[素材]]")
        out = self.topics.hierarchy_prompt(self.cfg)
        self.assertIn("建立层级", out)
        self.assertIn("→ 素材", out)               # 显示当前父级
        self.assertIn("set-parents --file", out)    # 指向落地命令

    def test_gather_shows_member_counts(self):
        self._page("素材归因")
        by = {"git:1": _entry("git:1", "2026-06-30", "p", "git", "commit", "a"),
              "git:2": _entry("git:2", "2026-06-30", "p", "git", "commit", "b")}
        self.topics.apply(self.cfg, [("git:1", ["素材归因"]), ("git:2", ["素材归因"])])
        # 现有主题列表带成员数(哪个太粗一眼可见)
        self.assertIn("素材归因  (2)", self.topics.gather(self.cfg, by))

    def test_apply_creates_page_and_maps_members_rollup(self):
        self._page("素材")
        mapping = [("git:1", ["素材匹配重构"]), ("claude:2", ["serial兜底"]),
                   ("git:3", ["none-of-these"])]   # none-of-these 忽略
        n, created = self.topics.apply(self.cfg, mapping)
        self.assertEqual(n, 2)
        self.assertIn("素材匹配重构", created)        # 新叶子自动建页
        # 但新建的没挂到 素材 下(层级要人维护)→ 手动挂上再验上卷
        self._page("素材匹配重构", parent="[[素材]]")
        self._page("serial兜底", parent="[[素材匹配重构]]")
        by_id = {"git:1": _entry("git:1", "2026-06-30", "p", "git", "commit", "改"),
                 "claude:2": _entry("claude:2", "2026-07-01", "p", "claude", "session", "聊")}
        ids = {e["id"] for e in self.topics.members(self.cfg, "素材", by_id)}
        self.assertEqual(ids, {"git:1", "claude:2"})   # 父主题上卷到两个后代的条目


class TimezoneTest(unittest.TestCase):
    def test_utc_to_local_consistent_across_notation(self):
        z = util.iso_utc_to_local("2026-06-01T09:00:00Z")
        off = util.iso_utc_to_local("2026-06-01T09:00:00+00:00")
        self.assertEqual(z, off)                 # Z 与 +00:00 是同一时刻 → 同一本地时间
        self.assertNotIn("Z", z)
        self.assertEqual(len(z), 19)             # 朴素 ISO(无时区后缀)

    def test_naive_and_empty_passthrough(self):
        self.assertEqual(util.iso_utc_to_local("2026-06-01T09:00:00"), "2026-06-01T09:00:00")
        self.assertEqual(util.iso_utc_to_local(""), "")
        self.assertIsNone(util.iso_utc_to_local(None))


class VaultGitignoreTest(unittest.TestCase):
    def test_ensure_creates_required_and_idempotent(self):
        from loom import cli
        vd = tempfile.mkdtemp(prefix="loom-vg-")
        self.assertTrue(cli._ensure_gitignore(vd))       # 首次:写入
        content = _read(os.path.join(vd, ".gitignore"))
        for pat in ("_data/", ".env", "*.xlsx", "*.pdf"):
            self.assertIn(pat, content)
        self.assertFalse(cli._ensure_gitignore(vd))      # 幂等:全都在 → 无改动

    def test_preserves_user_lines(self):
        from loom import cli
        vd = tempfile.mkdtemp(prefix="loom-vg-")
        with open(os.path.join(vd, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("我的自定义忽略\n_data/\n")
        cli._ensure_gitignore(vd)
        content = _read(os.path.join(vd, ".gitignore"))
        self.assertIn("我的自定义忽略", content)           # 用户已有行保留
        self.assertIn("*.xlsx", content)                  # 缺的补上

    def test_untrack_ignored_removes_from_index_keeps_local(self):
        from loom import cli
        vd = tempfile.mkdtemp(prefix="loom-vg-")
        for a in (["init", "-q"], ["config", "user.email", "t@t"],
                  ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", vd, *a], check=True, capture_output=True)
        os.makedirs(os.path.join(vd, "topic", "_data"))
        with open(os.path.join(vd, "topic", "_data", "raw.xlsx"), "w") as f:
            f.write("x")
        with open(os.path.join(vd, "keep.md"), "w") as f:
            f.write("# k")
        subprocess.run(["git", "-C", vd, "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", vd, "commit", "-q", "-m", "误跟踪原始数据"],
                       check=True, capture_output=True)
        cli._ensure_gitignore(vd)
        removed = cli._untrack_ignored(vd)
        self.assertTrue(any("raw.xlsx" in f for f in removed))
        tracked = subprocess.run(["git", "-C", vd, "ls-files"],
                                 capture_output=True, text=True).stdout
        self.assertIn("keep.md", tracked)                 # 正常文档仍跟踪
        self.assertNotIn("raw.xlsx", tracked)             # 原始数据移出云端
        self.assertTrue(os.path.exists(                   # 但本地文件仍在
            os.path.join(vd, "topic", "_data", "raw.xlsx")))


class VaultGitResultTest(unittest.TestCase):
    def setUp(self):
        from loom import cli
        self.cli = cli
        self.vd = tempfile.mkdtemp(prefix="loom-vault-result-")
        for args in (["init", "-q"], ["config", "user.email", "t@t"],
                     ["config", "user.name", "tester"]):
            subprocess.run(["git", "-C", self.vd, *args], check=True,
                           capture_output=True)
        self.cfg = {"vault": {"dir": self.vd}}

    def test_local_backup_distinguishes_commit_and_no_change(self):
        with open(os.path.join(self.vd, "note.md"), "w", encoding="utf-8") as f:
            f.write("hello")
        first = self.cli.vault_git(self.cfg, False)
        self.assertTrue(first["ok"])
        self.assertEqual(first["stage"], "complete")
        self.assertEqual(first["commit"], "created")
        self.assertEqual(first["push"], "not_requested")

        second = self.cli.vault_git(self.cfg, False)
        self.assertTrue(second["ok"])
        self.assertEqual(second["commit"], "unchanged")

    def test_requested_push_without_remote_is_failure(self):
        with open(os.path.join(self.vd, "note.md"), "w", encoding="utf-8") as f:
            f.write("hello")
        result = self.cli.vault_git(self.cfg, True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "push")
        self.assertEqual(result["commit"], "created")
        self.assertEqual(result["push"], "failed")
        self.assertIn("未配置 remote", result["message"])

    def test_push_command_failure_is_not_reported_as_success(self):
        with open(os.path.join(self.vd, "note.md"), "w", encoding="utf-8") as f:
            f.write("hello")
        subprocess.run(["git", "-C", self.vd, "remote", "add", "origin",
                        os.path.join(self.vd, "missing-remote.git")], check=True,
                       capture_output=True)
        result = self.cli.vault_git(self.cfg, True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "push")
        self.assertEqual(result["push"], "failed")
        self.assertIn("推送失败", result["message"])


class DoCollectTest(unittest.TestCase):
    def test_cli_uses_git_as_the_project_document_switch(self):
        from loom import cli
        from loom import collectors
        cfg = {"sources": {"git": {"enabled": False}, "docs": {"enabled": True}},
               "feishu": {"enabled": False}}
        selected = cli._sync_sources(cfg)
        self.assertNotIn("git", selected)
        self.assertNotIn("docs", selected)                 # 旧 docs=true 不得绕过 Git 关闭

        cfg["sources"]["git"]["enabled"] = True
        cfg["sources"]["docs"]["enabled"] = False
        selected = cli._sync_sources(cfg)
        self.assertNotIn("git", selected)
        self.assertNotIn("docs", selected)                 # 旧 docs=false 也不得被升级后扩大采集

        cfg["sources"]["docs"]["enabled"] = True
        selected = cli._sync_sources(cfg)
        self.assertIn("git", selected)
        self.assertIn("docs", selected)
        if "docs" in collectors.REGISTRY and collectors.is_syncable("docs"):
            self.assertEqual(cli._sync_sources(cfg, "git"), ["git", "docs"])

    def test_legacy_docs_source_command_is_rejected_and_git_updates_both_flags(self):
        from loom import cli
        cfg = {"sources": {"git": {"enabled": True}, "docs": {"enabled": True}}}
        original_save = cli.config.save
        cli.config.save = lambda value: None
        try:
            docs_args = type("Args", (), {"name": "docs", "action": "disable"})()
            with self.assertRaisesRegex(SystemExit, "项目文档已并入 Git"):
                cli.cmd_source(cfg, docs_args)
            self.assertTrue(cfg["sources"]["docs"]["enabled"])

            git_args = type("Args", (), {"name": "git", "action": "disable"})()
            cli.cmd_source(cfg, git_args)
            self.assertFalse(cfg["sources"]["git"]["enabled"])
            self.assertFalse(cfg["sources"]["docs"]["enabled"])
        finally:
            cli.config.save = original_save

    def test_one_failing_collector_does_not_abort_others(self):
        from loom import cli
        from loom import collectors
        for p in (util.DATA_PATH, util.INDEX_PATH):
            if os.path.exists(p):
                os.remove(p)

        def boom(cfg, since):
            raise RuntimeError("源坏了")

        def ok(cfg, since):
            return [_entry("ok:1", "2026-06-01", "p", "notes", "note", "还活着")]

        orig = dict(collectors.REGISTRY)
        try:
            collectors.REGISTRY.clear()
            collectors.REGISTRY.update({"boom": boom, "ok": ok})
            by_id = cli.do_collect({"redact": False}, ["boom", "ok"], "2000-01-01")
            self.assertIn("ok:1", by_id)                  # boom 抛异常但 ok 仍入库
        finally:
            collectors.REGISTRY.clear()
            collectors.REGISTRY.update(orig)


class DigestTest(unittest.TestCase):
    """AI 会话摘要:生成原材料(含答)、回写校验、叠加覆盖、重采不丢、可检索。"""

    def setUp(self):
        from loom import digest
        self.digest = digest
        for p in (util.DATA_PATH, util.INDEX_PATH, digest.DIGEST_PATH):
            if os.path.exists(p):
                os.remove(p)
        self.root = tempfile.mkdtemp(prefix="loom-dg-")
        proj = os.path.join(self.root, "proj-x")
        os.makedirs(proj)
        # 开场首问故意含糊("继续吧"),真正主题("分层匹配 + serial 兜底")只在助手回答里
        rows = [
            {"cwd": "/Users/x/data-mkt", "timestamp": "2026-06-10T09:00:00Z",
             "type": "user", "message": {"content": "继续吧"}},
            {"timestamp": "2026-06-10T09:02:00Z", "type": "assistant",
             "message": {"content": "我们把素材匹配改成分层匹配加 serial 兜底,脏数据分离。"}},
            {"timestamp": "2026-06-10T09:30:00Z", "type": "user",
             "message": {"content": "那脏数据怎么隔离?"}},
        ]
        with open(os.path.join(proj, "sid-dg.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        self.cfg = {"redact": False,
                    "sources": {"claude": {"enabled": True, "projects_dir": self.root}}}
        ents = claude_col.collect(self.cfg, "2000-01-01")
        self.e = [x for x in ents if "sid-dg" in x["id"]][0]
        self.day = self.e["date"]
        self.eid = self.e["id"]
        store.save({x["id"]: x for x in ents})

    def test_material_includes_questions_and_answers(self):
        mat = self.digest.gen_material(self.cfg, self.day)
        self.assertIn(self.eid, mat)                       # 会话 id 可被 AI 照抄
        self.assertIn("[我] 继续吧", mat)
        self.assertIn("分层匹配加 serial 兜底", mat)         # 答案侧内容也进原材料(关键)
        self.assertIn("那脏数据怎么隔离", mat)

    def test_set_rejects_fabricated_id(self):
        tsv = (f"{self.eid}\t素材匹配分层重构\t把匹配改为分层+serial兜底,并隔离脏数据。\n"
               "claude:编造:2026-06-10\t假的\t不该被接受\n")
        applied = self.digest.set_from_text(self.cfg, self.day, tsv)
        self.assertEqual(applied, [self.eid])              # 只收当天真实会话,幻觉 id 丢弃
        self.assertIn(self.eid, self.digest.load())
        self.assertNotIn("claude:编造:2026-06-10", self.digest.load())

    def test_apply_overlays_and_keeps_raw(self):
        self.digest.set_from_text(self.cfg, self.day,
                                  f"{self.eid}\t素材匹配分层重构\t分层+serial兜底。")
        by_id = store.load()
        raw = by_id[self.eid]["summary"]
        n = self.digest.apply_all(by_id)
        self.assertEqual(n, 1)
        self.assertEqual(by_id[self.eid]["summary"], "素材匹配分层重构")   # 标题被覆盖
        self.assertEqual(by_id[self.eid]["detail"]["summary_raw"], raw)   # 原判保留
        self.assertIn("serial", by_id[self.eid]["detail"]["digest"])
        self.assertTrue(by_id[self.eid]["detail"]["ai_digest"])

    def test_survives_recollect_and_is_searchable(self):
        self.digest.set_from_text(self.cfg, self.day,
                                  f"{self.eid}\t素材匹配分层重构\t分层匹配加 serial 兜底,脏数据隔离。")
        # 首次叠加 + 建索引
        by_id = store.load()
        self.digest.apply_all(by_id)
        store.save(by_id)
        search.rebuild()
        hits = {h["id"] for h in search.query("serial 兜底")}
        self.assertIn(self.eid, hits)                      # 摘要进检索(答案侧词也搜得到)
        # 模拟重采:采集器把 summary 打回"继续吧",再 apply_all 应恢复真实标题
        fresh = claude_col.collect(self.cfg, "2000-01-01")
        store.upsert(by_id, fresh)
        self.assertEqual(by_id[self.eid]["summary"], "继续吧")   # 采集器重建=糊标题
        self.digest.apply_all(by_id)
        self.assertEqual(by_id[self.eid]["summary"], "素材匹配分层重构")  # 摘要救回

    def test_redaction_on_set(self):
        cfg = dict(self.cfg, redact=True)
        self.digest.set_from_text(cfg, self.day,
                                  f"{self.eid}\t配置密钥\tpassword=SuperSecret123 别泄露")
        self.assertNotIn("SuperSecret123", self.digest.load()[self.eid]["abstract"])


class ServeTest(unittest.TestCase):
    """浏览页 API:纯函数出 JSON + 一发端到端 HTTP。"""

    def setUp(self):
        from loom import serve, topics
        self.serve, self.topics = serve, topics
        self.cfg = {"vault": {"dir": tempfile.mkdtemp(prefix="loom-vault-")}}
        for p in (util.DATA_PATH, util.INDEX_PATH, topics._map_path()):
            if os.path.exists(p):
                os.remove(p)
        es = [
            _entry("git:p:1", "2026-06-01", "proj", "git", "commit", "净额口径修复",
                   body="按订单精算"),
            _entry("claude:s:2026-06-01", "2026-06-01", "proj", "claude", "session",
                   "对净额的讨论", opening="净额怎么算"),
            _entry("note:x", "2026-06-02", "分析", "notes", "note", "随手记"),
        ]
        store.save({e["id"]: e for e in es})
        search.rebuild()
        # 主题:父子两页 + 两条映射
        td = topics.topics_dir(self.cfg)
        os.makedirs(td, exist_ok=True)
        open(os.path.join(td, "bf支付.md"), "w").write("---\ntitle: bf支付\n---\n")
        open(os.path.join(td, "净额.md"), "w").write("---\ntitle: 净额\nparent: bf支付\n---\n")
        topics.save_map({"git:p:1": ["净额"], "claude:s:2026-06-01": ["净额"]})

    def test_api_days_and_day(self):
        by_id = store.load()
        days = self.serve.api_days(by_id)["days"]
        self.assertEqual(days[0], {"date": "2026-06-02", "count": 1})   # 倒序
        d = self.serve.api_day("2026-06-01", by_id)
        self.assertEqual(d["total"], 2)
        self.assertIn("commit", d["groups"])
        self.assertEqual(d["groups"]["session"][0]["topics"], ["净额"])  # 卡片带主题

    def test_api_topics_rollup_and_topic(self):
        t = self.serve.api_topics(self.cfg)
        root = t["tree"][0]
        self.assertEqual(root["name"], "bf支付")
        self.assertEqual(root["count"], 2)                  # 伞主题显示上卷数(直挂0)
        self.assertEqual(root["direct"], 0)
        self.assertEqual(root["children"][0]["name"], "净额")
        m = self.serve.api_topic(self.cfg, "bf支付", store.load())
        self.assertEqual(m["total"], 2)                     # 上卷含子主题成员
        self.assertEqual(len(m["groups"]["commit"]), 1)

    def test_api_search_and_entry(self):
        r = self.serve.api_search(self.cfg, "净额口径")
        self.assertEqual(len(r["hits"]), 1)
        self.assertEqual(r["hits"][0]["topics"], ["净额"])
        e = self.serve.api_entry("git:p:1", store.load())
        self.assertEqual(e["detail"]["body"], "按订单精算")   # 详情含 detail
        self.assertIn("related", e)                          # 网页抽屉依赖顶层关联边
        self.assertIsInstance(e["related"], list)
        self.assertEqual(self.serve.api_entry("没有", {}), {"error": "not found"})

    def test_api_relation_graph_reports_full_and_visible_counts(self):
        graph = self.serve.api_relation_graph(store.load())
        self.assertEqual(graph["total_entries"], 3)
        self.assertEqual(graph["shown_nodes"], len(graph["nodes"]))
        self.assertEqual(graph["shown_edges"], len(graph["edges"]))

    def test_api_topic_relation_graph_keeps_hierarchy_and_aggregates_records(self):
        by_id = store.load()
        by_id["claude:s:2026-06-01"]["detail"].update({
            "start": "2026-06-01T08:30:00", "end": "2026-06-01T09:30:00",
        })
        self.topics.save_map({
            "git:p:1": ["净额"], "claude:s:2026-06-01": ["bf支付"],
        })
        graph = self.serve.api_topic_relation_graph(self.cfg, by_id)
        self.assertEqual({node["name"] for node in graph["nodes"]}, {"bf支付", "净额"})
        self.assertEqual(graph["hierarchy_edges"], [["bf支付", "净额"]])
        self.assertEqual(graph["total_relation_edges"], 1)
        self.assertEqual(graph["mapped_relation_edges"], 1)
        self.assertEqual(graph["relation_edges"][0]["count"], 1)
        nodes = {node["name"]: node for node in graph["nodes"]}
        self.assertEqual(nodes["bf支付"]["kinds"], {"session": 1})
        self.assertEqual(nodes["净额"]["kinds"], {"commit": 1})

    def test_api_search_paginates_all_records_with_stable_filters(self):
        rows = []
        for i in range(45):
            day = "2026-06-02" if i >= 30 else "2026-06-01"
            rows.append(_entry(
                f"row:{i:02d}", day, "proj", "git" if i % 2 == 0 else "notes",
                "commit", ("needle " if i % 3 == 0 else "other ") + str(i),
                ts=day + "T10:00:00"))
        store.save({e["id"]: e for e in rows})
        search.rebuild()

        first = self.serve.api_search(self.cfg, "", page=1, page_size=20)
        second = self.serve.api_search(self.cfg, "", page=2, page_size=20)
        last = self.serve.api_search(self.cfg, "", page=99, page_size=20)
        self.assertEqual((first["total"], first["pages"], first["page_size"]), (45, 3, 20))
        self.assertEqual(len(first["hits"]), 20)
        self.assertEqual(len(second["hits"]), 20)
        self.assertEqual((last["page"], len(last["hits"])), (3, 5))  # 越界落到末页
        ids = [e["id"] for e in first["hits"] + second["hits"] + last["hits"]]
        self.assertEqual(len(ids), len(set(ids)))                       # 同时间戳也不跨页重漏
        self.assertEqual(ids, sorted(ids, reverse=True))

        filtered = self.serve.api_search(
            self.cfg, "needle", tool="git", since="2026-06-02", page=1, page_size=10)
        self.assertEqual(filtered["total"], 3)                         # q/工具/日期同层过滤
        self.assertEqual({e["id"] for e in filtered["hits"]},
                         {"row:30", "row:36", "row:42"})
        hundred = self.serve.api_search(self.cfg, "", page_size=999)
        self.assertEqual(hundred["page_size"], 100)                    # 服务端硬上限
        empty = self.serve.api_search(self.cfg, "not-found", page=80, page_size=20)
        self.assertEqual((empty["total"], empty["page"], empty["pages"]), (0, 1, 1))

    def test_api_stats(self):
        st = self.serve.api_stats(self.cfg, store.load())
        self.assertEqual(st["entries"], 3)
        self.assertEqual(st["days"], 2)
        self.assertEqual(st["topics"], 2)                   # bf支付 + 净额 两页
        self.assertEqual(st["tagged"], 2)
        self.assertEqual(set(st["tools"]), {"git", "claude", "notes"})   # 并列不断顺序
        self.assertEqual(len(st["recent"]), 3)

    def test_console_records_filter_and_derived_state(self):
        rows = self.serve.api_console_records(store.load(), q="净额", period="all")["records"]
        self.assertEqual({r["id"] for r in rows}, {"git:p:1", "claude:s:2026-06-01"})
        self.assertTrue(all(r["state"] == "classified" for r in rows))
        git_only = self.serve.api_console_records(store.load(), source="git",
                                                   period="all")["records"]
        self.assertEqual([r["id"] for r in git_only], ["git:p:1"])

    def test_console_overview_is_real_and_hides_feishu_tokens(self):
        self.cfg["feishu"] = {"enabled": True, "bitables": [
            {"name": "需求池", "app_token": "secret-app-token", "table_id": "secret-table"}
        ]}
        ov = self.serve.api_console_overview(self.cfg, store.load())
        self.assertEqual(ov["today_entries"], 0)
        self.assertIn("recent", ov)
        self.assertFalse(ov["feishu_bridge"]["connected"])
        self.assertEqual(ov["admin"]["feishu"]["bitables"], [{"name": "需求池"}])
        self.assertIn("resources", ov)                    # 管理首屏单请求拿齐资源数据
        self.assertNotIn("secret-app-token", json.dumps(ov, ensure_ascii=False))

    def test_console_overview_scans_repositories_only_once(self):
        original = self.serve._repo_rows
        calls = []

        def fake_repo_rows(cfg):
            calls.append(cfg)
            return []

        self.serve._repo_rows = fake_repo_rows
        try:
            ov = self.serve.api_console_overview(self.cfg, store.load())
        finally:
            self.serve._repo_rows = original
        self.assertEqual(len(calls), 1)                    # overview 与来源诊断复用扫描结果
        self.assertIn("admin", ov)
        self.assertIn("resources", ov)

    def test_admin_action_finish_uses_lightweight_refresh_signal(self):
        original = self.serve.api_admin_overview

        def should_not_scan(*args, **kwargs):
            raise AssertionError("action response must not rebuild the full overview")

        self.serve.api_admin_overview = should_not_scan
        try:
            result = self.serve._finish_action(self.cfg, True, "done")
        finally:
            self.serve.api_admin_overview = original
        self.assertTrue(result["refresh"])
        self.assertEqual(result["overview"], {"refresh": True})

    def test_console_resources_reports_actual_components(self):
        r = self.serve.api_console_resources(self.cfg, store.load())
        ids = {x["id"] for x in r["items"]}
        self.assertEqual(ids, {"records", "index", "vault", "rss", "growth"})
        self.assertGreaterEqual(r["disk_total"], r["disk_free"])

    def test_api_admin_overview_answers_core_questions(self):
        ov = self.serve.api_admin_overview(self.cfg, store.load())
        self.assertEqual(ov["collected"]["entries"], 3)      # 采了什么
        self.assertEqual(ov["collected"]["tools"]["git"], 1)
        self.assertIn("vault", ov)
        self.assertIn(util.ENV_PATH, ov["vault"]["local_only"])   # 什么不上云
        self.assertTrue(any(x["title"] == "vault .gitignore 不完整"
                            for x in ov["broken"]))          # 哪里坏了

    def test_codebuddy_is_available_and_docs_are_folded_into_git(self):
        from loom import collectors
        self.assertIn("codebuddy", collectors.sync_names())
        self.assertFalse(config.DEFAULT_CONFIG["sources"]["codebuddy"]["enabled"])
        ov = self.serve.api_admin_overview(self.cfg, store.load())
        row = next(s for s in ov["sources"] if s["name"] == "codebuddy")
        categories = {s["name"]: s["category"] for s in ov["sources"]}
        self.assertEqual(categories["git"], "development")
        self.assertEqual(categories["feishu"], "collaboration")
        self.assertEqual(categories["notes"], "knowledge")
        self.assertNotIn("docs", categories)              # 项目文档并入 Git，不单列管理项
        git_row = next(s for s in ov["sources"] if s["name"] == "git")
        self.assertIn("项目文档", git_row["message"])
        self.assertTrue(row["available"])
        self.assertFalse(row["enabled"])
        self.assertEqual(row["status"], "off")
        self.assertTrue(any(x["label"] == "会话历史" for x in row["checks"]))
        self.assertFalse(any(x["title"] == "codebuddy" for x in ov["broken"]))

        console = self.serve.api_console_overview(self.cfg, store.load())
        self.assertEqual(console["available_sources"], len(collectors.sync_names()) - 1)
        cfg_without_git = {**self.cfg, "sources": {"git": {"enabled": False},
                                                    "docs": {"enabled": True}}}
        self.assertFalse(self.serve._source_enabled(cfg_without_git, "docs"))
        result = self.serve._manual_sync(
            self.cfg, {"source": "codebuddy", "since": "2026-07-01", "backup": False})
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["sync"]["sources"][0]["name"], "codebuddy")
        self.assertIn("已关闭", result["sync"]["sources"][0]["message"])

    def test_pi_and_opencode_are_registered_opt_in_sources(self):
        from loom import collectors
        cfg = json.loads(json.dumps(self.cfg))
        cfg["sources"] = {}
        for name in ("pi", "opencode"):
            cfg["sources"][name] = dict(config.DEFAULT_CONFIG["sources"][name])
        ov = self.serve.api_admin_overview(cfg, store.load())
        rows = {row["name"]: row for row in ov["sources"]}
        for name, key in (("pi", "sessions_dir"), ("opencode", "data_dir")):
            self.assertIn(name, collectors.sync_names())
            self.assertFalse(config.DEFAULT_CONFIG["sources"][name]["enabled"])
            self.assertEqual(rows[name]["category"], "development")
            self.assertTrue(rows[name]["available"])
            self.assertEqual(rows[name]["status"], "off")
            self.assertEqual(rows[name]["checks"][0]["label"], key)
            self.assertEqual(rows[name]["checks"][0]["value"],
                             util.expand(config.DEFAULT_CONFIG["sources"][name][key]))
            self.assertIn(key, config.DEFAULT_CONFIG["sources"][name])

    def test_admin_repo_rows_accepts_git_worktree(self):
        root = tempfile.mkdtemp(prefix="loom-admin-repo-")
        wt = tempfile.mkdtemp(prefix="loom-admin-wt-")
        env = {**os.environ, "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@x",
               "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@x"}
        subprocess.run(["git", "-C", root, "init", "-q"], check=True, env=env)
        with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as f:
            f.write("hello")
        subprocess.run(["git", "-C", root, "add", "README.md"], check=True, env=env)
        subprocess.run(["git", "-C", root, "commit", "-q", "-m", "init"],
                       check=True, env=env)
        os.rmdir(wt)
        subprocess.run(["git", "-C", root, "worktree", "add", "-q", wt],
                       check=True, env=env)

        rows = self.serve._repo_rows({"repos": [wt]})
        self.assertTrue(rows[0]["git"])

    def test_api_admin_action_guards_sensitive_config_removal(self):
        repo = tempfile.mkdtemp(prefix="loom-admin-repo-")
        self.cfg["repos"] = [repo]
        r = self.serve.api_admin_action(self.cfg, {"action": "repo_remove", "path": repo})
        self.assertFalse(r["ok"])
        self.assertEqual(r["needs_confirm"], "remove")
        self.assertEqual(self.cfg["repos"], [repo])

        r = self.serve.api_admin_action(self.cfg, {"action": "repo_remove", "path": repo,
                                                   "confirm": "remove"})
        self.assertTrue(r["ok"])
        self.assertEqual(self.cfg["repos"], [])

    def test_api_admin_action_updates_non_sensitive_config(self):
        r = self.serve.api_admin_action(self.cfg, {"action": "identity_add",
                                                   "value": "me@example.com"})
        self.assertTrue(r["ok"])
        self.assertIn("me@example.com", self.cfg["identities"]["emails"])
        r = self.serve.api_admin_action(self.cfg, {"action": "source_set",
                                                   "name": "notes", "enabled": True})
        self.assertTrue(r["ok"])
        self.assertTrue(self.cfg["sources"]["notes"]["enabled"])
        r = self.serve.api_admin_action(self.cfg, {"action": "source_set",
                                                   "name": "git", "enabled": False})
        self.assertTrue(r["ok"])
        self.assertFalse(self.cfg["sources"]["git"]["enabled"])
        git_row = next(x for x in self.serve._source_diagnostics(self.cfg)
                       if x["name"] == "git")
        self.assertEqual(git_row["status"], "off")
        source_dir = tempfile.mkdtemp(prefix="loom-source-path-")
        r = self.serve.api_admin_action(self.cfg, {"action": "source_path_set",
                                                   "name": "claude", "path": source_dir})
        self.assertTrue(r["ok"])
        self.assertEqual(self.cfg["sources"]["claude"]["projects_dir"], source_dir)
        r = self.serve.api_admin_action(self.cfg, {"action": "source_path_set",
                                                   "name": "codebuddy", "path": source_dir})
        self.assertTrue(r["ok"])
        self.assertEqual(self.cfg["sources"]["codebuddy"]["extension_data"], source_dir)
        for name, key in (("pi", "sessions_dir"), ("opencode", "data_dir")):
            r = self.serve.api_admin_action(self.cfg, {"action": "source_path_set",
                                                       "name": name, "path": source_dir})
            self.assertTrue(r["ok"])
            self.assertEqual(self.cfg["sources"][name][key], source_dir)
        r = self.serve.api_admin_action(self.cfg, {"action": "source_path_set",
                                                   "name": "docs", "path": source_dir})
        self.assertFalse(r["ok"])

    def test_manual_sync_reports_success_partial_and_error(self):
        from loom import collectors

        def ok(cfg, since):
            return [_entry("sync:ok", "2026-07-13", "p", "notes", "note", "已采集")]

        def empty(cfg, since):
            return []

        def boom(cfg, since):
            raise RuntimeError("来源连接失败")

        original = dict(collectors.REGISTRY)
        try:
            collectors.REGISTRY.clear()
            collectors.REGISTRY.update({"ok": ok, "empty": empty})
            cfg = {"vault": self.cfg["vault"], "redact": False,
                   "sources": {"ok": {"enabled": True}, "empty": {"enabled": True}}}
            result = self.serve._manual_sync(
                cfg, {"source": "all", "since": "2026-07-01", "backup": False})
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["sync"]["collected"], 1)
            self.assertEqual([r["count"] for r in result["sync"]["sources"]], [1, 0])

            collectors.REGISTRY["boom"] = boom
            cfg["sources"]["boom"] = {"enabled": True}
            result = self.serve._manual_sync(
                cfg, {"source": "all", "since": "2026-07-01", "backup": False})
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "partial")
            failed = next(r for r in result["sync"]["sources"] if r["name"] == "boom")
            self.assertEqual(failed["status"], "error")
            self.assertIn("来源连接失败", failed["message"])
            self.assertIn("sync:ok", store.load())       # 其它来源仍正常入库

            collectors.REGISTRY.clear()
            collectors.REGISTRY["boom"] = boom
            cfg["sources"] = {"boom": {"enabled": True}}
            result = self.serve._manual_sync(
                cfg, {"source": "all", "since": "2026-07-01", "backup": False})
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "error")
        finally:
            collectors.REGISTRY.clear()
            collectors.REGISTRY.update(original)

    def test_manual_sync_honors_diagnostic_partial_result(self):
        from loom import collectors
        name = "diagnostic-test"
        entry = _entry("sync:partial", "2026-07-13", "p", "git", "commit", "部分采集")
        collectors.REGISTRY[name] = lambda cfg, since: [entry]
        collectors.DIAGNOSTIC_REGISTRY[name] = lambda cfg, since: {
            "entries": [entry], "errors": ["另一个仓库读取失败"]}
        try:
            cfg = {"vault": self.cfg["vault"], "redact": False,
                   "sources": {name: {"enabled": True}}}
            result = self.serve._manual_sync(
                cfg, {"source": name, "since": "2026-07-01", "backup": False})
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["sync"]["sources"][0]["status"], "partial")
            self.assertEqual(result["sync"]["sources"][0]["count"], 1)
        finally:
            collectors.REGISTRY.pop(name, None)
            collectors.DIAGNOSTIC_REGISTRY.pop(name, None)

    def test_manual_sync_becomes_partial_when_backup_fails(self):
        from loom import cli, collectors
        name = "backup-test"
        original_backup = cli.vault_git
        collectors.REGISTRY[name] = lambda cfg, since: []
        cli.vault_git = lambda cfg, push: {
            "ok": False, "status": "error", "commit": "created", "push": "failed",
            "message": "推送失败:remote unavailable", "errors": []}
        try:
            cfg = {"vault": self.cfg["vault"], "redact": False,
                   "sources": {name: {"enabled": True}}}
            result = self.serve._manual_sync(
                cfg, {"source": name, "since": "2026-07-01", "backup": True})
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "partial")
            self.assertFalse(result["sync"]["backup"]["ok"])

            action = self.serve.api_admin_action(cfg, {"action": "vault_backup", "push": False})
            self.assertFalse(action["ok"])
            self.assertEqual(action["status"], "error")
        finally:
            cli.vault_git = original_backup
            collectors.REGISTRY.pop(name, None)

    def test_fix_mojibake(self):
        garbled = "净额".encode("utf-8").decode("latin-1")   # 模拟裸 UTF-8 过 latin-1
        self.assertEqual(self.serve._fix(garbled), "净额")
        self.assertEqual(self.serve._fix("正常ascii"), "正常ascii")

    def test_http_end_to_end(self):
        import http.client
        import re
        import threading
        from http.server import ThreadingHTTPServer
        token = "test-admin-token"
        srv = ThreadingHTTPServer(("127.0.0.1", 0), self.serve._make_handler(self.cfg, token))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
            c.request("GET", "/api/search?q=%E5%87%80%E9%A2%9D")
            hits = json.loads(c.getresponse().read())["hits"]
            self.assertEqual(len(hits), 2)                  # 两条净额相关都命中
            c.request("GET", "/api/admin/overview")
            response = c.getresponse()
            self.assertEqual(response.status, 403)                 # 旧管理接口也不得绕过 token
            self.assertEqual(json.loads(response.read())["error"], "forbidden")
            c.request("GET", "/api/admin/overview", headers={"X-Loom-Token": token})
            response = c.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["collected"]["entries"], 3)
            c.request("POST", "/api/admin/action",
                      body=json.dumps({"action": "identity_add", "value": "迪仔"}),
                      headers={"Content-Type": "application/json", "X-Loom-Token": token})
            self.assertTrue(json.loads(c.getresponse().read())["ok"])
            c.request("GET", "/")
            html_response = c.getresponse()
            page = html_response.read()
            self.assertIn("img-src 'self' data:",
                          html_response.getheader("Content-Security-Policy"))
            self.assertIn(b"loom", page[:2000])                    # 默认是零构建 Vanilla 控制台
            self.assertIn(b'id="themebtn"', page)
            self.assertIn(b'id="hdr-search"', page)               # ⌘K 顶栏搜索不跳转
            self.assertIn(b'function focusGlobalSearch', page)
            self.assertIn(b'q.focus({preventScroll:true});q.select()', page)
            self.assertIn(b'GSEARCH_SEQ++; //', page)
            self.assertIn(b"wrap.addEventListener('focusout'", page)
            self.assertNotIn(b'id="home-search-btn"', page)
            self.assertIn(b'if(!nodes.length)', page)               # 空主题不生成非法 SVG
            self.assertIn(b'class="admin-shell"', page)
            self.assertEqual(page.count(b'class="panel privacy-metric-panel"'), 2)
            self.assertIn(b'#admin-pane-privacy .admin-grid{align-items:stretch}', page)
            self.assertIn(b'data-v="home"', page)
            self.assertIn(b'data-v="ledger"', page)
            self.assertIn(b'data-v="calendar"', page)
            self.assertIn(b'data-topic-mode="relations"', page)    # 主题层级与结构关联两种视角
            self.assertIn(b"api('/api/topic-relations'", page)
            self.assertIn(b'class="drawer-related"', page)         # 详情保留主线自动关联能力
            self.assertIn(b'data-v="report"', page)                # 主线日报能力保留在 Vanilla 页面
            self.assertIn(b'id="report-export"', page)
            self.assertIn(b"action:'report_material'", page)
            self.assertIn(b'id="admin-skills"', page)              # AI skill 管理不因替换 React 而丢失
            self.assertIn(b"api('/api/admin/skills')", page)
            self.assertIn(b'id="home-sync-btn"', page)
            self.assertIn(b"search:'ledger'", page)                # 旧 hash 保持兼容
            self.assertIn(b"days:'calendar'", page)
            self.assertIn(b'--page-track:960px;--hero-track:760px;--reading-track:760px', page)
            self.assertIn(b'grid-template-columns:1fr;gap:var(--space-5)', page)
            self.assertIn(b'scrollbar-gutter:stable', page)
            self.assertIn(b'window.scrollTo(0,0)', page)
            self.assertNotIn(b'data-v="search"', page)
            self.assertNotIn(b'data-v="days"', page)
            self.assertIn(b'class="source-groups"', page)
            self.assertIn(b'data-source-category', page)
            self.assertIn(b'id="sync-options"', page)
            self.assertIn(b'id="sync-result"', page)
            self.assertIn(b'id="backup-result"', page)
            self.assertIn(b'id="drawer-backdrop"', page)
            self.assertIn(b'drawer(false,false)', page)
            self.assertIn(b'inset:var(--header-offset) 0 0', page)
            self.assertIn(b'top:var(--header-offset);right:-560px', page)
            self.assertIn(b'padding:20px;z-index:4', page)
            self.assertIn(b'header:after', page)
            self.assertIn(b'z-index:4;border-radius:0', page)
            self.assertIn(b'id="f-page-size"', page)
            self.assertIn(b'page_size:LEDGER_PAGE_SIZE', page)
            self.assertIn(b'id="ledger-pagination"', page)
            self.assertNotIn(b'function renderLedgerRecent', page)

            # 原 React 构建不再抢占首页，但仍可从 /app 访问。
            if self.serve._ui_dir():
                c.request("GET", "/app")
                app = c.getresponse().read()
                self.assertIn(b'<div id="root">', app)
                self.assertIn(b'type="module"', app)
                asset_match = re.search(rb'src="\.(/assets/[^"]+\.js)"', app)
                self.assertIsNotNone(asset_match)
                c.request("GET", asset_match.group(1).decode())
                asset_resp = c.getresponse()
                self.assertEqual(asset_resp.status, 200)
                asset_resp.read()
            c.request("GET", "/api/nope")
            self.assertEqual(c.getresponse().status, 404)
        finally:
            srv.shutdown()

    def test_concurrent_http_reads_use_isolated_entry_snapshots(self):
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        barrier = threading.Barrier(2)
        seen, stats_sizes, errors = [], [], []
        original_days, original_stats = self.serve.api_days, self.serve.api_stats

        def fake_days(by_id):
            seen.append(by_id)
            barrier.wait(timeout=5)
            by_id.clear()                                  # 只应影响本请求的快照
            barrier.wait(timeout=5)
            return {"days": []}

        def fake_stats(cfg, by_id):
            seen.append(by_id)
            barrier.wait(timeout=5)
            barrier.wait(timeout=5)
            stats_sizes.append(len(by_id))
            return {"entries": len(by_id)}

        self.serve.api_days, self.serve.api_stats = fake_days, fake_stats
        srv = ThreadingHTTPServer(("127.0.0.1", 0), self.serve._make_handler(self.cfg, "token"))
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        def request(path):
            try:
                c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=6)
                c.request("GET", path)
                response = c.getresponse()
                response.read()
                if response.status != 200:
                    raise AssertionError("unexpected HTTP status: %s" % response.status)
            except BaseException as exc:
                errors.append(exc)

        workers = [threading.Thread(target=request, args=(path,))
                   for path in ("/api/days", "/api/stats")]
        try:
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=7)
        finally:
            srv.shutdown()
            self.serve.api_days, self.serve.api_stats = original_days, original_stats
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertEqual(len(seen), 2)
        self.assertIsNot(seen[0], seen[1])
        self.assertEqual(stats_sizes, [3])

    def test_console_http_requires_token_and_sets_security_headers(self):
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        token = "test-admin-token"
        srv = ThreadingHTTPServer(("127.0.0.1", 0), self.serve._make_handler(self.cfg, token))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
            c.request("GET", "/api/console/v1/overview")
            self.assertEqual(c.getresponse().status, 403)

            c.request("GET", "/api/console/v1/overview",
                      headers={"X-Loom-Token": token})
            response = c.getresponse()
            payload = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertIn("today_entries", payload)
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            self.assertEqual(response.getheader("X-Frame-Options"), "DENY")
        finally:
            srv.shutdown()

    def test_admin_http_rejects_cross_site_or_unauthenticated_posts(self):
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        token = "test-admin-token"
        srv = ThreadingHTTPServer(("127.0.0.1", 0), self.serve._make_handler(self.cfg, token))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        body = json.dumps({"action": "identity_add", "value": "attacker@example.com"})
        try:
            c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
            c.request("POST", "/api/admin/action", body=body,
                      headers={"Content-Type": "text/plain"})
            self.assertEqual(c.getresponse().status, 403)

            c.request("POST", "/api/admin/action", body=body,
                      headers={"Content-Type": "text/plain", "X-Loom-Token": token})
            self.assertEqual(c.getresponse().status, 415)

            c.request("POST", "/api/admin/action", body=body,
                      headers={"Content-Type": "application/json", "X-Loom-Token": token,
                               "Origin": "https://evil.example"})
            self.assertEqual(c.getresponse().status, 403)
            self.assertNotIn("attacker@example.com",
                             self.cfg.get("identities", {}).get("emails", []))
        finally:
            srv.shutdown()


class RelationsTest(unittest.TestCase):
    def setUp(self):
        from loom import relations
        self.rel = relations
        self.by = {
            "claude:s1:2026-06-30": _entry(
                "claude:s1:2026-06-30", "2026-06-30", "p", "claude", "session", "改归因",
                ts="2026-06-30T09:00:00", start="2026-06-30T09:00:00",
                end="2026-06-30T10:00:00"),
            "claude:s1:2026-07-01": _entry(
                "claude:s1:2026-07-01", "2026-07-01", "p", "claude", "session", "续聊",
                ts="2026-07-01T09:00:00", start="2026-07-01T09:00:00",
                end="2026-07-01T09:30:00"),
            "git:p:aaa": _entry("git:p:aaa", "2026-06-30", "p", "git", "commit", "fix",
                                ref="aaa", ts="2026-06-30T09:30:00",
                                file_list=[{"path": "src/attr.py"}, {"path": "README.md"}]),
            "git:p:bbb": _entry("git:p:bbb", "2026-06-30", "p", "git", "commit", "more",
                                ref="bbb", ts="2026-06-30T14:00:00",
                                file_list=[{"path": "src/attr.py"}]),
            "doc:p:src/attr.py": _entry("doc:p:src/attr.py", "2026-06-30", "p", "docs",
                                        "doc", "attr doc", path="src/attr.py"),
            "git:other:ccc": _entry("git:other:ccc", "2026-06-30", "other", "git",
                                    "commit", "unrelated", ref="ccc",
                                    ts="2026-06-30T09:30:00", file_list=[{"path": "z.py"}]),
        }

    def _ids(self, eid):
        return {h["id"] for h in self.rel.neighbors(self.by, eid)}

    def test_session_produces_in_window_commit(self):
        # 会话时段内、同项目的提交被关联;跨项目的不关联
        n = self._ids("claude:s1:2026-06-30")
        self.assertIn("git:p:aaa", n)          # 09:30 落在 09:00–10:00
        self.assertNotIn("git:other:ccc", n)   # 别的项目不算

    def test_commit_reverse_links_session(self):
        self.assertIn("claude:s1:2026-06-30", self._ids("git:p:aaa"))

    def test_commit_cochange_shared_file(self):
        n = self.rel.neighbors(self.by, "git:p:aaa")
        bbb = [h for h in n if h["id"] == "git:p:bbb"][0]
        self.assertTrue(any("共改" in r for r in bbb["reasons"]))

    def test_commit_links_doc_by_path(self):
        self.assertIn("doc:p:src/attr.py", self._ids("git:p:aaa"))

    def test_session_thread_same_sid(self):
        self.assertIn("claude:s1:2026-07-01", self._ids("claude:s1:2026-06-30"))

    def test_out_of_window_commit_not_session_output(self):
        # bbb 在 14:00,不在会话时段 → 不因"会话产出"关联(但可因共改/被文档间接出现)
        n = [h for h in self.rel.neighbors(self.by, "claude:s1:2026-06-30")]
        self.assertNotIn("git:p:bbb", {h["id"] for h in n})

    def test_unknown_id_returns_empty(self):
        self.assertEqual(self.rel.neighbors(self.by, "nope:x"), [])

    def test_ranked_by_score_desc(self):
        scores = [h["score"] for h in self.rel.neighbors(self.by, "git:p:aaa")]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_global_graph_derives_complete_unique_edges(self):
        graph = self.rel.global_graph(self.by)
        self.assertEqual(graph["total_entries"], len(self.by))
        self.assertEqual(graph["total_nodes"], 5)  # unrelated commit is omitted
        self.assertEqual(graph["total_edges"], 5)
        pairs = {(e["source"], e["target"]) for e in graph["edges"]}
        self.assertEqual(len(pairs), graph["shown_edges"])

    def test_global_graph_caps_visible_nodes_without_dangling_edges(self):
        graph = self.rel.global_graph(self.by, max_nodes=3, max_edges=2)
        node_ids = {node["id"] for node in graph["nodes"]}
        self.assertLessEqual(len(node_ids), 3)
        self.assertLessEqual(len(graph["edges"]), 2)
        self.assertTrue(all(e["source"] in node_ids and e["target"] in node_ids
                            for e in graph["edges"]))


class McpTest(unittest.TestCase):
    def setUp(self):
        from loom import mcp
        self.mcp = mcp
        self.cfg = {"vault": {"dir": tempfile.mkdtemp(prefix="loom-vault-")}}

    def _call(self, method, params=None, rid=1):
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        return self.mcp.handle(msg, self.cfg)

    def test_initialize_advertises_tools(self):
        r = self._call("initialize", {})
        self.assertEqual(r["result"]["serverInfo"]["name"], "loom")
        self.assertIn("tools", r["result"]["capabilities"])

    def test_initialized_notification_no_response(self):
        # 通知(无 id)不回响应
        self.assertIsNone(self.mcp.handle(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}, self.cfg))

    def test_tools_list(self):
        names = {t["name"] for t in self._call("tools/list")["result"]["tools"]}
        self.assertEqual(names, {"loom_search", "loom_related", "loom_topic_ls",
                                 "loom_topic_show", "loom_today", "loom_note"})

    def test_search_tool_returns_text_content(self):
        r = self._call("tools/call", {"name": "loom_search",
                                      "arguments": {"term": "不存在的词xyz"}})
        self.assertEqual(r["result"]["content"][0]["type"], "text")
        self.assertIn("无命中", r["result"]["content"][0]["text"])

    def test_unknown_tool_is_error(self):
        r = self._call("tools/call", {"name": "nope", "arguments": {}})
        self.assertEqual(r["error"]["code"], -32602)

    def test_unknown_method_is_error(self):
        self.assertEqual(self._call("bogus")["error"]["code"], -32601)

    def test_tool_exception_returned_as_iserror_not_crash(self):
        # 工具内部异常 → isError 结果,连接不崩(topic_show 无 vault 目录也不抛到顶)
        r = self._call("tools/call", {"name": "loom_topic_show",
                                      "arguments": {"topic": "任意"}})
        self.assertEqual(r["result"]["content"][0]["type"], "text")   # 有结果,未变成协议错误

    def test_serve_loop_reads_and_writes_ndjson(self):
        import io
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
        stdout = io.StringIO()
        self.mcp.serve(self.cfg, stdin=stdin, stdout=stdout)
        out_lines = [l for l in stdout.getvalue().splitlines() if l.strip()]
        self.assertEqual(len(out_lines), 2)              # initialize + tools/list;通知不回
        self.assertEqual(json.loads(out_lines[0])["id"], 1)
        self.assertEqual(json.loads(out_lines[1])["id"], 2)

    def test_serve_parse_error_on_bad_json(self):
        import io
        stdout = io.StringIO()
        self.mcp.serve(self.cfg, stdin=io.StringIO("not json\n"), stdout=stdout)
        self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main(verbosity=2)
