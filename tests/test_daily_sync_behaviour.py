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
        # Staged, not merely dirty: a concurrent session part-way through
        # its own `git add`. Without the commit's pathspec this is what
        # gets swept into the automatic commit (audit M2 / DS-M4).
        git("add", "--", "tasks/inbox.md", cwd=machine.data)
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

        # The prose edit was stashed for the pull and came back. Kills
        # DS-M2 (delete the stash-pop block: every run buries the day's
        # work in a stash nobody looks at).
        assert "half-written thought" in (
            machine.data / "tasks" / "inbox.md"
        ).read_text(encoding="utf-8")

    def test_append_only_block_stages_nothing_else(self, world: SyncWorld) -> None:
        """The `git add` before the append-only commit must carry the
        pathspec too, not just the `git commit`.

        Audit M2: the commit-contents assertion above passes with either
        half of the pair intact, because `git commit -- <paths>` is a
        partial commit and ignores whatever else is staged. Observe the
        index at the moment of that commit instead: a post-commit hook
        records what is still staged, which must be nothing.
        """
        machine = world.add_machine("a")
        record = world.root / "staged-at-append-commit.txt"
        hook = machine.data_git_dir / "hooks" / "post-commit"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            "# Record the real index at the append-only commit.\n"
            'git log -1 --format=%s | grep -q "append-only capture" || exit 0\n'
            f'env -u GIT_INDEX_FILE git diff --cached --name-only > "{record}"\n'
            "exit 0\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        machine.append_memory("2026-09-08-m2")
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- a concurrent session is mid-edit\n", encoding="utf-8"
        )
        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr

        assert record.exists(), "the append-only commit never ran"
        assert record.read_text(encoding="utf-8").strip() == "", (
            "the append-only block staged files outside MEMORY_APPEND_FILES: "
            + record.read_text(encoding="utf-8")
        )

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
# Unpushed data-submodule commits (audit S1)
# ============================================================================


class TestSubmoduleCommitsArePublished:
    """Every commit made in the data submodule during a run must reach
    origin before the parent pointer bump that references it is pushed.

    Observed live on 2026-09-08 at 09:29: the append-only memory commit
    emptied the tree, so the commit-and-push block took its "nothing to
    commit" branch and never pushed, while the parent bump referencing
    that commit was published. Origin's personal-assistant then pointed
    at a pa-data SHA the other machine could not fetch.
    """

    def test_memory_commit_reaches_the_data_remote(self, world: SyncWorld) -> None:
        """The append-only commit is published even though the tree ended clean."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-s1")
        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr
        assert world.published_data_head() == machine.head("data")
        assert "2026-09-08-s1" in world.published_data_file("memories/memories.jsonl")

    def test_published_pointer_is_fetchable(self, world: SyncWorld) -> None:
        """The parent pointer must never name an object origin lacks."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-s1b")
        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr
        pointer = world.published_pointer()
        assert pointer == machine.head("data")
        assert world.data_object_exists(pointer), (
            f"published parent points at {pointer}, which is not in the data "
            "remote — `git submodule update` on the other machine would fail "
            'with "reference is not a tree"'
        )

    def test_bump_is_withheld_when_the_submodule_is_unverifiable(
        self, world: SyncWorld
    ) -> None:
        """Audit M1: no origin/main means the ahead-check cannot run, so the
        parent bump must not be published either.

        Reached by a misconfigured remote — a fetch refspec that never
        writes refs/remotes/origin/main — under which the pull still
        succeeds, so the run reaches the bump with no way to tell whether
        the submodule HEAD is fetchable.
        """
        machine = world.add_machine("a")
        git("config", "--unset", "remote.origin.fetch", cwd=machine.data)
        git("update-ref", "-d", "refs/remotes/origin/main", cwd=machine.data)
        machine.append_memory("2026-09-08-m1")
        parent_before = world.published_parent_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "bump WITHHELD" in combined
        assert world.published_parent_head() == parent_before, (
            "published a pointer to a data commit that may be unfetchable"
        )
        assert world.gate("daily-sync-gate").splitlines()[0] == "1"

    def test_second_machine_can_follow(self, world: SyncWorld) -> None:
        """The end-to-end consequence: machine B can update to A's push."""
        machine_a = world.add_machine("a")
        machine_b = world.add_machine("b")
        machine_a.append_memory("2026-09-08-s1c")
        assert world.run_sync(machine_a).returncode == 0

        git("pull", "-q", "--ff-only", "origin", "main", cwd=machine_b.pa)
        git("submodule", "update", "--init", "--quiet", cwd=machine_b.pa)
        assert "2026-09-08-s1c" in machine_b.memories.read_text(encoding="utf-8")


