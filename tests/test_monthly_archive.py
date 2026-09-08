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


# ===========================================================================
# _apply halt gates — the WIRING, driven through the real entry point
#
# Added by audit round two (2026-09-08), finding S8/C5: the sanity and
# invariance predicates were well tested, but nothing exercised ``_apply``, so
# deleting the ``SANITY GATE TRIPPED ... return 3`` halt, or turning
# ``if not inv_ok:`` into ``if False:``, passed the whole suite — i.e. a run
# that archived 250,000 records, or archived still-recallable ones, would
# push without stopping.
#
# Every subprocess and every psql query is faked: no daily-sync.sh, no
# archive-memories.py, no PostgreSQL, no network. The module's real paths are
# repointed into tmp_path (with HOME pinned so ``_preflight``'s main-checkout
# assertion resolves there), so nothing outside the test tree is read or
# written.
# ===========================================================================

import json  # noqa: E402
import subprocess  # noqa: E402


def _completed(rc: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """A stand-in for a finished subprocess run."""
    return subprocess.CompletedProcess(args=["fake"], returncode=rc,
                                       stdout=stdout, stderr=stderr)


def _production_record(category: str, age_days: float, mem_id: str) -> dict:
    """A record carrying the field set the writer actually emits.

    Field list taken from ``hooks/extraction-hook.py`` (the ``record = {...}``
    literal at :900, the optional fields appended after it, and ``verified``
    set from ``anchor_verify.verify_memory`` at :1173), not from the older
    ten-field conftest fixture — audit finding M5. Every optional field is
    present, including the nested ``anchors`` list; ``deadline_at`` mirrors
    ``created_at`` so a ``commitment`` record ages identically whichever
    field the reference-time rule picks.
    """
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    return {
        "id": mem_id,
        "session_id": "11111111-2222-3333-4444-555555555555",
        "project": "-home-shawn-personal-assistant",
        "source": "extraction",
        "category": category,
        "content": f"A {category} record {age_days} days old.",
        "confidence": "high",
        "research_tags": ["memory-system", "archival"],
        "source_context": "Session transcript, tail of the window",
        "created_at": created.isoformat(),
        "licence": None,
        "extractor_model_id": "claude-haiku-4-5-20251001",
        "source_message_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "summary": f"{category} summary",
        "why": "Because the halt gates must be exercised on realistic records.",
        "how_to_apply": "Only relevant to guidance categories; harmless here.",
        "zotero_key": "ABCD2345",
        "deadline_at": created.isoformat(),
        "anchors": [
            {"type": "file", "ref": "scripts/monthly-archive.py", "line": 497},
            {"type": "commit", "ref": "1a546ab"},
        ],
        "verified": "true",
    }


class FakeCadence:
    """Records every orchestration step and answers for psql and subprocesses."""

    def __init__(self, archive_dir: Path) -> None:
        self.archive_dir = archive_dir
        self.labels: list[str] = []
        self.dryrun_count = 5
        self.active_counts = "progress|100"
        self.category_config = "progress|30\ngotcha|\npattern|"
        self.still_active = "0"
        self.archived_records: list[dict] = []

    def run(self, cmd, *, label):
        """Stand in for ``monthly-archive._run`` (no subprocess is spawned)."""
        self.labels.append(label)
        if label == "archive dry-run":
            return _completed(stdout=f"Records to archive: **{self.dryrun_count}**")
        if label == "archive --apply":
            # Simulate the tool: write this run's records to the partition
            # and report the path on stderr, exactly as the real tool does.
            partition = self.archive_dir / "memories-archive-2026-06.jsonl"
            partition.parent.mkdir(parents=True, exist_ok=True)
            partition.write_text(
                "".join(json.dumps(r) + "\n" for r in self.archived_records),
                encoding="utf-8")
            return _completed(
                stderr=f"archived {len(self.archived_records)} records → {partition}")
        return _completed()

    def psql(self, sql):
        """Stand in for ``monthly-archive._psql`` (no database is contacted)."""
        if "active_memories" in sql:
            return self.active_counts
        if "category_config" in sql:
            return self.category_config
        if "is_active" in sql:
            return self.still_active
        raise AssertionError(f"unexpected query: {sql}")


@pytest.fixture()
def cadence(tmp_path, monkeypatch):
    """Repoint monthly-archive at a throwaway tree and fake every side effect."""
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "personal-assistant"
    (root / "logs").mkdir(parents=True)
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "python3").write_text("#!/bin/false\n")
    corpus = root / "data" / "memories" / "memories.jsonl"
    corpus.parent.mkdir(parents=True)
    corpus.write_text("", encoding="utf-8")
    archive_dir = corpus.parent / "archive"
    monkeypatch.setattr(ma, "PA_DIR", root)
    monkeypatch.setattr(ma, "VENV_PY", root / "venv" / "bin" / "python3")
    monkeypatch.setattr(ma, "CORPUS", corpus)
    monkeypatch.setattr(ma, "DATA_DIR", root / "data")
    monkeypatch.setattr(ma, "ARCHIVE_TOOL", root / "scripts" / "archive-memories.py")
    monkeypatch.setattr(ma, "DAILY_SYNC", root / "scripts" / "daily-sync.sh")
    monkeypatch.setattr(ma, "SYNC_PG", root / "scripts" / "sync-to-postgres.py")
    monkeypatch.setattr(ma, "ARCHIVE_GLOB", str(archive_dir / "memories-archive-*.jsonl"))
    monkeypatch.setattr(ma, "LOCK_PATH", root / "logs" / "monthly-archive.lock")
    monkeypatch.setattr(ma, "LOG_PATH", root / "logs" / "monthly-archive.log")
    fake = FakeCadence(archive_dir)
    monkeypatch.setattr(ma, "_run", fake.run)
    monkeypatch.setattr(ma, "_psql", fake.psql)
    return fake


