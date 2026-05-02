#!/usr/bin/env python3
"""
Rebuild PostgreSQL from authoritative sources — full reset.

Audit refs: B-Critical C1, B-Critical C2, B-X2 (cluster B-postgres,
2026-05-02). The earlier version of this script truncated only the
``memories`` table and reset only the ``postgres_sync_line`` cursor,
leaving the ``sessions`` table, the ``sessions_sync_timestamp`` and
``zotero_sync_line`` cursors, the freshness marker, and the PG
``sync_state`` rows in their pre-rebuild state. Subsequent runs of
``sync-to-postgres.py`` / ``sync-sessions-to-postgres.py`` /
``sync-to-zotero.py`` then skipped data they should have replayed —
silently violating the "rebuild = fresh from canonical" contract.

What this script now does
-------------------------
After a successful run the database is in the same shape as if
``schema.sql`` had just been applied to an empty DB, **plus** every
sync cursor / state marker is reset to its initial value. The next
runs of the sync scripts then fully repopulate from the authoritative
sources:

* memories — from ``data/memories/memories.jsonl``
* sessions — from ``~/cc-archives/`` ``session.meta.json`` files
* embeddings — backfilled by ``sync-to-postgres.py`` (or run
  ``backfill-embeddings.py`` directly to embed in one pass)
* Zotero notes — re-emitted by ``sync-to-zotero.py``

What this script will NOT do
----------------------------
* Drop or recreate the schema. Schema migrations live in
  ``schema.sql``; this script trusts the schema is already correct
  and asserts the version.
* Touch authoritative source files (``memories.jsonl``, archive
  ``session.meta.json`` files). Those are the rebuild *sources*.
* Run any sync after the reset. Operators run the sync scripts
  themselves (or wait for the cron tick).

Confirmation gate
-----------------
The default mode is ``--dry-run``: prints the catalogue of reset
targets and exits with status 0 without touching anything. To actually
perform the rebuild, pass ``--yes`` (or ``-y``). When stdin is a TTY
the script also prompts for confirmation regardless — ``--yes``
suppresses the prompt.

Error handling
--------------
Each reset is wrapped in try/except. On the first failure the script
stops, logs a "partial rebuild — manual cleanup needed" warning, and
exits non-zero. Stop-on-first-error is intentional: continuing past a
failure is the original bug we are fixing.

Usage
-----
    venv/bin/python3 scripts/rebuild-postgres.py            # dry-run (default)
    venv/bin/python3 scripts/rebuild-postgres.py --yes      # actually rebuild
    venv/bin/python3 scripts/rebuild-postgres.py --dry-run  # explicit dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Schema-version guard (audit IC5 / B-X1).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _schema_version import (  # noqa: E402
    EXPECTED_SCHEMA_VERSION,
    SchemaVersionError,
    assert_schema_version,
)

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = PA_DIR / "logs"
DB_NAME = "claude_memories"

# Cursor file shared by all three sync scripts (memories, sessions,
# zotero). Living in ``memories/sync-cursors.json`` is a historical
# accident — it is the single JSON object holding every sync cursor.
CURSOR_FILE = PA_DIR / "memories" / "sync-cursors.json"

# Tables holding *derived* data — these get TRUNCATEd on rebuild.
# ``meta`` is configuration (schema_version) and is NOT in this list.
# ``category_config`` is also configuration, not derived data, and
# stays untouched. ``sync_state`` is reset via UPDATE rather than
# TRUNCATE so the row identities and seeded values from ``schema.sql``
# survive.
DERIVED_TABLES: tuple[str, ...] = ("memories", "sessions")

# Cursor keys to remove from ``sync-cursors.json``. After removal the
# sync scripts fall back to their hard-coded defaults
# (``load_cursor`` returns 0 / epoch). Listed individually rather
# than wiping the file so that any future cursor key added without
# updating this list shows up as a deliberate omission rather than
# silent surplus state.
CURSOR_KEYS_TO_RESET: tuple[str, ...] = (
    "postgres_sync_line",      # sync-to-postgres.py
    "sessions_sync_timestamp",  # sync-sessions-to-postgres.py
    "zotero_sync_line",         # sync-to-zotero.py
    "postgres_last_sync_ts",    # freshness marker (sync-to-postgres.py)
)

# PG ``sync_state`` rows to reset to their seeded values from
# ``schema.sql``. Mapping is sync_type -> reset value. Note: nothing
# in the live codebase reads these rows today (the cursors above are
# the live source of truth), but ``schema.sql`` documents them as part
# of the schema contract and the ``pending_zotero_sync`` view depends
# on the ``postgres_to_zotero`` row. Keeping them in lockstep with the
# fresh-schema state preserves the "as if freshly initialised"
# guarantee.
SYNC_STATE_RESETS: dict[str, str] = {
    "jsonl_to_postgres": "0",
    "postgres_to_zotero": "2000-01-01T00:00:00Z",
    "sessions_to_postgres": "2000-01-01T00:00:00Z",
}


# ============================================================================
# Reset target catalogue
# ============================================================================


@dataclass(frozen=True)
class ResetTarget:
    """One unit of work in the rebuild.

    Attributes:
        kind: ``"table"`` | ``"sync_state_row"`` | ``"cursor_key"``.
            Used to build the end-of-run summary.
        name: Human-readable target identifier (table name, cursor
            key, or sync_type). Logged before each reset.
        description: One-line explanation for the dry-run printout.
    """

    kind: str
    name: str
    description: str


def build_reset_targets() -> list[ResetTarget]:
    """Build the ordered list of reset targets.

    Order matters slightly:
      1. PG tables first (TRUNCATEs the largest mutation surface).
      2. PG sync_state rows next (small UPDATEs, in the same DB).
      3. Cursor file keys last (filesystem op, independent of DB).

    Within each group, order is stable across runs to keep the log
    diff-friendly.
    """
    targets: list[ResetTarget] = []
    for table in DERIVED_TABLES:
        targets.append(ResetTarget(
            kind="table",
            name=table,
            description=f"TRUNCATE TABLE {table} (derived data)",
        ))
    for sync_type, value in SYNC_STATE_RESETS.items():
        targets.append(ResetTarget(
            kind="sync_state_row",
            name=sync_type,
            description=(
                f"UPDATE sync_state SET last_position = {value!r} "
                f"WHERE sync_type = {sync_type!r}"
            ),
        ))
    for key in CURSOR_KEYS_TO_RESET:
        targets.append(ResetTarget(
            kind="cursor_key",
            name=key,
            description=f"Remove {key!r} from {CURSOR_FILE.name}",
        ))
    return targets


# ============================================================================
# Logging
# ============================================================================


def setup_logging() -> logging.Logger:
    """Configure logging to file and stderr.

    Stderr handler runs at INFO so operators see every step in their
    terminal; file handler at the same level for the audit trail.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("rebuild-postgres")
    logger.setLevel(logging.INFO)
    # Idempotent setup so repeated imports (e.g. tests) do not stack
    # handlers.
    logger.handlers.clear()

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