# ============================================================================
# Failure paths (Lens B M2 — none of these were exercised at all)
# ============================================================================


class TestCrossMachineRebase:
    """The everyday two-machine case: both machines appended today, so
    the pull is not a fast-forward and the rebase conflicts on
    memories.jsonl. This is the path the append-safe resolver exists
    for, and nothing exercised it end to end."""

    def test_both_machines_records_survive_the_rebase(
        self, world: SyncWorld
    ) -> None:
        """Union, not one side — the resolver is genuinely invoked here."""
        machine = world.add_machine("a")
        world.publish_memory_append("2026-09-08-from-b")
        machine.append_memory("2026-09-08-from-a")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "not fast-forwardable" in combined
        assert "rebase conflicts resolved" in combined

        published = world.published_data_file("memories/memories.jsonl")
        assert "2026-09-08-from-a" in published
        assert "2026-09-08-from-b" in published, "the other machine's record was lost"
        assert "<<<<<<<" not in published

    def test_rebase_conflict_on_prose_aborts(self, world: SyncWorld) -> None:
        """Kills DS-M6: routing an unknown path to the submodule branch
        would resolve a conflicted prose file trust-ours instead."""
        machine = world.add_machine("a")
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- local commitment\n", encoding="utf-8"
        )
        machine.commit_data("local inbox edit", "tasks/inbox.md")
        world.publish_data_change("tasks/inbox.md", "# Inbox\n\n- remote item\n")
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "unsupported paths" in combined
        # The rebase was aborted, so no half-finished state is left.
        assert not (machine.data_git_dir / "rebase-merge").exists()
        assert "<<<<<<<" not in (
            machine.data / "tasks" / "inbox.md"
        ).read_text(encoding="utf-8")
        assert world.published_data_head() == published_before


class TestStashIsRestoredWhenTheRunAborts:
    """If anything between the stash and the pop fails, the EXIT trap must
    put the working tree back. An un-popped stash is invisible until
    someone goes looking — the shape that orphaned 41 records."""

    def test_failed_pull_restores_the_stashed_edits(self, world: SyncWorld) -> None:
        """Kills DS-M5: removing `trap restore_stash_on_exit EXIT` leaves
        the day's uncommitted work buried in a stash."""
        machine = world.add_machine("a")
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- unsaved work\n", encoding="utf-8"
        )
        # Break the data remote so the pull cannot succeed.
        git("remote", "set-url", "origin", str(world.root / "no-such-remote.git"),
            cwd=machine.data)

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "unsaved work" in (
            machine.data / "tasks" / "inbox.md"
        ).read_text(encoding="utf-8"), "the edit is buried in a stash"
        assert not git("stash", "list", cwd=machine.data).stdout.strip()


