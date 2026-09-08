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
import sys
import unicodedata
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
    """Load all JSONL memory records, skipping malformed and non-object lines.

    A JSONL line that parses to a list, a number, or a string is as unusable
    here as one that does not parse at all, so both are skipped rather than
    handed downstream to raise an AttributeError several functions later.
    """
    out: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                out.append(record)
    return out


def parse_date(created_at: object) -> datetime | None:
    """Parse an ISO ``created_at`` to a naive datetime (date precision).

    Returns None for anything unparseable — including a non-string value,
    which the corpus does occasionally carry.
    """
    if not isinstance(created_at, str) or not created_at:
        return None
    try:
        return datetime.fromisoformat(created_at[:10])
    except ValueError:
        return None


def normalise_tag(tag: object) -> str | None:
    """Return the canonical form of a research tag, or None if unusable.

    One normalisation, used everywhere: NFC first (so a composed and a
    decomposed spelling of the same accented tag count as one tag rather
    than two), then strip, then case-fold to lower. The three call sites
    below previously disagreed — one stripped, one did not — so the same
    tag could be counted under two keys.

    A non-string entry (the corpus carries the occasional null or nested
    object) yields None rather than an AttributeError.
    """
    if not isinstance(tag, str):
        return None
    cleaned = unicodedata.normalize("NFC", tag).strip().lower()
    return cleaned or None


def record_tags(record: dict) -> list[str]:
    """Return one record's usable, normalised research tags."""
    raw = record.get("research_tags") or []
    if not isinstance(raw, list):
        return []
    return [tag for tag in (normalise_tag(item) for item in raw) if tag]


def unusable_tag_count(records: list[dict]) -> int:
    """Count research_tags entries that could not be normalised."""
    total = 0
    for record in records:
        raw = record.get("research_tags") or []
        if not isinstance(raw, list):
            total += 1
            continue
        total += sum(1 for item in raw if normalise_tag(item) is None)
    return total


def tag_frequencies(records: list[dict]) -> Counter:
    """Count research_tags usages across all records."""
    counter: Counter = Counter()
    for record in records:
        for tag in record_tags(record):
            counter[tag] += 1
    return counter


def wiki_tag_support(records: list[dict]) -> dict[str, int]:
    """For each wiki tag, count memories whose joined tags match an expansion."""
    support = {wt: 0 for wt in WIKI_TAG_EXPANSIONS}
    for record in records:
        joined = " ".join(record_tags(record))
        if not joined:
            continue
        for wiki_tag, expansions in WIKI_TAG_EXPANSIONS.items():
            if any(expansion in joined for expansion in expansions):
                support[wiki_tag] += 1
    return support


def cooccurrence(records: list[dict], head_tags: set[str]) -> Counter:
    """Count co-occurring pairs among a restricted set of head tags."""
    pairs: Counter = Counter()
    for record in records:
        present = sorted(set(record_tags(record)) & head_tags)
        for first, second in combinations(present, 2):
            pairs[(first, second)] += 1
    return pairs


def main(argv: list[str] | None = None) -> int:
    """Print the vocabulary report. Writes nothing; returns an exit code.

    This script is read-only by design — ``/weekly-review`` step 5b runs it
    against the live corpus — so every result goes to stdout and every
    problem with the corpus is a diagnostic, not a traceback.
    """
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=120, help="how many top tags to list")
    ap.add_argument("--window-days", type=int, default=90,
                    help="recency window length in days")
    ap.add_argument("--as-of", type=str, default=None,
                    help="window end date YYYY-MM-DD (default: newest created_at)")
    args = ap.parse_args(argv)

    if not MEMORIES_JSONL.exists():
        print(f"no memory corpus at {MEMORIES_JSONL} — nothing to analyse",
              file=sys.stderr)
        return 1

    records = load_memories(MEMORIES_JSONL)
    if not records:
        print(f"{MEMORIES_JSONL} holds no usable memory records "
              "(empty, or every line malformed) — nothing to analyse",
              file=sys.stderr)
        return 1

    dated = [(parse_date(r.get("created_at", "")), r) for r in records]
    valid_dates = [d for d, _ in dated if d is not None]

    if args.as_of:
        try:
            as_of = datetime.fromisoformat(args.as_of)
        except ValueError:
            print(f"--as-of must be an ISO date, not {args.as_of!r}",
                  file=sys.stderr)
            return 2
    elif valid_dates:
        as_of = max(valid_dates)
    else:
        # An undated corpus is analysable in aggregate; only the recency
        # window is impossible. Say so and carry on rather than raising
        # ValueError out of max() and aborting the weekly review.
        as_of = None

    if as_of is None:
        window_start = None
        recent: list[dict] = []
        print("note: no record carries a parseable created_at — the recency "
              "window is skipped", file=sys.stderr)
    else:
        window_start = as_of - timedelta(days=args.window_days)
        recent = [r for d, r in dated if d is not None and d >= window_start]

    unusable = unusable_tag_count(records)
    if unusable:
        print(f"note: skipped {unusable} research_tags entries that were not "
              "usable strings", file=sys.stderr)

    if valid_dates:
        print(f"corpus: {len(records)} records | "
              f"{min(valid_dates).date()} → {max(valid_dates).date()}")
    else:
        print(f"corpus: {len(records)} records | no parseable created_at dates")
    if as_of is None:
        print(f"recency window: skipped ({args.window_days}d) → 0 records\n")
    else:
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
    # Both denominators are floored at 1: an empty recent window was already
    # guarded, an empty corpus was not, and neither may divide by zero.
    n_all, n_recent = max(1, len(records)), max(1, len(recent))
    for wt in WIKI_TAG_EXPANSIONS:
        a, r = sup_all[wt], sup_recent[wt]
        print(f"{wt:28s} {a:9d} {100*a/n_all:7.1f}% {r:7d} {100*r/n_recent:7.1f}%")

    head = {t for t, _ in all_freq.most_common(40)}
    print("\n=== TOP 30 CO-OCCURRING PAIRS (among top-40 tags) ===")
    for (a, b), n in cooccurrence(records, head).most_common(30):
        print(f"{n:4d}  {a} + {b}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
