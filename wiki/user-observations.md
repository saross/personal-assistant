---
title: "Personal-Assistant — User Observations"
tags: [index]
created: 2026-05-18
updated: 2026-05-18
status: seed
---

# Personal-Assistant — User Observations

Meta-level log about how Shawn and Claude work together on the
personal-assistant project. Each entry is a candidate observation drafted
at session-close (`/handoff` step 4), then accepted / edited / discarded /
replaced by Shawn. Empty is a valid outcome.

These feed eventually into `notes/working-with-claude.md` at curation
time (`/weekly-review`).

Format: dated entries; first line summary; body explains the context and
what generalises.

---

## 2026-05-18 — Drafted candidates (pending review)

The following four candidates were drafted at the 2026-05-18 `/handoff`.
Mark with ✓ (accept) / ✏ (edit, with revised text) / ✗ (discard) /
replace inline. Empty is fine — these are jog-the-memory drafts, not
load-bearing claims.

### Candidate 1: Pre-emptive structural clarification over implementation drift

When Claude started to drift into implementing the grimoire/wiki layout,
Shawn paused with *"we should discuss this and make a deliberate
decision"* and surfaced the cross-project-vs-PA-project structural
ambiguity that had been glossed. Saved a meaningful amount of rework.

**What this means in practice:** when there's a structural ambiguity in
a design, *name it before implementing*. Cheaper to clarify scope at the
question-mark than to refactor after the wrong abstraction is in place.

Applicable beyond PA project — generalisable working pattern.

[ ] accept   [ ] edit   [ ] discard

### Candidate 2: Explicit cost gates framed up front

For the bake-off, Shawn set a $5 cap up front and required explicit
approval before each batch run. The API-call review gate worked smoothly
in practice — small approvals, no surprises, kept spend at 29% of cap
across four iterations.

**What this means in practice:** cost gates work best when the cap is
stated *before* the work begins, not negotiated mid-stream. Per-batch
approval is low-friction when amounts are small enough that approval is
a 5-second yes/no.

[ ] accept   [ ] edit   [ ] discard

### Candidate 3: "Quick-and-dirty test" as effort framing

Before launching the Gemini-tuned bake-off round, Shawn said: *"this is
a quick-and-dirty test to see if we can move the needle, I want to see
results before we spend more time on refining prompts."* Explicit
framing of effort level and signal expectations protected against
over-engineering the first pass.

**What this means in practice:** for iterative work, naming the
*expected signal threshold* up front (move-the-needle vs converge-on-
final) calibrates Claude's effort. Saves the "I built it as if it were
production-final" failure mode on early iterations.

[ ] accept   [ ] edit   [ ] discard

### Candidate 4: AFK delegation with autonomy

Shawn delegated a high-judgment task ("review the Gemini output
carefully, consider what optimal looks like, tune the prompt, launch
one more round") with pre-approval for the API spend, then went AFK.
Trust-based work pattern; produced faster iteration than synchronous
gating, contingent on honest reporting back.

**What this means in practice:** Claude can run multi-step
judgment-heavy work autonomously when (a) the trust-base is established,
(b) the scope is clearly bounded, (c) cost approval is granted up front,
and (d) the report-back is comprehensive enough to support the
delegated judgment. This is a strong working pattern when both
parties understand the contract.

[ ] accept   [ ] edit   [ ] discard

---

## 2026-05-18 (follow-up session) — Drafted candidates (pending review)

Four candidates drafted at the second 2026-05-18 `/handoff` (the
small-follow-ups + v3-spot-check + F1+F2 wire-up session).

### Candidate 5: Verification-before-implementation as default

Mid-session, after I proposed a priority queue including both quick
spot-checks and the bigger F-arc, Shawn replied *"let's do the quick
spot check first"*. The v3 hook health check was cheap (one SQL query,
under a minute) and confirmed nothing was broken before committing to
the much larger F1+F2 swap. Had v3 been broken, F1 would have been the
wrong work; the cheap check de-risked the costly one.

**What this means in practice:** when offering a punch list that mixes
quick verifications with larger arcs, Shawn defaults to spot-checks
first. The pattern is *don't build on unverified state* — and the
spot-checks are small enough to be effectively free. Worth proposing
verifications proactively even when I think the state is fine; the
cost of asking is dominated by the cost of being wrong.

[ ] accept   [ ] edit   [ ] discard

### Candidate 6: API Call Review Gate operated as a live safeguard, not a nominal one

When laying out F-arc options, I offered "hold off backfill until live
SessionEnds confirm clean" as the recommended path versus "backfill
immediately after wire-up". Shawn picked hold-off. That gate was real:
without it, F1 would have rolled into a 307-session API call window
the same session, against zero live validation. The gate only fires
when I surface it as an explicit option — if I had bundled F1 + F3
into one window assuming approval, the safeguard would have been
silently bypassed.

**What this means in practice:** the CLAUDE.md "API Call Review Gate"
is a working safeguard Shawn uses actively. When chained API stages are
in scope, present each stage as a separate gate-able decision, not as
a single rollup approval. "Stage A approved" does not authorise stage
B. This generalises beyond cost — applies to any chain where each link
warrants independent approval.

[ ] accept   [ ] edit   [ ] discard

### Candidate 7: Continuity-first session warm-up beats memory-first

Session open: *"Let's Pick up where we left off — read planning/continuity.md first."*
That instruction is load-bearing. continuity.md was 540 lines of
current state across multiple workstreams; the recall dump (43 KB of
memories) would have been pure noise for context-warmup. Reading
continuity first gave me grounded priorities; the small follow-ups
were already named there as `[ ]` items waiting to be checked off.

**What this means in practice:** when Shawn says "pick up where we left
off", the right first move is *always* `Read planning/continuity.md`,
not /recall or a memory scan. Memory is candidate pool; continuity is
the surfacing layer (per the 2026-05-17 architectural decision). The
session-start payload already provides memory dumps automatically; my
job is to bring continuity into focus.

[ ] accept   [ ] edit   [ ] discard

### Candidate 8: Pause for design alignment when scope exceeds the briefing

When the F-arc started, the briefing said "wire Gemini Flex into
archive.py + switch the constant + backfill + QA pass" — four bullets.
The actual scope was bigger: prompt location, extractor location,
fallback policy, backfill timing — four design choices that branched
outcomes meaningfully. I paused with `AskUserQuestion` and surfaced
all four as side-by-side options with explicit recommendations. Shawn
took all four defaults; the work proceeded without backtracking.

**What this means in practice:** when the scope I'm about to plunge
into exceeds what the briefing names, pause to surface the design
choices BEFORE writing code. Especially with default-recommendations
shown — they make delegation a 30-second decision rather than a
mid-implementation derailment. Cheaper to clarify scope at the
question-mark than to refactor after the wrong abstraction is in
place. (This is a sibling to Candidate 1's pattern.)

[ ] accept   [ ] edit   [ ] discard
