#!/usr/bin/env python3
"""
Fetch full memory content for Tier 2 autonomous retrieval.

Standalone query tool invoked by Claude Code mid-conversation to
retrieve complete memory records matching tags, queries, categories,
or specific IDs.  Tries PostgreSQL first (``active_memories`` view
with decay rules), falls back to JSONL grep when the database is
unavailable.

Usage:
    python3 ~/personal-assistant/scripts/fetch-memories.py --tag validation
    python3 ~/personal-assistant/scripts/fetch-memories.py --query "GPS accuracy"
    python3 ~/personal-assistant/scripts/fetch-memories.py \\
        --category decision --query "PostgreSQL"
    python3 ~/personal-assistant/scripts/fetch-memories.py \\
        --id "2026-03-15-abc123"
    python3 ~/personal-assistant/scripts/fetch-memories.py \\
        --tag validation --tag methodology
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path(__file__).resolve().parent.parent
MEMORIES_FILE = PA_DIR / "memories" / "memories.jsonl"
CURSOR_FILE = PA_DIR / "memories" / "sync-cursors.json"
SYNC_CONFIG_FILE = PA_DIR / "data" / "config" / "sync.json"
DB_NAME = "claude_memories"
MAX_RESULTS = 10

# Freshness-warning thresholds (M3). Both must be exceeded for a warning
# to fire, so a quiet day doesn't flood stderr.
RECALL_UNSYNCED_LINE_THRESHOLD = 20
RECALL_STALENESS_MINUTES = 15


# ============================================================================
# Freshness check (M3): warn when /recall may be returning stale
# results because sync-to-postgres.py hasn't caught up with JSONL.
# ============================================================================

def _staleness_warning() -> str | None:
    """
    Return a one-line warning string if postgres is materially behind
    the canonical JSONL, else None. Controlled by
    ``recall_staleness_warning`` in data/config/sync.json (default: on).

    Checks two things:
      1. JSONL has grown by more than RECALL_UNSYNCED_LINE_THRESHOLD
         lines since the last successful sync.
      2. Last sync timestamp is older than RECALL_STALENESS_MINUTES.

    Both must fire; either alone is noise on a normal day.
    """
    # Config gate.
    try:
        if SYNC_CONFIG_FILE.exists():
            cfg = json.loads(SYNC_CONFIG_FILE.read_text(encoding="utf-8"))
            if not cfg.get("recall_staleness_warning", True):
                return None
    except (json.JSONDecodeError, OSError):
        pass  # fall through to default-on behaviour

    if not CURSOR_FILE.exists() or not MEMORIES_FILE.exists():
        return None

    try:
        cursor = json.loads(CURSOR_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    last_line = cursor.get("postgres_sync_line")
    last_ts = cursor.get("postgres_last_sync_ts")
    if last_line is None or last_ts is None:
        return None

    try:
        current_lines = sum(1 for _ in MEMORIES_FILE.open(encoding="utf-8"))
    except OSError:
        return None

    unsynced = current_lines - int(last_line)

    try:
        last_sync = datetime.fromisoformat(last_ts)
        if last_sync.tzinfo is None:
            last_sync = last_sync.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None

    age_minutes = (datetime.now(timezone.utc) - last_sync).total_seconds() / 60.0

    if unsynced > RECALL_UNSYNCED_LINE_THRESHOLD and age_minutes > RECALL_STALENESS_MINUTES:
        return (
            f"[fetch-memories] WARNING: postgres is {unsynced} lines / "
            f"{age_minutes:.0f} min behind JSONL. Recent memories may be "
            f"missing from /recall until the next sync-to-postgres.py run."
        )
    return None


# ============================================================================
# Argument parsing
# ============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for memory retrieval."""
    parser = argparse.ArgumentParser(
        description=(
            "Fetch full memory content for Tier 2 retrieval. "
            "Tries PostgreSQL first, falls back to JSONL."
        ),
    )
    parser.add_argument(
        "--tag", "-t",
        action="append",
        dest="tags",
        metavar="TAG",
        help="Filter by research tag (repeatable).",
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        default=None,
        help="Free-text search across memory content.",
    )
    parser.add_argument(
        "--category", "-c",
        type=str,
        default=None,
        help="Filter by memory category (exact match).",
    )
    parser.add_argument(
        "--id",
        type=str,
        dest="memory_id",
        default=None,
        help="Retrieve a specific memory by ID.",
    )
    parser.add_argument(
        "--semantic", "-s",
        type=str,
        default=None,
        metavar="QUERY",
        help="Semantic similarity search (requires pgvector + embeddings).",
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=MAX_RESULTS,
        help=f"Maximum results (default: {MAX_RESULTS}).",
    )

    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit must be a positive integer")

    # Require at least one filter
    if not any([args.tags, args.query, args.category, args.memory_id, args.semantic]):
        parser.error(
            "At least one filter required: "
            "--tag, --query, --category, --id, or --semantic"
        )

    return args


