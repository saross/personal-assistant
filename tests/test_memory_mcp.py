"""Tests for scripts/memory_mcp.py — the MCP memory server."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# -------------------------------------------------------------------------
# Module import (file has no .py-friendly name, load via spec)
# -------------------------------------------------------------------------

MODULE_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "memory_mcp.py"
)
_spec = importlib.util.spec_from_file_location("memory_mcp", MODULE_PATH)
memory_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(memory_mcp)


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously for tests."""
    return asyncio.run(coro)


SAMPLE_RESULTS = [
    {
        "id": "2026-04-12-abcdef123456",
        "category": "decision",
        "content": "Use PostgreSQL for the memory store",
        "summary": "Chose PostgreSQL for memory store",
        "confidence": "high",
        "research_tags": ["database", "architecture"],
        "source_context": "planning session",
        "created_at": "2026-04-12T10:00:00+00:00",
        "project": "-home-shawn-personal-assistant",
    },
    {
        "id": "2026-04-11-fedcba654321",
        "category": "architecture",
        "content": "Split repo into public + private submodule",
        "summary": "Repo split architecture",
        "confidence": "high",
        "research_tags": ["architecture", "repo-split"],
        "source_context": "infrastructure work",
        "created_at": "2026-04-11T15:00:00+00:00",
        "project": "-home-shawn-personal-assistant",
    },
]


# -------------------------------------------------------------------------
# Tool registration test
# -------------------------------------------------------------------------

class TestRegistration:
    """Verify the five expected tools are registered with FastMCP."""

    def test_all_tools_registered(self) -> None:
        tools = _run(memory_mcp.mcp.list_tools())
        names = {t.name for t in tools}
        assert names == {
            "search_memories",
            "semantic_search",
            "search_sessions",
            "get_memory",
            "list_recent",
            "memory_statistics",
        }

    def test_all_tools_are_read_only(self) -> None:
        """Every tool must be marked readOnlyHint=True."""
        tools = _run(memory_mcp.mcp.list_tools())
        for tool in tools:
            assert tool.annotations is not None, (
                f"{tool.name} missing annotations"
            )
            assert tool.annotations.readOnlyHint is True, (
                f"{tool.name} is not readOnly"
            )


# -------------------------------------------------------------------------
# Envelope helpers
# -------------------------------------------------------------------------

class TestEnvelope:
    """Tests for _envelope and _error_envelope."""

    def test_envelope_structure(self) -> None:
        out = memory_mcp._envelope(SAMPLE_RESULTS, source="postgres")
        data = json.loads(out)
        assert data["count"] == 2
        assert data["source"] == "postgres"
        assert len(data["results"]) == 2
        assert "note" not in data

    def test_envelope_with_note(self) -> None:
        out = memory_mcp._envelope(
            [], source="jsonl", note="Fallback",
        )
        data = json.loads(out)
        assert data["count"] == 0
        assert data["note"] == "Fallback"

    def test_error_envelope_structure(self) -> None:
        out = memory_mcp._error_envelope("something failed")
        data = json.loads(out)
        assert data["count"] == 0
        assert data["results"] == []
        assert data["source"] == "none"
        assert data["error"] == "something failed"

    def test_envelope_handles_unicode(self) -> None:
        """Non-ASCII content round-trips through JSON correctly."""
        results = [{"content": "Παναγία inscription"}]
        out = memory_mcp._envelope(results, source="postgres")
        data = json.loads(out)
        assert data["results"][0]["content"] == "Παναγία inscription"


# -------------------------------------------------------------------------
# search_memories tool
# -------------------------------------------------------------------------

