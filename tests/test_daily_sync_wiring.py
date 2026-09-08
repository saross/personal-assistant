"""
Wiring tests for ``scripts/daily-sync.sh`` — what the script must invoke.

Originally these read the script's *source* and matched substrings within
a byte window of the call, on the premise that daily-sync.sh could not be
run in a test. A re-audit found the window test would still pass with the
call commented out, and ``daily_sync_harness`` now provides a world the
script can genuinely run in — so these assert the consequence instead:
whether the archiver process actually ran, how often, with which flags,
and what happens when it fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from daily_sync_harness import build_world, SyncWorld
import json
import os
import subprocess
import time

ARCHIVER = "archive-agent-mail.py"


@pytest.fixture()
def world(tmp_path: Path) -> SyncWorld:
    """A seeded two-remote world with no machines yet."""
    return build_world(tmp_path)


class TestAgentMailArchiverWiring:
    """``daily-sync.sh`` runs the agent-mail archiver once per sync, with
    ``--commit --quiet``, early enough that the commit it makes is pushed
    by the same run — and a failure there is a warning, never fatal."""

    def test_archiver_runs_once_with_commit_and_quiet(self, world: SyncWorld) -> None:
        """Exactly one invocation, with the flags the archiver needs."""
        machine = world.add_machine("a")
        assert world.run_sync(machine).returncode == 0
        assert world.calls_to(ARCHIVER) == [f"{ARCHIVER} --commit --quiet"]

    def test_dry_run_does_not_invoke_the_archiver(self, world: SyncWorld) -> None:
        """Audit S9: ``--dry-run`` promises no changes, and the archiver
        commits — so a dry run must not reach it at all."""
        machine = world.add_machine("a")
        result = world.run_sync(machine, "--dry-run")
        assert result.returncode == 0, result.stdout + result.stderr
        assert world.calls_to(ARCHIVER) == []

    def test_archiver_commit_is_published_by_the_same_run(
        self, world: SyncWorld
    ) -> None:
        """The archiver's commit must reach origin, as its comment claims."""
        machine = world.add_machine("a")
        result = world.run_sync(machine, PA_TEST_ARCHIVER_COMMIT="mail-record-1")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "mail-record-1" in world.published_data_file("agent-mail/index.jsonl")

    def test_archiver_failure_warns_and_the_sync_continues(
        self, world: SyncWorld
    ) -> None:
        """Mail is still on disk, so a failure here must never be fatal."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-wiring")
        result = world.run_sync(machine, PA_TEST_ARCHIVER_RC="3")
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "WARNING: agent-mail archive failed" in combined
        assert "=== daily-sync complete" in combined
        # The rest of the sync still happened.
        assert world.published_data_head() == machine.head("data")


ROOT = Path(__file__).resolve().parent.parent


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
                 sidecar_age=None, archive_root=True):
    """Write pipeline gate files, optionally aged (in minutes).

    ``sidecar_age`` writes the ``.state.json`` sidecar beside each gate
    with its own age, so the "the run saved state but could not render"
    case can be described separately from the gate's own mtime.

    ``archive_root`` creates an empty ``~/cc-archives``. Without one the
    hook-gate liveness check cannot run and says so, which is right but
    is not what most of these tests are about.
    """
    if archive_root:
        (tmp_path / "cc-archives").mkdir(exist_ok=True)
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

        Forty minutes up, well past the grace: reported. The mutation
        this kills: skipping staleness whenever uptime is below the
        window.
        """
        _write_gates(tmp_path, age_minutes=21 * 24 * 60)

        result = _run_gate_block(tmp_path, uptime_seconds=40 * 60)

        assert "since this machine booted" in result.stdout
        assert "postgres-sync-memories" in result.stdout

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

    def test_a_gate_older_than_the_boot_waits_only_for_the_grace(
        self, tmp_path,
    ):
        """
        Tenth re-audit, M2 — the grace was inert: a gate older than the
        boot was judged by its age SINCE BOOT against the thirty-minute
        window, which is the same test as the uptime one it followed. A
        gate that predates the boot means cron has not run at all since
        the machine came up, and after the grace that is the whole story.

        Twelve minutes up against a ten-minute grace: reported. The
        mutation this kills: measuring a pre-boot gate against the stale
        window.
        """
        _write_gates(tmp_path, age_minutes=21 * 24 * 60)

        result = _run_gate_block(tmp_path, uptime_seconds=12 * 60)

        assert "since this machine booted" in result.stdout
        assert "12m" in result.stdout

    def test_five_minutes_after_boot_is_still_silent(self, tmp_path):
        """Inside the grace, cron has not had its turn."""
        _write_gates(tmp_path, age_minutes=21 * 24 * 60)

        result = _run_gate_block(tmp_path, uptime_seconds=5 * 60)

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

    def test_a_missing_archive_root_says_the_check_is_off(self, tmp_path):
        """
        Tenth re-audit, M4 — with no archive tree the liveness check
        cannot run, and it used to print nothing at all. A check that
        cannot run is not a clean bill of health: a mistyped
        PA_CC_ARCHIVES turned into permanent silence about two of the
        three gates.

        The mutation this kills: dropping the else-branch that says so.
        """
        _write_gates(
            tmp_path, age_minutes=30 * 24 * 60, names=HOOK_GATES,
            archive_root=False,
        )
        (tmp_path / ".cache" / CRON_GATE).write_text("0\n", encoding="utf-8")

        result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

        assert "liveness checking" in result.stdout
        assert "is OFF" in result.stdout
        assert str(tmp_path / "cc-archives") in result.stdout
        # Said once, not once per gate that would have used it.
        assert result.stdout.count("liveness checking") == 1
        # And it is not an accusation against the hooks themselves.
        assert "the session hooks are not running" not in result.stdout

    def test_a_mistyped_root_says_the_check_is_off(self, tmp_path):
        """The same for a path that was set and is wrong."""
        _write_gates(tmp_path, age_minutes=60, archive_root=False)

        result = _run_gate_block(
            tmp_path, uptime_seconds=48 * 3600,
            PA_CC_ARCHIVES=str(tmp_path / "cc-archves"),
        )

        assert "liveness checking" in result.stdout
        assert "cc-archves" in result.stdout

    def test_a_symlinked_archive_root_is_followed(self, tmp_path):
        """
        Tenth re-audit, M3 — ``find`` defaults to -P, which does not
        follow a symlink named on the command line: it matches nothing
        under a symlinked root and reports every hook healthy for ever.
        The mutation this kills: dropping ``-H``.
        """
        _write_gates(tmp_path, age_minutes=120, archive_root=False)
        real = tmp_path / "archives-elsewhere"
        session = real / "proj" / "2026-09-01T10-00_abc"
        session.mkdir(parents=True)
        meta = session / "session.meta.json"
        meta.write_text("{}", encoding="utf-8")
        stamp = time.time() - 30 * 60
        os.utime(meta, (stamp, stamp))
        (tmp_path / "cc-archives").symlink_to(real, target_is_directory=True)

        result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

        assert "the session hooks are not running" in result.stdout
        assert "liveness checking" not in result.stdout


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