# ============================================================================
# PostgreSQL retrieval
# ============================================================================


def try_postgres(
    tags: list[str] | None = None,
    query: str | None = None,
    category: str | None = None,
    memory_id: str | None = None,
    limit: int = MAX_RESULTS,
    project: str | None = None,
) -> list[dict[str, Any]] | None:
    """
    Query the ``active_memories`` view in PostgreSQL.

    Returns a list of memory dicts if successful, or ``None`` if
    PostgreSQL is unavailable (import failure or connection error).
    Errors are printed to stderr, never stdout — CC reads stdout
    for memory content.

    All queries use parameterised placeholders to prevent injection.
    """
    try:
        import psycopg2  # noqa: WPS433 — optional dependency
    except ImportError:
        return None

    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError as exc:
        print(
            f"[fetch-memories] PostgreSQL unavailable: {exc}",
            file=sys.stderr,
        )
        return None

    try:
        columns = [
            "id", "category", "content", "summary", "confidence",
            "research_tags", "source_context", "created_at", "project",
        ]
        base = (
            f"SELECT {', '.join(columns)} "  # noqa: S608
            f"FROM active_memories WHERE TRUE"
        )
        conditions: list[str] = []
        params: list[Any] = []

        if memory_id:
            conditions.append("id = %s")
            params.append(memory_id)

        if tags:
            # Tags are stored lowercase; normalise input to match
            conditions.append("research_tags && %s")
            params.append([t.lower() for t in tags])

        if query:
            conditions.append(
                "to_tsvector('english', "
                "content || ' ' || "
                "COALESCE(summary, '') || ' ' || "
                "COALESCE(source_context, '')) "
                "@@ plainto_tsquery('english', %s)"
            )
            params.append(query)

        if category:
            conditions.append("category = %s")
            params.append(category)

        if project:
            conditions.append("project = %s")
            params.append(project)

        sql = base
        for cond in conditions:
            sql += f" AND {cond}"
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            record: dict[str, Any] = {}
            for i, col in enumerate(columns):
                value = row[i]
                # Convert datetime to ISO string for consistency
                if isinstance(value, datetime):
                    value = value.isoformat()
                record[col] = value
            results.append(record)

        return results

    except Exception as exc:  # noqa: BLE001
        print(
            f"[fetch-memories] PostgreSQL query error: {exc}",
            file=sys.stderr,
        )
        return None
    finally:
        conn.close()


# ============================================================================
# Semantic search (pgvector)
# ============================================================================


