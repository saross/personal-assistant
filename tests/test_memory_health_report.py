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
