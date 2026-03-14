"""
Tests for sync-to-postgres.py — cursor management, JSONL parsing,
and record-to-tuple conversion.

Tests pure functions only; does not require a running PostgreSQL instance.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Import the sync module (hyphenated filename requires importlib)
_sync_path = Path(__file__).parent.parent / "scripts" / "sync-to-postgres.py"
_spec = importlib.util.spec_from_file_location("sync_to_postgres", _sync_path)
sync_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_mod)


# ============================================================================
# Cursor Management
# ============================================================================


class TestCursorLoadSave:
    """Cursor file read/write roundtrip and edge cases."""

    def test_load_returns_zero_when_no_file(self, tmp_path, monkeypatch):
        """Missing cursor file should return 0."""
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", tmp_path / "missing.json")
        assert sync_mod.load_cursor() == 0

    def test_roundtrip(self, tmp_path, monkeypatch):
        """Save then load should return the same value."""
        cursor_file = tmp_path / "sync-cursors.json"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        sync_mod.save_cursor(42)
        assert sync_mod.load_cursor() == 42

    def test_roundtrip_preserves_other_keys(self, tmp_path, monkeypatch):
        """Saving a cursor should not clobber other keys in the file."""
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(json.dumps({"other_key": "preserved"}) + "\n")
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        sync_mod.save_cursor(99)
        data = json.loads(cursor_file.read_text())
        assert data["other_key"] == "preserved"
        assert data["postgres_sync_line"] == 99

    def test_load_handles_corrupt_json(self, tmp_path, monkeypatch):
        """Corrupt cursor file should return 0 rather than crash."""
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text("not valid json{{{")
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        assert sync_mod.load_cursor() == 0

    def test_load_handles_missing_key(self, tmp_path, monkeypatch):
        """Cursor file exists but doesn't have our key."""
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(json.dumps({"unrelated": 5}) + "\n")
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        assert sync_mod.load_cursor() == 0

    def test_save_creates_file_if_missing(self, tmp_path, monkeypatch):
        """save_cursor should create the file if it doesn't exist."""
        cursor_file = tmp_path / "new-cursors.json"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        sync_mod.save_cursor(10)
        assert cursor_file.exists()
        assert json.loads(cursor_file.read_text())["postgres_sync_line"] == 10

    def test_cursor_increments(self, tmp_path, monkeypatch):
        """Multiple saves should each update the value."""
        cursor_file = tmp_path / "sync-cursors.json"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        sync_mod.save_cursor(0)
        sync_mod.save_cursor(50)
        sync_mod.save_cursor(100)
        assert sync_mod.load_cursor() == 100


# ============================================================================
# JSONL Record Parsing
# ============================================================================


class TestParseJsonlRecord:
    """Parsing individual JSONL lines into record dicts."""

    @pytest.fixture
    def logger(self):
        """Provide a test logger."""
        import logging
        return logging.getLogger("test")

    def test_valid_record(self, logger, sample_memories):
        """A well-formed JSONL line should parse correctly."""
        line = json.dumps(sample_memories[0])
        result = sync_mod.parse_jsonl_record(line, 1, logger)
        assert result is not None
        assert result["id"] == "2026-02-07-abc123"
        assert result["category"] == "decision"

    def test_empty_line_returns_none(self, logger):
        """Blank lines should be skipped, not error."""
        assert sync_mod.parse_jsonl_record("", 1, logger) is None
        assert sync_mod.parse_jsonl_record("   ", 2, logger) is None
        assert sync_mod.parse_jsonl_record("\n", 3, logger) is None

    def test_malformed_json_returns_none(self, logger):
        """Invalid JSON should log a warning and return None."""
        result = sync_mod.parse_jsonl_record("{not valid json", 1, logger)
        assert result is None

    def test_missing_id_returns_none(self, logger):
        """Record without 'id' field should be rejected."""
        record = {
            "category": "decision",
            "content": "Some content",
            "created_at": "2026-02-07T10:00:00+00:00",
        }
        result = sync_mod.parse_jsonl_record(json.dumps(record), 1, logger)
        assert result is None

    def test_missing_category_returns_none(self, logger):
        """Record without 'category' field should be rejected."""
        record = {
            "id": "test-id",
            "content": "Some content",
            "created_at": "2026-02-07T10:00:00+00:00",
        }
        result = sync_mod.parse_jsonl_record(json.dumps(record), 1, logger)
        assert result is None

    def test_missing_content_returns_none(self, logger):
        """Record without 'content' field should be rejected."""
        record = {
            "id": "test-id",
            "category": "decision",
            "created_at": "2026-02-07T10:00:00+00:00",
        }
        result = sync_mod.parse_jsonl_record(json.dumps(record), 1, logger)
        assert result is None

    def test_missing_created_at_returns_none(self, logger):
        """Record without 'created_at' field should be rejected."""
        record = {
            "id": "test-id",
            "category": "decision",
            "content": "Some content",
        }
        result = sync_mod.parse_jsonl_record(json.dumps(record), 1, logger)
        assert result is None

    def test_empty_required_field_returns_none(self, logger):
        """Empty string in a required field should be rejected."""
        record = {
            "id": "",
            "category": "decision",
            "content": "Some content",
            "created_at": "2026-02-07T10:00:00+00:00",
        }
        result = sync_mod.parse_jsonl_record(json.dumps(record), 1, logger)
        assert result is None


