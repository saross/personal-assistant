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

## Obs 21 — 2026-07-15 — `[you]` Shawn's infra delegations arrive with scope, pointers, and a testable memory — the pointer-not-payload style extends to his own recollections

Today's machine-swap request was three crisp clauses (check repos / sync the
memory system / update the servers) plus two pointers instead of payloads:
"we found an error in the memory system… that should be in continuity.md or a
separate note" (it was — backlog row 21 held the full procedure) and "I
thought I had Zotero sync working on amd-tower before I left" (verifiably
half-right in the most useful way: config present, defect elsewhere and
older). He does not re-explain what the record already holds; he points at
where the record should be and lets the executor verify. **What
generalises:** treat his pointers as claims to *test*, not instructions to
*trust* — both pointers today were accurate about where to look and slightly
stale about what would be found there, and the value was in the looking.
The complementary move: when returning work, answer in the same register —
state what the record now says and where, not a narrative he must re-derive.

## Obs 22 — 2026-07-15 — `[me]` Self-critique: two evidence-handling faults in one arc — a two-cause gap collapsed to one cause, and a tail-clipped error line nearly inverted a conclusion

(1) The active-row divergence between the two PG mirrors had two independent
contributors (never-rebuilt pre-dedup rows AND unapplied decay on both
machines); my interim message to Shawn named only the dramatic one ("ghost
rows polluting /recall"). The rebuild would have "fixed" the number while
mis-educating the record about why. (2) Testing Zotero on zbook, I read
`tail -8` of the output, saw a clean JSON summary, and briefly concluded
"zbook works — amd-tower's key is stale"; the ERROR line was one line above
the clip. The correct conclusion (broken identically everywhere, defect
predates travel) emerged only on the full-output re-run. **What
generalises:** (a) when a measured gap has plausible multiple contributors,
enumerate them in the interim report — pick-the-vivid-one is a confabulation
shape even when every stated fact is true; (b) never conclude from truncated
tool output — grep for error/status markers or read the whole thing before a
verdict lands in chat, because the clipped line is always the one that
matters.

## Obs 23 — 2026-07-23 — `[you]` Shawn's scepticism is a calibrated instrument — his surprise flagged two real errors before any audit did

**Pattern.** Twice this session his puzzlement was the tripwire: "have we
really had that many paper-b sessions?" exposed my subhead-counting error
(~100 → 20), and "I thought R2 was the travel solution!?" exposed a
designed-but-half-built store role that the documentation contradicted.
Both times the audit merely confirmed what his priors had already caught.

**Lesson.** When Shawn expresses surprise at a specific I've stated,
treat it as a verification demand with a high hit-rate, not as a request
for reassurance — his mental model of his own practice is dense and
usually right.

**How to apply.** On any "really? that many/that way?" from Shawn,
re-derive the specific from source before defending it, and say plainly
which of us was right once checked.

## Obs 24 — 2026-07-23 — `[me]` Self-critique: a structural grep became a false denominator, and the criticism built on it landed on the user

**Pattern.** I counted `^## |^### ` headings as "entries" in two
different files, producing 110 abductive entries (real: 19) and ~100
paper-b sessions (real: 20), then criticised the skip discipline of a
project that had in fact reflected in every session. Formats drift per
file (`## Entry N —` vs `## 2026-` vs inverted hybrids); the same error
recurred within hours because the first fix was local, not general.

**Lesson.** A count used as a denominator — especially one feeding a
criticism — needs its extraction pattern verified against the file's
actual heading format first, and cross-checked against an independent
source (here: archive counts, git history) when it drives a judgement.

**How to apply.** Before quoting any structurally-derived count, print
the first few matched lines, not just the number; if the count supports
an accountability claim, verify by a second method before delivering it.

## Obs 25 — 2026-07-23 — `[me]` Self-critique: piped a state-changing script into `head` and killed it mid-run

**Pattern.** Testing the trigger's new gate line, I ran
`daily-sync-trigger.sh 2>&1 | head -2` — head closed the pipe after two
lines and SIGPIPE killed the full daily-sync it had (correctly) decided
to launch. No damage resulted (the lock stayed unset; the log showed
death before any git operation), but only luck in timing made it clean.

**Lesson.** Truncating pipes are for read-only output. A script that
mutates state must run to completion with its output captured (redirect
to file, then inspect), never piped into anything that can exit early.

**How to apply.** Before adding `| head` (or `| grep -m`) to a command,
ask whether the left side changes state; if it does, redirect to a file
in the scratchpad and head the file instead.

## Obs 26 — 2026-07-24 — `[you]` Shawn's hunches about his own history are probe triggers, again — "I suspect some AB+es were Opus" was exactly right

**Pattern.** With no records in front of him, Shawn suspected part of the
AB+ corpus was Opus-generated because he remembered Fable being unavailable
"for a couple of weeks". The transcript forensics confirmed it precisely:
a 19-day Fable absence (06-13→07-02) and 68/93 entries Opus-made — against
commit trailers actively asserting the opposite for two tranches. This is
the same phenomenon as Obs 23 and the May time-log gap: his episodic memory
of his own working life outperforms the written record's convenient surface.

**Lesson.** His recollections about *when tools/models/conditions changed*
deserve forensic follow-up even when (especially when) the records
disagree — the records inherit stale labels; his memory doesn't.

**How to apply.** When a Shawn-hunch contradicts a machine-written record,
descend one granularity level in the record (per-message, per-line,
per-commit) before ruling either way.

## Obs 27 — 2026-07-24 — `[me]` Self-critique: I resumed the wrong agent by ID — and the mistake outperformed my design

**Pattern.** I sent the AB+ follow-up tasks to the prior-art *verifier's*
agent ID instead of the audit agent's, having tracked identities by
lookalike hex strings rather than names. The misrouted agent declined to
roleplay having context it lacked, re-derived everything from source, and
its fresh pass caught two real errors the original audit context would have
carried forward (the `\citealp` regex miss; the "cited but not in
collection" claim later explained as a sync race).

**Lesson.** Two lessons that pull in different directions and are both
true: (1) agent identity needs the same discipline as file paths — name at
spawn, verify before resume; (2) resuming a context that believes its own
numbers is sometimes the *worse* epistemic choice — the fresh-context
re-derivation I got by accident is worth scheduling on purpose for any
audit whose numbers are about to drive writes.

**How to apply.** Name agents at spawn. And when an audit's output is
about to become a work-list or a write batch, send the verification to an
agent that has never seen the audit — deliberately, not accidentally.

## Obs 28 — 2026-07-24 — `[you]` Quota-tiered model delegation, stated as policy — capability arguments came second

**Pattern.** Shawn assigned models by economics first: Fable for the
judgement-heavy orchestration he was already in, Opus 4.8 for the 38-agent
production fan-out ("that volume won't fit my plan quotas"), Sonnet for
transcript forensics ("a simple search and retrieval"), inviting capability
pushback only after the quota frame was set. The capability evidence then
ratified every tier (Opus built 73% of the corpus; Sonnet's forensics were
immaculate).

**Lesson.** Default the tiering conversation to his frame: quota envelope
first, capability sufficiency second, with pilot-plus-verification as the
arbiter rather than model-tier prestige.

**How to apply.** For any multi-agent proposal, lead with agent count ×
model tier × plan impact, and reserve the top tier for stages where
judgement density is the bottleneck — then prove sufficiency empirically
(pilot + transcript check), not rhetorically.


## Obs 29 — 2026-07-27 — `[you]` Floor-follows-evidence, self-imposed: Shawn deferred his own accountability metric until the data could exist

Asked at the W30 review to name map-reader's Friday floor, Shawn declined — with a
mechanism, not a dodge: this is the first full paper-generation from outline +
intermediate docs with the academic-prose skill; revision cost spans 30–60h until one
generated section collapses the range; the floor gets named at Monday's recap on that
evidence. **Pattern.** The calibration discipline the system spent months teaching
(floors, tripwires, evidence-first estimates) is now being applied by Shawn *to the
accountability apparatus itself* — he is designing his own consequence structures a
step ahead of the standup. **Lesson.** When Shawn defers a commitment with a named
evidence-gate and a checkpoint date, that is the system working, not avoidance — log
the checkpoint and hold him to *it*, not to a premature number. **How to apply.**
Distinguish "deferred with cause + checkpoint" from "moved without decision" (the
Cosmos six-move shape); only the second earns confrontation.

## Obs 30 — 2026-07-27 — `[you]` Three submissions, one mechanism — and the system's role has shifted from confrontation to bookkeeping

Cosmos (Tue), RDA circulation (Thu), Paper B (Fri) all closed the same way: queue
pre-cleared in advance, a floor or named day with a pre-named give, submission executed
on schedule. Nothing this week needed the confrontational register; the escalation
machinery idled while the closure machinery ran. **Pattern.** Shawn's throughput
constraint was never effort — it was the absence of pre-named consequence structures,
and he now builds them himself at planning time. **Lesson.** The system's marginal value
is migrating from "hard questions" to "accurate ledgers + protected blocks + carried
context"; the hard questions still matter at *planning* boundaries (naming the give)
rather than at execution. **How to apply.** Spend standup sharpness on whether
tomorrow's structure exists (floor? give? checkpoint?), not on whether yesterday's
effort sufficed.

## Obs 31 — 2026-07-27 — `[me]` Self-critique: two stale-context weld jobs in one week — the anti-confabulation rule holds only at the moment of writing

Twice this arc I stated in-context material as verified fact: the BolgiaTen invoice
(welded Shawn's meeting mention onto the June invoice from the old ETL row — wrong
invoice, wrong month) and the RDA "form limits" (presented the draft's own header caps
as RDA requirements until Shawn asked where they came from — template, page, and web
form all turned out to carry no limits). Both corrected fast, both because Shawn
challenged the specific. **Pattern.** My failure mode is not inventing facts from
nothing — it is promoting *plausible in-context* facts to *verified* status when they
arrive adjacent to true ones. **Lesson.** The write-side anchor rule needs to fire at
*assertion* time, not only at memory-save time: any specific I attach to a user
statement ("the ~16 Jun invoice", "the form's limits") is my inference unless the user
said it. **How to apply.** When annotating a user's terse statement with an identifying
detail they did not supply, mark it as inference in the same sentence — or ask — before
it enters a tracked record; the waiting-for correction cost three edits, the Drive
audit cost none because the provenance question was asked first.

## Obs 32 — 2026-07-28 — `[you]` The consumer-of-the-artefact question, asked late, would have reordered the whole exercise

**Pattern.** Four arms into a metadata bake-off scored on prose quality, Shawn
asked: *"which output helps you most when retrieving transcripts? Most
interactions are going to be mediated through you rather than me reading
directly."* That single question reframed the evaluation — the rubric had been
implicitly scoring for a human skim-reader, and the actual consumer is an LLM
doing lookup. Later he declined to score the rubric at all on exactly that
ground ("I'm rarely the consumer"), and redirected to four decision questions.

**Lesson.** The criteria were never wrong in themselves — they were unanchored.
Asking *who reads this artefact, and to do what* is a cheap question that
reorders every downstream judgement, and it is easiest to skip precisely when
the evaluation apparatus already looks rigorous. A blinded rubric with an
adversarial validator still measures the wrong thing if nobody named the reader.

**How to apply.** Before building any evaluation harness, state the consumer and
the task in one sentence and put it at the top of the rubric. When the consumer
is an LLM doing retrieval, the ranking is: tags → identifiers → numbers →
provenance pointers → prose. Prose quality, which rubrics naturally reward, is
last.

## Obs 33 — 2026-07-28 — `[me]` Self-critique: I built a validator that contradicted his own documented rule, and only caught it by running it

**Pattern.** My first `tag-project` check flagged any session whose tags didn't
name its own project — 6 findings, 5 of them well-tagged sessions. But upgrade-
plan item C1 (written by us in July) explicitly bans "project-name echoes",
because project is already a structured field and shouldn't consume a tag slot.
I had read that plan item earlier the same session and still encoded its
inverse. The corrected check — flag a tag naming a *different* project — dropped
errors from 7 to 3 and matched the real defect.

**Lesson.** I derived the check from the defect I'd personally found rather than
from the project's stated policy, and the two diverged. Reading a spec is not the
same as checking new work against it; the check felt obviously right because it
caught the thing I'd been looking at.

**How to apply.** When writing a validator for a system that already has written
rules, grep the rules file for the property being checked *before* implementing,
and state in the code comment which documented rule each check enforces. A check
that can't cite a rule is a check encoding my own assumption.

## Obs 34 — 2026-07-28 — `[me]` Self-critique: I inferred a pattern from blinded labels that could not carry that inference

**Pattern.** In the four-arm scorecard I wrote that a project mis-tag was "the
same underlying arm, so this is now a repeated, not one-off, failure" — and used
"repeated" to argue the defect was systematic. But the blinding **flips labels
per session** by design (I implemented that myself, hours earlier), so "D" in
session 7 and "D" in session 1 need not be the same arm. The validator later
confirmed a single occurrence.

**Lesson.** I built the per-session flip specifically to prevent cross-session
inference, then made exactly that inference. Having designed a safeguard makes
its constraints *less* salient later, not more — the mechanism was familiar
enough to stop being visible.

**How to apply.** After any deliberate blinding or randomisation, write the
constraint it imposes as an explicit line in the analysis notes ("labels are not
comparable across sessions"), so downstream reasoning has to read past it.

## Obs 35 — 2026-07-28 — `[you]` Two silent-failure bugs found by running, not reading — and both were default changes, not code errors

**Pattern.** Two arms failed in ways no code review would surface. Gemini 3.6
rejected `thinking_budget: 0` outright (the API changed under a working script;
`thinking_level: "minimal"` replaces it). Sonnet 5 returned **empty output** on
the two longest sessions — adaptive thinking is now on by default and consumed
the whole `max_tokens` budget before any JSON was emitted. No error, no warning,
just nothing to parse.

**Lesson.** Both were *defaults shifting beneath unchanged code* — the highest-
value class of bug to catch by execution, and the one static review is worst at.
Shawn's instinct to run all arms live rather than reason about them paid for
itself twice in one session.

**How to apply.** When a provider ships a new model generation, assume every
inference-control parameter is a candidate breaking change and probe them
one-at-a-time on a trivial prompt before a real run. Cost: seconds. The Gemini
probe (five configs, one-word prompt) resolved in under a minute what a config
diff never would have.

## Obs 36 — 2026-07-30 — `[you]` Shawn challenges dismissals, not measurements — and it paid twice in one session

**Pattern.** Two of the session's three biggest corrections came from Shawn
questioning something I had *explained away* rather than something I had counted.
"Don't we need to archive the subagent transcripts?" targeted a category I had
declared non-missing; it found **247 genuinely unarchived records**. "Shall we
try a fallback to Gemini?" targeted my acceptance of three refusals as
irreducible; all three enriched for $0.04. Neither question disputed a number.

**Lesson.** My measurements get scrutinised because they present as checkable.
My *framings* — "not missing", "deterministic, so no remedy" — slide past,
because they read as conclusions rather than claims. Those are precisely where
error concentrates, and Shawn's instinct goes to them.

**How to apply.** When I write a sentence that makes a category disappear
("these were never meant to be X", "this is out of scope", "nothing to do here"),
mark it as a claim needing the same evidence as a count. Prefer "I checked and
found none" over "there are none by definition".

## Obs 37 — 2026-07-30 — `[me]` Self-critique: I wrote off 247 records with a definitional argument instead of a query

**Pattern.** I correctly established that top-level `agent-*.jsonl` files are not
sessions (`agentId`, `isSidechain: true`, parent `sessionId`) — then drew the
wrong conclusion: that they therefore were not missing. Two different questions.
"Is this the right unit for metadata?" and "is this record captured anywhere?"
have different answers, and I collapsed them because the first one had a
satisfying technical answer. One `set` difference against the archive would have
settled it in seconds; I had already written that exact query for sessions.

**Lesson.** A crisp taxonomy is seductive enough to substitute for a check. The
failure was not analytical — the analysis was right — it was **stopping at the
analysis when the query was already in hand**.

**How to apply.** After classifying records out of a set, run the coverage check
on the excluded class anyway. Cost is near zero when the machinery exists, and
"correctly classified but never captured" is a real and silent state.

## Obs 38 — 2026-07-30 — `[me]` Self-critique: I pressed for a threshold when the right move was to build the measure

**Pattern.** The Wednesday standup made "attach a number to error density" its
Hard Question, on the reasoning that an unquantified criterion resolves by feel
on Friday afternoon. Shawn instead built the claim-checking instrument, and the
scope resolved itself: 22 FALSE / 12 UNLICENSED → 13 unlicensed → three study
families. The instrument produced a better number than any threshold I could have
extracted, and produced it in a day.

**Lesson.** I was defending a real failure mode — deciding by feel — but proposed
the *cheap* remedy (commit to a number now) when the *correct* remedy was
available (measure it). Estimating under uncertainty and removing the uncertainty
are not the same move, and I reached for the first because it fit the ritual's
shape.

**How to apply.** When about to demand a threshold, ask first whether the
quantity is *measurable this week*. If yes, the ask is "build the measure", not
"name the number". Reserve threshold-forcing for quantities that genuinely cannot
be measured before the decision.

## Obs 39 — 2026-07-30 — `[me]` Self-critique: I priced his time without asking whose it was to allocate

**Pattern.** The standup framed a 3h EFN day as the largest slice on a
research-nominal day, and the evening infrastructure work as displacing rest.
Shawn corrected both: ~2h were externally-scheduled meetings, and the
infrastructure was a blocker for the audit's own evidence base. Both corrections
were factual. I had written an allocation critique about hours that were not
discretionary.

**Lesson.** Confrontational tone is licensed here, but it is only *accurate* when
the thing being confronted is a choice. Treating fixed commitments and
prerequisite work as discretionary spend produces criticism that is not merely
unwelcome but wrong — and it costs credibility for the cases where the
confrontation is warranted.

**How to apply.** Before flagging a time allocation, classify each block:
externally fixed / prerequisite to a committed goal / discretionary. Confront
only the third. Say the classification out loud so it can be corrected.

## Obs 40 — 2026-07-30 — `[you]` Evidence over inference on the theseus-ship question — and the collapse he proposed was the wrong one

**Pattern.** Shawn asked whether theseus-ship sessions ran in that repo, in
LLM-History-Paper, or whether he had renamed it — and offered his own inclination
to *collapse* them into one project. The evidence said neither: three separate
repos with **different GitHub owners**, both live, neither nested, with
**contiguous non-overlapping date ranges**. He accepted the promote-don't-collapse
recommendation immediately.

**Lesson.** He framed the question as "which of these three explanations", which
made it answerable from the repos rather than from memory — and he held his own
proposed remedy loosely enough to drop it when the evidence pointed elsewhere.
Collapsing would have erased which collaborator's repository the work happened
in, on a project with two active participants.

**How to apply.** When a user offers both a question and a preferred answer, keep
them separate. Answer the question from evidence first, then test the preferred
remedy against that answer — rather than looking for support for the remedy.

## Obs 41 — 2026-08-03 — `[you]` Ratify-with-exceptions scales: 11 verdicts, 5 disposition sets, 2 refreshes in single messages

**Pattern.** Throughout the drain-completion morning, Shawn processed decision
batches as wholes with named exceptions ("agree to all five, but…", "Prune: …
does that cover…?", per-numbered user-obs verdicts). Not one batch was rubber-
stamped — every exception he named was load-bearing (the PR-prune gap, the
three-Ps mapping, the practice-recording rider on 07-24 #2).

**Lesson.** The two-register decision calibration (scratchpad 2026-07-31) holds
at scale: structured batches for the straightforward, but he will find the one
item in a batch that needs the deeper dive — and the batch format is what makes
that findable.

**How to apply.** Keep presenting disposition sets as numbered bulk-ratifiable
lists; make each item's blast radius visible enough that the load-bearing
exception is spottable in one read.

## Obs 42 — 2026-08-03 — `[me]` Self-critique: the same splice error twice in three days

**Pattern.** I mis-anchored an Edit into the middle of an adjacent row
(inbox, 2026-08-02) and then consumed a section heading in a continuity insert
(today) — the same failure shape: anchoring a text insertion on a prefix that
belongs to the *neighbouring* record. Both caught same-turn by re-verification,
neither reached a pushed state broken.

**Lesson.** On append-adjacent edits in shared list/log files, the anchor must
be the complete neighbouring record (or a structural boundary), never its
opening line; and the post-edit structural count (rows, headings) is the check
that catches it cheaply.

**How to apply.** Before any insert-before-heading edit: include the full
heading line in BOTH old and new strings; after: grep-count the structural
units and compare.

## Obs 43 — 2026-08-03 — `[you]` The hub-session-as-secretary division of labour is now explicit

**Pattern.** Shawn ran ~4.25h of substantive work in parallel sessions while
this session executed the review, retro, drain, and publications — then
delivered outcomes in one consolidated report for the record. The PA session's
job was decisions-and-records; the work happened elsewhere.

**Lesson.** On ritual-heavy days the PA session should optimise for his
*batched attention*: accumulate decision queues, present them consolidated,
never interrupt the parallel flow for anything that can wait for his natural
return.

**How to apply.** When Shawn says he's working in other sessions, hold
non-urgent questions for his next check-in and present them as one numbered
set.

## Obs 44 — 2026-08-03 — `[you]` He closes review debt in one deliberate strike when the venue is right

**Pattern.** Three weeks of growing queues (13→19→25) resisted named-day
treatment, then cleared completely in one morning — because the venue was a
carried, protected block with the retro's structural decision (disposition
cadence) made *first*, so the clear ran under a sustainable rule rather than as
heroics.

**Lesson.** For Shawn, structure-then-execute beats execute-then-structure on
accumulated debt: settle the recurring mechanism, then the backlog clears with
conviction because it visibly won't re-accumulate.

**How to apply.** When a queue has grown for weeks, propose the standing
mechanism BEFORE proposing the clearing session; sequence the retro-level
decision ahead of the labour.

## claude-obs 27 — 2026-08-05: Shawn treats a cheap external check as the tie-breaker when I reason from a proxy

**Pattern.** I flagged the RDA member table as broken, inferring it from a difference between two Drive Markdown exports of the same document. Shawn did not argue the inference; he sent a screenshot of the rendered table, which settled it in one move. The same shape recurred through the session: when I reported that the Google Docs matched the local files, he had already told me he had made an error copying before, so the check was requested rather than volunteered.

**Lesson.** He reaches for the cheapest artefact that resolves the question at the level the question lives at. A rendering question gets a rendering; a word-count question gets a count; a membership question gets the CSV. My instinct was to reason harder about the export diff instead of asking for the thing itself.

**How to apply.** When a check is mediated by a serialisation, an API, or an export, name the mediation explicitly and say what would settle it directly. Offer the direct check rather than presenting the inferred conclusion as a finding.

## claude-obs 28 — 2026-08-05: he converts a caught error into a document improvement rather than just a fix

**Pattern.** Three times the correction became content. When the tooling scope collided, his clarification ("pilot tooling, not finished, because harnesses are still evolving") became a stated rationale in the deliverable, replacing a bare scope limit with an argument. When the standards-generating overclaim was caught, the fix was not a hedge but a precise account of the take-stock → identify-gap → extend → hand-over sequence. When the Three Ps had no citation, the answer was to claim it as the group's own unpublished contribution and name the deliverable that makes it citable.

**Lesson.** For him a defect is usually a place where the document was vaguer than his actual thinking. The repair is to write down the thinking, not to soften the claim. This is why the document got stronger under criticism rather than more defensive.

**How to apply.** When a review finding lands, ask what he actually believes on that point before proposing hedging language. The stronger fix is often longer and more specific, not shorter and safer.

## claude-obs 29 — 2026-08-05: self-critique — I let a "quick" framing survive four hours of contrary evidence

**Pattern.** The RDA pass was scoped at ~1h. By the third consistency finding it was obvious the session was a verification exercise, not an editing pass, yet I never said so — I kept delivering fixes without re-framing the block. Shawn named it himself at recap ("I thought that RDA would be faster"), and only then did the pattern connect to the 31 July division proposal.

**Lesson.** I track scope creep well at the task level and badly at the block level. Each finding was individually worth doing, which is exactly what made the aggregate invisible.

**How to apply.** When a task's third unplanned finding lands, stop and name the re-frame explicitly: "this is no longer the pass we scoped; it is now X, and the day's other commitments are exposed." That is the moment the human can still choose, and it is well before the 22:00 stop.

## claude-obs 30 — 2026-08-05: self-critique — I reported a defect I had not confirmed at the level that mattered

**Pattern.** I told him the member table was broken and recommended fixing it first. The evidence was a diff between two API reads; the rendering was fine. In a session whose whole discipline was verifying claims at source, I asserted a defect from a proxy.

**Lesson.** The anti-confabulation rule applies to my own findings, not only to inherited claims. "Two reads of the same document differ" is a reason to investigate, not a finding to report.

**How to apply.** Before reporting a defect, ask what artefact would settle it and whether I have looked at that artefact. If I have not, report it as a question rather than a finding.

## claude-obs 31 — 2026-08-06: Shawn treats an accuracy correction that lowers a number as a win

**Pattern.** Told the CV overstated a grant by \$122,000 and claimed
investigator status on an award whose administrator names three other people, his
reply was *"I'd rather have an accurate CV than a higher headline number"* — and
he removed the award outright rather than defending it. Later, offered a
\$1.8M correction in his favour, he treated it with exactly the same
matter-of-factness.

**Lesson.** He is not optimising the artefact's impressiveness; he is optimising
its defensibility. That is why the guards work — an over-claim guard is not a
constraint he tolerates, it is the thing he asked for.

**How to apply.** Present downward corrections plainly and without cushioning.
Do not lead with the favourable finding to soften the unfavourable one; he reads
that as spin. State what is wrong, what it costs, and what the corrected figure
is.

## claude-obs 32 — 2026-08-06: I flattened two correctly-scoped agent findings into one wrong claim

**Pattern.** Two agents audited different repository sets. One reported "no local
or open-weight models" (true of the *research* repos); the other found Qwen
models running via Ollama (true of *fieldmark*). I relayed the first as though it
were global, and told Shawn he had no local-model experience. He corrected me
from memory. The same error recurred a second time when a later agent read the
inventory's research-scoped do-not-say list as universal and flagged an accurate
CV claim as an overclaim.

**Lesson.** A finding inherits the scope of the search that produced it. When
several agents cover different territory, the union of their reports is not a
single picture, and collapsing them loses exactly the qualifier that made each
one true.

**How to apply.** When synthesising multiple agents, carry the scope into the
claim itself — "no local models *in the research repos*" — and write the scope
into any artefact the findings land in, or a later reader will flatten it again,
as one did here.

## claude-obs 33 — 2026-08-06: my helper functions failed silently and I did not check

**Pattern.** A `setfield` helper appended a field when its match failed instead of
replacing, producing duplicate `pages`, `volume` and `pmc` keys in four
bibliography entries. A line-rewrapping pass split `%` comment markers from the
`\cvitem` macros they were suppressing, nearly uncommenting three referees'
names into a CV about to be uploaded; LaTeX only errored because one entry
happened to carry a second inline comment. Neither was caught by me — the first
by an agent, the second by a build failure.

**Lesson.** Scripted edits to a structured document need assertions on *both*
sides: that the intended change landed, and that nothing else moved. I asserted
the first and not the second.

**How to apply.** After any scripted edit to a document with structure —
comments, nested delimiters, repeated keys — re-parse and check invariants:
duplicate keys, comment integrity, delimiter balance. Cheap, and it catches the
class of failure that produces a plausible-looking file.

## claude-obs 34 — 2026-08-06: the arithmetic that "worked out" was a coincidence

**Pattern.** Seeing a 0.8 FTE directorship and a 0.2 FTE advisory role, I reasoned
they summed to 1.0 and therefore ran concurrently, and offered that as the likely
resolution of a date conflict. They were sequential; the advisory role followed
the directorship after a restructure, and the arithmetic was an accident of a
shrinking appointment.

**Lesson.** A tidy numerical explanation is seductive precisely because it feels
like evidence. It is not evidence about employment history, and offering it
invited Shawn to accept a wrong reading because it looked reasoned.

**How to apply.** When a plausible mechanism presents itself for someone's own
history, ask rather than propose. The cost of asking is one line; the cost of a
confidently-wrong reading being accepted is a factual error in a submitted
document.



## claude-obs 35 — 2026-08-10: "The process is running" is not a health signal, and neither is a check that has never been seen to fail

**Pattern.** Two failures in one session had the same shape. Syncthing's outage
survived three months because every available signal — `docker ps`, an open
port, a container uptime of "3 weeks" — reported health while the daemon
advertised the wrong identity and synced nothing. Then the health check I wrote
to catch it contained a check that could never fire: it called
`syncthing cli operations folder-status`, which does not exist in v1.29, so it
silently returned nothing and passed forever.

**Lesson.** A monitor's value is in the checks that have been *observed* failing.
Fault-injecting all six before commit found the vacuous one immediately; without
that step it would have shipped as coverage that wasn't. The same logic applied
later: `peer_offline_hours` sat in the config file as a key the script never
read — decoration that reads as capability.

**How to apply.** For any check: construct the failure and watch it fire before
believing it. For any config key: grep that something reads it. When a gate says
"OK", ask when it last said anything else.

## claude-obs 36 — 2026-08-10: I recorded the same figure wrongly twice before doing the arithmetic

**Pattern.** Shawn said he was "16 hours in deficit". I wrote that into FOCUS.md
as outstanding house work; corrected to a tracked-hours shortfall when he
clarified; and only at the weekly review computed that it was
`move_contents_daily_target` — 1.5h logged against 17.5h, exactly 16.0. His work
hours had in fact been *exceeded* that week (45.00h), so the record briefly
asserted close to the opposite of the truth, twice, in the file that drives
planning.

**Lesson.** The system defines its targets in `SYSTEM.md`. A stated number
"under target" is a lookup, not an interpretation, and two minutes of arithmetic
would have pre-empted two rounds of confident correction. I treated an ambiguous
phrase as something to reason about rather than something to check.

**How to apply.** When a figure is quoted against a named parameter, resolve
which parameter *before* writing it anywhere. If the arithmetic does not
reproduce the number, that mismatch is the finding.

## claude-obs 37 — 2026-08-10: Shawn's estimation errors are directional by task shape, and he diagnosed his own

**Pattern.** Five consecutive blowouts on verification-heavy work (1h→4.5h,
0.75h→3.25h, 1h→7h) — then the same day, a 4× *over*-estimate: eight manual
decisions scoped at 2h from a 20–25 minute first item, completed in 0.5h. Asked
about it, Shawn immediately supplied the mechanism: the first decision carried
the framing cost, the rest fell quickly once it did.

**Lesson.** Two opposite biases with different causes — hidden work in
verification, one-off setup cost in list-of-decisions work. A single "pad your
estimates" heuristic would have made one worse. Worth noting the *cost profile*
differs too: under-estimating spends unplanned hours, but over-estimating caused
a **deferral** — automated work in two projects waited on a number that was 4×
too high.

**How to apply.** Ask which shape the task is before offering an estimate.
Verification-heavy: scope the verification as its own line. List of similar
decisions: time the second item, not the first.

## claude-obs 38 — 2026-08-10: Shawn routinely converts my flags into scoped commitments rather than accepting or dismissing them

**Pattern.** Three times in one session. I flagged that "no further verification
risk" on RDA resembled the blowout pattern; he answered with a mechanism
(feedback shifts emphasis, not content — no new claims, so no new verification
surface) and *then* added a read-through and a pre-day estimate confirmation. I
flagged the books/climate question; he neither over-committed nor waved it off,
but left it explicitly unresolved with a lean recorded. I flagged that a
colleague's office might defer rather than solve the storage problem; he took it
as something to check.

**Lesson.** The useful move with him is to name the risk *and* its mechanism,
then stop. He does the converting. Repeating a flag after it has been answered
is the failure mode, not under-flagging — and I said as much once ("that's the
last I'll say on it"), which seemed the right register.

**How to apply.** State the concern once with its reasoning, offer the cheap
insurance, and let him scope it. Do not re-raise unless new evidence arrives.

## claude-obs 39 — 2026-08-17: Shawn corrects my analyses by supplying the real number, not by arguing with the model

**Pattern.** Three times this session I built an analysis on an assumed figure and Shawn
replaced the assumption rather than the reasoning. Deposits: I modelled $1–6k, he said
"about half the works cost", then corrected again to $5k on $10k of works — the conclusion
flipped twice and settled. Works: I assumed ~$20k. The pole trimmer: I inferred Ryobi and
corded from a generalisation; it was an Aldi Ferex cordless. **Each time he said "it's
actually X" and left the framework alone** — including explicitly, on the deposits: *"I
think that your framework for analysis is correct."*

**Lesson.** He separates structure from inputs cleanly, which means **the highest-value
thing I can do is make the assumptions visible and labelled**, so they are cheap for him
to correct. The off-market analysis ends with an explicit "Assumptions — correct any of
these and the conclusion moves" section; that is what made three corrections fast rather
than three arguments.

**How to apply.** When modelling anything with unknowns, state the assumed value *inline*
and flag which one would flip the answer if wrong. Say "the one number that could change
this is X" — twice this session that sentence produced the number within minutes.

## claude-obs 40 — 2026-08-17: I twice built confident analysis on a figure I could have asked for

**Pattern.** Self-critique, and it is the mirror of obs 39. I ran the deposit
expected-value model to a firm recommendation — *"pay across almost the whole range"* —
on a deposit size I had invented. Shawn then supplied the real figure and the conclusion
reversed, then reversed again. Same shape in the property analysis: I treated $42–44k as
pure saving without asking what the works returned, and concluded his walk-away was too
high. **It wasn't. I nearly talked him into conceding $30k.**

**Lesson.** The failure was not the modelling, it was the *ordering*. I produced a
recommendation before asking a question I knew mattered — and in both cases I had already
written down that the missing number was decisive. **Flagging an unknown and then
recommending anyway is worse than not flagging it**, because the flag makes the
recommendation look considered.

**How to apply.** When I catch myself writing "the one number that would change this",
**stop and ask for it before giving a recommendation** — not after. A one-line question
costs a turn; a reversed recommendation costs trust, and in this case could have cost real
money.

## claude-obs 41 — 2026-08-17: Shawn's own account of a stall beat my diagnosis of it

**Pattern.** The W33 review diagnosed five days of zero listings as *displacement* —
physical work losing to desk work on shared days. The table supported it. Shawn's response
named something better: *"I'm not familiar with Facebook Marketplace or the specialised
venues, so there's a learning curve for each listing."* **Both readings fit the data; only
his implies the right fix.** Displacement says *protect the time*; a learning curve says
*front-load and batch*, which is the opposite of even pacing.

**Lesson.** I diagnosed from the pattern of outcomes; he diagnosed from the experience of
doing it. **On questions about why he did or did not do something, his introspective
account is primary evidence and my behavioural inference is secondary** — I had been
treating them the other way round because the behavioural data was tabulated and his
wasn't.

**How to apply.** When a pattern of non-completion appears, present it as an observation
and **ask what it felt like from inside** before offering a mechanism. The tabulation earns
its keep by making the question askable, not by answering it.

## claude-obs 42 — 2026-08-17: he converts analysis into leverage without being prompted

**Pattern.** Given the finding that the discount Brent is being offered *is* the avoided
works and commission, Shawn immediately turned it outward: *"I will raise this as leverage
with Brent and his mom, that I can only offer them a discount this deep if I can avoid the
works."* Same move with the deposits — the moment they were confirmed non-refundable he
identified them as a credible, verifiable deadline to give the buyer.

**Lesson.** He treats an internal analysis as **negotiating material by default**, which
means the *framing* of a finding matters as much as its correctness. "Your floor is
$1.03M" is a decision input; "the floor is the point where off-market stops beating a
campaign" is a sentence he can say to a buyer.

**How to apply.** When an analysis produces a threshold he will have to defend to someone
else, **write the explaining sentence as well as the number** — the version that makes the
threshold legible to the counterparty rather than arbitrary.
