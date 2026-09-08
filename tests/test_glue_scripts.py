"""
Tests for the glue / orchestration shell scripts touched by Audit
2026-05-02 Cluster E (Batch 8 fixes).

Covered:
- ``scripts/commit-data.sh`` — refuses to run from a non-main branch
  in either the data submodule or the parent repo (E-Critical, Top-10
  item #9). Replaces the previous hardcoded ``git push origin main``
  which silently published the wrong refs.
- ``scripts/sync-symlinks.sh`` — ``ensure_symlink`` now reports a
  dangling-symlink warning when the target string is correct but the
  source file no longer exists (E-Medium "already correct"
  misclassification of broken links).

These tests run the live shell scripts in throwaway working trees
under ``tmp_path``; they do not touch the user's real ``data``
submodule or ``~/.claude`` tree. ``daily-sync.sh``'s own tests live
in ``test_daily_sync_behaviour.py``, on the harness built for it.
"""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMIT_DATA_SCRIPT = REPO_ROOT / "scripts" / "commit-data.sh"
SYNC_SYMLINKS_SCRIPT = REPO_ROOT / "scripts" / "sync-symlinks.sh"


# ============================================================================
# Helpers
# ============================================================================


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run ``git`` with deterministic identity in ``cwd``."""
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test Bot",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test Bot",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        }
    )
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


# ============================================================================
# commit-data.sh — branch-detection guard (E-Critical)
# ============================================================================


class TestCommitDataBranchGuard:
    """``commit-data.sh`` must refuse to run unless the data submodule
    is on ``main`` (and warn before pushing the parent submodule
    pointer if the parent repo is on a non-main branch).

    The previous implementation hardcoded ``git push origin main`` from
    whatever branch happened to be checked out; on a topic branch this
    silently published the *unchanged* local main ref while the new
    commit was orphaned in the reflog.
    """

    @pytest.fixture()
    def fake_pa_tree(self, tmp_path: Path) -> Path:
        """Build a minimal ``personal-assistant`` lookalike under
        tmp_path, with a ``scripts/`` symlink to the real script and a
        nested ``data/`` directory that is a real git repo (no remote
        — the script's branch check fires before any network call)."""
        pa_dir = tmp_path / "pa"
        scripts_dir = pa_dir / "scripts"
        scripts_dir.mkdir(parents=True)

        # Symlink the script under test into the fake tree so its
        # SCRIPT_DIR / PA_DIR resolution lands inside tmp_path.
        (scripts_dir / "commit-data.sh").symlink_to(COMMIT_DATA_SCRIPT)

        # logs/ is created by the script itself (mkdir -p) — no need.

        data_dir = pa_dir / "data"
        data_dir.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=data_dir)
        # Seed a commit so HEAD is real and `git diff --cached --quiet`
        # has a comparison base.
        (data_dir / "seed.txt").write_text("seed\n")
        _git("add", "seed.txt", cwd=data_dir)
        _git("commit", "--quiet", "-m", "seed", cwd=data_dir)

        # Initialise the parent so any later `cd "$PA_DIR"` step has a
        # repo to talk to (script exits before that step on the failure
        # path under test, but we leave the fixture realistic).
        _git("init", "--quiet", "--initial-branch=main", cwd=pa_dir)
        return pa_dir

    def test_refuses_when_data_submodule_on_topic_branch(
        self, fake_pa_tree: Path
    ) -> None:
        """Branch != main in the data submodule must fail before any
        commit or push attempt."""
        data_dir = fake_pa_tree / "data"
        # Switch to a feature branch and stage a change so there is
        # something to commit (otherwise the "no changes" early-exit
        # would mask the branch check — though our fix runs first).
        _git("checkout", "--quiet", "-b", "feature/x", cwd=data_dir)
        (data_dir / "new.txt").write_text("new\n")

        result = subprocess.run(
            [
                "bash",
                str(fake_pa_tree / "scripts" / "commit-data.sh"),
                "test-msg",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit on topic branch; got "
            f"rc={result.returncode}\nstdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
        assert "feature/x" in result.stderr
        assert "not 'main'" in result.stderr or "not main" in result.stderr

    def test_proceeds_on_main_when_no_changes(
        self, fake_pa_tree: Path
    ) -> None:
        """On main with no staged changes, the script should exit 0
        with the 'No data changes' message (i.e. the branch check
        passes and the early-exit path runs)."""
        result = subprocess.run(
            [
                "bash",
                str(fake_pa_tree / "scripts" / "commit-data.sh"),
                "test-msg",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"Expected rc=0; got rc={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "No data changes" in result.stdout

    def test_no_hardcoded_push_to_main(self) -> None:
        """Defence in depth: the literal ``git push origin main`` must
        not appear in the script source — only ``git push origin
        HEAD:main`` after the branch check has confirmed we're on main."""
        source = COMMIT_DATA_SCRIPT.read_text(encoding="utf-8")
        # The dangerous pattern was ``git push origin main`` (no HEAD
        # explicit). The fix uses ``git push origin HEAD:main``.
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert stripped != "git push origin main", (
                "commit-data.sh still contains the hardcoded "
                "`git push origin main` (Audit E-Critical 2026-05-02)."
            )


# ============================================================================
# sync-symlinks.sh — dangling-symlink detection (E-Medium)
# ============================================================================


class TestSyncSymlinksDanglingDetection:
    """``ensure_symlink`` must distinguish a healthy symlink from a
    dangling one. The previous implementation only compared
    ``readlink`` against the expected target string and reported
    "already correct" even when the source had been moved or deleted.
    """

    def _run_ensure_symlink(
        self, src: str, target: str, label: str
    ) -> subprocess.CompletedProcess[str]:
        """Source the script's ``ensure_symlink`` helper in isolation
        so we can probe its behaviour without running the whole sync."""
        # Extract the helper functions from the script, then call
        # ensure_symlink with the test arguments. We use bash -c to
        # source the live script's body up to the `# Step 1:` marker,
        # which holds only function definitions and constants.
        script = SYNC_SYMLINKS_SCRIPT.read_text(encoding="utf-8")
        marker = "# Step 1: Submodule init/update"
        helper_body, _, _ = script.partition(marker)

        wrapper = (
            helper_body
            + "\n"
            + f'ensure_symlink "{src}" "{target}" "{label}"\n'
        )
        return subprocess.run(
            ["bash", "-c", wrapper],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_dangling_symlink_reports_warning(self, tmp_path: Path) -> None:
        """A symlink with a correct target string but missing source
        must be reported as a dangling symlink, not "already correct"."""
        missing_src = tmp_path / "does-not-exist.md"
        target = tmp_path / "link-to-missing.md"
        target.symlink_to(missing_src)

        # Sanity check: link exists, source does not.
        assert target.is_symlink()
        assert not missing_src.exists()

        result = self._run_ensure_symlink(
            str(missing_src), str(target), "test-link"
        )
        assert result.returncode == 0
        # The fix surfaces "dangling" / "WARNING" rather than the old
        # "already correct" line.
        combined = result.stdout + result.stderr
        assert "dangling" in combined.lower() or "WARNING" in combined, (
            f"Expected dangling-symlink warning; got:\n{combined}"
        )
        assert "already correct" not in combined

    def test_healthy_symlink_still_reports_already_correct(
        self, tmp_path: Path
    ) -> None:
        """Regression check: a real, correctly-pointing symlink to an
        existing source must still report "already correct" (the
        normal idempotent path)."""
        real_src = tmp_path / "real-source.md"
        real_src.write_text("hello\n")
        target = tmp_path / "link-to-real.md"
        target.symlink_to(real_src)

        result = self._run_ensure_symlink(
            str(real_src), str(target), "test-link"
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "already correct" in combined
        assert "dangling" not in combined.lower()

    def test_wrong_target_string_updates_symlink(
        self, tmp_path: Path
    ) -> None:
        """Regression check: a symlink whose target string does not
        match the expected source must be re-pointed (the existing
        update path)."""
        old_src = tmp_path / "old.md"
        old_src.write_text("old\n")
        new_src = tmp_path / "new.md"
        new_src.write_text("new\n")
        target = tmp_path / "link.md"
        target.symlink_to(old_src)

        result = self._run_ensure_symlink(
            str(new_src), str(target), "test-link"
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "updated symlink" in combined
        # The link now points at new_src.
        assert target.resolve() == new_src.resolve()



# ============================================================================
# Audit round two (2026-09-08), tranche 2 — git and sync writers.
#
# Findings S11 (sync-symlinks retargeting), S13 (compose-global-claude-md
# truncation), S14 (the R2 version probe killing the script), S16 (commit-data
# committing without a pathspec), and S20 (commit-data's lock and parent guard
# removable with the suite green).
#
# Every test below runs the live script in a throwaway tree with HOME pinned
# into tmp_path: none of them may reach the real ~/.claude, the real data
# submodule, the real cc-archives mount, or the network.
# ============================================================================

COMPOSE_SCRIPT = REPO_ROOT / "scripts" / "compose-global-claude-md.sh"
R2_PUSH_SCRIPT = REPO_ROOT / "scripts" / "push-archives-to-r2.sh"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test Bot",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test Bot",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _run_script(script: Path, *args: str, home: Path, cwd: Path | None = None,
                extra_env: dict[str, str] | None = None
                ) -> subprocess.CompletedProcess[str]:
    """Run a shell script with HOME pinned into the test tree."""
    env = os.environ.copy()
    env.update(GIT_IDENTITY)
    env["HOME"] = str(home)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


# ----------------------------------------------------------------------------
# S11 — ensure_symlink must RETARGET a symlink-to-directory, not write inside it
# ----------------------------------------------------------------------------


class TestSyncSymlinksRetargetsDirectoryLinks:
    """``ln -sf`` follows a symlink that points at a DIRECTORY and creates the
    new link *inside* it. Every skill link (step 4) is exactly that shape, so
    retargeting a renamed skill silently failed, the script logged "updated
    symlink" on every run, and a stray symlink was deposited into the old
    source directory. ``ln -sfn`` retargets the link itself.
    """

    def _ensure_symlink(self, src: Path, target: Path, home: Path
                        ) -> subprocess.CompletedProcess[str]:
        """Source only the helper half of the script (function definitions and
        constants — everything above the first step) and call the helper.

        The script's steps are never executed, so this cannot touch the real
        ~/.claude; HOME is pinned as a second line of defence.
        """
        script = SYNC_SYMLINKS_SCRIPT.read_text(encoding="utf-8")
        helper_body, _, _ = script.partition("# Step 1: Submodule init/update")
        wrapper = f'{helper_body}\nensure_symlink "{src}" "{target}" "skill-x"\n'
        env = os.environ.copy()
        env["HOME"] = str(home)
        return subprocess.run(["bash", "-c", wrapper], env=env,
                              capture_output=True, text=True, check=False)

    def test_symlinked_directory_is_retargeted_not_populated(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        home.mkdir()
        old_skill = tmp_path / "skills-old"
        new_skill = tmp_path / "skills-new"
        old_skill.mkdir()
        new_skill.mkdir()
        link = tmp_path / "linked-skill"
        link.symlink_to(old_skill)

        result = self._ensure_symlink(new_skill, link, home)

        assert result.returncode == 0, result.stderr
        assert os.readlink(link) == str(new_skill), (
            "the symlink was not retargeted (ln -sf followed it into the "
            "old directory instead)"
        )
        assert list(old_skill.iterdir()) == [], (
            f"a stray link was deposited inside the old target: "
            f"{[p.name for p in old_skill.iterdir()]}"
        )


# ----------------------------------------------------------------------------
# S13 — compose-global-claude-md.sh must not truncate the target before writing
# ----------------------------------------------------------------------------


class TestComposeGlobalClaudeMdIsAtomic:
    """``compose > "$TARGET"`` truncated ~/.claude/CLAUDE.md before the first
    byte was written, so a failure inside ``compose`` left the global
    instruction file partial — silently dropping the outbound-message rule and
    the ownership boundaries — and ``set -e`` aborted without restoring it.
    """

    @pytest.fixture()
    def fake_pa_tree(self, tmp_path: Path) -> tuple[Path, Path]:
        """A minimal tree with the composer's three sources. Returns
        ``(pa_dir, home)``."""
        pa_dir = tmp_path / "pa"
        (pa_dir / "scripts").mkdir(parents=True)
        (pa_dir / "scripts" / "compose-global-claude-md.sh").symlink_to(
            COMPOSE_SCRIPT
        )
        (pa_dir / "global-agent-guidance").mkdir()
        (pa_dir / "global-agent-guidance" / "common.md").write_text(
            "# Shared guidance\n\nCOMMON-SECTION\n", encoding="utf-8"
        )
        (pa_dir / "global-claude-md").mkdir()
        (pa_dir / "global-claude-md" / "claude.md").write_text(
            "# Claude overlay\n\nOVERLAY-SECTION\n", encoding="utf-8"
        )
        (pa_dir / "data" / "global-claude-md").mkdir(parents=True)
        (pa_dir / "data" / "global-claude-md" / "local.md").write_text(
            "# Local\n\nLOCAL-SECTION\n", encoding="utf-8"
        )
        home = tmp_path / "home"
        home.mkdir()
        return pa_dir, home

    def test_composes_all_three_sections(
        self, fake_pa_tree: tuple[Path, Path]
    ) -> None:
        pa_dir, home = fake_pa_tree
        result = _run_script(
            pa_dir / "scripts" / "compose-global-claude-md.sh", home=home
        )
        assert result.returncode == 0, result.stderr
        composed = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        for marker in ("COMMON-SECTION", "OVERLAY-SECTION", "LOCAL-SECTION"):
            assert marker in composed

    @pytest.mark.skipif(
        os.geteuid() == 0, reason="root ignores the unreadable-source setup"
    )
    def test_failed_compose_leaves_the_previous_file_intact(
        self, fake_pa_tree: tuple[Path, Path]
    ) -> None:
        pa_dir, home = fake_pa_tree
        script = pa_dir / "scripts" / "compose-global-claude-md.sh"
        assert _run_script(script, home=home).returncode == 0
        target = home / ".claude" / "CLAUDE.md"
        previous = target.read_text(encoding="utf-8")

        # A source that passes the -f existence check but cannot be read: the
        # shape a mid-compose failure takes (submodule unmounted, ENOSPC).
        local = pa_dir / "data" / "global-claude-md" / "local.md"
        local.chmod(0o000)
        (pa_dir / "global-agent-guidance" / "common.md").write_text(
            "# Shared guidance\n\nCHANGED-COMMON\n", encoding="utf-8"
        )
        try:
            result = _run_script(script, home=home)
        finally:
            local.chmod(0o644)

        assert result.returncode != 0, "a failed compose must not exit 0"
        assert target.read_text(encoding="utf-8") == previous, (
            "the previous global CLAUDE.md was truncated by a failed compose"
        )


# ----------------------------------------------------------------------------
# S14 — the rclone version probe must not kill push-archives-to-r2.sh
# ----------------------------------------------------------------------------


class TestR2PushVersionProbe:
    """Under ``set -euo pipefail`` a non-matching ``grep`` in the advisory
    version probe made the whole pipeline non-zero, killing the script before
    the mount and remote preconditions — and before any log line, so
    daily-sync reported the indistinguishable "push skipped or errored".
    """

    def test_unparseable_rclone_version_reaches_the_preconditions(
        self, tmp_path: Path
    ) -> None:
        pa_dir = tmp_path / "pa"
        (pa_dir / "scripts").mkdir(parents=True)
        (pa_dir / "scripts" / "push-archives-to-r2.sh").symlink_to(R2_PUSH_SCRIPT)
        home = tmp_path / "home"
        home.mkdir()  # no mnt/rpi-shares → the mount precondition must refuse

        # A fake rclone whose version banner carries no X.Y number. Nothing
        # here contacts the network; the real rclone is never invoked.
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "rclone"
        fake.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "version" ]]; then\n'
            '    echo "rclone banner with no parseable number"\n'
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)

        result = _run_script(
            pa_dir / "scripts" / "push-archives-to-r2.sh",
            home=home,
            extra_env={"RCLONE_BIN": str(fake),
                       "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        )

        combined = result.stdout + result.stderr
        assert "canonical mount point missing" in combined, (
            "the script died on the advisory version probe before reaching "
            f"its real preconditions; got rc={result.returncode}, "
            f"output:\n{combined}"
        )
        assert result.returncode == 1


# ----------------------------------------------------------------------------
# S16 / S20 — commit-data.sh: explicit pathspec, lock, and branch guards
# ----------------------------------------------------------------------------


class TestCommitDataSafetyContracts:
    """``commit-data.sh`` shares one working tree with concurrent sessions, so
    three contracts have to hold: it commits only the paths it means to; it
    refuses to run while the daily-sync lock is held; and it refuses to publish
    from anywhere but ``main``.
    """

    @pytest.fixture()
    def pa_with_data_remote(self, tmp_path: Path) -> Path:
        """A fake tree whose data submodule has a bare local remote, so the
        script's push succeeds without a network."""
        pa_dir = tmp_path / "pa"
        (pa_dir / "scripts").mkdir(parents=True)
        (pa_dir / "scripts" / "commit-data.sh").symlink_to(COMMIT_DATA_SCRIPT)

        data_remote = tmp_path / "data.git"
        data_remote.mkdir()
        _git("init", "--bare", "--quiet", "--initial-branch=main", cwd=data_remote)

        data_dir = pa_dir / "data"
        data_dir.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=data_dir)
        (data_dir / "seed.txt").write_text("seed\n")
        _git("add", "seed.txt", cwd=data_dir)
        _git("commit", "--quiet", "-m", "seed", cwd=data_dir)
        _git("remote", "add", "origin", str(data_remote), cwd=data_dir)
        _git("push", "--quiet", "origin", "main", cwd=data_dir)

        _git("init", "--quiet", "--initial-branch=main", cwd=pa_dir)
        (pa_dir / "README.md").write_text("parent\n")
        _git("add", "README.md", cwd=pa_dir)
        _git("commit", "--quiet", "-m", "seed parent", cwd=pa_dir)
        return pa_dir

    @staticmethod
    def _commit_count(repo: Path) -> int:
        return int(_git("rev-list", "--count", "HEAD", cwd=repo).stdout.strip())

    def test_leaves_another_sessions_staged_file_alone(
        self, pa_with_data_remote: Path
    ) -> None:
        """S16: a bare ``git commit`` after ``git add -A`` published whatever
        a concurrent session had already staged in the shared index."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')
        # Another session, part-way through an edit and already staged.
        (data_dir / "continuity.md").write_text("half-written prose\n")
        _git("add", "continuity.md", cwd=data_dir)

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 0, result.stderr
        committed = _git("show", "--name-only", "--pretty=format:", "HEAD",
                         cwd=data_dir).stdout.split()
        assert "memories.jsonl" in committed
        assert "continuity.md" not in committed, (
            "commit-data.sh swept a concurrent session's staged prose"
        )
        staged = _git("diff", "--cached", "--name-only", cwd=data_dir).stdout.split()
        assert staged == ["continuity.md"], (
            "the other session's staged work was lost, not preserved"
        )

    def test_refuses_while_the_daily_sync_lock_is_held(
        self, pa_with_data_remote: Path
    ) -> None:
        """S20: the flock is what stops commit-data interleaving with an
        in-flight daily-sync rebase (audit 2026-05-02 E-Critical lock-gap)."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')
        before = self._commit_count(data_dir)

        (pa_dir / "logs").mkdir(exist_ok=True)
        lock_path = pa_dir / "logs" / "daily-sync.lock"
        with open(lock_path, "w") as lock_fh:      # stand-in for daily-sync
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = _run_script(pa_dir / "scripts" / "commit-data.sh",
                                 "test-msg", home=pa_dir)

        assert result.returncode == 1, result.stdout + result.stderr
        assert "lock held" in result.stderr
        assert self._commit_count(data_dir) == before, (
            "commit-data.sh committed while the daily-sync lock was held"
        )

    def test_refuses_on_a_detached_head_in_the_data_submodule(
        self, pa_with_data_remote: Path
    ) -> None:
        """S20: ``git submodule update`` leaves the submodule detached; a
        commit made there is orphaned by the next checkout."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        _git("checkout", "--quiet", "--detach", "HEAD", cwd=data_dir)
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')
        before = self._commit_count(data_dir)

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode != 0
        assert "not 'main'" in result.stderr
        assert self._commit_count(data_dir) == before

    def test_parent_pointer_bump_is_not_committed_off_main(
        self, pa_with_data_remote: Path
    ) -> None:
        """S20: with the parent guard gone, the pointer bump lands on a branch
        that is never published — the orphaned-bump shape the guard exists to
        prevent."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')
        _git("checkout", "--quiet", "-b", "feature/x", cwd=pa_dir)
        before = self._commit_count(pa_dir)

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 0, result.stderr
        assert "WARNING: parent repo is on branch 'feature/x'" in result.stderr
        assert self._commit_count(pa_dir) == before, (
            "the submodule pointer bump was committed on a feature branch"
        )
        # The data half still went through — only the parent bump is withheld.
        assert self._commit_count(data_dir) == 2

    # ---- re-audit of PR #114 (2026-09-08) ----------------------------------

    def test_refuses_when_the_data_submodule_is_mid_merge(
        self, pa_with_data_remote: Path
    ) -> None:
        """CRITICAL. Every commit here names a pathspec, so it is a PARTIAL
        commit, which git refuses during a merge — but only after ``git add``
        has staged the paths. The run then dies with the paths staged, and
        every later run sees no UNSTAGED change, says "No data changes to
        commit." and exits 0 with the data uncommitted: a latched silent
        no-op. The guard must fire BEFORE anything is staged."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        (data_dir / "conflict.txt").write_text("base\n")
        _git("add", "conflict.txt", cwd=data_dir)
        _git("commit", "--quiet", "-m", "base", cwd=data_dir)
        _git("checkout", "--quiet", "-b", "other", cwd=data_dir)
        (data_dir / "conflict.txt").write_text("theirs\n")
        _git("commit", "--quiet", "-am", "theirs", cwd=data_dir)
        _git("checkout", "--quiet", "main", cwd=data_dir)
        (data_dir / "conflict.txt").write_text("ours\n")
        _git("commit", "--quiet", "-am", "ours", cwd=data_dir)
        _git("merge", "other", cwd=data_dir)          # conflicts, on purpose
        assert (data_dir / ".git" / "MERGE_HEAD").exists()
        (data_dir / "conflict.txt").write_text("resolved\n")
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 2, result.stdout + result.stderr
        assert "unfinished merge/rebase" in result.stderr
        # Nothing was staged: the new file is still untracked.
        porcelain = _git("status", "--porcelain", cwd=data_dir).stdout
        assert "?? memories.jsonl" in porcelain, (
            f"the guard staged something before refusing:\n{porcelain}"
        )

    def test_refuses_to_report_success_on_a_latched_staged_state(
        self, pa_with_data_remote: Path
    ) -> None:
        """CRITICAL, second half. The state a died-mid-commit run leaves
        behind: paths staged, working tree clean. The old code found no
        unstaged change and exited 0 — reporting success on data that was
        neither committed nor pushed, forever."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')
        _git("add", "memories.jsonl", cwd=data_dir)   # staged, tree now clean

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 3, (
            f"a staged-but-uncommitted store must not exit 0; got "
            f"rc={result.returncode}\n{result.stdout}\n{result.stderr}"
        )
        assert "memories.jsonl" in result.stderr
        assert self._commit_count(data_dir) == 1
        staged = _git("diff", "--cached", "--name-only", cwd=data_dir).stdout.split()
        assert staged == ["memories.jsonl"], "the staged work was discarded"

    def test_metacharacter_filename_does_not_sweep_a_lookalike(
        self, pa_with_data_remote: Path
    ) -> None:
        """MEDIUM. A pathspec is a GLOB by default, so the real filename
        ``weird[1].md`` matched a concurrent session's staged ``weird1.md``
        and committed it too. ``--pathspec-file-nul`` does not help — it makes
        the file FORMAT literal, not the matching; ``--literal-pathspecs``
        does."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        (data_dir / "weird[1].md").write_text("ours\n")
        (data_dir / "weird1.md").write_text("theirs\n")
        _git("add", "-A", cwd=data_dir)
        _git("commit", "--quiet", "-m", "add both", cwd=data_dir)
        (data_dir / "weird[1].md").write_text("ours, edited\n")     # this run
        (data_dir / "weird1.md").write_text("theirs, in progress\n")
        _git("add", "weird1.md", cwd=data_dir)                      # other session

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        committed = _git("show", "--name-only", "--pretty=format:", "HEAD",
                         cwd=data_dir).stdout.split()
        assert committed == ["weird[1].md"], (
            f"the glob pathspec swept a lookalike: {committed}"
        )
        staged = _git("diff", "--cached", "--name-only", cwd=data_dir).stdout.split()
        assert staged == ["weird1.md"]

    def test_withheld_staged_work_is_named_not_hidden(
        self, pa_with_data_remote: Path
    ) -> None:
        """MEDIUM. The old pathspec-filtered ``git status --short -- <paths>``
        hid withheld staged work: a fully staged ``git mv`` vanished from the
        listing and the run still ended with "Done"."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        (data_dir / "prose.md").write_text("a note\n")
        _git("add", "prose.md", cwd=data_dir)
        _git("commit", "--quiet", "-m", "prose", cwd=data_dir)
        # Another session's fully staged rename: nothing unstaged to see.
        _git("mv", "prose.md", "prose-renamed.md", cwd=data_dir)
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "prose.md" in result.stdout, (
            f"the withheld staged rename was never shown:\n{result.stdout}"
        )
        assert "still staged" in result.stdout.lower()
        committed = _git("show", "--name-only", "--pretty=format:", "HEAD",
                         cwd=data_dir).stdout.split()
        assert committed == ["memories.jsonl"]
        # Rename detection reports the new name only; the staged rename is
        # intact and still the other session's to commit.
        status = _git("status", "--short", cwd=data_dir).stdout
        assert "R  prose.md -> prose-renamed.md" in status

    # ---- second re-audit of PR #114 (2026-09-08) ----

    def test_refuses_on_unmerged_index_entries_without_a_marker_file(
        self, pa_with_data_remote: Path
    ) -> None:
        """CRITICAL (second re-audit). A conflicted ``git stash pop`` leaves
        unmerged index entries but no MERGE_HEAD; the marker-file guard let the
        run stage the conflict markers, commit them, push, and exit 0."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        (data_dir / "notes.md").write_text("seed\n")            # not the usual fixture name
        _git("add", "notes.md", cwd=data_dir)
        _git("commit", "--quiet", "-m", "base", cwd=data_dir)
        (data_dir / "notes.md").write_text("seed\nstashed\n")
        _git("stash", "push", "--quiet", cwd=data_dir)
        (data_dir / "notes.md").write_text("seed\nother\n")
        _git("commit", "--quiet", "-am", "other", cwd=data_dir)
        pop = subprocess.run(["git", "stash", "pop"], cwd=data_dir,
                             capture_output=True, text=True)
        assert pop.returncode != 0 and not (data_dir / ".git" / "MERGE_HEAD").exists()
        # Would be staged if the guard leaked:
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 2, result.stdout + result.stderr
        assert "unmerged" in result.stderr
        assert "<<<<<<<" in (data_dir / "notes.md").read_text()          # untouched
        assert "?? memories.jsonl" in _git("status", "--porcelain", cwd=data_dir).stdout
        assert self._commit_count(data_dir) == 3                        # seed, base, other
        remote = pa_dir.parent / "data.git"
        assert _git("rev-list", "--count", "main", cwd=remote).stdout.strip() == "1"

    def test_latched_state_remedy_never_advises_a_bare_reset(
        self, pa_with_data_remote: Path
    ) -> None:
        """MEDIUM (second re-audit). The printed remedy said ``git -C data reset``,
        which unstages another session's work so the re-run sweeps it — the
        very sweep the pathspec work exists to prevent."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        (data_dir / "their-draft.md").write_text("another session's\n")
        _git("add", "their-draft.md", cwd=data_dir)

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 3
        assert "reset -- <path>" in result.stderr
        assert not re.search(r"reset(?!\s+--\s)", result.stderr.replace("bare reset", "")), (
            result.stderr)

    def test_stale_parent_pointer_is_bumped_when_data_is_already_pushed(
        self, pa_with_data_remote: Path
    ) -> None:
        """MEDIUM (second re-audit). A run that committed and pushed the data
        submodule and died before the pointer bump left the parent stale, and
        every later run said "No data changes to commit." and exited 0."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        _git("-c", "advice.addEmbeddedRepo=false", "add", "data", cwd=pa_dir)
        _git("commit", "--quiet", "-m", "record pointer", cwd=pa_dir)
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')
        _git("add", "memories.jsonl", cwd=data_dir)
        _git("commit", "--quiet", "-m", "dead run's data commit", cwd=data_dir)
        _git("push", "--quiet", "origin", "HEAD:main", cwd=data_dir)
        assert _git("status", "--porcelain", "--", "data", cwd=pa_dir).stdout.strip()

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "stale" in result.stdout
        assert _git("log", "-1", "--format=%s", cwd=pa_dir).stdout.strip() == (
            "chore: update data submodule reference")
        assert _git("rev-parse", "HEAD:data", cwd=pa_dir).stdout.strip() == (
            _git("rev-parse", "HEAD", cwd=data_dir).stdout.strip())
        assert _git("status", "--porcelain", "--", "data", cwd=pa_dir).stdout.strip() == ""

    def test_stale_pointer_with_unpushed_data_refuses(
        self, pa_with_data_remote: Path
    ) -> None:
        """The other half: a stale pointer whose data commit never reached
        origin must not be bumped (origin would name an unfetchable commit)."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        _git("-c", "advice.addEmbeddedRepo=false", "add", "data", cwd=pa_dir)
        _git("commit", "--quiet", "-m", "record pointer", cwd=pa_dir)
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')
        _git("add", "memories.jsonl", cwd=data_dir)
        _git("commit", "--quiet", "-m", "unpushed", cwd=data_dir)

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 3
        assert "not on origin/main" in result.stderr
        assert "record pointer" == _git("log", "-1", "--format=%s", cwd=pa_dir).stdout.strip()
        remote = pa_dir.parent / "data.git"
        assert _git("rev-list", "--count", "main", cwd=remote).stdout.strip() == "1"

    # ---- third re-audit of PR #114 (2026-09-08) ----

    def test_parent_ahead_of_the_data_checkout_is_never_rolled_back(
        self, pa_with_data_remote: Path
    ) -> None:
        """CRITICAL (third re-audit). A parent pulled without `git submodule
        update` records a NEWER pointer than the checkout; the bump rewrote it
        backwards, rolling every other machine's data back a commit."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')
        _git("add", "memories.jsonl", cwd=data_dir)
        _git("commit", "--quiet", "-m", "c2", cwd=data_dir)
        _git("push", "--quiet", "origin", "HEAD:main", cwd=data_dir)
        _git("-c", "advice.addEmbeddedRepo=false", "add", "data", cwd=pa_dir)
        _git("commit", "--quiet", "-m", "parent records c2", cwd=pa_dir)
        newer = _git("rev-parse", "HEAD", cwd=data_dir).stdout.strip()
        _git("reset", "--quiet", "--hard", "HEAD~1", cwd=data_dir)   # checkout behind

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "not behind" in result.stdout
        assert _git("rev-parse", "HEAD:data", cwd=pa_dir).stdout.strip() == newer
        assert _git("log", "-1", "--format=%s", cwd=pa_dir).stdout.strip() == "parent records c2"

    def test_data_tracked_as_plain_files_is_never_committed_into_the_parent(
        self, tmp_path: Path
    ) -> None:
        """MEDIUM (third re-audit): with data/ tracked as ordinary files, the
        bump committed the private submodule's contents into the parent. The
        state arises when the parent tracked data/ BEFORE it became a
        repository (git ignores paths inside a nested repository afterwards,
        so the fixture builds it in that order)."""
        pa_dir = tmp_path / "pa"
        (pa_dir / "scripts").mkdir(parents=True)
        (pa_dir / "scripts" / "commit-data.sh").symlink_to(COMMIT_DATA_SCRIPT)
        data_dir = pa_dir / "data"
        data_dir.mkdir()
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')
        _git("init", "--quiet", "--initial-branch=main", cwd=pa_dir)
        _git("add", "data/memories.jsonl", cwd=pa_dir)           # plain file, pre-repository
        _git("commit", "--quiet", "-m", "wrongly tracked", cwd=pa_dir)
        data_remote = tmp_path / "data.git"
        data_remote.mkdir()
        _git("init", "--bare", "--quiet", "--initial-branch=main", cwd=data_remote)
        _git("init", "--quiet", "--initial-branch=main", cwd=data_dir)
        _git("add", "memories.jsonl", cwd=data_dir)
        _git("commit", "--quiet", "-m", "data", cwd=data_dir)
        _git("remote", "add", "origin", str(data_remote), cwd=data_dir)
        _git("push", "--quiet", "origin", "main", cwd=data_dir)
        assert _git("ls-files", "-s", "--", "data", cwd=pa_dir).stdout.startswith("100644")
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n{"id": "m2"}\n')

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 2, result.stdout + result.stderr
        assert "ordinary files" in result.stderr
        assert _git("log", "-1", "--format=%s", cwd=pa_dir).stdout.strip() == "wrongly tracked"

    def test_bisect_in_progress_is_refused_before_staging(
        self, pa_with_data_remote: Path
    ) -> None:
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        _git("bisect", "start", cwd=data_dir)
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 2
        assert "?? memories.jsonl" in _git("status", "--porcelain", cwd=data_dir).stdout

    # ---- fourth re-audit of PR #114 (2026-09-08): the untested guards ----

    def test_plain_file_guard_fires_before_anything_is_pushed(self, tmp_path: Path) -> None:
        """The guard used to sit in the parent half, AFTER the data commit and push,
        so exit 2 no longer meant 'nothing happened'."""
        pa_dir = tmp_path / "pa"
        (pa_dir / "scripts").mkdir(parents=True)
        (pa_dir / "scripts" / "commit-data.sh").symlink_to(COMMIT_DATA_SCRIPT)
        data_dir = pa_dir / "data"
        data_dir.mkdir()
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')
        _git("init", "--quiet", "--initial-branch=main", cwd=pa_dir)
        _git("add", "data/memories.jsonl", cwd=pa_dir)
        _git("commit", "--quiet", "-m", "wrongly tracked", cwd=pa_dir)
        data_remote = tmp_path / "data.git"
        data_remote.mkdir()
        _git("init", "--bare", "--quiet", "--initial-branch=main", cwd=data_remote)
        _git("init", "--quiet", "--initial-branch=main", cwd=data_dir)
        _git("add", "memories.jsonl", cwd=data_dir)
        _git("commit", "--quiet", "-m", "data", cwd=data_dir)
        _git("remote", "add", "origin", str(data_remote), cwd=data_dir)
        _git("push", "--quiet", "origin", "main", cwd=data_dir)
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n{"id": "m2"}\n')

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 2
        assert "Committing these paths" not in result.stdout
        assert self._commit_count(data_dir) == 1                        # nothing committed
        assert _git("rev-list", "--count", "main", cwd=data_remote).stdout.strip() == "1"

    def test_parent_bump_commit_leaves_another_sessions_staged_parent_file_alone(
        self, pa_with_data_remote: Path
    ) -> None:
        """Kills: dropping `-- data` from the parent bump commit (the staged parent
        file rode along under the bump's message)."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        (pa_dir / "NOTES.md").write_text("another session's parent edit\n")
        _git("add", "NOTES.md", cwd=pa_dir)
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        shown = _git("show", "--stat", "--format=", "HEAD", cwd=pa_dir).stdout
        assert "data" in shown and "NOTES.md" not in shown
        assert "NOTES.md" in _git("diff", "--cached", "--name-only", cwd=pa_dir).stdout

    def test_unborn_parent_is_handled_after_the_data_push(self, tmp_path: Path) -> None:
        """Kills: removing the unborn-HEAD guard (the branch query died with rc 128
        after the data had been pushed)."""
        pa_dir = tmp_path / "pa"
        (pa_dir / "scripts").mkdir(parents=True)
        (pa_dir / "scripts" / "commit-data.sh").symlink_to(COMMIT_DATA_SCRIPT)
        data_remote = tmp_path / "data.git"
        data_remote.mkdir()
        _git("init", "--bare", "--quiet", "--initial-branch=main", cwd=data_remote)
        data_dir = pa_dir / "data"
        data_dir.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=data_dir)
        (data_dir / "seed.txt").write_text("seed\n")
        _git("add", "seed.txt", cwd=data_dir)
        _git("commit", "--quiet", "-m", "seed", cwd=data_dir)
        _git("remote", "add", "origin", str(data_remote), cwd=data_dir)
        _git("push", "--quiet", "origin", "main", cwd=data_dir)
        _git("init", "--quiet", "--initial-branch=main", cwd=pa_dir)      # no commit
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "no commit yet" in result.stdout
        assert _git("rev-list", "--count", "main", cwd=data_remote).stdout.strip() == "2"

    def test_stale_tracking_ref_does_not_cause_a_false_refusal(
        self, pa_with_data_remote: Path
    ) -> None:
        """Kills: dropping the `fetch` before the on-origin check (a commit that IS on
        the remote but not in the stale origin/main ref gave a false exit 3)."""
        pa_dir = pa_with_data_remote
        data_dir = pa_dir / "data"
        _git("-c", "advice.addEmbeddedRepo=false", "add", "data", cwd=pa_dir)
        _git("commit", "--quiet", "-m", "record pointer", cwd=pa_dir)
        (data_dir / "memories.jsonl").write_text('{"id": "m1"}\n')
        _git("add", "memories.jsonl", cwd=data_dir)
        _git("commit", "--quiet", "-m", "pushed elsewhere", cwd=data_dir)
        _git("push", "--quiet", "origin", "HEAD:main", cwd=data_dir)
        old = _git("rev-parse", "HEAD~1", cwd=data_dir).stdout.strip()
        _git("update-ref", "refs/remotes/origin/main", old, cwd=data_dir)   # stale ref

        result = _run_script(pa_dir / "scripts" / "commit-data.sh", "test-msg",
                             home=pa_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "already on origin" in result.stdout
        assert "already-pushed data commit" in result.stdout            # the final line


# ----------------------------------------------------------------------------
# AR17 — push-archives-to-r2.sh: read .env, never execute it; never overwrite
# ----------------------------------------------------------------------------


class TestR2PushSafety:
    """The offsite push handled credentials and overwrites unsafely.

    ``set -a; . "$ENV_FILE"; set +a`` EXECUTED the .env file — command
    substitutions in it would run — and exported every secret it contained
    into the environment of rclone, df, and grep. And ``rclone copy`` with
    ``--s3-disable-checksum`` decides "changed" on size and modtime, so a
    truncated canonical file with a fresh mtime overwrote the last good
    offsite copy of a session that can no longer be recovered from anywhere.

    Nothing here contacts R2: ``rclone`` and ``df`` are stubs on PATH that
    record their arguments and environment.
    """

    @pytest.fixture()
    def sandbox(self, tmp_path: Path):
        """A fake PA tree, a mounted-looking canonical, and stub binaries."""
        pa_dir = tmp_path / "pa"
        (pa_dir / "scripts").mkdir(parents=True)
        (pa_dir / "scripts" / "push-archives-to-r2.sh").symlink_to(R2_PUSH_SCRIPT)

        home = tmp_path / "home"
        canonical = home / "mnt" / "rpi-shares" / "cc-archives-consolidated"
        canonical.mkdir(parents=True)

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        argv_log = tmp_path / "rclone-argv.txt"
        env_log = tmp_path / "rclone-env.txt"

        rclone = bin_dir / "rclone"
        rclone.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "version" ]]; then echo "rclone v1.68.2"; exit 0; fi\n'
            'if [[ "$1" == "listremotes" ]]; then echo "r2archives:"; exit 0; fi\n'
            f'printf "%s\\n" "$@" > {argv_log}\n'
            f"env > {env_log}\n"
            "exit 0\n",
            encoding="utf-8",
        )
        rclone.chmod(0o755)

        # A df that claims the mount is live, so the run reaches the transfer.
        df_stub = bin_dir / "df"
        df_stub.write_text(
            "#!/usr/bin/env bash\n"
            'echo "Filesystem Size Used Avail Use% Mounted on"\n'
            'echo "//rpi-server/shares 100G 1G 99G 1% /mnt"\n',
            encoding="utf-8",
        )
        df_stub.chmod(0o755)

        return SimpleNamespace(
            script=pa_dir / "scripts" / "push-archives-to-r2.sh",
            pa_dir=pa_dir, home=home, bin_dir=bin_dir,
            argv_log=argv_log, env_log=env_log, rclone=rclone,
            canonical=canonical, tmp_path=tmp_path,
        )

    #: Invented credentials, supplied unless a test is about their absence.
    AMBIENT_CREDENTIALS = {
        "RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID": "ambient-id-invented",
        "RCLONE_CONFIG_R2ARCHIVES_SECRET_ACCESS_KEY": "ambient-secret-invented",
    }

    def _run(self, sandbox, *args: str, credentials: bool = True, **extra):
        env = {
            "RCLONE_BIN": str(sandbox.rclone),
            "PATH": f"{sandbox.bin_dir}:{os.environ['PATH']}",
        }
        if credentials:
            env.update(self.AMBIENT_CREDENTIALS)
        env.update(extra)
        return _run_script(
            sandbox.script, *args, home=sandbox.home, extra_env=env
        )

    def _argv(self, sandbox) -> list[str]:
        assert sandbox.argv_log.exists(), "rclone was never invoked"
        return sandbox.argv_log.read_text(encoding="utf-8").split("\n")

    def test_dry_run_reaches_rclone_with_dry_run(self, sandbox) -> None:
        """--dry-run must survive all the way to the transfer's argv."""
        result = self._run(sandbox, "--dry-run")

        assert result.returncode == 0, result.stdout + result.stderr
        argv = self._argv(sandbox)
        assert argv[0] == "copy"
        assert "--dry-run" in argv

    def test_the_transfer_refuses_to_modify_an_existing_object(
        self, sandbox
    ) -> None:
        """An append-only archive: a changed object is corruption, not news."""
        assert self._run(sandbox).returncode == 0
        assert "--immutable" in self._argv(sandbox)

    @pytest.mark.parametrize("args", [(), ("--dry-run",)])
    def test_the_subcommand_is_always_copy_never_sync(
        self, sandbox, args
    ) -> None:
        """``sync`` deletes from the destination; ``copy`` never does.

        The header promises "Never deletes from R2. These are open-science
        records we never want to lose". One word in the invocation inverts
        that: `rclone sync` removes every object in the bucket that is absent
        locally, so a canonical store that failed to mount, or one session
        deliberately pruned, would take the offsite copies with it. Only the
        dry-run branch asserted the subcommand, so the real branch could be
        switched with the whole R2 suite green (round 4c-2, finding 17).
        """
        assert self._run(sandbox, *args).returncode == 0

        argv = self._argv(sandbox)
        assert argv[0] == "copy", (
            f"the transfer ran `rclone {argv[0]}`; sync deletes from R2"
        )
        assert "sync" not in argv

    @pytest.mark.parametrize("args", [(), ("--dry-run",)])
    def test_no_deletion_flag_ever_reaches_rclone(self, sandbox, args) -> None:
        """--delete-during and friends turn copy into sync by the back door."""
        assert self._run(sandbox, *args).returncode == 0

        offenders = [
            argument for argument in self._argv(sandbox)
            if argument.startswith("--delete")
        ]
        assert offenders == [], f"deletion flags reached rclone: {offenders}"

    def test_an_unmounted_canonical_refuses(self, sandbox) -> None:
        """The silent-empty-dir state must stop the push, not push nothing."""
        quiet_df = sandbox.bin_dir / "df"
        quiet_df.write_text(
            "#!/usr/bin/env bash\necho 'tmpfs 1G 0 1G 0% /tmp'\n",
            encoding="utf-8",
        )
        quiet_df.chmod(0o755)

        result = self._run(sandbox)

        assert result.returncode == 1
        assert "not mounted" in (result.stdout + result.stderr)
        assert not sandbox.argv_log.exists(), "a transfer ran anyway"

    def test_a_command_substitution_in_env_is_never_executed(
        self, sandbox
    ) -> None:
        """.env is read as text. It used to be executed as a shell script."""
        marker = sandbox.tmp_path / "SHOULD-NOT-EXIST"
        (sandbox.pa_dir / ".env").write_text(
            "# invented credentials for this test\n"
            f'RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID=$(touch {marker})\n'
            'RCLONE_CONFIG_R2ARCHIVES_SECRET_ACCESS_KEY="s3cret-not-real"\n',
            encoding="utf-8",
        )

        assert self._run(sandbox, credentials=False).returncode == 0

        assert not marker.exists(), (
            "sourcing .env executed a command substitution inside it"
        )
        env_text = sandbox.env_log.read_text(encoding="utf-8")
        assert (
            f"RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID=$(touch {marker})"
            in env_text
        ), "the value was not passed through literally"

    def test_only_the_two_r2_variables_are_exported(self, sandbox) -> None:
        """Every other secret in .env used to reach every child process.

        The assertions are on the .env FILE's values, not on variable names:
        a name like ANTHROPIC_API_KEY may legitimately already be in the
        ambient environment, and this fix is about what sourcing the file
        added on top of it.
        """
        (sandbox.pa_dir / ".env").write_text(
            "OPENAI_API_KEY=sk-invented-value-from-dot-env\n"
            "ANTHROPIC_API_KEY=ant-invented-value-from-dot-env\n"
            'RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID="r2-id-invented"\n'
            "RCLONE_CONFIG_R2ARCHIVES_SECRET_ACCESS_KEY='r2-secret-invented'\n",
            encoding="utf-8",
        )

        assert self._run(sandbox, credentials=False).returncode == 0

        env_text = sandbox.env_log.read_text(encoding="utf-8")
        assert "sk-invented-value-from-dot-env" not in env_text, (
            "a non-R2 secret from .env reached the transfer's environment"
        )
        assert "ant-invented-value-from-dot-env" not in env_text
        # The two that are needed arrive, with their quotes stripped.
        assert "RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID=r2-id-invented" in env_text
        assert (
            "RCLONE_CONFIG_R2ARCHIVES_SECRET_ACCESS_KEY=r2-secret-invented"
            in env_text
        )

    def test_an_ambient_credential_is_not_overwritten_by_env(
        self, sandbox
    ) -> None:
        """The loader is idempotent: what is already exported wins."""
        (sandbox.pa_dir / ".env").write_text(
            "RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID=from-dot-env\n",
            encoding="utf-8",
        )
        result = self._run(
            sandbox, credentials=False,
            RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID="from-ambient",
            RCLONE_CONFIG_R2ARCHIVES_SECRET_ACCESS_KEY="secret-invented",
        )

        assert result.returncode == 0
        env_text = sandbox.env_log.read_text(encoding="utf-8")
        assert "RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID=from-ambient" in env_text

    def test_a_missing_credential_refuses_before_any_transfer(
        self, sandbox
    ) -> None:
        """No keys is not "an rclone error"; it is "do not start".

        Without this an unreadable .env, or one that has lost the R2 lines,
        sailed past every precondition and ran a real copy with no
        credentials: thousands of 403s against the retry budget, and an exit
        code that blamed rclone (round 4c-2, finding 10).
        """
        result = self._run(sandbox, credentials=False)

        assert result.returncode == 2, result.stdout + result.stderr
        combined = result.stdout + result.stderr
        assert "missing R2 credential" in combined
        assert not sandbox.argv_log.exists(), (
            "a transfer was attempted with no credentials"
        )

    def test_one_credential_alone_is_not_enough(self, sandbox) -> None:
        result = self._run(
            sandbox, credentials=False,
            RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID="only-the-id",
        )

        assert result.returncode == 2
        assert "SECRET_ACCESS_KEY" in result.stdout + result.stderr
        assert not sandbox.argv_log.exists()

    def test_a_trailing_comment_is_not_part_of_the_secret(
        self, sandbox
    ) -> None:
        """`KEY=value   # note` is a comment, not eight more characters."""
        (sandbox.pa_dir / ".env").write_text(
            "RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID=r2-id-invented   "
            "# rotated 2026-03-02\n"
            "RCLONE_CONFIG_R2ARCHIVES_SECRET_ACCESS_KEY=  r2-secret-invented  \n",
            encoding="utf-8",
        )

        assert self._run(sandbox, credentials=False).returncode == 0

        env_text = sandbox.env_log.read_text(encoding="utf-8")
        assert "RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID=r2-id-invented\n" in env_text
        assert (
            "RCLONE_CONFIG_R2ARCHIVES_SECRET_ACCESS_KEY=r2-secret-invented\n"
            in env_text
        )

    def test_a_hash_inside_a_quoted_secret_survives(self, sandbox) -> None:
        """The comment strip must not eat a '#' that is part of the key."""
        (sandbox.pa_dir / ".env").write_text(
            'RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID="r2#id#invented"\n'
            "RCLONE_CONFIG_R2ARCHIVES_SECRET_ACCESS_KEY='r2#secret'\n",
            encoding="utf-8",
        )

        assert self._run(sandbox, credentials=False).returncode == 0

        env_text = sandbox.env_log.read_text(encoding="utf-8")
        assert "RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID=r2#id#invented\n" in env_text

    def test_an_immutable_refusal_exits_three_and_says_so(
        self, sandbox
    ) -> None:
        """A changed canonical object is corruption, not a retryable blip."""
        sandbox.rclone.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "version" ]]; then echo "rclone v1.68.2"; exit 0; fi\n'
            'if [[ "$1" == "listremotes" ]]; then echo "r2archives:"; exit 0; fi\n'
            'echo "ERROR: session.jsonl.gz: Source and destination exist but '
            'do not match: immutable file modified" >> '
            f'{sandbox.pa_dir}/logs/r2-push.log\n'
            "exit 1\n",
            encoding="utf-8",
        )
        sandbox.rclone.chmod(0o755)

        result = self._run(sandbox)

        assert result.returncode == 3, result.stdout + result.stderr
        assert "ABORTED" in result.stdout + result.stderr

    def test_a_transport_failure_still_exits_two(self, sandbox) -> None:
        """The positive control: an ordinary failure stays retryable."""
        sandbox.rclone.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "version" ]]; then echo "rclone v1.68.2"; exit 0; fi\n'
            'if [[ "$1" == "listremotes" ]]; then echo "r2archives:"; exit 0; fi\n'
            'echo "ERROR: dial tcp: lookup failed" >> '
            f'{sandbox.pa_dir}/logs/r2-push.log\n'
            "exit 1\n",
            encoding="utf-8",
        )
        sandbox.rclone.chmod(0o755)

        result = self._run(sandbox)

        assert result.returncode == 2
        assert "safe to retry" in result.stdout + result.stderr


