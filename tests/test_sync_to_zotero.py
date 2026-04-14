"""Tests for scripts/sync-to-zotero.py."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the hyphenated module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sync_to_zotero = importlib.import_module("sync-to-zotero")


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------

SAMPLE_MEMORIES = [
    # Valid — source_insight with real 8-char key
    {
        "id": "2026-04-12-aaaaaaaaaa01",
        "session_id": "session-uuid-01",
        "category": "source_insight",
        "content": "Key finding about X leading to Y.",
        "research_tags": ["topic-a", "method-b"],
        "created_at": "2026-04-12T10:00:00+00:00",
        "zotero_key": "MPZHXY3P",
    },
    # Valid — another source_insight
    {
        "id": "2026-04-12-aaaaaaaaaa02",
        "session_id": "session-uuid-02",
        "category": "source_insight",
        "content": "Alternative hypothesis for Z.",
        "research_tags": ["topic-c"],
        "created_at": "2026-04-12T11:00:00+00:00",
        "zotero_key": "N2C5KIGL",
    },
    # Legacy — zotero_key is a citation slug (not valid)
    {
        "id": "2026-04-12-aaaaaaaaaa03",
        "category": "source_insight",
        "content": "Legacy memory with slug key.",
        "created_at": "2026-04-12T12:00:00+00:00",
        "zotero_key": "buchanan-hamilton-2021",
    },
    # Not source_insight — should be ignored
    {
        "id": "2026-04-12-aaaaaaaaaa04",
        "category": "decision",
        "content": "A decision, not a source insight.",
        "created_at": "2026-04-12T13:00:00+00:00",
        "zotero_key": "MPZHXY3P",
    },
    # source_insight without zotero_key — should be ignored
    {
        "id": "2026-04-12-aaaaaaaaaa05",
        "category": "source_insight",
        "content": "Insight without a Zotero link.",
        "created_at": "2026-04-12T14:00:00+00:00",
    },
]


def write_jsonl(path: Path, memories: list[dict]) -> None:
    """Write memories as JSONL."""
    with open(path, "w", encoding="utf-8") as fh:
        for mem in memories:
            fh.write(json.dumps(mem, ensure_ascii=False) + "\n")


# -------------------------------------------------------------------------
# Validation tests
# -------------------------------------------------------------------------

class TestIsValidZoteroKey:
    """Tests for the 8-char alphanumeric key validator."""

    def test_accepts_valid_key(self) -> None:
        """Real Zotero keys (8 uppercase alphanumeric) are accepted."""
        assert sync_to_zotero.is_valid_zotero_key("MPZHXY3P")
        assert sync_to_zotero.is_valid_zotero_key("N2C5KIGL")
        assert sync_to_zotero.is_valid_zotero_key("9B2FJ6SL")

    def test_rejects_citation_slugs(self) -> None:
        """Author-year slugs are rejected."""
        assert not sync_to_zotero.is_valid_zotero_key("buchanan-hamilton-2021")
        assert not sync_to_zotero.is_valid_zotero_key("sobotkova_2023")

    def test_rejects_arxiv_ids(self) -> None:
        """arXiv IDs are rejected."""
        assert not sync_to_zotero.is_valid_zotero_key("2511.21569")

    def test_rejects_wrong_length(self) -> None:
        """Strings of the wrong length are rejected."""
        assert not sync_to_zotero.is_valid_zotero_key("SHORT")
        assert not sync_to_zotero.is_valid_zotero_key("TOOLONGXYZ")
        assert not sync_to_zotero.is_valid_zotero_key("ABC12345X")

    def test_rejects_lowercase(self) -> None:
        """Lowercase strings are rejected (Zotero keys are uppercase)."""
        assert not sync_to_zotero.is_valid_zotero_key("mpzhxy3p")

    def test_rejects_none_and_empty(self) -> None:
        """None and empty strings are rejected."""
        assert not sync_to_zotero.is_valid_zotero_key(None)
        assert not sync_to_zotero.is_valid_zotero_key("")


# -------------------------------------------------------------------------
# Filter tests
# -------------------------------------------------------------------------

class TestLoadPendingMemories:
    """Tests for memory filtering and cursor-relative loading."""

    def test_filters_to_valid_source_insights(self, tmp_path: Path) -> None:
        """Only source_insight memories with valid keys are returned."""
        jsonl = tmp_path / "memories.jsonl"
        write_jsonl(jsonl, SAMPLE_MEMORIES)

        with patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl):
            pending, new_cursor, legacy = (
                sync_to_zotero.load_pending_memories(0)
            )

        assert len(pending) == 2
        ids = {m["id"] for m in pending}
        assert ids == {
            "2026-04-12-aaaaaaaaaa01",
            "2026-04-12-aaaaaaaaaa02",
        }
        assert legacy == 1  # The citation-slug memory
        assert new_cursor == 5  # 5 lines read

    def test_resumes_from_cursor(self, tmp_path: Path) -> None:
        """Lines before the cursor are skipped."""
        jsonl = tmp_path / "memories.jsonl"
        write_jsonl(jsonl, SAMPLE_MEMORIES)

        # Start from line 3 (skip first 3 entries)
        with patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl):
            pending, new_cursor, legacy = (
                sync_to_zotero.load_pending_memories(3)
            )

        # Only entries 3+ scanned; neither is a valid source_insight
        assert pending == []
        assert legacy == 0
        assert new_cursor == 5

    def test_empty_file(self, tmp_path: Path) -> None:
        """Empty JSONL yields empty pending list."""
        jsonl = tmp_path / "memories.jsonl"
        jsonl.write_text("", encoding="utf-8")

        with patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl):
            pending, _, legacy = sync_to_zotero.load_pending_memories(0)

        assert pending == []
        assert legacy == 0


# -------------------------------------------------------------------------
# Note formatting tests
# -------------------------------------------------------------------------

class TestFormatNote:
    """Tests for HTML note rendering."""

    def test_includes_content(self) -> None:
        """Rendered note contains the memory's content."""
        mem = SAMPLE_MEMORIES[0]
        html = sync_to_zotero.format_note(mem)
        assert "Key finding about X leading to Y." in html

    def test_includes_marker(self) -> None:
        """Rendered note contains the memory ID marker."""
        mem = SAMPLE_MEMORIES[0]
        html = sync_to_zotero.format_note(mem)
        assert sync_to_zotero.NOTE_MARKER_PREFIX in html
        assert f"<code>{mem['id']}</code>" in html

    def test_includes_tags(self) -> None:
        """Rendered note contains tags if present."""
        mem = SAMPLE_MEMORIES[0]
        html = sync_to_zotero.format_note(mem)
        assert "topic-a" in html
        assert "method-b" in html

    def test_escapes_html(self) -> None:
        """HTML special characters in content are escaped."""
        mem = {
            "id": "test-id",
            "content": "Finding: x < y & z > w",
            "created_at": "2026-04-12T10:00:00+00:00",
            "session_id": "abc",
            "research_tags": [],
        }
        html = sync_to_zotero.format_note(mem)
        assert "&lt;" in html
        assert "&gt;" in html
        assert "&amp;" in html
        # Raw < > & should not appear in the content paragraph
        assert "x < y" not in html
        assert "x > y" not in html

    def test_missing_optional_fields(self) -> None:
        """Memory without tags or session still renders."""
        mem = {
            "id": "test-id",
            "content": "Just content.",
            "created_at": "2026-04-12T10:00:00+00:00",
        }
        html = sync_to_zotero.format_note(mem)
        assert "Just content." in html
        assert "test-id" in html


