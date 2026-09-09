"""
Tests for scripts/drift-sweep.py — the standing anchor drift-sweep (item 8).

Covers the pure trend_line flattening, the best-effort append_trend writer,
and main()'s threshold exit logic (with the slow git-resolution sweep
stubbed out — the resolution itself is already covered by the memory-health
report's tests).
"""

from __future__ import annotations

import json
import os
import subprocess
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
        "unusable": [],
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
    _pin_repos(monkeypatch, [tmp_path])
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


# ============================================================================
# run_sweep, unstubbed, against throwaway repositories
# (findings ANT-Me / ANT-Mf / AN10)
# ============================================================================


def _init_repo(path: Path, relpath: str) -> Path:
    """Create a throwaway git repository at *path* tracking one file."""
    target = path / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# seeded\n", encoding="utf-8")
    env = {
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "PATH": os.environ.get("PATH", ""), "HOME": str(path.parent),
    }
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-qm", "seed"], check=True, env=env,
    )
    return path


def _pin_repos(monkeypatch, repos, discovered=None) -> None:
    """Pin discovery to *repos*, with an optional discovery-only count.

    ``run_sweep`` reads ``broad_repo_set_detail``; the plain
    ``broad_repo_set`` is pinned too so a test reaching either is served.
    """
    count = len(repos) if discovered is None else discovered
    monkeypatch.setattr(ds.ta, "broad_repo_set", lambda: list(repos))
    monkeypatch.setattr(
        ds.ta, "broad_repo_set_detail", lambda: (list(repos), count),
    )


def _record(mid: str, ref: str, created: str) -> dict:
    """One anchored synthetic memory."""
    return {
        "id": mid, "category": "progress", "created_at": created,
        "anchors": [{"type": "file", "ref": ref}],
    }


OLD = "2026-01-01T00:00:00+00:00"      # long before FIXED_NOW
RECENT = "2026-06-05T00:00:00+00:00"   # within a 30-day window of FIXED_NOW


def test_run_sweep_resolves_the_full_back_set(tmp_path, monkeypatch) -> None:
    """Every anchored record is checked, however old (the sweep's purpose).

    Unstubbed: real git, real anchor_verify, one throwaway repository.
    Kills the mutation hard-coding ``days=30`` in run_sweep, which would drop
    the 2026-01 record and defeat the module docstring's "never ages out".
    """
    repo = _init_repo(tmp_path / "repo", "wiki/notes.md")
    _pin_repos(monkeypatch, [repo])
    records = [
        _record("m-old", "wiki/notes.md", OLD),
        _record("m-recent", "wiki/notes.md", RECENT),
        _record("m-gone", "wiki/ghost.md", OLD),
    ]
    result = ds.run_sweep(records, as_of=FIXED_NOW)
    assert result["anchored_in_window"] == 3
    assert result["verdicts"]["true"] == 2
    assert result["fail_count"] == 1
    assert result["repo_count"] == 1
    assert result["failing_file_ref_recovery"] == {"absent": 1}


def test_run_sweep_honours_a_narrow_window(tmp_path, monkeypatch) -> None:
    """The control: ``days`` still narrows the population when asked."""
    repo = _init_repo(tmp_path / "repo", "wiki/notes.md")
    _pin_repos(monkeypatch, [repo])
    result = ds.run_sweep(
        [_record("m-old", "wiki/notes.md", OLD),
         _record("m-recent", "wiki/notes.md", RECENT)],
        as_of=FIXED_NOW, days=30,
    )
    assert result["anchored_in_window"] == 1


def test_run_sweep_recovers_a_prefix_mismatch(tmp_path, monkeypatch) -> None:
    """The recovery split comes from the real basename index, not a stub."""
    repo = _init_repo(tmp_path / "repo", "wiki/notes.md")
    _pin_repos(monkeypatch, [repo])
    result = ds.run_sweep(
        [_record("m-1", "notes.md", OLD)], as_of=FIXED_NOW,
    )
    assert result["fail_count"] == 1
    assert result["failing_file_ref_recovery"] == {"recoverable": 1}


