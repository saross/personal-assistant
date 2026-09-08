"""
Unit tests for ``daily-sync.sh``'s stash bookkeeping helpers.

``push_stash`` and ``stash_ref_for`` are the whole basis of the guarantee
that a run only ever pops or drops a stash it created itself. Their
failure modes — a push that saved nothing, an entry that has moved or
vanished — are awkward to stage through a full sync, so the function
bodies are extracted from the live script and exercised directly against
throwaway repositories.

This is not a source-grep test: the bash actually executed here is the
bash the script runs. It does assume the functions remain self-contained
(no reliance on the script's globals beyond ``LOG_FILE``), which the
extraction below would break loudly on.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DAILY_SYNC = REPO_ROOT / "scripts" / "daily-sync.sh"

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test Bot",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test Bot",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run git deterministically in a throwaway repository."""
    env = os.environ.copy()
    env.update(_GIT_ENV)
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"git {args}: {result.stderr}"
    return result


def _extract_function(name: str) -> str:
    """Return the text of one shell function definition from the script."""
    lines = DAILY_SYNC.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(f"{name}() {{")]
    assert len(starts) == 1, f"expected exactly one definition of {name}"
    start = starts[0]
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


def _run_shell(body: str) -> subprocess.CompletedProcess[str]:
    """Run ``body`` with the stash helpers defined, as the script does."""
    script = "\n".join(
        [
            "set -euo pipefail",
            'LOG_FILE="/dev/null"',
            _extract_function("push_stash"),
            _extract_function("stash_ref_for"),
            body,
        ]
    )
    env = os.environ.copy()
    env.update(_GIT_ENV)
    return subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True, check=False
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A repository holding one commit and one *foreign* stash."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "--quiet", "--initial-branch=main", cwd=repo)
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "--quiet", "-m", "seed", cwd=repo)
    # A concurrent session's stash, which this run must never touch.
    (repo / "tracked.txt").write_text("someone else's work\n", encoding="utf-8")
    _git("stash", "push", "--quiet", "-m", "a concurrent session", cwd=repo)
    return repo


def _stash_shas(repo: Path) -> list[str]:
    """SHAs currently on the stack, newest first."""
    out = _git("stash", "list", "--format=%H", cwd=repo).stdout
    return out.split()


class TestPushStash:
    """``push_stash`` must return the SHA of an entry it actually created."""

    def test_returns_the_new_entry(self, repo: Path) -> None:
        """The happy path: a dirty tree yields a genuinely new SHA."""
        foreign = _stash_shas(repo)[0]
        (repo / "tracked.txt").write_text("our work\n", encoding="utf-8")
        result = _run_shell(f'push_stash "{repo}" "ours"')
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == _stash_shas(repo)[0]
        assert result.stdout.strip() != foreign

    def test_refuses_when_the_push_saved_nothing(self, repo: Path) -> None:
        """Audit M3. `git stash push` exits 0 on a clean tree without
        creating an entry, leaving refs/stash on somebody else's stash.
        Returning that SHA would make the caller pop and drop their work."""
        foreign = _stash_shas(repo)[0]
        result = _run_shell(f'push_stash "{repo}" "ours" || echo REFUSED')
        assert "REFUSED" in result.stdout, result.stdout + result.stderr
        assert foreign not in result.stdout, "returned a foreign stash's SHA"
        assert _stash_shas(repo) == [foreign], "the foreign stash was disturbed"

    def test_refuses_when_a_pathspec_matches_nothing(self, repo: Path) -> None:
        """The same hole through a pathspec that saves nothing."""
        foreign = _stash_shas(repo)[0]
        (repo / "tracked.txt").write_text("our work\n", encoding="utf-8")
        result = _run_shell(
            f"push_stash \"{repo}\" \"ours\" -- ':!tracked.txt' || echo REFUSED"
        )
        assert "REFUSED" in result.stdout, result.stdout + result.stderr
        assert foreign not in result.stdout
        assert _stash_shas(repo) == [foreign]


