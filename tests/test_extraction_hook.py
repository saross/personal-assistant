"""
Tests for extraction-hook.py — tag normalisation, transcript parsing,
memory formatting, cursor tracking, and command filtering.

Tests pure functions only; does not call the Anthropic API. The
``TestExtractMemoriesTransientErrors`` and ``TestCursorFileLock``
classes mock the Anthropic SDK and exercise the C2/C3 audit fixes
respectively (2026-05-19).
"""

import json
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import functions under test (conftest.py adds hooks/ to sys.path)
import importlib
import os

# Prevent the hook from creating log dirs in the real PA directory during import
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

# Hook filename uses hyphens — not a valid Python identifier
eh = importlib.import_module("extraction-hook")


# ============================================================================
# Tag Normalisation
# ============================================================================


class TestNormaliseTag:
    """Tests for normalise_tag() — the core folksonomy normaliser."""

    def test_lowercase(self):
        assert eh.normalise_tag("GPS-Accuracy") == "gps-accuracy"

    def test_underscores_to_hyphens(self):
        assert eh.normalise_tag("field_method") == "field-method"

    def test_spaces_to_hyphens(self):
        assert eh.normalise_tag("data quality") == "data-quality"

    def test_strips_special_chars(self):
        assert eh.normalise_tag("tag!@#$%") == "tag"

    def test_collapses_multiple_hyphens(self):
        assert eh.normalise_tag("a--b---c") == "a-b-c"

    def test_strips_leading_trailing_hyphens(self):
        assert eh.normalise_tag("-leading-trailing-") == "leading-trailing"

    def test_combined_normalisation(self):
        assert eh.normalise_tag("  GPS_Accuracy!!  ") == "gps-accuracy"

    def test_empty_string(self):
        assert eh.normalise_tag("") == ""

    def test_already_normalised(self):
        assert eh.normalise_tag("field-method") == "field-method"

    def test_mixed_separators(self):
        assert eh.normalise_tag("open_data quality") == "open-data-quality"


class TestNormaliseTags:
    """Tests for normalise_tags() — batch normalisation with dedup."""

    def test_deduplicates(self):
        result = eh.normalise_tags(["GPS", "gps", "GPS"])
        assert result == ["gps"]

    def test_preserves_order(self):
        result = eh.normalise_tags(["beta", "alpha", "gamma"])
        assert result == ["beta", "alpha", "gamma"]

    def test_dedup_after_normalisation(self):
        # "field_method" and "field-method" normalise to the same tag
        result = eh.normalise_tags(["field_method", "field-method"])
        assert result == ["field-method"]

    def test_filters_empty(self):
        result = eh.normalise_tags(["valid", "", "  ", "also-valid"])
        assert result == ["valid", "also-valid"]

    def test_empty_list(self):
        assert eh.normalise_tags([]) == []


# ============================================================================
# Transcript Parsing
# ============================================================================


def make_transcript_entry(
    role: str, content: str, uuid: str, entry_type: str | None = None
) -> dict:
    """Helper to create a transcript JSONL entry."""
    return {
        "type": entry_type or role,
        "uuid": uuid,
        "message": {"content": content},
    }


