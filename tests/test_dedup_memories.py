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

import hashlib
import importlib
import json
import logging
import os
import sys
from contextlib import contextmanager
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
    # CURSOR_FILE is derived from MEMORIES_FILE at import time, so patching
    # the corpus alone would leave the backlog gate reading the real store's
    # sync-cursors.json.
    monkeypatch.setattr(dedup, "CURSOR_FILE", tmp_path / "sync-cursors.json")
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


# ---------------------------------------------------------------------------
# Resolution policies — which copy survives (audit finding B3)
# ---------------------------------------------------------------------------


class TestResolutionPolicies:
    """The three duplicate classes, and what each one keeps."""

    def test_longest_summary_wins_earliest_line_breaks_ties(self) -> None:
        """Kills a mutation flipping the sort key to shortest-summary-first."""
        copies = [
            (7, record(summary="Short."), ""),
            (3, record(summary="A considerably more informative summary."), ""),
            (9, record(summary="A considerably more informative summary."), ""),
        ]
        lineno, winner, _raw = dedup.pick_summary_winner(copies)
        assert lineno == 3
        assert winner["summary"].startswith("A considerably")

    def test_reid_salt_is_the_original_line_number(self) -> None:
        """The synthetic salt pins each copy to where it was in the file.

        Kills a mutation that drops ``lineno`` (or the per-copy index) from
        the id source: every copy would then mint the same new id and the
        collision would survive.
        """
        copies = [
            (11, record(id="2031-04-02-aaaabbbbcccc",
                        session_id="session-orchid", source="reprocessing"), ""),
            (12, record(id="2031-04-02-aaaabbbbcccc",
                        session_id="session-orchid", source="reprocessing"), ""),
        ]
        out = dedup.reid_reprocess_collision(copies)
        new_ids = [rec["id"] for _lineno, rec, _raw in out]
        assert len(set(new_ids)) == 2
        expected = hashlib.sha256(
            "session-orchid-reprocess-relineno-11-0".encode()
        ).hexdigest()[:12]
        assert new_ids[0] == f"2031-04-02-{expected}"
        assert out[0][1]["_dedup_origin"]["original_id"] == "2031-04-02-aaaabbbbcccc"


# ---------------------------------------------------------------------------
# The removal journal (findings A6 and A10)
# ---------------------------------------------------------------------------


