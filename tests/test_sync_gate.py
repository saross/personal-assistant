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
import fcntl
import logging
import multiprocessing
import os
import subprocess
import time
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
TRIGGER = SCRIPTS_DIR / "daily-sync-trigger.sh"
sys.path.insert(0, str(SCRIPTS_DIR))

import _sync_gate  # noqa: E402


def _ack_worker(gate_path: str) -> None:
    """Acknowledge the quarantine, as `--ack-quarantine` does."""
    _sync_gate.apply_gate(
        _sync_gate.GateEvent(
            outcome=_sync_gate.CYCLE_ACK, quarantine_entries=2,
            script="test",
        ),
        gate_path=Path(gate_path), logger=logging.getLogger("ack-worker"),
    )


def _tick_worker(gate_path: str) -> None:
    """A cron tick that quarantines two more rows."""
    _sync_gate.apply_gate(
        _sync_gate.GateEvent(
            outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=2, script="test",
        ),
        gate_path=Path(gate_path), logger=logging.getLogger("tick-worker"),
    )


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
        start = source.index("PG_GATE_STALE_HOURS=")
        end = source.index("unset _pg_gate_name", start)
        block = source[start:end]

        cache = tmp_path / ".cache"
        cache.mkdir()
        (cache / "postgres-sync-sessions-gate").write_text(
            "2\nexactly one problem\nand a second, independent one\n",
            encoding="utf-8",
        )
        # Every gate must exist, or the never-written check fires and
        # drowns out what this test is actually about.
        for name in (
            "postgres-sync-memories-gate", "index-session-content-gate",
        ):
            (cache / name).write_text("0\n", encoding="utf-8")

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
        # The count-0 gates must stay silent.
        assert "postgres-sync-memories" not in result.stdout
        assert "index-session-content" not in result.stdout


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
            processed=2, quarantine_entries=7,
            quarantine_file=tmp_path / "q.jsonl",
        )
        for _ in range(5):
            state = self._apply(
                gate, outcome=_sync_gate.CYCLE_COMPLETED,
                connected=True, processed=100,
            )
        assert _sync_gate.PROBLEM_QUARANTINE in state.problems
        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 7

    def test_the_count_follows_the_file(self, tmp_path):
        """
        The count is the file's length beyond the acknowledged position,
        recomputed every run — not a running total anyone has to keep
        (eighth re-audit, finding C1). The mutation this kills:
        accumulating a per-run delta again.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=3,
        )
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=7,
        )
        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 7

    def test_an_unreadable_quarantine_file_leaves_the_problem_alone(
        self, tmp_path,
    ):
        """
        ``None`` is not zero: a file we could not read is no evidence
        that the rows were repaired.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=4,
        )
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=None,
        )
        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 4

    def test_a_lost_tick_is_repaired_by_the_next(self, tmp_path):
        """
        Finding M5, dissolved by the same change: a run whose gate write
        failed loses nothing, because the next run recomputes from the
        file rather than adding to a total that was never stored.
        """
        gate = tmp_path / "g"
        # The tick that quarantined two rows never reached the gate.
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=2,
        )
        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 2

    def test_an_ack_then_a_reset_counts_the_rows_again(self, tmp_path):
        """
        Finding M4, likewise: after an acknowledgement, a rebuild
        re-offers the same rows and they are refused again. The
        acknowledged position is forgotten, so they are reported.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=2,
        )
        self._apply(
            gate, outcome=_sync_gate.CYCLE_ACK, quarantine_entries=2,
        )
        # A rebuild clears the cursor; the rows are re-offered.
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_DEGRADED, fault_detail="exit 6",
            reset_quarantine_ack=True, quarantine_entries=2,
        )
        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 2

    def test_only_an_acknowledgement_lowers_a_quarantine(self, tmp_path):
        """
        The one thing that clears it is a human saying they have looked.
        The mutation this kills: ignoring ``ack_quarantine``.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=7,
        )
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_ACK, quarantine_entries=7,
        )
        assert _sync_gate.PROBLEM_QUARANTINE not in state.problems

    def test_rows_quarantined_after_an_ack_are_reported(self, tmp_path):
        """
        Acknowledging records a position, not a count: three more rows
        after it are three new problems, not a cleared slate.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=7,
        )
        self._apply(gate, outcome=_sync_gate.CYCLE_ACK, quarantine_entries=7)
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=10,
        )
        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 3

    def _sidecar(self, gate: Path) -> dict:
        """The acked block AS PERSISTED, not as returned in memory.

        The distinction is the whole of the ninth re-audit's C1: the
        transition computed a new acknowledged position and then returned
        the old one, so the correction survived exactly one render.
        """
        import json

        state_file = gate.with_name(gate.name + ".state.json")
        return json.loads(state_file.read_text(encoding="utf-8"))["acked"]

    def test_a_reset_position_is_persisted_not_just_rendered(self, tmp_path):
        """
        Ninth re-audit, C1. After a reset the sidecar must say the
        acknowledged position is zero. The mutation this kills: ending
        ``next_state`` with ``acked = state.acked``, which keeps the old
        position on disk — the next idle run then recomputes an
        outstanding count of nothing and pops a problem it learnt nothing
        about.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=2,
        )
        self._apply(gate, outcome=_sync_gate.CYCLE_ACK, quarantine_entries=2)
        assert self._sidecar(gate)["acked_position"] == 2

        self._apply(
            gate, outcome=_sync_gate.CYCLE_DEGRADED, fault_detail="exit 6",
            reset_quarantine_ack=True, quarantine_entries=2,
        )
        assert self._sidecar(gate)["acked_position"] == 0, (
            "the reset was rendered but never saved"
        )

        # And the run after it — an idle one, which may touch nothing —
        # still sees the two rows.
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_IDLE, connected=True,
            quarantine_entries=2,
        )
        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 2, (
            "an idle run lowered a problem it learnt nothing about"
        )

    def test_a_clamped_position_is_persisted_not_just_rendered(
        self, tmp_path,
    ):
        """
        The quarantine file shrank — repaired and replayed by hand, or
        rotated — below the acknowledged position. The clamp brings the
        position back to the file's length, and that correction has to
        survive to the next run. The mutation this kills: deleting the
        ``min(acked_position, entries)`` clamp, or discarding it.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=9,
        )
        self._apply(gate, outcome=_sync_gate.CYCLE_ACK, quarantine_entries=9)
        assert self._sidecar(gate)["acked_position"] == 9

        # The file is rebuilt with three rows.
        self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=3,
        )
        assert self._sidecar(gate)["acked_position"] == 3, (
            "the clamp was rendered but never saved"
        )

        # Two more rows land: two outstanding, not eleven and not zero.
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=5,
        )
        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 2

    def test_a_nonsense_acked_position_is_ignored_and_corrected(
        self, tmp_path,
    ):
        """
        The sidecar is a file on disk that a person can edit. A negative
        or non-integer position must be treated as zero AND written back
        as zero, or every run re-derives from rubbish. The mutation this
        kills: deleting the isinstance/negative guard.
        """
        import json

        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=4,
        )
        state_file = gate.with_name(gate.name + ".state.json")
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        raw["acked"]["acked_position"] = -17
        state_file.write_text(json.dumps(raw), encoding="utf-8")

        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=4,
        )

        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 4
        assert self._sidecar(gate)["acked_position"] == 0

        raw = json.loads(state_file.read_text(encoding="utf-8"))
        raw["acked"]["acked_position"] = "seventeen"
        state_file.write_text(json.dumps(raw), encoding="utf-8")
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=4,
        )
        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 4

    def test_the_ack_records_the_position_it_was_given(self, tmp_path):
        """
        The acknowledgement is the only thing that moves the position
        forward, and it takes it from the event. The mutation this kills:
        dropping ``quarantine_entries=entries`` from the ack event, which
        leaves the position where it was and re-reports rows the operator
        has just dismissed.
        """
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=6,
        )
        self._apply(gate, outcome=_sync_gate.CYCLE_ACK, quarantine_entries=6)

        assert self._sidecar(gate)["acked_position"] == 6
        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=6,
        )
        assert _sync_gate.PROBLEM_QUARANTINE not in state.problems

    def test_the_quarantine_text_names_the_acknowledgement_command(
        self, tmp_path,
    ):
        """The operator must be told how to clear it, exactly."""
        gate = tmp_path / "g"
        self._seed(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=1,
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
            fault_detail="a fault", quarantine_entries=4,
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
            fault_detail="a fault", quarantine_entries=4,
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
        # M1: quarantines raise their own problem and must not stop a
        # completed run lowering a fault.
        ("fault", _sync_gate.CYCLE_COMPLETED, True, 50, False),
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
        # outage: connecting lowers it, whatever else the run did. An
        # idle run now reports connected=True when the advisory lock was
        # taken over a live connection (M3), which is the common case;
        # connected=None is a run that never tried at all.
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
                processed=1, quarantine_entries=5,
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
                # The quarantine file has not changed between the two
                # runs, so a standing quarantine problem must persist.
                quarantine_entries=5 if problem == "quarantine" else None,
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
        """
        A new problem kind must arrive with its own rules and its own
        rows. Derived from ``PROBLEM_ORDER`` rather than a hard-coded set
        (sixth re-audit, finding M5): a list written out by hand is
        updated by the same edit that adds the problem, and so proves
        nothing.
        """
        covered = {row[0] for row in self.MATRIX}
        assert covered == set(_sync_gate.PROBLEM_ORDER)

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


class TestQuarantinesDoNotBlockAFaultLowering:
    """
    Sixth re-audit, finding M1 — ``completed_cleanly`` required zero
    quarantines, so a run that processed fifty rows and refused one left
    a standing fault untouched. The two are independent problems.
    """

    def test_a_run_with_a_quarantine_still_lowers_a_fault(self, tmp_path):
        """The mutation this kills: restoring ``not event.quarantined``."""
        gate = tmp_path / "g"
        _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_DEGRADED, fault_detail="f",
                script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-m1"),
        )
        state = _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
                processed=50, quarantine_entries=1, script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-m1"),
        )
        assert _sync_gate.PROBLEM_FAULT not in state.problems
        assert _sync_gate.PROBLEM_QUARANTINE in state.problems


class TestTheOutageThresholdIsPinned:
    """
    Low: the streak's threshold was only ever exercised at its current
    value by tests that hard-coded 3.
    """

    def _outage(self, gate):
        """One unreachable run."""
        return _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_OUTAGE, connected=False,
                script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-streak"),
        )

    def test_one_outage_does_not_raise_the_problem(self, tmp_path):
        """A restart is not an outage worth waking anyone for."""
        state = self._outage(tmp_path / "g")
        assert _sync_gate.PROBLEM_OUTAGE not in state.problems
        assert state.outage_streak == 1

    def test_the_threshold_is_where_the_constant_says(self, tmp_path):
        """
        Derived from ``OUTAGE_STREAK_THRESHOLD``, so changing the constant
        changes the test with it rather than leaving it lying.
        """
        gate = tmp_path / "g"
        for run in range(1, _sync_gate.OUTAGE_STREAK_THRESHOLD):
            state = self._outage(gate)
            assert _sync_gate.PROBLEM_OUTAGE not in state.problems, (
                f"the problem stood after only {run} outage(s)"
            )
        state = self._outage(gate)
        assert _sync_gate.PROBLEM_OUTAGE in state.problems
        assert state.problems[
            _sync_gate.PROBLEM_OUTAGE
        ].count == _sync_gate.OUTAGE_STREAK_THRESHOLD


class TestWhitespaceOnlyDetails:
    """Low: a problem whose text is blank must not render an empty line."""

    def test_a_blank_detail_is_not_raised(self, tmp_path):
        """
        A problem nobody can read is worse than none: the count says
        something is wrong and the line says nothing at all.
        """
        gate = tmp_path / "g"
        state = _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_DEGRADED, fault_detail="   \n\t ",
                script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-blank"),
        )
        assert _sync_gate.PROBLEM_FAULT not in state.problems
        assert gate.read_text(encoding="utf-8").strip() == "0"


class TestConcurrencyAroundTheAcknowledgement:
    """
    Finding C2 — a cron tick and an ack interleaving used to resurrect a
    dismissed problem: both read the same state, and the tick wrote last.
    """

    def test_an_ack_is_not_undone_by_a_concurrent_tick(self, tmp_path):
        """
        Two real processes, the real flock. The mutation this kills:
        dropping ``gate_lock`` from ``apply_gate``.
        """
        gate = tmp_path / "g"
        _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
                processed=1, quarantine_entries=5, script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-race"),
        )

        ctx = multiprocessing.get_context("fork")
        for _ in range(20):
            _sync_gate.apply_gate(
                _sync_gate.GateEvent(
                    outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
                    processed=1, quarantine_entries=5, script="test",
                ),
                gate_path=gate, logger=logging.getLogger("test-race"),
            )
            procs = [
                ctx.Process(target=_ack_worker, args=(str(gate),)),
                ctx.Process(target=_tick_worker, args=(str(gate),)),
            ]
            for proc in procs:
                proc.start()
            for proc in procs:
                proc.join(timeout=30)

            state = _sync_gate.read_state(gate)
            quarantine = state.problems.get(_sync_gate.PROBLEM_QUARANTINE)
            # Either order is legal; what is not legal is a torn state in
            # which the tick's count survives the ack that followed it.
            assert quarantine is None or quarantine.count == 2, (
                f"interleaved ack and tick left {quarantine}"
            )

    def test_a_kill_mid_write_leaves_the_previous_gate(
        self, tmp_path, monkeypatch,
    ):
        """
        Atomic replacement: an interrupted render must not truncate the
        gate into "no problems". The mutation this kills: writing the
        gate or the sidecar with a plain ``write_text``.
        """
        gate = tmp_path / "g"
        _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_DEGRADED, fault_detail="standing",
                script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-atomic"),
        )
        before = gate.read_bytes()

        def _boom(src, dst):
            raise KeyboardInterrupt("killed mid-write")

        monkeypatch.setattr(os, "replace", _boom)
        with pytest.raises(KeyboardInterrupt):
            _sync_gate.apply_gate(
                _sync_gate.GateEvent(
                    outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
                    processed=1, script="test",
                ),
                gate_path=gate, logger=logging.getLogger("test-atomic"),
            )

        assert gate.read_bytes() == before


#: Any of these names in a write target's source text means the write is
#: aimed at a gate, its sidecar, or the cache directory they live in.
GATE_TARGET_HINTS = (
    "GATE_FILE", "gate_path", "gate", ".cache", "state_path", "_DEFAULT_GATE",
)


def _gate_flavoured_names(tree: ast.AST) -> set[str]:
    """Names bound to something that smells like a gate path.

    One level of aliasing, which is all it takes to defeat a check that
    only looks at the write's own target: ``sneaky = Path.home() /
    ".cache" / "x"`` followed by ``sneaky.write_text(...)`` (seventh
    re-audit, finding M5). Resolved transitively, so a chain of aliases
    is caught too.
    """
    aliases: set[str] = set()
    for _ in range(4):  # a fixed point, reached in one or two passes
        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            rendered = ast.unparse(node.value)
            if not (
                any(hint in rendered for hint in GATE_TARGET_HINTS)
                or any(name in rendered.split() for name in aliases)
                or any(f"{name}." in rendered for name in aliases)
            ):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    grew = True
        if not grew:
            break
    return aliases


@pytest.mark.parametrize("script_name", GATED_SCRIPTS)
def test_no_script_writes_a_gate_path_directly(script_name):
    """
    Name-based checking is not enough (sixth re-audit, finding M6): a
    script could bypass the whole state machine with
    ``some_gate_path.write_text(...)`` and the call-name test would not
    see it, because the call is named ``write_text``.

    Nor is checking only the write's own target text (seventh re-audit,
    finding M5): one intermediate variable hid it. Simple aliases are
    resolved first, then no ``write_text``, ``write_bytes``, ``open`` or
    ``os.replace`` may name a gate, a sidecar, the cache directory, or
    anything bound from one.
    """
    source = (SCRIPTS_DIR / script_name).read_text(encoding="utf-8")
    tree = ast.parse(source)
    aliases = _gate_flavoured_names(tree)
    # The indexer's refusal memory is the one other store under ~/.cache.
    # It is not a gate, it has its own writer, and that writer is checked
    # separately just below.
    exempt: set[int] = set()
    for func in ast.walk(tree):
        if isinstance(func, ast.FunctionDef) and func.name == "save_refusals":
            exempt |= {
                inner.lineno for inner in ast.walk(func)
                if hasattr(inner, "lineno")
            }
    offenders = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else None
        )
        if name not in ("write_text", "write_bytes", "open", "replace"):
            continue
        rendered = ast.unparse(node)
        mentions_gate = any(hint in rendered for hint in GATE_TARGET_HINTS)
        mentions_alias = any(
            alias in {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            for alias in aliases
        )
        if node.lineno in exempt:
            continue
        if mentions_gate or mentions_alias:
            offenders.append(f"{script_name}:{node.lineno}: {rendered[:90]}")

    assert not offenders, (
        "these write directly to a gate or its sidecar instead of going "
        "through the state machine:\n  " + "\n  ".join(offenders)
    )


def test_only_the_gate_module_writes_gate_files():
    """
    The companion check on the module itself: ``_sync_gate.py`` is
    allowed to write these paths, and is the only file that may.
    """
    source = (SCRIPTS_DIR / "_sync_gate.py").read_text(encoding="utf-8")
    assert "_atomic_write" in source
    # And every write inside it goes through that one helper.
    tree = ast.parse(source)
    # ``open`` and ``os.replace`` too, not just the Path helpers: a
    # ``gate_path.open("w")`` bypasses the atomic write just as neatly
    # (seventh re-audit, finding M5). The two inside ``_atomic_write``
    # itself are how it does its job, so they are named and excused.
    allowed_lines = {
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_atomic_write"
        for node in ast.walk(node)
        if isinstance(node, ast.Call)
    }
    direct = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute)
             and node.func.attr in ("write_text", "write_bytes", "open",
                                    "replace"))
            or (isinstance(node.func, ast.Name) and node.func.id == "open")
        )
        and node.lineno not in allowed_lines
        # The lock file is opened, never written through.
        and "lock_file" not in ast.unparse(node)
    ]
    assert not direct, (
        f"_sync_gate.py writes outside _atomic_write at lines {direct}"
    )


def test_the_gate_lock_is_held_across_the_read_modify_write(tmp_path):
    """
    Finding C2, deterministically. A race test can pass by luck; this
    asserts from inside the transition that the lock is actually held,
    which no interleaving can fake.

    ``flock`` is per open file description, so a second ``open`` in this
    same process conflicts with the one ``apply_gate`` holds. The
    mutation this kills: dropping ``gate_lock`` from ``apply_gate``.
    """
    gate = tmp_path / "g"
    lock_file = _sync_gate.lock_path_for(gate)
    observed = {"held": None}
    real_next_state = _sync_gate.next_state

    def _probe(state, event):
        """Check, mid-cycle, that nobody else could be doing this too."""
        with open(lock_file, "a", encoding="utf-8") as probe:
            try:
                fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                observed["held"] = True
            else:
                observed["held"] = False
                fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
        return real_next_state(state, event)

    _sync_gate.next_state = _probe
    try:
        _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_DEGRADED, fault_detail="x",
                script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-lock"),
        )
    finally:
        _sync_gate.next_state = real_next_state

    assert observed["held"] is True, (
        "the gate state was read and written without holding the lock"
    )


def _hold_shared_lock(lock_path: str, seconds: float) -> None:
    """Hold a SHARED lock on the gate lock file (module level, for fork)."""
    with open(lock_path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        time.sleep(seconds)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class TestTheLockIsExclusive:
    """
    ``LOCK_EX`` → ``LOCK_SH`` survived every earlier test, because a
    shared lock still *looks* taken to a non-blocking exclusive probe.
    The difference only shows when a second holder must be excluded.
    """

    def test_an_exclusive_taker_waits_for_another_holder(self, tmp_path):
        """
        A second process holds the lock shared; the exclusive taker must
        BLOCK until it lets go. Under ``LOCK_SH`` it would sail straight
        through, which is the whole bug: two cycles reading and writing
        the same state at once. The mutation this kills: LOCK_EX →
        LOCK_SH.
        """
        gate = tmp_path / "g"
        lock_file = _sync_gate.lock_path_for(gate)
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.touch()

        ctx = multiprocessing.get_context("fork")
        holder = ctx.Process(
            target=_hold_shared_lock, args=(str(lock_file), 1.0),
        )
        holder.start()
        time.sleep(0.25)  # let the child take it

        started = time.monotonic()
        with _sync_gate.gate_lock(gate):
            waited = time.monotonic() - started
        holder.join(timeout=30)

        assert waited > 0.4, (
            f"the exclusive lock was taken in {waited:.3f}s while another "
            f"process held it — it is not exclusive"
        )

    def test_a_wedged_holder_is_reported_not_waited_on_for_ever(
        self, tmp_path, monkeypatch,
    ):
        """
        Low: a bare blocking LOCK_EX would hang a session hook for ever.
        The wait is bounded and says so.
        """
        gate = tmp_path / "g"
        lock_file = _sync_gate.lock_path_for(gate)
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.touch()
        monkeypatch.setattr(_sync_gate, "LOCK_WAIT_SECONDS", 0.3)

        ctx = multiprocessing.get_context("fork")
        holder = ctx.Process(
            target=_hold_shared_lock, args=(str(lock_file), 2.0),
        )
        holder.start()
        time.sleep(0.25)
        try:
            with pytest.raises(TimeoutError, match="has held"):
                with _sync_gate.gate_lock(gate):
                    pass
        finally:
            holder.join(timeout=30)


class TestWritesHappenInsideTheLock:
    """
    ``render_gate`` outside the lock survived: the state was serialised
    but the file everyone reads was not.
    """

    def test_the_gate_is_rendered_inside_the_lock(self, tmp_path):
        """
        Observed from inside ``render_gate``. The mutation this kills:
        moving the render out of the ``with gate_lock(...)`` block.
        """
        gate = tmp_path / "g"
        lock_file = _sync_gate.lock_path_for(gate)
        observed = {"held": None}
        real_render = _sync_gate.render_gate

        def _probe(path, state, logger=None):
            with open(lock_file, "a", encoding="utf-8") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    observed["held"] = True
                else:
                    observed["held"] = False
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return real_render(path, state, logger)

        _sync_gate.render_gate = _probe
        try:
            _sync_gate.apply_gate(
                _sync_gate.GateEvent(
                    outcome=_sync_gate.CYCLE_DEGRADED, fault_detail="x",
                    script="test",
                ),
                gate_path=gate, logger=logging.getLogger("test-render"),
            )
        finally:
            _sync_gate.render_gate = real_render

        assert observed["held"] is True, (
            "the gate file was rendered outside the lock"
        )


class TestTheRenameIsMadeDurable:
    """The directory fsync after os.replace survived every earlier test."""

    def test_the_parent_directory_is_fsynced(self, tmp_path, monkeypatch):
        """
        Without it a power failure can lose the rename even though the
        file's contents were durable — the gate silently reverts. The
        mutation this kills: removing the directory fsync.
        """
        gate = tmp_path / "g"
        fsynced_dirs = []
        real_fsync = os.fsync

        def _record(fd):
            try:
                if os.path.isdir(f"/proc/self/fd/{fd}"):
                    fsynced_dirs.append(os.readlink(f"/proc/self/fd/{fd}"))
            except OSError:  # pragma: no cover — platform variation
                pass
            return real_fsync(fd)

        monkeypatch.setattr(os, "fsync", _record)
        _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_DEGRADED, fault_detail="x",
                script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-fsync"),
        )
        monkeypatch.undo()

        assert str(tmp_path) in fsynced_dirs, (
            f"the gate's directory was never fsynced: {fsynced_dirs}"
        )


class TestTheAcknowledgementEventIsItsOwnKind:
    """
    Finding M4 — the ack rode on ``CYCLE_IDLE``, and idle lowers
    ``degraded``. So acknowledging a quarantine also declared a missing
    archive root resolved.
    """

    def test_an_ack_does_not_lower_degraded(self, tmp_path):
        """The mutation this kills: sending CYCLE_IDLE for an ack."""
        gate = tmp_path / "g"
        _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
                processed=1, quarantine_entries=3, script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-ack-kind"),
        )
        _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_DEGRADED,
                degraded_detail="the archive root is missing", script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-ack-kind"),
        )

        state = _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_ACK, script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-ack-kind"),
        )

        assert _sync_gate.PROBLEM_QUARANTINE not in state.problems
        assert _sync_gate.PROBLEM_DEGRADED in state.problems, (
            "acknowledging a quarantine also lowered a degraded problem"
        )

    def test_an_ack_does_not_touch_the_outage_streak(self, tmp_path):
        """
        The mutation this kills: ``connected=True`` on the ack event,
        which would clear an outage nobody had recovered from.
        """
        gate = tmp_path / "g"
        for _ in range(_sync_gate.OUTAGE_STREAK_THRESHOLD):
            _sync_gate.apply_gate(
                _sync_gate.GateEvent(
                    outcome=_sync_gate.CYCLE_OUTAGE, connected=False,
                    script="test",
                ),
                gate_path=gate, logger=logging.getLogger("test-ack-kind"),
            )
        state = _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_ACK, script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-ack-kind"),
        )
        assert _sync_gate.PROBLEM_OUTAGE in state.problems
        assert state.outage_streak == _sync_gate.OUTAGE_STREAK_THRESHOLD


class TestApplyGateReportsWhatIsOnDisk:
    """
    Finding C1 — ``apply_gate`` returned the state it *meant* to write,
    so a caller could not tell a successful write from a failed one.
    """

    def test_a_failed_write_returns_the_old_state(self, tmp_path, monkeypatch):
        """
        The mutation this kills: returning the in-memory transition
        result instead of re-reading.
        """
        gate = tmp_path / "g"
        _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
                processed=1, quarantine_entries=4, script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-ondisk"),
        )

        def _fail(path, text):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(_sync_gate, "_atomic_write", _fail)
        state = _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_ACK, script="test",
            ),
            gate_path=gate, logger=logging.getLogger("test-ondisk"),
        )
        monkeypatch.undo()

        assert _sync_gate.PROBLEM_QUARANTINE in state.problems, (
            "apply_gate reported a state that was never written"
        )

    def test_a_failed_write_never_says_the_gate_is_clear(
        self, tmp_path, monkeypatch, caplog,
    ):
        """A log line claiming success over a failure is the whole bug."""
        gate = tmp_path / "g"

        def _fail(path, text):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(_sync_gate, "_atomic_write", _fail)
        with caplog.at_level(logging.ERROR):
            _sync_gate.apply_gate(
                _sync_gate.GateEvent(
                    outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
                    processed=1, script="test",
                ),
                gate_path=gate, logger=logging.getLogger("test-ondisk"),
            )
        monkeypatch.undo()

        assert "COULD NOT BE PERSISTED" in caplog.text
        assert "Gate: clear" not in caplog.text

    def test_an_unwritable_cache_does_not_raise(self, tmp_path, monkeypatch):
        """
        Finding M1: ``gate_lock``'s open had no error handling, so an
        unwritable ~/.cache raised PermissionError through every caller —
        turning a schema mismatch's exit 2 into an exit 1 traceback.
        """
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        state = _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_DEGRADED, fault_detail="x",
                script="test",
            ),
            gate_path=blocker / "g", logger=logging.getLogger("test-ondisk"),
        )
        assert state.problems == {}


def test_the_refusal_memory_is_also_written_atomically():
    """
    The one store under ``~/.cache`` that is not a gate. It is exempt
    from the direct-write check above, so its own atomicity is asserted
    here rather than assumed: a half-written refusal memory reads as
    "nothing refused" and sends the next run back into the same wall.
    """
    source = (SCRIPTS_DIR / "index-session-content.py").read_text(
        encoding="utf-8",
    )
    tree = ast.parse(source)
    saver = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "save_refusals"
    )
    body = ast.unparse(saver)
    assert ".tmp" in body, "save_refusals does not write to a temp file"
    assert "os.replace" in body, "save_refusals does not rename into place"


@pytest.mark.parametrize("script_name", GATED_SCRIPTS)
def test_no_script_names_itself_with_a_literal(script_name):
    """
    Every gate problem carries the script it came from, and the name is
    what Shawn is told to run to clear it. A literal at the call site is
    a second source of truth that a rename silently leaves behind — the
    banner then points at a script that no longer exists.

    Eighth re-audit, low. The mutation this kills: putting the literal
    back at either apply_gate call site.
    """
    source = (SCRIPTS_DIR / script_name).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "SCRIPT_NAME = " in source, f"{script_name} defines no SCRIPT_NAME"

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "script":
                continue
            if isinstance(keyword.value, ast.Constant):
                offenders.append(f"{script_name}:{node.lineno}")
    assert not offenders, (
        f"the script names itself with a literal instead of SCRIPT_NAME: "
        f"{offenders}"
    )


# ---------------------------------------------------------------------------
# Eighth re-audit — mutations that survived the suite as it stood
# ---------------------------------------------------------------------------


class TestTheLockIsReleasedExplicitly:
    """
    Closing the handle releases a flock as a side effect, so dropping the
    explicit ``LOCK_UN`` changes nothing a test could see from outside —
    which is exactly why it survived. The invariant is that the release
    is deliberate and happens while the fd is still ours, not left to
    whatever the interpreter does with the handle afterwards.
    """

    def test_the_unlock_is_issued_before_the_handle_is_closed(
        self, tmp_path, monkeypatch,
    ):
        """The mutation this kills: deleting the LOCK_UN call."""
        import fcntl

        calls: list[int] = []
        real_flock = fcntl.flock

        def _record(fileno, operation):
            calls.append(operation)
            return real_flock(fileno, operation)

        monkeypatch.setattr(_sync_gate.fcntl, "flock", _record)

        gate = tmp_path / "gates" / "g"
        with _sync_gate.gate_lock(gate):
            pass

        assert fcntl.LOCK_UN in calls, (
            "the lock was never released explicitly — it was left to the "
            "handle being closed"
        )
        assert calls.index(fcntl.LOCK_UN) > 0, "released before it was taken"

    def test_the_wait_is_bounded_by_a_sane_default(self):
        """
        A bare LOCK_EX would hang a cron tick or a session hook for ever
        behind a wedged holder; an unbounded default brings that back
        without changing a line of logic. Read from the module, with no
        monkeypatching, so the shipped value is what is pinned.
        """
        assert _sync_gate.LOCK_WAIT_SECONDS == 10.0, (
            "the shipped lock timeout changed — a hook must not wait "
            "longer than a person will"
        )


class TestTheTempFileIsFlushedBeforeItIsSynced:
    """
    ``os.fsync`` syncs what the kernel has, and Python's buffer is not
    the kernel's. Without the flush the sync is a no-op on an empty file
    and the data reaches disk only when the handle is closed — unsynced,
    which is the whole point of the call.
    """

    def test_the_file_has_its_bytes_when_fsync_is_called(
        self, tmp_path, monkeypatch,
    ):
        """
        The mutation this kills: removing ``handle.flush()`` — the file
        is then zero bytes at the moment it is synced.
        """
        import stat as stat_module

        sizes: list[int] = []
        real_fsync = _sync_gate.os.fsync

        def _record(fileno):
            info = os.fstat(fileno)
            if not stat_module.S_ISDIR(info.st_mode):
                sizes.append(info.st_size)
            return real_fsync(fileno)

        monkeypatch.setattr(_sync_gate.os, "fsync", _record)

        _sync_gate._atomic_write(tmp_path / "target", "some content\n")

        assert sizes, "the file itself was never fsynced"
        assert sizes[0] > 0, (
            "fsync ran against an empty file: the buffer had not been "
            "flushed, so nothing was actually made durable"
        )


class TestTheStateIsWrittenBeforeTheGateIsRendered:
    """
    The sidecar is the source of truth and the gate file is a mirror of
    it. Written in that order, a crash between the two leaves a correct
    state and a stale mirror, which the next run repairs. Reversed, a
    crash leaves a gate file the state does not justify, and the next run
    reverts it — a problem that was cleared comes back, or one that was
    raised disappears.
    """

    def test_apply_gate_persists_before_it_renders(self):
        """The mutation this kills: swapping the two calls."""
        source = (SCRIPTS_DIR / "_sync_gate.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        applier = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "apply_gate"
        )
        order = [
            node.func.id for node in ast.walk(applier)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("write_state", "render_gate")
        ]
        assert order, "apply_gate no longer writes the state or the gate"
        assert order.index("write_state") < order.index("render_gate"), (
            "the gate is rendered before the state it mirrors is saved"
        )


class TestAnAcknowledgementKeepsTheRecordedRoot:
    """
    ``archive_root`` says which archive tree the indexer's refusal memory
    was built against, and the memory's keys are relative paths. Losing
    it makes a memory built elsewhere look like one with no root
    recorded — which every reader treats as its own.
    """

    def test_the_ack_does_not_clear_the_archive_root(self):
        """
        The mutation this kills: taking the root from the event on the
        CYCLE_ACK branch, where it is always None.
        """
        state = _sync_gate.GateState(
            problems={
                _sync_gate.PROBLEM_QUARANTINE: _sync_gate.Problem("x", 2),
            },
            outage_streak=0,
            acked={},
            archive_root="/archives/cc",
        )

        after = _sync_gate.next_state(
            state,
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_ACK,
                quarantine_entries=2,
                script="test",
            ),
        )

        assert after.archive_root == "/archives/cc", (
            "acknowledging a quarantine forgot which archive tree the "
            "refusal memory belongs to"
        )
        assert _sync_gate.PROBLEM_QUARANTINE not in after.problems


class TestALockTimeoutDoesNotEscapeApplyGate:
    """
    ``gate_lock`` raises ``TimeoutError`` when another process has held
    the lock too long. Every caller of ``apply_gate`` is reporting on
    something else — a schema mismatch, an absent archive root, a clean
    cycle — and a contended gate must not rewrite that verdict.
    """

    def test_a_timeout_is_caught_and_the_disk_state_returned(
        self, tmp_path, monkeypatch, caplog,
    ):
        """
        The mutation this kills: narrowing the handler so TimeoutError
        raises through — every caller then turns a busy lock into an
        exit 1 traceback.
        """
        from contextlib import contextmanager

        gate = tmp_path / "gates" / "g"
        logger = logging.getLogger("test-timeout")
        _sync_gate.apply_gate(
            _sync_gate.GateEvent(
                outcome=_sync_gate.CYCLE_DEGRADED,
                fault_detail="something is wrong",
                script="test",
            ),
            gate_path=gate, logger=logger,
        )

        @contextmanager
        def _always_contended(gate_path):
            raise TimeoutError(f"another process has held {gate_path}")
            yield  # pragma: no cover — unreachable, keeps this a generator

        monkeypatch.setattr(_sync_gate, "gate_lock", _always_contended)

        with caplog.at_level(logging.ERROR):
            state = _sync_gate.apply_gate(
                _sync_gate.GateEvent(
                    outcome=_sync_gate.CYCLE_COMPLETED,
                    connected=True, processed=5, script="test",
                ),
                gate_path=gate, logger=logger,
            )

        assert "COULD NOT BE PERSISTED" in caplog.text
        assert _sync_gate.PROBLEM_FAULT in state.problems, (
            "the caller was told the fault had been cleared by a run that "
            "never reached the file"
        )


class TestTheAliasResolverFollowsAChain:
    """
    The structural check that no script writes a gate path directly
    resolves aliases to a fixed point. One pass finds only the first
    hop, and two hops is all it takes to hide a write.
    """

    def test_a_chain_is_resolved_whatever_order_it_is_visited_in(self):
        """
        ``ast.walk`` is breadth-first, not document order, so which
        assignment is seen first is an accident of where it sits in the
        tree. The alias written before the name it copies is the case a
        single pass cannot see: the copy is visited while the source is
        still unknown, and nothing goes back for it.

        The mutation this kills: one resolver pass instead of a fixed
        point.
        """
        source = (
            "third = second\n"
            "second = first\n"
            "first = GATE_FILE\n"
            "unrelated = compute()\n"
        )
        names = _gate_flavoured_names(ast.parse(source))

        assert {"first", "second", "third"} <= names, (
            f"the resolver stopped short of the chain: {sorted(names)}"
        )
        assert "unrelated" not in names


#: The modules this audit tranche owns. House style is 100 columns, and a
#: docstring that ran to 123 got through review twice.
TRANCHE_MODULES = (
    "_sync_gate.py",
    "_sync_cursor.py",
    "_pg_row_guard.py",
    "sync-to-postgres.py",
    "sync-sessions-to-postgres.py",
    "index-session-content.py",
)


@pytest.mark.parametrize("module_name", TRANCHE_MODULES)
def test_the_tranche_stays_within_a_hundred_columns(module_name):
    """The mutation this kills: a re-wrapped docstring drifting back."""
    source = (SCRIPTS_DIR / module_name).read_text(encoding="utf-8")
    long_lines = [
        f"{module_name}:{number}: {len(line)} columns"
        for number, line in enumerate(source.splitlines(), 1)
        if len(line) > 100
    ]
    assert not long_lines, "\n".join(long_lines)


class TestARenderFailureLeavesTheStateIntact:
    """
    The sidecar is the source of truth and the gate file mirrors it, so a
    failed render must leave the problem recorded rather than lost. This
    is the behaviour the write-then-render order exists to protect, in
    the raising direction (eighth re-audit, M3's tie to the ordering).
    """

    def test_the_sidecar_still_holds_the_problem(
        self, tmp_path, monkeypatch, caplog,
    ):
        """
        The mutation this kills: letting a render failure abandon the
        state write, so the problem is neither shown nor remembered.
        """
        gate = tmp_path / "gates" / "g"
        logger = logging.getLogger("test-render-fail")
        real_write = _sync_gate._atomic_write

        def _fail_only_the_render(path, text):
            if path.name.endswith(".state.json"):
                return real_write(path, text)
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(_sync_gate, "_atomic_write", _fail_only_the_render)

        with caplog.at_level(logging.ERROR):
            state = _sync_gate.apply_gate(
                _sync_gate.GateEvent(
                    outcome=_sync_gate.CYCLE_DEGRADED,
                    fault_detail="the schema is wrong",
                    script="test",
                ),
                gate_path=gate, logger=logger,
            )

        assert "COULD NOT BE PERSISTED" in caplog.text
        assert _sync_gate.PROBLEM_FAULT in state.problems, (
            "a failed render lost the problem the run had found"
        )

        # And the next run's render repairs the mirror from the sidecar.
        monkeypatch.setattr(_sync_gate, "_atomic_write", real_write)
        _sync_gate.render_gate(
            gate, _sync_gate.read_state(gate, logger), logger,
        )
        assert "the schema is wrong" in gate.read_text(encoding="utf-8")


class TestTheCursorGoingBackwardsIsARebuild:
    """
    Ninth re-audit, C2 — exit 6 is raised only when a rebuild lands while
    a sync is in flight. Run the rebuild on a quiet machine and nothing
    is raised at all, so the gate detects it by watching the cursor
    across the gap BETWEEN runs.
    """

    @pytest.mark.parametrize("recorded,current,expected", [
        (None, None, False),      # nothing recorded yet
        (None, 5, False),         # first run to report
        (5, 5, False),            # standing still
        (5, 9, False),            # ordinary progress
        (5, None, True),          # the key was removed
        (9, 3, True),             # rewound
        ("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", False),
        ("2026-09-02T00:00:00Z", "2026-09-01T00:00:00Z", True),
        ("2026-09-02T00:00:00Z", None, True),
        (5, "2026-09-01T00:00:00Z", False),   # a shape change, not a rewind
    ])
    def test_the_predicate(self, recorded, current, expected):
        """The mutation this kills: any arm of the comparison."""
        assert _sync_gate.cursor_went_backwards(recorded, current) is expected

    def _state_file(self, gate: Path) -> dict:
        import json

        path = gate.with_name(gate.name + ".state.json")
        return json.loads(path.read_text(encoding="utf-8"))

    def _apply(self, gate: Path, **kwargs):
        return _sync_gate.apply_gate(
            _sync_gate.GateEvent(script="test", **kwargs),
            gate_path=gate, logger=logging.getLogger("test-cursor"),
        )

    def test_the_recorded_position_is_where_the_run_left_it(self, tmp_path):
        """
        The state stores the END position, because the next run's START
        is what it must be compared with. The mutation this kills:
        recording the starting position, which compares a run with itself
        and never sees the gap a rebuild happens in.
        """
        gate = tmp_path / "g"
        self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=2, cursor_seen=True,
            cursor_position=0, cursor_position_after=7,
        )
        assert self._state_file(gate)["cursor_position"] == 7

    def test_a_vanished_key_resets_the_acknowledged_position(self, tmp_path):
        """
        The end-to-end case in one transition: two rows acknowledged, the
        cursor key removed, the same two rows re-offered. The mutation
        this kills: relying on ``reset_quarantine_ack`` alone.
        """
        gate = tmp_path / "g"
        self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=2, cursor_seen=True,
            cursor_position=None, cursor_position_after=2,
        )
        self._apply(gate, outcome=_sync_gate.CYCLE_ACK, quarantine_entries=2)
        assert self._state_file(gate)["acked"]["acked_position"] == 2

        state = self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, quarantine_entries=2, cursor_seen=True,
            cursor_position=None, cursor_position_after=2,
        )

        assert state.problems[_sync_gate.PROBLEM_QUARANTINE].count == 2
        assert "cursor was reset" in state.problems[
            _sync_gate.PROBLEM_QUARANTINE
        ].detail
        assert self._state_file(gate)["acked"]["acked_position"] == 0

    def test_an_event_that_never_looked_keeps_the_recorded_position(
        self, tmp_path,
    ):
        """
        The indexer shares this state machine and has no cursor at all.
        The mutation this kills: recording the event's position
        unconditionally, which lets a cursorless run erase what the sync
        recorded and blind the next comparison.
        """
        gate = tmp_path / "g"
        self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=2, cursor_seen=True,
            cursor_position=0, cursor_position_after=7,
        )
        self._apply(
            gate, outcome=_sync_gate.CYCLE_COMPLETED, connected=True,
            processed=1, refusals=0,
        )
        assert self._state_file(gate)["cursor_position"] == 7
