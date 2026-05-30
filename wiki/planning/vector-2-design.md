# Vector 2 — Session-start payload reduction (DESIGN)

**Status:** Design — decisions resolved 2026-05-16; implementation pending Phase 5.
**Created:** 2026-05-16
**Author:** Claude (Opus 4.7) + Shawn
**Related:**

- `planning/memory-system-v2-design.md` — Vector 2 is the read/surfacing
  complement to v2's write-side fixes
- `planning/memory-system-v2-future-extensions.md` § C — original capture
- `planning/memory-system-v2-implementation-plan.md` — Phase 5 (migration
  sweep) is the dependency for the strongest selector
- `hooks/session-start-retrieval.py` — current implementation
- `global-claude-md/shared.md` Anti-confabulation section — the write-side
  rule Vector 2 mirrors on the read side

## 1. Motivation

The v2 confabulation fix (Phases 1–3, shipped 2026-05-16) cleans the
**write path** — every new memory passes through anchor verification and
confidence binding before it lands in JSONL. Vector 2 cleans the
**read/surfacing path** — even verified memories, when dumped as a wall
of authoritative-looking bullets at session start, drive primacy-effect
errors and fragment welding in Opus 4.7.

This is not speculative. The 2026-04-24 reduction
(`MAX_PERMANENT_OTHER` 15 → 8, `MAX_RECENT_*` 35 → 25/5) was already a
Vector-2-shaped move, motivated explicitly by *"Opus 4.7
confabulation-gravity from the high-volume decision/architecture pool"*
(hooks/session-start-retrieval.py:32–37, 102–106). Vector 2 is the next
step in a direction already established by evidence, not a new theory.

## 1a. Scope decisions (resolved 2026-05-16)

Recorded here so future sessions don't re-litigate them:

- **Scratchpad is out of scope.** Vector 2 covers the recall dump only.
  Scratchpad handling is a sibling problem (Vector 2b) for a later pass.
  Rationale: scratchpad is user-curated with a different lifecycle (no
  `verified` field, no decay, terse by design); coupling its redesign to
  Vector 2 inflates the design surface without sharing leverage.
  Empirical implication: Vector 2 alone can drop the recall dump from
  ~17 KB to ≤1.5 KB — a meaningful 15+ KB cut — but the total
  session-start payload stays bottlenecked at ~28 KB by the
  untouched scratchpad until Vector 2b lands.
- **Load mode: hybrid (tiny eager digest + lazy-on-demand depth).**
  Inject a small "what changed since last session" digest at start
  (target ≤1.5 KB), and rely on the existing tier-2 autonomous
  retrieval (`fetch-memories.py` via the Retrieval Instructions
  protocol) for everything else.
- **Sequencing: design now, ship after Phase 5.** Capture the design
  while the framing is fresh; defer implementation so the migration
  sweep can backfill `verified` across the corpus, making
  `verified=true` viable as the dominant filter (today only 8 / 24,702
  memories have `verified=true`). *[2026-05-30: the "a migration sweep
  backfills `verified` across the corpus" premise proved false — see the
  §6b reframe. Verified coverage grows forward, not via a sweep, so
  `verified=true` is the dominant filter only among the ~3.6 % anchored
  records. The sequencing decision itself (ship after Phase 5) is
  unaffected and has since shipped — PASS 1 + PASS 2, 2026-05-30.]*

## 2. Empirical baseline (2026-05-16)

Measured from the persisted session-start hook output of session
`db593d33-fafc-4ffb-8b68-d3bb6c5daae5`:

| Section | Bytes | % | Items |
|---|---:|---:|---:|
| Anti-confabulation header | 600 | 1% | — |
| Recent Memories (14 d) | 4,888 | 11% | 30 |
| Relevant Constraints | 2,698 | 6% | 10 |
| Gotchas & Patterns (14–180 d) | 1,756 | 4% | 10 |
| Key Decisions & Knowledge | 5,536 | 13% | 28 |
| Retrieval Instructions | 1,076 | 2% | — |
| **Recall dump subtotal** | **16,554** | **38%** | **78** |
| Scratchpad (global + project) | 27,404 | 62% | — |
| **Total payload** | **43,958** | 100% | |

