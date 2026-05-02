#!/usr/bin/env python3
"""
Shared project-id encoding for hooks that need to compare a session's
working directory against the ``project`` field stored on memories.

Why
---
``hooks/session-start-retrieval.py`` derives a project id from
``cwd`` to filter memories to the current project. The extraction hook
uses ``Path(transcript_path).parent.name`` — a value Claude Code itself
encodes from cwd by replacing ``/`` with ``-``. The two encodings need
to match byte-for-byte; if they ever drift, ``is_same_project`` returns
``False`` for every memory of the active project and project-aware
retrieval silently breaks.

Until this batch the encoding lived inline in
``session-start-retrieval.py`` (``str(Path(cwd).resolve()).replace("/", "-")``).
The audit (IC3, C-C4, C-X3) flagged the duplication as a future-proofing
risk — Claude Code could change its encoding (URL-encode reserved
characters, for example), and any consumer of the ``project`` field
would silently disagree until someone noticed empty retrieval.

Both consumers now import ``encode_project_id`` from this module.

Audit refs
----------
* ``reports/audit-2026-05-02/SUMMARY.md`` — IC3.
* ``reports/audit-2026-05-02/cluster-C-hooks.md`` — C-C4 (retrieval),
  C-X3 (cross-file).
"""

from pathlib import Path
from typing import Optional


def encode_project_id(cwd: str) -> Optional[str]:
    """Encode *cwd* as the canonical project id used by memory writers.

    Resolves *cwd* to an absolute path (matching the historical
    behaviour of ``session-start-retrieval.py``), then replaces every
    ``/`` with ``-`` — the same encoding Claude Code uses for the
    project directory under ``~/.claude/projects/<encoded-cwd>/``.

    Returns ``None`` for an empty *cwd* (callers treat ``None`` as
    "no current project known").

    Examples
    --------
    >>> encode_project_id("/home/shawn/personal-assistant")
    '-home-shawn-personal-assistant'
    >>> encode_project_id("")
    >>> encode_project_id("/")
    '-'
    """
    if not cwd:
        return None
    return str(Path(cwd).resolve()).replace("/", "-")
