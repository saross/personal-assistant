#!/usr/bin/env python3
"""
search-sessions.py — fast, safe full-text search over archived session content.

This is the everyday path for "where did we discuss X across past sessions". It
queries the PostgreSQL `session_chunks` index (populated by
index-session-content.py) and NEVER decompresses a transcript at query time —
the structural fix for the 2026-06-21 archive-search crash. Results are ranked,
snippeted, and carry an archive_dir:turn_idx handle for exact retrieval.

It is the indexed rung of the escalation ladder:
    memory system (/recall)            -> what was distilled to memory
    session metadata (sessions table)  -> which session was that
    THIS (session_chunks)              -> the actual transcript content   <-- here
    --show retrieval (below)           -> the exact turn(s), verbatim
    search-archives-safe.sh            -> bounded ad-hoc .gz fallback

Usage:
    # Search (ranked full-text; websearch syntax: quotes, OR, -exclude):
    scripts/search-sessions.py "mixture model deconvolution"
    scripts/search-sessions.py "preregistration" --project inscriptions --role assistant
    scripts/search-sessions.py "Rome suggest" --limit 20          # both terms, ranked
    scripts/search-sessions.py "build_model_f1" --substring        # exact/identifier (trgm)
    scripts/search-sessions.py "OSF" --json                        # machine-readable

    # Retrieve exact turns (verbatim, from the index — no .gz access):
    scripts/search-sessions.py --show 2026-06-19T07-48_complete-... --turn 42 --context 2

The reusable search()/show_turns() functions back both this CLI and the
search_sessions MCP tool, so the safe path is available to agents too.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

DB_NAME = "claude_memories"

# Snippet markers chosen to read in a terminal and survive JSON round-trips.
_HEADLINE_OPTS = "MaxFragments=2,MaxWords=18,MinWords=5,StartSel=«,StopSel=»"


def _connect():
    """Open a psycopg2 connection to the memory DB (raises on failure)."""
    import psycopg2
    return psycopg2.connect(dbname=DB_NAME)


def search(
    query: str,
    *,
    project: str | None = None,
    role: str | None = None,
    limit: int = 10,
    substring: bool = False,
) -> list[dict[str, Any]]:
    """Search session content. Returns ranked result dicts (newest-first for substring).

    FTS mode (default) uses websearch_to_tsquery + ts_rank + ts_headline.
    substring mode uses a trigram-backed ILIKE for exact/identifier matches that
    FTS stemming would mangle. Both stay server-side and bounded by LIMIT.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            params: list[Any] = []
            if substring:
                select = (
                    "SELECT c.archive_dir, c.turn_idx, c.role, c.session_id, c.project, "
                    "s.title, s.started_at, 1.0::float AS rank, "
                    "left(c.text, 240) AS snippet "
                    "FROM session_chunks c LEFT JOIN sessions s ON s.id = c.session_id "
                    "WHERE c.text ILIKE %s"
                )
                params.append(f"%{query}%")
                order = " ORDER BY s.started_at DESC NULLS LAST, c.id DESC LIMIT %s"
            else:
                select = (
                    "SELECT c.archive_dir, c.turn_idx, c.role, c.session_id, c.project, "
                    "s.title, s.started_at, ts_rank(c.tsv, q) AS rank, "
                    f"ts_headline('english', c.text, q, '{_HEADLINE_OPTS}') AS snippet "
                    "FROM session_chunks c "
                    "CROSS JOIN websearch_to_tsquery('english', %s) q "
                    "LEFT JOIN sessions s ON s.id = c.session_id "
                    "WHERE c.tsv @@ q"
                )
                params.append(query)
                order = " ORDER BY rank DESC, s.started_at DESC NULLS LAST LIMIT %s"

            filters = ""
            if project:
                filters += " AND c.project = %s"
                params.append(project)
            if role:
                filters += " AND c.role = %s"
                params.append(role)
            params.append(limit)

            cur.execute(select + filters + order, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def show_turns(
    archive_dir: str,
    turn_idx: int,
    *,
    context: int = 2,
    project: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve a turn and its neighbours verbatim from the index (no .gz read)."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            params: list[Any] = [archive_dir, turn_idx - context, turn_idx + context]
            sql = (
                "SELECT turn_idx, role, text FROM session_chunks "
                "WHERE archive_dir = %s AND turn_idx BETWEEN %s AND %s"
            )
            if project:
                sql += " AND project = %s"
                params.append(project)
            sql += " ORDER BY turn_idx"
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


# --- CLI formatting ---------------------------------------------------------

def _format_results(rows: list[dict[str, Any]]) -> str:
    """Render search results for a terminal."""
    if not rows:
        return "No matches. (Try --substring for identifiers, or widen the query.)"
    out = []
    for r in rows:
        date = str(r.get("started_at") or "")[:10] or "????-??-??"
        title = r.get("title") or r.get("archive_dir") or "(untitled)"
        handle = f"{r['archive_dir']} #{r['turn_idx']}"
        snippet = " ".join((r.get("snippet") or "").split())
        out.append(
            f"[{date}] {r.get('project','?')} · {r.get('role','?')} · rank {r.get('rank',0):.3f}\n"
            f"  {title}\n"
            f"  {snippet}\n"
            f"  ↳ retrieve: --show {r['archive_dir']} --turn {r['turn_idx']}"
        )
    return "\n\n".join(out)


def _format_turns(rows: list[dict[str, Any]], focus: int) -> str:
    """Render retrieved turns, marking the focal one."""
    if not rows:
        return "No turns found for that archive_dir/turn."
    out = []
    for r in rows:
        marker = "▶" if r["turn_idx"] == focus else " "
        out.append(f"{marker} #{r['turn_idx']} [{r['role']}]\n{r['text']}")
    return "\n\n".join(out)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Search archived session content (indexed, safe).")
    parser.add_argument("query", nargs="?", help="Full-text query (websearch syntax).")
    parser.add_argument("--project", help="Scope to one project (e.g. inscriptions).")
    parser.add_argument("--role", choices=["user", "assistant"], help="Filter by turn role.")
    parser.add_argument("--limit", type=int, default=10, help="Max results (default 10).")
    parser.add_argument("--substring", action="store_true",
                        help="Exact/identifier match (trigram ILIKE) instead of FTS.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument("--show", metavar="ARCHIVE_DIR",
                        help="Retrieve verbatim turns from this session directory.")
    parser.add_argument("--turn", type=int, help="Turn index to retrieve (with --show).")
    parser.add_argument("--context", type=int, default=2,
                        help="Neighbour turns to include with --show (default 2).")
    args = parser.parse_args(argv)

    try:
        if args.show is not None:
            if args.turn is None:
                parser.error("--show requires --turn")
            rows = show_turns(args.show, args.turn, context=args.context, project=args.project)
            print(json.dumps(rows, ensure_ascii=False, indent=2, default=str)
                  if args.json else _format_turns(rows, args.turn))
            return 0 if rows else 1

        if not args.query:
            parser.error("a query is required (or use --show ... --turn ...)")
        rows = search(args.query, project=args.project, role=args.role,
                      limit=args.limit, substring=args.substring)
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str)
              if args.json else _format_results(rows))
        return 0 if rows else 1
    except ImportError:
        print("psycopg2 is required; install it in the venv.", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — surface DB errors cleanly to the CLI
        print(f"search-sessions: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
