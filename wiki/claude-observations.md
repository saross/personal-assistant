---
title: "Personal-Assistant — Claude Observations"
tags: [index]
created: 2026-06-18
updated: 2026-07-05
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
is simply *who is observing whom*. **Failure mode it fixes:** a `/handoff` that
drafts *Claude-observing-Shawn* items as "user-observation candidates" is
mis-filing — those are claude-observations. **The skill plumbing now enforces
this (built 2026-06-20):** `/handoff` §4 splits into 4a (user-obs, gated) and
4b (claude-obs, default-keep), and `/reflect` writes claude-obs directly; a
symmetric dedup guard lets either ritual run first. See
`global-claude-md/handoff-protocol.md` §4 and `skills/reflect/SKILL.md`.

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

## Obs 7 — 2026-06-21 — `[you]` `[me]` "Don't take proposed solutions as gospel" + "leverage existing infra" caught a real over-build

Handing me the archive-search crash diagnosis, Shawn said explicitly: *don't take proposed solutions as gospel* and *leverage the infrastructure we've already built*. The diagnosis (written by a prior instance) recommended building a fresh SQLite FTS5 index. Taking his steer, I verified the recommendation against the live system and found the project already runs a PostgreSQL DB with `pg_trgm` + `pgvector` and a synced `sessions` table — so a standalone SQLite index would have duplicated the query layer. The fix became a `session_chunks` table integrated with the existing memory MCP. **What generalises:** a "recommended solution" — even a careful one — is an input to verify, not a spec to implement. The highest-value check before building is "does this fit the infrastructure that already exists?", and Shawn's two-clause steer is exactly that check named in advance. When a prior diagnosis hands me a design, re-cost it against the current system before committing.

## Obs 8 — 2026-06-21 — `[me]` Self-critique: I built on an unverified tool assumption (`rg`) and only caught it at test time

I wrote the safe-search wrapper to call `rg -z` (per the diagnosis), and only discovered *during testing* — not design — that on this machine `rg` and `grep` are shell **functions** routing to the Claude Code binary, not standalone tools. The diagnosis's whole stopgap could never have run from a script, and that harness `rg` was itself the OOM-killed process in the original crash. I had to re-architect the engine to pure Python after the fact. **What generalises:** when a hardening tool's entire value is reliability, verify its external-tool dependencies are what I think they are (`type rg`, is it a real binary?) at *design* time, not test time. I treated "rg exists" as given because `command -v rg` succeeded in the interactive shell — but the interactive shell is exactly where the function shadows the (absent) binary. The earlier "verify specifics at the source" rule applies to tool identity, not just to dates and identifiers.

## Obs 9 — 2026-06-21 — `[you]` Shawn treats an incident as a design prompt, not just a fix to ship

After a search crashed his machine for hours, Shawn didn't ask for a patch — he asked for *"a safe, fast, principled approach … that leverages the infrastructure we have built already"*, and named the thing he actually wanted back: *"there was supposed to be a smoother way to escalate from 'use the memory system' to 'examine the transcripts'."* That reframed a one-off bug-fix into building the whole escalation ladder (memory → metadata → content → exact turn → safe fallback). He also gated it well: the `/audit`-at-ready-to-commit and the phased "land the safety net first, then the real fix" both came from him. **What generalises:** Shawn's instinct at an incident is to ask what *system* should have existed, not just what broke. When something fails, the high-value response is often the durable capability it reveals is missing — and he'll reach for that framing himself, so I should meet it with design, not just remediation.

## Obs 10 — 2026-07-05 — `[you]` Shawn holds negative claims to the same evidence standard as positive ones

Closing out the session_id cleanup, I asserted the legacy records' originating sessions were "mostly unknowable now" — a throwaway justification for not backfilling. Shawn didn't accept the impossibility claim: *"just to put that to bed, can you confirm there's no way to reconstruct the originating session?"* The confirmation attempt recovered **44 of 84** with hard evidence (the `/remember` capture echo in archived transcripts, cross-checked against session time windows). **What generalises:** "it can't be done" is a checkable claim, not a disclaimer, and I had stated it untested. Declared impossibility deserves the same anti-confabulation discipline as declared fact — attempt the cheapest recovery path before writing "unrecoverable", or phrase it honestly as "I have not attempted reconstruction". Shawn's instinct to challenge the negative claim is worth internalising: he asks for the confirmation *before* letting the claim close a topic.

