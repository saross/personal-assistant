#!/usr/bin/env python3
"""
efficacy_build_judge_tasks.py — build BLINDED pairwise judge tasks for the
efficacy experiment (Workstream G, roadmap item #1).

The stylometric distance is a proxy; this sets up a holistic test of whether a
judge, shown genuine corpus excerpts as the target voice, prefers guide-written
passages over plain ones as "more like this author". Validity controls:

* **Blinding** — passages are copied to anonymised files (`pairNN_A.md` /
  `pairNN_B.md`); the judge never sees condition-revealing filenames.
* **Position-bias counterbalancing** — each unordered pair is emitted in BOTH
  orders (guide as A, and guide as B); no RNG, fully deterministic.
* **Topic-matched** — each pair is C0 vs guide on the SAME topic, so the choice
  is about voice, not content.
* **Content-cueing caveat** — reference excerpts are archaeology (the corpus's
  domain); for on-domain test topics this shares vocabulary, so the off-domain
  pairs are the cleaner voice test. The judge prompt explicitly says to ignore
  topical overlap.

Reference excerpts are real ~400-word mid-document windows of two corpus papers
(genuine author text). A mapping file records which side is the guide for
scoring; the judges never see it.

Usage
-----
    python efficacy_build_judge_tasks.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase1_pipeline as p1  # noqa: E402
from efficacy_build_prompts import strip_citations  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
EXP = REPO_ROOT / "data/experiments/style-efficacy-2026-05-31"
EXTRACTED = REPO_ROOT / "data/style-corpus/extracted"
PASSAGES = EXP / "passages"
JUDGE_DIR = EXP / "judge-tasks"

# Two reference papers chosen for voice variety + recency: a first-author 2022
# methods/argument paper and a last-author 2024 paper. Real author text.
REFERENCE_PAPERS = ["NQGD7QXT", "9B2FJ6SL"]
REFERENCE_WINDOW_INDEX = 2          # mid-document (skips abstract/intro)
REFERENCE_TARGET_WORDS = 400

TOPICS = ["A1", "A2", "B1", "B3"]
# (contrast label, guide condition) — compared against C0 (plain). C3 was
# dropped in the 2026-05-31 citation-corrected re-run (rejected condition;
# its overshoot issues are citation-independent).
CONTRASTS = [("C2vC0", "C2")]
REP = "rep1"                          # one representative passage per cell


def mid_window(text: str, nlp, idx: int, target: int) -> str:
    """Return the idx-th contiguous ~target-word whole-sentence window."""
    doc = nlp(text)
    windows, buf, n = [], [], 0
    for sent in doc.sents:
        s = sent.text.strip()
        if not s:
            continue
        buf.append(s)
        n += len(s.split())
        if n >= target:
            windows.append(" ".join(buf))
            buf, n = [], 0
    if buf:
        windows.append(" ".join(buf))
    return windows[min(idx, len(windows) - 1)]


def main() -> int:
    import spacy
    nlp = spacy.load("en_core_web_sm")
    nlp.select_pipes(disable=["ner"])
    nlp.max_length = 2_000_000

    if JUDGE_DIR.exists():
        shutil.rmtree(JUDGE_DIR)
    JUDGE_DIR.mkdir(parents=True)

    # --- reference.md: real corpus excerpts ---
    ref_parts = ["# Reference writing samples by the target author\n",
                 "These are genuine samples of the author's voice. Use them to "
                 "judge which candidate passage reads more like the same "
                 "author.\n"]
    for i, key in enumerate(REFERENCE_PAPERS, 1):
        body = (EXTRACTED / key / "body.md").read_text(encoding="utf-8",
                                                       errors="replace")
        stripped, _ = p1.strip_references(body)
        excerpt = mid_window(stripped, nlp, REFERENCE_WINDOW_INDEX,
                             REFERENCE_TARGET_WORDS)
        # Strip citations from the reference too: citation format is
        # venue-determined and excluded from the voice being judged.
        excerpt = strip_citations(excerpt)
        ref_parts.append(f"## Reference sample {i}\n\n{excerpt}\n")
    (JUDGE_DIR / "reference.md").write_text("\n".join(ref_parts),
                                            encoding="utf-8")

    # --- blinded pairs, both orders ---
    mapping = []
    n = 0
    for contrast, guide_cond in CONTRASTS:
        for topic in TOPICS:
            guide_file = PASSAGES / f"{topic}__{guide_cond}__{REP}.md"
            plain_file = PASSAGES / f"{topic}__C0__{REP}.md"
            for order in (0, 1):
                pid = f"pair{n:02d}"
                # order 0: A=guide, B=plain ; order 1: A=plain, B=guide
                a_src, b_src = ((guide_file, plain_file) if order == 0
                                else (plain_file, guide_file))
                shutil.copyfile(a_src, JUDGE_DIR / f"{pid}_A.md")
                shutil.copyfile(b_src, JUDGE_DIR / f"{pid}_B.md")
                mapping.append({
                    "pair_id": pid, "topic_id": topic, "contrast": contrast,
                    "guide_condition": guide_cond, "order": order,
                    "guide_side": "A" if order == 0 else "B",
                    "A_source": a_src.name, "B_source": b_src.name,
                })
                n += 1

    (JUDGE_DIR / "judge-mapping.json").write_text(
        json.dumps({"reference_papers": REFERENCE_PAPERS,
                    "rep": REP, "n_pairs": len(mapping),
                    "pairs": mapping}, indent=2), encoding="utf-8")
    print(f"Wrote {len(mapping)} blinded pairs + reference.md to "
          f"{JUDGE_DIR.relative_to(REPO_ROOT)}/")
    print(f"  contrasts: {[c for c, _ in CONTRASTS]}; topics: {TOPICS}; "
          f"both orders → {len(mapping)} judge tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
