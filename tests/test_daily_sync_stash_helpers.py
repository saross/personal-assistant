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
import re
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
    "status_records",
    "encode_record_path",
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
            f'apply_before_status="$(status_records "{repo}")"\n'
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

    _FUNCTIONS = ("stash_tracked_half_landed", "status_lines_for",
                  "status_records", "encode_record_path")

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
        assert self._ask(repo, sha, " M\tt.txt",
                         " M\tt.txt\n??\tu.txt") == "NOT-LANDED"

    def test_an_unrelated_write_is_not_the_tracked_half(
        self, tmp_path: Path
    ) -> None:
        """The weaker variant: anything at all writing in the window
        between the snapshot and the classification."""
        repo, sha = self._entry(tmp_path)
        assert self._ask(
            repo, sha, " M\tt.txt", " M\tt.txt\n??\tsomebody-elses-file.md"
        ) == "NOT-LANDED"

    def test_the_tracked_path_changing_is_not_enough_on_its_own(
        self, tmp_path: Path
    ) -> None:
        """Audit C1 (third re-audit) corrected this case.

        It used to assert LANDED from a status change alone, with no apply
        having happened at all -- which is precisely the defect: anything
        that writes to one of the entry's paths in the window then reads
        as "the entry landed". The entry's own hunks have to be in the
        files, and here nothing put them there.
        """
        repo, sha = self._entry(tmp_path)
        assert self._ask(repo, sha, "", " M\tt.txt") == "NOT-LANDED"

    def test_an_apply_that_really_landed_is_evidence(
        self, tmp_path: Path
    ) -> None:
        """And the other direction, or nothing would ever be dropped."""
        repo, sha = self._entry(tmp_path)
        _git("stash", "apply", sha, cwd=repo)
        assert self._ask(repo, sha, "", " M\tt.txt\n??\tu.txt") == "LANDED"

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
        assert self._ask(repo, sha, "", "??\tonly.txt") == "NOT-LANDED"


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