class TestSearchMemories:
    """Tests for the search_memories tool."""

    def test_requires_at_least_one_filter(self) -> None:
        """Bare call with no filters returns an error envelope."""
        out = _run(memory_mcp.search_memories())
        data = json.loads(out)
        assert data["count"] == 0
        assert "error" in data
        assert "filter" in data["error"].lower()

    def test_postgres_happy_path(self) -> None:
        """PostgreSQL returns results; they flow through the envelope."""
        with patch.object(
            memory_mcp.fetch_memories,
            "try_postgres",
            return_value=SAMPLE_RESULTS,
        ) as mock_pg:
            out = _run(memory_mcp.search_memories(query="PostgreSQL"))

        data = json.loads(out)
        assert data["count"] == 2
        assert data["source"] == "postgres"
        # Strict call-args check: all other filters should be None
        mock_pg.assert_called_once_with(
            tags=None,
            query="PostgreSQL",
            category=None,
            memory_id=None,
            limit=10,
            project=None,
        )

    def test_tag_filter_passed_through(self) -> None:
        """Tags are forwarded to try_postgres as a list."""
        with patch.object(
            memory_mcp.fetch_memories,
            "try_postgres",
            return_value=[],
        ) as mock_pg:
            _run(memory_mcp.search_memories(
                tags=["architecture", "decision"],
            ))
        assert mock_pg.call_args.kwargs["tags"] == [
            "architecture", "decision",
        ]

    def test_empty_tags_passed_as_none(self) -> None:
        """Empty tag list is converted to None (not [] — psql && '{}' fails)."""
        with patch.object(
            memory_mcp.fetch_memories,
            "try_postgres",
            return_value=[],
        ) as mock_pg:
            _run(memory_mcp.search_memories(query="x", tags=[]))
        assert mock_pg.call_args.kwargs["tags"] is None

    def test_project_filter_pushed_to_postgres(self) -> None:
        """Project filter is passed to try_postgres (server-side WHERE clause)."""
        with patch.object(
            memory_mcp.fetch_memories,
            "try_postgres",
            return_value=SAMPLE_RESULTS,
        ) as mock_pg:
            _run(memory_mcp.search_memories(
                query="test",
                project="-home-shawn-personal-assistant",
            ))

        assert mock_pg.call_args.kwargs["project"] == (
            "-home-shawn-personal-assistant"
        )

    def test_combined_filters(self) -> None:
        """All filters passed together are forwarded correctly."""
        with patch.object(
            memory_mcp.fetch_memories,
            "try_postgres",
            return_value=SAMPLE_RESULTS,
        ) as mock_pg:
            _run(memory_mcp.search_memories(
                query="database",
                category="decision",
                tags=["architecture"],
                project="-home-shawn-personal-assistant",
                limit=25,
            ))
        mock_pg.assert_called_once_with(
            tags=["architecture"],
            query="database",
            category="decision",
            memory_id=None,
            limit=25,
            project="-home-shawn-personal-assistant",
        )

    def test_jsonl_fallback_when_postgres_unavailable(self) -> None:
        """When try_postgres returns None, falls back to JSONL."""
        with (
            patch.object(
                memory_mcp.fetch_memories,
                "try_postgres",
                return_value=None,
            ),
            patch.object(
                memory_mcp.fetch_memories,
                "load_jsonl_memories",
                return_value=SAMPLE_RESULTS,
            ),
            patch.object(
                memory_mcp.fetch_memories,
                "matches_filters",
                return_value=True,
            ),
        ):
            out = _run(memory_mcp.search_memories(query="test"))

        data = json.loads(out)
        assert data["source"] == "jsonl"
        assert data["count"] == 2
        # Pin the decay warning string — it's the reason the note exists
        assert "decay rules NOT applied" in data["note"]

    def test_limit_respected(self) -> None:
        """The limit parameter is passed through to try_postgres."""
        with patch.object(
            memory_mcp.fetch_memories,
            "try_postgres",
            return_value=[],
        ) as mock_pg:
            _run(memory_mcp.search_memories(query="x", limit=25))
        assert mock_pg.call_args.kwargs["limit"] == 25


# -------------------------------------------------------------------------
# semantic_search tool
# -------------------------------------------------------------------------

