#!/usr/bin/env python3
"""
Pre-flight guard for bulk in-place rewrites of memories.jsonl and
tag-vocabulary.txt.

Scripts that rewrite these files in place (dedup-memories,
reprocess-sessions, backfill-summaries, tag-gardening, ...) must call
:func:`ensure_safe_to_rewrite` before modifying anything on disk, and
:func:`mark_bulk_rewrite_commit_msg` when composing the commit message
for the resulting change.

Why
---
Without the guard, a bulk rewrite can race with (a) an append from
another machine's extraction hook that hasn't synced yet, producing
silent data loss on the next sync, or (b) the scheduled ``daily-sync``
cron on the same machine, producing non-fast-forward push rejections
that require manual recovery. The guard enforces that bulk rewrites
happen only when origin and local HEAD agree and the working tree is
clean on the target files.

The commit-message trailer ``Rewrite-Class: bulk`` allows the post-sync
shrink check (scripts/daily-sync.sh) to distinguish intentional
net-deletion commits from accidental ones.

Config
------
``data/config/sync.json``::

    {"require_clean_origin_for_bulk": true}

When ``false``, the guard runs and logs, but does not abort. Used as a
rollback switch if the guard produces false positives.

Usage
-----
::

    from _bulk_rewrite_guard import ensure_safe_to_rewrite, mark_bulk_rewrite_commit_msg

    ensure_safe_to_rewrite(reason="dedup memories.jsonl by id")
    # ... perform the rewrite ...
    # Commit message should include the trailer:
    msg = mark_bulk_rewrite_commit_msg(
        "dedup: collapse 123 duplicate memory records",
        rewrite_class="bulk",
    )

Exit codes (via sys.exit)
-------------------------
* ``0`` — safe to proceed
* ``2`` — guard failed (repo state or lock contention)
* ``3`` — configuration error (missing venv, bad config)
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PA_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PA_ROOT / "data"
CONFIG_FILE = DATA_DIR / "config" / "sync.json"
LOCK_FILE = PA_ROOT / "logs" / "daily-sync.lock"
LOG_FILE = PA_ROOT / "logs" / "bulk-rewrite-guard.log"

# Target files whose cleanliness the guard enforces. Keep in sync with
# the files daily-sync.sh treats as append-only canonical stores.
PROTECTED_FILES = (
    "memories/memories.jsonl",
    "memories/tag-vocabulary.txt",
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("_bulk_rewrite_guard")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    """Read data/config/sync.json, returning defaults if missing."""
    defaults = {
        "require_clean_origin_for_bulk": True,
        "retry_on_push_reject": True,
        "detect_jsonl_shrink": True,
        "recall_staleness_warning": True,
    }
    if not CONFIG_FILE.exists():
        return defaults
    try:
        with CONFIG_FILE.open(encoding="utf-8") as f:
            stored = json.load(f)
        return {**defaults, **stored}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            "Could not read %s (%s) — using defaults", CONFIG_FILE, e
        )
        return defaults


# ---------------------------------------------------------------------------
# Git helpers (minimal, subprocess-based — no pygit dependency)
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path = DATA_DIR) -> subprocess.CompletedProcess:
    """Run a git command in the data submodule and return the result."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _fetch_origin() -> bool:
    """Fetch origin/main. Returns True on success, False otherwise."""
    result = _git("fetch", "origin", "main", "--quiet")
    if result.returncode != 0:
        logger.error("git fetch failed: %s", result.stderr.strip())
        return False
    return True


def _head_matches_origin() -> bool:
    """True iff local main == origin/main (no unpushed, no unpulled)."""
    # Detect detached HEAD — a known submodule state after some git
    # operations (see daily-sync.sh comment). In detached state, the
    # `main` branch exists but HEAD doesn't point at it, so the guard
    # should refuse and point the user at daily-sync for recovery.
    current = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if current == "HEAD":
        logger.error(
            "Data submodule is in detached HEAD state. Run "
            "scripts/daily-sync.sh (or `cd data && git checkout main && "
            "git pull`) before any bulk rewrite."
        )
        return False
    if current != "main":
        logger.error(
            "Data submodule is on branch %r, expected 'main'. Switch "
            "branches before running a bulk rewrite.", current,
        )
        return False
    local = _git("rev-parse", "main").stdout.strip()
    remote = _git("rev-parse", "origin/main").stdout.strip()
    if not local or not remote:
        logger.error(
            "Could not resolve main / origin/main (local=%r remote=%r). "
            "Did `git fetch` succeed?", local, remote,
        )
        return False
    return local == remote


