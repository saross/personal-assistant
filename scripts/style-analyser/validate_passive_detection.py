#!/usr/bin/env python3
"""
validate_passive_detection.py — HUMAN-AUDIT PRINTER for spaCy passive detection.

**This script asserts nothing and decides nothing.** It samples sentences that
spaCy's dependency parse flags as passive, prints each one with its trigger
tokens and a blank ``VERDICT`` line, and stops. A person then reads the sample
and marks every example TRUE PASSIVE / FALSE POSITIVE / EDGE CASE. The question
being answered is whether the v2 pipeline's reported ``passive_ratio`` is a
real measurement or a parser artefact driven by two-column reflow, reduced
relative clauses, and predicative adjectives — and this file produces the
worksheet, not the answer.

How this relates to phase 1 (audit finding L4)
----------------------------------------------
The *trigger rule* is identical to ``phase1_pipeline.spacy_features``: a token
whose ``pos_`` is ``VERB`` and which has a child whose ``dep_`` is
``nsubjpass`` or ``auxpass``. Three things around that rule are **not**
identical, so a tally taken from this script cannot be substituted for phase
1's figures:

1. **Unit.** Phase 1 counts passive *verbs* — a sentence with two passive verbs
   contributes 2 to the numerator of ``passive_ratio``. This script counts
   *sentences* holding at least one trigger, so its counts run lower and its
   sample is drawn from a different population than the ratio's numerator.
2. **Sentence set.** This script and phase 1's ``spacy_features`` both segment
   with raw spaCy sentence boundaries (``doc.sents``), but phase 1's *other*
   sentence metrics use ``phase1_pipeline.split_sentences``, a paragraph-aware
   splitter that keeps only 5–200-word fragments. "Sentence" therefore means
   two different things inside phase 1, and the sentences sampled here are the
   raw spaCy ones, never the 5–200-word filtered set.
3. **Reference stripping.** ``strip_references`` is applied here as a safety
   net and its verdict is printed per paper. On the clean corpus it should
   report ``none`` — body.md already has the reference list separated out,
   which is the assumption phase 1 makes on its ``--clean-corpus`` path. A
   printed method other than ``none`` means the pre-pass cut something and the
   sample below is not the whole paper.

Corpus layout
-------------
Reads the clean extraction at ``data/style-corpus/extracted/<key>/body.md``,
resolved against the repository root derived from ``__file__`` — so the script
behaves the same from any working directory, and never depends on ``~``.
``--corpus-dir`` points it at some other extraction and ``--keys`` chooses the
papers. The pre-2026-05-24 layout it used to read
(``/tmp/style-corpus-extract/<key>.txt``) no longer exists; reading it made
every paper "MISSING" and produced a silent zero-example report that still
exited 0 — audit finding STT2.

Exit status
-----------
``0`` when at least one flagged sentence was printed; ``1`` when the sample
came out empty — no paper readable, or no flagged sentence in any paper that
was. An audit printer that printed nothing must not be mistaken for a pass.

spaCy is imported inside :func:`load_nlp` rather than at module scope (the same
arrangement ``phase1_pipeline`` uses), so the helpers here — path resolution,
argument parsing, formatting, and the drivers, which take an already-built
pipeline — can be imported where spaCy is not installed. The dependency itself
is real and unchanged for an actual run.

Usage:
    ~/personal-assistant/venv/bin/python3 \\
        scripts/style-analyser/validate_passive_detection.py --help
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

# Make the pipeline module importable so we can reuse strip_references().
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from phase1_pipeline import strip_references  # noqa: E402

#: Repository root, derived from this file's location (``<root>/scripts/
#: style-analyser/``). Deliberately not ``Path.home()``: the script must work
#: from a worktree, a checkout under another name, or any working directory.
REPO_ROOT = SCRIPT_DIR.parent.parent

#: The QA-passed clean extraction: one directory per paper, prose in body.md.
DEFAULT_CORPUS_DIR = REPO_ROOT / "data" / "style-corpus" / "extracted"

#: Papers sampled when ``--keys`` is not given.
DEFAULT_KEYS = ["GNPTJ3EZ", "TPD3G6PX", "9B2FJ6SL", "SP2R6FF9"]

DEFAULT_SPACY_MODEL = "en_core_web_sm"
SAMPLE_PER_PAPER = 5
SEED = 42
TRUNCATE_AT = 250


# ---------------------------------------------------------------------------
# Corpus access
# ---------------------------------------------------------------------------

def body_path(corpus_dir: Path, key: str) -> Path:
    """Return the prose file for paper ``key`` in the clean-extraction layout."""
    return corpus_dir / key / "body.md"


def read_body(path: Path) -> str | None:
    """Return the text of ``path``, or ``None`` if it cannot be read.

    A missing or unreadable paper is a diagnostic on stderr and a skipped
    paper, never a traceback: one absent extraction must not stop the operator
    from auditing the papers that *are* present (audit finding STT2).
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"  SKIPPED: cannot read {path} ({exc})", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Flagging
# ---------------------------------------------------------------------------