# ============================================================================
# Reset implementations
# ============================================================================


def truncate_table(conn: Any, table: str, logger: logging.Logger) -> None:
    """TRUNCATE one derived-data table.

    The table name is hard-coded in :data:`DERIVED_TABLES`, never user
    input — f-string interpolation here is safe by construction.
    """
    with conn:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {table}")
    logger.info("Truncated table %s", table)


def reset_sync_state_row(
    conn: Any,
    sync_type: str,
    value: str,
    logger: logging.Logger,
) -> None:
    """Reset one ``sync_state`` row to its seeded value.

    Uses UPDATE rather than DELETE so the row identities seeded by
    ``schema.sql`` survive (preserves the SERIAL ids and the
    NOT NULL UNIQUE invariant on ``sync_type``). ``last_sync_at`` is
    bumped to NOW() so an operator querying the table sees that the
    row was reset, not stale.
    """
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sync_state SET last_position = %s, "
                "last_sync_at = NOW() WHERE sync_type = %s",
                (value, sync_type),
            )
            if cur.rowcount == 0:
                # Row missing — re-insert it. This makes the reset
                # idempotent against partial schemas where a row was
                # manually deleted.
                cur.execute(
                    "INSERT INTO sync_state (sync_type, last_position) "
                    "VALUES (%s, %s) ON CONFLICT (sync_type) DO NOTHING",
                    (sync_type, value),
                )
                logger.info(
                    "Re-inserted missing sync_state row %r = %r",
                    sync_type, value,
                )
            else:
                logger.info(
                    "Reset sync_state row %r to %r", sync_type, value,
                )


