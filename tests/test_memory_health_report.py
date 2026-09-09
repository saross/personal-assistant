"""
Unit tests for scripts/memory-health-report.py.

Covers the pure compute functions (corpus composition, growth windows,
archival aggregation, anchor health, confab-log parsing, and the Tier-C
classification) without touching PostgreSQL or git — Tier-C's resolvers are
injected as fakes, mirroring the production wiring.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Hyphenated filename → import via importlib.
_path = Path(__file__).parent.parent / "scripts" / "memory-health-report.py"
_spec = importlib.util.spec_from_file_location("memory_health_report", _path)
mhr = importlib.util.module_from_spec(_spec)
sys.modules["memory_health_report"] = mhr
_spec.loader.exec_module(mhr)

NOW = datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc)


def _rec(**kw):
    """Minimal record with sensible defaults."""
    base = {
        "id": kw.pop("id", "x"),
        "category": kw.pop("category", "progress"),
        "source": kw.pop("source", "extraction"),
        "created_at": kw.pop("created_at", NOW.isoformat()),
    }
    base.update(kw)
    return base


class TestSummariseCorpus:
    def test_counts_and_breakdowns(self) -> None:
        records = [
            _rec(id="a", category="decision", source="manual"),
            _rec(id="b", category="progress", source="extraction"),
            _rec(id="c", category="decision", source="extraction"),
        ]
        out = mhr.summarise_corpus(records)
        assert out["total_records"] == 3
        assert out["distinct_ids"] == 3
        assert out["by_category"]["decision"] == 2
        assert out["by_source"]["extraction"] == 2
        assert out["duplicate_id_groups"] == 0

    def test_duplicate_id_tripwire(self) -> None:
        records = [_rec(id="dup"), _rec(id="dup"), _rec(id="dup"), _rec(id="solo")]
        out = mhr.summarise_corpus(records)
        assert out["distinct_ids"] == 2
        assert out["duplicate_id_groups"] == 1
        assert out["duplicate_id_excess_lines"] == 2  # 3 copies → 2 excess

    def test_missing_id_counted(self) -> None:
        out = mhr.summarise_corpus([{"category": "progress"}, _rec(id="a")])
        assert out["records_without_id"] == 1
        assert out["distinct_ids"] == 1


class TestGrowthWindows:
    def test_window_membership(self) -> None:
        records = [
            _rec(created_at=(NOW - timedelta(hours=2)).isoformat()),    # in 1d/7d/30d
            _rec(created_at=(NOW - timedelta(days=3)).isoformat()),     # in 7d/30d
            _rec(created_at=(NOW - timedelta(days=20)).isoformat()),    # in 30d only
            _rec(created_at=(NOW - timedelta(days=90)).isoformat()),    # in none
        ]
        out = mhr.growth_windows(records, NOW)
        assert out["created_last_1d"] == 1
        assert out["created_last_7d"] == 2
        assert out["created_last_30d"] == 3

    def test_unparseable_created_at_ignored(self) -> None:
        out = mhr.growth_windows([_rec(created_at="not-a-date")], NOW)
        assert out["created_last_30d"] == 0


class TestArchivalSummary:
    def test_aggregates_runs(self) -> None:
        lines = [
            '{"run_at": "2026-06-02T06:09:26Z", "total": 4094, "counts": {"progress": 4094}}',
            '{"run_at": "2026-06-04T04:20:23Z", "total": 158, "counts": {"progress": 61, "context": 32}}',
        ]
        out = mhr.archival_summary(lines)
        assert out["archival_runs"] == 2
        assert out["total_archived"] == 4252
        assert out["archived_by_category"]["progress"] == 4155
        assert out["last_run_at"] == "2026-06-04T04:20:23Z"

    def test_empty_log(self) -> None:
        out = mhr.archival_summary([])
        assert out["total_archived"] == 0
        assert out["last_run_at"] is None


class TestAnchorHealth:
    def test_anchored_fraction_and_verified(self) -> None:
        records = [
            _rec(anchors=[{"type": "file", "ref": "scripts/foo.py"}], verified="true"),
            _rec(anchors=[{"type": "file", "ref": "scripts/bar.py"}], verified="false"),
            _rec(anchors=[{"type": "file", "ref": "scripts/baz.py"}], verified=None),
            _rec(),  # unanchored
        ]
        out = mhr.anchor_health(records)
        assert out["anchored"] == 3
        assert out["unanchored"] == 1
        assert out["anchored_pct"] == 75.0
        assert out["verified_breakdown"]["true"] == 1
        assert out["verified_breakdown"]["false"] == 1
        assert out["verified_breakdown"]["pending"] == 1  # None → pending

    def test_malformed_anchor_counted(self) -> None:
        # A commit anchor whose ref is not a hash is the documented malformed
        # case (wellformed_anchor → False); a real file path is well-formed.
        records = [
            _rec(anchors=[
                {"type": "commit", "ref": "not-a-real-hash"},     # malformed
                {"type": "file", "ref": "scripts/foo.py"},        # ok
            ]),
        ]
        out = mhr.anchor_health(records)
        assert out["malformed_anchors"] == 1
        assert out["records_with_malformed_anchor"] == 1


class TestParseConfabLog:
    def test_verifier_rate_vs_manual(self) -> None:
        lines = [
            # verifier row (checked>0) → contributes to the rate
            "2026-06-04T04:48Z\tsource=data-profile-verifier\tdeliverable=d\t"
            "checked=4\tflagged=2\tconfab=1\tkinds=confabulation,stale_count\tdetail=-",
            # manual row (checked=0) → absolute count only, excluded from rate
            "2026-06-03T05:08Z\tsource=self-catch\tdeliverable=g\t"
            "checked=0\tflagged=1\tconfab=1\tkinds=path\tdetail=x",
        ]
        out = mhr.parse_confab_log(lines)
        assert out["verifier_checked"] == 4
        assert out["verifier_flagged"] == 2
        assert out["verifier_flag_rate"] == 0.5      # 2/4, manual NOT folded in
        assert out["manual_flagged"] == 1
        assert out["flagged_by_kind"]["confabulation"] == 1
        assert out["flagged_by_kind"]["path"] == 1

    def test_no_verifier_rows_gives_none_rate(self) -> None:
        lines = [
            "ts\tsource=self-catch\tchecked=0\tflagged=1\tconfab=0\tkinds=path\tdetail=-",
        ]
        out = mhr.parse_confab_log(lines)
        assert out["verifier_flag_rate"] is None
        assert out["manual_flagged"] == 1

    def test_ignores_non_metric_lines(self) -> None:
        out = mhr.parse_confab_log(["", "garbage line with no fields", "  "])
        assert out["rows"] == 0


class TestTierCAudit:
    """Classification logic with injected (fake) resolvers — no git."""

    def test_fail_rate_and_recovery_split(self) -> None:
        records = [
            # in window, all anchors resolve → true
            _rec(id="ok", anchors=[{"type": "file", "ref": "real/a.py"}]),
            # in window, one file anchor fails-and-absent
            _rec(id="bad-absent", anchors=[{"type": "file", "ref": "gone/x.py"}]),
            # in window, one file anchor fails-but-recoverable
            _rec(id="bad-recov", anchors=[{"type": "file", "ref": "moved/y.py"}]),
            # out of window → ignored
            _rec(id="old", anchors=[{"type": "file", "ref": "gone/x.py"}],
                 created_at=(NOW - timedelta(days=60)).isoformat()),
        ]
        # Fakes: a record is "false" iff it holds a known-bad ref.
        bad = {"gone/x.py", "moved/y.py"}

        def verify(rec):
            return "false" if any(a["ref"] in bad for a in rec["anchors"]) else "true"

        def verify_file_ref(ref):
            return "false" if ref in bad else "true"

        def recover(ref):
            return ("recoverable", "real/y.py") if ref == "moved/y.py" else ("absent", None)

        out = mhr.tier_c_audit(
            records, as_of=NOW, days=30,
            verify=verify, verify_file_ref=verify_file_ref, recover=recover,
        )
        assert out["anchored_in_window"] == 3            # the 60-day-old one excluded
        assert out["fail_count"] == 2
        assert out["fail_rate_pct"] == round(100 * 2 / 3, 1)
        assert out["failing_file_ref_recovery"]["absent"] == 1
        assert out["failing_file_ref_recovery"]["recoverable"] == 1

    def test_resolving_anchor_on_failing_record_not_classified(self) -> None:
        """A file anchor that itself resolves must NOT enter the split, even
        when its record failed because of a different (commit) anchor."""
        records = [
            _rec(id="mixed", anchors=[
                {"type": "file", "ref": "real/a.py"},       # resolves fine
                {"type": "commit", "ref": "deadbeef"},      # this is what fails
            ]),
        ]

        def verify(rec):
            return "false"  # record fails (the commit anchor)

        def verify_file_ref(ref):
            return "true"   # the file anchor resolves

        def recover(ref):
            return ("absent", None)

        out = mhr.tier_c_audit(
            records, as_of=NOW, days=30,
            verify=verify, verify_file_ref=verify_file_ref, recover=recover,
        )
        assert out["fail_count"] == 1
        # The resolving file anchor is excluded → empty split.
        assert out["failing_file_ref_recovery"] == {}


class TestSurfacingSection:
    """§G — earned-utility surfacing summary (item 16)."""

    def test_empty_stats(self) -> None:
        out = mhr.surfacing_section({})
        assert out["distinct_memories_surfaced"] == 0
        assert out["top"] == []

    def test_summary_and_top(self) -> None:
        stats = {
            "a": {"active_retrievals": 3, "digest_exposures": 1,
                  "last_active_at": "t", "last_any_at": "t"},
            "b": {"active_retrievals": 0, "digest_exposures": 5,
                  "last_active_at": None, "last_any_at": "t"},
        }
        out = mhr.surfacing_section(stats)
        assert out["distinct_memories_surfaced"] == 2
        assert out["memories_ever_actively_retrieved"] == 1  # only 'a'
        assert out["total_active_retrievals"] == 3
        assert out["total_digest_exposures"] == 6
        # 'a' (active 3) ranks above 'b' (active 0).
        assert out["top"][0]["id"] == "a"
        assert out["top"][0]["active"] == 3


class TestDriftTrend:
    """§H — anchor drift trend parsing (item 8)."""

    def test_no_runs(self) -> None:
        assert mhr.drift_trend([]) == {"runs": 0, "latest": None, "history": []}
        assert mhr.drift_trend(["", "  "])["runs"] == 0

    def test_parses_and_keeps_latest_plus_history(self) -> None:
        lines = [
            '{"run_at": "2026-06-01T00:00:00+00:00", "fail_pct": 18.0, "total_anchored": 1500, "fail": 270}',
            'GARBAGE LINE',
            '{"run_at": "2026-06-06T00:00:00+00:00", "fail_pct": 18.4, "total_anchored": 1616, "fail": 297}',
        ]
        out = mhr.drift_trend(lines)
        assert out["runs"] == 2  # malformed line skipped
        assert out["latest"]["fail_pct"] == 18.4
        assert [h["fail_pct"] for h in out["history"]] == [18.0, 18.4]

    def test_history_capped_at_8(self) -> None:
        lines = [
            f'{{"run_at": "2026-06-{i:02d}T00:00:00+00:00", "fail_pct": {i}.0,'
            f' "total_anchored": 1000, "fail": {i}}}'
            for i in range(1, 13)
        ]
        out = mhr.drift_trend(lines)
        assert out["runs"] == 12
        assert len(out["history"]) == 8  # last 8 only
        assert out["history"][-1]["fail_pct"] == 12.0


def test_surfacing_section_recency_tiebreak() -> None:
    """Equal active+digest counts → more-recently-surfaced ranks first (reproducible)."""
    stats = {
        "older": {"active_retrievals": 1, "digest_exposures": 0,
                  "last_active_at": "x", "last_any_at": "2026-06-01T00:00:00+00:00"},
        "newer": {"active_retrievals": 1, "digest_exposures": 0,
                  "last_active_at": "x", "last_any_at": "2026-06-06T00:00:00+00:00"},
    }
    out = mhr.surfacing_section(stats)
    assert out["top"][0]["id"] == "newer"


# ---------------------------------------------------------------------------
# Tenth re-audit, L4 — /memory-health and the gate read one file, so they
# must read it the same way
# ---------------------------------------------------------------------------


class TestTheQuarantineCountAgreesWithTheGate:
    """
    Two counts of the same file that disagree send the operator looking
    for a row one of them cannot see. The report and the session-start
    gate now share the sync pipeline's parser.
    """

    def _both(self, monkeypatch, tmp_path, body: str):
        """Count one quarantine file through the report and the gate."""
        import sys

        sys.path.insert(
            0, str(Path(__file__).resolve().parent.parent / "scripts"),
        )
        import _sync_cursor

        path = tmp_path / "quarantine-postgres-drops.jsonl"
        path.write_text(body, encoding="utf-8")
        monkeypatch.setattr(mhr, "QUARANTINE_FILE", path)
        return mhr.quarantine_count(), _sync_cursor.count_quarantine_entries(
            path,
        )

    @pytest.mark.parametrize("label,body", [
        ("complete rows", '{"reason": "a"}\n{"reason": "b"}\n'),
        ("last row unterminated", '{"reason": "a"}\n{"reason": "b"}'),
        ("damaged last row", '{"reason": "a"}\n{"reason": "b'),
        ("blank lines about", '\n{"reason": "a"}\n\n   \n'),
        ("a non-object line", '{"reason": "a"}\n[1, 2]\n'),
        ("nothing at all", ""),
    ])
    def test_the_two_counts_are_the_same(
        self, monkeypatch, tmp_path, label, body,
    ):
        """
        The mutation this kills: counting non-blank lines here instead of
        parsing — "damaged last row" and "a non-object line" then report
        one row more than the gate can see.
        """
        reported, gated = self._both(monkeypatch, tmp_path, body)
        assert reported == gated, (
            f"{label}: /memory-health says {reported}, the gate says {gated}"
        )

    def test_an_absent_file_counts_zero(self, monkeypatch, tmp_path):
        """
        No file is the ordinary state of a machine whose sync has never
        dropped a row: ``sync-to-postgres.py`` creates it on the first drop.
        Reporting a fault here would leave the report permanently red on a
        healthy machine, and an alarm that is always on is not an alarm.

        Kills the mutation that folds "absent" into the unreadable branch.
        """
        monkeypatch.setattr(
            mhr, "QUARANTINE_FILE", tmp_path / "not-there.jsonl",
        )
        assert mhr.quarantine_state() == (0, mhr.QUARANTINE_ABSENT)
        assert mhr.quarantine_count() == 0

    def test_a_file_that_exists_but_cannot_be_decoded_is_unknown(
        self, monkeypatch, tmp_path,
    ):
        """
        The state AN8 was about: the file is THERE and we cannot read it, so
        we do not know whether it holds nothing or a hundred dropped rows.

        Kills the mutation ``return 0 if entries is None else len(entries)``,
        which printed "0 (expect 0)" over exactly that file.
        """
        damaged = tmp_path / "quarantine-postgres-drops.jsonl"
        damaged.write_bytes(b"\xff\xfe{\"reason\": \"a\"}\n")
        monkeypatch.setattr(mhr, "QUARANTINE_FILE", damaged)
        assert mhr.quarantine_state() == (None, mhr.QUARANTINE_UNREADABLE)
        assert mhr.quarantine_count() is None

    def test_a_path_that_cannot_be_opened_is_unknown(
        self, monkeypatch, tmp_path,
    ):
        """A directory where the file should be is not "no quarantined rows"."""
        blocked = tmp_path / "quarantine-postgres-drops.jsonl"
        blocked.mkdir()
        monkeypatch.setattr(mhr, "QUARANTINE_FILE", blocked)
        assert mhr.quarantine_state() == (None, mhr.QUARANTINE_UNREADABLE)

    def test_a_readable_file_reports_its_real_count(
        self, monkeypatch, tmp_path,
    ):
        """The third state, for completeness: read it and say what is there."""
        path = tmp_path / "quarantine-postgres-drops.jsonl"
        path.write_text(
            '{"reason": "a"}\n{"reason": "b"}\n', encoding="utf-8",
        )
        monkeypatch.setattr(mhr, "QUARANTINE_FILE", path)
        assert mhr.quarantine_state() == (2, mhr.QUARANTINE_READ)


# ============================================================================
# build_report / render_report / main, end to end (findings ANT3 / ANT4)
# ============================================================================

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fake_audit_pg import FakeDatabase, connect_factory  # noqa: E402


def _anchored(**kw) -> dict:
    """A synthetic record carrying one resolvable file anchor."""
    return _rec(anchors=[{"type": "file", "ref": "wiki/notes.md"}], **kw)


@pytest.fixture
def report_paths(tmp_path, monkeypatch):
    """Pin every path constant the report reads into a tmp directory.

    Returns the directory. Nothing in these tests touches the operator's
    corpus, logs, archive, or quarantine file.
    """
    root = tmp_path / "store"
    (root / "archive").mkdir(parents=True)
    (root / "logs").mkdir()
    for name, value in [
        ("MEMORIES_FILE", root / "memories.jsonl"),
        ("ARCHIVE_DIR", root / "archive"),
        ("ARCHIVE_RUNS_LOG", root / "archive" / "archive-runs.jsonl"),
        ("QUARANTINE_FILE", root / "quarantine-postgres-drops.jsonl"),
        ("CONFAB_LOG", root / "logs" / "confab-flags.log"),
        ("SURFACED_LOG", root / "logs" / "surfaced.log"),
        ("DRIFT_LOG", root / "logs" / "drift-sweep.jsonl"),
    ]:
        monkeypatch.setattr(mhr, name, value)
    (root / "quarantine-postgres-drops.jsonl").write_text("", encoding="utf-8")
    return root


@pytest.fixture
def fake_pg(monkeypatch):
    """Patch psycopg2.connect with a fake serving one seeded database."""
    import psycopg2

    def install(db: FakeDatabase):
        conn, connect = connect_factory(db)
        monkeypatch.setattr(psycopg2, "connect", connect)
        return conn

    return install


def _write_corpus(root: Path, records: list[dict]) -> None:
    """Write the synthetic canonical JSONL the report will read."""
    import json as _json
    (root / "memories.jsonl").write_text(
        "".join(_json.dumps(r) + "\n" for r in records), encoding="utf-8",
    )


def _build(**kw):
    """Call build_report with the test defaults."""
    import logging
    kw.setdefault("run_tier_c", False)
    return mhr.build_report(
        as_of=NOW, tier_c_days=30,
        logger=logging.getLogger("test-mhr"), **kw
    )


class TestBuildReportVerdict:
    """What makes the report FAIL, and what the exit code then is."""

    def test_a_clean_corpus_passes(self, report_paths, fake_pg) -> None:
        _write_corpus(report_paths, [_anchored(id="m-1"), _anchored(id="m-2")])
        fake_pg(FakeDatabase(memories=[
            {"id": "m-1", "is_active": True}, {"id": "m-2", "is_active": True},
        ]))
        report, clean = _build()
        assert clean is True
        assert report["integrity"]["quarantine_count"] == 0
        assert "MEMORY-HEALTH REPORT" in "\n".join(mhr.render_report(report))

    def test_a_duplicate_id_fails(self, report_paths, fake_pg) -> None:
        """Kills the mutation dropping the dup-id term from ``clean``."""
        _write_corpus(report_paths, [_anchored(id="m-1"), _anchored(id="m-1")])
        fake_pg(FakeDatabase(memories=[{"id": "m-1", "is_active": True}]))
        report, clean = _build()
        assert report["corpus"]["duplicate_id_groups"] == 1
        assert clean is False

    def test_a_quarantined_row_fails(self, report_paths, fake_pg) -> None:
        """Kills the mutation zeroing the quarantine count in the report."""
        _write_corpus(report_paths, [_anchored(id="m-1")])
        (report_paths / "quarantine-postgres-drops.jsonl").write_text(
            '{"reason": "a dropped row"}\n', encoding="utf-8",
        )
        fake_pg(FakeDatabase(memories=[{"id": "m-1", "is_active": True}]))
        report, clean = _build()
        assert report["integrity"]["quarantine_count"] == 1
        assert clean is False

    def test_an_unreadable_quarantine_file_is_unknown_and_fails(
        self, report_paths, fake_pg, monkeypatch,
    ) -> None:
        """AN8: a file we cannot read must not print "0 (expect 0)" and PASS."""
        _write_corpus(report_paths, [_anchored(id="m-1")])
        damaged = report_paths / "quarantine-postgres-drops.jsonl"
        damaged.write_bytes(b"\xff\xfe{\"reason\": \"a\"}\n")
        fake_pg(FakeDatabase(memories=[{"id": "m-1", "is_active": True}]))
        report, clean = _build()
        assert report["integrity"]["quarantine_count"] is None
        assert report["integrity"]["quarantine_state"] == mhr.QUARANTINE_UNREADABLE
        assert clean is False
        rendered = "\n".join(mhr.render_report(report))
        assert "UNKNOWN — quarantine file present but unreadable" in rendered
        assert "overall                 : FAIL" in rendered

    def test_an_absent_quarantine_file_passes_and_says_so(
        self, report_paths, fake_pg, monkeypatch,
    ) -> None:
        """The state of this machine today: no file, nothing ever dropped.

        Kills the mutation that fails the verdict on absence — which would
        make /memory-health permanently red on a healthy machine.
        """
        _write_corpus(report_paths, [_anchored(id="m-1")])
        monkeypatch.setattr(
            mhr, "QUARANTINE_FILE", report_paths / "not-there.jsonl",
        )
        fake_pg(FakeDatabase(memories=[{"id": "m-1", "is_active": True}]))
        report, clean = _build()
        assert report["integrity"]["quarantine_count"] == 0
        assert report["integrity"]["quarantine_state"] == mhr.QUARANTINE_ABSENT
        assert clean is True
        rendered = "\n".join(mhr.render_report(report))
        assert "0 (expect 0; never written on this machine)" in rendered
        assert "overall                 : PASS" in rendered

    def test_an_archive_leak_fails(self, report_paths, fake_pg) -> None:
        """An archived id still is_active=TRUE is a recall leak.

        Kills the mutation dropping the archive-leak term from ``clean``.
        """
        _write_corpus(report_paths, [_anchored(id="m-1")])
        (report_paths / "archive" / "memories-archive-2031-02.jsonl").write_text(
            '{"id": "old-1"}\n', encoding="utf-8",
        )
        fake_pg(FakeDatabase(memories=[
            {"id": "m-1", "is_active": True},
            {"id": "old-1", "content": "x", "is_active": True},
        ]))
        report, clean = _build()
        assert report["integrity"]["archive_parity"]["leaked_active"] == 1
        assert clean is False


class TestMainExitCodes:
    """The documented exit codes (module docstring lines 23-27)."""

    def _main(self, monkeypatch, argv: list[str] | None = None) -> int:
        monkeypatch.setattr(
            sys, "argv", ["memory-health-report.py"] + (argv or []),
        )
        return mhr.main()

    def test_clean_exits_zero(
        self, report_paths, fake_pg, monkeypatch, capsys,
    ) -> None:
        _write_corpus(report_paths, [_anchored(id="m-1")])
        fake_pg(FakeDatabase(memories=[{"id": "m-1", "is_active": True}]))
        assert self._main(monkeypatch) == 0
        assert "[A] Corpus size" in capsys.readouterr().out

    def test_failed_integrity_exits_one(
        self, report_paths, fake_pg, monkeypatch, capsys,
    ) -> None:
        """Kills the mutation returning 0 regardless of the verdict."""
        _write_corpus(report_paths, [_anchored(id="m-1"), _anchored(id="m-1")])
        fake_pg(FakeDatabase(memories=[{"id": "m-1", "is_active": True}]))
        assert self._main(monkeypatch) == 1
        assert "FAIL" in capsys.readouterr().out

    def test_a_missing_corpus_exits_two(
        self, report_paths, monkeypatch, capsys,
    ) -> None:
        """Kills the mutation dropping the missing-corpus guard."""
        assert self._main(monkeypatch) == 2
        assert "[A] Corpus size" not in capsys.readouterr().out

    def test_the_report_survives_a_schema_bump(
        self, report_paths, fake_pg, monkeypatch, capsys,
    ) -> None:
        """AN4: a schema mismatch must not cost the whole report.

        Kills the mutation restoring ``sys.exit(2)`` in the PG readers: the
        eight non-PG sections need no database at all.
        """
        _write_corpus(report_paths, [_anchored(id="m-1")])
        fake_pg(FakeDatabase(memories=[], schema_version="999"))
        assert self._main(monkeypatch) == 0
        out = capsys.readouterr().out
        assert "[A] Corpus size" in out
        assert "(unavailable — skipped)" in out


class TestPgSnapshotSql:
    """The recall invariant (P2) has to be read off the right relation."""

    def test_the_view_and_the_flag_are_what_is_queried(
        self, report_paths, fake_pg,
    ) -> None:
        """Kills ``FROM active_memories`` -> ``FROM memories`` and
        ``is_active IS TRUE`` -> ``IS NOT NULL``: the seeded rows give each
        of the four counts a different value.
        """
        import logging
        conn = fake_pg(FakeDatabase(memories=[
            {"id": "a", "is_active": True},
            {"id": "b", "is_active": False},
            {"id": "c", "is_active": None},
        ]))
        snap = mhr.pg_snapshot(logging.getLogger("test-mhr"))
        assert snap["total_rows"] == 3
        assert snap["is_active_true"] == 1
        assert snap["is_active_false"] == 1
        # The view is ``WHERE is_active = TRUE`` (schema.sql:273), and SQL
        # three-valued logic excludes the NULL row — so the view count
        # tracks is_active_true, not "everything not false" (finding M5).
        assert snap["active_memories_view"] == 1
        assert "SELECT COUNT(*) FROM active_memories" in conn.executed_sql
        assert (
            "SELECT COUNT(*) FROM memories WHERE is_active IS TRUE"
            in conn.executed_sql
        )

    def test_the_connection_is_read_only_and_time_limited(
        self, report_paths, fake_pg,
    ) -> None:
        """AN14: a lock-contended database must not hang /memory-health.

        The VALUE is asserted, not the prefix: PostgreSQL reads
        ``statement_timeout = '0'`` as "no limit", so a mutation to "0"
        passes a prefix check while removing the protection entirely
        (finding M4).
        """
        import logging
        conn = fake_pg(FakeDatabase(memories=[{"id": "a", "is_active": True}]))
        mhr.pg_snapshot(logging.getLogger("test-mhr"))
        assert conn.readonly is True
        assert conn.executed_sql[0] == (
            "SET LOCAL statement_timeout = '15s'"
        ), "the timeout must be the FIRST statement on the connection"
        assert mhr.PG_STATEMENT_TIMEOUT not in ("0", 0, "", None)
        assert conn.rollbacks >= 1

    def test_the_timeout_precedes_the_schema_query(
        self, report_paths, fake_pg,
    ) -> None:
        """The schema check is itself a SELECT against a lockable table.

        Kills the mutation moving the SET after assert_schema_version: the
        one query that runs on every single invocation is then the only
        unprotected one.
        """
        import logging
        conn = fake_pg(FakeDatabase(memories=[{"id": "a", "is_active": True}]))
        mhr.pg_snapshot(logging.getLogger("test-mhr"))
        timeout_at = conn.executed_sql.index(
            "SET LOCAL statement_timeout = '15s'"
        )
        schema_at = next(
            i for i, sql in enumerate(conn.executed_sql) if "FROM meta" in sql
        )
        assert timeout_at < schema_at


class TestSectionsFilterInactiveRecords:
    """[A] labels the two populations; the rest describe the active one."""

    def test_growth_and_anchors_exclude_soft_deleted_records(
        self, report_paths, fake_pg,
    ) -> None:
        """Kills the mutation running the sections over every line.

        A ``/forget``-ed record is still in the JSONL and still in PostgreSQL,
        so the membership tripwires must see it — but recall cannot return
        it, so the composition sections must not count it (finding AN16).
        """
        _write_corpus(report_paths, [
            _anchored(id="m-1"),
            _anchored(id="m-2", is_active=False),
        ])
        fake_pg(FakeDatabase(memories=[
            {"id": "m-1", "is_active": True}, {"id": "m-2", "is_active": False},
        ]))
        report, _clean = _build()
        assert report["corpus"]["total_records"] == 2
        assert report["corpus"]["active_records"] == 1
        assert report["anchors"]["total_records"] == 1
        assert report["growth"]["created_last_1d"] == 1
        rendered = "\n".join(mhr.render_report(report))
        assert "2 all / 1 active" in rendered
        assert "[B] Growth & churn  (active records only)" in rendered


class TestAnchoredCountsOnlyVerifiableAnchors:
    """[C]'s headline number must mean what it says (finding AN5)."""

    def test_zotero_only_records_are_not_counted_as_anchored(self) -> None:
        """Kills the mutation counting any truthy ``anchors`` as anchored."""
        out = mhr.anchor_health([
            _rec(id="a", anchors=[{"type": "file", "ref": "wiki/a.md"}]),
            _rec(id="b", anchors=[{"type": "zotero", "ref": "ABCD1234"}]),
            _rec(id="c", anchors=[{"type": "url", "ref": "https://example.org"}]),
        ])
        assert out["anchored"] == 1
        assert out["anchored_any"] == 3
        assert out["anchored_pct"] == round(100 / 3, 1)

    def test_a_string_anchors_field_is_one_malformed_record(self) -> None:
        """Kills the mutation iterating a non-list ``anchors`` per character."""
        out = mhr.anchor_health([_rec(id="a", anchors="wiki/notes.md")])
        assert out["malformed_anchors"] == 1
        assert out["records_with_malformed_anchor"] == 1
        assert out["anchored"] == 0

    def test_verified_is_case_folded_and_stale_kept(self) -> None:
        """"stale" is a documented value; TRUE and true are one bucket."""
        out = mhr.anchor_health([
            _rec(id="a", anchors=[{"type": "file", "ref": "a.md"}], verified=True),
            _rec(id="b", anchors=[{"type": "file", "ref": "b.md"}],
                 verified="TRUE"),
            _rec(id="c", anchors=[{"type": "file", "ref": "c.md"}],
                 verified="stale"),
        ])
        assert out["verified_breakdown"] == {"true": 2, "stale": 1}


