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

import datetime
import importlib.util
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
COMPOSE_SCRIPT = SCRIPTS / "compose-global-claude-md.sh"




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


def write_git_stub(bin_dir: Path, log: Path) -> None:
    """
    Write a ``git`` stub that records argv and stands in for two commands.

    ``sync-symlinks.sh`` decides whether to initialise the data submodule
    from what git reports, so the stub answers ``submodule status`` from
    ``STUB_SUBMODULE_STATUS`` -- each test states the repository shape it
    is describing.

    Round 4d-5 (M-b): it must also POPULATE the submodule on
    ``submodule update``, as real git does. Without that, no test could
    reach the fresh-clone happy path: the init "succeeded", data/ stayed
    empty, and the run then exited 1 at the step-7 pre-check for a file
    the init should have produced. Several tests were quietly inspecting
    failing runs.

    Args:
        bin_dir: Directory placed first on ``PATH``.
        log: File each invocation appends one ``git arg arg`` line to.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "git"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "git" >> {shlex.quote(str(log))}\n'
        f'for a in "$@"; do printf " %s" "$a" >> {shlex.quote(str(log))}; done\n'
        f'printf "\\n" >> {shlex.quote(str(log))}\n'
        'if [[ "${1:-}" == "submodule" && "${2:-}" == "status" ]]; then\n'
        "    # Honour the pathspec, as real git does (round 4d-6, L2):\n"
        "    # without it every declared submodule is listed, and the\n"
        "    # caller reads only the FIRST line's prefix.\n"
        '    want=""\n'
        '    for ((i = 1; i <= $#; i++)); do\n'
        '        if [[ "${!i}" == "--" ]]; then\n'
        "            j=$((i + 1))\n"
        '            want="${!j:-}"\n'
        "        fi\n"
        "    done\n"
        '    while IFS= read -r line; do\n'
        '        [[ -z "$line" ]] && continue\n'
        "        read -r -a fields <<< \"$line\"\n"
        '        if [[ -z "$want" || "${fields[1]:-}" == "$want" ]]; then\n'
        '            printf "%s\\n" "$line"\n'
        "        fi\n"
        '    done <<< "${STUB_SUBMODULE_STATUS:-}"\n'
        'elif [[ "${1:-}" == "submodule" && "${2:-}" == "update" ]]; then\n'
        "    # Real git clones the submodule here, leaving a checkout with\n"
        "    # a .git file in it. Reproduce enough of that for the steps\n"
        "    # downstream to behave as they would on a real machine.\n"
        '    if [[ -n "${STUB_SUBMODULE_POPULATES:-}" ]]; then\n'
        '        mkdir -p "$STUB_SUBMODULE_POPULATES/global-claude-md"\n'
        '        printf "# Local\\n\\nMARKER-LOCAL\\n" \\\n'
        '            > "$STUB_SUBMODULE_POPULATES/global-claude-md/local.md"\n'
        '        printf "gitdir: ../.git/modules/data\\n" \\\n'
        '            > "$STUB_SUBMODULE_POPULATES/.git"\n'
        "    fi\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)


def write_compose_recorder(pa_dir: Path, log: Path) -> None:
    """
    Put a recording wrapper in front of the real composer.

    ``sync-symlinks.sh`` sends the composer's stdout to /dev/null, so
    "was step 7 consulted at all?" is otherwise unobservable -- and
    replacing the whole dry-run passthrough with ``:`` survived the suite
    (round 4d-5, survivor iii). The wrapper logs its argv and then execs
    the real script, so behaviour is unchanged and the call is visible.

    Args:
        pa_dir: The synthetic PA_DIR whose scripts/ holds the composer.
        log: The shared argv log.
    """
    wrapper = pa_dir / "scripts" / "compose-global-claude-md.sh"
    if wrapper.exists() or wrapper.is_symlink():
        wrapper.unlink()
    # The real script is reached through a symlink INSIDE the sandbox's
    # scripts/ directory, so its own SCRIPT_DIR/PA_DIR still resolve to
    # the sandbox. Exec'ing it at its real path would point the composer
    # at this repository instead.
    real = pa_dir / "scripts" / ".compose-real.sh"
    if real.exists() or real.is_symlink():
        real.unlink()
    real.symlink_to(COMPOSE_SCRIPT)
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "compose" >> {shlex.quote(str(log))}\n'
        f'for a in "$@"; do printf " %s" "$a" >> {shlex.quote(str(log))}; done\n'
        f'printf "\\n" >> {shlex.quote(str(log))}\n'
        f"exec bash {shlex.quote(str(real))} \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)


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
    write_git_stub(bin_dir, log)
    write_compose_recorder(pa_dir, log)
    # An ORDINARY CLONE: .git is a DIRECTORY. Round 4d-4 (M3): the sandbox
    # used to have no .git at all, so `[ -f "$PA_DIR/.git" ]` was false for
    # the wrong reason in every clone test and relaxing it to `[ -e ... ]`
    # went unnoticed — on a real machine that mutation makes every clone
    # read as a worktree and never initialise its submodule. The
    # worktree tests overwrite this with a FILE, as git does.
    (pa_dir / ".git").mkdir()
    (pa_dir / ".git" / "HEAD").write_text(
        "ref: refs/heads/main\n", encoding="utf-8"
    )
    return {
        "pa_dir": pa_dir,
        "home": home,
        "bin": bin_dir,
        "log": log,
        "script": pa_dir / "scripts" / "sync-symlinks.sh",
    }


def assert_composed(claude_md: Path, local_marker: str) -> None:
    """
    Assert the composed CLAUDE.md carries all three layers, in order.

    Round 4d-6 (L7): the M-b tests asserted only that the file EXISTS. A
    composer that wrote an empty file, or dropped the private local layer,
    would have satisfied them -- and the local layer is the whole reason
    step 7 needs data/ at all.

    Args:
        claude_md: The composed file.
        local_marker: Which local-layer marker to expect -- the sandbox's
            own ``LOCAL-SECTION``, or ``MARKER-LOCAL`` where the stub git
            populated the submodule.
    """
    assert claude_md.is_file(), f"{claude_md} was not composed"
    composed = claude_md.read_text(encoding="utf-8")
    markers = ("COMMON-SECTION", "OVERLAY-SECTION", local_marker)
    for marker in markers:
        assert marker in composed, f"{marker} missing from {claude_md}"
    positions = [composed.index(marker) for marker in markers]
    assert positions == sorted(positions), (markers, positions)


#: The sentence the destructive remedy is made of, without the "Remedy: "
#: prefix. Round 4d-7 (M1): asserting the PREFIXED form let the step-1
#: site, which emitted the same sentence inline, print it unnoticed.
DESTRUCTIVE_ADVICE = "entirely (git will not clone into a"


def assert_no_destructive_advice(
    result: subprocess.CompletedProcess[str],
) -> None:
    """Fail if "remove <PA_DIR>/data entirely" appears on either stream."""
    combined = result.stdout + result.stderr
    assert DESTRUCTIVE_ADVICE not in combined, combined
    assert "entirely" not in combined, combined


def _make_worktree(pa_dir: Path) -> None:
    """Turn an ordinary-clone sandbox into a LINKED WORKTREE.

    git marks a linked worktree by replacing the ``.git`` directory with a
    FILE holding a ``gitdir:`` pointer at the main checkout's admin area.
    The distinction is exactly what ``sync-symlinks.sh`` reads, so the
    fixtures have to reproduce both shapes rather than neither.
    """
    git_path = pa_dir / ".git"
    if git_path.is_dir():
        shutil.rmtree(git_path)
    git_path.write_text(
        "gitdir: /elsewhere/.git/worktrees/synthetic\n", encoding="utf-8"
    )


def _run_sync(
    sandbox: dict[str, Path],
    *args: str,
    submodule_status: str = " 1234abcd data (heads/main)",
) -> subprocess.CompletedProcess[str]:
    """Run the sandboxed ``sync-symlinks.sh`` with stubs on PATH.

    ``submodule_status`` is what the stub ``git`` reports for
    ``submodule status -- data``; the default describes an initialised
    submodule, which is the ordinary case.
    """
    return run_script(
        sandbox["script"],
        *args,
        home=sandbox["home"],
        path_prefix=sandbox["bin"],
        cwd=sandbox["pa_dir"],
        extra_env={
            "STUB_SUBMODULE_STATUS": submodule_status,
            # Where the stub git materialises a submodule checkout when
            # `submodule update` runs, as real git would.
            "STUB_SUBMODULE_POPULATES": str(sandbox["pa_dir"] / "data"),
        },
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
    session made there. This step exists only to populate an
    UNINITIALISED ``data/``.

    Round 4d-2 replaced the original "is data/ non-empty?" test: a fresh
    clone whose ``data/`` held one stray file answered yes and the
    submodule was then never initialised — the opposite failure. The gate
    now asks git, whose ``submodule status`` prefixes an uninitialised
    submodule with ``-``.
    """

    def test_initialised_submodule_is_left_alone(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A checked-out submodule means no `submodule update` at all."""
        result = _run_sync(
            sync_sandbox, "--quiet", submodule_status=" 1234abcd data (main)"
        )

        assert result.returncode == 0, result.stderr
        recorded = sync_sandbox["log"].read_text(encoding="utf-8")
        assert "submodule update" not in recorded, recorded

    def test_a_locally_modified_submodule_is_left_alone(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """"+" means checked out at a different commit — still hands off."""
        result = _run_sync(
            sync_sandbox, "--quiet", submodule_status="+1234abcd data (main)"
        )

        assert result.returncode == 0, result.stderr
        assert "submodule update" not in sync_sandbox["log"].read_text(
            encoding="utf-8"
        )

    def test_uninitialised_submodule_is_initialised(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """"-" plus an EMPTY data/ is the case the step exists for."""
        data = sync_sandbox["pa_dir"] / "data"
        for child in sorted(data.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()

        result = _run_sync(
            sync_sandbox, "--quiet", submodule_status="-1234abcd data"
        )

        recorded = sync_sandbox["log"].read_text(encoding="utf-8")
        assert "git submodule update --init --recursive --quiet" in recorded
        # Round 4d-5 (M-b): the stub now populates data/ as real git does,
        # so the fresh-clone path can actually be asserted to SUCCEED. It
        # used to exit 1 at the step-7 pre-check for the very file the
        # init should have produced, and nothing noticed.
        assert result.returncode == 0, result.stdout + result.stderr
        # The local layer here comes from the stub git's submodule
        # checkout, so its marker is the stub's.
        assert_composed(
            sync_sandbox["home"] / ".claude" / "CLAUDE.md", "MARKER-LOCAL"
        )

    def test_quiet_suppresses_the_submodule_ready_line(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """L3 — `did_verbose` differs from `did` only under --quiet.

        Nothing asserted the suppression, so the helper could collapse to
        `did` and cron logs would gain a line per run that says nothing
        happened.
        """
        data = sync_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()

        quiet = _run_sync(
            sync_sandbox, "--quiet", submodule_status="-1234abcd data"
        )

        assert quiet.returncode == 0, quiet.stdout + quiet.stderr
        assert_composed(
            sync_sandbox["home"] / ".claude" / "CLAUDE.md", "MARKER-LOCAL"
        )
        assert "Submodule ready." not in quiet.stdout, quiet.stdout

    def test_without_quiet_the_submodule_ready_line_is_printed(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """The negative half: the line exists, it is merely suppressible."""
        data = sync_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()

        loud = _run_sync(sync_sandbox, submodule_status="-1234abcd data")

        assert loud.returncode == 0, loud.stdout + loud.stderr
        assert_composed(
            sync_sandbox["home"] / ".claude" / "CLAUDE.md", "MARKER-LOCAL"
        )
        assert "Submodule ready." in loud.stdout, loud.stdout

    def test_a_non_empty_data_reports_rather_than_attempting_the_init(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """Round 4d-3 reverses round 4d-2's rule here, and says why.

        Round 4d-2 asserted that a stray file in ``data/`` must not
        suppress the init. Verified against a throwaway superproject, git
        refuses to clone into a non-empty directory — "destination path
        already exists and is not an empty directory" — so that init
        could only ever fail, and under ``set -e`` it aborted the whole
        run at step 1. Saying plainly what a human has to clear is the
        useful behaviour.
        """
        (sync_sandbox["pa_dir"] / "data" / "README-left-behind.md").write_text(
            "a stray file in an uninitialised submodule\n", encoding="utf-8"
        )

        result = _run_sync(
            sync_sandbox, "--quiet", submodule_status="-1234abcd data"
        )

        assert result.returncode == 0, result.stderr
        assert "uninitialised but not empty" in result.stdout
        assert "submodule update" not in sync_sandbox["log"].read_text(
            encoding="utf-8"
        )

    def test_a_linked_worktree_never_initialises_data(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """M1/M2 — a worktree's data/ belongs to the main checkout.

        A linked worktree carries a ``.git`` FILE rather than a directory,
        holds stub directories under ``data/``, and reports the submodule
        uninitialised. Round 4d-2 sent exactly that state into an init
        that git refuses.
        """
        _make_worktree(sync_sandbox["pa_dir"])

        result = _run_sync(
            sync_sandbox, "--quiet", submodule_status="-1234abcd data"
        )

        assert result.returncode == 0, result.stderr
        assert "belongs to the main checkout" in result.stdout
        assert "submodule update" not in sync_sandbox["log"].read_text(
            encoding="utf-8"
        )

    def test_a_plain_clone_with_allow_worktree_still_initialises(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """M1 — the FLAG is not evidence about the checkout.

        `--allow-worktree` says "I know what I am doing", not "this is a
        worktree". Treating it as the fact made a plain clone announce
        itself a worktree, skip an init it genuinely needed, relink all of
        ~/.claude at that clone, and die at step 7 on the missing local
        source — the half-migrated state the guard exists to prevent,
        reached by a new route.
        """
        (sync_sandbox["home"] / "personal-assistant").mkdir()
        data = sync_sandbox["pa_dir"] / "data"
        for child in sorted(data.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()

        result = _run_sync(
            sync_sandbox,
            "--allow-worktree",
            submodule_status="-1234abcd data",
        )

        recorded = sync_sandbox["log"].read_text(encoding="utf-8")
        assert "git submodule update --init --recursive --quiet" in recorded
        assert "belongs to the main checkout" not in result.stdout, (
            "a plain clone was reported as a worktree"
        )
        # The whole run has to succeed, not merely reach the init (M-b).
        assert result.returncode == 0, result.stdout + result.stderr
        assert "[8/8]" in result.stdout, result.stdout
        assert_composed(
            sync_sandbox["home"] / ".claude" / "CLAUDE.md", "MARKER-LOCAL"
        )

    def test_the_worktree_skip_reads_the_checkout_not_the_flag(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A real worktree skips WITHOUT the flag; the flag alone does not."""
        _make_worktree(sync_sandbox["pa_dir"])

        result = _run_sync(
            sync_sandbox, "--quiet", submodule_status="-1234abcd data"
        )

        assert "belongs to the main checkout" in result.stdout
        assert "submodule update" not in sync_sandbox["log"].read_text(
            encoding="utf-8"
        )

    def test_the_pathspec_selects_data_among_several_submodules(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """L2 — dropping `-- data` survived, because there is only one.

        Only the FIRST line's prefix is read, so the moment a second
        submodule is declared the gate starts answering about whichever
        one git lists first. Here an uninitialised `vendor` is listed
        ahead of an initialised `data`: without the pathspec the script
        would see "-" and try to initialise a submodule that is already
        checked out -- the exact thing E10 exists to prevent.
        """
        result = _run_sync(
            sync_sandbox,
            submodule_status=(
                "-aaaaaaaa vendor\n 1234abcd data (heads/main)"
            ),
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "Submodule already initialised" in result.stdout, result.stdout
        assert "uninitialised but not empty" not in result.stdout, (
            "vendor's state was read as data's"
        )
        assert "submodule update" not in sync_sandbox["log"].read_text(
            encoding="utf-8"
        ), "an initialised data/ was re-initialised"

    def test_the_pathspec_ignores_another_submodules_state(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """The other direction: data uninitialised behind an initialised one."""
        data = sync_sandbox["pa_dir"] / "data"
        for child in sorted(data.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()

        result = _run_sync(
            sync_sandbox,
            "--quiet",
            submodule_status=(
                " bbbbbbbb vendor (heads/main)\n-1234abcd data"
            ),
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "git submodule update --init" in sync_sandbox["log"].read_text(
            encoding="utf-8"
        ), "an uninitialised data/ was left alone"

    def test_a_submodule_checkout_is_not_a_worktree(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """L-b — a submodule checkout also has a .git FILE, and is not one.

        git writes ".git/worktrees/<name>" into a linked worktree's
        pointer and ".git/modules/<name>" into a submodule's. Only the
        first is a worktree, and only a worktree's data/ belongs to
        someone else.
        """
        git_path = sync_sandbox["pa_dir"] / ".git"
        shutil.rmtree(git_path)
        git_path.write_text(
            "gitdir: ../.git/modules/personal-assistant\n", encoding="utf-8"
        )
        data = sync_sandbox["pa_dir"] / "data"
        for child in sorted(data.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()

        result = _run_sync(
            sync_sandbox, "--quiet", submodule_status="-1234abcd data"
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "belongs to the main checkout" not in result.stdout, (
            "a submodule checkout was mistaken for a worktree"
        )
        assert "git submodule update --init" in sync_sandbox["log"].read_text(
            encoding="utf-8"
        )

    def test_the_worktree_pointer_shape_is_what_is_matched(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A .git file that is neither shape is not treated as a worktree."""
        git_path = sync_sandbox["pa_dir"] / ".git"
        shutil.rmtree(git_path)
        git_path.write_text("something else entirely\n", encoding="utf-8")
        data = sync_sandbox["pa_dir"] / "data"
        for child in sorted(data.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()

        result = _run_sync(
            sync_sandbox, "--quiet", submodule_status="-1234abcd data"
        )

        assert "belongs to the main checkout" not in result.stdout
        assert "git submodule update --init" in sync_sandbox["log"].read_text(
            encoding="utf-8"
        )

    def test_allow_worktree_completes_all_eight_steps(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """The escape hatch has to actually work, stub dirs and all.

        Reproduces M1: a worktree of this repository, ``data/`` holding
        empty stub directories, ``git submodule status`` reporting "-",
        and ``--allow-worktree`` given. Before this round the run exited 1
        at step 1 and ~/.claude was never created.
        """
        (sync_sandbox["home"] / "personal-assistant").mkdir()
        _make_worktree(sync_sandbox["pa_dir"])
        for stub in ("memories", "tasks", "logs"):
            (sync_sandbox["pa_dir"] / "data" / stub).mkdir()

        result = _run_sync(
            sync_sandbox,
            "--allow-worktree",
            submodule_status="-1234abcd data",
        )

        assert result.returncode == 0, result.stderr
        assert "[8/8]" in result.stdout, result.stdout
        claude = sync_sandbox["home"] / ".claude"
        assert (claude / "settings.json").is_symlink()
        assert (claude / "commands" / "fossick.md").is_symlink()
        assert (claude / "skills" / "tally-sherds").is_symlink()
        assert (claude / "agents" / "trench-scribe.md").is_symlink()
        assert (claude / "output-styles" / "terse.md").is_symlink()
        # No init ran here, so the local layer is the sandbox's own.
        assert_composed(claude / "CLAUDE.md", "LOCAL-SECTION")
        assert "submodule update" not in sync_sandbox["log"].read_text(
            encoding="utf-8"
        )

    def test_the_submodule_line_is_future_tense_under_dry_run(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """"Submodule ready." read as done work in a preview."""
        data = sync_sandbox["pa_dir"] / "data"
        for child in sorted(data.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()

        result = _run_sync(
            sync_sandbox, "--dry-run", submodule_status="-1234abcd data"
        )

        # Step 7 legitimately fails here: with data/ genuinely empty the
        # composer has no local source, which is the correct outcome for
        # an uninitialised submodule. Step 1's narration is what is under
        # test, and it has already been emitted.
        assert "would have the submodule ready" in result.stdout
        assert "Submodule ready." not in result.stdout

    def test_no_submodule_declared_is_a_no_op(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A repository without the submodule must not be "initialised"."""
        result = _run_sync(sync_sandbox, "--quiet", submodule_status="")

        assert result.returncode == 0, result.stderr
        assert "submodule update" not in sync_sandbox["log"].read_text(
            encoding="utf-8"
        )

class TestUnusableDataStopsBeforeAnythingIsRelinked:
    """M2 — a failure at step 7 arrives after ~/.claude has been rewired.

    Step 7 composes from three sources, one of them inside ``data/``. When
    that source is absent the composer cannot succeed, and finding out at
    step 7 leaves every ~/.claude symlink already repointed and step 1's
    warning long scrolled off a cron log.
    """

    @staticmethod
    def _strip_local(pa_dir: Path) -> None:
        """Remove the composer's data/-borne source, leaving data/ non-empty."""
        (pa_dir / "data" / "global-claude-md" / "local.md").unlink()
        (pa_dir / "data" / "global-claude-md").rmdir()
        (pa_dir / "data" / "stray-file.md").write_text("x\n", encoding="utf-8")

    def test_a_clone_stops_at_step_one_with_nothing_relinked(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """Not one symlink is created, and the exit status says so."""
        self._strip_local(sync_sandbox["pa_dir"])
        before = snapshot(sync_sandbox["home"])

        result = _run_sync(
            sync_sandbox, submodule_status="-1234abcd data"
        )

        assert result.returncode == 1, result.stdout
        assert "[2/8]" not in result.stdout, result.stdout
        assert snapshot(sync_sandbox["home"]) == before

    def test_the_remedy_is_the_one_that_works(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """`git submodule update --init` cannot clone into a non-empty
        directory, so it must not be offered as the fix for one."""
        self._strip_local(sync_sandbox["pa_dir"])

        result = _run_sync(
            sync_sandbox, submodule_status="-1234abcd data"
        )

        assert "remove" in result.stdout.lower()
        assert "data" in result.stdout
        remedy_lines = [
            line for line in result.stdout.splitlines()
            if "Remedy:" in line or "WARNING: data/" in line
        ]
        assert remedy_lines, result.stdout

    def test_the_non_empty_warning_does_not_offer_the_impossible_command(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """`git submodule update --init` must not be offered as the fix
        for a non-empty data/, in the output or in the source.

        Checked on the OUTPUT of the failing run, because a line-by-line
        source scan misses an advisory that sits on the line after the
        diagnosis — which is exactly where it sat.
        """
        self._strip_local(sync_sandbox["pa_dir"])

        result = _run_sync(
            sync_sandbox, submodule_status="-1234abcd data"
        )

        assert "not empty" in result.stdout or "Remedy:" in result.stdout
        assert "submodule update --init" not in result.stdout, result.stdout

    def test_the_warning_branch_uses_the_shared_remedy(self) -> None:
        """One remedy string, so step 1 and the summary cannot diverge."""
        source = (SCRIPTS / "sync-symlinks.sh").read_text(encoding="utf-8")
        assert "DATA_REMEDY=" in source
        # Round 4d-7 (M1): the advice is EMITTED from exactly one place.
        # It used to be interpolated inline at step 1 as well, so the
        # guard added in round 4d-6 covered the step-7 site only and the
        # two could disagree inside a single run.
        emit_sites = [
            line for line in source.splitlines()
            if "$DATA_REMEDY" in line and line.lstrip().startswith("say ")
        ]
        assert len(emit_sites) == 1, emit_sites
        assert "say_data_remedy" in source
        # Only executable lines: the comment above that branch quotes the
        # withdrawn advice on purpose, so the reason stays on record.
        code = [
            line for line in source.splitlines()
            if not line.lstrip().startswith("#")
        ]
        assert not [
            line for line in code if "submodule update --init' by hand" in line
        ], "an advisory survives that git cannot honour"

    def test_a_worktree_skips_step_seven_and_completes(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A worktree's data/ is the main checkout's; steps 2-6 still run."""
        _make_worktree(sync_sandbox["pa_dir"])
        self._strip_local(sync_sandbox["pa_dir"])

        result = _run_sync(
            sync_sandbox,
            "--allow-worktree",
            submodule_status="-1234abcd data",
        )

        assert result.returncode == 0, result.stdout
        assert "will be SKIPPED" in result.stdout
        assert "SKIPPED:" in result.stdout
        claude = sync_sandbox["home"] / ".claude"
        assert (claude / "commands" / "fossick.md").is_symlink()
        assert not (claude / "CLAUDE.md").exists(), (
            "step 7 wrote despite having no source"
        )

    def test_a_dry_run_is_exempt_from_the_stop(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """Previewing an incomplete checkout changes nothing, so it is allowed."""
        self._strip_local(sync_sandbox["pa_dir"])
        before = snapshot(sync_sandbox["home"])

        result = _run_sync(
            sync_sandbox, "--dry-run", submodule_status="-1234abcd data"
        )

        assert "[2/8]" in result.stdout, result.stdout
        assert snapshot(sync_sandbox["home"]) == before


class TestComposerNamesTheRightRemedy:
    """M2 — the composer's own error had the same impossible advice."""

    def test_a_non_empty_data_says_remove_not_init(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """The state git cannot clone into gets the remedy that works."""
        local = compose_sandbox["pa_dir"] / "data" / "global-claude-md"
        (local / "local.md").unlink()
        local.rmdir()
        (compose_sandbox["pa_dir"] / "data" / "stray.md").write_text(
            "x\n", encoding="utf-8"
        )

        result = _run_compose(compose_sandbox)

        assert result.returncode == 1
        assert "Remove" in result.stderr
        assert "not empty" in result.stderr

    def test_an_absent_data_still_says_init(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """When data/ is genuinely absent, an init IS the remedy."""
        local = compose_sandbox["pa_dir"] / "data" / "global-claude-md"
        (local / "local.md").unlink()
        local.rmdir()
        (compose_sandbox["pa_dir"] / "data").rmdir()

        result = _run_compose(compose_sandbox)

        assert result.returncode == 1
        assert "submodule update --init" in result.stderr


class TestDryRunNeverFailsWhereARealRunSucceeds:
    """M-a — a preview exiting 1 where the real run exits 0.

    The --dry-run exemption sat on the whole pre-check, so a preview never
    set SKIP_COMPOSE, step 7 ran the composer anyway, and the composer
    died on the very file the pre-check had just established was missing.
    """

    def test_a_worktree_dry_run_exits_zero_and_skips_step_seven(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """The real worktree run exits 0; the preview must too."""
        _make_worktree(sync_sandbox["pa_dir"])
        data = sync_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()
        before = snapshot(sync_sandbox["home"])

        result = _run_sync(
            sync_sandbox,
            "--allow-worktree",
            "--dry-run",
            submodule_status="-1234abcd data",
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "SKIPPED:" in result.stdout, result.stdout
        assert "[8/8]" in result.stdout, result.stdout
        assert snapshot(sync_sandbox["home"]) == before

    def test_a_broken_clone_dry_run_narrates_to_the_end(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """L-c, decided here: a preview runs to step 8 and exits 0.

        A preview changes nothing, so it must not fail, and one that stops
        two thirds of the way through is not a preview. It says plainly
        that a real run would refuse, then narrates the rest.
        """
        data = sync_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()
        (data / "stray.md").write_text("x\n", encoding="utf-8")
        before = snapshot(sync_sandbox["home"])

        result = _run_sync(
            sync_sandbox, "--dry-run", submodule_status="-1234abcd data"
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "a REAL run would" in result.stdout
        assert "[8/8]" in result.stdout, result.stdout
        assert snapshot(sync_sandbox["home"]) == before

    def test_a_preview_prints_the_remedy_it_is_previewing(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """L5 — the preview withheld the one line worth acting on.

        A dry run on an initialised-but-incomplete submodule said "a REAL
        run would refuse" and stopped there, while the real run printed
        the full "Do NOT delete" diagnosis. Previewing a refusal without
        its reason is the least useful half of the message.
        """
        data = sync_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()
        (data / ".git").write_text(
            "gitdir: ../.git/modules/data\n", encoding="utf-8"
        )

        preview = _run_sync(
            sync_sandbox,
            "--dry-run",
            submodule_status=" 1234abcd data (heads/main)",
        )

        assert preview.returncode == 0, preview.stdout + preview.stderr
        assert "a REAL run would" in preview.stdout
        assert "Do NOT delete" in preview.stdout, preview.stdout
        assert "remove" not in preview.stdout.lower(), preview.stdout

    def test_the_preview_and_the_real_run_give_the_same_remedy(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """Whatever the state, the two must agree on what to do about it."""
        data = sync_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()
        (data / "stray.md").write_text("x\n", encoding="utf-8")

        preview = _run_sync(
            sync_sandbox, "--dry-run", submodule_status="-1234abcd data"
        )
        real = _run_sync(
            sync_sandbox, submodule_status="-1234abcd data"
        )

        assert preview.returncode == 0
        assert real.returncode == 1
        for output in (preview.stdout, real.stdout):
            assert "Remedy: remove" in output, output
            assert "will not clone into a non-empty directory" in output

    def test_the_worktree_note_is_not_the_broken_clone_note(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """L4 — swapping the two dry-run branches survived the suite.

        Exit 0, SKIPPED and [8/8] hold for both, so nothing noticed which
        NOTE was printed — and a worktree preview claiming "a REAL run
        would refuse at step 1" is simply false: the real worktree run
        exits 0.
        """
        _make_worktree(sync_sandbox["pa_dir"])
        data = sync_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()

        result = _run_sync(
            sync_sandbox,
            "--allow-worktree",
            "--dry-run",
            submodule_status="-1234abcd data",
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "belongs to the main" in result.stdout, result.stdout
        assert "a REAL run would" not in result.stdout, result.stdout

    def test_the_broken_clone_note_is_not_the_worktree_note(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """The other direction of the same swap.

        Round 4d-7 (M2): data/ must be NON-empty here. An empty one is a
        fresh clone whose init step 1 would perform, which is a different
        state with a different note — that confusion was the M2 defect.
        """
        data = sync_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()
        (data / "stray.md").write_text("x\n", encoding="utf-8")

        result = _run_sync(
            sync_sandbox, "--dry-run", submodule_status="-1234abcd data"
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "a REAL run would" in result.stdout, result.stdout
        assert "belongs to the main" not in result.stdout, result.stdout

    def test_a_fresh_clone_preview_offers_no_remedy(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """M2 — the preview contradicted the step it had just narrated.

        Empty data/, status "-": step 1 previews `git submodule update
        --init`, which is what produces local.md, and a real run in this
        state exits 0 and composes. The preview nonetheless said "a REAL
        run would refuse at step 1" and offered to delete data/ — the
        very directory it had just said it would populate.
        """
        data = sync_sandbox["pa_dir"] / "data"
        for child in sorted(data.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        before = snapshot(sync_sandbox["home"])

        result = _run_sync(
            sync_sandbox, "--dry-run", submodule_status="-1234abcd data"
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "would run: git submodule update --init" in result.stdout
        assert "a REAL run would" not in result.stdout, result.stdout
        assert_no_destructive_advice(result)
        assert "previewed rather than performed" in result.stdout
        assert "[8/8]" in result.stdout, result.stdout
        assert snapshot(sync_sandbox["home"]) == before

    def test_the_real_run_of_that_state_does_succeed(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """The claim the preview must not contradict, asserted directly."""
        data = sync_sandbox["pa_dir"] / "data"
        for child in sorted(data.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()

        result = _run_sync(sync_sandbox, submodule_status="-1234abcd data")

        assert result.returncode == 0, result.stdout + result.stderr
        assert_composed(
            sync_sandbox["home"] / ".claude" / "CLAUDE.md", "MARKER-LOCAL"
        )

    def test_a_healthy_dry_run_actually_consults_the_composer(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """Survivor (iii): replacing the passthrough with `:` was invisible.

        sync-symlinks sends the composer's stdout to /dev/null, so "was
        step 7 consulted?" needs the recording wrapper to answer.
        """
        before = snapshot(sync_sandbox["home"])

        result = _run_sync(sync_sandbox, "--dry-run")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "[8/8]" in result.stdout, result.stdout
        recorded = sync_sandbox["log"].read_text(encoding="utf-8")
        assert "compose --dry-run" in recorded, recorded
        assert snapshot(sync_sandbox["home"]) == before

    def test_a_healthy_real_run_consults_the_composer_without_dry_run(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """The negative half: a real run passes no --dry-run through."""
        result = _run_sync(sync_sandbox)

        assert result.returncode == 0, result.stdout + result.stderr
        recorded = sync_sandbox["log"].read_text(encoding="utf-8")
        compose_calls = [
            line for line in recorded.splitlines()
            if line.startswith("compose")
        ]
        assert compose_calls == ["compose"], compose_calls


class TestTheRemedyNeverSaysDeleteALiveSubmodule:
    """C1 — data/ is the PRIVATE pa-data submodule.

    The step-7 pre-check printed one remedy for every non-worktree run:
    "remove …/data entirely". Reached with an INITIALISED submodule that
    merely lacked global-claude-md/local.md, that advice destroys
    uncommitted work, and its parenthesised rationale ("git will not
    clone into a non-empty directory") is not even true of that state.
    """

    @staticmethod
    def _initialised_but_incomplete(pa_dir: Path) -> None:
        """An initialised submodule holding real work but not local.md."""
        data = pa_dir / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()
        (data / ".git").write_text(
            "gitdir: ../.git/modules/data\n", encoding="utf-8"
        )
        (data / "memories").mkdir()
        (data / "memories" / "memories.jsonl").write_text(
            '{"id": "synthetic", "content": "uncommitted work"}\n',
            encoding="utf-8",
        )

    def test_an_initialised_submodule_is_never_told_to_delete_data(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """The state the audit reproduced: initialised, missing one file."""
        self._initialised_but_incomplete(sync_sandbox["pa_dir"])

        result = _run_sync(
            sync_sandbox, submodule_status=" 1234abcd data (heads/main)"
        )

        assert result.returncode == 1, result.stdout
        combined = result.stdout + result.stderr
        assert "remove" not in combined.lower(), combined
        assert "Do NOT delete" in combined
        assert "git -C" in combined and "status" in combined
        # And the work it would have destroyed is still there.
        assert (
            sync_sandbox["pa_dir"] / "data" / "memories" / "memories.jsonl"
        ).is_file()

    def test_an_uninitialised_non_empty_data_still_gets_the_removal(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """The destructive remedy is right for the state it was written for.

        Survivor (i): deleting the remedy line left the suite green, so
        both branches now pin their text.
        """
        data = sync_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()
        (data / "stray.md").write_text("x\n", encoding="utf-8")

        result = _run_sync(
            sync_sandbox, submodule_status="-1234abcd data"
        )

        assert result.returncode == 1, result.stdout
        assert "Remedy: remove" in result.stdout, result.stdout
        assert "will not clone into a non-empty directory" in result.stdout

    def test_a_failed_status_query_never_unlocks_the_removal(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """L9 — `$( … || true )` keeps whatever was printed before a failure.

        A `git submodule status` that emitted a "-" line and THEN failed
        would otherwise be taken as authoritative, and "-" is the one
        answer that unlocks "remove data/ entirely". The remedy now needs
        git to have both said it and succeeded.
        """
        # A stub git that prints the uninitialised line and then fails.
        stub = sync_sandbox["bin"] / "git"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "${1:-}" == "submodule" && "${2:-}" == "status" ]]; then\n'
            '    printf -- "-1234abcd data\\n"\n'
            "    exit 128\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        data = sync_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()
        (data / "memories").mkdir()

        result = _run_sync(sync_sandbox)

        assert result.returncode == 1, result.stdout
        assert "state is unknown" in result.stdout, result.stdout
        assert "Remedy: remove" not in result.stdout, result.stdout
        assert "Do NOT" in result.stdout
        assert (data / "memories").is_dir()

    def test_a_failed_query_never_prints_the_advice_from_either_site(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """M1 — the advice was emitted from TWO places, one unguarded.

        Round 4d-6 guarded the step-7 site. Step 1 interpolated the same
        sentence inline, gated on the "-" prefix alone, so a git that
        printed "-…" and then failed produced BOTH "remove …/data
        entirely" (step 1) and "state is unknown … Do NOT delete"
        (step 7) in one run — contradicting itself, destructively.
        """
        stub = sync_sandbox["bin"] / "git"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "${1:-}" == "submodule" && "${2:-}" == "status" ]]; then\n'
            '    printf -- "-abc data (heads/main)\\n"\n'
            "    exit 1\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        data = sync_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()
        (data / "memories").mkdir()
        (data / "memories" / "memories.jsonl").write_text(
            '{"id": "synthetic"}\n', encoding="utf-8"
        )

        result = _run_sync(sync_sandbox)

        assert_no_destructive_advice(result)
        assert "state is unknown" in result.stdout, result.stdout
        # Step 1 must not assert a state it has no evidence for: with the
        # query failed, "data/ is uninitialised but not empty" is a claim
        # about a submodule git declined to describe.
        assert "'git submodule status' failed" in result.stdout, result.stdout
        assert "uninitialised but not empty" not in result.stdout, (
            result.stdout
        )
        assert (data / "memories" / "memories.jsonl").is_file()

    def test_a_failed_query_with_no_output_is_unknown_not_undeclared(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """L-i — the emptiness test used to be asked first.

        A git exiting 128 having printed nothing was reported as "no data
        submodule is declared": a confident answer drawn from a question
        that was never answered.
        """
        stub = sync_sandbox["bin"] / "git"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "${1:-}" == "submodule" && "${2:-}" == "status" ]]; then\n'
            "    exit 128\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        data = sync_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()

        result = _run_sync(sync_sandbox)

        assert "state is unknown" in result.stdout, result.stdout
        assert "no data submodule is declared" not in result.stdout
        assert_no_destructive_advice(result)

    def test_no_declared_submodule_gets_its_own_remedy(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A checkout with no submodule at all is a third state."""
        data = sync_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()

        result = _run_sync(sync_sandbox, submodule_status="")

        assert result.returncode == 1, result.stdout
        assert "no data submodule is declared" in result.stdout
        assert "remove" not in result.stdout.lower(), result.stdout

    def test_the_composer_says_the_same_thing(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """The composer had the identical defect, keyed on emptiness."""
        data = compose_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()
        (data / ".git").write_text(
            "gitdir: ../.git/modules/data\n", encoding="utf-8"
        )
        (data / "memories").mkdir()

        result = _run_compose(compose_sandbox)

        assert result.returncode == 1
        assert "Remove" not in result.stderr, result.stderr
        assert "Do NOT delete" in result.stderr

    def test_a_directory_shaped_git_also_counts_as_initialised(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """L3 — `-e` versus `-f` on data/.git, made deliberate.

        A submodule checked out the old way, or one converted by hand,
        has a .git DIRECTORY rather than a gitdir: file. It is just as
        initialised, and just as much not-to-be-deleted, so the test is
        `-e`. Nothing exercised that breadth, so tightening it to `-f`
        survived -- and would have met such a checkout with "Remove
        $PA_DIR/data".
        """
        data = compose_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()
        (data / ".git").mkdir()
        (data / ".git" / "HEAD").write_text(
            "ref: refs/heads/main\n", encoding="utf-8"
        )
        (data / "memories").mkdir()

        result = _run_compose(compose_sandbox)

        assert result.returncode == 1
        assert "Remove" not in result.stderr, result.stderr
        assert "Do NOT delete" in result.stderr

    def test_the_composer_still_says_remove_for_an_uninitialised_data(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """Non-empty AND no checkout is the state removal is right for."""
        data = compose_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()
        (data / "stray.md").write_text("x\n", encoding="utf-8")

        result = _run_compose(compose_sandbox)

        assert result.returncode == 1
        assert "Remove" in result.stderr
        assert "no submodule checkout" in result.stderr

    def test_the_composer_handles_an_empty_data_directory(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """Survivor (ii): dropping the `ls -A` conjunct must fail a test.

        data/ present but EMPTY is the state an init fixes, so it must
        get the init advice and not the removal one.
        """
        data = compose_sandbox["pa_dir"] / "data"
        (data / "global-claude-md" / "local.md").unlink()
        (data / "global-claude-md").rmdir()
        assert list(data.iterdir()) == []

        result = _run_compose(compose_sandbox)

        assert result.returncode == 1
        assert "submodule update --init" in result.stderr
        assert "Remove" not in result.stderr, result.stderr


class TestSyncSymlinksRefusesFromAWorktree:
    """Round 4d-2 — steps 2-6 relink the LIVE ~/.claude before step 7 dies.

    From a worktree the link steps repointed every ~/.claude symlink at
    the branch, and only then did the composer refuse and `set -e` abort —
    leaving the operator's configuration half-migrated, with no message
    saying which half.
    """

    def test_a_foreign_root_is_refused_before_step_one(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """Nothing is linked, and no git command runs at all."""
        (sync_sandbox["home"] / "personal-assistant").mkdir()
        before = snapshot(sync_sandbox["home"])

        result = _run_sync(sync_sandbox, "--quiet")

        assert result.returncode == 2, result.stdout
        assert "refusing to relink" in result.stderr
        assert snapshot(sync_sandbox["home"]) == before
        assert sync_sandbox["log"].read_text(encoding="utf-8") == ""

    def test_dry_run_is_exempt(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """Inspecting what a worktree run would do is the flag's purpose."""
        (sync_sandbox["home"] / "personal-assistant").mkdir()
        before = snapshot(sync_sandbox["home"])

        result = _run_sync(sync_sandbox, "--dry-run")

        assert result.returncode == 0, result.stderr
        assert "would run:" in result.stdout
        assert snapshot(sync_sandbox["home"]) == before

    def test_allow_worktree_proceeds(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """The explicit override still works, for a deliberate migration."""
        (sync_sandbox["home"] / "personal-assistant").mkdir()

        result = _run_sync(sync_sandbox, "--quiet", "--allow-worktree")

        assert result.returncode == 0, result.stderr
        assert (
            sync_sandbox["home"] / ".claude" / "commands" / "fossick.md"
        ).is_symlink()


class TestClaudeDirectoryMode:
    """Round 4d-2 — ~/.claude holds settings.json and the global rules."""

    def test_it_is_created_private_under_a_permissive_umask(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """umask 000 must not produce a world-readable ~/.claude."""
        script = sync_sandbox["pa_dir"] / "run-with-umask.sh"
        script.write_text(
            "#!/usr/bin/env bash\numask 000\nexec bash "
            + shlex.quote(str(sync_sandbox["script"]))
            + " --quiet\n",
            encoding="utf-8",
        )
        script.chmod(0o755)

        result = run_script(
            script,
            home=sync_sandbox["home"],
            path_prefix=sync_sandbox["bin"],
            cwd=sync_sandbox["pa_dir"],
            extra_env={"STUB_SUBMODULE_STATUS": " 1234abcd data (main)"},
        )

        assert result.returncode == 0, result.stderr
        mode = (sync_sandbox["home"] / ".claude").stat().st_mode & 0o777
        assert mode == 0o700, oct(mode)


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

    def test_dry_run_narrates_in_the_future_tense(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """A preview must not read as a report of work already done."""
        claude = sync_sandbox["home"] / ".claude"
        commands = claude / "commands"
        commands.mkdir(parents=True)
        stale = commands / "retired.md"
        stale.symlink_to(sync_sandbox["pa_dir"] / "commands" / "retired.md")

        result = _run_sync(sync_sandbox, "--dry-run")

        assert result.returncode == 0, result.stderr
        assert "would prune" in result.stdout, result.stdout
        assert "would link" in result.stdout, result.stdout
        for past in ("— pruned stale", "— linked", "— updated symlink"):
            assert past not in result.stdout, (past, result.stdout)

    def test_a_real_run_still_reports_in_the_past_tense(
        self, sync_sandbox: dict[str, Path]
    ) -> None:
        """The negative half: a real run has actually done the work."""
        result = _run_sync(sync_sandbox)

        assert result.returncode == 0, result.stderr
        assert "— linked" in result.stdout, result.stdout
        assert "would link" not in result.stdout

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


class TestComposerTargetIdentity:
    """Round 4d-2 — the guard keys on WHAT is written, not on a flag.

    Round 4d's version stood down the moment ``--target`` was passed, so
    ``--target "$HOME/.claude/CLAUDE.md"`` from a worktree overwrote the
    protected file and exited 0 — the exact thing the guard existed to
    prevent, reachable by naming it.
    """

    def test_naming_the_live_file_explicitly_is_still_refused(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """--target cannot be used to reach the protected artefact."""
        live = compose_sandbox["home"] / "personal-assistant"
        live.mkdir()
        target = compose_sandbox["home"] / ".claude" / "CLAUDE.md"
        target.parent.mkdir(parents=True)
        target.write_text("the live instructions\n", encoding="utf-8")

        result = _run_compose(
            compose_sandbox, "--target", str(target)
        )

        assert result.returncode == 2, result.stdout
        assert "refusing to write" in result.stderr
        assert target.read_text(encoding="utf-8") == "the live instructions\n"

    def test_a_symlinked_route_to_the_live_file_is_refused(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """Identity is resolved, so a symlinked directory is no way round."""
        (compose_sandbox["home"] / "personal-assistant").mkdir()
        claude = compose_sandbox["home"] / ".claude"
        claude.mkdir()
        target = claude / "CLAUDE.md"
        target.write_text("the live instructions\n", encoding="utf-8")
        alias = compose_sandbox["home"] / "claude-alias"
        alias.symlink_to(claude)

        result = _run_compose(
            compose_sandbox, "--target", str(alias / "CLAUDE.md")
        )

        assert result.returncode == 2, result.stdout
        assert target.read_text(encoding="utf-8") == "the live instructions\n"

    def test_a_symlink_file_to_the_live_target_is_refused(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """Round 4d-3 — the LEAF is resolved, not only its directory.

        Resolving the directory alone left a symlink FILE naming the live
        CLAUDE.md unrecognised: it compared as itself, so the guard did
        not fire. ``mv`` would then have replaced the operator's symlink
        with a regular file and left the live instructions stale but
        present — a quiet failure, and plainly the intent the guard is
        there to refuse.
        """
        (compose_sandbox["home"] / "personal-assistant").mkdir()
        claude = compose_sandbox["home"] / ".claude"
        claude.mkdir()
        target = claude / "CLAUDE.md"
        target.write_text("the live instructions\n", encoding="utf-8")
        link = compose_sandbox["home"] / "link-to-claude-md"
        link.symlink_to(target)

        result = _run_compose(compose_sandbox, "--target", str(link))

        assert result.returncode == 2, result.stdout
        assert "refusing to write" in result.stderr
        assert target.read_text(encoding="utf-8") == "the live instructions\n"

    def test_a_symlink_file_elsewhere_is_still_allowed(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """The negative half: a link to an ordinary file still composes.

        Note what the atomic write does to it: ``mv`` replaces the link
        rather than following it, so the composed document lands AT the
        target path and the link's former destination is untouched. That
        is pre-existing, and safe — it is why the guard above has to work
        on identity rather than on where a write would land.
        """
        (compose_sandbox["home"] / "personal-assistant").mkdir()
        real = compose_sandbox["home"] / "preview" / "CLAUDE.md"
        real.parent.mkdir()
        real.write_text("placeholder\n", encoding="utf-8")
        link = compose_sandbox["home"] / "link-to-preview"
        link.symlink_to(real)

        result = _run_compose(compose_sandbox, "--target", str(link))

        assert result.returncode == 0, result.stderr
        assert "MARKER-LOCAL" in link.read_text(encoding="utf-8")
        assert not link.is_symlink(), "mv followed the link instead"
        assert real.read_text(encoding="utf-8") == "placeholder\n"

    def test_a_relative_symlink_to_the_live_target_is_refused(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """L1 — `readlink -f` must canonicalise, not just read the link.

        Every earlier test linked with an ABSOLUTE path, where plain
        `readlink` happens to give the same answer as `readlink -f`, so
        dropping the flag survived. A relative link separates them: plain
        `readlink` yields ".claude/CLAUDE.md", which matches nothing.
        """
        (compose_sandbox["home"] / "personal-assistant").mkdir()
        claude = compose_sandbox["home"] / ".claude"
        claude.mkdir()
        target = claude / "CLAUDE.md"
        target.write_text("the live instructions\n", encoding="utf-8")
        link = compose_sandbox["home"] / "relative-link"
        link.symlink_to(Path(".claude") / "CLAUDE.md")

        result = _run_compose(compose_sandbox, "--target", str(link))

        assert result.returncode == 2, result.stdout
        assert target.read_text(encoding="utf-8") == "the live instructions\n"

    def test_a_dangling_symlink_to_the_live_target_is_refused(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """L5 — `-e` is false for a dangling link, so `-L` has to be there.

        A link naming the live CLAUDE.md before that file exists slipped
        past the guard entirely and would have been replaced by a regular
        file.
        """
        (compose_sandbox["home"] / "personal-assistant").mkdir()
        claude = compose_sandbox["home"] / ".claude"
        claude.mkdir()
        link = compose_sandbox["home"] / "dangling-link"
        link.symlink_to(claude / "CLAUDE.md")
        assert not link.exists() and link.is_symlink()

        result = _run_compose(compose_sandbox, "--target", str(link))

        assert result.returncode == 2, result.stdout
        assert link.is_symlink(), "the dangling link was replaced by a file"
        assert not (claude / "CLAUDE.md").exists()

    def test_the_live_target_itself_is_resolved(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """L1 — LIVE_TARGET must go through resolve_path, not be literal.

        When ~/.claude is itself a symlinked directory, a literal
        "$HOME/.claude/CLAUDE.md" never equals the resolved target the
        operator names, and the guard silently stops firing.
        """
        (compose_sandbox["home"] / "personal-assistant").mkdir()
        real_claude = compose_sandbox["home"] / "real-claude-dir"
        real_claude.mkdir()
        (compose_sandbox["home"] / ".claude").symlink_to(real_claude)
        target = real_claude / "CLAUDE.md"
        target.write_text("the live instructions\n", encoding="utf-8")

        result = _run_compose(compose_sandbox, "--target", str(target))

        assert result.returncode == 2, result.stdout
        assert target.read_text(encoding="utf-8") == "the live instructions\n"

    def test_an_unusable_live_root_is_refused(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """A file (or dangling symlink) at the live root is not a checkout."""
        (compose_sandbox["home"] / "personal-assistant").write_text(
            "not a checkout\n", encoding="utf-8"
        )
        target = compose_sandbox["home"] / ".claude" / "CLAUDE.md"
        target.parent.mkdir(parents=True)
        target.write_text("the live instructions\n", encoding="utf-8")

        result = _run_compose(compose_sandbox)

        assert result.returncode == 2, result.stdout
        assert "not a usable checkout" in result.stderr
        assert target.read_text(encoding="utf-8") == "the live instructions\n"

    def test_a_dangling_symlink_live_root_is_refused(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """The same, by the route a moved checkout actually leaves behind."""
        (compose_sandbox["home"] / "personal-assistant").symlink_to(
            compose_sandbox["home"] / "moved-away"
        )
        target = compose_sandbox["home"] / ".claude" / "CLAUDE.md"
        target.parent.mkdir(parents=True)
        target.write_text("the live instructions\n", encoding="utf-8")

        result = _run_compose(compose_sandbox)

        assert result.returncode == 2, result.stdout
        assert target.read_text(encoding="utf-8") == "the live instructions\n"

    def test_a_target_elsewhere_is_still_allowed(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """The legitimate --target use is unaffected."""
        (compose_sandbox["home"] / "personal-assistant").mkdir()
        elsewhere = compose_sandbox["home"] / "preview" / "CLAUDE.md"

        result = _run_compose(compose_sandbox, "--target", str(elsewhere))

        assert result.returncode == 0, result.stderr
        assert "MARKER-LOCAL" in elsewhere.read_text(encoding="utf-8")

    def test_a_missing_live_root_warns_rather_than_passing_silently(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """With no checkout to protect the run proceeds, but says so."""
        result = _run_compose(compose_sandbox)

        assert result.returncode == 0, result.stderr
        assert "without a provenance check" in result.stderr


class TestComposerRefusesADirectoryTarget:
    """Round 4d-2 — `mv` onto a directory moves the temp file inside it."""

    def test_a_directory_target_is_a_usage_error(
        self, compose_sandbox: dict[str, Path]
    ) -> None:
        """Exit 2, nothing composed, and no stray temp file left behind."""
        destination = compose_sandbox["home"] / "somewhere"
        destination.mkdir()

        result = _run_compose(
            compose_sandbox, "--target", str(destination)
        )

        assert result.returncode == 2
        assert "must name a file, not a directory" in result.stderr
        assert list(destination.iterdir()) == [], list(destination.iterdir())


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


class TestTheSaltNeverReachesArgv:
    """C2 — /proc/<pid>/cmdline is world-readable; environ is not."""

    @staticmethod
    def _argv_recording_python(bin_dir: Path, log: Path) -> None:
        """Shadow python3 with a wrapper that logs argv, then execs the real one."""
        bin_dir.mkdir(parents=True, exist_ok=True)
        wrapper = bin_dir / "python3"
        wrapper.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >> {shlex.quote(str(log))}\n'
            f"exec {shlex.quote(sys.executable)} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)

    def test_the_salt_is_not_in_the_child_process_argv(
        self, synthetic_env: Path, tmp_path: Path
    ) -> None:
        """The interpreter is invoked without the secret on its command line."""
        home = tmp_path / "home"
        home.mkdir()
        bin_dir = tmp_path / "pybin"
        argv_log = tmp_path / "argv.log"
        argv_log.write_text("", encoding="utf-8")
        self._argv_recording_python(bin_dir, argv_log)

        env = dict(os.environ)
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
        env["ENV_FINGERPRINT_SALT"] = "salt-canary-argv-7e11"
        result = subprocess.run(
            ["bash", str(ENV_FINGERPRINT), str(synthetic_env)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(home),
            timeout=60,
        )

        assert result.returncode == 0, result.stderr
        recorded = argv_log.read_text(encoding="utf-8")
        assert recorded.strip(), "the wrapper never ran"
        assert "salt-canary-argv-7e11" not in recorded, recorded

    def test_a_whitespace_only_salt_is_refused(
        self, synthetic_env: Path, tmp_path: Path
    ) -> None:
        """"   " is not a salt; it passed the old emptiness test."""
        home = tmp_path / "home"
        home.mkdir()

        result = _run_fingerprint(synthetic_env, home, salt="   \t ")

        assert result.returncode == 2
        assert "ENV_FINGERPRINT_SALT" in result.stderr

    def test_surrounding_whitespace_does_not_change_the_digest(
        self, tmp_path: Path
    ) -> None:
        """A salt pasted with a trailing newline still matches its twin."""
        home = tmp_path / "home"
        home.mkdir()
        env_file = tmp_path / "one.env"
        env_file.write_text("SYNTHETIC_ONE=shared-value\n", encoding="utf-8")

        tidy = _run_fingerprint(env_file, home, salt="shared-salt")
        padded = _run_fingerprint(env_file, home, salt="  shared-salt\n")

        assert tidy.returncode == 0 and padded.returncode == 0
        assert tidy.stdout.splitlines()[-3:] == (
            padded.stdout.splitlines()[-3:]
        )

    def test_the_documented_example_keeps_the_salt_off_the_command_line(
        self,
    ) -> None:
        """Both the script header and the reference page must say so."""
        header = ENV_FINGERPRINT.read_text(encoding="utf-8")
        doc = (
            REPO_ROOT / "wiki" / "docs" / "env-cross-machine-reference.md"
        ).read_text(encoding="utf-8")
        # Only the RUNNABLE examples: the page also quotes the old, unsafe
        # form in prose to explain why it was withdrawn.
        runnable = "\n".join(
            block.split("\n", 1)[1]
            for block in doc.split("```bash")[1:]
        ).split("```")[0]
        for text in (header, runnable):
            assert "ENV_FINGERPRINT_SALT='$" not in text, (
                "an example still puts the salt on a command line"
            )
        assert "printf 'export ENV_FINGERPRINT_SALT=%q" in runnable
        assert "| ssh amd-tower 'bash -s'" in runnable

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


class TestEnvFingerprintAgreesWithItsConsumer:
    """Round 4d-2 — the tool must not certify a file the loader cannot read."""

    def test_an_invalid_byte_is_reported_not_papered_over(
        self, tmp_path: Path
    ) -> None:
        """`errors="replace"` produced a clean report for an unreadable file.

        The reported offset is asserted exactly (round 4d-3): reporting
        ``exc.end`` instead of ``exc.start`` points a byte past the
        offending one, which is precisely the sort of off-by-one that
        wastes an operator's afternoon in a file they cannot open safely.
        """
        home = tmp_path / "home"
        home.mkdir()
        env_file = tmp_path / "invalid.env"
        # The 0xff sits at offset 16, counting from zero.
        payload = b"SYNTHETIC_ONE=ab\xffcd\nSYNTHETIC_TWO=fine\n"
        assert payload.index(b"\xff") == 16
        env_file.write_bytes(payload)

        result = _run_fingerprint(env_file, home)

        assert result.returncode == 3, result.stdout
        assert "INVALID UTF-8" in result.stdout
        assert "byte 16 is not valid UTF-8" in result.stdout, result.stdout
        # And no per-key line was emitted, which would have read as healthy.
        assert "SYNTHETIC_ONE\t" not in result.stdout

    def test_the_offset_points_at_the_offending_byte_not_past_it(
        self, tmp_path: Path
    ) -> None:
        """A second file puts the bad byte somewhere else, so the number
        cannot be a coincidence of one fixture."""
        home = tmp_path / "home"
        home.mkdir()
        env_file = tmp_path / "invalid-later.env"
        payload = b"SYNTHETIC_ONE=fine\nSYNTHETIC_TWO=ab\xffcd\n"
        offset = payload.index(b"\xff")
        env_file.write_bytes(payload)

        result = _run_fingerprint(env_file, home)

        assert result.returncode == 3
        assert f"byte {offset} is not valid UTF-8" in result.stdout, (
            result.stdout
        )

    def test_the_loader_really_does_raise_on_that_file(
        self, tmp_path: Path
    ) -> None:
        """The consumer's behaviour, so the two cannot drift apart again."""
        importer_path = REPO_ROOT / "scripts" / "lit-scout-zotero-import.py"
        spec = importlib.util.spec_from_file_location(
            "lit_scout_zotero_import_env", importer_path
        )
        assert spec is not None and spec.loader is not None
        importer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(importer)

        env_file = tmp_path / "invalid.env"
        env_file.write_bytes(b"SYNTHETIC_ONE=ab\xffcd\n")

        with pytest.raises(UnicodeDecodeError):
            importer.load_env(env_file)

    def test_the_duplicate_warning_names_the_winning_assignment(
        self, synthetic_env: Path, tmp_path: Path
    ) -> None:
        """The loader keeps the FIRST assignment; the warning used to say last."""
        home = tmp_path / "home"
        home.mkdir()

        result = _run_fingerprint(synthetic_env, home)

        assert "FIRST assignment wins" in result.stdout
        assert "last wins" not in result.stdout
        # The header must agree with the code it documents (round 4d-3,
        # L1): it still said "the last assignment wins" while the warning
        # it describes had already been corrected.
        header = ENV_FINGERPRINT.read_text(encoding="utf-8")
        assert "last assignment wins" not in header
        assert "FIRST assignment wins" in header

    def test_the_loader_really_keeps_the_first_assignment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pinned against the loader itself, not against a reading of it."""
        importer_path = REPO_ROOT / "scripts" / "lit-scout-zotero-import.py"
        spec = importlib.util.spec_from_file_location(
            "lit_scout_zotero_import_dup", importer_path
        )
        assert spec is not None and spec.loader is not None
        importer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(importer)

        env_file = tmp_path / "duplicates.env"
        env_file.write_text(
            "SYNTHETIC_DUP=first-assignment\n"
            "SYNTHETIC_DUP=second-assignment\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("SYNTHETIC_DUP", raising=False)

        importer.load_env(env_file)

        assert os.environ["SYNTHETIC_DUP"] == "first-assignment"
        monkeypatch.delenv("SYNTHETIC_DUP", raising=False)


# ---------------------------------------------------------------------------
# syncthing-bind-heal.sh — ET15
#
# The only restart anywhere in this tranche. No test referenced the script.
# The stub `docker` below records argv and never contacts a daemon.
# ---------------------------------------------------------------------------

BIND_HEAL = SCRIPTS / "syncthing-bind-heal.sh"


@pytest.fixture
def heal_sandbox(tmp_path: Path) -> dict[str, Path]:
    """A pinned HOME with a stub docker and no Syncthing setup yet."""
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "stubbin"
    log = tmp_path / "argv.log"
    log.write_text("", encoding="utf-8")
    write_stub(bin_dir, "docker", log)
    return {"home": home, "bin": bin_dir, "log": log}


def _run_heal(sandbox: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    """Run the heal script with the stub docker first on PATH."""
    return run_script(
        BIND_HEAL, home=sandbox["home"], path_prefix=sandbox["bin"]
    )


def _compose_setup(home: Path, with_cert: bool) -> Path:
    """Create the compose directory, optionally with a visible cert.pem."""
    compose_dir = home / "docker" / "syncthing"
    (compose_dir / "config").mkdir(parents=True)
    (compose_dir / "docker-compose.yml").write_text(
        "services:\n  syncthing:\n    image: synthetic\n", encoding="utf-8"
    )
    if with_cert:
        (compose_dir / "config" / "cert.pem").write_text(
            "not a real certificate\n", encoding="utf-8"
        )
    return compose_dir


class TestSyncthingBindHeal:
    """ET15 — the preconditions, pinned with a stub docker."""

    def test_no_compose_file_means_no_action(
        self, heal_sandbox: dict[str, Path]
    ) -> None:
        """A machine that does not run the container is a silent no-op.

        The real config IS visible here, so only the missing compose file
        can stop the script — otherwise this would pass for the wrong
        reason (the cert precondition below).
        """
        config = heal_sandbox["home"] / "docker" / "syncthing" / "config"
        config.mkdir(parents=True)
        (config / "cert.pem").write_text(
            "not a real certificate\n", encoding="utf-8"
        )

        result = _run_heal(heal_sandbox)

        assert result.returncode == 0
        assert heal_sandbox["log"].read_text(encoding="utf-8") == ""

    def test_an_absent_cert_means_no_action(
        self, heal_sandbox: dict[str, Path]
    ) -> None:
        """Home not mounted: recreating would re-bind the underlay."""
        _compose_setup(heal_sandbox["home"], with_cert=False)

        result = _run_heal(heal_sandbox)

        assert result.returncode == 0
        assert heal_sandbox["log"].read_text(encoding="utf-8") == ""
        assert "refusing to act" in result.stderr

    def test_both_present_recreates_once(
        self, heal_sandbox: dict[str, Path]
    ) -> None:
        """With the compose file and the real config visible, it recreates."""
        compose_dir = _compose_setup(heal_sandbox["home"], with_cert=True)

        result = _run_heal(heal_sandbox)

        assert result.returncode == 0
        recorded = heal_sandbox["log"].read_text(encoding="utf-8")
        recreates = [
            line
            for line in recorded.splitlines()
            if "up -d --force-recreate" in line
        ]
        assert len(recreates) == 1, recorded
        assert str(compose_dir / "docker-compose.yml") in recreates[0]

    def test_it_always_exits_zero(
        self, heal_sandbox: dict[str, Path]
    ) -> None:
        """A heal script must never break a login or a hook chain."""
        _compose_setup(heal_sandbox["home"], with_cert=True)
        write_stub(
            heal_sandbox["bin"], "docker", heal_sandbox["log"], exit_code=1
        )

        result = _run_heal(heal_sandbox)

        assert result.returncode == 0
        assert "FAILED" in result.stderr


# ---------------------------------------------------------------------------
# syncthing-health.sh — E15 and E16
# ---------------------------------------------------------------------------

HEALTH = SCRIPTS / "syncthing-health.sh"


def _expectations(path: Path, container: str = "syncthing") -> Path:
    """Write a synthetic expectations file naming one unreachable host."""
    path.write_text(
        json.dumps(
            {
                "folder_id": "synthetic-folder",
                "devices": {"AAAAAAA-BBBBBBB": "synthetic-node"},
                "thresholds": {
                    "peer_offline_hours": 48,
                    "stuck_sync_hours": 12,
                },
                "hosts": {
                    "not-this-machine": {
                        "expected_device_id": "AAAAAAA-BBBBBBB",
                        "container": container,
                        "config_dir": "/synthetic/config",
                        "ssh_host": "",
                        "always_on": False,
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


class TestSyncthingHealthAlwaysExitsZero:
    """E15 — `set -u` plus a trailing flag broke the one hard invariant."""

    def test_simulate_need_without_a_value_still_exits_zero(
        self, tmp_path: Path
    ) -> None:
        """A trailing --simulate-need must not kill the monitor."""
        home = tmp_path / "home"
        (home / ".cache").mkdir(parents=True)
        expectations = _expectations(tmp_path / "expected.json")

        result = run_script(
            HEALTH,
            "--quiet",
            "--simulate-need",
            home=home,
            extra_env={"SYNCTHING_EXPECTED_FILE": str(expectations)},
        )

        assert result.returncode == 0, result.stderr
        assert "needs a byte count" in result.stderr

    def test_a_missing_expectations_file_exits_zero(
        self, tmp_path: Path
    ) -> None:
        """The documented degradation: a verdict in the gate, status 0."""
        home = tmp_path / "home"
        (home / ".cache").mkdir(parents=True)

        result = run_script(
            HEALTH,
            "--quiet",
            home=home,
            extra_env={
                "SYNCTHING_EXPECTED_FILE": str(tmp_path / "absent.json")
            },
        )

        assert result.returncode == 0, result.stderr
        gate = (home / ".cache" / "syncthing-gate").read_text(
            encoding="utf-8"
        )
        assert "expectations file missing" in gate


class TestSyncthingHealthQuoting:
    """E16 — a quote in a path must not change the program being run."""

    def test_a_quote_in_the_expectations_path_is_survivable(
        self, tmp_path: Path
    ) -> None:
        """The path reaches Python as argv, so it cannot end a literal."""
        home = tmp_path / "home"
        (home / ".cache").mkdir(parents=True)
        awkward = tmp_path / "it's a dir"
        awkward.mkdir()
        expectations = _expectations(awkward / "expected.json")

        result = run_script(
            HEALTH,
            "--quiet",
            "--local-only",
            home=home,
            extra_env={"SYNCTHING_EXPECTED_FILE": str(expectations)},
        )

        assert result.returncode == 0, result.stderr
        gate = (home / ".cache" / "syncthing-gate").read_text(
            encoding="utf-8"
        )
        # The file was read, so the "missing" branch did not fire...
        assert "expectations file missing" not in gate
        # ...and no embedded Python was corrupted by the apostrophe, which
        # is what interpolating the path into the program text would do.
        assert "SyntaxError" not in result.stderr, result.stderr
        assert "Traceback" not in result.stderr, result.stderr

    def test_no_json_value_is_interpolated_into_a_command_string(
        self,
    ) -> None:
        """Every operator-supplied value is quoted before reaching a shell.

        A source-level assertion: the command strings ``run_on`` builds are
        executed by ``bash -c`` or by ``ssh``, and every interpolation of a
        value out of the expectations JSON must go through ``shq`` (or be
        passed as a positional argument) first. Proving this by execution
        would mean letting a crafted value run a command.

        Round 4d-2 widened this beyond ``$container``/``$config_dir``:
        ``$FOLDER_ID`` was still being pasted into the remote URL.
        """
        source = HEALTH.read_text(encoding="utf-8")
        assert "shq()" in source
        for quoted in (
            'q_container="$(shq "$container")"',
            'q_config_dir="$(shq "$config_dir")"',
            'q_folder_id="$(shq "$(urlencode "$FOLDER_ID")")"',
        ):
            assert quoted in source, quoted
        # No bare interpolation of a JSON-sourced value survives inside a
        # command string handed to a shell.
        for line in source.splitlines():
            if "run_on " not in line and "docker exec" not in line:
                continue
            for name in ("$container", "$config_dir", "$FOLDER_ID"):
                assert name + " " not in line, f"{name} interpolated: {line}"
                assert name + '"' not in line, f"{name} interpolated: {line}"

    def test_the_threshold_is_not_spliced_into_python(self) -> None:
        """Values reach the embedded Python as argv, never as program text.

        Round 4d-2 (C1) found ``$threshold_h`` still spliced into a
        comparison inside a ``python3 -c`` program. A non-numeric value
        there would be a syntax error, and the surrounding ``2>/dev/null``
        would have hidden it.
        """
        source = HEALTH.read_text(encoding="utf-8")
        assert "if hours >= threshold_hours:" in source
        assert "if hours >= $threshold_h:" not in source
        assert "threshold_hours = float(sys.argv[3])" in source


# ---------------------------------------------------------------------------
# syncthing-health.sh check H — the peer-absence alert (round 4d-2, C1)
#
# The E16 rewrite left the peer-absence heredoc reading sys.argv[1..2] while
# the invocation passed nothing, so argv was ['-c'], the third line raised
# IndexError, stderr went to /dev/null, and the alert could never fire
# again. These tests drive the whole check through a stub `docker`.
# ---------------------------------------------------------------------------

#: A dispatching docker stand-in. Every branch answers from the
#: environment, so a test decides what the "mesh" looks like.
_DOCKER_STUB = '''#!/usr/bin/env python3
"""Synthetic docker: answers the queries syncthing-health.sh makes."""
import json
import os
import sys

args = sys.argv[1:]


def emit(payload):
    """Print a JSON payload and exit cleanly."""
    print(json.dumps(payload))
    raise SystemExit(0)


if args and args[0] == "inspect":
    fmt = args[args.index("-f") + 1] if "-f" in args else ""
    print("true" if "Running" in fmt else "2031-01-01T00:00:00Z")
    raise SystemExit(0)

if args and args[0] == "exec":
    rest = args[2:]
    if rest[:3] == ["stat", "-c", "%i"]:
        # Match the host inode so the bind-liveness check passes.
        print(os.stat(os.environ["STUB_CONFIG_DIR"]).st_ino)
        raise SystemExit(0)
    if rest and rest[0] == "syncthing":
        if "system" in rest:
            emit({"myID": os.environ["STUB_DEVICE_ID"]})
        if "folders" in rest:
            # Every configured folder, one per line, as the real CLI does.
            print(os.environ["STUB_FOLDER_LIST"])
            raise SystemExit(0)
        if "connections" in rest:
            emit({"connections": {}})
        raise SystemExit(0)
    if rest and rest[0] == "sh":
        script = rest[2] if len(rest) > 2 else ""
        if "db/status" in script:
            # Record what the inner shell was given positionally, so a test
            # can assert the folder id was PASSED rather than pasted.
            with open(os.environ["STUB_URL_LOG"], "a") as handle:
                handle.write(" ".join(rest[3:]) + "\\n")
            emit({"state": "idle", "errors": 0, "pullErrors": 0,
                  "needBytes": 0})
        if "system/status" in script:
            emit({"discoveryStatus": {}})
        if "stats/device" in script:
            emit(json.loads(os.environ["STUB_DEVICE_STATS"]))
    raise SystemExit(0)

raise SystemExit(0)
'''

#: Invented device identifiers for the synthetic mesh.
_THIS_NODE = "SYNTHET-ICNODE-AAAAAAA"
_PEER_NODE = "SYNTHET-ICPEER-BBBBBBB"


@pytest.fixture
def health_sandbox(tmp_path: Path) -> dict[str, Any]:
    """A pinned HOME, a dispatching stub docker, and a config directory."""
    home = tmp_path / "home"
    (home / ".cache").mkdir(parents=True)
    config_dir = tmp_path / "syncthing-config"
    config_dir.mkdir()
    bin_dir = tmp_path / "stubbin"
    bin_dir.mkdir()
    stub = bin_dir / "docker"
    stub.write_text(_DOCKER_STUB, encoding="utf-8")
    stub.chmod(0o755)
    url_log = tmp_path / "url.log"
    url_log.write_text("", encoding="utf-8")
    return {
        "home": home,
        "bin": bin_dir,
        "config_dir": config_dir,
        "url_log": url_log,
        "tmp": tmp_path,
    }


def _mesh_expectations(
    path: Path,
    this_label: str,
    config_dir: Path,
    folder_id: str,
) -> Path:
    """Write an expectations file for this machine plus one roaming peer."""
    path.write_text(
        json.dumps(
            {
                "folder_id": folder_id,
                "devices": {
                    _THIS_NODE: "this-node",
                    _PEER_NODE: "the-absent-peer",
                },
                "thresholds": {
                    "peer_offline_hours": 48,
                    "stuck_sync_hours": 12,
                },
                "hosts": {
                    this_label: {
                        "expected_device_id": _THIS_NODE,
                        "container": "syncthing",
                        "config_dir": str(config_dir),
                        "ssh_host": "",
                        "always_on": False,
                    },
                    "the-peer": {
                        "expected_device_id": _PEER_NODE,
                        "container": "syncthing",
                        "config_dir": "/synthetic/peer",
                        "ssh_host": "",
                        "always_on": False,
                    },
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _run_health(
    sandbox: dict[str, Any],
    device_stats: dict,
    folder_id: str = "synthetic-folder",
    folder_list: str = "",
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the monitor against the synthetic mesh; return result and gate.

    ``folder_id`` is what the expectations file declares; ``folder_list``
    is what the running daemon reports (defaulting to the same single id).
    They differ only where a test needs the daemon to list a folder whose
    id merely CONTAINS the expected one.
    """
    expectations = _mesh_expectations(
        sandbox["tmp"] / "expected.json",
        socket.gethostname(),
        sandbox["config_dir"],
        folder_id,
    )
    result = run_script(
        HEALTH,
        "--quiet",
        "--local-only",
        home=sandbox["home"],
        path_prefix=sandbox["bin"],
        extra_env={
            "SYNCTHING_EXPECTED_FILE": str(expectations),
            "STUB_CONFIG_DIR": str(sandbox["config_dir"]),
            "STUB_DEVICE_ID": _THIS_NODE,
            "STUB_FOLDER_LIST": folder_list or folder_id,
            "STUB_DEVICE_STATS": json.dumps(device_stats),
            "STUB_URL_LOG": str(sandbox["url_log"]),
        },
    )
    gate = (sandbox["home"] / ".cache" / "syncthing-gate").read_text(
        encoding="utf-8"
    )
    return result, gate


class TestPeerAbsenceAlertActuallyFires:
    """C1 — the alert a silent IndexError had disabled entirely."""

    def test_a_long_absent_peer_is_reported(
        self, health_sandbox: dict[str, Any]
    ) -> None:
        """A peer last seen years ago must reach the gate file."""
        result, gate = _run_health(
            health_sandbox, {_PEER_NODE: {"lastSeen": "2020-01-01T00:00:00Z"}}
        )

        assert result.returncode == 0, result.stderr
        assert "peer(s) absent beyond" in gate, gate
        assert "the-absent-peer" in gate, gate

    def test_a_never_seen_peer_is_reported(
        self, health_sandbox: dict[str, Any]
    ) -> None:
        """The epoch sentinel Syncthing uses for "never" is caught too."""
        _, gate = _run_health(
            health_sandbox, {_PEER_NODE: {"lastSeen": "1970-01-01T00:00:00Z"}}
        )

        assert "the-absent-peer (never)" in gate, gate

    def test_a_recently_seen_peer_is_not_reported(
        self, health_sandbox: dict[str, Any]
    ) -> None:
        """The negative half: a healthy mesh must stay quiet."""
        recent = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=1)
        ).isoformat()
        _, gate = _run_health(
            health_sandbox, {_PEER_NODE: {"lastSeen": recent}}
        )

        assert "peer(s) absent" not in gate, gate

    def test_the_folder_id_reaches_the_url_as_an_argument(
        self, health_sandbox: dict[str, Any]
    ) -> None:
        """The id is passed to the inner shell, not pasted into its text."""
        _run_health(
            health_sandbox,
            {_PEER_NODE: {"lastSeen": "2020-01-01T00:00:00Z"}},
            folder_id="synthetic-folder",
        )

        recorded = health_sandbox["url_log"].read_text(encoding="utf-8")
        assert "synthetic-folder" in recorded, recorded


class TestFolderMembershipIsAWholeLineMatch:
    """Round 4d-3 — ``grep -qxF`` must not relax to ``grep -qF``.

    Without ``-x`` the membership test passes whenever the expected id is
    a SUBSTRING of any configured folder id. A mesh carrying both
    ``pa-data`` and ``pa-data-archive`` would then report the folder
    present when only the archive one existed — the check would pass while
    nothing was syncing the folder that matters.
    """

    def test_a_substring_match_is_not_membership(
        self, health_sandbox: dict[str, Any]
    ) -> None:
        """The daemon lists only a SUPERSTRING of the expected id."""
        result, gate = _run_health(
            health_sandbox,
            {_PEER_NODE: {"lastSeen": "2020-01-01T00:00:00Z"}},
            folder_id="pa-data",
            folder_list="pa-data-archive",
        )

        assert result.returncode == 0, result.stderr
        assert "is MISSING from the running config" in gate, gate

    def test_a_prefix_in_the_list_does_not_satisfy_a_longer_id(
        self, health_sandbox: dict[str, Any]
    ) -> None:
        """And the other direction: a shorter listed id is not a match."""
        _, gate = _run_health(
            health_sandbox,
            {_PEER_NODE: {"lastSeen": "2020-01-01T00:00:00Z"}},
            folder_id="pa-data-archive",
            folder_list="pa-data",
        )

        assert "is MISSING from the running config" in gate, gate

    def test_a_metacharacter_in_the_id_is_matched_literally(
        self, health_sandbox: dict[str, Any]
    ) -> None:
        """``-F`` matters too: an id is data, not a regular expression.

        The dot in ``pa.data`` matches any character once the id is used
        as a pattern, so a daemon carrying only ``paXdata`` would report
        the expected folder present.
        """
        _, gate = _run_health(
            health_sandbox,
            {_PEER_NODE: {"lastSeen": "2020-01-01T00:00:00Z"}},
            folder_id="pa.data",
            folder_list="paXdata",
        )

        assert "is MISSING from the running config" in gate, gate

    def test_a_missing_folder_stops_the_remaining_checks(
        self, health_sandbox: dict[str, Any]
    ) -> None:
        """L6 — the early `return` after a MISSING folder was unpinned.

        Every check after D queries that folder by id. Without the return
        they run anyway against a folder the daemon does not have, and the
        gate fills with derived complaints — "0 bytes behind", a
        peer-absence line — that describe nothing real and bury the one
        problem that matters.
        """
        result, gate = _run_health(
            health_sandbox,
            {_PEER_NODE: {"lastSeen": "2020-01-01T00:00:00Z"}},
            folder_id="pa-data",
            folder_list="some-other-folder",
        )

        assert result.returncode == 0, result.stderr
        assert "is MISSING from the running config" in gate, gate
        # The peer-absence check (H) lives past the return, and its input
        # is available — so if it appears, the return did not happen.
        assert "peer(s) absent beyond" not in gate, gate
        # And no db/status query was issued for a folder that is not there.
        assert health_sandbox["url_log"].read_text(encoding="utf-8") == "", (
            "the folder-status query ran for a folder the daemon lacks"
        )

    def test_an_exact_id_among_several_is_membership(
        self, health_sandbox: dict[str, Any]
    ) -> None:
        """The positive half: the real id listed beside its look-alikes."""
        _, gate = _run_health(
            health_sandbox,
            {_PEER_NODE: {"lastSeen": "2020-01-01T00:00:00Z"}},
            folder_id="pa-data",
            folder_list="pa-data-archive\npa-data\nother-folder",
        )

        assert "is MISSING from the running config" not in gate, gate
        # The run got past check D, so the peer-absence alert still fires.
        assert "peer(s) absent beyond" in gate, gate


class TestSyncthingHealthUnknownArguments:
    """L4 — a typo'd flag ran the full check in silence."""

    def test_a_typo_warns_and_still_exits_zero(
        self, health_sandbox: dict[str, Any]
    ) -> None:
        """`--local-onlt` must say so rather than silently probing SSH."""
        expectations = _mesh_expectations(
            health_sandbox["tmp"] / "expected.json",
            socket.gethostname(),
            health_sandbox["config_dir"],
            "synthetic-folder",
        )

        result = run_script(
            HEALTH,
            "--quiet",
            "--local-onlt",
            home=health_sandbox["home"],
            path_prefix=health_sandbox["bin"],
            extra_env={
                "SYNTHETIC_UNUSED": "1",
                "SYNCTHING_EXPECTED_FILE": str(expectations),
                "STUB_CONFIG_DIR": str(health_sandbox["config_dir"]),
                "STUB_DEVICE_ID": _THIS_NODE,
                "STUB_FOLDER_LIST": "synthetic-folder",
                "STUB_DEVICE_STATS": "{}",
                "STUB_URL_LOG": str(health_sandbox["url_log"]),
            },
        )

        assert result.returncode == 0, result.stderr
        assert "unknown argument '--local-onlt'" in result.stderr
        assert "Usage: syncthing-health.sh" in result.stderr


# ---------------------------------------------------------------------------
# ollama-endpoint.sh — E20 / ET16
# ---------------------------------------------------------------------------

OLLAMA = SCRIPTS / "ollama-endpoint.sh"


def _run_ollama(
    tmp_path: Path, curl_exit: int
) -> subprocess.CompletedProcess[str]:
    """Run the endpoint probe with a stub curl of the given exit status."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    bin_dir = tmp_path / "stubbin"
    log = tmp_path / "curl.log"
    log.write_text("", encoding="utf-8")
    write_stub(bin_dir, "curl", log, exit_code=curl_exit)
    return run_script(OLLAMA, home=home, path_prefix=bin_dir)


class TestOllamaEndpoint:
    """ET16 — no direct test existed; exiting 0 unreachable survived."""

    def test_the_first_reachable_candidate_is_printed(
        self, tmp_path: Path
    ) -> None:
        """A responding probe yields one URL and status 0."""
        result = _run_ollama(tmp_path, curl_exit=0)

        assert result.returncode == 0
        # The FIRST candidate in the script's own list, read from the
        # script rather than restated here: pinning the private LAN
        # address of a specific machine in a public repository is not this
        # test's business (round 4d-2).
        first_candidate = next(
            line.split('"')[1]
            for line in OLLAMA.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith('"http')
        )
        assert result.stdout.strip() == first_candidate

    def test_no_candidate_prints_nothing_and_exits_one(
        self, tmp_path: Path
    ) -> None:
        """E20 — an empty LINE is a value; nothing is not."""
        result = _run_ollama(tmp_path, curl_exit=7)

        assert result.returncode == 1
        assert result.stdout == "", repr(result.stdout)

    def test_the_consuming_idiom_is_documented(self) -> None:
        """`VAR=$(script) cmd` discards the status; say what to do instead."""
        source = OLLAMA.read_text(encoding="utf-8")
        assert "if url=$(" in source


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    raise SystemExit(pytest.main([__file__, "-v"]))
