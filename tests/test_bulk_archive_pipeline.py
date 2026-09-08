"""
Entry-point tests for ``scripts/bulk-archive.py`` against a synthetic store.

``tests/test_bulk_archive.py`` exercises private helpers. Nothing exercised
the commands themselves, so the whole write path — the incremental skip, the
triviality predicate, the checkpoint, the catalogue rebuild — could be
neutered without a single test noticing (audit 2026-09-08, lens B findings 2
and 3).

These tests run ``cmd_discover``, ``cmd_archive``, and ``cmd_verify`` against
an invented ``~/.claude/projects`` tree and an invented archive root under
``tmp_path``, and assert consequences on disk. The compression and metadata
writing is done by the real ``cc_session_toolkit``; only the paths are fake.
No transcript, archive entry, or project name here corresponds to anything
real.
"""

from __future__ import annotations

import argparse
import gzip
import importlib
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

bulk_archive = importlib.import_module("bulk-archive")

LOGGER = logging.getLogger("bulk-archive-pipeline-test")


class Pipeline:
    """A synthetic store pair plus the namespaces the commands expect."""

    def __init__(self, tmp_path: Path) -> None:
        self.raw_root = tmp_path / "claude" / "projects"
        self.project_dir = make_raw_store(self.raw_root)
        self.archive_root = tmp_path / "cc-archives"
        self.archive_root.mkdir(parents=True)
        self.manifest = tmp_path / "manifest.json"
        self.checkpoint = tmp_path / "progress.json"
        self.catalogue = self.archive_root / "CATALOG.json"

    def add_session(
        self, session_id: str, *, records=None, age_hours: float = 96
    ) -> Path:
        """Write one synthetic transcript into the raw store."""
        body = records if records is not None else substantive_records(session_id)
        path = write_transcript(
            self.project_dir / f"{session_id}.jsonl", body
        )
        age_file(path, hours=age_hours)
        return path

    def discover(self, **overrides) -> list[dict]:
        """Run ``discover`` at its defaults and return the manifest."""
        args = argparse.Namespace(
            mode="discover",
            source_root=self.raw_root,
            min_turns=0,
            min_content_tokens=0,
            min_content_chars=bulk_archive.MIN_CONTENT_CHARS,
            **overrides,
        )
        bulk_archive.cmd_discover(args, LOGGER)
        return json.loads(self.manifest.read_text(encoding="utf-8"))

    def archive(self, *, dry_run: bool = False, limit: int = 0) -> None:
        """Run ``archive`` over whatever the manifest currently holds."""
        args = argparse.Namespace(
            mode="archive",
            source_root=self.raw_root,
            dry_run=dry_run,
            limit=limit,
            min_turns=0,
            min_content_tokens=0,
            min_content_chars=bulk_archive.MIN_CONTENT_CHARS,
        )
        bulk_archive.cmd_archive(args, LOGGER)

    def verify(self, *, fix_catalogue: bool = False) -> None:
        """Run ``verify``, optionally rebuilding the catalogue."""
        bulk_archive.cmd_verify(
            argparse.Namespace(mode="verify", fix_catalogue=fix_catalogue),
            LOGGER,
        )

    def checkpoint_state(self) -> dict:
        """The on-disk checkpoint, or the empty default."""
        if not self.checkpoint.exists():
            return {"archived_ids": [], "failed_ids": {}}
        return json.loads(self.checkpoint.read_text(encoding="utf-8"))

    def entries(self) -> list[Path]:
        """Every archive entry directory currently on disk."""
        return sorted(
            p.parent for p in self.archive_root.rglob("session.meta.json")
        )


@pytest.fixture()
def pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Pipeline:
    """Point every module-level path constant at the synthetic tree."""
    harness = Pipeline(tmp_path)
    monkeypatch.setattr(bulk_archive, "CLAUDE_PROJECTS_DIR", harness.raw_root)
    monkeypatch.setattr(
        bulk_archive, "DEFAULT_ARCHIVE_ROOT", harness.archive_root
    )
    monkeypatch.setattr(bulk_archive, "CATALOGUE_FILE", harness.catalogue)
    monkeypatch.setattr(bulk_archive, "MANIFEST_FILE", harness.manifest)
    monkeypatch.setattr(bulk_archive, "CHECKPOINT_FILE", harness.checkpoint)
    return harness


SID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
SID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
SID_C = "cccccccc-3333-4333-8333-cccccccccccc"


# ---------------------------------------------------------------------------
# AR3 — the completeness guard
# ---------------------------------------------------------------------------


