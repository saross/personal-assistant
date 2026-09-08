"""
Wiring tests for scripts/daily-sync.sh — things the shell script must invoke.

daily-sync.sh cannot be run in a test (it pushes to GitHub), so these tests
read its source and pin the calls that other components rely on. Added after
the 2026-09-08 audit (Lens B, finding M3).
"""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DAILY_SYNC = ROOT / "scripts" / "daily-sync.sh"


def test_daily_sync_runs_the_agent_mail_archiver_before_the_submodule_sync():
    source = DAILY_SYNC.read_text()
    call = source.index("archive-agent-mail.py")
    assert "--commit --quiet" in source[call:call + 200]
    assert call < source.index("# Data submodule sync")
    # Failure must be logged, never fatal.
    assert 'log "WARNING: agent-mail archive failed' in source[call:call + 400]


# ---------------------------------------------------------------------------
# Audit round two, finding C2 — an exit code nobody sees is not a signal
# ---------------------------------------------------------------------------

TRIGGER = ROOT / "scripts" / "daily-sync-trigger.sh"
SETTINGS_TEMPLATE = ROOT / "settings-template.json"


def test_trigger_surfaces_every_postgres_gate():
    """
    The trigger enumerates gate files explicitly, so a gate that is
    written but not listed here is written into silence — the exact
    failure the script's own header warns about three times. Since the
    third re-audit there is one gate per script, and all of them must be
    relayed (finding C1).
    """
    source = TRIGGER.read_text(encoding="utf-8")
    for name in (
        "postgres-sync-memories-gate",
        "postgres-sync-sessions-gate",
        "index-session-content-gate",
    ):
        assert name in source, f"{name} is never relayed"

    block_start = source.index("for _pg_gate_name in")
    block = source[block_start:source.index("unset _pg_gate_name", block_start)]
    # Same shape as the other gates: count on line 1, detail after.
    assert 'head -1 "$_pg_gate_file"' in block
    assert 'tail -n +2 "$_pg_gate_file"' in block
    assert "GATE_LINES+=" in block
    # A single problem must print: the threshold is -gt 0, not -gt 1.
    assert '"$_pg_count" -gt 0' in block
    # And they must be added before the block is printed, not after.
    assert block_start < source.index("Infra gates — RELAY THESE TO SHAWN")


