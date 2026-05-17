"""
Tests for extraction-hook.py — tag normalisation, transcript parsing,
memory formatting, cursor tracking, and command filtering.

Tests pure functions only; does not call the Anthropic API.
"""

import json
from pathlib import Path

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

        messages, last_uuid = eh.parse_transcript(str(transcript), None)
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

        messages, last_uuid = eh.parse_transcript(str(transcript), "uuid-2")
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

        messages, last_uuid = eh.parse_transcript(
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

        messages, _ = eh.parse_transcript(str(transcript), None)
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

        messages, last_uuid = eh.parse_transcript(str(transcript), None)
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

        messages, _ = eh.parse_transcript(str(transcript), None)
        assert len(messages) == 1
        assert messages[0]["content"] == "Normal"

    def test_skip_flag_resets_on_normal_user_message(self, tmp_path):
        """Non-command user message after a command should reset skip flag."""
        transcript = tmp_path / "transcript.jsonl"
        entries = [
            # Command exchange — both should be filtered
            make_transcript_entry(
                "user",
                "# /remember \u2014 Manual Memory Capture\n\nSome content",
                "uuid-1",
            ),
            # Normal user message immediately after (no assistant in between)
            make_transcript_entry("user", "Normal question", "uuid-2"),
            # This assistant response should NOT be skipped
            make_transcript_entry("assistant", "Normal answer", "uuid-3"),
        ]
        with open(transcript, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        messages, _ = eh.parse_transcript(str(transcript), None)
        assert len(messages) == 2
        contents = [m["content"] for m in messages]
        assert "Normal question" in contents
        assert "Normal answer" in contents

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

        messages, _ = eh.parse_transcript(str(transcript), None)
        assert len(messages) == 1
        assert "[THINKING]:" in messages[0]["content"]
        assert "Here is my answer." in messages[0]["content"]

    def test_empty_transcript(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")

        messages, last_uuid = eh.parse_transcript(str(transcript), None)
        assert messages == []
        assert last_uuid is None

    def test_truncates_long_messages(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        long_content = "x" * 10000
        entry = make_transcript_entry("user", long_content, "uuid-1")
        with open(transcript, "w") as f:
            f.write(json.dumps(entry) + "\n")

        messages, _ = eh.parse_transcript(str(transcript), None)
        assert len(messages[0]["content"]) == eh.MAX_MESSAGE_CHARS


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
