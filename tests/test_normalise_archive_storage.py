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
import sys
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
    """Two different transcripts under one entry is a human's problem."""

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
