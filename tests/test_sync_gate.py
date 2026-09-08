"""
Tests for ``scripts/_sync_gate.py`` — the session-start gate the Postgres
syncs raise on exit 4 and exit 6.

Audit round two, finding C2: fixing the diagnosis was only half of the
September 2026 incident. The other half is that an exit code reaching
nothing but a log file is a signal emitted and not surfaced, which this
repository has learned three times is indistinguishable from no signal.

Everything here writes inside ``tmp_path``. A test that wrote the real
``~/.cache/postgres-sync-gate`` would put a fabricated infrastructure
problem in front of Shawn at his next session start.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import _sync_gate  # noqa: E402


class TestGateFormat:
    """The shape every other gate in ``~/.cache`` uses."""

    def test_raising_writes_count_then_detail(self, tmp_path: Path) -> None:
        """Line 1 is the problem count; the rest is what gets printed."""
        gate = tmp_path / "postgres-sync-gate"
        assert _sync_gate.write_gate("something broke", gate_path=gate) is True

        lines = gate.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "1"
        assert lines[1] == "something broke"

    def test_detail_is_collapsed_to_one_line(self, tmp_path: Path) -> None:
        """
        A multi-line diagnosis would break the count-then-details contract
        the trigger script parses with ``head -1`` / ``tail -n +2``.
        """
        gate = tmp_path / "postgres-sync-gate"
        _sync_gate.write_gate(
            "first line\nsecond line\n\tthird", gate_path=gate,
        )
        lines = [
            line for line in gate.read_text(encoding="utf-8").splitlines()
            if line
        ]
        assert len(lines) == 2
        assert lines[1] == "first line second line third"

    def test_clearing_writes_zero(self, tmp_path: Path) -> None:
        """
        A clean run lowers the gate, so a fault that has been fixed stops
        being reported without anyone deleting a file.
        """
        gate = tmp_path / "postgres-sync-gate"
        _sync_gate.write_gate("broken", gate_path=gate)
        assert _sync_gate.clear_gate(gate_path=gate) is True
        assert gate.read_text(encoding="utf-8").strip() == "0"

    def test_parent_directory_is_created(self, tmp_path: Path) -> None:
        """A machine with no ``~/.cache`` yet must not crash the sync."""
        gate = tmp_path / "nested" / "cache" / "postgres-sync-gate"
        assert _sync_gate.write_gate("broken", gate_path=gate) is True
        assert gate.exists()

    def test_io_failure_is_reported_not_raised(self, tmp_path: Path) -> None:
        """
        A gate we cannot write must never take down a sync that has
        otherwise done its job.
        """
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        gate = blocker / "postgres-sync-gate"
        assert _sync_gate.write_gate("broken", gate_path=gate) is False
        assert _sync_gate.clear_gate(gate_path=gate) is False

    def test_default_path_matches_the_trigger_script(self) -> None:
        """
        ``daily-sync-trigger.sh`` reads a hard-coded path. If this constant
        and that path ever diverge the gate is written into silence — the
        precise failure C2 is about.
        """
        trigger = (
            Path(__file__).resolve().parent.parent
            / "scripts" / "daily-sync-trigger.sh"
        ).read_text(encoding="utf-8")
        assert _sync_gate.GATE_FILE.name in trigger
        assert '${HOME}/.cache/postgres-sync-gate' in trigger
        assert _sync_gate.GATE_FILE == Path.home() / ".cache" / "postgres-sync-gate"


@pytest.mark.parametrize("script_name", [
    "sync-to-postgres.py",
    "sync-sessions-to-postgres.py",
])
def test_both_syncs_raise_and_clear_the_gate(script_name: str) -> None:
    """
    Source-level wiring check: each sync must raise the gate on both
    human-action exits and lower it on a clean run. A gate written by only
    one of the two, or never cleared, is worse than none — it either
    misses half the faults or nags for ever.
    """
    source = (SCRIPTS_DIR / script_name).read_text(encoding="utf-8")
    assert "write_gate(" in source
    assert "clear_gate(" in source
    # Both raise sites, and the clear, use the module's pinnable constant.
    assert source.count("gate_path=GATE_FILE") == 3
    exit_four = source.index("sys.exit(4)")
    exit_six = source.index("sys.exit(6)")
    assert "write_gate(" in source[exit_four - 700:exit_four]
    assert "write_gate(" in source[exit_six - 700:exit_six]