class TestUndatedRecordsStayInTheBackSet:
    """A record with no created_at must not age out silently (AN6)."""

    def test_an_undated_anchored_record_is_considered(self) -> None:
        """Kills ``if created is None or created <= cutoff: continue``."""
        records = [
            _rec(id="dated", anchors=[{"type": "file", "ref": "a.md"}]),
            {"id": "undated", "anchors": [{"type": "file", "ref": "b.md"}]},
            _rec(id="unparseable", anchors=[{"type": "file", "ref": "c.md"}],
                 created_at="not a date"),
        ]
        out = mhr.tier_c_audit(
            records, as_of=NOW, days=30,
            verify=lambda rec: "false",
            verify_file_ref=lambda ref: "false",
            recover=lambda ref: ("absent", None),
        )
        assert out["anchored_in_window"] == 3
        assert out["undated_included"] == 2
        assert out["fail_count"] == 3


class TestSurfacingTopIsCheckedAgainstTheCorpus:
    """A retrieved id that no longer exists is reported, not shown as live."""

    def test_an_id_absent_from_the_corpus_is_flagged(self) -> None:
        """Kills the mutation dropping the membership check (finding AN17)."""
        stats = {
            "gone-1": {"active_retrievals": 9, "digest_exposures": 0,
                       "last_any_at": "2031-01-02"},
            "here-1": {"active_retrievals": 4, "digest_exposures": 0,
                       "last_any_at": "2031-01-03"},
        }
        out = mhr.surfacing_section(stats, {"here-1"})
        assert out["top_not_in_corpus"] == 1
        assert [t["in_corpus"] for t in out["top"]] == [False, True]

    def test_the_top_list_holds_five(self) -> None:
        """Kills the ``[:5]`` -> ``[:1]`` mutation."""
        stats = {
            f"m-{i}": {"active_retrievals": i, "digest_exposures": 0,
                       "last_any_at": "2031-01-01"}
            for i in range(8)
        }
        out = mhr.surfacing_section(stats, set(stats))
        assert len(out["top"]) == 5
        assert out["top"][0]["id"] == "m-7"


