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

    scripts/resolve-merge-conflicts.py --check path/to/memories.jsonl

Exit codes
----------
    0  clean, or resolved successfully
    2  a named file does not exist
    3  the file needs a HUMAN — marker-shaped lines outside any conflict
       block, or a block structure that does not balance. Nothing is
       written. `--check` reports the offending line numbers.

`--check` writes nothing and only classifies, so daily-sync.sh's guard and
this script cannot disagree about what counts as a conflict: they are the
same predicate (audit C2, fifth re-audit — the guard used to refuse files
this script then declined to touch, wedging the sync behind advice to run
a resolver that printed "no conflict markers — skipping").

Use --quiet-if-clean to suppress the "no conflict markers" message when
invoked by automation.

Line endings
------------
Files are read with `splitlines()` and written back joined with "\n", so
CRLF becomes LF. Nothing in this repo writes CRLF, and preserving mixed
endings through a union is not worth the complexity — but it is a rewrite,
so it is recorded here rather than left to be discovered.

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
from dataclasses import dataclass
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

    Shape only: whether it ACTS as a marker depends on where it sits, which
    is what `analyse` decides. Matching is against whole-line forms, not
    substrings, so memory content that happens to contain `=======` or
    `<<<<<<<` inside a larger JSON string does not trigger a false positive.
    """
    return (
        line.startswith(CONFLICT_START_PREFIX)
        or line.startswith(CONFLICT_END_PREFIX)
        or line.startswith(CONFLICT_BASE_PREFIX)
        or line == CONFLICT_SEPARATOR
    )


@dataclass(frozen=True)
class Analysis:
    """What a file's conflict markers add up to."""

    blocks: list[tuple[int, int]]  # (opener index, closer index), 0-based
    problems: list[str]  # human-readable, line-numbered, in file order

    @property
    def needs_human(self) -> bool:
        """True when this script must not rewrite the file at all."""
        return bool(self.problems)

    @property
    def resolvable(self) -> bool:
        """True when there is a well-formed conflict this script can union."""
        return bool(self.blocks) and not self.problems

    @property
    def summary(self) -> str:
        """One line, for a caller that has to explain this to a human."""
        if self.problems:
            return "; ".join(self.problems)
        if self.blocks:
            return f"{len(self.blocks)} conflict block(s)"
        return ""


def analyse(lines: list[str]) -> Analysis:
    """
    Locate every conflict block, and every reason not to trust the file.

    The block structure has to BALANCE (audit C3, fifth re-audit): an
    opener inside an open block, a block that is never closed, a closer
    with no opener, a separator or base marker outside any block, or a
    block with no separator all mean this script cannot know which side a
    given line belongs to. Two openers before a closer used to be rewritten
    into a file that still held a live `=======` and `>>>>>>> `, reported
    as "resolved 2 blocks", exit 0.
    """
    blocks: list[tuple[int, int]] = []
    problems: list[str] = []
    open_at: int | None = None

    for index, line in enumerate(lines):
        number = index + 1
        if line.startswith(CONFLICT_START_PREFIX):
            if open_at is None:
                open_at = index
            else:
                problems.append(
                    f"line {number}: conflict opener inside the block opened "
                    f"at line {open_at + 1}"
                )
        elif line.startswith(CONFLICT_END_PREFIX):
            if open_at is None:
                problems.append(f"line {number}: conflict closer with no opener above it")
            else:
                blocks.append((open_at, index))
                open_at = None
        elif open_at is None and (
            line == CONFLICT_SEPARATOR or line.startswith(CONFLICT_BASE_PREFIX)
        ):
            problems.append(f"line {number}: {line!r} outside any conflict block")

    if open_at is not None:
        problems.append(f"line {open_at + 1}: conflict block is never closed")

    for start, end in blocks:
        if not any(lines[k] == CONFLICT_SEPARATOR for k in range(start + 1, end)):
            problems.append(
                f"line {start + 1}: conflict block has no '{CONFLICT_SEPARATOR}' separator"
            )

    return Analysis(blocks=blocks, problems=problems)


def has_conflict_markers(lines: list[str]) -> bool:
    """True iff the file holds at least one complete conflict block."""
    return bool(analyse(lines).blocks)


def marker_lines_outside_blocks(lines: list[str]) -> list[str]:
    """Every reason a human, not this script, has to look at the file."""
    return analyse(lines).problems


