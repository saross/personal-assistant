"""
Tests for scripts/monthly-archive.py — the recurring archival cadence
(write-path item 13 / P2).

Focuses on the safety-critical pure helpers: the dry-run SANITY gate and
the time-pinned recall-INVARIANCE gate (``verify_all_past_decay``), which
independently re-derives the decay decision for every archived record so a
boundary error in the tool cannot slip a still-recallable record into the
cold store. The subprocess/PG orchestration is exercised by a Shawn-watched
first run, not unit-tested here.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# The script has a hyphen in its name, so we need importlib tricks.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
ma = __import__("monthly-archive")

AS_OF = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


def _rec(category: str, *, age_days: float, mem_id: str = "id-1", deadline_age: float | None = None) -> dict:
    """Build a record whose created_at is `age_days` before AS_OF."""
    rec = {
        "id": mem_id,
        "category": category,
        "created_at": (AS_OF - timedelta(days=age_days)).isoformat(),
    }
    if deadline_age is not None:
        rec["deadline_at"] = (AS_OF - timedelta(days=deadline_age)).isoformat()
    return rec


# ===========================================================================
# parse_category_counts / parse_category_config / parse_archive_count / paths
# ===========================================================================


def test_parse_category_counts_skips_blank_and_malformed() -> None:
    out = "decision|120\n\ngarbage\nprogress|notanumber\ncontext|11\n"
    assert ma.parse_category_counts(out) == {"decision": 120, "context": 11}


def test_parse_category_config_null_decay_is_none() -> None:
    out = "decision|30\ngotcha|\npattern|\nprogress|30\n"
    cfg = ma.parse_category_config(out)
    assert cfg == {"decision": 30, "gotcha": None, "pattern": None, "progress": 30}


def test_parse_archive_count() -> None:
    assert ma.parse_archive_count("Records to archive: **46**  (0.04 MB)") == 46
    assert ma.parse_archive_count("no marker here") is None
    assert ma.parse_archive_count("Records to archive: **0**") == 0


def test_parse_partition_path() -> None:
    line = "archived 46 records → /home/x/data/memories/archive/memories-archive-2026-06.jsonl"
    assert ma.parse_partition_path(line) == "/home/x/data/memories/archive/memories-archive-2026-06.jsonl"
    assert ma.parse_partition_path("nothing relevant") is None


def test_parse_jsonl_records_skips_bad_lines() -> None:
    text = '{"id":"a","category":"progress"}\n\nnot json\n[1,2]\n{"id":"b"}\n'
    recs = ma.parse_jsonl_records(text)
    assert [r.get("id") for r in recs] == ["a", "b"]


# ===========================================================================
# sanity_verdict
# ===========================================================================


def test_sanity_zero_and_normal_ok() -> None:
    assert ma.sanity_verdict(0, 22_000)[0] is True
    assert ma.sanity_verdict(46, 22_000)[0] is True


def test_sanity_rejects_negative_over_cap_and_over_fraction() -> None:
    assert ma.sanity_verdict(-1, 22_000)[0] is False
    assert ma.sanity_verdict(ma.SANITY_ABS_CAP + 1, 10_000_000)[0] is False
    assert ma.sanity_verdict(5_000, 10_000)[0] is False  # 50% > 25%


def test_sanity_no_active_skips_fraction() -> None:
    assert ma.sanity_verdict(5, 0)[0] is True


# ===========================================================================
# record_age_days
# ===========================================================================


def test_record_age_days_from_created_at() -> None:
    assert ma.record_age_days(_rec("progress", age_days=40), AS_OF) == pytest.approx(40.0)


def test_record_age_days_commitment_uses_deadline() -> None:
    # created 5 days ago but deadline 40 days ago → ages from the deadline.
    rec = _rec("commitment", age_days=5, deadline_age=40)
    assert ma.record_age_days(rec, AS_OF) == pytest.approx(40.0)


def test_record_age_days_commitment_without_deadline_uses_created() -> None:
    assert ma.record_age_days(_rec("commitment", age_days=33), AS_OF) == pytest.approx(33.0)


def test_record_age_days_missing_or_unparseable_is_none() -> None:
    assert ma.record_age_days({"category": "progress"}, AS_OF) is None
    assert ma.record_age_days({"category": "progress", "created_at": "not-a-date"}, AS_OF) is None


def test_record_age_days_parses_z_suffixed_timestamp() -> None:
    # The corpus contains Z-stamped timestamps; they must parse, not read as
    # unparseable (which would falsely flag the record as an invariance offender).
    rec = {"id": "z", "category": "progress", "created_at": "2026-05-03T06:11:28.861073Z"}
    age = ma.record_age_days(rec, AS_OF)
    assert age is not None and age == pytest.approx(30.24, abs=0.1)


# ===========================================================================
# verify_all_past_decay — the recall-invariance gate (safety heart)
# ===========================================================================

DECAY = {"progress": 30, "context": 30, "commitment": 30, "system_success": 90,
         "gotcha": None, "pattern": None, "decision": None}


def test_invariance_all_past_decay_holds() -> None:
    archived = [_rec("progress", age_days=40, mem_id="a"),
                _rec("context", age_days=45, mem_id="b"),
                _rec("system_success", age_days=120, mem_id="c")]
    ok, offenders = ma.verify_all_past_decay(archived, DECAY, AS_OF)
    assert ok is True and offenders == []


def test_invariance_in_window_record_is_regression() -> None:
    # 20 days old, 30-day window → still recallable → must NOT be archived.
    archived = [_rec("progress", age_days=40, mem_id="ok"),
                _rec("progress", age_days=20, mem_id="bad")]
    ok, offenders = ma.verify_all_past_decay(archived, DECAY, AS_OF)
    assert ok is False
    assert any("bad" in o for o in offenders) and not any("ok:" in o for o in offenders)


def test_invariance_boundary_is_strict() -> None:
    # age exactly == decay_days is NOT past decay (archive iff age > decay).
    archived = [_rec("progress", age_days=30, mem_id="boundary")]
    ok, offenders = ma.verify_all_past_decay(archived, DECAY, AS_OF)
    assert ok is False and "boundary" in offenders[0]


def test_invariance_just_past_boundary_holds() -> None:
    archived = [_rec("progress", age_days=30.5, mem_id="justpast")]
    ok, _ = ma.verify_all_past_decay(archived, DECAY, AS_OF)
    assert ok is True


def test_invariance_permanent_category_is_regression() -> None:
    archived = [_rec("gotcha", age_days=400, mem_id="g")]
    ok, offenders = ma.verify_all_past_decay(archived, DECAY, AS_OF)
    assert ok is False and "permanent" in offenders[0]


def test_invariance_no_decay_category_is_regression() -> None:
    # decision has decay_days=None → never archivable.
    archived = [_rec("decision", age_days=400, mem_id="d")]
    ok, offenders = ma.verify_all_past_decay(archived, DECAY, AS_OF)
    assert ok is False and "no-decay" in offenders[0]


def test_invariance_unparseable_age_is_regression() -> None:
    archived = [{"id": "x", "category": "progress", "created_at": "garbage"}]
    ok, offenders = ma.verify_all_past_decay(archived, DECAY, AS_OF)
    assert ok is False and "unparseable" in offenders[0]


def test_invariance_unknown_category_treated_as_no_decay() -> None:
    archived = [_rec("brand_new_category", age_days=400, mem_id="u")]
    ok, offenders = ma.verify_all_past_decay(archived, DECAY, AS_OF)
    assert ok is False and "no-decay" in offenders[0]


def test_invariance_empty_archived_is_vacuously_ok() -> None:
    ok, offenders = ma.verify_all_past_decay([], DECAY, AS_OF)
    assert ok is True and offenders == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
