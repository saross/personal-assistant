"""
Tests for scripts/surfacing_stats.py — read-only aggregator for the
earned-utility value signal (item 16, Stage 1).

Covers the tolerant line parser, per-memory aggregation (active vs passive
weighting, last-active vs last-any timestamps), the corpus-level summary,
and a round-trip parity check that the surfacing_log writer's output
parses cleanly here (so the two modules cannot drift apart).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import surfacing_log  # noqa: E402
import surfacing_stats  # noqa: E402


def _line(ts: str, mem_id: str, path: str, rank: int = 1) -> str:
    """Build a canonical surfaced.log line for tests."""
    return f"{ts}\tid={mem_id}\tpath={path}\trank={rank}\tsession=-"


# ============================================================================
# parse_surfacing_line — tolerant parser
# ============================================================================


def test_parse_valid_line() -> None:
    rec = surfacing_stats.parse_surfacing_line(
        _line("2026-06-06T09:00:00+00:00", "abc", "digest", 2)
    )
    assert rec is not None
    assert rec["id"] == "abc"
    assert rec["path"] == "digest"
    assert rec["rank"] == "2"
    assert rec["timestamp"] == "2026-06-06T09:00:00+00:00"


def test_parse_blank_and_malformed_return_none() -> None:
    assert surfacing_stats.parse_surfacing_line("") is None
    assert surfacing_stats.parse_surfacing_line("   ") is None
    # No tabs at all → no id/path fields.
    assert surfacing_stats.parse_surfacing_line("garbage line") is None


def test_parse_missing_required_fields_return_none() -> None:
    # Has a path but no id.
    assert (
        surfacing_stats.parse_surfacing_line("2026-06-06T09:00:00+00:00\tpath=digest")
        is None
    )
    # Has an id but no path.
    assert (
        surfacing_stats.parse_surfacing_line("2026-06-06T09:00:00+00:00\tid=abc")
        is None
    )


def test_parse_tolerates_extra_fields() -> None:
    rec = surfacing_stats.parse_surfacing_line(
        "2026-06-06T09:00:00+00:00\tid=abc\tpath=fetch\trank=1\tsession=-\textra=foo"
    )
    assert rec is not None
    assert rec["extra"] == "foo"


# ============================================================================
# aggregate_surfacing — per-memory stats
# ============================================================================


def test_aggregate_separates_active_from_digest() -> None:
    lines = [
        _line("2026-06-06T09:00:00+00:00", "a", "digest"),
        _line("2026-06-06T09:01:00+00:00", "a", "digest"),
        _line("2026-06-06T09:02:00+00:00", "a", "fetch"),
        _line("2026-06-06T09:03:00+00:00", "a", "recall"),
    ]
    stats = surfacing_stats.aggregate_surfacing(lines)
    assert stats["a"]["digest_exposures"] == 2
    assert stats["a"]["active_retrievals"] == 2  # fetch + recall


def test_aggregate_last_active_vs_last_any() -> None:
    """last_active tracks fetch/recall only; last_any tracks everything."""
    lines = [
        _line("2026-06-06T09:00:00+00:00", "a", "fetch"),
        _line("2026-06-06T10:00:00+00:00", "a", "digest"),  # latest, but passive
    ]
    stats = surfacing_stats.aggregate_surfacing(lines)
    assert stats["a"]["last_active_at"] == "2026-06-06T09:00:00+00:00"
    assert stats["a"]["last_any_at"] == "2026-06-06T10:00:00+00:00"


def test_aggregate_multiple_memories_and_skips_malformed() -> None:
    lines = [
        _line("2026-06-06T09:00:00+00:00", "a", "fetch"),
        "totally malformed",
        _line("2026-06-06T09:01:00+00:00", "b", "digest"),
        "",
    ]
    stats = surfacing_stats.aggregate_surfacing(lines)
    assert set(stats) == {"a", "b"}
    assert stats["a"]["active_retrievals"] == 1
    assert stats["b"]["digest_exposures"] == 1


def test_aggregate_from_path(tmp_path: Path) -> None:
    log = tmp_path / "surfaced.log"
    log.write_text(
        "\n".join(
            [
                _line("2026-06-06T09:00:00+00:00", "a", "recall"),
                _line("2026-06-06T09:01:00+00:00", "a", "digest"),
            ]
        ),
        encoding="utf-8",
    )
    stats = surfacing_stats.aggregate_surfacing(log)
    assert stats["a"]["active_retrievals"] == 1
    assert stats["a"]["digest_exposures"] == 1


def test_aggregate_missing_path_returns_empty(tmp_path: Path) -> None:
    """A not-yet-created log (normal pre-accrual) yields empty stats."""
    assert surfacing_stats.aggregate_surfacing(tmp_path / "nope.log") == {}


# ============================================================================
# summarise — corpus-level roll-up
# ============================================================================


def test_summarise_totals() -> None:
    lines = [
        _line("2026-06-06T09:00:00+00:00", "a", "fetch"),
        _line("2026-06-06T09:01:00+00:00", "a", "digest"),
        _line("2026-06-06T09:02:00+00:00", "b", "digest"),
    ]
    summary = surfacing_stats.summarise(surfacing_stats.aggregate_surfacing(lines))
    assert summary["distinct_memories_surfaced"] == 2
    assert summary["memories_ever_actively_retrieved"] == 1  # only 'a'
    assert summary["total_active_retrievals"] == 1
    assert summary["total_digest_exposures"] == 2


# ============================================================================
# Round-trip parity — writer output parses via the aggregator
# ============================================================================


def test_writer_output_parses_in_aggregator(tmp_path: Path) -> None:
    """surfacing_log writer output must parse cleanly here (no drift)."""
    log = tmp_path / "surfaced.log"
    now = datetime(2026, 6, 6, 9, 0, 0, tzinfo=timezone.utc)
    surfacing_log.log_surfaced(
        [{"id": "x"}, {"id": "y"}], "fetch", log_path=log, now=now
    )
    surfacing_log.log_surfaced([{"id": "x"}], "digest", log_path=log, now=now)
    stats = surfacing_stats.aggregate_surfacing(log)
    assert stats["x"]["active_retrievals"] == 1
    assert stats["x"]["digest_exposures"] == 1
    assert stats["y"]["active_retrievals"] == 1


# ============================================================================
# Lens B RT11 — the renderer and the CLI entry point
# ============================================================================

import json  # noqa: E402
import pytest  # noqa: E402


def _stats_log(tmp_path: Path) -> Path:
    """A small log: one heavily retrieved memory, one only ever in a digest."""
    log = tmp_path / "surfaced.log"
    log.write_text(
        "\n".join([
            _line("2026-06-01T09:00:00+00:00", "hot", "fetch"),
            _line("2026-06-02T09:00:00+00:00", "hot", "recall"),
            _line("2026-06-03T09:00:00+00:00", "hot", "mcp"),
            _line("2026-06-01T09:00:00+00:00", "cold", "digest"),
        ]) + "\n",
        encoding="utf-8",
    )
    return log


class TestRenderHuman:
    """The human summary is the thing an operator actually reads."""

    def test_ranks_the_most_actively_retrieved_first(self, tmp_path: Path) -> None:
        """Kills: dropping ``reverse=True`` from the ranking sort.

        Reversed, the report headlines the memories nobody has ever asked
        for — the opposite of the value signal it exists to show.
        """
        stats = surfacing_stats.aggregate_surfacing(_stats_log(tmp_path))
        rendered = surfacing_stats._render_human(stats, top=20)
        body = rendered.split("## Top", 1)[1]
        assert body.index("hot") < body.index("cold")

    def test_totals_appear_in_the_summary(self, tmp_path: Path) -> None:
        stats = surfacing_stats.aggregate_surfacing(_stats_log(tmp_path))
        rendered = surfacing_stats._render_human(stats, top=20)
        assert "Total active retrievals:           3" in rendered
        assert "Total digest exposures (passive):  1" in rendered

    def test_top_n_truncates(self, tmp_path: Path) -> None:
        """Kills: ignoring the --top bound."""
        stats = surfacing_stats.aggregate_surfacing(_stats_log(tmp_path))
        rendered = surfacing_stats._render_human(stats, top=1)
        assert "## Top 1 most actively retrieved" in rendered
        assert "cold" not in rendered.split("## Top", 1)[1]

    def test_empty_log_still_renders(self, tmp_path: Path) -> None:
        """Pre-accrual is the normal state; it must not raise."""
        rendered = surfacing_stats._render_human({}, top=20)
        assert "Distinct memories surfaced:        0" in rendered
        assert "## Top" not in rendered


class TestMain:
    """``main()`` had no test: aggregating an empty dict passed."""

    def test_human_output_reports_the_real_counts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Kills: main() aggregating ``{}`` instead of the log it was given."""
        log = _stats_log(tmp_path)
        monkeypatch.setattr(
            sys, "argv", ["surfacing_stats.py", "--log-path", str(log)],
        )
        surfacing_stats.main()
        out = capsys.readouterr().out
        assert "Distinct memories surfaced:        2" in out
        assert "hot" in out

    def test_json_output_carries_summary_and_per_memory_stats(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        log = _stats_log(tmp_path)
        monkeypatch.setattr(
            sys, "argv", ["surfacing_stats.py", "--log-path", str(log), "--json"],
        )
        surfacing_stats.main()
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["total_active_retrievals"] == 3
        assert payload["memories"]["hot"]["active_retrievals"] == 3

    def test_missing_log_reports_zeroes_rather_than_failing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(sys, "argv", [
            "surfacing_stats.py", "--log-path", str(tmp_path / "absent.log"),
        ])
        surfacing_stats.main()
        assert "Distinct memories surfaced:        0" in capsys.readouterr().out


def test_mcp_lines_count_as_active_retrieval(tmp_path: Path) -> None:
    """Audit R5: an MCP serve is intent-driven, like fetch and recall."""
    log = _stats_log(tmp_path)
    stats = surfacing_stats.aggregate_surfacing(log)
    assert stats["hot"]["active_retrievals"] == 3
    assert stats["hot"]["last_active_at"] == "2026-06-03T09:00:00+00:00"
