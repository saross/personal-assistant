"""
Tests for ``scripts/dedup-memories.py`` — the one-shot duplicate collapser.

The script rewrites the canonical memory store in place, so every test here
drives it against a throwaway JSONL under ``tmp_path`` with the module's path
constants monkeypatched, and with the bulk-rewrite guard replaced by a
recording stub (its own behaviour is covered by
``tests/test_bulk_rewrite_guard.py``). Nothing here may reach the real store;
the ``store`` fixture makes that structural rather than a matter of
discipline.

Fixtures are synthetic throughout: no id, line, tag, or sentence is copied
from the live corpus.
"""

from __future__ import annotations

import importlib
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
dedup = importlib.import_module("dedup-memories")

#: A Unicode LINE SEPARATOR — legal inside a JSON string, and a line break to
#: ``str.splitlines()`` but not to ``"\n"``-splitting or file iteration.
LS = "\u2028"


class Recorder:
    """Records the calls a stubbed guard/collaborator received."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the module at a throwaway corpus, log directory, and guard.

    Returns the corpus path (not yet created). The module logger's handlers
    are cleared too: ``setup_logging`` appends a fresh
    :class:`logging.FileHandler` on every call, so without this a later test
    keeps writing to an earlier test's deleted log file.
    """
    corpus = tmp_path / "memories.jsonl"
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(dedup, "MEMORIES_FILE", corpus)
    monkeypatch.setattr(dedup, "LOG_DIR", log_dir)
    monkeypatch.setattr(dedup, "LOG_FILE", log_dir / "dedup-test.log")
    logger = logging.getLogger("dedup-memories")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    return corpus


@pytest.fixture
def guard(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    """Replace the clean-tree guard with a recorder; keep the real flock."""
    recorder = Recorder()
    monkeypatch.setattr(dedup, "ensure_safe_to_rewrite", recorder)
    return recorder


def record(**overrides: object) -> dict:
    """Build a synthetic memory record with the canonical field shape."""
    base: dict = {
        "id": "2031-04-02-aaaabbbbcccc",
        "session_id": "session-orchid",
        "project": "-home-analyst-survey-atlas",
        "source": "extraction",
        "category": "decision",
        "content": "Kiln temperature logs are stored per firing, not per day.",
        "summary": "Kiln logs are per firing.",
        "confidence": "high",
        "research_tags": ["kiln", "recording"],
        "created_at": "2031-04-02T09:15:00+00:00",
    }
    base.update(overrides)
    return base


def write_corpus(path: Path, records: list[dict]) -> None:
    """Serialise records exactly as the extraction hook does (ensure_ascii)."""
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )


def write_corpus_unescaped(path: Path, records: list[dict]) -> None:
    """Serialise with ``ensure_ascii=False``, planting RAW separators.

    This is the shape an earlier ``ensure_ascii=False`` rewrite left on disk,
    so it is what a reader must survive today — not a hypothetical.
    """
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )


def run_main(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    """Invoke ``dedup.main()`` with a pinned argv."""
    monkeypatch.setattr(sys, "argv", ["dedup-memories.py", *argv])
    dedup.main()


# ---------------------------------------------------------------------------
# A1 — Unicode line separators must never split a record
# ---------------------------------------------------------------------------


class TestUnicodeLineSeparators:
    """A record whose content carries U+2028 must survive a rewrite."""

    def test_two_runs_are_byte_identical(
        self, store: Path, guard: Recorder, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Round-tripping a U+2028 record twice changes nothing at all.

        Kills the mutation ``json.dumps(clean)`` ->
        ``json.dumps(clean, ensure_ascii=False)``: run one un-escapes the
        separator, run two reads it as a line break and tears the record in
        two, so the third file differs from the second.
        """
        write_corpus(store, [
            record(id="2031-04-02-aaaabbbbcccc",
                   content=f"Trench A{LS}Trench B were dug in one season."),
            record(id="2031-04-03-ddddeeeeffff", summary="Second record."),
        ])
        before = store.read_bytes()

        run_main(monkeypatch)
        after_one = store.read_bytes()
        run_main(monkeypatch)
        after_two = store.read_bytes()

        assert after_one == before, "a clean corpus must round-trip unchanged"
        assert after_two == after_one, "the second run must be a no-op"
        assert b"\\u2028" in after_two, "the separator must stay escaped"

    def test_line_count_agrees_with_newline_split(self, store: Path) -> None:
        """Iteration and a ``"\\n"`` split must agree on the line count.

        The corpus here carries a RAW separator — the shape an earlier
        ``ensure_ascii=False`` rewrite left behind. Kills the mutation
        ``text.split("\\n")`` -> ``text.splitlines()``: the latter counts the
        U+2028 as a line break, so the loader reports three lines for a
        two-line file.
        """
        write_corpus_unescaped(store, [
            record(id="2031-04-02-aaaabbbbcccc",
                   content=f"Context continued{LS}on the next visual line."),
            record(id="2031-04-03-ddddeeeeffff"),
        ])

        records, _ = dedup.load_records_with_position()
        text = store.read_text(encoding="utf-8")
        newline_count = len(text.split("\n")) - 1
        with store.open("rb") as fh:
            iterated = sum(1 for _ in fh)

        assert len(records) == newline_count == iterated == 2

    def test_separator_record_is_not_torn_apart(
        self, store: Path, guard: Recorder, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Every output line still parses as JSON after a real run.

        Kills either half of the defect: a torn record leaves two fragments
        that ``json.loads`` rejects.
        """
        content = f"Paragraph one{LS}paragraph two."
        write_corpus_unescaped(store, [
            record(id="2031-04-02-aaaabbbbcccc", content=content),
            record(id="2031-04-03-ddddeeeeffff"),
        ])

        run_main(monkeypatch)

        lines = store.read_text(encoding="utf-8").split("\n")[:-1]
        assert len(lines) == 2
        parsed = [json.loads(line) for line in lines]
        assert parsed[0]["content"] == content
        # The run also HEALS the raw separator planted above: it is written
        # back escaped, so the next reader cannot trip over it either.
        assert LS not in store.read_text(encoding="utf-8")
