"""
Behavioural tests for ``scripts/daily-sync.sh``.

Audit 2026-09-08 (Lens B, C1) found the script had no behavioural test:
its one end-to-end fixture died before the sync body and the test passed
anyway, so nine load-bearing mutations survived the suite. These tests
run the real script inside ``daily_sync_harness``'s throwaway world — two
bare remotes, one or two machine clones, a pinned ``HOME``, and a stub
``PATH`` that makes network egress impossible — and assert consequences
in the published repositories rather than log substrings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from daily_sync_harness import build_world, git, SyncWorld


@pytest.fixture()
def world(tmp_path: Path) -> SyncWorld:
    """A seeded two-remote world with no machines yet."""
    return build_world(tmp_path)


# ============================================================================
# The sync body actually runs (audit C1 / S21)
# ============================================================================


class TestSyncReachesTheEnd:
    """The previous fixture exited 1 at the parent stash, so every
    load-bearing branch below it was dead in test. A sync over a clean
    world must run to completion and take its documented no-op paths."""

    def test_clean_sync_runs_to_completion(self, world: SyncWorld) -> None:
        """A machine with nothing to do exits 0 having reached the end."""
        machine = world.add_machine("a")
        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "=== daily-sync complete" in combined, combined
        # Everything past the point the old fixture died is reached.
        assert world.calls_to("sync-symlinks.sh"), combined
        assert world.calls_to("check-archive-drift.py"), combined

    def test_memory_append_is_committed_on_its_own(self, world: SyncWorld) -> None:
        """An appended record is committed with an explicit pathspec, and
        a concurrent session's prose edit is NOT swept into that commit.

        Kills DS-M3/DS-M4 (``git add -- "${memory_dirty[@]}"`` widened to
        ``git add -A``, or the pathspec dropped from ``git commit``)."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-aaa")
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- half-written thought\n", encoding="utf-8"
        )
        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr

        # Find the append-only commit (a later commit may sweep the rest
        # of the dirty tree — that is the `git add -A` behaviour audit S2
        # leaves to Shawn's decision and this test deliberately ignores).
        log = git("log", "--format=%H %s", cwd=machine.data).stdout.splitlines()
        memory_commits = [ln.split(" ", 1)[0] for ln in log if "append-only capture" in ln]
        assert len(memory_commits) == 1, log
        touched = git(
            "show", "--name-only", "--format=", memory_commits[0], cwd=machine.data
        ).stdout.split()
        assert touched == ["memories/memories.jsonl"], touched

    def test_dry_run_commits_nothing_and_pushes_nothing(self, world: SyncWorld) -> None:
        """``--dry-run`` must leave every repository byte-identical."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-dry")
        before_data = machine.head("data")
        before_parent = machine.head("parent")
        before_published = world.published_data_head()

        result = world.run_sync(machine, "--dry-run")
        assert result.returncode == 0, result.stdout + result.stderr
        assert machine.head("data") == before_data
        assert machine.head("parent") == before_parent
        assert world.published_data_head() == before_published
        # The append is still sitting uncommitted in the working tree.
        assert "2026-09-08-dry" in machine.memories.read_text(encoding="utf-8")


# ============================================================================
# Parent-repo branch guard (Batch 11 Medium, 2026-05-02)
# ============================================================================


class TestParentBranchGuard:
    """``daily-sync.sh`` must not sync from a parent-repo feature branch:
    ``push_with_retry`` hardcodes ``git push origin main``, so the pointer
    bump would land on the feature branch while the unchanged local main
    was published, orphaning the bump.

    Migrated from ``tests/test_glue_scripts.py`` onto the behavioural
    harness (audit C1/S21): the old fixture asserted a log substring on a
    run that had already exited 1 several steps earlier.
    """

    def test_feature_branch_switches_to_main_and_publishes(
        self, world: SyncWorld
    ) -> None:
        """The run switches to main, completes, and the bump reaches origin."""
        machine = world.add_machine("a")
        git("checkout", "-q", "-b", "feature/x", cwd=machine.pa)
        machine.append_memory("2026-09-08-branch")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "parent repo on 'feature/x' — switching to main" in combined
        assert machine.branch("parent") == "main"
        # The bump was published from main, not orphaned on feature/x.
        assert world.published_pointer() == machine.head("data")

    def test_source_has_parent_branch_guard(self) -> None:
        """Defence in depth: the guard must not vanish in a refactor."""
        source = (Path(__file__).resolve().parent.parent
                  / "scripts" / "daily-sync.sh").read_text(encoding="utf-8")
        assert "parent_current_branch" in source
        assert "failed to switch parent repo to main" in source
