"""
Tests for ``scripts/analyse-wiki-vocabulary.py``.

``/weekly-review`` step 5b runs this script against the live memory corpus,
so two properties matter more than any of its arithmetic: it must write
nothing anywhere, and a corpus it cannot fully parse must produce a
diagnostic rather than a traceback that aborts the review.

The corpus is redirected to a synthetic JSONL file under ``tmp_path`` in
every test; the module constant is patched, never the real store. Every tag,
date, and sentence is invented — see ``tests/fixtures``.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SCRIPT = PROJECT_ROOT / "scripts" / "analyse-wiki-vocabulary.py"

sys.path.insert(0, str(TESTS_DIR))
from fixtures import bake_off as fx  # noqa: E402

_spec = importlib.util.spec_from_file_location("analyse_wiki_vocabulary", SCRIPT)
assert _spec is not None and _spec.loader is not None
vocab = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = vocab
_spec.loader.exec_module(vocab)


@pytest.fixture(autouse=True)
def refuse_sockets(monkeypatch):
    """Fail loudly if any test in this module opens a socket."""

    def refuse(*args, **kwargs):
        raise AssertionError(
            "a vocabulary-analyser test opened a network socket; this script "
            "reads one JSONL file and prints."
        )

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _corpus(tmp_path: Path, records: list) -> Path:
    """Write a synthetic corpus and point the module constant at it."""
    return fx.write_memories_jsonl(tmp_path / "memories.jsonl", records)


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """Return a builder that installs a synthetic corpus as MEMORIES_JSONL."""

    def build(records: list) -> Path:
        path = _corpus(tmp_path, records)
        monkeypatch.setattr(vocab, "MEMORIES_JSONL", path)
        return path

    return build


TYPICAL_RECORDS = [
    fx.memory_record(
        "2026-01-05-aaa",
        research_tags=["prompt-design", "agent-orchestration"],
        created_at="2026-01-05T10:00:00+00:00",
    ),
    fx.memory_record(
        "2026-01-06-bbb",
        research_tags=["survey-grid", "teaching-load"],
        created_at="2026-01-06T11:00:00+00:00",
    ),
]


# ---------------------------------------------------------------------------
# The script must not write
# ---------------------------------------------------------------------------


def _tree_snapshot(root: Path) -> dict[str, tuple[bool, int, int]]:
    """Map every path under ``root`` to ``(is_file, mtime_ns, size)``.

    Only ``__pycache__`` is skipped, because the interpreter writes it and
    the code under test does not. ``.git`` is NOT skipped: a script that
    corrupts the object store or rewrites a ref is doing the most damage
    it can do to this repository, and a guard that looks away from the one
    directory holding the history is not a guard. It costs little —
    roughly 5,000 entries and 0.04s in a full clone.

    Directories are recorded as well as files, so a test that creates an
    empty directory is caught too, and a path that cannot be stat'ed (a
    dangling symlink into an uninitialised submodule, say) is recorded by
    its presence rather than silently dropped.
    """
    snapshot: dict[str, tuple[bool, int, int]] = {}
    for path in root.rglob("*"):
        parts = path.parts
        if "__pycache__" in parts:
            continue
        try:
            stat = path.stat()
        except OSError:
            snapshot[str(path)] = (False, -1, -1)
            continue
        snapshot[str(path)] = (path.is_file(), stat.st_mtime_ns, stat.st_size)
    return snapshot


#: The tree must be genuinely covered before an "unchanged" verdict means
#: anything. Both the count and the named files are asserted, because a
#: threshold alone can be relaxed to nothing without a test noticing.
def _assert_snapshot_covers_the_repository(
    snapshot: dict[str, tuple[bool, int, int]]
) -> None:
    """Fail unless ``snapshot`` plausibly covers the whole checkout."""
    assert len(snapshot) > 100, (
        f"the repository snapshot holds {len(snapshot)} entries — "
        "implausibly few, so an 'unchanged' verdict would be vacuous"
    )
    assert str(PROJECT_ROOT / "scripts") in snapshot
    assert str(PROJECT_ROOT / "tests") in snapshot


class TestWritesNothing:
    """The analyser is read-only; a report that lands on disk is a defect."""

    def test_repository_tree_and_home_are_untouched(self, corpus, capsys):
        """Snapshot the WHOLE checkout, plus HOME, across a full run.

        The previous version walked a list of directory names and compared
        each in turn. Three of them (``reports``, ``notes``, ``logs``) are
        symlinks into the private data submodule and ``data`` is the
        submodule itself, so wherever the submodule is uninitialised those
        comparisons were {} == {} — a guard that passed because it was
        looking at nothing. Snapshotting the root wholesale, and checking
        the snapshot really covers the tree, removes both failure modes.

        ``Path.home()`` here is the SUITE'S own temporary home, not the
        operator's: ``tests/conftest.py`` repoints ``HOME`` at import time
        so the suite's gate files and sidecars land somewhere disposable.
        Watching it still catches a script that writes to ``~`` — the write
        lands in the temp home rather than the real one, and shows up in
        this diff either way.
        """
        corpus(TYPICAL_RECORDS)
        home = Path.home()
        repo_before = _tree_snapshot(PROJECT_ROOT)
        home_before = _tree_snapshot(home)
        _assert_snapshot_covers_the_repository(repo_before)

        assert vocab.main([]) == 0

        repo_after = _tree_snapshot(PROJECT_ROOT)
        home_after = _tree_snapshot(home)
        assert repo_after == repo_before, (
            "the analyser wrote into the repository: "
            f"{sorted(set(repo_after) ^ set(repo_before))}"
        )
        assert home_after == home_before, (
            "the analyser wrote into HOME: "
            f"{sorted(set(home_after) ^ set(home_before))}"
        )
        capsys.readouterr()

    def test_the_snapshot_covers_known_repository_files(self):
        """Pin the coverage check itself.

        A bare count threshold can be neutered by relaxing the number
        (``> 100`` -> ``>= 0``) without any test noticing. Naming files
        that must be in the snapshot cannot be relaxed the same way: if
        they are absent the walk is not looking at the repository.
        """
        snapshot = _tree_snapshot(PROJECT_ROOT)
        _assert_snapshot_covers_the_repository(snapshot)
        for relative in (
            "scripts/analyse-wiki-vocabulary.py",
            "scripts/bake-off-metadata.py",
            "tests/conftest.py",
            "agents/corpus-style-analyser-v2.md",
            "CLAUDE.md",
        ):
            assert str(PROJECT_ROOT / relative) in snapshot, relative

    def test_a_write_inside_dot_git_is_caught(self, tmp_path):
        """.git is watched, not skipped: it is the most damaging target.

        Exercised on a synthetic tree because the real .git must never be
        written to — and in a linked worktree or a git-archive copy it is a
        file, or absent, so it could not exercise the directory case.
        """
        git_dir = tmp_path / ".git" / "refs" / "heads"
        git_dir.mkdir(parents=True)
        (git_dir / "main").write_text("0" * 40 + "\n", encoding="utf-8")
        before = _tree_snapshot(tmp_path)
        (git_dir / "main").write_text("1" * 40 + "\n", encoding="utf-8")
        assert _tree_snapshot(tmp_path) != before
        (tmp_path / ".git" / "objects").mkdir()
        assert str(tmp_path / ".git" / "objects") in _tree_snapshot(tmp_path)

    def test_only_pycache_is_skipped(self, tmp_path):
        """The one exclusion is the interpreter's, not the code's.

        The directory itself is skipped along with its contents: the
        interpreter creates and rewrites it constantly, and treating that
        as evidence of a rogue write would make the guard cry wolf.
        """
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "module.pyc").write_bytes(b"\x00")
        assert _tree_snapshot(tmp_path) == {}
        (tmp_path / "kept.txt").write_text("x", encoding="utf-8")
        assert list(_tree_snapshot(tmp_path)) == [str(tmp_path / "kept.txt")]

    @staticmethod
    def _snapshot_of_size(n_entries: int) -> dict[str, tuple[bool, int, int]]:
        """Build a snapshot with exactly ``n_entries``, named dirs included."""
        snapshot = {
            str(PROJECT_ROOT / "scripts"): (False, 0, 0),
            str(PROJECT_ROOT / "tests"): (False, 0, 0),
        }
        index = 0
        while len(snapshot) < n_entries:
            snapshot[str(PROJECT_ROOT / f"invented-{index}")] = (True, 0, 0)
            index += 1
        assert len(snapshot) == n_entries
        return snapshot

    def test_a_snapshot_at_the_threshold_is_rejected(self):
        """Fix the threshold in place from below.

        A two-entry fixture only pinned "> 2", so the number could drift to
        anything below the real tree's size without a test noticing. Exactly
        100 entries must still be rejected: that is what "> 100" means, and
        it is what "> 2" would wrongly accept.
        """
        with pytest.raises(AssertionError, match="implausibly few"):
            _assert_snapshot_covers_the_repository(self._snapshot_of_size(100))

    def test_a_snapshot_just_over_the_threshold_is_accepted(self):
        """And from above: 101 entries must pass, which "> 100000" would not."""
        _assert_snapshot_covers_the_repository(self._snapshot_of_size(101))

    def test_a_thin_snapshot_is_rejected(self):
        """The degenerate case the guard exists for."""
        with pytest.raises(AssertionError, match="implausibly few"):
            _assert_snapshot_covers_the_repository(self._snapshot_of_size(2))

    def test_the_snapshot_notices_a_new_file(self, tmp_path):
        """Guard the guard: the snapshot must be able to fail."""
        (tmp_path / "before.txt").write_text("a", encoding="utf-8")
        before = _tree_snapshot(tmp_path)
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "after.txt").write_text("b", encoding="utf-8")
        assert _tree_snapshot(tmp_path) != before

    def test_the_snapshot_notices_a_rewrite(self, tmp_path):
        target = tmp_path / "file.txt"
        target.write_text("original", encoding="utf-8")
        before = _tree_snapshot(tmp_path)
        target.write_text("rewritten and longer", encoding="utf-8")
        assert _tree_snapshot(tmp_path) != before

    def test_the_corpus_itself_is_not_rewritten(self, corpus):
        path = corpus(TYPICAL_RECORDS)
        before = path.stat()
        assert vocab.main([]) == 0
        assert (path.stat().st_mtime_ns, path.stat().st_size) == (
            before.st_mtime_ns,
            before.st_size,
        )


# ---------------------------------------------------------------------------
# Corpora that cannot be fully parsed
# ---------------------------------------------------------------------------


class TestDegradedCorpora:
    """Every malformed shape yields a diagnostic, never a traceback."""

    def test_empty_corpus_exits_with_a_diagnostic(self, corpus, capsys):
        """The finding: max(valid_dates) raised ValueError."""
        corpus([])
        assert vocab.main([]) == 1
        assert "nothing to analyse" in capsys.readouterr().err

    def test_all_malformed_corpus_exits_with_a_diagnostic(self, corpus, capsys):
        corpus(["{not json", "also not json"])
        assert vocab.main([]) == 1
        assert "nothing to analyse" in capsys.readouterr().err

    def test_missing_corpus_exits_with_a_diagnostic(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(vocab, "MEMORIES_JSONL", tmp_path / "absent.jsonl")
        assert vocab.main([]) == 1
        assert "no memory corpus" in capsys.readouterr().err

    def test_undated_corpus_still_reports_all_time_frequencies(self, corpus, capsys):
        """An undated corpus loses the window, not the whole report."""
        corpus([
            fx.memory_record("no-date-1", research_tags=["survey-grid"], created_at=""),
            fx.memory_record("no-date-2", research_tags=["survey-grid"], created_at="?"),
        ])
        assert vocab.main([]) == 0
        captured = capsys.readouterr()
        assert "no parseable created_at dates" in captured.out
        assert "survey-grid" in captured.out
        assert "recency window is skipped" in captured.err

    def test_non_string_tags_are_skipped_with_a_note(self, corpus, capsys):
        """The finding: tag.lower() raised AttributeError on a null tag."""
        corpus([
            fx.memory_record(
                "mixed-tags",
                research_tags=["survey-grid", None, 17, {"nested": True}],
            )
        ])
        assert vocab.main([]) == 0
        captured = capsys.readouterr()
        assert "skipped 3 research_tags entries" in captured.err
        assert "survey-grid" in captured.out

    def test_malformed_line_is_skipped_not_fatal(self, corpus, capsys):
        corpus([
            fx.memory_record("good", research_tags=["survey-grid"]),
            "{ this line is not json",
            "[1, 2, 3]",
        ])
        assert vocab.main([]) == 0
        assert "corpus: 1 records" in capsys.readouterr().out

    def test_bad_as_of_is_rejected(self, corpus, capsys):
        corpus(TYPICAL_RECORDS)
        assert vocab.main(["--as-of", "not-a-date"]) == 2
        assert "--as-of must be an ISO date" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


class TestTagNormalisation:
    """One normalisation, used at every call site."""

    def test_case_whitespace_and_unicode_form_collapse(self):
        """NFC first: a decomposed accent must not become a second tag."""
        assert vocab.normalise_tag("  Survey-Grid  ") == "survey-grid"
        composed, decomposed = "Tell Café", "Tell Café"
        assert composed != decomposed  # different code points
        assert vocab.normalise_tag(composed) == vocab.normalise_tag(decomposed)

    def test_unusable_values_return_none(self):
        for value in (None, 17, {"a": 1}, "", "   "):
            assert vocab.normalise_tag(value) is None

    def test_frequencies_and_support_count_different_things(self):
        """Support counts memories; frequency counts usages."""
        records = [
            fx.memory_record(
                "two-matching-tags",
                research_tags=["memory-system", "memory-pipeline"],
            )
        ]
        assert vocab.wiki_tag_support(records)["memory-system"] == 1
        frequencies = vocab.tag_frequencies(records)
        assert frequencies["memory-system"] == 1
        assert frequencies["memory-pipeline"] == 1
        assert sum(frequencies.values()) == 2

    def test_stripped_and_unstripped_spellings_are_one_tag(self):
        """The two call sites used to disagree: one stripped, one did not."""
        records = [
            fx.memory_record("a", research_tags=[" survey-grid "]),
            fx.memory_record("b", research_tags=["survey-grid"]),
        ]
        assert vocab.tag_frequencies(records)["survey-grid"] == 2

    def test_cooccurrence_pairs_are_normalised(self):
        records = [
            fx.memory_record("a", research_tags=[" Survey-Grid ", "PHASING"]),
        ]
        pairs = vocab.cooccurrence(records, {"survey-grid", "phasing"})
        assert pairs[("phasing", "survey-grid")] == 1


class TestReportShape:
    """The parts of the report a reader relies on."""

    def test_every_wiki_tag_appears_even_at_zero_support(self, corpus, capsys):
        corpus([fx.memory_record("a", research_tags=["survey-grid"])])
        assert vocab.main([]) == 0
        printed = capsys.readouterr().out
        for wiki_tag in vocab.WIKI_TAG_EXPANSIONS:
            assert wiki_tag in printed

    def test_as_of_pins_the_window_and_output_is_reproducible(self, corpus, capsys):
        corpus([
            fx.memory_record(
                "old", research_tags=["survey-grid"],
                created_at="2025-01-01T10:00:00+00:00",
            ),
            fx.memory_record(
                "new", research_tags=["phasing"],
                created_at="2026-01-05T10:00:00+00:00",
            ),
        ])
        assert vocab.main(["--as-of", "2026-01-06", "--window-days", "30"]) == 0
        first = capsys.readouterr().out
        assert vocab.main(["--as-of", "2026-01-06", "--window-days", "30"]) == 0
        assert capsys.readouterr().out == first
        assert "2025-12-07 → 2026-01-06" in first
        assert "→ 1 records" in first
