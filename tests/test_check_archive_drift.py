"""
Tests for ``scripts/check-archive-drift.py`` — the archive's only tripwire.

This script is the sole automated detector for the failure that produced the
2026-07-28 gap (77 substantive sessions never archived, found twelve weeks
late). Until 2026-09-08 it had no tests at all: ``missing = {}`` or an
always-trivial predicate both left the full suite green, so the tripwire could
be disarmed silently.

The file also pins the cross-script agreement the gate depends on (audit
finding AR1): the sessions the gate REPORTS are exactly the sessions
``bulk-archive.py discover`` selects at the flags the gate's remediation line
names. Every transcript here is synthetic.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import logging
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from archive_fixtures import (  # noqa: E402
    age_file,
    make_archive_entry,
    make_raw_store,
    substantive_records,
    trivial_records,
    write_transcript,
)


def _load(name: str, filename: str):
    """Import a hyphenated script by path (they are not importable by name)."""
    spec = importlib.util.spec_from_file_location(
        name, str(SCRIPTS_DIR / filename)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


drift = _load("check_archive_drift_under_test", "check-archive-drift.py")
bulk_archive = importlib.import_module("bulk-archive")



def _discover_defaults() -> dict[str, object]:
    """The ``discover`` sub-parser's defaults, read from the real CLI.

    Restating the defaults in the test would let them drift apart silently;
    parsing an empty argument list makes the test fail the moment the command
    the drift gate recommends stops meaning what the gate assumes.
    """
    parsed = _parse_discover_args()
    return {
        "min_turns": parsed.min_turns,
        "min_content_tokens": parsed.min_content_tokens,
        "min_content_chars": parsed.min_content_chars,
    }


def _parse_discover_args() -> argparse.Namespace:
    """Parse ``bulk-archive.py discover`` with no flags, via its own parser.

    ``setup_logging`` is replaced for the duration: the real one opens a
    ``FileHandler`` under the repository's ``logs/``, which the hermeticity
    guard (rightly) treats as the suite writing to the operator's data.
    """
    captured: dict[str, argparse.Namespace] = {}

    def capture(args: argparse.Namespace, logger: logging.Logger) -> None:
        captured["args"] = args

    argv = sys.argv
    sys.argv = ["bulk-archive.py", "discover"]
    original_cmd = bulk_archive.cmd_discover
    original_logging = bulk_archive.setup_logging
    bulk_archive.cmd_discover = capture
    bulk_archive.setup_logging = lambda: logging.getLogger("cli-under-test")
    try:
        bulk_archive.main()
    finally:
        bulk_archive.cmd_discover = original_cmd
        bulk_archive.setup_logging = original_logging
        sys.argv = argv
    return captured["args"]


@pytest.fixture()
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A synthetic raw store and archive root, wired into the drift check."""
    raw_root = tmp_path / "claude" / "projects"
    archive_root = tmp_path / "cc-archives"
    # TWO project directories, deliberately. A store always holds many, and
    # with only one every "walk the store" bug is invisible: truncating the
    # iteration to its first element left the suite green while the tripwire
    # reported Clean over every project but the alphabetically first — the
    # 2026-07-28 failure mode exactly (round 4c-2, finding 19). The second
    # name sorts AFTER the first, so a truncated walk misses it.
    project_dir = make_raw_store(raw_root, project_key="-home-tester-Workshop")
    second_project_dir = make_raw_store(
        raw_root, project_key="-home-tester-Zenodo-uploads"
    )
    archive_root.mkdir(parents=True)
    gate = tmp_path / "cache" / "cc-archive-drift-gate"
    gate.parent.mkdir(parents=True)

    monkeypatch.setattr(drift, "RAW_ROOT", raw_root)
    monkeypatch.setattr(drift, "ARCHIVE_ROOT", archive_root)
    monkeypatch.setattr(drift, "GATE_FILE", gate)
    return argparse.Namespace(
        raw_root=raw_root, archive_root=archive_root,
        project_dir=project_dir, second_project_dir=second_project_dir,
        gate=gate,
    )


