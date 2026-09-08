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
submodule or ``~/.claude`` tree.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMIT_DATA_SCRIPT = REPO_ROOT / "scripts" / "commit-data.sh"
SYNC_SYMLINKS_SCRIPT = REPO_ROOT / "scripts" / "sync-symlinks.sh"
DAILY_SYNC_SCRIPT = REPO_ROOT / "scripts" / "daily-sync.sh"


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
# daily-sync.sh — parent-repo branch guard (Batch 11 Medium)
# ============================================================================


class TestDailySyncParentBranchGuard:
    """``daily-sync.sh`` must guard the parent-repo half against running
    on a non-main branch, mirroring the data-submodule guard at
    line 268-275 and the parallel guard in ``commit-data.sh``.

    The previous implementation had no parent-branch check, so a
    daily-sync invoked from a feature branch in the parent would
    silently FF-pull origin/main into the feature branch, commit the
    submodule pointer bump there, and push the (unchanged) local main —
    orphaning the bump on a branch that is never published. Same shape
    as the ``commit-data.sh`` push-to-wrong-branch bug fixed in
    ``db957e5``; calibration audit 2026-05-02 found this residual gap.
    """

    @pytest.fixture()
    def fake_pa_with_remote(self, tmp_path: Path) -> Path:
        """Build a fake personal-assistant tree with bare-repo remotes
        for both the parent and the data submodule, so the script's
        ``git pull --ff-only origin main`` calls succeed.

        Returns the parent working copy. The parent starts on a feature
        branch named ``feature/x``; ``main`` exists locally and on the
        bare remote so the branch-switch path can complete successfully.
        """
        # Bare remotes for both halves of the sync.
        data_remote = tmp_path / "data.git"
        parent_remote = tmp_path / "parent.git"
        data_remote.mkdir()
        parent_remote.mkdir()
        _git("init", "--bare", "--quiet", "--initial-branch=main", cwd=data_remote)
        _git("init", "--bare", "--quiet", "--initial-branch=main", cwd=parent_remote)

        # Data working copy (will become the submodule).
        data_src = tmp_path / "data-src"
        data_src.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=data_src)
        (data_src / "seed.txt").write_text("seed\n")
        (data_src / "config").mkdir()
        (data_src / "config" / "sync.json").write_text("{}\n")
        _git("add", "-A", cwd=data_src)
        _git("commit", "--quiet", "-m", "seed data", cwd=data_src)
        _git("remote", "add", "origin", str(data_remote), cwd=data_src)
        _git("push", "--quiet", "origin", "main", cwd=data_src)

        # Parent working copy.
        pa_dir = tmp_path / "pa"
        pa_dir.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=pa_dir)
        # Symlink the script under test in.
        (pa_dir / "scripts").mkdir()
        (pa_dir / "scripts" / "daily-sync.sh").symlink_to(DAILY_SYNC_SCRIPT)
        (pa_dir / "scripts" / "resolve-merge-conflicts.py").symlink_to(
            REPO_ROOT / "scripts" / "resolve-merge-conflicts.py"
        )
        (pa_dir / "scripts" / "sync-symlinks.sh").symlink_to(
            REPO_ROOT / "scripts" / "sync-symlinks.sh"
        )
        (pa_dir / "scripts" / "compose-global-claude-md.sh").write_text(
            "#!/usr/bin/env bash\nexit 0\n"
        )
        (pa_dir / "scripts" / "compose-global-claude-md.sh").chmod(0o755)

        # venv stub: daily-sync.sh references "$PA_DIR/venv/bin/python3"
        # only on the resolver path, which we won't hit in this test.
        (pa_dir / "venv" / "bin").mkdir(parents=True)
        (pa_dir / "venv" / "bin" / "python3").symlink_to("/usr/bin/python3")

        # Add the data submodule. Use file:// URL so submodule add works.
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
        subprocess.run(
            [
                "git",
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                "--quiet",
                str(data_remote),
                "data",
            ],
            cwd=str(pa_dir),
            env=env,
            check=True,
            capture_output=True,
        )
        _git("commit", "--quiet", "-m", "add data submodule", cwd=pa_dir)
        _git("remote", "add", "origin", str(parent_remote), cwd=pa_dir)
        _git("push", "--quiet", "origin", "main", cwd=pa_dir)

        # Switch the parent to a feature branch so the new guard fires.
        _git("checkout", "--quiet", "-b", "feature/x", cwd=pa_dir)

        return pa_dir

    def test_parent_on_feature_branch_switches_to_main(
        self, fake_pa_with_remote: Path
    ) -> None:
        """When the parent repo is on a feature branch, daily-sync must
        log the switch-to-main message and end on main, not silently
        operate on the feature branch."""
        pa_dir = fake_pa_with_remote

        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": "Test Bot",
                "GIT_AUTHOR_EMAIL": "test@example.invalid",
                "GIT_COMMITTER_NAME": "Test Bot",
                "GIT_COMMITTER_EMAIL": "test@example.invalid",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_SYSTEM": "/dev/null",
                # Allow file:// submodule operations during the run.
                "GIT_ALLOW_PROTOCOL": "file",
            }
        )
        result = subprocess.run(
            ["bash", str(pa_dir / "scripts" / "daily-sync.sh")],
            cwd=str(pa_dir),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        # Combined log output is on stderr (via the `log` function).
        combined = result.stdout + result.stderr
        assert (
            "parent repo on 'feature/x' — switching to main" in combined
        ), (
            f"Expected branch-switch log line; got:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}\n"
            f"rc={result.returncode}"
        )
        # And the parent must actually be on main afterwards.
        post = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=pa_dir)
        assert post.stdout.strip() == "main", (
            f"Expected parent to be on main after sync; got "
            f"'{post.stdout.strip()}'"
        )

    def test_source_has_parent_branch_guard(self) -> None:
        """Defence in depth: the script source must contain the
        parent-branch guard. Catches accidental removal in future
        refactors."""
        source = DAILY_SYNC_SCRIPT.read_text(encoding="utf-8")
        # The guard checks the parent's current branch and either
        # switches or fails.
        assert "parent_current_branch" in source, (
            "daily-sync.sh missing parent-branch guard variable "
            "(Batch 11 Medium 2026-05-02)."
        )
        assert "failed to switch parent repo to main" in source, (
            "daily-sync.sh missing parent branch-switch failure path."
        )


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


