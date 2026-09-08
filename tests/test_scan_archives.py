"""
Tests for ``scripts/_scan_archives.py`` — the safe archive scan engine.

This engine exists because an ad-hoc transcript search locked the machine on
2026-06-21: a pipeline collapsed each ~25 MB transcript into ONE line and ran
a bounded-quantifier regex over it. The safety properties that prevent a
repeat — strict line orientation, the per-line truncation guard, and a narrow
exception tuple that skips a corrupt member without aborting the scan — had
no tests, so all three could be removed with the suite green (lens B finding
7).

Every ``.gz`` here is built in the test. Nothing reads ~/cc-archives.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

_spec = importlib.util.spec_from_file_location(
    "scan_archives_under_test", str(SCRIPTS_DIR / "_scan_archives.py")
)
assert _spec is not None and _spec.loader is not None
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)


def _entry(root: Path, name: str, lines: list[str]) -> Path:
    """Write one archive entry holding a gzipped transcript."""
    entry = root / "lantern-survey" / name
    entry.mkdir(parents=True, exist_ok=True)
    with gzip.open(entry / "session.jsonl.gz", "wb") as handle:
        handle.write("".join(line + "\n" for line in lines).encode("utf-8"))
    return entry


class TestPerLineTruncation:
    """The guard that defuses a pathologically long line."""

    def test_a_long_line_is_truncated_before_the_regex_sees_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The needle sits past the cap, so a truncating scan must miss it."""
        haystack = "a" * 500 + "NEEDLE"
        _entry(tmp_path, "2026-03-02_long", [haystack])

        matches = scan.scan_file(
            tmp_path / "lantern-survey" / "2026-03-02_long" / "session.jsonl.gz",
            re.compile("NEEDLE"),
            context=0, max_line=100, and_pattern=None, display_root=tmp_path,
        )

        assert matches == 0, (
            "the per-line truncation guard was not applied; a flattened "
            "25 MB line would reach the regex engine whole"
        )

    def test_the_same_line_matches_when_the_cap_allows_it(
        self, tmp_path: Path
    ) -> None:
        """The positive control: truncation, not a broken search."""
        _entry(tmp_path, "2026-03-02_long", ["a" * 500 + "NEEDLE"])

        matches = scan.scan_file(
            tmp_path / "lantern-survey" / "2026-03-02_long" / "session.jsonl.gz",
            re.compile("NEEDLE"),
            context=0, max_line=10_000, and_pattern=None,
            display_root=tmp_path,
        )

        assert matches == 1

    def test_files_with_matches_applies_the_same_cap(
        self, tmp_path: Path
    ) -> None:
        """The cheap path must not be the unguarded one."""
        path = _entry(
            tmp_path, "2026-03-02_long", ["b" * 500 + "NEEDLE"]
        ) / "session.jsonl.gz"

        assert scan._has_match(path, re.compile("NEEDLE"), None, 100) is False
        assert scan._has_match(path, re.compile("NEEDLE"), None, 10_000) is True


