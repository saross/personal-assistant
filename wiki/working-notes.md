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

## 2026-05-18: Editable installs are mandatory when a sibling venv consumes the toolkit

The PA hook calls `~/personal-assistant/venv/bin/python3 -m cc_session_toolkit.cli ...`
— so the toolkit lives in the *PA* venv, but the source tree is at
`~/Code/cc-session-toolkit/`. Before today, `cc-session-toolkit 0.1.0`
was installed in PA's venv as a regular (non-editable) wheel. That
meant every change to `~/Code/cc-session-toolkit/src/` was invisible to
the hook until I re-ran `pip install` — and silently so.

Verified during F1 wire-up: after editing `archive.py` and re-running
the hook, the new code path didn't execute. `pip show` revealed the
non-editable install at the venv site-packages dir.

Fix: `~/personal-assistant/venv/bin/pip install -e ~/Code/cc-session-toolkit`.
Now `pip show` reports the editable install pointing at `~/Code/...`,
and source-tree changes are picked up immediately.

Implication: any cross-repo dev where machine M's venv consumes a
toolkit from repo R needs editable installs on M, *or* a tagged-release
+ reinstall step in the dev loop. zbook and rpi-server still have the
old non-editable wheel — they need the same `pip install -e` before
relying on the new path there.

Anchored at: `~/Code/cc-session-toolkit/pyproject.toml`;
`~/personal-assistant/venv/lib/python3.13/site-packages/cc_session_toolkit/__init__.py`
(now a symlink to the editable source).

## 2026-05-18: Real-world distilled-transcript sizes confirm Gemini's context-window advantage

Smoke-test on three real archived PA sessions after wiring up
`transcript_text.extract_transcript_text`:

| Session | Distilled chars | Estimated tokens |
|---|---:|---:|
| 2026-05-17 implement-quick-steps... | 512,412 | ~128,103 |
| 2026-05-16 vector-2-design... | 241,112 | ~60,278 |
| 2026-05-14 sync-personal-assistant... | 646,258 | ~161,564 |

All three were on gz-compressed JSONL. Two of three exceed Haiku's
200K-token context window; the 161K case is uncomfortably close. With
Gemini Flex's 1M-token window all three fit one-shot with multiple-x
headroom.

This is the empirical case for the chunking-vs-one-shot architectural
decision: had F1 stuck with Haiku, ~30% of PA's session corpus would
have needed chunking + cross-chunk stitching just for routine
auto-metadata. The bake-off had pre-screened to *in-window* sessions;
real-world traffic does not.

Anchored at: `~/cc-archives/personal-assistant/2026-05-{14,16,17}*/session.jsonl.gz`;
`cc_session_toolkit/transcript_text.py:estimate_tokens`.

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


## 2026-05-20: F3 backfill scope is 32 sessions, not 307

The "307 historic sessions" figure in earlier continuity entries was a
misread: it is the **total unique main-thread session count across all
amd-tower archive locations**, not the subset needing F3. The
F3-needing subset (`auto_generated.purpose == "Auto-metadata unavailable"`)
is exactly 32. This matches the refined cost estimate computed by
`scripts/backfill-session-metadata.py --cost-sample-size 20` ($1.26
mean / $2.79 p90 worst-case envelope). Inventory at
`planning/archive-inventory-2026-05-20.md`.


## 2026-05-20: Two parallel background agents on the same repo, zero conflicts

Ran C2+C3+C4 agent and M7-M15+Lows cleanup agent concurrently against
`~/personal-assistant/`. Coordination: explicit file-ownership rules
in the prompts (C2/C3/C4 owned `extraction-hook.py`,
`sync-symlinks.sh`, `data/.gitignore`; cleanup owned everything else).
Both agents instructed to `git pull --rebase` before pushing.

Result: cleanup agent's pull was a no-op (sibling's commits had
already landed); zero rebase conflicts; 14 PA commits + 2 toolkit
commits + 1 pa-data commit shipped in one window.

Pattern is reusable for future multi-agent work on shared repos:
split scope by file ownership, dispatch in parallel, defensive
rebase. Anchored at this continuity entry plus commit log
`87abe5d..0ec0a7b` (PA), `41758a3..6ac9fe2` (toolkit).


## 2026-05-20: Worktree-archives can hold canonical bytes that per-project archives stub

map-reader-llm's per-project `archive/cc-sessions/` is full of Git LFS
pointer stubs (87 sessions). The canonical bytes live at
`.claude/worktrees/agent-a59a9dae0bff3f27b/archive/cc-sessions/` — the
worktree was created when LFS smudge was active, so it has real
content. Any tool reading the per-project layer (cc-session-toolkit
backfill, rsync to consolidated store, grep across transcripts) gets
pointer-text not session content, and most fail silently or with
cryptic errors.

**Inventory pre-flight is what surfaced this** — would have been easy
to miss until consolidation failed mid-rsync.

Future: any project using Git LFS for archive content needs explicit
verification that the per-project layer has been LFS-pulled, OR migrate
to the new architecture where `archive/cc-sessions/` is gitignored and
lives only on the consolidated mount (per the 2026-05-20 architectural
decision). LLM-History-Paper has the same pattern with 49 pointer
stubs in its `archive/cc-sessions/`. Anchored at
`planning/archive-inventory-2026-05-20.md`.


## 2026-05-22: Anti-confabulation discipline applied to empirical-construction agents

When generating something that *feels* generative (a style guide, a
literature taxonomy, a methodological framework), the standard
anti-confabulation rule — re-verify checkable specifics at source —
needs structural enforcement, not just intent. The
`corpus-style-analyser` agent (`~/.claude/agents/corpus-style-analyser.md`)
enforces this via:

