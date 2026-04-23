# /recap — End-of-Day Recap

Evening complement to morning `/standup`. Captures what actually happened vs what was
committed, calibrates estimation accuracy, logs time, and plans tomorrow.

Designed as a collaborative end-of-day ritual: review the day's evidence together,
confirm hours, capture the narrative, and set up the next morning's standup.

## Usage

```text
/recap
/recap [summary of what happened today]
```

## Arguments

- *(no arguments)* — Review git activity, then ask the user what happened
- `[summary]` — Use the provided summary as the basis (still run git review)

## Behaviour

### 1. Load Today's State

Read these files:

- `~/personal-assistant/standups/YYYY-MM-DD.md` — Today's standup (for commitments)
- `~/personal-assistant/tasks/FOCUS.md` — Current focus items
- `~/personal-assistant/tasks/backlog.md` — For capturing new items

If no standup exists for today, note it:

```text
No standup found for today. Running recap without commitment comparison.
```

### 2. Review Day's Git Activity

Scan git repos for today's commits to build an evidence base for the recap.
This helps the user reconstruct what they worked on and estimate hours accurately.

**Repo discovery:**

Scan these locations for git repositories on the current machine:

- `~/personal-assistant/` (and its `data/` submodule)
- `~/Code/*/` (all subdirectories that contain `.git/`)

For each repo found, run:

```bash
git -C <repo-path> log --all --after="<yesterday>" --before="<tomorrow>" \
  --format="%h %H %ai %s"
```

**Cross-machine check:** If the current machine is zbook-ubuntu or amd-tower-ubuntu,
also attempt to check the other machine via SSH (timeout 5 seconds). If SSH fails,
note it and continue — the local data is usually sufficient.

```bash
# From zbook, check amd-tower (or vice versa)
ssh -o ConnectTimeout=5 <other-machine> \
  'for d in ~/Code/*/; do [ -d "$d/.git" ] && echo "=== $(basename $d) ===" && \
  git -C "$d" log --all --after="<yesterday>" --before="<tomorrow>" \
  --format="%h %ai %s"; done' 2>/dev/null
```

Only report repos/machines that have commits — skip silent ones.

**Map repo names to project names** using this table (extend as needed):

| Repo directory | Project name |
|---------------|-------------|
| `personal-assistant` | personal-assistant |
| `map-reader-llm` | map-reader-llm |
| `fieldmark-docs-staging` | efn |
| `llm-history-paper` | llm-history-paper |
| `anu-digital-humanities` | anu |
| `cc-session-toolkit` | personal-assistant |

**Present the summary** grouped by project, with commit time ranges:

```text
## Today's git activity

**map-reader-llm** (7 commits, 10:15–17:42)
- fix: verifier config alignment
- feat: thinking-level override
- docs: Flash-Lite evaluation results

**personal-assistant** (4 commits, 08:30–14:20)
- feat: retrieval improvements
- fix: summary backfill

**efn** (1 commit, 16:00)
- fix: template metadata corrections

No activity found on: llm-history-paper
```

Keep commit descriptions brief — group related commits if there are many.

**Important context for hours estimation:** Some projects (especially map-reader-llm)
involve Batch API experiments that run autonomously. High commit volume does not
necessarily mean high active time. When presenting the summary, note the commit
pattern (e.g., "clusters suggest setup → wait → evaluation cycles") to help the
user estimate accurately.

### 3. Gather Actuals

**If no argument provided**, use the git review as a conversation starter:

```text
That's what the git trail shows. How does that map to your day?
Anything not captured in commits — reading, planning, meetings, comms?
```

**If argument provided**, use it as the basis. Cross-reference with the git review
and ask clarifying questions only if something significant is missing or ambiguous.

### 3b. Generate Recap

Use this template. **Tone: reflective, not confrontational.** This is calibration,
not accountability — save that for `/standup`.

```text
---

## End-of-Day Recap

### Committed vs Actual

| # | Committed | Result |
|---|-----------|--------|
| 1 | [from standup Today section] | [what actually happened] |
| 2 | [from standup Today section] | [what actually happened] |

### Parallel work

[Things done outside main commitments — other sessions, conversations, admin.
If nothing, write "None noted."]

### Estimation accuracy

[How accurate were today's estimates? Over-committed? Under-committed?
What expanded beyond expectation? What was faster than expected?
One or two sentences — this builds the calibration record.]

### Key developments

[New information, changed deadlines, decisions made, new items captured.
Things that change the landscape for tomorrow. If nothing, write "No changes."]
```

### 4. Log Time

After reviewing the day together, propose hours by project based on the git
activity and the user's account of their day. Present as a table for confirmation:

```text
## Hours

Based on what you've described:

| Project | Hours | Description |
|---------|------:|-------------|
| map-reader-llm | 3 | H11 config audit, thinking-level experiments |
| personal-assistant | 2 | Retrieval improvements, sessions table |
| efn | 0.5 | Template fixes |
| **Total** | **5.5** | |

Look right? I'll log these via /track.
```

**Guidelines for proposing hours:**

- Be conservative — idle sessions, waiting for experiments, and context-switching
  all reduce active time below what commit timestamps suggest
- Round to nearest 0.5h
- Group related work into one entry per project per day
- If uncertain about a project's hours, ask rather than guess

Once confirmed, append all entries to `~/personal-assistant/reports/time-log.csv`
in one step. Use today's date (not catch-up flag) for same-day logging.

If the user has already logged time today (check the CSV), note it and only
log additional unrecorded hours.

### 5. Append to Standup File

Append the recap to `~/personal-assistant/standups/YYYY-MM-DD.md` after a
separator line (`---`). If the standup file doesn't exist, create it with
just the recap section.

