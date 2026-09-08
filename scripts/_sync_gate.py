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
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from _sync_cursor import comparable_timestamp  # noqa: E402

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
#: Not a cycle at all: a human dismissing the quarantine problem. Its own
#: kind because it must touch that problem and nothing else — riding on
#: CYCLE_IDLE meant it also lowered ``degraded``, so acknowledging a
#: quarantine quietly declared a missing archive root resolved too
#: (seventh re-audit, finding M4).
CYCLE_ACK = "ack"

#: Consecutive unreachable runs before the outage problem stands. At a
#: five-minute tick this is roughly fifteen minutes: long enough not to
#: nag over a restart, short enough to matter.
#: What :func:`read_state_with_status` found on disk. A missing sidecar
#: and a corrupt one both yield an empty state, and only the status tells
#: them apart (ninth re-audit, finding M2).
STATE_MISSING = "missing"
STATE_OK = "ok"
STATE_CORRUPT = "corrupt"

OUTAGE_STREAK_THRESHOLD = 3

#: How long to wait for another process's gate lock before giving up and
#: saying so. Long enough for any honest cycle, short enough that a wedged
#: holder cannot hang a session hook.
LOCK_WAIT_SECONDS = 10.0

# ============================================================================
# Problems
# ============================================================================

PROBLEM_FAULT = "fault"
PROBLEM_CORRELATED = "correlated"
PROBLEM_QUARANTINE = "quarantine"
PROBLEM_DEGRADED = "degraded"
PROBLEM_OUTAGE = "outage"
PROBLEM_REFUSALS = "refusals"

#: The word the quarantine problem uses for a row PostgreSQL would not
#: accept. Named, not inlined, because three test modules assert on this
#: exact spelling: with the word written out in both places, rewording the
#: message leaves every guard passing against a sentence the code no longer
#: emits (eleventh re-audit follow-up L1).
QUARANTINE_REFUSED_WORD = "REFUSED"

#: The fragment that says the acknowledged quarantine position was reset
#: under the operator's feet, so rows they had already dismissed are being
#: counted again. Same reason as above: shared by the message and by the
#: tests that assert it appears — and, just as importantly, by the tests
#: that assert it does NOT (an ordinary quarantine must not claim a reset).
CURSOR_RESET_PHRASE = "cursor was reset"

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
    #: ``{"acked_at": ISO, "acked_count": N, "acked_position": P}``.
    #: ``acked_at``/``acked_count`` are the record of the last
    #: ``--ack-quarantine``, kept so what was dismissed survives the
    #: problem itself. ``acked_position`` is how far into the
    #: append-only quarantine file the operator has read, and is
    #: maintained by EVERY transition — clamped to the file's length and
    #: reset when the cursor goes backwards.
    acked: dict[str, object] = field(default_factory=dict)
    #: The archive root the indexer's refusal memory was built against.
    #: Pruning against a *different* root would forget every entry
    #: because none of its directories exist there (sixth re-audit).
    archive_root: str | None = None
    #: Where the last run that looked LEFT the sync cursor. The next
    #: run's STARTING position is measured against it, so the comparison
    #: spans the gap between runs — which is when a rebuild happens. A
    #: rebuild that removes the key, or rewinds it, is how
    #: previously acknowledged rows come to be re-offered — and an
    #: ordinary rebuild raises no exit 6 for anyone to notice, so the
    #: gate detects it by comparing this with the next run's observation
    #: (ninth re-audit, finding C2). ``int`` for the memories sync (a
    #: line number), ``str`` for the sessions sync (an ISO timestamp).
    cursor_position: int | str | None = None


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
    #: How many entries the quarantine file holds right now. The gate
    #: DERIVES the standing problem from this and the acknowledged
    #: position, rather than accumulating a per-run delta — a delta is
    #: lost whenever a run cannot write its gate, or counts a
    #: deduplicated re-offer twice (eighth re-audit, finding C1).
    #: ``None`` means "could not read it", which is not zero.
    quarantine_entries: int | None = None
    quarantine_file: Path | None = None
    #: A rebuild cleared the cursor, so the rows will be re-offered and
    #: re-refused: forget the acknowledged position, or the second
    #: refusal of the same rows would be silently below it. Set
    #: explicitly on the exit-6 path; ordinary rebuilds are detected from
    #: ``cursor_position`` instead, because they raise nothing.
    reset_quarantine_ack: bool = False
    #: Where the sync cursor stood when this run STARTED, compared with
    #: where the last run LEFT it. ``None`` with ``cursor_seen`` true
    #: means the key is not in the cursor file at all — a rebuild removed
    #: it. The comparison has to span the gap BETWEEN runs, which is when
    #: a rebuild happens; comparing a run with itself would see nothing.
    cursor_position: int | str | None = None
    #: Where this run left the cursor, which is what the next run's
    #: starting position is measured against.
    cursor_position_after: int | str | None = None
    #: Did this run look at the cursor? The indexer has none, and an
    #: event that never looked must not erase the recorded position.
    cursor_seen: bool = False
    #: Set to raise the ``fault`` problem with this text.
    fault_detail: str | None = None
    #: Set to raise the ``correlated`` problem with this text.
    correlated_detail: str | None = None
    #: Set to raise the ``degraded`` problem with this text.
    degraded_detail: str | None = None
    #: Indexer only: outstanding refusals across the whole memory.
    refusals: int | None = None
    #: Indexer only: the archive root this run scanned, recorded so the
    #: refusal memory is never pruned against a different one.
    archive_root: str | None = None
    #: The script's name, for the problem text.
    script: str = ""


