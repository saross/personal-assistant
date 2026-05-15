# Memory System v2 — Design Doc (DRAFT)

**Status:** Decisions resolved 2026-05-15 — ready for implementation planning.
**Created:** 2026-05-14 (drafted), 2026-05-15 (decisions folded in)
**Author:** Claude (Opus 4.7) + Shawn
**Related:** `planning/memory-corpus-audit-2026-05-14.md` (audit complete — findings
folded in below); `global-claude-md/shared.md` Anti-confabulation + Memory System
sections (already updated).

## 1. Motivation

A verifier run regularly turns up confabulations in important outputs. Investigation
traced two structural vectors, plus a third interaction effect:

1. **Contamination** — memories enter the corpus without verification. Confabulated
   specifics from a past session become "fact" for future sessions.
2. **Surfacing / primacy** — even true memories, dumped as authoritative-looking
   bullets at session start, get treated as established ground truth and shape
   downstream claims without triggering the "verify before citing" reflex.
3. **Dual memory systems** — the custom JSONL system runs in parallel with Anthropic's
   harness-injected "auto memory" (MD-based). Asymmetric framing and uncontrolled write
   paths amplify both vectors above. (Addressed: `shared.md` now declares the JSONL
   system canonical and the MD system legacy. This doc does not revisit it.)

This doc proposes v2 changes to the **write side** of the custom system, importing the
better disciplines from the MD system without losing the JSONL system's scale,
decay, tagging, and semantic-search advantages.

Vector 2 (session-start payload reduction) is a **separate workstream**, explicitly
deferred — not covered here.

## 1a. Design tenets

- **The system must be ~99% self-driving.** No proposed change may rely on a
  review-gated step in the steady state. Manual review is allowed at *bootstrap*
  (formalising vocabulary, one-off migrations) and at *exceptional* moments
  (verifier surfaces a concern). It is not allowed as a per-write or per-recall
  gate. This rules out: review-required link creation, propose-and-confirm
  autonomous saves, blocking existence checks that need a human, and any
  reconciliation step that depends on a human reading the queue.
- **Fail soft, never silent.** When a check fails (anchor unresolved, link
  ambiguous, category invalid), the memory still lands — but with a structured
  flag (`verified: false`, `confidence: low`, etc.) that recall ranking respects.
  Better an audit-trail entry than a dropped memory or a silent corruption.
- **Anchors over confidence.** A memory's trustworthiness is determined by
  whether its claims resolve, not by a self-reported confidence label. The
  `confidence` field is decorative if it is not bound to an objective condition.

## 2. Current state (from P1 verification, 2026-05-14)

- **Write paths are exactly two:** `/remember` (user-invoked manual capture) and
  `hooks/extraction-hook.py` (automatic, on Stop/PreCompact/SessionEnd).
  Retrospective categories are also assigned during `/weekly-review`.
- **MCP memory server (`scripts/memory_mcp.py`) is read-only** — no programmatic
  write tool exists.
- **Extraction is the contamination machine.** Memories are extracted by
  **Haiku 4.5** reading a *truncated* transcript (≤30 exchanges, 3000 chars/message,
  thinking blocks cut to 1500 chars). Haiku summarises another model's work post-hoc,
  with no access to the files referenced. A confabulated filename in the main session
  is extracted verbatim and stamped `confidence: high`.
- **No source anchors.** The extraction prompt asks for category/content/confidence/
  tags/summary. Records carry `session_id` but no turn/UUID anchor, no file pointer.
  `source_context` (present on ~72% of entries) is free text, not a verifiable
  reference. The corpus is largely **unverifiable by construction**.
- **Corpus shape:** 25,581 memories — 93% `extraction`, 6.4% `reprocessing`,
  0.6% (157) `manual`. Growth: Feb 6,022 / Mar 6,733 / Apr 9,356. Roughly doubles
  every 3–4 months. Two rogue categories present (`feedback` ×5, `preference` ×1)
  outside the extraction hook's `VALID_CATEGORIES`.
- **"Claude can save" mode:** the write *procedure* exists (the `/remember` steps),
  but there is no autonomous trigger — nothing lets Claude decide mid-session that
  something is worth saving and capture it without the user typing the command.

## 3. Proposed changes

### A. Source anchors on every write

Every checkable specific in a memory must carry a re-verifiable anchor. CLAUDE.md
write-side rule already states this for Claude-driven writes; the **extraction hook
must enforce it too**, since that is 93% of the corpus.

- **Schema:** add a structured `source_anchor` field (or promote `source_context`
  to structured form). Candidate shape: `{type: file|commit|zotero|url, ref: "...",
  line: N?}`. Multiple anchors allowed.
- **Extraction prompt:** instruct Haiku to populate `source_anchor` only from
  anchors *actually present in the transcript* (a file path the session edited, a
  commit hash, a Zotero key). If no anchor is available, Haiku must either lower
  `confidence` or reword to drop the false precision — never invent an anchor.
