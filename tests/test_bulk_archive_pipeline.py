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
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from archive_fixtures import (  # noqa: E402
    age_file,
    make_archive_entry,
    make_raw_store,
    prose_record,
    substantive_records,
    tool_result_record,
    tool_use_record,
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
        fields = {
            "mode": "discover",
            "source_root": self.raw_root,
            "min_turns": 0,
            "min_content_tokens": 0,
            "min_content_chars": bulk_archive.MIN_CONTENT_CHARS,
            "layout": "auto",
        }
        fields.update(overrides)
        args = argparse.Namespace(**fields)
        bulk_archive.cmd_discover(args, LOGGER)
        return json.loads(self.manifest.read_text(encoding="utf-8"))

    def archive(
        self, *, dry_run: bool = False, limit: int = 0,
        retry_failed: bool = False,
    ) -> None:
        """Run ``archive`` over whatever the manifest currently holds."""
        args = argparse.Namespace(
            mode="archive",
            source_root=self.raw_root,
            dry_run=dry_run,
            limit=limit,
            retry_failed=retry_failed,
            min_turns=0,
            min_content_tokens=0,
            min_content_chars=bulk_archive.MIN_CONTENT_CHARS,
            layout="auto",
        )
        bulk_archive.cmd_archive(args, LOGGER)

    def verify(self, *, fix_catalogue: bool = False) -> int:
        """Run ``verify``, optionally rebuilding the catalogue.

        Returns its exit status, so callers can assert on it.
        """
        return bulk_archive.cmd_verify(
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



def _stub_anthropic_batch(custom_id: str, payload: dict):
    """An ``anthropic`` module whose batch results carry one scripted reply."""
    block = types.SimpleNamespace(text=json.dumps(payload))
    result = types.SimpleNamespace(
        custom_id=custom_id,
        result=types.SimpleNamespace(
            type="succeeded",
            message=types.SimpleNamespace(content=[block]),
        ),
    )

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            self.messages = types.SimpleNamespace(
                batches=types.SimpleNamespace(
                    retrieve=lambda batch_id: types.SimpleNamespace(
                        processing_status="ended",
                        request_counts=types.SimpleNamespace(
                            succeeded=1, errored=0, processing=0
                        ),
                    ),
                    results=lambda batch_id: iter([result]),
                )
            )

    module = types.ModuleType("anthropic")
    module.Anthropic = _Client
    return module


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

    def test_archive_skips_a_transcript_that_grew_and_is_still_live(
        self, pipeline: Pipeline
    ) -> None:
        """The window between the two commands is where the prefix slips in.

        Growth plus a fresh mtime is the dangerous combination: the session
        resumed and may still be appending, so any copy is a prefix.
        """
        source = pipeline.add_session(SID_A)
        manifest = pipeline.discover()
        assert [entry["session_id"] for entry in manifest] == [SID_A]

        # The session resumed after discovery and is writing right now.
        with source.open("a", encoding="utf-8") as handle:
            for record in substantive_records(SID_A, turns=1):
                handle.write(json.dumps(record) + "\n")
        age_file(source, hours=0.1)

        pipeline.archive()

        assert pipeline.entries() == [], (
            "a transcript that was still being written was archived anyway; "
            "the copy is a prefix and the archive now calls it complete"
        )
        assert pipeline.checkpoint_state()["archived_ids"] == []

    def test_a_grown_but_quiescent_transcript_is_archived_in_full(
        self, pipeline: Pipeline
    ) -> None:
        """A stale manifest is not evidence that the file is moving.

        Discovery already skipped anything inside the grace window, so a
        manifested session was quiescent when listed. If it is quiescent
        again now, a size difference says the manifest is out of date — and
        refusing on it made the refusal permanent, because the manifest kept
        the old size (round 4c-2, finding 1).
        """
        source = pipeline.add_session(SID_A)
        pipeline.discover()
        with source.open("a", encoding="utf-8") as handle:
            for record in substantive_records(SID_A, turns=1):
                handle.write(json.dumps(record) + "\n")
        age_file(source, hours=96)
        expected = source.read_text(encoding="utf-8")

        pipeline.archive()

        entries = pipeline.entries()
        assert len(entries) == 1
        with gzip.open(entries[0] / "session.jsonl.gz", "rt", encoding="utf-8") as fh:
            assert fh.read() == expected, (
                "the archive holds the prefix discovery saw, not the whole "
                "transcript"
            )

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


# ---------------------------------------------------------------------------
# AR13, AR14, AR16 — nothing good is overwritten, nothing is half-written
# ---------------------------------------------------------------------------


class TestSubagentArchivesAreNotClobbered:
    """A subagent transcript is a research record in its own right."""

    def _source(self, tmp_path: Path, body: str) -> Path:
        source = tmp_path / "source"
        (source / "subagents").mkdir(parents=True, exist_ok=True)
        (source / "subagents" / "agent-7c31.jsonl").write_text(
            body, encoding="utf-8"
        )
        return source

    def test_an_existing_archive_is_left_alone(self, tmp_path: Path) -> None:
        """A re-run must not replace a good archive with today's source."""
        source = self._source(tmp_path, '{"turn": "complete record"}\n')
        archive_dir = tmp_path / "entry"
        archive_dir.mkdir()
        assert bulk_archive.archive_subagents(source, archive_dir, LOGGER) == 1

        # The source has since been truncated — a live store being cleaned.
        (source / "subagents" / "agent-7c31.jsonl").write_text(
            "", encoding="utf-8"
        )
        assert bulk_archive.archive_subagents(source, archive_dir, LOGGER) == 0

        with gzip.open(
            archive_dir / "subagents" / "agent-7c31.jsonl.gz", "rt"
        ) as handle:
            assert handle.read() == '{"turn": "complete record"}\n'

    def test_force_overwrites_deliberately(self, tmp_path: Path) -> None:
        """The escape hatch exists, and it is opt-in."""
        source = self._source(tmp_path, '{"turn": "first"}\n')
        archive_dir = tmp_path / "entry"
        archive_dir.mkdir()
        bulk_archive.archive_subagents(source, archive_dir, LOGGER)
        (source / "subagents" / "agent-7c31.jsonl").write_text(
            '{"turn": "second"}\n', encoding="utf-8"
        )

        assert bulk_archive.archive_subagents(
            source, archive_dir, LOGGER, force=True
        ) == 1
        with gzip.open(
            archive_dir / "subagents" / "agent-7c31.jsonl.gz", "rt"
        ) as handle:
            assert handle.read() == '{"turn": "second"}\n'

    def test_a_failed_write_leaves_no_partial_archive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An interrupted compression must not look like a finished one."""
        source = self._source(tmp_path, '{"turn": "complete record"}\n')
        archive_dir = tmp_path / "entry"
        archive_dir.mkdir()

        real_open = gzip.open

        def boom(*args, **kwargs):
            handle = real_open(*args, **kwargs)
            handle.write(b'{"turn": "par')
            raise OSError("interrupted mid-write")

        monkeypatch.setattr(bulk_archive.gzip, "open", boom)
        assert bulk_archive.archive_subagents(source, archive_dir, LOGGER) == 0
        monkeypatch.setattr(bulk_archive.gzip, "open", real_open)

        dest = archive_dir / "subagents"
        assert not (dest / "agent-7c31.jsonl.gz").exists(), (
            "a truncated archive was left where a complete one belongs"
        )
        assert list(dest.glob("*.tmp")) == []


class TestEnrichmentWritersMerge:
    """Neither enrichment path may drop metadata the other wrote.

    Both paths write session.meta.json and both must merge rather than
    replace: the Terra path writes a three_ps block, the Haiku batch path
    does not, and whichever runs second used to delete what the first left.

    These tests execute the real writers. The versions they replace
    re-implemented the merge inline (asserting the test's own arithmetic) and
    grepped the source text for `**existing,` — neither of which can fail
    when the production code changes shape (round 4c-2, findings 23, 24, 25).
    """

    THREE_PS = {
        "prompt_summary": "Asked how the grid meets the terrace edge.",
        "process_summary": "Compared contour-following and downslope grids.",
        "provenance_summary": "Follows the 2026-02 reconnaissance visit.",
    }

    def _entry_with_three_ps(self, tmp_path: Path) -> Path:
        """An archive entry already enriched by the Terra path."""
        entry = tmp_path / "entry"
        entry.mkdir()
        (entry / "session.meta.json").write_text(json.dumps({
            "session": {"id": SID_A},
            "project": {"name": "lantern-survey"},
            "auto_generated": {
                "title": "Old title",
                "purpose": "Old purpose",
                "tags": ["old"],
                "three_ps": dict(self.THREE_PS),
            },
            "three_ps": dict(self.THREE_PS),
            "extractor_model_id": "gpt-5.6-terra",
        }, indent=2), encoding="utf-8")
        return entry

    def _meta(self, entry: Path) -> dict:
        return json.loads(
            (entry / "session.meta.json").read_text(encoding="utf-8")
        )

    def test_the_haiku_batch_apply_keeps_the_terra_three_ps(
        self, pipeline: Pipeline, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_enrich_apply, executed — not its source text."""
        entry = self._entry_with_three_ps(tmp_path)
        state_dir = tmp_path / "batch-state"
        monkeypatch.setattr(bulk_archive, "BATCH_STATE_DIR", state_dir)
        monkeypatch.setattr(
            bulk_archive, "BATCH_STATE_FILE", tmp_path / "legacy.json"
        )
        bulk_archive.save_state(
            {
                "batch_id": "msgbatch_enrich",
                "n_requests": 1,
                "session_id_map": {f"session-{SID_A}": str(entry)},
            },
            state_dir, tmp_path / "legacy.json",
        )
        monkeypatch.setitem(
            sys.modules, "anthropic",
            _stub_anthropic_batch(f"session-{SID_A}", {
                "title": "New title",
                "purpose": "New purpose",
                "tags": ["new"],
            }),
        )

        bulk_archive._enrich_apply("msgbatch_enrich", LOGGER)

        auto = self._meta(entry)["auto_generated"]
        assert auto["title"] == "New title"
        assert auto["tags"] == ["new"]
        assert auto["three_ps"] == self.THREE_PS, (
            "the Haiku batch apply deleted the Terra three-Ps summaries"
        )

    def test_the_terra_writer_keeps_fields_it_does_not_set(
        self, tmp_path: Path
    ) -> None:
        """_write_enriched_meta, executed (finding 23).

        Deleting `**existing,` from this function survived the whole suite:
        the Terra in-place path would then replace auto_generated wholesale,
        which is AR13 again on the sibling path.
        """
        entry = self._entry_with_three_ps(tmp_path)
        meta = self._meta(entry)
        meta["auto_generated"]["reviewed_by"] = "shawn"
        meta["auto_generated"]["review_note"] = "checked against field notes"
        (entry / "session.meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

        assert bulk_archive._write_enriched_meta(
            entry,
            {
                "title": "Terra title",
                "purpose": "Terra purpose",
                "tags": ["terra"],
                "three_ps": {
                    "prompt_summary": "New prompt summary.",
                    "process_summary": "New process summary.",
                    "provenance_summary": "New provenance summary.",
                },
            },
            LOGGER,
        ) is True

        auto = self._meta(entry)["auto_generated"]
        assert auto["title"] == "Terra title"
        assert auto["three_ps"]["prompt_summary"] == "New prompt summary."
        assert auto["reviewed_by"] == "shawn", (
            "_write_enriched_meta replaced auto_generated wholesale; every "
            "field it does not itself set is gone"
        )
        assert auto["review_note"] == "checked against field notes"

    def test_the_terra_writer_stages_its_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A crash mid-write must leave the previous metadata readable."""
        entry = self._entry_with_three_ps(tmp_path)
        before = (entry / "session.meta.json").read_text(encoding="utf-8")

        real_replace = Path.replace
        monkeypatch.setattr(
            Path, "replace",
            lambda self, target: (_ for _ in ()).throw(OSError("interrupted")),
        )
        assert bulk_archive._write_enriched_meta(
            entry, {"title": "T", "purpose": "P", "tags": []}, LOGGER
        ) is False
        monkeypatch.setattr(Path, "replace", real_replace)

        assert (entry / "session.meta.json").read_text(
            encoding="utf-8"
        ) == before

    def test_the_batch_apply_stages_its_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same guarantee on the batch path."""
        entry = self._entry_with_three_ps(tmp_path)
        before = (entry / "session.meta.json").read_text(encoding="utf-8")
        state_dir = tmp_path / "batch-state"
        monkeypatch.setattr(bulk_archive, "BATCH_STATE_DIR", state_dir)
        monkeypatch.setattr(
            bulk_archive, "BATCH_STATE_FILE", tmp_path / "legacy.json"
        )
        bulk_archive.save_state(
            {
                "batch_id": "msgbatch_enrich",
                "n_requests": 1,
                "session_id_map": {f"session-{SID_A}": str(entry)},
            },
            state_dir, tmp_path / "legacy.json",
        )
        monkeypatch.setitem(
            sys.modules, "anthropic",
            _stub_anthropic_batch(f"session-{SID_A}", {
                "title": "New title", "purpose": "New", "tags": [],
            }),
        )

        real_replace = Path.replace
        monkeypatch.setattr(
            Path, "replace",
            lambda self, target: (_ for _ in ()).throw(OSError("interrupted")),
        )
        bulk_archive._enrich_apply("msgbatch_enrich", LOGGER)
        monkeypatch.setattr(Path, "replace", real_replace)

        assert (entry / "session.meta.json").read_text(
            encoding="utf-8"
        ) == before


class TestCatalogueWrites:
    """AR16 — the catalogue is rebuilt atomically and read defensively."""

    def test_a_crash_leaves_the_previous_catalogue_intact(
        self, pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pipeline.catalogue.write_text(
            json.dumps({"sessions": [{"id": SID_B}]}), encoding="utf-8"
        )
        before = pipeline.catalogue.read_text(encoding="utf-8")

        real_replace = Path.replace

        def boom(self, target):
            raise OSError("interrupted")

        monkeypatch.setattr(Path, "replace", boom)
        with pytest.raises(OSError):
            bulk_archive.write_catalogue({"sessions": []}, LOGGER)
        monkeypatch.setattr(Path, "replace", real_replace)

        assert pipeline.catalogue.read_text(encoding="utf-8") == before

    @pytest.mark.parametrize("corruption", [
        # A write cut off mid-array: the shape a crashed rebuild leaves.
        '{"sessions": [',
        # Valid JSON of the wrong shape — the toolkit's own guard catches
        # JSONDecodeError and KeyError, so this is the case that reached
        # discover as an unhandled TypeError and took the command down.
        '{"sessions": [1, 2, 3]}',
        '{"sessions": "not-a-list"}',
    ])
    def test_a_corrupt_catalogue_does_not_stop_discovery(
        self, pipeline: Pipeline, corruption: str
    ) -> None:
        """discover reads the catalogue on every run; it must not die on it."""
        pipeline.add_session(SID_A)
        pipeline.catalogue.write_text(corruption, encoding="utf-8")

        manifest = pipeline.discover()

        assert [entry["session_id"] for entry in manifest] == [SID_A]

    def test_verify_rebuilds_the_catalogue_from_disk(
        self, pipeline: Pipeline
    ) -> None:
        make_archive_entry(pipeline.archive_root, SID_A)
        pipeline.catalogue.write_text(
            json.dumps({"sessions": []}), encoding="utf-8"
        )

        pipeline.verify(fix_catalogue=True)

        catalogue = json.loads(
            pipeline.catalogue.read_text(encoding="utf-8")
        )
        assert [entry["id"] for entry in catalogue["sessions"]] == [SID_A]
        assert list(pipeline.archive_root.glob("CATALOG.json.tmp")) == []


# ---------------------------------------------------------------------------
# AR15 — the token counter needs the toolkit already on sys.path
# ---------------------------------------------------------------------------


class TestTokenCounterOrdering:
    """``--min-content-tokens`` used to be the one floor that could not run.

    ``_make_token_counter`` importlib-loads ``extract-transcript-text.py``,
    which imports ``cc_session_toolkit`` at module scope. It was built BEFORE
    the toolkit's ``src`` was put on ``sys.path``, so the preferred floor died
    with "No module named cc_session_toolkit" and exit 1.
    """

    def test_the_toolkit_path_is_added_before_the_counter_is_built(
        self, pipeline: Pipeline, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        toolkit_src = tmp_path / "Code" / "cc-session-toolkit" / "src"
        toolkit_src.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(tmp_path))
        pipeline.add_session(SID_A)

        observed: dict[str, bool] = {}

        def spy(logger):
            observed["on_path"] = str(toolkit_src) in sys.path
            return lambda jsonl_file: 10_000

        monkeypatch.setattr(bulk_archive, "_make_token_counter", spy)
        monkeypatch.setattr(
            sys, "path", [p for p in sys.path if p != str(toolkit_src)]
        )

        pipeline.discover(min_content_tokens=1_000)

        assert observed.get("on_path") is True, (
            "the distilled-token counter was built before cc_session_toolkit "
            "was importable; --min-content-tokens cannot run"
        )


# ---------------------------------------------------------------------------
# AR21 — verify and the search engine must agree on what an archive is
# ---------------------------------------------------------------------------


class TestCanonicalStorageIsEnforcedByVerify:
    """A raw-only entry is invisible to every ad-hoc search.

    ``_scan_archives.py`` globs only ``session.jsonl.gz``, because gz is the
    canonical storage form (decided 2026-08-22). verify accepted a raw
    ``session.jsonl`` as equally fine, so an entry nobody could search
    reported clean forever.
    """

    def test_a_raw_only_entry_is_reported(
        self, pipeline: Pipeline, capsys: pytest.CaptureFixture[str]
    ) -> None:
        entry = make_archive_entry(
            pipeline.archive_root, SID_A, with_transcript=False
        )
        (entry / "session.jsonl").write_text(
            '{"type": "user", "message": {"role": "user", "content": "hi"}}\n',
            encoding="utf-8",
        )

        pipeline.verify()

        report = capsys.readouterr().out
        assert "Non-canonical storage" in report
        assert str(entry) in report

    def test_a_gz_entry_is_not_reported(
        self, pipeline: Pipeline, capsys: pytest.CaptureFixture[str]
    ) -> None:
        make_archive_entry(pipeline.archive_root, SID_A)

        pipeline.verify()

        assert "Non-canonical storage" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The archive command's own contract: what lands, what is recorded, what is
# refused (lens B finding 3 — no test ran any cmd_* entry point at all)
# ---------------------------------------------------------------------------


class TestArchiveCommandContract:
    """What ``archive`` writes, what it records, and what it must not swallow."""

    def test_dry_run_writes_nothing(self, pipeline: Pipeline) -> None:
        pipeline.add_session(SID_A)
        pipeline.discover()

        pipeline.archive(dry_run=True)

        assert pipeline.entries() == []
        assert not pipeline.checkpoint.exists()

    def test_a_failure_is_recorded_and_the_run_continues(
        self, pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One bad session must not cost the other 599."""
        pipeline.add_session(SID_A)
        pipeline.add_session(SID_B)
        pipeline.discover()

        from cc_session_toolkit import archive as toolkit_archive
        real_archive = toolkit_archive.archive_session

        def fail_on_a(*, session_path, **kwargs):
            if SID_A in str(session_path):
                raise RuntimeError("synthetic archive failure")
            return real_archive(session_path=session_path, **kwargs)

        monkeypatch.setattr(toolkit_archive, "archive_session", fail_on_a)

        pipeline.archive()

        state = pipeline.checkpoint_state()
        assert state["archived_ids"] == [SID_B]
        assert SID_A in state["failed_ids"]
        record = state["failed_ids"][SID_A]
        assert "synthetic archive failure" in record["reason"]
        # A timestamp, so the entry can age out instead of blocking forever.
        assert record["recorded_at"]

    def test_a_keyboard_interrupt_is_not_swallowed(
        self, pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``except Exception`` is deliberate; BaseException would not be.

        Widening it would make Ctrl-C look like a per-session failure: the
        run would record the interrupt in failed_ids and carry on.
        """
        pipeline.add_session(SID_A)
        pipeline.discover()

        from cc_session_toolkit import archive as toolkit_archive

        def interrupted(**kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(toolkit_archive, "archive_session", interrupted)

        with pytest.raises(KeyboardInterrupt):
            pipeline.archive()

    def test_the_checkpoint_is_written_as_each_session_lands(
        self, pipeline: Pipeline
    ) -> None:
        """Dropping the checkpoint update makes every resume re-archive all."""
        pipeline.add_session(SID_A)
        pipeline.add_session(SID_B)
        pipeline.discover()

        pipeline.archive()

        assert sorted(pipeline.checkpoint_state()["archived_ids"]) == sorted(
            [SID_A, SID_B]
        )
        assert pipeline.checkpoint_state()["stats"]["total_archived"] == 2

    def test_subagents_are_archived_beside_their_session(
        self, pipeline: Pipeline
    ) -> None:
        """A subagent transcript is a research record, archived in full.

        Pins two things that were separately removable: that the
        ``subagents`` directory is looked for at all, and that the copy
        streams the WHOLE file rather than one 8 KiB block.
        """
        pipeline.add_session(SID_A)
        subagents = pipeline.project_dir / SID_A / "subagents"
        subagents.mkdir(parents=True)
        body = "".join(
            json.dumps({"type": "assistant", "seq": n, "pad": "z" * 200})
            + "\n"
            for n in range(200)
        )
        assert len(body) > 8192, "the fixture must exceed one read block"
        (subagents / "agent-5a7b.jsonl").write_text(body, encoding="utf-8")

        manifest = pipeline.discover()
        assert manifest[0]["subagent_count"] == 1, (
            "discovery did not see the subagents directory"
        )

        pipeline.archive()

        archived = list(
            pipeline.archive_root.rglob("subagents/agent-5a7b.jsonl.gz")
        )
        assert len(archived) == 1
        with gzip.open(archived[0], "rt", encoding="utf-8") as handle:
            assert handle.read() == body, (
                "the subagent archive is truncated; only the first block of "
                "the transcript was copied"
            )


class TestSubagentsCommand:
    """``subagents`` backfills orphans into archives that predate them."""

    def test_an_orphan_is_attached_to_its_archived_parent(
        self, pipeline: Pipeline
    ) -> None:
        entry = make_archive_entry(pipeline.archive_root, SID_A)
        orphan = pipeline.project_dir / "agent-9d0e.jsonl"
        orphan.write_text(
            json.dumps({"sessionId": SID_A, "type": "assistant"}) + "\n",
            encoding="utf-8",
        )

        bulk_archive.cmd_subagents(
            argparse.Namespace(
                mode="subagents", source_root=pipeline.raw_root,
                dry_run=False,
            ),
            LOGGER,
        )

        assert (entry / "subagents" / "agent-9d0e.jsonl.gz").exists()

    def test_dry_run_attaches_nothing(self, pipeline: Pipeline) -> None:
        entry = make_archive_entry(pipeline.archive_root, SID_A)
        orphan = pipeline.project_dir / "agent-9d0e.jsonl"
        orphan.write_text(
            json.dumps({"sessionId": SID_A, "type": "assistant"}) + "\n",
            encoding="utf-8",
        )

        bulk_archive.cmd_subagents(
            argparse.Namespace(
                mode="subagents", source_root=pipeline.raw_root, dry_run=True,
            ),
            LOGGER,
        )

        assert not (entry / "subagents").exists()

    def test_an_orphan_with_no_archived_parent_is_quarantined_not_dropped(
        self, pipeline: Pipeline
    ) -> None:
        """Some subagents outlived their session file entirely."""
        orphan = pipeline.project_dir / "agent-1c2d.jsonl"
        orphan.write_text(
            json.dumps({"sessionId": SID_C, "type": "assistant"}) + "\n",
            encoding="utf-8",
        )

        bulk_archive.cmd_subagents(
            argparse.Namespace(
                mode="subagents", source_root=pipeline.raw_root,
                dry_run=False,
            ),
            LOGGER,
        )

        held = (
            pipeline.archive_root / "_legacy" / "_orphan-subagents" / SID_C
            / "subagents" / "agent-1c2d.jsonl.gz"
        )
        assert held.exists(), "an unattachable subagent was discarded"


class TestLegacyRelocation:
    """Sessions launched from outside a project tree have a filing precedent."""

    def test_a_new_entry_joins_its_existing_legacy_directory(
        self, pipeline: Pipeline
    ) -> None:
        """Without this the same project splits across two locations."""
        legacy = pipeline.archive_root / "_legacy" / "workshop"
        legacy.mkdir(parents=True)
        fresh = pipeline.archive_root / "workshop" / "2026-03-02_entry"
        fresh.mkdir(parents=True)
        (fresh / "session.meta.json").write_text("{}", encoding="utf-8")

        moved = bulk_archive.relocate_to_legacy_precedent(
            [fresh], pipeline.archive_root, LOGGER
        )

        assert moved == 1
        assert (legacy / "2026-03-02_entry" / "session.meta.json").exists()
        assert not fresh.exists()

    def test_no_precedent_means_no_move(self, pipeline: Pipeline) -> None:
        """This step must never invent a new legacy project."""
        fresh = pipeline.archive_root / "workshop" / "2026-03-02_entry"
        fresh.mkdir(parents=True)
        (fresh / "session.meta.json").write_text("{}", encoding="utf-8")

        assert bulk_archive.relocate_to_legacy_precedent(
            [fresh], pipeline.archive_root, LOGGER
        ) == 0
        assert fresh.exists()


class TestUserMessageSampling:
    """The enrichment prompt is built from what the operator actually said."""

    def test_tool_results_are_not_sampled_as_user_prose(
        self, tmp_path: Path
    ) -> None:
        """A tool_result is the machine talking back, not a user message."""
        path = write_transcript(tmp_path / "s.jsonl", [
            prose_record("user", "Plan the terrace survey grid properly.", index=1),
            tool_use_record(2),
            tool_result_record(3),
            prose_record("user", "Now write the field notes template.", index=4),
        ])

        sampled, _files = bulk_archive._sample_user_messages(path)

        assert all("wrote 4 lines" not in message for message in sampled), (
            "tool output was sampled into the enrichment prompt as the "
            "operator's own words"
        )
        assert any("terrace survey grid" in message for message in sampled)

    def test_the_last_messages_are_kept_as_well_as_the_first(
        self, tmp_path: Path
    ) -> None:
        """First 2 + last 2: dropping the tail loses where a session ended."""
        records = []
        for n in range(6):
            records.append(prose_record(
                "user", f"Substantive question number {n} about the survey.",
                index=n + 1,
            ))
        path = write_transcript(tmp_path / "s.jsonl", records)

        sampled, _files = bulk_archive._sample_user_messages(path)

        assert any("number 5" in message for message in sampled), (
            "the final user messages were dropped from the sample"
        )
        assert any("number 0" in message for message in sampled)


# ---------------------------------------------------------------------------
# Round 4c-2 finding 1 — a recorded failure must not be permanent
# ---------------------------------------------------------------------------


class TestFailedIdsAreRetried:
    """A failure is a moment, not a verdict.

    The to_archive filter skips anything in failed_ids, and AR12's self-heal
    pruned archived_ids against disk but left failed_ids untouched. So AR3
    traded "silently truncated" for "permanently unarchivable": a session
    that grew during a copy, or a failure entry synced from the other
    machine, blocked archiving here on every future run while the drift gate
    reported it forever.
    """

    def _checkpoint(self, pipeline: Pipeline, failed: dict) -> None:
        pipeline.checkpoint.write_text(json.dumps({
            "started_at": "2026-03-01T00:00:00+00:00",
            "updated_at": "2026-03-01T00:00:00+00:00",
            "archived_ids": [],
            "skipped_trivial_ids": [],
            "failed_ids": failed,
            "stats": {
                "total_archived": 0, "total_subagents": 0,
                "total_compressed_bytes": 0,
            },
        }), encoding="utf-8")

    def test_a_grown_then_stable_session_archives_on_the_second_run(
        self, pipeline: Pipeline
    ) -> None:
        """No flags, no re-discovery: the retry is automatic."""
        source = pipeline.add_session(SID_A)
        pipeline.discover()

        # First run: the session is live again, so the guard refuses.
        with source.open("a", encoding="utf-8") as handle:
            for record in substantive_records(SID_A, turns=1):
                handle.write(json.dumps(record) + "\n")
        age_file(source, hours=0.1)
        pipeline.archive()
        assert pipeline.entries() == []

        # Second run: the session has been quiet for days.
        age_file(source, hours=96)
        pipeline.archive()

        assert len(pipeline.entries()) == 1, (
            "a session refused once was never retried"
        )
        assert pipeline.checkpoint_state()["archived_ids"] == [SID_A]

    def test_a_transient_failure_is_retried_without_flags(
        self, pipeline: Pipeline
    ) -> None:
        pipeline.add_session(SID_A)
        pipeline.discover()
        self._checkpoint(pipeline, {SID_A: {
            "reason": "source changed DURING the copy (10 -> 20 bytes)",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }})

        pipeline.archive()

        assert len(pipeline.entries()) == 1
        assert pipeline.checkpoint_state()["failed_ids"] == {}

    def test_a_failure_for_a_session_now_on_disk_is_dropped(
        self, pipeline: Pipeline
    ) -> None:
        """The record is simply wrong; some other path archived it."""
        make_archive_entry(pipeline.archive_root, SID_A)
        pipeline.add_session(SID_B)
        pipeline.discover()
        self._checkpoint(pipeline, {SID_A: {
            "reason": "disk full",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }})

        pipeline.archive()

        assert SID_A not in pipeline.checkpoint_state()["failed_ids"]

    def test_an_aged_failure_is_retried(self, pipeline: Pipeline) -> None:
        pipeline.add_session(SID_A)
        pipeline.discover()
        old = datetime.now(timezone.utc) - timedelta(
            days=bulk_archive.FAILED_RETRY_AFTER_DAYS + 1
        )
        self._checkpoint(pipeline, {SID_A: {
            "reason": "no space left on device",
            "recorded_at": old.isoformat(),
        }})

        pipeline.archive()

        assert len(pipeline.entries()) == 1

    def test_a_recent_hard_failure_still_blocks(
        self, pipeline: Pipeline
    ) -> None:
        """The retry must not become "ignore failures entirely"."""
        pipeline.add_session(SID_A)
        pipeline.discover()
        self._checkpoint(pipeline, {SID_A: {
            "reason": "no space left on device",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }})

        pipeline.archive()

        assert pipeline.entries() == []
        assert SID_A in pipeline.checkpoint_state()["failed_ids"]

    def test_retry_failed_clears_even_a_recent_hard_failure(
        self, pipeline: Pipeline
    ) -> None:
        pipeline.add_session(SID_A)
        pipeline.discover()
        self._checkpoint(pipeline, {SID_A: {
            "reason": "no space left on device",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }})

        pipeline.archive(retry_failed=True)

        assert len(pipeline.entries()) == 1

    def test_a_legacy_bare_string_failure_is_retried_once(
        self, pipeline: Pipeline
    ) -> None:
        """Entries written before this change carry no timestamp to age."""
        pipeline.add_session(SID_A)
        pipeline.discover()
        self._checkpoint(pipeline, {SID_A: "archive_session returned None"})

        pipeline.archive()

        assert len(pipeline.entries()) == 1

    def test_the_retry_decision_is_made_in_memory_not_by_the_rewrite(
        self, pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The selection must use the pruned set, not the file it wrote.

        With the checkpoint write suppressed, a run that still archives the
        session proves ``already_failed`` itself was pruned — rather than the
        skip being lifted as a side effect of rewriting failed_ids to disk.
        """
        pipeline.add_session(SID_A)
        pipeline.discover()
        self._checkpoint(pipeline, {SID_A: {
            "reason": "source changed DURING the copy (10 -> 20 bytes)",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }})
        monkeypatch.setattr(bulk_archive, "_save_checkpoint", lambda cp: None)

        pipeline.archive()

        assert len(pipeline.entries()) == 1


# ---------------------------------------------------------------------------
# Round 4c-2 finding 2 — the progress file must never take the command down
# ---------------------------------------------------------------------------


class TestCheckpointDurability:
    """A progress file is an optimisation; it must not be a failure mode.

    logs/bulk-archive-progress.json is tracked in the private data submodule,
    so it can arrive with git conflict markers in it, and a crash mid-write
    left it truncated. Either way json.loads raised and `archive` died before
    doing any work.
    """

    @pytest.mark.parametrize("corruption", [
        '{"archived_ids": [',
        "<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> origin/main\n",
        "",
        "[1, 2, 3]",
        '{"archived_ids": "not-a-list", "failed_ids": 7}',
    ])
    def test_a_corrupt_checkpoint_is_treated_as_empty(
        self, pipeline: Pipeline, corruption: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        pipeline.add_session(SID_A)
        pipeline.discover()
        pipeline.checkpoint.write_text(corruption, encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger=LOGGER.name):
            pipeline.archive()

        assert len(pipeline.entries()) == 1, (
            "an unreadable progress file stopped the archive run"
        )

    def test_an_unreadable_checkpoint_is_reported(
        self, pipeline: Pipeline, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Treated as empty, but never silently."""
        pipeline.checkpoint.write_text('{"archived_ids": [', encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger=LOGGER.name):
            bulk_archive._load_checkpoint(LOGGER)

        assert any(
            "unreadable" in record.message for record in caplog.records
        )

    def test_a_crash_mid_write_leaves_the_previous_checkpoint_intact(
        self, pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Written after every session — the likeliest file to be caught."""
        pipeline.checkpoint.write_text(json.dumps({
            "archived_ids": [SID_B], "failed_ids": {},
            "skipped_trivial_ids": [],
            "stats": {"total_archived": 1, "total_subagents": 0,
                      "total_compressed_bytes": 0},
        }), encoding="utf-8")
        before = pipeline.checkpoint.read_text(encoding="utf-8")

        real_replace = Path.replace

        def boom(self, target):
            raise OSError("interrupted")

        monkeypatch.setattr(Path, "replace", boom)
        with pytest.raises(OSError):
            bulk_archive._save_checkpoint(bulk_archive._empty_checkpoint())
        monkeypatch.setattr(Path, "replace", real_replace)

        assert pipeline.checkpoint.read_text(encoding="utf-8") == before, (
            "the progress file was truncated in place; the next run dies "
            "parsing it"
        )

    def test_the_staged_write_happens_beside_the_target(
        self, pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A temp file elsewhere would make the rename non-atomic."""
        staged: list[Path] = []
        real_replace = Path.replace

        def record(self, target):
            staged.append(Path(self))
            return real_replace(self, target)

        monkeypatch.setattr(Path, "replace", record)
        bulk_archive._save_checkpoint(bulk_archive._empty_checkpoint())

        assert staged, "no atomic rename was performed"
        assert staged[0].parent == pipeline.checkpoint.parent
        assert list(pipeline.checkpoint.parent.glob("*.tmp")) == []


# ---------------------------------------------------------------------------
# Round 4c-2 finding 4 — a check that always exits 0 is not a check
# ---------------------------------------------------------------------------


class TestVerifyExitStatus:
    """daily-sync and cron read the exit status, not the report.

    verify printed size mismatches and non-canonical entries and then
    reported success, so AR3's detection half and AR21 were invisible to
    every automated caller.
    """

    def test_a_clean_archive_exits_zero(self, pipeline: Pipeline) -> None:
        make_archive_entry(pipeline.archive_root, SID_A)

        assert pipeline.verify() == 0

    def test_a_size_mismatch_exits_non_zero(
        self, pipeline: Pipeline, capsys: pytest.CaptureFixture[str]
    ) -> None:
        entry = make_archive_entry(pipeline.archive_root, SID_A)
        with gzip.open(entry / "session.jsonl.gz", "wb") as handle:
            handle.write(b'{"type": "user"}\n')

        status = pipeline.verify()

        assert status == 1
        assert "Size mismatch" in capsys.readouterr().out

    def test_a_missing_transcript_exits_non_zero(
        self, pipeline: Pipeline
    ) -> None:
        make_archive_entry(pipeline.archive_root, SID_A, with_transcript=False)

        assert pipeline.verify() == 1

    def test_a_raw_only_entry_exits_non_zero(
        self, pipeline: Pipeline
    ) -> None:
        entry = make_archive_entry(
            pipeline.archive_root, SID_A, with_transcript=False
        )
        (entry / "session.jsonl").write_text("{}\n", encoding="utf-8")

        assert pipeline.verify() == 1

    def test_rebuilding_the_catalogue_is_a_repair_not_a_finding(
        self, pipeline: Pipeline
    ) -> None:
        """An out-of-date index is fixed by the run, so the run is clean."""
        make_archive_entry(pipeline.archive_root, SID_A)
        pipeline.catalogue.write_text(
            json.dumps({"sessions": []}), encoding="utf-8"
        )

        assert pipeline.verify(fix_catalogue=True) == 0

    def test_main_propagates_the_verify_status(
        self, pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The wiring, not just the return value: main() must hand it on."""
        make_archive_entry(pipeline.archive_root, SID_A, with_transcript=False)
        monkeypatch.setattr(sys, "argv", ["bulk-archive.py", "verify"])
        monkeypatch.setattr(bulk_archive, "setup_logging", lambda: LOGGER)

        assert bulk_archive.main() == 1

    def test_main_returns_zero_for_a_clean_verify(
        self, pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_archive_entry(pipeline.archive_root, SID_A)
        monkeypatch.setattr(sys, "argv", ["bulk-archive.py", "verify"])
        monkeypatch.setattr(bulk_archive, "setup_logging", lambda: LOGGER)

        assert bulk_archive.main() == 0


# ---------------------------------------------------------------------------
# Round 4c-2 finding 3 — the before/after comparison around the copy
# ---------------------------------------------------------------------------


class TestDuringCopyComparison:
    """The last guard: the source must not move while it is being read.

    The grace window catches a session that is obviously live; this catches
    the narrow case where a session resumes in the seconds the copy takes.
    It could be deleted with 63 tests green (round 4c-2, finding 3).
    """

    def _grow_during_copy(self, pipeline: Pipeline, monkeypatch, source: Path):
        """Make archive_session append to the source as it runs."""
        from cc_session_toolkit import archive as toolkit_archive
        real_archive = toolkit_archive.archive_session

        def growing(*, session_path, **kwargs):
            metadata = real_archive(session_path=session_path, **kwargs)
            with source.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"type": "user", "late": True}) + "\n")
            return metadata

        monkeypatch.setattr(toolkit_archive, "archive_session", growing)

    def test_a_source_that_changes_during_the_copy_is_not_counted_archived(
        self, pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = pipeline.add_session(SID_A)
        pipeline.discover()
        self._grow_during_copy(pipeline, monkeypatch, source)

        pipeline.archive()

        state = pipeline.checkpoint_state()
        assert state["archived_ids"] == [], (
            "a session whose transcript moved during the copy was recorded "
            "as archived; the entry may hold only a prefix"
        )
        assert SID_A in state["failed_ids"]
        assert "DURING the copy" in state["failed_ids"][SID_A]["reason"]

    def test_the_suspect_entry_is_named_so_verify_can_find_it(
        self, pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Left in place deliberately — but never silently."""
        source = pipeline.add_session(SID_A)
        pipeline.discover()
        self._grow_during_copy(pipeline, monkeypatch, source)

        with caplog.at_level(logging.ERROR, logger=LOGGER.name):
            pipeline.archive()

        assert any(
            "may be truncated" in record.message for record in caplog.records
        )

    def test_a_stable_source_is_counted_archived(
        self, pipeline: Pipeline
    ) -> None:
        """The positive control for the same comparison."""
        pipeline.add_session(SID_A)
        pipeline.discover()

        pipeline.archive()

        assert pipeline.checkpoint_state()["archived_ids"] == [SID_A]
        assert pipeline.checkpoint_state()["failed_ids"] == {}


# ---------------------------------------------------------------------------
# Round 4c-2 findings 5 and 6 — the catalogue's corruption report and its lock
# ---------------------------------------------------------------------------


class TestCatalogueCorruptionIsReported:
    """A corrupt index must be distinguishable from an empty one.

    The toolkit's get_archived_session_ids swallows JSONDecodeError and
    KeyError and returns an empty set, so delegating to it made the
    "unreadable" warning AR16 promised unreachable: an operator watching for
    it would never learn the index needed rebuilding.
    """

    @pytest.mark.parametrize("corruption,expected", [
        ('{"sessions": [', "corrupt"),
        ("not json at all", "corrupt"),
        ('{"sessions": "not-a-list"}', "no 'sessions' list"),
        ('[1, 2, 3]', "no 'sessions' list"),
    ])
    def test_a_corrupt_catalogue_is_named_in_the_log(
        self, pipeline: Pipeline, caplog: pytest.LogCaptureFixture,
        corruption: str, expected: str,
    ) -> None:
        pipeline.catalogue.write_text(corruption, encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger=LOGGER.name):
            ids = bulk_archive.read_catalogue_ids(pipeline.catalogue, LOGGER)

        assert ids == set()
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert expected in messages, messages
        assert "verify --fix-catalogue" in messages

    def test_entries_without_an_id_are_counted_and_reported(
        self, pipeline: Pipeline, caplog: pytest.LogCaptureFixture
    ) -> None:
        pipeline.catalogue.write_text(
            json.dumps({"sessions": [{"id": SID_A}, {"title": "no id"}, 7]}),
            encoding="utf-8",
        )

        with caplog.at_level(logging.WARNING, logger=LOGGER.name):
            ids = bulk_archive.read_catalogue_ids(pipeline.catalogue, LOGGER)

        assert ids == {SID_A}
        assert any(
            "no usable session id" in record.getMessage()
            for record in caplog.records
        )

    def test_a_good_catalogue_produces_no_warning(
        self, pipeline: Pipeline, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The positive control: a healthy index must be quiet."""
        pipeline.catalogue.write_text(
            json.dumps({"sessions": [{"id": SID_A}, {"id": SID_B}]}),
            encoding="utf-8",
        )

        with caplog.at_level(logging.WARNING, logger=LOGGER.name):
            ids = bulk_archive.read_catalogue_ids(pipeline.catalogue, LOGGER)

        assert ids == {SID_A, SID_B}
        assert caplog.records == []


class TestCatalogueLockIsHeld:
    """Two `verify --fix-catalogue` runs must not interleave.

    Temp-and-rename was pinned; the lock was not, so replacing the flock with
    `pass` left the suite green (round 4c-2, finding 6). The rename makes
    each write atomic, but without the lock two rebuilds race and the loser's
    scan silently wins.
    """

    def test_a_second_writer_waits_for_the_lock(
        self, pipeline: Pipeline
    ) -> None:
        """A held lock must block the write until it is released."""
        import fcntl as _fcntl
        import threading

        lock_path = pipeline.catalogue.with_name(
            pipeline.catalogue.name + ".lock"
        )
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        released = threading.Event()
        wrote = threading.Event()

        with open(lock_path, "w", encoding="utf-8") as holder:
            _fcntl.flock(holder.fileno(), _fcntl.LOCK_EX)

            def writer() -> None:
                bulk_archive.write_catalogue({"sessions": [{"id": SID_A}]}, LOGGER)
                wrote.set()

            thread = threading.Thread(target=writer, daemon=True)
            thread.start()
            # While the lock is held the writer must make no progress.
            assert not wrote.wait(timeout=0.5), (
                "the catalogue was written while another process held the "
                "lock; two rebuilds can interleave"
            )
            released.set()
            _fcntl.flock(holder.fileno(), _fcntl.LOCK_UN)

        thread.join(timeout=5)
        assert wrote.is_set(), "the writer never completed after release"
        assert released.is_set()
        catalogue = json.loads(pipeline.catalogue.read_text(encoding="utf-8"))
        assert [entry["id"] for entry in catalogue["sessions"]] == [SID_A]
