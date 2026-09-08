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


#: Extracted into every harness shell: the helpers the stash tests below
#: were originally written against.
_BASE_FUNCTIONS = (
    "add_sync_gate_detail",
    "push_stash",
    "stash_ref_for",
    "drop_stash_by_sha",
)


def _run_shell(
    body: str,
    functions: tuple[str, ...] = (),
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run ``body`` with the named script functions defined, as the script does.

    ``functions`` is extracted in addition to ``_BASE_FUNCTIONS``; order
    is irrelevant because bash resolves calls at run time, so the list may
    be given in whatever order reads best at the call site. ``extra_env``
    is the way to hand the shell a string that must not be re-parsed —
    a gate line full of ``$(...)`` interpolations, for instance.
    """
    script = "\n".join(
        [
            "set -euo pipefail",
            'LOG_FILE="/dev/null"',
            # The script's own logger writes to stderr via tee; here it
            # just goes to stderr, which the assertions read.
            'log() { printf "%s\\n" "$*" >&2; }',
            # `fail` exits; the real one also writes a gate line.
            'fail() { printf "FAIL: %s\\n" "$1" >&2; exit "${2:-2}"; }',
            "sync_gate_details=()",
            "DRY_RUN=0",
            *[_extract_function(name) for name in (*_BASE_FUNCTIONS, *functions)],
            body,
        ]
    )
    env = os.environ.copy()
    env.update(_GIT_ENV)
    env.update(extra_env or {})
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


class TestAddSyncGateDetail:
    """The gate is built in memory during a run and rendered once. Two
    blocks reaching the same conclusion must not tell the operator twice
    (audit low, sixth re-audit): the count is the number of lines, so a
    repeat inflates the count as well as the reading."""

    def test_a_repeat_is_dropped(self) -> None:
        """Same text twice, recorded once, order preserved."""
        result = _run_shell(
            'add_sync_gate_detail "first"\n'
            'add_sync_gate_detail "second"\n'
            'add_sync_gate_detail "first"\n'
            'printf "%s\\n" "${#sync_gate_details[@]}" "${sync_gate_details[@]}"\n'
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["2", "first", "second"]

    def test_distinct_details_all_survive(self) -> None:
        """Dedup must not collapse things that merely start alike."""
        result = _run_shell(
            'add_sync_gate_detail "stash 0badc0de could not be dropped"\n'
            'add_sync_gate_detail "stash 0badc0df could not be dropped"\n'
            'printf "%s\\n" "${#sync_gate_details[@]}"\n'
        )
        assert result.stdout.strip() == "2", result.stdout


class TestTemporaryFileGuard:
    """`mktemp` failing must be a `fail` (exit 2), not a bare abort with
    status 1 — which daily-sync-trigger.sh reports as benign lock
    contention (audit low, eighth re-audit)."""

    def test_the_scanner_guards_its_mktemp(self) -> None:
        """Source-level, with its limits stated: the failure needs a
        TMPDIR that cannot be written, which pytest cannot arrange for a
        subprocess without also breaking git. What is checkable is that
        the call is guarded at all — an unguarded `errors="$(mktemp)"`
        aborts under `set -e` with status 1."""
        source = DAILY_SYNC.read_text(encoding="utf-8")
        line = next(
            ln for ln in source.splitlines() if 'errors="$(mktemp' in ln
        )
        assert "|| fail" in line, (
            "the mktemp for the corpus check is unguarded, so a failure "
            "exits 1 and is read as lock contention: " + line
        )


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


class TestDropStashBySha:
    """``drop_stash_by_sha`` is what every restore path relies on to drop
    the entry it applied and no other. Its contract also decides whether
    the orphan path may report "recovered": an entry still on the stack
    would be applied again next run, duplicating every record in it."""

    def test_drops_the_named_entry_not_the_top_one(self, repo: Path) -> None:
        """A foreign stash sits above ours; only ours may go."""
        foreign = _stash_shas(repo)[0]
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        ours = _stash_shas(repo)[0]
        # Another entry lands on top after ours.
        (repo / "tracked.txt").write_text("later\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "later", cwd=repo)
        later = _stash_shas(repo)[0]

        result = _run_shell(f'drop_stash_by_sha "{repo}" "{ours}"')
        assert result.returncode == 0, result.stderr
        remaining = _stash_shas(repo)
        assert ours not in remaining
        assert foreign in remaining
        assert later in remaining

    def test_reports_failure_when_the_entry_has_gone(self, repo: Path) -> None:
        """Non-zero and a warning, so the caller does not claim success —
        the orphan path uses this to say "applied" rather than
        "recovered", and to gate the leftover."""
        gone = _stash_shas(repo)[0]
        _git("stash", "drop", "--quiet", cwd=repo)
        result = _run_shell(f'drop_stash_by_sha "{repo}" "{gone}" || echo REFUSED')
        assert "REFUSED" in result.stdout, result.stdout + result.stderr
        assert "no longer on" in result.stderr


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


# ============================================================================
# The stash-state sidecar: what a run records for the NEXT run to read
# ============================================================================

#: Everything ``write_stash_state`` and its readers need, extracted live.
_SIDECAR_FUNCTIONS = (
    "ancestor_blocks_checkout",
    "mode_matches",
    "append_stash_state_row",
    "write_stash_state",
    "previously_recorded_stashes",
    "record_conflicted_stash",
    "record_partial_stash",
    "partial_records_for",
    "partial_repo_for",
    "describe_stash",
    "unrestored_untracked_paths",
)


def _sidecar_preamble(repo: Path, sidecar: Path) -> str:
    """Shell that puts the sidecar writers in a runnable state."""
    return "\n".join(
        [
            f'STASH_STATE_FILE="{sidecar}"',
            f'DATA_DIR="{repo}"',
            f'PA_DIR="{repo}"',
            "stash_state_written_shas=()",
            "conflicted_stash_records=()",
            "applied_stash_shas=()",
            "partial_stash_shas=()",
            "partial_stash_records=()",
        ]
    )


class TestWriteStashState:
    """The sidecar is how one run tells the next whose markers a
    half-merged tree holds. A row that is wrong sends the operator to
    delete an entry that holds the only copy of something."""

    def test_one_row_per_sha_and_applied_outranks_conflicted(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """Audit M3 (tenth re-audit). An entry that conflicted, was then
        RESOLVED, and whose drop failed is recorded in both lists. Two
        independent loops wrote a row from each, so the stale
        ``conflicted`` row survived alongside the true ``applied`` one —
        and was matched against an unrelated conflict in the same path on
        a later run. Kills: restoring the second `printf ... conflicted`
        loop's independence from the applied loop.
        """
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        sidecar = tmp_path / "sidecar"

        result = _run_shell(
            _sidecar_preamble(repo, sidecar)
            + "\n"
            + f'record_conflicted_stash "{repo}" "{sha}" "memories/memories.jsonl"\n'
            + f'applied_stash_shas+=("{sha}")\n'
            + "write_stash_state\n",
            _SIDECAR_FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        rows = sidecar.read_text(encoding="utf-8").splitlines()
        assert len(rows) == 1, rows
        assert rows[0].split("\t")[2] == "applied", rows

    def test_partial_outranks_applied(self, repo: Path, tmp_path: Path) -> None:
        """Audit S27. `partial` is the one state whose advice is "do not
        delete this entry", so nothing may downgrade it."""
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        sidecar = tmp_path / "sidecar"

        result = _run_shell(
            _sidecar_preamble(repo, sidecar)
            + "\n"
            + f'applied_stash_shas+=("{sha}")\n'
            + f'record_partial_stash "{repo}" "{sha}" "missing\treports/only-here.md"\n'
            + "write_stash_state\n",
            _SIDECAR_FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        rows = sidecar.read_text(encoding="utf-8").splitlines()
        assert len(rows) == 1, rows
        assert rows[0].split("\t")[2] == "partial", rows
        assert rows[0].split("\t")[3] == "reports/only-here.md", rows

    def test_a_dropped_entry_gets_no_row(self, repo: Path, tmp_path: Path) -> None:
        """The write-side expiry. A stash that is gone cannot be the
        source of anything, and a row naming it sends the operator hunting
        for an entry that is not there. Kills: dropping the
        `stash_ref_for ... || return 0` guard in append_stash_state_row.
        """
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        gone = _stash_shas(repo)[0]
        _git("stash", "drop", "--quiet", cwd=repo)
        sidecar = tmp_path / "sidecar"

        result = _run_shell(
            _sidecar_preamble(repo, sidecar)
            + "\n"
            + f'record_conflicted_stash "{repo}" "{gone}" "memories/memories.jsonl"\n'
            + "write_stash_state\n",
            _SIDECAR_FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        assert sidecar.read_text(encoding="utf-8") == "", sidecar.read_text()

    def test_a_path_with_a_space_and_a_comma_survives_the_round_trip(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """Audit L1 (tenth re-audit). The paths were comma-joined into one
        field and word-split on the way back, so `notes/a b, c.md` was read
        as three paths, matched none of them, and lost its attribution —
        for exactly the filenames a human is most likely to create.

        Kills: `"${paths//$'\\n'/,}"` in record_conflicted_stash together
        with `for path in ${paths//,/ }` on the read side. Two paths, so
        the join has something to join and the damage is visible.
        """
        awkward = "notes/a b, c.md"
        plain = "memories/memories.jsonl"
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        sidecar = tmp_path / "sidecar"
        current = f"{awkward}\n{plain}"

        result = _run_shell(
            _sidecar_preamble(repo, sidecar)
            + "\n"
            + f'record_conflicted_stash "{repo}" "{sha}" "{awkward}\n{plain}"\n'
            + "write_stash_state\n"
            + f'previously_recorded_stashes "{repo}" conflicted "{current}"\n',
            _SIDECAR_FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        rows = sidecar.read_text(encoding="utf-8").splitlines()
        assert [r.split("\t")[3] for r in rows] == [awkward, plain], rows
        assert sha[:8] in result.stdout, (
            "a path holding a space and a comma lost its attribution: "
            + result.stdout
        )
        assert awkward in result.stdout, result.stdout
        assert plain in result.stdout, result.stdout


class TestPreviouslyRecordedStashes:
    """Only a stash an earlier run RECORDED conflicting on, that is still
    on the stack, and whose recorded path is unmerged NOW, may be named as
    the source of these markers. Every one of those three conditions has
    "delete an entry holding the only copy of something" on the other
    side of it."""

    def _row(self, repo: Path, sha: str, state: str, path: str) -> str:
        """One sidecar row, in the file's own format."""
        return f"{repo}\t{sha}\t{state}\t{path}\n"

    def test_a_recorded_path_is_matched_whole_not_as_a_substring(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """`grep -qxF`, not `grep -qF`. A row recording `notes/a.md` says
        nothing about a conflict in `notes/a.md.bak`: different file,
        somebody else's conflict, and the advice is to delete an entry
        that has nothing to do with it.

        Kills: `grep -qxF` -> `grep -qF`.
        """
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        sidecar = tmp_path / "sidecar"
        sidecar.write_text(self._row(repo, sha, "conflicted", "notes/a.md"),
                           encoding="utf-8")

        result = _run_shell(
            _sidecar_preamble(repo, sidecar)
            + "\n"
            + f'previously_recorded_stashes "{repo}" conflicted "notes/a.md.bak"\n',
            _SIDECAR_FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "", (
            "a row about notes/a.md was blamed for a conflict in "
            "notes/a.md.bak: " + result.stdout
        )

    def test_a_row_with_no_path_is_never_a_marker_source(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """A path-less row says "this entry's content is already in your
        tree", never "these markers are its content". Without the guard
        the empty field matches nothing and the row is skipped anyway —
        unless `current` is itself empty, at which point every path-less
        row becomes the source of every conflict.

        Kills: `[[ -n "$path" ]] || continue`.
        """
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        sidecar = tmp_path / "sidecar"
        sidecar.write_text(self._row(repo, sha, "conflicted", ""), encoding="utf-8")

        result = _run_shell(
            _sidecar_preamble(repo, sidecar)
            + "\n"
            + f'previously_recorded_stashes "{repo}" conflicted ""\n',
            _SIDECAR_FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "", result.stdout

    def test_a_partial_row_is_not_returned_as_a_conflicted_one(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """The two states get opposite closing advice — "delete that
        entry" versus "recover its files before you delete it" — so the
        reader must not conflate them."""
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        sidecar = tmp_path / "sidecar"
        sidecar.write_text(self._row(repo, sha, "partial", "notes/a.md"),
                           encoding="utf-8")

        conflicted = _run_shell(
            _sidecar_preamble(repo, sidecar)
            + "\n"
            + f'previously_recorded_stashes "{repo}" conflicted "notes/a.md"\n',
            _SIDECAR_FUNCTIONS,
        )
        partial = _run_shell(
            _sidecar_preamble(repo, sidecar)
            + "\n"
            + f'previously_recorded_stashes "{repo}" partial "notes/a.md"\n',
            _SIDECAR_FUNCTIONS,
        )
        assert conflicted.stdout.strip() == "", conflicted.stdout
        assert sha[:8] in partial.stdout, partial.stdout


# ============================================================================
# Classifying a failed `git stash apply` (audit S27)
# ============================================================================

_CLASSIFY_FUNCTIONS = (
    "unmerged_paths",
    "snapshot_before_apply",
    "classify_apply_failure",
    "stash_tracked_half_landed",
    "status_lines_for",
    "unrestored_untracked_paths",
    "ancestor_blocks_checkout",
    "mode_matches",
)


class TestUnmergedPaths:
    """``classify_apply_failure`` feeds two of these lists to ``comm``,
    which compares them with the LOCALE's collating sequence. git emits
    paths in byte order, and the two disagree the moment a repository
    holds both an upper-case and a lower-case name."""

    def test_the_list_is_sorted_for_comm_not_left_in_git_order(
        self, tmp_path: Path
    ) -> None:
        """Kills: dropping `| sort -u` from unmerged_paths.

        git lists `B.md` before `a.md` (byte order); a UTF-8 locale puts
        `a.md` first, and GNU comm compares with the locale's collation.
        Unsorted input makes comm report a path that was ALREADY unmerged
        as new — i.e. blame this apply for somebody else's conflict,
        which is how an entry gets condemned.

        Pinned to a UTF-8 locale, because in the C locale git's order and
        sort's order coincide and there is nothing to test.
        """
        locale = _utf8_locale()
        repo = _conflicted_repo(tmp_path, ["B.md", "a.md"])
        raw = _git(
            "diff", "--name-only", "--diff-filter=U", cwd=repo
        ).stdout.split()
        assert raw == ["B.md", "a.md"], f"git no longer emits byte order: {raw}"

        result = _run_shell(
            f'PA_DIR="{repo}"\nunmerged_paths "{repo}"\n',
            _CLASSIFY_FUNCTIONS,
            {"LC_ALL": locale},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["a.md", "B.md"], (
            "the list is in git's byte order, which comm does not share: "
            + result.stdout
        )

    def test_an_already_unmerged_path_is_not_blamed_on_this_apply(
        self, tmp_path: Path
    ) -> None:
        """The consequence of the sort, at the site that depends on it.

        `comm -13` walks two lists in step. Fed git's byte order under a
        UTF-8 locale it falls out of step at the first case difference and
        reports `B.md` — already unmerged before this apply — as something
        this apply did, which is what condemns an innocent entry.
        """
        locale = _utf8_locale()
        repo = _conflicted_repo(tmp_path, ["B.md", "a.md"])
        result = _run_shell(
            f'PA_DIR="{repo}"\n'
            f'apply_before_unmerged="a.md"\n'
            f'apply_before_status="$(git -C "{repo}" status --porcelain)"\n'
            f'classify_apply_failure "{repo}" HEAD\n'
            'printf "%s\\n" "$apply_outcome_paths"\n',
            _CLASSIFY_FUNCTIONS,
            {"LC_ALL": locale},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["B.md"], (
            "a path that was already unmerged was attributed to this "
            "apply: " + result.stdout
        )

    def test_the_parents_data_gitlink_is_excluded(self, tmp_path: Path) -> None:
        """Audit L3 (tenth re-audit). The parent stash is taken with
        `-- ':!data'`, so it can never contain the gitlink and a conflict
        there can never be its doing. Attributing one to a stash is how an
        entry gets deleted.

        Kills: dropping the `':!data'` pathspec.
        """
        repo = _conflicted_repo(tmp_path, ["data", "settings.json"])
        result = _run_shell(
            f'PA_DIR="{repo}"\nunmerged_paths "{repo}"\n', _CLASSIFY_FUNCTIONS
        )
        assert result.returncode == 0, result.stderr
        assert "settings.json" in result.stdout, result.stdout
        assert "data" not in result.stdout.split(), (
            "the parent's data gitlink was offered as a stash's doing: "
            + result.stdout
        )


class TestUnrestoredUntrackedPaths:
    """The predicate the whole S27 fix rests on: which files are still
    only inside a stash entry."""

    def test_a_file_the_apply_could_not_write_is_reported(
        self, tmp_path: Path
    ) -> None:
        """The measured shape: an untracked file the stash holds, which
        the working tree now holds at somebody else's content."""
        repo = tmp_path / "s27"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "mem.jsonl").write_text("line1\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / "report.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "-u", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        (repo / "report.txt").write_text("theirs\n", encoding="utf-8")

        result = _run_shell(
            f'unrestored_untracked_paths "{repo}" "{sha}"\n', _CLASSIFY_FUNCTIONS
        )
        assert result.returncode == 0, result.stderr
        # `differs`, not `missing`: a copy IS at that path, which is why
        # the apply declined it, and why a checkout would overwrite it.
        assert result.stdout.strip() == "differs\treport.txt", result.stdout

    def test_a_restored_file_is_not_reported(self, tmp_path: Path) -> None:
        """Byte-identical content means the entry holds nothing unique,
        and the drop guard must not stand in the way of an ordinary run."""
        repo = tmp_path / "s27ok"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "mem.jsonl").write_text("line1\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / "report.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "-u", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        (repo / "report.txt").write_text("ours\n", encoding="utf-8")

        result = _run_shell(
            f'unrestored_untracked_paths "{repo}" "{sha}"\n', _CLASSIFY_FUNCTIONS
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "", result.stdout

    def test_an_entry_with_no_untracked_tree_is_silent(self, repo: Path) -> None:
        """A stash pushed without `-u` has no third parent at all; the
        guard must not turn that into a refusal to drop anything, ever."""
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        result = _run_shell(
            f'unrestored_untracked_paths "{repo}" "{sha}"\n', _CLASSIFY_FUNCTIONS
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "", result.stdout


# ============================================================================
# stranded_stashes: which word the operator gets about a leftover entry
# ============================================================================

_STRANDED_FUNCTIONS = (
    "stash_was_partial",
    "stash_was_applied",
    "stash_was_conflicted",
    "stash_was_blocked",
    "stranded_stashes",
)


def _stranded_preamble() -> str:
    """Empty state arrays, as the script has before any apply."""
    return "\n".join(
        [
            "partial_stash_shas=()",
            "applied_stash_shas=()",
            "conflicted_stash_shas=()",
            "blocked_stash_shas=()",
        ]
    )


class TestStrandedStashPrecedence:
    """One entry can be in more than one list — the ordinary
    conflicted-then-resolved-then-undroppable path puts it in two — and
    the states carry opposite advice. The order the checks run in IS the
    advice the operator gets."""

    def test_applied_outranks_conflicted(self, repo: Path) -> None:
        """An apply that conflicted and was then RESOLVED has its content
        in the tree in usable form: the advice is "delete the entry", not
        "resolve the markers" that are no longer there.

        Kills: reordering `stash_was_applied` after `stash_was_conflicted`.
        """
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        result = _run_shell(
            _stranded_preamble()
            + "\n"
            + f'conflicted_stash_shas+=("{sha}")\n'
            + f'applied_stash_shas+=("{sha}")\n'
            + f'stranded_stashes "{repo}" "{sha}"\n',
            _STRANDED_FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.split()[0] == "applied", result.stdout

    def test_partial_outranks_applied(self, repo: Path) -> None:
        """Audit S27: `partial` is the one state whose advice is "do not
        delete this entry", because it still holds the only copy of
        something. Nothing may downgrade it."""
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        result = _run_shell(
            _stranded_preamble()
            + "\n"
            + f'applied_stash_shas+=("{sha}")\n'
            + f'partial_stash_shas+=("{sha}")\n'
            + f'stranded_stashes "{repo}" "{sha}"\n',
            _STRANDED_FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.split()[0] == "partial", result.stdout


# ============================================================================
# Gate supersession keys (audit M2, tenth re-audit)
# ============================================================================

_GATE_KEY_FUNCTIONS = (
    "gate_line_class",
    "gate_sha_keys",
    "gate_claim_keys",
    "gate_subject_keys",
)

#: The line check_interrupted_state writes when it can attribute nothing.
#: It LISTS every entry on the stack precisely because it has no claim to
#: make about any of them.
_UNATTRIBUTED_LINE = (
    "daily-sync STOPPED: /repo (data submodule) has unmerged paths from an "
    "operation this run cannot identify — UU notes/a.md. Resolve them by "
    "hand. Do NOT touch any stash entry until the sync has run far enough "
    "to reconcile orphans; the entries on the stack right now are: "
    "0badc0de stash@{0} On main: daily-sync branch-switch"
)

#: The line the EXIT handler writes about an entry git refused to apply
#: because the index was already unmerged.
_BLOCKED_LINE = (
    "daily-sync could not apply 1 of its own stash(es) because the index "
    "was ALREADY unmerged: data submodule: 0badc0de stash@{0} On main: "
    "daily-sync branch-switch. Their entries are intact and their work is "
    "nowhere else."
)


class TestGateSupersedeKeys:
    """Which gate lines a later run may retire. Getting this wrong in
    either direction is a live failure: too eager erases a still-true
    warning, too shy leaves contradictory advice side by side."""

    def test_the_unattributed_line_claims_no_stash(self) -> None:
        """Audit M2 (tenth re-audit). The SHAs on that line are a listing
        of what is on the stack, not a claim about any of them — so a run
        that can attribute nothing must not retire an earlier run's
        specific, still-true word about every entry it happened to list.

        Kills: harvesting `_our_shas` from the whole line text.
        """
        result = _run_shell(
            f'gate_claim_keys "{_UNATTRIBUTED_LINE}"\n', _GATE_KEY_FUNCTIONS
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["unattributed"], result.stdout
        assert "0badc0de" not in result.stdout, result.stdout

    def test_a_specific_line_claims_its_stash(self) -> None:
        """The other direction: a claim about an entry must still retire
        an earlier, contradictory claim about that same entry."""
        result = _run_shell(
            f'gate_claim_keys "{_BLOCKED_LINE}"\n', _GATE_KEY_FUNCTIONS
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "stash:0badc0de", result.stdout

    def test_every_stash_naming_gate_line_is_classified(self) -> None:
        """A wording change must not silently switch supersession off.

        Every gate detail the script writes that names a stash — by
        `describe_stash` or by a truncated SHA — has to classify as
        something other than `other`, or a later run cannot retire it and
        contradictory advice accumulates.
        """
        source = DAILY_SYNC.read_text(encoding="utf-8")
        naming = [
            line.strip().strip('"')
            for line in source.splitlines()
            if line.strip().startswith('"daily-sync')
            and ("describe_stash" in line or "sha:0:8" in line or "_sha:0:8" in line)
        ]
        assert naming, "no stash-naming gate lines found; has the format changed?"
        for line in naming:
            # The line is handed over in the environment, not spliced into
            # the shell: it is full of `$(describe_stash ...)` and would
            # otherwise be re-parsed rather than classified.
            result = _run_shell(
                'gate_line_class "$PA_TEST_GATE_LINE"\n',
                _GATE_KEY_FUNCTIONS,
                {"PA_TEST_GATE_LINE": line},
            )
            assert result.returncode == 0, result.stderr
            assert result.stdout != "other", (
                "this gate line names a stash but classifies as `other`, so "
                "no later run can retire it: " + line
            )


def _utf8_locale() -> str:
    """
    Return an installed UTF-8 locale, or skip.

    The sort/comm coupling only bites where the locale's collation differs
    from byte order, which the C locale's does not.
    """
    available = subprocess.run(
        ["locale", "-a"], capture_output=True, text=True, check=False
    ).stdout.splitlines()
    for candidate in ("en_AU.utf8", "en_GB.utf8", "en_US.utf8"):
        if candidate in available:
            return candidate
    pytest.skip("no UTF-8 locale installed; git and sort agree in C")


def _conflicted_repo(tmp_path: Path, names: list[str]) -> Path:
    """
    Build a repository whose index holds an add/add conflict on ``names``.

    Used where the test needs unmerged paths without caring how they got
    there. ``data`` among the names becomes a gitlink recorded straight
    into the index (`update-index --cacheinfo 160000`), which is what the
    parent repository's `data` entry is and the only way to stage a
    conflicted submodule pointer without a second working tree.
    """
    repo = tmp_path / ("conflicted-" + "-".join(n.replace("/", "_") for n in names))
    repo.mkdir()
    _git("init", "--quiet", "--initial-branch=main", cwd=repo)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "--quiet", "-m", "seed", cwd=repo)

    def _side(branch: str, content: str, gitlink: str) -> None:
        """Commit one version of every conflicting path on ``branch``."""
        _git("checkout", "--quiet", "-B", branch, "main", cwd=repo)
        for name in names:
            if name == "data":
                _git("update-index", "--add", "--cacheinfo",
                     f"160000,{gitlink},data", cwd=repo)
            else:
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                _git("add", "--", name, cwd=repo)
        _git("commit", "--quiet", "-m", f"{branch} version", cwd=repo)

    # Two distinct, well-formed object names; neither has to exist, and a
    # gitlink to a commit git cannot see is exactly the S1 state anyway.
    _side("theirs", "theirs\n", "1" * 40)
    _side("ours", "ours\n", "2" * 40)
    merge = _run_shell(f'git -C "{repo}" merge theirs || true\n')
    assert merge.returncode == 0, merge.stderr
    return repo


#: Everything the single drop site consults before letting an entry go.
_DROP_GUARD_FUNCTIONS = (
    "drop_applied_stash",
    "unrestored_untracked_paths",
    "ancestor_blocks_checkout",
    "mode_matches",
    "record_partial_stash",
    "describe_stash",
)


class TestDropAppliedStashGuard:
    """The S27 invariant, at the one place that drops an applied entry.
    The classification above decides what the operator is TOLD; this
    decides what happens to the only copy of the file."""

    def test_an_entry_holding_an_unrestored_file_is_never_dropped(
        self, tmp_path: Path
    ) -> None:
        """Kills DS-S27: dropping the `unrestored_untracked_paths` guard
        from `drop_applied_stash`. Without it the entry goes and the file
        — in no commit, no index, and no working tree — goes with it."""
        repo = tmp_path / "guard"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "mem.jsonl").write_text("line1\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / "report.txt").write_text("the only copy\n", encoding="utf-8")
        _git("stash", "push", "-u", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        # The other machine's copy is what is in the tree now, which is
        # why `git stash apply` gave up on the untracked half.
        (repo / "report.txt").write_text("theirs\n", encoding="utf-8")

        result = _run_shell(
            "\n".join(
                [
                    "partial_stash_shas=()",
                    "partial_stash_records=()",
                    "applied_stash_shas=()",
                    f'drop_applied_stash "{repo}" "{sha}" "data submodule" || echo KEPT',
                    'printf "%s\\n" "${partial_stash_shas[@]}"',
                ]
            ),
            _DROP_GUARD_FUNCTIONS,
        )
        assert "KEPT" in result.stdout, result.stdout + result.stderr
        assert sha in result.stdout, "the entry was not recorded as partial"
        assert _stash_shas(repo) == [sha], "the only copy of report.txt was dropped"

    def test_an_entry_whose_files_are_all_back_is_dropped(
        self, tmp_path: Path
    ) -> None:
        """The guard must not become a refusal to drop anything ever: the
        ordinary clean apply has to still tidy up after itself, or every
        run leaves an entry the next one applies again."""
        repo = tmp_path / "guard-ok"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "mem.jsonl").write_text("line1\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / "report.txt").write_text("the only copy\n", encoding="utf-8")
        _git("stash", "push", "-u", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        (repo / "report.txt").write_text("the only copy\n", encoding="utf-8")

        result = _run_shell(
            "\n".join(
                [
                    "partial_stash_shas=()",
                    "partial_stash_records=()",
                    "applied_stash_shas=()",
                    f'drop_applied_stash "{repo}" "{sha}" "data submodule"',
                ]
            ),
            _DROP_GUARD_FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        assert _stash_shas(repo) == [], "the entry was left on the stack"


class TestUnrestoredUntrackedStates:
    """`missing` and `differs` carry opposite recovery commands, and the
    wrong one destroys the other machine's file (audit C1, eleventh
    re-audit)."""

    def _entry_with(self, tmp_path: Path, name: str, make) -> tuple[Path, str]:
        """A repo holding one seed commit and a stash of one untracked
        thing, built by ``make(repo)``."""
        repo = tmp_path / name
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        make(repo)
        _git("stash", "push", "-u", "--quiet", "-m", "ours", cwd=repo)
        return repo, _stash_shas(repo)[0]

    def _report(self, repo: Path, sha: str) -> str:
        """Run the predicate against one entry."""
        result = _run_shell(
            f'unrestored_untracked_paths "{repo}" "{sha}"\n', _CLASSIFY_FUNCTIONS
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    def test_an_absent_path_is_missing_not_differs(self, tmp_path: Path) -> None:
        """The entry really does hold the only copy: a checkout is safe
        and is the only way to get it back."""
        repo, sha = self._entry_with(
            tmp_path,
            "absent",
            lambda r: (r / "report.txt").write_text("only copy\n", encoding="utf-8"),
        )
        assert self._report(repo, sha).strip() == "missing\treport.txt"

    def test_a_present_but_different_path_is_differs(self, tmp_path: Path) -> None:
        """Kills DS-C1: reporting a bare path, so every gate says the file
        exists "ONLY inside the entry" and offers `git checkout <sha>^3 --
        <path>` -- which overwrites the copy that IS there, stages it, and
        has the next run publish it."""
        repo, sha = self._entry_with(
            tmp_path,
            "different",
            lambda r: (r / "report.txt").write_text("ours\n", encoding="utf-8"),
        )
        (repo / "report.txt").write_text("the other machine's\n", encoding="utf-8")
        assert self._report(repo, sha).strip() == "differs\treport.txt"

    def test_an_identical_path_is_reported_at_all(self, tmp_path: Path) -> None:
        """Byte-identical means the entry holds nothing unique, whatever
        git said about it."""
        repo, sha = self._entry_with(
            tmp_path,
            "identical",
            lambda r: (r / "report.txt").write_text("same\n", encoding="utf-8"),
        )
        (repo / "report.txt").write_text("same\n", encoding="utf-8")
        assert self._report(repo, sha).strip() == ""

    def test_a_restored_symlink_is_not_reported_for_ever(
        self, tmp_path: Path
    ) -> None:
        """Kills DS-M2: `hash-object` follows the link and hashes what is
        at the other end -- for a dangling link it fails outright -- so
        every untracked symlink was permanently unrestored, its entry
        could never be dropped, and each run pushed another stash."""
        def _make(repo: Path) -> None:
            """A dangling symlink, which is what a relative link into an
            unmounted tree looks like."""
            (repo / "link").symlink_to("/nowhere/in/particular")

        repo, sha = self._entry_with(tmp_path, "symlink", _make)
        (repo / "link").symlink_to("/nowhere/in/particular")
        assert self._report(repo, sha).strip() == "", (
            "an untracked symlink is unrecoverable for ever"
        )

    def test_a_symlink_pointing_somewhere_else_differs(
        self, tmp_path: Path
    ) -> None:
        """The other direction: a link that now points elsewhere is a
        different file and must still be reported."""
        repo, sha = self._entry_with(
            tmp_path, "symlink2", lambda r: (r / "link").symlink_to("/one/place")
        )
        (repo / "link").symlink_to("/somewhere/else")
        assert self._report(repo, sha).strip() == "differs\tlink"


class TestPartialRecoveryAdvice:
    """The gate's words. The invariant: never advise a command that
    overwrites a file present in the working tree."""

    _FUNCTIONS = ("partial_recovery_advice", "partial_paths_list")

    def test_a_missing_path_gets_a_checkout(self) -> None:
        """Nothing is there, so writing the stashed copy destroys nothing."""
        result = _run_shell(
            'partial_recovery_advice /repo 0badc0de "$PA_TEST_LINES"\n',
            self._FUNCTIONS,
            {"PA_TEST_LINES": "missing\tnotes/a.md"},
        )
        assert result.returncode == 0, result.stderr
        assert "checkout 0badc0de^3" in result.stdout, result.stdout
        assert "DIFFERENT" not in result.stdout, result.stdout

    def test_a_differing_path_never_gets_a_checkout(self) -> None:
        """Kills DS-C1's advice half: a bare checkout here replaces the
        other machine's file, stages it, and the next run publishes it."""
        result = _run_shell(
            'partial_recovery_advice /repo 0badc0de "$PA_TEST_LINES"\n',
            self._FUNCTIONS,
            {"PA_TEST_LINES": "differs\tnotes/a.md"},
        )
        assert result.returncode == 0, result.stderr
        assert "checkout" not in result.stdout, (
            "advised a command that overwrites a file that is present: "
            + result.stdout
        )
        assert "show 0badc0de^3" in result.stdout, result.stdout
        assert "merge by hand" in result.stdout, result.stdout

    def test_both_kinds_in_one_entry_get_their_own_command(self) -> None:
        """One entry can hold both, and the paths must not be pooled."""
        result = _run_shell(
            'partial_recovery_advice /repo 0badc0de "$PA_TEST_LINES"\n',
            self._FUNCTIONS,
            {"PA_TEST_LINES": "missing\tnotes/gone.md\ndiffers\tnotes/here.md"},
        )
        assert result.returncode == 0, result.stderr
        before_show = result.stdout.split("DIFFERENT")[0]
        assert "notes/gone.md" in before_show, result.stdout
        assert "notes/here.md" not in before_show, (
            "a path that is present was swept into the checkout advice: "
            + result.stdout
        )

    def test_the_advice_always_says_how_to_finish(self) -> None:
        """Audit low (eleventh re-audit): without this the entry sits on
        the stack for ever and every run re-reports it."""
        result = _run_shell(
            'partial_recovery_advice /repo 0badc0de "$PA_TEST_LINES"\n',
            self._FUNCTIONS,
            {"PA_TEST_LINES": "missing\tnotes/a.md"},
        )
        assert "stash drop <ref>" in result.stdout, result.stdout


class TestStashAlreadyInTree:
    """The re-apply guard in the EXIT handler. Applying an entry whose
    content is already in the tree lays it on top of itself, which for a
    corpus committed in between means UU markers in the live
    memories.jsonl with rc 0."""

    _FUNCTIONS = (
        "stash_already_in_tree",
        "stash_was_applied",
        "stash_was_conflicted",
        "stash_was_partial",
    )

    def _ask(self, setup: str) -> str:
        """Run the predicate with the state arrays as ``setup`` leaves them."""
        result = _run_shell(
            "partial_stash_shas=()\napplied_stash_shas=()\n"
            "conflicted_stash_shas=()\nblocked_stash_shas=()\n"
            + setup
            + '\nif stash_already_in_tree deadbeef; then echo SKIP; else echo APPLY; fi\n',
            self._FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    @pytest.mark.parametrize(
        "array",
        ["applied_stash_shas", "conflicted_stash_shas", "partial_stash_shas"],
    )
    def test_every_state_that_reached_the_tree_blocks_a_re_apply(
        self, array: str
    ) -> None:
        """Kills: dropping any one of the three from the predicate --
        notably `stash_was_partial`, whose entry has its tracked half in
        the tree already."""
        assert self._ask(f'{array}+=("deadbeef")') == "SKIP"

    def test_an_untouched_entry_is_still_restored(self) -> None:
        """The guard must not become "never restore anything": that is the
        failure mode the EXIT trap exists to prevent."""
        assert self._ask("blocked_stash_shas+=(\"deadbeef\")") == "APPLY"


class TestCarryForwardPartialStashes:
    """Re-reading the sidecar at the start of every run is what keeps a
    partly-applied entry's warning alive. It must not cost one pass over
    the entry's whole untracked tree per RECORDED PATH."""

    def test_each_entry_is_examined_once_however_many_rows_it_has(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """Audit low (eleventh re-audit): the sidecar holds one row per
        path, and re-deriving an entry's state re-reads `<sha>^3` and
        hashes every file in it. Three rows for one entry meant three
        passes at every session start.

        Kills: dropping the `done_shas` guard from
        carry_forward_partial_stashes.
        """
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        sidecar = tmp_path / "sidecar"
        sidecar.write_text(
            "".join(
                f"{repo}\t{sha}\tpartial\tnotes/{name}.md\n"
                for name in ("one", "two", "three")
            ),
            encoding="utf-8",
        )
        calls = tmp_path / "calls"

        result = _run_shell(
            "\n".join(
                [
                    f'STASH_STATE_FILE="{sidecar}"',
                    f'DATA_DIR="{repo}"',
                    f'PA_DIR="{repo}"',
                    "partial_stash_shas=()",
                    "partial_stash_records=()",
                    # A stand-in for the real predicate that counts how
                    # often the entry is examined.
                    "unrestored_untracked_paths() {",
                    f'    printf "call\\n" >> "{calls}"',
                    "    printf 'missing\\tnotes/one.md\\n'",
                    "}",
                    "carry_forward_partial_stashes",
                    'printf "%s\\n" "${#partial_stash_records[@]}"',
                ]
            ),
            ("carry_forward_partial_stashes", "record_partial_stash"),
        )
        assert result.returncode == 0, result.stderr
        assert calls.read_text(encoding="utf-8").count("call") == 1, (
            "the entry was examined once per recorded row: "
            + calls.read_text(encoding="utf-8")
        )
        assert result.stdout.strip() == "1", result.stdout


class TestStashTrackedHalfLanded:
    """The positive evidence `applied` rests on. "The tree changed" is
    not that evidence: git 2.48.1 restores the untracked half BEFORE the
    tracked merge, so an entry whose files came back and whose merge was
    then refused changes the tree without landing a byte of what it was
    asked to land."""

    _FUNCTIONS = ("stash_tracked_half_landed", "status_lines_for")

    def _ask(self, repo: Path, sha: str, before: str, after: str) -> str:
        """Run the predicate over two recorded porcelain snapshots."""
        result = _run_shell(
            'apply_before_status="$PA_TEST_BEFORE"\n'
            'apply_after_status="$PA_TEST_AFTER"\n'
            f'if stash_tracked_half_landed "{repo}" "{sha}"; then\n'
            "  echo LANDED\nelse\n  echo NOT-LANDED\nfi\n",
            self._FUNCTIONS,
            {"PA_TEST_BEFORE": before, "PA_TEST_AFTER": after},
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def _entry(self, tmp_path: Path) -> tuple[Path, str]:
        """A repo whose stash changes one tracked file and adds one
        untracked file -- the shape the C1 sequence needs."""
        repo = tmp_path / "landed"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "t.txt").write_text("base\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / "t.txt").write_text("stashed\n", encoding="utf-8")
        (repo / "u.txt").write_text("new file\n", encoding="utf-8")
        _git("stash", "push", "-u", "--quiet", "-m", "ours", cwd=repo)
        return repo, _stash_shas(repo)[0]

    def test_an_untracked_file_appearing_is_not_the_tracked_half(
        self, tmp_path: Path
    ) -> None:
        """Kills DS-C1: reading `git status` differing as evidence.

        The measured git 2.48.1 signature -- `?? u.txt` appears because
        the untracked half was restored first, and `t.txt` says exactly
        what it said before because the merge was refused.
        """
        repo, sha = self._entry(tmp_path)
        assert self._ask(repo, sha, " M t.txt", " M t.txt\n?? u.txt") == "NOT-LANDED"

    def test_an_unrelated_write_is_not_the_tracked_half(
        self, tmp_path: Path
    ) -> None:
        """The weaker variant: anything at all writing in the window
        between the snapshot and the classification."""
        repo, sha = self._entry(tmp_path)
        assert self._ask(
            repo, sha, " M t.txt", " M t.txt\n?? somebody-elses-file.md"
        ) == "NOT-LANDED"

    def test_the_tracked_path_changing_is_the_tracked_half(
        self, tmp_path: Path
    ) -> None:
        """And the other direction, or nothing would ever be dropped."""
        repo, sha = self._entry(tmp_path)
        assert self._ask(repo, sha, "", " M t.txt") == "LANDED"

    def test_an_entry_with_no_tracked_half_lands_nothing(
        self, tmp_path: Path
    ) -> None:
        """An untracked-only entry has nothing to land, so a changed tree
        says nothing about it either way."""
        repo = tmp_path / "untracked-only"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / "only.txt").write_text("only\n", encoding="utf-8")
        _git("stash", "push", "-u", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        assert self._ask(repo, sha, "", "?? only.txt") == "NOT-LANDED"


class TestAncestorBlocksCheckout:
    """`git checkout <sha>^3 -- <path>` creates every directory on the way
    to <path>. An ancestor that is a regular file is deleted; an ancestor
    that is a symlink -- this repository's whole root layout -- is
    replaced by a real directory."""

    def _report(self, repo: Path, sha: str) -> str:
        """The predicate's verdict for one entry."""
        result = _run_shell(
            f'unrestored_untracked_paths "{repo}" "{sha}"\n', _CLASSIFY_FUNCTIONS
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def _entry_holding(self, tmp_path: Path, name: str, inner: str) -> tuple[Path, str]:
        """A repo whose stash holds one untracked file at ``inner``."""
        repo = tmp_path / name
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        target = repo / inner
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stashed\n", encoding="utf-8")
        _git("stash", "push", "-u", "--quiet", "-m", "ours", cwd=repo)
        return repo, _stash_shas(repo)[0]

    def test_a_regular_file_where_a_directory_belongs_is_differs(
        self, tmp_path: Path
    ) -> None:
        """Kills DS-M1: testing only the leaf. `fileclash/deep.md` is
        absent, but `fileclash` is a FILE -- and the advised checkout
        deletes it."""
        repo, sha = self._entry_holding(tmp_path, "fileclash", "fileclash/deep.md")
        (repo / "fileclash").write_text("somebody's notes\n", encoding="utf-8")
        assert self._report(repo, sha) == "differs\tfileclash/deep.md"

    def test_a_symlinked_ancestor_is_differs(self, tmp_path: Path) -> None:
        """This repository's root is symlinks into the data submodule --
        `memories -> data/memories`, `logs -> data/logs`. Checking a path
        out through one replaces the link with a real directory."""
        repo, sha = self._entry_holding(tmp_path, "linkdir", "linkdir/new.md")
        (repo / "real-target").mkdir()
        (repo / "linkdir").symlink_to("real-target")
        assert self._report(repo, sha) == "differs\tlinkdir/new.md"

    def test_a_real_directory_ancestor_is_still_missing(
        self, tmp_path: Path
    ) -> None:
        """The guard must not turn every nested path into `differs`: an
        ordinary directory is exactly what a checkout expects."""
        repo, sha = self._entry_holding(tmp_path, "plaindir", "notes/new.md")
        (repo / "notes").mkdir(exist_ok=True)
        assert self._report(repo, sha) == "missing\tnotes/new.md"


class TestSymlinkWhereAFileBelongs:
    """A symlink standing where the entry holds a regular file is
    something in the tree, and it is not this."""

    def test_a_symlink_to_identical_content_is_still_differs(
        self, tmp_path: Path
    ) -> None:
        """Kills: deleting the symlink-in-tree branch. Without it the path
        falls through to `hash-object`, which FOLLOWS the link and hashes
        what is at the other end -- so a link pointing at a byte-identical
        file reads as restored, and the entry is dropped while the real
        file it held is nowhere."""
        repo = tmp_path / "linkfile"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / "report.txt").write_text("the same bytes\n", encoding="utf-8")
        _git("stash", "push", "-u", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        # A symlink to a file whose content matches the stashed blob.
        (repo / "elsewhere.txt").write_text("the same bytes\n", encoding="utf-8")
        (repo / "report.txt").symlink_to("elsewhere.txt")

        result = _run_shell(
            f'unrestored_untracked_paths "{repo}" "{sha}"\n', _CLASSIFY_FUNCTIONS
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "differs\treport.txt", result.stdout


class TestModeIsPartOfRestored:
    """Identical bytes at the wrong mode is not a restored file."""

    def test_an_executable_bit_lost_in_the_tree_is_differs(
        self, tmp_path: Path
    ) -> None:
        """Kills DS-L3: comparing content alone. A hook the entry holds as
        100755 and the tree holds as 0644 does not run, and dropping the
        entry loses the only record that it should."""
        repo = tmp_path / "modes"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        script = repo / "hook.sh"
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
        _git("stash", "push", "-u", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        # Same bytes, restored without the bit.
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o644)

        result = _run_shell(
            f'unrestored_untracked_paths "{repo}" "{sha}"\n', _CLASSIFY_FUNCTIONS
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "differs\thook.sh", result.stdout


class TestCorpusLineCount:
    """Both shrink sites count the same way, and a corpus whose last
    record lacks its newline must not read as one record shorter."""

    def test_an_unterminated_last_record_still_counts(self) -> None:
        """Kills DS-L4: `wc -l`, which counts newlines. A commit that only
        drops the trailing terminator then reads as a one-line shrink and
        raises a false exit 4 on a corpus nobody truncated."""
        result = _run_shell(
            'printf \'{"a":1}\\n{"b":2}\' | corpus_line_count\n',
            ("corpus_line_count",),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "2", result.stdout

    def test_a_terminated_corpus_counts_the_same(self) -> None:
        """The same two records, terminated: the count must not move."""
        result = _run_shell(
            'printf \'{"a":1}\\n{"b":2}\\n\' | corpus_line_count\n',
            ("corpus_line_count",),
        )
        assert result.stdout.strip() == "2", result.stdout

    def test_an_empty_corpus_is_zero(self) -> None:
        """`grep -c ''` exits 1 on no match; that must not abort the run."""
        result = _run_shell("printf '' | corpus_line_count\n", ("corpus_line_count",))
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0", result.stdout


class TestAdvisedCheckoutIsSafe:
    """The advised command is run verbatim by a human under stress. It
    must be the command that works."""

    def test_the_path_separator_is_present_and_load_bearing(
        self, tmp_path: Path
    ) -> None:
        """Kills: dropping `--` from the advised checkout. A path
        beginning with a dash is a path, not an option, and without the
        separator git rejects the command the operator was shown."""
        repo = tmp_path / "dash"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        awkward = "-dash-leading.md"
        (repo / awkward).write_text("the only copy\n", encoding="utf-8")
        _git("stash", "push", "-u", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        assert not (repo / awkward).exists()

        advice = _run_shell(
            'partial_recovery_advice "$PA_TEST_REPO" "$PA_TEST_SHA" "$PA_TEST_LINES"\n',
            ("partial_recovery_advice", "partial_paths_list"),
            {
                "PA_TEST_REPO": str(repo),
                "PA_TEST_SHA": sha,
                "PA_TEST_LINES": f"missing\t{awkward}",
            },
        )
        assert advice.returncode == 0, advice.stderr
        assert " -- " in advice.stdout, advice.stdout

        command = advice.stdout.split("restore with ", 1)[1].split(". ", 1)[0]
        run = subprocess.run(command, shell=True, cwd=str(repo),
                             capture_output=True, text=True, check=False)
        assert run.returncode == 0, run.stderr
        assert (repo / awkward).read_text(encoding="utf-8") == "the only copy\n"


class TestSidecarIsWrittenWhole:
    """A sidecar is read by the NEXT run to decide whether an entry may be
    deleted. Half of one is worse than none: rows for some entries and not
    others reads as "that stash produced nothing"."""

    def test_a_failed_write_leaves_the_previous_sidecar_intact(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """Kills DS-L2: unlinking the live file and appending to it with
        `|| true`. The old rows were destroyed before the first byte of
        the new ones was written, and a failure to write them was
        swallowed."""
        holder = tmp_path / "cache"
        holder.mkdir()
        sidecar = holder / "daily-sync-stash-state"
        sidecar.write_text(
            "/somewhere\tdeadbeef\tconflicted\tnotes/a.md\n", encoding="utf-8"
        )
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        holder.chmod(0o555)
        try:
            result = _run_shell(
                _sidecar_preamble(repo, sidecar)
                + "\n"
                + f'record_conflicted_stash "{repo}" "{sha}" "notes/b.md"\n'
                + "write_stash_state\n"
                + 'printf "%s\\n" "${sync_gate_details[@]}"\n',
                _SIDECAR_FUNCTIONS + ("record_partial_stash",),
            )
        finally:
            holder.chmod(0o755)
        assert result.returncode == 0, result.stderr
        assert sidecar.read_text(encoding="utf-8") == (
            "/somewhere\tdeadbeef\tconflicted\tnotes/a.md\n"
        ), "the previous sidecar was destroyed by a write that then failed"
        assert "could not write" in result.stdout, (
            "a sidecar that could not be written said nothing: " + result.stdout
        )
        assert not list(holder.glob("daily-sync-stash-state.*")), (
            "a temporary file was left behind"
        )


    def test_a_row_that_fails_to_write_does_not_replace_the_sidecar(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """Kills DS-L2's second half: renaming the temporary file into
        place regardless of whether every row reached it. A sidecar
        holding some entries and not others reads as "that stash produced
        nothing", which is the verdict that ends in a deleted entry."""
        sidecar = tmp_path / "sidecar"
        sidecar.write_text(
            "/somewhere\tdeadbeef\tconflicted\tnotes/a.md\n", encoding="utf-8"
        )
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]

        result = _run_shell(
            _sidecar_preamble(repo, sidecar)
            + "\n"
            # A row writer that cannot write: a full disk, a revoked
            # permission, anything that fails part-way.
            + "append_stash_state_row() { return 1; }\n"
            + f'record_conflicted_stash "{repo}" "{sha}" "notes/b.md"\n'
            + "write_stash_state\n"
            + 'printf "%s\\n" "${sync_gate_details[@]}"\n',
            _SIDECAR_FUNCTIONS + ("record_partial_stash",),
        )
        assert result.returncode == 0, result.stderr
        assert sidecar.read_text(encoding="utf-8") == (
            "/somewhere\tdeadbeef\tconflicted\tnotes/a.md\n"
        ), "a half-written sidecar replaced a good one"
        assert "could not write" in result.stdout, result.stdout
        assert not list(tmp_path.glob("sidecar.*")), "a temporary file was left behind"


class TestCarriedForwardRows:
    """What the early trap rewrites the sidecar from. A row it does not
    carry is a row the next run cannot read."""

    _FUNCTIONS = (
        "carry_forward_partial_stashes",
        "record_partial_stash",
        "record_conflicted_stash",
        "unrestored_untracked_paths",
        "ancestor_blocks_checkout",
        "mode_matches",
    )

    def _carry(self, repo: Path, sidecar: Path) -> subprocess.CompletedProcess[str]:
        """Run the carry-forward over one sidecar and print what it took."""
        return _run_shell(
            "\n".join(
                [
                    f'STASH_STATE_FILE="{sidecar}"',
                    f'DATA_DIR="{repo}"',
                    f'PA_DIR="{repo}"',
                    "partial_stash_shas=()",
                    "partial_stash_records=()",
                    "conflicted_stash_shas=()",
                    "conflicted_stash_records=()",
                    "carry_forward_partial_stashes",
                    'printf "partial=%s\\n" "${#partial_stash_records[@]}"',
                    'printf "conflicted=%s\\n" "${#conflicted_stash_records[@]}"',
                ]
            ),
            self._FUNCTIONS,
        )

    def test_a_conflicted_row_is_carried(self, repo: Path, tmp_path: Path) -> None:
        """Kills DS-M2: carrying only `partial`. An early exit then
        rewrote the sidecar from this run's arrays alone and dropped every
        previous run's conflicted row -- the rows
        previously_recorded_stashes needs to say whose markers a
        half-merged tree holds."""
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        sidecar = tmp_path / "sidecar"
        sidecar.write_text(f"{repo}\t{sha}\tconflicted\tnotes/a.md\n", encoding="utf-8")

        result = self._carry(repo, sidecar)
        assert result.returncode == 0, result.stderr
        assert "conflicted=1" in result.stdout, result.stdout

    def test_an_applied_row_is_not_carried(self, repo: Path, tmp_path: Path) -> None:
        """Kills: `[[ "$state" == "partial" ]]` -> `-n "$state"`, and the
        same widening of the case below it. An `applied` row is a
        statement about a tree this run has not looked at; re-asserting it
        lets a stale row outlive the state it describes.

        The entry deliberately HOLDS an unrestored untracked file, so a
        widened match would record it as partial rather than falling
        through on an empty comparison.
        """
        (repo / "notes-only.md").write_text("only in the stash\n", encoding="utf-8")
        _git("stash", "push", "-u", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        assert not (repo / "notes-only.md").exists()
        sidecar = tmp_path / "sidecar"
        sidecar.write_text(f"{repo}\t{sha}\tapplied\t\n", encoding="utf-8")

        result = self._carry(repo, sidecar)
        assert result.returncode == 0, result.stderr
        assert "partial=0" in result.stdout, result.stdout
        assert "conflicted=0" in result.stdout, result.stdout


class TestPublishedShrinkPrecondition:
    """The guard is called from two sites, both of which now establish
    that origin/main exists first. Reaching it without one means a push
    site was added without that gate — and a guard that cannot check a
    push must not pass it."""

    def test_a_missing_origin_ref_is_refused_not_waved_through(
        self, tmp_path: Path
    ) -> None:
        """Kills DS-M4's silent `return 0`: the one push that publishes
        commits nothing in the run inspected went out with no record that
        its guard had not run."""
        repo = tmp_path / "no-origin"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "memories").mkdir()
        (repo / "memories" / "memories.jsonl").write_text(
            '{"id": "one"}\n', encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        logs = tmp_path / "logs"
        logs.mkdir()

        result = _run_shell(
            "\n".join(
                [
                    'DETECT_JSONL_SHRINK="true"',
                    f'LOG_DIR="{logs}"',
                    f'DATA_DIR="{repo}"',
                    f'cd "{repo}"',
                    'abort_on_published_shrink "ahead-of-origin push"',
                    "echo REACHED-THE-PUSH",
                ]
            ),
            ("abort_on_published_shrink", "corpus_line_count"),
        )
        assert result.returncode == 4, result.stdout + result.stderr
        assert "REACHED-THE-PUSH" not in result.stdout, (
            "a push the guard could not check was waved through: " + result.stdout
        )
        assert "no origin/main" in result.stderr, result.stderr