### 6. Generate Work-Log Memory

Write a `progress` memory (30-day decay) summarising the day. Format:

```json
{
  "category": "progress",
  "content": "Work log [YYYY-MM-DD]: [1-2 sentence summary of what was accomplished and any notable developments]",
  "confidence": "high",
  "source": "manual",
  "source_context": "End-of-day recap via /recap",
  "research_tags": ["work-log", "daily-recap"]
}
```

Follow the same JSONL writing protocol as `/remember` — proper JSON escaping,
unique ID, append to `memories/memories.jsonl`.

### 7. Append to Human-Readable Work Log

Append a dated entry to `~/personal-assistant/reports/work-log.md`. This is a
persistent, human-readable record the user can review directly (unlike the
machine memory above, which decays and is for Claude's use).

If the file doesn't exist, create it with a header:

```markdown
# Work Log

Daily record of work accomplished. Generated by `/recap`.
```

Then append an entry in this format:

```markdown

## YYYY-MM-DD (Day-of-week)

**Focus:** [list active focus slot names]

### Done

- [Bullet list of concrete accomplishments from the recap]

### Key developments

[1-2 sentences on new information, changed deadlines, or decisions.
Copy from the recap's "Key developments" section. If none, omit this subsection.]

### Hours

[Always include this section — hours are logged in step 4.
Format: `Project: Xh` (one line per project), plus a total line.]
```

**Important**: Keep entries concise — this file will grow over weeks and months.
Each entry should be scannable in under 10 seconds.

### 8. Plan Tomorrow

This is the bridge between today's recap and tomorrow's standup. Ask:

```text
What's the plan for tomorrow? Any fixed commitments (meetings, deadlines,
teaching) I should know about?
```

Then construct a structured plan together:

```text
### Tomorrow

**Fixed:** [meetings, deadlines, teaching — things with specific times]

**Focus work:**
- [Specific next action from focus slot 1]
- [Specific next action from focus slot 2]

**If time allows:** [lower-priority items, backlog candidates]
```

Use the current FOCUS.md next actions as defaults — if the user doesn't override
them, carry them forward. Update FOCUS.md `Next action` and `Last updated` fields
if the user specifies changes.

Include the Tomorrow section in the standup file (appended after the recap).

### 9. Follow-up capture (probe aggressively)

The single weakest point in the current system is under-capture of
subtasks that surface during work. Shawn's 2026-04-22 self-diagnosis:
Tuesday's ANU overrun traced to two "obvious" subtasks (Week 7 slide
deck, weeks-8–11 plan) that weren't captured three weeks earlier when
the ANU commitment was first scoped. By the time the week arrived,
they resurfaced as "new" work inside an already-committed window. The
corrective rule (`feedback_capture-everything-at-plan-time`): over-capture
at scoping time; consolidate later.

`/recap` is the second-cheapest capture moment (after the in-block
`/track` follow-up prompt). Probe aggressively and specifically, not
with a single generic "anything to add?" question. Ask all four, one
at a time — short answers are fine, "none" is valid, but don't let the
user skip the whole block with one reply.

**Probe 1 — deferred within today's work:**

> During today's work, did anything come up that you deliberately
> pushed off — a subtask, a fix, a refactor, a follow-up — that
> should be captured before it's forgotten?

**Probe 2 — surprises in today's scope:**

> Did today's tasks take longer or shorter than expected because
> of subtasks that weren't in the original plan? If so, those
> subtasks should be in the backlog of the project they surfaced
> in (so future scoping sees them).

**Probe 3 — upcoming commitments implied by today:**

> Did today's work generate any commitments to others (a message
> you owe, a file you said you'd send, a review you offered to
> do)? Those go to `waiting-for.md` with the person named, or to
> inbox with a due date.

**Probe 4 — backlog candidates:**

> Anything broader — new project idea, feature to explore, tool
> to try, paper to read — that came up today and is worth a
> backlog row?

For each probe:
- Short answer ("none" / empty) → move on.
- Specific item(s) → capture immediately to the right file
  (`tasks/inbox.md`, `tasks/backlog.md`, or `tasks/waiting-for.md`).
- Ambiguous/multiple → capture to inbox for later triage; don't
  spend recap time consolidating.

Probes 1 and 2 are the experimentally-prioritised ones (they catch
the "obvious three weeks ago" failure mode). Probes 3 and 4 are the
existing behaviour made explicit.

### 10. Weekly Review Reminder (Thursday/Friday only)

If today is **Thursday**, add after the recap:

```text
Weekly review reminder: Tomorrow is Friday — plan to run /weekly-review
before end of day. Have you been doing weekly reviews?
```

If today is **Friday**, add after the recap:

```text
Weekly review: Have you run /weekly-review this week? If not, now is a
good time — it takes 10 minutes and the data is freshest while the
week is still in your head.
```

Skip this step on all other days.

## Notes

- **Tone is reflective**, not confrontational. `/standup` does accountability;
  `/recap` does calibration and record-keeping.
- The committed-vs-actual comparison is the core value — it builds estimation
  accuracy over time (a self-identified weakness).
- Don't judge expanded scope — just record it. "Fieldmark work expanded from
  1 hour to full day" is data, not a failure.
- The Tomorrow section is critical — it becomes the basis for the next standup's
  "what did you commit to?"
- The git review step grounds the conversation in evidence rather than memory,
  which is especially valuable for multi-project days and catch-up logging.
- If the user runs `/recap` and a recap already exists for today, append a
  second recap with a note: "Second recap — [time]". Multiple recaps in a day
  are fine (e.g., after a mid-day refocus).
