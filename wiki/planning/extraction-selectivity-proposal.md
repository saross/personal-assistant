# Extraction selectivity proposal (write-path plan item 14 / P3)

**Status:** PROPOSAL — awaiting Shawn's sign-off. **No change has been made to
the live extraction hook.** This documents the diagnostic and the options; the
hook (`hooks/extraction-hook.py`) is live behaviour affecting *every* session,
so it gets the item-13 treatment: design → sign-off → gated change → measure.

**Date:** 2026-06-04; **rev. 2026-06-05** — Lever 2 reworked from a write-time
hard-drop to **sideline-not-delete** after measuring the `low` bucket's
false-positive risk (carve-outs barely fire; 62 % of `low` is
permanent-category). **Author:** workstream-B (PA, memory-system).

All figures below are re-derivable at source from `data/memories/memories.jsonl`
(filter `source=extraction`) and are point-in-time (the corpus grows
continuously). Reproduce with the snippets archived in the 2026-06-04 P3
continuity entry, or via `/memory-health`.

---

## 1. Diagnostic — the hook over-extracts by ~4–7×

The extraction prompt already asks for restraint — *"Prefer fewer high-quality
memories over many low-quality ones"* and *"Typical extraction: 2–8 memories
per session"* (`hooks/extraction-hook.py:214–215`). It is almost entirely
ignored:

| Metric (source=extraction) | Value |
|---|---|
| Memories per session — median | **33** |
| — mean / p90 / p95 / max | 56.9 / 139 / 197 / **378** |
| Sessions over the 2–8 target (>8) | 339 / 393 = **86 %** |
| Share of all memories from over-target sessions | 22,087 / 22,347 = **99 %** |
| Recent 30 d extraction rate | 6,671 = **~222 / day** |

This is a **volume** problem, not a terse-junk problem: content length is
healthy (median 286 chars; only 9 % under 200 chars). The hook produces
reasonably-sized memories — just 4–7× too many of them.

**Category mix (recent 30 d):** `decision` 27 %, `progress` 19 %, `gotcha`
10 %, `commitment` 7 %, `architecture` 6 %, `pattern` 6 %, `context` 5 %.
`decision` at 27 % = ~60 "decisions"/day — implausibly many genuine durable
choices.

**Qualitative sample confirms it.** The `decision` bucket is full of
micro-decisions and plans miscategorised as durable choices:

- *"Use Quarto for slides. User will request a template or provide logo."*
- *"Kept 'Explore CC Max plan…' as a single backlog row rather than splitting…"*
- *"Slot 1 rotation: Adela paper + deck tomorrow morning…"* (ephemeral scheduling)
- *"Plan to use explore agents to summarise BolgiaTen's proposed development…"* (a plan)

**The key signal: Haiku flags a lower-value tail itself.** Of 12 sampled recent
`decision` memories, **8 were `confidence: low`**, and those samples were
ephemeral/procedural. Corpus-wide, extraction confidence is **high 75 % / low
19 % / medium 6 %**. That signal is currently **discarded**: the prompt declares
confidence *"advisory; downstream verification overrides"* (`:168`), and nothing
gates on it, so every in-category memory is persisted regardless. **Caveat,
measured (see Lever 2): the `low` bucket is *mixed*, not pure junk** — 62 % is
permanent-category and 2,400 records carry `why`/`how_to_apply` guidance fields.
This is exactly why Lever 2 *sidelines* `low` (reversible) rather than deleting
it.

## 2. Root cause

1. **Soft guidance, no enforcement.** "2–8" is a buried suggestion, not a
   constraint; long sessions yield memories roughly proportional to content.
2. **An existing value signal is unused.** Haiku's own `confidence: low`
   (19 % of output) tracks the low-value tail but is never acted on.
3. **No post-extraction gate.** Beyond the item-11 malformed-anchor drop, every
   returned memory is written verbatim. There is no value bar, cap, or ranking.

## 3. Levers (and what each would drop, simulated over the existing corpus)

Two of the three levers are **deterministic and no-API** (a view-predicate
sideline + a session cap) and can be validated *now* by replaying them over the
22,347 existing extraction records. The third (the prompt) changes what Haiku
generates and can only be measured by re-running extraction (API-gated) or
observed forward via the P6 health report.

