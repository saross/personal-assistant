---
title: "Personal-Assistant — Working Notes"
tags: [index]
created: 2026-05-18
updated: 2026-05-18
status: seed
---

# Personal-Assistant Working Notes

Chronological lab notebook for the personal-assistant project. Empirical
observations from sessions: measurements, confirmed behaviours, surprises
that change how we'd approach similar work. Distinct from `continuity.md`
(state) and `reflections/` (meta-observations).

Format: dated entries with pithy headlines. Capture the *measurement* or
the *principle*, not the recounting.

---

## 2026-05-18: Gemini 3 Flash needs `thinking_budget=0` for structured-JSON generation

Gemini 3 Flash Preview is a reasoning model. With default thinking enabled,
thinking tokens consume the output budget before any visible JSON is
emitted. First bake-off round (10 sessions, `max_output_tokens=1024`,
default thinking) produced **0/10 parseable JSONs** — every response was
truncated mid-`purpose` field at consistent positions (~100 chars of
visible output).

Fix: set `config={"thinking_config": {"thinking_budget": 0}}` in the
`generate_content` call. Validation: re-ran same 10 sessions, same budget,
got **10/10 successes** with substantive output.

Also gives apples-to-apples comparison with Haiku (which has no thinking
mode), so it's the right choice for the auto-metadata pipeline regardless.

Anchored at: `scripts/bake-off-metadata.py` `gemini_call_once()`; bake-off
artefacts in `data/experiments/bake-off-metadata-2026-05-18/`
(`responses-gemini-baseline/` = thinking-on failures;
`responses-gemini-tuned-v1/` and later = thinking-off successes).

## 2026-05-18: Haiku Batch produces conversational text on long transcripts when instructions are in the user message

Failure mode discovered during 2026-05-18 bake-off round 2: on 5 of 10
sessions, Haiku 4.5 returned regular conversational text instead of the
required JSON — *"I saw the caveat. No response needed — just standing
by if you need anything else for the training materials. All files are
now aligned: ✓ run-sheet-basic-training-condensed.md…"*. The model
treated `[assistant]` markers in the distilled transcript as chat turns
and continued the conversation.

Root cause: structural. Instructions came before the transcript in a
single user message; after 100K+ tokens of transcript ending in an
`[assistant]` block, recency made the conversation-continuation reading
dominant.

Fix (validated): three changes in concert —

1. Move instructions to `system=` parameter (separate context layer).
2. Wrap the distilled transcript in `<transcript>…</transcript>` tags.
3. Replace `[user]` / `[assistant]` markers with neutral dividers like
   `--- User ---` / `--- Assistant ---`.
4. Put an output-format reminder *after* the closing transcript tag, so
   the last thing the model sees is "begin with `{`".

Validation: bake-off round 4 with redesigned prompt: **0/10 conversational
failures** (versus 5/10 in round 2). Effect replicated across both Haiku
and Gemini.

Anchored at: `scripts/extract-transcript-text.py` (the new dividers);
`scripts/bake-off-metadata.py` `_build_user_message()` (the wrapping);
`haiku_build_batch_requests()` and `gemini_call_once()` (the system-prompt
plumbing).

## 2026-05-18: Auto-metadata bake-off iteration trajectory — diminishing-returns curve

Five rounds of prompt iteration scored against a fixed 42-cell rubric
(7 in-window sessions × 6 fields). Each round added ~1.2-1.7K tokens to
the system prompt; per-call cost lift was ~4% per iteration because
transcript token cost dominates.

| Round | Prompt | Haiku wins | Gemini wins | Ties |
|---|---|---:|---:|---:|
| 2 | base | 29 (69%) | 1 (2%) | 12 (29%) |
| 3 | v1 tuned (specifics requirement + comparisons table) | 11 (26%) | 12 (29%) | 19 (45%) |
| 4 | v2 tuned (+ structural reqs: sequencing, rejected alternatives, contrastive numbers, user voice, conceptual characterisation, session-shape labelling) | 7 (17%) | 17 (40%) | 18 (43%) |
| 5 | v2 + title named-entity rule | (not re-scored; spot-check confirmed 3825319a title regression fixed) | — | — |

Marginal gain per round shrank from 18 cells (base → v1) to 4 cells
(v1 → v2). Round 5 fixed a single regression without re-scoring the
full rubric.

Implication: for similar prompt-tuning problems, expect ~3 iterations
before diminishing returns. Stopping criterion: when residual gaps look
stylistic / model-intrinsic rather than addressable, productionise.

Anchored at: `data/experiments/bake-off-metadata-2026-05-18/` (all
prompts, response sets, populated rubrics).
