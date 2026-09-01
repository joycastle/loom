# -*- coding: utf-8 -*-
"""配置读写 + 增删助手 + 飞书 URL 解析。config.json 靠子命令管理,免手编。"""
import copy
import json
import os
import re
import subprocess

from . import util

# 记录每个 config.json 上一次 load/save 时的 (mtime, 快照),用于保存前检测"自我们
# 加载以来是否有别的进程(并发的 CLI)改过磁盘"。GUI 常驻内存、CLI 随手写,二者
# 共用同一 ~/.loom;没有这道守卫,GUI 的下次 save 会用启动快照整体覆盖 CLI 的改动
# (last-writer-wins)。按路径分键,避免多 LOOM_HOME(测试)相互串。
_BASELINE = {}

DEFAULT_CONFIG = {
    # watchlist:我负责的项目/表名/领域词。飞书群消息命中即算"和我相关"(哪怕
    # 没点名我),用来把话题相关但没@我的内容也捞进周报。子串匹配,大小写不敏感。
    "owner": {"name": "", "feishu_name": "", "watchlist": []},
    "identities": {"emails": [], "names": []},
    "default_since_days": 100,
    "redact": True,          # 采集入库前抹掉 token/密钥值(推云端/Basic Memory 防泄露);私有可信仓可设 false
    "repos": [],
    "sources": {
        "git":       {"enabled": True},
        "claude":    {"enabled": True, "projects_dir": "~/.claude/projects"},
        "codex":     {"enabled": True, "homes": ["~/.codex"]},
        "cursor":    {"enabled": True, "app_support": "~/Library/Application Support/Cursor",
                      # 临时/worktree 目录不算项目名(路径含这些片段就跳过);可覆盖。
                      "scratch_path_patterns": ["/private/tmp/", "/scratchpad/", "/wt-"]},
        "codebuddy": {
            "enabled": False,
            "app_support": "~/Library/Application Support/CodeBuddy",
            "extension_data": "~/Library/Application Support/CodeBuddyExtension/Data",
        },
        "pi":        {"enabled": False, "sessions_dir": "~/.pi/agent/sessions"},
        "opencode":  {"enabled": False, "data_dir": "~/.local/share/opencode"},
        # 通过已登录的 lark-cli 读取 Bridge 绑定群；默认关闭，避免升级后扩大采集。
        "codex_feishu_bridge": {
            "enabled": False,
            "home": "~/.feishu-codex-bridge",
            "user_open_id": "",
        },
        "docs":      {"enabled": True},   # 索引各仓 .md(全文归档,不进日记)
        "notes":     {"enabled": True},   # 索引 vault/notes/ 手动加的文档(loom doc add 闭环)
        # 飞书主动采集(user OAuth,以我身份拉我可见的群/私聊)。默认关闭:自带飞书
        # 应用(BYO),申请 user scope 发版 + `loom feishu login` 后才生效。
        "feishu_user": {
            "enabled": False,
            "base_url": "https://open.feishu.cn",           # token / IM 端点
            "authorize_base": "https://accounts.feishu.cn",  # 授权页(第一步拿 code)
            "redirect_port": 8788,
            "scopes": ["im:chat:readonly", "im:message:readonly",
                       "offline_access"],
            # 相关性过滤:只留和我有关的群消息。源码只留机制,这里是全部策略,零配置
            # 即可跑;简单项(静音群/重要人)默认空、自己填,高级项(阈值/权重/噪音词)
            # 给通用默认、想调再改。关注词表复用顶层 owner.watchlist。
            "relevance": {
                "mute_chats": [],    # 静音的群(群名子串或 chat_id),命中直接丢
                "vip_senders": [],   # 重要的人(open_id),命中永久保留
                "keep_score": 8,     # 达标线:分数≥它,或我发的/VIP,才留原文
                "noise_prefixes": ["欢迎", "入职", "收到", "好的", "谢谢",
                                    "辛苦", "哈哈", "赞"],
                "weights": {
                    "mentioned_me": 30, "reply_to_me": 25, "my_thread": 15,
                    "p2p": 10, "small_group_5": 8, "small_group_15": 4,
                    "watchlist_hit": 8, "cross_source_hit": 5,
                    "mention_all": -20, "bot_sender": -10, "noise_penalty": -15,
                },
                "cross_source": {"enabled": True, "min_count": 2},
                "stop_words": [],    # 追加到内置英文停用词表(领域通用词,不必复制默认)
            },
        },
    },
    "feishu": {
        "enabled": False,
        "base_url": "https://open.feishu.cn/open-apis",
        "bitables": [],
        # 多维表格默认列名(不同团队叫法不同,可覆盖);add_bitable 只读这里、不写死。
        "bitable_field_defaults": {
            "person_field": "需求负责人", "date_field": "预计完成时间",
            "title_field": "需求描述", "status_field": "需求状态",
        },
    },
    # relations:结构边权重(会话产出/共改文件/改文档/同会话续接)。源码只留机制。
    "relations": {"weights": {
        "session_commit": 3.0, "shared_file_base": 1.0, "shared_file_per": 0.3,
        "commit_doc": 2.0, "session_continue": 2.5,
    }},
    # report:日报出料 + 跨源聚类的**全部策略**(词表/权重/阈值),源码只留机制。
    "report": {
        "importance_tiers": {"high": 15, "mid": 8},  # 决定簇展开/一句带过(跨源簇易过线)
        "section_keywords": {                        # 把 AI 日报按标题切段的关键词
            "work": ["工作", "进度", "完成", "做了"],
            "thinking": ["思考", "心得", "问题", "复盘"],
            "plan": ["明日", "明天", "计划", "下一步", "next", "todo"],
        },
        "column_keywords": {                         # 导入飞书日报 xlsx 的列名匹配
            "date": ["提交时间", "日期"],
            "work": ["今日工作", "工作与进度", "今日进度"],
            "thinking": ["今日思考", "思考", "问题与心得"],
            "plan": ["明日", "明天", "计划"],
        },
        "cluster": {                                 # 跨源聚类策略(全可调)
            "jaccard_min": 0.35, "edge_min": 3.0, "id_owners_max": 3,
            "topic_owners_max": 6, "big_cluster": 8,
            "weights": {
                "strong": 4.0, "weak": 1.5, "topic_rare": 3.5, "topic_common": 2.0,
                "rel_continue": 4.0, "rel_touch": 3.0, "rel_shared_file": 2.5,
                "rel_time": 1.0,
            },
            # 重要度权重:偏向"跨源多样 + 个人关注",而非"提交数量"。degree/member_count
            # 是量的信号(单源刷一堆小提交也会高),压低;kind_diversity(同一件事被几种
            # 来源印证=真的重要)与 keyword_hit(命中关注词=对本职有分量)拉高。
            "score_weights": {
                "degree": 0.3, "member_count": 0.3, "kind_diversity": 6.0,
                "span_days": 1.0, "file_changes": 0.02, "keyword_hit": 3.0,
            },
            # 泛化 id:出现在一堆条目里但不代表"同一件事",不作聚类标识符。
            # 用户在私有 config 的 generic_ids_extra 追加自己项目特有的噪音词。
            "generic_ids": ["agents", "readme", "onboarding", "handoff", "changelog",
                            "license", "contributing", "index", "main", "roadmap",
                            "todo", "notes", "agents.md", "readme.md", "readme.en.md",
                            "onboarding.md", "handoff.md", "claude.md", "documents",
                            "desktop", "github", "gitlab", "http", "https", "private",
                            "public", "prototype", "source", "apps", "assets", "build",
                            "dist", "node_modules", "package", "config", "jsonl",
                            "json", "sqlite", "since", "until", "month", "week",
                            "journal", "vault", "local", "loom",
                            # 常见英文/代码散词:出现在 commit 正文里,不代表"同一件事",
                            # 别当共享标识符(否则造 nothing/external 之类垃圾标签与假边)。
                            "absent", "abspath", "actively", "after", "alone", "already",
                            "always", "another", "append", "before", "business", "candidates",
                            "carry", "circuit", "cleaner", "collected", "common", "concatenating",
                            "curated", "default", "defaults", "editable", "enable", "everyone",
                            "exclude", "external", "guardian", "mentions", "nothing", "reviews",
                            "scaffold", "search", "session", "stage", "suggests", "value"],
            "generic_ids_extra": [],
        },
    },
    # 从 util.HOME(尊重 LOOM_HOME)派生,而非硬编码 ~/.loom/vault——否则临时
    # LOOM_HOME 下 ~ 仍解析到真实家目录,测试会误写真实 vault(曾导致真配置被污染)。
    "vault": {"dir": os.path.join(util.HOME, "vault"), "remote": ""},
}


