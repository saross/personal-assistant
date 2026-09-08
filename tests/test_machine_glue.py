"""
Behavioural tests for the machine-glue shell scripts.

These scripts run unattended — from cron, from ``daily-sync.sh``, and at
SessionStart — and between them they are the only code in the repository
that removes files from ``~/.claude``, initialises a git submodule,
installs packages, restarts a container, or overwrites the global
instruction file. Audit round 4d found the riskiest of those operations
completely uncovered (lens B, ET5/ET8-ET10/ET14-ET16).

Every test here runs the REAL script inside a sandbox:

  * ``HOME`` is pinned to a pytest ``tmp_path`` subdirectory;
  * the script is reached through a symlink inside a synthetic
    ``PA_DIR``, so ``SCRIPT_DIR``/``PA_DIR`` resolve into the sandbox
    while the code executed is byte-for-byte the code in ``scripts/``;
  * ``git``, ``pip``, ``docker``, and ``curl`` are stub executables that
    record their argv into a file and exit 0, placed first on ``PATH``;
  * no network is reachable and no real service is contacted.

All fixture content is invented.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

from no_network_guard import refuse_socket_connections

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse every socket connection made from the test process itself."""
    refuse_socket_connections(monkeypatch)


# ---------------------------------------------------------------------------
# Sandbox helpers
# ---------------------------------------------------------------------------


def write_stub(bin_dir: Path, name: str, log: Path, exit_code: int = 0) -> None:
    """
    Write an executable stub named ``name`` that records its argv.

    Args:
        bin_dir: Directory placed first on ``PATH``.
        name: Command to shadow (``git``, ``pip``, ``docker``, ``curl``).
        log: File each invocation appends one ``name arg arg`` line to.
        exit_code: Status the stub exits with.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / name
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s" {shlex.quote(name)} >> {shlex.quote(str(log))}\n'
        f'for a in "$@"; do printf " %s" "$a" >> {shlex.quote(str(log))}; done\n'
        f'printf "\\n" >> {shlex.quote(str(log))}\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)


def run_script(
    script: Path,
    *args: str,
    home: Path,
    path_prefix: Path | None = None,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run ``script`` with a pinned ``HOME`` and a stub-first ``PATH``.

    Args:
        script: The script (usually a symlink into ``scripts/``) to run.
        *args: Command-line arguments for the script.
        home: Directory to pin ``HOME`` to.
        path_prefix: Directory of stub executables, placed first on PATH.
        cwd: Working directory for the child process.
        extra_env: Additional environment variables.

    Returns:
        The completed process, with text streams captured.
    """
    env = dict(os.environ)
    env["HOME"] = str(home)
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}:{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else str(home),
        timeout=120,
    )


def snapshot(root: Path) -> set[str]:
    """Return every path under ``root`` as a set of relative strings."""
    return {
        str(p.relative_to(root))
        for p in root.rglob("*")
        # rglob does not descend into symlinked directories, which is what
        # we want: a link's *target* is not something the script created.
    }


# ---------------------------------------------------------------------------
# sync-symlinks.sh sandbox
# ---------------------------------------------------------------------------


