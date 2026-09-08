"""
Tests for sync-to-postgres.py — cursor management, JSONL parsing,
and record-to-tuple conversion.

Tests pure functions only; does not require a running PostgreSQL instance.
"""

import fcntl
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
_sync_path = Path(__file__).parent.parent / "scripts" / "sync-to-postgres.py"
_spec = importlib.util.spec_from_file_location("sync_to_postgres", _sync_path)
sync_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_mod)


def _seed_gate(gate: Path, detail: str) -> None:
    """Seed a standing fault through the state machine.

    The gate file is derived from the sidecar state, so a test that writes
    the file by hand is describing a state that does not exist — the next
    run would legitimately render it away.
    """
    import _sync_gate

    _sync_gate.apply_gate(
        _sync_gate.GateEvent(
            outcome=_sync_gate.CYCLE_DEGRADED,
            fault_detail=detail,
            script="test",
        ),
        gate_path=gate,
        logger=logging.getLogger("test-seed"),
    )


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

    def test_save_cursor_is_atomic(self, tmp_path, monkeypatch):
        """
        Audit round two, finding P16: a cursor save interrupted part-way
        must leave the previous file intact.

        The old implementation used ``Path.write_text``, which truncates
        the real path before writing — a kill in that window reset *every*
        sync's cursor at once. The replacement writes a temp file and
        renames, so an interrupted save is a no-op. The mutation this
        kills: reverting ``save_cursor`` to ``CURSOR_FILE.write_text(...)``.
        """
        cursor_file = tmp_path / "sync-cursors.json"
        original = {"postgres_sync_line": 10, "zotero_sync_line": 3}
        cursor_file.write_text(json.dumps(original), encoding="utf-8")
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        def _boom(src, dst):
            raise KeyboardInterrupt("killed mid-write")

        monkeypatch.setattr(os, "replace", _boom)
        with pytest.raises(KeyboardInterrupt):
            sync_mod.save_cursor(11)

        assert json.loads(cursor_file.read_text(encoding="utf-8")) == original

    def test_save_sync_timestamp_is_atomic(self, tmp_path, monkeypatch):
        """The freshness marker takes the same atomic path (finding P16)."""
        cursor_file = tmp_path / "sync-cursors.json"
        original = {"postgres_sync_line": 10}
        cursor_file.write_text(json.dumps(original), encoding="utf-8")
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)

        def _boom(src, dst):
            raise KeyboardInterrupt("killed mid-write")

        monkeypatch.setattr(os, "replace", _boom)
        with pytest.raises(KeyboardInterrupt):
            sync_mod.save_sync_timestamp()

        assert json.loads(cursor_file.read_text(encoding="utf-8")) == original


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
        # v3 fields (2026-05-17): source_message_uuid (Gap 1) — defaults
        # to None when absent from the JSONL record; licence and
        # extractor_model_id (Gap 3) — both default to None when absent.
        assert result[20] is None                                          # source_message_uuid
        assert result[21] is None                                          # licence
        assert result[22] is None                                          # extractor_model_id

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
        # v3 defaults (Gap 1 + Gap 3)
        assert result[20] is None                                          # source_message_uuid
        assert result[21] is None                                          # licence
        assert result[22] is None                                          # extractor_model_id

    def test_explicit_null_session_id_coerced_to_empty(self):
        """A present-but-null session_id must coerce to "" (NOT NULL column).

        Manual (/remember) records carry an explicit ``session_id: null``;
        a plain .get default only covers the absent-key case, and the None
        passed through aborted a full rebuild's insert batch (2026-07-04).
        """
        record = {
            "id": "test-null-session",
            "session_id": None,
            "category": "decision",
            "content": "Manually captured memory.",
            "created_at": "2026-06-15T00:00:00+00:00",
        }
        result = sync_mod.record_to_tuple(record)
        assert result[1] == ""

    def test_unparseable_deadline_coerced_to_none(self):
        """A non-timestamp deadline_at (e.g. "TBD") must sync as None.

        deadline_at is free text at capture time; passing it through to
        the TIMESTAMPTZ column aborted a full rebuild's insert batch
        (2026-07-04). A parseable deadline must still pass through intact.
        """
        base = {
            "id": "test-tbd-deadline",
            "category": "openness",
            "content": "Commitment with an undetermined deadline.",
            "created_at": "2026-07-02T00:00:00+00:00",
        }
        tbd = sync_mod.record_to_tuple({**base, "deadline_at": "TBD"})
        assert tbd[12] is None
        kept = sync_mod.record_to_tuple(
            {**base, "deadline_at": "2026-07-15T00:00:00+00:00"}
        )
        assert kept[12] == "2026-07-15T00:00:00+00:00"

    def test_source_field_included(self, sample_memories):
        """Source field (extraction/manual) should be at index 3."""
        extraction_tuple = sync_mod.record_to_tuple(sample_memories[0])
        manual_tuple = sync_mod.record_to_tuple(sample_memories[1])
        assert extraction_tuple[3] == "extraction"
        assert manual_tuple[3] == "manual"

    def test_tuple_length_matches_fields(self, sample_memories):
        """Tuple length should match JSONL_FIELDS count (24 after the P8 is_active append)."""
        result = sync_mod.record_to_tuple(sample_memories[0])
        assert len(result) == len(sync_mod.JSONL_FIELDS)
        assert len(result) == 24

    def test_is_active_defaults_true_and_propagates(self):
        """P8: is_active lands at the last tuple index — default True, False when set."""
        active = sync_mod.record_to_tuple({
            "id": "t-active", "category": "progress", "content": "x",
            "created_at": "2026-06-06T00:00:00+00:00",
        })
        forgotten = sync_mod.record_to_tuple({
            "id": "t-forgotten", "category": "progress", "content": "x",
            "created_at": "2026-06-06T00:00:00+00:00", "is_active": False,
        })
        assert active[-1] is True
        assert forgotten[-1] is False

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

    def test_source_message_uuid_propagates_to_tuple(self):
        """v3: source_message_uuid (when present) lands at index 20.

        Provenance audit Gap 1 (2026-05-17): the tuple position must
        match the INSERT column order in :func:`insert_memories`. A
        legitimate UUID flows through unchanged for the verifier's
        UUID-indexed lookup path.
        """
        record = {
            "id": "test-with-uuid",
            "category": "progress",
            "content": "Anchor me.",
            "created_at": "2026-05-17T00:00:00+00:00",
            "source_message_uuid": "msg-uuid-anchor",
        }
        result = sync_mod.record_to_tuple(record)
        assert result[20] == "msg-uuid-anchor"

    def test_licence_propagates_to_tuple(self):
        """v3: licence (when present) lands at index 21.

        Provenance audit Gap 3 (2026-05-17): when a record carries a
        sharing licence (e.g. populated post-hoc by a curation pass),
        the value flows through to the PG column unchanged.
        """
        record = {
            "id": "test-with-licence",
            "category": "progress",
            "content": "Shareable.",
            "created_at": "2026-05-17T00:00:00+00:00",
            "licence": "CC-BY-4.0",
        }
        result = sync_mod.record_to_tuple(record)
        assert result[21] == "CC-BY-4.0"

    def test_extractor_model_id_propagates_to_tuple(self):
        """v3: extractor_model_id (when present) lands at index 22.

        Provenance audit Gap 3 (2026-05-17): the Haiku version that
        produced the memory is preserved for RO-Crate attribution and
        for model-version invalidation passes after a Haiku regression.
        """
        record = {
            "id": "test-with-model",
            "category": "progress",
            "content": "Attributed.",
            "created_at": "2026-05-17T00:00:00+00:00",
            "extractor_model_id": "claude-haiku-4-5-20251001",
        }
        result = sync_mod.record_to_tuple(record)
        assert result[22] == "claude-haiku-4-5-20251001"


