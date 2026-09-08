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

The re-audit of that fix found a third case hiding inside the second, and
the split is now three-way (finding C1). ``ProgrammingError`` and
``InternalError`` are *not* about the row: a REVOKE, a half-applied
migration, or an already-aborted transaction refuses every row alike. Left
in the "refused row" class they would quarantine an entire cursor window
and advance past it. They belong with the outage: hold the cursor,
quarantine nothing — but exit non-zero, because unlike an outage no amount
of retrying will fix them.

This module supplies the four pieces both scripts need:

1. :func:`classify_pg_error` — sort an exception into outage, environment
   fault, or refused row (:func:`is_outage_error` remains for callers that
   only need the first question answered).
2. :func:`insert_rows_individually` — after a failed batch, replay row by row
   so one poison row cannot halt the healthy remainder, stopping instead of
   quarantining when the evidence says the fault is not in the data.
3. :func:`sanitise_nuls` — strip NUL at the ingest boundary, since neither
   ``text`` nor ``jsonb`` can hold one and the LLM text pipeline demonstrably
   emits them (lens A-X2).
4. :class:`EnvironmentFault` — what a caller raises so its ``main`` can exit
   non-zero rather than reporting success over a database it never wrote to.

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
#: already gone away. Transient: hold the cursor and retry next tick.
OUTAGE_ERROR_NAMES: tuple[str, ...] = ("OperationalError", "InterfaceError")

#: psycopg2 exception classes that mean "the database is not in the state
#: this script was written for". Verified against psycopg2 2.9.12:
#: ``InsufficientPrivilege`` (a REVOKE), ``UndefinedTable`` and
#: ``UndefinedColumn`` (a half-applied migration or a restore) are all
#: ``ProgrammingError``; ``InFailedSqlTransaction`` is ``InternalError``.
#:
#: These look identical to a refused row — every row fails — but nothing is
#: wrong with the data. Quarantining the slice and advancing would empty a
#: whole cursor window into a quarantine file (42k rows after a cursor
#: reset) and exit 0 into a log nobody reads. Hold the cursor, quarantine
#: nothing, and exit non-zero so the operator is told (audit round two
#: re-audit, finding C1).
ENVIRONMENT_ERROR_NAMES: tuple[str, ...] = (
    "ProgrammingError", "InternalError", "NotSupportedError",
)

#: Outcome of :func:`classify_pg_error`.
OUTAGE = "outage"
ENVIRONMENT = "environment"
ROW = "row"

#: Most rows a single run may quarantine before it stops and reports
#: instead. A handful of poison rows is a data problem; hundreds is a
#: symptom of something systemic that quarantining would merely hide,
#: and every quarantined row is one the cursor then skips.
DEFAULT_QUARANTINE_CAP = 200

#: Fewest rows in a replay before "every row failed identically" counts as
#: evidence of an environment fault rather than of bad data. One refusal is
#: no evidence at all — and a lone poison row is exactly what the per-row
#: replay exists to isolate.
MIN_ROWS_FOR_ALL_ALIKE = 2


class EnvironmentFault(RuntimeError):
    """
    The database refused work for a reason that is not about the data.

    Raised or reported so the caller holds its cursor, quarantines
    nothing, and exits non-zero. Distinct from an outage only in that
    retrying will not help until a human changes something.
    """

#: The NUL code point. Legal in JSON (as the escape ``\u0000``) and in a
#: Python string, but rejected by PostgreSQL in both ``text`` and ``jsonb``.
NUL = "\x00"


def _matches_any(exc: BaseException, psycopg2_module: Any,
                 names: tuple[str, ...]) -> bool:
    """Return True when ``exc`` is an instance of any named psycopg2 class.

    Missing attributes are tolerated so a partial stand-in module in a test
    cannot make the classifier throw.
    """
    for name in names:
        error_class = getattr(psycopg2_module, name, None)
        if isinstance(error_class, type) and isinstance(exc, error_class):
            return True
    return False


