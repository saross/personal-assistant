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

The optional ``--archive-parity`` mode reconciles the cold-store memory
partitions (``memories/archive/memories-archive-*.jsonl``, written by
``scripts/archive-memories.py``) against PostgreSQL ``is_active`` state. This
surfaces — and bounds — the historical "archived id never reached PG" drift
(590 records as of 2026-06-04, all 2026-04-14 onward, traced to the
pre-item-22 stranded-cursor leak, not duplicate ids). It fails ONLY on a
recall leak: an archived id still ``is_active=TRUE``. See the
``ArchiveParityResult`` docstring for the asymmetric semantics.

Exit codes:
  0 — The two stores agree (and no archived id leaked active)
  1 — At least one canonical id is missing from PostgreSQL (the bug), a row
      diverges in content/is_active/verified, a memories row exists only in
      PostgreSQL, OR an archived id is still is_active=TRUE under
      --archive-parity
  2 — Audit could not run (e.g., DB unavailable, JSONL missing, schema drift)

Usage:
    venv/bin/python3 scripts/audit-postgres-sync.py
    venv/bin/python3 scripts/audit-postgres-sync.py --sessions
    venv/bin/python3 scripts/audit-postgres-sync.py --archive-root /path
    venv/bin/python3 scripts/audit-postgres-sync.py --archive-parity
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
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

# Cold-store memory partitions written by scripts/archive-memories.py
# (one file per month, e.g. memories-archive-2026-06.jsonl). The
# --archive-parity mode reconciles these archived ids against PostgreSQL.
# Note the distinct semantics from the live audit: an archived id ABSENT
# from PG is benign (the record was never synced before eviction, and it is
# preserved verbatim in the cold partition); the only failure is an archived
# id still flagged is_active=TRUE in PG, which would leak a past-decay record
# back into /recall via the active_memories view.
DEFAULT_MEMORY_ARCHIVE_DIR = PA_DIR / "memories" / "archive"
MEMORY_ARCHIVE_GLOB = "memories-archive-*.jsonl"


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
    """Summary of a reconciliation between canonical and PostgreSQL.

    ``divergent`` holds ids present on both sides whose content, ``is_active``
    flag, or ``verified`` value disagrees. The sync mirrors with
    ``INSERT ... ON CONFLICT DO NOTHING``, so an edited record is exactly what
    it CANNOT propagate — comparing id sets alone reported "in sync" for the
    system's most likely failure (audit 2026-09-08, finding AN9).

    ``duplicate_canonical_ids`` reports ids appearing on more than one JSONL
    line: set semantics hid them, and PostgreSQL keeps only one of them.

    ``strict_orphans`` decides whether a PostgreSQL-only row fails the audit.
    It does for memories — a row ``/recall`` can return that the canonical
    corpus does not contain is a real divergence. It does not for sessions,
    where the local archive mirror is legitimately partial.
    """

    source_name: str
    canonical_count: int
    postgres_count: int
    only_in_canonical: list[str]
    only_in_postgres: list[str]
    divergent: list[str] = field(default_factory=list)
    duplicate_canonical_ids: list[str] = field(default_factory=list)
    strict_orphans: bool = False

    @property
    def is_clean(self) -> bool:
        """True when the two stores agree on membership AND on content."""
        if self.only_in_canonical or self.divergent:
            return False
        return not (self.strict_orphans and self.only_in_postgres)


@dataclass
class ArchiveParityResult:
    """
    Reconciliation between the cold-store archive partitions and PostgreSQL.

    Unlike :class:`AuditResult`, an archived id missing from PostgreSQL is
    NOT a failure: the record may have been appended during a window when
    the line-cursor sync had stranded (the pre-2026-06-02 item-22 bug) and
    then been evicted to the cold partition before any re-scan could
    reconcile it. Such a record is preserved verbatim in the partition and,
    being past-decay, has zero recall impact. The genuine failure is the
    inverse: an archived id whose PostgreSQL row is still ``is_active=TRUE``,
    which would leak an evicted record back into the ``active_memories`` view.
    """

    archive_count: int
    archived_in_pg: int
    archived_not_in_pg: int
    leaked_active: list[str]

    @property
    def is_clean(self) -> bool:
        """True when no archived id is still active in PostgreSQL."""
        return len(self.leaked_active) == 0


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


