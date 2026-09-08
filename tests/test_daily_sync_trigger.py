"""
Tests for ``scripts/daily-sync-trigger.sh`` — the live SessionStart hook.

Audit S7 (Lens B, C3): this script had no tests of any kind, and both of
its contracts were removable with the suite green — making the day check
claim "already ran" (the sync never runs again, ever) and inserting
``exit "$rc"`` before the case (a sync failure breaks the SessionStart
hook chain) both passed.

Each test runs the real script with ``HOME`` and ``SCRIPT_DIR`` pointed
at ``tmp_path``, with a stub ``daily-sync.sh`` that records its
invocation and exits with a chosen code. Nothing here touches the real
``~/.cache`` or runs a real sync.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TRIGGER_SCRIPT = REPO_ROOT / "scripts" / "daily-sync-trigger.sh"

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


@dataclass
class TriggerRig:
    """A sandboxed trigger: pinned HOME, stub sync, recorded invocations."""

    home: Path
    scripts: Path
    ran_marker: Path

    @property
    def lock_file(self) -> Path:
        """The once-per-day lock the trigger maintains."""
        return self.home / ".cache" / "daily-sync-last-run"

    def gate(self, name: str) -> Path:
        """Path to one of the ``~/.cache`` gate files."""
        return self.home / ".cache" / name

    def sync_ran(self) -> bool:
        """Did the stub sync actually get invoked?"""
        return self.ran_marker.exists()

    def run(
        self, sync_rc: int = 0, unset_home: bool = False
    ) -> subprocess.CompletedProcess[str]:
        """Run the trigger with the stub sync exiting ``sync_rc``."""
        env = os.environ.copy()
        env.update({"HOME": str(self.home), "PA_TEST_SYNC_RC": str(sync_rc)})
        if unset_home:
            del env["HOME"]
        return subprocess.run(
            ["bash", str(self.scripts / "daily-sync-trigger.sh")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


@pytest.fixture()
def rig(tmp_path: Path) -> TriggerRig:
    """Build the sandboxed trigger rig."""
    home = tmp_path / "home"
    (home / ".cache").mkdir(parents=True)
    pa = tmp_path / "pa"
    scripts = pa / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "daily-sync-trigger.sh").symlink_to(TRIGGER_SCRIPT)

    ran_marker = tmp_path / "sync-ran"
    stub = scripts / "daily-sync.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "# Stub sync: record the invocation, exit with the chosen code.\n"
        f'printf "x\\n" >> "{ran_marker}"\n'
        'exit "${PA_TEST_SYNC_RC:-0}"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return TriggerRig(home=home, scripts=scripts, ran_marker=ran_marker)


# ============================================================================
# Contract 1 — at most one sync per calendar day, and it does run again
# ============================================================================


class TestOncePerDay:
    """The trigger fires on every session start but syncs at most once a
    day — and must go on syncing on later days."""

    def test_first_session_runs_the_sync_and_stamps_the_lock(
        self, rig: TriggerRig
    ) -> None:
        """The dominant first-of-day path."""
        result = rig.run()
        assert result.returncode == 0, result.stderr
        assert rig.sync_ran()
        assert rig.lock_file.read_text().strip() == TODAY

    def test_second_session_the_same_day_does_not_sync(self, rig: TriggerRig) -> None:
        """The dominant every-other-session path stays silent and cheap."""
        assert rig.run().returncode == 0
        rig.ran_marker.unlink()
        result = rig.run()
        assert result.returncode == 0
        assert not rig.sync_ran()

    def test_a_stale_lock_syncs_again(self, rig: TriggerRig) -> None:
        """Kills DST-M1: pinning the day check to "already ran" would stop
        the sync running ever again, with the suite green."""
        rig.lock_file.write_text(YESTERDAY + "\n", encoding="utf-8")
        result = rig.run()
        assert result.returncode == 0
        assert rig.sync_ran()
        assert rig.lock_file.read_text().strip() == TODAY


# ============================================================================
# Contract 2 — always exit 0, so the hook chain survives
# ============================================================================


class TestAlwaysExitsZero:
    """A sync failure must not break the SessionStart hook chain or block
    the session; it must also leave the lock unset so the next session
    retries."""

    @pytest.mark.parametrize("rc", [1, 2, 3, 4])
    def test_sync_failure_still_exits_zero(self, rig: TriggerRig, rc: int) -> None:
        """Kills DST-M2: an ``exit "$rc"`` before the case would break the
        chain on exactly the days the sync is broken."""
        result = rig.run(sync_rc=rc)
        assert result.returncode == 0, result.stderr
        assert not rig.lock_file.exists(), "a failed sync must not stamp the lock"

    def test_unset_home_does_not_break_the_hook_chain(self, rig: TriggerRig) -> None:
        """Audit L4: under `set -u` a bare ${HOME} aborted with status 1 —
        the exact failure the always-exit-0 contract exists to prevent —
        in any environment that does not export HOME (a systemd unit, a
        bare cron, `env -i`)."""
        result = rig.run(unset_home=True)
        assert result.returncode == 0, (
            f"trigger exited {result.returncode} with HOME unset\n{result.stderr}"
        )

    def test_lock_contention_is_reported_as_such(self, rig: TriggerRig) -> None:
        """Exit 1 is benign contention, not a broken sync."""
        result = rig.run(sync_rc=1)
        assert "lock contention" in result.stderr

    def test_genuine_failure_names_the_exit_code(self, rig: TriggerRig) -> None:
        """Exit 2/3/4 must be distinguishable from contention."""
        result = rig.run(sync_rc=3)
        assert "sync failed (exit 3)" in result.stderr
        assert "lock contention" not in result.stderr


# ============================================================================
# Infra gates — rendered to STDOUT, where the session can see them
# ============================================================================


class TestGateRendering:
    """Gate output goes to stdout deliberately: SessionStart stderr never
    reaches the session context, and a signal that is emitted but not
    surfaced is indistinguishable from no signal."""

    def _add_syncthing_check(self, rig: TriggerRig) -> None:
        """Install a do-nothing health check so the gate block is entered."""
        check = rig.scripts / "syncthing-health.sh"
        check.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        check.chmod(0o755)

    def test_zero_count_gate_prints_nothing(self, rig: TriggerRig) -> None:
        """A clean gate must stay silent."""
        rig.gate("memory-drift-gate").write_text("0\n", encoding="utf-8")
        result = rig.run()
        assert "Infra gates" not in result.stdout

    def test_memory_drift_gate_is_surfaced(self, rig: TriggerRig) -> None:
        """A non-zero count reaches stdout with its detail line."""
        rig.gate("memory-drift-gate").write_text(
            "1\nrecords survive in only ONE store\n", encoding="utf-8"
        )
        result = rig.run()
        assert "Infra gates" in result.stdout
        assert "records survive in only ONE store" in result.stdout

    def test_daily_sync_gate_is_surfaced(self, rig: TriggerRig) -> None:
        """Audit S3/S17: a wedged sync must be visible at session start."""
        rig.gate("daily-sync-gate").write_text(
            "1\ndaily-sync STOPPED: stash pop conflicted on tasks/inbox.md\n",
            encoding="utf-8",
        )
        result = rig.run()
        assert "[daily-sync gate]" in result.stdout
        assert "stash pop conflicted on tasks/inbox.md" in result.stdout

    def test_syncthing_gate_normal_layout(self, rig: TriggerRig) -> None:
        """count, `checked …`, then the problems."""
        self._add_syncthing_check(rig)
        rig.gate("syncthing-gate").write_text(
            "2\nchecked 2026-09-08 10:04:20 on AMD-tower-ubuntu\n"
            "folder personal-docs is out of sync\n"
            "peer zbook last seen 9 days ago\n",
            encoding="utf-8",
        )
        result = rig.run()
        assert "folder personal-docs is out of sync" in result.stdout
        assert "peer zbook last seen 9 days ago" in result.stdout
        assert "checked 2026-09-08" not in result.stdout

    def test_a_problem_line_beginning_checked_is_not_swallowed(
        self, rig: TriggerRig
    ) -> None:
        """Audit L4: only the gate's own `checked <date> <time> on <host>`
        header may be skipped. A glob on `checked *` would swallow a real
        problem line that happens to start with the word."""
        self._add_syncthing_check(rig)
        rig.gate("syncthing-gate").write_text(
            "1\nchecked folder personal-docs by hand — still out of sync\n",
            encoding="utf-8",
        )
        result = rig.run()
        assert "checked folder personal-docs by hand" in result.stdout

    def test_syncthing_gate_early_exit_layout(self, rig: TriggerRig) -> None:
        """Audit S10: count then problems, with no `checked` line — the
        layout syncthing-health.sh writes when its expectations file is
        missing. The old ``tail -n +3`` printed the header alone."""
        self._add_syncthing_check(rig)
        rig.gate("syncthing-gate").write_text(
            "1\nexpectations file missing: ~/.config/syncthing-expectations.json\n",
            encoding="utf-8",
        )
        result = rig.run()
        assert "[syncthing gate] 1 problem(s)" in result.stdout
        assert "expectations file missing" in result.stdout, (
            "the only detail line was swallowed; the header stands alone"
        )