def _mtime_ns(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def _remember(cfg):
    """记下本次 load/save 的 (mtime, 快照),作为下次 save 的三方合并基线。"""
    _BASELINE[util.CONFIG_PATH] = {
        "mtime": _mtime_ns(util.CONFIG_PATH),
        "snapshot": copy.deepcopy(cfg),
    }


def _merge_external(ours, base, theirs):
    """把磁盘上 `theirs` 相对 `base` 的外部改动就地并入内存 `ours`。
    规则:本次(ours 相对 base)改过的键 → 保留 ours(本次操作优先);ours 没碰过的键
    → 采纳 theirs 的外部改动(含新增/删除)。dict 递归,list/标量整体处理。"""
    if not (isinstance(ours, dict) and isinstance(base, dict) and isinstance(theirs, dict)):
        return
    for k, tv in theirs.items():
        bv = base.get(k)
        ov = ours.get(k)
        if isinstance(tv, dict) and isinstance(ov, dict) and isinstance(bv, dict):
            _merge_external(ov, bv, tv)
        elif k not in ours or ov == bv:
            ours[k] = copy.deepcopy(tv)   # ours 没动 → 采纳外部值
        # else: ours 改过(ov != bv)→ 冲突,保留 ours
    for k in list(ours.keys()):           # theirs 删掉、且 ours 没改的键 → 一并删
        if k in base and k not in theirs and ours.get(k) == base.get(k):
            del ours[k]


def load():
    if not os.path.exists(util.CONFIG_PATH):
        fresh = json.loads(json.dumps(DEFAULT_CONFIG))
        _remember(fresh)
        return fresh
    with open(util.CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    # 补齐缺省键,便于旧配置平滑升级
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    # 旧版本允许单独关闭 docs。迁移到“项目文档并入 Git”之前先继承这项
    # 明确选择，不能因为补入默认 git=true 就悄悄恢复全文采集。
    old_sources = cfg.get("sources", {})
    old_docs = old_sources.get("docs", {}) if isinstance(old_sources, dict) else {}
    _deep_update(merged, cfg)
    # Codex 支持用 CODEX_HOME 隔离多套环境。早期 Loom 只允许单个 home；
    # 载入时兼容转换为 homes 列表，不移动任何 Codex 原始会话。
    old_codex = old_sources.get("codex", {}) if isinstance(old_sources, dict) else {}
    if isinstance(old_codex, dict) and "homes" not in old_codex and old_codex.get("home"):
        merged["sources"]["codex"]["homes"] = [old_codex["home"]]
    merged["sources"]["codex"].pop("home", None)
    # 早期开发版使用了含糊的 feishu_bridge 名称；迁到项目全称，避免以后
    # 接入其它 Bridge 时配置和记录来源撞名。
    if isinstance(old_sources, dict) and "feishu_bridge" in old_sources:
        if "codex_feishu_bridge" not in old_sources:
            merged["sources"]["codex_feishu_bridge"] = old_sources["feishu_bridge"]
        merged["sources"].pop("feishu_bridge", None)
    if isinstance(old_docs, dict) and "enabled" in old_docs:
        if old_docs["enabled"] is False:
            # 隐私上采取保守迁移：旧 docs=false 优先，宁可暂停组合来源，
            # 也不能在升级后扩大采集范围。用户重新开启 Git 时会同时对齐两项。
            merged["sources"]["git"]["enabled"] = False
        elif isinstance(old_sources, dict) and "git" not in old_sources:
            merged["sources"]["git"]["enabled"] = True
    _remember(merged)
    return merged


def save(cfg):
    os.makedirs(util.HOME, exist_ok=True)
    # 并发守卫:若磁盘自我们加载以来被别的进程(CLI)改过,先把它的外部改动并进来,
    # 再落盘——避免用陈旧的内存快照整体覆盖(last-writer-wins),保持 App↔CLI 一致。
    prev = _BASELINE.get(util.CONFIG_PATH)
    if prev and prev["mtime"] is not None:
        cur = _mtime_ns(util.CONFIG_PATH)
        if cur is not None and cur != prev["mtime"]:
            try:
                with open(util.CONFIG_PATH, encoding="utf-8") as f:
                    theirs = json.load(f)
            except Exception:
                theirs = None
            if isinstance(theirs, dict):
                _merge_external(cfg, prev["snapshot"], theirs)
    tmp = f"{util.CONFIG_PATH}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, util.CONFIG_PATH)
    _remember(cfg)


def _deep_update(base, overlay):
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def source_enabled(cfg, name):
    """Return the product-level switch state for a collector.

    Repository documents are presented as part of Git in the console, so Git is
    their single source of truth even when an older config still contains a
    separate ``sources.docs.enabled`` value.
    """
    if name in ("git", "docs"):
        sources = cfg.get("sources", {})
        docs = sources.get("docs", {})
        if isinstance(docs, dict) and docs.get("enabled") is False:
            return False
        if "git" in sources:
            return bool(sources.get("git", {}).get("enabled", True))
        # 未经 config.load() 合并的旧配置也要尊重显式 docs 选择。
        if isinstance(docs, dict) and "enabled" in docs:
            return bool(docs["enabled"])
        return True
    if name == "feishu":
        return bool(cfg.get("feishu", {}).get("enabled"))
    return bool(cfg.get("sources", {}).get(name, {}).get("enabled"))


def codex_homes(cfg):
    """返回去重后的 Codex home 列表；兼容旧版单数 ``home`` 配置。"""
    src = cfg.get("sources", {}).get("codex", {})
    raw = src.get("homes")
    if isinstance(raw, str):
        raw = [raw]
    elif not isinstance(raw, (list, tuple)):
        legacy = src.get("home")
        raw = [legacy] if legacy else ["~/.codex"]

    homes, seen = [], set()
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            continue
        path = os.path.abspath(util.expand(value.strip()))
        key = os.path.normcase(path)
        if key not in seen:
            seen.add(key)
            homes.append(path)
    return homes


def vault_dir(cfg):
    return util.expand(cfg["vault"]["dir"])


def journal_dir(cfg):
    return os.path.join(vault_dir(cfg), "journal")


def notes_dir(cfg):
    custom = cfg.get("sources", {}).get("notes", {}).get("dir", "")
    return util.expand(custom) if custom else os.path.join(vault_dir(cfg), "notes")


# ---- 增删助手 ----
def git_worktree_info(path):
    """Return canonical Git worktree metadata; reject bare and non-repositories."""
    path = os.path.abspath(util.expand(path))
    if not os.path.isdir(path):
        return None
    try:
        inside = subprocess.run(
            ["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        common = subprocess.run(
            ["git", "-C", path, "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=10)
        root = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if common.returncode != 0 or root.returncode != 0:
        return None
    common_dir = common.stdout.strip()
    if not os.path.isabs(common_dir):
        common_dir = os.path.join(path, common_dir)
    return {"path": path, "root": os.path.realpath(root.stdout.strip()),
            "common_dir": os.path.realpath(common_dir)}


def add_repo(cfg, path):
    requested = os.path.abspath(util.expand(path))
    path = requested
    info = git_worktree_info(path)
    if not info:
        raise ValueError(f"{path} 不是 git 仓")
    # Always persist the canonical worktree root.  Callers such as the local
    # Agent may discover a nested directory inside a repository; saving that
    # arbitrary child path makes later diagnostics and deduplication unstable.
    # Preserve the user's lexical spelling when they selected the worktree root
    # itself (macOS commonly aliases /var to /private/var).  Nested selections
    # are still normalized to the repository root.
    try:
        selected_root = os.path.samefile(requested, info["root"])
    except OSError:
        selected_root = False
    path = requested if selected_root else info["root"]
    info = git_worktree_info(path)
    if not info:  # Repository state changed between the two fixed probes.
        raise ValueError(f"{path} 不是 git 仓")
    for existing in cfg["repos"]:
        other = git_worktree_info(existing)
        if other and other["common_dir"] == info["common_dir"] and other["path"] != path:
            raise ValueError(f"{path} 与已配置的 {other['path']} 属于同一 Git 仓库")
    if path not in cfg["repos"]:
        cfg["repos"].append(path)
    return path


def rm_repo(cfg, path):
    path = os.path.abspath(util.expand(path))
    cfg["repos"] = [r for r in cfg["repos"] if r != path]


def scan_repos(root):
    """在 root 下(深度<=3)找所有 .git 仓,返回仓根路径列表。"""
    root = util.expand(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth > 3:
            dirnames[:] = []
            continue
        if ".git" in dirnames or ".git" in filenames:
            if git_worktree_info(dirpath):
                found.append(dirpath)
        if ".git" in dirnames:
            dirnames[:] = [d for d in dirnames if d != ".git"]
    return sorted(set(found))


FEISHU_TOKEN_RE = re.compile(r"(?:/base/|/wiki/|obj_token=)([A-Za-z0-9]{20,})")
FEISHU_TABLE_RE = re.compile(r"[?&]table=([A-Za-z0-9]+)")


def parse_bitable_url(url):
    """从多维表格 URL 解析 (app_token, table_id)。table 缺失时返回 None,需另填。"""
    m = FEISHU_TOKEN_RE.search(url)
    app_token = m.group(1) if m else None
    t = FEISHU_TABLE_RE.search(url)
    table_id = t.group(1) if t else None
    return app_token, table_id


def add_bitable(cfg, name, app_token, table_id, **fields):
    # 列名默认走配置(不同团队叫法不同),源码不写死具体业务列名。
    fd = dict(DEFAULT_CONFIG["feishu"]["bitable_field_defaults"])
    fd.update(cfg.get("feishu", {}).get("bitable_field_defaults", {}) or {})
    b = {
        "name": name,
        "app_token": app_token,
        "table_id": table_id,
        "person_field": fields.get("person_field", fd["person_field"]),
        "date_field": fields.get("date_field", fd["date_field"]),
        "title_field": fields.get("title_field", fd["title_field"]),
        "status_field": fields.get("status_field", fd["status_field"]),
    }
    cfg["feishu"]["enabled"] = True
    cfg["feishu"]["bitables"] = [x for x in cfg["feishu"]["bitables"] if x["name"] != name]
    cfg["feishu"]["bitables"].append(b)
    return b
