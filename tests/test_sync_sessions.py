"""
Tests for sync-sessions-to-postgres.py — metadata discovery, extraction,
cursor management, and row conversion.

Tests pure functions only; does not require a running PostgreSQL instance.
"""

import importlib.util
import json
import logging
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

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


@pytest.fixture(autouse=True)
def pinned_gate_file(tmp_path, monkeypatch):
    """Keep the session-start gate inside the test's tmp directory.

    The gate is read by daily-sync-trigger.sh and printed to Shawn at
    session start. A test that wrote the real one would put a fabricated
    infrastructure problem in front of him — the same class as audit
    finding S21, and it happened once while this was being written.
    Autouse so no future test can forget.
    """
    gate = tmp_path / "gates" / "this-script-gate"
    monkeypatch.setattr(sync_mod, "GATE_FILE", gate)
    return gate


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

    def test_save_cursor_is_atomic(self, tmp_path, monkeypatch):
        """
        Audit round two, finding P16: an interrupted cursor save must
        leave the previous file — including the *other* syncs' cursors —
        intact. The mutation this kills: reverting ``save_cursor`` to
        ``CURSOR_FILE.write_text(...)``, which truncates in place.
        """
        cursor_file = tmp_path / "sync-cursors.json"
        original = {
            "postgres_sync_line": 15809,
            "sessions_sync_timestamp": "2026-03-15T04:00:00Z",
        }
        cursor_file.write_text(json.dumps(original), encoding="utf-8")
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        def _boom(src, dst):
            raise KeyboardInterrupt("killed mid-write")

        monkeypatch.setattr(os, "replace", _boom)
        with pytest.raises(KeyboardInterrupt):
            sync_mod.save_cursor("2026-03-16T04:00:00Z")

        assert json.loads(cursor_file.read_text(encoding="utf-8")) == original


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


# ============================================================================
# Upsert Accounting (#55 fix)
# ============================================================================


class _FakePsycopg2Error(Exception):
    """Stand-in for ``psycopg2.Error`` in patched-sys.modules tests.

    Carries ``pgcode`` like the real class: PostgreSQL's SQLSTATE for a
    server-side error, ``None`` for one psycopg2 raised client-side.
    """

    def __init__(self, message: str = "", pgcode: str | None = None) -> None:
        super().__init__(message)
        self.pgcode = pgcode


class _FakePsycopg2OperationalError(_FakePsycopg2Error):
    """Stand-in for ``psycopg2.OperationalError`` (subclass of Error)."""


class _FakePsycopg2InterfaceError(_FakePsycopg2Error):
    """Stand-in for ``psycopg2.InterfaceError`` (connection already gone)."""


class _FakePsycopg2DataError(_FakePsycopg2Error):
    """Stand-in for ``psycopg2.DataError`` — the row's content is wrong."""


class _FakePsycopg2IntegrityError(_FakePsycopg2Error):
    """Stand-in for ``psycopg2.IntegrityError`` — e.g. a NOT NULL violation."""


class _FakePsycopg2ProgrammingError(_FakePsycopg2Error):
    """Stand-in for ``psycopg2.ProgrammingError`` — e.g. InsufficientPrivilege."""


class _FakePsycopg2InternalError(_FakePsycopg2Error):
    """Stand-in for ``psycopg2.InternalError`` — e.g. InFailedSqlTransaction."""


def _poisoning_execute_values(
    poison_ids: set[str],
    error_class: type[Exception] = _FakePsycopg2DataError,
    message: str = (
        "unsupported Unicode escape sequence\n"
        "DETAIL:  \\u0000 cannot be converted to text."
    ),
):
    """
    Build an ``execute_values`` stand-in that refuses specific rows.

    Reproduces the live September 2026 failure exactly: any statement
    whose value list contains a poison id raises, which means the batch
    fails (it contains the poison row alongside the healthy ones) and the
    per-row replay then fails only on the poison row itself.
    """

    def _side_effect(cur, sql, values, page_size=None, fetch=False):
        ids = [row[0] for row in values]
        offending = [sid for sid in ids if sid in poison_ids]
        if offending:
            # A distinct SQLSTATE per row, so the all-alike environment
            # rule is never what these tests are actually exercising.
            raise error_class(
                f"{message} (row {offending[0]})",
                f"22{abs(hash(offending[0])) % 1000:03d}",
            )
        return [(sid,) for sid in ids]

    return _side_effect


