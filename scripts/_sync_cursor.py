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

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


def _iso_now() -> str:
    """Return an ISO 8601 UTC timestamp for quarantine entries."""
    return datetime.now(timezone.utc).isoformat()


def quarantine_record(
    quarantine_path: Path,
    record: Any,
    reason: str,
    *,
    logger: logging.Logger | None = None,
) -> bool:
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

    Returns
    -------
    bool
        ``True`` on successful write; ``False`` if the underlying I/O
        operation raised. The caller can use the return to decide
        whether to advance the cursor anyway (poison-record case) or
        halt and retry next cycle.
    """
    entry = {
        "reason": reason,
        "quarantined_at": _iso_now(),
        "record": record,
    }
    try:
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        with quarantine_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError) as exc:
        if logger is not None:
            logger.error(
                "Could not write quarantine entry to %s (reason=%r): %s",
                quarantine_path, reason, exc,
            )
        return False

    if logger is not None:
        logger.info(
            "Quarantined record (reason=%r) to %s",
            reason, quarantine_path,
        )
    return True


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
