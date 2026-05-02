#!/usr/bin/env python3
"""
Rebuild PostgreSQL from canonical JSONL.

Truncates the memories table, resets the sync cursor to 0,
and re-runs a full sync. This is the safety net for the
"PostgreSQL is derived" guarantee.

Usage:
    venv/bin/python3 scripts/rebuild-postgres.py
"""

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
DB_NAME = "claude_memories"

# ============================================================================
# Logging
# ============================================================================

def setup_logging() -> logging.Logger:
    """Configure logging to file and stderr."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("rebuild-postgres")
    logger.setLevel(logging.INFO)

    log_file = LOG_DIR / "rebuild.log"
    fh = logging.FileHandler(log_file, encoding="utf-8")
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


def rebuild(logger: logging.Logger) -> None:
    """Truncate memories table, reset cursor, re-sync everything."""
    try:
        import psycopg2
    except ImportError:
        logger.error(
            "psycopg2 not installed. Run: venv/bin/pip install psycopg2-binary"
        )
        sys.exit(1)

    # Step 1: Truncate memories table
    logger.info("Step 1: Truncating memories table...")
    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError as exc:
        logger.error("Cannot connect to PostgreSQL: %s", exc)
        sys.exit(1)

    # Schema-version guard (audit IC5). Rebuild against the wrong shape
    # would silently truncate the wrong tables — fail loud.
    try:
        assert_schema_version(conn)
    except SchemaVersionError:
        conn.close()
        sys.exit(2)

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE memories")
                logger.info("Memories table truncated")
    except Exception as exc:
        logger.error("Failed to truncate: %s", exc)
        sys.exit(1)
    finally:
        conn.close()

    # Step 2: Reset sync cursor
    logger.info("Step 2: Resetting sync cursor to 0...")
    # Import sync module functions
    import importlib.util
    sync_path = PA_DIR / "scripts" / "sync-to-postgres.py"
    if not sync_path.exists():
        logger.error("sync-to-postgres.py not found at %s", sync_path)
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("sync_to_postgres", sync_path)
    if not spec or not spec.loader:
        logger.error("Failed to load module spec from %s", sync_path)
        sys.exit(1)
    sync_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync_mod)

    sync_mod.save_cursor(0)
    logger.info("Cursor reset to 0")

    # Step 3: Run full sync
    logger.info("Step 3: Running full sync...")
    sync_logger = logging.getLogger("sync-to-postgres")
    # Attach our handlers so sync output appears in rebuild log
    for handler in logger.handlers:
        sync_logger.addHandler(handler)
    sync_logger.setLevel(logging.INFO)

    sync_mod.sync(sync_logger)
    logger.info("Rebuild complete")


def main() -> None:
    """Entry point."""
    logger = setup_logging()
    logger.info("Starting full rebuild from JSONL")

    # Confirm action
    if sys.stdin.isatty():
        response = input(
            "This will TRUNCATE the memories table and re-sync from JSONL. "
            "Continue? [y/N] "
        )
        if response.lower() not in ("y", "yes"):
            logger.info("Rebuild cancelled by user")
            return

    try:
        rebuild(logger)
    except Exception as exc:
        logger.error("Unexpected error: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
