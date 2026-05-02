#!/usr/bin/env python3
"""
Backfill semantic embeddings for existing memories in PostgreSQL.

Generates embeddings via Ollama (nomic-embed-text) for all memories
where the embedding column is NULL. Safe to re-run — only processes
records without embeddings.

Usage:
    venv/bin/python3 scripts/backfill-embeddings.py [--dry-run] [--batch-size N] [--limit N]

Options:
    --dry-run       Report count without generating embeddings
    --batch-size N  Records per Ollama API call (default: 200)
    --limit N       Process at most N records (0 = all, default)
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = PA_DIR / "logs"
LOG_FILE = LOG_DIR / "backfill-embeddings.log"
DB_NAME = "claude_memories"
DEFAULT_BATCH_SIZE = 200

# Import embed module from same directory
sys.path.insert(0, str(PA_DIR / "scripts"))
from embed import build_embed_text, generate_embeddings, is_ollama_available
# Schema-version guard (audit IC5 / B-X1).
from _schema_version import assert_schema_version, SchemaVersionError  # noqa: E402


# ============================================================================
# Logging
# ============================================================================


def setup_logging() -> logging.Logger:
    """Configure file and console logging."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("backfill-embeddings")
    log.setLevel(logging.INFO)

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(ch)

    return log


# ============================================================================
# Backfill
# ============================================================================


def count_missing(conn: psycopg2.extensions.connection) -> int:
    """Count memories with NULL embeddings."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM memories WHERE embedding IS NULL")
        return cur.fetchone()[0]


def fetch_batch(
    conn: psycopg2.extensions.connection,
    batch_size: int,
    offset: int = 0,
) -> list[tuple[str, str, str, str]]:
    """
    Fetch a batch of memories needing embeddings.

    Returns list of (id, content, summary, source_context) tuples,
    ordered by created_at DESC (newest first).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, content, COALESCE(summary, ''),
                   COALESCE(source_context, '')
            FROM memories
            WHERE embedding IS NULL
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (batch_size, offset),
        )
        return cur.fetchall()


def update_embeddings(
    conn: psycopg2.extensions.connection,
    id_embedding_pairs: list[tuple[str, list[float]]],
) -> int:
    """
    Update memories with generated embeddings.

    Args:
        conn: PostgreSQL connection.
        id_embedding_pairs: List of (memory_id, embedding_vector) tuples.

    Returns:
        Number of rows updated.
    """
    if not id_embedding_pairs:
        return 0

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            "UPDATE memories SET embedding = %s::vector WHERE id = %s",
            [(json.dumps(emb), mid) for mid, emb in id_embedding_pairs],
            page_size=100,
        )
    conn.commit()
    return len(id_embedding_pairs)


def backfill(
    batch_size: int,
    limit: int,
    dry_run: bool,
    logger: logging.Logger,
) -> None:
    """Run the embedding backfill."""
    # Check Ollama
    if not dry_run and not is_ollama_available():
        logger.error(
            "Ollama not available or nomic-embed-text not pulled. "
            "Run: ollama pull nomic-embed-text"
        )
        sys.exit(1)

    conn = psycopg2.connect(dbname=DB_NAME)
    # Schema-version guard (audit IC5).
    try:
        assert_schema_version(conn)
    except SchemaVersionError:
        conn.close()
        sys.exit(2)
    missing = count_missing(conn)

    if limit > 0:
        to_process = min(missing, limit)
    else:
        to_process = missing

    logger.info("Memories without embeddings: %d", missing)
    logger.info("Will process: %d (batch size: %d)", to_process, batch_size)

    if dry_run:
        n_batches = (to_process + batch_size - 1) // batch_size
        logger.info("[DRY RUN] Would process %d batches", n_batches)
        conn.close()
        return

    total_embedded = 0
    batch_num = 0

    while total_embedded < to_process:
        # Always fetch from offset 0 since previous batch was updated
        batch = fetch_batch(conn, batch_size)
        if not batch:
            break

        batch_num += 1

        # Build texts for embedding
        records = []
        for mid, content, summary, source_context in batch:
            text = build_embed_text({
                "content": content,
                "summary": summary,
                "source_context": source_context,
            })
            records.append((mid, text))

        # Generate embeddings
        texts = [text for _, text in records]
        embeddings = generate_embeddings(texts)

        # Pair successful embeddings with IDs
        pairs = []
        for (mid, _), emb in zip(records, embeddings):
            if emb is not None:
                pairs.append((mid, emb))

        # Update database
        updated = update_embeddings(conn, pairs)
        total_embedded += updated

        skipped = len(records) - len(pairs)
        logger.info(
            "Batch %d: embedded %d memories (%d/%d total%s)",
            batch_num, updated, total_embedded, to_process,
            f", {skipped} skipped" if skipped else "",
        )

        # Guard against infinite loop: if an entire batch fails to
        # embed, break rather than retrying the same records forever
        if updated == 0:
            logger.error(
                "Batch %d: all %d embeddings failed — aborting",
                batch_num, len(records),
            )
            break

    conn.close()
    logger.info("Backfill complete: %d memories embedded", total_embedded)


# ============================================================================
# CLI
# ============================================================================


def main() -> None:
    """Parse arguments and run backfill."""
    parser = argparse.ArgumentParser(
        description="Backfill semantic embeddings for memories",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"Records per batch (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max records to process (0 = all)",
    )

    args = parser.parse_args()
    logger = setup_logging()
    backfill(args.batch_size, args.limit, args.dry_run, logger)


if __name__ == "__main__":
    main()