# -------------------------------------------------------------------------
# Marker parsing tests
# -------------------------------------------------------------------------

class TestExtractMemoryIds:
    """Tests for parsing memory IDs from existing notes."""

    def test_extracts_single_marker(self) -> None:
        """A note with one marker returns a single ID."""
        note = (
            "<p>Some content.</p><hr>"
            "<p><em>— source_insight memory "
            "<code>2026-04-12-abc123</code> (captured ...)</em></p>"
        )
        ids = sync_to_zotero.extract_memory_ids_from_note(note)
        assert ids == {"2026-04-12-abc123"}

    def test_extracts_multiple_markers(self) -> None:
        """A note with multiple markers returns all IDs."""
        note = (
            "source_insight memory <code>id-1</code>"
            " and source_insight memory <code>id-2</code>"
        )
        ids = sync_to_zotero.extract_memory_ids_from_note(note)
        assert ids == {"id-1", "id-2"}

    def test_returns_empty_for_plain_note(self) -> None:
        """A note without markers returns an empty set."""
        note = "<p>Just a regular Zotero note.</p>"
        ids = sync_to_zotero.extract_memory_ids_from_note(note)
        assert ids == set()

    def test_returns_empty_for_empty_note(self) -> None:
        """An empty string returns an empty set."""
        assert sync_to_zotero.extract_memory_ids_from_note("") == set()


