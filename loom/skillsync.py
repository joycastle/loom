# -*- coding: utf-8 -*-
"""Hot-pluggable install / uninstall of the loom-skill into AI coding agents.

One core, shared by the CLI (``loom skill …``) and the desktop GUI (a sidecar
endpoint) so neither re-implements the logic. Design contract:

* **One canonical source** — ``skills/loom-skill/SKILL.md`` — rendered per agent
  into the format that agent reads (SKILL.md / Cursor ``.mdc`` / a marker block).
* **Dedicated files loom owns** (Claude/Codex skills dir, Cursor rules file) are
  written / overwritten / deleted outright. **Shared files** (CodeBuddy
  ``AGENTS.md``) get an idempotent, HTML-comment-delimited marker block —
  conda-init style — so everything outside the block is the user's and is never
  touched.
* **Idempotent**: installing twice makes no further change; install → uninstall
  → install reproduces the same bytes.
* **Drift-safe**: the version + a SHA-256 of exactly what loom last wrote is
  recorded in the single state file ``~/.loom/config.json``. Before overwriting
  content that no longer matches that hash (a user or another tool edited it), we
  first write a timestamped ``.loom-backup-<stamp>`` and flag the drift — never a
  blind clobber.
* **Reversible**: uninstall is the provable inverse — delete the dedicated file
  (and its now-empty dir) or strip exactly the marker block, leaving the rest of
  a shared file byte-for-byte intact.

Pure functions, side-effect-scoped by their arguments, unit-testable against a
temp HOME + temp agent homes (see tests/test_skillsync.py). Never writes a real
agent directory unless the caller passed real paths.
"""
import hashlib
import os
import re
import shutil
from datetime import datetime

from . import agents, config, util

MARKER_VERSION = 1
_MARK_END = "<!-- <<< loom-skill <<< -->"
_BLOCK_RE = re.compile(
    r"<!-- >>> loom-skill v\d+ >>> -->.*?<!-- <<< loom-skill <<< -->", re.S)


def _mark_begin(version=MARKER_VERSION):
    return f"<!-- >>> loom-skill v{version} >>> -->"


# ---------------------------------------------------------------- canonical
def _canonical_path():
    """Path to the single authoritative loom-skill source.

    ``LOOM_SKILL_SOURCE`` overrides it (used by packaging / tests); otherwise it
    is ``<repo>/skills/loom-skill/SKILL.md`` relative to this package.
    """
    override = (os.environ.get("LOOM_SKILL_SOURCE") or "").strip()
    if override:
        return util.expand(override)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "skills", "loom-skill", "SKILL.md")


def _read_canonical():
    path = _canonical_path()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到 loom-skill 源文件:{path}")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _parse_canonical(text):
    """Return (name, description, body) from the canonical SKILL.md frontmatter."""
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        raise ValueError("canonical SKILL.md 缺少 YAML frontmatter")
    front, body = m.group(1), m.group(2).strip("\n")
    meta = {}
    for line in front.splitlines():
        if line and not line[0].isspace() and ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta.get("name", "loom"), meta.get("description", ""), body


# ---------------------------------------------------------------- rendering
def _render_skill(name, desc, body):
    return f"---\nname: {name}\ndescription: {desc}\n---\n\n{body}\n"


def _render_mdc(desc, body):
    return f"---\ndescription: {desc}\nalwaysApply: true\n---\n\n{body}\n"


def _render_marker_block(body):
    return f"{_mark_begin()}\n{body}\n{_MARK_END}"


def render(agent_key):
    """Render the loom-skill for one agent.

    For dedicated targets this is the full file content; for marker targets it is
    the marker block that gets spliced into the shared file.
    """
    spec = agents.get(agent_key)
    name, desc, body = _parse_canonical(_read_canonical())
    if spec.fmt == agents.FMT_SKILL:
        return _render_skill(name, desc, body)
    if spec.fmt == agents.FMT_MDC:
        return _render_mdc(desc, body)
    if spec.fmt == agents.FMT_MARKER:
        return _render_marker_block(body)
    raise ValueError(f"未知渲染格式:{spec.fmt}")


