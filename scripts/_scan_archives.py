#!/usr/bin/env python3
"""
_scan_archives.py — the safe line-oriented engine behind search-archives-safe.sh.

This is the ad-hoc *fallback* scanner for cc-archives gzipped transcripts. The
everyday path is the indexed search (scripts/search-sessions.py / the
/search-sessions skill / the search_sessions MCP tool), which never touches a
.gz at query time. This engine exists for the cases the index does not cover.

WHY PYTHON, NOT ripgrep/grep
----------------------------
On this machine `rg` and `grep` are **shell functions** that route to the Claude
Code executable, not standalone binaries — they are unreliable from a
non-interactive script and were themselves part of the 2026-06-21 crash
(the harness's own ripgrep was seen OOM-killed). A pure-Python streaming scan
has no such dependency and is fully under our control.

THE SAFETY CONTRACT (from archive-search-crash-diagnosis-2026-06-21.md)
----------------------------------------------------------------------
  * Strictly line-oriented: iterate the decompressed stream one line at a time.
    Newlines are NEVER collapsed (no `tr '\\n'`), so a transcript can never
    become one multi-megabyte line — the pathology that caused the crash.
  * Bounded memory: only one line (plus a tiny context ring buffer) is resident.
  * Per-line length guard: any line longer than --max-line is truncated before
    the regex sees it, so even a pathological long line cannot trigger heavy
    backtracking (defence in depth — natural lines here top out ~90 KB).
  * Single process, files scanned sequentially. Resource limits (nice, ionice,
    timeout, cgroup) and single-run locking are imposed by the shell wrapper.

This engine prints `path:lineno: text` for matches (with optional context),
mirroring grep's familiar shape, and exits 0 on matches / 1 on none.
"""

from __future__ import annotations

import argparse
import gzip
import re
import sys
from collections import deque
from pathlib import Path

# Natural JSONL lines on this corpus top out ~90 KB; 1 MB is a generous guard
# that still defuses any pathological (e.g. accidentally-flattened) line.
DEFAULT_MAX_LINE = 1_000_000


def iter_transcripts(root: Path):
    """Yield every transcript .gz under *root*, sorted, sessions then subagents.

    Accepts either a single ``.gz`` file or a directory tree. Matches the
    archive layout: ``*/session.jsonl.gz`` plus ``*/subagents/*.jsonl.gz``.
    """
    if root.is_file():
        yield root
        return
    yield from sorted(root.rglob("session.jsonl.gz"))
    yield from sorted(root.rglob("subagents/*.jsonl.gz"))


