## `/handoff` — Session-close ritual

`/handoff` is the end-of-session ritual that produces and updates
several handoff artefacts at the right cognitive moment: when the
session content is still loaded, observations are fresh, and we are
about to lose context.

This is **distinct from `/recap`** — `/recap` is your daily
multi-project priority review (high abstraction, end-of-day, serves
you). `/handoff` is per session-close in a single project (working
state, mid-grained, serves continuity for the next session).

### When to invoke

- Explicit: you say "let's wrap up", "before we close out", invoke
  `/handoff` directly, or otherwise signal session close.
- Cue-based: I recognise session-end signals (substantive work
  complete, you indicate stopping, conversation is winding down) and
  propose: *"Want me to run `/handoff` before we close?"*
- Not after every short session. If nothing load-bearing happened
  (routine cleanup, single quick question), skip.

### Time budget

5–10 minutes of back-and-forth. If it consistently runs longer, the
ritual is doing too much — recalibrate by deferring some steps to
`/weekly-review`.

### The six steps

#### 1. Update `continuity.md`

Following `continuity-protocol.md`:

- Mark done items in place with `[x]` + date
- Update changed items (status blocks for active workstreams)
- Carry forward open questions; move resolved decisions to the
  session log
- Draft a new session-log entry: one paragraph summarising the
  session + bullets of artefacts touched (commits, planning docs,
  scripts)

I draft the diff; you spot-check and accept/edit.

#### 2. Capture observations to `working-notes.md`

If the session produced a useful empirical observation (a measurement,
a confirmed behaviour, a surprise that changes how we'd approach
similar work), draft 1–3 candidate entries for the project's
`wiki/working-notes.md` lab notebook. Format follows the existing
`/observe` skill convention (timestamped, structured).

You decide: accept / edit / discard. Empty is a valid outcome.

#### 3. Flag candidate wiki entries

Scan the session content for material that could feed
`~/personal-assistant/notes/<topic>.md` (cross-project topic notes).
Don't curate now — just **flag for the next `/weekly-review`**:

- Identify clusters: "this session generated material that would fit
  `notes/llm-craft.md`" or "this is a new topic — candidate page
  `notes/<topic>.md`"
- Append a one-line note to `~/personal-assistant/notes/_inbox.md`
  (or equivalent staging file) so the weekly review picks it up
- Do not write the wiki entry now — curation happens at
  `/weekly-review` with the full week's candidates in front of us

This is the deliberate fix for the recap-too-late problem: capture at
session-close, curate at weekly-review.

#### 4. Capture user observations (suggest candidates)

**Draft 2–4 candidate observations** about how we worked together this
session and surface them for review. Useful whether or not a full
`/reflect` has been done — candidates may jog memory, or be directly
right, or just be wrong-but-useful for prompting better ones.

Look for, when drafting candidates:

- Moments where you pushed back productively (or didn't push back when
  you should have)
- Decision-density dynamics — when did the session benefit from your
  steering vs my proposing
- Meta-observations you made about your own working style
- Inflection points where a new lens (e.g. open-science angle in
  2026-05-17) reframed the work
- Whether anti-confabulation discipline held under context pressure

You decide: accept / edit / discard / replace with your own. Empty is
still a valid outcome — but the *drafted candidates* are what makes
this step useful.

Accepted observations land in `wiki/user-observations.md` (per project).
This is your meta-level log about our collaboration, feeding eventually
into `notes/working-with-claude.md` at curation time.

#### 5. Commit and push

**Default: commit and push everything before handoff closes.** Batched
for legibility — group changes by logical area, not by file.

- Default batching pattern: one commit per logical area
  (e.g. design-doc, protocol-doc, continuity, notes). One bundled
  commit only if all changes belong to one logical area.
- Subject line imperative ≤50 chars; body explains what advanced
  and why.
- Push after committing if remote tracking is set up. If push fails
  for non-trivial reasons (rebase conflict, etc.), surface it rather
  than working around — handoff isn't truly closed until the push
  succeeds or the user accepts the deferral.
- Working tree should be clean at handoff-end, except for files
  deliberately left uncommitted.

#### 6. Produce a resume prompt (always runs)

End every `/handoff` with a short, **copy-paste-ready prompt the user can
drop into the next session** to resume smoothly. The user was hand-authoring
this every time; it is now a built-in closer. Display it **last**, in a fenced
block, *after* the commit/push so it can reference the state just landed.

Keep it brief — usually just an orientation plus any carry-forward that is
not obvious from the docs:

- **Orientation:** point at the authoritative continuity / planning doc(s) by
  path, and name the project — e.g. "read `planning/paper-writeup-continuity.md`,
  Session N START-HERE". If the continuity doc already uses a START-HERE beacon,
  reference it so the two stay consistent.
- **Immediate next action:** the one or two concrete things to pick up first.
- **Carry-forward context:** *only* what the next session cannot reconstruct
  from the docs — in-flight state (a running process + PID/ETA), an unresolved
  decision, a gotcha, a "don't re-do X" note. Omit the line if there is nothing.
- **Anti-confabulation:** re-read any path, commit hash, PID, or filename
  before putting it in the prompt (same rule as step 1) — the prompt is only
  useful if its pointers are correct.

This step **always runs**, even for light or verification-only sessions: if
nothing changed, the prompt is just a one-line pointer to the current
continuity doc. The point is that the user never hand-writes the resume prompt
again.

Suggested shape (display in a fenced block so it copies cleanly):

```text
Resume <project>. Read <continuity/planning doc path> (<beacon / section>).
Next: <immediate next action(s)>.
Carry-forward: <key in-flight state / gotcha / decision — omit if none>.
```

### What `/handoff` does NOT do

- It does not curate wiki pages — that happens at `/weekly-review`.
- It does not duplicate `/recap` — daily priorities are your domain.
- It does not modify `FOCUS.md` — different artefact, different
  lifecycle.
- It does not surface memories for review — the auto-extracted memory
  corpus is for the weekly cluster-and-carry, not session-close.

### Adapt to the session

- **Light session** (single quick question, no design work): skip steps
  2–4; just update continuity if there's anything worth noting.
- **Heavy design session** (this one, for example): all five steps
  warranted; expect the full 10 minutes.
- **Verification-only session** (read state, confirm something, leave):
  often no continuity update needed at all.
- **Step 6 (resume prompt) always runs**, regardless of session weight — even
  a light or verification-only session ends with at least a one-line pointer to
  the current continuity doc.

If you're tempted to skip continuity entirely after a heavy session,
stop — that's the highest-cost failure mode. The whole architecture
depends on the handoff doc accurately reflecting state.

### Anti-confabulation reminder

When updating continuity.md, **re-read** any cited specifics
(filenames, line numbers, commit hashes, config values) before
including them in the new session-log entry. The session has been long;
specifics may have drifted in context. Apply the rule from `shared.md`:
re-verify at the source, or say "I'd need to re-read X to be sure."

### Where this fits

`/handoff` is one of two ritual moments that knit the artefact picture
together:

- **`/handoff`** — per session-close, captures fresh observations and
  state
- **`/weekly-review`** — periodic curation, runs cluster-and-carry from
  candidate pools (memory corpus, working-notes, observations) into
  curated wiki pages

Both feed the same downstream artefacts (continuity, working-notes,
wiki) — `/handoff` provides the raw material; `/weekly-review` does
the synthesis.