# ============================================================================
# Field Order Consistency
# ============================================================================


class TestFieldConsistency:
    """Ensure JSONL_FIELDS matches the tuple produced by record_to_tuple."""

    def test_field_list_contents(self):
        """JSONL_FIELDS should contain all expected fields (pre-v2 + v2 + v3)."""
        expected = {
            "id", "session_id", "project", "source", "category", "content",
            "summary", "confidence", "research_tags", "zotero_key",
            "source_context", "created_at", "deadline_at",
            # v2 additions (2026-05-16)
            "anchors", "verified", "links", "why", "how_to_apply",
            "superseded_by", "revisions",
            # v3 additions (2026-05-17): source_message_uuid (Gap 1),
            # licence + extractor_model_id (Gap 3).
            "source_message_uuid", "licence", "extractor_model_id",
            # P8 fix (2026-06-06): soft-delete flag now syncs to PG.
            "is_active",
        }
        assert set(sync_mod.JSONL_FIELDS) == expected

    def test_source_in_fields(self):
        """The 'source' field must be present in JSONL_FIELDS."""
        assert "source" in sync_mod.JSONL_FIELDS


# ============================================================================
# Insert Accounting (#55 fix)
# ============================================================================


class _FakePsycopg2Error(Exception):
    """Stand-in for ``psycopg2.Error`` — base class for all DB errors.

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
    """Stand-in for ``psycopg2.DataError`` — the record's content is wrong."""


class _FakePsycopg2ProgrammingError(_FakePsycopg2Error):
    """Stand-in for ``psycopg2.ProgrammingError``.

    Client-side ("can't adapt type 'dict'") when constructed without a
    SQLSTATE; server-side (InsufficientPrivilege, UndefinedTable,
    UndefinedColumn) when given one.
    """


class _FakePsycopg2InternalError(_FakePsycopg2Error):
    """Stand-in for ``psycopg2.InternalError`` — e.g. InFailedSqlTransaction."""


class _FakePsycopg2IntegrityError(_FakePsycopg2Error):
    """Stand-in for ``psycopg2.IntegrityError`` — e.g. a NOT NULL violation."""


def _poisoning_execute_values(
    poison_ids: set[str],
    error_class: type[Exception] = _FakePsycopg2DataError,
    message: str = (
        'invalid input syntax for type timestamp with time zone: "TBD"'
    ),
    pgcode: str | None = "",
):
    """
    Build an ``execute_values`` stand-in that refuses specific ids.

    The batch contains the poison record alongside the healthy ones, so it
    raises; the per-row replay then raises only on the poison record —
    exactly the shape of the live failure.
    """

    def _side_effect(cur, sql, values, page_size=None, fetch=False):
        ids = [row[0] for row in values]
        offending = [mid for mid in ids if mid in poison_ids]
        if offending:
            # Default: a distinct SQLSTATE per row, so the all-alike
            # environment rule is never what these tests exercise. Pass
            # ``pgcode=None`` to model an error psycopg2 raised
            # client-side, which carries no SQLSTATE.
            code = (
                f"22{abs(hash(offending[0])) % 1000:03d}"
                if pgcode == "" else pgcode
            )
            raise error_class(f"{message} (row {offending[0]})", code)
        return [(mid,) for mid in ids]

    return _side_effect