def _old_substantive(project_dir: Path, session_id: str) -> Path:
    """A substantive transcript, aged past the grace window."""
    path = write_transcript(
        project_dir / f"{session_id}.jsonl", substantive_records(session_id)
    )
    age_file(path, hours=96)
    return path


class TestDriftReporting:
    """The six cases the tripwire has to get right."""

    def test_substantive_unarchived_session_is_reported(self, stores) -> None:
        """The 2026-07-28 case: prose on disk, nothing in the archive."""
        sid = "11111111-1111-4111-8111-111111111111"
        _old_substantive(stores.project_dir, sid)

        assert drift.main([]) == 1
        lines = stores.gate.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "1", "the gate's first line must be the count"
        assert any(sid in line for line in lines[1:])

    def test_trivial_session_is_not_reported(self, stores) -> None:
        """Below the prose floor: deliberately un-archived, never flagged."""
        sid = "22222222-2222-4222-8222-222222222222"
        path = write_transcript(
            stores.project_dir / f"{sid}.jsonl", trivial_records(sid, turns=5)
        )
        age_file(path, hours=96)

        assert drift.main([]) == 0
        assert stores.gate.read_text(encoding="utf-8").splitlines()[0] == "0"

    def test_session_inside_the_grace_window_is_not_reported(
        self, stores
    ) -> None:
        """The hooks have not had their chance yet."""
        sid = "33333333-3333-4333-8333-333333333333"
        path = write_transcript(
            stores.project_dir / f"{sid}.jsonl", substantive_records(sid)
        )
        age_file(path, hours=2)

        assert drift.main([]) == 0
        assert stores.gate.read_text(encoding="utf-8").splitlines()[0] == "0"

    def test_archived_session_is_not_reported(self, stores) -> None:
        """A session with a meta on disk is done, wherever the meta sits."""
        sid = "44444444-4444-4444-8444-444444444444"
        _old_substantive(stores.project_dir, sid)
        make_archive_entry(stores.archive_root, sid)

        assert drift.main([]) == 0

    def test_flat_agent_transcripts_are_never_sessions(self, stores) -> None:
        """``agent-*.jsonl`` are subagent records, archived inside a parent."""
        path = write_transcript(
            stores.project_dir / "agent-9f2c1a.jsonl",
            substantive_records("agent-9f2c1a"),
        )
        age_file(path, hours=96)

        assert drift.main([]) == 0

    def test_a_session_missing_from_the_second_project_is_reported(
        self, stores
    ) -> None:
        """The store is walked whole, not just its first project.

        The 2026-07-28 gap was 77 sessions spread across projects and
        machines. A tripwire that reads only the first project directory
        reports Clean on a store that is missing most of its archive.
        """
        first = "88888888-8888-4888-8888-888888888888"
        second = "99999999-9999-4999-8999-999999999999"
        _old_substantive(stores.project_dir, first)
        _old_substantive(stores.second_project_dir, second)
        # Only the FIRST project's session is archived.
        make_archive_entry(stores.archive_root, first)

        assert drift.main([]) == 1

        lines = stores.gate.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "1"
        assert any(second in line for line in lines[1:]), (
            "the session missing from the second project directory was not "
            "reported; the store is not being walked whole"
        )

    def test_every_project_directory_contributes_to_the_count(
        self, stores
    ) -> None:
        """Two unarchived sessions, one per project, must both be counted."""
        first = "aaaaaaaa-8888-4888-8888-888888888888"
        second = "bbbbbbbb-9999-4999-8999-999999999999"
        _old_substantive(stores.project_dir, first)
        _old_substantive(stores.second_project_dir, second)

        assert drift.main([]) == 1

        lines = stores.gate.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "2", (
            f"expected both projects counted, gate says {lines[0]}"
        )

    def test_missing_store_exits_two(self, tmp_path, monkeypatch) -> None:
        """A store that is absent is 'cannot run', never 'clean'."""
        monkeypatch.setattr(drift, "RAW_ROOT", tmp_path / "no-raw")
        monkeypatch.setattr(drift, "ARCHIVE_ROOT", tmp_path / "no-archive")
        monkeypatch.setattr(drift, "GATE_FILE", tmp_path / "gate")
        assert drift.main([]) == 2
        assert not (tmp_path / "gate").exists(), (
            "a run that could not read the stores must not leave a gate "
            "claiming a count"
        )