def _connect_read_only(logger: logging.Logger):
    """Open a read-only, schema-checked connection, or return ``None``.

    The session is set read-only before any statement runs, and the caller
    ends it with ``rollback()`` rather than ``with conn:`` — psycopg2's
    connection context manager COMMITS on exit, and a reconciliation tool
    has nothing to commit.

    Raises :class:`SchemaVersionError` on a schema mismatch instead of
    calling ``sys.exit(2)``. This function is imported by
    ``memory-health-report.py``, where a bare ``sys.exit`` inside a library
    helper killed the whole report — including the eight sections that need
    no database at all (audit 2026-09-08, finding AN4). Callers translate the
    exception into their own exit code or degrade around it.
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

    try:
        conn.set_session(readonly=True)
    except Exception as exc:  # noqa: BLE001 — a fake or an old driver
        logger.warning("Could not set a read-only session: %s", exc)

    # Schema-version guard (audit IC5), before any schema-dependent query.
    try:
        assert_schema_version(conn)
    except SchemaVersionError:
        conn.close()
        raise
    return conn


def _read_jsonl_fingerprints(
    jsonl_path: Path,
    logger: logging.Logger,
) -> tuple[dict[str, str], list[str]]:
    """Return ``({id: fingerprint}, duplicate_ids)`` for a canonical JSONL.

    The LAST line wins for a repeated id, matching "the newest line is the
    record" convention used elsewhere in the pipeline. Duplicates are
    returned rather than silently collapsed: PostgreSQL keeps only one of
    them, so a duplicate is a divergence waiting to happen (finding AN9).
    """
    fingerprints: dict[str, str] = {}
    seen: set[str] = set()
    duplicates: list[str] = []
    with jsonl_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                logger.warning("Malformed JSON at line %d: %s", line_number, exc)
                continue
            mid = record.get("id")
            if not mid:
                logger.warning("Missing id at line %d (skipped)", line_number)
                continue
            mid = str(mid)
            if mid in seen:
                duplicates.append(mid)
            seen.add(mid)
            fingerprints[mid] = row_fingerprint(
                record.get("content"),
                record.get("is_active"),
                record.get("verified"),
            )
    return fingerprints, sorted(set(duplicates))


def _read_postgres_ids(
    table: str,
    logger: logging.Logger,
) -> set[str] | None:
    """
    Return the set of ids from a PostgreSQL table, or ``None`` on error.

    Uses the same connection conventions as the sync scripts
    (``postgresql:///claude_memories`` via peer auth). Raises
    :class:`SchemaVersionError` on schema drift.
    """
    conn = _connect_read_only(logger)
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id FROM {table}")
            rows = cur.fetchall()
        return {str(r[0]) for r in rows}
    except Exception as exc:
        logger.error("Query against %s failed: %s", table, exc)
        return None
    finally:
        conn.rollback()
        conn.close()


def row_fingerprint(
    content: object, is_active: object, verified: object,
) -> str:
    """A comparable digest of the three fields the sync can silently diverge on.

    One function for both sides, so JSONL and PostgreSQL normalise
    identically: a missing or NULL ``is_active`` counts as active (the column
    defaults to TRUE), and ``verified`` is case-folded because the corpus
    holds a JSON boolean where the column holds text.
    """
    active = "f" if is_active is False else "t"
    mark = "" if verified is None else str(verified).lower()
    return "\x1f".join([str(content if content is not None else ""), active, mark])


def _read_postgres_fingerprints(
    logger: logging.Logger,
) -> dict[str, str] | None:
    """Return ``{id: fingerprint}`` for every memories row, or ``None``."""
    conn = _connect_read_only(logger)
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, content, is_active, verified FROM memories")
            rows = cur.fetchall()
        return {str(r[0]): row_fingerprint(r[1], r[2], r[3]) for r in rows}
    except Exception as exc:
        logger.error("Fingerprint query against memories failed: %s", exc)
        return None
    finally:
        conn.rollback()
        conn.close()


def _read_postgres_active_map(
    ids: list[str],
    logger: logging.Logger,
) -> dict[str, bool | None] | None:
    """
    Return ``{id: is_active}`` for the subset of ``ids`` present in PG.

    Ids absent from the result dict are absent from PostgreSQL entirely.
    Returns ``None`` when the database is unavailable and RAISES
    :class:`SchemaVersionError` on schema drift, so a caller that can produce
    a partial report (``memory-health-report.py``) may degrade rather than
    die (finding AN4). ``ANY(%s)`` sends the id list as a single
    array parameter, so we are not bound by the per-statement parameter
    ceiling even for tens of thousands of archived ids.
    """
    if not ids:
        return {}
    conn = _connect_read_only(logger)
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, is_active FROM memories WHERE id = ANY(%s)",
                (ids,),
            )
            rows = cur.fetchall()
        return {str(r[0]): r[1] for r in rows}
    except Exception as exc:
        logger.error("is_active query failed: %s", exc)
        return None
    finally:
        conn.rollback()
        conn.close()


def audit_memories(
    jsonl_path: Path,
    logger: logging.Logger,
) -> AuditResult | None:
    """Reconcile memory ids AND row content between JSONL and PostgreSQL.

    Membership in both directions, plus a per-row fingerprint over content,
    ``is_active``, and ``verified``: the mirror inserts with ``ON CONFLICT DO
    NOTHING``, so an edited record never reaches PostgreSQL and an id-only
    comparison would call that "in sync" (finding AN9).
    """
    if not jsonl_path.exists():
        logger.error("Canonical JSONL not found: %s", jsonl_path)
        return None

    canonical, duplicates = _read_jsonl_fingerprints(jsonl_path, logger)
    postgres = _read_postgres_fingerprints(logger)
    if postgres is None:
        return None

    canonical_ids = set(canonical)
    postgres_ids = set(postgres)
    only_canonical = sorted(canonical_ids - postgres_ids)
    only_postgres = sorted(postgres_ids - canonical_ids)
    divergent = sorted(
        mid for mid in canonical_ids & postgres_ids
        if canonical[mid] != postgres[mid]
    )

    return AuditResult(
        source_name="memories",
        canonical_count=len(canonical_ids),
        postgres_count=len(postgres_ids),
        only_in_canonical=only_canonical,
        only_in_postgres=only_postgres,
        divergent=divergent,
        duplicate_canonical_ids=duplicates,
        # A PostgreSQL row with no canonical line is a row /recall can return
        # and the corpus does not contain.
        strict_orphans=True,
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
        # ~/cc-archives on any one machine is a mirror, not the union, so a
        # PostgreSQL session row with no local metadata is expected.
        strict_orphans=False,
    )


# ============================================================================
# Archive-vs-PostgreSQL parity (cold-store reconciliation)
# ============================================================================

def _read_archive_partition_ids(
    archive_dir: Path,
    logger: logging.Logger,
) -> set[str]:
    """
    Collect the union of memory ids across every cold-store partition.

    Globs ``archive_dir`` for ``memories-archive-*.jsonl`` files and reuses
    :func:`_read_jsonl_ids` per partition. A missing directory yields an
    empty set (nothing has been archived yet).
    """
    ids: set[str] = set()
    if not archive_dir.exists():
        logger.warning("Archive directory does not exist: %s", archive_dir)
        return ids
    partitions = sorted(archive_dir.glob(MEMORY_ARCHIVE_GLOB))
    if not partitions:
        logger.warning(
            "No archive partitions (%s) under %s",
            MEMORY_ARCHIVE_GLOB, archive_dir,
        )
        return ids
    for partition in partitions:
        ids |= _read_jsonl_ids(partition, logger)
    return ids


def audit_archive_parity(
    archive_dir: Path,
    logger: logging.Logger,
) -> ArchiveParityResult | None:
    """
    Reconcile archived (cold-store) ids against PostgreSQL is_active state.

    Three quantities are reported: archived ids present in PG, archived ids
    absent from PG (benign — never synced before eviction, preserved in the
    partition), and the failure set of archived ids still ``is_active=TRUE``
    (a recall leak). See :class:`ArchiveParityResult` for the semantics.
    """
    archive_ids = _read_archive_partition_ids(archive_dir, logger)
    active_map = _read_postgres_active_map(sorted(archive_ids), logger)
    if active_map is None:
        return None

    in_pg = set(active_map)
    not_in_pg = archive_ids - in_pg
    leaked_active = sorted(
        mid for mid, is_active in active_map.items() if is_active is True
    )

    return ArchiveParityResult(
        archive_count=len(archive_ids),
        archived_in_pg=len(in_pg),
        archived_not_in_pg=len(not_in_pg),
        leaked_active=leaked_active,
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
    print(f"  divergent rows   : {len(result.divergent):>7}")
    print(f"  duplicate ids    : {len(result.duplicate_canonical_ids):>7}")

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
        label = "FAILURE — " if result.strict_orphans else ""
        print(
            f"  {label}The following ids exist only in PostgreSQL "
            "(orphans: reachable by /recall, absent from the canonical):"
        )
        for mid in result.only_in_postgres[:5]:
            print(f"    - {mid}")
        if len(result.only_in_postgres) > 5:
            remaining = len(result.only_in_postgres) - 5
            print(f"    ... and {remaining} more")

    if result.divergent:
        print()
        print(
            "  FAILURE — the following ids differ in content, is_active, or "
            "verified between the canonical and PostgreSQL (the mirror "
            "inserts ON CONFLICT DO NOTHING, so edits do not propagate):"
        )
        for mid in result.divergent[:20]:
            print(f"    - {mid}")
        if len(result.divergent) > 20:
            print(f"    ... and {len(result.divergent) - 20} more")

    if result.duplicate_canonical_ids:
        print()
        print(
            "  The following ids appear on more than one canonical line "
            "(PostgreSQL keeps one of them):"
        )
        for mid in result.duplicate_canonical_ids[:10]:
            print(f"    - {mid}")


def print_archive_parity_report(result: ArchiveParityResult) -> None:
    """Print a human-readable summary of an archive-parity result."""
    print("=== archive-vs-postgres parity ===")
    print(f"  archived ids            : {result.archive_count:>8}")
    print(f"  archived & in postgres  : {result.archived_in_pg:>8}")
    print(
        f"  archived, NOT in postgres: {result.archived_not_in_pg:>7}  "
        "(benign: never synced before eviction; preserved in cold store)"
    )
    print(f"  leaked (still is_active) : {len(result.leaked_active):>7}")

    if result.leaked_active:
        print()
        print(
            "  FAILURE — the following archived ids are still is_active=TRUE "
            "in PostgreSQL (recall leak):"
        )
        for mid in result.leaked_active[:20]:
            print(f"    - {mid}")
        if len(result.leaked_active) > 20:
            remaining = len(result.leaked_active) - 20
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
    parser.add_argument(
        "--archive-parity",
        action="store_true",
        help=(
            "Also reconcile cold-store memory partitions "
            "(memories/archive/memories-archive-*.jsonl) against PostgreSQL "
            "is_active state. Fails only on a recall leak (an archived id "
            "still is_active=TRUE), not on archived-ids-absent-from-PG."
        ),
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=DEFAULT_MEMORY_ARCHIVE_DIR,
        help=(
            "Cold-store partition directory for --archive-parity "
            "(default: memories/archive)."
        ),
    )
    args = parser.parse_args()

    logger = setup_logging()

    results: list[AuditResult] = []

    # A schema mismatch is exit 2 for THIS script (it can produce no audit at
    # all without the schema), but the readers raise rather than exiting so
    # that library callers can degrade instead (finding AN4).
    try:
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

        # Track parity cleanliness separately — ArchiveParityResult has its own
        # is_clean semantics (a leak, not a missing id, is the failure).
        archive_clean = True
        if args.archive_parity:
            print()
            parity_result = audit_archive_parity(args.archive_dir, logger)
            if parity_result is None:
                return 2
            print_archive_parity_report(parity_result)
            archive_clean = parity_result.is_clean
    except SchemaVersionError:
        return 2

    # Exit 1 if any audit found canonical rows missing from PostgreSQL, rows
    # whose content diverges, a PostgreSQL-only memories orphan, or an
    # archived id leaked back into the active set.
    if any(not r.is_clean for r in results) or not archive_clean:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
