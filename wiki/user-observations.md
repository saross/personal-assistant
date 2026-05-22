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

[ ] accept   [ ] edit   [ ] discard

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

[ ] accept   [ ] edit   [ ] discard

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

[ ] accept   [ ] edit   [ ] discard