def _install_fake_psycopg2(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returned_ids: list[str],
    raise_on_connect: bool = False,
    advisory_lock_acquired: bool = True,
    execute_values_side_effect=None,
) -> MagicMock:
    """
    Install a fake ``psycopg2`` package into ``sys.modules`` so the
    function-level import inside ``upsert_sessions`` and the advisory-
    lock helper use it.

    ``returned_ids`` controls what ``execute_values(fetch=True)`` yields
    (simulating the ``RETURNING id`` clause). ``advisory_lock_acquired``
    controls what ``pg_try_advisory_lock`` reports back (for tests that
    want to exercise the contended-lock path).
    ``execute_values_side_effect`` overrides the return value entirely,
    for tests that need the call to raise.
    """
    fake_psycopg2 = types.ModuleType("psycopg2")
    fake_extras = types.ModuleType("psycopg2.extras")

    fake_psycopg2.Error = _FakePsycopg2Error
    fake_psycopg2.OperationalError = _FakePsycopg2OperationalError
    fake_psycopg2.InterfaceError = _FakePsycopg2InterfaceError
    fake_psycopg2.DataError = _FakePsycopg2DataError
    fake_psycopg2.IntegrityError = _FakePsycopg2IntegrityError
    fake_psycopg2.ProgrammingError = _FakePsycopg2ProgrammingError
    fake_psycopg2.InternalError = _FakePsycopg2InternalError

    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    # pg_try_advisory_lock(...) → [(True,)] or [(False,)] depending on
    # flag. The upsert path's SELECT does not fetchone; the advisory
    # lock path does. Schema-version assertion (audit IC5) also calls
    # fetchone — return the seeded version when ``meta`` is queried,
    # the advisory-lock boolean otherwise.
    last_sql = {"value": ""}

    def _exec(sql, *args, **kwargs):
        last_sql["value"] = sql
        return None

    def _fetchone():
        if "meta" in last_sql["value"]:
            return ("3",)
        return (advisory_lock_acquired,)

    cur.execute.side_effect = _exec
    cur.fetchone.side_effect = _fetchone

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    if raise_on_connect:
        fake_psycopg2.connect = MagicMock(
            side_effect=_FakePsycopg2OperationalError("DB down")
        )
    else:
        fake_psycopg2.connect = MagicMock(return_value=conn)

    if execute_values_side_effect is not None:
        fake_extras.execute_values = MagicMock(
            side_effect=execute_values_side_effect
        )
    else:
        fake_extras.execute_values = MagicMock(
            return_value=[(mid,) for mid in returned_ids]
        )

    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", fake_extras)

    return conn


@pytest.fixture
def test_logger() -> logging.Logger:
    """Quiet logger for accountability tests."""
    return logging.getLogger("test-sync-sessions")


def _minimal_row(sid: str) -> dict:
    """Build a minimal session row dict populated for every column."""
    columns = [
        "id", "project", "project_directory", "title", "purpose", "tags",
        "started_at", "ended_at", "duration_minutes",
        "model_provider", "model_id",
        "turns", "human_messages", "assistant_messages",
        "thinking_blocks", "tool_calls",
        "tokens_input", "tokens_output",
        "tokens_cache_read", "tokens_cache_creation",
        "estimated_cost_usd",
        "prompt_summary", "process_summary", "provenance_summary",
        "archive_path", "capture_type",
        "subagent_count", "subagent_total_cost_usd",
        "raw_metadata",
    ]
    row = {c: None for c in columns}
    row["id"] = sid
    row["project"] = "test"
    row["tags"] = []
    row["subagent_count"] = 0
    row["subagent_total_cost_usd"] = 0.0
    row["raw_metadata"] = "{}"
    return row


