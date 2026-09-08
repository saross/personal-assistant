"""
Tests for ``scripts/style-analyser/phase3_promotion.py``.

The promotion algorithm turns per-paper rates into the `attested` /
`attested-concentrated` / `attested-rarely` verdicts the style guide quotes,
and the audit found three problems with it:

* a mismatch between ``paper_keys`` and ``per_paper_rates`` silently produced
  EMPTY ``papers_present`` / ``papers_absent`` lists, disarming the very
  confabulation guard those lists exist to provide (ST25);
* ``n_present`` counts papers whose rate is above zero, so a continuous,
  structurally positive metric — mean sentence length, MATTR, dependency
  depth — was promoted to `attested` on the strength of "18/18 papers have
  it", which says nothing at all (ST26);
* a metric measured as exactly zero was printed as "?", indistinguishable
  from a metric nobody counted.

Every rate and key here is invented.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style_test_helpers import load_style_module, refuse_sockets  # noqa: E402

promotion = load_style_module("phase3_promotion")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here may open a socket; this script is CPU-only."""
    refuse_sockets(monkeypatch)


KEYS = ["AAAA1111", "BBBB2222", "CCCC3333", "DDDD4444", "EEEE5555",
        "FFFF6666"]


# ---------------------------------------------------------------------------
# ST25 — the confabulation guard must not disarm itself
# ---------------------------------------------------------------------------

def test_a_key_and_rate_mismatch_is_an_error():
    """Unaligned lists would attribute a rate to the wrong paper.

    The mutation this kills: restoring
    ``if paper_keys is not None and len(paper_keys) == len(rates)``, which
    skips the evidence lists instead of failing.
    """
    with pytest.raises(ValueError, match="paper keys"):
        promotion.promote("semicolon_per_1k", [1.0, 2.0],
                          paper_keys=["AAAA1111"])


def test_aligned_keys_produce_the_evidence_lists():
    """Present papers descend by rate; absent papers are sorted by key."""
    verdict = promotion.promote(
        "semicolon_per_1k", [0.0, 3.0, 1.0], paper_keys=KEYS[:3])

    assert [p["key"] for p in verdict["papers_present"]] == ["BBBB2222",
                                                             "CCCC3333"]
    assert verdict["papers_absent"] == ["AAAA1111"]


# ---------------------------------------------------------------------------
# ST26 — presence is not evidence for an always-positive metric
# ---------------------------------------------------------------------------

def test_a_continuous_metric_is_not_promoted_by_presence():
    """"Every paper has a sentence length" is not an attestation.

    The mutation this kills: dropping the ``CONTINUOUS_METRICS`` lookup, after
    which the rationale claims presence across papers as its evidence.
    """
    verdict = promotion.promote("sentence_mean", [21.0, 23.0, 24.0, 22.0,
                                                  25.0, 20.0],
                                paper_keys=KEYS)

    assert verdict["presence_rule_applies"] is False
    assert verdict["promotion_basis"] == "papers measured"
    assert "papers measured" in verdict["promotion_rationale"]


def test_a_rate_metric_still_reports_the_presence_rule():
    """A feature that can genuinely be absent keeps the original rule."""
    verdict = promotion.promote("semicolon_per_1k", [0.0, 2.0, 3.0, 4.0,
                                                     0.0, 5.0],
                                paper_keys=KEYS)

    assert verdict["presence_rule_applies"] is True
    assert verdict["promotion_basis"] == "papers with the feature"
    assert verdict["n_papers_present"] == 4


# ---------------------------------------------------------------------------
# The five verdict branches, at their exact boundaries
# ---------------------------------------------------------------------------

def test_three_papers_with_five_occurrences_and_low_cv_is_attested():
    """The floor values themselves must pass: >= 3 papers, >= 5 occurrences."""
    verdict = promotion.promote("semicolon_per_1k", [1.0, 1.0, 1.0],
                                paper_keys=KEYS[:3], n_occ=5)

    assert verdict["promotion"] == "attested"


def test_one_occurrence_short_of_the_floor_is_attested_rarely():
    """n_occ = 4 is below the floor of 5, so the verdict drops a step."""
    verdict = promotion.promote("semicolon_per_1k", [1.0, 1.0, 1.0],
                                paper_keys=KEYS[:3], n_occ=4)

    assert verdict["promotion"] == "attested-rarely"


def test_two_papers_is_attested_rarely():
    """Below the paper floor, however many occurrences there are."""
    verdict = promotion.promote("semicolon_per_1k", [3.0, 4.0, 0.0],
                                paper_keys=KEYS[:3], n_occ=99)

    assert verdict["promotion"] == "attested-rarely"


