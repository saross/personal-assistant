"""
Tests for sync-to-postgres.py — cursor management, JSONL parsing,
and record-to-tuple conversion.

Tests pure functions only; does not require a running PostgreSQL instance.
"""

import importlib.util
import json
import logging
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

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
        from psycopg2.extras import Json
        result = sync_mod.record_to_tuple(sample_memories[0])
        # First 13 fields are pre-v2 fixed values.
        assert result[:13] == (
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
        # v2 fields (2026-05-16): anchors, verified, links, why,
        # how_to_apply, superseded_by, revisions. JSONB fields are
        # wrapped in psycopg2.extras.Json — compare via .adapted.
        assert isinstance(result[13], Json) and result[13].adapted == []  # anchors
        assert result[14] is None                                          # verified
        assert isinstance(result[15], Json) and result[15].adapted == []  # links
        assert result[16] is None                                          # why
        assert result[17] is None                                          # how_to_apply
        assert result[18] is None                                          # superseded_by
        assert isinstance(result[19], Json) and result[19].adapted == []  # revisions

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
        from psycopg2.extras import Json
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
        # v2 defaults
        assert isinstance(result[13], Json) and result[13].adapted == []  # anchors
        assert result[14] is None                                          # verified
        assert isinstance(result[15], Json) and result[15].adapted == []  # links
        assert result[16] is None                                          # why
        assert result[17] is None                                          # how_to_apply
        assert result[18] is None                                          # superseded_by
        assert isinstance(result[19], Json) and result[19].adapted == []  # revisions

    def test_source_field_included(self, sample_memories):
        """Source field (extraction/manual) should be at index 3."""
        extraction_tuple = sync_mod.record_to_tuple(sample_memories[0])
        manual_tuple = sync_mod.record_to_tuple(sample_memories[1])
        assert extraction_tuple[3] == "extraction"
        assert manual_tuple[3] == "manual"

    def test_tuple_length_matches_fields(self, sample_memories):
        """Tuple length should match JSONL_FIELDS count (20 after v2)."""
        result = sync_mod.record_to_tuple(sample_memories[0])
        assert len(result) == len(sync_mod.JSONL_FIELDS)
        assert len(result) == 20

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
        """JSONL_FIELDS should contain all expected fields (pre-v2 + v2)."""
        expected = {
            "id", "session_id", "project", "source", "category", "content",
            "summary", "confidence", "research_tags", "zotero_key",
            "source_context", "created_at", "deadline_at",
            # v2 additions (2026-05-16)
            "anchors", "verified", "links", "why", "how_to_apply",
            "superseded_by", "revisions",
        }
        assert set(sync_mod.JSONL_FIELDS) == expected

    def test_source_in_fields(self):
        """The 'source' field must be present in JSONL_FIELDS."""
        assert "source" in sync_mod.JSONL_FIELDS


# ============================================================================
# Insert Accounting (#55 fix)
# ============================================================================


class _FakePsycopg2Error(Exception):
    """Stand-in for ``psycopg2.Error`` — base class for all DB errors."""


class _FakePsycopg2OperationalError(_FakePsycopg2Error):
    """Stand-in for ``psycopg2.OperationalError`` (subclass of Error)."""


def _install_fake_psycopg2(
    monkeypatch: pytest.MonkeyPatch,
    *,
    present_before_ids: list[str],
    returned_ids: list[str],
    raise_on_connect: bool = False,
    advisory_lock_acquired: bool = True,
) -> MagicMock:
    """
    Install a fake ``psycopg2`` package into ``sys.modules`` that the
    function-level import in ``insert_memories`` and the advisory-lock
    helper will pick up.

    The mock controls:
      - the pre-flight SELECT result (``present_before_ids``)
      - the RETURNING result of ``execute_values`` (``returned_ids``)
      - whether ``psycopg2.connect`` raises an OperationalError
      - whether ``pg_try_advisory_lock`` reports acquired (for the
        contended-lock path)

    Returns the fake connection mock so callers can assert on usage.
    """
    fake_psycopg2 = types.ModuleType("psycopg2")
    fake_extras = types.ModuleType("psycopg2.extras")

    fake_psycopg2.Error = _FakePsycopg2Error
    fake_psycopg2.OperationalError = _FakePsycopg2OperationalError

    # Fake Json wrapper for JSONB columns (v2 schema). record_to_tuple
    # imports Json lazily from psycopg2.extras to wrap anchors/links/
    # revisions; the mock just stores .adapted so tests can introspect.
    class _FakeJson:
        def __init__(self, value):
            self.adapted = value

        def __repr__(self):
            return f"FakeJson({self.adapted!r})"

    fake_extras.Json = _FakeJson

    # Cursor mock: fetchall returns the pre-flight SELECT result;
    # fetchone returns the schema-version row when ``meta`` is queried
    # (audit IC5 boot-time assertion) and the advisory-lock boolean
    # otherwise.
    cur = MagicMock()
    cur.fetchall.return_value = [(mid,) for mid in present_before_ids]

    last_sql = {"value": ""}

    def _exec(sql, *args, **kwargs):
        last_sql["value"] = sql
        return None

    def _fetchone():
        if "meta" in last_sql["value"]:
            # Schema version: bumped to "2" on 2026-05-16 with the v2
            # schema migration. Must match _schema_version.EXPECTED_SCHEMA_VERSION
            # and the seed value in scripts/schema.sql.
            return ("2",)
        return (advisory_lock_acquired,)

    cur.execute.side_effect = _exec
    cur.fetchone.side_effect = _fetchone
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

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

    # execute_values returns RETURNING rows when fetch=True.
    fake_extras.execute_values = MagicMock(
        return_value=[(mid,) for mid in returned_ids]
    )

    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", fake_extras)

    return conn


@pytest.fixture
def test_logger() -> logging.Logger:
    """Quiet logger for accountability tests."""
    return logging.getLogger("test-sync")


class TestInsertMemoriesAccounting:
    """Row-level accounting for :func:`insert_memories` (#55)."""

    def _make_records(self, ids: list[str]) -> list[tuple]:
        """Build minimal INSERT tuples with the given ids."""
        return [
            (
                mid, "sess", None, "extraction", "progress", "c",
                None, "medium", [], None, "", "2026-04-23T00:00:00Z", None,
            )
            for mid in ids
        ]

    def test_all_new_rows_all_inserted(
        self, monkeypatch: pytest.MonkeyPatch, test_logger: logging.Logger
    ) -> None:
        """Empty pre-flight + full RETURNING → clean insert, no drops."""
        ids = ["new-a", "new-b", "new-c"]
        _install_fake_psycopg2(
            monkeypatch,
            present_before_ids=[],
            returned_ids=ids,
        )
        result = sync_mod.insert_memories(self._make_records(ids), test_logger)
        assert result.db_available is True
        assert result.input_count == 3
        assert result.inserted == 3
        assert result.expected_dupes == 0
        assert result.unexpected_drops == []

    def test_all_duplicates_all_expected(
        self, monkeypatch: pytest.MonkeyPatch, test_logger: logging.Logger
    ) -> None:
        """All ids pre-existing, 0 returned → all expected dupes, no drops."""
        ids = ["dup-a", "dup-b"]
        _install_fake_psycopg2(
            monkeypatch,
            present_before_ids=ids,
            returned_ids=[],
        )
        result = sync_mod.insert_memories(self._make_records(ids), test_logger)
        assert result.db_available is True
        assert result.inserted == 0
        assert result.expected_dupes == 2
        assert result.unexpected_drops == []

    def test_mixed_new_and_expected_dupes(
        self, monkeypatch: pytest.MonkeyPatch, test_logger: logging.Logger
    ) -> None:
        """N input, K pre-existing, N-K returned → counts correct, no drops."""
        ids = ["dup-a", "new-b", "dup-c", "new-d"]
        _install_fake_psycopg2(
            monkeypatch,
            present_before_ids=["dup-a", "dup-c"],
            returned_ids=["new-b", "new-d"],
        )
        result = sync_mod.insert_memories(self._make_records(ids), test_logger)
        assert result.db_available is True
        assert result.input_count == 4
        assert result.inserted == 2
        assert result.expected_dupes == 2
        assert result.unexpected_drops == []

    def test_unexpected_drop_halts_cursor(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        test_logger: logging.Logger,
    ) -> None:
        """Id absent from both pre-flight and RETURNING → drop + no advance."""
        # Point CURSOR_FILE and QUARANTINE_FILE into tmp_path and MEMORIES_FILE
        # at a small stub so sync() can run end-to-end.
        memories = tmp_path / "memories.jsonl"
        memories.write_text(
            json.dumps({
                "id": "mem-a",
                "category": "progress",
                "content": "x",
                "created_at": "2026-04-23T00:00:00Z",
            }) + "\n"
            + json.dumps({
                "id": "mem-b",
                "category": "progress",
                "content": "y",
                "created_at": "2026-04-23T00:00:00Z",
            }) + "\n",
            encoding="utf-8",
        )
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "quarantine.jsonl"

        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)

        # mem-a absent both pre-flight and RETURNING → unexpected drop.
        # mem-b returned normally.
        _install_fake_psycopg2(
            monkeypatch,
            present_before_ids=[],
            returned_ids=["mem-b"],
        )

        sync_mod.sync(test_logger)

        # Cursor must not have advanced.
        assert not cursor_file.exists() or (
            json.loads(cursor_file.read_text()).get("postgres_sync_line", 0) == 0
        )
        # Quarantine file must contain the dropped record.
        assert quarantine.exists()
        lines = [
            json.loads(line) for line in quarantine.read_text().splitlines()
            if line.strip()
        ]
        assert len(lines) == 1
        assert lines[0]["id"] == "mem-a"

    def test_unexpected_drop_result_shape(
        self, monkeypatch: pytest.MonkeyPatch, test_logger: logging.Logger
    ) -> None:
        """Direct check: unexpected_drops is populated on id fall-through."""
        ids = ["ok-1", "dropped-2", "ok-3"]
        _install_fake_psycopg2(
            monkeypatch,
            present_before_ids=[],
            returned_ids=["ok-1", "ok-3"],
        )
        result = sync_mod.insert_memories(self._make_records(ids), test_logger)
        assert result.db_available is True
        assert result.unexpected_drops == ["dropped-2"]
        assert result.inserted == 2

    def test_db_unavailable_no_advance(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        test_logger: logging.Logger,
    ) -> None:
        """psycopg2.connect raising → db_available=False, cursor untouched."""
        memories = tmp_path / "memories.jsonl"
        memories.write_text(
            json.dumps({
                "id": "mem-a",
                "category": "progress",
                "content": "x",
                "created_at": "2026-04-23T00:00:00Z",
            }) + "\n",
            encoding="utf-8",
        )
        cursor_file = tmp_path / "sync-cursors.json"

        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)

        _install_fake_psycopg2(
            monkeypatch,
            present_before_ids=[],
            returned_ids=[],
            raise_on_connect=True,
        )

        sync_mod.sync(test_logger)

        # Cursor key should not be set.
        if cursor_file.exists():
            data = json.loads(cursor_file.read_text())
            assert "postgres_sync_line" not in data or data["postgres_sync_line"] == 0

    def test_within_batch_dedup_last_wins(
        self, monkeypatch: pytest.MonkeyPatch, test_logger: logging.Logger
    ) -> None:
        """
        Input batch with duplicate ids collapses to the last occurrence.
        The ``duplicates_within_batch`` counter surfaces the collapse so
        operators can see canonical-corruption signals without the
        accounting line looking like a silent-drop event.
        """
        # Two records share id ``dup-a``; only the last should survive
        # the within-batch dedup pass.
        records = [
            (
                "dup-a", "sess", None, "extraction", "progress", "first",
                None, "medium", [], None, "", "2026-04-23T00:00:00Z", None,
            ),
            (
                "new-b", "sess", None, "extraction", "progress", "x",
                None, "medium", [], None, "", "2026-04-23T00:00:00Z", None,
            ),
            (
                "dup-a", "sess", None, "extraction", "progress", "second",
                None, "medium", [], None, "", "2026-04-23T00:00:00Z", None,
            ),
        ]
        _install_fake_psycopg2(
            monkeypatch,
            present_before_ids=[],
            returned_ids=["dup-a", "new-b"],
        )
        result = sync_mod.insert_memories(records, test_logger)
        assert result.db_available is True
        assert result.duplicates_within_batch == 1
        # Deduped input count: 2 unique ids (dup-a and new-b).
        assert result.input_count == 2
        assert result.inserted == 2
        assert result.unexpected_drops == []

    def test_quarantine_dedup_skips_already_present(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        test_logger: logging.Logger,
    ) -> None:
        """
        Repeated calls to _write_quarantine with the same id append
        only once — the quarantine file does not grow linearly when the
        cursor is halted and cron re-runs the same input slice.
        """
        quarantine = tmp_path / "quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)

        dropped = [{"id": "mem-x", "content": "payload"}]
        sync_mod._write_quarantine(dropped, test_logger)
        sync_mod._write_quarantine(dropped, test_logger)
        sync_mod._write_quarantine(dropped, test_logger)

        lines = [
            json.loads(line) for line in quarantine.read_text().splitlines()
            if line.strip()
        ]
        assert len(lines) == 1
        assert lines[0]["id"] == "mem-x"

    def test_quarantine_dedup_appends_new_only(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        test_logger: logging.Logger,
    ) -> None:
        """Mixed new + already-quarantined input writes only the new ids."""
        quarantine = tmp_path / "quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)

        sync_mod._write_quarantine(
            [{"id": "old-1", "content": "a"}], test_logger
        )
        sync_mod._write_quarantine(
            [{"id": "old-1", "content": "a"}, {"id": "new-2", "content": "b"}],
            test_logger,
        )

        lines = [
            json.loads(line) for line in quarantine.read_text().splitlines()
            if line.strip()
        ]
        ids = {ln["id"] for ln in lines}
        assert ids == {"old-1", "new-2"}
        assert len(lines) == 2

    def test_advisory_lock_contended_skips_sync(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        test_logger: logging.Logger,
    ) -> None:
        """
        When another sync holds the advisory lock, sync() exits cleanly
        without touching the cursor or calling insert_memories.
        """
        memories = tmp_path / "memories.jsonl"
        memories.write_text(
            json.dumps({
                "id": "mem-a",
                "category": "progress",
                "content": "x",
                "created_at": "2026-04-23T00:00:00Z",
            }) + "\n",
            encoding="utf-8",
        )
        cursor_file = tmp_path / "sync-cursors.json"

        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)

        _install_fake_psycopg2(
            monkeypatch,
            present_before_ids=[],
            returned_ids=["mem-a"],
            advisory_lock_acquired=False,
        )

        # Spy on insert_memories — it must not be called when contended.
        called = {"insert": False}
        orig_insert = sync_mod.insert_memories

        def _spy(records, logger):
            called["insert"] = True
            return orig_insert(records, logger)

        monkeypatch.setattr(sync_mod, "insert_memories", _spy)

        sync_mod.sync(test_logger)

        assert called["insert"] is False
        # Cursor key should not be set (or left at 0).
        if cursor_file.exists():
            data = json.loads(cursor_file.read_text())
            assert data.get("postgres_sync_line", 0) == 0

    def test_narrow_exception_reraises_non_psycopg_errors(
        self, monkeypatch: pytest.MonkeyPatch, test_logger: logging.Logger
    ) -> None:
        """
        The post-connect except clause catches psycopg2.Error only; a
        KeyError from a malformed record bubbles up rather than being
        disguised as ``db_available=False``. This lets programmer bugs
        surface instead of being swallowed.
        """
        _install_fake_psycopg2(
            monkeypatch,
            present_before_ids=[],
            returned_ids=[],
        )
        # Make execute_values raise a non-psycopg error.
        sys.modules["psycopg2.extras"].execute_values = MagicMock(
            side_effect=KeyError("missing column")
        )
        with pytest.raises(KeyError):
            sync_mod.insert_memories(
                self._make_records(["a"]), test_logger
            )

    def test_poison_lines_are_quarantined_before_advance(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        test_logger: logging.Logger,
    ) -> None:
        """
        Audit IC2 / B-C4: when every line in a slice fails to parse, the
        cursor used to advance silently and the corrupt block was lost
        forever. New contract: quarantine each poison line, then advance.
        """
        memories = tmp_path / "memories.jsonl"
        # All three lines are poison — two malformed, one missing id.
        memories.write_text(
            "{not valid json\n"
            "}}also broken{{\n"
            + json.dumps({
                "category": "progress",
                "content": "x",
                "created_at": "2026-04-23T00:00:00Z",
                # No id field — fails required-field validation.
            }) + "\n",
            encoding="utf-8",
        )
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "quarantine.jsonl"

        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)

        _install_fake_psycopg2(
            monkeypatch,
            present_before_ids=[],
            returned_ids=[],
        )

        sync_mod.sync(test_logger)

        # Cursor advanced past the poison slice (anti-infinite-loop).
        assert cursor_file.exists()
        cursor_data = json.loads(cursor_file.read_text())
        assert cursor_data["postgres_sync_line"] == 3

        # Each poison line landed in the quarantine with a reason.
        assert quarantine.exists()
        entries = [
            json.loads(line) for line in
            quarantine.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(entries) == 3
        reasons = {e["reason"] for e in entries}
        # Two malformed JSON + one missing-id-field.
        assert "parse_failure" in reasons
        assert any(r.startswith("missing_required_field:") for r in reasons)
        for entry in entries:
            assert "quarantined_at" in entry
            assert "raw_line" in entry["record"]
            assert "line_number" in entry["record"]
