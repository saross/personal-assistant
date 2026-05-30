#!/usr/bin/env python3
"""
phase5_evaluator.py — corpus-style-analyser v2 Phase 5 downstream evaluator.

Per ~/personal-assistant/wiki/planning/style-guide-agent-v2-implementation-plan.md
§6.3 (and §9 decision 10): a deterministic, CPU-only evaluator that takes
arbitrary text *claiming to apply the academic style guide* and reports

  (a) the Mahalanobis distance from the text to the corpus centroid in the
      Phase 1 feature space, with per-feature standardised deltas and an
      empirical (leave-one-paper-out) envelope classification; and
  (b) a pass/fail verdict against the 8-metric tolerance gate documented in
      Appendix E of the v2.3 style guide.

This is a *downstream* tool: the style-guide-generating agent
(`corpus-style-analyser-v2`) produces the guide; this script scores text that
was written under it. It makes NO LLM calls and NO network calls — pure CPU +
scikit-learn + spaCy. It follows the same two-script shape as Phase 3
(`phase3_promotion.py` computes a deterministic algorithm and emits JSON;
`phase3_guide_verifier.py` is the deterministic regression gate): Phase 5 is the
generation-time gate that complements the guide-time verifier.

Design notes (the non-obvious decisions)
-----------------------------------------
* **Identical feature extraction.** Input text is measured by importing
  `process_paper` from `phase1_pipeline.py`, so every feature is computed with
  the exact same code path that produced the corpus vectors in
  `phase1-results-clean.json`. No re-implementation, no drift.

* **Ledoit-Wolf shrinkage.** With 18 papers and ~12 features the raw sample
  covariance is badly conditioned (p approaches n), so the Mahalanobis metric
  is estimated with `sklearn.covariance.LedoitWolf`. Features are z-scored
  against the corpus mean/std first so the shrinkage target (a scaled identity)
  is sensible across features on very different scales (MATTR ≈ 0.73 vs
  semicolons ≈ 6.5 per 1k).

* **Bimodal metrics are excluded from the single centroid.** Per
  `phase3-promotion-clean.json`, `em_dash_per_1k`, `mean_dep_depth` and
  `pace_count` are flagged `bimodal: true`. A single Gaussian centroid is the
  wrong abstraction for these: 12 of 18 papers carry exactly zero em-dashes, so
  a zero-em-dash text is perfectly corpus-typical, yet it would sit far from a
  naive centroid. mean_dep_depth splits 5-vs-13 across a ~1-level range. We take
  plan §6.3 option (a): drop every phase3-bimodal metric from the Mahalanobis
  space and report it separately in an advisory block with its empirical
  cluster ranges and the input's cluster assignment. The exclusion set is read
  from phase3 at run time, so it self-syncs if the thresholds change.

* **Empirical envelope, not just chi-square.** The squared Mahalanobis distance
  of a held-out sample is only chi-square(df) distributed under multivariate
  normality, which 18 papers cannot establish. The primary interpretive frame
  is therefore the empirical leave-one-paper-out (LOO) distance distribution of
  the 18 corpus papers; the chi-square percentile is reported as a secondary
  parametric cross-check carrying an explicit normality caveat.

Usage
-----
    # Score a file
    python phase5_evaluator.py --text path/to/generated.md

    # Score a literal passage
    python phase5_evaluator.py --passage "We analysed the assemblage; ..."

    # Em-dash gate defaults to the modern 2026+ ceiling (≤0.20/1k). To score
    # against the legacy two-sided corpus band (0.572 ±0.20) instead:
    python phase5_evaluator.py --text gen.md --corpus-em-dash

    # JSON instead of markdown
    python phase5_evaluator.py --text gen.md --format json

    # Leave-one-paper-out validation report + sanity-check fixtures
    python phase5_evaluator.py --validate \
        --report data/style-corpus/phase5-validation-report.md

Exit code is non-zero when the 8-metric gate FAILS (for CI / pre-publish
gating), mirroring `phase3_guide_verifier.py`. In `--validate` mode the exit
code is non-zero when a sanity-check expectation is violated.

Requires `scikit-learn>=1.4`, `scipy>=1.10`, `spacy==3.8.14` with
`en_core_web_sm==3.8.0`, `numpy` — all present in `~/Code/write-like-me/.venv`
(scikit-learn + scipy added 2026-05-30 for this script).
"""
# UK/Australian English throughout (per global CLAUDE.md). Third-party API
# spellings (e.g. `sklearn.covariance`) are retained as imported.

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.stats import chi2
from sklearn.covariance import LedoitWolf

# Make the sibling phase1_pipeline importable regardless of cwd. Importing it
# is side-effect-free: the module only defines constants/functions and guards
# main() behind `if __name__ == "__main__"`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase1_pipeline as p1  # noqa: E402  (after sys.path manipulation)

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

PHASE1_DEFAULT = Path("data/style-corpus/phase1-results-clean.json")
PHASE3_DEFAULT = Path("data/style-corpus/phase3-promotion-clean.json")
EXTRACTED_DEFAULT = Path("data/style-corpus/extracted")

# ---------------------------------------------------------------------------
# Mahalanobis feature space (plan §6.3 / §9 decision 10)
# ---------------------------------------------------------------------------