class TestCompletenessGuard:
    """A transcript that may still be growing must never become canonical.

    Discovery and archiving are separate commands. Before 2026-09-08 nothing
    between them re-checked the source, so a live session's transcript could
    be copied mid-write; the prefix then WAS the session, and every integrity
    check agreed, because each compared the archive only against itself.
    """

    def test_discover_skips_a_transcript_inside_the_grace_window(
        self, pipeline: Pipeline
    ) -> None:
        """A session written an hour ago is not yet safe to copy."""
        pipeline.add_session(SID_A, age_hours=1)
        pipeline.add_session(SID_B, age_hours=96)

        manifest = pipeline.discover()

        assert [entry["session_id"] for entry in manifest] == [SID_B]

    def test_archive_skips_a_transcript_that_grew_since_discovery(
        self, pipeline: Pipeline
    ) -> None:
        """The window between the two commands is where the prefix slips in."""
        source = pipeline.add_session(SID_A)
        manifest = pipeline.discover()
        assert [entry["session_id"] for entry in manifest] == [SID_A]

        # The session resumed: more prose arrived after discovery ran.
        with source.open("a", encoding="utf-8") as handle:
            for record in substantive_records(SID_A, turns=1):
                handle.write(json.dumps(record) + "\n")
        age_file(source, hours=96)

        pipeline.archive()

        assert pipeline.entries() == [], (
            "a transcript that changed after discovery was archived anyway; "
            "the copy is a prefix and the archive now calls it complete"
        )
        assert pipeline.checkpoint_state()["archived_ids"] == []

    def test_archive_skips_a_transcript_still_inside_the_grace_window(
        self, pipeline: Pipeline
    ) -> None:
        """Re-statting at archive time catches what discovery could not."""
        source = pipeline.add_session(SID_A)
        pipeline.discover()
        # The session woke up again between the two commands.
        age_file(source, hours=0.5)

        pipeline.archive()

        assert pipeline.entries() == []

    def test_archive_writes_a_stable_transcript(
        self, pipeline: Pipeline
    ) -> None:
        """The guard must not refuse the ordinary case."""
        pipeline.add_session(SID_A)
        pipeline.discover()
        pipeline.archive()

        entries = pipeline.entries()
        assert len(entries) == 1
        assert (entries[0] / "session.jsonl.gz").exists()
        meta = json.loads(
            (entries[0] / "session.meta.json").read_text(encoding="utf-8")
        )
        assert meta["session"]["id"] == SID_A
        assert pipeline.checkpoint_state()["archived_ids"] == [SID_A]

    def test_verify_flags_a_transcript_shorter_than_its_metadata(
        self, pipeline: Pipeline, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The truncation backstop: the archive checked against its own claim."""
        entry = make_archive_entry(pipeline.archive_root, SID_A)
        meta_path = entry / "session.meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        # A prefix: the transcript holds less than the metadata records.
        with gzip.open(entry / "session.jsonl.gz", "wb") as handle:
            handle.write(b'{"type": "user"}\n')
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        pipeline.verify()

        report = capsys.readouterr().out
        assert "Size mismatch" in report
        assert str(entry) in report

    def test_verify_is_quiet_when_sizes_agree(
        self, pipeline: Pipeline, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A correct archive must not be reported as truncated."""
        make_archive_entry(pipeline.archive_root, SID_A)

        pipeline.verify()

        report = capsys.readouterr().out
        assert "Size mismatch" not in report
        assert "No integrity issues found" in report

    def test_verify_reports_a_missing_transcript(
        self, pipeline: Pipeline, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An entry with metadata but no transcript is not an archived session."""
        entry = make_archive_entry(
            pipeline.archive_root, SID_A, with_transcript=False
        )

        pipeline.verify()

        report = capsys.readouterr().out
        assert f"Missing JSONL: {entry}" in report


# ---------------------------------------------------------------------------
# Selection: the incremental skip and the triviality predicate
# ---------------------------------------------------------------------------


class TestDiscoverSelection:
    """What ``discover`` puts in the manifest, and what it leaves out."""

    def test_already_archived_session_is_skipped(
        self, pipeline: Pipeline
    ) -> None:
        """Disk is the dedup key: a meta on disk means done."""
        pipeline.add_session(SID_A)
        make_archive_entry(pipeline.archive_root, SID_A)

        assert pipeline.discover() == []

    def test_trivial_session_is_skipped(self, pipeline: Pipeline) -> None:
        """Below the prose floor, whatever the turn count."""
        pipeline.add_session(SID_A, records=trivial_records(SID_A, turns=6))

        assert pipeline.discover() == []

    def test_a_ghost_catalogue_entry_does_not_suppress_archiving(
        self, pipeline: Pipeline, caplog: pytest.LogCaptureFixture
    ) -> None:
        """CATALOG.json is a derived index, never the dedup key (AR2).

        A catalogued id with no ``session.meta.json`` on disk is a ghost. It
        used to make discovery skip the session while the drift check — which
        reads metas only — kept reporting it, so the two disagreed forever.
        """
        pipeline.add_session(SID_A)
        pipeline.catalogue.write_text(
            json.dumps({"sessions": [{"id": SID_A, "title": "ghost"}]}),
            encoding="utf-8",
        )

        with caplog.at_level(logging.WARNING, logger=LOGGER.name):
            manifest = pipeline.discover()

        assert [entry["session_id"] for entry in manifest] == [SID_A], (
            "a catalogue entry with no metadata on disk suppressed archiving"
        )
        assert any("ghost" in record.message for record in caplog.records), (
            "the ghost count must be reported, not silently absorbed"
        )

    def test_a_catalogued_and_archived_session_is_still_skipped(
        self, pipeline: Pipeline
    ) -> None:
        """Dropping the catalogue union must not disable the real skip."""
        pipeline.add_session(SID_A)
        make_archive_entry(pipeline.archive_root, SID_A)
        pipeline.catalogue.write_text(
            json.dumps({"sessions": [{"id": SID_A}]}), encoding="utf-8"
        )

        assert pipeline.discover() == []

    def test_flat_agent_transcripts_are_skipped(
        self, pipeline: Pipeline
    ) -> None:
        """``agent-*.jsonl`` are subagent records, not sessions."""
        path = write_transcript(
            pipeline.project_dir / "agent-4b19f2.jsonl",
            substantive_records("agent-4b19f2"),
        )
        age_file(path, hours=96)

        assert pipeline.discover() == []
