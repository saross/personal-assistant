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

import json
import logging
from pathlib import Path
from typing import NamedTuple

#: The governing invariant, and the fourth re-audit's one finding in three
#: places: **a gate is lowered only by evidence that the fault it records
#: is gone. Absence of work is not evidence.** A run that found nothing to
#: do has not shown that yesterday's quarantined rows were repaired, that
#: the revoked grant was restored, or that the disk was emptied. It has
#: shown nothing at all.
#:
#: Hence five outcomes rather than three. The distinction that matters is
#: not "did the run finish" but "did the run learn anything".
#:
#: Processed at least one row and advanced the cursor. The only outcome
#: that can lower a gate.
CYCLE_COMPLETED = "completed"
#: Nothing to do — no new lines, no new archives. Touches no gate. This is
#: the case that cleared a standing quarantine warning within one
#: five-minute tick before the fourth re-audit.
CYCLE_IDLE = "idle"
#: Another instance held the advisory lock; this run did nothing.
CYCLE_CONTENDED = "contended"
#: PostgreSQL could not be reached. Feeds the consecutive-outage counter.
CYCLE_OUTAGE = "outage"
#: Reached the database, or never needed to, but could not complete
#: safely: rows unaccounted for, a missing canonical, an archive root that
#: is absent or empty. The cursor did not advance.
CYCLE_DEGRADED = "degraded"

#: Consecutive unreachable runs before the gate says so. At a five-minute
#: cron tick this is roughly fifteen minutes, which is long enough not to
#: nag over a restart and short enough to matter (fourth re-audit, M4).
OUTAGE_STREAK_THRESHOLD = 3

#: What fault a standing gate currently records, so a later run can tell
#: whether its evidence addresses *that* fault. Connecting is evidence
#: against an outage gate and says nothing about a quarantine gate.
REASON_OUTAGE = "outage"
REASON_QUARANTINE = "quarantine"
REASON_FAULT = "fault"


class GateState(NamedTuple):
    """
    The sidecar state behind a gate file.

    The gate file itself is a fixed two-line format the trigger parses;
    it has nowhere to record *why* it was raised or how many consecutive
    runs have failed to connect. This sits beside it.
    """

    #: One of the ``REASON_*`` constants, or None when no gate stands.
    reason: str | None = None
    #: Consecutive runs that could not reach PostgreSQL.
    outage_streak: int = 0


def state_path_for(gate_path: Path) -> Path:
    """Return the sidecar state path beside a gate file."""
    return gate_path.with_name(gate_path.name + ".state.json")


def read_state(gate_path: Path) -> GateState:
    """
    Read the sidecar state, defaulting to "no gate, no outages".

    Any unreadable or malformed state reads as the default: this is
    bookkeeping that improves the message, never a gate on correctness.
    """
    try:
        raw = json.loads(
            state_path_for(gate_path).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValueError):
        return GateState()
    if not isinstance(raw, dict):
        return GateState()
    reason = raw.get("reason")
    streak = raw.get("outage_streak", 0)
    return GateState(
        reason=reason if isinstance(reason, str) else None,
        outage_streak=streak if isinstance(streak, int) and streak >= 0 else 0,
    )


def write_state(gate_path: Path, state: GateState) -> None:
    """Persist the sidecar state, ignoring I/O failure."""
    path = state_path_for(gate_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "reason": state.reason,
                "outage_streak": state.outage_streak,
            }, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass

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


class CycleResult(NamedTuple):
    """
    What one sync cycle learnt, which is what the gate policy needs.

    ``connected`` is deliberately tri-state. ``True`` means we reached
    PostgreSQL — evidence against an outage gate. ``False`` means we tried
    and could not — evidence *for* one. ``None`` means we never tried,
    which is the case for a cycle that found nothing to do, and which must
    not move the outage counter in either direction.
    """

    outcome: str
    quarantined: int = 0
    processed: int = 0
    connected: bool | None = None


def apply_sync_gate(
    result: CycleResult,
    *,
    script: str,
    gate_path: Path,
    quarantine_file: Path,
    logger: logging.Logger,
) -> None:
    """
    Raise, lower, or leave a script's gate on this cycle's evidence.

    The rules, in order, each one a finding from the fourth re-audit:

    1. **Rows were quarantined** — raise the warning gate, whatever the
       outcome. Data left the pipeline; a degraded run that also
       quarantined used to discard the count entirely (M3).
    2. **Three consecutive unreachable runs** — raise the outage gate. A
       persistent outage produced no session-start signal at all before
       this: the syncs exit 0 on an outage by design, so nothing surfaced
       (M4).
    3. **We connected and the standing gate was an outage** — lower it.
       Connecting is precisely the evidence that "unreachable" is over.
    4. **Completed, processed at least one row, quarantined none** —
       lower the gate. This is the only evidence that a quarantine
       warning or a fault is actually resolved.
    5. **Anything else** — leave the gate exactly as it stands. An idle,
       contended, or outage run has learnt nothing about the recorded
       fault, and saying otherwise is how a five-minute no-op tick came
       to erase a standing alarm.
    """
    state = read_state(gate_path)
    if result.connected is True:
        streak = 0
    elif result.connected is False:
        streak = state.outage_streak + 1
    else:
        streak = state.outage_streak

    if result.quarantined:
        write_gate(
            f"[{script}] {result.quarantined} row(s) were REFUSED by "
            f"PostgreSQL and quarantined to {quarantine_file}; the cursor "
            f"advanced past them, so they are NOT in the database. Repair "
            f"and replay them.",
            gate_path=gate_path,
            count=result.quarantined,
            logger=logger,
        )
        write_state(gate_path, GateState(REASON_QUARANTINE, streak))
        return

    if streak >= OUTAGE_STREAK_THRESHOLD:
        write_gate(
            f"[{script}] PostgreSQL has been unreachable for {streak} "
            f"consecutive runs (~{streak * 5} minutes). The sync is making "
            f"no progress and nothing is reaching the query layer; /recall "
            f"and /search-sessions are serving stale data. Check that "
            f"PostgreSQL is running.",
            gate_path=gate_path,
            count=streak,
            logger=logger,
        )
        write_state(gate_path, GateState(REASON_OUTAGE, streak))
        return

    if result.connected is True and state.reason == REASON_OUTAGE:
        logger.info("PostgreSQL is reachable again — lowering the gate.")
        clear_gate(gate_path=gate_path, logger=logger)
        write_state(gate_path, GateState(None, 0))
        return

    if result.outcome == CYCLE_COMPLETED and result.processed >= 1:
        clear_gate(gate_path=gate_path, logger=logger)
        write_state(gate_path, GateState(None, streak))
        return

    logger.info(
        "Cycle outcome %r with %d row(s) processed — no evidence about any "
        "standing gate, so it is left alone.",
        result.outcome, result.processed,
    )
    write_state(gate_path, GateState(state.reason, streak))


def raise_fault_gate(
    detail: str,
    *,
    gate_path: Path,
    logger: logging.Logger,
) -> None:
    """
    Raise a gate for a fault that stopped the run, and record why.

    Used by the exit paths (an environment fault, a correlated refusal, a
    cap overflow, a schema mismatch, an unexpected exception). Keeps the
    outage streak, which is about connectivity rather than about this
    fault.
    """
    state = read_state(gate_path)
    write_gate(detail, gate_path=gate_path, logger=logger)
    write_state(gate_path, GateState(REASON_FAULT, state.outage_streak))
