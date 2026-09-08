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
    """The rendered file, which is derived and never written by hand."""

    def _render(self, gate, *problems):
        """Render a gate from a state built out of the given problems."""
        state = _sync_gate.GateState(
            problems={
                name: _sync_gate.Problem(detail) for name, detail in problems
            },
        )
        _sync_gate.render_gate(gate, state, logging.getLogger("test-format"))
        return gate.read_text(encoding="utf-8").splitlines()

    def test_count_then_one_line_per_problem(self, tmp_path: Path) -> None:
        """Line 1 is the count; the rest is what gets printed."""
        lines = self._render(
            tmp_path / "g",
            ("fault", "the first problem"),
            ("degraded", "the second problem"),
        )
        assert lines[0] == "2"
        assert set(lines[1:]) == {"the first problem", "the second problem"}

    def test_a_clean_state_renders_zero(self, tmp_path: Path) -> None:
        """Zero problems is a one-line file saying so."""
        lines = self._render(tmp_path / "g")
        assert lines == ["0"]

    def test_details_are_collapsed_to_one_line_each(self, tmp_path) -> None:
        """
        A multi-line detail would break the count-then-lines contract the
        trigger parses.
        """
        lines = self._render(
            tmp_path / "g", ("fault", "first line\nsecond line\n\tthird"),
        )
        assert lines == ["1", "first line second line third"]

    def test_problems_render_in_a_stable_order(self, tmp_path) -> None:
        """
        So the gate text does not churn between runs for reasons nobody
        changed. Most actionable first.
        """
        lines = self._render(
            tmp_path / "g",
            ("refusals", "refusals"),
            ("outage", "outage"),
            ("fault", "fault"),
        )
        assert lines[1:] == ["outage", "fault", "refusals"]

    def test_parent_directory_is_created(self, tmp_path: Path) -> None:
        """A machine with no ``~/.cache`` yet must not crash the sync."""
        gate = tmp_path / "nested" / "cache" / "g"
        assert self._render(gate, ("fault", "x")) == ["1", "x"]
        assert gate.exists()

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

    def test_the_trigger_prints_every_problem_line(
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
            "2\nexactly one problem\nand a second, independent one\n",
            encoding="utf-8",
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
        # EVERY problem line, not just the first (fifth re-audit): these
        # gates carry one line per independent problem now.
        assert "and a second, independent one" in result.stdout
        # The count-0 gate must stay silent.
        assert "postgres-sync-memories" not in result.stdout


#: Every function that writes a gate file or its sidecar state. A new one
#: must be added here, or the structural test below cannot see it — which
#: is how three separate tests came to write the operator's real gate.
GATE_CALLS = (
    "apply_gate",
    "render_gate",
    "write_state",
    "read_state",
    "write_gate",
    "clear_gate",
    "raise_fault_gate",
    "apply_sync_gate",
)
GATED_SCRIPTS = (
    "sync-to-postgres.py",
    "sync-sessions-to-postgres.py",
    "index-session-content.py",
)


def _gate_call_nodes(source: str):
    """Yield every AST call node that touches a gate file or its state."""
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
    Parsed, not grepped (fourth re-audit, finding M6), and covering every
    function that writes a gate OR its sidecar state (fifth re-audit).

    The substring version of this test was defeated by anything that
    merely *contained* the right text — ``gate_path=GATE_FILE if False
    else Path.home() / ".cache" / "x"`` passed it while writing the
    operator's real gate. Three times during this audit a test wrote a
    real gate file and would have put a fabricated infrastructure problem
    in front of Shawn at session start.

    Every such call must pass its path as a bare Name, and that name must
    be the script's own ``GATE_FILE`` (or a parameter a helper was handed
    it in) — never an expression, never the shared default, never a
    literal path.
    """
    source = (SCRIPTS_DIR / script_name).read_text(encoding="utf-8")
    calls = list(_gate_call_nodes(source))
    assert calls, f"{script_name} touches no gate at all"

    for name, node in calls:
        keywords = {kw.arg: kw.value for kw in node.keywords}
        positional = node.args
        # The path may be the first positional argument (render_gate,
        # write_state, read_state) or the gate_path keyword (apply_gate).
        value = keywords.get("gate_path")
        if value is None and positional:
            value = positional[0]
        assert value is not None, (
            f"{script_name}:{node.lineno}: {name} passes no gate path"
        )
        assert isinstance(value, ast.Name), (
            f"{script_name}:{node.lineno}: the gate path given to {name} "
            f"is a {type(value).__name__}, not a plain name — an "
            f"expression here can evaluate to any path at all"
        )
        assert value.id in ("GATE_FILE", "gate_path"), (
            f"{script_name}:{node.lineno}: the gate path given to {name} "
            f"is bound to {value.id!r}, not the module's GATE_FILE"
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
    assert len(assignments) == 1, (
        f"{script_name}: GATE_FILE is not assigned exactly once"
    )
    value = assignments[0].value
    assert isinstance(value, ast.Name) and value.id == "_DEFAULT_GATE_FILE", (
        f"{script_name}: GATE_FILE is not the shared per-script constant"
    )


@pytest.mark.parametrize("script_name", GATED_SCRIPTS)
def test_no_script_decides_gate_semantics_for_itself(script_name):
    """
    Every script goes through ``apply_gate``, and none of them renders a
    gate or writes a state directly. Five rounds of re-audit found the
    same leak each time a script was allowed its own rule.
    """
    source = (SCRIPTS_DIR / script_name).read_text(encoding="utf-8")
    names = [name for name, _ in _gate_call_nodes(source)]
    assert "apply_gate" in names, f"{script_name} bypasses the state machine"
    for forbidden in ("render_gate", "write_state", "write_gate", "clear_gate"):
        assert forbidden not in names, (
            f"{script_name} calls {forbidden} directly instead of going "
            f"through apply_gate"
        )


class TestEvidenceLowersAProblem:
    """
    The governing invariant, now expressed per problem: each is raised and
    lowered by its own evidence, and by nothing else.
    """

    def _seed(self, gate, **event_kwargs):
        """Put the state machine into a known state."""
        return _sync_gate.apply_gate(
            _sync_gate.GateEvent(script="test", **event_kwargs),
            gate_path=gate, logger=logging.getLogger("test-gate"),
        )

    def _apply(self, gate, **event_kwargs):
        """Apply one more event."""
        return self._seed(gate, **event_kwargs)

    @pytest.mark.parametrize("outcome,connected,processed", [
        (_sync_gate.CYCLE_IDLE, None, 0),
        (_sync_gate.CYCLE_CONTENDED, True, 0),
        (_sync_gate.CYCLE_OUTAGE, False, 0),
        (_sync_gate.CYCLE_DEGRADED, True, 0),
        # Completed but nothing processed is not evidence either.
        (_sync_gate.CYCLE_COMPLETED, True, 0),
    ])
    def test_a_run_that_learnt_nothing_leaves_a_fault(
        self, tmp_path, outcome, connected, processed,
    ):
        """
        The mutation this kills: lowering ``fault`` on any outcome, or on
        a completed cycle that processed no rows.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_DEGRADED,
            fault_detail="a standing fault",
        )
        state = self._apply(
            gate, outcome=outcome, connected=connected, processed=processed,
        )
        assert _sync_gate.PROBLEM_FAULT in state.problems

    def test_a_completed_run_lowers_a_fault(self, tmp_path):
        """Real work, nothing refused: the one thing that is evidence."""
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_DEGRADED,
            fault_detail="a standing fault",
        )
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED,
            connected=True, processed=3,
        )
        assert _sync_gate.PROBLEM_FAULT not in state.problems

    def test_later_rows_never_lower_a_quarantine(self, tmp_path):
        """
        Fifth re-audit's first critical: that a hundred later memories
        synced cleanly is no evidence at all about the seven that were
        dropped. The mutation this kills: lowering ``quarantine`` on a
        completed run.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=2, quarantined=7,
            quarantine_file=tmp_path / "q.jsonl",
        )
        for _ in range(5):
            state = self._apply(
                gate, outcome=_sync_gate.CYCLE_COMPLETED,
                connected=True, processed=100,
            )
        assert _sync_gate.PROBLEM_QUARANTINE in state.problems
        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 7

    def test_the_quarantine_count_accumulates(self, tmp_path):
        """Each refusal adds to a running total, never replaces it."""
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantined=3,
        )
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantined=4,
        )
        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 7

    def test_only_an_acknowledgement_lowers_a_quarantine(self, tmp_path):
        """
        The one thing that clears it is a human saying they have looked.
        The mutation this kills: ignoring ``ack_quarantine``.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantined=7,
        )
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_IDLE, ack_quarantine=True,
        )
        assert _sync_gate.PROBLEM_QUARANTINE not in state.problems

    def test_an_acknowledgement_does_not_swallow_this_runs_refusals(
        self, tmp_path,
    ):
        """
        Acking clears what a human read, not what this very run refused
        while they were reading it.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantined=7,
        )
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantined=2, ack_quarantine=True,
        )
        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 2

    def test_the_quarantine_text_names_the_acknowledgement_command(
        self, tmp_path,
    ):
        """The operator must be told how to clear it, exactly."""
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantined=1,
            quarantine_file=Path("/data/q.jsonl"),
        )
        detail = gate.read_text(encoding="utf-8")
        assert "--ack-quarantine" in detail
        assert "venv/bin/python3" in detail
        assert "/data/q.jsonl" in detail

    def test_problems_do_not_overwrite_each_other(self, tmp_path):
        """
        Fifth re-audit: an outage used to overwrite the standing reason,
        and one later connected run cleared both. Independent problems
        stand independently, and the count says how many.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_DEGRADED,
            fault_detail="a fault", quarantined=4,
        )
        for _ in range(3):
            state = self._apply(
                gate, outcome=_sync_gate.CYCLE_OUTAGE, connected=False,
            )
        assert {
            _sync_gate.PROBLEM_FAULT,
            _sync_gate.PROBLEM_QUARANTINE,
            _sync_gate.PROBLEM_OUTAGE,
        } <= set(state.problems)
        assert gate.read_text(encoding="utf-8").splitlines()[0] == "3"

    def test_reconnecting_lowers_only_the_outage(self, tmp_path):
        """
        The exact leak the state machine exists to close: a connected run
        cleared the outage AND everything it had overwritten.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_DEGRADED,
            fault_detail="a fault", quarantined=4,
        )
        for _ in range(3):
            self._apply(
                gate, outcome=_sync_gate.CYCLE_OUTAGE, connected=False,
            )
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_IDLE, connected=True,
        )
        assert _sync_gate.PROBLEM_OUTAGE not in state.problems
        assert _sync_gate.PROBLEM_FAULT in state.problems
        assert _sync_gate.PROBLEM_QUARANTINE in state.problems

    def test_a_contended_run_changes_nothing_at_all(self, tmp_path):
        """Not even the streak: this run did literally nothing."""
        gate = tmp_path / "g"
        self._apply(gate, outcome=_sync_gate.CYCLE_OUTAGE, connected=False)
        before = _sync_gate.read_state(gate)
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_CONTENDED, connected=True,
        )
        assert state.outage_streak == before.outage_streak
        assert state.problems == before.problems

    def test_degraded_is_lowered_by_finding_the_inputs_again(self, tmp_path):
        """An idle run has at least found its canonical and its root."""
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_DEGRADED,
            degraded_detail="the archive root is missing",
        )
        state = self._apply(gate, outcome=_sync_gate.CYCLE_IDLE)
        assert _sync_gate.PROBLEM_DEGRADED not in state.problems

    def test_every_degraded_outcome_is_reported(self, tmp_path):
        """
        Fifth re-audit's third critical: degraded outcomes were silent,
        including the cursor-held stall. The mutation this kills: dropping
        ``degraded_detail`` from the event.
        """
        gate = tmp_path / "g"
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_DEGRADED,
            degraded_detail="ids dropped and the cursor is HELD",
        )
        assert _sync_gate.PROBLEM_DEGRADED in state.problems
        assert "cursor is HELD" in gate.read_text(encoding="utf-8")


class TestTheTransitionMatrix:
    """
    The docstring's rules, executable: every standing problem crossed with
    every outcome, asserted. If a rule changes, this table changes with
    it — deliberately, and visibly.
    """

    #: (problem, outcome, connected, processed) -> does it still stand?
    MATRIX = [
        # fault: only a completed run with work done lowers it.
        ("fault", _sync_gate.CYCLE_IDLE, None, 0, True),
        ("fault", _sync_gate.CYCLE_CONTENDED, True, 0, True),
        ("fault", _sync_gate.CYCLE_OUTAGE, False, 0, True),
        ("fault", _sync_gate.CYCLE_DEGRADED, True, 0, True),
        ("fault", _sync_gate.CYCLE_COMPLETED, True, 0, True),
        ("fault", _sync_gate.CYCLE_COMPLETED, True, 1, False),
        # correlated: the same rule.
        ("correlated", _sync_gate.CYCLE_IDLE, None, 0, True),
        ("correlated", _sync_gate.CYCLE_CONTENDED, True, 0, True),
        ("correlated", _sync_gate.CYCLE_OUTAGE, False, 0, True),
        ("correlated", _sync_gate.CYCLE_DEGRADED, True, 0, True),
        ("correlated", _sync_gate.CYCLE_COMPLETED, True, 1, False),
        # quarantine: nothing here lowers it. Only --ack-quarantine.
        ("quarantine", _sync_gate.CYCLE_IDLE, None, 0, True),
        ("quarantine", _sync_gate.CYCLE_CONTENDED, True, 0, True),
        ("quarantine", _sync_gate.CYCLE_OUTAGE, False, 0, True),
        ("quarantine", _sync_gate.CYCLE_DEGRADED, True, 0, True),
        ("quarantine", _sync_gate.CYCLE_COMPLETED, True, 1, True),
        ("quarantine", _sync_gate.CYCLE_COMPLETED, True, 999, True),
        # degraded: completed or idle lowers it; the rest do not.
        ("degraded", _sync_gate.CYCLE_IDLE, None, 0, False),
        ("degraded", _sync_gate.CYCLE_CONTENDED, True, 0, True),
        ("degraded", _sync_gate.CYCLE_OUTAGE, False, 0, True),
        ("degraded", _sync_gate.CYCLE_DEGRADED, True, 0, True),
        ("degraded", _sync_gate.CYCLE_COMPLETED, True, 1, False),
        # outage: connecting lowers it, whatever else the run did.
        ("outage", _sync_gate.CYCLE_IDLE, True, 0, False),
        ("outage", _sync_gate.CYCLE_IDLE, None, 0, True),
        ("outage", _sync_gate.CYCLE_CONTENDED, True, 0, True),
        ("outage", _sync_gate.CYCLE_OUTAGE, False, 0, True),
        ("outage", _sync_gate.CYCLE_DEGRADED, True, 0, False),
        ("outage", _sync_gate.CYCLE_COMPLETED, True, 1, False),
        # refusals: only an authoritative run reporting none lowers it.
        ("refusals", _sync_gate.CYCLE_COMPLETED, True, 1, True),
        ("refusals", _sync_gate.CYCLE_IDLE, None, 0, True),
    ]

    def _standing(self, gate, problem: str):
        """Put exactly one problem into the state."""
        events = {
            "fault": dict(
                outcome=_sync_gate.CYCLE_DEGRADED, fault_detail="f",
            ),
            "correlated": dict(
                outcome=_sync_gate.CYCLE_DEGRADED, correlated_detail="c",
            ),
            "quarantine": dict(
                outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
                processed=1, quarantined=5,
            ),
            "degraded": dict(
                outcome=_sync_gate.CYCLE_DEGRADED, degraded_detail="d",
            ),
            "outage": dict(
                outcome=_sync_gate.CYCLE_OUTAGE, connected=False,
            ),
            "refusals": dict(
                outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
                processed=1, refusals=4,
            ),
        }[problem]
        repeats = _sync_gate.OUTAGE_STREAK_THRESHOLD if problem == "outage" else 1
        for _ in range(repeats):
            state = _sync_gate.apply_gate(
                _sync_gate.GateEvent(script="test", **events),
                gate_path=gate, logger=logging.getLogger("test-matrix"),
            )
        assert problem in state.problems, f"failed to raise {problem}"
        return state

    @pytest.mark.parametrize(
        "problem,outcome,connected,processed,still_standing", MATRIX,
    )
    def test_transition(
        self, tmp_path, problem, outcome, connected, processed,
        still_standing,
    ):
        """
        One cell of the table. The mutation this kills: any change to a
        raise/lower rule that nobody meant to make.
        """
        gate = tmp_path / "g"
        self._standing(gate, problem)
        state = _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=outcome, connected=connected, processed=processed,
                script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-matrix"),
        )
        assert (problem in state.problems) is still_standing, (
            f"{problem} after {outcome} (connected={connected}, "
            f"processed={processed}) should "
            f"{'stand' if still_standing else 'be lowered'}"
        )

    def test_the_matrix_covers_every_problem(self):
        """A new problem kind must arrive with its own rules and rows."""
        covered = {row[0] for row in self.MATRIX}
        known = {
            _sync_gate.PROBLEM_FAULT, _sync_gate.PROBLEM_CORRELATED,
            _sync_gate.PROBLEM_QUARANTINE, _sync_gate.PROBLEM_DEGRADED,
            _sync_gate.PROBLEM_OUTAGE, _sync_gate.PROBLEM_REFUSALS,
        }
        assert covered == known

    def test_the_rendered_count_is_the_number_of_standing_problems(
        self, tmp_path,
    ):
        """
        Never clamped: a count that says 1 when three things are wrong is
        how a gate comes to mean something other than what it says.
        """
        gate = tmp_path / "g"
        for count, kwargs in (
            (0, dict(outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
                     processed=1)),
            (1, dict(outcome=_sync_gate.CYCLE_DEGRADED, fault_detail="f")),
            (3, dict(outcome=_sync_gate.CYCLE_DEGRADED, fault_detail="f",
                     correlated_detail="c", degraded_detail="d")),
        ):
            _sync_gate.apply_gate(
                _sync_gate.GateEvent(script="test", **kwargs),
                gate_path=gate, logger=logging.getLogger("test-matrix"),
            )
            assert gate.read_text(encoding="utf-8").splitlines()[0] == str(count)


class TestStateFileDiagnostics:
    """
    Fifth re-audit: a state we cannot read or write means every standing
    problem is silently forgotten. That must never be silent.
    """

    def test_a_corrupt_state_is_reported(self, tmp_path, caplog):
        """The mutation this kills: swallowing the JSONDecodeError."""
        gate = tmp_path / "g"
        _sync_gate.state_path_for(gate).parent.mkdir(parents=True, exist_ok=True)
        _sync_gate.state_path_for(gate).write_text("{not json", encoding="utf-8")
        with caplog.at_level(logging.ERROR):
            state = _sync_gate.read_state(
                gate, logging.getLogger("test-state"),
            )
        assert state.problems == {}
        assert "corrupt" in caplog.text

    def test_an_unwritable_state_is_reported(self, tmp_path, caplog):
        """The mutation this kills: swallowing the OSError on write."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        gate = blocker / "g"
        with caplog.at_level(logging.ERROR):
            written = _sync_gate.write_state(
                gate, _sync_gate.GateState(), logging.getLogger("test-state"),
            )
        assert written is False
        assert "Could not write the gate state" in caplog.text

    def test_an_unwritable_gate_is_reported(self, tmp_path, caplog):
        """A gate we cannot render is a run whose problems never surface."""
        blocker = tmp_path / "blocker2"
        blocker.write_text("not a directory", encoding="utf-8")
        gate = blocker / "g"
        with caplog.at_level(logging.ERROR):
            written = _sync_gate.render_gate(
                gate, _sync_gate.GateState(), logging.getLogger("test-state"),
            )
        assert written is False
        assert "Could not write the gate file" in caplog.text

    def test_a_missing_state_is_silent(self, tmp_path, caplog):
        """A first run is ordinary, not a problem to report."""
        with caplog.at_level(logging.ERROR):
            _sync_gate.read_state(
                tmp_path / "never-written", logging.getLogger("test-state"),
            )
        assert caplog.text == ""


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
