# -*- coding: utf-8 -*-
"""Registry of AI coding agents and where the loom-skill installs for each.

One place answers "where does agent X live, is it present, and which file does
the loom-skill go into". Both the skill installer (``loom/skillsync.py``) and
future callers import this; the collectors already resolve each agent's *data*
home, and we reuse those same config keys here so nothing is hardcoded twice.

Two important nuances, verified by probing the real machine at implementation
time (2026-07, read-only) rather than trusting docs:

* An agent's **instruction / skill home** is not always the same directory the
  collector reads *session history* from. Claude and Codex keep both under one
  dotfile home (``~/.claude`` / ``~/.codex``), so we derive the skill home from
  the collector's config. Cursor and CodeBuddy keep session history under macOS
  ``Application Support`` but keep user rules / ``AGENTS.md`` under a ``~/.cursor``
  / ``~/.codebuddy`` dotfile home — a genuinely different location, exposed here
  as an overridable ``config_home`` source key (defaulted, never duplicated from
  the collector's data path).

* Prefer a **dedicated file loom owns outright** (write / overwrite / delete)
  over a marker block inside a shared file, because it can never interleave with
  the user's own content. We fall back to a marker block only where the agent has
  no user-writable skills directory (CodeBuddy today).

Findings encoded below (the 3 unknowns from the design):

* **Codex** ``~/.codex/skills/`` exists; ``.system/`` is a reserved system tree
  (``.codex-system-skills.marker``) holding built-in skills, and the bundled
  ``skill-installer`` skill documents personal skills as
  ``$CODEX_HOME/skills/<name>/SKILL.md``. So a dedicated ``skills/loom/`` dir is
  the right, safe, reversible target.
* **CodeBuddy** has **no** personal skills dir — only the package-manager-owned
  ``skills-marketplace/`` (its own ``version.txt`` / ``marketplace.json``), which
  we must never write into. ``~/.codebuddy/AGENTS.md`` *is* auto-loaded in full,
  so we fall back to a marker block there.
* **Cursor** ships a Cursor-*managed* ``~/.cursor/skills-cursor/`` (has
  ``.cursor-managed-skills-manifest.json`` / ``.sync-manifest.json``) that Cursor
  syncs and would clobber — unsafe to write into. The dedicated, loom-owned
  ``~/.cursor/rules/loom.mdc`` (frontmatter + ``alwaysApply``) is confirmed
  working today and remains functional across the ``.mdc`` → ``RULE.md``
  migration, so it is the safest reversible target.
"""
import os

from . import util


# Rendered-content formats (see loom/skillsync.py for the renderers).
FMT_SKILL = "skill"   # Anthropic Agent-Skills SKILL.md (name + description + body)
FMT_MDC = "mdc"       # Cursor rules file (description + alwaysApply + body)
FMT_MARKER = "marker" # marker-delimited block inside a shared file

# Install strategies.
STRAT_DEDICATED = "dedicated"  # a file/dir loom owns: write / overwrite / delete
STRAT_MARKER = "marker"        # a block inside a user-owned shared file


class AgentSpec:
    """Static description of one agent + how the loom-skill installs into it.

    ``home(cfg)`` resolves the agent's instruction/skill home (respecting config
    overrides so tests can point at a temp dir). ``target_path(cfg)`` is the exact
    file loom reads/writes; ``owns_dir(cfg)`` (dedicated only) is the directory to
    remove on uninstall if it ends up empty.
    """

    def __init__(self, key, label, label_en, home_resolver, rel_target,
                 fmt, strategy, rel_owns_dir=None):
        self.key = key
        self.label = label
        self.label_en = label_en
        self._home_resolver = home_resolver
        self.rel_target = rel_target
        self.fmt = fmt
        self.strategy = strategy
        self.rel_owns_dir = rel_owns_dir

    def home(self, cfg):
        return self._home_resolver(cfg)

    def detect(self, cfg):
        """Is this agent present on the machine? (its home dir exists)."""
        home = self.home(cfg)
        return bool(home) and os.path.isdir(home)

    def target_path(self, cfg):
        return os.path.join(self.home(cfg), *self.rel_target.split("/"))

    def owns_dir(self, cfg):
        if not self.rel_owns_dir:
            return None
        return os.path.join(self.home(cfg), *self.rel_owns_dir.split("/"))


# ---- per-agent home resolvers (reuse the collectors' configured paths) ----
def _claude_home(cfg):
    # The collector configures projects_dir (~/.claude/projects); the skill home
    # is its parent, i.e. the ~/.claude dotfile home.
    src = cfg.get("sources", {}).get("claude", {})
    projects = util.expand(src.get("projects_dir", "~/.claude/projects"))
    return os.path.dirname(projects.rstrip("/") or projects)


def _codex_home(cfg):
    # Codex keeps sessions, AGENTS.md and skills all under the same $CODEX_HOME.
    src = cfg.get("sources", {}).get("codex", {})
    return util.expand(src.get("home", "~/.codex"))


def _cursor_home(cfg):
    # Cursor session history lives in Application Support (that is what the
    # collector reads), but user rules live in the ~/.cursor dotfile home.
    # Overridable via sources.cursor.config_home (default ~/.cursor).
    src = cfg.get("sources", {}).get("cursor", {})
    return util.expand(src.get("config_home", "~/.cursor"))


def _codebuddy_home(cfg):
    # IDE history is under Application Support (collector); AGENTS.md / CLI config
    # live in the ~/.codebuddy dotfile home. Overridable via
    # sources.codebuddy.config_home (default ~/.codebuddy).
    src = cfg.get("sources", {}).get("codebuddy", {})
    return util.expand(src.get("config_home", "~/.codebuddy"))


REGISTRY = {
    "claude": AgentSpec(
        "claude", "Claude Code", "Claude Code",
        _claude_home, "skills/loom/SKILL.md",
        FMT_SKILL, STRAT_DEDICATED, rel_owns_dir="skills/loom"),
    "codex": AgentSpec(
        "codex", "Codex CLI", "Codex CLI",
        _codex_home, "skills/loom/SKILL.md",
        FMT_SKILL, STRAT_DEDICATED, rel_owns_dir="skills/loom"),
    "cursor": AgentSpec(
        "cursor", "Cursor", "Cursor",
        _cursor_home, "rules/loom.mdc",
        FMT_MDC, STRAT_DEDICATED),
    "codebuddy": AgentSpec(
        "codebuddy", "CodeBuddy", "CodeBuddy",
        _codebuddy_home, "AGENTS.md",
        FMT_MARKER, STRAT_MARKER),
}

# Stable display order for CLI/GUI.
ORDER = ["claude", "codex", "cursor", "codebuddy"]


def all_keys():
    return list(ORDER)


def get(key):
    try:
        return REGISTRY[key]
    except KeyError:
        raise ValueError(f"未知 agent: {key}(可选:{', '.join(ORDER)}、all)")
