"""
Tests for scripts/drift-sweep.py — the standing anchor drift-sweep (item 8).

Covers the pure trend_line flattening, the best-effort append_trend writer,
and main()'s threshold exit logic (with the slow git-resolution sweep
stubbed out — the resolution itself is already covered by the memory-health
report's tests).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Hyphenated module names — import via __import__ after putting scripts/ on path.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
ds = __import__("drift-sweep")


FIXED_NOW = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)

# A representative tier_c_audit result (the shape run_sweep returns).
SAMPLE_RESULT = {
    "window_days": 100_000,
    "anchored_in_window": 1612,
    "verdicts": {"true": 1296, "false": 297, "pending": 7, "no_valid_anchor": 12},
    "fail_count": 297,
    "fail_rate_pct": 18.4,
    "failing_file_ref_recovery": {"absent": 201, "recoverable": 95, "ambiguous": 65},
    "repo_count": 36,
}


# ============================================================================
# trend_line — pure flattening
# ============================================================================


def test_trend_line_maps_all_fields() -> None:
    rec = ds.trend_line(SAMPLE_RESULT, as_of=FIXED_NOW)
    assert rec == {
        "run_at": FIXED_NOW.isoformat(),
        "total_anchored": 1612,
        "pass": 1296,
        "fail": 297,
        "pending": 7,
        "no_valid_anchor": 12,
        "fail_pct": 18.4,
        "absent": 201,
        "recoverable": 95,
        "ambiguous": 65,
        "repos": 36,
    }


def test_trend_line_tolerates_missing_keys() -> None:
    """A sparse result (e.g. zero failures, no recovery split) defaults to 0."""
    rec = ds.trend_line(
        {"anchored_in_window": 5, "verdicts": {"true": 5}, "fail_count": 0,
         "fail_rate_pct": 0.0},
        as_of=FIXED_NOW,
    )
    assert rec["pass"] == 5
    assert rec["fail"] == 0
    assert rec["absent"] == rec["recoverable"] == rec["ambiguous"] == 0


# ============================================================================
# append_trend — best-effort JSONL writer
# ============================================================================


def test_append_trend_writes_jsonl(tmp_path: Path) -> None:
    log = tmp_path / "drift-sweep.jsonl"
    rec = ds.trend_line(SAMPLE_RESULT, as_of=FIXED_NOW)
    assert ds.append_trend(rec, log_path=log) is True
    line = log.read_text(encoding="utf-8").strip()
    assert json.loads(line)["total_anchored"] == 1612


def test_append_trend_appends_not_overwrites(tmp_path: Path) -> None:
    log = tmp_path / "drift-sweep.jsonl"
    rec = ds.trend_line(SAMPLE_RESULT, as_of=FIXED_NOW)
    ds.append_trend(rec, log_path=log)
    ds.append_trend(rec, log_path=log)
    assert log.read_text(encoding="utf-8").count("\n") == 2


def test_append_trend_never_raises_on_unwritable(tmp_path: Path) -> None:
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    log = blocker / "drift-sweep.jsonl"  # parent is a file → unwritable
    assert ds.append_trend({"x": 1}, log_path=log) is False


# ============================================================================
# main — threshold exit logic (sweep stubbed)
# ============================================================================


def _stub_main(monkeypatch, *, fail_pct: float):
    """Stub load_records + run_sweep so main() runs without touching git/PG."""
    monkeypatch.setattr(ds, "load_records", lambda path: [])
    result = dict(SAMPLE_RESULT, fail_rate_pct=fail_pct)
    monkeypatch.setattr(ds, "run_sweep", lambda records, **kw: result)


def test_main_exit_zero_below_threshold(tmp_path: Path, monkeypatch) -> None:
    _stub_main(monkeypatch, fail_pct=18.4)
    rc = ds.main(["--log-path", str(tmp_path / "d.jsonl"), "--alert-threshold", "25"])
    assert rc == 0


def test_main_exit_one_above_threshold(tmp_path: Path, monkeypatch) -> None:
    _stub_main(monkeypatch, fail_pct=30.0)
    rc = ds.main(["--log-path", str(tmp_path / "d.jsonl"), "--alert-threshold", "25"])
    assert rc == 1


def test_main_appends_a_trend_line(tmp_path: Path, monkeypatch) -> None:
    _stub_main(monkeypatch, fail_pct=18.4)
    log = tmp_path / "d.jsonl"
    ds.main(["--log-path", str(log)])
    assert log.exists() and log.read_text(encoding="utf-8").count("\n") == 1


def test_main_no_log_skips_append(tmp_path: Path, monkeypatch) -> None:
    _stub_main(monkeypatch, fail_pct=18.4)
    log = tmp_path / "d.jsonl"
    ds.main(["--log-path", str(log), "--no-log"])
    assert not log.exists()


def test_main_missing_memories_file_exits_2(tmp_path: Path, monkeypatch) -> None:
    """A read failure on the corpus exits 2 cleanly, not a bare traceback."""
    def _raise(path):
        raise FileNotFoundError("no such file")
    monkeypatch.setattr(ds, "load_records", _raise)
    rc = ds.main(["--memories", str(tmp_path / "nope.jsonl"),
                  "--log-path", str(tmp_path / "d.jsonl"), "--no-log"])
    assert rc == 2


# ============================================================================
# The sweep refuses to log a run it could not trust (findings AN3 / AN7 / AN18)
# ============================================================================


def _fixed_sweep(monkeypatch, result: dict) -> None:
    """Stub load_records + run_sweep with a caller-supplied sweep result."""
    monkeypatch.setattr(ds, "load_records", lambda path: [])
    monkeypatch.setattr(ds, "run_sweep", lambda records, **kw: result)


def test_a_pending_dominated_sweep_writes_no_trend_row(tmp_path, monkeypatch):
    """A sweep that could not check most anchors is not a drift measurement.

    Kills the mutation removing the MAX_PENDING_PCT guard: the fabricated
    spike lands in an append-only log and shows in [H] for ever.
    """
    _fixed_sweep(monkeypatch, dict(
        SAMPLE_RESULT, verdicts={"true": 100, "pending": 900},
        anchored_in_window=1000, fail_count=0, fail_rate_pct=0.0,
    ))
    log = tmp_path / "d.jsonl"
    rc = ds.main(["--log-path", str(log)])
    assert rc == 2
    assert not log.exists(), "an unreliable sweep must not append a trend row"


def test_a_pending_rate_under_the_floor_still_logs(tmp_path, monkeypatch):
    """The control: the ordinary handful of pending verdicts is fine."""
    _fixed_sweep(monkeypatch, SAMPLE_RESULT)
    log = tmp_path / "d.jsonl"
    assert ds.main(["--log-path", str(log)]) == 0
    assert json.loads(log.read_text(encoding="utf-8"))["repos"] == 36


def test_an_empty_repo_set_refuses_the_sweep(tmp_path, monkeypatch):
    """Discovery that found nothing is a failure, not a 100 % drift result."""
    monkeypatch.setattr(ds, "load_records", lambda path: [])

    def _raise(records, **kw):
        raise ds.ta.RepoSetUnavailable("no git repositories discovered")

    monkeypatch.setattr(ds, "run_sweep", _raise)
    log = tmp_path / "d.jsonl"
    assert ds.main(["--log-path", str(log)]) == 2
    assert not log.exists()


def test_a_shrunken_repo_set_refuses_the_sweep(tmp_path, monkeypatch):
    """run_sweep enforces the floor the last successful run recorded.

    Kills the mutation dropping the ``len(repos) < min_repos`` guard: a run
    on a machine where ~/Code is unpopulated would report every anchor in
    those repositories as absent.
    """
    monkeypatch.setattr(ds.ta, "broad_repo_set", lambda: [tmp_path])
    with pytest.raises(ds.ta.RepoSetUnavailable):
        ds.run_sweep([], as_of=FIXED_NOW, min_repos=12)


def test_the_repo_floor_comes_from_the_last_logged_sweep(tmp_path) -> None:
    """last_repo_count reads the most recent non-zero ``repos`` value."""
    log = tmp_path / "d.jsonl"
    log.write_text(
        json.dumps({"run_at": "2031-01-01T00:00:00+00:00", "repos": 9}) + "\n"
        + "{broken\n"
        + json.dumps({"run_at": "2031-01-08T00:00:00+00:00", "repos": 11})
        + "\n",
        encoding="utf-8",
    )
    assert ds.last_repo_count(log) == 11
    assert ds.last_repo_count(tmp_path / "absent.jsonl") == 0


def test_a_lost_trend_row_is_a_failed_run(tmp_path, monkeypatch) -> None:
    """An unwritable trend log exits non-zero (finding AN18).

    Kills the mutation that keeps the old ``return 0`` after a failed append:
    a silent gap in the series is invisible when the trend is next read.
    """
    _fixed_sweep(monkeypatch, SAMPLE_RESULT)
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    rc = ds.main(["--log-path", str(blocker / "d.jsonl")])
    assert rc == 2
