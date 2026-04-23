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

import json
import logging
import sys
from pathlib import Path
from typing import Any, NamedTuple, Optional

# Optional embedding support — gracefully degrades if unavailable
try:
    from embed import (
        build_embed_text,
        generate_embeddings,
        is_ollama_available,
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

# All fields we extract from JSONL and insert into PostgreSQL
JSONL_FIELDS = [
    "id", "session_id", "project", "source", "category", "content",
    "summary", "confidence", "research_tags", "zotero_key",
    "source_context", "created_at", "deadline_at",
]


# ============================================================================
# Logging
# ============================================================================

def setup_logging() -> logging.Logger:
    """Configure logging to file and stderr."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sync-to-postgres")
    logger.setLevel(logging.INFO)

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


# ============================================================================
# Cursor management
# ============================================================================

def load_cursor(cursor_key: str = "postgres_sync_line") -> int:
    """
    Load the last synced line number from the cursor file.

    Returns 0 if the file doesn't exist or the key is missing.
    """
    if not CURSOR_FILE.exists():
        return 0
    try:
        data = json.loads(CURSOR_FILE.read_text(encoding="utf-8"))
        return int(data.get(cursor_key, 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0


def save_cursor(line_number: int, cursor_key: str = "postgres_sync_line") -> None:
    """Save the current sync position to the cursor file."""
    data = {}
    if CURSOR_FILE.exists():
        try:
            data = json.loads(CURSOR_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            data = {}
    data[cursor_key] = line_number
    CURSOR_FILE.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
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
    data = {}
    if CURSOR_FILE.exists():
        try:
            data = json.loads(CURSOR_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            data = {}
    data["postgres_last_sync_ts"] = datetime.now(timezone.utc).isoformat()
    CURSOR_FILE.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )


# ============================================================================
# JSONL parsing
# ============================================================================

def parse_jsonl_record(line: str, line_number: int, logger: logging.Logger
                       ) -> Optional[dict[str, Any]]:
    """
    Parse a single JSONL line into a record dict.

    Returns None for empty/malformed lines. Applies defaults for
    missing optional fields.
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


def record_to_tuple(record: dict[str, Any]) -> tuple:
    """
    Convert a parsed JSONL record to an INSERT-ready tuple.

    Field order matches JSONL_FIELDS:
        id, session_id, project, source, category, content, summary,
        confidence, research_tags, zotero_key, source_context,
        created_at, deadline_at
    """
    return (
        record["id"],
        record.get("session_id", ""),
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
        record.get("deadline_at"),
    )


# ============================================================================
# Database operations
# ============================================================================

class InsertResult(NamedTuple):
    """
    Accounting result for a single insert batch.

    Attributes:
        input_count: Number of records the caller handed us.
        inserted: Number of rows PG actually inserted (from RETURNING).
        expected_dupes: Rows already present at pre-flight — ON CONFLICT
            was expected to skip these, so they are not anomalies.
        unexpected_drops: Ids that were neither present pre-flight nor
            returned by INSERT. These indicate silent row loss (#55).
        db_available: False when we could not reach the database.
    """

    input_count: int
    inserted: int
    expected_dupes: int
    unexpected_drops: list[str]
    db_available: bool


def _write_quarantine(
    dropped_records: list[dict[str, Any]],
    logger: logging.Logger,
) -> None:
    """
    Append dropped memory records to the quarantine JSONL.

    Creates parent directories and the file if missing. We quarantine
    the *full records* (not just ids) so the drop can be diagnosed and
    replayed without consulting the canonical.
    """
    try:
        QUARANTINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with QUARANTINE_FILE.open("a", encoding="utf-8") as f:
            for rec in dropped_records:
                f.write(json.dumps(rec) + "\n")
        logger.info(
            "Quarantined %d unexpectedly-dropped record(s) to %s",
            len(dropped_records),
            QUARANTINE_FILE,
        )
    except OSError as exc:
        logger.error(
            "Could not write quarantine file %s: %s", QUARANTINE_FILE, exc
        )


def insert_memories(
    records: list[tuple],
    logger: logging.Logger,
) -> InsertResult:
    """
    Insert memory records into PostgreSQL with full accounting.

    Workflow:
      1. Pre-flight: SELECT existing ids so we know what ON CONFLICT is
         *supposed* to skip (expected duplicates).
      2. INSERT ... ON CONFLICT DO NOTHING RETURNING id, capturing the
         set of ids PG actually inserted.
      3. Classify every input id as inserted, expected-dupe, or
         unexpected-drop.

    Returns an :class:`InsertResult` so callers can decide whether to
    advance the sync cursor. Callers MUST treat ``unexpected_drops``
    non-empty as a hard stop — those rows never landed and skipping
    them would cause silent loss (#55).
    """
    input_count = len(records)

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
        )

    input_ids = [r[0] for r in records]

    insert_sql = """
        INSERT INTO memories (
            id, session_id, project, source, category, content, summary,
            confidence, research_tags, zotero_key, source_context,
            created_at, deadline_at
        ) VALUES %s
        ON CONFLICT (id) DO NOTHING
        RETURNING id
    """

    try:
        with conn:
            with conn.cursor() as cur:
                # Pre-flight: which of our input ids are already in PG?
                # These are the rows ON CONFLICT is expected to skip.
                cur.execute(
                    "SELECT id FROM memories WHERE id = ANY(%s)",
                    (input_ids,),
                )
                present_before = {row[0] for row in cur.fetchall()}

                # Insert with RETURNING to capture what PG actually took.
                returned = execute_values(
                    cur,
                    insert_sql,
                    records,
                    page_size=100,
                    fetch=True,
                )
                returned_ids = {row[0] for row in returned}

        # Preserve input order when reporting unexpected drops.
        unexpected_drops = [
            mid
            for mid in input_ids
            if mid not in present_before and mid not in returned_ids
        ]

        result = InsertResult(
            input_count=input_count,
            inserted=len(returned_ids),
            expected_dupes=len(present_before),
            unexpected_drops=unexpected_drops,
            db_available=True,
        )

        logger.info(
            "Insert accounting: input=%d inserted=%d expected_dupes=%d "
            "unexpected_drops=%d",
            result.input_count,
            result.inserted,
            result.expected_dupes,
            len(result.unexpected_drops),
        )
        if unexpected_drops:
            logger.error(
                "Unexpectedly dropped %d id(s) — neither pre-existing "
                "nor inserted. First 10: %s",
                len(unexpected_drops),
                unexpected_drops[:10],
            )
        return result
    except Exception as exc:
        logger.error("Database error during insert: %s", exc)
        return InsertResult(
            input_count=input_count,
            inserted=0,
            expected_dupes=0,
            unexpected_drops=[],
            db_available=False,
        )
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
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content, COALESCE(summary, ''),
                       COALESCE(source_context, '')
                FROM memories
                WHERE embedding IS NULL
                ORDER BY created_at DESC
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