class TestShrinkDetector:
    """A net shrink of memories.jsonl without a ``Rewrite-Class: bulk``
    trailer must undo the commit and abort before the push."""

    def test_shrink_aborts_the_push_and_reports(self, world: SyncWorld) -> None:
        """Kills DS-M7: with the guard off, a truncated corpus is pushed."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-doomed")
        # Simulate something truncating the corpus mid-run: a post-commit
        # hook fires once, after the append-only commit, so the shrink is
        # carried by the auto-sync commit the detector inspects.
        hook = machine.data_git_dir / "hooks" / "post-commit"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            "# Test hook: truncate the corpus exactly once.\n"
            'marker="$GIT_DIR/truncated"\n'
            '[[ -f "$marker" ]] && exit 0\n'
            'touch "$marker"\n'
            'printf "" > memories/memories.jsonl\n'
            "exit 0\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 4, combined
        assert "SHRINK DETECTED" in combined
        assert list((machine.pa / "logs").glob("daily-sync-SHRINK-*.txt"))
        assert world.published_data_head() == published_before, (
            "a shrunk corpus reached origin"
        )


# ============================================================================
# Detached-HEAD ordering (audit S5)
# ============================================================================


class TestDetachedHeadGuard:
    """Nothing may commit into the data submodule before the branch guard.

    ``git submodule update`` — run by ``sync-symlinks.sh`` at the end of
    every sync, and by ``setup.sh`` — checks the recorded SHA out
    *detached* whenever the parent pointer and the submodule HEAD
    disagree. The guard used to sit below the archiver and the
    append-only memory commit, so on a detached HEAD those commits landed
    on an unreachable ref and the guard's ``git checkout main`` then
    reverted the working tree, removing the just-appended records.
    """

    def test_append_survives_a_detached_head(self, world: SyncWorld) -> None:
        """The record reaches origin instead of the reflog."""
        machine = world.add_machine("a")
        git("checkout", "-q", "--detach", "HEAD", cwd=machine.data)
        machine.append_memory("2026-09-08-s5")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "switching to main" in combined
        assert machine.branch("data") == "main"
        assert "2026-09-08-s5" in machine.memories.read_text(encoding="utf-8"), (
            "the branch switch reverted the working tree over the append"
        )
        assert "2026-09-08-s5" in world.published_data_file("memories/memories.jsonl")

    def test_two_stashes_in_one_run_are_both_popped(
        self, world: SyncWorld
    ) -> None:
        """Audit C1 — a regression the S5 guard introduced.

        On a detached HEAD the guard stashes; if anything dirties the tree
        before the pre-pull block (here the archiver writes prose, as a
        concurrent session would) a SECOND stash is pushed. Only one pop
        ran, so the branch-switch stash — holding the day's memory append —
        stayed on the stack while the run exited 0 and cleared the gate.
        """
        machine = world.add_machine("a")
        git("checkout", "-q", "--detach", "HEAD", cwd=machine.data)
        machine.append_memory("2026-09-08-c1")

        result = world.run_sync(
            machine, PA_TEST_ARCHIVER_DIRTIES="# Inbox\n\n- written mid-run\n"
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined

        assert not git("stash", "list", cwd=machine.data).stdout.strip(), (
            "a stash this run pushed was left on the stack"
        )
        assert "2026-09-08-c1" in machine.memories.read_text(encoding="utf-8")
        assert "2026-09-08-c1" in world.published_data_file("memories/memories.jsonl")
        assert "written mid-run" in (
            machine.data / "tasks" / "inbox.md"
        ).read_text(encoding="utf-8")

    def test_overlapping_stashes_leave_a_gate_naming_the_stash(
        self, world: SyncWorld
    ) -> None:
        """Second re-audit C1: a REFUSED pop must not exit silently.

        When two stashes this run pushed touch the same file, the first
        pop restores it and the second is refused outright — rc 1, "your
        local changes would be overwritten", nothing unmerged. That fell
        through to a bare `fail` with the remaining stash already
        forgotten, so the next run exited 0 and wrote gate 0 over it while
        the work sat in a stash nobody knew about.
        """
        machine = world.add_machine("a")
        git("checkout", "-q", "--detach", "HEAD", cwd=machine.data)
        # Both stashes will touch tasks/inbox.md at the same line.
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- from before the switch\n", encoding="utf-8"
        )
        result = world.run_sync(
            machine, PA_TEST_ARCHIVER_DIRTIES="# Inbox\n\n- written mid-run\n"
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0, combined
        assert "STRANDED STASH" in combined, combined

        leftovers = git("stash", "list", cwd=machine.data).stdout.strip().splitlines()
        assert len(leftovers) == 1, leftovers
        gate = world.gate("daily-sync-gate").splitlines()
        assert gate and gate[0] == "1", gate
        # Named by SHA, so the operator can actually recover it.
        stranded_sha = git(
            "rev-parse", "--short=8", "stash@{0}", cwd=machine.data
        ).stdout.strip()
        assert stranded_sha in "\n".join(gate), gate
        # Oldest-first ordering: the branch-switch stash is the one that
        # applied, so the later "daily-sync on <host>" stash is stranded.
        assert "daily-sync on" in leftovers[0]
        assert "branch-switch" not in leftovers[0]

    def test_a_conflicted_pop_drops_only_the_entry_it_popped(
        self, world: SyncWorld
    ) -> None:
        """After resolving a conflicted pop, the entry that was popped is
        the one to drop — not whatever is on top.

        The conflicted entry is the OLDER of this run's two stashes, so a
        bare `git stash drop` takes the newer one instead: that work is
        discarded unapplied, and the conflicted entry stays on the stack.
        """
        machine = world.add_machine("a")
        git("checkout", "-q", "--detach", "HEAD", cwd=machine.data)
        machine.append_memory("2026-09-08-ours")          # -> stash A
        world.publish_memory_append("2026-09-08-theirs")  # conflicts with A

        result = world.run_sync(
            machine,
            PA_TEST_ARCHIVER_DIRTIES="# Inbox\n\n- written mid-run\n",  # -> stash B
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert not git("stash", "list", cwd=machine.data).stdout.strip(), (
            "an entry was left behind, so the wrong one was dropped"
        )
        assert "written mid-run" in (
            machine.data / "tasks" / "inbox.md"
        ).read_text(encoding="utf-8"), "the newer stash was dropped unapplied"
        published = world.published_data_file("memories/memories.jsonl")
        assert "2026-09-08-ours" in published
        assert "2026-09-08-theirs" in published

    def test_a_concurrent_sessions_stash_is_never_touched(
        self, world: SyncWorld
    ) -> None:
        """Only stashes this run created may be popped.

        A concurrent session pushes its own stash between our
        branch-switch stash and our pre-pull stash, so ours are no longer
        the top of the stack. Matching by SHA is what keeps their work
        out of our tree; matching by position would pop it and drop it.
        """
        machine = world.add_machine("a")
        git("checkout", "-q", "--detach", "HEAD", cwd=machine.data)
        machine.append_memory("2026-09-08-mine")

        result = world.run_sync(
            machine,
            PA_TEST_ARCHIVER_STASHES="their unfinished note\n",
            PA_TEST_ARCHIVER_DIRTIES="# Inbox\n\n- ours, mid-run\n",
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined

        # Theirs is still on the stack, untouched and unapplied.
        leftovers = git("stash", "list", cwd=machine.data).stdout.strip().splitlines()
        assert len(leftovers) == 1, leftovers
        assert "a concurrent session" in leftovers[0]
        assert not (machine.data / "tasks" / "foreign-session.md").exists(), (
            "a concurrent session's stash was applied into our tree"
        )
        # Ours both came back and were published.
        assert "2026-09-08-mine" in world.published_data_file("memories/memories.jsonl")
        assert "ours, mid-run" in (
            machine.data / "tasks" / "inbox.md"
        ).read_text(encoding="utf-8")

    def test_detached_head_with_prose_edits_keeps_them(
        self, world: SyncWorld
    ) -> None:
        """A concurrent session's uncommitted prose survives the switch."""
        machine = world.add_machine("a")
        git("checkout", "-q", "--detach", "HEAD", cwd=machine.data)
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- work in progress\n", encoding="utf-8"
        )
        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "work in progress" in (
            machine.data / "tasks" / "inbox.md"
        ).read_text(encoding="utf-8")