def test_run_sweep_resolves_each_ref_once(tmp_path, monkeypatch) -> None:
    """Kills the mutation dropping the resolver memo (finding AN10).

    verify_file walks every repository and spawns up to two git processes
    each; tier_c_audit asks about every failing file anchor a second time for
    the recovery split, so an unmemoised sweep pays for the same ref twice
    per record.
    """
    repo = _init_repo(tmp_path / "repo", "wiki/notes.md")
    _pin_repos(monkeypatch, [repo])
    calls: list[str] = []
    real_verify_file = ds.av.verify_file

    def counting(ref, repos):
        calls.append(ref)
        return real_verify_file(ref, repos)

    monkeypatch.setattr(ds.av, "verify_file", counting)
    ds.run_sweep(
        [_record("m-1", "wiki/ghost.md", OLD),
         _record("m-2", "wiki/ghost.md", OLD)],
        as_of=FIXED_NOW,
    )
    # Two failing records, one distinct ref, ONE resolution through the
    # memoised split resolver. Without the memo it is one per record.
    # (verify_memory dispatches through anchor_verify._VERIFIERS, which
    # captured the real function at import, so it is not counted here.)
    assert calls.count("wiki/ghost.md") == 1


def test_main_reads_the_corpus_it_was_given(tmp_path, monkeypatch, capsys) -> None:
    """``--memories`` must actually be honoured (finding ANT-Mf).

    load_records is NOT stubbed here: the file named on the command line is
    the one swept, and its record count reaches the rendered summary.
    """
    repo = _init_repo(tmp_path / "repo", "wiki/notes.md")
    _pin_repos(monkeypatch, [repo])
    corpus = tmp_path / "elsewhere.jsonl"
    corpus.write_text(
        "\n".join(json.dumps(_record(f"m-{i}", "wiki/notes.md", OLD))
                  for i in range(4)) + "\n",
        encoding="utf-8",
    )
    rc = ds.main(["--memories", str(corpus), "--no-log"])
    assert rc == 0
    assert "Anchored swept:   4" in capsys.readouterr().out


# ============================================================================
# The repository floor must not become a one-way ratchet (finding C1)
# ============================================================================


def test_the_logged_repo_count_is_discovery_only(tmp_path, monkeypatch) -> None:
    """A worktree and the main checkout must log the SAME number.

    broad_repo_set adds the running copy's own checkout when HOME-based
    discovery missed it, so a sweep from ~/worktrees sees one repository more
    than a sweep from ~/personal-assistant. Recording that augmented number
    would ratchet the floor to a value the main checkout can never reach, and
    the trend log is append-only.

    Kills the mutation ``result["repo_count"] = len(repos)``.
    """
    repo = _init_repo(tmp_path / "repo", "wiki/notes.md")
    worktree = _init_repo(tmp_path / "worktree", "wiki/notes.md")
    records = [_record("m-1", "wiki/notes.md", OLD)]

    # From the main checkout: discovery finds one, nothing is added.
    _pin_repos(monkeypatch, [repo], discovered=1)
    from_main = ds.run_sweep(records, as_of=FIXED_NOW)

    # From a worktree: the same discovery, plus this copy's own checkout.
    _pin_repos(monkeypatch, [repo, worktree], discovered=1)
    from_worktree = ds.run_sweep(records, as_of=FIXED_NOW)

    assert from_main["repo_count"] == from_worktree["repo_count"] == 1
    assert ds.trend_line(from_worktree, as_of=FIXED_NOW)["repos"] == 1


