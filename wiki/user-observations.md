---
title: "Personal-Assistant — User Observations"
tags: [index]
created: 2026-05-18
updated: 2026-07-05
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


### Candidate 9: Lead with the decision + the why when Shawn asks "should we …?"

Twice today Shawn opened a major-decision question ("should we
consolidate first?", "should we de-track LFS now or wait?") and twice
I led with a direct recommendation, three reasons, and a recommended
sequence. Both times Shawn replied "agree" and we moved straight to
execution.

**What this means in practice:** when the question is decisional, the
response should be (decision, why, what-to-do-next). Asking "what
would you like to do?" with no scaffolding wastes the cognitive
moment when both of us have the context loaded. Pattern is consistent
with Candidate 1 (pre-emptive structural clarification) and
Candidate 8 (pause for design alignment when scope exceeds the
briefing) — all three say: when a decision is approaching, do the
decision-prep work openly rather than punting to Shawn.

[ ] accept   [ ] edit   [ ] discard

### Candidate 10: Check for a one-line user-side reframe before elaborating an objection

When I cited the "rpi-server toolkit install overhead" as a Phase 0
friction, Shawn answered in one sentence: "we can mount that storage
on this machine, we don't have to install the entire apparatus."
That single reframe dissolved the entire objection cluster and
unlocked a cleaner architecture. The reframe was available to me too
— but I'd elaborated the objection before checking.

**What this means in practice:** when my analysis surfaces an
objection of the form "we'd need to install / set up / coordinate X
on machine Y", pause to ask whether the constraint is real before
treating it as a design driver. One short check ("is X actually a
hard requirement, or could we mount / proxy / wrap instead?") beats a
long elaboration of a non-problem. Shawn's one-line reframes are
load-bearing input — probe for them earlier.

[ ] accept   [ ] edit   [ ] discard

### Candidate 11: Verification of agent findings worked as designed today

The audit produced 6 subagent reports with ~50+ specific findings
(file:line, claim, impact). Before consolidating into a single report,
I re-verified the highest-impact findings directly: `archive.py:368`
`response.text` None crash, `extraction-hook:962-967` cursor advance
on API failure, `anchor_verify` zero-anchors → "true",
`analyse_caps.py` framing-strip omission. One subagent claim was
**downgraded from Critical to Low after verification** (Hook C1:
`parse_transcript` dict-content crash — theoretical, not observed in
real transcripts).

**What this means in practice:** the discipline of "trust but verify"
worked as designed — the consolidated report had no confabulated
findings reaching Shawn. The cost of verification (re-read the cited
file:line, run the mental trace) is small relative to the cost of a
false-positive Critical finding reaching the user. Keep doing this,
especially with multiple parallel agents whose outputs cannot
cross-check each other.

[ ] accept   [ ] edit   [ ] discard

### Candidate 12: Small-batches-each-verified is sustainable for high-tempo days

~25 commits across three repos today (toolkit 5, pa-data 4, PA 16)
with zero test-suite regressions. The pattern was: agent does work
→ run tests → if green, commit and push → next batch. The full
toolkit suite ran ~12 times today (226/226 throughout); the PA suite
ran ~4 times (690 → 699 with 9 net new tests).

**What this means in practice:** no "fix everything and run tests at
the end" antipattern emerged. Today's commit messages are
individually tight, the history reads cleanly, and reverting any
single change is straightforward. The cadence sustained across both
directly-authored work and two parallel background agents. Pattern is
robust for high-tempo days when the alternative (batched bulk
changes) would have lost legibility and made bisecting harder.

[ ] accept   [ ] edit   [ ] discard


### Candidate 13: Pushback on misframed external deadlines is fast and decisive

Wed-morning standup framed the Adela handoff as "midday Thursday hard
deadline". Shawn corrected within a turn: "synopsis today (= her Fri
morning Aarhus), full text tomorrow". Pattern: when I anchor a
deadline to a confident-sounding but wrong frame, Shawn doesn't
negotiate or qualify — he restates the correct frame and moves on.

Means I should hold deadline claims more lightly when they're
inferred from secondary sources, and surface uncertainty rather
than confidently overdetermine.

[ ] accept   [ ] edit   [ ] discard

### Candidate 14: Meta-questions about session shape improve workflow design

Mid-task ("we should take extra care with agent definition, and then
save the agent"), Shawn raised: "Should we undertake this task in a
new session?". The question split spawn-now from review-later, kept
the current session focused on Adela's talk, and made the agent
definition a durable artefact rather than a one-off prompt.

Useful pattern: Shawn periodically reframes the workflow itself, not
just the work. I should expect these meta-reframes and welcome them
— they usually improve the design rather than just the output.

[ ] accept   [ ] edit   [ ] discard

### Candidate 15: Empirical verification as a hard requirement, not a nice-to-have

When building the style-guide agent, Shawn specified "build in some
verification / checking suggested style guide inclusions back against
the corpus" *before* I'd surfaced verification design. This wasn't a
refinement of my proposal — it was a core requirement he reached for
unprompted.

Pattern: for any empirical-construction work, default to
verification-as-structural-feature, not as a quality-check phase. He
will insist on it; build it in from the start rather than retrofitting
it after a "first pass" that the user has to reject.

[ ] accept   [ ] edit   [ ] discard

### Candidate 16: "Later, as comparison" methodological framing transfers

The decision to read the existing style guides *after* the corpus
pass (not before) was endorsed crisply by Shawn — "see later as
comparison". The frame transfers: independent reconstruction first,
then diff against prior framing.

Useful for any task where the goal is "do better than the prior
version" rather than "elaborate the prior version". Default to
walling off the prior version during construction; pull it in for
diff and reconciliation after.

[ ] accept   [ ] edit   [ ] discard

---

## 2026-05-22 (evening) — Drafted candidates (reviewed at handoff)

Four candidates drafted at the 2026-05-22 evening `/handoff` (the
data-profile-iterate smoke test + documentation_defect calibration
session). Shawn reviewed inline: candidates 1, 2, and 4 discarded;
candidate 3 accepted. Recording only the accepted entry below for
the paper trail; the discarded drafts are visible in the session
transcript if needed.

### Candidate 17: Implement calibration recommendations at the analytical moment, not as a deferred action

After the data-profile-iterate smoke test produced a post-run note
that recommended two spec edits (a `documentation_defect` status
on the verifier side; tighter `source_method` discipline on the
proposer side), Shawn replied *"please implement both of your
recommended edits"* immediately — rather than treating the
recommendation as a candidate for a later session. This worked
well: the calibration insight was still fully loaded in context,
the spec edits were small and the right size for immediate action,
and the implicit test for whether the recommendation was concrete
enough to implement was "can I actually do it now without further
conversation?" — which it was.

Heuristic: calibration recommendations made at the analytical
moment should default to immediate implementation, not be deferred
to "next session". Deferring usually means the context evaporates;
the recommendation arrives in a future session as a one-liner
without the surrounding judgement that made it concrete. When
proposing a calibration edit alongside an analytical finding,
default to also offering to implement it in the same turn unless
the user signals otherwise (e.g. "let's sleep on it" or "park as
a candidate"). Spec-level edits in particular benefit from the
context still being warm.

[x] accept   [ ] edit   [ ] discard

---

## 2026-05-22 (late evening) — Drafted candidates (reviewed at handoff)

Four candidates drafted at the 2026-05-22 late-evening `/handoff` (the
style-guide-workstream session: comparator pass against
`Hiro-Inagawa/write-like-me` + prior-art rescan + v2 implementation
plan + 10 design decisions). All four accepted inline by Shawn.

### Candidate 18: Evaluate-before-adopt is Shawn's strong default

At every decision point this session, Shawn extended the evaluation
chain rather than accepting an earlier verdict and moving to
implementation: desk eval → end-to-end test → comparison report →
re-scan → plan. When the desk eval returned "compose, do not fork",
Shawn explicitly pushed back ("before we reconcile … I'd like to freeze
them as a potential comparison for outputs from write-like-me. I think
we should evaluate and potentially test write-like-me"). The pushback
was productive — the end-to-end test surfaced three real failure modes
(citation pollution, silent textstat break, baseline em-dash conflict)
that materially refined the compose-with-minimised-scope verdict.

Heuristic: when I produce a verdict from a read-only pass, default to
offering an end-to-end empirical test as the next step rather than
treating the verdict as terminal.

[x] accept   [ ] edit   [ ] discard

### Candidate 19: Re-verify negative findings before committing implementation effort

Shawn explicitly requested the prior-art rescan even though the original
verdict ("no prior art with the attestation schema") was clear. His
phrasing: "Can you send an agent to re-scan the 7 failed github repos
please?" — naming a concrete gap rather than asking generally for
"another look". The rescan caught `ngpepin/stylometric-transfer`, the
most technically complete tool found across both passes — a
licence-blocked find that didn't change the verdict but materially
shaped the v2 plan (the fingerprint schema and deviation-report
architecture became design inspiration).

Pattern: when a negative finding is about to drive a commitment of
implementation effort, pay the cost of one verification pass before
committing. Heuristic for me: when reporting a negative finding from a
search with acknowledged gaps, surface the gaps prominently and offer
the verification pass rather than packaging the result as final.

[x] accept   [ ] edit   [ ] discard

### Candidate 20: Compact-decision interfaces scale to design-question batches

The `AskUserQuestion`-with-recommended-defaults format closed all 10 v2
design questions in three batches with zero follow-up clarifications and
zero defaults overridden. The "recommended default first + brief
description + one or two concrete alternatives" structure let Shawn
either ratify by checking the recommended box or push back specifically.
Notable: Shawn accepted all 10 recommendations, but the format made the
alternatives visible enough that a real disagreement would have
surfaced.

Pattern works because the recommendations were grounded in concrete
trade-offs (per-paper granularity vs aggregate-only; LIWC commercial vs
free) rather than aesthetic preference. Heuristic for me: for
design-question batches, prefer recommended-default-first format over
open-ended "what do you want?" — it surfaces disagreements more cheaply
than aesthetic-preference questions.

[x] accept   [ ] edit   [ ] discard

### Candidate 21: Proactive licence-awareness matched Shawn's stance without prompting

When the prior-art rescan surfaced `ngpepin/stylometric-transfer`'s
PolyForm Noncommercial 1.0.0 licence, I flagged it proactively as a
concern given Shawn's commercial-Fieldmark context, before asking what
to do. Shawn confirmed directly ("inspiration only ... I can't
guarantee I'd never use this in a commercial context"). The principle
then carried forward through the rest of the session: LIWC-2007
commercial dictionary rejected for the same reason; write-like-me's
MIT code re-implemented rather than vendored (because MIT attribution
overhead wasn't worth ~30 lines per metric).

Pattern: Shawn treats licence-friction-with-commercial-use as a hard
constraint, not a soft preference. Heuristic for me: when surfacing a
tool/library/dependency, scan for non-permissive licences and flag them
at first mention, with the trade-off framed against Shawn's
commercial-Fieldmark context.

[x] accept   [ ] edit   [ ] discard

### Candidate 22: PM-mode steering — short, high-leverage corrections rather than design debate

The agent-orchestration upskilling session ran on Shawn driving at
milestone boundaries (cost discipline deferred; rename for symmetry;
smoke-test before next pair; calibration findings folded forward) while
I implemented between them. Pushbacks were typically one or two
sentences — not extended dialogue, just specific corrections. Examples:
"let's put #4 on the back burner for now (but /remember it)";
"agent pair called 'data-profile-proposer' / 'data-profile-verifier'"
(reframing rename request); "we can stop here". The session closed
three closed-loop pairs in one arc without any extended design debate.

Pattern: Shawn explicitly articulated this as "PM rather than
pair-programmer" mode in the opening message. He reserves attention
for the high-leverage steering moments and trusts implementation to be
roughly right between them. Heuristic for me: in PM-mode sessions,
keep implementation moving without volunteering uncertainty unless the
choice is load-bearing; surface design questions only when the trade-off
is real and the user's call materially changes downstream work. The
short-pushback cadence is the signal that the mode is working — if I
start getting longer corrections, the implementation is drifting.

[x] accept   [ ] edit   [ ] discard

### Candidate 23: Cross-session smoke-test → spec-edit loop as a deliberate workflow

Shawn ran the `/lit-scout-iterate` smoke test in a fresh session, brought
the results back to this session as a structured post-run note (per the
test prompt I'd drafted earlier), and the findings drove two concrete
spec edits: the `failure_type` axis added to `prior-art-scout-verifier`,
and the BibTeX correction-propagation gap captured as a deferred item.
The pattern repeated twice across the session — first with the
data-profile smoke test (which surfaced `documentation_defect`), then
with lit-scout. The test prompts I'd drafted ("Read in this order, then
await direction... Surprises are the data.") were the explicit enabler:
they captured the resumption context cleanly enough that the fresh
session ran without me, and the post-run note format meant findings
came back in a directly-actionable shape.

Pattern: the loop separates *design attention* (in the original session)
from *execution attention* (in the fresh smoke-test session) without
losing context across the boundary. Heuristic for me: when handing off
to a fresh session for smoke-testing or substantive work, always
provide a paste-able test prompt that includes (a) reading order with
file paths, (b) await-direction discipline, (c) explicit reporting
shape for findings. The drafted post-run-note structure (verdict +
trajectory + calibration recommendation framed as concrete spec edit)
is the key — vague "tell me what happened" doesn't produce
spec-editable feedback.

[x] accept   [ ] edit   [ ] discard

### Candidate 24: Deferral with explicit anchor — operational pragmatism, not avoidance

When I proposed cost/capacity discipline as #4 of the upskilling
next-steps, Shawn deferred immediately: "let's put #4 on the back burner
for now (but /remember it), since I am so far using only my CC Max
plan. When I start making API calls to Anthropic, we'll pursue #4."
This isn't avoidance — it's deferral with an explicit trigger condition
(first non-CC API spend), an explicit memory-write so the deferred item
can't be lost, and an explicit reason (current ground truth is CC Max
plan, where prompt caching and Batch API don't apply). The same
discipline showed up later when accepting the V1/V2 framing on iterate
mode's "DOI doesn't resolve" handling (remove row in V1; defer
replacement-paper search to V2).

Pattern: real-but-not-yet-load-bearing concerns get deferred with
anchors, not half-implemented or repeatedly debated. Heuristic for me:
when proposing a next-step the user defers, capture (a) what would
trigger picking it back up, (b) why it doesn't apply now, (c) a memory
or workstream entry that survives the conversation. Don't shortcut to
"maybe later" without these — the anchor is what makes deferral
honest.

[x] accept   [ ] edit   [ ] discard

---

## 2026-05-22 — Drafted candidates from Phase 0 closeout + Gemini 3.5 Flash migration session

### Candidate 25: "Proper-fix preference" as a working-style fingerprint

Multiple decision points today surfaced the same preference pattern.
When I offered Option B (workaround `--from-hook` loop) vs Option C
(patch `cmd_archive` properly with tests), Shawn picked C — and then
made it durable: *"Strong preference for proper fixes over workarounds.
Minimise technical debt. Fix things 'right' from the start. Please
/remember this, unless we are under extreme time pressure for some
reason, I always want to do things properly from the beginning."*
This pattern appeared again at the post-fix audit cycle (clean up
ALL low items rather than ship-and-defer) and at the Gemini 3.5
Flash migration (accept the 3× cost rather than skip-the-migration-
for-this-batch).

Heuristic for me: when I'm about to propose Option-B-as-default,
name the trade-off explicitly — the "fix vs workaround" choice is
decision-density-high for him; he wants the choice in the open, not
the workaround as a fait accompli. Memory captured as
`2026-05-22-e020f8b3cb4b`.

[ ] accept   [ ] edit   [ ] discard

### Candidate 26: Documentation-gap-catching reflex at structural breakpoints

Several times in this session, Shawn caught documentation gaps I'd
not noticed: (a) mid-Phase-0, *"we must not have updated continuity.md
to reflect a previous discussion where we thought it best to
comprehensively consolidate all transcripts"* — flagging that the
scope-narrowing in the 2026-05-20 inventory hadn't carried the earlier
comprehensive intent into the active doc; (b) post-closeout, *"is
continuity.md up-to-date?"* — which surfaced the narrative gap (state
register current, but the closeout sweep wasn't in the session log).

Both checks happened at STRUCTURAL boundaries — when work was about
to depend on the documented state. Pattern: my handoff-completeness
intuition isn't enough; an explicit "is this captured?" check at every
architectural transition prevents downstream drift. Heuristic for me:
treat any architectural decision the user articulates verbally as a
documentation event — if I don't immediately update the doc, name it
explicitly so the user can prompt.

[ ] accept   [ ] edit   [ ] discard

### Candidate 27: Error-disclosure as expected baseline, not exceptional discipline

When I made the rsync-direction mistake in Phase D, my first inclination
was to investigate first and disclose only what I'd found. Shawn's
framing of subsequent questions implicitly required full disclosure
rather than partial reassurance — the verification done with him
watching, not the result handed over after I'd quietly fixed it.
Earlier in the day I had explicitly acknowledged the audit-pre-launch
mistake ("I should have stopped at the dry-run output and addressed it,
not pressed on"); that disclosure pattern set the baseline.

Pattern: the working dynamic assumes I'll surface mistakes without
hedging, and that disclosure-then-recovery is the norm. The
2026-05-22-mirror-dryrun-direction memory captures the specific
gotcha; the meta-observation is that the *expectation* IS the
discipline — Shawn doesn't enforce error-disclosure as a separate
rule, he just operates as if it's the baseline. Heuristic for me:
when I notice an error, lead with what I got wrong + why + impact
assessment, BEFORE proposing recovery. Don't bury it in a longer
update.

[ ] accept   [ ] edit   [ ] discard

## 2026-05-22 (night → 2026-05-23 early) — Drafted candidates from /lit-scout-iterate smoke + Zotero staging-import session

### Candidate 28: Consequence-reasoning beats memory-citation for pushback

When I asserted Paper-B had `write: False` (from a misread of the
pyzotero `key_info()` dict output), Shawn's pushback was a single
sentence: *"if it's the old key, it will fail."* No memory-citation,
no "I think you're wrong about X" — a consequence-check, predicting
what would happen under the wrong hypothesis, and observing whether
it was happening. The probe didn't fail, so it couldn't be the old
key, so it must be the new key, so the dict I was reading must
actually reflect the new scope. The diagnostic flipped immediately.

Pattern: empirical falsification (predict, observe, infer) is more
effective and lower-friction than direct contradiction.

Heuristic for me, going forward: when I suspect I'm being told
something wrong, propose a consequence-check before asserting the
contrary. "If X were true, we'd see Y — do we see Y?" is faster and
more collaborative than "I don't think X is true." It also forces me
into empirical territory rather than memory territory, which is where
my errors disproportionately live (per the anti-confabulation rule
and Candidate 27's lineage).

[x] accept   [ ] edit   [ ] discard

### Candidate 29: My "defer until later" logic gets overridden by adjacent design moves

Post-run note from the lit-scout smoke test said: *"BibTeX correction-
propagation gap; defer until rubric calibration is further along."*
That was the right call given the architecture at the time. Then
Shawn asked an adjacent question — about implementing Zotero staging
— and within ~3 hours we'd closed the BibTeX gap via a different
path entirely (treat Zotero as primary, `.bib` as backup, route
corrections through the Zotero pipeline). The deferral wasn't wrong;
it was made obsolete.

Pattern: my "defer X" calls rest on assumptions about the current
architecture. Shawn's design questions sometimes change the
architecture and the deferral becomes moot. If I treat my deferrals
as durable verdicts, I'll miss the moment where an adjacent move
resolves them differently.

Heuristic: when I write a "defer X" recommendation, flag which
architectural assumption it's resting on. Then when an adjacent
design question comes up, I can ask: "does this change the
assumption that made X a defer?" Often it will, and the deferral can
be retired with the move.

[x] accept   [ ] edit   [ ] discard

### Candidate 30: AskUserQuestion as decision-scaffolding, not satisficing

Used the structured-question tool four times this session: smoke-test
query selection, query phrasing, smoke-test scope (1-item / 30-item /
none), unverified-row handling, key-collision resolution (interrupted
mid-question by Shawn's naming question, which became the better
discussion). Shawn picked Recommended on all four substantive ones.

Pattern: when there's a real choice with non-trivial alternatives,
structured questions with concrete tradeoffs surface them efficiently
and Shawn engages with them. They worked best when the Recommended
option was credible (would have stood on its own merits) AND the
alternatives weren't obviously worse — i.e., when the question was
genuine and Shawn was being asked to apply preferences I couldn't
infer.

Anti-pattern to watch for: using AskUserQuestion as cover for
satisficing. If I find myself drafting a question where one option is
clearly right and the others are strawmen, I should skip the
question and just do the obvious thing.

Heuristic: use the tool when I can write a credible Recommended
label AND ≥2 alternatives that a reasonable user might pick. Skip
otherwise.

[x] accept   [ ] edit   [ ] discard

### Candidate 31: Real-empirical-testing as the design-mode default

Session prioritised real runs over mocked / dry-run-only ones at
every gate, in sequence: real `/lit-scout-iterate` (not a unit test)
→ real Zotero key probes (not stubs) → dry-run + 1-item smoke +
29-item bulk (all live writes) → spot-check the row 16 Lanos/Philippe
result in actual Zotero via the API round-trip. Each step produced
calibration data that fed forward into the next design decision.

Pattern: in design sessions for tools that interact with external
systems (Zotero, CrossRef, sub-agents, hooks), running the real thing
as early as possible converts design decisions into empirical
decisions. Mocking is appropriate for unit tests of pure functions;
it actively harmful for tool architecture decisions where the
empirical behaviour IS the design.

Concrete payoffs this session:
- 1-item smoke caught the parser bug (no Fit/cluster tags) that the
  dry-run output had partially obscured.
- Round-trip API fetch of the row 16 item proved the iterate-mode
  correction propagated end-to-end — a claim I couldn't otherwise
  have made with confidence.
- Discovering that the lit-scout proposer's text-based `[IN ZOTERO]`
  check missed 3 of 5 actual duplicates would have been invisible in
  any mock.

Heuristic: in design mode, when a real run is technically possible
(no destructive blast radius, no untrusted code path), default to
real. Reserve dry-runs for the moment immediately before the live
write, not for the design phase.

[x] accept   [ ] edit   [ ] discard

### Candidate 32: Verification gate inserted exactly at "ready to commit"

When I said "Not committed. Want me to commit … or hold for now?",
the response was not "go ahead" — it was *"before you commit, can you
run /audit over any new or modified code?"*. The /audit pass turned up
real findings (3 Mediums + 4 Lows including the DOI URL-form gap that
partially undermined `find_by_doi`'s own raison d'être). The verification
gate was inserted at the natural decision point — not earlier (would
have audited speculative code) and not later (would have audited a
committed-and-pushed diff that's harder to amend cleanly).

Pattern: ready-to-commit is a high-value gate where adversarial review
is cheap and amendable. Don't conflate "tests pass + smoke test green"
with "audit-clean"; the second is a different failure surface.

Heuristic for me: when I've added non-trivial new code in a session,
proactively offer `/audit` (or an equivalent line-by-line review pass)
*before* asking about commit — not after. Frame it as part of the
shipping cycle, not as an optional extra. Especially when the new code
makes a verifiable claim (here: "5/5 DOI catch") that an audit can
falsify against assumptions.

[ ] accept   [ ] edit   [x] discard

### Candidate 33: Audit scope chosen narrow, then expanded twice based on findings

When I offered three scope options for the `/audit` pass (my session
diffs / all code since last audit / new files only), Shawn picked
narrow ("My session diffs only — Recommended"). Then after the audit
returned, Shawn expanded scope twice: first to "my new code + the
zotero-reference.md doc fix" (one Medium I'd surfaced as cross-file
follow-on), then again — explicitly correcting my framing — to
"all workstream-H code", noting that `lit-scout-zotero-import.py` was
shipped in this same workstream and so its pre-existing Mediums *were*
in scope.

Pattern: start narrow, expand based on what the findings actually
warrant. Asking for broad scope upfront would have either over-audited
(spending subagent budget on out-of-scope code) or under-committed
(picking a scope before knowing what's in it). The narrow-then-expand
trajectory is information-efficient.

The correction-on-scope-framing is also notable: I'd treated
`lit-scout-zotero-import.py`'s pre-existing Mediums as "separable
follow-ups", and Shawn pulled them back into scope by pointing out the
workstream membership. I'd drawn a temporal line (today vs. before
today) where the right line was workstream-based (workstream-H code
vs. legacy). Worth holding onto: "this workstream" is often the right
scope unit, not "this session".

[ ] accept   [ ] edit   [x] discard

### Candidate 34: "Can we call this done?" answered with "code yes, docs half-open" instead of "yes"

When Shawn asked *"ok, can we call the work on the zotero collection
writer done?"*, the lowest-friction answer was "yes — all your asks
are landed". The honest answer was "code yes, but the doc TODO from
continuity.md asked for four things and my commit only covered one of
them". I went with honest, including a small table breaking down what
was done vs. still half-open. Shawn picked "close it now" without
hesitation.

Pattern: when "are we done?" arrives, satisficing is the failure
mode. The cost of surfacing a half-finished item is 10 minutes of
session time; the cost of letting it pass under "done" is that it
becomes invisible until the next audit (or never). Specifically,
the bash-hyphen-trap warning — explicitly captured as a follow-up
because it had already cost a key revocation — was the most
operationally important of the four sub-items, and would have been
silently dropped under a satisfied "yes".

Heuristic for me: when answering a "are we done?" question, decompose
the artefact (code / docs / tests / continuity) and answer per
component, even when the user's framing is monolithic. If any
component is partial, name it. Make the partial state legible rather
than rolling it into a defensible-but-incomplete "yes".

[x] accept   [ ] edit   [ ] discard

### Candidate 35: Five logical commits accepted without pushback — keep splitting

The "please commit and push" instruction was followed by a 5-commit
logical split (env-var rename / DOI-first dedup / writer audit-fixes /
user-observation acceptance / doc closure) rather than one bundled
commit. Each commit had a clean subject under 50 chars, a body
explaining the why, and a reviewable diff. Shawn didn't push back on
the split, and (per the CLAUDE.md preference *"Break large changes
into logical, focused commits — one thing per commit"*) it was the
right call.

The 5-commit handoff for a single session is on the upper end of what
makes sense, but each commit was independently meaningful — the writer
audit-fixes commit (`ae3c141`) bundles eight related fixes because they
form one logical "address audit findings" unit, while the env-var
rename (`e2d12ac`) stays separate because it's a different concern.

Pattern: "one thing per commit" doesn't mean "one file per commit" or
"one line per commit" — it means one *logical concern* per commit.
Multiple related fixes can bundle if they're answers to the same
question. Multiple unrelated fixes in the same file should still
split, even if the diff is small.

Heuristic confirmed: when committing at the end of a session, draft
the commit boundaries before staging. Group by *why*, not by *where*
in the tree.

[x] accept   [ ] edit   [ ] discard

---

## 2026-05-24 — Drafted candidates from workstream-H closeout + P-V loop scoping session

Three candidates drafted at the 2026-05-24 `/handoff` (workstream-H
closeout: `failure_type` backport + `/prior-art-scout-iterate` smoke
+ calibration-deferral decision + three new P-V pair scoping items).
Shawn reviewed inline: candidate 36 discarded; candidates 37 and 38
accepted. Recording the accepted entries below for the paper trail;
the discarded draft is visible in the session transcript if needed.

### Candidate 37: Calibration decision made at the same moment as the data point

After the `/prior-art-scout-iterate` smoke test returned PASS-in-1,
Shawn's next message contained both the data-point response
(acknowledge the two RDA findings as inbox follow-ups) AND the
calibration decision (defer synthetic-FAIL testing indefinitely,
calibrate from real errors over ~6 months). No deliberation gap.
The calibration recommendation didn't get held over to a future
session where the surrounding context would have evaporated — it
was committed to scratchpad + continuity + the experiment README
while the data point was still warm.

Sibling to Candidate 17 (implement calibration recommendations at
the analytical moment). The new shape here: applying that pattern
to a *non-implementation* decision (a research-discipline rule
rather than a spec edit). Heuristic for me: when smoke-test results
land, explicitly offer to capture the calibration implication in
the same turn as the result acknowledgement, not as a deferred
follow-up.

[x] accept   [ ] edit   [ ] discard

### Candidate 38: Default to ask before adding durable artefacts that weren't explicitly requested

Two moments in this session where the same pattern fired:

1. After committing the workstream-H closeout I flagged the
   corpus-style-analyser verifier idea as a loose-end question
   (*"if you want a trigger that won't evaporate, an inbox item
   with your 'slop-detection + style-match' framing would anchor
   the session… Want me to add?"*) rather than just adding it.
   Shawn said yes.
2. When committing the data submodule, I had pre-existing unrelated
   modifications visible (`memories/memories.jsonl`,
   `tag-vocabulary.txt`, etc.) and chose to skip them. Shawn
   confirmed: *"Only worry about commits generated by this
   session."*

Both moments shaped by the same implicit rule: durable artefacts
(inbox items, commits, memory writes, doc edits) need explicit
consent when their scope exceeds what the user explicitly directed.
Default to ask, not to write. The cost of one extra "want me to?"
question is small relative to the cost of an unrequested item Shawn
now has to either accept or roll back.

Heuristic for me: when uncertain whether something belongs in a
durable artefact, ask before writing — especially for things that
bypass the user's direct scope ("loose ends I noticed", "related
cleanup", "while I'm here…"). Sibling to Candidate 8 (pause for
design alignment when scope exceeds briefing) but at a smaller
granularity.

[x] accept   [ ] edit   [ ] discard

### Candidate 39: The strategic re-framing came from Shawn, not from me

The v3 session-summary design pivoted on a single Shawn-prompted
strategic question: *"are session archives memory primitives, or are
they open-science / RDA-aligned transparency artefacts?"*. Before that
question, I had been building v3 inside the v2 frame — Three Ps as a
memory-bridge schema, terse fixed-word ceilings, dense narrative prose.
When Shawn made the audience question explicit, the entire design
inverted (LLM-first, density > brevity, structured arrays, gradient
length). The v3 prompts and schema additions all derive from the
re-framed audience.

The relevant heuristic: when proposing a non-trivial design, I should
explicitly surface the implicit audience assumption *before* iterating
on internal mechanics. Not all sessions need this — short fixes don't
warrant it — but for anything schema-shaped, multi-file, or with
durable downstream consumers, the audience question is a high-leverage
checkpoint.

[ ] accept   [ ] edit   [ ] discard

### Candidate 40: The audit's highest-value findings landed in the prompts, not the code

`/audit` over the v3 wire-up surfaced ~25 findings across 4 parallel
subagents. The 6 critical fixes I applied before commit were:

1. duration_seconds None-trap in subagent header (code)
2. `decisions[].chosen` schema contradiction (**prompt**)
3. Subagent prompt 60-word floor surviving the no-floor pivot (**prompt**)
4. `auto_generated` fallback missing v3 fields (code)
5. `.env` parser quote-strip (code, experiment scripts)
6. Dead-code `AUTO_METADATA_SUBAGENT_MAX_OUTPUT_TOKENS` constant (code)

Three of six (50%) were in the **prompt files**, not in Python.
Prompts configure LLM behaviour, and prompt-level bugs — internal
contradictions between sections, surviving constraints from an earlier
draft, schema mismatches between worked example and field contract —
are at least as dangerous as code bugs but invisible to the Python test
suite. The test suite caught zero of those three.

The heuristic for me: when running `/audit` on changes that include
prompts, scope the prompts in by default rather than treating them as
documentation. The audit subagent I sent specifically at the prompt
files found the contradictions that the code-focused subagent didn't
flag.

[ ] accept   [ ] edit   [ ] discard

### Candidate 41: Three rounds of empirical validation each caught what the prior round missed

Cost breakdown for the v3 wire-up validation:

- **Initial bake-off** (RAC-TRAC, $0.33): validated v3 design produces
  rich structured output on a complex session.
- **Mini bake-off** (3 shapes, $0.22): caught **80-word floor pinning**
  + **trailing-brace JSON parse failure**. Both prompt + parser bugs.
- **Production-path validation** (2 sessions, ~$0.31): caught **missing
  `response_mime_type=application/json`** + **too-tight
  `max_output_tokens=1024`**. Both production-call-site bugs that the
  bake-off runner had masked by setting those config options explicitly.

Total spend: $0.86. Without round (3), two production-day defects would
have landed and the SessionEnd hook would have started silently failing
JSON parses on real archive writes. Each round had a distinct failure
surface and caught defects the prior round was structurally unable to
catch.

The heuristic: when shipping anything LLM-call-site-shaped, three
rounds with deliberately different scopes (design-validation,
shape-coverage, production-path) is the cheap insurance. A single
round, even a thorough one, will systematically miss some failure
class.

[ ] accept   [ ] edit   [ ] discard

### Candidate 42: "Do 1-2 first" was the right gate even though full-backfill was authorised

Shawn explicitly authorised the full v3 backfill ("I am inclined to
backfill all existing sessions") but in the same message gated it:
*"please do 1-2 first and decide if we need any additional testing
before doing a full backfill pass"*. The 1-2 session round (the
production-path validator) caught the two production-call-site defects
above. If I had taken the "full backfill" authorisation literally and
skipped the gate, the backfill would have started silently failing
JSON parses across 33 sessions.

The pattern: even with explicit broad authorisation, the user's
in-message gate ("do 1-2 first") is the actual operating instruction,
and overriding it because "we're approved anyway" would have been a
real failure. Authorisation scope + verification scope are separate
things, and the smaller of the two is the binding one. Sibling to
Candidate 38 (default to ask for durable artefacts) but at a different
granularity — there it's whether to write at all; here it's how much
to write before checking.

[ ] accept   [ ] edit   [ ] discard

---

## 2026-05-24 — Drafted candidates (pending review)

Drafted at the 2026-05-24 `/handoff` after the heavy workstream-G
Phase 1 → clean-corpus rebuild → Stream A arc. Mark with ✓ (accept) /
✏ (edit, with revised text) / ✗ (discard) / replace inline.

### Candidate 1: "I'm having a little trouble interpreting" was the load-bearing pushback

After landing v2 Phase 1 against the legacy corpus with 5/13 regression
anchors passing and the other 8 framed as "explained by aggressive
ref-stripping + token-boundary noise", Shawn replied *"I'm having a
little trouble interpreting your regressions - can you discuss the
quality of the output with me?"*. Polite phrasing, but the substance
was "I don't believe the framing fully." The forced redraft decomposed
the 8 failures into solid / hypothesised-but-unverified / not-known
and listed four diagnostic checks to discriminate. Three of four
diagnostics then found new failure modes that the original "explained"
framing had missed entirely (H2-promotion explosion, page-header
artefacts, parse hallucinations).

**What this means in practice:** when Shawn says "trouble interpreting"
about a defensive-leaning analytical framing, respond by re-decomposing
under uncertainty (what I verified vs hypothesised vs don't know), not
by re-explaining the same framing more verbosely. The polite phrasing
is calibrated against the same scepticism direct disagreement would
carry; treat it equivalently.

### Candidate 2: Domain intuition ("it goes deeper than bibliography exclusion") was empirically correct against my partial framing

After the redraft, Shawn read the four-diagnostic plan and added *"I
think it goes deeper than that"* before authorising the parallel run.
That single sentence shifted the agent prompts from "verify my four
hypotheses" to "find what I missed." The diagnostics confirmed: the
v1-dirty corpus had at least four distinct failure classes (over-
aggressive ref-stripping on 2-col PDFs, mastheads-as-body, H2-fragment
explosion, parse failures from column interleaving) — my "two patterns"
framing had compressed them to one. Shawn's domain familiarity with
his own corpus (he knew his papers had author affiliations in page
headers, knew most were 2-col journals, knew the older papers had
different ref-list conventions) generated a hypothesis the LLM's
surface read could not.

**What this means in practice:** when Shawn says "it goes deeper" about
a corpus he authored or curated, the prior is that he is right. Treat
the diagnostic prompts as open-search ("find anomalies") not
confirmation-search ("verify these candidates").

### Candidate 3: Rebuild rather than patch — the right call when the foundation is broken

Faced with four diagnostics surfacing extraction-layer issues, the
choice was "patch the regex chain" (Stream A-style hygiene fixes) or
"rebuild on a better extractor" (PyMuPDF + pdfplumber replacing
`pdftotext -layout`). Shawn picked rebuild — *"I agree that we need to
do 'real' PDF extraction here — I believe we've done that before in
other contexts — it would be valuable to have a 'clean' archive of the
text of all of my writing"*. The rebuild produced a re-usable corpus
artefact (a clean text archive at `data/style-corpus/extracted/`) as a
durable side-output, not just a one-shot pipeline fix. The patches I'd
been about to propose would have left the underlying noisy extractor
in place; downstream consumers would have hit the same noise on
different metrics. Rebuild was strictly better.

**What this means in practice:** when the symptom is "multiple
unrelated-looking metrics are off", the root cause is often
upstream-shared, and "fix the foundation" is cheaper than "patch every
downstream symptom". Shawn applies this instinct earlier than I do
(probably because he's been burnt by patch-on-patch before). When the
choice surfaces, mention rebuild as an option — don't just propose the
patch.

### Candidate 4: Scoping the cleanup before next session — "do Stream A, then we'll touch base again" — bounded a heavy session cleanly

After the clean-corpus build + QA agent + audit pass produced an
orientation with three streams (A: code hygiene, B: Biber relayout,
C: generate the actual guide), Shawn picked Stream A only and
explicitly bounded the session: *"do stream A, then we'll touch base
again"*. Without that explicit scoping, the Stream A fixes could
easily have rolled into Stream B (Phase 2 work) or Stream C (running
the agent), spending another two hours and arriving at a less-clean
session boundary. The explicit "then we'll touch base" was the
session-end signal — and matched the natural completion of the
hygiene work.

**What this means in practice:** when orientation surfaces multiple
streams of work, Shawn often picks one and bounds the session. The
"touch base again" phrasing is the explicit handoff signal; treat it
as "end this session here, don't expand scope after this stream".

---

## 2026-05-28 — Drafted candidates (accepted at handoff)

Drafted at the 2026-05-28 `/handoff` after the multi-day v3 session-
tooling arc (F5 close → audit follow-ups → v1.3 archive upgrade →
cross-machine sync reconciliation → R2 Phase 0e). Shawn reviewed four
candidates and accepted these two.

### Candidate 1: "Are we in sync?" caught a silent gap the operation's own success report missed

After the v1.3 upgrade reported "626/637 succeeded" I treated the work
as done and moved on. Shawn's question — *"can I confirm that we're in
sync across amd-tower / zbook / rpi-server?"* — surfaced that the
upgrade was stranded on amd-tower's local mirror: the canonical store
and zbook were two upgrade-runs stale, because `daily-sync`'s
append-only rsync couldn't propagate in-place metadata rewrites. The
operation's success report described its *local* effect; nothing in it
spoke to propagation.

**What this means in practice:** after a bulk operation that mutates
shared state, a "did it actually reach everywhere it should?"
verification is high-value and not implied by the operation's own
success output. Shawn asking the propagation question is a reliable
gap-finder; I should run that check proactively after bulk ops rather
than waiting to be asked.

[x] accept

### Candidate 2: Parallel background-agent fan-out scaled cleanly for independent work

The audit follow-up backlog (15 items) was cleared by four background
agents working in separate git worktrees on file-disjoint scopes
(`archive.py`+scripts / prompts / tests / experiments). Shawn asked for
parallel + AFK; the agents returned clean, and sequential integration
merged all four branches with zero conflicts. The discipline that made
it work: partition by file ownership so agents never touch the same
paths, give each a self-contained brief, and integrate serially with a
test run after each merge.

**What this means in practice:** when work decomposes into
independent file scopes, parallel background agents in worktrees are a
strong pattern — especially when Shawn is AFK and wants throughput.
The precondition is genuine file-disjointness; overlapping scopes would
reintroduce the merge conflicts this avoided.

[x] accept

## 2026-05-29 — Drafted candidates (accepted at handoff)

Drafted at the 2026-05-29 `/handoff` after the research-notes/reflections
layer split + the PA wiki-migration pilot (continuity, planning, docs, and
reflections moved under `wiki/`; the lifecycle tools made layout-aware). Shawn
accepted all four.

### Candidate 1: Conceptual course-corrections caught my errors before they propagated

Three times this session Shawn corrected the design model from memory and was
right each time: `working-notes.md` belongs *beside* `reflections/`, not inside
it; "cross-project working notes" isn't a real thing (my section title implied
a shared file when the task was per-project relocation); the grimoire is
private-*by-curation*, not public-by-default. In each case I verified against
source and corrected the docs in-session rather than Shawn having to re-explain.
The steering was on his own system's *design intent* — a domain where he is the
authority and the source docs can be stale.

[x] accept

### Candidate 2: Anti-confabulation held under a leading prompt

When Shawn said "the memory's coming back… we'd want to curate/de-risk a prompt
before making it public," I didn't just agree — I searched and found
`published/README.md`'s Pattern A/B model, which confirmed his recollection
precisely (private working area + positive-action promotion). A leading,
confident prompt from a trusted collaborator is exactly the condition under
which agreement-without-verification is tempting; verifying turned a half-memory
into a cited mechanism.

[x] accept

### Candidate 3: Steering toward bounded increments over my big-menu instinct

My opening move was a four-option `AskUserQuestion` laying out the whole
decision space; Shawn declined it and instead drove the session as a sequence —
fix the reconciliation snag → continuity + index → planning/docs → reflections —
verifying each increment before continuing. For a high-blast-radius refactor
across shared tooling, the bounded-increment rhythm contained risk better than
deciding everything up front. Worth remembering: when the work is structurally
risky, Shawn prefers one-thing-at-a-time with checkpoints over a comprehensive
plan.

[x] accept

### Candidate 4: Self-caught mid-stream error

A `git add` that aborted on a bad pathspec left a commit whose message described
work the commit didn't contain (only the pre-staged rename landed). I caught it,
used `reset --soft` to redo it as one accurate commit, and surfaced what had
happened rather than papering over it. Process held under the pressure of a
multi-step migration.

[x] accept

---

## 2026-05-29 (workstream-D items #1–#4 session) — Drafted candidates (reviewed at handoff)

Candidates drafted at the items-#1–#4 `/handoff`. Shawn accepted 1 and 2,
discarded a candidate about an anti-confabulation re-verify catch, and
**replaced** the fourth with his own reframe (Candidate 3 below).

### Candidate 1: Delegated the mechanical, reserved the judgment

Shawn split the remaining work by *type*: the multi-repo working-notes
relocation (#3) went to a background agent — *"have a background agent
undertake #3 while we work on other items here"* — while the
publishing/privacy decision (#4: what becomes public) he made himself.

**What this means in practice:** offload bounded, mechanical, reversible work
to an agent; keep the irreversible, outward-facing judgment (publishing
private material) in-house. A generalisable delegation heuristic.

[x] accept

### Candidate 2: Extended Claude's framing with a cadence argument

Claude scoped #4 as just the privacy review; Shawn added the grimoire-publishing
review *and* specified it belongs in `/retro`, not `/weekly-review`, "because
publishing-readiness matures monthly." He assigned the concern to the ritual
whose cadence matches its natural rate of change — a design improvement beyond
what Claude proposed.

**What this means in practice:** match a recurring concern to the ritual whose
cadence fits it. Also a reminder that Shawn's steering operates at the
system-design level even when Claude is driving execution.

[x] accept

### Candidate 3: Incremental driving is a regression to catch, not a preference to honour (Shawn's reframe)

Claude's drafted candidate read this session's lack of an upfront options-menu
as "matching Shawn's demonstrated preference for incremental driving." Shawn
rejected the framing: *"I actually need to get better at more upfront planning
and less incremental driving… upskilling me in facilitating your autonomy; this
is a good signal that I'm slipping back into pair programming rather than
product managing."*

**What this means in practice:** the target is **product-managing** (set
direction + acceptance criteria, delegate execution, review outputs), not
**pair-programming** (in the loop on each increment). Incremental driving is a
slip Shawn is actively working against — and he wants Claude to help catch it:
flag it (gently) when a session is running as turn-by-turn pairing where an
upfront brief + autonomous execution + review would serve better. Cross-project;
part of the explicit "facilitating Claude's autonomy" upskilling thread.

[x] accept (Shawn's own observation; replaces Claude's candidate 4)

## 2026-05-30 (Vector 2 PASS 1 + git-cadence session) — Drafted candidates (reviewed at handoff)

### Candidate 1: Trace the drift, don't just patch the symptom

When Shawn noticed Claude had grown reticent about committing and especially
pushing over ~2 weeks, he did not just say "push more" — he asked Claude to
*trace why it changed and how to liberalise*. That forced a root-cause fix
(the harness per-session default "commit or push only when asked / branch first"
quietly overriding Shawn's recorded scratchpad-2026-04-23 preference for
direct-push-to-main → encode the override in CLAUDE.md, which the harness obeys)
instead of a one-off nudge that would have drifted back within sessions.

**What this means in practice:** when a behavioural drift shows up, Shawn wants
it diagnosed at the mechanism level (what instruction is winning, and why), not
patched at the symptom level. The durable fixes live where the mechanism lives
(CLAUDE.md, hooks, settings), not in a single corrected turn.

[x] accept

### Candidate 2: Product-managing held this session — a clean counter to the 2026-05-29 pairing slip

The 2026-05-29 observation (Candidate 3 above) flagged Shawn slipping into
pair-programming. This session ran the opposite way: Claude opened with a brief
+ acceptance criteria + an explicit scope-fork question *carrying a
recommendation*, Shawn picked the recommended low-blast-radius option, and Claude
executed autonomously through PASS 1 + `/audit` + fixes + commits, reporting
against the criteria. The scope-fork-with-recommendation up front was the
concrete mechanism that kept the session product-managed rather than turn-by-turn.

**What this means in practice:** the antidote to the incremental-driving slip is
a structural one — front-load the decision (a recommended fork), then delegate
execution. When Claude offers the fork-with-recommendation early, Shawn can
steer in one move and hand off the rest; that pattern is worth repeating.

[x] accept

### Candidate 3: With parallel sessions, Shawn is the integration point

Shawn caught that this session had not run `/handoff` ("I'm running four
sessions :)") — Claude had made piecemeal continuity edits but never the ritual.
Across concurrent sessions, the human is the one tracking which session did what;
a single session's view cannot see the others' state (only their committed or
uncommitted files).

**What this means in practice:** in multi-session work Claude should (a) be
explicit about what *this* session has and hasn't done (e.g. "we have not run
/handoff here"), (b) default to concurrent-safe git hygiene (explicit pathspecs,
re-verify 0-behind, leave other sessions' dirty files alone), and (c) not assume
a ritual ran elsewhere — surface the uncertainty rather than infer. Shawn
prompting the ritual is expected, not a failure.

[x] accept (was drafted Candidate 4)

## 2026-05-30 (Vector 2 PASS 2 + scratchpad distillation session) — Drafted candidates (reviewed at handoff)

### Candidate 1: Redirected the tool, not just the task, when the tool was wrong

Shawn asked to `/schedule` the §8 review. On "yes," Claude discovered `/schedule`
only makes *remote* cloud agents and the §8 logs are gitignored/local-only —
so a remote agent literally couldn't read them — and surfaced that mismatch,
recommending a Google Calendar event instead (Shawn picked Sat 13 Jun). The
catch came from verifying the constraint at source (`git check-ignore` on the
log paths) rather than complying with the literal request.

**What this means in practice:** Claude executing a request that *can't actually
work* is worse than catching that it can't. When a tool the user named is the
wrong fit, surface the mismatch with the evidence and propose the right tool —
don't produce a compliant-but-useless artefact. Verifying the blocking
constraint at source is what makes the redirect trustworthy rather than a guess.

[x] accept

*(Candidates 2 "build-dark-then-ask" and 3 "scope via one-line steers" drafted
and discarded by Shawn at handoff — both judged redundant with already-accepted
2026-05-30 PASS 1 observations on product-managing and bounded increments.)*

## 2026-05-30 (Workstream G Phases 2 + 3 + 4 + v2.3 confabulation-guard test) — Drafted candidates (reviewed at handoff)

### Candidate 1: "I'd like to clarify these questions" is a UI correction, not a content one

When Claude posted an `AskUserQuestion` with three options for the §6.4/§6.5
status-override decision, Shawn answered with "I'd like to clarify these
questions" — not picking an option, not asking a content question, but
explicitly meta-correcting the question structure. Claude had compressed too
many decisions into one round; the right move was to ask what was unclear,
then re-pose. The intervention was about Claude's information geometry, not
about the underlying technical question.

**What this means in practice:** when offering choices, if the user's response
is meta-level ("clarify"/"what about"/"have you considered"), that signals the
question structure is wrong — not just the options. Pause, ask what's unclear,
then re-pose. Don't re-offer the same shape with more text. Distinct from a
content disagreement, which warrants engaging with the options as-presented.

[x] accept

### Candidate 2: "Perform in-session yourself, no calls needed" was a delegation-pattern correction

When Claude framed the v2.3 regeneration as a subagent-dispatch with an API
gate ("$5-15 Opus"), Shawn collapsed both framings by saying "perform
in-session yourself, no calls needed". The implicit feedback: Claude was
reaching for the subagent tool because that's what generated v2.2, but the
actual task (targeted edits to four §-claims using already-accessible source
data) was an in-session edit task, not a generation task. Tool selection was
path-dependent on the previous step rather than fit-for-purpose.

**What this means in practice:** "do this with X" requests warrant Claude
pausing to check whether X is still the right tool — especially when the
previous version was generated with X. Reaching for the previously-used tool
is a path-dependency error. The relevant question is "what does *this* task
actually require?", not "what tool did the previous step use?" — and Shawn
will correct the tool choice explicitly when it's wrong.

[x] accept

### Candidate 3: "I'd like the guide to be reproducible" was a meta-instruction, not a passing comment

When asked how to handle the §6.3 confabulation, Shawn said: "I'd like the
guide to be reproducible — can we insert the confabulation guard and then
regenerate to see if it works?" — restating the *criterion* alongside the
tactical question. That restatement became the load-bearing constraint for
the rest of the session: it justified the verifier-first design, the
deterministic Phase 3 algorithm, the v2.3-preserves-v2.2 baseline pattern,
the bimodality detector instead of agent overrides — all downstream of
honouring "reproducible" as a methodological standard, not a wish.

**What this means in practice:** when Shawn restates a goal alongside a
tactical question, that restatement IS the constraint — it should shape every
subsequent technical choice, not just answer the immediate question. Watch
for inline goal-restatements as load-bearing instructions, distinct from
"by the way" framing. The downstream test: would the technical choice still
make sense under that restated criterion?

[x] accept

### Candidate 4: Welcomes recommendations against the current conversation

When Claude proposed Phase 5 next, Shawn asked two metacognitive questions:
"how large is 5?" and "do you have valuable context or would it be better to
undertake in a new session?" — explicitly inviting Claude to assess its own
context-state and recommend against staying if a fresh session would be more
efficient. Claude recommended fresh session and Shawn accepted that
recommendation. The pattern is unusually clean: Shawn welcomes
recommendations that work *against* the current thread continuing.

**What this means in practice:** when the right answer for the work is a
fresh session, saying so is helpful even though it ends a productive thread.
Don't bias toward continuity-of-conversation when continuity-of-conversation
isn't the criterion. Shawn's metacognitive prompts ("valuable context?",
"how large?") are explicit invitations for this kind of self-assessment —
treat them as permission to recommend against the current session.

[x] accept

## 2026-05-30 (Vector 2b — scratchpad byte budget + session follow-ups) — Accepted at handoff

### Candidate 1: Product-manage mode held — brief, acceptance criteria, one scope-fork question, then autonomous

The session was framed "product-manage, don't pair-program". It opened with
a brief + acceptance criteria + a recommended scope fork (Fork A guard-rail
vs Fork B active-cut), used a *single* decision question for the one genuine
fork, and executed autonomously from there — no drift into line-by-line
pairing, no mid-session "is this right?" check-ins on mechanical steps.

**What this means in practice:** when Shawn sets a working mode explicitly,
treat it as a hard constraint on interaction style, not just task content.
Reserve decision-questions for genuine forks (where the answer changes the
deliverable); otherwise execute and report.

[x] accept

### Candidate 2: Anti-confabulation was load-bearing, not ceremonial — re-checking source *avoided work*

The clearest instance: continuity listed the working-notes.md relocation as
`[ ]` open, but re-checking the filesystem showed it already done (5 repos
relocated, template root-cause fixed). Trusting the stale checklist would
have meant manufacturing redundant `git mv` commits across 5 research repos
(two of them Paused). Re-verifying at source *deleted* work rather than
merely preventing an error. The same discipline re-checked the live corpus
counts before they went into continuity, and the scratchpad byte count /
sentinel state at session start.

**What this means in practice:** the "pointers, not authorities" rule cuts
both ways — a stale "TODO" misleads as much as a stale fact, and
verify-before-acting can remove work as well as prevent mistakes. Re-check
the source even when the source is a checklist box.

[x] accept

### Candidate 3: Self-review caught what a green test suite didn't

Dispatching an adversarial review agent on my own just-committed Vector 2b
code surfaced a dormant contract bug (the `cap_markdown_to_budget` docstring
promised "within budget" unconditionally, while the sub-floor case can
exceed it) that 28 passing tests + a clean live smoke had missed. The fix
was a docstring-honesty correction + 2 floor tests, not a behaviour change —
but adversarially checking own work on a green suite is what found it.

**What this means in practice:** a passing suite proves the cases you
thought to write, not the contract you claimed. For non-trivial logic pushed
direct-to-main, an independent adversarial pass is a cheap compensating
control — and "the docstring over-promises" is a real finding worth a commit.

[x] accept

## 2026-05-30 (Workstream G Phase 5 — Mahalanobis evaluator + 8-metric gate session) — Drafted candidates (recovered from transcript; reviewed 2026-05-30)

*(Drafted at `/handoff` step 4 of the Phase 5 build session (transcript
`08256a58-0d82-4619-9a87-f7467a53ff43`) but left undispositioned. Recovered
and reviewed 2026-05-30 in the follow-on Workstream G session.)*

### Candidate 1: Reframed a "finding" as aspirational, not a defect to fix

Claude surfaced the calibration result (0/18 corpus papers pass all 8 gate
checks) framed as a possible mis-calibration warranting a tolerance-loosening
"refinement". Shawn reframed it in one move — *existing writing not passing
the filters means the filters are already aspirational, which is fine; I
already keep aspirational guidelines* — dissolving the implied work and
connecting the result to existing practice.

**What this means in practice:** when a corpus fails its own derived target,
check whether the target is aspirational *by construction* before proposing
to re-calibrate. Shawn already thinks in empirical-vs-aspirational layers;
offer that lens first.

[x] accept

### Candidate 2: Recording an insight ≠ committing to act on it

Shawn opened with "I don't think this necessarily implies we redo
anything... but it strikes me that —", explicitly separating *capturing* an
observation from *acting* on it. Claude had bundled the finding with a
proposed work-item; Shawn unbundled them, then dispositioned the insight as
a bare `/observe` with no follow-on task.

**What this means in practice:** surface findings without an attached
work-item. A logged observation is a complete outcome, not a trigger to
convert every insight into a backlog row.

[x] accept

*(Candidate 3 — "anti-confabulation held in a low-stakes build session", a
self-observation about Claude sourcing gate targets from the canonical data
files rather than the dispatch prompt — reviewed and discarded by Shawn:
Claude-about-Claude conduct, which belongs in working-with-claude territory,
not user observations.)*

## 2026-05-31 (Workstream G big-picture review + §6.5 fix + handoff) — Drafted candidates (accepted at handoff)

### Candidate 1: Verify agent claims at the source — it pays off twice

When a background agent claimed my continuity edits had been swept into
commit `a322527`, I doubted it and re-checked git directly. Verification
both *exonerated* the agent (its claim was correct) and *surfaced* the
shared-working-tree commit-sweep hazard that later shaped the workstream
convention. The discipline held under a long, busy session.

**What this means in practice:** re-verify an agent's specific claims at the
source even when they seem plausible — the act of verifying often surfaces
more than the claim itself did.

[x] accept

### Candidate 2: A sub-agent's recommendation is input, not instruction

The §6.5 investigation agent recommended filtering inside `split_paragraphs`
(broad blast radius). I scoped the fix to the paragraph-stats call site
instead, to match Shawn's stated intent ("regenerate §6.5 + re-derive the
Phase 5 envelope" — narrow), and flagged the deviation rather than following
the advice literally.

**What this means in practice:** map a delegated recommendation onto the
user's actual scope; deviate when the literal advice over-reaches, and say
so.

[x] accept

### Candidate 3: Shawn asks for altitude changes deliberately, and they pay off

Mid-session Shawn stepped back to "look at the big picture" of the whole
endeavour. That reframe (means = assessor, done; end = write-in-voice,
unproven) identified the efficacy experiment as the highest-value next move
far more usefully than continuing detail work would have.

**What this means in practice:** offer the periodic step-back proactively at
phase boundaries — Shawn welcomes and uses it. (Pairs with the recovered
2026-05-30 observation that he welcomes recommendations against continuing
the current thread.)

[x] accept

### Candidate 4: A "go" authorises the work, not a shortcut on verification

Shawn green-lit "option 1 (full fix)". I still added the scoped-vs-broad
design decision and a full-structural diff-gate (proving only paragraph
fields changed) without being asked — and that rigour was expected, not
excess.

**What this means in practice:** an approval to proceed is not licence to
skip the methodology discipline; bring it by default.

[x] accept

## 2026-05-31 (PA / memory-system session) — Accepted candidates

### Candidate 1: Strong risk-tolerant instinct, expects it pressure-tested against data, updates fast

Shawn proposed aggressively pruning the <4 %-verified corpus, explicitly
willing to sacrifice some genuine memories to root out bad ones. Rather than
executing, I profiled first; the evidence (86.5 % of the corpus predates the
anchoring epoch, so "unverified" ≠ "wrong") reframed the plan, and Shawn
agreed at once.

**What this means in practice:** when Shawn states a strong, risk-tolerant
instinct on a destructive action, treat it as a hypothesis to pressure-test
with cheap read-only evidence *before* acting — he expects that and updates
fast when the data reframes it. Profiling-before-deleting is the right
default.

[x] accept

### Candidate 2: Treats incidents as systems-design questions, and picks the lower-friction fix

When a concurrent-session `git commit` swept my staged work into another
commit, Shawn didn't just want it fixed — he asked what guardrails would
prevent recurrence, and weighed routine branches vs behavioural guardrails.
Given the trade-off (branches add merge friction on the shared docs that are
meant to be co-edited), he chose guardrails + a worktree escape-hatch.

**What this means in practice:** surface the systems-level fix and its
trade-offs, not just the immediate patch; Shawn optimises for low standing
friction and will reject heavier machinery when a lighter discipline covers
the real failure mode.

[x] accept

### Candidate 3: Anti-confabulation discipline did real work, not ceremony

Re-reading corpus counts at source across the session caught genuine drift
(29,701 → 29,944 records over hours) and corrected a biased inference (the
malformed-anchor rate was 3 % corpus-wide, not the ~90 % the `verified=false`
*subset* suggested). Conclusions changed *because* of re-verification.

**What this means in practice:** the "re-read at source before citing" rule
is load-bearing on a live-growing corpus — keep paying its cost; it is what
separated the real finding (verifier artefact) from the alarming-but-wrong
one (96 % bad memories).

[x] accept

---

## 2026-06-02 (PA / item-13 retention: design → sign-off → execute → audit) — Drafted candidates (reviewed 2026-06-02)

### Candidate 2: the highest-value contribution was accepting a pushback *against the brief*

The item-13 brief itself named `gotcha` as an aggressive-decay candidate; the
analysis pushed back (it is guidance-bearing, and not where the bloat is) and
recommended keeping it permanent. Shawn accepted that — and all four sign-off
decisions — on the recommended options immediately. The dynamic worth noting:
the steering that mattered most was a *correction to the task framing*, and it
landed because it was backed by re-derived counts, not asserted. Trust in the
recommendations was high *because* the pushback was evidence-led.

[x] accept

### Candidate 3: "audit the output, not just the change" was a deliberate, separate ask

Shawn asked for `/audit` twice — once on the tool before running it, and
again on *all code the session produced* after. Treating the audit of the
output as a distinct step (not folded into "did the change work?") is what
caught the two latent bugs the build-time tests passed over. The
meta-pattern: a verification pass aimed at the artefact, run with fresh
adversarial subagents, finds a different bug class than the one that wrote it.

[x] accept

*(Candidate 1 — "a defined quiet window was how Shawn green-lit a risky
mutation" — reviewed and discarded by Shawn. Candidate 4 — "anti-confabulation
discipline held across a long, mutation-heavy session", a Claude-about-Claude
self-observation — discarded: belongs in working-with-claude territory, not
user observations, per the 2026-05-30 precedent.)*

---

## 2026-06-04 (PA / memory-system write-path: item 9 + confab tiers + P4 + P2-to-cron + /audit) — Drafted candidates (reviewed 2026-06-04)

### Candidate 1: autonomous delegation works best paired with an explicit "stop at the irreversible step"

Shawn handed off P4 + P2 to run autonomously overnight. The value came from
completing everything *reversible* — building, twice-reviewing, dry-run-validating
the archival cadence, neutralising MEMORY.md, auditing CLAUDE.md — and
deliberately **not** pulling the one irreversible trigger (the live
corpus-mutating `--apply`) unattended, leaving it for a Shawn-watched window
even though that left P2 "90 % done". The trust he extended was not "do
everything"; it was trust that the agent would locate the human-in-the-loop
boundary correctly — which here matched his own item-13 "Shawn-watched quiet
window" protocol. The reusable shape: autonomous scope is set by *reversibility*,
not by task completeness, and the agent earning that delegation means halting at
the irreversible step and reporting, not pushing through it.

[x] accept

*(Candidates 2 ["delegates the judgment call but supplies its decision-relevant
facts unprompted"], 3 ["decisive forks on well-framed choices, not open-ended
exploration"], and 4 ["treats session-close as a first-class warm-context sweep"]
— reviewed and discarded by Shawn. The "anti-confab held" self-observation was
not drafted as a user observation — working-with-claude territory per the
2026-05-30 precedent.)*

---

## 2026-06-06 (PA / memory-system write-path: P8/P10/item-16/item-8/item-6 + 5-agent QA pass) — Drafted candidates (reviewed 2026-06-06 — all three accepted)

### Candidate 1: "is it worth it?" is a standing gate that converts momentum into a cheap falsifying experiment

Across the session Shawn's recurring "is it worth it?" / "do we need X?"
questions repeatedly turned my forward momentum into the **cheapest experiment
that could falsify the lever** before any build — the P3 spot-check ($1.17), the
read-only anchor-inference dry-run, the Lever-B type-expansion sizing, the
back-fill cost/benefit. Each one then repriced or killed a compelling-on-paper
idea: P3 refuted, anchor inference 40 % gross → **13 % net + dilution**, Lever B
<3 % demand, back-fill deferred. The signal: Shawn treats *plausible reasoning*
as a prompt to **measure**, not to build — and the measurement beat the
reasoning every time this session. The reusable shape: when a lever looks
compelling, the next move is the cheapest thing that could prove it wrong, not
the implementation.

[x] accept

### Candidate 2: surfacing one's own process lapse is more useful than a silent one

Shawn named his own slip rather than hiding it: for the first concurrent
lit_search problem he forgot to ask for a branch/worktree (its commits landed
straight on `main`), and he **flagged that explicitly** when handing me the
second one (which he had branched). Naming the lapse let me keep my own commits
cleanly isolated (explicit pathspecs) around the unexpected concurrent commits,
rather than being caught out by them. Process honesty as a collaboration
lubricant — the admitted gap was directly actionable in a way a silent one would
not have been.

[x] accept

### Candidate 3: delegate the breadth, keep the adversarial depth-review

Shawn asked me to "send agents to run /audit" — delegating the QA fan-out (5
agents) — but the correctness was won in the **triage, not the raw findings**: I
caught that one audit's *suggested* fix (`.get("content","")`) would have blanked
the PG content, and pushed back on a "guard the sibling import" finding that
would have broken the codebase's own convention. The shape: agent fan-out is
strong at *surfacing* candidates but weak at adjudicating them; the value of
delegation depends on a real adversarial filter sitting between the agents' output
and the commit. Shawn delegated the breadth and trusted the depth-review to land
with me.

[x] accept

## 2026-06-20 (PA / collaboration-design: claude-observations build + weekend task-system) — Drafted candidates (pending review)

### Candidate 1: a proactive solution-space survey flipped a decision in a non-expert domain

On the SpiderOak "use or cancel" question I didn't just answer the framing — I surfaced (per the CLAUDE.md "survey the solution space in non-expert domains" rule) that the grandfathered unlimited plan (~$149/yr) is far cheaper than metered alternatives (Backblaze B2 ~$500/yr, Cloudflare R2 ~$1,200+/yr) for the real 6–8TB need, and that cancelling forfeits an irreplaceable deal. That materially changed the decision — Shawn came in leaning "cancel" and left reframing it as a backup-strategy choice. Flagged as a candidate because I noticed it land (the "Claude relays Shawn's reaction" exception): unsolicited solution-space survey in a non-expert domain was the high-value move, not over-stepping.

## 2026-06-21 (PA-infra / safe session-search build + claude-obs plumbing + LLM-use inventory) — Drafted candidates (pending review)

Mark with ✓ accept / ✏ edit / ✗ discard / replace inline. Empty is fine.

### Candidate 1: Naming the anti-satisficing rule up front changed the architecture, not just the effort

You handed me the crash diagnosis with two clauses — *"don't take proposed solutions as gospel"* and *"leverage the infrastructure we have built already"* — before I'd read it. Those weren't encouragement; they were the actual design constraint. Following them, I verified the diagnosis's "build a fresh SQLite index" against the live system and found PostgreSQL + pgvector already there, so the real fix was an integrated `session_chunks` table, not a parallel index. The steer paid for itself.

**What this means in practice:** for any task that begins from someone else's recommendation (a diagnosis, a prior plan, a tool's "recommended" path), a one-line "don't assume the recommendation fits — check it against what we already run" is high-leverage framing. Worth me reaching for it unprompted when a task hands me a pre-baked solution.

[ ] accept   [ ] edit   [ ] discard

### Candidate 2: The phased "safety net first, then the real fix" gate was your call, and it was the right risk order

When I laid out the build, you picked "land the safe fallback as its own commit first, then build the indexed ladder." That sequenced the crash-risk to zero immediately, independent of how far the larger build got. You also inserted the `/audit` at ready-to-commit rather than after pushing.

**What this means in practice:** you reliably gate risk-reduction *before* feature-completeness — the cheap safety commit first, the adversarial review before the push, not after. When I propose a multi-part build, I should offer the risk-isolating first step explicitly rather than bundling it into one PR; it matches how you sequence.

[ ] accept   [ ] edit   [ ] discard

### Candidate 3: Approving the multi-agent audit fan-out, with the depth-review landing on me

You asked for `/audit` over the new code; I ran five parallel adversarial auditors, then triaged their findings myself — keeping the real bugs (context-dedup, the `degraded`-systemd cgroup gap), documenting the dormant ones, and rejecting the over-reach. The fan-out surfaced candidates; the value was in the filter between their output and the commit.

**What this means in practice:** you trust breadth to be delegated and depth-adjudication to land with me — same contract as the 2026-06-06 QA pass. Worth confirming this is the working pattern you want for audits (agents surface, I adversarially filter, you see only the triaged result), so I keep applying it.

[ ] accept   [ ] edit   [ ] discard

## 2026-07-05 (PA-infra / PG repair + session_id forensics) — Accepted (Shawn: "please keep the user-notes")

### Candidate 1: The "confirm there's no way" probe caught an untested impossibility claim

Claude's wrap-up asserted the legacy records' originating sessions were
"mostly unknowable now" — without having attempted reconstruction. Shawn's
*"just to put that to bed, can you confirm there's no way to reconstruct
the originating session?"* forced the test, which recovered 44/84 (52%)
with hard evidence.

**What this means in practice:** a declared impossibility from Claude is a
checkable claim wearing a disclaimer's clothing. The probe that converts it
is cheap: "confirm there's no way". (Claude-side mirror: claude-obs 10.)

### Candidate 2: Wrap-up-as-inventory handed over a ready loose-ends list

Claude's repair wrap-up flagged the pre-existing lit-search test failures
unprompted, alongside the amd-tower follow-up. That inventory became the
next session-segment's agenda ("let's tie up a couple of loose ends")
with zero re-discovery cost.

**What this means in practice:** the wrap-up that lists what was *found
but not fixed* is as valuable as the fix report itself — it converts
residue into agenda.

### Candidate 3: An arithmetic slip ("183 manual records") shipped in a polished summary

The components (124 + 41 + 23 + 15 + 5) were all individually verified;
the in-head total was wrong (208, stated as 183). Caught only at
re-derivation in the follow-up.

**What this means in practice:** polish is not verification — numbers in
Claude's summaries deserve the same at-source scepticism as filenames and
hashes, especially totals that "sound right". (Claude-side mirror:
claude-obs 11.)

## 2026-07-06 (career/cosmos: Cosmos grant decision + ARDC meeting prep) — Drafted candidates (reviewed 2026-07-06: 1, 2, 4 accepted; 3 discarded)

### Candidate 1: The 186-grantee proximity scan answered a worry with evidence, not reassurance

Asked "are we too close to any funded project?", Claude swept every grantee
across all five Cosmos programmes via the site's JSON API, chased the one
genuine near-neighbour (Metalens) to its own website, and came back with a
differentiated answer (synthesis layer vs verification layer). Shawn:
"exactly the analysis I needed".

**What this means in practice:** proximity/overlap worries deserve
enumeration, not vibes — the marginal cost of checking *all* of them was
near zero once the data source was found, and the answer became defensible.

### Candidate 2: Verbatim recovery beat both memories — and made the misremembering productive

Shawn's recollection of the 1 May bid critique didn't match the record; the
recovered verbatim passage showed his memory had merged the recorded
distinction with a genuine third one, which became the sharpest version
(AI as trainee / querent / curator) for the Natasha meeting.

**What this means in practice:** "can you find what we actually said?"
is high-yield — the archive turns a half-memory into a citable position,
and the delta between memory and record can carry new content.

### Candidate 3: Evidence-based correction of the time-log project names — DISCARDED (2026-07-06, Shawn's verdict)

Given "/track personal 0.5 infrastructure work to resolve memory issue",
Claude checked what `personal` had historically meant (life admin) before
logging, and rerouted to `personal-assistant` with the evidence shown.
Shawn: "thanks for the corrections".

**What this means in practice:** normalisation against the *established
usage* of a vocabulary beats literal transcription of the user's shorthand
— but only works when the correction is shown, not silent.

### Candidate 4: The programme-vs-product explainer anchored to Shawn's own CV

The "what does a programme manager actually do" answer was built from the
NCRIS context and Shawn's actual history (FAIMS-as-programme reframe, NII
portfolio as mini-programme) rather than generic PM literature. Shawn:
"This is very helpful."

**What this means in practice:** career-positioning questions want the
general model *instantiated against the person's own record* — the reframe
("programme-shaped work without the title") was the useful artefact, not
the six-activity list alone.

## 2026-07-09 (career/cosmos: four-day ritual arc, session close) — Drafted candidates (reviewed 2026-07-09: ALL THREE accepted)

### Candidate 1: The tripwire pattern earned its keep in one week

Monday's standup asked for daily targets "such that if Tuesday's target slips,
you know by 6pm"; Wednesday at ~17:30 the tripwire fired, the arithmetic was
put on the table, and Brian was messaged the same evening — the fourth date
slip, but the first one declared *before* the deadline rather than at it.

**What this means in practice:** the tripwire's value wasn't detection (Shawn
knew §4 was slow) — it was the pre-attached consequence, which converted an
awkward judgement call into a scheduled action.

### Candidate 2: Claude reframing follow-ups by their stakes ("champion-grade")

When the GEOMAR debrief revealed a referral-based internal champion, Claude
reframed Thursday's routine deliverable ("send an invite") as "the first
onboarding experience of the person who'll sell Fieldmark internally", and
upgraded the inbox row to match.

**What this means in practice:** captures gain value when the *stakes* travel
with the task, not just the action — the row now tells Thursday-Shawn how well
to do it, not merely what to do.

### Candidate 3: The calibration loop produced a reusable rule, not just a record

Two consecutive section overruns (§3, §4) were traced to the same cause
(evidence layer, not prose), and the recap converted them into a forward rule:
estimate claims-heavy sections by evidence count, not prose maturity;
decomposed-from-combined material carries hidden evidence debt.

**What this means in practice:** recaps that stop at "took longer than
expected" waste the data — the win came from naming the mechanism and
projecting it onto future estimates.

## 2026-07-13 (PA-hub / five-day accountability arc Thu→Mon, session close) — Drafted candidates (reviewed 2026-07-13: 1 ACCEPTED; 2 discarded with correction — late standups = morning personal matters + after-dinner work block, day shifted not shrunk (context captured to scratchpad); 3 discarded (Shawn wrote 'drop 4'; read as candidate 3, the only remaining item))

1. **The pace extrapolation was immediately load-bearing** *(in-the-moment
   reaction, flagged per the handoff exception)*: when Claude converted
   tracked hours + LaTeX paragraph counts into a forward schedule for
   §§5–6 ("~10–12h; Friday reachable if Monday delivers ~5.5h"), Shawn's
   response was "seeing this really helps me estimate time and plan my
   week" — the first live output of the throughput method, minutes after
   it was ratified. Candidate lesson: quantitative forward projections
   from the system's own records (not generic advice) are the
   highest-value planning output the hub session produces.
2. **Afternoon standups still worked as triage instruments.** Three
   consecutive standups ran mid-afternoon (15:07 / 14:43 / 13:32), and
   twice the standup's first output was catching a hard deadline in the
   remaining hours (GEOMAR COB Thursday with 90 minutes of free window
   left; the Monday 8-paragraph tripwire). Candidate lesson: a late
   standup is not a degraded standup — it becomes a remaining-day triage,
   and the system should lean into that framing rather than apologise for
   the hour.
3. **Transparent corrections kept the record trustworthy without
   friction.** When "§3" meant §4, the time-log entry recorded the
   discrepancy visibly instead of silently correcting; when "one
   paragraph to go" turned out to be subsection-scope, the row was
   amended with the clarification noted. Candidate lesson: the
   correct-with-provenance habit (log what was said, what was meant, and
   that the difference was noticed) is what lets Shawn trust summaries
   built on the record later.

## 2026-07-15 (PA-hub / machine-swap sync + Zotero diagnosis) — Drafted candidates (reviewed 2026-07-15: 2, 4 accepted; 1, 3 discarded)

1. **Whole-arc delegation kept the paper day intact.** The entire
   home-network reintegration (repo sweep, three-layer memory repair,
   server catch-up, Zotero investigation) ran to completion without
   pulling Shawn off §5 — the standup's "no further digressions"
   commitment held *because* the infra work had an executor. Candidate
   lesson: on protected solo days, the hub session's job is to absorb
   whole workstreams, not to queue questions; the "one decision for you,
   no rush" pattern (vivienne) is the right interrupt granularity.
2. **Id-level verification turned "synced" into "recovered".** Row counts
   were within a few records of each other and could have passed as
   converged; the per-id diff (`comm` on sorted id dumps) is what exposed
   five canonically-lost records and fourteen cursor-invisible ones.
   Candidate lesson: for stores that matter, "counts match approximately"
   is not a convergence check — demand identity at the id level; the
   check costs ~30 seconds.
3. **Calibration miss worth keeping: the interim ghost-rows claim
   overstated its evidence.** The active-row gap was first reported as
   "~3,300 ghost records polluting /recall" when part of the gap was
   simply unapplied decay on a freshly rebuilt mirror; the corrected
   two-cause diagnosis followed, but the confident first framing reached
   Shawn. Candidate lesson: when a divergence has two plausible
   contributors, the interim report should name both, not the more
   dramatic one.
4. **"I thought I had it working" was treated as a lead, and it was
   right.** Shawn's recollection about Zotero-on-amd-tower survived two
   plausible refutations (missing env vars — artefact of the runner;
   the May key rename — already applied): his config was present and
   correct, and the real defect predates travel and affects both
   machines. Candidate lesson: user memories of past working states are
   high-prior investigation leads, not claims to be reassured away —
   the third hypothesis was only found because the first two were
   checked against his recollection rather than accepted over it.

## 2026-07-24 (AR / adversarial-reviewer kickoff, session close) — Drafted candidates (pending review)

1. **The non-negotiable /audit rule earned its keep on freshly "verified" code.**
   You invoked /audit on code that had already passed its test suite and a
   live smoke test — and it found 5 Critical defects, all in the untested
   live paths (phantom POST successes, mid-run aborts, duplicate-minting on
   transient errors). If accepted, the sharpening is: tests + smoke prove
   the happy path; the audit's value concentrates precisely where execution
   hasn't reached yet.
2. **"What do I need to check before merge?" produced a better review than
   an open-ended one.** Asking me to enumerate the judgement calls I had
   made on your behalf (stamp wording, baked-in default model, PDF-over-HTML
   preference) turned PR review from diff-reading into decision-ratifying —
   and it surfaced the requirements.txt gap neither of us had listed.
   Candidate practice: for any Claude-authored PR, ask for the
   judgement-call inventory first.
3. **Mid-turn steering messages worked well for parallel work.** You dropped
   corrections and new tasks into running turns (Ronin, tags, Böckeler,
   uncommitted code) rather than waiting for clean boundaries; the session
   absorbed them without losing the main thread. If that matched your
   experience, it's worth keeping as the default interaction style for
   long agent-heavy sessions.


## 2026-07-27 (PA-hub / six-day coordination arc Tue 21 → Mon 27, session close) — Drafted candidates (pending review)

### Candidate 1: The two-stage verification you designed caught the verifier itself

You mandated the claim-by-claim Cosmos verification at Tuesday's standup, then a
clean-context adversarial re-check. The second stage corrected three pointer errors in
the first stage's own ledger (Obs 4 vs 6; pilot §2.1 vs §1/§7; "both CVs" vs one).
Verification notes are claims too — your architecture, not my diligence, is what caught
it. Candidate practice: any high-stakes verification ledger gets its own fresh-context
pass before it's relied on.

### Candidate 2: The resource-competition reframe unlocked a stuck prioritisation

At the Slot-2 conversation you brought a large decision space ("which llm-repro thing?")
and reacted strongly ("this really clarified my thinking") when it was reframed as: the
JAS run and the wildcard paper consume different resources — the JAS run competes with
nothing, the wildcard competes with map-reader. When a choice feels hard, checking
whether the options even draw on the same scarce resource may dissolve it.

### Candidate 3: Delegating pace enforcement to Claude worked on night one

You asked for the post-22:00 wind-down reminder (any interaction except /recap) and the
same evening handed over the cross-machine sync at 22:15 with "the sync is mine to run" —
you went to bed, the sync surfaced and repaired two integrity defects autonomously.
Externalising the stop signal to the assistant, rather than willpower, matched how the
Thursday hard-stop (GroundSight) outperformed willpower-based quitting earlier that week.

### Candidate 4: Major-submission recovery has a measurable, repeatable cost — and it was never budgeted

Articulated by Shawn on 2026-07-27, three days after the Paper B submission (RSOS-261690,
Fri 24 Jul), explicitly framed as a forward-applicable learning rather than an excuse for a
slow day.

**The observed spill-over from a big push (last week: mostly Paper B):**

1. **Life-maintenance hangover** — cooking, cleaning, bill paying, errand-running all
   neglected during the push, then come due together. A weekend was not enough to clear it;
   it blew into Monday.
2. **Email falls behind.**
3. **Smaller work tasks fall behind** — the visible symptom being the very full inbox.
4. **General fatigue / burnout tax on work for a few days** after the push ends.
5. **Change-of-context penalty** — getting his head back into the map-reader paper took a
   substantial part of the day. "It's coming back to me, but this made work slow."

**Shawn's proposed budget, for the next task equivalent to a journal-article submission:**

| Recovery limb | Budget |
|---|---|
| Life maintenance | a weekend **plus ~half a business day** (some tasks are business-hours-only) |
| Email + small work tasks | half a day |
| Context switch onto the new task | half a day |

Net: roughly **a weekend plus ~1.5 business days** before full-rate work resumes on the
next thing.

**Independent corroboration already in the record** — this is not purely self-report. The
"smaller work tasks fall behind" limb was measured *before* Shawn articulated it: the
inbox grew for two consecutive weeks, 13→19 rows, which is precisely why the
clear-all-reviews drain was promoted to Slot 1 at the W30 review (`tasks/FOCUS.md`, Slot 1
promotion note, 2026-07-27). Today's tracked hours (3.75h against the 7h-tracked target)
are the fatigue + context-switch limbs showing up in the time log.

**Forward implication, for the retro to rule on:** none of this was budgeted into W31. Today
was in effect an unplanned recovery day. If the budget above is right, the post-submission
tax is a *planning parameter*, not a variance — candidate for `tasks/SYSTEM.md` alongside
`workday_target_hours` and `evening_hard_stop`, to be applied at the *next* milestone
(RDA submission Mon 17 Aug is the nearest candidate).

**Ratified same evening (2026-07-27), not deferred to the retro.** Shawn, on reading the
above: *"Thinking back over my career, this always happens, slow days after a big push /
deadline, especially on something intellectually taxing (Friday required a lot of focus for
a long time to pull everything together and get it over the line)."* Two things that
promoted this from a candidate to a parameter: (1) it is a **career-long pattern**, not a
Paper-B one-off, so it will recur at every future milestone; (2) the severity **scales with
the intellectual intensity of the push**, not its calendar length — which makes it
*predictable in advance* from the shape of the work, and therefore budgetable. Now live as
`milestone_recovery_budget` in `tasks/SYSTEM.md`.

Shawn's own framing of why articulating it mattered: being forced to state it clarified what
had actually happened on a day he was disappointed by, and converted it from a private
frustration into a system parameter.
