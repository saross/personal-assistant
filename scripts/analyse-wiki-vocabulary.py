#!/usr/bin/env python3
"""
Analyse the memory corpus to validate the wiki tag vocabulary.

Workstream D (memory-system rethink + wiki formalisation), item #1:
empirically validate / refine the 24-tag wiki vocabulary in
``notes/_tags.md`` against what actually recurs in the memory corpus.

The memory corpus (``data/memories/memories.jsonl``) carries fine-grained
``research_tags`` auto-applied at extraction time; the vocabulary has
grown uncontrolled (≈28k unique tags, ~68 % singletons). The wiki
vocabulary is a deliberately separate, coarse, hand-curated set of 24
tags. This script measures, for each wiki tag, how much corpus support
it has (via a documented keyword-expansion map), and surfaces
high-frequency corpus themes that have *no* wiki-tag home.

It also serves workstream-D item #2 (extending ``/weekly-review`` with a
cluster-and-carry curation step): the recency-windowed theme frequencies
are the natural input to "what recurred this week worth carrying to a
wiki page".

Outputs (stdout, plain text):
    1. Top-N all-time research_tags by frequency.
    2. Top-N research_tags within a recency window (default 90 days).
    3. Per-wiki-tag corpus support (all-time + recency), via the
       keyword-expansion map below.
    4. Top co-occurring tag pairs among the most frequent tags.

The keyword-expansion map (WIKI_TAG_EXPANSIONS) is a transparent,
editable heuristic: a wiki tag is "supported" by a memory when any of
its expansion substrings appears in that memory's joined research_tags.
The map is intentionally visible so the support counts are reproducible
and arguable rather than a black box.

Usage:
    python3 scripts/analyse-wiki-vocabulary.py [--top N] [--window-days D]
                                               [--as-of YYYY-MM-DD]

``--as-of`` pins the recency window's end date for reproducibility
(defaults to the newest created_at in the corpus, so the window is
relative to the data, not the wall clock).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path

PA_ROOT = Path(__file__).resolve().parent.parent
MEMORIES_JSONL = PA_ROOT / "data" / "memories" / "memories.jsonl"
if not MEMORIES_JSONL.exists():
    MEMORIES_JSONL = PA_ROOT / "memories" / "memories.jsonl"

# -------------------------------------------------------------------------
# The 24 wiki tags (notes/_tags.md, 2026-05-18) and their corpus-support
# keyword expansions. A memory supports a wiki tag if any expansion
# substring is found in the memory's joined, lower-cased research_tags.
# Expansions are deliberately generous: the goal is to detect *presence
# of a theme*, not to classify precisely. Over-broad tags (e.g. llm-craft)
# are expected to match widely; that is itself a finding.
# -------------------------------------------------------------------------

WIKI_TAG_EXPANSIONS: dict[str, list[str]] = {
    # --- Craft scaffolding (artefact kinds) ---
    "prompts": ["prompt", "incantation", "few-shot", "system-prompt"],
    "agents": ["agent", "subagent", "sub-agent", "agentic", "proposer", "verifier"],
    "skills": ["skill", "slash-command", "slash_command"],
    "hooks": ["hook", "session-start", "precompact", "pre-compact", "sessionend",
              "session-end", "lifecycle"],
    "claude-md": ["claude-md", "claude.md", "claudemd"],
    "scratchpad": ["scratchpad"],
    "memory-system": ["memory-system", "memory-architecture", "memory-extraction",
                      "recall", "extraction-hook", "memory-pipeline"],
    "index": ["index-page", "navigation", "table-of-contents", "wiki-index"],
    # --- Failure modes and mitigation patterns ---
    "anti-confabulation": ["confabulation", "hallucination", "fragment-weld",
                           "anchor-verif", "anchor", "grounding", "anti-confab"],
    "anti-satisficing": ["satisficing", "anti-satisficing", "exit-closing",
                         "exhaustiveness"],
    "audit-pattern": ["audit", "adversarial-review", "claims-inventory",
                      "code-review", "review-pattern"],
    "bidirectional-verification": ["verification", "verifier", "bidirectional",
                                   "cross-check", "cross-validation", "proposer-verifier"],
    "provenance": ["provenance", "ro-crate", "rocrate", "three-ps", "three-p",
                   "fair", "rda"],
    # --- Domain / topic areas ---
    "llm-craft": ["llm", "prompt", "gemini", "claude", "opus", "haiku",
                  "context-window", "token", "model-selection", "few-shot"],
    "working-practices": ["focus", "session-shape", "time-management", "avoidance",
                          "accountability", "wind-down", "capacity",
                          "working-practice", "pacing", "productivity"],
    "coding-practices": ["refactor", "debugging", "testing", "ci-", "git-",
                         "python", "data-pipeline", "install", "dependency",
                         "code-quality", "string-normalis", "regression"],
    "research-methodology": ["methodology", "research-method", "bayesian",
                            "statistic", "ablation", "experiment-design",
                            "sampling", "calibration"],
    "open-science": ["open-science", "fair", "ro-crate", "rda", "data-sharing",
                     "reproducibility", "openness", "data-citation"],
    "teaching": ["teaching", "marking", "rubric", "student", "course",
                 "pedagog", "curriculum", "humn", "assessment"],
    # --- Cross-cutting themes ---
    "session-shape": ["session-shape", "pacing", "wind-down", "capacity",
                      "should-vs-must", "session-end", "session-start"],
    "human-ai-collaboration": ["human-ai", "collaboration", "interaction-pattern",
                              "delegation", "trust-calibration"],
    "three-Ps": ["three-ps", "three-p", "prompt-process-provenance"],
    "memory-systems": ["memory-system", "memory-architecture", "collaborative-memory",
                       "memory-pipeline"],
    "paper-seed": ["paper-seed", "paper-idea", "paper-draft", "manuscript-seed",
                   "paper-concept"],
}


def load_memories(path: Path) -> list[dict]:
    """Load all JSONL memory records, skipping malformed lines."""
    out: list[dict] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def parse_date(created_at: str) -> datetime | None:
    """Parse an ISO created_at to a naive datetime (date precision)."""
    if not created_at:
        return None
    try:
        return datetime.fromisoformat(created_at[:10])
    except ValueError:
        return None


def tag_frequencies(records: list[dict]) -> Counter:
    """Count research_tags usages across all records."""
    counter: Counter = Counter()
    for rec in records:
        for tag in rec.get("research_tags", []) or []:
            counter[tag.lower().strip()] += 1
    return counter


def wiki_tag_support(records: list[dict]) -> dict[str, int]:
    """For each wiki tag, count memories whose joined tags match an expansion."""
    support = {wt: 0 for wt in WIKI_TAG_EXPANSIONS}
    for rec in records:
        joined = " ".join(t.lower() for t in (rec.get("research_tags", []) or []))
        if not joined:
            continue
        for wt, expansions in WIKI_TAG_EXPANSIONS.items():
            if any(exp in joined for exp in expansions):
                support[wt] += 1
    return support


def cooccurrence(records: list[dict], head_tags: set[str]) -> Counter:
    """Count co-occurring pairs among a restricted set of head tags."""
    pairs: Counter = Counter()
    for rec in records:
        present = sorted({t.lower().strip() for t in (rec.get("research_tags", []) or [])}
                         & head_tags)
        for a, b in combinations(present, 2):
            pairs[(a, b)] += 1
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=120, help="how many top tags to list")
    ap.add_argument("--window-days", type=int, default=90,
                    help="recency window length in days")
    ap.add_argument("--as-of", type=str, default=None,
                    help="window end date YYYY-MM-DD (default: newest created_at)")
    args = ap.parse_args()

    records = load_memories(MEMORIES_JSONL)
    dated = [(parse_date(r.get("created_at", "")), r) for r in records]
    valid_dates = [d for d, _ in dated if d is not None]
    as_of = (datetime.fromisoformat(args.as_of) if args.as_of
             else max(valid_dates))
    window_start = as_of - timedelta(days=args.window_days)
    recent = [r for d, r in dated if d is not None and d >= window_start]

    print(f"corpus: {len(records)} records | "
          f"{min(valid_dates).date()} → {max(valid_dates).date()}")
    print(f"recency window: {window_start.date()} → {as_of.date()} "
          f"({args.window_days}d) → {len(recent)} records\n")

    all_freq = tag_frequencies(records)
    recent_freq = tag_frequencies(recent)

    print(f"=== TOP {args.top} research_tags (all-time) ===")
    for tag, n in all_freq.most_common(args.top):
        print(f"{n:5d}  {tag}")

    print(f"\n=== TOP {min(args.top, 60)} research_tags (last {args.window_days}d) ===")
    for tag, n in recent_freq.most_common(min(args.top, 60)):
        print(f"{n:4d}  {tag}")

    print("\n=== WIKI-TAG CORPUS SUPPORT (memories matching expansion) ===")
    print(f"{'wiki-tag':28s} {'all-time':>9s} {'%corpus':>8s} {'recent':>7s} {'%recent':>8s}")
    sup_all = wiki_tag_support(records)
    sup_recent = wiki_tag_support(recent)
    n_all, n_recent = len(records), max(1, len(recent))
    for wt in WIKI_TAG_EXPANSIONS:
        a, r = sup_all[wt], sup_recent[wt]
        print(f"{wt:28s} {a:9d} {100*a/n_all:7.1f}% {r:7d} {100*r/n_recent:7.1f}%")

    head = {t for t, _ in all_freq.most_common(40)}
    print("\n=== TOP 30 CO-OCCURRING PAIRS (among top-40 tags) ===")
    for (a, b), n in cooccurrence(records, head).most_common(30):
        print(f"{n:4d}  {a} + {b}")


if __name__ == "__main__":
    main()
