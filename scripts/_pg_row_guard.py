#!/usr/bin/env python3
"""
Row-level guards shared by the two PostgreSQL sync scripts.

Background
----------
``sync-to-postgres.py`` (memories) and ``sync-sessions-to-postgres.py``
(session metadata) both advance a cursor through an append-only canonical
store, and both used to collapse two completely different failures into one
``db_available=False`` flag:

* **The database cannot be reached** — transient. Holding the cursor and
  retrying on the next cron tick is exactly right.
* **The database refused this row** — permanent, and caused by content. Every
  later invocation re-fails identically, the cursor never advances, and the
  operator is told "PostgreSQL may be down", which is false.

The audit's round-two finding P1 (lens A-C1) caught the second shape live: two
``session.meta.json`` files carried a NUL (``\\x00``) inside LLM-generated
narrative text, PostgreSQL rejects ``\\u0000`` inside ``jsonb``, and because
``execute_values`` runs the whole page in one transaction, those two rows took
48 healthy sessions down with them. The ``sessions`` table sat three weeks
stale with the wrong diagnosis in the log.

This module supplies the three pieces both scripts need to split the cases:

1. :func:`is_outage_error` — classify a psycopg2 exception.
2. :func:`insert_rows_individually` — after a failed batch, replay row by row
   so one poison row cannot halt the healthy remainder.
3. :func:`sanitise_nuls` — strip NUL at the ingest boundary, since neither
   ``text`` nor ``jsonb`` can hold one and the LLM text pipeline demonstrably
   emits them (lens A-X2).

The contract this restores is the one ``_sync_cursor.py`` already states:
every cursor advance is either a successful processing or an *explicit*
quarantine of the skipped record.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

#: psycopg2 exception classes that mean "we could not talk to the database".
#: ``OperationalError`` covers connection loss, authentication failure, and
#: server shutdown; ``InterfaceError`` covers use of a connection that has
#: already gone away. Everything else under ``psycopg2.Error`` — ``DataError``,
#: ``IntegrityError``, ``ProgrammingError``, ``InternalError`` — is the server
#: telling us something about *this row*.
OUTAGE_ERROR_NAMES: tuple[str, ...] = ("OperationalError", "InterfaceError")

#: The NUL code point. Legal in JSON (as the escape ``\u0000``) and in a
#: Python string, but rejected by PostgreSQL in both ``text`` and ``jsonb``.
NUL = "\x00"


def is_outage_error(exc: BaseException, psycopg2_module: Any) -> bool:
    """
    Return True when ``exc`` means the database was unreachable.

    Parameters
    ----------
    exc:
        The exception raised by a psycopg2 call.
    psycopg2_module:
        The imported ``psycopg2`` module. Passed in rather than imported here
        because both call sites import psycopg2 lazily (and the tests install
        a stand-in module in ``sys.modules``).

    Returns
    -------
    bool
        True for the connection-level errors listed in
        :data:`OUTAGE_ERROR_NAMES`; False for every content-caused error, and
        False for exceptions from outside psycopg2 (a ``ValueError`` from
        parameter adaptation, for instance, is a bad row, not an outage).

    Notes
    -----
    Missing attributes are tolerated so a partial stand-in module in a test
    cannot make the classifier throw; an unknown class simply is not an
    outage, which is the conservative reading — it sends the row to
    quarantine rather than silently holding the cursor forever.
    """
    for name in OUTAGE_ERROR_NAMES:
        error_class = getattr(psycopg2_module, name, None)
        if isinstance(error_class, type) and isinstance(exc, error_class):
            return True
    return False


def insert_rows_individually(
    conn: Any,
    sql: str,
    rows: Iterable[tuple],
    *,
    psycopg2_module: Any,
    execute_values: Callable[..., Any],
    logger: logging.Logger,
    id_of: Callable[[tuple], str] = lambda row: str(row[0]),
) -> tuple[set[str], list[tuple[str, str]], bool]:
    """
    Replay a failed batch one row at a time, isolating the poison rows.

    ``execute_values`` sends a whole page in a single statement inside a
    single transaction, so one row PostgreSQL refuses aborts every other row
    in that page. When the batch fails with a data error the caller falls back
    here: each row gets its own transaction, so the healthy rows land and only
    the genuinely bad ones are reported.

    Parameters
    ----------
    conn:
        An open psycopg2 connection. Used as a context manager per row, which
        commits on success and rolls back on failure — the rollback is what
        clears the aborted-transaction state so the *next* row can proceed.
    sql:
        The same INSERT/UPSERT statement the batch used (it must contain the
        ``VALUES %s`` placeholder ``execute_values`` expands, and should end
        with ``RETURNING id``).
    rows:
        The value tuples, in the same column order as the batch.
    psycopg2_module:
        The imported ``psycopg2`` module (for exception classes).
    execute_values:
        ``psycopg2.extras.execute_values``.
    logger:
        Logger for the per-row error lines.
    id_of:
        Extracts the row's identifier for reporting. Defaults to the first
        column, which is ``id`` in both sync scripts.

    Returns
    -------
    tuple[set[str], list[tuple[str, str]], bool]
        ``(returned_ids, poison, reachable)``:

        * ``returned_ids`` — ids PostgreSQL returned from ``RETURNING``.
        * ``poison`` — ``(row_id, error message)`` for every row the database
          refused. The caller quarantines these and advances past them.
        * ``reachable`` — False when the database went away part-way through
          the replay. The caller must then hold its cursor: the rows not yet
          attempted have neither landed nor been quarantined.
    """
    rows = list(rows)
    total_rows = len(rows)
    returned_ids: set[str] = set()
    poison: list[tuple[str, str]] = []

    for attempted, row in enumerate(rows, start=1):
        try:
            with conn:
                with conn.cursor() as cur:
                    got = execute_values(cur, sql, [row], page_size=1, fetch=True)
            returned_ids.update(str(item[0]) for item in (got or []))
        except (psycopg2_module.Error, ValueError, TypeError) as exc:
            if is_outage_error(exc, psycopg2_module):
                logger.warning(
                    "PostgreSQL became unreachable during the per-row "
                    "replay (%s) — stopping after %d of %d row(s); "
                    "cursor held.",
                    exc, attempted, total_rows,
                )
                return returned_ids, poison, False
            row_id = id_of(row)
            poison.append((row_id, str(exc).strip()))
            logger.error(
                "PostgreSQL refused row %s — quarantining it and continuing: "
                "%s", row_id, str(exc).strip(),
            )

    return returned_ids, poison, True


def sanitise_nuls(value: Any) -> tuple[Any, int]:
    """
    Recursively strip NUL characters from every string in a JSON-shaped value.

    PostgreSQL accepts a NUL in neither ``text`` (``ValueError: A string
    literal cannot contain NUL (0x00) characters``, raised by psycopg2 before
    the statement is even sent) nor ``jsonb`` (``unsupported Unicode escape
    sequence … \\u0000 cannot be converted to text``). The canonical stores
    are JSONL, which *can* hold one, and the LLM text pipeline demonstrably
    produces them — so the sanitising has to happen at the ingest boundary of
    each sync rather than at the individual column that happened to fail
    first (lens A-X2).

    Removal, not replacement: a NUL in generated prose is an encoding
    artefact with no meaning to preserve, and substituting a visible sentinel
    would change text that operators read and search.

    Parameters
    ----------
    value:
        Any JSON-shaped value — dict, list, str, or scalar. Dict keys are
        sanitised too, since a NUL in a key breaks ``jsonb`` just as surely.

    Returns
    -------
    tuple[Any, int]
        The cleaned value and the number of NUL characters removed. The
        caller logs a warning when the count is non-zero: silent repair of
        canonical content is exactly the sort of thing an operator should be
        able to see in the log.
    """
    if isinstance(value, str):
        if NUL not in value:
            return value, 0
        return value.replace(NUL, ""), value.count(NUL)

    if isinstance(value, dict):
        cleaned_dict: dict[Any, Any] = {}
        removed = 0
        for key, item in value.items():
            new_key, key_removed = sanitise_nuls(key)
            new_item, item_removed = sanitise_nuls(item)
            cleaned_dict[new_key] = new_item
            removed += key_removed + item_removed
        return cleaned_dict, removed

    if isinstance(value, list):
        cleaned_list = []
        removed = 0
        for item in value:
            new_item, item_removed = sanitise_nuls(item)
            cleaned_list.append(new_item)
            removed += item_removed
        return cleaned_list, removed

    # Numbers, booleans, None: no strings to clean.
    return value, 0