def reset_cursor_key(
    cursor_file: Path,
    key: str,
    logger: logging.Logger,
) -> None:
    """Remove one key from the shared sync-cursors JSON file.

    If the file does not exist there is nothing to do — the syncs
    will create it on their first save. If the key is absent, log
    that and continue (idempotent). Otherwise rewrite the file
    without the key so ``load_cursor`` returns its default.
    """
    if not cursor_file.exists():
        logger.info(
            "Cursor file %s missing — no work for key %r",
            cursor_file, key,
        )
        return

    try:
        data = json.loads(cursor_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as exc:
        # Corrupt cursor file: rewrite it as an empty object so the
        # syncs start fresh. Logged at WARNING because operators
        # should know the file was non-trivially repaired.
        logger.warning(
            "Cursor file %s corrupt (%s); rewriting as empty object",
            cursor_file, exc,
        )
        data = {}

    if not isinstance(data, dict):
        logger.warning(
            "Cursor file %s did not contain an object; rewriting empty",
            cursor_file,
        )
        data = {}

    if key not in data:
        logger.info(
            "Cursor key %r already absent from %s — no-op",
            key, cursor_file.name,
        )
        return

    del data[key]
    cursor_file.parent.mkdir(parents=True, exist_ok=True)
    cursor_file.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("Removed cursor key %r from %s", key, cursor_file.name)


# ============================================================================
# Orchestration
# ============================================================================


def _open_connection(logger: logging.Logger) -> Any | None:
    """Open a psycopg2 connection or return None on failure.

    Logs the failure cause and returns None rather than raising — the
    caller turns None into a clean exit so the operator sees the
    error message rather than a traceback.
    """
    try:
        import psycopg2
    except ImportError:
        logger.error(
            "psycopg2 not installed. Run: "
            "venv/bin/pip install psycopg2-binary"
        )
        return None
    try:
        return psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError as exc:
        logger.error("Cannot connect to PostgreSQL: %s", exc)
        return None


def print_dry_run(
    targets: list[ResetTarget],
    logger: logging.Logger,
) -> None:
    """Emit the catalogue of targets without performing any reset.

    Operators read this to confirm the rebuild will hit exactly the
    right surfaces before passing ``--yes``.
    """
    logger.info("[dry-run] Would reset %d target(s):", len(targets))
    by_kind: dict[str, list[ResetTarget]] = {}
    for tgt in targets:
        by_kind.setdefault(tgt.kind, []).append(tgt)
    for kind in ("table", "sync_state_row", "cursor_key"):
        bucket = by_kind.get(kind, [])
        if not bucket:
            continue
        logger.info("[dry-run]   %s (%d):", kind, len(bucket))
        for tgt in bucket:
            logger.info("[dry-run]     - %s — %s", tgt.name, tgt.description)
    logger.info(
        "[dry-run] No changes made. Re-run with --yes to perform "
        "the rebuild."
    )


def perform_rebuild(
    targets: list[ResetTarget],
    logger: logging.Logger,
    *,
    cursor_file: Path = CURSOR_FILE,
    open_conn: Callable[[logging.Logger], Any | None] = _open_connection,
) -> int:
    """Execute every reset target in order. Returns process exit code.

    Stop-on-first-error is intentional: the bug we are fixing is
    "partial rebuild leaves the system in an inconsistent state";
    continuing past a failure would re-introduce that exact shape.

    Parameters are injected (``cursor_file``, ``open_conn``) so tests
    can stub them without monkey-patching globals. Production callers
    use the defaults.
    """
    conn = open_conn(logger)
    if conn is None:
        return 1

    # Schema-version guard — refuse to rebuild against an unexpected
    # shape. A version mismatch could mean the truncate hits the
    # wrong tables or sync_state has a different row set.
    try:
        assert_schema_version(conn)
    except SchemaVersionError:
        conn.close()
        return 2

    counts = {"table": 0, "sync_state_row": 0, "cursor_key": 0}
    try:
        for tgt in targets:
            try:
                if tgt.kind == "table":
                    truncate_table(conn, tgt.name, logger)
                elif tgt.kind == "sync_state_row":
                    reset_sync_state_row(
                        conn,
                        tgt.name,
                        SYNC_STATE_RESETS[tgt.name],
                        logger,
                    )
                elif tgt.kind == "cursor_key":
                    reset_cursor_key(cursor_file, tgt.name, logger)
                else:
                    logger.error(
                        "Unknown reset kind %r for target %r — "
                        "stopping. Manual cleanup may be needed.",
                        tgt.kind, tgt.name,
                    )
                    return 1
                counts[tgt.kind] += 1
            except Exception as exc:  # noqa: BLE001 — log and stop
                logger.error(
                    "Reset failed for %s %r: %s. PARTIAL REBUILD — "
                    "manual cleanup needed (see "
                    "reports/audit-2026-05-02/cluster-B-postgres.md).",
                    tgt.kind, tgt.name, exc,
                )
                return 1
    finally:
        conn.close()

    logger.info(
        "Reset %d target(s): %d table(s) truncated, %d PG row(s) "
        "cleared, %d cursor key(s) removed.",
        sum(counts.values()),
        counts["table"],
        counts["sync_state_row"],
        counts["cursor_key"],
    )
    logger.info(
        "Database is now in fresh-schema state. Next steps: run "
        "sync-to-postgres.py, sync-sessions-to-postgres.py, "
        "backfill-embeddings.py, sync-to-zotero.py (in that order) "
        "to repopulate from authoritative sources."
    )
    return 0


# ============================================================================
# CLI
# ============================================================================


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    ``--dry-run`` is the implicit default: when neither ``--yes`` nor
    ``--dry-run`` is given, the script behaves as ``--dry-run`` and
    exits 0. Operators must pass ``--yes`` to actually mutate state.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild PostgreSQL from authoritative sources. Default "
            "is dry-run; pass --yes to actually reset."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--yes", "-y",
        action="store_true",
        help=(
            "Confirm destructive operation. TRUNCATEs derived tables, "
            "resets sync_state rows, and clears cursor keys. Without "
            "this flag the script prints the catalogue and exits."
        ),
    )
    group.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the catalogue of reset targets and exit. Default "
            "behaviour when --yes is not supplied."
        ),
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help=(
            "Skip the interactive confirmation prompt even on a TTY. "
            "Implied by --yes."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns process exit code (caller exits with it).

    Exit codes:
      0 — success (or dry-run completed cleanly)
      1 — connection failure / reset failure / generic error
      2 — schema version mismatch (matches ``_schema_version`` contract)
    """
    args = parse_args(argv)
    logger = setup_logging()
    targets = build_reset_targets()

    logger.info(
        "rebuild-postgres starting (expected schema_version=%s)",
        EXPECTED_SCHEMA_VERSION,
    )

    if not args.yes:
        # Default and explicit --dry-run both land here.
        print_dry_run(targets, logger)
        return 0

    # ``--yes`` path. Optionally prompt one more time on a TTY (so
    # an operator who typed it by reflex still has a chance to abort)
    # unless ``--no-prompt`` was passed explicitly.
    if sys.stdin.isatty() and not args.no_prompt:
        try:
            response = input(
                "About to TRUNCATE memories+sessions, reset sync_state "
                "rows, and clear sync cursor keys. Continue? [y/N] "
            )
        except EOFError:
            response = ""
        if response.strip().lower() not in ("y", "yes"):
            logger.info("Rebuild cancelled by operator")
            return 0

    return perform_rebuild(targets, logger)


if __name__ == "__main__":
    sys.exit(main())