def sync(logger: logging.Logger) -> None:
    """
    Run one sync cycle: read new JSONL lines, insert into PostgreSQL,
    update cursor.
    """
    if not MEMORIES_FILE.exists():
        logger.warning("Memories file not found: %s", MEMORIES_FILE)
        return

    check_canonical_for_duplicates(logger)

    cursor_line = load_cursor()

    # Read all lines and process from cursor position
    lines = MEMORIES_FILE.read_text(encoding="utf-8").splitlines()
    total_lines = len(lines)

    if cursor_line >= total_lines:
        logger.info("No new memories to sync (cursor=%d, total=%d)", cursor_line, total_lines)
        # Freshness marker advances even on no-op — downstream /recall
        # uses this to distinguish "recently confirmed empty" from
        # "haven't checked in N hours".
        save_sync_timestamp()
        return

    new_lines = lines[cursor_line:]
    logger.info(
        "Processing lines %d–%d (%d new)",
        cursor_line + 1, total_lines, len(new_lines),
    )

    # Parse records. We keep both the original dict (for quarantine on
    # unexpected drop) and the INSERT tuple (for psycopg2), indexed by id.
    records: list[tuple] = []
    parsed_by_id: dict[str, dict[str, Any]] = {}
    for offset, line in enumerate(new_lines):
        line_number = cursor_line + offset + 1  # 1-based for logging
        parsed = parse_jsonl_record(line, line_number, logger)
        if parsed is not None:
            records.append(record_to_tuple(parsed))
            parsed_by_id[parsed["id"]] = parsed

    if not records:
        logger.info("No valid records to insert")
        save_cursor(total_lines)
        return

    # Insert into PostgreSQL (returns InsertResult with full accounting).
    result = insert_memories(records, logger)

    # Cursor advance policy (#55): advance ONLY when we have positive
    # evidence every input row is accounted for. Specifically:
    #   - DB was reachable, AND
    #   - no ids fell through both pre-flight and RETURNING.
    if not result.db_available:
        logger.warning(
            "Insert returned db_available=False — cursor NOT advanced "
            "(PostgreSQL may be down)"
        )
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
        return
    else:
        save_cursor(total_lines)
        save_sync_timestamp()
        logger.info("Cursor advanced to line %d", total_lines)

    # Best-effort embedding of memories with NULL embeddings.
    # Processes up to EMBED_BATCH_SIZE per sync cycle (~100ms overhead).
    if HAS_EMBED:
        _update_embeddings(logger)


def main() -> None:
    """Entry point."""
    logger = setup_logging()
    logger.info("Starting sync")
    try:
        sync(logger)
    except Exception as exc:
        logger.error("Unexpected error: %s", exc, exc_info=True)
        sys.exit(1)
    logger.info("Sync complete")


if __name__ == "__main__":
    main()
