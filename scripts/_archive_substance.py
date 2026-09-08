#!/usr/bin/env python3
"""
_archive_substance.py — the ONE definition of a "substantive" session.

WHY THIS MODULE EXISTS
----------------------
Until 2026-09-08 three scripts each carried their own answer to "is this
session worth archiving?", and they disagreed:

  * ``check-archive-drift.py`` — at least 4,000 characters of user/assistant
    prose, with a 48-hour grace window before a session is expected in the
    archive.
  * ``bulk-archive.py discover`` — at least five *turns* (the default), a
    proxy the 2026-07-28 diagnosis had already measured as wrong: it
    discarded 56 of 77 substantive sessions, including a 205,848-token
    session that happened to have two turns.
  * ``bulk-archive.py enrich`` — at least 1,000 *distilled tokens*,
    unconditionally.

The consequence was a permanent gate. A two-turn, 28 KB session is
substantive to the drift check, which reports it every day; it is trivial to
the archiver at the flags the drift check's own remediation line tells you to
run, so running that command never clears the report. A gate that cannot be
cleared trains its reader to ignore it — which is exactly how the 2026-07-28
77-session archive gap went unnoticed for twelve weeks.

So the predicate lives here, once, and every consumer calls it. Changing the
floor changes the gate and the archiver together, by construction.

THE PREDICATE
-------------
A session is *substantive* when the conversational prose it contains reaches
:data:`MIN_CONTENT_CHARS`. "Conversational prose" means the text of
``user``/``assistant`` records only: tool traffic, thinking blocks, and
machine-injected records (``isMeta``, ``isCompactSummary``, ``isSidechain``)
are excluded, because none of them is something a person said or a model
said back.

A session is *within grace* when its transcript was last written less than
:data:`GRACE_HOURS` ago. Hooks archive at SessionEnd/PreCompact, so a
younger transcript is not yet expected in the archive — and, per the
completeness guard (audit 2026-09-08, finding AR3), is also not safe to
archive, because it may still be growing.
"""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path
from typing import IO, Any

#: Characters of conversational prose below which a session carries nothing
#: worth archiving or summarising. ~1,000 tokens at the chars/4 estimator the
#: bake-off manifests use; the floor adopted 2026-07-28 after 71 sessions
#: below it were deliberately left un-archived.
MIN_CONTENT_CHARS = 4_000

#: The same floor expressed in estimated tokens, for call sites and help text
#: that speak in tokens. chars/4 is the estimator used throughout the hub.
MIN_CONTENT_TOKENS = MIN_CONTENT_CHARS // 4

#: Hours after a transcript's last write before the archive is expected to
#: hold it — and before it is safe to copy (it may still be growing).
GRACE_HOURS = 48

#: Record types that carry conversational prose. Everything else in a
#: transcript is machinery.
_PROSE_TYPES = frozenset({"user", "assistant"})

#: Top-level boolean flags that mark a record as machine-injected rather than
#: conversational. Mirrors the exclusions in ``hooks/extraction-hook.py``.
_MACHINE_FLAGS = ("isMeta", "isCompactSummary", "isSidechain")


def _open_transcript(path: Path) -> IO[str]:
    """Open a transcript for text reading, transparently handling gzip.

    ``encoding="utf-8-sig"`` rather than ``"utf-8"``: a byte-order mark on the
    first line makes ``json.loads`` fail on that record, which silently drops
    the opening exchange from the substance count (audit 2026-09-08, AR23).
    """
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", errors="replace")
    return open(path, "rt", encoding="utf-8-sig", errors="replace")


def _record_prose_chars(record: dict[str, Any]) -> int:
    """Characters of conversational prose in one transcript record."""
    if record.get("type") not in _PROSE_TYPES:
        return 0
    if any(record.get(flag) for flag in _MACHINE_FLAGS):
        return 0
    message = record.get("message")
    if not isinstance(message, dict):
        return 0
    content = message.get("content")
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        # Only ``text`` blocks: ``tool_use``, ``tool_result``, and ``thinking``
        # blocks are machinery, not something anyone said.
        return sum(
            len(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return 0


def session_content_chars(path: Path, threshold: int | None = None) -> int:
    """Count characters of conversational prose in a transcript.

    Streams the file one line at a time, so a multi-megabyte transcript costs
    one line of memory. When *threshold* is given the count stops as soon as
    it is reached, which makes the common (clearly substantive) case almost
    free; the returned value is then a lower bound, never an over-count.

    An unreadable transcript counts as zero — a file we cannot open is not
    evidence of substance.
    """
    total = 0
    try:
        with _open_transcript(path) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(record, dict):
                    continue
                total += _record_prose_chars(record)
                if threshold is not None and total >= threshold:
                    return total
    except (OSError, EOFError, gzip.BadGzipFile):
        return 0
    return total


def is_substantive(path: Path, min_chars: int = MIN_CONTENT_CHARS) -> bool:
    """True when a transcript reaches the conversational-prose floor.

    This is THE predicate. ``check-archive-drift.py`` uses it to decide what
    to report, ``bulk-archive.py discover`` uses it to decide what to archive,
    and ``bulk-archive.py enrich`` uses it to decide what to summarise, so the
    gate's remediation command archives exactly what the gate reported.
    """
    if min_chars <= 0:
        return True
    return session_content_chars(path, threshold=min_chars) >= min_chars


def within_grace(
    path: Path,
    *,
    now: float | None = None,
    grace_hours: float = GRACE_HOURS,
) -> bool:
    """True when a transcript was written too recently to act on.

    Used in two places for two reasons that happen to share a window: the
    drift check will not *report* a session this young (the hooks have not
    had their chance yet), and the archiver will not *copy* one (it may still
    be being written, and a truncated copy becomes canonical — AR3).
    """
    if grace_hours <= 0:
        return False
    try:
        mtime = path.stat().st_mtime
    except OSError:
        # An unstattable transcript is treated as in-grace: refusing to act is
        # always the safe direction for a file we cannot characterise.
        return True
    return (now if now is not None else time.time()) - mtime < grace_hours * 3600
