"""
Tests for ``scripts/normalise-archive-storage.py`` — the storage normaliser.

This script DELETES transcripts, and until 2026-09-08 it had no tests: the
sha256 round-trip verify could be removed, or an ``unlink`` added to the
DIVERGENT branch, and the full suite stayed green (lens B finding 4).

Pinned here: the round-trip verification before any raw file is removed; the
AR9 ordering (repoint the metadata, atomically, BEFORE unlinking, so an
interrupted run leaves the raw file in place rather than an unrecoverable
half-state); the self-heal of a stale meta left by an older interrupted run;
and that a DIVERGENT pair is touched by nothing at all.

Every archive entry here is invented.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _load():
    """Import the hyphenated script by path."""
    spec = importlib.util.spec_from_file_location(
        "normalise_archive_storage_under_test",
        str(SCRIPTS_DIR / "normalise-archive-storage.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


normalise = _load()

RAW_BODY = (
    '{"type": "user", "message": {"role": "user", "content": "First turn."}}\n'
    '{"type": "assistant", "message": {"role": "assistant", '
    '"content": "First reply."}}\n'
)
EXTRA_BODY = (
    '{"type": "user", "message": {"role": "user", "content": "Second turn."}}\n'
)



def _age(path: Path, *, seconds: float) -> None:
    """Backdate *path*'s mtime, so the staleness threshold can be tested."""
    when = time.time() - seconds
    os.utime(path, (when, when))


def _entry(
    root: Path,
    name: str = "2026-03-02_survey",
    *,
    raw: str | None = None,
    gz: str | None = None,
    jsonl_path: str = "session.jsonl",
) -> Path:
    """Build one synthetic archive entry in the requested storage state."""
    entry = root / "lantern-survey" / name
    entry.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        (entry / "session.jsonl").write_text(raw, encoding="utf-8")
    if gz is not None:
        with gzip.open(entry / "session.jsonl.gz", "wb") as handle:
            handle.write(gz.encode("utf-8"))
    (entry / "session.meta.json").write_text(
        json.dumps({
            "schema_version": "1.1",
            "session": {"id": "dddddddd-4444-4444-8444-dddddddddddd"},
            "project": {"name": "lantern-survey"},
            "archive": {"jsonl_path": jsonl_path, "jsonl_bytes": len(raw or "")},
        }, indent=2),
        encoding="utf-8",
    )
    return entry


def _meta(entry: Path) -> dict:
    return json.loads((entry / "session.meta.json").read_text(encoding="utf-8"))