class TestGateFileWrite:
    """The gate is read by a SessionStart hook; a torn read is a false alarm."""

    def test_gate_write_is_atomic(self, stores, monkeypatch) -> None:
        """A crash mid-write leaves the previous gate intact (AR23)."""
        stores.gate.write_text("0\n", encoding="utf-8")
        _old_substantive(
            stores.project_dir, "55555555-5555-4555-8555-555555555555"
        )

        real_replace = drift.os.replace

        def boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(drift.os, "replace", boom)
        with pytest.raises(OSError):
            drift.main([])
        monkeypatch.setattr(drift.os, "replace", real_replace)

        assert stores.gate.read_text(encoding="utf-8") == "0\n"
        leftovers = [
            p for p in stores.gate.parent.iterdir() if p.name.endswith(".tmp")
        ]
        assert not leftovers, f"temporary gate files left behind: {leftovers}"


class TestGateAgreesWithTheArchiver:
    """AR1: the remediation command must archive exactly what the gate says.

    Before 2026-09-08 the gate filtered on prose and ``discover`` filtered on
    turn count, so a two-turn 28 KB session was reported every day and skipped
    by every run of the command the report recommended.
    """

    def _discover(self, tmp_path, monkeypatch, raw_root, archive_root):
        """Run ``bulk-archive.py discover`` at its defaults; return the manifest."""
        manifest_file = tmp_path / "manifest.json"
        monkeypatch.setattr(bulk_archive, "CLAUDE_PROJECTS_DIR", raw_root)
        monkeypatch.setattr(bulk_archive, "DEFAULT_ARCHIVE_ROOT", archive_root)
        monkeypatch.setattr(
            bulk_archive, "CATALOGUE_FILE", archive_root / "CATALOG.json"
        )
        monkeypatch.setattr(bulk_archive, "MANIFEST_FILE", manifest_file)
        # The defaults the remediation line actually runs with — read off the
        # real parser rather than restated, so a changed default breaks here.
        args = argparse.Namespace(
            mode="discover", source_root=raw_root, **_discover_defaults()
        )
        bulk_archive.cmd_discover(
            args, logging.getLogger("discover-under-test")
        )
        return json.loads(manifest_file.read_text(encoding="utf-8"))

    def test_reported_session_is_also_discovered(
        self, stores, tmp_path, monkeypatch
    ) -> None:
        """A two-turn 28 KB session: reported by the gate AND selected."""
        sid = "66666666-6666-4666-8666-666666666666"
        path = _old_substantive(stores.project_dir, sid)
        assert path.stat().st_size > 28_000

        assert drift.main([]) == 1
        manifest = self._discover(
            tmp_path, monkeypatch, stores.raw_root, stores.archive_root
        )
        assert [entry["session_id"] for entry in manifest] == [sid]

    def test_trivial_session_is_neither_reported_nor_discovered(
        self, stores, tmp_path, monkeypatch
    ) -> None:
        """Five short turns: skipped by both, so the gate stays clearable."""
        sid = "77777777-7777-4777-8777-777777777777"
        path = write_transcript(
            stores.project_dir / f"{sid}.jsonl", trivial_records(sid, turns=5)
        )
        age_file(path, hours=96)

        assert drift.main([]) == 0
        manifest = self._discover(
            tmp_path, monkeypatch, stores.raw_root, stores.archive_root
        )
        assert manifest == []
