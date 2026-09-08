#!/usr/bin/env python3
"""
_log_dir.py — create a script's log directory, or explain why it cannot.

``logs/`` in this repository is a symlink into the private ``data``
submodule. When the submodule is not checked out — a fresh clone, a linked
git worktree, a machine where ``git submodule update`` has not run — the
symlink dangles, and ``Path("logs").mkdir(parents=True, exist_ok=True)``
raises ``FileExistsError``: the link exists, its target does not, and
``exist_ok`` does not cover that case.

Every long-running script here calls ``setup_logging()`` as its first act, so
the failure surfaced as an unhandled traceback out of a logging helper — a
diagnosis three frames away from the actual problem, which is one command
long to fix (audit 2026-09-08, finding AR20).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_log_dir(log_dir: Path) -> Path:
    """Create *log_dir*, exiting with a readable message if it cannot exist.

    Returns *log_dir* on success. Exits 2 (the "could not run" code used
    across this pipeline) when the path is a dangling symlink into the
    uninitialised ``data`` submodule, naming the remedy.
    """
    if log_dir.is_symlink() and not log_dir.exists():
        sys.stderr.write(
            f"{log_dir} is a symlink to {os.readlink(log_dir)!r}, which does "
            "not exist.\nThe private data submodule is not checked out here. "
            "Run:\n\n    git submodule update --init data\n\n"
            "(In a linked worktree the submodule is deliberately absent; run "
            "this script from the main checkout instead.)\n"
        )
        raise SystemExit(2)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        sys.stderr.write(f"Cannot create log directory {log_dir}: {exc}\n")
        raise SystemExit(2) from exc
    return log_dir
