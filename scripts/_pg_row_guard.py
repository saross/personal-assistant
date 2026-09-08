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
the split is now three-way (finding C1). A REVOKE, a half-applied
migration, an already-aborted transaction, or a full disk refuses every row
alike. Left in the "refused row" class they would quarantine an entire
cursor window and advance past it. They belong with the outage: hold the
cursor, quarantine nothing — but exit non-zero, because unlike an outage no
amount of retrying will fix them.

The second re-audit then found that the *exception class* is the wrong
discriminator. ``ProgrammingError`` covers both a REVOKE and a client-side
"can't adapt type 'dict'"; ``OperationalError`` covers both a closed socket
and a full disk. Classification is now by SQLSTATE class — the identifier
PostgreSQL's own error documentation is organised around — with the Python
class consulted only when there is no SQLSTATE at all, which means psycopg2
raised the error before the server ever saw it.

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
import os
from typing import Any, Callable, Iterable

#: psycopg2 exception classes that mean "we could not reach the database" —
#: but only when they carry NO SQLSTATE. A server that answers well enough to
#: send back an error code is, by definition, reachable: psycopg2 raises
#: ``OperationalError`` for DiskFull (53100), LockNotAvailable (55P03), and
#: QueryCanceled (57014) among others, and routing those to "outage, retry,
#: exit 0" hid a full disk behind a message about PostgreSQL possibly being
#: stopped (second re-audit, finding M5).
CONNECTION_ERROR_NAMES: tuple[str, ...] = ("OperationalError", "InterfaceError")

#: Exception classes psycopg2 raises *client-side*, with no SQLSTATE, when a
#: value cannot be adapted — "can't adapt type 'dict'", a NUL in a text
#: parameter. As row-specific as an error gets.
CLIENT_SIDE_ROW_ERROR_NAMES: tuple[str, ...] = (
    "ProgrammingError", "DataError", "IntegrityError",
)

#: SQLSTATE class 08 — connection exception. The one server-reported family
#: that is genuinely an outage.
OUTAGE_SQLSTATE_CLASSES: frozenset[str] = frozenset({"08"})

#: SQLSTATE classes that describe *this row's content*, and nothing else:
#:
#: * ``21`` cardinality violation
#: * ``22`` data exception — bad timestamp, value too long, and 22P05
#:   ``untranslatable_character``, which is what a NUL in jsonb raises
#: * ``23`` integrity constraint violation — NOT NULL, unique, foreign key
#:
#: Quarantine these and move on: the next row may well be fine, and retrying
#: this one for ever cannot help.
ROW_SQLSTATE_CLASSES: frozenset[str] = frozenset({"21", "22", "23"})

#: Everything else the server can report is an environment fault: the
#: database is reachable and answering, but is not in the state this script
#: was written for, and no row is to blame. Classified by exclusion rather
#: than by list so a SQLSTATE nobody anticipated defaults to "hold the cursor
#: and tell someone" rather than "quarantine the data and carry on" — the
#: safe direction, because a wrongly held cursor is recoverable and wrongly
#: skipped data is not.
#:
#: Named for the reader, all confirmed against psycopg2 2.9.12:
#:   ``0A`` feature not supported          ``42`` syntax error / access rule
#:   ``25`` invalid transaction state      ``53`` insufficient resources
#:   ``3D``/``3F`` invalid catalog/schema  ``54`` program limit exceeded
#:   ``55`` object not in prerequisite state
#:   ``57`` operator intervention (57014 QueryCanceled, 57P01 admin shutdown)
#:   ``58`` system error                   ``XX`` internal error
#:
#: Note ``40`` (transaction rollback: deadlock, serialisation failure) also
#: lands here. Retrying would in principle succeed, so an outage-style silent
#: retry would be defensible — but both syncs already serialise themselves
#: with a PostgreSQL advisory lock, so a deadlock here means something
#: unexpected is writing to these tables, which is exactly worth surfacing.
ENVIRONMENT_SQLSTATE_CLASSES_DOCUMENTED: tuple[str, ...] = (
    "0A", "25", "3D", "3F", "42", "53", "54", "55", "57", "58", "XX",
)