def _fake_pa_root(tmp_path, archive_rc=0, sync_rc=0, index_rc=0):
    """Build a fake ~/personal-assistant whose python3 is a stub.

    Lets the real command string from settings-template.json be executed
    with HOME pinned to tmp_path — no real archive, database, or .env is
    touched, and the shell grouping under test is the shipped one rather
    than a reconstruction of it.
    """
    root = tmp_path / "personal-assistant"
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / ".env").write_text("PA_TEST=1\n", encoding="utf-8")
    for name in ("sync-sessions-to-postgres.py", "index-session-content.py"):
        (root / "scripts" / name).write_text("", encoding="utf-8")

    stub = root / "venv" / "bin" / "python3"
    stub.write_text(
        "#!/bin/bash\n"
        'case "$*" in\n'
        f'  *cc_session_toolkit*) touch "{tmp_path}/archive.ran"; '
        f'exit {archive_rc} ;;\n'
        f'  *sync-sessions-to-postgres.py*) touch "{tmp_path}/sync.ran"; '
        f'exit {sync_rc} ;;\n'
        f'  *index-session-content.py*) touch "{tmp_path}/index.ran"; '
        f'exit {index_rc} ;;\n'
        "esac\nexit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return root


def _run_chain(command, tmp_path):
    """Execute a hook command with HOME pinned to the fake tree."""
    return subprocess.run(
        ["bash", "-c", command],
        capture_output=True, text=True,
        env={"HOME": str(tmp_path), "PATH": os.environ["PATH"]},
    )


def _session_chains():
    """Return the PreCompact and SessionEnd commands from the template."""
    settings = json.loads(SETTINGS_TEMPLATE.read_text(encoding="utf-8"))
    return [
        hook["command"]
        for event in ("PreCompact", "SessionEnd")
        for group in settings["hooks"][event]
        for hook in group["hooks"]
        if "sync-sessions-to-postgres.py" in hook["command"]
    ]


def test_session_hooks_run_the_indexer_even_if_the_sync_fails(tmp_path):
    """
    The chain used ``&&`` between the sessions sync and the content
    indexer, so the sync's non-zero exits (4, 5, 6, 7) would silently stop
    the indexer running at all. Executed, not merely read: the sync exits
    4 and the indexer must still run.
    """
    for index, command in enumerate(_session_chains()):
        run_dir = tmp_path / f"chain{index}"
        run_dir.mkdir()
        _fake_pa_root(run_dir, sync_rc=4)
        result = _run_chain(command, run_dir)

        assert (run_dir / "sync.ran").exists()
        assert (run_dir / "index.ran").exists(), (
            "the indexer did not run after the sync exited 4"
        )
        assert "exited 4" in result.stderr
        assert result.returncode == 0


def test_an_archive_failure_still_fails_the_hook(tmp_path):
    """
    Third re-audit, finding M1: the ``;`` that let the indexer run
    regardless also swallowed an archive failure, because the last
    command in the list set the status. The sync and indexer are now
    grouped behind the archive's ``&&``, so a failed archive stops the
    chain AND the hook exits non-zero. The mutation this kills: dropping
    the outer braces, or the archive's ``&&``.
    """
    for index, command in enumerate(_session_chains()):
        run_dir = tmp_path / f"archive-fail{index}"
        run_dir.mkdir()
        _fake_pa_root(run_dir, archive_rc=1)
        result = _run_chain(command, run_dir)

        assert (run_dir / "archive.ran").exists()
        assert result.returncode != 0, (
            "a failed archive was reported to the hook as success"
        )
        assert not (run_dir / "sync.ran").exists()
        assert not (run_dir / "index.ran").exists()


def test_a_clean_run_exits_zero(tmp_path):
    """The happy path is unchanged by the grouping."""
    for index, command in enumerate(_session_chains()):
        run_dir = tmp_path / f"clean{index}"
        run_dir.mkdir()
        _fake_pa_root(run_dir)
        result = _run_chain(command, run_dir)
        assert result.returncode == 0
        assert (run_dir / "index.ran").exists()


def _gate_block(source: str) -> str:
    """Extract the trigger's postgres-gate loop for execution in a test."""
    start = source.index("_pa_gate_minutes() {")
    end = source.index("unset _pg_gate_name", start)
    return source[start:end]


def _run_gate_block(tmp_path, uptime_seconds=None, **overrides):
    """Run the extracted block with HOME pinned; return the result.

    ``uptime_seconds`` writes a stand-in ``/proc/uptime`` and points the
    block at it, so the boot reference and the post-boot grace can be
    exercised without waiting for a reboot. Any other keyword becomes an
    environment variable, so a test can set a knob or leave it unset.
    """
    script = tmp_path / "gate-block.sh"
    script.write_text(
        "GATE_LINES=()\n" + _gate_block(TRIGGER.read_text(encoding="utf-8"))
        + '\nprintf "%s\\n" "${GATE_LINES[@]}"\n',
        encoding="utf-8",
    )
    env = {"HOME": str(tmp_path), "PATH": os.environ["PATH"]}
    if uptime_seconds is not None:
        uptime_file = tmp_path / "fake-uptime"
        uptime_file.write_text(
            f"{uptime_seconds}.00 {uptime_seconds}.00\n", encoding="utf-8",
        )
        env["PA_UPTIME_FILE"] = str(uptime_file)
    env.update({key: str(value) for key, value in overrides.items()})
    return subprocess.run(
        ["bash", str(script)],
        capture_output=True, text=True,
        env=env,
    )


CRON_GATE = "postgres-sync-memories-gate"
HOOK_GATES = ("postgres-sync-sessions-gate", "index-session-content-gate")
ALL_GATES = (CRON_GATE,) + HOOK_GATES


def _write_gates(tmp_path, age_minutes=0.0, names=ALL_GATES,
                 sidecar_age=None):
    """Write pipeline gate files, optionally aged (in minutes).

    ``sidecar_age`` writes the ``.state.json`` sidecar beside each gate
    with its own age, so the "the run saved state but could not render"
    case can be described separately from the gate's own mtime.
    """
    cache = tmp_path / ".cache"
    cache.mkdir(exist_ok=True)
    for name in names:
        gate = cache / name
        gate.write_text("0\n", encoding="utf-8")
        stamp = time.time() - age_minutes * 60
        os.utime(gate, (stamp, stamp))
        if sidecar_age is not None:
            sidecar = cache / f"{name}.state.json"
            sidecar.write_text("{}", encoding="utf-8")
            side_stamp = time.time() - sidecar_age * 60
            os.utime(sidecar, (side_stamp, side_stamp))
    return cache


def _archive_session(tmp_path, age_minutes=0.0):
    """Put one archived session under ~/cc-archives with a given age."""
    session = tmp_path / "cc-archives" / "proj" / "2026-09-01T10-00_abc"
    session.mkdir(parents=True, exist_ok=True)
    meta = session / "session.meta.json"
    meta.write_text("{}", encoding="utf-8")
    stamp = time.time() - age_minutes * 60
    os.utime(meta, (stamp, stamp))
    return meta


def test_a_gate_that_was_never_written_is_reported(tmp_path):
    """
    Seventh re-audit, M6: a script that never runs writes no gate, and a
    gate that is absent used to be skipped silently — the one failure a
    gate cannot report about itself. The mutation this kills: restoring
    the `[[ -f ... ]] || continue` skip.
    """
    (tmp_path / ".cache").mkdir()
    result = _run_gate_block(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "has NEVER been written" in result.stdout
    for name in ALL_GATES:
        assert name.removesuffix("-gate") in result.stdout


def test_a_fresh_clean_gate_says_nothing(tmp_path):
    """The quiet path must stay quiet, or the banner becomes noise."""
    _write_gates(tmp_path)
    result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)
    assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Ninth re-audit, finding M4 — the cron gate and the hook gates fail in
# different ways, and one wall-clock rule described neither
# ---------------------------------------------------------------------------


class TestTheCronWrittenGate:
    """
    postgres-sync-memories-gate is refreshed every five minutes by cron.
    Silence IS the signal — but only silence the machine was awake for.
    """

    def test_an_old_gate_after_a_long_uptime_is_reported(self, tmp_path):
        """Two hours of silence from a five-minute job is a dead cron."""
        _write_gates(tmp_path, age_minutes=120)

        result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

        assert "postgres-sync-memories gate] has not been written" in (
            result.stdout
        )
        assert "Check the cron entry" in result.stdout

    def test_a_three_week_old_gate_is_reported_soon_after_boot(
        self, tmp_path,
    ):
        """
        Ninth re-audit, M4 — the uptime amnesty was checked before the
        boot arm, so a three-week-old gate went unreported for the first
        six hours after every boot: exactly the window in which someone
        is sitting at the machine and could fix it.

        Forty minutes up, against a ten-minute grace and a thirty-minute
        window: the reference is the boot, the age is forty minutes, and
        it is reported. The mutation this kills: skipping staleness
        whenever uptime is below the window.
        """
        _write_gates(tmp_path, age_minutes=21 * 24 * 60)

        result = _run_gate_block(tmp_path, uptime_seconds=40 * 60)

        assert "since this machine booted" in result.stdout
        assert "postgres-sync-memories" in result.stdout

    def test_the_first_minutes_after_boot_are_silent(self, tmp_path):
        """
        Cron has not had its turn yet, and reporting a dead sync on every
        boot is how a gate becomes something people scroll past.
        """
        _write_gates(tmp_path, age_minutes=21 * 24 * 60)

        result = _run_gate_block(tmp_path, uptime_seconds=4 * 60)

        assert "postgres-sync-memories" not in result.stdout

    def test_a_gate_written_since_boot_is_measured_from_itself(
        self, tmp_path,
    ):
        """
        Up for two days, gate written five minutes ago: nothing to say.
        The mutation this kills: always measuring from the boot.
        """
        _write_gates(tmp_path, age_minutes=5)

        result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

        assert result.stdout.strip() == ""

    def test_an_unreadable_uptime_falls_back_to_wall_clock_age(
        self, tmp_path,
    ):
        """The guard must fail towards reporting, not towards silence."""
        _write_gates(tmp_path, age_minutes=120)

        result = _run_gate_block(
            tmp_path, PA_UPTIME_FILE=str(tmp_path / "no-such-file"),
        )

        assert "postgres-sync-memories gate] has not been written" in (
            result.stdout
        )

    def test_the_window_can_be_overridden(self, tmp_path):
        """The escape hatch must survive the validation."""
        _write_gates(tmp_path, age_minutes=20)

        quiet = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)
        loud = _run_gate_block(
            tmp_path, uptime_seconds=48 * 3600, PA_GATE_STALE_MINUTES="10",
        )

        assert "postgres-sync-memories" not in quiet.stdout
        assert "postgres-sync-memories gate] has not been written" in (
            loud.stdout
        )