Corpus state at design time:

- Total memories: 24,702
- `verified=true`: 8 — `verified=false`: 3 — `verified=pending`: 3 —
  `verified IS NULL`: 24,688
- Phase 2 verification ran on **18 post-v2 memories**; of those, 9
  produced anchors and were verified (4 true, 3 false, 2 pending);
  9 produced no anchors and were left `verified=NULL` per design.
- Recent-window (14 d) category distribution is dominated by `decision`
  (456), `progress` (338), `gotcha` (186), `commitment` (173),
  `architecture` (135) — the same "high-volume decision pool" the
  2026-04-24 reduction targeted.

These numbers ground the design; do not paraphrase them from memory in
later sessions — re-measure if the gap to current is >2 weeks or any
relevant code has changed.

## 3. Problem statement

Three concrete failure modes:

1. **Primacy effect.** Items at the top of a long context are
   over-weighted in downstream reasoning. The recall dump sits early in
   the system prompt and presents itself as authoritative
   (`# Memory Context` heading, bullet form, dates, tags). Even with
   the "pointers, not authorities" disclaimer, Opus 4.7 references
   surfaced entries with high conviction.
2. **Fragment welding.** When many specific identifiers (filenames,
   commit hashes, config values) sit in context together, Opus 4.7
   composites adjacent fragments into novel identifiers. The 2026-04-24
   reduction made this explicit; cutting volume reduced incidents but
   did not eliminate them. The remaining ~78 bullets are still well
   above the threshold at which welding occurs in practice.
3. **Stale-as-authoritative.** Pre-v2 memories carry no `verified`
   field. A stale memory (file moved, decision superseded) is
   indistinguishable from a current one at recall time. The drift sweep
   (Phase 5) addresses this on the corpus side; Vector 2 addresses it
   on the surfacing side — unverified content should not be surfaced
   eagerly.

## 4. Design tenets

Inherited from v2 plus one new tenet:

- **The system must be ~99% self-driving.** (v2 tenet) The digest is
  generated automatically; no review gate on what gets surfaced.
- **Fail soft, never silent.** (v2 tenet) When the digest generator
  cannot resolve a memory's status, the memory is omitted from the
  digest rather than surfaced with a fallback label.
- **Anchors over confidence.** (v2 tenet) Surfacing rank is determined
  by `verified` state, not self-reported `confidence`.
- **(NEW) Eager bytes are a budget, not a default.** The session-start
  channel costs context every session. Treat its size as a hard
  ceiling, not as something that can grow over time. Default to *less*
  surfaced; rely on lazy fetch for depth.

## 5. Proposed design

### 5a. Shape — hybrid digest + lazy depth

The session-start dump becomes a small, opinionated digest. Concretely:

```text
# Session-start digest

**What changed since {since}:**
- {N1} new memories ({categories breakdown})
- {N2} memories updated/corrected via /update
- {N3} memories forgotten via /forget

**Verified-true entries from the last 7 days ({K} items):**
- [category] summary | tags [date]
- ...

**Active commitments and waiting-for items:**
- (handled separately by accountability hook — not duplicated here)

**Anti-confabulation reminder:** unverified content from prior
sessions is not surfaced here. Use /recall to fetch it explicitly.

**For depth:** /recall <query>, or fetch-memories.py for autonomous
retrieval. Full retrieval protocol omitted — see CLAUDE.md.
```

Target size: **≤1,500 bytes** total digest. Compared to today's 16,554-byte
recall dump, this is roughly a 90% cut.

### 5b. What gets removed

- The four bucket dumps (Recent, Constraints, Gotchas & Patterns, and
  Key Decisions) — all moved behind `/recall` and the autonomous tier-2
  protocol.
