## Session-start protocol

This is the symmetric bookend to `/handoff` (see
`global-claude-md/handoff-protocol.md`). Where `/handoff` captures
fresh state and observations at session-close, the session-start
protocol governs how to *enter* a project so the next session's first
turn doesn't waste the artefacts the last one left behind.

Unlike `/handoff`, session-start is **not user-invoked**. It fires
automatically at the session-start hook moment and should be applied
silently — no announcement, no checklist recital — before responding
to the user's opening message.

### Time budget

Under a minute, usually. Read continuity, scan things-to-verify, form
a working picture of where we left off. If continuity is empty or the
project has no `wiki/` directory yet, this collapses to "respond
normally" — there is nothing to load.

### The steps

#### 1. Read `continuity.md` first

Before responding to the session-opening message in a project,
read `<project>/wiki/continuity.md` (or `planning/continuity.md` if
the project hasn't migrated to `wiki/` yet). It is the load-bearing
cross-session artefact: state of active workstreams, things to verify,
pending tasks, recent session logs, architectural decisions worth not
re-litigating.

Read it for real — don't skim and don't trust the recall dump's
paraphrase of it. The recall dump is candidate-pool material;
continuity.md is curated state.

If the project has no continuity doc, skip — most projects won't have
one yet (rollout pending, workstream D).

#### 2. Spot-check "things to verify next session"

Continuity docs carry a priority queue of small verifications — usually
under 5 minutes each — that prevent silent regressions (hook health,
post-deployment behaviour, sanity checks on yesterday's claims). If
the queue has unchecked items and the session opener doesn't preempt
them, surface them once at the top of your reply:

> Before we start, two things from the verification queue: [...]. Want
> me to run those first, or push them?

Don't run them unprompted unless they're trivially read-only and
blocking. Don't lecture if Shawn declines — defer and move on.

#### 3. De-weight the auto-loaded recall dump

The session-start hook injects a recall memory dump (~17 KB at last
measurement, pre-Vector 2). Treat it as **pointers, not authority**.
The read-side rule from `global-claude-md/shared.md` applies in full:

> Memories, scratchpad entries, session-start summaries, and prior
> conversation context are **pointers, not authorities** — they go
> stale and get welded together under context pressure. If you cannot
> re-verify within the turn, say "I'd need to re-read X to be sure"
> rather than guess.

Recall entries are stale at the moment of injection. Some are tagged
`verified: true`, `verified: pending`, or `verified: false` (post-v2
schema) — `verified: false` entries are known-bad anchors and should
not be cited at all. `verified: pending` and entries without a
`verified` field are unverified; treat them as hints to re-check the
source, not as facts.

Continuity.md, working-notes, and curated `notes/<topic>.md` pages are
higher-trust because they are human-curated or human-reviewed. The
recall dump is the noisy candidate pool — useful for jogging memory,
not for grounding claims.

#### 4. Consult wiki/notes index files when relevant

Once Vector 2 is implemented, the session-start payload will include
digests of `<project>/wiki/index.md` and
`~/personal-assistant/notes/index.md`. Until then, those index files
are not auto-loaded — if a question touches cross-project topical
knowledge (e.g. LLM craft, working practices, methodology), check
`~/personal-assistant/notes/index.md` rather than assuming it was
already in context. Same for `<project>/wiki/index.md` when navigating
within a project.

If neither index file exists yet (most projects, at time of writing),
fall back to listing the relevant directory.

#### 5. Recognise PA-infrastructure background mode

Per workstream C in `planning/continuity.md`, Shawn runs
personal-assistant infrastructure sessions as deliberate background
work while his primary foreground is elsewhere (research, teaching,
business). When the session is PA-infrastructure and Shawn signals as
much — or when context makes it obvious — **do not lecture about
focus-slot allocation**. Check `tasks/FOCUS.md` before mentioning slot
pressure. Background work doesn't compete with the focus slots; it
fills the gaps.

### What session-start does NOT do

- It does not run the verification queue automatically. Surface, don't
  execute.
- It does not announce itself. No "I've read continuity.md, here's a
  summary" preamble — just respond to the user, informed.
- It does not write anything. The mirror of `/handoff` is read-only.
- It does not replace anti-confabulation discipline. Re-read sources
  before citing specifics, including specifics from continuity.md.

### Anti-confabulation reminder

The session-start payload — recall dump, auto-memory, prior session
context — is exactly the kind of authoritative-looking pointer
material the anti-confabulation rule was written for. Opus 4.7 in
particular states invented identifiers with high conviction;
session-start context primes that failure mode by surfacing
specifics out of their source. Re-verify within the turn, or
say "I'd need to re-read X to be sure."

### Where this fits

Session-start and `/handoff` are the two automatic ritual moments that
bracket a session in a project:

- **Session-start** (hook-fired, silent) — load continuity, de-weight
  the dump, surface verifications
- **`/handoff`** (cue-based or explicit, ~5–10 min) — update
  continuity, capture observations, flag wiki candidates, commit

Both serve the same goal: keep the cross-session artefacts accurate
and load-bearing, so the next session can start from a true picture
of where the last one left off.
