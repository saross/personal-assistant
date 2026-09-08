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
    start = source.index("PG_GATE_STALE_HOURS=")
    end = source.index("unset _pg_gate_name", start)
    return source[start:end]


def _run_gate_block(tmp_path, stale_hours="6", uptime_seconds=None):
    """Run the extracted block with HOME pinned; return its stdout.

    ``uptime_seconds`` writes a stand-in ``/proc/uptime`` and points the
    block at it, so the boot-time guard can be exercised without waiting
    for a reboot.
    """
    script = tmp_path / "gate-block.sh"
    script.write_text(
        "GATE_LINES=()\n" + _gate_block(TRIGGER.read_text(encoding="utf-8"))
        + '\nprintf "%s\\n" "${GATE_LINES[@]}"\n',
        encoding="utf-8",
    )
    env = {
        "HOME": str(tmp_path),
        "PATH": os.environ["PATH"],
        "PA_GATE_STALE_HOURS": stale_hours,
    }
    if uptime_seconds is not None:
        uptime_file = tmp_path / "fake-uptime"
        uptime_file.write_text(
            f"{uptime_seconds}.00 {uptime_seconds}.00\n", encoding="utf-8",
        )
        env["PA_UPTIME_FILE"] = str(uptime_file)
    return subprocess.run(
        ["bash", str(script)],
        capture_output=True, text=True,
        env=env,
    )


def _write_gates(tmp_path, age_hours=0.0, names=None, sidecar_age=None):
    """Write the three pipeline gate files, optionally aged.

    ``sidecar_age`` writes the ``.state.json`` sidecar beside each gate
    with its own age, so the "the run saved state but could not render"
    case can be described separately from the gate's own mtime.
    """
    cache = tmp_path / ".cache"
    cache.mkdir(exist_ok=True)
    names = names or (
        "postgres-sync-memories-gate",
        "postgres-sync-sessions-gate",
        "index-session-content-gate",
    )
    for name in names:
        gate = cache / name
        gate.write_text("0\n", encoding="utf-8")
        stamp = time.time() - age_hours * 3600
        os.utime(gate, (stamp, stamp))
        if sidecar_age is not None:
            sidecar = cache / f"{name}.state.json"
            sidecar.write_text("{}", encoding="utf-8")
            side_stamp = time.time() - sidecar_age * 3600
            os.utime(sidecar, (side_stamp, side_stamp))
    return cache


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
    assert "postgres-sync-memories" in result.stdout
    assert "postgres-sync-sessions" in result.stdout
    assert "index-session-content" in result.stdout


def test_a_stale_gate_is_reported(tmp_path):
    """
    A clean gate that stopped being refreshed means a dead cron entry or
    a broken hook chain. The mutation this kills: dropping the mtime
    check.
    """
    cache = tmp_path / ".cache"
    cache.mkdir()
    for name in (
        "postgres-sync-memories-gate",
        "postgres-sync-sessions-gate",
        "index-session-content-gate",
    ):
        gate = cache / name
        gate.write_text("0\n", encoding="utf-8")
        # Seven hours old, against a six-hour threshold.
        old = time.time() - 7 * 3600
        os.utime(gate, (old, old))

    result = _run_gate_block(tmp_path)

    assert "has not been updated for over 6h" in result.stdout
    assert result.stdout.count("has not been updated") == 3


def test_a_fresh_clean_gate_says_nothing(tmp_path):
    """The quiet path must stay quiet, or the banner becomes noise."""
    cache = tmp_path / ".cache"
    cache.mkdir()
    for name in (
        "postgres-sync-memories-gate",
        "postgres-sync-sessions-gate",
        "index-session-content-gate",
    ):
        (cache / name).write_text("0\n", encoding="utf-8")

    result = _run_gate_block(tmp_path)

    assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Eighth re-audit, finding C2 — staleness measured against a machine that
# was switched off is three false alarms, not three dead scripts
# ---------------------------------------------------------------------------


def test_old_gates_after_a_fresh_boot_say_nothing(tmp_path):
    """
    The false-alarm case: the machine was off overnight, so every gate is
    hours old and none of the scripts has had a chance to run yet. The
    mutation this kills: dropping the uptime guard, which puts three
    "the script is not running" lines in front of Shawn every morning.
    """
    _write_gates(tmp_path, age_hours=9)

    result = _run_gate_block(tmp_path, uptime_seconds=600)

    assert result.returncode == 0, result.stderr
    assert "has not been updated" not in result.stdout
    assert result.stdout.strip() == ""


def test_old_gates_after_a_long_uptime_are_reported(tmp_path):
    """
    The true case: the machine has been up for two days and the gates
    stopped being refreshed seven hours ago. That is a dead cron entry
    and must still be reported.
    """
    _write_gates(tmp_path, age_hours=7)

    result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

    assert "has not been updated for over 6h" in result.stdout
    assert result.stdout.count("has not been updated") == 3