class TestSemanticSearch:
    """Tests for the semantic_search tool."""

    def test_happy_path(self) -> None:
        """Semantic results flow through when Ollama is available."""
        results_with_sim = [
            {**SAMPLE_RESULTS[0], "similarity": 0.92},
            {**SAMPLE_RESULTS[1], "similarity": 0.71},
        ]
        with patch.object(
            memory_mcp.fetch_memories,
            "try_semantic",
            return_value=results_with_sim,
        ) as mock_sem:
            out = _run(memory_mcp.semantic_search(query="database"))

        data = json.loads(out)
        assert data["count"] == 2
        assert data["source"] == "postgres"
        mock_sem.assert_called_once()

    def test_min_similarity_filter(self) -> None:
        """Results below the similarity threshold are dropped."""
        results = [
            {**SAMPLE_RESULTS[0], "similarity": 0.92},
            {**SAMPLE_RESULTS[1], "similarity": 0.35},
        ]
        with patch.object(
            memory_mcp.fetch_memories,
            "try_semantic",
            return_value=results,
        ):
            out = _run(memory_mcp.semantic_search(
                query="x", min_similarity=0.5,
            ))

        data = json.loads(out)
        assert data["count"] == 1
        assert data["results"][0]["similarity"] == 0.92

    def test_ollama_unavailable_returns_error(self) -> None:
        """try_semantic returning None yields a clear error envelope."""
        with patch.object(
            memory_mcp.fetch_memories,
            "try_semantic",
            return_value=None,
        ):
            out = _run(memory_mcp.semantic_search(query="x"))

        data = json.loads(out)
        assert data["count"] == 0
        assert "error" in data
        assert "semantic" in data["error"].lower()


# -------------------------------------------------------------------------
# get_memory tool
# -------------------------------------------------------------------------

class TestGetMemory:
    """Tests for the get_memory tool."""

    def test_found(self) -> None:
        """Existing memory returns a single-result envelope."""
        with patch.object(
            memory_mcp.fetch_memories,
            "try_postgres",
            return_value=[SAMPLE_RESULTS[0]],
        ):
            out = _run(memory_mcp.get_memory(
                memory_id="2026-04-12-abcdef123456",
            ))

        data = json.loads(out)
        assert data["count"] == 1
        assert data["results"][0]["id"] == "2026-04-12-abcdef123456"

    def test_not_found_in_postgres(self) -> None:
        """Empty PG result returns error; does NOT fall through to JSONL."""
        with (
            patch.object(
                memory_mcp.fetch_memories,
                "try_postgres",
                return_value=[],
            ),
            patch.object(
                memory_mcp.fetch_memories,
                "load_jsonl_memories",
            ) as mock_jsonl,
        ):
            out = _run(memory_mcp.get_memory(memory_id="never-existed"))

        data = json.loads(out)
        assert data["count"] == 0
        assert "error" in data
        assert "not found" in data["error"].lower()
        # PG returned empty (not None) — JSONL should not be consulted
        mock_jsonl.assert_not_called()

    def test_jsonl_fallback(self) -> None:
        """PostgreSQL unavailable falls back to JSONL scan."""
        with (
            patch.object(
                memory_mcp.fetch_memories,
                "try_postgres",
                return_value=None,
            ),
            patch.object(
                memory_mcp.fetch_memories,
                "load_jsonl_memories",
                return_value=SAMPLE_RESULTS,
            ),
        ):
            out = _run(memory_mcp.get_memory(
                memory_id="2026-04-12-abcdef123456",
            ))

        data = json.loads(out)
        assert data["count"] == 1
        assert data["source"] == "jsonl"


# -------------------------------------------------------------------------
# list_recent tool
# -------------------------------------------------------------------------

