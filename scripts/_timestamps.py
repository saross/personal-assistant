#!/usr/bin/env python3
"""
Shared timestamp helpers for memory writers.

Why
---
The schema for ``memories.created_at`` is ``TIMESTAMPTZ NOT NULL``
(``scripts/schema.sql``). The live extraction hook writes a full ISO-8601
string with microseconds and a UTC offset (e.g.
``2026-05-02T15:23:14.123456+00:00``). Until this batch,
``scripts/reprocess-sessions.py`` truncated to the date-only form
``YYYY-MM-DD``. Date-only strings parse to a naive midnight, sort to
the bottom of session-start retrieval, and lose the time-of-day signal
the rest of the system relies on.

The fix is to enforce a single canonical format at the writer side.
Any writer that emits a ``created_at`` for a memory record MUST use
``now_iso`` or ``coerce_to_iso`` from this module.

Audit refs
----------
* ``reports/audit-2026-05-02/SUMMARY.md`` — IC4, A-Medium #6, A-CF4,
  C-M6.
* ``reports/audit-2026-05-02/cluster-A-memory-pipeline.md`` — Medium #6
  narrative.

Receiver-side defence
---------------------
``hooks/session-start-retrieval.py`` substitutes ``datetime.min`` when
parsing fails. After this batch the substitution should be unreachable
on freshly-emitted records, but the defence-in-depth is left in place
to cover legacy records still on disk.
"""

from datetime import datetime, timezone


def now_iso() -> str:
    """Return the current UTC time in the canonical ISO-8601 format.

    Identical shape to ``datetime.now(timezone.utc).isoformat()`` —
    the function exists so both writers reference the same source of
    truth even if the format ever changes.
    """
    return datetime.now(timezone.utc).isoformat()


def coerce_to_iso(value: str | None, fallback: str | None = None) -> str:
    """Coerce *value* to a full ISO-8601 timestamp.

    The reprocess-sessions writer reads ``started_at`` from
    ``session.meta.json``. The archiver writes a full ISO timestamp
    there, but historical files (or files from other tooling) may
    contain a date-only ``YYYY-MM-DD`` string. This helper preserves
    the original instant when it is already a full ISO timestamp,
    upgrades a date-only string to ``T00:00:00+00:00``, and falls back
    to *fallback* (or ``now_iso()``) when *value* is empty.

    The returned string is always parseable by
    ``datetime.fromisoformat``.

    Parameters
    ----------
    value
        The candidate timestamp string. May be ``None``, empty, a full
        ISO-8601 string, or a date-only ``YYYY-MM-DD`` string.
    fallback
        Used when *value* is missing or unparseable. ``None`` means
        "use the current UTC time".

    Returns
    -------
    str
        A canonical ISO-8601 timestamp with timezone offset.
    """
    if value:
        # Try a full parse first — handles every shape
        # ``datetime.fromisoformat`` accepts (with ``Z`` normalised).
        candidate = value.replace("Z", "+00:00") if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            parsed = None
        if parsed is not None:
            # Tz-naive → assume UTC (the historical behaviour for
            # date-only strings the audit found).
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.isoformat()
    if fallback is not None:
        return fallback
    return now_iso()
