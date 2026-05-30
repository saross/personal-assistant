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

# --- Metric mapping: §N.N -> phase3 metric name(s) -------------------------
# Each §-claim may have one primary metric (its main count/rate) plus
# secondary metrics (e.g. §6.1 has both mean and median SL).

SECTION_TO_METRICS: dict[str, list[str]] = {
    "1.1": ["first_plural_per_1k"],
    "1.2": ["mattr_100", "hapax_ratio"],
    # §3.4 (Latin abbreviations cf./i.e./e.g.) has a compound status
    # spanning several abbreviations and a semantic-absence claim about
    # `pace` as Latin citation hedge. Phase 1 doesn't measure these as
    # distinct metrics, so §3.4 has no Phase 3 verdict and is skipped.
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
    status: str         # "PASS" | "FAIL" | "WARN" | "SKIP"
    expected: str = ""
    actual: str = ""
    note: str = ""

    def line(self) -> str:
        tag = {"PASS": "✓", "FAIL": "✗", "WARN": "!", "SKIP": "·"}[self.status]
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


def extract_count_paper_fractions(body: str) -> list[tuple[int, int, str]]:
    """Find every `N/M papers` or `N / M papers` mention with surrounding context."""
    pat = re.compile(r"(\d+)\s*/\s*(\d+)\s+papers", re.I)
    out = []
    for m in pat.finditer(body):
        n, total = int(m.group(1)), int(m.group(2))
        # Grab a snippet for context
        s, e = max(0, m.start() - 60), min(len(body), m.end() + 60)
        snippet = body[s:e].replace("\n", " ").strip()
        out.append((n, total, snippet))
    return out


def extract_named_keys_in_block(body: str) -> list[str]:
    """Find Zotero-key-shaped tokens inside the body (8-char alphanumeric, common pattern)."""
    return list(set(re.findall(r"\b([0-9A-Z]{8})\b", body)))


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


def extract_explicit_count_word_ratios(body: str) -> list[tuple[int, int]]:
    """Patterns like `73 em-dashes / 127,720 words`."""
    pat = re.compile(
        r"(\d{1,3}(?:,?\d{3})*)\s+[a-zA-Z\-]+\s*/\s*(\d{1,3}(?:,?\d{3})*)\s+words",
        re.I,
    )
    out = []
    for m in pat.finditer(body):
        a = int(m.group(1).replace(",", ""))
        b = int(m.group(2).replace(",", ""))
        out.append((a, b))
    return out


# --- The verifier core ------------------------------------------------------

def verify_claim(section: str, title: str, body: str,
                 phase1: dict, phase3: dict) -> list[CheckResult]:
    """Run every applicable check on a single claim block."""
    out: list[CheckResult] = []
    metrics = SECTION_TO_METRICS.get(section, [])

    # Look up phase3 verdicts for this section's metrics
    p3 = {p["metric"]: p for p in phase3["promotions"]}
    p3_for_section = [p3[m] for m in metrics if m in p3]

    # ---- Check 1: Status field matches at least one of the metrics' verdicts.
    declared_status = extract_status(body)
    if declared_status is None:
        out.append(CheckResult(section, None, "status present",
                               "SKIP", note="no **Status:** line"))
    else:
        valid = False
        accepted = set()
        for verdict in p3_for_section:
            algo_status = verdict["promotion"]
            accepted.add(algo_status)
            if declared_status == algo_status:
                valid = True
                break
            # Allowlist semantic override
            if section in STATUS_OVERRIDE_ALLOWLIST:
                expected_algo, allowed, _reason = STATUS_OVERRIDE_ALLOWLIST[section]
                if declared_status == allowed and algo_status == expected_algo:
                    valid = True
                    out.append(CheckResult(
                        section, verdict["metric"],
                        "status (semantic override allowed)",
                        "PASS",
                        expected=allowed,
                        actual=declared_status,
                        note=STATUS_OVERRIDE_ALLOWLIST[section][2],
                    ))
                    break
        if not valid and p3_for_section:
            out.append(CheckResult(
                section,
                p3_for_section[0]["metric"],
                "status matches phase3 verdict",
                "FAIL",
                expected="/".join(sorted(accepted)),
                actual=declared_status,
            ))
        elif valid and not out[-1:] or (out and out[-1].section != section):
            # add a positive PASS row when not override
            if section not in STATUS_OVERRIDE_ALLOWLIST:
                out.append(CheckResult(
                    section,
                    p3_for_section[0]["metric"] if p3_for_section else None,
                    "status matches phase3 verdict",
                    "PASS",
                    expected=declared_status,
                    actual=declared_status,
                ))

    # ---- Check 2: Every `N/M papers` fraction matches phase3 n_papers_present.
    # Skip sub-cluster partitions (claims like "6/18 papers at elevated rate"
    # or "10/18 papers at low rate") — these are agent-derived clusterings
    # the algorithm does not model. They get a WARN, not a FAIL.
    fractions = extract_count_paper_fractions(body)
    subcluster_keywords = re.compile(
        r"\b(elevated|low(?:er)?|high(?:er)?|cluster|sub[\-\s]?cluster|tier"
        r"|bin|elevation|range|at\s+(?:high|low|elevated))\b",
        re.I,
    )
    for n, total, snippet in fractions:
        is_subcluster = bool(subcluster_keywords.search(snippet))
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
    cwr = extract_explicit_count_word_ratios(body)
    for count, words in cwr:
        # words should equal corpus n_words
        n_words_corpus = phase1["aggregate"]["n_words"]
        if words != n_words_corpus:
            out.append(CheckResult(
                section, None, "denominator words",
                "FAIL",
                expected=str(n_words_corpus),
                actual=str(words),
                note="aggregate word count mismatch",
            ))
        else:
            # numerator must match a known regression count
            agg_reg = phase1["aggregate"]["regression"]
            numerators = {k: v for k, v in agg_reg.items()
                          if isinstance(v, int) and v == count}
            if numerators:
                out.append(CheckResult(
                    section, None, "count / words ratio",
                    "PASS",
                    expected=f"{count}/{n_words_corpus}",
                    actual=f"{count}/{words}",
                    note=f"matches {','.join(numerators.keys())}",
                ))
            else:
                # Don't fail on unknown numerators — could be aggregated counts
                # phase1 doesn't track (e.g. announcement colons).
                out.append(CheckResult(
                    section, None, "count / words ratio",
                    "WARN",
                    expected="known regression count",
                    actual=f"{count}/{words}",
                    note="numerator not in phase1.aggregate.regression — verify manually",
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
                extra = named_in_appears - present
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
                extra_a = named_in_absent - absent
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

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--guide", required=True, type=Path)
    ap.add_argument("--phase1", default=Path("data/style-corpus/phase1-results-clean.json"), type=Path)
    ap.add_argument("--phase3", default=Path("data/style-corpus/phase3-promotion-clean.json"), type=Path)
    ap.add_argument("--report", default=None, type=Path)
    args = ap.parse_args()

    guide = args.guide.read_text(encoding="utf-8")
    phase1 = json.load(open(args.phase1))
    phase3 = json.load(open(args.phase3))

    claims = split_claim_blocks(guide)
    all_results: list[CheckResult] = []
    for section, title, body in claims:
        if section not in SECTION_TO_METRICS:
            continue  # nothing to deterministically check
        all_results.extend(verify_claim(section, title, body, phase1, phase3))

    # Summary
    counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
    for r in all_results:
        counts[r.status] += 1

    lines: list[str] = []
    lines.append(f"# Phase 3 — Guide verifier report")
    lines.append("")
    lines.append(f"**Guide:** `{args.guide}`")
    lines.append(f"**Phase 1 input:** `{args.phase1}`")
    lines.append(f"**Phase 3 input:** `{args.phase3}`")
    lines.append("")
    lines.append(f"**Summary:** {counts['PASS']} PASS · {counts['FAIL']} FAIL · "
                 f"{counts['WARN']} WARN · {counts['SKIP']} SKIP "
                 f"({len(all_results)} total checks across "
                 f"{len(set(r.section for r in all_results))} §-claims).")
    lines.append("")
    if counts["FAIL"]:
        lines.append("**Verdict:** ✗ FAIL — confabulation or numeric mismatch detected.")
    elif counts["WARN"]:
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
        tag = "✗" if n_fail else ("!" if n_warn else "✓")
        lines.append(f"## §{section} — {tag} ({n_pass} PASS / {n_fail} FAIL / {n_warn} WARN)")
        lines.append("")
        for r in rs:
            lines.append(r.line())
        lines.append("")

    report_text = "\n".join(lines)
    if args.report:
        args.report.write_text(report_text, encoding="utf-8")
        print(f"Wrote {args.report}")
    print(report_text)

    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