#: SQLSTATE classes that are environment faults but *transient* ones: a
#: deadlock or serialisation failure (40), a cancelled query or an
#: operator intervention (57). The cursor is still held and the gate still
#: raised — something unexpected is happening to these tables — but the
#: remedy is "wait for the next tick", not "fix your grants" (third
#: re-audit, finding M4).
TRANSIENT_SQLSTATE_CLASSES: frozenset[str] = frozenset({"40", "57"})

#: Outcome of :func:`classify_pg_error` and of the per-row replay.
OUTAGE = "outage"
ENVIRONMENT = "environment"
ROW = "row"
#: The replay refused more rows than the cap allows. Its own outcome, not
#: an environment fault: the database is fine and the rows may genuinely
#: be poison — there are simply too many to skip silently (finding M2).
CAP_EXCEEDED = "cap_exceeded"
#: A whole batch refused with one SQLSTATE and not a single success.
#: Correlated poison, or a schema fault the row errors are a symptom of
#: (finding C3).
CORRELATED = "correlated"

#: How many rows must fail alike before the run stops rather than
#: quarantining them. Below this, correlated poison is ordinary — two
#: archived sessions from one LLM run both carrying a NUL — and must
#: still be quarantined so the cursor can advance. At or above it, a
#: migration that added a NOT NULL column looks exactly the same, and
#: quarantining 200 rows a tick is round one's data loss through a
#: different door.
MIN_ROWS_FOR_CORRELATED = 5

#: Environment variable forcing the per-row path for one run, overriding
#: the correlated-refusal hold.
QUARANTINE_ANYWAY_ENV_VAR = "PA_PG_QUARANTINE_ANYWAY"

#: Most rows a single run may quarantine before it stops and reports
#: instead. A handful of poison rows is a data problem; hundreds is a
#: symptom of something systemic that quarantining would merely hide,
#: and every quarantined row is one the cursor then skips. Override with
#: ``PA_PG_QUARANTINE_CAP`` or ``--quarantine-cap``.
DEFAULT_QUARANTINE_CAP = 200

#: Environment variable overriding :data:`DEFAULT_QUARANTINE_CAP`.
QUARANTINE_CAP_ENV_VAR = "PA_PG_QUARANTINE_CAP"


class EnvironmentFault(RuntimeError):
    """
    The database refused work for a reason that is not about the data.

    Raised or reported so the caller holds its cursor, quarantines
    nothing, and exits non-zero. Distinct from an outage only in that
    retrying will not help until a human changes something.
    """


class QuarantineCapExceeded(EnvironmentFault):
    """
    More rows were refused in one run than the cap allows.

    A subclass so existing handlers still catch it, but a distinct type so
    the caller can say something true: the database is not broken and the
    rows may really be poison — there are just too many to skip without
    someone looking (finding M2).
    """


class CorrelatedRefusal(EnvironmentFault):
    """
    A whole batch refused with one SQLSTATE and not one success.

    Ambiguous by nature: either correlated poison (one buggy extraction
    run) or a schema fault the row errors are a symptom of (a migration
    adding a NOT NULL column, a unique index ``ON CONFLICT`` does not
    name). Quarantining the batch would be right in the first case and
    catastrophic in the second, so the run stops and asks (finding C3).
    """


#: The NUL code point. Legal in JSON (as the escape ``\u0000``) and in a
#: Python string, but rejected by PostgreSQL in both ``text`` and ``jsonb``.
NUL = "\x00"


