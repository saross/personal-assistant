"""
Tests for ``scripts/style-analyser/phase3_guide_verifier.py``.

This script is the gate that is supposed to stop a confabulated number
reaching the published style guide, and the audit found four ways past it:

* the ``N <feature> / M words`` check accepted the numerator if it matched ANY
  integer in the aggregate block, so "73 semicolons / 127,720 words" passed on
  the strength of the em-dash count being 73 (ST4);
* ``extract_per_1k_aggregates`` was written but never called, and any section
  without a metric mapping was skipped wholesale, so a confabulated per-1k
  rate passed with a tick and exit 0 (ST28, STT6/C6);
* a genuine numeric mismatch was downgraded from FAIL to WARN whenever a word
  such as "lower" appeared anywhere in a 120-character window (ST6);
* every eight-character upper-case token was treated as a Zotero key, so
  METADATA, ANALYSIS and 20260530 were reported as confabulated keys (ST7).

The re-audit found two more:

* the per-1k extractor required a decimal point and a bare ``1 000``, so
  ``0.57 per 1,000 words``, ``0.57/1,000 words``, ``0.57 per 1k`` and the
  integer ``6 per 1 000 words`` produced no row at all and passed unchecked
  (ST-R4g-7);
* the key check decided what WAS a key by shape, requiring both a letter and a
  digit, so an all-letter key such as ABCDEFGH was invisible to check 5 and a
  confabulated one passed (ST-R4g-8).

Every fixture here is invented: the keys, the rates, and the guide prose are
all synthetic, and no corpus file is read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style_test_helpers import (  # noqa: E402
    SCRIPTS_DIR, load_style_module, refuse_sockets,
)

verifier = load_style_module("phase3_guide_verifier")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here may open a socket; this script is CPU-only."""
    refuse_sockets(monkeypatch)


# ---------------------------------------------------------------------------
# Synthetic phase 1 / phase 3 fixtures
# ---------------------------------------------------------------------------

#: Six invented papers. Semicolons in four of them, em-dashes in none.
PHASE1 = {
    "per_paper": [
        {"key": "AAAA1111", "regression": {"semicolon_per_1k": 10.0,
                                           "em_dash_per_1k": 0.0}},
        {"key": "BBBB2222", "regression": {"semicolon_per_1k": 12.0,
                                           "em_dash_per_1k": 0.0}},
        {"key": "CCCC3333", "regression": {"semicolon_per_1k": 14.0,
                                           "em_dash_per_1k": 0.0}},
        {"key": "DDDD4444", "regression": {"semicolon_per_1k": 12.0,
                                           "em_dash_per_1k": 0.0}},
        {"key": "EEEE5555", "regression": {"semicolon_per_1k": 0.0,
                                           "em_dash_per_1k": 0.0}},
        {"key": "FFFF6666", "regression": {"semicolon_per_1k": 0.0,
                                           "em_dash_per_1k": 0.0}},
    ],
    "aggregate": {
        "n_words": 1000,
        "announcement_colon_per_1k": 1.25,
        "regression": {
            "semicolon_count": 12,
            "semicolon_per_1k": 12.0,
            # Deliberately equal to a DIFFERENT feature's count, which is the
            # exact shape of finding ST4.
            "em_dash_count": 73,
            "em_dash_per_1k": 73.0,
        },
    },
}

PHASE3 = {
    "promotions": [
        {"metric": "semicolon_per_1k", "section": "6.2",
         "promotion": "attested", "n_papers_present": 4,
         "n_papers_total": 6, "cv": 0.5},
        {"metric": "pace_count", "section": "3.4",
         "promotion": "attested-concentrated", "n_papers_present": 3,
         "n_papers_total": 6, "cv": 2.0},
    ],
}


def _claim(section: str, title: str, body: str) -> str:
    """Wrap a claim body in the `### N.N Title` block shape the guide uses."""
    return f"### {section} {title}\n\n{body}\n"


def _statuses(results, check_prefix: str) -> list[str]:
    """Return the statuses of the rows whose check label starts as given."""
    return [r.status for r in results if r.check.startswith(check_prefix)]


# ---------------------------------------------------------------------------
# ST4 — the count must match the metric the claim names
# ---------------------------------------------------------------------------

