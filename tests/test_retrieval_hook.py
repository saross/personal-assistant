"""
Tests for session-start-retrieval.py — scratchpad loading and
integration with memory context output.

Tests pure functions only; does not execute the hook end-to-end.
"""

import importlib
import sys

import pytest

# conftest.py adds hooks/ to sys.path
retrieval = importlib.import_module("session-start-retrieval")


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
