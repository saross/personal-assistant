---
name: review-paper
description: >-
  Multi-lens fresh-context review panel for academic paper prose. Two
  stances: critical-friend (constructive, drafting phase — the default) and
  adversarial ("Reviewer 2", whole-paper pre-submission gate). Use when the
  user asks to review a paper section or whole manuscript, run an
  adversarial or Reviewer-2 pass, run a critical-friend pass, or invokes
  /review-paper. Not for code review or literature review.
---

# /review-paper — fresh-context review panel

**Announce at start:** "I'm using the review-paper skill — mechanical
pre-pass first, then the [stance] panel after the API gate."

Design doc: `~/personal-assistant/wiki/planning/paper-review-skill-spec.md`.
Workflow: `~/personal-assistant/scripts/workflows/review-paper.mjs`.
Pre-pass: `~/personal-assistant/scripts/review-paper-prepass.py`.

Core invariants (do not weaken in orchestration):

- **Fresh-context panel** — each lens reads only the target artefacts;
  never paste drafting-session context into lens prompts.
- **Deterministic verdict** — computed from finding severities (including
  the mechanical pre-pass). No agent's opinion, including the
  meta-reviewer's, ever overrides it.
- **Evidence anchors** — no anchor, no finding; applies to you too when you
  add or kill findings.
- **Model pinned at dispatch; artefact stamped at render** (provenance
  convention, spec §"Model provenance").

## Step 0 — parameters

Gather before anything runs (ask only for what you cannot infer from the
repo):

| Parameter | Default / notes |
| --- | --- |
| `targets` | Section `.tex` file(s), absolute paths |
| `repo` | Paper repo root |
| `stance` | `critical-friend`. **`adversarial` is reserved for drafts the author considers "done"** — Reviewer 2 on still-forming prose is premature; confirm before using it. |
| `scope` | `section` (1 target) or `paper` (all sections) |
| bibs / aux | Pre-pass `--bib`/`--aux` for citation resolution + label sanity; also pass the bib list as workflow `bibPaths` (source-fidelity context) |
| word budget, dash tokens | Repo conventions, if any — pre-pass flags `--word-budget` and `--dash-token` (not workflow args) |
| `abPlusDir` | Per-paper AB+ corpus (source-fidelity substrate). Missing entries get flagged, not guessed. |
| `constraints` | Hard constraints text (vocab sentinels, date rules, must-keep citekeys) — activates the constraints lens |
| `paperBrief` | 3–6 lines: what the paper argues (static context) |
| `model` | `claude-opus-4-8` unless the author overrides at the gate |
| `readOnlyContext` | Extra paths lenses may consult (supplements, atoms) — optional |
| `lensSet` | Subset of lens keys to run — optional; unknown/unconfigured keys fail fast |
| `voice` + `voiceReference` | Off by default; final-polish only |

## Step 1 — mechanical pre-pass (free, deterministic, always first)

```bash
~/personal-assistant/venv/bin/python3 \
  ~/personal-assistant/scripts/review-paper-prepass.py \
  --repo <repo> --target <rel-path> [--target ...] \
  --bib '<glob>' --aux <rel.aux> [--word-budget N] \
  [--dash-token 'human--AI'] [--build-cmd 'latexmk ...'] \
  --json-out <scratchpad>/prepass.json
```

Present its findings to the author immediately — they are free and often
actionable without any agent run. The JSON also yields:

- `findings` → pass verbatim as `prepassFindings` (they join the verdict);
- `settled_rulings` → pass verbatim as `settledRulings` (author-settled
  register; lenses must not re-litigate it). Its keys are repo-relative
  target paths — the workflow matches them against its absolute targets
  itself, so no re-keying is needed.

## Step 2 — API gate (mandatory, every run)

Before dispatching, present and get explicit approval: (1) model,
(2) real-time agents via the Workflow tool, (3) agent count, (4) estimated
tokens/cost. Approval for one run does not cover the next.

Measured baseline (§5 run, 2026-07-17, spec §"Implementation"): ~270k
subagent tokens for 4 lenses over one section, ~4–6 min wall-clock.

