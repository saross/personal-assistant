#!/usr/bin/env python3
"""
validate_passive_detection.py — manual audit of spaCy passive-voice detection.

Samples 5 flagged sentences per paper (seed=42) across four corpus papers and
prints them for human verdict (TRUE PASSIVE / FALSE POSITIVE / EDGE CASE). The
goal is to determine whether the v2 pipeline's reported passive_ratio (mean
0.28 across 18 papers) is a real measurement or a parser artefact driven by
two-column reflow, reduced relative clauses, and predicative adjectives.

Usage:
    ~/Code/write-like-me/.venv/bin/python \\
        ~/personal-assistant/scripts/style-analyser/validate_passive_detection.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

# Make the pipeline module importable so we can reuse strip_references().
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from phase1_pipeline import strip_references  # noqa: E402

import spacy  # noqa: E402

CORPUS_DIR = Path("/tmp/style-corpus-extract")
PAPERS = ["GNPTJ3EZ", "TPD3G6PX", "9B2FJ6SL", "SP2R6FF9"]
SAMPLE_PER_PAPER = 5
SEED = 42
TRUNCATE_AT = 250


def find_passive_triggers(sent) -> list[tuple[str, str, str]]:
    """Return [(dep, child_text, head_text), ...] for every nsubjpass / auxpass
    child of a VERB head in this sentence. Mirrors phase1_pipeline.spacy_features
    exactly: pos_=='VERB' AND child.dep_ in {nsubjpass, auxpass}."""
    triggers = []
    for tok in sent:
        if tok.pos_ != "VERB":
            continue
        for child in tok.children:
            if child.dep_ in ("nsubjpass", "auxpass"):
                triggers.append((child.dep_, child.text, tok.text))
    return triggers


def collect_flagged(text: str, nlp) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """Run spaCy and return [(sentence_text, [triggers...]), ...] for every
    sentence that contains at least one passive trigger."""
    doc = nlp(text)
    flagged = []
    for sent in doc.sents:
        # Match the pipeline's filter: skip space-only sentences.
        tokens = [t for t in sent if not t.is_space]
        if not tokens:
            continue
        triggers = find_passive_triggers(sent)
        if triggers:
            sent_text = sent.text.strip()
            # Collapse internal newlines / runs of whitespace for readability.
            sent_text = " ".join(sent_text.split())
            if sent_text:
                flagged.append((sent_text, triggers))
    return flagged


def truncate(text: str, n: int = TRUNCATE_AT) -> str:
    return text if len(text) <= n else text[:n].rstrip() + "..."


def format_trigger(dep: str, child: str, head: str) -> str:
    return f'flag: ({dep}: {child}, head: {head})'


def main() -> int:
    print("Loading en_core_web_sm...", file=sys.stderr)
    nlp = spacy.load("en_core_web_sm")
    print(f"  model version: {nlp.meta['version']}", file=sys.stderr)
    nlp.max_length = 2_000_000

    rng = random.Random(SEED)
    rows = []
    totals = {}
    for key in PAPERS:
        txt_path = CORPUS_DIR / f"{key}.txt"
        if not txt_path.exists():
            print(f"  MISSING: {txt_path}", file=sys.stderr)
            continue
        raw = txt_path.read_text(encoding="utf-8", errors="replace")
        stripped, method = strip_references(raw)
        flagged = collect_flagged(stripped, nlp)
        totals[key] = (len(flagged), method)
        print(
            f"  {key}: ref_strip={method} flagged_sents={len(flagged)}",
            file=sys.stderr,
        )

        sample = rng.sample(flagged, min(SAMPLE_PER_PAPER, len(flagged)))
        for sent_text, triggers in sample:
            rows.append((key, sent_text, triggers))

    # Print 20 examples for human verdict.
    print("\n" + "=" * 78)
    print("PASSIVE DETECTION AUDIT — 20 SAMPLED FLAGGED SENTENCES")
    print("=" * 78 + "\n")
    for i, (key, sent_text, triggers) in enumerate(rows, 1):
        trig_strs = "; ".join(format_trigger(*t) for t in triggers)
        print(f"[{i:02d}] {key}")
        print(f"     SENTENCE: {truncate(sent_text)}")
        print(f"     TRIGGERS: {trig_strs}")
        print(f"     VERDICT : ___________")
        print()

    # Totals for context.
    print("-" * 78)
    print("Per-paper flagged-sentence counts (for context):")
    for key, (n, method) in totals.items():
        print(f"  {key}: {n} flagged sentences (ref_strip={method})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