| Policy (simulated) | Keeps | Drops | Of dropped, permanent-category |
|---|---|---|---|
| A. Drop `confidence=low` | 81 % | **19 %** | 62 % (sample-confirmed micro/procedural) |
| B. Cap top-12 / session | 19 % | 81 % | 87 % |
| C. Cap top-20 / session | 30 % | 70 % | 87 % |
| D. Drop low + cap-12 | 18 % | 82 % | 87 % |
| E. Drop low + cap-20 | 27 % | 73 % | 86 % |

**Reading the table:** the confidence gate (A) identifies a well-targeted
19 % — the tail Haiku itself flagged — but *how we act on it matters* (see
Lever 2: sideline, not delete). The blunt caps (B–E) are enormous but
**dangerous**: they drop by rank, so 87 % of what they cut is permanent-category
(`decision`, `architecture`, `source_insight`, `methodology`), and a
legitimately dense analysis session would lose genuinely-durable memories. The
cap is the wrong *primary* lever — it confuses "too many" with "the last ones
are worthless," which is false for a real research-heavy day.

### Lever 1 (PRIMARY) — strengthen the prompt so Haiku extracts fewer, better

Make the cap prescriptive and give Haiku the value judgment (it has the
semantics; a post-hoc cap does not):

- *"Extract NO MORE THAN ~10 memories. If more seem worthy, rank by **durable,
  cross-session** value and keep only the most valuable; DROP the rest."*
- A sharper bar: *"A status update, a micro-decision, a one-off procedural pick,
  or a plan for later today is NOT worth persisting."*
- Sharpen `decision`: *"an explicit, durable choice with lasting rationale —
  NOT a plan, a task-management pick, or a one-off procedural choice."*
- Reinforce the existing self-correction rule.

This is the true *"fewer, higher-value at source"* lever — Haiku chooses which
~10 survive, by meaning. **Effect is not measurable without re-running Haiku
(API-gated)**; alternatively ship it and watch the P6 health report's volume +
confidence mix move over the next weeks (forward observation, no API).

### Lever 2 (SECONDARY, no-API) — confidence-aware **sidelining** (not deletion)

**Decided 2026-06-05: sideline, do not hard-delete.** Use the `confidence: low`
signal, but act on it *reversibly*. Earlier this section proposed a write-time
hard-drop ("don't persist `low` unless anchored / self-corrected"). Measuring
the bucket killed that idea — a write-time drop is a **one-way door** on a
noisy signal, and the carve-outs that were meant to make it safe barely fire:

- **The carve-outs are mostly inert.** Only **8 %** of `low` memories carry a
  usable anchor (so the anchor carve-out spares almost nothing), and the
  self-correction carve-out is **not implementable as written** — `superseded_by`
  is populated **0** times and no field marks "the deliberately-kept-low original
  of a correction" (`revisions` is the audit field, populated on 219 records of
  all confidences, not a self-correction flag). So "drop `low` minus carve-outs"
  was, in practice, "drop ~92 % of `low`".
- **The `low` bucket is not cleanly junk.** Of 4,238 `low` memories, **62 %
  (2,634) are permanent-category** (decision 1,099, gotcha 441, pattern 324,
  architecture 214, source_insight 105…), and **2,400 of those carry
  `why`/`how_to_apply`** guidance fields with 1,822 ≥ 250 chars. A structured
  guidance memory Haiku merely *hedged* to `low` is not obviously low-value, and
  we cannot cheaply separate valuable-`low` from junk-`low` at write time.
- **A delete is self-blinding** — once dropped we cannot audit whether the
  filter was right.

**The policy — sideline, fully reversible, reuses existing machinery:**

1. **Write `low` memories as normal** (nothing is lost at write time).
2. **Exclude `confidence = 'low'` from the `active_memories` view** (a one-line
   predicate, `AND confidence IS DISTINCT FROM 'low'`) → it stops surfacing in
   `/recall` and the session-start digest. This kills the costs that bite most
   immediately: recall noise and digest competition. (NB: this is a view change,
   so it carries a `schema_version` bump + the DDL in `schema.sql`.)
3. **To also reclaim JSONL size / embedding compute**, extend the archival
   criterion (`scripts/archive-memories.py` / `monthly-archive.py`) to treat
   `confidence = 'low'` as archival-eligible **independently of category decay**
   — the current sweep keys on the category decay window only, so a fresh
   permanent-category `low` record would otherwise stay in the hot JSONL (just
   hidden from recall). With that small addition the monthly sweep cold-stores
   sidelined `low`, still queryable via `fetch-memories.py --include-archive`.
   *If we only do step 2, recall/digest go quiet but the hot file keeps the
   hidden records — fine as a first cut; step 3 is the size win.*

