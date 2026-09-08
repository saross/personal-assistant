#!/usr/bin/env python3
"""
Sync memories from canonical JSONL to PostgreSQL query layer.

Reads from memories/memories.jsonl starting at the last synced line,
inserts new records into PostgreSQL, and updates the sync cursor.

Connection: peer auth via unix socket (postgresql:///claude_memories).
Designed to run via cron every 5 minutes.

Usage:
    venv/bin/python3 scripts/sync-to-postgres.py
"""

import argparse
import json
import logging
from dataclasses import dataclass, replace
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, NamedTuple

# Shared quarantine helper (audit IC2 — quarantine-on-skip).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sync_cursor import (  # noqa: E402
    QUARANTINE_FAILED,
    QUARANTINE_WRITTEN,
    append_quarantine_entry,
    count_quarantine_entries,
    cursor_fault_detail,
    read_quarantine_entries,
    normalise_line_cursor,
    CursorKeyVanished,
    quarantine_record,
    read_cursor_file,
    read_cursor_file_locked,
    update_cursor_file,
)
# Schema-version guard (audit IC5 / B-X1) — every PG-touching script
# asserts the on-disk schema version before issuing queries.
from _schema_version import assert_schema_version, SchemaVersionError  # noqa: E402
# Row-level Postgres guards (audit round two, finding P2 / lens A-X1+A-X2).
from _sync_gate import (  # noqa: E402
    CYCLE_COMPLETED,
    CYCLE_CONTENDED,
    CYCLE_DEGRADED,
    CYCLE_IDLE,
    CYCLE_ACK,
    CYCLE_OUTAGE,
    PROBLEM_QUARANTINE,
    STATE_CORRUPT,
    MEMORIES_GATE as _DEFAULT_GATE_FILE,
    GateEvent,
    apply_gate,
    gate_matches_state,
    read_state_safely,
    read_state_with_status,
    state_path_for,
)
from _pg_row_guard import (  # noqa: E402
    CAP_EXCEEDED,
    CORRELATED,
    DEFAULT_QUARANTINE_CAP,
    ENVIRONMENT,
    OUTAGE,
    QUARANTINE_ANYWAY_ENV_VAR,
    QUARANTINE_CAP_ENV_VAR,
    CorrelatedRefusal,
    EnvironmentFault,
    QuarantineCapExceeded,
    classify_pg_error,
    environment_remedy,
    insert_rows_individually,
    resolve_quarantine_anyway,
    resolve_quarantine_cap,
    sanitise_nuls,
    sqlstate_class,
)

# Optional embedding support — gracefully degrades if unavailable
try:
    from embed import (
        build_embed_text,
        generate_embeddings,
        is_ollama_available,
        EmbeddingDimensionError,
    )
    HAS_EMBED = True
except ImportError:
    HAS_EMBED = False

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path(__file__).resolve().parent.parent
MEMORIES_FILE = PA_DIR / "memories" / "memories.jsonl"
CURSOR_FILE = PA_DIR / "memories" / "sync-cursors.json"
LOG_DIR = PA_DIR / "logs"
LOG_FILE = LOG_DIR / "sync.log"
# Quarantine destination for rows silently dropped by ON CONFLICT.
# Lives in the data submodule but the *write* is fine — we just do not
# commit submodule pointer changes as part of this fix (#55).
QUARANTINE_FILE = PA_DIR / "data" / "memories" / "quarantine-postgres-drops.jsonl"
DB_NAME = "claude_memories"
# Session-start gate raised on exit 4 / 6 (re-audit finding C2). A module
# constant rather than the helper's default so tests can pin it to a tmp
# directory: a test that writes the real gate would put a fabricated
# problem in front of Shawn at his next session start.
SCRIPT_NAME = "sync-to-postgres.py"
GATE_FILE = _DEFAULT_GATE_FILE
# Advisory-lock key for serialising concurrent sync runs. PG hashes the
# string to a 32-bit int; `pg_try_advisory_lock` is session-scoped and
# auto-releases when the connection closes.
ADVISORY_LOCK_KEY = "sync-to-postgres"

# All fields we extract from JSONL and insert into PostgreSQL.
# v2 additions (2026-05-16): anchors, verified, links, why, how_to_apply,
# superseded_by, revisions. Pre-v2 entries lack these fields; record_to_tuple
# defaults them to empty / NULL appropriately.
# v3 additions (2026-05-17):
#   - source_message_uuid — transcript-message anchor used by the tier-3
#     archive verifier (Gap 1). Optional; pre-v3 entries default to NULL.
#   - licence, extractor_model_id — RO-Crate / FAIR sharing fields
#     (Gap 3). licence defaults to NULL until the user opts in;
#     extractor_model_id defaults to NULL for pre-v3 rows and to
#     HAIKU_MODEL for v3+ extraction-hook writes.
JSONL_FIELDS = [
    "id", "session_id", "project", "source", "category", "content",
    "summary", "confidence", "research_tags", "zotero_key",
    "source_context", "created_at", "deadline_at",
    # v2 schema
    "anchors", "verified", "links", "why", "how_to_apply",
    "superseded_by", "revisions",
    # v3 schema
    "source_message_uuid", "licence", "extractor_model_id",
    # Soft-delete flag (P8 fix, 2026-06-06). Appended last so existing
    # tuple indices stay stable. Absent from most records (defaults TRUE);
    # /forget writes is_active=false, and syncing it here means a
    # forgotten-before-first-sync row inserts inactive rather than being
    # resurrected as active by the INSERT's column default.
    "is_active",
]


# ============================================================================
# Logging
# ============================================================================