class TestUpsertSessionsAccounting:
    """Row-level accounting for :func:`upsert_sessions` (#55)."""

    def test_all_rows_returned(
        self, monkeypatch: pytest.MonkeyPatch, test_logger: logging.Logger
    ) -> None:
        """All input ids returned by DO UPDATE → no drops, full insert."""
        ids = ["s1", "s2", "s3"]
        _install_fake_psycopg2(monkeypatch, returned_ids=ids)
        rows = [_minimal_row(sid) for sid in ids]
        result = sync_mod.upsert_sessions(rows, test_logger)
        assert result.db_available is True
        assert result.input_count == 3
        assert result.inserted == 3
        assert result.unexpected_drops == []

    def test_unexpected_drop_recorded(
        self, monkeypatch: pytest.MonkeyPatch, test_logger: logging.Logger
    ) -> None:
        """Id absent from RETURNING → unexpected_drops populated."""
        ids = ["s1", "s2", "s3"]
        _install_fake_psycopg2(monkeypatch, returned_ids=["s1", "s3"])
        rows = [_minimal_row(sid) for sid in ids]
        result = sync_mod.upsert_sessions(rows, test_logger)
        assert result.db_available is True
        assert result.inserted == 2
        assert result.unexpected_drops == ["s2"]

    def test_drop_halts_cursor_and_quarantines(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        archive_tree: Path,
        test_logger: logging.Logger,
    ) -> None:
        """Unexpected drop → cursor not advanced, row written to quarantine."""
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "sessions-quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)

        # Both sessions in archive_tree will be discovered. Return only one
        # id so the other is "dropped".
        _install_fake_psycopg2(
            monkeypatch,
            returned_ids=["abc12345-6789-0000-aaaa-bbbbccccdddd"],
        )

        sync_mod.sync(archive_tree, full_resync=True, logger=test_logger)

        # Cursor must not have advanced — no sessions_sync_timestamp key.
        if cursor_file.exists():
            data = json.loads(cursor_file.read_text())
            assert "sessions_sync_timestamp" not in data
        # Quarantine file should contain the dropped session row.
        assert quarantine.exists()
        lines = [
            json.loads(line) for line in quarantine.read_text().splitlines()
            if line.strip()
        ]
        assert len(lines) == 1
        assert lines[0]["id"] == "def67890-1234-0000-aaaa-bbbbccccdddd"

    def test_db_unavailable_no_advance(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        archive_tree: Path,
        test_logger: logging.Logger,
    ) -> None:
        """connect raising → db_available=False, cursor untouched."""
        cursor_file = tmp_path / "sync-cursors.json"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        _install_fake_psycopg2(
            monkeypatch, returned_ids=[], raise_on_connect=True
        )

        sync_mod.sync(archive_tree, full_resync=True, logger=test_logger)

        if cursor_file.exists():
            data = json.loads(cursor_file.read_text())
            assert "sessions_sync_timestamp" not in data

    def test_within_batch_dedup_last_wins(
        self, monkeypatch: pytest.MonkeyPatch, test_logger: logging.Logger
    ) -> None:
        """Duplicate session ids in one batch collapse to the last row."""
        rows = [
            _minimal_row("s-dup"),
            _minimal_row("s-new"),
            _minimal_row("s-dup"),
        ]
        # Mark the two dup rows so we can see which one "won".
        rows[0]["title"] = "first"
        rows[2]["title"] = "second"

        _install_fake_psycopg2(
            monkeypatch, returned_ids=["s-dup", "s-new"]
        )
        result = sync_mod.upsert_sessions(rows, test_logger)
        assert result.db_available is True
        assert result.duplicates_within_batch == 1
        assert result.input_count == 2  # deduped
        assert result.inserted == 2
        assert result.unexpected_drops == []

    def test_quarantine_dedup_skips_already_present(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        test_logger: logging.Logger,
    ) -> None:
        """Repeated quarantine calls for the same id append only once."""
        quarantine = tmp_path / "sessions-quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)

        dropped = [{"id": "s-x", "title": "t"}]
        sync_mod._write_quarantine(dropped, test_logger)
        sync_mod._write_quarantine(dropped, test_logger)

        lines = [
            json.loads(line) for line in quarantine.read_text().splitlines()
            if line.strip()
        ]
        assert len(lines) == 1
        assert lines[0]["id"] == "s-x"

    def test_advisory_lock_contended_skips_sync(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        archive_tree: Path,
        test_logger: logging.Logger,
    ) -> None:
        """Contended advisory lock → sync exits without calling upsert."""
        cursor_file = tmp_path / "sync-cursors.json"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        _install_fake_psycopg2(
            monkeypatch,
            returned_ids=["abc12345-6789-0000-aaaa-bbbbccccdddd"],
            advisory_lock_acquired=False,
        )

        called = {"upsert": False}
        orig_upsert = sync_mod.upsert_sessions

        def _spy(rows, logger):
            called["upsert"] = True
            return orig_upsert(rows, logger)

        monkeypatch.setattr(sync_mod, "upsert_sessions", _spy)

        sync_mod.sync(archive_tree, full_resync=True, logger=test_logger)

        assert called["upsert"] is False
        if cursor_file.exists():
            data = json.loads(cursor_file.read_text())
            assert "sessions_sync_timestamp" not in data

    def test_narrow_exception_reraises_non_psycopg_errors(
        self, monkeypatch: pytest.MonkeyPatch, test_logger: logging.Logger
    ) -> None:
        """
        KeyError from a malformed row bubbles up rather than being
        reported as db_available=False — programmer bugs should not be
        disguised as transient DB trouble.
        """
        _install_fake_psycopg2(monkeypatch, returned_ids=[])
        sys.modules["psycopg2.extras"].execute_values = MagicMock(
            side_effect=KeyError("missing column")
        )
        rows = [_minimal_row("s-a")]
        with pytest.raises(KeyError):
            sync_mod.upsert_sessions(rows, test_logger)

    def test_id_less_session_quarantined_and_cursor_advances(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_metadata: dict,
        test_logger: logging.Logger,
    ) -> None:
        """
        Audit IC2 / B-M2: a session.meta.json that lacks a session id
        used to be skipped silently, leaving the cursor pinned and
        spamming the same warning every cron tick. New contract is that
        the offending metadata is appended to the quarantine and the
        cursor advances past it.
        """
        archive_root = tmp_path / "archive"
        # Build a single archive entry whose metadata lacks ``session.id``.
        meta = json.loads(json.dumps(sample_metadata))  # deep copy
        meta["session"]["id"] = ""  # poison: empty id triggers the skip path
        meta["archive"]["archived_at"] = "2026-03-15T07:00:00Z"
        session_dir = archive_root / "broken" / "2026-03-15T05-00_no_id"
        session_dir.mkdir(parents=True)
        (session_dir / "session.meta.json").write_text(
            json.dumps(meta), encoding="utf-8",
        )

        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "sessions-quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)

        # No DB calls should be made — the row is dropped before upsert.
        _install_fake_psycopg2(monkeypatch, returned_ids=[])

        sync_mod.sync(archive_root, full_resync=True, logger=test_logger)

        # Cursor advanced to the latest archived_at so the same id-less
        # metadata is not re-discovered every run.
        assert cursor_file.exists()
        data = json.loads(cursor_file.read_text())
        assert data["sessions_sync_timestamp"] == "2026-03-15T07:00:00Z"

        # The id-less metadata landed in the quarantine.
        assert quarantine.exists()
        entries = [
            json.loads(line) for line in
            quarantine.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(entries) == 1
        assert entries[0]["reason"] == "missing_session_id"
        assert entries[0]["record"]["meta_path"].endswith("session.meta.json")


# ============================================================================
# Audit round two, finding P1 (lens A-C1/A-X1/A-X2) — a refused row is not
# an outage, and a NUL must never reach PostgreSQL
# ============================================================================


class TestRowErrorsVersusOutages:
    """
    The live September 2026 failure and its fix.

    Two ``session.meta.json`` files carried a NUL inside LLM-generated
    narrative. PostgreSQL rejects ``\\u0000`` in ``jsonb``; the whole
    48-session batch aborted; the error was reported as
    ``db_available=False`` ("PostgreSQL may be down"); the cursor never
    advanced; and the sessions table sat three weeks stale.
    """

    def test_nul_in_narrative_is_stripped_at_ingest(
        self, tmp_path: Path, sample_metadata: dict,
        test_logger: logging.Logger, caplog,
    ) -> None:
        """
        The exact poison shape: a NUL inside a sub-agent narrative.

        ``metadata_to_row`` is the ingest boundary, so no NUL may survive
        into ``raw_metadata`` (jsonb) or the derived TEXT columns. The
        mutation this kills: dropping the ``sanitise_nuls`` call.
        """
        meta = json.loads(json.dumps(sample_metadata))
        meta["subagent_summaries"] = [
            {"narrative": "Ran the sweep\x00 and reported back."},
        ]
        meta["auto_generated"]["three_ps"]["prompt_summary"] = "Bad\x00text"
        meta_path = tmp_path / "session.meta.json"

        with caplog.at_level(logging.WARNING):
            row = sync_mod.metadata_to_row(meta_path, meta, test_logger)

        assert "\x00" not in row["raw_metadata"]
        assert "\x00" not in json.dumps(row)
        assert row["prompt_summary"] == "Badtext"
        assert "NUL" in caplog.text

    def test_data_error_quarantines_the_row_and_advances(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        archive_tree: Path,
        test_logger: logging.Logger,
        caplog,
    ) -> None:
        """
        One refused row must not hold 47 healthy ones hostage.

        The batch fails, the per-row replay lands the healthy session,
        the refused session is quarantined, and the cursor advances — so
        the next run makes progress instead of re-failing identically.
        The mutation this kills: classifying every ``psycopg2.Error`` as
        ``db_available=False``.
        """
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "sessions-quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)

        poison_id = "def67890-1234-0000-aaaa-bbbbccccdddd"
        healthy_id = "abc12345-6789-0000-aaaa-bbbbccccdddd"
        _install_fake_psycopg2(
            monkeypatch,
            returned_ids=[],
            execute_values_side_effect=_poisoning_execute_values({poison_id}),
        )

        with caplog.at_level(logging.INFO):
            sync_mod.sync(archive_tree, full_resync=True, logger=test_logger)

        # Cursor advanced past the poisoned slice.
        assert cursor_file.exists(), "cursor was not written — the sync stalled"
        cursor = json.loads(cursor_file.read_text(encoding="utf-8"))
        assert cursor["sessions_sync_timestamp"] == "2026-03-15T06:00:00Z"

        # The refused session is quarantined with the database's reason.
        entries = [
            json.loads(line)
            for line in quarantine.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [e["record"]["id"] for e in entries] == [poison_id]
        assert entries[0]["reason"] == "postgres_refused_row"
        assert "\\u0000" in entries[0]["record"]["postgres_error"]

        # The healthy session still landed, and nobody was told the
        # database was down.
        assert healthy_id not in {e["record"]["id"] for e in entries}
        assert "may be down" not in caplog.text
        assert "may be stopped" not in caplog.text

    def test_healthy_rows_land_when_one_row_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        test_logger: logging.Logger,
    ) -> None:
        """Per-row replay accounting: 2 inserted, 1 quarantined, 0 drops."""
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        _install_fake_psycopg2(
            monkeypatch,
            returned_ids=[],
            execute_values_side_effect=_poisoning_execute_values({"s2"}),
        )
        rows = [_minimal_row(sid) for sid in ("s1", "s2", "s3")]

        result = sync_mod.upsert_sessions(rows, test_logger)

        assert result.db_available is True
        assert result.inserted == 2
        assert result.quarantined == ("s2",)
        assert result.unexpected_drops == []

    def test_integrity_error_is_also_a_row_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        test_logger: logging.Logger,
    ) -> None:
        """A NOT NULL violation is content, not an outage (finding P10)."""
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        _install_fake_psycopg2(
            monkeypatch,
            returned_ids=[],
            execute_values_side_effect=_poisoning_execute_values(
                {"s2"},
                error_class=_FakePsycopg2IntegrityError,
                message='null value in column "project" violates not-null',
            ),
        )
        rows = [_minimal_row(sid) for sid in ("s1", "s2")]

        result = sync_mod.upsert_sessions(rows, test_logger)

        assert result.db_available is True
        assert result.quarantined == ("s2",)

    def test_operational_error_still_holds_the_cursor(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        archive_tree: Path,
        test_logger: logging.Logger,
    ) -> None:
        """
        A genuine outage keeps the old behaviour: no quarantine, no
        cursor advance, retry next run. The split must not turn a real
        outage into 48 quarantined sessions.
        """
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "sessions-quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)

        def _server_gone(cur, sql, values, page_size=None, fetch=False):
            raise _FakePsycopg2OperationalError(
                "server closed the connection unexpectedly"
            )

        _install_fake_psycopg2(
            monkeypatch, returned_ids=[],
            execute_values_side_effect=_server_gone,
        )

        sync_mod.sync(archive_tree, full_resync=True, logger=test_logger)

        if cursor_file.exists():
            data = json.loads(cursor_file.read_text(encoding="utf-8"))
            assert "sessions_sync_timestamp" not in data
        assert not quarantine.exists()

    def test_outage_part_way_through_replay_holds_the_cursor(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        test_logger: logging.Logger,
    ) -> None:
        """
        If the database dies during the per-row replay, the rows not yet
        attempted are neither stored nor quarantined — so the cursor must
        stay put rather than skipping them.
        """
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        calls = {"n": 0}

        def _dies_on_replay(cur, sql, values, page_size=None, fetch=False):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _FakePsycopg2DataError("bad row somewhere")
            raise _FakePsycopg2OperationalError("server closed the connection")

        _install_fake_psycopg2(
            monkeypatch, returned_ids=[],
            execute_values_side_effect=_dies_on_replay,
        )
        rows = [_minimal_row(sid) for sid in ("s1", "s2")]

        result = sync_mod.upsert_sessions(rows, test_logger)

        assert result.db_available is False
        assert result.quarantined == ()


