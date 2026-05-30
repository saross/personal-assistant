#!/usr/bin/env python3
"""
Phase 3 — Kumar aggregation rule formalisation.

Consumes the Phase 1 measurement output (phase1-results-clean.json) and
applies the deterministic promotion algorithm from plan §4.2 to every
metric for which per-paper rates are available.

Promotion rules (plan §4.2 / agent v2.2 lines 165-171):

    attested              | n_papers >=3 AND n_occ >=5 AND CV <=1.5
    attested-concentrated | n_papers >=3 AND CV >1.5
    attested-rarely       | 1<=n_papers<=2 OR (n_papers>=3 AND n_occ<5)
    absent-when-searched  | n_occ<=2 AND n_papers<=1 (with deliberate-
                          | search flag — applied externally per metric)
    derived-by-inference  | external annotation; not produced here

`n_papers_present` here = count of papers with per-paper rate > 0.
`n_occ` is the corpus-wide raw count if available, otherwise rounded
sum of (per-paper rate x per-paper word count).

CV = sample stdev (Bessel) of per-paper rates / mean of per-paper rates.

Output: data/style-corpus/phase3-promotion-clean.json
- one entry per promotable metric, with all stats + verdict + rationale
- a `coverage` block naming which §-claims this script provides verdicts
  for vs which require external annotation by the agent

No LLM calls. Deterministic. Re-runs are cheap; tune CV threshold or
n_occ floor by editing the constants below.
"""
from __future__ import annotations
import json
import statistics
import sys
from pathlib import Path

PHASE1 = Path("data/style-corpus/phase1-results-clean.json")
OUT = Path("data/style-corpus/phase3-promotion-clean.json")

# Promotion thresholds (plan §4.2).
CV_THRESHOLD = 1.5
N_OCC_FLOOR = 5
N_PAPERS_FLOOR = 3

# Bimodality detector (v2.3 addition, 2026-05-30).
# A distribution is flagged as bimodal when the largest INNER consecutive
# gap (one that leaves at least BIMODALITY_MIN_PER_SIDE papers on each
# side) is at least BIMODALITY_GAP_FRACTION of the overall range.
# The min-per-side constraint rules out single-outlier cases (a gap
# between the 17th and 18th paper isn't a bimodal cluster split — it's
# one outlier).
# Bimodal distributions promote to `attested-concentrated` even when
# CV <= CV_THRESHOLD: they signal a cluster split (e.g. fieldwork-
# register vs essay-register) that CV alone does not capture.
BIMODALITY_GAP_FRACTION = 0.25
BIMODALITY_MIN_PER_SIDE = 3  # gap must leave >=3 papers on EACH side
BIMODALITY_MIN_PAPERS = 2 * BIMODALITY_MIN_PER_SIDE  # 6


def detect_bimodal(rates: list[float]) -> tuple[bool, float, float]:
    """Return (is_bimodal, max_inner_gap, normalised_gap).

    Considers only "inner" gaps — gaps that leave at least
    BIMODALITY_MIN_PER_SIDE papers above and below — so single outliers
    do not trigger the detector. The largest such inner gap, divided
    by the overall range, must reach BIMODALITY_GAP_FRACTION.
    """
    if len(rates) < BIMODALITY_MIN_PAPERS:
        return False, 0.0, 0.0
    s = sorted(rates)
    rng = s[-1] - s[0]
    if rng == 0:
        return False, 0.0, 0.0
    # Inner gaps: between index i and i+1, with i+1 >= MIN_PER_SIDE
    # (i.e. at least MIN_PER_SIDE papers at or below) and len(s)-(i+1) >=
    # MIN_PER_SIDE (at least MIN_PER_SIDE papers above).
    inner_gaps: list[float] = []
    for i in range(BIMODALITY_MIN_PER_SIDE - 1,
                   len(s) - BIMODALITY_MIN_PER_SIDE):
        inner_gaps.append(s[i + 1] - s[i])
    if not inner_gaps:
        return False, 0.0, 0.0
    max_gap = max(inner_gaps)
    normalised = max_gap / rng
    return normalised >= BIMODALITY_GAP_FRACTION, max_gap, normalised


# -- Promotion algorithm -----------------------------------------------------