# ============================================================================
# Conflict partitioning (audit S3)
# ============================================================================


class TestStashPopConflictPartitioning:
    """A stash-pop conflict on a prose file must abort, not be "resolved".

    ``resolve-merge-conflicts.py`` strips conflict markers and unions both
    sides. That is right for an append-only JSONL and destructive for
    anything else: a conflicted ``tasks/inbox.md`` came back as an
    interleaved union with duplicate lines dropped, was committed by the
    block below, and was pushed. The rebase path has always partitioned;
    this path did not.
    """

    def test_prose_conflict_aborts_and_preserves_the_tree(
        self, world: SyncWorld
    ) -> None:
        """The tree is left as git left it and nothing is published."""
        machine = world.add_machine("a")
        world.publish_data_change(
            "tasks/inbox.md", "# Inbox\n\n- from the other machine\n"
        )
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- half-written local thought\n", encoding="utf-8"
        )
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined

        inbox = (machine.data / "tasks" / "inbox.md").read_text(encoding="utf-8")
        assert "<<<<<<<" in inbox, (
            "the union resolver rewrote a prose file instead of aborting:\n" + inbox
        )
        assert "half-written local thought" in inbox
        # The stash git preserved on a conflicted pop is still there.
        assert git("stash", "list", cwd=machine.data).stdout.strip()
        # And the EXIT handler did not try to re-pop into the half-merged
        # tree on the way out (second re-audit M5).
        assert "— restoring" not in combined, combined
        # Nothing was published.
        assert world.published_data_head() == published_before

    def test_prose_conflict_writes_a_gate_line(self, world: SyncWorld) -> None:
        """The wedged state is surfaced at session start, not only logged."""
        machine = world.add_machine("a")
        world.publish_data_change("tasks/inbox.md", "# Inbox\n\n- theirs\n")
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- ours\n", encoding="utf-8"
        )
        world.run_sync(machine)

        gate = world.gate("daily-sync-gate")
        assert gate.splitlines()[0] == "1", gate
        assert "tasks/inbox.md" in gate

    def test_tag_vocabulary_conflict_is_resolved_like_the_corpus(
        self, world: SyncWorld
    ) -> None:
        """Audit L1: every entry of MEMORY_APPEND_FILES must reach the
        resolver, not just the first. The vocabulary is the second, and
        nothing exercised it through the stash-pop path."""
        machine = world.add_machine("a")
        git("checkout", "-q", "--detach", "HEAD", cwd=machine.data)
        world.publish_data_change(
            "memories/tag-vocabulary.txt", "seed-tag\nremote-tag\n"
        )
        (machine.data / "memories" / "tag-vocabulary.txt").write_text(
            "seed-tag\nlocal-tag\n", encoding="utf-8"
        )

        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr
        published = world.published_data_file("memories/tag-vocabulary.txt")
        assert "local-tag" in published
        assert "remote-tag" in published
        assert "<<<<<<<" not in published

    def test_staged_markers_are_refused_by_the_append_only_block(
        self, world: SyncWorld
    ) -> None:
        """Second re-audit C2: the check must read CONTENT, not the index.

        The previous check read the porcelain code, so a marker-laden
        memories.jsonl that had been `git add`ed read as a plain `M ` and
        was committed and pushed — and the gate this script printed told
        the operator to run exactly that `git add`.
        """
        machine = world.add_machine("a")
        machine.memories.write_text(
            '{"id": "ours"}\n'
            "<<<<<<< Updated upstream\n"
            '{"id": "theirs"}\n'
            "=======\n"
            '{"id": "mine"}\n'
            ">>>>>>> Stashed changes\n",
            encoding="utf-8",
        )
        git("add", "--", "memories/memories.jsonl", cwd=machine.data)
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "conflict markers" in combined
        assert world.published_data_head() == published_before
        committed = git("show", "HEAD:memories/memories.jsonl", cwd=machine.data).stdout
        assert "<<<<<<<" not in committed, "markers were committed"
        # And the advice must not be the very command that caused this.
        gate = world.gate("daily-sync-gate")
        assert "resolve-merge-conflicts.py" in gate
        assert "Do NOT 'git add'" in gate

    def test_markers_pulled_from_origin_stop_the_auto_sync_commit(
        self, world: SyncWorld
    ) -> None:
        """The other machine published a marker-laden corpus (the C2
        disaster). After the pull, this machine must refuse to build a
        commit on top of it — the auto-sync block is the last gate before
        `git add -A` sweeps the corpus into a commit."""
        machine = world.add_machine("a")
        world.publish_data_change(
            "memories/memories.jsonl",
            '{"id": "seed"}\n<<<<<<< HEAD\n{"id": "a"}\n=======\n{"id": "b"}\n>>>>>>> x\n',
        )
        # Something else dirty, so the auto-sync block would commit.
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- local note\n", encoding="utf-8"
        )
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "auto-sync commit" in combined
        assert world.published_data_head() == published_before, (
            "committed on top of a corpus full of conflict markers"
        )

    def test_next_run_refuses_to_commit_the_conflicted_corpus(
        self, world: SyncWorld
    ) -> None:
        """Audit C2, end to end over two runs.

        Run one takes the S3 abort with markers left in both a prose file
        and memories.jsonl. Run two used to see ``UU memories/…`` as merely
        "dirty", stage it, and commit git's conflict markers into the
        append-only corpus — which the S1 push then publishes to both
        machines as unparseable JSONL.
        """
        machine = world.add_machine("a")
        # Both files conflict, and both are in the branch-switch stash
        # (which is the only stash that can carry memories.jsonl).
        git("checkout", "-q", "--detach", "HEAD", cwd=machine.data)
        world.publish_data_change("tasks/inbox.md", "# Inbox\n\n- theirs\n")
        world.publish_memory_append("2026-09-08-theirs")
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- ours\n", encoding="utf-8"
        )
        machine.append_memory("2026-09-08-ours")

        first = world.run_sync(machine)
        assert first.returncode == 2, first.stdout + first.stderr
        corpus = machine.memories.read_text(encoding="utf-8")
        assert "<<<<<<<" in corpus, "expected run one to leave the corpus unmerged"
        published_before = world.published_data_head()

        second = world.run_sync(machine)
        combined = second.stdout + second.stderr
        assert second.returncode == 2, combined
        # Refused by the content check (which now runs first) or by the
        # unmerged-index check behind it; either way, refused.
        assert "conflict markers" in combined or "unmerged" in combined, combined
        # The direct harm: markers must never enter a commit. (They reach
        # origin one step later, when the human resolves the prose file
        # that stopped the run and the S1 push finds HEAD ahead.)
        committed = git("show", "HEAD:memories/memories.jsonl", cwd=machine.data).stdout
        assert "<<<<<<<" not in committed, "conflict markers were committed"
        assert world.published_data_head() == published_before, (
            "conflict markers were committed and published"
        )
        assert "<<<<<<<" not in world.published_data_file("memories/memories.jsonl")
        gate = world.gate("daily-sync-gate")
        assert gate.splitlines()[0] == "1", gate
        assert "memories/memories.jsonl" in gate

    def test_clean_run_clears_the_gate(self, world: SyncWorld) -> None:
        """A gate left by an earlier wedge must not nag forever."""
        machine = world.add_machine("a")
        (world.home / ".cache" / "daily-sync-gate").write_text(
            "1\nstale wedge from an earlier run\n", encoding="utf-8"
        )
        assert world.run_sync(machine).returncode == 0
        assert world.gate("daily-sync-gate").splitlines() == ["0"]