def test_a_gate_predating_the_boot_names_the_boot(tmp_path):
    """
    Up seven hours, gates eight hours old: the scripts have not run since
    the machine came up, which is worth saying in those words rather than
    as a bare age. The mutation this kills: dropping the boot-epoch
    comparison, which loses the distinction.
    """
    _write_gates(tmp_path, age_hours=8)

    result = _run_gate_block(tmp_path, uptime_seconds=7 * 3600)

    assert "has not been updated since this machine booted 7h ago" in (
        result.stdout
    )
    assert result.stdout.count("since this machine booted") == 3


def test_an_unreadable_uptime_file_still_reports_staleness(tmp_path):
    """
    The guard must fail towards reporting: a machine with no readable
    /proc/uptime keeps the behaviour that existed before it.
    """
    _write_gates(tmp_path, age_hours=9)
    missing = tmp_path / "no-such-uptime"

    script = tmp_path / "gate-block.sh"
    script.write_text(
        "GATE_LINES=()\n" + _gate_block(TRIGGER.read_text(encoding="utf-8"))
        + '\nprintf "%s\\n" "${GATE_LINES[@]}"\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True, text=True,
        env={
            "HOME": str(tmp_path),
            "PATH": os.environ["PATH"],
            "PA_GATE_STALE_HOURS": "6",
            "PA_UPTIME_FILE": str(missing),
        },
    )

    assert "has not been updated for over 6h" in result.stdout


# ---------------------------------------------------------------------------
# Eighth re-audit, finding M6 — PA_GATE_STALE_HOURS reached $(( )) unchecked
# ---------------------------------------------------------------------------


def test_a_non_numeric_stale_hours_falls_back_to_the_default(tmp_path):
    """
    Bash evaluates the contents of $(( )) as an arithmetic EXPRESSION, so
    an array subscript there runs a command substitution out of the
    environment. The mutation this kills: restoring
    ``PG_GATE_STALE_HOURS="${PA_GATE_STALE_HOURS:-6}"`` with no pattern
    check — the marker file then appears.
    """
    _write_gates(tmp_path, age_hours=7)
    marker = tmp_path / "injected"

    result = _run_gate_block(
        tmp_path,
        stale_hours=f"1[$(touch {marker})]",
        uptime_seconds=48 * 3600,
    )

    assert not marker.exists(), (
        "a value from the environment was executed as a command"
    )
    # Fell back to six hours, so the seven-hour-old gates are still stale.
    assert "has not been updated for over 6h" in result.stdout


def test_an_empty_or_zero_stale_hours_falls_back_too(tmp_path):
    """Zero would make every gate stale the instant it is written."""
    _write_gates(tmp_path, age_hours=1)

    for value in ("", "0", "-3", "six", "6.5"):
        result = _run_gate_block(
            tmp_path, stale_hours=value, uptime_seconds=48 * 3600,
        )
        assert "has not been updated" not in result.stdout, (
            f"PA_GATE_STALE_HOURS={value!r} was not rejected"
        )


def test_a_valid_override_is_still_honoured(tmp_path):
    """The validation must not amount to ignoring the variable."""
    _write_gates(tmp_path, age_hours=3)

    result = _run_gate_block(
        tmp_path, stale_hours="2", uptime_seconds=48 * 3600,
    )

    assert "has not been updated for over 2h" in result.stdout


# ---------------------------------------------------------------------------
# Eighth re-audit, low — the sidecar is independent evidence that the
# script ran, so staleness must look at it too
# ---------------------------------------------------------------------------


def test_a_fresh_sidecar_keeps_a_stale_gate_quiet(tmp_path):
    """
    The run saved its state but its gate render failed. The script is
    alive; "the script is not running" would send Shawn after the wrong
    thing. The mutation this kills: measuring the gate file alone.
    """
    _write_gates(tmp_path, age_hours=9, sidecar_age=0)

    result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

    assert "has not been updated" not in result.stdout


def test_a_missing_gate_beside_a_live_sidecar_is_reported(tmp_path):
    """
    The mirror of the case above: state is being written and the gate is
    not there at all, so whatever the script found never reaches session
    start. That is its own problem and must be named as such rather than
    reported as a script that has never run.
    """
    cache = tmp_path / ".cache"
    cache.mkdir()
    for name in (
        "postgres-sync-memories-gate",
        "postgres-sync-sessions-gate",
        "index-session-content-gate",
    ):
        (cache / f"{name}.state.json").write_text("{}", encoding="utf-8")

    result = _run_gate_block(tmp_path, uptime_seconds=48 * 3600)

    assert "its gate file is missing" in result.stdout
    assert "has NEVER been written" not in result.stdout
    assert result.stdout.count("its gate file is missing") == 3
