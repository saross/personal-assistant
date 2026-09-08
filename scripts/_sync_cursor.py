#!/usr/bin/env python3
"""
Shared quarantine helper for sync scripts.

Background
----------
Several sync scripts (``sync-to-postgres.py``, ``sync-sessions-to-postgres.py``,
``sync-to-zotero.py``) advance a cursor through an append-only JSONL canonical.
Without care, a cursor advance past a record the script could not process is a
silent data-loss event: the record never re-enters the sync pipeline, even
after the underlying issue is repaired.

The audit (``reports/audit-2026-05-02``) documented four such sites under
inter-cluster issue IC2:

* ``sync-to-postgres.py``  — corrupt JSONL slice silently skipped (B-C4).
* ``sync-sessions-to-postgres.py`` — id-less session metadata silently skipped
  (B-M2).
* ``sync-to-zotero.py``    — cursor never rewinds when the JSONL shrinks
  (D-C3).
* ``sync-to-zotero.py``    — ``skipped_not_found`` advances the cursor past a
  transiently-missing Zotero item (D-M10).

The agreed contract after this batch is: every cursor advance is either
(a) a successful processing, or (b) an *explicit* quarantine of the skipped
record. This module factors out the quarantine bookkeeping so each call site
follows the same shape.

Quarantine schema
-----------------
Each quarantine line is one JSON object::

    {
        "reason": "<short tag, e.g. 'parse_failure'>",
        "quarantined_at": "<ISO 8601 UTC timestamp>",
        "record": <original record, opaque>
    }

The ``record`` field is whatever the caller hands us — typically the original
parsed dict, or for parse failures the offending raw line. The operator can
later reconcile by reading the file back.

Appends are deduplicated on the ``(reason, record)`` pair by default (audit
round two, finding P14): a halted cursor re-reads the same input slice on every
cron tick, and without dedup one poison line accretes 288 identical entries a
day, burying the entries that are genuinely distinct.

Shared cursor file
------------------
:func:`update_cursor_file` is the one supported way to change
``memories/sync-cursors.json``. It takes an exclusive ``flock`` for the whole
read-modify-write cycle and writes via temp-file + :func:`os.replace`, so
neither an interleaving between two callers *that both use it* nor a kill
part-way through a write can lose a cursor (audit round two, finding P16).

That qualification is load-bearing, and an earlier version of this docstring
omitted it (re-audit finding M2): ``flock`` is advisory, so the guarantee
holds only over the writers that take the lock. Every writer in the
repository now does — ``sync-to-postgres.py``, ``sync-sessions-to-postgres.py``,
``sync-to-zotero.py``, and ``rebuild-postgres.py`` — and any new one must,
or it silently reintroduces the lost-update it was written to prevent.

A caller that already holds the lock (``rebuild-postgres.py`` holds it across
its TRUNCATE so a concurrent sync cannot write a pre-rebuild position back
afterwards) uses :func:`apply_cursor_update` instead. ``flock`` is per open
file description, so taking it twice in one process would deadlock.

Quarantine file location
------------------------
We deliberately keep the existing quarantine paths used by the postgres syncs
(``data/memories/quarantine-postgres-drops.jsonl`` and
``data/sessions/quarantine-postgres-drops.jsonl``). Cluster-B X4 and IC6 flag
that those paths sit inside the data submodule and may be auto-committed; that
trade-off is being addressed separately (Batch later in the audit). For Batch 2
we keep the contract intact.

JSONL shrink detection
----------------------
:func:`detect_jsonl_shrink` lets a caller compare a saved cursor (line number)
against the current line count of a JSONL canonical. When the file has shrunk
below the saved cursor (compaction, dedup migration, submodule revert), we do
**not** silently rewind the cursor. The caller is expected to log a WARN, set
the cursor to ``0`` (forcing a full re-scan), and proceed. This catches D-C3.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


#: ``quarantine_record`` appended a new line.
QUARANTINE_WRITTEN = "written"
#: An identical entry was already on disk; nothing was appended.
QUARANTINE_DUPLICATE = "duplicate"
#: The write raised; the entry is NOT on disk.
QUARANTINE_FAILED = "failed"


def _iso_now() -> str:
    """Return an ISO 8601 UTC timestamp for quarantine entries."""
    return datetime.now(timezone.utc).isoformat()


def _ends_mid_line(path: Path) -> bool:
    """Does this file end without a trailing newline?

    Appending straight onto such a file would join two entries into one
    line, so the writer starts a fresh line first. This asks only about
    the newline, not about whether the last line parses: a COMPLETE
    record whose newline was lost still needs a separator before the next
    one, and a partial line needs one too.
    """
    try:
        with path.open("rb") as handle:
            if handle.seek(0, 2) == 0:
                return False
            handle.seek(-1, 2)
            return handle.read(1) != b"\n"
    except OSError:
        return False


def comparable_timestamp(value: str) -> str:
    """
    Put an ISO-8601 instant into ONE spelling, for lexical comparison.

    The sessions cursor is compared as text, and the same instant has
    several spellings: a trailing ``Z``, a trailing ``z``, an explicit
    ``+00:00``, or no offset at all. ``+`` sorts before ``Z`` and a naive
    string is a prefix of an aware one, so mixing spellings makes a
    cursor look as though it has gone backwards and announces a rebuild
    that never happened.

    One helper, used by the gate's rebuild check and by the cycle's own
    "is this session newer than the cursor" filter, so the two can never
    disagree about the order of two timestamps (eleventh re-audit, L2).
    """
    if not isinstance(value, str) or not value:
        return value
    text = value.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    marker = text.find("T")
    if marker != -1:
        tail = text[marker + 1:]
        # No offset at all: treat it as UTC, which is what every writer
        # in this repo means by a naive timestamp.
        if "+" not in tail and "-" not in tail:
            text += "+00:00"
    return text


def normalise_line_cursor(
    value: object,
    *,
    key: str = "the cursor",
    logger: logging.Logger | None = None,
) -> int | None:
    """
    Coerce a line-number cursor to an ``int``, or ``None`` if it is not one.

    The cursor file is JSON on disk that a rebuild, a merge, or a person
    can rewrite, so its type is not guaranteed. Every reader must reach
    the SAME conclusion about it: the cycle used to accept the string
    ``"500"`` while the gate's type filter rejected it, so the gate saw
    the cursor vanish and reported a rebuild that had not happened
    (tenth re-audit, finding M1).

    A digit string is coerced — it is unambiguously the same position.
    Anything else is treated as absent and warned about once, because a
    cursor nobody can read is a real problem and silently resyncing from
    zero would hide it.
    """
    if isinstance(value, bool):
        pass  # bools are ints in Python and are never a line number
    elif isinstance(value, int) and value >= 0:
        return value
    elif isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    if value is None:
        return None
    # A NEGATIVE integer falls through to the warning below rather than
    # returning quietly: it is as unusable as a string of letters, it
    # resets the acknowledged position, and the docstring has always
    # promised it would be reported (eleventh re-audit, finding M3).
    if logger is not None:
        logger.warning(
            "%s is %r, which is not a line number — treating it as absent "
            "and syncing from the beginning. Check the cursor file.",
            key, value,
        )
    return None


def normalise_timestamp_cursor(
    value: object,
    *,
    key: str = "the cursor",
    logger: logging.Logger | None = None,
) -> str | None:
    """
    Coerce a timestamp cursor to a ``str``, or ``None`` if it is not one.

    The sessions cursor is an ISO-8601 instant, compared lexically, so
    the value has to BE one: ``'abc'`` sorts after every real timestamp,
    which made the sync skip every session it found and report itself
    idle for ever, with nothing on the gate (eleventh re-audit, finding
    M1). A number, an object, or a string that will not parse is
    therefore treated as absent and warned about.
    """
    if isinstance(value, str) and value.strip():
        candidate = comparable_timestamp(value)
        try:
            datetime.fromisoformat(candidate)
        except ValueError:
            pass
        else:
            return value
    if value is None:
        return None
    if logger is not None:
        logger.warning(
            "%s is %r, which is not an ISO-8601 timestamp — treating it "
            "as absent and syncing from the beginning. Check the cursor "
            "file.", key, value,
        )
    return None


def cursor_fault_detail(
    script: str, key: str, cursor_file: Path, value: object, expected: str,
) -> str:
    """
    The gate text for a cursor that is present and unusable.

    A cursor nobody can read is the failure this gate exists for: the
    sync resyncs from the beginning every tick, the acknowledged
    quarantine position is reset with it, and without this line none of
    that reaches anybody (eleventh re-audit, findings M1 and M3).
    """
    return (
        f"[{script}] the sync cursor {key} in {cursor_file} is "
        f"{value!r}, which is not {expected}. The sync is starting from "
        f"the beginning on every run and the acknowledged quarantine "
        f"position has been reset, so dismissed rows are being reported "
        f"again. Repair the cursor file."
    )


def append_quarantine_entry(quarantine_path: Path, entry: Any) -> bool:
    """
    THE one code path that appends to a quarantine file. True on success.

    Every writer goes through here, because the append has a
    precondition that is easy to forget and expensive to get wrong: a
    file that ends mid-line must be given its separator first. A second
    writer that appended directly ran its record onto the end of a
    complete row whose newline had been lost, and BOTH then vanished
    from the gate, the health report, the duplicate check and the
    acknowledgement alike (eleventh re-audit, finding C1).

    The entry is written exactly as given: the two producers use
    different shapes — a bare row, and a ``{reason, quarantined_at,
    record}`` wrapper — and both are understood by
    :func:`read_quarantine_entries`.
    """
    try:
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(entry, ensure_ascii=False)
        with quarantine_path.open("a", encoding="utf-8") as handle:
            # Repair a partial trailing line rather than concatenating
            # onto it, which would corrupt two entries instead of one.
            if _ends_mid_line(quarantine_path):
                handle.write("\n")
            handle.write(payload + "\n")
    except (OSError, TypeError, ValueError):
        return False
    return True


def read_quarantine_entries(quarantine_path: Path) -> list[dict] | None:
    """
    Every complete record in a quarantine file, or ``None`` if unreadable.

    THE one parser for this format. The gate's count, the writer's
    duplicate check, and ``/memory-health`` all read the file through
    here, because two readers that disagree about what a record is
    produce a row that is invisible to one of them for ever — which is
    exactly what happened when the counter skipped a trailing line the
    deduper still matched against (tenth re-audit, finding C1).

    What counts as a record:

    * a non-blank line that parses as a JSON object;
    * including the LAST line when the file ends without a newline, if it
      parses — an interrupted write that got all the way to the closing
      brace produced a whole record, and the missing newline is a
      separator problem, not a content one.

    What does not:

    * blank lines;
    * anything that does not parse, or parses to something other than an
      object — damage, hand-editing, or a write cut off mid-record.

    ``None`` (missing or unreadable) is emphatically not "empty": the
    data submodule being unmounted must not erase a standing alarm
    (ninth re-audit, finding M1).
    """
    try:
        with quarantine_path.open("r", encoding="utf-8") as handle:
            entries: list[dict] = []
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    entries.append(parsed)
            return entries
    except (OSError, UnicodeDecodeError):
        return None


def count_quarantine_entries(quarantine_path: Path) -> int | None:
    """
    Return how many entries the quarantine file holds, or None if unknown.

    The file is append-only, so its length is a running total of every
    row that has ever been quarantined — which is what lets the gate
    DERIVE the standing problem from the file rather than accumulating a
    delta per run (eighth re-audit, finding C1). A delta is lost whenever
    a run cannot write its gate, counts a deduplicated re-offer twice, or
    misses a path that never reported at all; a re-derived count repairs
    itself on the next tick.

    Counts exactly what :func:`read_quarantine_entries` returns, which is
    exactly what the duplicate check matches against, so the gate's
    number is always the number of rows an operator can find and replay.
    """
    entries = read_quarantine_entries(quarantine_path)
    return None if entries is None else len(entries)


def _entry_fingerprint(reason: str, record: Any) -> str:
    """
    Return a stable hash identifying one quarantine entry.

    The ``quarantined_at`` timestamp is deliberately excluded — two
    appends of the same ``(reason, record)`` pair are the *same* event
    observed twice (audit round two, finding P14 / lens A-M12), not two
    events. ``sort_keys`` makes dict ordering irrelevant; ``default=str``
    keeps a non-serialisable record hashable rather than raising here
    (the write path reports that failure).
    """
    try:
        payload = json.dumps(
            {"reason": reason, "record": record},
            sort_keys=True, ensure_ascii=False, default=str,
        )
    except (TypeError, ValueError):  # pragma: no cover — default=str is total
        payload = f"{reason}\x1f{record!r}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


#: Per-path cache of the fingerprints already on disk, keyed by the file's
#: ``(size, mtime_ns)`` signature so an unchanged file is read once per
#: process rather than once per quarantine call.
_FINGERPRINT_CACHE: dict[Path, tuple[tuple[int, int], set[str]]] = {}


def _existing_fingerprints(quarantine_path: Path) -> set[str]:
    """
    Return the fingerprints of every entry already in ``quarantine_path``.

    Returns an empty set when the file is missing or unreadable — a
    quarantine we cannot read is treated as empty, which risks a
    duplicate append but never suppresses a genuine one.
    """
    try:
        stat = quarantine_path.stat()
    except OSError:
        return set()

    signature = (stat.st_size, stat.st_mtime_ns)
    cached = _FINGERPRINT_CACHE.get(quarantine_path)
    if cached is not None and cached[0] == signature:
        return cached[1]

    # THE same parser the gate counts with. Two readers of one file that
    # disagree about what a record is will always leave some row visible
    # to one and invisible to the other (tenth re-audit, finding C1).
    entries = read_quarantine_entries(quarantine_path)
    if entries is None:
        return set()
    fingerprints = {
        _entry_fingerprint(
            str(entry.get("reason", "")), entry.get("record"),
        )
        for entry in entries
    }

    _FINGERPRINT_CACHE[quarantine_path] = (signature, fingerprints)
    return fingerprints


def quarantine_record(
    quarantine_path: Path,
    record: Any,
    reason: str,
    *,
    logger: logging.Logger | None = None,
    dedup: bool = True,
) -> str:
    """
    Append a single quarantine entry to ``quarantine_path``.

    Parameters
    ----------
    quarantine_path:
        Destination JSONL file. Parent directories are created on demand.
    record:
        The original record (any JSON-serialisable value). For parse
        failures, callers may pass the offending raw line as a string.
    reason:
        Short tag describing why the record was quarantined, for example
        ``"parse_failure"``, ``"missing_id"``, ``"zotero_item_missing"``.
    logger:
        Optional logger; if provided, a single INFO line records the
        quarantine event, or an ERROR line if the write fails.
    dedup:
        When true (the default), an entry whose ``(reason, record)`` pair
        is already present in the file is not appended a second time.
        Audit round two, finding P14 (lens A-M12): while a sync cursor is
        halted, every five-minute cron tick re-parses the same input
        slice and re-quarantines the same lines — 288 duplicate entries
        per poison line per day. Pass ``dedup=False`` only when repeated
        occurrences of an identical record are themselves the signal.

    Returns
    -------
    str
        One of :data:`QUARANTINE_WRITTEN` (this call appended a line),
        :data:`QUARANTINE_DUPLICATE` (an identical entry was already
        there), or :data:`QUARANTINE_FAILED` (the write raised).

        The first two both mean "the entry is on disk", which is what a
        cursor advance needs. The distinction matters to the caller's
        *count*: a gate that says "7 rows quarantined" must match the
        file, and tallying attempted writes counted the same poison line
        once per cron tick (sixth re-audit, finding M4).
    """
    fingerprint = _entry_fingerprint(reason, record)
    if dedup and fingerprint in _existing_fingerprints(quarantine_path):
        if logger is not None:
            logger.debug(
                "Quarantine entry already present (reason=%r) in %s — "
                "not appending a duplicate",
                reason, quarantine_path,
            )
        return QUARANTINE_DUPLICATE

    entry = {
        "reason": reason,
        "quarantined_at": _iso_now(),
        "record": record,
    }
    if not append_quarantine_entry(quarantine_path, entry):
        if logger is not None:
            logger.error(
                "Could not write quarantine entry to %s (reason=%r)",
                quarantine_path, reason,
            )
        return QUARANTINE_FAILED

    # Keep the cache in step with our own append so a second call in the
    # same process dedups even where the filesystem's mtime granularity
    # would not reveal the change.
    cached = _FINGERPRINT_CACHE.get(quarantine_path)
    if cached is not None:
        cached[1].add(fingerprint)
        try:
            stat = quarantine_path.stat()
            _FINGERPRINT_CACHE[quarantine_path] = (
                (stat.st_size, stat.st_mtime_ns), cached[1],
            )
        except OSError:  # pragma: no cover — the file was just written
            _FINGERPRINT_CACHE.pop(quarantine_path, None)

    if logger is not None:
        logger.info(
            "Quarantined record (reason=%r) to %s",
            reason, quarantine_path,
        )
    return QUARANTINE_WRITTEN


def advance_or_quarantine(
    *,
    success: bool,
    record: Any,
    reason: str | None,
    quarantine_path: Path,
    logger: logging.Logger | None = None,
) -> bool:
    """
    Encapsulate the cursor-advance policy for a single record.

    If ``success`` is true, the caller's cursor advance is fine — this
    function is a no-op aside from returning ``True``.

    If ``success`` is false, the record is appended to the quarantine
    file (via :func:`quarantine_record`) and a WARN is logged. The
    function still returns ``True`` so the caller can advance past the
    poison record without infinite-looping; callers who prefer to halt
    on quarantine should not rely on this helper for that decision.

    Parameters
    ----------
    success:
        Did the caller successfully process the record?
    record:
        The record being processed (passed straight through to the
        quarantine entry on failure).
    reason:
        Why the record was skipped. Required when ``success`` is False.
    quarantine_path:
        Destination JSONL file for the quarantine entry.
    logger:
        Optional logger; if provided, the quarantine event and any I/O
        failure are logged.

    Returns
    -------
    bool
        Always returns ``True`` to indicate the caller may advance the
        cursor past this record. Callers with a stricter policy
        (e.g. halt-on-any-skip) should not use this helper.
    """
    if success:
        return True

    # Failure path: quarantine + WARN. The caller still advances so a
    # poison record cannot lock the cursor in place forever.
    if reason is None:
        reason = "unspecified"
    if logger is not None:
        logger.warning(
            "Quarantining record (reason=%r) — cursor will advance past it",
            reason,
        )
    quarantine_record(
        quarantine_path,
        record,
        reason,
        logger=logger,
    )
    return True


# ---------------------------------------------------------------------------
# Shared cursor file (memories/sync-cursors.json)
# ---------------------------------------------------------------------------


@contextmanager
def cursor_file_lock(cursor_path: Path) -> Iterator[None]:
    """
    Hold an exclusive advisory lock over a cursor file's sidecar lock.

    Why a sidecar rather than the cursor file itself: the cursor is
    rewritten via temp-file + :func:`os.replace`, so any lock held on the
    original inode would be invalidated by the rename. A lock file that is
    never renamed sidesteps that hazard. This mirrors
    ``hooks/extraction-hook.py::cursor_file_lock``, which solved the same
    problem for the extraction cursor.

    Why this exists (audit round two, finding P16 / lens A-M14): three
    processes — ``sync-to-postgres.py``, ``sync-sessions-to-postgres.py``
    and ``sync-to-zotero.py`` — each do ``read → mutate → write`` on the
    one ``memories/sync-cursors.json``. An interleaving loses one
    process's update; a kill part-way through a non-atomic write truncates
    the file and resets *every* cursor at once.

    ``fcntl.flock`` is advisory: it only serialises callers that take the
    same lock. Linux-only, matching this project's infrastructure.
    """
    lock_path = cursor_path.with_name(cursor_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            # Closing the fd releases the lock; unlocking explicitly makes
            # the lifetime obvious to a reader.
            try:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            except OSError:  # pragma: no cover — fd is still open here
                pass


def read_cursor_file(cursor_path: Path) -> dict[str, Any]:
    """
    Return the cursor file's JSON object, or ``{}`` when unusable.

    A missing, unreadable, malformed, or non-object cursor file yields an
    empty dict so every caller falls back to its own hard-coded default
    rather than raising mid-sync.
    """
    if not cursor_path.exists():
        return {}
    try:
        data = json.loads(cursor_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, TypeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def read_cursor_file_locked(cursor_path: Path) -> dict[str, Any]:
    """
    Return the cursor object, read once under the exclusive lock.

    The compare-and-set needs two facts about the same instant — the
    position, and whether the key was there at all. Reading them with two
    unlocked calls leaves a window in which a rebuild can land between
    them, so the run could see a position and then conclude the key had
    always been absent, defeating the very check it was making (second
    re-audit, low finding L1).
    """
    with cursor_file_lock(cursor_path):
        return read_cursor_file(cursor_path)


def _write_cursor_file(cursor_path: Path, data: dict[str, Any]) -> None:
    """
    Write ``data`` over ``cursor_path`` atomically.

    Temp file in the same directory (so :func:`os.replace` stays within one
    filesystem and is therefore atomic), flushed and fsynced before the
    rename. A reader either sees the whole previous file or the whole new
    one; a kill mid-write can never leave a truncated cursor file behind.
    The temp name carries the pid so two processes cannot collide on it
    even if one of them skipped :func:`cursor_file_lock`.

    The parent directory is fsynced after the rename too (re-audit, low
    finding). Without it the rename itself can be lost to a power failure
    even though the file's own contents were durable, leaving the cursor
    at its pre-write value — the atomicity holds, but the durability the
    fsync above was for does not.
    """
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cursor_path.with_name(f"{cursor_path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, cursor_path)
        # Make the rename itself durable, not just the file's contents.
        dir_fd = os.open(str(cursor_path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        # Never leave a stray temp file behind on failure (including a
        # KeyboardInterrupt part-way through the write).
        tmp_path.unlink(missing_ok=True)
        raise


class CursorKeyVanished(RuntimeError):
    """
    A cursor key present when the run started was gone when it saved.

    The only thing that removes a key is ``rebuild-postgres.py``. If a sync
    read a position, then a rebuild truncated the tables and cleared the
    cursors, writing that position back would tell the next run that rows
    it just destroyed are already synced — they would never be replayed
    (re-audit finding M3). Callers report this and exit non-zero rather
    than writing.
    """


def apply_cursor_update(
    cursor_path: Path,
    updates: dict[str, Any] | None = None,
    *,
    delete_keys: tuple[str, ...] = (),
    expect_present: tuple[str, ...] = (),
) -> dict[str, Any]:
    """
    Read-modify-write the cursor file **without** taking the lock.

    For callers already inside :func:`cursor_file_lock`. ``flock`` is held
    per open file description, so a nested :func:`update_cursor_file` in the
    same process would block on itself forever.

    See :func:`update_cursor_file` for the parameters; the only difference
    is who holds the lock.

    Raises
    ------
    CursorKeyVanished
        If any key named in ``expect_present`` is absent from the file.
    """
    data = read_cursor_file(cursor_path)
    missing = [key for key in expect_present if key not in data]
    if missing:
        raise CursorKeyVanished(
            f"cursor key(s) {', '.join(sorted(missing))} were present when "
            f"this run started and are gone now — a rebuild reset "
            f"{cursor_path.name} mid-run"
        )
    if updates:
        data.update(updates)
    for key in delete_keys:
        data.pop(key, None)
    _write_cursor_file(cursor_path, data)
    return data


def update_cursor_file(
    cursor_path: Path,
    updates: dict[str, Any] | None = None,
    *,
    delete_keys: tuple[str, ...] = (),
    expect_present: tuple[str, ...] = (),
) -> dict[str, Any]:
    """
    Merge ``updates`` into the shared cursor file under an exclusive lock.

    The whole read-modify-write cycle happens inside
    :func:`cursor_file_lock`, and the write itself is atomic, so a
    concurrent sync can neither observe a half-written file nor silently
    drop the key this call is setting.

    Parameters
    ----------
    cursor_path:
        The shared cursor JSON file.
    updates:
        Keys to set. ``None`` is treated as ``{}`` (useful with
        ``delete_keys``).
    delete_keys:
        Keys to remove, applied after ``updates``.
    expect_present:
        Keys that must still be in the file. A compare-and-set against a
        concurrent rebuild: see :class:`CursorKeyVanished`.

    Returns
    -------
    dict[str, Any]
        The cursor object as written.

    Raises
    ------
    CursorKeyVanished
        If any key named in ``expect_present`` is absent.
    """
    with cursor_file_lock(cursor_path):
        return apply_cursor_update(
            cursor_path, updates,
            delete_keys=delete_keys, expect_present=expect_present,
        )


# ---------------------------------------------------------------------------
# JSONL shrink detection
# ---------------------------------------------------------------------------


def detect_jsonl_shrink(
    jsonl_path: Path,
    saved_cursor_line: int,
) -> tuple[bool, int]:
    """
    Detect whether ``jsonl_path`` is shorter than the saved cursor.

    The canonical JSONL files in this project are append-only by
    convention, but compaction passes (dedup-memories, tag-gardening),
    submodule reverts, or restoring a snapshot can cause the file to
    shrink. If that happens we must not let a cursor sit beyond EOF —
    every subsequent sync would be a no-op until the file grew past the
    pinned line, at which point earlier records would be skipped.

    Parameters
    ----------
    jsonl_path:
        Path to the canonical file.
    saved_cursor_line:
        The cursor value loaded from disk (line index, 0-based or
        1-past-the-end as the caller's convention dictates).

    Returns
    -------
    tuple[bool, int]
        ``(shrunk, current_line_count)``. ``shrunk`` is ``True`` when the
        file has fewer lines than ``saved_cursor_line``. The caller is
        expected to log a WARN, reset its cursor to ``0``, and force a
        full re-scan.
    """
    if not jsonl_path.exists():
        # Treating "file vanished" as a shrink: it is a strictly larger
        # disturbance than mere truncation, and the recovery is the same.
        return saved_cursor_line > 0, 0

    line_count = 0
    with jsonl_path.open("r", encoding="utf-8") as fh:
        for _ in fh:
            line_count += 1

    return saved_cursor_line > line_count, line_count
