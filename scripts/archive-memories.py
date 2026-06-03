#!/usr/bin/env python3
"""
Item 13 — category retention/archival sweep (no-API corpus maintenance).

Evict past-decay records of *ephemeral* categories from the live canonical
``memories.jsonl`` into a cold, git-versioned monthly partition. Archived
records stay fully retrievable (on disk, in git history) but leave the hot
append/scan/sync loop and are excluded from recall.

Policy (signed off 2026-06-01 —
``wiki/planning/memory-retention-policy-proposal.md``)
-----------------------------------------------------------------------
A record is archived iff its category has a **finite** decay window and the
record is **older than** that window. The windows are the canonical
``category_config.decay_days`` values in PostgreSQL (the same source
``apply-decay.py`` and the ``active_memories`` view use), with one
policy override applied on top:

* ``gotcha`` and ``pattern`` are **permanent** (never archived) — they are
  guidance-bearing (in the extraction hook's ``GUIDANCE_CATEGORIES``), so
  their value outlives any decay window. This override (:data:`PERMANENT_
  OVERRIDES`) holds even while ``category_config`` still records the legacy
  ``180`` for them, so the script honours the sign-off regardless of whether
  the separate ``category_config`` flip (``180 → NULL``) has been applied.

The age reference matches the ``active_memories`` view exactly: standard
categories age from ``created_at``; ``commitment`` ages from
``COALESCE(deadline_at, created_at)``. The boundary matches
``apply-decay.py`` (archive iff ``age_days > decay_days``, strictly).

Behaviour-preserving
--------------------
Records past their decay window are *already* excluded from recall by the
``active_memories`` view, so archiving them does not change what ``/recall``
returns via PostgreSQL. The only delta is the degraded JSONL-grep fallback
(``fetch-memories.py`` when PG is down), which currently returns past-decay
records and will, after the sweep, become *consistent* with the primary
path. See the proposal, §5.

Safety (mirrors ``recover_anchors.py``)
---------------------------------------
* **Dry-run is the default.** ``--apply`` is required to move anything, and
  even then the change is gated by :mod:`_bulk_rewrite_guard`
  (``ensure_safe_to_rewrite``: origin==local on the ``data`` submodule, clean
  protected files, daily-sync flock) and wrapped in ``lock_jsonl_for_rewrite``
  so concurrent extraction-hook appends drain and are blocked for the rewrite
  window. The commit carries the ``Rewrite-Class: bulk`` trailer.
* **Archive, never delete.** Archived records are appended **verbatim**
  (original line bytes) to the month partition; nothing is destroyed. Kept
  records are written back verbatim too (minimal diff).
* **Staged rollout.** ``--category progress`` sweeps one category at a time;
  run ``progress`` alone first and verify recall + digest are unchanged
  before the rest.
* **PostgreSQL.** A surgical ``UPDATE memories SET is_active=FALSE,
  decayed_at=NOW()`` for the archived ids — no delete (a rebuild stays
  possible), no embedding work.

Usage
-----
::

    venv/bin/python3 scripts/archive-memories.py                       # dry-run, all ephemeral
    venv/bin/python3 scripts/archive-memories.py --category progress   # dry-run, one category
    venv/bin/python3 scripts/archive-memories.py --report out.md       # dry-run + save report
    venv/bin/python3 scripts/archive-memories.py --category progress --apply   # mutate (guarded)
    venv/bin/python3 scripts/archive-memories.py --apply --no-postgres         # JSONL only

Run ``--apply`` from the **main working tree** (not a git worktree): the bulk
guard and the commit operate on ``<repo>/data``, which is the real submodule
only there. ``CORPUS`` is an absolute path to the main tree, so a dry-run is
safe to run from anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The canonical corpus lives in the main working tree's data submodule. This
# is an absolute path on purpose (as in recover_anchors.py): a dry-run run
# from a git worktree still reads the live corpus, and --apply is required to
# run from the main tree anyway.
CORPUS = Path.home() / "personal-assistant" / "data" / "memories" / "memories.jsonl"
ARCHIVE_DIR = CORPUS.parent / "archive"

DB_NAME = "claude_memories"

# Categories kept permanent by the 2026-06-01 sign-off despite a legacy
# finite window still sitting in category_config. Applied on top of the PG
# windows so the script never archives guidance memories.
PERMANENT_OVERRIDES = frozenset({"gotcha", "pattern"})

# In-repo mirror of the signed-off windows — the fallback when PostgreSQL is
# unreachable, and the human-readable record of policy. The canonical live
# source remains category_config in PG. Categories absent here are permanent.
FINAL_POLICY_WINDOWS: dict[str, int] = {
    "progress": 30,
    "context": 30,
    "waiting_for": 14,
    "blocker_real": 30,
    "commitment": 30,        # ages from deadline_at (fallback created_at)
    "completion": 90,
    "system_friction": 60,
    "system_success": 90,
}


# ============================================================================
# Pure core (no I/O — fully testable)
# ============================================================================


def parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp to an aware UTC datetime, or ``None``.

    Naive timestamps are assumed UTC (the corpus mixes both forms).
    """
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def effective_windows(pg_windows: dict[str, int | None]) -> dict[str, int | None]:
    """Apply the permanent-category overrides on top of the raw PG windows."""
    w = dict(pg_windows)
    for cat in PERMANENT_OVERRIDES:
        w[cat] = None
    return w