class TestTheHookWrittenGates:
    """
    The sessions sync and the content indexer run from session hooks. A
    fortnight away from the machine, or one very long session, leaves
    their gates untouched and nothing is wrong — so wall-clock age is not
    evidence about them at all. Only a session that ENDED without the
    hook running is.
    """

    def test_an_ancient_gate_alone_says_nothing(self, tmp_path):
        """
        The mutation this kills: applying the cron rule to these gates —
        every holiday then comes back to two dead-script warnings.
        """
        _write_gates(tmp_path, age_minutes=30 * 24 * 60)
        # No archived session at all: nothing has ended.

        result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

        for name in HOOK_GATES:
            assert name.removesuffix("-gate") + " gate] a session" not in (
                result.stdout
            )
        assert "the session hooks are not running" not in result.stdout

    def test_a_session_archived_after_the_gate_is_reported(self, tmp_path):
        """
        A session ended, its metadata was written, and the gate was not
        touched. That is a hook that did not run, whatever the clock says.
        """
        _write_gates(tmp_path, age_minutes=120)
        _archive_session(tmp_path, age_minutes=30)

        result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

        assert "the session hooks are not running" in result.stdout
        assert "postgres-sync-sessions" in result.stdout
        assert "index-session-content" in result.stdout

    def test_a_session_archived_just_before_the_gate_is_not(self, tmp_path):
        """
        The ordinary sequence: the session ends, the hook runs, the gate
        is written a moment later. The mutation this kills: comparing
        without the lag allowance, which reports every healthy session.
        """
        _write_gates(tmp_path, age_minutes=10)
        _archive_session(tmp_path, age_minutes=11)

        result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

        assert "the session hooks are not running" not in result.stdout

    def test_a_session_inside_the_lag_allowance_is_not_reported(
        self, tmp_path,
    ):
        """
        The hook chain takes time — archive, sync, index. A gate written
        a few minutes after the metadata is the normal case.
        """
        _write_gates(tmp_path, age_minutes=60)
        _archive_session(tmp_path, age_minutes=50)

        result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

        assert "the session hooks are not running" not in result.stdout

    def test_the_lag_allowance_can_be_overridden(self, tmp_path):
        """The escape hatch must survive the validation here too."""
        _write_gates(tmp_path, age_minutes=60)
        _archive_session(tmp_path, age_minutes=50)

        result = _run_gate_block(
            tmp_path, uptime_seconds=48 * 3600, PA_HOOK_GATE_LAG_MINUTES="5",
        )

        assert "the session hooks are not running" in result.stdout

    def test_a_missing_archive_root_is_not_an_accusation(self, tmp_path):
        """
        A machine with no archive tree yet has no evidence either way.
        The mutation this kills: reporting when the root is absent.
        """
        _write_gates(tmp_path, age_minutes=30 * 24 * 60, names=HOOK_GATES)
        # The cron gate is deliberately absent here, so the only thing
        # that could speak is the hook rule.
        (tmp_path / ".cache" / CRON_GATE).write_text("0\n", encoding="utf-8")

        result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

        assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Eighth re-audit, finding M6 — the knobs reach $(( )), so they are checked