# ============================================================================
# Wedged states are surfaced, not merely logged (audit S17, S19)
# ============================================================================


class TestOrphanedStashWedge:
    """A conflicted orphan-stash pop stops every later run in the same
    place — the tree stays conflicted, the extraction hook keeps
    appending to an invalid JSONL, and each session re-enters the same
    failure. Only the log said so."""

    def test_conflicted_orphan_pop_writes_a_gate_line(self, world: SyncWorld) -> None:
        """The wedge is recorded where session start will show it."""
        machine = world.add_machine("a")
        # Build a stash that cannot be applied cleanly: stash one append,
        # then commit a different one at the same end-of-file position.
        machine.append_memory("2026-09-08-stashed")
        git("stash", "push", "-q", "-m", "orphan", cwd=machine.data)
        machine.append_memory("2026-09-08-committed")
        machine.commit_data("conflicting append", "memories/memories.jsonl")

        result = world.run_sync(machine, PA_TEST_ORPHAN_STASHES="stash@{0}")
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "ORPHANED STASH" in combined

        gate = world.gate("daily-sync-gate")
        assert gate.splitlines()[0] == "1", gate
        assert "orphaned stash" in gate.lower()
        # The stash itself is preserved for the human.
        assert git("stash", "list", cwd=machine.data).stdout.strip()