def _working_tree_clean_on(files: tuple[str, ...]) -> bool:
    """True iff none of the given paths have unstaged or staged changes."""
    dirty = []
    for path in files:
        result = _git("status", "--porcelain", "--", path)
        if result.stdout.strip():
            dirty.append(path)
    if dirty:
        logger.error(
            "Protected files have uncommitted changes: %s",
            ", ".join(dirty),
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------


_lock_fd: Optional[int] = None


def _acquire_lock() -> bool:
    """Acquire the shared daily-sync flock (non-blocking)."""
    global _lock_fd
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    # O_CLOEXEC so the fd doesn't leak into child processes if the
    # guard's caller spawns subprocesses before release_lock() runs.
    _lock_fd = os.open(
        str(LOCK_FILE),
        os.O_CREAT | os.O_WRONLY | os.O_CLOEXEC,
        0o644,
    )
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        logger.error(
            "Lock contention: %s is held by another process "
            "(daily-sync or concurrent bulk rewrite)", LOCK_FILE,
        )
        os.close(_lock_fd)
        _lock_fd = None
        return False


def release_lock() -> None:
    """Release the flock. Safe to call multiple times."""
    global _lock_fd
    if _lock_fd is not None:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(_lock_fd)
        _lock_fd = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_safe_to_rewrite(reason: str) -> None:
    """
    Verify the repo is in a safe state for an in-place bulk rewrite of
    memories.jsonl or tag-vocabulary.txt. Exits with non-zero status
    via sys.exit on failure.

    The guard:
      1. Fetches origin/main.
      2. Verifies HEAD == origin/main (no unpushed local commits, no
         unpulled remote commits).
      3. Verifies the protected files have no uncommitted changes.
      4. Acquires the shared daily-sync flock (non-blocking).

    If ``require_clean_origin_for_bulk`` is ``false`` in
    data/config/sync.json, the guard still runs and logs every step,
    but non-zero results become warnings rather than aborts. This is a
    rollback switch, not a disable switch — the log trail is preserved.
    """
    cfg = _load_config()
    enforce = cfg.get("require_clean_origin_for_bulk", True)
    mode = "enforcing" if enforce else "warning-only (flag off)"

    logger.info("bulk-rewrite guard invoked: reason=%r mode=%s", reason, mode)

    ok = True

    if not _fetch_origin():
        ok = False

    if not _head_matches_origin():
        logger.error(
            "HEAD != origin/main. Resolve via `cd data && git pull` "
            "(or `daily-sync.sh`) before running a bulk rewrite."
        )
        ok = False

    if not _working_tree_clean_on(PROTECTED_FILES):
        logger.error(
            "Protected files dirty. Commit or stash extraction-hook "
            "captures before running a bulk rewrite."
        )
        ok = False

    if not _acquire_lock():
        ok = False

    if ok:
        logger.info("guard passed; proceeding with rewrite: %s", reason)
        return

    if enforce:
        logger.error("guard failed — aborting (set require_clean_origin_for_bulk=false to override)")
        release_lock()
        sys.exit(2)

    logger.warning(
        "guard failed but enforcement disabled — proceeding despite "
        "unsafe state (reason=%r)", reason,
    )


def mark_bulk_rewrite_commit_msg(subject: str, *, rewrite_class: str = "bulk") -> str:
    """
    Return a commit message with the ``Rewrite-Class: <class>`` trailer
    appended, so the post-sync shrink check (scripts/daily-sync.sh) can
    distinguish intentional net-deletion commits from accidental ones.

    Use with ``git commit -m "$(python3 _bulk_rewrite_guard.py --msg ...)"``
    or wire programmatically::

        import subprocess
        from _bulk_rewrite_guard import mark_bulk_rewrite_commit_msg
        msg = mark_bulk_rewrite_commit_msg(
            "dedup: collapse 123 duplicate memory records",
        )
        subprocess.run(["git", "commit", "-m", msg], check=True)
    """
    trailer = f"Rewrite-Class: {rewrite_class}"
    # Ensure exactly one blank line between subject and trailer
    body = subject.rstrip()
    if not body.endswith("\n"):
        body += "\n"
    return f"{body}\n{trailer}\n"


# ---------------------------------------------------------------------------
# CLI (for shell-script integration / diagnostics)
# ---------------------------------------------------------------------------


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Pre-flight guard for bulk memories.jsonl / tag-vocabulary.txt rewrites."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser(
        "check", help="Run the guard checks and exit 0/2 accordingly."
    )
    check.add_argument(
        "--reason", required=True, help="Short description of the rewrite (for logs)."
    )

    msg = sub.add_parser(
        "msg", help="Print a commit message with the Rewrite-Class trailer."
    )
    msg.add_argument("subject", help="Commit subject line (one paragraph OK).")
    msg.add_argument("--class", dest="rewrite_class", default="bulk")

    args = parser.parse_args()

    if args.cmd == "check":
        try:
            ensure_safe_to_rewrite(args.reason)
            print("OK", file=sys.stderr)
            return 0
        finally:
            release_lock()

    if args.cmd == "msg":
        sys.stdout.write(
            mark_bulk_rewrite_commit_msg(args.subject, rewrite_class=args.rewrite_class)
        )
        return 0

    parser.print_help()
    return 3


if __name__ == "__main__":
    sys.exit(_main())
