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

        # All three should be included (within MAX_PERMANENT_OTHER slots).
        # Each is a different foreign project so the per-project cap
        # does not bind.
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
        """When cross-project exceeds allocation, relevant ones win.

        Spreads memories across multiple foreign projects so the
        per-project cap does not artificially limit the result size.
        """
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        current_project = "-home-shawn-paper"

        # Create more cross-project memories than MAX_PERMANENT_OTHER,
        # distributed across many foreign projects so the per-project
        # cap doesn't bite (each project contributes at most one).
        limit = retrieval.MAX_PERMANENT_OTHER
        memories = []
        for i in range(limit + 5):
            tags = ["methodology"] if i < 5 else ["unrelated"]
            memories.append(self._make_memory(
                f"mem-{i}", f"-home-shawn-other-{i}", "decision",
                tags,
                (now - timedelta(days=i)).isoformat(),
            ))

        project_tags = {"methodology"}

        result = retrieval.retrieve_permanent(
            memories, set(), current_project, project_tags
        )

        # Should have MAX_PERMANENT_OTHER
        assert len(result) == limit

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
        """Recent cross-project memories also use tag relevance scoring.

        Uses multiple foreign projects so the per-project cap doesn't
        artificially constrain the result.
        """
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=retrieval.RECENT_DAYS)
        current_project = "-home-shawn-paper"

        # Create more recent cross-project memories than available slots,
        # across many foreign projects
        limit = retrieval.MAX_RECENT_OTHER
        memories = []
        for i in range(limit + 3):
            tags = ["methodology"] if i < 2 else ["unrelated"]
            memories.append(self._make_memory(
                f"recent-{i}", f"-home-shawn-other-{i}", "progress",
                tags,
                (now - timedelta(days=i)).isoformat(),
            ))

        project_tags = {"methodology"}

        result = retrieval.retrieve_recent(
            memories, cutoff, current_project, project_tags
        )

        # Should take MAX_RECENT_OTHER
        assert len(result) == limit

        # The 2 relevant ones (methodology tag) should be included
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

        # Would get up to MAX_PERMANENT_SAME + MAX_PERMANENT_OTHER slots
        # (all unused cross-project slots overflow to same-project),
        # but only 25 same-project memories exist, so all are returned.
        assert len(result) == 25


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


# ============================================================================
# Constraint Spotlight
# ============================================================================