def setup_logging() -> logging.Logger:
    """Configure logging to file and stderr.

    Guards against handler stacking: ``logging.getLogger(name)`` returns
    the same logger across calls, and ``addHandler`` would otherwise
    duplicate emit lines each time ``main()`` runs in a long-lived
    process (tests, MCP server). Skip configuration when handlers
    already exist.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sync-to-postgres")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        # Already configured (this process has called setup_logging
        # before). Do not stack a second pair of handlers.
        return logger

    # File handler
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    # Stderr handler (for cron error capture)
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.WARNING)
    sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(sh)

    return logger


@dataclass(frozen=True)
class CycleResult:
    """
    What one sync cycle learnt. Translated into a
    :class:`_sync_gate.GateEvent` by ``main``.

    ``connected`` is tri-state: True is evidence against an outage, False
    is evidence for one, and None means the run never tried.
    """

    outcome: str
    processed: int = 0
    connected: bool | None = None
    #: Why this cycle is degraded, if it is — the text the gate shows.
    degraded_detail: str | None = None
    #: Where the cursor stood when this cycle STARTED, so the gate can
    #: see a rebuild that rewound or removed it between runs. ``None``
    #: alongside ``cursor_seen`` means the key was absent (ninth
    #: re-audit, C2).
    cursor_position: int | str | None = None
    #: Where this cycle left it, which is what the NEXT run's starting
    #: position is compared against.
    cursor_position_after: int | str | None = None
    #: Did this cycle get far enough to read the cursor at all?
    cursor_seen: bool = False


# ============================================================================
# Cursor management
# ============================================================================

def load_cursor(cursor_key: str = "postgres_sync_line") -> int:
    """
    Load the last synced line number from the cursor file.

    Returns 0 if the file doesn't exist or the key is missing.

    The sync cycle itself does NOT use this: it needs the position and
    the key's presence from one atomic observation, so it reads the whole
    object once under the lock (low finding L1). This remains for
    diagnostics and for callers that only want the number.
    """
    try:
        return int(read_cursor_file(CURSOR_FILE).get(cursor_key, 0))
    except (ValueError, TypeError):
        return 0


def save_cursor(
    line_number: int,
    cursor_key: str = "postgres_sync_line",
    *,
    expect_present: bool = False,
) -> None:
    """Save the current sync position to the cursor file.

    Routed through :func:`_sync_cursor.update_cursor_file` (audit round
    two, finding P16): four processes read-modify-write this one file,
    so the whole cycle runs under an exclusive flock and the write itself
    is temp-file + ``os.replace``. Before that, an interleaving lost one
    process's advance, and a kill part-way through the write truncated
    the file and reset every cursor at once.

    ``expect_present`` makes the write a compare-and-set (re-audit
    finding M3). Pass whether the key was in the snapshot
    :func:`_sync_locked` read at the start of the cycle: if it was there
    then and is gone now, a
    rebuild cleared it, and writing this position back would tell the
    next run that rows the rebuild destroyed are already synced. Raises
    :class:`CursorKeyVanished` instead.
    """
    update_cursor_file(
        CURSOR_FILE, {cursor_key: line_number},
        expect_present=(cursor_key,) if expect_present else (),
    )


def save_sync_timestamp() -> None:
    """
    Record a wall-clock timestamp of the most recent successful sync.

    Paired with `postgres_sync_line`, this lets /recall (via
    fetch-memories.py) detect "stale" states — i.e. the JSONL has grown
    since the last sync, or the cursor hasn't advanced in a while —
    and warn the caller that /recall results may be incomplete.
    """
    from datetime import datetime, timezone
    update_cursor_file(
        CURSOR_FILE,
        {"postgres_last_sync_ts": datetime.now(timezone.utc).isoformat()},
    )


# ============================================================================
# JSONL parsing
# ============================================================================

def parse_jsonl_record(line: str, line_number: int, logger: logging.Logger
                       ) -> dict[str, Any] | None:
    """
    Parse a single JSONL line into a record dict.

    Returns None for empty/malformed lines. Applies defaults for
    missing optional fields.

    Note: callers that need to distinguish "blank line" (legitimate skip)
    from "malformed JSON / missing required field" (poison record that
    should be quarantined) should use :func:`classify_jsonl_line` below.
    """
    stripped = line.strip()
    if not stripped:
        return None
    try:
        record = json.loads(stripped)
    except json.JSONDecodeError as exc:
        logger.warning("Malformed JSON at line %d: %s", line_number, exc)
        return None

    # Validate required fields
    required = ["id", "category", "content", "created_at"]
    for field in required:
        if field not in record or not record[field]:
            logger.warning(
                "Missing required field '%s' at line %d (id=%s)",
                field, line_number, record.get("id", "unknown"),
            )
            return None

    return record


def classify_jsonl_line(
    line: str,
    line_number: int,
    logger: logging.Logger,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Parse a single JSONL line, returning ``(record, failure_reason)``.

    Outcomes:
      * ``(record, None)`` — successfully parsed and valid.
      * ``(None, None)`` — blank/whitespace-only line (legitimate skip,
        no quarantine).
      * ``(None, "<reason>")`` — poison record (malformed JSON, missing
        required field, or an unusable ``created_at``). The caller should
        quarantine the raw line before advancing the cursor (audit IC2 /
        B-C4).

    This is also the ingest boundary for NUL sanitising (audit round two,
    finding P2 / lens A-X2): the canonical JSONL can hold a NUL, but
    PostgreSQL cannot store one in ``text`` — psycopg2 raises
    ``ValueError`` before the statement is even sent, which is not a
    ``psycopg2.Error`` and so escaped every handler in this file.
    """
    stripped = line.strip()
    if not stripped:
        return None, None
    try:
        record = json.loads(stripped)
    except json.JSONDecodeError as exc:
        logger.warning("Malformed JSON at line %d: %s", line_number, exc)
        return None, "parse_failure"

    record, nuls_removed = sanitise_nuls(record)
    if nuls_removed:
        logger.warning(
            "Removed %d NUL character(s) from line %d (id=%s) before "
            "syncing — PostgreSQL cannot store U+0000 in a text column.",
            nuls_removed, line_number, record.get("id", "unknown"),
        )

    required = ["id", "category", "content", "created_at"]
    for field in required:
        if field not in record or not record[field]:
            logger.warning(
                "Missing required field '%s' at line %d (id=%s)",
                field, line_number, record.get("id", "unknown"),
            )
            return None, f"missing_required_field:{field}"

    # ``created_at`` is TIMESTAMPTZ NOT NULL (scripts/schema.sql), and
    # unlike ``deadline_at`` it has no NULL-coercion escape: free text
    # there aborts the insert. ``deadline_at`` has repeatedly carried
    # values like 'TBD', '2026-08-XX' and '2026-Q4' — the same hands
    # write both fields, so validate before the database has to
    # (audit round two, finding P2 / lens A-C2).
    if not _is_parseable_timestamp(record["created_at"]):
        logger.warning(
            "Unparseable created_at %r at line %d (id=%s) — quarantining; "
            "the column is TIMESTAMPTZ NOT NULL and cannot take it.",
            record["created_at"], line_number, record.get("id", "unknown"),
        )
        return None, "unparseable_created_at"

    return record, None


def _is_parseable_timestamp(value: Any) -> bool:
    """Return True when ``value`` is an ISO timestamp PostgreSQL will take.

    Every writer of ``created_at`` goes through ``_timestamps.now_iso()``
    (``datetime.now(timezone.utc).isoformat()``), so a value this rejects
    was hand-edited or produced outside the pipeline — precisely the case
    worth catching before it reaches a NOT NULL TIMESTAMPTZ column.
    """
    from datetime import datetime
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    return True


def _deadline_or_none(value: Any) -> Any:
    """Pass through a parseable ISO timestamp; coerce anything else to None.

    ``deadline_at`` is free text at capture time — a manual record has
    carried ``"TBD"`` — and an unparseable value must not abort the whole
    insert batch against the TIMESTAMPTZ column. NULL is semantically safe:
    the decay view falls back to ``created_at`` when ``deadline_at`` is NULL.
    """
    if value is None:
        return None
    from datetime import datetime
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        logging.getLogger("sync-to-postgres").warning(
            "Unparseable deadline_at %r — syncing as NULL", value,
        )
        return None
    return value


def record_to_tuple(record: dict[str, Any]) -> tuple:
    """
    Convert a parsed JSONL record to an INSERT-ready tuple.

    Field order matches JSONL_FIELDS and the INSERT column list in
    insert_records(). v2 JSONB fields (anchors, links, revisions) are
    wrapped in psycopg2.extras.Json so they serialise correctly into
    JSONB columns; v2 TEXT fields default to NULL when absent.
    """
    # Lazy import — psycopg2 is only loaded when this codepath runs,
    # matching the pattern used elsewhere in the file.
    from psycopg2.extras import Json

    def _list_or_empty(value: Any) -> list:
        return value if isinstance(value, list) else []

    return (
        record["id"],
        # ``or ""`` rather than a .get default: manual (/remember) records
        # carry an explicit ``session_id: null``, which .get would pass
        # through to the NOT NULL column and abort the whole insert batch.
        record.get("session_id") or "",
        record.get("project"),
        record.get("source", "extraction"),
        record["category"],
        record["content"],
        record.get("summary"),
        record.get("confidence", "medium"),
        record.get("research_tags") if isinstance(record.get("research_tags"), list) else [],
        record.get("zotero_key"),
        record.get("source_context", ""),
        record["created_at"],
        _deadline_or_none(record.get("deadline_at")),
        # v2 fields (2026-05-16)
        Json(_list_or_empty(record.get("anchors"))),
        record.get("verified"),
        Json(_list_or_empty(record.get("links"))),
        record.get("why"),
        record.get("how_to_apply"),
        record.get("superseded_by"),
        Json(_list_or_empty(record.get("revisions"))),
        # v3 fields (2026-05-17)
        record.get("source_message_uuid"),
        record.get("licence"),
        record.get("extractor_model_id"),
        # Soft-delete flag (P8 fix, 2026-06-06) — defaults TRUE when absent,
        # mirroring the column default; a /forget'd record carries False.
        record.get("is_active", True),
    )


# ============================================================================
# Database operations
# ============================================================================

