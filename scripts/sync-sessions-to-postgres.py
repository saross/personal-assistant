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
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, NamedTuple

# Shared quarantine helper (audit IC2 — quarantine-on-skip).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sync_cursor import (  # noqa: E402
    CursorKeyVanished,
    quarantine_record,
    read_cursor_file,
    update_cursor_file,
)
# Row-level Postgres guards (audit round two, finding P1 / lens A-X1+A-X2).
from _pg_row_guard import (  # noqa: E402
    ENVIRONMENT,
    OUTAGE,
    EnvironmentFault,
    classify_pg_error,
    insert_rows_individually,
    sanitise_nuls,
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


# ============================================================================
# Cursor management (shared file with memory sync)
# ============================================================================

def load_cursor() -> str:
    """
    Load the last sync timestamp from the cursor file.

    Returns ISO timestamp string. Defaults to epoch if no cursor exists.
    """
    return str(read_cursor_file(CURSOR_FILE).get(
        CURSOR_KEY, "2000-01-01T00:00:00Z",
    ))


def cursor_key_present() -> bool:
    """Return whether this sync's cursor key is currently in the file.

    Read at the start of a cycle so :func:`save_cursor` can refuse to
    write a timestamp back if a rebuild removed the key in the meantime
    (re-audit finding M3).
    """
    return CURSOR_KEY in read_cursor_file(CURSOR_FILE)


def save_cursor(timestamp: str, *, expect_present: bool = False) -> None:
    """Save the current sync timestamp to the shared cursor file.

    Routed through :func:`_sync_cursor.update_cursor_file` (audit round
    two, finding P16): this file is shared with ``sync-to-postgres.py``,
    ``sync-to-zotero.py``, and ``rebuild-postgres.py``, so the
    read-modify-write cycle runs under an exclusive flock and the write is
    temp-file + ``os.replace``. Previously a plain ``write_text`` could
    interleave with the memories sync and lose one of the two advances.

    ``expect_present`` makes the write a compare-and-set against a
    concurrent rebuild — see :func:`cursor_key_present` and re-audit
    finding M3.
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


@contextmanager
def _sync_advisory_lock(logger: logging.Logger) -> Iterator[bool]:
    """
    Acquire a PostgreSQL session-scoped advisory lock for the sync cycle.

    Yields True when the sync should proceed, False when another sync
    already holds the lock. The lock auto-releases when the backing
    connection closes. If psycopg2 is missing or the database is
    unreachable, yields True unconditionally — the upsert path handles
    those cases and leaves the cursor alone (#55).
    """
    try:
        import psycopg2
    except ImportError:
        yield True
        return

    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError:
        yield True
        return

    # Schema-version guard (audit IC5).
    try:
        assert_schema_version(conn)
    except SchemaVersionError:
        conn.close()
        sys.exit(2)

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
            yield False
            return
        yield True
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
                sid = rec.get("id")
                if isinstance(sid, str):
                    ids.add(sid)
            except json.JSONDecodeError:
                continue
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
    try:
        QUARANTINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with QUARANTINE_FILE.open("a", encoding="utf-8") as f:
            for row in new_rows:
                f.write(json.dumps(row) + "\n")
        if skipped:
            logger.info(
                "Quarantined %d new session(s) (skipped %d already "
                "present) to %s",
                len(new_rows), skipped, QUARANTINE_FILE,
            )
        else:
            logger.info(
                "Quarantined %d unexpectedly-dropped session(s) to %s",
                len(new_rows), QUARANTINE_FILE,
            )
    except OSError as exc:
        logger.error(
            "Could not write quarantine file %s: %s", QUARANTINE_FILE, exc
        )


def _quarantine_refused_rows(
    poison: list[tuple[str, str]],
    rows_by_id: dict[str, dict[str, Any]],
    logger: logging.Logger,
) -> list[str]:
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
    list[str]
        The ids successfully quarantined. Only these may be skipped by a
        cursor advance — a quarantine write that failed leaves the row
        unaccounted for, so it stays in ``unexpected_drops`` and halts
        the cursor instead (audit IC2's contract).
    """
    quarantined: list[str] = []
    for session_id, message in poison:
        written = quarantine_record(
            QUARANTINE_FILE,
            {
                "id": session_id,
                "postgres_error": message,
                "row": rows_by_id.get(session_id),
            },
            "postgres_refused_row",
            logger=logger,
        )
        if written:
            quarantined.append(session_id)
        else:
            logger.error(
                "Could not quarantine refused session %s — holding the "
                "cursor rather than skipping it.", session_id,
            )
    return quarantined


def upsert_sessions(
    rows: list[dict[str, Any]],
    logger: logging.Logger,
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
                    f"not about the data ({type(exc).__name__}: "
                    f"{str(exc).strip()}). Cursor held; nothing quarantined."
                ) from exc
            # Content failure, not an outage. ``execute_values`` sends the
            # whole page in one transaction, so a single refused row aborts
            # every other row with it; replay individually to find out which.
            logger.error(
                "Batch upsert refused by PostgreSQL (%s) — replaying %d row(s) "
                "individually to isolate the offending session(s).",
                str(exc).strip(), len(values),
            )
            returned_ids, poison, status = insert_rows_individually(
                conn,
                upsert_sql,
                values,
                psycopg2_module=psycopg2,
                execute_values=execute_values,
                logger=logger,
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
                    "The per-row replay stopped: the refusals are not about "
                    "the data (see the preceding log line). Cursor held; "
                    "nothing quarantined."
                )
            quarantined = _quarantine_refused_rows(poison, rows_by_id, logger)

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
) -> None:
    """
    Run one sync cycle: find new session.meta.json files, upsert into
    PostgreSQL, update cursor.

    Serialised against concurrent runs via a PG advisory lock; if another
    sessions-sync is in progress, this one exits without touching the
    cursor.
    """
    with _sync_advisory_lock(logger) as acquired:
        if not acquired:
            return
        _sync_locked(archive_root, full_resync, logger)


def _sync_locked(
    archive_root: Path,
    full_resync: bool,
    logger: logging.Logger,
) -> None:
    """Core sync cycle, executed under the advisory lock."""
    since = None if full_resync else load_cursor()
    # Whether the key existed when we read it, for the compare-and-set at
    # save time (re-audit finding M3).
    cursor_key_was_present = cursor_key_present()
    if since:
        logger.info("Syncing sessions archived after %s", since)
    else:
        logger.info("Full resync — processing all sessions")

    # Find and parse metadata files
    sessions = find_session_metadata(archive_root, since=since, logger=logger)
    if not sessions:
        logger.info("No new sessions to sync")
        return

    logger.info("Found %d session(s) to sync", len(sessions))

    # Convert to row dicts. Sessions whose metadata lacks an ``id`` are
    # quarantined here so the cursor can advance past them without
    # spamming the same warning every run forever (audit IC2 / B-M2).
    rows = []
    latest_archived_at = since or "2000-01-01T00:00:00Z"
    skipped_no_id = 0
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
            quarantine_record(
                QUARANTINE_FILE,
                {
                    "meta_path": str(meta_path),
                    "metadata": metadata,
                },
                "missing_session_id",
                logger=logger,
            )
            skipped_no_id += 1
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
        return

    # Upsert into PostgreSQL (returns InsertResult with full accounting).
    result = upsert_sessions(rows, logger)

    # Cursor advance policy (#55, refined by audit round two finding P1):
    # advance ONLY when the DB was reachable AND every input id is
    # accounted for — either returned by the upsert or explicitly
    # quarantined. A row the database *refused* is accounted for; a row
    # that vanished without explanation is not.
    if not result.db_available:
        logger.warning(
            "Upsert could not reach PostgreSQL — cursor NOT advanced. "
            "This is an outage, not a data problem; the next run retries."
        )
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
        return
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
    args = parser.parse_args()

    logger = setup_logging()
    logger.info("Starting session sync (archive_root=%s)", args.archive_root)
    try:
        sync(args.archive_root, args.full_resync, logger)
    except EnvironmentFault as exc:
        # Reachable database, wrong state: permissions, a missing table or
        # column, an aborted transaction. Retrying cannot help, so say so
        # with a distinct exit code rather than reporting success over a
        # database we never wrote to (re-audit finding C1).
        logger.error("ENVIRONMENT FAULT — %s", exc)
        logger.error(
            "Fix the database (grants, schema, migration state) and re-run. "
            "No session was quarantined and the cursor did not move."
        )
        sys.exit(4)
    except CursorKeyVanished as exc:
        # A rebuild cleared the cursors while this cycle was running.
        # Writing our timestamp back would mark sessions the rebuild
        # destroyed as already synced (re-audit finding M3).
        logger.error("CURSOR RESET MID-RUN — %s", exc)
        logger.error(
            "Not writing the timestamp back. The next run starts from the "
            "rebuilt cursor and replays from the archive tree, which is "
            "what the rebuild intended."
        )
        sys.exit(6)
    except Exception as exc:
        logger.error("Unexpected error: %s", exc, exc_info=True)
        sys.exit(1)
    logger.info("Session sync complete")


if __name__ == "__main__":
    main()