class TestParentStashWedge:
    """The parent half wedges the same way the data half does: while a
    path is unmerged, the next run's `git stash push -u -- ':!data'`
    refuses, so every later session fails in the same place. Audit M3 —
    it had no gate line."""

    def test_parent_pop_conflict_writes_a_gate_line(self, world: SyncWorld) -> None:
        """A conflicted parent pop is surfaced at session start."""
        machine = world.add_machine("a")
        world.publish_parent_change("settings.json", '{"from": "the other machine"}\n')
        (machine.pa / "settings.json").write_text('{"from": "here"}\n', encoding="utf-8")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "stash pop raised conflicts" in combined

        gate = world.gate("daily-sync-gate")
        assert gate.splitlines()[0] == "1", gate
        assert "parent-repo stash pop conflicted" in gate
        # …and the stash holding the work is named too (second re-audit C1).
        assert "UNRECOVERED" in gate
        # The stash git preserved on a conflicted pop is still there.
        assert git("stash", "list", cwd=machine.pa).stdout.strip()


class TestUnusableHomeIsNotLockContention:
    """Every gate this script writes lives under ~/.cache, so an unset or
    unwritable HOME must stop the run up front with exit 2 — not abort it
    with "unbound variable" (status 1, which the trigger reports as lock
    contention), and not kill it half-way through at a gate write, after
    it has already committed and pushed. Second re-audit M4."""

    def test_unset_home_fails_early_with_a_diagnosis(
        self, world: SyncWorld
    ) -> None:
        """No commit, no push, and an exit code that means "broken"."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-m4")
        before = world.published_data_head()

        result = world.run_sync(machine, HOME="__PA_TEST_UNSET__")
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "HOME is unset" in combined
        assert world.published_data_head() == before

    def test_unwritable_cache_fails_before_any_commit(
        self, world: SyncWorld
    ) -> None:
        """A gate directory that cannot be written stops the run at the
        start, not after the commits have gone out."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-m4b")
        (world.home / ".cache").rmdir()
        (world.home / ".cache").write_text("not a directory\n", encoding="utf-8")
        before = world.published_data_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "not writable" in combined
        assert world.published_data_head() == before


