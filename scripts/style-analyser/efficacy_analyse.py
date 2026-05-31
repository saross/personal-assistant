#!/usr/bin/env python3
"""
efficacy_analyse.py — paired analysis of the style-guide efficacy experiment
(Workstream G, roadmap item #1).

Consumes `scores.json` (from `efficacy_score.py`) and produces the paired
comparison of the three conditions:

  * C0 — plain
  * C1 — generic academic   (the Shawn-specificity control)
  * C2 — full guide + exemplars

Pairing unit = topic. For each (topic, condition) cell we take the MEDIAN
Mahalanobis distance over its replicates (robust to an outlier generation),
then pair across topics. The decision-relevant comparison is C2 vs C1: does the
author-specific guide beat a generic academic-register instruction?

Tests (all one-sided in the pre-registered direction "the later condition is
closer to the corpus", plus two-sided for completeness):
  * Exact sign-flip permutation test on the mean paired difference. With n
    topics there are 2**n sign assignments; for n <= ~20 this is enumerated
    exactly, so the pilot (n=4, min p = 1/16 = 0.0625) is honestly reported as
    underpowered rather than faked.
  * Wilcoxon signed-rank as a rank-based cross-check (guarded for small n).
  * Effect size = median paired difference / corpus LOO standard deviation.

Also: envelope-band migration, gate pass-count shift (caveated as
teaching-to-the-test), on-domain vs off-domain stratum breakdown, and the
per-feature standardised-|z| profile (which features the guide moves toward the
corpus, and which it still misses — the latter feeds guide improvement).

CPU-only, deterministic, no network. Writes `analysis.md` + `analysis.json`.

Usage
-----
    python efficacy_analyse.py
    python efficacy_analyse.py --experiment-dir DIR
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPERIMENT_DIR = REPO_ROOT / "data/experiments/style-efficacy-2026-05-31"

CONDITIONS = ["C0", "C1", "C2"]
COND_LABEL = {
    "C0": "plain",
    "C1": "generic academic",
    "C2": "full guide + exemplars",
}
# Pairs reported as (baseline, treatment): positive diff = treatment closer.
PAIRS = [("C1", "C2"), ("C0", "C2"), ("C0", "C1")]


def cell_median_distance(rows: list[dict]) -> float:
    return statistics.median(r["distance"] for r in rows)


def modal_band(rows: list[dict]) -> str:
    bands = [r["envelope_band"] for r in rows]
    return statistics.mode(bands) if bands else "?"


def exact_signflip_p(diffs: list[float]) -> tuple[float, float]:
    """Exact sign-flip permutation p-values (one-sided greater, two-sided).

    Null: each signed difference is equally likely +d or -d (symmetry about 0).
    Statistic: the sum of signed differences. Enumerates all 2**n flips.
    Returns (p_one_sided_greater, p_two_sided). Drops exact zeros from the
    flip set (they contribute equally to both tails) per the standard
    sign-flip convention, but keeps them in the observed statistic.
    """
    nz = [d for d in diffs if d != 0.0]
    n = len(nz)
    if n == 0:
        return (1.0, 1.0)
    observed = sum(diffs)
    ge = 0
    le = 0
    total = 0
    base = sum(diffs) - sum(nz)  # contribution of any zero diffs (=0, explicit)
    for signs in itertools.product((1, -1), repeat=n):
        stat = base + sum(s * abs(d) for s, d in zip(signs, nz))
        total += 1
        if stat >= observed:
            ge += 1
        if stat <= observed:
            le += 1
    p_greater = ge / total
    p_two = min(1.0, 2.0 * min(ge, le) / total)
    return (round(p_greater, 5), round(p_two, 5))


def wilcoxon_guarded(diffs: list[float]) -> dict:
    nz = [d for d in diffs if d != 0.0]
    if len(nz) < 1:
        return {"available": False, "reason": "all differences zero"}
    try:
        from scipy.stats import wilcoxon
        stat, p_two = wilcoxon(nz, alternative="two-sided")
        _, p_gt = wilcoxon(nz, alternative="greater")
        return {"available": True, "statistic": round(float(stat), 4),
                "p_two_sided": round(float(p_two), 5),
                "p_one_sided_greater": round(float(p_gt), 5),
                "n_nonzero": len(nz)}
    except Exception as exc:  # noqa: BLE001 - report, do not crash analysis
        return {"available": False, "reason": str(exc)}


def paired_block(cells: dict, topics: list[str], baseline: str,
                 treatment: str, loo_sd: float) -> dict:
    """Paired stats for one (baseline, treatment) comparison over `topics`."""
    diffs: list[float] = []
    per_topic: list[dict] = []
    for t in topics:
        b = cells[(t, baseline)]
        x = cells[(t, treatment)]
        d = b - x  # positive: treatment is closer to corpus
        diffs.append(d)
        per_topic.append({"topic_id": t, "baseline_dist": round(b, 4),
                          "treatment_dist": round(x, 4), "diff": round(d, 4)})
    n = len(diffs)
    wins = sum(1 for d in diffs if d > 0)
    p_gt, p_two = exact_signflip_p(diffs)
    median_d = statistics.median(diffs) if diffs else 0.0
    mean_d = statistics.mean(diffs) if diffs else 0.0
    return {
        "baseline": baseline,
        "treatment": treatment,
        "n_topics": n,
        "per_topic": per_topic,
        "median_diff": round(median_d, 4),
        "mean_diff": round(mean_d, 4),
        "win_rate": f"{wins}/{n}",
        "effect_size_loo_sd": (round(median_d / loo_sd, 3)
                               if loo_sd else None),
        "permutation_p_one_sided_greater": p_gt,
        "permutation_p_two_sided": p_two,
        "wilcoxon": wilcoxon_guarded(diffs),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--experiment-dir", type=Path,
                    default=DEFAULT_EXPERIMENT_DIR)
    args = ap.parse_args()

    scores_path = args.experiment_dir / "scores.json"
    if not scores_path.exists():
        print(f"No scores.json: {scores_path}")
        return 2
    data = json.loads(scores_path.read_text(encoding="utf-8"))
    rows = data["results"]
    loo_sd = data["loo_summary"]["stdev"]
    loo_max = data["loo_summary"]["max"]

    # Group rows by (topic, condition).
    by_cell: dict[tuple[str, str], list[dict]] = {}
    stratum_of: dict[str, str] = {}
    for r in rows:
        by_cell.setdefault((r["topic_id"], r["condition"]), []).append(r)
        stratum_of[r["topic_id"]] = r["stratum"]

    # Topics that have all three conditions present (complete pairs only).
    all_topics = sorted({t for (t, _c) in by_cell})
    topics = [t for t in all_topics
              if all((t, c) in by_cell for c in CONDITIONS)]
    incomplete = [t for t in all_topics if t not in topics]

    cells_dist = {(t, c): cell_median_distance(by_cell[(t, c)])
                  for t in topics for c in CONDITIONS}
    cells_band = {(t, c): modal_band(by_cell[(t, c)])
                  for t in topics for c in CONDITIONS}
    cells_gate = {(t, c): statistics.median(x["gate_n_pass"]
                                            for x in by_cell[(t, c)])
                  for t in topics for c in CONDITIONS}

    # Paired comparisons (overall + per stratum).
    comparisons = {f"{b}_vs_{tr}": paired_block(cells_dist, topics, b, tr, loo_sd)
                   for (b, tr) in PAIRS}
    strata = sorted(set(stratum_of[t] for t in topics))
    by_stratum: dict[str, dict] = {}
    for s in strata:
        s_topics = [t for t in topics if stratum_of[t] == s]
        by_stratum[s] = {
            f"{b}_vs_{tr}": paired_block(cells_dist, s_topics, b, tr, loo_sd)
            for (b, tr) in PAIRS
        }

    # Envelope-band migration (topic-level modal band per condition).
    band_counts = {c: {"within": 0, "borderline": 0, "outside": 0}
                   for c in CONDITIONS}
    for t in topics:
        for c in CONDITIONS:
            band_counts[c][cells_band[(t, c)]] += 1

    # Gate pass-count per condition (mean of topic-level medians).
    gate_mean = {c: round(statistics.mean(cells_gate[(t, c)] for t in topics), 2)
                 for c in CONDITIONS} if topics else {}

    # Per-feature mean |z| per condition (closeness to corpus per feature).
    feat_abs_z: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        for fd in r["feature_deltas"]:
            feat_abs_z.setdefault(fd["feature"], {}).setdefault(
                r["condition"], []).append(abs(fd["z"]))
    feature_profile = []
    for feat, by_cond in sorted(feat_abs_z.items()):
        entry = {"feature": feat}
        for c in CONDITIONS:
            vals = by_cond.get(c, [])
            entry[f"mean_abs_z_{c}"] = (round(statistics.mean(vals), 3)
                                        if vals else None)
        if entry.get("mean_abs_z_C0") is not None and \
           entry.get("mean_abs_z_C2") is not None:
            entry["c2_improvement_vs_c0"] = round(
                entry["mean_abs_z_C0"] - entry["mean_abs_z_C2"], 3)
        feature_profile.append(entry)
    feature_profile.sort(key=lambda e: -(e.get("c2_improvement_vs_c0") or 0))

    analysis = {
        "experiment": data["experiment"],
        "n_passages": data["n_passages"],
        "n_complete_topics": len(topics),
        "incomplete_topics": incomplete,
        "loo_summary": data["loo_summary"],
        "underpowered_note": (
            f"n={len(topics)} complete topics; exact permutation min one-sided "
            f"p = 1/2^{len(topics)} = {1/2**len(topics):.4g}. "
            "A pilot (n<=4) cannot reach conventional significance; read the "
            "effect direction, win-rate and LOO-SD magnitude, not the p-value."
        ),
        "cell_distances": {f"{t}|{c}": round(cells_dist[(t, c)], 4)
                           for t in topics for c in CONDITIONS},
        "comparisons_overall": comparisons,
        "comparisons_by_stratum": by_stratum,
        "band_migration": band_counts,
        "gate_mean_pass": gate_mean,
        "feature_profile": feature_profile,
    }
    (args.experiment_dir / "analysis.json").write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- Human-readable report ----------------------------------------
    L: list[str] = []
    L.append(f"# Efficacy analysis — {data['experiment']}")
    L.append("")
    L.append(f"- Passages scored: **{data['n_passages']}** across "
             f"**{len(topics)}** complete topics "
             f"({', '.join(topics)}).")
    if incomplete:
        L.append(f"- Incomplete topics (excluded from pairing): {incomplete}")
    L.append(f"- Corpus LOO envelope: max **{loo_max}** (within-band ceiling), "
             f"sd **{loo_sd}** (effect-size unit).")
    L.append(f"- {analysis['underpowered_note']}")
    L.append("")
    L.append("## Per-condition distance (lower = closer to corpus)")
    L.append("")
    L.append("| Topic | Stratum | C0 plain | C1 generic | C2 guide |")
    L.append("|---|---|--:|--:|--:|")
    for t in topics:
        L.append(f"| {t} | {stratum_of[t]} | "
                 f"{cells_dist[(t,'C0')]:.3f} | {cells_dist[(t,'C1')]:.3f} | "
                 f"{cells_dist[(t,'C2')]:.3f} |")
    L.append("")
    L.append("## Paired comparisons (median distance per topic)")
    L.append("")
    L.append("Positive diff = treatment condition closer to corpus. "
             "`C1_vs_C2` is the decision-relevant test (author-specific guide "
             "vs generic academic register).")
    L.append("")
    L.append("| Comparison | median Δ | mean Δ | win-rate | Δ in LOO-SD | "
             "perm p (1-sided) | Wilcoxon p (1-sided) |")
    L.append("|---|--:|--:|--:|--:|--:|--:|")
    for key in (f"{b}_vs_{tr}" for (b, tr) in PAIRS):
        cmp = comparisons[key]
        w = cmp["wilcoxon"]
        wp = (f"{w['p_one_sided_greater']}" if w.get("available")
              else "n/a")
        L.append(f"| {COND_LABEL[cmp['baseline']]} → "
                 f"{COND_LABEL[cmp['treatment']]} | {cmp['median_diff']} | "
                 f"{cmp['mean_diff']} | {cmp['win_rate']} | "
                 f"{cmp['effect_size_loo_sd']} | "
                 f"{cmp['permutation_p_one_sided_greater']} | {wp} |")
    L.append("")
    L.append("## Envelope-band migration (topic-level modal band)")
    L.append("")
    L.append("| Condition | within | borderline | outside |")
    L.append("|---|--:|--:|--:|")
    for c in CONDITIONS:
        b = band_counts[c]
        L.append(f"| {c} {COND_LABEL[c]} | {b['within']} | "
                 f"{b['borderline']} | {b['outside']} |")
    L.append("")
    L.append("## 8-metric gate (mean pass-count; teaching-to-the-test — "
             "interpret with caution)")
    L.append("")
    L.append("| Condition | mean gate pass /8 |")
    L.append("|---|--:|")
    for c in CONDITIONS:
        L.append(f"| {c} {COND_LABEL[c]} | {gate_mean.get(c)} |")
    L.append("")
    L.append("## Per-stratum (on-domain vs off-domain) — C1→C2 and C0→C2")
    L.append("")
    L.append("| Stratum | comparison | median Δ | win-rate | Δ in LOO-SD |")
    L.append("|---|---|--:|--:|--:|")
    for s in strata:
        for (b, tr) in (("C1", "C2"), ("C0", "C2")):
            cmp = by_stratum[s][f"{b}_vs_{tr}"]
            L.append(f"| {s} | {b}→{tr} | {cmp['median_diff']} | "
                     f"{cmp['win_rate']} | {cmp['effect_size_loo_sd']} |")
    L.append("")
    L.append("## Per-feature profile (mean |z| vs corpus; lower = closer)")
    L.append("")
    L.append("Sorted by C2's improvement over C0. Features where C2's |z| is "
             "still large are the guide's misses (candidates for revision).")
    L.append("")
    L.append("| Feature | C0 |z| | C1 |z| | C2 |z| | C2 gain vs C0 |")
    L.append("|---|--:|--:|--:|--:|")
    for e in feature_profile:
        L.append(f"| {e['feature']} | {e.get('mean_abs_z_C0')} | "
                 f"{e.get('mean_abs_z_C1')} | {e.get('mean_abs_z_C2')} | "
                 f"{e.get('c2_improvement_vs_c0')} |")
    L.append("")
    (args.experiment_dir / "analysis.md").write_text(
        "\n".join(L) + "\n", encoding="utf-8")

    print(f"Wrote analysis.md + analysis.json to "
          f"{args.experiment_dir.relative_to(REPO_ROOT)}/")
    # Console summary of the headline comparison.
    head = comparisons["C1_vs_C2"]
    print(f"\nHeadline (C1 generic → C2 guide): median Δ={head['median_diff']} "
          f"({head['effect_size_loo_sd']} LOO-SD), win-rate {head['win_rate']}, "
          f"perm p(1-sided)={head['permutation_p_one_sided_greater']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
