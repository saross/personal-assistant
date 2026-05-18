#!/usr/bin/env python3
"""
SessionStart hook for Claude Code — capture ``commit_at_start`` sidecar.

Closes the honest gap in provenance audit Gap 2 (2026-05-17). The
archive runs at session-close (SessionEnd / PreCompact), so the git
HEAD it captures is ``commit_at_end``. To populate ``commit_at_start``,
we need a side-channel that records HEAD at the *start* of the
session, keyed by session id, that the archive can later read back.

This hook does that. It runs at SessionStart (startup, resume, clear,
compact), reads ``session_id`` and ``cwd`` from the hook payload,
resolves ``git rev-parse HEAD`` in the working directory, and writes a
JSON sidecar to ``~/personal-assistant/data/code-state/<session_id>.json``.

Consumer:
    ``cc_session_toolkit.archive.capture_code_state`` reads the sidecar
    (by session id) when constructing the ``code_state`` block at
    archive time. If the sidecar is missing or unreadable,
    ``commit_at_start`` collapses to *None* — provenance capture must
    never break the session.

Failure policy:
    Best-effort throughout. Any error is logged to
    ``data/logs/session-start-code-state.log`` and the hook exits 0 so
    a missing sidecar never blocks session start. The schema already
    accepts *None* for the field, so absence is graceful degradation
    rather than data corruption.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PA_DIR = Path.home() / "personal-assistant"
SIDECAR_DIR = PA_DIR / "data" / "code-state"
LOG_FILE = PA_DIR / "data" / "logs" / "session-start-code-state.log"


def _log(message: str, level: str = "INFO") -> None:
    """Append a timestamped line to the hook log.  Best-effort."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"{timestamp} [{level}] {message}\n")
    except OSError:
        pass  # logging must never break the hook


def _git_head(project_root: Path) -> str | None:
    """
    Resolve ``git rev-parse HEAD`` in *project_root*.

    Returns *None* if the directory does not exist, is not a git
    repository, or the git command fails for any reason. Mirrors the
    semantics of ``cc_session_toolkit.archive._run_git`` so the two
    sides agree on what "no commit captured" means.
    """
    if not project_root.is_dir():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _log(f"git rev-parse failed in {project_root}: {exc}", level="WARNING")
        return None
    if result.returncode != 0:
        # Not a git repo, or git refuses (e.g. empty repo with no commits).
        return None
    commit = result.stdout.strip()
    return commit or None


def main() -> int:
    """SessionStart hook entry point."""
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError) as exc:
        _log(f"stdin was not valid JSON: {exc}", level="WARNING")
        return 0

    session_id = hook_input.get("session_id")
    cwd = hook_input.get("cwd")
    if not session_id:
        _log("no session_id in payload; nothing to write", level="WARNING")
        return 0
    if not cwd:
        _log(
            f"no cwd for session_id={session_id}; "
            "commit_at_start cannot be captured",
            level="INFO",
        )
        return 0

    commit = _git_head(Path(cwd))
    if commit is None:
        _log(
            f"no git HEAD resolved for session_id={session_id} cwd={cwd}; "
            "skipping sidecar write",
            level="INFO",
        )
        return 0

    sidecar = {
        "session_id": session_id,
        "commit_at_start": commit,
        "project_root": str(Path(cwd).resolve()),
        "captured_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }

    try:
        SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
        sidecar_path = SIDECAR_DIR / f"{session_id}.json"
        sidecar_path.write_text(
            json.dumps(sidecar, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        _log(
            f"failed to write sidecar for session_id={session_id}: {exc}",
            level="WARNING",
        )
        return 0

    _log(
        f"wrote sidecar session_id={session_id} commit={commit[:12]} "
        f"project_root={cwd}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