class TestOrphanStashesAreResolvedByIdentity:
    """The drift detector hands back ``stash@{n}`` selectors produced by
    another process. An index is a position, not an identity: one
    concurrent push or drop renumbers the stack. Resolve to a SHA at read
    time and pop by SHA (second re-audit, low)."""

    def test_a_stale_selector_does_not_wedge_the_sync(
        self, world: SyncWorld
    ) -> None:
        """A selector that no longer resolves means the stash is gone —
        skip it. Popping it blind failed and took the whole sync down."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-orphan")

        result = world.run_sync(machine, PA_TEST_ORPHAN_STASHES="stash@{7}")
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "no longer resolves" in combined
        # The run carried on and did its work.
        assert "2026-09-08-orphan" in world.published_data_file(
            "memories/memories.jsonl"
        )

    def test_a_real_orphan_is_recovered_and_published(
        self, world: SyncWorld
    ) -> None:
        """The load-bearing 2026-08-20 recovery still recovers."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-stranded")
        git("stash", "push", "-q", "-m", "orphaned by a killed run", cwd=machine.data)

        result = world.run_sync(machine, PA_TEST_ORPHAN_STASHES="stash@{0}")
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "recovered" in combined
        assert not git("stash", "list", cwd=machine.data).stdout.strip()
        assert "2026-09-08-stranded" in world.published_data_file(
            "memories/memories.jsonl"
        )


class TestBrokenCheckoutIsNotLockContention:
    """``daily-sync-trigger.sh`` maps exit 1 to "another sync is running".
    A broken checkout must therefore never exit 1 (audit S19)."""

    def test_uninitialised_submodule_fails_with_a_diagnosis(
        self, world: SyncWorld
    ) -> None:
        """An absent data/.git is named, not mistaken for a lock."""
        machine = world.add_machine("a")
        (machine.data / ".git").rename(machine.data / ".git-disabled")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "not initialised" in combined
        # Nothing was stashed in the parent by git walking up to it.
        assert not git("stash", "list", cwd=machine.pa).stdout.strip()

    def test_unwritable_log_dir_fails_with_a_diagnosis(
        self, world: SyncWorld
    ) -> None:
        """A log dir that cannot be created is named, not mistaken for a lock."""
        machine = world.add_machine("a")
        (machine.pa / "logs").rmdir()
        (machine.pa / "logs").write_text("not a directory\n", encoding="utf-8")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "log directory" in combined


# ============================================================================
# Rebase-conflict resolution on the submodule pointer (audit S4)
# ============================================================================


def _prepare_competing_parent_bump(world: SyncWorld) -> tuple[str, Path]:
    """
    Prepare — but do not publish — another machine's ``data`` bump.

    The foreign pointer is a real commit in the data remote (pushed to a
    side branch, so the data half of the sync is untouched); only the
    parent-repo pointer will conflict. Returns the foreign gitlink SHA
    and the clone whose ``main`` holds the unpublished bump.
    """
    side = world.root / "side-data"
    git("clone", "-q", str(world.data_remote), str(side), cwd=world.root)
    (side / "memories" / "memories.jsonl").write_text(
        '{"id": "2026-09-08-foreign", "content": "other machine"}\n', encoding="utf-8"
    )
    git("commit", "-q", "-am", "foreign data commit", cwd=side)
    git("push", "-q", "origin", "HEAD:refs/heads/side", cwd=side)
    foreign_sha = git("rev-parse", "HEAD", cwd=side).stdout.strip()

    other = world.root / "side-parent"
    git("clone", "-q", "--no-checkout", str(world.parent_remote), str(other), cwd=world.root)
    git("read-tree", "-m", "-u", "HEAD", cwd=other)
    git("update-index", "--cacheinfo", f"160000,{foreign_sha},data", cwd=other)
    git("commit", "-q", "-m", "other machine bump", cwd=other)
    return foreign_sha, other


