#!/usr/bin/env python3
"""
index-session-content.py — populate the session_chunks transcript-content index.

Walks the cc-archives tree, parses each session transcript LINE BY LINE (never
collapsing newlines — see archive-search-crash-diagnosis-2026-06-21.md), extracts
the clean human/assistant prose (one chunk per conversational turn, skipping
thinking and tool noise), and upserts it into the PostgreSQL `session_chunks`
table. That table's GENERATED tsvector column auto-builds the full-text index.

This is the one place transcripts are decompressed; steady-state search then runs
entirely against the index and never touches a .gz. Safe by construction:
streaming gzip, one JSON line at a time, bounded memory, single process, niced.

Idempotent + incremental: a file is skipped when its mtime matches what was last
indexed, so re-runs are cheap. `--force` reindexes regardless. Re-indexing a file
replaces its rows transactionally (no stale turns).

Usage:
    venv/bin/python3 scripts/index-session-content.py            # all projects
    venv/bin/python3 scripts/index-session-content.py --project inscriptions
    venv/bin/python3 scripts/index-session-content.py --force
    venv/bin/python3 scripts/index-session-content.py --include-subagents

Scope note: by default only main session transcripts (session.jsonl.gz) are
indexed — that is the human↔assistant conversation. Subagent transcripts are
mostly tool work; include them with --include-subagents.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
from pathlib import Path

DB_NAME = "claude_memories"
DEFAULT_ARCHIVE_ROOT = Path.home() / "cc-archives"
# Defence-in-depth cap: natural turn text is small; this only guards against a
# pathological block. Far below anything that would stress the row.
MAX_CHUNK_CHARS = 100_000

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("index-session-content")


# --- Transcript parsing (line-oriented, bounded) ----------------------------

def extract_turn_text(record: dict) -> str | None:
    """Return the clean prose of one user/assistant turn, or None to skip it.

    Keeps: user string content, and `text` blocks from either role. Drops:
    thinking, tool_use, tool_result blocks, and all non-message record types
    (permission-mode, attachment, system, …). This keeps the index prose-only,
    so searches match conversation, not tool noise or base64.
    """
    if record.get("type") not in ("user", "assistant"):
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None

    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
        return text or None
    if not isinstance(content, list):
        return None

    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            piece = (block.get("text") or "").strip()
            if piece:
                parts.append(piece)
    if not parts:
        return None
    text = "\n".join(parts)
    return text[:MAX_CHUNK_CHARS] if len(text) > MAX_CHUNK_CHARS else text


def iter_turns(gz_path: Path):
    """Yield (turn_idx, role, text) for each prose turn in one transcript.

    Streams the gzip one line at a time; a malformed line is skipped, never
    fatal. turn_idx is the ordinal of the source record in the file, so it is a
    stable handle for later retrieval of the exact turn.
    """
    try:
        with gzip.open(gz_path, "rt", errors="replace") as handle:
            for idx, line in enumerate(handle):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                text = extract_turn_text(record)
                if text is None:
                    continue
                role = (record.get("message") or {}).get("role") or record.get("type")
                yield idx, role, text
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        logger.warning("  skipped %s (%s)", gz_path.name, exc)


# --- Archive discovery ------------------------------------------------------

def session_id_for(session_dir: Path) -> str | None:
    """Read the session UUID from session.meta.json, if present."""
    meta = session_dir / "session.meta.json"
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text())
        return (data.get("session") or {}).get("id")
    except (OSError, json.JSONDecodeError):
        return None


def discover(archive_root: Path, project: str | None, include_subagents: bool):
    """Yield (gz_path, project, session_dir) for transcripts to index.

    Archive layout: <root>/<project>/<session-dir>/session.jsonl.gz, with
    subagent transcripts under <session-dir>/subagents/*.jsonl.gz.
    """
    project_roots = [archive_root / project] if project else \
        [d for d in sorted(archive_root.iterdir()) if d.is_dir() and not d.name.startswith("_")]
    for proj_root in project_roots:
        if not proj_root.is_dir():
            continue
        proj_name = proj_root.name
        for session_dir in sorted(p for p in proj_root.iterdir() if p.is_dir()):
            main = session_dir / "session.jsonl.gz"
            if main.is_file():
                yield main, proj_name, session_dir
            if include_subagents:
                for sub in sorted((session_dir / "subagents").glob("*.jsonl.gz")):
                    yield sub, proj_name, session_dir


# --- Indexing ---------------------------------------------------------------

def index_archive(archive_root: Path, project: str | None,
                  include_subagents: bool, force: bool) -> tuple[int, int, int]:
    """Index matching transcripts. Returns (files_indexed, files_skipped, chunks)."""
    import psycopg2
    from psycopg2.extras import execute_values

    conn = psycopg2.connect(dbname=DB_NAME)
    conn.autocommit = False
    files_indexed = files_skipped = total_chunks = 0
    try:
        with conn.cursor() as cur:
            for gz_path, proj_name, session_dir in discover(
                    archive_root, project, include_subagents):
                rel_path = str(gz_path.relative_to(archive_root))
                mtime = gz_path.stat().st_mtime

                # Incremental skip: already indexed at this mtime?
                if not force:
                    cur.execute(
                        "SELECT 1 FROM session_chunks WHERE archive_path = %s "
                        "AND source_mtime = %s LIMIT 1", (rel_path, mtime))
                    if cur.fetchone():
                        files_skipped += 1
                        continue

                sess_id = session_id_for(session_dir)
                rows = [
                    (sess_id, proj_name, session_dir.name, rel_path, turn_idx,
                     role, text, len(text), mtime)
                    for turn_idx, role, text in iter_turns(gz_path)
                ]

                # Replace this file's rows transactionally (no stale turns).
                # Known limitation: a file with ZERO extractable prose turns
                # records no row, so its mtime is never stored and it is
                # re-parsed every run. Dormant for main transcripts (every real
                # session has ≥1 user turn); only bites pure-tool subagent files
                # (--include-subagents) or corrupt archives, at a cost of one
                # cheap re-parse per run. Accepted rather than adding a separate
                # indexed-files table for a negligible, self-limiting cost.
                cur.execute("DELETE FROM session_chunks WHERE archive_path = %s",
                            (rel_path,))
                if rows:
                    execute_values(
                        cur,
                        "INSERT INTO session_chunks (session_id, project, archive_dir, "
                        "archive_path, turn_idx, role, text, char_len, source_mtime) "
                        "VALUES %s ON CONFLICT (archive_path, turn_idx) DO UPDATE SET "
                        "text = EXCLUDED.text, role = EXCLUDED.role, "
                        "char_len = EXCLUDED.char_len, source_mtime = EXCLUDED.source_mtime, "
                        "indexed_at = NOW()",
                        rows)
                conn.commit()
                files_indexed += 1
                total_chunks += len(rows)
                logger.info("  indexed %-22s %-45s %4d turns",
                            proj_name, session_dir.name[:45], len(rows))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return files_indexed, files_skipped, total_chunks


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Populate the session_chunks index.")
    parser.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT),
                        help="Archive root (default: ~/cc-archives).")
    parser.add_argument("--project", default=None,
                        help="Index only this project sub-directory (e.g. inscriptions).")
    parser.add_argument("--include-subagents", action="store_true",
                        help="Also index subagent transcripts (default: main only).")
    parser.add_argument("--force", action="store_true",
                        help="Reindex even if the file mtime is unchanged.")
    args = parser.parse_args(argv)

    # Be a polite background citizen on the shared desktop (CPU only; this is
    # local parse work, no API). The shell never needs to wrap this.
    try:
        os.nice(10)
    except (OSError, PermissionError):
        pass

    archive_root = Path(args.archive_root).expanduser()
    if not archive_root.is_dir():
        parser.error(f"archive root not found: {archive_root}")

    logger.info("Indexing session content from %s%s ...", archive_root,
                f" (project={args.project})" if args.project else "")
    try:
        indexed, skipped, chunks = index_archive(
            archive_root, args.project, args.include_subagents, args.force)
    except ImportError:
        logger.error("psycopg2 is required; install it in the venv.")
        return 2
    logger.info("Done: %d file(s) indexed, %d skipped (unchanged), %d chunks.",
                indexed, skipped, chunks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
