# Paper-review skill — spec (draft 2026-07-01)

Status: **draft for Shawn's review.** Drafted with CC during Paper B §2 editing.
Updated 2026-07-17 after the first full multi-agent critical-friend run (Paper B
§5 Discussion) — amendments are marked *(§5 run, 2026-07-17)* in place; material
with no existing home is in the dated learnings section at the end.

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
- **Settled rulings travel with the target** *(§5 run, 2026-07-17)*. Feed each
  lens the target file's settled-rulings register (the STANDING GUARDS /
  wording-guards comment block), explicitly marked "author-settled — do not
  re-flag; report only if the prose has drifted from the recorded ruling".
  Without this, fresh eyes relitigate closed questions: the §5 mechanical lens
  re-flagged four items the author had ruled on within 24 hours (apparatus-knot
  wording, "an historical", "gave up on", remit-in-close) — wasted findings and
  wasted author attention.
- **Evidence-anchored findings.** Every finding carries a checkable anchor: line
  number, grep hit, citekey, atom id, or verbatim source quote. No anchor → not a
  finding. (From the prototype; matches the anti-confabulation write-side rule.)
  Lenses also emit an explicit `CLEAN: <dimension>` line for each dimension with
  no findings, so silence is never ambiguous *(§5 run, 2026-07-17)*.
- **Deterministic aggregation.** Findings carry `severity ∈ {blocker, major,
  minor}`; the verdict is computed from severities, **not** from any agent's
  self-reported pass boolean. (Anti-satisficing; from the prototype.)
  *(§5 run, 2026-07-17 — two aggregation rules added:)*
  - **Convergence upgrades priority.** Independent convergence is a severity
    signal: when several lenses find the same issue unprompted, upgrade its
    confidence/priority in the report. On the §5 run, three lenses
    independently found the same structural miscount (the roadmap said "five
    further principles"; six `\paragraph` blocks followed).
  - **The orchestrator MUST verify contested findings against authoritative
    sources before presenting.** One lens reported the prose contradicting the
    file's own verification anchor (METR 80% vs a recorded "90%"); source
    verification (arXiv fetch) showed the *prose* was right and the *anchor*
    was stale — the naive fix would have broken correct text.
- **Mechanical pre-pass (no LLM, runs first, cheap):** aspell (en_AU, tex mode),
  doubled words, dash consistency (`human--AI`), brace/paren balance, **citation
  resolution** (every `\parencite/\cite/\textcite` key defined in the bibs), word
  budget via `texcount` where available. Deterministic; feeds the report before
  any agent runs. *(§5 run, 2026-07-17 — three checks added:)*
  - **Aux-label sanity check.** For every `\ref` target, read the `\newlabel`
    value from the `.aux` and flag implausible resolutions (e.g. all supplement
    labels resolving to the same section number). The §5 run's biggest catch:
    labels on `\section*`/`\subsection*` (starred — the counter never steps)
    made every "Supplement~A `\ref{supp:A.3}`" render as "Supplement A 6"
    across seven sites, silently passing every "clean" build. A one-line aux
    grep would have caught it months earlier.
  - **Guard-comment anchor freshness.** Header comments that cite file:line
    anchors (e.g. "verified at 04:235") go stale when files are edited or
    comments consolidated; verify each anchor still points at the claimed
    content. The §5 run caught the orchestrator's own stale anchors.
  - **Build-convergence gate.** Clean-rebuild (`latexmk -C`, then a raised
    `$max_repeat`) as part of the pre-pass; and in the apply phase, **always
    gate commits on build success (`&&`, not `;`)** — the §5 run pushed a
    commit past a failed build because the chain wasn't gated (harmless, a
    convergence artefact, but the hole is real).

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
   no gap)? Every `\ref{}` targets the right section? *(§5 run, 2026-07-17:)*
   duplication findings are **policy questions, not defects** — when a guard
   says "don't restate §4 evidence" but the author has deliberately written
   compressed worked examples, the fix is often amending the guard to codify
   actual practice, then repairing only objective breaches (identical strings,
   verbatim cross-section echoes). The lens reports the tension; the
   orchestrator frames it as guard-vs-prose for the author to rule on.
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