def classify_pg_error(exc: BaseException, psycopg2_module: Any) -> str:
    """
    Sort a database exception into one of three response classes.

    Parameters
    ----------
    exc:
        The exception raised by a psycopg2 call.
    psycopg2_module:
        The imported ``psycopg2`` module. Passed in rather than imported
        here because both call sites import psycopg2 lazily (and the tests
        install a stand-in module in ``sys.modules``).

    Returns
    -------
    str
        * :data:`OUTAGE` — the database is unreachable. Hold the cursor,
          quarantine nothing, retry on the next tick.
        * :data:`ENVIRONMENT` — the database is reachable but not in the
          expected state (permissions revoked, a table or column missing,
          a transaction already aborted). Recognised by class *and* by
          carrying a server SQLSTATE. Hold the cursor, quarantine
          nothing, and report non-zero: retrying will not help, and
          quarantining would discard good data to no purpose.
        * :data:`ROW` — the database refused *this row's content*
          (``DataError``, ``IntegrityError``, or an adaptation
          ``ValueError``/``TypeError``). Quarantine it and move on.

    The three-way split replaces an earlier two-way one that put
    ``ProgrammingError`` and ``InternalError`` in the ``ROW`` class. That
    was a regression on the pre-branch behaviour: a REVOKE or a
    half-applied migration refuses every row, so the whole slice was
    quarantined, the cursor advanced past it, and the process exited 0.
    """
    if _matches_any(exc, psycopg2_module, OUTAGE_ERROR_NAMES):
        return OUTAGE
    if _matches_any(exc, psycopg2_module, ENVIRONMENT_ERROR_NAMES):
        # One qualification, and it matters: psycopg2 also raises
        # ``ProgrammingError`` *client-side* when it cannot adapt a Python
        # value ("can't adapt type 'dict'"), which is as row-specific as an
        # error gets. Server-side errors carry the SQLSTATE PostgreSQL sent
        # (``pgcode``); a client-side adaptation failure has none. Use that
        # to tell them apart, and let the all-alike rule in
        # :func:`insert_rows_individually` catch anything this misjudges.
        if getattr(exc, "pgcode", None):
            return ENVIRONMENT
        return ROW
    return ROW


def is_outage_error(exc: BaseException, psycopg2_module: Any) -> bool:
    """
    Return True when ``exc`` means the database was unreachable.

    Thin wrapper over :func:`classify_pg_error` for callers that only need
    the "retry later" question answered.
    """
    return classify_pg_error(exc, psycopg2_module) == OUTAGE


def _error_signature(exc: BaseException) -> str:
    """
    Return a coarse identity for an error, for the all-rows-alike check.

    Prefers the SQLSTATE (``pgcode``) that PostgreSQL attaches to every
    server-side error, because two rows failing with 22P02 are the same
    fault; falls back to the exception class name for adaptation errors
    raised client-side, which carry no SQLSTATE.
    """
    pgcode = getattr(exc, "pgcode", None)
    if isinstance(pgcode, str) and pgcode:
        return f"sqlstate:{pgcode}"
    return f"class:{type(exc).__name__}"