# ============================================================================
# Record to Tuple Conversion
# ============================================================================


class TestRecordToTuple:
    """Converting parsed records to PostgreSQL INSERT tuples."""

    def test_full_record(self, sample_memories):
        """Complete record should produce a correct tuple."""
        result = sync_mod.record_to_tuple(sample_memories[0])
        assert result == (
            "2026-02-07-abc123",     # id
            "test-session-1",         # session_id
            "-home-shawn-test-project",  # project
            "extraction",             # source
            "decision",               # category
            "Use PostgreSQL for memory queries.",  # content
            None,                     # summary
            "high",                   # confidence
            ["database", "architecture"],  # research_tags
            None,                     # zotero_key
            "Phase 2 planning",       # source_context
            "2026-02-07T10:00:00+00:00",  # created_at
            None,                     # deadline_at
        )

    def test_record_with_deadline(self, sample_memories):
        """Commitment record with deadline should include deadline_at."""
        result = sync_mod.record_to_tuple(sample_memories[1])
        assert result[0] == "2026-02-07-def456"
        assert result[2] == "-home-shawn-test-project"  # project
        assert result[3] == "manual"                     # source
        assert result[4] == "commitment"                 # category
        assert result[12] == "2026-02-13T15:00:00+11:00"  # deadline_at

    def test_missing_optional_fields_get_defaults(self):
        """Record with only required fields should get sensible defaults."""
        minimal = {
            "id": "test-minimal",
            "category": "progress",
            "content": "Something happened.",
            "created_at": "2026-02-08T00:00:00+00:00",
        }
        result = sync_mod.record_to_tuple(minimal)
        assert result[1] == ""           # session_id default
        assert result[2] is None         # project default
        assert result[3] == "extraction"  # source default
        assert result[6] is None         # summary default
        assert result[7] == "medium"      # confidence default
        assert result[8] == []            # research_tags default
        assert result[9] is None          # zotero_key default
        assert result[10] == ""           # source_context default
        assert result[12] is None         # deadline_at default

    def test_source_field_included(self, sample_memories):
        """Source field (extraction/manual) should be at index 3."""
        extraction_tuple = sync_mod.record_to_tuple(sample_memories[0])
        manual_tuple = sync_mod.record_to_tuple(sample_memories[1])
        assert extraction_tuple[3] == "extraction"
        assert manual_tuple[3] == "manual"

    def test_tuple_length_matches_fields(self, sample_memories):
        """Tuple length should match JSONL_FIELDS count (13)."""
        result = sync_mod.record_to_tuple(sample_memories[0])
        assert len(result) == len(sync_mod.JSONL_FIELDS)

    def test_tags_preserved_as_list(self, sample_memories):
        """research_tags should remain a list for PostgreSQL TEXT[] column."""
        result = sync_mod.record_to_tuple(sample_memories[0])
        assert isinstance(result[8], list)
        assert result[8] == ["database", "architecture"]

    def test_empty_tags_list(self):
        """Empty tags list should be preserved as empty list."""
        record = {
            "id": "test-no-tags",
            "category": "progress",
            "content": "No tags here.",
            "created_at": "2026-02-08T00:00:00+00:00",
            "research_tags": [],
        }
        result = sync_mod.record_to_tuple(record)
        assert result[8] == []


# ============================================================================
# Field Order Consistency
# ============================================================================


class TestFieldConsistency:
    """Ensure JSONL_FIELDS matches the tuple produced by record_to_tuple."""

    def test_field_list_contents(self):
        """JSONL_FIELDS should contain all expected fields."""
        expected = {
            "id", "session_id", "project", "source", "category", "content",
            "summary", "confidence", "research_tags", "zotero_key",
            "source_context", "created_at", "deadline_at",
        }
        assert set(sync_mod.JSONL_FIELDS) == expected

    def test_source_in_fields(self):
        """The 'source' field must be present in JSONL_FIELDS."""
        assert "source" in sync_mod.JSONL_FIELDS
