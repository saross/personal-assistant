"""
Tests for scripts/archive-memories.py — the item-13 category-retention sweep.

Covers the pure planning logic (``should_archive``, ``partition_corpus``,
``effective_windows``, ``parse_iso``, ``_reference_time``). The I/O paths
(corpus rewrite, bulk-rewrite guard, git commit, postgres update) are not
exercised here — they reuse already-tested modules (``_bulk_rewrite_guard``,
``_schema_version``).
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load(name, rel):
    path = Path(__file__).parent.parent / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


am = _load("archive_memories", "scripts/archive-memories.py")

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
# A representative ephemeral window set (mirrors the signed-off policy).
WINDOWS = am.effective_windows({
    "progress": 30, "context": 30, "waiting_for": 14, "commitment": 30,
    "gotcha": 180, "pattern": 180, "decision": None,
})


def _days_ago(n: int) -> str:
    """ISO timestamp n days before NOW (aware UTC)."""
    return (NOW.replace(hour=0) - timedelta(days=n)).isoformat()


def _rec(category, created_days_ago, **extra):
    r = {"id": f"id-{category}-{created_days_ago}", "category": category,
         "created_at": _days_ago(created_days_ago)}
    r.update(extra)
    return r


class TestParseIso:
    def test_z_suffix(self):
        assert am.parse_iso("2026-06-01T00:00:00Z").tzinfo is not None

    def test_naive_assumed_utc(self):
        dt = am.parse_iso("2026-06-01T00:00:00")
        assert dt.tzinfo == timezone.utc

    def test_none_and_garbage(self):
        assert am.parse_iso(None) is None
        assert am.parse_iso("not-a-date") is None


class TestReferenceTime:
    def test_standard_uses_created_at(self):
        rec = {"category": "progress", "created_at": "C", "deadline_at": "D"}
        assert am._reference_time(rec) == "C"

    def test_commitment_prefers_deadline(self):
        rec = {"category": "commitment", "created_at": "C", "deadline_at": "D"}
        assert am._reference_time(rec) == "D"

    def test_commitment_falls_back_to_created(self):
        rec = {"category": "commitment", "created_at": "C"}
        assert am._reference_time(rec) == "C"


class TestEffectiveWindows:
    def test_gotcha_pattern_forced_permanent(self):
        w = am.effective_windows({"gotcha": 180, "pattern": 180, "progress": 30})
        assert w["gotcha"] is None
        assert w["pattern"] is None
        assert w["progress"] == 30

    def test_does_not_mutate_input(self):
        # The module-level WINDOWS is shared across tests; effective_windows
        # must copy, not mutate its argument.
        src = {"gotcha": 180, "progress": 30}
        am.effective_windows(src)
        assert src == {"gotcha": 180, "progress": 30}

    def test_override_added_when_category_absent(self):
        # pattern not in the input dict is still forced permanent.
        w = am.effective_windows({"progress": 30})
        assert w["pattern"] is None and w["gotcha"] is None


class TestShouldArchive:
    def test_permanent_category_never_archives(self):
        assert am.should_archive(_rec("decision", 9999), WINDOWS, NOW) is False

    def test_progress_past_window_archives(self):
        assert am.should_archive(_rec("progress", 45), WINDOWS, NOW) is True

    def test_progress_within_window_kept(self):
        assert am.should_archive(_rec("progress", 10), WINDOWS, NOW) is False

    def test_boundary_is_strict(self):
        # age exactly == window → NOT archived (matches apply-decay's strict >).
        assert am.should_archive(_rec("progress", 30), WINDOWS, NOW) is False
        assert am.should_archive(_rec("progress", 31), WINDOWS, NOW) is True

    def test_fractional_age_past_window_archives(self):
        # A record 30d 12h old is past a 30d window (PG decays it via the
        # fractional interval); the truncated-.days bug would wrongly keep it.
        rec = {"id": "x", "category": "progress",
               "created_at": (NOW - timedelta(days=30, hours=12)).isoformat()}
        assert am.should_archive(rec, WINDOWS, NOW) is True

    def test_fractional_age_within_window_kept(self):
        rec = {"id": "x", "category": "progress",
               "created_at": (NOW - timedelta(days=29, hours=23)).isoformat()}
        assert am.should_archive(rec, WINDOWS, NOW) is False

    def test_commitment_ages_from_deadline(self):
        # created recently, but deadline 40 days past → archived on window 30.
        rec = _rec("commitment", 5, deadline_at=_days_ago(40))
        assert am.should_archive(rec, WINDOWS, NOW) is True

    def test_commitment_future_deadline_kept(self):
        rec = _rec("commitment", 200, deadline_at=_days_ago(-10))  # 10d in future
        assert am.should_archive(rec, WINDOWS, NOW) is False

    def test_gotcha_override_keeps_old_record(self):
        # 200 days old but gotcha is forced permanent by the override.
        assert am.should_archive(_rec("gotcha", 200), WINDOWS, NOW) is False

    def test_unparseable_timestamp_is_kept(self):
        rec = {"id": "x", "category": "progress", "created_at": "garbage"}
        assert am.should_archive(rec, WINDOWS, NOW) is False

    def test_missing_timestamp_is_kept(self):
        assert am.should_archive({"id": "x", "category": "progress"},
                                 WINDOWS, NOW) is False

    def test_unknown_category_is_kept(self):
        assert am.should_archive(_rec("mystery", 9999), WINDOWS, NOW) is False


class TestPartitionCorpus:
    def _lines(self, records):
        return [json.dumps(r) + "\n" for r in records]

    def test_splits_and_counts(self):
        records = [
            _rec("progress", 45),   # archive
            _rec("progress", 5),    # keep (young)
            _rec("decision", 999),  # keep (permanent)
            _rec("context", 60),    # archive
        ]
        lines = self._lines(records)
        kept, archived, counts = am.partition_corpus(lines, WINDOWS, NOW)
        assert len(archived) == 2
        assert len(kept) == 2
        assert counts == {"progress": 1, "context": 1}

    def test_only_categories_filter(self):
        records = [_rec("progress", 45), _rec("context", 60)]
        lines = self._lines(records)
        kept, archived, counts = am.partition_corpus(
            lines, WINDOWS, NOW, only_categories=frozenset({"progress"}))
        # context is past its window but out of scope → kept.
        assert [a["record"]["category"] for a in archived] == ["progress"]
        assert any("context" in k for k in kept)

    def test_verbatim_lines_preserved(self):
        # An archived line is preserved byte-for-byte (incl. exotic spacing).
        raw = json.dumps(_rec("progress", 45)) + "\n"
        weird = raw.replace(", ", ",   ")  # extra whitespace, still valid JSON
        kept, archived, counts = am.partition_corpus([weird], WINDOWS, NOW)
        assert len(archived) == 1
        assert archived[0]["raw"] == weird

    def test_blank_and_unparseable_lines_kept(self):
        lines = ["\n", "not json\n", json.dumps(_rec("progress", 45)) + "\n"]
        kept, archived, counts = am.partition_corpus(lines, WINDOWS, NOW)
        assert "\n" in kept
        assert "not json\n" in kept
        assert len(archived) == 1

    def test_every_line_lands_in_exactly_one_bucket(self):
        records = [_rec("progress", 45), _rec("decision", 999),
                   _rec("context", 60), _rec("progress", 5)]
        lines = self._lines(records) + ["\n", "junk\n"]
        kept, archived, counts = am.partition_corpus(lines, WINDOWS, NOW)
        # No record dropped or duplicated: kept + archived == input.
        assert len(kept) + len(archived) == len(lines)

    def test_empty_only_categories_archives_nothing(self):
        records = [_rec("progress", 45), _rec("context", 60)]
        lines = self._lines(records)
        kept, archived, counts = am.partition_corpus(
            lines, WINDOWS, NOW, only_categories=frozenset())
        assert archived == []
        assert len(kept) == 2
        assert counts == {}

    def test_counts_accumulate_per_category(self):
        records = [_rec("progress", 40), _rec("progress", 50),
                   _rec("progress", 60)]
        # distinct ids so they are distinct records
        for i, r in enumerate(records):
            r["id"] = f"p{i}"
        kept, archived, counts = am.partition_corpus(
            self._lines(records), WINDOWS, NOW)
        assert counts["progress"] == 3


class TestPartitionIds:
    def test_missing_partition_is_empty_set(self, tmp_path):
        assert am._partition_ids(tmp_path / "nope.jsonl") == set()

    def test_reads_ids_skipping_blank_and_garbage(self, tmp_path):
        p = tmp_path / "part.jsonl"
        p.write_text(
            json.dumps({"id": "a", "category": "progress"}) + "\n"
            + "\n"                       # blank
            + "not json\n"               # unparseable
            + json.dumps({"category": "progress"}) + "\n"  # id-less
            + json.dumps({"id": "b"}) + "\n",
            encoding="utf-8",
        )
        assert am._partition_ids(p) == {"a", "b"}
