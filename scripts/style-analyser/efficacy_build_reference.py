#!/usr/bin/env python3
"""
efficacy_build_reference.py — build a LENGTH-MATCHED corpus reference for the
efficacy experiment (Workstream G, roadmap item #1).

Motivation (pilot finding, 2026-05-31). The Phase 5 evaluator's feature space
is built on WHOLE corpus papers (2,344-13,113 words). Scoring ~400-word
generated passages against it is a length mismatch: hapax ratio (the fraction
of word *types* occurring exactly once) is structurally ~3x higher in a
400-word text than in a multi-thousand-word paper (Heaps' law), and in the
pilot it alone contributed ~58% of the squared Mahalanobis distance, forcing
every passage "outside" the envelope regardless of style.

The fix is to judge a generated passage against *what ~400-word excerpts of the
corpus actually look like*. This script chunks each corpus body into
contiguous, whole-sentence windows of ~`--target-words` words and runs the
identical `phase1_pipeline.process_paper` feature extractor on each window,
writing a phase1-format file whose `per_paper` list is in fact per-EXCERPT.

`efficacy_score.py --reference-phase1 <this file>` then builds the Mahalanobis
centroid, covariance and leave-one-out envelope from these excerpts, while the
8-metric gate keeps its whole-corpus aspirational targets (those are register
central tendencies, not length-dependent). The official `phase5_evaluator.py`
whole-paper instrument is left untouched — this is an experiment-side artefact.

CPU-only, deterministic (given the spaCy model), no network.

Usage
-----
    python efficacy_build_reference.py                 # ~400-word windows
    python efficacy_build_reference.py --target-words 400 --min-words 250
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase5_evaluator as p5  # noqa: E402
import phase1_pipeline as p1   # noqa: E402
from efficacy_build_prompts import strip_citations  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_DIR = REPO_ROOT / "data/experiments/style-efficacy-2026-05-31"


def json_safe(obj):
    """Recursively make a process_paper record JSON-serialisable.

    `process_paper` returns an internal `_pos_bigrams_counter` keyed by
    (tag, tag) tuples (Appendix C descriptive only — not a Mahalanobis
    feature). Stringify any non-primitive dict key so the record dumps cleanly;
    the dotted feature paths build_corpus_matrix reads are untouched.
    """
    if isinstance(obj, dict):
        return {(k if isinstance(k, (str, int, float, bool, type(None)))
                 else repr(k)): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def sentence_windows(text: str, nlp, target_words: int,
                     min_words: int) -> list[str]:
    """Split `text` into contiguous whole-sentence windows of ~target_words.

    A window accumulates sentences until its running word count reaches
    target_words, then closes. A trailing window shorter than min_words is
    dropped, so the reference is not contaminated by the same short-text
    artefact it exists to correct.
    """
    doc = nlp(text)
    windows: list[str] = []
    buf: list[str] = []
    n = 0
    for sent in doc.sents:
        s = sent.text.strip()
        if not s:
            continue
        buf.append(s)
        n += len(s.split())
        if n >= target_words:
            windows.append(" ".join(buf))
            buf, n = [], 0
    if buf and n >= min_words:
        windows.append(" ".join(buf))
    return windows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target-words", type=int, default=400,
                    help="approx words per excerpt window (default 400)")
    ap.add_argument("--min-words", type=int, default=250,
                    help="drop a trailing window shorter than this")
    ap.add_argument("--phase1", type=Path, default=p5.PHASE1_DEFAULT,
                    help="whole-corpus phase1 (for the list of paper keys)")
    ap.add_argument("--extracted-dir", type=Path, default=p5.EXTRACTED_DEFAULT)
    ap.add_argument("--spacy-model", default="en_core_web_sm")
    ap.add_argument("--keep-citations", action="store_true",
                    help="do NOT strip citations from the reference (legacy "
                         "behaviour; default is citation-free to match "
                         "citation-free generation)")
    ap.add_argument("--out", type=Path,
                    default=EXPERIMENT_DIR / "reference-excerpts-400.json")
    args = ap.parse_args()
    # Aggregate semicolon density, citation-inclusive vs citation-free, so the
    # guide's §6.2 voice-target can be corrected (the 6.54/1k figure is mostly
    # citation-list separators — a venue artefact).
    semi_incl = semi_free = words_incl = words_free = 0

    phase1 = p5.load_json(args.phase1)
    keys = [p["key"] for p in phase1["per_paper"]]

    import spacy
    nlp = spacy.load(args.spacy_model)
    nlp.select_pipes(disable=["ner"])
    nlp.max_length = 2_000_000

    excerpts: list[dict] = []
    per_paper_counts: dict[str, int] = {}
    for key in keys:
        body = args.extracted_dir / key / "body.md"
        if not body.exists():
            print(f"  WARNING: no body.md for {key}", file=sys.stderr)
            continue
        text = body.read_text(encoding="utf-8", errors="replace")
        stripped, _method = p1.strip_references(text)
        cite_free = strip_citations(stripped)
        semi_incl += stripped.count(";")
        words_incl += len(stripped.split())
        semi_free += cite_free.count(";")
        words_free += len(cite_free.split())
        windows = sentence_windows(stripped, nlp, args.target_words,
                                   args.min_words)
        per_paper_counts[key] = len(windows)
        for i, w in enumerate(windows):
            # Strip citations so the reference matches the citation-free
            # generation regime (citation format is venue-determined; see
            # guide §3). Without this the reference's semicolon density is
            # citation-inflated and unfairly penalises citation-free output.
            if not args.keep_citations:
                w = strip_citations(w)
            rec = json_safe(p1.process_paper(f"{key}#w{i}", w, nlp))
            rec["key"] = f"{key}#w{i}"
            rec["source_paper"] = key
            excerpts.append(rec)

    import statistics
    wcounts = [e["n_words"] for e in excerpts]
    semi_density_incl = round(1000.0 * semi_incl / max(words_incl, 1), 3)
    semi_density_free = round(1000.0 * semi_free / max(words_free, 1), 3)
    payload = {
        "reference_kind": "length-matched corpus excerpts",
        "citations_stripped": not args.keep_citations,
        "target_words": args.target_words,
        "min_words": args.min_words,
        "n_excerpts": len(excerpts),
        "n_source_papers": len(per_paper_counts),
        "excerpts_per_paper": per_paper_counts,
        "excerpt_word_stats": {
            "min": min(wcounts), "max": max(wcounts),
            "mean": round(statistics.mean(wcounts), 1),
            "median": statistics.median(wcounts),
        },
        # Corpus semicolon density, citation-inclusive vs citation-free (for
        # the §6.2 voice-target correction).
        "semicolon_per_1k_citation_inclusive": semi_density_incl,
        "semicolon_per_1k_citation_free": semi_density_free,
        # phase1-compatible: build_corpus_matrix reads per_paper[*][<dotted>].
        "per_paper": excerpts,
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"Wrote {args.out.relative_to(REPO_ROOT)} "
          f"(citations_stripped={not args.keep_citations})")
    print(f"  {len(excerpts)} excerpts from {len(per_paper_counts)} papers; "
          f"word count min/median/mean/max = "
          f"{payload['excerpt_word_stats']['min']}/"
          f"{payload['excerpt_word_stats']['median']}/"
          f"{payload['excerpt_word_stats']['mean']}/"
          f"{payload['excerpt_word_stats']['max']}")
    print(f"  corpus semicolon /1k: citation-inclusive {semi_density_incl} "
          f"-> citation-free {semi_density_free}  (for guide §6.2)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