# Candidate continuous, length-normalised features. Each tuple is
# (dotted_path_into_per_paper_record, human_label, phase3_metric_name_or_None).
# A candidate whose phase3 metric is flagged `bimodal: true` is moved out of the
# Mahalanobis space at run time and reported in the advisory block instead.
# Raw counts (while_count, however_count, …) are deliberately NOT candidates:
# they are length-dependent and would conflate document length with style.
CANDIDATE_FEATURES: list[tuple[str, str, str | None]] = [
    ("sentence_stats.mean",          "Mean sentence length (words)",  "sentence_mean"),
    ("sentence_stats.stdev",         "Sentence-length stdev",          None),
    ("paragraph_stats.mean",         "Mean paragraph length (words)", "paragraph_mean_words"),
    ("mattr_100",                    "MATTR-100",                     "mattr_100"),
    ("hapax_ratio",                  "Hapax ratio",                   "hapax_ratio"),
    ("passive_ratio",                "Passive ratio",                 "passive_ratio"),
    ("nominalisation_per_1000w",     "Nominalisation /1000w",         "nominalisation_per_1000w"),
    ("announcement_colon_per_1k",    "Announcement colon /1k",        "announcement_colon_per_1k"),
    ("hedge_per_100w",               "Hedge density /100w",           "hedge_per_100w"),
    ("concession_rate",              "Concession rate",               "concession_rate"),
    ("regression.first_plural_per_1k", "First-plural /1k",            "first_plural_per_1k"),
    ("regression.semicolon_per_1k",  "Semicolon /1k",                 "semicolon_per_1k"),
    # The two below are phase3-bimodal and will be auto-dropped to advisory.
    ("mean_dep_depth",               "Mean dependency depth",         "mean_dep_depth"),
    ("regression.em_dash_per_1k",    "Em-dash /1k",                   "em_dash_per_1k"),
]

# Envelope classification multipliers applied to the LOO distance distribution.
# `loo_max` is the most atypical *corpus* paper, so a text at or below it is
# squarely corpus-consistent; we only escalate beyond that boundary.
ENVELOPE_BORDERLINE_FACTOR = 1.5  # within (loo_max, 1.5*loo_max] -> borderline

# Below this word count, per-1k rates and the Mahalanobis estimate are noisy.
SHORT_INPUT_WORDS = 200

# Minimum papers each side of a gap for the advisory cluster split (matches
# phase3_promotion.BIMODALITY_MIN_PER_SIDE so the clusters line up).
ADVISORY_MIN_PER_SIDE = 3

# ---------------------------------------------------------------------------
# Booster inventory (8-metric gate, check 6)
# ---------------------------------------------------------------------------

