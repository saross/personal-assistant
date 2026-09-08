#!/usr/bin/env python3
"""
Session-start gates for the PostgreSQL pipeline, as a state machine.

Why
---
The syncs run from cron every five minutes and from session hooks. Their
output goes to ``logs/sync.log`` and ``logs/sync-sessions.log``, which
nobody reads until something has already gone wrong — which is precisely
how the sessions table came to sit three weeks stale in September 2026
behind an error message that said "PostgreSQL may be down".

An exit code that reaches nothing but a log file is a signal emitted and
not surfaced, which this repository has now learned three times is
indistinguishable from no signal at all (``daily-sync-trigger.sh`` says
so at length, having watched the Syncthing gate report three problems at
every session start for a fortnight with nobody seeing one). So the
scripts write gate files, and the trigger prints them at session start.

Why a state machine
-------------------
Five rounds of re-audit found the same class of bug five times, and each
fix was an incremental rule bolted onto the last: a no-op tick lowering a
standing alarm; an outage overwriting a quarantine warning; a run that
processed one row declaring a hundred quarantined rows resolved; a
project-scoped run clearing another project's problem. The rules kept
leaking because they were rules about *a* gate — one file, one message,
one implicit reason — rather than about the distinct problems that file
was being asked to represent.

So the gate is now derived, never written directly. Each script owns a
state file recording a dict of **independent problems**, each with its
own text and its own raise/lower evidence. The gate file is rendered from
that dict: the count is the number of standing problems and each gets its
own detail line. Problems cannot overwrite each other, an outage cannot
erase a quarantine warning, and "what lowers this?" is answered per
problem, in one place, by :func:`next_state` — which is a pure function,
so the rules are executable and the transition table is a test.

The problems, and what lowers each
----------------------------------
``fault``
    A run stopped and a human must act: an unexpected exception (exit 1),
    a schema mismatch (2), an environment fault (4), a cursor reset by a
    rebuild (6), a quarantine-cap overflow (7), an override that lost the
    lock (8). Lowered only by a later COMPLETED run of the same script —
    connected, lock taken, at least one row processed, none refused.

``correlated``
    A whole batch refused with one SQLSTATE and nothing accepted, held
    rather than quarantined. Lowered like ``fault``.

``quarantine``
    Rows were refused on content grounds and skipped. Carries a RUNNING
    count and the quarantine file's path. **Never lowered by later rows**
    — that a hundred subsequent memories synced cleanly is no evidence at
    all about the seven that were dropped. Lowered only by an explicit
    ``--ack-quarantine``, which is a human saying they have looked.

``degraded``
    The run could not do its job for a reason outside the database: the
    canonical is missing, the archive root is absent or holds no
    ``session.meta.json``, or rows were dropped and the cursor held.
    Lowered by a later run that completes, or that is idle without being
    degraded again — an idle run has, at least, found its inputs.

``outage``
    PostgreSQL was unreachable. A streak counter, standing from three
    consecutive runs (~15 minutes at a five-minute tick). The streak
    resets and the problem lowers on any run that CONNECTED — and
    resetting it touches nothing else, which is the bug that made an
    outage recovery clear a standing quarantine warning.

``refusals``
    (Indexer.) Transcripts PostgreSQL refused, counted across the WHOLE
    refusal memory rather than this run's scope. A project-scoped run may
    forget entries it visited but may not lower the problem unless the
    memory is empty.

Gate file format
----------------
The same shape as every other gate in ``~/.cache`` (``cc-archives-gate``,
``syncthing-gate``, ``memory-drift-gate``, ``cc-archive-drift-gate``):

* line 1 — the count of standing problems, ``0`` meaning clean;
* the remaining lines — one detail line per problem, printed verbatim.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

# ============================================================================
# Cycle outcomes
# ============================================================================

#: Processed at least one row and advanced the cursor.
CYCLE_COMPLETED = "completed"
#: Nothing to do — no new lines, no new archives.
CYCLE_IDLE = "idle"
#: Another instance held the advisory lock; this run did nothing at all.
CYCLE_CONTENDED = "contended"
#: PostgreSQL could not be reached.
CYCLE_OUTAGE = "outage"
#: Could not complete safely: missing inputs, or rows unaccounted for.
CYCLE_DEGRADED = "degraded"

#: Consecutive unreachable runs before the outage problem stands. At a
#: five-minute tick this is roughly fifteen minutes: long enough not to
#: nag over a restart, short enough to matter.
OUTAGE_STREAK_THRESHOLD = 3

# ============================================================================
# Problems
# ============================================================================

PROBLEM_FAULT = "fault"
PROBLEM_CORRELATED = "correlated"
PROBLEM_QUARANTINE = "quarantine"
PROBLEM_DEGRADED = "degraded"
PROBLEM_OUTAGE = "outage"
PROBLEM_REFUSALS = "refusals"

#: Render order, most actionable first. Stable, so the gate text does not
#: churn between runs for reasons nobody changed.
PROBLEM_ORDER: tuple[str, ...] = (
    PROBLEM_OUTAGE,
    PROBLEM_FAULT,
    PROBLEM_CORRELATED,
    PROBLEM_DEGRADED,
    PROBLEM_QUARANTINE,
    PROBLEM_REFUSALS,
)

# ============================================================================
# Gate files — one per script, never shared
# ============================================================================

#: A single file with two writers meant a clean run of one script erased
#: the other's alarm within a cron tick. ``daily-sync-trigger.sh``
#: iterates exactly these names.
MEMORIES_GATE: Path = Path.home() / ".cache" / "postgres-sync-memories-gate"
SESSIONS_GATE: Path = Path.home() / ".cache" / "postgres-sync-sessions-gate"
INDEXER_GATE: Path = Path.home() / ".cache" / "index-session-content-gate"

#: Every gate this module owns, in the order the trigger prints them.
ALL_GATES: tuple[Path, ...] = (MEMORIES_GATE, SESSIONS_GATE, INDEXER_GATE)


# ============================================================================
# State
# ============================================================================


@dataclass(frozen=True)
class Problem:
    """One standing problem: what to say, and how many of it there are."""

    detail: str
    count: int = 1


@dataclass(frozen=True)
class GateState:
    """
    Everything a script remembers between runs about its own gate.

    ``problems`` holds only what currently stands. ``outage_streak``
    persists even when the outage problem does not, because two
    consecutive failures are worth remembering and not worth reporting.
    """

    problems: dict[str, Problem] = field(default_factory=dict)
    outage_streak: int = 0
    #: ``{"acked_at": ISO, "acked_count": N}`` from the last
    #: ``--ack-quarantine``, so the record of who dismissed what survives
    #: the problem itself.
    acked: dict[str, object] = field(default_factory=dict)
    #: The archive root the indexer's refusal memory was built against.
    #: Pruning against a *different* root would forget every entry
    #: because none of its directories exist there (sixth re-audit).
    archive_root: str | None = None


@dataclass(frozen=True)
class GateEvent:
    """
    What one run of a script observed. The sole input to the transitions.

    ``connected`` is tri-state on purpose: ``True`` is evidence against an
    outage, ``False`` is evidence for one, and ``None`` — a run that never
    reached the point of trying — must move the counter in neither
    direction.
    """

    outcome: str
    connected: bool | None = None
    processed: int = 0
    quarantined: int = 0
    quarantine_file: Path | None = None
    #: Set to raise the ``fault`` problem with this text.
    fault_detail: str | None = None
    #: Set to raise the ``correlated`` problem with this text.
    correlated_detail: str | None = None
    #: Set to raise the ``degraded`` problem with this text.
    degraded_detail: str | None = None
    #: The operator has looked at the quarantine and is clearing it.
    ack_quarantine: bool = False
    #: Indexer only: outstanding refusals across the whole memory.
    refusals: int | None = None
    #: Indexer only: the archive root this run scanned, recorded so the
    #: refusal memory is never pruned against a different one.
    archive_root: str | None = None
    #: The script's name, for the problem text.
    script: str = ""


def quarantine_detail(script: str, count: int, path: Path | None) -> str:
    """Compose the quarantine problem's text, naming the acknowledgement."""
    where = path if path is not None else "the quarantine file"
    return (
        f"[{script}] {count} row(s) have been REFUSED by PostgreSQL and "
        f"quarantined to {where}. They are NOT in the database and the "
        f"cursor has moved past them. Repair and replay them, then clear "
        f"this with: ~/personal-assistant/venv/bin/python3 "
        f"~/personal-assistant/scripts/{script} --ack-quarantine"
    )