def quarantine_detail(
    script: str,
    count: int,
    path: Path | None,
    *,
    after_reset: bool = False,
) -> str:
    """Compose the quarantine problem's text, naming the acknowledgement."""
    where = path if path is not None else "the quarantine file"
    reset_note = (
        f" The sync {CURSOR_RESET_PHRASE} since these were acknowledged, so "
        f"rows you had already dismissed are being offered again and are "
        f"counted here."
        if after_reset else ""
    )
    return (
        f"[{script}] {count} row(s) have been {QUARANTINE_REFUSED_WORD} "
        f"by PostgreSQL and quarantined to {where}. They are NOT in the "
        f"database and the "
        f"cursor has moved past them.{reset_note} Repair and replay them, "
        f"then clear this with: ~/personal-assistant/venv/bin/python3 "
        f"~/personal-assistant/scripts/{script} --ack-quarantine"
    )


def cursor_went_backwards(
    recorded: int | str | None,
    current: int | str | None,
) -> bool:
    """
    Did the sync cursor move backwards since the last run that looked?

    A rebuild removes the cursor key or rewinds it, and the rows the
    operator had already acknowledged are then re-offered and refused
    again. Only the rebuild-during-a-sync case raises exit 6; an ordinary
    rebuild raises nothing at all, so the gate has to see the movement
    for itself (ninth re-audit, finding C2).

    ``recorded is None`` means there is nothing to compare against — a
    first run, or one after the state was cleared — which is not evidence
    of anything. A ``current`` of ``None`` means the key has gone.
    """
    if recorded is None:
        return False
    if current is None:
        return True
    try:
        return _comparable_cursor(current) < _comparable_cursor(recorded)
    except TypeError:
        # Two different shapes of cursor: a version change, not a rewind.
        return False