def test_no_paper_at_all_is_an_absence_candidate():
    """Zero everywhere is a candidate for absent-when-searched, not attested."""
    verdict = promotion.promote("semicolon_per_1k", [0.0, 0.0, 0.0],
                                paper_keys=KEYS[:3], n_occ=0)

    assert verdict["promotion"] == "absent-when-searched-candidate"


def test_a_high_cv_concentrates_the_verdict():
    """CV above the threshold is `attested-concentrated`, not `attested`."""
    verdict = promotion.promote("semicolon_per_1k", [0.1, 0.1, 12.0],
                                paper_keys=KEYS[:3], n_occ=50)

    assert verdict["cv"] > promotion.CV_THRESHOLD
    assert verdict["promotion"] == "attested-concentrated"


# ---------------------------------------------------------------------------
# The bimodality detector
# ---------------------------------------------------------------------------

def test_a_single_outlier_is_not_a_bimodal_split():
    """One paper far from the rest is an outlier, not two clusters.

    The mutation this kills: dropping the min-per-side constraint from
    ``detect_bimodal``, which makes the 17th-to-18th gap a "cluster split".
    """
    is_bimodal, _gap, _frac = promotion.detect_bimodal(
        [1.0, 1.1, 1.2, 1.3, 1.4, 9.0])

    assert is_bimodal is False


def test_two_clusters_of_three_are_bimodal():
    """Three low papers and three high ones is exactly the intended case."""
    is_bimodal, _gap, frac = promotion.detect_bimodal(
        [1.0, 1.1, 1.2, 8.0, 8.1, 8.2])

    assert is_bimodal is True
    assert frac > promotion.BIMODALITY_GAP_FRACTION


def test_fewer_than_six_papers_cannot_be_bimodal():
    """The detector needs three papers a side; five cannot supply them."""
    assert promotion.detect_bimodal([1.0, 1.0, 1.0, 9.0, 9.0])[0] is False


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_a_measured_zero_is_printed_as_zero(tmp_path, monkeypatch, capsys):
    """`n_occ or '?'` turned a measured zero into "not counted".

    The mutation this kills: restoring ``str(p['n_occ'] or '?')``.
    """
    phase1 = tmp_path / "phase1.json"
    phase1.write_text(
        '{"per_paper": [{"key": "AAAA1111", "regression": '
        '{"pace_count_case_sensitive": 0}}], '
        '"aggregate": {"regression": {"pace_count_case_sensitive": 0}}}',
        encoding="utf-8")
    monkeypatch.setattr(promotion, "PHASE1", phase1)
    monkeypatch.setattr(promotion, "OUT", tmp_path / "phase3.json")

    assert promotion.main([]) == 0

    out = capsys.readouterr().out
    assert "?" not in out.split("promotion")[-1]


def test_dry_run_writes_no_verdict_file(tmp_path, monkeypatch):
    """``--dry-run`` prints the table and writes nothing.

    The mutation this kills: dropping ``dry_run=args.dry_run`` from the write.
    """
    phase1 = tmp_path / "phase1.json"
    phase1.write_text(
        '{"per_paper": [{"key": "AAAA1111", "mattr_100": 0.7}], '
        '"aggregate": {"regression": {}}}', encoding="utf-8")
    out_path = tmp_path / "phase3.json"
    monkeypatch.setattr(promotion, "PHASE1", phase1)
    monkeypatch.setattr(promotion, "OUT", out_path)

    assert promotion.main(["--dry-run"]) == 0
    assert not out_path.exists()


def test_a_written_verdict_file_carries_provenance(tmp_path, monkeypatch):
    """The verdicts must be traceable to the phase 1 file behind them."""
    import json

    phase1 = tmp_path / "phase1.json"
    phase1.write_text(
        '{"per_paper": [{"key": "AAAA1111", "mattr_100": 0.7}], '
        '"aggregate": {"regression": {}}}', encoding="utf-8")
    out_path = tmp_path / "phase3.json"
    monkeypatch.setattr(promotion, "PHASE1", phase1)
    monkeypatch.setattr(promotion, "OUT", out_path)

    assert promotion.main([]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["provenance"]["script"] == "phase3_promotion.py"
    assert payload["provenance"]["inputs"][0]["sha256"]


def test_a_missing_phase1_input_exits_two(tmp_path, monkeypatch, capsys):
    """A missing input is a diagnostic, not a traceback."""
    monkeypatch.setattr(promotion, "PHASE1", tmp_path / "absent.json")

    assert promotion.main([]) == 2
    assert "not found" in capsys.readouterr().err