def test_a_count_matching_the_wrong_feature_now_fails():
    """"73 semicolons" must not pass because 73 is the em-dash count.

    The mutation this kills: matching the numerator against any integer in
    `aggregate.regression` (``if isinstance(v, int) and v == count``).
    """
    body = "**Status:** attested\n\nThe corpus has 73 semicolons / 1,000 words."

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    assert _statuses(results, "count / words") == ["FAIL"]


def test_a_count_matching_its_own_feature_passes():
    """The check must still pass a correct claim, or it is merely strict."""
    body = "**Status:** attested\n\nThe corpus has 12 semicolons / 1,000 words."

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    assert _statuses(results, "count / words") == ["PASS"]


def test_a_feature_phase_one_does_not_count_is_reported_as_unverifiable():
    """An unmappable feature word must fail, not pass with a shrug.

    The mutation this kills: falling back to WARN for an unknown numerator
    (the old behaviour, which let the claim through with exit 0).
    """
    body = "**Status:** attested\n\nThere are 12 widgets / 1,000 words."

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    row = [r for r in results if r.check.startswith("count / words")][0]
    assert row.status == "FAIL"
    assert "cannot verify" in row.note


# ---------------------------------------------------------------------------
# STT6 / ST28 — per-1k rates are checked, and unmapped sections are reported
# ---------------------------------------------------------------------------

def test_a_confabulated_per_1k_rate_fails():
    """A rate that matches no phase 1 aggregate must not pass.

    The mutation this kills: deleting the check-4b block, restoring
    ``extract_per_1k_aggregates`` to dead code.
    """
    body = "**Status:** attested\n\nSemicolons run at 6.54 per 1 000 words."

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    assert _statuses(results, "per-1k rate") == ["FAIL"]


def test_a_correct_per_1k_rate_passes():
    """The corpus's own rate, quoted correctly, passes."""
    body = "**Status:** attested\n\nSemicolons run at 12.0 per 1 000 words."

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    assert _statuses(results, "per-1k rate") == ["PASS"]


@pytest.mark.parametrize(
    ("shape", "expected"),
    [
        ("0.57 per 1,000 words", 0.57),   # comma thousands separator
        ("0.57 per 1 000 words", 0.57),   # space separator (the old shape)
        ("0.57 per 1000 words", 0.57),    # no separator at all
        ("0.57 per 1 000 w", 0.57),       # abbreviated unit
        ("0.57 per 1k", 0.57),            # `1k` after `per`
        ("0.57/1,000 words", 0.57),       # slash plus comma
        ("0.57/1k", 0.57),                # slash plus `1k` (the old shape)
        ("6 per 1 000 words", 6.0),       # integer rate, space separator
        ("6 per 1,000 words", 6.0),       # integer rate, comma separator
    ],
)
def test_every_per_1k_shape_the_guide_writes_is_extracted(shape, expected):
    r"""Each way of writing a per-1 000-word rate must reach check 4b.

    The mutation this kills: restoring
    ``r"(\d+\.\d+)\s*(?:per\s+1\s*0?\s*0?\s*0\s*w?|...|/1k)"``, which
    requires a decimal point and a separator-free ``1 000``, so the comma,
    ``per 1k`` and integer shapes match nothing.
    """
    assert verifier.extract_per_1k_aggregates(
        f"Semicolons run at {shape} across the corpus.") == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "The 2026 revision covers 1,000 words of prose in all.",
        "The corpus has 12 semicolons / 1,000 words.",
        "A budget of 1 000 words per section was agreed.",
    ],
)
def test_a_word_count_with_no_leading_rate_is_not_a_per_1k_claim(text):
    r"""Widening the pattern must not turn word counts and years into rates.

    The mutation this kills: dropping the mandatory leading
    ``(\d+(?:\.\d+)?)\s*(?:per\s+|/\s*)`` from ``_PER_1K_RE``, which makes
    a bare ``1,000 words`` — check 4's own denominator among them — match as a
    per-1k rate and fabricates check-4b rows for claims that make no such
    assertion.
    """
    assert verifier.extract_per_1k_aggregates(text) == []


