#!/usr/bin/env python3
"""check-archive-drift.py — raw↔archive reconciliation for session transcripts.

The source↔destination class-fix (tasks/backlog.md, captured 2026-07-31; the
transcript instance of the same failure class as the memory store's
check-memory-drift.py). A pipeline whose destination silently diverges from
its source produced: the B8 un-archived batches (77 sessions found
2026-07-28), the memory JSONL pre-commit losses (×3), and the below-cursor
splices (×2). Every instance was individually contained; this check makes
the class visible the day it recurs.

What it compares, per machine:

  SOURCE:      ~/.claude/projects/<cwd-key>/*.jsonl   (this machine's live
               working transcripts — top level only; `subagents/` and flat
               `agent-*.jsonl` files are agent transcripts archived inside
               their parent, never sessions in their own right)
  DESTINATION: ~/cc-archives/**/session.meta.json     (the full local
               mirror, walked recursively — depth must never decide
               visibility)

Design constraints, learned from the 2026-07-28 diagnosis (§7b/§9.5):

  * Substantive sessions only. Sessions below a distilled-content floor
    (~1,000 tokens of conversational prose) are skipped by design — 71
    such sessions were deliberately left un-archived on 2026-07-28, and a
    check that re-flags them forever trains the reader to ignore it.
  * Union of machines. This check reads only the LOCAL raw store; the
    archive mirror is corpus-wide. Running it on every machine (it rides
    daily-sync.sh) covers the union — on 2026-07-28 a single-machine check
    would have reported the archive complete while 55 of 77 gap sessions
    sat on the other machine.
  * Grace window. A session younger than GRACE_HOURS is not yet expected
    in the archive (hooks archive at SessionEnd/PreCompact), so it is
    counted separately, never flagged.

Output: a gate file (~/.cache/cc-archive-drift-gate) in the standard gate
format — first line is the count of missing substantive sessions, following
lines name them. daily-sync-trigger.sh surfaces a non-zero count at session
start. Read-only: this script never archives, never writes to the stores.

Usage:
    venv/bin/python3 scripts/check-archive-drift.py             # report + gate
    venv/bin/python3 scripts/check-archive-drift.py --quiet-if-clean

Exit codes: 0 clean, 1 drift found, 2 could not run.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

RAW_ROOT = Path.home() / ".claude" / "projects"
ARCHIVE_ROOT = Path.home() / "cc-archives"
GATE_FILE = Path.home() / ".cache" / "cc-archive-drift-gate"

# ~1,000 tokens of conversational prose, approximated as chars/4. Matches
# the --min-content-tokens floor bulk-archive.py adopted on 2026-07-28
# (turn count is NOT a substance proxy — a 205k-token session can be two
# turns).
MIN_CONTENT_CHARS = 4_000
GRACE_HOURS = 48

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("check-archive-drift")


def raw_session_content_chars(path: Path, threshold: int) -> int:
    """Approximate distilled conversational content, stopping at threshold.

    Counts characters of user/assistant prose (string content and `text`
    blocks), ignoring tool traffic, thinking, and machine-injected records
    — the same notion of substance the archiver's floor uses. Streams the
    file and returns early once the threshold is crossed, so the common
    (clearly substantive) case costs almost nothing.
    """
    total = 0
    try:
        with open(path, "rt", errors="replace", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if record.get("type") not in ("user", "assistant"):
                    continue
                if record.get("isMeta") or record.get("isCompactSummary"):
                    continue
                message = record.get("message")
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    total += len(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            total += len(block.get("text") or "")
                if total >= threshold:
                    return total
    except OSError:
        return 0
    return total


def is_agent_transcript(path: Path) -> bool:
    """True for flat agent transcripts (agent-*.jsonl) — never sessions."""
    return path.name.startswith("agent-")


def collect_raw_sessions() -> tuple[dict[str, Path], int, int]:
    """Return ({session_id: path}, n_trivial, n_in_grace) for the local raw store."""
    sessions: dict[str, Path] = {}
    trivial = grace = 0
    now = time.time()
    for project_dir in sorted(RAW_ROOT.iterdir()):
        if not project_dir.is_dir():
            continue
        for jsonl in project_dir.glob("*.jsonl"):
            if is_agent_transcript(jsonl):
                continue
            if now - jsonl.stat().st_mtime < GRACE_HOURS * 3600:
                grace += 1
                continue
            if raw_session_content_chars(jsonl, MIN_CONTENT_CHARS) < MIN_CONTENT_CHARS:
                trivial += 1
                continue
            sessions[jsonl.stem] = jsonl
    return sessions, trivial, grace


def collect_archived_ids() -> tuple[set[str], int]:
    """Return (session ids present in the archive mirror, n_duplicate_dirs)."""
    ids: set[str] = set()
    seen_twice = 0
    for meta_path in ARCHIVE_ROOT.rglob("session.meta.json"):
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        sid = (meta.get("session") or {}).get("id")
        if not sid:
            continue
        if sid in ids:
            seen_twice += 1
        ids.add(sid)
    return ids, seen_twice


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet-if-clean", action="store_true",
                        help="Print nothing when no drift is found.")
    args = parser.parse_args(argv)

    if not RAW_ROOT.is_dir() or not ARCHIVE_ROOT.is_dir():
        logger.error("store missing (raw=%s archive=%s) — cannot run",
                     RAW_ROOT.is_dir(), ARCHIVE_ROOT.is_dir())
        return 2

    raw, n_trivial, n_grace = collect_raw_sessions()
    archived, n_dup = collect_archived_ids()

    missing = {sid: path for sid, path in raw.items() if sid not in archived}

    GATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [str(len(missing))]
    for sid, path in sorted(missing.items())[:20]:
        lines.append(f"{sid}  ({path.parent.name})")
    if len(missing) > 20:
        lines.append(f"... +{len(missing) - 20} more")
    GATE_FILE.write_text("\n".join(lines) + "\n")

    if missing:
        logger.warning("ARCHIVE DRIFT: %d substantive raw session(s) on this "
                       "machine have NO archive entry:", len(missing))
        for sid, path in sorted(missing.items()):
            logger.warning("  %s  (%s)", sid, path.parent.name)
        logger.warning("Archive them with scripts/bulk-archive.py (raw-first; "
                       "see transcript-archive-diagnosis-2026-07-28.md §9).")
        return 1

    if not args.quiet_if_clean:
        logger.info("Clean — every substantive raw session is archived "
                    "(raw substantive=%d, trivial=%d, in-grace=%d, "
                    "archived ids=%d, duplicate archive dirs=%d)",
                    len(raw), n_trivial, n_grace, len(archived), n_dup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
