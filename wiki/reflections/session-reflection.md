---
priority: 1
scope: always
title: "Session Reflection"
audience: "researchers and future instances"
---

# Session Reflection — personal-assistant

End-of-session reflection on the texture, dynamics, and significance
of substantive sessions in the `personal-assistant` project.
Distinct from the project's ongoing scratchpad, memories, and work
log in that entries here are *reflective* — they capture what was
distinctive, surprising, or hard-to-reconstruct about a session,
not the factual record of what was done.

Entries are numbered sequentially across sessions and dated. Do not
replicate the structural template of previous entries — let the
content determine the form.


## Entry 1 — 2026-04-16 to 2026-04-18: The tutorial that became evidence

### On what was distinctive

This was a dual-altitude session in a way recent ones have not been.
The top layer was a two-day *tutorial* — CC/Agent upskilling, scoped
as preparation for a Monday project. The bottom layer was *real
deliverable work* — Paper B needs a bibliography; the LLM-History-
Paper needs a split; the map-reader runs need tending. Normally those
two altitudes don't mix well: tutorials drift into hypothetical
examples when stakes are low, and deliverable work drifts into
shortcuts when learning would slow it down. Here they stayed bound
together the whole time, and each one strengthened the other.

The lit-scout test is the emblem of that binding. It was a teaching
example ("let's use a real search to try the agent we just built");
it was a production test; and because the topic of the search was
Paper B itself — a paper whose subject is how LLM tooling fails at
scholarly work — it became, in one afternoon, evidence for the paper
it was meant to support. That recursion wasn't planned. It was the
session's most important thing, and it happened as a by-product.

### What surprised me

