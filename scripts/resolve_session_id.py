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


class CatalogueError(RuntimeError):
    """``CATALOG.json`` parsed as JSON but is not the shape we expect.

    Distinct from a *missing* or *unparseable* catalogue, both of which are
    normal and degrade silently to the filesystem walk. This means the file
    is there and readable but structurally wrong — a top-level list instead
    of an object, a ``sessions`` value that is not a list, an entry that is
    not an object, or a path field that is not a string. Before audit L5
    each of those escaped as an ``AttributeError`` or ``TypeError``
    traceback and exit 1, which a caller cannot tell from "no such
    session".
    """


def resolve_via_catalogue(
    session_id: str, root: Path
) -> Path | None:
    """Fast path: look up session_id in <root>/CATALOG.json.

    Returns the archive directory, or ``None`` when the catalogue is
    absent, unparseable, or simply does not list this session — all normal,
    and the caller falls back to the filesystem walk. Raises
    :class:`CatalogueError` when the file is present and valid JSON but the
    wrong shape, which is a broken catalogue rather than a miss.
    """
    catalogue = root / "CATALOG.json"
    if not catalogue.is_file():
        return None
    try:
        data = json.loads(catalogue.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        raise CatalogueError(
            f"{catalogue}: expected a JSON object, found {type(data).__name__}"
        )
    sessions = data.get("sessions") or []
    if not isinstance(sessions, list):
        raise CatalogueError(
            f"{catalogue}: 'sessions' must be a list, "
            f"found {type(sessions).__name__}"
        )

    for entry in sessions:
        if not isinstance(entry, dict):
            raise CatalogueError(
                f"{catalogue}: session entries must be objects, "
                f"found {type(entry).__name__}"
            )
        if entry.get("id") != session_id:
            continue
        # Catalogue entries record a path relative to the archive root.
        # Field name has shifted between schema versions; try both.
        rel = (
            entry.get("path")
            or entry.get("archive_relpath")
            or entry.get("relative_path")
        )
        if not rel:
            continue
        if not isinstance(rel, str):
            raise CatalogueError(
                f"{catalogue}: path for session {session_id} must be a "
                f"string, found {type(rel).__name__}"
            )
        if not _within_root(root, rel):
            # Say so rather than falling through silently: a catalogue
            # pointing outside its own archive is a defect somebody needs
            # to fix, and the filesystem walk that follows will otherwise
            # make the rejection look like an ordinary catalogue miss.
            print(
                f"resolve-session-id: ignoring catalogue path for "
                f"{session_id}: {rel!r} escapes the archive root {root}",
                file=sys.stderr,
            )
            continue
        candidate = root / rel
        if candidate.exists():
            return candidate
    return None


def _within_root(root: Path, rel: str) -> bool:
    """True iff ``root / rel`` stays inside *root* (audit R13).

    ``CATALOG.json`` is data, not code: an absolute ``rel`` silently
    replaces the archive root (``Path("/a") / "/etc"`` is ``/etc``), and a
    ``../`` chain walks out of it. Either way the resolver would hand a
    caller -- tier-3 verification, a FAIR export -- a path from outside the
    archive as though it were an archived session. Checked on the resolved
    forms so a symlinked component cannot smuggle the escape past us.
    """
    try:
        target = (root / rel).resolve()
        base = root.resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return target == base or base in target.parents


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
    """CLI entry point. Exit 0 with the path, 1 for not found, 2 for errors."""
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    session_id = sys.argv[1]
    root = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_ROOT
    try:
        result = resolve(session_id, root)
    except CatalogueError as exc:
        # A structurally broken catalogue (audit L5). Exit 2, as the
        # docstring promises for IO/usage errors, rather than a traceback
        # that a caller cannot distinguish from "not found".
        print(f"resolve-session-id: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # The default root is an NFS/SMB mount of the rpi share (audit
        # R14). A stale or unmounted share makes is_dir() or rglob() raise
        # mid-walk, and the docstring already promised exit 2 for an IO
        # error -- what actually happened was a traceback and exit 1,
        # indistinguishable to a caller from "no such session".
        print(f"resolve-session-id: cannot read {root}: {exc}", file=sys.stderr)
        return 2
    if result is not None:
        print(result)
        return 0
    print(f"NOT FOUND: {session_id}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
