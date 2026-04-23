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
"""

import argparse
import json
import logging
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, NamedTuple, Optional

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
    if not CURSOR_FILE.exists():
        return "2000-01-01T00:00:00Z"
    try:
        data = json.loads(CURSOR_FILE.read_text(encoding="utf-8"))
        return str(data.get(CURSOR_KEY, "2000-01-01T00:00:00Z"))
    except (json.JSONDecodeError, ValueError, TypeError):
        return "2000-01-01T00:00:00Z"


def save_cursor(timestamp: str) -> None:
    """Save the current sync timestamp to the shared cursor file."""
    data = {}
    if CURSOR_FILE.exists():
        try:
            data = json.loads(CURSOR_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            data = {}
    data[CURSOR_KEY] = timestamp
    CURSOR_FILE.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )


# ============================================================================
# Archive discovery
# ============================================================================

def find_session_metadata(
    archive_root: Path,
    since: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
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
) -> dict[str, Any]:
    """
    Extract a flat row dict from a session.meta.json structure.

    Maps nested metadata fields to the sessions table columns.
    """
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
        "id": session.get("id", ""),
        "project": project.get("name", "unknown"),
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
        db_available: False when we could not reach the database.
        duplicates_within_batch: Input rows that shared an id with
            another row in the same batch; the last occurrence won.
    """

    input_count: int
    inserted: int
    expected_dupes: int
    unexpected_drops: list[str]
    db_available: bool
    duplicates_within_batch: int = 0


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

        unexpected_drops = [mid for mid in input_ids if mid not in returned_ids]

        result = InsertResult(
            input_count=input_count,
            inserted=len(returned_ids),
            expected_dupes=0,
            unexpected_drops=unexpected_drops,
            db_available=True,
            duplicates_within_batch=duplicates_within_batch,
        )

        # DEBUG on the happy path (nothing to notice); INFO when something
        # actually landed or when an anomaly surfaced.
        accounting_msg = (
            "Upsert accounting: input=%d inserted=%d unexpected_drops=%d "
            "dupes_in_batch=%d"
        )
        accounting_args = (
            result.input_count, result.inserted,
            len(result.unexpected_drops), result.duplicates_within_batch,
        )
        if unexpected_drops or duplicates_within_batch or result.inserted:
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
    except psycopg2.Error as exc:
        logger.error("Database error during upsert: %s", exc)
        return InsertResult(
            input_count=input_count,
            inserted=0,
            expected_dupes=0,
            unexpected_drops=[],
            db_available=False,
            duplicates_within_batch=duplicates_within_batch,
        )
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

    # Convert to row dicts
    rows = []
    latest_archived_at = since or "2000-01-01T00:00:00Z"
    for meta_path, metadata in sessions:
        row = metadata_to_row(meta_path, metadata)
        if not row["id"]:
            logger.warning("Session missing id in %s, skipping", meta_path)
            continue
        rows.append(row)

        # Track the latest archived_at for cursor advancement.
        # Normalise Z → +00:00 for consistent lexicographic comparison.
        archived_at = metadata.get("archive", {}).get("archived_at", "")
        if archived_at:
            normalised = archived_at.replace("Z", "+00:00")
            latest_normalised = latest_archived_at.replace("Z", "+00:00")
            if normalised > latest_normalised:
                latest_archived_at = archived_at

    if not rows:
        logger.info("No valid sessions to upsert")
        return

    # Upsert into PostgreSQL (returns InsertResult with full accounting).
    result = upsert_sessions(rows, logger)

    # Cursor advance policy (#55): advance ONLY when DB was reachable AND
    # every input id appeared in RETURNING.
    if not result.db_available:
        logger.warning(
            "Upsert returned db_available=False — cursor NOT advanced "
            "(PostgreSQL may be down)"
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
        save_cursor(latest_archived_at)
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
    except Exception as exc:
        logger.error("Unexpected error: %s", exc, exc_info=True)
        sys.exit(1)
    logger.info("Session sync complete")


if __name__ == "__main__":
    main()