def resolve_quarantine_cap(
    explicit: int | None = None,
    *,
    logger: logging.Logger | None = None,
) -> int:
    """
    Return the per-run quarantine cap, honouring the override chain.

    Precedence: an explicit value (the ``--quarantine-cap`` flag) beats
    the ``PA_PG_QUARANTINE_CAP`` environment variable, which beats
    :data:`DEFAULT_QUARANTINE_CAP`. A non-numeric or negative value is
    reported and ignored rather than silently disabling the cap — from
    either source, identically: ``max(0, explicit)`` quietly turned
    ``--quarantine-cap -1`` into "stop at the first refusal", which is
    not what anyone typing a negative number meant (third re-audit).

    Zero is accepted and means "quarantine nothing": every refused row
    becomes an environment fault. Useful for an operator who wants the
    run to stop at the first refusal.
    """
    if explicit is not None:
        if explicit < 0:
            if logger is not None:
                logger.warning(
                    "Ignoring --quarantine-cap=%d — negative; using the "
                    "default of %d.", explicit, DEFAULT_QUARANTINE_CAP,
                )
            return DEFAULT_QUARANTINE_CAP
        return explicit

    raw = os.environ.get(QUARANTINE_CAP_ENV_VAR)
    if raw is None or not raw.strip():
        return DEFAULT_QUARANTINE_CAP
    try:
        value = int(raw)
    except ValueError:
        if logger is not None:
            logger.warning(
                "Ignoring %s=%r — not an integer; using the default of %d.",
                QUARANTINE_CAP_ENV_VAR, raw, DEFAULT_QUARANTINE_CAP,
            )
        return DEFAULT_QUARANTINE_CAP
    if value < 0:
        if logger is not None:
            logger.warning(
                "Ignoring %s=%r — negative; using the default of %d.",
                QUARANTINE_CAP_ENV_VAR, raw, DEFAULT_QUARANTINE_CAP,
            )
        return DEFAULT_QUARANTINE_CAP
    return value


#: Sentinel for a ``pgcode`` that is present but not a SQLSTATE — an
#: empty string, a truncated one, bytes, an int. Distinct from ``None``
#: (no SQLSTATE at all, i.e. client-side) because the two must be
#: classified differently: unrecognisable metadata is not evidence that
#: the row is at fault (third re-audit, finding M3).
MALFORMED_SQLSTATE = "??"


