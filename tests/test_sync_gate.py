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

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
TRIGGER = SCRIPTS_DIR / "daily-sync-trigger.sh"
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

    def test_every_gate_is_relayed_by_the_trigger(self) -> None:
        """
        The trigger names the gates it prints. A gate written but not
        named there is written into silence — the precise failure C2 is
        about, and the reason C1 asks for *every* postgres gate to be
        relayed. The mutation this kills: adding a gate file without
        adding it to the trigger's list.
        """
        trigger = TRIGGER.read_text(encoding="utf-8")
        for gate in _sync_gate.ALL_GATES:
            assert gate.name in trigger, f"{gate.name} is never relayed"
            assert gate.parent == Path.home() / ".cache"

    def test_the_gates_are_distinct_files(self) -> None:
        """
        One file per script (finding C1). Sharing one meant a clean run of
        either sync erased the other's alarm within a cron tick.
        """
        assert len(set(_sync_gate.ALL_GATES)) == len(_sync_gate.ALL_GATES)
        assert _sync_gate.MEMORIES_GATE != _sync_gate.SESSIONS_GATE

    def test_the_trigger_prints_a_gate_whose_count_is_one(
        self, tmp_path: Path,
    ) -> None:
        """
        The threshold is ``-gt 0``, not ``-gt 1``: a single problem is the
        commonest case and must print. Executed against a copy of the
        trigger's gate block with HOME pinned to tmp — never the real
        script, which runs the daily sync.
        """
        source = TRIGGER.read_text(encoding="utf-8")
        start = source.index("for _pg_gate_name in")
        end = source.index("unset _pg_gate_name", start)
        block = source[start:end]

        cache = tmp_path / ".cache"
        cache.mkdir()
        (cache / "postgres-sync-sessions-gate").write_text(
            "1\nexactly one problem\n", encoding="utf-8",
        )
        (cache / "postgres-sync-memories-gate").write_text(
            "0\n", encoding="utf-8",
        )

        script = tmp_path / "gate-block.sh"
        script.write_text(
            "GATE_LINES=()\n" + block
            + '\nprintf "%s\\n" "${GATE_LINES[@]}"\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True, text=True,
            env={"HOME": str(tmp_path), "PATH": os.environ["PATH"]},
        )

        assert result.returncode == 0, result.stderr
        assert "exactly one problem" in result.stdout
        # The count-0 gate must stay silent.
        assert "postgres-sync-memories" not in result.stdout


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
    # Every gate call goes through the module's pinnable constant, so a
    # test can never write the operator's real gate.
    assert "gate_path=_DEFAULT_GATE_FILE" not in source
    exit_four = source.index("sys.exit(4)")
    exit_six = source.index("sys.exit(6)")
    assert "write_gate(" in source[exit_four - 900:exit_four]
    assert "write_gate(" in source[exit_six - 900:exit_six]
    # And the clear is reached only through the outcome policy, never
    # unconditionally at the end of main (finding C1).
    assert source.count("clear_gate(") == 1
    assert "_apply_gate_policy(" in source


