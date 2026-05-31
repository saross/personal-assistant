#!/usr/bin/env python3
"""
efficacy_score_judges.py — tally the blind pairwise judge test
(Workstream G, roadmap item #1).

Reads `judge-tasks/judge-mapping.json` (which side was the guide, per pair) and
`judge-tasks/judgments.jsonl` (each judge's A/B choice + confidence), and reports
whether judges preferred guide-written passages over plain ones as "more like
the author". Includes a position-bias check exploiting the counterbalanced
design (each unordered pair judged in both A/B orders): if the preference is for
the guide CONTENT it persists across orders; if it is a letter bias it does not.

CPU-only, deterministic. Writes `judge-analysis.md` + `judge-analysis.json`.

Usage
-----
    python efficacy_score_judges.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXP = REPO_ROOT / "data/experiments/style-efficacy-2026-05-31"
JUDGE = EXP / "judge-tasks"
STRATUM = {"A1": "on-domain", "A2": "on-domain",
           "B1": "off-domain", "B3": "off-domain"}
# Contrasts present in the judge run. C3vC0 was dropped in the 2026-05-31
# citation-corrected re-run (rejected condition).
CONTRASTS = ["C2vC0"]


def winrate(rows: list[dict]) -> str:
    n = len(rows)
    g = sum(r["picked_guide"] for r in rows)
    return f"{g}/{n}"


def main() -> int:
    mapping = {p["pair_id"]: p
               for p in json.loads((JUDGE / "judge-mapping.json")
                                   .read_text())["pairs"]}
    rows = []
    for line in (JUDGE / "judgments.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        j = json.loads(line)
        m = mapping[j["pair_id"]]
        rows.append({**m, "choice": j["choice"],
                     "confidence": j["confidence"],
                     "picked_guide": j["choice"] == m["guide_side"]})

    letters = Counter(r["choice"] for r in rows)
    by_contrast = {}
    for c in CONTRASTS:
        rs = [r for r in rows if r["contrast"] == c]
        ga = [r for r in rs if r["guide_side"] == "A"]
        gb = [r for r in rs if r["guide_side"] == "B"]
        by_contrast[c] = {
            "overall": winrate(rs),
            "guide_as_A_biasagainst": winrate(ga),
            "guide_as_B": winrate(gb),
            "per_topic": {t: winrate([r for r in rs if r["topic_id"] == t])
                          for t in ["A1", "A2", "B1", "B3"]},
        }
    gp = [r for r in rows if r["picked_guide"]]
    pp = [r for r in rows if not r["picked_guide"]]
    summary = {
        "n_judgments": len(rows),
        "overall_guide_winrate": winrate(rows),
        "raw_letter_choices": dict(letters),
        "by_contrast": by_contrast,
        "guide_picked_confidence": dict(Counter(r["confidence"] for r in gp)),
        "plain_picked_confidence": dict(Counter(r["confidence"] for r in pp)),
    }
    (EXP / "judge-analysis.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    L = ["# Blind pairwise judge test — analysis", "",
         f"- **{len(rows)} judgments** (2 contrasts x 4 topics x 2 orders), "
         "one fresh-context judge each; guide vs plain (C0), blind + "
         "order-counterbalanced.",
         f"- **Overall: guide preferred {winrate(rows)}** "
         f"({100*sum(r['picked_guide'] for r in rows)//len(rows)}%).",
         f"- Raw letter choices A={letters['A']} B={letters['B']} "
         "(mild B-lean → why the counterbalancing matters).", "",
         "## By contrast", "",
         "| Contrast | guide win | guide=A (bias against) | guide=B |",
         "|---|--:|--:|--:|"]
    for c in CONTRASTS:
        b = by_contrast[c]
        L.append(f"| {c} | {b['overall']} | {b['guide_as_A_biasagainst']} | "
                 f"{b['guide_as_B']} |")
    L += ["", "## Per topic (guide win, both orders)", "",
          "| Contrast | A1 (on) | A2 (on) | B1 (off) | B3 (off) |",
          "|---|--:|--:|--:|--:|"]
    for c in CONTRASTS:
        pt = by_contrast[c]["per_topic"]
        L.append(f"| {c} | {pt['A1']} | {pt['A2']} | {pt['B1']} | {pt['B3']} |")
    L += ["",
          f"Guide-picked confidence: {summary['guide_picked_confidence']}; "
          f"plain-picked: {summary['plain_picked_confidence']}.", ""]
    (EXP / "judge-analysis.md").write_text("\n".join(L) + "\n",
                                           encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