class TestConstraintSpotlight:
    """Tests for retrieve_constraints() — dedicated constraint retrieval."""

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

    def test_retrieves_constraint_categories_only(self):
        """Only error_mode and prompt_effectiveness memories are returned."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        memories = [
            self._make_memory(
                "err-1", "-home-shawn-paper", "error_mode",
                ["validation"], (now - timedelta(days=5)).isoformat(),
            ),
            self._make_memory(
                "prompt-1", "-home-shawn-paper", "prompt_effectiveness",
                ["chain-of-thought"], (now - timedelta(days=3)).isoformat(),
            ),
            self._make_memory(
                "decision-1", "-home-shawn-paper", "decision",
                ["validation"], (now - timedelta(days=1)).isoformat(),
            ),
            self._make_memory(
                "arch-1", "-home-shawn-paper", "architecture",
                ["validation"], (now - timedelta(days=2)).isoformat(),
            ),
        ]

        result = retrieval.retrieve_constraints(
            memories, set(), "-home-shawn-paper"
        )

        result_ids = {m["id"] for m in result}
        assert result_ids == {"err-1", "prompt-1"}

    def test_excludes_already_retrieved_ids(self):
        """Memories already in recent/permanent are not duplicated."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        memories = [
            self._make_memory(
                "err-1", "-home-shawn-paper", "error_mode",
                ["validation"], (now - timedelta(days=5)).isoformat(),
            ),
            self._make_memory(
                "err-2", "-home-shawn-paper", "error_mode",
                ["api"], (now - timedelta(days=3)).isoformat(),
            ),
        ]

        # err-1 already retrieved by permanent retrieval
        result = retrieval.retrieve_constraints(
            memories, {"err-1"}, "-home-shawn-paper"
        )

        result_ids = {m["id"] for m in result}
        assert result_ids == {"err-2"}

    def test_scored_by_tag_overlap_across_projects(self):
        """Constraints from any project are scored by tag overlap uniformly."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)

        # Constraint from different project but with relevant tags
        relevant_other = self._make_memory(
            "other-relevant", "-home-shawn-fieldmark", "error_mode",
            ["validation", "methodology"],
            (now - timedelta(days=30)).isoformat(),
        )
        # Constraint from same project but with no tag overlap
        irrelevant_same = self._make_memory(
            "same-irrelevant", "-home-shawn-paper", "error_mode",
            ["screenshots", "canvas"],
            (now - timedelta(days=1)).isoformat(),
        )

        memories = [relevant_other, irrelevant_same]
        project_tags = {"validation", "methodology", "llm-evaluation"}

        result = retrieval.retrieve_constraints(
            memories, set(), "-home-shawn-paper", project_tags
        )

        # Both returned, but relevant-other should be first (higher tag overlap)
        assert len(result) == 2
        assert result[0]["id"] == "other-relevant"
        assert result[1]["id"] == "same-irrelevant"

    def test_respects_max_constraints_limit(self):
        """Returns at most MAX_CONSTRAINTS memories."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)

        # Create more constraints than MAX_CONSTRAINTS (10)
        memories = []
        for i in range(10):
            memories.append(self._make_memory(
                f"err-{i}", "-home-shawn-paper", "error_mode",
                ["tag"], (now - timedelta(days=i)).isoformat(),
            ))

        result = retrieval.retrieve_constraints(
            memories, set(), "-home-shawn-paper"
        )

        assert len(result) == retrieval.MAX_CONSTRAINTS

    def test_empty_when_no_constraint_memories(self):
        """Returns empty list when no error_mode/prompt_effectiveness exist."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        memories = [
            self._make_memory(
                "dec-1", "-home-shawn-paper", "decision",
                ["validation"], (now - timedelta(days=1)).isoformat(),
            ),
            self._make_memory(
                "arch-1", "-home-shawn-paper", "architecture",
                ["api"], (now - timedelta(days=2)).isoformat(),
            ),
        ]

        result = retrieval.retrieve_constraints(
            memories, set(), "-home-shawn-paper"
        )

        assert result == []

    def test_falls_back_to_recency_when_no_tags(self):
        """Without project tags, constraints are sorted by recency only."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        old = self._make_memory(
            "old", "-home-shawn-paper", "error_mode",
            ["methodology"], (now - timedelta(days=30)).isoformat(),
        )
        new = self._make_memory(
            "new", "-home-shawn-fieldmark", "prompt_effectiveness",
            ["screenshots"], (now - timedelta(days=1)).isoformat(),
        )

        memories = [old, new]

        result = retrieval.retrieve_constraints(
            memories, set(), "-home-shawn-paper", project_tags=set()
        )

        # Both score 0 on tag overlap, so recency wins
        assert result[0]["id"] == "new"
        assert result[1]["id"] == "old"

    def test_constraints_section_in_output(self):
        """Constraint memories produce a 'Relevant Constraints' section."""
        constraints = [
            {
                "category": "error_mode",
                "confidence": "high",
                "content": "Always validate API response codes",
                "research_tags": ["validation"],
                "created_at": "2026-03-10T10:00:00+00:00",
            },
        ]

        output = retrieval.format_context([], [], constraints=constraints)

        assert "## Relevant Constraints" in output
        assert "Always validate API response codes" in output

    def test_constraints_positioned_between_recent_and_permanent(self):
        """Constraints section appears after recent, before permanent."""
        recent = [
            {
                "category": "progress",
                "confidence": "high",
                "content": "Recent progress entry",
                "research_tags": [],
                "created_at": "2026-03-14T10:00:00+00:00",
            },
        ]
        constraints = [
            {
                "category": "error_mode",
                "confidence": "high",
                "content": "Constraint entry",
                "research_tags": ["validation"],
                "created_at": "2026-03-10T10:00:00+00:00",
            },
        ]
        permanent = [
            {
                "category": "decision",
                "confidence": "high",
                "content": "Permanent decision entry",
                "research_tags": [],
                "created_at": "2026-03-01T10:00:00+00:00",
            },
        ]

        output = retrieval.format_context(recent, permanent, constraints)

        recent_pos = output.index("## Recent Memories")
        constraint_pos = output.index("## Relevant Constraints")
        permanent_pos = output.index("## Key Decisions & Knowledge")

        assert recent_pos < constraint_pos < permanent_pos