class TestOnlyACompletedCycleClears:
    """
    Finding C1's invariant, at the level of the policy both syncs share:
    a gate is cleared only by a cycle of *that* script that completed.
    """

    def _load_sync(self):
        """Import the memories sync (its policy is the shared one)."""
        import importlib.util
        path = SCRIPTS_DIR / "sync-to-postgres.py"
        spec = importlib.util.spec_from_file_location("sync_gate_probe", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @pytest.fixture
    def raised(self, tmp_path: Path) -> Path:
        """A gate already standing, as a previous exit-4 run left it."""
        gate = tmp_path / "postgres-sync-memories-gate"
        _sync_gate.write_gate("a previous run exited 4", gate_path=gate)
        return gate

    def test_a_contended_run_leaves_the_gate(self, raised, tmp_path) -> None:
        """
        A run that deferred to another instance learnt nothing about the
        fault. The mutation this kills: clearing on any outcome.
        """
        sync_mod = self._load_sync()
        sync_mod._apply_gate_policy(
            _sync_gate.CYCLE_CONTENDED, 0, "sync-to-postgres.py",
            tmp_path / "quarantine.jsonl", raised,
            logging.getLogger("test-gate-policy"),
        )
        assert raised.read_text(encoding="utf-8").startswith("1")

    def test_an_outage_run_leaves_the_gate(self, raised, tmp_path) -> None:
        """A run that never reached the database learnt nothing either."""
        sync_mod = self._load_sync()
        sync_mod._apply_gate_policy(
            _sync_gate.CYCLE_DEGRADED, 0, "sync-to-postgres.py",
            tmp_path / "quarantine.jsonl", raised,
            logging.getLogger("test-gate-policy"),
        )
        assert raised.read_text(encoding="utf-8").startswith("1")

    def test_a_completed_clean_run_clears_the_gate(
        self, raised, tmp_path,
    ) -> None:
        """The one case that may clear it."""
        sync_mod = self._load_sync()
        sync_mod._apply_gate_policy(
            _sync_gate.CYCLE_COMPLETED, 0, "sync-to-postgres.py",
            tmp_path / "quarantine.jsonl", raised,
            logging.getLogger("test-gate-policy"),
        )
        assert raised.read_text(encoding="utf-8").strip() == "0"

    def test_a_completed_run_that_quarantined_raises_a_warning(
        self, tmp_path,
    ) -> None:
        """
        Finding C3's first invariant: quarantining is data leaving the
        pipeline, and it happened silently at exit 0 with no gate at all.
        """
        gate = tmp_path / "postgres-sync-memories-gate"
        sync_mod = self._load_sync()
        sync_mod._apply_gate_policy(
            _sync_gate.CYCLE_COMPLETED, 7, "sync-to-postgres.py",
            tmp_path / "quarantine.jsonl", gate,
            logging.getLogger("test-gate-policy"),
        )
        lines = gate.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "7"
        assert "REFUSED" in lines[1]
        assert "quarantine.jsonl" in lines[1]

    def test_neither_sync_can_clear_the_other(self) -> None:
        """
        Structural guarantee rather than a race: the two scripts name
        different constants, so there is no interleaving in which one
        clears the other's alarm.
        """
        memories = self._load_sync()
        import importlib.util
        path = SCRIPTS_DIR / "sync-sessions-to-postgres.py"
        spec = importlib.util.spec_from_file_location("sessions_probe", path)
        sessions = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sessions)

        assert memories.GATE_FILE == _sync_gate.MEMORIES_GATE
        assert sessions.GATE_FILE == _sync_gate.SESSIONS_GATE
        assert memories.GATE_FILE != sessions.GATE_FILE


def test_no_script_writes_a_gate_outside_a_pinned_path():
    """
    Every gate call site must use its module's own ``GATE_FILE``
    constant, never the helper's default and never the shared import
    alias. Three separate occasions during this audit a test wrote the
    operator's real gate and put a fabricated infrastructure problem in
    front of him at session start; this is the structural check that
    makes the next one a test failure instead.
    """
    for script_name in (
        "sync-to-postgres.py",
        "sync-sessions-to-postgres.py",
        "index-session-content.py",
    ):
        source = (SCRIPTS_DIR / script_name).read_text(encoding="utf-8")
        assert "gate_path=_DEFAULT_GATE_FILE" not in source, script_name
        assert "GATE_FILE = _DEFAULT_GATE_FILE" in source, script_name
        for call in ("write_gate(", "clear_gate("):
            position = 0
            while True:
                position = source.find(call, position)
                if position == -1:
                    break
                window = source[position:position + 900]
                # Either the module constant directly, or a gate_path
                # parameter the caller filled from it — never the
                # helper's own default, which has none by design.
                assert (
                    "gate_path=GATE_FILE" in window
                    or "gate_path=gate_path" in window
                ), f"{script_name}: a {call} call does not pin gate_path"
                position += 1
        # And where a helper takes the path as a parameter, main passes
        # the module constant.
        if "_apply_gate_policy(" in source:
            assert "QUARANTINE_FILE, GATE_FILE, logger," in source