class InsertResult(NamedTuple):
    """
    Accounting result for a single insert batch.

    Attributes:
        input_count: Number of records attempted after within-batch
            dedup (see ``duplicates_within_batch``).
        inserted: Number of rows PG actually inserted (from RETURNING).
        expected_dupes: Rows already present at pre-flight — ON CONFLICT
            was expected to skip these, so they are not anomalies.
        unexpected_drops: Ids that were neither present pre-flight nor
            returned by INSERT. These indicate silent row loss (#55).
        db_available: False when we could not *reach* the database. A
            record the database refused is not an outage — see
            ``quarantined``.
        duplicates_within_batch: Input records that shared an id with
            another record in the same batch; the last occurrence won.
            Non-zero here usually indicates canonical corruption.
        newly_quarantined: How many of ``quarantined`` were written to
            the quarantine file by THIS run. The gate reports this, not
            the length of ``quarantined``: a held cursor re-offers the
            same rows every tick and they are deduplicated on disk
            (seventh re-audit, finding C2).
        quarantined: Ids PostgreSQL refused on content grounds. They have
            been written to the quarantine file, so the caller may
            advance the cursor past them: they are accounted for, not
            silently lost (audit round two, finding P2 / lens A-X1).
    """

    input_count: int
    inserted: int
    expected_dupes: int
    unexpected_drops: list[str]
    db_available: bool
    duplicates_within_batch: int = 0
    quarantined: tuple[str, ...] = ()
    newly_quarantined: int = 0


@contextmanager
def _sync_advisory_lock(
    logger: logging.Logger,
) -> Iterator[tuple[bool, bool | None]]:
    """
    Acquire a PostgreSQL session-scoped advisory lock for the sync cycle.

    Yields ``(proceed, connected)``. ``connected`` is None when psycopg2
    is missing, False when the connection failed, and True when the lock
    was taken over a live connection — which is the only honest way for
    an idle cycle to know whether the database was reachable (sixth
    re-audit, finding M3).

    Yields True when the sync should proceed, False when another sync
    already holds the lock and this run should defer to the next cron
    tick. The lock auto-releases when the backing connection closes.

    If psycopg2 is missing or the database is unreachable, yields True
    unconditionally — those cases are handled by the insert path, which
    logs appropriately and leaves the cursor alone.

    This prevents the race where two overlapping sync runs both see the
    same ids as missing from pre-flight, both attempt INSERT, and the
    loser classifies the winner's rows as unexpected_drops (#55).
    """
    try:
        import psycopg2
    except ImportError:
        yield True, None
        return

    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError:
        # Could not connect; the insert path reports the outage. The
        # second element says so, because an idle cycle otherwise has no
        # way to know whether the database was reachable (finding M3).
        yield True, False
        return

    # Schema-version guard (audit IC5). On mismatch we exit non-zero
    # rather than silently proceed against an unexpected shape.
    try:
        assert_schema_version(conn)
    except SchemaVersionError:
        conn.close()
        sys.exit(2)
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
        # The connection died between connect and the version query.
        # That is an outage, not an unexpected fault: raising here made
        # it exit 1 with a fault only a completed run could lower —
        # which cannot happen while the database is down (seventh
        # re-audit, finding M2).
        logger.warning("Lost the connection during the schema check: %s", exc)
        conn.close()
        yield True, False
        return

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s))",
                (ADVISORY_LOCK_KEY,),
            )
            acquired = bool(cur.fetchone()[0])
        conn.commit()  # end txn; session-scoped lock persists on conn
        if not acquired:
            logger.warning(
                "Another sync holds the advisory lock for %r — skipping "
                "this cycle. Will retry on next tick.",
                ADVISORY_LOCK_KEY,
            )
            yield False, True
            return
        yield True, True
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
        # Same reasoning: an outage during the lock query is an outage
        # (finding M2).
        logger.warning(
            "Lost the connection while taking the advisory lock: %s", exc,
        )
        yield True, False
    finally:
        conn.close()  # releases the lock if we hold it


def _load_quarantined_ids() -> set[str] | None:
    """
    Return the set of ids already present in the quarantine JSONL.

    Used to avoid appending duplicate rows on repeated cron runs. When
    the cursor halts, subsequent ticks re-read the same input slice and
    would otherwise quarantine the same ids over and over. Malformed
    lines are skipped silently — the quarantine file is a diagnostic
    log, not load-bearing.

    Reads through :func:`read_quarantine_entries`, the one parser, so
    this cannot come to disagree with the gate about what is in the
    file. Returns ``None`` when the file cannot be read at all: the
    duplicate check is then UNKNOWN, and the caller writes anyway,
    because a repeated entry is a nuisance and a lost one is a lost row
    (eleventh re-audit, finding M2).
    """
    if not QUARANTINE_FILE.exists():
        # For a WRITER about to create the file, "not there" is not the
        # ambiguity it is for the gate: there is nothing to duplicate.
        return set()
    entries = read_quarantine_entries(QUARANTINE_FILE)
    if entries is None:
        # One bad byte used to raise UnicodeDecodeError straight out of
        # here and out of _write_quarantine with it, so a single damaged
        # character stopped every quarantine write on the machine for
        # ever. Unknown is not empty and not fatal: the caller writes
        # anyway (eleventh re-audit, finding M2).
        return None
    ids: set[str] = set()
    for rec in entries:
        # Two shapes live in this one file. ``_write_quarantine``
        # appends the bare row, so the id is at the top level;
        # ``_sync_cursor.quarantine_record`` wraps it as
        # ``{"reason", "quarantined_at", "record"}``, so the id is one
        # level down. Reading only the first shape meant the dedup could
        # not see entries written by the second (re-audit, low finding).
        for candidate in (rec, rec.get("record")):
            if isinstance(candidate, dict):
                mid = candidate.get("id")
                if isinstance(mid, str):
                    ids.add(mid)
    return ids


def _write_quarantine(
    dropped_records: list[dict[str, Any]],
    logger: logging.Logger,
) -> None:
    """
    Append dropped memory records to the quarantine JSONL.

    Creates parent directories and the file if missing. Deduplicates
    against already-quarantined ids so repeated cron runs against the
    same halted cursor do not grow the file linearly. We quarantine
    the *full records* (not just ids) so the drop can be diagnosed and
    replayed without consulting the canonical.
    """
    already = _load_quarantined_ids()
    if already is None:
        logger.warning(
            "Could not read %s to check for duplicates — appending "
            "without deduplicating. A repeated entry is a nuisance; a "
            "dropped record is a lost row.", QUARANTINE_FILE,
        )
        new_records = list(dropped_records)
    else:
        new_records = [
            r for r in dropped_records if r.get("id") not in already
        ]
    if not new_records:
        logger.info(
            "All %d dropped record(s) already in quarantine — no new appends",
            len(dropped_records),
        )
        return
    skipped = len(dropped_records) - len(new_records)
    # Through the SHARED appender, which repairs a missing separator
    # before it writes. Appending here directly ran this record onto the
    # end of a complete row whose newline had been lost, and both then
    # vanished from every reader at once (eleventh re-audit, C1).
    for rec in new_records:
        if not append_quarantine_entry(QUARANTINE_FILE, rec):
            logger.error(
                "Could not write quarantine file %s — %d record(s) are "
                "unaccounted for", QUARANTINE_FILE, len(new_records),
            )
            return
    if skipped:
        logger.info(
            "Quarantined %d new record(s) (skipped %d already present) "
            "to %s", len(new_records), skipped, QUARANTINE_FILE,
        )
    else:
        logger.info(
            "Quarantined %d unexpectedly-dropped record(s) to %s",
            len(new_records), QUARANTINE_FILE,
        )


