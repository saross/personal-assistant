#!/usr/bin/env python3
"""
Detect memory records that have gone missing from the canonical JSONL store.

The memory system keeps three stores: the canonical
``data/memories/memories.jsonl``, the cold-store partitions under
``data/memories/archive/``, and the derived PostgreSQL query layer. A record
is *healthy* when it lives in the canonical file or an archive partition.
This script finds records that live somewhere else and nowhere else — i.e.
canonical data that has been silently lost.

WHY THIS EXISTS (2026-08-20)
----------------------------
``scripts/daily-sync.sh`` stashes uncommitted data-submodule changes before
pulling, then pops the stash afterwards. The extraction hook appends to
``memories.jsonl`` continuously, so there are almost always uncommitted
appends when that stash is taken. If the run does not reach its pop — on
2026-08-19 a second ``daily-sync`` invocation started mid-run and the first
never popped — those appends are orphaned into a stash that nobody looks at.

Two distinct loss paths follow, and they need two distinct checks:

1. **PG-only records.** The append was synced to PostgreSQL before the stash
   was taken, so PostgreSQL holds the only copy. Found by
   ``pg_ids - jsonl_ids - archive_ids``.
2. **Stash-only records.** The stash was taken before any sync ran, so the
   record reached *no* store at all. A PostgreSQL comparison cannot see
   these — the only surviving copy is the stash itself.

Path 2 is why this is not simply a PG-parity check. On 2026-08-20 path 1
accounted for 38 records (18–19 Aug) and path 2 for a further 3 (18 Jul)
that had been invisible for a month.

Note that ``scripts/audit-postgres-sync.py`` already computed the path-1 set
but reported it as "likely orphans from deletions", excluded it from its
``is_clean`` verdict, truncated it to five lines, and never subtracted the
archive partitions — so 4,684 legitimately-archived ids buried the 38 real
ones. The signal existed; the interpretation discarded it.

⚠ RUN THIS BEFORE ``rebuild-postgres.py`` OR ANY ``--full-resync``. A rebuild
treats the canonical JSONL as complete by definition, so it cannot see a
PG-only record and will destroy it.

Exit codes:
  0 — clean: every record in PostgreSQL and in every stash is accounted for
  1 — drift found: at least one record survives in only one place
  2 — could not run (PostgreSQL unavailable, canonical file missing)

Usage:
    venv/bin/python3 scripts/check-memory-drift.py
    venv/bin/python3 scripts/check-memory-drift.py --recover
    venv/bin/python3 scripts/check-memory-drift.py --quiet-if-clean
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PA_DIR / "data"
MEMORIES_FILE = DATA_DIR / "memories" / "memories.jsonl"
ARCHIVE_DIR = DATA_DIR / "memories" / "archive"
ARCHIVE_GLOB = "memories-archive-*.jsonl"
LOG_FILE = PA_DIR / "logs" / "memory-drift.log"
DB_NAME = "claude_memories"

# Fields written by the extraction hook on every record. Recovery from
# PostgreSQL reconstructs these in this order so a recovered line is
# byte-comparable in shape to a natively-written one.
ALWAYS_FIELDS = [
    "id", "session_id", "project", "source", "category", "content",
    "confidence", "research_tags", "source_context", "created_at",
    "licence", "extractor_model_id", "source_message_uuid", "summary",
]
# Written only when populated — omitted rather than emitted as null.
OPTIONAL_FIELDS = ["why", "how_to_apply", "anchors", "verified", "deadline_at", "zotero_key"]


# ============================================================================
# Result types
# ============================================================================

@dataclass
class DriftResult:
    """Records surviving in only one store, split by which store that is."""

    jsonl_count: int = 0
    archive_count: int = 0
    postgres_count: int = 0
    #: ids in PostgreSQL but in neither the canonical file nor an archive
    pg_only: list[str] = field(default_factory=list)
    #: (stash ref, [raw JSONL lines]) for records surviving only in a stash
    stash_only: list[tuple[str, list[str]]] = field(default_factory=list)
    #: stashes touching memories.jsonl whose records are all accounted for
    stashes_clean: list[str] = field(default_factory=list)

    @property
    def stash_only_count(self) -> int:
        """Total number of records surviving only in a stash."""
        return sum(len(lines) for _, lines in self.stash_only)

    @property
    def is_clean(self) -> bool:
        """True when no record survives in only one place."""
        return not self.pg_only and not self.stash_only


# ============================================================================
# Store readers
# ============================================================================

def _read_jsonl_ids(path: Path, log: logging.Logger) -> set[str]:
    """Return the set of memory ids in a JSONL file, skipping unparseable lines."""
    ids: set[str] = set()
    if not path.exists():
        log.warning("File does not exist: %s", path)
        return ids
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                ids.add(json.loads(line)["id"])
            except (json.JSONDecodeError, KeyError):
                log.warning("Unparseable line %s:%d", path, lineno)
    return ids


def _read_archive_ids(log: logging.Logger) -> set[str]:
    """Return the union of memory ids across every cold-store partition."""
    ids: set[str] = set()
    if not ARCHIVE_DIR.exists():
        log.warning("Archive directory missing: %s", ARCHIVE_DIR)
        return ids
    for partition in sorted(ARCHIVE_DIR.glob(ARCHIVE_GLOB)):
        ids |= _read_jsonl_ids(partition, log)
    return ids


def _psql(sql: str) -> str:
    """Run a query via peer auth and return raw stdout, or raise CalledProcessError."""
    return subprocess.run(
        ["psql", "-d", DB_NAME, "-tAc", sql],
        capture_output=True, text=True, check=True,
    ).stdout


def _read_pg_ids(log: logging.Logger) -> set[str] | None:
    """Return every id in the PostgreSQL layer, or None if it is unreachable."""
    try:
        return set(_psql("SELECT id FROM memories;").split())
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        log.error("PostgreSQL unavailable: %s", exc)
        return None


# ============================================================================
# Stash inspection
# ============================================================================

def _stash_refs(log: logging.Logger) -> list[str]:
    """Return every stash ref in the data submodule, newest first."""
    try:
        out = subprocess.run(
            ["git", "-C", str(DATA_DIR), "stash", "list", "--format=%gd"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        log.warning("Could not list stashes: %s", exc)
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _stash_added_records(ref: str, log: logging.Logger) -> list[str]:
    """
    Return the raw JSONL lines a stash ADDS to memories.jsonl.

    A stash commit has multiple parents, so ``git show`` emits a *combined*
    diff in which added lines carry one ``+`` per parent rather than a single
    one. Stripping only the first ``+`` leaves a leading ``+`` on the payload
    and every line fails to parse — which is why this strips the whole run.
    """
    try:
        diff = subprocess.run(
            ["git", "-C", str(DATA_DIR), "show", ref, "--", "memories/memories.jsonl"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        log.warning("Could not read %s: %s", ref, exc)
        return []
    records: list[str] = []
    for line in diff.splitlines():
        if not line.startswith("+"):
            continue
        payload = line.lstrip("+")
        if not payload.startswith("{"):
            continue
        try:
            json.loads(payload)
        except json.JSONDecodeError:
            continue
        records.append(payload)
    return records


# ============================================================================
# The check
# ============================================================================

def check_drift(log: logging.Logger) -> DriftResult | None:
    """Compare every store and return the records surviving in only one."""
    if not MEMORIES_FILE.exists():
        log.error("Canonical file missing: %s", MEMORIES_FILE)
        return None
    jsonl_ids = _read_jsonl_ids(MEMORIES_FILE, log)
    archive_ids = _read_archive_ids(log)
    pg_ids = _read_pg_ids(log)
    if pg_ids is None:
        return None

    result = DriftResult(
        jsonl_count=len(jsonl_ids),
        archive_count=len(archive_ids),
        postgres_count=len(pg_ids),
    )
    # Path 1 — synced to PostgreSQL, then lost from the canonical file.
    # Subtracting the archives is essential: without it every deliberately
    # evicted record reads as drift and the real signal is buried.
    result.pg_only = sorted(pg_ids - jsonl_ids - archive_ids)

    # Path 2 — stashed before any sync ran, so no store ever saw it.
    safe = jsonl_ids | archive_ids | pg_ids
    for ref in _stash_refs(log):
        added = _stash_added_records(ref, log)
        if not added:
            continue
        orphaned = [line for line in added if json.loads(line)["id"] not in safe]
        if orphaned:
            result.stash_only.append((ref, orphaned))
        else:
            result.stashes_clean.append(ref)
    return result


# ============================================================================
# Recovery
# ============================================================================

def _pg_records(ids: list[str]) -> list[str]:
    """Reconstruct extraction-shaped JSONL lines for the given ids from PostgreSQL."""
    sql = """SELECT row_to_json(t) FROM (
      SELECT id, session_id, project, source, category, content, confidence,
             research_tags, source_context,
             to_char(created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')
               || '+00:00' AS created_at,
             licence, extractor_model_id, source_message_uuid, summary,
             why, how_to_apply, anchors, verified,
             to_char(deadline_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')
               || '+00:00' AS deadline_at,
             zotero_key
      FROM memories) t;"""
    wanted = set(ids)
    lines: list[str] = []
    for raw in _psql(sql).splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        if row["id"] not in wanted:
            continue
        record = {key: row.get(key) for key in ALWAYS_FIELDS}
        if record["research_tags"] is None:
            record["research_tags"] = []
        for key in OPTIONAL_FIELDS:
            if row.get(key) not in (None, "", [], {}):
                record[key] = row[key]
        lines.append(json.dumps(record, ensure_ascii=False))
    lines.sort(key=lambda line: (json.loads(line)["created_at"], json.loads(line)["id"]))
    return lines


def recover(result: DriftResult, log: logging.Logger) -> int:
    """Append every drifted record back into the canonical file. Returns the count."""
    lines = _pg_records(result.pg_only) if result.pg_only else []
    for _, stash_lines in result.stash_only:
        lines.extend(stash_lines)
    if not lines:
        return 0
    with MEMORIES_FILE.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")
    log.warning("RECOVERED %d records into %s", len(lines), MEMORIES_FILE)
    return len(lines)


# ============================================================================
# Reporting
# ============================================================================

def print_report(result: DriftResult) -> None:
    """Print a human-readable summary. Drift is stated loudly and in full."""
    print("Memory store drift check")
    print(f"  canonical JSONL : {result.jsonl_count:>7}")
    print(f"  archive files   : {result.archive_count:>7}")
    print(f"  PostgreSQL      : {result.postgres_count:>7}")
    print()
    if result.is_clean:
        print("  CLEAN — every record is present in the canonical file or an archive.")
        if result.stashes_clean:
            refs = ", ".join(result.stashes_clean)
            print(f"  Stashes touching memories.jsonl, all accounted for: {refs}")
            print("  (These are safe to drop once you no longer want them as evidence.)")
        return

    print("  *** DRIFT DETECTED — canonical data survives in only one place. ***")
    if result.pg_only:
        print(f"\n  {len(result.pg_only)} record(s) in PostgreSQL ONLY "
              "(lost from the canonical file and not archived):")
        for mid in result.pg_only:
            print(f"    {mid}")
    for ref, lines in result.stash_only:
        print(f"\n  {len(lines)} record(s) in {ref} ONLY "
              "(never reached any store — a PostgreSQL check cannot see these):")
        for raw in lines:
            print(f"    {json.loads(raw)['id']}")
    print("\n  Recover with:  venv/bin/python3 scripts/check-memory-drift.py --recover")
    print("  DO NOT run rebuild-postgres.py or --full-resync until this is clean:")
    print("  a rebuild treats the canonical JSONL as complete and will destroy the above.")


# ============================================================================
# Entry point
# ============================================================================

def main() -> int:
    """Parse arguments, run the check, optionally recover, and set the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument(
        "--recover", action="store_true",
        help="append drifted records back into the canonical JSONL",
    )
    parser.add_argument(
        "--quiet-if-clean", action="store_true",
        help="print nothing when there is no drift (for cron)",
    )
    parser.add_argument(
        "--list-recoverable-stashes", action="store_true",
        help=(
            "print one stash ref per line for stashes that still hold records "
            "found nowhere else, and nothing for stashes already accounted "
            "for. Used by daily-sync.sh so it never re-pops a stash whose "
            "contents have already been recovered."
        ),
    )
    args = parser.parse_args()

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stderr)],
    )
    log = logging.getLogger("memory-drift")

    result = check_drift(log)
    if result is None:
        # Cannot tell. Emit nothing: for --list-recoverable-stashes the safe
        # reading of "unknown" is "do not touch any stash".
        return 2

    if args.list_recoverable_stashes:
        for ref, _lines in result.stash_only:
            print(ref)
        return 0

    if result.is_clean:
        log.info("Clean — no drift (jsonl=%d archive=%d pg=%d)",
                 result.jsonl_count, result.archive_count, result.postgres_count)
        if not args.quiet_if_clean:
            print_report(result)
        return 0

    log.warning("DRIFT: %d PostgreSQL-only, %d stash-only record(s)",
                len(result.pg_only), result.stash_only_count)
    print_report(result)
    if args.recover:
        count = recover(result, log)
        print(f"\n  Recovered {count} record(s). Re-run to confirm clean, then commit "
              "data/memories/memories.jsonl.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