class TestRemovalJournal:
    """Nothing leaves the corpus without a durable copy on disk first."""

    def test_dropped_duplicate_is_recorded_before_the_rename(
        self, store: Path, guard: Recorder, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Every removed copy lands in the dated journal.

        Kills the mutation that deletes the ``write_removal_journal`` call:
        the losing copy would be evicted with no trace anywhere.
        """
        write_corpus(store, [
            record(id="2031-04-02-aaaabbbbcccc", summary="Short."),
            record(id="2031-04-02-aaaabbbbcccc",
                   summary="A much longer and more useful summary."),
        ])

        run_main(monkeypatch)

        journal = dedup.removal_journal_path()
        entries = [json.loads(line) for line
                   in journal.read_text(encoding="utf-8").split("\n")[:-1]]
        assert [e["type"] for e in entries] == ["removed"]
        assert entries[0]["reason"] == "summary-only"
        assert entries[0]["record"]["summary"] == "Short."
        assert entries[0]["original_lineno"] == 1

    def test_reid_writes_an_old_to_new_mapping_line(
        self, store: Path, guard: Recorder, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A re-identified copy leaves a reconcilable mapping.

        Kills the mutation that drops the ``remapped`` journal entries:
        surfaced.log, superseded_by, and the PostgreSQL row for the old id
        would be orphaned with no trail.
        """
        collided = record(id="2031-04-02-aaaabbbbcccc",
                          session_id="session-orchid", source="reprocessing")
        other = dict(collided)
        other["content"] = "A different chunk of the same session."
        write_corpus(store, [collided, other])

        run_main(monkeypatch)

        journal = dedup.removal_journal_path()
        entries = [json.loads(line) for line
                   in journal.read_text(encoding="utf-8").split("\n")[:-1]]
        assert all(e["type"] == "reid" for e in entries)
        assert len(entries) == 2
        assert {e["old_id"] for e in entries} == {"2031-04-02-aaaabbbbcccc"}
        assert len({e["new_id"] for e in entries}) == 2
        # The corpus itself carries the new ids and no transient marker.
        written = [json.loads(line) for line
                   in store.read_text(encoding="utf-8").split("\n")[:-1]]
        assert {r["id"] for r in written} == {e["new_id"] for e in entries}
        assert all("_dedup_origin" not in r for r in written)

    def test_journal_is_appended_never_truncated(
        self, store: Path, guard: Recorder, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A second run adds to the evidence rather than destroying it.

        Kills the mutation that opens the journal in ``"w"`` mode.
        """
        journal = dedup.removal_journal_path()
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text('{"type": "removed", "run_at": "earlier"}\n',
                           encoding="utf-8")
        write_corpus(store, [
            record(id="2031-04-02-aaaabbbbcccc", summary="Short."),
            record(id="2031-04-02-aaaabbbbcccc", summary="Longer summary here."),
        ])

        run_main(monkeypatch)

        lines = journal.read_text(encoding="utf-8").split("\n")[:-1]
        assert len(lines) == 2
        assert json.loads(lines[0])["run_at"] == "earlier"


# ---------------------------------------------------------------------------
# Wiring: guard, flock, atomic rename, dry-run gate
# ---------------------------------------------------------------------------


class TestWiring:
    """What the real run takes, and what the dry run must not."""

    def test_dry_run_writes_nothing_and_skips_the_guard(
        self, store: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--dry-run leaves the corpus and the journal alone.

        Kills the mutation that deletes ``if args.dry_run: ... return``, and
        the one that calls the guard before the dry-run branch.
        """
        write_corpus(store, [
            record(id="2031-04-02-aaaabbbbcccc", summary="Short."),
            record(id="2031-04-02-aaaabbbbcccc", summary="Longer summary here."),
        ])
        before = store.read_bytes()

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise SystemExit(2)

        monkeypatch.setattr(dedup, "ensure_safe_to_rewrite", refuse)
        run_main(monkeypatch, "--dry-run")

        assert store.read_bytes() == before
        assert not dedup.removal_journal_path().exists()

    def test_real_run_takes_the_guard_and_the_flock(
        self, store: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The rewrite is gated and locked, and renames a temp file.

        Kills the mutations that drop ``ensure_safe_to_rewrite``, replace
        ``lock_jsonl_for_rewrite`` with a nullcontext, or write the corpus
        in place instead of temp-and-rename.
        """
        write_corpus(store, [record(id="2031-04-02-aaaabbbbcccc")])
        order: list[str] = []
        real_lock = dedup.lock_jsonl_for_rewrite
        real_rename = os.rename
        renames: list[tuple[str, str]] = []

        @contextmanager
        def recording_lock(path):
            order.append(f"lock:{path}")
            with real_lock(path):
                yield

        def recording_rename(src, dst, **kwargs):
            renames.append((str(src), str(dst)))
            return real_rename(src, dst, **kwargs)

        monkeypatch.setattr(dedup, "ensure_safe_to_rewrite",
                            lambda reason: order.append("guard"))
        monkeypatch.setattr(dedup, "lock_jsonl_for_rewrite", recording_lock)
        monkeypatch.setattr(os, "rename", recording_rename)

        run_main(monkeypatch)

        assert order == ["guard", f"lock:{store}"]
        assert renames == [(str(store.with_suffix(".jsonl.tmp")), str(store))]

    def test_shrink_during_the_run_aborts_without_writing(
        self, store: Path, guard: Recorder, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A corpus that shrank mid-run must abort, not overwrite.

        Kills the mutation that turns the ``current_size < initial_bytes``
        abort into a warning.
        """
        write_corpus(store, [record(id="2031-04-02-aaaabbbbcccc")])
        before = store.read_bytes()
        real_load = dedup.load_records_with_position

        def load_overstating_the_size():
            records, initial = real_load()
            return records, initial + 4096  # pretend the file has since shrunk

        monkeypatch.setattr(dedup, "load_records_with_position",
                            load_overstating_the_size)

        with pytest.raises(SystemExit) as excinfo:
            run_main(monkeypatch)

        assert excinfo.value.code == 1
        assert store.read_bytes() == before
        assert not store.with_suffix(".jsonl.tmp").exists()


# ---------------------------------------------------------------------------
# Invariants and the unclassified-group policy (finding A13)
# ---------------------------------------------------------------------------


class TestInvariants:
    """Both invariant exits, and the group that must NOT trigger one."""

    def test_unexpected_duplicate_ids_abort(
        self, store: Path, guard: Recorder, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A duplicate id no policy accounted for is still fatal.

        Kills the mutation that deletes the duplicate-id invariant entirely
        while fixing A13.
        """
        write_corpus(store, [record(id="2031-04-02-aaaabbbbcccc")])
        duplicated = [
            (1, record(id="2031-04-02-aaaabbbbcccc"), ""),
            (2, record(id="2031-04-02-aaaabbbbcccc"), ""),
        ]
        monkeypatch.setattr(
            dedup, "dedup",
            lambda records, logger: (
                duplicated,
                {k: 0 for k in ("total_input_lines", "summary_only_dropped",
                                "reprocess_reid", "byte_identical_dropped")},
                {"removed": [], "remapped": [], "unclassified_ids": []},
            ),
        )

        with pytest.raises(SystemExit) as excinfo:
            run_main(monkeypatch)
        assert excinfo.value.code == 1

    def test_unserialisable_record_aborts(
        self, store: Path, guard: Recorder, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A record that cannot round-trip through JSON is fatal.

        Kills the mutation that deletes the serialisation invariant.
        """
        write_corpus(store, [record(id="2031-04-02-aaaabbbbcccc")])
        broken = [(1, {"id": "2031-04-02-aaaabbbbcccc", "content": {1, 2}}, "")]
        monkeypatch.setattr(
            dedup, "dedup",
            lambda records, logger: (
                broken,
                {k: 0 for k in ("total_input_lines", "summary_only_dropped",
                                "reprocess_reid", "byte_identical_dropped")},
                {"removed": [], "remapped": [], "unclassified_ids": []},
            ),
        )

        with pytest.raises(SystemExit) as excinfo:
            run_main(monkeypatch)
        assert excinfo.value.code == 1

    def test_unclassified_group_does_not_abort_a_productive_run(
        self, store: Path, guard: Recorder, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An unresolved group is kept verbatim, and the run still finishes.

        Kills the mutation that counts unclassified ids in the duplicate-id
        invariant: one awkward group would abort the whole sweep, so it could
        never make progress.
        """
        unclassified_a = record(id="2031-04-05-111122223333",
                                content="One reading of the section.")
        unclassified_b = record(id="2031-04-05-111122223333",
                                content="A different reading of the section.")
        write_corpus(store, [
            unclassified_a,
            unclassified_b,
            record(id="2031-04-02-aaaabbbbcccc", summary="Short."),
            record(id="2031-04-02-aaaabbbbcccc", summary="Longer summary here."),
        ])

        run_main(monkeypatch)

        written = [json.loads(line) for line
                   in store.read_text(encoding="utf-8").split("\n")[:-1]]
        ids = [r["id"] for r in written]
        assert ids.count("2031-04-05-111122223333") == 2, "kept verbatim"
        assert ids.count("2031-04-02-aaaabbbbcccc") == 1, "duplicate resolved"

    def test_a_run_that_resolves_nothing_exits_non_zero(
        self, store: Path, guard: Recorder, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If every group is unclassified the run achieved nothing.

        Kills the mutation that always returns 0 once A13 stops the abort.
        """
        write_corpus(store, [
            record(id="2031-04-05-111122223333",
                   content="One reading of the section."),
            record(id="2031-04-05-111122223333",
                   content="A different reading of the section."),
        ])

        with pytest.raises(SystemExit) as excinfo:
            run_main(monkeypatch)
        assert excinfo.value.code == 1


# ---------------------------------------------------------------------------
# Unsynced-backlog gate (audit 2026-09-08, finding A9)
# ---------------------------------------------------------------------------


class TestPostgresBacklogGate:
    """A line-deleting rewrite must not run ahead of the PostgreSQL sync."""

    def _corpus_with_a_duplicate(self, store: Path) -> None:
        write_corpus(store, [
            record(id="2031-04-02-aaaabbbbcccc", summary="Short."),
            record(id="2031-04-02-aaaabbbbcccc", summary="Longer summary here."),
            record(id="2031-04-03-ddddeeeeffff"),
        ])

    def test_backlog_refuses_and_writes_nothing(
        self, store: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A cursor behind the file blocks the rewrite before the guard.

        Kills the mutation that deletes the gate: without it the sweep
        removes a line, the still-unsynced record drops below the
        line-position cursor, and PostgreSQL never sees it.
        """
        self._corpus_with_a_duplicate(store)
        before = store.read_bytes()
        dedup.CURSOR_FILE.write_text(
            json.dumps({"postgres_sync_line": 1}), encoding="utf-8")

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("the guard ran despite the backlog")

        monkeypatch.setattr(dedup, "ensure_safe_to_rewrite", refuse)

        with pytest.raises(SystemExit) as excinfo:
            run_main(monkeypatch)

        assert excinfo.value.code == 1
        assert store.read_bytes() == before
        assert not dedup.removal_journal_path().exists()

    def test_caught_up_cursor_proceeds(
        self, store: Path, guard: Recorder, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A cursor level with the file lets the rewrite run."""
        self._corpus_with_a_duplicate(store)
        dedup.CURSOR_FILE.write_text(
            json.dumps({"postgres_sync_line": 3}), encoding="utf-8")

        run_main(monkeypatch)

        assert len(store.read_text(encoding="utf-8").split("\n")[:-1]) == 2

    def test_absent_cursor_is_not_a_backlog(
        self, store: Path, guard: Recorder, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A machine with no PostgreSQL has no cursor and must not be blocked."""
        self._corpus_with_a_duplicate(store)
        assert not dedup.CURSOR_FILE.exists()

        run_main(monkeypatch)

        assert len(store.read_text(encoding="utf-8").split("\n")[:-1]) == 2


    def test_unusable_cursor_refuses_and_writes_nothing(
        self, store: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A cursor that is present and unreadable must fail CLOSED.

        Kills the mutation that treats an unusable cursor as no backlog:
        the sweep would delete lines with nobody able to say which records
        would be stranded beneath the cursor. Audit round 4a-2, M2.
        """
        self._corpus_with_a_duplicate(store)
        before = store.read_bytes()
        dedup.CURSOR_FILE.write_text(
            json.dumps({"postgres_sync_line": -4}), encoding="utf-8")

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("the guard ran despite an unusable cursor")

        monkeypatch.setattr(dedup, "ensure_safe_to_rewrite", refuse)

        with pytest.raises(SystemExit) as excinfo:
            run_main(monkeypatch)

        assert excinfo.value.code == 1
        assert store.read_bytes() == before
        assert not dedup.removal_journal_path().exists()
