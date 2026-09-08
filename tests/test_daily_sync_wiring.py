"""
Wiring tests for scripts/daily-sync.sh — things the shell script must invoke.

daily-sync.sh cannot be run in a test (it pushes to GitHub), so these tests
read its source and pin the calls that other components rely on. Added after
the 2026-09-08 audit (Lens B, finding M3).
"""

import json
import os
import subprocess
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