# -------------------------------------------------------------------------
# Cursor tests
# -------------------------------------------------------------------------

class TestCursor:
    """Tests for cursor persistence."""

    def test_load_returns_zero_when_missing(self, tmp_path: Path) -> None:
        """Missing cursor file returns 0."""
        cursor = tmp_path / "cursors.json"
        with patch.object(sync_to_zotero, "CURSOR_FILE", cursor):
            assert sync_to_zotero.load_cursor() == 0

    def test_round_trip(self, tmp_path: Path) -> None:
        """save_cursor then load_cursor returns the same value."""
        cursor = tmp_path / "cursors.json"
        with patch.object(sync_to_zotero, "CURSOR_FILE", cursor):
            sync_to_zotero.save_cursor(42)
            assert sync_to_zotero.load_cursor() == 42

    def test_preserves_other_keys(self, tmp_path: Path) -> None:
        """Saving the Zotero cursor does not clobber other cursor keys."""
        cursor = tmp_path / "cursors.json"
        cursor.write_text(
            json.dumps({
                "postgres_sync_line": 100,
                "other_key": "value",
            }),
            encoding="utf-8",
        )
        with patch.object(sync_to_zotero, "CURSOR_FILE", cursor):
            sync_to_zotero.save_cursor(42)

        data = json.loads(cursor.read_text())
        assert data["postgres_sync_line"] == 100
        assert data["other_key"] == "value"
        assert data["zotero_sync_line"] == 42


# -------------------------------------------------------------------------
# Sync orchestration tests (mocked pyzotero)
# -------------------------------------------------------------------------