def _reference_time(record: dict) -> str | None:
    """The timestamp a record's age is measured from (matches active_memories).

    ``commitment`` ages from ``deadline_at`` (falling back to ``created_at``);
    every other category ages from ``created_at``.
    """
    if record.get("category") == "commitment":
        return record.get("deadline_at") or record.get("created_at")
    return record.get("created_at")


def should_archive(record: dict, windows: dict[str, int | None],
                   now: datetime) -> bool:
    """True iff *record* is past its category's finite decay window.

    A category with a ``None``/missing window is permanent and never
    archives. A record whose reference timestamp cannot be parsed is kept
    (conservative — we never archive something we cannot age).
    """
    decay_days = windows.get(record.get("category"))
    if decay_days is None:
        return False
    ref = parse_iso(_reference_time(record))
    if ref is None:
        return False
    # Fractional comparison (NOT truncated ``.days``) so the boundary matches
    # apply-decay.py / the active_memories view exactly: a record aged 30.6 d
    # past a 30 d window is already decayed by PG (created_at < NOW() - 30d)
    # and must be archived too. Truncating with ``.days`` would keep it,
    # leaving past-decay records behind in the hot file.
    return (now - ref) > timedelta(days=decay_days)


def partition_corpus(lines, windows: dict[str, int | None], now: datetime,
                     only_categories: frozenset[str] | None = None):
    """Split corpus *lines* into (kept_raw, archived, counts).

    ``lines`` is an iterable of raw file lines (newline included). Returns:
      * ``kept_raw``  — verbatim lines to write back to the live corpus.
      * ``archived``  — list of ``{"raw": line, "record": dict}`` to move.
      * ``counts``    — ``Counter`` of archived records per category.

    ``only_categories`` restricts eligibility; categories outside the set are
    always kept (used for the staged single-category rollout). Blank lines and
    unparseable lines are always kept verbatim.
    """
    kept_raw: list[str] = []
    archived: list[dict] = []
    counts: Counter = Counter()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            kept_raw.append(line)
            continue
        try:
            rec = json.loads(stripped)
        except json.JSONDecodeError:
            kept_raw.append(line)  # never drop something we cannot parse
            continue
        cat = rec.get("category")
        eligible = only_categories is None or cat in only_categories
        if eligible and should_archive(rec, windows, now):
            archived.append({"raw": line, "record": rec})
            counts[cat] += 1
        else:
            kept_raw.append(line)
    return kept_raw, archived, counts


# ============================================================================
# Windows source (PostgreSQL, read-only)
# ============================================================================


