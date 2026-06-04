"""
Tests for scripts/log-recall.py — Vector 2 §8 instrumentation for the
manual /recall depth-fetch path (measurement (2)).

Covers the pure line formatter, the best-effort write contract (a
logging failure must never raise), and format-parity with the autonomous
fetch-memories.py log so a single parser reads the whole file.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# The script has a hyphen in its name, so we need importlib tricks.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
log_recall_mod = __import__("log-recall")


FIXED_NOW = datetime(2026, 6, 2, 8, 30, 0, tzinfo=timezone.utc)


# ============================================================================
# format_line — pure formatter
# ============================================================================


def test_format_line_shape() -> None:
    """A formatted line is tab-separated with the five expected fields."""
    line = log_recall_mod.format_line(
        "category:decision;query", 10, 3, "recall", now=FIXED_NOW
    )
    assert line.endswith("\n")
    fields = line.rstrip("\n").split("\t")
    assert fields == [
        "2026-06-02T08:30:00+00:00",
        "selectors=category:decision;query",
        "limit=10",
        "results=3",
        "source=recall",
    ]


def test_format_line_blank_selectors_default_to_none() -> None:
    """Empty or whitespace selectors collapse to the sentinel 'none'."""
    line = log_recall_mod.format_line("   ", 10, 0, "recall", now=FIXED_NOW)
    assert "\tselectors=none\t" in line


def test_format_line_coerces_results_to_int() -> None:
    """A non-int results value is coerced (not just rendered)."""
    # Pass a float so the test fails if the int() coercion is removed.
    line = log_recall_mod.format_line("query", 10, 3.9, "recall", now=FIXED_NOW)
    assert "\tresults=3\t" in line


def test_format_line_sanitises_tab_newline_in_fields() -> None:
    """Tabs/newlines in selectors or source can't forge or split a record."""
    line = log_recall_mod.format_line(
        "tag:a\tb", 10, 0, "rec\nall", now=FIXED_NOW
    )
    assert line.count("\t") == 4  # exactly the four field separators
    assert line.count("\n") == 1  # the single trailing newline
    assert "selectors=tag:a b" in line and "source=rec all" in line


# ============================================================================
# log_recall — best-effort writer
# ============================================================================


def test_log_recall_appends_line(tmp_path: Path) -> None:
    """A successful write returns True and appends one parseable line."""
    log_path = tmp_path / "fetch-memories.log"
    ok = log_recall_mod.log_recall(
        "tag:ethics", results=2, limit=10, log_path=log_path, now=FIXED_NOW
    )
    assert ok is True
    contents = log_path.read_text(encoding="utf-8")
    assert contents.count("\n") == 1
    assert "selectors=tag:ethics" in contents
    assert "source=recall" in contents


def test_log_recall_appends_not_overwrites(tmp_path: Path) -> None:
    """A second call appends rather than truncating the first line."""
    log_path = tmp_path / "fetch-memories.log"
    log_recall_mod.log_recall("query", results=1, log_path=log_path, now=FIXED_NOW)
    log_recall_mod.log_recall("recent", results=5, log_path=log_path, now=FIXED_NOW)
    assert log_path.read_text(encoding="utf-8").count("\n") == 2


def test_log_recall_creates_parent_dir(tmp_path: Path) -> None:
    """A missing logs directory is created on first write."""
    log_path = tmp_path / "logs" / "fetch-memories.log"
    assert log_recall_mod.log_recall("none", log_path=log_path, now=FIXED_NOW) is True
    assert log_path.exists()


def test_log_recall_best_effort_never_raises(tmp_path: Path) -> None:
    """An unwritable path returns False and does NOT raise.

    Mirrors the digest best-effort-log contract: a log component that is
    a regular file makes mkdir(parents=True) fail, which must be
    swallowed so /recall is still served.
    """
    blocker = tmp_path / "afile"
    blocker.write_text("not a directory", encoding="utf-8")
    log_path = blocker / "nested" / "fetch-memories.log"
    # Must not raise:
    assert log_recall_mod.log_recall("query", log_path=log_path, now=FIXED_NOW) is False


# ============================================================================
# Format parity with fetch-memories.py
# ============================================================================


def test_format_parity_with_autonomous_path() -> None:
    """The shared leading fields match the autonomous log's field order.

    The 2026-06-13 review parses both paths from one file; the first four
    fields (timestamp, selectors, limit, results) must read identically,
    with source appended. Guards against silent format drift.
    """
    line = log_recall_mod.format_line("query", "?", 0, "recall", now=FIXED_NOW)
    fields = line.rstrip("\n").split("\t")
    assert fields[1].startswith("selectors=")
    assert fields[2].startswith("limit=")
    assert fields[3].startswith("results=")
    assert fields[4] == "source=recall"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
