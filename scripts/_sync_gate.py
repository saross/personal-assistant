#!/usr/bin/env python3
"""
Session-start gate file for the PostgreSQL sync scripts.

Why
---
The syncs run from cron every five minutes and from session hooks. Their
output goes to ``logs/sync.log`` and ``logs/sync-sessions.log``, which
nobody reads until something has already gone wrong — which is precisely
how the sessions table came to sit three weeks stale in September 2026
behind an error message that said "PostgreSQL may be down".

Fixing the diagnosis is only half of it. An exit code that reaches nothing
but a log file is a signal emitted and not surfaced, which this repository
has now learned three times is indistinguishable from no signal at all
(``scripts/daily-sync-trigger.sh`` says so at length, having watched the
Syncthing gate report three problems at every session start for a fortnight
with nobody seeing one).

So the two "a human must do something" exits — 4 (environment fault) and 6
(a rebuild cleared the cursor mid-run) — write a gate file, and
``daily-sync-trigger.sh`` prints it to STDOUT at session start under the
"RELAY THESE TO SHAWN" header.

Format
------
The same shape as every other gate in ``~/.cache`` (``cc-archives-gate``,
``syncthing-gate``, ``memory-drift-gate``, ``cc-archive-drift-gate``):

* line 1 — the problem count, ``0`` meaning clean;
* the remaining lines — one detail line each, printed verbatim.

A clean run rewrites the file with ``0``, so a fault that has been fixed
stops being reported without anyone having to delete anything.
"""

from __future__ import annotations

import logging
from pathlib import Path

#: What one sync cycle achieved. Only :data:`CYCLE_COMPLETED` licenses a
#: caller to clear its gate: a run that deferred to another instance, or
#: that could not reach the database, has learnt nothing about the fault
#: the gate is reporting (third re-audit, finding C1).
CYCLE_COMPLETED = "completed"
#: Another instance held the advisory lock; this run did nothing.
CYCLE_CONTENDED = "contended"
#: The run could not do its job — unreachable database, missing canonical,
#: rows unaccounted for. The cursor did not advance.
CYCLE_DEGRADED = "degraded"

#: One gate file per script, never a shared one (third re-audit, finding
#: C1). A single file with two writers and an unconditional clear meant a
#: clean run of the memories sync erased the sessions sync's alarm within
#: one cron tick — five minutes of visibility for a fault that needs a
#: human. ``daily-sync-trigger.sh`` iterates exactly these names.
MEMORIES_GATE: Path = Path.home() / ".cache" / "postgres-sync-memories-gate"
SESSIONS_GATE: Path = Path.home() / ".cache" / "postgres-sync-sessions-gate"
INDEXER_GATE: Path = Path.home() / ".cache" / "index-session-content-gate"

#: Every gate this module owns, in the order the trigger prints them.
ALL_GATES: tuple[Path, ...] = (MEMORIES_GATE, SESSIONS_GATE, INDEXER_GATE)


def write_gate(
    detail: str,
    *,
    gate_path: Path,
    count: int = 1,
    logger: logging.Logger | None = None,
) -> bool:
    """
    Raise the gate with a one-line diagnosis.

    Parameters
    ----------
    detail:
        One line, printed verbatim at session start. Name the script and
        the SQLSTATE: the reader is deciding whether to stop what they are
        doing, and "sync-to-postgres exited 4" alone does not tell them.
        Newlines are collapsed so the count-then-details format holds.
    gate_path:
        Which gate to raise. Required — there is no default, because a
        default is how two scripts came to share one file.
    count:
        The problem count on line 1. Any positive value raises the gate;
        the number is informative (how many rows were quarantined, say),
        not a severity.
    logger:
        Optional; an I/O failure is logged rather than raised. A gate we
        cannot write must never take down a sync that has otherwise done
        its job.

    Returns
    -------
    bool
        True when the gate is on disk.
    """
    line = " ".join(detail.split())
    try:
        gate_path.parent.mkdir(parents=True, exist_ok=True)
        gate_path.write_text(f"{max(1, count)}\n{line}\n", encoding="utf-8")
    except OSError as exc:
        if logger is not None:
            logger.error("Could not write the gate file %s: %s", gate_path, exc)
        return False
    return True


def clear_gate(
    *,
    gate_path: Path,
    logger: logging.Logger | None = None,
) -> bool:
    """
    Lower the gate after a full, successful cycle of the owning script.

    The caller must have completed a whole cycle. A run that returned
    early because another instance held the advisory lock, or because the
    database was unreachable, has learnt nothing about the fault the gate
    is reporting and must leave it standing (finding C1). This function
    cannot check that, so each caller decides — see the sync scripts'
    cycle-outcome constants.

    Writes ``0`` rather than deleting the file: the trigger script reads a
    count, and a missing file and a zero count mean the same thing to it,
    but a file that is present and says ``0`` is evidence the sync ran and
    was happy — useful when the question is "did this even execute?".

    Returns True when the file is on disk saying zero.
    """
    try:
        gate_path.parent.mkdir(parents=True, exist_ok=True)
        gate_path.write_text("0\n", encoding="utf-8")
    except OSError as exc:
        if logger is not None:
            logger.error("Could not clear the gate file %s: %s", gate_path, exc)
        return False
    return True
