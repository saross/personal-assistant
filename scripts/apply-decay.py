#!/usr/bin/env python3
"""
Apply decay rules to memories in PostgreSQL.

Marks memories as inactive (is_active = FALSE, decayed_at = NOW()) based
on category_config.decay_days. Special handling for 'commitment' category
which decays from deadline_at rather than created_at.

This is a PostgreSQL-only operation — it never touches the canonical JSONL.
Run weekly via cron or manually.

Usage:
    venv/bin/python3 scripts/apply-decay.py
    venv/bin/python3 scripts/apply-decay.py --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

# Schema-version guard (audit IC5 / B-X1).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _schema_version import assert_schema_version, SchemaVersionError  # noqa: E402

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = PA_DIR / "logs"
LOG_FILE = LOG_DIR / "decay.log"
DB_NAME = "claude_memories"


# ============================================================================
# Logging
# ============================================================================

def setup_logging() -> logging.Logger:
    """Configure logging to file and stderr."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("apply-decay")
    logger.setLevel(logging.INFO)

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(sh)

    return logger


# ============================================================================
# Decay logic
# ============================================================================

def apply_decay(logger: logging.Logger, dry_run: bool = False) -> None:
    """
    Mark expired memories as inactive based on category decay rules.

    Standard categories: decay from created_at + decay_days.
    Commitment category: decay from deadline_at + 30 days (or created_at
    if no deadline set).
    """
    try:
        import psycopg2
    except ImportError:
        logger.error(
            "psycopg2 not installed. Run: venv/bin/pip install psycopg2-binary"
        )
        return

    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError as exc:
        logger.warning("Cannot connect to PostgreSQL: %s", exc)
        return

    # Schema-version guard (audit IC5).
    try:
        assert_schema_version(conn)
    except SchemaVersionError:
        conn.close()
        sys.exit(2)

    # Shared WHERE clause for decay logic — single source of truth for both
    # dry-run preview and actual decay execution.
    # Two cases:
    #   1. Standard categories: created_at + decay_days < NOW()
    #   2. Commitment: COALESCE(deadline_at, created_at) + 30 days < NOW()
    decay_where = """
        m.category = c.category
        AND m.is_active = TRUE
        AND c.decay_days IS NOT NULL
        AND (
            -- Standard decay: from created_at
            (m.category != 'commitment'
             AND m.created_at < NOW() - (c.decay_days || ' days')::INTERVAL)
            OR
            -- Commitment decay: from deadline_at (fallback to created_at)
            (m.category = 'commitment'
             AND COALESCE(m.deadline_at, m.created_at)
                 < NOW() - (c.decay_days || ' days')::INTERVAL)
        )
    """

    decay_sql = f"""
        UPDATE memories m
        SET is_active = FALSE,
            decayed_at = NOW()
        FROM category_config c
        WHERE {decay_where}
        RETURNING m.id, m.category, m.content, m.created_at, m.deadline_at
    """

    preview_sql = f"""
        SELECT m.id, m.category,
               LEFT(m.content, 80) AS content_preview,
               m.created_at, m.deadline_at
        FROM memories m
        JOIN category_config c ON {decay_where}
    """

    try:
        with conn:
            with conn.cursor() as cur:
                if dry_run:
                    cur.execute(preview_sql)
                    rows = cur.fetchall()
                    logger.info("[DRY RUN] Would decay %d memories:", len(rows))
                    for row in rows:
                        logger.info(
                            "  %s [%s] %s (created=%s, deadline=%s)",
                            row[0], row[1], row[2], row[3], row[4],
                        )
                else:
                    cur.execute(decay_sql)
                    rows = cur.fetchall()
                    logger.info("Decayed %d memories:", len(rows))
                    for row in rows:
                        logger.info(
                            "  %s [%s] %.80s",
                            row[0], row[1], row[2],
                        )
    except Exception as exc:
        logger.error("Database error during decay: %s", exc)
    finally:
        conn.close()


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Apply memory decay rules from category_config"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be decayed without making changes",
    )
    args = parser.parse_args()

    logger = setup_logging()
    logger.info("Starting decay processing%s", " (dry run)" if args.dry_run else "")
    try:
        apply_decay(logger, dry_run=args.dry_run)
    except Exception as exc:
        logger.error("Unexpected error: %s", exc, exc_info=True)
        sys.exit(1)
    logger.info("Decay processing complete")


if __name__ == "__main__":
    main()