@pytest.fixture
def sync_sandbox(tmp_path: Path) -> dict[str, Path]:
    """
    Build a synthetic ``PA_DIR`` and ``HOME`` for ``sync-symlinks.sh``.

    The sandbox carries one command, one skill, one agent, and one output
    style, plus the three composer sources, so all eight steps run. There
    is deliberately no ``venv/``, so step 8 warns instead of touching pip
    unless a test supplies a stub venv.
    """
    pa_dir = tmp_path / "pa"
    (pa_dir / "scripts").mkdir(parents=True)
    for name in ("sync-symlinks.sh", "compose-global-claude-md.sh"):
        (pa_dir / "scripts" / name).symlink_to(SCRIPTS / name)
    (pa_dir / "settings.json").write_text("{}\n", encoding="utf-8")
    (pa_dir / "commands").mkdir()
    (pa_dir / "commands" / "fossick.md").write_text(
        "# /fossick\n", encoding="utf-8"
    )
    (pa_dir / "skills" / "tally-sherds").mkdir(parents=True)
    (pa_dir / "skills" / "tally-sherds" / "SKILL.md").write_text(
        "# tally-sherds\n", encoding="utf-8"
    )
    (pa_dir / "agents").mkdir()
    (pa_dir / "agents" / "trench-scribe.md").write_text(
        "# trench-scribe\n", encoding="utf-8"
    )
    (pa_dir / "output-styles").mkdir()
    (pa_dir / "output-styles" / "terse.md").write_text(
        "# terse\n", encoding="utf-8"
    )
    (pa_dir / "global-agent-guidance").mkdir()
    (pa_dir / "global-agent-guidance" / "common.md").write_text(
        "# Shared\n\nCOMMON-SECTION\n", encoding="utf-8"
    )
    (pa_dir / "global-claude-md").mkdir()
    (pa_dir / "global-claude-md" / "claude.md").write_text(
        "# Overlay\n\nOVERLAY-SECTION\n", encoding="utf-8"
    )
    (pa_dir / "data" / "global-claude-md").mkdir(parents=True)
    (pa_dir / "data" / "global-claude-md" / "local.md").write_text(
        "# Local\n\nLOCAL-SECTION\n", encoding="utf-8"
    )
    (pa_dir / "requirements.txt").write_text(
        "anthropic\npsycopg2-binary\npytest\nmcp\npyzotero\n"
        "cc-session-toolkit @ git+ssh://git@example.invalid/toolkit.git@main\n",
        encoding="utf-8",
    )
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "stubbin"
    log = tmp_path / "argv.log"
    log.write_text("", encoding="utf-8")
    write_stub(bin_dir, "git", log)
    return {
        "pa_dir": pa_dir,
        "home": home,
        "bin": bin_dir,
        "log": log,
        "script": pa_dir / "scripts" / "sync-symlinks.sh",
    }


def _run_sync(
    sandbox: dict[str, Path], *args: str
) -> subprocess.CompletedProcess[str]:
    """Run the sandboxed ``sync-symlinks.sh`` with stubs on PATH."""
    return run_script(
        sandbox["script"],
        *args,
        home=sandbox["home"],
        path_prefix=sandbox["bin"],
        cwd=sandbox["pa_dir"],
    )