def test_the_stale_window_is_exactly_thirty_minutes(tmp_path):
    """
    Pinned at the boundary, so a default that drifts in either direction
    fails. The mutation this kills: 30 → anything else.
    """
    _write_gates(tmp_path, age_minutes=30)
    silent = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)
    assert "has not been written" not in silent.stdout, (
        "a gate exactly at the window was called late"
    )

    _write_gates(tmp_path, age_minutes=31)
    loud = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)
    assert "has not been written for 31m" in loud.stdout


def test_the_boot_grace_is_exactly_ten_minutes(tmp_path):
    """
    A gate older than the boot waits out the grace and no longer. The
    mutation this kills: 10 → anything else.
    """
    _write_gates(tmp_path, age_minutes=21 * 24 * 60)

    silent = _run_gate_block(tmp_path, uptime_seconds=10 * 60)
    assert silent.stdout.strip() == "", (
        "reported before the grace had elapsed"
    )

    loud = _run_gate_block(tmp_path, uptime_seconds=11 * 60)
    assert "in the 11m since this machine booted" in loud.stdout


def test_the_hook_lag_allowance_is_exactly_fifteen_minutes(tmp_path):
    """
    A session archived within the allowance of the gate is the ordinary
    sequence. The mutation this kills: 15 → anything else.
    """
    _write_gates(tmp_path, age_minutes=60)

    _archive_session(tmp_path, age_minutes=46)   # 14m newer than the gate
    silent = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)
    assert "the session hooks are not running" not in silent.stdout

    _archive_session(tmp_path, age_minutes=44)   # 16m newer
    loud = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)
    assert "the session hooks are not running" in loud.stdout
    assert "more than 15m after this gate" in loud.stdout


def test_the_shipped_defaults_apply_with_nothing_set(tmp_path):
    """
    The three windows are the behaviour on every machine that has never
    heard of the knobs, and the tests above set none of them — this one
    states that plainly, in one place, so the trio is visible together.
    """
    _write_gates(tmp_path, age_minutes=25)
    assert _run_gate_block(
        tmp_path, uptime_seconds=48 * 3600,
    ).stdout.strip() == ""

    _write_gates(tmp_path, age_minutes=35)
    assert "has not been written for 35m" in _run_gate_block(
        tmp_path, uptime_seconds=48 * 3600,
    ).stdout

    _write_gates(tmp_path, age_minutes=21 * 24 * 60)
    assert _run_gate_block(
        tmp_path, uptime_seconds=8 * 60,
    ).stdout.strip() == ""

    _write_gates(tmp_path, age_minutes=60)
    _archive_session(tmp_path, age_minutes=50)
    assert "the session hooks are not running" not in _run_gate_block(
        tmp_path, uptime_seconds=48 * 3600,
    ).stdout

    _archive_session(tmp_path, age_minutes=40)
    assert "the session hooks are not running" in _run_gate_block(
        tmp_path, uptime_seconds=48 * 3600,
    ).stdout




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
