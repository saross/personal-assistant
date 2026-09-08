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
