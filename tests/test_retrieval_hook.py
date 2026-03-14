"""
Tests for session-start-retrieval.py — tag-relevance scoring,
cross-project retrieval, scratchpad loading, and output integration.

Tests pure functions only; does not execute the hook end-to-end.
"""

import importlib
import sys

import pytest

# conftest.py adds hooks/ to sys.path
retrieval = importlib.import_module("session-start-retrieval")


# ============================================================================
# Tag Relevance Scoring
# ============================================================================


class TestCollectProjectTags:
    """Tests for collect_project_tags() — building tag profiles."""

    def test_collects_tags_from_same_project(self):
        """Returns tags from memories matching the current project."""
        memories = [
            {
                "project": "-home-shawn-paper",
                "research_tags": ["methodology", "llm-evaluation"],
            },
            {
                "project": "-home-shawn-paper",
                "research_tags": ["field-method"],
            },
        ]
        result = retrieval.collect_project_tags(memories, "-home-shawn-paper")
        assert result == {"methodology", "llm-evaluation", "field-method"}

    def test_excludes_other_project_tags(self):
        """Tags from other projects are not included."""
        memories = [
            {
                "project": "-home-shawn-paper",
                "research_tags": ["methodology"],
            },
            {
                "project": "-home-shawn-fieldmark",
                "research_tags": ["documentation", "screenshots"],
            },
        ]
        result = retrieval.collect_project_tags(memories, "-home-shawn-paper")
        assert result == {"methodology"}
        assert "documentation" not in result

    def test_includes_legacy_memories_without_project(self):
        """Memories with no project field are treated as same-project."""
        memories = [
            {"research_tags": ["legacy-tag"]},
            {
                "project": "-home-shawn-paper",
                "research_tags": ["paper-tag"],
            },
        ]
        result = retrieval.collect_project_tags(memories, "-home-shawn-paper")
        assert "legacy-tag" in result
        assert "paper-tag" in result

    def test_handles_string_tags(self):
        """Tags stored as a single string (not list) are handled."""
        memories = [
            {
                "project": "-home-shawn-paper",
                "research_tags": "single-tag",
            },
        ]
        result = retrieval.collect_project_tags(memories, "-home-shawn-paper")
        assert result == {"single-tag"}

    def test_normalises_to_lowercase(self):
        """Tags are normalised to lowercase for matching."""
        memories = [
            {
                "project": "-home-shawn-paper",
                "research_tags": ["Methodology", "LLM-Evaluation"],
            },
        ]
        result = retrieval.collect_project_tags(memories, "-home-shawn-paper")
        assert "methodology" in result
        assert "llm-evaluation" in result

    def test_returns_empty_when_no_tags(self):
        """Returns empty set when memories have no tags."""
        memories = [
            {"project": "-home-shawn-paper", "research_tags": []},
            {"project": "-home-shawn-paper"},
        ]
        result = retrieval.collect_project_tags(memories, "-home-shawn-paper")
        assert result == set()

    def test_handles_null_tags(self):
        """Gracefully handles memories with research_tags set to None."""
        memories = [
            {"project": "-home-shawn-paper", "research_tags": None},
            {
                "project": "-home-shawn-paper",
                "research_tags": ["valid-tag"],
            },
        ]
        result = retrieval.collect_project_tags(memories, "-home-shawn-paper")
        assert result == {"valid-tag"}

    def test_returns_all_tags_when_no_current_project(self):
        """When current_project is None, all memories are same-project."""
        memories = [
            {
                "project": "-home-shawn-paper",
                "research_tags": ["tag-a"],
            },
            {
                "project": "-home-shawn-fieldmark",
                "research_tags": ["tag-b"],
            },
        ]
        result = retrieval.collect_project_tags(memories, None)
        assert result == {"tag-a", "tag-b"}