Two scope extensions validated on the §5 run (2026-07-17) — candidates for the
skill's checklist:

- **Whole-paper heading review:** accuracy, parallelism, grammatical
  consistency of heading forms, and collisions (e.g. two "Limitations"
  sections left behind after a restructure).
- **Cross-reference audit** distinguishing wrong-level refs (fix) from
  deliberate section-level refs (keep), including adding subsection labels
  where targets lack them.

## Report structure

Per-dimension verdict + findings (each: severity + evidence anchor + detail) →
overall verdict → prioritised recommendations. (From the reproducibility
framework.)

**Triaged presentation** *(validated on the §5 run, 2026-07-17)* — three tiers,
so author rulings can be collected in one batch:

1. **Act-now mechanical batch** — author pre-authorises; no per-item review.
2. **Rulings-needed** — before→after snippets with one line of context each,
   so the author can review in chat without opening the file.
3. **Standing-rulings-honoured** — items flagged again by fresh eyes but
   already ruled on; listed for transparency, not reopened unless the author
   asks.

## Implementation

- A **skill** (working title `/review-paper`) that runs a **generalised Workflow
  script** — the prototype `.mjs`, with lens prompts and constraints lifted into
  `args`: `{ target, stance, scope, lensSet, atomMapPath?, wordBudget?,
  constraints? }`. *(Built 2026-07-24 — see the build record at the end. The
  live arg surface is documented in the workflow script's header; `atomMapPath`
  was superseded by the AB+ substrate decision, and `wordBudget` moved to the
  mechanical pre-pass.)*
- Deterministic layers (mechanical pre-pass, aggregation) live in the script; LLM
  layers (lenses, syntheses) are `agent()` calls. *(Amended 2026-07-24: the
  Workflow sandbox has no filesystem access, so the mechanical pre-pass lives in
  its own Python script and its findings enter the aggregation via
  `prepassFindings`.)*
- **Cost profile:** section ≈ 4–5 agents; whole-paper ≈ (8 sections × 4 lenses) +
  2 syntheses ≈ ~34 agents. Whole-paper adversarial is a deliberate pre-submission
  spend, not a routine run. Measured on the §5 run (2026-07-17): roughly 270k
  subagent tokens across four lenses, ~4–6 minutes each (parallel).

## Build plan (atom-first)

1. Generalise the prototype into a parameterised **section** workflow + thin skill
   wrapper; default stance critical-friend; source-fidelity uses AB+ entries where
   present and flags the rest. *(Built 2026-07-24; hardening runs on Paper B
   §3–§8 still to do.)* Run on Paper B §3–§8 to harden the rubric.