def _quarantine_refused_records(
    poison: list[tuple[str, str]],
    records_by_id: dict[str, tuple],
    logger: logging.Logger,
) -> tuple[list[str], list[str]]:
    """
    Write every record PostgreSQL refused on content grounds to quarantine.

    Parameters
    ----------
    poison:
        ``(memory id, error message)`` pairs from the per-row replay.
    records_by_id:
        The deduped INSERT tuples, so the offending values are preserved
        for diagnosis. Values are stringified because the tuple carries
        psycopg2 adapters (``Json``) that are not JSON-serialisable.
    logger:
        Logger for the quarantine event.

    Returns
    -------
    tuple[list[str], list[str]]
        ``(accounted_for, newly_written)``. The first is every id whose
        entry is on disk — a duplicate counts, because the cursor may
        advance past it. The second is only what THIS call appended, and
        is a diagnostic: the gate derives its number from the file.

        Only ids in ``accounted_for`` may be skipped by a cursor
        advance: a quarantine write that failed leaves the record
        unaccounted for, so it stays in ``unexpected_drops`` and
        halts the cursor instead (audit IC2's contract).
    """
    quarantined: list[str] = []
    newly_written: list[str] = []
    for memory_id, message in poison:
        record = records_by_id.get(memory_id)
        status = quarantine_record(
            QUARANTINE_FILE,
            {
                "id": memory_id,
                "postgres_error": message,
                "row_values": (
                    [str(value) for value in record] if record else None
                ),
            },
            "postgres_refused_row",
            logger=logger,
        )
        if status == QUARANTINE_WRITTEN:
            # Only a line that actually reached the file counts towards
            # the gate. A duplicate is still "accounted for" — the cursor
            # may advance past it — but counting it inflated the gate by
            # the whole batch on every tick while the cursor was held
            # (seventh re-audit, finding C2).
            newly_written.append(memory_id)
        if status != QUARANTINE_FAILED:
            quarantined.append(memory_id)
        else:
            logger.error(
                "Could not quarantine refused record %s — holding the "
                "cursor rather than skipping it.", memory_id,
            )
    return quarantined, newly_written


def insert_memories(
    records: list[tuple],
    logger: logging.Logger,
    quarantine_cap: int | None = None,
    quarantine_anyway: bool = False,
) -> InsertResult:
    """
    Insert memory records into PostgreSQL with full accounting.

    Workflow:
      1. Dedupe the input batch by id (last occurrence wins) so that
         within-batch duplicates are not misclassified as drops.
      2. Pre-flight: SELECT existing ids so we know what ON CONFLICT is
         *supposed* to skip (expected duplicates).
      3. INSERT ... ON CONFLICT DO NOTHING RETURNING id, capturing the
         set of ids PG actually inserted.
      4. Classify every input id as inserted, expected-dupe, or
         unexpected-drop.

    Returns an :class:`InsertResult` so callers can decide whether to
    advance the sync cursor. Callers MUST treat ``unexpected_drops``
    non-empty as a hard stop — those rows never landed and skipping
    them would cause silent loss (#55).

    Failure handling splits two cases that were previously conflated
    (audit round two, finding P2 / lens A-X1):

    * The database is unreachable — ``db_available=False``, the caller
      holds the cursor, and the next cron tick retries.
    * The database refused a record's *content* (a free-text timestamp,
      a dict where a scalar belongs, a NUL) — the batch is replayed one
      record at a time so the healthy records still land, and the
      offending ones are quarantined so the cursor can advance. Retrying
      those forever cannot help: the failure is deterministic, and while
      the cursor sits still every later memory is invisible to /recall.
    """
    # Within-batch dedup: if the same id appears twice in ``records``,
    # only the last occurrence would "win" in PG anyway (subsequent
    # inserts against the just-inserted row conflict). Collapse here so
    # ``input_count`` and the set-based classification stay consistent.
    by_id: dict[str, tuple] = {}
    for rec in records:
        by_id[rec[0]] = rec
    deduped_records = list(by_id.values())
    duplicates_within_batch = len(records) - len(deduped_records)
    input_count = len(deduped_records)

    try:
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError:
        logger.error(
            "psycopg2 not installed. Run: venv/bin/pip install psycopg2-binary"
        )
        return InsertResult(
            input_count=input_count,
            inserted=0,
            expected_dupes=0,
            unexpected_drops=[],
            db_available=False,
            duplicates_within_batch=duplicates_within_batch,
        )

    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError as exc:
        logger.warning("Cannot connect to PostgreSQL: %s", exc)
        logger.info(
            "PostgreSQL may be stopped — this is not critical. "
            "JSONL remains canonical."
        )
        return InsertResult(
            input_count=input_count,
            inserted=0,
            expected_dupes=0,
            unexpected_drops=[],
            db_available=False,
            duplicates_within_batch=duplicates_within_batch,
        )

    # Schema-version guard (audit IC5). Mismatch is treated as fatal —
    # silently proceeding could insert against the wrong shape.
    try:
        assert_schema_version(conn)
    except SchemaVersionError:
        conn.close()
        sys.exit(2)

    input_ids = [r[0] for r in deduped_records]

    insert_sql = """
        INSERT INTO memories (
            id, session_id, project, source, category, content, summary,
            confidence, research_tags, zotero_key, source_context,
            created_at, deadline_at,
            anchors, verified, links, why, how_to_apply,
            superseded_by, revisions,
            source_message_uuid, licence, extractor_model_id,
            is_active
        ) VALUES %s
        ON CONFLICT (id) DO NOTHING
        RETURNING id
    """

    records_by_id = {rec[0]: rec for rec in deduped_records}

    try:
        present_before: set[str] = set()
        returned_ids: set[str] = set()
        quarantined: list[str] = []
        newly: list[str] = []
        try:
            with conn:
                with conn.cursor() as cur:
                    # Pre-flight: which of our input ids are already in PG?
                    # These are the rows ON CONFLICT is expected to skip.
                    # ANY(%s) sends the list as a single PG array parameter,
                    # so we are not limited by the ~32k per-statement
                    # parameter ceiling — batches of 100k ids would still fit.
                    cur.execute(
                        "SELECT id FROM memories WHERE id = ANY(%s)",
                        (input_ids,),
                    )
                    present_before = {row[0] for row in cur.fetchall()}

                    # Insert with RETURNING to capture what PG actually took.
                    returned = execute_values(
                        cur,
                        insert_sql,
                        deduped_records,
                        page_size=100,
                        fetch=True,
                    )
                    returned_ids = {row[0] for row in returned}
        except (psycopg2.Error, ValueError, TypeError) as exc:
            verdict = classify_pg_error(exc, psycopg2)
            if verdict == OUTAGE:
                logger.warning("Cannot reach PostgreSQL during insert: %s", exc)
                logger.info(
                    "PostgreSQL may be stopped — this is not critical. "
                    "JSONL remains canonical; cursor held for the next tick."
                )
                return InsertResult(
                    input_count=input_count,
                    inserted=0,
                    expected_dupes=0,
                    unexpected_drops=[],
                    db_available=False,
                    duplicates_within_batch=duplicates_within_batch,
                )
            if verdict == ENVIRONMENT:
                # Permissions, a missing table or column, an aborted
                # transaction: reachable but not in the expected state.
                # The records are fine; quarantining them would discard
                # good memories and advance the cursor past them.
                raise EnvironmentFault(
                    f"PostgreSQL refused the insert for a reason that is "
                    f"not about the data (SQLSTATE "
                    f"{getattr(exc, 'pgcode', None) or 'none'}, "
                    f"{type(exc).__name__}: {str(exc).strip()}). "
                    f"Cursor held; nothing quarantined. "
                    f"{environment_remedy(sqlstate_class(exc))}"
                ) from exc
            # The database refused a record's content (a bad timestamp, a
            # dict where a scalar belongs, a NUL). ``execute_values`` sends
            # the page in one transaction, so one bad record aborts the
            # whole batch; replay individually to find out which one.
            logger.error(
                "Batch insert refused by PostgreSQL (%s) — replaying %d "
                "record(s) individually to isolate the offending row(s).",
                str(exc).strip(), len(deduped_records),
            )
            returned_ids, poison, status, detail = insert_rows_individually(
                conn,
                insert_sql,
                deduped_records,
                psycopg2_module=psycopg2,
                execute_values=execute_values,
                logger=logger,
                quarantine_cap=resolve_quarantine_cap(
                    quarantine_cap, logger=logger,
                ),
                quarantine_anyway=resolve_quarantine_anyway(
                    quarantine_anyway, logger=logger,
                ),
            )
            if status == OUTAGE:
                return InsertResult(
                    input_count=input_count,
                    inserted=len(returned_ids),
                    expected_dupes=len(present_before),
                    unexpected_drops=[],
                    db_available=False,
                    duplicates_within_batch=duplicates_within_batch,
                )
            if status == ENVIRONMENT:
                raise EnvironmentFault(
                    f"The per-row replay stopped: the refusals are not "
                    f"about the data (SQLSTATE class {detail}). Cursor "
                    f"held; nothing quarantined. "
                    f"{environment_remedy(detail)}"
                )
            if status == CAP_EXCEEDED:
                raise QuarantineCapExceeded(
                    f"more than {detail} record(s) were refused in one "
                    f"run. The database is fine and they may genuinely be "
                    f"poison, but quarantining that many would advance "
                    f"the cursor past every one of them. Cursor held; "
                    f"nothing quarantined."
                )
            if status == CORRELATED:
                raise CorrelatedRefusal(
                    f"every record in the batch was refused with the same "
                    f"SQLSTATE ({detail}) and not one landed. That is "
                    f"either correlated poison or a schema fault the row "
                    f"errors are a symptom of. Cursor held; nothing "
                    f"quarantined."
                )
            quarantined, newly = _quarantine_refused_records(
                poison, records_by_id, logger,
            )

        # Preserve input order when reporting unexpected drops. A record
        # the database explicitly refused is accounted for by its
        # quarantine entry, so it is not a silent drop.
        quarantined_set = set(quarantined)
        unexpected_drops = [
            mid
            for mid in input_ids
            if mid not in present_before
            and mid not in returned_ids
            and mid not in quarantined_set
        ]

        result = InsertResult(
            input_count=input_count,
            inserted=len(returned_ids),
            expected_dupes=len(present_before),
            unexpected_drops=unexpected_drops,
            db_available=True,
            duplicates_within_batch=duplicates_within_batch,
            quarantined=tuple(quarantined),
            newly_quarantined=len(newly),
        )

        # Keep the happy path quiet; escalate only when there is
        # something a human might want to see. Pure re-sync cycles
        # (all expected_dupes) emit at DEBUG; anything anomalous or
        # novel is logged at INFO.
        accounting_msg = (
            "Insert accounting: input=%d inserted=%d expected_dupes=%d "
            "unexpected_drops=%d dupes_in_batch=%d quarantined=%d"
        )
        accounting_args = (
            result.input_count, result.inserted, result.expected_dupes,
            len(result.unexpected_drops), result.duplicates_within_batch,
            len(result.quarantined),
        )
        if (unexpected_drops or duplicates_within_batch
                or result.inserted or quarantined):
            logger.info(accounting_msg, *accounting_args)
        else:
            logger.debug(accounting_msg, *accounting_args)

        if duplicates_within_batch:
            logger.warning(
                "Input batch contained %d within-batch duplicate id(s); "
                "last occurrence of each id won. Check canonical JSONL "
                "for corruption.",
                duplicates_within_batch,
            )
        if unexpected_drops:
            logger.error(
                "Unexpectedly dropped %d id(s) — neither pre-existing "
                "nor inserted. First 10: %s",
                len(unexpected_drops),
                unexpected_drops[:10],
            )
        return result
    finally:
        conn.close()