def test_a_smaller_set_warns_and_names_the_override(
    tmp_path, monkeypatch, capsys,
) -> None:
    """The refusal has to tell the operator how to get past it.

    Kills the mutation dropping the RepoSetShrunk branch: the run would still
    refuse, but with no way to reset a floor written into an append-only log.
    """
    repo = _init_repo(tmp_path / "repo", "wiki/notes.md")
    _pin_repos(monkeypatch, [repo], discovered=1)
    log = tmp_path / "d.jsonl"
    log.write_text(json.dumps({"run_at": "2031-01-01", "repos": 5}) + "\n",
                   encoding="utf-8")
    corpus = tmp_path / "memories.jsonl"
    corpus.write_text(
        json.dumps(_record("m-1", "wiki/notes.md", OLD)) + "\n", encoding="utf-8",
    )

    rc = ds.main(["--memories", str(corpus), "--log-path", str(log)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "WARN: discovery found 1 repositories" in err
    assert "--min-repos 1" in err
    assert log.read_text(encoding="utf-8").count("\n") == 1, "no row appended"


def test_the_override_lets_the_sweep_run(tmp_path, monkeypatch) -> None:
    """--min-repos resets the floor, and the new count is what gets logged."""
    repo = _init_repo(tmp_path / "repo", "wiki/notes.md")
    _pin_repos(monkeypatch, [repo], discovered=1)
    log = tmp_path / "d.jsonl"
    log.write_text(json.dumps({"run_at": "2031-01-01", "repos": 5}) + "\n",
                   encoding="utf-8")
    corpus = tmp_path / "memories.jsonl"
    corpus.write_text(
        json.dumps(_record("m-1", "wiki/notes.md", OLD)) + "\n", encoding="utf-8",
    )

    rc = ds.main(["--memories", str(corpus), "--log-path", str(log),
                  "--min-repos", "1"])
    assert rc == 0
    rows = [json.loads(ln) for ln in
            log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert rows[-1]["repos"] == 1


def test_no_log_drops_the_floor(tmp_path, monkeypatch) -> None:
    """A run that records nothing cannot corrupt the series, so it may run."""
    repo = _init_repo(tmp_path / "repo", "wiki/notes.md")
    _pin_repos(monkeypatch, [repo], discovered=1)
    log = tmp_path / "d.jsonl"
    log.write_text(json.dumps({"run_at": "2031-01-01", "repos": 5}) + "\n",
                   encoding="utf-8")
    corpus = tmp_path / "memories.jsonl"
    corpus.write_text(
        json.dumps(_record("m-1", "wiki/notes.md", OLD)) + "\n", encoding="utf-8",
    )

    assert ds.main(["--memories", str(corpus), "--log-path", str(log),
                    "--no-log"]) == 0
    assert log.read_text(encoding="utf-8").count("\n") == 1


def test_main_applies_the_floor_from_the_log(tmp_path, monkeypatch) -> None:
    """main() must pass the logged floor down, not a hard-coded zero.

    run_sweep is NOT stubbed here: the floor travels from the log through
    main() into the real sweep. Kills the mutation ``min_repos=0``.
    """
    repo = _init_repo(tmp_path / "repo", "wiki/notes.md")
    _pin_repos(monkeypatch, [repo], discovered=2)
    log = tmp_path / "d.jsonl"
    log.write_text(json.dumps({"run_at": "2031-01-01", "repos": 9}) + "\n",
                   encoding="utf-8")
    corpus = tmp_path / "memories.jsonl"
    corpus.write_text(
        json.dumps(_record("m-1", "wiki/notes.md", OLD)) + "\n", encoding="utf-8",
    )

    assert ds.main(["--memories", str(corpus), "--log-path", str(log)]) == 2
    assert log.read_text(encoding="utf-8").count("\n") == 1


# ============================================================================
# A sweep that discovered nothing must not reach the log at all (M-a)
# ============================================================================


def test_a_degraded_machine_refuses_without_stubbing_discovery(
    tmp_path, monkeypatch, capsys,
) -> None:
    """No ~/Code, no ~/personal-assistant, but the checkout is a repository.

    broad_repo_set_detail is NOT stubbed here: only project_id.repo_set and
    PA_DIR are, which is the shape of the real degraded machine. Before the
    fix the sweep ran against that one checkout and appended a fail_pct
    100.0 row carrying ``repos: 0``.
    """
    worktree = _init_repo(tmp_path / "worktrees" / "pa-copy", "wiki/notes.md")
    monkeypatch.setattr(ds.ta.project_id, "repo_set", list)
    monkeypatch.setattr(ds.ta, "PA_DIR", worktree)
    log = tmp_path / "d.jsonl"
    corpus = tmp_path / "memories.jsonl"
    corpus.write_text(
        json.dumps(_record("m-1", "wiki/gone.md", OLD)) + "\n", encoding="utf-8",
    )

    rc = ds.main(["--memories", str(corpus), "--log-path", str(log)])
    assert rc == 2
    assert not log.exists(), "a degraded sweep must append nothing"
    assert "sweep unreliable" in capsys.readouterr().err


def test_a_zero_repo_result_is_never_logged(tmp_path, monkeypatch) -> None:
    """The second guard, independent of discovery raising.

    Kills the mutation removing the ``record["repos"] <= 0`` refusal: a
    result carrying no repository count would otherwise be appended, and
    last_repo_count skips such a row, so it imposes no floor on the next run
    either.
    """
    _fixed_sweep(monkeypatch, dict(SAMPLE_RESULT, repo_count=0))
    log = tmp_path / "d.jsonl"
    assert ds.main(["--log-path", str(log)]) == 2
    assert not log.exists()


def test_the_floor_skips_a_degraded_row_already_in_the_log(tmp_path) -> None:
    """A ``repos: 0`` row must not mask a real floor recorded before it.

    Kills the mutation ``count > 0`` -> ``count >= 0``: the scan then stops
    on the newest row and reports "no floor at all".
    """
    log = tmp_path / "d.jsonl"
    log.write_text(
        json.dumps({"run_at": "2031-01-01T00:00:00+00:00", "repos": 7}) + "\n"
        + json.dumps({"run_at": "2031-01-08T00:00:00+00:00", "repos": 0}) + "\n",
        encoding="utf-8",
    )
    assert ds.last_repo_count(log) == 7


def test_the_trend_row_names_the_repositories_left_out(
    tmp_path, monkeypatch,
) -> None:
    """A run that excluded a repository has to say so (finding M-b).

    Kills the mutation dropping ``unusable_repos`` from the sweep result:
    the row would record the full discovered count as though every
    repository had answered, and the only trace of the exclusion would be a
    stderr WARN that a cron run discards.
    """
    good = _init_repo(tmp_path / "good", "wiki/notes.md")
    broken = tmp_path / "broken"          # a directory, not a repository
    broken.mkdir()
    _pin_repos(monkeypatch, [good, broken], discovered=2)
    ds.av.reset_unusable_repos()

    result = ds.run_sweep(
        [_record("m-1", "wiki/gone.md", OLD)], as_of=FIXED_NOW,
    )
    assert result["unusable_repos"] == [str(broken)]

    row = ds.trend_line(result, as_of=FIXED_NOW)
    assert row["unusable"] == [str(broken)]
    assert row["repos"] == 2, "the discovered count is unchanged by exclusion"
    rendered = ds._render(row)
    assert "Repositories EXCLUDED (1)" in rendered
    assert str(broken) in rendered


def test_a_clean_sweep_records_no_exclusions(tmp_path, monkeypatch) -> None:
    """The control: nothing excluded, nothing to report."""
    good = _init_repo(tmp_path / "good", "wiki/notes.md")
    _pin_repos(monkeypatch, [good], discovered=1)
    ds.av.reset_unusable_repos()
    row = ds.trend_line(
        ds.run_sweep([_record("m-1", "wiki/notes.md", OLD)], as_of=FIXED_NOW),
        as_of=FIXED_NOW,
    )
    assert row["unusable"] == []
    assert "EXCLUDED" not in ds._render(row)