class TestCorruptArchivesAreSkipped:
    """A partial or corrupt member must never abort the whole scan."""

    def test_a_corrupt_member_is_skipped_and_the_scan_continues(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        good = _entry(tmp_path, "2026-03-02_good", [
            json.dumps({"type": "user", "text": "NEEDLE in the good entry"})
        ])
        bad = tmp_path / "lantern-survey" / "2026-03-03_bad"
        bad.mkdir(parents=True)
        (bad / "session.jsonl.gz").write_bytes(b"not gzip at all")

        exit_code = scan.main(["NEEDLE", str(tmp_path)])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "NEEDLE in the good entry" in captured.out
        assert "skipped" in captured.err
        assert str(good.name) in captured.out

    def test_a_keyboard_interrupt_is_not_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exception tuple is narrow on purpose.

        Widening it to BaseException would make Ctrl-C look like a corrupt
        archive: the scan would report "skipped" and carry on.
        """
        path = _entry(tmp_path, "2026-03-02_entry", ["x"]) / "session.jsonl.gz"

        def interrupted(*args, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(scan.gzip, "open", interrupted)

        with pytest.raises(KeyboardInterrupt):
            scan.scan_file(
                path, re.compile("x"), context=0, max_line=1000,
                and_pattern=None, display_root=tmp_path,
            )


class TestTranscriptDiscovery:
    """What the engine considers an archived transcript."""

    def test_sessions_and_subagents_are_both_scanned(
        self, tmp_path: Path
    ) -> None:
        entry = _entry(tmp_path, "2026-03-02_entry", ["session line"])
        (entry / "subagents").mkdir()
        with gzip.open(entry / "subagents" / "agent-1f2e.jsonl.gz", "wb") as fh:
            fh.write(b"subagent line\n")

        found = [p.name for p in scan.iter_transcripts(tmp_path)]

        assert found == ["session.jsonl.gz", "agent-1f2e.jsonl.gz"]

    def test_a_raw_transcript_is_not_scanned(self, tmp_path: Path) -> None:
        """gz is the canonical form; raw entries are a defect verify reports.

        Pinned here so the two commands cannot drift apart again: if this
        engine ever starts accepting raw JSONL, ``verify``'s non-canonical
        finding has to change with it (AR21).
        """
        entry = tmp_path / "lantern-survey" / "2026-03-02_raw"
        entry.mkdir(parents=True)
        (entry / "session.jsonl").write_text("raw line\n", encoding="utf-8")

        assert list(scan.iter_transcripts(tmp_path)) == []


class TestExitCodes:
    """grep's convention: 0 on matches, 1 on none."""

    def test_no_matches_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _entry(tmp_path, "2026-03-02_entry", ["nothing of interest"])

        assert scan.main(["NEEDLE", str(tmp_path)]) == 1

    def test_matches_exit_zero_with_path_and_line_number(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _entry(tmp_path, "2026-03-02_entry", ["first", "NEEDLE here", "third"])

        assert scan.main(["NEEDLE", str(tmp_path)]) == 0

        out = capsys.readouterr().out
        assert ":2:" in out, f"expected path:lineno output, got {out!r}"


class TestDefaultsAreThemselvesPinned:
    """The safety limits' DEFAULT values, not just their plumbing.

    Every other test passes --max-line explicitly, so widening
    DEFAULT_MAX_LINE to 1e11 left 48 tests green — and the default is what
    every real invocation uses, because search-archives-safe.sh only ever
    passes SAS_MAXLINE, whose own default is the same number (round 4c-2,
    finding 22). A limit nobody exercises at its default is not a limit.
    """

    def test_the_default_line_cap_is_the_documented_one(self) -> None:
        assert scan.DEFAULT_MAX_LINE == 1_000_000, (
            "the per-line guard's default changed; the 2026-06-21 crash was "
            "a ~25 MB single line reaching the regex engine"
        )

    def test_a_pathological_line_is_truncated_at_the_default(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Run the scanner with NO explicit limit, as the wrapper does."""
        needle = "NEEDLEPASTTHEDEFAULTCAP"
        _entry(tmp_path, "2026-03-02_pathological", [
            "a" * (scan.DEFAULT_MAX_LINE + 500) + needle
        ])

        exit_code = scan.main([needle, str(tmp_path)])

        assert exit_code == 1, (
            "text beyond the default per-line cap reached the regex; the "
            "cap is not being applied on the default path"
        )
        assert "0 file(s) matched" in capsys.readouterr().err

    def test_content_inside_the_default_cap_still_matches(
        self, tmp_path: Path
    ) -> None:
        """The positive control: the default must not break ordinary search."""
        _entry(tmp_path, "2026-03-02_ordinary", ["a line holding NEEDLE"])

        assert scan.main(["NEEDLE", str(tmp_path)]) == 0