def scan_file(
    path: Path,
    pattern: re.Pattern[str],
    *,
    context: int,
    max_line: int,
    and_pattern: re.Pattern[str] | None,
    display_root: Path,
) -> int:
    """Scan one gzipped transcript line by line. Returns the match count.

    Memory stays bounded to one line plus a ``context``-deep ring buffer; the
    file is never read whole and newlines are never collapsed.
    """
    rel = path.relative_to(display_root) if display_root in path.parents else path
    before: deque[tuple[int, str]] = deque(maxlen=context) if context else deque(maxlen=0)
    after_remaining = 0
    matches = 0
    # Highest line number already written. Lines stream in increasing order, so
    # this dedupes any overlap: an after-context line that later also qualifies
    # as before-context of a nearby match must not be emitted twice.
    last_printed = 0

    try:
        with gzip.open(path, "rt", errors="replace") as handle:
            for lineno, raw in enumerate(handle, start=1):
                line = raw.rstrip("\n")
                # Per-line guard: truncate before the regex touches it. No suffix
                # is appended — the matched/displayed text must be the real
                # content, never a marker the regex could spuriously match on.
                if len(line) > max_line:
                    line = line[:max_line]

                is_match = bool(pattern.search(line))
                if is_match and and_pattern is not None:
                    is_match = bool(and_pattern.search(line))

                if is_match:
                    matches += 1
                    for bno, btext in before:
                        if bno > last_printed:
                            sys.stdout.write(f"{rel}:{bno}- {btext}\n")
                            last_printed = bno
                    if lineno > last_printed:
                        sys.stdout.write(f"{rel}:{lineno}: {line}\n")
                        last_printed = lineno
                    before.clear()
                    after_remaining = context
                elif after_remaining > 0:
                    if lineno > last_printed:
                        sys.stdout.write(f"{rel}:{lineno}- {line}\n")
                        last_printed = lineno
                    after_remaining -= 1
                    if context:
                        before.append((lineno, line))
                elif context:
                    before.append((lineno, line))
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        # A corrupt or partial archive must never abort the whole scan.
        sys.stderr.write(f"_scan_archives: skipped {path} ({exc})\n")
    return matches


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point. Compiles the patterns and scans sequentially."""
    parser = argparse.ArgumentParser(
        description="Safe, line-oriented scan of cc-archives gzipped transcripts.",
    )
    parser.add_argument("pattern", help="Regular expression to search for.")
    parser.add_argument("path", nargs="?", default=str(Path.home() / "cc-archives"),
                        help="Archive file or subtree (default: ~/cc-archives).")
    parser.add_argument("--and", dest="and_pattern", default=None,
                        help="Second regex; a line must match BOTH to count.")
    parser.add_argument("-C", "--context", type=int, default=0,
                        help="Lines of context to show before/after each match.")
    parser.add_argument("--max-line", type=int, default=DEFAULT_MAX_LINE,
                        help=f"Truncate lines longer than this (default {DEFAULT_MAX_LINE}).")
    parser.add_argument("--ignore-case", "-i", action="store_true", default=True,
                        help="Case-insensitive (default on).")
    parser.add_argument("--case-sensitive", dest="ignore_case", action="store_false",
                        help="Make the search case-sensitive.")
    parser.add_argument("--files-with-matches", "-l", action="store_true",
                        help="Print only the paths of files that contain a match.")
    args = parser.parse_args(argv)

    flags = re.IGNORECASE if args.ignore_case else 0
    try:
        pattern = re.compile(args.pattern, flags)
        and_pattern = re.compile(args.and_pattern, flags) if args.and_pattern else None
    except re.error as exc:
        parser.error(f"invalid regex: {exc}")

    root = Path(args.path).expanduser()
    if not root.exists():
        parser.error(f"path not found: {root}")
    display_root = root if root.is_dir() else root.parent

    total = 0
    files_hit = 0
    for transcript in iter_transcripts(root):
        if args.files_with_matches:
            # Cheap path: stop at the first match per file.
            if _has_match(transcript, pattern, and_pattern, args.max_line):
                rel = transcript.relative_to(display_root) \
                    if display_root in transcript.parents else transcript
                sys.stdout.write(f"{rel}\n")
                files_hit += 1
        else:
            n = scan_file(transcript, pattern, context=args.context,
                          max_line=args.max_line, and_pattern=and_pattern,
                          display_root=display_root)
            if n:
                files_hit += 1
            total += n

    sys.stderr.write(
        f"_scan_archives: {files_hit} file(s) matched"
        + (f", {total} line(s)" if not args.files_with_matches else "") + ".\n"
    )
    return 0 if files_hit else 1


def _has_match(path: Path, pattern: re.Pattern[str],
               and_pattern: re.Pattern[str] | None, max_line: int) -> bool:
    """Return True at the first matching line (for --files-with-matches)."""
    try:
        with gzip.open(path, "rt", errors="replace") as handle:
            for raw in handle:
                line = raw.rstrip("\n")
                if len(line) > max_line:
                    line = line[:max_line]
                if pattern.search(line) and (and_pattern is None or and_pattern.search(line)):
                    return True
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        sys.stderr.write(f"_scan_archives: skipped {path} ({exc})\n")
    return False


if __name__ == "__main__":
    raise SystemExit(main())
