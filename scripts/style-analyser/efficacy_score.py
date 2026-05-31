#!/usr/bin/env python3
"""
efficacy_score.py — score the efficacy-experiment passages with the Phase 5
evaluator (Workstream G, roadmap item #1).

Reads every generated passage in the experiment's `passages/` directory, scores
each through `phase5_evaluator.evaluate_text` (the same Mahalanobis-distance +
8-metric-gate code path used everywhere else, so there is zero feature drift),
and writes one structured results file. CPU-only: no LLM calls, no network.

For efficiency the corpus feature space, spaCy model and leave-one-out (LOO)
distance envelope are loaded ONCE and reused across all passages (a fresh
`evaluate_text` recomputes them per call otherwise — spaCy load dominates).

Passage filenames must follow `{topic_id}__{condition}__rep{n}.md`
(e.g. `A1__C0__rep1.md`); the stratum is recovered by joining against the
prompts manifest.

Usage
-----
    python efficacy_score.py                       # default experiment dir
    python efficacy_score.py --experiment-dir DIR  # override
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Import the Phase 5 evaluator from the sibling script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase5_evaluator as p5  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPERIMENT_DIR = REPO_ROOT / "data/experiments/style-efficacy-2026-05-31"

# {topic_id}__{condition}__rep{n}.md  -> e.g.  A4__C2__rep3.md
FNAME_RE = re.compile(r"^(?P<topic>[A-Z]\d+)__(?P<cond>C\d)__rep(?P<rep>\d+)$")


def load_corpus_space(phase1_path: Path, phase3_path: Path, spacy_model: str,
                      reference_phase1_path: Path | None = None):
    """Load the corpus matrices, LOO envelope, feature space and spaCy once.

    `phase1_path` is the whole-corpus file; its `aggregate` block supplies the
    8-metric gate's aspirational targets (register central tendencies, not
    length-dependent), so it is always used for the gate.

    If `reference_phase1_path` is given (a length-matched excerpt reference from
    `efficacy_build_reference.py`), the Mahalanobis centroid, covariance and
    leave-one-out (LOO) envelope are built from THOSE excerpt vectors instead of
    the whole-paper vectors. This corrects the passage-length artefact (hapax
    ratio etc.) documented in the pilot findings, while the gate stays anchored
    to the whole corpus.
    """
    phase1 = p5.load_json(phase1_path)
    phase3 = p5.load_json(phase3_path)
    fs = p5.resolve_feature_space(phase3)
    matrix_source = reference_phase1_path or phase1_path
    matrix_phase1 = (p5.load_json(reference_phase1_path)
                     if reference_phase1_path else phase1)
    X, _keys = p5.build_corpus_matrix(matrix_phase1, fs.active_paths)
    loo = p5.leave_one_out_distances(X)

    import spacy
    nlp = spacy.load(spacy_model)
    nlp.select_pipes(disable=["ner"])
    nlp.max_length = 2_000_000
    return phase1, phase3, fs, X, loo, nlp, str(matrix_source)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--experiment-dir", type=Path,
                    default=DEFAULT_EXPERIMENT_DIR)
    ap.add_argument("--phase1", type=Path, default=p5.PHASE1_DEFAULT,
                    help="whole-corpus phase1 (gate targets + default matrix)")
    ap.add_argument("--phase3", type=Path, default=p5.PHASE3_DEFAULT)
    ap.add_argument("--reference-phase1", type=Path, default=None,
                    help="length-matched excerpt reference (from "
                         "efficacy_build_reference.py); used for the Mahalanobis "
                         "space + LOO envelope while the gate stays whole-corpus")
    ap.add_argument("--spacy-model", default="en_core_web_sm")
    ap.add_argument("--out", type=Path, default=None,
                    help="output JSON (default: <experiment-dir>/scores.json)")
    args = ap.parse_args()

    passages_dir = args.experiment_dir / "passages"
    if not passages_dir.is_dir():
        print(f"No passages dir: {passages_dir}", file=sys.stderr)
        return 2
    out_path = args.out or (args.experiment_dir / "scores.json")

    # Stratum lookup from the manifest (optional; falls back to "?").
    stratum_by_topic: dict[str, str] = {}
    manifest_path = args.experiment_dir / "prompts.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for rec in manifest.get("records", []):
            stratum_by_topic[rec["topic_id"]] = rec["stratum"]

    phase1, phase3, fs, X, loo, nlp, matrix_source = load_corpus_space(
        args.phase1, args.phase3, args.spacy_model, args.reference_phase1
    )

    results: list[dict] = []
    skipped: list[str] = []
    for path in sorted(passages_dir.glob("*.md")):
        m = FNAME_RE.match(path.stem)
        if not m:
            skipped.append(path.name)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        ev = p5.evaluate_text(text, path.name, phase1, phase3, nlp,
                              loo=loo, X=X, fs=fs)
        d = p5.evaluation_to_dict(ev)
        results.append({
            "file": path.name,
            "topic_id": m.group("topic"),
            "stratum": stratum_by_topic.get(m.group("topic"), "?"),
            "condition": m.group("cond"),
            "rep": int(m.group("rep")),
            "n_words": d["n_words"],
            "short_input": d["short_input"],
            "distance": d["mahalanobis"]["distance"],
            "envelope_band": d["mahalanobis"]["envelope"]["band"],
            "loo_max": d["mahalanobis"]["envelope"]["loo_max"],
            "chi2_percentile": d["mahalanobis"]["chi2_percentile"],
            "gate_n_pass": d["gate"]["n_pass"],
            "gate_n_total": d["gate"]["n_total"],
            "gate_pass": d["gate"]["pass"],
            "feature_deltas": d["feature_deltas"],
        })

    # LOO summary for downstream effect-size-in-SD-units calculations.
    import statistics
    loo_summary = {
        "n": len(loo),
        "mean": round(statistics.mean(loo), 4),
        "stdev": round(statistics.pstdev(loo), 4),
        "max": round(max(loo), 4),
        "median": round(statistics.median(loo), 4),
    }

    payload = {
        "experiment": args.experiment_dir.name,
        "n_passages": len(results),
        "n_skipped": len(skipped),
        "skipped_files": skipped,
        "mahalanobis_reference": matrix_source,
        "reference_n_rows": int(X.shape[0]),
        "gate_reference": str(args.phase1),
        "loo_summary": loo_summary,
        "results": results,
    }
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Scored {len(results)} passages -> {out_path.relative_to(REPO_ROOT)}")
    if skipped:
        print(f"  Skipped {len(skipped)} non-conforming filenames: {skipped}",
              file=sys.stderr)
    n_short = sum(1 for r in results if r["short_input"])
    if n_short:
        print(f"  WARNING: {n_short} passage(s) below the 200-word floor — "
              "their per-1k rates are unstable.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