def test_a_comma_separated_per_1k_rate_is_checked_rather_than_skipped():
    """A missed shape is not a PASS, it is silence, which is the whole hole.

    The mutation this kills: restoring the decimal-and-bare-``1 000``-only
    pattern, under which this confabulated rate produces NO ROW AT ALL and the
    guide passes the gate with exit 0.
    """
    body = "**Status:** attested\n\nSemicolons run at 0.57 per 1,000 words."

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    assert _statuses(results, "per-1k rate") == ["FAIL"]


def test_an_integer_per_1k_rate_is_checked_in_both_directions():
    r"""An integer rate is a rate: wrong ones fail, right ones pass.

    The mutation this kills: restoring the ``(\d+\.\d+)`` numerator, which
    requires a decimal point and so drops every integer rate unchecked.
    """
    wrong = "**Status:** attested\n\nSemicolons run at 6 per 1 000 words."
    right = "**Status:** attested\n\nSemicolons run at 12 per 1 000 words."

    assert _statuses(
        verifier.verify_claim("6.2", "Semicolons", wrong, PHASE1, PHASE3),
        "per-1k rate") == ["FAIL"]
    assert _statuses(
        verifier.verify_claim("6.2", "Semicolons", right, PHASE1, PHASE3),
        "per-1k rate") == ["PASS"]


def test_a_section_with_no_metric_mapping_is_reported_as_unverified():
    """52 §-claims used to be skipped in silence; each now leaves a row.

    The mutation this kills: restoring ``continue`` for a section absent from
    SECTION_TO_METRICS, which makes an unchecked claim indistinguishable from
    a checked one.
    """
    guide = _claim("9.9", "An unmapped section",
                   "**Status:** attested\n\nAn unchecked number: 999.9/1k.")

    results = verifier.verify_guide(guide, PHASE1, PHASE3)

    assert [r.status for r in results] == ["UNVERIFIED"]


# ---------------------------------------------------------------------------
# ST6 — the sub-cluster downgrade needs the claim to say so
# ---------------------------------------------------------------------------

def test_an_incidental_word_no_longer_downgrades_a_mismatch():
    """"lower" in the neighbouring prose is not a sub-cluster declaration.

    The mutation this kills: restoring the keyword scan over the +/-60-char
    snippet, under which this mismatch comes back as WARN and the run exits 0.
    """
    body = ("**Status:** attested\n\nRates are lower in later work. "
            "The pattern appears in 5/6 papers.")

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    assert _statuses(results, "N/M papers fraction") == ["FAIL"]


def test_a_declared_sub_cluster_partition_is_still_a_warning():
    """A genuine agent-defined partition stays a WARN, as intended."""
    body = ("**Status:** attested\n\nThe pattern appears in 5/6 papers at the "
            "elevated rate.")

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    assert _statuses(results, "N/M papers fraction") == ["WARN"]


def test_a_matching_fraction_passes():
    """The four papers phase 3 recorded, claimed correctly, pass."""
    body = "**Status:** attested\n\nIt appears in 4/6 papers."

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    assert _statuses(results, "N/M papers fraction") == ["PASS"]


# ---------------------------------------------------------------------------
# ST7 — only key-shaped tokens are treated as keys
# ---------------------------------------------------------------------------

def test_upper_case_words_and_date_strings_are_not_zotero_keys():
    """METADATA, ANALYSIS and 20260530 produced spurious FAIL rows.

    The mutation this kills: restoring the bare ``[0-9A-Z]{8}`` pattern.
    """
    assert verifier.extract_named_keys_in_block(
        "METADATA ANALYSIS 20260530 SENTENCE") == []


def test_a_key_shaped_token_that_is_not_in_the_corpus_still_fails():
    """The check must still catch an invented key, or ST7's fix guts it."""
    body = "**Status:** attested\n\nSee ABCD1234 for the pattern."

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    assert _statuses(results, "named-key validity") == ["FAIL"]


def test_a_real_corpus_key_passes_the_key_check():
    """A key that is in phase 1 raises nothing."""
    body = "**Status:** attested\n\nSee AAAA1111 for the pattern."

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    assert _statuses(results, "named-key validity") == []


