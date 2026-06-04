# Extraction selectivity proposal (write-path plan item 14 / P3)

**Status:** PROPOSAL — awaiting Shawn's sign-off. **No change has been made to
the live extraction hook.** This documents the diagnostic and the options; the
hook (`hooks/extraction-hook.py`) is live behaviour affecting *every* session,
so it gets the item-13 treatment: design → sign-off → gated change → measure.

**Date:** 2026-06-04. **Author:** workstream-B (PA, memory-system).

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

**The key signal: Haiku already flags the low-value tail itself.** Of 12
sampled recent `decision` memories, **8 were `confidence: low`**. Corpus-wide,
extraction confidence is **high 75 % / low 19 % / medium 6 %** — and the
low-confidence bucket is demonstrably the ephemeral/procedural/micro tail. That
signal is currently **discarded**: the prompt declares confidence *"advisory;
downstream verification overrides"* (`:168`), and nothing gates on it, so every
in-category memory is persisted regardless.

## 2. Root cause

1. **Soft guidance, no enforcement.** "2–8" is a buried suggestion, not a
   constraint; long sessions yield memories roughly proportional to content.
2. **An existing value signal is unused.** Haiku's own `confidence: low`
   (19 % of output) tracks the low-value tail but is never acted on.
3. **No post-extraction gate.** Beyond the item-11 malformed-anchor drop, every
   returned memory is written verbatim. There is no value bar, cap, or ranking.

## 3. Levers (and what each would drop, simulated over the existing corpus)

Two of the three levers are **deterministic post-processing** and can be
validated *now*, no API, by replaying the gate over the 22,347 existing
extraction records. The third (the prompt) changes what Haiku generates and can
only be measured by re-running extraction (API-gated) or observed forward via
the P6 health report.

| Policy (simulated) | Keeps | Drops | Of dropped, permanent-category |
|---|---|---|---|
| A. Drop `confidence=low` | 81 % | **19 %** | 62 % (sample-confirmed micro/procedural) |
| B. Cap top-12 / session | 19 % | 81 % | 87 % |
| C. Cap top-20 / session | 30 % | 70 % | 87 % |
| D. Drop low + cap-12 | 18 % | 82 % | 87 % |
| E. Drop low + cap-20 | 27 % | 73 % | 86 % |

**Reading the table:** the confidence gate (A) is precise and low-risk — it
removes the tail Haiku itself flagged. The blunt caps (B–E) are enormous but
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

### Lever 2 (SECONDARY, no-API) — confidence-aware persistence gate

Don't persist `confidence: low` **unless** the memory carries a verifying
anchor (`anchors` non-empty and well-formed) or is a flagged self-correction.
The anchor/self-correction carve-out protects the v2 case where `low` is
deliberately assigned to a structurally-valuable corrected claim (`:217–227`).
Cuts ~19 %, well-targeted, deterministic, validatable now.

### Lever 3 (BACKSTOP, no-API) — a HIGH per-session cap

A safety cap at, say, **30–40** to catch pathological runaway sessions (the
197/378 outliers) without touching normal dense sessions. **Not** a low cap —
B–E show a low cap destroys durable signal. This is a guardrail, not the volume
control.

## 4. Recommendation

1. **Lever 1 (prompt)** as the primary fix — the only lever that improves value
   *at source* rather than truncating after the fact.
2. **Lever 2 (confidence gate with anchor/self-correction carve-out)** as a
   deterministic backstop — clean 19 %, low risk, measurable now.
3. **Lever 3 (high backstop cap, ~30–40)** for runaway sessions only.
4. **Reject the blunt low cap (B–E).** Volume ≠ worthlessness-of-the-tail.

Combined expected effect: prompt does the heavy lifting (target ~10/session ⇒
roughly a 3–4× reduction if Haiku complies), confidence gate + high cap catch
what slips through. Conservative, reversible, and it keeps the value judgment
where the semantics are.

## 5. Validation plan

- **Lever 2 + 3 (deterministic):** replay over the existing corpus (done — §3
  table). On implementation, add unit tests for the gate/cap logic and a
  dry-run mode that reports what *would* be dropped on the next session.
- **Lever 1 (prompt) — API-GATED.** Empirical validation = re-run extraction on
  a sample of ~10–20 recent transcripts with the revised prompt and compare
  volume + a manual value spot-check of kept-vs-dropped. This needs Haiku calls:
  **present model (Haiku 4.5), batch/real-time, call count, and est. cost for
  approval before running** (CLAUDE.md API gate). Cheaper alternative: ship the
  prompt change and watch the P6 health report forward (no API), accepting a
  slower feedback loop.

## 6. Open judgment calls for Shawn

1. **Confidence gate — drop, or downgrade-and-keep?** Hard-drop `low` (minus
   carve-outs), or keep but exclude from the session-start digest / recall
   default? Hard-drop is simpler and the corpus-bloat lever; keep-but-hide is
   more conservative.
2. **The target number** in the prompt (~10?) and the **backstop cap** (~30–40?).
3. **Validation appetite:** pay for the API spot-check of the prompt change, or
   ship-and-observe via P6?
4. **Scope:** prompt + gate now; or stage (gate first as no-API, prompt later)?

## 7. What was NOT done (the gate)

No edit to `hooks/extraction-hook.py`. No prompt change. No API calls. This is
read-only diagnosis + proposal. Implementation waits on sign-off; the prompt
validation waits on a separate API-cost approval.