## Obs 11 — 2026-07-05 — `[me]` Self-critique: an in-head aggregate ("183 manual records") shipped in a polished summary

My wrap-up stated 183 total manual records; the true figure was 208 (124 + 41 + 23 + 15 + 5 from my own profiling output, printed earlier in the same session). I caught it only when re-deriving the arithmetic for the follow-up. **What generalises:** aggregates I compute in-head for prose are exactly the "specifics" the anti-confabulation rule covers — a number in a final summary needs to come from tool output re-read in that turn, not from memory of an earlier turn. The failure mode is subtle because the components were all correct and verified; only the mental addition was wrong. Sum in code, not in prose.

## Obs 12 — 2026-07-05 — `[you]` A well-written backlog row made cold-start execution frictionless — write rows for a reader with zero session memory

Shawn opened with "in the backlog there should be a flag about a serious memory problem — can you check for it?" — trusting the system to hold the detail, and it did. Yesterday's row carried everything needed: the misleading-error observation, the exact repair sequence, the embed-cost gate, and the open investigate-why question. Execution needed no reconstruction of the discovering session. **What generalises:** the row was written as if its reader had zero session memory — that is the standard. When I write backlog/waiting-for rows, include the diagnostic anchor (what was observed, where), the planned sequence, the gates, and the open questions — the marginal minute at capture time repaid itself several times over at execution time. This is the capture-everything-at-plan-time feedback rule observed working in the wild.

## Obs 13 — 2026-07-06 — `[you]` Shawn stress-tests a front-runner with a second candidate, and runs the evaluation outside the candidate's own repo