def strip_conflict_markers(lines: list[str]) -> list[str]:
    """
    Return the union of both sides of every conflict block.

    Removed: the marker lines themselves, and any diff3/zdiff3 merge-base
    section. Kept: everything else, including marker-shaped lines outside a
    block — `analyse` refuses such files before this is ever called, and a
    line outside a block is content whose side cannot be known (audit C1,
    fourth re-audit).

    The base section is dropped whole rather than unioned. The correct
    resolution of an append-only conflict is `ours` ∪ `theirs`; the base is
    neither. Anything in it that survived is already in one of the two
    sides, and anything that did not was deleted deliberately — unioning it
    back in resurrects deleted records.

    Where the base ends is the LAST `=======` before the block's closer,
    not the first (audit M1, fifth re-audit): a base section that itself
    contains a line reading `=======` otherwise ends early, and the real
    base content after it is unioned back in. The cost of that rule is a
    block whose THEIRS side contains a literal `=======` line, where the
    split lands too late; JSONL cannot produce one, and the alternative
    loses records on every diff3 conflict.
    """
    analysis = analyse(lines)
    drop: set[int] = set()
    for start, end in analysis.blocks:
        drop.add(start)
        drop.add(end)
        separators = [k for k in range(start + 1, end) if lines[k] == CONFLICT_SEPARATOR]
        if not separators:
            continue  # `analyse` has already refused this file
        separator = separators[-1]
        bases = [
            k
            for k in range(start + 1, separator)
            if lines[k].startswith(CONFLICT_BASE_PREFIX)
        ]
        if bases:
            drop.update(range(bases[0], separator))
        drop.add(separator)
    return [line for index, line in enumerate(lines) if index not in drop]


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


#: `resolve` return values below zero are statuses, not block counts.
MISSING_FILE = -2
NEEDS_HUMAN = -3


def describe(path: Path, analysis: Analysis) -> str:
    """One line a caller can put in front of a human."""
    return f"{path}: {analysis.summary}"


def check(path: Path) -> int:
    """
    Classify `path` without touching it. Prints one line describing it.

    Returns the process exit code: 0 clean, 1 a conflict this script can
    resolve, 2 no such file, 3 needs a human. daily-sync.sh's guard calls
    this rather than pattern-matching the file itself, so the two cannot
    disagree about what a conflict is (audit C2, fifth re-audit).
    """
    if not path.exists():
        print(f"ERROR: {path} does not exist", file=sys.stderr)
        return 2
    analysis = analyse(path.read_text(encoding="utf-8").splitlines())
    if analysis.needs_human:
        print(describe(path, analysis))
        return 3
    if analysis.blocks:
        print(describe(path, analysis))
        return 1
    return 0


def resolve(path: Path, quiet_if_clean: bool) -> int:
    """
    Resolve conflicts in `path`. Returns the number of conflict blocks
    removed (0 if the file was already clean), or a negative status.
    """
    if not path.exists():
        print(f"ERROR: {path} does not exist", file=sys.stderr)
        return MISSING_FILE

    lines = path.read_text(encoding="utf-8").splitlines()
    analysis = analyse(lines)
    if analysis.needs_human:
        # Nothing is written. Without a balanced structure there is no way
        # to tell which side a line belongs to, and guessing is how a
        # concurrent session's work gets destroyed. Say exactly which
        # lines: daily-sync.sh's gate quotes this at the operator.
        print(
            f"ERROR: {path} needs a human, not this script — "
            + analysis.summary
            + ". Edit those lines by hand, then re-run the sync.",
            file=sys.stderr,
        )
        return NEEDS_HUMAN

    if not analysis.blocks:
        if not quiet_if_clean:
            print(f"{path}: no conflict markers — skipping")
        return 0

    cleaned = strip_conflict_markers(lines)
    before = len(cleaned)

    if path.name == "memories.jsonl":
        deduped = dedup_jsonl_by_id(cleaned)
    else:
        deduped = dedup_by_line(cleaned)

    atomic_write(path, "\n".join(deduped) + "\n")
    print(
        f"{path}: resolved {len(analysis.blocks)} conflict block(s) "
        f"({before} lines → {len(deduped)} after dedup)"
    )
    return len(analysis.blocks)


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
    parser.add_argument(
        "--check",
        action="store_true",
        help="Classify the files without changing them (0 clean, 1 resolvable, 3 manual)",
    )
    args = parser.parse_args()

    if args.check:
        worst = 0
        for path in args.paths:
            status = check(path)
            # 3 (needs a human) outranks 2 (missing) outranks 1.
            worst = max(worst, status)
        return worst

    total_blocks = 0
    for path in args.paths:
        result = resolve(path, args.quiet_if_clean)
        if result == MISSING_FILE:
            return 2
        if result == NEEDS_HUMAN:
            return 3
        total_blocks += result

    if total_blocks == 0 and not args.quiet_if_clean:
        print("No conflicts to resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
