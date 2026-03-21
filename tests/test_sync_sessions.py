"""
Tests for sync-sessions-to-postgres.py — metadata discovery, extraction,
cursor management, and row conversion.

Tests pure functions only; does not require a running PostgreSQL instance.
"""

import importlib.util
import json
from pathlib import Path

import pytest

# Import the sync module (hyphenated filename requires importlib)
_sync_path = (
    Path(__file__).parent.parent / "scripts" / "sync-sessions-to-postgres.py"
)
_spec = importlib.util.spec_from_file_location("sync_sessions", _sync_path)
sync_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_mod)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_metadata() -> dict:
    """A realistic session.meta.json structure."""
    return {
        "schema_version": "1.1",
        "session": {
            "id": "abc12345-6789-0000-aaaa-bbbbccccdddd",
            "started_at": "2026-03-15T01:00:00Z",
            "ended_at": "2026-03-15T03:30:00Z",
            "duration_minutes": 150,
        },
        "project": {
            "name": "map-reader-llm",
            "directory": "/home/shawn/Code/map-reader-llm",
        },
        "model": {
            "provider": "anthropic",
            "model_id": "claude-opus-4-6",
            "access_method": "claude-code-cli",
        },
        "statistics": {
            "turns": 20,
            "human_messages": 20,
            "assistant_messages": 250,
            "thinking_blocks": 15,
            "tool_calls": {
                "total": 180,
                "by_type": {"Read": 30, "Bash": 80, "Edit": 50, "Write": 20},
            },
            "tokens": {
                "input": 15000,
                "output": 95000,
                "cache_read": 50000000,
                "cache_creation": 700000,
            },
            "estimated_cost_usd": 95.50,
        },
        "auto_generated": {
            "title": "Implement consensus detection pipeline",
            "purpose": "Build N=30 consensus sweep for mound detection",
            "tags": ["consensus", "detection", "pipeline"],
            "three_ps": {
                "prompt_summary": "Build the consensus sweep pipeline",
                "process_summary": "Iterative development with testing",
                "provenance_summary": "Part of Phase 3a replication",
            },
        },
        "three_ps": {
            "prompt_summary": "",
            "process_summary": "",
            "provenance_summary": "",
        },
        "archive": {
            "jsonl_path": "session.jsonl.gz",
            "jsonl_sha256": "deadbeef1234",
            "jsonl_bytes": 3000000,
            "archived_at": "2026-03-15T04:00:00Z",
            "capture_type": "session_end",
        },
    }


@pytest.fixture
def archive_tree(tmp_path, sample_metadata) -> Path:
    """Create a realistic archive directory tree with session.meta.json files."""
    # Session 1: map-reader-llm
    session1_dir = tmp_path / "map-reader-llm" / "2026-03-15T01-00_abc12345"
    session1_dir.mkdir(parents=True)
    (session1_dir / "session.meta.json").write_text(
        json.dumps(sample_metadata), encoding="utf-8"
    )

    # Session 2: personal-assistant (different project, later timestamp)
    meta2 = json.loads(json.dumps(sample_metadata))  # deep copy
    meta2["session"]["id"] = "def67890-1234-0000-aaaa-bbbbccccdddd"
    meta2["project"]["name"] = "personal-assistant"
    meta2["project"]["directory"] = "/home/shawn/personal-assistant"
    meta2["auto_generated"]["title"] = "Set up PostgreSQL sessions table"
    meta2["archive"]["archived_at"] = "2026-03-15T06:00:00Z"
    meta2["archive"]["capture_type"] = "pre_compact"

    session2_dir = tmp_path / "personal-assistant" / "2026-03-15T05-00_def67890"
    session2_dir.mkdir(parents=True)
    (session2_dir / "session.meta.json").write_text(
        json.dumps(meta2), encoding="utf-8"
    )

    return tmp_path


# ============================================================================
# Cursor Management
# ============================================================================


