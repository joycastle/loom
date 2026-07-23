# -*- coding: utf-8 -*-
"""Global test isolation — the one place that GUARANTEES the suite can never read
or clobber the real ~/.loom.

`loom.util` resolves HOME/DATA_PATH/INDEX_PATH at IMPORT time from $LOOM_HOME
(default ~/.loom). pytest imports conftest.py BEFORE any test module, so setting
LOOM_HOME to a throwaway tempdir here protects the whole suite — including any
test (or future test) that forgets to isolate itself. This is why the ledger got
wiped when tests/agent scripts ran against the real home.
"""
import os
import tempfile

_REAL = os.path.abspath(os.path.expanduser("~/.loom"))
_cur = os.environ.get("LOOM_HOME", "")

# If LOOM_HOME is unset, or (dangerously) points at the real home, redirect the
# entire test session to a fresh sandbox. An already-set temp dir is left alone.
if not _cur or os.path.abspath(os.path.expanduser(_cur)) == _REAL:
    os.environ["LOOM_HOME"] = tempfile.mkdtemp(prefix="loom-pytest-home-")
