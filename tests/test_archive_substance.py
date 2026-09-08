"""
Tests for ``scripts/_archive_substance.py`` — the ONE substantive-session rule.

The class of defect these pin (audit 2026-09-08, finding AR1): the drift gate
and the archiver each carried their own idea of "substantive", they disagreed,
and so the gate reported sessions that its own remediation command refused to
archive. The gate could never be cleared, and a gate nobody can clear is a
gate nobody reads — which is how a 77-session archive gap survived twelve
weeks.

Every transcript here is synthetic (see ``tests/archive_fixtures.py``).
"""

from __future__ import annotations

import gzip
import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from archive_fixtures import (  # noqa: E402
    age_file,
    prose_record,
    substantive_records,
    tool_result_record,
    tool_use_record,
    trivial_records,
    write_transcript,
)

substance = importlib.import_module("_archive_substance")


class TestProseCounting:
    """What counts as conversational prose, and what does not."""

    def test_counts_string_and_block_content(self, tmp_path: Path) -> None:
        """Both content shapes production writes contribute to the count."""
        path = write_transcript(tmp_path / "s.jsonl", [
            prose_record("user", "x" * 100, index=1),
            prose_record("assistant", "y" * 250, index=2, structured=True),
        ])
        assert substance.session_content_chars(path) == 350

    def test_machine_records_are_excluded(self, tmp_path: Path) -> None:
        """isMeta / isSidechain / isCompactSummary carry no human prose."""
        path = write_transcript(tmp_path / "s.jsonl", [
            prose_record("user", "a" * 5_000, index=1, is_meta=True),
            prose_record("assistant", "b" * 5_000, index=2, is_sidechain=True),
            prose_record("user", "c" * 5_000, index=3, is_compact_summary=True),
            prose_record("user", "d" * 40, index=4),
        ])
        assert substance.session_content_chars(path) == 40
        assert substance.is_substantive(path) is False

    def test_tool_traffic_and_thinking_are_excluded(self, tmp_path: Path) -> None:
        """A session of nothing but tool churn is not substantive."""
        path = write_transcript(tmp_path / "s.jsonl", [
            tool_use_record(1),
            tool_result_record(2),
            tool_use_record(3),
            tool_result_record(4),
        ])
        assert substance.session_content_chars(path) == 0

    def test_non_conversational_types_are_excluded(self, tmp_path: Path) -> None:
        """``system``/``summary`` records are machinery, whatever their size."""
        path = write_transcript(tmp_path / "s.jsonl", [
            {"type": "system", "cwd": "/home/tester", "content": "z" * 9_000},
            {"type": "summary", "summary": "q" * 9_000},
        ])
        assert substance.session_content_chars(path) == 0

    def test_byte_order_mark_does_not_drop_the_first_record(
        self, tmp_path: Path
    ) -> None:
        """A UTF-8 BOM must not silently cost the opening exchange (AR23)."""
        path = tmp_path / "bom.jsonl"
        records = [prose_record("user", "m" * 6_000, index=1)]
        body = "".join(json.dumps(r) + "\n" for r in records)
        path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
        assert substance.session_content_chars(path) == 6_000

    def test_partial_last_line_is_tolerated(self, tmp_path: Path) -> None:
        """A transcript caught mid-write still counts what it can read."""
        path = write_transcript(tmp_path / "s.jsonl", [
            prose_record("user", "k" * 5_000, index=1),
        ])
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"type": "assistant", "message": {"role"')
        assert substance.session_content_chars(path) == 5_000

    def test_threshold_stops_early_without_undercounting(
        self, tmp_path: Path
    ) -> None:
        """Early exit returns a lower bound that still clears the floor."""
        path = write_transcript(tmp_path / "s.jsonl", substantive_records("s1"))
        capped = substance.session_content_chars(path, threshold=1_000)
        assert capped >= 1_000
        assert substance.session_content_chars(path) > capped

    def test_gzipped_transcripts_are_read(self, tmp_path: Path) -> None:
        """The archived form is readable by the same predicate."""
        plain = write_transcript(tmp_path / "s.jsonl", substantive_records("s1"))
        gz = tmp_path / "session.jsonl.gz"
        with gzip.open(gz, "wb") as handle:
            handle.write(plain.read_bytes())
        assert substance.is_substantive(gz) is True

    def test_unreadable_transcript_counts_as_zero(self, tmp_path: Path) -> None:
        """A file we cannot open is not evidence of substance."""
        assert substance.session_content_chars(tmp_path / "absent.jsonl") == 0


class TestFloor:
    """The 4,000-character floor, on both sides."""

    def test_two_turn_large_session_is_substantive(self, tmp_path: Path) -> None:
        """One long exchange is substantive — the case turn count lost."""
        path = write_transcript(
            tmp_path / "big.jsonl", substantive_records("s1", turns=1)
        )
        assert path.stat().st_size > 28_000
        assert substance.is_substantive(path) is True

    def test_many_short_turns_are_not_substantive(self, tmp_path: Path) -> None:
        """Five turns of nothing is still nothing."""
        path = write_transcript(
            tmp_path / "small.jsonl", trivial_records("s2", turns=5)
        )
        assert substance.is_substantive(path) is False

    def test_zero_floor_accepts_everything(self, tmp_path: Path) -> None:
        """A disabled floor is explicit, not accidental."""
        path = write_transcript(tmp_path / "empty.jsonl", [])
        assert substance.is_substantive(path, min_chars=0) is True


class TestGraceWindow:
    """The 48-hour window before a transcript is expected — or safe to copy."""

    def test_fresh_transcript_is_in_grace(self, tmp_path: Path) -> None:
        path = write_transcript(tmp_path / "s.jsonl", substantive_records("s1"))
        age_file(path, hours=1)
        assert substance.within_grace(path) is True

    def test_old_transcript_is_out_of_grace(self, tmp_path: Path) -> None:
        path = write_transcript(tmp_path / "s.jsonl", substantive_records("s1"))
        age_file(path, hours=72)
        assert substance.within_grace(path) is False

    def test_missing_transcript_is_treated_as_in_grace(
        self, tmp_path: Path
    ) -> None:
        """Refusing to act is the safe direction for a file we cannot stat."""
        assert substance.within_grace(tmp_path / "gone.jsonl") is True

    @pytest.mark.parametrize("hours", [47.9, 48.1])
    def test_boundary_is_honoured(self, tmp_path: Path, hours: float) -> None:
        path = write_transcript(tmp_path / "s.jsonl", substantive_records("s1"))
        age_file(path, hours=hours)
        assert substance.within_grace(path) is (hours < 48)