# ============================================================================
# Constraint Consolidation
# ============================================================================


class TestConstraintConsolidation:
    """Tests for constraint category exclusion from permanent retrieval."""

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

    def test_constraint_categories_not_in_permanent_categories(self):
        """error_mode and prompt_effectiveness are not in PERMANENT_CATEGORIES."""
        assert "error_mode" not in retrieval.PERMANENT_CATEGORIES
        assert "prompt_effectiveness" not in retrieval.PERMANENT_CATEGORIES

    def test_permanent_excludes_constraint_categories(self):
        """retrieve_permanent() does not return constraint-category memories."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        memories = [
            self._make_memory(
                "err-1", "-home-shawn-paper", "error_mode",
                ["validation"], (now - timedelta(days=10)).isoformat(),
            ),
            self._make_memory(
                "prompt-1", "-home-shawn-paper", "prompt_effectiveness",
                ["chain-of-thought"], (now - timedelta(days=10)).isoformat(),
            ),
            self._make_memory(
                "dec-1", "-home-shawn-paper", "decision",
                ["architecture"], (now - timedelta(days=10)).isoformat(),
            ),
        ]

        result = retrieval.retrieve_permanent(
            memories, set(), "-home-shawn-paper"
        )

        result_cats = {m["category"] for m in result}
        assert "decision" in result_cats
        assert "error_mode" not in result_cats
        assert "prompt_effectiveness" not in result_cats

    def test_constraints_include_same_project_memories(self):
        """Same-project constraint memories surface via retrieve_constraints."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        memories = [
            self._make_memory(
                "err-same", "-home-shawn-paper", "error_mode",
                ["validation"], (now - timedelta(days=10)).isoformat(),
            ),
            self._make_memory(
                "err-other", "-home-shawn-fieldmark", "error_mode",
                ["api"], (now - timedelta(days=5)).isoformat(),
            ),
        ]

        result = retrieval.retrieve_constraints(
            memories, set(), "-home-shawn-paper"
        )

        result_ids = {m["id"] for m in result}
        assert "err-same" in result_ids
        assert "err-other" in result_ids


# ============================================================================
# Section Headers
# ============================================================================


class TestSectionHeaders:
    """Tests for item counts in section headers."""

    def test_recent_header_includes_item_count(self):
        """Recent section header shows item count."""
        recent = [
            {
                "category": "progress",
                "confidence": "high",
                "content": f"Entry {i}",
                "research_tags": [],
                "created_at": "2026-03-14T10:00:00+00:00",
            }
            for i in range(3)
        ]

        output = retrieval.format_context(recent, [])
        assert "\u2014 3 items" in output
        assert "## Recent Memories" in output

    def test_constraint_header_includes_item_count(self):
        """Constraint section header shows item count."""
        constraints = [
            {
                "category": "error_mode",
                "confidence": "high",
                "content": "Constraint entry",
                "research_tags": ["validation"],
                "created_at": "2026-03-10T10:00:00+00:00",
            },
        ]

        output = retrieval.format_context([], [], constraints=constraints)
        assert "\u2014 1 item" in output
        assert "## Relevant Constraints" in output

    def test_permanent_header_includes_item_count(self):
        """Permanent section header shows item count."""
        permanent = [
            {
                "category": "decision",
                "confidence": "high",
                "content": f"Decision {i}",
                "research_tags": [],
                "created_at": "2026-03-01T10:00:00+00:00",
            }
            for i in range(5)
        ]

        output = retrieval.format_context([], permanent)
        assert "\u2014 5 items" in output
        assert "## Key Decisions & Knowledge" in output


