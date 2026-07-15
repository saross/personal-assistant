# Paper-review skill — spec (draft 2026-07-01)

Status: **draft for Shawn's review.** Drafted with CC during Paper B §2 editing.

A reusable reviewer for academic paper prose, in two modes that share one
architecture:

- **critical-friend** — constructive, section-scope, drafting phase (what CC and
  Shawn did by hand across Paper B §2 this session).
- **adversarial** — hostile "Reviewer 2", whole-paper-scope, pre-submission gate.

## Prior art this builds on (reuse, don't start cold)

| Source | What we lift |
|---|---|
| `2026-mq-llm-dh-judgement-paper-b/scripts/workflows/adversarial-review-s3.mjs` | The working prototype: multi-lens skeptic panel, fail-by-default preamble, `LENS_VERDICT` schema (severity/detail/**evidence anchor**), **deterministic severity aggregation** (verdict computed from severities, not any agent's `passes` boolean), barrier via `parallel`. Its header already names the generalisation path (lift lens prompts to params; take target + atoms + constraints via `args`). |
| `llm-reproducibility/.claude/skills/reproduction-assessor/references/adversarial-review-framework.md` | **Fresh-context independence** ("reviewer sees only the artefacts… mirrors independent peer review"); the "**if it's not in the artefact, it doesn't count**" standard; dimensioned PASS/CONCERN → overall CONFIRMED/QUALIFIED/CHALLENGED; the **confirmation-bias dimension** (scrutinise "close enough"/"minor"/"expected"); the report structure. |
| `llm-reproducibility/.claude/skills/research-assessor/` | `verbatim-quote-requirements.md` (every claim → a source quote — the citation–claim-fit discipline that caught Sousa); repliCATS Seven Signals (HASS-adapted credibility rubric); `evidence-vs-claims-guide.md`. |
| Paper B §2 session (2026-06/07) | The validated section checklist: mechanical (aspell/dashes/braces/citation-resolution/word-budget), once-and-only-once, **source-fit** (Sousa/Wu catches), subsection flow/handoffs, altitude. |

## Shared architecture

- **Fresh-context panel.** Each lens is a fresh-context subagent that reads only
  the target artefact — no drafting-conversation memory. (Reflexively enacts the
  paper's own thesis: independence of context gives a check its catching power.)
- **Evidence-anchored findings.** Every finding carries a checkable anchor: line
  number, grep hit, citekey, atom id, or verbatim source quote. No anchor → not a
  finding. (From the prototype; matches the anti-confabulation write-side rule.)
- **Deterministic aggregation.** Findings carry `severity ∈ {blocker, major,
  minor}`; the verdict is computed from severities, **not** from any agent's
  self-reported pass boolean. (Anti-satisficing; from the prototype.)
- **Mechanical pre-pass (no LLM, runs first, cheap):** aspell (en_AU, tex mode),
  doubled words, dash consistency (`human--AI`), brace/paren balance, **citation
  resolution** (every `\parencite/\cite/\textcite` key defined in the bibs), word
  budget via `texcount` where available. Deterministic; feeds the report before
  any agent runs.

## Dimensions (lenses) — general, parameterised

1. **Source fidelity & claim–evidence** *(the killer dimension).* **decompose →
   classify → verify**, enacting the paper's own §2.3 method: (a) decompose the
   section into load-bearing claims carrying enough context to be checkable (heed
   the granularity caveat — no context-stripped fragments); (b) classify each as
   *cited* / *the paper's own finding* / *load-bearing but uncited*; (c) verify — a
   cited claim is checked against the **AB+ entry** for its citekey (attested
   quotes → fit verdict; the Sousa/Wu catch), a load-bearing uncited claim is
   flagged ("should this be cited?"), an own-finding passes to the consistency
   lens. Every concrete specific (number/date/name/quote) verified against source
   (look the value up — the source is the only oracle).

   **Substrate — RESOLVED (2026-07-01): a per-paper AB+ corpus, not atom maps.**
   Atom maps were a Paper-B-split artefact; no future paper has them. Instead,
   generate an AB+ entry for **every** cited source (Shawn wants this artefact in
   its own right) via the live `ab-plus-pipeline.mjs`; §2 tranches exist, generate
   the gap. The lens then checks claim ↔ AB+ attested quotes with **full**
   coverage (not "where present"). Missing entry → flag; **later, chain AB+
   generation into the reviewer workflow** so it self-heals. Generating the corpus
   is a batch LLM run → **API-gate review** before running.
   *[reuses research-assessor claims-evidence extraction, scoped down + the AB+
   pipeline + the verbatim-quote discipline]*
2. **Internal consistency & once-and-only-once.** Contradiction with other
   sections? Each concept introduced once and covered thoroughly (no redundancy,
   no gap)? Every `\ref{}` targets the right section?
3. **Calibration & over-claim.** Is each claim proportionate to its evidence?
   Over-claim ("shows/demonstrates/clearly"), mis-calibrated hedges, altitude
   (argument at altitude; exhaustive detail to a supplement). *[reproducibility
   confirmation-bias dimension]*
4. **Completeness & gaps (adversarial edge).** What objection would Reviewer 2
   raise? What is promised but not delivered? Name the weakest sentence.
5. **Voice (optional, off by default).** `phase5` diagnostic vs the corpus; on for
   a final polish only.

## Stance (changes preamble + output, not mechanics)

- **critical-friend:** constructive preamble; findings framed as improvements +
  what already works; not fail-by-default; output = prioritised suggestions.
- **adversarial:** harsh-skeptic preamble (fail-by-default, Reviewer 2); findings
  = objections + severity; output = per-dimension PASS/CONCERN → overall
  CONFIRMED/QUALIFIED/CHALLENGED → prioritised recommendations. **Reserve for
  drafts considered "done"** — Reviewer 2 on still-forming prose is premature.

## Scope

- **section (atom):** run the panel on one section file. Fast; drafting use.
- **paper (composed):** fan-out the panel over all sections (parallel) → a
  **cross-section synthesis** pass (thesis coherence, once-and-only-once *across*
  sections, claim→evidence traceability §2→§4/§5, argument arc) → an
  **adversarial synthesis** (the Reviewer-2 report) → deterministic aggregation.
  Pre-submission use.

## Report structure

Per-dimension verdict + findings (each: severity + evidence anchor + detail) →
overall verdict → prioritised recommendations. (From the reproducibility
framework.)

## Implementation

- A **skill** (working title `/review-paper`) that runs a **generalised Workflow
  script** — the prototype `.mjs`, with lens prompts and constraints lifted into
  `args`: `{ target, stance, scope, lensSet, atomMapPath?, wordBudget?,
  constraints? }`.
- Deterministic layers (mechanical pre-pass, aggregation) live in the script; LLM
  layers (lenses, syntheses) are `agent()` calls.
- **Cost profile:** section ≈ 4–5 agents; whole-paper ≈ (8 sections × 4 lenses) +
  2 syntheses ≈ ~34 agents. Whole-paper adversarial is a deliberate pre-submission
  spend, not a routine run.

## Build plan (atom-first)

1. Generalise the prototype into a parameterised **section** workflow + thin skill
   wrapper; default stance critical-friend; source-fidelity uses AB+ entries where
   present and flags the rest. Run on Paper B §3–§8 to harden the rubric.
2. **Generate the full-paper AB+ corpus** — the source-fidelity substrate *and* a
   standalone artefact Shawn wants. Run `ab-plus-pipeline.mjs` over the citekey gap
   (§1, §3–§8, any un-AB+'d §2). **API-gate review first.** Source-fidelity then
   reaches full coverage.
3. Add the **adversarial** stance (fail-by-default preamble + verdict aggregation).
4. **Chain AB+ generation into the reviewer** so a missing entry self-heals
   (auto-generate) rather than only flags.
5. Compose the **whole-paper** mode (fan-out + cross-section synthesis +
   Reviewer-2). Build near submission.

## Decisions (resolved 2026-07-01)

1. **Home:** `personal-assistant` (shared, reusable across papers). ✓
2. **Source substrate:** claim–evidence decomposition + a **per-paper AB+ corpus**
   (generate an entry for every cited source; not atom maps). ✓ — see Dimension 1.
3. **First build:** the **section atom** first, critical-friend default. ✓
4. **Panel size (default, tunable):** 4 lenses single-pass + the free mechanical
   pre-pass; add redundancy on the killer dimension only in whole-paper adversarial
   mode.