def test_apply_pushes_when_every_gate_passes(cadence) -> None:
    """The positive control: without it, the halt tests below could pass
    simply because the pipeline never got that far."""
    cadence.dryrun_count = 1
    cadence.archived_records = [_production_record("progress", 400, "past-decay-1")]
    assert ma.main(["--apply"]) == 0
    assert "archive --apply" in cadence.labels
    assert "push (daily-sync)" in cadence.labels


def test_sanity_gate_halts_before_the_apply(cadence) -> None:
    """An absurd sweep must be refused BEFORE the corpus is touched."""
    cadence.dryrun_count = ma.SANITY_ABS_CAP + 1
    assert ma.main(["--apply"]) == 3
    assert "archive dry-run" in cadence.labels
    assert "archive --apply" not in cadence.labels, (
        "the sanity gate let an oversized sweep reach the mutating tool")
    assert "push (daily-sync)" not in cadence.labels


def test_fraction_cap_is_measured_against_the_live_active_count(cadence) -> None:
    """The gate's second bound is wired to the PG active count, not a constant."""
    cadence.active_counts = "progress|100"
    cadence.dryrun_count = 30           # 30% of 100, over the 25% cap
    assert ma.main(["--apply"]) == 3
    assert "archive --apply" not in cadence.labels


def test_invariance_gate_halts_before_the_push(cadence) -> None:
    """A still-recallable record in the archived set is a recall regression:
    halt with the commit local and revertable, never push."""
    cadence.dryrun_count = 1
    cadence.archived_records = [_production_record("progress", 1, "still-recallable")]
    assert ma.main(["--apply"]) == 4
    assert "archive --apply" in cadence.labels
    assert "push (daily-sync)" not in cadence.labels, (
        "recall-regressing archival was pushed")


def test_pg_drift_gate_halts_before_the_push(cadence) -> None:
    """Archived ids that still read is_active=TRUE mean PG was unreachable
    during the apply — do not publish on known drift."""
    cadence.dryrun_count = 1
    cadence.archived_records = [_production_record("progress", 400, "past-decay-1")]
    cadence.still_active = "1"
    assert ma.main(["--apply"]) == 6
    assert "push (daily-sync)" not in cadence.labels


def test_apply_from_a_worktree_is_refused_before_anything_runs(cadence, tmp_path,
                                                              monkeypatch) -> None:
    """Preflight pins the tool to the MAIN checkout: the corpus it rewrites is
    an absolute path into the main tree, so a worktree run would break mutual
    exclusion."""
    monkeypatch.setattr(ma, "PA_DIR", tmp_path / "worktrees" / "pa-copy")
    assert ma.main(["--apply"]) == 2
    assert cadence.labels == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