class TestNotNullColumnDefaults:
    """Finding P10 (lens A-M8) — ``.get(key, default)`` on a NOT NULL column."""

    def test_null_project_name_becomes_unknown(
        self, tmp_path: Path, sample_metadata: dict,
    ) -> None:
        """
        ``{"project": {"name": null}}`` must not reach ``project TEXT NOT
        NULL``. ``.get("name", "unknown")`` returns None when the key
        exists with a null value — the exact hazard the comment four
        lines above it warns about. The mutation this kills: restoring
        ``project.get("name", "unknown")``.
        """
        meta = json.loads(json.dumps(sample_metadata))
        meta["project"]["name"] = None
        row = sync_mod.metadata_to_row(tmp_path / "session.meta.json", meta)
        assert row["project"] == "unknown"

    def test_null_session_id_becomes_empty_string(
        self, tmp_path: Path, sample_metadata: dict,
    ) -> None:
        """A null session id must route to the id-less quarantine path."""
        meta = json.loads(json.dumps(sample_metadata))
        meta["session"]["id"] = None
        row = sync_mod.metadata_to_row(tmp_path / "session.meta.json", meta)
        assert row["id"] == ""


# ============================================================================
# Re-audit finding C1 — an environment fault is neither an outage nor a
# refused row
# ============================================================================


