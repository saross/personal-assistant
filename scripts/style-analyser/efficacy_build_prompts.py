#!/usr/bin/env python3
"""
efficacy_build_prompts.py — assemble the generation prompts for the
style-guide efficacy experiment (Workstream G, roadmap item #1).

The experiment asks whether the empirical academic style guide measurably
pulls LLM output toward Shawn's corpus, beyond a plain or a generically
academic prompt. It is a paired, three-condition design:

  * C0 — plain          : format/length scaffold + topic only.
  * C1 — generic academic: scaffold + "formal scholarly register" instruction.
  * C2 — full guide      : scaffold + the empirical guide (How-to-read +
                           sections 1-11) + Appendix F exemplars + topic.

Holding topic, task, length and format constant across the three conditions
isolates the *style guidance* as the only varying factor. The C1 condition is
the methodologically important control: it separates Shawn-SPECIFIC value
(does C2 beat C1?) from "any academic-register instruction helps" (C1 vs C0).

This script is deterministic and makes NO LLM or network calls. It extracts the
C2 guide-context block once (so the exact instruction text is archived and
reproducible), then writes every assembled (condition x topic) prompt to a
manifest JSON. Generation itself is performed downstream by fresh-context
in-CC Claude subagents — one subagent per (condition x topic x replicate) — so
the C0/C1 generations never see the guide (clean isolation). Scoring is then
done by `efficacy_score.py` (CPU-only, no API).

Usage
-----
    python efficacy_build_prompts.py            # writes manifest + C2 block
    python efficacy_build_prompts.py --pilot    # also prints the pilot subset
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style_support  # noqa: E402  (after the sys.path insertion above)

# --------------------------------------------------------------------------
# Citation stripping (2026-05-31). Citation format is venue-determined, NOT
# authorial voice (Shawn), so the injected guide must not prescribe or
# demonstrate citations. The canonical guide's §3/§9.4 now carry exclusion
# notes and the Appendix F reverse-prompts have had their citation directives
# removed, but the verbatim exemplar SENTENCES still contain citation tokens —
# this strips citations (e.g. "(Niven 2011a; Whitmore and Dennis 2019)",
# "(cf. Fish and Kowalewski 1990)", and the integrated "Smith (2012)") from
# the injected context. Year-free parentheticals such as "(FAIR)" or
# "(12 articles)", and year-bearing ones that are not citations such as
# "(Bulgaria in 2019)", are left untouched.
# --------------------------------------------------------------------------
# Finding ST17: "any parenthetical holding a capitalised word and a year"
# was too loose in one direction and too tight in the other. It deleted
# "(Bulgaria in 2019)" — a place and a date, not a citation — while leaving
# the integrated form "Smith (2012)" untouched, because the author's name sits
# OUTSIDE the brackets. The shape of a citation is matched instead: an
# optional signal phrase, an author (or two, or "et al."), a year, and an
# optional locator, repeated for a multi-work citation.
_NAME = r"[A-Z][\w'’\-]+"
_AUTHORS = rf"{_NAME}(?:\s+(?:and|&)\s+{_NAME})?(?:\s+et\s+al\.?)?"
_YEAR = r"(?:18|19|20)\d{2}[a-z]?"
_LOCATOR = r"(?:\s*[:,]\s*\d+(?:[–—-]\d+)?)?"
_SIGNAL = r"(?:cf\.\s*|see\s+(?:also\s+)?|e\.g\.,?\s*|i\.e\.,?\s*)?"
_ENTRY = rf"{_SIGNAL}{_AUTHORS},?\s+{_YEAR}{_LOCATOR}"
_CITATION_PAREN_RE = re.compile(rf"\s*\({_ENTRY}(?:\s*;\s*{_ENTRY})*\)")
#: The integrated form: "Smith (2012) argues" -> "Smith argues".
_INTEGRATED_CITE_RE = re.compile(rf"(?<=\w)\s*\({_YEAR}{_LOCATOR}\)")
_FIX_SPACE_PUNCT_RE = re.compile(r"\s+([,.;:])")
# Finding ST16: a bare `  +` collapsed the indentation of nested lists and the
# interior alignment of code blocks in the injected guide. The lookbehind
# confines it to runs of spaces AFTER visible text, and fenced blocks are
# skipped entirely.
_FIX_DOUBLE_SPACE_RE = re.compile(r"(?<=\S)  +")
_FENCE_RE = re.compile(r"^\s*```")


def _tidy_spacing(text: str) -> str:
    """Collapse interior space runs in prose lines, leaving structure alone.

    Leading indentation carries meaning in Markdown (nested list items,
    indented code), and a fenced block may be aligned deliberately, so
    neither is touched.
    """
    lines: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            lines.append(line)
            continue
        lines.append(line if in_fence else _FIX_DOUBLE_SPACE_RE.sub(" ", line))
    return "\n".join(lines)


def strip_citations(text: str) -> str:
    """Remove parenthetical and integrated citations, and tidy the residue.

    Year-free parentheticals ("(FAIR)", "(12 articles)") and year-bearing
    ones that are not citations ("(Bulgaria in 2019)") are left alone.
    """
    text = _CITATION_PAREN_RE.sub("", text)
    text = _INTEGRATED_CITE_RE.sub("", text)
    text = _FIX_SPACE_PUNCT_RE.sub(r"\1", text)
    return _tidy_spacing(text)


# Prepended to the C2 task wrapper: an explicit, belt-and-braces no-citation
# instruction (the guide §3 exclusion note already says this, but state it at
# the point of the task too).
CITATION_DIRECTIVE = (
    "Do NOT include any citations or references — citation format is determined "
    "by the publication venue, not by this author's voice, so write the prose "
    "with no parenthetical citations and no author-year references."
)

# --------------------------------------------------------------------------
# Paths (run from the repository / worktree root)
# --------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDE_PATH = (
    REPO_ROOT
    / "notes/style-guides/academic/style-guide-academic-2026-05-30-2.md"
)
EXPERIMENT_DIR = REPO_ROOT / "data/experiments/style-efficacy-2026-05-31"
C2_CONTEXT_PATH = EXPERIMENT_DIR / "prompt-c2-context.md"
MANIFEST_PATH = EXPERIMENT_DIR / "prompts.json"

# C2 context = the prescriptive guide ("How to read" through the end of §11)
# plus the Appendix F exemplar block. Located by SECTION MARKERS rather than
# line numbers, so guide edits that shift line numbers do not silently break
# the extraction (a line-number scheme did exactly that after the 2026-05-31
# citation edits). The evidence/reference appendices A-E (corpus inventory,
# evidence ledger, version diff, 8-metric gate) are deliberately EXCLUDED — a
# realistic /write-like-me consumer injects the prescriptive guide + exemplars,
# not the evidence tables.
GUIDE_BLOCK_MARKERS: list[tuple[str, str | None]] = [
    ("## How to read this guide", "## Appendix A"),   # How-to-read + §§1-11
    ("## Appendix F", None),                           # exemplars → EOF
]

# --------------------------------------------------------------------------
# Condition templates. {topic} and {c2_context} are filled per record.
# The shared scaffold fixes FORMAT and LENGTH only (no style/register), so the
# C0 baseline is genuinely un-styled. ~400 words gives comfortable margin above
# the evaluator's 200-word short-input floor (per-1k rates destabilise below it).
# --------------------------------------------------------------------------
SCAFFOLD_FORMAT = (
    "Use flowing paragraphs only — no bullet points, no headings, no lists, "
    "and no section titles. Do not include a title. Output only the prose "
    "itself, with no preamble, framing, or closing commentary."
)

C0_TEMPLATE = (
    "Write approximately 400 words of continuous prose on the topic specified "
    "below. " + SCAFFOLD_FORMAT + "\n\nTopic: {topic}"
)

C1_TEMPLATE = (
    "Write approximately 400 words of continuous prose on the topic specified "
    "below, in a formal, scholarly register suitable for a peer-reviewed "
    "academic journal article. " + SCAFFOLD_FORMAT + "\n\nTopic: {topic}"
)

C2_TEMPLATE = (
    "{c2_context}\n\n"
    "---\n\n"
    "The text above is a style guide describing one author's academic writing "
    "voice (sections 1-11), followed by few-shot exemplars of that voice "
    "(Appendix F). Write approximately 400 words of continuous prose on the "
    "topic specified below, applying this style guide as faithfully as you "
    "can. " + CITATION_DIRECTIVE + " " + SCAFFOLD_FORMAT + "\n\nTopic: {topic}"
)

# --------------------------------------------------------------------------
# Topics. Two strata of six. On-domain (A) = the corpus's own themes, phrased
# as NEW synthetic writing tasks (never "reproduce paper X"). Off-domain (B) =
# topics outside archaeology where an academic register is still natural; these
# test whether the guide transfers VOICE independently of CONTENT (and control
# for distance dropping via discipline-vocabulary overlap rather than style).
# `pilot` flags the 4-topic pilot subset (2 on-domain + 2 off-domain).
# --------------------------------------------------------------------------
TOPICS: list[dict] = [
    # On-domain (held-out corpus themes)
    {"id": "A1", "stratum": "on-domain", "pilot": True,
     "text": "the methodological case for capturing field data with "
             "structured, born-digital mobile tools rather than paper "
             "recording in archaeological survey"},
    {"id": "A2", "stratum": "on-domain", "pilot": True,
     "text": "how FAIR data principles reshape what questions a long-running "
             "landscape-archaeology project can later ask of its own records"},
    {"id": "A3", "stratum": "on-domain", "pilot": False,
     "text": "the trade-offs between standardised and project-customisable "
             "data-recording schemas across multiple field seasons"},
    {"id": "A4", "stratum": "on-domain", "pilot": False,
     "text": "the contribution of diachronic survey data to reconstructing "
             "long-term settlement patterns in a Mediterranean landscape"},
    {"id": "A5", "stratum": "on-domain", "pilot": False,
     "text": "the challenges of integrating legacy excavation archives with "
             "newly collected digital datasets"},
    {"id": "A6", "stratum": "on-domain", "pilot": False,
     "text": "the sustainability problem facing open-source research software "
             "in archaeology once initial grant funding ends"},
    # Off-domain (novel — outside archaeology)
    {"id": "B1", "stratum": "off-domain", "pilot": True,
     "text": "the methodological case for pre-registering hypotheses in "
             "experimental psychology"},
    {"id": "B2", "stratum": "off-domain", "pilot": False,
     "text": "how herd-immunity thresholds for an infectious disease depend "
             "on the structure of contact networks"},
    {"id": "B3", "stratum": "off-domain", "pilot": True,
     "text": "the trade-offs between interpretability and predictive accuracy "
             "in clinical machine-learning models"},
    {"id": "B4", "stratum": "off-domain", "pilot": False,
     "text": "why reproducibility remains contested in computational social "
             "science"},
    {"id": "B5", "stratum": "off-domain", "pilot": False,
     "text": "the economics of proprietary versus open-source licensing for "
             "an early-stage software company"},
    {"id": "B6", "stratum": "off-domain", "pilot": False,
     "text": "the role of randomised controlled trials in evaluating "
             "education interventions"},
]

CONDITIONS = ["C0", "C1", "C2"]


def _marker_line(lines: list[str], prefix: str) -> int:
    """Return the index of the first line starting with `prefix` (else raise)."""
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            return i
    raise ValueError(f"guide section marker not found: {prefix!r}")


def extract_guide_block() -> str:
    """Return the concatenated, citation-stripped C2 context block.

    Sections are located by header markers (GUIDE_BLOCK_MARKERS), robust to
    line-number shifts. Citation tokens are then stripped, because citation
    format is venue-determined and excluded from voice (see module header and
    guide §3).
    """
    lines = GUIDE_PATH.read_text(encoding="utf-8").splitlines()
    chunks: list[str] = []
    for start_marker, end_marker in GUIDE_BLOCK_MARKERS:
        start = _marker_line(lines, start_marker)
        end = _marker_line(lines, end_marker) if end_marker else len(lines)
        chunks.append("\n".join(lines[start:end]).strip())
    return strip_citations("\n\n".join(chunks).strip()) + "\n"


def build_manifest(c2_context: str) -> dict:
    """Assemble every (condition x topic) prompt record."""
    records: list[dict] = []
    for topic in TOPICS:
        for cond in CONDITIONS:
            if cond == "C0":
                prompt = C0_TEMPLATE.format(topic=topic["text"])
            elif cond == "C1":
                prompt = C1_TEMPLATE.format(topic=topic["text"])
            else:
                prompt = C2_TEMPLATE.format(
                    c2_context=c2_context, topic=topic["text"]
                )
            records.append({
                "topic_id": topic["id"],
                "stratum": topic["stratum"],
                "pilot": topic["pilot"],
                "condition": cond,
                "topic_text": topic["text"],
                "prompt": prompt,
            })
    # Record the guide's path relative to the repository when it lies inside
    # it, and absolutely when it does not: `relative_to` RAISES on an outside
    # path, which made the manifest unbuildable for a guide anywhere else.
    try:
        guide_reference = str(GUIDE_PATH.relative_to(REPO_ROOT))
    except ValueError:
        guide_reference = str(GUIDE_PATH)
    return {
        "experiment": "style-efficacy-2026-05-31",
        "guide": guide_reference,
        "guide_block_markers": GUIDE_BLOCK_MARKERS,
        "citations_stripped": True,
        "conditions": {
            "C0": "plain — format/length scaffold + topic only",
            "C1": "generic academic — scaffold + formal-scholarly register",
            "C2": "full guide — scaffold + guide sections 1-11 + Appendix F",
        },
        "length_target_words": 400,
        "short_input_floor_words": 200,
        "n_topics": len(TOPICS),
        "n_conditions": len(CONDITIONS),
        "records": records,
    }


def main(argv: list[str] | None = None) -> int:
    """Assemble every prompt; 0 on success, 2 when the guide cannot be read."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pilot", action="store_true",
                    help="also print the pilot subset (topic_ids x conditions)")
    ap.add_argument("--dry-run", action="store_true",
                    help="assemble the prompts and report them, but write "
                         "nothing")
    args = ap.parse_args(argv)

    # Finding STT-M4: the experiment directory was created BEFORE the guide
    # was read, so a missing guide or a renamed section marker left an empty
    # directory behind as the only trace of a failed run. Read first; create
    # only once there is something to put in it.
    try:
        c2_context = extract_guide_block()
    except (OSError, ValueError) as exc:
        print(f"Could not extract the guide block: {exc}", file=sys.stderr)
        return 2

    manifest = build_manifest(c2_context)
    # Which code and which guide produced these prompts.
    manifest["provenance"] = style_support.provenance_block(
        Path(__file__).name, [GUIDE_PATH])
    wrote = style_support.atomic_write_text(C2_CONTEXT_PATH, c2_context,
                                            dry_run=args.dry_run)
    style_support.atomic_write_json(MANIFEST_PATH, manifest,
                                    dry_run=args.dry_run)

    n_c2_words = len(c2_context.split())
    if not wrote:
        print(f"--dry-run: nothing written to {EXPERIMENT_DIR} "
              f"({n_c2_words} words of C2 context, "
              f"{len(manifest['records'])} prompt records)")
        return 0
    print(f"Wrote {C2_CONTEXT_PATH} ({n_c2_words} words of C2 context)")
    print(f"Wrote {MANIFEST_PATH} "
          f"({len(manifest['records'])} prompt records: "
          f"{manifest['n_topics']} topics x {manifest['n_conditions']} conds)")

    if args.pilot:
        pilot_ids = [t["id"] for t in TOPICS if t["pilot"]]
        print(f"\nPilot subset ({len(pilot_ids)} topics x {len(CONDITIONS)} "
              f"conds x 2 reps = {len(pilot_ids) * len(CONDITIONS) * 2} "
              f"generations): {', '.join(pilot_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
