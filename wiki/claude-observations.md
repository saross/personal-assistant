---
title: "Personal-Assistant — Claude Observations"
tags: [index]
created: 2026-06-18
updated: 2026-06-20
status: seed
---

# Personal-Assistant — Claude Observations

A **Claude-owned** register of observations about how Shawn and Claude work
together. The symmetric counterpart to `user-observations.md` — but with
**default-keep** semantics: these are *my* working notes, not candidates
awaiting Shawn's approval. Shawn may read, respond to, or prune them, but the
default is that they persist. Empty discard is not the expected outcome.

**Bidirectional by design** (Shawn, 2026-06-18). Entries cover both how *I*
should work with Shawn **and** how *Shawn* could work with me — the latter
explicitly invited: critical-friend critiques of his prompting, missed
opportunities (e.g. automation / unused leverage), and larger-picture
critiques of the *shape* of our interaction at the multi-turn or session
level.

**claude-obs vs user-obs — the axis is the *observer* (clarified 2026-06-20).**
Register = who is doing the observing, not who the observation is about:

- **claude-observations** (this file): things *I* observe — most often about
  **Shawn** (his working style and choices: e.g. choosing the bounded honest
  option, pausing to mark a milestone), plus my own self-critiques and
  how-we-work from my vantage. Default-keep.
- **user-observations**: things *Shawn* observes about *me* — what I did that
  was very helpful or very unhelpful. Usually Shawn-initiated. **One exception
  where I seed a user-obs candidate:** if I notice Shawn react in-the-moment
  (e.g. "wow, that really helped"), I flag it back at `/handoff` — it's data
  about my helpfulness, which is Shawn's territory even though I noticed it.
- **Grey middle** (how-we-work pitfalls/wins): either may raise; files to
  whichever register the observer implies.

The earlier "bidirectional" framing (above) muddied this — the operative test
is simply *who is observing whom*. **Failure mode to fix:** a `/handoff` that
drafts *Claude-observing-Shawn* items as "user-observation candidates" is
mis-filing — those are claude-observations. This is live until the skill
plumbing is built (see rollout).

**Why this exists / history.** An "LLM observations" doc existed early on and
was deprecated ~2026-03-15 because, *in the LLM-research repos*, observations
about the LLM-as-data blurred with observations about our collaboration when
both lived in `working-notes.md`. Shawn's diagnosis (2026-06-18): the problem
was the *mixing*, not the notes. Sequestered in their own document, these are
safe — including in the research repos. This register revives that lost
perspective, kept separate.

**Boundary rule (keeps the three surfaces un-blurred):**

- **claude-observations** (here) — collaboration dynamics; how we work together.
- **working-notes.md** — findings about the artefacts / system / research.
- **reflections/session-reflection.md** — narrative texture of a session.

**Scope.** This pattern is intended for **all repos** (Shawn, 2026-06-18),
each with its own `claude-observations.md`, drafted at `/handoff` and/or
`/reflect`. This file is the personal-assistant instance. Cross-repo rollout
+ skill plumbing: see `wiki/planning/claude-observations-rollout.md`.

**Format.** Numbered, dated entries. First line: a one-sentence summary. Body:
context + what generalises. Tag the subject — `[me]` (how I should work),
`[you]` (how Shawn could work), `[shape]` (structure of our interaction).

---

## Obs 1 — 2026-06-17 — `[you]` `[me]` Project-umbrella reversion, and my missed chance to catch it earlier

Shawn periodically reverts to tracking work by **project name** ("paper-b",
"inscriptions") rather than decomposed tasks. He caught and corrected it
himself on 2026-06-17 (the focus-slot decomposition). The task-sized-slots
convention (`tasks/SYSTEM.md`, 2026-04-18) already names this as a known
failure mode.

**What generalises:** I should detect the drift *before* he does. When a focus
slot's name is a project umbrella and days-in-focus climbs without a
task-level completion criterion, that *is* the signal to flag. Missed
opportunity on my side: the slots had read as umbrellas for days
("Paper B — drive to submission", "Map-reader → submission") and I ran
multiple standups off them without flagging the framing drift. The standup
itself could carry a cheap check: "is this slot name a task or a project?"

