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


def _tree_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """Map every non-git file under ``root`` to ``(mtime_ns, size)``."""
    snapshot: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        stat = path.stat()
        snapshot[str(path)] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


class TestWritesNothing:
    """The analyser is read-only; a report that lands on disk is a defect."""

    def test_repository_tree_is_untouched(self, corpus, capsys):
        """Snapshot the whole checkout across a full run."""
        corpus(TYPICAL_RECORDS)
        for directory in ("wiki", "reports", "notes", "logs", "data", "scripts"):
            watched = PROJECT_ROOT / directory
            before = _tree_snapshot(watched) if watched.is_dir() else {}
            assert vocab.main([]) == 0
            after = _tree_snapshot(watched) if watched.is_dir() else {}
            assert after == before, f"the analyser wrote into {directory}/"
        capsys.readouterr()

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