| Run | Agents | Rough tokens |
| --- | --- | --- |
| Section, critical-friend | 4–6 | ~0.3M |
| Section, adversarial | +meta-reviewer, +unanimous-check if clean | ~0.4–0.5M |
| Whole paper (8 sections), adversarial | ~34 (8×4 + synthesis + meta + checks) | ~2.5–3M |

Whole-paper adversarial is a deliberate pre-submission spend, not routine.

## Step 3 — dispatch

Workflow tool, `scriptPath:
~/personal-assistant/scripts/workflows/review-paper.mjs` (expand `~`), args
per the script header. Always pass `model` and `run_date` (today —
the sandbox has no clock), plus `prepassFindings` and `settledRulings` from
Step 1. Record the run ID (`wf_…`) from the **Workflow tool result
envelope** for the stamp — the script's return object cannot know it.

## Step 4 — verify contested findings BEFORE presenting

Non-negotiable (spec: the §5 METR case — a lens said the prose contradicted
a recorded anchor; the *anchor* was stale, and the naive fix would have
broken correct text). Before the report ships:

1. Verify every ref in `metaReview.verifyBeforePresenting` (adversarial
   runs only — `metaReview` is null for critical-friend), every finding
   that contradicts a recorded anchor or guard, and every pair of lenses in
   contradiction — against **authoritative sources** (re-read the target,
   the AB+ entry, or fetch the source), never against memory.
2. Classify each killed finding with the hallucinated-objection taxonomy
   (total-fabrication / partial-corruption / identifier-hijacking /
   placeholder / semantic-drift) and keep the kill list in the report — it
   is the panel's calibration record.
3. Convergence (`converged: true`) upgrades priority, never verdict.

## Step 5 — render the triaged report + stamp

Write to `<repo>/planning/reviews/review-<stance>-<scope>-<YYYY-MM-DD>.md`
(follow the paper repo's conventions if they differ). Structure:
per-dimension verdicts + findings → overall verdict (`CONFIRMED /
QUALIFIED / CHALLENGED` adversarial; `cleared` boolean critical-friend) →
prioritised recommendations (meta-reviewer priorities,
convergence-weighted). **If `partialCoverage` > 0, or `crossSection` /
`metaReview` / a triggered unanimous-check returned null, say so at the top
of the report: the verdict does not stand as a gate until the failed agents
are re-run.** Present author-facing items in three tiers:

1. **Act-now mechanical batch** — pre-authorised; no per-item review.
2. **Rulings-needed** — before→after snippets, one line of context each,
   reviewable in chat without opening the file.
3. **Standing-rulings-honoured** — re-flagged-but-already-ruled items;
   transparency only, not reopened unless the author asks.

**Stamp block (mandatory):** model (from the workflow result — the script
stamps what it *requested*; transcripts remain ground truth for what
resolved), run date, workflow `runId`, and the workflow script's git rev
(`git -C ~/personal-assistant log -1 --format=%h --
scripts/workflows/review-paper.mjs`).

## Apply phase (only when the author says apply)

- Batch fixes via **scripted exact-string replacement with per-edit
  assertions** (exact match, count == 1; abort on failure) — not
  hand-editing at volume.
- **Re-read the target immediately before applying** — the author edits
  between review and apply (two stale-buffer collisions on Paper B).
- **Gate commits on build success** (`&&`, never `;`).

## Calibration gate — SSH-hedging stress test

LLM reviewers systematically underrate prose with hedging/risk/limitation
language — the register careful SSH writing uses (LLM-REVal, spec
§"Prior-art scout findings"). The calibration lens carries an inline guard,
but the guard must be *tested*, not trusted:

- **When:** before the adversarial stance's first real use, and after any
  change to stance preambles or the calibration lens.
- **How:** run the adversarial panel over a known-good, peer-reviewed,
  deliberately hedged section (author nominates it). **Pass:** no finding
  flags a calibrated hedge as weakness; any hedge finding demonstrates
  genuine mis-calibration with evidence. **Fail:** tighten the calibration
  guard and re-test before trusting adversarial output.
- Record the result (date, target, verdict) in the spec's learnings
  section.

## After the run

Log measured cost vs the table above; feed material learnings back into
the spec (dated, in place) — that is how the §5 amendments accreted.