- The Retrieval Instructions footer (~1 KB repeated every session) —
  moved into `CLAUDE.md` once (or a referenced doc), not the recall
  channel.
- All `verified=false` and `verified=null` entries from the eager
  surfacing path.

### 5c. What gets surfaced eagerly

Only:

- A "what changed" counter — small, mechanical, no per-entry surface.
- A bounded list of `verified=true` entries from the last 7 days,
  scored by tag overlap with the current project, capped by the
  byte budget.
- The anti-confabulation reminder (kept — it's load-bearing).

### 5d. What the tier-2 autonomous retrieval already covers

The current hook (`hooks/session-start-retrieval.py:826–861`) already
documents an autonomous-retrieval protocol that Claude can invoke
mid-conversation when topic match is detected. Vector 2 promotes this
from "footer instruction" to "primary depth mechanism" — the eager
digest stops trying to pre-fetch.

This works *only* if the protocol is actually followed. Open question
6c below.

## 6. Selector specification (stages)

### 6a. Stage 1 — pre-Phase-5 (corpus-agnostic selectors)

Phase 5 has not yet backfilled `verified` across the corpus, so the
`verified=true` filter is too restrictive (only 8 memories qualify
today). Stage 1 ships with corpus-agnostic selectors that approximate
the eventual behaviour:

1. **What-changed counter.** Read the extraction cursor + the JSONL
   tail to count new/updated/forgotten memories since a cutoff
   (default: 7 days). Mechanical; no LLM in the path.
2. **Verified-true bucket.** Include all `verified=true` memories from
   the last 7 days that have ≥1 tag overlap with the current project's
   tag profile. Cap: byte budget (not item count) — the cap is the
   binding constraint.
3. **Promoted-recent fallback** *(permanent — originally labelled
   "temporary, removed in Stage 2"; that label withdrawn 2026-05-30, see
   §6b)*.
   If the verified-true bucket fills <50% of the budget, top up with
   the K most-recent memories from the current project that have
   non-empty `anchors` (i.e. went through verification even if the
   result was not yet `true`). This prevents the digest from being
   empty during the migration window.
4. **Strict byte cap.** The selector enforces the byte budget by
   trimming the lowest-rank entries first; no spill, no overflow.

### 6b. Stage 2 — anchored-and-verified-first (the fallback is permanent)

> **Reframed 2026-05-30 (feasibility finding — supersedes the original
> "verified-first, delete the fallback" plan).** The original premise was
> that a one-off migration sweep would backfill `verified` across the whole
> corpus, after which the promoted-recent fallback could be deleted. That
> premise is false. Anchoring is a *forward* write-path feature, live only
> since 2026-05-16; the back-corpus was never anchored. Re-verified at source
> (`data/memories/memories.jsonl`, 2026-05-30): of **29,807** records, only
> **1,076 (3.6 %)** carry non-empty `anchors`, and `scripts/anchor_verify.py`
> returns `None` — not `true` — for the **96.4 %** with no anchors. A free,
> local re-resolution pass over the anchored 3.6 % lifts `verified=true` only
> marginally (the finding estimated net new ≈ two dozen, from ≈659 today).
> **Conclusion: the promoted-recent fallback is not a migration stopgap — it
> is the permanent handler for the anchor-less majority.** Broad back-corpus
> `verified` coverage would require a *retroactive anchor-generation* pass
> (re-reading transcripts with an extractor model: thousands of API calls,
> separate costed decision — see `wiki/planning/memory-system-v2-design.md`
> §4), not a backfill. Verified coverage therefore grows *forward* as the
> anchored write-path runs, not via a one-off sweep. Refs: continuity
> workstream B (2026-05-30), `scripts/anchor_verify.py`.

Stage 2 is therefore a *rebalancing* of Stage 1's selectors as
forward-anchored coverage accumulates, not a teardown of the fallback:

1. **What-changed counter.** Unchanged.
2. **Anchored-and-verified-first bucket.** Among records that *have*
   anchors, rank `verified=true` ahead of the rest, exactly as Stage 1
   does. As the anchored pool grows (forward write-path), this bucket
   fills more of the budget on its own and the fallback contributes
   proportionally less — but it is never removed, because the ~96 % of
   records that carry no anchors can only ever be surfaced by recency.
3. **Promoted-recent fallback — retained, permanently.** Top up from the
   most-recent current-project memories whenever the anchored-and-verified
   bucket underfills the budget. This is now a standing selector, not a
   migration-window crutch. (It was §6a item 3 "temporary"; that label is
   withdrawn.)
4. **Optional: verified-true preserved-stale annotation.** For the
   `inscriptions` revitalisation case (memories that are technically
   stale but deliberately preserved), the digest can surface them
   under a clearly-labelled section so Claude can distinguish them
   from current-project signal.

### 6c. Selector inputs and outputs

Input: the loaded memories list (already streamed by
`load_all_memories()`), the current project id, the project tag
profile, the byte budget.

Output: a list of memory records selected, plus a counter dict
`{new, updated, forgotten}`.

Pure function — testable in isolation, no I/O after load.

## 7. Open questions

Items not resolved here that need answers before implementation:

- **7a. "Since when" cursor.** The "what changed" counter needs a
  reference point. Options: wall-clock (7 days), last session boundary
  (read from a new state file), per-project last engagement. Wall-clock
  is simplest; per-project last engagement gives the best digest but
  needs new state. **Suggest:** wall-clock for Stage 1; consider
  per-project in Stage 2 if the simpler version proves insufficient.
- **7b. Byte budget value.** Set to ≤1,500 B in §5a. Could be tighter
  (1 KB) or looser (2 KB). The value should be tuned against
  observed compaction patterns and `/recall` invocation frequency.
  **Suggest:** start at 1,500 B and revisit after 2 weeks of operation.
- **7c. Autonomous tier-2 utilisation rate.** Vector 2's lazy-depth
  premise requires that `fetch-memories.py` is *actually* invoked when
  topic matches are detected. We have no instrumentation today to
  confirm this. **Action:** add a `fetch-memories.log` (analogous to
  `extraction.log`) before Stage 1 ships; measure utilisation over a
  fortnight. If usage is near zero, the lazy-depth premise fails and
  Vector 2 needs to surface more eagerly than this design assumes.
- **7d. Confidence label visibility.** Today's recall dump omits the
  `confidence` field by design. Should the verified-true bucket
  surface a binding marker (e.g. `[verified]` prefix)? Pro: signals
  "this passed verification" without re-introducing soft confidence
  labels. Con: more chars per entry under a tight byte budget.
  **Suggest:** omit the marker — the section heading already does the
  semantic work; per-entry annotations cost bytes the budget needs.
- **7e. Retrieval Instructions footer placement.** Moving it from the
  recall channel into CLAUDE.md is a one-line edit but increases the
  CLAUDE.md weight permanently. Alternative: keep a one-line pointer
  in the digest (~80 B), full protocol in a referenced doc.
  **Suggest:** one-line pointer in the digest, full doc at
  `global-claude-md/tier-2-retrieval.md`.
- **7f. Scratchpad coupling.** Out of scope per §1a, but if Vector 2b
  ships in the same window, the two should share the same byte-budget
  primitive rather than re-inventing it. Note for Vector 2b design.

## 8. Empirical testing plan

Before ship, run for at least one week with Stage 1 enabled on
amd-tower only (zbook and rpi-server keep current hook):

1. **Payload-size measurement.** Log session-start digest bytes per
   firing; verify median ≤1,500 B, p95 ≤2 KB.
2. **/recall and fetch-memories invocation rates.** Compare per-session
   counts vs the 2-week pre-ship baseline. Hypothesis: invocations
   *increase* under lazy-depth; if they don't, depth isn't being
   fetched, and Vector 2 is starving Claude rather than disciplining it.
3. **Verifier hit rate.** The output verifier already runs against
   important deliverables. Compare the count of confabulation-flagged
   items per fortnight pre- vs post-ship. Hypothesis: the reduction
   shows up as fewer fragment-welding cases (synthesised identifiers,
   composited paths). Sample size will be small; treat as direction,
   not significance.
4. **Subjective signal.** Shawn flags any session where the digest
   *felt* too thin (had to /recall things that should have been
   surfaced) or too thick (still seeing primacy-effect drift). One
   week of anecdotes beats a noisy quantitative comparison at this
   scale.

If any of (1)–(4) flunks, roll back to current hook on amd-tower and
revise the design before deploying to zbook/rpi-server.

## 9. Implementation sequencing

Phase ordering proposal (folds into v2 implementation plan as a new
phase 4.5 or 5b):

1. **Pre-step (instrumentation).** Add `fetch-memories.log` and a tiny
   `digest.log` (per-session: bytes, item count, since-cutoff).
   Useful regardless of when Stage 1 ships.
2. **Stage 1 implementation.**
   - New module: `scripts/digest.py` (pure function: selector + byte
     cap). Reuses `load_all_memories`, `derive_project`,
     `collect_project_tags` from the existing hook.
   - Rewrite the digest-producing section of
     `hooks/session-start-retrieval.py` to call `digest.py`.
   - Move full Retrieval Instructions to
     `global-claude-md/tier-2-retrieval.md`.
   - Test suite: digest size under various corpus states, selector
     correctness with `verified=true/false/pending/null` mixes,
     edge cases (empty corpus, no verified entries, all entries
     foreign-project).
3. **Roll out to amd-tower only.** Two-week observation window.
4. **Review.** Evaluate the 4 measurements from §8. Decide go/no-go on
   zbook + rpi-server rollout.
5. **Stage 2 (rebalance, not teardown).** Per the 2026-05-30 feasibility
   finding (§6b) there is no corpus-wide `verified` backfill and the
   promoted-recent fallback is permanent. "Stage 2" is the ongoing
   rebalancing of the anchored-and-verified bucket against the fallback as
   forward-anchored coverage accumulates — not a one-off removal step.

## 10. Risks and mitigations

- **R1: Lazy depth isn't fetched.** Mitigation: §8 measurement (2).
  Rollback path: bring back a bounded permanent slot (≤2 KB) ahead of
  the digest.
- **R2: Verified-true corpus too sparse to surface anything useful.**
  Mitigation: promoted-recent fallback (§6a item 3). Per the 2026-05-30
  finding (§6b) this sparsity is structural, not a migration-window
  transient (~96% of records carry no anchors and never will via backfill),
  so the fallback is a permanent, explicit selector rather than a
  time-limited crutch.
- **R3: Cross-project signal lost.** Today's hook gives 8 / 28
  permanent slots to other-project memories under tag-relevance
  ranking. Stage 1's verified-true filter has no cross-project quota.
  Mitigation: byte budget is small enough that even one cross-project
  match displaces one same-project match; rely on tag-overlap scoring
  to surface the right cross-project items rather than reserving slots.
- **R4: The digest becomes another welding surface.** Even a tight
  digest, if it lists 8–10 specific identifiers, can drive fragment
  welding. Mitigation: surfacing `verified=true` only means each
  identifier is one that resolves *today* — welding two resolving
  paths produces a non-resolving path, which the verifier catches.
  This is a softer mitigation than the byte cap and may need
  revisiting.
- **R5: Phase 5 slips.** Stage 1 is designed to work without Phase 5;
  the fallback covers it. Per the 2026-05-30 finding (§6b) the fallback is
  permanent regardless of Phase 5 timing, so a slip costs nothing here —
  there is no fallback-removal "cleanup win" gated on Phase 5.

---

*Open this doc when Phase 5 is near completion or when you're ready
to schedule the Vector 2 implementation. Do not re-litigate the
resolved decisions in §1a without explicit reason.*