- **Recall:** before citing a memory as fact, the anchor is checked for resolution
  (file exists / commit exists). Unresolvable anchor → memory flagged stale.

### B. Why / How-to-apply structure for guidance categories

The MD system's feedback type forces capture of *reasoning*, not just the rule.
Import this for **guidance-bearing categories** — those that tell future-Claude how
to behave, as opposed to recording a fact:

- Candidates: `feedback` (formalise the rogue category), `decision`, `gotcha`,
  `methodology`, `pattern`, `error_mode`.
- A memory in these categories should carry, in addition to `content`:
  - **Why** — the reason/incident behind the rule. This is what survives code drift.
  - **How to apply** — when/where the guidance kicks in, so edge cases can be judged.
- **Decision:** structured fields (`why`, `how_to_apply`), not content convention.
  Queryable, enforceable in the extraction prompt and `/remember`, and recall can
  ranking-boost entries that have both fields populated.

### C. Typed links between memories

Tags express *topic*; they cannot express *relationship*. Add typed links so the
corpus becomes a graph, not a bag.

- **Schema:** `links: [{relation, target_id}]`. Relation vocabulary (draft):
  `revises`, `supersedes`, `supports`, `contradicts`, `refines`, `depends-on`.
- **The hard problem — who creates links?** Extraction-time Haiku cannot: it does
  not see the corpus, so it does not know related memory IDs. Link creation needs
  corpus awareness.
- **Decision:** combo of three mechanisms, ranked by priority:
  1. **Primary — `/remember`-time and autonomous-save-time linking.** When
     Claude is writing the memory and knows it revises/supersedes/contradicts a
     specific prior memory, link immediately. Cheapest, highest precision. The
     extraction hook can do this too if the conversation surfaces the relation
     explicitly.
  2. **Secondary — periodic linking pass** (analogous to `/tags` gardening).
     Per the self-driving tenet, this must run automatically and auto-apply
     high-confidence links, not propose-for-review.
  3. **Tertiary — semantic-search-assisted on write.** Surface near-neighbours
     to the writer; auto-link only above a strict similarity threshold to keep
     it self-driving.

### D. Conscious "Claude can save" mode

Give Claude an autonomous capture trigger — decide mid-session that something is
worth saving, and write it (following the `/remember` procedure) without the user
invoking the command.

- **When to fire** — needs explicit criteria, analogous to the MD system's
  "when_to_save" guidance but for the JSONL categories. E.g. user articulates a
  durable preference/constraint; a non-obvious decision is made with rationale; an
  approach notably succeeds or fails.
- **Transparency** — autonomous saves must be announced in-conversation, never
  silent. Draft: "Saved to memory: [category] — [summary]."
- **Decision:** announce-and-save, immediate write (no end-of-session batching).
  Per the self-driving tenet, no propose-and-confirm step.
- **Coordination risk:** if Claude saves autonomously *and* the extraction hook
  later runs over the same transcript, the same fact is captured twice. Mitigation:
  extend the `COMMAND_MARKERS` mechanism (currently skips `/remember` exchanges) to
  also skip autonomous-save announcement turns, so the hook does not re-extract.

### E. Extraction-hook hardening (audit-informed)

The audit (2026-05-14) **reframed the problem**: active confabulation is rare
(~1.2% of a weighted deep sample, probably lower corpus-wide); the dominant
defect is **unverifiability — 53% of the corpus carries no anchor at all, and
71% of the deep sample cannot be mechanically checked.** The post-4.7 cohort
does *not* confabulate at a higher rate than older cohorts — but volume means
~135 confabulated and ~5,500 unauditable entries land per month at current
rates. Ranked changes (from audit recommendations):

1. **Mandatory `anchors` array** for `decision`, `progress`, `architecture`,
   `gotcha`, `provenance`, `completion` (change A). If the transcript contains
   no anchor, downgrade or drop the entry — do not store an unauditable
   high-confidence claim. Highest-leverage change.
2. **Hybrid existence-check pass.** *Synchronous* fast check at extraction time
   — stat the file, `git rev-parse` the hash, search the *repo set* (sibling
   repos under `~/Code` plus the `pa-data` submodule), not just the cwd repo.
   Resolves → `verified: true`. Does not resolve → still append, but with
   `verified: false` and `confidence` downgraded (do not reject — Haiku may have
   misnamed; recall de-weights the entry). *Plus* a periodic drift sweep
   (Section 4) that re-verifies anchors over time and re-flags entries whose
   anchors have since disappeared. Fully automatic, fail-soft, no human-in-loop
   per the self-driving tenet. Would have caught all five sampled
   confabulations.
3. **Volume throttling / stricter inclusion.** April produced ~9,300 entries;
   the "prefer fewer high-quality" prompt instruction is not biting. Volume is a
   risk multiplier even at a constant error rate.