class TestRunSync:
    """End-to-end sync tests with mocked pyzotero client."""

    def _setup(
        self, tmp_path: Path, memories: list[dict],
    ) -> tuple[Path, Path, Path]:
        """Common fixture setup: write JSONL, set cursor file."""
        jsonl = tmp_path / "memories.jsonl"
        cursor = tmp_path / "cursors.json"
        logs = tmp_path / "logs"
        write_jsonl(jsonl, memories)
        return jsonl, cursor, logs

    def test_dry_run_skips_api(self, tmp_path: Path) -> None:
        """Dry run produces no API calls and does not advance cursor."""
        jsonl, cursor, logs = self._setup(tmp_path, SAMPLE_MEMORIES)

        with (
            patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl),
            patch.object(sync_to_zotero, "CURSOR_FILE", cursor),
            patch.object(sync_to_zotero, "LOG_DIR", logs),
            patch.object(sync_to_zotero, "LOG_FILE", logs / "sync.log"),
            patch.object(sync_to_zotero, "build_zotero_client") as mk_client,
        ):
            summary = sync_to_zotero.run_sync(dry_run=True)

        mk_client.assert_not_called()
        assert summary["created"] == 2
        assert summary["pending"] == 2
        # Cursor not advanced in dry run
        assert not cursor.exists()

    def test_live_sync_creates_notes(self, tmp_path: Path) -> None:
        """Live sync creates notes for each pending memory."""
        jsonl, cursor, logs = self._setup(tmp_path, SAMPLE_MEMORIES)

        # Mock the pyzotero client
        mock_zot = MagicMock()
        mock_zot.children.return_value = []  # No existing notes
        mock_zot.item_template.return_value = {"itemType": "note", "note": ""}
        mock_zot.create_items.return_value = {
            "successful": {"0": {"key": "NEWNOTE1"}},
            "failed": {},
        }

        with (
            patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl),
            patch.object(sync_to_zotero, "CURSOR_FILE", cursor),
            patch.object(sync_to_zotero, "LOG_DIR", logs),
            patch.object(sync_to_zotero, "LOG_FILE", logs / "sync.log"),
            patch.object(
                sync_to_zotero,
                "build_zotero_client",
                return_value=mock_zot,
            ),
            patch.object(sync_to_zotero, "API_SLEEP_SECONDS", 0),
        ):
            summary = sync_to_zotero.run_sync(dry_run=False)

        assert summary["created"] == 2
        assert summary["failed"] == 0
        assert summary["skipped_legacy"] == 1
        # Two create_items calls (one per valid memory)
        assert mock_zot.create_items.call_count == 2

        # Verify the cursor was advanced to the correct line (5 = end of
        # the 5-memory fixture file)
        assert cursor.exists()
        cursor_data = json.loads(cursor.read_text())
        assert cursor_data["zotero_sync_line"] == 5

        # Verify create_items was called with the right parent keys
        parent_keys = {
            call.kwargs.get("parentid") or call.args[1]
            for call in mock_zot.create_items.call_args_list
            if call.args or "parentid" in call.kwargs
        }
        assert parent_keys == {"MPZHXY3P", "N2C5KIGL"}

    def test_idempotency_skips_existing(self, tmp_path: Path) -> None:
        """Re-syncing memories already present as notes skips them."""
        jsonl, cursor, logs = self._setup(tmp_path, SAMPLE_MEMORIES)

        # Per-item children map: MPZHXY3P has an existing note with the
        # marker for memory aaaaaaaaaa01; N2C5KIGL has no notes
        existing_note_for_m1 = {
            "data": {
                "note": (
                    "<p>Old note.</p><hr>"
                    "<p><em>— source_insight memory "
                    "<code>2026-04-12-aaaaaaaaaa01</code></em></p>"
                )
            }
        }

        def children_side_effect(item_key: str, **kwargs):
            if item_key == "MPZHXY3P":
                return [existing_note_for_m1]
            return []

        mock_zot = MagicMock()
        mock_zot.children.side_effect = children_side_effect
        mock_zot.item_template.return_value = {"itemType": "note", "note": ""}
        mock_zot.create_items.return_value = {
            "successful": {"0": {"key": "NEW"}},
            "failed": {},
        }

        with (
            patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl),
            patch.object(sync_to_zotero, "CURSOR_FILE", cursor),
            patch.object(sync_to_zotero, "LOG_DIR", logs),
            patch.object(sync_to_zotero, "LOG_FILE", logs / "sync.log"),
            patch.object(
                sync_to_zotero,
                "build_zotero_client",
                return_value=mock_zot,
            ),
            patch.object(sync_to_zotero, "API_SLEEP_SECONDS", 0),
        ):
            summary = sync_to_zotero.run_sync(dry_run=False)

        # Memory 1 skipped (existing note has its marker)
        # Memory 2 created (no existing notes on its parent)
        assert summary["skipped_duplicate"] == 1
        assert summary["created"] == 1
        assert summary["failed"] == 0
        # create_items called exactly once, for memory 2's parent
        assert mock_zot.create_items.call_count == 1
        parent = (
            mock_zot.create_items.call_args.kwargs.get("parentid")
            or mock_zot.create_items.call_args.args[1]
        )
        assert parent == "N2C5KIGL"

    def test_item_not_found_does_not_block(self, tmp_path: Path) -> None:
        """A 404 on one memory logs a warning and proceeds."""
        jsonl, cursor, logs = self._setup(tmp_path, SAMPLE_MEMORIES)

        mock_zot = MagicMock()
        mock_zot.children.return_value = []
        mock_zot.item_template.return_value = {"itemType": "note", "note": ""}

        # First create_items raises 404, second succeeds
        call_count = {"n": 0}

        def create_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("HTTP 404: item not found")
            return {
                "successful": {"0": {"key": "OK"}},
                "failed": {},
            }

        mock_zot.create_items.side_effect = create_side_effect

        with (
            patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl),
            patch.object(sync_to_zotero, "CURSOR_FILE", cursor),
            patch.object(sync_to_zotero, "LOG_DIR", logs),
            patch.object(sync_to_zotero, "LOG_FILE", logs / "sync.log"),
            patch.object(
                sync_to_zotero,
                "build_zotero_client",
                return_value=mock_zot,
            ),
            patch.object(sync_to_zotero, "API_SLEEP_SECONDS", 0),
        ):
            summary = sync_to_zotero.run_sync(dry_run=False)

        assert summary["skipped_not_found"] == 1
        assert summary["created"] == 1
        assert summary["failed"] == 0

    def test_limit_caps_batch(self, tmp_path: Path) -> None:
        """--limit N processes at most N memories."""
        jsonl, cursor, logs = self._setup(tmp_path, SAMPLE_MEMORIES)

        mock_zot = MagicMock()
        mock_zot.children.return_value = []
        mock_zot.item_template.return_value = {"itemType": "note", "note": ""}
        mock_zot.create_items.return_value = {
            "successful": {"0": {"key": "OK"}}, "failed": {},
        }

        with (
            patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl),
            patch.object(sync_to_zotero, "CURSOR_FILE", cursor),
            patch.object(sync_to_zotero, "LOG_DIR", logs),
            patch.object(sync_to_zotero, "LOG_FILE", logs / "sync.log"),
            patch.object(
                sync_to_zotero,
                "build_zotero_client",
                return_value=mock_zot,
            ),
            patch.object(sync_to_zotero, "API_SLEEP_SECONDS", 0),
        ):
            summary = sync_to_zotero.run_sync(dry_run=False, limit=1)

        assert summary["created"] == 1
        assert mock_zot.create_items.call_count == 1

    def test_empty_file_produces_no_calls(self, tmp_path: Path) -> None:
        """Empty memories file makes no API calls."""
        jsonl, cursor, logs = self._setup(tmp_path, [])

        with (
            patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl),
            patch.object(sync_to_zotero, "CURSOR_FILE", cursor),
            patch.object(sync_to_zotero, "LOG_DIR", logs),
            patch.object(sync_to_zotero, "LOG_FILE", logs / "sync.log"),
            patch.object(sync_to_zotero, "build_zotero_client") as mk_client,
        ):
            summary = sync_to_zotero.run_sync(dry_run=False)

        mk_client.assert_not_called()
        assert summary["pending"] == 0
        assert summary["created"] == 0