class TestApplyOrdering:
    """AR9 — nothing is deleted before the record replacing it is on disk."""

    def test_raw_only_is_compressed_repointed_and_removed(
        self, tmp_path: Path
    ) -> None:
        """The ordinary case still completes."""
        entry = _entry(tmp_path, raw=RAW_BODY)

        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 0

        assert not (entry / "session.jsonl").exists()
        assert (entry / "session.jsonl.gz").exists()
        assert _meta(entry)["archive"]["jsonl_path"] == "session.jsonl.gz"
        with gzip.open(entry / "session.jsonl.gz", "rt") as handle:
            assert handle.read() == RAW_BODY

    def test_a_failed_repoint_leaves_the_raw_file_in_place(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure that used to destroy the only recoverable copy.

        With the old ordering the raw file was already gone by the time the
        repoint ran, so a failure here left gz written, raw deleted, and the
        metadata still naming session.jsonl — a state the next run reported
        as 'already canonical' and never repaired.
        """
        entry = _entry(tmp_path, raw=RAW_BODY)

        def boom(meta_path: Path, gz_path: Path) -> None:
            raise OSError("no space left on device")

        monkeypatch.setattr(normalise, "_repoint", boom)

        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 1

        assert (entry / "session.jsonl").exists(), (
            "the raw transcript was deleted before the metadata that "
            "replaces it was safely written"
        )
        assert (entry / "session.jsonl").read_text(encoding="utf-8") == RAW_BODY

    def test_the_repoint_is_atomic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A crash mid-write must not truncate the metadata.

        A session with an unparseable meta has no id, which drops it out of
        every archived-ids set and re-arms the drift gates on a session that
        is in fact archived.
        """
        entry = _entry(tmp_path, raw=RAW_BODY)
        before = (entry / "session.meta.json").read_text(encoding="utf-8")

        real_replace = Path.replace

        def boom(self, target):
            raise OSError("interrupted")

        monkeypatch.setattr(Path, "replace", boom)
        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 1
        monkeypatch.setattr(Path, "replace", real_replace)

        assert (entry / "session.meta.json").read_text(encoding="utf-8") == before
        assert (entry / "session.jsonl").exists()

    def test_a_stale_meta_self_heals_on_a_re_run(self, tmp_path: Path) -> None:
        """gz present, raw absent, meta stale: the interrupted-run residue."""
        entry = _entry(tmp_path, gz=RAW_BODY, jsonl_path="session.jsonl")

        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 0

        archive = _meta(entry)["archive"]
        assert archive["jsonl_path"] == "session.jsonl.gz"
        assert archive["jsonl_bytes_uncompressed"] == len(RAW_BODY)

    def test_an_already_canonical_entry_is_left_alone(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The self-heal must not rewrite entries that are already correct."""
        entry = _entry(tmp_path, gz=RAW_BODY, jsonl_path="session.jsonl.gz")
        before = (entry / "session.meta.json").read_text(encoding="utf-8")

        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 0

        assert (entry / "session.meta.json").read_text(encoding="utf-8") == before
        assert "already-canonical=1" in capsys.readouterr().out


class TestDivergentIsUntouched:
    """Two different transcripts under one entry is a human's problem.

    Both prefix branches are guarded by an ``is_prefix`` call as well as a
    length comparison, and the two guards do different work. Until round
    4c-2 only the gz-longer case had a fixture, so dropping the raw-longer
    branch's ``is_prefix(...)`` left the suite green — and unguarded, a
    DIVERGENT pair whose raw half is merely LONGER is recompressed over the
    gz and the raw then unlinked. That is permanent loss of the gz content,
    in the one branch of this script that both writes and deletes.
    """

    def test_a_longer_but_divergent_raw_is_not_recompressed_over_the_gz(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """raw is longer than gz, and is NOT a superset of it."""
        divergent_raw = (
            '{"type": "user", "message": {"role": "user", '
            '"content": "A wholly different first turn."}}\n'
        ) * 4
        entry = _entry(tmp_path, raw=divergent_raw, gz=RAW_BODY)
        assert len(divergent_raw) > len(RAW_BODY), (
            "the fixture must exercise the raw-longer half"
        )
        raw_before = (entry / "session.jsonl").read_bytes()
        gz_before = (entry / "session.jsonl.gz").read_bytes()
        meta_before = (entry / "session.meta.json").read_text(encoding="utf-8")

        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 1

        assert (entry / "session.jsonl").read_bytes() == raw_before, (
            "a divergent raw transcript was deleted"
        )
        assert (entry / "session.jsonl.gz").read_bytes() == gz_before, (
            "a divergent raw transcript was recompressed over the gz; the "
            "gz content is gone and unrecoverable"
        )
        assert (entry / "session.meta.json").read_text(
            encoding="utf-8"
        ) == meta_before
        assert "DIVERGENT" in capsys.readouterr().out

    def test_a_genuine_raw_longer_prefix_is_still_converged(
        self, tmp_path: Path
    ) -> None:
        """The positive control for the branch the guard protects."""
        longer_raw = RAW_BODY + EXTRA_BODY
        entry = _entry(tmp_path, raw=longer_raw, gz=RAW_BODY)

        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 0

        assert not (entry / "session.jsonl").exists()
        with gzip.open(entry / "session.jsonl.gz", "rt") as handle:
            assert handle.read() == longer_raw
        assert _meta(entry)["archive"]["jsonl_path"] == "session.jsonl.gz"

    def test_nothing_is_deleted_or_rewritten(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        entry = _entry(
            tmp_path, raw=RAW_BODY, gz=EXTRA_BODY + "x" * len(RAW_BODY)
        )
        raw_before = (entry / "session.jsonl").read_bytes()
        gz_before = (entry / "session.jsonl.gz").read_bytes()
        meta_before = (entry / "session.meta.json").read_text(encoding="utf-8")

        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 1

        assert (entry / "session.jsonl").read_bytes() == raw_before
        assert (entry / "session.jsonl.gz").read_bytes() == gz_before
        assert (entry / "session.meta.json").read_text(
            encoding="utf-8"
        ) == meta_before
        assert "DIVERGENT" in capsys.readouterr().out


class TestRoundTripVerification:
    """No raw file is removed on the strength of an unverified copy."""

    def test_a_failed_round_trip_raises_and_keeps_the_raw(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _entry(tmp_path, raw=RAW_BODY)

        # A compressor that quietly drops the tail: exactly the corruption
        # the verify exists to catch.
        real_sha = normalise.sha256_file

        def wrong_sha(path: Path, *, decompress: bool = False):
            if decompress:
                return "0" * 64, 0
            return real_sha(path, decompress=decompress)

        monkeypatch.setattr(normalise, "sha256_file", wrong_sha)

        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 1

        assert (entry / "session.jsonl").exists()
        assert not (entry / "session.jsonl.gz").exists(), (
            "an unverified gz was left behind for a later run to trust"
        )

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        entry = _entry(tmp_path, raw=RAW_BODY)
        before = sorted(p.name for p in entry.iterdir())

        assert normalise.main(["--root", str(tmp_path)]) == 0

        assert sorted(p.name for p in entry.iterdir()) == before
        assert _meta(entry)["archive"]["jsonl_path"] == "session.jsonl"


class TestRawOnlyCompressionIsStaged:
    """A kill mid-compression must leave a state the next run can finish.

    The raw-only branch wrote straight to session.jsonl.gz. A kill mid-write
    left a partial .gz beside the raw, and every later run then read the
    entry as dual-form, found the truncated gz neither identical to the raw
    nor in a prefix relationship with it, called it DIVERGENT, and exited 1
    forever without converging (round 4c-2, finding 9).
    """

    def test_a_crash_mid_compression_leaves_no_partial_gz(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _entry(tmp_path, raw=RAW_BODY)

        real_replace = Path.replace

        def boom(self, target):
            raise OSError("killed mid-write")

        monkeypatch.setattr(Path, "replace", boom)
        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 1
        monkeypatch.setattr(Path, "replace", real_replace)

        assert not (entry / "session.jsonl.gz").exists(), (
            "a partial .gz was left where a complete one belongs; the entry "
            "now reads as DIVERGENT on every future run"
        )
        assert (entry / "session.jsonl").read_text(encoding="utf-8") == RAW_BODY

    def test_the_re_run_converges_after_an_interrupted_compression(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point of staging: the next run finishes the job."""
        entry = _entry(tmp_path, raw=RAW_BODY)

        real_replace = Path.replace
        monkeypatch.setattr(
            Path, "replace",
            lambda self, target: (_ for _ in ()).throw(OSError("killed")),
        )
        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 1
        monkeypatch.setattr(Path, "replace", real_replace)

        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 0

        assert not (entry / "session.jsonl").exists()
        with gzip.open(entry / "session.jsonl.gz", "rt") as handle:
            assert handle.read() == RAW_BODY
        assert _meta(entry)["archive"]["jsonl_path"] == "session.jsonl.gz"

    def test_no_temporary_file_survives_a_successful_run(
        self, tmp_path: Path
    ) -> None:
        entry = _entry(tmp_path, raw=RAW_BODY)

        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 0

        assert list(entry.glob("*.tmp")) == []


class TestStaleTemporariesAreSwept:
    """Round 4c-3 finding L-10 — an abandoned .tmp is not inert.

    The staged writes across this pipeline leave `<name>.tmp` behind when a
    process is killed between the write and the rename, and nothing cleaned
    them up. push-archives-to-r2.sh mirrors the archive root wholesale, so a
    partial temporary became a PERMANENT object in R2 -- permanent because
    that push is --immutable and never deletes, so the half-written file
    could not afterwards be replaced or removed.
    """

    def test_an_abandoned_temporary_is_removed(self, tmp_path: Path) -> None:
        entry = _entry(tmp_path, gz=RAW_BODY, jsonl_path="session.jsonl.gz")
        stale = entry / "session.jsonl.gz.tmp"
        stale.write_bytes(b"\x1f\x8b partial")
        _age(stale, seconds=2 * normalise.STALE_TEMP_MIN_AGE_SECONDS)

        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 0

        assert not stale.exists(), (
            "an abandoned temporary was left for the R2 push to upload as a "
            "permanent immutable object"
        )

    def test_dry_run_reports_but_does_not_remove(self, tmp_path: Path) -> None:
        entry = _entry(tmp_path, gz=RAW_BODY, jsonl_path="session.jsonl.gz")
        stale = entry / "session.jsonl.gz.tmp"
        stale.write_bytes(b"partial")
        _age(stale, seconds=2 * normalise.STALE_TEMP_MIN_AGE_SECONDS)

        result = normalise.main(["--root", str(tmp_path)])

        assert result == 0
        assert stale.exists()

    def test_a_recent_temporary_is_left_alone(
        self, tmp_path: Path
    ) -> None:
        """A concurrent normalise pass must not have its staging deleted.

        An age threshold rather than a comparison against this run's start
        time: a concurrent pass that began a second earlier would fail the
        start-time test and have its in-flight file swept.
        """
        entry = _entry(tmp_path, gz=RAW_BODY, jsonl_path="session.jsonl.gz")
        fresh = entry / "session.jsonl.gz.tmp"
        fresh.write_bytes(b"another run is mid-write")

        assert normalise.main(["--root", str(tmp_path), "--apply"]) == 0

        assert fresh.exists(), (
            "a temporary belonging to a concurrent run was swept"
        )

    def test_the_sweep_is_counted_in_the_summary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        entry = _entry(tmp_path, gz=RAW_BODY, jsonl_path="session.jsonl.gz")
        stale = entry / "session.jsonl.gz.tmp"
        stale.write_bytes(b"partial")
        _age(stale, seconds=2 * normalise.STALE_TEMP_MIN_AGE_SECONDS)

        normalise.main(["--root", str(tmp_path), "--apply"])

        assert "stale-temp=1" in capsys.readouterr().out
