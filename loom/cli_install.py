# -*- coding: utf-8 -*-
"""Install a ``loom`` command that re-invokes the bundled ``loom-core`` binary.

This is Loom's take on VS Code's "Install 'code' command in PATH": the desktop
app already ships a single ``loom-core`` executable that doubles as the CLI
(``loom/desktop.py`` routes every non-desktop verb to ``loom/cli.py:main``).  All
we have to do is drop a tiny ``exec``-only shell wrapper named ``loom`` into a
PATH directory so ``loom …`` in any terminal runs that same bundled binary — no
separate ``pip install``, no ``sudo``.

Everything here is pure and side-effect-scoped by its arguments so it can be
unit-tested against a throwaway directory and a fake PATH — it never has to touch
the real filesystem PATH.
"""
import os
import sys

_WRAPPER_MARKER = "# loom-cli-wrapper v1"


def _wrapper_script(target_binary):
    """A minimal POSIX wrapper.

    ``exec`` replaces the shell so exit status and signals pass straight through;
    ``"$@"`` forwards every argument verbatim (spaces preserved).  The binary path
    is single-quoted with embedded quotes escaped so odd install paths stay safe.
    """
    quoted = "'" + target_binary.replace("'", "'\\''") + "'"
    return (
        "#!/bin/sh\n"
        + _WRAPPER_MARKER + "\n"
        "# Installed by the Loom desktop app. Runs the bundled loom-core binary,\n"
        "# which dispatches every non-desktop verb to the loom CLI.\n"
        "# Safe to delete or regenerate from Settings.\n"
        "exec " + quoted + " \"$@\"\n"
    )


def _norm(path):
    return os.path.normcase(os.path.normpath(os.path.expanduser(path)))


def _on_path(directory, path_env):
    target = _norm(directory)
    return any(entry and _norm(entry) == target
               for entry in (path_env or "").split(os.pathsep))


def default_candidate_dirs(home):
    """Prefer a no-sudo, per-user dir; fall back to the classic shared one.

    ``~/.local/bin`` needs no elevation and is on PATH in most modern shells.
    ``/usr/local/bin`` is the traditional spot but is often root-owned — we only
    reach it if the per-user dir cannot be created/written.
    """
    return [os.path.join(home, ".local", "bin"), "/usr/local/bin"]


def resolve_target_binary(frozen=None, executable=None, env=None):
    """Absolute path the wrapper should exec, or ``None`` in a dev checkout.

    * ``LOOM_CLI_TARGET`` always wins (lets a dev point at a built loom-core).
    * In a PyInstaller build ``sys.frozen`` is set and ``sys.executable`` *is* the
      bundled ``loom-core`` — exactly what we want to exec.
    * A plain ``python3`` dev run is not a self-contained CLI, so we return
      ``None`` and the caller surfaces a "packaged app only" message.
    """
    env = os.environ if env is None else env
    override = (env.get("LOOM_CLI_TARGET") or "").strip()
    if override:
        return override
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    executable = sys.executable if executable is None else executable
    return executable if frozen else None


def install_cli(target_binary, home=None, path_env=None, candidate_dirs=None,
                command_name="loom"):
    """Write the ``loom`` wrapper into the first writable PATH-friendly dir.

    Idempotent: the wrapper content is fully determined by ``target_binary``, and
    each install atomically replaces any previous copy.  Returns
    ``{ok, path, target, on_path, command}``; raises ``RuntimeError`` if no
    candidate directory is writable and ``ValueError`` on a bad target.
    """
    if not target_binary or not os.path.isabs(target_binary):
        raise ValueError("target_binary 必须是绝对路径")
    home = os.path.expanduser("~") if home is None else home
    path_env = os.environ.get("PATH", "") if path_env is None else path_env
    dirs = list(candidate_dirs) if candidate_dirs else default_candidate_dirs(home)
    script = _wrapper_script(target_binary)

    errors = []
    for directory in dirs:
        dest = os.path.join(directory, command_name)
        tmp = dest + ".loom-tmp"
        try:
            os.makedirs(directory, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(script)
            os.chmod(tmp, 0o755)
            os.replace(tmp, dest)  # atomic overwrite → idempotent re-install
        except OSError as exc:
            errors.append("%s(%s)" % (directory, exc))
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            continue
        return {
            "ok": True,
            "path": dest,
            "target": target_binary,
            "on_path": _on_path(directory, path_env),
            "command": command_name,
        }
    raise RuntimeError("无法写入 loom 命令(已尝试:%s)" % "; ".join(errors))