# ---------------------------------------------------------------------------


class TestTheStalenessKnobsAreValidated:
    """
    Bash evaluates the contents of $(( )) as an arithmetic EXPRESSION, so
    an array subscript there runs a command substitution out of the
    environment.
    """

    KNOBS = (
        "PA_GATE_STALE_MINUTES",
        "PA_GATE_BOOT_GRACE_MINUTES",
        "PA_HOOK_GATE_LAG_MINUTES",
    )

    @pytest.mark.parametrize("knob", KNOBS)
    def test_a_value_from_the_environment_is_never_executed(
        self, tmp_path, knob,
    ):
        """
        The mutation this kills: taking any of these straight from the
        environment with no pattern check — the marker file then appears.
        """
        _write_gates(tmp_path, age_minutes=120)
        marker = tmp_path / f"injected-{knob}"

        result = _run_gate_block(
            tmp_path, uptime_seconds=48 * 3600,
            **{knob: f"1[$(touch {marker})]"},
        )

        assert not marker.exists(), (
            f"{knob} was executed as a command"
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("knob", KNOBS)
    @pytest.mark.parametrize("value", ["", "0", "-3", "thirty", "6.5"])
    def test_a_nonsense_value_falls_back_to_the_default(
        self, tmp_path, knob, value,
    ):
        """A rejected value must leave the shipped behaviour in place."""
        _write_gates(tmp_path, age_minutes=120)

        result = _run_gate_block(
            tmp_path, uptime_seconds=48 * 3600, **{knob: value},
        )

        assert "postgres-sync-memories gate] has not been written" in (
            result.stdout
        ), f"{knob}={value!r} changed the shipped behaviour"


def test_the_shipped_defaults_apply_with_nothing_set(tmp_path):
    """
    The thirty-minute window, the ten-minute grace, and the
    fifteen-minute lag are the behaviour on every machine that has never
    heard of the knobs, and every other test here sets at least one. The
    mutation this kills: changing any shipped default.
    """
    # Twenty-five minutes is inside the window; thirty-five is not.
    _write_gates(tmp_path, age_minutes=25)
    quiet = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)
    assert quiet.stdout.strip() == ""

    _write_gates(tmp_path, age_minutes=35)
    loud = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)
    assert "postgres-sync-memories gate] has not been written" in loud.stdout

    # Eight minutes of uptime is inside the grace; twelve is not.
    _write_gates(tmp_path, age_minutes=21 * 24 * 60)
    early = _run_gate_block(tmp_path, uptime_seconds=8 * 60)
    assert early.stdout.strip() == ""

    # A session archived ten minutes after the gate is inside the lag;
    # twenty is not.
    _write_gates(tmp_path, age_minutes=60)
    _archive_session(tmp_path, age_minutes=50)
    inside = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)
    assert "the session hooks are not running" not in inside.stdout

    _archive_session(tmp_path, age_minutes=40)
    outside = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)
    assert "the session hooks are not running" in outside.stdout