def outage_detail(script: str, streak: int) -> str:
    """Compose the outage problem's text."""
    return (
        f"[{script}] PostgreSQL has been unreachable for {streak} "
        f"consecutive runs (~{streak * 5} minutes). Nothing is reaching "
        f"the query layer; /recall and /search-sessions are serving stale "
        f"data. Check that PostgreSQL is running."
    )


def refusals_detail(script: str, count: int) -> str:
    """Compose the indexer's refusals text."""
    return (
        f"[{script}] {count} transcript(s) are NOT in the search index. "
        f"/search-sessions cannot find them. They are retried when the "
        f"file changes, or with --force."
    )


def _has_text(detail: str | None) -> bool:
    """Is this a problem someone could actually read?

    A blank or whitespace-only detail would raise a problem whose line
    says nothing: the count reports something wrong and the text reports
    nothing at all, which is worse than silence (sixth re-audit, low).
    """
    return bool(detail and detail.strip())


def next_state(state: GateState, event: GateEvent) -> GateState:
    """
    Apply one run's observations to the gate state. Pure, and total.

    Each problem is raised and lowered by its own evidence, and by nothing
    else. The order below is the order of the module docstring's list; the
    only interaction between problems is that none of them has any.

    A contended run — another instance held the lock, so this one did
    nothing whatsoever — changes nothing at all, not even the streak.
    """
    problems = dict(state.problems)
    streak = state.outage_streak

    # A contended run did nothing whatsoever, so it changes nothing —
    # not even the streak. Callers skip apply_gate entirely for this case;
    # the guard is here so the rule holds wherever it is called from.
    if event.outcome == CYCLE_CONTENDED:
        return GateState(problems, streak, state.acked, state.archive_root)

    # -- outage: connectivity is its own evidence, and touches nothing else
    if event.connected is True:
        streak = 0
        problems.pop(PROBLEM_OUTAGE, None)
    elif event.connected is False:
        streak += 1
        if streak >= OUTAGE_STREAK_THRESHOLD:
            problems[PROBLEM_OUTAGE] = Problem(
                outage_detail(event.script, streak), streak,
            )

    # -- quarantine: acknowledged first, so this run's own refusals are
    #    not silently acked along with the ones a human actually read.
    acked_count = 0
    if event.ack_quarantine:
        standing = problems.pop(PROBLEM_QUARANTINE, None)
        acked_count = standing.count if standing else 0
    if event.quarantined:
        standing = problems.get(PROBLEM_QUARANTINE)
        running = (standing.count if standing else 0) + event.quarantined
        problems[PROBLEM_QUARANTINE] = Problem(
            quarantine_detail(event.script, running, event.quarantine_file),
            running,
        )

    # -- degraded: raised by a reason, lowered by finding the inputs again
    if _has_text(event.degraded_detail):
        problems[PROBLEM_DEGRADED] = Problem(event.degraded_detail)
    elif event.outcome in (CYCLE_COMPLETED, CYCLE_IDLE):
        problems.pop(PROBLEM_DEGRADED, None)

    # -- fault and correlated: raised by a stop, lowered by real work
    if _has_text(event.fault_detail):
        problems[PROBLEM_FAULT] = Problem(event.fault_detail)
    if _has_text(event.correlated_detail):
        problems[PROBLEM_CORRELATED] = Problem(event.correlated_detail)

    # A completed run lowers fault and correlated whatever else it did.
    # Requiring zero quarantines meant a run that processed fifty rows
    # and refused one left a standing fault untouched — the quarantine
    # raises its own problem, and conflating the two hid the first
    # (sixth re-audit, finding M1).
    completed_cleanly = (
        event.outcome == CYCLE_COMPLETED
        and event.connected is True
        and event.processed >= 1
        and not _has_text(event.fault_detail)
        and not _has_text(event.correlated_detail)
    )
    if completed_cleanly:
        problems.pop(PROBLEM_FAULT, None)
        problems.pop(PROBLEM_CORRELATED, None)

    # -- refusals: about the whole memory, not this run's slice
    # ``refusals`` is already a count of the WHOLE memory, not this run's
    # slice, so an empty memory is an empty index-refusal problem whoever
    # observed it. The scope flag that used to guard this inverted the
    # rule: a scoped run that cleared the last refusal could not lower it
    # (sixth re-audit, finding M7).
    if event.refusals is not None:
        if event.refusals > 0:
            problems[PROBLEM_REFUSALS] = Problem(
                refusals_detail(event.script, event.refusals),
                event.refusals,
            )
        else:
            problems.pop(PROBLEM_REFUSALS, None)

    acked = state.acked
    if event.ack_quarantine:
        acked = {
            "acked_at": datetime.now(timezone.utc).isoformat(),
            "acked_count": acked_count,
        }
    root = event.archive_root or state.archive_root
    return GateState(problems, streak, acked, root)