class TestTrackedHalfEvidenceIsTheHunks:
    """`applied` -- the verdict that lets an entry be deleted -- must rest
    on the entry's OWN hunks being in the files on disk, not on something
    having changed."""

    _FUNCTIONS = ("stash_tracked_half_landed", "status_lines_for",
                  "status_records", "encode_record_path")

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

    def _two_path_entry(self, tmp_path: Path, name: str) -> tuple[Path, str]:
        """The production shape: one entry touching a prose file and the
        corpus, which is the most-stashed and most-hook-written file here."""
        repo = tmp_path / name
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "t.txt").write_text("base\n", encoding="utf-8")
        (repo / "memories.jsonl").write_text('{"id": "seed"}\n', encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / "t.txt").write_text("stashed\n", encoding="utf-8")
        (repo / "memories.jsonl").write_text(
            '{"id": "seed"}\n{"id": "m1-only-in-stash"}\n', encoding="utf-8"
        )
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        return repo, _stash_shas(repo)[0]

    def test_a_hook_write_during_a_refused_merge_is_not_evidence(
        self, tmp_path: Path
    ) -> None:
        """Kills DS-C1-residual: comparing `git status` LINES.

        A local edit to t.txt makes git refuse the merge outright, and the
        extraction hook appends to memories.jsonl inside the window. Both
        tracked paths' status words then differ, none of it because the
        entry landed -- and the entry holds the only copy of
        m1-only-in-stash.
        """
        repo, sha = self._two_path_entry(tmp_path, "hookwrite")
        # The refusal: git wrote nothing.
        (repo / "t.txt").write_text("a local edit\n", encoding="utf-8")
        before = " M\tt.txt"
        # …and the hook fired in the apply window.
        (repo / "memories.jsonl").write_text(
            '{"id": "seed"}\n{"id": "written-by-the-hook"}\n', encoding="utf-8"
        )
        after = " M\tmemories.jsonl\n M\tt.txt"

        assert self._ask(repo, sha, before, after) == "NOT-LANDED"
        # And the record that would have been destroyed is still there.
        held = _git("show", f"{sha}:memories.jsonl", cwd=repo).stdout
        assert "m1-only-in-stash" in held, held

    def test_one_of_two_tracked_paths_moving_is_not_enough(
        self, tmp_path: Path
    ) -> None:
        """EVERY path the entry touches, not any one of them."""
        repo, sha = self._two_path_entry(tmp_path, "halfway")
        (repo / "memories.jsonl").write_text(
            '{"id": "seed"}\n{"id": "written-by-the-hook"}\n', encoding="utf-8"
        )
        assert self._ask(repo, sha, "", " M\tmemories.jsonl") == "NOT-LANDED"

    def test_a_clean_apply_into_a_tree_that_moved_on_is_evidence(
        self, tmp_path: Path
    ) -> None:
        """The other direction, or nothing would ever be dropped. The
        stash's hunk and the tree's own movement are in different regions,
        which is the ordinary cross-machine case."""
        repo = tmp_path / "movedon"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "f.txt").write_text(
            "".join(f"line {n}\n" for n in range(1, 13)), encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        lines = (repo / "f.txt").read_text(encoding="utf-8").splitlines()
        lines[1] = "line 2 CHANGED BY THE STASH"
        (repo / "f.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        # main moved on, elsewhere in the file…
        lines = (repo / "f.txt").read_text(encoding="utf-8").splitlines()
        lines[9] = "line 10 CHANGED ON MAIN"
        (repo / "f.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "main moved on", cwd=repo)
        # …and the entry applies cleanly on top of it.
        _git("stash", "apply", sha, cwd=repo)

        assert self._ask(repo, sha, "", " M\tf.txt") == "LANDED"

    def test_hunks_already_there_before_the_apply_are_not_evidence(
        self, tmp_path: Path
    ) -> None:
        """Kills DS-C1's second conjunct: dropping the per-path status
        test and resting on the reverse-apply alone.

        The hunks reverse-apply because they ARE in the files -- somebody
        put them there before this apply, which reported a failure and
        moved nothing. `applied` is a claim about what THIS apply did, and
        the entry is kept until something can say so.
        """
        repo, sha = self._two_path_entry(tmp_path, "already-there")
        # The content the entry holds, put there by other means, and
        # committed so the tree is clean and says nothing changed.
        (repo / "t.txt").write_text("stashed\n", encoding="utf-8")
        (repo / "memories.jsonl").write_text(
            '{"id": "seed"}\n{"id": "m1-only-in-stash"}\n', encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "the same edit from elsewhere", cwd=repo)

        assert self._ask(repo, sha, "", "") == "NOT-LANDED"

    def test_a_binary_path_is_never_called_landed(self, tmp_path: Path) -> None:
        """`git diff` says "Binary files differ" and `git apply` refuses
        it. Reading that as not-landed keeps the entry, which is the safe
        direction for a file no text tool can merge."""
        repo = tmp_path / "binary"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "blob.bin").write_bytes(b"\x00\x01\x02seed\n")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / "blob.bin").write_bytes(b"\x00\x01\x02stashed\n")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        (repo / "blob.bin").write_bytes(b"\x00\x01\x02stashed\n")

        assert self._ask(repo, sha, "", " M\tblob.bin") == "NOT-LANDED"


class TestCorpusLineCountIsBinarySafe:
    """The count is what decides whether a shrink is real. Getting it
    wrong upward hides a truncation exactly when the corpus is damaged."""

    def test_a_nul_byte_does_not_inflate_the_count(self, tmp_path: Path) -> None:
        """Kills DS-M-b: `grep -c ''` without `-a`. GNU grep 3.11 treats a
        file holding a NUL as binary and prints "binary file matches"
        instead of a count -- measured 3 for `a\\0b\\nc\\n`, true 2 -- so
        lines_after was inflated precisely when the corpus was corrupt and
        a truncation could pass."""
        corrupt = tmp_path / "nul.jsonl"
        corrupt.write_bytes(b'{"a":1}\x00{"b":2}\n{"c":3}\n')
        result = _run_shell(
            f'corpus_line_count < "{corrupt}"\n', ("corpus_line_count",)
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "2", result.stdout

    def test_a_count_that_cannot_be_produced_is_a_failure(self) -> None:
        """Kills DS-L4: `|| true` in the REAL corpus_line_count. grep
        exits 2 on a read error and prints nothing; the empty string then
        compared as 0 at every call site, so a guard whose measurement had
        failed passed in silence.

        `grep` is shadowed to behave as it does on a read error, which is
        the one way to reach that branch without an unreadable file the
        test would then have to create and clean up.
        """
        result = _run_shell(
            "grep() { return 2; }\n"
            'if printf "x\\n" | corpus_line_count; then\n'
            "  echo PASSED\nelse\n  echo FAILED\nfi\n",
            ("corpus_line_count",),
        )
        assert "FAILED" in result.stdout, result.stdout + result.stderr
        assert "could not count the corpus" in result.stderr, result.stderr

    def test_an_unreadable_blob_stops_the_run(self, tmp_path: Path) -> None:
        """And the caller treats it as one: a guard that cannot measure
        must not wave a push through."""
        repo = tmp_path / "unreadable"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "memories.jsonl").write_text('{"id": "one"}\n', encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)

        result = _run_shell(
            "\n".join(
                [
                    f'cd "{repo}"',
                    f'DATA_DIR="{repo}"',
                    # A counter that cannot count, standing in for grep
                    # exiting 2 on a read error.
                    "corpus_line_count() { return 1; }",
                    'corpus_lines_at "HEAD:memories.jsonl"',
                    "echo REACHED-THE-VERDICT",
                ]
            ),
            ("corpus_lines_at",),
        )
        assert result.returncode == 4, result.stdout + result.stderr
        assert "REACHED-THE-VERDICT" not in result.stdout, result.stdout
        assert "could not count" in result.stderr, result.stderr

    def test_a_blob_that_is_not_there_is_zero_records(
        self, tmp_path: Path
    ) -> None:
        """A path absent from a tree is a real answer, and the commonest
        one: the corpus did not exist before the commit that added it."""
        repo = tmp_path / "absent"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "other.txt").write_text("x\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)

        result = _run_shell(
            "\n".join(
                [
                    f'cd "{repo}"',
                    f'DATA_DIR="{repo}"',
                    'corpus_lines_at "HEAD:memories.jsonl"',
                    'printf "%s\\n" "$corpus_lines"',
                ]
            ),
            ("corpus_lines_at", "corpus_line_count"),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0", result.stdout


class TestOrphanedSidecarTemps:
    """write_stash_state builds the sidecar beside itself and renames it
    into place. A run killed in that window leaves the half-built file
    for ever."""

    _FUNCTIONS = ("sweep_orphaned_stash_state_temps",)

    def test_a_leftover_temp_is_swept(self, tmp_path: Path) -> None:
        """Kills DS-L3: no sweep at all. They accumulate in ~/.cache and
        are indistinguishable from live state to anyone looking."""
        cache = tmp_path / "cache"
        cache.mkdir()
        sidecar = cache / "daily-sync-stash-state"
        sidecar.write_text("/repo\tdeadbeef\tconflicted\tnotes/a.md\n",
                           encoding="utf-8")
        orphan = cache / "daily-sync-stash-state.Ab12Cd"
        orphan.write_text("half a row\n", encoding="utf-8")
        unrelated = cache / "daily-sync-gate"
        unrelated.write_text("0\n", encoding="utf-8")

        result = _run_shell(
            f'STASH_STATE_FILE="{sidecar}"\nsweep_orphaned_stash_state_temps\n',
            self._FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        assert not orphan.exists(), "the orphaned temporary file survived"
        assert sidecar.read_text(encoding="utf-8") == (
            "/repo\tdeadbeef\tconflicted\tnotes/a.md\n"
        ), "the sweep took the sidecar with it"
        assert unrelated.exists(), "the sweep took an unrelated gate file"
        assert not list(cache.glob("*sweepmark*")), "the marker was left behind"


class TestAppendRowWriteFailure:
    """The row writer's own failure path -- not a stub standing in for
    it. A row that never reached the temporary file must stop that file
    being renamed over a good sidecar."""

    def test_a_real_write_failure_keeps_the_previous_sidecar(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """Kills DS-L1: `|| return 1` -> `|| true` in
        append_stash_state_row. The existing test stubbed the whole
        function, so the mutation survived and a part-written temp would
        have been renamed into place -- an empty sidecar over a good one.

        `mktemp` is shadowed to hand back a file it cannot write to,
        which is what a full disk or a revoked permission looks like from
        inside the function. `mv` still succeeds on an unwritable source,
        so without the guard the empty file lands.
        """
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
            + "mktemp() {\n"
            '    local made\n'
            '    made="$(command mktemp "$1")" || return 1\n'
            '    chmod 0444 "$made"\n'
            '    printf "%s" "$made"\n'
            "}\n"
            + f'record_conflicted_stash "{repo}" "{sha}" "notes/b.md"\n'
            + "write_stash_state\n"
            + 'printf "%s\\n" "${sync_gate_details[@]}"\n',
            _SIDECAR_FUNCTIONS + ("record_partial_stash",),
        )
        assert result.returncode == 0, result.stderr
        assert sidecar.read_text(encoding="utf-8") == (
            "/somewhere\tdeadbeef\tconflicted\tnotes/a.md\n"
        ), "a sidecar no row reached was renamed over a good one"
        assert "could not write" in result.stdout, result.stdout
        # audit L2: and the gate says the kept file is an earlier run's.
        assert "EARLIER run's rows" in result.stdout, result.stdout
        assert not list(tmp_path.glob("sidecar.*")), "a temporary file was left"


class TestRetryPushRechecksTheShrink:
    """push_with_retry fetches, rebases, and re-pushes. Every shrink check
    the run has made by then happened BEFORE that rebase -- which is
    exactly where the append-safe resolver rewrites the corpus -- and once
    the retry push succeeds nothing else looks.

    Driven with a stub `git` rather than a real race: what has to be
    pinned is the ORDER of the calls, and staging a genuine push race that
    also conflicts on rebase depends on git's patch-offset heuristics
    rather than on anything this script does.
    """

    def test_the_guard_runs_between_the_rebase_and_the_retry_push(
        self, tmp_path: Path
    ) -> None:
        """Kills DS-L5: dropping the post-rebase abort_on_published_shrink."""
        trace = tmp_path / "trace"
        result = _run_shell(
            "\n".join(
                [
                    'RETRY_ON_REJECT="true"',
                    "RETRY_ATTEMPTS=3",
                    "RETRY_BACKOFF=0",
                    'PA_DIR="/nonexistent"',
                    'RESOLVER="/nonexistent"',
                    "sleep() { :; }",
                    f'trace="{trace}"',
                    # A git that rejects the first push and takes the
                    # second, and rebases cleanly in between.
                    "git() {",
                    '    case "$*" in',
                    '        *"push origin main"*)',
                    '            printf "push\\n" >> "$trace"',
                    '            [[ -f "$trace.pushed" ]] && return 0',
                    '            touch "$trace.pushed"',
                    "            return 1 ;;",
                    '        *"fetch origin main"*) printf "fetch\\n" >> "$trace" ;;',
                    '        *"pull --rebase"*)     printf "rebase\\n" >> "$trace" ;;',
                    '        *"status --porcelain"*) ;;',
                    "    esac",
                    "    return 0",
                    "}",
                    "abort_on_published_shrink() {",
                    '    printf "shrink-check %s\\n" "$1" >> "$trace"',
                    "}",
                    'push_with_retry "data submodule"',
                ]
            ),
            ("push_with_retry",),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        steps = trace.read_text(encoding="utf-8").split()
        assert steps[:1] == ["push"], steps
        assert "rebase" in steps, steps
        rebase_at = steps.index("rebase")
        assert "shrink-check" in steps[rebase_at:], (
            "the corpus was never re-measured after the rebase: " + str(steps)
        )
        check_at = steps.index("shrink-check", rebase_at)
        assert "push" in steps[check_at:], (
            "the re-check did not precede the retry push: " + str(steps)
        )

    def test_the_parent_repo_is_not_measured(self, tmp_path: Path) -> None:
        """The parent holds no corpus; asking about one there would fail
        the run on a repository the guard knows nothing about."""
        trace = tmp_path / "trace-parent"
        result = _run_shell(
            "\n".join(
                [
                    'RETRY_ON_REJECT="true"',
                    "RETRY_ATTEMPTS=3",
                    "RETRY_BACKOFF=0",
                    'PA_DIR="/nonexistent"',
                    'RESOLVER="/nonexistent"',
                    "sleep() { :; }",
                    f'trace="{trace}"',
                    "git() {",
                    '    case "$*" in',
                    '        *"push origin main"*)',
                    '            [[ -f "$trace.pushed" ]] && return 0',
                    '            touch "$trace.pushed"',
                    "            return 1 ;;",
                    "    esac",
                    "    return 0",
                    "}",
                    'abort_on_published_shrink() { printf "shrink-check\\n" >> "$trace"; }',
                    'push_with_retry "parent repo"',
                ]
            ),
            ("push_with_retry",),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert not trace.exists(), "the parent repo was measured for a corpus"


class TestUnattributableShrinkFailsClosed:
    """The outer comparison sees the corpus shorter than origin's; the
    per-commit loop names no commit that shortened it. That is a history
    this guard does not understand, which is the last state in which to
    assume the best."""

    def _repo_with(self, tmp_path: Path, records: int) -> Path:
        """A repo whose HEAD holds ``records`` corpus lines."""
        repo = tmp_path / f"unattributable-{records}"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "memories").mkdir()
        (repo / "memories" / "memories.jsonl").write_text(
            "".join(f'{{"id": "r{n}"}}\n' for n in range(records)), encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        return repo

    def _run_guard(self, repo: Path, logs: Path) -> subprocess.CompletedProcess[str]:
        """Call the published-shrink guard inside ``repo``."""
        return _run_shell(
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
            (
                "abort_on_published_shrink",
                "corpus_lines_at",
                "corpus_line_count",
                "has_bulk_rewrite_trailer",
            ),
        )

    def test_a_shrink_no_commit_explains_is_refused(self, tmp_path: Path) -> None:
        """Kills DS-M1's fail-open: `return 0` when the loop named nobody.

        origin/main is set to a commit that is NOT an ancestor of HEAD and
        holds more records -- a diverged branch about to be published --
        so the range holds no commit that shortened anything, and the
        guard used to allow it.
        """
        repo = self._repo_with(tmp_path, 1)
        logs = tmp_path / "logs-unattributable"
        logs.mkdir()
        # A richer corpus on a side history, published as origin/main.
        _git("checkout", "--quiet", "-b", "side", cwd=repo)
        (repo / "memories" / "memories.jsonl").write_text(
            "".join(f'{{"id": "r{n}"}}\n' for n in range(5)), encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "the other machine's captures", cwd=repo)
        side = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
        _git("checkout", "--quiet", "main", cwd=repo)
        # A local commit that touches nothing of the corpus.
        (repo / "notes.md").write_text("a prose file\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "prose", cwd=repo)
        _git("update-ref", "refs/remotes/origin/main", side, cwd=repo)

        result = self._run_guard(repo, logs)
        assert result.returncode == 4, result.stdout + result.stderr
        assert "REACHED-THE-PUSH" not in result.stdout, result.stdout
        reports = list(logs.glob("daily-sync-shrink-*.log"))
        assert reports, "no report was written"
        written = reports[0].read_text(encoding="utf-8")
        assert "could not be attributed" in written, written

    def test_a_shrink_every_commit_owns_is_still_allowed(
        self, tmp_path: Path
    ) -> None:
        """The fail-closed rule must not swallow the escape hatch: a
        commit that shortened it and says so still publishes."""
        repo = self._repo_with(tmp_path, 5)
        logs = tmp_path / "logs-allowed"
        logs.mkdir()
        origin = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
        _git("update-ref", "refs/remotes/origin/main", origin, cwd=repo)
        (repo / "memories" / "memories.jsonl").write_text(
            '{"id": "kept"}\n', encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m",
             "chore(memories): monthly archive\n\nRewrite-Class: bulk\n", cwd=repo)

        result = self._run_guard(repo, logs)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "REACHED-THE-PUSH" in result.stdout, result.stdout


class TestSweepNarrowing:
    """The sweep deletes files in ~/.cache. Both of the clauses that keep
    it from deleting the wrong ones have to stay."""

    _FUNCTIONS = ("sweep_orphaned_stash_state_temps",)

    def _cache(self, tmp_path: Path) -> tuple[Path, Path]:
        """A cache directory holding a real sidecar."""
        cache = tmp_path / "cache-narrowing"
        cache.mkdir()
        sidecar = cache / "daily-sync-stash-state"
        sidecar.write_text("/repo\tdeadbeef\tconflicted\tnotes/a.md\n",
                           encoding="utf-8")
        return cache, sidecar

    def test_a_temp_newer_than_the_sweep_survives(self, tmp_path: Path) -> None:
        """Kills: dropping `! -newer "$marker"`. The clause is what keeps a
        writer this reasoning has not anticipated from losing its
        half-built sidecar; without it the sweep takes whatever it finds."""
        cache, sidecar = self._cache(tmp_path)
        fresh = cache / "daily-sync-stash-state.Fr3sh1"
        fresh.write_text("a writer that is still going\n", encoding="utf-8")
        # Dated after the marker the sweep is about to create.
        subprocess.run(["touch", "-d", "+1 hour", str(fresh)], check=True)

        result = _run_shell(
            f'STASH_STATE_FILE="{sidecar}"\nsweep_orphaned_stash_state_temps\n',
            self._FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        assert fresh.exists(), "the sweep took a file newer than itself"

    def test_a_differently_named_neighbour_survives(self, tmp_path: Path) -> None:
        """Kills: widening the glob to `${base}.*`. The six characters are
        exactly what mktemp appends; anything else in that directory
        belongs to something else."""
        cache, sidecar = self._cache(tmp_path)
        neighbour = cache / "daily-sync-stash-state.backup-before-the-upgrade"
        neighbour.write_text("somebody kept this on purpose\n", encoding="utf-8")
        orphan = cache / "daily-sync-stash-state.Ab12Cd"
        orphan.write_text("half a row\n", encoding="utf-8")

        result = _run_shell(
            f'STASH_STATE_FILE="{sidecar}"\nsweep_orphaned_stash_state_temps\n',
            self._FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        assert not orphan.exists(), "the orphan survived"
        assert neighbour.exists(), (
            "the sweep took a file that is not one of its temporaries"
        )

    def test_a_marker_a_killed_run_left_is_itself_sweepable(
        self, tmp_path: Path
    ) -> None:
        """Audit L-a: the marker used to be named so that the glob could
        never match it, so a run killed between creating it and removing
        it left litter no sweep could collect -- the very thing this
        function exists to prevent."""
        cache, sidecar = self._cache(tmp_path)
        stranded = cache / "daily-sync-stash-state.MRK123"
        stranded.write_text("", encoding="utf-8")
        subprocess.run(["touch", "-d", "-1 hour", str(stranded)], check=True)

        result = _run_shell(
            f'STASH_STATE_FILE="{sidecar}"\nsweep_orphaned_stash_state_temps\n',
            self._FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        assert not stranded.exists(), (
            "a marker a killed run left behind is unreachable by any sweep"
        )
        assert sidecar.exists(), "the sweep took the sidecar"


class TestRenameOnlyStash:
    """Git reports a rename by its DESTINATION alone, so a rename-only
    entry contributed one path and the pathspec-limited diff then dropped
    the source's deletion."""

    _FUNCTIONS = ("stash_tracked_half_landed", "status_lines_for",
                  "status_records", "encode_record_path")

    def _renaming_entry(self, tmp_path: Path) -> tuple[Path, str]:
        """A repo whose stash is a pure rename."""
        repo = tmp_path / "renaming"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "old.md").write_text("content that stays identical\n",
                                     encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        _git("mv", "old.md", "new.md", cwd=repo)
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        return repo, _stash_shas(repo)[0]

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

    def test_a_half_done_rename_is_not_landed(self, tmp_path: Path) -> None:
        """Kills DS-L-d: `--name-only` without `--no-renames`.

        The destination arrived and the source was never removed. With
        only the destination in the path set, what was left of the diff --
        "create new.md" -- reverse-applied cleanly while old.md was still
        sitting there, and the entry was called landed and dropped though
        the rename had never completed.
        """
        repo, sha = self._renaming_entry(tmp_path)
        (repo / "new.md").write_text("content that stays identical\n",
                                     encoding="utf-8")
        assert (repo / "old.md").exists(), "the fixture did not model a half-rename"
        assert self._ask(repo, sha, "", " M\told.md\n??\tnew.md") == "NOT-LANDED"

    def test_a_completed_rename_is_landed(self, tmp_path: Path) -> None:
        """The other direction: a rename the apply really did complete."""
        repo, sha = self._renaming_entry(tmp_path)
        _git("stash", "apply", sha, cwd=repo)
        assert not (repo / "old.md").exists()
        # status_records gives a rename BOTH of its paths, one row each.
        assert self._ask(repo, sha, "", "R \told.md\nR \tnew.md") == "LANDED"


class TestBinaryStashIsNotCalledRefused:
    """`git apply` will not take a binary diff, so the tracked-half check
    says "not landed" about an entry that may have landed perfectly well.
    Keeping it is right; telling the operator git declined the merge is
    not."""

    def test_a_binary_tracked_half_is_recognised(self, tmp_path: Path) -> None:
        """Kills DS-L-c: no binary case at all, so the `refused` wording
        was given to an entry nothing had refused."""
        repo = tmp_path / "binary-detect"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "blob.bin").write_bytes(b"\x00\x01seed\n")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / "blob.bin").write_bytes(b"\x00\x01stashed\n")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]

        result = _run_shell(
            f'if stash_tracked_half_is_binary "{repo}" "{sha}"; then\n'
            "  echo BINARY\nelse\n  echo TEXT\nfi\n",
            ("stash_tracked_half_is_binary",),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "BINARY", result.stdout

    def test_a_text_tracked_half_is_not_called_binary(
        self, tmp_path: Path
    ) -> None:
        """Or every ordinary entry would get the binary wording."""
        repo = tmp_path / "text-detect"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "notes.md").write_text("seed\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / "notes.md").write_text("stashed\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]

        result = _run_shell(
            f'if stash_tracked_half_is_binary "{repo}" "{sha}"; then\n'
            "  echo BINARY\nelse\n  echo TEXT\nfi\n",
            ("stash_tracked_half_is_binary",),
        )
        assert result.stdout.strip() == "TEXT", result.stdout


class TestMergeWithNoCorpusInAnyParent:
    """A merge none of whose parents holds the corpus cannot be measured
    against anything, and the corpus it publishes came from its own
    resolution."""

    def test_it_is_refused_as_unjudgeable(self, tmp_path: Path) -> None:
        """Kills DS-M1's refusal branch. Counting a corpus-less parent as
        zero records leaves this refused too -- by the fail-closed rule --
        but saying "the shrink could not be attributed" of a merge whose
        parents simply have no corpus sends the operator looking for the
        wrong thing."""
        repo = tmp_path / "no-corpus-parents"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "memories").mkdir()
        (repo / "memories" / "memories.jsonl").write_text(
            "".join(f'{{"id": "r{n}"}}\n' for n in range(5)), encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "the published corpus", cwd=repo)
        origin = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
        _git("update-ref", "refs/remotes/origin/main", origin, cwd=repo)

        # Two parentless commits, neither holding a corpus…
        empty = _git("hash-object", "-wt", "tree", "/dev/null", cwd=repo).stdout.strip()
        one = _git("commit-tree", empty, "-m", "side one", cwd=repo).stdout.strip()
        two = _git("commit-tree", empty, "-m", "side two", cwd=repo).stdout.strip()
        # …merged into a commit that introduces a corpus of its own.
        (repo / "memories" / "memories.jsonl").write_text(
            '{"id": "one record"}\n', encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        tree = _git("write-tree", cwd=repo).stdout.strip()
        merge = _git(
            "commit-tree", tree, "-p", one, "-p", two, "-m", "Merge two strangers",
            cwd=repo
        ).stdout.strip()
        _git("reset", "--quiet", "--hard", merge, cwd=repo)
        logs = tmp_path / "logs-no-corpus"
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
            (
                "abort_on_published_shrink",
                "corpus_lines_at",
                "corpus_line_count",
                "has_bulk_rewrite_trailer",
            ),
        )
        assert result.returncode == 4, result.stdout + result.stderr
        assert "REACHED-THE-PUSH" not in result.stdout, result.stdout
        written = next(iter(logs.glob("daily-sync-shrink-*.log"))).read_text(
            encoding="utf-8"
        )
        assert "none of its parents holds the corpus" in written, written


#: The functions that are allowed to run a quiet grep, and the reason
#: each is safe: none of them has a producer on the far side of a pipe.
#: Asserted as a SET rather than a count (audit 3, sixth re-audit): a
#: decorative fifth site would restore vacuity to a count, and a correct
#: refactor that moves one would fail it for no reason.
_QUIET_GREP_SITES = {
    "render_sync_gate",              # gate supersession, here-string
    "previously_recorded_stashes",   # sidecar path matching, here-string
    "has_bulk_rewrite_trailer",      # the trailer, here-string
}

#: `grep -q`, `grep -Fqx`, `grep --quiet` — every spelling of "tell me
#: yes or no and stop reading" (audit 2, sixth re-audit).
_QUIET_GREP = re.compile(r"\bgrep\s+(?:-[A-Za-z]*q|--quiet)")


def _script_statements() -> list[tuple[int, str, str]]:
    """
    The script as `(line number, enclosing function, statement)` triples.

    Continuation lines and lines ending in a pipe are joined, so a
    pipeline written across several lines is one statement — the shape
    that walked through the previous line-at-a-time scan. Heredoc bodies
    are skipped entirely: the embedded Python in this script is not shell
    and must not be linted as though it were. A trailing inline comment
    is dropped, so prose about the rule cannot satisfy or violate it.
    """
    lines = DAILY_SYNC.read_text(encoding="utf-8").splitlines()
    statements: list[tuple[int, str, str]] = []
    function = ""
    heredoc = ""
    pending = ""
    pending_at = 0
    for number, raw in enumerate(lines, start=1):
        if heredoc:
            if raw.strip() == heredoc:
                heredoc = ""
            continue
        opener = re.search(r"<<-?'?([A-Za-z_][A-Za-z0-9_]*)'?\s*$", raw)
        if opener:
            heredoc = opener.group(1)
        name = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{", raw)
        if name:
            function = name.group(1)
        elif raw == "}":
            function = ""
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        # A trailing comment on a code line: drop it, but only when the
        # `#` is not inside a quoted string.
        if " #" in stripped and stripped.count("'") % 2 == 0 \
                and stripped.count('"') % 2 == 0:
            head, _, tail = stripped.partition(" #")
            if not re.search(r"[\"\']", tail):
                stripped = head.strip()
        if not stripped:
            continue
        if not pending:
            pending_at = number
        pending += (" " if pending else "") + stripped
        if stripped.endswith("\\") or stripped.endswith("|"):
            pending = pending.rstrip("\\").rstrip()
            continue
        statements.append((pending_at, function, pending))
        pending = ""
    if pending:
        statements.append((pending_at, function, pending))
    return statements


class TestGuardsDoNotPipeIntoGrepQ:
    """A quiet grep exits on its first match; the upstream then dies of
    SIGPIPE, and `set -o pipefail` reports the pipeline as FAILED. Any
    match on the far side of a pipe can therefore read as its opposite --
    a real trailer as "no trailer", a binary path as "no binary paths" --
    on a race decided by how much the upstream had written."""

    def test_no_quiet_grep_sits_on_the_far_side_of_a_pipe(self) -> None:
        """Kills DS-item-2: a line-at-a-time scan.

        The previous form asked whether ONE line held both a pipe and a
        `grep -q`, so writing the pipe as a trailing operator --
        `printf ... |` then `grep -qE ...` on the next line -- put the
        push-gate defect back with the suite green. It also matched the
        literal `grep -q`, so `grep -Fqx` and `grep --quiet` walked past
        it.
        """
        offenders = []
        for number, _function, statement in _script_statements():
            match = _QUIET_GREP.search(statement)
            if match and "|" in statement[: match.start()]:
                offenders.append(f"{number}: {statement}")
        assert not offenders, (
            "these pipe into a quiet grep, whose match reads as a failure "
            "under `set -o pipefail`:\n" + "\n".join(offenders)
        )

    def test_the_quiet_greps_are_exactly_where_they_are_expected(self) -> None:
        """Audit 3: the SET, not a count.

        A count is satisfied by a decorative fifth site and broken by a
        correct refactor. Naming the functions says what is actually
        being protected, and a new one has to be added here deliberately.
        """
        found = {
            function
            for _number, function, statement in _script_statements()
            if _QUIET_GREP.search(statement)
        }
        assert found == _QUIET_GREP_SITES, (
            f"the quiet greps have moved: found {sorted(found)}, "
            f"expected {sorted(_QUIET_GREP_SITES)}"
        )


class TestSweepCollectsItsOwnMarker:
    """A run killed between creating the sweep's marker and removing it
    must leave something a later sweep can collect -- otherwise the
    function that exists to clear litter is a source of it."""

    def test_a_marker_left_by_a_killed_sweep_is_collected_next_time(
        self, tmp_path: Path
    ) -> None:
        """Kills DS-L-a: naming the marker so the sweep's own glob can
        never match it.

        `find` and `rm` are stubbed in the first pass, which is what a
        kill between the mktemp and the rest of the function looks like
        from the next run's point of view. (A pass that gets as far as its
        own `find` already collects its own marker, since a file is not
        NEWER than itself -- so only a kill in that narrow window can
        strand one.)
        """
        cache = tmp_path / "cache-marker"
        cache.mkdir()
        sidecar = cache / "daily-sync-stash-state"
        sidecar.write_text("/repo\tdeadbeef\tconflicted\tnotes/a.md\n",
                           encoding="utf-8")

        first = _run_shell(
            f'STASH_STATE_FILE="{sidecar}"\n'
            "find() { :; }\n"
            "rm() { :; }\n"
            "sweep_orphaned_stash_state_temps\n",
            ("sweep_orphaned_stash_state_temps",),
        )
        assert first.returncode == 0, first.stderr
        stranded = [p for p in cache.iterdir() if p.name != sidecar.name]
        assert stranded, "the first pass left no marker, so nothing is being tested"

        # Dated back, so the second pass's marker is newer than it.
        for path in stranded:
            subprocess.run(["touch", "-d", "-1 hour", str(path)], check=True)
        second = _run_shell(
            f'STASH_STATE_FILE="{sidecar}"\nsweep_orphaned_stash_state_temps\n',
            ("sweep_orphaned_stash_state_temps",),
        )
        assert second.returncode == 0, second.stderr
        assert [p for p in cache.iterdir()] == [sidecar], (
            "the marker a killed sweep left behind is unreachable by any "
            "later sweep: " + str(list(cache.iterdir()))
        )


class TestUnjudgeableMergeDoesNotStopTheScan:
    """A merge this guard cannot measure decides the verdict only when
    nothing else in the range can."""

    def _repo(self, tmp_path: Path, name: str, records: int) -> tuple[Path, str]:
        """A repo whose published corpus holds ``records`` lines."""
        repo = tmp_path / name
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "memories").mkdir()
        (repo / "memories" / "memories.jsonl").write_text(
            "".join(f'{{"id": "r{n}"}}\n' for n in range(records)), encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "the published corpus", cwd=repo)
        origin = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
        _git("update-ref", "refs/remotes/origin/main", origin, cwd=repo)
        return repo, origin

    def _guard(self, repo: Path, logs: Path) -> subprocess.CompletedProcess[str]:
        """Call the published-shrink guard inside ``repo``."""
        return _run_shell(
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
            (
                "abort_on_published_shrink",
                "corpus_lines_at",
                "corpus_line_count",
                "has_bulk_rewrite_trailer",
            ),
        )

    def test_a_later_trailered_commit_still_owns_the_shrink(
        self, tmp_path: Path
    ) -> None:
        """Kills DS-L4: breaking at the first corpus-less merge.

        Two parentless commits holding nothing, a merge that RESTORES the
        corpus in full, and then an archive commit that shortens it and
        says so. The merge is unmeasurable but it took nothing away, and
        the commit that did is blameless -- so this publishes.
        """
        repo, _ = self._repo(tmp_path, "later-owner", 5)
        logs = tmp_path / "logs-later"
        logs.mkdir()
        empty = _git("hash-object", "-wt", "tree", "/dev/null", cwd=repo).stdout.strip()
        one = _git("commit-tree", empty, "-m", "side one", cwd=repo).stdout.strip()
        two = _git("commit-tree", empty, "-m", "side two", cwd=repo).stdout.strip()
        # The merge restores the corpus exactly as origin has it.
        tree = _git("write-tree", cwd=repo).stdout.strip()
        merge = _git("commit-tree", tree, "-p", one, "-p", two, "-m",
                     "Merge two strangers", cwd=repo).stdout.strip()
        _git("reset", "--quiet", "--hard", merge, cwd=repo)
        # …and a deliberate archive run shortens it afterwards.
        (repo / "memories" / "memories.jsonl").write_text(
            '{"id": "kept"}\n', encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m",
             "chore(memories): monthly archive\n\nRewrite-Class: bulk\n", cwd=repo)

        result = self._guard(repo, logs)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "REACHED-THE-PUSH" in result.stdout, result.stdout

    def test_an_unjudgeable_merge_still_decides_when_nothing_else_can(
        self, tmp_path: Path
    ) -> None:
        """The other side: with no commit to account for the shrink, the
        merge is the answer -- and is named as one, not reported as an
        unattributable mystery."""
        repo, _ = self._repo(tmp_path, "sole-cause", 5)
        logs = tmp_path / "logs-sole"
        logs.mkdir()
        empty = _git("hash-object", "-wt", "tree", "/dev/null", cwd=repo).stdout.strip()
        one = _git("commit-tree", empty, "-m", "side one", cwd=repo).stdout.strip()
        two = _git("commit-tree", empty, "-m", "side two", cwd=repo).stdout.strip()
        (repo / "memories" / "memories.jsonl").write_text(
            '{"id": "one record"}\n', encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        tree = _git("write-tree", cwd=repo).stdout.strip()
        merge = _git("commit-tree", tree, "-p", one, "-p", two, "-m",
                     "Merge two strangers", cwd=repo).stdout.strip()
        _git("reset", "--quiet", "--hard", merge, cwd=repo)

        result = self._guard(repo, logs)
        assert result.returncode == 4, result.stdout + result.stderr
        written = next(iter(logs.glob("daily-sync-shrink-*.log"))).read_text(
            encoding="utf-8"
        )
        assert "none of its parents holds the corpus" in written, written
        assert merge in written, written


class TestStatusRecordsAreRaw:
    """The snapshots this guard compares are matched against paths the
    stash's own diff reports with `-z`, i.e. raw. `git status --porcelain`
    without `-z` C-QUOTES anything holding a space, so the two never
    compared equal and such a path was silently unmeasurable."""

    _FUNCTIONS = ("status_records", "status_lines_for",
                  "stash_tracked_half_landed", "encode_record_path")

    def test_a_path_with_a_space_is_reported_unquoted(
        self, tmp_path: Path
    ) -> None:
        """Kills DS-L5: `git status --porcelain` without `-z`."""
        repo = tmp_path / "spaced"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "field notes.md").write_text("seed\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / "field notes.md").write_text("edited\n", encoding="utf-8")

        result = _run_shell(f'status_records "{repo}"\n', self._FUNCTIONS)
        assert result.returncode == 0, result.stderr
        assert result.stdout == " M\tfield notes.md\n", repr(result.stdout)
        assert '"' not in result.stdout, (
            "the path is C-quoted, so it can never equal the raw path the "
            "stash diff reports: " + repr(result.stdout)
        )

    def test_a_rename_with_a_space_is_measurable(self, tmp_path: Path) -> None:
        """The shape the audit named: a rename whose paths hold spaces.

        Both paths must appear, unquoted and one record each, or the
        tracked half of any entry touching them can never be called
        landed and its stash is kept for ever.
        """
        repo = tmp_path / "spaced-rename"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "old name.md").write_text("content that stays\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        _git("mv", "old name.md", "new name.md", cwd=repo)
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]
        _git("stash", "apply", sha, cwd=repo)

        records = _run_shell(f'status_records "{repo}"\n', self._FUNCTIONS)
        assert records.returncode == 0, records.stderr
        paths = [line.split("\t", 1)[1] for line in records.stdout.splitlines()]
        assert "new name.md" in paths, records.stdout
        assert "old name.md" in paths, records.stdout
        assert '"' not in records.stdout, records.stdout

        landed = _run_shell(
            'apply_before_status=""\n'
            f'apply_after_status="$(status_records "{repo}")"\n'
            f'if stash_tracked_half_landed "{repo}" "{sha}"; then\n'
            "  echo LANDED\nelse\n  echo NOT-LANDED\nfi\n",
            self._FUNCTIONS,
        )
        assert landed.returncode == 0, landed.stderr
        assert landed.stdout.strip() == "LANDED", landed.stdout

    def test_a_staged_rename_gives_each_path_its_own_record(
        self, tmp_path: Path
    ) -> None:
        """`-z` gives a rename its two paths as separate FIELDS rather
        than an `<old> -> <new>` line, so nothing downstream parses an
        arrow -- which is what the previous form did, on quoted text."""
        repo = tmp_path / "staged-rename"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "before.md").write_text("content that stays\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        _git("mv", "before.md", "after.md", cwd=repo)

        result = _run_shell(f'status_records "{repo}"\n', self._FUNCTIONS)
        assert result.returncode == 0, result.stderr
        rows = result.stdout.splitlines()
        assert [r.split("\t", 1)[1] for r in rows] == ["after.md", "before.md"], rows
        assert all(r.startswith("R") for r in rows), rows
        assert " -> " not in result.stdout, result.stdout


class TestSweepCollectsWhatTheWriterLeaves:
    """The writer's mktemp template and the sweep's glob are two halves of
    one contract, and nothing tied them together: renaming the template
    left every orphan uncollectable and the suite silent."""

    _FUNCTIONS = ("sweep_orphaned_stash_state_temps",)

    def test_the_writers_own_orphan_is_collected(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """Kills DS-L3: the writer's template and the sweep's glob
        drifting apart.

        The writer is driven for real -- a sidecar built, `mv` stubbed so
        it is never renamed into place, which is what a kill in that
        window leaves -- and the sweep then has to collect exactly what
        that writer left.
        """
        cache = tmp_path / "cache-writer"
        cache.mkdir()
        sidecar = cache / "daily-sync-stash-state"
        (repo / "tracked.txt").write_text("ours\n", encoding="utf-8")
        _git("stash", "push", "--quiet", "-m", "ours", cwd=repo)
        sha = _stash_shas(repo)[0]

        killed = _run_shell(
            _sidecar_preamble(repo, sidecar)
            + "\n"
            + "mv() { :; }\n"
            + f'record_conflicted_stash "{repo}" "{sha}" "notes/a.md"\n'
            + "write_stash_state\n",
            _SIDECAR_FUNCTIONS + ("record_partial_stash",),
        )
        assert killed.returncode == 0, killed.stderr
        orphans = [p for p in cache.iterdir() if p.name != sidecar.name]
        assert orphans, "the writer left nothing, so nothing is being swept"
        for path in orphans:
            subprocess.run(["touch", "-d", "-1 hour", str(path)], check=True)

        swept = _run_shell(
            f'STASH_STATE_FILE="{sidecar}"\nsweep_orphaned_stash_state_temps\n',
            self._FUNCTIONS,
        )
        assert swept.returncode == 0, swept.stderr
        left = [p.name for p in cache.iterdir()]
        assert left == [], (
            "the sweep cannot collect what the writer leaves behind: " + str(left)
        )

    def test_a_legacy_sweepmark_is_collected_too(self, tmp_path: Path) -> None:
        """Audit L7: before the marker was renamed it was created as
        `<sidecar>.sweepmark.XXXXXX`, which no glob of the current shape
        matches -- so any one an older build stranded would sit in
        ~/.cache for ever."""
        cache = tmp_path / "cache-legacy"
        cache.mkdir()
        sidecar = cache / "daily-sync-stash-state"
        sidecar.write_text("/repo\tdeadbeef\tconflicted\tnotes/a.md\n",
                           encoding="utf-8")
        legacy = cache / "daily-sync-stash-state.sweepmark.Ab12Cd"
        legacy.write_text("", encoding="utf-8")
        subprocess.run(["touch", "-d", "-1 hour", str(legacy)], check=True)

        result = _run_shell(
            f'STASH_STATE_FILE="{sidecar}"\nsweep_orphaned_stash_state_temps\n',
            self._FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        assert not legacy.exists(), (
            "a marker an older build stranded is uncollectable for ever"
        )
        assert sidecar.exists(), "the sweep took the sidecar"


class TestBinaryGateLineIsClassified:
    """The gate line that says an entry holds binary content is a claim
    about that entry's state, so a later run's word about the same stash
    has to be able to retire it -- and its own word has to retire what
    came before."""

    _FUNCTIONS = (
        "gate_line_class",
        "gate_sha_keys",
        "gate_claim_keys",
        "gate_subject_keys",
    )

    _BINARY_LINE = (
        "daily-sync STOPPED: parent-repo stash 0badc0de stash@{0} On main: "
        "daily-sync parent holds BINARY content, so this run could NOT tell "
        "whether its tracked changes reached the tree — it has kept the entry "
        "rather than guess."
    )
    _REFUSED_LINE = (
        "daily-sync STOPPED: applying parent-repo stash 0badc0de stash@{0} "
        "On main: daily-sync parent was REFUSED — git declined the merge and "
        "preserved the entry."
    )

    def test_a_binary_line_has_its_own_class(self) -> None:
        """Kills DS-L2: deleting the `*"BINARY content"*` arm, which left
        the line as `other` -- claiming nothing and protected from
        nothing, so it accumulated beside every later word about the same
        stash."""
        result = _run_shell(
            'gate_line_class "$PA_TEST_LINE"\n',
            self._FUNCTIONS,
            {"PA_TEST_LINE": self._BINARY_LINE},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "binary", result.stdout

    def test_it_retires_a_stale_refused_line_about_the_same_stash(self) -> None:
        """Two mutually exclusive descriptions of one entry must not stand
        side by side: this run's says the guard could not tell, the
        earlier one says git declined."""
        claims = _run_shell(
            'gate_claim_keys "$PA_TEST_LINE"\n',
            self._FUNCTIONS,
            {"PA_TEST_LINE": self._BINARY_LINE},
        )
        subjects = _run_shell(
            'gate_subject_keys "$PA_TEST_LINE"\n',
            self._FUNCTIONS,
            {"PA_TEST_LINE": self._REFUSED_LINE},
        )
        assert claims.returncode == 0, claims.stderr
        assert subjects.returncode == 0, subjects.stderr
        assert claims.stdout.strip() == "stash:0badc0de", claims.stdout
        assert subjects.stdout.strip() == "stash:0badc0de", subjects.stdout
        assert claims.stdout.strip() == subjects.stdout.strip(), (
            "a binary line cannot retire an earlier REFUSED line about the "
            "same entry"
        )


class TestUnjudgeableMergeBesideATrailer:
    """A trailer on one commit must not vouch for another commit that
    never said anything. The merge is dismissed only when a trailered
    commit's own transition spans the WHOLE observed drop."""

    def _repo(self, tmp_path: Path, name: str, records: int) -> Path:
        """A repo whose published corpus holds ``records`` lines."""
        repo = tmp_path / name
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "memories").mkdir()
        (repo / "memories" / "memories.jsonl").write_text(
            "".join(f'{{"id": "r{n}"}}\n' for n in range(records)), encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "the published corpus", cwd=repo)
        _git("update-ref", "refs/remotes/origin/main",
             _git("rev-parse", "HEAD", cwd=repo).stdout.strip(), cwd=repo)
        return repo

    def _merge_of_two_strangers(self, repo: Path, records: int) -> str:
        """A merge of two parentless corpus-less commits, holding
        ``records`` corpus lines of its own."""
        empty = _git("hash-object", "-wt", "tree", "/dev/null", cwd=repo).stdout.strip()
        one = _git("commit-tree", empty, "-m", "side one", cwd=repo).stdout.strip()
        two = _git("commit-tree", empty, "-m", "side two", cwd=repo).stdout.strip()
        (repo / "memories" / "memories.jsonl").write_text(
            "".join(f'{{"id": "r{n}"}}\n' for n in range(records)), encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        tree = _git("write-tree", cwd=repo).stdout.strip()
        merge = _git("commit-tree", tree, "-p", one, "-p", two, "-m",
                     "Merge two strangers", cwd=repo).stdout.strip()
        _git("reset", "--quiet", "--hard", merge, cwd=repo)
        return merge

    def _archive(self, repo: Path, records: int) -> None:
        """A trailered bulk rewrite down to ``records`` lines."""
        (repo / "memories" / "memories.jsonl").write_text(
            "".join(f'{{"id": "kept{n}"}}\n' for n in range(records)), encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m",
             "chore(memories): monthly archive\n\nRewrite-Class: bulk\n", cwd=repo)

    def _guard(self, repo: Path, logs: Path) -> subprocess.CompletedProcess[str]:
        """Call the published-shrink guard inside ``repo``."""
        return _run_shell(
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
            (
                "abort_on_published_shrink",
                "corpus_lines_at",
                "corpus_line_count",
                "has_bulk_rewrite_trailer",
            ),
        )

    def test_a_trailer_that_owns_only_part_of_the_shrink_does_not_excuse_it(
        self, tmp_path: Path
    ) -> None:
        """Kills the ordering defect: returning `allowed` before the
        unjudgeable merge is ever promoted.

        origin holds 5. The merge introduces a corpus of 4 -- one record
        gone, unmeasurably, because neither of its parents held one -- and
        a trailered archive commit then takes 4 to 2. The trailer accounts
        for that second drop and says nothing about the first.
        """
        repo = self._repo(tmp_path, "part-owner", 5)
        logs = tmp_path / "logs-part"
        logs.mkdir()
        merge = self._merge_of_two_strangers(repo, 4)
        self._archive(repo, 2)

        result = self._guard(repo, logs)
        assert result.returncode == 4, result.stdout + result.stderr
        assert "REACHED-THE-PUSH" not in result.stdout, result.stdout
        written = next(iter(logs.glob("daily-sync-shrink-*.log"))).read_text(
            encoding="utf-8"
        )
        assert "none of its parents holds the corpus" in written, written
        assert merge in written, written

    def test_a_trailer_that_owns_the_whole_shrink_still_publishes(
        self, tmp_path: Path
    ) -> None:
        """The other side. The merge restores the corpus in full, so
        origin's count and the archive commit's own parent count are the
        same, and its result is what HEAD holds -- there is no room left
        for the merge to have taken anything.
        """
        repo = self._repo(tmp_path, "whole-owner", 5)
        logs = tmp_path / "logs-whole"
        logs.mkdir()
        self._merge_of_two_strangers(repo, 5)
        self._archive(repo, 1)

        result = self._guard(repo, logs)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "REACHED-THE-PUSH" in result.stdout, result.stdout

    def test_every_unmeasurable_merge_is_recorded_even_when_allowed(
        self, tmp_path: Path
    ) -> None:
        """Recording is not fatal; being silent is. A run that publishes
        must still leave a trace that something in its range could not be
        measured."""
        repo = self._repo(tmp_path, "recorded", 5)
        logs = tmp_path / "logs-recorded"
        logs.mkdir()
        merge = self._merge_of_two_strangers(repo, 5)
        self._archive(repo, 1)

        result = self._guard(repo, logs)
        assert result.returncode == 0, result.stdout + result.stderr
        assert merge[:8] in result.stderr, (
            "an unmeasurable merge passed without a word: " + result.stderr
        )
        assert "cannot measure what it kept" in result.stderr, result.stderr


class TestRecordPathsSurviveNewlines:
    """These records are newline-joined into a shell variable, and a shell
    variable cannot hold a NUL -- so the separator has to be escaped
    rather than chosen."""

    _FUNCTIONS = ("status_records", "status_lines_for", "encode_record_path")

    def test_a_path_with_a_newline_stays_one_record(self, tmp_path: Path) -> None:
        """Kills DS-item-5: emitting the raw path.

        A newline in a path used to split one record into two, and the
        fragment after the break could be matched as though it were a
        path of its own.
        """
        repo = tmp_path / "newline-path"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        awkward = "notes/two\nlines.md"
        (repo / "notes").mkdir()
        (repo / awkward).write_text("seed\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / awkward).write_text("edited\n", encoding="utf-8")

        result = _run_shell(f'status_records "{repo}"\n', self._FUNCTIONS)
        assert result.returncode == 0, result.stderr
        rows = result.stdout.splitlines()
        assert len(rows) == 1, ("a path with a newline split into several "
                               f"records: {rows}")
        assert rows[0] == " M\tnotes/two\\nlines.md", repr(rows[0])

    def test_a_fragment_cannot_impersonate_a_path(self, tmp_path: Path) -> None:
        """The consequence: the tail of a split path must not answer to a
        query for a real one."""
        repo = tmp_path / "impersonate"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "notes").mkdir()
        # The tail of this path is exactly the name of a real file.
        (repo / "notes" / "decoy\nlines.md").write_text("seed\n", encoding="utf-8")
        (repo / "lines.md").write_text("a real file, untouched\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)
        (repo / "notes" / "decoy\nlines.md").write_text("edited\n", encoding="utf-8")

        result = _run_shell(
            f'records="$(status_records "{repo}")"\n'
            'status_lines_for "$records" "lines.md"\n',
            self._FUNCTIONS,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "", (
            "the tail of a split path answered for a file nothing touched: "
            + repr(result.stdout)
        )

    def test_a_literal_backslash_n_is_not_a_newline(self, tmp_path: Path) -> None:
        """Backslash is escaped first, or `a\\nb` and a real newline would
        encode to the same record and match each other."""
        result = _run_shell(
            'encode_record_path "$PA_TEST_LITERAL"\n'
            'printf "|"\n'
            'encode_record_path "$PA_TEST_NEWLINE"\n',
            self._FUNCTIONS,
            {"PA_TEST_LITERAL": "notes/a\\nb.md", "PA_TEST_NEWLINE": "notes/a\nb.md"},
        )
        assert result.returncode == 0, result.stderr
        literal, newline = result.stdout.split("|")
        assert literal != newline, (
            "a literal backslash-n and a real newline encode alike: "
            + repr(result.stdout)
        )


class TestRenderSyncGateSupersession:
    """The gate keys are exercised elsewhere in isolation; nothing drove
    render_sync_gate itself, so swapping which side gets gate_claim_keys
    and which gets gate_subject_keys reintroduced the tenth re-audit's M2
    with the suite green."""

    _FUNCTIONS = (
        "render_sync_gate",
        "gate_line_class",
        "gate_sha_keys",
        "gate_claim_keys",
        "gate_subject_keys",
    )

    #: What `fail` leaves behind: a free-text line that NAMES a stash but
    #: makes no classifiable claim about it.
    _STALE_OTHER = (
        "daily-sync FAILED and will keep failing until this is resolved: "
        "parent repo: applying stash 0badc0de was refused"
    )
    _BINARY = (
        "daily-sync STOPPED: parent-repo stash 0badc0de stash@{0} On main: "
        "daily-sync parent holds BINARY content, so this run could NOT tell "
        "whether its tracked changes reached the tree."
    )
    _BLOCKED = (
        "daily-sync could not apply 1 of its own stash(es) because the index "
        "was ALREADY unmerged: data submodule: 0badc0de stash@{0} On main: "
        "daily-sync branch-switch."
    )
    _LISTING = (
        "daily-sync STOPPED: /repo (data submodule) has unmerged paths from "
        "an operation this run cannot identify — UU notes/a.md. Do NOT touch "
        "any stash entry; the entries on the stack right now are: "
        "0badc0de stash@{0} On main: daily-sync branch-switch"
    )

    def _render(self, tmp_path: Path, previous: str, ours: list[str]) -> list[str]:
        """Run render_sync_gate over a seeded gate file and read it back."""
        gate = tmp_path / f"gate-{abs(hash((previous, tuple(ours)))) % 10**8}"
        gate.write_text(f"1\n{previous}\n", encoding="utf-8")
        body = "\n".join(
            [
                f'SYNC_GATE="{gate}"',
                "DRY_RUN=0",
                "sync_run_completed=0",
                "sync_gate_details=()",
            ]
            + [f'sync_gate_details+=("{line}")' for line in ours]
            + ["render_sync_gate"]
        )
        result = _run_shell(body, self._FUNCTIONS)
        assert result.returncode == 0, result.stdout + result.stderr
        lines = gate.read_text(encoding="utf-8").splitlines()
        assert int(lines[0]) == len(lines) - 1, lines
        return lines[1:]

    def test_a_binary_line_retires_a_stale_line_about_the_same_stash(
        self, tmp_path: Path
    ) -> None:
        """Kills DS-item-4: swapping gate_claim_keys and gate_subject_keys.

        This run has a classifiable claim about 0badc0de; the previous
        run left an unclassifiable line that merely names it. The claim
        wins. Swap the two calls and the previous line -- read as a claim,
        which it is not -- keeps a key of its own and survives, so two
        descriptions of one entry stand side by side again.
        """
        rendered = self._render(tmp_path, self._STALE_OTHER, [self._BINARY])
        assert self._BINARY in rendered, rendered
        assert self._STALE_OTHER not in rendered, (
            "a stale free-text line about the same stash outlived this "
            "run's word on it: " + str(rendered)
        )

    def test_a_listing_line_never_erases_a_specific_claim(
        self, tmp_path: Path
    ) -> None:
        """The other direction, and the tenth re-audit's finding: a run
        that can attribute nothing LISTS every entry on the stack, and
        that listing must not retire what an earlier run knew about one
        of them."""
        rendered = self._render(tmp_path, self._BLOCKED, [self._LISTING])
        assert self._BLOCKED in rendered, (
            "a line that could attribute nothing erased a specific claim: "
            + str(rendered)
        )
        assert self._LISTING in rendered, rendered

    def test_a_completed_run_replaces_rather_than_appends(
        self, tmp_path: Path
    ) -> None:
        """And the surrounding contract the supersession sits inside: a
        run that finished everything speaks for the current state."""
        gate = tmp_path / "gate-completed"
        gate.write_text(f"1\n{self._BLOCKED}\n", encoding="utf-8")
        result = _run_shell(
            "\n".join(
                [
                    f'SYNC_GATE="{gate}"',
                    "DRY_RUN=0",
                    "sync_run_completed=1",
                    "sync_gate_details=()",
                    f'sync_gate_details+=("{self._BINARY}")',
                    "render_sync_gate",
                ]
            ),
            self._FUNCTIONS,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        lines = gate.read_text(encoding="utf-8").splitlines()
        assert lines == ["1", self._BINARY], lines


class TestSpanRuleNeedsBothEnds:
    """The span rule asks two things of a trailered commit: that it
    started no lower than origin, and that it ended no higher than HEAD.
    Only the first was ever tested."""

    def _repo(self, tmp_path: Path, name: str, records: int) -> Path:
        """A repo whose published corpus holds ``records`` lines."""
        repo = tmp_path / name
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        (repo / "memories").mkdir()
        (repo / "memories" / "memories.jsonl").write_text(
            "".join(f'{{"id": "r{n}"}}\n' for n in range(records)), encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "the published corpus", cwd=repo)
        _git("update-ref", "refs/remotes/origin/main",
             _git("rev-parse", "HEAD", cwd=repo).stdout.strip(), cwd=repo)
        return repo

    def _archive(self, repo: Path, records: int) -> None:
        """A trailered bulk rewrite down to ``records`` lines."""
        (repo / "memories").mkdir(exist_ok=True)
        (repo / "memories" / "memories.jsonl").write_text(
            "".join(f'{{"id": "kept{n}"}}\n' for n in range(records)), encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m",
             "chore(memories): monthly archive\n\nRewrite-Class: bulk\n", cwd=repo)

    def _delete_corpus(self, repo: Path) -> None:
        """A trailered commit that removes the corpus altogether, so
        everything after it has a parent that holds none."""
        _git("rm", "--quiet", "--", "memories/memories.jsonl", cwd=repo)
        _git("commit", "--quiet", "-m",
             "chore(memories): retire the corpus\n\nRewrite-Class: bulk\n", cwd=repo)

    def _merge_onto_head(self, repo: Path, records: int) -> str:
        """A merge of HEAD with a parentless stranger, holding ``records``
        corpus lines of its own.

        Unmeasurable only because NEITHER parent holds a corpus -- which
        is why the caller deletes it first. The merge stays on HEAD's
        history, so the commits before it are in the range the guard
        scans; a merge built off to one side would take them out of it,
        and the mutant this fixture exists for would survive.
        """
        head = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
        empty = _git("hash-object", "-wt", "tree", "/dev/null", cwd=repo).stdout.strip()
        stranger = _git("commit-tree", empty, "-m", "a stranger",
                        cwd=repo).stdout.strip()
        (repo / "memories").mkdir(exist_ok=True)
        (repo / "memories" / "memories.jsonl").write_text(
            "".join(f'{{"id": "m{n}"}}\n' for n in range(records)), encoding="utf-8"
        )
        _git("add", "-A", cwd=repo)
        tree = _git("write-tree", cwd=repo).stdout.strip()
        merge = _git("commit-tree", tree, "-p", head, "-p", stranger, "-m",
                     "Merge a stranger", cwd=repo).stdout.strip()
        _git("reset", "--quiet", "--hard", merge, cwd=repo)
        return merge

    def _guard(self, repo: Path, logs: Path) -> subprocess.CompletedProcess[str]:
        """Call the published-shrink guard inside ``repo``."""
        return _run_shell(
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
            (
                "abort_on_published_shrink",
                "corpus_lines_at",
                "corpus_line_count",
                "has_bulk_rewrite_trailer",
            ),
        )

    def test_a_trailer_that_started_high_but_ended_high_excuses_nothing(
        self, tmp_path: Path
    ) -> None:
        """Kills the SECOND condition: mutating `lines_after` to
        `lines_before` on the `-le` test.

        origin holds 5. A trailered rewrite takes 5 to 4 -- it started
        exactly where origin is, so the first condition passes -- and an
        unmeasurable merge then holds 2. The trailer said nothing about
        the drop from 4 to 2, and with only the first condition checked
        the run published it.
        """
        repo = self._repo(tmp_path, "started-high", 5)
        logs = tmp_path / "logs-started-high"
        logs.mkdir()
        self._archive(repo, 4)
        # Retiring the corpus is what leaves the merge below with no
        # parent holding one, while keeping the whole chain on HEAD.
        self._delete_corpus(repo)
        merge = self._merge_onto_head(repo, 2)

        result = self._guard(repo, logs)
        assert result.returncode == 4, result.stdout + result.stderr
        assert "REACHED-THE-PUSH" not in result.stdout, result.stdout
        written = next(iter(logs.glob("daily-sync-shrink-*.log"))).read_text(
            encoding="utf-8"
        )
        assert "none of its parents holds the corpus" in written, written
        assert merge in written, written

    def test_a_trailer_that_spans_both_ends_still_publishes(
        self, tmp_path: Path
    ) -> None:
        """The rule must still let a real archive run out: this one starts
        at origin's count and ends at HEAD's, so nothing is left over for
        the merge to have taken."""
        repo = self._repo(tmp_path, "spans-both", 5)
        logs = tmp_path / "logs-spans-both"
        logs.mkdir()
        self._delete_corpus(repo)
        self._merge_onto_head(repo, 5)
        self._archive(repo, 1)

        result = self._guard(repo, logs)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "REACHED-THE-PUSH" in result.stdout, result.stdout