class TestSessionCursor:
    """Cursor file read/write for session sync."""

    def test_load_returns_epoch_when_no_file(self, tmp_path, monkeypatch):
        """Missing cursor file should return epoch timestamp."""
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", tmp_path / "missing.json")
        assert sync_mod.load_cursor() == "2000-01-01T00:00:00Z"

    def test_roundtrip(self, tmp_path, monkeypatch):
        """Save then load should return the same timestamp."""
        cursor_file = tmp_path / "sync-cursors.json"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        sync_mod.save_cursor("2026-03-15T04:00:00Z")
        assert sync_mod.load_cursor() == "2026-03-15T04:00:00Z"

    def test_preserves_other_keys(self, tmp_path, monkeypatch):
        """Saving session cursor should not clobber memory sync cursor."""
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(
            json.dumps({"postgres_sync_line": 15809}) + "\n"
        )
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        sync_mod.save_cursor("2026-03-15T04:00:00Z")
        data = json.loads(cursor_file.read_text())
        assert data["postgres_sync_line"] == 15809
        assert data["sessions_sync_timestamp"] == "2026-03-15T04:00:00Z"

    def test_handles_corrupt_json(self, tmp_path, monkeypatch):
        """Corrupt cursor file should return epoch rather than crash."""
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text("not valid json{{{")
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        assert sync_mod.load_cursor() == "2000-01-01T00:00:00Z"

    def test_handles_missing_key(self, tmp_path, monkeypatch):
        """Cursor file exists but doesn't have our key."""
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(json.dumps({"unrelated": 5}) + "\n")
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        assert sync_mod.load_cursor() == "2000-01-01T00:00:00Z"


# ============================================================================
# Archive Discovery
# ============================================================================


class TestFindSessionMetadata:
    """Discovering session.meta.json files in the archive tree."""

    def test_finds_all_sessions(self, archive_tree):
        """Should find all session.meta.json files in the tree."""
        results = sync_mod.find_session_metadata(archive_tree)
        assert len(results) == 2

    def test_returns_path_and_metadata(self, archive_tree):
        """Each result should be a (path, metadata_dict) tuple."""
        results = sync_mod.find_session_metadata(archive_tree)
        for meta_path, metadata in results:
            assert isinstance(meta_path, Path)
            assert meta_path.name == "session.meta.json"
            assert isinstance(metadata, dict)
            assert "session" in metadata

    def test_filters_by_since_timestamp(self, archive_tree):
        """Only sessions archived after the cursor should be returned."""
        # Session 1 archived at 04:00, session 2 at 06:00
        results = sync_mod.find_session_metadata(
            archive_tree, since="2026-03-15T05:00:00Z"
        )
        assert len(results) == 1
        _, metadata = results[0]
        assert metadata["project"]["name"] == "personal-assistant"

    def test_returns_empty_for_future_cursor(self, archive_tree):
        """Cursor beyond all archives should return empty list."""
        results = sync_mod.find_session_metadata(
            archive_tree, since="2099-01-01T00:00:00Z"
        )
        assert len(results) == 0

    def test_returns_empty_for_missing_root(self, tmp_path):
        """Non-existent archive root should return empty list."""
        results = sync_mod.find_session_metadata(tmp_path / "nonexistent")
        assert len(results) == 0

    def test_skips_malformed_json(self, tmp_path):
        """Corrupt meta files should be skipped, not crash."""
        session_dir = tmp_path / "project" / "2026-03-15T01-00_bad"
        session_dir.mkdir(parents=True)
        (session_dir / "session.meta.json").write_text("not valid json{{{")

        results = sync_mod.find_session_metadata(tmp_path)
        assert len(results) == 0

    def test_no_since_returns_all(self, archive_tree):
        """Without since filter, all sessions are returned."""
        results = sync_mod.find_session_metadata(archive_tree, since=None)
        assert len(results) == 2


# ============================================================================
# Metadata to Row Conversion
# ============================================================================