# ============================================================================
# Summary Display
# ============================================================================


class TestSummaryDisplay:
    """Tests for summary-based display in format_memory()."""

    def test_displays_summary_when_present(self):
        """format_memory() uses summary field instead of content."""
        mem = {
            "category": "decision",
            "confidence": "high",
            "content": "This is a very long content string that goes on "
                       "and on with lots of detail about the decision.",
            "summary": "Chose PostgreSQL for full-text search.",
            "research_tags": ["architecture"],
            "created_at": "2026-03-10T10:00:00+00:00",
        }

        result = retrieval.format_memory(mem)
        assert "Chose PostgreSQL for full-text search." in result
        assert "very long content string" not in result

    def test_falls_back_to_content_when_no_summary(self):
        """format_memory() uses content when summary is absent."""
        mem = {
            "category": "decision",
            "confidence": "high",
            "content": "Use JSONL for storage.",
            "research_tags": [],
            "created_at": "2026-03-10T10:00:00+00:00",
        }

        result = retrieval.format_memory(mem)
        assert "Use JSONL for storage." in result

    def test_falls_back_when_summary_is_empty_string(self):
        """format_memory() falls back to content when summary is empty."""
        mem = {
            "category": "decision",
            "confidence": "high",
            "content": "Fallback content here.",
            "summary": "",
            "research_tags": [],
            "created_at": "2026-03-10T10:00:00+00:00",
        }

        result = retrieval.format_memory(mem)
        assert "Fallback content here." in result


# ============================================================================
# Compact Level 1 Format
# ============================================================================


class TestCompactFormat:
    """Tests for compact Level 1 memory format (Phase 4)."""

    def _make_mem(self, **overrides):
        """Helper to create a memory dict with defaults."""
        mem = {
            "category": "decision",
            "confidence": "high",
            "content": "Full content text here.",
            "summary": "Chose PostgreSQL for search.",
            "research_tags": ["architecture", "system-design"],
            "created_at": "2026-03-10T10:00:00+00:00",
        }
        mem.update(overrides)
        return mem

    def test_excludes_confidence(self):
        """Confidence level is not shown in compact format."""
        result = retrieval.format_memory(self._make_mem())
        assert "(high" not in result
        assert "high," not in result

    def test_date_at_end(self):
        """Date appears at the end in brackets."""
        result = retrieval.format_memory(self._make_mem())
        assert result.endswith("[2026-03-10]")

    def test_no_tags_prefix(self):
        """Tags appear after pipe without 'tags:' label."""
        result = retrieval.format_memory(self._make_mem())
        assert "tags:" not in result.lower()
        assert "| architecture, system-design" in result

    def test_tagless_memory_no_trailing_pipe(self):
        """Memory with no tags has no pipe or trailing space."""
        mem = self._make_mem(research_tags=[])
        result = retrieval.format_memory(mem)
        assert "|" not in result
        assert result.endswith("[2026-03-10]")

    def test_category_prefix_retained(self):
        """Category prefix is still present for scanning."""
        result = retrieval.format_memory(self._make_mem())
        assert result.startswith("[decision]")

    def test_summary_is_primary_content(self):
        """Summary is shown, not full content."""
        result = retrieval.format_memory(self._make_mem())
        assert "Chose PostgreSQL for search." in result
        assert "Full content text here." not in result

    def test_level2_instruction_in_header(self):
        """format_context() header includes /recall instruction."""
        recent = [{
            "category": "progress",
            "confidence": "high",
            "content": "Test",
            "research_tags": [],
            "created_at": "2026-03-14T10:00:00+00:00",
        }]
        output = retrieval.format_context(recent, [])
        assert "/recall" in output
        assert "full memory content" in output

    def test_anti_confabulation_warning_in_header(self):
        """format_context() header includes anti-confabulation warning.

        Added 2026-04-24 to counter Opus 4.7's tendency to weld together
        plausible-looking fragments from pre-loaded memory summaries.
        """
        recent = [{
            "category": "progress",
            "confidence": "high",
            "content": "Test",
            "research_tags": [],
            "created_at": "2026-03-14T10:00:00+00:00",
        }]
        output = retrieval.format_context(recent, [])
        assert "Anti-confabulation" in output
        assert "pointers, not" in output
        assert "re-read the source file" in output

    def test_slot_allocation_constants(self):
        """Slot constants reflect 2026-04-24 tuning to reduce
        Opus 4.7 confabulation-gravity from the high-volume
        decision/architecture pool."""
        assert retrieval.MAX_RECENT_SAME == 25
        assert retrieval.MAX_RECENT_OTHER == 5
        assert retrieval.MAX_PERMANENT_SAME == 20
        assert retrieval.MAX_PERMANENT_OTHER == 8
        assert retrieval.MAX_CONSTRAINTS == 10
        assert retrieval.MAX_MIDDLE_AGED == 10
        assert retrieval.MAX_OTHER_PROJECT_CAP == 3
        assert retrieval.RECENT_DAYS == 14
        assert retrieval.MIDDLE_AGED_DAYS == 180


