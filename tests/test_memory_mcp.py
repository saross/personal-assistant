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
        # Pin the fallback note: it must say soft deletes ARE honoured and
        # decay is NOT (audit R2 — the old wording conflated the two).
        assert "is_active: false) ARE excluded" in data["note"]
        assert "decay is NOT applied" in data["note"]

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
        # Whatever _pg_connect reports reaches the envelope. In production
        # that message is deliberately generic (audit R18); what is pinned
        # here is that the tool does not swallow it.
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
                "true",
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
        assert r["verified"] == "true"   # RT18: same shape as search_memories
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

    def test_search_survives_jsonl_load_failure(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A JSONL load exception is caught and returns an error envelope.

        The detail belongs in the server log, not in the envelope crossing
        to the client (audit R18).
        """
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
        assert "disk error" not in data["error"]
        assert "disk error" in caplog.text

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
        assert "is_active: false) ARE excluded" in data["note"]
        assert "decay is NOT applied" in data["note"]


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


# -------------------------------------------------------------------------
# Audit R2 (2026-09-08): forgotten memories must not surface via MCP
# -------------------------------------------------------------------------

class TestSoftDeleteInJsonlFallbacks:
    """``is_active: false`` excludes a record from both JSONL fallbacks.

    Deliberately does NOT stub ``matches_filters`` (lens B, RT7): the
    fallback's own filtering is the thing under test.
    """

    @staticmethod
    def _corpus() -> list[dict]:
        """Two records, one of them retired via ``/forget``."""
        retired = {**SAMPLE_RESULTS[0], "id": "2026-04-12-retired",
                   "is_active": False}
        live = {**SAMPLE_RESULTS[1], "id": "2026-04-11-live"}
        return [retired, live]

    def test_search_memories_fallback_drops_forgotten(self) -> None:
        """Kills: removing the ``is_active`` guard from ``matches_filters``."""
        with (
            patch.object(memory_mcp.fetch_memories, "try_postgres",
                         return_value=None),
            patch.object(memory_mcp.fetch_memories, "load_jsonl_memories",
                         return_value=self._corpus()),
        ):
            out = _run(memory_mcp.search_memories(
                project="-home-shawn-personal-assistant"))
        data = json.loads(out)
        assert [r["id"] for r in data["results"]] == ["2026-04-11-live"]

    def test_get_memory_fallback_reports_forgotten_as_not_found(self) -> None:
        """Kills: dropping ``and fetch_memories.is_active(mem)`` in get_memory."""
        with (
            patch.object(memory_mcp.fetch_memories, "try_postgres",
                         return_value=None),
            patch.object(memory_mcp.fetch_memories, "load_jsonl_memories",
                         return_value=self._corpus()),
        ):
            out = _run(memory_mcp.get_memory(memory_id="2026-04-12-retired"))
        data = json.loads(out)
        assert data["count"] == 0
        assert "not found" in data["error"]

    def test_get_memory_fallback_still_serves_a_live_record(self) -> None:
        """The guard must not break the ordinary fallback hit."""
        with (
            patch.object(memory_mcp.fetch_memories, "try_postgres",
                         return_value=None),
            patch.object(memory_mcp.fetch_memories, "load_jsonl_memories",
                         return_value=self._corpus()),
        ):
            out = _run(memory_mcp.get_memory(memory_id="2026-04-11-live"))
        data = json.loads(out)
        assert data["count"] == 1
        assert data["source"] == "jsonl"

    def test_fallback_notes_say_what_is_and_is_not_applied(self) -> None:
        """The note must not imply soft deletes are ignored (audit R2)."""
        with (
            patch.object(memory_mcp.fetch_memories, "try_postgres",
                         return_value=None),
            patch.object(memory_mcp.fetch_memories, "load_jsonl_memories",
                         return_value=self._corpus()),
        ):
            search_note = json.loads(_run(memory_mcp.search_memories(
                project="-home-shawn-personal-assistant")))["note"]
            get_note = json.loads(_run(memory_mcp.get_memory(
                memory_id="2026-04-11-live")))["note"]
        for note in (search_note, get_note):
            assert "is_active: false) ARE excluded" in note
            assert "decay is NOT applied" in note


# -------------------------------------------------------------------------
# Audit R5 (2026-09-08): MCP retrieval feeds the earned-utility signal
# -------------------------------------------------------------------------

class TestSurfacingInstrumentation:
    """Every tool that returns memory content logs the ids it served.

    The MCP server was the one retrieval surface writing nothing to
    ``surfaced.log``, so memories served to Claude Desktop or claude.ai were
    invisible to the aggregator a future archival decision rests on.
    """

    @staticmethod
    def _ids_logged(mock_log) -> list[list[str]]:
        """The id lists passed to ``log_surfaced``, call by call."""
        return [
            [m["id"] for m in call.args[0]]
            for call in mock_log.call_args_list
        ]

    def test_search_memories_postgres_logs_exactly_what_it_returns(self) -> None:
        """Kills: deleting the ``_log_surfaced(results)`` call in the PG branch."""
        with (
            patch.object(memory_mcp.fetch_memories, "try_postgres",
                         return_value=SAMPLE_RESULTS),
            patch.object(memory_mcp.surfacing_log, "log_surfaced") as mock_log,
        ):
            out = _run(memory_mcp.search_memories(query="database"))
        returned = [r["id"] for r in json.loads(out)["results"]]
        assert self._ids_logged(mock_log) == [returned]

    def test_search_memories_jsonl_logs_the_truncated_list(self) -> None:
        """The logged ids are the ones actually served, not the pre-limit set."""
        with (
            patch.object(memory_mcp.fetch_memories, "try_postgres",
                         return_value=None),
            patch.object(memory_mcp.fetch_memories, "load_jsonl_memories",
                         return_value=SAMPLE_RESULTS),
            patch.object(memory_mcp.surfacing_log, "log_surfaced") as mock_log,
        ):
            out = _run(memory_mcp.search_memories(
                project="-home-shawn-personal-assistant", limit=1))
        returned = [r["id"] for r in json.loads(out)["results"]]
        assert len(returned) == 1
        assert self._ids_logged(mock_log) == [returned]

    def test_semantic_search_logs_after_the_similarity_filter(self) -> None:
        """Only the memories that survive min_similarity are logged."""
        scored = [
            {**SAMPLE_RESULTS[0], "similarity": 0.91},
            {**SAMPLE_RESULTS[1], "similarity": 0.20},
        ]
        with (
            patch.object(memory_mcp.fetch_memories, "try_semantic",
                         return_value=scored),
            patch.object(memory_mcp.surfacing_log, "log_surfaced") as mock_log,
        ):
            out = _run(memory_mcp.semantic_search(query="x", min_similarity=0.5))
        returned = [r["id"] for r in json.loads(out)["results"]]
        assert self._ids_logged(mock_log) == [returned]

    def test_get_memory_logs_the_single_record(self) -> None:
        with (
            patch.object(memory_mcp.fetch_memories, "try_postgres",
                         return_value=[SAMPLE_RESULTS[0]]),
            patch.object(memory_mcp.surfacing_log, "log_surfaced") as mock_log,
        ):
            _run(memory_mcp.get_memory(memory_id=SAMPLE_RESULTS[0]["id"]))
        assert self._ids_logged(mock_log) == [[SAMPLE_RESULTS[0]["id"]]]

    def test_list_recent_logs_its_rows(self) -> None:
        columns = [
            "id", "category", "content", "summary", "confidence", "verified",
            "research_tags", "source_context", "created_at", "project",
        ]
        row = tuple(SAMPLE_RESULTS[0].get(c, "true") for c in columns)
        cursor = MagicMock()
        cursor.fetchall.return_value = [row]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with (
            patch.object(memory_mcp, "_pg_connect", return_value=(conn, None)),
            patch.object(memory_mcp.surfacing_log, "log_surfaced") as mock_log,
        ):
            _run(memory_mcp.list_recent(days=7))
        assert self._ids_logged(mock_log) == [[SAMPLE_RESULTS[0]["id"]]]

    def test_tools_log_under_a_path_the_aggregator_counts(self) -> None:
        """``path=mcp`` must be a label the writer accepts and the reader counts.

        Kills: logging under an unknown label (the line would be written but
        never counted as active retrieval).
        """
        import importlib

        sys.path.insert(0, str(MODULE_PATH.parent))
        surfacing_log = importlib.import_module("surfacing_log")
        surfacing_stats = importlib.import_module("surfacing_stats")
        assert memory_mcp.SURFACING_PATH in surfacing_log.VALID_PATHS
        assert memory_mcp.SURFACING_PATH in surfacing_stats.ACTIVE_PATHS

    def test_error_paths_log_nothing(self) -> None:
        """A tool that returns no memories must not write a surfacing line."""
        with (
            patch.object(memory_mcp.fetch_memories, "try_semantic",
                         return_value=None),
            patch.object(memory_mcp.surfacing_log, "log_surfaced") as mock_log,
        ):
            _run(memory_mcp.semantic_search(query="x"))
        mock_log.assert_not_called()


# -------------------------------------------------------------------------
# Audit R7 (2026-09-08): semantic search declares what it cannot see
# -------------------------------------------------------------------------

class TestSemanticCoverageNote:
    """Un-embedded memories are excluded outright, so say so."""

    @staticmethod
    def _semantic_with_coverage(missing: int, total: int):
        """A try_semantic stand-in that fills the coverage dict it is given."""

        def _fake(**kwargs):
            kwargs["stats"]["unembedded_active"] = missing
            kwargs["stats"]["total_active"] = total
            return [SAMPLE_RESULTS[0]]

        return _fake

    def test_note_reports_the_uncovered_count(self) -> None:
        """Kills: dropping the note (a caller cannot tell empty from unindexed)."""
        with patch.object(
            memory_mcp.fetch_memories, "try_semantic",
            self._semantic_with_coverage(4, 10),
        ):
            data = json.loads(_run(memory_mcp.semantic_search(query="canopy")))
        assert "4 of 10 active memories have no embedding" in data["note"]

    def test_full_coverage_adds_no_note(self) -> None:
        """No gap, no noise."""
        with patch.object(
            memory_mcp.fetch_memories, "try_semantic",
            self._semantic_with_coverage(0, 10),
        ):
            data = json.loads(_run(memory_mcp.semantic_search(query="canopy")))
        assert "note" not in data

    def test_tool_description_states_the_limitation(self) -> None:
        """The contract is in the tool description, not only the envelope."""
        tools = {t.name: t for t in _run(memory_mcp.mcp.list_tools())}
        assert "embedding" in tools["semantic_search"].description


# -------------------------------------------------------------------------
# search_sessions tool: envelopes and bounds (lens B RT5, audit R9)
# -------------------------------------------------------------------------

class TestSearchSessionsTool:
    """The tool's own error and empty-result handling, not the search itself."""

    def test_results_are_wrapped_in_a_postgres_envelope(self) -> None:
        rows = [{"archive_dir": "2026-04-02T09-15_notebook", "turn_idx": 3,
                 "role": "user", "project": "sherds"}]
        with patch.object(memory_mcp.search_sessions_mod, "search",
                          return_value=rows) as mock_search:
            data = json.loads(_run(memory_mcp.search_sessions(query="loader")))
        assert data["source"] == "postgres"
        assert data["count"] == 1
        # The tool's arguments must reach the search function unchanged.
        assert mock_search.call_args.kwargs["substring"] is False

    def test_empty_result_carries_the_guidance_note(self) -> None:
        """Kills: dropping the note (the caller is told nothing to try next)."""
        with patch.object(memory_mcp.search_sessions_mod, "search",
                          return_value=[]):
            data = json.loads(_run(memory_mcp.search_sessions(query="loader")))
        assert data["source"] == "none"
        assert "--substring" in data["note"]

    def test_import_error_becomes_an_error_envelope(self) -> None:
        """Kills: deleting the ImportError branch (an unhandled traceback)."""
        with patch.object(memory_mcp.search_sessions_mod, "search",
                          side_effect=ImportError("no psycopg2")):
            data = json.loads(_run(memory_mcp.search_sessions(query="loader")))
        assert data["count"] == 0
        assert "psycopg2" in data["error"]

    def test_usage_error_text_reaches_the_caller(self) -> None:
        """The trigram floor must be actionable, not a generic failure."""
        with patch.object(
            memory_mcp.search_sessions_mod, "search",
            side_effect=ValueError("--substring needs at least 3 characters"),
        ):
            data = json.loads(_run(memory_mcp.search_sessions(
                query="ab", substring=True)))
        assert "at least 3 characters" in data["error"]

    def test_filters_are_forwarded(self) -> None:
        with patch.object(memory_mcp.search_sessions_mod, "search",
                          return_value=[]) as mock_search:
            _run(memory_mcp.search_sessions(
                query="loader", project="sherds", role="user",
                substring=True, limit=5))
        kwargs = mock_search.call_args.kwargs
        assert kwargs == {"project": "sherds", "role": "user",
                          "limit": 5, "substring": True}


class TestMcpConnectionBounds:
    """_pg_connect must bound both the connect and the statement (audit R9)."""

    def test_connect_kwargs_carry_both_timeouts(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: dropping connect_timeout or the statement_timeout option."""
        import psycopg2

        recorded: dict = {}

        def _fake_connect(**kwargs):
            recorded.update(kwargs)
            conn = MagicMock()
            cur = MagicMock()
            cur.fetchone.return_value = ("3",)
            conn.cursor.return_value.__enter__.return_value = cur
            return conn

        monkeypatch.setattr(psycopg2, "connect", _fake_connect)
        conn, err = memory_mcp._pg_connect()
        assert err is None
        assert recorded["connect_timeout"] == memory_mcp.CONNECT_TIMEOUT_SECONDS
        assert recorded["options"] == (
            f"-c statement_timeout={memory_mcp.STATEMENT_TIMEOUT_MS}"
        )


# -------------------------------------------------------------------------
# Audit R18 (2026-09-08): driver detail stays server-side
# -------------------------------------------------------------------------

class TestErrorEnvelopesAreGeneric:
    """psycopg2's text names sockets, hosts, and databases. Log it, don't ship it."""

    _SECRET = "could not connect to server: /var/run/postgresql/.s.PGSQL.5432"

    def test_connection_failure_detail_is_logged_not_returned(
        self, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Kills: interpolating the exception into the (None, message) tuple."""
        import psycopg2

        def _refuse(**kwargs):
            raise psycopg2.OperationalError(self._SECRET)

        monkeypatch.setattr(psycopg2, "connect", _refuse)
        with caplog.at_level("WARNING"):
            conn, err = memory_mcp._pg_connect()
        assert conn is None
        assert self._SECRET not in err
        assert self._SECRET in caplog.text

    @pytest.mark.parametrize("tool", ["list_recent", "memory_statistics"])
    def test_connection_failure_envelope_carries_no_detail(
        self, monkeypatch: pytest.MonkeyPatch, tool: str,
    ) -> None:
        """Both database-only tools report the generic message."""
        monkeypatch.setattr(
            memory_mcp, "_pg_connect",
            lambda: (None, memory_mcp.GENERIC_DB_ERROR),
        )
        data = json.loads(_run(getattr(memory_mcp, tool)()))
        assert "/var/run/postgresql" not in data["error"]
        assert "PostgreSQL unavailable" in data["error"]

    def test_query_failure_envelope_carries_no_detail(
        self, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Kills: interpolating the query exception into the envelope."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError(
            'relation "active_memories" does not exist'
        )
        conn.cursor.return_value.__enter__.return_value = cursor
        monkeypatch.setattr(memory_mcp, "_pg_connect", lambda: (conn, None))
        with caplog.at_level("ERROR"):
            data = json.loads(_run(memory_mcp.list_recent(days=7)))
        assert "active_memories" not in data["error"]
        assert "active_memories" in caplog.text

    def test_schema_mismatch_message_is_still_actionable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Our own message has no host detail and tells the operator what to run.

        Kills: sweeping the schema-version text into the generic branch.
        """
        import psycopg2

        def _connect(**kwargs):
            conn = MagicMock()
            cur = MagicMock()
            cur.fetchone.return_value = ("0",)
            conn.cursor.return_value.__enter__.return_value = cur
            return conn

        monkeypatch.setattr(psycopg2, "connect", _connect)
        conn, err = memory_mcp._pg_connect()
        assert conn is None
        assert "schema_version" in err


# -------------------------------------------------------------------------
# Lens B RT13 and RT18: exact id match, and one memory shape across tools
# -------------------------------------------------------------------------

class TestResultShapeAndMatching:
    """Two contracts the tools share."""

    def test_get_memory_jsonl_fallback_matches_the_id_exactly(self) -> None:
        """Kills: ``==`` -> ``startswith`` in the fallback scan."""
        corpus = [{**SAMPLE_RESULTS[0], "id": "2026-04-12-abcdef123456"}]
        with (
            patch.object(memory_mcp.fetch_memories, "try_postgres",
                         return_value=None),
            patch.object(memory_mcp.fetch_memories, "load_jsonl_memories",
                         return_value=corpus),
        ):
            data = json.loads(_run(memory_mcp.get_memory(
                memory_id="2026-04-12-abc")))
        assert data["count"] == 0

    def test_list_recent_and_search_memories_agree_on_the_columns(self) -> None:
        """Kills: letting the two column lists drift apart.

        A client that fetches a memory through one tool and then the other
        should not find a field has vanished; ``verified`` was missing from
        list_recent's list (lens B, RT18).
        """
        columns = [
            "id", "category", "content", "summary", "confidence", "verified",
            "research_tags", "source_context", "created_at", "project",
        ]
        row = tuple(SAMPLE_RESULTS[0].get(c, "true") for c in columns)
        cursor = MagicMock()
        cursor.fetchall.return_value = [row]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.object(memory_mcp, "_pg_connect", return_value=(conn, None)):
            recent = json.loads(_run(memory_mcp.list_recent(days=7)))
        with patch.object(memory_mcp.fetch_memories, "try_postgres",
                          return_value=[{c: "x" for c in columns}]):
            searched = json.loads(_run(memory_mcp.search_memories(query="x")))
        assert set(recent["results"][0]) == set(searched["results"][0])