# ============================================================================
# Embedding update (best-effort, post-insert)
# ============================================================================

EMBED_BATCH_SIZE = 100


def _update_embeddings(logger: logging.Logger) -> None:
    """
    Embed memories with NULL embedding column.

    Processes up to EMBED_BATCH_SIZE records per invocation. Called after
    each sync cycle. If Ollama is unavailable, logs a debug message and
    returns — content sync is never blocked by embedding failures.
    """
    if not is_ollama_available():
        logger.debug("Ollama unavailable — skipping embedding update")
        return

    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        return

    conn = None
    try:
        conn = psycopg2.connect(dbname=DB_NAME)
        # Schema-version guard (audit IC5). Embedding update is best-
        # effort and runs AFTER a successful insert pass; calling
        # ``sys.exit(2)`` here makes the operator see a non-zero exit
        # code despite the sync having actually completed. Downgrade to
        # a warning + early return so the exit code reflects the actual
        # outcome — embeddings will catch up on the next cron tick once
        # the schema mismatch is resolved.
        try:
            assert_schema_version(conn)
        except SchemaVersionError as exc:
            logger.warning(
                "Skipping embedding update — schema-version mismatch: %s",
                exc,
            )
            conn.close()
            return
        with conn.cursor() as cur:
            # Audit B-M10 (re-tiered Critical, 2026-05-02): the previous
            # ``ORDER BY created_at DESC`` walked the unembedded queue
            # newest-first. Under any sustained arrival rate exceeding
            # ``EMBED_BATCH_SIZE`` per cycle, the *oldest* unembedded
            # rows would never reach the front of the queue. The HNSW
            # partial index excludes rows with NULL embeddings, so those
            # records were silently absent from /recall results — a
            # wrong-results failure mode rather than a crash.
            #
            # ASC ordering means new arrivals temporarily wait while the
            # backlog drains, but they are caught up on the next cron
            # tick. Under bursty load both orderings behave identically;
            # under steady load ASC is the only one that bounds the age
            # of an unembedded row.
            cur.execute(
                """
                SELECT id, content, COALESCE(summary, ''),
                       COALESCE(source_context, '')
                FROM memories
                WHERE embedding IS NULL
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (EMBED_BATCH_SIZE,),
            )
            rows = cur.fetchall()

        if not rows:
            return

        texts = [
            build_embed_text({
                "content": content,
                "summary": summary,
                "source_context": source_context,
            })
            for _, content, summary, source_context in rows
        ]

        embeddings = generate_embeddings(texts)

        pairs = []
        for (mid, _, _, _), emb in zip(rows, embeddings):
            if emb is not None:
                pairs.append((json.dumps(emb), mid))

        if pairs:
            with conn:
                with conn.cursor() as cur:
                    psycopg2.extras.execute_batch(
                        cur,
                        "UPDATE memories SET embedding = "
                        "%s::vector WHERE id = %s",
                        pairs,
                        page_size=100,
                    )
            logger.info(
                "Embedded %d memories (%d still pending)",
                len(pairs), len(rows) - len(pairs),
            )

    except EmbeddingDimensionError as exc:
        # Deliberately ahead of the broad handler below: a wrong-width
        # model is a configuration fault that repeats on every tick, and
        # the old code turned PostgreSQL's rejection into a warning and
        # re-embedded the same rows forever. ERROR (not WARNING) so it
        # reaches cron's stderr capture (audit round two, finding P12).
        logger.error(
            "Embedding update ABORTED — %s Rows stay unembedded (and so "
            "absent from semantic /recall) until the endpoint is fixed; "
            "content sync is unaffected.", exc,
        )
    except Exception as exc:
        logger.warning("Embedding update failed (non-fatal): %s", exc)
    finally:
        if conn is not None:
            conn.close()


# ============================================================================
# Main sync logic
# ============================================================================

def check_canonical_for_duplicates(logger: logging.Logger) -> None:
    """Warn (once per sync) if the canonical contains duplicate ids.

    Duplicate ids indicate canonical corruption — most commonly from an
    accidental concat (merge/restore/manual append) or from a bug in a
    rewrite script. This tripwire was added after the 2026-04-14 dedup
    recovered from a 2026-03-15 concat accident that went unnoticed for
    ~30 days. A warning (not a fatal error) is deliberate: a corrupted
    canonical is bad, but not syncing is worse. The warning gets read
    out in cron logs and on the next /standup.
    """
    seen: set[str] = set()
    dups: set[str] = set()
    try:
        with open(MEMORIES_FILE, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    mid = json.loads(stripped).get("id")
                except json.JSONDecodeError:
                    continue
                if not mid:
                    continue
                if mid in seen:
                    dups.add(mid)
                else:
                    seen.add(mid)
    except OSError as exc:
        logger.warning("Duplicate-id check could not read canonical: %s", exc)
        return
    if dups:
        logger.warning(
            "Canonical contains %d duplicate ids — possible corruption. "
            "Run scripts/dedup-memories.py to investigate. First 3: %s",
            len(dups),
            sorted(dups)[:3],
        )


def sync(
    logger: logging.Logger,
    quarantine_cap: int | None = None,
    quarantine_anyway: bool = False,
) -> CycleResult:
    """
    Run one sync cycle: read new JSONL lines, insert into PostgreSQL,
    update cursor.

    Serialised against concurrent runs via a PG advisory lock; if another
    sync is in progress, this one exits without touching the cursor and
    the next cron tick retries.

    Returns
    -------
    CycleResult
        What the cycle learnt, which is what the gate policy needs: the
        outcome, how many rows were quarantined, how many were processed,
        and whether PostgreSQL was reached. Only a cycle that processed
        at least one row can lower a gate — absence of work is not
        evidence that a fault is gone (fourth re-audit, finding C1).
    """
    if not MEMORIES_FILE.exists():
        logger.warning("Memories file not found: %s", MEMORIES_FILE)
        return CycleResult(
            CYCLE_DEGRADED,
            degraded_detail=(
                f"[sync-to-postgres.py] the canonical memory store "
                f"{MEMORIES_FILE} is missing. Nothing can be synced until "
                f"it is back — check the data submodule."
            ),
            # Stated rather than left to the default: this return is
            # BEFORE the advisory lock, so the run never tried to reach
            # PostgreSQL and has learnt nothing about it. Spelling it out
            # keeps the rule exceptionless — every construction says what
            # it knows (ninth re-audit, finding M6).
            connected=None,
        )

    check_canonical_for_duplicates(logger)

    with _sync_advisory_lock(logger) as (acquired, connected):
        if not acquired:
            return CycleResult(CYCLE_CONTENDED, connected=connected)
        return _sync_locked(
            logger, quarantine_cap, quarantine_anyway, connected,
        )


def _sync_locked(
    logger: logging.Logger,
    quarantine_cap: int | None = None,
    quarantine_anyway: bool = False,
    lock_connected: bool | None = None,
) -> CycleResult:
    """Core sync cycle, executed under the advisory lock.

    Reports where the cursor stood when the cycle STARTED, whatever the
    cycle then did. The gate compares that with the position the last run
    recorded: an ordinary rebuild — one with no sync in flight — raises
    no exit 6 for anyone to notice, and the cursor going backwards is the
    only evidence that acknowledged rows are being re-offered (ninth
    re-audit, finding C2). Reporting the position at the END would say
    nothing, because a re-sync puts it back where it was.

    Returns a :class:`CycleResult` — see :func:`sync`.
    """
    snapshot = read_cursor_file_locked(CURSOR_FILE)
    # Normalised ONCE, here, and handed to both the cycle and the gate.
    # Two readers with different ideas of what counts as a cursor made
    # the gate see a rebuild the cycle had not noticed (tenth re-audit,
    # finding M1).
    raw_cursor = snapshot.get("postgres_sync_line")
    started_at = normalise_line_cursor(
        raw_cursor, key="postgres_sync_line", logger=logger,
    )
    # Present and unusable is not the same as absent, and it is the
    # failure this gate exists for: the sync resyncs from the beginning
    # every tick and the acknowledged quarantine position goes with it
    # (eleventh re-audit, findings M1 and M3).
    cursor_fault = (
        cursor_fault_detail(
            SCRIPT_NAME, "postgres_sync_line", CURSOR_FILE, raw_cursor,
            "a line number",
        )
        if raw_cursor is not None and started_at is None else None
    )
    result = _sync_locked_body(
        logger, quarantine_cap, quarantine_anyway, lock_connected,
        snapshot, started_at,
    )
    ended_at = normalise_line_cursor(
        read_cursor_file_locked(CURSOR_FILE).get("postgres_sync_line"),
        key="postgres_sync_line", logger=logger,
    )
    return replace(
        result,
        cursor_position=started_at,
        cursor_position_after=ended_at,
        cursor_seen=True,
        degraded_detail=result.degraded_detail or cursor_fault,
    )


def _sync_locked_body(
    logger: logging.Logger,
    quarantine_cap: int | None,
    quarantine_anyway: bool,
    lock_connected: bool | None,
    cursor_snapshot: dict,
    cursor_line: int | None,
) -> CycleResult:
    """The cycle itself, given the one locked cursor read above.

    ``cursor_line`` is the normalised position from :func:`_sync_locked`
    — the same value the gate is given, so the two can never disagree
    about where the cursor stood (tenth re-audit, finding M1).

    Returns a :class:`CycleResult` — see :func:`sync`.
    """
    # One locked read for both facts (low finding L1): the position, and
    # whether the key was there at all. Two unlocked reads leave a window
    # in which a rebuild lands between them, and the compare-and-set at
    # save time then concludes the key had always been absent — defeating
    # the check it was making. A first-ever run has no key and must still
    # be able to write one; only a key that *disappears* mid-run means a
    # rebuild happened (finding M3). The read itself now happens in
    # :func:`_sync_locked`, which passes the snapshot in so the cursor's
    # starting position can be reported to the gate.
    if cursor_line is None:
        cursor_line = 0
    cursor_key_was_present = "postgres_sync_line" in cursor_snapshot

    # Read all lines and process from cursor position
    lines = MEMORIES_FILE.read_text(encoding="utf-8").splitlines()
    total_lines = len(lines)

    # Shrink guard (item 22): if the canonical shrank below the saved cursor
    # — an archival sweep evicting records (scripts/archive-memories.py), a
    # dedup/compaction pass, or a submodule revert — the cursor would otherwise
    # sit past EOF. The ``cursor_line >= total_lines`` early-return below would
    # then fire on every cycle, the cursor would never move, and each
    # subsequent append would be silently skipped until the file regrew past
    # the stale line (the D-C3-class bug _sync_cursor.detect_jsonl_shrink
    # documents). Reset to 0 and full-re-scan; the insert is ON CONFLICT DO
    # NOTHING, so re-scanning already-synced rows is cheap and idempotent.
    #
    # Computed inline against ``total_lines`` (not via detect_jsonl_shrink) on
    # purpose: the cursor is SAVED as the ``splitlines()`` count below
    # (``save_cursor(total_lines)``) and the slice ``lines[cursor_line:]`` uses
    # the same list, so the shrink test must use that same count. The helper
    # counts lines by file-handle iteration, which diverges from ``splitlines()``
    # on embedded Unicode line separators (U+2028/U+2029/U+0085/…) and would
    # fire a spurious shrink every cycle once such a char survives an
    # ``ensure_ascii=False`` rewrite.
    if cursor_line > total_lines:
        logger.warning(
            "Canonical JSONL shrank below the sync cursor (cursor=%d, "
            "total=%d) — resetting cursor to 0 for a full re-scan "
            "(ON CONFLICT DO NOTHING).",
            cursor_line, total_lines,
        )
        cursor_line = 0

    if cursor_line >= total_lines:
        logger.info("No new memories to sync (cursor=%d, total=%d)", cursor_line, total_lines)
        # Freshness marker advances even on no-op — downstream /recall
        # uses this to distinguish "recently confirmed empty" from
        # "haven't checked in N hours".
        save_sync_timestamp()
        # Nothing to do. NOT "completed": this run has learnt nothing
        # about any standing gate, and calling it complete cleared a
        # quarantine warning on the next five-minute tick (finding C1).
        return CycleResult(CYCLE_IDLE, connected=lock_connected)

    new_lines = lines[cursor_line:]
    logger.info(
        "Processing lines %d–%d (%d new)",
        cursor_line + 1, total_lines, len(new_lines),
    )

    # Parse records. We keep both the original dict (for quarantine on
    # unexpected drop) and the INSERT tuple (for psycopg2), indexed by id.
    # Poison records (malformed JSON, missing required fields) are
    # quarantined here so the cursor can advance past them without
    # silently losing data — see audit IC2 / B-C4.
    records: list[tuple] = []
    parsed_by_id: dict[str, dict[str, Any]] = {}
    poison_count = 0
    poison_written = 0  # for the log line below; the gate re-derives its own
    for offset, line in enumerate(new_lines):
        line_number = cursor_line + offset + 1  # 1-based for logging
        parsed, failure_reason = classify_jsonl_line(line, line_number, logger)
        if parsed is not None:
            records.append(record_to_tuple(parsed))
            parsed_by_id[parsed["id"]] = parsed
        elif failure_reason is not None:
            # Poison record: quarantine the raw line + line number so an
            # operator can repair the canonical and replay if needed.
            status = quarantine_record(
                QUARANTINE_FILE,
                {
                    "line_number": line_number,
                    "raw_line": line.rstrip("\n"),
                },
                failure_reason,
                logger=logger,
            )
            poison_count += 1
            if status == QUARANTINE_WRITTEN:
                # Diagnostic only: the gate derives its number from the
                # file itself now, so this is for the log (finding C1).
                poison_written += 1
        # else: blank line — legitimate skip, no quarantine.

    if not records:
        # No valid records — but we still advance the cursor IF every
        # skipped line was either blank or successfully quarantined as
        # poison. Without quarantine the corrupt block would be silently
        # skipped and never re-enter the sync pipeline (audit IC2).
        if poison_count:
            logger.warning(
                "No valid records in slice; %d poison line(s) quarantined "
                "to %s. Advancing cursor past the poisoned slice.",
                poison_count, QUARANTINE_FILE,
            )
        else:
            logger.info("No valid records to insert (slice was blank-only)")
        save_cursor(total_lines, expect_present=cursor_key_was_present)
        # Poison lines were quarantined at the parse layer, before any
        # database contact — nothing was processed and nothing is known
        # about connectivity.
        return CycleResult(CYCLE_IDLE, connected=lock_connected)

    # Insert into PostgreSQL (returns InsertResult with full accounting).
    result = insert_memories(
        records, logger, quarantine_cap, quarantine_anyway,
    )

    # Cursor advance policy (#55, refined by audit round two finding P2):
    # advance ONLY when we have positive evidence every input row is
    # accounted for. Specifically:
    #   - the DB was reachable, AND
    #   - no ids fell through pre-flight, RETURNING, *and* quarantine.
    # A record the database explicitly refused is accounted for by its
    # quarantine entry; one that vanished without explanation is not.
    outcome = CYCLE_COMPLETED
    if not result.db_available:
        logger.warning(
            "Insert could not reach PostgreSQL — cursor NOT advanced. "
            "This is an outage, not a data problem; the next tick retries."
        )
        # Nothing was learnt about any standing fault, so the gate stays —
        # but the outage counter moves, and three in a row raise a gate of
        # their own (finding M4).
        outcome = CYCLE_OUTAGE
    elif result.unexpected_drops:
        dropped_records = [
            parsed_by_id[mid]
            for mid in result.unexpected_drops
            if mid in parsed_by_id
        ]
        _write_quarantine(dropped_records, logger)
        logger.error(
            "Cursor NOT advanced — %d id(s) were silently dropped by "
            "ON CONFLICT. Dropped ids: %s",
            len(result.unexpected_drops),
            result.unexpected_drops[:10],
        )
        return CycleResult(
            CYCLE_DEGRADED,
            connected=True,
            degraded_detail=(
                f"[sync-to-postgres.py] {len(result.unexpected_drops)} "
                f"memory id(s) were silently dropped by ON CONFLICT and "
                f"the cursor is HELD. Nothing new syncs until this is "
                f"understood; the ids are in logs/sync.log."
            ),
        )
    else:
        if result.quarantined:
            logger.error(
                "PostgreSQL refused %d record(s) on content grounds; they "
                "are quarantined in %s and the cursor advances past them. "
                "Repair the canonical and replay from the quarantine. "
                "First 10: %s",
                len(result.quarantined), QUARANTINE_FILE,
                list(result.quarantined[:10]),
            )
        save_cursor(total_lines, expect_present=cursor_key_was_present)
        save_sync_timestamp()
        logger.info("Cursor advanced to line %d", total_lines)

    # Best-effort embedding of memories with NULL embeddings.
    # Processes up to EMBED_BATCH_SIZE per sync cycle (~100ms overhead).
    if HAS_EMBED:
        _update_embeddings(logger)

    return CycleResult(
        outcome,
        processed=result.inserted + result.expected_dupes,
        connected=result.db_available,
    )


def _acknowledge_quarantine(logger: logging.Logger) -> int:
    """
    Lower the quarantine problem, and do nothing else. Returns an exit code.

    A STATE-ONLY operation (sixth re-audit, finding C1). It runs no sync,
    takes no advisory lock, and touches no database.

    Records the POSITION in the append-only quarantine file rather than a
    count, so rows quarantined after this moment are still reported
    (eighth re-audit, finding C1). A file whose length cannot be read is
    therefore a refusal, not a no-op: recording an unknown position would
    either dismiss rows nobody has seen or silently do nothing while
    reporting success (ninth re-audit, finding M3).

    The verdict comes from BOTH artefacts on disk afterwards — the
    sidecar and the rendered gate (eighth re-audit, finding M3). A write
    that half-succeeded used to report success or "nothing changed",
    while the other half still said the opposite.
    """
    before, status = read_state_with_status(GATE_FILE, logger)
    if status == STATE_CORRUPT:
        # A corrupt sidecar reads as "no problems", which is
        # indistinguishable from a clean one — say which it is rather
        # than reporting nothing to do (eighth re-audit, low). An ABSENT
        # sidecar is not corrupt: on a healthy pipeline that has nothing
        # to report there is simply nothing there, and calling it corrupt
        # made every ack on a working machine exit 9 (ninth re-audit,
        # finding M2).
        logger.error(
            "The gate state %s exists but could not be read. Refusing to "
            "report on a quarantine problem whose state is unknown; fix "
            "or delete the file and re-run.", state_path_for(GATE_FILE),
        )
        return 9
    if PROBLEM_QUARANTINE not in before.problems:
        logger.info(
            "--ack-quarantine: there is no standing quarantine problem to "
            "clear. Nothing to do."
        )
        return 0

    # Only now that there is something to clear does an unreadable
    # quarantine file matter. Checking it first turned every ack on a
    # machine that has never quarantined anything into an exit 9.
    entries = count_quarantine_entries(QUARANTINE_FILE)
    if entries is None:
        logger.error(
            "--ack-quarantine could not read the quarantine file %s, so "
            "it cannot record how far you have read. The standing problem "
            "is UNCHANGED. Check that the data submodule is mounted and "
            "the file is readable, then run this again.", QUARANTINE_FILE,
        )
        return 9

    standing = before.problems[PROBLEM_QUARANTINE].count
    apply_gate(
        GateEvent(
            outcome=CYCLE_ACK,
            quarantine_entries=entries,
            script=SCRIPT_NAME,
        ),
        gate_path=GATE_FILE,
        logger=logger,
    )

    after = read_state_safely(GATE_FILE, logger)
    sidecar_cleared = PROBLEM_QUARANTINE not in after.problems
    # Compare the file with what this state renders to, rather than
    # hunting for a word in the problem text: a substring sentinel stops
    # working the day the wording improves (ninth re-audit, low).
    gate_cleared = gate_matches_state(GATE_FILE, after)

    if not sidecar_cleared:
        logger.error(
            "--ack-quarantine did NOT clear the quarantine problem: the "
            "gate state on disk still carries it. Nothing has changed; "
            "see the errors above."
        )
        return 9
    if not gate_cleared:
        logger.error(
            "--ack-quarantine updated the gate state but could NOT "
            "re-render %s, which no longer matches it. The state is "
            "correct, so the next run of this script repairs the gate "
            "file; until then session start shows a problem that is "
            "already dismissed.", GATE_FILE,
        )
        return 9
    logger.warning(
        "--ack-quarantine: cleared a quarantine problem covering %d row(s). "
        "The rows themselves are still in %s and still absent from "
        "PostgreSQL; this only dismisses the session-start warning.",
        standing, QUARANTINE_FILE,
    )
    return 0
def _gate_fault(
    logger: logging.Logger,
    detail: str,
    *,
    connected: bool | None = None,
    correlated: bool = False,
    reset_quarantine_ack: bool = False,
) -> None:
    """Raise this script's fault (or correlated) problem and render the gate.

    One helper so every exit path goes through the same state machine and
    none of them can invent its own gate semantics.
    """
    apply_gate(
        GateEvent(
            outcome=CYCLE_DEGRADED,
            connected=connected,
            correlated_detail=detail if correlated else None,
            fault_detail=None if correlated else detail,
            reset_quarantine_ack=reset_quarantine_ack,
            quarantine_entries=count_quarantine_entries(QUARANTINE_FILE),
            quarantine_file=QUARANTINE_FILE,
            # Record where the cursor has ended up, even on the way out.
            # Exit 6 IS a rebuild, so leaving the pre-rebuild position
            # recorded made the very next run see the same rewind again
            # and repeat the "cursor was reset" sentence over rows it had
            # already reported (tenth re-audit, low L5).
            cursor_seen=reset_quarantine_ack,
            cursor_position_after=(
                normalise_line_cursor(
                    read_cursor_file_locked(CURSOR_FILE).get(
                        "postgres_sync_line",
                    ),
                    key="postgres_sync_line", logger=logger,
                )
                if reset_quarantine_ack else None
            ),
            script=SCRIPT_NAME,
        ),
        gate_path=GATE_FILE,
        logger=logger,
    )


def main() -> None:
    """Entry point.

    Exit codes:
        0 - ran to completion (possibly syncing nothing)
        1 - unexpected error
        2 - schema-version mismatch
        4 - environment fault: PostgreSQL is reachable but not in the
            expected state (permissions, a missing table or column, an
            aborted transaction), or refused far more rows than a data
            problem explains. Nothing was quarantined; the cursor held.
        6 - a rebuild removed this sync's cursor key mid-run; the position
            was deliberately not written back
    """
    parser = argparse.ArgumentParser(
        description="Sync memories from the canonical JSONL to PostgreSQL",
    )
    parser.add_argument(
        "--quarantine-cap", type=int, default=None,
        help=(
            "Stop and report an environment fault once this many rows have "
            f"been refused in one run (default: {DEFAULT_QUARANTINE_CAP}, or "
            f"${QUARANTINE_CAP_ENV_VAR}). 0 means stop at the first refusal."
        ),
    )
    parser.add_argument(
        "--ack-quarantine", action="store_true",
        help=(
            "Clear the standing quarantine problem from the session-start "
            "gate. Says you have looked at the quarantined rows; it does "
            "not replay them."
        ),
    )
    parser.add_argument(
        "--quarantine-anyway", action="store_true",
        help=(
            "Quarantine a batch that was wholly refused with one SQLSTATE "
            "instead of holding the cursor. Use once, after checking the "
            "schema. Also settable as $PA_PG_QUARANTINE_ANYWAY=1."
        ),
    )
    args = parser.parse_args()

    logger = setup_logging()
    if args.ack_quarantine:
        # State only: no sync, no advisory lock, no database (finding C1).
        sys.exit(_acknowledge_quarantine(logger))
    logger.info("Starting sync")
    try:
        cycle = sync(
            logger, args.quarantine_cap, args.quarantine_anyway,
        )
    except QuarantineCapExceeded as exc:
        # Not an environment fault: the database is fine, there are just
        # too many refusals to skip without someone looking.
        logger.error("QUARANTINE CAP EXCEEDED — %s", exc)
        _gate_fault(
            logger,
            f"[sync-to-postgres.py] exit 7 — {exc} Raise the ceiling with "
            f"$PA_PG_QUARANTINE_CAP or --quarantine-cap once you have "
            f"looked at why so many memories are being refused.",
            connected=True,
        )
        sys.exit(7)
    except CorrelatedRefusal as exc:
        # Ambiguous between poison and a schema fault, so it is named as
        # ambiguous and the escape hatch is spelt out.
        logger.error("CORRELATED REFUSAL — %s", exc)
        _gate_fault(
            logger,
            f"[sync-to-postgres.py] exit 4 — {exc} Either correlated poison or a "
            f"schema fault (a migration adding a NOT NULL column, a "
            f"unique index the upsert does not name). Check the schema; "
            f"if the rows really are poison, run exactly: "
            f"~/personal-assistant/venv/bin/python3 "
            f"~/personal-assistant/scripts/sync-to-postgres.py --quarantine-anyway",
            connected=True, correlated=True,
        )
        sys.exit(4)
    except EnvironmentFault as exc:
        # Reachable database, wrong state: permissions, a missing table or
        # column, an aborted transaction. Retrying cannot help.
        logger.error("ENVIRONMENT FAULT — %s", exc)
        logger.error(
            "Fix the database (grants, schema, migration state) and re-run. "
            "No memory was quarantined and the cursor did not move."
        )
        _gate_fault(
            logger,
            f"[sync-to-postgres.py] exit 4 — environment fault: {exc} Cursor held, "
            f"nothing quarantined; the sync is making no progress until "
            f"this is fixed.",
            connected=True,
        )
        sys.exit(4)
    except CursorKeyVanished as exc:
        # A rebuild cleared the cursors while this cycle was running.
        logger.error("CURSOR RESET MID-RUN — %s", exc)
        _gate_fault(
            logger,
            f"[sync-to-postgres.py] exit 6 — a rebuild cleared the sync cursor "
            f"mid-run, so this run's position was deliberately not "
            f"written back. Confirm the rebuild was intended, then let "
            f"the next run replay from the canonical.",
            connected=True,
            # A rebuild will re-offer every row, so any refusal of them
            # is new: forget what was acknowledged, or the second refusal
            # of the same rows falls silently below the mark (eighth
            # re-audit, finding C1).
            reset_quarantine_ack=True,
        )
        sys.exit(6)
    except SystemExit as exc:
        # assert_schema_version exits 2 from deep inside the call stack,
        # and SystemExit is a BaseException, so it sails past the handler
        # below unless it is caught here.
        if exc.code not in (0, None):
            _gate_fault(
                logger,
                f"[sync-to-postgres.py] exit {exc.code} — the sync stopped before "
                f"doing any work. Exit 2 is a schema-version mismatch: "
                f"the script and the database disagree about the shape of "
                f"the tables. Nothing was synced.",
            )
        raise
    except Exception as exc:
        logger.error("Unexpected error: %s", exc, exc_info=True)
        # An unexpected exception is a fault the operator must see: the
        # sync is dead in a way nobody anticipated and will stay dead
        # every five minutes until someone looks.
        _gate_fault(
            logger,
            f"[sync-to-postgres.py] exit 1 — UNEXPECTED ERROR: "
            f"{type(exc).__name__}: {exc} The sync is not running at "
            f"all; see the traceback in the log.",
        )
        sys.exit(1)

    if args.quarantine_anyway and cycle.outcome == CYCLE_CONTENDED:
        # The override is per-run and was NOT applied: another instance
        # held the lock. Reporting success would leave the operator
        # believing they had cleared the batch.
        logger.error(
            "--quarantine-anyway was requested but another instance held "
            "the advisory lock, so this run did nothing and the override "
            "was not applied. Re-run it."
        )
        _gate_fault(
            logger,
            "[sync-to-postgres.py] exit 8 — --quarantine-anyway did not run: another "
            "instance held the advisory lock. The batch is still held; "
            "re-run the override.",
            connected=True,
        )
        sys.exit(8)

    if cycle.outcome == CYCLE_CONTENDED:
        # A contended run did nothing: it must not so much as read the
        # gate state, let alone write it (finding C2).
        logger.info("Another instance holds the lock — gate untouched.")
        return

    apply_gate(
        GateEvent(
            outcome=cycle.outcome,
            connected=cycle.connected,
            processed=cycle.processed,
            # Observed, not accumulated: the gate derives the standing
            # problem from the file every run (finding C1).
            quarantine_entries=count_quarantine_entries(QUARANTINE_FILE),
            quarantine_file=QUARANTINE_FILE,
            degraded_detail=cycle.degraded_detail,
            # Where the cursor stood when the cycle started, so the gate
            # can see a rebuild that rewound or removed it — which is the
            # only trace an ordinary rebuild leaves (ninth re-audit, C2).
            cursor_position=cycle.cursor_position,
            cursor_position_after=cycle.cursor_position_after,
            cursor_seen=cycle.cursor_seen,
            script=SCRIPT_NAME,
        ),
        gate_path=GATE_FILE,
        logger=logger,
    )
    logger.info("sync complete (outcome=%s)", cycle.outcome)


if __name__ == "__main__":
    main()
