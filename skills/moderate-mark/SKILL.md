---
name: moderate-mark
description: >-
  This skill should be used when the user asks to "moderate marks",
  "produce marking dossiers", "double-mark" an assessment, run a
  "second-reader pass", or "build a moderation pack". Also trigger
  when the user has just entered rubric marks for a HUMN8031
  Assessment 2 paper and wants a moderation dossier produced. Do not
  trigger for rubric design or rubric review — only for dossier
  production on a marked assessment.
version: 0.1.1
---

# Moderate Mark — HUMN8031 Assessment 2

Produce a moderation dossier for a marked literature review. The
dossier double-marks the marker's tier picks against the rubric
descriptors and the submitted text, surfaces upward and downward
descriptor-fit findings independently, and produces polished marker
comments + per-criterion borderline comments ready for Canvas.

This skill is HUMN8031-specific in v0.1.x. Paths, rubric weights,
A1↔A2 criterion mapping, and the cohort-relative norm (ANU Masters
low-70s mode) are hardcoded in the stage prompts. Externalisation
to a `config.yaml` is a v0.2 candidate.

## Pipeline overview

The skill runs four stages in sequence. Each stage is independently
re-invokable. Together they produce a single moderation dossier per
student.

```text
Stage 1 — Neutral dossier
   stage-1-produce-dossier.md
   ↓ (criterion-by-criterion descriptor-fit analysis,
      A1→A2 trajectory, identifies borderline criteria;
      NO lift or hold recommendations at this stage)
Stage 2 — Upward check
   stage-2-upward-check.md
   ↓ (for borderline-or-suggestive criteria, evaluate
      descriptor evidence for the higher tier; apply
      default-to-lower discipline; apply marker-comment-as-
      descriptor-evidence rule)
Stage 3 — Downward check
   stage-3-downward-check.md
   ↓ (for each call, evaluate whether descriptor + cohort-
      relative norm support a lower tier; apply marker-comment-
      as-descriptor-evidence rule on the downward side)
Stage 4 — Reconcile and append
   stage-4-reconcile-and-append.md
       (synthesise upward + downward findings; produce final
        mark recommendation; append polished marker-comment
        bullets and per-criterion borderline paste-ables)
```

The four stages are kept separate (not collapsed) for accountability:
each stage's reasoning is preserved in the dossier, so a moderator can
see why the recommendation landed where it did. Stage 4 is unified
in v0.1.x (reconcile + polished comments + borderline comments in one
agent run); split into 4a/4b is a v2 option if the prompt grows
unwieldy.

## Invocation patterns

- **`/moderate-mark <student-stem>`** — full 4-stage pipeline for one
  student. Example: `/moderate-mark li-jiayuan`. The student-stem is
  the dash-separated surname-given-name as it appears in the marks
  filename (e.g., `li-jiayuan` matches `li-jiayuan-1276958.md` in
  `reports/marking/a2-shawn-marks/`).
- **`/moderate-mark batch`** — pipeline across all students with marks
  entered in `reports/marking/a2-shawn-marks/`. Skip students whose
  dossier already exists at `reports/marking/dossiers/<stem>-*.md`
  unless `--force` is passed.
- **`/moderate-mark stage-N <student-stem>`** — re-run a single stage
  on an existing dossier. Stage N reads the prior stages' output from
  the dossier file in place and rewrites only its own section.

## Re-invocation: overwrite with confirmation

If `/moderate-mark <student>` is run on a student who already has a
dossier at `reports/marking/dossiers/<stem>-<submission-id>.md`,
prompt for single-line confirmation before overwriting:

```text
Dossier already exists for <student> at <path>. Overwrite? [y/N]
```

Bail on anything other than `y` / `Y` / `yes`.

## Pre-flight checks (run before any stage)

The skill bails with a clear message if any of these checks fail:

1. **Marks file present.** Glob `reports/marking/a2-shawn-marks/<stem>-*.md`. If zero or multiple matches: bail with the offending count and the matched paths.
2. **Submission text present.** Glob `data/submissions-lit-review/extracted/<stem>-*.txt`. Same rule.
3. **Rubric definition present.** Verify `reports/marking/a2-rubric-definition.json` exists.
4. **Body word count parseable.** Compute via deterministic awk extraction (see Discipline Rule 8 in `discipline-rules.md`). If unparseable, raise a flag in the dossier header rather than bailing — the marker can verify manually.

The A1 feedback file (`reports/marking/a1-feedback/<stem>-*.md`) is
treated as **optional**. If absent, proceed with an empty A1
trajectory section noting "A1 feedback unavailable — late enrolee
or other reason". This is an edge case for late enrolees.