class TestTheSurfacedLogOverrideIsHonoured:
    """M-c: the reader resolves the path the writer would have used."""

    def test_pa_surfaced_log_is_read(
        self, report_paths, fake_pg, monkeypatch,
    ) -> None:
        """Kills the mutation binding SURFACED_LOG at import only.

        With the override set, section [G] reported "no surfacings logged
        yet" while the writer was appending to the pinned file.
        """
        _write_corpus(report_paths, [_anchored(id="m-1")])
        pinned = report_paths / "logs" / "pinned-surfaced.log"
        pinned.write_text(
            "2031-01-02T03:04:05+00:00\tid=m-1\tpath=recall\trank=1\t"
            "session=s-1\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("PA_SURFACED_LOG", str(pinned))
        fake_pg(FakeDatabase(memories=[{"id": "m-1", "is_active": True}]))
        report, _clean = _build()
        assert report["surfacing"]["distinct_memories_surfaced"] == 1
        assert report["surfacing"]["top"][0]["id"] == "m-1"


# ============================================================================
# Timestamp handling and the loader's narrow except (findings ANT-L3 / L4)
# ============================================================================


class TestGrowthWindowBoundaries:
    """What counts as "in the last N days", exactly."""

    def test_a_record_exactly_on_the_cutoff_is_outside(self) -> None:
        """Kills the ``>`` -> ``>=`` boundary flip.

        The window is trailing and half-open: a record created exactly N days
        ago is N days old, not within the last N.
        """
        on_cutoff = (NOW - timedelta(days=7)).isoformat()
        just_inside = (NOW - timedelta(days=7) + timedelta(seconds=1)).isoformat()
        out = mhr.growth_windows(
            [_rec(id="a", created_at=on_cutoff),
             _rec(id="b", created_at=just_inside)],
            NOW, windows_days=(7,),
        )
        assert out["created_last_7d"] == 1

    def test_a_naive_timestamp_is_read_as_utc(self) -> None:
        """Kills the mutation rejecting tz-naive timestamps.

        The corpus carries them (one live record at the audit); dropping them
        would silently understate growth rather than say anything.
        """
        naive = NOW.replace(tzinfo=None).isoformat()
        assert mhr._parse_iso(naive) == NOW
        out = mhr.growth_windows([_rec(id="a", created_at=naive)], NOW)
        assert out["created_last_1d"] == 1

    def test_an_unparseable_date_is_not_counted_as_recent(self) -> None:
        """Kills the mutation counting unparseable dates into every window."""
        out = mhr.growth_windows(
            [_rec(id="a", created_at="last Tuesday"),
             _rec(id="b", created_at=None)],
            NOW,
        )
        assert out == {"created_last_1d": 0, "created_last_7d": 0,
                       "created_last_30d": 0}


class TestLoadRecordsSkipsOnlyBadJson:
    """The loader's except must stay narrow (finding ANT-L4)."""

    def test_a_malformed_line_is_skipped(self, tmp_path) -> None:
        path = tmp_path / "memories.jsonl"
        path.write_text('{"id": "a"}\n{broken\n{"id": "b"}\n', encoding="utf-8")
        assert [r["id"] for r in mhr.load_records(path)] == ["a", "b"]

    def test_any_other_error_propagates(self, tmp_path, monkeypatch) -> None:
        """Kills the mutation widening the except to bare ``Exception``.

        A JSONDecodeError is operational data we route around; anything else
        is a bug or an interpreter-level problem, and swallowing it would
        report a truncated corpus as a complete one.
        """
        path = tmp_path / "memories.jsonl"
        path.write_text('{"id": "a"}\n', encoding="utf-8")

        def boom(_text):
            raise RuntimeError("not a decode error")

        monkeypatch.setattr(mhr.json, "loads", boom)
        with pytest.raises(RuntimeError):
            mhr.load_records(path)


class TestTierCSurvivesADiscoveryFailure:
    """[F] is one section of nine; the other eight need no repositories."""

    def test_the_report_still_prints_when_discovery_is_empty(
        self, report_paths, fake_pg, monkeypatch, capsys,
    ) -> None:
        """AN4's defect, reintroduced on the tier-C path (round 4f-3, M1).

        Kills the mutation removing the try/except around broad_repo_set:
        --tier-c on a machine with no discoverable repositories tracebacks
        out of main() with stdout EMPTY, discarding sections [A] to [H] that
        were already built.
        """
        _write_corpus(report_paths, [_anchored(id="m-1")])
        fake_pg(FakeDatabase(memories=[{"id": "m-1", "is_active": True}]))

        def _raise() -> list:
            raise mhr.ta.RepoSetUnavailable("no git repositories discovered")

        monkeypatch.setattr(mhr.ta, "broad_repo_set", _raise)
        monkeypatch.setattr(
            sys, "argv", ["memory-health-report.py", "--tier-c"],
        )
        rc = mhr.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "[A] Corpus size" in out
        assert "[H] Anchor drift trend" in out
        assert "[F] Tier C — skipped: repository discovery failed" in out

    def test_build_report_omits_the_tier_c_section(
        self, report_paths, fake_pg, monkeypatch,
    ) -> None:
        """The section is absent, not zero-filled: we did not measure it."""
        _write_corpus(report_paths, [_anchored(id="m-1")])
        fake_pg(FakeDatabase(memories=[{"id": "m-1", "is_active": True}]))

        def _raise() -> list:
            raise mhr.ta.RepoSetUnavailable("no git repositories discovered")

        monkeypatch.setattr(mhr.ta, "broad_repo_set", _raise)
        report, clean = _build(run_tier_c=True)
        assert "tier_c" not in report
        assert clean is True


class TestTheSoftDeletePredicateIsShared:
    """One definition of "forgotten", not one per reader (finding M2)."""

    def test_a_string_false_is_not_active(
        self, report_paths, fake_pg,
    ) -> None:
        """Kills the inline ``r.get("is_active") is not False``.

        The corpus carries the JSON boolean, the string "false", the string
        "False", and a numeric 0 — ``/forget`` and the sync have written all
        of them over time. An identity test against ``False`` sees only the
        first, so a forgotten record would be counted as active here while
        fetch-memories and the digest, which use _soft_delete.is_active,
        correctly hide it.
        """
        _write_corpus(report_paths, [
            _anchored(id="m-live"),
            _anchored(id="m-bool", is_active=False),
            _anchored(id="m-str", is_active="false"),
            _anchored(id="m-caps", is_active="False"),
            _anchored(id="m-zero", is_active=0),
        ])
        fake_pg(FakeDatabase(memories=[
            {"id": "m-live", "is_active": True},
            {"id": "m-bool", "is_active": False},
            {"id": "m-str", "is_active": False},
            {"id": "m-caps", "is_active": False},
            {"id": "m-zero", "is_active": False},
        ]))
        report, _clean = _build()
        assert report["corpus"]["total_records"] == 5
        assert report["corpus"]["active_records"] == 1
        assert report["anchors"]["total_records"] == 1

    def test_the_membership_tripwire_still_sees_every_line(
        self, report_paths, fake_pg,
    ) -> None:
        """live_ids must NOT be filtered: PostgreSQL keeps forgotten rows.

        Kills the mutation that filters live_ids by is_active — every
        soft-deleted record would then look like a PostgreSQL-only orphan.
        """
        _write_corpus(report_paths, [
            _anchored(id="m-live"),
            _anchored(id="m-gone", is_active=False),
        ])
        fake_pg(FakeDatabase(memories=[
            {"id": "m-live", "is_active": True},
            {"id": "m-gone", "is_active": False},
        ]))
        report, clean = _build()
        assert report["integrity"]["only_in_postgres"] == 0
        assert report["integrity"]["only_in_canonical"] == 0
        assert clean is True


class TestTheAnchoredGapIsDescribedAccurately:
    """[C]'s explanatory clause is a measurable claim (finding M3)."""

    def test_the_sentence_covers_more_than_zotero_and_url(
        self, report_paths, fake_pg,
    ) -> None:
        """The old wording said "the rest carry only zotero/url anchors".

        Measured against the live corpus, most of that population carried
        something else entirely: `ref` and `context` anchors, `line` anchors,
        and records whose file/commit anchors are all malformed. The fixture
        below holds one of each, none of them zotero or url, so a report
        that names those two types is describing records that are not there.
        """
        _write_corpus(report_paths, [
            _anchored(id="m-ok"),
            _rec(id="m-ref", anchors=[{"type": "ref", "ref": "Obs 14"}]),
            _rec(id="m-bad-file",
                 anchors=[{"type": "file", "ref": "a scoring table (7 cells)"}]),
        ])
        fake_pg(FakeDatabase(memories=[
            {"id": mid, "is_active": True}
            for mid in ("m-ok", "m-ref", "m-bad-file")
        ]))
        report, _clean = _build()
        assert report["anchors"]["anchored"] == 1
        assert report["anchors"]["anchored_any"] == 3

        line = next(
            ln for ln in mhr.render_report(report)
            if "any anchors at all" in ln
        )
        assert "zotero/url" not in line
        assert "cannot resolve" in line
        assert "no well-formed file/commit anchor" in line


class TestTheVerdictMatchesTheDocumentedExitCodes:
    """The docstring promised a failure the expression never checked (L6)."""

    def test_a_postgres_only_row_fails_the_report(
        self, report_paths, fake_pg,
    ) -> None:
        """Kills the mutation dropping only_in_postgres from ``clean``.

        A PostgreSQL row with no canonical line is a row /recall can return
        and the corpus does not contain — the divergence audit-postgres-sync
        already fails on.
        """
        _write_corpus(report_paths, [_anchored(id="m-1")])
        fake_pg(FakeDatabase(memories=[
            {"id": "m-1", "is_active": True},
            {"id": "ghost-1", "is_active": True},
        ]))
        report, clean = _build()
        assert report["integrity"]["only_in_postgres"] == 1
        assert clean is False

    def test_the_unsynced_tail_does_not_fail_the_report(
        self, report_paths, fake_pg,
    ) -> None:
        """The control, and the reason the other direction is exempt.

        Kills a mutation that also fails on only_in_canonical: the sync cron
        drains that tail every five minutes, so /memory-health would be red
        most of the time.
        """
        _write_corpus(report_paths, [_anchored(id="m-1"), _anchored(id="m-2")])
        fake_pg(FakeDatabase(memories=[{"id": "m-1", "is_active": True}]))
        report, clean = _build()
        assert report["integrity"]["only_in_canonical"] == 1
        assert clean is True

    def test_an_unreachable_database_does_not_fail_the_report(
        self, report_paths, monkeypatch,
    ) -> None:
        """"n/a" is not a divergence — it is an absent measurement."""
        _write_corpus(report_paths, [_anchored(id="m-1")])
        monkeypatch.setattr(mhr, "pg_snapshot", lambda logger: None)
        report, clean = _build()
        assert report["integrity"]["only_in_postgres"] == "n/a"
        assert clean is True


class TestTheSurfacedTopIsCheckedAgainstTheActiveCorpus:
    """[G]'s "no longer live" branch has to be reachable (finding L7)."""

    def test_a_forgotten_id_is_reported_as_gone(
        self, report_paths, fake_pg, monkeypatch,
    ) -> None:
        """Kills the mutation passing live_ids instead of the active ids.

        surfaced.log outlives /forget, so a heavily-retrieved id can name a
        record recall will never return again. Testing membership against
        every JSONL line marked it present and the branch never fired.
        """
        _write_corpus(report_paths, [
            _anchored(id="m-live"),
            _anchored(id="m-forgotten", is_active=False),
        ])
        pinned = report_paths / "logs" / "pinned-surfaced.log"
        pinned.write_text(
            "2031-01-02T03:04:05+00:00\tid=m-forgotten\tpath=recall\trank=1\t"
            "session=s-1\n"
            "2031-01-02T03:04:06+00:00\tid=m-live\tpath=recall\trank=2\t"
            "session=s-1\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("PA_SURFACED_LOG", str(pinned))
        fake_pg(FakeDatabase(memories=[
            {"id": "m-live", "is_active": True},
            {"id": "m-forgotten", "is_active": False},
        ]))
        report, _clean = _build()
        assert report["surfacing"]["top_not_in_corpus"] == 1
        by_id = {t["id"]: t["in_corpus"] for t in report["surfacing"]["top"]}
        assert by_id == {"m-forgotten": False, "m-live": True}
        rendered = "\n".join(mhr.render_report(report))
        assert "no longer in the live corpus" in rendered


class TestTheNonListAnchorsCountIsShown:
    """A counted field nobody renders is a field nobody reads (L5)."""

    def test_the_report_names_the_non_list_anchors_records(self) -> None:
        """Kills the mutation dropping the clause from the rendered line."""
        report = {
            "generated_at": "2031-01-01T00:00:00+00:00",
            "corpus": {"total_records": 2, "distinct_ids": 2,
                       "duplicate_id_groups": 0, "duplicate_id_excess_lines": 0,
                       "by_category": {}, "by_source": {}, "active_records": 2,
                       "inactive_records": 0},
            "postgres": None,
            "growth": {}, "archival": {"total_archived": 0, "archival_runs": 0,
                                       "last_run_at": None},
            "cold_partition_records": 0,
            "anchors": {"anchored": 0, "unanchored": 1, "anchored_any": 1,
                        "anchored_pct": 0.0, "verified_breakdown": {},
                        "malformed_anchors": 1,
                        "records_with_malformed_anchor": 1,
                        "malformed_anchor_fields": 1},
            "integrity": {"clean": True, "duplicate_id_groups": 0,
                          "quarantine_count": 0,
                          "quarantine_state": mhr.QUARANTINE_ABSENT,
                          "only_in_canonical": "n/a",
                          "only_in_postgres": "n/a", "archive_parity": None},
            "confab": {"rows": 0},
            "surfacing": {"distinct_memories_surfaced": 0},
            "drift_trend": {"runs": 0},
        }
        line = next(ln for ln in mhr.render_report(report)
                    if "malformed anchors" in ln)
        assert "non-list anchors field" in line


def _init_git_repo(path: Path, relpath: str = "wiki/notes.md") -> Path:
    """Create a throwaway git repository at *path* tracking one file."""
    import os
    import subprocess
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


class TestTierCNamesTheExcludedRepositories:
    """[F]'s fail rate is computed against fewer repositories than it looks.

    Finding M-b: a repository anchor resolution could not consult left no
    trace in the report at all — only a stderr WARN, which the weekly review
    never sees.
    """

    def test_the_section_lists_them(
        self, report_paths, fake_pg, monkeypatch, tmp_path,
    ) -> None:
        """Kills the mutation dropping unusable_repos from the tier-C dict."""
        good = _init_git_repo(tmp_path / "good-repo")
        broken = tmp_path / "broken-repo"     # a directory, not a repository
        broken.mkdir()
        monkeypatch.setattr(mhr.ta, "broad_repo_set", lambda: [good, broken])
        monkeypatch.setattr(
            mhr.ta, "build_basename_index", lambda repos: {},
        )
        mhr.av.reset_unusable_repos()
        _write_corpus(report_paths, [
            _rec(id="m-1", anchors=[{"type": "file", "ref": "wiki/gone.md"}]),
        ])
        fake_pg(FakeDatabase(memories=[{"id": "m-1", "is_active": True}]))

        report, _clean = _build(run_tier_c=True)
        assert report["tier_c"]["unusable_repos"] == [str(broken)]
        assert report["tier_c"]["repos_consulted"] == 2
        rendered = "\n".join(mhr.render_report(report))
        assert "repositories EXCLUDED   : 1 of 2" in rendered
        assert str(broken) in rendered

    def test_a_clean_run_says_nothing(
        self, report_paths, fake_pg, monkeypatch, tmp_path,
    ) -> None:
        """The control: no exclusions, no line."""
        good = _init_git_repo(tmp_path / "good-repo")
        monkeypatch.setattr(mhr.ta, "broad_repo_set", lambda: [good])
        monkeypatch.setattr(mhr.ta, "build_basename_index", lambda repos: {})
        mhr.av.reset_unusable_repos()
        _write_corpus(report_paths, [_anchored(id="m-1")])
        fake_pg(FakeDatabase(memories=[{"id": "m-1", "is_active": True}]))
        report, _clean = _build(run_tier_c=True)
        assert report["tier_c"]["unusable_repos"] == []
        assert "EXCLUDED" not in "\n".join(mhr.render_report(report))


def test_a_schema_mismatch_ends_the_transaction(report_paths, fake_pg) -> None:
    """pg_snapshot must not leave an open transaction behind.

    Kills the mutation dropping ``conn.rollback()`` from the schema-mismatch
    path: the connection is closed with a transaction still open, which on a
    pooled or long-lived connection holds a snapshot the server cannot
    discard.
    """
    import logging
    conn = fake_pg(FakeDatabase(memories=[], schema_version="999"))
    assert mhr.pg_snapshot(logging.getLogger("test-mhr")) is None
    assert conn.rollbacks >= 1
    assert conn.closed