- Explicit per-claim status fields (`attested` / `attested-rarely` /
  `absent-when-searched` / `aspirational` / `derived-by-inference`).
- Required ≥2 verbatim quotations with paper key + section locator
  per attested claim.
- Separate evidence ledger (Appendix C) so each numbered claim in
  the body can be falsified by re-reading the named passage.
- An aspirational section explicitly walled off from corpus, so
  "things the agent thinks should be in the guide" cannot leak into
  the empirical sections without a status downgrade.

Result: claims are empirically falsifiable by re-reading the named
source. Generalises to any agent that constructs claims from a
corpus, not just style — works for taxonomies, methodological
frameworks, lit-review summaries. Run-1 output at
`notes/style-guides/academic/style-guide-academic-2026-05-22.md`
demonstrates the scaffolding in practice on 18 papers / 139k words.


## 2026-05-22: Background-agent + parent-session-reconciliation pattern for HIL empirical work

For tasks that have a batch-y empirical pass AND a human-judgement
reconciliation pass, splitting them across an agent invocation (batch,
runs while you do other work) and a future parent-session (interactive
Q&A) outperforms a single long interactive session. Run-1 of the
style guide demonstrated this: agent built the empirical guide +
aspirational section in ~14 minutes background while Shawn worked on
the inscriptions talk; reconciliation against prior conscious guides
is captured as an inbox follow-up for a fresh-eyes session.

Two specific benefits over single-session:

1. **Lower handoff cost than expected.** The agent's output file is
   the durable artefact; no conversation state needs to be carried
   forward. Reconciliation can happen any time, in any session.
2. **Fresh-eyes for the judgement pass.** Reconciliation under tired
   attention at the tail of a long session is materially worse than
   reconciliation under fresh attention in a new session, especially
   for taste-driven decisions (style, voice, methodology).

Pattern generalises beyond style guides: any task with structure
"agent extracts/analyses, human judges" benefits from the split.
Captured in agent definition under "Reconciliation with prior style
guides — NOT YOUR JOB".


## 2026-05-22 (late evening): Reference-list contamination is the default failure mode for stylometry on academic prose

Ran `Hiro-Inagawa/write-like-me`'s `scripts/stylometry.py` against the
same 18-paper Zotero corpus that produced corpus-style-analyser run-1.
Two concrete leakages visible in the output: (a) co-author surnames
`sobotkova` (56) and `ross` (52) appeared in the top-20 sentence-initial
words; (b) URL fragments `doi` (2.054/1k), `https` (1.891/1k), `org`
(1.284/1k) appeared in the top-30 distinctive content words. Roughly 5%
of the corpus passing through `compute_features` was reference-list noise.

Write-like-me's markdown stripper (`stylometry.py:115-160`) catches
frontmatter, code fences, inline code, tables, image tags, and inline
`[N]` citations — but does not detect the references-section boundary
in academic prose. Run-1 stripped references explicitly per paper (per
its `Run notes` section); the difference is visible in the corpus
footprint — 116,842 words (write-like-me) vs 139,105 words (run-1), a
~16% delta that's mostly write-like-me's *over*-stripping of legitimate
markdown structure combined with *under*-stripping of references.

Generalises: any stylometry tool that doesn't ship an explicit
academic-references heuristic will leak reference-list content into
sentence-initial-word and top-content-word distributions when fed
academic papers. The corrective for v2 of corpus-style-analyser is an
explicit references-section regex (`^(References|Bibliography|Works\s+Cited|Literature\s+Cited)\b`
case-insensitive, truncate after the last occurrence) with a fallback
heuristic that detects high-density `Author, A. (Year)` patterns. The
fallback matters: ~30% of academic publishers use venue-specific
synonyms or omit the heading entirely.

This is general for tool-evaluation, not just stylometry: when running a
genre-agnostic tool against domain-specific text, check the input/output
mass balance before trusting the distributional outputs.


## 2026-05-22 (late evening): Multi-author benchmark suites need scrutiny before applying to single-author voice work

The Wang et al. 2025 "Catch Me If You Can" evaluation ensemble (arXiv
2509.14543) was on the corpus-style-analyser v2 adoption shortlist as
a way to measure whether the produced style guide actually moves LLM
output toward Shawn's voice. The Plan agent's investigation of the
open-source release at `github.com/jaaack-wang/llms-implicit-writing-styles-imitation`
(MIT, 5 stars, last push 2026-01-16) surfaced a structural mismatch:
three of the four metrics — authorship attribution accuracy, authorship
verification, and AI-detection rate — are designed for *multi-author*
benchmarks. AA and AV ask "is this text by author X vs Y" or "are
these two texts by the same author"; both require ≥2 authors to
discriminate against. The Shawn corpus has one. AI-detection requires
external services (GPTZero). Only the style-matcher metric (Mahalanobis
distance over stylometric feature space) ports cleanly.

The adopted scope for Phase 5 of v2 is therefore a **reduced two-metric
CC-only suite**: Mahalanobis distance over Phase-1 features + the
8-metric tolerance gate from write-like-me's `references/07-verification.md`.
Both run on CPU with no external API. Optional GPTZero appendix for
generation-time AI-detection scores (~$0.05/1000 words external API
spend, opt-in).

Generalises: benchmark-shaped evaluation ensembles often assume the
discriminative-classification frame (which-of-N-classes is this?) that
fits academic benchmark datasets but not within-author personalisation
work. Before adopting a published ensemble, check whether the metrics
were designed for the *between-class* problem or the *within-class
match-to-target* problem. The frames look identical until you try to
run them on a single-author corpus and three of four metrics become
undefined.