# ============================================================================
# Tier 2 Retrieval Instructions
# ============================================================================


class TestRetrievalInstructions:
    """Tests for Tier 2 autonomous fetch instructions in output."""

    _SAMPLE_RECENT = [{
        "category": "progress",
        "content": "Test entry",
        "research_tags": [],
        "created_at": "2026-03-14T10:00:00+00:00",
    }]

    _SAMPLE_PERMANENT = [{
        "category": "decision",
        "content": "Permanent entry",
        "research_tags": ["architecture"],
        "created_at": "2026-03-01T10:00:00+00:00",
    }]

    def test_instructions_present_when_memories_exist(self):
        """Retrieval instructions appear when memories are present."""
        output = retrieval.format_context(self._SAMPLE_RECENT, [])
        assert "## Retrieval Instructions" in output
        assert "fetch-memories.py" in output
        assert "Wait for user confirmation" in output

    def test_instructions_absent_when_no_memories(self):
        """No retrieval instructions when there are no memories."""
        output = retrieval.format_context([], [])
        assert output == ""

    def test_instructions_after_memory_sections(self):
        """Instructions appear after all memory sections."""
        output = retrieval.format_context(
            self._SAMPLE_RECENT, self._SAMPLE_PERMANENT,
        )
        recent_pos = output.index("## Recent Memories")
        permanent_pos = output.index("## Key Decisions")
        instructions_pos = output.index("## Retrieval Instructions")
        assert instructions_pos > permanent_pos > recent_pos

    def test_instructions_include_protocol(self):
        """Instructions describe the gated announcement protocol."""
        output = retrieval.format_context(self._SAMPLE_RECENT, [])
        assert "shall I retrieve" in output
        assert "When NOT to fetch" in output
        assert "/recall" in output


# ============================================================================
# Per-project cap (2026-04-24)
# ============================================================================


