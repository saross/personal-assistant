# /weekly-review — Weekly Review

The weekly reckoning. Aggregates data from across the system into a scorecard,
surfaces patterns, generates collaborator reports, and asks one strategic question.

Renamed from `/review` on 2026-04-23 to un-shadow Claude Code's built-in
`/review` (PR review). Historical references in `planning/` docs still use the
old name.

## Usage

```text
/weekly-review
/weekly-review this-week
```

## Arguments

- *(no arguments)* — Review the previous Monday-to-Sunday week
- `this-week` — Review the current week so far (with a note that it's partial)

## Behaviour

### 1. Determine Review Period

- Default: previous Monday (00:00) to Sunday (23:59)
- `this-week`: current Monday to today
- If run on a Monday, default covers the week that just ended (yesterday was Sunday)
- Display the date range prominently in the output header

### 2. Aggregate Data

Read these sources and extract data for the review period:

| Source | What to extract |
|--------|----------------|
| `~/personal-assistant/standups/YYYY-MM-DD.md` | Hard questions asked, patterns detected this week, **and "Committed vs Actual" tables (the canonical closure source — `[x] DONE` / `Exceeded` rows are this week's closures)** |
| `~/personal-assistant/tasks/inbox.md` | `[x]` rows where disposition is `→ Done` and the Done date falls in the period — these are inbox-direct closures (small tasks done without ever entering a focus slot) |
| `~/personal-assistant/tasks/FOCUS.md` + data-submodule git log on `tasks/FOCUS.md` | Current state, days in focus, approaching deadlines, **and slot rotations within the period — a rotation implies the previous task closed** |
| `~/personal-assistant/memories/memories.jsonl` | Memories created in period, by category |
| `~/personal-assistant/tasks/inbox.md` | Items currently unprocessed |
| `~/personal-assistant/tasks/waiting-for.md` | Items waiting, any overdue follow-ups |
| `~/personal-assistant/tasks/collaborators.md` | Who gets reports, what projects they care about |

**Git activity:** For each project listed in FOCUS.md (extract from the `Project:` field),
attempt to find the repo and run `git log --oneline --after="YYYY-MM-DD" --before="YYYY-MM-DD"`
to get commit counts and summaries. Common repo locations:

- `~/personal-assistant/` (this repo)
- `~/Code/[project-name]/`
- `~/[project-name]/`

If a repo cannot be found, note it and move on — git data is supplementary.

**Counting completions (canonical closure reconciliation):** Closures land in
multiple primary sources; the weekly review is where they are *consolidated* into
the canonical Completions section. Scan all four sources for the period:

1. **Standup recaps** — every `~/personal-assistant/standups/YYYY-MM-DD.md` in
   the period. In each, parse the "End-of-Day Recap" → "Committed vs Actual"
   table. Rows marked `Done`, `Exceeded`, or with a `[x] DONE` prefix are
   closures. Capture the commitment text + the result narrative.
2. **Inbox-direct closures** — under the post-2026-05-24 inbox-as-tray flow,
   inbox-direct closures are removed from `inbox.md` at closure time and
   surfaced into that day's recap. So they are already captured by source (1)
   above; do not double-count. For the period 2026-02-08 → 2026-05-24, inbox
   `[x] → **Done` rows DID stay in the file — that historical record now lives
   in `~/personal-assistant/tasks/inbox-archive.md`. For weekly reviews
   covering pre-2026-05-24 weeks, grep `inbox-archive.md` for `^- \[x\]` rows
   where disposition is `→ **Done` and the Done date falls in the period. For
   weekly reviews covering 2026-W22 onward, this source is redundant with (1).
3. **FOCUS.md slot rotations** — `cd ~/personal-assistant/data && git log
   --since=... --until=... --oneline -- tasks/FOCUS.md`. Each commit that
   changes a slot's `Started:` date implies the previous task in that slot
   closed. Cross-reference with the standup recap from that day for the task
   name.
4. **Time-log** — `~/personal-assistant/reports/time-log.csv`. Descriptions
   like "Finalised and submitted X" or "Delivered Y" are corroborating
   evidence; do not count standalone, use to disambiguate.

Deduplicate (the same closure may appear in two sources). The reconciled
list IS the Completions section — it is the canonical weekly closure
record. There is no separate `tasks/done/` file to maintain (retired
2026-05-24; see CLAUDE.md).

**Counting focus changes:** Use `cd ~/personal-assistant/data && git log
--oneline -- tasks/FOCUS.md` for commits in the review period. Each commit
that touches FOCUS.md represents a focus change.

**Counting inbox flow** (post-2026-05-24 inbox-as-tray flow):

- **Added in period:** items currently in `inbox.md` with a date-prefix in
  the review period, PLUS rows in `inbox-archive.md` with the same date-prefix
  that were dispositioned within the period (these were added in-period and
  also dispositioned in-period).
- **Processed in period:** for tray-resident items, the date-prefix
  filtering above gives adds; dispositioned-in-period count comes from
  `inbox-archive.md` Killed/Superseded/Consolidated entries dated in the
  period + counts from each downstream destination (new backlog rows
  carrying `(captured ... from inbox)` provenance, new focus-slot
  populations, recap closures). Pragmatic shortcut: count net change in
  `inbox.md` line count, plus rows added to `inbox-archive.md` in the
  period, plus the recap-captured inbox-direct closures from source (1)
  of the closure reconciliation.

**Counting memories:** Read `memories.jsonl`, filter by `created_at` in the
review period. Group by category.

### 3. Load Previous Review (for trends)

Check `~/personal-assistant/reports/weekly/` for the most recent review file
(sorted by filename). If one exists, read its scorecard to populate the Trend column.

- Trend indicators: `+N` (increased), `-N` (decreased), `=` (same), `—` (no prior data)

### 4. Generate Internal Review

Use this template. Match the `standup_tone` from SYSTEM.md.

```text
# Weekly Review — Week of [start date] to [end date]

## Scorecard

| Metric | This week | Trend |
|--------|-----------|-------|
| Items completed | N | [trend] |
| Avg days in focus | N.N | [trend] |
| Focus changes | N | [trend] |
| Inbox items (added/processed) | N/N | [trend] |
| Waiting-for items | N | [trend] |
| Memories extracted | N | [trend] |

## Completions

**This section is the canonical weekly closure record.** Output the reconciled
closure list from step 2. Group by:

- **Slot tasks closed** (from FOCUS.md slot rotations + matching recap row) —
  the high-leverage closes
- **Commitments met** (from recap "Committed vs Actual" — rows not already
  surfaced as slot-task closes)
- **Inbox-direct closures** (small tasks done without ever entering focus)

For each item: item name, project tag, source (which standup/recap or inbox
row), and a one-line outcome. Days-in-focus only applies to slot-task closes.

If nothing was completed: "Nothing completed this week." — don't soften it.

## Focus State

[Current focus items from FOCUS.md, with:
- Days in focus
- Deadline proximity
- Flag anything at escalation_confront_day (7+) or beyond
- Note if next actions are stale or undefined]

## Git Activity

[Commits per project for the week.
Format: "project-name: N commits — [brief summary of changes]"
If no git data available: "No git activity tracked."]

## Patterns

[Aggregate patterns from standups and memories:
- Avoidance patterns (comfortable vs hard work — look for progress memories
  on infrastructure while research items stall)
- Completion patterns (what enabled finishing? Single-threading? Deadlines?)
- Commitment accuracy (stated plans from standups vs actual completions)
- System friction points (system_friction memories from the week)

Be specific. "You committed to X on Monday's standup. By Friday, Y happened instead."
If insufficient data for pattern detection, say so briefly.]

## Waiting For

[Items from waiting-for.md, with age.
Flag any where follow-up is overdue (> 7 days without progress).
If none: omit this section.]

## Hard Question

[One strategic question for the week — NOT a daily tactical question.
This should connect to larger goals and stakes.
Examples:
- "You completed 3 infrastructure tasks and 0 research tasks. Is this leave
  being used for what it's for?"
- "The paper deadline is in N days. At current pace, will you make it?"
- "You said X was blocked. Is it still blocked, or are you avoiding it?"
- "What would this week look like if you were being honest about priorities?"]

## Next Week

What are the 1-3 concrete deliverables for next week?
[Leave this section as a prompt — the user fills it in after reading the review.]
```

### 5. Generate Collaborator Reports

1. **Read** `~/personal-assistant/tasks/collaborators.md`
2. **For each collaborator entry**, extract their name, projects, context, and tone
3. **Filter** the review data to only their projects:
   - Completions on their projects
   - Focus state of their projects
   - Git activity on their projects
   - Relevant waiting-for items
4. **Generate** a report using this template:

```text
# Update for [Name] — Week of [start date] to [end date]

## [Project Name]

### Progress

[What was done this week on their project — completions, git commits, focus time.
Write in the tone specified for this collaborator.
If nothing happened: be honest but professional. "No progress this week due to [reason]."]

### Blockers

[Anything blocking progress on their project, from FOCUS.md's "Blocked by" field
or from waiting-for items related to their project.
If none: "None currently."]

### Next Steps

[What's planned for next week on their project — from FOCUS.md's next action
and any commitments from the review.
Be concrete: "Complete results section draft" not "Continue working on paper."]

### Needs from You

[Anything the user needs from this collaborator — derived from waiting-for items,
FOCUS.md blocked-by, or explicit mentions in standups.
If nothing: "Nothing right now."]
```

5. **Save** each collaborator report to:
   `~/personal-assistant/reports/collaborators/[name-lowercase]-YYYY-WXX.md`

### 6. Save Internal Review

Save to `~/personal-assistant/reports/weekly/YYYY-WXX.md`

Use ISO week numbering (`date +%V` or Python `isocalendar()`).

### 7. Display and Follow-up

1. **Display** the full internal review
2. **List** collaborator reports generated with their file paths
3. **Retro cadence check:** Read `~/personal-assistant/reports/retros/` and find
   the most recent file by filename (YYYY-MM.md format). Compute weeks since
   that retro covers the calendar month with name `YYYY-MM`:
   - **0–3 weeks since end of that month**: no notice.
   - **4–5 weeks since end of that month**: `📋 Retro due — last retro
     covered [Month YYYY]. Run /retro at end of this month.`
   - **6+ weeks (i.e., a calendar month was skipped)**: `⚠ Retro overdue —
     last covered [Month YYYY]; [N] full months have ended since. Run
     /retro this week; cadence target is monthly.`
   If no retros exist at all: `📋 No retros on file. First /retro establishes
   the baseline — run when you have ~30 min.`
4. **Ask:** "Any learnings worth capturing this week?"
   - If yes, offer to route to `/craft` (practical learnings) or `/remember` (context/decisions)
5. **Ask** the user to fill in the "Next Week" section with 1-3 concrete deliverables

## Notes

- The review is not optional. Avoiding the review is itself a data point.
- If data sources are missing (no standups, no completions), report that honestly —
  "No standups this week" is itself information.
- First review will show `—` for all trends. That's fine.
- Collaborator reports use the collaborator's specified tone, NOT the internal
  confrontational tone. Brian doesn't need to hear "you're avoiding this."
- The Hard Question should be genuinely uncomfortable if the data warrants it.
  A week of great progress gets a lighter question.
- Git activity is best-effort. If repos can't be found, skip that section.
- Keep the review factual. Let the data speak. Add interpretation in Patterns
  and the Hard Question, not in the Scorecard.
