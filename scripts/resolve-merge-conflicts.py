#!/usr/bin/env python3
"""
Resolve git merge conflicts in append-only memory files via union + dedup.

Purpose
-------
memories.jsonl and tag-vocabulary.txt are effectively append-only across
machines — extraction hooks on zbook and amd-tower each append new records
during independent sessions, producing three-way merges whose "conflict"
is actually two valid additions on either side.

The correct resolution is the set union. This script rewrites the conflicted
files in place, stripping conflict markers and deduplicating:
  - memories.jsonl: by the JSON `id` field. Blank lines are dropped (harmless
    for JSONL); malformed-but-non-empty lines are kept (first occurrence wins
    by string equality).
  - tag-vocabulary.txt: by exact line match

Invocation
----------
    scripts/resolve-merge-conflicts.py path/to/memories.jsonl [path/to/tag-vocabulary.txt]

Exits 0 on success (including the clean-file no-op case), 2 on missing
input file. Use --quiet-if-clean to suppress the "no conflict markers"
message when invoked by automation.

Safety
------
- Writes via temp file + atomic rename, so a crash mid-write leaves the
  original intact.
- Does not touch git state. Caller is responsible for `git add` and
  commit/continue.
- Never deletes a line — only deduplicates. Union is strictly >= either
  side on its own.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


CONFLICT_START_PREFIX = "<<<<<<< "
CONFLICT_END_PREFIX = ">>>>>>> "
CONFLICT_SEPARATOR = "======="  # Git emits exactly this with nothing after


def is_conflict_marker(line: str) -> bool:
    """
    Is this line a git conflict marker?

    Markers are matched against their exact line forms, not substring, so
    memory content that happens to contain `=======` or `<<<<<<<` within
    a larger JSON string does not trigger a false positive.
    """
    return (
        line.startswith(CONFLICT_START_PREFIX)
        or line.startswith(CONFLICT_END_PREFIX)
        or line == CONFLICT_SEPARATOR
    )


def has_conflict_markers(lines: list[str]) -> bool:
    """True iff any line matches a git conflict marker on its own."""
    return any(is_conflict_marker(ln) for ln in lines)


def strip_conflict_markers(lines: list[str]) -> list[str]:
    """Remove conflict-marker lines, keeping everything between them."""
    return [ln for ln in lines if not is_conflict_marker(ln)]


def dedup_jsonl_by_id(lines: list[str]) -> list[str]:
    """
    Deduplicate JSONL by the `id` field. Records missing `id` or
    unparseable are kept (first occurrence wins based on string equality).
    """
    seen_ids: set[str] = set()
    seen_raw: set[str] = set()
    out: list[str] = []
    for ln in lines:
        if not ln.strip():
            continue
        try:
            mid = json.loads(ln).get("id")
        except json.JSONDecodeError:
            mid = None
        if mid:
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
        else:
            if ln in seen_raw:
                continue
            seen_raw.add(ln)
        out.append(ln)
    return out


def dedup_by_line(lines: list[str]) -> list[str]:
    """Deduplicate by exact line match while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for ln in lines:
        if ln in seen:
            continue
        seen.add(ln)
        out.append(ln)
    return out


def atomic_write(path: Path, content: str) -> None:
    """Write via temp file + rename to survive mid-write interruption."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def resolve(path: Path, quiet_if_clean: bool) -> int:
    """
    Resolve conflicts in `path`. Returns the number of conflict blocks
    removed (0 if file was already clean).
    """
    if not path.exists():
        print(f"ERROR: {path} does not exist", file=sys.stderr)
        return -1

    lines = path.read_text(encoding="utf-8").splitlines()
    if not has_conflict_markers(lines):
        if not quiet_if_clean:
            print(f"{path}: no conflict markers — skipping")
        return 0

    # Count conflict blocks (each block has exactly one <<<<<<< marker)
    blocks = sum(1 for ln in lines if ln.startswith(CONFLICT_START_PREFIX))

    cleaned = strip_conflict_markers(lines)
    before = len(cleaned)

    if path.name == "memories.jsonl":
        deduped = dedup_jsonl_by_id(cleaned)
    else:
        deduped = dedup_by_line(cleaned)

    atomic_write(path, "\n".join(deduped) + "\n")
    print(
        f"{path}: resolved {blocks} conflict block(s) "
        f"({before} lines → {len(deduped)} after dedup)"
    )
    return blocks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve merge conflicts in append-only memory files."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Files to resolve (memories.jsonl, tag-vocabulary.txt, ...)",
    )
    parser.add_argument(
        "--quiet-if-clean",
        action="store_true",
        help="Suppress output when a file has no conflicts",
    )
    args = parser.parse_args()

    total_blocks = 0
    for path in args.paths:
        result = resolve(path, args.quiet_if_clean)
        if result < 0:
            return 2
        total_blocks += result

    if total_blocks == 0 and not args.quiet_if_clean:
        print("No conflicts to resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
