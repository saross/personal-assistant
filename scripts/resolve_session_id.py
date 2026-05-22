#!/usr/bin/env python3
"""
Cross-machine session-id resolver — Phase 0 Step 9.

Given a Claude Code session UUID, return the canonical archive path under
~/mnt/rpi-shares/cc-archives-consolidated/ (or a custom archive root).
Used as the source-of-truth lookup when a session_id needs to be traced
to its on-disk transcript — by tier-3 memory verification, downstream
research workflows, RO-Crate / FAIR consumers, etc.

Resolution strategy (in order of speed):
  1. ``CATALOG.json`` lookup — fast path for catalogued sessions. The
     catalogue tracks active-project top-level sessions but
     ``rebuild_catalogue`` scans one level deep, so nested sub-category
     sessions (e.g. ``LLM-History-Paper/theseus-ship/...``) and
     ``_legacy/*`` content may not appear here.
  2. Filesystem ``rglob`` fallback — slower but exhaustive. Walks every
     ``session.meta.json`` under the archive root and matches
     ``meta.session.id``. Catches everything the catalogue misses.

Usage:
    resolve_session_id.py <session_id>
    resolve_session_id.py <session_id> <archive_root>

Exit 0 with the resolved path printed to stdout if found.
Exit 1 with NOT FOUND message to stderr if not.
Exit 2 for usage / IO errors.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_ROOT = Path.home() / "mnt" / "rpi-shares" / "cc-archives-consolidated"


def resolve_via_catalogue(
    session_id: str, root: Path
) -> Path | None:
    """Fast path: look up session_id in <root>/CATALOG.json."""
    catalogue = root / "CATALOG.json"
    if not catalogue.is_file():
        return None
    try:
        data = json.loads(catalogue.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for entry in data.get("sessions", []) or []:
        if entry.get("id") != session_id:
            continue
        # Catalogue entries record a path relative to the archive root.
        # Field name has shifted between schema versions; try both.
        rel = (
            entry.get("path")
            or entry.get("archive_relpath")
            or entry.get("relative_path")
        )
        if rel:
            candidate = root / rel
            if candidate.exists():
                return candidate
    return None


def resolve_via_filesystem(
    session_id: str, root: Path
) -> Path | None:
    """
    Slow fallback: rglob every ``session.meta.json`` under *root* and
    return the parent dir whose ``meta.session.id`` matches.
    """
    for meta in root.rglob("session.meta.json"):
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if m.get("session", {}).get("id") == session_id:
            return meta.parent
    return None


def resolve(session_id: str, root: Path = DEFAULT_ROOT) -> Path | None:
    """
    Resolve a session_id to its archive dir.

    Returns the directory containing ``session.jsonl(.gz)`` and
    ``session.meta.json`` for the matching session, or ``None`` if
    no match is found under *root*.
    """
    if not root.is_dir():
        return None
    hit = resolve_via_catalogue(session_id, root)
    if hit is not None:
        return hit
    return resolve_via_filesystem(session_id, root)


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    session_id = sys.argv[1]
    root = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_ROOT
    result = resolve(session_id, root)
    if result is not None:
        print(result)
        return 0
    print(f"NOT FOUND: {session_id}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