class TestPruneStaleSymlinks:
    """ET5 — the only ``rm`` in this tranche, previously untested.

    ``prune_stale_symlinks`` walks ``~/.claude/{commands,skills,agents,
    output-styles}``. Two one-line mutations survived the suite: ``[ -L ]``
    → ``[ -e ]`` and ``rm`` → ``rm -rf``. Together they would recursively
    delete real directories the operator had put there by hand.
    """

    def test_a_real_directory_is_left_alone(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A genuine directory under commands/ must survive untouched."""
        commands = sync_sandbox["home"] / ".claude" / "commands"
        commands.mkdir(parents=True)
        keep = commands / "hand-made"
        keep.mkdir()
        (keep / "note.md").write_text("mine\n", encoding="utf-8")

        result = _run_sync(sync_sandbox, "--quiet")

        assert result.returncode == 0, result.stderr
        assert keep.is_dir()
        assert (keep / "note.md").read_text(encoding="utf-8") == "mine\n"

    def test_a_real_file_is_left_alone(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A hand-written file under commands/ must survive untouched."""
        commands = sync_sandbox["home"] / ".claude" / "commands"
        commands.mkdir(parents=True)
        keep = commands / "notes.md"
        keep.write_text("hand written\n", encoding="utf-8")

        result = _run_sync(sync_sandbox, "--quiet")

        assert result.returncode == 0, result.stderr
        assert keep.read_text(encoding="utf-8") == "hand written\n"

    def test_a_symlink_pointing_outside_the_source_dir_is_left_alone(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """Only links INTO the repo's source directory are prunable."""
        commands = sync_sandbox["home"] / ".claude" / "commands"
        commands.mkdir(parents=True)
        outside = sync_sandbox["home"] / "elsewhere" / "gone.md"
        link = commands / "elsewhere.md"
        link.symlink_to(outside)  # dangling, but not into $PA_DIR/commands

        result = _run_sync(sync_sandbox, "--quiet")

        assert result.returncode == 0, result.stderr
        assert link.is_symlink(), "a link outside the source dir was pruned"

    def test_only_a_dangling_in_tree_symlink_is_removed(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A dangling link into commands/ goes; a live one stays."""
        commands = sync_sandbox["home"] / ".claude" / "commands"
        commands.mkdir(parents=True)
        stale = commands / "retired.md"
        stale.symlink_to(sync_sandbox["pa_dir"] / "commands" / "retired.md")
        live = commands / "fossick.md"
        live.symlink_to(sync_sandbox["pa_dir"] / "commands" / "fossick.md")

        result = _run_sync(sync_sandbox, "--quiet")

        assert result.returncode == 0, result.stderr
        assert not stale.is_symlink() and not stale.exists()
        assert live.is_symlink() and live.exists()

    def test_the_removal_carries_no_recursive_or_force_flag(self) -> None:
        """``rm`` in the prune must stay flagless.

        This one is a source-level assertion on purpose. ``rm -rf`` on a
        SYMLINK behaves exactly like ``rm`` — rm never follows a link —
        so the flag is invisible from the outside until it is paired with
        a second mutation (``[ -L ]`` → ``[ -e ]``, pinned above), at
        which point it recursively deletes real directories under
        ``~/.claude``. A latent flag that only becomes destructive in
        combination is worth pinning where it is written.
        """
        source = (SCRIPTS / "sync-symlinks.sh").read_text(encoding="utf-8")
        body = source.split("prune_stale_symlinks() {", 1)[1].split(
            "\nensure_symlink()", 1
        )[0]
        removals = [
            line.strip()
            for line in body.splitlines()
            if line.strip().startswith(("rm ", "rm -", "run_action rm"))
        ]
        assert removals == ['run_action rm "$link"'], removals

    def test_the_prune_does_not_follow_a_link_into_the_repo(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A live link to a whole skill directory must leave it intact."""
        skills = sync_sandbox["home"] / ".claude" / "skills"
        skills.mkdir(parents=True)
        # A link to a whole (now removed) skill directory — the case where
        # `rm -rf` on the link's *target* would be most destructive.
        target_dir = sync_sandbox["pa_dir"] / "skills" / "tally-sherds"
        live_link = skills / "tally-sherds"
        live_link.symlink_to(target_dir)
        payload = target_dir / "SKILL.md"

        result = _run_sync(sync_sandbox, "--quiet")

        assert result.returncode == 0, result.stderr
        assert payload.exists(), "the prune followed a link into the repo"


class TestRealFileNotASymlink:
    """ET11 — the "file exists, not a symlink → skip" branch (:120)."""

    def test_a_hand_written_settings_json_is_not_replaced(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """``~/.claude/settings.json`` written by hand must be preserved."""
        claude = sync_sandbox["home"] / ".claude"
        claude.mkdir(parents=True)
        settings = claude / "settings.json"
        settings.write_text('{"handwritten": true}\n', encoding="utf-8")

        result = _run_sync(sync_sandbox)

        assert result.returncode == 0, result.stderr
        assert not settings.is_symlink()
        assert settings.read_text(encoding="utf-8") == '{"handwritten": true}\n'
        assert "not a symlink" in result.stdout


class TestSubmoduleUpdateIsGated:
    """E10 — ``git submodule update`` must not run on an initialised data/.

    On an initialised submodule it checks out the recorded gitlink SHA,
    detaching ``data/`` from its branch and orphaning commits a concurrent
    session made there. This step exists only to populate an empty
    ``data/``.
    """

    def test_initialised_submodule_is_left_alone(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A non-empty data/ means no git invocation at all."""
        result = _run_sync(sync_sandbox, "--quiet")

        assert result.returncode == 0, result.stderr
        recorded = sync_sandbox["log"].read_text(encoding="utf-8")
        assert "submodule" not in recorded, recorded

    def test_uninitialised_submodule_is_initialised(
        self, sync_sandbox: dict[str, Path], tmp_path: Path
    ) -> None:
        """An empty data/ still gets `git submodule update --init`."""
        # Strip data/ back to an empty directory, the uninitialised shape,
        # and give the composer its local source from elsewhere so the
        # later steps still run.
        local = sync_sandbox["pa_dir"] / "data" / "global-claude-md"
        (local / "local.md").unlink()
        local.rmdir()
        (sync_sandbox["pa_dir"] / "data" / "global-claude-md").mkdir()
        (sync_sandbox["pa_dir"] / "data" / "global-claude-md").rmdir()

        result = _run_sync(sync_sandbox, "--quiet")

        recorded = sync_sandbox["log"].read_text(encoding="utf-8")
        assert "git submodule update --init --recursive --quiet" in recorded
        # The composer then fails on the missing local source, which is the
        # correct outcome for a genuinely uninitialised submodule.
        assert result.returncode != 0


class TestDependencyInstall:
    """E9 — never ``pip install --upgrade -r requirements.txt`` unattended."""

    @staticmethod
    def _fake_venv(pa_dir: Path, log: Path, missing: str) -> None:
        """Install a stub venv whose probe reports ``missing`` absent."""
        venv_bin = pa_dir / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        probe = venv_bin / "python3"
        probe.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "{missing}"\n'
            "exit 0\n",
            encoding="utf-8",
        )
        probe.chmod(0o755)
        write_stub(venv_bin, "pip", log)

    def test_only_the_missing_distribution_is_installed(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """pip is asked for the missing package, not the whole file."""
        self._fake_venv(
            sync_sandbox["pa_dir"], sync_sandbox["log"], "pyzotero"
        )

        result = _run_sync(sync_sandbox, "--quiet")

        assert result.returncode == 0, result.stderr
        recorded = sync_sandbox["log"].read_text(encoding="utf-8")
        assert "pip install --quiet pyzotero" in recorded, recorded
        assert "--upgrade" not in recorded
        assert "-r " not in recorded

    def test_the_git_specification_is_read_from_requirements(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A missing cc_session_toolkit installs its declared git+ssh spec."""
        self._fake_venv(
            sync_sandbox["pa_dir"], sync_sandbox["log"], "cc_session_toolkit"
        )

        result = _run_sync(sync_sandbox, "--quiet")

        assert result.returncode == 0, result.stderr
        recorded = sync_sandbox["log"].read_text(encoding="utf-8")
        assert "git+ssh://git@example.invalid/toolkit.git@main" in recorded
        assert "--upgrade" not in recorded

    def test_nothing_is_installed_when_all_probes_pass(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """An empty probe result means pip is never invoked."""
        self._fake_venv(sync_sandbox["pa_dir"], sync_sandbox["log"], "")

        result = _run_sync(sync_sandbox, "--quiet")

        assert result.returncode == 0, result.stderr
        assert "pip" not in sync_sandbox["log"].read_text(encoding="utf-8")


class TestSyncSymlinksDryRun:
    """E5 — ``--dry-run`` prints every action and performs none."""

    def test_dry_run_creates_nothing_and_prunes_nothing(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A dry run leaves the pinned HOME byte-for-byte as it was."""
        claude = sync_sandbox["home"] / ".claude"
        claude.mkdir(parents=True)
        commands = claude / "commands"
        commands.mkdir()
        stale = commands / "retired.md"
        stale.symlink_to(sync_sandbox["pa_dir"] / "commands" / "retired.md")
        self_ = TestDependencyInstall()
        self_._fake_venv(
            sync_sandbox["pa_dir"], sync_sandbox["log"], "pyzotero"
        )
        before = snapshot(sync_sandbox["home"])

        result = _run_sync(sync_sandbox, "--dry-run")

        assert result.returncode == 0, result.stderr
        assert snapshot(sync_sandbox["home"]) == before
        assert stale.is_symlink(), "--dry-run pruned a symlink"
        assert not (claude / "CLAUDE.md").exists()
        assert "pip" not in sync_sandbox["log"].read_text(encoding="utf-8")
        assert "would run:" in result.stdout

    def test_unknown_argument_is_a_usage_error(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A misspelt flag must not be silently ignored."""
        result = _run_sync(sync_sandbox, "--dryrun")

        assert result.returncode == 2
        assert "unknown argument" in result.stderr
        assert not (sync_sandbox["home"] / ".claude").exists()


# ---------------------------------------------------------------------------
# compose-global-claude-md.sh
# ---------------------------------------------------------------------------


@pytest.fixture
def compose_sandbox(tmp_path: Path) -> dict[str, Path]:
    """A synthetic PA_DIR carrying the composer's three sources."""
    pa_dir = tmp_path / "pa"
    (pa_dir / "scripts").mkdir(parents=True)
    (pa_dir / "scripts" / "compose-global-claude-md.sh").symlink_to(
        SCRIPTS / "compose-global-claude-md.sh"
    )
    (pa_dir / "global-agent-guidance").mkdir()
    (pa_dir / "global-agent-guidance" / "common.md").write_text(
        "# Shared guidance\n\nMARKER-COMMON\n", encoding="utf-8"
    )
    (pa_dir / "global-claude-md").mkdir()
    (pa_dir / "global-claude-md" / "claude.md").write_text(
        "# Claude overlay\n\nMARKER-OVERLAY\n", encoding="utf-8"
    )
    (pa_dir / "data" / "global-claude-md").mkdir(parents=True)
    (pa_dir / "data" / "global-claude-md" / "local.md").write_text(
        "# Local detail\n\nMARKER-LOCAL\n", encoding="utf-8"
    )
    home = tmp_path / "home"
    home.mkdir()
    return {
        "pa_dir": pa_dir,
        "home": home,
        "script": pa_dir / "scripts" / "compose-global-claude-md.sh",
    }


def _run_compose(
    sandbox: dict[str, Path], *args: str
) -> subprocess.CompletedProcess[str]:
    """Run the sandboxed composer with a pinned HOME."""
    return run_script(sandbox["script"], *args, home=sandbox["home"])


class TestComposerLayerOrder:
    """ET9 — swapping common and overlay left the suite green."""

    def test_the_three_layers_appear_in_order(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """common, then the Claude overlay, then the private local file."""
        result = _run_compose(compose_sandbox)

        assert result.returncode == 0, result.stderr
        composed = (
            compose_sandbox["home"] / ".claude" / "CLAUDE.md"
        ).read_text(encoding="utf-8")
        positions = [
            composed.index(marker)
            for marker in ("MARKER-COMMON", "MARKER-OVERLAY", "MARKER-LOCAL")
        ]
        assert positions == sorted(positions), positions


class TestComposerDryRun:
    """ET8 and E13 — --dry-run writes nothing, and only that spelling."""

    def test_dry_run_writes_nothing(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """The pinned HOME is unchanged by a dry run."""
        before = snapshot(compose_sandbox["home"])

        result = _run_compose(compose_sandbox, "--dry-run")

        assert result.returncode == 0, result.stderr
        assert snapshot(compose_sandbox["home"]) == before
        assert not (
            compose_sandbox["home"] / ".claude" / "CLAUDE.md"
        ).exists()
        assert "Would write to" in result.stdout

    def test_a_dry_run_over_an_existing_file_leaves_it_alone(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """A previous composition survives a later dry run byte for byte."""
        assert _run_compose(compose_sandbox).returncode == 0
        target = compose_sandbox["home"] / ".claude" / "CLAUDE.md"
        previous = target.read_text(encoding="utf-8")
        (compose_sandbox["pa_dir"] / "global-agent-guidance"
         / "common.md").write_text(
            "# Shared guidance\n\nMARKER-CHANGED\n", encoding="utf-8"
        )

        assert _run_compose(compose_sandbox, "--dry-run").returncode == 0

        assert target.read_text(encoding="utf-8") == previous

    def test_a_misspelt_flag_is_a_usage_error(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """"--dryrun" used to overwrite the target with no error at all."""
        result = _run_compose(compose_sandbox, "--dryrun")

        assert result.returncode == 2
        assert "unknown argument" in result.stderr
        assert not (
            compose_sandbox["home"] / ".claude" / "CLAUDE.md"
        ).exists()


class TestComposerWritesNowhereElse:
    """ET10 — nothing stopped the script writing a Sol-owned surface."""

    def test_only_the_target_is_created_under_home(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """A full run creates ~/.claude and ~/.claude/CLAUDE.md, nothing more."""
        before = snapshot(compose_sandbox["home"])

        result = _run_compose(compose_sandbox)

        assert result.returncode == 0, result.stderr
        created = snapshot(compose_sandbox["home"]) - before
        assert created == {".claude", ".claude/CLAUDE.md"}, created

    def test_no_codex_or_agents_file_is_touched(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """The Sol-owned surfaces named in the header stay absent."""
        _run_compose(compose_sandbox)

        home = compose_sandbox["home"]
        assert not (home / ".codex").exists()
        assert not (home / "AGENTS.md").exists()
        assert not (compose_sandbox["pa_dir"] / "AGENTS.md").exists()


class TestComposerRefusesFromAWorktree:
    """E11 — a worktree run must not overwrite the live instructions."""

    def test_it_refuses_when_a_live_checkout_exists_elsewhere(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """With $HOME/personal-assistant present, another root is refused."""
        live = compose_sandbox["home"] / "personal-assistant"
        live.mkdir()
        target = compose_sandbox["home"] / ".claude" / "CLAUDE.md"
        target.parent.mkdir(parents=True)
        target.write_text("the live instructions\n", encoding="utf-8")

        result = _run_compose(compose_sandbox)

        assert result.returncode == 2, result.stdout
        assert "refusing to write" in result.stderr
        assert target.read_text(encoding="utf-8") == "the live instructions\n"

    def test_an_explicit_target_is_allowed(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """--target names somewhere else, so the guard steps aside."""
        (compose_sandbox["home"] / "personal-assistant").mkdir()
        elsewhere = compose_sandbox["home"] / "preview" / "CLAUDE.md"

        result = _run_compose(compose_sandbox, "--target", str(elsewhere))

        assert result.returncode == 0, result.stderr
        assert "MARKER-LOCAL" in elsewhere.read_text(encoding="utf-8")
        assert not (
            compose_sandbox["home"] / ".claude" / "CLAUDE.md"
        ).exists()

    def test_target_without_a_path_is_a_usage_error(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """A bare --target must not silently compose to the default."""
        result = _run_compose(compose_sandbox, "--target")

        assert result.returncode == 2
        assert "--target needs a path" in result.stderr


# ---------------------------------------------------------------------------
# env-fingerprint.sh
#
# The tool exists to compare two .env files WITHOUT disclosing a value, and
# had no tests at all: a value-leaking edit stayed green (lens B, ET14).
# Every .env below is synthetic, written into a pytest tmp dir, with
# obviously fake values. The real ~/personal-assistant/.env is never read.
# ---------------------------------------------------------------------------

#: A distinctive fake value: if any part of it appears in the output, the
#: no-disclosure invariant is broken and grep will say so.
CANARY = "canary-VALUE-8f3a-must-not-appear"

ENV_FINGERPRINT = SCRIPTS / "env-fingerprint.sh"


@pytest.fixture
def synthetic_env(tmp_path: Path) -> Path:
    """Write a synthetic .env carrying the canary and a duplicate key."""
    env_file = tmp_path / "synthetic.env"
    env_file.write_text(
        "# a synthetic env file — none of these are real\n"
        f"SYNTHETIC_TOKEN={CANARY}\n"
        'SYNTHETIC_QUOTED="quoted-value-1234"\n'
        "export SYNTHETIC_EXPORTED=exported-value-5678\n"
        "SYNTHETIC_EMPTY=\n"
        "SYNTHETIC_TOKEN=second-assignment-wins\n",
        encoding="utf-8",
    )
    return env_file


def _run_fingerprint(
    env_file: Path, home: Path, salt: str | None = "synthetic-salt"
) -> subprocess.CompletedProcess[str]:
    """Run the fingerprinter over ``env_file`` with a pinned HOME."""
    extra = {"ENV_FINGERPRINT_SALT": salt} if salt is not None else None
    env = dict(os.environ)
    env.pop("ENV_FINGERPRINT_SALT", None)
    env["HOME"] = str(home)
    if extra:
        env.update(extra)
    return subprocess.run(
        ["bash", str(ENV_FINGERPRINT), str(env_file)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(home),
        timeout=60,
    )


class TestEnvFingerprintDisclosesNothing:
    """ET14 — the whole point of the tool, finally pinned."""

    def test_no_value_appears_in_the_output(
        self, synthetic_env: Path, tmp_path: Path
    ) -> None:
        """Not one character sequence from any value is printed."""
        home = tmp_path / "home"
        home.mkdir()

        result = _run_fingerprint(synthetic_env, home)

        assert result.returncode == 0, result.stderr
        combined = result.stdout + result.stderr
        for value in (
            CANARY,
            "quoted-value-1234",
            "exported-value-5678",
            "second-assignment-wins",
        ):
            assert value not in combined, f"{value!r} was disclosed"

    def test_the_salt_is_never_printed(
        self, synthetic_env: Path, tmp_path: Path
    ) -> None:
        """The shared secret must not leak through the output either."""
        home = tmp_path / "home"
        home.mkdir()

        result = _run_fingerprint(
            synthetic_env, home, salt="salt-canary-9d2f"
        )

        assert "salt-canary-9d2f" not in result.stdout + result.stderr

    def test_only_a_bucket_is_reported_not_a_length(
        self, synthetic_env: Path, tmp_path: Path
    ) -> None:
        """E23 — an exact length narrows a brute-force sweep; a bucket does not."""
        home = tmp_path / "home"
        home.mkdir()

        result = _run_fingerprint(synthetic_env, home)

        rows = [
            line
            for line in result.stdout.splitlines()
            if line.startswith("SYNTHETIC_")
        ]
        assert rows, result.stdout
        buckets = []
        for row in rows:
            bucket = row.split("\t")[2].split()[0]
            assert bucket in ("empty", "short", "medium", "long"), row
            buckets.append(bucket)
        # The third column is never a number, so no exact length is on offer.
        assert not any(b.isdigit() for b in buckets), buckets
        assert "empty" in buckets, "the empty-value marker was lost"


class TestEnvFingerprintRequiresASalt:
    """E23 — a public default salt made the output a value oracle."""

    def test_it_refuses_without_a_salt(
        self, synthetic_env: Path, tmp_path: Path
    ) -> None:
        """No salt is a refusal, not a fall-back to a published constant."""
        home = tmp_path / "home"
        home.mkdir()

        result = _run_fingerprint(synthetic_env, home, salt=None)

        assert result.returncode == 2
        assert "ENV_FINGERPRINT_SALT" in result.stderr
        assert not result.stdout.strip().endswith("### ---")

    def test_no_salt_constant_is_committed(self) -> None:
        """The script must carry no default salt for anyone to read."""
        source = ENV_FINGERPRINT.read_text(encoding="utf-8")
        assert "efn-envcmp" not in source
        assert 'ENV_FINGERPRINT_SALT:-efn' not in source

    def test_the_same_salt_gives_the_same_digest(
        self, tmp_path: Path
    ) -> None:
        """Cross-host comparison still works: equal values, equal hashes."""
        home = tmp_path / "home"
        home.mkdir()
        one = tmp_path / "host-a.env"
        one.write_text(f"SYNTHETIC_TOKEN={CANARY}\n", encoding="utf-8")
        two = tmp_path / "host-b.env"
        two.write_text(
            f'SYNTHETIC_TOKEN="{CANARY}"\n', encoding="utf-8"
        )

        first = _run_fingerprint(one, home, salt="shared-salt")
        second = _run_fingerprint(two, home, salt="shared-salt")

        def digest(result: subprocess.CompletedProcess[str]) -> str:
            """Pull the digest column from the SYNTHETIC_TOKEN row."""
            row = next(
                line for line in result.stdout.splitlines()
                if line.startswith("SYNTHETIC_TOKEN\t")
            )
            return row.split("\t")[1]

        assert digest(first) == digest(second)
        assert len(digest(first)) == 12

    def test_a_different_salt_gives_a_different_digest(
        self, tmp_path: Path
    ) -> None:
        """The salt actually participates in the hash."""
        home = tmp_path / "home"
        home.mkdir()
        env_file = tmp_path / "one.env"
        env_file.write_text("SYNTHETIC_ONE=same-value\n", encoding="utf-8")

        a = _run_fingerprint(env_file, home, salt="salt-a")
        b = _run_fingerprint(env_file, home, salt="salt-b")

        assert a.stdout != b.stdout


class TestEnvFingerprintParsing:
    """Quotes, `export`, and the duplicate-key warning."""

    def test_quotes_and_export_are_normalised(self, tmp_path: Path) -> None:
        """The three spellings of one value fingerprint identically."""
        home = tmp_path / "home"
        home.mkdir()
        env_file = tmp_path / "shapes.env"
        env_file.write_text(
            "PLAIN=shared-value\n"
            'QUOTED="shared-value"\n'
            "EXPORTED_ONE=shared-value\n"
            "export EXPORTED_TWO=shared-value\n",
            encoding="utf-8",
        )

        result = _run_fingerprint(env_file, home)

        assert result.returncode == 0, result.stderr
        digests = {
            line.split("\t")[0]: line.split("\t")[1]
            for line in result.stdout.splitlines()
            if "\t" in line and not line.startswith("###")
        }
        assert set(digests) == {
            "PLAIN", "QUOTED", "EXPORTED_ONE", "EXPORTED_TWO"
        }, digests
        assert len(set(digests.values())) == 1, digests

    def test_the_duplicate_key_warning_fires(
        self, synthetic_env: Path, tmp_path: Path
    ) -> None:
        """A duplicated key is a silent override at load time."""
        home = tmp_path / "home"
        home.mkdir()

        result = _run_fingerprint(synthetic_env, home)

        assert "DUPLICATE KEYS" in result.stdout
        assert "SYNTHETIC_TOKEN" in result.stdout

    def test_a_missing_file_is_reported_not_crashed(
        self, tmp_path: Path
    ) -> None:
        """An absent .env is a clear message, exit 0."""
        home = tmp_path / "home"
        home.mkdir()

        result = _run_fingerprint(tmp_path / "absent.env", home)

        assert result.returncode == 0
        assert "MISSING" in result.stdout


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    raise SystemExit(pytest.main([__file__, "-v"]))
