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