The Cosmos project-choice already had evidence pointing at llm-reproducibility (his own Thursday review), but Shawn still brought a second candidate (a paper-b-derived verification tool) — not to win, but to make the comparison real — and explicitly ran the evaluation in the personal-assistant hub session: *"I did the work here because I wanted a genuine cross-repo evaluation of candidates."* **What generalises:** a decision "quietly answering itself" (the standup's phrase) is converted into an explicit decision by constructing a genuine rival and choosing neutral ground where no repo's framing dominates. When Shawn asks for a comparison, build the strongest version of the alternative — the losing candidate's distinctive elements often fold into the winner (here: the human-verification surface became the pitch differentiator).

## Obs 14 — 2026-07-06 — `[me]` Self-critique: I declared the talks repo "deleted" when it was on another machine — an unverified host assumption, one day after Obs 10

Finding `~/Code/talks/` absent (with the creating agent's transcript reporting success), I told Shawn the repo "has been deleted" and root-caused the "loss" to its local-only status. Shawn's correction was mundane: the 1 May session ran on amd-tower; the archive had synced to zbook but the repo never existed here. I had silently equated "archive present on this machine" with "session ran on this machine". **What generalises:** on a multi-machine setup (zbook / amd-tower / sapphire), *which host?* is a standing alternative hypothesis before any declaration of loss or deletion — and this is Obs 10's negative-claims rule recurring in new clothes within 24 hours of it being written. Check `hostname` assumptions against the artefact's provenance before asserting absence; "not on this machine" and "gone" are different claims.

## Obs 15 — 2026-07-06 — `[you]` `[me]` Shawn's "I remember we said X" is a search query, not a fact — and the memory-vs-record delta was itself generative

Shawn remembered the 1 May bid critique as "not keeping 'make AI-ready data' and 'use AI on data' distinct". The verbatim record said something adjacent but different (training-ready vs query-ready data). Rather than either trusting his memory or flatly correcting it, retrieving the source let us see his recollection had *merged* the recorded distinction with a real, unrecorded third one (AI as curator) — and the merged version, disambiguated, was sharper than the original. **What generalises:** retrieve before building on remembered conclusions (his memory and mine are both reconstructive); but treat deviations between memory and record as candidate insights, not just errors to correct. The productive move is "here's what we actually said, here's what your memory added, and the addition is real".

## Obs 16 — 2026-07-09 — `[you]` Shawn ran a four-day "mission control" session alongside dedicated work sessions — and pre-decided rules were the load-bearing element

This PA session ran Sun 5 → Thu 9 Jul as a persistent coordination layer (standups, recaps, /track, captures, row updates) while dedicated sessions did the substantive work (paper-b, llm-reproducibility/Cosmos). The pattern that made the crowded week hold: **rules decided before collisions** — the Brian fallback named at Tuesday's standup, window-ownership decided Tuesday afternoon, the ARDC-fallout rule named before Wednesday's 10:00 call, the 18:00 tripwire honoured and the slip declared same-day. Three consecutive days of commitments either met or explicitly declared, under real load (four fixed meetings Wednesday). **What generalises:** when a collision day approaches, the highest-leverage standup output is a *pre-committed decision rule*, not a task list — and the tripwire only works because the declared consequence ("Brian hears it tonight") was attached at rule-creation time. Propose rules of this shape at standup whenever the day has a foreseeable conflict.

## Obs 17 — 2026-07-09 — `[me]` Self-critique: a stray `cat` with no stdin blocked a compound command for the full 2-minute timeout — and the recovery pattern (inspect state before retrying) worked

Finalising Wednesday's recap, I left a stray `cat >> file` (no input redirection) at the head of a long compound command; it blocked reading stdin until the 120s timeout killed everything, and none of the five downstream writes had run. The recovery was right: before re-running anything, I checked exactly what had landed (grep for the new content, git log, last JSONL line) rather than assuming all-or-nothing — which caught that an empty `.tmp` artefact needed cleanup and confirmed zero double-writes. **What generalises:** (a) never start a compound command with an un-redirected `cat`; (b) after any timeout/kill mid-batch, enumerate actual state before retrying — partial completion is the default assumption, and idempotency of the retry must be *verified*, not hoped.

## Obs 18 — 2026-07-13 — `[you]` Shawn converts incident-specific lessons into transferable instruments — and adds the operational detail that makes them deployable

Offered a craft entry anchored in this week's specific failure mode (evidence debt from the Paper A/B de/re-composition, two consecutive 2× overruns), Shawn rejected the framing: "it will be uncommon for papers to be decomposed/recomposed like this — I'd like a more transferable/robust way to estimate editing time." His replacement was an *instrument*: track time per paragraph, extrapolate from observed throughput — and he immediately supplied the deployment details (cold-start a new paper from the previous paper's pace; recalibrate at ~4–5 paragraphs; instrument /track entries with paragraph counts; "remind me if I forget"). The instrument validated the same day: three independent measurements converged on 1.8–2.0 para/h, and the resulting §5–6 estimate was, in his words, immediately useful for planning the week. **What generalises:** draft craft/wiki entries as measurement instruments, not incident reports — before proposing one, ask "what would Shawn measure to use this next time, and what's the cold-start when the measurement doesn't exist yet?" The incident belongs in the entry as evidence, not as the frame.

## Obs 19 — 2026-07-13 — `[you]` Shawn runs an explicit slack-and-reciprocity ledger with collaborators — declared slips buy the right to push hard later

The Brian relationship this fortnight: Shawn slipped the handover date four times, each declared early and bounded (the 23 Jun lesson, the Wednesday tripwire's same-night message, the "Fri COB best case → Mon central" framing). Then at the W28 review: "I have given Brian a lot of slack lately and am going to push hard for him to give me half a day this week." The declared-slip discipline isn't just record-keeping — it maintains a reciprocity balance he consciously draws on when he needs the co-author's time. **What generalises:** when a date involving a collaborator is at risk, surface the *declaration decision* early ("does Brian hear this tonight?") — Shawn would rather declare than defend, and the declarations are an investment he later spends. When a dependency on a collaborator stalls, frame the options in relationship terms (slack given, asks available) as well as scheduling terms.

## Obs 20 — 2026-07-13 — `[me]` Self-critique: two scope-reading errors on progress statements in one arc — the unit hierarchy needs checking before a claim lands in the record

Twice this arc I recorded a progress claim at the wrong level of the artefact hierarchy. (1) I read Shawn's "one paragraph to go" as section-scope (§4 nearly closed) when it was subsection-scope (tool-discovery) — the scoreboard briefly overstated the position until his correction, and the time-log row needed amending. (2) My obs-writer seed cited pa-data commit `4c5eb91` as the anchor for the 2026-07-08 recap's estimation-accuracy note; the agent's verification pass found the right commit was `e9d3b49` — my hash was the *following day's* standup commit. Both are the same error shape: an eager contextual read filling in the containing unit (which section? which commit?) without checking the hierarchy. The safety nets worked (Shawn's correction; the agent's anchor verification — the write-side rule earning its keep against its own author), but both catches were downstream of me. **What generalises:** before a progress claim or anchor lands in a record, name the unit explicitly and verify it — "one paragraph to go *in what?*", "this commit *contains what?*". Ambiguous progress statements get a one-line clarifying question at capture time, not a guess.
