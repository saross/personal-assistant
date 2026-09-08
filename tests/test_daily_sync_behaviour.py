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

    def test_a_completed_run_with_findings_replaces_the_old_gate(
        self, world: SyncWorld
    ) -> None:
        """Audit M5 (eighth re-audit): completion is what makes a run's
        view current.

        A run that reaches the end and still has something to say replaces
        what was there; a run that stops early adds to it. With
        sync_run_completed never set, a completed run would carry stale
        lines forward for ever.
        """
        machine = world.add_machine("a")
        (world.home / ".cache" / "daily-sync-gate").write_text(
            "1\ndaily-sync STOPPED: something a previous run found\n",
            encoding="utf-8",
        )
        # A completed run that raises one finding of its own: no
        # origin/main, so the pointer bump is withheld.
        git("config", "--unset", "remote.origin.fetch", cwd=machine.data)
        git("update-ref", "-d", "refs/remotes/origin/main", cwd=machine.data)
        machine.append_memory("2026-09-08-m5")

        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr

        joined = "\n".join(gate_details(world))
        assert "bump was withheld" in joined, joined
        assert "something a previous run found" not in joined, (
            "a completed run carried a stale finding forward: " + joined
        )

    def test_a_completed_clean_run_clears_it(self, world: SyncWorld) -> None:
        """The other half of the same rule."""
        machine = world.add_machine("a")
        (world.home / ".cache" / "daily-sync-gate").write_text(
            "1\ndaily-sync STOPPED: something a previous run found\n",
            encoding="utf-8",
        )
        assert world.run_sync(machine).returncode == 0
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

    def test_a_failed_drop_during_restore_is_not_called_a_conflict(
        self, world: SyncWorld
    ) -> None:
        """The EXIT restore applies, then drops. A failed DROP is not a
        failed apply: the work is in the tree, and saying the restore
        "raised conflicts" sends the operator looking for markers that are
        not there while the real problem — an entry still on the stack —
        goes unnamed.
        """
        machine = world.add_machine("a")
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- unsaved work\n", encoding="utf-8"
        )
        git("remote", "set-url", "origin", str(world.root / "no-such-remote.git"),
            cwd=machine.data)

        result = world.run_sync(machine, PA_TEST_GIT_REFUSE_DROP="1")
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined

        # The edit came back…
        assert "unsaved work" in (
            machine.data / "tasks" / "inbox.md"
        ).read_text(encoding="utf-8")
        # …so this was not a conflicted restore.
        assert "restore raised conflicts" not in combined, combined
        joined = "\n".join(gate_details(world))
        assert "could not drop" in combined, combined
        assert "ALREADY in the working tree" in joined, joined

    def test_a_second_stash_blocked_by_the_first_is_not_condemned(
        self, world: SyncWorld
    ) -> None:
        """Audit C1 (ninth re-audit): classify by what THIS apply changed.

        The ordinary two-stash SIGTERM shape. Stash 1's restore conflicts;
        git then REFUSES stash 2 outright because the index is unmerged,
        leaving its entry untouched — and the whole-repository scan called
        that "conflicted" too, so the gate told the operator to delete the
        only copy of its records.
        """
        machine = world.add_machine("a")
        inbox = machine.data / "tasks" / "inbox.md"
        base = machine.head("data")
        inbox.write_text("# Inbox\n\n- the version on main\n", encoding="utf-8")
        machine.commit_data("main version", "tasks/inbox.md")

        # Stash 1 (branch-switch) will conflict on restore…
        git("checkout", "-q", "--detach", base, cwd=machine.data)
        inbox.write_text("# Inbox\n\n- the version in the stash\n", encoding="utf-8")
        # …and stash 2 carries a record that exists nowhere else.
        git("remote", "set-url", "origin", str(world.root / "no-such-remote.git"),
            cwd=machine.data)

        result = world.run_sync(
            machine, PA_TEST_ARCHIVER_DIRTIES="# Inbox\n\n- written mid-run\n"
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined

        joined = "\n".join(gate_details(world))
        # Exactly one entry produced the markers, and it is named.
        assert joined.count("WITH CONFLICTS") == 1, joined
        assert "blocked" in combined.lower(), combined
        # The second is BLOCKED: intact, its work nowhere else, and the
        # advice is to pop it once the earlier conflict is cleared —
        # never to delete it.
        assert "ALREADY unmerged" in joined, joined
        assert "Resolve the earlier conflict first, then pop these" in joined, joined
        assert "do not delete them" in joined, joined
        # And the blocked entry is not among those called conflicted.
        conflicted_line = next(d for d in gate_details(world) if "WITH CONFLICTS" in d)
        blocked_sha = git(
            "rev-parse", "--short=8", "stash@{0}", cwd=machine.data
        ).stdout.strip()
        assert blocked_sha not in conflicted_line, (
            "the blocked stash was condemned as the source of the markers: "
            + conflicted_line
        )

    def test_a_conflicted_restore_is_never_told_to_pop(
        self, world: SyncWorld
    ) -> None:
        """Audit C-A (eighth re-audit): the exit handler's apply can
        conflict too.

        That branch only logged, so the SHA entered neither list and the
        stranded check called it UNRECOVERED — telling the operator to pop
        a stash whose content was already in the tree as markers. Routine
        under SessionStart's 90 s SIGTERM: the run aborts before its own
        pop, and the handler's restore hits the conflict instead.

        Staged so the restore MUST conflict: the stash is taken against an
        older commit, the branch guard then moves the tree to a main whose
        version of the file differs, and the pull fails before the run
        reaches its own pop.
        """
        machine = world.add_machine("a")
        inbox = machine.data / "tasks" / "inbox.md"
        base = machine.head("data")
        inbox.write_text("# Inbox\n\n- the version on main\n", encoding="utf-8")
        machine.commit_data("main version", "tasks/inbox.md")

        # Detach to the older commit and dirty the same file there.
        git("checkout", "-q", "--detach", base, cwd=machine.data)
        inbox.write_text("# Inbox\n\n- the version in the stash\n", encoding="utf-8")
        # And break the remote, so the run aborts after the branch-switch
        # stash and before its own pop.
        git("remote", "set-url", "origin", str(world.root / "no-such-remote.git"),
            cwd=machine.data)

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "conflicted; its content is in the tree as markers" in combined, combined
        assert "<<<<<<<" in inbox.read_text(encoding="utf-8"), inbox.read_text()

        joined = "\n".join(gate_details(world))
        assert "UNRECOVERED" not in joined, (
            "a tree holding markers was told to pop the stash that put them "
            "there: " + joined
        )
        assert "WITH CONFLICTS" in joined, joined
        assert "Do NOT pop" in joined, joined

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
        assert list((machine.pa / "logs").glob("daily-sync-shrink-*.log"))
        assert world.published_data_head() == published_before, (
            "a shrunk corpus reached origin"
        )

    def test_a_corpus_already_short_at_run_start_never_reaches_origin(
        self, world: SyncWorld
    ) -> None:
        """Audit S23 (tenth re-audit). The detector ran on the auto-sync
        commit and nowhere else — but the append-only block commits
        memories.jsonl FIRST and usually empties the tree, so the
        auto-sync block takes its "nothing to commit" branch and the
        ahead-of-origin push publishes the append-only commit unchecked. A
        truncation already on disk when the run started therefore reached
        origin with the detector switched on, rc 0, and a cleared gate.

        Kills DS-S23: removing `abort_on_jsonl_shrink "append-only commit"`
        from the append-only block.
        """
        machine = world.add_machine("a")
        published_before = world.published_data_head()
        # Something truncated the corpus before the sync ever started —
        # an interrupted rewrite, a bad editor save, a botched recovery.
        machine.memories.write_text("", encoding="utf-8")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 4, combined
        assert "SHRINK DETECTED" in combined, combined
        reports = list((machine.pa / "logs").glob("daily-sync-shrink-*.log"))
        assert reports, "no shrink report was written"
        assert "append-only commit" in reports[0].read_text(encoding="utf-8")
        assert world.published_data_head() == published_before, (
            "a corpus truncated before the run reached origin"
        )
        # And the commit that carried it was undone.
        assert machine.head("data") == published_before, (
            "the shrinking commit is still on the local branch"
        )

    def test_the_undone_commit_leaves_nothing_staged(
        self, world: SyncWorld
    ) -> None:
        """Audit low (eleventh re-audit). `git reset --soft` left the
        truncated corpus STAGED, so the next block's `git add -A` /
        `git commit` re-committed it -- and the operator running
        `git status` was told the shrink was ready to commit. `--mixed`
        keeps the file on disk and unstages it.

        Kills: `git reset --mixed "HEAD~1"` -> `--soft`.
        """
        machine = world.add_machine("a")
        machine.memories.write_text("", encoding="utf-8")

        assert world.run_sync(machine).returncode == 4
        assert not git(
            "diff", "--cached", "--name-only", cwd=machine.data
        ).stdout.strip(), "the truncated corpus was left staged for the next commit"
        # …and it is still on disk for the operator to look at.
        assert machine.memories.read_text(encoding="utf-8") == ""

    def test_a_bulk_rewrite_trailer_still_lets_a_shrink_through(
        self, world: SyncWorld
    ) -> None:
        """The escape hatch has to keep working at the new site too, or a
        legitimate archive run wedges the sync. The trailer is checked on
        the commit that carries the shrink, so a run whose PREVIOUS commit
        carries it is unaffected — this asserts the guard is a guard, not
        a prohibition."""
        machine = world.add_machine("a")
        machine.memories.write_text("", encoding="utf-8")
        machine.commit_data("prune", "memories/memories.jsonl")
        git("commit", "-q", "--amend", "-m",
            "chore(memories): monthly archive\n\nRewrite-Class: bulk\n",
            cwd=machine.data)
        machine.append_memory("2026-09-08-after-the-archive")

        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "2026-09-08-after-the-archive" in world.published_data_file(
            "memories/memories.jsonl"
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

        # The resolver dropped the entry itself, so nothing is left on the
        # stack: the failed drop belongs in the log, and there is nothing
        # for the operator to act on. What must never happen is calling
        # work that is in the tree and published "unrecovered".
        assert "could not drop" in combined, combined
        gate = world.gate("daily-sync-gate")
        assert "UNRECOVERED" not in gate, (
            "applied work was reported as lost, and popping it would "
            "duplicate every record: " + gate
        )
        assert not git("stash", "list", cwd=machine.data).stdout.strip()
        assert "restore raised conflicts" not in combined, combined

    def test_an_undroppable_own_stash_is_classified_as_applied(
        self, world: SyncWorld
    ) -> None:
        """Audit M2 (sixth re-audit): pin the `applied` classification.

        A git that refuses `stash drop` leaves the run having applied its
        own stash and been unable to drop it. That work is in the tree and
        published; calling it UNRECOVERED and advising a pop would apply
        every record in it a second time.
        """
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-m2-applied")
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- forces a stash\n", encoding="utf-8"
        )

        result = world.run_sync(machine, PA_TEST_GIT_REFUSE_DROP="1")
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined

        joined = "\n".join(gate_details(world))
        assert "could not drop" in combined, combined
        assert "ALREADY in the working tree" in joined, joined
        assert "Do NOT pop" in joined, joined
        assert "UNRECOVERED" not in joined, (
            "applied work was classified as lost: " + joined
        )
        # The entry IS still on the stack — that is what makes the gate
        # necessary, and what the operator has to delete.
        assert git("stash", "list", cwd=machine.data).stdout.strip()
        # …and the restore path must not call a failed drop a conflict.
        assert "restore raised conflicts" not in combined, combined

    def test_the_exit_handler_never_re_applies_what_was_applied(
        self, world: SyncWorld
    ) -> None:
        """Audit C2 (seventh re-audit): still-on-the-stack is not unapplied.

        The exit handler re-applied any of the run's stashes still on the
        stack without asking whether the run had already applied them. An
        entry whose DROP failed has its content in the tree — and, by the
        time the handler runs, committed — so applying it again lands the
        same content on top of itself: `UU` markers in the live
        memories.jsonl, with exit 0.
        """
        machine = world.add_machine("a")
        git("checkout", "-q", "--detach", "HEAD", cwd=machine.data)
        machine.append_memory("2026-09-08-c2-ours")
        world.publish_memory_append("2026-09-08-c2-theirs")

        result = world.run_sync(machine, PA_TEST_GIT_REFUSE_DROP="1")
        combined = result.stdout + result.stderr

        corpus = machine.memories.read_text(encoding="utf-8")
        assert "<<<<<<<" not in corpus, (
            "the exit handler applied an already-applied stash onto the "
            "committed tree:\n" + corpus
        )
        for line in corpus.splitlines():
            json.loads(line)
        assert "already applied it" in combined, combined
        # The undroppable entry is reported, and the run says so.
        assert result.returncode != 0 or "could not drop" in combined, combined
        joined = "\n".join(gate_details(world))
        assert "could not drop" in joined or "ALREADY in the working tree" in joined, joined

    def test_a_conflicted_apply_is_not_told_to_pop(
        self, world: SyncWorld
    ) -> None:
        """Audit M1 (sixth re-audit): markers in the tree are a third state.

        A conflicted apply that is then abandoned leaves the stash's
        content in the tree AS MARKERS. Popping it applies the same
        content again on top of them; the advice has to be resolve, then
        delete.
        """
        machine = world.add_machine("a")
        git("checkout", "-q", "--detach", "HEAD", cwd=machine.data)
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- ours\n", encoding="utf-8"
        )
        world.publish_data_change("tasks/inbox.md", "# Inbox\n\n- theirs\n")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined

        joined = "\n".join(gate_details(world))
        assert "WITH CONFLICTS" in joined, joined
        assert "resolve the markers" in joined, joined
        assert "Do NOT pop" in joined, joined
        assert "UNRECOVERED" not in joined, (
            "a conflicted apply was called unrecovered: " + joined
        )

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

    def test_a_marker_beyond_line_nine_is_still_refused(
        self, world: SyncWorld
    ) -> None:
        """Audit M3 (seventh re-audit): the line-number pattern.

        Every marker fixture in the suite put its problem on a
        single-digit line, so narrowing the guard's `^[0-9]+$` to
        `^[0-9]$` passed everything — while a corpus whose only problem
        was on line 13 had its record dropped, and with no records left
        the sync staged and pushed it.
        """
        machine = world.add_machine("a")
        machine.memories.write_text(
            "".join(f'{{"id": "r{n}"}}\n' for n in range(12)) + "=======\n",
            encoding="utf-8",
        )
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert world.published_data_head() == published_before, (
            "a corpus with a marker on line 13 was published"
        )
        joined = "\n".join(gate_details(world))
        assert "line 13" in joined, joined

    def test_an_unreadable_record_refuses_rather_than_proceeds(
        self, world: SyncWorld
    ) -> None:
        """And a record the guard cannot parse is itself a refusal.

        Dropping what it does not understand is how a too-narrow pattern
        turned a marker-laden corpus into a clean verdict.
        """
        machine = world.add_machine("a")
        resolver = machine.pa / "scripts" / "resolve-merge-conflicts.py"
        resolver.unlink()
        resolver.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            'print("memories/memories.jsonl\\tnot-a-number\\tsomething")\n'
            "sys.exit(3)\n",
            encoding="utf-8",
        )
        resolver.chmod(0o755)
        git("commit", "-q", "-am", "checker with an odd record", cwd=machine.pa)
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        assert world.published_data_head() == published_before
        joined = "\n".join(gate_details(world))
        assert "could not read" in joined, joined
        assert "not-a-number" in joined, joined

    def test_a_record_with_no_tabs_refuses_rather_than_proceeds(
        self, world: SyncWorld
    ) -> None:
        """The other unparsed branch: a line with no field separators at
        all. Dropping it silently is how a marker-laden corpus becomes a
        clean verdict."""
        machine = world.add_machine("a")
        resolver = machine.pa / "scripts" / "resolve-merge-conflicts.py"
        resolver.unlink()
        resolver.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            'print("something went wrong but not in a record shape")\n'
            "sys.exit(3)\n",
            encoding="utf-8",
        )
        resolver.chmod(0o755)
        git("commit", "-q", "-am", "checker with a bare line", cwd=machine.pa)
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        assert world.published_data_head() == published_before
        joined = "\n".join(gate_details(world))
        assert "could not read" in joined, joined
        assert "not in a record shape" in joined, joined

    def test_an_empty_path_field_refuses(self, world: SyncWorld) -> None:
        """And a record whose path is empty names nothing to act on."""
        machine = world.add_machine("a")
        resolver = machine.pa / "scripts" / "resolve-merge-conflicts.py"
        resolver.unlink()
        resolver.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            'print("\\t4\\ta problem with no file")\n'
            "sys.exit(3)\n",
            encoding="utf-8",
        )
        resolver.chmod(0o755)
        git("commit", "-q", "-am", "checker with an empty path", cwd=machine.pa)

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert "could not read" in joined, joined

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

    def test_a_marker_laden_corpus_stops_the_run_before_reconciliation(
        self, world: SyncWorld
    ) -> None:
        """Audit M6 (eighth re-audit): the start-of-run corpus guard, on
        its own.

        With a clean index — no unmerged paths, nothing in progress, so
        check_interrupted_state has nothing to say — a corpus holding
        markers must still stop the run before orphan reconciliation,
        with the corpus advice rather than generic orphan advice.
        """
        machine = world.add_machine("a")
        machine.memories.write_text(
            '<<<<<<< HEAD\n{"id": "a"}\n=======\n{"id": "b"}\n>>>>>>> x\n',
            encoding="utf-8",
        )
        machine.commit_data("committed markers", "memories/memories.jsonl")
        assert not git("status", "--porcelain", cwd=machine.data).stdout.strip()
        # An orphan the detector would otherwise be asked to recover.
        published_before = world.published_data_head()

        result = world.run_sync(machine, PA_TEST_ORPHAN_STASHES="stash@{0}")
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert world.published_data_head() == published_before

        joined = "\n".join(gate_details(world))
        assert "conflict blocks" in joined or "marker-shaped" in joined, joined
        assert "ORPHANED STASH" not in joined, (
            "reconciliation ran before the corpus guard: " + joined
        )
        assert "no longer resolves" not in combined, combined

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

    def test_a_hanging_checker_is_bounded_and_reported(
        self, world: SyncWorld
    ) -> None:
        """Audit (low, eighth re-audit): this runs inside a 90 s
        SessionStart budget, so the checker is bounded — and a timeout is
        a checker failure, never a corpus verdict."""
        machine = world.add_machine("a")
        resolver = machine.pa / "scripts" / "resolve-merge-conflicts.py"
        resolver.unlink()
        resolver.write_text(
            "#!/usr/bin/env python3\nimport time\ntime.sleep(600)\n", encoding="utf-8"
        )
        resolver.chmod(0o755)
        git("commit", "-q", "-am", "hanging checker", cwd=machine.pa)
        # Bound the test itself, not just the script.
        world.bin_dir.joinpath("timeout").write_text(
            "#!/usr/bin/env bash\n"
            "# Shorten the script's own 60 s bound so the test is quick.\n"
            'shift\n'
            'exec /usr/bin/timeout 2 "$@"\n',
            encoding="utf-8",
        )
        world.bin_dir.joinpath("timeout").chmod(0o755)

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        joined = "\n".join(gate_details(world))
        assert "checker itself failed" in joined, joined
        assert "124" in joined, joined
        assert "Edit those LINES by hand" not in joined, joined

    def test_the_missing_tool_gate_names_the_tool(self, world: SyncWorld) -> None:
        """Audit L1 (ninth re-audit): a backtick pair inside a
        double-quoted string ran `timeout` as a command, so the gate lost
        the tool's name to its (empty) output."""
        machine = world.add_machine("a")
        missing = world.bin_dir / "timeout"
        missing.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")
        missing.chmod(0o755)

        assert world.run_sync(machine).returncode == 2
        joined = "\n".join(gate_details(world))
        assert "timeout" in joined, (
            "the gate does not name the tool it needs: " + joined
        )
        assert "'timeout' binary" in joined, joined

    def test_a_missing_tool_says_so_rather_than_blaming_the_checker(
        self, world: SyncWorld
    ) -> None:
        """Exit 127 is "could not execute": the tool is missing, which is
        neither a corpus verdict nor something to fix in the checker."""
        machine = world.add_machine("a")
        # A `timeout` on PATH that is not executable at all.
        missing = world.bin_dir / "timeout"
        missing.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")
        missing.chmod(0o755)

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        joined = "\n".join(gate_details(world))
        assert "a required tool is missing" in joined, joined
        assert "127" in joined, joined
        assert "Fix the checker" not in joined, joined

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
    it had no gate line; audit C1 (seventh re-audit) — and then it had
    the data half's diagnosis but not its distinctions."""

    def test_a_conflicted_parent_apply_is_not_told_to_pop(
        self, world: SyncWorld
    ) -> None:
        """Audit C1 (seventh re-audit): the third state, on both halves.

        A conflicted apply put the stash's content in the tree as
        markers. Telling the operator to pop it — as the parent half did,
        and as the old test asserted — applies the same content again on
        top of them.
        """
        machine = world.add_machine("a")
        world.publish_parent_change("settings.json", '{"from": "the other machine"}\n')
        (machine.pa / "settings.json").write_text('{"from": "here"}\n', encoding="utf-8")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert "raised conflicts" in combined

        details = gate_details(world)
        joined = "\n".join(details)
        assert "in the tree as conflict markers" in joined, joined
        assert "DELETE the entry" in joined, joined
        assert "Do NOT pop" in joined, joined
        assert "UNRECOVERED" not in joined, (
            "a conflicted parent apply was called unrecovered: " + joined
        )
        assert "WITH CONFLICTS" in joined, "the third state was not recorded: " + joined
        # The diagnosis precedes the recovery advice (audit L5).
        diagnosis = next(i for i, d in enumerate(details) if "conflicted" in d)
        recovery = next(i for i, d in enumerate(details) if "WITH CONFLICTS" in d)
        assert diagnosis < recovery, details
        # The stash git preserved on a conflicted apply is still there.
        assert git("stash", "list", cwd=machine.pa).stdout.strip()

    def test_a_refused_parent_apply_is_told_to_pop(self, world: SyncWorld) -> None:
        """And the opposite state gets the opposite advice.

        A REFUSED apply leaves the tree untouched and the work only in
        the stash, so popping it — once whatever collides is cleared — is
        exactly right. The parent half made no distinction and gated
        "conflict markers are preserved" over a clean tree.
        """
        machine = world.add_machine("a")
        (machine.pa / "settings.json").write_text('{"from": "here"}\n', encoding="utf-8")

        result = world.run_sync(
            machine, PA_TEST_GIT_REFUSE_APPLY_IN=str(machine.pa)
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined

        joined = "\n".join(gate_details(world))
        assert "REFUSED" in joined, joined
        assert "then pop it" in joined, joined
        assert "in the tree as conflict markers" not in joined, (
            "a refused apply was described as leaving markers: " + joined
        )
        assert "WITH CONFLICTS" not in joined, joined


class TestAnInterruptedPredecessor:
    """A run killed mid-operation leaves state the next run must NAME
    rather than trip over three steps later — and must describe
    accurately enough that acting on it is safe (audit M1-M4 and C-B)."""

    def _git_dir(self, machine: object, repo: str) -> Path:
        """The real git directory of either repository."""
        return machine.data_git_dir if repo == "data" else machine.pa / ".git"

    def test_an_unfinished_rebase_with_conflicts_offers_both_ways_out(
        self, world: SyncWorld
    ) -> None:
        """Unresolved paths: finish it, or throw it away — the operator
        chooses, and the run names both commands."""
        machine = world.add_machine("a")
        (machine.data_git_dir / "rebase-merge").mkdir()
        machine.memories.write_text('{"id": "a"}\n', encoding="utf-8")
        machine.commit_data("base", "memories/memories.jsonl")
        git("stash", "push", "-q", "-m", "x", cwd=machine.data, check=False)
        # Force an unmerged path alongside the rebase directory.
        git("update-index", "--index-info", cwd=machine.data, check=False)

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert "rebase" in joined, joined
        assert "rebase --continue" in joined or "Complete it" in joined, joined

    def test_a_resolved_operation_is_told_to_continue_not_abort(
        self, world: SyncWorld
    ) -> None:
        """Audit M3 (eighth re-audit): an operation in progress with
        NOTHING unresolved is a resolution waiting to be committed.
        Aborting it discards work somebody has already done."""
        machine = world.add_machine("a")
        (machine.data_git_dir / "rebase-merge").mkdir()

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert "nothing left unresolved" in joined, joined
        assert "rebase --continue" in joined, joined
        assert "Do NOT abort" in joined, joined

    def test_an_interrupted_git_am_is_not_told_to_abort_a_rebase(
        self, world: SyncWorld
    ) -> None:
        """Audit M2 (eighth re-audit): rebase-apply is `git am`'s
        directory too, and `git rebase --abort` is not the way out of a
        half-applied mailbox."""
        machine = world.add_machine("a")
        (machine.data_git_dir / "rebase-apply").mkdir()
        (machine.data_git_dir / "rebase-apply" / "applying").write_text("", encoding="utf-8")

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert "git am" in joined, joined
        assert "am --continue" in joined or "am --abort" in joined, joined
        assert "rebase --abort" not in joined, joined

    def test_a_bare_rebase_apply_is_still_a_rebase(self, world: SyncWorld) -> None:
        """Without `applying` it is an interactive-less rebase, not am."""
        machine = world.add_machine("a")
        (machine.data_git_dir / "rebase-apply").mkdir()

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert "rebase" in joined, joined
        assert "git am" not in joined, joined

    @pytest.mark.parametrize(
        ("head_file", "operation"),
        [("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert")],
    )
    def test_cherry_pick_and_revert_get_their_own_commands(
        self, world: SyncWorld, head_file: str, operation: str
    ) -> None:
        """Audit M4 (eighth re-audit): each operation has its own way out,
        and `git merge --abort` is not it."""
        machine = world.add_machine("a")
        (machine.data_git_dir / head_file).write_text(
            machine.head("data") + "\n", encoding="utf-8"
        )

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert f"{operation} --continue" in joined or f"{operation} --abort" in joined, joined

    def test_an_unfinished_merge_is_told_to_commit(self, world: SyncWorld) -> None:
        """A merge finishes with `git commit`, not `merge --continue`."""
        machine = world.add_machine("a")
        (machine.data_git_dir / "MERGE_HEAD").write_text(
            machine.head("data") + "\n", encoding="utf-8"
        )

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert "merge is in progress" in joined, joined
        # , not `merge --continue`.
        assert " commit." in joined, joined
        assert "merge --continue" not in joined, joined

    @pytest.mark.parametrize("repo", ["data", "parent"])
    def test_a_bisect_is_named_and_head_is_left_alone(
        self, world: SyncWorld, repo: str
    ) -> None:
        """Audit M2 (ninth re-audit): a bisect was invisible, and the
        branch guard then checked out main in the middle of one —
        destroying somebody's session, exit 0."""
        machine = world.add_machine("a")
        git_dir = machine.data_git_dir if repo == "data" else machine.pa / ".git"
        head_before = machine.head(repo)
        (git_dir / "BISECT_LOG").write_text("# bisect log\n", encoding="utf-8")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        joined = "\n".join(gate_details(world))
        assert "bisect is in progress" in joined, joined
        assert "bisect reset" in joined, joined
        assert "will not move HEAD" in joined, joined
        assert machine.head(repo) == head_before, "HEAD was moved mid-bisect"

    def test_the_data_half_runs_despite_a_parent_mid_operation(
        self, world: SyncWorld
    ) -> None:
        """Audit M3 (ninth re-audit): each check before ITS OWN half.

        A human mid-rebase in the parent is no reason to stop memory sync
        — that is the half that loses data when it does not run.
        """
        machine = world.add_machine("a")
        (machine.pa / ".git" / "rebase-merge").mkdir()
        machine.append_memory("2026-09-08-m3")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        # The parent is still named…
        joined = "\n".join(gate_details(world))
        assert "parent repo" in joined, joined
        # …but the memory records reached origin first.
        assert "2026-09-08-m3" in world.published_data_file(
            "memories/memories.jsonl"
        ), "the data half was blocked by a parent-repo operation"

    def test_the_parent_repository_is_checked_too(self, world: SyncWorld) -> None:
        """Audit M1 (eighth re-audit): a rebase left in the PARENT went
        entirely unnoticed — the run exited 0 and cleared the gate."""
        machine = world.add_machine("a")
        (machine.pa / ".git" / "rebase-merge").mkdir()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        joined = "\n".join(gate_details(world))
        assert "parent repo" in joined, joined
        assert "rebase" in joined, joined

    def test_unmerged_paths_of_unknown_origin_name_no_stash_to_delete(
        self, world: SyncWorld
    ) -> None:
        """Audit C-B (eighth re-audit): never advise deleting a stash the
        run cannot prove put those markers there.

        The blanket "DELETE any stash entry this left behind" was advice
        to destroy the only copy of an orphan — given before
        reconciliation had so much as listed what was on the stack.
        """
        machine = world.add_machine("a")
        # An orphan holding the only copy of a record…
        machine.append_memory("2026-09-08-only-copy")
        git("stash", "push", "-q", "-m", "an orphan nobody has recovered",
            cwd=machine.data)
        # …and unmerged paths from something else entirely.
        machine.memories.write_text('{"id": "committed"}\n', encoding="utf-8")
        machine.commit_data("diverge", "memories/memories.jsonl")
        git("stash", "apply", "stash@{0}", cwd=machine.data, check=False)
        assert "<<<<<<<" in machine.memories.read_text(encoding="utf-8")

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert "cannot identify" in joined, joined
        assert "Do NOT touch any stash entry" in joined, joined
        assert "DELETE" not in joined.upper() or "do not touch" in joined.lower(), joined
        # The entries are listed in full so nothing is deleted blind.
        assert "an orphan nobody has recovered" in joined, joined

    def test_a_stash_this_run_recorded_is_named_in_full(
        self, world: SyncWorld
    ) -> None:
        """And when a PREVIOUS run recorded conflicting on a stash, that
        one may be named — by SHA, selector, and message."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-recorded")
        git("stash", "push", "-q", "-m", "recorded as conflicted", cwd=machine.data)
        sha = git("rev-parse", "stash@{0}", cwd=machine.data).stdout.strip()
        machine.memories.write_text('{"id": "committed"}\n', encoding="utf-8")
        machine.commit_data("diverge", "memories/memories.jsonl")
        git("stash", "apply", "stash@{0}", cwd=machine.data, check=False)
        (world.home / ".cache" / "daily-sync-stash-state").write_text(
            f"{machine.data}\t{sha}\tconflicted\tmemories/memories.jsonl\n",
            encoding="utf-8",
        )

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert sha[:8] in joined, joined
        assert "stash@{0}" in joined, joined
        assert "recorded as conflicted" in joined, joined
        assert "delete that entry" in joined, joined
        assert "Do NOT pop" in joined, joined

    def test_a_stale_row_is_not_blamed_for_an_unrelated_conflict(
        self, world: SyncWorld
    ) -> None:
        """Audit C2 (ninth re-audit): attribution needs a path match.

        A row about a stash that conflicted on one file says nothing about
        a fresh conflict in another. Blaming it invites deleting work that
        has nothing to do with the markers on screen.
        """
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-unrelated")
        git("stash", "push", "-q", "-m", "conflicted on something else",
            cwd=machine.data)
        sha = git("rev-parse", "stash@{0}", cwd=machine.data).stdout.strip()
        # The row claims it left markers in a file that is fine now.
        (world.home / ".cache" / "daily-sync-stash-state").write_text(
            f"{machine.data}\t{sha}\tconflicted\ttasks/inbox.md\n", encoding="utf-8"
        )
        # The actual conflict is somewhere else entirely.
        machine.memories.write_text('{"id": "committed"}\n', encoding="utf-8")
        machine.commit_data("diverge", "memories/memories.jsonl")
        git("stash", "apply", sha, cwd=machine.data, check=False)
        assert "<<<<<<<" in machine.memories.read_text(encoding="utf-8")

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert "cannot identify" in joined, joined
        assert sha[:8] not in joined.split("on the stack right now")[0], (
            "a stale row was blamed for an unrelated conflict: " + joined
        )

    def test_a_dropped_entry_is_not_named(self, world: SyncWorld) -> None:
        """A row about an entry that is no longer on the stack names
        nothing: the stash is gone, so it is the source of nothing — and
        naming it sends the operator hunting for something that is not
        there.

        Staged as an abandoned stash apply (no MERGE_HEAD), so the
        attribution branch is the one that runs.
        """
        machine = world.add_machine("a")
        # A live stash, which will produce the actual conflict…
        machine.append_memory("2026-09-08-live")
        git("stash", "push", "-q", "-m", "the live one", cwd=machine.data)
        # …and one that is dropped before the run, on top of it.
        machine.append_memory("2026-09-08-gone")
        git("stash", "push", "-q", "-m", "since dropped", cwd=machine.data)
        sha = git("rev-parse", "stash@{0}", cwd=machine.data).stdout.strip()
        git("stash", "drop", "-q", "stash@{0}", cwd=machine.data)
        assert sha not in git(
            "stash", "list", "--format=%H", cwd=machine.data
        ).stdout.split()

        machine.memories.write_text('{"id": "committed"}\n', encoding="utf-8")
        machine.commit_data("diverge", "memories/memories.jsonl")
        git("stash", "apply", "stash@{0}", cwd=machine.data, check=False)
        assert "<<<<<<<" in machine.memories.read_text(encoding="utf-8")
        (world.home / ".cache" / "daily-sync-stash-state").write_text(
            f"{machine.data}\t{sha}\tconflicted\tmemories/memories.jsonl\n",
            encoding="utf-8",
        )

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert sha[:8] not in joined.split("on the stack right now")[0], (
            "a stash that is no longer on the stack was named as the source "
            "of these markers: " + joined
        )

    def test_an_applied_row_is_never_a_marker_source(
        self, world: SyncWorld
    ) -> None:
        """Applied rows exist to say "already in your tree", never "these
        markers are its content" — they carry no paths for that reason."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-applied-row")
        git("stash", "push", "-q", "-m", "applied last run", cwd=machine.data)
        sha = git("rev-parse", "stash@{0}", cwd=machine.data).stdout.strip()
        (world.home / ".cache" / "daily-sync-stash-state").write_text(
            f"{machine.data}\t{sha}\tapplied\tmemories/memories.jsonl\n",
            encoding="utf-8",
        )
        machine.memories.write_text('{"id": "committed"}\n', encoding="utf-8")
        machine.commit_data("diverge", "memories/memories.jsonl")
        git("stash", "apply", sha, cwd=machine.data, check=False)

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert "cannot identify" in joined, (
            "an applied row was treated as a marker source: " + joined
        )

    def test_a_real_conflict_writes_a_row_with_its_paths(
        self, world: SyncWorld
    ) -> None:
        """The write side, driven by a run that actually conflicts."""
        machine = world.add_machine("a")
        inbox = machine.data / "tasks" / "inbox.md"
        base = machine.head("data")
        inbox.write_text("# Inbox\n\n- on main\n", encoding="utf-8")
        machine.commit_data("main version", "tasks/inbox.md")
        git("checkout", "-q", "--detach", base, cwd=machine.data)
        inbox.write_text("# Inbox\n\n- in the stash\n", encoding="utf-8")
        git("remote", "set-url", "origin", str(world.root / "no-such-remote.git"),
            cwd=machine.data)

        assert world.run_sync(machine).returncode == 2
        sidecar = (world.home / ".cache" / "daily-sync-stash-state").read_text(
            encoding="utf-8"
        )
        rows = [r for r in sidecar.splitlines() if "conflicted" in r]
        assert len(rows) == 1, sidecar
        repo, sha, state, paths = rows[0].split("\t")
        assert repo == str(machine.data)
        assert state == "conflicted"
        assert paths == "tasks/inbox.md", rows[0]
        assert git("rev-parse", "stash@{0}", cwd=machine.data).stdout.strip() == sha

    def test_a_completed_clean_run_clears_the_sidecar(
        self, world: SyncWorld
    ) -> None:
        """Every non-dry run rewrites it, so nothing survives a clean one."""
        sidecar = world.home / ".cache" / "daily-sync-stash-state"
        sidecar.write_text(
            "/somewhere\tdeadbeef\tconflicted\tmemories/memories.jsonl\n",
            encoding="utf-8",
        )
        machine = world.add_machine("a")
        assert world.run_sync(machine).returncode == 0
        assert sidecar.read_text(encoding="utf-8") == "", sidecar.read_text()

    def test_a_later_word_about_a_stash_supersedes_the_earlier_one(
        self, world: SyncWorld
    ) -> None:
        """Audit M1 (ninth re-audit): contradictory advice must not stand
        side by side.

        A failing run appends, so an earlier run's "pop it" and a later
        run's "delete it" — about the same stash — were both on screen at
        once. The later word wins.
        """
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-supersede")
        git("stash", "push", "-q", "-m", "recorded as conflicted", cwd=machine.data)
        sha = git("rev-parse", "stash@{0}", cwd=machine.data).stdout.strip()
        machine.memories.write_text('{"id": "committed"}\n', encoding="utf-8")
        machine.commit_data("diverge", "memories/memories.jsonl")
        git("stash", "apply", "stash@{0}", cwd=machine.data, check=False)
        (world.home / ".cache" / "daily-sync-stash-state").write_text(
            f"{machine.data}\t{sha}\tconflicted\tmemories/memories.jsonl\n",
            encoding="utf-8",
        )
        # An earlier run's advice about the very same stash.
        (world.home / ".cache" / "daily-sync-gate").write_text(
            f"1\nan earlier run said: {sha[:8]} holds unrecovered work — pop it\n",
            encoding="utf-8",
        )

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert "an earlier run said" not in joined, (
            "an earlier run's contradictory advice about the same stash "
            "survived: " + joined
        )
        assert sha[:8] in joined, joined
        assert "delete that entry" in joined, joined

    def test_a_failing_run_keeps_the_previous_interruption_line(
        self, world: SyncWorld
    ) -> None:
        """Audit M1 (seventh re-audit): a run that fails has not
        established that whatever a previous run recorded is resolved."""
        machine = world.add_machine("a")
        (world.home / ".cache" / "daily-sync-gate").write_text(
            "1\ndaily-sync was INTERRUPTED by SIGTERM before it finished.\n",
            encoding="utf-8",
        )
        (machine.data_git_dir / "rebase-merge").mkdir()

        assert world.run_sync(machine).returncode == 2
        joined = "\n".join(gate_details(world))
        assert "INTERRUPTED by SIGTERM" in joined, (
            "the previous run's only record was erased: " + joined
        )
        assert "rebase is in progress" in joined, joined


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


# ============================================================================
# A stash that applied only PART of itself (audit S27)
# ============================================================================


class TestPartiallyAppliedStash:
    """``git stash apply`` restores the untracked tree AFTER merging the
    tracked one, and abandons the whole untracked half the moment one of
    its paths already exists. One command therefore writes conflict
    markers for a tracked path and leaves an untracked file unrestored —
    and the untracked file is in no commit, no index and no working tree,
    so the entry holds its only copy. The conflicted path resolved the
    markers and dropped the entry, with rc 0 and a clean gate."""

    def _stage(self, world: SyncWorld, *, diverge_corpus: bool) -> tuple[object, str]:
        """
        Build the shape: a detached HEAD holding a local append and an
        untracked report, against an origin that published a report of the
        same name (and, optionally, a divergent append).

        Returns the machine and the untracked path.
        """
        machine = world.add_machine("a")
        report = "reports/field-notes.md"
        if diverge_corpus:
            world.publish_memory_append("2026-09-08-from-elsewhere")
        world.publish_data_change(report, "the other machine's copy\n")

        base = machine.head("data")
        machine.append_memory("2026-09-08-local-append")
        target = machine.data / report
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("the only copy of this exists in the stash\n",
                          encoding="utf-8")
        # Detached HEAD makes the branch guard stash first, untracked
        # files included — the ordinary shape after `submodule update`.
        git("checkout", "-q", "--detach", base, cwd=machine.data)
        return machine, report

    def test_an_untracked_file_survives_a_conflicted_apply(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-S27: with the drop guard removed, the resolver cleans
        the markers, ``drop_applied_stash`` drops the entry, and the only
        copy of the report is gone with rc 0."""
        machine, report = self._stage(world, diverge_corpus=True)
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined

        # The entry is still on the stack, and still holds the file.
        listed = git("stash", "list", "--format=%H", cwd=machine.data).stdout.split()
        assert listed, "the entry that holds the only copy was dropped"
        sha = listed[0]
        kept = git("show", f"{sha}^3:{report}", cwd=machine.data).stdout
        assert kept == "the only copy of this exists in the stash\n", kept

        joined = "\n".join(gate_details(world))
        assert report in joined, ("the gate does not name the file that did "
                                  "not come back: " + joined)
        # audit C1 (eleventh re-audit): the tree HOLDS the other machine's
        # copy, tracked at HEAD after the pull. Saying the file exists
        # "ONLY inside the entry" and offering a bare checkout is advice to
        # overwrite it, stage it, and publish it on the next run.
        assert "DIFFERENT copy" in joined, joined
        assert "ONLY inside" not in joined, joined
        assert f"checkout {sha}^3" not in joined, (
            "the gate advised a command that overwrites a file present in "
            "the worktree: " + joined
        )
        assert f"show {sha}^3" in joined, joined
        assert "merge by hand" in joined, joined
        assert "stash drop <ref>" in joined, joined
        # The other machine's copy is untouched and still what is tracked.
        assert (machine.data / report).read_text(encoding="utf-8") == (
            "the other machine's copy\n"
        )
        assert world.published_data_head() == published_before

    def test_a_clean_merge_with_an_untracked_collision_is_not_called_refused(
        self, world: SyncWorld
    ) -> None:
        """The same failure without markers: the tracked half merges
        cleanly and git still gives up on the untracked half. That was
        classified ``refused`` — "the tree was left untouched and the work
        is only in the stash" — about a tree it had just written to, with
        advice (pop it) that git refuses again for the same reason."""
        machine, report = self._stage(world, diverge_corpus=False)

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined

        joined = "\n".join(gate_details(world))
        assert "only PARTLY" in joined, joined
        assert report in joined, joined
        assert "was refused" not in joined, (
            "a half-applied entry was reported as a refusal that left the "
            "tree untouched: " + joined
        )
        assert "left untouched" not in joined, joined
        # And the local append really is in the tree, which is why
        # "untouched" was false.
        assert "2026-09-08-local-append" in machine.memories.read_text(
            encoding="utf-8"
        )

    def test_the_partial_warning_survives_the_next_run(
        self, world: SyncWorld
    ) -> None:
        """A gate line lives one run: the next run replaces it, and a run
        with nothing to say clears it. The file would still be in no
        commit and no tree. Every later run re-reads the sidecar and says
        so again, until the file comes back."""
        machine = world.add_machine("a")
        report = "reports/only-in-the-stash.md"
        target = machine.data / report
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("nowhere else\n", encoding="utf-8")
        git("stash", "push", "-u", "-q", "-m", "a previous run", cwd=machine.data)
        sha = git("rev-parse", "stash@{0}", cwd=machine.data).stdout.strip()
        assert not target.exists(), "the fixture did not model an unrestored file"
        (world.home / ".cache" / "daily-sync-stash-state").write_text(
            f"{machine.data}\t{sha}\tpartial\t{report}\n", encoding="utf-8"
        )

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        # Nothing failed — the sync ran — but the warning still stands.
        assert result.returncode == 0, combined
        joined = "\n".join(gate_details(world))
        assert report in joined, joined
        assert f"checkout {sha}^3" in joined, joined
        assert git("stash", "list", cwd=machine.data).stdout.strip(), (
            "the entry holding the only copy was dropped by a clean run"
        )

    def test_a_recovered_file_stops_the_nagging(self, world: SyncWorld) -> None:
        """The other side of it: once the file is back, the entry holds
        nothing unique and the gate must fall silent — or the operator
        learns to ignore it."""
        machine = world.add_machine("a")
        report = "reports/only-in-the-stash.md"
        target = machine.data / report
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("nowhere else\n", encoding="utf-8")
        git("stash", "push", "-u", "-q", "-m", "a previous run", cwd=machine.data)
        sha = git("rev-parse", "stash@{0}", cwd=machine.data).stdout.strip()
        (world.home / ".cache" / "daily-sync-stash-state").write_text(
            f"{machine.data}\t{sha}\tpartial\t{report}\n", encoding="utf-8"
        )
        # The operator recovers it, byte for byte. `stash push -u` took
        # the directory away with the file, so it has to come back too.
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("nowhere else\n", encoding="utf-8")
        git("add", "--", report, cwd=machine.data)
        machine.commit_data("recovered by hand", report)

        assert world.run_sync(machine).returncode == 0
        assert world.gate("daily-sync-gate").strip() == "0", world.gate(
            "daily-sync-gate"
        )


# ============================================================================
# The sidecar outlives a run that only read it (audit M1, tenth re-audit)
# ============================================================================


class TestSidecarLifetime:
    """``render_on_early_exit`` rewrote the sidecar from arrays that did
    not exist yet, so the very run that READ it — check_interrupted_state,
    naming whose markers a half-merged tree holds — truncated it on the
    way out and the next run decayed to the generic wording."""

    def _stage_recorded_conflict(self, world: SyncWorld) -> tuple[object, str]:
        """A live stash, a real unmerged path, and a sidecar row tying
        the two together — the state a conflicted run leaves behind."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-recorded")
        git("stash", "push", "-q", "-m", "recorded as conflicted", cwd=machine.data)
        sha = git("rev-parse", "stash@{0}", cwd=machine.data).stdout.strip()
        machine.memories.write_text('{"id": "committed"}\n', encoding="utf-8")
        machine.commit_data("diverge", "memories/memories.jsonl")
        git("stash", "apply", "stash@{0}", cwd=machine.data, check=False)
        (world.home / ".cache" / "daily-sync-stash-state").write_text(
            f"{machine.data}\t{sha}\tconflicted\tmemories/memories.jsonl\n",
            encoding="utf-8",
        )
        return machine, sha

    def test_a_run_that_only_read_the_sidecar_does_not_wipe_it(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-S28-M1: restoring `write_stash_state` to
        `render_on_early_exit` empties the file on the way out of run 1,
        and run 2 can no longer name the stash."""
        machine, sha = self._stage_recorded_conflict(world)
        sidecar = world.home / ".cache" / "daily-sync-stash-state"

        first = world.run_sync(machine)
        assert first.returncode == 2, first.stdout + first.stderr
        joined = "\n".join(gate_details(world))
        assert "these markers ARE that stash's content" in joined, joined
        assert sidecar.read_text(encoding="utf-8").strip(), (
            "the run that read the sidecar truncated it on the way out"
        )

        # Nothing has changed on disk; the second run must say the same.
        second = world.run_sync(machine)
        assert second.returncode == 2, second.stdout + second.stderr
        again = "\n".join(gate_details(world))
        assert "these markers ARE that stash's content" in again, (
            "attribution decayed to the generic wording on the second run: "
            + again
        )
        assert sha[:8] in again, again


class TestGateSupersessionRoundTrip:
    """Three runs, verbatim. A run that can attribute nothing LISTS every
    entry on the stack — and the SHAs were harvested from the whole line,
    so that listing superseded every still-true, specific line about every
    entry it mentioned."""

    def test_a_blocked_stashs_fact_survives_to_the_third_run(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-S28-M2 (and DS-S28-M1 with it).

        Run 1 conflicts on one stash and is BLOCKED on a second, whose
        work is nowhere else. Runs 2 and 3 find the half-merged tree. With
        the sidecar wiped by run 2's early exit, run 3 fell through to the
        generic listing — which named the blocked stash, and so erased the
        one line saying its records exist nowhere else.
        """
        machine = world.add_machine("a")
        inbox = machine.data / "tasks" / "inbox.md"
        base = machine.head("data")
        inbox.write_text("# Inbox\n\n- the version on main\n", encoding="utf-8")
        machine.commit_data("main version", "tasks/inbox.md")
        git("checkout", "-q", "--detach", base, cwd=machine.data)
        inbox.write_text("# Inbox\n\n- the version in the stash\n", encoding="utf-8")
        git("remote", "set-url", "origin", str(world.root / "no-such-remote.git"),
            cwd=machine.data)

        first = world.run_sync(
            machine, PA_TEST_ARCHIVER_DIRTIES="# Inbox\n\n- written mid-run\n"
        )
        assert first.returncode == 2, first.stdout + first.stderr
        joined = "\n".join(gate_details(world))
        assert "ALREADY unmerged" in joined, joined
        blocked_sha = git(
            "rev-parse", "--short=8", "stash@{0}", cwd=machine.data
        ).stdout.strip()

        for run in (2, 3):
            result = world.run_sync(machine)
            assert result.returncode == 2, (run, result.stdout + result.stderr)

        final = "\n".join(gate_details(world))
        assert "ALREADY unmerged" in final, (
            "a run that could attribute nothing erased the one line saying "
            "the blocked stash's work is nowhere else: " + final
        )
        assert blocked_sha in final, final
        assert "their work is\nnowhere else" in final or "nowhere else" in final, final


# ============================================================================
# The sidecar file itself (audit C2, ninth re-audit — kept honest)
# ============================================================================


class TestSidecarIsNeverStale:
    """A sidecar that cannot be truncated must not keep serving the
    previous run's rows: a stale row is an instruction to delete an
    entry."""

    def test_an_unwritable_sidecar_is_unlinked_rather_than_left_stale(
        self, world: SyncWorld
    ) -> None:
        """Kills: dropping the `rm -f "$STASH_STATE_FILE"` before the
        truncating write. With only `: > file`, a read-only sidecar
        survives untouched and every later run reads a row about a stash
        that conflicted weeks ago."""
        machine = world.add_machine("a")
        sidecar = world.home / ".cache" / "daily-sync-stash-state"
        sidecar.write_text(
            "/gone\tdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef\tconflicted\t"
            "memories/memories.jsonl\n",
            encoding="utf-8",
        )
        sidecar.chmod(0o444)

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "deadbeef" not in sidecar.read_text(encoding="utf-8"), (
            "a read-only sidecar kept serving the previous run's row"
        )
        assert "could not write" not in combined, combined


# ============================================================================
# A bisect is never told to "finish it" (audit L4, tenth re-audit)
# ============================================================================


class TestBisectWithUnmergedPaths:
    """A bisect holding unmerged paths took the generic arm, which offers
    `$continue_cmd` — set, for a bisect, to `git bisect reset`. "Resolve
    them and finish it (git bisect reset)" throws the bisect away."""

    def test_a_bisect_with_unmerged_paths_is_still_named_a_bisect(
        self, world: SyncWorld
    ) -> None:
        """Kills: `continue_cmd="git -C $repo bisect reset"` in the bisect
        arm, together with the ordering that let the unmerged branch run
        for a bisect at all."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-bisect")
        git("stash", "push", "-q", "-m", "a stash", cwd=machine.data)
        machine.memories.write_text('{"id": "committed"}\n', encoding="utf-8")
        machine.commit_data("diverge", "memories/memories.jsonl")
        git("stash", "apply", "stash@{0}", cwd=machine.data, check=False)
        assert "<<<<<<<" in machine.memories.read_text(encoding="utf-8")
        head_before = machine.head("data")
        (machine.data_git_dir / "BISECT_LOG").write_text("# bisect log\n",
                                                         encoding="utf-8")

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert "bisect is in progress" in joined, joined
        assert "will not move HEAD" in joined, joined
        assert "finish it" not in joined, (
            "a bisect was offered a --continue it does not have: " + joined
        )
        assert machine.head("data") == head_before


# ============================================================================
# The parent check runs before the parent branch guard
# ============================================================================


class TestParentCheckPrecedesTheBranchGuard:
    """``check_interrupted_state`` on the parent exists to stop the branch
    guard moving HEAD out of somebody's working state. Below the guard it
    would be a report written after the damage."""

    def test_a_parent_bisect_survives_a_feature_branch(
        self, world: SyncWorld
    ) -> None:
        """Kills: moving `check_interrupted_state "$PA_DIR"` below the
        parent branch guard — `git checkout main` then runs mid-bisect and
        the branch the human was on is gone."""
        machine = world.add_machine("a")
        git("checkout", "-q", "-b", "feature", cwd=machine.pa)
        (machine.pa / ".git" / "BISECT_LOG").write_text("# bisect log\n",
                                                        encoding="utf-8")

        result = world.run_sync(machine)
        assert result.returncode == 2, result.stdout + result.stderr
        joined = "\n".join(gate_details(world))
        assert "bisect is in progress" in joined, joined
        assert "parent repo" in joined, joined
        assert machine.branch("parent") == "feature", (
            "the branch guard checked out main in the middle of a bisect"
        )


# ============================================================================
# The gate never advises a command that overwrites a live file (audit C1)
# ============================================================================


class TestPartialAdviceNeverClobbers:
    """A path the untracked restore declined is a path that ALREADY HOLDS
    something — usually the other machine's copy, tracked at HEAD after
    the pull. Every partial gate line said the file existed "ONLY inside
    the entry" and offered `git checkout <sha>^3 -- <path>`, which
    replaces it, stages it, and has the next run publish it."""

    def test_following_the_gates_command_cannot_clobber_the_tracked_file(
        self, world: SyncWorld
    ) -> None:
        """The exact sequence, then the gate's own command run verbatim.

        Kills DS-C1: `unrestored_untracked_paths` printing a bare path, so
        every consumer words it as `missing` and hands the operator a
        checkout.
        """
        machine = world.add_machine("a")
        report = "reports/field-notes.md"
        theirs = "the other machine's copy\n"
        world.publish_memory_append("2026-09-08-from-elsewhere")
        world.publish_data_change(report, theirs)

        base = machine.head("data")
        machine.append_memory("2026-09-08-local-append")
        target = machine.data / report
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("the local copy\n", encoding="utf-8")
        git("checkout", "-q", "--detach", base, cwd=machine.data)

        assert world.run_sync(machine).returncode == 2
        joined = "\n".join(gate_details(world))
        sha = git("stash", "list", "--format=%H", cwd=machine.data).stdout.split()[0]

        # The gate names the state, not a fiction about where the file is.
        assert "DIFFERENT copy" in joined, joined
        assert "ONLY inside" not in joined, joined
        # …and offers no command that would write over what is there.
        assert f"checkout {sha}^3" not in joined, joined
        assert f"show {sha}^3" in joined, joined

        # Run every `git` command the gate actually offers. None of them
        # may change the tracked file or stage anything.
        offered = [
            line.strip().rstrip(".")
            for line in joined.replace(". ", ".\n").splitlines()
            if "git -C" in line and "show" in line
        ]
        assert offered, joined
        before = (machine.data / report).read_text(encoding="utf-8")
        # The conflicted apply already left the corpus in the index; what
        # matters is that the advice adds nothing to it.
        staged_before = git(
            "diff", "--cached", "--name-only", cwd=machine.data
        ).stdout
        for command in offered:
            snippet = command[command.index("git -C"):]
            # `<path>` is a placeholder the operator fills in.
            snippet = snippet.replace("<path>", report)
            subprocess.run(snippet, shell=True, cwd=str(machine.data),
                           capture_output=True, text=True, check=False)
        assert (machine.data / report).read_text(encoding="utf-8") == before == theirs
        assert git(
            "diff", "--cached", "--name-only", cwd=machine.data
        ).stdout == staged_before, "the gate's advice staged something"


# ============================================================================
# A partial found before the full EXIT handler exists (audit M1)
# ============================================================================


class TestPartialFoundDuringRecovery:
    """reconcile_orphaned_stashes runs while only the EARLY trap is
    installed, and its `partial` branch calls `fail`. Nothing wrote the
    sidecar, so the warning lived exactly one run and the next clean run
    cleared the gate over a file that was in no commit and no tree."""

    def test_an_orphan_partial_is_still_reported_on_the_next_run(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-M1 (eleventh): dropping the `write_stash_state` before
        that `fail`, or the `partial_stash_records` guard in
        render_on_early_exit."""
        machine = world.add_machine("a")
        report = "reports/orphan-notes.md"
        target = machine.data / report
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("the stashed copy\n", encoding="utf-8")
        machine.append_memory("2026-09-08-orphaned")
        git("stash", "push", "-u", "-q", "-m", "an orphan", cwd=machine.data)
        sha = git("rev-parse", "stash@{0}", cwd=machine.data).stdout.strip()
        # The corpus moved on, so the tracked half conflicts, and somebody
        # else's copy of the report is in the way of the untracked half.
        machine.memories.write_text('{"id": "moved on"}\n', encoding="utf-8")
        machine.commit_data("diverge", "memories/memories.jsonl")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("a different copy\n", encoding="utf-8")

        first = world.run_sync(machine, PA_TEST_ORPHAN_STASHES="stash@{0}")
        assert first.returncode == 2, first.stdout + first.stderr
        joined = "\n".join(gate_details(world))
        assert report in joined, joined
        sidecar = world.home / ".cache" / "daily-sync-stash-state"
        rows = [r for r in sidecar.read_text(encoding="utf-8").splitlines()
                if "partial" in r]
        assert rows, "the orphan's partial state was never recorded"
        assert rows[0].split("\t")[1] == sha, rows

        # A second run, with the markers resolved by hand: it completes,
        # and must still say the report has not come back.
        machine.memories.write_text('{"id": "resolved by hand"}\n', encoding="utf-8")
        git("add", "--", "memories/memories.jsonl", cwd=machine.data)
        second = world.run_sync(machine)
        assert second.returncode == 0, second.stdout + second.stderr
        again = "\n".join(gate_details(world))
        assert report in again, (
            "the warning was cleared while the file was still only in the "
            "stash: " + again
        )


# ============================================================================
# An untracked collision with IDENTICAL content (audit M3)
# ============================================================================


class TestIdenticalUntrackedCollision:
    """Both machines write the same report. git declines the untracked
    half just as loudly, having already applied the tracked one — and
    that was classified `refused` ("the tree was left untouched"), so a
    perfectly recovered entry was gated as unrecovered work, never
    dropped, and re-stashed on every later run."""

    def test_an_identical_collision_is_recovered_not_gated(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-M3: requiring `apply_outcome_untracked` to be
        non-empty before the tree-changed branch may classify anything."""
        machine = world.add_machine("a")
        report = "reports/shared-notes.md"
        same = "both machines wrote this\n"
        world.publish_data_change(report, same)

        base = machine.head("data")
        machine.append_memory("2026-09-08-identical")
        target = machine.data / report
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(same, encoding="utf-8")
        git("checkout", "-q", "--detach", base, cwd=machine.data)

        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr
        assert world.gate("daily-sync-gate").strip() == "0", world.gate(
            "daily-sync-gate"
        )
        assert not git("stash", "list", cwd=machine.data).stdout.strip(), (
            "an entry whose content is entirely in the tree was kept"
        )
        assert "2026-09-08-identical" in world.published_data_file(
            "memories/memories.jsonl"
        )


# ============================================================================
# Nothing is PUSHED that shrinks the corpus against origin (audit M4)
# ============================================================================


class TestPublishedShrinkGuard:
    """abort_on_jsonl_shrink covers the two commits this script makes. The
    ahead-of-origin push publishes whatever is on the branch, including a
    commit made by commit-data.sh, monthly-archive.py, or by hand."""

    def test_a_hand_committed_truncation_is_never_pushed(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-M4: removing `abort_on_published_shrink` from before
        `push_with_retry "data submodule"`."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-one")
        machine.append_memory("2026-09-08-two")
        machine.commit_data("real captures", "memories/memories.jsonl")
        git("push", "-q", "origin", "main", cwd=machine.data)
        published_before = world.published_data_head()

        # Something else truncates and commits -- no trailer, not this
        # script, and the tree is left clean so the auto-sync block has
        # nothing to do.
        machine.memories.write_text('{"id": "all that is left"}\n', encoding="utf-8")
        machine.commit_data("a botched rewrite", "memories/memories.jsonl")

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 4, combined
        assert world.published_data_head() == published_before, (
            "a hand-committed truncation reached origin"
        )
        joined = "\n".join(gate_details(world))
        assert "SHORTER than origin" in joined, joined
        assert "Rewrite-Class: bulk" in joined, joined
        # Nothing was undone: the commits are not this script's to reset.
        assert git("log", "-1", "--format=%s", cwd=machine.data).stdout.strip() == (
            "a botched rewrite"
        )
        assert list((machine.pa / "logs").glob("daily-sync-shrink-*.log"))

    def test_a_bulk_trailer_in_the_range_still_publishes(
        self, world: SyncWorld
    ) -> None:
        """A deliberate archive run must still reach origin, or the
        monthly rewrite wedges the sync every time."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-one")
        machine.append_memory("2026-09-08-two")
        machine.commit_data("real captures", "memories/memories.jsonl")
        git("push", "-q", "origin", "main", cwd=machine.data)

        machine.memories.write_text('{"id": "kept"}\n', encoding="utf-8")
        machine.commit_data("archive", "memories/memories.jsonl")
        git("commit", "-q", "--amend", "-m",
            "chore(memories): monthly archive\n\nRewrite-Class: bulk\n",
            cwd=machine.data)

        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr
        assert world.published_data_file("memories/memories.jsonl") == (
            '{"id": "kept"}\n'
        )


# ============================================================================
# The EXIT handler's own partial restore (audit M5)
# ============================================================================


class TestExitHandlerPartialRestore:
    """The run stashes, something fails before its pop, and the EXIT
    handler's restore is the one that half-lands: the pull has already
    put the other machine's copy where the untracked file belongs."""

    def test_a_partial_restore_is_recorded_gated_and_not_re_applied(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-M5: replacing `record_partial_stash` in the exit
        handler's `partial` arm with `:` -- the entry is then reported as
        UNRECOVERED and the operator is told to pop it, which re-applies
        the tracked half on top of itself."""
        machine = world.add_machine("a")
        report = "reports/exit-notes.md"
        base = machine.head("data")
        # main gains the other machine's copy of the report…
        target = machine.data / report
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("main's copy\n", encoding="utf-8")
        machine.commit_data("the other machine's report", report)
        # …while the stash is taken on a detached HEAD that predates it.
        git("checkout", "-q", "--detach", base, cwd=machine.data)
        machine.append_memory("2026-09-08-exit-handler")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("the stashed copy\n", encoding="utf-8")
        # The pull fails, so the run never reaches its own pop.
        git("remote", "set-url", "origin", str(world.root / "no-such-remote.git"),
            cwd=machine.data)

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined

        joined = "\n".join(gate_details(world))
        assert "only PARTLY" in joined, joined
        assert report in joined, joined
        assert "UNRECOVERED" not in joined, (
            "a half-restored entry was reported as unrecovered work, whose "
            "advice is to pop it: " + joined
        )
        assert "DIFFERENT copy" in joined, joined

        sidecar = world.home / ".cache" / "daily-sync-stash-state"
        rows = [r for r in sidecar.read_text(encoding="utf-8").splitlines()
                if "\tpartial\t" in r]
        assert rows, "no partial row was written for the restored entry"
        assert rows[0].split("\t")[3] == report, rows

        # The tracked half landed exactly once.
        corpus = machine.memories.read_text(encoding="utf-8")
        assert corpus.count("2026-09-08-exit-handler") == 1, corpus
        assert (machine.data / report).read_text(encoding="utf-8") == "main's copy\n"


# ============================================================================
# `applied` needs positive evidence, not a changed tree (audit C1, second)
# ============================================================================


class TestAppliedNeedsEvidence:
    """git 2.48.1 restores a stash's untracked half BEFORE merging the
    tracked one. An entry whose files come back and whose merge is then
    refused outright changes the working tree without landing a byte of
    what it was asked to land -- and was dropped for it, taking the only
    copy of that tracked change with it."""

    def test_an_untracked_landing_with_a_refused_merge_is_not_dropped(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-C1: classifying `applied` from `git status` differing.

        Staged so the branch-switch stash carries both halves, the pull
        brings nothing that collides with the untracked one, and a local
        edit made in the meantime makes the tracked merge impossible.
        """
        machine = world.add_machine("a")
        base = machine.head("data")
        report = "reports/from-the-stash.md"
        machine.append_memory("2026-09-08-only-in-the-stash")
        target = machine.data / report
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("the stashed report\n", encoding="utf-8")
        git("checkout", "-q", "--detach", base, cwd=machine.data)
        # The archiver runs between the branch-switch stash and the pop,
        # and writes the corpus -- so the stash's tracked change can no
        # longer be merged into it.
        published_before = world.published_data_head()

        result = world.run_sync(
            machine,
            PA_TEST_GIT_REFUSE_APPLY_IN=str(machine.data),
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined

        listed = git("stash", "list", "--format=%H", cwd=machine.data).stdout.split()
        assert listed, "the entry holding the only copy of the append was dropped"
        kept = git("show", f"{listed[0]}:memories/memories.jsonl",
                   cwd=machine.data).stdout
        assert "2026-09-08-only-in-the-stash" in kept, kept
        joined = "\n".join(gate_details(world))
        assert joined, "nothing was gated about the entry that was kept"
        assert world.published_data_head() == published_before

    def test_a_concurrent_write_during_a_refused_apply_is_still_refused(
        self, world: SyncWorld
    ) -> None:
        """The weaker variant: anything writing between the snapshot and
        the classification flipped a plainly refused apply to `applied`.

        Kills DS-C1 in its cheapest form -- the write here is by another
        session and touches nothing the stash holds.
        """
        machine = world.add_machine("a")
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- unsaved work\n", encoding="utf-8"
        )
        git("remote", "set-url", "origin", str(world.root / "no-such-remote.git"),
            cwd=machine.data)

        result = world.run_sync(
            machine,
            PA_TEST_GIT_REFUSE_APPLY_IN=str(machine.data),
            PA_TEST_WRITE_DURING_APPLY=str(machine.data / "unrelated.md"),
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 2, combined
        assert git("stash", "list", cwd=machine.data).stdout.strip(), (
            "a refused apply was read as applied because something else wrote"
        )
        joined = "\n".join(gate_details(world))
        assert "REFUSED" in joined or "UNRECOVERED" in joined, joined
        assert "could not drop" not in joined, (
            "an apply that did nothing was reported as applied: " + joined
        )


# ============================================================================
# A conflicted row survives an early exit (audit M2, second re-audit)
# ============================================================================


class TestConflictedRowsAreCarried:
    """The early trap rewrites the sidecar from this run's arrays. A row
    it does not carry forward is a row the next run cannot read -- and
    the conflicted rows are exactly what previously_recorded_stashes
    needs to say whose markers a half-merged tree holds."""

    def test_a_conflicted_row_survives_an_early_exit(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-M2: carrying only `partial` rows forward.

        Run 1 leaves a conflicted row. Run 2 exits early -- an orphan the
        drift detector names, which fails before the full EXIT handler
        exists -- and must not take the row with it. Run 3 still
        attributes the markers.
        """
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-conflicting")
        git("stash", "push", "-q", "-m", "recorded as conflicted", cwd=machine.data)
        sha = git("rev-parse", "stash@{0}", cwd=machine.data).stdout.strip()
        machine.memories.write_text('{"id": "committed"}\n', encoding="utf-8")
        machine.commit_data("diverge", "memories/memories.jsonl")
        git("stash", "apply", "stash@{0}", cwd=machine.data, check=False)
        sidecar = world.home / ".cache" / "daily-sync-stash-state"
        sidecar.write_text(
            f"{machine.data}\t{sha}\tconflicted\tmemories/memories.jsonl\n",
            encoding="utf-8",
        )

        # Run 2 exits early, at the corpus guard, before the full handler.
        second = world.run_sync(machine)
        assert second.returncode == 2, second.stdout + second.stderr
        rows = [r for r in sidecar.read_text(encoding="utf-8").splitlines() if r]
        assert rows, "the early exit emptied the sidecar"
        assert rows[0].split("\t")[1] == sha, rows
        assert rows[0].split("\t")[2] == "conflicted", rows

        third = world.run_sync(machine)
        assert third.returncode == 2, third.stdout + third.stderr
        joined = "\n".join(gate_details(world))
        assert "these markers ARE that stash's content" in joined, (
            "attribution was lost with the conflicted row: " + joined
        )


# ============================================================================
# The bulk trailer excuses one commit, not a range (audit M3, second)
# ============================================================================


class TestPerCommitTrailer:
    """One deliberate archive commit waved through every unrelated
    truncation beside it."""

    def _publish_two_hundred(self, world: SyncWorld) -> object:
        """A machine whose origin holds a corpus worth truncating."""
        machine = world.add_machine("a")
        for index in range(4):
            machine.append_memory(f"2026-09-08-record-{index}")
        machine.commit_data("real captures", "memories/memories.jsonl")
        git("push", "-q", "origin", "main", cwd=machine.data)
        return machine

    def test_an_untrailered_truncation_beside_a_bulk_one_is_refused(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-M3: asking whether the RANGE holds a trailer anywhere.

        A legitimate archive commit, then a botched one. The second must
        stop the push even though the first is blameless.
        """
        machine = self._publish_two_hundred(world)
        published_before = world.published_data_head()
        machine.memories.write_text(
            '{"id": "kept-by-the-archive"}\n{"id": "also-kept"}\n', encoding="utf-8"
        )
        machine.commit_data("archive", "memories/memories.jsonl")
        git("commit", "-q", "--amend", "-m",
            "chore(memories): monthly archive\n\nRewrite-Class: bulk\n",
            cwd=machine.data)
        machine.memories.write_text('{"id": "oops"}\n', encoding="utf-8")
        machine.commit_data("a botched rewrite", "memories/memories.jsonl")

        result = world.run_sync(machine)
        assert result.returncode == 4, result.stdout + result.stderr
        assert world.published_data_head() == published_before, (
            "a truncation rode out on somebody else's trailer"
        )
        joined = "\n".join(gate_details(world))
        assert "Rewrite-Class: bulk" in joined, joined

    def test_a_body_merely_quoting_the_trailer_is_not_one(
        self, world: SyncWorld
    ) -> None:
        """Kills: unanchoring the trailer grep. A commit that talks about
        the trailer has not declared one."""
        machine = self._publish_two_hundred(world)
        published_before = world.published_data_head()
        machine.memories.write_text('{"id": "all that is left"}\n', encoding="utf-8")
        machine.commit_data("prune", "memories/memories.jsonl")
        git("commit", "-q", "--amend", "-m",
            "chore(memories): prune\n\nRewrite-Class: bulk would be wrong here,\n"
            "because this is not a bulk rewrite.\n",
            cwd=machine.data)

        result = world.run_sync(machine)
        assert result.returncode == 4, result.stdout + result.stderr
        assert world.published_data_head() == published_before, (
            "a commit merely quoting the trailer was treated as declaring it"
        )

    def test_a_trailing_terminator_change_is_not_a_shrink(
        self, world: SyncWorld
    ) -> None:
        """Audit L4: `wc -l` counts newlines, so a commit that only drops
        the corpus's final terminator read as a one-line shrink and raised
        a false exit 4 on a corpus nobody truncated."""
        machine = self._publish_two_hundred(world)
        text = machine.memories.read_text(encoding="utf-8")
        machine.memories.write_text(text.rstrip("\n"), encoding="utf-8")

        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr
        assert not list((machine.pa / "logs").glob("daily-sync-shrink-*.log")), (
            "dropping the final newline was reported as a shrink"
        )


# ============================================================================
# Nothing is pushed that no guard could check (audit M4, second re-audit)
# ============================================================================


class TestUnverifiablePushIsWithheld:
    """Without origin/main the shrink check cannot run. The auto-sync
    block pushed anyway, publishing content nothing had compared against
    anything -- and the skip was silent."""

    def test_without_origin_main_nothing_is_pushed_and_the_skip_is_said(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-M4: the silent `return 0` and the ungated push."""
        machine = world.add_machine("a")
        machine.append_memory("2026-09-08-unverifiable")
        published_before = world.published_data_head()
        # The remote-tracking ref the guard and the S1 check both need,
        # removed the way production loses it: a fetch refspec that never
        # writes it, under which the pull still succeeds.
        git("config", "--unset", "remote.origin.fetch", cwd=machine.data)
        git("update-ref", "-d", "refs/remotes/origin/main", cwd=machine.data)

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "no origin/main ref" in combined, combined
        assert world.published_data_head() == published_before, (
            "a commit no guard could check was pushed anyway"
        )
        joined = "\n".join(gate_details(world))
        assert "origin/main" in joined, joined

    def test_a_commit_the_auto_sync_block_makes_is_withheld_too(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-M4's other half: the auto-sync block pushed whatever
        it had just committed, whether or not anything could check it.

        Dirtied with a prose file, which the append-only block leaves
        alone, so the auto-sync block is the one that commits.
        """
        machine = world.add_machine("a")
        (machine.data / "tasks" / "inbox.md").write_text(
            "# Inbox\n\n- written by a session\n", encoding="utf-8"
        )
        published_before = world.published_data_head()
        git("config", "--unset", "remote.origin.fetch", cwd=machine.data)
        git("update-ref", "-d", "refs/remotes/origin/main", cwd=machine.data)

        result = world.run_sync(machine)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "push is WITHHELD" in combined, combined
        assert world.published_data_head() == published_before, (
            "the auto-sync block pushed a commit no guard could check"
        )
        # The commit was still made: the work is on the branch, not lost.
        assert machine.head("data") != published_before


# ============================================================================
# A merge is measured against its smallest parent (audit M-a, third)
# ============================================================================


class TestMergedBulkRewrite:
    """A bulk rewrite made on a branch and brought in with `--no-ff` shows
    the whole truncation against the merge's FIRST parent while carrying
    no trailer of its own -- exit 4 with no way out short of rewriting
    history."""

    def _published_corpus(self, world: SyncWorld) -> object:
        """A machine whose origin holds a corpus worth truncating."""
        machine = world.add_machine("a")
        for index in range(4):
            machine.append_memory(f"2026-09-08-record-{index}")
        machine.commit_data("real captures", "memories/memories.jsonl")
        git("push", "-q", "origin", "main", cwd=machine.data)
        return machine

    def test_a_bulk_rewrite_merged_no_ff_still_publishes(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-M-a: comparing a merge against its first parent."""
        machine = self._published_corpus(world)
        git("checkout", "-q", "-b", "archive-run", cwd=machine.data)
        machine.memories.write_text('{"id": "kept"}\n', encoding="utf-8")
        machine.commit_data("archive", "memories/memories.jsonl")
        git("commit", "-q", "--amend", "-m",
            "chore(memories): monthly archive\n\nRewrite-Class: bulk\n",
            cwd=machine.data)
        git("checkout", "-q", "main", cwd=machine.data)
        git("merge", "-q", "--no-ff", "-m", "Merge the monthly archive",
            "archive-run", cwd=machine.data)

        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr
        assert world.published_data_file("memories/memories.jsonl") == (
            '{"id": "kept"}\n'
        )

    def test_a_merge_that_truncates_below_both_parents_is_refused(
        self, world: SyncWorld
    ) -> None:
        """And skipping merges entirely would miss this: the resolution
        itself throws records away that neither side dropped."""
        machine = self._published_corpus(world)
        base = machine.head("data")
        git("checkout", "-q", "-b", "side", cwd=machine.data)
        machine.append_memory("2026-09-08-from-the-branch")
        machine.commit_data("branch capture", "memories/memories.jsonl")
        git("checkout", "-q", "main", cwd=machine.data)
        machine.append_memory("2026-09-08-from-main")
        machine.commit_data("main capture", "memories/memories.jsonl")
        git("merge", "-q", "--no-commit", "side", cwd=machine.data, check=False)
        # A "resolution" that keeps almost nothing from either side.
        machine.memories.write_text('{"id": "oops"}\n', encoding="utf-8")
        git("add", "--", "memories/memories.jsonl", cwd=machine.data)
        git("commit", "-q", "-m", "Merge side", cwd=machine.data)
        assert machine.head("data") != base
        published_before = world.published_data_head()

        result = world.run_sync(machine)
        assert result.returncode == 4, result.stdout + result.stderr
        assert world.published_data_head() == published_before, (
            "a merge whose own resolution truncated the corpus was published"
        )


# ============================================================================
# A leftover sidecar temp is swept by a run (audit L3, third re-audit)
# ============================================================================


class TestSweptSidecarTemps:
    """The sweep has to run, not merely exist."""

    def test_a_run_clears_a_leftover_sidecar_temp(self, world: SyncWorld) -> None:
        """Kills DS-L3's other half: removing the call from the run.

        Placed under the flock, so nothing else is between its mktemp and
        its rename.
        """
        machine = world.add_machine("a")
        orphan = world.home / ".cache" / "daily-sync-stash-state.Ab12Cd"
        orphan.write_text("half a row from a killed run\n", encoding="utf-8")

        assert world.run_sync(machine).returncode == 0
        assert not orphan.exists(), (
            "a half-built sidecar from a killed run survived the next one"
        )


# ============================================================================
# A merge this guard cannot judge is refused, not waved through (audit M1)
# ============================================================================


class TestUnjudgeableMerge:
    """The smallest-parent rule took `min` over every parent, and a parent
    that does not hold the corpus counts as zero records -- so a merge
    with an orphan or unrelated-history parent could keep one record out
    of a hundred and never register as a shrink at all."""

    def _published_corpus(self, world: SyncWorld) -> object:
        """A machine whose origin holds a corpus worth truncating."""
        machine = world.add_machine("a")
        for index in range(4):
            machine.append_memory(f"2026-09-09-record-{index}")
        machine.commit_data("real captures", "memories/memories.jsonl")
        git("push", "-q", "origin", "main", cwd=machine.data)
        return machine

    def test_a_merge_with_an_orphan_parent_cannot_be_judged(
        self, world: SyncWorld
    ) -> None:
        """Kills DS-M1: counting a corpus-less parent as zero records.

        The orphan branch shares no history and holds no corpus, so the
        minimum over the parents was 0 and `after < before` was false for
        any surviving record -- "every commit that shortened it carries a
        trailer, allowed" over a merge that kept one line in five.
        """
        machine = self._published_corpus(world)
        published_before = world.published_data_head()
        # An orphan built with plumbing, so the working tree is never
        # disturbed: a parentless commit holding the empty tree, and so
        # no corpus at all.
        empty_tree = git(
            "hash-object", "-wt", "tree", "/dev/null", cwd=machine.data
        ).stdout.strip()
        orphan = git(
            "commit-tree", empty_tree, "-m", "an unrelated history",
            cwd=machine.data
        ).stdout.strip()
        git("merge", "-q", "--no-commit", "--allow-unrelated-histories",
            orphan, cwd=machine.data, check=False)
        machine.memories.write_text('{"id": "one record in five"}\n',
                                    encoding="utf-8")
        git("add", "-A", cwd=machine.data)
        git("commit", "-q", "-m", "Merge unrelated", cwd=machine.data)

        result = world.run_sync(machine)
        assert result.returncode == 4, result.stdout + result.stderr
        assert world.published_data_head() == published_before, (
            "a merge this guard could not judge published a truncated corpus"
        )
        joined = "\n".join(gate_details(world))
        assert "SHORTER than origin" in joined, joined
        # The corpus-less parent is EXCLUDED, so the merge is measured
        # against the one parent that has a corpus and the shrink is
        # attributed to it. Counting that parent as zero records leaves
        # the shrink unattributed -- also refused, by the fail-closed
        # rule, but for the wrong reason and one commit too late.
        report = next(iter((machine.pa / "logs").glob("daily-sync-shrink-*.log")))
        written = report.read_text(encoding="utf-8")
        assert "could not be attributed" not in written, written
        merge_sha = machine.head("data")
        assert merge_sha in written, written

    def test_a_normal_no_ff_bulk_merge_still_publishes(
        self, world: SyncWorld
    ) -> None:
        """The rule the orphan case must not break: an archive run made on
        a branch and merged with --no-ff still goes out."""
        machine = self._published_corpus(world)
        git("checkout", "-q", "-b", "archive-run", cwd=machine.data)
        machine.memories.write_text('{"id": "kept"}\n', encoding="utf-8")
        machine.commit_data("archive", "memories/memories.jsonl")
        git("commit", "-q", "--amend", "-m",
            "chore(memories): monthly archive\n\nRewrite-Class: bulk\n",
            cwd=machine.data)
        git("checkout", "-q", "main", cwd=machine.data)
        git("merge", "-q", "--no-ff", "-m", "Merge the monthly archive",
            "archive-run", cwd=machine.data)

        result = world.run_sync(machine)
        assert result.returncode == 0, result.stdout + result.stderr
        assert world.published_data_file("memories/memories.jsonl") == (
            '{"id": "kept"}\n'
        )