def fetch_windows_from_pg() -> dict[str, int | None] | None:
    """Read ``category_config.decay_days`` from PG, or ``None`` if unreachable.

    Asserts the schema version first (audit IC5). Returns the raw windows
    (before :func:`effective_windows` overrides).
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 unavailable — using in-repo policy fallback", file=sys.stderr)
        return None
    from _schema_version import assert_schema_version, SchemaVersionError

    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError as exc:
        print(f"PG unreachable ({exc}) — using in-repo policy fallback", file=sys.stderr)
        return None
    try:
        assert_schema_version(conn)
    except SchemaVersionError:
        conn.close()
        sys.exit(2)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT category, decay_days FROM category_config")
            return {cat: dd for cat, dd in cur.fetchall()}
    finally:
        conn.close()


def resolve_windows() -> tuple[dict[str, int | None], str]:
    """Return the effective windows and a one-word provenance label."""
    pg = fetch_windows_from_pg()
    if pg is None:
        return effective_windows(FINAL_POLICY_WINDOWS), "policy-fallback"
    return effective_windows(pg), "category_config"


# ============================================================================
# Reporting
# ============================================================================


def render_report(counts: Counter, archived: list[dict], windows: dict,
                  source: str, only: frozenset[str] | None) -> str:
    total = sum(counts.values())
    total_bytes = sum(len(a["raw"].encode("utf-8")) for a in archived)
    lines = ["# archive-memories — dry-run proposal (item 13)\n"]
    scope = ", ".join(sorted(only)) if only else "all ephemeral categories"
    lines.append(f"Scope: **{scope}**   windows from: **{source}**")
    lines.append(f"Records to archive: **{total}**  "
                 f"({total_bytes / 1e6:.2f} MB)\n")
    lines.append("## per category")
    for cat, n in counts.most_common():
        lines.append(f"- `{cat}` (window {windows.get(cat)} d): **{n}**")
    lines.append("\n## sample records (first 15)")
    for a in archived[:15]:
        rec = a["record"]
        summ = (rec.get("summary") or rec.get("content") or "")[:70]
        lines.append(f"- `{rec.get('category')}` {rec.get('created_at')} "
                     f"id={rec.get('id')}  {summ}")
    return "\n".join(lines) + "\n"


# ============================================================================
# Apply (guarded mutation)
# ============================================================================


def _partition_path(now: datetime) -> Path:
    """Month partition for this run: archive/memories-archive-YYYY-MM.jsonl."""
    return ARCHIVE_DIR / f"memories-archive-{now:%Y-%m}.jsonl"


def _partition_ids(partition: Path) -> set[str]:
    """Ids already present in *partition* (for idempotent, dedup-on-retry append)."""
    if not partition.exists():
        return set()
    ids: set[str] = set()
    with partition.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rid = json.loads(line).get("id")
            except json.JSONDecodeError:
                continue
            if rid:
                ids.add(rid)
    return ids


def apply_archive(corpus: Path, windows: dict, now: datetime,
                  only: frozenset[str] | None, reason: str, *,
                  do_postgres: bool) -> None:
    """Move past-decay records to the month partition (guarded + locked)."""
    from _bulk_rewrite_guard import (
        ensure_safe_to_rewrite,
        lock_jsonl_for_rewrite,
        mark_bulk_rewrite_commit_msg,
        release_lock,
    )

    ensure_safe_to_rewrite(reason=reason)
    archived_ids: list[str] = []
    partition = _partition_path(now)
    try:
        with lock_jsonl_for_rewrite(corpus):
            # Re-read the corpus fresh INSIDE the lock so any append that
            # landed between planning and now is included in the decision.
            with corpus.open(encoding="utf-8") as fh:
                kept_raw, archived, counts = partition_corpus(
                    fh, windows, now, only)
            if not archived:
                print("nothing to archive (corpus unchanged).", file=sys.stderr)
                return
            archived_ids = [a["record"].get("id") for a in archived
                            if a["record"].get("id")]
            n_idless = sum(1 for a in archived if not a["record"].get("id"))
            if n_idless:
                print(f"WARNING: {n_idless} archived record(s) have no id — "
                      "evicted from the corpus but cannot be marked inactive "
                      "in postgres.", file=sys.stderr)

            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            # Idempotent append: skip records already present in this month's
            # partition, so a crash-then-retry (records still in the un-renamed
            # corpus, already appended here) cannot duplicate them in the cold
            # store. Id-less records (latent — none today) append unconditionally.
            existing_ids = _partition_ids(partition)
            to_append = [a for a in archived
                         if not a["record"].get("id")
                         or a["record"]["id"] not in existing_ids]
            # Write + fsync the partition BEFORE truncating the corpus, so the
            # archived records are durable ahead of the source rename — a crash
            # leaves the originals in the (un-renamed) corpus, never lost.
            with partition.open("a", encoding="utf-8") as out:
                for a in to_append:
                    out.write(a["raw"])
                out.flush()
                os.fsync(out.fileno())

            tmp = corpus.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as out:
                for line in kept_raw:
                    out.write(line)
                out.flush()
                os.fsync(out.fileno())
            tmp.replace(corpus)
            _write_run_manifest(partition, counts, reason, now)
            print(f"archived {sum(counts.values())} records → {partition}",
                  file=sys.stderr)
    finally:
        release_lock()

    _git_commit(corpus, partition, sum(counts.values()), only,
                mark_bulk_rewrite_commit_msg)
    if not do_postgres:
        print("skipped postgres update (--no-postgres); reconcile is_active "
              "later if needed.", file=sys.stderr)
    elif archived_ids:
        _update_postgres(archived_ids)
    else:
        print("no archived ids to update in postgres.", file=sys.stderr)


def _write_run_manifest(partition: Path, counts: Counter, reason: str,
                        now: datetime) -> None:
    """Append a one-line run summary to archive/archive-runs.jsonl (audit)."""
    manifest = ARCHIVE_DIR / "archive-runs.jsonl"
    entry = {
        "run_at": now.isoformat(),
        "reason": reason,
        "partition": partition.name,
        "counts": dict(counts),
        "total": sum(counts.values()),
    }
    with manifest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _git_commit(corpus: Path, partition: Path, n: int,
                only: frozenset[str] | None, mark) -> None:
    import subprocess
    data_dir = corpus.parent.parent  # .../data
    scope = ",".join(sorted(only)) if only else "ephemeral"
    subject = mark(
        f"chore(memories): archive {n} past-decay records ({scope}) (item 13)",
        rewrite_class="bulk",
    )
    paths = [
        str(corpus.relative_to(data_dir)),
        str(partition.relative_to(data_dir)),
        str((ARCHIVE_DIR / "archive-runs.jsonl").relative_to(data_dir)),
    ]
    subprocess.run(["git", "-C", str(data_dir), "add", *paths], check=True)
    subprocess.run(["git", "-C", str(data_dir), "commit", "-m", subject], check=True)
    print(f"committed archival in data submodule ({n} records)", file=sys.stderr)


def _update_postgres(ids: list[str]) -> None:
    """Mark archived rows inactive (is_active=FALSE, decayed_at=NOW())."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 unavailable — skipping postgres update", file=sys.stderr)
        return
    from _schema_version import assert_schema_version, SchemaVersionError
    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except Exception as exc:  # noqa: BLE001
        # The corpus is already mutated + committed at this point, so this is
        # a loud warning, not a quiet skip: the rows still read is_active=TRUE
        # in PG (though already excluded from recall by the decay predicate).
        print(f"WARNING: postgres unreachable ({exc}) after the corpus was "
              f"archived — {len(ids)} rows still show is_active=TRUE. Re-run "
              "the is_active update or a postgres rebuild to reconcile.",
              file=sys.stderr)
        return
    try:
        assert_schema_version(conn)
    except SchemaVersionError:
        conn.close()
        sys.exit(2)
    with conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE memories SET is_active=FALSE, decayed_at=NOW() "
            "WHERE id = ANY(%s)",
            (ids,),
        )
        n = cur.rowcount
    conn.close()
    if n != len(ids):
        print(f"WARNING: postgres marked {n} rows inactive but {len(ids)} ids "
              "were archived — drift between JSONL and PG (ids not yet synced?).",
              file=sys.stderr)
    else:
        print(f"postgres: marked {n} rows inactive", file=sys.stderr)