def try_semantic(
    query: str,
    category: str | None = None,
    tags: list[str] | None = None,
    limit: int = MAX_RESULTS,
) -> list[dict[str, Any]] | None:
    """
    Semantic similarity search via pgvector cosine distance.

    Generates an embedding for the query text via Ollama, then finds
    the closest memories by cosine similarity. Returns None if pgvector,
    Ollama, or PostgreSQL is unavailable (caller falls back to FTS).

    Args:
        query: Free-text search query.
        category: Optional category filter (exact match).
        tags: Optional tag filter (array overlap).
        limit: Maximum results.

    Returns:
        List of memory dicts with an added ``similarity`` field,
        or None if semantic search is unavailable.
    """
    try:
        from embed import embed_single
    except ImportError:
        print(
            "[fetch-memories] embed module not available",
            file=sys.stderr,
        )
        return None

    # Generate query embedding
    query_vector = embed_single(query)
    if query_vector is None:
        print(
            "[fetch-memories] Could not generate query embedding "
            "(Ollama unavailable?)",
            file=sys.stderr,
        )
        return None

    try:
        import psycopg2
    except ImportError:
        return None

    try:
        conn = psycopg2.connect(dbname=DB_NAME)
    except psycopg2.OperationalError as exc:
        print(
            f"[fetch-memories] PostgreSQL unavailable: {exc}",
            file=sys.stderr,
        )
        return None

    try:
        columns = [
            "id", "category", "content", "summary", "confidence",
            "research_tags", "source_context", "created_at", "project",
        ]
        sql = (
            f"SELECT {', '.join(columns)}, "
            f"1 - (embedding <=> %s::vector) AS similarity "
            f"FROM active_memories "
            f"WHERE embedding IS NOT NULL"
        )
        params: list[Any] = [json.dumps(query_vector)]

        if category:
            sql += " AND category = %s"
            params.append(category)

        if tags:
            sql += " AND research_tags && %s"
            params.append([t.lower() for t in tags])

        sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
        params.append(json.dumps(query_vector))
        params.append(limit)

        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            record: dict[str, Any] = {}
            for i, col in enumerate(columns):
                value = row[i]
                if isinstance(value, datetime):
                    value = value.isoformat()
                record[col] = value
            record["similarity"] = float(row[len(columns)])
            results.append(record)

        return results

    except Exception as exc:
        print(
            f"[fetch-memories] Semantic search error: {exc}",
            file=sys.stderr,
        )
        return None
    finally:
        conn.close()


# ============================================================================
# JSONL fallback retrieval
# ============================================================================


def load_jsonl_memories() -> list[dict[str, Any]]:
    """
    Load all memories from the canonical JSONL file.

    Returns an empty list if the file does not exist or is empty.
    Skips blank lines and malformed JSON silently.
    """
    if not MEMORIES_FILE.exists():
        return []

    records: list[dict[str, Any]] = []
    with open(MEMORIES_FILE, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue

    return records


def matches_filters(
    mem: dict[str, Any],
    tags: list[str] | None = None,
    query: str | None = None,
    category: str | None = None,
    memory_id: str | None = None,
) -> bool:
    """
    Check whether a memory matches the given filter criteria.

    All provided filters are combined with AND logic:
    - **Tags:** any of the provided tags must appear in the memory's
      ``research_tags`` (case-insensitive).
    - **Query:** case-insensitive substring search across ``content``,
      ``summary``, and ``source_context``.
    - **Category:** exact match on the ``category`` field.
    - **ID:** exact match on the ``id`` field.
    """
    # ID filter (exact match)
    if memory_id is not None:
        if mem.get("id") != memory_id:
            return False

    # Category filter (exact match)
    if category is not None:
        if mem.get("category") != category:
            return False

    # Tag filter (any tag overlaps, case-insensitive)
    if tags is not None:
        mem_tags = mem.get("research_tags") or []
        if isinstance(mem_tags, str):
            mem_tags = [mem_tags]
        mem_tags_lower = {str(t).lower() for t in mem_tags}
        if not any(t.lower() in mem_tags_lower for t in tags):
            return False

    # Free-text query (case-insensitive substring search)
    if query is not None:
        query_lower = query.lower()
        searchable = " ".join([
            str(mem.get("content", "")),
            str(mem.get("summary", "")),
            str(mem.get("source_context", "")),
        ]).lower()
        if query_lower not in searchable:
            return False

    return True


def _parse_datetime(dt_str: str) -> datetime:
    """
    Parse an ISO datetime string for sorting.

    Returns epoch (1970-01-01) for unparseable values so they
    sort to the end.
    """
    try:
        # Handle timezone-aware strings (with +00:00 or Z)
        cleaned = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError, AttributeError):
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def fallback_jsonl(
    tags: list[str] | None = None,
    query: str | None = None,
    category: str | None = None,
    memory_id: str | None = None,
    limit: int = MAX_RESULTS,
) -> list[dict[str, Any]]:
    """
    Query memories from the canonical JSONL file.

    Loads all memories, filters by the provided criteria, sorts by
    ``created_at`` descending (most recent first), and returns the
    top *limit* matches.

    Note: this fallback does not apply decay rules — it returns all
    memories regardless of ``is_active`` status.  When PostgreSQL is
    unavailable, returning slightly more results is better than
    returning nothing.
    """
    memories = load_jsonl_memories()
    matched = [
        m for m in memories
        if matches_filters(m, tags, query, category, memory_id)
    ]
    matched.sort(
        key=lambda m: _parse_datetime(m.get("created_at", "")),
        reverse=True,
    )
    return matched[:limit]