class TestRebasePointerConflict:
    """When the parent push is rejected and the rebase conflicts on the
    ``data`` gitlink, the local bump must win — we have just pushed the
    submodule, so origin's pointer is the stale one.

    git-checkout(1): during a rebase ``--ours`` is the branch being
    rebased ONTO (origin) and ``--theirs`` is the work being replayed
    (ours). The script used ``--ours``, the opposite of its comment.

    Measured while writing these tests: for a *gitlink* the flag decides
    nothing — neither form alters the index entry, and the following
    ``git add data`` records the submodule's checked-out HEAD. The
    outcome is therefore pinned behaviourally here and the flag itself
    by source inspection.
    """

    def test_local_pointer_wins_the_rebase(self, world: SyncWorld) -> None:
        """Stage a genuine push race with a pre-push hook, then check
        which pointer origin ends up holding."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-s4")

        # A pre-push hook lets the other machine win the race exactly
        # once, so our first parent push is rejected and the retry path
        # has to rebase — the only way to reach the conflict resolver.
        race_marker = world.root / "race-done"
        foreign_sha, other = _prepare_competing_parent_bump(world)
        hook = machine.pa / ".git" / "hooks" / "pre-push"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            "# Test hook: publish the other machine's bump, once.\n"
            "cat >/dev/null\n"
            f'[[ -f "{race_marker}" ]] && exit 0\n'
            f'touch "{race_marker}"\n'
            "env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_PREFIX \\\n"
            f'    git -C "{other}" push -q origin main\n'
            "exit 0\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined

        published_log = git("log", "--format=%s", "main", cwd=world.parent_remote).stdout
        assert "other machine bump" in published_log, (
            "the other machine's commit was clobbered rather than rebased onto"
        )
        assert world.published_pointer() == machine.head("data"), (
            "origin kept the stale foreign pointer "
            f"({foreign_sha[:8]}) instead of our freshly pushed submodule SHA"
        )

    def test_every_interpreter_call_uses_pa_dir(self) -> None:
        """Audit L3: one call hardcoded ~/personal-assistant/venv, so a run
        from a worktree or a relocated checkout used another tree's
        interpreter. The cc-archives block it sits in only runs with the
        rpi-shares mount present, which no test can have — hence a source
        assertion."""
        source = (Path(__file__).resolve().parent.parent
                  / "scripts" / "daily-sync.sh").read_text(encoding="utf-8")
        assert "$HOME/personal-assistant" not in source, (
            "an interpreter or path is resolved through $HOME instead of $PA_DIR"
        )

    def test_memory_append_list_has_one_source_of_truth(self) -> None:
        """Audit L1: the three conflict partitions must derive from
        MEMORY_APPEND_FILES, not each repeat it as a literal. With the
        list written out three times, adding a file to the array would
        have silently left every partition routing it to "unsupported"."""
        source = (Path(__file__).resolve().parent.parent
                  / "scripts" / "daily-sync.sh").read_text(encoding="utf-8")
        assert source.count("memories/tag-vocabulary.txt") == 1, (
            "the append-only file list is written out more than once"
        )

    def test_source_never_takes_origin_side_in_a_rebase(self) -> None:
        """Both rebase resolvers must use ``--theirs``.

        ``resolve_rebase_conflicts``'s submodule branch is only reachable
        from a context where a ``data`` gitlink can conflict, which the
        data submodule itself never has — so it is pinned by source
        inspection rather than behaviourally.
        """
        source = (Path(__file__).resolve().parent.parent
                  / "scripts" / "daily-sync.sh").read_text(encoding="utf-8")
        assert "checkout --ours" not in source, (
            "audit S4: --ours takes origin's stale pointer during a rebase"
        )
        assert source.count("git checkout --theirs -- ") == 2


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