def _phase1_with_extra_paper(key: str) -> dict:
    """Return PHASE1 plus one more invented paper, so a key can be made real."""
    extra = {"key": key, "regression": {"semicolon_per_1k": 8.0,
                                        "em_dash_per_1k": 0.0}}
    return {**PHASE1, "per_paper": [*PHASE1["per_paper"], extra]}


def test_an_all_letter_corpus_key_is_recognised_and_checked():
    """ABCDEFGH is a real key here, and the shape test made it invisible.

    The mutation this kills: restoring the single-argument
    ``named = extract_named_keys_in_block(body)`` call, which filters every
    candidate through the letters-AND-digits shape test before the corpus key
    set is consulted, so no all-letter key is ever checked.
    """
    phase1 = _phase1_with_extra_paper("ABCDEFGH")
    body = "**Status:** attested\n\nSee ABCDEFGH for the pattern."

    results = verifier.verify_claim("6.2", "Semicolons", body, phase1, PHASE3)

    assert [r.status for r in results if r.actual == "ABCDEFGH"] == ["PASS"]
    assert _statuses(results, "named-key validity") == []


def test_the_same_all_letter_token_is_ignored_when_it_is_not_a_key():
    """ABCDEFGH with no such paper in phase 1 is prose, not a confabulation.

    The mutation this kills: dropping the ``& known`` intersection from
    ``extract_named_keys_in_block`` (``sorted(candidates | plausible)``), which
    reports every eight-character upper-case word as an invalid key and brings
    the whole ST7 false-positive class back.
    """
    body = "**Status:** attested\n\nSee ABCDEFGH for the pattern."

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    assert [r for r in results if r.actual == "ABCDEFGH"] == []


def test_the_extractor_defers_to_the_corpus_key_set():
    """Known keys are keys whatever their shape; unknown ones need the shape.

    The mutation this kills: returning ``sorted(plausible)`` regardless of
    ``valid_keys``, i.e. keeping the shape test as the primary filter, under
    which the real all-letter key ABCDEFGH is dropped from the result.
    """
    text = "ABCDEFGH METADATA ABCD1234 20260530 SENTENCE"

    assert verifier.extract_named_keys_in_block(
        text, {"ABCDEFGH"}) == ["ABCD1234", "ABCDEFGH"]


# ---------------------------------------------------------------------------
# STT-M1 / ST29 — check 1 emits exactly one row, whatever happens
# ---------------------------------------------------------------------------

def test_a_status_with_no_phase3_verdict_behind_it_is_reported():
    """An unbacked status used to emit NO ROW AT ALL — invisible, not passed.

    The mutation this kills: restoring the ``if not valid and p3_for_section``
    / ``elif valid and not out[-1:] or ...`` precedence tangle, under which
    this claim produces no status row.
    """
    phase3_without_the_metric = {"promotions": []}
    body = "**Status:** attested\n\nA claim with nothing behind it."

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1,
                                    phase3_without_the_metric)

    status_rows = [r for r in results if r.check.startswith("status")]
    assert len(status_rows) == 1
    assert status_rows[0].status == "UNVERIFIED"


def test_a_status_that_contradicts_phase3_fails():
    """The core of check 1, kept honest by the rewrite."""
    body = "**Status:** attested-rarely\n\nA claim."

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    status_rows = [r for r in results if r.check.startswith("status")]
    assert [r.status for r in status_rows] == ["FAIL"]


def test_a_status_matching_phase3_passes_exactly_once():
    """One row, not zero and not two."""
    body = "**Status:** attested\n\nA claim."

    results = verifier.verify_claim("6.2", "Semicolons", body, PHASE1, PHASE3)

    status_rows = [r for r in results if r.check.startswith("status")]
    assert [r.status for r in status_rows] == ["PASS"]


def test_the_allowlisted_semantic_override_is_now_reachable():
    """§3.4's override was dead code while §3.4 had no metric mapping.

    The mutation this kills: removing "3.4" from SECTION_TO_METRICS, which
    returns the allowlist entry to unreachable dead code (finding ST28).
    """
    body = "**Status:** absent-when-searched\n\nNo Latin citation hedge."

    results = verifier.verify_claim("3.4", "Latin abbreviations", body,
                                    PHASE1, PHASE3)

    status_rows = [r for r in results if r.check.startswith("status")]
    assert [r.status for r in status_rows] == ["PASS"]
    assert "word-sense" in status_rows[0].note