class TestListRecent:
    """Tests for the list_recent tool."""

    def test_postgres_unavailable_error(self) -> None:
        """PostgreSQL down yields a clear error (no JSONL fallback)."""
        with patch.object(
            memory_mcp,
            "_pg_connect",
            return_value=(None, "connection refused"),
        ):
            out = _run(memory_mcp.list_recent(days=7))

        data = json.loads(out)
        assert data["count"] == 0
        assert "error" in data
        # Connection failure reason propagates to client
        assert "connection refused" in data["error"]

    def test_query_uses_make_interval(self) -> None:
        """SQL uses make_interval(days => %s) — not brittle quoted literal."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(
            memory_mcp,
            "_pg_connect",
            return_value=(mock_conn, None),
        ):
            _run(memory_mcp.list_recent(
                days=14, category="decision", limit=30,
            ))

        call_args = mock_cursor.execute.call_args
        assert call_args is not None
        sql, params = call_args.args
        # make_interval is the safe form; the buggy form was INTERVAL '%s days'
        assert "make_interval(days => %s)" in sql
        assert "INTERVAL '%s days'" not in sql
        assert "category = %s" in sql
        # Placeholder count must match param count
        assert sql.count("%s") == len(params)
        assert params == [14, "decision", 30]

    def test_connection_closed_on_success(self) -> None:
        """Connection is closed on the happy path, not just on failure."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(
            memory_mcp,
            "_pg_connect",
            return_value=(mock_conn, None),
        ):
            _run(memory_mcp.list_recent(days=7))

        mock_conn.close.assert_called_once()

    def test_results_deserialised_from_rows(self) -> None:
        """Rows are converted to dicts with correct column mapping."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = [
            (
                "id-1",
                "decision",
                "content-text",
                "summary-text",
                "high",
                ["tag1", "tag2"],
                "context-text",
                "2026-04-12T10:00:00",
                "proj-a",
            ),
        ]
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(
            memory_mcp,
            "_pg_connect",
            return_value=(mock_conn, None),
        ):
            out = _run(memory_mcp.list_recent(days=1))

        data = json.loads(out)
        assert data["count"] == 1
        # Verify EVERY column is mapped to the correct key
        r = data["results"][0]
        assert r["id"] == "id-1"
        assert r["category"] == "decision"
        assert r["content"] == "content-text"
        assert r["summary"] == "summary-text"
        assert r["confidence"] == "high"
        assert r["research_tags"] == ["tag1", "tag2"]
        assert r["source_context"] == "context-text"
        assert r["created_at"] == "2026-04-12T10:00:00"
        assert r["project"] == "proj-a"


# -------------------------------------------------------------------------
# memory_statistics tool
# -------------------------------------------------------------------------

class TestMemoryStatistics:
    """Tests for memory_statistics."""

    def test_postgres_unavailable_error(self) -> None:
        """Connection failure reason propagates through to the client."""
        with patch.object(
            memory_mcp,
            "_pg_connect",
            return_value=(None, "auth failed"),
        ):
            out = _run(memory_mcp.memory_statistics())
        data = json.loads(out)
        assert "error" in data
        assert "auth failed" in data["error"]

    def test_returns_expected_stats_structure(self) -> None:
        """Successful call returns all expected stats fields."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)

        # Queue up the expected results for each query in sequence
        mock_cursor.fetchone.side_effect = [
            (12345,),  # total_active
            (567,),    # added_last_7_days
        ]
        mock_cursor.fetchall.side_effect = [
            [("decision", 3000), ("gotcha", 1500)],  # by_category
            [("tag-a", 200), ("tag-b", 150)],        # top_tags
            [("proj-a", 5000), ("proj-b", 3000)],    # top_projects
        ]
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(
            memory_mcp,
            "_pg_connect",
            return_value=(mock_conn, None),
        ):
            out = _run(memory_mcp.memory_statistics())

        data = json.loads(out)
        # New shape: {source, stats}, not {count, results}
        assert data["source"] == "postgres"
        stats = data["stats"]
        assert stats["total_active"] == 12345
        assert stats["added_last_7_days"] == 567
        assert len(stats["by_category"]) == 2
        assert stats["by_category"][0]["category"] == "decision"
        assert len(stats["top_tags"]) == 2
        assert len(stats["top_projects"]) == 2
        mock_conn.close.assert_called_once()

    def test_sql_query_ordering(self) -> None:
        """Verify each query runs in the expected order (not just mock drift)."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.side_effect = [(1,), (1,)]
        mock_cursor.fetchall.side_effect = [[], [], []]
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(
            memory_mcp,
            "_pg_connect",
            return_value=(mock_conn, None),
        ):
            _run(memory_mcp.memory_statistics())

        # Five SQL statements in expected order
        calls = [c.args[0] for c in mock_cursor.execute.call_args_list]
        assert len(calls) == 5
        assert "COUNT(*)" in calls[0] and "active_memories" in calls[0]
        assert "GROUP BY category" in calls[1]
        assert "UNNEST(research_tags)" in calls[2]
        assert "INTERVAL '7 days'" in calls[3]
        assert "GROUP BY project" in calls[4]


# -------------------------------------------------------------------------
# Error handling
# -------------------------------------------------------------------------

class TestErrorHandling:
    """Tests that errors don't crash the MCP subprocess."""

    def test_search_survives_jsonl_load_failure(self) -> None:
        """A JSONL load exception is caught and returns an error envelope."""
        with (
            patch.object(
                memory_mcp.fetch_memories,
                "try_postgres",
                return_value=None,
            ),
            patch.object(
                memory_mcp.fetch_memories,
                "load_jsonl_memories",
                side_effect=OSError("disk error"),
            ),
        ):
            out = _run(memory_mcp.search_memories(query="x"))

        data = json.loads(out)
        assert "error" in data
        assert "disk error" in data["error"]

    def test_list_recent_survives_query_failure(self) -> None:
        """A DB query exception is caught and returns an error envelope."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.execute.side_effect = RuntimeError("bad query")
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(
            memory_mcp,
            "_pg_connect",
            return_value=(mock_conn, None),
        ):
            out = _run(memory_mcp.list_recent(days=7))

        data = json.loads(out)
        assert "error" in data
        mock_conn.close.assert_called_once()  # Connection closed even on error


# -------------------------------------------------------------------------
# Stdio invariant — THE critical test for an MCP server
# -------------------------------------------------------------------------

class TestStdioInvariant:
    """
    Verify no tool writes to stdout under any conditions.

    A stdio MCP server that writes to stdout corrupts the JSON-RPC
    stream. This is the single most important invariant of the file —
    protect it with tests.
    """

    def test_search_memories_stdout_clean_on_success(self, capsys) -> None:
        """Successful search produces zero stdout output."""
        with patch.object(
            memory_mcp.fetch_memories,
            "try_postgres",
            return_value=SAMPLE_RESULTS,
        ):
            _run(memory_mcp.search_memories(query="test"))
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_search_memories_stdout_clean_on_error(self, capsys) -> None:
        """Error paths also produce zero stdout output."""
        with (
            patch.object(
                memory_mcp.fetch_memories,
                "try_postgres",
                return_value=None,
            ),
            patch.object(
                memory_mcp.fetch_memories,
                "load_jsonl_memories",
                side_effect=OSError("boom"),
            ),
        ):
            _run(memory_mcp.search_memories(query="test"))
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_semantic_search_stdout_clean(self, capsys) -> None:
        with patch.object(
            memory_mcp.fetch_memories,
            "try_semantic",
            return_value=None,
        ):
            _run(memory_mcp.semantic_search(query="x"))
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_get_memory_stdout_clean(self, capsys) -> None:
        with patch.object(
            memory_mcp.fetch_memories,
            "try_postgres",
            return_value=[],
        ):
            _run(memory_mcp.get_memory(memory_id="nonexistent"))
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_list_recent_stdout_clean(self, capsys) -> None:
        with patch.object(
            memory_mcp,
            "_pg_connect",
            return_value=(None, "unavailable"),
        ):
            _run(memory_mcp.list_recent(days=7))
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_memory_statistics_stdout_clean(self, capsys) -> None:
        with patch.object(
            memory_mcp,
            "_pg_connect",
            return_value=(None, "unavailable"),
        ):
            _run(memory_mcp.memory_statistics())
        captured = capsys.readouterr()
        assert captured.out == ""


# -------------------------------------------------------------------------
# get_memory JSONL not-found branch
# -------------------------------------------------------------------------

class TestGetMemoryJsonlNotFound:
    """The JSONL fallback "not found" branch (distinct from PG not-found)."""

    def test_jsonl_fallback_not_found(self) -> None:
        """PG unavailable + ID missing from JSONL → error envelope."""
        with (
            patch.object(
                memory_mcp.fetch_memories,
                "try_postgres",
                return_value=None,
            ),
            patch.object(
                memory_mcp.fetch_memories,
                "load_jsonl_memories",
                return_value=SAMPLE_RESULTS,  # does not contain 'nonexistent'
            ),
        ):
            out = _run(memory_mcp.get_memory(memory_id="nonexistent"))
        data = json.loads(out)
        assert data["count"] == 0
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_jsonl_fallback_found_includes_decay_warning(self) -> None:
        """JSONL fallback hit includes the decay warning note."""
        with (
            patch.object(
                memory_mcp.fetch_memories,
                "try_postgres",
                return_value=None,
            ),
            patch.object(
                memory_mcp.fetch_memories,
                "load_jsonl_memories",
                return_value=SAMPLE_RESULTS,
            ),
        ):
            out = _run(memory_mcp.get_memory(
                memory_id="2026-04-12-abcdef123456",
            ))
        data = json.loads(out)
        assert data["count"] == 1
        assert "decay rules NOT applied" in data["note"]


# -------------------------------------------------------------------------
# Semantic search tag and boundary tests
# -------------------------------------------------------------------------

class TestSemanticSearchExtras:
    """Additional semantic_search coverage."""

    def test_tags_and_category_forwarded(self) -> None:
        """tag_list and category reach try_semantic."""
        with patch.object(
            memory_mcp.fetch_memories,
            "try_semantic",
            return_value=[],
        ) as mock_sem:
            _run(memory_mcp.semantic_search(
                query="database",
                category="decision",
                tags=["architecture", "postgres"],
            ))
        assert mock_sem.call_args.kwargs["category"] == "decision"
        assert mock_sem.call_args.kwargs["tags"] == [
            "architecture", "postgres",
        ]

    def test_empty_tags_passed_as_none(self) -> None:
        """Empty list is converted to None (consistent with search_memories)."""
        with patch.object(
            memory_mcp.fetch_memories,
            "try_semantic",
            return_value=[],
        ) as mock_sem:
            _run(memory_mcp.semantic_search(query="x", tags=[]))
        assert mock_sem.call_args.kwargs["tags"] is None

    def test_similarity_boundary(self) -> None:
        """Results with similarity == min_similarity are kept (>=, not >)."""
        results = [
            {**SAMPLE_RESULTS[0], "similarity": 0.50},  # exact boundary
            {**SAMPLE_RESULTS[1], "similarity": 0.49},  # just below
        ]
        with patch.object(
            memory_mcp.fetch_memories,
            "try_semantic",
            return_value=results,
        ):
            out = _run(memory_mcp.semantic_search(
                query="x", min_similarity=0.50,
            ))
        data = json.loads(out)
        # The 0.50 match should be kept
        assert data["count"] == 1
        assert data["results"][0]["similarity"] == 0.50

    def test_over_fetch_when_min_similarity_set(self) -> None:
        """When min_similarity > 0, limit is expanded for over-fetching."""
        with patch.object(
            memory_mcp.fetch_memories,
            "try_semantic",
            return_value=[],
        ) as mock_sem:
            _run(memory_mcp.semantic_search(
                query="x", limit=10, min_similarity=0.5,
            ))
        # Should over-fetch (currently hard-coded to 50)
        assert mock_sem.call_args.kwargs["limit"] > 10


# -------------------------------------------------------------------------
# Tool schema pinning
# -------------------------------------------------------------------------

class TestToolSchemas:
    """Pin the public tool contract (descriptions, parameter bounds)."""

    def test_search_memories_schema(self) -> None:
        tools = {t.name: t for t in _run(memory_mcp.mcp.list_tools())}
        tool = tools["search_memories"]
        assert tool.description is not None
        assert len(tool.description) > 20  # Meaningful description
        schema = tool.inputSchema
        props = schema["properties"]
        # All expected parameters are present
        assert set(props.keys()) == {
            "query", "category", "tags", "project", "limit",
        }
        # limit has bounds
        assert props["limit"]["maximum"] == 50
        assert props["limit"]["minimum"] == 1

    def test_semantic_search_schema(self) -> None:
        tools = {t.name: t for t in _run(memory_mcp.mcp.list_tools())}
        tool = tools["semantic_search"]
        props = tool.inputSchema["properties"]
        assert "query" in props
        assert "min_similarity" in props
        # min_similarity bounds
        assert props["min_similarity"]["minimum"] == 0.0
        assert props["min_similarity"]["maximum"] == 1.0
        # query is required
        assert "query" in tool.inputSchema.get("required", [])

    def test_list_recent_schema(self) -> None:
        tools = {t.name: t for t in _run(memory_mcp.mcp.list_tools())}
        tool = tools["list_recent"]
        props = tool.inputSchema["properties"]
        assert props["days"]["minimum"] == 1
        assert props["days"]["maximum"] == 365