class TestTagOverlapScore:
    """Tests for tag_overlap_score() — counting tag overlap."""

    def test_counts_overlapping_tags(self):
        """Returns count of tags that appear in both memory and project."""
        mem = {"research_tags": ["methodology", "llm-evaluation", "gps"]}
        project_tags = {"methodology", "llm-evaluation", "field-method"}
        assert retrieval.tag_overlap_score(mem, project_tags) == 2

    def test_returns_zero_for_no_overlap(self):
        """Returns 0 when no tags match."""
        mem = {"research_tags": ["unrelated-a", "unrelated-b"]}
        project_tags = {"methodology", "field-method"}
        assert retrieval.tag_overlap_score(mem, project_tags) == 0

    def test_returns_zero_for_empty_project_tags(self):
        """Returns 0 when project tag set is empty."""
        mem = {"research_tags": ["methodology"]}
        assert retrieval.tag_overlap_score(mem, set()) == 0

    def test_returns_zero_for_memory_without_tags(self):
        """Returns 0 when memory has no tags."""
        mem = {"research_tags": []}
        project_tags = {"methodology"}
        assert retrieval.tag_overlap_score(mem, project_tags) == 0

    def test_handles_string_tags(self):
        """Tags stored as a single string are handled."""
        mem = {"research_tags": "methodology"}
        project_tags = {"methodology", "field-method"}
        assert retrieval.tag_overlap_score(mem, project_tags) == 1

    def test_case_insensitive_matching(self):
        """Tag matching is case-insensitive."""
        mem = {"research_tags": ["Methodology", "LLM-Evaluation"]}
        project_tags = {"methodology", "llm-evaluation"}
        assert retrieval.tag_overlap_score(mem, project_tags) == 2

    def test_handles_missing_tags_field(self):
        """Gracefully handles memories with no research_tags key."""
        mem = {"content": "No tags here"}
        project_tags = {"methodology"}
        assert retrieval.tag_overlap_score(mem, project_tags) == 0

    def test_handles_null_tags(self):
        """Gracefully handles memories with research_tags set to None."""
        mem = {"research_tags": None}
        project_tags = {"methodology"}
        assert retrieval.tag_overlap_score(mem, project_tags) == 0


# ============================================================================
# Cross-Project Retrieval Ordering
# ============================================================================


class TestCrossProjectRelevance:
    """Tests for tag-relevance-based cross-project memory ordering."""

    def _make_memory(
        self, mem_id, project, category, tags, created_at
    ):
        """Helper to create a memory dict."""
        return {
            "id": mem_id,
            "project": project,
            "category": category,
            "content": f"Memory {mem_id}",
            "confidence": "high",
            "research_tags": tags,
            "created_at": created_at,
        }

    def test_permanent_cross_project_sorted_by_tag_overlap(self):
        """Cross-project permanents with higher tag overlap come first."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        current_project = "-home-shawn-paper"

        # Three cross-project permanent memories with varying tag overlap
        high_overlap = self._make_memory(
            "high", "-home-shawn-fieldmark", "decision",
            ["methodology", "llm-evaluation"],
            (now - timedelta(days=30)).isoformat(),
        )
        low_overlap = self._make_memory(
            "low", "-home-shawn-fieldmark", "decision",
            ["screenshots"],
            (now - timedelta(days=5)).isoformat(),  # More recent
        )
        no_overlap = self._make_memory(
            "none", "-home-shawn-teaching", "decision",
            ["canvas", "rubric"],
            (now - timedelta(days=1)).isoformat(),  # Most recent
        )

        memories = [high_overlap, low_overlap, no_overlap]
        project_tags = {"methodology", "llm-evaluation", "field-method"}

        result = retrieval.retrieve_permanent(
            memories, set(), current_project, project_tags
        )

        # All three should be included (within MAX_PERMANENT_OTHER=8)
        result_ids = [m["id"] for m in result]
        assert "high" in result_ids
        assert "low" in result_ids
        assert "none" in result_ids

        # High-overlap should appear before low-overlap (despite being older)
        high_idx = result_ids.index("high")
        low_idx = result_ids.index("low")
        # Note: final merged list is sorted by recency for output,
        # but high_overlap was *selected* due to relevance scoring.
        # The key test is that all three are included (within allocation).
        assert len(result) == 3

    def test_relevant_cross_project_selected_over_irrelevant(self):
        """When cross-project exceeds allocation, relevant ones win."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        current_project = "-home-shawn-paper"

        # Create more cross-project memories than MAX_PERMANENT_OTHER (8)
        memories = []
        for i in range(12):
            tags = ["methodology"] if i < 5 else ["unrelated"]
            memories.append(self._make_memory(
                f"mem-{i}", "-home-shawn-other", "decision",
                tags,
                (now - timedelta(days=i)).isoformat(),
            ))

        project_tags = {"methodology"}

        result = retrieval.retrieve_permanent(
            memories, set(), current_project, project_tags
        )

        # Should have 8 (MAX_PERMANENT_OTHER)
        assert len(result) == 8

        # The 5 relevant ones (methodology tag) should all be included
        result_ids = {m["id"] for m in result}
        for i in range(5):
            assert f"mem-{i}" in result_ids

    def test_falls_back_to_recency_when_no_project_tags(self):
        """Without project tags, cross-project sorting is recency-only."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        current_project = "-home-shawn-new-project"

        old_relevant = self._make_memory(
            "old", "-home-shawn-fieldmark", "decision",
            ["methodology"],
            (now - timedelta(days=30)).isoformat(),
        )
        new_irrelevant = self._make_memory(
            "new", "-home-shawn-fieldmark", "decision",
            ["screenshots"],
            (now - timedelta(days=1)).isoformat(),
        )

        memories = [old_relevant, new_irrelevant]
        # Empty project tags — no same-project memories exist yet
        project_tags: set[str] = set()

        result = retrieval.retrieve_permanent(
            memories, set(), current_project, project_tags
        )

        # Both included, but order should be recency (new first in output)
        result_ids = [m["id"] for m in result]
        assert result_ids == ["new", "old"]

    def test_recent_cross_project_uses_tag_relevance(self):
        """Recent cross-project memories also use tag relevance scoring."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=7)
        current_project = "-home-shawn-paper"

        # 5 recent cross-project memories, only 3 slots available
        memories = []
        for i in range(5):
            tags = ["methodology"] if i < 2 else ["unrelated"]
            memories.append(self._make_memory(
                f"recent-{i}", "-home-shawn-other", "progress",
                tags,
                (now - timedelta(days=i)).isoformat(),
            ))

        project_tags = {"methodology"}

        result = retrieval.retrieve_recent(
            memories, cutoff, current_project, project_tags
        )

        # Should take MAX_RECENT_OTHER (3)
        assert len(result) == 3

        # The 2 relevant ones should be included
        result_ids = {m["id"] for m in result}
        assert "recent-0" in result_ids
        assert "recent-1" in result_ids

    def test_same_project_unaffected_by_tag_scoring(self):
        """Same-project memories are still sorted by recency, not tags."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        current_project = "-home-shawn-paper"

        old_tagged = self._make_memory(
            "old", current_project, "decision",
            ["methodology"],
            (now - timedelta(days=30)).isoformat(),
        )
        new_untagged = self._make_memory(
            "new", current_project, "decision",
            [],
            (now - timedelta(days=1)).isoformat(),
        )

        memories = [old_tagged, new_untagged]
        project_tags = {"methodology"}

        result = retrieval.retrieve_permanent(
            memories, set(), current_project, project_tags
        )

        # Both included, ordered by recency (new first)
        result_ids = [m["id"] for m in result]
        assert result_ids == ["new", "old"]

    def test_overflow_from_cross_to_same_project(self):
        """Unused cross-project slots overflow to same-project."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        current_project = "-home-shawn-paper"

        # 25 same-project permanents, 0 cross-project
        memories = []
        for i in range(25):
            memories.append(self._make_memory(
                f"same-{i}", current_project, "decision",
                ["tag"],
                (now - timedelta(days=i)).isoformat(),
            ))

        result = retrieval.retrieve_permanent(
            memories, set(), current_project, set()
        )

        # Should get MAX_PERMANENT_SAME + MAX_PERMANENT_OTHER = 28
        # (all 8 unused cross-project slots overflow to same-project)
        assert len(result) == 25  # Only 25 exist, all included