# ---------------------------------------------------------------- fs helpers
def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.loom-tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_text(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def _backup(path):
    """Timestamped single-shot backup of a file about to be overwritten."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = f"{path}.loom-backup-{stamp}"
    # Extremely unlikely collision within the same second → add a counter.
    n = 1
    while os.path.exists(dest):
        dest = f"{path}.loom-backup-{stamp}-{n}"
        n += 1
    shutil.copy2(path, dest)
    return dest


def _splice_block(text, block):
    if _BLOCK_RE.search(text):
        return _BLOCK_RE.sub(lambda _m: block, text, count=1)
    if not text:
        return block + "\n"
    sep = "\n" if text.endswith("\n") else "\n\n"
    return text + sep + block + "\n"


def _remove_block(text):
    """Strip exactly the loom block, restoring the join install created.

    Only the block and the separator install inserted at its junction are
    touched — every other byte of the user's file is preserved (no
    document-wide whitespace normalization). Install always inserts the block
    at the end preceded by one separator and followed by a single newline, so
    for the common end-of-file case this is the exact inverse.
    """
    m = _BLOCK_RE.search(text)
    if not m:
        return text  # nothing of ours here → leave the file untouched
    before, after = text[:m.start()], text[m.end():]
    before_has, after_has = bool(before.strip("\n")), bool(after.strip("\n"))
    if not before_has and not after_has:
        return ""  # file held only our block (+ blank lines) → empty it
    if not after_has:  # block at end (install's normal placement)
        return before.rstrip("\n") + "\n"
    if not before_has:  # block at start
        return after.lstrip("\n")
    # Block sits between user content (user reordered it) → collapse only the
    # junction to a single blank line; content on either side is byte-preserved.
    return before.rstrip("\n") + "\n\n" + after.lstrip("\n")


# ---------------------------------------------------------------- state
def _state_all(cfg):
    st = cfg.get("skill_installs")
    if not isinstance(st, dict):
        st = {}
        cfg["skill_installs"] = st
    return st


def _state(cfg, key):
    entry = _state_all(cfg).get(key)
    return entry if isinstance(entry, dict) else None


def _current_region(spec, cfg):
    """What loom's region currently holds on disk (or None)."""
    text = _read_text(spec.target_path(cfg))
    if spec.strategy == agents.STRAT_MARKER:
        return None if text is None else _match_block(text)
    return text


def _match_block(text):
    m = _BLOCK_RE.search(text)
    return m.group(0) if m else None