class TestStashRefFor:
    """``stash_ref_for`` must resolve a SHA to its current selector, and
    say so when the entry has gone."""

    def test_resolves_each_entry_to_its_own_selector(self, repo: Path) -> None:
        """Indices shift; the SHA is what identifies an entry."""
        (repo / "tracked.txt").write_text("second\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "second", cwd=repo)
        (repo / "tracked.txt").write_text("third\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "third", cwd=repo)

        newest, middle, oldest = _stash_shas(repo)
        for sha, expected in (
            (newest, "stash@{0}"),
            (middle, "stash@{1}"),
            (oldest, "stash@{2}"),
        ):
            result = _run_shell(f'stash_ref_for "{repo}" "{sha}"')
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip() == expected

    def test_reports_a_vanished_entry(self, repo: Path) -> None:
        """An entry dropped between our push and our pop is not "the top
        one now" — matching by identity is the whole point."""
        gone = _stash_shas(repo)[0]
        _git("stash", "drop", "--quiet", cwd=repo)
        result = _run_shell(f'stash_ref_for "{repo}" "{gone}" || echo ABSENT')
        assert "ABSENT" in result.stdout, result.stdout + result.stderr
        assert "stash@" not in result.stdout


# ============================================================================
# The unmerged-status regex, at every site that scans porcelain output
# ============================================================================

#: git status(1), "Short Format" § Porcelain — every unmerged state.
UNMERGED_CODES = ["UU", "AA", "DD", "AU", "UA", "DU", "UD"]


def _unmerged_regexes() -> list[str]:
    """Extract every unmerged-status regex literal from the script."""
    found = []
    for line in DAILY_SYNC.read_text(encoding="utf-8").splitlines():
        if "=~ ^(UU" in line:
            regex = line.split("=~ ", 1)[1].rsplit("]]", 1)[0].lstrip()
            # Drop only the single space that separates the regex from
            # `]]` — one site ends in an escaped space, which is part of
            # the pattern and must survive.
            found.append(regex[:-1] if regex.endswith(" ") else regex)
    return found


class TestUnmergedStatusRegex:
    """Four separate blocks scan ``git status --porcelain`` for unmerged
    paths. Narrowing any of them to ``^UU `` would make add/add,
    delete/delete, and the mixed forms invisible: the stash-pop path would
    report "no unmerged paths detected", and the append-only block would
    stage a half-merged corpus.

    The regexes are executed here as bash, exactly as written in the
    script, rather than being matched as text.
    """

    def test_four_sites_scan_for_unmerged_paths(self) -> None:
        """Both rebase resolvers, the stash-pop scan, and the memory check."""
        assert len(_unmerged_regexes()) == 4, _unmerged_regexes()

    @pytest.mark.parametrize("code", UNMERGED_CODES)
    def test_every_site_recognises_every_unmerged_code(self, code: str) -> None:
        """A conflict in any unmerged state must be seen at every site."""
        for index, regex in enumerate(_unmerged_regexes()):
            script = (
                f'line="{code} tasks/inbox.md"\n'
                f'if [[ "$line" =~ {regex} ]]; then echo MATCH; fi\n'
            )
            result = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True, check=False
            )
            assert "MATCH" in result.stdout, (
                f"site {index} does not recognise {code}: {regex}\n{result.stderr}"
            )

    def test_a_clean_status_line_is_not_mistaken_for_a_conflict(self) -> None:
        """`M ` and `??` must not be read as unmerged."""
        for regex in _unmerged_regexes():
            for line in ("M  memories/memories.jsonl", "?? notes/new.md"):
                script = f'if [[ "{line}" =~ {regex} ]]; then echo MATCH; fi\n'
                result = subprocess.run(
                    ["bash", "-c", script], capture_output=True, text=True, check=False
                )
                assert "MATCH" not in result.stdout, (regex, line)