# ============================================================================
# Output formatting
# ============================================================================


def format_output(memories: list[dict[str, Any]]) -> str:
    """
    Format memory results as markdown for CC consumption.

    Produces a structured output with full content, confidence, tags,
    and source context for each result.  Returns a zero-results
    message if the list is empty.
    """
    count = len(memories)

    if count == 0:
        return (
            "## Memory Details (0 results)\n\n"
            "No memories matched the query."
        )

    noun = "result" if count == 1 else "results"
    lines: list[str] = [f"## Memory Details ({count} {noun})\n"]

    for i, mem in enumerate(memories, 1):
        category = mem.get("category") or "unknown"
        created = (str(mem.get("created_at") or ""))[:10]
        content = mem.get("content") or "(no content)"
        confidence = mem.get("confidence") or "unknown"

        tags = mem.get("research_tags") or []
        if isinstance(tags, str):
            tags = [tags]
        tags_str = ", ".join(str(t) for t in tags) if tags else "(none)"

        source = mem.get("source_context") or "(no source)"

        lines.append(f"### [{i}] {category} — {created}")
        lines.append(content)
        similarity = mem.get("similarity")
        if similarity is not None:
            lines.append(f"Similarity: {similarity:.3f}")
        lines.append(f"Confidence: {confidence}")
        lines.append(f"Tags: {tags_str}")
        lines.append(f"Source: {source}")
        lines.append("---")

    return "\n".join(lines)


# ============================================================================
# Main
# ============================================================================


def main() -> None:
    """
    Entry point: parse args, try PostgreSQL, fall back to JSONL.

    Outputs formatted memory results to stdout.  All error messages
    go to stderr so CC only sees clean memory content.
    """
    args = parse_args()
    results = None

    # Freshness check (M3): surface a warning to stderr if postgres is
    # materially behind JSONL so /recall callers can decide whether to
    # wait for the next sync cycle.
    warning = _staleness_warning()
    if warning:
        print(warning, file=sys.stderr)

    # Determine the effective text query for FTS/JSONL fallback.
    # --semantic provides the query text if --query is not also set.
    effective_query = args.query or args.semantic

    # Semantic search path (pgvector cosine similarity)
    if args.semantic:
        results = try_semantic(
            query=args.semantic,
            category=args.category,
            tags=args.tags,
            limit=args.limit,
        )
        if results is None:
            # Semantic unavailable — fall through to FTS
            print(
                "[fetch-memories] Semantic search unavailable, "
                "trying FTS",
                file=sys.stderr,
            )

    # Standard search path (FTS via PostgreSQL)
    if results is None and (
        effective_query or args.tags or args.category or args.memory_id
    ):
        results = try_postgres(
            tags=args.tags,
            query=effective_query,
            category=args.category,
            memory_id=args.memory_id,
            limit=args.limit,
        )

    # Fall back to JSONL if PostgreSQL is unavailable
    if results is None:
        print(
            "[fetch-memories] Falling back to JSONL search",
            file=sys.stderr,
        )
        results = fallback_jsonl(
            tags=args.tags,
            query=effective_query,
            category=args.category,
            memory_id=args.memory_id,
            limit=args.limit,
        )

    print(format_output(results))


if __name__ == "__main__":
    main()
