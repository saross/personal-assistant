"""
Tests for scripts/log-confab-flag.py — Vector 2 §8 instrumentation for
measurement (3), the verifier-agent confabulation-flag rate.

Covers the corrections.jsonl tally, the pure line formatter, the
file-loader's lenient parsing, and the best-effort write contract (a
logging failure must never raise).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# The script has a hyphen in its name, so we need importlib tricks.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
log_confab = __import__("log-confab-flag")


FIXED_NOW = datetime(2026, 6, 2, 9, 0, 0, tzinfo=timezone.utc)


def _claim(status: str, failure_type: str | None = None) -> dict:
    return {"status": status, "failure_type": failure_type}


# ============================================================================
# tally_corrections
# ============================================================================


def test_tally_counts_fail_as_flagged_and_confab_subset() -> None:
    """flagged counts FAILs; confab counts the confabulation subset."""
    records = [
        _claim("pass"),
        _claim("partial"),
        _claim("fail", "confabulation"),
        _claim("fail", "stale_count"),
        _claim("fail", "confabulation"),
        _claim("documentation_defect", "encoding_artefact"),
        _claim("unverifiable"),
    ]
    t = log_confab.tally_corrections(records)
    assert t["checked"] == 7
    assert t["flagged"] == 3  # only status=fail
    assert t["confab"] == 2  # of the fails, two are confabulation
    assert t["kinds"] == ["confabulation", "stale_count"]  # sorted, fails only


def test_tally_empty() -> None:
    """An empty corrections set tallies to all-zero, no kinds."""
    t = log_confab.tally_corrections([])
    assert t == {"checked": 0, "flagged": 0, "confab": 0, "kinds": []}


def test_tally_status_case_insensitive() -> None:
    """status/failure_type comparisons are case-insensitive."""
    t = log_confab.tally_corrections([_claim("FAIL", "Confabulation")])
    assert t["flagged"] == 1
    assert t["confab"] == 1


def test_tally_no_confab_when_only_other_failure_types() -> None:
    """A run with failures but no confabulation reports confab=0."""
    t = log_confab.tally_corrections(
        [_claim("fail", "metadata_drift"), _claim("fail", "stale_count")]
    )
    assert t["flagged"] == 2
    assert t["confab"] == 0
    assert t["kinds"] == ["metadata_drift", "stale_count"]


# ============================================================================
# load_corrections
# ============================================================================


def test_load_corrections_skips_blank_and_unparseable(tmp_path: Path) -> None:
    """Blank lines and non-JSON lines are skipped; dicts are kept."""
    p = tmp_path / "corrections.jsonl"
    p.write_text(
        '{"status":"fail","failure_type":"confabulation"}\n'
        "\n"
        "not json at all\n"
        '{"status":"pass"}\n'
        "[1, 2, 3]\n",  # valid JSON but not a dict → skipped
        encoding="utf-8",
    )
    records = log_confab.load_corrections(p)
    assert len(records) == 2
    assert log_confab.tally_corrections(records)["confab"] == 1


# ============================================================================
# format_line
# ============================================================================


def test_format_line_shape() -> None:
    """A formatted line is tab-separated with the eight expected fields."""
    line = log_confab.format_line(
        "lit-scout-verifier", "topic-x", 42, 3, 2, ["confabulation", "stale_count"],
        now=FIXED_NOW,
    )
    assert line.endswith("\n")
    fields = line.rstrip("\n").split("\t")
    assert fields == [
        "2026-06-02T09:00:00+00:00",
        "source=lit-scout-verifier",
        "deliverable=topic-x",
        "checked=42",
        "flagged=3",
        "confab=2",
        "kinds=confabulation,stale_count",
        "detail=-",  # absent by default (verifier-tally rows)
    ]


def test_format_line_defaults_for_blank_deliverable_kinds_and_detail() -> None:
    """Blank deliverable → '-'; empty kinds → 'none'; empty detail → '-'."""
    line = log_confab.format_line("data-profile-verifier", "", 10, 0, 0, [], now=FIXED_NOW)
    assert "\tdeliverable=-\t" in line
    assert "\tkinds=none\t" in line
    assert line.endswith("\tdetail=-\n")


def test_format_line_detail_is_whitespace_collapsed_and_bounded() -> None:
    """A detail note with tabs/newlines is collapsed so it never breaks the TSV."""
    messy = "claimed\tscripts/foo.py\n  actually   scripts/bar/foo.py"
    line = log_confab.format_line(
        "user-correction", "inscriptions", 0, 1, 1, ["path"], now=FIXED_NOW, detail=messy,
    )
    # Still exactly eight tab-separated fields — the note added no stray tabs.
    assert len(line.rstrip("\n").split("\t")) == 8
    assert "detail=claimed scripts/foo.py actually scripts/bar/foo.py" in line


def test_format_line_detail_truncated_to_200_chars() -> None:
    """An over-long detail is truncated so the log cannot bloat."""
    line = log_confab.format_line(
        "user-correction", "x", 0, 1, 1, ["count"], now=FIXED_NOW, detail="z" * 500,
    )
    detail_field = line.rstrip("\n").split("\t")[-1]
    assert detail_field == "detail=" + "z" * 200


def test_manual_entry_round_trips_through_log_confab_flag(tmp_path: Path) -> None:
    """A /confab-style manual entry writes source, checked=0, and the detail."""
    log_path = tmp_path / "confab-flags.log"
    ok = log_confab.log_confab_flag(
        "user-correction",
        checked=0,
        flagged=1,
        confab=1,
        kinds=["identifier"],
        deliverable="paper-b",
        detail="said the variable was n_atoms, it is atom_count",
        log_path=log_path,
        now=FIXED_NOW,
    )
    assert ok is True
    contents = log_path.read_text(encoding="utf-8")
    assert "source=user-correction" in contents
    assert "\tchecked=0\t" in contents
    assert "detail=said the variable was n_atoms, it is atom_count" in contents


# ============================================================================
# log_confab_flag — best-effort writer
# ============================================================================


def test_log_confab_flag_appends(tmp_path: Path) -> None:
    """A successful write returns True and appends one parseable line."""
    log_path = tmp_path / "confab-flags.log"
    ok = log_confab.log_confab_flag(
        "prior-art-scout-verifier",
        checked=8,
        flagged=1,
        confab=1,
        kinds=["confabulation"],
        deliverable="prior-art-x",
        log_path=log_path,
        now=FIXED_NOW,
    )
    assert ok is True
    contents = log_path.read_text(encoding="utf-8")
    assert contents.count("\n") == 1
    assert "source=prior-art-scout-verifier" in contents
    assert "confab=1" in contents


def test_log_confab_flag_appends_not_overwrites(tmp_path: Path) -> None:
    """A second call appends rather than truncating the first line."""
    log_path = tmp_path / "confab-flags.log"
    log_confab.log_confab_flag("lit-scout-verifier", checked=1, flagged=0, confab=0,
                               log_path=log_path, now=FIXED_NOW)
    log_confab.log_confab_flag("lit-scout-verifier", checked=2, flagged=1, confab=1,
                               log_path=log_path, now=FIXED_NOW)
    assert log_path.read_text(encoding="utf-8").count("\n") == 2


def test_log_confab_flag_best_effort_never_raises(tmp_path: Path) -> None:
    """An unwritable path returns False and does NOT raise."""
    blocker = tmp_path / "afile"
    blocker.write_text("not a directory", encoding="utf-8")
    log_path = blocker / "nested" / "confab-flags.log"
    assert (
        log_confab.log_confab_flag(
            "lit-scout-verifier", checked=1, flagged=0, confab=0,
            log_path=log_path, now=FIXED_NOW,
        )
        is False
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