# -------------------------------------------------------------------------
# Cursor edge cases (regression tests for cursor arithmetic bugs)
# -------------------------------------------------------------------------

class TestCursorEdgeCases:
    """Regression tests for cursor arithmetic in load_pending_memories."""

    def test_single_line_file_advances_cursor(self, tmp_path: Path) -> None:
        """A 1-line file with cursor=0 advances the cursor to 1.

        Regression guard: an earlier implementation used
        ``line_num + 1 if line_num else since_line`` which treated the
        valid line index 0 as falsy, leaving the cursor stuck at 0.
        """
        jsonl = tmp_path / "memories.jsonl"
        mem = {
            "id": "single",
            "category": "source_insight",
            "content": "x",
            "zotero_key": "ABC12345",
        }
        write_jsonl(jsonl, [mem])

        with patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl):
            pending, new_cursor, _ = (
                sync_to_zotero.load_pending_memories(0)
            )

        assert len(pending) == 1
        assert new_cursor == 1

    def test_cursor_not_rewound_when_since_exceeds_length(
        self, tmp_path: Path,
    ) -> None:
        """A cursor larger than the file length is preserved.

        Regression guard: an earlier implementation computed
        ``new_cursor = line_num + 1`` which could return a value LESS
        than ``since_line`` if the file had been truncated.
        """
        jsonl = tmp_path / "memories.jsonl"
        write_jsonl(jsonl, SAMPLE_MEMORIES[:3])  # 3 lines

        with patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl):
            pending, new_cursor, _ = (
                sync_to_zotero.load_pending_memories(100)
            )

        assert pending == []
        # Cursor never rewinds — stays at or above the input value
        assert new_cursor >= 100

    def test_empty_file_preserves_cursor(self, tmp_path: Path) -> None:
        """An empty file with any cursor value returns that cursor unchanged."""
        jsonl = tmp_path / "memories.jsonl"
        jsonl.write_text("", encoding="utf-8")

        with patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl):
            _, new_cursor, _ = sync_to_zotero.load_pending_memories(42)

        assert new_cursor == 42