def _comparable_cursor(value: int | str) -> int | str:
    """Put a timestamp cursor into one spelling before comparing it.

    Delegates to :func:`_sync_cursor.comparable_timestamp`, which the
    sessions cycle's own newer-than-the-cursor filter also uses. Two
    spellings of the same instant compare unequal, so a helper used by
    only one of the two readers is a difference of opinion waiting to
    happen (tenth re-audit L1; eleventh re-audit L2).
    """
    if isinstance(value, str):
        return comparable_timestamp(value)
    return value


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
        return GateState(
            problems, streak, state.acked, state.archive_root,
            state.cursor_position,
        )

    if event.outcome == CYCLE_ACK:
        # Touches the quarantine problem and nothing else: not the
        # streak, not degraded, not a fault. A human has read something;
        # that is evidence about exactly one thing (seventh re-audit,
        # finding M4).
        #
        # Acknowledging records the POSITION in the append-only
        # quarantine file, not a count: rows quarantined after this point
        # are new and must be reported, and a re-derived count is what
        # makes that work (eighth re-audit, finding C1).
        standing = problems.pop(PROBLEM_QUARANTINE, None)
        acked = dict(state.acked)
        acked.update({
            "acked_at": datetime.now(timezone.utc).isoformat(),
            "acked_count": standing.count if standing else 0,
            "acked_position": (
                event.quarantine_entries
                if event.quarantine_entries is not None
                else acked.get("acked_position", 0)
            ),
        })
        return GateState(
            problems, streak, acked, state.archive_root,
            state.cursor_position,
        )

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
    # -- quarantine: DERIVED from the file, never accumulated ------------
    # The count is "entries in the append-only quarantine file, beyond the
    # position a human acknowledged". Every run recomputes it, so a tick
    # that could not write its gate, a path that forgot to report, and a
    # re-offer that deduplicated on disk all repair themselves next time
    # (finding C1).
    acked_position = state.acked.get("acked_position", 0)
    if not isinstance(acked_position, int) or acked_position < 0:
        acked_position = 0
    # A rebuild is detected two ways: the exit-6 path says so outright,
    # and an ordinary rebuild — which raises nothing for anyone to notice
    # — is caught by the cursor having moved backwards since the last run
    # that looked (ninth re-audit, finding C2).
    cursor_position = state.cursor_position
    was_reset = event.reset_quarantine_ack
    if event.cursor_seen:
        if cursor_went_backwards(state.cursor_position, event.cursor_position):
            was_reset = True
        cursor_position = event.cursor_position_after
    if was_reset:
        acked_position = 0
    if event.quarantine_entries is not None:
        entries = max(0, event.quarantine_entries)
        acked_position = min(acked_position, entries)
        outstanding = entries - acked_position
        if outstanding > 0:
            problems[PROBLEM_QUARANTINE] = Problem(
                quarantine_detail(
                    event.script, outstanding, event.quarantine_file,
                    after_reset=was_reset,
                ),
                outstanding,
            )
        else:
            problems.pop(PROBLEM_QUARANTINE, None)

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

    # PERSIST the position this transition computed. Returning
    # ``state.acked`` unchanged threw away the exit-6 reset and the
    # clamp above: both lasted exactly one render, and the next idle run
    # recomputed a stale outstanding count from the old position — an
    # idle run silently changing a gate, which is the one thing the state
    # machine exists to forbid (ninth re-audit, finding C1).
    acked = dict(state.acked)
    acked["acked_position"] = acked_position
    # Set once and never flipped: a run against a different root must not
    # claim a memory built elsewhere, or the next prune would forget it
    # all (seventh re-audit, low).
    root = state.archive_root or event.archive_root
    return GateState(problems, streak, acked, root, cursor_position)


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
        # Bounded and non-blocking rather than a bare LOCK_EX: a wedged
        # holder would otherwise hang a cron tick, or a session hook,
        # for ever with nothing said (seventh re-audit, low).
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"another process has held {lock_file} for more "
                        f"than {LOCK_WAIT_SECONDS}s"
                    )
                time.sleep(0.05)
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

    Callers that need to tell "there is nothing recorded" from "there is
    something recorded and it is rubbish" — the acknowledgement is the
    only one — must use :func:`read_state_with_status` instead. Both
    conditions produce an empty state, and treating the first as the
    second refused to acknowledge anything on a healthy pipeline (ninth
    re-audit, finding M2).
    """
    return read_state_with_status(gate_path, logger)[0]


def read_state_with_status(
    gate_path: Path,
    logger: logging.Logger | None = None,
) -> tuple[GateState, str]:
    """
    Read the sidecar and say which of three things happened.

    Returns ``(state, status)`` where status is one of
    :data:`STATE_MISSING` (no sidecar — a machine that has never run this
    script, or one whose cache was cleared), :data:`STATE_OK` (read and
    parsed, however empty), or :data:`STATE_CORRUPT` (present but not
    usable). The state is empty in the first and last cases alike, which
    is why the status has to be carried separately.
    """
    path = state_path_for(gate_path)
    if not path.exists():
        return GateState(), STATE_MISSING
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        if logger is not None:
            logger.error(
                "Could not read the gate state %s (%s) — treating every "
                "standing problem as resolved, which may hide one.",
                path, exc,
            )
        return GateState(), STATE_CORRUPT
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        if logger is not None:
            logger.error(
                "Gate state %s is corrupt (%s) — treating every standing "
                "problem as resolved, which may hide one. It is rewritten "
                "from this run's observations.", path, exc,
            )
        return GateState(), STATE_CORRUPT

    if not isinstance(raw, dict):
        if logger is not None:
            logger.error(
                "Gate state %s is not an object — ignoring it.", path,
            )
        return GateState(), STATE_CORRUPT

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
    cursor = raw.get("cursor_position")
    return GateState(
        problems=problems,
        outage_streak=streak if isinstance(streak, int) and streak >= 0 else 0,
        acked=acked if isinstance(acked, dict) else {},
        archive_root=root if isinstance(root, str) else None,
        cursor_position=cursor if isinstance(cursor, (int, str)) else None,
    ), STATE_OK


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
            "cursor_position": state.cursor_position,
        }, indent=2) + "\n")
    except OSError as exc:
        if logger is not None:
            logger.error(
                "Could not write the gate state %s (%s) — the next run "
                "will forget every standing problem.", path, exc,
            )
        return False
    return True


def render_text(state: GateState) -> str:
    """
    The exact text a gate file holds for this state.

    Factored out of :func:`render_gate` so a caller can ask whether the
    file on disk still AGREES with the state, without matching on a
    substring of the problem text. A sentinel word in the detail is a
    check that stops working the day someone improves the wording (ninth
    re-audit, low).
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
    return f"{len(standing)}\n" + (body + "\n" if body else "")


