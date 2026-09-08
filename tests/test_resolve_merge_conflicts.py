"""
Tests for ``scripts/resolve-merge-conflicts.py``.

Audit S6 (Lens B, C2): the append-safe resolver — the thing that decides
what happens to memory records when two machines conflict — had zero
tests. Rewriting ``strip_conflict_markers`` to keep only the *ours* side,
silently deleting the other machine's records on every cross-machine
conflict, passed the entire suite.

The conflict fixtures here are built by a real ``git merge`` wherever the
assertion is about behaviour under real markers, because no fixture
anywhere in the suite previously contained one. The unit tests use
hand-written markers for the edge cases git will not produce on demand.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOLVER = REPO_ROOT / "scripts" / "resolve-merge-conflicts.py"


def _load_resolver():
    """Import the hyphenated script as a module for unit testing."""
    spec = importlib.util.spec_from_file_location("resolve_merge_conflicts", RESOLVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before executing: @dataclass resolves annotations through
    # sys.modules[cls.__module__], which is None for an unregistered module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rmc = _load_resolver()


def _run_resolver(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the resolver as the sync does, and capture everything."""
    return subprocess.run(
        [sys.executable, str(RESOLVER), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run git with a deterministic identity in a throwaway repo."""
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
        ["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True, check=False
    )


def _record(record_id: str) -> str:
    """One JSONL memory record, as the extraction hook writes them."""
    return json.dumps({"id": record_id, "category": "decision", "content": record_id})


@pytest.fixture()
def real_conflict(tmp_path: Path) -> Path:
    """
    Produce a genuinely git-generated conflict in ``memories.jsonl``.

    Two branches append a different record to the same end-of-file
    position, exactly as two machines' extraction hooks do; the merge
    leaves the file with real conflict markers.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "--quiet", "--initial-branch=main", cwd=repo)
    corpus = repo / "memories.jsonl"
    corpus.write_text(_record("shared-1") + "\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "--quiet", "-m", "seed", cwd=repo)

    _git("checkout", "--quiet", "-b", "other", cwd=repo)
    corpus.write_text(
        _record("shared-1") + "\n" + _record("from-zbook") + "\n", encoding="utf-8"
    )
    _git("commit", "--quiet", "-am", "zbook append", cwd=repo)

    _git("checkout", "--quiet", "main", cwd=repo)
    corpus.write_text(
        _record("shared-1") + "\n" + _record("from-amd-tower") + "\n", encoding="utf-8"
    )
    _git("commit", "--quiet", "-am", "amd-tower append", cwd=repo)

    merge = _git("merge", "other", cwd=repo)
    assert merge.returncode != 0, "expected a conflict; git merged cleanly"
    assert "<<<<<<<" in corpus.read_text(encoding="utf-8")
    return corpus


@pytest.fixture()
def diff3_conflict(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    """
    A git-generated conflict under ``merge.conflictStyle`` diff3/zdiff3.

    Both machines append, and both delete the same pre-existing record, so
    the merge base carries a record neither side kept — exactly the line
    that must NOT be resurrected by the union.
    """
    style = getattr(request, "param", "diff3")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "--quiet", "--initial-branch=main", cwd=repo)
    _git("config", "merge.conflictStyle", style, cwd=repo)
    corpus = repo / "memories.jsonl"
    corpus.write_text(
        _record("shared-1") + "\n" + _record("deleted-on-both") + "\n", encoding="utf-8"
    )
    _git("add", "-A", cwd=repo)
    _git("commit", "--quiet", "-m", "seed", cwd=repo)

    _git("checkout", "--quiet", "-b", "other", cwd=repo)
    corpus.write_text(
        _record("shared-1") + "\n" + _record("from-zbook") + "\n", encoding="utf-8"
    )
    _git("commit", "--quiet", "-am", "zbook append", cwd=repo)

    _git("checkout", "--quiet", "main", cwd=repo)
    corpus.write_text(
        _record("shared-1") + "\n" + _record("from-amd-tower") + "\n", encoding="utf-8"
    )
    _git("commit", "--quiet", "-am", "amd-tower append", cwd=repo)

    merge = _git("merge", "other", cwd=repo)
    assert merge.returncode != 0, "expected a conflict; git merged cleanly"
    text = corpus.read_text(encoding="utf-8")
    assert "|||||||" in text, f"expected a {style} base section, got:\n{text}"
    return corpus


# ============================================================================
# diff3 / zdiff3 conflict style (audit C1, third re-audit)
# ============================================================================


class TestDiff3ConflictStyle:
    """With ``merge.conflictStyle`` set to diff3 or zdiff3, git emits a
    fourth marker — ``||||||| <ref>`` — and a whole merge-base section.
    Recognising only the three classic markers left that line in the file
    as "malformed but non-empty" and unioned the base back in."""

    @pytest.mark.parametrize("diff3_conflict", ["diff3", "zdiff3"], indirect=True)
    def test_base_marker_is_recognised_and_removed(self, diff3_conflict: Path) -> None:
        """The marker line must never survive into the corpus."""
        result = _run_resolver(str(diff3_conflict))
        assert result.returncode == 0, result.stderr
        text = diff3_conflict.read_text(encoding="utf-8")
        assert "|||||||" not in text, text
        for line in text.splitlines():
            json.loads(line)

    @pytest.mark.parametrize("diff3_conflict", ["diff3", "zdiff3"], indirect=True)
    def test_the_base_section_is_not_resurrected(self, diff3_conflict: Path) -> None:
        """A record both sides deleted stays deleted. Unioning the base
        section back in would bring it back on every conflict."""
        assert "deleted-on-both" in diff3_conflict.read_text(encoding="utf-8")
        assert _run_resolver(str(diff3_conflict)).returncode == 0
        text = diff3_conflict.read_text(encoding="utf-8")
        assert "deleted-on-both" not in text, (
            "the merge base was unioned back in, resurrecting a deleted record"
        )
        # Both sides' appends still survive: this is still a union.
        assert "from-amd-tower" in text
        assert "from-zbook" in text

    def test_a_base_holding_a_separator_line_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Audit M3 (sixth re-audit): two separators, no guessing.

        A diff3 base whose own content holds a line reading `=======`
        leaves the block with two separator candidates. Taking the first
        ends the base early and resurrects the records after it; taking
        the last eats a THEIRS line that is literally `=======`, which a
        tag vocabulary can legitimately hold. Both lose data silently, so
        the file goes to a human. Built by a real diff3 merge.
        """
        repo = tmp_path / "repo"
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch=main", cwd=repo)
        _git("config", "merge.conflictStyle", "diff3", cwd=repo)
        vocab = repo / "tag-vocabulary.txt"
        vocab.write_text("keep-me\n=======\ndeleted-on-both\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "--quiet", "-m", "seed", cwd=repo)

        _git("checkout", "--quiet", "-b", "other", cwd=repo)
        vocab.write_text("keep-me\nfrom-zbook\n", encoding="utf-8")
        _git("commit", "--quiet", "-am", "zbook", cwd=repo)

        _git("checkout", "--quiet", "main", cwd=repo)
        vocab.write_text("keep-me\nfrom-amd-tower\n", encoding="utf-8")
        _git("commit", "--quiet", "-am", "amd-tower", cwd=repo)

        assert _git("merge", "other", cwd=repo).returncode != 0
        conflicted = vocab.read_text(encoding="utf-8")
        assert "|||||||" in conflicted, conflicted

        result = _run_resolver(str(vocab))
        assert result.returncode == 3, result.stdout + result.stderr
        assert "which one divides the two sides" in result.stderr, result.stderr
        assert vocab.read_text(encoding="utf-8") == conflicted, "the file was rewritten"

    def test_the_base_section_starts_at_its_first_marker(
        self, tmp_path: Path
    ) -> None:
        """Every base marker in a block belongs to the base.

        Starting at the last would leave an earlier `||||||| ` line and
        its section in the union — a marker published into the corpus.
        """
        target = tmp_path / "memories.jsonl"
        target.write_text(
            "<<<<<<< HEAD\n" + _record("ours") + "\n"
            "||||||| first base\n" + _record("base-one") + "\n"
            "||||||| second base\n" + _record("base-two") + "\n"
            "=======\n" + _record("theirs") + "\n>>>>>>> x\n",
            encoding="utf-8",
        )
        assert _run_resolver(str(target)).returncode == 0
        text = target.read_text(encoding="utf-8")
        assert "|||||||" not in text, text
        assert "base-one" not in text and "base-two" not in text, text
        assert '"ours"' in text and '"theirs"' in text

    def test_the_base_marker_is_always_labelled(self) -> None:
        """git never emits a bare `|||||||`.

        Measured against git across a plain merge, both diff3 styles, and
        a stash pop: an add/add conflict, where neither side had the file
        at all, still gets `||||||| <sha>`, and a stash pop gets
        `||||||| Stash base`. There is no bare form to match, and matching
        one anyway is what let a stray pipe run swallow a file's tail
        (audit C1, fourth re-audit).
        """
        assert rmc.is_conflict_marker("||||||| parent of 1a2b3c4 (seed)")
        assert rmc.is_conflict_marker("||||||| Stash base")
        assert not rmc.is_conflict_marker("|||||||")

    def test_base_marker_lookalikes_in_content_are_safe(self) -> None:
        """Exact-line matching, as for the other three markers."""
        embedded = json.dumps({"id": "x", "content": "a ||||||| pipe run"})
        assert not rmc.has_conflict_markers([embedded])


# ============================================================================
# Lines outside a conflict block are never touched (audit C1, fourth re-audit)
# ============================================================================


class TestStrayMarkersOutsideBlocks:
    """A marker-shaped line with no ``<<<<<<< `` above it is not a
    conflict. It is content that happens to look like one, or a file a
    human is part-way through repairing — and this script cannot tell
    which side of a boundary that is not there each line belongs to.

    The bug: any ``|||||||`` line opened a "base section" that swallowed
    everything after it to the next marker or to end of file. A
    conflict-free tag vocabulary lost its tail, and the script reported
    "resolved 0 conflict block(s)" and exit 0 while doing it — under a
    gate that had told the operator to run exactly this resolver.
    """

    @pytest.mark.parametrize("name", ["memories.jsonl", "tag-vocabulary.txt"])
    @pytest.mark.parametrize(
        ("stray", "expected_rc"),
        [
            ("|||||||", 0),  # git never emits this: it is content
            ("||||||| looks like a base", 3),
            ("=======", 3),
            (">>>>>>> a branch", 3),
        ],
    )
    def test_a_stray_marker_leaves_the_file_byte_identical(
        self, tmp_path: Path, name: str, stray: str, expected_rc: int
    ) -> None:
        """Kept verbatim, with everything after it, and not even the
        trailing newline changed — the file is written without one.

        A marker-shaped stray is refused (exit 3) so the sync's guard and
        this script agree; one that only looks like a marker to a careless
        eye is simply content.
        """
        target = tmp_path / name
        original = (
            "first line\n"
            + stray + "\n"
            + "line after the stray marker\n"
            + "last line with no trailing newline"
        )
        target.write_bytes(original.encode("utf-8"))

        result = _run_resolver(str(target))
        assert result.returncode == expected_rc, result.stderr
        assert target.read_bytes() == original.encode("utf-8"), (
            "the resolver rewrote a file that holds no conflict block"
        )

    def test_a_stray_marker_is_reported_to_the_operator(
        self, tmp_path: Path
    ) -> None:
        """By LINE NUMBER: the operator has to edit those lines by hand,
        and the sync's gate quotes this at them."""
        target = tmp_path / "memories.jsonl"
        target.write_text(
            '{"id": "a"}\n||||||| looks like a base\n{"id": "b"}\n', encoding="utf-8"
        )
        result = _run_resolver("--quiet-if-clean", str(target))
        assert result.returncode == 3
        assert "line 2" in result.stderr
        assert "outside any conflict block" in result.stderr
        assert "needs a human" in result.stderr
        # The offending line is QUOTED, so trailing spaces and the exact
        # text are visible to whoever has to edit it.
        assert "'||||||| looks like a base'" in result.stderr, result.stderr

    def test_a_stray_after_a_completed_block_is_still_reported(
        self, tmp_path: Path
    ) -> None:
        """The parser must close the block at its closer.

        Leaving `in_block` set means everything after the first block
        looks like it is inside one, so a stray marker below it is never
        reported and the file is rewritten as if it were sound.
        """
        target = tmp_path / "memories.jsonl"
        body = (
            "<<<<<<< HEAD\n" + _record("a") + "\n=======\n"
            + _record("b") + "\n>>>>>>> x\n"
            + "=======\n" + _record("c") + "\n"
        )
        target.write_text(body, encoding="utf-8")

        result = _run_resolver(str(target))
        assert result.returncode == 3, result.stdout + result.stderr
        assert "line 6" in result.stderr, result.stderr
        assert target.read_text(encoding="utf-8") == body, "the file was rewritten"

    def test_a_stray_marker_below_a_real_block_survives_the_resolution(
        self, tmp_path: Path
    ) -> None:
        """The block is resolved; the line beneath it is not the block's."""
        target = tmp_path / "memories.jsonl"
        target.write_text(
            "<<<<<<< HEAD\n"
            + _record("ours") + "\n"
            + "=======\n"
            + _record("theirs") + "\n"
            + ">>>>>>> other\n"
            + "|||||||\n"
            + _record("after") + "\n",
            encoding="utf-8",
        )
        assert _run_resolver(str(target)).returncode == 0
        lines = target.read_text(encoding="utf-8").splitlines()
        assert "|||||||" in lines, "a line outside the block was dropped"
        assert any('"after"' in ln for ln in lines), "the file's tail was swallowed"
        assert any('"ours"' in ln for ln in lines)
        assert any('"theirs"' in ln for ln in lines)


# ============================================================================
# Unbalanced structure, and the shared predicate (audit C3 / C2)
# ============================================================================


class TestUnbalancedStructure:
    """When the block structure does not balance there is no way to know
    which side a line belongs to. Nothing is written and the exit code
    says so, rather than a rewrite that leaves live markers behind."""

    @pytest.mark.parametrize(
        ("body", "expected_in_stderr"),
        [
            (
                # Two openers before a closer: rewritten into a file that
                # still held a live `=======` and `>>>>>>> `, and reported
                # as "resolved 2 blocks", exit 0 (audit C3).
                "<<<<<<< HEAD\na\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> x\n",
                "opener inside the block opened at line 1",
            ),
            ("<<<<<<< HEAD\na\n=======\nb\n", "never closed"),
            ("a\n>>>>>>> x\n", "closer with no opener"),
            ("a\n=======\nb\n", "outside any conflict block"),
            ("<<<<<<< HEAD\na\n>>>>>>> x\n", "no '=======' separator"),
        ],
    )
    def test_nothing_is_written_and_the_exit_code_says_so(
        self, tmp_path: Path, body: str, expected_in_stderr: str
    ) -> None:
        """Exit 3, file untouched, and the reason names a line."""
        target = tmp_path / "memories.jsonl"
        target.write_text(body, encoding="utf-8")
        result = _run_resolver(str(target))
        assert result.returncode == 3, result.stdout + result.stderr
        assert expected_in_stderr in result.stderr, result.stderr
        assert target.read_text(encoding="utf-8") == body, "the file was rewritten"

    def test_a_resolvable_file_is_still_resolved(self, tmp_path: Path) -> None:
        """The refusal must not swallow the ordinary case."""
        target = tmp_path / "memories.jsonl"
        target.write_text(
            "<<<<<<< HEAD\n" + _record("a") + "\n=======\n"
            + _record("b") + "\n>>>>>>> x\n",
            encoding="utf-8",
        )
        assert _run_resolver(str(target)).returncode == 0
        text = target.read_text(encoding="utf-8")
        assert '"a"' in text and '"b"' in text
        assert "<<<<<<<" not in text and "=======" not in text


class TestCheckMode:
    """`--check` is the predicate daily-sync.sh's guard calls, so the two
    cannot disagree about what a conflict is (audit C2)."""

    def test_clean_file_is_zero_and_silent(self, tmp_path: Path) -> None:
        """Nothing marker-shaped anywhere."""
        target = tmp_path / "memories.jsonl"
        target.write_text(_record("a") + "\n", encoding="utf-8")
        result = _run_resolver("--check", str(target))
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_resolvable_conflict_is_one(self, tmp_path: Path) -> None:
        """A well-formed block: the sync may run the resolver on it."""
        target = tmp_path / "memories.jsonl"
        target.write_text(
            "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> x\n", encoding="utf-8"
        )
        result = _run_resolver("--check", str(target))
        assert result.returncode == 1
        assert target.read_text(encoding="utf-8").startswith("<<<<<<<"), "check wrote"

    @pytest.mark.parametrize(
        "body",
        [
            "a\n=======\nb\n",
            "a\n||||||| base\nb\n",
            "a\n>>>>>>> x\n",
            "<<<<<<< HEAD\na\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> x\n",
        ],
    )
    def test_needs_a_human_is_three(self, tmp_path: Path, body: str) -> None:
        """Every shape the resolver refuses is reported as manual."""
        target = tmp_path / "memories.jsonl"
        target.write_text(body, encoding="utf-8")
        result = _run_resolver("--check", str(target))
        assert result.returncode == 3, result.stdout + result.stderr
        # One tab-separated record per problem: path, line number, text.
        for record in result.stdout.splitlines():
            path_field, number, text = record.split("\t")
            assert path_field == str(target)
            assert number.isdigit()
            assert text

    def test_a_missing_file_has_its_own_code(self, tmp_path: Path) -> None:
        """Audit M4 (sixth re-audit): a vanished file is not a corpus
        verdict. Sharing a code with "needs a human" made the guard advise
        hand-editing a file that is not there."""
        result = _run_resolver("--check", str(tmp_path / "gone.jsonl"))
        assert result.returncode == 2, result.stdout + result.stderr
        assert "no such file" in result.stderr
        assert result.stdout.strip() == "", "a missing file produced a corpus record"

    def test_an_undecodable_byte_is_a_checker_failure_not_a_verdict(
        self, tmp_path: Path
    ) -> None:
        """Audit C2 (sixth re-audit): an uncaught exception exited 1, which
        the guard reads as "resolvable" — so the sync gated a traceback as
        marker-shaped lines and parsed its lines as file paths.

        The check now reads tolerantly, so one stray byte still yields a
        verdict; whatever else goes wrong is reported as CHECKER FAILED
        with its reason, on a code no corpus verdict uses.
        """
        target = tmp_path / "memories.jsonl"
        target.write_bytes(b'{"id": "a"}\n\xff\xfe not utf-8\n')
        result = _run_resolver("--check", str(target))
        assert result.returncode == 0, result.stdout + result.stderr

        # And a genuine failure — an unreadable file — is code 4 with a reason.
        target.chmod(0o000)
        try:
            failed = _run_resolver("--check", str(target))
        finally:
            target.chmod(0o600)
        assert failed.returncode == 4, failed.stdout + failed.stderr
        assert "checker failed" in failed.stderr
        assert "PermissionError" in failed.stderr
        assert failed.stdout.strip() == "", "a failure produced a corpus record"

    def test_check_and_resolve_agree_on_every_shape(self, tmp_path: Path) -> None:
        """The invariant: one predicate. What --check calls resolvable,
        resolve resolves; what it calls manual, resolve refuses; what it
        calls clean, resolve leaves alone."""
        shapes = {
            "clean": "a\nb\n",
            "resolvable": "<<<<<<< H\na\n=======\nb\n>>>>>>> x\n",
            "stray-separator": "a\n=======\nb\n",
            "stray-closer": "a\n>>>>>>> x\n",
            "stray-base": "a\n||||||| b\nc\n",
            "nested": "<<<<<<< H\na\n<<<<<<< H\nb\n=======\nc\n>>>>>>> x\n",
            "unclosed": "<<<<<<< H\na\n=======\nb\n",
            "no-separator": "<<<<<<< H\na\n>>>>>>> x\n",
            "pipe-content": "a\n|||||||\nb\n",
        }
        for name, body in shapes.items():
            target = tmp_path / f"{name}-memories.jsonl"
            target.write_text(body, encoding="utf-8")
            checked = _run_resolver("--check", str(target)).returncode
            resolved = _run_resolver("--quiet-if-clean", str(target)).returncode
            expected = {0: 0, 1: 0, 3: 3}[checked]
            assert resolved == expected, (
                f"{name}: --check said {checked} but resolve exited {resolved}"
            )


# ============================================================================
# The union property — neither machine's records may be dropped
# ============================================================================


class TestUnionOfBothSides:
    """The resolution of an append-only conflict is the set union. Any
    implementation that keeps one side is silent cross-machine data
    loss, and is what the whole script exists to prevent."""

    def test_both_machines_records_survive(self, real_conflict: Path) -> None:
        """Kills RMC-M1: keeping only the ours-side passed the old suite."""
        result = _run_resolver(str(real_conflict))
        assert result.returncode == 0, result.stderr
        text = real_conflict.read_text(encoding="utf-8")
        assert "from-amd-tower" in text
        assert "from-zbook" in text, "the other machine's record was discarded"
        assert "shared-1" in text

    def test_no_markers_survive_the_resolution(self, real_conflict: Path) -> None:
        """The file must be valid JSONL afterwards, not half-merged."""
        assert _run_resolver(str(real_conflict)).returncode == 0
        lines = real_conflict.read_text(encoding="utf-8").splitlines()
        assert not any(
            ln.startswith(("<<<<<<< ", ">>>>>>> ")) or ln == "=======" for ln in lines
        )
        for line in lines:
            json.loads(line)

    def test_union_is_never_shorter_than_either_side(self, real_conflict: Path) -> None:
        """"Never deletes a line — only deduplicates" (module docstring)."""
        before = real_conflict.read_text(encoding="utf-8").splitlines()
        ours = [ln for ln in before if "from-amd-tower" in ln]
        theirs = [ln for ln in before if "from-zbook" in ln]
        assert _run_resolver(str(real_conflict)).returncode == 0
        after = real_conflict.read_text(encoding="utf-8").splitlines()
        assert len(after) >= max(len(ours), len(theirs))
        assert len(after) == 3

    def test_records_are_deduplicated_by_id(self, tmp_path: Path) -> None:
        """The same record appended on both sides collapses to one."""
        corpus = tmp_path / "memories.jsonl"
        corpus.write_text(
            "<<<<<<< HEAD\n"
            + _record("dup") + "\n"
            + _record("only-ours") + "\n"
            + "=======\n"
            + _record("dup") + "\n"
            + _record("only-theirs") + "\n"
            + ">>>>>>> other\n",
            encoding="utf-8",
        )
        assert _run_resolver(str(corpus)).returncode == 0
        lines = corpus.read_text(encoding="utf-8").splitlines()
        assert sum(1 for ln in lines if '"dup"' in ln) == 1
        assert len(lines) == 3

    def test_tag_vocabulary_dedups_by_line(self, tmp_path: Path) -> None:
        """Non-JSONL files take the exact-line path."""
        vocab = tmp_path / "tag-vocabulary.txt"
        vocab.write_text(
            "<<<<<<< HEAD\nshared\nours-only\n=======\nshared\ntheirs-only\n>>>>>>> other\n",
            encoding="utf-8",
        )
        assert _run_resolver(str(vocab)).returncode == 0
        assert vocab.read_text(encoding="utf-8").splitlines() == [
            "shared",
            "ours-only",
            "theirs-only",
        ]


# ============================================================================
# Malformed input must not abort the sync (audit S12)
# ============================================================================


class TestMalformedLines:
    """``daily-sync.sh`` turns a non-zero exit here into ``fail … 3``,
    which aborts the whole sync leaving a conflicted tree behind. The
    resolver must therefore survive anything a JSONL file can contain."""

    @pytest.mark.parametrize("payload", ["123", "null", "true", '"a string"', "[1, 2]"])
    def test_valid_json_that_is_not_an_object_is_kept(
        self, tmp_path: Path, payload: str
    ) -> None:
        """Audit S12: these parse fine and then raise AttributeError on
        ``.get()``, which the old ``except json.JSONDecodeError`` missed."""
        corpus = tmp_path / "memories.jsonl"
        corpus.write_text(
            "<<<<<<< HEAD\n"
            + _record("ours") + "\n"
            + "=======\n"
            + payload + "\n"
            + ">>>>>>> other\n",
            encoding="utf-8",
        )
        result = _run_resolver(str(corpus))
        assert result.returncode == 0, result.stderr
        assert "Traceback" not in result.stderr
        text = corpus.read_text(encoding="utf-8")
        assert payload in text, "a malformed-but-non-empty line was dropped"
        assert '"ours"' in text

    def test_unparseable_lines_are_kept_and_deduplicated(self, tmp_path: Path) -> None:
        """Genuinely broken JSON is kept once, by string equality."""
        corpus = tmp_path / "memories.jsonl"
        corpus.write_text(
            "<<<<<<< HEAD\n{not json\n=======\n{not json\n{also not json\n>>>>>>> x\n",
            encoding="utf-8",
        )
        assert _run_resolver(str(corpus)).returncode == 0
        assert corpus.read_text(encoding="utf-8").splitlines() == [
            "{not json",
            "{also not json",
        ]

    def test_dedup_helper_handles_non_objects_directly(self) -> None:
        """Unit-level pin on the same defect."""
        assert rmc.dedup_jsonl_by_id(["123", "123", "null"]) == ["123", "null"]

    def test_blank_lines_are_dropped(self, tmp_path: Path) -> None:
        """Harmless for JSONL, and stated in the module docstring."""
        assert rmc.dedup_jsonl_by_id(["", "  ", _record("a")]) == [_record("a")]


# ============================================================================
# Marker recognition, no-ops, and the file-level contract
# ============================================================================


class TestMarkersAndContract:
    """Marker matching is deliberately exact-line, so record content that
    contains ``=======`` cannot be mistaken for a conflict."""

    def test_marker_lookalikes_inside_content_are_not_markers(self) -> None:
        """A record whose content embeds the separator is left alone."""
        embedded = json.dumps({"id": "x", "content": "a table ======= like this"})
        assert not rmc.has_conflict_markers([embedded])
        assert rmc.is_conflict_marker("=======")
        assert not rmc.is_conflict_marker("======= trailing")

    def test_clean_file_is_untouched(self, tmp_path: Path) -> None:
        """The no-op path must not rewrite the file at all."""
        corpus = tmp_path / "memories.jsonl"
        original = _record("a") + "\n" + _record("a") + "\n"
        corpus.write_text(original, encoding="utf-8")
        before = corpus.stat().st_mtime_ns

        result = _run_resolver(str(corpus))
        assert result.returncode == 0
        assert "no conflict markers" in result.stdout
        assert corpus.read_text(encoding="utf-8") == original, (
            "a clean file was deduplicated — the resolver must only act on conflicts"
        )
        assert corpus.stat().st_mtime_ns == before

    def test_quiet_if_clean_says_nothing(self, tmp_path: Path) -> None:
        """Automation calls it this way; silence keeps the log readable."""
        corpus = tmp_path / "memories.jsonl"
        corpus.write_text(_record("a") + "\n", encoding="utf-8")
        result = _run_resolver("--quiet-if-clean", str(corpus))
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_missing_file_exits_two(self, tmp_path: Path) -> None:
        """Documented contract: exit 2 on a missing input file."""
        result = _run_resolver(str(tmp_path / "absent.jsonl"))
        assert result.returncode == 2
        assert "does not exist" in result.stderr

    def test_several_files_in_one_call(self, tmp_path: Path) -> None:
        """The sync passes both memory files at once."""
        corpus = tmp_path / "memories.jsonl"
        corpus.write_text(
            "<<<<<<< HEAD\n" + _record("a") + "\n=======\n" + _record("b") + "\n>>>>>>> x\n",
            encoding="utf-8",
        )
        vocab = tmp_path / "tag-vocabulary.txt"
        vocab.write_text("<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> x\n", encoding="utf-8")
        result = _run_resolver(str(corpus), str(vocab))
        assert result.returncode == 0, result.stderr
        assert '"a"' in corpus.read_text(encoding="utf-8")
        assert '"b"' in corpus.read_text(encoding="utf-8")
        assert vocab.read_text(encoding="utf-8").splitlines() == ["ours", "theirs"]

    def test_no_temp_file_is_left_behind(self, real_conflict: Path) -> None:
        """The atomic write must leave no ``.tmp`` sibling."""
        assert _run_resolver(str(real_conflict)).returncode == 0
        assert not list(real_conflict.parent.glob("*.tmp"))

    def test_resolved_file_ends_with_a_newline(self, real_conflict: Path) -> None:
        """An unterminated final line would corrupt the next append."""
        assert _run_resolver(str(real_conflict)).returncode == 0
        assert real_conflict.read_text(encoding="utf-8").endswith("\n")
