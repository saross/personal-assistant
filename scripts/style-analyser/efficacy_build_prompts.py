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
from pathlib import Path

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

# Guide line boundaries (1-indexed, inclusive) for the C2 context block.
# Verified 2026-05-31 against style-guide-academic-2026-05-30-2.md (1631 lines):
#   line   23 = "## How to read this guide"
#   line   49 = "## 1. Dimension 1 ..."
#   line 1062 = end of section 11 (line 1063 = "## Appendix A")
#   line 1450 = "## Appendix F ..."  (exemplar block, runs to EOF 1631)
# The evidence/reference appendices A-E (corpus inventory, evidence ledger,
# version diff, the 8-metric gate protocol) are deliberately EXCLUDED: a
# realistic /write-like-me consumer injects the prescriptive guide plus the
# exemplars, not the evidence tables. The target numbers still appear in the
# section prose (e.g. sec 6.1 mean sentence length 21.45), so this does not
# fully remove the teaching-to-the-test exposure; see the pre-registration doc.
GUIDE_BLOCKS: list[tuple[int, int]] = [(23, 1062), (1450, 1631)]

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
    "can. " + SCAFFOLD_FORMAT + "\n\nTopic: {topic}"
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


def extract_guide_block() -> str:
    """Return the concatenated C2 context block from the guide file.

    Joins the 1-indexed inclusive line ranges in GUIDE_BLOCKS with a blank-line
    separator. Raises if the guide is shorter than the highest requested line,
    so a guide edit that shifts boundaries fails loudly rather than silently
    truncating the injected context.
    """
    lines = GUIDE_PATH.read_text(encoding="utf-8").splitlines()
    highest = max(end for _, end in GUIDE_BLOCKS)
    if len(lines) < highest:
        raise ValueError(
            f"Guide {GUIDE_PATH} has {len(lines)} lines but block boundaries "
            f"require >= {highest}; re-verify GUIDE_BLOCKS after a guide edit."
        )
    chunks: list[str] = []
    for start, end in GUIDE_BLOCKS:
        chunks.append("\n".join(lines[start - 1:end]))
    return "\n\n".join(chunks).strip() + "\n"


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
    return {
        "experiment": "style-efficacy-2026-05-31",
        "guide": str(GUIDE_PATH.relative_to(REPO_ROOT)),
        "guide_blocks_1indexed_inclusive": GUIDE_BLOCKS,
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pilot", action="store_true",
                    help="also print the pilot subset (topic_ids x conditions)")
    args = ap.parse_args()

    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    c2_context = extract_guide_block()
    C2_CONTEXT_PATH.write_text(c2_context, encoding="utf-8")

    manifest = build_manifest(c2_context)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    n_c2_words = len(c2_context.split())
    print(f"Wrote {C2_CONTEXT_PATH.relative_to(REPO_ROOT)} "
          f"({n_c2_words} words of C2 context)")
    print(f"Wrote {MANIFEST_PATH.relative_to(REPO_ROOT)} "
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