def gate_matches_state(gate_path: Path, state: GateState) -> bool:
    """
    Does the rendered gate file say exactly what this state says?

    ``False`` when the file is missing, unreadable, or out of step — all
    of which mean session start is showing something other than the
    truth. Used by the acknowledgement, which is the one command for
    which a half-completed write IS the error.
    """
    try:
        return gate_path.read_text(encoding="utf-8") == render_text(state)
    except (OSError, UnicodeDecodeError):
        return False


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
    try:
        _atomic_write(gate_path, render_text(state))
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
    Read, transition, persist, render — then return WHAT IS ON DISK.

    The returned state is re-read after the write, not the in-memory
    result of the transition (seventh re-audit, finding C1). Returning
    the intended state meant a caller could not tell a successful write
    from a failed one: ``--ack-quarantine`` reported "cleared" and exited
    0 over an EACCES, while the sidecar still carried the problem. Now
    the caller sees what a future run will see, which is the only thing
    that matters.

    Never raises. A gate that cannot be written must not change what the
    script does about the condition the gate was describing (finding M1):
    a schema mismatch still exits 2, an absent archive root still exits
    2, and the failure is reported at ERROR in its own right. The one
    caller that treats it as an error in itself is the acknowledgement,
    which has nothing else to do.

    The whole read-modify-write happens under :func:`gate_lock`, so a
    cron tick cannot interleave with an acknowledgement and resurrect a
    problem a human has just dismissed (finding C2 of the sixth round).
    """
    try:
        with gate_lock(gate_path):
            previous = read_state(gate_path, logger)
            if event.cursor_seen and cursor_went_backwards(
                previous.cursor_position, event.cursor_position,
            ):
                logger.warning(
                    "The sync cursor has moved backwards (%r -> %r) — a "
                    "rebuild has re-offered rows that were already "
                    "acknowledged. The quarantine count starts again from "
                    "the whole file.",
                    previous.cursor_position, event.cursor_position,
                )
            state = next_state(previous, event)
            persisted = write_state(gate_path, state, logger)
            rendered = render_gate(gate_path, state, logger)
            # Re-read inside the lock: what the next run will see.
            on_disk = read_state(gate_path, logger)
    except (OSError, TimeoutError) as exc:
        logger.error(
            "THE GATE COULD NOT BE PERSISTED (%s: %s). This run's "
            "problems will not reach session start, and any standing "
            "problem is unchanged. The condition itself is unaffected — "
            "see the exit code.", type(exc).__name__, exc,
        )
        return read_state_safely(gate_path, logger)

    if not (persisted and rendered):
        logger.error(
            "THE GATE COULD NOT BE PERSISTED. This run's problems will "
            "not reach session start; the errors above say why."
        )
    elif on_disk.problems:
        logger.info(
            "Gate: %d standing problem(s) — %s",
            len(on_disk.problems), ", ".join(sorted(on_disk.problems)),
        )
    else:
        logger.info("Gate: clear.")
    return on_disk


def read_state_safely(
    gate_path: Path,
    logger: logging.Logger | None = None,
) -> GateState:
    """Read the state, returning an empty one if even that fails."""
    try:
        return read_state(gate_path, logger)
    except OSError:
        return GateState()
