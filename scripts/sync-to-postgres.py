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
from typing import Any, Optional

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

def insert_memories(records: list[tuple], logger: logging.Logger) -> int:
    """
    Insert memory records into PostgreSQL.

    Uses execute_values for batch efficiency. ON CONFLICT (id) DO NOTHING
    handles re-syncs gracefully.

    Returns the number of rows actually inserted.
    """
    try:
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError:
        logger.error(
            "psycopg2 not installed. Run: venv/bin/pip install psycopg2-binary"
        )
        return 0

    insert_sql = """
        INSERT INTO memories (
            id, session_id, project, source, category, content, summary,
            confidence, research_tags, zotero_key, source_context,
            created_at, deadline_at
        ) VALUES %s
        ON CONFLICT (id) DO NOTHING
    """

    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError as exc:
        logger.warning("Cannot connect to PostgreSQL: %s", exc)
        logger.info(
            "PostgreSQL may be stopped — this is not critical. "
            "JSONL remains canonical."
        )
        return 0

    try:
        with conn:
            with conn.cursor() as cur:
                # execute_values with ON CONFLICT returns only the last
                # batch's rowcount, so we count processed records instead
                execute_values(cur, insert_sql, records, page_size=100)
        logger.info(
            "Sent %d memories to PostgreSQL (duplicates skipped via ON CONFLICT)",
            len(records),
        )
        return len(records)
    except Exception as exc:
        logger.error("Database error during insert: %s", exc)
        return 0
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

def sync(logger: logging.Logger) -> None:
    """
    Run one sync cycle: read new JSONL lines, insert into PostgreSQL,
    update cursor.
    """
    if not MEMORIES_FILE.exists():
        logger.warning("Memories file not found: %s", MEMORIES_FILE)
        return

    cursor_line = load_cursor()

    # Read all lines and process from cursor position
    lines = MEMORIES_FILE.read_text(encoding="utf-8").splitlines()
    total_lines = len(lines)

    if cursor_line >= total_lines:
        logger.info("No new memories to sync (cursor=%d, total=%d)", cursor_line, total_lines)
        return

    new_lines = lines[cursor_line:]
    logger.info(
        "Processing lines %d–%d (%d new)",
        cursor_line + 1, total_lines, len(new_lines),
    )

    # Parse records
    records = []
    for offset, line in enumerate(new_lines):
        line_number = cursor_line + offset + 1  # 1-based for logging
        parsed = parse_jsonl_record(line, line_number, logger)
        if parsed is not None:
            records.append(record_to_tuple(parsed))

    if not records:
        logger.info("No valid records to insert")
        save_cursor(total_lines)
        return

    # Insert into PostgreSQL
    inserted = insert_memories(records, logger)

    # Only advance cursor if insertion succeeded
    if inserted > 0:
        save_cursor(total_lines)
        logger.info("Cursor advanced to line %d", total_lines)
    else:
        logger.warning(
            "Insert returned 0 — cursor NOT advanced (PostgreSQL may be down)"
        )

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