# write-like-me's exact booster list is not redistributed with the corpus, so
# this is an independently-specified, conservative inventory of certainty /
# intensity markers from the academic hedging-&-boosting literature (Hyland
# 2005 family). It is deliberately narrow to avoid false positives on
# legitimate vocabulary. The gate target (0.067/100w) is the write-like-me
# reference value carried in Appendix E; run-1 found the corpus essentially
# zero on targeted boosting vocabulary, so the check is a one-sided ceiling.
BOOSTER_TOKENS = frozenset({
    "clearly", "obviously", "undoubtedly", "certainly", "definitely",
    "evidently", "surely", "indisputably", "unquestionably",
    "incontrovertibly", "undeniably", "decidedly", "conclusively",
    "plainly", "manifestly", "indubitably",
})
BOOSTER_PHRASES = (
    "of course", "without doubt", "no doubt", "beyond doubt",
    "needless to say", "it is clear that", "there is no doubt",
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def dotted(d: dict, path: str):
    """Fetch a nested value via an 'a.b.c' path; None if any key is missing."""
    cur = d
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Feature-space resolution (active vs advisory) from phase3 bimodal flags
# ---------------------------------------------------------------------------

@dataclass
class FeatureSpace:
    """The resolved Mahalanobis feature space plus the advisory (bimodal) set."""

    active_paths: list[str]
    active_labels: list[str]
    advisory: list[dict]  # one entry per excluded bimodal metric

    @property
    def k(self) -> int:
        return len(self.active_paths)


def resolve_feature_space(phase3: dict) -> FeatureSpace:
    """Split CANDIDATE_FEATURES into active and advisory using phase3 flags.

    A candidate is moved to the advisory block iff its phase3 metric is flagged
    `bimodal: true`. Candidates with no phase3 metric (e.g. sentence stdev) are
    always kept active.
    """
    bimodal_metrics = {
        p["metric"] for p in phase3["promotions"] if p.get("bimodal")
    }
    active_paths: list[str] = []
    active_labels: list[str] = []
    advisory: list[dict] = []
    for path, label, metric in CANDIDATE_FEATURES:
        if metric is not None and metric in bimodal_metrics:
            advisory.append({"path": path, "label": label, "metric": metric})
        else:
            active_paths.append(path)
            active_labels.append(label)
    return FeatureSpace(active_paths, active_labels, advisory)


# ---------------------------------------------------------------------------
# Corpus matrix + Mahalanobis machinery
# ---------------------------------------------------------------------------

def build_corpus_matrix(phase1: dict, paths: list[str]) -> tuple[np.ndarray, list[str]]:
    """Assemble the (n_papers x k) feature matrix from the stored per-paper
    vectors. Returns (X, paper_keys). Raises if any feature is missing."""
    keys: list[str] = []
    rows: list[list[float]] = []
    for rec in phase1["per_paper"]:
        row = []
        for path in paths:
            v = dotted(rec, path)
            if not isinstance(v, (int, float)):
                raise ValueError(
                    f"paper {rec.get('key')!r} lacks numeric feature {path!r}"
                )
            row.append(float(v))
        rows.append(row)
        keys.append(rec["key"])
    return np.asarray(rows, dtype=float), keys


def standardiser(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (mean, std) per column. Sample std (ddof=1); zero std -> 1.0 so a
    constant feature contributes nothing instead of dividing by zero."""
    mean = X.mean(axis=0)
    std = X.std(axis=0, ddof=1)
    std = np.where(std == 0.0, 1.0, std)
    return mean, std


def zscore(X: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return (X - mean) / std


def fit_ledoit_wolf(Xz: np.ndarray) -> LedoitWolf:
    return LedoitWolf().fit(Xz)


def mahalanobis_distance(lw: LedoitWolf, xz: np.ndarray) -> float:
    """Euclidean Mahalanobis distance (not squared) for a single z-scored row."""
    d2 = float(lw.mahalanobis(xz.reshape(1, -1))[0])
    return math.sqrt(max(d2, 0.0))


def leave_one_out_distances(X: np.ndarray) -> list[float]:
    """LOO Mahalanobis distance for each corpus paper: fit on the other n-1
    (z-scored by their own mean/std), then score the held-out paper."""
    n = len(X)
    out: list[float] = []
    idx = np.arange(n)
    for i in range(n):
        train = X[idx != i]
        mean, std = standardiser(train)
        lw = fit_ledoit_wolf(zscore(train, mean, std))
        xi = zscore(X[i], mean, std)
        out.append(mahalanobis_distance(lw, xi))
    return out


def distribution_summary(values: list[float]) -> dict:
    s = sorted(values)
    return {
        "n": len(s),
        "min": round(s[0], 4),
        "median": round(statistics.median(s), 4),
        "mean": round(statistics.mean(s), 4),
        "p90": round(percentile(s, 90), 4),
        "p95": round(percentile(s, 95), 4),
        "max": round(s[-1], 4),
    }


def percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile on an already-sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_values[lo]
    frac = rank - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def classify_envelope(distance: float, loo: list[float]) -> dict:
    """Classify the input distance against the empirical LOO envelope."""
    s = sorted(loo)
    loo_max = s[-1]
    below = sum(1 for v in s if v < distance)
    empirical_pct = round(100.0 * below / len(s), 1)
    if distance <= loo_max:
        band = "within"
        gloss = "≤ most atypical corpus paper — consistent with the corpus"
    elif distance <= ENVELOPE_BORDERLINE_FACTOR * loo_max:
        band = "borderline"
        gloss = (
            f"between loo_max and {ENVELOPE_BORDERLINE_FACTOR:g}×loo_max — "
            "atypical but not clearly foreign"
        )
    else:
        band = "outside"
        gloss = f"> {ENVELOPE_BORDERLINE_FACTOR:g}×loo_max — outside the corpus envelope"
    return {
        "band": band,
        "gloss": gloss,
        "empirical_percentile": empirical_pct,
        "loo_max": round(loo_max, 4),
    }


# ---------------------------------------------------------------------------
# Advisory (bimodal) cluster split
# ---------------------------------------------------------------------------

def cluster_split(values: list[float],
                  min_per_side: int = ADVISORY_MIN_PER_SIDE) -> dict:
    """Split a bimodal distribution at its largest inner gap.

    Mirrors phase3_promotion.detect_bimodal's gap definition (only gaps that
    leave >= min_per_side papers on each side are considered) so the clusters
    reported here match the phase3 bimodality verdict. Returns the two cluster
    ranges and the gap-midpoint boundary used to assign new input.
    """
    s = sorted(values)
    n = len(s)
    if n < 2 * min_per_side:
        return {"split": False}
    best_gap = -1.0
    best_i = -1
    for i in range(min_per_side - 1, n - min_per_side):
        gap = s[i + 1] - s[i]
        if gap > best_gap:
            best_gap, best_i = gap, i
    if best_i < 0:
        return {"split": False}
    low = s[: best_i + 1]
    high = s[best_i + 1:]
    boundary = (s[best_i] + s[best_i + 1]) / 2.0
    return {
        "split": True,
        "boundary": round(boundary, 4),
        "low_range": (round(low[0], 4), round(low[-1], 4)),
        "low_n": len(low),
        "high_range": (round(high[0], 4), round(high[-1], 4)),
        "high_n": len(high),
    }


def advisory_report(phase1: dict, fs: FeatureSpace, record: dict) -> list[dict]:
    """For each excluded bimodal metric, report the corpus clusters and where
    the input value falls."""
    out: list[dict] = []
    for adv in fs.advisory:
        path = adv["path"]
        corpus_vals = [
            float(dotted(p, path)) for p in phase1["per_paper"]
            if isinstance(dotted(p, path), (int, float))
        ]
        split = cluster_split(corpus_vals)
        input_val = dotted(record, path)
        input_val = float(input_val) if isinstance(input_val, (int, float)) else None
        assignment = None
        if split.get("split") and input_val is not None:
            assignment = "low" if input_val <= split["boundary"] else "high"
        out.append({
            "metric": adv["metric"],
            "label": adv["label"],
            "input_value": round(input_val, 4) if input_val is not None else None,
            "corpus_min": round(min(corpus_vals), 4),
            "corpus_max": round(max(corpus_vals), 4),
            "split": split,
            "input_cluster": assignment,
        })
    return out


# ---------------------------------------------------------------------------
# 8-metric gate (plan §2.4 / guide Appendix E)
# ---------------------------------------------------------------------------

@dataclass
class GateCheck:
    key: str
    label: str
    target: float
    tol: float
    mode: str            # "band" | "max" | "zero"
    unit: str
    source: str
    actual: float = 0.0
    passed: bool = False
    note: str = ""

    def evaluate(self) -> None:
        if self.mode == "band":
            self.passed = abs(self.actual - self.target) <= self.tol
        elif self.mode == "max":
            self.passed = self.actual <= self.target + self.tol
        elif self.mode == "zero":
            self.passed = self.actual == 0
        else:  # pragma: no cover - guarded by construction
            raise ValueError(f"unknown gate mode {self.mode!r}")

    def band_str(self) -> str:
        if self.mode == "band":
            return f"{self.target:g} ± {self.tol:g}"
        if self.mode == "max":
            return f"≤ {self.target + self.tol:g}"
        return "= 0"


def count_boosters(words: list[str], lower_text: str) -> int:
    """Booster-token hits + booster-phrase hits (word-boundary phrase match)."""
    import re
    token_hits = sum(1 for w in words if w in BOOSTER_TOKENS)
    phrase_hits = 0
    for phrase in BOOSTER_PHRASES:
        phrase_hits += len(re.findall(r"\b" + re.escape(phrase) + r"\b",
                                      lower_text))
    return token_hits + phrase_hits


def consecutive_short_runs(text: str, nlp, max_words: int = 5) -> tuple[int, list[str]]:
    """Count runs of >= 2 adjacent sentences each with <= max_words words.

    Uses spaCy sentence segmentation *without* phase1's 5-word floor (which
    would drop the very sentences this check looks for). Markdown ATX heading
    lines (`^#+\\s+...`) are dropped first: they are not prose sentences, and
    the guide's Appendix E run-notes define the canonical segmentation as
    operating with heading markers stripped. On generated prose (the intended
    input) there are no headings, so this only affects scoring of raw
    corpus/markdown bodies. Returns (n_runs, example_run_texts).
    """
    import re
    text = re.sub(r"^\s*#{1,6}\s+.*$", "", text, flags=re.MULTILINE)
    doc = nlp(text)
    short_flags: list[tuple[bool, str]] = []
    for sent in doc.sents:
        stext = sent.text.strip()
        if not stext:
            continue
        n_words = len(re.findall(r"[^\W\d_][^\W\d_'’\-]*", stext, re.UNICODE))
        short_flags.append((0 < n_words <= max_words, stext))
    n_runs = 0
    examples: list[str] = []
    run: list[str] = []
    for is_short, stext in short_flags + [(False, "")]:  # sentinel flush
        if is_short:
            run.append(stext)
        else:
            if len(run) >= 2:
                n_runs += 1
                examples.append(" / ".join(run[:3]))
            run = []
    return n_runs, examples


def build_gate(phase1: dict, corpus_em_dash: bool = False) -> list[GateCheck]:
    """Construct the 8 gate checks, sourcing data-backed targets live from the
    phase1 aggregate (re-read source, per anti-confabulation discipline).

    The em-dash check defaults to the MODERN 2026+ ceiling (≤0.20/1k): the
    0.572 aggregate is the mean of a bimodal split (12/18 papers at exactly 0,
    six at 0.50–2.06/1k), so the two-sided band rejects both halves of the
    corpus AND rejects the zero-em-dash modern prose that §6.3 calls correct
    for 2026+. Pass `corpus_em_dash=True` to score against the legacy
    two-sided corpus band (0.572 ±0.20) instead.
    """
    agg = phase1["aggregate"]
    reg = agg["regression"]

    if corpus_em_dash:
        # LEGACY two-sided corpus band. Fits the *aggregate* (older-academic)
        # register, not new prose; retained for backward-comparison only.
        em_dash = GateCheck(
            key="em_dash_per_1k", label="Em dashes per 1 000 words",
            target=float(reg["em_dash_per_1k"]), tol=0.20, mode="band",
            unit="/1k",
            source="phase1 aggregate.regression.em_dash_per_1k (§6.3) — LEGACY band",
            note="legacy bimodal band (--corpus-em-dash); default is the 2026+ ceiling",
        )
    else:
        # DEFAULT: feedback_em-dash-usage-declining (2026-05-24): the 0.572
        # aggregate over-represents pre-2023 prose; 2023+ papers carry zero.
        # For new prose, treat as a one-sided ceiling of 0.20/1k.
        em_dash = GateCheck(
            key="em_dash_per_1k", label="Em dashes per 1 000 words",
            target=0.0, tol=0.20, mode="max",
            unit="/1k",
            source="phase1 aggregate.regression.em_dash_per_1k (§6.3) — "
                   "MODERN (2026+) ceiling ≤0.20/1k",
            note="2026+ ceiling per feedback_em-dash-usage-declining "
                 "(default; --corpus-em-dash for legacy band)",
        )

    checks = [
        em_dash,
        GateCheck(
            key="semicolon_per_1k", label="Semicolons per 1 000 words",
            target=float(reg["semicolon_per_1k"]), tol=1.0, mode="band",
            unit="/1k", source="phase1 aggregate.regression.semicolon_per_1k (§6.2)",
        ),
        GateCheck(
            key="announcement_colon_per_1k",
            label="Announcement colons per 1 000 words",
            target=float(agg["announcement_colon_per_1k"]), tol=0.5, mode="band",
            unit="/1k", source="phase1 aggregate.announcement_colon_per_1k (§6.4)",
        ),
        GateCheck(
            key="mean_sentence_length", label="Mean sentence length (words)",
            target=float(agg["sentence_stats"]["mean"]), tol=10.0, mode="band",
            unit="words", source="phase1 aggregate.sentence_stats.mean (§6.1)",
        ),
        GateCheck(
            key="consecutive_short_sentences",
            label="Consecutive ≤5-word sentence runs",
            target=0.0, tol=0.0, mode="zero",
            unit="runs", source="write-like-me 07-verification (§6.1)",
        ),
        GateCheck(
            key="boosters_per_100w", label="Boosters per 100 words",
            target=0.067, tol=0.0, mode="max",
            unit="/100w",
            source="Appendix E borrowed (write-like-me ref); corpus ≈0 (§4.3)",
        ),
        GateCheck(
            key="hedge_per_100w", label="Hedge density per 100 words",
            target=float(agg["hedge_per_100w"]), tol=0.1, mode="band",
            unit="/100w", source="phase1 aggregate.hedge_per_100w (§4.2)",
        ),
        GateCheck(
            key="concession_rate", label="Concession rate",
            target=float(agg["concession_rate"]), tol=0.05, mode="band",
            unit="ratio", source="phase1 aggregate.concession_rate (§6.7)",
        ),
    ]
    return checks


def evaluate_gate(checks: list[GateCheck], record: dict, text: str,
                  nlp) -> None:
    """Fill in each check's `actual` from the input record + text and decide
    pass/fail in place."""
    # Use the same reference-stripped basis as process_paper, so the booster
    # and consecutive-short checks see the same prose as the other six metrics.
    stripped, _method = p1.strip_references(text)
    lower = stripped.lower()
    words = p1.tokenize_words(stripped)
    reg = record["regression"]

    n_runs, run_examples = consecutive_short_runs(stripped, nlp)
    booster_hits = count_boosters(words, lower)
    booster_rate = round(booster_hits / max(len(words), 1) * 100, 3)

    actuals = {
        "em_dash_per_1k": reg["em_dash_per_1k"],
        "semicolon_per_1k": reg["semicolon_per_1k"],
        "announcement_colon_per_1k": record["announcement_colon_per_1k"],
        "mean_sentence_length": record["sentence_stats"]["mean"],
        "consecutive_short_sentences": float(n_runs),
        "boosters_per_100w": booster_rate,
        "hedge_per_100w": record["hedge_per_100w"],
        "concession_rate": record["concession_rate"],
    }
    for chk in checks:
        chk.actual = float(actuals[chk.key])
        chk.evaluate()
        if chk.key == "consecutive_short_sentences" and run_examples:
            chk.note = "; ".join(run_examples[:2])
        if chk.key == "boosters_per_100w" and booster_hits:
            chk.note = f"{booster_hits} booster token/phrase hit(s)"


# ---------------------------------------------------------------------------
# Core evaluation of one text
# ---------------------------------------------------------------------------

@dataclass
class Evaluation:
    source_label: str
    n_words: int
    short_input: bool
    distance: float
    squared: float
    k: int
    shrinkage: float
    loo_summary: dict
    envelope: dict
    chi2_percentile: float
    feature_deltas: list[dict]
    advisory: list[dict]
    gate: list[GateCheck]
    record: dict = field(repr=False, default_factory=dict)

    @property
    def gate_pass(self) -> bool:
        return all(c.passed for c in self.gate)

    @property
    def gate_n_pass(self) -> int:
        return sum(1 for c in self.gate if c.passed)


def evaluate_text(text: str, source_label: str, phase1: dict, phase3: dict,
                  nlp, corpus_em_dash: bool = False,
                  loo: list[float] | None = None,
                  X: np.ndarray | None = None,
                  fs: FeatureSpace | None = None) -> Evaluation:
    """Run the full evaluation (Mahalanobis + 8-metric gate) on one text.

    `loo`, `X`, `fs` may be supplied to avoid recomputation when scoring many
    texts (e.g. the validation report); otherwise they are derived here.
    """
    if fs is None:
        fs = resolve_feature_space(phase3)
    if X is None:
        X, _keys = build_corpus_matrix(phase1, fs.active_paths)
    if loo is None:
        loo = leave_one_out_distances(X)

    # Measure the input with the exact phase1 code path.
    record = p1.process_paper(source_label, text, nlp)
    n_words = record["n_words"]

    # Input feature vector in the active space.
    x_input = np.array(
        [float(dotted(record, path)) for path in fs.active_paths], dtype=float
    )

    # Fit the full-corpus model and score the input.
    mean, std = standardiser(X)
    lw = fit_ledoit_wolf(zscore(X, mean, std))
    xz = zscore(x_input, mean, std)
    squared = float(lw.mahalanobis(xz.reshape(1, -1))[0])
    distance = math.sqrt(max(squared, 0.0))

    envelope = classify_envelope(distance, loo)
    chi2_pct = round(float(chi2.cdf(squared, df=fs.k)) * 100.0, 1)

    # Per-feature standardised deltas, sorted by |z|.
    deltas: list[dict] = []
    for col, (path, label) in enumerate(zip(fs.active_paths, fs.active_labels)):
        deltas.append({
            "feature": label,
            "path": path,
            "input": round(float(x_input[col]), 4),
            "corpus_mean": round(float(mean[col]), 4),
            "corpus_std": round(float(std[col]), 4),
            "z": round(float(xz[col]), 3),
        })
    deltas.sort(key=lambda d: -abs(d["z"]))

    advisory = advisory_report(phase1, fs, record)

    gate = build_gate(phase1, corpus_em_dash)
    evaluate_gate(gate, record, text, nlp)

    return Evaluation(
        source_label=source_label,
        n_words=n_words,
        short_input=n_words < SHORT_INPUT_WORDS,
        distance=round(distance, 4),
        squared=round(squared, 4),
        k=fs.k,
        shrinkage=round(float(lw.shrinkage_), 4),
        loo_summary=distribution_summary(loo),
        envelope=envelope,
        chi2_percentile=chi2_pct,
        feature_deltas=deltas,
        advisory=advisory,
        gate=gate,
        record=record,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_markdown(ev: Evaluation) -> str:
    L: list[str] = []
    L.append("# Phase 5 — Style evaluator verdict")
    L.append("")
    L.append(f"**Input:** `{ev.source_label}` ({ev.n_words:,} words)")
    if ev.short_input:
        L.append("")
        L.append(
            f"> ⚠ Short input (< {SHORT_INPUT_WORDS} words): per-1k rates and the "
            "Mahalanobis estimate are noisy. Treat both verdicts as indicative only."
        )
    L.append("")

    # Headline verdict
    gate_tag = "✓ PASS" if ev.gate_pass else "✗ FAIL"
    L.append(f"**8-metric gate:** {gate_tag} ({ev.gate_n_pass}/{len(ev.gate)} checks)")
    L.append(
        f"**Mahalanobis distance:** {ev.distance} "
        f"(squared {ev.squared}, k={ev.k} features) — "
        f"**{ev.envelope['band'].upper()}** the corpus envelope"
    )
    L.append("")
    L.append("---")
    L.append("")

    # Mahalanobis detail
    L.append("## Mahalanobis distance to corpus centroid")
    L.append("")
    s = ev.loo_summary
    L.append(
        f"- Corpus leave-one-paper-out distances (n={s['n']}): "
        f"min {s['min']}, median {s['median']}, p90 {s['p90']}, "
        f"p95 {s['p95']}, max {s['max']}"
    )
    L.append(
        f"- Input distance **{ev.distance}** sits above "
        f"{ev.envelope['empirical_percentile']}% of corpus LOO distances "
        f"({ev.envelope['band']}: {ev.envelope['gloss']})"
    )
    L.append(
        f"- Ledoit-Wolf shrinkage intensity: {ev.shrinkage} "
        "(0 = raw covariance, 1 = pure scaled-identity target)"
    )
    L.append(
        f"- χ²({ev.k}) parametric percentile: {ev.chi2_percentile}% "
        "*(assumes multivariate normality — secondary cross-check only)*"
    )
    L.append("")

    # Feature deltas
    L.append("## Per-feature standardised deltas (sorted by |z|)")
    L.append("")
    L.append("| Feature | Input | Corpus mean | Corpus std | z |")
    L.append("|---|---:|---:|---:|---:|")
    for d in ev.feature_deltas:
        L.append(
            f"| {d['feature']} | {d['input']:g} | {d['corpus_mean']:g} | "
            f"{d['corpus_std']:g} | {d['z']:+.2f} |"
        )
    L.append("")

    # 8-metric gate
    L.append("## 8-metric tolerance gate (Appendix E)")
    L.append("")
    L.append("| Check | Target band | Input | Verdict | Note |")
    L.append("|---|---|---:|:--:|---|")
    for c in ev.gate:
        tag = "✓" if c.passed else "✗"
        actual = f"{c.actual:g} {c.unit}".strip()
        L.append(
            f"| {c.label} | {c.band_str()} {c.unit}".rstrip() +
            f" | {actual} | {tag} | {c.note} |"
        )
    L.append("")

    # Advisory bimodal features
    if ev.advisory:
        L.append("## Bimodal advisory features (excluded from Mahalanobis)")
        L.append("")
        L.append(
            "These metrics are flagged `bimodal: true` in "
            "`phase3-promotion-clean.json`; a single centroid mis-models them, "
            "so they are reported here rather than folded into the distance."
        )
        L.append("")
        L.append("| Metric | Input | Low cluster (n) | High cluster (n) | Input falls in |")
        L.append("|---|---:|---|---|:--:|")
        for a in ev.advisory:
            sp = a["split"]
            if sp.get("split"):
                low = f"{sp['low_range'][0]:g}–{sp['low_range'][1]:g} ({sp['low_n']})"
                high = f"{sp['high_range'][0]:g}–{sp['high_range'][1]:g} ({sp['high_n']})"
            else:
                low = high = "—"
            iv = "—" if a["input_value"] is None else f"{a['input_value']:g}"
            cl = a["input_cluster"] or "—"
            L.append(f"| {a['label']} | {iv} | {low} | {high} | {cl} |")
        L.append("")

    L.append("---")
    L.append("")
    overall = "✓ PASS" if ev.gate_pass else "✗ FAIL"
    L.append(
        f"**Overall:** gate {overall}; distance {ev.distance} "
        f"({ev.envelope['band']}). The 8-metric gate is the formal pass/fail; "
        "the Mahalanobis distance is a continuous diagnostic of overall "
        "stylometric typicality."
    )
    L.append("")
    return "\n".join(L)


def evaluation_to_dict(ev: Evaluation) -> dict:
    return {
        "source": ev.source_label,
        "n_words": ev.n_words,
        "short_input": ev.short_input,
        "mahalanobis": {
            "distance": ev.distance,
            "squared": ev.squared,
            "k_features": ev.k,
            "shrinkage": ev.shrinkage,
            "loo_summary": ev.loo_summary,
            "envelope": ev.envelope,
            "chi2_percentile": ev.chi2_percentile,
        },
        "feature_deltas": ev.feature_deltas,
        "advisory_bimodal": ev.advisory,
        "gate": {
            "pass": ev.gate_pass,
            "n_pass": ev.gate_n_pass,
            "n_total": len(ev.gate),
            "checks": [
                {
                    "key": c.key, "label": c.label, "target": c.target,
                    "tol": c.tol, "mode": c.mode, "unit": c.unit,
                    "actual": c.actual, "pass": c.passed, "note": c.note,
                    "source": c.source,
                }
                for c in ev.gate
            ],
        },
    }


# ---------------------------------------------------------------------------
# Validation mode — LOO distances + sanity-check fixtures
# ---------------------------------------------------------------------------

# Synthetic non-academic fixtures. These are NOT corpus extracts — they are
# deliberately off-register prose used to confirm the metric ranks foreign text
# farther from the centroid than a held-out corpus paper. Labelled clearly so
# they are never mistaken for attested corpus evidence.
SANITY_FIXTURES: list[tuple[str, str]] = [
    (
        "fixture:childrens-narrative",
        "The little dog ran fast. He saw a cat. The cat was big and grey. "
        "Spot barked loudly. He wanted to play. The cat did not want to play. "
        "It climbed up a tall tree. Spot looked up. He waited and waited. "
        "Then his friend came. They walked home together in the warm sun. "
        "It was a good day for a little dog and his very best friend.",
    ),
    (
        "fixture:marketing-listicle",
        "Boost your productivity TODAY with these 5 amazing hacks! Number one: "
        "wake up early. It's a total game-changer, trust me. Number two: drink "
        "more water — you'll feel incredible. Number three: ditch your phone. "
        "Seriously, do it now. Number four: make a list. Number five: just do "
        "it. Click the link below to unlock your free bonus guide right now!",
    ),
]


def gate_calibration(phase1: dict, phase3: dict, nlp, extracted_dir: Path,
                     fs: FeatureSpace, loo: list[float],
                     X: np.ndarray) -> dict:
    """Score the 8-metric gate against all 18 corpus papers.

    Returns per-check pass counts and the per-paper pass-count distribution.
    The point is calibration: the Appendix E tolerances were set against the
    corpus *aggregate*, and several are tighter than the corpus's own
    between-paper variance, so real corpus papers routinely fail individual
    checks. Surfacing this lets a downstream reader interpret a gate FAIL
    correctly rather than treating any FAIL as proof of off-voice text.
    """
    keys = [p["key"] for p in phase1["per_paper"]]
    per_check_pass: dict[str, int] = {}
    per_paper_pass: list[int] = []
    n_scored = 0
    for key in keys:
        body = extracted_dir / key / "body.md"
        if not body.exists():
            continue
        text = body.read_text(encoding="utf-8", errors="replace")
        ev = evaluate_text(text, key, phase1, phase3, nlp,
                           loo=loo, X=X, fs=fs)
        n_scored += 1
        per_paper_pass.append(ev.gate_n_pass)
        for c in ev.gate:
            per_check_pass.setdefault(c.key, 0)
            if c.passed:
                per_check_pass[c.key] += 1
    # Labels for display (from a throwaway gate built off the same phase1).
    # The em-dash label is identical in both modes, so the mode is irrelevant
    # here; the default (modern ceiling) is used.
    labels = {c.key: c.label for c in build_gate(phase1)}
    return {
        "n_scored": n_scored,
        "per_check": [
            {"key": k, "label": labels.get(k, k), "pass": v,
             "pct": round(100.0 * v / max(n_scored, 1), 0)}
            for k, v in per_check_pass.items()
        ],
        "per_paper_pass": sorted(per_paper_pass),
        "n_pass_all": sum(1 for x in per_paper_pass if x == 8),
        "median_pass": (statistics.median(per_paper_pass)
                        if per_paper_pass else 0),
    }


def build_validation_report(phase1: dict, phase3: dict, nlp,
                            extracted_dir: Path) -> tuple[str, bool]:
    """Produce the LOO distance table + sanity-check fixtures.

    Returns (markdown, sanity_ok). `sanity_ok` is False if any off-register
    fixture scores at or below the corpus LOO median (the metric would then be
    failing to separate foreign text from corpus text).
    """
    fs = resolve_feature_space(phase3)
    X, keys = build_corpus_matrix(phase1, fs.active_paths)
    loo = leave_one_out_distances(X)
    loo_summary = distribution_summary(loo)

    L: list[str] = []
    L.append("# Phase 5 — validation report")
    L.append("")
    L.append(
        "Leave-one-paper-out (LOO) Mahalanobis distances for the 18-paper "
        "academic corpus, plus off-register sanity fixtures. Generated by "
        "`phase5_evaluator.py --validate`."
    )
    L.append("")
    L.append(f"**Active feature space (k={fs.k}):** "
             + ", ".join(fs.active_labels))
    if fs.advisory:
        L.append("")
        L.append("**Excluded (bimodal, advisory only):** "
                 + ", ".join(a["label"] for a in fs.advisory))
    L.append("")

    # LOO table
    L.append("## Leave-one-paper-out distances")
    L.append("")
    s = loo_summary
    L.append(
        f"min {s['min']} · median {s['median']} · mean {s['mean']} · "
        f"p90 {s['p90']} · p95 {s['p95']} · max {s['max']}"
    )
    L.append("")
    L.append("| Paper key | LOO distance |")
    L.append("|---|---:|")
    paired = sorted(zip(keys, loo), key=lambda kv: kv[1])
    for key, d in paired:
        L.append(f"| {key} | {round(d, 4)} |")
    L.append("")

    # Sanity fixtures
    L.append("## Sanity-check fixtures")
    L.append("")
    L.append(
        "Off-register synthetic prose (NOT corpus extracts) plus one held-out "
        "real corpus paper. Expectation: foreign fixtures score farther than "
        "the corpus LOO max; the real paper scores within the LOO range."
    )
    L.append("")
    L.append("| Sample | n words | Distance | vs LOO max | Gate |")
    L.append("|---|---:|---:|---|:--:|")

    sanity_ok = True
    loo_max = loo_summary["max"]
    loo_median = loo_summary["median"]

    # Pick a real corpus paper (the LOO-median paper) as an in-distribution check
    median_idx = sorted(range(len(loo)), key=lambda i: loo[i])[len(loo) // 2]
    median_key = keys[median_idx]
    body = (extracted_dir / median_key / "body.md")
    samples: list[tuple[str, str]] = list(SANITY_FIXTURES)
    if body.exists():
        samples.append((f"corpus:{median_key} (held-out real)",
                        body.read_text(encoding="utf-8", errors="replace")))

    for label, text in samples:
        ev = evaluate_text(text, label, phase1, phase3, nlp,
                           loo=loo, X=X, fs=fs)
        is_corpus = label.startswith("corpus:")
        if is_corpus:
            verdict = "within" if ev.distance <= loo_max else "ABOVE (unexpected)"
            if ev.distance > loo_max:
                sanity_ok = False
        else:
            verdict = "farther ✓" if ev.distance > loo_max else "NOT farther ✗"
            if ev.distance <= loo_median:
                sanity_ok = False
        gate_tag = "✓" if ev.gate_pass else "✗"
        L.append(
            f"| {label} | {ev.n_words:,} | {ev.distance} | {verdict} | {gate_tag} |"
        )

    L.append("")

    # Gate calibration against the corpus itself.
    cal = gate_calibration(phase1, phase3, nlp, extracted_dir, fs, loo, X)
    L.append("## 8-metric gate calibration (against the 18 corpus papers)")
    L.append("")
    L.append(
        "How the Appendix E gate scores the corpus that defined it. The "
        "tolerances were set against the corpus *aggregate*; several are "
        "tighter than the between-paper variance, so real corpus papers "
        "routinely fail individual checks. **Read a gate FAIL on the "
        "high-variance checks (em-dash, semicolon, announcement-colon, hedge) "
        "as a deviation flag, not proof of off-voice text — cross-check the "
        "Mahalanobis distance.**"
    )
    L.append("")
    L.append(f"- Papers passing all 8 checks: **{cal['n_pass_all']}/"
             f"{cal['n_scored']}**")
    L.append(f"- Median checks passed per paper: **{cal['median_pass']}/8** "
             f"(distribution: {cal['per_paper_pass']})")
    L.append("")
    L.append("| Check | Corpus papers passing |")
    L.append("|---|---:|")
    for c in cal["per_check"]:
        L.append(f"| {c['label']} | {c['pass']}/{cal['n_scored']} "
                 f"({c['pct']:.0f}%) |")
    L.append("")

    L.append("---")
    L.append("")
    verdict = "✓ PASS" if sanity_ok else "✗ FAIL"
    L.append(
        f"**Sanity verdict:** {verdict} — "
        + ("off-register fixtures rank farther than the corpus and the held-out "
           "real paper stays within range."
           if sanity_ok else
           "a fixture did not separate as expected; inspect the feature space.")
    )
    L.append("")
    return "\n".join(L), sanity_ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Phase 5 downstream style evaluator (Mahalanobis + 8-metric gate)."
    )
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--text", type=Path, help="path to a file to evaluate")
    src.add_argument("--passage", type=str, help="literal passage to evaluate")
    ap.add_argument("--validate", action="store_true",
                    help="run LOO validation + sanity fixtures instead of scoring input")
    ap.add_argument("--phase1", type=Path, default=PHASE1_DEFAULT)
    ap.add_argument("--phase3", type=Path, default=PHASE3_DEFAULT)
    ap.add_argument("--extracted-dir", type=Path, default=EXTRACTED_DEFAULT,
                    help="clean-corpus <key>/body.md root (for --validate sanity check)")
    ap.add_argument("--format", choices=("markdown", "json"), default="markdown")
    ap.add_argument("--report", type=Path, default=None,
                    help="also write the report/verdict to this path")
    ap.add_argument("--corpus-em-dash", action="store_true",
                    help="score the em-dash check against the LEGACY two-sided "
                         "corpus band (0.572 ±0.20) instead of the default "
                         "modern 2026+ ceiling (≤0.20/1k). The default ceiling "
                         "follows feedback_em-dash-usage-declining; the legacy "
                         "band is bimodal and retained for backward comparison "
                         "only")
    ap.add_argument("--spacy-model", default="en_core_web_sm")
    args = ap.parse_args()

    if not args.phase1.exists():
        print(f"Phase 1 input not found: {args.phase1}", file=sys.stderr)
        return 2
    if not args.phase3.exists():
        print(f"Phase 3 input not found: {args.phase3}", file=sys.stderr)
        return 2

    phase1 = load_json(args.phase1)
    phase3 = load_json(args.phase3)

    import spacy
    nlp = spacy.load(args.spacy_model)
    if nlp.meta.get("version") != "3.8.0":
        print(f"WARNING: spaCy model version {nlp.meta.get('version')} != "
              "pinned 3.8.0", file=sys.stderr)
    nlp.select_pipes(disable=["ner"])
    nlp.max_length = 2_000_000

    # --- Validation mode -------------------------------------------------
    if args.validate:
        report, sanity_ok = build_validation_report(
            phase1, phase3, nlp, args.extracted_dir
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(report, encoding="utf-8")
            print(f"Wrote {args.report}", file=sys.stderr)
        print(report)
        return 0 if sanity_ok else 1

    # --- Single-text evaluation -----------------------------------------
    if args.text:
        if not args.text.exists():
            print(f"Input file not found: {args.text}", file=sys.stderr)
            return 2
        text = args.text.read_text(encoding="utf-8", errors="replace")
        source_label = str(args.text)
    elif args.passage:
        text = args.passage
        source_label = "<passage>"
    else:
        ap.error("one of --text, --passage, or --validate is required")
        return 2  # unreachable

    fs = resolve_feature_space(phase3)
    ev = evaluate_text(text, source_label, phase1, phase3, nlp,
                       corpus_em_dash=args.corpus_em_dash, fs=fs)

    if args.format == "json":
        out = json.dumps(evaluation_to_dict(ev), indent=2, ensure_ascii=False)
    else:
        out = render_markdown(ev)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(out, encoding="utf-8")
        print(f"Wrote {args.report}", file=sys.stderr)
    print(out)

    return 0 if ev.gate_pass else 1


if __name__ == "__main__":
    sys.exit(main())