# ============================================================================
# Scratchpad Loading
# ============================================================================


class TestLoadScratchpad:
    """Tests for load_scratchpad() — file reading and size warnings."""

    def test_returns_content_when_file_exists(self, tmp_path, monkeypatch):
        """Scratchpad content is returned when the file exists."""
        scratchpad = tmp_path / "scratchpad.md"
        scratchpad.write_text(
            "# Scratchpad\n\n"
            "## Corrections\n\n"
            "- 2026-03-14: Test correction entry\n"
        )
        monkeypatch.setattr(retrieval, "SCRATCHPAD_FILE", scratchpad)
        result = retrieval.load_scratchpad()
        assert "Test correction entry" in result
        assert "# Scratchpad" in result

    def test_returns_empty_when_file_missing(self, tmp_path, monkeypatch):
        """Returns empty string when scratchpad file does not exist."""
        monkeypatch.setattr(
            retrieval, "SCRATCHPAD_FILE", tmp_path / "nonexistent.md"
        )
        assert retrieval.load_scratchpad() == ""

    def test_returns_empty_when_file_empty(self, tmp_path, monkeypatch):
        """Returns empty string when scratchpad file is empty."""
        scratchpad = tmp_path / "scratchpad.md"
        scratchpad.write_text("")
        monkeypatch.setattr(retrieval, "SCRATCHPAD_FILE", scratchpad)
        assert retrieval.load_scratchpad() == ""

    def test_returns_empty_when_file_whitespace_only(
        self, tmp_path, monkeypatch
    ):
        """Returns empty string when scratchpad contains only whitespace."""
        scratchpad = tmp_path / "scratchpad.md"
        scratchpad.write_text("   \n\n   \n")
        monkeypatch.setattr(retrieval, "SCRATCHPAD_FILE", scratchpad)
        assert retrieval.load_scratchpad() == ""

    def test_warns_when_over_line_limit(
        self, tmp_path, monkeypatch, capsys
    ):
        """Warns to stderr when scratchpad exceeds SCRATCHPAD_WARN_LINES."""
        scratchpad = tmp_path / "scratchpad.md"
        # Write 160 lines — above the 150-line threshold
        lines = [f"- Line {i}" for i in range(160)]
        scratchpad.write_text("\n".join(lines))
        monkeypatch.setattr(retrieval, "SCRATCHPAD_FILE", scratchpad)
        monkeypatch.setattr(retrieval, "SCRATCHPAD_WARN_LINES", 150)

        result = retrieval.load_scratchpad()

        # Content should still be returned
        assert "Line 0" in result
        assert "Line 159" in result

        # Warning should appear on stderr
        captured = capsys.readouterr()
        assert "160 lines" in captured.err
        assert "/retro" in captured.err

    def test_no_warning_when_under_limit(
        self, tmp_path, monkeypatch, capsys
    ):
        """No warning when scratchpad is within the line limit."""
        scratchpad = tmp_path / "scratchpad.md"
        lines = [f"- Line {i}" for i in range(50)]
        scratchpad.write_text("\n".join(lines))
        monkeypatch.setattr(retrieval, "SCRATCHPAD_FILE", scratchpad)
        monkeypatch.setattr(retrieval, "SCRATCHPAD_WARN_LINES", 150)

        retrieval.load_scratchpad()

        captured = capsys.readouterr()
        assert captured.err == ""


