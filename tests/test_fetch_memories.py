"""
Tests for scripts/fetch-memories.py — Tier 2 autonomous memory retrieval.

Tests the JSONL fallback path, filter logic, and output formatting.
PostgreSQL tests verify graceful degradation without requiring a
running database.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# The script has a hyphen in its name, so we need importlib tricks.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
fetch_memories = __import__("fetch-memories")


# ============================================================================
# Test fixtures
# ============================================================================


def _make_memory(
    *,
    mem_id: str = "2026-03-15-abc123",
    category: str = "decision",
    content: str = "Use PostgreSQL for memory queries.",
    summary: str = "Chose PostgreSQL for search.",
    confidence: str = "high",
    tags: list[str] | None = None,
    source_context: str = "Phase 2 planning",
    created_at: str = "2026-03-15T10:00:00+00:00",
    project: str = "-home-shawn-test-project",
) -> dict[str, Any]:
    """Build a sample memory record with sensible defaults."""
    return {
        "id": mem_id,
        "session_id": "test-session-1",
        "project": project,
        "source": "extraction",
        "category": category,
        "content": content,
        "summary": summary,
        "confidence": confidence,
        "research_tags": tags if tags is not None else ["database"],
        "source_context": source_context,
        "created_at": created_at,
    }


def _write_jsonl(path: Path, memories: list[dict]) -> None:
    """Write a list of memory dicts to a JSONL file."""
    with open(path, "w", encoding="utf-8") as fh:
        for mem in memories:
            fh.write(json.dumps(mem, ensure_ascii=False) + "\n")


# ============================================================================
# TestMatchesFilters
# ============================================================================


class TestMatchesFilters:
    """Tests for matches_filters() — JSONL filtering logic."""

    def test_matches_by_tag(self) -> None:
        """Memory matches when any provided tag is present."""
        mem = _make_memory(tags=["validation", "methodology"])
        assert fetch_memories.matches_filters(
            mem, tags=["validation"]
        )

    def test_tag_matching_case_insensitive(self) -> None:
        """Tag matching is case-insensitive."""
        mem = _make_memory(tags=["GPS-Accuracy"])
        assert fetch_memories.matches_filters(
            mem, tags=["gps-accuracy"]
        )

    def test_no_tag_overlap_returns_false(self) -> None:
        """Returns False when no tags overlap."""
        mem = _make_memory(tags=["database"])
        assert not fetch_memories.matches_filters(
            mem, tags=["validation"]
        )

    def test_matches_by_query_in_content(self) -> None:
        """Free-text query matches substring in content field."""
        mem = _make_memory(content="GPS accuracy under canopy")
        assert fetch_memories.matches_filters(
            mem, query="GPS accuracy"
        )

    def test_matches_by_query_in_summary(self) -> None:
        """Free-text query matches substring in summary field."""
        mem = _make_memory(
            content="Unrelated",
            summary="GPS accuracy threshold",
        )
        assert fetch_memories.matches_filters(
            mem, query="GPS accuracy"
        )

    def test_matches_by_query_in_source_context(self) -> None:
        """Free-text query matches substring in source_context."""
        mem = _make_memory(
            content="Unrelated",
            summary="Unrelated",
            source_context="Discussion about GPS accuracy",
        )
        assert fetch_memories.matches_filters(
            mem, query="GPS accuracy"
        )

    def test_query_case_insensitive(self) -> None:
        """Free-text query is case-insensitive."""
        mem = _make_memory(content="GPS Accuracy under canopy")
        assert fetch_memories.matches_filters(
            mem, query="gps accuracy"
        )

    def test_matches_by_category(self) -> None:
        """Category filter uses exact match."""
        mem = _make_memory(category="decision")
        assert fetch_memories.matches_filters(
            mem, category="decision"
        )

    def test_category_mismatch_returns_false(self) -> None:
        """Returns False when category does not match."""
        mem = _make_memory(category="progress")
        assert not fetch_memories.matches_filters(
            mem, category="decision"
        )

    def test_matches_by_id(self) -> None:
        """ID filter uses exact match."""
        mem = _make_memory(mem_id="2026-03-15-abc123")
        assert fetch_memories.matches_filters(
            mem, memory_id="2026-03-15-abc123"
        )

    def test_id_mismatch_returns_false(self) -> None:
        """Returns False when ID does not match."""
        mem = _make_memory(mem_id="2026-03-15-abc123")
        assert not fetch_memories.matches_filters(
            mem, memory_id="2026-03-15-def456"
        )

    def test_and_logic_for_combined_filters(self) -> None:
        """Multiple filters combine with AND logic."""
        mem = _make_memory(
            category="decision",
            tags=["database"],
            content="Use PostgreSQL",
        )
        # Matches: category + tag + query all satisfied
        assert fetch_memories.matches_filters(
            mem,
            category="decision",
            tags=["database"],
            query="PostgreSQL",
        )
        # Fails: tag does not match (AND fails)
        assert not fetch_memories.matches_filters(
            mem,
            category="decision",
            tags=["validation"],
            query="PostgreSQL",
        )

    def test_no_filters_matches_everything(self) -> None:
        """With no filters, every memory matches."""
        mem = _make_memory()
        assert fetch_memories.matches_filters(mem)

    def test_handles_missing_fields_gracefully(self) -> None:
        """Memories with missing optional fields do not raise."""
        mem = {"id": "bare-minimum", "category": "decision"}
        # No content/summary/source_context — should not raise
        assert not fetch_memories.matches_filters(
            mem, query="nonexistent",
        )
        # Category filter still works on sparse records
        assert fetch_memories.matches_filters(
            mem, category="decision",
        )

    def test_handles_string_tags(self) -> None:
        """Tags stored as a single string (not list) are handled."""
        mem = _make_memory()
        mem["research_tags"] = "database"  # String, not list
        assert fetch_memories.matches_filters(
            mem, tags=["database"]
        )

    def test_handles_none_tags(self) -> None:
        """research_tags set to None does not raise."""
        mem = _make_memory()
        mem["research_tags"] = None
        assert not fetch_memories.matches_filters(
            mem, tags=["database"]
        )


# ============================================================================
# TestFallbackJsonl
# ============================================================================


class TestFallbackJsonl:
    """Tests for fallback_jsonl() — end-to-end JSONL retrieval."""

    def test_returns_matching_memories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns memories matching the given tag filter."""
        memories = [
            _make_memory(tags=["validation"]),
            _make_memory(
                mem_id="other",
                tags=["database"],
                created_at="2026-03-14T10:00:00+00:00",
            ),
        ]
        _write_jsonl(tmp_path / "memories.jsonl", memories)
        monkeypatch.setattr(
            fetch_memories, "MEMORIES_FILE",
            tmp_path / "memories.jsonl",
        )

        results = fetch_memories.fallback_jsonl(tags=["validation"])
        assert len(results) == 1
        assert results[0]["id"] == "2026-03-15-abc123"

    def test_sorts_by_created_at_descending(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Results are ordered most-recent first."""
        memories = [
            _make_memory(
                mem_id="old",
                tags=["test"],
                created_at="2026-03-10T10:00:00+00:00",
            ),
            _make_memory(
                mem_id="new",
                tags=["test"],
                created_at="2026-03-20T10:00:00+00:00",
            ),
        ]
        _write_jsonl(tmp_path / "memories.jsonl", memories)
        monkeypatch.setattr(
            fetch_memories, "MEMORIES_FILE",
            tmp_path / "memories.jsonl",
        )

        results = fetch_memories.fallback_jsonl(tags=["test"])
        assert results[0]["id"] == "new"
        assert results[1]["id"] == "old"

    def test_respects_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns at most N results."""
        memories = [
            _make_memory(
                mem_id=f"mem-{i}",
                tags=["common"],
                created_at=f"2026-03-{10+i:02d}T10:00:00+00:00",
            )
            for i in range(5)
        ]
        _write_jsonl(tmp_path / "memories.jsonl", memories)
        monkeypatch.setattr(
            fetch_memories, "MEMORIES_FILE",
            tmp_path / "memories.jsonl",
        )

        results = fetch_memories.fallback_jsonl(
            tags=["common"], limit=2,
        )
        assert len(results) == 2

    def test_returns_empty_for_no_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns empty list when nothing matches."""
        memories = [_make_memory(tags=["database"])]
        _write_jsonl(tmp_path / "memories.jsonl", memories)
        monkeypatch.setattr(
            fetch_memories, "MEMORIES_FILE",
            tmp_path / "memories.jsonl",
        )

        results = fetch_memories.fallback_jsonl(
            tags=["nonexistent"],
        )
        assert results == []

    def test_handles_missing_jsonl_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns empty list when JSONL file does not exist."""
        monkeypatch.setattr(
            fetch_memories, "MEMORIES_FILE",
            tmp_path / "does-not-exist.jsonl",
        )

        results = fetch_memories.fallback_jsonl(tags=["anything"])
        assert results == []


# ============================================================================
# TestFormatOutput
# ============================================================================


class TestFormatOutput:
    """Tests for format_output() — CC-facing output formatting."""

    def test_formats_single_result(self) -> None:
        """Single result produces correct markdown."""
        memories = [_make_memory()]
        output = fetch_memories.format_output(memories)
        assert "## Memory Details (1 result)" in output
        assert "### [1] decision — 2026-03-15" in output
        assert "Use PostgreSQL for memory queries." in output

    def test_formats_multiple_results(self) -> None:
        """Multiple results are numbered sequentially."""
        memories = [
            _make_memory(mem_id="first"),
            _make_memory(mem_id="second"),
        ]
        output = fetch_memories.format_output(memories)
        assert "### [1]" in output
        assert "### [2]" in output
        assert "(2 results)" in output

    def test_zero_results_message(self) -> None:
        """Zero results produce a helpful message."""
        output = fetch_memories.format_output([])
        assert "0 results" in output
        assert "No memories matched" in output

    def test_includes_all_fields(self) -> None:
        """Output includes content, confidence, tags, source."""
        memories = [_make_memory(
            content="Test content here",
            confidence="high",
            tags=["tag-one", "tag-two"],
            source_context="Test source",
        )]
        output = fetch_memories.format_output(memories)
        assert "Test content here" in output
        assert "Confidence: high" in output
        assert "tag-one, tag-two" in output
        assert "Source: Test source" in output

    def test_handles_empty_tags(self) -> None:
        """Memories with no tags show '(none)'."""
        memories = [_make_memory(tags=[])]
        output = fetch_memories.format_output(memories)
        assert "Tags: (none)" in output


# ============================================================================
# TestTryPostgres
# ============================================================================


class TestTryPostgres:
    """Tests for try_postgres() — graceful fallback."""

    def test_returns_none_when_psycopg2_unavailable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns None when psycopg2 cannot be imported."""
        import builtins

        original_import = builtins.__import__

        def mock_import(
            name: str, *args: Any, **kwargs: Any,
        ) -> Any:
            if name == "psycopg2":
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        result = fetch_memories.try_postgres(tags=["test"])
        assert result is None

    def test_returns_none_when_connection_fails(self) -> None:
        """Returns None when database connection fails."""
        with patch("psycopg2.connect") as mock_connect:
            import psycopg2
            mock_connect.side_effect = psycopg2.OperationalError(
                "connection refused"
            )
            result = fetch_memories.try_postgres(tags=["test"])
            assert result is None

    def test_no_stdout_output_on_failure(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Database errors go to stderr, not stdout."""
        with patch("psycopg2.connect") as mock_connect:
            import psycopg2
            mock_connect.side_effect = psycopg2.OperationalError(
                "test error"
            )
            fetch_memories.try_postgres(tags=["test"])

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "test error" in captured.err


# ============================================================================
# Cold archive retrieval (item 13: --include-archive)
# ============================================================================


class TestArchiveRetrieval:
    """Tests for load_archive_memories() and search_archive()."""

    def _write_partition(self, archive_dir: Path, name: str,
                         memories: list[dict[str, Any]]) -> None:
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / name).write_text(
            "".join(json.dumps(m) + "\n" for m in memories),
            encoding="utf-8",
        )

    def test_missing_archive_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fetch_memories, "ARCHIVE_DIR", tmp_path / "nope")
        assert fetch_memories.load_archive_memories() == []

    def test_loads_across_partitions_skipping_junk(self, tmp_path, monkeypatch):
        archive = tmp_path / "archive"
        self._write_partition(archive, "memories-archive-2026-05.jsonl",
                              [_make_memory(mem_id="a")])
        self._write_partition(archive, "memories-archive-2026-06.jsonl",
                              [_make_memory(mem_id="b")])
        # Blank + malformed lines must be skipped, not crash.
        with (archive / "memories-archive-2026-06.jsonl").open(
                "a", encoding="utf-8") as fh:
            fh.write("\n")
            fh.write("not json\n")
        # A non-matching filename must be ignored.
        (archive / "ignore-me.jsonl").write_text(
            json.dumps(_make_memory(mem_id="z")) + "\n", encoding="utf-8")
        monkeypatch.setattr(fetch_memories, "ARCHIVE_DIR", archive)
        ids = {m["id"] for m in fetch_memories.load_archive_memories()}
        assert ids == {"a", "b"}

    def test_search_archive_filters_and_sorts(self, tmp_path, monkeypatch):
        archive = tmp_path / "archive"
        self._write_partition(archive, "memories-archive-2026-06.jsonl", [
            _make_memory(mem_id="old", category="progress",
                         created_at="2026-02-01T00:00:00+00:00",
                         content="alpha milestone"),
            _make_memory(mem_id="new", category="progress",
                         created_at="2026-04-01T00:00:00+00:00",
                         content="alpha milestone"),
            _make_memory(mem_id="other", category="progress",
                         created_at="2026-03-01T00:00:00+00:00",
                         content="beta thing"),
        ])
        monkeypatch.setattr(fetch_memories, "ARCHIVE_DIR", archive)
        hits = fetch_memories.search_archive(query="alpha")
        assert [m["id"] for m in hits] == ["new", "old"]  # recency desc, beta excluded

    def test_search_archive_respects_limit(self, tmp_path, monkeypatch):
        archive = tmp_path / "archive"
        self._write_partition(archive, "memories-archive-2026-06.jsonl",
                              [_make_memory(mem_id=f"m{i}", category="progress")
                               for i in range(5)])
        monkeypatch.setattr(fetch_memories, "ARCHIVE_DIR", archive)
        assert len(fetch_memories.search_archive(category="progress", limit=2)) == 2