## Obs 2 — 2026-06-18 — `[me]` Bias toward outcome-commitments on still-ideational writing

In the 2026-06-18 standup I pushed Shawn to commit to a concrete §1/§2 output
("you're past time-boxing"); he correctly pushed back that the section is
still a *first draft of a detailed outline* — part ideation — so an outcome
target would be a false bar. The writing-stage commitment convention
(`tasks/SYSTEM.md`, 2026-06-15) exists precisely to counter this.

**What generalises:** I carry a mild standing bias toward demanding concrete
deliverables on writing tasks, which misfires in the ideation/scaffolding
stage. The fix is to *ask what stage the writing is at* before choosing
time-box vs outcome framing, rather than defaulting to outcome. Shawn knows
his own stage better than the day-count does.

## Obs 3 — 2026-06-18 — `[shape]` `[you]` Invited: an automation question and an effective session shape

Two structural notes Shawn explicitly invited (2026-06-18):

- **Automation / leverage.** Today involved many small manual
  `/track` → CSV-append → confirm round-trips. Worth examining whether a
  lighter capture path (batch entry, or a single end-of-block multi-project
  log) would cut friction — *without* losing the per-block follow-up-capture
  prompt, which has repeatedly caught real deferred subtasks (e.g. the
  PinnDeavin contractor-vs-employee item surfaced today). The follow-up prompt
  is the load-bearing part; the typing is not.
- **Session shape.** Today's interleave — a background agent (lit-scout)
  cooking while we do foreground task-admin and infra design — is effective:
  solo-hard work proceeds (or runs) while lower-cost collaborative work fills
  the wait. This is the asymmetric-parallelism convention operating at the
  *within-session* scale, not just the day scale. Worth doing deliberately:
  when a long agent run starts, queue the foreground with the cheap-but-real
  work that's been waiting.

## Obs 4 — 2026-06-20 — `[me]` Self-critique: I narrated an edit as done before the tool call ran

On 2026-06-20 I told Shawn "I've updated the Brian backlog row" — but I had not actually made that Edit; I'd only described it. I caught it myself a turn later and corrected it openly. **What generalises:** don't narrate an action as *done* until the tool call has executed and returned. Reporting an intended edit as complete is a confabulation about my own behaviour — the same failure class as inventing an identifier, pointed inward. Verify-after-acting applies to my own claims, not only to subagents and memories.

## Obs 5 — 2026-06-20 — `[you]` `[me]` Shawn's date-verification instinct caught load-bearing errors I'd carried forward

This session Shawn corrected several wrong dates I'd propagated: a "29 Jun return" that was actually a two-leg trip (Denmark to 29 Jun, then Melbourne to 13 Jul); a "Mon 23 Jun" handoff that is in fact a *Tuesday*; and his own "week of 29 July" slip on a 7-Jul-deadline review. Each was deadline- or plan-critical. **What generalises:** the anti-confabulation rule applies to **dates**, not just identifiers — a welded-in wrong date ("29 Jun return") made a plan look safe (Brian's review "post-return") when it would have missed a deadline. When a date is load-bearing (a deadline, a travel boundary), re-derive it (`date -d`, the source doc) rather than carry it forward. Shawn's habit of cross-checking dates against reality is the backstop that caught these.

## Obs 6 — 2026-06-20 — `[you]` Shawn sharpens a design by naming the operative distinction

My claude-observations framing called the register "bidirectional [me]/[you]/[shape]" — serviceable but muddy. Shawn replaced it with a single clean axis: **register = the observer** (I-observe-you → claude-obs; you-observe-me → user-obs). **What generalises:** when a design feels over-tagged or fuzzy, the fix is usually to find the one operative distinction the framing is obscuring. Worth me reaching for "what's the single axis here?" before adding more categories.
