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
            layout="auto",
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
            layout="auto",
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


# ---------------------------------------------------------------------------
# AR10 — the layout probe must not guess
# ---------------------------------------------------------------------------


class TestLayoutProbe:
    """A store read under the wrong layout is read wrongly and silently."""

    def test_a_live_store_is_recognised(self, pipeline: Pipeline) -> None:
        pipeline.add_session(SID_A)
        assert bulk_archive.detect_source_layout(
            pipeline.raw_root, LOGGER
        ) == "live"

    def test_a_merged_snapshot_is_recognised(self, tmp_path: Path) -> None:
        """Machine directories holding project keys is positive evidence."""
        root = tmp_path / "snapshot"
        for machine in ("amd-tower", "zbook"):
            project = root / machine / "-home-tester-Workshop"
            project.mkdir(parents=True)
            write_transcript(
                project / f"{SID_A}.jsonl", substantive_records(SID_A)
            )
        assert bulk_archive.detect_source_layout(root, LOGGER) == "snapshot"

    def test_session_uuid_directories_are_refused_not_read_as_projects(
        self, tmp_path: Path
    ) -> None:
        """The live store whose top-level transcripts have been archived away.

        Under the old single-negation probe this tree was read as a merged
        snapshot, and each session-UUID directory became a *project key*.
        """
        root = tmp_path / "ambiguous"
        (root / SID_A / "subagents").mkdir(parents=True)
        write_transcript(
            root / SID_A / "subagents" / "agent-1.jsonl",
            substantive_records("agent-1"),
        )

        with pytest.raises(SystemExit) as exit_info:
            bulk_archive.detect_source_layout(root, LOGGER)

        assert exit_info.value.code != 0

    def test_an_explicit_layout_overrides_the_probe(
        self, tmp_path: Path
    ) -> None:
        """The operator who knows better is not blocked by the refusal."""
        root = tmp_path / "ambiguous"
        (root / SID_A).mkdir(parents=True)

        assert bulk_archive.detect_source_layout(
            root, LOGGER, "snapshot"
        ) == "snapshot"
        assert bulk_archive.detect_source_layout(
            root, LOGGER, "live"
        ) == "live"


# ---------------------------------------------------------------------------
# AR12 — the checkpoint is a claim, not evidence
# ---------------------------------------------------------------------------


class TestCheckpointIsVerifiedAgainstDisk:
    """logs/ is synced between machines; the archive is per-machine.

    A checkpoint written on the other machine says "these sessions are
    archived" about an archive that has never held them. Honoured unchecked,
    it made this machine skip them permanently while the drift gate reported
    them forever.
    """

    def test_a_checkpoint_naming_an_unarchived_session_is_dropped(
        self, pipeline: Pipeline, caplog: pytest.LogCaptureFixture
    ) -> None:
        pipeline.add_session(SID_A)
        pipeline.discover()
        pipeline.checkpoint.write_text(json.dumps({
            "started_at": "2026-03-01T00:00:00+00:00",
            "updated_at": "2026-03-01T00:00:00+00:00",
            "archived_ids": [SID_A],
            "skipped_trivial_ids": [],
            "failed_ids": {},
            "stats": {
                "total_archived": 1, "total_subagents": 0,
                "total_compressed_bytes": 0,
            },
        }), encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger=LOGGER.name):
            pipeline.archive()

        assert len(pipeline.entries()) == 1, (
            "a checkpoint from another machine suppressed archiving of a "
            "session this machine has never archived"
        )
        assert any(
            "never archived" in record.message for record in caplog.records
        )
        assert pipeline.checkpoint_state()["archived_ids"] == [SID_A]

    def test_a_checkpoint_matching_disk_still_skips(
        self, pipeline: Pipeline
    ) -> None:
        """The resume behaviour the checkpoint exists for must survive."""
        pipeline.add_session(SID_A)
        pipeline.discover()
        pipeline.archive()
        entries_after_first = pipeline.entries()

        pipeline.archive()

        assert pipeline.entries() == entries_after_first


# ---------------------------------------------------------------------------
# ART14 — the cross-machine tie-break
# ---------------------------------------------------------------------------


class TestCrossMachineTieBreak:
    """"Largest wins" is evidence-backed: 14 quarantined copies were 0 bytes."""

    def test_the_larger_copy_of_a_duplicated_session_is_kept(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "snapshot"
        archive_root = tmp_path / "cc-archives"
        archive_root.mkdir()
        small = root / "amd-tower" / "-home-tester-Workshop"
        large = root / "zbook" / "-home-tester-Workshop"
        write_transcript(
            small / f"{SID_A}.jsonl", substantive_records(SID_A, turns=1)
        )
        write_transcript(
            large / f"{SID_A}.jsonl", substantive_records(SID_A, turns=4)
        )
        for path in (small, large):
            age_file(path / f"{SID_A}.jsonl", hours=96)
        monkeypatch.setattr(bulk_archive, "DEFAULT_ARCHIVE_ROOT", archive_root)
        monkeypatch.setattr(
            bulk_archive, "CATALOGUE_FILE", archive_root / "CATALOG.json"
        )

        pairs = bulk_archive.iter_source_project_dirs(root, LOGGER)
        mapping = bulk_archive.resolve_project_mapping(LOGGER, pairs)
        manifest = bulk_archive.discover_sessions(
            mapping, 0, LOGGER, pairs, min_content_tokens=0,
            min_content_chars=bulk_archive.MIN_CONTENT_CHARS,
        )

        assert len(manifest) == 1
        assert manifest[0]["source_machine"] == "zbook", (
            "the smaller copy won the cross-machine tie-break; a 0-byte "
            "transcript would beat a complete one"
        )