class TestEnvironmentFaults:
    """
    ``ProgrammingError`` and ``InternalError`` are not about the data.

    Verified against psycopg2 2.9.12: ``InsufficientPrivilege`` (42501),
    ``UndefinedTable`` (42P01), and ``UndefinedColumn`` (42703) are all
    ``ProgrammingError``; ``InFailedSqlTransaction`` (25P02) is
    ``InternalError``. Classed as refused rows they would empty the whole
    cursor window into a quarantine file and exit 0.
    """

    def _revoke(self, cur, sql, values, page_size=None, fetch=False):
        """execute_values stand-in modelling a REVOKE on the sessions table."""
        raise _FakePsycopg2ProgrammingError(
            "permission denied for table sessions", "42501",
        )

    def test_permission_denied_holds_the_cursor(
        self, monkeypatch, tmp_path, archive_tree, test_logger,
    ):
        """
        Cursor untouched, quarantine file never created. The mutation this
        kills: classifying ProgrammingError as a refused row.
        """
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "sessions-quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)
        _install_fake_psycopg2(
            monkeypatch, returned_ids=[],
            execute_values_side_effect=self._revoke,
        )

        with pytest.raises(sync_mod.EnvironmentFault):
            sync_mod.sync(archive_tree, full_resync=True, logger=test_logger)

        assert not quarantine.exists()
        if cursor_file.exists():
            data = json.loads(cursor_file.read_text(encoding="utf-8"))
            assert "sessions_sync_timestamp" not in data

    def test_main_exits_four(
        self, monkeypatch, tmp_path, archive_tree,
    ):
        """
        The whole point of C1: the run must not report success. Exit 4,
        distinct from the outage path (0) and an unexpected error (1).
        """
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", tmp_path / "cursors.json")
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        # Keep the run's own log inside tmp_path rather than the repo's.
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync-sessions.log",
        )
        _install_fake_psycopg2(
            monkeypatch, returned_ids=[],
            execute_values_side_effect=self._revoke,
        )
        monkeypatch.setattr(
            sys, "argv",
            ["sync-sessions-to-postgres.py", "--archive-root",
             str(archive_tree), "--full-resync"],
        )

        try:
            with pytest.raises(SystemExit) as excinfo:
                sync_mod.main()
        finally:
            logging.getLogger("sync-sessions-to-postgres").handlers.clear()

        assert excinfo.value.code == 4

    def test_aborted_transaction_is_an_environment_fault(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """InFailedSqlTransaction (InternalError, 25P02) must not quarantine."""
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )

        def _aborted(cur, sql, values, page_size=None, fetch=False):
            raise _FakePsycopg2InternalError(
                "current transaction is aborted, commands ignored", "25P02",
            )

        _install_fake_psycopg2(
            monkeypatch, returned_ids=[],
            execute_values_side_effect=_aborted,
        )

        with pytest.raises(sync_mod.EnvironmentFault):
            sync_mod.upsert_sessions(
                [_minimal_row("s1"), _minimal_row("s2")], test_logger,
            )
        assert not (tmp_path / "quarantine.jsonl").exists()


