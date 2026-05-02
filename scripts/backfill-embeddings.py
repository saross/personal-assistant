#!/usr/bin/env python3
"""
Backfill semantic embeddings for existing memories in PostgreSQL.

Generates embeddings via Ollama (nomic-embed-text) for all memories
where the embedding column is NULL. Safe to re-run — only processes
records without embeddings (idempotent: running twice produces the same
end state).

Audit context (B-M10, IC7, 2026-05-02): pairs with the ASC ordering fix
in ``sync-to-postgres.py``. The cron-driven embedding loop only walks
``EMBED_BATCH_SIZE=100`` rows per tick; this script is the catch-up
tool for any backlog that accumulated under the previous DESC ordering
or during an Ollama outage.

Usage:
    venv/bin/python3 scripts/backfill-embeddings.py [--dry-run]
        [--batch-size N] [--limit N] [--catch-up]

Options:
    --dry-run       Report count without generating embeddings
    --batch-size N  Records per Ollama API call (default: 200)
    --limit N       Process at most N records (0 = all, default)
    --catch-up      Process *every* row currently lacking an embedding,
                    oldest first; ignores --limit. Continues past
                    individual batch failures rather than aborting on
                    the first all-failed batch (the default behaviour
                    aborts to surface a sustained Ollama outage).
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
    ordered by created_at ASC (oldest first).

    The ordering matches ``sync-to-postgres.py``'s embedding loop after
    the B-M10 fix: oldest-first so that older unembedded rows cannot be
    starved by a steady stream of newer arrivals.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, content, COALESCE(summary, ''),
                   COALESCE(source_context, '')
            FROM memories
            WHERE embedding IS NULL
            ORDER BY created_at ASC
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
    catch_up: bool = False,
) -> None:
    """
    Run the embedding backfill.

    Parameters
    ----------
    batch_size:
        Rows per Ollama API call.
    limit:
        Maximum rows to process. 0 means "all". Ignored when ``catch_up``
        is true.
    dry_run:
        Report counts without calling Ollama.
    logger:
        Configured logger.
    catch_up:
        Process every currently-unembedded row, oldest first, and tolerate
        individual batch failures (skip the failing rows by advancing the
        SQL ``OFFSET`` past them so the next batch is fresh data).
        Idempotent: running twice in a row is harmless because each call
        only sees rows still lacking embeddings.
    """
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

    if catch_up:
        to_process = missing
    elif limit > 0:
        to_process = min(missing, limit)
    else:
        to_process = missing

    logger.info("Memories without embeddings: %d", missing)
    logger.info(
        "Will process: %d (batch size: %d, catch-up: %s)",
        to_process, batch_size, catch_up,
    )

    if dry_run:
        n_batches = (to_process + batch_size - 1) // batch_size
        logger.info("[DRY RUN] Would process %d batches", n_batches)
        conn.close()
        return

    total_embedded = 0
    batch_num = 0
    # In catch-up mode we advance ``offset`` past any batch where every
    # record failed, so a single poison record (e.g. a row whose content
    # tickles a model-specific bug) cannot stall the entire run. A
    # subsequent invocation revisits the skipped rows because they still
    # lack embeddings — i.e. the skip is observational, not destructive.
    offset = 0

    while total_embedded < to_process:
        batch = fetch_batch(conn, batch_size, offset=offset)
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

        if updated == 0:
            if catch_up:
                # Skip past this batch and continue. The offset advance
                # is a within-run heuristic; the next ``fetch_batch``
                # still uses ``WHERE embedding IS NULL`` so cleared rows
                # never reappear in the same loop.
                logger.warning(
                    "Batch %d: all %d embeddings failed — skipping "
                    "and continuing (catch-up mode)",
                    batch_num, len(records),
                )
                offset += len(records)
                continue
            # Default behaviour: abort to surface a sustained outage.
            logger.error(
                "Batch %d: all %d embeddings failed — aborting",
                batch_num, len(records),
            )
            break

        # Successful batch: keep offset at 0 so the next fetch returns
        # the next-oldest unembedded slice.
        offset = 0

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
    parser.add_argument(
        "--catch-up", action="store_true",
        help=(
            "Process every unembedded row (oldest first); skip past "
            "batches whose embeddings all fail rather than aborting"
        ),
    )

    args = parser.parse_args()
    logger = setup_logging()
    backfill(
        args.batch_size,
        args.limit,
        args.dry_run,
        logger,
        catch_up=args.catch_up,
    )


if __name__ == "__main__":
    main()
