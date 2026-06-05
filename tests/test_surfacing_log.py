"""
Tests for scripts/surfacing_log.py — per-memory surfacing logger
(earned-utility value signal, item 16, Stage 1).

Covers the pure line formatter, rank assignment / id-less skipping, the
best-effort write contract (a logging failure must never raise), and the
CLI ``--ids`` path used by the ``/recall`` command. A round-trip parity
test (logger output parses cleanly via the aggregator's parser) lives in
``test_surfacing_stats.py``.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Underscore module name — importable directly once scripts/ is on the path.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import surfacing_log  # noqa: E402


FIXED_NOW = datetime(2026, 6, 6, 9, 15, 0, tzinfo=timezone.utc)


# ============================================================================
# format_surfacing_line — pure formatter
# ============================================================================


def test_format_line_shape() -> None:
    """A formatted line is tab-separated, five fields, newline-terminated."""
    line = surfacing_log.format_surfacing_line(
        "2026-06-06-abc123", "digest", 1, None, now=FIXED_NOW
    )
    assert line.endswith("\n")
    fields = line.rstrip("\n").split("\t")
    assert fields == [
        FIXED_NOW.isoformat(),
        "id=2026-06-06-abc123",
        "path=digest",
        "rank=1",
        "session=-",
    ]


def test_format_line_session_passthrough() -> None:
    """A provided session id is recorded; an empty one degrades to ``-``."""
    with_sess = surfacing_log.format_surfacing_line(
        "id1", "recall", 2, "sess-42", now=FIXED_NOW
    )
    assert "session=sess-42" in with_sess
    blank = surfacing_log.format_surfacing_line("id1", "recall", 2, "", now=FIXED_NOW)
    assert "session=-" in blank


def test_format_line_non_numeric_rank_degrades() -> None:
    """A non-numeric rank becomes ``-`` rather than raising."""
    line = surfacing_log.format_surfacing_line("id1", "fetch", "x", None, now=FIXED_NOW)
    assert "rank=-" in line


def test_format_line_sanitises_embedded_whitespace() -> None:
    """Embedded tabs/newlines in a field cannot forge a column."""
    line = surfacing_log.format_surfacing_line(
        "bad\tid\nhere", "digest", 1, None, now=FIXED_NOW
    )
    # Exactly five tab-separated fields survive the sanitisation.
    assert len(line.rstrip("\n").split("\t")) == 5
    assert "id=bad id here" in line


# ============================================================================
# iter_surfacing_lines — rank assignment + id-less skipping
# ============================================================================


def test_iter_ranks_are_one_based_in_order() -> None:
    """Entries are ranked 1, 2, 3 … in surfaced order."""
    mems = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    lines = surfacing_log.iter_surfacing_lines(mems, "digest", now=FIXED_NOW)
    ranks = [ln.split("\trank=")[1].split("\t")[0] for ln in lines]
    assert ranks == ["1", "2", "3"]


def test_iter_skips_id_less_without_consuming_rank() -> None:
    """An entry with no id is skipped and does not consume a rank slot."""
    mems = [{"id": "a"}, {"no_id": 1}, {"id": "c"}]
    lines = surfacing_log.iter_surfacing_lines(mems, "fetch", now=FIXED_NOW)
    assert len(lines) == 2
    ids = [ln.split("\tid=")[1].split("\t")[0] for ln in lines]
    ranks = [ln.split("\trank=")[1].split("\t")[0] for ln in lines]
    assert ids == ["a", "c"]
    assert ranks == ["1", "2"]  # contiguous — the skip did not leave a gap


def test_iter_empty_and_none() -> None:
    """Empty list and None both yield no lines."""
    assert surfacing_log.iter_surfacing_lines([], "digest", now=FIXED_NOW) == []
    assert surfacing_log.iter_surfacing_lines(None, "digest", now=FIXED_NOW) == []


def test_iter_ignores_non_dict_entries() -> None:
    """A stray non-dict entry is skipped, not crashed on."""
    mems = [{"id": "a"}, "not-a-dict", {"id": "b"}]
    lines = surfacing_log.iter_surfacing_lines(mems, "recall", now=FIXED_NOW)
    assert len(lines) == 2


# ============================================================================
# log_surfaced — best-effort writer
# ============================================================================


def test_log_surfaced_appends_and_counts(tmp_path: Path) -> None:
    """Writes one line per id and returns the count."""
    log = tmp_path / "surfaced.log"
    n = surfacing_log.log_surfaced(
        [{"id": "a"}, {"id": "b"}], "digest", log_path=log, now=FIXED_NOW
    )
    assert n == 2
    assert log.read_text(encoding="utf-8").count("\n") == 2


def test_log_surfaced_appends_not_overwrites(tmp_path: Path) -> None:
    """A second call appends rather than truncating."""
    log = tmp_path / "surfaced.log"
    surfacing_log.log_surfaced([{"id": "a"}], "digest", log_path=log, now=FIXED_NOW)
    surfacing_log.log_surfaced([{"id": "b"}], "fetch", log_path=log, now=FIXED_NOW)
    assert log.read_text(encoding="utf-8").count("\n") == 2


def test_log_surfaced_creates_parent_dir(tmp_path: Path) -> None:
    """A missing logs directory is created on first write."""
    log = tmp_path / "nested" / "dir" / "surfaced.log"
    n = surfacing_log.log_surfaced([{"id": "a"}], "recall", log_path=log, now=FIXED_NOW)
    assert n == 1
    assert log.exists()


def test_log_surfaced_empty_returns_zero(tmp_path: Path) -> None:
    """Empty / None input writes nothing and returns 0 (no file created)."""
    log = tmp_path / "surfaced.log"
    assert surfacing_log.log_surfaced([], "digest", log_path=log) == 0
    assert surfacing_log.log_surfaced(None, "digest", log_path=log) == 0
    assert not log.exists()


def test_log_surfaced_never_raises_on_unwritable(tmp_path: Path) -> None:
    """A write to an impossible path returns 0, never raises."""
    # A path whose 'parent' is an existing file cannot be a directory.
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    log = blocker / "surfaced.log"
    assert surfacing_log.log_surfaced([{"id": "a"}], "digest", log_path=log) == 0


# ============================================================================
# main — the /recall CLI path (--ids splitting)
# ============================================================================


def test_cli_ids_split_on_whitespace_and_commas(
    tmp_path: Path, monkeypatch
) -> None:
    """``--ids`` accepts whitespace and/or comma separators."""
    log = tmp_path / "surfaced.log"
    monkeypatch.setattr(surfacing_log, "DEFAULT_LOG_PATH", log)
    monkeypatch.setattr(
        sys, "argv", ["surfacing_log.py", "--path", "recall", "--ids", "a, b  c"]
    )
    surfacing_log.main()
    body = log.read_text(encoding="utf-8")
    assert body.count("\n") == 3
    assert "path=recall" in body
    for want in ("id=a", "id=b", "id=c"):
        assert want in body


def test_cli_empty_ids_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    """An empty ``--ids`` (zero-match recall) writes no lines."""
    log = tmp_path / "surfaced.log"
    monkeypatch.setattr(surfacing_log, "DEFAULT_LOG_PATH", log)
    monkeypatch.setattr(sys, "argv", ["surfacing_log.py", "--ids", ""])
    surfacing_log.main()
    assert not log.exists()
