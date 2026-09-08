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
    @pytest.mark.parametrize("stray", ["|||||||", "||||||| looks like a base", "======="])
    def test_a_stray_marker_leaves_the_file_byte_identical(
        self, tmp_path: Path, name: str, stray: str
    ) -> None:
        """Kept verbatim, with everything after it, and not even the
        trailing newline changed — the file is written without one."""
        target = tmp_path / name
        original = (
            "first line\n"
            + stray + "\n"
            + "line after the stray marker\n"
            + "last line with no trailing newline"
        )
        target.write_bytes(original.encode("utf-8"))

        result = _run_resolver(str(target))
        assert result.returncode == 0, result.stderr
        assert target.read_bytes() == original.encode("utf-8"), (
            "the resolver rewrote a file that holds no conflict block"
        )

    def test_a_stray_marker_is_reported_to_the_operator(
        self, tmp_path: Path
    ) -> None:
        """Silence would leave them circling: the sync's gate points here."""
        target = tmp_path / "memories.jsonl"
        target.write_text(
            '{"id": "a"}\n||||||| looks like a base\n{"id": "b"}\n', encoding="utf-8"
        )
        result = _run_resolver("--quiet-if-clean", str(target))
        assert result.returncode == 0
        assert "outside any conflict block" in result.stderr
        assert "needs a human" in result.stderr

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
