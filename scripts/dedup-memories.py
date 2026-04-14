#!/usr/bin/env python3
"""
Dedup the canonical memory store (one-shot).

Resolves 7,616 summary-backfill duplicates (drop the no-summary version)
and ~306 reprocess-sessions chunk-collision duplicates (re-id each copy
with a synthetic salt so all content is preserved). Concurrent appends
from the extraction hook during execution are detected by comparing the
file's byte size before reading and before renaming — any new bytes are
copied verbatim to the deduped output.

History: this script was written in response to a 2026-03-15 concat
accident where amd-tower's uncommitted memories.jsonl was merged into
zbook's already-backfilled canonical (commit df9639e), producing the
summary-backfill duplicates. The reprocess collisions are a separate
bug in scripts/reprocess-sessions.py line 453 (no per-chunk salt in
the id hash). Full diagnosis in planning/memory-store-dedup-and-rebuild.md
and the approved plan at /home/shawn/.claude/plans/gentle-roaming-meadow.md.

Usage:
    venv/bin/python3 scripts/dedup-memories.py --dry-run    # analyse only
    venv/bin/python3 scripts/dedup-memories.py              # apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PA_ROOT = Path(__file__).resolve().parent.parent
MEMORIES_FILE = PA_ROOT / "data" / "memories" / "memories.jsonl"
if not MEMORIES_FILE.exists():
    MEMORIES_FILE = PA_ROOT / "memories" / "memories.jsonl"
LOG_DIR = PA_ROOT / "data" / "logs"
if not LOG_DIR.exists():
    LOG_DIR = PA_ROOT / "logs"
LOG_FILE = LOG_DIR / "dedup-2026-04-14.log"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("dedup-memories")
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(sh)
    return logger


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load_records_with_position() -> tuple[list[tuple[int, dict | None, str]], int]:
    """
    Load all records, returning (list of (lineno, record, raw_line), final_byte_position).

    raw_line is the un-decoded original line (without trailing newline) for
    byte-exact preservation when a record needs to be written back unchanged.
    """
    records: list[tuple[int, dict | None, str]] = []
    with open(MEMORIES_FILE, "rb") as f:
        raw = f.read()
    final_bytes = len(raw)
    text = raw.decode("utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            records.append((lineno, None, line))
            continue
        try:
            d = json.loads(stripped)
            records.append((lineno, d, line))
        except json.JSONDecodeError:
            records.append((lineno, None, line))  # preserve malformed lines verbatim
    return records, final_bytes


# ---------------------------------------------------------------------------
# Resolution policies
# ---------------------------------------------------------------------------


def is_summary_only_diff(a: dict, b: dict) -> bool:
    """Two records differ ONLY in the 'summary' field."""
    a_ns = {k: v for k, v in a.items() if k != "summary"}
    b_ns = {k: v for k, v in b.items() if k != "summary"}
    return a_ns == b_ns


def pick_summary_winner(copies: list[tuple[int, dict, str]]) -> tuple[int, dict, str]:
    """
    Among copies that differ only in 'summary', keep the one with the
    longest summary (most informative). File order breaks ties.
    """
    def key(item: tuple[int, dict, str]) -> tuple[int, int]:
        lineno, rec, _raw = item
        summary = rec.get("summary") or ""
        return (-len(summary), lineno)  # longest summary first, then earliest lineno
    return sorted(copies, key=key)[0]


def reid_reprocess_collision(
    copies: list[tuple[int, dict, str]],
) -> list[tuple[int, dict, str]]:
    """
    Re-id each copy in a reprocess chunk-collision group so all copies
    have distinct ids. Uses the original lineno as a synthetic per-copy
    salt (the only uniqueness we have retroactively).

    New id format: {date_prefix}-{hash({session_id}-reprocess-relineno-{lineno}-{i})}
    where i is the copy's position within the collision group (0, 1, 2, ...).
    """
    out: list[tuple[int, dict, str]] = []
    for i, (lineno, rec, _raw) in enumerate(copies):
        session_id = rec.get("session_id", "")
        created_at = rec.get("created_at", "")
        # Date prefix from the existing id (preserve the day)
        old_id = rec.get("id", "")
        date_prefix = old_id[:10] if len(old_id) >= 10 and old_id[4] == "-" else created_at[:10]
        if not date_prefix:
            date_prefix = datetime.utcnow().strftime("%Y-%m-%d")
        id_source = f"{session_id}-reprocess-relineno-{lineno}-{i}"
        new_hash = hashlib.sha256(id_source.encode()).hexdigest()[:12]
        new_id = f"{date_prefix}-{new_hash}"
        new_rec = dict(rec)
        new_rec["id"] = new_id
        new_rec["_dedup_origin"] = {
            "original_id": old_id,
            "original_lineno": lineno,
            "reason": "reprocess-chunk-collision",
        }
        # Return lineno=lineno for file-order preservation during output sort
        out.append((lineno, new_rec, ""))
    return out


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def dedup(
    records: list[tuple[int, dict | None, str]],
    logger: logging.Logger,
) -> tuple[list[tuple[int, dict | None, str]], dict[str, int]]:
    """
    Apply the resolution policies and return the deduped record list
    (preserving original file order by lineno) plus a stats dict.
    """
    stats: dict[str, int] = {
        "total_input_lines": len(records),
        "blank_or_malformed": 0,
        "unique_records": 0,
        "summary_only_dropped": 0,
        "reprocess_reid": 0,
        "byte_identical_dropped": 0,
        "unclassified_groups": 0,
        "unclassified_groups_detail": 0,
    }

    # Group by id
    by_id: dict[str, list[tuple[int, dict, str]]] = defaultdict(list)
    blank_lines: list[tuple[int, None, str]] = []
    for lineno, rec, raw in records:
        if rec is None:
            blank_lines.append((lineno, None, raw))
            stats["blank_or_malformed"] += 1
            continue
        mid = rec.get("id")
        if not mid:
            blank_lines.append((lineno, None, raw))
            stats["blank_or_malformed"] += 1
            continue
        by_id[mid].append((lineno, rec, raw))

    kept: list[tuple[int, dict, str]] = []

    for mid, copies in by_id.items():
        if len(copies) == 1:
            kept.append(copies[0])
            stats["unique_records"] += 1
            continue

        # Byte-identical? Keep first.
        if all(c[2] == copies[0][2] for c in copies):
            kept.append(copies[0])
            stats["byte_identical_dropped"] += len(copies) - 1
            continue

        # Summary-only diff? Keep summary winner.
        all_pairs_summary_only = True
        for c in copies[1:]:
            if not is_summary_only_diff(copies[0][1], c[1]):
                all_pairs_summary_only = False
                break
        if all_pairs_summary_only:
            winner = pick_summary_winner(copies)
            kept.append(winner)
            stats["summary_only_dropped"] += len(copies) - 1
            continue

        # Reprocess chunk-collision? Re-id to preserve all.
        if all(c[1].get("source") == "reprocessing" for c in copies):
            session_ids = {c[1].get("session_id") for c in copies}
            if len(session_ids) == 1:
                reid_copies = reid_reprocess_collision(copies)
                kept.extend(reid_copies)
                stats["reprocess_reid"] += len(copies)
                continue

        # Unclassified — log for review, keep all verbatim
        stats["unclassified_groups"] += 1
        stats["unclassified_groups_detail"] += len(copies)
        logger.warning(
            "Unclassified duplicate group id=%s (size=%d, linenos=%s, sources=%s)",
            mid,
            len(copies),
            [c[0] for c in copies],
            [c[1].get("source") for c in copies],
        )
        kept.extend(copies)

    # Re-attach blank/malformed lines, sort by original lineno for file-order preservation
    output: list[tuple[int, dict | None, str]] = []
    output.extend(kept)
    output.extend(blank_lines)
    output.sort(key=lambda x: x[0])

    return output, stats


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write_output(
    records: list[tuple[int, dict | None, str]],
    new_tail_bytes: bytes,
    logger: logging.Logger,
) -> int:
    """
    Write the deduped records to a temp file and atomically rename over
    the canonical. Returns the new file's line count.

    new_tail_bytes: raw bytes of records appended to the canonical AFTER
    our initial load (detected via byte-position comparison). These are
    written verbatim after the deduped records so concurrent appends are
    preserved.
    """
    tmp_path = MEMORIES_FILE.with_suffix(".jsonl.tmp")
    with open(tmp_path, "wb") as f:
        for lineno, rec, raw in records:
            if rec is None:
                # blank or malformed line: preserve raw bytes
                f.write((raw + "\n").encode("utf-8"))
            else:
                # Strip transient _dedup_origin marker before writing
                clean = {k: v for k, v in rec.items() if k != "_dedup_origin"}
                f.write((json.dumps(clean, ensure_ascii=False) + "\n").encode("utf-8"))
        if new_tail_bytes:
            if not new_tail_bytes.endswith(b"\n"):
                new_tail_bytes = new_tail_bytes + b"\n"
            f.write(new_tail_bytes)
        f.flush()
        os.fsync(f.fileno())

    # Re-count before rename
    with open(tmp_path, "rb") as f:
        line_count = sum(1 for _ in f)

    logger.info("Temp file written: %s (%d lines)", tmp_path, line_count)
    os.rename(tmp_path, MEMORIES_FILE)
    return line_count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="analyse only; do not write")
    args = parser.parse_args()

    logger = setup_logging()
    logger.info("=== dedup-memories starting (dry_run=%s) ===", args.dry_run)
    logger.info("Canonical: %s", MEMORIES_FILE)

    records, initial_bytes = load_records_with_position()
    logger.info("Loaded %d raw lines (%d bytes) from canonical", len(records), initial_bytes)

    deduped, stats = dedup(records, logger)

    logger.info("--- dedup stats ---")
    for k, v in stats.items():
        logger.info("  %-30s %d", k, v)
    net_change = len(deduped) - stats["total_input_lines"]
    logger.info("  net line change:              %+d", net_change)

    # Invariants
    ids_in_output: dict[str, int] = defaultdict(int)
    for lineno, rec, _raw in deduped:
        if rec is not None and "id" in rec:
            ids_in_output[rec["id"]] += 1
    dup_ids_remaining = {i: c for i, c in ids_in_output.items() if c > 1}
    if dup_ids_remaining:
        logger.error(
            "INVARIANT FAILURE: %d duplicate ids remain after dedup",
            len(dup_ids_remaining),
        )
        for i, (mid, count) in enumerate(dup_ids_remaining.items()):
            if i >= 5:
                break
            logger.error("  %s × %d", mid, count)
        sys.exit(1)
    logger.info("INVARIANT OK: all output ids unique (%d total)", len(ids_in_output))

    for lineno, rec, raw in deduped:
        if rec is None:
            continue
        try:
            clean = {k: v for k, v in rec.items() if k != "_dedup_origin"}
            json.dumps(clean, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            logger.error("INVARIANT FAILURE: record not serialisable at lineno=%d: %s", lineno, exc)
            sys.exit(1)
    logger.info("INVARIANT OK: all kept records serialise as JSON")

    if args.dry_run:
        logger.info("Dry run: no file written. Exiting.")
        return

    # Check for concurrent appends: compare current file size to initial_bytes
    current_size = MEMORIES_FILE.stat().st_size
    new_tail_bytes = b""
    if current_size > initial_bytes:
        with open(MEMORIES_FILE, "rb") as f:
            f.seek(initial_bytes)
            new_tail_bytes = f.read()
        added_lines = new_tail_bytes.count(b"\n")
        logger.warning(
            "Concurrent append detected: file grew %d bytes (%d lines) during dedup. "
            "Preserving new tail verbatim.",
            current_size - initial_bytes, added_lines,
        )
    elif current_size < initial_bytes:
        logger.error(
            "Canonical SHRANK during dedup (initial=%d, current=%d). Aborting to avoid data loss.",
            initial_bytes, current_size,
        )
        sys.exit(1)

    final_count = write_output(deduped, new_tail_bytes, logger)
    logger.info("Wrote %d lines to %s", final_count, MEMORIES_FILE)
    logger.info("Backup is at: %s", MEMORIES_FILE.with_suffix(".jsonl.bak.2026-04-14"))
    logger.info("=== dedup-memories complete ===")


if __name__ == "__main__":
    main()