def resolve_quarantine_anyway(
    explicit: bool = False,
    *,
    logger: logging.Logger | None = None,
) -> bool:
    """
    Should a correlated batch refusal be quarantined rather than held?

    The escape hatch for :class:`CorrelatedRefusal` (finding C3): when the
    operator has looked and decided the batch really is poison, one run
    with ``--quarantine-anyway`` or ``PA_PG_QUARANTINE_ANYWAY=1`` forces
    the per-row path. Deliberately per-run and not persisted: a permanent
    setting would restore exactly the silent behaviour the hold exists to
    prevent.
    """
    if explicit:
        return True
    raw = os.environ.get(QUARANTINE_ANYWAY_ENV_VAR, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        if logger is not None:
            logger.warning(
                "%s is set — a correlated batch refusal will be "
                "quarantined rather than held. This run only.",
                QUARANTINE_ANYWAY_ENV_VAR,
            )
        return True
    return False


def sqlstate_class(exc: BaseException) -> str | None:
    """
    Return the two-character SQLSTATE class of ``exc``.

    Returns
    -------
    str | None
        * ``None`` — no ``pgcode`` at all. The signature of a client-side
          failure: psycopg2 raised it without ever reaching the server.
        * :data:`MALFORMED_SQLSTATE` — a ``pgcode`` that is not a
          five-character string. SQLSTATE is defined as exactly five
          characters; anything else is metadata this code does not
          understand, and guessing from a prefix would be worse than
          admitting so.
        * Otherwise the upper-cased first two characters.
    """
    pgcode = getattr(exc, "pgcode", None)
    if pgcode is None:
        return None
    if isinstance(pgcode, str) and len(pgcode) == 5:
        return pgcode[:2].upper()
    return MALFORMED_SQLSTATE


def environment_remedy(state_class: str | None) -> str:
    """
    Return the one-line remedy for an environment fault of this class.

    A deadlock or a cancelled query is not fixed by adjusting grants, and
    telling an operator to do that at 2 a.m. wastes the one thing the gate
    was built to buy — attention (finding M4).
    """
    if state_class in TRANSIENT_SQLSTATE_CLASSES:
        return (
            "This looks transient (a deadlock, a serialisation failure, a "
            "cancelled query, or an operator intervention): the next run "
            "retries automatically and no action is needed unless it "
            "persists. If it does, look for another writer to these "
            "tables or an administrative action on the server."
        )
    return (
        "Fix the database (grants, schema, migration state) and re-run."
    )


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

    The verdict comes from the SQLSTATE the server sent, not from the
    Python exception class. That is the second re-audit's finding C1: the
    class is far too coarse. ``ProgrammingError`` covers both a REVOKE and
    a client-side "can't adapt type 'dict'"; ``OperationalError`` covers
    both a closed socket and a full disk. The SQLSTATE separates them
    exactly, and it is the identifier PostgreSQL's own documentation is
    organised around.

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
        * :data:`OUTAGE` — SQLSTATE class 08, or a connection-level
          exception with no SQLSTATE at all. Hold the cursor, quarantine
          nothing, retry on the next tick, exit 0.
        * :data:`ROW` — SQLSTATE classes 21, 22, or 23; or a client-side
          adaptation failure (``ValueError``, ``TypeError``, or a psycopg2
          error with no SQLSTATE). This row's content is wrong.
          Quarantine it and carry on.
        * :data:`ENVIRONMENT` — every other server-reported SQLSTATE.
          Reachable but not in the expected state. Hold the cursor,
          quarantine nothing, report non-zero.

    An earlier version of this branch also treated "every row in the batch
    failed identically" as an environment fault. That rule was withdrawn:
    correlated poison is ordinary here — two archived sessions from the
    same LLM run both carrying a NUL, two records from one buggy
    extraction sharing 23502 — and the rule turned exactly the situation
    this branch exists to fix into a permanent stall with no escape.
    """
    state_class = sqlstate_class(exc)

    if state_class is not None:
        # Server-reported: the SQLSTATE decides, with no appeal to the
        # Python class. A pgcode we cannot parse falls through to
        # ENVIRONMENT with everything else — the safe direction, since
        # unrecognisable metadata is not evidence the row is at fault.
        if state_class in OUTAGE_SQLSTATE_CLASSES:
            return OUTAGE
        if state_class in ROW_SQLSTATE_CLASSES:
            return ROW
        return ENVIRONMENT

    # No SQLSTATE: psycopg2 raised this before the server saw it.
    if _matches_any(exc, psycopg2_module, CONNECTION_ERROR_NAMES):
        return OUTAGE
    if isinstance(exc, (ValueError, TypeError)):
        return ROW
    if _matches_any(exc, psycopg2_module, CLIENT_SIDE_ROW_ERROR_NAMES):
        return ROW
    return ENVIRONMENT


def is_outage_error(exc: BaseException, psycopg2_module: Any) -> bool:
    """
    Return True when ``exc`` means the database was unreachable.

    Thin wrapper over :func:`classify_pg_error` for callers that only need
    the "retry later" question answered. Note that this is now False for a
    full disk or a cancelled query, which psycopg2 also reports as
    ``OperationalError`` — see :data:`CONNECTION_ERROR_NAMES`.
    """
    return classify_pg_error(exc, psycopg2_module) == OUTAGE


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
    quarantine_anyway: bool = False,
) -> tuple[set[str], list[tuple[str, str]], str, str]:
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
        Stop and report once this many rows have been refused. A handful
        of poison rows is a data problem; hundreds is a symptom, and each
        quarantined row is one the cursor skips. Resolve it with
        :func:`resolve_quarantine_cap` so ``PA_PG_QUARANTINE_CAP`` and
        ``--quarantine-cap`` are honoured.
    quarantine_anyway:
        Skip the correlated-refusal hold for this run, quarantining the
        batch instead. The operator's escape hatch once they have looked —
        see :func:`resolve_quarantine_anyway`.

    Returns
    -------
    tuple[set[str], list[tuple[str, str]], str, str]
        ``(returned_ids, poison, status, detail)``:

        * ``returned_ids`` — ids PostgreSQL returned from ``RETURNING``.
        * ``poison`` — ``(row_id, error message)`` for every row the
          database refused on content grounds. Meaningful only when
          ``status`` is :data:`ROW`; the caller quarantines these and
          advances past them.
        * ``status`` — :data:`ROW`, :data:`OUTAGE`, :data:`ENVIRONMENT`,
          :data:`CAP_EXCEEDED`, or :data:`CORRELATED`. Only :data:`ROW`
          lets the caller advance; every other outcome means hold the
          cursor and quarantine nothing, because rows not yet attempted
          have neither landed nor been quarantined.
        * ``detail`` — a short machine-ish token for the caller's message
          and gate text: the SQLSTATE for :data:`CORRELATED`, the cap for
          :data:`CAP_EXCEEDED`, the SQLSTATE class otherwise.

    Each refusal is judged on its own SQLSTATE. Count matters in exactly
    one way, and only above a threshold: when at least
    :data:`MIN_ROWS_FOR_CORRELATED` rows all fail with the SAME SQLSTATE
    and not one succeeds, the replay stops rather than quarantining, since
    a migration that added a NOT NULL column is indistinguishable from
    correlated poison at that point and quarantining would be data loss.
    Below the threshold — two sessions from one LLM run both carrying a
    NUL — the rows are quarantined and the cursor advances, which is the
    case this replay exists for.
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
                _log_landed_rows(returned_ids, logger)
                return returned_ids, [], OUTAGE, "08"
            if verdict == ENVIRONMENT:
                logger.error(
                    "PostgreSQL refused row %s for a reason that is not "
                    "about the data (%s, SQLSTATE %s: %s) — environment "
                    "fault. Holding the cursor and quarantining nothing.",
                    id_of(row), type(exc).__name__,
                    sqlstate_class(exc) or "none", str(exc).strip(),
                )
                _log_landed_rows(returned_ids, logger)
                return (
                    returned_ids, [], ENVIRONMENT,
                    sqlstate_class(exc) or "none",
                )

            row_id = id_of(row)
            poison.append((row_id, str(exc).strip()))
            signatures.add(getattr(exc, "pgcode", None) or type(exc).__name__)
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
                    "nothing. Raise the ceiling with %s or "
                    "--quarantine-cap if this is genuinely a bad batch.",
                    quarantine_cap, QUARANTINE_CAP_ENV_VAR,
                )
                _log_landed_rows(returned_ids, logger)
                return returned_ids, [], CAP_EXCEEDED, str(quarantine_cap)

    # Count matters here and nowhere else: a whole batch refused alike,
    # with nothing landing, is as consistent with a schema fault as with
    # poison, and the two want opposite responses (finding C3).
    if (total_rows >= MIN_ROWS_FOR_CORRELATED
            and not returned_ids
            and len(poison) == total_rows
            and len(signatures) == 1
            and not quarantine_anyway):
        signature = next(iter(signatures))
        logger.error(
            "All %d row(s) were refused with the same SQLSTATE (%s) and "
            "not one landed. That is either correlated poison — one bad "
            "extraction run, one LLM batch — or a schema fault the row "
            "errors are a symptom of, such as a migration adding a NOT "
            "NULL column or a unique index the upsert does not name. "
            "Quarantining would be right for the first and would lose "
            "%d rows for the second, so this run holds the cursor and "
            "quarantines nothing. Check the schema; if the rows really "
            "are poison, re-run once with %s=1 (or --quarantine-anyway).",
            total_rows, signature, total_rows, QUARANTINE_ANYWAY_ENV_VAR,
        )
        _log_landed_rows(returned_ids, logger)
        return returned_ids, [], CORRELATED, signature

    return returned_ids, poison, ROW, ""


def _log_landed_rows(
    returned_ids: set[str],
    logger: logging.Logger,
) -> None:
    """
    Say which rows committed before the replay was abandoned.

    They are in the database while the cursor stays behind them, so the
    next run re-attempts them — harmless (``ON CONFLICT`` covers it) but
    invisible without this line, which left an operator comparing counts
    with no way to tell what had already landed (second re-audit, low
    finding L4).
    """
    if not returned_ids:
        logger.info("No row had landed before the run was abandoned.")
        return
    landed = sorted(returned_ids)
    logger.warning(
        "%d row(s) DID land before the run was abandoned and are already "
        "in PostgreSQL; the cursor stays behind them, so the next run "
        "re-attempts them harmlessly. First 10: %s",
        len(landed), landed[:10],
    )


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
