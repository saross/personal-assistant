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

import ast
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


GATE_CALLS = ("write_gate", "clear_gate", "raise_fault_gate")
GATED_SCRIPTS = (
    "sync-to-postgres.py",
    "sync-sessions-to-postgres.py",
    "index-session-content.py",
)


def _gate_call_nodes(source: str):
    """Yield every AST call node that raises or lowers a gate."""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(
            func, "attr", None,
        )
        if name in GATE_CALLS:
            yield name, node


@pytest.mark.parametrize("script_name", GATED_SCRIPTS)
def test_every_gate_call_pins_the_path_to_the_module_constant(script_name):
    """
    Parsed, not grepped (fourth re-audit, finding M6).

    The substring version of this test was defeated by anything that
    merely *contained* the right text — ``gate_path=GATE_FILE if False
    else Path.home() / ".cache" / "x"`` passed it while writing the
    operator's real gate. Three times during this audit a test wrote a
    real gate file and would have put a fabricated infrastructure
    problem in front of Shawn at session start; this is the check that
    makes the next one a test failure.

    Every gate call must pass ``gate_path`` as a bare Name, and that name
    must be the script's own ``GATE_FILE`` (or a parameter of a helper
    that main fills from it) — never an expression, never the shared
    default, never a literal path.
    """
    source = (SCRIPTS_DIR / script_name).read_text(encoding="utf-8")
    calls = list(_gate_call_nodes(source))
    assert calls, f"{script_name} raises no gate at all"

    for name, node in calls:
        keywords = {kw.arg: kw.value for kw in node.keywords}
        assert "gate_path" in keywords, (
            f"{script_name}:{node.lineno}: {name} does not pass gate_path"
        )
        value = keywords["gate_path"]
        assert isinstance(value, ast.Name), (
            f"{script_name}:{node.lineno}: gate_path is a "
            f"{type(value).__name__}, not a plain name — an expression "
            f"here can evaluate to any path at all"
        )
        assert value.id in ("GATE_FILE", "gate_path"), (
            f"{script_name}:{node.lineno}: gate_path is bound to "
            f"{value.id!r}, not the module's GATE_FILE"
        )


@pytest.mark.parametrize("script_name", GATED_SCRIPTS)
def test_each_script_defines_its_own_gate_constant(script_name):
    """
    ``GATE_FILE`` must be assigned from the shared module's per-script
    constant, so tests can pin it and the three scripts cannot collide.
    """
    source = (SCRIPTS_DIR / script_name).read_text(encoding="utf-8")
    assignments = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "GATE_FILE"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1, f"{script_name}: GATE_FILE is not assigned once"
    value = assignments[0].value
    assert isinstance(value, ast.Name) and value.id == "_DEFAULT_GATE_FILE", (
        f"{script_name}: GATE_FILE is not the shared per-script constant"
    )


@pytest.mark.parametrize("script_name", (
    "sync-to-postgres.py", "sync-sessions-to-postgres.py",
))
def test_the_syncs_route_clearing_through_the_shared_policy(script_name):
    """
    Neither sync may clear its gate directly: the decision belongs to
    ``apply_sync_gate``, which is where the evidence rule lives.
    """
    source = (SCRIPTS_DIR / script_name).read_text(encoding="utf-8")
    names = [name for name, _ in _gate_call_nodes(source)]
    assert "clear_gate" not in names, (
        f"{script_name} clears its gate outside the shared policy"
    )
    assert "apply_sync_gate(" in source


class TestEvidenceLowersAGate:
    """
    The fourth re-audit's governing invariant: a gate is lowered only by
    evidence that the fault it records is gone. Absence of work is not
    evidence.
    """

    @pytest.fixture
    def gate(self, tmp_path: Path) -> Path:
        """A gate already standing, as a previous exit-4 run left it."""
        path = tmp_path / "postgres-sync-memories-gate"
        _sync_gate.raise_fault_gate(
            "a previous run exited 4", gate_path=path,
            logger=logging.getLogger("test-gate"),
        )
        return path

    def _apply(self, gate, result):
        """Run the shared policy against a standing gate."""
        _sync_gate.apply_sync_gate(
            result,
            script="sync-to-postgres.py",
            gate_path=gate,
            quarantine_file=gate.parent / "quarantine.jsonl",
            logger=logging.getLogger("test-gate"),
        )

    def _standing(self, gate) -> bool:
        """Is the gate still raised?"""
        return gate.read_text(encoding="utf-8").splitlines()[0] != "0"

    @pytest.mark.parametrize("result", [
        # Nothing to do: the case that cleared a standing alarm every
        # five minutes before this fix.
        _sync_gate.CycleResult(_sync_gate.CYCLE_IDLE),
        # Deferred to another instance.
        _sync_gate.CycleResult(_sync_gate.CYCLE_CONTENDED, connected=True),
        # Could not reach the database.
        _sync_gate.CycleResult(_sync_gate.CYCLE_OUTAGE, connected=False),
        # Reached it, but could not finish safely.
        _sync_gate.CycleResult(_sync_gate.CYCLE_DEGRADED, connected=True),
        # Completed, but processed nothing — no evidence either.
        _sync_gate.CycleResult(
            _sync_gate.CYCLE_COMPLETED, processed=0, connected=True,
        ),
    ])
    def test_a_run_that_learnt_nothing_leaves_the_gate(self, gate, result):
        """
        The mutation this kills: lowering the gate on any outcome, or on
        a completed cycle that processed no rows.
        """
        self._apply(gate, result)
        assert self._standing(gate), f"{result.outcome} lowered the gate"

    def test_processing_a_row_cleanly_lowers_the_gate(self, gate) -> None:
        """The one case that is evidence: work was done and none refused."""
        self._apply(gate, _sync_gate.CycleResult(
            _sync_gate.CYCLE_COMPLETED, processed=3, connected=True,
        ))
        assert not self._standing(gate)

    def test_quarantining_raises_the_warning_gate(self, tmp_path) -> None:
        """Data leaving the pipeline is worth a gate at any outcome."""
        gate = tmp_path / "postgres-sync-memories-gate"
        self._apply(gate, _sync_gate.CycleResult(
            _sync_gate.CYCLE_COMPLETED, quarantined=7, processed=7,
            connected=True,
        ))
        lines = gate.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "7"
        assert "REFUSED" in lines[1]

    def test_a_degraded_run_that_quarantined_still_gates(self, tmp_path):
        """
        Finding M3: a degraded run discarded its quarantine count, so rows
        that had left the pipeline went unreported. The mutation this
        kills: testing the outcome before the count.
        """
        gate = tmp_path / "postgres-sync-memories-gate"
        self._apply(gate, _sync_gate.CycleResult(
            _sync_gate.CYCLE_DEGRADED, quarantined=2, connected=True,
        ))
        assert gate.read_text(encoding="utf-8").splitlines()[0] == "2"


