"""
Tests for ``scripts/_batch_state.py`` — one state file per Batch API job.

The Anthropic Batch API takes up to 24 hours. Both ``bulk-archive.py`` and
``reprocess-sessions.py`` kept the map from ``custom_id`` to target in a
single file, so a second submit before the first was applied destroyed the
first's map — and that map is the only record of which archive entry, or
which session, each reply belongs to (audit 2026-09-08, finding AR18).

Nothing here contacts a provider; the module is pure filesystem logic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from _batch_state import (  # noqa: E402
    UnsafeBatchId,
    load_state,
    save_state,
    state_path,
)


def _state(batch_id: str, marker: str) -> dict:
    """A minimal batch state carrying something identifiable."""
    return {"batch_id": batch_id, "n_requests": 1, "marker": marker}


class TestPerBatchState:
    """A second submit must not destroy the first submit's map."""

    def test_two_batches_keep_their_own_state(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        legacy = tmp_path / "legacy.json"

        save_state(_state("msgbatch_first", "first"), state_dir, legacy)
        save_state(_state("msgbatch_second", "second"), state_dir, legacy)

        first = load_state("msgbatch_first", state_dir, legacy)
        second = load_state("msgbatch_second", state_dir, legacy)
        assert first is not None and first["marker"] == "first", (
            "the second submit overwrote the first batch's map"
        )
        assert second is not None and second["marker"] == "second"

    def test_the_legacy_slot_still_names_the_latest_batch(
        self, tmp_path: Path
    ) -> None:
        """Operators and older tooling read the single slot; keep it correct."""
        state_dir = tmp_path / "state"
        legacy = tmp_path / "legacy.json"

        save_state(_state("msgbatch_first", "first"), state_dir, legacy)
        save_state(_state("msgbatch_second", "second"), state_dir, legacy)

        assert json.loads(legacy.read_text(encoding="utf-8"))["batch_id"] == (
            "msgbatch_second"
        )

    def test_the_legacy_slot_is_a_fallback_only_for_its_own_batch(
        self, tmp_path: Path
    ) -> None:
        """A slot describing another batch is the defect, not a fallback."""
        state_dir = tmp_path / "state"
        legacy = tmp_path / "legacy.json"
        legacy.write_text(json.dumps(_state("msgbatch_old", "old")), "utf-8")

        assert load_state("msgbatch_old", state_dir, legacy) is not None
        assert load_state("msgbatch_new", state_dir, legacy) is None

    def test_an_unknown_batch_returns_none(self, tmp_path: Path) -> None:
        assert load_state(
            "msgbatch_absent", tmp_path / "state", tmp_path / "legacy.json"
        ) is None

    def test_a_corrupt_state_file_is_not_a_crash(self, tmp_path: Path) -> None:
        """A half-written state must not take the apply command down."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "msgbatch_torn.json").write_text('{"batch_id": ', "utf-8")

        assert load_state(
            "msgbatch_torn", state_dir, tmp_path / "legacy.json"
        ) is None

    def test_the_write_is_atomic(self, tmp_path: Path) -> None:
        """No temporary files survive a successful save."""
        state_dir = tmp_path / "state"
        legacy = tmp_path / "legacy.json"
        save_state(_state("msgbatch_first", "first"), state_dir, legacy)

        leftovers = [p.name for p in state_dir.iterdir() if ".tmp" in p.name]
        assert leftovers == []


class TestBatchIdSafety:
    """A batch id arrives on the command line; it is not a path."""

    @pytest.mark.parametrize("batch_id", [
        "../escape", "sub/dir", "", ".hidden", "with space",
    ])
    def test_unsafe_ids_are_refused(
        self, tmp_path: Path, batch_id: str
    ) -> None:
        with pytest.raises(UnsafeBatchId):
            state_path(tmp_path, batch_id)

    def test_a_normal_provider_id_is_accepted(self, tmp_path: Path) -> None:
        assert state_path(tmp_path, "msgbatch_01AbC-9.x").name == (
            "msgbatch_01AbC-9.x.json"
        )