def _install_fake_psycopg2(
    monkeypatch: pytest.MonkeyPatch,
    *,
    present_before_ids: list[str],
    returned_ids: list[str],
    raise_on_connect: bool = False,
    advisory_lock_acquired: bool = True,
    execute_values_side_effect=None,
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
    fake_psycopg2.InterfaceError = _FakePsycopg2InterfaceError
    fake_psycopg2.DataError = _FakePsycopg2DataError
    fake_psycopg2.ProgrammingError = _FakePsycopg2ProgrammingError
    fake_psycopg2.InternalError = _FakePsycopg2InternalError
    fake_psycopg2.IntegrityError = _FakePsycopg2IntegrityError

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
            # Schema version: bumped to "3" on 2026-05-17 with the v3
            # schema migration (source_message_uuid column for tier-3
            # verifier fallback). Must match
            # _schema_version.EXPECTED_SCHEMA_VERSION and the seed
            # value in scripts/schema.sql.
            return ("3",)
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

    # execute_values returns RETURNING rows when fetch=True, unless the
    # caller supplied a side effect (for the refused-row tests).
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


# ============================================================================
# Shrink guard (item 22) — a cursor stranded past EOF after an archival
# sweep (or any JSONL shrink) must trigger a full re-scan, not a silent
# no-op that skips every subsequent append.
# ============================================================================


class TestShrinkResetItem22:
    """_sync_locked must honour _sync_cursor.detect_jsonl_shrink."""

    def _wire(self, tmp_path, monkeypatch, *, cursor_value, n_records):
        """Build a tmp corpus + cursor and mock the DB insert; return the mock."""
        corpus = tmp_path / "memories.jsonl"
        recs = [
            {
                "id": f"id{i}",
                "category": "progress",
                "content": f"record {i}",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
            for i in range(n_records)
        ]
        corpus.write_text(
            "".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text(
            json.dumps({"postgres_sync_line": cursor_value}) + "\n",
            encoding="utf-8")

        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", corpus)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)  # skip Ollama path
        # Isolation: point quarantine at tmp so a future poison-line fixture
        # can never write to the real data/memories quarantine file.
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl")

        ok = MagicMock()
        ok.db_available = True
        ok.unexpected_drops = []
        insert = MagicMock(return_value=ok)
        monkeypatch.setattr(sync_mod, "insert_memories", insert)
        return insert

    def test_stranded_cursor_triggers_full_rescan(self, tmp_path, monkeypatch):
        # cursor=100 but the file has only 3 lines → shrink → reset to 0 →
        # re-scan all 3 (without the guard this hits the no-op early-return).
        insert = self._wire(tmp_path, monkeypatch, cursor_value=100, n_records=3)
        sync_mod._sync_locked(logging.getLogger("item22-test"))
        assert insert.call_count == 1
        assert len(insert.call_args[0][0]) == 3      # all records re-scanned
        assert sync_mod.load_cursor() == 3           # cursor landed at new EOF

    def test_in_bounds_cursor_not_reset(self, tmp_path, monkeypatch):
        # cursor=2, file has 5 lines → no shrink → process only the 3 new.
        insert = self._wire(tmp_path, monkeypatch, cursor_value=2, n_records=5)
        sync_mod._sync_locked(logging.getLogger("item22-test"))
        assert len(insert.call_args[0][0]) == 3      # lines 3,4,5 only
        assert sync_mod.load_cursor() == 5

    def test_exact_eof_is_not_a_shrink(self, tmp_path, monkeypatch):
        # cursor == line count → no new work, no reset, clean no-op.
        insert = self._wire(tmp_path, monkeypatch, cursor_value=3, n_records=3)
        sync_mod._sync_locked(logging.getLogger("item22-test"))
        insert.assert_not_called()
        assert sync_mod.load_cursor() == 3


# ============================================================================
# Audit round two, finding P2 (lens A-C2/A-X1/A-X2) — a refused record is
# not an outage; created_at and NUL are guarded at ingest
# ============================================================================


class TestRefusedRecordsVersusOutages:
    """
    The memories path had the sessions path's defect plus two extra
    exposures: an unguarded ``created_at`` (TIMESTAMPTZ NOT NULL) and a
    NUL in ``content``, which raises ``ValueError`` — not a
    ``psycopg2.Error`` — and so escaped every handler in the file.
    """

    def _record(self, mid: str, **overrides) -> dict:
        """Build a minimal valid canonical record."""
        record = {
            "id": mid,
            "category": "progress",
            "content": f"content for {mid}",
            "created_at": "2026-09-01T00:00:00+00:00",
        }
        record.update(overrides)
        return record

    def _write_canonical(self, path: Path, records: list[dict]) -> None:
        """Write records to a canonical JSONL file."""
        path.write_text(
            "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8",
        )

    def test_nul_in_content_is_stripped_at_ingest(self, tmp_path):
        """
        A NUL in content used to raise ``ValueError: A string literal
        cannot contain NUL`` from psycopg2 — outside the psycopg2.Error
        ladder entirely, so main's bare except exited 1 with the cursor
        untouched. The mutation this kills: dropping ``sanitise_nuls``
        from ``classify_jsonl_line``.
        """
        logger = logging.getLogger("test-nul")
        line = json.dumps(self._record("m1", content="before\x00after"))
        record, reason = sync_mod.classify_jsonl_line(line, 1, logger)
        assert reason is None
        assert record["content"] == "beforeafter"
        assert "\x00" not in json.dumps(record)

    def test_unparseable_created_at_is_poison_not_a_stall(self, tmp_path):
        """
        ``created_at`` is TIMESTAMPTZ NOT NULL and has no NULL-coercion
        escape, unlike ``deadline_at``. Free text there must be
        quarantined at parse time rather than halting the cursor.
        """
        logger = logging.getLogger("test-created-at")
        for bad in ("TBD", "2026-08-XX", "2026-Q4", "", None, 12345):
            line = json.dumps(self._record("m1", created_at=bad))
            record, reason = sync_mod.classify_jsonl_line(line, 1, logger)
            assert record is None, f"{bad!r} should not have parsed"
            assert reason is not None

    def test_valid_created_at_shapes_still_parse(self):
        """The guard must not reject the shapes the writers actually emit."""
        logger = logging.getLogger("test-created-at-ok")
        for good in (
            "2026-09-01T00:00:00+00:00",
            "2026-09-01T00:00:00.123456+00:00",
            "2026-09-01T00:00:00Z",
        ):
            line = json.dumps(self._record("m1", created_at=good))
            record, reason = sync_mod.classify_jsonl_line(line, 1, logger)
            assert reason is None, f"{good!r} should have parsed"
            assert record is not None

    def test_free_text_created_at_advances_the_cursor(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        One hand-edited timestamp must not make every later memory
        invisible to /recall. End-to-end: the bad record is quarantined,
        the good one syncs, and the cursor moves.
        """
        memories = tmp_path / "memories.jsonl"
        self._write_canonical(memories, [
            self._record("m-good"),
            self._record("m-bad", created_at="TBD"),
        ])
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=["m-good"],
        )

        sync_mod.sync(test_logger)

        assert json.loads(cursor_file.read_text())["postgres_sync_line"] == 2
        entries = [
            json.loads(line)
            for line in quarantine.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [e["reason"] for e in entries] == ["unparseable_created_at"]

    def test_refused_record_is_quarantined_and_cursor_advances(
        self, monkeypatch, tmp_path, test_logger, caplog,
    ):
        """
        The database refuses one record; the healthy record still lands,
        the refused one is quarantined, and the cursor advances. The
        mutation this kills: classifying every ``psycopg2.Error`` as
        ``db_available=False``.
        """
        memories = tmp_path / "memories.jsonl"
        self._write_canonical(memories, [
            self._record("m-good"),
            self._record("m-bad"),
        ])
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
            execute_values_side_effect=_poisoning_execute_values({"m-bad"}),
        )

        with caplog.at_level(logging.INFO):
            sync_mod.sync(test_logger)

        assert json.loads(cursor_file.read_text())["postgres_sync_line"] == 2
        entries = [
            json.loads(line)
            for line in quarantine.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [e["record"]["id"] for e in entries] == ["m-bad"]
        assert entries[0]["reason"] == "postgres_refused_row"
        assert "may be down" not in caplog.text
        assert "may be stopped" not in caplog.text

    def test_cannot_adapt_dict_is_a_row_error(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        A JSON object where a scalar belongs raises ProgrammingError
        ("can't adapt type 'dict'") — client-side, with no SQLSTATE. That
        is content, not an outage and not an environment fault: the
        SQLSTATE is what separates it from an InsufficientPrivilege or an
        UndefinedTable, which share its exception class (re-audit C1).
        """
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        _install_fake_psycopg2(
            monkeypatch,
            present_before_ids=[],
            returned_ids=[],
            execute_values_side_effect=_poisoning_execute_values(
                {"b"},
                error_class=_FakePsycopg2ProgrammingError,
                message="can't adapt type 'dict'",
                # Client-side adaptation failure: no SQLSTATE, and about
                # this row alone — unlike a server-side ProgrammingError.
                pgcode=None,
            ),
        )
        records = [
            sync_mod.record_to_tuple({
                "id": mid, "category": "progress", "content": "c",
                "created_at": "2026-09-01T00:00:00+00:00",
            })
            for mid in ("a", "b", "c")
        ]

        result = sync_mod.insert_memories(records, test_logger)

        assert result.db_available is True
        assert result.inserted == 2
        assert result.quarantined == ("b",)
        assert result.unexpected_drops == []

    def test_outage_still_holds_the_cursor(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        A genuine outage keeps the old behaviour: nothing quarantined,
        cursor untouched, retry on the next tick. The split must not turn
        a stopped PostgreSQL into a quarantined canonical.
        """
        memories = tmp_path / "memories.jsonl"
        self._write_canonical(memories, [self._record("m-good")])
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)

        def _server_gone(cur, sql, values, page_size=None, fetch=False):
            raise _FakePsycopg2OperationalError(
                "server closed the connection unexpectedly"
            )

        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=[],
            execute_values_side_effect=_server_gone,
        )

        sync_mod.sync(test_logger)

        if cursor_file.exists():
            assert json.loads(
                cursor_file.read_text()
            ).get("postgres_sync_line", 0) == 0
        assert not quarantine.exists()


class TestQuarantineDedupAtTheCallSite:
    """
    Finding P14 (lens A-M12) at the call site that produced it.

    The poison-quarantine loop runs *before* ``insert_memories``, so while
    the cursor is halted — a PostgreSQL outage, say — every five-minute
    tick re-parses the same slice and re-quarantines the same lines: 288
    duplicate entries per poison line per day, burying the entries that
    are genuinely distinct.
    """

    def test_repeated_outage_ticks_quarantine_once(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        Twelve ticks (one hour) against an unreachable database must
        leave one quarantine entry per poison line, not twelve. The
        mutation this kills: removing the dedup branch from
        ``quarantine_record``.
        """
        memories = tmp_path / "memories.jsonl"
        memories.write_text(
            "{not valid json\n"
            + json.dumps({
                "id": "m-good", "category": "progress", "content": "c",
                "created_at": "2026-09-01T00:00:00+00:00",
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
            monkeypatch, present_before_ids=[], returned_ids=[],
            raise_on_connect=True,
        )

        for _ in range(12):
            sync_mod.sync(test_logger)

        entries = [
            json.loads(line)
            for line in quarantine.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(entries) == 1, (
            f"one poison line quarantined {len(entries)} times across 12 "
            "ticks"
        )
        assert entries[0]["reason"] == "parse_failure"
        # And the cursor really is still halted, which is what makes the
        # re-read happen at all.
        if cursor_file.exists():
            assert json.loads(
                cursor_file.read_text()
            ).get("postgres_sync_line", 0) == 0


# ============================================================================
# Re-audit finding C1 — an environment fault is neither an outage nor a
# refused record
# ============================================================================


class TestEnvironmentFaults:
    """
    The memories store is the one where quarantining wrongly costs most:
    a cursor reset would put 42k records through the replay, and a REVOKE
    or a half-applied migration refuses every one of them alike.
    """

    def _canonical(self, path: Path, ids: list[str]) -> None:
        """Write a small valid canonical file."""
        path.write_text(
            "".join(
                json.dumps({
                    "id": mid, "category": "progress", "content": "c",
                    "created_at": "2026-09-01T00:00:00+00:00",
                }) + "\n"
                for mid in ids
            ),
            encoding="utf-8",
        )

    def _undefined_column(self, cur, sql, values, page_size=None, fetch=False):
        """execute_values stand-in modelling a half-applied migration."""
        raise _FakePsycopg2ProgrammingError(
            'column "is_active" does not exist', "42703",
        )

    def test_missing_column_holds_the_cursor_and_quarantines_nothing(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        The C1 regression in full: with ProgrammingError in the refused-row
        class, every record was quarantined and the cursor advanced past
        the whole slice. The mutation this kills: returning ROW for a
        ProgrammingError carrying a SQLSTATE.
        """
        memories = tmp_path / "memories.jsonl"
        self._canonical(memories, ["m1", "m2", "m3"])
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=[],
            execute_values_side_effect=self._undefined_column,
        )

        with pytest.raises(sync_mod.EnvironmentFault):
            sync_mod.sync(test_logger)

        assert not quarantine.exists()
        if cursor_file.exists():
            assert json.loads(
                cursor_file.read_text()
            ).get("postgres_sync_line", 0) == 0

    def test_main_exits_four(self, monkeypatch, tmp_path):
        """
        Not exit 0. Before this, an environment fault could quarantine a
        whole cursor window and still report success.
        """
        memories = tmp_path / "memories.jsonl"
        self._canonical(memories, ["m1", "m2"])
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", tmp_path / "cursors.json")
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )
        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=[],
            execute_values_side_effect=self._undefined_column,
        )

        monkeypatch.setattr(sys, "argv", ["sync-to-postgres.py"])
        try:
            with pytest.raises(SystemExit) as excinfo:
                sync_mod.main()
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        assert excinfo.value.code == 4

    def test_correlated_poison_is_quarantined_and_advances(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        Three records refused with the same 22P05 — one buggy extraction
        run, or three sessions from one LLM batch all carrying a NUL.
        Every one is quarantined and the cursor advances. An earlier
        version of this branch held the cursor and exited 4 here, every
        tick, for ever, with no escape hatch: P1 rebuilt on correlated
        poison. The mutation this kills: reinstating an "every row failed
        alike" environment rule.
        """
        memories = tmp_path / "memories.jsonl"
        self._canonical(memories, ["m1", "m2", "m3"])
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)

        def _same_fault(cur, sql, values, page_size=None, fetch=False):
            raise _FakePsycopg2DataError(
                "unsupported Unicode escape sequence", "22P05",
            )

        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=[],
            execute_values_side_effect=_same_fault,
        )

        sync_mod.sync(test_logger)

        assert json.loads(cursor_file.read_text())["postgres_sync_line"] == 3
        entries = [
            json.loads(line)
            for line in quarantine.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert sorted(e["record"]["id"] for e in entries) == ["m1", "m2", "m3"]

    def test_a_single_poison_record_still_advances(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        The guard against over-correction: one refused record in a
        one-record slice is a row fault, not an environment fault, and
        must still be quarantined so the cursor can move.
        """
        memories = tmp_path / "memories.jsonl"
        self._canonical(memories, ["m-only"])
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=[],
            execute_values_side_effect=_poisoning_execute_values({"m-only"}),
        )

        sync_mod.sync(test_logger)

        assert json.loads(cursor_file.read_text())["postgres_sync_line"] == 1
        entries = [
            json.loads(line)
            for line in quarantine.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [e["record"]["id"] for e in entries] == ["m-only"]

    def test_revoke_after_a_success_still_holds_the_cursor(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        The case the all-alike rule cannot catch: one record lands, then a
        REVOKE refuses the rest. Only the exception's *class* says this is
        not about the data. Without that, the remaining records are
        quarantined and the cursor advances past them. The mutation this
        kills: emptying ENVIRONMENT_ERROR_NAMES.
        """
        memories = tmp_path / "memories.jsonl"
        self._canonical(memories, ["m1", "m2", "m3"])
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)

        def _revoke_after_first(cur, sql, values, page_size=None, fetch=False):
            ids = [row[0] for row in values]
            if ids == ["m1"]:
                return [("m1",)]
            if len(ids) > 1:
                # The initial batch: fails because m2/m3 are refused.
                raise _FakePsycopg2DataError("batch aborted", "22P05")
            raise _FakePsycopg2ProgrammingError(
                "permission denied for table memories", "42501",
            )

        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=[],
            execute_values_side_effect=_revoke_after_first,
        )

        with pytest.raises(sync_mod.EnvironmentFault):
            sync_mod.sync(test_logger)

        assert not quarantine.exists()
        if cursor_file.exists():
            assert json.loads(
                cursor_file.read_text()
            ).get("postgres_sync_line", 0) == 0


class TestCursorResetMidRun:
    """
    Re-audit finding M3 — a rebuild that clears the cursors while a sync
    is mid-cycle must not have the sync's stale position written back.
    """

    def _canonical(self, path: Path, ids: list[str]) -> None:
        """Write a small valid canonical file."""
        path.write_text(
            "".join(
                json.dumps({
                    "id": mid, "category": "progress", "content": "c",
                    "created_at": "2026-09-01T00:00:00+00:00",
                }) + "\n"
                for mid in ids
            ),
            encoding="utf-8",
        )

    def test_vanished_cursor_key_is_not_written_back(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        The rebuild removes ``postgres_sync_line`` between this cycle's
        read and its write. Writing 3 back would tell the next run that
        rows the rebuild truncated are already synced — they would never
        be replayed. The mutation this kills: dropping ``expect_present``
        from ``save_cursor``.
        """
        memories = tmp_path / "memories.jsonl"
        self._canonical(memories, ["m1", "m2", "m3"])
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(
            json.dumps({"postgres_sync_line": 0}), encoding="utf-8",
        )
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[],
            returned_ids=["m1", "m2", "m3"],
        )

        original_insert = sync_mod.insert_memories

        def _rebuild_runs_now(records, logger, quarantine_cap=None, quarantine_anyway=False):
            """Simulate rebuild-postgres.py clearing the cursors mid-cycle."""
            cursor_file.write_text(json.dumps({}), encoding="utf-8")
            return original_insert(records, logger, quarantine_cap, quarantine_anyway)

        monkeypatch.setattr(sync_mod, "insert_memories", _rebuild_runs_now)

        with pytest.raises(sync_mod.CursorKeyVanished):
            sync_mod.sync(test_logger)

        assert "postgres_sync_line" not in json.loads(
            cursor_file.read_text(encoding="utf-8")
        )

    def test_main_exits_six(self, monkeypatch, tmp_path):
        """A distinct exit code, so the operator can tell this apart."""
        memories = tmp_path / "memories.jsonl"
        self._canonical(memories, ["m1"])
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(
            json.dumps({"postgres_sync_line": 0}), encoding="utf-8",
        )
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )
        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=["m1"],
        )

        original_insert = sync_mod.insert_memories

        def _rebuild_runs_now(records, logger, quarantine_cap=None, quarantine_anyway=False):
            cursor_file.write_text(json.dumps({}), encoding="utf-8")
            return original_insert(records, logger, quarantine_cap, quarantine_anyway)

        monkeypatch.setattr(sync_mod, "insert_memories", _rebuild_runs_now)

        monkeypatch.setattr(sys, "argv", ["sync-to-postgres.py"])
        try:
            with pytest.raises(SystemExit) as excinfo:
                sync_mod.main()
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        assert excinfo.value.code == 6

    def test_first_run_with_no_cursor_key_still_writes(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        The over-correction guard: a key that was never there is a first
        run (or the first run after a rebuild), and must still be written.
        """
        memories = tmp_path / "memories.jsonl"
        self._canonical(memories, ["m1"])
        cursor_file = tmp_path / "sync-cursors.json"
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=["m1"],
        )

        sync_mod.sync(test_logger)

        assert json.loads(
            cursor_file.read_text(encoding="utf-8")
        )["postgres_sync_line"] == 1


class TestQuarantineDedupSeesBothShapes:
    """
    Re-audit, low finding: two record shapes live in one quarantine file.
    ``_write_quarantine`` appends the bare row (id at the top level);
    ``_sync_cursor.quarantine_record`` wraps it as
    ``{"reason", "quarantined_at", "record"}`` (id one level down).
    ``_load_quarantined_ids`` read only the first, so the drop-path dedup
    could not see entries the refused-row path had written.
    """

    def test_wrapped_entries_are_seen_by_the_dedup(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        A record quarantined by the refused-row path must not be appended
        a second time by the drop path. The mutation this kills: reading
        only ``rec.get("id")``.
        """
        quarantine = tmp_path / "quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)

        # Shape 2: written by quarantine_record (id nested under "record").
        sync_mod.quarantine_record(
            quarantine,
            {"id": "m-x", "postgres_error": "refused"},
            "postgres_refused_row",
            logger=test_logger,
        )
        assert sync_mod._load_quarantined_ids() == {"m-x"}

        # The drop path must now treat it as already present.
        sync_mod._write_quarantine([{"id": "m-x", "content": "c"}], test_logger)

        entries = [
            json.loads(line)
            for line in quarantine.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(entries) == 1

    def test_bare_entries_are_still_seen(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """The original shape must keep working — this reads both."""
        quarantine = tmp_path / "quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)
        sync_mod._write_quarantine([{"id": "m-y", "content": "c"}], test_logger)
        assert sync_mod._load_quarantined_ids() == {"m-y"}


class TestTheCycleReadsTheCursorUnderTheLock:
    """
    Low finding L1, at the call site. The helper being correct is not
    enough: the sync must actually use it, and
    ``read_cursor_file_locked`` → ``read_cursor_file`` survived as a
    mutation until this test existed.
    """

    def test_the_first_cursor_read_holds_the_lock(
        self, monkeypatch, tmp_path, test_logger,
    ):
        """
        Observed from inside the read itself: the first time the cycle
        looks at the cursor file, the sidecar lock must already be held,
        or a rebuild can land between the position and the key-presence
        check. The mutation this kills: calling ``read_cursor_file``
        instead of ``read_cursor_file_locked`` in ``_sync_locked``.
        """
        import _sync_cursor

        memories = tmp_path / "memories.jsonl"
        memories.write_text(
            json.dumps({
                "id": "m1", "category": "progress", "content": "c",
                "created_at": "2026-09-01T00:00:00+00:00",
            }) + "\n",
            encoding="utf-8",
        )
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(
            json.dumps({"postgres_sync_line": 0}), encoding="utf-8",
        )
        lock_path = cursor_file.with_name(cursor_file.name + ".lock")
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=["m1"],
        )

        observations = []
        real_read = _sync_cursor.read_cursor_file

        def _probe(path):
            """Record whether the cursor lock is held during this read."""
            held = False
            if lock_path.exists():
                with open(lock_path, "a", encoding="utf-8") as probe:
                    try:
                        fcntl.flock(
                            probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB,
                        )
                    except BlockingIOError:
                        held = True
                    else:
                        fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
            observations.append(held)
            return real_read(path)

        monkeypatch.setattr(_sync_cursor, "read_cursor_file", _probe)
        monkeypatch.setattr(sync_mod, "read_cursor_file", _probe)

        sync_mod.sync(test_logger)

        assert observations, "the cursor file was never read"
        assert observations[0] is True, (
            "the cycle's first cursor read was taken without the lock"
        )


class TestMemoriesGatePolicyIsWired:
    """
    Finding M5 — the memories sync's correlated hold had no end-to-end
    test, so replacing its guard with ``if False`` survived.
    """

    def _canonical(self, path: Path, ids: list[str]) -> None:
        """Write a small valid canonical file."""
        path.write_text(
            "".join(
                json.dumps({
                    "id": mid, "category": "progress", "content": "c",
                    "created_at": "2026-09-01T00:00:00+00:00",
                }) + "\n"
                for mid in ids
            ),
            encoding="utf-8",
        )

    def test_a_correlated_batch_holds_the_cursor_end_to_end(
        self, monkeypatch, tmp_path, test_logger, pinned_gate_file,
    ):
        """
        Five records refused alike: cursor held, nothing quarantined,
        exit 4, gate naming the SQLSTATE and the exact command. The
        mutation this kills: ``if status == CORRELATED`` → ``if False``
        in ``insert_memories``.
        """
        memories = tmp_path / "memories.jsonl"
        self._canonical(memories, [f"m{i}" for i in range(5)])
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )

        def _all_alike(cur, sql, values, page_size=None, fetch=False):
            raise _FakePsycopg2IntegrityError(
                'null value in column "project"', "23502",
            )

        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=[],
            execute_values_side_effect=_all_alike,
        )
        monkeypatch.setattr(sys, "argv", ["sync-to-postgres.py"])

        try:
            with pytest.raises(SystemExit) as excinfo:
                sync_mod.main()
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        assert excinfo.value.code == 4
        assert not quarantine.exists()
        if cursor_file.exists():
            assert json.loads(
                cursor_file.read_text()
            ).get("postgres_sync_line", 0) == 0
        gate = pinned_gate_file.read_text(encoding="utf-8")
        assert "23502" in gate
        assert "venv/bin/python3" in gate
        assert "--quarantine-anyway" in gate

    def test_an_idle_tick_leaves_the_gate_end_to_end(
        self, monkeypatch, tmp_path, pinned_gate_file,
    ):
        """
        Finding C1 through ``main``: the commonest run of all — nothing
        new to sync — must not lower a standing gate.
        """
        memories = tmp_path / "memories.jsonl"
        self._canonical(memories, ["m1"])
        cursor_file = tmp_path / "sync-cursors.json"
        cursor_file.write_text(
            json.dumps({"postgres_sync_line": 1}), encoding="utf-8",
        )
        _seed_gate(pinned_gate_file, "rows were refused earlier")
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )
        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=[],
        )
        monkeypatch.setattr(sys, "argv", ["sync-to-postgres.py"])

        try:
            sync_mod.main()
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        assert pinned_gate_file.read_text(encoding="utf-8").startswith("1"), (
            "a no-op tick lowered a standing gate"
        )

    def test_an_unexpected_exception_raises_a_gate(
        self, monkeypatch, tmp_path, pinned_gate_file,
    ):
        """
        Finding M2: exit 1 raised no gate, so a sync that died in a way
        nobody anticipated stayed dead silently, every five minutes.
        """
        memories = tmp_path / "memories.jsonl"
        self._canonical(memories, ["m1"])
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", tmp_path / "cursors.json")
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )

        def _boom(logger, *args, **kwargs):
            raise RuntimeError("something nobody anticipated")

        monkeypatch.setattr(sync_mod, "sync", _boom)
        monkeypatch.setattr(sys, "argv", ["sync-to-postgres.py"])

        try:
            with pytest.raises(SystemExit) as excinfo:
                sync_mod.main()
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        assert excinfo.value.code == 1
        gate = pinned_gate_file.read_text(encoding="utf-8")
        assert "UNEXPECTED ERROR" in gate
        assert "something nobody anticipated" in gate

    def test_a_schema_mismatch_exit_raises_a_gate(
        self, monkeypatch, tmp_path, pinned_gate_file,
    ):
        """
        Finding M2: assert_schema_version exits 2 from deep in the stack,
        and SystemExit is a BaseException, so it sailed past the handler
        and raised nothing.
        """
        memories = tmp_path / "memories.jsonl"
        self._canonical(memories, ["m1"])
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", tmp_path / "cursors.json")
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )

        def _exit_two(logger, *args, **kwargs):
            sys.exit(2)

        monkeypatch.setattr(sync_mod, "sync", _exit_two)
        monkeypatch.setattr(sys, "argv", ["sync-to-postgres.py"])

        try:
            with pytest.raises(SystemExit) as excinfo:
                sync_mod.main()
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        assert excinfo.value.code == 2
        assert "exit 2" in pinned_gate_file.read_text(encoding="utf-8")


class TestParseLayerQuarantineReachesTheGate:
    """
    A poison line is quarantined before any database contact, so the cycle
    is idle — but rows still left the pipeline, and the gate must say so.
    """

    def test_a_poison_line_raises_the_quarantine_problem(
        self, monkeypatch, tmp_path, pinned_gate_file,
    ):
        """
        The mutation this kills: dropping ``quarantined`` from the idle
        CycleResult, or gating the quarantine problem behind a completed
        outcome.
        """
        memories = tmp_path / "memories.jsonl"
        memories.write_text("{not valid json\n", encoding="utf-8")
        quarantine = tmp_path / "quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", tmp_path / "cursors.json")
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )
        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=[],
        )
        monkeypatch.setattr(sys, "argv", ["sync-to-postgres.py"])

        try:
            sync_mod.main()
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        gate = pinned_gate_file.read_text(encoding="utf-8")
        assert "1 row(s) have been REFUSED" in gate
        assert str(quarantine) in gate

    def test_ack_quarantine_clears_it(
        self, monkeypatch, tmp_path, pinned_gate_file,
    ):
        """
        The one thing that lowers a quarantine problem is a human saying
        they have looked. The mutation this kills: ignoring the flag.
        """
        memories = tmp_path / "memories.jsonl"
        memories.write_text("{not valid json\n", encoding="utf-8")
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", tmp_path / "cursors.json")
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )
        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=[],
        )
        monkeypatch.setattr(sys, "argv", ["sync-to-postgres.py"])
        try:
            sync_mod.main()
            assert "REFUSED" in pinned_gate_file.read_text(encoding="utf-8")

            monkeypatch.setattr(
                sys, "argv", ["sync-to-postgres.py", "--ack-quarantine"],
            )
            # The ack is state-only and exits on its own (finding C1).
            with pytest.raises(SystemExit) as excinfo:
                sync_mod.main()
            assert excinfo.value.code == 0
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        assert pinned_gate_file.read_text(encoding="utf-8").strip() == "0"


class TestAcknowledgementIsStateOnly:
    """
    Sixth re-audit, finding C1 — ``--ack-quarantine`` ran a full sync, so
    a contended cron tick returned at the contended branch before the
    acknowledgement was applied, while main logged "cleared by hand" over
    a problem that still stood.
    """

    def _standing_quarantine(self, gate: Path) -> None:
        """Raise a quarantine problem through the state machine."""
        import _sync_gate

        _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
                processed=1, quarantined=4, script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-ack"),
        )

    def test_the_ack_works_while_another_instance_holds_the_lock(
        self, monkeypatch, tmp_path, pinned_gate_file,
    ):
        """
        The acknowledgement is a state operation, not a sync: contention
        is irrelevant to it. The mutation this kills: running the cycle
        before handling the ack.
        """
        import _sync_gate

        self._standing_quarantine(pinned_gate_file)
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", tmp_path / "m.jsonl")
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", tmp_path / "cursors.json")
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )
        # Every instance is contended, and the canonical is missing too.
        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=[],
            advisory_lock_acquired=False,
        )
        monkeypatch.setattr(
            sys, "argv", ["sync-to-postgres.py", "--ack-quarantine"],
        )

        try:
            with pytest.raises(SystemExit) as excinfo:
                sync_mod.main()
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        assert excinfo.value.code == 0
        state = _sync_gate.read_state(pinned_gate_file)
        assert _sync_gate.PROBLEM_QUARANTINE not in state.problems
        assert state.acked["acked_count"] == 4
        assert "acked_at" in state.acked

    def test_the_ack_never_touches_the_database(
        self, monkeypatch, tmp_path, pinned_gate_file,
    ):
        """A state-only operation opens no connection at all."""
        self._standing_quarantine(pinned_gate_file)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", tmp_path / "cursors.json")
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )
        conn = _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=[],
        )
        monkeypatch.setattr(
            sys, "argv", ["sync-to-postgres.py", "--ack-quarantine"],
        )

        try:
            with pytest.raises(SystemExit):
                sync_mod.main()
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        assert sys.modules["psycopg2"].connect.call_count == 0, (
            "the acknowledgement opened a database connection"
        )

    def test_a_failed_ack_exits_non_zero_and_says_so(
        self, monkeypatch, tmp_path, pinned_gate_file, caplog,
    ):
        """
        The log must never claim success over a failure. The failure is
        induced where it really happens — the atomic write — with
        ``next_state`` untouched, so the state this exercises is one the
        code can actually produce (seventh re-audit, finding C1). The
        mutation this kills: returning the intended state from
        ``apply_gate`` rather than what is on disk.
        """
        import _sync_gate

        self._standing_quarantine(pinned_gate_file)
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(
            sys, "argv", ["sync-to-postgres.py", "--ack-quarantine"],
        )

        def _refuse_to_write(path, text):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(_sync_gate, "_atomic_write", _refuse_to_write)

        try:
            with caplog.at_level(logging.ERROR):
                with pytest.raises(SystemExit) as excinfo:
                    sync_mod.main()
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        assert excinfo.value.code == 9
        assert "did NOT clear" in caplog.text
        # And the problem really is still there for the next run.
        monkeypatch.undo()
        state = _sync_gate.read_state(pinned_gate_file)
        assert _sync_gate.PROBLEM_QUARANTINE in state.problems

    def test_an_ack_with_nothing_standing_says_so(
        self, monkeypatch, tmp_path, pinned_gate_file, caplog,
    ):
        """
        Low: acknowledging nothing used to report "cleared 0 rows". The
        mutation this kills: dropping the nothing-to-do branch.
        """
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(
            sys, "argv", ["sync-to-postgres.py", "--ack-quarantine"],
        )

        try:
            with caplog.at_level(logging.INFO):
                with pytest.raises(SystemExit) as excinfo:
                    sync_mod.main()
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        assert excinfo.value.code == 0
        assert "no standing quarantine problem" in caplog.text
        assert "cleared a quarantine problem covering 0" not in caplog.text


class TestAHeldCursorDoesNotInflateTheGate:
    """
    Seventh re-audit, finding C2 — a duplicate quarantine entry counted
    as freshly quarantined, so with the cursor held the gate's number
    grew by the whole batch every five minutes over a file that never
    changed.
    """

    def test_four_ticks_of_a_held_cursor_report_the_same_count(
        self, monkeypatch, tmp_path, pinned_gate_file,
    ):
        """
        Two poison lines, four ticks, cursor held throughout: the gate
        must say 2 every time, because the file says 2. The mutation this
        kills: counting anything but QUARANTINE_WRITTEN.
        """
        import _sync_gate

        memories = tmp_path / "memories.jsonl"
        memories.write_text(
            "{not valid json\n}}also broken{{\n", encoding="utf-8",
        )
        cursor_file = tmp_path / "sync-cursors.json"
        quarantine = tmp_path / "quarantine.jsonl"
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(sync_mod, "QUARANTINE_FILE", quarantine)
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )
        # The database is down, so the cursor never advances and the same
        # two lines are re-read on every tick.
        _install_fake_psycopg2(
            monkeypatch, present_before_ids=[], returned_ids=[],
            raise_on_connect=True,
        )
        monkeypatch.setattr(sys, "argv", ["sync-to-postgres.py"])

        try:
            for tick in range(4):
                sync_mod.main()
                state = _sync_gate.read_state(pinned_gate_file)
                problem = state.problems.get(_sync_gate.PROBLEM_QUARANTINE)
                assert problem is not None
                assert problem.count == 2, (
                    f"after tick {tick + 1} the gate claims "
                    f"{problem.count} quarantined rows"
                )
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        # And the file really does hold two.
        lines = [
            line for line in quarantine.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == 2


class TestAGateFailureNeverChangesTheExitCode:
    """
    Seventh re-audit, finding M1 — an unwritable ~/.cache raised
    PermissionError through every caller, so a schema mismatch's exit 2
    became an exit 1 traceback and the indexer's absent-root path
    returned 1.
    """

    def test_a_schema_mismatch_still_exits_two(
        self, monkeypatch, tmp_path, pinned_gate_file,
    ):
        """
        The gate is about reporting the condition, never about changing
        what the script does about it. The mutation this kills: letting
        the gate's OSError propagate out of apply_gate.
        """
        import _sync_gate

        memories = tmp_path / "memories.jsonl"
        memories.write_text("", encoding="utf-8")
        monkeypatch.setattr(sync_mod, "MEMORIES_FILE", memories)
        monkeypatch.setattr(sync_mod, "CURSOR_FILE", tmp_path / "cursors.json")
        monkeypatch.setattr(
            sync_mod, "QUARANTINE_FILE", tmp_path / "quarantine.jsonl",
        )
        monkeypatch.setattr(sync_mod, "HAS_EMBED", False)
        monkeypatch.setattr(sync_mod, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            sync_mod, "LOG_FILE", tmp_path / "logs" / "sync.log",
        )
        monkeypatch.setattr(sys, "argv", ["sync-to-postgres.py"])

        def _exit_two(logger, *args, **kwargs):
            sys.exit(2)

        monkeypatch.setattr(sync_mod, "sync", _exit_two)

        # ~/.cache is unwritable: the gate cannot be taken at all.
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(sync_mod, "GATE_FILE", blocker / "g")

        try:
            with pytest.raises(SystemExit) as excinfo:
                sync_mod.main()
        finally:
            logging.getLogger("sync-to-postgres").handlers.clear()

        assert excinfo.value.code == 2, (
            "a gate failure changed the exit code for the underlying "
            "condition"
        )
