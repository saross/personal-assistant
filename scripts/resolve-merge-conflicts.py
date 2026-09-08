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
# Under `merge.conflictStyle = diff3` or `zdiff3` git emits a fourth marker
# and a whole extra section — the merge BASE — between `|||||||` and
# `=======`. The label is never empty: an add/add conflict, where neither
# side had the file, still gets `||||||| <sha>`, and a stash pop gets
# `||||||| Stash base` (verified against git across merge, both diff3
# styles, and stash pop). So there is no bare-marker form to match.
CONFLICT_BASE_PREFIX = "||||||| "


def is_conflict_marker(line: str) -> bool:
    """
    Does this line have the exact shape of a git conflict marker?

    Shape only: whether it is ACTING as a marker depends on where it sits,
    which is what `strip_conflict_markers` decides. Matching is against
    whole-line forms, not substrings, so memory content that happens to
    contain `=======` or `<<<<<<<` inside a larger JSON string does not
    trigger a false positive.
    """
    return (
        line.startswith(CONFLICT_START_PREFIX)
        or line.startswith(CONFLICT_END_PREFIX)
        or line.startswith(CONFLICT_BASE_PREFIX)
        or line == CONFLICT_SEPARATOR
    )


def has_conflict_markers(lines: list[str]) -> bool:
    """
    True iff the file holds a conflict block, i.e. an opening marker.

    audit C1 (fourth re-audit): a `=======` or `||||||| ...` line with no
    `<<<<<<< ` above it is not a conflict — it is content that happens to
    look like a marker, or a half-repaired file a human is part-way
    through. Either way this script must not touch the file: it has no
    way to tell which side of a boundary that is not there each line
    belongs to. `resolve` reports such lines and leaves the file alone.
    """
    return any(ln.startswith(CONFLICT_START_PREFIX) for ln in lines)


def marker_lines_outside_blocks(lines: list[str]) -> list[str]:
    """
    Return marker-shaped lines that sit outside any conflict block.

    Used only to tell a human that a file needs their eye: they are kept
    verbatim, never rewritten.
    """
    stray: list[str] = []
    in_block = False
    for ln in lines:
        if ln.startswith(CONFLICT_START_PREFIX):
            in_block = True
            continue
        if in_block:
            if ln.startswith(CONFLICT_END_PREFIX):
                in_block = False
            continue
        if is_conflict_marker(ln):
            stray.append(ln)
    return stray


def strip_conflict_markers(lines: list[str]) -> list[str]:
    """
    Remove conflict markers, and any diff3/zdiff3 merge-base section,
    from INSIDE conflict blocks — and nothing else.

    The invariant (audit C1, fourth re-audit): a line outside an open
    block — one where `<<<<<<< ` has been seen and `>>>>>>> ` has not — is
    never removed. Keying on the marker shape alone meant a stray
    `|||||||` line anywhere in a conflict-free file opened a "base
    section" that swallowed everything after it to the next marker or to
    end of file: a tag vocabulary lost its tail, and the script reported
    "resolved 0 conflict block(s)" and exit 0 while doing it.

    Inside a block the base section is dropped whole rather than unioned.
    The correct resolution of an append-only conflict is `ours` ∪
    `theirs`; the base is neither. Anything in it that survived is already
    in one of the two sides, and anything that did not was deleted
    deliberately — unioning it back in resurrects deleted records.
    """
    out: list[str] = []
    in_block = False
    in_base = False
    for ln in lines:
        if ln.startswith(CONFLICT_START_PREFIX):
            in_block, in_base = True, False
            continue
        if in_block:
            if ln.startswith(CONFLICT_END_PREFIX):
                in_block, in_base = False, False
                continue
            if ln.startswith(CONFLICT_BASE_PREFIX):
                in_base = True
                continue
            if ln == CONFLICT_SEPARATOR:
                in_base = False
                continue
            if in_base:
                continue
        out.append(ln)
    return out


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
            parsed = json.loads(ln)
        except json.JSONDecodeError:
            parsed = None
        # audit S12: a line that is valid JSON but not an object — `123`,
        # `null`, `"text"`, `[1, 2]` — parses fine and then raises
        # AttributeError on .get(), which escaped the except clause. The
        # resolver died with a traceback, and daily-sync.sh turns that
        # into `fail … 3`: the whole sync aborts with a conflicted tree
        # left in place. The docstring promises malformed-but-non-empty
        # lines are KEPT, so treat a non-object exactly like an
        # unparseable one and dedup it by string equality.
        mid = parsed.get("id") if isinstance(parsed, dict) else None
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
    stray = marker_lines_outside_blocks(lines)
    if stray:
        # Not something this script may fix: without an opening marker
        # there is no way to tell which side each line belongs to. Say so
        # loudly — daily-sync.sh's gate points the operator here, and a
        # silent no-op would leave them going in circles.
        print(
            f"WARNING: {path}: {len(stray)} marker-shaped line(s) outside any "
            "conflict block, left untouched — this file needs a human: "
            + ", ".join(repr(ln) for ln in stray[:3]),
            file=sys.stderr,
        )
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