def insert_rows_individually(
    conn: Any,
    sql: str,
    rows: Iterable[tuple],
    *,
    psycopg2_module: Any,
    execute_values: Callable[..., Any],
    logger: logging.Logger,
    id_of: Callable[[tuple], str] = lambda row: str(row[0]),
    quarantine_cap: int = DEFAULT_QUARANTINE_CAP,
) -> tuple[set[str], list[tuple[str, str]], str]:
    """
    Replay a failed batch one row at a time, isolating the poison rows.

    ``execute_values`` sends a whole page in a single statement inside a
    single transaction, so one row PostgreSQL refuses aborts every other row
    in that page. When the batch fails with a row error the caller falls back
    here: each row gets its own transaction, so the healthy rows land and only
    the genuinely bad ones are reported.

    Precondition
    ------------
    The connection must not be left inside an aborted transaction. Callers
    reach this function from an ``except`` around ``with conn:``, which has
    already rolled back — but a caller that does not use the connection as a
    context manager would otherwise have every statement here fail with
    ``InFailedSqlTransaction`` and the FIRST GOOD ROW would be quarantined.
    Rather than trust the precondition, this function rolls back first
    (re-audit finding M1); on a healthy connection that is a no-op.

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
    quarantine_cap:
        Stop and report an environment fault once this many rows have been
        refused. A handful of poison rows is a data problem; hundreds is a
        symptom, and each quarantined row is one the cursor skips.

    Returns
    -------
    tuple[set[str], list[tuple[str, str]], str]
        ``(returned_ids, poison, status)``:

        * ``returned_ids`` — ids PostgreSQL returned from ``RETURNING``.
        * ``poison`` — ``(row_id, error message)`` for every row the database
          refused on content grounds. Meaningful only when ``status`` is
          :data:`ROW`; the caller quarantines these and advances past them.
        * ``status`` — :data:`ROW` when the replay completed and any failures
          were genuinely per-row; :data:`OUTAGE` when the database went away
          part-way through; :data:`ENVIRONMENT` when the failures are not
          about the data. In the latter two cases the caller must hold its
          cursor and quarantine nothing: rows not yet attempted have neither
          landed nor been quarantined.

    A replay in which *no* row succeeded and every one of two or more rows
    was refused with the same error signature (SQLSTATE, or exception class
    for client-side adaptation errors) is reported as :data:`ENVIRONMENT`
    even when the class says ``DataError``. Data poison is sporadic; "all
    of them, identically, and not one success" is a fault in the database
    or the schema, and quarantining a whole cursor window on that evidence
    destroys more than it saves.

    Two deliberate limits on that rule. A single refused row is left in the
    :data:`ROW` class: with one row there is no "all alike" evidence, and a
    lone poison record is the case this whole replay exists to handle. And
    any success in the same replay proves the environment is healthy, so
    the remaining failures are per-row by demonstration. The cost of the
    rule is a false hold when a small slice happens to be uniformly bad —
    recoverable, because the run now exits non-zero and says so, where the
    opposite mistake silently skips data.
    """
    # M1: never replay from inside an aborted transaction. Harmless on a
    # healthy connection; on an aborted one it is the difference between
    # isolating the poison row and quarantining the first good one.
    try:
        conn.rollback()
    except psycopg2_module.Error:
        pass

    rows = list(rows)
    total_rows = len(rows)
    returned_ids: set[str] = set()
    poison: list[tuple[str, str]] = []
    signatures: set[str] = set()

    for attempted, row in enumerate(rows, start=1):
        try:
            with conn:
                with conn.cursor() as cur:
                    got = execute_values(cur, sql, [row], page_size=1, fetch=True)
            returned_ids.update(str(item[0]) for item in (got or []))
        except (psycopg2_module.Error, ValueError, TypeError) as exc:
            verdict = classify_pg_error(exc, psycopg2_module)
            if verdict == OUTAGE:
                logger.warning(
                    "PostgreSQL became unreachable during the per-row "
                    "replay (%s) — stopping after %d of %d row(s); "
                    "cursor held.",
                    exc, attempted, total_rows,
                )
                return returned_ids, [], OUTAGE
            if verdict == ENVIRONMENT:
                logger.error(
                    "PostgreSQL refused row %s for a reason that is not "
                    "about the data (%s: %s) — this is an environment "
                    "fault (permissions, a missing table or column, an "
                    "aborted transaction). Holding the cursor and "
                    "quarantining nothing.",
                    id_of(row), type(exc).__name__, str(exc).strip(),
                )
                return returned_ids, [], ENVIRONMENT

            row_id = id_of(row)
            poison.append((row_id, str(exc).strip()))
            signatures.add(_error_signature(exc))
            logger.error(
                "PostgreSQL refused row %s — quarantining it and continuing: "
                "%s", row_id, str(exc).strip(),
            )

            if len(poison) > quarantine_cap:
                logger.error(
                    "More than %d row(s) refused in one run — stopping. "
                    "That many at once is a symptom, not a data problem, "
                    "and quarantining them would advance the cursor past "
                    "every one. Holding the cursor and quarantining "
                    "nothing.",
                    quarantine_cap,
                )
                return returned_ids, [], ENVIRONMENT

    # Every row refused, none succeeded, all alike: a fault in the database
    # or schema wearing a row error's clothes. Needs at least two rows —
    # see the note in the docstring on why a single refusal stays a row
    # fault — and no successes, since one success proves the environment is
    # fine and makes the remaining failures per-row by demonstration.
    if (total_rows >= MIN_ROWS_FOR_ALL_ALIKE
            and not returned_ids
            and len(poison) == total_rows
            and len(signatures) == 1):
        logger.error(
            "Every one of the %d row(s) was refused with the same error "
            "(%s) and not one succeeded — that is an environment fault, "
            "not %d independently bad rows. Holding the cursor and "
            "quarantining nothing.",
            total_rows, next(iter(signatures)), total_rows,
        )
        return returned_ids, [], ENVIRONMENT

    return returned_ids, poison, ROW


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
