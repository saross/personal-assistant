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