# ----------------------------------------------------------------------------
# ART5 — search-archives-safe.sh: the limits and the single-run lock
# ----------------------------------------------------------------------------


SEARCH_ARCHIVES_SCRIPT = REPO_ROOT / "scripts" / "search-archives-safe.sh"
SCAN_ENGINE_SCRIPT = REPO_ROOT / "scripts" / "_scan_archives.py"


class TestSearchArchivesSafety:
    """The wrapper written after the 2026-06-21 machine lock-up.

    Its whole job is the OS-level safety around the scan: nice, ionice, a
    hard timeout, and a non-blocking lock so a second search refuses instead
    of stacking (the amplifier that turned one bad pipeline into a frozen
    desktop). Both were removable with the full suite green.

    TMPDIR is pinned into the test tree so the lock file cannot collide with
    a concurrent suite run or with the operator's own search.
    """

    @pytest.fixture()
    def sandbox(self, tmp_path: Path):
        pa_dir = tmp_path / "pa"
        (pa_dir / "scripts").mkdir(parents=True)
        script = pa_dir / "scripts" / "search-archives-safe.sh"
        script.symlink_to(SEARCH_ARCHIVES_SCRIPT)
        (pa_dir / "scripts" / "_scan_archives.py").symlink_to(
            SCAN_ENGINE_SCRIPT
        )

        archive = tmp_path / "cc-archives" / "lantern-survey" / "2026-03-02_a"
        archive.mkdir(parents=True)
        import gzip as _gzip
        with _gzip.open(archive / "session.jsonl.gz", "wb") as handle:
            handle.write(
                b'{"type":"user","message":{"role":"user",'
                b'"content":"the LANTERN pattern"}}\n'
            )

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        return SimpleNamespace(
            script=script, archive_root=tmp_path / "cc-archives",
            home=tmp_path / "home", tmpdir=run_dir, tmp_path=tmp_path,
        )

    def _env(self, sandbox, **extra) -> dict[str, str]:
        env = {
            "TMPDIR": str(sandbox.tmpdir),
            "SAS_NO_CGROUP": "1",
            "SAS_TIMEOUT": "30",
        }
        env.update(extra)
        return env

    def test_a_normal_search_reports_path_and_line_number(
        self, sandbox
    ) -> None:
        sandbox.home.mkdir()
        result = _run_script(
            sandbox.script, "LANTERN", str(sandbox.archive_root),
            home=sandbox.home, extra_env=self._env(sandbox),
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert ":1:" in result.stdout, result.stdout

    def test_a_second_search_refuses_while_the_lock_is_held(
        self, sandbox
    ) -> None:
        """Exit 3 and REFUSED, not a queued second scan."""
        sandbox.home.mkdir()
        lock_path = sandbox.tmpdir / "cc-archive-search.lock"
        with open(lock_path, "w", encoding="utf-8") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                result = _run_script(
                    sandbox.script, "LANTERN", str(sandbox.archive_root),
                    home=sandbox.home, extra_env=self._env(sandbox),
                )
            finally:
                fcntl.flock(held.fileno(), fcntl.LOCK_UN)

        assert result.returncode == 3, result.stdout + result.stderr
        assert "REFUSED" in result.stderr

    def test_the_resource_limits_reach_the_executed_command(
        self, sandbox
    ) -> None:
        """nice, ionice, and timeout must be in the argv that actually runs."""
        sandbox.home.mkdir()
        bin_dir = sandbox.tmp_path / "bin"
        bin_dir.mkdir()
        argv_log = sandbox.tmp_path / "limit-argv.txt"
        stub = bin_dir / "nice"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$0" "$@" > {argv_log}\n'
            "exit 0\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)

        result = _run_script(
            sandbox.script, "LANTERN", str(sandbox.archive_root),
            home=sandbox.home,
            extra_env=self._env(
                sandbox, PATH=f"{bin_dir}:{os.environ['PATH']}"
            ),
        )

        assert argv_log.exists(), (
            "the scan ran without the nice/ionice/timeout wrapper: "
            + result.stdout + result.stderr
        )
        argv = argv_log.read_text(encoding="utf-8").split("\n")
        assert argv[1:3] == ["-n", "19"]
        assert "ionice" in argv
        assert "timeout" in argv
        assert "30" in argv, "the wall-clock kill was not passed through"
        assert any(a.endswith("_scan_archives.py") for a in argv)

    def test_a_missing_search_path_exits_two(self, sandbox) -> None:
        """A bad invocation must never look like 'no matches'."""
        sandbox.home.mkdir()
        result = _run_script(
            sandbox.script, "LANTERN", str(sandbox.tmp_path / "absent"),
            home=sandbox.home, extra_env=self._env(sandbox),
        )

        assert result.returncode == 2
        assert "path not found" in result.stderr