def promote(metric: str,
            per_paper_rates: list[float],
            paper_keys: list[str] | None = None,
            n_occ: int | None = None,
            section: str = "") -> dict:
    """Apply plan §4.2 promotion rules to a single metric.

    `per_paper_rates`: one rate per paper (any unit — per-1k, per-100w,
        ratio, raw count — what matters is variance across papers).
    `paper_keys`: parallel list of paper keys aligned to per_paper_rates.
        Used to emit explicit `papers_present` / `papers_absent` lists
        that downstream consumers (e.g. the style-guide-generating
        agent) copy verbatim into "Where it appears" / "Where it does
        not" lists. Required for the confabulation guard.
    `n_occ`: corpus-wide total occurrences when known; if None, the
        verdict can still resolve on n_papers + CV alone.
    """
    n_total = len(per_paper_rates)
    n_present = sum(1 for r in per_paper_rates if r > 0)
    mean = statistics.mean(per_paper_rates) if per_paper_rates else 0.0
    stdev = (
        statistics.stdev(per_paper_rates) if len(per_paper_rates) > 1 else 0.0
    )
    cv = stdev / mean if mean > 0 else 0.0

    # Build verbatim paper-key lists for the confabulation guard.
    papers_present: list[dict] = []
    papers_absent: list[str] = []
    if paper_keys is not None and len(paper_keys) == len(per_paper_rates):
        paired = list(zip(paper_keys, per_paper_rates))
        present_pairs = [(k, r) for k, r in paired if r > 0]
        present_pairs.sort(key=lambda kv: -kv[1])  # descending rate
        papers_present = [
            {"key": k, "rate": round(r, 4)} for k, r in present_pairs
        ]
        papers_absent = sorted(k for k, r in paired if r == 0)

    # Bimodality detection
    is_bimodal, max_gap, gap_frac = detect_bimodal(per_paper_rates)

    # Decide promotion
    if n_present >= N_PAPERS_FLOOR:
        if n_occ is None or n_occ >= N_OCC_FLOOR:
            if cv > CV_THRESHOLD:
                status = "attested-concentrated"
                rationale = (
                    f"n_papers={n_present} >= {N_PAPERS_FLOOR}"
                    f" AND CV={cv:.3f} > {CV_THRESHOLD}"
                )
            elif is_bimodal:
                status = "attested-concentrated"
                rationale = (
                    f"n_papers={n_present} >= {N_PAPERS_FLOOR}"
                    f" AND bimodality detected (max consecutive gap"
                    f" {max_gap:.3f} = {gap_frac:.1%} of range,"
                    f" >= {BIMODALITY_GAP_FRACTION:.0%} threshold);"
                    f" CV={cv:.3f} alone was below {CV_THRESHOLD}"
                )
            else:
                status = "attested"
                rationale = (
                    f"n_papers={n_present} >= {N_PAPERS_FLOOR}"
                    + (f" AND n_occ={n_occ} >= {N_OCC_FLOOR}"
                       if n_occ is not None else "")
                    + f" AND CV={cv:.3f} <= {CV_THRESHOLD}"
                    f" AND not bimodal (gap_frac={gap_frac:.2f})"
                )
        else:
            status = "attested-rarely"
            rationale = (
                f"n_papers={n_present} >= {N_PAPERS_FLOOR}"
                f" but n_occ={n_occ} < {N_OCC_FLOOR}"
            )
    elif n_present >= 1:
        status = "attested-rarely"
        rationale = f"n_papers={n_present} < {N_PAPERS_FLOOR}"
    else:
        # n_present == 0; deliberate-search flag determines absent-when-
        # searched vs not-searched. Caller may post-process.
        status = "absent-when-searched-candidate"
        rationale = (
            f"n_papers={n_present} == 0; "
            "external deliberate-search flag required to promote to "
            "`absent-when-searched`"
        )

    return {
        "metric": metric,
        "section": section,
        "n_papers_total": n_total,
        "n_papers_present": n_present,
        "n_occ": n_occ,
        "mean_rate": round(mean, 4),
        "stdev_rate": round(stdev, 4),
        "cv": round(cv, 4),
        "min_rate": round(min(per_paper_rates), 4) if per_paper_rates else 0.0,
        "max_rate": round(max(per_paper_rates), 4) if per_paper_rates else 0.0,
        "bimodal": is_bimodal,
        "max_consecutive_gap": round(max_gap, 4),
        "bimodality_gap_fraction": round(gap_frac, 4),
        "promotion": status,
        "promotion_rationale": rationale,
        "papers_present": papers_present,
        "papers_absent": papers_absent,
    }