4. **Extractor-model bake-off.** Run a small comparison: Haiku 4.5 (current),
   Gemini 2.5 Flash, and Sonnet 4.6 (if affordable at the per-session × current
   volume rate) on a representative sample of recent sessions. Compare anchor
   recall, confabulation rate, and per-memory cost. **Cost-model approval gate
   per CLAUDE.md applies** — present model set, sample size, total call count,
   and estimated cost before any spend; approval for the bake-off does not
   imply approval for ongoing use of the winner.

### F. Bind `confidence` to an objective condition

93.1% of the corpus is `confidence: high`, including every confabulation the
audit found. **Decision:** formalise rather than remove. Bind the field to an
objective condition tied to verification state. Draft rubric:

- `high` → `verified: true` (anchors resolve) **and** category in the
  guidance set has both `why` and `how_to_apply` populated (where applicable).
- `medium` → `verified: true` but missing structural fields, *or* `verified:
  pending` (sync check timed out or anchor type not checkable, e.g. Zotero key
  with the API offline).
- `low` → `verified: false` (anchors did not resolve) or no anchors present.

Extraction-time `confidence` from Haiku is overwritten by this rubric — the
extractor's self-rating is advisory only. Recall ranking respects the bound
value.

### G. Fix the `project` → repo decode

The `project` field encodes the session cwd, but cited commits and files
routinely live in submodules or sibling repos (audit Mode D — five sampled
entries cited hashes that fail in the cwd repo but resolve elsewhere). Any
verification logic must search a repo set.

**Note on the `inscriptions` cluster:** the audit flagged these as
mis-attributed because the current repo content does not match the Nov/Dec 2025
descriptions. Shawn's clarification (2026-05-15): the repo is a *revitalisation*
of a moribund project on the same conceptual topic — same project, new
iteration. The earlier entries are not mis-attributed; they describe a prior
iteration of legitimate work. The drift sweep must therefore distinguish
**project-revitalisation drift** (legitimate, anchors gone but memory retains
historical value) from **true staleness** (anchor disappeared, memory no longer
reflects reality). Concrete rule: anchors gone *and* the surrounding category
is permanent (e.g. `architecture`, `decision`, `provenance`) → preserve with
`verified: stale` flag, do not de-weight as harshly as `verified: false`.

## 4. Migration of the existing 25k corpus

Audit-informed. The corpus is 99.4% machine-generated; 53% unanchored;
duplication is negligible (0.1% — not a problem). Confabulations are few in
absolute terms but unverifiable entries number in the thousands.

**Chosen sequence (decision 2026-05-15):**

1. **Fix the forward pipeline first** (changes A, E, F, G). New writes land
   anchored, verified, and correctly attributed. Stops the bleeding before
   touching the existing corpus.
2. **Targeted schema fix** — formalise `feedback` in `VALID_CATEGORIES` and
   re-categorise the single `preference` entry as `feedback`. Closes the
   six-entry schema mismatch. One-off, ~10 minutes.
3. **Establish the periodic drift sweep** (audit rec #7) — automated quarterly
   anchor-existence check across the whole corpus, with the
   revitalisation/staleness distinction from change G. Self-driving per tenet.
4. **Bulk-flag** unanchored permanent-category entries with `verified: false`
   so recall de-weights them. Cheaper than a retroactive anchor pass; preserves
   the entries for historical context.
5. **Reassess** after the sweep and the bulk-flag run produce data. Decide
   whether a retroactive anchor pass on high-value categories is worth the
   cost. Hold this open — do not commit to it now.

**Out of scope for migration:** transient categories (`progress`, `context`,
`waiting_for`) — decay erodes them naturally.

## 5. Resolved decisions (2026-05-15)

All eight open questions from the 2026-05-14 draft are resolved. Decisions live
in their respective change sections; this is the index:

| # | Topic | Decision | Lives in |
|---|---|---|---|
| 1 | Why/How-to-apply form | Structured fields (`why`, `how_to_apply`) | Change B |
| 2 | Link-creation mechanism | Combo, `/remember`-time primary, all auto-applied (no review gate, per tenet) | Change C |
| 3 | Conscious-save autonomy | Announce-and-save, immediate write | Change D |
| 4 | Extractor model | Bake-off Haiku vs Flash vs Sonnet; cost-model gate before any spend | Change E.4 |
| 5 | Migration stance | Forward fixes → schema fix → drift sweep → bulk-flag → reassess anchor pass | Section 4 |
| 6 | Rogue categories | Formalise `feedback` in `VALID_CATEGORIES`; fold lone `preference` into `feedback` | Section 4 step 2 |
| 7 | `confidence` field | Bind to objective condition (verification + structural completeness) | Change F |
| 8 | Existence-check timing | Hybrid: sync fast check + periodic drift sweep, fail-soft | Change E.2 |

The design tenets in section 1a (self-driving, fail-soft, anchors-over-confidence)
took load on questions 2, 3, and 8 — each was decided in the direction the tenets
prescribed once the tenets were made explicit.

## 6. Out of scope / deferred

- Session-start payload reduction (vector 2) — separate workstream.
- Anything touching the read/recall ranking algorithm beyond anchor-resolution checks.
- MCP server changes — staying read-only for now.
