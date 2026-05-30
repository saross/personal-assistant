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

## 2026-05-30 (Vector 2 PASS 2 + scratchpad distillation session) — Drafted candidates (pending review)

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

[ ] candidate — accept / edit / discard

### Candidate 2: Built the every-session change dark, reserved the flip as Shawn's call

The PASS 2 cutover "changes every session," so Claude shipped it default-OFF
(byte-identical legacy path, safe to commit and push with zero behavioural
change) and surfaced enabling-on-amd-tower as an explicit go/no-go rather than
flipping it unilaterally. Shawn said GO. Same shape recurred at the commit gate
for the scratchpad distillation (staged, presented, committed only on approval).

**What this means in practice:** for hard-to-reverse or every-session-affecting
actions, the pattern that worked was build-dark-then-ask — get the engine fully
landed and verified behind an OFF flag (so it costs nothing to sit there), then
reserve the single enabling decision for Shawn. He keeps the trigger without the
work being blocked on him.

[ ] candidate — accept / edit / discard

### Candidate 3: Scope grew by one-line additive steers at context-shared moments

The session extended PASS 2 → "the scratchpad needs attention" → "both, distill
first" → "Vector 2b as a focused session", each a single-line decision riding on
work already loaded in context. Claude delivered + proposed-next; Shawn picked.
This is the "opportunistic micro-tasks during context-shared moments" feedback
pattern in action — the bundling was cheap because each extension attached to
the live context rather than starting cold.

**What this means in practice:** when the context is already warm, offering the
adjacent next step (with a recommendation) lets Shawn extend scope in one move.
Keep proposing the next bounded step at each delivery rather than waiting to be
asked — but keep each a real fork he can decline, not a slide into open-ended
work.

[ ] candidate — accept / edit / discard
