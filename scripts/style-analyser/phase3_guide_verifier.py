#!/usr/bin/env python3
"""
Phase 3 — Style-guide deterministic verifier.

Walks a generated style guide (markdown) and cross-checks every
mechanically-checkable numeric claim against the canonical source
data in `phase1-results-clean.json` and `phase3-promotion-clean.json`.

Surfaces:
- Numeric mismatches (e.g. "8/18 papers" when phase3 says 6/18).
- Status mismatches between the guide's `**Status:**` field and the
  phase3 promotion verdict (with an allowlist for semantic overrides).
- "Where it appears" papers that are NOT in phase3's
  `papers_present` for that metric (a confabulation).
- "plus N more" / "additional papers" hedging that has no anchor.

No LLM calls. Deterministic. Designed to run as a regression gate
after every style-guide generation.

Usage:
    python phase3_guide_verifier.py \
        --guide notes/style-guides/academic/style-guide-academic-2026-05-30.md \
        [--phase1 data/style-corpus/phase1-results-clean.json] \
        [--phase3 data/style-corpus/phase3-promotion-clean.json] \
        [--report data/style-corpus/phase3-guide-verifier-report.md]

Exit code is non-zero on any FAIL (for CI / pre-publish gating).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style_support  # noqa: E402  (after the sys.path insertion above)

# __file__-derived, not relative to the working directory: the documented
# invocation gives this script an absolute path and never cd's first, so a
# relative default resolved against wherever the shell happened to be.
PA_ROOT = Path(__file__).resolve().parents[2]
PHASE1_DEFAULT = PA_ROOT / "data" / "style-corpus" / "phase1-results-clean.json"
PHASE3_DEFAULT = PA_ROOT / "data" / "style-corpus" / "phase3-promotion-clean.json"

# --- Metric mapping: §N.N -> phase3 metric name(s) -------------------------
# Each §-claim may have one primary metric (its main count/rate) plus
# secondary metrics (e.g. §6.1 has both mean and median SL).

SECTION_TO_METRICS: dict[str, list[str]] = {
    "1.1": ["first_plural_per_1k"],
    "1.2": ["mattr_100", "hapax_ratio"],
    # §3.4 (Latin abbreviations cf./i.e./e.g.) has a compound status
    # spanning several abbreviations and a semantic-absence claim about
    # `pace` as Latin citation hedge. Phase 1 measures only `pace`, which is
    # what the STATUS_OVERRIDE_ALLOWLIST entry below is about — and while
    # §3.4 was absent from this mapping the section was skipped wholesale
    # (:532), so that allowlist entry was unreachable dead code and the
    # section's numeric claims went unchecked (finding ST28).
    "3.4": ["pace_count"],
    "4.2": ["hedge_per_100w"],
    "5.1": ["passive_ratio"],
    "5.2": ["nominalisation_per_1000w"],
    "5.3": ["mean_dep_depth"],
    "6.1": ["sentence_mean", "sentence_median"],
    "6.2": ["semicolon_per_1k"],
    "6.3": ["em_dash_per_1k"],
    "6.4": ["announcement_colon_per_1k"],
    "6.5": ["paragraph_median_words", "paragraph_mean_words"],
    "6.6": ["while_count", "however_count", "although_count", "whilst_count"],
    "6.7": ["concession_rate"],
}

# Per-metric per-paper rate field in phase1 (dotted path).
METRIC_TO_PER_PAPER_PATH: dict[str, str] = {
    "first_plural_per_1k":         "regression.first_plural_per_1k",
    "mattr_100":                   "mattr_100",
    "hapax_ratio":                 "hapax_ratio",
    "pace_count":                  "regression.pace_count_case_sensitive",
    "hedge_per_100w":              "hedge_per_100w",
    "passive_ratio":               "passive_ratio",
    "nominalisation_per_1000w":    "nominalisation_per_1000w",
    "mean_dep_depth":              "mean_dep_depth",
    "sentence_mean":               "sentence_stats.mean",
    "sentence_median":             "sentence_stats.median",
    "semicolon_per_1k":            "regression.semicolon_per_1k",
    "em_dash_per_1k":              "regression.em_dash_per_1k",
    "announcement_colon_per_1k":   "announcement_colon_per_1k",
    "paragraph_median_words":      "paragraph_stats.median",
    "paragraph_mean_words":        "paragraph_stats.mean",
    "while_count":                 "regression.while_count",
    "however_count":               "regression.however_count",
    "although_count":              "regression.although_count",
    "whilst_count":                "regression.whilst_count",
    "concession_rate":             "concession_rate",
}

# Per-metric CORPUS-AGGREGATE path in phase1 (dotted, under `aggregate`).
# Check 4b uses this to check a claimed per-1 000-word rate against the rate
# phase 1 actually measured. Metrics with no corpus-level rate (MATTR, hapax,
# the raw subordinator counts) are deliberately absent: a per-1k claim in
# their section is reported as unverifiable rather than checked against a
# number that means something else.
METRIC_TO_AGGREGATE_PATH: dict[str, str] = {
    "first_plural_per_1k":       "regression.first_plural_per_1k",
    "semicolon_per_1k":          "regression.semicolon_per_1k",
    "em_dash_per_1k":            "regression.em_dash_per_1k",
    "announcement_colon_per_1k": "announcement_colon_per_1k",
    "hedge_per_100w":            "hedge_per_100w",
    "concession_rate":           "concession_rate",
    "nominalisation_per_1000w":  "nominalisation_per_1000w_mean_of_papers",
    "passive_ratio":             "passive_ratio_mean_of_papers",
    "mean_dep_depth":            "mean_dep_depth_mean_of_papers",
    "sentence_mean":             "sentence_stats.mean",
    "sentence_median":           "sentence_stats.median",
    "paragraph_mean_words":      "paragraph_stats.mean",
    "paragraph_median_words":    "paragraph_stats.median",
    "mattr_100":                 "mattr_100",
    "hapax_ratio":               "hapax_ratio",
}

# The noun a `N <feature> / M words` claim uses -> the key in
# `phase1.aggregate.regression` that holds that count. Finding ST4: the check
# used to accept the numerator if it matched ANY integer in the regression
# block, so "73 semicolons / 127,720 words" passed on the strength of the
# em-dash count being 73. The claim now has to match the metric it names.
FEATURE_WORD_TO_AGGREGATE_COUNT: dict[str, str] = {
    "em-dash": "em_dash_count",
    "em-dashes": "em_dash_count",
    "emdash": "em_dash_count",
    "emdashes": "em_dash_count",
    "semicolon": "semicolon_count",
    "semicolons": "semicolon_count",
    "while": "while_count",
    "whilst": "whilst_count",
    "however": "however_count",
    "although": "although_count",
    "pace": "pace_count_case_sensitive",
    "first-plural": "first_plural_count",
    "we": "first_plural_count",
}

# Semantic overrides: §-claim allowed to disagree with the algorithm
# because the algorithm cannot distinguish word-sense or has other
# documented limitations. Override -> (algorithm_status, allowed_status,
# reason).
STATUS_OVERRIDE_ALLOWLIST: dict[str, tuple[str, str, str]] = {
    "3.4": (
        "attested-concentrated",
        "absent-when-searched",
        "all raw `pace` hits are noun-sense, not Latin citation hedge; "
        "tokeniser cannot distinguish word-sense",
    ),
}


# --- Data containers --------------------------------------------------------

@dataclass
class CheckResult:
    section: str
    metric: str | None
    check: str          # short label
    status: str         # "PASS" | "FAIL" | "WARN" | "SKIP" | "UNVERIFIED"
    expected: str = ""
    actual: str = ""
    note: str = ""

    def line(self) -> str:
        tag = {"PASS": "✓", "FAIL": "✗", "WARN": "!", "SKIP": "·",
               "UNVERIFIED": "?"}[self.status]
        line = f"  {tag} [{self.status}] §{self.section} {self.check}"
        if self.metric:
            line += f" ({self.metric})"
        if self.expected or self.actual:
            line += f" — expected `{self.expected}`, got `{self.actual}`"
        if self.note:
            line += f" — {self.note}"
        return line


# --- Helpers ----------------------------------------------------------------

def dotted(d: dict, path: str):
    """Get nested value via 'a.b.c' path."""
    cur = d
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def papers_with_rate_present(phase1: dict, metric_path: str) -> list[str]:
    """List of paper keys with per-paper rate/count > 0 for a metric."""
    out = []
    for p in phase1["per_paper"]:
        v = dotted(p, metric_path)
        if isinstance(v, (int, float)) and v > 0:
            out.append(p["key"])
    return out


def papers_with_rate_absent(phase1: dict, metric_path: str) -> list[str]:
    """List of paper keys with per-paper rate/count == 0."""
    out = []
    for p in phase1["per_paper"]:
        v = dotted(p, metric_path)
        if isinstance(v, (int, float)) and v == 0:
            out.append(p["key"])
    return out


def split_claim_blocks(guide: str) -> list[tuple[str, str, str]]:
    """Yield (section, title, body) for each `### N.N Title` block."""
    out = []
    # Match `### N.N <title>` then collect content until next `### ` or `## `.
    head_re = re.compile(r"^### (\d+\.\d+) (.+?)$", re.M)
    matches = list(head_re.finditer(guide))
    for i, m in enumerate(matches):
        section = m.group(1)
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(guide)
        # Trim at next ## (appendix start)
        next_section = re.search(r"^## ", guide[start:end], re.M)
        if next_section:
            end = start + next_section.start()
        body = guide[start:end].strip()
        out.append((section, title, body))
    return out


def extract_status(body: str) -> str | None:
    m = re.search(r"^\*\*Status:\*\*\s*([a-z\-]+)", body, re.M)
    return m.group(1) if m else None


# A partition phrase, matched against the REST OF THE CLAUSE that follows a
# `N/M papers` fraction. Finding ST6: the old test looked for any of
# low/high/range/bin/tier anywhere in a +/-60-character snippet, so an
# incidental word downgraded a genuine numeric mismatch from FAIL to WARN.
# A sub-cluster claim says so in its own clause; that is what this matches.
_SUBCLUSTER_CLAUSE_RE = re.compile(
    r"^[^.;:]{0,80}?\b(?:"
    r"sub-?cluster"
    r"|(?:at|in|within|above|below)\s+(?:the\s+|a\s+|an\s+)?"
    r"(?:low(?:er)?|high(?:er)?|elevated|upper|top|bottom|middle)\s+"
    r"(?:rate|rates|band|tier|bin|cluster|group|end|mode)"
    r")\b",
    re.I,
)

# A Zotero key is eight characters of upper-case letters and digits, and in
# practice always mixes the two. Finding ST7: `[0-9A-Z]{8}` alone also matches
# METADATA, ANALYSIS and 20260530, each of which was reported as a
# confabulated corpus key. Requiring at least one letter AND at least one
# digit keeps the check (an invented key such as ABCD1234 still fails) while
# dropping the whole class of false positives.
_ZOTERO_KEY_RE = re.compile(
    r"\b(?=[0-9A-Z]{8}\b)(?=[0-9A-Z]*[A-Z])(?=[0-9A-Z]*[0-9])([0-9A-Z]{8})\b"
)


def extract_count_paper_fractions(body: str) -> list[tuple[int, int, str, bool]]:
    """Find every `N/M papers` mention, with its context and partition flag.

    Returns ``(n, total, snippet, is_subcluster)``. ``snippet`` is context for
    the human reading the report; ``is_subcluster`` is decided structurally,
    from the clause that FOLLOWS the fraction, never from the snippet.
    """
    pat = re.compile(r"(\d+)\s*/\s*(\d+)\s+papers", re.I)
    out = []
    for m in pat.finditer(body):
        n, total = int(m.group(1)), int(m.group(2))
        # Context for the report...
        s, e = max(0, m.start() - 60), min(len(body), m.end() + 60)
        snippet = body[s:e].replace("\n", " ").strip()
        # ...and, separately, the structural test: does the claim's own
        # clause declare a sub-cluster partition?
        tail = body[m.end():m.end() + 160].replace("\n", " ")
        out.append((n, total, snippet,
                    bool(_SUBCLUSTER_CLAUSE_RE.match(tail))))
    return out


def extract_named_keys_in_block(body: str) -> list[str]:
    """Return the Zotero-key-shaped tokens in the body, sorted.

    Sorted, not ``list(set(...))``: set iteration order varies with the
    interpreter's hash seed, which made the report's FAIL rows come out in a
    different order on every run (finding STT-M2).
    """
    return sorted(set(_ZOTERO_KEY_RE.findall(body)))


def extract_cv_values(body: str) -> list[float]:
    """Find numeric CV statements: `CV = 1.664`, `CV 1.664`, `(CV 1.664)`."""
    pat = re.compile(r"\bCV\s*[=:]?\s*(\d+(?:\.\d+)?)", re.I)
    return [float(m.group(1)) for m in pat.finditer(body)]


def extract_per_1k_aggregates(body: str) -> list[float]:
    """Numeric aggregate rates of the form `X per 1 000` or `X per 1k` or `X/1k`."""
    pat = re.compile(
        r"(\d+\.\d+)\s*(?:per\s+1\s*0?\s*0?\s*0\s*w?|/\s*1\s*0?\s*0?\s*0\s*w?|/1k)",
        re.I,
    )
    return [float(m.group(1)) for m in pat.finditer(body)]


def extract_explicit_count_word_ratios(body: str) -> list[tuple[int, str, int]]:
    """Patterns like `73 em-dashes / 127,720 words`.

    Returns ``(count, feature_word, words)``. The feature word is what the
    claim says it counted, and check 4 now insists the number match THAT
    metric (finding ST4).
    """
    pat = re.compile(
        r"(\d{1,3}(?:,?\d{3})*)\s+([a-zA-Z\-]+)\s*/\s*(\d{1,3}(?:,?\d{3})*)\s+words",
        re.I,
    )
    out = []
    for m in pat.finditer(body):
        count = int(m.group(1).replace(",", ""))
        feature = m.group(2).lower()
        words = int(m.group(3).replace(",", ""))
        out.append((count, feature, words))
    return out


# --- The verifier core ------------------------------------------------------

def _match_status(section: str, declared_status: str,
                  p3_for_section: list[dict]) -> CheckResult:
    """Return the single row for check 1: does the declared status hold?

    A status is accepted if it equals the promotion verdict of ANY of the
    section's metrics, or if the section's allowlist entry permits exactly
    this substitution. Everything else is a FAIL naming what phase 3 said.
    """
    accepted = sorted({verdict["promotion"] for verdict in p3_for_section})
    for verdict in p3_for_section:
        if declared_status == verdict["promotion"]:
            return CheckResult(
                section, verdict["metric"], "status matches phase3 verdict",
                "PASS", expected=declared_status, actual=declared_status,
            )
    override = STATUS_OVERRIDE_ALLOWLIST.get(section)
    if override:
        expected_algo, allowed, reason = override
        for verdict in p3_for_section:
            if declared_status == allowed and verdict["promotion"] == expected_algo:
                return CheckResult(
                    section, verdict["metric"],
                    "status (semantic override allowed)", "PASS",
                    expected=allowed, actual=declared_status, note=reason,
                )
    return CheckResult(
        section, p3_for_section[0]["metric"], "status matches phase3 verdict",
        "FAIL", expected="/".join(accepted), actual=declared_status,
    )


def verify_claim(section: str, title: str, body: str,
                 phase1: dict, phase3: dict) -> list[CheckResult]:
    """Run every applicable check on a single claim block."""
    out: list[CheckResult] = []
    metrics = SECTION_TO_METRICS.get(section, [])

    # Look up phase3 verdicts for this section's metrics
    p3 = {p["metric"]: p for p in phase3["promotions"]}
    p3_for_section = [p3[m] for m in metrics if m in p3]

    # ---- Check 1: Status field matches at least one of the metrics' verdicts.
    #
    # Rewritten for finding STT-M1. The old control flow was
    # `elif valid and not out[-1:] or (out and out[-1].section != section)`,
    # whose precedence made it right only by accident (finding ST29), and it
    # emitted NO ROW AT ALL when the section had no phase 3 verdict — so a
    # declared status with nothing behind it was invisible rather than
    # reported. Every branch below emits exactly one row.
    declared_status = extract_status(body)
    if declared_status is None:
        out.append(CheckResult(section, None, "status present",
                               "SKIP", note="no **Status:** line"))
    elif not p3_for_section:
        out.append(CheckResult(
            section, None, "status has a phase3 verdict behind it",
            "UNVERIFIED",
            expected="a phase3 verdict for one of "
                     f"{metrics or 'this section’s metrics'}",
            actual=declared_status,
            note="phase 3 promoted no metric for this section, so the "
                 "declared status is unbacked",
        ))
    else:
        matched = _match_status(section, declared_status, p3_for_section)
        out.append(matched)

    # ---- Check 2: Every `N/M papers` fraction matches phase3 n_papers_present.
    # Sub-cluster partitions (claims like "6/18 papers at the elevated rate")
    # are agent-derived clusterings the algorithm does not model, so they get
    # a WARN rather than a FAIL — but ONLY when the claim's own clause says it
    # is a partition. The flag is computed structurally in
    # `extract_count_paper_fractions`; the old keyword scan over a +/-60-char
    # snippet downgraded genuine mismatches on an incidental word (ST6).
    fractions = extract_count_paper_fractions(body)
    for n, total, snippet, is_subcluster in fractions:
        # The N/M might match any of the metrics' n_papers_present, OR the
        # complement (n_total - n_present) for a "where it does not" claim.
        matched_any = False
        for verdict in p3_for_section:
            n_pres = verdict["n_papers_present"]
            n_tot = verdict["n_papers_total"]
            if total != n_tot:
                continue
            if n == n_pres:
                out.append(CheckResult(
                    section, verdict["metric"], f"N/M papers fraction",
                    "PASS", expected=f"{n_pres}/{n_tot}",
                    actual=f"{n}/{total}",
                    note=f"matches papers_present",
                ))
                matched_any = True
                break
            if n == n_tot - n_pres:
                out.append(CheckResult(
                    section, verdict["metric"], f"N/M papers fraction (negation)",
                    "PASS", expected=f"{n_tot - n_pres}/{n_tot}",
                    actual=f"{n}/{total}",
                    note=f"matches papers_absent",
                ))
                matched_any = True
                break
        if not matched_any and p3_for_section:
            if is_subcluster:
                out.append(CheckResult(
                    section, p3_for_section[0]["metric"],
                    f"N/M papers fraction (sub-cluster partition)",
                    "WARN",
                    expected="agent-defined sub-cluster",
                    actual=f"{n}/{total}",
                    note=f"not algorithmically checkable; context: «{snippet}»",
                ))
                continue
            # Find the closest expected value for this metric
            expecteds = []
            for verdict in p3_for_section:
                n_pres = verdict["n_papers_present"]
                n_tot = verdict["n_papers_total"]
                expecteds.append(f"{n_pres}/{n_tot} (present) or "
                                 f"{n_tot - n_pres}/{n_tot} (absent)")
            out.append(CheckResult(
                section, p3_for_section[0]["metric"],
                f"N/M papers fraction",
                "FAIL",
                expected=" | ".join(expecteds),
                actual=f"{n}/{total}",
                note=f"context: «{snippet}»",
            ))

    # ---- Check 3: Every CV value matches phase3 cv
    cvs = extract_cv_values(body)
    for cv in cvs:
        matched = False
        for verdict in p3_for_section:
            if abs(cv - verdict["cv"]) <= 0.005:  # rounding tolerance
                out.append(CheckResult(
                    section, verdict["metric"], "CV value",
                    "PASS", expected=str(verdict["cv"]),
                    actual=str(cv),
                ))
                matched = True
                break
        if not matched and p3_for_section:
            expecteds = ", ".join(
                f"{v['metric']}={v['cv']}" for v in p3_for_section
            )
            out.append(CheckResult(
                section, p3_for_section[0]["metric"], "CV value",
                "FAIL",
                expected=expecteds,
                actual=str(cv),
            ))

    # ---- Check 4: Aggregate `count / words` claims match phase1 totals
    #
    # Finding ST4: the numerator used to be accepted if it equalled ANY
    # integer in `aggregate.regression`, so "73 semicolons / 127,720 words"
    # passed because the EM-DASH count happened to be 73. The claim names its
    # feature, and the number is now checked against that feature's count.
    agg_reg = phase1["aggregate"]["regression"]
    n_words_corpus = phase1["aggregate"]["n_words"]
    for count, feature, words in extract_explicit_count_word_ratios(body):
        if words != n_words_corpus:
            out.append(CheckResult(
                section, None, "denominator words",
                "FAIL",
                expected=str(n_words_corpus),
                actual=str(words),
                note="aggregate word count mismatch",
            ))
            continue
        aggregate_key = FEATURE_WORD_TO_AGGREGATE_COUNT.get(feature)
        if aggregate_key is None or aggregate_key not in agg_reg:
            out.append(CheckResult(
                section, None, "count / words ratio",
                "FAIL",
                expected="a feature phase 1 counts",
                actual=f"{count} {feature} / {words} words",
                note=f"cannot verify: no aggregate metric is named "
                     f"'{feature}', so the number is unchecked",
            ))
            continue
        expected_count = agg_reg[aggregate_key]
        status = "PASS" if expected_count == count else "FAIL"
        out.append(CheckResult(
            section, aggregate_key, "count / words ratio", status,
            expected=f"{expected_count}/{n_words_corpus}",
            actual=f"{count}/{words}",
            note=f"claim names '{feature}' -> aggregate.regression."
                 f"{aggregate_key}",
        ))

    # ---- Check 4b: `X per 1 000 words` rates match the phase 1 aggregate.
    #
    # `extract_per_1k_aggregates` existed but was never called (finding ST28),
    # so a confabulated per-1k rate in §6.2/§6.3 passed with a tick and exit 0
    # (finding STT6/C6). Any per-1k number in the claim must now match the
    # corpus rate of one of the section's metrics.
    per_1k_claims = extract_per_1k_aggregates(body)
    if per_1k_claims:
        aggregate = phase1["aggregate"]
        candidates = {
            metric: dotted(aggregate, METRIC_TO_AGGREGATE_PATH[metric])
            for metric in metrics
            if metric in METRIC_TO_AGGREGATE_PATH
            and isinstance(dotted(aggregate, METRIC_TO_AGGREGATE_PATH[metric]),
                           (int, float))
        }
        for claimed in per_1k_claims:
            if not candidates:
                out.append(CheckResult(
                    section, None, "per-1k rate", "UNVERIFIED",
                    expected="a corpus rate for this section's metrics",
                    actual=str(claimed),
                    note="no aggregate rate is mapped for "
                         f"{metrics or 'this section'}",
                ))
                continue
            # A rounding tolerance of half the last printed digit: guide
            # claims are quoted to 2-3 decimals against a 3-decimal source.
            hit = [m for m, v in sorted(candidates.items())
                   if abs(float(v) - claimed) <= 0.005]
            if hit:
                out.append(CheckResult(
                    section, hit[0], "per-1k rate", "PASS",
                    expected=str(candidates[hit[0]]), actual=str(claimed),
                ))
            else:
                out.append(CheckResult(
                    section, sorted(candidates)[0], "per-1k rate", "FAIL",
                    expected=", ".join(f"{m}={candidates[m]}"
                                       for m in sorted(candidates)),
                    actual=str(claimed),
                    note="claimed rate matches no phase 1 aggregate rate for "
                         "this section",
                ))

    # ---- Check 5: Named Zotero keys in claim body must be valid papers
    valid_keys = {p["key"] for p in phase1["per_paper"]}
    named = extract_named_keys_in_block(body)
    invalid = [k for k in named if k not in valid_keys]
    for k in invalid:
        out.append(CheckResult(
            section, None, "named-key validity",
            "FAIL",
            expected="known corpus key",
            actual=k,
            note="key does not appear in phase1.per_paper",
        ))

    # ---- Check 6: For an `attested-concentrated` claim, named papers
    # in "Where it appears" must be a subset of phase3 papers_present, AND
    # named papers in "Where it does not" must be a subset of papers_absent.
    # Use a tight regex window that terminates strictly at the next `**`
    # block, so the "Where it does not" papers are not pulled into the
    # "Where it appears" window.
    if declared_status in ("attested-concentrated", "attested-rarely"):
        for verdict in p3_for_section:
            metric_path = METRIC_TO_PER_PAPER_PATH.get(verdict["metric"])
            if not metric_path:
                continue
            present = set(papers_with_rate_present(phase1, metric_path))
            absent = set(papers_with_rate_absent(phase1, metric_path))

            # Tight window: from `**Where it appears...**` to the next `**`
            # bold-block marker (which is the start of "Where it does not"
            # or "Evidence"). This is non-greedy and structural.
            wm = re.search(
                r"\*\*Where it appears[^*]*?\*\*([^*]*)",
                body, re.S,
            )
            if wm:
                window_appears = wm.group(1)
                named_in_appears = set(re.findall(r"\b([0-9A-Z]{8})\b",
                                                  window_appears))
                # Filter to known corpus keys only (avoid date strings
                # like 2026-05-22 false-matching)
                named_in_appears &= {p["key"] for p in phase1["per_paper"]}
                extra = sorted(named_in_appears - present)
                for k in extra:
                    out.append(CheckResult(
                        section, verdict["metric"],
                        "named in 'Where it appears' but rate==0",
                        "FAIL",
                        expected=f"key in {sorted(present)}",
                        actual=k,
                        note="this paper has rate=0 for this metric",
                    ))
                missing = present - named_in_appears
                if missing:
                    out.append(CheckResult(
                        section, verdict["metric"],
                        "'Where it appears' completeness",
                        "WARN",
                        expected=f"all {len(present)} present papers named",
                        actual=f"{len(present) - len(missing)} of {len(present)} named",
                        note=f"unnamed: {sorted(missing)}",
                    ))

            # Same check for "Where it does not"
            wm_n = re.search(
                r"\*\*Where it does not[^*]*?\*\*([^*]*)",
                body, re.S,
            )
            if wm_n:
                window_absent = wm_n.group(1)
                named_in_absent = set(re.findall(r"\b([0-9A-Z]{8})\b",
                                                 window_absent))
                named_in_absent &= {p["key"] for p in phase1["per_paper"]}
                extra_a = sorted(named_in_absent - absent)
                for k in extra_a:
                    out.append(CheckResult(
                        section, verdict["metric"],
                        "named in 'Where it does not' but rate>0",
                        "FAIL",
                        expected=f"key in {sorted(absent)}",
                        actual=k,
                        note="this paper has rate>0 for this metric",
                    ))

    # ---- Check 7: Detect unanchored "plus N more / additional" hedges
    hedge_pat = re.compile(
        r"plus\s+(?:another\s+)?(\w+)\s+(?:papers?|chapters?|articles?|cases?)\s+(?:with|that|featuring)",
        re.I,
    )
    for m in hedge_pat.finditer(body):
        out.append(CheckResult(
            section, None, "unanchored 'plus N more' hedge",
            "FAIL",
            expected="explicit enumeration or no hedge",
            actual=m.group(0)[:80],
            note="confabulation risk: claim has no source anchor",
        ))

    return out


# --- Top-level driver -------------------------------------------------------

def verify_guide(guide: str, phase1: dict, phase3: dict) -> list[CheckResult]:
    """Check every `### N.N` claim block in the guide.

    A section with no entry in ``SECTION_TO_METRICS`` used to be skipped
    silently, so 52 of the guide's §-claims were never looked at and a
    confabulated number in one of them passed with a tick (findings STT6/C6).
    Each such section now yields one UNVERIFIED row, which the caller counts
    against the exit code unless ``--allow-unverified`` was passed.
    """
    results: list[CheckResult] = []
    for section, title, body in split_claim_blocks(guide):
        if section not in SECTION_TO_METRICS:
            results.append(CheckResult(
                section, None, "section has a deterministic check",
                "UNVERIFIED",
                expected="an entry in SECTION_TO_METRICS",
                actual=f"§{section} {title}",
                note="no metric is mapped to this section, so its numbers "
                     "were not checked against phase 1 or phase 3",
            ))
            continue
        results.extend(verify_claim(section, title, body, phase1, phase3))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--guide", required=True, type=Path)
    ap.add_argument("--phase1", default=PHASE1_DEFAULT, type=Path)
    ap.add_argument("--phase3", default=PHASE3_DEFAULT, type=Path)
    ap.add_argument("--report", default=None, type=Path)
    ap.add_argument(
        "--allow-unverified", action="store_true",
        help="exit 0 even when some §-claims could not be checked (they are "
             "still reported); without this, an unverifiable claim fails the "
             "run, because 'not checked' is not 'checked and correct'",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="print the report but write no file")
    args = ap.parse_args(argv)

    guide = args.guide.read_text(encoding="utf-8")
    phase1 = json.loads(args.phase1.read_text(encoding="utf-8"))
    phase3 = json.loads(args.phase3.read_text(encoding="utf-8"))

    all_results = verify_guide(guide, phase1, phase3)

    # Summary
    counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0, "UNVERIFIED": 0}
    for r in all_results:
        counts[r.status] += 1
    failed = bool(counts["FAIL"]) or (
        bool(counts["UNVERIFIED"]) and not args.allow_unverified)

    lines: list[str] = []
    lines.append("# Phase 3 — Guide verifier report")
    lines.append("")
    lines.append(f"**Guide:** `{args.guide}`")
    lines.append(f"**Phase 1 input:** `{args.phase1}`")
    lines.append(f"**Phase 3 input:** `{args.phase3}`")
    lines.append("")
    lines.append(f"**Summary:** {counts['PASS']} PASS · {counts['FAIL']} FAIL · "
                 f"{counts['WARN']} WARN · {counts['SKIP']} SKIP · "
                 f"{counts['UNVERIFIED']} UNVERIFIED "
                 f"({len(all_results)} total checks across "
                 f"{len(set(r.section for r in all_results))} §-claims).")
    lines.append("")
    if counts["FAIL"]:
        lines.append("**Verdict:** ✗ FAIL — confabulation or numeric mismatch detected.")
    elif counts["UNVERIFIED"] and not args.allow_unverified:
        lines.append("**Verdict:** ✗ FAIL — some §-claims could not be checked "
                     "at all (see the UNVERIFIED rows); re-run with "
                     "`--allow-unverified` to accept that.")
    elif counts["WARN"] or counts["UNVERIFIED"]:
        lines.append("**Verdict:** ! WARN — passed but with cautionary findings.")
    else:
        lines.append("**Verdict:** ✓ PASS — all deterministic checks passed.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Per-section detail
    by_section: dict[str, list[CheckResult]] = {}
    for r in all_results:
        by_section.setdefault(r.section, []).append(r)
    for section in sorted(by_section.keys(), key=lambda s: tuple(map(int, s.split(".")))):
        rs = by_section[section]
        # Section pass/fail tally
        n_fail = sum(1 for r in rs if r.status == "FAIL")
        n_warn = sum(1 for r in rs if r.status == "WARN")
        n_pass = sum(1 for r in rs if r.status == "PASS")
        n_unver = sum(1 for r in rs if r.status == "UNVERIFIED")
        tag = "✗" if n_fail else ("?" if n_unver else ("!" if n_warn else "✓"))
        lines.append(f"## §{section} — {tag} ({n_pass} PASS / {n_fail} FAIL / "
                     f"{n_warn} WARN / {n_unver} UNVERIFIED)")
        lines.append("")
        for r in rs:
            lines.append(r.line())
        lines.append("")

    # Provenance: which code and which inputs produced this verdict.
    provenance = style_support.provenance_block(
        Path(__file__).name, [args.guide, args.phase1, args.phase3])
    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- Script: `{provenance['script']}`, commit "
                 f"`{provenance['git_commit']}`")
    for item in provenance["inputs"]:
        lines.append(f"- Input `{item['path']}` sha256 `{item['sha256']}`")
    lines.append("")

    report_text = "\n".join(lines)
    if args.report:
        wrote = style_support.atomic_write_text(args.report, report_text,
                                                dry_run=args.dry_run)
        print(f"Wrote {args.report}" if wrote
              else f"--dry-run: nothing written to {args.report}")
    print(report_text)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
