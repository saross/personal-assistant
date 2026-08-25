## Continuity Document — Full Reference

A `continuity.md` is a living, per-project handoff artefact that survives
across sessions. It is the canonical answer to *"where were we, and
what next?"* — read at session start, updated at session end via
`/handoff`. See `handoff-protocol.md` for the update ritual.

### Location

- **Target state:** `<project>/wiki/continuity.md` (alongside other
  wiki-eligible content under the project's `wiki/` directory).
- **Current state:** existing projects use `<project>/planning/continuity.md`.
  Migration to `wiki/` is a one-time per-project move; both paths are
  valid until that lands.

One continuity doc per project. Never delete; always append.

### What continuity.md IS

- Cross-session **state** at handoff: open workstreams, things to verify
  next session, pending tasks, open decisions.
- A short **session log** (reverse-chronological, one paragraph + bullets
  per session). Newest at top.
- An "architectural decisions worth not re-litigating" section — the
  load-bearing innovation. Captures settled choices so the next session
  doesn't re-open them under context pressure.
- A pointer to reference docs that survive across sessions (design docs,
  planning artefacts, audit reports).

### What continuity.md IS NOT

- A daily priority manager — that's `tasks/FOCUS.md` (different audience,
  different cadence).
- An ephemeral in-session task list — use harness `TaskCreate` or scoped
  working files for that.
- A summary of the project's purpose — that's `<project>/CLAUDE.md`.
- A general-knowledge wiki page — that's `notes/<topic>.md`.
- A dump of everything that happened — be selective; if it doesn't
  affect the next session, leave it out.

### Required sections

Order matters — read sequentially, most-load-bearing first:

1. **Active workstreams** — what's currently in flight, by name. Each
   workstream gets a short status block (pointer to deeper docs, current
   phase, key constraints).
2. **Things to verify next session** — concrete, ideally <5-minute
   checks. Carry the failure mode: "if this query doesn't return X, the
   hook didn't fire". Promotes safety after each session-end change.
3. **Pending tasks (cross-session)** — items that survive across
   sessions. Mark `[x]` with date when done; do not delete.
4. **Open decisions / questions** — things needing a deliberate call.
   Resolved decisions move down to the session-log entry where they
   were made.
5. **Architectural decisions worth not re-litigating** — distilled from
   design + planning docs so the next session doesn't reopen settled
   questions. Reference the source doc; one or two sentences per
   decision.
6. **Reference docs** — table of related planning/design docs with
   one-line "read when…" guidance.
7. **Recent session logs** — reverse-chronological. One paragraph + a
   short bullet list of artefacts touched (commits, planning docs,
   scripts) per session.

### Update discipline

Each end-of-session update (via `/handoff`) does five things:

1. **Mark done items in place** — replace `[ ]` with `[x]` + the date
   (e.g. `[x] 2026-05-17 verified`). Never delete.
2. **Update changed items** — if a workstream advanced, update its
   status block in place; don't add a duplicate.
3. **Carry forward open questions** — anything still unresolved stays
   in §4. Anything newly resolved moves down to the session log.
4. **Append a new session log entry** — one paragraph + bullets; most
   recent first.
5. **Save and commit** — `continuity.md` is checked into the project's
   git history; the commit message follows the project's commit
   conventions.

### Length and curation discipline

- **Target: under 300 lines.** When it grows past that, prune the
  session log (move entries older than ~6 weeks to
  `wiki/continuity-archive/`).
- **Curation cost: ~5 minutes per session-close.** I draft the diff
  during `/handoff`; you spot-check.
- **Selective, not exhaustive.** If a session produced nothing
  load-bearing for the next one (e.g. all routine), the session-log
  entry can be a single line — or omitted entirely.

### Anti-patterns to avoid

- Re-litigating decisions in §5. If a decision feels wrong, write a
  new session log entry with the reasoning for changing course — don't
  silently edit history.
- Letting §7 (session logs) bloat. Each entry should be the minimum
  that would let a future reader pick up cold.
- Mixing project-level focus (belongs in `tasks/FOCUS.md`) with
  cross-session state.
- Citing specifics (file paths, commit hashes, config values) without
  re-verifying — continuity docs go stale. Apply the anti-confabulation
  rule from `global-agent-guidance/common.md`: re-read the source before
  citing.

### Where this fits in the artefact map

- **`tasks/FOCUS.md`** — your daily priority manager (different audience)
- **`<project>/wiki/continuity.md`** — this doc, cross-session project state
- **`<project>/wiki/index.md`** — project artefact catalogue (navigation)
- **`<project>/wiki/working-notes.md`** — chronological lab notebook
- **`<project>/wiki/reflections/`** — `/reflect` outputs
- **`~/personal-assistant/notes/<topic>.md`** — cross-project curated knowledge
- **`data/scratchpad.md`** — protocol guardrails / principles
- **Memory corpus** — noisy auto-extracted candidate pool

continuity.md is the *table of contents + current state* page for the
project wiki. It points outward to the other artefacts; it does not
duplicate them.