class TestMetadataToRow:
    """Converting session.meta.json to a flat database row."""

    def test_basic_fields(self, sample_metadata, tmp_path):
        """Core fields should be extracted correctly."""
        meta_path = tmp_path / "session.meta.json"
        row = sync_mod.metadata_to_row(meta_path, sample_metadata)

        assert row["id"] == "abc12345-6789-0000-aaaa-bbbbccccdddd"
        assert row["project"] == "map-reader-llm"
        assert row["project_directory"] == "/home/shawn/Code/map-reader-llm"
        assert row["title"] == "Implement consensus detection pipeline"
        assert row["purpose"] == "Build N=30 consensus sweep for mound detection"
        assert row["started_at"] == "2026-03-15T01:00:00Z"
        assert row["ended_at"] == "2026-03-15T03:30:00Z"
        assert row["duration_minutes"] == 150

    def test_model_fields(self, sample_metadata, tmp_path):
        """Model provider and ID should be extracted."""
        meta_path = tmp_path / "session.meta.json"
        row = sync_mod.metadata_to_row(meta_path, sample_metadata)

        assert row["model_provider"] == "anthropic"
        assert row["model_id"] == "claude-opus-4-6"

    def test_statistics(self, sample_metadata, tmp_path):
        """Statistics fields should be extracted from nested structure."""
        meta_path = tmp_path / "session.meta.json"
        row = sync_mod.metadata_to_row(meta_path, sample_metadata)

        assert row["turns"] == 20
        assert row["human_messages"] == 20
        assert row["assistant_messages"] == 250
        assert row["thinking_blocks"] == 15
        assert row["tool_calls"] == 180
        assert row["tokens_input"] == 15000
        assert row["tokens_output"] == 95000
        assert row["tokens_cache_read"] == 50000000
        assert row["tokens_cache_creation"] == 700000
        assert row["estimated_cost_usd"] == 95.50

    def test_tags(self, sample_metadata, tmp_path):
        """Tags should be extracted as a list."""
        meta_path = tmp_path / "session.meta.json"
        row = sync_mod.metadata_to_row(meta_path, sample_metadata)

        assert row["tags"] == ["consensus", "detection", "pipeline"]

    def test_three_ps_fallback_to_auto_generated(self, sample_metadata, tmp_path):
        """When top-level three_ps is empty, use auto_generated.three_ps."""
        meta_path = tmp_path / "session.meta.json"
        row = sync_mod.metadata_to_row(meta_path, sample_metadata)

        # Top-level three_ps is empty strings, so auto_generated should be used
        assert row["prompt_summary"] == "Build the consensus sweep pipeline"
        assert row["process_summary"] == "Iterative development with testing"
        assert row["provenance_summary"] == "Part of Phase 3a replication"

    def test_three_ps_prefers_top_level(self, sample_metadata, tmp_path):
        """Non-empty top-level three_ps should take precedence."""
        sample_metadata["three_ps"]["prompt_summary"] = "Manual enrichment"
        meta_path = tmp_path / "session.meta.json"
        row = sync_mod.metadata_to_row(meta_path, sample_metadata)

        assert row["prompt_summary"] == "Manual enrichment"

    def test_archive_fields(self, sample_metadata, tmp_path):
        """Archive path and capture type should be extracted."""
        meta_path = tmp_path / "session.meta.json"
        row = sync_mod.metadata_to_row(meta_path, sample_metadata)

        assert row["archive_path"] == str(tmp_path)
        assert row["capture_type"] == "session_end"

    def test_raw_metadata_is_valid_json(self, sample_metadata, tmp_path):
        """raw_metadata should be a valid JSON string of the full metadata."""
        meta_path = tmp_path / "session.meta.json"
        row = sync_mod.metadata_to_row(meta_path, sample_metadata)

        parsed = json.loads(row["raw_metadata"])
        assert parsed["schema_version"] == "1.1"
        assert parsed["session"]["id"] == sample_metadata["session"]["id"]

    def test_missing_optional_sections(self, tmp_path):
        """Metadata with minimal fields should not crash."""
        minimal = {
            "session": {"id": "minimal-session"},
            "project": {"name": "test"},
        }
        meta_path = tmp_path / "session.meta.json"
        row = sync_mod.metadata_to_row(meta_path, minimal)

        assert row["id"] == "minimal-session"
        assert row["project"] == "test"
        assert row["turns"] is None
        assert row["tokens_input"] is None
        assert row["tags"] == []
        assert row["capture_type"] is None

    def test_tool_calls_integer_fallback(self, tmp_path):
        """If tool_calls is an integer rather than a dict, handle gracefully."""
        metadata = {
            "session": {"id": "int-tools"},
            "project": {"name": "test"},
            "statistics": {"tool_calls": 42},
        }
        meta_path = tmp_path / "session.meta.json"
        row = sync_mod.metadata_to_row(meta_path, metadata)

        assert row["tool_calls"] == 42


# ============================================================================
# End-to-end Discovery + Conversion
# ============================================================================


class TestEndToEnd:
    """Integration tests: discover archives and convert to rows."""

    def test_full_pipeline(self, archive_tree):
        """Find sessions, convert to rows, verify all fields present."""
        sessions = sync_mod.find_session_metadata(archive_tree)
        assert len(sessions) >= 1

        for meta_path, metadata in sessions:
            row = sync_mod.metadata_to_row(meta_path, metadata)
            # Every row must have an id and project
            assert row["id"]
            assert row["project"]
            # raw_metadata must be parseable
            assert json.loads(row["raw_metadata"])

    def test_incremental_discovers_only_new(self, archive_tree):
        """After syncing, only newer sessions should be found."""
        # First sync: get all
        all_sessions = sync_mod.find_session_metadata(archive_tree)
        assert len(all_sessions) == 2

        # Simulate cursor at session 1's archive time
        new_sessions = sync_mod.find_session_metadata(
            archive_tree, since="2026-03-15T04:00:00Z"
        )
        assert len(new_sessions) == 1
        _, metadata = new_sessions[0]
        assert metadata["session"]["id"] == "def67890-1234-0000-aaaa-bbbbccccdddd"