2. **Generate the full-paper AB+ corpus** — the source-fidelity substrate *and* a
   standalone artefact Shawn wants. Run `ab-plus-pipeline.mjs` over the citekey gap
   (§1, §3–§8, any un-AB+'d §2). **API-gate review first.** Source-fidelity then
   reaches full coverage. *(Done 2026-07-24 — 75/79, see substrate status.)*
3. Add the **adversarial** stance (fail-by-default preamble + verdict aggregation).
   *(Built 2026-07-24, incl. Devil's-Advocate hard rules, meta-reviewer, and
   unanimous-check; SSH-hedging stress test still to run.)*
4. **Chain AB+ generation into the reviewer** so a missing entry self-heals
   (auto-generate) rather than only flags. *(Not built — still open.)*
5. Compose the **whole-paper** mode (fan-out + cross-section synthesis +
   Reviewer-2). Build near submission. *(Structurally built 2026-07-24 —
   `scope: 'paper'` fans out per-section panels, then cross-section synthesis,
   then meta-review — but unexercised on a real paper.)*

## Decisions (resolved 2026-07-01)

1. **Home:** `personal-assistant` (shared, reusable across papers). ✓
2. **Source substrate:** claim–evidence decomposition + a **per-paper AB+ corpus**
   (generate an entry for every cited source; not atom maps). ✓ — see Dimension 1.
3. **First build:** the **section atom** first, critical-friend default. ✓
4. **Panel size (default, tunable):** 4 lenses single-pass + the free mechanical
   pre-pass; add redundancy on the killer dimension only in whole-paper adversarial
   mode.

## Learnings from the §5 run (2026-07-17)

First full multi-agent critical-friend run: Paper B §5 Discussion, four
fresh-context lenses launched in parallel over one section file
(flow/altitude; duplication & cross-section consistency; claim–evidence &
cross-ref audit; mechanical & register) — a run-specific partition of the
dimensions above, not a replacement for them. Each lens returned raw findings
with `severity ∈ {blocker, major, minor}`, a verbatim anchor, and
`CLEAN: <dimension>` lines; the orchestrator verified contested findings
against sources before presenting a triaged report; author rulings were
collected in one batch. Amendments marked *(§5 run, 2026-07-17)* throughout
the spec came from this run; what follows had no existing home.

### Apply phase (new — the spec previously stopped at the report)

- **Batch fixes via scripted exact-string replacement with assertions.** A
  Python script with per-edit assertions (exact-string match, count == 1)
  proved safer than hand-editing at volume; a failed assertion aborts rather
  than silently mis-applying.
- **Concurrent-author risk is real.** The author edits between review and
  apply — re-read the target immediately before applying; two stale-buffer
  collisions happened earlier in the same project.
- **Gate commits on build success** (`&&`, not `;`) — see the
  build-convergence gate under the mechanical pre-pass.

## Prior-art scout findings (2026-07-24)

Closed-loop `/prior-art-scout-iterate` run before freezing the adversarial
design: PASS after one iterate pass, 24 candidates, 117 claims verified.
Full report: `prior-art-adversarial-reviewer-2026-07-24.md` (same
directory). Verdict: **build, informed by** — nothing found does hostile
whole-paper pre-submission review for humanities/social-science argument
structure; the commercial services that exist (PeerGenius.ai 7-persona
panel + editor aggregation; Enago AI Peer Review Lite) are STEM/biomedical
and closed. Design imports below were candidates for Shawn's ruling; the
2026-07-24 apparatus-build instruction ("adversarial stance, meta-reviewer
pass, Devil's-Advocate hard rules, SSH-hedging stress test") ruled the
first three IN — each is now built (see the build record). The
hallucinated-objection taxonomy was adopted in the build as vocabulary
only (CC's call, pending explicit confirmation); the last two are
unchanged (deferred / benchmark). Statuses noted per item:

- **Devil's-Advocate hard rules** (tianmind-studio/expert-review-panel,
  MIT) → *adversarial stance preamble*. **BUILT 2026-07-24** (hard-rule
  fields are schema-required in adversarial mode; `[UNANIMOUS-CHECK]`
  dispatches a devil's advocate when the full panel returns clean).
  Dissent must cite specific
  evidence, name the target claim, state a falsifiable counter-condition,
  and self-declare its retraction condition; an `[UNANIMOUS-CHECK]` flag
  forces re-examination when all lenses agree. A stronger anti-sycophancy
  mechanism than "be critical", and it maps directly onto the existing
  evidence-anchor rule.
- **Meta-reviewer pass** (PeerGenius editor-aggregation pattern +
  OpenReviewer's fine-tuned-critic finding) → *whole-paper Reviewer-2
  synthesis*. **BUILT 2026-07-24** (runs on every adversarial run, both
  scopes; classifies finding trustworthiness, prioritises, names blind
  spots and verify-before-presenting refs; verdict authority stays with
  the deterministic aggregation). A distinct persona that reads the panel's own findings
  adversarially before the report is assembled. Constraint: deterministic
  severity aggregation remains the verdict authority — the meta-reviewer
  critiques and prioritises findings, never overrides the computed verdict.
- **SSH-hedging stress test** (LLM-REVal, arXiv 2510.12367) → *calibration
  checklist*. **BUILT 2026-07-24 as a required calibration gate** in the
  skill (procedure + pass criterion; inline guard added to the calibration
  lens) — **not yet run**; required before the adversarial stance's first
  real use. LLM reviewers systematically underrate prose containing
  critical/risk/hedging language — exactly the register careful SSH writing
  uses. Before trusting the adversarial mode, run it over a known-good
  hedged section and confirm calibrated hedges are not flagged as weakness.
- **Hallucinated-objection taxonomy** (arXiv 2602.05930) → *orchestrator
  verification of contested findings*. **ADOPTED AS VOCABULARY 2026-07-24**
  (the meta-reviewer's trust enum + the skill's kill-list classification;
  CC's call — cheap, and it slots into the existing verify-before-
  presenting step. Overrule if unwanted.) Classify killed objections as total
  fabrication / partial corruption / identifier hijacking / placeholder /
  semantic — gives the existing verify-before-presenting step a vocabulary
  and a calibration record.
- **Calibration harness** (jinming99/reviewer-under-review, Apache-2.0) →
  *future evaluation*. Bipartite concern-match graphs + L0–L4 ladder for
  grading AI reviewers against real referee reports. Adopt when real
  reviews exist to calibrate against (e.g. once Paper B's referee reports
  arrive) rather than building this from scratch.
- **refchecker** (markrussinovich/refchecker, MIT) → *mechanical pre-pass,
  probably redundant*. External-API citation-existence checking; our
  pre-pass already does key-resolution and the AB+ corpus does source
  verification, so note it as a benchmark, not a dependency.

## AB+ substrate status (2026-07-24 audit; RESOLVED same day — see below)

Zotero Paper-B collection audited (proposer + independent re-check +
corrected v2; scripts in session scratchpad, `abplus-audit-v2.py`):

- **Coverage: 93/171 items with AB+ notes; 55/79 cited keys (69.6%).**
  Generation work-list: **23 cited keys** (batch LLM run — API-gate review
  before launching). 53 uncited/unmapped items need triage, not generation.
- **Two pipeline prerequisites** before the gap run: (1)
  `_query_zotero_pdfs` (paper repo, `scripts/ab_plus/zotero.py`) surfaces
  PDF attachments only — needs HTML-snapshot support
  (`bockelerHarnessEngineering2026` is HTML-only); (2) the Zotero
  note-push step ran from code never committed — re-author as a tracked
  module via branch + PR (the paper repo is gated, PR-merge history).
- **Source exclusion (ruled 2026-07-24): no AB+ entries for films** —
  default-exclude non-text sources by BibTeX entry type at the
  citekey-resolution stage, *before* the attachment requirement (the
  *Ronin* case: cited via `\citealp` at `04-results.tex:145`, correctly in
  the bib, but not an AB+ target).
- Cite-regex lesson for the source-fidelity lens: match the **full**
  natbib/biblatex command family (any command containing "cite") —
  a `\citealp`-shaped miss produced a false "uncited" finding in the v1
  audit.

**Resolution (2026-07-24, same day):** the gap run completed. Paper-repo
PRs #20 (provenance pin+stamp, HTML snapshots, tracked note-push, /audit
hardening) and #21 (title-markup join fix, deterministic citation-context
seed) merged; tranche 8 generated (20 entries, `claude-opus-4-8` pinned and
transcript-verified, 117/117 quotes deterministically verified, 17/20
verifier-clean with 3 mild advisory notes); Zotero batch clean (20 notes
created, 93 back-fill provenance stamps, zero failures). **Cited-key AB+
coverage: 75/79 (94.9%)** — the remaining 4 are explicit rulings (3
unavailable sources incl. two print books, 1 film). The source-fidelity
lens's substrate is ready for the adversarial whole-paper run; late
arrivals (e.g. `Ballsun-Stanton2026Absence`) are one-key pipeline
invocations. Seed difference for tranche 8 (citation-context, not §2
synthesis) is recorded in the tranche index.

## Model provenance convention (2026-07-24)

Applies to this skill's workflow and to every agent-spawning workflow in
scope. Forensics on the AB+ corpus showed session-level records are
unreliable: a mid-session model switch left both `session.meta.json` and git
`Co-Authored-By` trailers stale, mislabelling 35 subagents' work; only
per-message transcript fields survived (see the paper repo's
`planning/ab-plus-model-provenance-2026-07-24.md`). Therefore:

1. **Pin at dispatch** — every `agent()` call passes an explicit model
   (`args.model` with a stated default), never session-inherited.
2. **Stamp the artefact** — the deterministic render/output step writes
   model, run date, workflow run ID, and script git rev into every generated
   artefact. The *script* stamps what it requested; models are never asked
   to self-report identity.
3. **Transcripts are ground truth** — the archived per-message `model`
   fields remain the audit trail for the resolved model; stamps make
   attribution artefact-local.

Enforced at launch time via the `/audit-config` error-mode table ("Agent
model unpinned") and the `/phase-gate` standards. Implemented for AB+ in
paper-repo PR #20 (2026-07-24).

## Build record (2026-07-24, second AR session)

The apparatus is built and audited. Three components, all in
`personal-assistant`:

- **`skills/review-paper/SKILL.md`** — the orchestration protocol
  (parameters → mechanical pre-pass → API gate → dispatch →
  verify-contested-findings → triaged report + provenance stamp → apply
  phase), plus the SSH-hedging calibration gate. Symlinked into
  `~/.claude/skills/` (auto-healed by `sync-symlinks.sh`).
- **`scripts/review-paper-prepass.py`** — the deterministic mechanical
  pre-pass (aspell en_AU, doubled words, dash conventions, brace/paren
  balance, full-cite-family citation resolution, texcount word budget,
  aux-label sanity with per-prefix grouping, guard-anchor freshness,
  opt-in build gate) + settled-rulings register extraction. Lives outside
  the workflow because the Workflow sandbox has no filesystem access;
  findings join the deterministic verdict via `prepassFindings`.
- **`scripts/workflows/review-paper.mjs`** — the portable panel workflow.
  Both stances, both scopes; per-stance JSON schemas (Devil's-Advocate
  fields required in adversarial mode); fresh-context lens panels fanned
  out per target; cross-section synthesis (paper scope); deterministic
  severity aggregation with convergence marking (repo-relative path
  normalisation); `[UNANIMOUS-CHECK]` devil's advocate; meta-reviewer with
  the hallucinated-objection trust taxonomy; model pinned at dispatch
  (default `claude-opus-4-8`), `run_date` echoed for the artefact stamp.

**Audit (same day):** three-agent `/audit` (one per file, cross-file
contracts in scope) found 3 Critical / 9 Medium / ~17 Low. Headline
catches, all fixed and re-verified against fixtures + real Paper B
sections: settled-rulings register keyed relative vs looked up absolute
(silently dead feature — confirmed independently by all three agents);
aux-label "starred-section" check colliding across counter types
(sec 1 / fig 1 / tab 1 → false major); citations wrapped across lines
never checked; lensSet fail-fast swallowed by `pipeline` (invalid config
would have produced CONFIRMED on zero review); no coverage guard on the
verdict (fully failed panel now throws; partial failure warns and is
echoed as `partialCoverage`, which SKILL.md rules gate-invalidating);
texcount "(errors:N)" trailer parsed as the word count. The audit-fix
round itself produced one new bug (that texcount parse) — caught by
re-running the fixtures, which is the pattern to keep: every audit fix
gets an empirical re-test, not just a re-read.

**Standing next steps:** (1) run the SSH-hedging stress test before the
adversarial stance's first real use; (2) critical-friend hardening runs
over Paper B §3–§8 (build plan step 1's tail); (3) AB+ self-heal chaining
(step 4); (4) first real whole-paper adversarial run when a paper is at
the pre-submission gate.
