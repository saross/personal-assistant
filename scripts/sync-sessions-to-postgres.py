#!/usr/bin/env python3
"""
Sync session metadata from cc-archives to PostgreSQL query layer.

Walks ~/cc-archives/ for session.meta.json files, parses metadata,
and upserts into the sessions table. Uses ON CONFLICT ... DO UPDATE
so that enriched sessions (e.g. after cc-session update) are reflected.

Canonical source: session.meta.json files in the archive tree.
PostgreSQL is a derived query layer that can be rebuilt at any time.

Designed to run via hook (chained after archive) or manually.

Usage:
    venv/bin/python3 scripts/sync-sessions-to-postgres.py
    venv/bin/python3 scripts/sync-sessions-to-postgres.py --archive-root /path/to/archives
    venv/bin/python3 scripts/sync-sessions-to-postgres.py --full-resync

Exit codes:
    0 - ran to completion (possibly syncing nothing)
    1 - unexpected error
    2 - schema-version mismatch
    4 - environment fault: PostgreSQL is reachable but not in the expected
        state (permissions, a missing table or column, an aborted
        transaction), or refused far more rows than a data problem
        explains. Nothing was quarantined and the cursor did not move.
    6 - a rebuild removed this sync's cursor key mid-run; the position was
        deliberately not written back
"""

import argparse
import json
import logging
from dataclasses import dataclass, replace
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, NamedTuple

