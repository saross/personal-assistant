#!/usr/bin/env python3
"""Reconcile one memory's mutable fields from JSONL into PostgreSQL (P8 fix).

``/forget`` and ``/update`` edit an **existing** row in
``data/memories/memories.jsonl`` (flip ``is_active`` to false, or replace
``content`` and reset ``verified``/``anchors``). But ``sync-to-postgres.py``
is INSERT-only (``ON CONFLICT (id) DO NOTHING``), so it never propagates an
edit to a row already in PostgreSQL. The PG-reading recall paths — the
session-start digest and the autonomous ``fetch-memories.py`` depth-fetch,
both via the ``active_memories`` view — therefore keep surfacing a
forgotten or stale memory until a manual ``rebuild-postgres``. That gap is
plan item **P8**.

This helper closes it: given a memory id, it reads the (already-edited)
JSONL record and issues a **surgical** ``UPDATE`` of just the mutable
columns — ``is_active``, ``content``, ``confidence``, ``verified``,
``anchors``, ``revisions`` — so PG mirrors the JSONL row. It is the same
lockstep-PG-update pattern as ``recover_anchors.py`` and
``archive-memories.py``. ``/forget`` and ``/update`` call it as a mandatory
final step.

It is **idempotent** — reconciling a row that already matches is a no-op —
and reconciles BOTH commands with one UPDATE (a /forget changes only
``is_active`` + ``revisions``; an /update changes ``content`` +
``revisions`` + clears ``verified``/``anchors``; mirroring all six columns
covers either).

Edge case (row not yet in PG): a memory forgotten before its first sync is
not in PG, so the UPDATE matches 0 rows. That is reported, not an error —
the regular sync will INSERT it, and since the P8 sibling fix added
``is_active`` to that INSERT, it inserts with the correct (inactive) flag.

Scope: PostgreSQL currently runs only on amd-tower. On a machine without
it, the helper prints a clear notice and exits non-zero (so the caller
knows the edit did not propagate); recall on those machines reads the
git-synced JSONL directly, so the JSONL edit alone suffices there.

Usage:
    python3 scripts/sync_memory_edit.py --id 2026-06-05-52451aba7fd4
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PA_DIR = Path(__file__).resolve().parent.parent
MEMORIES_FILE = PA_DIR / "memories" / "memories.jsonl"
DB_NAME = "claude_memories"  # scripts/sync-to-postgres.py:53

# The columns a /forget or /update can change. Mirroring all six means one
# UPDATE reconciles either command (and is idempotent for unchanged fields).
MUTABLE_COLUMNS = ("is_active", "content", "confidence", "verified",
                   "anchors", "revisions")

# Exit codes (so an automated caller can distinguish outcomes).
EXIT_OK = 0           # reconciled (or row not-yet-in-PG, which is benign)
EXIT_PG_UNAVAILABLE = 1  # edit did NOT propagate — a rebuild is needed
EXIT_NOT_FOUND = 2    # id is not in the JSONL at all


def find_record(memory_id: str, *, memories_path: Path = MEMORIES_FILE) -> dict | None:
    """Return the JSONL record with the given id, or ``None`` if absent.

    Reads the live append-only JSONL line by line. Ids are unique, so the
    first match is returned; a malformed line is skipped (the file is
    operational data and one bad line must not abort the lookup).
    """
    try:
        with memories_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("id") == memory_id:
                    return record
    except OSError:
        return None
    return None


def extract_values(record: dict) -> dict:
    """Pull the mutable-column values from a record (pure; no I/O).

    Defaults mirror the PostgreSQL column defaults and
    ``sync-to-postgres.record_to_tuple`` so a reconcile of an
    unforgotten/uncorrected record is a true no-op: ``is_active`` defaults
    TRUE, ``confidence`` to ``'medium'``, ``verified`` to ``None``, and the
    JSONB lists to ``[]``.
    """
    return {
        "is_active": record.get("is_active", True),
        "content": record["content"],
        "confidence": record.get("confidence", "medium"),
        "verified": record.get("verified"),
        "anchors": record.get("anchors") if isinstance(record.get("anchors"), list) else [],
        "revisions": record.get("revisions") if isinstance(record.get("revisions"), list) else [],
    }


UPDATE_SQL = (
    "UPDATE memories SET is_active=%s, content=%s, confidence=%s, "
    "verified=%s, anchors=%s, revisions=%s WHERE id=%s"
)


def reconcile_pg(record: dict, *, dbname: str = DB_NAME, connect=None) -> int:
    """Surgically UPDATE the mutable columns for ``record`` in PG.

    Returns the number of rows updated (1 = reconciled, 0 = id not in PG
    yet). ``connect`` is an injectable zero-arg callable returning a DB
    connection (psycopg2-style, usable as a context manager); it defaults
    to ``psycopg2.connect(dbname=...)``. Raises on a connection/driver
    failure so :func:`main` can report that the edit did not propagate.
    """
    import psycopg2
    from psycopg2.extras import Json

    vals = extract_values(record)
    conn = (connect or (lambda: psycopg2.connect(dbname=dbname)))()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                UPDATE_SQL,
                (
                    vals["is_active"],
                    vals["content"],
                    vals["confidence"],
                    vals["verified"],
                    Json(vals["anchors"]),
                    Json(vals["revisions"]),
                    record["id"],
                ),
            )
            return cur.rowcount
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    """Reconcile one memory id from JSONL into PostgreSQL."""
    parser = argparse.ArgumentParser(
        description="Propagate a /forget or /update edit to PostgreSQL (P8 fix).",
    )
    parser.add_argument("--id", required=True, help="The edited memory's id.")
    parser.add_argument(
        "--memories", type=Path, default=MEMORIES_FILE,
        help="Path to memories.jsonl (override for testing).",
    )
    parser.add_argument("--dbname", default=DB_NAME, help="PostgreSQL database name.")
    args = parser.parse_args(argv)

    record = find_record(args.id, memories_path=args.memories)
    if record is None:
        print(f"[sync-memory-edit] ERROR: id {args.id} not found in {args.memories}",
              file=sys.stderr)
        return EXIT_NOT_FOUND
    if "content" not in record:
        # A valid memory always carries content; its absence means a malformed
        # record. Fail with a clear, accurate message rather than letting the
        # KeyError surface later as a misleading "PostgreSQL unreachable" — and
        # rather than defaulting content to "" (which would blank the PG row).
        print(f"[sync-memory-edit] ERROR: record {args.id} has no 'content' field "
              "(malformed); not reconciling.", file=sys.stderr)
        return EXIT_NOT_FOUND

    try:
        n = reconcile_pg(record, dbname=args.dbname)
    except ImportError:
        print("[sync-memory-edit] WARNING: psycopg2 unavailable — edit NOT "
              "propagated to PostgreSQL. Run rebuild-postgres on this machine, "
              "or ignore if this machine has no PG (recall reads JSONL).",
              file=sys.stderr)
        return EXIT_PG_UNAVAILABLE
    except Exception as exc:  # noqa: BLE001 — surface, don't crash the command
        # Distinguish "server not there" from "server there, query failed".
        # A schema mismatch (e.g. a pre-v2 mirror missing the ``verified``
        # column) used to be mislabelled "PostgreSQL unreachable", which sent
        # the 2026-07-04 zbook diagnosis down the wrong path first.
        import psycopg2
        if isinstance(exc, psycopg2.OperationalError):
            print(f"[sync-memory-edit] WARNING: PostgreSQL unreachable ({exc}) — "
                  "edit NOT propagated. Run rebuild-postgres on this machine "
                  "when PG is back.", file=sys.stderr)
        else:
            print(f"[sync-memory-edit] WARNING: PostgreSQL query failed ({exc}) — "
                  "edit NOT propagated. Likely a schema mismatch: apply "
                  "scripts/schema.sql, then rebuild-postgres on this machine.",
                  file=sys.stderr)
        return EXIT_PG_UNAVAILABLE

    if n == 1:
        print(f"[sync-memory-edit] PostgreSQL reconciled for {args.id} "
              f"(is_active={record.get('is_active', True)}).")
    elif n == 0:
        print(f"[sync-memory-edit] NOTE: {args.id} not yet in PostgreSQL; the next "
              "sync will INSERT it with the correct is_active. No action needed.")
    else:  # pragma: no cover — id is a primary key, so >1 is impossible
        print(f"[sync-memory-edit] WARNING: {n} rows matched {args.id} (expected 1).",
              file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