# ---------------------------------------------------------------------------
# Driver: exit codes, --allow-unverified, --dry-run, determinism
# ---------------------------------------------------------------------------

def _write_inputs(tmp_path: Path, guide_text: str) -> dict[str, Path]:
    """Write a guide plus the two JSON inputs into a throwaway directory."""
    paths = {
        "guide": tmp_path / "guide.md",
        "phase1": tmp_path / "phase1.json",
        "phase3": tmp_path / "phase3.json",
        "report": tmp_path / "report.md",
    }
    paths["guide"].write_text(guide_text, encoding="utf-8")
    paths["phase1"].write_text(json.dumps(PHASE1), encoding="utf-8")
    paths["phase3"].write_text(json.dumps(PHASE3), encoding="utf-8")
    return paths


def _run_main(paths: dict[str, Path], *extra: str) -> int:
    """Call the verifier's ``main`` with explicit paths."""
    return verifier.main([
        "--guide", str(paths["guide"]), "--phase1", str(paths["phase1"]),
        "--phase3", str(paths["phase3"]), "--report", str(paths["report"]),
        *extra,
    ])


CLEAN_GUIDE = _claim(
    "6.2", "Semicolons",
    "**Status:** attested\n\nThe corpus has 12 semicolons / 1,000 words, "
    "12.0 per 1 000 words, in 4/6 papers.")


def test_a_clean_guide_exits_zero_and_writes_a_report(tmp_path):
    """The gate must pass a guide whose numbers are all correct."""
    paths = _write_inputs(tmp_path, CLEAN_GUIDE)

    assert _run_main(paths) == 0
    assert "✓ PASS" in paths["report"].read_text(encoding="utf-8")


def test_an_unverifiable_section_fails_the_run_unless_allowed(tmp_path):
    """"Not checked" is not "checked and correct" — so it fails by default.

    The mutation this kills: counting only FAIL rows toward the exit code.
    """
    paths = _write_inputs(
        tmp_path,
        CLEAN_GUIDE + _claim("9.9", "Unmapped", "**Status:** attested\n"))

    assert _run_main(paths) == 1
    assert _run_main(paths, "--allow-unverified") == 0


def test_dry_run_writes_no_report(tmp_path):
    """``--dry-run`` prints the verdict and writes nothing.

    The mutation this kills: dropping ``dry_run=args.dry_run`` from the write.
    """
    paths = _write_inputs(tmp_path, CLEAN_GUIDE)

    assert _run_main(paths, "--dry-run") == 0
    assert not paths["report"].exists()


def test_the_report_is_byte_identical_under_two_hash_seeds(tmp_path):
    """Set iteration order used to reorder the FAIL rows on every run.

    Run in a child process so PYTHONHASHSEED actually differs. The mutation
    this kills: restoring ``list(set(...))`` in
    ``extract_named_keys_in_block``, which reorders the named-key rows.
    """
    guide = _claim(
        "6.2", "Semicolons",
        "**Status:** attested\n\nSee ABCD1234, WXYZ9876, and QRST5432 — "
        "all invented — in 4/6 papers.")
    paths = _write_inputs(tmp_path, guide)

    outputs = []
    for seed in ("0", "1"):
        report = tmp_path / f"report-{seed}.md"
        env = {**os.environ, "PYTHONHASHSEED": seed}
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "phase3_guide_verifier.py"),
             "--guide", str(paths["guide"]), "--phase1", str(paths["phase1"]),
             "--phase3", str(paths["phase3"]), "--report", str(report)],
            capture_output=True, text=True, env=env, check=False,
        )
        assert proc.returncode == 1, proc.stderr
        outputs.append(report.read_bytes())

    assert outputs[0] == outputs[1]


def test_the_report_records_its_inputs(tmp_path):
    """Provenance ties a verdict to the guide and data that produced it.

    The mutation this kills: dropping the provenance section from the report.
    """
    paths = _write_inputs(tmp_path, CLEAN_GUIDE)

    assert _run_main(paths) == 0

    report = paths["report"].read_text(encoding="utf-8")
    assert "## Provenance" in report
    assert "phase3_guide_verifier.py" in report
    assert report.count("sha256") == 3