# ============================================================================
# Persistence
# ============================================================================


def state_path_for(gate_path: Path) -> Path:
    """Return the sidecar state path beside a gate file."""
    return gate_path.with_name(gate_path.name + ".state.json")


def lock_path_for(gate_path: Path) -> Path:
    """Return the lock file guarding one gate and its sidecar."""
    return gate_path.with_name(gate_path.name + ".lock")


@contextmanager
def gate_lock(gate_path: Path) -> Iterator[None]:
    """
    Hold an exclusive lock over one gate's read-modify-write cycle.

    Without it, a cron tick and an ``--ack-quarantine`` can interleave:
    the ack reads a state containing the quarantine, the tick reads the
    same state, the ack writes it out without the problem, and the tick
    writes it back WITH the problem — resurrecting something a human had
    just dismissed (sixth re-audit, finding C2).

    A sidecar lock file, never renamed, because the state and the gate are
    both replaced by rename and a lock on either inode would be stale the
    moment it mattered.
    """
    lock_file = lock_path_for(gate_path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:  # pragma: no cover — the fd is still open
                pass


def _atomic_write(path: Path, text: str) -> None:
    """
    Replace ``path`` with ``text`` atomically: temp, fsync, rename, fsync.

    A reader — the trigger, or the next run — sees either the whole
    previous file or the whole new one. A kill part-way through leaves
    the previous one, rather than a truncated gate that reads as "no
    problems" (sixth re-audit, finding C2).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read_state(
    gate_path: Path,
    logger: logging.Logger | None = None,
) -> GateState:
    """
    Read the sidecar state, defaulting to "no problems, no outages".

    A missing file is ordinary and silent. An unreadable or corrupt one is
    reported: it means a script is about to forget every standing problem,
    and that must never happen quietly (fifth re-audit).
    """
    path = state_path_for(gate_path)
    if not path.exists():
        return GateState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        if logger is not None:
            logger.error(
                "Could not read the gate state %s (%s) — treating every "
                "standing problem as resolved, which may hide one.",
                path, exc,
            )
        return GateState()
    except (json.JSONDecodeError, ValueError) as exc:
        if logger is not None:
            logger.error(
                "Gate state %s is corrupt (%s) — treating every standing "
                "problem as resolved, which may hide one. It is rewritten "
                "from this run's observations.", path, exc,
            )
        return GateState()

    if not isinstance(raw, dict):
        if logger is not None:
            logger.error(
                "Gate state %s is not an object — ignoring it.", path,
            )
        return GateState()

    problems: dict[str, Problem] = {}
    for key, value in (raw.get("problems") or {}).items():
        if isinstance(value, dict) and isinstance(value.get("detail"), str):
            count = value.get("count", 1)
            problems[str(key)] = Problem(
                value["detail"],
                count if isinstance(count, int) and count > 0 else 1,
            )
    streak = raw.get("outage_streak", 0)
    acked = raw.get("acked")
    root = raw.get("archive_root")
    return GateState(
        problems=problems,
        outage_streak=streak if isinstance(streak, int) and streak >= 0 else 0,
        acked=acked if isinstance(acked, dict) else {},
        archive_root=root if isinstance(root, str) else None,
    )


def write_state(
    gate_path: Path,
    state: GateState,
    logger: logging.Logger | None = None,
) -> bool:
    """
    Persist the sidecar state. Reports I/O failure rather than swallowing it.

    A state we could not write means the next run starts from a blank
    slate and silently drops every standing problem — the same silence
    this whole module exists to remove.
    """
    path = state_path_for(gate_path)
    try:
        _atomic_write(path, json.dumps({
            "problems": {
                key: {"detail": problem.detail, "count": problem.count}
                for key, problem in state.problems.items()
            },
            "outage_streak": state.outage_streak,
            "acked": state.acked,
            "archive_root": state.archive_root,
        }, indent=2) + "\n")
    except OSError as exc:
        if logger is not None:
            logger.error(
                "Could not write the gate state %s (%s) — the next run "
                "will forget every standing problem.", path, exc,
            )
        return False
    return True


def render_gate(
    gate_path: Path,
    state: GateState,
    logger: logging.Logger | None = None,
) -> bool:
    """
    Write the gate file from the state: a count, then one line per problem.

    The count is the number of standing problems and may be ``0``; the
    trigger treats zero as clean. It is never clamped — a rendered gate
    says exactly how many independent things are wrong, and a clamp is how
    a count comes to mean something other than what it says.
    """
    standing = [
        state.problems[key] for key in PROBLEM_ORDER if key in state.problems
    ]
    # A problem under a key this version does not know about still shows.
    standing.extend(
        problem for key, problem in state.problems.items()
        if key not in PROBLEM_ORDER
    )
    body = "\n".join(" ".join(problem.detail.split()) for problem in standing)
    try:
        _atomic_write(
            gate_path, f"{len(standing)}\n" + (body + "\n" if body else ""),
        )
    except OSError as exc:
        if logger is not None:
            logger.error(
                "Could not write the gate file %s (%s) — this run's "
                "problems will not reach session start.", gate_path, exc,
            )
        return False
    return True


def apply_gate(
    event: GateEvent,
    *,
    gate_path: Path,
    logger: logging.Logger,
) -> GateState:
    """
    Read, transition, persist, render. The one entry point for a script.

    Returns the new state so a caller can log or assert on it.

    The whole read-modify-write happens under :func:`gate_lock`, so a
    cron tick cannot interleave with an acknowledgement and resurrect a
    problem a human has just dismissed (finding C2).
    """
    with gate_lock(gate_path):
        state = next_state(read_state(gate_path, logger), event)
        write_state(gate_path, state, logger)
        render_gate(gate_path, state, logger)
    if state.problems:
        logger.info(
            "Gate: %d standing problem(s) — %s",
            len(state.problems), ", ".join(sorted(state.problems)),
        )
    else:
        logger.info("Gate: clear.")
    return state