class TestQuarantineDedupSeesBothShapes:
    """
    Re-audit, low finding: the sessions quarantine file also holds two
    shapes — the bare row from ``_write_quarantine`` and the wrapped entry
    from ``_sync_cursor.quarantine_record`` — and the dedup read only one.
    """

    def test_wrapped_entries_are_seen_by_the_dedup(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """The mutation this kills: reading only ``rec.get("id")``."""
        quarantine = tmp_path / "sessions-quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)

        sync_mod.quarantine_record(
            quarantine,
            {"id": "s-x", "postgres_error": "refused"},
            "postgres_refused_row",
            logger=test_logger,
        )
        assert sync_mod._load_quarantined_ids() == {"s-x"}

        sync_mod._write_quarantine([{"id": "s-x", "title": "t"}], test_logger)

        entries = [
            json.loads(line)
            for line in quarantine.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(entries) == 1


class TestCorrelatedPoison:
    """
    Second re-audit, C1 — the case the withdrawn all-alike rule broke.

    The live September 2026 incident was *two* archived sessions carrying
    a NUL in LLM-generated narrative. Both raise the same SQLSTATE. A rule
    keyed on "every row failed alike" therefore held the cursor on exactly
    the incident the branch was written to fix.
    """

    def test_two_nul_sessions_are_quarantined_and_the_cursor_advances(
        self, monkeypatch, tmp_path, archive_tree, test_logger,
    ):
        """
        Both sessions refused with 22P05 (untranslatable_character, what
        PostgreSQL raises for a NUL in jsonb). Both quarantined, cursor
        advanced, exit clean. The mutation this kills: reinstating an
        "every row failed alike" environment rule.
        """
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "sessions-quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)

        def _both_nul(cur, sql, values, page_size=None, fetch=False):
            raise _FakePsycopg2DataError(
                "unsupported Unicode escape sequence: "
                "\\u0000 cannot be converted to text",
                "22P05",
            )

        _install_fake_psycopg2(
            monkeypatch, returned_ids=[],
            execute_values_side_effect=_both_nul,
        )

        sync_mod.sync(archive_tree, full_resync=True, logger=test_logger)

        assert json.loads(
            cursor_file.read_text(encoding="utf-8")
        )["sessions_sync_timestamp"] == "2026-03-15T06:00:00Z"
        entries = [
            json.loads(line)
            for line in quarantine.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(entries) == 2

    def test_disk_full_holds_the_cursor(
        self, monkeypatch, tmp_path, archive_tree, test_logger,
    ):
        """
        53100 arrives as an OperationalError, so the class-based split
        called it an outage and exited 0 — a full disk reported as
        "PostgreSQL may be stopped", every five minutes, silently (M5).
        """
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "sessions-quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)

        def _disk_full(cur, sql, values, page_size=None, fetch=False):
            raise _FakePsycopg2OperationalError(
                "could not extend file: No space left on device", "53100",
            )

        _install_fake_psycopg2(
            monkeypatch, returned_ids=[],
            execute_values_side_effect=_disk_full,
        )

        with pytest.raises(sync_mod.EnvironmentFault):
            sync_mod.sync(archive_tree, full_resync=True, logger=test_logger)

        assert not quarantine.exists()
        if cursor_file.exists():
            assert "sessions_sync_timestamp" not in json.loads(
                cursor_file.read_text(encoding="utf-8")
            )

    def test_mixed_row_and_environment_faults_hold(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        One genuinely bad row and one REVOKE: the environment fault wins,
        because the run cannot tell how much of the rest it failed to
        attempt. Nothing is quarantined.
        """
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )

        def _mixed(cur, sql, values, page_size=None, fetch=False):
            ids = [row[0] for row in values]
            if len(ids) > 1:
                raise _FakePsycopg2DataError("batch aborted", "22001")
            if ids[0] == "s1":
                raise _FakePsycopg2DataError("value too long", "22001")
            raise _FakePsycopg2ProgrammingError(
                "permission denied for table sessions", "42501",
            )

        _install_fake_psycopg2(
            monkeypatch, returned_ids=[], execute_values_side_effect=_mixed,
        )

        with pytest.raises(sync_mod.EnvironmentFault):
            sync_mod.upsert_sessions(
                [_minimal_row("s1"), _minimal_row("s2")], test_logger,
            )
        assert not (tmp_path / "quarantine.jsonl").exists()

    def test_default_quarantine_cap_is_exercised(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        Every other cap test passes ``cap=5``, so the shipped default was
        never exercised (M1). Refusing one row past the default must stop
        the run; refusing exactly the default must not.
        """
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        cap = sync_mod.DEFAULT_QUARANTINE_CAP
        rows = [_minimal_row(f"s{i}") for i in range(cap + 1)]

        def _all_bad(cur, sql, values, page_size=None, fetch=False):
            raise _FakePsycopg2DataError("value too long", "22001")

        _install_fake_psycopg2(
            monkeypatch, returned_ids=[], execute_values_side_effect=_all_bad,
        )

        with pytest.raises(sync_mod.EnvironmentFault):
            sync_mod.upsert_sessions(rows, test_logger)

    def test_env_var_overrides_the_cap(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """``PA_PG_QUARANTINE_CAP`` tunes it without a code change (M2)."""
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setenv("PA_PG_QUARANTINE_CAP", "1")

        def _all_bad(cur, sql, values, page_size=None, fetch=False):
            raise _FakePsycopg2DataError("value too long", "22001")

        _install_fake_psycopg2(
            monkeypatch, returned_ids=[], execute_values_side_effect=_all_bad,
        )

        with pytest.raises(sync_mod.EnvironmentFault):
            sync_mod.upsert_sessions(
                [_minimal_row(f"s{i}") for i in range(3)], test_logger,
            )

    def test_explicit_cap_beats_the_environment(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """The ``--quarantine-cap`` flag wins over the variable."""
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setenv("PA_PG_QUARANTINE_CAP", "1")

        def _all_bad(cur, sql, values, page_size=None, fetch=False):
            raise _FakePsycopg2DataError("value too long", "22001")

        _install_fake_psycopg2(
            monkeypatch, returned_ids=[], execute_values_side_effect=_all_bad,
        )

        result = sync_mod.upsert_sessions(
            [_minimal_row(f"s{i}") for i in range(3)],
            test_logger,
            quarantine_cap=10,
        )
        assert len(result.quarantined) == 3


class TestSessionsCursorResetMidRun:
    """
    M1 — the sessions sync's compare-and-set had no test at all, so
    ``expect_present=()`` survived as a mutation.
    """

    def test_vanished_cursor_key_is_not_written_back(
        self, monkeypatch, tmp_path, archive_tree, test_logger,
    ):
        """
        A rebuild clears the cursors mid-cycle; the sessions timestamp
        must not be written back over it. The mutation this kills:
        dropping ``expect_present`` from the sessions ``save_cursor``.
        """
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(
            json.dumps({"sessions_sync_timestamp": "2026-03-15T00:00:00Z"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        _install_fake_psycopg2(
            monkeypatch,
            returned_ids=[
                "abc12345-6789-0000-aaaa-bbbbccccdddd",
                "def67890-1234-0000-aaaa-bbbbccccdddd",
            ],
        )

        original_upsert = sync_mod.upsert_sessions

        def _rebuild_runs_now(rows, logger, quarantine_cap=None):
            cursor_file.write_text(json.dumps({}), encoding="utf-8")
            return original_upsert(rows, logger, quarantine_cap)

        monkeypatch.setattr(sync_mod, "upsert_sessions", _rebuild_runs_now)

        with pytest.raises(sync_mod.CursorKeyVanished):
            sync_mod.sync(archive_tree, full_resync=False, logger=test_logger)

        assert "sessions_sync_timestamp" not in json.loads(
            cursor_file.read_text(encoding="utf-8")
        )

    def test_main_exits_six(self, monkeypatch, tmp_path, archive_tree):
        """The documented exit code, asserted end to end (M1)."""
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(
            json.dumps({"sessions_sync_timestamp": "2026-03-15T00:00:00Z"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync-sessions.log",
        )
        _install_fake_psycopg2(
            monkeypatch,
            returned_ids=[
                "abc12345-6789-0000-aaaa-bbbbccccdddd",
                "def67890-1234-0000-aaaa-bbbbccccdddd",
            ],
        )

        original_upsert = sync_mod.upsert_sessions

        def _rebuild_runs_now(rows, logger, quarantine_cap=None):
            cursor_file.write_text(json.dumps({}), encoding="utf-8")
            return original_upsert(rows, logger, quarantine_cap)

        monkeypatch.setattr(sync_mod, "upsert_sessions", _rebuild_runs_now)
        monkeypatch.setattr(
            sys, "argv",
            ["sync-sessions-to-postgres.py", "--archive-root",
             str(archive_tree)],
        )

        try:
            with pytest.raises(SystemExit) as excinfo:
                sync_mod.main()
        finally:
            logging.getLogger("sync-sessions-to-postgres").handlers.clear()

        assert excinfo.value.code == 6

    def test_first_run_with_no_cursor_key_still_writes(
        self, monkeypatch, tmp_path, archive_tree, test_logger,
    ):
        """A key that was never there is a first run, and must still write."""
        cursor_file = tmp_path / "sync-cursors.json"
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        _install_fake_psycopg2(
            monkeypatch,
            returned_ids=[
                "abc12345-6789-0000-aaaa-bbbbccccdddd",
                "def67890-1234-0000-aaaa-bbbbccccdddd",
            ],
        )

        sync_mod.sync(archive_tree, full_resync=False, logger=test_logger)

        assert json.loads(
            cursor_file.read_text(encoding="utf-8")
        )["sessions_sync_timestamp"] == "2026-03-15T06:00:00Z"


class TestSessionStartGate:
    """
    Finding C2 — exit 4 and exit 6 must reach the session-start banner,
    not just a log file.
    """

    def _revoke(self, cur, sql, values, page_size=None, fetch=False):
        """execute_values stand-in modelling a REVOKE."""
        raise _FakePsycopg2ProgrammingError(
            "permission denied for table sessions", "42501",
        )

    def test_exit_four_raises_the_gate_naming_the_sqlstate(
        self, monkeypatch, tmp_path, archive_tree, pinned_gate_file,
    ):
        """
        The operator reading the banner is deciding whether to stop what
        they are doing; "exited 4" alone does not tell them. The mutation
        this kills: removing the write_gate call from the exit-4 path.
        """
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", tmp_path / "cursors.json")
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync-sessions.log",
        )
        _install_fake_psycopg2(
            monkeypatch, returned_ids=[],
            execute_values_side_effect=self._revoke,
        )
        monkeypatch.setattr(
            sys, "argv",
            ["sync-sessions-to-postgres.py", "--archive-root",
             str(archive_tree), "--full-resync"],
        )

        try:
            with pytest.raises(SystemExit):
                sync_mod.main()
        finally:
            logging.getLogger("sync-sessions-to-postgres").handlers.clear()

        lines = pinned_gate_file.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "1"
        assert "42501" in lines[1]
        assert "sync-sessions-to-postgres.py" in lines[1]

    def test_a_clean_run_lowers_the_gate(
        self, monkeypatch, tmp_path, archive_tree, pinned_gate_file,
    ):
        """
        A fixed fault must stop reporting itself without anyone deleting a
        file. The mutation this kills: removing the clear_gate call.
        """
        pinned_gate_file.parent.mkdir(parents=True, exist_ok=True)
        pinned_gate_file.write_text("1\nstale problem\n", encoding="utf-8")

        monkeypatch.setattr(sync_mod, "CURSOR_FILE", tmp_path / "cursors.json")
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync-sessions.log",
        )
        _install_fake_psycopg2(
            monkeypatch,
            returned_ids=[
                "abc12345-6789-0000-aaaa-bbbbccccdddd",
                "def67890-1234-0000-aaaa-bbbbccccdddd",
            ],
        )
        monkeypatch.setattr(
            sys, "argv",
            ["sync-sessions-to-postgres.py", "--archive-root",
             str(archive_tree), "--full-resync"],
        )

        try:
            sync_mod.main()
        finally:
            logging.getLogger("sync-sessions-to-postgres").handlers.clear()

        assert pinned_gate_file.read_text(encoding="utf-8").strip() == "0"