class TestParseTranscript:
    """Tests for parse_transcript() — JSONL parsing and cursor logic."""

    def test_parses_all_messages(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        entries = [
            make_transcript_entry("user", "Hello", "uuid-1"),
            make_transcript_entry("assistant", "Hi there", "uuid-2"),
            make_transcript_entry("user", "How are you?", "uuid-3"),
        ]
        with open(transcript, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        messages, last_uuid, _, _ = eh.parse_transcript(str(transcript), None)
        assert len(messages) == 3
        assert last_uuid == "uuid-3"

    def test_resumes_from_cursor(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        entries = [
            make_transcript_entry("user", "Old message", "uuid-1"),
            make_transcript_entry("assistant", "Old reply", "uuid-2"),
            make_transcript_entry("user", "New message", "uuid-3"),
        ]
        with open(transcript, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        messages, last_uuid, _, _ = eh.parse_transcript(str(transcript), "uuid-2")
        assert len(messages) == 1
        assert messages[0]["content"] == "New message"
        assert last_uuid == "uuid-3"

    def test_stale_cursor_reprocesses_all(self, tmp_path):
        """If cursor UUID not found, falls back to full reprocessing."""
        transcript = tmp_path / "transcript.jsonl"
        entries = [
            make_transcript_entry("user", "Message one", "uuid-1"),
            make_transcript_entry("assistant", "Reply one", "uuid-2"),
        ]
        with open(transcript, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        messages, last_uuid, _, _ = eh.parse_transcript(
            str(transcript), "nonexistent-uuid"
        )
        assert len(messages) == 2
        assert last_uuid == "uuid-2"

    def test_skips_non_user_assistant_types(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        entries = [
            {"type": "system", "uuid": "uuid-1", "message": {"content": "sys"}},
            make_transcript_entry("user", "Hello", "uuid-2"),
        ]
        with open(transcript, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        messages, _, _, _ = eh.parse_transcript(str(transcript), None)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_command_marker_filtering(self, tmp_path):
        """Slash command exchanges should be filtered out."""
        transcript = tmp_path / "transcript.jsonl"
        entries = [
            make_transcript_entry("user", "Normal question", "uuid-1"),
            make_transcript_entry("assistant", "Normal answer", "uuid-2"),
            # This user message contains a command marker
            make_transcript_entry(
                "user",
                "# /remember \u2014 Manual Memory Capture\n\nSome content",
                "uuid-3",
            ),
            make_transcript_entry(
                "assistant", "Captured to memory: ...", "uuid-4"
            ),
            make_transcript_entry("user", "Back to normal", "uuid-5"),
        ]
        with open(transcript, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        messages, last_uuid, _, _ = eh.parse_transcript(str(transcript), None)
        assert len(messages) == 3  # uuid-1, uuid-2, uuid-5
        contents = [m["content"] for m in messages]
        assert "Normal question" in contents
        assert "Normal answer" in contents
        assert "Back to normal" in contents
        assert "Captured to memory" not in contents

    def test_all_command_markers_filtered(self, tmp_path):
        """Verify all command markers are filtered."""
        transcript = tmp_path / "transcript.jsonl"
        entries = []
        for i, marker in enumerate(eh.COMMAND_MARKERS):
            entries.append(
                make_transcript_entry("user", marker, f"cmd-{i}")
            )
            entries.append(
                make_transcript_entry("assistant", f"Response {i}", f"resp-{i}")
            )
        # Add one normal exchange
        entries.append(make_transcript_entry("user", "Normal", "normal-1"))

        with open(transcript, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        messages, _, _, _ = eh.parse_transcript(str(transcript), None)
        assert len(messages) == 1
        assert messages[0]["content"] == "Normal"

    # NOTE: a prior test test_skip_flag_resets_on_normal_user_message
    # was removed 2026-05-20 because it pinned the pre-M6-fix behaviour
    # (which let a non-command user entry between a slash command and
    # its response un-skip that response). The new behaviour — flag
    # persists until consumed by the next assistant turn — is exercised
    # by ``test_command_skip_flag_persists_across_user_entries`` further
    # down in this class.


    def test_structured_content_blocks(self, tmp_path):
        """Handles list-of-blocks content format."""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "uuid": "uuid-1",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "Let me think about this..."},
                    {"type": "text", "text": "Here is my answer."},
                ]
            },
        }
        with open(transcript, "w") as f:
            f.write(json.dumps(entry) + "\n")

        messages, _, _, _ = eh.parse_transcript(str(transcript), None)
        assert len(messages) == 1
        assert "[THINKING]:" in messages[0]["content"]
        assert "Here is my answer." in messages[0]["content"]

    def test_empty_transcript(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")

        messages, last_uuid, _, _ = eh.parse_transcript(str(transcript), None)
        assert messages == []
        assert last_uuid is None

    def test_truncates_long_messages(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        long_content = "x" * 10000
        entry = make_transcript_entry("user", long_content, "uuid-1")
        with open(transcript, "w") as f:
            f.write(json.dumps(entry) + "\n")

        messages, _, _, _ = eh.parse_transcript(str(transcript), None)
        assert len(messages[0]["content"]) == eh.MAX_MESSAGE_CHARS

    def test_command_skip_flag_persists_across_user_entries(
        self, tmp_path
    ):
        """The slash-command skip flag must survive an intervening
        non-command user entry (e.g., an MCP tool_result-as-user).

        Pre-M6 fix: the flag was auto-cleared by any non-command user
        entry, so a sequence of:

            user(/remember) -> user(MCP injection) -> assistant(/remember reply)

        would un-skip the assistant turn, producing a sporadic
        double-extraction of the slash-command response.

        Fixed behaviour: the flag clears only when the next assistant
        turn consumes it, regardless of how many user entries arrive
        in between.
        """
        transcript = tmp_path / "transcript.jsonl"
        entries = [
            # Pre-command baseline that should appear in output.
            make_transcript_entry("user", "Normal question", "uuid-1"),
            make_transcript_entry("assistant", "Normal answer", "uuid-2"),
            # Slash-command user entry — sets skip_next_assistant=True.
            make_transcript_entry(
                "user",
                "# /remember — Manual Memory Capture\n\nSave this",
                "uuid-3",
            ),
            # MCP-style intervening user entry. Pre-fix this cleared the
            # flag; post-fix it must not.
            make_transcript_entry(
                "user", "[tool_result] {\"status\":\"ok\"}", "uuid-4",
            ),
            # The actual /remember response — must STILL be skipped.
            make_transcript_entry(
                "assistant",
                "Captured to memory: Save this",
                "uuid-5",
            ),
            # Post-command baseline that should appear.
            make_transcript_entry("user", "Back to normal", "uuid-6"),
        ]
        with open(transcript, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        messages, _, _, _ = eh.parse_transcript(str(transcript), None)
        contents = [m["content"] for m in messages]
        # The /remember response must not appear.
        assert not any(
            "Captured to memory" in c for c in contents
        ), (
            "skip flag was cleared by the intervening user entry; "
            "the /remember response leaked into the extraction batch "
            "(M6 regression)"
        )
        # The MCP-style user entry itself is still emitted — only the
        # assistant response after a command is filtered.
        assert any("tool_result" in c for c in contents)
        # Pre- and post-command baselines preserved.
        assert any("Normal question" in c for c in contents)
        assert any("Normal answer" in c for c in contents)
        assert any("Back to normal" in c for c in contents)


# ============================================================================
# Memory Formatting
# ============================================================================


class TestFormatMemories:
    """Tests for format_memories() — schema validation and ID generation."""

    def test_basic_formatting(self):
        extracted = [
            {
                "category": "decision",
                "content": "Use JSONL for storage.",
                "confidence": "high",
                "research_tags": ["architecture"],
                "source_context": "Design discussion",
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert len(result) == 1
        mem = result[0]
        assert mem["source"] == "extraction"
        assert mem["category"] == "decision"
        assert mem["content"] == "Use JSONL for storage."
        assert mem["confidence"] == "high"
        assert "id" in mem
        assert "created_at" in mem

    def test_invalid_category_defaults_to_context(self):
        extracted = [
            {
                "category": "nonexistent_category",
                "content": "Some content.",
                "confidence": "high",
                "research_tags": [],
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert result[0]["category"] == "context"

    # --- Item 11: write-time anchor quality gate ---------------------------

    def test_malformed_commit_anchor_dropped_good_one_kept(self):
        extracted = [
            {
                "category": "decision",
                "content": "Rome count verified.",
                "confidence": "high",
                "research_tags": [],
                "anchors": [
                    {"type": "commit", "ref": "rome-verification-script"},  # malformed
                    {"type": "commit", "ref": "7078d39"},                   # good
                ],
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert result[0]["anchors"] == [{"type": "commit", "ref": "7078d39"}]

    def test_memory_with_only_malformed_anchor_kept_unanchored(self):
        # A bad anchor must not force-drop the memory itself; it just loses
        # the anchor (better than a memory stuck at verified=false).
        extracted = [
            {
                "category": "decision",
                "content": "Some fine content.",
                "confidence": "high",
                "research_tags": [],
                "anchors": [{"type": "commit", "ref": "audit-corrections-applied"}],
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert len(result) == 1
        assert "anchors" not in result[0]

    def test_wellformed_anchors_pass_through_with_line(self):
        extracted = [
            {
                "category": "decision",
                "content": "x",
                "confidence": "high",
                "research_tags": [],
                "anchors": [{"type": "file", "ref": "scripts/anchor_verify.py", "line": 42}],
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert result[0]["anchors"] == [
            {"type": "file", "ref": "scripts/anchor_verify.py", "line": 42}
        ]

    def test_invalid_confidence_defaults_to_medium(self):
        extracted = [
            {
                "category": "decision",
                "content": "Some content.",
                "confidence": "very-high",
                "research_tags": [],
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert result[0]["confidence"] == "medium"

    def test_tags_normalised(self):
        extracted = [
            {
                "category": "decision",
                "content": "Some content.",
                "confidence": "high",
                "research_tags": ["GPS_Accuracy", "Field Method"],
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert result[0]["research_tags"] == ["gps-accuracy", "field-method"]

    def test_string_tags_handled(self):
        """Haiku sometimes returns a single string instead of array."""
        extracted = [
            {
                "category": "decision",
                "content": "Some content.",
                "confidence": "high",
                "research_tags": "single-tag",
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert result[0]["research_tags"] == ["single-tag"]

    def test_optional_fields_included_when_present(self):
        extracted = [
            {
                "category": "source_insight",
                "content": "Smith 2024 reports GPS degradation.",
                "confidence": "high",
                "research_tags": ["gps-accuracy"],
                "zotero_key": "ABC123",
                "deadline_at": "2026-02-28T00:00:00+00:00",
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert result[0]["zotero_key"] == "ABC123"
        assert result[0]["deadline_at"] == "2026-02-28T00:00:00+00:00"

    def test_optional_fields_omitted_when_absent(self):
        extracted = [
            {
                "category": "decision",
                "content": "Some content.",
                "confidence": "high",
                "research_tags": [],
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert "zotero_key" not in result[0]
        assert "deadline_at" not in result[0]

    def test_skips_empty_content(self):
        extracted = [
            {"category": "decision", "content": "", "confidence": "high",
             "research_tags": []},
            {"category": "decision", "content": "Real content.",
             "confidence": "high", "research_tags": []},
        ]
        result = eh.format_memories(extracted, "test-session")
        assert len(result) == 1

    def test_unique_ids(self):
        extracted = [
            {"category": "decision", "content": f"Memory {i}.",
             "confidence": "high", "research_tags": []}
            for i in range(5)
        ]
        result = eh.format_memories(extracted, "test-session")
        ids = [m["id"] for m in result]
        assert len(set(ids)) == 5  # All unique

    def test_all_valid_categories_accepted(self):
        """Every category in VALID_CATEGORIES should pass validation."""
        for cat in eh.VALID_CATEGORIES:
            extracted = [
                {"category": cat, "content": f"Test {cat}.",
                 "confidence": "high", "research_tags": []}
            ]
            result = eh.format_memories(extracted, "test-session")
            assert result[0]["category"] == cat

    def test_summary_included_when_present(self):
        """Summary field is included in the record when Haiku provides it."""
        extracted = [
            {
                "category": "decision",
                "content": "We chose PostgreSQL for the query layer because "
                           "it supports full-text search and tag analytics.",
                "summary": "Chose PostgreSQL for full-text search and tag analytics.",
                "confidence": "high",
                "research_tags": ["architecture"],
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert result[0]["summary"] == (
            "Chose PostgreSQL for full-text search and tag analytics."
        )

    def test_summary_omitted_when_absent(self):
        """Summary field is omitted from the record when not provided."""
        extracted = [
            {
                "category": "decision",
                "content": "Some content.",
                "confidence": "high",
                "research_tags": [],
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert "summary" not in result[0]

    def test_source_message_uuid_propagated(self):
        """When provided, source_message_uuid lands on every record.

        Provenance audit Gap 1 (2026-05-17): the UUID of the last
        transcript message included in the extraction batch is the
        tier-3 verifier's anchor when mechanical anchor matching
        fails. Every memory in a batch shares the same UUID — the
        verifier uses it to seek directly into the archived
        transcript rather than re-grepping the whole file.
        """
        extracted = [
            {
                "category": "decision",
                "content": "First memory.",
                "confidence": "high",
                "research_tags": [],
            },
            {
                "category": "progress",
                "content": "Second memory.",
                "confidence": "medium",
                "research_tags": [],
            },
        ]
        result = eh.format_memories(
            extracted,
            "test-session",
            source_message_uuid="msg-uuid-42",
        )
        assert len(result) == 2
        assert result[0]["source_message_uuid"] == "msg-uuid-42"
        assert result[1]["source_message_uuid"] == "msg-uuid-42"

    def test_source_message_uuid_omitted_when_none(self):
        """No source_message_uuid argument → field absent from record.

        Keeps the field optional, matching the schema-side default of
        NULL and avoiding spurious empty strings in legacy reads.
        """
        extracted = [
            {
                "category": "decision",
                "content": "Some content.",
                "confidence": "high",
                "research_tags": [],
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert "source_message_uuid" not in result[0]

    def test_source_message_uuid_omitted_when_empty_string(self):
        """Empty string source_message_uuid → field omitted, not stored.

        An empty UUID is not a valid anchor and would only mislead the
        verifier. Treat it the same as ``None``.
        """
        extracted = [
            {
                "category": "decision",
                "content": "Some content.",
                "confidence": "high",
                "research_tags": [],
            }
        ]
        result = eh.format_memories(
            extracted, "test-session", source_message_uuid=""
        )
        assert "source_message_uuid" not in result[0]

    def test_extractor_model_id_defaults_to_haiku_constant(self):
        """v3 (Gap 3): every record carries the HAIKU_MODEL value by default.

        Provenance audit Gap 3 (2026-05-17): the extractor model ID is
        emitted into every memory record for RO-Crate attribution and
        for invalidation passes after a Haiku regression. Defaults to
        the module-level ``HAIKU_MODEL`` constant — the same value the
        Anthropic API call uses, so the record and the call site are
        guaranteed to agree.
        """
        extracted = [
            {
                "category": "decision",
                "content": "Some content.",
                "confidence": "high",
                "research_tags": [],
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert result[0]["extractor_model_id"] == eh.HAIKU_MODEL

    def test_extractor_model_id_override(self):
        """Explicit extractor_model_id overrides the HAIKU_MODEL default.

        Lets re-extraction tools (e.g. a future bake-off harness)
        attribute their records to a model other than the one the live
        hook is currently configured for.
        """
        extracted = [
            {
                "category": "decision",
                "content": "Some content.",
                "confidence": "high",
                "research_tags": [],
            }
        ]
        result = eh.format_memories(
            extracted,
            "test-session",
            extractor_model_id="claude-haiku-5-0-future",
        )
        assert result[0]["extractor_model_id"] == "claude-haiku-5-0-future"

    def test_licence_defaults_to_none(self):
        """v3 (Gap 3): licence is None by default (RO-Crate user opt-in).

        Provenance audit Gap 3 (2026-05-17): RO-Crate requires a
        licence string on shared records but none has been set
        project-wide. Default to ``None`` so the user explicitly opts
        in to a licence at the moment the record becomes shareable.
        """
        extracted = [
            {
                "category": "decision",
                "content": "Some content.",
                "confidence": "high",
                "research_tags": [],
            }
        ]
        result = eh.format_memories(extracted, "test-session")
        assert "licence" in result[0]
        assert result[0]["licence"] is None

    def test_licence_explicit_override(self):
        """An explicit licence string lands on every record in the batch."""
        extracted = [
            {
                "category": "decision",
                "content": "First.",
                "confidence": "high",
                "research_tags": [],
            },
            {
                "category": "progress",
                "content": "Second.",
                "confidence": "medium",
                "research_tags": [],
            },
        ]
        result = eh.format_memories(
            extracted, "test-session", licence="CC-BY-4.0"
        )
        assert result[0]["licence"] == "CC-BY-4.0"
        assert result[1]["licence"] == "CC-BY-4.0"


# ============================================================================
# Cursor Tracking
# ============================================================================


class TestCursorTracking:
    """Tests for load_cursor() and save_cursor()."""

    def test_load_missing_cursor(self, tmp_path, monkeypatch):
        monkeypatch.setattr(eh, "CURSOR_FILE", tmp_path / "cursor.json")
        assert eh.load_cursor() == {}

    def test_roundtrip(self, tmp_path, monkeypatch):
        cursor_file = tmp_path / "cursor.json"
        monkeypatch.setattr(eh, "CURSOR_FILE", cursor_file)

        eh.save_cursor({"session-1": "uuid-42"})
        loaded = eh.load_cursor()
        assert loaded == {"session-1": "uuid-42"}

    def test_corrupt_cursor_returns_empty(self, tmp_path, monkeypatch):
        cursor_file = tmp_path / "cursor.json"
        cursor_file.write_text("not valid json{{{")
        monkeypatch.setattr(eh, "CURSOR_FILE", cursor_file)

        assert eh.load_cursor() == {}


# ============================================================================
# Vocabulary Loading
# ============================================================================


class TestSeedTags:
    """Tests for load_seed_tags() and update_vocabulary()."""

    def test_loads_from_file(self, tmp_path, monkeypatch):
        vocab = tmp_path / "tags.txt"
        vocab.write_text("# Comment\nfield-method\ndata-quality\n\ngps-accuracy\n")
        monkeypatch.setattr(eh, "VOCABULARY_FILE", vocab)

        tags = eh.load_seed_tags()
        assert "field-method" in tags
        assert "data-quality" in tags
        assert "gps-accuracy" in tags
        # Comments and blank lines excluded
        assert "# Comment" not in tags
        assert "" not in tags

    def test_fallback_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(eh, "VOCABULARY_FILE", tmp_path / "nonexistent.txt")
        tags = eh.load_seed_tags()
        assert len(tags) > 0  # Fallback list
        assert "field-method" in tags

    def test_update_adds_novel_tags(self, tmp_path, monkeypatch):
        vocab = tmp_path / "tags.txt"
        vocab.write_text("existing-tag\n")
        monkeypatch.setattr(eh, "VOCABULARY_FILE", vocab)

        eh.update_vocabulary(["existing-tag", "new-tag"])

        content = vocab.read_text()
        assert "new-tag" in content
        # Existing tag not duplicated
        assert content.count("existing-tag") == 1


# ============================================================================
# C2 (2026-05-19): Transient vs permanent Anthropic API errors
# ============================================================================


def _long_conversation() -> list[dict]:
    """Build a conversation long enough to clear MIN_CONTENT_LENGTH."""
    # MIN_CONTENT_LENGTH is 500; pack a single message well past that.
    return [{"role": "user", "content": "x" * 800, "uuid": "u1"}]


def _make_api_status_error(status_code: int) -> Exception:
    """Build an ``anthropic.APIStatusError`` with the given status_code.

    We avoid invoking the real constructor (which insists on an
    ``httpx.Response``) by setting the attribute on a bare instance.
    Acceptable for unit-test purposes — the production code paths only
    read ``status_code``.
    """
    import anthropic

    err = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
    Exception.__init__(err, f"status {status_code}")
    err.status_code = status_code
    return err


class _StringIO:
    """Minimal stdin replacement for main() — only ``read()`` is used."""

    def __init__(self, payload: str) -> None:
        self._payload = payload

    def read(self) -> str:
        return self._payload


class TestExtractMemoriesTransientErrors:
    """C2: transient API errors must return None, not [].

    The cursor-advance decision in ``main()`` depends on this:
    ``None`` means do-not-advance (retry-worthy), ``[]`` means advance
    (API succeeded or input was hopeless).
    """

    def test_internal_server_error_returns_none(self):
        """A 5xx (overload, 529) is transient — return None."""
        with patch.object(eh, "load_seed_tags", return_value=["tag1"]):
            with patch("anthropic.Anthropic") as mock_cls:
                mock_client = MagicMock()
                mock_client.messages.create.side_effect = _make_api_status_error(529)
                mock_cls.return_value = mock_client
                result = eh.extract_memories(_long_conversation(), "sess-1")
        assert result is None

    def test_rate_limit_429_returns_none(self):
        """429 rate-limit is transient — return None."""
        with patch.object(eh, "load_seed_tags", return_value=["tag1"]):
            with patch("anthropic.Anthropic") as mock_cls:
                mock_client = MagicMock()
                mock_client.messages.create.side_effect = _make_api_status_error(429)
                mock_cls.return_value = mock_client
                result = eh.extract_memories(_long_conversation(), "sess-1")
        assert result is None

    def test_400_permanent_returns_empty_list(self):
        """A 4xx other than 429 is permanent — return [] (advance cursor)."""
        with patch.object(eh, "load_seed_tags", return_value=["tag1"]):
            with patch("anthropic.Anthropic") as mock_cls:
                mock_client = MagicMock()
                mock_client.messages.create.side_effect = _make_api_status_error(400)
                mock_cls.return_value = mock_client
                result = eh.extract_memories(_long_conversation(), "sess-1")
        assert result == []

    def test_timeout_returns_none(self):
        """Network timeout is transient — return None."""
        import anthropic

        # APITimeoutError takes a request arg; bypass via __new__ to keep
        # the test independent of SDK constructor details.
        timeout = anthropic.APITimeoutError.__new__(anthropic.APITimeoutError)
        Exception.__init__(timeout, "timed out")
        with patch.object(eh, "load_seed_tags", return_value=["tag1"]):
            with patch("anthropic.Anthropic") as mock_cls:
                mock_client = MagicMock()
                mock_client.messages.create.side_effect = timeout
                mock_cls.return_value = mock_client
                result = eh.extract_memories(_long_conversation(), "sess-1")
        assert result is None

    def test_connection_error_returns_none(self):
        """SDK-level connection error is transient — return None."""
        import anthropic

        conn_err = anthropic.APIConnectionError.__new__(anthropic.APIConnectionError)
        Exception.__init__(conn_err, "connection refused")
        with patch.object(eh, "load_seed_tags", return_value=["tag1"]):
            with patch("anthropic.Anthropic") as mock_cls:
                mock_client = MagicMock()
                mock_client.messages.create.side_effect = conn_err
                mock_cls.return_value = mock_client
                result = eh.extract_memories(_long_conversation(), "sess-1")
        assert result is None

    def test_unknown_exception_returns_empty_list(self):
        """A non-Anthropic exception is treated as permanent — return []."""
        with patch.object(eh, "load_seed_tags", return_value=["tag1"]):
            with patch("anthropic.Anthropic") as mock_cls:
                mock_client = MagicMock()
                mock_client.messages.create.side_effect = RuntimeError("bug")
                mock_cls.return_value = mock_client
                result = eh.extract_memories(_long_conversation(), "sess-1")
        assert result == []

    def test_main_does_not_advance_cursor_on_transient_error(
        self, tmp_path, monkeypatch
    ):
        """End-to-end: a transient API failure must leave the cursor unchanged.

        Constructs a tiny transcript, mocks the Anthropic client to
        raise a 529, runs main(), and asserts the cursor file is
        unchanged afterwards.
        """
        # Stage a transcript with two messages
        transcript = tmp_path / "transcript.jsonl"
        entries = [
            make_transcript_entry("user", "x" * 800, "uuid-A"),
            make_transcript_entry("assistant", "y" * 800, "uuid-B"),
        ]
        with open(transcript, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        # Redirect cursor / memories / vocab to tmp_path so we don't
        # touch the live PA state during the test.
        cursor_file = tmp_path / "cursor.json"
        monkeypatch.setattr(eh, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(eh, "MEMORIES_FILE", tmp_path / "memories.jsonl")
        monkeypatch.setattr(eh, "VOCABULARY_FILE", tmp_path / "tags.txt")
        monkeypatch.setattr(eh, "load_env", lambda: None)

        hook_payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "sess-X"}
        )
        monkeypatch.setattr("sys.stdin", _StringIO(hook_payload))

        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = _make_api_status_error(529)
            mock_cls.return_value = mock_client
            eh.main()

        # Cursor file must NOT contain an entry for sess-X (we never
        # advanced past the transient failure).
        if cursor_file.exists():
            saved = json.loads(cursor_file.read_text())
            assert "sess-X" not in saved, (
                "transient API failure must not advance cursor; "
                f"found {saved!r}"
            )

    def test_main_advances_cursor_on_permanent_error(
        self, tmp_path, monkeypatch
    ):
        """Permanent API errors advance the cursor (no infinite reprocessing)."""
        transcript = tmp_path / "transcript.jsonl"
        entries = [
            make_transcript_entry("user", "x" * 800, "uuid-A"),
        ]
        with open(transcript, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        cursor_file = tmp_path / "cursor.json"
        monkeypatch.setattr(eh, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(eh, "MEMORIES_FILE", tmp_path / "memories.jsonl")
        monkeypatch.setattr(eh, "VOCABULARY_FILE", tmp_path / "tags.txt")
        monkeypatch.setattr(eh, "load_env", lambda: None)

        hook_payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "sess-Y"}
        )
        monkeypatch.setattr("sys.stdin", _StringIO(hook_payload))

        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = _make_api_status_error(400)
            mock_cls.return_value = mock_client
            eh.main()

        # Empty list → cursor advances to the last seen UUID.
        assert cursor_file.exists()
        saved = json.loads(cursor_file.read_text())
        assert saved.get("sess-Y") == "uuid-A"


# ============================================================================
# C3 (2026-05-19): Cursor file flock — concurrent main() invocations
# ============================================================================


class TestCursorFileLock:
    """Verify ``cursor_file_lock`` serialises concurrent mutators.

    Stop / PreCompact / SessionEnd hooks all fire close together on
    session-close; without flock, the last writer wins and the cursor
    lags the JSONL.
    """

    def test_lock_serialises_concurrent_writers(self, tmp_path, monkeypatch):
        """Five threads each appending one line under the lock — no losses.

        Simulates the load-mutate-save race that motivated C3. The
        critical section reads the file, appends, and writes back;
        without serialisation a thread that reads before another's
        write will overwrite it.
        """
        target = tmp_path / "cursor.json"
        monkeypatch.setattr(eh, "CURSOR_FILE", target)
        # Seed an empty dict.
        target.write_text("{}")

        n_threads = 5
        barrier = threading.Barrier(n_threads)
        errors: list[BaseException] = []

        def worker(idx: int) -> None:
            try:
                barrier.wait(timeout=5)
                with eh.cursor_file_lock():
                    current = json.loads(target.read_text())
                    # Simulated processing window — long enough that
                    # an unlocked race would clobber.
                    import time as _t
                    _t.sleep(0.02)
                    current[f"sess-{idx}"] = f"uuid-{idx}"
                    target.write_text(json.dumps(current))
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(i,)) for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"worker errors: {errors!r}"
        saved = json.loads(target.read_text())
        # Every worker's mutation must have landed.
        for i in range(n_threads):
            assert saved.get(f"sess-{i}") == f"uuid-{i}", (
                f"lost write from worker {i}; final state: {saved!r}"
            )


# ============================================================================
# P10: max_tokens truncation salvage
# ============================================================================


class TestSalvageTruncatedArray:
    """_salvage_truncated_array recovers the complete prefix of a cut-off array."""

    def test_complete_array_returns_all(self):
        text = '[{"content": "a"}, {"content": "b"}, {"content": "c"}]'
        assert eh._salvage_truncated_array(text) == [
            {"content": "a"}, {"content": "b"}, {"content": "c"}
        ]

    def test_truncated_mid_string_keeps_complete_prefix(self):
        # Two complete objects, then a third cut off mid-string.
        text = '[{"content": "a"}, {"content": "b"}, {"content": "cccc'
        assert eh._salvage_truncated_array(text) == [
            {"content": "a"}, {"content": "b"}
        ]

    def test_truncated_mid_object_keeps_prefix(self):
        # Cut off mid-key of the second object.
        text = '[{"content": "a"}, {"cat'
        assert eh._salvage_truncated_array(text) == [{"content": "a"}]

    def test_first_object_truncated_returns_empty(self):
        text = '[{"content": "aaaa'
        assert eh._salvage_truncated_array(text) == []

    def test_open_bracket_only(self):
        assert eh._salvage_truncated_array("[") == []

    def test_empty_array(self):
        assert eh._salvage_truncated_array("[]") == []

    def test_non_array_returns_empty(self):
        assert eh._salvage_truncated_array('{"content": "a"}') == []
        assert eh._salvage_truncated_array("garbage") == []

    def test_whitespace_and_newlines_between_objects(self):
        text = '[\n  {"content": "a"},\n  {"content": "b"},\n  {"content": "tr'
        assert eh._salvage_truncated_array(text) == [
            {"content": "a"}, {"content": "b"}
        ]

    def test_non_dict_elements_filtered(self):
        text = '[{"content": "a"}, "loose string", {"content": "b"}, {"c'
        assert eh._salvage_truncated_array(text) == [
            {"content": "a"}, {"content": "b"}
        ]


class TestTruncationRouting:
    """A max_tokens stop_reason routes to salvage instead of dropping the window."""

    @staticmethod
    def _mock_response(text: str, stop_reason: str):
        block = MagicMock()
        block.text = text
        resp = MagicMock()
        resp.content = [block]
        resp.stop_reason = stop_reason
        return resp

    def test_truncated_response_is_salvaged_not_dropped(self):
        truncated = '[{"category": "progress", "content": "a"}, {"category": "tru'
        with patch.object(eh, "load_seed_tags", return_value=["tag1"]):
            with patch("anthropic.Anthropic") as mock_cls:
                mock_client = MagicMock()
                mock_client.messages.create.return_value = self._mock_response(
                    truncated, "max_tokens"
                )
                mock_cls.return_value = mock_client
                result = eh.extract_memories(_long_conversation(), "sess-trunc")
        # Pre-P10 this returned [] (whole window lost); now the one complete
        # object is recovered.
        assert result == [{"category": "progress", "content": "a"}]

    def test_complete_response_unaffected(self):
        complete = '[{"category": "progress", "content": "a"}]'
        with patch.object(eh, "load_seed_tags", return_value=["tag1"]):
            with patch("anthropic.Anthropic") as mock_cls:
                mock_client = MagicMock()
                mock_client.messages.create.return_value = self._mock_response(
                    complete, "end_turn"
                )
                mock_cls.return_value = mock_client
                result = eh.extract_memories(_long_conversation(), "sess-ok")
        assert result == [{"category": "progress", "content": "a"}]


# ============================================================================
# Audit round two (2026-09-08): H11, H13, H16
# ============================================================================


class TestAuditRoundTwo:
    def test_tool_only_assistant_entry_does_not_consume_the_skip_flag(self, tmp_path):
        """H11: the command response is often split into a tool-use-only entry
        (empty text) followed by the text-bearing one; only the latter is skipped."""
        marker = next(m for m in eh.COMMAND_MARKERS if m.startswith("# /"))
        transcript = tmp_path / "t.jsonl"
        entries = [
            make_transcript_entry("user", marker + "\nrun it", "u1"),
            {"type": "assistant", "uuid": "a-tool",
             "message": {"content": [{"type": "tool_use", "name": "x", "input": {}}]}},
            make_transcript_entry("assistant", "Here is the command response text", "a-text"),
            make_transcript_entry("user", "thanks, unrelated follow-up question here", "u2"),
            make_transcript_entry("assistant", "an ordinary answer that must survive", "a2"),
        ]
        transcript.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        messages, _, _, _ = eh.parse_transcript(str(transcript), None)
        texts = [m["content"] for m in messages]
        assert "Here is the command response text" not in texts
        assert "an ordinary answer that must survive" in texts

    def test_too_short_window_returns_none_so_the_cursor_holds(self):
        """H16: a too-short window is neither success nor sterile; it must accumulate."""
        with patch("anthropic.Anthropic") as mock_cls:
            result = eh.extract_memories([{"role": "user", "content": "hi"}], "s")
        assert result is None
        mock_cls.assert_not_called()

    def test_recent_seed_tags_come_from_the_newest_records(self, tmp_path, monkeypatch):
        """H13: seed tags are the most common tags in recent records, not the
        alphabetical head of the vocabulary file."""
        store = tmp_path / "memories.jsonl"
        lines = ["partial-first-line-is-ignored"]
        for i in range(40):
            tags = ["common-tag", "rare-%d" % i] if i % 2 else ["common-tag", "second-tag"]
            lines.append(json.dumps({"id": str(i), "research_tags": tags}))
        store.write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(eh, "MEMORIES_FILE", store)
        seeds = eh.recent_seed_tags(3)
        assert seeds[0] == "common-tag" and seeds[1] == "second-tag" and len(seeds) == 3
        monkeypatch.setattr(eh, "MEMORIES_FILE", tmp_path / "absent.jsonl")
        vocab = tmp_path / "vocab.txt"
        vocab.write_text("aaa\nbbb\n")
        monkeypatch.setattr(eh, "VOCABULARY_FILE", vocab)
        assert eh.recent_seed_tags(5) == ["aaa", "bbb"]          # fallback

    def test_vocabulary_is_untouched_when_the_append_fails(
        self, tmp_path, monkeypatch
    ):
        """H18, behaviourally: the vocabulary is written only after the append.

        Kills moving ``update_vocabulary(new_tags)`` above
        ``append_memories(memories)`` in main(), and kills reinstating the
        ``update_vocabulary`` call inside ``format_memories`` — either puts
        the window's tags in the shared vocabulary for memories that were
        never persisted, so the vocabulary claims tags no record carries.

        Replaces an ``inspect.getsource`` string assertion (audit round two
        M6), which passed for any rename or reordering that kept the literal
        text.
        """
        transcript, cursor_file, _ = _stage_main_paths(tmp_path, monkeypatch)
        vocab = tmp_path / "tag-vocabulary.txt"
        vocab.write_text("existing-tag\n", encoding="utf-8")
        monkeypatch.setattr(eh, "VOCABULARY_FILE", vocab)
        # A regular file where the store's parent directory must be, so the
        # append raises before any vocabulary work could legitimately run.
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(eh, "MEMORIES_FILE", blocker / "sub" / "memories.jsonl")

        payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "sess-V"}
        )
        monkeypatch.setattr("sys.stdin", _StringIO(payload))
        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _mock_extraction_response(
                _ONE_MEMORY_JSON
            )
            mock_cls.return_value = mock_client
            with pytest.raises(SystemExit):
                eh.main()

        assert vocab.read_text(encoding="utf-8") == "existing-tag\n", (
            "the vocabulary gained tags from memories that were never written"
        )

    def test_vocabulary_records_the_tags_of_a_successful_append(
        self, tmp_path, monkeypatch
    ):
        """The other half: after a good append the tags DO land.

        Kills ``update_vocabulary(new_tags)`` -> ``pass``, which the
        ordering test above cannot see on its own.
        """
        transcript, _, _ = _stage_main_paths(tmp_path, monkeypatch)
        vocab = tmp_path / "tag-vocabulary.txt"
        vocab.write_text("existing-tag\n", encoding="utf-8")
        monkeypatch.setattr(eh, "VOCABULARY_FILE", vocab)

        payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "sess-W"}
        )
        monkeypatch.setattr("sys.stdin", _StringIO(payload))
        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _mock_extraction_response(
                _ONE_MEMORY_JSON
            )
            mock_cls.return_value = mock_client
            eh.main()

        text = vocab.read_text(encoding="utf-8")
        assert "existing-tag" in text
        assert "audit-round-two" in text


class TestCursorPruning:
    """Audit round two M6: ``save_cursor``'s prune had no coverage."""

    def test_an_overflowing_cursor_is_pruned_to_the_cap(self, tmp_path, monkeypatch):
        """Kills ``for key in keys[:len(keys) - MAX_CURSOR_ENTRIES]`` -> ``keys``.

        The mutation deletes EVERY entry, so every live session reparses its
        whole transcript on the next firing. Nothing asserted the size, so it
        survived.
        """
        target = tmp_path / "cursor.json"
        monkeypatch.setattr(eh, "CURSOR_FILE", target)
        overflow = 20
        cursor = {
            f"sess-{i:04d}": f"uuid-{i:04d}"
            for i in range(eh.MAX_CURSOR_ENTRIES + overflow)
        }
        eh.save_cursor(cursor)

        saved = json.loads(target.read_text(encoding="utf-8"))
        assert len(saved) == eh.MAX_CURSOR_ENTRIES
        # The prune keeps the tail of insertion order — the newest sessions.
        assert "sess-0000" not in saved
        assert f"sess-{overflow:04d}" in saved
        last = eh.MAX_CURSOR_ENTRIES + overflow - 1
        assert saved[f"sess-{last:04d}"] == f"uuid-{last:04d}"

    def test_a_cursor_exactly_at_the_cap_is_not_pruned(self, tmp_path, monkeypatch):
        """Kills a prune that drops a session while still at the cap.

        Specifically ``keys[:len(keys) - MAX_CURSOR_ENTRIES + 1]``: the
        dropped session reprocesses its entire transcript on the next
        firing.

        Note the honest limit: ``>`` -> ``>=`` on the guard above is an
        EQUIVALENT mutant, not a surviving one. At exactly the cap the
        slice is empty either way, so no test can distinguish them.
        """
        target = tmp_path / "cursor.json"
        monkeypatch.setattr(eh, "CURSOR_FILE", target)
        cursor = {
            f"sess-{i:04d}": f"uuid-{i:04d}"
            for i in range(eh.MAX_CURSOR_ENTRIES)
        }
        eh.save_cursor(cursor)

        saved = json.loads(target.read_text(encoding="utf-8"))
        assert len(saved) == eh.MAX_CURSOR_ENTRIES
        assert saved["sess-0000"] == "uuid-0000"

    def test_the_cursor_is_written_atomically(self, tmp_path, monkeypatch):
        """Kills ``tmp.rename(CURSOR_FILE)`` -> ``CURSOR_FILE.write_text(...)``.

        A crash mid-write would otherwise leave a truncated cursor, which
        ``load_cursor`` reads as empty — every session reparsed from the top.
        The temp file must not survive the write either.
        """
        target = tmp_path / "cursor.json"
        monkeypatch.setattr(eh, "CURSOR_FILE", target)
        renames: list[tuple[str, str]] = []
        real_rename = type(target).rename

        def _tracking_rename(self, dest):
            renames.append((str(self), str(dest)))
            return real_rename(self, dest)

        monkeypatch.setattr(type(target), "rename", _tracking_rename)
        eh.save_cursor({"sess-A": "uuid-A"})

        assert renames == [(str(target.with_suffix(".tmp")), str(target))]
        assert json.loads(target.read_text(encoding="utf-8")) == {"sess-A": "uuid-A"}
        assert not target.with_suffix(".tmp").exists()


# ============================================================================
# Audit round two, Lens B (2026-09-08): H5 (persistence path), H21 (flock
# wiring in main), H22 (transcript-shape fidelity)
# ============================================================================


def make_live_shape_entry(
    role: str,
    content: str | list,
    uuid: str,
    *,
    is_meta: bool = False,
    is_sidechain: bool = False,
) -> dict:
    """Build a transcript entry carrying the keys a live transcript carries.

    ``make_transcript_entry`` above emits the three keys the parser reads
    (``type``, ``uuid``, ``message``), which is why the ``isMeta`` /
    ``isSidechain`` blindness of audit H22 was invisible to the suite. The
    key set here was measured (2026-09-08) from the entries under
    ``~/.claude/projects/-home-shawn-personal-assistant``: every ``user``
    and ``assistant`` entry carries ``cwd``, ``entrypoint``, ``gitBranch``,
    ``isSidechain``, ``message``, ``parentUuid``, ``sessionId``,
    ``timestamp``, ``type``, ``userType``, ``uuid``, and ``version``, and a
    harness-injected entry adds ``isMeta``. Only the SHAPE is reproduced —
    every value below is synthetic.
    """
    return {
        "type": role,
        "uuid": uuid,
        "parentUuid": None,
        "sessionId": "00000000-0000-0000-0000-000000000000",
        "timestamp": "2026-09-08T00:00:00.000Z",
        "cwd": "/home/shawn/personal-assistant",
        "gitBranch": "main",
        "entrypoint": "cli",
        "userType": "external",
        "version": "0.0.0",
        "isMeta": is_meta,
        "isSidechain": is_sidechain,
        "message": {"role": role, "content": content},
    }


def _write_transcript(path: Path, entries: list[dict]) -> None:
    """Write JSONL entries to *path*, one compact object per line."""
    path.write_text(
        "".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8"
    )


def _mock_extraction_response(payload: str):
    """Build a mock Anthropic response carrying *payload* as its only text."""
    block = MagicMock()
    block.text = payload
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "end_turn"
    return resp


# One extracted memory, in the shape ``format_memories`` expects. Anchor-less
# on purpose: ``anchor_verify.verify_memory`` short-circuits to None without
# anchors, so no git subprocess is spawned by these tests.
_ONE_MEMORY_JSON = json.dumps(
    [
        {
            "category": "decision",
            "content": "Pinned the persistence path with an end-to-end test.",
            "summary": "Persistence path pinned.",
            "confidence": "high",
            "research_tags": ["audit-round-two"],
        }
    ]
)


def _stage_main_paths(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    """Redirect every file ``main()`` writes into *tmp_path*.

    Returns ``(transcript, cursor_file, memories_file)``. The transcript
    holds one user turn long enough to clear ``MIN_CONTENT_LENGTH``.
    ``repo_set_for`` is stubbed to an empty repo set so anchor verification
    does no filesystem discovery outside the temporary directory.
    """
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(
        transcript,
        [make_live_shape_entry("user", "decide: " + "x" * 800, "uuid-A")],
    )
    cursor_file = tmp_path / "cursor.json"
    memories_file = tmp_path / "memories.jsonl"
    monkeypatch.setattr(eh, "CURSOR_FILE", cursor_file)
    monkeypatch.setattr(eh, "MEMORIES_FILE", memories_file)
    monkeypatch.setattr(eh, "VOCABULARY_FILE", tmp_path / "tags.txt")
    monkeypatch.setattr(eh, "load_env", lambda: None)
    monkeypatch.setattr(eh, "repo_set_for", lambda project: [])
    return transcript, cursor_file, memories_file


class TestAppendMemories:
    """H5: the append path itself — no test called it before 2026-09-08."""

    def test_append_preserves_the_existing_store(self, tmp_path, monkeypatch):
        """Kills ``with open(MEMORIES_FILE, "wb") as fh`` in append_memories.

        The mutation truncates the ~42k-record canonical store on every
        session close. Seeding a prior record and asserting it survives —
        and that the file grew by exactly the encoded payload — is what
        makes truncation visible.
        """
        store = tmp_path / "memories.jsonl"
        seed = json.dumps({"id": "seed-1", "content": "already here"}) + "\n"
        store.write_text(seed, encoding="utf-8")
        monkeypatch.setattr(eh, "MEMORIES_FILE", store)

        new = [{"id": "new-1", "content": "appended"}]
        eh.append_memories(new)

        text = store.read_text(encoding="utf-8")
        assert text.startswith(seed), "the pre-existing store was truncated"
        expected = json.dumps(new[0]) + "\n"
        assert text == seed + expected
        assert store.stat().st_size == len((seed + expected).encode("utf-8"))

    def test_append_is_a_no_op_for_an_empty_list(self, tmp_path, monkeypatch):
        """Kills ``if not memories: return`` → falling through to os.write.

        An empty append must not even create the file — the hook fires on
        every session close, most of which extract nothing.
        """
        store = tmp_path / "memories.jsonl"
        monkeypatch.setattr(eh, "MEMORIES_FILE", store)
        eh.append_memories([])
        assert not store.exists()

    def test_append_creates_the_store_and_its_parent(self, tmp_path, monkeypatch):
        """Kills ``target_path.parent.mkdir(parents=True, exist_ok=True)``.

        First run on a fresh clone has no ``memories/`` directory; without
        the mkdir the very first extraction raises and is lost.
        """
        store = tmp_path / "memories" / "memories.jsonl"
        monkeypatch.setattr(eh, "MEMORIES_FILE", store)
        eh.append_memories([{"id": "first", "content": "x"}])
        assert json.loads(store.read_text(encoding="utf-8"))["id"] == "first"


class TestMainPersistsAndAdvances:
    """H5: a *successful* main() — bytes appended, cursor advanced."""

    def test_main_appends_the_extracted_memories(self, tmp_path, monkeypatch):
        """Kills ``append_memories(memories)`` → ``pass`` in main().

        Also kills the truncating-append mutation: the seeded record must
        still be in the store afterwards. Nothing in the suite asserted a
        byte reached ``memories.jsonl`` before this test.
        """
        transcript, cursor_file, store = _stage_main_paths(tmp_path, monkeypatch)
        seed = json.dumps({"id": "seed-1", "content": "already here"}) + "\n"
        store.write_text(seed, encoding="utf-8")

        payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "sess-P"}
        )
        monkeypatch.setattr("sys.stdin", _StringIO(payload))

        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _mock_extraction_response(
                _ONE_MEMORY_JSON
            )
            mock_cls.return_value = mock_client
            eh.main()

        lines = store.read_text(encoding="utf-8").splitlines()
        assert lines[0] == seed.rstrip("\n"), "the store was rewritten, not appended"
        assert len(lines) == 2, f"expected one appended record, got {lines[1:]}"
        record = json.loads(lines[1])
        assert record["content"] == (
            "Pinned the persistence path with an end-to-end test."
        )
        assert record["session_id"] == "sess-P"
        # Cursor advanced only because the append succeeded.
        assert json.loads(cursor_file.read_text())["sess-P"] == "uuid-A"

    def test_main_holds_the_cursor_when_the_append_fails(self, tmp_path, monkeypatch):
        """Kills moving the cursor advance ABOVE ``append_memories(memories)``.

        With the advance moved up, a failed append loses the window's
        memories forever: the bytes never land and the cursor has already
        stepped past them.
        """
        transcript, cursor_file, _ = _stage_main_paths(tmp_path, monkeypatch)
        # A regular file standing where the store's parent directory must be,
        # so ``parent.mkdir`` raises and the append cannot happen.
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(eh, "MEMORIES_FILE", blocker / "sub" / "memories.jsonl")

        payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "sess-F"}
        )
        monkeypatch.setattr("sys.stdin", _StringIO(payload))

        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _mock_extraction_response(
                _ONE_MEMORY_JSON
            )
            mock_cls.return_value = mock_client
            with pytest.raises(SystemExit) as exc:
                eh.main()

        assert exc.value.code == 1, "a failed save must exit non-zero"
        saved = json.loads(cursor_file.read_text()) if cursor_file.exists() else {}
        assert "sess-F" not in saved, (
            "cursor advanced past a window whose memories were never written; "
            f"cursor is {saved!r}"
        )


class TestConcurrentMainInvocations:
    """H21: the flock wiring inside main(), not just the context manager.

    Stop / PreCompact / SessionEnd fire seconds apart at session close, so
    two main() runs genuinely race over one transcript.
    """

    def test_two_racing_main_runs_persist_the_window_once(
        self, tmp_path, monkeypatch
    ):
        """Kills ``with cursor_file_lock():`` → ``if True:`` in main().

        Without the lock both runs read the same starting cursor, both
        extract the same window, and both append — the window's memories
        land twice with a fresh id each, so dedup-by-id never catches them.
        ``TestCursorFileLock`` exercises the context manager directly and
        would stay green through that mutation.
        """
        transcript, cursor_file, store = _stage_main_paths(tmp_path, monkeypatch)
        payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "sess-R"}
        )
        monkeypatch.setattr("sys.stdin", _StringIO(payload))

        # Both runs meet inside the mocked API call. With the lock the second
        # run never gets there (it blocks on flock), so the barrier times out
        # and breaks — which is exactly the signal that serialisation held.
        barrier = threading.Barrier(2)
        response = _mock_extraction_response(_ONE_MEMORY_JSON)

        def _create(**_kwargs):
            try:
                barrier.wait(timeout=1.0)
            except threading.BrokenBarrierError:
                pass
            return response

        errors: list[BaseException] = []

        def worker() -> None:
            try:
                eh.main()
            except SystemExit:
                pass  # "no new messages" exits 0 — the expected second run
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = _create
            mock_cls.return_value = mock_client
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

        assert not errors, f"worker errors: {errors!r}"
        assert not any(t.is_alive() for t in threads), "a run never finished"

        lines = [
            ln for ln in store.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
        # No corruption: every line is a whole JSON object.
        records = [json.loads(ln) for ln in lines]
        assert len(records) == 1, (
            f"the window was persisted {len(records)} times — the second run "
            "was not serialised behind the first"
        )
        assert json.loads(cursor_file.read_text())["sess-R"] == "uuid-A"


class TestTranscriptShapeFidelity:
    """H22: harness-injected and subagent turns must not reach the model."""

    def test_meta_entries_are_not_sent_as_user_turns(self, tmp_path):
        """Kills dropping the ``entry.get("isMeta")`` guard in parse_transcript.

        A system-reminder injection is recorded with ``"role": "user"``; fed
        to the extractor it becomes a "memory" of the harness's own prose.
        """
        transcript = tmp_path / "t.jsonl"
        _write_transcript(
            transcript,
            [
                make_live_shape_entry(
                    "user", "harness injection, not something Shawn said",
                    "u-meta", is_meta=True,
                ),
                make_live_shape_entry("user", "a real question from Shawn", "u-real"),
                make_live_shape_entry("assistant", "an ordinary answer", "a-real"),
            ],
        )
        messages, last_uuid, _, _ = eh.parse_transcript(str(transcript), None)
        texts = [m["content"] for m in messages]
        assert "harness injection, not something Shawn said" not in texts
        assert texts == ["a real question from Shawn", "an ordinary answer"]
        # The skipped entry still advances the cursor.
        assert last_uuid == "a-real"

    def test_sidechain_entries_are_not_sent_as_conversation(self, tmp_path):
        """Kills dropping the ``entry.get("isSidechain")`` guard.

        A subagent's turns belong to that agent's own transcript; extracting
        them here attributes the subagent's words to this session.
        """
        transcript = tmp_path / "t.jsonl"
        _write_transcript(
            transcript,
            [
                make_live_shape_entry(
                    "user", "subagent task brief text here", "u-side",
                    is_sidechain=True,
                ),
                make_live_shape_entry(
                    "assistant", "subagent reply text here", "a-side",
                    is_sidechain=True,
                ),
                make_live_shape_entry("user", "the real turn", "u-real"),
            ],
        )
        messages, last_uuid, _, _ = eh.parse_transcript(str(transcript), None)
        assert [m["content"] for m in messages] == ["the real turn"]
        assert last_uuid == "u-real"

    def test_a_meta_slash_command_still_suppresses_its_response(self, tmp_path):
        """Kills moving the isMeta guard ABOVE the command-marker branch.

        Slash commands arrive as ``isMeta`` user entries (all 364
        marker-bearing user entries measured under
        ~/.claude/projects/-home-shawn-personal-assistant on 2026-09-08).
        Skipping meta entries before the marker test would leave
        ``skip_next_assistant`` unset and let every /remember, /forget, and
        /update response back into extraction — the duplication the marker
        filter exists to stop.
        """
        marker = next(m for m in eh.COMMAND_MARKERS if m.startswith("# /"))
        transcript = tmp_path / "t.jsonl"
        _write_transcript(
            transcript,
            [
                make_live_shape_entry(
                    "user", marker + "\nrun it", "u-cmd", is_meta=True,
                ),
                make_live_shape_entry(
                    "assistant", "the slash-command response", "a-cmd",
                ),
                make_live_shape_entry("user", "an unrelated real question", "u-real"),
                make_live_shape_entry("assistant", "an ordinary answer", "a-real"),
            ],
        )
        messages, _, _, _ = eh.parse_transcript(str(transcript), None)
        texts = [m["content"] for m in messages]
        assert "the slash-command response" not in texts
        assert texts == ["an unrelated real question", "an ordinary answer"]

    def test_a_meta_only_window_still_reports_a_cursor_position(self, tmp_path):
        """Kills placing the isMeta guard ABOVE the ``last_seen_uuid`` assignment.

        A window of nothing but harness injections yields no messages, but it
        must still report where the transcript was read to, or ``main()`` has
        nothing to save.
        """
        transcript = tmp_path / "t.jsonl"
        _write_transcript(
            transcript,
            [
                make_live_shape_entry("user", "injection one", "u1", is_meta=True),
                make_live_shape_entry("user", "injection two", "u2", is_meta=True),
            ],
        )
        messages, last_uuid, _, _ = eh.parse_transcript(str(transcript), None)
        assert messages == []
        assert last_uuid == "u2"

    def test_main_advances_the_cursor_past_a_meta_only_window(
        self, tmp_path, monkeypatch
    ):
        """Kills ``if not messages: sys.exit(0)`` without the cursor advance.

        Audit round two M1: ``parse_transcript`` reported the position but
        ``main()`` exited before ``save_cursor`` ever ran, so a window whose
        entries were all dropped by design was re-parsed on every firing
        forever. The entries are dropped either way, so nothing is lost by
        stepping past them.
        """
        transcript, cursor_file, store = _stage_main_paths(tmp_path, monkeypatch)
        _write_transcript(
            transcript,
            [
                make_live_shape_entry(
                    "user", "harness injection " + "x" * 800, "uuid-M1",
                    is_meta=True,
                ),
                make_live_shape_entry(
                    "assistant", "subagent reply " + "y" * 800, "uuid-M2",
                    is_sidechain=True,
                ),
            ],
        )
        payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "sess-M"}
        )
        monkeypatch.setattr("sys.stdin", _StringIO(payload))

        with patch("anthropic.Anthropic") as mock_cls:
            with pytest.raises(SystemExit) as exc:
                eh.main()
            # No window means no model call at all.
            mock_cls.assert_not_called()

        assert exc.value.code == 0
        assert cursor_file.exists(), "the cursor file was never written"
        assert json.loads(cursor_file.read_text())["sess-M"] == "uuid-M2"
        # Nothing was persisted — the entries really were dropped.
        assert not store.exists()

    def test_main_does_not_write_a_cursor_when_nothing_is_new(
        self, tmp_path, monkeypatch
    ):
        """Kills making the cursor write unconditional (``if True:``).

        A firing with nothing after the cursor must not rewrite the cursor
        file at all; the hook fires three times at every session close, and
        an unconditional write stores a null uuid for the session.

        Note the honest limit (audit round two L3): dropping the
        ``new_last_uuid != last_uuid`` conjunct is a NEAR-EQUIVALENT
        mutant, not a surviving one. ``parse_transcript`` skips past the
        cursor entry with ``continue`` before ``last_seen_uuid`` is
        assigned, so the returned uuid can never equal the one we started
        from — the conjunct is unreachable, and no test can distinguish
        its presence. It is kept as a statement of intent.
        """
        transcript, cursor_file, _ = _stage_main_paths(tmp_path, monkeypatch)
        cursor_file.write_text(json.dumps({"sess-N": "uuid-A"}), encoding="utf-8")
        before = cursor_file.stat().st_mtime_ns

        payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "sess-N"}
        )
        monkeypatch.setattr("sys.stdin", _StringIO(payload))
        with patch("anthropic.Anthropic"):
            with pytest.raises(SystemExit):
                eh.main()

        assert cursor_file.stat().st_mtime_ns == before
        assert json.loads(cursor_file.read_text()) == {"sess-N": "uuid-A"}


class TestImportSideEffects:
    """Audit round two M7: importing the hook must not touch the live log."""

    def test_import_under_pytest_does_not_open_the_live_log(self, tmp_path):
        """Kills hoisting ``logging.basicConfig(filename=LOG_FILE)`` out of the
        ``"pytest" not in sys.modules`` guard.

        The guard used to cover only ``LOG_DIR.mkdir``, so a test import
        still handed ``basicConfig`` the operator's real
        ``data/logs/extraction.log``. It was inert only because pytest's
        logging plugin had already installed a root handler, which makes
        ``basicConfig`` a no-op — an accident, not a guarantee.

        Run in a subprocess with ``HOME`` pinned to a tmp directory and a
        stand-in ``pytest`` module in ``sys.modules``, and with the log
        directory pre-created so nothing else can stop the file being
        opened. If the file exists afterwards, the guard has gone.
        """
        fake_home = tmp_path / "home"
        log_dir = fake_home / "personal-assistant" / "logs"
        log_dir.mkdir(parents=True)

        program = textwrap.dedent(
            """
            import json, logging, sys, types
            # Stand in for pytest so the hook takes its under-test branch.
            sys.modules.setdefault("pytest", types.ModuleType("pytest"))
            sys.path.insert(0, sys.argv[1])
            import importlib
            hook = importlib.import_module("extraction-hook")
            handlers = [
                getattr(h, "baseFilename", None)
                for h in logging.getLogger().handlers
            ]
            print(json.dumps({
                "log_file": str(hook.LOG_FILE),
                "file_handlers": [h for h in handlers if h],
            }))
            """
        )
        env = dict(os.environ, HOME=str(fake_home))
        env.pop("ANTHROPIC_API_KEY", None)
        result = subprocess.run(
            [sys.executable, "-c", program, str(Path(eh.__file__).parent)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout.strip().splitlines()[-1])

        assert report["log_file"] == str(log_dir / "extraction.log")
        assert not (log_dir / "extraction.log").exists(), (
            "importing the hook under pytest opened the live extraction log"
        )
        assert report["file_handlers"] == [], (
            f"a file handler was installed at import: {report['file_handlers']}"
        )


class TestSplitCommandWindow:
    """Audit round two M1: a window that ends mid-slash-command.

    The skip flag exists so a ``/remember`` (or ``/forget``, or
    ``/update``) response is never extracted — the command has already
    written the record itself, and re-extracting it duplicates the memory
    with a fresh id that dedup-by-id cannot catch.

    The flag lives inside one ``parse_transcript`` call, so it survives
    only as long as the cursor does not move past the command. A window
    ending between the command and its response looks all-dropped, which
    is why advancing there destroyed the skip. The split is reachable:
    PreCompact fires before the model call, and an interrupt mid-tool-use
    leaves ``[command, tool-use-only assistant]``.
    """

    @staticmethod
    def _command_marker() -> str:
        return next(m for m in eh.COMMAND_MARKERS if m.startswith("# /"))

    def test_a_window_ending_mid_command_holds_the_cursor(
        self, tmp_path, monkeypatch
    ):
        """Kills ``and not skip_pending`` in the empty-window cursor advance.

        With the guard gone the cursor steps past the command entry, and
        the next window starts after it — so the response arrives with no
        flag set and goes straight to Haiku.
        """
        transcript, cursor_file, store = _stage_main_paths(tmp_path, monkeypatch)
        _write_transcript(
            transcript,
            [
                make_live_shape_entry(
                    "user", self._command_marker() + "\nsave that", "uuid-cmd",
                    is_meta=True,
                ),
                # The interrupt shape: a tool-use-only assistant entry, which
                # deliberately does NOT consume the flag (audit H11).
                {
                    "type": "assistant",
                    "uuid": "uuid-tool",
                    "isMeta": False,
                    "isSidechain": False,
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "name": "Write", "input": {}}
                        ],
                    },
                },
            ],
        )
        payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "sess-SC"}
        )
        monkeypatch.setattr("sys.stdin", _StringIO(payload))

        with patch("anthropic.Anthropic") as mock_cls:
            with pytest.raises(SystemExit) as exc:
                eh.main()
            mock_cls.assert_not_called()

        assert exc.value.code == 0
        saved = json.loads(cursor_file.read_text()) if cursor_file.exists() else {}
        assert "sess-SC" not in saved, (
            "the cursor advanced past a pending command skip; the response "
            f"will be extracted next firing. Cursor: {saved!r}"
        )
        assert not store.exists()

    def test_the_response_is_still_skipped_on_the_next_firing(
        self, tmp_path, monkeypatch
    ):
        """Kills the same guard, at the consequence rather than the cursor.

        Second firing, with the response now present alongside a real
        exchange: the response must not reach Haiku. If the first firing
        had advanced the cursor, this window would begin after the command
        and the response would be an ordinary assistant turn.
        """
        transcript, cursor_file, store = _stage_main_paths(tmp_path, monkeypatch)
        marker = self._command_marker()
        response = "THE COMMAND RESPONSE THAT MUST NEVER BE EXTRACTED"

        # Firing one: the window ends mid-command.
        _write_transcript(
            transcript,
            [
                make_live_shape_entry(
                    "user", marker + "\nsave that", "uuid-cmd", is_meta=True
                ),
            ],
        )
        payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "sess-SC2"}
        )
        monkeypatch.setattr("sys.stdin", _StringIO(payload))
        with patch("anthropic.Anthropic"):
            with pytest.raises(SystemExit):
                eh.main()

        # Firing two: the response has landed, and a real exchange follows.
        _write_transcript(
            transcript,
            [
                make_live_shape_entry(
                    "user", marker + "\nsave that", "uuid-cmd", is_meta=True
                ),
                make_live_shape_entry("assistant", response, "uuid-resp"),
                make_live_shape_entry(
                    "user", "a genuine question " + "q" * 800, "uuid-user"
                ),
                make_live_shape_entry(
                    "assistant", "a genuine answer " + "a" * 800, "uuid-ans"
                ),
            ],
        )
        monkeypatch.setattr("sys.stdin", _StringIO(payload))
        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _mock_extraction_response(
                _ONE_MEMORY_JSON
            )
            mock_cls.return_value = mock_client
            eh.main()
            assert mock_client.messages.create.call_count == 1
            sent = mock_client.messages.create.call_args.kwargs["messages"][0][
                "content"
            ]

        assert response not in sent, (
            "the slash-command response was sent to the model — the skip "
            "flag did not survive the window split"
        )
        assert "a genuine question" in sent
        # The real exchange was extracted and the cursor now moves.
        assert json.loads(cursor_file.read_text())["sess-SC2"] == "uuid-ans"
        assert store.exists()

    def test_a_completed_command_window_still_advances(self, tmp_path, monkeypatch):
        """Kills widening the hold to every window carrying a command.

        When the response HAS been seen the flag is spent, so holding the
        cursor would re-parse the same window forever — the failure M1's
        fix was meant to remove, reintroduced from the other side.
        """
        transcript, cursor_file, _ = _stage_main_paths(tmp_path, monkeypatch)
        _write_transcript(
            transcript,
            [
                make_live_shape_entry(
                    "user", self._command_marker() + "\nsave that", "uuid-cmd",
                    is_meta=True,
                ),
                make_live_shape_entry(
                    "assistant", "the command response", "uuid-resp"
                ),
            ],
        )
        payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "sess-SC3"}
        )
        monkeypatch.setattr("sys.stdin", _StringIO(payload))
        with patch("anthropic.Anthropic") as mock_cls:
            with pytest.raises(SystemExit):
                eh.main()
            mock_cls.assert_not_called()

        assert json.loads(cursor_file.read_text())["sess-SC3"] == "uuid-resp"

    def test_parse_transcript_reports_the_pending_flag(self, tmp_path):
        """Kills ``return ParsedWindow(..., skip_next_assistant)`` -> ``False``.

        The unit-level statement of the same contract: the third field is
        the live flag at end of window, not a constant.
        """
        marker = self._command_marker()
        pending = tmp_path / "pending.jsonl"
        _write_transcript(
            pending,
            [make_live_shape_entry("user", marker + "\nx", "u1", is_meta=True)],
        )
        assert eh.parse_transcript(str(pending), None).skip_pending is True

        spent = tmp_path / "spent.jsonl"
        _write_transcript(
            spent,
            [
                make_live_shape_entry("user", marker + "\nx", "u1", is_meta=True),
                make_live_shape_entry("assistant", "the response", "u2"),
            ],
        )
        assert eh.parse_transcript(str(spent), None).skip_pending is False

        plain = tmp_path / "plain.jsonl"
        _write_transcript(
            plain, [make_live_shape_entry("user", "an ordinary turn", "u1")]
        )
        assert eh.parse_transcript(str(plain), None).skip_pending is False


class TestSafeAdvancePosition:
    """Audit round three C1: where the cursor stops when a command is pending.

    Two invariants have to hold at once:

    1. a slash-command response is never sent to the model (it duplicates
       what the command itself wrote); and
    2. a real message is never extracted twice.

    Holding the cursor outright satisfies (1) and breaks (2) — the real
    messages before the command are re-read every firing. Advancing to the
    last uuid satisfies (2) and breaks (1). ``safe_uuid`` — the position
    just before the command — is the only answer that satisfies both.
    """

    @staticmethod
    def _command_marker() -> str:
        return next(m for m in eh.COMMAND_MARKERS if m.startswith("# /"))

    def test_both_invariants_hold_across_the_split(self, tmp_path, monkeypatch):
        """Kills advancing to ``new_last_uuid`` when a skip is pending, and
        kills holding the cursor instead of advancing to ``safe_uuid``.

        Firing one extracts the two real messages and stops at the
        assistant, NOT at the command. Firing two therefore sees the
        command and its response together, sends nothing to the model, and
        steps past both — with the real messages still behind the cursor.
        """
        transcript, cursor_file, store = _stage_main_paths(tmp_path, monkeypatch)
        marker = self._command_marker()
        response = "THE COMMAND RESPONSE THAT MUST NEVER BE EXTRACTED"
        real_user = "a genuine question " + "q" * 800
        real_assistant = "a genuine answer " + "a" * 800

        # Firing one: real exchange, then the command, with no response yet.
        _write_transcript(
            transcript,
            [
                make_live_shape_entry("user", real_user, "uuid-1"),
                make_live_shape_entry("assistant", real_assistant, "uuid-2"),
                make_live_shape_entry(
                    "user", marker + "\nsave that", "uuid-3", is_meta=True
                ),
            ],
        )
        payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "sess-SA"}
        )
        monkeypatch.setattr("sys.stdin", _StringIO(payload))
        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _mock_extraction_response(
                _ONE_MEMORY_JSON
            )
            mock_cls.return_value = mock_client
            eh.main()
            assert mock_client.messages.create.call_count == 1
            first_prompt = mock_client.messages.create.call_args.kwargs[
                "messages"
            ][0]["content"]

        assert "a genuine question" in first_prompt
        assert "a genuine answer" in first_prompt
        after_first = json.loads(cursor_file.read_text())["sess-SA"]
        assert after_first == "uuid-2", (
            "the cursor should stop at the entry before the command, not at "
            f"the command itself; it is at {after_first!r}"
        )
        assert len(store.read_text(encoding="utf-8").splitlines()) == 1

        # Firing two: the response has landed.
        _write_transcript(
            transcript,
            [
                make_live_shape_entry("user", real_user, "uuid-1"),
                make_live_shape_entry("assistant", real_assistant, "uuid-2"),
                make_live_shape_entry(
                    "user", marker + "\nsave that", "uuid-3", is_meta=True
                ),
                make_live_shape_entry("assistant", response, "uuid-4"),
            ],
        )
        monkeypatch.setattr("sys.stdin", _StringIO(payload))
        with patch("anthropic.Anthropic") as mock_cls:
            with pytest.raises(SystemExit) as exc:
                eh.main()
            mock_cls.assert_not_called()

        assert exc.value.code == 0
        # Invariant 1: nothing was sent, so the response never reached Haiku.
        # Invariant 2: the store still holds exactly the first firing's record.
        assert len(store.read_text(encoding="utf-8").splitlines()) == 1
        assert json.loads(cursor_file.read_text())["sess-SA"] == "uuid-4"

    def test_safe_uuid_stops_before_the_command(self, tmp_path):
        """Kills settling ``safe_uuid`` after the command instead of before.

        The unit-level statement: with a pending skip, the safe position is
        the entry preceding the command, never the command's own uuid.
        """
        transcript = tmp_path / "t.jsonl"
        _write_transcript(
            transcript,
            [
                make_live_shape_entry("user", "real one", "u1"),
                make_live_shape_entry("assistant", "real two", "u2"),
                make_live_shape_entry(
                    "user", self._command_marker() + "\nx", "u3", is_meta=True
                ),
            ],
        )
        window = eh.parse_transcript(str(transcript), None)
        assert window.skip_pending is True
        assert window.last_uuid == "u3"
        assert window.safe_uuid == "u2"

    def test_skip_pending_is_reported_even_with_real_messages(self, tmp_path):
        """Kills computing ``skip_pending`` only for all-dropped windows (M3).

        A window can carry perfectly good messages and still end mid-command;
        that is precisely the case C1 exists for.
        """
        transcript = tmp_path / "t.jsonl"
        _write_transcript(
            transcript,
            [
                make_live_shape_entry("user", "a real question", "u1"),
                make_live_shape_entry(
                    "user", self._command_marker() + "\nx", "u2", is_meta=True
                ),
            ],
        )
        window = eh.parse_transcript(str(transcript), None)
        assert window.messages, "the real message must still be extracted"
        assert window.skip_pending is True
        assert window.safe_uuid == "u1"

    def test_back_to_back_commands_keep_the_skip_pending(self, tmp_path):
        """Kills clearing the flag on a second command entry (mutation M-b2).

        Two commands in a row leave one response still owed. If the second
        entry cleared the flag rather than re-setting it, the cursor would
        advance past both and that response would be extracted.
        """
        marker = self._command_marker()
        transcript = tmp_path / "t.jsonl"
        _write_transcript(
            transcript,
            [
                make_live_shape_entry("user", "real one", "u1"),
                make_live_shape_entry("user", marker + "\nfirst", "u2", is_meta=True),
                make_live_shape_entry("user", marker + "\nsecond", "u3", is_meta=True),
            ],
        )
        window = eh.parse_transcript(str(transcript), None)
        assert window.skip_pending is True
        assert window.safe_uuid == "u1"

    def test_safe_uuid_is_the_last_entry_when_nothing_is_pending(self, tmp_path):
        """Kills freezing ``safe_uuid`` when no skip was ever pending.

        With the flag clear at end of window the cursor may go all the way,
        so ``safe_uuid`` must equal ``last_uuid`` — otherwise the ordinary
        case silently stops short and re-reads entries every firing.
        """
        transcript = tmp_path / "t.jsonl"
        _write_transcript(
            transcript,
            [
                make_live_shape_entry("user", "real one", "u1"),
                make_live_shape_entry("assistant", "real two", "u2"),
            ],
        )
        window = eh.parse_transcript(str(transcript), None)
        assert window.skip_pending is False
        assert window.safe_uuid == "u2" == window.last_uuid

    def test_a_spent_command_lets_the_cursor_run_to_the_end(self, tmp_path):
        """Kills leaving ``safe_uuid`` frozen after the response arrives.

        Once the response has been seen the flag is spent, so the whole
        window is behind us and the cursor may pass the response too.
        """
        transcript = tmp_path / "t.jsonl"
        _write_transcript(
            transcript,
            [
                make_live_shape_entry(
                    "user", self._command_marker() + "\nx", "u1", is_meta=True
                ),
                make_live_shape_entry("assistant", "the response", "u2"),
            ],
        )
        window = eh.parse_transcript(str(transcript), None)
        assert window.skip_pending is False
        assert window.safe_uuid == "u2"
