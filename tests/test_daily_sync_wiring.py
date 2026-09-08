"""
Wiring tests for scripts/daily-sync.sh — things the shell script must invoke.

daily-sync.sh cannot be run in a test (it pushes to GitHub), so these tests
read its source and pin the calls that other components rely on. Added after
the 2026-09-08 audit (Lens B, finding M3).
"""

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


def test_session_hooks_run_the_indexer_even_if_the_sync_fails():
    """
    The PreCompact and SessionEnd chains used ``&&`` between the sessions
    sync and the content indexer, so the sync's new non-zero exits (4 and
    6) would silently stop the indexer from ever running. The sync's own
    exit code is still echoed to stderr.
    """
    import json

    settings = json.loads(SETTINGS_TEMPLATE.read_text(encoding="utf-8"))
    chains = [
        hook["command"]
        for event in ("PreCompact", "SessionEnd")
        for group in settings["hooks"][event]
        for hook in group["hooks"]
        if "sync-sessions-to-postgres.py" in hook["command"]
    ]
    assert len(chains) == 2, "expected one chain per session-close event"
    for command in chains:
        sync_at = command.index("sync-sessions-to-postgres.py")
        index_at = command.index("index-session-content.py")
        between = command[sync_at:index_at]
        assert "&&" not in between, (
            "the indexer is still chained behind the sync with &&, so a "
            "sync exit of 4 or 6 stops it running"
        )
        assert ";" in between
        assert "exited $?" in between, "the sync's exit code is not logged"