Net: ~100 % of the hot-path benefit of a delete, ~0 % of the irreversibility.
If the `low`-filter ever proves too aggressive, the records are still there
(in-corpus after step 2, in cold store after step 3). Deterministic, no-API.

**Route to a true delete, if still wanted later (the one-way door, gated):**
run the filter in **log-only dry-run** for ~2–4 weeks — log what it *would*
delete to a side file, review a sample to confirm the false-positive rate is
acceptably low — *then* flip to deletion. Do not delete on the uncalibrated
self-report sight-unseen. Sidelining makes this optional rather than urgent.

**Caveat (carve-out, revised):** since the anchor carve-out only touches 8 %
and the self-correction carve-out is not yet implementable, the simplest first
cut sidelines **all** `confidence = 'low'`. If we want to *keep* anchored-`low`
in the active set (they are self-verifying), that is a one-line predicate
addition; the self-correction carve-out needs a real marker field added to the
prompt/schema first (separate, small piece of work — not a blocker).

### Lever 3 (BACKSTOP, no-API) — a HIGH per-session cap

A safety cap at, say, **30–40** to catch pathological runaway sessions (the
197/378 outliers) without touching normal dense sessions. **Not** a low cap —
B–E show a low cap destroys durable signal. This is a guardrail, not the volume
control.

## 4. Recommendation

1. **Lever 1 (prompt)** as the primary fix — the only lever that improves value
   *at source* rather than truncating after the fact.
2. **Lever 2 (confidence-aware *sidelining*)** — exclude `confidence = 'low'`
   from `active_memories`/recall/digest; the P2 sweep cold-stores it. Reversible,
   no-API, ~19 % off the hot path. **Not** a hard-delete (the bucket is 62 %
   permanent-category and the carve-outs barely fire — see Lever 2).
3. **Lever 3 (high backstop cap, ~30–40)** for runaway sessions only.
4. **Reject the blunt low cap (B–E).** Volume ≠ worthlessness-of-the-tail.

Combined expected effect: prompt does the heavy lifting (target ~10/session ⇒
roughly a 3–4× reduction if Haiku complies), sidelining + high cap catch what
slips through. Conservative, **reversible at every step**, and it keeps the
value judgment where the semantics are.

## 5. Validation plan

- **Lever 2 (sideline) + 3 (cap) — deterministic, no-API:** replay over the
  existing corpus (done — §3 table). On implementation, add unit tests for the
  view-predicate + cap logic. Sidelining is **reversible by construction** (the
  records stay in the corpus / cold store), so it needs no dry-run gate — a
  wrong filter is undone by reverting the predicate. The dry-run gate is
  reserved for the *optional later* true-delete (Lever 2's one-way door).
- **Lever 1 (prompt) — API-GATED.** Empirical validation = re-run extraction on
  a sample of ~10–20 recent transcripts with the revised prompt and compare
  volume + a manual value spot-check of kept-vs-dropped. This needs Haiku calls:
  **present model (Haiku 4.5), batch/real-time, call count, and est. cost for
  approval before running** (CLAUDE.md API gate). Cheaper alternative: ship the
  prompt change and watch the P6 health report forward (no API), accepting a
  slower feedback loop.

## 6. Open judgment calls for Shawn

1. ✅ **Confidence gate — RESOLVED 2026-06-05: sideline, not delete** (Lever 2).
   Sub-question still open: sideline **all** `low`, or keep anchored-`low` (8 %)
   in the active set? Default = sideline all (simplest); the anchored carve-out
   is a one-line add if wanted.
2. **The target number** in the prompt (~10?) and the **backstop cap** (~30–40?).
3. **Validation appetite (provisional lean: pay for an API spot-check):** re-run
   extraction on ~10–20 transcripts (old vs new prompt) — I present
   model/count/cost for approval first — or ship-and-observe via P6 (no API).
4. **Scope (provisional lean: do all three together):** prompt + sideline + cap
   in one change, or stage (the no-API sideline + cap first, prompt after).
   Note: doing the prompt and the sideline together means the P6 health report
   can't cleanly attribute the volume drop between them — the API spot-check
   (decision 3) is the clean attribution if that matters to you.

## 7. What was NOT done (the gate)

No edit to `hooks/extraction-hook.py`. No prompt change. No API calls. This is
read-only diagnosis + proposal. Implementation waits on sign-off; the prompt
validation waits on a separate API-cost approval.