class TestOutageStreak:
    """
    Finding M4 — the syncs exit 0 on an outage by design, so a persistent
    outage produced no session-start signal at all.
    """

    def _apply(self, gate, result):
        """Run the shared policy."""
        _sync_gate.apply_sync_gate(
            result,
            script="sync-to-postgres.py",
            gate_path=gate,
            quarantine_file=gate.parent / "quarantine.jsonl",
            logger=logging.getLogger("test-gate"),
        )

    def _count(self, gate) -> str:
        """The gate's problem count, or "0" when no gate exists."""
        if not gate.exists():
            return "0"
        return gate.read_text(encoding="utf-8").splitlines()[0]

    def test_three_consecutive_outages_raise_a_gate(self, tmp_path) -> None:
        """
        Two is a restart; three is a problem. The mutation this kills:
        never incrementing the streak.
        """
        gate = tmp_path / "postgres-sync-memories-gate"
        outage = _sync_gate.CycleResult(
            _sync_gate.CYCLE_OUTAGE, connected=False,
        )

        self._apply(gate, outage)
        assert self._count(gate) == "0"
        self._apply(gate, outage)
        assert self._count(gate) == "0"

        self._apply(gate, outage)
        lines = gate.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "3"
        assert "unreachable for 3 consecutive runs" in lines[1]

    def test_connecting_again_lowers_the_outage_gate(self, tmp_path) -> None:
        """
        Connecting IS the evidence that "unreachable" is over, even on an
        otherwise idle run. The mutation this kills: requiring a completed
        cycle to clear an outage gate.
        """
        gate = tmp_path / "postgres-sync-memories-gate"
        outage = _sync_gate.CycleResult(
            _sync_gate.CYCLE_OUTAGE, connected=False,
        )
        for _ in range(3):
            self._apply(gate, outage)
        assert self._count(gate) == "3"

        self._apply(gate, _sync_gate.CycleResult(
            _sync_gate.CYCLE_IDLE, connected=True,
        ))
        assert gate.read_text(encoding="utf-8").strip() == "0"

    def test_an_idle_run_that_never_connected_does_not_count(self, tmp_path):
        """
        ``connected=None`` means we never tried: it must move the counter
        in neither direction, or a quiet week would look like an outage.
        """
        gate = tmp_path / "postgres-sync-memories-gate"
        for _ in range(10):
            self._apply(gate, _sync_gate.CycleResult(_sync_gate.CYCLE_IDLE))
        assert self._count(gate) == "0"

    def test_the_streak_resets_on_a_successful_run(self, tmp_path) -> None:
        """An outage that recovers must not accumulate towards the next."""
        gate = tmp_path / "postgres-sync-memories-gate"
        outage = _sync_gate.CycleResult(
            _sync_gate.CYCLE_OUTAGE, connected=False,
        )
        self._apply(gate, outage)
        self._apply(gate, outage)
        self._apply(gate, _sync_gate.CycleResult(
            _sync_gate.CYCLE_COMPLETED, processed=1, connected=True,
        ))
        assert _sync_gate.read_state(gate).outage_streak == 0

        self._apply(gate, outage)
        assert self._count(gate) == "0"


def test_the_gate_files_are_distinct():
    """One gate file per script — the third re-audit's finding C1."""
    assert len(set(_sync_gate.ALL_GATES)) == len(_sync_gate.ALL_GATES)


def test_this_module_did_not_lose_tests_to_an_edit():
    """
    A guard against the mistake that produced this line: a scripted
    rewrite of this file truncated fourteen tests off the end, and the
    suite went green because the tests were simply gone. Collection count
    is the cheapest possible tripwire for that.
    """
    import ast as _ast

    tree = _ast.parse(Path(__file__).read_text(encoding="utf-8"))
    tests = [
        node for node in _ast.walk(tree)
        if isinstance(node, _ast.FunctionDef)
        and node.name.startswith("test_")
    ]
    assert len(tests) >= 20, (
        f"only {len(tests)} test functions remain in this module — an "
        f"edit has removed some"
    )
