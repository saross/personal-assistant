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
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, NamedTuple

# Shared quarantine helper (audit IC2 — quarantine-on-skip).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sync_cursor import quarantine_record  # noqa: E402
# Schema-version guard (audit IC5 / B-X1) — every PG-touching script
# asserts the on-disk schema version before issuing queries.
from _schema_version import assert_schema_version, SchemaVersionError  # noqa: E402

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
      * ``(None, "<reason>")`` — poison record (malformed JSON or
        missing required field). The caller should quarantine the raw
        line before advancing the cursor (audit IC2 / B-C4).
    """
    stripped = line.strip()
    if not stripped:
        return None, None
    try:
        record = json.loads(stripped)
    except json.JSONDecodeError as exc:
        logger.warning("Malformed JSON at line %d: %s", line_number, exc)
        return None, "parse_failure"

    required = ["id", "category", "content", "created_at"]
    for field in required:
        if field not in record or not record[field]:
            logger.warning(
                "Missing required field '%s' at line %d (id=%s)",
                field, line_number, record.get("id", "unknown"),
            )
            return None, f"missing_required_field:{field}"

    return record, None


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
        db_available: False when we could not reach the database.
        duplicates_within_batch: Input records that shared an id with
            another record in the same batch; the last occurrence won.
            Non-zero here usually indicates canonical corruption.
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
        yield True
        return

    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError:
        yield True
        return

    # Schema-version guard (audit IC5). On mismatch we exit non-zero
    # rather than silently proceed against an unexpected shape.
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
        conn.commit()  # end txn; session-scoped lock persists on conn
        if not acquired:
            logger.warning(
                "Another sync holds the advisory lock for %r — skipping "
                "this cycle. Will retry on next tick.",
                ADVISORY_LOCK_KEY,
            )
            yield False
            return
        yield True
    finally:
        conn.close()  # releases the lock if we hold it


def _load_quarantined_ids() -> set[str]:
    """
    Return the set of ids already present in the quarantine JSONL.

    Used to avoid appending duplicate rows on repeated cron runs. When
    the cursor halts, subsequent ticks re-read the same input slice and
    would otherwise quarantine the same ids over and over. Malformed
    lines are skipped silently — the quarantine file is a diagnostic
    log, not load-bearing.
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
                mid = rec.get("id")
                if isinstance(mid, str):
                    ids.add(mid)
            except json.JSONDecodeError:
                continue
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
    try:
        QUARANTINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with QUARANTINE_FILE.open("a", encoding="utf-8") as f:
            for rec in new_records:
                f.write(json.dumps(rec) + "\n")
        if skipped:
            logger.info(
                "Quarantined %d new record(s) (skipped %d already present) "
                "to %s",
                len(new_records), skipped, QUARANTINE_FILE,
            )
        else:
            logger.info(
                "Quarantined %d unexpectedly-dropped record(s) to %s",
                len(new_records), QUARANTINE_FILE,
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
            source_message_uuid, licence, extractor_model_id
        ) VALUES %s
        ON CONFLICT (id) DO NOTHING
        RETURNING id
    """

    try:
        with conn:
            with conn.cursor() as cur:
                # Pre-flight: which of our input ids are already in PG?
                # These are the rows ON CONFLICT is expected to skip.
                # ANY(%s) sends the list as a single PG array parameter,
                # so we are not limited by the ~32k per-statement parameter
                # ceiling — batches of 100k ids would still fit.
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
            duplicates_within_batch=duplicates_within_batch,
        )

        # Keep the happy path quiet; escalate only when there is
        # something a human might want to see. Pure re-sync cycles
        # (all expected_dupes) emit at DEBUG; anything anomalous or
        # novel is logged at INFO.
        accounting_msg = (
            "Insert accounting: input=%d inserted=%d expected_dupes=%d "
            "unexpected_drops=%d dupes_in_batch=%d"
        )
        accounting_args = (
            result.input_count, result.inserted, result.expected_dupes,
            len(result.unexpected_drops), result.duplicates_within_batch,
        )
        if unexpected_drops or duplicates_within_batch or result.inserted:
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
    except psycopg2.Error as exc:
        logger.error("Database error during insert: %s", exc)
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

    Serialised against concurrent runs via a PG advisory lock; if another
    sync is in progress, this one exits without touching the cursor and
    the next cron tick retries.
    """
    if not MEMORIES_FILE.exists():
        logger.warning("Memories file not found: %s", MEMORIES_FILE)
        return

    check_canonical_for_duplicates(logger)

    with _sync_advisory_lock(logger) as acquired:
        if not acquired:
            return
        _sync_locked(logger)


def _sync_locked(logger: logging.Logger) -> None:
    """Core sync cycle, executed under the advisory lock."""
    cursor_line = load_cursor()

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
        return

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
    for offset, line in enumerate(new_lines):
        line_number = cursor_line + offset + 1  # 1-based for logging
        parsed, failure_reason = classify_jsonl_line(line, line_number, logger)
        if parsed is not None:
            records.append(record_to_tuple(parsed))
            parsed_by_id[parsed["id"]] = parsed
        elif failure_reason is not None:
            # Poison record: quarantine the raw line + line number so an
            # operator can repair the canonical and replay if needed.
            quarantine_record(
                QUARANTINE_FILE,
                {
                    "line_number": line_number,
                    "raw_line": line.rstrip("\n"),
                },
                failure_reason,
                logger=logger,
            )
            poison_count += 1
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