def find_passive_triggers(sent) -> list[tuple[str, str, str]]:
    """Return [(dep, child_text, head_text), ...] for every nsubjpass / auxpass
    child of a VERB head in this sentence.

    The rule is exactly ``phase1_pipeline.spacy_features``' rule
    (``pos_ == "VERB"`` and ``child.dep_`` in {nsubjpass, auxpass}). What the
    *caller* does with it differs from phase 1 — see the module docstring,
    point 1: phase 1 counts passive verbs, :func:`collect_flagged` counts
    sentences.
    """
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
    """Shorten ``text`` to ``n`` characters, marking the cut with an ellipsis."""
    return text if len(text) <= n else text[:n].rstrip() + "..."


def format_trigger(dep: str, child: str, head: str) -> str:
    """Render one (dep, child, head) trigger for the printed worksheet."""
    return f'flag: ({dep}: {child}, head: {head})'


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line for this printer.

    Every path default is a *default*, not a constant: an operator auditing a
    re-extraction points ``--corpus-dir`` at it and gets the same worksheet.
    """
    parser = argparse.ArgumentParser(
        description="Print a sample of spaCy-flagged passive sentences for a "
                    "human to classify. Asserts nothing.",
    )
    parser.add_argument(
        "--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR,
        help="directory of <key>/body.md bundles "
             f"(default: {DEFAULT_CORPUS_DIR})",
    )
    parser.add_argument(
        "--keys", nargs="+", default=list(DEFAULT_KEYS),
        help=f"paper keys to sample (default: {' '.join(DEFAULT_KEYS)})",
    )
    parser.add_argument(
        "--spacy-model", default=DEFAULT_SPACY_MODEL,
        help=f"spaCy model name (default: {DEFAULT_SPACY_MODEL})",
    )
    return parser.parse_args(argv)


def load_nlp(model_name: str = DEFAULT_SPACY_MODEL):
    """Load and return the spaCy pipeline used to flag passives.

    The ``import spacy`` sits here rather than at module scope so that the
    printer's helpers stay importable in an environment without spaCy; the
    dependency is genuine and this function will raise ``ImportError`` there,
    which is the correct outcome for an actual run.
    """
    import spacy

    print(f"Loading {model_name}...", file=sys.stderr)
    nlp = spacy.load(model_name)
    print(f"  model version: {nlp.meta['version']}", file=sys.stderr)
    nlp.max_length = 2_000_000
    return nlp


def run(nlp, corpus_dir: Path, keys: list[str]) -> int:
    """Print the worksheet for ``keys`` under ``corpus_dir``; return an exit code.

    ``nlp`` is passed in rather than loaded here so the driver can be exercised
    against a scripted pipeline. Returns ``1`` when no flagged sentence was
    printed, so an empty run cannot be mistaken for a clean audit.
    """
    rng = random.Random(SEED)
    rows: list[tuple[str, str, list[tuple[str, str, str]]]] = []
    totals: dict[str, tuple[int, str]] = {}

    for key in keys:
        raw = read_body(body_path(corpus_dir, key))
        if raw is None:
            continue
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

    # Print the sampled examples for human verdict.
    print("\n" + "=" * 78)
    print(f"PASSIVE DETECTION AUDIT — {len(rows)} SAMPLED FLAGGED SENTENCES")
    print("=" * 78 + "\n")
    for i, (key, sent_text, triggers) in enumerate(rows, 1):
        trig_strs = "; ".join(format_trigger(*t) for t in triggers)
        print(f"[{i:02d}] {key}")
        print(f"     SENTENCE: {truncate(sent_text)}")
        print(f"     TRIGGERS: {trig_strs}")
        print("     VERDICT : ___________")
        print()

    # Totals for context.
    print("-" * 78)
    print("Per-paper flagged-sentence counts (for context):")
    for key, (n, method) in totals.items():
        print(f"  {key}: {n} flagged sentences (ref_strip={method})")

    if not rows:
        print(
            "EMPTY SAMPLE: no flagged sentence was printed — every paper was "
            "unreadable or contained no passive trigger. Nothing was audited; "
            "check --corpus-dir and --keys.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Load spaCy, then print the worksheet; return the process exit status."""
    args = parse_args(argv)
    nlp = load_nlp(args.spacy_model)
    return run(nlp, args.corpus_dir, args.keys)


if __name__ == "__main__":
    sys.exit(main())