# ---------------------------------------------------------------------------
# Eighth re-audit, low — the sidecar is independent evidence the script ran
# ---------------------------------------------------------------------------


def test_a_fresh_sidecar_keeps_a_stale_gate_quiet(tmp_path):
    """
    The run saved its state but its gate render failed. The script is
    alive; "it is not running" would send Shawn after the wrong thing.
    The mutation this kills: measuring the gate file alone.
    """
    _write_gates(tmp_path, age_minutes=120, sidecar_age=0)

    result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

    assert "has not been written" not in result.stdout


def test_a_missing_gate_beside_a_live_sidecar_is_reported(tmp_path):
    """
    The mirror of the case above: state is being written and the gate is
    not there at all, so whatever the script found never reaches session
    start. That is its own problem and must be named as such rather than
    reported as a script that has never run.
    """
    cache = tmp_path / ".cache"
    cache.mkdir()
    for name in ALL_GATES:
        (cache / f"{name}.state.json").write_text("{}", encoding="utf-8")

    result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

    assert "its gate file is missing" in result.stdout
    assert "has NEVER been written" not in result.stdout
    assert result.stdout.count("its gate file is missing") == 3


def test_the_two_guards_that_no_behaviour_can_distinguish():
    """
    Two guards in the staleness block are, on this design, equivalent to
    their absence — and are kept anyway, so they are pinned here rather
    than left to rot.

    The post-boot grace is compared against its OWN threshold, not the
    staleness window. With the reference taken as the later of the boot
    and the gate's mtime, the age of a boot-referenced gate IS the
    uptime, so a grace below the window can never change a verdict; it
    bites only if the two are ever set the other way round, or if a clock
    jump makes the boot look older than it is. Swapping the threshold is
    therefore invisible to any test that runs, and that is exactly the
    kind of change worth catching before it becomes load-bearing.

    The archive-root existence check is the same shape: ``find`` on a
    path that is not there prints nothing and its complaint is already
    discarded, so removing the check changes no output — it just runs a
    walk of nothing on every session start and leaves the intent
    unstated.
    """
    source = TRIGGER.read_text(encoding="utf-8")
    block = _gate_block(source)

    assert "PG_UPTIME_SECONDS < PG_BOOT_GRACE_MINUTES * 60" in block, (
        "the post-boot grace is measured against the wrong threshold"
    )
    root_check = block.index('if [[ -d "$PG_ARCHIVE_ROOT" ]]; then')
    find_call = block.index('find "$PG_ARCHIVE_ROOT"')
    assert root_check < find_call, (
        "the archive tree is walked without checking it is there"
    )