If the marks file is malformed (no parseable rubric ratings), bail
with the parse error and the path. Do not guess.

## Inputs (HUMN8031-specific paths)

| Input | Path pattern |
|---|---|
| A2 marker tier picks | `reports/marking/a2-shawn-marks/<stem>-<canvas-user-id>.md` |
| A1 feedback (optional) | `reports/marking/a1-feedback/<stem>-<canvas-user-id>.md` |
| Submission body text | `data/submissions-lit-review/extracted/<stem>-<submission-id>.txt` |
| Rubric definition | `reports/marking/a2-rubric-definition.json` |
| Discipline rules | `discipline-rules.md` (in this skill) |
| Format spec | `dossier-format.md` (in this skill) |
| Worked example | `examples/jiang-xinrui-canonical.md` (in this skill) |

The Canvas user ID (in marks/A1 filenames) and the submission ID (in
extracted-text filename) are *different IDs*. The skill reads both
files via student-stem glob; the submission ID for the dossier output
filename comes from the extracted-text header (`# Submission ID: <id>`
on line 2).

## Output

| Output | Path pattern |
|---|---|
| Moderation dossier | `reports/marking/dossiers/<stem>-<submission-id>.md` |
| Batch progress | `reports/marking/dossiers/batch-progress.md` (batch mode only) |

## Stage prompts and supporting docs (read in this order)

1. **`discipline-rules.md`** — the 11 locked rules. Every stage must
   apply these; rules are cited by number in stage prompts.
2. **`dossier-format.md`** — the 10-section spec for the dossier
   output. Stages 1–4 each write specified sections.
3. **`examples/jiang-xinrui-canonical.md`** — the canonical reference
   dossier. Read for voice, tone, length conventions, and bullet
   structure. Format authority is `dossier-format.md`; voice authority
   is this example.
4. **`stage-1-produce-dossier.md`** — neutral descriptor-fit analysis
   and A1→A2 trajectory; identifies borderline criteria; NO lift/hold
   recommendations.
5. **`stage-2-upward-check.md`** — upward review for
   borderline-or-suggestive criteria; drift-catch logic as one
   internal trigger (NOT a named protocol).
6. **`stage-3-downward-check.md`** — cohort-relative downward review;
   marker-comment-as-descriptor-evidence rule applied on the downward
   side.
7. **`stage-4-reconcile-and-append.md`** — reconciles upward and
   downward findings; appends polished marker-comment bullets and
   per-criterion borderline paste-ables; produces the final mark
   recommendation.

## Verdict outcomes (locked vocabulary)

The dossier verdict line and per-criterion calls use exactly three
labels:

- **Aligned** — descriptor evidence supports the marker's tier
- **Lift recommended** — descriptor evidence supports the higher
  tier; default-to-lower can be overcome
- **Hold recommended** — descriptor evidence reads borderline but
  default-to-lower keeps the marker's tier (often because the
  marker's contemporaneous comment is itself descriptor evidence
  for the lower tier — Discipline Rule 2)

Borderline calls that are defensible either way are labelled
**Borderline** in the dossier body (not as a verdict outcome). They
are surfaced for transparency, not as recommendations.

## Anti-patterns (do not do these)

- Do not reintroduce "drift-catch" as a section heading or stage
  name. It is one internal trigger inside Stage 2, not a named
  protocol. The asymmetric-fatigue hypothesis was not supported by
  cohort data.
- Do not trust upstream word-count categorisations (e.g., progress
  files). The skill computes body word count itself via Discipline
  Rule 8.
- Do not write prose drafts for marker comment fields. All four
  comment-field outputs are bullets (Strongest aspect, One change,
  A1 feedback-action, per-criterion borderline). The polished
  marker comment is bullet 1, prefixed `**[Your comment, polished]**`.
- Do not recommend a tier lift that contradicts the marker's own
  contemporaneous Canvas comment when that comment names the
  defining feature of the lower tier's descriptor (Discipline
  Rule 2). This is the principal anti-inflation safeguard.

## V2 backlog (do not implement in v0.1.x)

Documented in `planning/moderate-mark-skill-plan.md` (sections F–J).
Do not pull forward without explicit ask:

- Consequential vs standard case branching (fail/escalation pathway)
- Project-specific config externalisation to `config.yaml`
- Escalated case email + convenor brief integration
- Retroactive rename pass on existing cohort dossiers
- Cohort aggregate stage (explicit, not just side-effect of batch)