# -------------------------------------------------------------------------
# Failure-path tests
# -------------------------------------------------------------------------

class TestFailurePaths:
    """Tests for error handling and cursor-advance invariants on failure."""

    def _setup(
        self, tmp_path: Path, memories: list[dict],
    ) -> tuple[Path, Path, Path]:
        jsonl = tmp_path / "memories.jsonl"
        cursor = tmp_path / "cursors.json"
        logs = tmp_path / "logs"
        write_jsonl(jsonl, memories)
        return jsonl, cursor, logs

    def test_generic_exception_marks_failed(self, tmp_path: Path) -> None:
        """Non-404 exception from create_items is classified as failed."""
        jsonl, cursor, logs = self._setup(
            tmp_path, [SAMPLE_MEMORIES[0]],
        )

        mock_zot = MagicMock()
        mock_zot.children.return_value = []
        mock_zot.item_template.return_value = {"itemType": "note", "note": ""}
        mock_zot.create_items.side_effect = RuntimeError(
            "Internal server error"
        )

        with (
            patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl),
            patch.object(sync_to_zotero, "CURSOR_FILE", cursor),
            patch.object(sync_to_zotero, "LOG_DIR", logs),
            patch.object(sync_to_zotero, "LOG_FILE", logs / "sync.log"),
            patch.object(
                sync_to_zotero,
                "build_zotero_client",
                return_value=mock_zot,
            ),
            patch.object(sync_to_zotero, "API_SLEEP_SECONDS", 0),
        ):
            summary = sync_to_zotero.run_sync(dry_run=False)

        assert summary["failed"] == 1
        assert summary["created"] == 0
        # Cursor NOT advanced when there are failures
        assert not cursor.exists()

    def test_template_failure_marks_failed(self, tmp_path: Path) -> None:
        """item_template raising is classified as failed."""
        jsonl, cursor, logs = self._setup(
            tmp_path, [SAMPLE_MEMORIES[0]],
        )

        mock_zot = MagicMock()
        mock_zot.children.return_value = []
        mock_zot.item_template.side_effect = RuntimeError(
            "Template service down"
        )

        with (
            patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl),
            patch.object(sync_to_zotero, "CURSOR_FILE", cursor),
            patch.object(sync_to_zotero, "LOG_DIR", logs),
            patch.object(sync_to_zotero, "LOG_FILE", logs / "sync.log"),
            patch.object(
                sync_to_zotero,
                "build_zotero_client",
                return_value=mock_zot,
            ),
            patch.object(sync_to_zotero, "API_SLEEP_SECONDS", 0),
        ):
            summary = sync_to_zotero.run_sync(dry_run=False)

        assert summary["failed"] == 1
        assert mock_zot.create_items.call_count == 0

    def test_failed_envelope_marks_failed(self, tmp_path: Path) -> None:
        """A pyzotero response with items in 'failed' is classified as failed."""
        jsonl, cursor, logs = self._setup(
            tmp_path, [SAMPLE_MEMORIES[0]],
        )

        mock_zot = MagicMock()
        mock_zot.children.return_value = []
        mock_zot.item_template.return_value = {"itemType": "note", "note": ""}
        mock_zot.create_items.return_value = {
            "successful": {},
            "failed": {"0": {"key": None, "message": "Invalid"}},
        }

        with (
            patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl),
            patch.object(sync_to_zotero, "CURSOR_FILE", cursor),
            patch.object(sync_to_zotero, "LOG_DIR", logs),
            patch.object(sync_to_zotero, "LOG_FILE", logs / "sync.log"),
            patch.object(
                sync_to_zotero,
                "build_zotero_client",
                return_value=mock_zot,
            ),
            patch.object(sync_to_zotero, "API_SLEEP_SECONDS", 0),
        ):
            summary = sync_to_zotero.run_sync(dry_run=False)

        assert summary["failed"] == 1
        assert summary["created"] == 0

    def test_success_envelope_variant_accepted(
        self, tmp_path: Path,
    ) -> None:
        """pyzotero's 'success' (singular) key is treated as a successful outcome."""
        jsonl, cursor, logs = self._setup(
            tmp_path, [SAMPLE_MEMORIES[0]],
        )

        mock_zot = MagicMock()
        mock_zot.children.return_value = []
        mock_zot.item_template.return_value = {"itemType": "note", "note": ""}
        # pyzotero sometimes returns the 'success' key instead of 'successful'
        mock_zot.create_items.return_value = {
            "success": {"0": "NEWKEY12"},
            "failed": {},
        }

        with (
            patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl),
            patch.object(sync_to_zotero, "CURSOR_FILE", cursor),
            patch.object(sync_to_zotero, "LOG_DIR", logs),
            patch.object(sync_to_zotero, "LOG_FILE", logs / "sync.log"),
            patch.object(
                sync_to_zotero,
                "build_zotero_client",
                return_value=mock_zot,
            ),
            patch.object(sync_to_zotero, "API_SLEEP_SECONDS", 0),
        ):
            summary = sync_to_zotero.run_sync(dry_run=False)

        assert summary["created"] == 1
        assert summary["failed"] == 0

    def test_children_exception_falls_back_safely(
        self, tmp_path: Path,
    ) -> None:
        """
        An exception from children() returns empty existing-ids set, so
        the memory is treated as not-yet-synced and a note is created.
        """
        jsonl, cursor, logs = self._setup(
            tmp_path, [SAMPLE_MEMORIES[0]],
        )

        mock_zot = MagicMock()
        mock_zot.children.side_effect = RuntimeError("network error")
        mock_zot.item_template.return_value = {"itemType": "note", "note": ""}
        mock_zot.create_items.return_value = {
            "successful": {"0": {"key": "NEW"}},
            "failed": {},
        }

        with (
            patch.object(sync_to_zotero, "MEMORIES_FILE", jsonl),
            patch.object(sync_to_zotero, "CURSOR_FILE", cursor),
            patch.object(sync_to_zotero, "LOG_DIR", logs),
            patch.object(sync_to_zotero, "LOG_FILE", logs / "sync.log"),
            patch.object(
                sync_to_zotero,
                "build_zotero_client",
                return_value=mock_zot,
            ),
            patch.object(sync_to_zotero, "API_SLEEP_SECONDS", 0),
        ):
            summary = sync_to_zotero.run_sync(dry_run=False)

        # Falls through to create_items which succeeds
        assert summary["created"] == 1