# ============================================================================
# Entry point
# ============================================================================


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--category", action="append", default=None,
                    help="Restrict to this category (repeatable). Default: "
                         "all ephemeral categories.")
    ap.add_argument("--apply", action="store_true",
                    help="Move records (default: dry-run only).")
    ap.add_argument("--no-postgres", action="store_true",
                    help="With --apply, skip the postgres is_active update.")
    ap.add_argument("--report", type=Path, default=None,
                    help="Write the dry-run proposal to this path as well.")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    windows, source = resolve_windows()
    only = frozenset(args.category) if args.category else None

    if not CORPUS.exists():
        print(f"corpus not found: {CORPUS}", file=sys.stderr)
        return 1

    # Pre-lock pass: drives the dry-run report and the early-exit gate below.
    # On --apply, apply_archive re-partitions the corpus INSIDE the rewrite
    # lock — that in-lock read is the authoritative one (it sees any append
    # that landed in between); this snapshot is only an estimate.
    with CORPUS.open(encoding="utf-8") as fh:
        _, archived, counts = partition_corpus(fh, windows, now, only)

    report = render_report(counts, archived, windows, source, only)
    print(report)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
        print(f"report written to {args.report}", file=sys.stderr)

    if not args.apply:
        print("DRY-RUN only. Re-run with --apply to archive (guarded).",
              file=sys.stderr)
        return 0

    if not archived:
        print("nothing to archive.", file=sys.stderr)
        return 0

    scope = ",".join(sorted(only)) if only else "ephemeral"
    apply_archive(CORPUS, windows, now, only,
                  reason=f"archive-memories: {sum(counts.values())} records "
                         f"({scope}) (item 13)",
                  do_postgres=not args.no_postgres)
    return 0


if __name__ == "__main__":
    sys.exit(main())
