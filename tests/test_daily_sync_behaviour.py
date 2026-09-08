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

import json
import signal
import subprocess
import time
from pathlib import Path

import pytest

from daily_sync_harness import build_world, git, SyncWorld


@pytest.fixture()
def world(tmp_path: Path) -> SyncWorld:
    """A seeded two-remote world with no machines yet."""
    return build_world(tmp_path)


def gate_details(world: SyncWorld) -> list[str]:
    """
    Return the daily-sync gate's detail lines, checking its own header.

    The first line is a problem count and the rest are the problems. A
    gate whose header disagrees with its body is the sort of thing an
    operator stops trusting, so every gate assertion goes through here
    (audit M1, fourth re-audit).
    """
    text = world.gate("daily-sync-gate")
    assert text, "no gate was written"
    lines = text.splitlines()
    count, details = int(lines[0]), lines[1:]
    assert count == len(details), f"header says {count}, body has {len(details)}: {lines}"
    assert count > 0, lines
    return details


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

    def test_dry_run_writes_no_gate(self, world: SyncWorld) -> None:
        """Audit (low, fourth re-audit): "no changes" includes the gate.

        A dry run that leaves a gate behind nags at every session start
        until a real run clears it — and with `fail` now gating every
        failure, a dry run on a broken checkout would do exactly that.
        """
        machine = world.add_machine("a")
        (machine.data / ".git").rename(machine.data / ".git-disabled")

        result = world.run_sync(machine, "--dry-run")
        assert result.returncode == 2, result.stdout + result.stderr
        assert world.gate("daily-sync-gate") == "", "a dry run wrote a gate file"

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
        assert gate_details(world)

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

    @pytest.mark.parametrize("style", ["diff3", "zdiff3"])
    def test_diff3_conflict_style_never_publishes_a_base_marker(
        self, world: SyncWorld, style: str
    ) -> None:
        """Audit C1 (third re-audit), end to end.

        With ``merge.conflictStyle`` set to diff3 or zdiff3 — a per-machine
        setting nothing here controls — git emits a fourth marker and a
        merge-base section. Neither the resolver nor the marker guard knew
        about it, so a corpus carrying ``||||||| parent of <sha>`` reached
        the bare remote with exit 0 and a clean gate.
        """
        machine = world.add_machine("a")
        git("config", "merge.conflictStyle", style, cwd=machine.data)
        world.publish_memory_append("2026-09-08-from-b")
        machine.append_memory("2026-09-08-from-a")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined

        published = world.published_data_file("memories/memories.jsonl")
        assert "|||||||" not in published, (
            f"a {style} base marker reached the remote:\n{published}"
        )
        assert "<<<<<<<" not in published
        for line in published.splitlines():
            json.loads(line)
        # Still a union of both machines.
        assert "2026-09-08-from-a" in published
        assert "2026-09-08-from-b" in published

    def test_rebase_conflict_on_the_tag_vocabulary_is_unioned(
        self, world: SyncWorld
    ) -> None:
        """The rebase partition must route every MEMORY_APPEND_FILES entry
        to the resolver, not just memories.jsonl (audit L1, behaviourally
        — the twin of the stash-pop case above)."""
        machine = world.add_machine("a")
        (machine.data / "memories" / "tag-vocabulary.txt").write_text(
            "seed-tag\nlocal-tag\n", encoding="utf-8"
        )
        machine.commit_data("local vocabulary", "memories/tag-vocabulary.txt")
        world.publish_data_change(
            "memories/tag-vocabulary.txt", "seed-tag\nremote-tag\n"
        )

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "not fast-forwardable" in combined
        published = world.published_data_file("memories/tag-vocabulary.txt")
        assert "local-tag" in published
        assert "remote-tag" in published
        assert "<<<<<<<" not in published

    def test_an_unresolvable_rebase_leaves_a_gate(self, world: SyncWorld) -> None:
        """Audit M3 (third re-audit): every non-zero exit must leave a gate
        line naming the reason.

        The rebase and push paths all wedge the sync until a human
        intervenes — the same divergence recurs on every run — and all of
        them exited 2 having written nothing but a log line and a stderr
        message the SessionStart hook chain never surfaces.
        """
        machine = world.add_machine("a")
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- local commitment\n", encoding="utf-8"
        )
        machine.commit_data("local inbox edit", "tasks/inbox.md")
        world.publish_data_change("tasks/inbox.md", "# Inbox\n\n- remote item\n")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined

        details = gate_details(world)
        joined = "\n".join(details)
        assert "rebase" in joined or "unsupported" in joined, details
        assert "daily-sync FAILED" in joined or "STOPPED" in joined, details

    def test_a_resolver_that_does_not_clean_stops_the_pull_rebase(
        self, world: SyncWorld
    ) -> None:
        """The rebase path must check the files after the resolver ran.

        "The resolver exited 0 and left the markers there" is the case
        these guards exist for — a diff3 corpus before this branch, a
        future bug after it. Without the check, `git add` stages the
        markers and `git rebase --continue` commits them.
        """
        machine = world.add_machine("a")
        machine.stub_resolver()
        world.publish_memory_append("2026-09-08-theirs")
        machine.append_memory("2026-09-08-ours")
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "conflict markers" in combined
        assert world.published_data_head() == published_before
        assert "<<<<<<<" not in world.published_data_file("memories/memories.jsonl")
        # The refusal must not have left a rebase half-done.
        assert not (machine.data_git_dir / "rebase-merge").exists()

    def test_a_resolver_that_does_not_clean_stops_the_push_retry(
        self, world: SyncWorld
    ) -> None:
        """The same guard on push_with_retry's own rebase resolver, which
        runs when our push is rejected mid-flight."""
        machine = world.add_machine("a")
        machine.stub_resolver()
        machine.append_memory("2026-09-08-ours")

        # Prepare, but do not publish, a conflicting append from elsewhere.
        rival = world.root / "rival-data"
        git("clone", "-q", str(world.data_remote), str(rival), cwd=world.root)
        with (rival / "memories" / "memories.jsonl").open("a", encoding="utf-8") as fh:
            fh.write('{"id": "2026-09-08-rival"}\n')
        git("commit", "-q", "-am", "rival append", cwd=rival)

        # Publish it exactly when our push starts, so the push is rejected
        # and the retry has to rebase.
        marker = world.root / "race-done"
        hook = machine.data_git_dir / "hooks" / "pre-push"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            "cat >/dev/null\n"
            f'[[ -f "{marker}" ]] && exit 0\n'
            f'touch "{marker}"\n'
            "env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_PREFIX \\\n"
            f'    git -C "{rival}" push -q origin main\n'
            "exit 0\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "conflict markers" in combined
        assert "<<<<<<<" not in world.published_data_file("memories/memories.jsonl")

    def test_a_later_failure_is_named_even_after_a_softer_gate(
        self, world: SyncWorld
    ) -> None:
        """Audit M1 (fourth re-audit): `fail` must APPEND its reason.

        Skipping the gate whenever one already existed meant the
        non-fatal withheld-bump gate — which an otherwise healthy run can
        raise — swallowed the reason for a real failure later in the same
        run, leaving the operator reading about a submodule pointer while
        sync-symlinks was what actually broke.
        """
        machine = world.add_machine("a")
        # Raise the soft gate: no origin/main, so the bump is withheld.
        git("config", "--unset", "remote.origin.fetch", cwd=machine.data)
        git("update-ref", "-d", "refs/remotes/origin/main", cwd=machine.data)
        machine.append_memory("2026-09-08-m1-soft")

        result = world.run_sync(machine, PA_TEST_SYMLINKS_RC="1")
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined

        details = gate_details(world)
        assert any("bump was withheld" in d for d in details), details
        assert any("sync-symlinks" in d for d in details), (
            "the real failure was swallowed by the earlier gate: " + repr(details)
        )

    def test_the_gate_reflects_only_the_latest_run(
        self, world: SyncWorld
    ) -> None:
        """Audit C1 (fifth re-audit): the gate is the state of the LAST
        run, each problem once.

        `fail` appended and nothing reset the file at run start, so a
        wedged sync — which fails the same way every session — appended
        the same paragraph again and again and the trigger relayed every
        copy. Three runs, three identical gates.
        """
        machine = world.add_machine("a")
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- local commitment\n", encoding="utf-8"
        )
        machine.commit_data("local inbox edit", "tasks/inbox.md")
        world.publish_data_change("tasks/inbox.md", "# Inbox\n\n- remote item\n")

        for _ in range(3):
            assert world.run_sync(machine).returncode == 2

        details = gate_details(world)
        assert len(details) == len(set(details)), f"duplicated lines: {details}"
        assert len(details) <= 2, details

    def test_only_a_completed_run_clears_the_gate(
        self, world: SyncWorld
    ) -> None:
        """A run that finishes every step, and found nothing wrong,
        clears the wedge a previous run recorded."""
        machine = world.add_machine("a")
        (world.home / ".cache" / "daily-sync-gate").write_text(
            "2\nstale one\nstale two\n", encoding="utf-8"
        )
        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr
        assert world.gate("daily-sync-gate").splitlines() == ["0"]

    def test_lock_contention_leaves_a_standing_gate(
        self, world: SyncWorld
    ) -> None:
        """Audit C1 (sixth re-audit): a run that did no work must not
        clear a wedge.

        The gate was written from the EXIT trap unconditionally, so a run
        that exited at the lock — having touched nothing — wrote "0" over
        a wedge a previous run raised. The trigger reads the gate BEFORE
        starting the sync, so the next session start was silent while the
        tree was still wedged.
        """
        machine = world.add_machine("a")
        wedge = "1\ndaily-sync STOPPED: something a previous run found\n"
        (world.home / ".cache" / "daily-sync-gate").write_text(wedge, encoding="utf-8")

        # Hold the lock, as a concurrent sync or commit-data would.
        lock = machine.pa / "logs" / "daily-sync.lock"
        lock.touch()
        holder = subprocess.Popen(["flock", str(lock), "sleep", "5"])
        try:
            result = world.run_sync(machine)
        finally:
            holder.terminate()
            holder.wait()

        assert result.returncode == 1, result.stdout + result.stderr
        assert "Another daily-sync is running" in result.stdout + result.stderr
        assert world.gate("daily-sync-gate") == wedge, (
            "a contended run cleared a standing wedge"
        )

    @pytest.mark.parametrize(
        ("signal_number", "expected_rc", "name"),
        [(signal.SIGTERM, 143, "SIGTERM"), (signal.SIGINT, 130, "SIGINT")],
    )
    def test_a_signal_leaves_a_standing_gate_and_a_distinct_status(
        self, world: SyncWorld, signal_number: int, expected_rc: int, name: str
    ) -> None:
        """Audit C1: SessionStart's 90 s timeout makes a killed run routine.

        It must not clear a standing wedge, must not exit 1 (which the
        trigger reads as benign lock contention), and must say that it was
        interrupted.
        """
        machine = world.add_machine("a")
        wedge = "1\ndaily-sync STOPPED: something a previous run found\n"
        (world.home / ".cache" / "daily-sync-gate").write_text(wedge, encoding="utf-8")
        # The archiver runs early; hold the run there while we signal it.
        process = world.start_sync(machine, PA_TEST_ARCHIVER_SLEEP="10")
        try:
            for _ in range(200):
                if "agent-mail" in world.calls():
                    break
                time.sleep(0.05)
            process.send_signal(signal_number)
            stdout, stderr = process.communicate(timeout=30)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

        combined = stdout + stderr
        assert process.returncode == expected_rc, f"{process.returncode}\n{combined}"
        assert f"INTERRUPTED by {name}" in combined, combined
        gate = world.gate("daily-sync-gate")
        assert "STOPPED: something a previous run found" in gate, (
            "an interrupted run cleared a standing wedge: " + gate
        )
        assert "INTERRUPTED" in gate, gate

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
        details = gate_details(world)
        # Named by SHA, so the operator can actually recover it.
        stranded_sha = git(
            "rev-parse", "--short=8", "stash@{0}", cwd=machine.data
        ).stdout.strip()
        assert stranded_sha in "\n".join(details), details
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

    def test_a_resolved_conflict_does_not_strand_the_parent_stash(
        self, world: SyncWorld
    ) -> None:
        """Audit M1 (third re-audit): the "do not restore" flag must be
        reset once the conflicted pop is resolved.

        As a one-way latch it survived the resolution, so when the parent
        half aborted later the EXIT handler refused to restore the parent
        stash — leaving settings.json reverted to HEAD, with the operator's
        machine-local edits sitting in a stash.
        """
        machine = world.add_machine("a")
        # A data-half conflict that IS resolved (memories.jsonl, unioned).
        git("checkout", "-q", "--detach", "HEAD", cwd=machine.data)
        machine.append_memory("2026-09-08-m1-ours")
        world.publish_memory_append("2026-09-08-m1-theirs")
        # A parent half that will abort after its stash is pushed: the
        # parent has diverged, so `git pull --ff-only` fails.
        (machine.pa / "settings.json").write_text(
            '{"machine": "local edits"}\n', encoding="utf-8"
        )
        (machine.pa / "local-note.md").write_text("local\n", encoding="utf-8")
        git("add", "--", "local-note.md", cwd=machine.pa)
        git("commit", "-q", "-m", "local parent commit", "--", "local-note.md",
            cwd=machine.pa)
        world.publish_parent_change("settings.json", '{"machine": "remote"}\n')

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "parent pull failed" in combined
        # The data conflict was resolved on the way past.
        assert "conflicts resolved" in combined
        # And the parent stash came back.
        assert "local edits" in (machine.pa / "settings.json").read_text(
            encoding="utf-8"
        ), "the parent stash was stranded and settings.json left reverted"
        assert not git("stash", "list", cwd=machine.pa).stdout.strip()

    def test_an_applied_stash_is_never_called_unrecovered(
        self, world: SyncWorld
    ) -> None:
        """Audit M2 (fifth re-audit): applied work is not lost work.

        A drop that fails after a successful apply left an entry on the
        stack, and the stranded-stash line called it "UNRECOVERED work in
        no commit; recover with stash pop". Popping it would duplicate
        every record in it — the contents are already in the tree and
        published. The advice has to be "delete the entry".
        """
        machine = world.add_machine("a")
        machine.self_dropping_resolver()
        git("checkout", "-q", "--detach", "HEAD", cwd=machine.data)
        machine.append_memory("2026-09-08-m2-ours")
        world.publish_memory_append("2026-09-08-m2-theirs")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined

        published = world.published_data_file("memories/memories.jsonl")
        assert "2026-09-08-m2-ours" in published
        assert "2026-09-08-m2-theirs" in published

        joined = "\n".join(gate_details(world))
        assert "could not drop" in joined, joined
        assert "ALREADY in the working tree" in joined, joined
        assert "UNRECOVERED" not in joined, (
            "applied work was reported as lost, and popping it would "
            "duplicate every record: " + joined
        )
        assert "Do NOT pop" in joined, joined

    def test_a_concurrent_drop_mid_resolve_does_not_strand_our_stash(
        self, world: SyncWorld
    ) -> None:
        """Audit C2 (fourth re-audit): the drop must re-resolve its
        selector, not reuse one from before the apply and the resolver.

        A concurrent session dropping its own stash in that window
        renumbers the stack. The stale selector then named the wrong
        entry: this destroyed a stash holding an untracked file that was
        in no commit anywhere, left our own entry behind, and exited 0.

        Their stash is pushed mid-run (by the archiver) so it sits ABOVE
        ours, and dropped mid-resolve (by the resolver), which is the only
        subprocess running between our apply and our drop.
        """
        machine = world.add_machine("a")
        machine.racing_resolver(drop_selector="stash@{0}")
        git("checkout", "-q", "--detach", "HEAD", cwd=machine.data)
        machine.append_memory("2026-09-08-c2-ours")
        world.publish_memory_append("2026-09-08-c2-theirs")

        result = world.run_sync(
            machine, PA_TEST_ARCHIVER_STASHES="their unfinished note\n"
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined

        remaining = git("stash", "list", cwd=machine.data).stdout.strip()
        assert remaining == "", f"our own stash was left behind: {remaining}"
        published = world.published_data_file("memories/memories.jsonl")
        assert "2026-09-08-c2-ours" in published
        assert "2026-09-08-c2-theirs" in published

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

        assert any("tasks/inbox.md" in d for d in gate_details(world))

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

    def test_markers_without_an_opening_line_are_still_refused(
        self, world: SyncWorld
    ) -> None:
        """Every marker form counts, not just `<<<<<<< `.

        A half-repaired conflict — somebody deleted the opening line and
        stopped — still leaves unparseable JSONL.
        """
        machine = world.add_machine("a")
        machine.memories.write_text(
            '{"id": "ours"}\n=======\n{"id": "theirs"}\n>>>>>>> stash\n',
            encoding="utf-8",
        )
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "conflict markers" in combined
        assert world.published_data_head() == published_before

    def test_a_pipe_run_that_is_not_a_marker_syncs_normally(
        self, world: SyncWorld
    ) -> None:
        """Audit C1 (fourth re-audit): guard and resolver must agree.

        git never emits a bare ``|||||||``, so treating one as a marker
        refused a file the resolver would then decline to touch — the
        operator circling between a gate telling them to run the resolver
        and a resolver saying there is nothing to do. A vocabulary line
        that happens to be a run of pipes is content.
        """
        machine = world.add_machine("a")
        (machine.data / "memories" / "tag-vocabulary.txt").write_text(
            "seed-tag\n|||||||\nanother-tag\n", encoding="utf-8"
        )
        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        published = world.published_data_file("memories/tag-vocabulary.txt")
        assert "|||||||" in published
        assert "another-tag" in published, "the file's tail was swallowed"

    def test_a_lone_separator_is_refused_with_hand_edit_advice(
        self, world: SyncWorld
    ) -> None:
        """Audit C2 (fifth re-audit): guard and resolver, one predicate.

        The guard refused a lone `=======` while the resolver required an
        opener and declined to touch it, so the sync wedged permanently
        behind gate advice to run a resolver that printed "no conflict
        markers — skipping". The refusal must now name the LINES and must
        not send the operator to the resolver.
        """
        machine = world.add_machine("a")
        machine.memories.write_text(
            '{"id": "a"}\n=======\n{"id": "b"}\n', encoding="utf-8"
        )
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert world.published_data_head() == published_before

        joined = "\n".join(gate_details(world))
        assert "line 2" in joined, joined
        assert "Edit those LINES by hand" in joined, joined
        assert "Do NOT run resolve-merge-conflicts.py" in joined, joined

    def test_a_resolvable_conflict_is_sent_to_the_resolver(
        self, world: SyncWorld
    ) -> None:
        """And a well-formed block still gets the advice that works."""
        machine = world.add_machine("a")
        machine.memories.write_text(
            '<<<<<<< HEAD\n{"id": "a"}\n=======\n{"id": "b"}\n>>>>>>> x\n',
            encoding="utf-8",
        )
        assert world.run_sync(machine).returncode == 2
        joined = "\n".join(gate_details(world))
        assert "resolve-merge-conflicts.py" in joined, joined
        assert "Edit those LINES by hand" not in joined, joined

    def test_a_broken_checker_never_produces_a_corpus_verdict(
        self, world: SyncWorld
    ) -> None:
        """Audit C2 (sixth re-audit): only 0/1/3 say anything about the
        corpus.

        A checker that fails any other way — an uncaught exception used to
        exit 1 — was read as "resolvable": the sync gated a traceback as
        marker-shaped lines and parsed its lines as file paths. A failure
        must name itself, and must not send anyone to edit a clean file.
        """
        machine = world.add_machine("a")
        resolver = machine.pa / "scripts" / "resolve-merge-conflicts.py"
        resolver.unlink()
        resolver.write_text(
            "#!/usr/bin/env python3\n"
            'import sys\n'
            'print("Traceback (most recent call last):", file=sys.stderr)\n'
            'print("  File \\"x\\", line 1, in <module>", file=sys.stderr)\n'
            "sys.exit(9)\n",
            encoding="utf-8",
        )
        resolver.chmod(0o755)
        git("commit", "-q", "-am", "broken checker", cwd=machine.pa)

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined

        joined = "\n".join(gate_details(world))
        assert "checker itself failed" in joined, joined
        assert "exit 9" in joined, joined
        assert "Traceback" in joined, "the reason was thrown away: " + joined
        assert "says NOTHING about the file" in joined, joined
        assert "Edit those LINES by hand" not in joined, (
            "a checker failure was reported as a corpus verdict: " + joined
        )

    def test_a_missing_interpreter_never_accuses_the_corpus(
        self, world: SyncWorld
    ) -> None:
        """Audit C3 (sixth re-audit): without the venv there is no verdict.

        Every `--check` failed, and the guard reported that as the corpus
        holding conflict markers — accusing a clean file and sending the
        operator to edit lines that are not there.
        """
        machine = world.add_machine("a")
        (machine.pa / "venv" / "bin" / "python3").unlink()
        machine.append_memory("2026-09-08-c3")
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert world.published_data_head() == published_before

        joined = "\n".join(gate_details(world))
        assert "virtual environment interpreter" in joined, joined
        assert "says NOTHING about memories.jsonl" in joined, joined
        assert "conflict markers" not in joined, (
            "a broken venv was reported as a corpus verdict: " + joined
        )

    def test_markers_in_the_tag_vocabulary_are_refused(
        self, world: SyncWorld
    ) -> None:
        """Every entry of MEMORY_APPEND_FILES is scanned, not just the
        corpus — the vocabulary is append-only and cross-machine too."""
        machine = world.add_machine("a")
        (machine.data / "memories" / "tag-vocabulary.txt").write_text(
            "seed-tag\n<<<<<<< HEAD\nours-tag\n=======\ntheirs-tag\n>>>>>>> x\n",
            encoding="utf-8",
        )
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "tag-vocabulary.txt" in combined
        assert world.published_data_head() == published_before

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
        assert any("memories/memories.jsonl" in d for d in gate_details(world))

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

        assert any("orphaned stash" in d.lower() for d in gate_details(world))
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

        details = gate_details(world)
        assert any("parent-repo stash pop conflicted" in d for d in details), details
        # …and the stash holding the work is named too (second re-audit C1),
        # AFTER the diagnosis: popping into a half-merged tree is the wrong
        # first move, so the reader must meet the diagnosis first (L5).
        assert any("UNRECOVERED" in d for d in details), details
        diagnosis = next(i for i, d in enumerate(details) if "conflicted" in d)
        recovery = next(i for i, d in enumerate(details) if "UNRECOVERED" in d)
        assert diagnosis < recovery, details
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

    def test_a_nonexistent_home_is_refused_not_created(
        self, world: SyncWorld
    ) -> None:
        """Audit L2: `mkdir -p "$HOME/.cache"` would conjure the whole
        path, writing gate files into a tree nothing else reads — on a
        machine whose home is, say, not yet mounted."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-l2")
        absent = world.root / "no-such-home"
        before = world.published_data_head()

        result = world.run_sync(machine, HOME=str(absent))
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "not a directory" in combined
        assert not absent.exists(), "the missing HOME was created anyway"
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

    def test_the_orphan_is_popped_even_with_a_foreign_stash_above_it(
        self, world: SyncWorld
    ) -> None:
        """Recovery must take the entry the detector named, not the top of
        the stack — a concurrent session's stash sits above it here."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-orphaned")
        git("stash", "push", "-q", "-m", "orphaned by a killed run", cwd=machine.data)
        (machine.data / "tasks" / "foreign.md").write_text(
            "their unfinished note\n", encoding="utf-8"
        )
        git("stash", "push", "-u", "-q", "-m", "a concurrent session", "--",
            "tasks/foreign.md", cwd=machine.data)
        # The detector reported the orphan when it was on top; a concurrent
        # push has since put another entry above it.
        result = world.run_sync(machine, PA_TEST_ORPHAN_STASHES="stash@{1}")
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined

        assert "2026-09-08-orphaned" in world.published_data_file(
            "memories/memories.jsonl"
        ), "the orphaned records were not recovered"
        leftovers = git("stash", "list", cwd=machine.data).stdout.strip().splitlines()
        assert len(leftovers) == 1, leftovers
        assert "a concurrent session" in leftovers[0]
        assert not (machine.data / "tasks" / "foreign.md").exists(), (
            "a concurrent session's stash was applied into our tree"
        )

    def test_a_stash_pushed_after_the_report_is_not_the_one_recovered(
        self, world: SyncWorld
    ) -> None:
        """Audit M3 (fourth re-audit): the selectors come from another
        process, so they can go stale between the report and the act.

        The detector reports while the orphan is on top; a concurrent
        session then pushes its own stash, and the reported selector now
        names THEIRS. Recovery must act on the commit the selector meant
        when it was read, not on the position it names by the time the
        apply runs.

        LIMIT: this pins "act on the detector's selector", the shape the
        code had two rounds ago. The remaining difference between
        applying by commit and popping by a freshly re-resolved selector
        is a single-command race that cannot be injected into from a
        stub, and is not covered here.
        """
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-m3-orphan")
        git("stash", "push", "-q", "-m", "orphaned by a killed run", cwd=machine.data)

        result = world.run_sync(
            machine,
            PA_TEST_ORPHAN_STASHES="stash@{0}",
            PA_TEST_DRIFT_STASHES_AFTER="their unfinished note\n",
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined

        assert "2026-09-08-m3-orphan" in world.published_data_file(
            "memories/memories.jsonl"
        ), "the orphaned records were not the ones recovered"
        assert not (machine.data / "tasks" / "racing.md").exists(), (
            "a concurrent session's stash was applied into our tree"
        )
        leftovers = git("stash", "list", cwd=machine.data).stdout.strip().splitlines()
        assert len(leftovers) == 1, leftovers
        assert "a concurrent session" in leftovers[0]

    def test_an_applied_orphan_that_cannot_be_dropped_is_not_called_recovered(
        self, world: SyncWorld
    ) -> None:
        """Applied is not recovered (audit low, fourth re-audit).

        An entry still on the stack is applied again next run and
        duplicates every record in it, so the word has to be earned. The
        drop is made to fail — and only the drop — by taking away write
        access to the stash reflog, which `git stash apply` does not need.
        """
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-undroppable")
        git("stash", "push", "-q", "-m", "orphaned by a killed run", cwd=machine.data)
        reflogs = machine.data_git_dir / "logs" / "refs"
        reflogs.chmod(0o500)
        try:
            result = world.run_sync(machine, PA_TEST_ORPHAN_STASHES="stash@{0}")
        finally:
            reflogs.chmod(0o700)

        combined = result.stdout + result.stderr
        assert "could not drop" in combined, combined
        assert "recovered" not in combined, (
            "reported as recovered while still on the stack: " + combined
        )
        joined = "\n".join(gate_details(world))
        assert "ALREADY in the working tree" in joined, joined
        assert "Do NOT pop" in joined, joined

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
        interpreter.

        LIMITS: a source assertion, and a weak one — any rewrite that
        spells the same path differently (``${HOME}``, an intermediate
        variable) passes it. It cannot be behavioural: the only call site
        sits inside the cc-archives block, which runs only with the
        rpi-shares mount present, and audit S21 forbids a test from having
        one. Treat it as a reminder, not a guarantee.
        """
        source = (Path(__file__).resolve().parent.parent
                  / "scripts" / "daily-sync.sh").read_text(encoding="utf-8")
        assert "$HOME/personal-assistant" not in source, (
            "an interpreter or path is resolved through $HOME instead of $PA_DIR"
        )

    def test_memory_append_list_has_one_source_of_truth(self) -> None:
        """Audit L1: the three conflict partitions must derive from
        MEMORY_APPEND_FILES, not each repeat it as a literal.

        LIMITS: a source assertion, defeated by any rewrite that spells
        the path differently. The behavioural cover is the pair of
        tag-vocabulary tests — one through the stash-pop partition, one
        through the rebase partition — which fail if either stops
        consulting the array. This one only catches the list being
        duplicated again.
        """
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