# -------------------------------------------------------------------------
# Content handling tests
# -------------------------------------------------------------------------

class TestContentHandling:
    """Tests for note formatting edge cases."""

    def test_unicode_content_preserved(self) -> None:
        """Non-ASCII characters survive formatting and escape pass."""
        mem = {
            "id": "unicode-test",
            "content": "Παναγία inscription from Θάσος with 1.5Ω resistance",
            "created_at": "2026-04-12T10:00:00+00:00",
            "session_id": "abc",
            "research_tags": ["epigraphy"],
        }
        html = sync_to_zotero.format_note(mem)
        assert "Παναγία" in html
        assert "Θάσος" in html
        assert "1.5Ω" in html

    def test_empty_content(self) -> None:
        """Memory with empty content still renders (no crash)."""
        mem = {
            "id": "empty-test",
            "content": "",
            "created_at": "2026-04-12T10:00:00+00:00",
            "session_id": "abc",
        }
        html = sync_to_zotero.format_note(mem)
        assert "empty-test" in html  # marker present

    def test_content_with_angle_brackets_in_marker(self) -> None:
        """Content containing <code> does not confuse the round-trip."""
        mem = {
            "id": "round-trip-id",
            "content": "The <code> tag is used for inline code in HTML.",
            "created_at": "2026-04-12T10:00:00+00:00",
            "session_id": "abc",
        }
        html = sync_to_zotero.format_note(mem)
        ids = sync_to_zotero.extract_memory_ids_from_note(html)
        assert ids == {"round-trip-id"}