# Shared quarantine helper (audit IC2 — quarantine-on-skip).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sync_cursor import (  # noqa: E402
    QUARANTINE_FAILED,
    QUARANTINE_WRITTEN,
    append_quarantine_entry,
    count_quarantine_entries,
    normalise_timestamp_cursor,
    CursorKeyVanished,
    quarantine_record,
    read_cursor_file,
    read_cursor_file_locked,
    update_cursor_file,
)
# Row-level Postgres guards (audit round two, finding P1 / lens A-X1+A-X2).
from _sync_gate import (  # noqa: E402
    CYCLE_COMPLETED,
    CYCLE_CONTENDED,
    CYCLE_DEGRADED,
    CYCLE_IDLE,
    CYCLE_ACK,
    CYCLE_OUTAGE,
    PROBLEM_QUARANTINE,
    STATE_CORRUPT,
    SESSIONS_GATE as _DEFAULT_GATE_FILE,
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
# Schema-version guard (audit IC5 / B-X1).
from _schema_version import assert_schema_version, SchemaVersionError  # noqa: E402

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ARCHIVE_ROOT = Path.home() / "cc-archives"
LOG_DIR = PA_DIR / "logs"
LOG_FILE = LOG_DIR / "sync-sessions.log"
CURSOR_FILE = PA_DIR / "memories" / "sync-cursors.json"
# Quarantine destination for rows silently dropped by the upsert. Lives
# in the data submodule but we do not commit submodule pointer changes
# as part of this fix (#55).
QUARANTINE_FILE = PA_DIR / "data" / "sessions" / "quarantine-postgres-drops.jsonl"
DB_NAME = "claude_memories"
# Session-start gate raised on exit 4 / 6 (re-audit finding C2). A module
# constant rather than the helper's default so tests can pin it to a tmp
# directory: a test that writes the real gate would put a fabricated
# problem in front of Shawn at his next session start.
SCRIPT_NAME = "sync-sessions-to-postgres.py"
GATE_FILE = _DEFAULT_GATE_FILE

CURSOR_KEY = "sessions_sync_timestamp"

# Advisory-lock key for serialising concurrent sessions-sync runs.
# Distinct from the memories sync so the two scripts can run in parallel
# against the same database without contending.
ADVISORY_LOCK_KEY = "sync-sessions-to-postgres"


# ============================================================================
# Logging
# ============================================================================

def setup_logging() -> logging.Logger:
    """Configure logging to file and stderr."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sync-sessions-to-postgres")
    logger.setLevel(logging.INFO)

    # File handler
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    # Stderr handler (for hook error capture)
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
# Cursor management (shared file with memory sync)
# ============================================================================

def load_cursor() -> str:
    """
    Load the last sync timestamp from the cursor file.

    Returns ISO timestamp string. Defaults to epoch if no cursor exists.

    The sync cycle itself does NOT use this: it needs the timestamp and
    the key's presence from one atomic observation, so it reads the whole
    object once under the lock (low finding L1). This remains for
    diagnostics.
    """
    return str(read_cursor_file(CURSOR_FILE).get(
        CURSOR_KEY, "2000-01-01T00:00:00Z",
    ))


def save_cursor(timestamp: str, *, expect_present: bool = False) -> None:
    """Save the current sync timestamp to the shared cursor file.

    Routed through :func:`_sync_cursor.update_cursor_file` (audit round
    two, finding P16): this file is shared with ``sync-to-postgres.py``,
    ``sync-to-zotero.py``, and ``rebuild-postgres.py``, so the
    read-modify-write cycle runs under an exclusive flock and the write is
    temp-file + ``os.replace``. Previously a plain ``write_text`` could
    interleave with the memories sync and lose one of the two advances.

    ``expect_present`` makes the write a compare-and-set against a
    concurrent rebuild: pass whether the key was in the snapshot
    :func:`_sync_locked` read at the start of the cycle (re-audit
    finding M3).
    """
    update_cursor_file(
        CURSOR_FILE, {CURSOR_KEY: timestamp},
        expect_present=(CURSOR_KEY,) if expect_present else (),
    )


# ============================================================================
# Archive discovery
# ============================================================================

def find_session_metadata(
    archive_root: Path,
    since: str | None = None,
    logger: logging.Logger | None = None,
) -> list[tuple[Path, dict[str, Any]]]:
    """
    Walk the archive tree and return parsed session.meta.json files.

    If ``since`` is provided (ISO timestamp), only returns sessions
    archived after that timestamp (based on archive.archived_at).

    Returns list of (meta_path, metadata_dict) tuples.
    """
    results = []
    if not archive_root.exists():
        if logger:
            logger.warning("Archive root does not exist: %s", archive_root)
        return results

    for meta_path in sorted(archive_root.rglob("session.meta.json")):
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            if logger:
                logger.warning("Failed to parse %s: %s", meta_path, exc)
            continue

        # Filter by archived_at timestamp if cursor provided.
        # Normalise Z → +00:00 for consistent lexicographic comparison.
        if since:
            archived_at = metadata.get("archive", {}).get("archived_at", "")
            if archived_at:
                normalised = archived_at.replace("Z", "+00:00")
                since_normalised = since.replace("Z", "+00:00")
                if normalised <= since_normalised:
                    continue

        results.append((meta_path, metadata))

    return results


# ============================================================================
# Metadata extraction
# ============================================================================

def archive_root_is_populated(archive_root: Path) -> bool:
    """
    Return True when the archive root holds at least one session metadata
    file.

    Short-circuits on the first hit, and is only ever called on the
    no-new-sessions path, so the extra walk costs nothing in the ordinary
    case. Distinguishes "a quiet week" from "the disk is not mounted",
    which is the difference between an idle cycle and a degraded one
    (fourth re-audit, finding C2).
    """
    return next(archive_root.rglob("session.meta.json"), None) is not None


def metadata_to_row(
    meta_path: Path,
    metadata: dict[str, Any],
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """
    Extract a flat row dict from a session.meta.json structure.

    Maps nested metadata fields to the sessions table columns.

    This is the ingest boundary for the sessions sync, so it is where NUL
    characters are stripped (audit round two, finding P1 / lens A-X2).
    LLM-generated narrative in ``statistics.subagents[].narrative`` has
    carried a NUL, and PostgreSQL rejects ``\\u0000`` inside the ``jsonb``
    ``raw_metadata`` column — which used to abort the whole batch and be
    misreported as an outage. Sanitising the whole document here also
    covers the derived TEXT columns (the three-Ps summaries), which draw
    from the same generated text.

    Args:
        meta_path: Path to the session.meta.json file (its parent becomes
            ``archive_path``).
        metadata: The parsed metadata document.
        logger: Optional logger; a warning is emitted when NULs were
            removed, so silent repair of archive content stays visible.
    """
    metadata, nuls_removed = sanitise_nuls(metadata)
    if nuls_removed and logger is not None:
        logger.warning(
            "Removed %d NUL character(s) from %s before syncing — "
            "PostgreSQL cannot store U+0000 in text or jsonb.",
            nuls_removed, meta_path,
        )

    # Use `or {}` instead of default arg — .get() returns None (not the
    # default) when the key exists with a null/None value.
    session = metadata.get("session") or {}
    project = metadata.get("project") or {}
    model = metadata.get("model") or {}
    stats = metadata.get("statistics") or {}
    tokens = stats.get("tokens") or {}
    tool_calls = stats.get("tool_calls") or {}
    auto = metadata.get("auto_generated") or {}
    three_ps = metadata.get("three_ps") or {}
    archive = metadata.get("archive") or {}

    # Use auto_generated three_ps if top-level is empty
    auto_three_ps = auto.get("three_ps", {})
    prompt_summary = three_ps.get("prompt_summary") or auto_three_ps.get("prompt_summary", "")
    process_summary = three_ps.get("process_summary") or auto_three_ps.get("process_summary", "")
    provenance_summary = (
        three_ps.get("provenance_summary") or auto_three_ps.get("provenance_summary", "")
    )

    # Archive path: the directory containing session.meta.json
    archive_path = str(meta_path.parent)

    # Sub-agent rollup (v1.2 schema). Pre-v1.2 archives lack
    # subagents_summary; default to zero so the typed columns are
    # always populated.
    subagents_summary = stats.get("subagents_summary") or {}
    subagent_count = subagents_summary.get("count", 0) or 0
    subagent_total_cost_usd = (
        subagents_summary.get("estimated_cost_usd", 0.0) or 0.0
    )

    return {
        # ``or`` rather than a .get default on both of these: the keys
        # exist with a null value in malformed metadata, and .get returns
        # that None rather than the default (the hazard the comment above
        # names). ``sessions.project`` is TEXT NOT NULL, so a None there
        # is an IntegrityError that used to halt the cursor permanently
        # (audit round two, finding P10 / lens A-M8).
        "id": session.get("id") or "",
        "project": project.get("name") or "unknown",
        "project_directory": project.get("directory"),
        "title": auto.get("title"),
        "purpose": auto.get("purpose"),
        "tags": auto.get("tags", []),
        "started_at": session.get("started_at"),
        "ended_at": session.get("ended_at"),
        "duration_minutes": session.get("duration_minutes"),
        "model_provider": model.get("provider"),
        "model_id": model.get("model_id"),
        "turns": stats.get("turns"),
        "human_messages": stats.get("human_messages"),
        "assistant_messages": stats.get("assistant_messages"),
        "thinking_blocks": stats.get("thinking_blocks"),
        "tool_calls": tool_calls.get("total") if isinstance(tool_calls, dict) else tool_calls,
        "tokens_input": tokens.get("input"),
        "tokens_output": tokens.get("output"),
        "tokens_cache_read": tokens.get("cache_read"),
        "tokens_cache_creation": tokens.get("cache_creation"),
        "estimated_cost_usd": stats.get("estimated_cost_usd"),
        "prompt_summary": prompt_summary,
        "process_summary": process_summary,
        "provenance_summary": provenance_summary,
        "archive_path": archive_path,
        "capture_type": archive.get("capture_type"),
        "subagent_count": subagent_count,
        "subagent_total_cost_usd": subagent_total_cost_usd,
        "raw_metadata": json.dumps(metadata),
    }


# ============================================================================
# Database operations
# ============================================================================

class InsertResult(NamedTuple):
    """
    Accounting result for a session upsert batch.

    Attributes:
        input_count: Number of rows attempted after within-batch dedup
            (see ``duplicates_within_batch``).
        inserted: Number of rows returned by the upsert (should equal
            input_count under DO UPDATE — any shortfall is anomalous).
        expected_dupes: Always 0 for DO UPDATE — kept for shape parity
            with the memory sync's InsertResult so callers can share
            logic if needed later.
        unexpected_drops: Ids in the input that did not appear in
            RETURNING. Under DO UPDATE these should never exist;
            anything here is a hard stop (#55).
        db_available: False when we could not *reach* the database. A row
            the database refused is NOT an outage — see ``quarantined``.
        duplicates_within_batch: Input rows that shared an id with
            another row in the same batch; the last occurrence won.
        quarantined: Ids PostgreSQL refused on content grounds (bad
            timestamp, NUL, wrong type, NOT NULL violation). They have
            been written to the quarantine file, so the caller may
            advance the cursor past them: they are accounted for, not
            lost (audit round two, finding P1 / lens A-X1).
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
    already holds the lock. The lock auto-releases when the backing
    connection closes. If psycopg2 is missing or the database is
    unreachable, yields True unconditionally — the upsert path handles
    those cases and leaves the cursor alone (#55).
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

    # Schema-version guard (audit IC5).
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
        conn.commit()
        if not acquired:
            logger.warning(
                "Another sessions-sync holds the advisory lock for %r — "
                "skipping this cycle. Will retry on next invocation.",
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
        conn.close()


def _load_quarantined_ids() -> set[str]:
    """
    Return the set of ids already present in the quarantine JSONL.

    Used to avoid appending duplicate rows on repeated sync runs
    against a halted cursor.
    """
    if not QUARANTINE_FILE.exists():
        return set()
    ids: set[str] = set()
    with QUARANTINE_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            # Two shapes live in this one file. ``_write_quarantine``
            # appends the bare row, so the id is at the top level;
            # ``_sync_cursor.quarantine_record`` wraps it as
            # ``{"reason", "quarantined_at", "record"}``, so the id is
            # one level down. Reading only the first shape meant the
            # dedup could not see entries written by the second
            # (re-audit, low finding).
            for candidate in (rec, rec.get("record")):
                if isinstance(candidate, dict):
                    sid = candidate.get("id")
                    if isinstance(sid, str):
                        ids.add(sid)
    return ids


def _write_quarantine(
    dropped_rows: list[dict[str, Any]],
    logger: logging.Logger,
) -> None:
    """
    Append dropped session rows to the quarantine JSONL.

    Creates parent directories and the file if missing. Deduplicates
    against already-quarantined ids so repeated runs against a halted
    cursor do not grow the file linearly.
    """
    already = _load_quarantined_ids()
    new_rows = [r for r in dropped_rows if r.get("id") not in already]
    if not new_rows:
        logger.info(
            "All %d dropped session row(s) already in quarantine — "
            "no new appends",
            len(dropped_rows),
        )
        return
    skipped = len(dropped_rows) - len(new_rows)
    # Through the SHARED appender, which repairs a missing separator
    # before it writes. Appending here directly ran this row onto the end
    # of a complete row whose newline had been lost, and both then
    # vanished from every reader at once (eleventh re-audit, C1).
    for row in new_rows:
        if not append_quarantine_entry(QUARANTINE_FILE, row):
            logger.error(
                "Could not write quarantine file %s — %d session(s) are "
                "unaccounted for", QUARANTINE_FILE, len(new_rows),
            )
            return
    if skipped:
        logger.info(
            "Quarantined %d new session(s) (skipped %d already present) "
            "to %s", len(new_rows), skipped, QUARANTINE_FILE,
        )
    else:
        logger.info(
            "Quarantined %d unexpectedly-dropped session(s) to %s",
            len(new_rows), QUARANTINE_FILE,
        )


def _quarantine_refused_rows(
    poison: list[tuple[str, str]],
    rows_by_id: dict[str, dict[str, Any]],
    logger: logging.Logger,
) -> tuple[list[str], list[str]]:
    """
    Write every row PostgreSQL refused on content grounds to quarantine.

    Parameters
    ----------
    poison:
        ``(session id, error message)`` pairs from the per-row replay.
    rows_by_id:
        The deduped input rows, so the full row can be quarantined for
        replay after the metadata is repaired.
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
        advance: a quarantine write that failed leaves the row
        unaccounted for, so it stays in ``unexpected_drops`` and
        halts the cursor instead (audit IC2's contract).
    """
    quarantined: list[str] = []
    newly_written: list[str] = []
    for session_id, message in poison:
        status = quarantine_record(
            QUARANTINE_FILE,
            {
                "id": session_id,
                "postgres_error": message,
                "row": rows_by_id.get(session_id),
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
            newly_written.append(session_id)
        if status != QUARANTINE_FAILED:
            quarantined.append(session_id)
        else:
            logger.error(
                "Could not quarantine refused session %s — holding the "
                "cursor rather than skipping it.", session_id,
            )
    return quarantined, newly_written


def upsert_sessions(
    rows: list[dict[str, Any]],
    logger: logging.Logger,
    quarantine_cap: int | None = None,
    quarantine_anyway: bool = False,
) -> InsertResult:
    """
    Upsert session rows into PostgreSQL with full accounting.

    Uses ON CONFLICT (id) DO UPDATE so enriched metadata (e.g. after
    cc-session update) replaces the previous version. The RETURNING
    clause captures every id PG touched; anything missing from that set
    is an unexpected drop (#55).

    Failure handling splits two cases that were previously conflated
    (audit round two, finding P1 / lens A-X1):

    * The database is unreachable — ``db_available=False``, the caller
      holds the cursor, and the next cron tick retries.
    * The database refused a row's *content* — the batch is replayed one
      row at a time so the healthy rows still land, and the offending
      rows are quarantined so the cursor can advance past them.

    Reporting a content failure as an outage is what left the sessions
    table three weeks stale in September 2026 with "PostgreSQL may be
    down" in the log while PostgreSQL was up the whole time.
    """
    # Within-batch dedup: multiple metadata files for the same session
    # id would otherwise let only the last one "win" via ON CONFLICT DO
    # UPDATE, misleadingly flagging the earlier occurrences as drops.
    # Collapse to the last occurrence explicitly.
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = row.get("id")
        if sid:
            by_id[sid] = row
    deduped_rows = list(by_id.values())
    duplicates_within_batch = len(rows) - len(deduped_rows)
    input_count = len(deduped_rows)

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

    columns = [
        "id", "project", "project_directory", "title", "purpose", "tags",
        "started_at", "ended_at", "duration_minutes",
        "model_provider", "model_id",
        "turns", "human_messages", "assistant_messages",
        "thinking_blocks", "tool_calls",
        "tokens_input", "tokens_output",
        "tokens_cache_read", "tokens_cache_creation",
        "estimated_cost_usd",
        "prompt_summary", "process_summary", "provenance_summary",
        "archive_path", "capture_type",
        "subagent_count", "subagent_total_cost_usd",
        "raw_metadata",
    ]

    # Build the UPDATE SET clause (exclude id from updates)
    update_cols = [c for c in columns if c != "id"]
    update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    # Also update synced_at on conflict
    update_set += ", synced_at = NOW()"

    upsert_sql = f"""
        INSERT INTO sessions ({', '.join(columns)})
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET {update_set}
        RETURNING id
    """

    # Convert deduped rows to tuples in column order
    values = [tuple(row[c] for c in columns) for row in deduped_rows]
    input_ids = [row["id"] for row in deduped_rows]

    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError as exc:
        logger.warning("Cannot connect to PostgreSQL: %s", exc)
        logger.info(
            "PostgreSQL may be stopped — session.meta.json files remain canonical."
        )
        return InsertResult(
            input_count=input_count,
            inserted=0,
            expected_dupes=0,
            unexpected_drops=[],
            db_available=False,
            duplicates_within_batch=duplicates_within_batch,
        )

    # Schema-version guard (audit IC5).
    try:
        assert_schema_version(conn)
    except SchemaVersionError:
        conn.close()
        sys.exit(2)

    rows_by_id = {row["id"]: row for row in deduped_rows}

    try:
        returned_ids: set[str] = set()
        quarantined: list[str] = []
        newly: list[str] = []
        try:
            with conn:
                with conn.cursor() as cur:
                    returned = execute_values(
                        cur,
                        upsert_sql,
                        values,
                        page_size=50,
                        fetch=True,
                    )
                    returned_ids = {row[0] for row in returned}
        except (psycopg2.Error, ValueError, TypeError) as exc:
            verdict = classify_pg_error(exc, psycopg2)
            if verdict == OUTAGE:
                logger.warning("Cannot reach PostgreSQL during upsert: %s", exc)
                logger.info(
                    "PostgreSQL may be stopped — session.meta.json files "
                    "remain canonical; cursor held for the next run."
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
                # Nothing is wrong with the rows, so quarantining them
                # would discard good data and advance past it.
                raise EnvironmentFault(
                    f"PostgreSQL refused the upsert for a reason that is "
                    f"not about the data (SQLSTATE "
                    f"{getattr(exc, 'pgcode', None) or 'none'}, "
                    f"{type(exc).__name__}: {str(exc).strip()}). "
                    f"Cursor held; nothing quarantined. "
                    f"{environment_remedy(sqlstate_class(exc))}"
                ) from exc
            # Content failure, not an outage. ``execute_values`` sends the
            # whole page in one transaction, so a single refused row aborts
            # every other row with it; replay individually to find out which.
            logger.error(
                "Batch upsert refused by PostgreSQL (%s) — replaying %d row(s) "
                "individually to isolate the offending session(s).",
                str(exc).strip(), len(values),
            )
            returned_ids, poison, status, detail = insert_rows_individually(
                conn,
                upsert_sql,
                values,
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
                    expected_dupes=0,
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
                    f"more than {detail} session(s) were refused in one "
                    f"run. The database is fine and they may genuinely be "
                    f"poison, but quarantining that many would advance "
                    f"the cursor past every one of them. Cursor held; "
                    f"nothing quarantined."
                )
            if status == CORRELATED:
                raise CorrelatedRefusal(
                    f"every session in the batch was refused with the same "
                    f"SQLSTATE ({detail}) and not one landed. That is "
                    f"either correlated poison or a schema fault the row "
                    f"errors are a symptom of. Cursor held; nothing "
                    f"quarantined."
                )
            quarantined, newly = _quarantine_refused_rows(
                poison, rows_by_id, logger,
            )

        quarantined_set = set(quarantined)
        unexpected_drops = [
            mid for mid in input_ids
            if mid not in returned_ids and mid not in quarantined_set
        ]

        result = InsertResult(
            input_count=input_count,
            inserted=len(returned_ids),
            expected_dupes=0,
            unexpected_drops=unexpected_drops,
            db_available=True,
            duplicates_within_batch=duplicates_within_batch,
            quarantined=tuple(quarantined),
            newly_quarantined=len(newly),
        )

        # DEBUG on the happy path (nothing to notice); INFO when something
        # actually landed or when an anomaly surfaced.
        accounting_msg = (
            "Upsert accounting: input=%d inserted=%d unexpected_drops=%d "
            "dupes_in_batch=%d quarantined=%d"
        )
        accounting_args = (
            result.input_count, result.inserted,
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
                "Input batch contained %d within-batch duplicate session "
                "id(s); last occurrence won.",
                duplicates_within_batch,
            )
        if unexpected_drops:
            logger.error(
                "Unexpectedly dropped %d session id(s) — not returned "
                "by DO UPDATE. First 10: %s",
                len(unexpected_drops),
                unexpected_drops[:10],
            )
        return result
    finally:
        conn.close()


# ============================================================================
# Main sync logic
# ============================================================================

def sync(
    archive_root: Path,
    full_resync: bool,
    logger: logging.Logger,
    quarantine_cap: int | None = None,
    quarantine_anyway: bool = False,
) -> CycleResult:
    """
    Run one sync cycle: find new session.meta.json files, upsert into
    PostgreSQL, update cursor.

    Serialised against concurrent runs via a PG advisory lock; if another
    sessions-sync is in progress, this one exits without touching the
    cursor.

    Returns a :class:`CycleResult`: only a cycle that processed at least
    one session may lower this script's gate — absence of work is not
    evidence that a fault is gone (fourth re-audit, finding C1).
    """
    with _sync_advisory_lock(logger) as (acquired, connected):
        if not acquired:
            return CycleResult(CYCLE_CONTENDED, connected=connected)
        return _sync_locked(
            archive_root, full_resync, logger, quarantine_cap,
            quarantine_anyway, connected,
        )


def _sync_locked(
    archive_root: Path,
    full_resync: bool,
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
    started_at = normalise_timestamp_cursor(
        snapshot.get(CURSOR_KEY), key=CURSOR_KEY, logger=logger,
    )
    result = _sync_locked_body(
        archive_root, full_resync, logger, quarantine_cap,
        quarantine_anyway, lock_connected, snapshot, started_at,
    )
    ended_at = normalise_timestamp_cursor(
        read_cursor_file_locked(CURSOR_FILE).get(CURSOR_KEY),
        key=CURSOR_KEY, logger=logger,
    )
    return replace(
        result,
        cursor_position=started_at,
        cursor_position_after=ended_at,
        cursor_seen=True,
    )


def _sync_locked_body(
    archive_root: Path,
    full_resync: bool,
    logger: logging.Logger,
    quarantine_cap: int | None,
    quarantine_anyway: bool,
    lock_connected: bool | None,
    cursor_snapshot: dict,
    cursor_since: str | None,
) -> CycleResult:
    """The cycle itself, given the one locked cursor read above.

    ``cursor_since`` is the normalised timestamp from
    :func:`_sync_locked` — the same value the gate is given, so the two
    can never disagree about where the cursor stood (tenth re-audit,
    finding M1).

    Returns a :class:`CycleResult` — see :func:`sync`.
    """
    # One locked read for both facts — the timestamp and whether the key
    # was there at all (low finding L1). Two unlocked reads leave a window
    # in which a rebuild lands between them, defeating the compare-and-set
    # at save time (finding M3). The read itself now happens in
    # :func:`_sync_locked`, which passes the snapshot in so the cursor's
    # starting position can be reported to the gate.
    since = None if full_resync else (
        cursor_since or "2000-01-01T00:00:00Z"
    )
    cursor_key_was_present = CURSOR_KEY in cursor_snapshot
    if since:
        logger.info("Syncing sessions archived after %s", since)
    else:
        logger.info("Full resync — processing all sessions")

    # Find and parse metadata files
    sessions = find_session_metadata(archive_root, since=since, logger=logger)
    if not sessions:
        # "No new sessions" and "the archive is not there" look identical
        # from here, and the difference decides whether this run may
        # lower a gate (fourth re-audit, finding C2). An unmounted or
        # mistyped root yields an empty walk, and calling that a clean
        # cycle cleared a standing alarm every five minutes.
        if not archive_root.exists():
            logger.warning(
                "Archive root does not exist: %s — this run learnt "
                "nothing; leaving any standing gate alone.", archive_root,
            )
            return CycleResult(
                CYCLE_DEGRADED,
                degraded_detail=(
                    f"[sync-sessions-to-postgres.py] the archive root "
                    f"{archive_root} does not exist. No session can be "
                    f"synced — check the mount or the --archive-root path."
                ),
                connected=lock_connected,
            )
        if not archive_root_is_populated(archive_root):
            logger.warning(
                "Archive root %s contains no session.meta.json at all. "
                "That is a missing mount or the wrong path, not an empty "
                "week; leaving any standing gate alone.", archive_root,
            )
            return CycleResult(
                CYCLE_DEGRADED,
                degraded_detail=(
                    f"[sync-sessions-to-postgres.py] the archive root "
                    f"{archive_root} contains no session.meta.json at "
                    f"all — a missing mount or the wrong path, not an "
                    f"empty week. No session can be synced."
                ),
                connected=lock_connected,
            )
        logger.info("No new sessions to sync")
        return CycleResult(CYCLE_IDLE, connected=lock_connected)

    logger.info("Found %d session(s) to sync", len(sessions))

    # Convert to row dicts. Sessions whose metadata lacks an ``id`` are
    # quarantined here so the cursor can advance past them without
    # spamming the same warning every run forever (audit IC2 / B-M2).
    rows = []
    latest_archived_at = since or "2000-01-01T00:00:00Z"
    skipped_no_id = 0
    skipped_written = 0  # for the log line below; the gate re-derives its own
    for meta_path, metadata in sessions:
        # Capture archived_at *before* the id check so the cursor can
        # still advance past id-less sessions once they are quarantined.
        archived_at = metadata.get("archive", {}).get("archived_at", "")
        if archived_at:
            normalised = archived_at.replace("Z", "+00:00")
            latest_normalised = latest_archived_at.replace("Z", "+00:00")
            if normalised > latest_normalised:
                latest_archived_at = archived_at

        row = metadata_to_row(meta_path, metadata, logger)
        if not row["id"]:
            logger.warning("Session missing id in %s, quarantining", meta_path)
            status = quarantine_record(
                QUARANTINE_FILE,
                {
                    "meta_path": str(meta_path),
                    "metadata": metadata,
                },
                "missing_session_id",
                logger=logger,
            )
            skipped_no_id += 1
            if status == QUARANTINE_WRITTEN:
                # Diagnostic only: the gate derives its number from the
                # file itself now (finding C1).
                skipped_written += 1
            continue
        rows.append(row)

    if not rows:
        if skipped_no_id:
            # All discovered sessions were id-less and have been
            # quarantined. Advance the cursor so subsequent runs do not
            # rediscover the same poison files; the operator can replay
            # from the quarantine once the metadata is repaired.
            logger.warning(
                "No valid sessions to upsert; %d id-less session(s) "
                "quarantined to %s. Advancing cursor to %s.",
                skipped_no_id, QUARANTINE_FILE, latest_archived_at,
            )
            if latest_archived_at != (since or "2000-01-01T00:00:00Z"):
                save_cursor(
                    latest_archived_at,
                    expect_present=cursor_key_was_present,
                )
        else:
            logger.info("No valid sessions to upsert")
        # Id-less metadata was quarantined before any database contact.
        return CycleResult(CYCLE_IDLE, connected=lock_connected)

    # Upsert into PostgreSQL (returns InsertResult with full accounting).
    result = upsert_sessions(
        rows, logger, quarantine_cap, quarantine_anyway,
    )

    # Cursor advance policy (#55, refined by audit round two finding P1):
    # advance ONLY when the DB was reachable AND every input id is
    # accounted for — either returned by the upsert or explicitly
    # quarantined. A row the database *refused* is accounted for; a row
    # that vanished without explanation is not.
    outcome = CYCLE_COMPLETED
    if not result.db_available:
        logger.warning(
            "Upsert could not reach PostgreSQL — cursor NOT advanced. "
            "This is an outage, not a data problem; the next run retries."
        )
        # Nothing was learnt about any standing fault, so the gate stays —
        # but the outage counter moves, and three in a row raise a gate of
        # their own (finding M4).
        outcome = CYCLE_OUTAGE
    elif result.unexpected_drops:
        rows_by_id = {row["id"]: row for row in rows}
        dropped_rows = [
            rows_by_id[mid]
            for mid in result.unexpected_drops
            if mid in rows_by_id
        ]
        _write_quarantine(dropped_rows, logger)
        logger.error(
            "Cursor NOT advanced — %d session id(s) were silently dropped "
            "by the upsert. Dropped ids: %s",
            len(result.unexpected_drops),
            result.unexpected_drops[:10],
        )
        return CycleResult(
            CYCLE_DEGRADED,
            connected=True,
            degraded_detail=(
                f"[sync-sessions-to-postgres.py] "
                f"{len(result.unexpected_drops)} session id(s) were "
                f"silently dropped by the upsert and the cursor is HELD. "
                f"Nothing new syncs until this is understood; the ids are "
                f"in logs/sync-sessions.log."
            ),
        )
    else:
        if result.quarantined:
            logger.error(
                "PostgreSQL refused %d session(s) on content grounds; they "
                "are quarantined in %s and the cursor advances past them. "
                "Repair the metadata and replay from the quarantine. "
                "First 10: %s",
                len(result.quarantined), QUARANTINE_FILE,
                list(result.quarantined[:10]),
            )
        save_cursor(latest_archived_at, expect_present=cursor_key_was_present)
        logger.info("Cursor advanced to %s", latest_archived_at)

    return CycleResult(
        outcome,
        processed=result.inserted,
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
                normalise_timestamp_cursor(
                    read_cursor_file_locked(CURSOR_FILE).get(
                        CURSOR_KEY,
                    ),
                    key=CURSOR_KEY, logger=logger,
                )
                if reset_quarantine_ack else None
            ),
            script=SCRIPT_NAME,
        ),
        gate_path=GATE_FILE,
        logger=logger,
    )


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Sync session metadata from cc-archives to PostgreSQL",
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=DEFAULT_ARCHIVE_ROOT,
        help="Root directory for session archives (default: ~/cc-archives)",
    )
    parser.add_argument(
        "--full-resync",
        action="store_true",
        help="Ignore cursor and resync all sessions",
    )
    parser.add_argument(
        "--quarantine-cap", type=int, default=None,
        help=(
            "Stop and report an environment fault once this many sessions "
            f"have been refused in one run (default: "
            f"{DEFAULT_QUARANTINE_CAP}, or ${QUARANTINE_CAP_ENV_VAR}). "
            "0 means stop at the first refusal."
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
    logger.info("Starting session sync")
    try:
        cycle = sync(
            args.archive_root, args.full_resync, logger,
            args.quarantine_cap, args.quarantine_anyway,
        )
    except QuarantineCapExceeded as exc:
        # Not an environment fault: the database is fine, there are just
        # too many refusals to skip without someone looking.
        logger.error("QUARANTINE CAP EXCEEDED — %s", exc)
        _gate_fault(
            logger,
            f"[sync-sessions-to-postgres.py] exit 7 — {exc} Raise the ceiling with "
            f"$PA_PG_QUARANTINE_CAP or --quarantine-cap once you have "
            f"looked at why so many sessions are being refused.",
            connected=True,
        )
        sys.exit(7)
    except CorrelatedRefusal as exc:
        # Ambiguous between poison and a schema fault, so it is named as
        # ambiguous and the escape hatch is spelt out.
        logger.error("CORRELATED REFUSAL — %s", exc)
        _gate_fault(
            logger,
            f"[sync-sessions-to-postgres.py] exit 4 — {exc} Either correlated poison or a "
            f"schema fault (a migration adding a NOT NULL column, a "
            f"unique index the upsert does not name). Check the schema; "
            f"if the rows really are poison, run exactly: "
            f"~/personal-assistant/venv/bin/python3 "
            f"~/personal-assistant/scripts/sync-sessions-to-postgres.py --quarantine-anyway",
            connected=True, correlated=True,
        )
        sys.exit(4)
    except EnvironmentFault as exc:
        # Reachable database, wrong state: permissions, a missing table or
        # column, an aborted transaction. Retrying cannot help.
        logger.error("ENVIRONMENT FAULT — %s", exc)
        logger.error(
            "Fix the database (grants, schema, migration state) and re-run. "
            "No session was quarantined and the cursor did not move."
        )
        _gate_fault(
            logger,
            f"[sync-sessions-to-postgres.py] exit 4 — environment fault: {exc} Cursor held, "
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
            f"[sync-sessions-to-postgres.py] exit 6 — a rebuild cleared the sync cursor "
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
                f"[sync-sessions-to-postgres.py] exit {exc.code} — the sync stopped before "
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
            f"[sync-sessions-to-postgres.py] exit 1 — UNEXPECTED ERROR: "
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
            "[sync-sessions-to-postgres.py] exit 8 — --quarantine-anyway did not run: another "
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
    logger.info("session sync complete (outcome=%s)", cycle.outcome)


if __name__ == "__main__":
    main()
