#!/usr/bin/env python3
"""
Audit PostgreSQL sync parity against the canonical JSONL/archive sources.

Read-only reconciliation tool for detecting the silent row-loss failure
mode described in issue #55. Compares the set of memory ids in
``data/memories/memories.jsonl`` (canonical) against
``claude_memories.memories`` (derived query layer), and optionally the
set of session ids in ``~/cc-archives/*/session.meta.json`` against
``claude_memories.sessions``.

Designed as the detection half of the #55 fix — run before and after
deploying the behavioural fix to confirm that (a) we can reproduce the
bug's fingerprint (rows only in JSONL, not in PG) and (b) the fix
eliminates it on new syncs.

Exit codes:
  0 — No rows are missing from PostgreSQL
  1 — At least one canonical id is missing from PostgreSQL (the bug)
  2 — Audit could not run (e.g., DB unavailable, JSONL missing)

Usage:
    venv/bin/python3 scripts/audit-postgres-sync.py
    venv/bin/python3 scripts/audit-postgres-sync.py --sessions
    venv/bin/python3 scripts/audit-postgres-sync.py --archive-root /path
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
# Schema-version guard (audit IC5 / B-X1).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _schema_version import assert_schema_version, SchemaVersionError  # noqa: E402

# ============================================================================
# Configuration — mirror the existing sync scripts so we use the same DB and
# canonical locations. Do not invent new env-var names.
# ============================================================================

PA_DIR = Path(__file__).resolve().parent.parent
MEMORIES_FILE = PA_DIR / "memories" / "memories.jsonl"
DEFAULT_ARCHIVE_ROOT = Path.home() / "cc-archives"
DB_NAME = "claude_memories"


# ============================================================================
# Logging
# ============================================================================

def setup_logging() -> logging.Logger:
    """Configure a simple stderr logger for the audit run."""
    logger = logging.getLogger("audit-postgres-sync")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(levelname)s: %(message)s")
    )
    logger.addHandler(handler)
    return logger


# ============================================================================
# Result container
# ============================================================================

@dataclass
class AuditResult:
    """Summary of a reconciliation between canonical and PostgreSQL."""

    source_name: str
    canonical_count: int
    postgres_count: int
    only_in_canonical: list[str]
    only_in_postgres: list[str]

    @property
    def is_clean(self) -> bool:
        """True when no canonical ids are missing from PostgreSQL."""
        return len(self.only_in_canonical) == 0


# ============================================================================
# Memory audit
# ============================================================================

def _read_jsonl_ids(jsonl_path: Path, logger: logging.Logger) -> set[str]:
    """
    Collect the set of ids in a JSONL canonical file.

    Duplicates are tolerated — the latest occurrence wins by virtue of
    set semantics (all occurrences map to the same id). Malformed lines
    and records without an ``id`` are warned about but do not halt the
    audit.
    """
    ids: set[str] = set()
    with jsonl_path.open(encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Malformed JSON at line %d: %s", line_number, exc
                )
                continue
            mid = record.get("id")
            if not mid:
                logger.warning(
                    "Missing id at line %d (skipped)", line_number
                )
                continue
            ids.add(str(mid))
    return ids


def _read_postgres_ids(
    table: str,
    logger: logging.Logger,
) -> set[str] | None:
    """
    Return the set of ids from a PostgreSQL table, or ``None`` on error.

    Uses the same connection conventions as the sync scripts
    (``postgresql:///claude_memories`` via peer auth).
    """
    try:
        import psycopg2
    except ImportError:
        logger.error(
            "psycopg2 not installed. Run: venv/bin/pip install psycopg2-binary"
        )
        return None

    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError as exc:
        logger.error("Cannot connect to PostgreSQL: %s", exc)
        return None

    # Schema-version guard (audit IC5). Audit exits 2 on schema
    # mismatch — distinct from "missing rows" exit 1, mirroring the
    # script's existing exit-code conventions.
    try:
        assert_schema_version(conn)
    except SchemaVersionError:
        conn.close()
        sys.exit(2)

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT id FROM {table}")
                rows = cur.fetchall()
        return {str(r[0]) for r in rows}
    except Exception as exc:
        logger.error("Query against %s failed: %s", table, exc)
        return None
    finally:
        conn.close()


def audit_memories(
    jsonl_path: Path,
    logger: logging.Logger,
) -> AuditResult | None:
    """Reconcile memory ids between the JSONL canonical and PostgreSQL."""
    if not jsonl_path.exists():
        logger.error("Canonical JSONL not found: %s", jsonl_path)
        return None

    canonical_ids = _read_jsonl_ids(jsonl_path, logger)
    postgres_ids = _read_postgres_ids("memories", logger)
    if postgres_ids is None:
        return None

    only_canonical = sorted(canonical_ids - postgres_ids)
    only_postgres = sorted(postgres_ids - canonical_ids)

    return AuditResult(
        source_name="memories",
        canonical_count=len(canonical_ids),
        postgres_count=len(postgres_ids),
        only_in_canonical=only_canonical,
        only_in_postgres=only_postgres,
    )


# ============================================================================
# Session audit (optional)
# ============================================================================

def _read_session_archive_ids(
    archive_root: Path,
    logger: logging.Logger,
) -> set[str]:
    """Collect session ids from ``session.meta.json`` files under a root."""
    ids: set[str] = set()
    if not archive_root.exists():
        logger.warning("Archive root does not exist: %s", archive_root)
        return ids

    for meta_path in archive_root.rglob("session.meta.json"):
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to parse %s: %s", meta_path, exc)
            continue
        sid = (metadata.get("session") or {}).get("id")
        if sid:
            ids.add(str(sid))
    return ids


def audit_sessions(
    archive_root: Path,
    logger: logging.Logger,
) -> AuditResult | None:
    """Reconcile session ids between archive metadata and PostgreSQL."""
    canonical_ids = _read_session_archive_ids(archive_root, logger)
    postgres_ids = _read_postgres_ids("sessions", logger)
    if postgres_ids is None:
        return None

    only_canonical = sorted(canonical_ids - postgres_ids)
    only_postgres = sorted(postgres_ids - canonical_ids)

    return AuditResult(
        source_name="sessions",
        canonical_count=len(canonical_ids),
        postgres_count=len(postgres_ids),
        only_in_canonical=only_canonical,
        only_in_postgres=only_postgres,
    )


# ============================================================================
# Reporting
# ============================================================================

def print_report(result: AuditResult) -> None:
    """Print a human-readable summary of an audit result to stdout."""
    print(f"=== {result.source_name} audit ===")
    print(f"  canonical count : {result.canonical_count:>8}")
    print(f"  postgres count  : {result.postgres_count:>8}")
    print(f"  only in canonical: {len(result.only_in_canonical):>7}")
    print(f"  only in postgres : {len(result.only_in_postgres):>7}")

    if result.only_in_canonical:
        print()
        print(
            "  The following ids are missing from PostgreSQL "
            "(the #55 bug's fingerprint):"
        )
        for mid in result.only_in_canonical[:20]:
            print(f"    - {mid}")
        if len(result.only_in_canonical) > 20:
            remaining = len(result.only_in_canonical) - 20
            print(f"    ... and {remaining} more")

    if result.only_in_postgres:
        print()
        print(
            "  The following ids exist only in PostgreSQL "
            "(likely orphans from deletions):"
        )
        for mid in result.only_in_postgres[:5]:
            print(f"    - {mid}")
        if len(result.only_in_postgres) > 5:
            remaining = len(result.only_in_postgres) - 5
            print(f"    ... and {remaining} more")


# ============================================================================
# CLI
# ============================================================================

def main() -> int:
    """Entry point. Returns the intended exit code."""
    parser = argparse.ArgumentParser(
        description=(
            "Audit PostgreSQL parity against the canonical JSONL / "
            "archive metadata (read-only)."
        ),
    )
    parser.add_argument(
        "--memories-file",
        type=Path,
        default=MEMORIES_FILE,
        help=(
            "Path to the canonical memories JSONL "
            "(default: data/memories/memories.jsonl)."
        ),
    )
    parser.add_argument(
        "--sessions",
        action="store_true",
        help="Also audit the sessions table against ~/cc-archives/.",
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root for --sessions (default: ~/cc-archives).",
    )
    args = parser.parse_args()

    logger = setup_logging()

    results: list[AuditResult] = []

    mem_result = audit_memories(args.memories_file, logger)
    if mem_result is None:
        return 2
    results.append(mem_result)
    print_report(mem_result)

    if args.sessions:
        print()
        sess_result = audit_sessions(args.archive_root, logger)
        if sess_result is None:
            return 2
        results.append(sess_result)
        print_report(sess_result)

    # Exit 1 if any audit found canonical rows missing from PostgreSQL.
    if any(not r.is_clean for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