# -- Metric extraction helpers ----------------------------------------------

def pp_rate(per_paper: list[dict], path: str) -> list[float]:
    """Pull per-paper rate using a dotted path, e.g. 'sentence_stats.mean'."""
    keys = path.split(".")
    rates: list[float] = []
    for p in per_paper:
        v = p
        for k in keys:
            if isinstance(v, dict) and k in v:
                v = v[k]
            else:
                v = None
                break
        if isinstance(v, (int, float)):
            rates.append(float(v))
    return rates


def pp_count(per_paper: list[dict], path: str) -> int:
    """Sum corpus-wide raw count from per-paper records."""
    return int(sum(v for v in pp_rate(per_paper, path)))


def main() -> int:
    if not PHASE1.exists():
        print(f"Phase 1 input not found: {PHASE1}", file=sys.stderr)
        return 2

    data = json.load(open(PHASE1))
    per_paper = data["per_paper"]
    agg_reg = data["aggregate"]["regression"]

    # Metrics catalogue: (section, metric_name, per_paper_path, n_occ)
    # Where n_occ comes from corpus-level regression counts when present.
    metrics_spec = [
        ("1.1",  "first_plural_per_1k",       "regression.first_plural_per_1k",   agg_reg.get("first_plural_count")),
        ("1.2",  "mattr_100",                  "mattr_100",                        None),
        ("1.2",  "hapax_ratio",                "hapax_ratio",                      None),
        ("4.2",  "hedge_per_100w",             "hedge_per_100w",                   None),
        ("5.1",  "passive_ratio",              "passive_ratio",                    None),
        ("5.2",  "nominalisation_per_1000w",   "nominalisation_per_1000w",         None),
        ("5.3",  "mean_dep_depth",             "mean_dep_depth",                   None),
        ("6.1",  "sentence_mean",              "sentence_stats.mean",              None),
        ("6.1",  "sentence_median",            "sentence_stats.median",            None),
        ("6.2",  "semicolon_per_1k",           "regression.semicolon_per_1k",      agg_reg.get("semicolon_count")),
        ("6.3",  "em_dash_per_1k",             "regression.em_dash_per_1k",        agg_reg.get("em_dash_count")),
        ("6.4",  "announcement_colon_per_1k",  "announcement_colon_per_1k",        None),
        ("6.5",  "paragraph_median_words",     "paragraph_stats.median",           None),
        ("6.5",  "paragraph_mean_words",       "paragraph_stats.mean",             None),
        ("6.7",  "concession_rate",            "concession_rate",                  None),
    ]

    # Per-subordinator counts (§6.6)
    subord_counts = [
        ("6.6", "while_count",   "regression.while_count",   agg_reg.get("while_count")),
        ("6.6", "however_count", "regression.however_count", agg_reg.get("however_count")),
        ("6.6", "although_count","regression.although_count",agg_reg.get("although_count")),
        ("6.6", "whilst_count",  "regression.whilst_count",  agg_reg.get("whilst_count")),
        ("3.4", "pace_count",    "regression.pace_count_case_sensitive",
                                                            agg_reg.get("pace_count_case_sensitive")),
    ]
    metrics_spec.extend(subord_counts)

    # Paper keys aligned with per_paper rate lists (needed for verbatim
    # papers_present / papers_absent lists used by the confabulation guard).
    paper_keys = [p["key"] for p in per_paper]

    promotions = []
    for section, name, path, n_occ in metrics_spec:
        rates = pp_rate(per_paper, path)
        if not rates:
            continue
        # Per-paper rates may have None values dropped; re-derive aligned
        # paper_keys for the rates we actually collected.
        keys_for_rates = []
        for p in per_paper:
            v = p
            for k in path.split("."):
                if isinstance(v, dict) and k in v:
                    v = v[k]
                else:
                    v = None
                    break
            if isinstance(v, (int, float)):
                keys_for_rates.append(p["key"])
        promotions.append(promote(
            name, rates, paper_keys=keys_for_rates,
            n_occ=n_occ, section=section,
        ))

    # UK orthography pairs (§8.1) — special handling: each pair gets its
    # own verdict, plus an aggregate UK:US ratio.
    uk_us_aggregate = agg_reg.get("uk_us_counts", {})
    uk_pair_verdicts = []
    if uk_us_aggregate:
        # Build per-paper rates per UK token from aggregate.regression counts
        # (per-paper UK counts would require re-walking; for now we report
        # the aggregate verdict only — n_papers from pp.regression.uk_us_counts)
        # Each paper has its own uk_us_counts dict.
        pp_uk_us = [p.get("regression", {}).get("uk_us_counts", {}) for p in per_paper]
        for uk_token, count in uk_us_aggregate.items():
            # Skip US tokens for verdict (we want UK-side presence)
            us_pair = {
                "analyse": "analyze", "analysed": "analyzed",
                "organisation": "organization", "organisations": "organizations",
                "characterise": "characterize", "characterised": "characterized",
                "recognise": "recognize", "recognised": "recognized",
                "utilise": "utilize", "utilised": "utilized",
                "emphasise": "emphasize",
                "behaviour": "behavior", "colour": "color", "labour": "labor",
                "centre": "center", "centres": "centers",
                "catalogue": "catalog", "metre": "meter",
            }
            if uk_token not in us_pair:
                continue
            us_token = us_pair[uk_token]
            us_count = uk_us_aggregate.get(us_token, 0)
            per_paper_uk_counts = [d.get(uk_token, 0) for d in pp_uk_us]
            uk_pair_verdicts.append({
                "pair": f"{uk_token}/{us_token}",
                "uk_aggregate": count,
                "us_aggregate": us_count,
                "uk_n_papers_present": sum(1 for v in per_paper_uk_counts if v > 0),
                "us_n_papers_present": sum(
                    1 for v in [d.get(us_token, 0) for d in pp_uk_us] if v > 0
                ),
                "uk_preferred": count > us_count,
            })

    # Coverage block: §-claims this script provides verdicts for
    sections_covered = sorted({m["section"] for m in promotions})
    # All §§N.N claims in the v2.2 guide (from earlier enumeration)
    all_sections = [
        "1.1", "1.2", "1.3",
        "2.1", "2.2", "2.3",
        "3.1", "3.2", "3.3", "3.4",
        "4.1", "4.2", "4.3", "4.4",
        "5.1", "5.2", "5.3",
        "6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7",
        "7.1", "7.2", "7.3", "7.4",
        "8.1", "8.2", "8.3", "8.4",
        "9.1", "9.2", "9.3", "9.4", "9.5",
        "10.1", "10.2", "10.3", "10.4", "10.5", "10.6", "10.7",
        "11.1", "11.2", "11.3", "11.4", "11.5", "11.6", "11.7", "11.8",
    ]
    sections_not_covered = [s for s in all_sections if s not in sections_covered]

    out = {
        "phase1_input": str(PHASE1),
        "thresholds": {
            "cv_threshold": CV_THRESHOLD,
            "n_occ_floor": N_OCC_FLOOR,
            "n_papers_floor": N_PAPERS_FLOOR,
        },
        "promotion_rules_note": (
            "Per plan §4.2 / agent v2.2. attested = n_papers>=3 AND "
            "n_occ>=5 AND CV<=1.5. attested-concentrated = n_papers>=3 AND "
            "CV>1.5. attested-rarely = 1<=n_papers<=2 OR (n_papers>=3 AND "
            "n_occ<5). absent-when-searched requires an external deliberate-"
            "search flag (here marked as `absent-when-searched-candidate`)."
        ),
        "n_metrics_promoted": len(promotions),
        "promotions": promotions,
        "uk_orthography_pairs": uk_pair_verdicts,
        "coverage": {
            "sections_with_pre_computed_verdict": sections_covered,
            "sections_requiring_in_run_status_assignment": sections_not_covered,
            "n_covered": len(sections_covered),
            "n_uncovered": len(sections_not_covered),
        },
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"Wrote {OUT}")
    print(f"\nMetrics promoted: {len(promotions)}")
    print(f"Sections covered:   {sections_covered}")
    print(f"\n{'§':5} {'metric':32} {'n_pres':>6} {'n_occ':>6} {'mean':>8} {'CV':>7}  promotion")
    print("-" * 95)
    for p in promotions:
        print(f"{p['section']:5} {p['metric']:32} "
              f"{p['n_papers_present']:>6} {str(p['n_occ'] or '?'):>6} "
              f"{p['mean_rate']:>8.3f} {p['cv']:>7.3f}  {p['promotion']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
