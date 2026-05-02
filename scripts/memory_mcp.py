#!/usr/bin/env python3
"""
MCP memory server — exposes the personal-assistant memory database.

A local Model Context Protocol (MCP) server that wraps the existing
fetch-memories query engine and makes it available to any Claude instance
(Claude Desktop, claude.ai, Claude Code) as a set of tools.

Read-only. All tools go through the ``active_memories`` PostgreSQL view
(decay rules applied) with JSONL fallback for offline scenarios.

Transport: stdio (default). Run directly:

    venv/bin/python3 scripts/memory_mcp.py

Or register with Claude Code:

    claude mcp add memory --scope user \\
        /home/shawn/personal-assistant/venv/bin/python3 \\
        -- /home/shawn/personal-assistant/scripts/memory_mcp.py

Critical invariant: never write to stdout. It corrupts the JSON-RPC stream.
All logging must go to stderr.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

# -------------------------------------------------------------------------
# Logging (stderr only — stdout is reserved for JSON-RPC)
# -------------------------------------------------------------------------

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[memory-mcp] %(levelname)s: %(message)s",
)
logger = logging.getLogger("memory-mcp")


# -------------------------------------------------------------------------
# Reuse the existing query engine
# -------------------------------------------------------------------------

# Load the hyphenated fetch-memories module via spec_from_file_location
# (avoids permanently mutating sys.path)
SCRIPT_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "fetch_memories", SCRIPT_DIR / "fetch-memories.py",
)
fetch_memories = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_memories)

DB_NAME = "claude_memories"
READ_ONLY = ToolAnnotations(readOnlyHint=True)

# Schema-version guard (audit IC5 / B-X1). Imported here so MCP tools
# can call ``assert_schema_version`` on every connection they open.
sys.path.insert(0, str(SCRIPT_DIR))
from _schema_version import assert_schema_version, SchemaVersionError  # noqa: E402


# -------------------------------------------------------------------------
# PostgreSQL helpers (only needed for tools not covered by fetch-memories)
# -------------------------------------------------------------------------

def _pg_connect() -> tuple[Any | None, str | None]:
    """
    Open a fresh PostgreSQL connection.

    Returns (connection, None) on success, (None, error_message) on
    failure. The error message is propagated to the MCP client so the
    caller can see *why* the connection failed (not just that it did).
    """
    try:
        import psycopg2
    except ImportError:
        msg = "psycopg2 not installed"
        logger.warning(msg)
        return None, msg
    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except Exception as exc:  # noqa: BLE001 — graceful degradation
        msg = f"PostgreSQL unavailable: {exc}"
        logger.warning(msg)
        return None, msg

    # Schema-version guard (audit IC5). Surface the mismatch through
    # the same (None, error) channel the connection failure path uses
    # — this keeps the MCP tool layer's error semantics uniform.
    try:
        assert_schema_version(conn)
    except SchemaVersionError as exc:
        conn.close()
        msg = str(exc)
        logger.error(msg)
        return None, msg
    return conn, None


def _row_to_memory(
    row: tuple[Any, ...], columns: list[str],
) -> dict[str, Any]:
    """
    Convert a DB row to a memory dict, serialising types json.dumps
    cannot handle natively (datetime, date, Decimal).
    """
    from decimal import Decimal
    from datetime import date as _date

    record: dict[str, Any] = {}
    for i, col in enumerate(columns):
        value = row[i]
        if isinstance(value, datetime):
            value = value.isoformat()
        elif isinstance(value, _date):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = float(value)
        record[col] = value
    return record


# -------------------------------------------------------------------------
# Output envelope
# -------------------------------------------------------------------------

def _envelope(
    results: list[dict[str, Any]],
    source: str,
    note: str | None = None,
) -> str:
    """
    Build the standard JSON response envelope.

    All tools return JSON strings with this shape so clients can parse
    them consistently:

        {
          "count": N,
          "results": [...],
          "source": "postgres" | "jsonl" | "none",
          "note": "optional human-readable context"
        }
    """
    payload: dict[str, Any] = {
        "count": len(results),
        "results": results,
        "source": source,
    }
    if note:
        payload["note"] = note
    return json.dumps(
        payload, ensure_ascii=False, indent=2, default=str,
    )


def _error_envelope(message: str) -> str:
    """Build a standardised error response."""
    return json.dumps(
        {"count": 0, "results": [], "source": "none", "error": message},
        ensure_ascii=False,
        indent=2,
        default=str,
    )


# -------------------------------------------------------------------------
# MCP server instance
# -------------------------------------------------------------------------

mcp = FastMCP("personal-assistant-memory")


# -------------------------------------------------------------------------
# Tool: search_memories
# -------------------------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
async def search_memories(
    query: Annotated[
        str | None,
        Field(description="Free-text search across content, summary, and source context"),
    ] = None,
    category: Annotated[
        str | None,
        Field(description="Exact category match (e.g. 'decision', 'source_insight')"),
    ] = None,
    tags: Annotated[
        list[str] | None,
        Field(description="Filter by research tags (array overlap, case-insensitive)"),
    ] = None,
    project: Annotated[
        str | None,
        Field(description="Filter by project (encoded cwd, e.g. '-home-shawn-personal-assistant')"),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=50, description="Maximum results to return (1-50)"),
    ] = 10,
) -> str:
    """
    Search memories by keyword, category, tags, or project.

    At least one filter is required. Returns active memories (decay rules
    applied via the active_memories view). Uses PostgreSQL full-text
    search when available, falls back to JSONL substring matching
    otherwise.
    """
    # Normalise tags: None and [] are both "no filter"
    tag_list = tags if tags else None

    if not any([query, category, tag_list, project]):
        return _error_envelope(
            "At least one filter required: query, category, tags, or project"
        )

    # Try PostgreSQL first (applies decay rules + FTS + server-side
    # project filter so LIMIT doesn't drop legitimate matches)
    results = fetch_memories.try_postgres(
        tags=tag_list,
        query=query,
        category=category,
        memory_id=None,
        limit=limit,
        project=project,
    )

    if results is not None:
        return _envelope(results, source="postgres")

    # Fall back to JSONL (no decay rules applied)
    try:
        all_memories = fetch_memories.load_jsonl_memories()
        filtered = [
            m for m in all_memories
            if fetch_memories.matches_filters(
                m,
                tags=tag_list,
                query=query,
                category=category,
                memory_id=None,
            )
            and (not project or m.get("project") == project)
        ]
        filtered.sort(
            key=lambda m: m.get("created_at", ""), reverse=True,
        )
        return _envelope(
            filtered[:limit],
            source="jsonl",
            note="PostgreSQL unavailable; using JSONL fallback (decay rules NOT applied)",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"JSONL fallback failed: {exc}")
        return _error_envelope(f"Memory lookup failed: {exc}")


# -------------------------------------------------------------------------
# Tool: semantic_search
# -------------------------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
async def semantic_search(
    query: Annotated[
        str,
        Field(min_length=1, description="Search query for semantic similarity matching"),
    ],
    category: Annotated[
        str | None,
        Field(description="Optional category filter"),
    ] = None,
    tags: Annotated[
        list[str] | None,
        Field(description="Optional tag filter (array overlap)"),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=50),
    ] = 10,
    min_similarity: Annotated[
        float,
        Field(
            ge=0.0, le=1.0,
            description="Minimum cosine similarity (0-1); results below are dropped",
        ),
    ] = 0.0,
) -> str:
    """
    Semantic similarity search using pgvector embeddings.

    Generates an embedding for the query via Ollama, then finds the
    closest memories by cosine similarity. Requires Ollama and pgvector
    to be available; returns an error otherwise (FTS tools still work).
    """
    tag_list = tags if tags else None

    # Over-fetch when a similarity threshold is set: try_semantic
    # sorts by cosine distance, so truncating at `limit` before
    # filtering by min_similarity can drop matches further down the
    # ranking. Fetch up to 50 and apply the filter client-side, then
    # truncate to the requested limit.
    fetch_limit = 50 if min_similarity > 0 else limit

    results = fetch_memories.try_semantic(
        query=query,
        category=category,
        tags=tag_list,
        limit=fetch_limit,
    )

    if results is None:
        return _error_envelope(
            "Semantic search unavailable — Ollama or pgvector not reachable. "
            "Use search_memories for full-text search instead."
        )

    # Apply minimum similarity filter, then truncate to requested limit
    if min_similarity > 0:
        results = [
            r for r in results
            if r.get("similarity", 0) >= min_similarity
        ]
    results = results[:limit]

    return _envelope(results, source="postgres")


# -------------------------------------------------------------------------
# Tool: get_memory
# -------------------------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
async def get_memory(
    memory_id: Annotated[
        str,
        Field(min_length=1, description="Memory ID (format: YYYY-MM-DD-<hash>)"),
    ],
) -> str:
    """
    Fetch a single memory by its ID.

    Returns the full memory record including content, tags, and
    metadata. Uses the active_memories view (decayed memories excluded).
    """
    results = fetch_memories.try_postgres(
        memory_id=memory_id, limit=1,
    )

    if results is not None:
        if not results:
            return _error_envelope(
                f"Memory {memory_id} not found (may be decayed or never existed)"
            )
        return _envelope(results, source="postgres")

    # JSONL fallback — scan for matching ID
    try:
        all_memories = fetch_memories.load_jsonl_memories()
        for mem in all_memories:
            if mem.get("id") == memory_id:
                return _envelope(
                    [mem],
                    source="jsonl",
                    note=(
                        "PostgreSQL unavailable; using JSONL fallback "
                        "(decay rules NOT applied — memory may be stale)"
                    ),
                )
        return _error_envelope(f"Memory {memory_id} not found")
    except Exception as exc:  # noqa: BLE001
        return _error_envelope(f"Memory lookup failed: {exc}")


# -------------------------------------------------------------------------
# Tool: list_recent
# -------------------------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
async def list_recent(
    days: Annotated[
        int,
        Field(ge=1, le=365, description="Number of days to look back"),
    ] = 7,
    category: Annotated[
        str | None,
        Field(description="Optional category filter"),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=100),
    ] = 20,
) -> str:
    """
    List memories created in the last N days.

    Returns active memories sorted by creation time (most recent first).
    Useful for catching up on recent work or building a digest.
    """
    conn, err = _pg_connect()
    if conn is None:
        return _error_envelope(
            f"list_recent requires database access ({err})"
        )

    try:
        columns = [
            "id", "category", "content", "summary", "confidence",
            "research_tags", "source_context", "created_at", "project",
        ]
        # Use make_interval to avoid quoting a %s inside a string literal;
        # also safer if `days` type ever widens beyond int.
        sql = (
            f"SELECT {', '.join(columns)} "  # noqa: S608
            f"FROM active_memories "
            f"WHERE created_at > NOW() - make_interval(days => %s)"
        )
        params: list[Any] = [days]

        if category:
            sql += " AND category = %s"
            params.append(category)

        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        results = [_row_to_memory(row, columns) for row in rows]
        return _envelope(results, source="postgres")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"list_recent query failed: {exc}")
        return _error_envelope(f"Query failed: {exc}")
    finally:
        conn.close()


# -------------------------------------------------------------------------
# Tool: memory_statistics
# -------------------------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
async def memory_statistics() -> str:
    """
    Return aggregate statistics about the memory database.

    Includes total active count, breakdown by category, top research
    tags, and recent activity summary. Useful for understanding the
    shape of the knowledge base before running targeted searches.
    """
    conn, err = _pg_connect()
    if conn is None:
        return _error_envelope(
            f"statistics require database access ({err})"
        )

    try:
        stats: dict[str, Any] = {}
        with conn.cursor() as cur:
            # Total active memories
            cur.execute("SELECT COUNT(*) FROM active_memories")
            stats["total_active"] = cur.fetchone()[0]

            # By category
            cur.execute(
                "SELECT category, COUNT(*) as n FROM active_memories "
                "GROUP BY category ORDER BY n DESC"
            )
            stats["by_category"] = [
                {"category": row[0], "count": row[1]}
                for row in cur.fetchall()
            ]

            # Top 20 tags
            cur.execute(
                "SELECT tag, COUNT(*) as n "
                "FROM active_memories, UNNEST(research_tags) AS tag "
                "GROUP BY tag ORDER BY n DESC LIMIT 20"
            )
            stats["top_tags"] = [
                {"tag": row[0], "count": row[1]}
                for row in cur.fetchall()
            ]

            # Recent activity (last 7 days) — literal interval is fine
            # here because there's no parameter substitution.
            cur.execute(
                "SELECT COUNT(*) FROM active_memories "
                "WHERE created_at > NOW() - INTERVAL '7 days'"
            )
            stats["added_last_7_days"] = cur.fetchone()[0]

            # Projects with activity
            cur.execute(
                "SELECT project, COUNT(*) as n FROM active_memories "
                "WHERE project IS NOT NULL "
                "GROUP BY project ORDER BY n DESC LIMIT 10"
            )
            stats["top_projects"] = [
                {"project": row[0], "count": row[1]}
                for row in cur.fetchall()
            ]

        # Statistics has a different shape from memory-listing tools:
        # a single stats dict rather than a list of memory records.
        return json.dumps(
            {"source": "postgres", "stats": stats},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Statistics query failed: {exc}")
        return _error_envelope(f"Query failed: {exc}")
    finally:
        conn.close()


# -------------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting memory MCP server (stdio transport)")
    mcp.run()