# -------------------------------------------------------------------------
# Cursor robustness tests
# -------------------------------------------------------------------------

class TestCursorRobustness:
    """Tests for cursor file handling under adverse conditions."""

    def test_load_handles_corrupt_json(self, tmp_path: Path) -> None:
        """A cursor file with invalid JSON is treated as missing."""
        cursor = tmp_path / "cursors.json"
        cursor.write_text("not valid json {{{", encoding="utf-8")

        with patch.object(sync_to_zotero, "CURSOR_FILE", cursor):
            assert sync_to_zotero.load_cursor() == 0

    def test_load_handles_non_integer_value(self, tmp_path: Path) -> None:
        """A cursor file with a non-integer value returns 0."""
        cursor = tmp_path / "cursors.json"
        cursor.write_text(
            json.dumps({"zotero_sync_line": "not a number"}),
            encoding="utf-8",
        )

        with patch.object(sync_to_zotero, "CURSOR_FILE", cursor):
            assert sync_to_zotero.load_cursor() == 0

    def test_save_handles_corrupt_existing_file(
        self, tmp_path: Path,
    ) -> None:
        """Saving does not crash if the existing cursor file is corrupt."""
        cursor = tmp_path / "cursors.json"
        cursor.write_text("garbage {{{", encoding="utf-8")

        with patch.object(sync_to_zotero, "CURSOR_FILE", cursor):
            sync_to_zotero.save_cursor(10)  # Should not raise
            assert sync_to_zotero.load_cursor() == 10


# -------------------------------------------------------------------------
# Not-found exception detection tests
# -------------------------------------------------------------------------

class TestNotFoundDetection:
    """Tests for _is_not_found_exception."""

    def test_detects_404_string(self) -> None:
        """Exceptions with '404' in message are recognised."""
        assert sync_to_zotero._is_not_found_exception(
            Exception("HTTP 404 Client Error")
        )

    def test_detects_not_found_string(self) -> None:
        """Exceptions with 'not found' in message are recognised."""
        assert sync_to_zotero._is_not_found_exception(
            Exception("The resource was Not Found")
        )

    def test_ignores_unrelated_errors(self) -> None:
        """Unrelated exceptions are not treated as not-found."""
        assert not sync_to_zotero._is_not_found_exception(
            Exception("Connection timeout")
        )
        assert not sync_to_zotero._is_not_found_exception(
            ValueError("Bad input")
        )
