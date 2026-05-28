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