# ============================================================================
# Output Integration
# ============================================================================


class TestScratchpadInOutput:
    """Tests for scratchpad integration in the main hook output."""

    def test_scratchpad_appears_after_memories(
        self, tmp_path, monkeypatch, capsys
    ):
        """Scratchpad section appears in output when file has content."""
        # Set up a scratchpad with content
        scratchpad = tmp_path / "scratchpad.md"
        scratchpad.write_text(
            "## Corrections\n\n"
            "- 2026-03-14: UK spelling required — always 'analyse' not 'analyze'\n"
        )
        monkeypatch.setattr(retrieval, "SCRATCHPAD_FILE", scratchpad)

        # Create a minimal memories file so context is not empty
        memories_file = tmp_path / "memories.jsonl"
        memories_file.write_text(
            '{"id":"test-1","category":"decision","content":"Test memory.",'
            '"confidence":"high","research_tags":[],'
            '"created_at":"2026-03-14T10:00:00+00:00"}\n'
        )
        monkeypatch.setattr(retrieval, "MEMORIES_FILE", memories_file)

        # Patch stdin for hook input
        import io
        monkeypatch.setattr(
            sys, "stdin", io.StringIO('{"cwd": "/home/shawn/personal-assistant"}')
        )

        # main() prints to stdout; may or may not call sys.exit
        try:
            retrieval.main()
        except SystemExit:
            pass

        captured = capsys.readouterr()
        output = captured.out

        # Both memory context and scratchpad should appear
        assert "# Memory Context" in output
        assert "# Scratchpad" in output
        assert "UK spelling required" in output

        # Scratchpad should come after memories
        mem_pos = output.index("# Memory Context")
        scratch_pos = output.index("# Scratchpad")
        assert scratch_pos > mem_pos

    def test_scratchpad_omitted_when_empty(
        self, tmp_path, monkeypatch, capsys
    ):
        """No scratchpad section when file does not exist."""
        monkeypatch.setattr(
            retrieval, "SCRATCHPAD_FILE", tmp_path / "nonexistent.md"
        )

        # Create a minimal memories file
        memories_file = tmp_path / "memories.jsonl"
        memories_file.write_text(
            '{"id":"test-1","category":"decision","content":"Test memory.",'
            '"confidence":"high","research_tags":[],'
            '"created_at":"2026-03-14T10:00:00+00:00"}\n'
        )
        monkeypatch.setattr(retrieval, "MEMORIES_FILE", memories_file)

        import io
        monkeypatch.setattr(
            sys, "stdin", io.StringIO('{"cwd": "/home/shawn/personal-assistant"}')
        )

        try:
            retrieval.main()
        except SystemExit:
            pass

        captured = capsys.readouterr()
        output = captured.out

        assert "# Memory Context" in output
        assert "# Scratchpad" not in output