# ---------------------------------------------------------------- public API
def _record_state(cfg, agent_key, target, strategy, sha):
    _state_all(cfg)[agent_key] = {
        "version": MARKER_VERSION,
        "sha256": sha,
        "target": target,
        "strategy": strategy,
        "installed_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }


def install(agent_key, cfg, dry_run=False):
    """Install (or update) the loom-skill for one agent. Idempotent + drift-safe.

    Returns a dict describing what happened; when ``dry_run`` nothing is written
    but the same fields (``action`` prefixed ``would_``) and a ``diff_preview``
    are returned so the GUI/CLI can show the change first. An explicitly-named
    agent is honoured even if not yet detected (pre-install); the ``all``
    selector, by contrast, only touches detected agents.
    """
    spec = agents.get(agent_key)
    target = spec.target_path(cfg)
    desired = render(agent_key)
    desired_hash = _sha256(desired)

    present = spec.detect(cfg)
    current = _current_region(spec, cfg)
    recorded = (_state(cfg, agent_key) or {}).get("sha256")
    current_hash = _sha256(current) if current is not None else None

    result = {
        "ok": True, "agent": agent_key, "label": spec.label,
        "label_en": spec.label_en, "target": target, "strategy": spec.strategy,
        "present": present, "drift": False, "backup": None,
    }

    # On-disk region already equals what we want.
    if current is not None and current_hash == desired_hash:
        if recorded != desired_hash and not dry_run:
            # Foreign-but-identical (e.g. user hand-copied the shipped skill):
            # adopt it into state — no backup, no rewrite, no churn.
            _record_state(cfg, agent_key, target, spec.strategy, desired_hash)
            config.save(cfg)
        result["action"] = "would_install" if dry_run else "unchanged"
        result["message"] = f"{spec.label}:已是最新,无需改动"
        return result

    # Would we be overwriting content that isn't the loom copy we recorded?
    drift = current is not None and current_hash != recorded
    result["drift"] = drift

    if dry_run:
        result["action"] = "would_install"
        result["diff_preview"] = desired
        result["message"] = (
            f"{spec.label}:将写入 {target}" + ("(检测到外部改动,会先备份)" if drift else ""))
        return result

    if drift:
        result["backup"] = _backup(target)

    if spec.strategy == agents.STRAT_MARKER:
        existing = _read_text(target) or ""
        _atomic_write(target, _splice_block(existing, desired))
    else:
        _atomic_write(target, desired)

    _record_state(cfg, agent_key, target, spec.strategy, desired_hash)
    config.save(cfg)

    result["action"] = "updated" if recorded else "installed"
    result["message"] = f"{spec.label}:已{'更新' if recorded else '安装'} → {target}"
    return result


def uninstall(agent_key, cfg, dry_run=False, force=False):
    """Remove exactly the loom-skill for one agent, leaving user content intact.

    A *foreign* dedicated file (content at loom's reserved path that loom never
    recorded installing — e.g. a user hand-copied the shipped skill) is left
    alone unless ``force``: we only ever delete a dedicated file we ourselves
    wrote. Marker blocks carry loom's own delimiters, so those are always ours
    to strip.
    """
    spec = agents.get(agent_key)
    target = spec.target_path(cfg)
    current = _current_region(spec, cfg)
    recorded = (_state(cfg, agent_key) or {}).get("sha256")
    current_hash = _sha256(current) if current is not None else None

    result = {
        "ok": True, "agent": agent_key, "label": spec.label,
        "label_en": spec.label_en, "target": target, "strategy": spec.strategy,
        "drift": False, "backup": None,
    }

    if current is None and recorded is None:
        result["action"] = "not_installed"
        result["message"] = f"{spec.label}:未安装,无需卸载"
        return result

    # Foreign dedicated file (never recorded by loom) → don't delete a file we
    # didn't create. Marker strategy is exempt (a loom block is provably ours).
    if (recorded is None and current is not None
            and spec.strategy != agents.STRAT_MARKER and not force):
        result["action"] = "skipped_foreign"
        result["drift"] = True
        result["message"] = (
            f"{spec.label}:{target} 非 loom 安装(无记录),已跳过;如确需删除用 --force")
        return result

    drift = current is not None and current_hash != recorded
    result["drift"] = drift

    if dry_run:
        result["action"] = "would_uninstall"
        result["message"] = (
            f"{spec.label}:将从 {target} 移除 loom-skill"
            + ("(检测到外部改动,会先备份)" if drift else ""))
        return result

    if current is not None:
        if drift:
            result["backup"] = _backup(target)
        if spec.strategy == agents.STRAT_MARKER:
            full = _read_text(target) or ""
            stripped = _remove_block(full)
            if stripped:
                _atomic_write(target, stripped)
            elif os.path.isfile(target):
                os.remove(target)  # file held only our block → remove it
        else:
            if os.path.isfile(target):
                os.remove(target)
            owns = spec.owns_dir(cfg)
            if owns and os.path.isdir(owns) and not os.listdir(owns):
                os.rmdir(owns)

    _state_all(cfg).pop(agent_key, None)
    config.save(cfg)

    result["action"] = "uninstalled"
    result["message"] = f"{spec.label}:已卸载"
    return result


def status(cfg):
    """Per-agent install status for CLI/GUI. Never writes."""
    out = []
    for key in agents.ORDER:
        spec = agents.get(key)
        target = spec.target_path(cfg)
        present = spec.detect(cfg)
        state = _state(cfg, key) or {}
        recorded = state.get("sha256")
        current = _current_region(spec, cfg)
        current_hash = _sha256(current) if current is not None else None
        try:
            desired_hash = _sha256(render(key))
        except Exception:
            desired_hash = None

        if not recorded:
            st = "not_installed" if current is None else "foreign"
        elif current is None:
            st = "missing"
        elif current_hash != recorded:
            st = "drifted"
        elif desired_hash and recorded != desired_hash:
            st = "update_available"
        else:
            st = "installed"

        out.append({
            "agent": key, "label": spec.label, "label_en": spec.label_en,
            "present": present, "status": st, "target": target,
            "strategy": spec.strategy, "version": state.get("version"),
            "installed_at": state.get("installed_at"),
        })
    return out


def resolve_agents(selector, cfg, for_install=True):
    """Expand a CLI ``--agent`` selector into concrete keys.

    ``all`` means every *detected* agent for install (skip absent ones so we do
    not create empty homes), but every known agent for uninstall (so a leftover
    can always be cleaned). A specific key is always honoured verbatim.
    """
    if selector == "all":
        if for_install:
            return [k for k in agents.ORDER if agents.get(k).detect(cfg)]
        return list(agents.ORDER)
    agents.get(selector)  # validate
    return [selector]