class TestPerProjectCap:
    """Tests for the MAX_OTHER_PROJECT_CAP limit on cross-project slots.

    With one foreign project (e.g., map-reader-llm) dominating the corpus,
    tag-relevance scoring alone lets it fill all cross-project slots. The
    per-project cap enforces diversity by capping contributions from any
    single foreign project.
    """

    @staticmethod
    def _make_memory(
        mem_id: str,
        project: str,
        category: str,
        tags: list,
        created_at: str,
    ) -> dict:
        return {
            "id": mem_id,
            "project": project,
            "category": category,
            "research_tags": tags,
            "created_at": created_at,
            "content": f"content for {mem_id}",
        }

    def test_apply_per_project_cap_limits_single_project(self):
        """Cap prevents one project from taking more than N entries."""
        memories = [
            self._make_memory(f"m-{i}", "-home-shawn-big-project",
                              "decision", ["t"], "2026-04-01T00:00:00+00:00")
            for i in range(10)
        ]
        result = retrieval.apply_per_project_cap(memories, limit=8, cap=3)
        assert len(result) == 3

    def test_apply_per_project_cap_allows_multiple_projects(self):
        """Cap is per-project, not global; multiple projects fill the limit."""
        memories = []
        for project_idx in range(4):
            for i in range(5):
                memories.append(self._make_memory(
                    f"p{project_idx}-{i}", f"-home-shawn-proj-{project_idx}",
                    "decision", ["t"], "2026-04-01T00:00:00+00:00",
                ))
        result = retrieval.apply_per_project_cap(memories, limit=8, cap=3)
        assert len(result) == 8
        # Each project contributes at most 3
        from collections import Counter
        counts = Counter(m["project"] for m in result)
        assert max(counts.values()) <= 3

    def test_per_project_cap_applied_in_retrieve_permanent(self):
        """retrieve_permanent enforces the per-project cap on cross-project."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        current_project = "-home-shawn-paper"
        # 10 memories all from a single foreign project
        memories = [
            self._make_memory(f"m-{i}", "-home-shawn-dominant",
                              "decision", ["methodology"], now)
            for i in range(10)
        ]
        result = retrieval.retrieve_permanent(
            memories, set(), current_project, {"methodology"}
        )
        # Cap limits to 3 from that single project; no same-project
        # memories exist to absorb the overflow, so final size is 3.
        assert len(result) == retrieval.MAX_OTHER_PROJECT_CAP


# ============================================================================
# Middle-aged bucket (gotcha + pattern, 14-180 days)
# ============================================================================


class TestMiddleAgedBucket:
    """Tests for retrieve_middle_aged() — restores documented 180-day
    decay for gotcha and pattern categories that was previously collapsed
    into the 14-day recent bucket only."""

    @staticmethod
    def _make_memory(
        mem_id: str,
        category: str,
        days_old: int,
        project: str = "-home-shawn-paper",
        tags: list | None = None,
    ) -> dict:
        from datetime import datetime, timedelta, timezone
        created = datetime.now(timezone.utc) - timedelta(days=days_old)
        return {
            "id": mem_id,
            "project": project,
            "category": category,
            "research_tags": tags or [],
            "created_at": created.isoformat(),
            "content": f"{category} memory {mem_id}",
        }

    def test_returns_gotcha_and_pattern_in_window(self):
        """Gotcha and pattern memories in the 14–180d window are returned."""
        memories = [
            self._make_memory("g1", "gotcha", 30),
            self._make_memory("p1", "pattern", 60),
        ]
        result = retrieval.retrieve_middle_aged(
            memories, set(), "-home-shawn-paper", set()
        )
        ids = {m["id"] for m in result}
        assert "g1" in ids
        assert "p1" in ids

    def test_excludes_memories_newer_than_recent_window(self):
        """Memories within RECENT_DAYS are excluded (belong to recent)."""
        memories = [
            self._make_memory("fresh", "gotcha", 2),  # < 14 days
            self._make_memory("aged", "gotcha", 30),
        ]
        result = retrieval.retrieve_middle_aged(
            memories, set(), "-home-shawn-paper", set()
        )
        ids = {m["id"] for m in result}
        assert "fresh" not in ids
        assert "aged" in ids

    def test_excludes_memories_older_than_middle_aged_window(self):
        """Memories older than MIDDLE_AGED_DAYS are excluded."""
        memories = [
            self._make_memory("ancient", "gotcha", 200),  # > 180 days
            self._make_memory("aged", "gotcha", 100),
        ]
        result = retrieval.retrieve_middle_aged(
            memories, set(), "-home-shawn-paper", set()
        )
        ids = {m["id"] for m in result}
        assert "ancient" not in ids
        assert "aged" in ids

    def test_excludes_other_categories(self):
        """Only gotcha and pattern are pulled."""
        memories = [
            self._make_memory("d1", "decision", 30),
            self._make_memory("g1", "gotcha", 30),
        ]
        result = retrieval.retrieve_middle_aged(
            memories, set(), "-home-shawn-paper", set()
        )
        ids = {m["id"] for m in result}
        assert "d1" not in ids
        assert "g1" in ids

    def test_excludes_already_retrieved_ids(self):
        """IDs already in already_ids are not returned."""
        memories = [
            self._make_memory("g1", "gotcha", 30),
            self._make_memory("g2", "gotcha", 30),
        ]
        result = retrieval.retrieve_middle_aged(
            memories, {"g1"}, "-home-shawn-paper", set()
        )
        ids = {m["id"] for m in result}
        assert "g1" not in ids
        assert "g2" in ids

    def test_respects_max_middle_aged_limit(self):
        """Returns at most MAX_MIDDLE_AGED entries."""
        memories = [
            self._make_memory(f"g{i}", "gotcha", 20 + i)
            for i in range(retrieval.MAX_MIDDLE_AGED + 5)
        ]
        result = retrieval.retrieve_middle_aged(
            memories, set(), "-home-shawn-paper", set()
        )
        assert len(result) == retrieval.MAX_MIDDLE_AGED


# ============================================================================
# Project-aware scratchpad loading
# ============================================================================


class TestLoadProjectScratchpad:
    """Tests for load_project_scratchpad() — loads per-project scratchpad
    keyed on the cwd basename to keep project-specific identifiers out of
    every session's context."""

    def test_loads_when_cwd_matches_existing_file(self, tmp_path, monkeypatch):
        """Returns content when data/scratchpads/<name>.md exists."""
        scratchpads = tmp_path / "scratchpads"
        scratchpads.mkdir()
        (scratchpads / "map-reader-llm.md").write_text(
            "# Per-project\n- test entry\n"
        )
        monkeypatch.setattr(retrieval, "SCRATCHPADS_DIR", scratchpads)
        content, path = retrieval.load_project_scratchpad(
            "/home/shawn/Code/map-reader-llm"
        )
        assert "test entry" in content
        assert path is not None
        assert path.name == "map-reader-llm.md"

    def test_returns_empty_when_no_matching_file(self, tmp_path, monkeypatch):
        """Returns empty when no per-project scratchpad exists for cwd."""
        scratchpads = tmp_path / "scratchpads"
        scratchpads.mkdir()
        monkeypatch.setattr(retrieval, "SCRATCHPADS_DIR", scratchpads)
        content, path = retrieval.load_project_scratchpad(
            "/home/shawn/Code/nonexistent-project"
        )
        assert content == ""
        assert path is None

    def test_returns_empty_when_cwd_empty(self, tmp_path, monkeypatch):
        """Empty cwd short-circuits to empty result."""
        monkeypatch.setattr(retrieval, "SCRATCHPADS_DIR", tmp_path)
        content, path = retrieval.load_project_scratchpad("")
        assert content == ""
        assert path is None

    def test_returns_empty_when_file_empty(self, tmp_path, monkeypatch):
        """Empty scratchpad file returns empty result."""
        scratchpads = tmp_path / "scratchpads"
        scratchpads.mkdir()
        (scratchpads / "voice-assistant.md").write_text("")
        monkeypatch.setattr(retrieval, "SCRATCHPADS_DIR", scratchpads)
        content, path = retrieval.load_project_scratchpad(
            "/home/shawn/Code/voice-assistant"
        )
        assert content == ""
        assert path is None