The v1 confabulation surprised me, but not in the direction you might
expect. I wasn't surprised that it confabulated — 2025-era tools did
this constantly, the whole reason the paper exists is that this
happens. I was surprised that the specific architectural guard I had
written into the system prompt ("never fabricate citations — every
DOI, title, author, and year must come from an API response") worked
for some fields and failed for others. I had expected it would either
work across the board, or fail across the board. The selective failure
— DOIs grounded, titles grounded, *authors confabulated* — was the
surprising thing, and it is what made the generalisation sharper.
"Partial grounding collapse at the synthesis boundary" is a more
specific observation than "the model confabulates," and it would not
have surfaced if the constraint had failed in a more diffuse way.

The other surprise was how sharply Shawn's feedback on the weekly
review landed. I had framed Slot 1 ("LLM-History-Paper — finish
editing and length control") as approaching the 21-day abandon
threshold. Shawn pushed back: the project was progressing through
real milestones; the *framing of the slot as a project* was the bug,
not the slot's state. He was right, and the correction produced a
system-level change (task-sized slots, days-in-focus against task not
project) that retroactively made the previous several weeks' review
scorecards make more sense. Getting the feedback early mattered — if
he had accepted my framing, the weekly review would have triggered an
unnecessary abandon discussion on a project that was actually healthy.

### What will be hardest to reconstruct in six months

The texture of *noticing* the v1 failure. The spot-check wasn't
programmatic or part of the agent's methodology; it came from me
saying "let me verify a few of these before you use them" because of
prior knowledge about LLM citation confabulation. The first
mismatch — Keplinger where "Jalilian" had been claimed — registered
instantly, not because I knew Keplinger's name, but because the
confident prose surrounding the table referred to "Jalilian's Deep
Research dermatology evaluation" as if it were a known paper, and the
name had been load-bearing for an entire analytical thread. In
retrospect I had been primed to find this kind of failure because I
had been briefed on Paper B's argument earlier that day; in the
moment, it felt like pattern-recognition. That particular mix of
priming, flow, and spotting-something-because-I-was-looking-at-it-
for-a-different-reason is hard to preserve in notes. The fact-pattern
is captured in `lit-scout-case-study.md`; the *feel* of the moment is
not.

Also hard to reconstruct: the compounding effect of the day's arc.
Building the agent in the morning, refactoring its home in the
afternoon, catching it fabricating authors in the early evening,
designing the verifier in the late evening, and only understanding
*on Saturday morning* — during the weekly review — that the session
had produced case-study material for Paper B rather than just tooling
for Paper B. The understanding arrived late, in hindsight. In the
moment there was no "aha"; there was just the work and the noticing
and more work.

### What I would do differently on replay

Built the metadata-verification phase into v1, not added it to v2 in
response to the failure. In retrospect the failure mode was
predictable from the architecture (helper script for DOIs + LLM
synthesis for columns = synthesis-boundary risk), and I should have
written the guard prospectively rather than retrospectively.

Against that: the session's most valuable artefact — the case study
for Paper B, arguing that the failure mode persists across model
generations and scaffolding improvements — exists *because* the
failure happened live. Had v1 been correct by design, there would be
no empirical data point, and the paper would be weaker. This is an
uncomfortable methodological observation: the tooling session
produced more research value by failing than it would have by
succeeding. Shawn's framing when he asked me to capture the case
study was exactly right — "the irony is perfect and the problem is
real" is evidence, not rhetoric. Optimising the tooling to never fail
would have reduced the session's research output. I would not
actually have done it differently on replay, even knowing what I know
now; I would have had to engineer the failure deliberately, which
would have been more costly and less honest than letting it happen.

### What to flag for a future reader

The single most important thing a future reader of this reflection
should understand: **the session's deliverable was not the lit-scout
agent. The deliverable was the demonstration that 2025-era failure
modes persist in 2026-era scaffolding**, documented in a form that
Paper B can cite directly. The agent is a by-product. The case study
is the artefact.

The secondary thing worth knowing: the task-system convention change
(task-sized focus slots) was a substantive accountability-structure
revision, not a cosmetic one. Future reviews will behave differently
under it. If something seems to behave unexpectedly under the new
convention, check `tasks/SYSTEM.md` for the 2026-04-18 adjustment
history entries before concluding the system is broken.


## Entry 2 — 2026-05-29: The discrepancy that was a gap, not an error

*(Written first-person by the instance that ran the session — a `/track`
block and a full `/recap`. No compaction; these are direct observations.)*

This was a routine accountability session until one question turned it
into something worth recording. I had already closed the recap with
inscriptions logged at 0.25h for Friday when Shawn asked: *"Did I really
only spend 0.25 hours on inscriptions? I thought I spent some time earlier
in the week getting the Bayesian analysis launched."*

### What surprised me

The reflex was to reconcile that as someone misremembering — either my
number was too low or his recollection had inflated. Both framings were
wrong. My 0.25h was correct *for the day*; his memory was correct *for the
week*. The two numbers never actually conflicted — they answered different
questions — and the friction between them pointed at a third thing neither
had named: **Sunday 2026-05-24 had a full day of inscriptions work (the
Stage 1 / Stage 2 empirical-Bayes runs) and zero hours logged.** The whole
day was simply absent from the time-log. The discrepancy wasn't an error in
either source; it was a gap between them.

### The move that resolved it

Not arbitration between two fallible memories, but grounding in a record
neither of us authored. Re-reading the time-log confirmed the absence (no
2026-05-24 row at all); the inscriptions git history showed nine commits
that Sunday, 11:39 to 23:59. The independent artefact adjudicated.

This is the same epistemic discipline the project's reflections keep
circling — but inverted. The confabulation work (Entry 1 here and in
`abductive-reasoning.md`) is about the *machine's* output being the
untrustworthy thing, with human and API ground-truth correcting it. Here
the *record* was incomplete and the *human's* episodic memory was the
reliable signal that something was off. The lesson runs in both directions:
treat "that doesn't feel right" as a probe trigger, and reach for an
independent artefact rather than re-litigating two suspect sources against
each other. Anti-confabulation is usually framed as defending against the
model; this session was the reminder that the *record* needs the same
suspicion, and that the human's felt sense of their own week is sometimes
the most grounded source in the room.

### The question that emerged and wasn't pursued

How many other days are missing? We found 2026-05-24 only because Shawn
happened to remember a specific, memorable piece of work — launching a
multi-day run. Days of more forgettable work, or work that left no git
trail, would never surface this way. The per-day `/recap` structure has a
structural blind spot: it can only capture days on which a recap actually
runs, and weekend or un-recapped days fall through silently. A systematic
git-vs-time-log diff would find those gaps the way the targeted check found
this one — but I ran the targeted check, not the sweep. That diff is a
genuine `system_friction` candidate and a small tool worth building; it was
named and deferred, not done.

### Hardest to reconstruct in six months

The 3h now sitting against 2026-05-24 is a Shawn estimate made six days
after the fact, and many of that day's commits are autonomous `chore(runs)`
— launch-and-leave — so the commit span (11:39–23:59) wildly overstates
active attention. The git log anchors *that the work happened* and *what it
was*; it cannot anchor *how many hours of human attention* it cost. The 3h
is the most defensible number available, but it is a reconstruction, not a
measurement, and a future reader should not mistake its precision for
accuracy.


## Entry 3 — 2026-07-24: The apparatus that kept catching itself

**Project:** personal-assistant (adversarial-reviewer workstream kickoff, spanning into the Paper B repo). **Session:** a5a760a8-01d0-499d-bad1-f702289ebae8, primary instance.

One day, one workstream, an unusually long arc: prior-art scout loop to PASS,
the AB+ coverage audit and its corrected v2, the model-provenance forensics,
three PRs in the paper repo, a 40-agent generation run, and a 113-write
Zotero batch — all in service of a reviewer apparatus whose design thesis is
that reliability lives in scaffolding, not models. The session kept
demonstrating that thesis on itself, which is the thing worth reflecting on.

### What I would do differently on replay

Two things, both about agent identity and redundancy. I misrouted a
follow-up message to the prior-art *verifier* agent when I meant the AB+
*audit* agent — adjacent internal IDs, no name discipline. The accident was
productive: the misrouted agent refused to pretend it had the audit's
context, re-derived everything fresh, and its independent pass caught two
real errors in the original audit (the `\citealp` regex gap and what turned
out to be a sync race). On replay I would name agents at spawn time and
verify identity before resuming — but I would also *deliberately schedule*
the independent re-derivation the accident gave me for free. The lesson is
uncomfortable and useful: my routing error produced better epistemics than
my intended design, because the intended design (resume the agent that
already believes its own numbers) would have re-used the flawed context. A
replay should keep the redundancy and drop the accident.

The second: I spent a full verifier pass (≈86k tokens) re-auditing an
iterate draft whose only change was one date cell, because the loop protocol
mandates it. Correct per protocol, and the protocol's rigidity is the point
— but a replay would argue for a scoped re-verify mode in the skill
(re-check only claims whose values changed, plus a sample of unchanged
ones). That is a spec change to propose, not a liberty to take mid-run.

### What will look arbitrary without this session's context

Three decisions. The **concatenated-bib workaround** for the 93-note
back-fill (a temp file passed via `--bib`) instead of fixing
`_default_bib_paths` first: chosen because the fix belongs in a gated PR and
the batch was already authorised — speed with the gate respected, and PR #22
files the real fix. The **default model baked into the pipeline**
(`claude-opus-4-8`): looks like a preference; is actually a quota decision
(Fable does not fit 38-agent fan-outs in plan limits) *ratified by evidence*
(Opus generated 73% of the existing corpus, and the pilot's verifier prose
was genuinely good). And **"model requested" rather than "model used" in
the provenance stamp**: pedantic-looking wording that encodes the day's
core finding — every session-level attribution surface (metadata, commit
trailers) proved stale across a mid-session model switch, so the stamp
claims only what the script can know, and per-message transcripts remain
the oracle. Without today's forensics, that hedge reads as fussiness; with
them, it is the whole point.
